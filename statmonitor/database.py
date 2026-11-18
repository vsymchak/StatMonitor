import psycopg2
from statmonitor.config import SUPABASE_DB_URL

def get_db(db_url=None):
    url = db_url or SUPABASE_DB_URL
    if not url:
        return None
    try:
        return psycopg2.connect(url, connect_timeout=10)
    except Exception as e:
        print(f"Помилка підключення до БД: {e}")
        return None

def get_cols(cur, tbl):
    try:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s;",
            (tbl,)
        )
        return {r[0] for r in cur.fetchall()}
    except Exception:
        return set()

def pick(cols, candidates, default=None):
    for c in candidates:
        if c in cols:
            return c
    return default

def pick_v(d, candidates, default=None):
    for n in candidates:
        if n in d and d[n] is not None:
            return d[n]
    return default

def ensure_tables(cur, conn):
    applied = False
    if SUPABASE_DB_URL:
        try:
            from migrate import run_migrations
            res = run_migrations(db_url=SUPABASE_DB_URL)
            if res is not None:
                applied = True
        except Exception as e:
            print(f"Migrations run notice: {e}")

    if not applied:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_match_analysis (
                event_id TEXT PRIMARY KEY, verdict_text TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS paper_bets (
                id SERIAL PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, sport TEXT NOT NULL,
                match_name TEXT NOT NULL, commence_time TIMESTAMPTZ NOT NULL, pick_label TEXT NOT NULL,
                odds NUMERIC(6,3) NOT NULL, stake_uah NUMERIC(10,2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING', match_score TEXT,
                profit_uah NUMERIC(10,2) NOT NULL DEFAULT 0.00,
                created_at TIMESTAMPTZ DEFAULT NOW(), settled_at TIMESTAMPTZ,
                kelly_pct NUMERIC(5,2)
            );
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS kelly_pct NUMERIC(5,2);
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS closing_odds NUMERIC(6,3);
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS clv_pct NUMERIC(6,2);
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS beat_closing_line BOOLEAN;
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS closing_recorded_at TIMESTAMPTZ;
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS confidence_score INTEGER;
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS risk_level TEXT;
            ALTER TABLE ai_match_analysis ADD COLUMN IF NOT EXISTS confidence_score INTEGER;
            ALTER TABLE ai_match_analysis ADD COLUMN IF NOT EXISTS risk_level TEXT;
            CREATE TABLE IF NOT EXISTS paper_daily_reports (
                report_date DATE PRIMARY KEY, sent_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS weekly_digests (
                week_key TEXT PRIMARY KEY, sent_at TIMESTAMPTZ DEFAULT NOW(), metrics_json JSONB, status TEXT DEFAULT 'SENT'
            );
        """)
        conn.commit()
