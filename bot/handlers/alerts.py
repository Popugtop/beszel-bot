"""Обработчики настроек алертов и управления мьютом нод."""

import logging
import re

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.database import queries as q
from bot.database.db import Database
from bot.keyboards.inline import (
    alert_settings_kb,
    muted_nodes_kb,
    quiet_hours_cancel_kb,
    cooldown_cancel_kb,
    back_to_main_kb,
)
from bot.services.monitor import Monitor

logger = logging.getLogger(__name__)
router = Router(name="alerts")

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class AlertFSM(StatesGroup):
    """FSM-состояния для ввода настроек алертов."""
    waiting_quiet_start = State()
    waiting_quiet_end = State()
    waiting_cooldown = State()


async def _show_alert_settings(
    target: CallbackQuery | Message,
    db: Database,
    user_id: int,
) -> None:
    """Отображает экран настроек алертов."""
    settings = await q.get_user_settings(db.conn, user_id)
    text = (
        "🔔 <b>Настройки алертов</b>\n\n"
        "Выберите параметр для изменения:"
    )
    kb = alert_settings_kb(settings)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "menu:alerts")
async def cb_menu_alerts(callback: CallbackQuery, db: Database) -> None:
    """Переход на экран настроек алертов."""
    await _show_alert_settings(callback, db, callback.from_user.id)


# ---------------------------------------------------------------------------
# Toggle алертов
# ---------------------------------------------------------------------------

TOGGLE_FIELDS = {
    "down": "alert_on_down",
    "up": "alert_on_up",
    "hub": "alert_on_hub_down",
    "new": "alert_on_new_node",
    "removed": "alert_on_removed_node",
}


@router.callback_query(F.data.startswith("alert:toggle:"))
async def cb_alert_toggle(callback: CallbackQuery, db: Database) -> None:
    """Переключает включение/выключение определённого типа алертов."""
    kind = callback.data.split(":", 2)[2]
    field = TOGGLE_FIELDS.get(kind)

    if not field:
        await callback.answer("Неизвестный тип алерта", show_alert=True)
        return

    user_id = callback.from_user.id
    settings = await q.get_user_settings(db.conn, user_id)
    current = settings.get(field, 1)
    new_value = 0 if current else 1

    await q.update_user_settings(db.conn, user_id, **{field: new_value})
    await _show_alert_settings(callback, db, user_id)


