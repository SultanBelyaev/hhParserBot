from typing import Optional

from app.bot.constants import CAMPAIGN_PRESETS
from app.config import settings
from app.database import SessionLocal
from app.models import ApplicationLog, Campaign
from app.services.auth_service import LoginState, get_login_manager
from app.services.scraper import check_session_valid
from app.services.stats_service import DETAIL_LABELS, build_campaign_stats
from app.services.worker import campaign_worker


CAMPAIGN_STATUS_LABELS = {
    "draft": "Черновик",
    "running": "Запущена",
    "stopping": "Останавливается",
    "completed": "Завершена",
    "paused": "Остановлена",
    "failed": "Ошибка",
}


def effective_status(campaign: Campaign) -> str:
    """Статус с учётом живого worker-потока (может расходиться с БД)."""
    if campaign_worker.is_running(campaign.id):
        if campaign.status == "stopping":
            return "stopping"
        return "running"
    if campaign.status == "stopping":
        return "paused"
    return campaign.status


def status_label(status: str) -> str:
    return CAMPAIGN_STATUS_LABELS.get(status, status)


def get_hh_status_quick() -> dict:
    """Быстрая проверка без Playwright (файл сессии)."""
    exists = settings.session_file.exists()
    return {
        "connected": exists,
        "message": None if exists else "Войдите в аккаунт HH.",
    }


def get_dashboard_data() -> dict:
    quick = get_hh_status_quick()
    campaigns = list_campaigns()
    running = [c for c in campaigns if effective_status(c) in ("running", "stopping")]
    return {
        "hh_connected": quick["connected"],
        "hh_message": quick["message"],
        "campaigns": campaigns,
        "running_count": len(running),
        "has_campaigns": bool(campaigns),
    }


def duplicate_campaign(campaign_id: int) -> Campaign:
    source = get_campaign(campaign_id)
    if not source:
        raise ValueError("Кампания не найдена")
    return create_campaign(
        name=f"{source.name} (копия)",
        search_query=source.search_query,
        apply_limit=source.apply_limit,
        area_id=source.area_id,
        cover_letter=source.cover_letter,
    )


def apply_preset(preset_index: int) -> dict:
    if preset_index < 0 or preset_index >= len(CAMPAIGN_PRESETS):
        raise ValueError("Неизвестный пресет")
    preset = CAMPAIGN_PRESETS[preset_index]
    return {
        "name": preset["name"],
        "search_query": preset["search_query"],
        "area_id": preset["area_id"] or None,
        "apply_limit": preset["apply_limit"],
        "cover_letter": settings.default_cover_letter,
    }


def get_auth_status() -> dict:
    connected = check_session_valid(settings.session_file, headless=settings.headless)
    message = None
    if not connected:
        if settings.session_file.exists():
            message = "Сессия истекла. Выполните повторный вход."
        else:
            message = "Войдите в аккаунт HH."
    return {"connected": connected, "message": message}


def start_login() -> str:
    get_login_manager().start()
    return "Отправьте номер телефона следующим сообщением (формат: +79...)."


def cancel_login() -> None:
    get_login_manager().cancel()


def get_login_state() -> dict:
    manager = get_login_manager()
    return {"state": manager.state.value, "error": manager.error}


def submit_login_phone(phone: str) -> str:
    get_login_manager().submit_phone(phone)
    return "Код отправлен. Отправьте SMS-код следующим сообщением."


def submit_login_code(code: str) -> str:
    manager = get_login_manager()
    manager.submit_code(code)
    if manager.state == LoginState.COMPLETED:
        return (
            "✅ Вход выполнен. Сессия сохранена.\n"
            "Проверьте: /status"
        )
    return "Обработка входа..."


def logout() -> str:
    get_login_manager().cancel()
    if settings.session_file.exists():
        settings.session_file.unlink()
    return "Сессия удалена."


def list_campaigns() -> list[Campaign]:
    db = SessionLocal()
    try:
        return db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    finally:
        db.close()


def get_campaign(campaign_id: int) -> Optional[Campaign]:
    db = SessionLocal()
    try:
        return db.get(Campaign, campaign_id)
    finally:
        db.close()


