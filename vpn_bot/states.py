from aiogram.fsm.state import State, StatesGroup


class AddResidentStates(StatesGroup):
    first_name = State()
    last_name = State()
    room = State()
