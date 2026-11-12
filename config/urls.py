from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = "پنل مدیریت ربات Pomov2rayBot"
admin.site.site_title = "مدیریت فروش VPN"
admin.site.index_title = "خوش آمدید | مدیریت کاربران، پلن‌ها و رسیدها"

urlpatterns = [
    path(
        'admin/',
        admin.site.urls,
    ),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )