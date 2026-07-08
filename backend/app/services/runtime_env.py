"""Runtime environment helpers."""
from __future__ import annotations

import os


def is_railway_runtime() -> bool:
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PUBLIC_DOMAIN"))


def require_headless_browser() -> bool:
    """Cloud servers have no X11 — browser must run headless."""
    if settings_headless():
        return True
    return not is_railway_runtime() and bool(os.getenv("DISPLAY"))


def settings_headless() -> bool:
    from app.config import settings

    return settings.headless
