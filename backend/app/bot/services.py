from typing import Optional

from app.config import settings
from app.database import SessionLocal
from app.models import ApplicationLog, Campaign
from app.services.auth_service import LoginState, get_login_manager
from app.services.scraper import check_session_valid
from app.services.stats_service import DETAIL_LABELS, build_campaign_stats
from app.services.worker import campaign_worker


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
    db = SessionLocal()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError("Кампания не найдена")
        if campaign.status == "running":
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
        if campaign.status == "running":
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
        if campaign.status == "running":
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
    status_map = {
        "draft": "Черновик",
        "running": "Запущена",
        "completed": "Завершена",
        "paused": "Остановлена",
        "failed": "Ошибка",
    }
    return (
        f"#{c.id} {c.name}\n"
        f"Статус: {status_map.get(c.status, c.status)}\n"
        f"Запрос: «{c.search_query}»\n"
        f"Прогресс: {c.processed_count}/{c.apply_limit} "
        f"(✅{c.sent_count} ⏭{c.skipped_count} ❌{c.failed_count})"
    )


def format_stats(stats: dict) -> str:
    lines = [
        f"📊 {stats['campaign_name']}",
        f"Статус: {stats['campaign_status']}",
        f"Успешность: {stats['rates']['success']}%",
        f"Найдено: {stats.get('vacancies_found') or '—'}",
        f"Обработано: {stats['processed_count']}/{stats['apply_limit']}",
        f"✅ {stats['totals']['sent']}  ⏭ {stats['totals']['skipped']}  ❌ {stats['totals']['failed']}",
    ]
    if stats["by_detail"]:
        lines.append("\nПричины:")
        for item in stats["by_detail"][:6]:
            lines.append(f"• {item['label']}: {item['count']}")
    return "\n".join(lines)


def format_logs(logs: list[ApplicationLog]) -> str:
    if not logs:
        return "Лог пуст."
    lines = ["📝 Последние отклики:"]
    for log in logs:
        icon = "✅" if log.status == "success" else "⏭" if log.status == "skipped" else "❌"
        letter = "📄" if log.cover_letter_sent else ""
        reason = DETAIL_LABELS.get(log.detail or "", log.detail or "")
        title = (log.vacancy_title or log.vacancy_id)[:50]
        lines.append(f"{icon}{letter} {title}\n   {reason}")
    return "\n".join(lines)
