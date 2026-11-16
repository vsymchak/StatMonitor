# Чекліст виконання (SPEC-09)

- [x] 1. Створити `watchdog.py`:
  - [x] `ensure_heartbeat_table(cur, conn)`
  - [x] `record_heartbeat(cur, conn, duration_sec, status, metadata)`
  - [x] `detect_missed_checkpoints(cur, conn, now_utc)`
  - [x] `detect_stale_heartbeat(last_ping_at, now_utc)`
  - [x] `ping_external_watchdog(url)`
  - [x] `format_watchdog_alert(missed_points, stale_info)`
- [x] 2. Створити автотести `test_watchdog.py` для перевірки розрахунку дельти запізнень і формування тексту алерта.
- [x] 3. Інтегрувати виклики `watchdog` у `main.py` (діагностика перед запуском, запис пульсу та пінг на фініші).
- [x] 4. Оновити статус у `docs/roadmap.md` та `docs/roadmap-diagram.md` (перевести крок 9 у Shipped!).
- [x] 5. Запустити тести та перевірити компіляцію.
