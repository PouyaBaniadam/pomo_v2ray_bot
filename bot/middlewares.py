from collections import (
    defaultdict,
    deque,
)
import logging
import time
from typing import (
    Callable,
    Dict,
    Any,
    Awaitable,
)
from aiogram import (
    BaseMiddleware,
    Bot,
)
from aiogram.types import (
    Message,
    CallbackQuery,
    TelegramObject,
)
from aiogram.enums import ChatMemberStatus
from bot.keyboards import (
    is_main_menu_button,
    get_force_join_kb,
)
from core.services import (
    upsert_telegram_user,
    get_active_required_channels,
    get_all_admin_ids,
    get_rate_limit_runtime_config,
)

logger = logging.getLogger(__name__)

PENDING_USER_EVENTS: Dict[int, TelegramObject] = {}
USER_REQUEST_TIMESTAMPS: Dict[int, deque] = defaultdict(deque)
USER_RATE_LIMIT_WARNED_UNTIL: Dict[int, float] = {}
RECEIPT_UPLOAD_COOLDOWN: Dict[int, float] = {}

_RATE_LIMIT_CACHE = {
    "updated_at": 0.0,
    "limit_per_minute": 25,
    "admin_ids": set(),
}

VALID_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


async def get_cached_rate_limit_config() -> tuple[int, set[int]]:
    now = time.monotonic()
    if now - _RATE_LIMIT_CACHE["updated_at"] > 15.0:
        limit, admin_ids = await get_rate_limit_runtime_config()
        _RATE_LIMIT_CACHE["limit_per_minute"] = limit
        _RATE_LIMIT_CACHE["admin_ids"] = admin_ids
        _RATE_LIMIT_CACHE["updated_at"] = now
    return (
        _RATE_LIMIT_CACHE["limit_per_minute"],
        _RATE_LIMIT_CACHE["admin_ids"],
    )


def check_receipt_upload_cooldown(
    user_id: int,
    cooldown_seconds: float = 5.0,
) -> float:
    now = time.monotonic()
    last_attempt = RECEIPT_UPLOAD_COOLDOWN.get(user_id, 0.0)
    remaining = cooldown_seconds - (now - last_attempt)
    if remaining > 0:
        return remaining
    RECEIPT_UPLOAD_COOLDOWN[user_id] = now
    return 0.0


def normalize_channel_id(
    raw_id: str,
) -> str | int:
    val = raw_id.strip()
    if val.startswith("https://t.me/"):
        val = val.replace("https://t.me/", "").strip("/")
    elif val.startswith("http://t.me/"):
        val = val.replace("http://t.me/", "").strip("/")
    if val.lstrip("-").isdigit():
        return int(val)
    if not val.startswith("@"):
        return f"@{val}"
    return val


async def get_unjoined_channels(
    bot: Bot,
    user_id: int,
) -> list:
    admin_ids = await get_all_admin_ids()
    if user_id in admin_ids:
        return []

    channels = await get_active_required_channels()
    if not channels:
        return []

    unjoined = []
    for ch in channels:
        target_chat_id = normalize_channel_id(ch.chat_id)
        try:
            member = await bot.get_chat_member(
                chat_id=target_chat_id,
                user_id=user_id,
            )
            is_member = (
                member.status in VALID_MEMBER_STATUSES
                or (
                    member.status == ChatMemberStatus.RESTRICTED
                    and getattr(member, "is_member", False)
                )
            )
            if not is_member:
                unjoined.append(ch)
        except Exception as exc:
            logger.warning(
                f"Force-join check failed for channel {target_chat_id} (Ensure bot is admin): {exc}"
            )
            continue

    return unjoined


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if not tg_user or tg_user.is_bot:
            return await handler(
                event,
                data,
            )

        limit_per_minute, admin_ids = await get_cached_rate_limit_config()
        if tg_user.id in admin_ids:
            return await handler(
                event,
                data,
            )

        now = time.monotonic()
        window_seconds = 60.0
        history = USER_REQUEST_TIMESTAMPS[tg_user.id]

        while history and (now - history[0]) > window_seconds:
            history.popleft()

        if len(history) >= limit_per_minute:
            warned_until = USER_RATE_LIMIT_WARNED_UNTIL.get(tg_user.id, 0.0)
            if now >= warned_until:
                USER_RATE_LIMIT_WARNED_UNTIL[tg_user.id] = now + 15.0
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer(
                            "⏳ تعداد درخواست‌های شما بیش از حد مجاز است! لطفاً کمی صبر کنید.",
                            show_alert=True,
                        )
                    except Exception:
                        pass
                elif isinstance(event, Message):
                    try:
                        await event.answer(
                            "⏳ <b>تعداد درخواست‌های شما بیش از حد مجاز است!</b>\n"
                            "لطفاً چند ثانیه صبر کرده و مجدداً تلاش کنید.",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
            return None

        history.append(now)
        return await handler(
            event,
            data,
        )


class UserUpsertAndAntiLoopMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        bot: Bot = data.get("bot")

        if tg_user and not tg_user.is_bot:
            is_verify_callback = (
                isinstance(event, CallbackQuery)
                and event.data == "verify_join"
            )

            if bot and not is_verify_callback:
                unjoined_channels = await get_unjoined_channels(
                    bot=bot,
                    user_id=tg_user.id,
                )
                if unjoined_channels:
                    PENDING_USER_EVENTS[tg_user.id] = event

                    join_text = (
                        "🔒 <b>عضویت در کانال الزامی است!</b>\n\n"
                        "برای استفاده از ربات و ادامه عملیات قبلی خود، لطفاً ابتدا از طریق دکمه‌های زیر در کانال عضو شوید و سپس روی دکمه <b>«✅ عضو شدم»</b> کلیک کنید:"
                    )
                    kb = get_force_join_kb(unjoined_channels)

                    if isinstance(event, Message):
                        await event.answer(
                            join_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    elif isinstance(event, CallbackQuery) and event.message:
                        await event.answer(
                            "🔒 ابتدا در کانال عضو شوید!",
                            show_alert=True,
                        )
                        await event.message.answer(
                            join_text,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    return

            is_start_command = (
                isinstance(event, Message)
                and event.text
                and event.text.startswith("/start")
            )
            if not is_start_command:
                db_user, _ = await upsert_telegram_user(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    full_name=tg_user.full_name,
                )
                if db_user.is_banned:
                    if isinstance(event, Message):
                        await event.answer(
                            "⛔️ حساب کاربری شما در ربات مسدود شده است."
                        )
                    return
                data["db_user"] = db_user

        if isinstance(event, Message) and event.text:
            state = data.get("state")
            if state and (
                is_main_menu_button(event.text) or event.text.startswith("/start")
            ):
                await state.clear()

        return await handler(
            event,
            data,
        )