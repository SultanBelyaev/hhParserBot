import asyncio
import logging

from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from app.bot.keyboards import (
    area_keyboard,
    campaign_actions_keyboard,
    confirm_campaign_keyboard,
    main_menu_keyboard,
)
from app.bot import services as bot_services
from app.config import ROOT_DIR, settings
from app.db_init import init_database

logger = logging.getLogger(__name__)

(
    LOGIN_PHONE,
    LOGIN_CODE,
    NEW_NAME,
    NEW_QUERY,
    NEW_LIMIT,
    NEW_AREA,
    NEW_CONFIRM,
) = range(7)


def _allowed_user_ids() -> set[int]:
    raw = settings.telegram_allowed_user_ids.strip()
    if not raw:
        return set()
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


def _allowed(user_id: int) -> bool:
    allowed_ids = _allowed_user_ids()
    if not allowed_ids:
        return True
    return user_id in allowed_ids


async def _deny(update: Update) -> bool:
    user = update.effective_user
    if user and _allowed(user.id):
        return False
    text = (
        "Доступ запрещён. Добавьте свой Telegram ID в .env:\n"
        f"TELEGRAM_ALLOWED_USER_IDS={user.id if user else 'YOUR_ID'}"
    )
    if update.message:
        await update.message.reply_text(text)
    elif update.callback_query:
        await update.callback_query.answer("Доступ запрещён", show_alert=True)
    return True


PRIORITY_GROUP = -1
DEFAULT_GROUP = 0


