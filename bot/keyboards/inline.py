"""Фабрики inline-клавиатур для всех экранов бота."""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _btn(text: str, cbd: str, style: str | None = None) -> InlineKeyboardButton:
    """Создаёт InlineKeyboardButton с опциональным style (Telegram Bot API 9.4+).

    aiogram 3.x наследует TelegramObject с extra='allow' в pydantic,
    поэтому extra-параметры передаются в Telegram API напрямую.
    """
    if style:
        return InlineKeyboardButton(text=text, callback_data=cbd, style=style)
    return InlineKeyboardButton(text=text, callback_data=cbd)


# ---------------------------------------------------------------------------
# Главное меню
# ---------------------------------------------------------------------------

def main_menu_kb() -> InlineKeyboardMarkup:
    """Клавиатура главного меню."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("📊 Статус нод", "menu:status"))
    builder.row(_btn("🔔 Настройки алертов", "menu:alerts"))
    builder.row(_btn("⚙️ Настройки бота", "menu:settings"))
    builder.row(_btn("📜 История алертов", "menu:history:0"))
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Статус нод
# ---------------------------------------------------------------------------

def status_menu_kb(up: int, down: int, paused: int) -> InlineKeyboardMarkup:
    """Клавиатура сводки статусов."""
    builder = InlineKeyboardBuilder()

    # Онлайн — зелёная кнопка
    builder.add(_btn(f"🟢 Онлайн ({up})", "status:online", style="success"))

    # Оффлайн — красная если есть упавшие, обычная если нет
    offline_style = "danger" if down > 0 else None
    builder.add(_btn(f"🔴 Оффлайн ({down})", "status:offline", style=offline_style))

    builder.adjust(2)
    builder.row(_btn("📋 Все ноды", "status:all"))
    builder.row(_btn("🔄 Обновить", "status:refresh"), _btn("🏠 Меню", "menu:main"))
    return builder.as_markup()


def nodes_list_kb(nodes: list[dict], back_cb: str = "status:refresh") -> InlineKeyboardMarkup:
    """Клавиатура со списком нод."""
    builder = InlineKeyboardBuilder()

    for node in nodes:
        status = node.get("status", "unknown")
        name = node.get("node_name") or node.get("name", "?")
        node_id = node.get("node_id") or node.get("id", "")

        icons = {"up": "🟢", "down": "🔴", "paused": "⏸"}
        icon = icons.get(status, "❓")

        style = None
        if status == "down":
            style = "danger"
        elif status == "up":
            style = "success"

        builder.row(_btn(f"{icon} {name}", f"node:view:{node_id}", style=style))

    builder.row(_btn("🔙 Назад", back_cb))
    return builder.as_markup()


def node_detail_kb(node_id: str, back_cb: str = "status:all") -> InlineKeyboardMarkup:
    """Клавиатура экрана детальной информации о ноде."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("🔄 Обновить", f"node:refresh:{node_id}"))
    builder.row(_btn("🔕 Замьютить", f"node:mute:{node_id}"))
    builder.row(_btn("🔙 Назад", back_cb))
    return builder.as_markup()


