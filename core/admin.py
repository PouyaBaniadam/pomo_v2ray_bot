import threading
import time
from datetime import timedelta

from django.contrib import (
    admin,
    messages,
)
from django.db.models import Max
from django.shortcuts import (
    redirect,
    render,
)
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action
from core.jalali import format_jalali
from core.models import (
    TelegramUser,
    Plan,
    Transaction,
    SubscriptionOrder,
    SupportTicket,
    RequiredChannel,
    BotSetting,
    BroadcastMessage,
)
from core.services import (
    send_telegram_message_sync,
    build_service_actions_reply_markup_sync,
    approve_transaction_sync,
    get_all_active_user_ids_sync,
)
from core.pasarguard import (
    create_user_from_template,
    fetch_pasarguard_templates_list,
    fetch_pasarguard_groups,
    resolve_default_group_ids_for_plan_type,
    create_or_update_user_template,
)


def render_free_test_reset_confirmation(
    model_admin,
    request,
    cancel_url: str,
):
    affected_count = TelegramUser.objects.filter(
        used_free_test=True,
    ).count()
    total_count = TelegramUser.objects.count()
    context = {
        **model_admin.admin_site.each_context(request),
        "title": "تاییدیه ریست تست رایگان",
        "affected_count": affected_count,
        "total_count": total_count,
        "cancel_url": cancel_url,
    }
    return render(
        request,
        "admin/core/confirm_reset_free_test.html",
        context,
    )


def execute_global_free_test_reset(
    model_admin,
    request,
):
    updated_count = TelegramUser.objects.filter(
        used_free_test=True,
    ).update(
        used_free_test=False,
    )
    BotSetting.objects.filter(id=1).update(
        free_test_enabled=True,
    )
    model_admin.message_user(
        request,
        f"تست رایگان برای همه کاربران فعال شد ({updated_count} کاربر ریست شدند).",
        level=messages.SUCCESS,
    )


@admin.register(TelegramUser)
class TelegramUserAdmin(ModelAdmin):
    list_display = (
        'telegram_id',
        'full_name',
        'username',
        'formatted_balance',
        'is_admin',
        'used_free_test',
        'free_test_count',
        'valid_referrals_count',
        'referral_gifts_received',
        'is_banned',
        'jalali_created_at',
    )
    search_fields = (
        'telegram_id',
        'username',
        'full_name',
    )
    list_filter = (
        'is_admin',
        'used_free_test',
        'is_banned',
        'created_at',
    )
    list_editable = (
        'is_admin',
        'used_free_test',
        'is_banned',
    )
    readonly_fields = (
        'telegram_id',
        'free_test_count',
        'jalali_created_at',
        'jalali_updated_at',
    )
    exclude = (
        'created_at',
        'updated_at',
    )
    actions = [
        'reset_selected_users_free_test',
    ]
    actions_list = [
        'reset_all_users_free_test_action',
    ]

    @action(
        description="ریست و فعال‌سازی تست برای همه کاربران",
        url_path="reset-all-free-tests",
    )
    def reset_all_users_free_test_action(
            self,
            request,
    ):
        cancel_url = str(reverse_lazy("admin:core_telegramuser_changelist"))
        if request.method == "POST" and request.POST.get("confirm") == "yes":
            execute_global_free_test_reset(
                self,
                request,
            )
            return redirect(cancel_url)
        return render_free_test_reset_confirmation(
            self,
            request,
            cancel_url,
        )

    @admin.action(description="فعال‌سازی مجدد تست رایگان برای کاربران انتخاب شده")
    def reset_selected_users_free_test(
            self,
            request,
            queryset,
    ):
        updated_count = queryset.update(
            used_free_test=False,
        )
        self.message_user(
            request,
            f"تست رایگان برای {updated_count} کاربر انتخاب شده مجدداً فعال شد.",
            level=messages.SUCCESS,
        )

    @admin.display(description="موجودی کیف پول")
    def formatted_balance(
            self,
            obj,
    ):
        return f"{obj.wallet_balance:,} تومان"

    @admin.display(
        description="تاریخ عضویت (شمسی)",
        ordering="created_at",
    )
    def jalali_created_at(
            self,
            obj,
    ):
        return format_jalali(obj.created_at)

    @admin.display(
        description="آخرین فعالیت (شمسی)",
        ordering="updated_at",
    )
    def jalali_updated_at(
            self,
            obj,
    ):
        return format_jalali(obj.updated_at)


