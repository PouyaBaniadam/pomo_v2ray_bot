from urllib.parse import quote
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CopyTextButton,
)

BTN_FREE_TEST_PREFIX = "🎁 دریافت تست رایگان"
BTN_FREE_TEST = "🎁 دریافت تست رایگان"
BTN_BUY_SERVICE = "🛒 خرید سرویس"
BTN_MY_SERVICES = "🔍 سرویس (های) من"
BTN_CHARGE_WALLET = "💳 افزایش موجودی"
BTN_USER_ACCOUNT = "👤 حساب کاربری"
BTN_REFERRAL_GIFT = "🎉 اشتراک رایگان (دعوت دوستان)"
BTN_SUPPORT = "💬 تیکت پشتیبانی"
BTN_TUTORIALS = "📚 آموزش اتصال"
BTN_CANCEL_ACTION = "انصراف و بازگشت 🔙"

MAIN_MENU_BUTTONS = {
    BTN_FREE_TEST,
    BTN_BUY_SERVICE,
    BTN_MY_SERVICES,
    BTN_CHARGE_WALLET,
    BTN_USER_ACCOUNT,
    BTN_REFERRAL_GIFT,
    BTN_SUPPORT,
    BTN_TUTORIALS,
}


def make_reply_btn(
    text: str,
    style: str | None = None,
    **kwargs,
) -> KeyboardButton:
    if style:
        try:
            return KeyboardButton(
                text=text,
                style=style,
                **kwargs,
            )
        except Exception:
            pass
    return KeyboardButton(
        text=text,
        **kwargs,
    )


def make_inline_btn(
    text: str,
    style: str | None = None,
    **kwargs,
) -> InlineKeyboardButton:
    if style:
        try:
            return InlineKeyboardButton(
                text=text,
                style=style,
                **kwargs,
            )
        except Exception:
            pass
    return InlineKeyboardButton(
        text=text,
        **kwargs,
    )


def is_main_menu_button(
    text: str,
) -> bool:
    if not text:
        return False
    return text in MAIN_MENU_BUTTONS or text.startswith(BTN_FREE_TEST_PREFIX)


def get_main_menu_keyboard(
    show_free_test: bool = True,
    free_test_title: str = None,
) -> ReplyKeyboardMarkup:
    rows = []
    if show_free_test:
        btn_label = (
            f"{BTN_FREE_TEST_PREFIX} ({free_test_title})"
            if free_test_title
            else BTN_FREE_TEST_PREFIX
        )
        rows.append(
            [
                make_reply_btn(
                    text=btn_label,
                    style="green",
                )
            ]
        )
    rows.extend(
        [
            [
                make_reply_btn(
                    text=BTN_BUY_SERVICE,
                    style="green",
                ),
                make_reply_btn(
                    text=BTN_MY_SERVICES,
                    style="blue",
                ),
            ],
            [
                make_reply_btn(
                    text=BTN_CHARGE_WALLET,
                    style="blue",
                ),
                make_reply_btn(
                    text=BTN_USER_ACCOUNT,
                    style="blue",
                ),
            ],
            [
                make_reply_btn(
                    text=BTN_REFERRAL_GIFT,
                    style="green",
                )
            ],
            [
                make_reply_btn(
                    text=BTN_SUPPORT,
                    style="red",
                ),
                make_reply_btn(
                    text=BTN_TUTORIALS,
                    style="blue",
                ),
            ],
        ]
    )
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def get_cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                make_reply_btn(
                    text=BTN_CANCEL_ACTION,
                    style="red",
                )
            ]
        ],
        resize_keyboard=True,
    )


def get_user_account_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="افزایش موجودی 💳",
                    callback_data="acc_charge_wallet",
                    style="green",
                ),
                make_inline_btn(
                    text="🧾 پرداخت‌های من",
                    callback_data="acc_my_payments",
                    style="blue",
                ),
            ]
        ]
    )


def get_tutorials_inline_kb(
    android_url: str,
    ios_url: str,
    windows_url: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="📱 آموزش اندروید (Android)",
                    url=android_url,
                    style="green",
                ),
                make_inline_btn(
                    text="🍏 آموزش آیفون (iOS)",
                    url=ios_url,
                    style="blue",
                ),
            ],
            [
                make_inline_btn(
                    text="💻 آموزش ویندوز (Windows)",
                    url=windows_url,
                    style="blue",
                ),
            ],
        ]
    )


