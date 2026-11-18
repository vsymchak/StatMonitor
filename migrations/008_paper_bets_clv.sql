-- 008_paper_bets_clv.sql: Додавання Closing Line Value (CLV) до ставок (SPEC-20)
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS closing_odds NUMERIC(6,3);
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS clv_pct NUMERIC(6,2);
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS beat_closing_line BOOLEAN;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS closing_recorded_at TIMESTAMPTZ;
