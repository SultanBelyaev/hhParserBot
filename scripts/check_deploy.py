#!/usr/bin/env python3
"""Preflight checks before deploy (run in start.sh)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        warnings.append("TELEGRAM_BOT_TOKEN not set — bot disabled")

    data_dir = os.getenv("DATA_DIR", "/data").strip().strip('"').strip("'")
    session_file = os.getenv("SESSION_FILE", f"{data_dir}/session.json").strip().strip('"').strip("'")
    if not session_file.startswith("/"):
        warnings.append(f"SESSION_FILE should be absolute on Railway, got: {session_file}")

    db_url = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
    if db_url and not db_url.startswith("sqlite:////"):
        warnings.append(f"DATABASE_URL should use sqlite:////data/... on Railway, got: {db_url[:40]}")

    data_path = Path(data_dir)
    if os.getenv("RAILWAY_PUBLIC_DOMAIN") and not data_path.is_dir():
        warnings.append(
            f"DATA_DIR {data_dir} missing at startup — attach Railway Volume with mount path /data"
        )

    if os.getenv("RAILWAY_PUBLIC_DOMAIN") and not token:
        errors.append("RAILWAY_PUBLIC_DOMAIN set but TELEGRAM_BOT_TOKEN missing")

    has_session_b64 = bool(os.getenv("SESSION_JSON_BASE64", "").strip().strip('"'))
    if not has_session_b64 and not os.path.exists(session_file):
        warnings.append("No SESSION_JSON_BASE64 and no session file — use /login in Telegram")

    if os.getenv("HEADLESS", "true").strip().strip('"').lower() not in {"true", "1", "yes"}:
        warnings.append("HEADLESS should be true on Railway")

    for msg in warnings:
        print(f"WARNING: {msg}", file=sys.stderr)
    for msg in errors:
        print(f"ERROR: {msg}", file=sys.stderr)

    if errors:
        return 1
    print("Deploy preflight OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
