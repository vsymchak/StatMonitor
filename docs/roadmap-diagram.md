# Візуальна діаграма дорожньої карти (Roadmap diagram)

**29 з 31 кроків реалізовано (29 Shipped, 2 Planned)** · Детальний опис: [roadmap.md](roadmap.md)

> 🟩 **Реалізовано (Shipped)** · 🟧 **У розробці (In Progress)** · 🟪 **Заплановано (Idea)** · ⬜ **Концепт (Fog)**  
> Колонки — це послідовні хвилі виконання (**Execution Waves**). Стрілка показує залежність («потрібен для»).

```mermaid
flowchart LR
    classDef shipped fill:#1b4332,stroke:#40916c,color:#d8f3dc,stroke-width:2px;
    classDef in_progress fill:#7f4f24,stroke:#d4a373,color:#faedcd,stroke-width:2px;
    classDef idea fill:#2b2d42,stroke:#8d99ae,color:#edf2f4,stroke-width:1px;
    classDef fog fill:#1e1e24,stroke:#4a4e69,color:#9a8c98,stroke-width:1px,stroke-dasharray: 4 4;

    subgraph Wave1["Хвиля 1: Базовий збір даних"]
        1["1 · Детекція схеми та збір коеф.<br><small>Адаптація колонок Supabase</small><br><b>S</b>"]:::shipped
        2["2 · Історія коеф. та ротація<br><small>4-денний ковзний архів</small><br><b>S</b>"]:::shipped
        3["3 · Доставка в Telegram<br><small>Чанкінг HTML до 3800 симв.</small><br><b>S</b>"]:::shipped
    end

    subgraph Wave2["Хвиля 2: Аналітика та Paper Trading"]
        4["4 · Графіки падіння коеф.<br><small>Matplotlib тренди в пам'яті</small><br><b>S</b>"]:::shipped
        5["5 · AI-аналіз Gemini<br><small>Каскад 4 моделей при 429</small><br><b>M</b>"]:::shipped
        6["6 · Paper Bank & автоставки<br><small>Банк 10k, стейкінг 2-4%</small><br><b>S</b>"]:::shipped
        7["7 · Розрахунок та щоденний звіт<br><small>Статуси WON/LOST, ROI о 08:00</small><br><b>M</b>"]:::shipped
    end

    subgraph Wave3["Хвиля 3: Еволюція планувальника (Фокус)"]
        8["8 · Динамічний розклад за матчами<br><small>Тригери за -15m та +115m</small><br><b>M</b>"]:::shipped
        9["9 · Watchdog & Healthcheck<br><small>Контроль затримок GH Actions</small><br><b>S</b>"]:::shipped
        10["10 · Smart Rate-Limiter<br><small>Бюджет квот The Odds API</small><br><b>S</b>"]:::shipped
        11["11 · Гібридний зовнішній тригер<br><small>Резервний Webhook/Cron-job</small><br><b>M</b>"]:::shipped
    end

    subgraph Wave4["Хвиля 4: Архітектура та надійність"]
        12["12 · Юніт-тести розрахунків<br><small>Покриття pytest маркетів</small><br><b>S</b>"]:::shipped
        13["13 · Модульна декомпозиція<br><small>Поділ main.py на пакети</small><br><b>M</b>"]:::shipped
        14["14 · Міграції БД та індекси<br><small>Оптимізація v_odds_alerts</small><br><b>S</b>"]:::shipped
    end

    subgraph Wave5["Хвиля 5: Інтерактивність та налаштування"]
        15["15 · Інтерактивний бот TG<br><small>Команди /status, /bank, /run</small><br><b>M</b>"]:::shipped
        16["16 · Матриця ліг та видів спорту<br><small>Конфігурація без зміни коду</small><br><b>S</b>"]:::shipped
    end

    subgraph Wave6["Хвиля 6: Спостережливість та UI"]
        17["17 · Веб-дашборд моніторингу<br><small>Streamlit UI + Графіки</small><br><b>L</b>"]:::shipped
    end

    subgraph Wave7["Хвиля 7: Точність ринку та верифікація"]
        18["18 · Точні медіанні коеф.<br><small>Benchmark БК, resolve point</small><br><b>M</b>"]:::shipped
        19["19 · Редагування коефіцієнтів<br><small>UI/TG/CLI для PENDING ставок</small><br><b>S</b>"]:::shipped
    end

    subgraph Wave8["Хвиля 8: Розумний беттинг та маркети"]
        20["20 · Відстеження CLV & Beat Line<br><small>Closing Line Value, +EV</small><br><b>M</b>"]:::shipped
        21["21 · AI Confidence Score<br><small>Шкала 1-10, фільтр валую</small><br><b>S</b>"]:::shipped
        22["22 · Динамічний стейкінг Келлі<br><small>Fractional Kelly 0.25</small><br><b>S</b>"]:::shipped
        23["23 · Обидві заб'ють & тотали<br><small>BTTS (Yes/No), цілі тотали</small><br><b>M</b>"]:::shipped
        27["27 · Дедуплікація & Anti-Spam<br><small>Пропуск активних ставок</small><br><b>S</b>"]:::shipped
        28["28 · Мульти-квота 5 Ключів & Теніс<br><small>2500 токенів Odds API, ATP/WTA</small><br><b>S</b>"]:::shipped
        29["29 · Cloudflare Cron & Фільтр шуму<br><small>Edge-розклад 20m, Night Silence</small><br><b>S</b>"]:::shipped
        30["30 · Оптимізація TG & Silent AI<br><small>Без спаму, лінк на Guest Web UI</small><br><b>S</b>"]:::shipped
    end

    subgraph Wave9["Хвиля 9: Розширена аналітика та дайджести"]
        24["24 · Аналітика ROI ліг & Drawdown<br><small>Фільтри, Max Drawdown %</small><br><b>M</b>"]:::shipped
        25["25 · Керування порогами в UI<br><small>Admin налаштування leagues.json</small><br><b>S</b>"]:::idea
        26["26 · Щотижневий графічний дайджест<br><small>Sunday Telegram Digest</small><br><b>S</b>"]:::shipped
    end

    subgraph Wave10["Хвиля 10: Реальний трейдинг та Bet Slip OCR"]
        31["31 · Гра на реальні гроші & Slip OCR<br><small>Реальний банк, фото купона через Gemini Vision</small><br><b>M</b>"]:::idea
    end

    %% Залежності Хвилі 1 і 2
    1 --> 2
    2 --> 4
    3 --> 4
    3 --> 5
    5 --> 6
    6 --> 7
    3 --> 7

    %% Залежності Хвилі 3 (Планувальник)
    2 --> 8
    7 --> 8
    8 --> 9
    1 --> 10
    8 --> 10
    9 --> 11

    %% Залежності Хвилі 4
    7 --> 12
    12 --> 13
    2 --> 14

    %% Залежності Хвилі 5
    13 --> 15
    13 --> 16

    %% Wave 6 connections
    6 --> 17
    7 --> 17
    11 --> 17

    %% Wave 7 connections
    6 --> 18
    14 --> 18
    18 --> 19
    15 --> 19
    17 --> 19

    %% Wave 8 connections
    8 --> 20
    18 --> 20
    5 --> 21
    6 --> 21
    20 --> 22
    21 --> 22
    16 --> 23
    18 --> 23
    6 --> 27
    13 --> 27
    10 --> 28
    16 --> 28
    17 --> 28
    8 --> 29
    9 --> 29
    11 --> 29
    27 --> 30

    %% Wave 9 connections
    17 --> 24
    16 --> 25
    17 --> 25
    4 --> 26
    7 --> 26
    20 --> 26

    %% Wave 10 connections
    6 --> 31
    17 --> 31
    19 --> 31
    5 --> 31
```

