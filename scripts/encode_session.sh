#!/usr/bin/env bash
# Кодирует data/session.json в base64 для переменной Railway SESSION_JSON_BASE64
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="${ROOT}/data/session.json"

if [ ! -f "$SESSION" ]; then
  echo "Файл не найден: $SESSION"
  echo "Сначала выполните локально: python login.py"
  exit 1
fi

echo "Скопируйте значение ниже в Railway → Variables → SESSION_JSON_BASE64"
echo ""
base64 < "$SESSION" | tr -d '\n'
echo ""
echo ""
