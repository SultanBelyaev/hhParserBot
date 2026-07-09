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

from app.bot import services as bot_services
from app.bot.commands import register_bot_commands
from app.bot.keyboards import (
    area_keyboard,
    campaign_actions_keyboard,
    campaigns_list_keyboard,
    cancel_inline_keyboard,
    confirm_campaign_keyboard,
    confirm_delete_keyboard,
    confirm_logout_keyboard,
    dashboard_keyboard,
    main_menu_keyboard,
    new_campaign_entry_keyboard,
    retry_keyboard,
)
from app.bot.messages import (
    format_campaign_preview,
    format_campaigns_overview,
    format_cover_letter_preview,
    format_dashboard,
    format_onboarding,
    friendly_error,
    help_text,
    step_header,
)
from app.bot.progress import start_progress_updates, stop_progress_updates
from app.config import ROOT_DIR, settings
from app.db_init import init_database

logger = logging.getLogger(__name__)

(
    LOGIN_PHONE,
    LOGIN_CODE,
    NEW_PRESET,
    NEW_NAME,
    NEW_QUERY,
    NEW_LIMIT,
    NEW_AREA,
    NEW_CONFIRM,
    NEW_COVER,
) = range(9)

PRIORITY_GROUP = -1
DEFAULT_GROUP = 0

MENU_HOME = filters.Regex("^🏠 Главная$")
MENU_SIMPLE = filters.Regex(r"^(📋 Кампании|🚪 Выйти из HH)$")


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


async def reset_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    try:
        await asyncio.wait_for(asyncio.to_thread(bot_services.cancel_login), timeout=3.0)
    except (asyncio.TimeoutError, Exception):
        logger.debug("cancel_login skipped during reset", exc_info=True)


async def _send_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False) -> None:
    bot_username = context.bot.username or "bot"
    data = await asyncio.to_thread(bot_services.get_dashboard_data)
    text = format_dashboard(
        bot_username=bot_username,
        hh_connected=data["hh_connected"],
        hh_message=data["hh_message"],
        campaigns=data["campaigns"],
    )
    onboard = format_onboarding(
        hh_connected=data["hh_connected"],
        has_campaigns=data["has_campaigns"],
    )
    if onboard:
        text += onboard

    markup = dashboard_keyboard(
        hh_connected=data["hh_connected"],
        has_campaigns=data["has_campaigns"],
    )

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=markup)


async def dashboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    await _send_dashboard(update, context)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reset_state(update, context)
    if await _deny(update):
        return
    user = update.effective_user
    bot_username = context.bot.username or "bot"
    await update.message.reply_text(
        f"Привет, {user.first_name}! Чат: @{bot_username}\n"
        f"ID: {user.id} · /help — справка",
        reply_markup=main_menu_keyboard(),
    )
    await _send_dashboard(update, context)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    await update.message.reply_text(help_text(), reply_markup=main_menu_keyboard())


