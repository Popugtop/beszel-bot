"""Утилиты для форматирования сообщений и данных."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Иконки для статусов нод
STATUS_ICONS = {
    "up": "🟢",
    "down": "🔴",
    "paused": "⏸",
}

# Иконки для типов событий
EVENT_ICONS = {
    "down": "🔴",
    "up": "🟢",
    "paused": "⏸",
    "hub_down": "⚠️",
    "hub_up": "✅",
    "new_node": "🆕",
    "removed_node": "🗑",
}


def get_status_icon(status: str) -> str:
    """Возвращает иконку для статуса ноды."""
    return STATUS_ICONS.get(status, "❓")


def get_event_icon(event_type: str) -> str:
    """Возвращает иконку для типа события."""
    return EVENT_ICONS.get(event_type, "❓")


def format_duration(seconds: float) -> str:
    """Форматирует длительность в читаемый вид.

    Examples:
        4 → "4с"
        267 → "4м 27с"
        3742 → "1ч 2м 22с"
        1209600 → "14д 0ч 0м"
    """
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}с"

    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}м {sec}с"

    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}ч {minutes}м {sec}с"

    days, hours = divmod(hours, 24)
    return f"{days}д {hours}ч {minutes}м"


def format_datetime_tz(dt_str: str, tz_name: str) -> str:
    """Конвертирует ISO datetime строку в локальное время.

    Args:
        dt_str: ISO строка вида "2025-04-27 15:30:45.000Z" или "2025-04-27T15:30:45Z"
        tz_name: Имя временной зоны, например "Asia/Yekaterinburg"

    Returns:
        Форматированное время: "2025-04-27 20:30:45"
    """
    try:
        # Нормализуем разные форматы
        dt_str_clean = dt_str.replace("Z", "+00:00").replace(" ", "T")
        if "." in dt_str_clean:
            dt_str_clean = dt_str_clean.split(".")[0] + "+00:00"

        dt = datetime.fromisoformat(dt_str_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")

        local_dt = dt.astimezone(tz)
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return dt_str[:19] if dt_str else "—"


def now_in_tz(tz_name: str) -> datetime:
    """Возвращает текущее время в заданной временной зоне."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def format_node_info(info: dict) -> str:
    """Форматирует метрики ноды из поля info.

    Returns:
        Строка с метриками или пустая строка если нет данных.
    """
    if not info:
        return ""

    lines = []

    cpu = info.get("cpu")
    if cpu is not None:
        lines.append(f"💻 CPU: {cpu:.1f}%")

    mem = info.get("mem")
    mem_total = info.get("memTotal")
    if mem is not None and mem_total:
        lines.append(f"🧠 RAM: {mem:.1f}% ({_mb_to_human(mem_total * mem / 100)} / {_mb_to_human(mem_total)})")
    elif mem is not None:
        lines.append(f"🧠 RAM: {mem:.1f}%")

    disk = info.get("disk")
    disk_total = info.get("diskTotal")
    if disk is not None and disk_total:
        lines.append(f"💾 Диск: {disk:.1f}% ({_mb_to_human(disk_total * disk / 100)} / {_mb_to_human(disk_total)})")
    elif disk is not None:
        lines.append(f"💾 Диск: {disk:.1f}%")

    uptime = info.get("uptime")
    if uptime:
        lines.append(f"⏱ Uptime системы: {format_duration(uptime)}")

    return "\n".join(lines)


def _mb_to_human(mb: float) -> str:
    """Конвертирует мегабайты в читаемый формат."""
    if mb >= 1024:
        return f"{mb / 1024:.1f} ГБ"
    return f"{mb:.0f} МБ"


def _sanitize_host(host: str) -> str:
    """Возвращает читаемое значение хоста.

    IP-адреса и hostname никогда не содержат пробелов.
    Если в поле пробел — это не адрес (например, команда установки агента).
    """
    if not host:
        return "—"
    if " " in host or len(host) > 253:
        return "—"
    return host


def format_node_alert(
    event_type: str,
    node_name: str,
    host: str,
    beszel_url: str,
    tz: str,
    extra: str = "",
) -> str:
    """Форматирует сообщение алерта об изменении статуса ноды."""
    icon = get_event_icon(event_type)
    now = now_in_tz(tz).strftime("%Y-%m-%d %H:%M:%S")
    host = _sanitize_host(host)

    if event_type == "down":
        title = "Нода DOWN"
        label = "Была онлайн"
    elif event_type == "up":
        title = "Нода UP"
        label = "Была оффлайн"
    elif event_type == "paused":
        title = "Нода PAUSED"
        label = ""
    else:
        title = event_type.upper()
        label = ""

    text = f"{icon} <b>{title}</b>\n\n"
    text += f"📛 Имя: <code>{node_name}</code>\n"
    text += f"🌐 Хост: <code>{host}</code>\n"
    text += f"⏰ Время: {now}\n"

    if extra and label:
        text += f"📊 {label}: {extra}\n"

    text += f"\n🔗 <a href=\"{beszel_url}\">Открыть Beszel</a>"
    return text


def format_hub_alert(event_type: str, beszel_url: str, tz: str) -> str:
    """Форматирует сообщение алерта о доступности Hub."""
    now = now_in_tz(tz).strftime("%Y-%m-%d %H:%M:%S")

    if event_type == "hub_down":
        return (
            f"⚠️ <b>Beszel Hub недоступен</b>\n\n"
            f"🌐 URL: <code>{beszel_url}</code>\n"
            f"⏰ Время: {now}"
        )
    else:
        return (
            f"✅ <b>Beszel Hub снова доступен</b>\n\n"
            f"🌐 URL: <code>{beszel_url}</code>\n"
            f"⏰ Время: {now}"
        )


def format_new_node_alert(node_name: str, host: str, status: str, beszel_url: str, tz: str) -> str:
    """Форматирует сообщение об обнаружении новой ноды."""
    icon = get_status_icon(status)
    now = now_in_tz(tz).strftime("%Y-%m-%d %H:%M:%S")
    host = _sanitize_host(host)
    return (
        f"🆕 <b>Обнаружена новая нода</b>\n\n"
        f"📛 Имя: <code>{node_name}</code>\n"
        f"🌐 Хост: <code>{host}</code>\n"
        f"📡 Статус: {icon} {status}\n"
        f"⏰ Время: {now}\n\n"
        f"🔗 <a href=\"{beszel_url}\">Открыть Beszel</a>"
    )


def format_removed_node_alert(node_name: str, host: str, tz: str) -> str:
    """Форматирует сообщение об удалении ноды."""
    now = now_in_tz(tz).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"🗑 <b>Нода удалена</b>\n\n"
        f"📛 Имя: <code>{node_name}</code>\n"
        f"🌐 Хост: <code>{host}</code>\n"
        f"⏰ Время: {now}"
    )


def format_mass_alert(events: list[dict], tz: str) -> str:
    """Форматирует сообщение о массовом изменении статусов нод.

    Используется когда одновременно меняется более 3 нод.
    """
    now = now_in_tz(tz).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"⚠️ <b>Массовое изменение статусов нод</b>\n⏰ Время: {now}\n"]

    for ev in events:
        icon = get_event_icon(ev["event_type"])
        name = ev.get("node_name", "unknown")
        host = ev.get("host", "")
        lines.append(f"{icon} <code>{name}</code> ({host}) → {ev['event_type'].upper()}")

    return "\n".join(lines)
