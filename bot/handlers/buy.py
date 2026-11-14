import re
from aiogram import Router, F, Bot
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states import BuyServiceState, WalletChargeState
from bot.keyboards import (
    BTN_BUY_SERVICE,
    get_buy_category_kb,
    get_plans_list_kb,
    get_service_naming_kb,
    get_confirm_purchase_kb,
    get_invoice_cancel_kb,
    get_main_menu_keyboard,
    get_admin_send_config_kb,
    get_service_actions_kb,
)
from core.jalali import format_jalali
from core.services import (
    get_bot_settings,
    get_active_plans,
    get_plan_by_id,
    get_user_profile_data,
    process_plan_purchase,
    create_wallet_transaction,
    get_all_admin_ids,
    count_user_pending_receipts,
)

router = Router()


@router.message(F.text == BTN_BUY_SERVICE)
async def start_buy_service(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BuyServiceState.selecting_category)

    bot_settings = await get_bot_settings()
    if bot_settings.sticker_buy:
        try:
            await message.answer_sticker(bot_settings.sticker_buy)
        except Exception:
            pass

    await message.answer(
        bot_settings.buy_menu_text,
        reply_markup=get_buy_category_kb(
            direct_title=bot_settings.direct_btn_title,
            tunnel_title=bot_settings.tunnel_btn_title,
        ),
        parse_mode="HTML",
    )


