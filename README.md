# Beszel Monitor Bot

Telegram-бот для мониторинга VPN-инфраструктуры через [Beszel](https://beszel.dev).

## Стек

- **Python 3.12+**
- **aiogram 3.x** — Telegram Bot Framework
- **aiohttp** — HTTP-клиент для Beszel REST API
- **APScheduler** — планировщик задач мониторинга
- **SQLite + aiosqlite** — хранение настроек и истории
- **Docker / docker-compose** — деплой

## Быстрый старт

```bash
cp .env.example .env
# Заполните .env своими данными
docker-compose up -d
```

## Конфигурация (.env)

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен Telegram бота | — |
| `ADMIN_IDS` | ID администраторов (через запятую) | — |
| `BESZEL_URL` | URL Beszel Hub | — |
| `BESZEL_EMAIL` | Email для входа в Beszel | — |
| `BESZEL_PASSWORD` | Пароль Beszel | — |
| `POLL_INTERVAL_SECONDS` | Интервал опроса нод | `30` |
| `ALERT_COOLDOWN_SECONDS` | Cooldown между повторными алертами | `300` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `TZ` | Временная зона | `UTC` |
| `DB_PATH` | Путь к SQLite базе | `data/bot.db` |

## Возможности

### Мониторинг
- Опрос всех нод каждые `POLL_INTERVAL_SECONDS` секунд
- Детекция событий: нода упала/поднялась/приостановлена, новая нода, нода удалена
- Алерт при недоступности Beszel Hub
- Группировка массовых алертов (>3 нод одновременно)
- Cooldown между повторными алертами об одной ноде

### Команды бота
- `/start` — главное меню
- `/status` — сводка статусов нод
- `/nodes` — список всех нод (текст)
- `/admin` — административная панель
- `/help` — справка

### Настройки алертов (через меню)
- Включение/выключение каждого типа алертов
- Тихие часы (алерты не отправляются в заданный период)
- Cooldown между повторными алертами
- Мьют отдельных нод

### История алертов
- Журнал последних событий с пагинацией
- Очистка истории

### Ежедневный дайджест
- Сводка online/offline нод за день
- Список нод, которые падали за 24 часа
- Настраиваемое время отправки

## Структура проекта

```
beszel-telegram-bot/
├── bot/
│   ├── __main__.py          # Точка входа
│   ├── config.py            # Настройки (pydantic-settings)
│   ├── loader.py            # Инициализация компонентов
│   ├── middlewares/
│   │   └── auth.py          # Проверка ADMIN_IDS
│   ├── handlers/
│   │   ├── start.py         # /start, /help
│   │   ├── status.py        # Статус нод
│   │   ├── nodes.py         # Детали нод
│   │   ├── alerts.py        # Настройки алертов
│   │   ├── settings.py      # Настройки бота
│   │   ├── history.py       # История алертов
│   │   └── admin.py         # Административные команды
│   ├── services/
│   │   ├── beszel_client.py # HTTP-клиент Beszel API
│   │   ├── monitor.py       # Логика мониторинга
│   │   └── notifier.py      # Отправка уведомлений
│   ├── database/
│   │   ├── db.py            # Подключение, миграции
│   │   └── queries.py       # SQL-запросы
│   ├── keyboards/
│   │   └── inline.py        # Inline-клавиатуры
│   └── utils/
│       └── formatting.py    # Форматирование сообщений
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## База данных

Автоматически создаётся при первом запуске. Таблицы:
- `user_settings` — настройки каждого администратора
- `muted_nodes` — замьюченные ноды
- `alert_history` — история событий
- `node_states` — последний снимок состояний нод

## Безопасность

- Только пользователи из `ADMIN_IDS` могут взаимодействовать с ботом
- Пароль/токены не логируются
- Токен Beszel автоматически обновляется при истечении (401/403)
- Graceful shutdown при SIGTERM/SIGINT
