# План реалізації SPEC-20: Closing Line Value (CLV) Tracking & Beat the Line %

## Фаза 1: Схема бази даних та міграція
- [x] Створити SQL-міграцію `migrations/008_paper_bets_clv.sql` з полями `closing_odds`, `clv_pct`, `beat_closing_line`, `closing_recorded_at`.
- [x] Додати резервні `ALTER TABLE` інструкції до `statmonitor/database.py:ensure_tables`.

## Фаза 2: Аналітичні алгоритми CLV
- [x] Реалізувати `calculate_clv_value(bet_odds, closing_odds)` у `statmonitor/analytics.py`.
- [x] Реалізувати агрегатор `calculate_clv_metrics(bets)` для портфеля ставок.
- [x] Експортувати функції у `statmonitor/__init__.py`.

## Фаза 3: Інтеграція у Paper Trading & Конвеєр
- [x] Створити `capture_closing_lines(cur, conn)` у `statmonitor/paper_trading.py`.
- [x] Інтегрувати виклик `capture_closing_lines` на початку `settle_and_report`.
- [x] Підключити оновлення CLV до перерахунку ставок `recalculate_historical_paper_bets`.
- [x] Додати зведення CLV до щоденного звіту Telegram у `settle_and_report`.

## Фаза 4: Інтерфейси (Dashboard & Bot)
- [x] Додати метрики Beat the Line % та CLV у Telegram-бот (`/bank`).
- [x] Додати стовпчик `CLV (+EV)` до міні-журналу останніх операцій у `dashboard.py`.
- [x] Додати аналітичну плашку CLV до секції Breakdown у `dashboard.py`.

## Фаза 5: Тестування та верифікація
- [x] Написати вичерпні тести `test_clv.py`.
- [x] Перевірити сумісність з існуючими тестами (`test_bot.py`, `test_dashboard.py`).
- [x] Перевірити проходження 100% тестів проекту (`python -m unittest discover`).

## Фаза 6: Документація та реліз
- [x] Створити `specs/20-clv-tracking/specification.md` та `plan.md`.
- [ ] Оновити `docs/roadmap.md`, `docs/roadmap-diagram.md`, `docs/architecture.md`, `README.md`.
- [ ] Зробити git commit та push у гілку `main`.
