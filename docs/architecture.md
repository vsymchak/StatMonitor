# Візуальна архітектура системи StatMonitor

> **Проєкт**: StatMonitor — інтелектуальна система спортивного моніторингу прогрузів, віртуального трейдингу (Paper Trading), спостережливості (Web Dashboard) та предиктивної AI-аналітики.  
> **Версія**: 3.4 (Еволюція: Мульти-ключовий монітор квот The Odds API в адмін-панелі + Динамічне автовиявлення тенісних турнірів + 86 Unit Tests)  
> **Оновлено**: 18.11.2026

---

## 1. Загальна схема системи (End-to-End System Architecture)

```mermaid
flowchart TD
    classDef ext fill:#1e293b,stroke:#475569,color:#f8fafc,stroke-width:1px;
    classDef gw fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe,stroke-width:2px;
    classDef core fill:#064e3b,stroke:#10b981,color:#d1fae5,stroke-width:2px;
    classDef pkg fill:#14532d,stroke:#16a34a,color:#dcfce7,stroke-width:1.5px;
    classDef data fill:#701a75,stroke:#d946ef,color:#fae8ff,stroke-width:2px;
    classDef ai fill:#7c2d12,stroke:#f97316,color:#ffedd5,stroke-width:2px;
    classDef notify fill:#14532d,stroke:#22c55e,color:#dcfce7,stroke-width:2px;
    classDef ui fill:#312e81,stroke:#6366f1,color:#e0e7ff,stroke-width:2px;
    classDef test fill:#334155,stroke:#94a3b8,color:#f1f5f9,stroke-width:1px,stroke-dasharray: 3 3;

    subgraph Triggers["🌐 1. Рівень тригерів і планувальника"]
        CronJob["Cron-job.org / Webhook<br>Точний розклад по секундах"]:::ext
        GHFallbackCron["GitHub Actions Fallback Cron<br>schedule: 15,45 * * * *"]:::ext
        ManualAdmin["Admin / CLI<br>python trigger_dispatch.py"]:::ext
        DashboardTrigger["Web Dashboard Button<br>⚡ Запустити моніторинг"]:::ui
        CFWorker["Cloudflare Worker<br>(deploy/cloudflare_webhook.js)<br>Захист ?secret=***"]:::gw
    end

    subgraph GitHubInfra["⚙️ 2. Інфраструктура виконання"]
        GHAPI["GitHub REST API<br>/workflows/scheduler.yml/dispatches"]:::gw
        GHRunner["GitHub Actions Runner (Ubuntu)<br>python -u main.py"]:::core
    end

    subgraph Ingestion["📡 3. Збір даних (Data Ingestion)"]
        OddsAPI["The Odds API v4<br>14 футбольних ліг, NBA, теніс<br>(API_KEY + RESERVE)"]:::ext
    end

    subgraph CoreEngine["🧠 4. Ядро обробки (StatMonitor Core & Package)"]
        MainPy["main.py (Лаконічний оркестратор)"]:::core
        RecalcPy["recalc_odds.py<br>CLI перерахунку та редагування ставок"]:::core
        
        subgraph StatMonitorPkg["📦 statmonitor/ (Модульний пакет)"]
            ModPipeline["pipeline.py<br>Конвеєр перевірки та алертингу"]:::pkg
            ModFetcher["fetcher.py<br>API запити та ротація ключів"]:::pkg
            ModLimiter["limiter.py<br>HOT/WARM/COLD ліги & Eco-режими"]:::pkg
            ModDB["database.py<br>Пул з'єднань та адаптація схеми"]:::pkg
            ModAI["ai.py<br>Gemini клієнт + Search Grounding"]:::pkg
            ModPaper["paper_trading.py<br>Стейкінг, розрахунок, медіана БК, edit_odds"]:::pkg
            ModChart["chart.py<br>Matplotlib тренди в пам'яті"]:::pkg
            ModNotify["notifier.py<br>Telegram HTML delivery & chunking"]:::pkg
            ModBot["bot.py<br>Двосторонній асистент /status /bank /edit_odds"]:::pkg
            ModLeague["league_config.py<br>Завантаження матриці ліг config/leagues.json"]:::pkg
            ModConfig["config.py<br>Константи, часовий пояс, ліги"]:::pkg
        end

        Watchdog["sys_watchdog.py<br>Pulse & Missed Checkpoints (Dedup)"]:::core
        SchedEngine["scheduler.py<br>Кластеризація, автофіксація EXECUTED"]:::core
        MigrateRunner["migrate.py<br>Версіоновані міграції БД"]:::core
    end

    subgraph AI["🤖 5. Штучний інтелект (AI Layer)"]
        GeminiAPI["Google Gemini API<br>Failover: 3.5-flash-lite ➔ 2.5-flash ➔ 3.8-flash<br>Google Search Grounding<br>Склади, травми, чутки, інсайди"]:::ai
    end

    subgraph Storage["💾 6. Сховище даних (Supabase PostgreSQL)"]
        DB[("PostgreSQL 15+<br>public schema")]:::data
        T_Migrations["schema_migrations (001-005)"]:::data
        T_Events["events (індекс на commence_time)"]:::data
        T_Odds["odds_history (індекси за часом та маркетом)"]:::data
        V_Alerts["v_odds_alerts (Optimized 96h Window View)"]:::data
        T_AI["ai_match_analysis"]:::data
        T_Bets["paper_bets (індекс за статусом і часом)"]:::data
        T_Sched["scheduler_plan (дедуплікація точок)"]:::data
        T_Poll["sports_poll_log (облік опитування ліг)"]:::data
        T_Beat["system_heartbeat"]:::data
    end

    subgraph TestSuite["🧪 7. Шар якості та тестування (86 unit-тестів)"]
        TestLeague["test_league_config.py (6 тестів)<br>Матриця ліг, тенісні фолбеки, пороги"]:::test
        TestBot["test_bot.py (15 тестів)<br>Команди /bank /status /bets /edit_odds, RBAC"]:::test
        TestLimiter["test_rate_limiter.py (6 тестів)<br>HOT/WARM/COLD, Eco-режими, квоти"]:::test
        TestEval["test_eval_picks.py (33 тести)<br>format_pick, eval_outcome, median_odds, edit_odds"]:::test
        TestKelly["test_kelly.py (6 тестів)<br>Критерій Келлі, clamping 1-5%, стейкінг"]:::test
        TestModules["test_modules.py (11 тестів)<br>Ізоляція statmonitor/, мульти-квота, теніс auto-discovery"]:::test
        TestDashboard["test_dashboard.py (6 тестів)<br>Метрики банку, час за Києвом, Odds quota live/heartbeat"]:::test
        TestSched["test_scheduler.py<br>Кластеризація, точки, маркування EXECUTED"]:::test
        TestWatch["test_watchdog.py<br>Пульс, затримки, дедуплікація"]:::test
        TestMigrate["test_migrate.py<br>Ідемпотентність SQL-міграцій (001-006)"]:::test
    end

    subgraph Delivery["📲 8. Рівень сповіщень та користувацького UI"]
        Telegram["Telegram Bot API<br>Канал/Чат користувача<br>Команди: /bank /bets /edit_odds /settle"]:::notify
        StreamlitUI["Streamlit Cloud Dashboard<br>(dashboard.py)<br>RBAC: Admin vs Read-Only<br>Графік капіталу Plotly, AI-картки<br>Редагування коефіцієнтів"]:::ui
    end

    %% Потоки тригерів
    CronJob -->|HTTP GET/POST| CFWorker
    GHFallbackCron -->|Scheduled Cron| GHRunner
    ManualAdmin -->|Direct API| GHAPI
    DashboardTrigger -->|HTTP Webhook| CFWorker
    CFWorker -->|POST workflow_dispatch| GHAPI
    GHAPI --> GHRunner
    GHRunner --> MainPy

    %% Оркестрація
    MainPy --> ModPipeline
    MainPy --> MigrateRunner
    MigrateRunner --> T_Migrations
    MigrateRunner --> DB

    %% Конвеєр statmonitor
    ModPipeline --> ModDB
    ModPipeline --> ModFetcher
    ModPipeline --> ModAI
    ModPipeline --> ModPaper
    ModPipeline --> ModChart
    ModPipeline --> ModNotify

    %% Дані
    ModFetcher -->|1. Запит ліній| OddsAPI
    OddsAPI -->|Котирування| ModFetcher
    ModFetcher -->|Збереження подій і коеф.| DB
    DB --> T_Events
    DB --> T_Odds
    T_Odds --> V_Alerts

    %% AI та Paper Trading
    V_Alerts -->|Алерти просідання| ModPipeline
    ModAI -->|Запит контексту + Search Grounding| GeminiAPI
    GeminiAPI -->|Вердикт і коротка ставка| ModAI
    ModAI --> T_AI
    ModPaper --> T_Bets

    %% Планувальник та Watchdog
    ModPipeline --> Watchdog
    Watchdog --> T_Beat
    ModPipeline --> SchedEngine
    SchedEngine --> T_Sched
    SchedEngine -.->|mark_checkpoints_executed| T_Sched

    %% Візуалізація та відправка
    ModChart -->|PNG Графік у пам'яті| ModNotify
    ModNotify -->|Фото та HTML зведення| Telegram
    Watchdog -.->|Watchdog Alert при затримці| Telegram

    %% Дашборд
    DB -.->|Прямий зв'язок (autocommit=True)| StreamlitUI
```

