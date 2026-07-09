"""Регистрация команд бота в Telegram."""
from telegram import BotCommand


BOT_COMMANDS = [
    BotCommand("start", "Главный экран"),
    BotCommand("help", "Справка"),
    BotCommand("status", "Статус HH"),
    BotCommand("login", "Вход в HH"),
    BotCommand("logout", "Выход из HH"),
    BotCommand("new", "Новая кампания"),
    BotCommand("campaigns", "Список кампаний"),
    BotCommand("cancel", "Отмена диалога"),
]


async def register_bot_commands(application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)
