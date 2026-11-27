-- 020_ledger_integrity.sql
-- Цілісність фінансових леджерів, feature-flags (kill-switch), аудит розрахунків та мапінг команд SX Bet

-- 1. Системні прапорці / Kill-switch для авто-трейдингу та зовнішніх інтеграцій
CREATE TABLE IF NOT EXISTS system_flags (
    key TEXT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO system_flags (key, enabled, reason)
VALUES
    ('sx_autostake_enabled', TRUE, 'Автоматичний стейкінг SX Bet із USDC risk guardrails'),
    ('trading_enabled', TRUE, 'Глобальний kill-switch торгівлі')
ON CONFLICT (key) DO NOTHING;

-- 2. Журнал аудиту розрахунків і ручних правок ставок
CREATE TABLE IF NOT EXISTS bet_audit_log (
    id SERIAL PRIMARY KEY,
    bet_id INTEGER REFERENCES paper_bets(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    old_score TEXT,
    new_score TEXT,
    actor TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bet_audit_log_bet_id ON bet_audit_log (bet_id, created_at DESC);

-- 3. Довідник канонічних аліасів команд (SX Bet / Odds API / ESPN)
CREATE TABLE IF NOT EXISTS team_aliases (
    id SERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    alias_name TEXT NOT NULL,
    sport TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (alias_name, sport)
);
CREATE INDEX IF NOT EXISTS idx_team_aliases_lookup ON team_aliases (LOWER(alias_name));

-- 4. Черга запитів запуску пайплайну / адмін-команд
CREATE TABLE IF NOT EXISTS pipeline_requests (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    force BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pipeline_requests_status ON pipeline_requests (status, requested_at DESC);

-- 5. Ідемпотентний захист реального леджера від подвійного зарахування BET_RESULT
-- із підтримкою сторнування (REVERSAL + is_superseded = TRUE)
ALTER TABLE real_bankroll_ledger
    ADD COLUMN IF NOT EXISTS is_superseded BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_real_ledger_active_bet_result
    ON real_bankroll_ledger (bet_id)
    WHERE bet_id IS NOT NULL
      AND transaction_type = 'BET_RESULT'
      AND is_superseded = FALSE;
