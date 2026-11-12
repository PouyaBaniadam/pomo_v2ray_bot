from aiogram import (
    Router,
    F,
    Bot,
)
from aiogram.types import (
    Message,
    CallbackQuery,
)
from django.conf import settings

from bot.keyboards import (
    BTN_FREE_TEST_PREFIX,
    BTN_REFERRAL_GIFT,
    get_main_menu_keyboard,
    get_referral_inline_kb,
    get_admin_send_config_kb,
    get_service_actions_kb,
)
from core.jalali import format_jalali
from core.services import (
    claim_free_test_order,
    get_user_profile_data,
    get_user_referrals_list,
    get_bot_settings,
    get_all_admin_ids,
)

router = Router()


@router.message(
    F.text.startswith(BTN_FREE_TEST_PREFIX),
)
async def handle_free_test_request(
    message: Message,
    bot: Bot,
):
    bot_settings = await get_bot_settings()
    success, delivery_type, order = await claim_free_test_order(message.from_user.id)

    if not success:
        if delivery_type == "disabled":
            await message.answer(
                "⚠️ <b>دریافت تست رایگان در حال حاضر غیرفعال است.</b>",
                reply_markup=get_main_menu_keyboard(
                    show_free_test=False,
                    free_test_title=bot_settings.free_test_title,
                ),
                parse_mode="HTML",
            )
            return

        await message.answer(
            "⚠️ <b>شما قبلاً از تست رایگان خود استفاده کرده‌اید!</b>\n"
            "هر کاربر (بر اساس آیدی عددی تلگرام) تنها یک‌بار امکان دریافت تست رایگان دارد.",
            reply_markup=get_main_menu_keyboard(
                show_free_test=False,
                free_test_title=bot_settings.free_test_title,
            ),
            parse_mode="HTML",
        )
        return

    admin_ids = await get_all_admin_ids()
    test_title = bot_settings.free_test_title
    order_date = format_jalali(order.created_at)

    if delivery_type == "instant":
        exp_str = format_jalali(
            order.expires_at,
            include_time=False,
        )
        await message.answer(
            f"🎁 <b>تست رایگان ({test_title}) شما به صورت خودکار فعال شد!</b>",
            reply_markup=get_main_menu_keyboard(
                show_free_test=False,
                free_test_title=test_title,
            ),
            parse_mode="HTML",
        )
        await message.answer(
            f"🎉 <b>اطلاعات سرویس تست رایگان شما:</b>\n\n"
            f"🏷 نام سرویس: <code>{order.custom_name}</code>\n"
            f"📦 مشخصات: {test_title}\n"
            f"📅 تاریخ دریافت: <b>{order_date}</b>\n"
            f"⏳ تاریخ انقضا: <b>{exp_str}</b>\n\n"
            f"🔗 <b>لینک کانفیگ / اشتراک شما:</b>\n"
            f"<code>{order.config_link}</code>\n\n"
            f"💡 از دکمه‌های زیر می‌توانید لینک را با یک کلیک کپی کنید یا QR Code آن را دریافت نمایید:",
            reply_markup=get_service_actions_kb(
                order.id,
                order.config_link,
            ),
            parse_mode="HTML",
        )
        for aid in admin_ids:
            try:
                await bot.send_message(
                    aid,
                    f"✅ <b>تحویل خودکار تست رایگان (#{order.id})</b>\n\n"
                    f"📅 تاریخ: <b>{order_date}</b>\n"
                    f"👤 کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
                    f"🏷 نام سرویس: <code>{order.custom_name}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return

    await message.answer(
        f"🎁 <b>درخواست تست رایگان ({test_title}) با موفقیت ثبت شد!</b>\n\n"
        f"🏷 نام سرویس تست شما: <code>{order.custom_name}</code>\n"
        f"📅 تاریخ ثبت: <b>{order_date}</b>\n"
        f"⏳ لینک کانفیگ تست رایگان به زودی برای شما ارسال می‌شود و از بخش «🔍 سرویس (های) من» نیز قابل مشاهده خواهد بود.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=False,
            free_test_title=test_title,
        ),
        parse_mode="HTML",
    )

    for aid in admin_ids:
        try:
            await bot.send_message(
                aid,
                f"🎁 <b>درخواست تست رایگان جدید! (#{order.id})</b>\n\n"
                f"📅 تاریخ: <b>{order_date}</b>\n"
                f"👤 کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
                f"🏷 نام سرویس: <code>{order.custom_name}</code>\n\n"
                f"👇 روی دکمه زیر بزنید و لینک تست را بفرستید تا درجا برای کاربر فعال شود:",
                reply_markup=get_admin_send_config_kb(order.id),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(
    F.text == BTN_REFERRAL_GIFT,
)
async def show_referral_gift_menu(
    message: Message,
    bot: Bot,
):
    await show_referral_gift_menu_by_user(
        message,
        message.from_user.id,
        bot,
    )


async def show_referral_gift_menu_by_user(
    msg: Message,
    user_id: int,
    bot: Bot,
):
    profile = await get_user_profile_data(user_id)
    bot_settings = await get_bot_settings()

    if bot_settings.sticker_wallet:
        try:
            await msg.answer_sticker(bot_settings.sticker_wallet)
        except Exception:
            pass

    bot_info = await bot.get_me()
    bot_username = bot_info.username or getattr(settings, 'BOT_USERNAME', 'Bot')
    invite_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    req_count = max(
        1,
        bot_settings.referral_required_count,
    )
    gift_title = bot_settings.referral_gift_title

    total_refs = profile['valid_referrals_count']
    gifts_received = profile['referral_gifts_received']
    current_cycle_progress = total_refs % req_count
    remaining_for_next = req_count - current_cycle_progress

    text = (
        f"🎉 <b>اشتراک رایگان با دعوت دوستان</b>\n\n"
        f"👥 به ازای هر {req_count} دعوت معتبر، ۱ اشتراک هدیه ({gift_title}) می‌گیری!\n"
        f"🔁 این هدیه تکرارپذیره (فقط یک‌بار نیست).\n\n"
        f"📊 دعوت‌های معتبر تا الان: <b>{current_cycle_progress}/{req_count}</b>\n"
        f"🎁 هدیه‌های گرفته‌شده: <b>{gifts_received}</b>\n"
        f"⏳ مانده تا هدیه بعدی: <b>{remaining_for_next} دعوت</b>\n\n"
        f"🔗 لینک اختصاصی دعوت تو:\n"
        f"<code>{invite_link}</code>"
    )

    await msg.answer(
        text,
        reply_markup=get_referral_inline_kb(
            invite_link=invite_link,
            share_text=bot_settings.referral_share_text,
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "my_referrals_list",
)
async def show_my_referrals_callback(
    callback: CallbackQuery,
):
    referrals = await get_user_referrals_list(callback.from_user.id)
    if not referrals:
        await callback.answer(
            "شما هنوز هیچ کاربری را دعوت نکرده‌اید!",
            show_alert=True,
        )
        return

    text = "👥 <b>لیست آخرین کاربران دعوت شده توسط شما (به تاریخ شمسی):</b>\n➖➖➖➖➖➖➖➖➖➖\n"
    for idx, ref_user in enumerate(referrals, 1):
        name = ref_user.full_name or "کاربر تلگرام"
        joined_jalali = format_jalali(
            ref_user.created_at,
            include_time=False,
        )
        text += f"{idx}. {name} (<code>{ref_user.telegram_id}</code>) | 📅 {joined_jalali}\n"

    await callback.message.answer(
        text,
        parse_mode="HTML",
    )
    await callback.answer()