# ---------------------------------------------------------------------------
# Тихие часы
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "alert:quiet")
async def cb_alert_quiet(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Начало настройки тихих часов."""
    user_id = callback.from_user.id
    settings = await q.get_user_settings(db.conn, user_id)
    start = settings.get("quiet_hours_start") or "не задано"
    end = settings.get("quiet_hours_end") or "не задано"

    text = (
        f"🕐 <b>Тихие часы</b>\n\n"
        f"Текущий период: <b>{start} – {end}</b>\n\n"
        f"Введите время <b>начала</b> тихих часов в формате <code>HH:MM</code>:\n"
        f"(или <code>сброс</code> для отключения тихих часов)"
    )
    await callback.message.edit_text(text, reply_markup=quiet_hours_cancel_kb(), parse_mode="HTML")
    await state.set_state(AlertFSM.waiting_quiet_start)
    await callback.answer()


@router.callback_query(F.data == "alert:quiet:cancel")
async def cb_quiet_cancel(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Отмена ввода тихих часов."""
    await state.clear()
    await _show_alert_settings(callback, db, callback.from_user.id)


@router.message(AlertFSM.waiting_quiet_start)
async def fsm_quiet_start(message: Message, db: Database, state: FSMContext) -> None:
    """Обрабатывает ввод времени начала тихих часов."""
    text = message.text.strip() if message.text else ""

    if text.lower() in ("сброс", "reset", "0", "off"):
        await q.update_user_settings(
            db.conn, message.from_user.id,
            quiet_hours_start=None, quiet_hours_end=None
        )
        await state.clear()
        await message.answer(
            "✅ Тихие часы отключены",
            reply_markup=back_to_main_kb(),
            parse_mode="HTML",
        )
        return

    if not TIME_RE.match(text):
        await message.answer(
            "❌ Неверный формат. Введите время в формате <code>HH:MM</code>, например <code>23:00</code>",
            reply_markup=quiet_hours_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(quiet_start=text)
    await state.set_state(AlertFSM.waiting_quiet_end)
    await message.answer(
        f"Время начала: <b>{text}</b>\n\nТеперь введите время <b>окончания</b> тихих часов:",
        reply_markup=quiet_hours_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(AlertFSM.waiting_quiet_end)
async def fsm_quiet_end(message: Message, db: Database, state: FSMContext) -> None:
    """Обрабатывает ввод времени окончания тихих часов."""
    text = message.text.strip() if message.text else ""

    if not TIME_RE.match(text):
        await message.answer(
            "❌ Неверный формат. Введите время в формате <code>HH:MM</code>, например <code>07:00</code>",
            reply_markup=quiet_hours_cancel_kb(),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    start = data.get("quiet_start")

    await q.update_user_settings(
        db.conn, message.from_user.id,
        quiet_hours_start=start, quiet_hours_end=text
    )
    await state.clear()
    await message.answer(
        f"✅ Тихие часы установлены: <b>{start} – {text}</b>",
        reply_markup=back_to_main_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "alert:cooldown")
async def cb_alert_cooldown(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Начало настройки cooldown."""
    user_id = callback.from_user.id
    settings = await q.get_user_settings(db.conn, user_id)
    current = settings.get("alert_cooldown", 300)

    text = (
        f"⏱ <b>Cooldown между алертами</b>\n\n"
        f"Текущее значение: <b>{current} секунд</b>\n\n"
        f"Введите количество секунд (0 — без ограничений, максимум 86400):"
    )
    await callback.message.edit_text(text, reply_markup=cooldown_cancel_kb(), parse_mode="HTML")
    await state.set_state(AlertFSM.waiting_cooldown)
    await callback.answer()


@router.callback_query(F.data == "alert:cooldown:cancel")
async def cb_cooldown_cancel(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Отмена ввода cooldown."""
    await state.clear()
    await _show_alert_settings(callback, db, callback.from_user.id)


@router.message(AlertFSM.waiting_cooldown)
async def fsm_cooldown(message: Message, db: Database, state: FSMContext) -> None:
    """Обрабатывает ввод значения cooldown."""
    text = message.text.strip() if message.text else ""

    if not text.isdigit():
        await message.answer(
            "❌ Введите целое число секунд (например, <code>300</code>)",
            reply_markup=cooldown_cancel_kb(),
            parse_mode="HTML",
        )
        return

    value = int(text)
    if value > 86400:
        await message.answer(
            "❌ Максимальное значение — 86400 секунд (24 часа)",
            reply_markup=cooldown_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await q.update_user_settings(db.conn, message.from_user.id, alert_cooldown=value)
    await state.clear()
    await message.answer(
        f"✅ Cooldown установлен: <b>{value} секунд</b>",
        reply_markup=back_to_main_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Управление мьютом нод
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("alert:mutes:"))
async def cb_alert_mutes(
    callback: CallbackQuery,
    db: Database,
    monitor: Monitor,
) -> None:
    """Экран управления замьюченными нодами."""
    page = int(callback.data.split(":")[-1])
    user_id = callback.from_user.id

    nodes = monitor.get_current_nodes()
    nodes_sorted = sorted(nodes, key=lambda n: n.get("node_name", ""))
    muted_ids = await q.get_muted_node_ids(db.conn, user_id)

    if not nodes_sorted:
        await callback.answer("Нет нод для управления", show_alert=True)
        return

    text = (
        f"🔕 <b>Управление мьютом нод</b>\n\n"
        f"Замьюченные ноды не будут вызывать алерты.\n"
        f"Нажмите на ноду чтобы изменить статус:"
    )
    kb = muted_nodes_kb(nodes_sorted, muted_ids, page=page)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("alert:node:mute:"))
async def cb_node_mute_from_alerts(callback: CallbackQuery, db: Database, monitor: Monitor) -> None:
    """Мьютит ноду из экрана настроек алертов."""
    node_id = callback.data.split(":", 3)[3]
    user_id = callback.from_user.id

    node = monitor.get_node(node_id)
    node_name = node.get("node_name", "unknown") if node else "unknown"

    await q.mute_node(db.conn, user_id, node_id, node_name)

    # Перезагружаем экран мьютов
    nodes = monitor.get_current_nodes()
    nodes_sorted = sorted(nodes, key=lambda n: n.get("node_name", ""))
    muted_ids = await q.get_muted_node_ids(db.conn, user_id)

    await callback.message.edit_reply_markup(
        reply_markup=muted_nodes_kb(nodes_sorted, muted_ids, page=0)
    )
    await callback.answer(f"🔕 {node_name} замьючена")


@router.callback_query(F.data.startswith("alert:node:unmute:"))
async def cb_node_unmute_from_alerts(callback: CallbackQuery, db: Database, monitor: Monitor) -> None:
    """Размьютит ноду из экрана настроек алертов."""
    node_id = callback.data.split(":", 3)[3]
    user_id = callback.from_user.id

    node = monitor.get_node(node_id)
    node_name = node.get("node_name", "unknown") if node else "unknown"

    await q.unmute_node(db.conn, user_id, node_id)

    nodes = monitor.get_current_nodes()
    nodes_sorted = sorted(nodes, key=lambda n: n.get("node_name", ""))
    muted_ids = await q.get_muted_node_ids(db.conn, user_id)

    await callback.message.edit_reply_markup(
        reply_markup=muted_nodes_kb(nodes_sorted, muted_ids, page=0)
    )
    await callback.answer(f"🔔 {node_name} размьючена")
