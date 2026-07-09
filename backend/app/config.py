import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=False)


def _default_sqlite_url() -> str:
    data_dir = os.getenv("DATA_DIR", str(ROOT_DIR / "data"))
    return f"sqlite:///{(Path(data_dir) / 'hh_parser.db').as_posix()}"


def _default_session_file() -> Path:
    data_dir = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
    raw = os.getenv("SESSION_FILE", str(data_dir / "session.json"))
    path = Path(raw.strip().strip('"').strip("'"))
    if not path.is_absolute():
        path = data_dir / path
    return path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(default_factory=_default_sqlite_url, validation_alias="DATABASE_URL")
    session_file: Path = Field(default_factory=_default_session_file, validation_alias="SESSION_FILE")
    data_dir: Path = Field(default=ROOT_DIR / "data", validation_alias="DATA_DIR")
    headless: bool = Field(default=True, validation_alias="HEADLESS")
    scroll_max: int = Field(default=30, validation_alias="SCROLL_MAX")
    scroll_pause_ms: int = Field(default=500, validation_alias="SCROLL_PAUSE_MS")
    scroll_buffer_factor: float = Field(default=1.5, validation_alias="SCROLL_BUFFER_FACTOR")
    apply_delay_ms: int = Field(default=700, validation_alias="APPLY_DELAY_MS")
    apply_poll_timeout_sec: float = Field(default=5.0, validation_alias="APPLY_POLL_TIMEOUT_SEC")
    hide_skipped_vacancies: bool = Field(default=False, validation_alias="HIDE_SKIPPED_VACANCIES")
    block_media: bool = Field(default=True, validation_alias="BLOCK_MEDIA")
    default_cover_letter: str = (
        "Аналитик с хорошим техническим бэкграундом и опытом проектирования сложных IT-решений. "
        "Имею высшее техническое образование (ВШЭ), что позволяет глубоко разбираться в архитектуре систем, "
        "базах данных и API-интеграциях. Активно участвую в хакатонах от Сбера и T1 Холдинга, где оттачиваю "
        "навыки быстрого анализа, генерации решений и работы в команде в условиях ограниченного времени. "
        "Гипербыстрообучаемый: за короткие сроки осваиваю новые технологии, методологии и инструменты. "
        "Легко адаптируюсь к изменениям, люблю разбираться в сложных задачах и искать нестандартные решения. "
        "Хочу работать в технологически сложном проекте. Интересны интеграции, работа с реляционными и NoSQL "
        "базами данных, проектирование API. Люблю разбираться в сложных процессах, находить узкие места "
        "и помогать делать систему лучше."
    )
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_ids: str = Field(default="", validation_alias="TELEGRAM_ALLOWED_USER_IDS")
    telegram_proxy_url: str = Field(default="", validation_alias="TELEGRAM_PROXY_URL")
    telegram_connect_timeout: float = Field(default=30.0, validation_alias="TELEGRAM_CONNECT_TIMEOUT")
    telegram_read_timeout: float = Field(default=30.0, validation_alias="TELEGRAM_READ_TIMEOUT")
    railway_public_domain: str = Field(default="", validation_alias="RAILWAY_PUBLIC_DOMAIN")
    public_url: str = Field(default="", validation_alias="PUBLIC_URL")
    telegram_use_webhook: bool = Field(default=False, validation_alias="TELEGRAM_USE_WEBHOOK")

    @model_validator(mode="before")
    @classmethod
    def _strip_railway_quotes(cls, data: Any) -> Any:
        """Railway Variables often come as \"value\" — strip outer quotes."""
        if not isinstance(data, dict):
            return data
        cleaned: dict[Any, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                cleaned[key] = value.strip().strip('"').strip("'")
            else:
                cleaned[key] = value
        return cleaned

    @field_validator("session_file", "data_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().strip('"').strip("'")
            path = Path(value)
            if not path.is_absolute() and os.getenv("DATA_DIR"):
                path = Path(os.getenv("DATA_DIR", "").strip().strip('"').strip("'")) / path
            return path
        return value

    @property
    def bot_heartbeat_file(self) -> Path:
        return self.data_dir / "bot.heartbeat"

    @property
    def telegram_webhook_base_url(self) -> str:
        if self.public_url.strip():
            return self.public_url.strip().rstrip("/")
        if self.railway_public_domain.strip():
            return f"https://{self.railway_public_domain.strip()}"
        return ""

    @property
    def should_use_telegram_webhook(self) -> bool:
        if not self.telegram_bot_token.strip():
            return False
        if self.telegram_use_webhook:
            return bool(self.telegram_webhook_base_url)
        return bool(self.railway_public_domain.strip())

    @property
    def telegram_webhook_url(self) -> str:
        base = self.telegram_webhook_base_url
        return f"{base}/telegram/webhook" if base else ""


settings = Settings()
