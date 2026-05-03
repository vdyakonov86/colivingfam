from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from vpn_bot.db import Resident


def rooms_reply_kb(room_numbers: list[str]) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    for rn in room_numbers:
        builder.add(KeyboardButton(text=rn))
    builder.adjust(4, 4, 4)
    builder.row(KeyboardButton(text="Отмена"))
    return builder.as_markup(resize_keyboard=True)

def admin_main_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="Список жителей"))
    b.add(KeyboardButton(text="Добавить жителя"))
    b.add(KeyboardButton(text="Удалить жителя"))
    b.add(KeyboardButton(text="Код привязки"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def resident_menu_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Ссылка подписки", callback_data="resident:sub"))
    b.add(InlineKeyboardButton(text="QR подписки", callback_data="resident:qr"))
    b.add(InlineKeyboardButton(text="Остаток трафика", callback_data="resident:remain_traffic"))
    b.adjust(1)
    return b.as_markup()


def cancel_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True,
    )


def residents_pick_inline(residents: list[tuple[str, Resident]], *, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for (room_number, r) in residents:
        label = f"{room_number} — {r.first_name}"
        b.add(InlineKeyboardButton(text=label[:64], callback_data=f"{prefix}:{r.id}"))
    b.adjust(1)
    return b.as_markup()
