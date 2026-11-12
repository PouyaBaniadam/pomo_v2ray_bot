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
                    style="success",
                )
            ]
        )
    rows.extend(
        [
            [
                make_reply_btn(
                    text=BTN_BUY_SERVICE,
                    style="success",
                ),
                make_reply_btn(
                    text=BTN_MY_SERVICES,
                    style="primary",
                ),
            ],
            [
                make_reply_btn(
                    text=BTN_CHARGE_WALLET,
                    style="primary",
                ),
                make_reply_btn(
                    text=BTN_USER_ACCOUNT,
                    style="primary",
                ),
            ],
            [
                make_reply_btn(
                    text=BTN_REFERRAL_GIFT,
                    style="success",
                )
            ],
            [
                make_reply_btn(
                    text=BTN_SUPPORT,
                    style="danger",
                ),
                make_reply_btn(
                    text=BTN_TUTORIALS,
                    style="primary",
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
                    style="danger",
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
                    style="success",
                ),
                make_inline_btn(
                    text="🧾 پرداخت‌های من",
                    callback_data="acc_my_payments",
                    style="primary",
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
                    style="success",
                ),
                make_inline_btn(
                    text="🍏 آموزش آیفون (iOS)",
                    url=ios_url,
                    style="primary",
                ),
            ],
            [
                make_inline_btn(
                    text="💻 آموزش ویندوز (Windows)",
                    url=windows_url,
                    style="primary",
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
                    style="primary",
                )
            ],
            [
                make_inline_btn(
                    text="✍️ ثبت تیکت در ربات",
                    callback_data="open_support_ticket",
                    style="success",
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
                style="primary",
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
                style="success",
            ),
            make_inline_btn(
                text="بازگشت 🔙",
                callback_data="cancel_wallet_flow",
                style="danger",
            ),
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )


def get_wallet_custom_amount_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_inline_btn(
                    text="🔙 بازگشت به مبالغ",
                    callback_data="back_to_wallet_amounts",
                    style="primary",
                ),
                make_inline_btn(
                    text="❌ انصراف",
                    callback_data="cancel_wallet_flow",
                    style="danger",
                ),
            ]
        ]
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
                    style="primary",
                ),
                make_inline_btn(
                    text="💰 کپی مبلغ",
                    copy_text=CopyTextButton(
                        text=str(amount),
                    ),
                    style="primary",
                ),
            ],
            [
                make_inline_btn(
                    text="❌ لغو فاکتور",
                    callback_data=f"cancel_inv:{invoice_number}",
                    style="danger",
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
                    style="success",
                ),
                make_inline_btn(
                    text="❌ رد رسید",
                    callback_data=f"adm_rejc_tx:{tx_id}",
                    style="danger",
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
                    style="success",
                ),
            ],
            [
                make_inline_btn(
                    text=tunnel_title,
                    callback_data="buy_cat:tunnel",
                    style="primary",
                ),
            ],
            [
                make_inline_btn(
                    text="🔙 انصراف",
                    callback_data="cancel_buy_flow",
                    style="danger",
                ),
            ],
        ]
    )


def get_plans_list_kb(
    plans,
    category: str,
) -> InlineKeyboardMarkup:
    keyboard = []
    btn_style = "success" if category == "direct" else "primary"
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
                style="danger",
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
                    style="danger",
                ),
                make_inline_btn(
                    text="پیش‌فرض ✏️",
                    callback_data=f"set_sname:{default_name}",
                    style="success",
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
                    style="danger",
                ),
                make_inline_btn(
                    text="تایید و پرداخت ✅",
                    callback_data=f"do_purchase:{plan_id}",
                    style="success",
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
                    style="success",
                )
            ],
            [
                make_inline_btn(
                    text="🔙 بازگشت به منوی اصلی",
                    callback_data="cancel_buy_flow",
                    style="danger",
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
                    style="success",
                ),
            ],
            [
                make_inline_btn(
                    text="👥 دعوت‌های من",
                    callback_data="my_referrals_list",
                    style="primary",
                ),
                make_inline_btn(
                    text="📋 کپی لینک دعوت",
                    copy_text=CopyTextButton(
                        text=invite_link,
                    ),
                    style="primary",
                ),
            ],
            [
                make_inline_btn(
                    text="🛒 خرید سرویس",
                    callback_data="go_to_buy_from_empty",
                    style="success",
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
                    style="success",
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
                    style="primary",
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
                    style="success",
                ),
                make_inline_btn(
                    text="👤 استیکر حساب کاربری",
                    callback_data="set_stk:sticker_account",
                    style="primary",
                ),
            ],
            [
                make_inline_btn(
                    text="🛒 استیکر خرید سرویس",
                    callback_data="set_stk:sticker_buy",
                    style="success",
                ),
                make_inline_btn(
                    text="💳 استیکر کیف پول / رفرال",
                    callback_data="set_stk:sticker_wallet",
                    style="primary",
                ),
            ],
            [
                make_inline_btn(
                    text="🔍 استیکر سرویس خالی",
                    callback_data="set_stk:sticker_empty",
                    style="danger",
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
                    style="primary",
                ),
                make_inline_btn(
                    text="📷 دریافت QR Code",
                    callback_data=f"get_qr:{order_id}",
                    style="success",
                ),
            ]
        )
    else:
        rows.append(
            [
                make_inline_btn(
                    text="📷 دریافت QR Code",
                    callback_data=f"get_qr:{order_id}",
                    style="success",
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
                    style="primary",
                ),
                make_inline_btn(
                    text="📢 ارسال پیام همگانی",
                    callback_data="adm_broadcast",
                    style="success",
                ),
            ],
            [
                make_inline_btn(
                    text="🔄 بروزرسانی آمار",
                    callback_data="adm_refresh_stats",
                    style="primary",
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
                    style="primary",
                )
            ]
        )
    rows.append(
        [
            make_inline_btn(
                text="✅ عضو شدم (بررسی و ادامه)",
                callback_data="verify_join",
                style="success",
            )
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )