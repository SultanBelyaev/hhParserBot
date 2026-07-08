#!/usr/bin/env python3
"""Encode session.json for Railway (cookies-only fits 32KB variable limit)."""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "data" / "session.json"
RAILWAY_LIMIT = 32768
SAFE_LIMIT = 30000


def load_session(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def slim_session(data: dict) -> dict:
    """HH auth needs cookies; localStorage in origins bloats the file."""
    return {"cookies": data.get("cookies", []), "origins": []}


def encode_bytes(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Encode session.json for Railway Variables")
    parser.add_argument("--session-file", type=Path, default=DEFAULT_SESSION)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include localStorage (usually too large for Railway Variables)",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="Print chunked variables if payload exceeds Railway limit",
    )
    args = parser.parse_args()

    if not args.session_file.exists():
        print(f"Файл не найден: {args.session_file}", file=sys.stderr)
        print("Сначала: python login.py", file=sys.stderr)
        return 1

    data = load_session(args.session_file)
    if not args.full:
        data = slim_session(data)

    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    encoded = encode_bytes(raw)
    mode = "full" if args.full else "cookies-only"

    print(f"# mode: {mode}, json={len(raw)} bytes, base64={len(encoded)} chars", file=sys.stderr)

    if len(encoded) <= RAILWAY_LIMIT and not args.split:
        print("SESSION_JSON_BASE64=" + encoded)
        return 0

    if len(encoded) <= RAILWAY_LIMIT and args.split:
        print("SESSION_JSON_BASE64=" + encoded)
        return 0

    if not args.split:
        print(
            f"Ошибка: base64={len(encoded)} > лимит Railway {RAILWAY_LIMIT}.",
            file=sys.stderr,
        )
        print("Используйте cookies-only (без --full) или загрузку на Volume:", file=sys.stderr)
        print("  ./scripts/upload_session_railway.sh", file=sys.stderr)
        return 1

    parts = [encoded[i : i + SAFE_LIMIT] for i in range(0, len(encoded), SAFE_LIMIT)]
    print(f"SESSION_JSON_B64_PARTS={len(parts)}")
    for idx, part in enumerate(parts, start=1):
        print(f"SESSION_JSON_B64_{idx}={part}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
