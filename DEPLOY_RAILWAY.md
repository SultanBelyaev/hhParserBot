# Деплой HH Parser на Railway

Пошаговая инструкция: API + Telegram-бот + Playwright-парсер в облаке.

## Что получится

| Компонент | В облаке |
|-----------|----------|
| FastAPI (`/api/health`, админка `/`) | ✅ |
| Telegram-бот | ✅ (доступ к `api.telegram.org` из EU/US) |
| Playwright-автоотклики | ✅ headless |
| Вход в HH через браузер | ❌ только локально → загрузка `session.json` |

---

## Предварительные требования

1. Аккаунт [Railway](https://railway.app)
2. Репозиторий на GitHub (проект должен быть в git)
3. Локально выполнен вход в HH:
   ```bash
   cd backend && python ../login.py
   ```
   Файл `data/session.json` должен существовать.

4. Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

---

## Шаг 1. Загрузить проект в GitHub

```bash
cd "/Users/sultanbelaev/Desktop/hh parser"
git init
git add .
git commit -m "Initial commit: HH parser with Railway deploy"
```

Создайте репозиторий на GitHub и выполните:

```bash
git remote add origin https://github.com/ВАШ_ЮЗЕР/hh-parser.git
git branch -M main
git push -u origin main
```

> **Важно:** `.env`, `data/session.json` и `*.db` в `.gitignore` — секреты в git не попадут.

---

## Шаг 2. Создать проект в Railway

1. Откройте [railway.app/new](https://railway.app/new)
2. **Deploy from GitHub repo** → выберите репозиторий `hh-parser`
3. Railway обнаружит `Dockerfile` и `railway.toml` автоматически

### Регион сервера

В **Settings → Region** выберите:
- `US West` или `EU West` — для стабильного доступа к Telegram API

---

## Шаг 3. Подключить Volume (постоянные данные)

Без volume база и сессия **сотрутся** при каждом redeploy.

1. В проекте Railway: **+ New** → **Volume**
2. Mount path: `/data`
3. Привяжите volume к сервису

---

## Шаг 4. Переменные окружения

**Settings → Variables** — добавьте:

### Обязательные

| Переменная | Значение |
|------------|----------|
| `TELEGRAM_BOT_TOKEN` | `"ваш_токен"` (в кавычках!) |
| `TELEGRAM_ALLOWED_USER_IDS` | ваш Telegram ID (узнать: `/start` у бота локально) |
| `DATA_DIR` | `/data` |
| `SESSION_FILE` | `/data/session.json` |
| `DATABASE_URL` | `sqlite:////data/hh_parser.db` |
| `HEADLESS` | `true` |

### Сессия HH (один из способов)

**Способ A — через base64 (проще для первого деплоя):**

```bash
chmod +x scripts/encode_session.sh
./scripts/encode_session.sh
```

Скопируйте вывод в переменную:

| Переменная | Значение |
|------------|----------|
| `SESSION_JSON_BASE64` | длинная строка base64 |

При каждом старте контейнер восстановит `/data/session.json`.

**Способ B — через Volume:**

1. Один раз залейте файл на volume через Railway CLI:
   ```bash
   npm i -g @railway/cli
   railway login
   railway link
   railway run bash
   # внутри контейнера — или scp/volume sync
   ```
2. Либо обновляйте `SESSION_JSON_BASE64` при истечении сессии.

### Опциональные (производительность)

```
APPLY_DELAY_MS=700
SCROLL_MAX=30
BLOCK_MEDIA=true
HIDE_SKIPPED_VACANCIES=false
```

### Прокси Telegram (обычно не нужен в облаке EU/US)

```
TELEGRAM_PROXY_URL=
```

---

## Шаг 5. Деплой

1. Railway автоматически соберёт Docker-образ и запустит `start.sh`
2. `start.sh` поднимает:
   - **Uvicorn** на порту `$PORT` (API + веб-админка)
   - **Telegram-бот** (если задан `TELEGRAM_BOT_TOKEN`)
3. Дождитесь статуса **Deployed** и зелёного healthcheck `/api/health`

### Проверка

```bash
curl https://ВАШ-ДОМЕН.railway.app/api/health
```

Ожидается:
```json
{"status":"ok","mode":"playwright-parser"}
```

Откройте в браузере: `https://ВАШ-ДОМЕН.railway.app`

---

## Шаг 6. Использование

1. Напишите боту в Telegram → `/start`
2. `/status` — проверка сессии HH
3. `/new` — создать кампанию
4. Запустите кампанию кнопкой ▶️

---

## Обновление сессии HH

Сессия hh.ru периодически истекает.

1. Локально:
   ```bash
   python login.py
   ./scripts/encode_session.sh
   ```
2. Обновите `SESSION_JSON_BASE64` в Railway Variables
3. **Redeploy** сервиса

---

## Два сервиса (опционально)

Если нужно разделить API и бота:

| Сервис | Start Command |
|--------|---------------|
| API | `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Bot | `cd backend && python run_bot.py` |

Оба должны использовать **один Volume** `/data` и одни переменные.

Для MVP достаточно одного сервиса (`start.sh`).

---

## Стоимость

- Railway: ~$5/мес (Hobby) + volume
- Playwright-образ ~1.5 GB — учитывайте при биллинге

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| `TimedOut` у бота | Смените регион на US/EU |
| `Сессия недействительна` | Обновите `SESSION_JSON_BASE64` |
| Healthcheck failed | Проверьте логи: `railway logs` |
| Chromium не найден | Убедитесь, что деплой идёт через Dockerfile, не Nixpacks |
| База пустая после redeploy | Подключите Volume на `/data` |

### Логи

```bash
railway logs --tail
```

---

## Локальная разработка (для сравнения)

```bash
cd "/Users/sultanbelaev/Desktop/hh parser"
source .venv/bin/activate
cd backend && uvicorn app.main:app --port 8001
```

Telegram-бот локально:
```bash
cd backend && python run_bot.py
```
