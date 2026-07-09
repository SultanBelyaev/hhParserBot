#!/usr/bin/env bash
set -euo pipefail

cd /app/backend

export DATA_DIR="${DATA_DIR:-/data}"
export SESSION_FILE="${SESSION_FILE:-/data/session.json}"
export DATABASE_URL="${DATABASE_URL:-sqlite:////data/hh_parser.db}"
export PORT="${PORT:-8080}"

# Относительный SESSION_FILE из .env → абсолютный путь на volume
if [[ "${SESSION_FILE}" != /* ]]; then
  export SESSION_FILE="${DATA_DIR}/${SESSION_FILE#./}"
fi

mkdir -p "${DATA_DIR}"
mkdir -p "$(dirname "${SESSION_FILE}")"

if [ -n "${SESSION_JSON_BASE64:-}" ] || [ -n "${SESSION_JSON_B64_PARTS:-}" ]; then
  python3 /app/scripts/restore_session_env.py || true
fi

python3 /app/scripts/check_deploy.py || true

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -z "${RAILWAY_PUBLIC_DOMAIN:-}" ] && [ "${TELEGRAM_USE_WEBHOOK:-}" != "true" ]; then
  echo "[bot] local polling mode — run: python run_bot.py (separate terminal)"
else
  echo "Telegram bot: webhook mode (inside uvicorn, domain=${RAILWAY_PUBLIC_DOMAIN:-PUBLIC_URL})"
echo "Redeploy: pick up TELEGRAM_BOT_TOKEN from Railway Variables ($(date -u +%Y-%m-%dT%H:%MZ))"
fi

echo "Starting API on port ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
