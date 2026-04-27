"""Обработчики статуса нод: сводка, списки, обновление."""

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import status_menu_kb, nodes_list_kb, main_menu_kb
from bot.services.monitor import Monitor
from bot.utils.formatting import now_in_tz

logger = logging.getLogger(__name__)
router = Router(name="status")


def _build_status_text(nodes: list[dict], tz: str, hub_available: bool) -> str:
    """Формирует текст сводки статусов нод."""
    up = [n for n in nodes if n.get("status") == "up"]
    down = [n for n in nodes if n.get("status") == "down"]
    paused = [n for n in nodes if n.get("status") == "paused"]

    hub_str = "✅ Доступен" if hub_available else "⚠️ Недоступен"
    now = now_in_tz(tz).strftime("%H:%M:%S")

    text = (
        f"📊 <b>Статус нод</b>\n\n"
        f"🟢 Онлайн: <b>{len(up)}</b>\n"
        f"🔴 Оффлайн: <b>{len(down)}</b>\n"
        f"⏸ Приостановлено: <b>{len(paused)}</b>\n\n"
        f"🔌 Hub: {hub_str}\n"
        f"🕐 Обновлено: {now}"
    )
    return text


async def _show_status(target: Message | CallbackQuery, monitor: Monitor, tz: str) -> None:
    """Показывает сводку статусов. Работает и с Message, и с CallbackQuery."""
    nodes = monitor.get_current_nodes()

    if not monitor.is_initialized:
        text = "⏳ Мониторинг ещё не инициализирован. Подождите первого цикла опроса."
        kb = main_menu_kb()
    else:
        up = [n for n in nodes if n.get("status") == "up"]
        down = [n for n in nodes if n.get("status") == "down"]
        paused = [n for n in nodes if n.get("status") == "paused"]
        text = _build_status_text(nodes, tz, monitor.is_hub_available)
        kb = status_menu_kb(len(up), len(down), len(paused))

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("status"))
async def cmd_status(message: Message, monitor: Monitor, tz: str) -> None:
    """Команда /status — показывает сводку статусов нод."""
    await _show_status(message, monitor, tz)


@router.callback_query(F.data == "menu:status")
async def cb_menu_status(callback: CallbackQuery, monitor: Monitor, tz: str) -> None:
    """Переход на экран статуса из главного меню."""
    await _show_status(callback, monitor, tz)


@router.callback_query(F.data == "status:refresh")
async def cb_status_refresh(callback: CallbackQuery, monitor: Monitor, tz: str) -> None:
    """Обновление сводки статусов."""
    await _show_status(callback, monitor, tz)


@router.callback_query(F.data == "status:online")
async def cb_status_online(callback: CallbackQuery, monitor: Monitor) -> None:
    """Список онлайн нод."""
    nodes = monitor.get_current_nodes()
    online = [n for n in nodes if n.get("status") == "up"]

    if not online:
        await callback.answer("Нет онлайн нод", show_alert=True)
        return

    text = f"🟢 <b>Онлайн ноды ({len(online)})</b>"
    await callback.message.edit_text(
        text,
        reply_markup=nodes_list_kb(online, back_cb="status:refresh"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "status:offline")
async def cb_status_offline(callback: CallbackQuery, monitor: Monitor) -> None:
    """Список оффлайн нод."""
    nodes = monitor.get_current_nodes()
    offline = [n for n in nodes if n.get("status") == "down"]

    if not offline:
        await callback.answer("Нет упавших нод ✅", show_alert=True)
        return

    text = f"🔴 <b>Оффлайн ноды ({len(offline)})</b>"
    await callback.message.edit_text(
        text,
        reply_markup=nodes_list_kb(offline, back_cb="status:refresh"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "status:all")
async def cb_status_all(callback: CallbackQuery, monitor: Monitor) -> None:
    """Список всех нод."""
    nodes = monitor.get_current_nodes()
    nodes_sorted = sorted(nodes, key=lambda n: (
        {"down": 0, "paused": 1, "up": 2}.get(n.get("status", ""), 3),
        n.get("node_name", "")
    ))

    if not nodes_sorted:
        await callback.answer("Нет данных о нодах", show_alert=True)
        return

    text = f"📋 <b>Все ноды ({len(nodes_sorted)})</b>"
    await callback.message.edit_text(
        text,
        reply_markup=nodes_list_kb(nodes_sorted, back_cb="status:refresh"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    from bot.handlers.start import WELCOME_TEXT
    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    """Пустой обработчик для кнопок-заглушек (пагинация и т.п.)."""
    await callback.answer()
