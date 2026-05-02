from __future__ import annotations

import html
import io

import qrcode
from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from vpn_bot.config import Settings
from vpn_bot.db import Database
from vpn_bot.filters import IsNotAdmin
from vpn_bot.keyboards import resident_menu_kb
from vpn_bot.xui_client import XuiClient
from vpn_bot.handlers.common import handle_bind_link

def build_user_router(settings: Settings, db: Database, xui: XuiClient) -> Router:
    router = Router(name="user")
    not_admin = IsNotAdmin(settings)

    @router.message(CommandStart(), not_admin)
    async def user_start(message: Message, command: CommandObject) -> None:
        if message.from_user is None:
            return

        args = (command.args or "").strip()
        if args.startswith("link_"):
            code = args.removeprefix("link_").strip()
            await handle_bind_link(message, db, code)
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

    @router.callback_query(F.data == "resident:sub")
    async def cb_sub(cq: CallbackQuery) -> None:
        if cq.from_user is None or cq.message is None:
            await cq.answer()
            return
        r = await db.get_resident_by_telegram(cq.from_user.id)
        if not r:
            await cq.answer("Нет привязки", show_alert=True)
            return
        url = xui.subscription_url(r.xui_sub_id)
        await cq.message.answer(f"Ссылка подписки:\n<code>{url}</code>", parse_mode="HTML")
        await cq.answer()

    @router.callback_query(F.data == "resident:qr")
    async def cb_qr(cq: CallbackQuery) -> None:
        if cq.from_user is None or cq.message is None:
            await cq.answer()
            return
        r = await db.get_resident_by_telegram(cq.from_user.id)
        if not r:
            await cq.answer("Нет привязки", show_alert=True)
            return
        url = xui.subscription_url(r.xui_sub_id)
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        await cq.message.answer_photo(
            BufferedInputFile(buf.read(), filename="sub.png"),
            caption="QR для подписки (добавьте в клиент).",
        )
        await cq.answer()

    return router