def get_support_inline_kb(
    support_username: str,
) -> InlineKeyboardMarkup:
    clean_username = support_username.lstrip('@')
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="👨‍💻 ارتباط مستقیم با پشتیبان",
                    url=f"https://t.me/{clean_username}",
                    style="blue",
                )
            ],
            [
                make_inline_btn(
                    text="✍️ ثبت تیکت در ربات",
                    callback_data="open_support_ticket",
                    style="green",
                )
            ],
        ]
    )


def get_wallet_preset_amounts_kb(
    prices: list[int],
) -> InlineKeyboardMarkup:
    rows = []
    current_row = []
    for p in prices:
        current_row.append(
            make_inline_btn(
                text=f"{p:,} تومان",
                callback_data=f"charge_amt:{p}",
                style="blue",
            )
        )
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    rows.append(
        [
            make_inline_btn(
                text="مبلغ دلخواه ✏️",
                callback_data="charge_amt:custom",
                style="green",
            ),
            make_inline_btn(
                text="بازگشت 🔙",
                callback_data="cancel_wallet_flow",
                style="red",
            ),
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )


def get_invoice_cancel_kb(
    invoice_number: str,
    card_number: str,
    amount: int,
) -> InlineKeyboardMarkup:
    clean_card = card_number.replace("-", "").replace(" ", "")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="💳 کپی شماره کارت",
                    copy_text=CopyTextButton(
                        text=clean_card,
                    ),
                    style="blue",
                ),
                make_inline_btn(
                    text="💰 کپی مبلغ",
                    copy_text=CopyTextButton(
                        text=str(amount),
                    ),
                    style="blue",
                ),
            ],
            [
                make_inline_btn(
                    text="❌ لغو فاکتور",
                    callback_data=f"cancel_inv:{invoice_number}",
                    style="red",
                )
            ],
        ]
    )


def get_admin_receipt_approval_kb(
    tx_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="✅ تایید و شارژ کیف پول",
                    callback_data=f"adm_appr_tx:{tx_id}",
                    style="green",
                ),
                make_inline_btn(
                    text="❌ رد رسید",
                    callback_data=f"adm_rejc_tx:{tx_id}",
                    style="red",
                ),
            ]
        ]
    )


def get_buy_category_kb(
    direct_title: str = "⚡ حجمی دایرکت",
    tunnel_title: str = "🛡 حجمی تانل",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text=direct_title,
                    callback_data="buy_cat:direct",
                    style="green",
                ),
            ],
            [
                make_inline_btn(
                    text=tunnel_title,
                    callback_data="buy_cat:tunnel",
                    style="blue",
                ),
            ],
            [
                make_inline_btn(
                    text="🔙 انصراف",
                    callback_data="cancel_buy_flow",
                    style="red",
                ),
            ],
        ]
    )


def get_plans_list_kb(
    plans,
    category: str,
) -> InlineKeyboardMarkup:
    keyboard = []
    btn_style = "green" if category == "direct" else "blue"
    for p in plans:
        keyboard.append(
            [
                make_inline_btn(
                    text=f"{p.title}",
                    callback_data=f"select_plan:{p.id}",
                    style=btn_style,
                )
            ]
        )
    keyboard.append(
        [
            make_inline_btn(
                text="🔙 بازگشت به دسته‌بندی",
                callback_data="back_to_categories",
                style="red",
            )
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=keyboard,
    )


def get_service_naming_kb(
    default_name: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="کنسل کن 🔙",
                    callback_data="back_to_categories",
                    style="red",
                ),
                make_inline_btn(
                    text="پیش‌فرض ✏️",
                    callback_data=f"set_sname:{default_name}",
                    style="green",
                ),
            ]
        ]
    )


def get_confirm_purchase_kb(
    plan_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="بازگشت 🔙",
                    callback_data="back_to_categories",
                    style="red",
                ),
                make_inline_btn(
                    text="تایید و پرداخت ✅",
                    callback_data=f"do_purchase:{plan_id}",
                    style="green",
                ),
            ]
        ]
    )


