from contextlib import asynccontextmanager
import logging
from pathlib import Path

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
async def health():
    from app.bot.runtime import get_bot_status, refresh_webhook_status

    bot_status = "not_configured"
    bot_mode = "none"
    bot_username = None
    bot_error = None
    info: dict = {}

    if settings.telegram_bot_token.strip():
        if settings.should_use_telegram_webhook:
            bot_mode = "webhook"
            info = await refresh_webhook_status()
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
    token = settings.telegram_bot_token.strip()
    bot_id = token.split(":", 1)[0] if token and ":" in token else None
    payload = {
        "status": "ok",
        "mode": "telegram-bot",
        "bot": bot_status,
        "bot_mode": bot_mode,
        "bot_username": bot_username,
        "bot_id": bot_id,
        "webhook_url": settings.telegram_webhook_url or None,
        "telegram_allowed_user_ids_set": bool(allowed),
    }
    if bot_error:
        payload["bot_startup_error"] = bot_error[:200]
    if settings.should_use_telegram_webhook:
        payload["updates_processed"] = info.get("updates_processed", 0)
        payload["webhook_posts_received"] = info.get("webhook_posts_received", 0)
        payload["last_update_id"] = info.get("last_update_id")
        payload["last_update_user_id"] = info.get("last_update_user_id")
        payload["last_update_text"] = info.get("last_update_text")
        if info.get("last_handler_error"):
            payload["last_handler_error"] = info.get("last_handler_error")
        payload["webhook_registered_url"] = info.get("webhook_registered_url")
        payload["webhook_expected_url"] = info.get("webhook_expected_url")
        payload["webhook_url_ok"] = info.get("webhook_url_ok")
        payload["webhook_pending_updates"] = info.get("webhook_pending_updates")
        if info.get("webhook_last_error"):
            payload["webhook_last_error"] = info.get("webhook_last_error")

    db_path = settings.database_url.replace("sqlite:///", "", 1) if settings.database_url.startswith("sqlite:///") else settings.database_url
    db_file = Path(db_path) if db_path else None
    campaigns_count = None
    if db_file and db_file.exists():
        try:
            from app.bot.services import list_campaigns

            campaigns_count = len(list_campaigns())
        except Exception:
            campaigns_count = None
    payload["database"] = {
        "url": settings.database_url,
        "path": str(db_file) if db_file else None,
        "on_volume": str(db_file).startswith("/data/") if db_file else False,
        "exists": db_file.exists() if db_file else False,
        "size_bytes": db_file.stat().st_size if db_file and db_file.exists() else 0,
        "campaigns_count": campaigns_count,
        "session_exists": settings.session_file.exists(),
    }
    return payload


@app.post("/api/bot/reregister-webhook")
async def reregister_webhook_endpoint():
    from app.bot.runtime import reregister_webhook

    try:
        info = await reregister_webhook()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "bot_username": info.get("username"),
        "webhook_registered_url": info.get("webhook_registered_url"),
        "webhook_pending_updates": info.get("webhook_pending_updates"),
        "webhook_last_error": info.get("webhook_last_error"),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    import asyncio

    from app.bot.runtime import ensure_telegram_bot, process_webhook_update, record_webhook_post

    record_webhook_post()
    logger.info("Webhook POST received")
    try:
        bot_app = await asyncio.wait_for(ensure_telegram_bot(), timeout=120)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=503, detail="Telegram bot startup timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = await request.json()
    try:
        # Await so reply_text completes before Telegram closes the webhook request.
        await asyncio.wait_for(process_webhook_update(bot_app, payload), timeout=55.0)
    except asyncio.TimeoutError:
        logger.error("Telegram webhook update timed out after 55s")
    except Exception:
        logger.exception("Failed to process Telegram webhook update")
    return {"ok": True}
