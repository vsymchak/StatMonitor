# Архітектурний план: Модульна декомпозиція ядра StatMonitor (SPEC-13)

## 1. Стратегія рефакторингу

Декомпозиція виконується поетапно методом екстракції коду («Extract Module») без зміни бізнес-логіки та з гарантією відсутності циклічних імпортів:

```
[main.py (567 рядків)]
       │
       ├──► statmonitor/config.py
       ├──► statmonitor/database.py
       ├──► statmonitor/notifier.py
       ├──► statmonitor/fetcher.py
       ├──► statmonitor/chart.py
       ├──► statmonitor/ai.py
       └──► statmonitor/paper_trading.py
       │
       ▼
[main.py (~70 рядків - оркестратор)]
```

## 2. Етапи виконання

### Етап 1: Створення пакету `statmonitor/` та базових компонентів
1. `statmonitor/__init__.py` — експорт головних функцій.
2. `statmonitor/config.py` — ізоляція налаштувань, env, `KYIV_TZ`, `INITIAL_BANKROLL`.
3. `statmonitor/database.py` — ізоляція `get_db()`, `ensure_tables()`, динамічної інспекції колонок.
4. `statmonitor/notifier.py` — винесення логіки Telegram Bot API та форматування.

### Етап 2: Винесення бізнес-доменів
1. `statmonitor/fetcher.py` — інкапсуляція викликів до The Odds API, чергування ключів, збереження `events` та `odds_history`.
2. `statmonitor/chart.py` — рендеринг графіків просідання на Matplotlib.
3. `statmonitor/ai.py` — аналіз Gemini, Search Grounding, каскадний failover, парсинг рекомендацій.
4. `statmonitor/paper_trading.py` — віртуальний банк, стейкінг, перевірка результатів матчів, щоденні підсумки.

### Етап 3: Оновлення `main.py`
1. Заміна тіла функцій у `main.py` на виклики з `statmonitor`.
2. Головна функція `run_pipeline()` або `main()` стає компактною та читабельною.
3. Збереження сумісності top-level експортів для будь-яких зовнішніх модулів.

### Етап 4: Тестування та перевірка
1. Написання `test_modules.py` для перевірки імпорту та цілісності підмодулів.
2. Запуск усіх тестів проекту.
3. Оновлення документації (roadmap, architecture).
