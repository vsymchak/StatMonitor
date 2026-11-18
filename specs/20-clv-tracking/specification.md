# SPEC-20: Фіксація лінії закриття (Closing Line Value) та розрахунок Beat the Line %

## 1. Контекст та мета
У професійній предиктивній аналітиці та беттингу показник **Closing Line Value (CLV)** є золотим стандартом валідації якості математичної моделі.
Лінія закриття ринку (Closing Line) у провідних бенчмарк-букмекерах (Pinnacle, Betfair Exchange) акумулює всю публічну та інсайдерську інформацію безпосередньо перед початком матчу і є найбільш ефективною оцінкою ймовірностей.

Якщо система стабільно бере коефіцієнти, вищі за лінію закриття ($CLV > 0\%$, $\text{Beat the Line} > 50\%$), вона має гарантоване позитивне математичне очікування (+EV) на дистанції незалежно від короткострокової дисперсії результатів окремих ігор.

**Мета SPEC-20**:
1. Фіксувати еталонний коефіцієнт закриття лінії (`closing_odds`) у точці `PRE_MATCH` (~15–25 хв до старту або на момент початку гри) за провідними бенчмарками (`BENCHMARK_BOOKMAKERS`: Pinnacle, Betfair, Unibet, Marathonbet).
2. Автоматично розраховувати показник $CLV\%$ та бінарний прапорець `beat_closing_line` для кожного парі у віртуальному банку (`paper_bets`).
3. Агрегувати показники успішності стратегії:
   - **Beat the Closing Line %**: частка ставок, у яких коефіцієнт входу був вигіднішим за коефіцієнт закриття;
   - **Середній CLV (+EV)**: середня математична перевага системи над ринком у відсотках.
4. Зберігати історію закриття у базі даних (`paper_bets`) через міграцію `008_paper_bets_clv.sql`.
5. Відображати метрики CLV:
   - **Web Dashboard**: стовпець `CLV (+EV)` у таблиці останніх та активних операцій, а також окремий аналітичний блок у секції Breakdown.
   - **Telegram-бот**: виведення `Beat the Closing Line %` та `Сер. CLV` у команді `/bank`, деталізація закриття у щоденному фінансовому звіті.
6. 100% покриття юніт-тестами (`test_clv.py`).

---

## 2. Математична модель

### 2.1. Розрахунок для окремої ставки
Для кожної ставки з фіксованим коефіцієнтом $k_{\text{bet}}$ та зафіксованою лінією закриття $k_{\text{closing}}$:
$$CLV\% = \left(\frac{k_{\text{bet}}}{k_{\text{closing}}} - 1\right) \times 100\%$$

$$\text{beat\_closing\_line} = \begin{cases} \text{True}, & \text{якщо } k_{\text{bet}} > k_{\text{closing}} \\ \text{False}, & \text{якщо } k_{\text{bet}} \le k_{\text{closing}} \end{cases}$$

*Приклад 1*: Ставка взята за $k_{\text{bet}} = 2.10$, закрилася за $k_{\text{closing}} = 1.85$.
$$CLV = \left(\frac{2.10}{1.85} - 1\right) \times 100\% = +13.51\% \quad (\text{beat} = \text{True})$$

*Приклад 2*: Ставка взята за $k_{\text{bet}} = 1.80$, закрилася за $k_{\text{closing}} = 1.95$.
$$CLV = \left(\frac{1.80}{1.95} - 1\right) \times 100\% = -7.69\% \quad (\text{beat} = \text{False})$$

### 2.2. Агреговані метрики (Портфель ставок)
Для набору ставок $N_{\text{CLV}}$ із зафіксованою лінією закриття:
$$\text{Beat the Line \%} = \frac{N_{\text{beat}}}{N_{\text{CLV}}} \times 100\%$$
$$\overline{CLV\%} = \frac{1}{N_{\text{CLV}}} \sum_{i=1}^{N_{\text{CLV}}} CLV_i$$

---

## 3. Схема БД та міграція 008
Файл `migrations/008_paper_bets_clv.sql`:
```sql
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS closing_odds NUMERIC(6,3);
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS clv_pct NUMERIC(6,2);
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS beat_closing_line BOOLEAN;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS closing_recorded_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_paper_bets_clv ON paper_bets(closing_odds, beat_closing_line);
```

---

## 4. Архітектура компонентів
- `statmonitor/analytics.py`:
  - `calculate_clv_value(bet_odds, closing_odds)`: чиста функція розрахунку для одного парі.
  - `calculate_clv_metrics(bets)`: агрегація Beat the Line % та середнього CLV для списку ставок / DataFrame.
- `statmonitor/paper_trading.py`:
  - `capture_closing_lines(cur, conn)`: сканує активні/розраховані ставки без зафіксованого закриття за 25 хв до початку або після старту, підтягує медіанний коефіцієнт бенчмарків з `odds_history` на момент `commence_time` та зберігає в базі.
  - Інтегровано у `settle_and_report` та `recalculate_historical_paper_bets`.
- `statmonitor/bot.py`:
  - У команді `/bank`: додано рядок `🎯 Beat the Closing Line: XX.X% | Сер. CLV: +X.XX%`.
- `dashboard.py`:
  - Відображення колонки `CLV (+EV)` у таблиці останніх операцій (`+13.5% 🏆` / `-7.7%`).
  - Окремий блок аналітики CLV у розділі Breakdown.
