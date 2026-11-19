# SPEC-37: Walkaway Odds in Telegram Alerts (`🎯 Ставити, поки коеф ≥ X.XX`)

> **Статус**: 🟩 Shipped  
> **Хвиля**: Wave 11 (Capital Safety & Quant Staking)  
> **Дата**: 19.11.2026  
> **Автор**: Володимир Симчак & Antigravity  
> **Тести**: 194/194 unit-тести (10 у `test_walkaway_odds.py`)  

---

## 1. Мета та Контекст

У спортивному квант-трейдингу коефіцієнти динамічно змінюються. Між моментом, коли алгоритм зафіксував просідання (сигнал) та надіслав сповіщення в Telegram, і моментом, коли гравець відкриває мобільний застосунок БК (Favbet, VBET тощо), може пройти від 1 до 10 хвилин.

За цей час ринок продовжує рух:
- Якщо котирування впали ще глибше (наприклад, з `2.02` до `1.85`), математична очікувана цінність ставки ($EV$) стрімко зменшується і стає від'ємною ($EV < 0$).
- Вхід у ставку з коефіцієнтом, нижчим за точку беззбитковості (Break-even odds), перетворює прибуткову стратегію на дистанційно збиткову (Steam Chasing Trap).

**Мета SPEC-37**:
1. Автоматично розраховувати **Walkaway Odds** ($k_{\text{walkaway}}$) — мінімальний граничний коефіцієнт, нижче якого вхід у ринок категорично заборонено ($EV < \text{min\_edge}$).
2. Додати чітку інструкцію до Telegram-алертів та зведення ставок:  
   `🎯 Ставити, поки коеф ≥ X.XX`
3. Зберігати `walkaway_odds` у базі даних (`paper_bets`) для аудиту та аналізу якості виконання (Slippage Audit).
4. Відображати колонку `Поріг (Walkaway)` у таблицях активних ставок (Paper Bank та Real Bank), а також попереджати трейдера при редагуванні коефіцієнта чи в модальному вікні пакетного розрахунку, якщо коефіцієнт опустився нижче допустимої межі.

---

## 2. Математична Модель Walkaway Odds

### 2.1. Справжня ймовірність $p_{\text{fair}}$
1. **Зняття маржі (De-vigging Pinnacle/Betfair)**:
   Якщо доступні парні котирування бенчмарка без маржі:
   $$p_{\text{fair}} = \text{de-vig}(k_1, k_2)$$
2. **Heuristic Implied Edge (Fallback)**:
   Якщо доступний лише зафіксований дроп $d\%$ та AI Confidence $c \in [1, 10]$:
   $$\text{Edge} = \left(0.02 + \frac{\min(d, 30)}{100} \times 0.18\right) \times \left(0.6 + \frac{c}{10} \times 0.4\right)$$
   $$p_{\text{fair}} = \frac{1 + \text{Edge}}{k_{\text{signal}}}$$

### 2.2. Розрахунок граничного коефіцієнта Walkaway
Для збереження мінімальної математичної переваги $\text{min\_edge} = 1.5\%$ ($0.015$):
$$k_{\text{walkaway}} = \text{round}\left(\frac{1.0 + \text{min\_edge}}{p_{\text{fair}}}, 2\right)$$
- Якщо $k_{\text{walkaway}} > k_{\text{signal}}$ (початковий edge був нижчим за поріг), то $k_{\text{walkaway}} = k_{\text{signal}}$.
- Якщо фактичний коефіцієнт у БК $k_{\text{real}} < k_{\text{walkaway}}$, гравець **не робить ставку**.

---

## 3. Точки Інтеграції

1. **`statmonitor/novig.py`**:
   - `estimate_walkaway_odds(odds, drop_pct, confidence, fair_prob, min_edge=0.015) -> float`
   - `format_walkaway_instruction(walkaway_k) -> str`
2. **`statmonitor/pipeline.py`**:
   - Telegram Alert Caption: додавання рядка `🎯 Ставити, поки коеф ≥ X.XX` безпосередньо під `🎯 Головний сигнал`.
   - Telegram AI Summary: відображення порогу входу `🛑 Поріг: ≥ X.XX` для кожного рекомендованого матчу.
   - Збереження `walkaway_odds` при створенні запису в `paper_bets`.
3. **`statmonitor/paper_trading.py`**:
   - Прийом та збереження `walkaway_odds` у `place_paper_bet`.
4. **`statmonitor/real_bankroll.py`**:
   - Відображення `walkaway_odds` у пропозиціях `prepare_real_stakes_batch`.
5. **`statmonitor/bot.py`**:
   - У команді `/bets` відображення порогу входу.
   - У команді `/edit_odds` перевірка, чи не став новий коефіцієнт нижчим за Walkaway Odds із виведенням застереження.
6. **`dashboard.py`**:
   - Колонка `Поріг (Walkaway)` у таблицях активних ставок (Paper та Real).
   - Підказка порогу в модальному вікні пакетного розрахунку реальних ставок.
7. **Міграція бази даних**:
   - `migrations/016_paper_bets_walkaway_odds.sql` (`ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS walkaway_odds NUMERIC(6,2);`).
