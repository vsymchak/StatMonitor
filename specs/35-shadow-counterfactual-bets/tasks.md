# Чекліст виконання SPEC-35

- [x] 1. Створити міграцію `migrations/015_shadow_counterfactual_bets.sql` та оновити `statmonitor/database.py`.
- [x] 2. Оновити `place_paper_bet`, `settle_and_report` та `manual_settle_bet` у `statmonitor/paper_trading.py` для збереження та авторозрахунку shadow-ставок.
- [x] 3. Реалізувати аналітичні функції `calculate_counterfactual_audit` та `calculate_confidence_calibration` у `statmonitor/analytics.py`.
- [x] 4. Оновити `dashboard.py`: блок контрфактичного аудиту, калібровки та реєстр shadow-ставок на вкладці `🧠 AI-аналітика Gemini`.
- [x] 5. Оновити `test_confidence.py` та створити `test_shadow_bets.py`.
- [x] 6. Запустити повний набір unit-тестів і переконатися у 100% успіху.
- [x] 7. Оновити дорожню карту та документацію (`README.md`, `architecture.md`, `roadmap.md`, `roadmap-diagram.md`).
