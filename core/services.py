from datetime import timedelta
import re
import requests
from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone
from asgiref.sync import sync_to_async
from core.jalali import format_jalali
from core.models import (
    TelegramUser,
    BotSetting,
    SupportTicket,
    Plan,
    Transaction,
    SubscriptionOrder,
    RequiredChannel,
)
from core.pasarguard import (
    create_user_from_template,
    get_requests_proxies,
)


def get_all_admin_ids_sync() -> list[int]:
    admins = set()
    if getattr(settings, 'ADMIN_TELEGRAM_ID', 0):
        try:
            admins.add(int(settings.ADMIN_TELEGRAM_ID))
        except ValueError:
            pass
    db_admins = TelegramUser.objects.filter(
        is_admin=True,
        is_banned=False,
    ).values_list(
        'telegram_id',
        flat=True,
    )
    admins.update(db_admins)
    return list(admins)


@sync_to_async
def get_all_admin_ids() -> list[int]:
    return get_all_admin_ids_sync()


def send_telegram_message_sync(
    chat_id: int,
    text: str,
):
    if not settings.BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=8,
            proxies=get_requests_proxies(),
        )
        return resp.status_code == 200
    except Exception:
        return False


def fulfill_plan_order_for_user_sync(
    user: TelegramUser,
    plan: Plan,
    custom_name: str,
) -> SubscriptionOrder:
    now = timezone.now()
    order = SubscriptionOrder.objects.create(
        user=user,
        plan=plan,
        order_type='purchase',
        custom_name=custom_name,
        price_paid=plan.price,
        status='pending_config',
    )

    if plan.pasarguard_template_id:
        success, sub_url, panel_username, err = create_user_from_template(
            template_id=plan.pasarguard_template_id,
            base_username=custom_name,
            note=f"Order #{order.id} | Plan: {plan.title} | TG: {user.telegram_id}",
        )
        if success and sub_url:
            order.config_link = sub_url.strip()
            order.panel_username = panel_username
            order.status = 'active'
            order.notified_user = True
            order.expires_at = now + timedelta(days=plan.duration_days)
            order.save(
                update_fields=[
                    'config_link',
                    'panel_username',
                    'status',
                    'notified_user',
                    'expires_at',
                ]
            )
        else:
            for aid in get_all_admin_ids_sync():
                send_telegram_message_sync(
                    aid,
                    f"⚠️ <b>خطا در ساخت خودکار کانفیگ سفارش #{order.id} در پاسارگارد:</b>\n"
                    f"<code>{err}</code>\n\n"
                    f"سفارش در حالت انتظار قرار گرفت.",
                )

    return order


def approve_transaction_sync(
    tx_id: int,
) -> tuple[bool, str, Transaction | None, SubscriptionOrder | None]:
    target_plan = None
    sname = None

    with db_transaction.atomic():
        try:
            tx = (
                Transaction.objects.select_for_update(of=('self',))
                .select_related(
                    'user',
                    'target_plan',
                )
                .get(id=tx_id)
            )
            if tx.is_processed:
                return (
                    False,
                    "این فاکتور قبلاً پردازش شده است.",
                    tx,
                    None,
                )

            user = TelegramUser.objects.select_for_update().get(
                telegram_id=tx.user.telegram_id,
            )
            tx.status = 'approved'
            tx.is_processed = True
            tx.save(
                update_fields=[
                    'status',
                    'is_processed',
                ]
            )

            user.wallet_balance += tx.amount

            if (
                tx.target_plan
                and tx.target_plan.is_active
                and user.wallet_balance >= tx.target_plan.price
            ):
                user.wallet_balance -= tx.target_plan.price
                target_plan = tx.target_plan
                sname = tx.target_custom_name or f"tg{user.telegram_id}"

            user.save(
                update_fields=['wallet_balance'],
            )
            tx.user = user
        except Transaction.DoesNotExist:
            return (
                False,
                "فاکتور یافت نشد.",
                None,
                None,
            )

    auto_order = None
    if target_plan:
        auto_order = fulfill_plan_order_for_user_sync(
            user=tx.user,
            plan=target_plan,
            custom_name=sname,
        )

    return (
        True,
        "فاکتور تایید شد.",
        tx,
        auto_order,
    )


