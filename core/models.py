import os
import random
from django.db import models
from django.utils import timezone
from core.jalali import get_current_jalali_year_month


def generate_invoice_number():
    return str(
        random.randint(
            100000,
            999999,
        )
    )


def receipt_image_upload_to(
    instance,
    filename: str,
) -> str:
    j_year, j_month = get_current_jalali_year_month()
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    inv = instance.invoice_number or "receipt"
    ts = int(timezone.now().timestamp())
    return f"receipts/{j_year}/{j_month}/inv_{inv}_{ts}{ext}"


class TelegramUser(models.Model):
    telegram_id = models.BigIntegerField(
        unique=True,
        primary_key=True,
        verbose_name="آیدی عددی تلگرام",
    )
    username = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        verbose_name="یوزرنیم تلگرام",
    )
    full_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="نام کامل",
    )
    wallet_balance = models.PositiveBigIntegerField(
        default=0,
        verbose_name="موجودی کیف پول (تومان)",
    )
    used_free_test = models.BooleanField(
        default=False,
        verbose_name="تست رایگان دریافت شده؟",
    )
    is_admin = models.BooleanField(
        default=False,
        verbose_name="ادمین ربات؟",
        help_text="با فعال کردن این تیک، کاربر در تلگرام به منوی /admin، تایید رسیدها و پاسخ به تیکت‌ها دسترسی خواهد داشت.",
    )

    referred_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals',
        verbose_name="دعوت شده توسط",
    )
    valid_referrals_count = models.PositiveIntegerField(
        default=0,
        verbose_name="تعداد دعوت‌های موفق",
    )
    referral_gifts_received = models.PositiveIntegerField(
        default=0,
        verbose_name="تعداد هدایای رفرال دریافتی",
    )

    is_banned = models.BooleanField(
        default=False,
        verbose_name="مسدود شده؟",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ عضویت",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="آخرین فعالیت",
    )

    class Meta:
        verbose_name = "کاربر تلگرام"
        verbose_name_plural = "کاربران و ادمین‌های تلگرام"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.full_name or 'بدون نام'} ({self.telegram_id})"


class Plan(models.Model):
    PLAN_TYPES = (
        ('direct', '⚡ اشتراک دایرکت (حجمی و نامحدود)'),
        ('tunnel', '🛡 اشتراک تانل (حجمی)'),
    )
    plan_type = models.CharField(
        max_length=20,
        choices=PLAN_TYPES,
        default='direct',
        verbose_name="دسته‌بندی سرور (دایرکت / تانل)",
    )
    title = models.CharField(
        max_length=150,
        verbose_name="عنوان نمایشی روی دکمه",
    )
    pasarguard_template_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="شناسه قالب پاسارگارد (Template ID)",
        help_text="عدد ID قالب مربوط به این پلن در بخش User Templates پنل پاسارگارد را وارد کنید.",
    )
    volume_gb = models.PositiveIntegerField(
        default=0,
        verbose_name="حجم (گیگابایت)",
        help_text="اگر پلن حجمی است عدد گیگ (مثلاً 30) را بنویسید. اگر پلن نامحدود است عدد 0 بگذارید.",
    )
    duration_days = models.PositiveIntegerField(
        default=30,
        verbose_name="مدت اعتبار (روز)",
    )
    max_users = models.PositiveIntegerField(
        default=1,
        verbose_name="تعداد کاربر مجاز",
        help_text="برای پلن‌های حجمی 1 بگذارید و برای نامحدودها تعداد کاربر (مثلاً 2 یا 3) را وارد کنید.",
    )
    price = models.PositiveBigIntegerField(
        verbose_name="قیمت (تومان)",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="فعال در ربات؟",
    )
    sort_order = models.PositiveIntegerField(
        default=1,
        verbose_name="ترتیب نمایش",
    )

    class Meta:
        verbose_name = "پلن فروش"
        verbose_name_plural = "پلن‌های فروش (دایرکت و تانل)"
        ordering = [
            'plan_type',
            'sort_order',
            'price',
        ]

    def __str__(self):
        return f"[{self.get_plan_type_display()}] {self.title} - {self.price:,} تومان"


