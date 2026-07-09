"""Telegram bot lifecycle for Railway webhook mode."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from telegram import Update
from telegram.ext import Application

from app.bot.handlers import build_application
from app.config import settings

logger = logging.getLogger(__name__)

STEP_TIMEOUT_SEC = 45


@dataclass
class BotRuntime:
    application: Application | None = None
    error: str | None = None
    task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_update_id: int | None = None
    last_update_user_id: int | None = None
    last_update_text: str | None = None
    updates_processed: int = 0


_runtime = BotRuntime()


def touch_heartbeat() -> None:
    settings.bot_heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    settings.bot_heartbeat_file.write_text(str(time.time()), encoding="utf-8")


def get_bot_status() -> dict:
    if _runtime.application is not None:
        username = _runtime.application.bot_data.get("username")
        return {
            "status": "running",
            "username": f"@{username}" if username else None,
            "bot_id": _runtime.application.bot_data.get("bot_id"),
            "error": None,
            "updates_processed": _runtime.updates_processed,
            "last_update_id": _runtime.last_update_id,
            "last_update_user_id": _runtime.last_update_user_id,
            "last_update_text": _runtime.last_update_text,
        }
    if _runtime.error:
        return {
            "status": f"failed: {_runtime.error[:120]}",
            "username": None,
            "error": _runtime.error,
            "updates_processed": _runtime.updates_processed,
            "last_update_id": _runtime.last_update_id,
            "last_update_user_id": _runtime.last_update_user_id,
            "last_update_text": _runtime.last_update_text,
        }
    if _runtime.task is not None and not _runtime.task.done():
        return {"status": "starting", "username": None, "error": None}
    return {"status": "starting", "username": None, "error": None}


async def start_telegram_webhook(*, for_polling: bool = False) -> Application:
    url = settings.telegram_webhook_url
    if not for_polling and not url:
        raise RuntimeError(
            "Webhook URL не задан. Сгенерируйте домен в Railway (Networking → Generate Domain) "
            "или укажите PUBLIC_URL=https://ваш-домен.railway.app"
        )

    logger.info("Building Telegram application...")
    app = await asyncio.to_thread(lambda: build_application(for_polling=for_polling))

    logger.info("Initializing Telegram application...")
    await asyncio.wait_for(app.initialize(), timeout=STEP_TIMEOUT_SEC)

    if for_polling:
        logger.info("Starting Telegram application (polling)...")
        await asyncio.wait_for(app.start(), timeout=STEP_TIMEOUT_SEC)
    else:
        logger.info("Telegram application initialized (webhook uses process_update)")

    if not for_polling:
        logger.info("Registering Telegram webhook: %s", url)
        await asyncio.wait_for(
            app.bot.set_webhook(url=url, drop_pending_updates=True),
            timeout=STEP_TIMEOUT_SEC,
        )

    touch_heartbeat()
    me = await asyncio.wait_for(app.bot.get_me(), timeout=STEP_TIMEOUT_SEC)
    app.bot_data["username"] = me.username
    app.bot_data["bot_id"] = me.id

    expected = settings.telegram_expected_username.strip().lstrip("@")
    if expected and me.username != expected:
        raise RuntimeError(
            f"Неверный TELEGRAM_BOT_TOKEN: ожидался @{expected}, "
            f"получен @{me.username}. У каждого Railway-проекта должен быть СВОЙ бот от @BotFather."
        )

    if not for_polling:
        info = await app.bot.get_webhook_info()
        if info.url and info.url != url:
            logger.warning("Webhook был %s, перерегистрируем на %s", info.url, url)

    logger.info(
        "Telegram bot ready: @%s (id=%s) webhook=%s",
        me.username,
        me.id,
        url if not for_polling else "polling",
    )
    return app


async def stop_telegram_webhook(app: Application) -> None:
    try:
        await app.bot.delete_webhook()
    except Exception:
        logger.exception("Failed to delete Telegram webhook")
    if app.running:
        await app.stop()
    await app.shutdown()
    logger.info("Telegram webhook stopped")


async def _boot_bot() -> None:
    try:
        _runtime.application = await asyncio.wait_for(
            start_telegram_webhook(),
            timeout=STEP_TIMEOUT_SEC * 4,
        )
        _runtime.error = None
    except Exception as exc:
        _runtime.application = None
        _runtime.error = str(exc)
        logger.exception("Telegram bot failed to start")


def schedule_bot_boot() -> None:
    if not settings.should_use_telegram_webhook:
        return
    if _runtime.task is not None and not _runtime.task.done():
        return
    _runtime.error = None
    _runtime.task = asyncio.create_task(_boot_bot())
    logger.info("Scheduled Telegram bot startup")


async def ensure_telegram_bot(*, wait: bool = True) -> Application:
    if _runtime.application is not None:
        return _runtime.application
    if _runtime.error and (_runtime.task is None or _runtime.task.done()):
        raise RuntimeError(_runtime.error)

    async with _runtime.lock:
        if _runtime.application is not None:
            return _runtime.application
        if _runtime.task is None or _runtime.task.done():
            schedule_bot_boot()
        if wait and _runtime.task is not None:
            await _runtime.task
        if _runtime.application is not None:
            return _runtime.application
        raise RuntimeError(_runtime.error or "Telegram bot is not ready yet")


async def shutdown_bot_runtime() -> None:
    if _runtime.task is not None and not _runtime.task.done():
        _runtime.task.cancel()
        try:
            await _runtime.task
        except asyncio.CancelledError:
            pass
    if _runtime.application is not None:
        await stop_telegram_webhook(_runtime.application)
        _runtime.application = None


def _describe_update(update: Update) -> str:
    if update.message:
        user = update.effective_user
        uid = user.id if user else "?"
        text = update.message.text or update.message.caption or f"[{update.message.content_type}]"
        return f"user={uid} text={text!r}"
    if update.callback_query:
        user = update.effective_user
        uid = user.id if user else "?"
        return f"user={uid} callback={update.callback_query.data!r}"
    return f"type={update.update_type}"


async def process_webhook_update(app: Application, payload: dict) -> None:
    update = Update.de_json(payload, app.bot)
    if update is None:
        logger.warning("Webhook payload did not decode to Update")
        return

    _runtime.last_update_id = update.update_id
    _runtime.last_update_user_id = update.effective_user.id if update.effective_user else None
    if update.message and update.message.text:
        _runtime.last_update_text = update.message.text[:120]
    elif update.callback_query:
        _runtime.last_update_text = update.callback_query.data

    logger.info("Processing update %s (%s)", update.update_id, _describe_update(update))
    await app.process_update(update)
    _runtime.updates_processed += 1
    touch_heartbeat()
    logger.info("Processed update %s", update.update_id)
