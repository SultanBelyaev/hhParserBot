"""Telegram bot lifecycle for Railway webhook mode."""
from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.ext import Application

from app.bot.handlers import build_application
from app.config import settings

logger = logging.getLogger(__name__)


def touch_heartbeat() -> None:
    settings.bot_heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    settings.bot_heartbeat_file.write_text(str(time.time()), encoding="utf-8")


async def start_telegram_webhook() -> Application:
    url = settings.telegram_webhook_url
    if not url:
        raise RuntimeError(
            "Webhook URL не задан. Сгенерируйте домен в Railway (Networking → Generate Domain) "
            "или укажите PUBLIC_URL=https://ваш-домен.railway.app"
        )

    app = build_application()
    await app.initialize()
    await app.start()
    await app.bot.set_webhook(url=url, drop_pending_updates=True)
    touch_heartbeat()
    logger.info("Telegram webhook active: %s", url)
    return app


async def stop_telegram_webhook(app: Application) -> None:
    await app.bot.delete_webhook()
    await app.stop()
    await app.shutdown()
    logger.info("Telegram webhook stopped")


async def enqueue_webhook_update(app: Application, payload: dict) -> None:
    update = Update.de_json(payload, app.bot)
    if update is not None:
        await app.update_queue.put(update)
        touch_heartbeat()
