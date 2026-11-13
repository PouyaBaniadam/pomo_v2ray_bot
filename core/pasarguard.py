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


def fetch_pasarguard_templates_list() -> list[dict]:
    base_url, api_key, verify_ssl = get_pasarguard_Runtime_credentials()
    if not base_url or not api_key:
        return []

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
                return [
                    item
                    for item in items
                    if isinstance(item, dict) and "id" in item and "name" in item
                ]
        except Exception:
            continue
    return []


def fetch_template_name_to_id_map() -> dict[str, int]:
    templates = fetch_pasarguard_templates_list()
    return {
        str(item["name"]).strip(): int(item["id"])
        for item in templates
    }


def fetch_pasarguard_groups() -> list[dict]:
    base_url, api_key, verify_ssl = get_pasarguard_Runtime_credentials()
    if not base_url or not api_key:
        return []

    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }
    for endpoint in (
        "/api/groups",
        "/api/group",
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
                    else data.get("groups") or data.get("items") or []
                )
                parsed = [
                    {
                        "id": int(g["id"]),
                        "name": str(g.get("name") or f"Group #{g['id']}").strip(),
                    }
                    for g in items
                    if isinstance(g, dict) and "id" in g
                ]
                if parsed:
                    return parsed
        except Exception:
            continue

    templates = fetch_pasarguard_templates_list()
    inferred_groups: dict[int, str] = {}
    for tpl in templates:
        t_name = str(tpl.get("name") or "").lower()
        g_ids = tpl.get("group_ids") or []
        for gid in g_ids:
            try:
                gid_int = int(gid)
            except (ValueError, TypeError):
                continue
            if gid_int not in inferred_groups:
                if "tunnel" in t_name:
                    inferred_groups[gid_int] = "Reis tunnel"
                elif "direct" in t_name:
                    inferred_groups[gid_int] = "Reis Group"
                else:
                    inferred_groups[gid_int] = f"Group #{gid_int}"

    if inferred_groups:
        return [
            {"id": gid, "name": gname}
            for gid, gname in sorted(inferred_groups.items())
        ]

    return [
        {"id": 1, "name": "Reis Group"},
        {"id": 2, "name": "Reis tunnel"},
    ]


def resolve_default_group_ids_for_plan_type(
    plan_type: str,
) -> list[int]:
    groups = fetch_pasarguard_groups()
    if not groups:
        return [1]

    target_keyword = "tunnel" if plan_type == "tunnel" else "group"
    for g in groups:
        g_name_lower = g["name"].lower()
        if plan_type == "tunnel" and "tunnel" in g_name_lower:
            return [g["id"]]
        if plan_type == "direct" and "tunnel" not in g_name_lower and (
            "group" in g_name_lower or "direct" in g_name_lower or "reis" in g_name_lower
        ):
            return [g["id"]]

    return [groups[0]["id"]]


def create_or_update_user_template(
    name: str,
    group_ids: list[int],
    data_limit_bytes: int = 0,
    expire_duration_seconds: int = 0,
    status: str = "active",
    on_hold_timeout_seconds: int | None = None,
    data_limit_reset_strategy: str = "no_reset",
    reset_usages: bool = False,
    hwid_limit: int | None = None,
    username_prefix: str | None = None,
    username_suffix: str | None = None,
    method: str = "chacha20-ietf-poly1305",
    flow: str | None = None,
    is_disabled: bool = False,
    template_id: int | None = None,
) -> tuple[bool, int | None, str | None]:
    base_url, api_key, verify_ssl = get_pasarguard_Runtime_credentials()
    if not base_url or not api_key:
        return (
            False,
            None,
            "PasarGuard base URL or API key is not configured.",
        )

    clean_name = (name or "").strip()[:64]
    if not clean_name:
        return (
            False,
            None,
            "Template name cannot be empty.",
        )

    valid_groups = [int(g) for g in (group_ids or []) if str(g).isdigit()]
    if not valid_groups:
        valid_groups = resolve_default_group_ids_for_plan_type("direct")

    extra_settings = {}
    if method:
        extra_settings["method"] = method
    if flow and flow != "none":
        extra_settings["flow"] = flow

    payload = {
        "name": clean_name,
        "group_ids": valid_groups,
        "data_limit": max(0, int(data_limit_bytes or 0)),
        "expire_duration": max(0, int(expire_duration_seconds or 0)),
        "status": status if status in ("active", "on_hold") else "active",
        "data_limit_reset_strategy": data_limit_reset_strategy or "no_reset",
        "reset_usages": bool(reset_usages),
        "is_disabled": bool(is_disabled),
        "username_prefix": (username_prefix or "").strip()[:20] or None,
        "username_suffix": (username_suffix or "").strip()[:20] or None,
        "extra_settings": extra_settings if extra_settings else None,
    }

    if hwid_limit is not None and str(hwid_limit).strip() != "":
        payload["hwid_limit"] = max(0, int(hwid_limit))

    if payload["status"] == "on_hold" and payload["expire_duration"] > 0:
        payload["on_hold_timeout"] = max(
            60,
            int(on_hold_timeout_seconds or 3600),
        )

    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    existing_map = fetch_template_name_to_id_map()
    target_id = template_id or existing_map.get(clean_name)

    try:
        if target_id:
            for endpoint in (
                f"/api/user_template/{int(target_id)}",
                f"/api/user_templates/{int(target_id)}",
            ):
                resp = requests.put(
                    f"{base_url}{endpoint}",
                    json=payload,
                    headers=headers,
                    timeout=12,
                    verify=verify_ssl,
                    proxies=get_requests_proxies(),
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    ret_id = int(data.get("id") or target_id)
                    return True, ret_id, None
                if resp.status_code not in (404, 405):
                    return (
                        False,
                        int(target_id),
                        f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

        for endpoint in (
            "/api/user_template",
            "/api/user_templates",
        ):
            resp = requests.post(
                f"{base_url}{endpoint}",
                json=payload,
                headers=headers,
                timeout=12,
                verify=verify_ssl,
                proxies=get_requests_proxies(),
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                created_id = data.get("id")
                if not created_id:
                    refreshed_map = fetch_template_name_to_id_map()
                    created_id = refreshed_map.get(clean_name)
                return (
                    True,
                    int(created_id) if created_id else None,
                    None,
                )
            if resp.status_code not in (404, 405):
                return (
                    False,
                    None,
                    f"HTTP {resp.status_code}: {resp.text[:200]}",
                )

        return (
            False,
            None,
            "PasarGuard template endpoint was not found.",
        )
    except requests.RequestException as exc:
        logger.exception(f"PasarGuard template creation failed: {exc}")
        return (
            False,
            None,
            f"Connection error: {exc}",
        )