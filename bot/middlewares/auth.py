"""Middleware для проверки прав доступа администратора."""

import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)


class AdminMiddleware(BaseMiddleware):
    """Блокирует все запросы от пользователей не из списка ADMIN_IDS.

    Работает с Message и CallbackQuery.
    """

    def __init__(self, admin_ids: list[int]) -> None:
        self._admin_ids = set(admin_ids)
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)

        if user_id is None:
            # Не можем определить пользователя — пропускаем
            return await handler(event, data)

        if user_id not in self._admin_ids:
            logger.warning("Несанкционированный доступ от user_id=%d", user_id)
            await self._reject(event)
            return None

        return await handler(event, data)

    def _extract_user_id(self, event: TelegramObject) -> int | None:
        """Извлекает user_id из события."""
        if isinstance(event, Message):
            return event.from_user.id if event.from_user else None
        if isinstance(event, CallbackQuery):
            return event.from_user.id if event.from_user else None
        return None

    async def _reject(self, event: TelegramObject) -> None:
        """Отправляет сообщение об отказе в доступе."""
        try:
            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён", show_alert=True)
        except Exception as e:
            logger.debug("Не удалось отправить сообщение об отказе: %s", e)