---

## 2. Модель даних (Entity-Relationship Diagram)

```mermaid
erDiagram
    events ||--o{ odds_history : "має котирування"
    events ||--o| ai_match_analysis : "має вердикт"
    events ||--o{ paper_bets : "генерує ставки"
    events ||--o{ scheduler_plan : "формує тригери"
    schema_migrations ||--o{ events : "фіксує структуру"

    schema_migrations {
        text version PK "Номер міграції (001, 002...)"
        text description "Опис змін"
        timestamptz applied_at "Дата виконання"
    }

    events {
        text id PK "Унікальний ID події (The Odds API)"
        text sport "Ключ виду спорту / ліги"
        text match_name "Матч (Home - Away)"
        timestamptz commence_time "Час початку матчу (UTC)"
        timestamptz created_at "Час створення"
    }

    odds_history {
        bigserial id PK
        text event_id FK "ID події"
        text bookmaker "Ключ букмекера (Pinnacle, BetOnline...)"
        text market_key "Маркет (h2h, totals, spreads)"
        text outcome_name "Вибір (П1, П2, Over...)"
        numeric point "Фора або тотал"
        numeric price "Коефіцієнт"
        timestamptz recorded_at "Час запису (ковзний архів 4 дні)"
    }

    paper_bets {
        serial id PK
        text event_id FK "Унікальний матч (захист від дублів)"
        text sport "Турнір"
        text match_name "Матч"
        timestamptz commence_time "Час старту"
        text pick_label "Маркет ставки (Ф2 (+1.5), ТБ 2.5...)"
        numeric odds "Коефіцієнт"
        numeric stake_uah "Розмір ставки (2-4% від вільного банку)"
        text status "PENDING / WON / LOST / VOID"
        text match_score "Фінальний рахунок"
        numeric profit_uah "Чистий прибуток/збиток"
        timestamptz settled_at "Час розрахунку"
    }

    ai_match_analysis {
        text event_id PK
        text verdict_text "Склади, травми, чутки, інсайди та ставка"
        timestamptz created_at "Кеш вердикту (12 год)"
    }

    scheduler_plan {
        serial id PK
        timestamptz target_time "Час очікуваного запуску"
        text trigger_type "PRE_MATCH (-15m) / SETTLE (+115m)"
        text[] event_ids "Пов'язані матчі кластера"
        text description "Людський опис"
        text status "PLANNED / SKIPPED / EXECUTED / MISSED"
        timestamptz executed_at "Час фактичного виконання"
    }

    system_heartbeat {
        text service_name PK "StatMonitor"
        timestamptz last_ping_at "Останній зафіксований пульс"
        text last_status "ONLINE / OK / WARNING"
        numeric last_duration_sec "Тривалість виконання"
        jsonb metadata "Кількість перевірених подій"
    }
```

