"""Обработчики команд /start и /help."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.inline import main_menu_kb

logger = logging.getLogger(__name__)
router = Router(name="start")

WELCOME_TEXT = (
    "👋 <b>Beszel Monitor Bot</b>\n\n"
    "Мониторинг VPN-инфраструктуры через Beszel.\n\n"
    "Выберите раздел:"
)

HELP_TEXT = (
    "ℹ️ <b>Справка</b>\n\n"
    "Бот отслеживает статусы нод Beszel и уведомляет при изменениях.\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/status — текущий статус нод\n"
    "/help — эта справка\n\n"
    "<b>Разделы меню:</b>\n"
    "📊 <b>Статус нод</b> — сводка и список нод\n"
    "🔔 <b>Настройки алертов</b> — включить/выключить уведомления\n"
    "⚙️ <b>Настройки бота</b> — ежедневный дайджест\n"
    "📜 <b>История алертов</b> — журнал событий"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Обработчик команды /start — показывает главное меню."""
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Обработчик команды /help."""
    await message.answer(HELP_TEXT, reply_markup=main_menu_kb(), parse_mode="HTML")
