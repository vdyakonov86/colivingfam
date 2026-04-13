from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Sequence

import aiosqlite

ROOM_RE = re.compile(r"^F(1[0-2]|[1-9])$", re.IGNORECASE)


def normalize_room(room: str) -> str:
    r = room.strip().upper()
    if not ROOM_RE.match(r):
        raise ValueError("Комната должна быть F1–F12")
    return r


@dataclass
class Resident:
    id: int
    first_name: str
    last_name: str
    room: str
    telegram_user_id: int | None
    xui_email: str
    xui_client_id: str
    xui_sub_id: str
    created_at: int


@dataclass
class LinkCode:
    code: str
    resident_id: int
    expires_at: int


class Database:
    def __init__(self, path: str) -> None:
        self.path = path

    async def connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS residents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    room TEXT NOT NULL,
                    telegram_user_id INTEGER UNIQUE,
                    xui_email TEXT NOT NULL UNIQUE,
                    xui_client_id TEXT NOT NULL,
                    xui_sub_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS link_codes (
                    code TEXT PRIMARY KEY,
                    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_residents_room ON residents(room);
                """
            )
            await db.commit()

    async def count_residents(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM residents")
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def add_resident(
        self,
        first_name: str,
        last_name: str,
        room: str,
        xui_email: str,
        xui_client_id: str,
        xui_sub_id: str,
    ) -> int:
        room = normalize_room(room)
        now = int(time.time())
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO residents (first_name, last_name, room, telegram_user_id, xui_email, xui_client_id, xui_sub_id, created_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (first_name.strip(), last_name.strip(), room, xui_email, xui_client_id, xui_sub_id, now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def delete_resident(self, resident_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM residents WHERE id = ?", (resident_id,))
            await db.commit()

    async def get_resident(self, resident_id: int) -> Resident | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM residents WHERE id = ?", (resident_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return _row_to_resident(row)

    async def get_resident_by_telegram(self, telegram_user_id: int) -> Resident | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM residents WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None
            return _row_to_resident(row)

    async def list_residents_grouped(self) -> list[Resident]:
        """F1..F12 then last_name, first_name."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT * FROM residents
                ORDER BY
                  CAST(SUBSTR(room, 2) AS INTEGER),
                  last_name COLLATE NOCASE,
                  first_name COLLATE NOCASE
                """
            )
            rows: Sequence[Any] = await cur.fetchall()
            return [_row_to_resident(r) for r in rows]

    async def bind_telegram(self, resident_id: int, telegram_user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE residents SET telegram_user_id = ? WHERE id = ?",
                (telegram_user_id, resident_id),
            )
            await db.commit()

    async def unbind_telegram(self, resident_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE residents SET telegram_user_id = NULL WHERE id = ?",
                (resident_id,),
            )
            await db.commit()

    async def add_link_code(self, code: str, resident_id: int, expires_at: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM link_codes WHERE resident_id = ?", (resident_id,))
            await db.execute(
                "INSERT INTO link_codes (code, resident_id, expires_at) VALUES (?, ?, ?)",
                (code, resident_id, expires_at),
            )
            await db.commit()

    async def consume_link_code(self, code: str) -> LinkCode | None:
        now = int(time.time())
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM link_codes WHERE code = ?",
                (code.strip(),),
            )
            row = await cur.fetchone()
            if not row:
                return None
            if int(row["expires_at"]) < now:
                await db.execute("DELETE FROM link_codes WHERE code = ?", (code.strip(),))
                await db.commit()
                return None
            await db.execute("DELETE FROM link_codes WHERE code = ?", (code.strip(),))
            await db.commit()
            return LinkCode(
                code=str(row["code"]),
                resident_id=int(row["resident_id"]),
                expires_at=int(row["expires_at"]),
            )


def _row_to_resident(row: aiosqlite.Row) -> Resident:
    return Resident(
        id=int(row["id"]),
        first_name=str(row["first_name"]),
        last_name=str(row["last_name"]),
        room=str(row["room"]),
        telegram_user_id=int(row["telegram_user_id"]) if row["telegram_user_id"] is not None else None,
        xui_email=str(row["xui_email"]),
        xui_client_id=str(row["xui_client_id"]),
        xui_sub_id=str(row["xui_sub_id"]),
        created_at=int(row["created_at"]),
    )
