from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

AREA_OPTIONS = [
    ("", "Вся Россия"),
    ("1", "Москва"),
    ("2", "Санкт-Петербург"),
    ("3", "Екатеринбург"),
    ("4", "Новосибирск"),
    ("88", "Казань"),
]


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Статус HH"), KeyboardButton("🔐 Войти")],
            [KeyboardButton("📋 Кампании"), KeyboardButton("➕ Новая кампания")],
            [KeyboardButton("🚪 Выйти из HH")],
        ],
        resize_keyboard=True,
    )


def campaign_actions_keyboard(campaign_id: int, status: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Статистика", callback_data=f"stats:{campaign_id}"),
            InlineKeyboardButton("📝 Лог", callback_data=f"logs:{campaign_id}"),
        ],
    ]
    if status == "running":
        rows.append([InlineKeyboardButton("⏹ Остановить", callback_data=f"stop:{campaign_id}")])
    else:
        rows.append([
            InlineKeyboardButton("▶️ Запустить", callback_data=f"start:{campaign_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{campaign_id}"),
        ])
    return InlineKeyboardMarkup(rows)


def area_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for area_id, label in AREA_OPTIONS:
        rows.append([InlineKeyboardButton(label, callback_data=f"area:{area_id}")])
    return InlineKeyboardMarkup(rows)


def confirm_campaign_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Создать", callback_data="confirm:create"),
            InlineKeyboardButton("❌ Отмена", callback_data="confirm:cancel"),
        ],
    ])
