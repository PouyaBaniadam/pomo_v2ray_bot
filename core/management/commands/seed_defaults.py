from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from core.models import (
    Plan,
    BotSetting,
    RequiredChannel,
)
from core.pasarguard import (
    fetch_template_name_to_id_map,
    create_or_update_user_template,
    resolve_default_group_ids_for_plan_type,
)

PRESET_WALLET_AMOUNTS = "49000,98000,148000,398000,89000,178000,268000,439000"
DEFAULT_CHANNEL_URL = "https://t.me/pomo_vpn"
DEFAULT_SUPPORT_USERNAME = "Pomoadmin"

DEFAULT_STICKERS = {
    "sticker_welcome": "CAACAgIAAxkBAAICKmr11cKbMrKSP8a65Lzz86FTalYuAAIxNAAC6BugStKvp8RmJqK8PQQ",
    "sticker_buy": "CAACAgIAAxkBAANXavRGS0a86I_PA5vhlSgBP-Bew8IAAjY_AAL8N0hJftW8yfivq4Y9BA",
    "sticker_wallet": "CAACAgIAAxkBAAIDx2r3W73SGEWEFAzQ1gn2chKqsZy5AAJ_PQACLckpSna3Jk8VU1wXPQQ",
    "sticker_account": "CAACAgIAAxkBAAIDz2r3XM24D09IHOAYsqte327B67kFAAI1LQACbgMoSiY-bw5YSe-3PQQ",
    "sticker_empty": "CAACAgIAAxkBAAIDy2r3XD_wDga_N3XQpWRj1PnqsOBUAALzQQACb7NoSV-j4NDXxKN2PQQ",
}


