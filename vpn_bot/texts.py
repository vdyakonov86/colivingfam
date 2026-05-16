import html

from vpn_bot.db import Resident

def place_title_from_name(place_name: str) -> str:
    return "Фонтанка" if place_name == "fontanka" else ("Невский" if place_name == "nevsky" else place_name)

def format_residents_list(residents: list[tuple[str, str, Resident]]) -> str:
    """
    residents: [(place_name, room_number, resident), ...]
    """
    if not residents:
        return "📭 Список жителей пуст."

    lines = ["📋 <b>Список жителей</b>"]

    current_place: str | None = None
    current_room: str | None = None

    for place_name, room_number, r in residents:
        if place_name != current_place:
            current_place = place_name
            current_room = None
            lines.append(f"\n🏠 <b>{html.escape(place_title_from_name(place_name))}</b>")

        if room_number != current_room:
            current_room = room_number
            lines.append(f"\n🚪 <b>Комната {html.escape(room_number)}</b>")

        tg = "не привязан"
        if r.telegram_user_id and r.telegram_username:
            username = html.escape(r.telegram_username)
            tg = f"<a href='https://t.me/{username}'>@{username}</a>"

        full_name = f"{r.first_name} {r.last_name}".strip()
        lines.append(f"• <b>{html.escape(full_name)}</b> — {tg}")

    return "\n".join(lines)