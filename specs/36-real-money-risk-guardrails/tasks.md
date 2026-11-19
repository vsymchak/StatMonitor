# Чекліст виконання SPEC-36

- [x] 1. Реалізувати функції запобіжників у `statmonitor/real_bankroll.py`: `check_daily_stop_loss`, `check_max_exposure`, `check_correlation_guard` та `evaluate_real_risk_guardrails`.
- [x] 2. Інтегрувати гейт ризиків у `prepare_real_stakes_batch` та `apply_real_stakes_batch`.
- [x] 3. Оновити Web Dashboard (`dashboard.py`): блок Circuit Breakers на вкладці `tab_real` та перевірка ризиків при перенесенні ставок.
- [x] 4. Створити вичерпний тестовий набір `test_risk_guardrails.py` та оновити існуючі тести (10 нових тестів).
- [x] 5. Переконатися у проходженні 100% unit-тестів без помилок (184 тести).
- [x] 6. Оновити документацію: `README.md`, `architecture.md`, `roadmap.md`, `roadmap-diagram.md`.