async def reset_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await asyncio.to_thread(bot_services.cancel_login)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reset_state(update, context)
    if await _deny(update):
        return
    user = update.effective_user
    bot_username = context.bot.username or "personalhhparserbot"
    await update.message.reply_text(
        f"Привет, {user.first_name}!\n\n"
        f"🤖 Это бот @{bot_username} — HH AutoApply (автоотклики hh.ru).\n"
        "Если вы искали другого бота — вы в нужном месте только если открыли именно его.\n\n"
        f"Ваш Telegram ID: {user.id}\n"
        "Команды:\n"
        "/status — статус HH\n"
        "/campaigns — список кампаний\n"
        "/new — новая кампания\n"
        "/login — вход в HH\n"
        "/logout — выход из HH",
        reply_markup=main_menu_keyboard(),
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram handler error: %s", context.error)
    if isinstance(update, Update):
        if update.message:
            await update.message.reply_text(f"Ошибка: {context.error}")
        elif update.callback_query:
            await update.callback_query.answer("Ошибка", show_alert=True)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    auth = await asyncio.to_thread(bot_services.get_auth_status)
    text = "✅ HH подключён" if auth["connected"] else f"❌ HH не подключён\n{auth['message'] or ''}"
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def campaigns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    campaigns = await asyncio.to_thread(bot_services.list_campaigns)
    if not campaigns:
        await update.message.reply_text("Кампаний пока нет. Нажмите «➕ Новая кампания».")
        return
    for campaign in campaigns:
        await update.message.reply_text(
            bot_services.format_campaign_short(campaign),
            reply_markup=campaign_actions_keyboard(campaign.id, campaign.status),
        )


def _login_error_hint(exc: Exception) -> str:
    text = str(exc)
    hint = (
        "\n\nОтправьте /login чтобы попробовать снова.\n"
        "Если ошибка повторяется на Railway — войдите локально:\n"
        "python login.py → python scripts/encode_session.py"
    )
    if "Timeout" in text or "timeout" in text:
        hint = (
            "\n\nHH мог не ответить (таймаут). Попробуйте /login ещё раз.\n"
            "Надёжнее: локально `python login.py`, затем обновите SESSION_JSON_BASE64."
        )
    return f"Ошибка: {text}{hint}"


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _deny(update):
        return ConversationHandler.END
    await update.message.reply_text("⏳ Запускаю браузер для входа на HH...")
    try:
        msg = await asyncio.to_thread(bot_services.start_login)
        await update.message.reply_text(msg)
        return LOGIN_PHONE
    except Exception as exc:
        await asyncio.to_thread(bot_services.cancel_login)
        await update.message.reply_text(_login_error_hint(exc))
        return ConversationHandler.END


async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    try:
        msg = await asyncio.to_thread(bot_services.submit_login_phone, phone)
        await update.message.reply_text(msg)
        return LOGIN_CODE
    except Exception as exc:
        await asyncio.to_thread(bot_services.cancel_login)
        await update.message.reply_text(_login_error_hint(exc))
        return ConversationHandler.END


async def login_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    try:
        msg = await asyncio.to_thread(bot_services.submit_login_code, code)
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    except Exception as exc:
        await asyncio.to_thread(bot_services.cancel_login)
        await update.message.reply_text(_login_error_hint(exc), reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await asyncio.to_thread(bot_services.cancel_login)
    await update.message.reply_text("Вход отменён.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def logout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    msg = await asyncio.to_thread(bot_services.logout)
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())


async def new_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _deny(update):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("Введите название кампании:")
    return NEW_NAME


async def new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Введите поисковый запрос (например: Python аналитик):")
    return NEW_QUERY


async def new_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["search_query"] = update.message.text.strip()
    await update.message.reply_text("Введите лимит откликов (число, например 10):")
    return NEW_LIMIT


async def new_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit = int(update.message.text.strip())
        if limit < 1 or limit > 500:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число от 1 до 500:")
        return NEW_LIMIT
    context.user_data["apply_limit"] = limit
    await update.message.reply_text("Выберите регион:", reply_markup=area_keyboard())
    return NEW_AREA


async def new_area_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    area_id = query.data.split(":", 1)[1]
    context.user_data["area_id"] = area_id or None
    context.user_data["cover_letter"] = settings.default_cover_letter
    preview = (
        f"Проверьте кампанию:\n\n"
        f"Название: {context.user_data['name']}\n"
        f"Запрос: {context.user_data['search_query']}\n"
        f"Лимит: {context.user_data['apply_limit']}\n"
        f"Регион: {area_id or 'Вся Россия'}\n"
        f"Сопроводительное: задано ({len(context.user_data['cover_letter'])} симв.)"
    )
    await query.edit_message_text(preview, reply_markup=confirm_campaign_keyboard())
    return NEW_CONFIRM


async def new_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "confirm:cancel":
        await query.edit_message_text("Создание отменено.")
        return ConversationHandler.END
    try:
        campaign = await asyncio.to_thread(
            bot_services.create_campaign,
            name=context.user_data["name"],
            search_query=context.user_data["search_query"],
            apply_limit=context.user_data["apply_limit"],
            area_id=context.user_data.get("area_id"),
            cover_letter=context.user_data.get("cover_letter"),
        )
        await query.edit_message_text(
            f"Кампания создана: #{campaign.id} {campaign.name}",
            reply_markup=campaign_actions_keyboard(campaign.id, campaign.status),
        )
    except Exception as exc:
        await query.edit_message_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def new_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Создание отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    query = update.callback_query
    await query.answer()
    action, _, cid = query.data.partition(":")
    campaign_id = int(cid)

    try:
        if action == "start":
            campaign = await asyncio.to_thread(bot_services.start_campaign, campaign_id)
            text = f"▶️ Кампания #{campaign.id} запущена"
        elif action == "stop":
            campaign = await asyncio.to_thread(bot_services.stop_campaign, campaign_id)
            text = f"⏹ Кампания #{campaign.id} остановлена"
        elif action == "delete":
            await asyncio.to_thread(bot_services.delete_campaign, campaign_id)
            await query.edit_message_text(f"🗑 Кампания #{campaign_id} удалена")
            return
        elif action == "stats":
            stats = await asyncio.to_thread(bot_services.campaign_stats, campaign_id)
            await query.message.reply_text(bot_services.format_stats(stats))
            return
        elif action == "logs":
            logs = await asyncio.to_thread(bot_services.campaign_logs, campaign_id)
            await query.message.reply_text(bot_services.format_logs(logs))
            return
        else:
            return

        campaign = await asyncio.to_thread(bot_services.get_campaign, campaign_id)
        await query.edit_message_text(
            text + "\n\n" + bot_services.format_campaign_short(campaign),
            reply_markup=campaign_actions_keyboard(campaign.id, campaign.status),
        )
    except Exception as exc:
        await query.message.reply_text(f"Ошибка: {exc}")


async def start_conv_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await start_cmd(update, context)
    return ConversationHandler.END


async def menu_simple_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reset_state(update, context)
    if await _deny(update):
        return
    text = update.message.text.strip()
    if text == "📊 Статус HH":
        await status_cmd(update, context)
    elif text == "📋 Кампании":
        await campaigns_cmd(update, context)
    elif text == "🚪 Выйти из HH":
        await logout_cmd(update, context)


MENU_SIMPLE = filters.Regex(r"^(📊 Статус HH|📋 Кампании|🚪 Выйти из HH)$")


def build_application(for_polling: bool = False) -> Application:
    if not settings.telegram_bot_token.strip():
        env_path = ROOT_DIR / ".env"
        raise RuntimeError(
            f"TELEGRAM_BOT_TOKEN не задан.\n"
            f"Создайте файл {env_path} и добавьте строку:\n"
            f"TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather"
        )

    login_conv = ConversationHandler(
        entry_points=[
            CommandHandler("login", login_start),
            MessageHandler(filters.Regex("^🔐 Войти$"), login_start),
        ],
        states={
            LOGIN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            LOGIN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_code)],
        },
        fallbacks=[
            CommandHandler("start", start_conv_fallback),
            CommandHandler("cancel", login_cancel),
            MessageHandler(MENU_SIMPLE, menu_simple_handler),
        ],
    )

    new_conv = ConversationHandler(
        entry_points=[
            CommandHandler("new", new_start),
            MessageHandler(filters.Regex("^➕ Новая кампания$"), new_start),
        ],
        states={
            NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_name)],
            NEW_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_query)],
            NEW_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_limit)],
            NEW_AREA: [CallbackQueryHandler(new_area_cb, pattern=r"^area:")],
            NEW_CONFIRM: [CallbackQueryHandler(new_confirm_cb, pattern=r"^confirm:")],
        },
        fallbacks=[
            CommandHandler("start", start_conv_fallback),
            CommandHandler("cancel", new_cancel),
            MessageHandler(MENU_SIMPLE, menu_simple_handler),
        ],
        allow_reentry=True,
    )

    request = HTTPXRequest(
        connect_timeout=settings.telegram_connect_timeout,
        read_timeout=settings.telegram_read_timeout,
        write_timeout=settings.telegram_read_timeout,
        proxy=settings.telegram_proxy_url.strip() or None,
    )

    async def _on_bot_start(application: Application) -> None:
        import time

        if not for_polling:
            return

        info = await application.bot.get_webhook_info()
        if info.url:
            logger.warning("Removing active webhook: %s", info.url)
        await application.bot.delete_webhook(drop_pending_updates=True)

        settings.bot_heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
        settings.bot_heartbeat_file.write_text(str(time.time()), encoding="utf-8")
        logger.info("Bot ready for polling, heartbeat written")

    builder = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .request(request)
        .get_updates_request(request)
    )
    if for_polling:
        builder = builder.post_init(_on_bot_start)
    app = builder.build()
    app.add_error_handler(_on_error)

    for handler in (
        CommandHandler("start", start_cmd),
        CommandHandler("status", status_cmd),
        CommandHandler("campaigns", campaigns_cmd),
        CommandHandler("logout", logout_cmd),
        CommandHandler("cancel", login_cancel),
        MessageHandler(MENU_SIMPLE, menu_simple_handler),
    ):
        app.add_handler(handler, group=PRIORITY_GROUP)

    app.add_handler(login_conv, group=DEFAULT_GROUP)
    app.add_handler(new_conv, group=DEFAULT_GROUP)
    app.add_handler(
        CallbackQueryHandler(callback_handler, pattern=r"^(start|stop|delete|stats|logs):"),
        group=DEFAULT_GROUP,
    )
    return app


