-- SPEC-25: Interactive League Thresholds Management
-- Таблиця динамічної конфігурації порогів ліг та ринків

CREATE TABLE IF NOT EXISTS league_thresholds (
    sport_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'soccer',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    min_drop_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00,
    min_odds NUMERIC(5,2) NOT NULL DEFAULT 1.40,
    max_odds NUMERIC(5,2) NOT NULL DEFAULT 4.00,
    markets JSONB NOT NULL DEFAULT '["h2h", "totals", "spreads"]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_league_thresholds_enabled ON league_thresholds(enabled);
