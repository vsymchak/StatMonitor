-- ==============================================================================
-- 005_nullable_legacy_odds_columns.sql
-- Сумісність та зняття обмежень на застарілі колонки odds_history (SPEC-18)
-- ==============================================================================

ALTER TABLE odds_history ALTER COLUMN outcome DROP NOT NULL;
ALTER TABLE odds_history ALTER COLUMN odds_value DROP NOT NULL;
ALTER TABLE odds_history ADD COLUMN IF NOT EXISTS market_key TEXT DEFAULT 'h2h';
ALTER TABLE odds_history ADD COLUMN IF NOT EXISTS point NUMERIC(6,2);
ALTER TABLE odds_history ADD COLUMN IF NOT EXISTS price NUMERIC(6,3);
ALTER TABLE odds_history ADD COLUMN IF NOT EXISTS outcome_name TEXT;