---

## 3. Детальний опис рівнів системи

### Рівень 1: Високоточний гібридний запуск (Execution Orchestration)
* **Зовнішній сервіс (Cron-job.org)**: викликає Webhook секунда в секунду за розкладом.
* **Шлюз Cloudflare Worker (`deploy/cloudflare_webhook.js`)**:
  - Перевіряє секрет `?secret=***`.
  - Відправляє `workflow_dispatch` на GitHub API за $\sim 50$ мс.
  - Жодних секретів не зберігається у відкритому вигляді (Cloudflare Encrypted Secrets).
* **Кнопка Web Dashboard**: запуск сканування безпосередньо з інтерфейсу Streamlit в один клік (для користувачів з роллю Admin).
* **Резервний GitHub Actions Cron (`.github/workflows/scheduler.yml`)**:
  - Активовано `schedule: - cron: '15,45 * * * *'` (кожні 30 хв у пікові хвилини) як надійний fallback-захист на випадок збоїв зовнішніх пінгерів.
* **GitHub Actions Runner**: без черг стартує контейнер Ubuntu з Python 3.10+ і запускає `main.py`.

### Рівень 2: Збір та адаптація котирувань (Ingestion Engine)
* **Підтримка 14 цільових турнірів**: АПЛ, Ла Ліга, Серія А, Бундесліга, Ліга 1, УПЛ, Екстракласа, Ліга Чемпіонів, Ліга Європи, Ліга Конференцій, Ліга Націй, НБА, Підсумкові турніри ATP та WTA.
* **Автоматична ротація API ключів (`statmonitor.fetcher`)**: при вичерпанні ліміту або 429 перемикається на `ODDS_API_KEY_RESERVE` (сумарний пул 1000 запитів).
* **Динамічна адаптація колонок (`statmonitor.database`)**: безпечна нормалізація при варіаціях схеми Supabase (`event_id` / `match_id`, `price` / `odds`, `point` / `line`).
* **Ковзний архів**: дані котирувань автоматично очищаються після 4 днів (`INTERVAL '4 days'`).