def create_campaign(
    *,
    name: str,
    search_query: str,
    apply_limit: int,
    area_id: Optional[str] = None,
    cover_letter: Optional[str] = None,
) -> Campaign:
    db = SessionLocal()
    try:
        campaign = Campaign(
            name=name,
            search_query=search_query,
            area_id=area_id or None,
            apply_limit=apply_limit,
            cover_letter=cover_letter or settings.default_cover_letter,
            status="draft",
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        return campaign
    finally:
        db.close()


def start_campaign(campaign_id: int) -> Campaign:
    if not settings.session_file.exists():
        raise ValueError(
            "Сессия HH не найдена. Выполните /login в боте "
            "или задайте SESSION_JSON_BASE64 в Railway Variables."
        )

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError("Кампания не найдена")
        if campaign_worker.is_running(campaign_id):
            raise ValueError("Кампания ещё останавливается. Подождите 10–30 сек и нажмите ▶️ снова.")
        if effective_status(campaign) == "running":
            raise ValueError("Кампания уже запущена")

        campaign_worker.start(campaign_id)
        campaign.status = "running"
        campaign.sent_count = 0
        campaign.skipped_count = 0
        campaign.failed_count = 0
        campaign.processed_count = 0
        campaign.vacancies_found = None
        campaign.error_message = None
        db.query(ApplicationLog).filter(ApplicationLog.campaign_id == campaign_id).delete()
        db.commit()
        db.refresh(campaign)
        return campaign
    finally:
        db.close()


def stop_campaign(campaign_id: int) -> Campaign:
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError("Кампания не найдена")
        campaign_worker.stop(campaign_id)
        if campaign_worker.is_running(campaign_id):
            campaign.status = "stopping"
        elif campaign.status in ("running", "stopping"):
            campaign.status = "paused"
        db.commit()
        db.refresh(campaign)
        campaign_id_saved = campaign.id
    finally:
        db.close()

    if campaign_worker.is_running(campaign_id_saved):
        campaign_worker.wait_until_stopped(campaign_id_saved, timeout_sec=90)

    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id_saved)
        if campaign and campaign.status in ("running", "stopping"):
            campaign.status = "paused"
            db.commit()
            db.refresh(campaign)
        return campaign
    finally:
        db.close()


def delete_campaign(campaign_id: int) -> None:
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError("Кампания не найдена")
        if campaign.status == "running" or campaign_worker.is_running(campaign_id):
            raise ValueError("Сначала остановите кампанию")
        db.query(ApplicationLog).filter(ApplicationLog.campaign_id == campaign_id).delete()
        db.delete(campaign)
        db.commit()
    finally:
        db.close()


def campaign_stats(campaign_id: int) -> dict:
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError("Кампания не найдена")
        return build_campaign_stats(campaign, db)
    finally:
        db.close()


def campaign_logs(campaign_id: int, limit: int = 15) -> list[ApplicationLog]:
    db = SessionLocal()
    try:
        return (
            db.query(ApplicationLog)
            .filter(ApplicationLog.campaign_id == campaign_id)
            .order_by(ApplicationLog.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def format_campaign_short(c: Campaign) -> str:
    status = effective_status(c)
    lines = [
        f"#{c.id} {c.name}",
        f"Статус: {status_label(status)}",
        f"Запрос: «{c.search_query}»",
        f"Прогресс: {c.processed_count}/{c.apply_limit} "
        f"(✅{c.sent_count} ⏭{c.skipped_count} ❌{c.failed_count})",
    ]
    if c.error_message and status == "failed":
        lines.append(f"\n⚠️ Причина: {c.error_message[:300]}")
    return "\n".join(lines)


def format_stats(stats: dict) -> str:
    raw_status = stats["campaign_status"]
    display_status = status_label(
        "running" if raw_status in ("running", "stopping") else raw_status
    )
    lines = [
        f"📊 {stats['campaign_name']}",
        f"Статус: {display_status}",
        f"Успешность: {stats['rates']['success']}%",
        f"Найдено: {stats.get('vacancies_found') or '—'}",
        f"Обработано: {stats['processed_count']}/{stats['apply_limit']}",
        f"✅ {stats['totals']['sent']}  ⏭ {stats['totals']['skipped']}  ❌ {stats['totals']['failed']}",
    ]
    if stats["by_detail"]:
        lines.append("\nПричины:")
        for item in stats["by_detail"][:6]:
            lines.append(f"• {item['label']}: {item['count']}")
    err = stats.get("error_message")
    if err and stats["campaign_status"] == "failed":
        lines.append(f"\n⚠️ Ошибка запуска: {err[:300]}")
    return "\n".join(lines)


def format_logs(logs: list[ApplicationLog], *, campaign: Campaign | None = None) -> str:
    if not logs:
        if campaign and campaign.error_message and effective_status(campaign) == "failed":
            return (
                "Лог пуст — ни одна вакансия не обработана.\n\n"
                f"⚠️ Причина: {campaign.error_message[:300]}"
            )
        return "Лог пуст."
    lines = ["📝 Последние отклики:"]
    for log in logs:
        icon = "✅" if log.status == "success" else "⏭" if log.status == "skipped" else "❌"
        letter = "📄" if log.cover_letter_sent else ""
        reason = DETAIL_LABELS.get(log.detail or "", log.detail or "")
        title = (log.vacancy_title or log.vacancy_id)[:50]
        lines.append(f"{icon}{letter} {title}\n   {reason}")
    return "\n".join(lines)
