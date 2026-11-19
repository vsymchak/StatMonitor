-- 012_clean_multi_picks.sql
-- SPEC-34: Очищення подвійних / альтернативних маркетів з 'або' / 'чи' / '/' у paper_bets

UPDATE paper_bets 
SET pick_label = TRIM(SPLIT_PART(pick_label, ' або ', 1))
WHERE pick_label ILIKE '% або %';

UPDATE paper_bets 
SET pick_label = TRIM(SPLIT_PART(pick_label, ' чи ', 1))
WHERE pick_label ILIKE '% чи %';

-- Специфічне виправлення для ставки #46 (Ф2 (+7.5) замість 'Ф2 (+7.5) або П2')
UPDATE paper_bets 
SET pick_label = 'Ф2 (+7.5)' 
WHERE id = 46 AND pick_label LIKE '%Ф2 (+7.5)%';
