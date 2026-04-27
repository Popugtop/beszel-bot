"""Обработчики детального просмотра нод и метрик."""

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database import queries as q
from bot.database.db import Database
from bot.keyboards.inline import node_detail_kb, node_detail_muted_kb
from bot.services.beszel_client import BeszelClient, BeszelAPIError
from bot.services.monitor import Monitor
from bot.utils.formatting import (
    format_node_info,
    format_datetime_tz,
    get_status_icon,
)

logger = logging.getLogger(__name__)
router = Router(name="nodes")


async def _get_node_detail_text(
    node_id: str,
    client: BeszelClient,
    monitor: Monitor,
    tz: str,
) -> tuple[str, dict | None]:
    """Получает данные ноды и формирует текст.

    Returns:
        Кортеж (текст сообщения, данные ноды или None).
    """
    # Сначала пробуем получить актуальные данные с Beszel
    node = None
    try:
        node = await client.get_system(node_id)
    except BeszelAPIError as e:
        logger.warning("Не удалось получить данные ноды %s с Beszel: %s", node_id, e)
        # Откатываемся к кэшированным данным
        node = monitor.get_node(node_id)

    if not node:
        return "❌ Нода не найдена или данные недоступны.", None

    name = node.get("name") or node.get("node_name", "unknown")
    host = node.get("host", "—")
    status = node.get("status", "unknown")
    icon = get_status_icon(status)

    updated = node.get("updated") or node.get("updated_at", "")
    updated_fmt = format_datetime_tz(updated, tz) if updated else "—"

    first_seen = node.get("created") or node.get("first_seen", "")
    first_seen_fmt = format_datetime_tz(first_seen, tz) if first_seen else "—"

    info = node.get("info") or {}
    if isinstance(info, str):
        import json
        try:
            info = json.loads(info)
        except Exception:
            info = {}

    metrics = format_node_info(info)

    text = (
        f"📡 <b>Нода: {name}</b>\n\n"
        f"📛 Имя: <code>{name}</code>\n"
        f"🌐 Хост: <code>{host}</code>\n"
        f"📊 Статус: {icon} {status}\n"
        f"🕐 Обновлено: {updated_fmt}\n"
        f"📅 Первый раз: {first_seen_fmt}\n"
    )

    if metrics:
        text += f"\n<b>Метрики:</b>\n{metrics}\n"

    return text, node


@router.callback_query(F.data.startswith("node:view:"))
async def cb_node_view(
    callback: CallbackQuery,
    client: BeszelClient,
    monitor: Monitor,
    db: Database,
    tz: str,
) -> None:
    """Просмотр детальной информации о ноде."""
    node_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    text, node = await _get_node_detail_text(node_id, client, monitor, tz)

    is_muted = await q.is_node_muted(db.conn, user_id, node_id)

    # Определяем backкнопку — откуда пришли (все ноды)
    back_cb = "status:all"
    if node and node.get("status") == "down":
        back_cb = "status:offline"
    elif node and node.get("status") == "up":
        back_cb = "status:online"

    kb = node_detail_muted_kb(node_id, back_cb) if is_muted else node_detail_kb(node_id, back_cb)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("node:refresh:"))
async def cb_node_refresh(
    callback: CallbackQuery,
    client: BeszelClient,
    monitor: Monitor,
    db: Database,
    tz: str,
) -> None:
    """Обновление информации о ноде."""
    node_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    text, node = await _get_node_detail_text(node_id, client, monitor, tz)
    is_muted = await q.is_node_muted(db.conn, user_id, node_id)

    back_cb = "status:all"
    kb = node_detail_muted_kb(node_id, back_cb) if is_muted else node_detail_kb(node_id, back_cb)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("node:mute:"))
async def cb_node_mute(
    callback: CallbackQuery,
    monitor: Monitor,
    db: Database,
) -> None:
    """Замьютить ноду."""
    node_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    node = monitor.get_node(node_id)
    node_name = node.get("node_name", "unknown") if node else "unknown"

    await q.mute_node(db.conn, user_id, node_id, node_name)

    kb = node_detail_muted_kb(node_id, "status:all")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"🔕 Нода {node_name} замьючена")


@router.callback_query(F.data.startswith("node:unmute:"))
async def cb_node_unmute(
    callback: CallbackQuery,
    monitor: Monitor,
    db: Database,
) -> None:
    """Размьютить ноду."""
    node_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    node = monitor.get_node(node_id)
    node_name = node.get("node_name", "unknown") if node else "unknown"

    await q.unmute_node(db.conn, user_id, node_id)

    kb = node_detail_kb(node_id, "status:all")
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"🔔 Нода {node_name} размьючена")