@router.callback_query(BuyServiceState.selecting_category, F.data.startswith("buy_cat:"))
async def select_category(callback: CallbackQuery, state: FSMContext):
    cat = callback.data.split(":")[1]
    plans = await get_active_plans(plan_type=cat)

    if not plans:
        await callback.answer(
            "در حال حاضر بسته فعالی در این بخش وجود ندارد.",
            show_alert=True,
        )
        return

    await state.set_state(BuyServiceState.selecting_plan)
    await state.update_data(selected_category=cat)

    bot_settings = await get_bot_settings()
    header_text = bot_settings.volume_plan_header if cat == 'direct' else bot_settings.unlimited_plan_header

    await callback.message.edit_text(
        f"{header_text}\n\n👇 بسته مورد نظر خود را انتخاب کنید:",
        reply_markup=get_plans_list_kb(plans, cat),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(StateFilter("*"), F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    bot_settings = await get_bot_settings()
    await state.set_state(BuyServiceState.selecting_category)
    await callback.message.edit_text(
        bot_settings.buy_menu_text,
        reply_markup=get_buy_category_kb(
            direct_title=bot_settings.direct_btn_title,
            tunnel_title=bot_settings.tunnel_btn_title,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BuyServiceState.selecting_plan, F.data.startswith("select_plan:"))
async def select_plan(callback: CallbackQuery, state: FSMContext):
    plan_id = int(callback.data.split(":")[1])
    plan = await get_plan_by_id(plan_id)
    if not plan:
        await callback.answer("بسته مورد نظر یافت نشد.", show_alert=True)
        return

    await state.set_state(BuyServiceState.entering_custom_name)
    await state.update_data(plan_id=plan_id)

    default_name = f"tg{callback.from_user.id}"
    await callback.message.edit_text(
        f"🏷 بسته انتخابی: <b>{plan.title}</b>\n\n"
        f"یک نام دلخواه به انگلیسی (۳ تا ۱۶ حرف یا عدد) برای سرویس خود بفرستید یا گزینه نام پیش‌فرض را بزنید:",
        reply_markup=get_service_naming_kb(default_name),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BuyServiceState.entering_custom_name, F.data.startswith("set_sname:"))
async def set_default_name(callback: CallbackQuery, state: FSMContext):
    sname = callback.data.split(":")[1]
    await show_purchase_summary(
        callback.message,
        callback.from_user.id,
        sname,
        state,
    )
    await callback.answer()


@router.message(BuyServiceState.entering_custom_name, F.text)
async def set_custom_name_text(message: Message, state: FSMContext):
    name = message.text.strip()
    if not re.match(r'^[a-zA-Z0-9_]{3,16}$', name):
        await message.answer(
            "⚠️ نام سرویس باید بین ۳ تا ۱۶ کاراکتر و فقط شامل حروف انگلیسی و عدد باشد. لطفاً دوباره ارسال کنید:"
        )
        return

    await show_purchase_summary(
        message,
        message.from_user.id,
        name,
        state,
    )


async def show_purchase_summary(
    msg: Message,
    user_id: int,
    sname: str,
    state: FSMContext,
):
    data = await state.get_data()
    plan_id = data.get("plan_id")
    plan = await get_plan_by_id(plan_id)
    profile = await get_user_profile_data(user_id)
    bot_settings = await get_bot_settings()

    server_type_title = (
        bot_settings.direct_btn_title
        if plan.plan_type == 'direct'
        else bot_settings.tunnel_btn_title
    )
    volume_info = f"{plan.volume_gb} گیگابایت" if plan.volume_gb > 0 else f"♾ نامحدود ({plan.max_users} کاربره)"

    if profile['wallet_balance'] < plan.price:
        pending_count = await count_user_pending_receipts(user_id)
        max_pending = max(1, bot_settings.max_pending_receipts)
        if pending_count >= max_pending:
            await state.clear()
            await msg.answer(
                f"⏳ شما {pending_count} رسید در انتظار تایید دارید. لطفاً تا بررسی رسیدهای قبلی صبر کنید.",
                parse_mode="HTML",
            )
            return

        deficit = plan.price - profile['wallet_balance']
        tx = await create_wallet_transaction(
            telegram_id=user_id,
            amount=deficit,
            target_plan_id=plan.id,
            target_custom_name=sname,
        )
        inv_date = format_jalali(tx.created_at)

        await state.set_state(WalletChargeState.uploading_receipt)
        await state.update_data(
            invoice_number=tx.invoice_number,
            amount=deficit,
        )

        wallet_deduction_line = (
            f"• کسر از کیف پول: {profile['wallet_balance']:,} تومان\n"
            if profile['wallet_balance'] > 0
            else ""
        )
        direct_invoice_text = (
            f"🧾 <b>فاکتور خرید سرویس</b>\n\n"
            f"• نام سرویس: <code>{sname}</code>\n"
            f"• بسته: {plan.title}\n"
            f"• نوع سرور: {server_type_title}\n"
            f"• حجم: {volume_info}\n"
            f"• مدت اعتبار: {plan.duration_days} روز\n"
            f"• قیمت بسته: {plan.price:,} تومان\n"
            f"{wallet_deduction_line}"
            f"• <b>مبلغ قابل پرداخت: {deficit:,} تومان</b>\n\n"
            f"🔢 شماره فاکتور: <code>#{tx.invoice_number}</code>\n"
            f"📅 تاریخ: {inv_date}\n"
            f"💳 شماره کارت:\n<code>{bot_settings.card_number}</code>\n"
            f"👤 به نام: <b>{bot_settings.card_holder}</b>\n\n"
            f"📌 پس از واریز، تصویر یا متن رسید را همین‌جا ارسال کنید تا سرویس شما به صورت خودکار فعال شود."
        )
        await msg.answer(
            direct_invoice_text,
            reply_markup=get_invoice_cancel_kb(
                tx.invoice_number,
                bot_settings.card_number,
                deficit,
            ),
            parse_mode="HTML",
        )
        return

    await state.set_state(BuyServiceState.confirming_purchase)
    await state.update_data(custom_name=sname)

    summary = (
        f"📋 <b>تایید نهایی خرید</b>\n\n"
        f"• نام سرویس: <code>{sname}</code>\n"
        f"• بسته: {plan.title}\n"
        f"• نوع سرور: {server_type_title}\n"
        f"• حجم: {volume_info}\n"
        f"• مدت اعتبار: {plan.duration_days} روز\n"
        f"• مبلغ قابل کسر: <b>{plan.price:,} تومان</b>\n"
        f"• موجودی کیف پول: {profile['wallet_balance']:,} تومان\n\n"
        f"آیا خرید و فعال‌سازی سرویس را تایید می‌کنید؟"
    )
    await msg.answer(
        summary,
        reply_markup=get_confirm_purchase_kb(plan.id),
        parse_mode="HTML",
    )


@router.callback_query(BuyServiceState.confirming_purchase, F.data.startswith("do_purchase:"))
async def execute_purchase(callback: CallbackQuery, state: FSMContext, bot: Bot):
    plan_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    sname = data.get("custom_name")

    success, msg, deficit, order = await process_plan_purchase(
        telegram_id=callback.from_user.id,
        plan_id=plan_id,
        custom_name=sname,
    )
    bot_settings = await get_bot_settings()

    if not success:
        pending_count = await count_user_pending_receipts(callback.from_user.id)
        max_pending = max(1, bot_settings.max_pending_receipts)
        if pending_count >= max_pending:
            await state.clear()
            await callback.answer(
                f"⏳ شما {pending_count} رسید در انتظار تایید دارید. لطفاً تا بررسی آن‌ها صبر کنید.",
                show_alert=True,
            )
            return

        tx = await create_wallet_transaction(
            telegram_id=callback.from_user.id,
            amount=deficit,
            target_plan_id=plan_id,
            target_custom_name=sname,
        )
        inv_date = format_jalali(tx.created_at)
        await state.set_state(WalletChargeState.uploading_receipt)
        await state.update_data(
            invoice_number=tx.invoice_number,
            amount=deficit,
        )
        await callback.message.edit_text(
            f"🧾 <b>فاکتور پرداخت سرویس <code>{sname}</code></b>\n\n"
            f"• شماره فاکتور: <code>#{tx.invoice_number}</code>\n"
            f"• تاریخ: <b>{inv_date}</b>\n"
            f"• مبلغ قابل پرداخت: <b>{deficit:,} تومان</b>\n\n"
            f"💳 شماره کارت:\n<code>{bot_settings.card_number}</code>\n"
            f"👤 به نام: <b>{bot_settings.card_holder}</b>\n\n"
            f"📌 پس از واریز، تصویر یا متن رسید را همین‌جا بفرستید تا سرویس شما خودکار فعال شود.",
            reply_markup=get_invoice_cancel_kb(
                tx.invoice_number,
                bot_settings.card_number,
                deficit,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.clear()
    profile = await get_user_profile_data(callback.from_user.id)
    server_badge = (
        bot_settings.direct_btn_title
        if order.plan.plan_type == 'direct'
        else bot_settings.tunnel_btn_title
    )

    admin_ids = await get_all_admin_ids()
    order_date = format_jalali(order.created_at)

    if order.status == 'active' and order.config_link:
        exp_str = format_jalali(order.expires_at, include_time=False)
        instant_text = (
            f"🎉 <b>سرویس شما با موفقیت فعال شد!</b>\n\n"
            f"• نام سرویس: <code>{sname}</code>\n"
            f"• بسته: {order.plan.title}\n"
            f"• تاریخ خرید: <b>{order_date}</b>\n"
            f"• تاریخ انقضا: <b>{exp_str}</b>\n"
            f"• مبلغ پرداختی: <b>{order.price_paid:,} تومان</b>\n"
            f"• موجودی باقیمانده: <b>{profile['wallet_balance']:,} تومان</b>\n\n"
            f"🔗 <b>لینک اشتراک:</b>\n"
            f"<code>{order.config_link}</code>"
        )
        await callback.message.edit_text(
            instant_text,
            reply_markup=get_service_actions_kb(order.id, order.config_link),
            parse_mode="HTML",
        )
        await callback.answer()

        admin_instant_alert = (
            f"✅ <b>فروش و تحویل خودکار (#{order.id})</b>\n\n"
            f"• تاریخ: <b>{order_date}</b>\n"
            f"• کاربر: {callback.from_user.full_name} (<code>{callback.from_user.id}</code>)\n"
            f"• دسته: <b>{server_badge}</b>\n"
            f"• بسته: {order.plan.title}\n"
            f"• نام سرویس: <code>{sname}</code>\n"
            f"• مبلغ: <b>{order.price_paid:,} تومان</b>"
        )
        for aid in admin_ids:
            try:
                await bot.send_message(aid, admin_instant_alert, parse_mode="HTML")
            except Exception:
                pass
        return

    success_text = (
        f"🎉 <b>خرید شما با موفقیت ثبت شد!</b>\n\n"
        f"• نام سرویس: <code>{sname}</code>\n"
        f"• تاریخ ثبت: <b>{order_date}</b>\n"
        f"• مبلغ پرداختی: <b>{order.price_paid:,} تومان</b>\n"
        f"• موجودی باقیمانده: <b>{profile['wallet_balance']:,} تومان</b>\n\n"
        f"⏳ لینک سرویس شما به زودی ارسال می‌شود."
    )
    await callback.message.edit_text(success_text, parse_mode="HTML")
    await callback.answer("خرید با موفقیت ثبت شد.")

    admin_alert = (
        f"🛒 <b>سفارش جدید (#{order.id})</b>\n\n"
        f"• تاریخ: <b>{order_date}</b>\n"
        f"• کاربر: {callback.from_user.full_name} (<code>{callback.from_user.id}</code>)\n"
        f"• دسته: <b>{server_badge}</b>\n"
        f"• بسته: {order.plan.title}\n"
        f"• نام سرویس: <code>{sname}</code>"
    )
    for aid in admin_ids:
        try:
            await bot.send_message(
                aid,
                admin_alert,
                reply_markup=get_admin_send_config_kb(order.id),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.callback_query(StateFilter("*"), F.data == "cancel_buy_flow")
async def cancel_buy_flow(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    profile = await get_user_profile_data(callback.from_user.id)
    await callback.message.answer(
        "✅ خرید لغو شد.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
    )
    await callback.answer()