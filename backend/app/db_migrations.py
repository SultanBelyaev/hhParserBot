"""Lightweight SQLite schema migrations."""
from sqlalchemy import inspect, text

from app.database import engine


def migrate_schema() -> None:
    inspector = inspect(engine)
    if "campaigns" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("campaigns")}
    if "vacancies_found" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE campaigns ADD COLUMN vacancies_found INTEGER"))
    if "cover_letter" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE campaigns ADD COLUMN cover_letter TEXT"))
    if "application_logs" in inspector.get_table_names():
        log_columns = {col["name"] for col in inspector.get_columns("application_logs")}
        if "cover_letter_sent" not in log_columns:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE application_logs ADD COLUMN cover_letter_sent BOOLEAN DEFAULT 0"
                ))