@admin.register(Plan)
class PlanAdmin(ModelAdmin):
    list_display = (
        'title',
        'plan_type',
        'pasarguard_template_id',
        'volume_gb',
        'duration_days',
        'max_users',
        'formatted_price',
        'is_active',
        'sort_order',
    )
    list_filter = (
        'plan_type',
        'is_active',
        'duration_days',
        'max_users',
    )
    list_editable = (
        'pasarguard_template_id',
        'is_active',
        'sort_order',
    )
    search_fields = ('title',)
    actions_list = [
        'sync_all_plans_to_pasarguard',
    ]

    @admin.display(description="قیمت")
    def formatted_price(
            self,
            obj,
    ):
        return f"{obj.price:,} تومان"

    def add_view(
            self,
            request,
            form_url="",
            extra_context=None,
    ):
        changelist_url = str(reverse_lazy("admin:core_plan_changelist"))

        if request.method == "POST":
            plan_type = request.POST.get("plan_type", "direct")
            title = (request.POST.get("title") or "").strip()
            volume_gb = max(0, int(request.POST.get("volume_gb") or 0))
            max_users = max(1, int(request.POST.get("max_users") or 1))
            price = max(0, int(request.POST.get("price") or 0))
            sort_order = max(1, int(request.POST.get("sort_order") or 1))
            is_active = bool(request.POST.get("is_active"))

            exp_val = max(1, int(request.POST.get("expire_value") or 30))
            exp_unit = request.POST.get("expire_unit", "days")
            unit_to_seconds = {
                "hours": 3600,
                "days": 86400,
                "months": 2592000,
            }
            expire_seconds = exp_val * unit_to_seconds.get(exp_unit, 86400)
            duration_days = max(1, round(expire_seconds / 86400))

            template_mode = request.POST.get("template_mode", "create_new")
            resolved_tpl_id = None

            if template_mode == "use_existing":
                raw_tpl_id = request.POST.get("existing_template_id")
                if raw_tpl_id and str(raw_tpl_id).isdigit():
                    resolved_tpl_id = int(raw_tpl_id)
            else:
                tpl_name = (request.POST.get("template_name") or title).strip()
                group_ids = [
                    int(gid)
                    for gid in request.POST.getlist("group_ids")
                    if str(gid).isdigit()
                ]
                if not group_ids:
                    group_ids = resolve_default_group_ids_for_plan_type(plan_type)

                status = request.POST.get("status", "active")
                on_hold_timeout = int(request.POST.get("on_hold_timeout") or 86400)
                method = request.POST.get("method", "chacha20-ietf-poly1305")
                raw_hwid = (request.POST.get("hwid_limit") or "").strip()
                hwid_limit = int(raw_hwid) if raw_hwid != "" else None
                username_prefix = request.POST.get("username_prefix")
                username_suffix = request.POST.get("username_suffix")
                reset_strategy = request.POST.get("data_limit_reset_strategy", "no_reset")
                reset_usages = bool(request.POST.get("reset_usages"))

                ok, created_tpl_id, err = create_or_update_user_template(
                    name=tpl_name,
                    group_ids=group_ids,
                    data_limit_bytes=volume_gb * 1073741824,
                    expire_duration_seconds=expire_seconds,
                    status=status,
                    on_hold_timeout_seconds=on_hold_timeout,
                    data_limit_reset_strategy=reset_strategy,
                    reset_usages=reset_usages,
                    hwid_limit=hwid_limit,
                    username_prefix=username_prefix,
                    username_suffix=username_suffix,
                    method=method,
                )
                if not ok:
                    self.message_user(
                        request,
                        f"خطا در ساخت قالب پاسارگارد: {err}",
                        level=messages.ERROR,
                    )
                    return redirect(request.path)
                resolved_tpl_id = created_tpl_id

            plan = Plan.objects.create(
                plan_type=plan_type,
                title=title,
                pasarguard_template_id=resolved_tpl_id,
                volume_gb=volume_gb,
                duration_days=duration_days,
                max_users=max_users,
                price=price,
                is_active=is_active,
                sort_order=sort_order,
            )
            self.message_user(
                request,
                f"پلن «{plan.title}» با موفقیت ساخته شد (Template ID: #{resolved_tpl_id}).",
                level=messages.SUCCESS,
            )
            return redirect(changelist_url)

        raw_templates = fetch_pasarguard_templates_list()
        formatted_templates = []
        for t in raw_templates:
            d_bytes = int(t.get("data_limit") or 0)
            exp_sec = int(t.get("expire_duration") or 0)
            formatted_templates.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "data_limit_gb": round(d_bytes / 1073741824, 2) if d_bytes > 0 else 0,
                    "expire_days": round(exp_sec / 86400, 1) if exp_sec > 0 else 0,
                }
            )

        direct_max = (
            Plan.objects.filter(plan_type="direct").aggregate(m=Max("sort_order"))["m"] or 0
        )
        tunnel_max = (
            Plan.objects.filter(plan_type="tunnel").aggregate(m=Max("sort_order"))["m"] or 0
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "افزودن پلن فروش",
            "templates_list": formatted_templates,
            "groups_list": fetch_pasarguard_groups(),
            "next_direct_order": direct_max + 1,
            "next_tunnel_order": tunnel_max + 1,
            "cancel_url": changelist_url,
        }
        return render(
            request,
            "admin/core/plan/add_plan.html",
            context,
        )

    @action(
        description="همگام‌سازی پلن‌ها با پاسارگارد",
        url_path="sync-plans-pasarguard",
    )
    def sync_all_plans_to_pasarguard(
            self,
            request,
    ):
        synced = 0
        for plan in Plan.objects.all():
            type_prefix = "Direct" if plan.plan_type == "direct" else "Tunnel"
            tpl_name = (
                f"{type_prefix} {plan.volume_gb}GB {plan.duration_days}D"
                if plan.volume_gb > 0
                else f"{type_prefix} Unlim {plan.max_users}U"
            )
            group_ids = resolve_default_group_ids_for_plan_type(plan.plan_type)
            hwid = plan.max_users if (plan.volume_gb == 0 or plan.max_users > 1) else None
            ok, tpl_id, _ = create_or_update_user_template(
                name=tpl_name,
                group_ids=group_ids,
                data_limit_bytes=plan.volume_gb * 1073741824,
                expire_duration_seconds=plan.duration_days * 86400,
                hwid_limit=hwid,
                template_id=plan.pasarguard_template_id,
            )
            if ok and tpl_id:
                if plan.pasarguard_template_id != tpl_id:
                    plan.pasarguard_template_id = tpl_id
                    plan.save(update_fields=['pasarguard_template_id'])
                synced += 1

        self.message_user(
            request,
            f"{synced} پلن با پاسارگارد همگام‌سازی شد.",
            level=messages.SUCCESS,
        )
        return redirect(reverse_lazy("admin:core_plan_changelist"))


