import html

from vpn_bot.db import Resident


def format_residents_list(residents: list[tuple[str, Resident]]) -> str:
    if not residents:
        return "📭 Список жителей пуст."
    lines = ["📋 <b>Список жителей</b>"]
    current_room = None
    for room_number, r in residents:
        if room_number != current_room:
            current_room = room_number
            lines.append(f"\n🚪 <b>Комната {room_number}</b>")
        tg = f"tg: <code>{r.telegram_user_id}</code>" if r.telegram_user_id else "не привязан"
        lines.append(
            f"• {html.escape(r.first_name)} — {tg}"
        )
        # lines.append(f"• {html.escape(r.last_name)} {html.escape(r.first_name)} (id: {r.id})")
    return "\n".join(lines)