#!/usr/bin/env bash
set -euo pipefail

cd /app/backend

mkdir -p "${DATA_DIR:-/data}"

restore_session_from_base64() {
  local target="${SESSION_FILE:-/data/session.json}"
  if ! echo "$1" | base64 -d > "$target" 2>/dev/null; then
    echo "WARNING: failed to decode SESSION_JSON_BASE64 — check Railway variable" >&2
    return 1
  fi
  echo "Session restored to $target ($(wc -c < "$target") bytes)"
}

if [ -n "${SESSION_JSON_B64_PARTS:-}" ]; then
  combined=""
  i=1
  while [ "$i" -le "$SESSION_JSON_B64_PARTS" ]; do
    var_name="SESSION_JSON_B64_${i}"
    part="${!var_name:-}"
    if [ -z "$part" ]; then
      echo "Missing ${var_name}" >&2
      exit 1
    fi
    combined+="$part"
    i=$((i + 1))
  done
  restore_session_from_base64 "$combined" || true
elif [ -n "${SESSION_JSON_BASE64:-}" ]; then
  restore_session_from_base64 "$SESSION_JSON_BASE64" || true
fi

export DATA_DIR="${DATA_DIR:-/data}"
export SESSION_FILE="${SESSION_FILE:-/data/session.json}"
export DATABASE_URL="${DATABASE_URL:-sqlite:////data/hh_parser.db}"
export PORT="${PORT:-8080}"

echo "Starting API on port ${PORT}..."
uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" &
API_PID=$!

BOT_PID=""
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  (
    while true; do
      echo "[bot] starting..."
      python run_bot.py 2>&1 | while IFS= read -r line; do echo "[bot] $line"; done
      code=${PIPESTATUS[0]}
      echo "[bot] exited with code ${code}, restart in 15s"
      sleep 15
    done
  ) &
  BOT_PID=$!
else
  echo "TELEGRAM_BOT_TOKEN not set — bot skipped"
fi

term_handler() {
  kill "$API_PID" 2>/dev/null || true
  [ -n "$BOT_PID" ] && kill "$BOT_PID" 2>/dev/null || true
}
trap term_handler SIGTERM SIGINT

# Keep API alive even if bot exits (Railway healthcheck depends on HTTP)
wait "$API_PID"
