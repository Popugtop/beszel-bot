"""Инициализация базы данных SQLite и управление подключением."""

import logging
import aiosqlite

logger = logging.getLogger(__name__)

# DDL для создания таблиц
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    alert_on_down INTEGER DEFAULT 1,
    alert_on_up INTEGER DEFAULT 1,
    alert_on_hub_down INTEGER DEFAULT 1,
    alert_on_new_node INTEGER DEFAULT 1,
    alert_on_removed_node INTEGER DEFAULT 1,
    quiet_hours_start TEXT DEFAULT NULL,
    quiet_hours_end TEXT DEFAULT NULL,
    alert_cooldown INTEGER DEFAULT 300,
    daily_digest INTEGER DEFAULT 0,
    daily_digest_time TEXT DEFAULT '09:00',
    last_digest_date TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS muted_nodes (
    user_id INTEGER,
    node_id TEXT,
    node_name TEXT,
    muted_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, node_id)
);

CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    node_id TEXT,
    node_name TEXT,
    event_type TEXT,
    message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS node_states (
    node_id TEXT PRIMARY KEY,
    node_name TEXT,
    status TEXT,
    host TEXT,
    info_json TEXT,
    last_seen TEXT,
    first_seen TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

# Индексы для ускорения частых запросов
CREATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_alert_history_user ON alert_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_history_node ON alert_history(user_id, node_id, event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_node_states_status ON node_states(status);
"""


class Database:
    """Обёртка над aiosqlite для управления соединением и миграциями."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Открывает соединение и инициализирует схему."""
        logger.info("Подключение к базе данных: %s", self._db_path)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row

        # Включаем WAL для лучшей конкурентности
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        await self._run_migrations()
        logger.info("База данных инициализирована")

    async def _run_migrations(self) -> None:
        """Создаёт таблицы и применяет миграции."""
        await self._conn.executescript(CREATE_TABLES_SQL)
        await self._conn.executescript(CREATE_INDEXES_SQL)
        await self._conn.commit()

    async def close(self) -> None:
        """Закрывает соединение с базой данных."""
        if self._conn:
            await self._conn.close()
            logger.info("Соединение с БД закрыто")

    @property
    def conn(self) -> aiosqlite.Connection:
        """Возвращает активное соединение."""
        if self._conn is None:
            raise RuntimeError("База данных не подключена. Вызовите connect() сначала.")
        return self._conn
