import asyncio
from aiogram import (
    Router,
    F,
    Bot,
)
from aiogram.filters import (
    Command,
    StateFilter,
)
from aiogram.types import (
    Message,
    CallbackQuery,
)
from aiogram.fsm.context import FSMContext

from bot.states import AdminState
from bot.keyboards import (
    BTN_CANCEL_ACTION,
    get_admin_panel_kb,
    get_admin_send_config_kb,
    get_service_actions_kb,
    get_cancel_reply_keyboard,
    get_main_menu_keyboard,
)
from core.backup import send_backup_to_admins
from core.jalali import (
    format_jalali,
    now_jalali_str,
)
from core.services import (
    get_admin_dashboard_stats,
    get_pending_orders_list,
    get_order_by_id,
    deliver_order_config_by_id,
    answer_support_ticket_by_id,
    get_all_active_user_ids,
    get_user_profile_data,
    get_all_admin_ids,
)

router = Router()


async def is_admin(
    user_id: int,
) -> bool:
    admin_ids = await get_all_admin_ids()
    return user_id in admin_ids


async def render_admin_dashboard_text() -> str:
    stats = await get_admin_dashboard_stats()
    now_str = now_jalali_str()
    return (
        f"👨‍💻 <b>پنل مدیریت سریع تلگرام</b>\n"
        f"🕒 آخرین بروزرسانی: <b>{now_str}</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"👥 کل کاربران ربات: <b>{stats['total_users']} نفر</b>\n"
        f"⏳ رسیدهای منتظر تایید: <b>{stats['pending_tx']} عدد</b>\n"
        f"📦 سفارش‌های منتظر کانفیگ: <b>{stats['pending_orders']} عدد</b>\n"
        f"✅ سرویس‌های فعال: <b>{stats['active_orders']} عدد</b>\n"
        f"📩 تیکت‌های باز پشتیبانی: <b>{stats['open_tickets']} عدد</b>\n"
        f"💰 مجموع واریزی‌های تایید شده: <b>{stats['total_revenue']:,} تومان</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"از دکمه‌های زیر برای مدیریت سریع استفاده کنید:"
    )


@router.message(
    StateFilter("*"),
    Command("admin"),
)
async def cmd_admin_panel(
    message: Message,
    state: FSMContext,
):
    if not await is_admin(message.from_user.id):
        return
    await state.clear()
    text = await render_admin_dashboard_text()
    await message.answer(
        text,
        reply_markup=get_admin_panel_kb(),
        parse_mode="HTML",
    )


@router.callback_query(
    F.data == "adm_refresh_stats",
)
async def refresh_admin_stats(
    callback: CallbackQuery,
):
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return
    text = await render_admin_dashboard_text()
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_admin_panel_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer("✅ آمار بروزرسانی شد")


@router.callback_query(
    F.data == "adm_manual_backup",
)
async def manual_backup_callback(
    callback: CallbackQuery,
    bot: Bot,
):
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return

    await callback.answer("⏳ در حال تهیه بکاپ کامل و ارسال به ادمین‌ها...")
    ok, result_msg = await send_backup_to_admins(bot)
    if not ok:
        await callback.message.answer(f"❌ {result_msg}")