@sync_to_async
def approve_transaction_by_id(
    tx_id: int,
):
    return approve_transaction_sync(tx_id)


@sync_to_async
def upsert_telegram_user(
    telegram_id: int,
    username: str = None,
    full_name: str = None,
    referrer_id: int = None,
):
    pending_gift_info = None
    rem_notification = None
    is_super_admin = bool(
        getattr(settings, 'ADMIN_TELEGRAM_ID', 0)
        and int(telegram_id) == int(settings.ADMIN_TELEGRAM_ID)
    )

    with db_transaction.atomic():
        user, created = TelegramUser.objects.select_for_update().get_or_create(
            telegram_id=telegram_id,
            defaults={
                'username': username,
                'full_name': full_name,
                'is_admin': is_super_admin,
            },
        )
        if not created:
            updated = False
            if user.username != username:
                user.username = username
                updated = True
            if user.full_name != full_name:
                user.full_name = full_name
                updated = True
            if is_super_admin and not user.is_admin:
                user.is_admin = True
                updated = True
            if updated:
                user.save(
                    update_fields=[
                        'username',
                        'full_name',
                        'is_admin',
                        'updated_at',
                    ]
                )

        can_bind_referrer = (
            user.referred_by is None
            and referrer_id is not None
            and int(referrer_id) != int(telegram_id)
            and not user.orders.exists()
        )

        if can_bind_referrer:
            try:
                referrer = TelegramUser.objects.select_for_update().get(
                    telegram_id=referrer_id,
                )
                bot_setting, _ = BotSetting.objects.get_or_create(id=1)
                req_count = max(
                    1,
                    bot_setting.referral_required_count,
                )
                gift_title = bot_setting.referral_gift_title
                gift_days = max(
                    1,
                    bot_setting.referral_gift_days,
                )

                user.referred_by = referrer
                user.save(
                    update_fields=['referred_by'],
                )

                referrer.valid_referrals_count += 1
                earned_gifts_total = referrer.valid_referrals_count // req_count
                new_gifts_count = earned_gifts_total - referrer.referral_gifts_received

                if new_gifts_count > 0:
                    referrer.referral_gifts_received = earned_gifts_total
                    referrer.save(
                        update_fields=[
                            'valid_referrals_count',
                            'referral_gifts_received',
                        ]
                    )
                    gift_name = f"gift_{referrer.telegram_id}_{earned_gifts_total}"
                    gift_order = SubscriptionOrder.objects.create(
                        user=referrer,
                        order_type='referral_gift',
                        custom_name=gift_name,
                        price_paid=0,
                        status='pending_config',
                    )
                    pending_gift_info = (
                        referrer,
                        gift_order,
                        bot_setting.referral_gift_template_id,
                        gift_title,
                        gift_days,
                        req_count,
                    )
                else:
                    referrer.save(
                        update_fields=['valid_referrals_count'],
                    )
                    rem = req_count - (referrer.valid_referrals_count % req_count)
                    rem_notification = (
                        referrer.telegram_id,
                        full_name or 'کاربر تلگرام',
                        rem,
                        gift_title,
                    )
            except TelegramUser.DoesNotExist:
                pass

    if rem_notification:
        ref_tid, fname, rem, g_title = rem_notification
        send_telegram_message_sync(
            ref_tid,
            f"👥 <b>یک کاربر جدید ({fname}) با لینک دعوت شما عضو ربات شد!</b>\n"
            f"⏳ تنها <b>{rem} دعوت دیگر</b> تا دریافت اشتراک هدیه ({g_title}) باقی مانده است.",
        )

    if pending_gift_info:
        referrer, gift_order, tpl_id, gift_title, gift_days, req_count = pending_gift_info
        delivered = False
        if tpl_id:
            success, sub_url, panel_username, _ = create_user_from_template(
                template_id=tpl_id,
                base_username=gift_order.custom_name,
                note=f"Referral Gift #{gift_order.id} | TG: {referrer.telegram_id}",
            )
            if success and sub_url:
                gift_order.config_link = sub_url.strip()
                gift_order.panel_username = panel_username
                gift_order.status = 'active'
                gift_order.notified_user = True
                gift_order.expires_at = timezone.now() + timedelta(days=gift_days)
                gift_order.save(
                    update_fields=[
                        'config_link',
                        'panel_username',
                        'status',
                        'notified_user',
                        'expires_at',
                    ]
                )
                delivered = True

        admin_ids = get_all_admin_ids_sync()
        if delivered:
            exp_str = format_jalali(
                gift_order.expires_at,
                include_time=False,
            )
            send_telegram_message_sync(
                referrer.telegram_id,
                f"🎉 <b>تبریک! شما به {referrer.valid_referrals_count} دعوت موفق رسیدید!</b>\n\n"
                f"🎁 یک <b>اشتراک هدیه ({gift_title})</b> با نام <code>{gift_order.custom_name}</code> به صورت آنی برای شما فعال شد!\n"
                f"⏳ تاریخ انقضا: <b>{exp_str}</b>\n\n"
                f"🔗 <b>لینک کانفیگ / اشتراک شما:</b>\n"
                f"<code>{gift_order.config_link}</code>\n\n"
                f"💡 از بخش «🔍 سرویس (های) من» می‌توانید همیشه به این لینک و بارکد آن دسترسی داشته باشید.",
            )
            for aid in admin_ids:
                send_telegram_message_sync(
                    aid,
                    f"✅ <b>تحویل خودکار هدیه دعوت دوستان در پاسارگارد! (سفارش #{gift_order.id})</b>\n"
                    f"کاربر <code>{referrer.telegram_id}</code> به {req_count} دعوت جدید رسید و هدیه <code>{gift_order.custom_name}</code> را دریافت کرد.",
                )
        else:
            send_telegram_message_sync(
                referrer.telegram_id,
                f"🎉 <b>تبریک! شما به {referrer.valid_referrals_count} دعوت موفق رسیدید!</b>\n\n"
                f"🎁 یک <b>اشتراک هدیه ({gift_title})</b> با نام <code>{gift_order.custom_name}</code> برای شما ثبت شد و به زودی لینک آن برایتان ارسال می‌گردد.",
            )
            for aid in admin_ids:
                send_telegram_message_sync(
                    aid,
                    f"🎁 <b>هدیه دعوت دوستان ثبت شد! (سفارش #{gift_order.id})</b>\n"
                    f"⚠️ <i>ساخت خودکار در پاسارگارد انجام نشد.</i>\n"
                    f"کاربر: <code>{referrer.telegram_id}</code>",
                )

    return user, created


