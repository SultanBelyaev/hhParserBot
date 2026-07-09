"""Тексты и форматирование сообщений бота."""
from __future__ import annotations

from app.bot.constants import AREA_OPTIONS
from app.models import Campaign


def step_header(flow: str, step: int, total: int, title: str) -> str:
    return f"Шаг {step}/{total} · {flow}\n{title}\n"


def help_text() -> str:
    return (
        "📖 Справка HH AutoApply\n\n"
        "Команды:\n"
        "/start — главный экран\n"
        "/help — эта справка\n"
        "/status — проверка сессии HH\n"
        "/login — вход в HH\n"
        "/logout — выход из HH\n"
        "/new — новая кампания\n"
        "/campaigns — список кампаний\n"
        "/cancel — отмена текущего диалога\n\n"
        "Кнопки меню дублируют команды.\n"
        "В любой момент: /cancel или «❌ Отмена»."
    )


def area_label(area_id: str | None) -> str:
    if not area_id:
        return "Вся Россия"
    for aid, label in AREA_OPTIONS:
        if aid == area_id:
            return label
    return area_id


def friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "не найден" in text or "not found" in text:
        return "Кампания не найдена. Обновите список: /campaigns"
    if "уже запущена" in text or "already" in text:
        return "Кампания уже запущена. Сначала остановите её."
    if "остановите" in text:
        return "Сначала остановите кампанию, затем повторите действие."
    if "timeout" in text or "таймаут" in text:
        return (
            "HH или Telegram не ответили вовремя.\n"
            "Попробуйте ещё раз через пару минут."
        )
    if "session" in text or "сессия" in text or "войдите" in text:
        return "Сначала войдите в HH: нажмите 🔐 Войти или /login"
    if "доступ" in text:
        return str(exc)
    return f"Что-то пошло не так.\n{exc}"


def format_dashboard(
    *,
    bot_username: str,
    hh_connected: bool,
    hh_message: str | None,
    campaigns: list[Campaign],
) -> str:
    hh_line = "✅ HH подключён" if hh_connected else f"❌ HH не подключён"
    if not hh_connected and hh_message:
        hh_line += f"\n{hh_message}"

    running = [c for c in campaigns if c.status == "running"]
    lines = [
        f"🤖 @{bot_username}",
        "",
        hh_line,
        f"Кампании: {len(campaigns)}"
        + (f" ({len(running)} запущена)" if running else ""),
    ]

    for c in running[:3]:
        lines.append(
            f"▶️ #{c.id} {c.name} — {c.processed_count}/{c.apply_limit} "
            f"✅{c.sent_count} ⏭{c.skipped_count} ❌{c.failed_count}"
        )

    if not hh_connected:
        lines.extend(["", "🚀 Быстрый старт: нажмите «🔐 Войти» ниже"])
    elif not campaigns:
        lines.extend(["", "➕ Создайте первую кампанию"])
    elif not running and hh_connected:
        lines.extend(["", "▶️ Запустите кампанию из списка «📋 Кампании»"])

    return "\n".join(lines)


def format_onboarding(*, hh_connected: bool, has_campaigns: bool) -> str | None:
    if hh_connected and has_campaigns:
        return None
    step = 1
    if hh_connected:
        step = 2
    if has_campaigns:
        return None
    total = 3
    lines = ["", "🚀 Быстрый старт"]
    if not hh_connected:
        lines.append(f"{step}/{total} Войдите в HH")
        step += 1
    if not has_campaigns:
        lines.append(f"{step}/{total} Создайте кампанию")
        step += 1
    lines.append(f"{step}/{total} Запустите автоотклики")
    return "\n".join(lines)


def format_campaigns_overview(campaigns: list[Campaign]) -> str:
    if not campaigns:
        return "📋 Кампаний пока нет.\nНажмите «➕ Новая кампания» или выберите пресет."

    status_icon = {
        "draft": "📝",
        "running": "▶️",
        "completed": "✅",
        "paused": "⏹",
        "failed": "❌",
    }
    lines = [f"📋 Кампании ({len(campaigns)})", ""]
    for c in campaigns[:15]:
        icon = status_icon.get(c.status, "•")
        progress = f"{c.processed_count}/{c.apply_limit}"
        extra = ""
        if c.status == "running":
            extra = f" ✅{c.sent_count} ⏭{c.skipped_count} ❌{c.failed_count}"
        elif c.status == "completed":
            extra = " · завершена"
        elif c.status == "draft":
            extra = " · черновик"
        lines.append(f"{icon} #{c.id} {c.name} — {progress}{extra}")
    if len(campaigns) > 15:
        lines.append(f"\n… и ещё {len(campaigns) - 15}")
    lines.append("\nНажмите кампанию ниже для управления.")
    return "\n".join(lines)


def format_campaign_preview(user_data: dict) -> str:
    letter = user_data.get("cover_letter") or ""
    area = area_label(user_data.get("area_id"))
    return (
        "Проверьте кампанию:\n\n"
        f"Название: {user_data.get('name')}\n"
        f"Запрос: {user_data.get('search_query')}\n"
        f"Лимит: {user_data.get('apply_limit')}\n"
        f"Регион: {area}\n"
        f"Сопроводительное: {len(letter)} симв."
    )


def format_cover_letter_preview(text: str, limit: int = 400) -> str:
    preview = text.strip()
    if len(preview) > limit:
        preview = preview[:limit] + "…"
    return f"👁 Сопроводительное письмо:\n\n{preview}"


def format_progress_update(campaign: Campaign, *, last_log_title: str | None = None) -> str:
    lines = [
        f"▶️ Кампания #{campaign.id} «{campaign.name}»",
        f"{campaign.processed_count}/{campaign.apply_limit} · "
        f"✅{campaign.sent_count} ⏭{campaign.skipped_count} ❌{campaign.failed_count}",
    ]
    if last_log_title:
        lines.append(f"Последний: {last_log_title[:60]}")
    return "\n".join(lines)


def format_campaign_finished(campaign: Campaign) -> str:
    status_map = {
        "completed": "✅ Завершена",
        "paused": "⏹ Остановлена",
        "failed": "❌ Ошибка",
    }
    title = status_map.get(campaign.status, campaign.status)
    lines = [
        f"{title}: #{campaign.id} «{campaign.name}»",
        f"Итого: {campaign.processed_count}/{campaign.apply_limit}",
        f"✅ {campaign.sent_count}  ⏭ {campaign.skipped_count}  ❌ {campaign.failed_count}",
    ]
    if campaign.error_message:
        lines.append(f"\nПричина: {campaign.error_message[:200]}")
    return "\n".join(lines)
