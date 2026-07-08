"""Create SQLite tables and apply lightweight migrations."""
from __future__ import annotations

import logging

from app.database import Base, engine
from app.db_migrations import migrate_schema

logger = logging.getLogger(__name__)


def init_database() -> None:
    import app.models  # noqa: F401 — register Campaign/ApplicationLog on Base.metadata

    from app.config import settings

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    logger.info("Database initialized at %s", settings.database_url)