@sync_to_async
def get_user_profile_data(
    telegram_id: int,
):
    user = TelegramUser.objects.get(
        telegram_id=telegram_id,
    )
    bot_setting, _ = BotSetting.objects.get_or_create(id=1)
    active_orders_count = user.orders.filter(
        status='active',
    ).count()
    hide_free_test = user.used_free_test or (not bot_setting.free_test_enabled)
    return {
        'telegram_id': user.telegram_id,
        'username': f"@{user.username}" if user.username else "ندارد",
        'full_name': user.full_name or "کاربر گرامی",
        'wallet_balance': user.wallet_balance,
        'used_free_test': hide_free_test,
        'free_test_title': bot_setting.free_test_title,
        'valid_referrals_count': user.valid_referrals_count,
        'referral_gifts_received': user.referral_gifts_received,
        'active_orders_count': active_orders_count,
        'created_at_jalali': format_jalali(
            user.created_at,
            include_time=False,
        ),
    }


@sync_to_async
def get_bot_settings() -> BotSetting:
    setting, _ = BotSetting.objects.get_or_create(
        id=1,
    )
    return setting


@sync_to_async
def get_rate_limit_runtime_config() -> tuple[int, set[int]]:
    setting, _ = BotSetting.objects.get_or_create(
        id=1,
    )
    limit = max(
        5,
        setting.rate_limit_per_minute,
    )
    admin_ids = set(get_all_admin_ids_sync())
    return limit, admin_ids


