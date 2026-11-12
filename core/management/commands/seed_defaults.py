from django.conf import settings
from django.core.management.base import BaseCommand
from core.models import (
    Plan,
    BotSetting,
    RequiredChannel,
)
from core.pasarguard import fetch_template_name_to_id_map


class Command(BaseCommand):
    help = "Seed initial bot settings, default plans, PasarGuard template IDs, and required channels."

    def handle(
        self,
        *args,
        **options,
    ):
        live_map = fetch_template_name_to_id_map()
        fallback_map = {
            'Direct 30GB 30D': 1,
            'Direct 60GB 30D': 2,
            'Direct 120GB 60D': 3,
            'Direct Unlim 2U': 4,
            'Direct Unlim 3U': 5,
            'Tunnel 30GB 30D': 6,
            'Tunnel 60GB 30D': 7,
            'Referral Gift 10GB': 8,
            'Free Test': 9,
        }
        tpl_map = {
            **fallback_map,
            **live_map,
        }

        setting, _ = BotSetting.objects.get_or_create(
            id=1,
            defaults={
                'pasarguard_base_url': settings.PASARGUARD_BASE_URL or 'https://netmitvip.ir:8000',
                'pasarguard_api_key': settings.PASARGUARD_API_KEY or '',
                'pasarguard_verify_ssl': settings.PASARGUARD_VERIFY_SSL,
                'max_receipt_size_mb': 3,
                'receipt_cooldown_seconds': 5,
                'max_pending_receipts': 3,
                'max_open_tickets': 2,
                'rate_limit_per_minute': 25,
                'referral_required_count': 3,
                'referral_gift_title': '۱۰ گیگابایت - ۱ روزه',
                'referral_gift_days': 1,
                'referral_gift_template_id': tpl_map.get('Referral Gift 10GB', 8),
                'referral_share_text': 'تجربه یک اتصال باکیفیت و بدون محدودیت!',
                'free_test_enabled': True,
                'free_test_title': '۱۰۰ مگابایت - ۱ روزه',
                'free_test_days': 1,
                'free_test_template_id': tpl_map.get('Free Test', 9),
                'direct_btn_title': '⚡ حجمی دایرکت',
                'tunnel_btn_title': '🛡 حجمی تانل',
                'volume_plan_header': "⚡ لیست اشتراک‌های دایرکت (شامل بسته‌های حجمی و نامحدود با سرعت بالا):",
                'unlimited_plan_header': "🛡 لیست اشتراک‌های تانل (مخصوص پایداری حداکثری در تمامی اینترنت‌ها):",
            },
        )

        updated_fields = []
        if not setting.pasarguard_base_url and settings.PASARGUARD_BASE_URL:
            setting.pasarguard_base_url = settings.PASARGUARD_BASE_URL
            updated_fields.append('pasarguard_base_url')
        if not setting.pasarguard_api_key and settings.PASARGUARD_API_KEY:
            setting.pasarguard_api_key = settings.PASARGUARD_API_KEY
            updated_fields.append('pasarguard_api_key')
        if not setting.referral_gift_template_id:
            setting.referral_gift_template_id = tpl_map.get('Referral Gift 10GB', 8)
            updated_fields.append('referral_gift_template_id')
        if not setting.free_test_template_id:
            setting.free_test_template_id = tpl_map.get('Free Test', 9)
            updated_fields.append('free_test_template_id')
        if updated_fields:
            setting.save(update_fields=updated_fields)

        if not RequiredChannel.objects.exists():
            RequiredChannel.objects.create(
                chat_id='@AxonNegar',
                title='📢 عضویت در کانال آکسون نگار',
                invite_link='https://t.me/AxonNegar',
                is_active=True,
                sort_order=1,
            )

        default_plans = [
            {
                'plan_type': 'direct',
                'title': '⚡ ۳۰ گیگ دایرکت - ۱ ماهه (۱۰۰,۰۰۰ تومان)',
                'template_name': 'Direct 30GB 30D',
                'volume_gb': 30,
                'duration_days': 30,
                'max_users': 1,
                'price': 100000,
                'sort_order': 1,
            },
            {
                'plan_type': 'direct',
                'title': '⚡ ۶۰ گیگ دایرکت - ۱ ماهه (۱۸۰,۰۰۰ تومان)',
                'template_name': 'Direct 60GB 30D',
                'volume_gb': 60,
                'duration_days': 30,
                'max_users': 1,
                'price': 180000,
                'sort_order': 2,
            },
            {
                'plan_type': 'direct',
                'title': '⚡ ۱۲۰ گیگ دایرکت - ۲ ماهه (۳۰۰,۰۰۰ تومان)',
                'template_name': 'Direct 120GB 60D',
                'volume_gb': 120,
                'duration_days': 60,
                'max_users': 1,
                'price': 300000,
                'sort_order': 3,
            },
            {
                'plan_type': 'direct',
                'title': '♾ نامحدود دایرکت ۱ ماهه - ۲ کاربره (۳۲۰,۰۰۰ تومان)',
                'template_name': 'Direct Unlim 2U',
                'volume_gb': 0,
                'duration_days': 30,
                'max_users': 2,
                'price': 320000,
                'sort_order': 4,
            },
            {
                'plan_type': 'direct',
                'title': '♾ نامحدود دایرکت ۱ ماهه - ۳ کاربره (۳۹۰,۰۰۰ تومان)',
                'template_name': 'Direct Unlim 3U',
                'volume_gb': 0,
                'duration_days': 30,
                'max_users': 3,
                'price': 390000,
                'sort_order': 5,
            },
            {
                'plan_type': 'tunnel',
                'title': '🛡 ۳۰ گیگ تانل - ۱ ماهه (۱۲۰,۰۰۰ تومان)',
                'template_name': 'Tunnel 30GB 30D',
                'volume_gb': 30,
                'duration_days': 30,
                'max_users': 1,
                'price': 120000,
                'sort_order': 1,
            },
            {
                'plan_type': 'tunnel',
                'title': '🛡 ۶۰ گیگ تانل - ۱ ماهه (۲۱۰,۰۰۰ تومان)',
                'template_name': 'Tunnel 60GB 30D',
                'volume_gb': 60,
                'duration_days': 30,
                'max_users': 1,
                'price': 210000,
                'sort_order': 2,
            },
        ]

        for p in default_plans:
            tpl_id = tpl_map.get(p['template_name'])
            plan_obj, created = Plan.objects.get_or_create(
                title=p['title'],
                defaults={
                    'plan_type': p['plan_type'],
                    'pasarguard_template_id': tpl_id,
                    'volume_gb': p['volume_gb'],
                    'duration_days': p['duration_days'],
                    'max_users': p['max_users'],
                    'price': p['price'],
                    'sort_order': p['sort_order'],
                    'is_active': True,
                },
            )
            if not created and not plan_obj.pasarguard_template_id and tpl_id:
                plan_obj.pasarguard_template_id = tpl_id
                plan_obj.save(
                    update_fields=['pasarguard_template_id'],
                )

        self.stdout.write(
            self.style.SUCCESS(
                "Default settings, PasarGuard templates, and plans synced successfully."
            )
        )