class Command(BaseCommand):
    help = "Seed initial bot settings, stickers, PasarGuard templates (On Hold, group bindings, tiered gifts), and the 10 default plans."

    def handle(
        self,
        *args,
        **options,
    ):
        setting, _ = BotSetting.objects.get_or_create(
            id=1,
            defaults={
                'pasarguard_base_url': settings.PASARGUARD_BASE_URL or 'https://netmitvip.ir:8000',
                'pasarguard_api_key': settings.PASARGUARD_API_KEY or '',
                'pasarguard_verify_ssl': settings.PASARGUARD_VERIFY_SSL,
                'wallet_preset_amounts': PRESET_WALLET_AMOUNTS,
                'max_receipt_size_mb': 3,
                'receipt_cooldown_seconds': 5,
                'max_pending_receipts': 3,
                'max_open_tickets': 2,
                'rate_limit_per_minute': 25,
                'support_username': DEFAULT_SUPPORT_USERNAME,
                'tutorial_android_url': DEFAULT_CHANNEL_URL,
                'tutorial_ios_url': DEFAULT_CHANNEL_URL,
                'tutorial_windows_url': DEFAULT_CHANNEL_URL,
                'referral_required_count': 3,
                'referral_gift_title': '۱۰ گیگابایت - ۱ روزه',
                'referral_gift_days': 1,
                'referral_milestone_10_title': '۳۰ گیگابایت - ۱ هفته‌ای',
                'referral_milestone_10_days': 7,
                'referral_milestone_20_title': '۱۰۰ گیگابایت - ۱ ماهه',
                'referral_milestone_20_days': 30,
                'referral_share_text': 'تجربه یک اتصال باکیفیت و بدون محدودیت!',
                'free_test_enabled': True,
                'free_test_title': '۱۰۰ مگابایت - ۱ روزه',
                'free_test_days': 1,
                'direct_btn_title': '⚡ حجمی دایرکت',
                'tunnel_btn_title': '🛡 حجمی تانل',
                **DEFAULT_STICKERS,
            },
        )

        updated_fields = []
        if not setting.pasarguard_base_url and settings.PASARGUARD_BASE_URL:
            setting.pasarguard_base_url = settings.PASARGUARD_BASE_URL
            updated_fields.append('pasarguard_base_url')
        if not setting.pasarguard_api_key and settings.PASARGUARD_API_KEY:
            setting.pasarguard_api_key = settings.PASARGUARD_API_KEY
            updated_fields.append('pasarguard_api_key')
        if setting.wallet_preset_amounts != PRESET_WALLET_AMOUNTS:
            setting.wallet_preset_amounts = PRESET_WALLET_AMOUNTS
            updated_fields.append('wallet_preset_amounts')
        if setting.support_username in ('Pomov2raySupport', '', None):
            setting.support_username = DEFAULT_SUPPORT_USERNAME
            updated_fields.append('support_username')
        for tut_field in ('tutorial_android_url', 'tutorial_ios_url', 'tutorial_windows_url'):
            if getattr(setting, tut_field, '') in ('https://t.me/Telegram', '', None):
                setattr(setting, tut_field, DEFAULT_CHANNEL_URL)
                updated_fields.append(tut_field)
        for stk_field, stk_file_id in DEFAULT_STICKERS.items():
            if not getattr(setting, stk_field, None):
                setattr(setting, stk_field, stk_file_id)
                updated_fields.append(stk_field)
        if updated_fields:
            setting.save(update_fields=updated_fields)

        live_map = fetch_template_name_to_id_map()
        direct_group_ids = resolve_default_group_ids_for_plan_type('direct')
        both_group_ids = resolve_default_group_ids_for_plan_type('both')

        ok_test, test_tpl_id, _ = create_or_update_user_template(
            name='Free Test',
            group_ids=both_group_ids,
            data_limit_bytes=100 * 1048576,
            expire_duration_seconds=max(1, setting.free_test_days) * 86400,
            status='on_hold',
            reset_usages=False,
            hwid_limit=0,
            method='chacha20-ietf-poly1305',
            template_id=live_map.get('Free Test'),
        )
        if ok_test and test_tpl_id:
            setting.free_test_template_id = test_tpl_id

        ok_ref3, ref3_tpl_id, _ = create_or_update_user_template(
            name='Referral Gift 10GB',
            group_ids=direct_group_ids,
            data_limit_bytes=10 * 1073741824,
            expire_duration_seconds=max(1, setting.referral_gift_days) * 86400,
            status='on_hold',
            reset_usages=False,
            hwid_limit=0,
            method='chacha20-ietf-poly1305',
            template_id=live_map.get('Referral Gift 10GB'),
        )
        if ok_ref3 and ref3_tpl_id:
            setting.referral_gift_template_id = ref3_tpl_id

        ok_ref10, ref10_tpl_id, _ = create_or_update_user_template(
            name='Referral Gift 30GB 7D',
            group_ids=direct_group_ids,
            data_limit_bytes=30 * 1073741824,
            expire_duration_seconds=max(1, setting.referral_milestone_10_days) * 86400,
            status='on_hold',
            reset_usages=False,
            hwid_limit=0,
            method='chacha20-ietf-poly1305',
            template_id=live_map.get('Referral Gift 30GB 7D'),
        )
        if ok_ref10 and ref10_tpl_id:
            setting.referral_milestone_10_template_id = ref10_tpl_id

        ok_ref20, ref20_tpl_id, _ = create_or_update_user_template(
            name='Referral Gift 100GB 30D',
            group_ids=direct_group_ids,
            data_limit_bytes=100 * 1073741824,
            expire_duration_seconds=max(1, setting.referral_milestone_20_days) * 86400,
            status='on_hold',
            reset_usages=False,
            hwid_limit=0,
            method='chacha20-ietf-poly1305',
            template_id=live_map.get('Referral Gift 100GB 30D'),
        )
        if ok_ref20 and ref20_tpl_id:
            setting.referral_milestone_20_template_id = ref20_tpl_id

        setting.save(
            update_fields=[
                'free_test_template_id',
                'referral_gift_template_id',
                'referral_milestone_10_template_id',
                'referral_milestone_20_template_id',
            ]
        )

        RequiredChannel.objects.filter(
            chat_id__in=['@AxonNegar', '@pomov2ray']
        ).update(
            chat_id='@pomo_vpn',
            title='📢 عضویت در کانال Pomo VPN',
            invite_link=DEFAULT_CHANNEL_URL,
        )
        if not RequiredChannel.objects.exists():
            RequiredChannel.objects.create(
                chat_id='@pomo_vpn',
                title='📢 عضویت در کانال Pomo VPN',
                invite_link=DEFAULT_CHANNEL_URL,
                is_active=True,
                sort_order=1,
            )

        default_plans = [
            {
                'plan_type': 'direct',
                'title': '⚡ ۱۰ گیگ دایرکت - ۱ ماهه (۴۹,۰۰۰ تومان)',
                'template_name': 'Direct 10GB 30D',
                'volume_gb': 10,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 49000,
                'sort_order': 1,
            },
            {
                'plan_type': 'direct',
                'title': '⚡ ۲۰ گیگ دایرکت - ۱ ماهه (۹۸,۰۰۰ تومان)',
                'template_name': 'Direct 20GB 30D',
                'volume_gb': 20,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 98000,
                'sort_order': 2,
            },
            {
                'plan_type': 'direct',
                'title': '⚡ ۳۰ گیگ دایرکت - ۱ ماهه (۱۴۸,۰۰۰ تومان)',
                'template_name': 'Direct 30GB 30D',
                'volume_gb': 30,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 148000,
                'sort_order': 3,
            },
            {
                'plan_type': 'direct',
                'title': '⚡ ۵۰ گیگ دایرکت - ۱ ماهه (۲۳۸,۰۰۰ تومان)',
                'template_name': 'Direct 50GB 30D',
                'volume_gb': 50,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 238000,
                'sort_order': 4,
            },
            {
                'plan_type': 'direct',
                'title': '♾ نامحدود دایرکت ۱ ماهه - ۲ کاربره (۳۱۹,۰۰۰ تومان)',
                'template_name': 'Direct Unlim 2U',
                'volume_gb': 0,
                'duration_days': 30,
                'max_users': 2,
                'hwid_limit': 2,
                'price': 319000,
                'sort_order': 5,
            },
            {
                'plan_type': 'direct',
                'title': '♾ نامحدود دایرکت ۱ ماهه - ۳ کاربره (۳۹۸,۰۰۰ تومان)',
                'template_name': 'Direct Unlim 3U',
                'volume_gb': 0,
                'duration_days': 30,
                'max_users': 3,
                'hwid_limit': 3,
                'price': 398000,
                'sort_order': 6,
            },
            {
                'plan_type': 'tunnel',
                'title': '🛡 ۱۰ گیگ تانل - ۱ ماهه (۸۹,۰۰۰ تومان)',
                'template_name': 'Tunnel 10GB 30D',
                'volume_gb': 10,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 89000,
                'sort_order': 1,
            },
            {
                'plan_type': 'tunnel',
                'title': '🛡 ۲۰ گیگ تانل - ۱ ماهه (۱۷۸,۰۰۰ تومان)',
                'template_name': 'Tunnel 20GB 30D',
                'volume_gb': 20,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 178000,
                'sort_order': 2,
            },
            {
                'plan_type': 'tunnel',
                'title': '🛡 ۳۰ گیگ تانل - ۱ ماهه (۲۶۸,۰۰۰ تومان)',
                'template_name': 'Tunnel 30GB 30D',
                'volume_gb': 30,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 268000,
                'sort_order': 3,
            },
            {
                'plan_type': 'tunnel',
                'title': '🛡 ۵۰ گیگ تانل - ۱ ماهه (۴۳۹,۰۰۰ تومان)',
                'template_name': 'Tunnel 50GB 30D',
                'volume_gb': 50,
                'duration_days': 30,
                'max_users': 0,
                'hwid_limit': 0,
                'price': 439000,
                'sort_order': 4,
            },
        ]

        obsolete_titles = [
            '⚡ ۳۰ گیگ دایرکت - ۱ ماهه (۱۰۰,۰۰۰ تومان)',
            '⚡ ۳۰ گیگ دایرکت - ۱ ماهه (۱۵۰,۰۰۰ تومان)',
            '⚡ ۶۰ گیگ دایرکت - ۱ ماهه (۱۸۰,۰۰۰ تومان)',
            '⚡ ۱۲۰ گیگ دایرکت - ۲ ماهه (۳۰۰,۰۰۰ تومان)',
            '♾ نامحدود دایرکت ۱ ماهه - ۲ کاربره (۳۲۰,۰۰۰ تومان)',
            '♾ نامحدود دایرکت ۱ ماهه - ۳ کاربره (۳۹۰,۰۰۰ تومان)',
            '🛡 ۳۰ گیگ تانل - ۱ ماهه (۱۲۰,۰۰۰ تومان)',
            '🛡 ۶۰ گیگ تانل - ۱ ماهه (۲۱۰,۰۰۰ تومان)',
        ]
        Plan.objects.filter(title__in=obsolete_titles).delete()

        for p in default_plans:
            target_groups = (
                direct_group_ids
                if p['plan_type'] == 'direct'
                else both_group_ids
            )
            existing_tpl_id = live_map.get(p['template_name'])
            ok, tpl_id, _ = create_or_update_user_template(
                name=p['template_name'],
                group_ids=target_groups,
                data_limit_bytes=p['volume_gb'] * 1073741824,
                expire_duration_seconds=p['duration_days'] * 86400,
                status='on_hold',
                reset_usages=False,
                hwid_limit=p['hwid_limit'],
                method='chacha20-ietf-poly1305',
                template_id=existing_tpl_id,
            )
            resolved_tpl_id = tpl_id if (ok and tpl_id) else existing_tpl_id
            if resolved_tpl_id:
                live_map[p['template_name']] = resolved_tpl_id

            query = Q(title=p['title'])
            if resolved_tpl_id:
                query |= Q(pasarguard_template_id=resolved_tpl_id)

            plan_obj = Plan.objects.filter(query).first()
            if not plan_obj:
                Plan.objects.create(
                    title=p['title'],
                    plan_type=p['plan_type'],
                    pasarguard_template_id=resolved_tpl_id,
                    volume_gb=p['volume_gb'],
                    duration_days=p['duration_days'],
                    max_users=p['max_users'],
                    price=p['price'],
                    sort_order=p['sort_order'],
                    is_active=True,
                )
            else:
                plan_obj.title = p['title']
                plan_obj.plan_type = p['plan_type']
                plan_obj.pasarguard_template_id = resolved_tpl_id
                plan_obj.volume_gb = p['volume_gb']
                plan_obj.duration_days = p['duration_days']
                plan_obj.max_users = p['max_users']
                plan_obj.price = p['price']
                plan_obj.sort_order = p['sort_order']
                plan_obj.save()

        self.stdout.write(
            self.style.SUCCESS(
                "Default settings, stickers, PasarGuard templates, and the 10 plans synced successfully."
            )
        )