@admin.register(Transaction)
class TransactionAdmin(ModelAdmin):
    list_display = (
        'invoice_number',
        'user',
        'formatted_amount',
        'target_plan',
        'target_custom_name',
        'receipt_preview',
        'status',
        'jalali_created_at',
    )
    list_filter = (
        'status',
        'created_at',
    )
    search_fields = (
        'invoice_number',
        'user__telegram_id',
        'user__username',
    )
    readonly_fields = (
        'invoice_number',
        'receipt_preview_large',
        'jalali_created_at',
    )
    exclude = ('created_at',)
    actions = [
        'approve_transactions',
        'reject_transactions',
    ]

    @admin.display(description="مبلغ")
    def formatted_amount(
            self,
            obj,
    ):
        return f"{obj.amount:,} تومان"

    @admin.display(
        description="تاریخ ایجاد (شمسی)",
        ordering="created_at",
    )
    def jalali_created_at(
            self,
            obj,
    ):
        return format_jalali(obj.created_at)

    @admin.display(description="تصویر رسید")
    def receipt_preview(
            self,
            obj,
    ):
        if obj.receipt_image:
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="height: 55px; width: auto; border-radius: 6px; border: 1px solid #4b5563;" title="برای بزرگنمایی کلیک کنید" />'
                '</a>',
                obj.receipt_image.url,
                obj.receipt_image.url,
            )
        if obj.receipt_text:
            return "📝 رسید متنی"
        return "—"

    @admin.display(description="مشاهده تصویر کامل رسید")
    def receipt_preview_large(
            self,
            obj,
    ):
        if obj.receipt_image:
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-height: 420px; border-radius: 10px; border: 2px solid #6366f1;" />'
                '</a>',
                obj.receipt_image.url,
                obj.receipt_image.url,
            )
        return "تصویری آپلود نشده است."

    def _notify_approved_tx(
            self,
            tx,
            auto_order,
    ):
        if auto_order:
            if auto_order.status == 'active' and auto_order.config_link:
                exp_str = format_jalali(
                    auto_order.expires_at,
                    include_time=False,
                )
                send_telegram_message_sync(
                    tx.user.telegram_id,
                    f"🎉 <b>پرداخت شما تایید شد و سرویس شما به صورت آنی فعال گردید!</b>\n\n"
                    f"🏷 نام سرویس: <code>{auto_order.custom_name}</code>\n"
                    f"📦 بسته: {auto_order.plan.title}\n"
                    f"⏳ تاریخ انقضا: <b>{exp_str}</b>\n"
                    f"💳 موجودی باقیمانده کیف پول: <b>{tx.user.wallet_balance:,} تومان</b>\n\n"
                    f"🔗 <b>لینک کانفیگ / اشتراک شما:</b>\n"
                    f"<code>{auto_order.config_link}</code>\n\n"
                    f"💡 از دکمه‌های زیر می‌توانید لینک را کپی کنید یا QR Code آن را دریافت نمایید:",
                    reply_markup=build_service_actions_reply_markup_sync(
                        auto_order.id,
                        auto_order.config_link,
                    ),
                )
            else:
                send_telegram_message_sync(
                    tx.user.telegram_id,
                    f"✅ <b>رسید شما تایید شد و سفارش سرویس <code>{auto_order.custom_name}</code> ({auto_order.plan.title}) به صورت خودکار ثبت گردید!</b>\n\n"
                    f"⏳ لینک کانفیگ شما در صف آماده‌سازی قرار گرفت و به محض صدور، همین‌جا برایتان ارسال خواهد شد.",
                )
        else:
            send_telegram_message_sync(
                tx.user.telegram_id,
                f"✅ <b>رسید شما تایید شد!</b>\n\n"
                f"🧾 شماره فاکتور: <code>#{tx.invoice_number}</code>\n"
                f"💰 مبلغ شارژ شده: <b>{tx.amount:,} تومان</b>\n"
                f"💳 موجودی فعلی کیف پول: <b>{tx.user.wallet_balance:,} تومان</b>\n\n"
                f"هم‌اکنون می‌توانید از منوی «🛒 خرید سرویس» اشتراک خود را تهیه کنید.",
            )

    def save_model(
            self,
            request,
            obj,
            form,
            change,
    ):
        if obj.status == 'approved' and not obj.is_processed:
            super().save_model(
                request,
                obj,
                form,
                change,
            )
            success, _, updated_tx, auto_order = approve_transaction_sync(obj.id)
            if success and updated_tx:
                self._notify_approved_tx(
                    updated_tx,
                    auto_order,
                )
            return

        if obj.status == 'rejected' and not obj.is_processed:
            obj.is_processed = True
            reason = f"\n📝 توضیحات ادمین: {obj.admin_note}" if obj.admin_note else ""
            send_telegram_message_sync(
                obj.user.telegram_id,
                f"❌ <b>فاکتور #{obj.invoice_number} به مبلغ {obj.amount:,} تومان تایید نشد.</b>{reason}",
            )
        super().save_model(
            request,
            obj,
            form,
            change,
        )

    @admin.action(description="✅ تایید رسیدهای انتخاب شده و ساخت خودکار کانفیگ در پاسارگارد")
    def approve_transactions(
            self,
            request,
            queryset,
    ):
        for tx in queryset.filter(is_processed=False):
            success, _, updated_tx, auto_order = approve_transaction_sync(tx.id)
            if success and updated_tx:
                self._notify_approved_tx(
                    updated_tx,
                    auto_order,
                )

    @admin.action(description="❌ رد کردن رسیدهای انتخاب شده")
    def reject_transactions(
            self,
            request,
            queryset,
    ):
        for tx in queryset.filter(is_processed=False):
            tx.status = 'rejected'
            self.save_model(
                request,
                tx,
                None,
                True,
            )


