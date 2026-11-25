# Налаштування Cloudflare Worker Webhook (Button-Only Mode)

> **Поточний режим (Варіант А)**: Регулярний Cron у Cloudflare (`wrangler.toml`, `cloudflare/wrangler.toml`) та GitHub Actions (`.github/workflows/scheduler.yml`) **вимкнено**, оскільки безперервний 24/7 моніторинг перенесено на **Render.com** (`render_service.py`). Cloudflare Worker `statmonitor.symchak.workers.dev` працює виключно як захищений HTTP-вебхук для ручного запуску з Web Dashboard (`⚡ Запуск`).

---

## ⚙️ Конфігурація Cloudflare Workers (Git Integration)

У Cloudflare Dashboard (`Workers & Pages` $\rightarrow$ `statmonitor` $\rightarrow$ `Settings`):

### 1. Збірка та деплой (`Builds`)
- Підключено репозиторій `vsymchak/StatMonitor` (гілка `main`).
- Команда деплою: `npx wrangler deploy` (використовує кореневий `wrangler.toml`, який вказує на `deploy/cloudflare_webhook.js`).
- Секцію `[triggers] crons` видалено — розклади не створюються при деплої, а `scheduled()` у коді працює як безпечна заглушка.

### 2. Змінні та секрети (`Variables and secrets`)
Переконайтеся, що налаштовані:
- `GITHUB_TOKEN` (або `GH_PAT`, Secret) — GitHub Personal Access Token із правами на запуск `workflow_dispatch` (`actions:write` / `repo`).
- `SECRET_KEY` (Secret) — секретний ключ доступу; **повинен точно збігатися** зі значенням `SECRET_KEY` у **Streamlit Cloud → Secrets**.

### 3. Перевірка роботи
- **Відкриття базового URL** (`https://statmonitor.symchak.workers.dev/` або кнопка **Visit** у Cloudflare): повертає `200 OK` зі статусом `{"status":"ok","mode":"button_only",...}` **без** запуску GitHub Actions.
- **Ручний запуск із дашборду** (`⚡ Запуск` або `⚡ Перезапустити моніторинг зараз`): передає `?secret=<SECRET_KEY>&source=dashboard_button` і ставить у чергу `.github/workflows/scheduler.yml` через `workflow_dispatch`.
- **Помилка `401 Unauthorized: Invalid secret`**: свідчить про невідповідність `SECRET_KEY` між Streamlit Secrets та Cloudflare `Variables and secrets`.
