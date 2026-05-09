import html
import time 

from aiogram import F, Router
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from vpn_bot.db import Database, normalize_room
from vpn_bot.keyboards import resident_menu_kb, cancel_reply_kb, rooms_reply_kb, resident_menu_kb, resident_access_request_kb
from vpn_bot.states import SendAccessRequestStates

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
    
    @router.callback_query(F.data == "resident:access_request")
    async def cb_access_request(cq: CallbackQuery, state: FSMContext) -> None:
        if cq.from_user is None or cq.message is None:
            await cq.answer()
            return

        await state.set_state(SendAccessRequestStates.name)
        await cq.message.answer(
            "Введите имя (если людей с вашим именем несколько, обозначьте себя по-другому, чтобы было понятно, кто вы):",
            reply_markup=cancel_reply_kb()
        )
        await cq.answer()
    
    @router.message(StateFilter(SendAccessRequestStates.name), F.text == "Отмена")
    @router.message(StateFilter(SendAccessRequestStates.room), F.text == "Отмена")
    async def cancel_access_request(message: Message, state: FSMContext) -> None:
        await state.clear()
        # Убираем Reply-клавиатуру с кнопкой "Отмена"
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        await message.answer("Вы не привязаны к боту. Можете отправить запрос на привязку", reply_markup=resident_access_request_kb())
    
    @router.message(StateFilter(SendAccessRequestStates.name))
    async def process_name(message: Message, state: FSMContext) -> None:
        name = message.text.strip()
        if not name:
            await message.answer("❌ Имя не может быть пустым.", reply_markup=cancel_reply_kb())
            return
        
        await state.update_data(name=name)
        await state.set_state(SendAccessRequestStates.room)
        rooms = await db.get_all_room_numbers()
        await message.answer(
            "🏠 Выберите комнату:",
            reply_markup=rooms_reply_kb(rooms)
        )
    
    @router.message(StateFilter(SendAccessRequestStates.room))
    async def process_room(message: Message, state: FSMContext) -> None:
        try:
            room_number = normalize_room(message.text.strip())
        except ValueError as e:
            await message.answer(str(e), reply_markup=cancel_reply_kb())
            return
        
        data = await state.get_data()
        name = data.get("name")
        
        await db.add_access_request(
            telegram_user_id=message.from_user.id,
            telegram_username=message.from_user.username,
            name=name,
            room_number=room_number,
            requested_at=int(time.time())
        )
        
        await state.clear()
        await message.answer("✅ Запрос отправлен администратору. Ожидайте подтверждения.", reply_markup=ReplyKeyboardRemove())