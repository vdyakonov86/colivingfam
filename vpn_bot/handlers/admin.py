from __future__ import annotations

import html
import logging
import secrets
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from vpn_bot.config import Settings
from vpn_bot.db import Database, normalize_room
from vpn_bot.filters import IsAdmin
from vpn_bot.keyboards import admin_main_kb, cancel_reply_kb, residents_pick_inline, rooms_reply_kb, resident_menu_kb, resident_access_request_kb, access_requests_list_kb, access_request_action_kb
from vpn_bot.slug import make_client_email
from vpn_bot.states import AddResidentStates, ProcessAccessRequestStates
from vpn_bot.texts import format_residents_list
from vpn_bot.xui_client import XuiApiError, XuiClient
from vpn_bot.handlers.common import handle_bind_link, register_access_request_handlers

logger = logging.getLogger(__name__)


def build_admin_router(settings: Settings, db: Database, xui: XuiClient) -> Router:
    router = Router(name="admin")
    is_admin = IsAdmin(settings)

     # Регистрируем общие обработчики для запроса доступа
    register_access_request_handlers(router, db)

    @router.message(CommandStart(), is_admin)
    async def admin_start(message: Message, command: CommandObject) -> None:
        args = (command.args or "").strip()
        if args.startswith("link_"):
            code = args.removeprefix("link_").strip()
            await handle_bind_link(message, db, code)
            return
        else:
            admin_name = message.from_user.full_name if message.from_user else "Администратор"
            message_text = (
                f"👋 Здравствуйте, {html.escape(admin_name)}!\n\n"
                "🛠 <b>Панель управления коливингом</b>\n"
                "Здесь вы можете управлять жильцами и их ключами.\n\n"
                "Выберите действие с помощью кнопок ниже."
            )
            await update_admin_keyboard_with_access_request_count(db, message=message, message_text=message_text)


    @router.message(Command("admin"), is_admin)
    async def admin_cmd(message: Message) -> None:
        await update_admin_keyboard_with_access_request_count(db, message=message)


    @router.message(F.text == "📋 Список жителей", is_admin)
    async def list_residents(message: Message) -> None:
        residents = await db.list_residents_grouped_with_room()
        if not residents:
            await message.answer("📭 Список жителей пуст.")
            return
        text = format_residents_list(residents)
        # Telegram message limit ~4096
        chunk = 3800
        for i in range(0, len(text), chunk):
            await message.answer(text[i : i + chunk], parse_mode="HTML", disable_web_page_preview=True)

    @router.message(F.text == "➕ Добавить жителя", is_admin)
    async def add_begin(message: Message, state: FSMContext) -> None:
        await state.set_state(AddResidentStates.first_name)
        await message.answer("Введите имя жителя:", reply_markup=cancel_reply_kb())

    @router.message(StateFilter(AddResidentStates.first_name), F.text == "Отмена", is_admin)
    @router.message(StateFilter(AddResidentStates.room), F.text == "Отмена", is_admin)
    async def add_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await update_admin_keyboard_with_access_request_count(db, message=message, message_text="Отменено")

    @router.message(StateFilter(AddResidentStates.first_name), is_admin)
    async def add_first(message: Message, state: FSMContext) -> None:
        name = message.text.strip()
        if not name:
            await message.answer("❌ Имя не может быть пустым. Попробуйте ещё раз.")
            return
        await state.update_data(first_name=name)
        await state.set_state(AddResidentStates.room)
        rooms = await db.get_all_room_numbers()
        # await message.answer("Введите фамилию.", reply_markup=cancel_reply_kb())
        await message.answer(
            "🏠 Выберите комнату для жителя:",
            reply_markup=rooms_reply_kb(rooms)
        )
 
    @router.message(StateFilter(AddResidentStates.room), is_admin)
    async def add_room(message: Message, state: FSMContext) -> None:
        try:
            room_number = normalize_room(message.text.strip())
        except ValueError as e:
            await state.clear()
            await message.answer(str(e), reply_markup=admin_main_kb())
            return

        data = await state.get_data()
        first: str = data["first_name"]
        last: str = data.get("last_name", "")

        count = await db.count_residents()
        if count >= settings.max_residents:
            await state.clear()
            await message.answer(
                f"Достигнут лимит жителей ({settings.max_residents}).",
                reply_markup=admin_main_kb(),
            )
            return

        room = await db.get_room_by_room_number(room_number)
        if room is None:
            await state.clear()
            await message.answer(f"Комнаты '{room_number}' не существует", reply_markup=admin_main_kb())
            return
        
        room_residents_count = await db.count_residents_by_room_id(room.id)
        max_residents = room.max_residents
        if (room_residents_count + 1) > max_residents:
            await state.clear()
            await update_admin_keyboard_with_access_request_count(
                db, 
                message=message, 
                message_text=f"Не удалось привязать жителя к комнате '{room_number}'. К ней привязано макс. возможное количество жителей: {max_residents})"
            )
            return
        
        try:
            email = make_client_email(room_number, last, first)
            _, client_uuid, sub_id = await xui.add_vless_client(email, tg_id=0)
            rid = await db.add_resident(first, last, room_number, email, client_uuid, sub_id)
        except XuiApiError as e:
            logger.exception("3x-ui add client failed")
            await state.clear()
            await update_admin_keyboard_with_access_request_count(db, message=message, message_text=f"Ошибка панели 3x-ui: {e}")
            return
        except Exception as e:
            logger.exception("Unexpected error during resident creation")
            # Пытаемся откатить клиента в XUI, если он был создан
            if 'client_uuid' in locals():
                try:
                    await xui.delete_client(client_uuid)
                except XuiApiError:
                    logger.exception("Rollback delete client failed")
            await state.clear()
            await update_admin_keyboard_with_access_request_count(db, message=message, message_text="Произошла внутренняя ошибка. Попробуйте позже.")
            return

        await state.clear()
        await update_admin_keyboard_with_access_request_count(db, message=message, message_text=f"Житель <b>{html.escape(first)}</b> ({html.escape(room_number)}) добавлен")

    @router.message(F.text == "❌ Удалить жителя", is_admin)
    async def del_pick(message: Message) -> None:
        residents = await db.list_residents_grouped_with_room()
        if not residents:
            await message.answer("Список пуст.")
            return
        await message.answer(
            "Выберите жителя для удаления:",
            reply_markup=residents_pick_inline(residents, prefix="adm_del"),
        )

    @router.callback_query(F.data.startswith("adm_del:"), is_admin)
    async def del_confirm(cq: CallbackQuery) -> None:
        if cq.message is None:
            await cq.answer()
            return
        rid = int(cq.data.split(":", 1)[1])
        r, room_number = await db.get_resident_with_room_by_id(rid)
        if not r:
            await cq.answer("Запись не найдена", show_alert=True)
            return
        await cq.message.edit_reply_markup(reply_markup=None)
        try:
            await xui.delete_client(r.xui_uuid)
        except XuiApiError as e:
            await cq.message.answer(f"⚠️ Ошибка удаления в панели: {e}")
            await cq.answer()
            return
        await db.delete_resident(rid)
        await cq.message.answer(
            f"🗑 Житель <b>{html.escape(r.first_name)} {html.escape(r.last_name)}</b> из комнаты {html.escape(room_number)} удалён.\n"
            f"Ключ VPN отозван.",
            parse_mode="HTML"
        )
        await cq.answer()

    @router.message(F.text == "🔗 Код привязки", is_admin)
    async def link_pick(message: Message) -> None:
        residents = await db.list_residents_grouped_with_room()
        unlinked = [(room_number, r) for (room_number, r) in residents if r.telegram_user_id is None]
        if not unlinked:
            await message.answer("Нет жителей без привязки Telegram.")
            return
        await message.answer(
            "Выберите жителя для выдачи кода привязки:",
            reply_markup=residents_pick_inline(unlinked, prefix="adm_link"),
        )

    @router.callback_query(F.data.startswith("adm_link:"), is_admin)
    async def link_issue(cq: CallbackQuery) -> None:
        if cq.message is None:
            await cq.answer()
            return
        rid = int(cq.data.split(":", 1)[1])
        r, room_number = await db.get_resident_with_room_by_id(rid)
        if not r:
            await cq.answer("Пользователь не существует", show_alert=True)
            return
        if r.telegram_user_id is not None:
            await cq.answer("Telegram пользователя уже привязан", show_alert=True)
            return
        code = secrets.token_urlsafe(8).replace("-", "")[:12].lower()
        expires = int(time.time()) + settings.link_code_ttl_minutes * 60
        await db.add_link_code(code, rid, expires)
        me = await cq.bot.get_me()
        if not me.username:
            await cq.answer("У бота нет username в Telegram", show_alert=True)
            return
        deep = f"https://t.me/{me.username}?start=link_{code}"
        await cq.message.edit_reply_markup(reply_markup=None)
        await cq.message.answer(
            f"🔗 <b>Код привязки для жителя {html.escape(r.first_name)} {html.escape(r.last_name)}</b> ({html.escape(room_number)})\n\n"
            f"⏱ Действует: {settings.link_code_ttl_minutes} мин.\n\n"
            f"🔹 <b>Отправьте жителю ссылку для привязки Telegram:</b>\n{deep}\n\n"
            f"👉 После перехода по ссылке житель получит доступ к меню VPN.",
            parse_mode="HTML",
        )
        await cq.answer()

    @router.message(F.text.startswith("👥 Запросы доступа"), is_admin)
    async def list_access_requests(message: Message) -> None:
        requests = await db.get_access_requests()
        count = len(requests)
        if count == 0:
            await message.answer("📭 Список ожидающих пуст.")
            return
        
        await message.answer(
            f"👥 <b>Список ожидающих: {count}</b>\n\n"
            "Выберите человека для обработки:",
            reply_markup=access_requests_list_kb(requests),
            parse_mode="HTML"
        )
    
    @router.callback_query(F.data.startswith("access_req:"), is_admin)
    async def show_access_request(cq: CallbackQuery) -> None:
        if cq.message is None:
            await cq.answer()
            return
        
        request_id = int(cq.data.split(":")[1])
        req = await db.get_access_request_by_id(request_id)
        
        if not req:
            await cq.answer("Запрос не найден", show_alert=True)
            return
        
        # Форматируем дату
        from datetime import datetime
        request_date = datetime.fromtimestamp(req.requested_at).strftime("%d.%m.%Y %H:%M")
        
        text = (
            f"👤 <b>Запрос доступа</b>\n\n"
            f"Имя: <b>{html.escape(req.name)}</b>\n"
            f"Комната: <b>{html.escape(req.room_number)}</b>\n"
            f"Дата запроса: {request_date}\n"
            f"Telegram ID: <code>{req.telegram_user_id}</code>\n"
        )
        
        if req.telegram_username:
            text += f"Username: @{html.escape(req.telegram_username)}\n"
        else:
            text += "Username: <i>не указан</i>\n"
        
        text += "\nВыберите действие:"
        
        await cq.message.edit_text(
            text,
            reply_markup=access_request_action_kb(req.id, req.telegram_username),
            parse_mode="HTML"
        )
        await cq.answer()

    @router.callback_query(F.data.startswith("access_action:add:"), is_admin)
    async def start_add_resident_from_request(cq: CallbackQuery, state: FSMContext) -> None:
        if cq.message is None:
            await cq.answer()
            return
        
        request_id = int(cq.data.split(":")[2])
        req = await db.get_access_request_by_id(request_id)
        
        if not req:
            await cq.answer("Запрос не найден", show_alert=True)
            return
        
        # Сохраняем данные запроса в состоянии
        await state.update_data(
            request_id=request_id,
            name=req.name,
            room_number=req.room_number,
            telegram_user_id=req.telegram_user_id,
            telegram_username=req.telegram_username
        )
        await state.set_state(ProcessAccessRequestStates.choosing_room)
        
        rooms = await db.get_all_room_numbers()
        await cq.message.answer(
            f"👤 <b>{html.escape(req.name)}</b> указал комнату <b>{html.escape(req.room_number)}</b>\n\n"
            "Вы можете подтвердить эту комнату или выбрать другую:",
            reply_markup=rooms_reply_kb(rooms),
            parse_mode="HTML"
        )
        await cq.answer()
    
    @router.message(ProcessAccessRequestStates.choosing_room, F.text == "Отмена", is_admin)
    async def cancel_add_from_request(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Добавление отменено.", reply_markup=admin_main_kb())
    
    @router.message(ProcessAccessRequestStates.choosing_room, is_admin)
    async def add_resident_from_request(message: Message, state: FSMContext) -> None:
        try:
            room_number = normalize_room(message.text.strip())
        except ValueError as e:
            await message.answer(str(e), reply_markup=cancel_reply_kb())
            return
        
        data = await state.get_data()
        name = data["name"]
        request_id = data["request_id"]
        telegram_user_id = data["telegram_user_id"]
        telegram_username = data["telegram_username"]
        
        room = await db.get_room_by_room_number(room_number)
        if room is None:
            await message.answer(
                f"Комнаты '{room_number}' не существует",
                reply_markup=cancel_reply_kb()
            )
            return
        
        room_residents_count = await db.count_residents_by_room_id(room.id)
        if room_residents_count >= room.max_residents:
            await message.answer(
                f"❌ Комната {room_number} заполнена (макс. {room.max_residents} чел.)",
                reply_markup=cancel_reply_kb()
            )
            return
        
        try:
            email = make_client_email(room_number, "", name)
            _, client_uuid, sub_id = await xui.add_vless_client(email, tg_id=telegram_user_id)
            rid = await db.add_resident(name, "", room_number, email, client_uuid, sub_id)
            
            # Привязываем Telegram сразу
            await db.bind_telegram(rid, telegram_user_id, telegram_username)
            
            # Удаляем запрос доступа
            await db.delete_access_request(request_id)
            
        except XuiApiError as e:
            logger.exception("3x-ui add client failed")
            await message.answer(f"Ошибка панели 3x-ui: {e}", reply_markup=admin_main_kb())
            await state.clear()
            return
        except Exception as e:
            logger.exception("Unexpected error during resident creation")
            await message.answer("Произошла внутренняя ошибка.", reply_markup=admin_main_kb())
            await state.clear()
            return
        
        await state.clear()
        
        # Уведомляем пользователя
        try:
            await message.bot.send_message(
                telegram_user_id,
                "✅ Ваш запрос доступа одобрен!\n",
                parse_mode="HTML",
                reply_markup=resident_menu_kb()
            )
        except Exception:
            logger.warning(f"Failed to notify user {telegram_user_id}")
        
        await update_admin_keyboard_with_access_request_count(db, message=message, message_text=f"✅ Пользователь <b>{html.escape(name)}</b> добавлен")

    @router.callback_query(F.data.startswith("access_action:reject:"), is_admin)
    async def reject_access_request(cq: CallbackQuery) -> None:
        if cq.message is None:
            await cq.answer()
            return
        
        request_id = int(cq.data.split(":")[2])
        req = await db.get_access_request_by_id(request_id)
        
        if not req:
            await cq.answer("Запрос не найден", show_alert=True)
            return
        
        # Удаляем запрос
        await db.delete_access_request(request_id)
        
        # Уведомляем пользователя
        try:
            await cq.bot.send_message(
                req.telegram_user_id,
                "❌ Ваш запрос доступа был отклонён администратором.\n"
                "Обратитесь к администратору лично для уточнения причины."
            )
        except Exception:
            logger.warning(f"Failed to notify user {req.telegram_user_id} about rejection")
        
        # Обновляем сообщение админу
        await cq.message.edit_text(
            f"❌ Запрос от <b>{html.escape(req.name)}</b> отклонён.\n"
            f"Комната: {html.escape(req.room_number)}",
            reply_markup=None,
            parse_mode="HTML"
        )
        
        # Показываем обновлённый список
        requests = await db.get_access_requests()
        count = len(requests)
        if count == 0:
            await update_admin_keyboard_with_access_request_count(db, callback=cq, message_text="📭 Список ожидающих пуст")
        else:
            await cq.message.answer(
                f"👥 <b>Оставшиеся запросы: {count}</b>",
                reply_markup=access_requests_list_kb(requests),
                parse_mode="HTML"
            )

    async def update_admin_keyboard_with_access_request_count(
        db: Database, 
        message: Message = None, 
        callback: CallbackQuery = None, 
        message_text: str = "Главное меню:"
    ) -> None:
        """
        Обновляет клавиатуру админа с актуальным количеством ожидающих запросов.
        Принимает либо message, либо callback (одно из двух).
        """
        requests = await db.get_access_requests()
        count = len(requests)
        
        keyboard = admin_main_kb(access_requests_count=count)
        
        if message:
            await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        elif callback and callback.message:
            await callback.message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")

    @router.message(Command("test"), is_admin)
    async def test_cmd(message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            return

        r = await db.get_resident_by_telegram(message.from_user.id)
        if r:
            await message.answer(
                f"{html.escape(r.first_name)}, ваше меню:",
                reply_markup=resident_menu_kb(),
            )
            return
        
        await message.answer(
            "Вы не привязаны к боту. Можете отправить запрос на привязку",
            reply_markup=resident_access_request_kb()
        )

    return router