@sync_to_async
def count_user_pending_receipts(
    telegram_id: int,
) -> int:
    return Transaction.objects.filter(
        user__telegram_id=telegram_id,
        status='pending_admin',
    ).count()


@sync_to_async
def count_user_open_tickets(
    telegram_id: int,
) -> int:
    return SupportTicket.objects.filter(
        user__telegram_id=telegram_id,
        status='open',
    ).count()


@sync_to_async
def set_bot_sticker(
    field_name: str,
    file_id: str,
) -> bool:
    allowed_fields = {
        'sticker_welcome',
        'sticker_account',
        'sticker_buy',
        'sticker_empty',
        'sticker_wallet',
    }
    if field_name not in allowed_fields:
        return False
    setting, _ = BotSetting.objects.get_or_create(
        id=1,
    )
    setattr(
        setting,
        field_name,
        file_id,
    )
    setting.save(
        update_fields=[field_name],
    )
    return True


@sync_to_async
def create_support_ticket(
    telegram_id: int,
    message_text: str,
) -> SupportTicket:
    user = TelegramUser.objects.get(
        telegram_id=telegram_id,
    )
    return SupportTicket.objects.create(
        user=user,
        user_message=message_text,
    )


@sync_to_async
def answer_support_ticket_by_id(
    ticket_id: int,
    reply_text: str,
):
    try:
        ticket = SupportTicket.objects.select_related('user').get(
            id=ticket_id,
        )
        ticket.admin_reply = reply_text
        ticket.status = 'answered'
        ticket.reply_sent = True
        ticket.save(
            update_fields=[
                'admin_reply',
                'status',
                'reply_sent',
            ]
        )
        return True, ticket
    except SupportTicket.DoesNotExist:
        return False, None


@sync_to_async
def get_active_plans(
    plan_type: str = None,
):
    qs = Plan.objects.filter(
        is_active=True,
    )
    if plan_type:
        qs = qs.filter(
            plan_type=plan_type,
        )
    return list(
        qs.order_by(
            'sort_order',
            'price',
        )
    )


@sync_to_async
def get_distinct_active_plan_prices() -> list[int]:
    setting, _ = BotSetting.objects.get_or_create(id=1)
    if setting.wallet_preset_amounts:
        raw_parts = re.split(
            r'[,،\s]+',
            setting.wallet_preset_amounts.strip(),
        )
        custom_prices = sorted(
            {
                int(p)
                for p in raw_parts
                if p.isdigit() and int(p) > 0
            }
        )
        if custom_prices:
            return custom_prices

    prices = list(
        Plan.objects.filter(
            is_active=True,
        )
        .values_list(
            'price',
            flat=True,
        )
        .distinct()
    )
    prices.sort()
    if prices:
        return prices

    base = max(
        10000,
        setting.min_wallet_charge,
    )
    return [
        base,
        base * 2,
        base * 5,
        base * 10,
    ]


@sync_to_async
def get_plan_by_id(
    plan_id: int,
):
    try:
        return Plan.objects.get(
            id=plan_id,
            is_active=True,
        )
    except Plan.DoesNotExist:
        return None


@sync_to_async
def create_wallet_transaction(
    telegram_id: int,
    amount: int,
    target_plan_id: int = None,
    target_custom_name: str = None,
) -> Transaction:
    user = TelegramUser.objects.get(
        telegram_id=telegram_id,
    )
    target_plan = None
    if target_plan_id:
        target_plan = Plan.objects.filter(
            id=target_plan_id,
            is_active=True,
        ).first()
    return Transaction.objects.create(
        user=user,
        amount=amount,
        target_plan=target_plan,
        target_custom_name=target_custom_name,
        status='awaiting_receipt',
    )


