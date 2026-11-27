-- 019_schema_sync_and_hotfixes.sql
-- Синхронізація всіх службових таблиць та перенесення одноразових фіксів даних із рантайм-коду

-- 1. Журнал системних помилок (SPEC-43)
CREATE TABLE IF NOT EXISTS system_errors (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'ERROR',
    error_code TEXT,
    message TEXT NOT NULL,
    details JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_system_errors_occurred ON system_errors (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_errors_unresolved ON system_errors (occurred_at DESC) WHERE resolved_at IS NULL;

-- 2. Налаштування авто-стейкінгу SX Bet
CREATE TABLE IF NOT EXISTS sx_settings (
    key TEXT PRIMARY KEY,
    value_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Колонка реального профіту
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_profit_uah NUMERIC(10, 2);

-- 4. Одноразове округлення реальних ставок до цілих гривень
UPDATE paper_bets
SET real_stake_uah = ROUND(real_stake_uah)
WHERE is_real_bet = TRUE
  AND real_stake_uah IS NOT NULL
  AND real_stake_uah != ROUND(real_stake_uah);
