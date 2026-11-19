# Чекліст виконання SPEC-37

- [x] 1. Розширити `statmonitor/novig.py`: `estimate_walkaway_odds` та `format_walkaway_instruction`.
- [x] 2. Створити міграцію `migrations/016_paper_bets_walkaway_odds.sql` та оновити `statmonitor/paper_trading.py`.
- [x] 3. Інтегрувати інструкцію Walkaway Odds в алерти та зведення `statmonitor/pipeline.py`.
- [x] 4. Оновити команди `/bets` та `/edit_odds` у `statmonitor/bot.py`.
- [x] 5. Додати `walkaway_odds` у `prepare_real_stakes_batch` в `statmonitor/real_bankroll.py`.
- [x] 6. Оновити таблиці активних ставок та блок розрахунку в `dashboard.py`.
- [x] 7. Створити вичерпний набір тестів `test_walkaway_odds.py`.
- [x] 8. Переконатися у 100% успішному проходженні всіх тестів.
- [x] 9. Оновити документацію: `README.md`, `architecture.md`, `roadmap.md`, `roadmap-diagram.md`.
