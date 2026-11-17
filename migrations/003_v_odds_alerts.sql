-- ==============================================================================
-- 003_v_odds_alerts.sql
-- Оптимізоване аналітичне представлення v_odds_alerts (SPEC-14)
-- ==============================================================================

DROP VIEW IF EXISTS v_odds_alerts CASCADE;
CREATE OR REPLACE VIEW v_odds_alerts AS
WITH ranked_odds AS (
    SELECT 
        oh.event_id,
        oh.bookmaker,
        oh.market_key,
        oh.outcome_name,
        oh.point,
        oh.price,
        oh.recorded_at,
        ROW_NUMBER() OVER (
            PARTITION BY oh.event_id, oh.bookmaker, oh.market_key, oh.outcome_name, COALESCE(oh.point, -999.0)
            ORDER BY oh.recorded_at ASC
        ) AS rn_first,
        ROW_NUMBER() OVER (
            PARTITION BY oh.event_id, oh.bookmaker, oh.market_key, oh.outcome_name, COALESCE(oh.point, -999.0)
            ORDER BY oh.recorded_at DESC
        ) AS rn_last
    FROM odds_history oh
    WHERE oh.recorded_at >= NOW() - INTERVAL '48 hours'
),
bounds AS (
    SELECT 
        f.event_id,
        f.bookmaker,
        f.market_key,
        f.outcome_name,
        f.point,
        f.price AS start_odds,
        f.recorded_at AS start_time,
        l.price AS current_odds,
        l.recorded_at AS last_time
    FROM ranked_odds f
    JOIN ranked_odds l ON f.event_id = l.event_id 
                      AND f.bookmaker = l.bookmaker 
                      AND f.market_key = l.market_key 
                      AND f.outcome_name = l.outcome_name 
                      AND COALESCE(f.point, -999.0) = COALESCE(l.point, -999.0)
                      AND l.rn_last = 1
    WHERE f.rn_first = 1
)
SELECT 
    b.event_id,
    e.sport,
    e.match_name,
    e.commence_time,
    b.bookmaker,
    b.market_key,
    b.outcome_name,
    b.point,
    b.start_odds,
    b.current_odds,
    ROUND(((b.current_odds - b.start_odds) / b.start_odds) * 100.0, 2) AS drop_pct,
    b.start_time,
    b.last_time
FROM bounds b
JOIN events e ON b.event_id = e.id
WHERE b.current_odds BETWEEN 1.40 AND 4.00
  AND b.current_odds < b.start_odds
  AND ROUND(((b.current_odds - b.start_odds) / b.start_odds) * 100.0, 2) <= -3.0
  AND e.commence_time >= NOW() - INTERVAL '2 hours'
ORDER BY drop_pct ASC;
