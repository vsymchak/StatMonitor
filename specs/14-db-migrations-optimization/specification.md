# Специфікація: Виділені міграції БД та оптимізація індексів і в'юшки v_odds_alerts (SPEC-14)

## 1. Контекст та мета
У процесі розвитку проекту `StatMonitor` структура бази даних створювалася фрагментарно:
* Частина таблиць створювалася через виклики `ensure_tables` у `main.py`.
* Інші таблиці створювалися в `scheduler.py` (`scheduler_plan`) та `sys_watchdog.py` (`system_heartbeat`).
* Ключова в'юшка детекції прогрузів `v_odds_alerts` створювалася вручну в консолі Supabase без фіксації у системі контролю версій (Git).
* З ростом обсягу таблиці `odds_history` (тисячі котирувань на добу) запити до бази та побудова графіків сповільнюються через відсутність складених (composite) індексів.

**Мета SPEC-14**:
1. Створити стандартизований, версіонований та ідемпотентний механізм міграцій БД (`migrate.py` + папка `migrations/`).
2. Зафіксувати еталонну DDL-схему всіх таблиць та представлень проекту.
3. Додати оптимізовані B-Tree індекси для таблиць `odds_history`, `events`, `paper_bets`, `scheduler_plan`.
4. Створити оптимізоване та версіоноване визначення аналітичної в'юшки `v_odds_alerts` із віконними функціями для миттєвої детекції прогрузів.

---

## 2. Архітектура міграцій

### А. Таблиця історії міграцій (`schema_migrations`)
```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Б. Структура файлів міграцій
Всі SQL-файли розміщуються в директорії `migrations/` із префіксом версії `NNN_nazva.sql`:
* `001_base_schema.sql` — створення базових таблиць (`events`, `odds_history`, `paper_bets`, `ai_match_analysis`, `paper_daily_reports`, `scheduler_plan`, `system_heartbeat`).
* `002_performance_indexes.sql` — складені індекси для прискорення селектів та JOIN.
* `003_v_odds_alerts.sql` — оптимізоване представлення пошуку прогрузів коефіцієнтів.

### В. Робота раннера (`migrate.py`)
1. Підключається до бази за `SUPABASE_DB_URL`.
2. Перевіряє наявність таблиці `schema_migrations` (створює її, якщо відсутня).
3. Зчитує всі файли `migrations/*.sql` в алфавітно-числовому порядку.
4. Порівнює з уже застосованими версіями у `schema_migrations`.
5. Застосовує лише нові міграції у транзакціях та фіксує їх виконання.
6. Підтримує запуск як через CLI (`--status`, `--dry-run`), так і програмно через `run_migrations()`.

---

## 3. Оптимізація індексів (SPEC-14 Index Plan)

Для запобігання деградації швидкодії таблиць додаються такі індекси:
1. `idx_odds_history_event_time` на `odds_history(event_id, recorded_at)` — прискорює побудову графіків коливань у часі.
2. `idx_odds_history_lookup` на `odds_history(event_id, bookmaker, market_key, outcome_name, recorded_at)` — прискорює вибірку історії для конкретного маркета.
3. `idx_odds_history_time` на `odds_history(recorded_at)` — миттєве видалення застарілих даних за 4 дні (`retention cleanup`).
4. `idx_events_commence` на `events(commence_time)` — швидка вибірка найближчих подій для планувальника.
5. `idx_paper_bets_pending` на `paper_bets(status, commence_time)` — фільтрація відкритих ставок.
6. `idx_scheduler_plan_target` на `scheduler_plan(target_time, status)` — пошук наступних точок запуску.

---

## 4. Оптимізація в'юшки `v_odds_alerts`

Представлення обчислює перший (`start_odds`) та поточний (`current_odds`) коефіцієнт для кожної лінії за останні 48 годин за допомогою віконних функцій `FIRST_VALUE` та `LAST_VALUE`:
* Фільтрація за валуйним діапазоном: $1.40 \le current\_odds \le 4.00$.
* Розрахунок просідання: `drop_pct = ROUND(((start_odds - current_odds) / start_odds) * 100, 2)`.
* Відбір сигналів із суттєвим падінням: `drop_pct >= 5.0%`.
* Автоматичний JOIN із `events` для отримання назви матчу, виду спорту та точного часу старту.

---

## 5. Критерії приймання (Acceptance Criteria)
* **AC-1**: Наявність директорії `migrations/` з версіонованими файлами `001_...`, `002_...`, `003_...`.
* **AC-2**: Модуль `migrate.py` успішно застосовує міграції, фіксує версії в `schema_migrations` та є строго ідемпотентним (повторний запуск не викликає помилок).
* **AC-3**: Складені індекси оптимізують доступ до `odds_history` та `events`.
* **AC-4**: В'юшка `v_odds_alerts` повертає очікувану структуру колонок, сумісну з `main.py`.
* **AC-5**: Наявність юніт-тестів `test_migrate.py`, інтеграція в систему та оновлення документації roadmap.
