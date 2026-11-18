-- ==============================================================================
-- 009_weekly_digests.sql
-- Таблиця обліку щотижневих графічних дайджестів у Telegram (SPEC-26)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS weekly_digests (
    week_key TEXT PRIMARY KEY,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    metrics_json JSONB,
    status TEXT DEFAULT 'SENT'
);

CREATE INDEX IF NOT EXISTS idx_weekly_digests_sent_at ON weekly_digests(sent_at DESC);
