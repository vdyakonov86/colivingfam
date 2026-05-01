from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Sequence
import json
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
    room_id: int
    telegram_user_id: int | None
    xui_email: str
    xui_uuid: str
    xui_sub_id: str
    created_at: int


@dataclass
class Room:
    id: int
    room_number: str
    max_residents: int
    created_at: int

@dataclass
class LinkCode:
    code: str
    resident_id: int
    expires_at: int


class Database:
    def __init__(self, path: str, seed_rooms_path: str) -> None:
        self.path = path
        self.seed_rooms_path = seed_rooms_path

    async def connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT UNIQUE NOT NULL,  
                    max_residents INTEGER NOT NULL,  
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS residents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    room_id INTEGER NOT NULL,
                    telegram_user_id INTEGER UNIQUE,
                    xui_email TEXT NOT NULL UNIQUE,
                    xui_uuid TEXT NOT NULL UNIQUE,
                    xui_sub_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_residents_room_id ON residents(room_id);

                CREATE TABLE IF NOT EXISTS link_codes (
                    code TEXT PRIMARY KEY,
                    resident_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    FOREIGN KEY (resident_id) REFERENCES residents(id) ON DELETE CASCADE
                );
                """
            )
            await db.commit()

        await self.seed_rooms_from_json(self.seed_rooms_path)

    async def count_residents(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM residents")
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def add_resident(
        self,
        first_name: str,
        last_name: str,
        room_number: str,
        xui_email: str,
        xui_uuid: str,
        xui_sub_id: str,
    ) -> int:
        room_number = normalize_room(room_number)
        room_id = await self.get_room_id_by_room_number(room_number)
        if room_id is None:
            raise ValueError("Комната не найдена")

        now = int(time.time())
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO residents (first_name, last_name, room_id, telegram_user_id, xui_email, xui_uuid, xui_sub_id, created_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (first_name.strip(), last_name.strip(), room_id, xui_email, xui_uuid, xui_sub_id, now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def get_room_id_by_room_number(self, room_number: str) -> int | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id FROM rooms WHERE room_number = ?", (room_number,))
            row = await cur.fetchone()
            return int(row["id"]) if row else None

    async def delete_resident(self, resident_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM residents WHERE id = ?", (resident_id,))
            await db.commit()

    async def get_resident_by_id(self, resident_id: int) -> Resident | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM residents WHERE id = ?", (resident_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return _row_to_resident(row)

    async def get_resident_with_room_by_id(self, resident_id: int) -> tuple[Resident, str] | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """SELECT residents.*, rooms.room_number FROM residents
                JOIN rooms ON residents.room_id = rooms.id
                WHERE residents.id = ?
                """, (resident_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return _row_to_resident(row), str(row["room_number"])

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
                SELECT residents.* 
                FROM residents 
                JOIN rooms ON residents.room_id = rooms.id 
                ORDER BY 
                    CAST(SUBSTR(rooms.room_number, 2) AS INTEGER),
                    residents.last_name COLLATE NOCASE,
                    residents.first_name COLLATE NOCASE
                """
            )
            rows: Sequence[Any] = await cur.fetchall()
            return [_row_to_resident(r) for r in rows]

    async def list_residents_grouped_with_room(self) -> list[tuple[str, Resident]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT rooms.room_number, residents.*
                FROM residents
                JOIN rooms ON residents.room_id = rooms.id
                ORDER BY
                    CAST(SUBSTR(rooms.room_number, 2) AS INTEGER),
                    residents.last_name COLLATE NOCASE,
                    residents.first_name COLLATE NOCASE
                """
            )
            rows = await cur.fetchall()
            result = []
            for row in rows:
                room_number = str(row["room_number"])
                # Поле room_number в _row_to_resident игнорируется, так как его нет в датаклассе.
                resident = _row_to_resident(row)
                result.append((room_number, resident))
            return result

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
            
    async def seed_rooms_from_json(self, json_path: str) -> None:
        with open(json_path) as f:
            data = json.load(f)
        async with aiosqlite.connect(self.path) as db:
            for room in data["rooms"]:
                await db.execute(
                    "INSERT OR IGNORE INTO rooms (room_number, max_residents, created_at) VALUES (?, ?, ?)",
                    (room["room_number"], room.get("max_residents"), int(time.time()))
                )
            await db.commit()
            
def _row_to_resident(row: aiosqlite.Row) -> Resident:
    return Resident(
        id=int(row["id"]),
        first_name=str(row["first_name"]),
        last_name=str(row["last_name"]),
        room_id=int(row["room_id"]),
        telegram_user_id=int(row["telegram_user_id"]) if row["telegram_user_id"] is not None else None,
        xui_email=str(row["xui_email"]),
        xui_uuid=str(row["xui_uuid"]),
        xui_sub_id=str(row["xui_sub_id"]),
        created_at=int(row["created_at"]),
    )