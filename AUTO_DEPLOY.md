# Авто-деплой на Railway

Цепочка: **push в `main` на GitHub → Railway автоматически пересобирает и деплоит**.

## Один раз в Railway (5 минут)

### 1. Подключить GitHub-репозиторий

1. [railway.app/new](https://railway.app/new) → **Deploy from GitHub repo**
2. Выберите **`SultanBelyaev/hhParserBot`**
3. Если репозитория нет в списке:
   - GitHub → **Settings → Applications → Railway → Configure**
   - Дайте доступ к репозиторию `hhParserBot`

### 2. Включить авто-деплой

1. Откройте сервис → **Settings**
2. **Source** → **Connect Repo** (если ещё не подключён)
3. **Branch**: `main`
4. **Automatic Deployments**: **Enable**

После этого каждый `git push` в `main` запускает новый деплой.

### 3. (Опционально) Wait for CI

Если хотите, чтобы Railway ждал успешного GitHub Actions перед деплоем:

1. **Settings → Deploy → Wait for CI** → включить
2. В репозитории уже есть workflow `.github/workflows/ci.yml`

---

## Как это работает дальше

```bash
# Локально — я или вы пушите изменения:
python3 scripts/git_push.py "описание изменений"

# Railway автоматически:
# 1. Получает webhook от GitHub
# 2. Собирает Docker-образ (Dockerfile)
# 3. Запускает start.sh (API + бот)
# 4. Проверяет /api/health
```

Смотреть деплои: **Railway → Deployments**.

---

## Переменные (не сбрасываются при авто-деплое)

Задайте один раз в **Variables** — они сохраняются между деплоями:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=...
DATA_DIR=/data
SESSION_FILE=/data/session.json
DATABASE_URL=sqlite:////data/hh_parser.db
HEADLESS=true
SESSION_JSON_BASE64=...   # из ./scripts/encode_session.sh
```

Volume на `/data` тоже подключается один раз.

---

## Ручной деплой (если нужно)

- Railway: **Cmd+K** → **Deploy Latest Commit**
- Или push пустого коммита:
  ```bash
  git commit --allow-empty -m "Trigger redeploy"
  python3 scripts/git_push.py "Trigger redeploy"
  ```

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| Push есть, деплоя нет | Settings → Automatic Deployments → **Enable** |
| Репозиторий не виден | GitHub → Railway App → дать доступ к `hhParserBot` |
| Деплой skipped | Изменились только `.md` — см. `watchPatterns` в `railway.toml` |
| Push rejected: workflow scope | У classic-токена включите галочку **`workflow`** (Settings → Developer settings → Tokens) |
