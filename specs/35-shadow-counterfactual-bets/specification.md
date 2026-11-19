# SPEC-35: Shadow-Bets & Counterfactual AI Audit (`status = 'FILTERED'`)

## 1. Контекст та Проблема
У поточній версії StatMonitor (v3.5) реалізовано фільтрацію валуйних сигналів за допомогою оцінки впевненості моделі Gemini (`AI Confidence Score >= 7/10`, SPEC-21). Якщо сигнал оцінено в 1–6 з 10, або вердикт ШІ містить рекомендацію «пропустити / утриматися», ставка безповоротно відхиляється і не потрапляє до бази даних.

**Проблема:**
1. **Відсутність доказової бази ефективності ШІ**: за відсутності збереження відхилених подій неможливо довести, чи фільтр $\ge 7/10$ справді покращує підсумковий ROI, чи, навпаки, відсікає прибуткові валуйні ставки.
2. **Неможливість A/B тестування**: неможливо порівняти фактичну стратегію проти гіпотетичної базової лінії («що було б, якби ми ставили на всі прогрузи без участі ШІ»).
3. **Некалібрований Confidence Score**: оцінка 1–10 потребує емпіричної калібровки (Brier Score, окупність та win rate за бакетами 1–4, 5–6, 7–8, 9–10).

## 2. Мета специфікації
1. Зберігати всі відсіяні системою ставки як **Shadow-ставки** у таблиці `paper_bets` зі статусом `status = 'FILTERED'` та позначкою `is_shadow = TRUE`.
2. Забезпечити **нульовий вплив на баланс**: shadow-ставки мають `profit_uah = 0.00` та не блокують кошти віртуального чи реального банкролу.
3. Автоматично відстежувати та розраховувати завершення матчів для shadow-ставок у `settle_and_report` із фіксацією гіпотетичного профіту в окремому полі `shadow_profit_uah` та статусу `shadow_status` (`WON`, `LOST`, `VOID`).
4. Надати модуль аналітики **Counterfactual AI Audit** у `statmonitor/analytics.py` для розрахунку доданої вартості ШІ (Alpha $\Delta\text{ROI}$, $\Delta\text{WinRate}$, збережений капітал).
5. Відображати результати аудиту, калібровку оцінок та реєстр shadow-ставок на веб-дашборді у вкладці `🧠 AI-аналітика Gemini`.

## 3. Архітектурні зміни

### 3.1. DDL Міграція (`015_shadow_counterfactual_bets.sql`)
Таблиця `paper_bets` розширюється новими полями:
- `is_shadow BOOLEAN DEFAULT FALSE`: прапорець shadow-ставки.
- `shadow_status TEXT`: статус розрахунку shadow-ставки (`PENDING`, `WON`, `LOST`, `VOID`).
- `shadow_profit_uah NUMERIC(10, 2) DEFAULT 0.00`: гіпотетичний PnL.
- `filter_reason TEXT`: причина відсікання (`LOW_CONFIDENCE (X/10 < 7)`, `AI_SKIP`, тощо).

### 3.2. Логіка пайплайну (`statmonitor/paper_trading.py`)
- У `place_paper_bet`:
  - Якщо `confidence < 7` або рекомендація "пропустити" — формується запис `status = 'FILTERED'`, `is_shadow = TRUE`, `shadow_status = 'PENDING'`, `filter_reason`.
  - Розраховується гіпотетичний розмір ставки (за критерієм Келлі від початкового банку), `profit_uah = 0.00`.
  - Функція повертає `False`, сигналізуючи пайплайну не додавати подію до оперативного зведення Telegram.
- У `settle_and_report`:
  - До вибірки розрахунку додаються події з `status = 'FILTERED' AND shadow_status = 'PENDING'`.
  - Завершений матч розраховується через `eval_outcome`, фіксуючи `shadow_status` (`WON`/`LOST`/`VOID`), `shadow_profit_uah` та `match_score`.
  - Поле `profit_uah` залишається `0.00`, баланси леджера та віртуального банку не змінюються.

### 3.3. Аналітика (`statmonitor/analytics.py`)
- `calculate_counterfactual_audit(bets)`:
  - Група A (Active, Confidence $\ge 7$): ROI, Win Rate, PnL, Turnover.
  - Група B (Shadow, Confidence $< 7$ або Skip): гіпотетичний ROI, Win Rate, PnL, Turnover.
  - Комбінована модель (A + B, без фільтрації ШІ): що було б за відсутності ШІ-фільтра.
  - Alpha ШІ: $\Delta \text{ROI} = \text{ROI}_{\text{Active}} - \text{ROI}_{\text{Shadow}}$, сума збереженого капіталу (`-shadow_profit`).
- `calculate_confidence_calibration(bets)`:
  - Розбиття на бакети: `1-4`, `5-6`, `7-8`, `9-10`.
  - Метрики для кожного бакета: Кількість ставок, Win Rate %, Avg CLV %, ROI %, Brier Score.

### 3.4. Дашборд (`dashboard.py`)
- На вкладці `🧠 AI-аналітика Gemini`:
  - Інтерактивний блок метрик контрфактичного аудиту (Active ROI vs Shadow ROI, збережений капітал, Alpha $\Delta\text{ROI}$).
  - Калібраційна таблиця за бакетами Confidence Score.
  - Експандер «🕵️ Реєстр Shadow-ставок (Counterfactual Log)» із фільтрами та детальними статусами.
