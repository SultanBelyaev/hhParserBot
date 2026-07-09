#!/usr/bin/env python3
"""Print Telegram bot usernames and webhook URLs (no secrets in output)."""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env_tokens() -> list[tuple[str, str]]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return []
    tokens: list[tuple[str, str]] = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            if raw and raw != "your_bot_token_here":
                tokens.append(("TELEGRAM_BOT_TOKEN", raw))
    return tokens


def _api(token: str, method: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read())


def _mask_token(token: str) -> str:
    bot_id = token.split(":", 1)[0]
    return f"{bot_id}:****"


def _describe_token(label: str, token: str) -> None:
    try:
        me = _api(token, "getMe")["result"]
        wh = _api(token, "getWebhookInfo")["result"]
    except urllib.error.URLError as exc:
        print(f"{label} ({_mask_token(token)}): API error — {exc}")
        return

    username = me.get("username", "?")
    webhook = wh.get("url") or "(empty — polling or webhook not set)"
    pending = wh.get("pending_update_count", 0)
    last_error = wh.get("last_error_message") or "none"

    print(f"{label} ({_mask_token(token)})")
    print(f"  username: @{username}")
    print(f"  webhook:  {webhook}")
    print(f"  pending:  {pending}")
    print(f"  last_err: {last_error}")
    print()


def main() -> int:
    tokens = _load_env_tokens()
    extra = os.environ.get("CHECK_TELEGRAM_TOKEN", "").strip()
    if extra:
        tokens.append(("CHECK_TELEGRAM_TOKEN", extra.strip('"\'')))

    if not tokens:
        print("No TELEGRAM_BOT_TOKEN in .env", file=sys.stderr)
        return 1

    print("Telegram webhook check\n")
    for label, token in tokens:
        if not re.match(r"^\d+:.+", token):
            print(f"{label}: invalid token format", file=sys.stderr)
            continue
        _describe_token(label, token)

    print("HH Parser Railway health (if deployed):")
    try:
        with urllib.request.urlopen(
            "https://hhparserbot-production.up.railway.app/api/health",
            timeout=15,
        ) as resp:
            data = json.loads(resp.read())
        print(f"  bot: {data.get('bot')}")
        print(f"  username: {data.get('bot_username')}")
        print(f"  webhook_ok: {data.get('webhook_url_ok')}")
        print(f"  updates_processed: {data.get('updates_processed')}")
    except urllib.error.URLError as exc:
        print(f"  unavailable: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
