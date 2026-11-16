# Дорожня карта розвитку StatMonitor (SDD Roadmap)

> **Статус**: 16 з 17 кроків реалізовано (Shipped) · 1 заплановано (Idea)  
> **Оновлено**: 16.11.2026  
> **Фокус**: Вдосконалення планувальника (Scheduler Evolution), спостережливість (Web Dashboard) та міграції БД

---

## 🟩 Wave 1: Базовий збір даних та сховище (Shipped)

### 1. Dynamic schema detection & multi-odds ingestion
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Автоматичне визначення колонок у таблицях Supabase (`odds_history`, `events`) та безпечна нормалізація невідповідностей назв (`event_id`/`match_id`, `price`/`odds`, `point`/`line`).
* **Залежності**: Немає

### 2. Odds history & 4-day rolling retention
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Збереження часових рядів котирувань та автоматична ротація (очищення записів, старіших за 4 дні) для утримання лімітів Supabase.
* **Залежності**: потрібен крок 1

### 3. Telegram HTML chunking & delivery engine
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Відправка повідомлень через Telegram Bot API з автоматичним розбиттям довгих текстів на блоки $\le 3800$ символів, обробкою помилок парсингу HTML та rate-limit павзами (429).
* **Залежності**: Немає

---

## 🟩 Wave 2: Аналітика, AI та Paper Trading (Shipped)

### 4. Matplotlib dynamic drop chart generator
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Побудова графіків падіння коефіцієнтів у пам'яті (`io.BytesIO`) у часовому поясі `Europe/Kyiv` та відправка як фото в Telegram.
* **Залежності**: потрібен крок 2, потрібен крок 3

### 5. Multi-model Gemini AI analyzer with failover
* **Розмір**: M
* **Статус**: 🟩 Shipped
* **Опис**: Автоматичний аналіз прогрузів спортивних ліній за допомогою Google Gemini API з каскадним перемиканням моделей при 429/404 (`gemini-3.5-flash-lite` $\rightarrow$ `gemini-2.5-flash-lite` $\rightarrow$ `gemini-2.5-flash` $\rightarrow$ `gemini-3.8-flash`) та кешуванням вердиктів.
* **Залежності**: потрібен крок 3

### 6. Paper Bank engine & auto-staking
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Віртуальний банк (початковий 10,000 грн), динамічний розрахунок розміру ставки (2–4% від вільного банку залежно від коефіцієнта) та захист від дублікатів ставок.
* **Залежності**: потрібен крок 5

### 7. Post-match score settlement & daily report
* **Розмір**: M
* **Статус**: 🟩 Shipped
* **Опис**: Автоматичний розрахунок результатів (`WON`, `LOST`, `VOID`) за завершеними матчами (The Odds API Scores), фіксація прибутку/збитку та щоденний звіт о 08:00 з показником ROI.
* **Залежності**: потрібен крок 6, потрібен крок 3

---

## 🟩 Wave 3: Вдосконалення планувальника (Scheduler Evolution)

### 8. Dynamic schedule generator based on match kickoff times
* **Розмір**: M
* **Статус**: 🟩 Shipped
* **Опис**: Модуль `scheduler.py` аналізує розклад найближчих матчів у базі (`events.commence_time`) та активні ставки (`paper_bets`) і формує кластеризовані тригери:
  - `PRE_MATCH`: за 15 хвилин до старту блоку матчів для фіксації фінальних прогрузів.
  - `SETTLE`: через 115 хвилин після старту для розрахунку результату.
  - Зберігає план у `scheduler_plan` та надсилає розклад у Telegram.
* **Залежності**: потрібен крок 2, потрібен крок 7

### 9. GitHub Actions cron healthcheck & missed-run watchdog
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Модуль `watchdog.py` фіксує пульс у таблиці `system_heartbeat` (час, тривалість, метадані), виявляє простій планувальника $> 150$ хв та прострочені контрольні точки з `scheduler_plan` ($> 25$ хв), формує тривожне сповіщення в Telegram та підтримує зовнішній HTTP пінг (`HEALTHCHECK_URL`).
* **Залежності**: потрібен крок 3, потрібен крок 8

