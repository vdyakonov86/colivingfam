from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def rooms_reply_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    for i in range(1, 13):
        b.add(KeyboardButton(text=f"F{i}"))
    b.adjust(4, 4, 4)
    b.row(KeyboardButton(text="Отмена"))
    return b.as_markup(resize_keyboard=True)


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
    b.adjust(1)
    return b.as_markup()


def cancel_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True,
    )


def residents_pick_inline(residents: list, *, prefix: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in residents:
        label = f"{r.room} — {r.last_name} {r.first_name}"
        b.add(InlineKeyboardButton(text=label[:64], callback_data=f"{prefix}:{r.id}"))
    b.adjust(1)
    return b.as_markup()
