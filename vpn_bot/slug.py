from __future__ import annotations

import re
import secrets

from vpn_bot.db import normalize_room

_NON_LATIN = re.compile(r"[^a-z0-9]+")


def _translit_ru(s: str) -> str:
    """Преобразует русские буквы в латиницу (остальные символы оставляет без изменений)."""
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    result = []
    for ch in s.lower():
        result.append(mapping.get(ch, ch))
    return ''.join(result)

def _slug_part(s: str) -> str:
    s = s.strip().lower()
    # транслитерация русских букв
    s = _translit_ru(s)
    # оставляем только латинские буквы, цифры, дефис, подчёркивание
    s = re.sub(r"[^a-z0-9._-]+", "", s)
    if not s:
        s = "user"
    return s[:14]

def make_client_email(room: str, last_name: str, first_name: str) -> str:
    room_n = normalize_room(room).lower()
    last_a = _slug_part(last_name)
    first_a = _slug_part(first_name)
    tail = secrets.token_hex(3)
    base = "_".join(p for p in (room_n, last_a, first_a, tail) if p)
    email = f"{base}"[:56]
    if not email:
        email = f"{room_n}_{tail}"
    return email