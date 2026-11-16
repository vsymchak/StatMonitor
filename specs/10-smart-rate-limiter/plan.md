# План реалізації SPEC-10: Smart Rate-Limiter

1. **Створення модуля `statmonitor/limiter.py`**:
   - `ensure_poll_log_table(cur, conn)`: створення таблиці `sports_poll_log (sport TEXT PRIMARY KEY, last_polled_at TIMESTAMPTZ, next_poll_at TIMESTAMPTZ, status TEXT)`.
   - `classify_sports_urgency(cur, sports_map, now_utc)`: аналіз `events` у БД та визначення категорії кожного спорту (`HOT`, `WARM`, `COLD`).
   - `filter_sports_to_poll(cur, conn, sports_map, remaining_credits=None)`: повернення списку тільки тих ліг, які дійсно потрібно опитати в поточному циклі.
   - `record_poll_success(cur, conn, polled_sports, remaining_credits)`: фіксація часу опитування в БД.
2. **Інтеграція в `statmonitor/fetcher.py`**:
   - Підключення `filter_sports_to_poll` на початку `fetch_and_save_odds`.
   - Фіксація опитування після завершення через `record_poll_success`.
3. **Відображення на Дашборді (`dashboard.py`)**:
   - Відображення плашки: Залишок квоти The Odds API та статус Rate Limiter (NORMAL / ECO / CRITICAL).
4. **Тестування (`test_rate_limiter.py`)**:
   - Тестування класифікації ліг (`HOT` при матчах < 6 год, `WARM`, `COLD`).
   - Тестування перемикання режимів `NORMAL`, `ECO`, `CRITICAL`.
   - Тестування інтервалів між опитуваннями.
5. **Оновлення документації та пуш в Git**:
   - Оновлення `docs/roadmap.md` та `docs/roadmap-diagram.md` (Крок 10 -> Shipped).
   - Завантаження в репозиторій.
