"""Точка входа в приложение Beszel Telegram Monitor Bot."""

import asyncio
import logging
import sys

from bot.config import load_settings
from bot.loader import (
    create_bot,
    create_dispatcher,
    create_services,
    create_monitor_and_notifier,
    register_middlewares,
    register_handlers,
    inject_dependencies,
)


def setup_logging(log_level: str) -> None:
    """Настраивает логирование."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


async def _digest_loop(monitor, notifier, settings) -> None:
    """Проверяет каждую минуту, нужно ли отправить ежедневный дайджест."""
    from bot.database import queries as q
    from bot.utils.formatting import now_in_tz

    while True:
        await asyncio.sleep(60)
        try:
            now = now_in_tz(settings.TZ)
            current_time = now.strftime("%H:%M")
            current_date = now.strftime("%Y-%m-%d")

            for user_id in await q.get_all_admin_user_ids(notifier._db.conn):
                s = await q.get_user_settings(notifier._db.conn, user_id)
                if not s.get("daily_digest"):
                    continue
                if s.get("daily_digest_time") == current_time and s.get("last_digest_date") != current_date:
                    await notifier.send_daily_digest(user_id, monitor.get_current_nodes())
                    logger.info("Дайджест отправлен пользователю %d", user_id)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Ошибка в digest loop: %s", e)


async def main() -> None:
    """Главная функция запуска бота."""
    settings = load_settings()
    setup_logging(settings.LOG_LEVEL)

    logger.info("Запуск Beszel Monitor Bot (realtime SSE)")
    logger.info("Beszel URL: %s", settings.beszel_url_clean)
    logger.info("Timezone: %s", settings.TZ)
    logger.info("Admin IDs: %s", settings.admin_id_list)
    logger.info("SSE reconnect: %ds", settings.SSE_RECONNECT_SECONDS)

    settings.ensure_db_dir()

    bot = create_bot(settings)
    dp = create_dispatcher()
    client, db = create_services(settings)
    monitor, notifier = create_monitor_and_notifier(bot, client, db, settings)

    register_middlewares(dp, settings)
    register_handlers(dp)
    inject_dependencies(dp, db, client, monitor, notifier, settings)

    async def on_startup() -> None:
        # База данных
        try:
            await db.connect()
            logger.info("База данных подключена")
        except Exception as e:
            logger.critical("Не удалось подключиться к БД: %s", e)
            sys.exit(1)

        # Beszel auth + первичная загрузка состояний из БД
        try:
            await client.start()
        except Exception as e:
            logger.error("Ошибка инициализации Beszel клиента: %s. Продолжаем...", e)

        await monitor.initialize_from_db()

        # Запускаем SSE-мониторинг и дайджест как фоновые задачи
        asyncio.create_task(monitor.start(), name="sse-monitor")
        asyncio.create_task(
            _digest_loop(monitor, notifier, settings), name="digest-loop"
        )

        logger.info("Бот готов к работе!")

    async def on_shutdown() -> None:
        logger.info("Завершение работы...")
        await monitor.stop()
        await client.close()
        await db.close()
        await bot.session.close()
        logger.info("Shutdown завершён")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("Запуск Telegram long-polling...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    except Exception as e:
        logger.critical("Критическая ошибка: %s", e, exc_info=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.critical("Необработанная ошибка: %s", e, exc_info=True)
        sys.exit(1)
