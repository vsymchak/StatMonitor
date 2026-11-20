# SPEC-42: Quantitative Backtest Engine (Simulation Platform)

## 1. Контекст та Проблема
У StatMonitor накопичено значний масив історичних спортивних подій та ставок (`paper_bets` та `real_bankroll_ledger`), включаючи активні сигнали, відсіяні Shadow-ставки (SPEC-35), коефіцієнти відкриття та закриття лінії CLV (SPEC-20), оцінки Gemini AI (SPEC-21) та пороги беззбитковості Walkaway Odds (SPEC-37).

**Проблема:**
1. **Відсутність інструменту перевірки гіпотез**: користувач і моделіст не мають можливості перевірити, як повела б себе стратегія при іншій частці Келлі ($0.05$ vs $0.10$ vs $0.25$), при фіксованій ставці (Flat Stake) або при зміні порогу сили сигналу ШІ ($\ge 6$ vs $\ge 7$ vs $\ge 8$).
2. **Ризик "Overfitting" без мультистратегічного порівняння**: без інструменту Grid Sweep важко емпірично знайти точку оптимуму між ROI, просіданням (Max Drawdown) та коефіцієнтом Шарпа (Sharpe Ratio).
3. **Оцінка контрфактичного сценарію (No-AI Baseline)**: необхідність наочного моделювання кривої капіталу за умови, що ШІ-фільтр взагалі був би вимкнений, або працював у більш жорсткому режимі.

## 2. Мета специфікації
1. Розробити автономний квантитативний модуль симуляції `statmonitor/backtest.py` з підтримкою:
   - Хронологічної покрокової симуляції еволюції капіталу.
   - Різних моделей управління капіталом: Дробовий Келлі ($0.01..1.0 \times \text{Kelly}$), Фіксована ставка (Flat UAH), Фіксований відсоток від поточного капіталу (% of Bank).
   - Гнучких фільтрів: діапазон коефіцієнтів, мінімальна оцінка Gemini Confidence (0–10), вибір ліг та маркетів, включення/виключення Shadow-ставок, врахування Walkaway Odds (+EV).
2. Розрахунок професійних квантитативних метрик:
   - **Net Profit (Чистий прибуток)** та **ROI %**.
   - **CAGR / Віддача на капітал %**.
   - **Max Drawdown % та Max Drawdown ₴** (пік-дно).
   - **Profit Factor** ($\sum \text{Gross Wins} / \sum \text{Gross Losses}$).
   - **Sharpe Ratio** та **Sortino Ratio** (ризик-скоригована прибутковість).
   - **Win Rate %**, серії виграшів/програшів (Streaks).
3. Пакетний аналіз та Grid Search (порівняння стратегій):
   - Генерація порівняльної матриці готових бенчмарків (Live Default, Aggressive Kelly, Flat Stake, No AI Baseline, Ultra High Confidence).
   - Grid Sweep за сіткою параметрів.
4. Інтерактивна студія бектесту на Web Dashboard:
   - Окрема вкладка `🔬 Квантитативний Бектест (Simulation Platform)`.
   - Інтерактивні віджети налаштування параметрів та миттєвий запуск симуляції.
   - Візуалізація кривої капіталу (Plotly Equity Curve) із заливкою зон просідання.
   - Порівняльна таблиця стратегій та журнал змодельованих ставок.
5. Забезпечення 100% покриття автотестами та оновлення дорожньої карти (`docs/roadmap.md`).

## 3. Архітектурні деталі

### 3.1. Модуль симулятора `statmonitor/backtest.py`
- `run_backtest(bets_df, config=None)` -> `dict`:
  - `config`:
    - `initial_bankroll`: float (за замовчуванням 10,000 ₴)
    - `staking_model`: `'KELLY_FRACTION'`, `'FLAT'`, `'PERCENT_BANK'`
    - `fraction`: float (0.10)
    - `flat_amount`: float (100.0)
    - `percent_bank`: float (0.02)
    - `min_confidence`: int (7)
    - `min_odds`: float (1.10)
    - `max_odds`: float (10.0)
    - `include_shadow`: bool (False)
    - `enforce_walkaway`: bool (False)
    - `selected_sports`: list (None)
    - `max_stake_cap_pct`: float (0.05)
    - `min_stake_uah`: float (20.0)
  - Повертає:
    - `metrics`: словник підсумкових квант-показників.
    - `equity_curve`: часовий ряд зміни балансу, просідання, PnL кожної ставки.
    - `executed_bets`: датафрейм проведених ставок.
    - `skipped_count`: кількість відфільтрованих подій.

- `run_benchmark_comparison(bets_df, initial_bank=10000.0)` -> `pd.DataFrame`:
  - Порівнює 5 еталонних стратегій:
    1. **Базова жива (Default 0.10x Kelly, Conf >= 7)**.
    2. **Агресивна (0.25x Kelly, Conf >= 7)**.
    3. **Консервативна Flat (100 ₴ флет, Conf >= 7)**.
    4. **Контрфактична No-AI (0.10x Kelly, всі ставки включно з Shadow)**.
    5. **Елітний фільтр (0.10x Kelly, Conf >= 8)**.

- `calculate_sharpe_ratio(returns, risk_free_rate=0.0)` -> `float`:
  - Розраховує коефіцієнт Шарпа на основі процентних прибутків/збитків на угоду.

### 3.2. Інтеграція в `dashboard.py`
- Додавання вкладки `🔬 Бектест та Симуляція (SPEC-42)`:
  - Панель керування симулятором (Start capital, Model, Kelly Fraction, Min Conf, Odds range, Shadow/Walkaway checkboxes).
  - KPI-картки підсумку симуляції.
  - Графік кривої капіталу Plotly з динамічною темою (Dark/Light).
  - Таблиця бенчмарків з підсвічуванням найвищого ROI та найнижчого Drawdown.

### 3.3. Тестування (`test_backtest.py`)
- Unit-тести на:
  - Хронологічний порядок та математику балансу.
  - Моделі стейкінгу: Kelly, Flat, % of bank.
  - Коректність розрахунку просідання (Max Drawdown).
  - Врахування та відсікання Shadow-ставок.
  - Розрахунок коефіцієнта Шарпа та Profit Factor.
