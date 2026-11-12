import threading
import time
from datetime import timedelta

from django.contrib import (
    admin,
    messages,
)
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
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
from core.pasarguard import create_user_from_template


@admin.register(TelegramUser)
class TelegramUserAdmin(ModelAdmin):
    list_display = (
        'telegram_id',
        'full_name',
        'username',
        'formatted_balance',
        'is_admin',
        'used_free_test',
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
        'is_banned',
    )
    readonly_fields = (
        'telegram_id',
        'jalali_created_at',
        'jalali_updated_at',
    )
    exclude = (
        'created_at',
        'updated_at',
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

    @admin.display(description="قیمت")
    def formatted_price(
            self,
            obj,
    ):
        return f"{obj.price:,} تومان"


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