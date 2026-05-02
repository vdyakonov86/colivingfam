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
from vpn_bot.keyboards import admin_main_kb, cancel_reply_kb, residents_pick_inline, rooms_reply_kb, resident_menu_kb
from vpn_bot.slug import make_client_email
from vpn_bot.states import AddResidentStates
from vpn_bot.texts import format_residents_list
from vpn_bot.xui_client import XuiApiError, XuiClient

logger = logging.getLogger(__name__)


def build_admin_router(settings: Settings, db: Database, xui: XuiClient) -> Router:
    router = Router(name="admin")
    is_admin = IsAdmin(settings)

    @router.message(CommandStart(), is_admin)
    async def admin_start(message: Message, command: CommandObject) -> None:

        args = (command.args or "").strip()
        if args.startswith("link_"):
            code = args.removeprefix("link_").strip()
            lc = await db.consume_link_code(code)
            if not lc:
                await message.answer("Код недействителен или истёк. Запросите новый у администратора.")
                return
            r, room_number = await db.get_resident_with_room_by_id(lc.resident_id)
            if not r:
                await message.answer("Ошибка: запись не найдена.")
                return

            r_binded = await db.get_resident_by_telegram(message.from_user.id)
            if r_binded:
                await message.answer("К вашему Telegram уже прикреплена ссылка для подписки. Обратитесь к администратору")
                return

            if r.telegram_user_id is not None:
                await message.answer("Этот житель уже привязан к другому Telegram.")
                return

            await db.bind_telegram(r.id, message.from_user.id)
            await message.answer(
                f"Привязка выполнена: <b>{html.escape(r.first_name)}</b> ({html.escape(room_number)}).\n"
                "Ниже меню для получения ссылки и QR.",
                reply_markup=resident_menu_kb(),
            )
            return
        else:
            await message.answer(
                "Админ-панель бота коливинга. Выберите действие кнопками ниже.",
                reply_markup=admin_main_kb(),
            )

    @router.message(Command("admin"), is_admin)
    async def admin_cmd(message: Message) -> None:
        await message.answer("Меню администратора.", reply_markup=admin_main_kb())

    @router.message(Command("test"), is_admin)
    async def test_cmd(message: Message) -> None:
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
            "Вы не привязаны к коливингу. Попросите у администратора код привязки и откройте ссылку, "
            "или отправьте команду из приглашения.",
        )

    @router.message(F.text == "Список жителей", is_admin)
    async def list_residents(message: Message) -> None:
        residents = await db.list_residents_grouped_with_room()
        text = format_residents_list(residents)
        # Telegram message limit ~4096
        chunk = 3800
        for i in range(0, len(text), chunk):
            await message.answer(text[i : i + chunk], parse_mode="HTML")

    @router.message(F.text == "Добавить жителя", is_admin)
    async def add_begin(message: Message, state: FSMContext) -> None:
        await state.set_state(AddResidentStates.first_name)
        await message.answer("Введите имя жителя.", reply_markup=cancel_reply_kb())

    @router.message(StateFilter(AddResidentStates.first_name), F.text == "Отмена", is_admin)
    @router.message(StateFilter(AddResidentStates.last_name), F.text == "Отмена", is_admin)
    @router.message(StateFilter(AddResidentStates.room), F.text == "Отмена", is_admin)
    async def add_cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_main_kb())

    @router.message(StateFilter(AddResidentStates.first_name), is_admin)
    async def add_first(message: Message, state: FSMContext) -> None:
        await state.update_data(first_name=message.text.strip())
        await state.set_state(AddResidentStates.room)
        # await message.answer("Введите фамилию.", reply_markup=cancel_reply_kb())
        await message.answer("Выберите комнату (F1–F12).", reply_markup=rooms_reply_kb())

    # @router.message(StateFilter(AddResidentStates.last_name), is_admin)
    # async def add_last(message: Message, state: FSMContext) -> None:
    #     await state.update_data(last_name=message.text.strip())
    #     await state.set_state(AddResidentStates.room)
    #     await message.answer("Выберите комнату (F1–F12).", reply_markup=rooms_reply_kb())

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
            await message.answer(
                f"Не удалось привязать жителя к комнате '{room_number}'. К ней привязано макс. возможное количество жителей: {max_residents})", 
                reply_markup=admin_main_kb()
            )
            return
        
        try:
            email = make_client_email(room_number, last, first)
            _, client_uuid, sub_id = await xui.add_vless_client(email, tg_id=0)
            rid = await db.add_resident(first, last, room_number, email, client_uuid, sub_id)
        except XuiApiError as e:
            logger.exception("3x-ui add client failed")
            await state.clear()
            await message.answer(f"Ошибка панели 3x-ui: {e}", reply_markup=admin_main_kb())
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
            await message.answer("Произошла внутренняя ошибка. Попробуйте позже.", reply_markup=admin_main_kb())
            return

        await state.clear()
        await message.answer(
            f"Житель <b>{html.escape(first)}</b> ({html.escape(room_number)}) добавлен",
            parse_mode="HTML",
            reply_markup=admin_main_kb(),
        )

    @router.message(F.text == "Удалить жителя", is_admin)
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
            await cq.message.answer(f"Ошибка удаления в панели: {e}")
            await cq.answer()
            return
        await db.delete_resident(rid)
        await cq.message.answer(f"Житель <b>{html.escape(r.first_name)}</b> ({html.escape(room_number)}) удалён.", parse_mode="HTML")
        await cq.answer()

    @router.message(F.text == "Код привязки", is_admin)
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
            f"Ссылка для жителя <b>{html.escape(r.first_name)}</b> ({html.escape(room_number)}): (действует ~{settings.link_code_ttl_minutes} мин):\n{deep}",
            parse_mode="HTML",
        )
        await cq.answer()

    return router
