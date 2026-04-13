import html

from vpn_bot.db import Resident


def format_residents_list(residents: list[Resident]) -> str:
    if not residents:
        return "Жителей пока нет."
    lines: list[str] = []
    current_room: str | None = None
    for r in residents:
        if r.room != current_room:
            current_room = r.room
            lines.append(f"\n<b>{current_room}</b>")
        tg = f"TG: <code>{r.telegram_user_id}</code>" if r.telegram_user_id else "не привязан"
        lines.append(
            f"• <code>{r.id}</code> — {html.escape(r.last_name)} {html.escape(r.first_name)} — {tg}"
        )
    return "\n".join(lines).strip()
