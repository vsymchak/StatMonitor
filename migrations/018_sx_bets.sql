-- 018_sx_bets.sql
-- Реєстр ставок та транзакцій децентралізованої біржі SX Bet (Крок 40 Web3 Auto-Staking)

CREATE TABLE IF NOT EXISTS sx_bets (
    id SERIAL PRIMARY KEY,
    order_id TEXT UNIQUE NOT NULL,
    market_hash TEXT NOT NULL,
    event_id TEXT,
    sport_label TEXT,
    event_name TEXT NOT NULL,
    market_name TEXT,
    bet_side TEXT,
    stake_usdc NUMERIC(10, 2) NOT NULL,
    odds NUMERIC(6, 2) NOT NULL,
    potential_payout_usdc NUMERIC(10, 2),
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING (UNSETTLED) / WON / LOST / VOID / CANCELLED
    profit_usdc NUMERIC(10, 2) DEFAULT 0.0,
    paper_bet_id INTEGER REFERENCES paper_bets(id) ON DELETE SET NULL,
    game_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMPTZ,
    raw_order JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_sx_bets_status ON sx_bets (status);
CREATE INDEX IF NOT EXISTS idx_sx_bets_created_at ON sx_bets (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sx_bets_paper_bet_id ON sx_bets (paper_bet_id);

CREATE TABLE IF NOT EXISTS sx_transactions (
    id SERIAL PRIMARY KEY,
    tx_hash TEXT UNIQUE,
    type TEXT NOT NULL,  -- DEPOSIT, WITHDRAWAL, BET_PLACED, BET_WON, BET_REFUND
    amount_usdc NUMERIC(10, 2) NOT NULL,
    balance_after_usdc NUMERIC(10, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_sx_transactions_created_at ON sx_transactions (created_at DESC);