### Рівень 3: Аналітика, AI та віртуальний банк (Intelligence Layer)
* **Оптимізована детекція прогрузів (`v_odds_alerts`)**: віконні функції `FIRST_VALUE` та `LAST_VALUE` за ковзним вікном 96 годин (міграція `003_v_odds_alerts.sql` та розширення) для миттєвого розрахунку падіння від першого до останнього котирування в діапазоні $1.40 - 4.00$.
* **Точний розрахунок медіанних коефіцієнтів та ліній (Крок 18)**:
  - `resolve_alert_from_history`: відновлює точну активну лінію та значення point з історії, якщо у перегляді воно було відсутнє (`NULL`).
  - `get_market_median_odds`: розраховує надійну медіану серед провідних бенчмарк-букмекерів (Pinnacle, Betfair, Unibet, BetOnline) у межах допуску $\pm 0.05$ point, виключаючи викривлені або одиночні викиди.
  - Утиліта пакетного перерахунку `recalc_odds.py` для оновлення коефіцієнтів існуючих відкритих або розрахованих ставок.
* **Каскадний Gemini AI з Google Search Grounding (`statmonitor.ai`)**:
  - Каскад моделей: `gemini-3.5-flash-lite` $\rightarrow$ `gemini-2.5-flash-lite` $\rightarrow$ `gemini-2.5-flash` $\rightarrow$ `gemini-3.8-flash`.
  - Підключено інструмент `google_search` для пошуку свіжих новин, лазарету, дискваліфікацій та інсайдів у режимі реального часу.
  - Структуровані секції: **Склади та кадрові втрати**, **Форма та тонус**, **Інсайди, чутки та суть прогрузу**, **Оцінка валую**.
  - Функція `extract_short_pick`: нормалізація назви ставки, відсікання кефів (`за 2.10`, `@ 1.95`), балансування дужок.