def run_bot() -> None:
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [bot] %(levelname)s %(name)s: %(message)s",
    )
    settings.session_file.parent.mkdir(parents=True, exist_ok=True)
    init_database()

    token = settings.telegram_bot_token.strip()
    allowed = _allowed_user_ids()
    logger.info(
        "Config: token_len=%s allowed_ids=%s session=%s",
        len(token),
        sorted(allowed) if allowed else "any",
        settings.session_file,
    )

    proxy_hint = f" (proxy: {settings.telegram_proxy_url})" if settings.telegram_proxy_url.strip() else ""

    while True:
        logger.info("Telegram bot starting%s", proxy_hint)
        try:
            app = build_application(for_polling=True)
            app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
            return
        except Conflict:
            logger.error(
                "Conflict: другой процесс уже использует этот токен бота. "
                "Остановите локальный `python run_bot.py` на Mac и убедитесь, "
                "что в Railway только 1 реплика. Retry через 60s..."
            )
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Bot stopped")
            return
        except Exception as exc:
            exc_name = type(exc).__name__
            if "TimedOut" in exc_name or "Connect" in str(exc):
                logger.error(
                    "Не удалось подключиться к api.telegram.org. Retry через 30s..."
                )
                time.sleep(30)
                continue
            logger.exception("Bot crashed, retry in 15s")
            time.sleep(15)
