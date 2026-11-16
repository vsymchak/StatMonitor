-- ==============================================================================
-- 004_sports_poll_log.sql
-- Таблиця для розумного Rate-Limiter (SPEC-10) та обліку опитування ліг
-- ==============================================================================

CREATE TABLE IF NOT EXISTS sports_poll_log (
    sport TEXT PRIMARY KEY,
    last_polled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    poll_count INT NOT NULL DEFAULT 1,
    tier TEXT NOT NULL DEFAULT 'COLD'
);

CREATE INDEX IF NOT EXISTS idx_poll_log_tier ON sports_poll_log (tier, last_polled_at);
