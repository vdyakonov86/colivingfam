from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from vpn_bot.config import get_settings
from vpn_bot.db import Database
from vpn_bot.handlers.admin import build_admin_router
from vpn_bot.handlers.user import build_user_router
from vpn_bot.xui_client import XuiApiError, XuiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def async_main() -> None:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path)
    await db.init()

    xui = XuiClient(settings)
    try:
        await xui.login()
    except XuiApiError:
        logging.exception("Не удалось войти в панель 3x-ui. Проверьте XUI_* в .env")
        await xui.aclose()
        raise

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_admin_router(settings, db, xui))
    dp.include_router(build_user_router(settings, db, xui))

    try:
        await dp.start_polling(bot)
    finally:
        await xui.aclose()


def main() -> None:
    asyncio.run(async_main())
