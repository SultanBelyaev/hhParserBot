"""Уведомления о прогрессе запущенных кампаний."""
from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application

from app.services.worker import campaign_worker

from app.bot import services as bot_services
from app.bot.messages import format_campaign_finished, format_progress_update

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 90
_tasks: dict[int, asyncio.Task] = {}


async def _poll_campaign(
    app: Application,
    *,
    chat_id: int,
    campaign_id: int,
    message_id: int | None,
) -> None:
    last_processed = -1
    try:
        while True:
            campaign = await asyncio.to_thread(bot_services.get_campaign, campaign_id)
            if campaign is None:
                return

            if not campaign_worker.is_running(campaign_id) and campaign.status != "running":
                text = format_campaign_finished(campaign)
                await app.bot.send_message(chat_id=chat_id, text=text)
                return

            if campaign.processed_count != last_processed:
                logs = await asyncio.to_thread(bot_services.campaign_logs, campaign_id, 1)
                last_title = logs[0].vacancy_title if logs else None
                text = format_progress_update(campaign, last_log_title=last_title)
                if message_id:
                    try:
                        await app.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                        )
                    except Exception:
                        sent = await app.bot.send_message(chat_id=chat_id, text=text)
                        message_id = sent.message_id
                else:
                    sent = await app.bot.send_message(chat_id=chat_id, text=text)
                    message_id = sent.message_id
                last_processed = campaign.processed_count

            await asyncio.sleep(POLL_INTERVAL_SEC)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Progress poll failed for campaign %s", campaign_id)
    finally:
        _tasks.pop(campaign_id, None)


def start_progress_updates(
    app: Application,
    *,
    chat_id: int,
    campaign_id: int,
    message_id: int | None = None,
) -> None:
    stop_progress_updates(campaign_id)
    task = app.create_task(
        _poll_campaign(app, chat_id=chat_id, campaign_id=campaign_id, message_id=message_id),
        name=f"progress-{campaign_id}",
    )
    _tasks[campaign_id] = task


def stop_progress_updates(campaign_id: int) -> None:
    task = _tasks.pop(campaign_id, None)
    if task and not task.done():
        task.cancel()