---

## Короткий опис пунктів українською мовою

| № | Пункт | Розмір | Статус | Короткий опис |
| :---: | :--- | :---: | :---: | :--- |
| **1** | **Детекція схеми та збір коеф.** | `S` | 🟩 Shipped | Автоматично адаптується до різних назв колонок у Supabase (`event_id`/`match_id`, `price`/`odds`) і зберігає котирування. |
| **2** | **Історія коеф. та ротація** | `S` | 🟩 Shipped | Накопичує часові ряди прогрузів та видаляє записи старіші за 4 дні для економії місця. |
| **3** | **Доставка в Telegram** | `S` | 🟩 Shipped | Відправляє сповіщення з розбиттям на блоки до 3800 символів та захистом від блокувань (rate-limit 429). |
| **4** | **Графіки падіння коеф.** | `S` | 🟩 Shipped | Генерує візуальні графіки Matplotlib у пам'яті (`BytesIO`) за київським часом і надсилає як фото. |
| **5** | **AI-аналіз Gemini** | `M` | 🟩 Shipped | Оцінює прогрузи через моделі Gemini з автоперемиканням при лімітах (`3.5-flash-lite` $\rightarrow$ `2.5-flash` $\rightarrow$ `3.8-flash`). |
| **6** | **Paper Bank & автоставки** | `S` | 🟩 Shipped | Веде віртуальний банк 10 000 грн, автоматично ставить 2–4% від банку залежно від коефіцієнта без дублювання. |
| **7** | **Розрахунок та щоденний звіт** | `M` | 🟩 Shipped | Перевіряє фінальні рахунки (`WON`/`LOST`/`VOID`), фіксує прибуток і щодня о 08:00 публікує підсумок з ROI. |
| **8** | **Динамічний розклад за матчами** | `M` | 🟩 Shipped | Аналізує розклад ігор: планує перевірки за 15 хв до старту (пікові прогрузи) та через 115 хв (миттєвий розрахунок). |
| **9** | **Watchdog & Healthcheck** | `S` | 🟩 Shipped | Фіксує пульс системи (`system_heartbeat`), знаходить запізнення GitHub Actions ($> 25$ хв) і надсилає алерт у Telegram. |
| **10** | **Smart Rate-Limiter** | `S` | 🟩 Shipped | Автоматично адаптує частоту опитування ліг (HOT/WARM/COLD) для збереження місячного ліміту запитів The Odds API. |
| **11** | **Гібридний зовнішній тригер** | `M` | 🟩 Shipped | Резервний Webhook (Cron-job / Cloudflare) для гарантованого запуску без затримок у чергах GitHub. |
| **12** | **Юніт-тести розрахунків** | `S` | 🟩 Shipped | Набір із 17 тестів (`test_eval_picks.py`) для маркетів 1X2, фор, тоталів (`eval_outcome`, `format_pick`, `extract_short_pick`). |
| **13** | **Модульна декомпозиція** | `M` | 🟩 Shipped | Розподіл монолітного `main.py` на окремі пакети: `fetcher`, `database`, `ai`, `notifier`, `chart`, `paper_trading`. |
| **14** | **Міграції БД та індекси** | `S` | 🟩 Shipped | Версіонований раннер `migrate.py`, цільові індекси для `odds_history` та оптимізована в'юшка `v_odds_alerts`. |
| **15** | **Інтерактивний бот TG** | `M` | 🟩 Shipped | Двосторонній асистент (`bot_service.py`): команди `/status`, `/bank`, `/bets`, `/today`, `/schedule`, `/run_now` з RBAC. |
| **16** | **Матриця ліг та спорту** | `S` | 🟩 Shipped | Декларативний конфіг `config/leagues.json` для вибору ліг, маркетів та індивідуальних порогів просідання. |
| **17** | **Веб-дашборд моніторингу** | `L` | 🟩 Shipped | Графічний інтерфейс на Streamlit (`dashboard.py`) з історією ставок, прибутком, AI-вердиктами та аналітикою банку. |
| **18** | **Точні медіанні коефіцієнти** | `M` | 🟩 Shipped | Добирання точного `point` з `odds_history`, розрахунок медіани еталонних БК (Pinnacle/Betfair/Unibet) та перерахунок історичних ставок. |
| **19** | **Редагування коефіцієнтів** | `S` | 🟩 Shipped | Зміна коефіцієнта для ставок у статусі `PENDING` через Streamlit Dashboard (адмін-режим), Telegram-бот (`/edit_odds`) та CLI. |
| **20** | **Відстеження CLV & Beat Line** | `M` | 🟩 Shipped | Фіксація Closing Line бенчмарків (Pinnacle/Betfair) перед матчем, розрахунок CLV % та Beat the Line % для доказу математичної переваги (+EV). |
| **21** | **AI Confidence Score & фільтр** | `S` | 🟩 Shipped | Оцінка впевненості 1–10 від Gemini AI та автоматичний фільтр відбору ставок у Paper Bank лише з високим значенням валую ($\ge 7$). |
| **22** | **Динамічний стейкінг Келлі** | `S` | 🟩 Shipped | Дробовий критерій Келлі ($0.25 \times \text{Kelly}$) з межами 1–5% та відображенням % банку в активних ставках UI та TG. |
| **23** | **Обидві заб'ють (BTTS) & цілі тотали** | `M` | 🟩 Shipped | Підтримка ринку Both Teams to Score (Yes/No) у футболі та фільтрація тоталів виключно до стандартних цілих і половинних ліній. |
| **24** | **Аналітика ROI ліг & Drawdown** | `M` | 🟩 Shipped | Сегментація ROI за турнірами на Web Dashboard, розрахунок максимального просідання капіталу (Max Drawdown %), серій (Streaks) та фільтри. |
| **25** | **Керування порогами в UI** | `S` | 🟪 Idea | Інтерфейс адміністратора на дашборді для налаштування порогів чутливості ліг (`min_drop_pct`, діапазонів коеф.) без правок коду. |
| **26** | **Щотижневий графічний дайджест** | `S` | 🟩 Shipped | Автоматичний звіт щонеділі о 22:00 (та команда `/digest`) у Telegram: графік зміни капіталу за тиждень, топ-3 ставки, показник середнього CLV та тижневий ROI. |
| **27** | **Дедуплікація & Anti-Spam** | `S` | 🟩 Shipped | Виключення з пайплайну аналізу та Telegram-сповіщень тих матчів, по яких у `paper_bets` уже зафіксовано активну ставку (`PENDING`), захист від дублювання та спаму. |
| **28** | **Мульти-квота Odds API (5 кл) & Теніс** | `S` | 🟩 Shipped | 5-рівневий пул квот (2500 запитів/міс) з моніторингом у Streamlit та пульсі, динамічне автовиявлення тенісних змагань (ATP/WTA). |
| **29** | **Cloudflare Cron & Фільтр шуму** | `S` | 🟩 Shipped | Секундний запуск Cloudflare Cron (`*/20 * * * *`), фокус PRE_MATCH точок тільки на ставках, нічна тиша (00:00–08:00) та усунення спаму Watchdog. |
| **30** | **Оптимізація TG & Silent AI** | `S` | 🟩 Shipped | Збереження повних AI-вердиктів Gemini у базі даних без перевантаження Telegram, посилання на Guest Web UI та захист від спаму повторними ставками. |
| **31** | **Гра на реальні гроші & Bet Slip OCR** | `M` | 🟪 Idea | Можливість гри на реальні гроші (UAH), введення реального банку, відмічання реальних ставок, завантаження фото купона БК в адмінці/TG та авторозпізнавання через Gemini Vision. |
