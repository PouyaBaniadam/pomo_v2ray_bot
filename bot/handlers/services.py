import io
import qrcode
from django.utils import timezone
from aiogram import (
    Router,
    F,
)
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
from bot.keyboards import (
    BTN_MY_SERVICES,
    get_service_actions_kb,
)
from core.jalali import format_jalali
from core.services import (
    get_user_orders,
    get_bot_settings,
    get_order_by_id,
)

router = Router()


@router.message(
    F.text == BTN_MY_SERVICES,
)
async def show_my_services(
    message: Message,
):
    orders = await get_user_orders(message.from_user.id)
    bot_settings = await get_bot_settings()

    if not orders:
        if bot_settings.sticker_empty:
            try:
                await message.answer_sticker(bot_settings.sticker_empty)
            except Exception:
                pass

        empty_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="بزن بریم بخریم 🛒",
                        callback_data="go_to_buy_from_empty",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="هدیه‌های من 🎁",
                        callback_data="go_to_referral_from_empty",
                    )
                ],
            ]
        )
        await message.answer(
            "متاسفانه شما سرویس فعالی ندارید.",
            reply_markup=empty_kb,
            parse_mode="HTML",
        )
        return

    now = timezone.now()
    for idx, order in enumerate(orders, 1):
        status_badge = "✅ فعال" if order.status == 'active' else "⏳ در انتظار صدور کانفیگ"
        plan_title = order.plan.title if order.plan else order.get_order_type_display()
        created_jalali = format_jalali(order.created_at)

        expiry_str = ""
        if order.expires_at:
            exp_jalali = format_jalali(
                order.expires_at,
                include_time=False,
            )
            rem_days = (order.expires_at - now).days
            if rem_days >= 0:
                expiry_str = f"⏳ <b>تاریخ انقضا:</b> {exp_jalali} ({rem_days + 1} روز مانده)\n"
            else:
                expiry_str = f"⏳ <b>وضعیت اعتبار:</b> منقضی شده ({exp_jalali})\n"

        card_text = (
            f"📡 <b>سرویس شماره {idx}:</b> <code>{order.custom_name}</code>\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"📊 <b>وضعیت:</b> {status_badge}\n"
            f"📦 <b>بسته:</b> {plan_title}\n"
            f"📅 <b>تاریخ ثبت:</b> {created_jalali}\n"
            f"{expiry_str}"
        )

        if order.status == 'active' and order.config_link:
            card_text += (
                f"\n🔗 <b>لینک کانفیگ / اشتراک:</b>\n"
                f"<code>{order.config_link}</code>"
            )
            await message.answer(
                card_text,
                reply_markup=get_service_actions_kb(
                    order.id,
                    order.config_link,
                ),
                parse_mode="HTML",
            )
        else:
            card_text += "\n⚠️ <i>لینک کانفیگ به زودی توسط مدیریت ارسال می‌گردد.</i>"
            await message.answer(
                card_text,
                parse_mode="HTML",
            )


@router.callback_query(
    F.data.startswith("get_qr:"),
)
async def send_service_qr_code(
    callback: CallbackQuery,
):
    order_id = int(callback.data.split(":")[1])
    order = await get_order_by_id(order_id)

    if not order or order.user.telegram_id != callback.from_user.id or not order.config_link:
        await callback.answer(
            "لینک کانفیگ برای این سرویس یافت نشد.",
            show_alert=True,
        )
        return

    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=3,
    )
    qr.add_data(order.config_link.strip())
    qr.make(fit=True)
    img = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    buf = io.BytesIO()
    img.save(
        buf,
        format="PNG",
    )
    buf.seek(0)

    photo_file = BufferedInputFile(
        buf.read(),
        filename=f"qr_{order.custom_name}.png",
    )
    await callback.message.answer_photo(
        photo=photo_file,
        caption=(
            f"📷 <b>QR Code سرویس:</b> <code>{order.custom_name}</code>\n\n"
            f"می‌توانید این بارکد را مستقیماً در اپلیکیشن V2rayNG یا Streisand اسکن کنید."
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data == "go_to_buy_from_empty",
)
async def empty_to_buy_redirect(
    callback: CallbackQuery,
    state,
):
    from bot.handlers.buy import start_buy_service
    try:
        await callback.message.delete()
    except Exception:
        pass
    await start_buy_service(
        callback.message,
        state,
    )
    await callback.answer()


@router.callback_query(
    F.data == "go_to_referral_from_empty",
)
async def empty_to_referral_redirect(
    callback: CallbackQuery,
    bot,
):
    from bot.handlers.gifts import show_referral_gift_menu_by_user
    try:
        await callback.message.delete()
    except Exception:
        pass
    await show_referral_gift_menu_by_user(
        callback.message,
        callback.from_user.id,
        bot,
    )
    await callback.answer()