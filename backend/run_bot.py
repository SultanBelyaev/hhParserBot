#!/usr/bin/env python3
"""Запуск Telegram-бота админки."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

from app.bot.handlers import run_bot

if __name__ == "__main__":
    run_bot()