@sync_to_async
def get_transaction_by_invoice(
    invoice_number: str,
):
    try:
        return Transaction.objects.select_related(
            'user',
            'target_plan',
        ).get(
            invoice_number=invoice_number,
        )
    except Transaction.DoesNotExist:
        return None


@sync_to_async
def update_transaction_receipt(
    invoice_number: str,
    relative_image_path: str = None,
    receipt_text: str = None,
):
    try:
        tx = Transaction.objects.select_related(
            'user',
            'target_plan',
        ).get(
            invoice_number=invoice_number,
        )
        tx.status = 'pending_admin'
        if relative_image_path:
            tx.receipt_image = relative_image_path
        if receipt_text:
            tx.receipt_text = receipt_text
        tx.save()
        return tx
    except Transaction.DoesNotExist:
        return None


@sync_to_async
def cancel_transaction_by_invoice(
    invoice_number: str,
):
    try:
        tx = Transaction.objects.get(
            invoice_number=invoice_number,
            status='awaiting_receipt',
        )
        tx.status = 'canceled'
        tx.save(
            update_fields=['status'],
        )
        return True
    except Transaction.DoesNotExist:
        return False


@sync_to_async
def reject_transaction_by_id(
    tx_id: int,
    note: str = "رسید ارسالی معتبر نمی‌باشد.",
):
    try:
        tx = Transaction.objects.select_related(
            'user',
            'target_plan',
        ).get(
            id=tx_id,
        )
        if tx.is_processed:
            return (
                False,
                "این فاکتور قبلاً پردازش شده است.",
                tx,
            )
        tx.status = 'rejected'
        tx.admin_note = note
        tx.is_processed = True
        tx.save(
            update_fields=[
                'status',
                'admin_note',
                'is_processed',
            ]
        )
        return (
            True,
            "فاکتور رد شد.",
            tx,
        )
    except Transaction.DoesNotExist:
        return (
            False,
            "فاکتور یافت نشد.",
            None,
        )


@sync_to_async
def process_plan_purchase(
    telegram_id: int,
    plan_id: int,
    custom_name: str,
):
    with db_transaction.atomic():
        user = TelegramUser.objects.select_for_update().get(
            telegram_id=telegram_id,
        )
        plan = Plan.objects.get(
            id=plan_id,
            is_active=True,
        )

        if user.wallet_balance < plan.price:
            deficit = plan.price - user.wallet_balance
            return (
                False,
                "موجودی کافی نیست",
                deficit,
                None,
            )

        user.wallet_balance -= plan.price
        user.save(
            update_fields=['wallet_balance'],
        )

    order = fulfill_plan_order_for_user_sync(
        user=user,
        plan=plan,
        custom_name=custom_name,
    )
    return (
        True,
        "خرید با موفقیت انجام شد",
        0,
        order,
    )


@sync_to_async
def get_user_orders(
    telegram_id: int,
):
    return list(
        SubscriptionOrder.objects.filter(
            user__telegram_id=telegram_id,
        )
        .select_related('plan')
        .order_by('-created_at')
    )


@sync_to_async
def get_user_transactions(
    telegram_id: int,
):
    return list(
        Transaction.objects.filter(
            user__telegram_id=telegram_id,
        )
        .order_by('-created_at')[:10]
    )


