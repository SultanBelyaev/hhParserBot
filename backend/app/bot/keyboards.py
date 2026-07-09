from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.bot.constants import AREA_OPTIONS, CAMPAIGN_PRESETS
from app.models import Campaign


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🏠 Главная"), KeyboardButton("🔐 Войти")],
            [KeyboardButton("📋 Кампании"), KeyboardButton("➕ Новая кампания")],
            [KeyboardButton("🚪 Выйти из HH")],
        ],
        resize_keyboard=True,
    )


def cancel_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="flow:cancel")]])


def dashboard_keyboard(*, hh_connected: bool, has_campaigns: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="dash:refresh"),
            InlineKeyboardButton("📋 Кампании", callback_data="dash:campaigns"),
        ],
    ]
    if not hh_connected:
        rows.append([InlineKeyboardButton("🔐 Войти в HH (шаг 1/3)", callback_data="onboard:login")])
    elif not has_campaigns:
        rows.append([InlineKeyboardButton("➕ Новая кампания (шаг 2/3)", callback_data="onboard:new")])
    else:
        rows.append([InlineKeyboardButton("➕ Новая кампания", callback_data="onboard:new")])
    return InlineKeyboardMarkup(rows)


def onboarding_keyboard(*, hh_connected: bool) -> Optional[InlineKeyboardMarkup]:
    if hh_connected:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔐 Войти в HH — 1/3", callback_data="onboard:login")],
            [InlineKeyboardButton("Пропустить", callback_data="onboard:skip")],
        ]
    )


def new_campaign_entry_keyboard(recent: list[Campaign]) -> InlineKeyboardMarkup:
    rows = []
    for idx, preset in enumerate(CAMPAIGN_PRESETS):
        rows.append([
            InlineKeyboardButton(
                f"⚡ {preset['name']} · {preset['apply_limit']} откл.",
                callback_data=f"preset:{idx}",
            )
        ])
    for c in recent[:2]:
        rows.append([
            InlineKeyboardButton(
                f"🔁 Повторить #{c.id} {c.name[:20]}",
                callback_data=f"repeat:{c.id}",
            )
        ])
    rows.append([InlineKeyboardButton("✏️ Настроить вручную", callback_data="preset:manual")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(rows)


def campaign_actions_keyboard(campaign_id: int, status: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Статистика", callback_data=f"stats:{campaign_id}"),
            InlineKeyboardButton("📝 Лог", callback_data=f"logs:{campaign_id}"),
        ],
    ]
    if status == "running":
        rows.append([InlineKeyboardButton("⏹ Остановить", callback_data=f"stop:{campaign_id}")])
    elif status == "stopping":
        rows.append([InlineKeyboardButton("⏳ Останавливается…", callback_data=f"noop:{campaign_id}")])
    else:
        rows.append([
            InlineKeyboardButton("▶️ Запустить", callback_data=f"start:{campaign_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{campaign_id}"),
        ])
    rows.append([InlineKeyboardButton("↩️ К списку", callback_data="dash:campaigns")])
    return InlineKeyboardMarkup(rows)


def campaigns_list_keyboard(campaigns: list[Campaign]) -> InlineKeyboardMarkup:
    rows = []
    for c in campaigns[:12]:
        icon = {"running": "▶️", "completed": "✅", "paused": "⏹", "draft": "📝"}.get(c.status, "•")
        rows.append([
            InlineKeyboardButton(
                f"{icon} #{c.id} {c.name[:22]}",
                callback_data=f"open:{c.id}",
            )
        ])
    rows.append([InlineKeyboardButton("➕ Новая кампания", callback_data="onboard:new")])
    rows.append([InlineKeyboardButton("🏠 Главная", callback_data="dash:refresh")])
    return InlineKeyboardMarkup(rows)


def area_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for area_id, label in AREA_OPTIONS:
        rows.append([InlineKeyboardButton(label, callback_data=f"area:{area_id}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(rows)


def confirm_campaign_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Создать", callback_data="confirm:create"),
            InlineKeyboardButton("❌ Отмена", callback_data="confirm:cancel"),
        ],
        [
            InlineKeyboardButton("👁 Письмо", callback_data="letter:preview"),
            InlineKeyboardButton("✏️ Изменить письмо", callback_data="letter:edit"),
        ],
        [InlineKeyboardButton("↩️ По умолчанию", callback_data="letter:default")],
    ])


def confirm_delete_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"delete_yes:{campaign_id}"),
            InlineKeyboardButton("↩️ Назад", callback_data=f"open:{campaign_id}"),
        ],
    ])


def confirm_logout_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, выйти", callback_data="logout:yes"),
            InlineKeyboardButton("↩️ Отмена", callback_data="logout:no"),
        ],
    ])


def retry_keyboard(action: str) -> InlineKeyboardMarkup:
    labels = {
        "login": "🔐 Повторить вход",
        "campaigns": "📋 Кампании",
        "new": "➕ Новая кампания",
    }
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(labels.get(action, "🔄 Повторить"), callback_data=f"retry:{action}")],
    ])
