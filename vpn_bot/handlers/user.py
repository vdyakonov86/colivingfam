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
from vpn_bot.keyboards import resident_menu_kb, resident_access_request_kb
from vpn_bot.xui_client import XuiClient
from vpn_bot.handlers.common import handle_bind_link, register_access_request_handlers

def build_user_router(settings: Settings, db: Database, xui: XuiClient) -> Router:
    router = Router(name="user")
    not_admin = IsNotAdmin(settings)

    # Регистрируем общие обработчики запроса доступа
    register_access_request_handlers(router, db) 

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
            "Вы не привязаны к боту. Можете отправить запрос на привязку",
            reply_markup=resident_access_request_kb()
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
        instructions = (
            "🔗 <b>Ссылка подписки</b>\n\n"
            "Скопируйте её и добавьте в клиент (v2rayNG / Streisand):\n"
            "• Кликните на плюсик ➕\n"
            "• Выберите «Импорт из буфера» или «Subscription»\n"
            "• Вставьте ссылку и сохраните\n\n"
            f"<code>{url}</code>"
        )
        await cq.message.answer(instructions, parse_mode="HTML", disable_web_page_preview=True)
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
        caption = (
            "📱 <b>QR-код подписки</b>\n\n"
            "Отсканируйте его в клиенте (v2rayNG / Streisand):\n"
            "• Нажмите на плюсик ➕\n"
            "• Выберите «Импорт из QR-кода»\n"
            "• Наведите камеру на экран"
        )
        await cq.message.answer_photo(
            BufferedInputFile(buf.read(), filename="sub.png"),
            caption=caption,
            parse_mode="HTML"
        )
        await cq.answer()

    @router.callback_query(F.data == "resident:remain_traffic")
    async def cb_remain_traffic(cq: CallbackQuery) -> None:
        if cq.from_user is None or cq.message is None:
            await cq.answer()
            return
        r = await db.get_resident_by_telegram(cq.from_user.id)
        if not r:
            await cq.answer("Нет привязки", show_alert=True)
            return

        total_gb = settings.xui_total_gb
        remain_bytes = await xui.get_remain_traffic(r.xui_email)

        if remain_bytes is None:
            await cq.message.answer("📊 <b>Тариф безлимитный</b>\n\nВы можете пользоваться VPN без ограничений.", parse_mode="HTML")
        else:
            remain_gb = round(remain_bytes, 2)
            used_gb = round(total_gb - remain_gb, 2)
            percent = (used_gb / total_gb) * 100 if total_gb > 0 else 0

            text = (
                f"📊 <b>Остаток трафика</b>\n\n"
                f"Использовано: {used_gb} / {total_gb} ГБ ({percent:.1f}%)\n\n"
                f"✅ <b>Доступно:</b> {remain_gb} ГБ"
            )
            await cq.message.answer(text, parse_mode="HTML")
        await cq.answer()

    @router.callback_query(F.data == "resident:supported_apps")
    async def cb_supported_apps(cq: CallbackQuery) -> None:
        if cq.from_user is None or cq.message is None:
            await cq.answer()
            return
        r = await db.get_resident_by_telegram(cq.from_user.id)
        if not r:
            await cq.answer("Нет привязки", show_alert=True)
            return
        
        # Формируем сообщение со ссылками на приложения
        text = (
            "📱 <b>Рекомендуемые приложения для подключения</b>\n\n"
            "🤖 <b>Android:</b>\n"
            "v2rayNG — скачать APK:\n"
            "https://github.com/2dust/v2rayNG/releases/download/2.0.18/v2rayNG_2.0.18-fdroid_arm64-v8a.apk\n\n"
            "🍏 <b>iOS (iPhone/iPad):</b>\n"
            "Streisand — установить из App Store:\n"
            "https://apps.apple.com/us/app/streisand/id6450534064\n\n"
            "💡 <b>Как подключиться:</b>\n"
            "1. Установите приложение\n"
            "2. Импортируйте конфигурацию (QR-код или ссылка подписки)\n"
            "3. Включите VPN"
        )
        
        await cq.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
        await cq.answer()

    return router