async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    bot_username = context.bot.username or "bot"
    await update.message.reply_text(
        f"✅ @{bot_username} отвечает.\n"
        f"update_id={update.update_id}, chat_id={update.effective_chat.id}"
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Telegram handler error: %s", context.error)
    if not isinstance(update, Update):
        return
    msg = friendly_error(context.error) if context.error else "Неизвестная ошибка"
    if update.message:
        await update.message.reply_text(msg, reply_markup=retry_keyboard("login"))
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    if not settings.session_file.exists():
        await update.message.reply_text(
            "❌ HH не подключён\nСначала войдите: 🔐 Войти",
            reply_markup=retry_keyboard("login"),
        )
        return
    await update.message.reply_text("⏳ Проверяю сессию HH...")
    try:
        auth = await asyncio.wait_for(
            asyncio.to_thread(bot_services.get_auth_status),
            timeout=45,
        )
    except asyncio.TimeoutError:
        auth = {"connected": False, "message": "Проверка заняла слишком долго."}
    if auth["connected"]:
        text = "✅ HH подключён"
    else:
        text = f"❌ HH не подключён\n{auth['message'] or ''}"
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def campaigns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    campaigns = await asyncio.to_thread(bot_services.list_campaigns)
    text = format_campaigns_overview(campaigns)
    await update.message.reply_text(
        text,
        reply_markup=campaigns_list_keyboard(campaigns),
    )


def _login_error_hint(exc: Exception) -> str:
    return friendly_error(exc) + "\n\n/login — попробовать снова."


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _deny(update):
        return ConversationHandler.END
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return ConversationHandler.END
    await msg.reply_text("⏳ Запускаю браузер для входа на HH...")
    try:
        hint = await asyncio.to_thread(bot_services.start_login)
        await msg.reply_text(
            step_header("Вход в HH", 1, 2, hint),
            reply_markup=cancel_inline_keyboard(),
        )
        return LOGIN_PHONE
    except Exception as exc:
        await asyncio.to_thread(bot_services.cancel_login)
        await msg.reply_text(_login_error_hint(exc), reply_markup=retry_keyboard("login"))
        return ConversationHandler.END


async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    try:
        hint = await asyncio.to_thread(bot_services.submit_login_phone, phone)
        await update.message.reply_text(
            step_header("Вход в HH", 2, 2, hint),
            reply_markup=cancel_inline_keyboard(),
        )
        return LOGIN_CODE
    except Exception as exc:
        await asyncio.to_thread(bot_services.cancel_login)
        await update.message.reply_text(_login_error_hint(exc), reply_markup=retry_keyboard("login"))
        return ConversationHandler.END


async def login_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    try:
        msg = await asyncio.to_thread(bot_services.submit_login_code, code)
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
        await _send_dashboard(update, context)
    except Exception as exc:
        await asyncio.to_thread(bot_services.cancel_login)
        await update.message.reply_text(_login_error_hint(exc), reply_markup=retry_keyboard("login"))
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await asyncio.to_thread(bot_services.cancel_login)
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query:
        await update.callback_query.answer()
    if target:
        await target.reply_text("Вход отменён.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def logout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    await update.message.reply_text(
        "Выйти из HH и удалить сессию?",
        reply_markup=confirm_logout_keyboard(),
    )


async def new_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await _deny(update):
        return ConversationHandler.END
    context.user_data.clear()
    data = await asyncio.to_thread(bot_services.get_dashboard_data)
    if not data["hh_connected"]:
        msg = update.message or update.callback_query.message
        text = "Сначала войдите в HH (шаг 1/3)."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, reply_markup=retry_keyboard("login"))
        else:
            await msg.reply_text(text, reply_markup=retry_keyboard("login"))
        return ConversationHandler.END

    campaigns = data["campaigns"]
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if update.callback_query:
        await update.callback_query.answer()
    await msg.reply_text(
        step_header("Новая кампания", 1, 5, "Выберите пресет или настройте вручную:"),
        reply_markup=new_campaign_entry_keyboard(campaigns),
    )
    return NEW_PRESET


async def new_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        step_header("Новая кампания", 2, 5, "Введите поисковый запрос (например: Python аналитик):"),
        reply_markup=cancel_inline_keyboard(),
    )
    return NEW_QUERY


async def new_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["search_query"] = update.message.text.strip()
    await update.message.reply_text(
        step_header("Новая кампания", 3, 5, "Введите лимит откликов (1–500):"),
        reply_markup=cancel_inline_keyboard(),
    )
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
    await update.message.reply_text(
        step_header("Новая кампания", 4, 5, "Выберите регион:"),
        reply_markup=area_keyboard(),
    )
    return NEW_AREA


async def _show_campaign_preview(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    if "cover_letter" not in context.user_data:
        context.user_data["cover_letter"] = settings.default_cover_letter
    preview = format_campaign_preview(context.user_data)
    await query.edit_message_text(preview, reply_markup=confirm_campaign_keyboard())


async def new_area_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    area_id = query.data.split(":", 1)[1]
    context.user_data["area_id"] = area_id or None
    context.user_data.setdefault("cover_letter", settings.default_cover_letter)
    await _show_campaign_preview(query, context)
    return NEW_CONFIRM


async def new_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["cover_letter"] = update.message.text.strip()
    preview = format_campaign_preview(context.user_data)
    await update.message.reply_text(
        step_header("Новая кампания", 5, 5, "Письмо сохранено.\n\n" + preview),
        reply_markup=confirm_campaign_keyboard(),
    )
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
            f"✅ Кампания создана: #{campaign.id} {campaign.name}\n\n"
            + bot_services.format_campaign_short(campaign),
            reply_markup=campaign_actions_keyboard(campaign.id, campaign.status),
        )
    except Exception as exc:
        await query.edit_message_text(friendly_error(exc))
    return ConversationHandler.END


