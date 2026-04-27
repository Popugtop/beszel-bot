"""Обработчики настроек бота: дайджест, интервал опроса."""

import logging
import re

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.database import queries as q
from bot.database.db import Database
from bot.keyboards.inline import bot_settings_kb, digest_time_cancel_kb, back_to_main_kb

logger = logging.getLogger(__name__)
router = Router(name="settings")

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class BotSettingsFSM(StatesGroup):
    """FSM-состояния для ввода настроек бота."""
    waiting_digest_time = State()


async def _show_settings(target: CallbackQuery | Message, db: Database, user_id: int) -> None:
    """Показывает экран настроек бота."""
    settings = await q.get_user_settings(db.conn, user_id)
    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        "Выберите параметр для изменения:"
    )
    kb = bot_settings_kb(settings)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "menu:settings")
async def cb_menu_settings(callback: CallbackQuery, db: Database) -> None:
    """Переход на экран настроек бота."""
    await _show_settings(callback, db, callback.from_user.id)


@router.callback_query(F.data == "settings:digest:toggle")
async def cb_digest_toggle(callback: CallbackQuery, db: Database) -> None:
    """Включает/выключает ежедневный дайджест."""
    user_id = callback.from_user.id
    settings = await q.get_user_settings(db.conn, user_id)
    current = settings.get("daily_digest", 0)
    await q.update_user_settings(db.conn, user_id, daily_digest=0 if current else 1)
    await _show_settings(callback, db, user_id)


@router.callback_query(F.data == "settings:digest:time")
async def cb_digest_time(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Начинает ввод времени ежедневного дайджеста."""
    user_id = callback.from_user.id
    settings = await q.get_user_settings(db.conn, user_id)
    current = settings.get("daily_digest_time", "09:00")

    text = (
        f"📊 <b>Время ежедневного дайджеста</b>\n\n"
        f"Текущее время: <b>{current}</b>\n\n"
        f"Введите новое время в формате <code>HH:MM</code>:"
    )
    await callback.message.edit_text(text, reply_markup=digest_time_cancel_kb(), parse_mode="HTML")
    await state.set_state(BotSettingsFSM.waiting_digest_time)
    await callback.answer()


@router.callback_query(F.data == "settings:digest:cancel")
async def cb_digest_cancel(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    """Отмена ввода времени дайджеста."""
    await state.clear()
    await _show_settings(callback, db, callback.from_user.id)


@router.message(BotSettingsFSM.waiting_digest_time)
async def fsm_digest_time(message: Message, db: Database, state: FSMContext) -> None:
    """Обрабатывает ввод времени дайджеста."""
    text = message.text.strip() if message.text else ""

    if not TIME_RE.match(text):
        await message.answer(
            "❌ Неверный формат. Введите время в формате <code>HH:MM</code>, например <code>09:00</code>",
            reply_markup=digest_time_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await q.update_user_settings(db.conn, message.from_user.id, daily_digest_time=text)
    await state.clear()
    await message.answer(
        f"✅ Время дайджеста установлено: <b>{text}</b>",
        reply_markup=back_to_main_kb(),
        parse_mode="HTML",
    )
