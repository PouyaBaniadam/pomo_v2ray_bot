import logging
import re
import secrets
import string
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def get_requests_proxies():
    if getattr(settings, 'PROXY_URL', ''):
        return {
            "http": settings.PROXY_URL,
            "https": settings.PROXY_URL,
        }
    return None


def get_pasarguard_Runtime_credentials() -> tuple[str, str, bool]:
    """
    Fetch PasarGuard credentials from BotSetting (DB) with fallback to .env settings.
    """
    from core.models import BotSetting

    base_url = settings.PASARGUARD_BASE_URL
    api_key = settings.PASARGUARD_API_KEY
    verify_ssl = settings.PASARGUARD_VERIFY_SSL

    try:
        bot_setting = BotSetting.objects.filter(id=1).first()
        if bot_setting:
            if bot_setting.pasarguard_base_url:
                base_url = bot_setting.pasarguard_base_url.strip().rstrip('/')
            if bot_setting.pasarguard_api_key:
                api_key = bot_setting.pasarguard_api_key.strip()
            verify_ssl = bot_setting.pasarguard_verify_ssl
    except Exception:
        pass

    return (
        base_url,
        api_key,
        verify_ssl,
    )


def build_unique_panel_username(
    base_name: str,
) -> str:
    """
    Build a unique username complying with PasarGuard validation rules:
    3-128 chars, alphanumeric/underscore, no consecutive underscores.
    """
    clean = re.sub(
        r'[^a-zA-Z0-9_]',
        '',
        base_name or 'user',
    )
    clean = re.sub(
        r'_+',
        '_',
        clean,
    ).strip('_')
    if len(clean) < 3:
        clean = f"usr{clean}"
    clean = clean[:20].rstrip('_')

    alphabet = string.ascii_lowercase + string.digits
    suffix = ''.join(
        secrets.choice(alphabet) for _ in range(4)
    )
    return f"{clean}_{suffix}"


def create_user_from_template(
    template_id: int,
    base_username: str,
    note: str = "",
) -> tuple[bool, str | None, str | None, str | None]:
    """
    Create a user on PasarGuard panel using a User Template ID.
    Returns: (success, subscription_url, panel_username, error_message)
    """
    base_url, api_key, verify_ssl = get_pasarguard_Runtime_credentials()

    if not base_url or not api_key:
        return (
            False,
            None,
            None,
            "PasarGuard base URL or API key is not configured.",
        )

    if not template_id:
        return (
            False,
            None,
            None,
            "PasarGuard Template ID is not set for this plan.",
        )

    panel_username = build_unique_panel_username(base_username)
    url = f"{base_url}/api/user/from_template"
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "user_template_id": int(template_id),
        "username": panel_username,
        "note": note[:250] if note else "",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=12,
            verify=verify_ssl,
            proxies=get_requests_proxies(),
        )
        if response.status_code in (200, 201):
            data = response.json()
            created_username = data.get("username") or panel_username

            sub_url = data.get("subscription_url") or ""
            if sub_url and sub_url.startswith("/"):
                sub_url = f"{base_url}{sub_url}"
            elif not sub_url and data.get("token"):
                sub_url = f"{base_url}/sub/{data['token']}"

            if sub_url:
                return (
                    True,
                    sub_url,
                    created_username,
                    None,
                )
            return (
                False,
                None,
                created_username,
                "User created on panel, but subscription_url was missing in response.",
            )

        logger.error(
            f"PasarGuard API Error ({response.status_code}): {response.text}"
        )
        return (
            False,
            None,
            None,
            f"Panel HTTP {response.status_code}: {response.text[:150]}",
        )
    except requests.RequestException as exc:
        logger.exception(f"PasarGuard connection failed: {exc}")
        return (
            False,
            None,
            None,
            f"Connection error: {exc}",
        )


def fetch_template_name_to_id_map() -> dict[str, int]:
    """
    Fetch available User Templates from PasarGuard to map template names to IDs.
    """
    base_url, api_key, verify_ssl = get_pasarguard_Runtime_credentials()
    if not base_url or not api_key:
        return {}

    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }
    for endpoint in (
        "/api/user_templates",
        "/api/user_template",
    ):
        try:
            resp = requests.get(
                f"{base_url}{endpoint}",
                headers=headers,
                timeout=10,
                verify=verify_ssl,
                proxies=get_requests_proxies(),
            )
            if resp.status_code == 200:
                data = resp.json()
                items = (
                    data
                    if isinstance(data, list)
                    else data.get("templates") or data.get("items") or []
                )
                return {
                    item["name"].strip(): int(item["id"])
                    for item in items
                    if isinstance(item, dict) and "name" in item and "id" in item
                }
        except Exception:
            continue
    return {}