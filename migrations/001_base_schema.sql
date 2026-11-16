-- ==============================================================================
-- 001_base_schema.sql
-- Базова схема таблиць StatMonitor (PostgreSQL / Supabase)
-- ==============================================================================

-- 1. Таблиця подій (матчів)
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    match_name TEXT NOT NULL,
    commence_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Таблиця часових рядів котирувань
CREATE TABLE IF NOT EXISTS odds_history (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market_key TEXT NOT NULL,
    outcome_name TEXT NOT NULL,
    point NUMERIC(6,2),
    price NUMERIC(6,3) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Таблиця віртуальних ставок (Paper Trading Bankroll)
CREATE TABLE IF NOT EXISTS paper_bets (
    id SERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    sport TEXT NOT NULL,
    match_name TEXT NOT NULL,
    commence_time TIMESTAMPTZ NOT NULL,
    pick_label TEXT NOT NULL,
    odds NUMERIC(6,3) NOT NULL,
    stake_uah NUMERIC(10,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    match_score TEXT,
    profit_uah NUMERIC(10,2) NOT NULL DEFAULT 0.00,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    settled_at TIMESTAMPTZ
);

-- 4. Таблиця збереження AI-аналітики Gemini
CREATE TABLE IF NOT EXISTS ai_match_analysis (
    event_id TEXT PRIMARY KEY,
    verdict_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Таблиця фіксації щоденних звітів
CREATE TABLE IF NOT EXISTS paper_daily_reports (
    report_date DATE PRIMARY KEY,
    sent_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Таблиця динамічного планувальника (SPEC-08)
CREATE TABLE IF NOT EXISTS scheduler_plan (
    id SERIAL PRIMARY KEY,
    target_time TIMESTAMPTZ NOT NULL,
    trigger_type TEXT NOT NULL,
    event_ids TEXT[] DEFAULT '{}',
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Таблиця контролю пульсу системи (SPEC-09 Watchdog)
CREATE TABLE IF NOT EXISTS system_heartbeat (
    service_name TEXT PRIMARY KEY,
    last_ping_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_status TEXT NOT NULL DEFAULT 'OK',
    last_duration_sec NUMERIC(8,2) DEFAULT 0.0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
