# Візуальна архітектура системи StatMonitor

> **Проєкт**: StatMonitor — інтелектуальна система спортивного моніторингу прогрузів, віртуального трейдингу (Paper Trading), спостережливості (Web Dashboard) та предиктивної AI-аналітики.  
> **Версія**: 2.2 (Еволюція SDD: Dynamic Scheduler + Precision Webhook + Watchdog + Web Dashboard + Migrations Runner)  
> **Оновлено**: 16.11.2026

---

## 1. Загальна схема системи (End-to-End System Architecture)

```mermaid
flowchart TD
    classDef ext fill:#1e293b,stroke:#475569,color:#f8fafc,stroke-width:1px;
    classDef gw fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe,stroke-width:2px;
    classDef core fill:#064e3b,stroke:#10b981,color:#d1fae5,stroke-width:2px;
    classDef data fill:#701a75,stroke:#d946ef,color:#fae8ff,stroke-width:2px;
    classDef ai fill:#7c2d12,stroke:#f97316,color:#ffedd5,stroke-width:2px;
    classDef notify fill:#14532d,stroke:#22c55e,color:#dcfce7,stroke-width:2px;
    classDef ui fill:#312e81,stroke:#6366f1,color:#e0e7ff,stroke-width:2px;

    subgraph Triggers["🌐 1. Рівень тригерів і планувальника"]
        CronJob["Cron-job.org / Webhook<br>Точний розклад по секундах"]:::ext
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

    subgraph CoreEngine["🧠 4. Ядро обробки (StatMonitor Core)"]
        MainPy["main.py (Оркестратор)"]:::core
        Watchdog["sys_watchdog.py<br>Pulse & Missed Checkpoints"]:::core
        SchedEngine["scheduler.py<br>Кластеризація -15m / +115m"]:::core
        MigrateRunner["migrate.py<br>Версіоновані міграції БД"]:::core
        ChartGen["Matplotlib Generator<br>Рендеринг трендів у BytesIO"]:::core
        PaperEngine["Paper Bank & Staking<br>Банк 10k, стейк 2-4%, ROI"]:::core
    end

    subgraph AI["🤖 5. Штучний інтелект (AI Layer)"]
        GeminiAPI["Google Gemini API<br>Failover: 3.5-flash-lite ➔ 2.5-flash ➔ 3.8-flash<br>Google Search Grounding<br>Склади, травми, чутки, інсайди"]:::ai
    end

    subgraph Storage["💾 6. Сховище даних (Supabase PostgreSQL)"]
        DB[("PostgreSQL 15+<br>public schema")]:::data
        T_Migrations["schema_migrations"]:::data
        T_Events["events (індекс на commence_time)"]:::data
        T_Odds["odds_history (індекси за часом та маркетом)"]:::data
        V_Alerts["v_odds_alerts (Optimized Window View)"]:::data
        T_AI["ai_match_analysis"]:::data
        T_Bets["paper_bets (індекс за статусом і часом)"]:::data
        T_Sched["scheduler_plan"]:::data
        T_Beat["system_heartbeat"]:::data
    end

    subgraph Delivery["📲 7. Рівень сповіщень та користувацького UI"]
        Telegram["Telegram Bot API<br>Канал/Чат користувача"]:::notify
        StreamlitUI["Streamlit Cloud Dashboard<br>(dashboard.py)<br>RBAC: Admin vs Read-Only<br>Графік капіталу Plotly, AI-картки"]:::ui
    end

    %% Потоки тригерів
    CronJob -->|HTTP GET/POST| CFWorker
    ManualAdmin -->|Direct API| GHAPI
    DashboardTrigger -->|HTTP Webhook| CFWorker
    CFWorker -->|POST workflow_dispatch| GHAPI
    GHAPI --> GHRunner
    GHRunner --> MainPy

    %% Міграції та ініціалізація
    MainPy --> MigrateRunner
    MigrateRunner --> T_Migrations
    MigrateRunner --> DB

    %% Потоки даних
    MainPy -->|1. Запит ліній| OddsAPI
    OddsAPI -->|Котирування| MainPy
    MainPy -->|Збереження подій і коеф.| DB
    DB --> T_Events
    DB --> T_Odds
    T_Odds --> V_Alerts

    %% Аналітика та AI
    V_Alerts -->|Алерти просідання| MainPy
    MainPy -->|Запит контексту + Search Grounding| GeminiAPI
    GeminiAPI -->|Вердикт і коротка ставка| MainPy
    MainPy --> T_AI
    MainPy --> PaperEngine
    PaperEngine --> T_Bets

    %% Планувальник та Watchdog
    MainPy --> Watchdog
    Watchdog --> T_Beat
    MainPy --> SchedEngine
    SchedEngine --> T_Sched

    %% Візуалізація та відправка
    MainPy --> ChartGen
    ChartGen -->|PNG Фото| Telegram
    MainPy -->|HTML тексти зведень| Telegram
    Watchdog -.->|Watchdog Alert при затримці| Telegram

    %% Дашборд
    DB -.->|Прямий Pooler зв'язок| StreamlitUI
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
        text status "PLANNED / SKIPPED / EXECUTED"
        timestamptz executed_at "Час виконання"
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
* **Кнопка Web Dashboard**: запуск сканування безпосередньо з інтерфейсу Streamlit в один клік.
* **GitHub Actions Runner**: без черг стартує контейнер Ubuntu з Python 3.10+ і запускає `main.py`.

### Рівень 2: Збір та адаптація котирувань (Ingestion Engine)
* **Підтримка 14 цільових турнірів**: АПЛ, Ла Ліга, Серія А, Бундесліга, Ліга 1, УПЛ, Екстракласа, Ліга Чемпіонів, Ліга Європи, Ліга Конференцій, Ліга Націй, НБА, Підсумкові турніри ATP та WTA.
* **Автоматична ротація API ключів**: при вичерпанні ліміту або 429 перемикається на `ODDS_API_KEY_RESERVE` (сумарний пул 1000 запитів).
* **Динамічна адаптація колонок**: безпечна нормалізація при варіаціях схеми Supabase.
* **Ковзний архів**: дані котирувань автоматично очищаються після 4 днів (`INTERVAL '4 days'`).

### Рівень 3: Аналітика, AI та віртуальний банк (Intelligence Layer)
* **Оптимізована детекція прогрузів (`v_odds_alerts`)**: віконні функції `FIRST_VALUE` та `LAST_VALUE` за останні 48 годин для миттєвого розрахунку падіння від першого до останнього котирування в діапазоні $1.40 - 4.00$.
* **Каскадний Gemini AI з Google Search Grounding**:
  - Каскад моделей: `gemini-3.5-flash-lite` $\rightarrow$ `gemini-2.5-flash-lite` $\rightarrow$ `gemini-2.5-flash` $\rightarrow$ `gemini-3.8-flash`.
  - Підключено інструмент `google_search` для пошуку свіжих новин, лазарету, дискваліфікацій та інсайдів у режимі реального часу.
  - Структуровані секції: **Склади та кадрові втрати**, **Форма та тонус**, **Інсайди, чутки та суть прогрузу**, **Оцінка валую**.
* **Paper Bank (10 000 грн)**:
  - Автоматичний стейкінг: 4% на коефіцієнти $\le 1.75$, 3% на $\le 2.35$, 2% на високі.
  - Автоматичний розрахунок за фінальними рахунками (`WON`, `LOST`, `VOID`).
  - Щоденний звіт з розрахунком ROI о 08:00 за Києвом.

### Рівень 4: Надійність, Watchdog, міграції та планувальник (Reliability Layer)
* **Версіоновані міграції БД (`migrate.py`)**:
  - Каталог `migrations/` (`001_base_schema.sql`, `002_performance_indexes.sql`, `003_v_odds_alerts.sql`).
  - Ідемпотентний раннер з журналом у `schema_migrations`.
  - Цільові B-Tree індекси на `odds_history`, `events`, `paper_bets`.
* **Динамічний планувальник (`scheduler.py`)**:
  - Кластеризація подій ($\Delta \le 25$ хв).
  - Формування контрольних точок за 15 хв до гри (`PRE_MATCH` для фіксації Closing Line) та через 115 хв (`SETTLE` для розрахунку ставок).
* **Системний пульс (`sys_watchdog.py`)**:
  - Фіксація тривалості циклу в `system_heartbeat`.
  - Автоматичне виявлення затримок черг ($> 25$ хв) з алертом у Telegram.
  - Підтримка зовнішнього пінгу (`HEALTHCHECK_URL`).

### Рівень 5: Спостережливість та доставка (Observability & Delivery)
* **Інтерактивний веб-дашборд (`dashboard.py` на Streamlit Cloud)**:
  - **RBAC безпека**: Гостьовий режим (Read-Only) без кнопок керування проти режиму адміністратора (`?key=...` або форма входу).
  - Інтерактивний графік зростання банку Plotly (Paper Bank Balance Growth).
  - Вкладка розкладу та живого пульсу системи.
  - Вкладка карток глибокої AI-аналітики з Markdown-розміткою.
* **Telegram Bot API**:
  - Графіки Matplotlib у пам'яті (`io.BytesIO`) за київським часом.
  - Автоматичне розбиття великих зведень на блоки $\le 3800$ символів.
  - Захист від помилок форматування HTML з fallback на звичайний текст.
