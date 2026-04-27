"""Обработчики истории алертов с пагинацией."""

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import queries as q
from bot.database.db import Database
from bot.keyboards.inline import history_kb
from bot.utils.formatting import get_event_icon

logger = logging.getLogger(__name__)
router = Router(name="history")

ITEMS_PER_PAGE = 10


@router.callback_query(F.data.startswith("menu:history:"))
async def cb_history(callback: CallbackQuery, db: Database, tz: str) -> None:
    """Отображает историю алертов с пагинацией."""
    page = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id

    total = await q.count_alerts(db.conn, user_id)
    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    alerts = await q.get_alert_history(
        db.conn, user_id,
        limit=ITEMS_PER_PAGE,
        offset=page * ITEMS_PER_PAGE,
    )

    if not alerts:
        text = "📜 <b>История алертов</b>\n\nИстория пуста."
    else:
        from bot.utils.formatting import format_datetime_tz
        lines = [f"📜 <b>История алертов</b> (стр. {page + 1}/{total_pages})\n"]
        for alert in alerts:
            icon = get_event_icon(alert.get("event_type", ""))
            name = alert.get("node_name") or "Hub"
            dt_raw = alert.get("created_at", "")
            dt_fmt = format_datetime_tz(dt_raw, tz)
            # Краткий формат: только время без даты если сегодня
            lines.append(f"{icon} [{dt_fmt}] {name}")
        text = "\n".join(lines)

    kb = history_kb(page, total_pages)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