@admin.register(SubscriptionOrder)
class SubscriptionOrderAdmin(ModelAdmin):
    list_display = (
        'custom_name',
        'panel_username',
        'user',
        'plan',
        'order_type',
        'status',
        'jalali_created_at',
        'jalali_expires_at',
    )
    list_filter = (
        'status',
        'order_type',
        'created_at',
    )
    search_fields = (
        'custom_name',
        'panel_username',
        'user__telegram_id',
        'user__username',
    )
    readonly_fields = (
        'jalali_created_at',
    )
    exclude = ('created_at',)
    actions = ['retry_pasarguard_generation']

    @admin.display(
        description="تاریخ ثبت (شمسی)",
        ordering="created_at",
    )
    def jalali_created_at(
            self,
            obj,
    ):
        return format_jalali(obj.created_at)

    @admin.display(
        description="تاریخ انقضا (شمسی)",
        ordering="expires_at",
    )
    def jalali_expires_at(
            self,
            obj,
    ):
        return format_jalali(
            obj.expires_at,
            include_time=False,
        )

    @admin.action(description="🔄 ساخت خودکار کانفیگ در پنل پاسارگارد برای سفارش‌های منتظر")
    def retry_pasarguard_generation(
            self,
            request,
            queryset,
    ):
        bot_setting, _ = BotSetting.objects.get_or_create(id=1)
        success_count = 0

        for order in queryset.filter(status='pending_config'):
            tpl_id = None
            days = 1
            if order.order_type == 'purchase' and order.plan:
                tpl_id = order.plan.pasarguard_template_id
                days = order.plan.duration_days
            elif order.order_type == 'free_test':
                tpl_id = bot_setting.free_test_template_id
                days = max(
                    1,
                    bot_setting.free_test_days,
                )
            elif order.order_type == 'referral_gift':
                tpl_id = bot_setting.referral_gift_template_id
                days = max(
                    1,
                    bot_setting.referral_gift_days,
                )

            if not tpl_id:
                continue

            ok, sub_url, panel_user, _ = create_user_from_template(
                template_id=tpl_id,
                base_username=order.custom_name,
                note=f"Retry Order #{order.id} | TG: {order.user.telegram_id}",
            )
            if ok and sub_url:
                order.config_link = sub_url.strip()
                order.panel_username = panel_user
                order.status = 'active'
                order.notified_user = True
                order.expires_at = timezone.now() + timedelta(days=days)
                order.save()
                exp_str = format_jalali(
                    order.expires_at,
                    include_time=False,
                )
                send_telegram_message_sync(
                    order.user.telegram_id,
                    f"🎉 <b>سرویس شما آماده و فعال شد!</b>\n\n"
                    f"🏷 نام سرویس: <code>{order.custom_name}</code>\n"
                    f"⏳ تاریخ انقضا: <b>{exp_str}</b>\n\n"
                    f"🔗 <b>لینک کانفیگ / اشتراک شما:</b>\n"
                    f"<code>{order.config_link}</code>\n\n"
                    f"💡 از دکمه‌های زیر می‌توانید لینک را کپی کنید یا QR Code آن را دریافت نمایید:",
                    reply_markup=build_service_actions_reply_markup_sync(
                        order.id,
                        order.config_link,
                    ),
                )
                success_count += 1

        self.message_user(
            request,
            f"{success_count} سفارش با موفقیت در پاسارگارد ساخته و برای کاربران ارسال شد.",
            level=messages.SUCCESS,
        )

    def save_model(
            self,
            request,
            obj,
            form,
            change,
    ):
        if obj.status == 'active' and obj.config_link and not obj.notified_user:
            if not obj.expires_at:
                days = obj.plan.duration_days if obj.plan else 1
                obj.expires_at = timezone.now() + timedelta(days=days)
            obj.notified_user = True
            exp_str = format_jalali(
                obj.expires_at,
                include_time=False,
            )
            send_telegram_message_sync(
                obj.user.telegram_id,
                f"🎉 <b>سرویس شما آماده و فعال شد!</b>\n\n"
                f"🏷 نام سرویس: <code>{obj.custom_name}</code>\n"
                f"📦 نوع سفارش: {obj.get_order_type_display()}\n"
                f"⏳ تاریخ انقضا: <b>{exp_str}</b>\n\n"
                f"🔗 <b>لینک کانفیگ / اشتراک شما:</b>\n"
                f"<code>{obj.config_link}</code>\n\n"
                f"💡 از دکمه‌های زیر می‌توانید لینک را کپی کنید یا QR Code آن را دریافت نمایید:",
                reply_markup=build_service_actions_reply_markup_sync(
                    obj.id,
                    obj.config_link,
                ),
            )
        super().save_model(
            request,
            obj,
            form,
            change,
        )


