#!/usr/bin/env python3
"""
Заполняет таблицу rooms из JSON-файла.
Использование: python seed_rooms.py --db /path/to/database.db --json rooms_seed.json
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Seed rooms table from JSON")
    parser.add_argument("--db", required=True, help="Path to SQLite database file")
    parser.add_argument("--json", required=True, help="Path to JSON configuration file")
    args = parser.parse_args()

    db_path = Path(args.db)
    json_path = Path(args.json)

    if not db_path.exists():
        print(f"❌ Database file not found: {db_path}")
        sys.exit(1)

    if not json_path.exists():
        print(f"❌ JSON file not found: {json_path}")
        sys.exit(1)

    # Загрузка конфигурации
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load JSON: {e}")
        sys.exit(1)

    rooms = config.get("rooms", [])
    if not rooms:
        print("⚠️ No rooms defined in JSON, nothing to do.")
        return

    # Подключение к БД
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Проверим, существует ли таблица rooms
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rooms'")
    if not cursor.fetchone():
        print("❌ Table 'rooms' does not exist. Please run migrations first.")
        sys.exit(1)

    current_ts = int(time.time())  # created_at — Unix timestamp
    inserted = 0
    skipped = 0

    for room in rooms:
        room_number = room.get("room_number")
        max_residents = room.get("max_residents", 4)

        if not room_number:
            print("⚠️ Skipping entry without 'room_number'")
            skipped += 1
            continue

        try:
            # Используем INSERT OR IGNORE, чтобы не нарушать уникальность комнаты
            cursor.execute(
                """
                INSERT OR IGNORE INTO rooms (room_number, max_residents, created_at)
                VALUES (?, ?, ?)
                """,
                (room_number, max_residents, current_ts)
            )
            if cursor.rowcount == 1:
                inserted += 1
                print(f"✅ Added room: {room_number} (max: {max_residents})")
            else:
                print(f"⏩ Room {room_number} already exists, skipped.")
                skipped += 1
        except Exception as e:
            print(f"❌ Error inserting room {room_number}: {e}")

    conn.commit()
    conn.close()

    print(f"\n✨ Done. Inserted: {inserted}, Skipped: {skipped}")

if __name__ == "__main__":
    main()