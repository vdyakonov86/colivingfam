import html

from vpn_bot.db import Resident


def format_residents_list(residents: list[tuple[str, Resident]]) -> str:
    """Форматирует список жителей для вывода."""
    if not residents:
        return "📭 Список жителей пуст."

    lines = ["📋 <b>Список жителей</b>"]
    current_room = None
    for room_number, r in residents:
        if room_number != current_room:
            current_room = room_number
            lines.append(f"\n🚪 <b>Комната {room_number}</b>")
        
        # Формируем строку с информацией о жителе
        line = f"<b>{html.escape(r.first_name)}</b>"
        tg = "не привязан"
        if r.telegram_user_id:
            tg = f"<a href='https://t.me/{html.escape(r.telegram_username)}'>@{html.escape(r.telegram_username)}</a>"

        lines.append(f"• <b>{html.escape(r.first_name)}</b> — {tg}")
    return "\n".join(lines)