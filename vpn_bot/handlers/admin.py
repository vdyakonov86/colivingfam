from __future__ import annotations

import html
import logging
import secrets
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from vpn_bot.config import Settings
from vpn_bot.db import Database, normalize_room
from vpn_bot.filters import IsAdmin
from vpn_bot.keyboards import admin_main_kb, cancel_reply_kb, residents_pick_inline, rooms_reply_kb
from vpn_bot.slug import make_client_email
from vpn_bot.states import AddResidentStates
from vpn_bot.texts import format_residents_list
from vpn_bot.xui_client import XuiApiError, XuiClient

logger = logging.getLogger(__name__)


def build_admin_router(settings: Settings, db: Database, xui: XuiClient) -> Router:
    router = Router(name="admin")
    is_admin = IsAdmin(settings)

    @router.message(CommandStart(), is_admin)
    async def admin_start(message: Message) -> None:
        await message.answer(
            "Админ-панель бота коливинга. Выберите действие кнопками ниже.",
            reply_markup=admin_main_kb(),
        )

    @router.message(Command("admin"), is_admin)
    async def admin_cmd(message: Message) -> None:
        await message.answer("Меню администратора.", reply_markup=admin_main_kb())

    @router.message(F.text == "Список жителей", is_admin)
    async def list_residents(message: Message) -> None:
        residents = await db.list_residents_grouped()
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
        await state.set_state(AddResidentStates.last_name)
        await message.answer("Введите фамилию.", reply_markup=cancel_reply_kb())

    @router.message(StateFilter(AddResidentStates.last_name), is_admin)
    async def add_last(message: Message, state: FSMContext) -> None:
        await state.update_data(last_name=message.text.strip())
        await state.set_state(AddResidentStates.room)
        await message.answer("Выберите комнату (F1–F12).", reply_markup=rooms_reply_kb())

    @router.message(StateFilter(AddResidentStates.room), is_admin)
    async def add_room(message: Message, state: FSMContext) -> None:
        try:
            room = normalize_room(message.text.strip())
        except ValueError as e:
            await message.answer(str(e))
            return
        data = await state.get_data()
        first: str = data["first_name"]
        last: str = data["last_name"]

        count = await db.count_residents()
        if count >= settings.max_residents:
            await state.clear()
            await message.answer(
                f"Достигнут лимит жителей ({settings.max_residents}).",
                reply_markup=admin_main_kb(),
            )
            return

        email = make_client_email(room, last, first)
        try:
            _, client_uuid, sub_id = await xui.add_vless_client(email, tg_id=0)
        except XuiApiError as e:
            logger.exception("3x-ui add client failed")
            await message.answer(f"Ошибка панели 3x-ui: {e}", reply_markup=admin_main_kb())
            await state.clear()
            return

        try:
            rid = await db.add_resident(first, last, room, email, client_uuid, sub_id)
        except Exception:
            logger.exception("DB add failed; rolling back XUI client")
            try:
                await xui.delete_client(client_uuid)
            except XuiApiError:
                logger.exception("Rollback delete client failed")
            await state.clear()
            await message.answer("Ошибка базы данных.", reply_markup=admin_main_kb())
            return

        await state.clear()
        await message.answer(
            f"Житель добавлен (id=<code>{rid}</code>, email=<code>{html.escape(email)}</code>).",
            parse_mode="HTML",
            reply_markup=admin_main_kb(),
        )

    @router.message(F.text == "Удалить жителя", is_admin)
    async def del_pick(message: Message) -> None:
        residents = await db.list_residents_grouped()
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
        r = await db.get_resident(rid)
        if not r:
            await cq.answer("Запись не найдена", show_alert=True)
            return
        await cq.message.edit_reply_markup(reply_markup=None)
        try:
            await xui.delete_client(r.xui_client_id)
        except XuiApiError as e:
            await cq.message.answer(f"Ошибка удаления в панели: {e}")
            await cq.answer()
            return
        await db.delete_resident(rid)
        await cq.message.answer(f"Житель <code>{rid}</code> удалён.", parse_mode="HTML")
        await cq.answer()

    @router.message(F.text == "Код привязки", is_admin)
    async def link_pick(message: Message) -> None:
        residents = await db.list_residents_grouped()
        unlinked = [r for r in residents if r.telegram_user_id is None]
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
        r = await db.get_resident(rid)
        if not r or r.telegram_user_id is not None:
            await cq.answer("Недоступно", show_alert=True)
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
            f"Код привязки для <b>{html.escape(r.last_name)} {html.escape(r.first_name)}</b> ({html.escape(r.room)}):\n"
            f"<code>{code}</code>\n\n"
            f"Ссылка для жителя (действует ~{settings.link_code_ttl_minutes} мин):\n{deep}",
            parse_mode="HTML",
        )
        await cq.answer()

    return router
