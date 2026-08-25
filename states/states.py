from aiogram.fsm.state import State, StatesGroup


class OrderStates(StatesGroup):
    waiting_confirm = State()


class SendMessageStates(StatesGroup):
    waiting_user_id = State()
    waiting_text = State()
    waiting_button = State()
    confirm = State()


class RefreshStates(StatesGroup):
    waiting_datetime = State()
