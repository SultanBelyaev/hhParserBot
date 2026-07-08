import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
DEFAULT_SESSION_FILE = DATA_DIR / "session.json"
DEFAULT_DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'hh_parser.db').as_posix()}")

load_dotenv(ROOT_DIR / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = DEFAULT_DATABASE_URL
    session_file: Path = Path(os.getenv("SESSION_FILE", str(DEFAULT_SESSION_FILE)))
    headless: bool = True
    scroll_max: int = 30
    scroll_pause_ms: int = 500
    scroll_buffer_factor: float = 1.5
    apply_delay_ms: int = 700
    apply_poll_timeout_sec: float = 5.0
    hide_skipped_vacancies: bool = False
    block_media: bool = True
    frontend_url: str = "http://localhost:5173"
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

    @field_validator("telegram_bot_token", "telegram_allowed_user_ids", "telegram_proxy_url", mode="before")
    @classmethod
    def _strip_env_quotes(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().strip('"').strip("'")
        return value

    @property
    def bot_heartbeat_file(self) -> Path:
        return Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data"))) / "bot.heartbeat"

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
