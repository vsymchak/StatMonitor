# План впровадження SPEC-26: Weekly Graphical Financial Digest

## Фази реалізації:

- [x] **Фаза 1: Схема бази даних та міграції**
  - Створено міграцію `migrations/009_weekly_digests.sql`
  - Додано створення `weekly_digests` у `statmonitor/database.py:ensure_tables`

- [x] **Фаза 2: Модуль генерації графіків (Matplotlib)**
  - Реалізовано `build_weekly_equity_chart` у `statmonitor/chart.py`
  - Підтримка побудови у буфер пам'яті `io.BytesIO` без збереження тимчасових файлів на диск

- [x] **Фаза 3: Генерація фінансового дайджесту**
  - Створено `statmonitor/digest.py` з функцією `generate_weekly_digest`
  - Інтегровано розрахунок ROI, обороту, Win Rate, CLV та вибірку топ-3 ставок
  - Експортовано у `statmonitor/__init__.py`

- [x] **Фаза 4: Інтеграція в розклад, бота та CLI**
  - Додано автозапуск у неділю ввечері в `statmonitor/paper_trading.py:settle_and_report`
  - Додано команду `/digest` та оновлено кнопку у `statmonitor/bot.py`
  - Додано команду CLI `--weekly-digest` у `main.py`

- [x] **Фаза 5: Тестування та верифікація**
  - Написано модуль тестів `test_digest.py` (6 тестів)
  - Усі 111 тестів проєкту проходять успішно
  - Згенеровано прев'ю-зображення дайджесту на робочий стіл та в артефакти
