from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from vpn_bot.config import Settings


class IsAdmin(Filter):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        u = event.from_user
        if u is None:
            return False
        return u.id in self._settings.admin_id_set


class IsNotAdmin(Filter):
    def __init__(self, settings: Settings) -> None:
        self._admin = IsAdmin(settings)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return not await self._admin(event)
