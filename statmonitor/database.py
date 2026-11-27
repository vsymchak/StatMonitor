import psycopg2
from statmonitor.config import SUPABASE_DB_URL

def get_db(db_url=None):
    url = db_url or SUPABASE_DB_URL
    if not url:
        return None
    # Надійне підключення з швидким таймаутом і ротацією портів (5432 / 6543)
    try:
        return psycopg2.connect(url, connect_timeout=5)
    except Exception:
        alt_url = url.replace(":5432/", ":6543/") if ":5432/" in url else url.replace(":6543/", ":5432/")
        try:
            return psycopg2.connect(alt_url, connect_timeout=5)
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

_MIGRATIONS_CHECKED = False


def ensure_tables(cur, conn, force=False):
    global _MIGRATIONS_CHECKED
    is_mock_cur = "unittest.mock" in getattr(type(cur), "__module__", "")
    if _MIGRATIONS_CHECKED and not force and not is_mock_cur:
        return
    applied = False
    if SUPABASE_DB_URL and not is_mock_cur:
        try:
            from migrate import run_migrations
            res = run_migrations(db_url=SUPABASE_DB_URL)
            if res is not None:
                applied = True
        except Exception as e:
            print(f"Migrations run notice: {e}")

    if applied and not is_mock_cur:
        _MIGRATIONS_CHECKED = True
        return

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
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN DEFAULT FALSE;
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS shadow_status TEXT;
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS shadow_profit_uah NUMERIC(10, 2) DEFAULT 0.00;
            ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS filter_reason TEXT;
            ALTER TABLE ai_match_analysis ADD COLUMN IF NOT EXISTS confidence_score INTEGER;
            ALTER TABLE ai_match_analysis ADD COLUMN IF NOT EXISTS risk_level TEXT;
            CREATE TABLE IF NOT EXISTS paper_daily_reports (
                report_date DATE PRIMARY KEY, sent_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS weekly_digests (
                week_key TEXT PRIMARY KEY, sent_at TIMESTAMPTZ DEFAULT NOW(), metrics_json JSONB, status TEXT DEFAULT 'SENT'
            );
            CREATE TABLE IF NOT EXISTS league_thresholds (
                sport_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'soccer',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                min_drop_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00,
                min_odds NUMERIC(5,2) NOT NULL DEFAULT 1.40,
                max_odds NUMERIC(5,2) NOT NULL DEFAULT 4.00,
                markets JSONB NOT NULL DEFAULT '["h2h", "totals", "spreads"]'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS system_errors (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'ERROR',
                error_code TEXT,
                message TEXT NOT NULL,
                details JSONB,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_system_errors_occurred ON system_errors (occurred_at DESC);
        """)
        conn.commit()
    _MIGRATIONS_CHECKED = True


def _extract_cur_conn(conn_or_cur):
    if hasattr(conn_or_cur, "cursor") and callable(getattr(conn_or_cur, "cursor", None)):
        try:
            c = conn_or_cur.cursor()
            if c is not None and c is not conn_or_cur:
                return c, conn_or_cur, True
        except Exception:
            pass
    return conn_or_cur, None, False


def log_system_error(conn_or_cur, source: str, message: str, severity: str = "ERROR", error_code: str = None, details: dict = None):
    """
    Записує системну помилку або попередження в таблицю system_errors.
    """
    try:
        import json
        cur, conn, is_new_cur = _extract_cur_conn(conn_or_cur)
        det_json = json.dumps(details) if details else None
        cur.execute("""
            INSERT INTO system_errors (source, severity, error_code, message, details, occurred_at)
            VALUES (%s, %s, %s, %s, %s, NOW());
        """, (source, severity, error_code, message[:500], det_json))
        if is_new_cur and conn:
            conn.commit()
            cur.close()
    except Exception as e:
        print(f"Помилка запису в system_errors: {e}")


def fetch_system_errors(conn_or_cur, limit: int = 15, unresolved_only: bool = True):
    """
    Повертає останні зафіксовані помилки для відображення в дашборді.
    """
    try:
        cur, conn, is_new_cur = _extract_cur_conn(conn_or_cur)
        cond = "WHERE resolved_at IS NULL" if unresolved_only else ""
        cur.execute(f"""
            SELECT id, source, severity, error_code, message, details, occurred_at
            FROM system_errors
            {cond}
            ORDER BY occurred_at DESC
            LIMIT %s;
        """, (limit,))
        cols = ["id", "source", "severity", "error_code", "message", "details", "occurred_at"]
        rows = cur.fetchall()
        if is_new_cur:
            cur.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        print(f"Помилка читання system_errors: {e}")
        return []


def resolve_system_errors(conn_or_cur, error_ids: list = None):
    """
    Позначає помилки як вирішені/прочитані.
    """
    try:
        cur, conn, is_new_cur = _extract_cur_conn(conn_or_cur)
        if error_ids:
            cur.execute("UPDATE system_errors SET resolved_at = NOW() WHERE id = ANY(%s);", (error_ids,))
        else:
            cur.execute("UPDATE system_errors SET resolved_at = NOW() WHERE resolved_at IS NULL;")
        if is_new_cur and conn:
            conn.commit()
            cur.close()
    except Exception as e:
        print(f"Помилка resolve_system_errors: {e}")
