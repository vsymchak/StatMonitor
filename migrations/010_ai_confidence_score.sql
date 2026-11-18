-- SPEC-21: AI Confidence Score & Value Filtering
-- Додавання оцінки впевненості нейромережі Gemini (1-10) та рівня ризику (Low / Medium / High)

ALTER TABLE paper_bets
ADD COLUMN IF NOT EXISTS confidence_score INTEGER,
ADD COLUMN IF NOT EXISTS risk_level TEXT;

ALTER TABLE ai_match_analysis
ADD COLUMN IF NOT EXISTS confidence_score INTEGER,
ADD COLUMN IF NOT EXISTS risk_level TEXT;