def node_detail_muted_kb(node_id: str, back_cb: str = "status:all") -> InlineKeyboardMarkup:
    """Клавиатура детальной информации для замьюченной ноды."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("🔄 Обновить", f"node:refresh:{node_id}"))
    builder.row(_btn("🔔 Размьютить", f"node:unmute:{node_id}"))
    builder.row(_btn("🔙 Назад", back_cb))
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Настройки алертов
# ---------------------------------------------------------------------------

def alert_settings_kb(settings: dict) -> InlineKeyboardMarkup:
    """Клавиатура настроек алертов."""
    def toggle_icon(flag: bool) -> str:
        return "✅" if flag else "❌"

    builder = InlineKeyboardBuilder()

    builder.row(_btn(
        f"{toggle_icon(settings.get('alert_on_down', 1))} Алерт при падении",
        "alert:toggle:down"
    ))
    builder.row(_btn(
        f"{toggle_icon(settings.get('alert_on_up', 1))} Алерт при восстановлении",
        "alert:toggle:up"
    ))
    builder.row(_btn(
        f"{toggle_icon(settings.get('alert_on_hub_down', 1))} Алерт при недоступности Hub",
        "alert:toggle:hub"
    ))
    builder.row(_btn(
        f"{toggle_icon(settings.get('alert_on_new_node', 1))} Новые ноды",
        "alert:toggle:new"
    ))
    builder.row(_btn(
        f"{toggle_icon(settings.get('alert_on_removed_node', 1))} Удалённые ноды",
        "alert:toggle:removed"
    ))

    # Тихие часы
    quiet_start = settings.get("quiet_hours_start") or "—"
    quiet_end = settings.get("quiet_hours_end") or "—"
    builder.row(_btn(
        f"🕐 Тихие часы: {quiet_start} – {quiet_end}",
        "alert:quiet"
    ))

    # Cooldown
    cooldown = settings.get("alert_cooldown", 300)
    builder.row(_btn(f"⏱ Cooldown: {cooldown}с", "alert:cooldown"))

    builder.row(_btn("🔇 Замьюченные ноды", "alert:mutes:0"))
    builder.row(_btn("🏠 Главное меню", "menu:main"))
    return builder.as_markup()


def muted_nodes_kb(
    all_nodes: list[dict],
    muted_ids: set[str],
    page: int = 0,
    per_page: int = 8,
) -> InlineKeyboardMarkup:
    """Клавиатура управления замьюченными нодами."""
    builder = InlineKeyboardBuilder()

    start = page * per_page
    page_nodes = all_nodes[start : start + per_page]

    for node in page_nodes:
        node_id = node.get("node_id") or node.get("id", "")
        name = node.get("node_name") or node.get("name", "?")
        is_muted = node_id in muted_ids
        icon = "🔕" if is_muted else "🔔"
        action = "unmute" if is_muted else "mute"
        builder.row(_btn(f"{icon} {name}", f"alert:node:{action}:{node_id}"))

    # Пагинация
    total_pages = (len(all_nodes) + per_page - 1) // per_page
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(_btn("⬅️", f"alert:mutes:{page - 1}"))
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
        if page < total_pages - 1:
            nav.append(_btn("➡️", f"alert:mutes:{page + 1}"))
        builder.row(*nav)

    builder.row(_btn("🔙 Настройки алертов", "menu:alerts"))
    return builder.as_markup()


def quiet_hours_cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены при вводе тихих часов."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("❌ Отмена", "alert:quiet:cancel"))
    return builder.as_markup()


def cooldown_cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены при вводе cooldown."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("❌ Отмена", "alert:cooldown:cancel"))
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Настройки бота
# ---------------------------------------------------------------------------

def bot_settings_kb(settings: dict) -> InlineKeyboardMarkup:
    """Клавиатура настроек бота."""
    def toggle_icon(flag: bool) -> str:
        return "✅" if flag else "❌"

    builder = InlineKeyboardBuilder()

    digest = settings.get("daily_digest", 0)
    digest_time = settings.get("daily_digest_time", "09:00")
    builder.row(_btn(
        f"{toggle_icon(digest)} Ежедневный дайджест",
        "settings:digest:toggle"
    ))
    if digest:
        builder.row(_btn(f"🕐 Время дайджеста: {digest_time}", "settings:digest:time"))

    builder.row(_btn("🏠 Главное меню", "menu:main"))
    return builder.as_markup()


def digest_time_cancel_kb() -> InlineKeyboardMarkup:
    """Кнопка отмены при вводе времени дайджеста."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("❌ Отмена", "settings:digest:cancel"))
    return builder.as_markup()


# ---------------------------------------------------------------------------
# История алертов
# ---------------------------------------------------------------------------

def history_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Клавиатура пагинации истории алертов."""
    builder = InlineKeyboardBuilder()

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(_btn("⬅️", f"menu:history:{page - 1}"))
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
        if page < total_pages - 1:
            nav.append(_btn("➡️", f"menu:history:{page + 1}"))
        builder.row(*nav)

    builder.row(_btn("🗑 Очистить историю", "history:clear:confirm"))
    builder.row(_btn("🏠 Главное меню", "menu:main"))
    return builder.as_markup()


def history_clear_confirm_kb() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения очистки истории."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn("✅ Да, очистить", "history:clear:do", style="danger"),
        _btn("❌ Отмена", "menu:history:0"),
    )
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Прочее
# ---------------------------------------------------------------------------

def back_to_main_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(_btn("🏠 Главное меню", "menu:main"))
    return builder.as_markup()
