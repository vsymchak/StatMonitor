# Чекліст реалізації (SPEC-08)

- [x] 1. Створити `scheduler.py` з функціями:
  - [x] `cluster_events(events, threshold_minutes)`
  - [x] `generate_schedule_points(events, pending_bets, now_utc)`
  - [x] `ensure_scheduler_tables(cur, conn)`
  - [x] `sync_schedule_to_db(cur, conn, points)`
  - [x] `format_schedule_for_tg(points)`
- [x] 2. Створити юніт-тести для `cluster_events` та `generate_schedule_points` у `test_scheduler.py`.
- [x] 3. Інтегрувати виклик динамічного розкладу в `main.py` (після завершення основного циклу).
- [x] 4. Оновити статус у `docs/roadmap.md` та `docs/roadmap-diagram.md` для пункту 8 (перевести в Shipped!).
- [x] 5. Провести верифікацію синтаксису та виконання тестів.
