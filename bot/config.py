"""Конфигурация бота через pydantic-settings и .env файл."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки бота, загружаемые из .env."""

    # Telegram
    BOT_TOKEN: str
    ADMIN_IDS: str  # через запятую: "123456,789012"

    # Beszel
    BESZEL_URL: str
    BESZEL_EMAIL: str
    BESZEL_PASSWORD: str

    # Мониторинг (SSE)
    SSE_RECONNECT_SECONDS: int = 5      # пауза перед реконнектом при обрыве
    ALERT_COOLDOWN_SECONDS: int = 300   # cooldown между повторными алертами об одной ноде

    # Прочее
    LOG_LEVEL: str = "INFO"
    TZ: str = "UTC"
    DB_PATH: str = "data/bot.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_id_list(self) -> list[int]:
        """Список ID администраторов."""
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit()]

    @property
    def beszel_url_clean(self) -> str:
        """URL Beszel без trailing slash."""
        return self.BESZEL_URL.rstrip("/")

    def ensure_db_dir(self) -> None:
        """Создаёт директорию для базы данных если не существует."""
        Path(self.DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Загружает настройки из .env файла."""
    return Settings()
