#!/usr/bin/env bash
# Остановить локальный Telegram-бот (чтобы не конфликтовал с Railway)
set -euo pipefail

if pgrep -f "run_bot.py" >/dev/null 2>&1; then
  pkill -f "run_bot.py" || true
  echo "Локальный run_bot.py остановлен."
else
  echo "Локальный run_bot.py не запущен."
fi

if pgrep -f "uvicorn app.main:app" >/dev/null 2>&1; then
  echo "Примечание: uvicorn всё ещё запущен (API). Это нормально, бот отдельно."
fi

echo "Теперь redeploy на Railway — бот должен заработать."
