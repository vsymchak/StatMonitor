# План реалізації SPEC-22: Динамічний стейкінг за критерієм Келлі

## Кроки реалізації:
1. **Міграція 006**:
   - Створити `migrations/006_paper_bets_kelly_pct.sql` з `ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS kelly_pct NUMERIC(5,2);`.
   - Оновити `statmonitor/database.py` для ідемпотентної підтримки колонки.

2. **Модуль стейкінгу `statmonitor/paper_trading.py`**:
   - Додати функцію `calculate_kelly_fraction(odds, drop_pct=None, confidence=None, fraction=0.25, min_pct=0.01, max_pct=0.05)`.
   - Оновити `place_paper_bet(...)`: приймати `drop_pct=None`, розраховувати `frac` та зберігати `kelly_pct` у базі даних.
   - Експортувати нову функцію в `statmonitor/__init__.py`.

3. **Оркестратор `statmonitor/pipeline.py`**:
   - Передавати `drop_pct=f.get("drop")` у виклик `place_paper_bet`.

4. **Telegram Bot `statmonitor/bot.py`**:
   - Оновити `cmd_bets`: вибирати `kelly_pct` (з fallback на розрахунок) та показувати `({kelly_pct}% банку за Келлі)` біля суми ставки.

5. **Web Dashboard `dashboard.py`**:
   - Додати колонку `"% банку (Келлі)"` у таблицю активних ставок.
   - Оновити випадаюче меню редагування коефіцієнтів з відображенням розміру ставки та % Келлі.

6. **Тестування та документація**:
   - Створити набір тестів `test_kelly.py` (розрахунок формули, граничні умови, clamping, стейкінг).
   - Оновити `docs/roadmap.md`, `docs/roadmap-diagram.md`, `docs/architecture.md`, `README.md`.
