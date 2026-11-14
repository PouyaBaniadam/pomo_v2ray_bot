from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
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


@router.message(F.text.startswith(BTN_FREE_TEST_PREFIX))
async def handle_free_test_request(message: Message, bot: Bot):
    bot_settings = await get_bot_settings()
    success, delivery_type, order = await claim_free_test_order(message.from_user.id)

    if not success:
        if delivery_type == "disabled":
            await message.answer(
                "⚠️ دریافت تست رایگان در حال حاضر غیرفعال است.",
                reply_markup=get_main_menu_keyboard(
                    show_free_test=False,
                    free_test_title=bot_settings.free_test_title,
                ),
                parse_mode="HTML",
            )
            return

        await message.answer(
            "⚠️ شما قبلاً از تست رایگان استفاده کرده‌اید.",
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
        await message.answer(
            "🎁 تست رایگان شما فعال شد.",
            reply_markup=get_main_menu_keyboard(
                show_free_test=False,
                free_test_title=test_title,
            ),
            parse_mode="HTML",
        )
        await message.answer(
            f"🎉 <b>سرویس تست رایگان شما آماده است!</b>\n\n"
            f"• نام سرویس: <code>{order.panel_username or order.custom_name}</code>\n"
            f"• مشخصات: {test_title}\n"
            f"• مدت اعتبار: <b>{bot_settings.free_test_days} روز</b>\n\n"
            f"🔗 <b>لینک اشتراک:</b>\n"
            f"<code>{order.config_link}</code>",
            reply_markup=get_service_actions_kb(order.id, order.config_link),
            parse_mode="HTML",
        )
        for aid in admin_ids:
            try:
                await bot.send_message(
                    aid,
                    f"✅ <b>تحویل خودکار تست رایگان (#{order.id})</b>\n\n"
                    f"• تاریخ: <b>{order_date}</b>\n"
                    f"• کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
                    f"• نام سرویس: <code>{order.panel_username or order.custom_name}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return

    await message.answer(
        f"🎁 <b>درخواست تست رایگان ثبت شد!</b>\n\n"
        f"• نام سرویس: <code>{order.custom_name}</code>\n"
        f"⏳ لینک تست به زودی برایتان ارسال می‌شود.",
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
                f"🎁 <b>درخواست تست رایگان (#{order.id})</b>\n\n"
                f"• تاریخ: <b>{order_date}</b>\n"
                f"• کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
                f"• نام سرویس: <code>{order.custom_name}</code>",
                reply_markup=get_admin_send_config_kb(order.id),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(F.text.in_({BTN_REFERRAL_GIFT, "🎉 اشتراک رایگان (دعوت دوستان)"}))
async def show_referral_gift_menu(message: Message, bot: Bot):
    await show_referral_gift_menu_by_user(message, message.from_user.id, bot)


async def show_referral_gift_menu_by_user(msg: Message, user_id: int, bot: Bot):
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

    req_count = max(1, bot_settings.referral_required_count)
    gift_title = bot_settings.referral_gift_title
    m10_title = bot_settings.referral_milestone_10_title
    m20_title = bot_settings.referral_milestone_20_title

    total_refs = profile['valid_referrals_count']
    gifts_received = profile['referral_gifts_received']
    current_cycle_progress = total_refs % req_count
    remaining_for_next = req_count - current_cycle_progress

    text = (
        f"🎉 <b>دریافت اشتراک رایگان با دعوت دوستان</b>\n\n"
        f"🎁 <b>جوایز دعوت:</b>\n"
        f"• به ازای هر <b>{req_count} دعوت</b>: <b>{gift_title}</b>\n"
        f"• پاداش ویژه <b>نفر ۱۰ام</b>: <b>{m10_title}</b>\n"
        f"• پاداش ویژه <b>نفر ۲۰ام</b>: <b>{m20_title}</b>\n\n"
        f"📊 کل دعوت‌های شما: <b>{total_refs} نفر</b>\n"
        f"⏳ مانده تا هدیه بعدی: <b>{remaining_for_next} دعوت</b>\n"
        f"🎁 هدیه‌های دریافتی: <b>{gifts_received} اشتراک</b>\n\n"
        f"🔗 <b>لینک دعوت اختصاصی شما:</b>\n"
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


@router.callback_query(F.data == "my_referrals_list")
async def show_my_referrals_callback(callback: CallbackQuery):
    referrals = await get_user_referrals_list(callback.from_user.id)
    if not referrals:
        await callback.answer(
            "شما هنوز کاربری را دعوت نکرده‌اید.",
            show_alert=True,
        )
        return

    text = "👥 <b>آخرین کاربران دعوت‌شده توسط شما:</b>\n\n"
    for idx, ref_user in enumerate(referrals, 1):
        name = ref_user.full_name or "کاربر تلگرام"
        joined_jalali = format_jalali(ref_user.created_at, include_time=False)
        text += f"{idx}. {name} (<code>{ref_user.telegram_id}</code>) | 📅 {joined_jalali}\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()