@router.callback_query(
    F.data == "adm_pending_orders",
)
async def show_pending_orders_for_admin(
    callback: CallbackQuery,
):
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return

    orders = await get_pending_orders_list()
    if not orders:
        await callback.answer(
            "✅ هیچ سفارش منتظر لینکی وجود ندارد!",
            show_alert=True,
        )
        return

    for order in orders:
        plan_title = order.plan.title if order.plan else order.get_order_type_display()
        order_date = format_jalali(order.created_at)
        msg_text = (
            f"⏳ <b>سفارش منتظر کانفیگ (#{order.id})</b>\n"
            f"📅 تاریخ ثبت: <b>{order_date}</b>\n"
            f"👤 کاربر: {order.user.full_name} (<code>{order.user.telegram_id}</code>)\n"
            f"📦 نوع/بسته: {plan_title}\n"
            f"🏷 نام سرویس: <code>{order.custom_name}</code>"
        )
        await callback.message.answer(
            msg_text,
            reply_markup=get_admin_send_config_kb(order.id),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    F.data.startswith("adm_set_cfg:"),
)
async def start_sending_config_link(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return

    order_id = int(callback.data.split(":")[1])
    order = await get_order_by_id(order_id)
    if not order:
        await callback.answer(
            "سفارش یافت نشد!",
            show_alert=True,
        )
        return

    await state.set_state(AdminState.waiting_for_config_link)
    await state.update_data(
        target_order_id=order_id,
    )

    plan_title = order.plan.title if order.plan else order.get_order_type_display()
    await callback.message.answer(
        f"🔗 <b>ارسال لینک کانفیگ برای سفارش #{order.id}</b>\n"
        f"👤 کاربر: <code>{order.user.telegram_id}</code>\n"
        f"🏷 نام سرویس: <code>{order.custom_name}</code> ({plan_title})\n\n"
        f"👇 لطفاً لینک کانفیگ یا اشتراک (Subscription URL) را در پیام بعدی بفرستید:",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("adm_rep_tkt:"),
)
async def start_replying_ticket(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return

    ticket_id = int(callback.data.split(":")[1])
    await state.set_state(AdminState.waiting_for_ticket_reply)
    await state.update_data(
        target_ticket_id=ticket_id,
    )

    await callback.message.answer(
        f"✍️ لطفاً پاسخ خود را برای <b>تیکت #{ticket_id}</b> بنویسید و ارسال کنید:",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(
    AdminState.waiting_for_config_link,
    F.text == BTN_CANCEL_ACTION,
)
@router.message(
    AdminState.waiting_for_broadcast_message,
    F.text == BTN_CANCEL_ACTION,
)
@router.message(
    AdminState.waiting_for_ticket_reply,
    F.text == BTN_CANCEL_ACTION,
)
async def cancel_admin_action(
    message: Message,
    state: FSMContext,
):
    if not await is_admin(message.from_user.id):
        return
    await state.clear()
    profile = await get_user_profile_data(message.from_user.id)
    await message.answer(
        "✅ عملیات ادمین لغو شد.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
    )


@router.message(
    AdminState.waiting_for_ticket_reply,
    F.text,
)
async def save_and_send_ticket_reply(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not await is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("target_ticket_id")
    reply_text = message.text.strip()

    success, ticket = await answer_support_ticket_by_id(
        ticket_id,
        reply_text,
    )
    await state.clear()
    profile = await get_user_profile_data(message.from_user.id)

    if not success or not ticket:
        await message.answer(
            "❌ تیکت مورد نظر یافت نشد!",
            reply_markup=get_main_menu_keyboard(
                show_free_test=not profile['used_free_test'],
                free_test_title=profile['free_test_title'],
            ),
        )
        return

    await message.answer(
        f"✅ پاسخ شما برای <b>تیکت #{ticket.id}</b> ثبت و به کاربر ارسال شد.",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
        parse_mode="HTML",
    )

    try:
        await bot.send_message(
            chat_id=ticket.user.telegram_id,
            text=(
                f"📩 <b>پاسخ پشتیبانی به تیکت #{ticket.id}:</b>\n\n"
                f"🗣 پیام شما: <i>{ticket.user_message}</i>\n\n"
                f"👨‍💻 <b>پاسخ ادمین:</b>\n{reply_text}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(
    AdminState.waiting_for_config_link,
    F.text,
)
async def save_and_deliver_config_link(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not await is_admin(message.from_user.id):
        return

    data = await state.get_data()
    order_id = data.get("target_order_id")
    config_link = message.text.strip()

    success, order = await deliver_order_config_by_id(
        order_id,
        config_link,
    )
    await state.clear()
    profile = await get_user_profile_data(message.from_user.id)

    if not success or not order:
        await message.answer(
            "❌ خطا در یافتن سفارش!",
            reply_markup=get_main_menu_keyboard(
                show_free_test=not profile['used_free_test'],
                free_test_title=profile['free_test_title'],
            ),
        )
        return

    exp_str = format_jalali(
        order.expires_at,
        include_time=False,
    )
    await message.answer(
        f"✅ <b>کانفیگ سفارش #{order.id} (<code>{order.custom_name}</code>) فعال شد و برای کاربر ارسال گردید!</b>",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
        parse_mode="HTML",
    )

    try:
        user_delivery_text = (
            f"🎉 <b>سرویس شما آماده و فعال شد!</b>\n\n"
            f"🏷 نام سرویس: <code>{order.custom_name}</code>\n"
            f"📦 نوع سفارش: {order.get_order_type_display()}\n"
            f"⏳ تاریخ انقضا: <b>{exp_str}</b>\n\n"
            f"🔗 <b>لینک کانفیگ / اشتراک شما:</b>\n"
            f"<code>{order.config_link}</code>\n\n"
        )
        await bot.send_message(
            chat_id=order.user.telegram_id,
            text=user_delivery_text,
            reply_markup=get_service_actions_kb(
                order.id,
                order.config_link,
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(
    F.data == "adm_broadcast",
)
async def start_broadcast_flow(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not await is_admin(callback.from_user.id):
        await callback.answer(
            "⛔️ عدم دسترسی",
            show_alert=True,
        )
        return

    await state.set_state(AdminState.waiting_for_broadcast_message)
    await callback.message.answer(
        "📢 <b>ارسال پیام همگانی به تمام کاربران</b>\n\n"
        "لطفاً متن پیام اطلاع‌رسانی خود را بنویسید و ارسال کنید (برای انصراف دکمه بازگشت پایین را بزنید):",
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(
    AdminState.waiting_for_broadcast_message,
    F.text,
)
async def execute_broadcast(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    if not await is_admin(message.from_user.id):
        return

    broadcast_text = message.text
    await state.clear()
    profile = await get_user_profile_data(message.from_user.id)

    user_ids = await get_all_active_user_ids()
    await message.answer(
        f"⏳ در حال ارسال پیام همگانی به <b>{len(user_ids)} کاربر</b>...",
        reply_markup=get_main_menu_keyboard(
            show_free_test=not profile['used_free_test'],
            free_test_title=profile['free_test_title'],
        ),
        parse_mode="HTML",
    )

    sent_count = 0
    for uid in user_ids:
        try:
            await bot.send_message(
                chat_id=uid,
                text=f"📢 <b>اطلاعیه:</b>\n➖➖➖➖➖➖➖➖➖➖\n{broadcast_text}",
                parse_mode="HTML",
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue

    await message.answer(
        f"✅ <b>پیام همگانی با موفقیت به {sent_count} از {len(user_ids)} کاربر ارسال شد.</b>",
        parse_mode="HTML",
    )