import asyncio
import logging
from aiogram import (
    Router,
    F,
    Dispatcher,
    Bot,
)
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    ErrorEvent,
    Update,
    BotCommand,
    BotCommandScopeChat,
)
from aiogram.fsm.context import FSMContext

from bot.keyboards import (
    BTN_USER_ACCOUNT,
    BTN_TUTORIALS,
    BTN_SUPPORT,
    BTN_CANCEL_ACTION,
    get_main_menu_keyboard,
    get_user_account_inline_kb,
    get_tutorials_inline_kb,
    get_support_inline_kb,
    get_cancel_reply_keyboard,
    get_admin_reply_ticket_kb,
    get_admin_sticker_assign_kb,
    get_force_join_kb,
)
from bot.middlewares import (
    PENDING_USER_EVENTS,
    get_unjoined_channels,
)
from bot.states import SupportState
from core.jalali import format_jalali
from core.services import (
    upsert_telegram_user,
    get_user_profile_data,
    get_bot_settings,
    create_support_ticket,
    set_bot_sticker,
    get_all_admin_ids,
    count_user_open_tickets,
)

logger = logging.getLogger(__name__)
router = Router()


@router.message(
    CommandStart(),
)
async def cmd_start(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    await state.clear()

    referrer_id = None
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
        except ValueError:
            referrer_id = None

    user, _ = await upsert_telegram_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        referrer_id=referrer_id,
    )

    admin_ids = await get_all_admin_ids()
    try:
        if user.telegram_id in admin_ids:
            await bot.set_my_commands(
                commands=[
                    BotCommand(
                        command="start",
                        description="شروع مجدد 🔄",
                    ),
                    BotCommand(
                        command="admin",
                        description="پنل مدیریت تلگرام 🛠",
                    ),
                ],
                scope=BotCommandScopeChat(
                    chat_id=user.telegram_id,
                ),
            )
        else:
            await bot.delete_my_commands(
                scope=BotCommandScopeChat(
                    chat_id=user.telegram_id,
                ),
            )
    except Exception:
        pass

    bot_settings = await get_bot_settings()

    if bot_settings.sticker_welcome:
        try:
            await message.answer_sticker(bot_settings.sticker_welcome)
        except Exception:
            pass

    show_test = (not user.used_free_test) and bot_settings.free_test_enabled
    await message.answer(
        bot_settings.welcome_text or "درود، کاربر گرامی خوش اومدی!",
        reply_markup=get_main_menu_keyboard(
            show_free_test=show_test,
            free_test_title=bot_settings.free_test_title,
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "verify_join",
)
async def verify_channel_join_callback(
    callback: CallbackQuery,
    bot: Bot,
    dispatcher: Dispatcher,
):
    unjoined = await get_unjoined_channels(
        bot=bot,
        user_id=callback.from_user.id,
    )

    if unjoined:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=get_force_join_kb(unjoined),
            )
        except Exception:
            pass
        await callback.answer(
            f"⚠️ شما هنوز در {len(unjoined)} کانال عضو نشده‌اید! لطفاً ابتدا عضو شوید و دوباره امتحان کنید.",
            show_alert=True,
        )
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    last_event = PENDING_USER_EVENTS.pop(
        callback.from_user.id,
        None,
    )

    if isinstance(last_event, Message):
        await callback.answer("✅ عضویت تایید شد! در حال ادامه...")
        synthetic_update = Update(
            update_id=999999999,
            message=last_event,
        )
        asyncio.create_task(
            dispatcher.feed_update(
                bot,
                synthetic_update,
            )
        )
        return

    if isinstance(last_event, CallbackQuery):
        resumed_cb = last_event.model_copy(
            update={"id": callback.id},
        )
        synthetic_update = Update(
            update_id=999999999,
            callback_query=resumed_cb,
        )
        asyncio.create_task(
            dispatcher.feed_update(
                bot,
                synthetic_update,
            )
        )
        return

    user, _ = await upsert_telegram_user(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    bot_settings = await get_bot_settings()
    show_test = (not user.used_free_test) and bot_settings.free_test_enabled

    await callback.answer("✅ عضویت شما تایید شد!")
    await callback.message.answer(
        f"✅ <b>عضویت شما تایید شد!</b>\n{bot_settings.welcome_text}",
        reply_markup=get_main_menu_keyboard(
            show_free_test=show_test,
            free_test_title=bot_settings.free_test_title,
        ),
        parse_mode="HTML",
    )


@router.message(
    F.text == BTN_USER_ACCOUNT,
)
async def show_user_account(
    message: Message,
):
    profile = await get_user_profile_data(message.from_user.id)
    bot_settings = await get_bot_settings()

    if bot_settings.sticker_account:
        try:
            await message.answer_sticker(bot_settings.sticker_account)
        except Exception:
            pass

    text = (
        f"👤 <b>حساب کاربری</b>\n\n"
        f"📎 نام کاربری: {profile['username']}\n"
        f"🔢 آیدی عددی: <code>{profile['telegram_id']}</code>\n"
        f"📅 تاریخ عضویت: <b>{profile['created_at_jalali']}</b>\n"
        f"📦 سرویس‌های فعال: {profile['active_orders_count']} عدد\n"
        f"👥 دعوت‌های موفق: {profile['valid_referrals_count']} نفر\n"
        f"💰 موجودی کیف پول: {profile['wallet_balance']:,} تومان\n\n"
        f"✔️ برای افزایش موجودی از دکمه زیر استفاده کنید."
    )
    await message.answer(
        text,
        reply_markup=get_user_account_inline_kb(),
        parse_mode="HTML",
    )


@router.message(
    F.text == BTN_TUTORIALS,
)
async def show_tutorials(
    message: Message,
):
    bot_settings = await get_bot_settings()
    text = (
        "📚 <b>راهنمای اتصال به سرویس‌ها</b>\n\n"
        "لطفاً سیستم‌عامل دستگاه خود را از دکمه‌های زیر انتخاب کنید تا ویدیو و آموزش قدم‌به‌قدم اتصال برایتان باز شود:"
    )
    await message.answer(
        text,
        reply_markup=get_tutorials_inline_kb(
            bot_settings.tutorial_android_url,
            bot_settings.tutorial_ios_url,
            bot_settings.tutorial_windows_url,
        ),
        parse_mode="HTML",
    )


@router.message(
    F.text == BTN_SUPPORT,
)
async def show_support_menu(
    message: Message,
):
    bot_settings = await get_bot_settings()
    text = (
        "💬 <b>بخش پشتیبانی</b>\n\n"
        "در صورت بروز هرگونه سوال یا مشکل در اتصال یا پرداخت، می‌توانید مستقیماً به آیدی پشتیبان پیام دهید یا داخل ربات تیکت ثبت کنید:"
    )
    await message.answer(
        text,
        reply_markup=get_support_inline_kb(
            bot_settings.support_username,
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "open_support_ticket",
)
async def start_support_ticket(
    callback: CallbackQuery,
    state: FSMContext,
):
    bot_settings = await get_bot_settings()
    open_count = await count_user_open_tickets(callback.from_user.id)
    max_open = max(
        1,
        bot_settings.max_open_tickets,
    )
    if open_count >= max_open:
        await callback.answer(
            f"⏳ شما در حال حاضر {open_count} تیکت باز در انتظار پاسخ دارید! لطفاً منتظر پاسخ پشتیبان بمانید.",
            show_alert=True,
        )
        return

    await state.set_state(SupportState.waiting_for_message)
    await callback.message.answer(
        "✍️ لطفاً پیام، سوال یا مشکل خود را در قالب یک متن بنویسید و ارسال کنید:\n"
        "<i>(برای انصراف روی دکمه بازگشت پایین صفحه کلیک کنید)</i>",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(
    SupportState.waiting_for_message,
    F.text == BTN_CANCEL_ACTION,
)
async def cancel_support_ticket(
    message: Message,
    state: FSMContext,
):
    await state.clear()
    profile = await get_user_profile_data(message.from_user.id)
    await message.answer(
        "✅ ثبت تیکت لغو شد و به منوی اصلی بازگشتید.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
    )


@router.message(
    SupportState.waiting_for_message,
    F.text,
)
async def save_support_ticket(
    message: Message,
    state: FSMContext,
):
    bot_settings = await get_bot_settings()
    open_count = await count_user_open_tickets(message.from_user.id)
    max_open = max(
        1,
        bot_settings.max_open_tickets,
    )
    profile = await get_user_profile_data(message.from_user.id)

    if open_count >= max_open:
        await state.clear()
        await message.answer(
            f"⏳ <b>شما هم‌اکنون {open_count} تیکت در انتظار پاسخ دارید!</b>\n"
            f"لطفاً تا زمان پاسخ‌گویی پشتیبانی به تیکت‌های قبلی خود صبر کنید.",
            reply_markup=get_main_menu_keyboard(
                show_free_test=not profile['used_free_test'],
                free_test_title=profile['free_test_title'],
            ),
            parse_mode="HTML",
        )
        return

    if len(message.text) > 2000:
        await message.answer(
            "⚠️ متن پیام شما بیش از حد طولانی است (حداکثر ۲۰۰۰ کاراکتر). لطفاً پیام خود را خلاصه‌تر ارسال کنید:"
        )
        return

    ticket = await create_support_ticket(
        message.from_user.id,
        message.text,
    )
    await state.clear()
    tkt_date = format_jalali(ticket.created_at)

    await message.answer(
        f"✅ <b>تیکت شما با شماره <code>#{ticket.id}</code> در تاریخ {tkt_date} ثبت شد!</b>\n"
        f"پشتیبانان ما در اسرع وقت بررسی کرده و پاسخ را همین‌جا برایتان ارسال می‌کنند.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
        parse_mode="HTML",
    )

    admin_ids = await get_all_admin_ids()
    for aid in admin_ids:
        try:
            await message.bot.send_message(
                aid,
                f"🔔 <b>تیکت پشتیبانی جدید (#{ticket.id})</b>\n"
                f"📅 تاریخ: <b>{tkt_date}</b>\n"
                f"👤 کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
                f"📝 متن پیام:\n{message.text}",
                reply_markup=get_admin_reply_ticket_kb(ticket.id),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(
    F.sticker,
)
async def get_sticker_file_id_for_admin(
    message: Message,
):
    admin_ids = await get_all_admin_ids()
    if message.from_user.id in admin_ids:
        await message.reply(
            f"🎯 <b>استیکر دریافت شد!</b>\n"
            f"کد استیکر:\n<code>{message.sticker.file_id}</code>\n\n"
            f"👇 با کلیک روی هر کدام از دکمه‌های زیر، این استیکر به صورت خودکار برای همان بخش تنظیم می‌شود:",
            reply_markup=get_admin_sticker_assign_kb(),
            parse_mode="HTML",
        )


@router.callback_query(
    F.data.startswith("set_stk:"),
)
async def assign_sticker_callback(
    callback: CallbackQuery,
):
    from bot.handlers.admin_panel import is_admin
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return

    field_name = callback.data.split(":")[1]
    if not callback.message.reply_to_message or not callback.message.reply_to_message.sticker:
        await callback.answer(
            "استیکر مرجع یافت نشد!",
            show_alert=True,
        )
        return

    file_id = callback.message.reply_to_message.sticker.file_id
    await set_bot_sticker(
        field_name,
        file_id,
    )
    await callback.answer(
        "✅ استیکر با موفقیت در دیتابیس ذخیره شد!",
        show_alert=True,
    )


@router.error()
async def global_error_handler(
    event: ErrorEvent,
):
    logger.exception(f"Unhandled exception inside bot: {event.exception}")
    if event.update.message:
        try:
            await event.update.message.answer(
                "⚠️ خطایی در پردازش درخواست رخ داد. لطفاً مجدداً تلاش کنید یا /start را بزنید."
            )
        except Exception:
            pass