from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from vpn_bot.config import Settings, get_settings
from vpn_bot.db import Database
from vpn_bot.handlers.admin import build_admin_router
from vpn_bot.handlers.user import build_user_router
from vpn_bot.xui_client import XuiApiError, XuiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

async def periodic_reset_check(db: Database, xui: XuiClient, settings: Settings, interval_seconds: int = 86400):
    """Проверяет раз в interval_seconds (по умолч. 1 день) и сбрасывает при необходимости."""
    while True:
        await asyncio.sleep(interval_seconds)
        await reset_overdue_traffic(db, xui, settings)

async def reset_overdue_traffic(db: Database, xui: XuiClient, settings: Settings):
    now = int(time.time())
    residents = await db.get_residents_for_reset(settings.traffic_reset_period)
    for r in residents:
        try:
            # сброс трафика в панели
            success = await xui.reset_client_traffic(r.xui_email)
            if success:
                # обновляем last_reset_at на текущее время
                await db.update_last_reset_time(r.id, now)
                logger.info(f"Traffic reset for {r.xui_email}")
            else:
                logger.error(f"Failed to reset traffic for {r.xui_email}")
        except Exception as e:
            logger.exception(f"Error resetting traffic for {r.xui_email}: {e}")

async def async_main() -> None:
    settings = get_settings()
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path, settings.seed_rooms_path)
    await db.init()

    xui = XuiClient(settings)
    try:
        await xui.login()
    except XuiApiError:
        logging.exception("Не удалось войти в панель 3x-ui. Проверьте XUI_* в .env")
        await xui.aclose()
        raise

    asyncio.create_task(periodic_reset_check(db, xui, settings))
    await reset_overdue_traffic(db, xui, settings)

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
