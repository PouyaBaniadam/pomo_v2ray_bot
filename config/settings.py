import os
from pathlib import Path

import dj_database_url
from django.urls import reverse_lazy
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'default-secret-key',
)
DEBUG = os.getenv(
    'DEBUG',
    'True',
) == 'True'
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core.apps.CoreConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv(
            'DATABASE_URL',
            'postgresql://postgres:postgres@db:5432/pomov2raybot_db',
        ),
        conn_max_age=600,
    )
}

LANGUAGE_CODE = 'fa'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('fa', 'Persian'),
]

STATIC_URL = 'static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

UNFOLD = {
    "SITE_TITLE": "مدیریت Pomov2rayBot",
    "SITE_HEADER": "پنل مدیریت فروش VPN",
    "SITE_URL": "/admin/",
    "STYLES": [
        "/static/css/custom_admin.css",
    ],
    "COLORS": {
        "primary": {
            "50": "245 243 255",
            "100": "237 233 254",
            "200": "221 214 254",
            "300": "196 181 253",
            "400": "167 139 250",
            "500": "139 92 246",
            "600": "124 58 237",
            "700": "109 40 217",
            "800": "91 33 182",
            "900": "76 29 149",
            "950": "46 16 101",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "مدیریت فروش و اشتراک‌ها",
                "separator": True,
                "items": [
                    {
                        "title": "سفارش‌ها و کانفیگ‌ها",
                        "icon": "vpn_key",
                        "link": reverse_lazy("admin:core_subscriptionorder_changelist"),
                    },
                    {
                        "title": "پلن‌های فروش",
                        "icon": "tune",
                        "link": reverse_lazy("admin:core_plan_changelist"),
                    },
                ],
            },
            {
                "title": "امور مالی و کیف پول",
                "separator": True,
                "items": [
                    {
                        "title": "فاکتورها و رسیدها",
                        "icon": "receipt_long",
                        "link": reverse_lazy("admin:core_transaction_changelist"),
                    },
                    {
                        "title": "آمار کلی و حسابداری",
                        "icon": "monitoring",
                        "link": reverse_lazy("admin:core_accountingreport_changelist"),
                    },
                ],
            },
            {
                "title": "کاربران و پشتیبانی",
                "separator": True,
                "items": [
                    {
                        "title": "کاربران و ادمین‌های تلگرام",
                        "icon": "group",
                        "link": reverse_lazy("admin:core_telegramuser_changelist"),
                    },
                    {
                        "title": "پیام‌های همگانی",
                        "icon": "campaign",
                        "link": reverse_lazy("admin:core_broadcastmessage_changelist"),
                    },
                    {
                        "title": "تیکت‌های پشتیبانی",
                        "icon": "support_agent",
                        "link": reverse_lazy("admin:core_supportticket_changelist"),
                    },
                ],
            },
            {
                "title": "تنظیمات سیستم",
                "separator": True,
                "items": [
                    {
                        "title": "کانال‌های جوین اجباری",
                        "icon": "campaign",
                        "link": reverse_lazy("admin:core_requiredchannel_changelist"),
                    },
                    {
                        "title": "تنظیمات کلی و اتصال پنل",
                        "icon": "settings",
                        "link": reverse_lazy("admin:core_botsetting_changelist"),
                    },
                ],
            },
        ],
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

BOT_TOKEN = os.getenv(
    'BOT_TOKEN',
    '',
).strip()
BOT_USERNAME = os.getenv(
    'BOT_USERNAME',
    'Pomov2rayBot',
).strip()
ADMIN_TELEGRAM_ID = int(
    os.getenv(
        'ADMIN_TELEGRAM_ID',
        '0',
    ) or 0
)
REDIS_URL = os.getenv(
    'REDIS_URL',
    '',
).strip()
PROXY_URL = os.getenv(
    'PROXY_URL',
    '',
).strip()

PASARGUARD_BASE_URL = os.getenv(
    'PASARGUARD_BASE_URL',
    '',
).rstrip('/')
PASARGUARD_API_KEY = os.getenv(
    'PASARGUARD_API_KEY',
    '',
).strip()
PASARGUARD_VERIFY_SSL = os.getenv(
    'PASARGUARD_VERIFY_SSL',
    'False',
) == 'True'