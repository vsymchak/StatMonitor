-- 006_paper_bets_kelly_pct.sql: Додавання відсотка стейкінгу за критерієм Келлі до ставок
ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS kelly_pct NUMERIC(5,2);
