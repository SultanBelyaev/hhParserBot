from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request

from app.config import settings
from app.database import Base, engine
from app.db_migrations import migrate_schema

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.session_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    migrate_schema()

    app.state.bot_application = None
    app.state.bot_startup_error = None
    if settings.should_use_telegram_webhook:
        from app.bot.runtime import start_telegram_webhook, stop_telegram_webhook

        try:
            app.state.bot_application = await start_telegram_webhook()
        except Exception as exc:
            app.state.bot_startup_error = str(exc)
            logger.exception("Telegram webhook failed to start")

    yield

    if app.state.bot_application is not None:
        from app.bot.runtime import stop_telegram_webhook

        await stop_telegram_webhook(app.state.bot_application)


app = FastAPI(
    title="HH Parser AutoApply",
    description="Автоотклики hh.ru — управление через Telegram-бота",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "service": "hh-parser",
        "ui": "telegram",
        "health": "/api/health",
    }


@app.get("/api/health")
def health(request: Request):
    import time

    bot_status = "not_configured"
    bot_mode = "none"
    if settings.telegram_bot_token.strip():
        if settings.should_use_telegram_webhook:
            bot_mode = "webhook"
            if getattr(request.app.state, "bot_application", None):
                bot_status = "running"
            elif getattr(request.app.state, "bot_startup_error", None):
                bot_status = f"failed: {request.app.state.bot_startup_error[:120]}"
            else:
                bot_status = "starting"
        else:
            bot_mode = "polling"
            hb = settings.bot_heartbeat_file
            if hb.exists():
                age_sec = time.time() - hb.stat().st_mtime
                bot_status = "running" if age_sec < 180 else f"stale ({int(age_sec)}s ago)"
            else:
                bot_status = "no_heartbeat"
    allowed = settings.telegram_allowed_user_ids.strip()
    return {
        "status": "ok",
        "mode": "telegram-bot",
        "bot": bot_status,
        "bot_mode": bot_mode,
        "webhook_url": settings.telegram_webhook_url or None,
        "telegram_allowed_user_ids_set": bool(allowed),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    bot_app = getattr(request.app.state, "bot_application", None)
    if bot_app is None:
        raise HTTPException(status_code=503, detail="Telegram webhook not configured")
    from app.bot.runtime import enqueue_webhook_update

    payload = await request.json()
    await enqueue_webhook_update(bot_app, payload)
    return {"ok": True}
