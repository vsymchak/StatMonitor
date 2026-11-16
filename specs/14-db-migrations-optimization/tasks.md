# Чекліст виконання (SPEC-14)

- [x] 1. Створити каталог `migrations/` та SQL-файли:
  - [x] `migrations/001_base_schema.sql` (базові таблиці системи)
  - [x] `migrations/002_performance_indexes.sql` (цільові B-Tree індекси)
  - [x] `migrations/003_v_odds_alerts.sql` (оптимізоване представлення v_odds_alerts)
- [x] 2. Розробити модуль та CLI `migrate.py`:
  - [x] Створення службової таблиці `schema_migrations`
  - [x] Зчитування та сортування міграцій
  - [x] Застосування транзакцій з фіксацією результатів
  - [x] Підтримка режимів `--status` та `--dry-run`
- [x] 3. Написати тестовий набір `test_migrate.py`.
- [x] 4. Інтегрувати виклик `run_migrations` у старт `main.py`.
- [x] 5. Запустити повний пакет тестів, перевірити компіляцію.
- [x] 6. Оновити `docs/roadmap.md` та `docs/roadmap-diagram.md` (крок 14 -> Shipped).
- [x] 7. Зафіксувати зміни та завантажити в репозиторій Git.