### 10. Smart rate-limiter & API credit budget allocator
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Контролер балансу запитів до The Odds API (`statmonitor/limiter.py` + `sports_poll_log`). Динамічно класифікує ліги за терміновістю (`HOT` < 6 год, `WARM` 6..24 год, `COLD` > 24 год) та бюджетними режимами (`NORMAL`, `ECO`, `CRITICAL`), знижуючи витрату квоти на 60–80%.
* **Залежності**: потрібен крок 1, потрібен крок 8

### 11. Hybrid runner support (External webhook / Cloud backup)
* **Розмір**: M
* **Статус**: 🟩 Shipped
* **Опис**: Реалізовано модуль `trigger_dispatch.py` (CLI + API для негайного запуску `workflow_dispatch`), безсерверний шлюз `deploy/cloudflare_webhook.js` для безкоштовного хостингу на Cloudflare Workers та підтримку вхідного параметра `trigger_source` у GitHub Actions воркфлоу.
* **Залежності**: потрібен крок 9

---

## 🟪 Wave 4: Архітектурна якість та надійність

### 12. Unit test suite for pick parsing & score evaluation
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Покриття автотестами (`test_eval_picks.py`) критичних чистих функцій `format_pick()`, `eval_outcome()`, `extract_short_pick()`. 17 нових тест-кейсів для 1X2, фор, тоталів футболу та баскетболу, очищення HTML/Markdown та відсікання кефів.
* **Залежності**: потрібен крок 7

### 13. Modular code decomposition
* **Розмір**: M
* **Статус**: 🟩 Shipped
* **Опис**: Розбиття 566-рядкового `main.py` на окремі імпортовані модулі в пакеті `statmonitor`: `config`, `database`, `notifier`, `fetcher`, `chart`, `ai`, `paper_trading`, `pipeline`. Забезпечено повну зворотну сумісність та 100% проходження тестів.
* **Залежності**: потрібен крок 12

### 14. Dedicated DB migrations & view optimization
* **Розмір**: S
* **Статус**: 🟩 Shipped
* **Опис**: Версіонований міграційний раннер (`migrate.py` + `migrations/*.sql`), B-Tree індекси для `odds_history`, `events`, `paper_bets` та оптимізоване SQL-представлення `v_odds_alerts` для прискорення детекції прогрузів.
* **Залежності**: потрібен крок 2

---

## 🟪 Wave 5: Розширені інтерактивні можливості

### 15. Telegram interactive bot commands (`/status`, `/bank`, `/run_now`)
* **Розмір**: M
* **Статус**: 🟩 Shipped
* **Опис**: Інтерактивний бот-асистент (`statmonitor/bot.py` + `bot_service.py`). Підтримка команд `/status`, `/bank`, `/bets`, `/today`, `/schedule`, `/run_now`, клавіатури швидких дій, перевірки авторизації за `TG_CHAT_ID` та режимів daemon / single-run.
* **Залежності**: потрібен крок 13

### 16. Multi-sport & custom league configuration matrix
* **Розмір**: S
* **Статус**: 🟪 Idea
* **Опис**: Винесення списку турнірів і порогів падіння котирувань у конфігураційний файл/таблицю замість жорсткого коду в скрипті.
* **Залежності**: потрібен крок 13

---

## 🟩 Wave 6: Спостережливість та Веб-інтерфейс (Shipped)

### 17. Web dashboard & Observability UI
* **Розмір**: L
* **Статус**: 🟩 Shipped
* **Опис**: Інтерактивний веб-дашборд на Streamlit (`dashboard.py` + `requirements.txt`) із візуалізацією капіталу (графік балансу), активними та розрахованими ставками, картками AI-вердиктів Gemini, монітором пульсу Watchdog та кнопкою запуску моніторингу через вебхук.
* **Залежності**: потрібен крок 6, потрібен крок 7, потрібен крок 11
