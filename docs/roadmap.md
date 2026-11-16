# Дорожня карта розвитку StatMonitor (SDD Roadmap)

> **Статус**: 9 з 17 кроків реалізовано (Shipped) · 1 в процесі (In Progress)  
> **Оновлено**: 16.11.2026  
> **Фокус**: Вдосконалення планувальника (Scheduler Evolution) та стабілізація кодової бази

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
* **Статус**: 🟧 In Progress (Next)
* **Опис**: Контролер балансу запитів до The Odds API. Динамічно зменшує частоту опитування другорядних ліг, коли залишок кредитів (`x-requests-remaining`) падає нижче критичного порогу, пріоритезуючи топ-події.
* **Залежності**: потрібен крок 1, потрібен крок 8

### 11. Hybrid runner support (External webhook / Cloud backup)
* **Розмір**: M
* **Статус**: ⬜ To Do
* **Опис**: Резервний тригер через безкоштовний сервіс (наприклад, Cron-job.org / Cloudflare Worker webhook / modal / serverless cron), що викликає GitHub Actions `workflow_dispatch` за точним розкладом без затримок черг.
* **Залежності**: потрібен крок 9

---

## 🟪 Wave 4: Архітектурна якість та надійність

### 12. Unit test suite for pick parsing & score evaluation
* **Розмір**: S
* **Статус**: 🟪 Idea
* **Опис**: Покриття автотестами (`pytest`) критичних чистих функцій `format_pick()`, `eval_outcome()`, `extract_short_pick()`.
* **Залежності**: потрібен крок 7

### 13. Modular code decomposition
* **Розмір**: M
* **Статус**: 🟪 Idea
* **Опис**: Розбиття 566-рядкового `main.py` на окремі імпортовані модулі: `statmonitor.fetcher`, `statmonitor.database`, `statmonitor.ai`, `statmonitor.scheduler`, `statmonitor.notifier`.
* **Залежності**: потрібен крок 12

### 14. Dedicated DB migrations & view optimization
* **Розмір**: S
* **Статус**: 🟪 Idea
* **Опис**: Оптимізація індексів та SQL-в'юшки `v_odds_alerts` для прискорення вибірки прогрузів при збільшенні обсягу даних.
* **Залежності**: потрібен крок 2

---

## 🟪 Wave 5: Розширені інтерактивні можливості

### 15. Telegram interactive bot commands (`/status`, `/bank`, `/run_now`)
* **Розмір**: M
* **Статус**: 🟪 Idea
* **Опис**: Перетворення бота зі суто сповіщувача на інтерактивного асистента через Webhook або Polling.
* **Залежності**: потрібен крок 13

### 16. Multi-sport & custom league configuration matrix
* **Розмір**: S
* **Статус**: 🟪 Idea
* **Опис**: Винесення списку турнірів і порогів падіння котирувань у конфігураційний файл/таблицю замість жорсткого коду в скрипті.
* **Залежності**: потрібен крок 13

---

## ⬜ Поза хвилями (Fog / Backlog)

### 17. Web dashboard & Observability UI
* **Розмір**: L
* **Статус**: ⬜ Fog
* **Опис**: Легкий веб-інтерфейс (Streamlit або Next.js) для перегляду історії банку, графіка приросту капіталу та списку активних ставок.
