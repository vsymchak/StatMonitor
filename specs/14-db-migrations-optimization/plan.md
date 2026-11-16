# Архітектурний план: Виділені міграції БД та оптимізація індексів (SPEC-14)

## 1. Архітектурний підхід
Для забезпечення надійності реляційної бази даних PostgreSQL (Supabase) застосовується класичний підхід декларативних SQL-міграцій із суворим контролем стану:

```
[migrations/]
   ├── 001_base_schema.sql
   ├── 002_performance_indexes.sql
   └── 003_v_odds_alerts.sql
          │
          ▼
    [migrate.py]  ────────►  [schema_migrations table]
          │
          ▼
   [Supabase PostgreSQL]
```

## 2. Етапи реалізації

### Етап 1: Створення SQL-файлів міграцій
1. `migrations/001_base_schema.sql`:
   - Створення таблиць `events`, `odds_history`, `paper_bets`, `ai_match_analysis`, `paper_daily_reports`, `scheduler_plan`, `system_heartbeat`.
   - Всі оператори містять `CREATE TABLE IF NOT EXISTS` для безпеки існуючих даних.
2. `migrations/002_performance_indexes.sql`:
   - Створення B-Tree індексів із `IF NOT EXISTS`.
3. `migrations/003_v_odds_alerts.sql`:
   - Створення або заміна представлення `CREATE OR REPLACE VIEW v_odds_alerts`.

### Етап 2: Реалізація міграційного раннера (`migrate.py`)
1. Функція `ensure_migrations_table(cur, conn)`.
2. Функція `get_applied_migrations(cur) -> set[str]`.
3. Функція `get_migration_files() -> list[tuple[str, str, str]]` (сортування за префіксом).
4. Функція `run_migrations(db_url=None, dry_run=False) -> list[str]`.
5. CLI інтерфейс з параметрами `--status` та `--dry-run`.

### Етап 3: Тестування та валідація
1. Модульні тести `test_migrate.py`:
   - Парсинг імен файлів міграцій.
   - Сортування черги виконання.
   - Ідемпотентність та обробка стану таблиці `schema_migrations`.
2. Перевірка синтаксису всіх SQL-файлів.

### Етап 4: Інтеграція та оновлення дорожньої карти
1. Підключення виклику `run_migrations()` у `main.py` при старті циклу.
2. Оновлення статусів у `docs/roadmap.md` та `docs/roadmap-diagram.md`.
