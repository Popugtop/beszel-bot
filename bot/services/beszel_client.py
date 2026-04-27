"""HTTP-клиент для работы с Beszel/PocketBase REST API и Realtime SSE."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Таймаут для обычных REST-запросов
REST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)

# Таймаут для SSE-соединения: без общего лимита, только connect timeout
SSE_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=None)


class BeszelAuthError(Exception):
    """Ошибка аутентификации в Beszel."""


class BeszelAPIError(Exception):
    """Общая ошибка Beszel API."""


class SSEEvent:
    """Одно событие Server-Sent Events."""

    __slots__ = ("event", "data", "id")

    def __init__(self) -> None:
        self.event: str = ""
        self.data: str = ""
        self.id: str = ""

    def is_complete(self) -> bool:
        return bool(self.data)

    def parse_json(self) -> Any:
        return json.loads(self.data)


async def _parse_sse_stream(content: aiohttp.StreamReader) -> AsyncGenerator[SSEEvent, None]:
    """Парсит SSE-поток построчно и выдаёт полные события.

    SSE-формат (RFC):
        event: <type>\\n
        data: <json>\\n
        \\n          ← пустая строка = конец события
    """
    current = SSEEvent()

    while True:
        raw = await content.readline()
        if not raw:
            # EOF — соединение закрыто
            break

        line = raw.decode("utf-8").rstrip("\r\n")

        if line == "":
            # Пустая строка — отправляем накопленное событие
            if current.is_complete():
                yield current
            current = SSEEvent()
            continue

        if line.startswith("event:"):
            current.event = line[6:].strip()
        elif line.startswith("data:"):
            current.data = line[5:].strip()
        elif line.startswith("id:"):
            current.id = line[3:].strip()
        # retry: и комментарии (#) — игнорируем


class BeszelClient:
    """Клиент для работы с Beszel/PocketBase REST API.

    Использует одну aiohttp.ClientSession для всех запросов.
    Автоматически повторяет аутентификацию при 401/403.
    """

    def __init__(self, base_url: str, email: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._token: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._auth_lock = asyncio.Lock()

    async def start(self) -> None:
        """Создаёт HTTP-сессию и выполняет первичную аутентификацию."""
        self._session = aiohttp.ClientSession()
        logger.info("Инициализация Beszel клиента для %s", self._base_url)
        await self._authenticate()

    async def close(self) -> None:
        """Закрывает HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Beszel HTTP-сессия закрыта")

    async def _authenticate(self) -> None:
        """Аутентифицируется в Beszel и сохраняет токен."""
        url = f"{self._base_url}/api/collections/users/auth-with-password"
        payload = {"identity": self._email, "password": self._password}

        try:
            async with self._session.post(url, json=payload, timeout=REST_TIMEOUT) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise BeszelAuthError(f"Ошибка аутентификации ({resp.status}): {text[:200]}")

                data = await resp.json()
                self._token = data.get("token")
                if not self._token:
                    raise BeszelAuthError("Токен не получен в ответе аутентификации")

                logger.info("Успешная аутентификация в Beszel")

        except aiohttp.ClientError as e:
            raise BeszelAuthError(f"Ошибка подключения при аутентификации: {e}") from e

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        retry_auth: bool = True,
    ) -> Any:
        """Выполняет REST-запрос с автоматической повторной аутентификацией."""
        if self._session is None or self._session.closed:
            raise BeszelAPIError("HTTP-сессия не инициализирована")

        url = f"{self._base_url}{path}"

        try:
            async with self._session.request(
                method, url,
                headers=self._auth_headers(),
                params=params,
                json=json_body,
                timeout=REST_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403) and retry_auth:
                    logger.warning("Токен устарел, повторная аутентификация...")
                    async with self._auth_lock:
                        await self._authenticate()
                    return await self._request(
                        method, path, params=params, json_body=json_body, retry_auth=False
                    )

                if resp.status not in (200, 204):
                    text = await resp.text()
                    raise BeszelAPIError(f"API ответил {resp.status}: {text[:200]}")

                if resp.status == 204:
                    return None
                return await resp.json()

        except aiohttp.ClientConnectorError as e:
            raise BeszelAPIError(f"Ошибка подключения к {self._base_url}: {e}") from e
        except aiohttp.ServerTimeoutError as e:
            raise BeszelAPIError(f"Таймаут запроса к {self._base_url}: {e}") from e
        except aiohttp.ClientError as e:
            raise BeszelAPIError(f"HTTP ошибка: {e}") from e

    # ------------------------------------------------------------------
    # REST API методы
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Проверяет доступность Beszel Hub."""
        try:
            data = await self._request("GET", "/api/health")
            return isinstance(data, dict) and data.get("code") == 200
        except (BeszelAPIError, BeszelAuthError) as e:
            logger.debug("Health check провалился: %s", e)
            return False

    async def get_systems(self, per_page: int = 200) -> list[dict]:
        """Возвращает полный список систем (нод)."""
        data = await self._request(
            "GET", "/api/collections/systems/records",
            params={"perPage": per_page}
        )
        items = data.get("items", [])
        logger.debug("REST sync: получено %d нод", len(items))
        return items

    async def get_system(self, system_id: str) -> dict:
        """Возвращает данные одной системы по ID."""
        return await self._request("GET", f"/api/collections/systems/records/{system_id}")

    # ------------------------------------------------------------------
    # PocketBase Realtime SSE
    # ------------------------------------------------------------------

    async def realtime_listen(
        self,
        stop_event: asyncio.Event,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """Подключается к PocketBase Realtime и стримит события изменений нод.

        Протокол:
            1. GET /api/realtime  →  SSE stream
            2. Первое событие PB_CONNECT содержит clientId
            3. POST /api/realtime с clientId и подпиской на systems/*
            4. Далее приходят события: (action, record)

        Yields:
            Кортеж ("create"|"update"|"delete", record_dict)

        Raises:
            BeszelAPIError: при ошибке подключения или HTTP
            BeszelAuthError: при ошибке авторизации
        """
        if self._session is None or self._session.closed:
            raise BeszelAPIError("HTTP-сессия не инициализирована")

        url = f"{self._base_url}/api/realtime"

        async with self._session.get(
            url,
            headers=self._auth_headers(),
            timeout=SSE_TIMEOUT,
        ) as resp:
            if resp.status in (401, 403):
                logger.warning("SSE: токен устарел, переавторизация...")
                async with self._auth_lock:
                    await self._authenticate()
                raise BeszelAPIError("Переавторизация выполнена, переподключитесь к SSE")

            if resp.status != 200:
                text = await resp.text()
                raise BeszelAPIError(f"SSE endpoint вернул {resp.status}: {text[:200]}")

            logger.debug("SSE соединение установлено")
            subscribed = False

            async for event in _parse_sse_stream(resp.content):
                if stop_event.is_set():
                    return

                if event.event == "PB_CONNECT":
                    try:
                        payload = event.parse_json()
                        client_id = payload.get("clientId", "")
                    except (json.JSONDecodeError, KeyError):
                        logger.error("SSE: не удалось распарсить PB_CONNECT: %s", event.data)
                        return

                    # Отправляем подписку на изменения коллекции systems
                    try:
                        await self._request(
                            "POST", "/api/realtime",
                            json_body={
                                "clientId": client_id,
                                "subscriptions": ["systems/*"],
                            },
                        )
                        subscribed = True
                        logger.info("SSE: подписка на systems/* активирована (clientId=%s)", client_id)
                    except BeszelAPIError as e:
                        logger.error("SSE: не удалось подписаться: %s", e)
                        return

                elif event.event == "systems" and subscribed:
                    try:
                        payload = event.parse_json()
                        action: str = payload.get("action", "")
                        record: dict = payload.get("record", {})

                        if action and record:
                            yield action, record

                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("SSE: не удалось распарсить событие: %s — %s", event.data[:100], e)
