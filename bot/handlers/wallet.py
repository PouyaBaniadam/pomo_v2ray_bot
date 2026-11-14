import os
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from django.conf import settings
from django.utils import timezone

from bot.states import WalletChargeState
from bot.middlewares import check_receipt_upload_cooldown
from bot.keyboards import (
    BTN_CHARGE_WALLET,
    get_main_menu_keyboard,
    get_wallet_preset_amounts_kb,
    get_wallet_custom_amount_kb,
    get_invoice_cancel_kb,
    get_admin_receipt_approval_kb,
    get_admin_send_config_kb,
    get_service_actions_kb,
)
from core.jalali import format_jalali, get_current_jalali_year_month
from core.services import (
    get_bot_settings,
    get_distinct_active_plan_prices,
    create_wallet_transaction,
    update_transaction_receipt,
    cancel_transaction_by_invoice,
    approve_transaction_by_id,
    reject_transaction_by_id,
    get_user_transactions,
    get_user_profile_data,
    get_all_admin_ids,
    count_user_pending_receipts,
)

router = Router()

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}


def optimize_receipt_image_file(file_path: str) -> str:
    try:
        from PIL import Image, ImageOps

        with Image.open(file_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[3])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            max_dimension = 1600
            if img.width > max_dimension or img.height > max_dimension:
                img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            base_no_ext = os.path.splitext(file_path)[0]
            optimized_jpg_path = f"{base_no_ext}.jpg"
            img.save(optimized_jpg_path, format="JPEG", quality=82, optimize=True)

        if optimized_jpg_path != file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return optimized_jpg_path
    except Exception:
        return file_path


@router.message(F.text == BTN_CHARGE_WALLET)
@router.callback_query(F.data == "acc_charge_wallet")
async def start_wallet_charge(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()

    user_id = event.from_user.id
    bot_settings = await get_bot_settings()
    pending_count = await count_user_pending_receipts(user_id)
    max_pending = max(1, bot_settings.max_pending_receipts)
    target_msg = event.message if isinstance(event, CallbackQuery) else event

    if pending_count >= max_pending:
        limit_msg = (
            f"⏳ شما {pending_count} رسید در انتظار تایید دارید.\n"
            f"لطفاً تا بررسی رسیدهای قبلی صبر کنید."
        )
        if isinstance(event, CallbackQuery):
            await event.answer(limit_msg, show_alert=True)
        else:
            await target_msg.answer(limit_msg, parse_mode="HTML")
        return

    await state.set_state(WalletChargeState.selecting_amount)
    prices = await get_distinct_active_plan_prices()

    if bot_settings.sticker_wallet:
        try:
            await target_msg.answer_sticker(bot_settings.sticker_wallet)
        except Exception:
            pass

    text = (
        "💰 <b>افزایش موجودی کیف پول</b>\n\n"
        "مبلغ مورد نظر خود را انتخاب کنید:"
    )
    await target_msg.answer(
        text,
        reply_markup=get_wallet_preset_amounts_kb(prices),
        parse_mode="HTML",
    )
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "back_to_wallet_amounts")
async def back_to_wallet_amounts(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WalletChargeState.selecting_amount)
    prices = await get_distinct_active_plan_prices()
    text = (
        "💰 <b>افزایش موجودی کیف پول</b>\n\n"
        "مبلغ مورد نظر خود را انتخاب کنید:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=get_wallet_preset_amounts_kb(prices),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_wallet_flow")