def get_insufficient_balance_kb(
    deficit: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text=f"💳 افزایش مستقیم کسری ({deficit:,} تومان)",
                    callback_data=f"charge_amt:{deficit}",
                    style="green",
                )
            ],
            [
                make_inline_btn(
                    text="🔙 بازگشت به منوی اصلی",
                    callback_data="cancel_buy_flow",
                    style="red",
                )
            ],
        ]
    )


def get_referral_inline_kb(
    invite_link: str,
    share_text: str = "تجربه یک اتصال باکیفیت و بدون محدودیت!",
) -> InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={quote(invite_link)}&text={quote(share_text)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="ارسال لینک به دوستان ↪️",
                    url=share_url,
                    style="green",
                ),
            ],
            [
                make_inline_btn(
                    text="👥 دعوت‌های من",
                    callback_data="my_referrals_list",
                    style="blue",
                ),
                make_inline_btn(
                    text="📋 کپی لینک دعوت",
                    copy_text=CopyTextButton(
                        text=invite_link,
                    ),
                    style="blue",
                ),
            ],
            [
                make_inline_btn(
                    text="🛒 خرید سرویس",
                    callback_data="go_to_buy_from_empty",
                    style="green",
                ),
            ],
        ]
    )


def get_admin_send_config_kb(
    order_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="🔗 ثبت و ارسال سریع لینک کانفیگ",
                    callback_data=f"adm_set_cfg:{order_id}",
                    style="green",
                )
            ]
        ]
    )


def get_admin_reply_ticket_kb(
    ticket_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="✍️ پاسخ سریع به تیکت",
                    callback_data=f"adm_rep_tkt:{ticket_id}",
                    style="blue",
                )
            ]
        ]
    )


def get_admin_sticker_assign_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="🏆 استیکر خوش‌آمدگویی",
                    callback_data="set_stk:sticker_welcome",
                    style="green",
                ),
                make_inline_btn(
                    text="👤 استیکر حساب کاربری",
                    callback_data="set_stk:sticker_account",
                    style="blue",
                ),
            ],
            [
                make_inline_btn(
                    text="🛒 استیکر خرید سرویس",
                    callback_data="set_stk:sticker_buy",
                    style="green",
                ),
                make_inline_btn(
                    text="💳 استیکر کیف پول / رفرال",
                    callback_data="set_stk:sticker_wallet",
                    style="blue",
                ),
            ],
            [
                make_inline_btn(
                    text="🔍 استیکر سرویس خالی",
                    callback_data="set_stk:sticker_empty",
                    style="red",
                ),
            ],
        ]
    )


def get_service_actions_kb(
    order_id: int,
    config_link: str,
) -> InlineKeyboardMarkup:
    rows = []
    clean_link = config_link.strip()
    if 0 < len(clean_link) <= 256:
        rows.append(
            [
                make_inline_btn(
                    text="📋 کپی لینک کانفیگ",
                    copy_text=CopyTextButton(
                        text=clean_link,
                    ),
                    style="blue",
                ),
                make_inline_btn(
                    text="📷 دریافت QR Code",
                    callback_data=f"get_qr:{order_id}",
                    style="green",
                ),
            ]
        )
    else:
        rows.append(
            [
                make_inline_btn(
                    text="📷 دریافت QR Code",
                    callback_data=f"get_qr:{order_id}",
                    style="green",
                )
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )


def get_admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="📦 سفارش‌های منتظر لینک",
                    callback_data="adm_pending_orders",
                    style="blue",
                ),
                make_inline_btn(
                    text="📢 ارسال پیام همگانی",
                    callback_data="adm_broadcast",
                    style="green",
                ),
            ],
            [
                make_inline_btn(
                    text="🔄 بروزرسانی آمار",
                    callback_data="adm_refresh_stats",
                    style="blue",
                ),
            ],
        ]
    )


def get_force_join_kb(
    channels: list,
) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        rows.append(
            [
                make_inline_btn(
                    text=ch.title,
                    url=ch.invite_link,
                    style="blue",
                )
            ]
        )
    rows.append(
        [
            make_inline_btn(
                text="✅ عضو شدم (بررسی و ادامه)",
                callback_data="verify_join",
                style="green",
            )
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )