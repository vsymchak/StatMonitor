-- 016_paper_bets_walkaway_odds.sql
-- SPEC-37: Walkaway Odds (мінімальний граничний коефіцієнт беззбитковості)
-- Фіксує ціновий поріг входу в ставку для запобігання втраті +EV через ковзання (slippage)

ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS walkaway_odds NUMERIC(6,2);