async def cancel_wallet_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    profile = await get_user_profile_data(callback.from_user.id)
    await callback.message.answer(
        "✅ افزایش موجودی لغو شد.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("charge_amt:"))
async def select_charge_amount(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "custom":
        bot_settings = await get_bot_settings()
        min_amt = bot_settings.min_wallet_charge
        await state.set_state(WalletChargeState.entering_custom_amount)
        await callback.message.edit_text(
            f"✏️ مبلغ مورد نظر را به تومان وارد کنید (حداقل {min_amt:,} تومان):",
            reply_markup=get_wallet_custom_amount_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    amount = int(val)
    await issue_invoice(callback.message, callback.from_user.id, amount, state)
    await callback.answer()


@router.message(WalletChargeState.entering_custom_amount, F.text)
async def process_custom_amount(message: Message, state: FSMContext):
    bot_settings = await get_bot_settings()
    min_amt = bot_settings.min_wallet_charge

    clean_text = re.sub(r'[,،\s]', '', message.text)
    if not clean_text.isdigit():
        await message.answer(
            f"⚠️ لطفاً مبلغ را فقط با عدد انگلیسی وارد کنید:",
            reply_markup=get_wallet_custom_amount_kb(),
        )
        return

    amount = int(clean_text)
    if amount < min_amt:
        await message.answer(
            f"⚠️ حداقل مبلغ قابل شارژ {min_amt:,} تومان است. لطفاً دوباره وارد کنید:",
            reply_markup=get_wallet_custom_amount_kb(),
        )
        return

    await issue_invoice(message, message.from_user.id, amount, state)


async def issue_invoice(
    msg: Message,
    user_id: int,
    amount: int,
    state: FSMContext,
):
    bot_settings = await get_bot_settings()
    pending_count = await count_user_pending_receipts(user_id)
    max_pending = max(1, bot_settings.max_pending_receipts)
    if pending_count >= max_pending:
        await state.clear()
        await msg.answer(
            f"⏳ شما {pending_count} رسید در انتظار تایید دارید. لطفاً تا بررسی رسیدهای قبلی صبر کنید.",
            parse_mode="HTML",
        )
        return

    tx = await create_wallet_transaction(user_id, amount)
    inv_date = format_jalali(tx.created_at)

    await state.set_state(WalletChargeState.uploading_receipt)
    await state.update_data(
        invoice_number=tx.invoice_number,
        amount=amount,
    )

    invoice_text = (
        f"🧾 <b>فاکتور افزایش موجودی</b>\n\n"
        f"• شماره فاکتور: <code>#{tx.invoice_number}</code>\n"
        f"• تاریخ: <b>{inv_date}</b>\n"
        f"• مبلغ قابل پرداخت: <b>{amount:,} تومان</b>\n\n"
        f"💳 شماره کارت:\n<code>{bot_settings.card_number}</code>\n"
        f"👤 به نام: <b>{bot_settings.card_holder}</b>\n\n"
        f"📌 پس از واریز، تصویر یا متن رسید را همین‌جا ارسال کنید."
    )
    await msg.answer(
        invoice_text,
        reply_markup=get_invoice_cancel_kb(
            tx.invoice_number,
            bot_settings.card_number,
            amount,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cancel_inv:"))
async def cancel_invoice(callback: CallbackQuery, state: FSMContext):
    inv_num = callback.data.split(":")[1]
    await cancel_transaction_by_invoice(inv_num)
    await state.clear()
    await callback.message.edit_text(
        f"❌ فاکتور <code>#{inv_num}</code> لغو شد.",
        parse_mode="HTML",
    )
    await callback.answer("فاکتور لغو شد")


async def save_and_forward_receipt_image(
    message: Message,
    state: FSMContext,
    bot: Bot,
    file_obj,
    ext: str = ".jpg",
    photo_file_id_for_admin: str | None = None,
):
    data = await state.get_data()
    inv_num = data.get("invoice_number")
    amount = data.get("amount")

    j_year, j_month = get_current_jalali_year_month()
    media_rel_dir = os.path.join("receipts", j_year, j_month)
    upload_abs_dir = os.path.join(settings.MEDIA_ROOT, media_rel_dir)
    os.makedirs(upload_abs_dir, exist_ok=True)

    ts = int(timezone.now().timestamp())
    file_name = f"inv_{inv_num}_{ts}{ext}"
    abs_file_path = os.path.join(upload_abs_dir, file_name)

    await bot.download(file_obj, destination=abs_file_path)

    abs_file_path = optimize_receipt_image_file(abs_file_path)
    final_file_name = os.path.basename(abs_file_path)
    rel_db_path = os.path.join(media_rel_dir, final_file_name).replace("\\", "/")

    tx = await update_transaction_receipt(inv_num, relative_image_path=rel_db_path)
    await state.clear()

    profile = await get_user_profile_data(message.from_user.id)
    if tx and tx.target_plan:
        user_wait_msg = (
            f"✅ <b>رسید فاکتور #{inv_num} دریافت شد.</b>\n\n"
            f"• بسته: <b>{tx.target_plan.title}</b>\n"
            f"• نام سرویس: <code>{tx.target_custom_name}</code>\n\n"
            f"⏳ پس از تایید، سرویس شما به صورت خودکار فعال و ارسال می‌شود."
        )
    else:
        user_wait_msg = (
            f"✅ <b>رسید فاکتور #{inv_num} دریافت شد.</b>\n"
            f"⏳ پس از بررسی و تایید، موجودی کیف پول شما شارژ می‌شود."
        )

    await message.answer(
        user_wait_msg,
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
        parse_mode="HTML",
    )

    if tx:
        admin_ids = await get_all_admin_ids()
        tx_date = format_jalali(tx.created_at)
        plan_info = (
            f"\n• بسته: {tx.target_plan.title}\n"
            f"• نام سرویس: <code>{tx.target_custom_name}</code>"
            if tx.target_plan
            else ""
        )
        caption = (
            f"🚨 <b>رسید پرداخت جدید</b>\n\n"
            f"• فاکتور: <code>#{inv_num}</code>\n"
            f"• تاریخ: <b>{tx_date}</b>\n"
            f"• کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
            f"• مبلغ: <b>{amount:,} تومان</b>"
            f"{plan_info}"
        )
        photo_input = (
            photo_file_id_for_admin
            if photo_file_id_for_admin
            else FSInputFile(abs_file_path)
        )
        for aid in admin_ids:
            try:
                await bot.send_photo(
                    chat_id=aid,
                    photo=photo_input,
                    caption=caption,
                    reply_markup=get_admin_receipt_approval_kb(tx.id),
                    parse_mode="HTML",
                )
            except Exception:
                pass


@router.message(WalletChargeState.uploading_receipt, F.photo)
async def process_receipt_photo(message: Message, state: FSMContext, bot: Bot):
    bot_settings = await get_bot_settings()
    cooldown_rem = check_receipt_upload_cooldown(
        message.from_user.id,
        cooldown_seconds=float(bot_settings.receipt_cooldown_seconds),
    )
    if cooldown_rem > 0:
        await message.answer(
            f"⏳ لطفاً {int(cooldown_rem) + 1} ثانیه صبر کنید و دوباره تلاش کنید."
        )
        return

    max_mb = max(1, bot_settings.max_receipt_size_mb)
    max_bytes = max_mb * 1024 * 1024

    photo = message.photo[-1]
    if photo.file_size and photo.file_size > max_bytes:
        await message.answer(
            "❌ حجم تصویر ارسالی زیاد است. لطفاً تصویر کم‌حجم‌تری بفرستید یا اطلاعات رسید را به صورت متن ارسال کنید:",
            parse_mode="HTML",
        )
        return

    await save_and_forward_receipt_image(
        message=message,
        state=state,
        bot=bot,
        file_obj=photo,
        ext=".jpg",
        photo_file_id_for_admin=photo.file_id,
    )


@router.message(WalletChargeState.uploading_receipt, F.document)
async def process_receipt_document(message: Message, state: FSMContext, bot: Bot):
    bot_settings = await get_bot_settings()
    cooldown_rem = check_receipt_upload_cooldown(
        message.from_user.id,
        cooldown_seconds=float(bot_settings.receipt_cooldown_seconds),
    )
    if cooldown_rem > 0:
        await message.answer(
            f"⏳ لطفاً {int(cooldown_rem) + 1} ثانیه صبر کنید و دوباره تلاش کنید."
        )
        return

    max_mb = max(1, bot_settings.max_receipt_size_mb)
    max_bytes = max_mb * 1024 * 1024

    doc = message.document
    if doc.file_size and doc.file_size > max_bytes:
        await message.answer(
            "❌ حجم فایل ارسالی زیاد است. لطفاً عکس رسید را به صورت تصویر معمولی بفرستید یا متن رسید را ارسال کنید:",
            parse_mode="HTML",
        )
        return

    mime = (doc.mime_type or "").lower()
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        await message.answer(
            "⚠️ فرمت فایل مجاز نیست. لطفاً فقط عکس یا متن رسید را ارسال کنید:",
            parse_mode="HTML",
        )
        return

    ext = os.path.splitext(doc.file_name or "")[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"

    await save_and_forward_receipt_image(
        message=message,
        state=state,
        bot=bot,
        file_obj=doc,
        ext=ext,
        photo_file_id_for_admin=None,
    )


@router.message(WalletChargeState.uploading_receipt, F.text)
async def process_receipt_text(message: Message, state: FSMContext, bot: Bot):
    bot_settings = await get_bot_settings()
    cooldown_rem = check_receipt_upload_cooldown(
        message.from_user.id,
        cooldown_seconds=float(bot_settings.receipt_cooldown_seconds),
    )
    if cooldown_rem > 0:
        await message.answer(
            f"⏳ لطفاً {int(cooldown_rem) + 1} ثانیه صبر کنید و دوباره تلاش کنید."
        )
        return

    if len(message.text) > 1500:
        await message.answer(
            "⚠️ متن ارسالی طولانی است. لطفاً متن کوتاه‌تری ارسال کنید:"
        )
        return

    data = await state.get_data()
    inv_num = data.get("invoice_number")
    amount = data.get("amount")

    tx = await update_transaction_receipt(inv_num, receipt_text=message.text)
    await state.clear()

    profile = await get_user_profile_data(message.from_user.id)
    if tx and tx.target_plan:
        user_wait_msg = (
            f"✅ <b>اطلاعات پرداخت فاکتور #{inv_num} دریافت شد.</b>\n\n"
            f"• بسته: <b>{tx.target_plan.title}</b>\n"
            f"• نام سرویس: <code>{tx.target_custom_name}</code>\n\n"
            f"⏳ پس از تایید، سرویس شما به صورت خودکار فعال و ارسال می‌شود."
        )
    else:
        user_wait_msg = (
            f"✅ <b>اطلاعات پرداخت فاکتور #{inv_num} دریافت شد.</b>\n"
            f"⏳ پس از بررسی و تایید، موجودی کیف پول شما شارژ می‌شود."
        )

    await message.answer(
        user_wait_msg,
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
        parse_mode="HTML",
    )

    if tx:
        admin_ids = await get_all_admin_ids()
        tx_date = format_jalali(tx.created_at)
        plan_info = (
            f"\n• بسته: {tx.target_plan.title}\n"
            f"• نام سرویس: <code>{tx.target_custom_name}</code>"
            if tx.target_plan
            else ""
        )
        admin_msg = (
            f"🚨 <b>رسید متنی جدید</b>\n\n"
            f"• فاکتور: <code>#{inv_num}</code>\n"
            f"• تاریخ: <b>{tx_date}</b>\n"
            f"• کاربر: {message.from_user.full_name} (<code>{message.from_user.id}</code>)\n"
            f"• مبلغ: <b>{amount:,} تومان</b>"
            f"{plan_info}\n\n"
            f"📝 متن رسید:\n<code>{message.text}</code>"
        )
        for aid in admin_ids:
            try:
                await bot.send_message(
                    chat_id=aid,
                    text=admin_msg,
                    reply_markup=get_admin_receipt_approval_kb(tx.id),
                    parse_mode="HTML",
                )
            except Exception:
                pass


@router.message(WalletChargeState.uploading_receipt)
async def process_unsupported_receipt_media(message: Message):
    await message.answer(
        "⚠️ لطفاً فقط <b>تصویر</b> یا <b>متن رسید</b> را ارسال کنید:",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adm_appr_tx:"))
async def admin_approve_receipt_callback(callback: CallbackQuery, bot: Bot):
    from bot.handlers.admin_panel import is_admin
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔️ عدم دسترسی", show_alert=True)
        return

    tx_id = int(callback.data.split(":")[1])
    success, msg, tx, auto_order = await approve_transaction_by_id(tx_id)
    if not success:
        await callback.answer(msg, show_alert=True)
        return

    if auto_order:
        if auto_order.status == 'active' and auto_order.config_link:
            admin_status_line = (
                f"✅ <b>تایید شد | سرویس #{auto_order.id} (<code>{auto_order.custom_name}</code>) فعال و ارسال گردید.</b>"
            )
            admin_kb = None
        else:
            admin_status_line = (
                f"✅ <b>رسید تایید شد و سفارش #{auto_order.id} ثبت گردید.</b>\n"
                f"⚠️ <i>لینک کانفیگ را با دکمه زیر ارسال کنید:</i>"
            )
            admin_kb = get_admin_send_config_kb(auto_order.id)
    else:
        admin_status_line = "✅ <b>تایید شد</b>"
        admin_kb = None

    if callback.message.caption:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\n{admin_status_line}",
            reply_markup=admin_kb,
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            text=f"{callback.message.text}\n\n{admin_status_line}",
            reply_markup=admin_kb,
            parse_mode="HTML",
        )

    try:
        if auto_order:
            if auto_order.status == 'active' and auto_order.config_link:
                exp_str = format_jalali(auto_order.expires_at, include_time=False)
                user_msg = (
                    f"🎉 <b>پرداخت شما تایید و سرویس فعال شد!</b>\n\n"
                    f"• نام سرویس: <code>{auto_order.custom_name}</code>\n"
                    f"• بسته: {auto_order.plan.title}\n"
                    f"• تاریخ انقضا: <b>{exp_str}</b>\n"
                    f"• موجودی کیف پول: <b>{tx.user.wallet_balance:,} تومان</b>\n\n"
                    f"🔗 <b>لینک اشتراک:</b>\n"
                    f"<code>{auto_order.config_link}</code>"
                )
                await bot.send_message(
                    tx.user.telegram_id,
                    user_msg,
                    reply_markup=get_service_actions_kb(
                        auto_order.id,
                        auto_order.config_link,
                    ),
                    parse_mode="HTML",
                )
            else:
                user_msg = (
                    f"✅ <b>پرداخت شما تایید و سفارش ثبت شد!</b>\n\n"
                    f"• نام سرویس: <code>{auto_order.custom_name}</code>\n"
                    f"• بسته: {auto_order.plan.title}\n\n"
                    f"⏳ لینک سرویس به زودی برایتان ارسال می‌شود."
                )
                await bot.send_message(
                    tx.user.telegram_id,
                    user_msg,
                    parse_mode="HTML",
                )
        else:
            user_msg = (
                f"✅ <b>رسید شما تایید شد!</b>\n\n"
                f"• شماره فاکتور: <code>#{tx.invoice_number}</code>\n"
                f"• مبلغ شارژ شده: <b>{tx.amount:,} تومان</b>\n"
                f"• موجودی فعلی: <b>{tx.user.wallet_balance:,} تومان</b>"
            )
            await bot.send_message(
                tx.user.telegram_id,
                user_msg,
                parse_mode="HTML",
            )
    except Exception:
        pass

    await callback.answer("✅ تایید انجام شد.")


@router.callback_query(F.data.startswith("adm_rejc_tx:"))
async def admin_reject_receipt_callback(callback: CallbackQuery, bot: Bot):
    from bot.handlers.admin_panel import is_admin
    if not await is_admin(callback.from_user.id):
        await callback.answer("⛔️ عدم دسترسی", show_alert=True)
        return

    tx_id = int(callback.data.split(":")[1])
    success, msg, tx = await reject_transaction_by_id(tx_id)
    if not success:
        await callback.answer(msg, show_alert=True)
        return

    if callback.message.caption:
        await callback.message.edit_caption(
            caption=f"{callback.message.caption}\n\n❌ <b>رد شد</b>",
            reply_markup=None,
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            text=f"{callback.message.text}\n\n❌ <b>رد شد</b>",
            reply_markup=None,
            parse_mode="HTML",
        )

    try:
        user_msg = f"❌ <b>فاکتور #{tx.invoice_number} به مبلغ {tx.amount:,} تومان تایید نشد.</b>"
        await bot.send_message(tx.user.telegram_id, user_msg, parse_mode="HTML")
    except Exception:
        pass

    await callback.answer("❌ رسید رد شد.")


@router.callback_query(F.data == "acc_my_payments")
async def show_my_payments(callback: CallbackQuery):
    transactions = await get_user_transactions(callback.from_user.id)
    if not transactions:
        await callback.message.answer("🧾 هنوز تراکنشی ثبت نکرده‌اید.")
        await callback.answer()
        return

    status_map = {
        'approved': '✅ تایید شده',
        'pending_admin': '⏳ در حال بررسی',
        'rejected': '❌ رد شده',
        'awaiting_receipt': 'منتظر رسید',
        'canceled': 'لغو شده',
    }

    text = "🧾 <b>آخرین تراکنش‌های شما:</b>\n\n"
    for tx in transactions:
        st = status_map.get(tx.status, tx.status)
        tx_date = format_jalali(tx.created_at)
        text += f"• فاکتور <code>#{tx.invoice_number}</code> | <b>{tx.amount:,} تومان</b> | {st}\n📅 <i>{tx_date}</i>\n\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()