class Transaction(models.Model):
    STATUS_CHOICES = (
        ('awaiting_receipt', 'در انتظار ارسال رسید توسط کاربر'),
        ('pending_admin', 'در انتظار بررسی ادمین ⏳'),
        ('approved', 'تایید و شارژ شده ✅'),
        ('rejected', 'رد شده ❌'),
        ('canceled', 'لغو شده توسط کاربر'),
    )
    invoice_number = models.CharField(
        max_length=20,
        default=generate_invoice_number,
        unique=True,
        verbose_name="شماره فاکتور",
    )
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name="کاربر",
    )
    amount = models.PositiveBigIntegerField(
        verbose_name="مبلغ (تومان)",
    )
    target_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='targeted_transactions',
        verbose_name="پلن مقصد (خرید خودکار)",
    )
    target_custom_name = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="نام سرویس انتخابی",
    )
    receipt_image = models.ImageField(
        upload_to=receipt_image_upload_to,
        null=True,
        blank=True,
        verbose_name="تصویر رسید",
    )
    receipt_text = models.TextField(
        null=True,
        blank=True,
        verbose_name="متن رسید / توضیحات کاربر",
    )
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default='awaiting_receipt',
        verbose_name="وضعیت",
    )
    admin_note = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="توضیحات ادمین (علت رد و...)",
    )
    is_processed = models.BooleanField(
        default=False,
        editable=False,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ایجاد",
    )

    class Meta:
        verbose_name = "فاکتور و رسید پرداخت"
        verbose_name_plural = "فاکتورها و رسیدهای کارت به کارت"
        ordering = ['-created_at']

    def __str__(self):
        return f"فاکتور #{self.invoice_number} - {self.amount:,} تومان ({self.get_status_display()})"


class SubscriptionOrder(models.Model):
    ORDER_TYPES = (
        ('purchase', 'خرید عادی'),
        ('free_test', 'تست رایگان'),
        ('referral_gift', 'هدیه دعوت دوستان'),
    )
    STATUS_CHOICES = (
        ('pending_config', 'در انتظار صدور لینک کانفیگ ⏳'),
        ('active', 'فعال و تحویل داده شده ✅'),
        ('expired', 'منقضی شده 🔚'),
    )
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name="کاربر",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="پلن انتخابی",
    )
    order_type = models.CharField(
        max_length=20,
        choices=ORDER_TYPES,
        default='purchase',
        verbose_name="نوع سفارش",
    )
    custom_name = models.CharField(
        max_length=50,
        verbose_name="نام سرویس",
    )
    panel_username = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        verbose_name="نام کاربری در پنل PasarGuard",
    )
    config_link = models.TextField(
        null=True,
        blank=True,
        verbose_name="لینک کانفیگ / اشتراک",
        help_text="به صورت خودکار توسط پنل پاسارگارد ساخته می‌شود (در صورت نیاز می‌توانید دستی هم وارد کنید).",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_config',
        verbose_name="وضعیت",
    )
    price_paid = models.PositiveBigIntegerField(
        default=0,
        verbose_name="مبلغ پرداخت شده (تومان)",
    )
    notified_user = models.BooleanField(
        default=False,
        editable=False,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ثبت",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="تاریخ انقضا",
    )

    class Meta:
        verbose_name = "سفارش سرویس (کانفیگ)"
        verbose_name_plural = "سفارش‌ها و کانفیگ‌های کاربران"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.custom_name} ({self.user.telegram_id})"


class SupportTicket(models.Model):
    STATUS_CHOICES = (
        ('open', 'در انتظار پاسخ ادمین 🟡'),
        ('answered', 'پاسخ داده شده ✅'),
        ('closed', 'بسته شده 🔒'),
    )
    user = models.ForeignKey(
        TelegramUser,
        on_delete=models.CASCADE,
        related_name='tickets',
        verbose_name="کاربر",
    )
    user_message = models.TextField(
        verbose_name="پیام کاربر",
    )
    admin_reply = models.TextField(
        null=True,
        blank=True,
        verbose_name="پاسخ ادمین",
        help_text="پاسخ خود را بنویسید و ذخیره کنید تا به صورت خودکار در تلگرام برای کاربر ارسال شود.",
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='open',
        verbose_name="وضعیت",
    )
    reply_sent = models.BooleanField(
        default=False,
        editable=False,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ثبت",
    )

    class Meta:
        verbose_name = "تیکت پشتیبانی"
        verbose_name_plural = "تیکت‌های پشتیبانی"
        ordering = ['-created_at']

    def __str__(self):
        return f"تیکت #{self.id} از {self.user.telegram_id}"


class RequiredChannel(models.Model):
    title = models.CharField(
        max_length=100,
        default="📢 عضویت در کانال رسمی",
        verbose_name="عنوان روی دکمه شیشه‌ای",
    )
    chat_id = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="یوزرنیم یا آیدی کانال (مثلاً @AxonNegar)",
        help_text="یوزرنیم کانال با @ (مثل @AxonNegar) یا آیدی عددی کانال خصوصی (مثل -100123456789). حتماً ربات را در کانال ادمین کنید.",
    )
    invite_link = models.URLField(
        default="https://t.me/AxonNegar",
        verbose_name="لینک عضویت کانال (مثلاً https://t.me/AxonNegar)",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="فعال باشد؟",
    )
    sort_order = models.PositiveIntegerField(
        default=1,
        verbose_name="ترتیب نمایش دکمه",
    )

    class Meta:
        verbose_name = "کانال جوین اجباری"
        verbose_name_plural = "کانال‌های جوین اجباری"
        ordering = [
            'sort_order',
            'id',
        ]

    def __str__(self):
        return f"{self.title} ({self.chat_id})"


