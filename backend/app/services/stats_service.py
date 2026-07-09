from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ApplicationLog, Campaign

DETAIL_LABELS: dict[str, str] = {
    "sent": "Отклик отправлен",
    "test_required": "Требуется тест",
    "cover_letter_required": "Обязательное сопроводительное (не задано)",
    "cover_letter_failed": "Не удалось отправить сопроводительное",
    "extra_steps": "Дополнительные шаги",
    "no_apply_button": "Нет кнопки отклика",
    "card_not_found": "Карточка не найдена",
    "timeout": "Таймаут",
    "error": "Ошибка",
    "unknown": "Неизвестный статус",
}

STATUS_LABELS: dict[str, str] = {
    "success": "Отправлено",
    "skipped": "Пропущено",
    "error": "Ошибка",
}


def _duration_seconds(started_at: Optional[datetime], finished_at: Optional[datetime]) -> Optional[int]:
    if not started_at:
        return None
    end = finished_at or datetime.now(timezone.utc)
    start = started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds()))


def build_campaign_stats(campaign: Campaign, db: Session) -> dict:
    logs = (
        db.query(ApplicationLog)
        .filter(ApplicationLog.campaign_id == campaign.id)
        .order_by(ApplicationLog.created_at.asc())
        .all()
    )

    by_status: dict[str, int] = {"success": 0, "skipped": 0, "error": 0}
    by_detail: dict[str, int] = {}

    for log in logs:
        by_status[log.status] = by_status.get(log.status, 0) + 1
        detail = log.detail or "unknown"
        by_detail[detail] = by_detail.get(detail, 0) + 1

    total = len(logs)
    sent = by_status.get("success", 0)
    skipped = by_status.get("skipped", 0)
    failed = by_status.get("error", 0)

    success_rate = round((sent / total) * 100, 1) if total else 0.0
    skip_rate = round((skipped / total) * 100, 1) if total else 0.0
    fail_rate = round((failed / total) * 100, 1) if total else 0.0

    duration = _duration_seconds(campaign.started_at, campaign.finished_at)
    avg_per_item = round(duration / total, 1) if duration is not None and total else None

    detail_breakdown = [
        {
            "detail": key,
            "label": DETAIL_LABELS.get(key, key),
            "count": count,
            "percent": round((count / total) * 100, 1) if total else 0.0,
            "status": (
                "success" if key == "sent"
                else "error" if key in ("card_not_found", "timeout", "error")
                else "skipped"
            ),
        }
        for key, count in sorted(by_detail.items(), key=lambda x: -x[1])
    ]

    timeline = []
    cumulative_sent = 0
    cumulative_skipped = 0
    cumulative_failed = 0
    for log in logs:
        if log.status == "success":
            cumulative_sent += 1
        elif log.status == "skipped":
            cumulative_skipped += 1
        else:
            cumulative_failed += 1
        timeline.append({
            "at": log.created_at.isoformat() if log.created_at else None,
            "vacancy_title": log.vacancy_title,
            "status": log.status,
            "detail": log.detail,
            "cumulative": {
                "sent": cumulative_sent,
                "skipped": cumulative_skipped,
                "failed": cumulative_failed,
            },
        })

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_status": campaign.status,
        "search_query": campaign.search_query,
        "apply_limit": campaign.apply_limit,
        "vacancies_found": getattr(campaign, "vacancies_found", None),
        "processed_count": campaign.processed_count,
        "remaining": max(0, campaign.apply_limit - campaign.processed_count),
        "totals": {
            "total": total,
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
        },
        "rates": {
            "success": success_rate,
            "skipped": skip_rate,
            "failed": fail_rate,
        },
        "timing": {
            "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
            "finished_at": campaign.finished_at.isoformat() if campaign.finished_at else None,
            "duration_seconds": duration,
            "avg_seconds_per_item": avg_per_item,
        },
        "by_status": by_status,
        "by_detail": detail_breakdown,
        "timeline": timeline[-50:],
        "error_message": campaign.error_message,
    }
