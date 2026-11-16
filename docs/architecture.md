# Візуальна архітектура системи StatMonitor

> **Проєкт**: StatMonitor — інтелектуальна система спортивного моніторингу прогрузів, віртуального трейдингу (Paper Trading) та предиктивної аналітики.  
> **Версія**: 2.0 (Еволюція SDD: Dynamic Scheduler + Precision Webhook + Watchdog)  
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

    subgraph Triggers["🌐 1. Рівень тригерів і планувальника"]
        CronJob["Cron-job.org / Webhook<br>Точний розклад по секундах"]:::ext
        ManualAdmin["Admin / CLI<br>python trigger_dispatch.py"]:::ext
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
        Watchdog["watchdog.py<br>Pulse & Missed Checkpoints"]:::core
        SchedEngine["scheduler.py<br>Кластеризація -15m / +115m"]:::core
        ChartGen["Matplotlib Generator<br>Рендеринг трендів у BytesIO"]:::core
        PaperEngine["Paper Bank & Staking<br>Банк 10k, стейк 2-4%, ROI"]:::core
    end

    subgraph AI["🤖 5. Штучний інтелект (AI Layer)"]
        GeminiAPI["Google Gemini API<br>Failover: 3.5-flash-lite ➔ 2.5-flash ➔ 3.8-flash<br>Аналіз прогрузів та вердикти"]:::ai
    end

    subgraph Storage["💾 6. Сховище даних (Supabase PostgreSQL)"]
        DB[("PostgreSQL 15+<br>public schema")]:::data
        T_Events["events"]:::data
        T_Odds["odds_history (4-day rolling)"]:::data
        V_Alerts["v_odds_alerts (View)"]:::data
        T_AI["ai_match_analysis"]:::data
        T_Bets["paper_bets (Bankroll)"]:::data
        T_Sched["scheduler_plan"]:::data
        T_Beat["system_heartbeat"]:::data
    end

    subgraph Delivery["📲 7. Рівень доставки (Delivery)"]
        Telegram["Telegram Bot API<br>Канал/Чат користувача"]:::notify
    end

    %% Потоки тригерів
    CronJob -->|HTTP GET/POST| CFWorker
    ManualAdmin -->|Direct API| GHAPI
    CFWorker -->|POST workflow_dispatch| GHAPI
    GHAPI --> GHRunner
    GHRunner --> MainPy

    %% Потоки даних
    MainPy -->|1. Запит ліній| OddsAPI
    OddsAPI -->|Котирування| MainPy
    MainPy -->|Збереження подій і коеф.| DB
    DB --> T_Events
    DB --> T_Odds
    T_Odds --> V_Alerts

    %% Аналітика та AI
    V_Alerts -->|Алерти просідання| MainPy
    MainPy -->|Запит контексту| GeminiAPI
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
```

---

## 2. Модель даних (Entity-Relationship Diagram)

```mermaid
erDiagram
    events ||--o{ odds_history : "має котирування"
    events ||--o| ai_match_analysis : "має вердикт"
    events ||--o{ paper_bets : "генерує ставки"
    events ||--o{ scheduler_plan : "формує тригери"

    events {
        text id PK "Унікальний ID події (The Odds API)"
        text sport "Ключ виду спорту / ліги"
        text home_team "Господарі"
        text away_team "Гості"
        timestamptz commence_time "Час початку матчу (UTC)"
    }

    odds_history {
        bigserial id PK
        text event_id FK
        text bookmaker "Ключ букмекера (pinnacle, bwin...)"
        text market "Маркет (h2h, totals, spreads)"
        text outcome "Вибір (П1, П2, Over...)"
        numeric point "Фора або тотал"
        numeric price "Коефіцієнт"
        timestamptz time "Час запису (автоочищення > 4 днів)"
    }

    paper_bets {
        serial id PK
        text event_id FK
        text sport "Турнір"
        text match_name "Матч"
        timestamptz commence_time "Час старту"
        text pick_label "Маркет ставки"
        numeric odds "Коефіцієнт"
        numeric stake_uah "Розмір ставки (грн)"
        text status "PENDING / WON / LOST / VOID"
        text match_score "Фінальний рахунок"
        numeric profit_uah "Чистий прибуток/збиток"
        timestamptz settled_at "Час розрахунку"
    }

    ai_match_analysis {
        text event_id PK
        text verdict_text "Повний аналіз та ставка Gemini"
        timestamptz created_at "Кеш вердикту (12 год)"
    }

    scheduler_plan {
        serial id PK
        timestamptz target_time "Час очікуваного запуску"
        text trigger_type "PRE_MATCH / SETTLE / BASELINE"
        text[] event_ids "Пов'язані матчі кластера"
        text description "Людський опис"
        text status "PLANNED / MISSED / EXECUTED"
    }

    system_heartbeat {
        text service_name PK "StatMonitor"
        timestamptz last_ping_at "Останній зафіксований пульс"
        text last_status "OK / WARNING"
        numeric last_duration_sec "Тривалість виконання"
        jsonb metadata "Кількість перевірених подій"
    }
```

---

## 3. Детальний опис рівнів системи

### Рівень 1: Високоточний гібридний запуск (Execution Orchestration)
* **Зовнішній сервіс (Cron-job.org)**: викликає Webhook секунда в секунду за розкладом.
* **Шлюз Cloudflare Worker (`deploy/cloudflare_webhook.js`)**:
  - Перевіряє токен `?secret=***`.
  - Відправляє `workflow_dispatch` на GitHub API за 50 мс.
  - Жодних секретів не зберігається у відкритому вигляді (використовуються Cloudflare Encrypted Secrets).
* **GitHub Actions Runner**: без черг стартує контейнер Ubuntu з Python 3.10 і запускає `main.py`.

### Рівень 2: Збір та адаптація котирувань (Ingestion Engine)
* **Підтримка 14 цільових турнірів**: АПЛ, Ла Ліга, Серія А, Бундесліга, Ліга 1, УПЛ, Екстракласа, Ліга Чемпіонів, Ліга Європи, Ліга Конференцій, Ліга Націй, НБА, Підсумкові турніри ATP та WTA.
* **Автоматична ротація API ключів**: при вичерпанні ліміту або 429 перемикається на `ODDS_API_KEY_RESERVE`.
* **Динамічна адаптація колонок**: модуль безпечно працює при різних схемах у БД (`event_id`/`match_id`, `price`/`odds`, `point`/`line`).
* **Ковзний архів**: дані котирувань автоматично очищаються після 4 днів (`INTERVAL '4 days'`).

### Рівень 3: Аналітика, AI та віртуальний банк (Intelligence Layer)
* **Детекція аномалій (`v_odds_alerts`)**: відбір матчів із коефіцієнтом від 1.40 до 4.00 та істотним відсотком просідання.
* **Каскадний Gemini AI Failover**: аналіз спортивних прогрузів через `gemini-3.5-flash-lite` $\rightarrow$ `gemini-2.5-flash-lite` $\rightarrow$ `gemini-2.5-flash` $\rightarrow$ `gemini-3.8-flash`. Кешування результатів на 12 годин для економії токенів.
* **Paper Bank (10,000 грн)**:
  - Автоматичний стейкінг: 4% на коефіцієнти $\le 1.75$, 3% на коефіцієнти $\le 2.35$, 2% на високі коефіцієнти.
  - Автоматичний розрахунок за результатами матчів (`WON`, `LOST`, `VOID`).
  - Щоденний звіт з розрахунком ROI о 08:00 за Києвом.

### Рівень 4: Надійність, Watchdog та динамічний розклад (Reliability Layer)
* **Динамічний планувальник (`scheduler.py`)**:
  - Об'єднує події в кластери ($\Delta \le 25$ хв).
  - Формує точки запуску за 15 хв до гри (пікові прогрузи) та через 115 хв (миттєвий розрахунок ставок).
* **Системний пульс (`watchdog.py`)**:
  - Фіксація тривалості циклу в `system_heartbeat`.
  - Автоматичне виявлення затримок черг ($> 25$ хв) з алертом у Telegram.
  - Підтримка зовнішнього пінгу (`HEALTHCHECK_URL`).

### Рівень 5: Доставка результатів (Notification Layer)
* **Графіки Matplotlib**: рендеринг у пам'яті (`io.BytesIO`) без створення сміттєвих файлів на диску, адаптований під часовий пояс `Europe/Kyiv`.
* **Telegram Bot API**:
  - Автоматичне розбиття великих зведень на блоки $\le 3800$ символів.
  - Захист від помилок форматування HTML з fallback на звичайний текст.
  - Обробка rate-limit (HTTP 429) із паузами `retry_after`.