async def new_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Создание отменено.")
    elif update.message:
        await update.message.reply_text("Создание отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def repeat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    campaign_id = int(query.data.split(":", 1)[1])
    source = await asyncio.to_thread(bot_services.get_campaign, campaign_id)
    if not source:
        await query.edit_message_text("Кампания не найдена.")
        return ConversationHandler.END
    context.user_data.update({
        "name": f"{source.name} (копия)",
        "search_query": source.search_query,
        "area_id": source.area_id,
        "apply_limit": source.apply_limit,
        "cover_letter": source.cover_letter or settings.default_cover_letter,
    })
    await query.edit_message_text(format_campaign_preview(context.user_data))
    await query.message.reply_text(
        step_header("Новая кампания", 5, 5, "Проверьте копию и подтвердите:"),
        reply_markup=confirm_campaign_keyboard(),
    )
    return NEW_CONFIRM


async def preset_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    if key == "manual":
        await query.edit_message_text(
            step_header("Новая кампания", 2, 5, "Введите название кампании:"),
        )
        return NEW_NAME

    idx = int(key)
    preset = await asyncio.to_thread(bot_services.apply_preset, idx)
    context.user_data.update(preset)
    await query.edit_message_text(format_campaign_preview(context.user_data))
    await query.message.reply_text(
        step_header("Новая кампания", 5, 5, "Проверьте пресет и подтвердите:"),
        reply_markup=confirm_campaign_keyboard(),
    )
    return NEW_CONFIRM


async def letter_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    action = query.data.split(":", 1)[1]
    await query.answer()

    if action == "preview":
        letter = context.user_data.get("cover_letter") or settings.default_cover_letter
        await query.message.reply_text(format_cover_letter_preview(letter))
        return NEW_CONFIRM
    if action == "default":
        context.user_data["cover_letter"] = settings.default_cover_letter
        await _show_campaign_preview(query, context)
        return NEW_CONFIRM
    if action == "edit":
        await query.message.reply_text(
            step_header("Новая кампания", 5, 5, "Отправьте текст сопроводительного письма:"),
            reply_markup=cancel_inline_keyboard(),
        )
        return NEW_COVER
    return NEW_CONFIRM


async def campaign_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    query = update.callback_query
    await query.answer()
    action, _, cid = query.data.partition(":")
    if not cid.isdigit():
        return
    campaign_id = int(cid)

    try:
        if action == "open":
            campaign = await asyncio.to_thread(bot_services.get_campaign, campaign_id)
            if not campaign:
                raise ValueError("Кампания не найдена")
            await query.edit_message_text(
                bot_services.format_campaign_short(campaign),
                reply_markup=campaign_actions_keyboard(campaign.id, campaign.status),
            )
            return

        if action == "start":
            campaign = await asyncio.to_thread(bot_services.start_campaign, campaign_id)
            text = f"▶️ Кампания #{campaign.id} запущена"
            start_progress_updates(
                context.application,
                chat_id=query.message.chat_id,
                campaign_id=campaign.id,
                message_id=query.message.message_id,
            )
        elif action == "stop":
            stop_progress_updates(campaign_id)
            campaign = await asyncio.to_thread(bot_services.stop_campaign, campaign_id)
            text = f"⏹ Кампания #{campaign.id} остановлена"
        elif action == "delete":
            await query.edit_message_text(
                f"Удалить кампанию #{campaign_id}?",
                reply_markup=confirm_delete_keyboard(campaign_id),
            )
            return
        elif action == "delete_yes":
            await asyncio.to_thread(bot_services.delete_campaign, campaign_id)
            campaigns = await asyncio.to_thread(bot_services.list_campaigns)
            await query.edit_message_text(
                f"🗑 Кампания #{campaign_id} удалена.\n\n" + format_campaigns_overview(campaigns),
                reply_markup=campaigns_list_keyboard(campaigns),
            )
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
        await query.message.reply_text(friendly_error(exc), reply_markup=retry_keyboard("campaigns"))


async def ui_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "dash:refresh":
        await _send_dashboard(update, context, edit=True)
    elif data == "dash:campaigns":
        campaigns = await asyncio.to_thread(bot_services.list_campaigns)
        await query.edit_message_text(
            format_campaigns_overview(campaigns),
            reply_markup=campaigns_list_keyboard(campaigns),
        )
    elif data == "onboard:skip":
        await query.edit_message_text("Онбординг пропущен. Откройте 🏠 Главная когда будете готовы.")
    elif data == "logout:yes":
        msg = await asyncio.to_thread(bot_services.logout)
        await query.edit_message_text(msg)
        await query.message.reply_text("Сессия удалена.", reply_markup=main_menu_keyboard())
    elif data == "logout:no":
        await query.edit_message_text("Выход отменён.")
    elif data.startswith("retry:"):
        action = data.split(":", 1)[1]
        if action == "campaigns":
            campaigns = await asyncio.to_thread(bot_services.list_campaigns)
            await query.message.reply_text(
                format_campaigns_overview(campaigns),
                reply_markup=campaigns_list_keyboard(campaigns),
            )
        else:
            await query.message.reply_text(
                f"Используйте /{action} или кнопку меню.",
                reply_markup=main_menu_keyboard(),
            )


async def start_conv_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await start_cmd(update, context)
    return ConversationHandler.END


async def menu_simple_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reset_state(update, context)
    if await _deny(update):
        return
    text = update.message.text.strip()
    if text == "🏠 Главная":
        await dashboard_cmd(update, context)
    elif text == "📋 Кампании":
        await campaigns_cmd(update, context)
    elif text == "🚪 Выйти из HH":
        await logout_cmd(update, context)


def build_application(for_polling: bool = False) -> Application:
    if not settings.telegram_bot_token.strip():
        env_path = ROOT_DIR / ".env"
        raise RuntimeError(
            f"TELEGRAM_BOT_TOKEN не задан.\n"
            f"Создайте файл {env_path} и добавьте строку:\n"
            f"TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather"
        )

    conv_fallbacks = [
        CommandHandler("start", start_conv_fallback),
        CommandHandler("cancel", login_cancel),
        CallbackQueryHandler(new_cancel, pattern=r"^flow:cancel$"),
        MessageHandler(filters.Regex("^🔐 Войти$"), login_start),
        MessageHandler(filters.Regex("^➕ Новая кампания$"), new_start),
        MessageHandler(MENU_SIMPLE, menu_simple_handler),
        MessageHandler(MENU_HOME, menu_simple_handler),
    ]

    login_conv = ConversationHandler(
        entry_points=[
            CommandHandler("login", login_start),
            MessageHandler(filters.Regex("^🔐 Войти$"), login_start),
            CallbackQueryHandler(login_start, pattern=r"^onboard:login$"),
            CallbackQueryHandler(login_start, pattern=r"^retry:login$"),
        ],
        states={
            LOGIN_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            LOGIN_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_code)],
        },
        fallbacks=conv_fallbacks,
    )

    new_conv = ConversationHandler(
        entry_points=[
            CommandHandler("new", new_start),
            MessageHandler(filters.Regex("^➕ Новая кампания$"), new_start),
            CallbackQueryHandler(new_start, pattern=r"^onboard:new$"),
            CallbackQueryHandler(new_start, pattern=r"^retry:new$"),
        ],
        states={
            NEW_PRESET: [
                CallbackQueryHandler(preset_cb, pattern=r"^preset:"),
                CallbackQueryHandler(repeat_cb, pattern=r"^repeat:"),
            ],
            NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_name)],
            NEW_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_query)],
            NEW_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_limit)],
            NEW_AREA: [CallbackQueryHandler(new_area_cb, pattern=r"^area:")],
            NEW_CONFIRM: [
                CallbackQueryHandler(new_confirm_cb, pattern=r"^confirm:"),
                CallbackQueryHandler(letter_cb, pattern=r"^letter:"),
            ],
            NEW_COVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_cover)],
        },
        fallbacks=conv_fallbacks,
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

        await register_bot_commands(application)

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
        .post_init(_on_bot_start)
    )
    app = builder.build()
    app.add_error_handler(_on_error)

    for handler in (
        CommandHandler("start", start_cmd),
        CommandHandler("help", help_cmd),
        CommandHandler("ping", ping_cmd),
        CommandHandler("status", status_cmd),
        CommandHandler("campaigns", campaigns_cmd),
        CommandHandler("logout", logout_cmd),
        CommandHandler("cancel", login_cancel),
        MessageHandler(MENU_HOME, menu_simple_handler),
        MessageHandler(MENU_SIMPLE, menu_simple_handler),
    ):
        app.add_handler(handler, group=PRIORITY_GROUP)

    app.add_handler(login_conv, group=DEFAULT_GROUP)
    app.add_handler(new_conv, group=DEFAULT_GROUP)
    app.add_handler(
        CallbackQueryHandler(campaign_callback, pattern=r"^(open|start|stop|delete|delete_yes|stats|logs):"),
        group=DEFAULT_GROUP,
    )
    app.add_handler(
        CallbackQueryHandler(ui_callback, pattern=r"^(dash:|onboard:|logout:|retry:)"),
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
                logger.error("Не удалось подключиться к api.telegram.org. Retry через 30s...")
                time.sleep(30)
                continue
            logger.exception("Bot crashed, retry in 15s")
            time.sleep(15)
