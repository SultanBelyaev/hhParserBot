from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.config import settings
from app.database import Base, engine
from app.routers import auth, campaigns

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _migrate_schema() -> None:
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.session_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    yield


app = FastAPI(
    title="HH Parser AutoApply",
    description="Система автооткликов на hh.ru через парсинг (Playwright)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(campaigns.router, prefix="/api")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def admin_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    import time

    bot_status = "not_configured"
    if settings.telegram_bot_token.strip():
        hb = settings.bot_heartbeat_file
        if hb.exists():
            age_sec = time.time() - hb.stat().st_mtime
            bot_status = "running" if age_sec < 180 else f"stale ({int(age_sec)}s ago)"
        else:
            bot_status = "no_heartbeat"
    allowed = settings.telegram_allowed_user_ids.strip()
    return {
        "status": "ok",
        "mode": "playwright-parser",
        "bot": bot_status,
        "telegram_allowed_user_ids_set": bool(allowed),
    }
