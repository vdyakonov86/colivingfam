import html
from aiogram.types import Message
from vpn_bot.db import Database
from vpn_bot.keyboards import resident_menu_kb

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
    await db.bind_telegram(r.id, message.from_user.id)

    await message.answer(
        f"Привязка выполнена: <b>{html.escape(r.first_name)}</b> ({html.escape(room_number)}).\n"
        "Ниже меню для получения ссылки и QR.",
        reply_markup=resident_menu_kb(),
        parse_mode="HTML"
    )
    return True