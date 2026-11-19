# Чекліст виконання SPEC-38

- [x] 1. Оновити `cloudflare/worker.js` та `deploy/cloudflare_webhook.js` із підтримкою zero-cost edge-перевірки Supabase REST API перед dispatch.
- [x] 2. Оновити `statmonitor/real_bankroll.py`: атомарний розрахунок сум `SUM(amount_uah)`, збереження цілісності при коригуваннях `ADJUSTMENT`, захист від розбіжностей.
- [x] 3. Оновити `dashboard.py`: санітизація URL (видалення `?key=...` після логіну) та кнопка `🚪 Вийти` у панелі навігації.
- [x] 4. Створити / оновити unit-тести для перевірки леджера, синхронізації та автентифікації (`test_orchestration_sync.py`).
- [x] 5. Переконатися у проходженні 100% тестів без регресій (174 тести).
- [x] 6. Оновити документацію: `docs/cloudflare_cron_setup.md`, `README.md`, `architecture.md`, `roadmap.md`, `roadmap-diagram.md`.
