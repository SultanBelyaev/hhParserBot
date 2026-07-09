from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request

from app.config import settings
from app.db_init import init_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.session_file.parent.mkdir(parents=True, exist_ok=True)
    init_database()

    if settings.should_use_telegram_webhook:
        from app.bot.runtime import schedule_bot_boot

        schedule_bot_boot()

    yield

    if settings.should_use_telegram_webhook:
        from app.bot.runtime import shutdown_bot_runtime

        await shutdown_bot_runtime()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

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


@app.get("/api/health/live")
def health_live():
    """Fast liveness probe for Railway — must not block on bot init."""
    return {"status": "ok"}


@app.get("/api/health")
def health():
    from app.bot.runtime import get_bot_status

    bot_status = "not_configured"
    bot_mode = "none"
    bot_username = None
    bot_error = None
    info: dict = {}

    if settings.telegram_bot_token.strip():
        if settings.should_use_telegram_webhook:
            bot_mode = "webhook"
            info = get_bot_status()
            bot_status = info["status"]
            bot_username = info["username"]
            bot_error = info["error"]
        else:
            import time

            bot_mode = "polling"
            hb = settings.bot_heartbeat_file
            if hb.exists():
                age_sec = time.time() - hb.stat().st_mtime
                bot_status = "running" if age_sec < 180 else f"stale ({int(age_sec)}s ago)"
            else:
                bot_status = "no_heartbeat"

    allowed = settings.telegram_allowed_user_ids.strip()
    payload = {
        "status": "ok",
        "mode": "telegram-bot",
        "bot": bot_status,
        "bot_mode": bot_mode,
        "bot_username": bot_username,
        "webhook_url": settings.telegram_webhook_url or None,
        "telegram_allowed_user_ids_set": bool(allowed),
    }
    if bot_error:
        payload["bot_startup_error"] = bot_error[:200]
    if settings.should_use_telegram_webhook:
        payload["updates_processed"] = info.get("updates_processed", 0)
        payload["last_update_id"] = info.get("last_update_id")
        payload["last_update_user_id"] = info.get("last_update_user_id")
        payload["last_update_text"] = info.get("last_update_text")
        payload["webhook_registered_url"] = info.get("webhook_registered_url")
        payload["webhook_expected_url"] = info.get("webhook_expected_url")
        payload["webhook_url_ok"] = info.get("webhook_url_ok")
        payload["webhook_pending_updates"] = info.get("webhook_pending_updates")
        if info.get("webhook_last_error"):
            payload["webhook_last_error"] = info.get("webhook_last_error")
    return payload


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    import asyncio

    from app.bot.runtime import ensure_telegram_bot, process_webhook_update

    logger.info("Webhook POST received")
    try:
        bot_app = await asyncio.wait_for(ensure_telegram_bot(), timeout=120)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=503, detail="Telegram bot startup timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = await request.json()

    async def _run_update() -> None:
        try:
            await process_webhook_update(bot_app, payload)
        except Exception:
            logger.exception("Failed to process Telegram webhook update")

    asyncio.create_task(_run_update())
    return {"ok": True}
