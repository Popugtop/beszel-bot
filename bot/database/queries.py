"""SQL-запросы для работы с базой данных."""

import json
import logging
from typing import Any
import aiosqlite

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User Settings
# ---------------------------------------------------------------------------

async def get_user_settings(conn: aiosqlite.Connection, user_id: int) -> dict[str, Any]:
    """Возвращает настройки пользователя, создаёт запись по умолчанию если нет."""
    async with conn.execute(
        "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        await conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,)
        )
        await conn.commit()
        async with conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

    return dict(row)


async def update_user_settings(conn: aiosqlite.Connection, user_id: int, **kwargs: Any) -> None:
    """Обновляет указанные поля настроек пользователя."""
    if not kwargs:
        return

    # Убеждаемся что запись существует
    await get_user_settings(conn, user_id)

    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    set_clause += ", updated_at = datetime('now')"
    values = list(kwargs.values()) + [user_id]

    await conn.execute(
        f"UPDATE user_settings SET {set_clause} WHERE user_id = ?", values
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Muted Nodes
# ---------------------------------------------------------------------------

async def get_muted_node_ids(conn: aiosqlite.Connection, user_id: int) -> set[str]:
    """Возвращает множество ID замьюченных нод пользователя."""
    async with conn.execute(
        "SELECT node_id FROM muted_nodes WHERE user_id = ?", (user_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    return {row["node_id"] for row in rows}


async def get_muted_nodes(conn: aiosqlite.Connection, user_id: int) -> list[dict]:
    """Возвращает список замьюченных нод с именами."""
    async with conn.execute(
        "SELECT node_id, node_name, muted_at FROM muted_nodes WHERE user_id = ? ORDER BY node_name",
        (user_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def mute_node(conn: aiosqlite.Connection, user_id: int, node_id: str, node_name: str) -> None:
    """Добавляет ноду в список замьюченных."""
    await conn.execute(
        "INSERT OR REPLACE INTO muted_nodes (user_id, node_id, node_name) VALUES (?, ?, ?)",
        (user_id, node_id, node_name)
    )
    await conn.commit()


async def unmute_node(conn: aiosqlite.Connection, user_id: int, node_id: str) -> None:
    """Убирает ноду из замьюченных."""
    await conn.execute(
        "DELETE FROM muted_nodes WHERE user_id = ? AND node_id = ?", (user_id, node_id)
    )
    await conn.commit()


async def is_node_muted(conn: aiosqlite.Connection, user_id: int, node_id: str) -> bool:
    """Проверяет, замьючена ли нода для пользователя."""
    async with conn.execute(
        "SELECT 1 FROM muted_nodes WHERE user_id = ? AND node_id = ?", (user_id, node_id)
    ) as cursor:
        return await cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Alert History
# ---------------------------------------------------------------------------

async def add_alert(
    conn: aiosqlite.Connection,
    user_id: int,
    node_id: str | None,
    node_name: str | None,
    event_type: str,
    message: str,
) -> None:
    """Записывает алерт в историю."""
    await conn.execute(
        """INSERT INTO alert_history (user_id, node_id, node_name, event_type, message)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, node_id, node_name, event_type, message)
    )
    await conn.commit()


async def get_alert_history(
    conn: aiosqlite.Connection,
    user_id: int,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    """Возвращает историю алертов с пагинацией."""
    async with conn.execute(
        """SELECT id, node_name, event_type, message, created_at
           FROM alert_history
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (user_id, limit, offset)
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def count_alerts(conn: aiosqlite.Connection, user_id: int) -> int:
    """Считает общее количество алертов пользователя."""
    async with conn.execute(
        "SELECT COUNT(*) FROM alert_history WHERE user_id = ?", (user_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_last_alert_time(
    conn: aiosqlite.Connection,
    user_id: int,
    node_id: str,
    event_type: str,
) -> str | None:
    """Возвращает время последнего алерта для ноды и типа события (для cooldown)."""
    async with conn.execute(
        """SELECT created_at FROM alert_history
           WHERE user_id = ? AND node_id = ? AND event_type = ?
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, node_id, event_type)
    ) as cursor:
        row = await cursor.fetchone()
    return row["created_at"] if row else None


async def get_alerts_last_24h(conn: aiosqlite.Connection, user_id: int) -> list[dict]:
    """Алерты за последние 24 часа (для дайджеста)."""
    async with conn.execute(
        """SELECT node_name, event_type, created_at
           FROM alert_history
           WHERE user_id = ? AND created_at >= datetime('now', '-24 hours')
           ORDER BY created_at DESC""",
        (user_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Node States
# ---------------------------------------------------------------------------

async def get_all_node_states(conn: aiosqlite.Connection) -> dict[str, dict]:
    """Возвращает все состояния нод как словарь {node_id: state_dict}."""
    async with conn.execute("SELECT * FROM node_states") as cursor:
        rows = await cursor.fetchall()

    result = {}
    for row in rows:
        d = dict(row)
        if d.get("info_json"):
            try:
                d["info"] = json.loads(d["info_json"])
            except json.JSONDecodeError:
                d["info"] = {}
        else:
            d["info"] = {}
        result[d["node_id"]] = d
    return result


async def upsert_node_state(
    conn: aiosqlite.Connection,
    node_id: str,
    node_name: str,
    status: str,
    host: str,
    info_json: str,
) -> None:
    """Обновляет или создаёт состояние ноды."""
    await conn.execute(
        """INSERT INTO node_states (node_id, node_name, status, host, info_json, last_seen, first_seen, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), datetime('now'))
           ON CONFLICT(node_id) DO UPDATE SET
               node_name = excluded.node_name,
               status = excluded.status,
               host = excluded.host,
               info_json = excluded.info_json,
               last_seen = excluded.last_seen,
               updated_at = excluded.updated_at""",
        (node_id, node_name, status, host, info_json)
    )
    await conn.commit()


async def delete_node_state(conn: aiosqlite.Connection, node_id: str) -> None:
    """Удаляет состояние ноды из базы."""
    await conn.execute("DELETE FROM node_states WHERE node_id = ?", (node_id,))
    await conn.commit()


async def get_node_state(conn: aiosqlite.Connection, node_id: str) -> dict | None:
    """Возвращает состояние конкретной ноды."""
    async with conn.execute(
        "SELECT * FROM node_states WHERE node_id = ?", (node_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        return None

    d = dict(row)
    if d.get("info_json"):
        try:
            d["info"] = json.loads(d["info_json"])
        except json.JSONDecodeError:
            d["info"] = {}
    else:
        d["info"] = {}
    return d


async def get_all_admin_user_ids(conn: aiosqlite.Connection) -> list[int]:
    """Возвращает всех пользователей у которых есть настройки."""
    async with conn.execute("SELECT user_id FROM user_settings") as cursor:
        rows = await cursor.fetchall()
    return [row["user_id"] for row in rows]
