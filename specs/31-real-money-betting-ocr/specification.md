# SPEC-31: Real Money Betting, Bankroll Tracking & Gemini Bet Slip OCR

> **Статус**: 🟩 Shipped  
> **Дата релізу**: 19.11.2026  
> **Гілка / Коміт**: `main` (`04efbcf`)  
> **Покриття тестами**: `test_real_bankroll.py`, `test_slip_ocr.py` (100% pass)

---

## 1. Мета та Контекст
Платформа StatMonitor працює у режимі віртуального трейдингу (Paper Trading) зі стартовим банком 10 000 грн, що дозволяє безперервно верифікувати прибутковість алгоритмів, дробовий критерій Келлі ($0.25 \times \text{Kelly}$), показники CLV (Closing Line Value) та ROI по турнірах.

Стратегічним кроком еволюції системи є **паралельний облік гри на реальні гроші (Real Money Mode)**:
1. Облік реального капіталу в гривнях (UAH), що формується виключно реальними депозитами користувача (без фіктивних стартових сум).
2. Пряма відмітка ставок, які укладені в букмекерській конторі, безпосередньо в таблиці активних ставок на Dashboard за допомогою інтуїтивного прапорця.
3. Автоматизація верифікації та внесення реальних ставок через завантаження фотографії / скріншота купона ставки з БК та його інтелектуального розпізнавання через **Gemini Multimodal API (Vision)**.

---

## 2. Реалізовані Можливості (Core Features)

### 2.1. Подвійний банкрол (Dual Bankroll: Paper & Real)
- **Paper Bankroll**: продовжує рахувати всі ставки (стартовий банк 10 000 грн) для бектестингу, безперервного аналізу стратегії та моніторингу алгоритмів.
- **Real Bankroll**: окремий облік капіталу в гривнях, що ведеться через леджер транзакцій `real_bankroll_ledger`:
  - **Початковий баланс**: починається з `0.00 ₴` і формується реальними депозитами (`DEPOSIT`).
  - **Транзакції каси**:
    - `DEPOSIT` — внесення коштів на баланс.
    - `WITHDRAWAL` — виведення виграшу з контори.
    - `ADJUSTMENT` — пряме коригування балансу (синхронізація з касою БК).
    - `BET_RESULT` — автоматичний розрахунок виграшу/програшу ставки при закритті матчу (`WON`, `LOST`, `VOID`).
  - **Метрики реального банку**: Real Balance, Total Deposits, Real Net Profit, Real Turnover, Real ROI % та Real Win Rate.
  - **Банер стану**: лаконічний зелений банер у верхній частині дашборду, що показує актуальний стан реальних коштів.

### 2.2. Інлайн-перемикач реальних ставок в один клік (Admin Inline Toggle)
- У таблиці **`⏳ Активні ставки в грі (Pending)`** для адміністратора впроваджено інтерактивну колонку **`🟢 Real`** (через `st.data_editor` з `CheckboxColumn`):
  - Адміністратор відмічає чекбокс навпроти потрібного матчу — ставка миттєво позначається в БД (`is_real_bet = TRUE`) і прив'язується до реального банкролу.
  - Зняття відмітки повертає ставку в статус віртуальної.
  - **Усі ставки завжди паралельно ведуться в Paper-трейдингу** (ставка не замінюється, а позначається додатковим прапорцем).
  - Усі інші колонки таблиці захищені від випадкових правок (`disabled`).
- Для звичайних відвідувачів (гостей) колонка відображається в режимі лише для читання зі значками `🟢 Real` / `⚪ Paper`.
- Фокус на одній букмекерській конторі: зайві селектори та колонки БК вилучені з інтерфейсу для максимальної чистоти та швидкості взаємодії.

### 2.3. AI Bet Slip OCR через Gemini Multimodal Vision
- **Інтерфейс завантаження**:
  - У кабінеті адміністратора Streamlit додано блок «🧾 Завантаження та OCR купона БК (Gemini Vision)» з підтримкою файлів `.jpg`, `.jpeg`, `.png`, `.webp`.