@admin.register(SupportTicket)
class SupportTicketAdmin(ModelAdmin):
    list_display = (
        'id',
        'user',
        'status',
        'jalali_created_at',
    )
    list_filter = (
        'status',
        'created_at',
    )
    search_fields = (
        'user__telegram_id',
        'user__username',
        'user_message',
    )
    readonly_fields = (
        'user',
        'user_message',
        'jalali_created_at',
    )
    exclude = ('created_at',)

    @admin.display(
        description="تاریخ ثبت (شمسی)",
        ordering="created_at",
    )
    def jalali_created_at(
            self,
            obj,
    ):
        return format_jalali(obj.created_at)

    def save_model(
            self,
            request,
            obj,
            form,
            change,
    ):
        if obj.admin_reply and not obj.reply_sent:
            obj.status = 'answered'
            obj.reply_sent = True
            send_telegram_message_sync(
                obj.user.telegram_id,
                f"📩 <b>پاسخ پشتیبانی به تیکت #{obj.id}:</b>\n\n"
                f"🗣 پیام شما: <i>{obj.user_message}</i>\n\n"
                f"👨‍💻 <b>پاسخ ادمین:</b>\n{obj.admin_reply}",
            )
        super().save_model(
            request,
            obj,
            form,
            change,
        )


@admin.register(RequiredChannel)
class RequiredChannelAdmin(ModelAdmin):
    list_display = (
        'title',
        'chat_id',
        'invite_link',
        'is_active',
        'sort_order',
    )
    list_filter = ('is_active',)
    list_editable = (
        'invite_link',
        'is_active',
        'sort_order',
    )
    search_fields = (
        'title',
        'chat_id',
    )


