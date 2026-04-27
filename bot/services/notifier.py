"""Сервис для формирования и отправки уведомлений администраторам."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.database import queries as q
from bot.database.db import Database
from bot.utils.formatting import (
    format_node_alert,
    format_hub_alert,
    format_new_node_alert,
    format_removed_node_alert,
    format_mass_alert,
    format_duration,
)

logger = logging.getLogger(__name__)

# Порог для группировки алертов в одно сообщение
MASS_ALERT_THRESHOLD = 3


class Notifier:
    """Отправляет уведомления администраторам с учётом их настроек."""

    def __init__(
        self,
        bot: Bot,
        db: Database,
        admin_ids: list[int],
        beszel_url: str,
        tz: str,
    ) -> None:
        self._bot = bot
        self._db = db
        self._admin_ids = admin_ids
        self._beszel_url = beszel_url
        self._tz = tz

    async def notify_status_change(self, events: list[dict]) -> None:
        """Обрабатывает список событий изменения статуса и рассылает алерты.

        Если событий больше MASS_ALERT_THRESHOLD — группирует в одно сообщение.

        Args:
            events: Список словарей с ключами:
                event_type, node_id, node_name, host,
                previous_status, current_status, duration_seconds
        """
        if not events:
            return

        for user_id in self._admin_ids:
            try:
                await self._process_events_for_user(user_id, events)
            except Exception as e:
                logger.error("Ошибка обработки событий для пользователя %d: %s", user_id, e)

    async def _process_events_for_user(self, user_id: int, events: list[dict]) -> None:
        """Обрабатывает события для конкретного пользователя."""
        settings = await q.get_user_settings(self._db.conn, user_id)

        # Проверяем тихие часы
        if _is_quiet_hours(
            settings.get("quiet_hours_start"),
            settings.get("quiet_hours_end"),
            self._tz,
        ):
            logger.debug("Тихие часы для пользователя %d, алерты пропущены", user_id)
            return

        # Фильтруем события: убираем мьют и настройки
        muted_ids = await q.get_muted_node_ids(self._db.conn, user_id)
        cooldown = settings.get("alert_cooldown", 300)

        filtered = []
        for ev in events:
            if not await self._should_send(settings, ev, user_id, muted_ids, cooldown):
                continue
            filtered.append(ev)

        if not filtered:
            return

        # Группируем если слишком много событий
        node_events = [e for e in filtered if e["event_type"] not in ("hub_down", "hub_up")]
        hub_events = [e for e in filtered if e["event_type"] in ("hub_down", "hub_up")]

        # Hub события всегда отправляем отдельно
        for ev in hub_events:
            msg = format_hub_alert(ev["event_type"], self._beszel_url, self._tz)
            await self._send_alert(user_id, ev, msg)

        # Нодовые события
        if len(node_events) > MASS_ALERT_THRESHOLD:
            msg = format_mass_alert(node_events, self._tz)
            # Для массовых алертов сохраняем только первое событие в историю
            for ev in node_events:
                await q.add_alert(
                    self._db.conn,
                    user_id,
                    ev.get("node_id"),
                    ev.get("node_name"),
                    ev["event_type"],
                    f"Массовый алерт: {len(node_events)} нод",
                )
            try:
                await self._bot.send_message(user_id, msg, parse_mode="HTML")
            except TelegramAPIError as e:
                logger.error("Ошибка отправки сообщения пользователю %d: %s", user_id, e)
        else:
            for ev in node_events:
                msg = self._format_event_message(ev)
                await self._send_alert(user_id, ev, msg)

    async def _should_send(
        self,
        settings: dict,
        event: dict,
        user_id: int,
        muted_ids: set[str],
        cooldown: int,
    ) -> bool:
        """Проверяет, нужно ли отправлять алерт для данного события."""
        event_type = event["event_type"]
        node_id = event.get("node_id")

        # Проверяем настройки для каждого типа
        type_flags = {
            "down": "alert_on_down",
            "up": "alert_on_up",
            "hub_down": "alert_on_hub_down",
            "hub_up": "alert_on_hub_down",
            "new_node": "alert_on_new_node",
            "removed_node": "alert_on_removed_node",
            "paused": "alert_on_down",  # paused считаем как down
        }
        flag = type_flags.get(event_type)
        if flag and not settings.get(flag, 1):
            return False

        # Проверяем мьют ноды
        if node_id and node_id in muted_ids:
            return False

        # Проверяем cooldown
        if node_id and cooldown > 0:
            last_time_str = await q.get_last_alert_time(
                self._db.conn, user_id, node_id, event_type
            )
            if last_time_str:
                try:
                    last_time = datetime.fromisoformat(last_time_str).replace(tzinfo=timezone.utc)
                    elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                    if elapsed < cooldown:
                        logger.debug(
                            "Cooldown для %s/%s: прошло %.0fs из %ds",
                            node_id, event_type, elapsed, cooldown
                        )
                        return False
                except ValueError:
                    pass

        return True

    def _format_event_message(self, event: dict) -> str:
        """Форматирует сообщение для события."""
        event_type = event["event_type"]
        node_name = event.get("node_name", "unknown")
        host = event.get("host", "")
        duration = event.get("duration_seconds")
        extra = format_duration(duration) if duration else ""

        if event_type in ("down", "up", "paused"):
            return format_node_alert(
                event_type, node_name, host, self._beszel_url, self._tz, extra
            )
        elif event_type == "new_node":
            status = event.get("current_status", "unknown")
            return format_new_node_alert(node_name, host, status, self._beszel_url, self._tz)
        elif event_type == "removed_node":
            return format_removed_node_alert(node_name, host, self._tz)
        else:
            return f"ℹ️ Событие: {event_type} для {node_name}"

    async def _send_alert(self, user_id: int, event: dict, message: str) -> None:
        """Отправляет алерт и сохраняет в историю."""
        try:
            await self._bot.send_message(user_id, message, parse_mode="HTML")
            await q.add_alert(
                self._db.conn,
                user_id,
                event.get("node_id"),
                event.get("node_name"),
                event["event_type"],
                message,
            )
        except TelegramAPIError as e:
            logger.error("Ошибка отправки алерта пользователю %d: %s", user_id, e)

    async def notify_hub_status(self, is_available: bool) -> None:
        """Отправляет уведомление об изменении доступности Hub."""
        event_type = "hub_up" if is_available else "hub_down"
        events = [{"event_type": event_type, "node_id": None, "node_name": None, "host": None}]
        await self.notify_status_change(events)

    async def send_daily_digest(self, user_id: int, nodes: list[dict]) -> None:
        """Отправляет ежедневный дайджест пользователю."""
        up = [n for n in nodes if n.get("status") == "up"]
        down = [n for n in nodes if n.get("status") == "down"]
        paused = [n for n in nodes if n.get("status") == "paused"]
        total = len(nodes)

        alerts_24h = await q.get_alerts_last_24h(self._db.conn, user_id)
        down_nodes_24h = [
            a for a in alerts_24h if a["event_type"] == "down"
        ]

        uptime_pct = (len(up) / total * 100) if total > 0 else 0

        from bot.utils.formatting import now_in_tz
        now = now_in_tz(self._tz).strftime("%Y-%m-%d")

        text = (
            f"📊 <b>Ежедневный дайджест</b>\n"
            f"📅 {now}\n\n"
            f"🟢 Онлайн: {len(up)}\n"
            f"🔴 Оффлайн: {len(down)}\n"
            f"⏸ Приостановлено: {len(paused)}\n"
            f"📈 Uptime: {uptime_pct:.1f}%\n"
        )

        if down_nodes_24h:
            text += f"\n⬇️ <b>Падения за 24ч:</b>\n"
            seen = set()
            for a in down_nodes_24h[:10]:
                name = a.get("node_name", "unknown")
                if name not in seen:
                    text += f"  • <code>{name}</code>\n"
                    seen.add(name)

        try:
            await self._bot.send_message(user_id, text, parse_mode="HTML")
            await q.update_user_settings(
                self._db.conn, user_id,
                last_digest_date=now_in_tz(self._tz).strftime("%Y-%m-%d")
            )
        except TelegramAPIError as e:
            logger.error("Ошибка отправки дайджеста пользователю %d: %s", user_id, e)


def _is_quiet_hours(start: str | None, end: str | None, tz_name: str) -> bool:
    """Проверяет, находимся ли сейчас в тихих часах.

    Корректно обрабатывает переход через полночь (например 23:00 - 07:00).
    """
    if not start or not end:
        return False

    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")

    from datetime import time as dt_time
    now = datetime.now(tz).time().replace(second=0, microsecond=0)

    try:
        start_t = dt_time.fromisoformat(start)
        end_t = dt_time.fromisoformat(end)
    except ValueError:
        return False

    if start_t <= end_t:
        # Обычный интервал: 09:00 - 18:00
        return start_t <= now <= end_t
    else:
        # Переход через полночь: 23:00 - 07:00
        return now >= start_t or now <= end_t
