# План впровадження SPEC-38: Zero-Cost Orchestration Sync & Atomic Financial Transactions

## Етапи робіт

1. **Cloudflare Worker Orchestration (`cloudflare/worker.js` та `deploy/cloudflare_webhook.js`)**:
   - Реалізувати функцію `checkShouldRunSupabase(env)`.
   - Інтегрувати перевірку перед викликом `triggerGitHubWorkflow` для `scheduled` cron та автоматичних вебхуків.
   - Забезпечити безперешкодний запуск для `source === "dashboard_button"` та `force=true`.
   - Забезпечити безпечний fail-open при відсутності змінних Supabase або помилках мережі.

2. **Атомарний фінансовий леджер (`statmonitor/real_bankroll.py`)**:
   - Оновити `record_real_transaction`:
     - Розрахунок балансу з використанням `SUM(amount_uah)`.
     - Для `ADJUSTMENT`: коректний запис різниці `new_balance - current_b` у поле `amount_uah` для збереження цілісності `SUM()`.
     - Транзакційна ізоляція з гарантованим `rollback` при помилках.
   - Оновити `get_real_bankroll_summary`:
     - Додати звірку та пріоритет `SUM(amount_uah)` над окремим останнім рядком.
     - Додати поле `ledger_sum` у результуючий словник.
   - Оновити `settle_real_bet_in_ledger`:
     - Гарантувати атомарну перевірку дублікатів розрахунку.

3. **Безпечна автентифікація Dashboard (`dashboard.py`)**:
   - Автоматичне прибирання чутливих параметрів `key` та `admin` з URL одразу після успішної авторизації.
   - Додавання кнопки `🚪 Вийти` (Logout) у навігаційну панель для адміністратора.

4. **Тестування та верифікація**:
   - Створити набір тестів у `test_real_bankroll.py` або `test_orchestration_sync.py` для перевірки:
     - Атомарності та цілісності сум у леджері при всіх типах операцій (`DEPOSIT`, `WITHDRAWAL`, `BET_RESULT`, `ADJUSTMENT`).
     - Захисту від витоку ключів та очищення query params.
     - Логіки перевірки `checkShouldRunSupabase`.
   - Прогнати повний набір unit-тестів (169+ тестів).

5. **Оновлення документації**:
   - `docs/roadmap.md`, `docs/roadmap-diagram.md`, `docs/architecture.md`, `docs/cloudflare_cron_setup.md`, `README.md`.
