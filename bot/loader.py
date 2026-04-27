"""Инициализация Bot, Dispatcher и сервисов."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import Settings
from bot.database.db import Database
from bot.services.beszel_client import BeszelClient
from bot.services.monitor import Monitor
from bot.services.notifier import Notifier

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    """Создаёт экземпляр Telegram Bot."""
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Создаёт Dispatcher с MemoryStorage для FSM."""
    return Dispatcher(storage=MemoryStorage())


def create_services(settings: Settings) -> tuple[BeszelClient, Database]:
    """Создаёт клиент Beszel и объект базы данных."""
    client = BeszelClient(
        base_url=settings.beszel_url_clean,
        email=settings.BESZEL_EMAIL,
        password=settings.BESZEL_PASSWORD,
    )
    db = Database(db_path=settings.DB_PATH)
    return client, db


def create_monitor_and_notifier(
    bot: Bot,
    client: BeszelClient,
    db: Database,
    settings: Settings,
) -> tuple[Monitor, Notifier]:
    """Создаёт сервисы мониторинга и нотификации."""
    notifier = Notifier(
        bot=bot,
        db=db,
        admin_ids=settings.admin_id_list,
        beszel_url=settings.beszel_url_clean,
        tz=settings.TZ,
    )
    monitor = Monitor(
        client=client,
        db=db,
        notifier=notifier,
        reconnect_seconds=settings.SSE_RECONNECT_SECONDS,
    )
    return monitor, notifier


def register_middlewares(dp: Dispatcher, settings: Settings) -> None:
    """Регистрирует middleware в диспетчере."""
    from bot.middlewares.auth import AdminMiddleware
    dp.message.middleware(AdminMiddleware(settings.admin_id_list))
    dp.callback_query.middleware(AdminMiddleware(settings.admin_id_list))


def register_handlers(dp: Dispatcher) -> None:
    """Регистрирует все роутеры обработчиков."""
    from bot.handlers import start, status, nodes, alerts, settings, admin, history

    dp.include_router(start.router)
    dp.include_router(status.router)
    dp.include_router(nodes.router)
    dp.include_router(alerts.router)
    dp.include_router(settings.router)
    dp.include_router(admin.router)
    dp.include_router(history.router)


def inject_dependencies(
    dp: Dispatcher,
    db: Database,
    client: BeszelClient,
    monitor: Monitor,
    notifier: Notifier,
    settings: Settings,
) -> None:
    """Внедряет зависимости в workflow_data диспетчера."""
    dp["db"] = db
    dp["client"] = client
    dp["monitor"] = monitor
    dp["notifier"] = notifier
    dp["tz"] = settings.TZ
    dp["settings"] = settings
