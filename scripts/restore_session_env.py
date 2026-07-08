#!/usr/bin/env python3
"""Restore session.json from SESSION_JSON_BASE64 (Railway Variables)."""
from __future__ import annotations

import base64
import binascii
import os
import sys
from pathlib import Path


def load_base64_from_env() -> str:
    parts_count = os.getenv("SESSION_JSON_B64_PARTS", "").strip()
    if parts_count.isdigit() and int(parts_count) > 0:
        chunks: list[str] = []
        for i in range(1, int(parts_count) + 1):
            part = os.getenv(f"SESSION_JSON_B64_{i}", "").strip()
            if not part:
                print(f"Missing SESSION_JSON_B64_{i}", file=sys.stderr)
                sys.exit(1)
            chunks.append(part)
        return "".join(chunks)

    raw = os.getenv("SESSION_JSON_BASE64", "").strip()
    if raw.startswith("SESSION_JSON_BASE64="):
        raw = raw.split("=", 1)[1].strip()
    return raw.strip('"').strip("'")


def main() -> int:
    encoded = load_base64_from_env()
    if not encoded:
        print("SESSION_JSON_BASE64 not set — skip session restore", file=sys.stderr)
        return 0

    session_file = Path(os.getenv("SESSION_FILE", "/data/session.json"))
    if not session_file.is_absolute():
        data_dir = Path(os.getenv("DATA_DIR", "/data"))
        session_file = data_dir / session_file

    session_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        print(f"WARNING: invalid SESSION_JSON_BASE64: {exc}", file=sys.stderr)
        print("Regenerate: ./scripts/encode_session.sh", file=sys.stderr)
        return 1

    session_file.write_bytes(payload)
    print(f"Session restored to {session_file} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