@admin.register(BotSetting)
class BotSettingAdmin(ModelAdmin):
    actions_list = [
        'reset_all_free_tests_from_settings',
    ]
    actions_detail = [
        'reset_all_free_tests_detail',
    ]

    @action(
        description="ریست و فعال‌سازی تست برای همه",
        url_path="reset-all-free-tests-settings",
    )
    def reset_all_free_tests_from_settings(
            self,
            request,
    ):
        cancel_url = str(reverse_lazy("admin:core_botsetting_changelist"))
        if request.method == "POST" and request.POST.get("confirm") == "yes":
            execute_global_free_test_reset(
                self,
                request,
            )
            return redirect(cancel_url)
        return render_free_test_reset_confirmation(
            self,
            request,
            cancel_url,
        )

    @action(
        description="ریست و فعال‌سازی تست برای همه",
        url_path="reset-all-free-tests-detail",
    )
    def reset_all_free_tests_detail(
            self,
            request,
            object_id,
    ):
        cancel_url = str(
            reverse_lazy(
                "admin:core_botsetting_change",
                args=[object_id],
            )
        )
        if request.method == "POST" and request.POST.get("confirm") == "yes":
            execute_global_free_test_reset(
                self,
                request,
            )
            return redirect(cancel_url)
        return render_free_test_reset_confirmation(
            self,
            request,
            cancel_url,
        )

    def has_add_permission(
            self,
            request,
    ):
        return not BotSetting.objects.exists()


def run_broadcast_background(msg_id: int, text: str):
    user_ids = get_all_active_user_ids_sync()
    success = 0
    for uid in user_ids:
        is_ok = send_telegram_message_sync(
            uid,
            f"📢 <b>اطلاعیه:</b>\n➖➖➖➖➖➖➖➖➖➖\n{text}"
        )
        if is_ok:
            success += 1
        time.sleep(0.05)

    BroadcastMessage.objects.filter(id=msg_id).update(
        is_sent=True,
        success_count=success,
    )


@admin.register(BroadcastMessage)
class BroadcastMessageAdmin(ModelAdmin):
    list_display = (
        'id',
        'short_message',
        'is_sent',
        'success_count',
        'jalali_created_at',
    )
    readonly_fields = (
        'is_sent',
        'success_count',
        'jalali_created_at',
    )
    exclude = ('created_at',)
    search_fields = ('message',)

    @admin.display(description="متن پیام")
    def short_message(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message

    @admin.display(description="تاریخ ایجاد", ordering="created_at")
    def jalali_created_at(self, obj):
        return format_jalali(obj.created_at)

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None
        super().save_model(request, obj, form, change)

        if is_new:
            threading.Thread(
                target=run_broadcast_background,
                args=(obj.id, obj.message),
                daemon=True
            ).start()

            self.message_user(
                request,
                "✅ پیام شما ثبت شد و در پس‌زمینه در حال ارسال به کاربران است (پس از اتمام، تیک ارسال می‌خورد).",
                level=messages.SUCCESS,
            )