- **Розпізнавання через Gemini Vision**:
  - Моделі: `gemini-2.5-flash`, `gemini-2.5-pro` (fallback на `gemini-1.5-flash`).
  - Зображення передається в API у форматі Base64 разом зі структурованим JSON-промтом.
  - Gemini витягує:
    1. Назву матчу / команд / учасників (`match_name`).
    2. Вид спорту (`sport`).
    3. Тип маркету та вибір (`pick_label`).
    4. Точний коефіцієнт (`odds`).
    5. Суму ставки (`stake_uah`).
    6. Номер квитанції / ID купона (`ticket_id`).
    7. Потенційний виграш (`potential_win_uah`).
- **Алгоритм зіставлення (Matching Engine)**:
  - Модуль `match_slip_with_pending_bets` автоматично шукає відповідний матч серед активних (`PENDING`) ставок за токенами імен команд, маркетом та близькістю коефіцієнта.
  - Після підтвердження адміністратора функція `apply_slip_to_bet` маркує ставку як реальну (`is_real_bet = TRUE`), зберігає скріншот у `slips/` та записує розпізнані метадані в `slip_meta`.

### 2.4. Автоматичний та ручний розрахунок результатів
- При авторозрахунку матчу за фінальним рахунком (`WON`, `LOST`, `VOID`) викликається `settle_real_bet_in_ledger`, що автоматично вносить запис `BET_RESULT` у леджер реального банку.
- Для адміністратора в дашборді реалізовано модальний блок **ручного розрахунку ставки (Manual Settle)** з вибором результату та зазначенням рахунку.

---

## 3. Схема Даних (Data Schema)

Міграція `migrations/014_real_money_mode_ocr.sql`:
```sql
-- 1. Розширення полів реальних ставок у paper_bets
ALTER TABLE paper_bets 
ADD COLUMN IF NOT EXISTS is_real_bet BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS real_stake_uah NUMERIC(10, 2),
ADD COLUMN IF NOT EXISTS real_odds NUMERIC(6, 3),
ADD COLUMN IF NOT EXISTS bookmaker_name TEXT,
ADD COLUMN IF NOT EXISTS slip_image_path TEXT,
ADD COLUMN IF NOT EXISTS slip_meta JSONB;

-- 2. Таблиця фінансового леджера реального банку
CREATE TABLE IF NOT EXISTS real_bankroll_ledger (
    id SERIAL PRIMARY KEY,
    transaction_type TEXT NOT NULL, -- 'DEPOSIT', 'WITHDRAWAL', 'ADJUSTMENT', 'BET_RESULT'
    amount_uah NUMERIC(10, 2) NOT NULL,
    balance_after_uah NUMERIC(10, 2) NOT NULL,
    description TEXT,
    bet_id INTEGER REFERENCES paper_bets(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_bets_is_real ON paper_bets (is_real_bet);
CREATE INDEX IF NOT EXISTS idx_real_bankroll_created ON real_bankroll_ledger (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_real_bankroll_type ON real_bankroll_ledger (transaction_type);
```

---

## 4. Архітектура Модулів

```
statmonitor/
├── real_bankroll.py     # Логіка леджера, транзакцій каси, розрахунку балансу та реальних ставок
└── slip_ocr.py          # Gemini Multimodal Vision OCR, нормалізація квитанцій та зіставлення з PENDING ставками
```

---

## 5. Тестування та Верифікація
- `test_real_bankroll.py`:
  - `test_ensure_real_bankroll_tables`
  - `test_get_real_bankroll_summary_defaults` (перевірка старту з 0.00 ₴)
  - `test_get_real_bankroll_summary_with_data` (депозити, ROI, оборот)
  - `test_record_real_transaction_deposit`
  - `test_record_real_transaction_withdrawal`
  - `test_record_real_transaction_adjustment`
  - `test_record_real_transaction_bet_result`
  - `test_toggle_real_bet_to_real`
  - `test_toggle_real_bet_to_paper`
  - `test_settle_real_bet_in_ledger_success`
  - `test_settle_real_bet_in_ledger_not_real`
  - `test_settle_real_bet_in_ledger_duplicate`
- `test_slip_ocr.py`:
  - `test_parse_bet_slip_with_gemini_missing_key`
  - `test_parse_bet_slip_with_gemini_empty_bytes`
  - `test_parse_bet_slip_with_gemini_mocked_success`
  - `test_match_slip_with_pending_bets_exact`
  - `test_match_slip_with_pending_bets_fuzzy`
  - `test_match_slip_with_pending_bets_no_match`
  - `test_apply_slip_to_bet`
- Повний набір тестів: **149 unit-тестів**, 100% успішне виконання.
