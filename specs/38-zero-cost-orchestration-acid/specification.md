# SPEC-38: Zero-Cost Orchestration Sync & Atomic Financial Transactions

## 1. Контекст та Проблема
У поточній конфігурації системи:
1. **Білінговий ризик GitHub Actions**: При регулярному опитуванні через Cloudflare Worker Cron кожні 15–20 хвилин (або Cron-job) запит `workflow_dispatch` пробуджує runner GitHub Actions. Навіть коли Python-скрипт завдяки `should_execute_pipeline` (SPEC-32) визначає відсутність подій і завершується за 1 секунду, GitHub Actions округлює час білінгу до повної хвилини. За 72–96 запусків на добу це спалює до 2 880 хв/місяць, вичерпуючи безкоштовний ліміт (2000 хв) публічних/приватних репозиторіїв.
2. **Ризик фінансової неузгодженості леджера (`real_bankroll_ledger`)**: При неатомарному читанні `balance_after_uah` з останнього запису та наступному записі нового рядка виникає ризик розбіжності між поточним балансом та математичною сумою транзакцій `SUM(amount_uah)`, особливо при коригуваннях (`ADJUSTMENT`) або паралельних операціях.
3. **Безпека автентифікації на Web Dashboard**: Передача адміністративного ключа через URL (`?key=...` або `?admin=...`) залишає секретний ключ у адресному рядку браузера, історії навігації та заголовках `Referer` при переході на зовнішні ресурси.

## 2. Мета та Вимоги (Requirements)
1. **Zero-Cost Orchestration Sync у Cloudflare Worker**:
   - Перед відправкою `POST /dispatches` у GitHub Actions воркер виконує легкий HTTP-запит до REST API Supabase (`/rest/v1/`).
   - Перевіряє наявність:
     1. Запланованих точок у `scheduler_plan` (`status = 'PLANNED'` у вікні `[now - 25m, now + 7m]`).
     2. Ставок у `paper_bets`, що потребують розрахунку (`status = 'PENDING'` та `commence_time < now - 85m`).
     3. Необхідності періодичного сканування (`system_heartbeat` для `scheduler_run` старіший за 80 хвилин).
   - Якщо подій немає — воркер повертає `skipped: true` без виклику GitHub Actions (0 використаних хвилин білінгу).
   - При прямому запуску з кнопки Dashboard (`source=dashboard_button` або `force=true`) або відсутності ключів Supabase — fail-open запуск GitHub Actions.
2. **Атомарність фінансового леджера (`statmonitor/real_bankroll.py`)**:
   - Розрахунок балансу суворо через агрегатний розрахунок `COALESCE(SUM(amount_uah), 0)` та звірку з `balance_after_uah`.
   - Забезпечення рівності $\sum \text{amount\_uah} \equiv \text{balance\_after\_uah}$ для кожної транзакції (включаючи `ADJUSTMENT` із дельтою).
   - Строгий транзакційний контекст із `commit` / `rollback`.
   - Захист від подвійного зарахування результатів ставок (`BET_RESULT`).
3. **Безпечна автентифікація Dashboard (`dashboard.py`)**:
   - При виявленні `key` або `admin` у query parameters: валідація, встановлення `st.session_state.is_admin = True`, негайне очищення query params з адресного рядка URL та `st.rerun()`.
   - Додавання кнопки безпечного виходу `🚪 Вийти` (Logout) у навігаційній панелі.
