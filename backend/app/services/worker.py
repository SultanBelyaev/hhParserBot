import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import ApplicationLog, Campaign
from app.services.scraper import run_campaign

logger = logging.getLogger(__name__)


class CampaignWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: Dict[int, threading.Thread] = {}
        self._stop_flags: Dict[int, threading.Event] = {}

    def is_running(self, campaign_id: int) -> bool:
        thread = self._threads.get(campaign_id)
        return thread is not None and thread.is_alive()

    def start(self, campaign_id: int) -> None:
        with self._lock:
            if self.is_running(campaign_id):
                raise RuntimeError("Кампания уже запущена")

            stop_event = threading.Event()
            self._stop_flags[campaign_id] = stop_event

            thread = threading.Thread(
                target=self._run_campaign,
                args=(campaign_id, stop_event),
                daemon=True,
                name=f"campaign-{campaign_id}",
            )
            self._threads[campaign_id] = thread
            thread.start()

    def stop(self, campaign_id: int) -> bool:
        stop_event = self._stop_flags.get(campaign_id)
        if stop_event:
            stop_event.set()
            return True
        return False

    def wait_until_stopped(self, campaign_id: int, *, timeout_sec: float = 90) -> bool:
        thread = self._threads.get(campaign_id)
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout=timeout_sec)
        return not self.is_running(campaign_id)

    def _run_campaign(self, campaign_id: int, stop_event: threading.Event) -> None:
        db = SessionLocal()
        try:
            campaign = db.get(Campaign, campaign_id)
            if not campaign:
                return

            campaign.status = "running"
            campaign.started_at = datetime.now(timezone.utc)
            campaign.error_message = None
            db.commit()

            def on_progress(data: dict) -> None:
                progress_db = SessionLocal()
                try:
                    c = progress_db.get(Campaign, campaign_id)
                    if not c:
                        return

                    if data.get("event") == "vacancies_found":
                        c.vacancies_found = data.get("count", 0)
                        progress_db.commit()
                        return

                    if data.get("event") == "vacancy_processed":
                        status = data["status"]
                        if status == "sent":
                            c.sent_count += 1
                        elif status in ("card_not_found", "timeout", "error", "cover_letter_failed"):
                            c.failed_count += 1
                        else:
                            c.skipped_count += 1
                        c.processed_count += 1

                        progress_db.add(
                            ApplicationLog(
                                campaign_id=campaign_id,
                                vacancy_id=data["vacancy_id"],
                                vacancy_title=data.get("vacancy_title"),
                                status="success" if status == "sent" else "skipped" if status not in ("card_not_found", "timeout", "error", "cover_letter_failed") else "error",
                                detail=status,
                                cover_letter_sent=bool(data.get("cover_letter_sent")),
                            )
                        )
                        progress_db.commit()
                finally:
                    progress_db.close()

            stats = run_campaign(
                search_query=campaign.search_query,
                area_id=campaign.area_id or "",
                apply_limit=campaign.apply_limit,
                session_file=settings.session_file,
                headless=settings.headless,
                scroll_max=settings.scroll_max,
                scroll_pause_ms=settings.scroll_pause_ms,
                scroll_buffer_factor=settings.scroll_buffer_factor,
                apply_delay_ms=settings.apply_delay_ms,
                apply_poll_timeout_sec=settings.apply_poll_timeout_sec,
                hide_skipped_vacancies=settings.hide_skipped_vacancies,
                block_media=settings.block_media,
                cover_letter=campaign.cover_letter or "",
                on_progress=on_progress,
                should_stop=stop_event.is_set,
            )

            campaign = db.get(Campaign, campaign_id)
            if campaign:
                if stop_event.is_set():
                    campaign.status = "paused"
                else:
                    campaign.status = "completed"
                campaign.sent_count = stats.sent
                campaign.skipped_count = stats.skipped
                campaign.failed_count = stats.failed
                campaign.processed_count = stats.sent + stats.skipped + stats.failed
                campaign.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as exc:
            logger.exception("Campaign %s failed: %s", campaign_id, exc)
            campaign = db.get(Campaign, campaign_id)
            if campaign:
                campaign.status = "failed"
                campaign.error_message = str(exc)
                campaign.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
            with self._lock:
                self._threads.pop(campaign_id, None)
                self._stop_flags.pop(campaign_id, None)


campaign_worker = CampaignWorker()
