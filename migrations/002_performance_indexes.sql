-- ==============================================================================
-- 002_performance_indexes.sql
-- Цільові B-Tree індекси для оптимізації аналітики та вибірок (SPEC-14)
-- ==============================================================================

-- 1. Індекси для таблиці odds_history (найбільш навантажена таблиця)
-- Прискорює вибірку історії для побудови графіків у пам'яті
CREATE INDEX IF NOT EXISTS idx_odds_history_event_time 
    ON odds_history (event_id, recorded_at);

-- Прискорює точковий пошук історії за маркетом та виходом
CREATE INDEX IF NOT EXISTS idx_odds_history_lookup 
    ON odds_history (event_id, bookmaker, market_key, outcome_name, recorded_at);

-- Прискорює 4-денне очищення застарілих записів (rolling retention)
CREATE INDEX IF NOT EXISTS idx_odds_history_time 
    ON odds_history (recorded_at);

-- 2. Індекси для таблиці подій events
-- Прискорює вибірку матчів на найближчі 24-36 годин для планувальника
CREATE INDEX IF NOT EXISTS idx_events_commence 
    ON events (commence_time);

-- 3. Індекси для ставок paper_bets
-- Швидкий пошук активних ставок у грі (PENDING)
CREATE INDEX IF NOT EXISTS idx_paper_bets_pending 
    ON paper_bets (status, commence_time);

CREATE INDEX IF NOT EXISTS idx_paper_bets_event 
    ON paper_bets (event_id);

-- 4. Індекс для планувальника scheduler_plan
CREATE INDEX IF NOT EXISTS idx_scheduler_target 
    ON scheduler_plan (target_time, status);

-- 5. Індекс для AI-вердиктів
CREATE INDEX IF NOT EXISTS idx_ai_match_created 
    ON ai_match_analysis (created_at DESC);
