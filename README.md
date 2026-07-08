# HH Parser — Система автооткликов на hh.ru

Массовые автоотклики на вакансии hh.ru через **парсинг** (Playwright). Управление — **только через Telegram-бота**.

## Архитектура

```
┌─────────────────────────────────────────────────────────┐
│              Telegram-бот                                │
│  • Вход в HH (телефон + SMS)                            │
│  • Создание и запуск кампаний                           │
│  • Статистика и логи откликов                          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              FastAPI + Playwright Worker                 │
│  • SQLite (кампании, логи)                              │
│  • Фоновый воркер автооткликов                          │
│  • Webhook для Telegram (Railway)                       │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   hh.ru                                  │
└─────────────────────────────────────────────────────────┘
```

## Быстрый старт

### 1. Установка

```bash
cd "hh parser"
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python3 -m playwright install chromium
cp .env.example .env
```

### 2. Настройка `.env`

```env
TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather
TELEGRAM_ALLOWED_USER_IDS=ваш_telegram_id
```

### 3. Запуск

**Локально (API + бот polling):**

```bash
cd "/Users/sultanbelaev/Desktop/hh parser"
source .venv/bin/activate
cd backend && uvicorn app.main:app --port 8001
```

В другом терминале (если uvicorn без webhook):

```bash
cd backend && python run_bot.py
```

**Или только бот локально:**

```bash
cd backend && python run_bot.py
```

### 4. Вход в HH

Через бота: `/login` или кнопка **🔐 Войти** → телефон → SMS-код.

Альтернатива — CLI:

```bash
python login.py
```

## Команды бота

| Команда / кнопка | Действие |
|------------------|----------|
| `/start` | Приветствие и меню |
| `/status` | Статус сессии HH |
| `/login` | Вход в HH |
| `/logout` | Удалить сессию |
| `/campaigns` | Список кампаний |
| `/new` | Новая кампания |
| Кнопки под кампанией | Статистика, лог, ▶️, ⏹ |

## Деплой в облако

См. **[DEPLOY_RAILWAY.md](./DEPLOY_RAILWAY.md)** и **[AUTO_DEPLOY.md](./AUTO_DEPLOY.md)**.

## Структура проекта

```
hh parser/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI: health + Telegram webhook
│   │   ├── bot/              # Telegram-бот
│   │   ├── models.py
│   │   └── services/         # scraper, worker, auth
│   ├── run_bot.py            # Локальный polling-бот
│   └── requirements.txt
├── login.py                  # CLI-вход в HH
├── scripts/
└── .env
```

## API (служебный)

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Healthcheck (Railway) |
| POST | `/telegram/webhook` | Webhook Telegram (Railway) |

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | — | Токен бота |
| `TELEGRAM_ALLOWED_USER_IDS` | — | Telegram ID (через запятую) |
| `HEADLESS` | `true` | Headless-браузер |
| `SESSION_FILE` | `data/session.json` | Сессия HH |
| `APPLY_DELAY_MS` | `700` | Пауза между откликами |

## Ограничения

- hh.ru может менять вёрстку — селекторы потребуют обновления
- Сессия периодически истекает — повторный `/login`
- Автоматизация может нарушать ToS hh.ru
