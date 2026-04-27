"""Realtime-мониторинг нод через PocketBase SSE.

Жизненный цикл:
    1. Старт → REST-синхронизация текущего состояния (без алертов)
    2. Подписка на SSE events систем (systems/*)
    3. При create/update/delete → немедленный алерт
    4. При обрыве → реконнект через SSE_RECONNECT_SECONDS
    5. После реконнекта → REST-синхронизация (с алертами за пропущенное время)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from bot.database import queries as q
from bot.database.db import Database
from bot.services.beszel_client import BeszelClient, BeszelAPIError, BeszelAuthError
from bot.services.notifier import Notifier

logger = logging.getLogger(__name__)


class Monitor:
    """Event-driven мониторинг через PocketBase Realtime SSE."""

    def __init__(
        self,
        client: BeszelClient,
        db: Database,
        notifier: Notifier,
        reconnect_seconds: int = 5,
    ) -> None:
        self._client = client
        self._db = db
        self._notifier = notifier
        self._reconnect_seconds = reconnect_seconds

        # Текущие состояния нод в памяти: {node_id: normalized_dict}
        self._current_states: dict[str, dict] = {}

        # True после первой успешной REST-синхронизации
        self._initialized = False

        # Текущий статус Hub
        self._hub_available: bool | None = None

        # Флаг остановки (выставляется при shutdown)
        self._stop_event = asyncio.Event()

        # Задача SSE-слушателя
        self._listener_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Публичный интерфейс
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запускает SSE-слушатель как фоновую asyncio-задачу."""
        self._stop_event.clear()
        self._listener_task = asyncio.create_task(
            self._sse_loop(), name="beszel-sse-listener"
        )
        logger.info("SSE мониторинг запущен")

    async def stop(self) -> None:
        """Останавливает SSE-слушатель."""
        self._stop_event.set()
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        logger.info("SSE мониторинг остановлен")

    async def initialize_from_db(self) -> None:
        """Загружает последние известные состояния нод из SQLite при старте."""
        db_states = await q.get_all_node_states(self._db.conn)
        self._current_states = db_states
        logger.info("Загружено %d состояний нод из БД", len(db_states))

    def get_current_nodes(self) -> list[dict]:
        """Возвращает текущий список нод из памяти."""
        return list(self._current_states.values())

    def get_node(self, node_id: str) -> dict | None:
        """Возвращает данные конкретной ноды из памяти."""
        return self._current_states.get(node_id)

    @property
    def is_hub_available(self) -> bool:
        return self._hub_available is True

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # SSE основной цикл
    # ------------------------------------------------------------------

    async def _sse_loop(self) -> None:
        """Основной цикл: подключение к SSE с автоматическим реконнектом."""
        first_attempt = True

        while not self._stop_event.is_set():
            try:
                if not first_attempt:
                    logger.info(
                        "Реконнект к Beszel SSE через %ds...",
                        self._reconnect_seconds,
                    )
                    await asyncio.sleep(self._reconnect_seconds)

                first_attempt = False
                await self._connect_and_process()

            except asyncio.CancelledError:
                logger.info("SSE listener отменён")
                return
            except (BeszelAuthError, BeszelAPIError) as e:
                await self._on_hub_unavailable()
                logger.error("SSE ошибка: %s", e)
            except Exception as e:
                await self._on_hub_unavailable()
                logger.error("Непредвиденная SSE ошибка: %s", e, exc_info=True)

    async def _connect_and_process(self) -> None:
        """Один цикл: REST-синхронизация + SSE-подписка + обработка событий."""
        # 1. Сначала REST-синхронизация чтобы иметь актуальный baseline
        #    перед тем как подпишемся на SSE
        await self._rest_sync()

        # 2. Помечаем Hub как доступный
        await self._on_hub_available()

        # 3. Читаем SSE события
        logger.info("Подключение к PocketBase Realtime SSE...")
        async for action, record in self._client.realtime_listen(self._stop_event):
            if self._stop_event.is_set():
                return
            await self._handle_sse_event(action, record)

        # Если генератор завершился без исключения — соединение просто закрылось
        if not self._stop_event.is_set():
            logger.warning("SSE соединение закрыто сервером")

    # ------------------------------------------------------------------
    # REST-синхронизация
    # ------------------------------------------------------------------

    async def _rest_sync(self) -> None:
        """Запрашивает текущее состояние всех нод через REST API.

        При первом запуске: сохраняет состояние, алерты не отправляет.
        При реконнекте: сравнивает с предыдущим состоянием, алерты отправляет.
        """
        logger.info("REST-синхронизация состояний нод...")

        try:
            systems = await self._client.get_systems()
        except BeszelAPIError as e:
            raise BeszelAPIError(f"REST sync failed: {e}") from e

        new_states = {s["id"]: s for s in systems}

        if not self._initialized:
            # Первый старт — просто сохраняем базовое состояние
            await self._save_states(new_states)
            self._current_states = {
                nid: self._normalize(n) for nid, n in new_states.items()
            }
            self._initialized = True
            logger.info(
                "Первичная синхронизация: %d нод. Мониторинг активен.",
                len(new_states),
            )
            return

        # Реконнект — выявляем изменения, которые произошли пока были офлайн
        events = self._diff_states(new_states)
        await self._save_states(new_states)
        self._current_states = {
            nid: self._normalize(n) for nid, n in new_states.items()
        }

        if events:
            logger.info(
                "REST sync после реконнекта: %d изменений обнаружено",
                len(events),
            )
            await self._notifier.notify_status_change(events)

    def _diff_states(self, new_raw: dict[str, dict]) -> list[dict]:
        """Сравнивает новые состояния с кешированными, возвращает список событий."""
        events = []
        now_utc = datetime.now(timezone.utc).isoformat()

        for node_id, new_node in new_raw.items():
            new_status = new_node.get("status", "unknown")
            new_name = new_node.get("name", "unknown")
            new_host = new_node.get("host", "")

            if node_id not in self._current_states:
                events.append(_make_event("new_node", node_id, new_name, new_host, None, new_status, now_utc))
                continue

            prev = self._current_states[node_id]
            prev_status = prev.get("status", "unknown")

            if prev_status != new_status:
                duration = prev.get("info", {}).get("uptime") if new_status == "down" else None
                events.append(_make_event(new_status, node_id, new_name, new_host, prev_status, new_status, now_utc, duration))

        for node_id, prev in self._current_states.items():
            if node_id not in new_raw:
                events.append(_make_event(
                    "removed_node", node_id,
                    prev.get("node_name", "unknown"),
                    prev.get("host", ""),
                    prev.get("status"), None, now_utc,
                ))

        return events

    # ------------------------------------------------------------------
    # Обработка SSE-событий
    # ------------------------------------------------------------------

    async def _handle_sse_event(self, action: str, record: dict) -> None:
        """Обрабатывает одно SSE-событие от PocketBase.

        Args:
            action: "create", "update" или "delete"
            record: Полная запись из коллекции systems
        """
        node_id = record.get("id", "")
        node_name = record.get("name", "unknown")
        node_host = record.get("host", "")
        new_status = record.get("status", "unknown")
        now_utc = datetime.now(timezone.utc).isoformat()

        if action == "create":
            logger.info("SSE create: %s (%s) — %s", node_name, node_host, new_status)
            await self._save_single(record)
            self._current_states[node_id] = self._normalize(record)
            event = _make_event("new_node", node_id, node_name, node_host, None, new_status, now_utc)
            await self._notifier.notify_status_change([event])

        elif action == "delete":
            prev = self._current_states.get(node_id, {})
            logger.info("SSE delete: %s", prev.get("node_name", node_id))
            await q.delete_node_state(self._db.conn, node_id)
            self._current_states.pop(node_id, None)
            event = _make_event(
                "removed_node", node_id,
                prev.get("node_name", node_name),
                prev.get("host", node_host),
                prev.get("status"), None, now_utc,
            )
            await self._notifier.notify_status_change([event])

        elif action == "update":
            prev = self._current_states.get(node_id)
            prev_status = prev.get("status", "unknown") if prev else "unknown"

            # Обновляем состояние в памяти и БД
            await self._save_single(record)
            self._current_states[node_id] = self._normalize(record)

            if prev_status != new_status:
                # Статус изменился — алерт
                # Для down: берём реальный аптайм ОС из метрик
                # Для up: время даунтайма надёжно не определить, оставляем None
                duration = prev.get("info", {}).get("uptime") if new_status == "down" and prev else None
                logger.info(
                    "SSE update: %s %s → %s (за %s)",
                    node_name, prev_status, new_status,
                    f"{duration:.0f}s" if duration else "?",
                )
                event = _make_event(
                    new_status, node_id, node_name, node_host,
                    prev_status, new_status, now_utc, duration,
                )
                await self._notifier.notify_status_change([event])
            else:
                # Только метрики обновились — тихо обновляем состояние
                logger.debug("SSE update (metrics only): %s", node_name)

    # ------------------------------------------------------------------
    # Hub availability
    # ------------------------------------------------------------------

    async def _on_hub_available(self) -> None:
        """Вызывается при успешном подключении к Hub."""
        if self._hub_available is False:
            # Был недоступен — отправляем алерт о восстановлении
            logger.info("Beszel Hub снова доступен")
            await self._notifier.notify_hub_status(True)
        self._hub_available = True

    async def _on_hub_unavailable(self) -> None:
        """Вызывается при потере соединения с Hub."""
        if self._hub_available is not False:
            # Был доступен или неизвестен — отправляем алерт
            if self._initialized:
                logger.warning("Beszel Hub недоступен")
                await self._notifier.notify_hub_status(False)
        self._hub_available = False

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    async def _save_states(self, states: dict[str, dict]) -> None:
        """Сохраняет все состояния нод в SQLite."""
        for node_id, node in states.items():
            await self._save_single(node)

    async def _save_single(self, node: dict) -> None:
        """Сохраняет одну ноду в SQLite."""
        info = node.get("info") or {}
        info_json = json.dumps(info) if info else "{}"
        await q.upsert_node_state(
            self._db.conn,
            node_id=node.get("id", ""),
            node_name=node.get("name", ""),
            status=node.get("status", "unknown"),
            host=node.get("host", ""),
            info_json=info_json,
        )

    def _normalize(self, node: dict) -> dict:
        """Приводит запись к единому формату для хранения в памяти."""
        return {
            "node_id": node.get("id", ""),
            "node_name": node.get("name", ""),
            "status": node.get("status", "unknown"),
            "host": node.get("host", ""),
            "info": node.get("info") or {},
            "updated_at": node.get("updated", ""),
        }


# ------------------------------------------------------------------
# Утилиты (module-level, без self)
# ------------------------------------------------------------------

def _make_event(
    event_type: str,
    node_id: str,
    node_name: str,
    host: str,
    prev_status: str | None,
    current_status: str | None,
    timestamp: str,
    duration_seconds: float | None = None,
) -> dict:
    return {
        "event_type": event_type,
        "node_id": node_id,
        "node_name": node_name,
        "host": host,
        "previous_status": prev_status,
        "current_status": current_status,
        "duration_seconds": duration_seconds,
        "timestamp": timestamp,
    }