@sync_to_async
def claim_free_test_order(
    telegram_id: int,
):
    bot_setting, _ = BotSetting.objects.get_or_create(id=1)
    if not bot_setting.free_test_enabled:
        return (
            False,
            "disabled",
            None,
        )

    with db_transaction.atomic():
        user = TelegramUser.objects.select_for_update().get(
            telegram_id=telegram_id,
        )
        if user.used_free_test:
            return (
                False,
                "already_used",
                None,
            )

        user.used_free_test = True
        user.save(
            update_fields=['used_free_test'],
        )

        test_name = f"test_{telegram_id}"
        order = SubscriptionOrder.objects.create(
            user=user,
            order_type='free_test',
            custom_name=test_name,
            price_paid=0,
            status='pending_config',
        )

    if bot_setting.free_test_template_id:
        success, sub_url, panel_username, _ = create_user_from_template(
            template_id=bot_setting.free_test_template_id,
            base_username=test_name,
            note=f"Free Test #{order.id} | TG: {telegram_id}",
        )
        if success and sub_url:
            days = max(
                1,
                bot_setting.free_test_days,
            )
            order.config_link = sub_url.strip()
            order.panel_username = panel_username
            order.status = 'active'
            order.notified_user = True
            order.expires_at = timezone.now() + timedelta(days=days)
            order.save(
                update_fields=[
                    'config_link',
                    'panel_username',
                    'status',
                    'notified_user',
                    'expires_at',
                ]
            )
            return (
                True,
                "instant",
                order,
            )

    return (
        True,
        "manual",
        order,
    )


@sync_to_async
def get_user_referrals_list(
    telegram_id: int,
):
    return list(
        TelegramUser.objects.filter(
            referred_by__telegram_id=telegram_id,
        )
        .order_by('-created_at')[:15]
    )


@sync_to_async
def get_order_by_id(
    order_id: int,
):
    try:
        return SubscriptionOrder.objects.select_related(
            'user',
            'plan',
        ).get(
            id=order_id,
        )
    except SubscriptionOrder.DoesNotExist:
        return None


@sync_to_async
def deliver_order_config_by_id(
    order_id: int,
    config_link: str,
):
    with db_transaction.atomic():
        try:
            order = SubscriptionOrder.objects.select_related(
                'user',
                'plan',
            ).get(
                id=order_id,
            )
            order.config_link = config_link.strip()
            order.status = 'active'
            order.notified_user = True
            bot_setting, _ = BotSetting.objects.get_or_create(id=1)
            if order.plan:
                days = order.plan.duration_days
            elif order.order_type == 'referral_gift':
                days = max(
                    1,
                    bot_setting.referral_gift_days,
                )
            else:
                days = max(
                    1,
                    bot_setting.free_test_days,
                )
            order.expires_at = timezone.now() + timedelta(days=days)
            order.save(
                update_fields=[
                    'config_link',
                    'status',
                    'notified_user',
                    'expires_at',
                ]
            )
            return True, order
        except SubscriptionOrder.DoesNotExist:
            return False, None


@sync_to_async
def get_pending_orders_list():
    return list(
        SubscriptionOrder.objects.filter(
            status='pending_config',
        )
        .select_related(
            'user',
            'plan',
        )
        .order_by('created_at')[:15]
    )


@sync_to_async
def get_admin_dashboard_stats():
    total_users = TelegramUser.objects.count()
    pending_tx = Transaction.objects.filter(
        status='pending_admin',
    ).count()
    pending_orders = SubscriptionOrder.objects.filter(
        status='pending_config',
    ).count()
    active_orders = SubscriptionOrder.objects.filter(
        status='active',
    ).count()
    open_tickets = SupportTicket.objects.filter(
        status='open',
    ).count()
    total_revenue = Transaction.objects.filter(
        status='approved',
    ).aggregate(
        total=Sum('amount'),
    )['total'] or 0

    return {
        'total_users': total_users,
        'pending_tx': pending_tx,
        'pending_orders': pending_orders,
        'active_orders': active_orders,
        'open_tickets': open_tickets,
        'total_revenue': total_revenue,
    }


def get_all_active_user_ids_sync() -> list[int]:
    return list(
        TelegramUser.objects.filter(
            is_banned=False,
        ).values_list(
            'telegram_id',
            flat=True,
        )
    )


@sync_to_async
def get_all_active_user_ids():
    return get_all_active_user_ids_sync()


@sync_to_async
def get_active_required_channels():
    return list(
        RequiredChannel.objects.filter(
            is_active=True,
        ).order_by(
            'sort_order',
            'id',
        )
    )