class BotSetting(models.Model):
    welcome_text = models.TextField(
        default="درود، کاربر گرامی خوش اومدی!",
        verbose_name="متن خوش‌آمدگویی استارت ربات (/start)",
    )
    card_number = models.CharField(
        max_length=30,
        default="6037-9975-0000-0000",
        verbose_name="شماره کارت جهت واریز",
    )
    card_holder = models.CharField(
        max_length=100,
        default="پوریا صیادی",
        verbose_name="نام صاحب کارت",
    )
    min_wallet_charge = models.PositiveBigIntegerField(
        default=10000,
        verbose_name="حداقل مبلغ شارژ کیف پول (تومان)",
    )
    wallet_preset_amounts = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        default="",
        verbose_name="مبالغ پیشنهادی شارژ کیف پول (اختیاری)",
        help_text="اگر خالی باشد، به صورت خودکار از قیمت پلن‌های فعال ساخته می‌شود. برای تنظیم دستی، مبالغ را با کاما جدا کنید (مثلاً: 100000,200000,500000).",
    )
    max_receipt_size_mb = models.PositiveIntegerField(
        default=3,
        verbose_name="حداکثر حجم مجاز فایل رسید (مگابایت)",
        help_text="کاربران نمی‌توانند تصویری حجیم‌تر از این مقدار (به مگابایت) برای رسید ارسال کنند.",
    )
    receipt_cooldown_seconds = models.PositiveIntegerField(
        default=5,
        verbose_name="فاصله زمانی مجاز بین ارسال رسیدها (ثانیه)",
        help_text="حداقل زمان انتظار (بر حسب ثانیه) بین دو تلاش کاربر برای ارسال رسید.",
    )
    max_pending_receipts = models.PositiveIntegerField(
        default=3,
        verbose_name="حداکثر رسید در انتظار تایید همزمان برای هر کاربر",
        help_text="جلوگیری از اسپم فیش واریزی قبل از تعیین تکلیف رسیدهای قبلی توسط ادمین.",
    )
    max_open_tickets = models.PositiveIntegerField(
        default=2,
        verbose_name="حداکثر تیکت باز همزمان برای هر کاربر",
        help_text="جلوگیری از اسپم تیکت پشتیبانی قبل از پاسخ‌گویی ادمین.",
    )
    rate_limit_per_minute = models.PositiveIntegerField(
        default=25,
        verbose_name="محدودیت تعداد درخواست کاربر در دقیقه (Rate Limit)",
        help_text="حداکثر تعداد پیام یا کلیک مجاز هر کاربر در هر دقیقه برای جلوگیری از اسپم و فلود.",
    )
    support_username = models.CharField(
        max_length=100,
        default="Pomov2raySupport",
        verbose_name="آیدی پشتیبان (بدون @)",
    )

    pasarguard_base_url = models.URLField(
        max_length=255,
        blank=True,
        null=True,
        default="https://netmitvip.ir:8000",
        verbose_name="آدرس پنل پاسارگارد (Base URL)",
        help_text="مثلاً https://netmitvip.ir:8000 (بدون اسلش انتهایی)",
    )
    pasarguard_api_key = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="کلید ارتباطی پاسارگارد (API Key)",
        help_text="کلید ساخته شده در بخش API Keys پنل پاسارگارد (شروع با pg_key_). اگر خالی باشد از فایل .env خوانده می‌شود.",
    )
    pasarguard_verify_ssl = models.BooleanField(
        default=False,
        verbose_name="بررسی گواهی SSL پنل پاسارگارد؟",
    )

    free_test_enabled = models.BooleanField(
        default=True,
        verbose_name="فعال بودن دریافت تست رایگان؟",
    )
    free_test_template_id = models.PositiveIntegerField(
        default=9,
        null=True,
        blank=True,
        verbose_name="شناسه قالب تست رایگان در پاسارگارد (Template ID)",
    )
    free_test_title = models.CharField(
        max_length=100,
        default="۱۰۰ مگابایت - ۱ روزه",
        verbose_name="عنوان نمایشی تست رایگان",
    )
    free_test_days = models.PositiveIntegerField(
        default=1,
        verbose_name="مدت اعتبار تست رایگان (روز)",
    )

    referral_gift_template_id = models.PositiveIntegerField(
        default=8,
        null=True,
        blank=True,
        verbose_name="شناسه قالب هدیه دعوت در پاسارگارد (Template ID)",
    )
    referral_required_count = models.PositiveIntegerField(
        default=3,
        verbose_name="تعداد دعوت لازم برای هر هدیه",
    )
    referral_gift_title = models.CharField(
        max_length=100,
        default="۱۰ گیگابایت - ۱ روزه",
        verbose_name="عنوان نمایشی هدیه دعوت (مثلاً: ۱۰ گیگابایت - ۱ روزه)",
    )
    referral_gift_days = models.PositiveIntegerField(
        default=1,
        verbose_name="مدت اعتبار هدیه دعوت (روز)",
    )
    referral_share_text = models.CharField(
        max_length=255,
        default="تجربه یک اتصال باکیفیت و بدون محدودیت!",
        verbose_name="متن اشتراک‌گذاری لینک دعوت",
    )

    tutorial_android_url = models.URLField(
        default="https://t.me/Telegram",
        verbose_name="لینک آموزش اندروید",
    )
    tutorial_ios_url = models.URLField(
        default="https://t.me/Telegram",
        verbose_name="لینک آموزش آیفون (iOS)",
    )
    tutorial_windows_url = models.URLField(
        default="https://t.me/Telegram",
        verbose_name="لینک آموزش ویندوز",
    )

    buy_menu_text = models.TextField(
        default=(
            "🛒 <b>خرید سرویس اشتراک V2Ray</b>\n\n"
            "لطفاً نوع سرور و اشتراک مد نظر خود را انتخاب کنید:\n\n"
            "⚡ <b>حجمی دایرکت (Direct):</b> شامل بسته‌های حجمی و نامحدود با اتصال مستقیم و سرعت بالا.\n"
            "🛡 <b>حجمی تانل (Tunnel):</b> سرورهای تانل‌شده با پایداری حداکثری در تمامی اپراتورها."
        ),
        verbose_name="متن راهنمای منوی خرید سرویس",
    )
    direct_btn_title = models.CharField(
        max_length=100,
        default="⚡ حجمی دایرکت",
        verbose_name="عنوان دکمه دسته‌بندی دایرکت",
    )
    tunnel_btn_title = models.CharField(
        max_length=100,
        default="🛡 حجمی تانل",
        verbose_name="عنوان دکمه دسته‌بندی تانل",
    )
    volume_plan_header = models.TextField(
        default=(
            "⚡ <b>فیلترشکن پرسرعت دایرکت (Direct)</b>\n"
            "• پرسرعت و متصل در تمامی اپراتورها\n"
            "• شامل بسته‌های حجمی و نامحدود\n"
            "• پشتیبانی آنلاین ۲۴ ساعته + گارانتی"
        ),
        verbose_name="متن بالای پلن‌های دایرکت (Direct)",
    )
    unlimited_plan_header = models.TextField(
        default=(
            "🛡 <b>فیلترشکن تانل شده (Tunnel)</b>\n"
            "• پایداری حداکثری حتی در شرایط اختلال شدید\n"
            "• سرعت و پینگ عالی بدون محدودیت کاربر\n"
            "• پشتیبانی آنلاین ۲۴ ساعته + گارانتی"
        ),
        verbose_name="متن بالای پلن‌های تانل (Tunnel)",
    )

    sticker_welcome = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="File ID استیکر خوش‌آمدگویی",
    )
    sticker_account = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="File ID استیکر حساب کاربری",
    )
    sticker_buy = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="File ID استیکر خرید سرویس",
    )
    sticker_empty = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="File ID استیکر عدم وجود سرویس",
    )
    sticker_wallet = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="File ID استیکر کیف پول و رفرال",
    )

    class Meta:
        verbose_name = "تنظیمات ربات"
        verbose_name_plural = "تنظیمات کلی و اتصال پنل"

    def __str__(self):
        return "تنظیمات اصلی ربات و پاسارگارد"


class BroadcastMessage(models.Model):
    message = models.TextField(
        verbose_name="متن پیام",
        help_text="این پیام برای تمام کاربران فعال ربات ارسال خواهد شد.",
    )
    is_sent = models.BooleanField(
        default=False,
        verbose_name="وضعیت ارسال",
        help_text="پس از پایان ارسال در پس‌زمینه، تیک می‌خورد.",
    )
    success_count = models.PositiveIntegerField(
        default=0,
        verbose_name="تعداد ارسال موفق",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ایجاد",
    )

    class Meta:
        verbose_name = "پیام همگانی"
        verbose_name_plural = "پیام‌های همگانی"
        ordering = ['-created_at']

    def __str__(self):
        return f"پیام همگانی #{self.id}"