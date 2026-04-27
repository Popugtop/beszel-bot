"""Административные команды: статистика, управление."""

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.database import queries as q
from bot.database.db import Database
from bot.keyboards.inline import main_menu_kb
from bot.services.beszel_client import BeszelClient, BeszelAPIError
from bot.services.monitor import Monitor
from bot.utils.formatting import now_in_tz

logger = logging.getLogger(__name__)
router = Router(name="admin")


@router.message(Command("admin"))
async def cmd_admin(message: Message, monitor: Monitor, db: Database, tz: str) -> None:
    """Команда /admin — расширенная информация об инфраструктуре."""
    nodes = monitor.get_current_nodes()
    up = [n for n in nodes if n.get("status") == "up"]
    down = [n for n in nodes if n.get("status") == "down"]
    paused = [n for n in nodes if n.get("status") == "paused"]

    total = len(nodes)
    uptime_pct = (len(up) / total * 100) if total > 0 else 0

    now = now_in_tz(tz).strftime("%Y-%m-%d %H:%M:%S")
    hub_str = "✅ Доступен" if monitor.is_hub_available else "⚠️ Недоступен"
    init_str = "✅ Да" if monitor.is_initialized else "⏳ Нет"

    # Количество алертов за сегодня у всех пользователей
    all_users = await q.get_all_admin_user_ids(db.conn)

    text = (
        f"🔧 <b>Административная панель</b>\n\n"
        f"🕐 Время: {now}\n"
        f"🔌 Hub: {hub_str}\n"
        f"🔄 Инициализирован: {init_str}\n\n"
        f"<b>Статистика нод:</b>\n"
        f"  Всего: {total}\n"
        f"  🟢 Онлайн: {len(up)} ({uptime_pct:.1f}%)\n"
        f"  🔴 Оффлайн: {len(down)}\n"
        f"  ⏸ Пауза: {len(paused)}\n\n"
        f"<b>Пользователи в системе:</b> {len(all_users)}\n"
    )

    if down:
        text += "\n<b>Упавшие ноды:</b>\n"
        for node in down[:10]:
            name = node.get("node_name", "?")
            host = node.get("host", "?")
            text += f"  🔴 <code>{name}</code> ({host})\n"
        if len(down) > 10:
            text += f"  ... и ещё {len(down) - 10}\n"

    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.message(Command("nodes"))
async def cmd_nodes(message: Message, monitor: Monitor) -> None:
    """Команда /nodes — текстовый список всех нод."""
    nodes = monitor.get_current_nodes()
    if not nodes:
        await message.answer("Нет данных о нодах. Мониторинг ещё не запущен.")
        return

    nodes_sorted = sorted(nodes, key=lambda n: (
        {"down": 0, "paused": 1, "up": 2}.get(n.get("status", ""), 3),
        n.get("node_name", "")
    ))

    icons = {"up": "🟢", "down": "🔴", "paused": "⏸"}
    lines = ["<b>Все ноды:</b>\n"]
    for node in nodes_sorted:
        status = node.get("status", "?")
        icon = icons.get(status, "❓")
        name = node.get("node_name", "?")
        host = node.get("host", "?")
        lines.append(f"{icon} <code>{name}</code> — {host}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "history:clear:confirm")
async def cb_history_clear_confirm(callback: CallbackQuery) -> None:
    """Запрос подтверждения очистки истории алертов."""
    from bot.keyboards.inline import history_clear_confirm_kb
    await callback.message.edit_text(
        "⚠️ <b>Очистить историю алертов?</b>\n\nЭто действие необратимо.",
        reply_markup=history_clear_confirm_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "history:clear:do")
async def cb_history_clear_do(callback: CallbackQuery, db: Database) -> None:
    """Очищает историю алертов пользователя."""
    user_id = callback.from_user.id
    await db.conn.execute(
        "DELETE FROM alert_history WHERE user_id = ?", (user_id,)
    )
    await db.conn.commit()

    await callback.message.edit_text(
        "✅ История алертов очищена.",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer("История очищена")
