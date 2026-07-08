#!/usr/bin/env bash
# Кодирует session.json (cookies-only) в base64 для Railway SESSION_JSON_BASE64
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/encode_session.py" "$@"
