# План реалізації SPEC-34: No-Vig Edge & Independent Real Bank Sizing

## Фаза 1: Математичний модуль No-Vig (`statmonitor/novig.py`)
- [x] Реалізувати `calculate_novig_fair_probability(odds_1, odds_2)` для 2-сторонніх ліній.
- [x] Реалізувати `calculate_novig_3way(odds_1, odds_x, odds_2)` для 1X2.
- [x] Реалізувати `calculate_edge_and_ev(offered_odds, fair_prob)`.
- [x] Реалізувати `calculate_walkaway_odds(fair_prob, min_edge=0.02)`.
- [x] Реалізувати `calculate_real_stake(odds, real_balance, fair_prob=None, drop_pct=None, confidence=None, fraction=0.10, min_stake=20.0, max_pct=0.05)`.

## Фаза 2: Логіка банкролу та пакетного переносу (`statmonitor/real_bankroll.py`)
- [x] Додати функцію `calculate_and_apply_real_stakes(cur, conn, bet_ids_with_stakes)` для безпечного транзакційного збереження.
- [x] Додати функцію підготовки проекту реальних ставок за поточним балансом (`prepare_real_stakes_batch`, `apply_real_stakes_batch`).

## Фаза 3: Інтерфейс у Streamlit (`dashboard.py`)
- [x] У таблиці активних ставок додати кнопку `⚡ Перенести в Реальні ставки & Розрахувати банк`.
- [x] Створити блок розрахунку:
  - [x] Відображення балансу реального банку;
  - [x] Таблиця обраних ставок із розрахованими сумами від реального депозиту;
  - [x] Поля ручного коригування сум;
  - [x] Підсумкова експозиція (% від банку);
  - [x] Кнопка підтвердження та фіксації.

## Фаза 4: Тестування
- [x] Створити `test_novig_edge.py` для 100% покриття формул No-Vig, EV та стейкінгу.
- [x] Перевірити проходження всіх тестів проекту (`python -m unittest discover`, 162 тести).

## Фаза 5: Документація та фіксація
- [x] Оновити `docs/roadmap.md` та `docs/roadmap-diagram.md` (Крок 34 -> Shipped).
- [ ] Коміт та пуш у гілку `main`.
