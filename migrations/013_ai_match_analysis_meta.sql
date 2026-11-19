-- 013_ai_match_analysis_meta.sql
-- SPEC-35: Збереження match_name та sport безпосередньо в ai_match_analysis для повних заголовків

ALTER TABLE ai_match_analysis ADD COLUMN IF NOT EXISTS match_name TEXT;
ALTER TABLE ai_match_analysis ADD COLUMN IF NOT EXISTS sport TEXT;

-- Збагачуємо існуючі записи з таблиці events
UPDATE ai_match_analysis a
SET match_name = COALESCE(NULLIF(e.match_name, ''), e.home_team || ' - ' || e.away_team),
    sport = e.sport
FROM events e
WHERE a.event_id = e.id AND (a.match_name IS NULL OR a.match_name = 'nan' OR a.match_name = '');

-- Збагачуємо з таблиці paper_bets (якщо є)
UPDATE ai_match_analysis a
SET match_name = b.match_name,
    sport = b.sport
FROM paper_bets b
WHERE a.event_id = b.event_id AND (a.match_name IS NULL OR a.match_name = 'nan' OR a.match_name = '');
