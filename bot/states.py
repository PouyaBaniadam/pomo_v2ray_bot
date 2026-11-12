from aiogram.fsm.state import (
    State,
    StatesGroup,
)


class SupportState(StatesGroup):
    waiting_for_message = State()


class WalletChargeState(StatesGroup):
    selecting_amount = State()
    entering_custom_amount = State()
    uploading_receipt = State()


class BuyServiceState(StatesGroup):
    selecting_category = State()
    selecting_plan = State()
    entering_custom_name = State()
    confirming_purchase = State()


class AdminState(StatesGroup):
    waiting_for_config_link = State()
    waiting_for_broadcast_message = State()
    waiting_for_ticket_reply = State()