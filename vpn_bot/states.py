from aiogram.fsm.state import State, StatesGroup


class AddResidentStates(StatesGroup):
    place = State()
    first_name = State()
    room = State()

class SendAccessRequestStates(StatesGroup):
    place = State()
    name = State()
    room = State()

class ProcessAccessRequestStates(StatesGroup):
    place = State()
    choosing_room = State() # Для выбора комнаты при добавлении