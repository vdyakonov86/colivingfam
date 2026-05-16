import html
import time 

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from vpn_bot.db import Database, normalize_room
from vpn_bot.keyboards import resident_menu_kb, cancel_reply_kb, rooms_reply_kb, resident_menu_kb, resident_access_request_kb, places_pick_inline
from vpn_bot.states import SendAccessRequestStates
from vpn_bot.xui_client import XuiClient
from vpn_bot.slug import make_client_email

async def create_resident_with_checks(
    *,
    db: Database,
    xui: XuiClient,
    place_id: int,
    first_name: str,
    last_name: str,
    room_number: str,
    tg_id: int,
) -> tuple[int, str]:
    """
    Делает:
    - проверка существования комнаты в place
    - проверка лимита комнаты
    - создание клиента в 3x-ui
    - добавление resident в БД (с place_id)
    Возвращает: (resident_id, xui_uuid)
    """
    room = await db.get_room_by_place_and_number(place_id, room_number)
    if room is None:
        raise ValueError(f"Комнаты '{room_number}' не существует в выбранном коливинге")

    room_residents_count = await db.count_residents_by_room_id(room.id)
    if room_residents_count >= room.max_residents:
        raise ValueError(f"Комната {room_number} заполнена (макс. {room.max_residents} чел.)")

    email = make_client_email(room_number, last_name, first_name)
    _, client_uuid, sub_id = await xui.add_vless_client(email, tg_id=tg_id)

    rid = await db.add_resident(place_id, first_name, last_name, room_number, email, client_uuid, sub_id)
    return rid, client_uuid

async def handle_bind_link(message: Message, db: Database, code: str) -> bool:
    """
    Обрабатывает привязку Telegram-аккаунта к жителю по коду из ссылки.
    Возвращает True, если привязка успешна, иначе False.
    Все сообщения об ошибках и успехе отправляются в чат.
    """
    lc = await db.consume_link_code(code)
    if not lc:
        await message.answer("Код недействителен или истёк. Запросите новый у администратора.")
        return False

    r, room_number = await db.get_resident_with_room_by_id(lc.resident_id)
    if not r:
        await message.answer("Ошибка: запись не найдена.")
        return False

    # Проверка, не привязан ли уже этот Telegram
    r_binded = await db.get_resident_by_telegram(message.from_user.id)
    if r_binded:
        await message.answer("К вашему Telegram уже прикреплена ссылка для подписки. Обратитесь к администратору")
        return False

    # Проверка, не привязан ли уже этот житель к другому Telegram
    if r.telegram_user_id is not None:
        await message.answer("Этот житель уже привязан к другому Telegram.")
        return False

    # Выполняем привязку
    await db.bind_telegram(r.id, message.from_user.id, message.from_user.username)

    await message.answer(
        f"Привязка выполнена: <b>{html.escape(r.first_name)}</b> ({html.escape(room_number)}).\n"
        "Ниже меню для получения ссылки и QR.",
        reply_markup=resident_menu_kb(),
        parse_mode="HTML"
    )
    return True

def register_access_request_handlers(router: Router, db: Database) -> None:
    """Регистрирует общие обработчики запроса доступа как для админа, так и для пользователя."""
    
    @router.message(StateFilter(SendAccessRequestStates.place), F.text == "Отмена")
    @router.message(StateFilter(SendAccessRequestStates.name), F.text == "Отмена")
    @router.message(StateFilter(SendAccessRequestStates.room), F.text == "Отмена")
    async def cancel_access_request(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        await message.answer("Вы не привязаны к боту. Можете отправить запрос на привязку", reply_markup=resident_access_request_kb())

    @router.callback_query(F.data == "resident:access_request")
    async def cb_access_request(cq: CallbackQuery, state: FSMContext) -> None:
        if cq.from_user is None or cq.message is None:
            await cq.answer()
            return

        places = await db.list_places()
        await state.set_state(SendAccessRequestStates.place)
        await cq.message.answer(
            "🏠 Выберите коливинг:",
            reply_markup=places_pick_inline(places, prefix="req_place")
        )
        await cq.answer()

    @router.callback_query(StateFilter(SendAccessRequestStates.place), F.data.startswith("req_place:"))
    async def pick_place_for_request(cq: CallbackQuery, state: FSMContext) -> None:
        if cq.message is None:
            await cq.answer()
            return
        place_id = int(cq.data.split(":", 1)[1])
        await state.update_data(place_id=place_id)
        await state.set_state(SendAccessRequestStates.name)
        await cq.message.answer("✏️ Введите имя:", reply_markup=cancel_reply_kb())
        await cq.answer()
        
    @router.message(StateFilter(SendAccessRequestStates.name))
    async def process_name(message: Message, state: FSMContext) -> None:
        name = message.text.strip()
        if not name:
            await message.answer("❌ Имя не может быть пустым.", reply_markup=cancel_reply_kb())
            return

        await state.update_data(name=name)
        data = await state.get_data()
        place_id = int(data["place_id"])

        await state.set_state(SendAccessRequestStates.room)
        rooms = await db.get_all_room_numbers(place_id)
        await message.answer("🚪 Выберите комнату:", reply_markup=rooms_reply_kb(rooms))
    
    @router.message(StateFilter(SendAccessRequestStates.room))
    async def process_room(message: Message, state: FSMContext) -> None:
        try:
            room_number = normalize_room(message.text.strip())
        except ValueError as e:
            await message.answer(str(e), reply_markup=cancel_reply_kb())
            return

        data = await state.get_data()
        name = data["name"]
        place_id = int(data["place_id"])

        await db.add_access_request(
            telegram_user_id=message.from_user.id,
            telegram_username=message.from_user.username,
            name=name,
            room_number=room_number,
            place_id=place_id,
            requested_at=int(time.time())
        )

        await state.clear()
        await message.answer("✅ Запрос отправлен администратору. Ожидайте подтверждения.", reply_markup=ReplyKeyboardRemove())