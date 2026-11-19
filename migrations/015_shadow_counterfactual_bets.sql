-- 015_shadow_counterfactual_bets.sql: Додавання полів для Shadow-ставок та Counterfactual AI Audit (SPEC-35)
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN DEFAULT FALSE;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS shadow_status TEXT;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS shadow_profit_uah NUMERIC(10, 2) DEFAULT 0.00;
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS filter_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_paper_bets_is_shadow ON paper_bets (is_shadow);
CREATE INDEX IF NOT EXISTS idx_paper_bets_shadow_status ON paper_bets (shadow_status);
