#!/usr/bin/env bash
# Загружает session.json на Railway Volume (/data/session.json)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="${ROOT}/data/session.json"

if [ ! -f "$SESSION" ]; then
  echo "Файл не найден: $SESSION"
  echo "Сначала: python login.py"
  exit 1
fi

if ! command -v railway >/dev/null 2>&1; then
  echo "Установите Railway CLI:"
  echo "  npm i -g @railway/cli"
  echo "  railway login"
  echo "  railway link"
  exit 1
fi

echo "Загрузка $SESSION → /data/session.json на Railway Volume..."
echo "(Нужен подключённый Volume с mount path /data)"
echo ""

cat "$SESSION" | railway run sh -c 'mkdir -p /data && cat > /data/session.json && wc -c /data/session.json'

echo ""
echo "Готово. В Railway Variables НЕ нужен SESSION_JSON_BASE64 — достаточно:"
echo "  DATA_DIR=/data"
echo "  SESSION_FILE=/data/session.json"