* **Paper Bank (10 000 грн) (`statmonitor.paper_trading`)**:
  - **Динамічний стейкінг за критерієм Келлі (`calculate_kelly_fraction`, Крок 22)**: розрахунок частки банку за формулою дробового Келлі ($0.25 \times \text{Kelly}$) на основі сили прогрузу (`drop_pct`) та очікуваної математичної переваги (Edge) із захисними межами $[1.0\%, 5.0\%]$.
  - Відображення % банку за Келлі в активних ставках Web Dashboard (колонка `"% банку (Келлі)"`) та у Telegram-боті (`/bets`).
  - Фіксація `kelly_pct` у базі даних (міграція `006_paper_bets_kelly_pct.sql`).
  - Ручне та автоматичне редагування коефіцієнтів (`update_pending_bet_odds`) для нерозрахованих ставок (Крок 19).
  - Гнучкий ручний розрахунок (`manual_settle_bet`) та автоматичний за фінальними рахунками (`WON`, `LOST`, `VOID`).
  - Щоденний звіт з розрахунком ROI о 08:00 за Києвом.
* **Дедуплікація активних ставок та захист від спаму (`statmonitor.pipeline`, Крок 27)**:
  - Перед запуском AI-аналізу та генерацією графіків конвеєр перевіряє активні ставки (`status = 'PENDING'`).
  - Події, по яких уже відкрито парі, автоматично пропускаються — це заощаджує квоти Gemini API, запобігає дублюванню сигналів та спаму в Telegram-каналі.
  - Активні ставки залишаються суворо незмінними (immutable) під час повторних автоматичних запусків моніторингу.

### Рівень 4: Надійність, Watchdog, міграції та планувальник (Reliability Layer)
* **Модульна архітектура пакету `statmonitor/`**:
  - Чітке розділення обов'язків: `config`, `database`, `notifier`, `fetcher`, `chart`, `ai`, `paper_trading`, `pipeline`.
  - Зворотна сумісність: `main.py` залишається центральною точкою входу.
* **Версіоновані міграції БД (`migrate.py`)**:
  - Каталог `migrations/` (`001_base_schema.sql` ... `006_paper_bets_kelly_pct.sql`).
  - Ідемпотентний раннер з журналом у `schema_migrations`.
  - Цільові B-Tree індекси на `odds_history`, `events`, `paper_bets`.
* **Автоматизований тестовий комплекс (`tests/` та кореневі тести)**:
  - 86 модульних тестів (100% проходження за $< 0.15$ с) без зовнішніх мережевих викликів.
* **Динамічний планувальник (`scheduler.py`)**:
  - Кластеризація подій ($\Delta \le 25$ хв).
  - Формування контрольних точок за 15 хв до гри (`PRE_MATCH` для фіксації Closing Line) та через 115 хв (`SETTLE` для розрахунку ставок).
  - **Автоматична фіксація виконання (`mark_checkpoints_executed`)**: виконані точки переводяться у статус `EXECUTED` з позначкою часу.
  - **Дедуплікація точок розкладу**: запобігання дублюванню однакових матчів у `scheduler_plan`.
* **Системний пульс (`sys_watchdog.py`)**:
  - Фіксація тривалості циклу в `system_heartbeat`.
  - Автоматичне виявлення затримок черг ($> 25$ хв) з алертом у Telegram.
  - Дедуплікація пропущених точок при формуванні повідомлень для уникнення спаму.
  - Підтримка зовнішнього пінгу (`HEALTHCHECK_URL`).

### Рівень 5: Спостережливість та доставка (Observability & Delivery)
* **Інтерактивний веб-дашборд (`dashboard.py` на Streamlit Cloud)**:
  - **RBAC безпека**: Гостьовий режим (Read-Only) без кнопок керування проти режиму адміністратора (`?key=...` або форма входу).
  - **Інтерактивне редагування коефіцієнтів (Крок 19)**: випадаюче меню для активних ставок у кабінеті адміністратора з автоматичним перерахунком потенційної виплати.
  - Інтерактивний графік зростання банку Plotly (Paper Bank Balance Growth).
  - Вкладка розкладу та живого пульсу системи.
  - Вкладка карток глибокої AI-аналітики з Markdown-розміткою.
* **Telegram Bot API (`statmonitor.notifier` / `bot.py`)**:
  - Графіки Matplotlib у пам'яті (`io.BytesIO`) за київським часом.
  - Автоматичне розбиття великих зведень на блоки $\le 3800$ символів.
  - Захист від помилок форматування HTML з fallback на звичайний текст.
  - Інтерактивні команди адміністратора: `/bank`, `/bets`, `/edit_odds <ID> <коеф>`, `/settle <ID> <результат> <рахунок>`.
