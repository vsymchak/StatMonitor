-- 014_real_money_mode_ocr.sql
-- SPEC-31: Гра на реальні гроші (Real Money Mode), облік реального банку та метадані купонів БК (Bet Slip OCR)

-- 1. Додавання полів реальних ставок у paper_bets
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS is_real_bet BOOLEAN DEFAULT FALSE;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_stake_uah NUMERIC(10, 2);
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_odds NUMERIC(6, 3);
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS bookmaker_name TEXT;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS slip_image_path TEXT;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS slip_meta JSONB;

CREATE INDEX IF NOT EXISTS idx_paper_bets_is_real ON paper_bets (is_real_bet);

-- 2. Таблиця обліку та журналу транзакцій реального банкролу (Real Bankroll Ledger)
CREATE TABLE IF NOT EXISTS real_bankroll_ledger (
    id SERIAL PRIMARY KEY,
    transaction_type TEXT NOT NULL, -- 'INITIAL', 'DEPOSIT', 'WITHDRAWAL', 'BET_RESULT', 'ADJUSTMENT'
    amount_uah NUMERIC(10, 2) NOT NULL,
    balance_after_uah NUMERIC(10, 2) NOT NULL,
    bet_id INTEGER REFERENCES paper_bets(id) ON DELETE SET NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_real_bankroll_created ON real_bankroll_ledger (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_real_bankroll_type ON real_bankroll_ledger (transaction_type);

-- 3. Ініціалізація початкового реального банку за замовчуванням (10,000 грн), якщо таблиця порожня
INSERT INTO real_bankroll_ledger (transaction_type, amount_uah, balance_after_uah, description)
SELECT 'INITIAL', 10000.00, 10000.00, 'Початковий реальний банк'
WHERE NOT EXISTS (SELECT 1 FROM real_bankroll_ledger);
