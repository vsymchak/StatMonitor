# План реалізації SPEC-31: Real Money Mode & Gemini Vision Bet Slip OCR

## Фаза 1: Схема бази даних та леджер
- [x] Створити SQL-міграцію `migrations/014_real_money_mode_ocr.sql` з полями `is_real_bet`, `real_stake_uah`, `real_odds`, `slip_meta` та таблицею `real_bankroll_ledger`.
- [x] Реалізувати логіку старту банкролу з 0 ₴ (формування депозитами `DEPOSIT` без фіктивних початкових сум).
- [x] Додати індекси на `is_real_bet` та `transaction_type`.

## Фаза 2: Модуль обліку реального банку (`statmonitor/real_bankroll.py`)
- [x] Реалізувати `ensure_real_bankroll_tables(cur, conn)` для автоматичної ініціалізації.
- [x] Реалізувати `get_real_bankroll_summary(cur, conn)`: розрахунок балансу, суми депозитів, обороту, чистого прибутку, ROI % та Win Rate.
- [x] Реалізувати `record_real_transaction(cur, conn, tx_type, amount, ...)`: внесення операцій `DEPOSIT`, `WITHDRAWAL`, `ADJUSTMENT`, `BET_RESULT`.
- [x] Реалізувати `toggle_real_bet(cur, conn, bet_id, is_real, ...)`: встановлення / зняття позначки реальної ставки із збереженням Paper-трейдингу.
- [x] Реалізувати `settle_real_bet_in_ledger(cur, conn, bet_id, outcome, profit, stake)`: транзакційне проведення результату ставки у фінансовий леджер.

## Фаза 3: AI OCR модуль купонів (`statmonitor/slip_ocr.py`)
- [x] Реалізувати `parse_bet_slip_with_gemini(image_bytes, ...)` з передачею Base64 у Gemini Multimodal API та структурованим JSON-виводом.
- [x] Реалізувати `match_slip_with_pending_bets(slip_data, pending_bets)`: нечітке співставлення команд, маркету та коефіцієнта з активними ставками.
- [x] Реалізувати `apply_slip_to_bet(cur, conn, bet_id, slip_data, image_path)`: фіксація купона та маркування ставки як реальної.

## Фаза 4: Веб-інтерфейс (Streamlit Dashboard)
- [x] Додати банер стану реального банку у верхню частину дашборду.
- [x] Впровадити інтерактивний `st.data_editor` з `CheckboxColumn("🟢 Real")` у таблицю активних ставок `⏳ Активні ставки в грі (Pending)` для адміністратора.
- [x] Забезпечити відображення статусу `🟢 Real` / `⚪ Paper` для гостей у режимі лише для читання.
- [x] Додати блок OCR-завантаження купона букмекера у кабінет адміністратора з попереднім переглядом.
- [x] Додати блок управління касою (депозити, виведення, коригування) та перегляду журналу транзакцій леджера.
- [x] Додати модальний інструмент ручного розрахунку ставки (Manual Settle) з вибором результату та рахунку.

## Фаза 5: Тестування та верифікація
- [x] Написати тести `test_real_bankroll.py` для всіх операцій леджера та маркування ставок.
- [x] Написати тести `test_slip_ocr.py` для розпізнавання, валідації та співставлення купонів.
- [x] Забезпечити проходження всіх 149 тестів у тестовому наборі проекту.
