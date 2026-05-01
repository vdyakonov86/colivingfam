import html

from vpn_bot.db import Resident


def format_residents_list(residents: list[tuple[str, Resident]]) -> str:
    if not residents:
        return "Жителей пока нет."
    lines: list[str] = []
    current_room: str | None = None
    for (room_number, r) in residents:
        if room_number != current_room:
            current_room = room_number
            lines.append(f"\n<b>{current_room}</b>")
        tg = f"TG: <code>{r.telegram_user_id}</code>" if r.telegram_user_id else "не привязан"
        lines.append(
            f"• {html.escape(r.last_name)} {html.escape(r.first_name)} — {tg}"
        )
    return "\n".join(lines).strip()
