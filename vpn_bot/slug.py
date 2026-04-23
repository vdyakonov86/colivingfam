from __future__ import annotations

import re
import secrets

from vpn_bot.db import normalize_room

_NON_LATIN = re.compile(r"[^a-z0-9]+")


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


def _slug_part(s: str) -> str:
    s = s.strip().lower()
    # Latin letters and digits only in slug; other chars dropped
    s = re.sub(r"[^a-z0-9]+", "", s, flags=re.ASCII)
    if not s:
        s = "user"
    return s[:14]
