# План реалізації SPEC-35

## Етап 1: База даних та міграція
1. Створити файл міграції `migrations/015_shadow_counterfactual_bets.sql`.
2. Оновити fallback DDL у `statmonitor/database.py`.

## Етап 2: Збереження та розрахунок Shadow-ставок
1. Модифікувати `place_paper_bet` у `statmonitor/paper_trading.py`:
   - Замість виходу при `confidence < 7` або `skip` фіксувати ставку з `status = 'FILTERED'`, `is_shadow = TRUE`, `shadow_status = 'PENDING'`, `profit_uah = 0.00`.
   - Зберігати розраховану гіпотетичну суму ставки `stake_uah` та `filter_reason`.
2. Модифікувати `settle_and_report` у `statmonitor/paper_trading.py`:
   - Включити у вибірку завершення `status = 'FILTERED' AND (shadow_status = 'PENDING' OR shadow_status IS NULL)`.
   - Зафіксувати `shadow_status = WON/LOST/VOID`, `shadow_profit_uah`, `match_score`, не чіпаючи `profit_uah`.
3. Оновити `manual_settle_bet` для підтримки розрахунку shadow-ставок.

## Етап 3: Квантитативна аналітика та калібровка
1. Реалізувати `calculate_counterfactual_audit(bets)` у `statmonitor/analytics.py`.
2. Реалізувати `calculate_confidence_calibration(bets)` із розрахунком Brier Score у `statmonitor/analytics.py`.

## Етап 4: Візуалізація у Web Dashboard
1. Оновити `dashboard.py`:
   - Додати аналітичний блок «Counterfactual AI Audit» на вкладці `🧠 AI-аналітика Gemini`.
   - Додати калібраційну таблицю бакетів оцінок.
   - Додати реєстр відсіяних ставок.

## Етап 5: Тестування та верифікація
1. Оновити `test_confidence.py` під нову поведінку збереження shadow-ставок.
2. Створити окремий модульний тест `test_shadow_bets.py` для перевірки всіх аспектів SPEC-35.
3. Перевірити, що всі 162+ тестів проходять успішно.
