import os
import json
from pathlib import Path

def _load_default_leagues():
    base_dir = Path(__file__).resolve().parent.parent
    default_file = base_dir / "config" / "leagues.json"
    if default_file.exists():
        try:
            with open(default_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and "leagues" in d and len(d["leagues"]) > 0:
                    return d
        except Exception:
            pass
    return {
        "version": "2.0",
        "leagues": [
            {"key": "soccer_epl", "title": "Англія (Прем'єр-ліга / АПЛ)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_spain_la_liga", "title": "Іспанія (Ла Ліга)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_italy_serie_a", "title": "Італія (Серія А)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_germany_bundesliga", "title": "Німеччина (Бундесліга)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_france_ligue_one", "title": "Франція (Ліга 1)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_ukraine_premier_league", "title": "Україна (УПЛ)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_poland_ekstraklasa", "title": "Польща (Екстракласа)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_uefa_champs_league", "title": "Ліга Чемпіонів УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_uefa_europa_league", "title": "Ліга Європи УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_uefa_conference_league", "title": "Ліга Конференцій УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "soccer_uefa_nations_league", "title": "Ліга Націй УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads", "btts"]},
            {"key": "basketball_nba", "title": "США (NBA)", "category": "basketball", "enabled": True, "min_drop_pct": 4.0, "min_odds": 1.35, "max_odds": 4.20, "markets": ["h2h", "totals", "spreads"]},
            {"key": "tennis_atp", "title": "Теніс (ATP Tour)", "category": "tennis", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.35, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "tennis_wta", "title": "Теніс (WTA Tour)", "category": "tennis", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.35, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "tennis_davis_cup", "title": "Теніс (Кубок Девіса)", "category": "tennis", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.35, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        ]
    }

DEFAULT_LEAGUES_CONFIG = _load_default_leagues()

def resolve_config_path(config_path=None):
    """Визначає повний шлях до файлу конфігурації ліг."""
    if config_path:
        return Path(config_path)
    env_path = os.environ.get("LEAGUES_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    
    # Шукаємо від поточної директорії або від кореня проєкту
    base_dir = Path(__file__).resolve().parent.parent
    default_file = base_dir / "config" / "leagues.json"
    return default_file

def fetch_db_leagues(cur):
    """
    Отримує конфігурацію ліг із таблиці league_thresholds.
    Повертає список словників або None, якщо таблиці немає або вона порожня.
    """
    if cur is None:
        return None
    try:
        cur.execute("""
            SELECT sport_key, title, category, enabled, min_drop_pct, min_odds, max_odds, markets
            FROM league_thresholds
            ORDER BY category ASC, title ASC;
        """)
        rows = cur.fetchall()
        if not rows:
            return None
        leagues = []
        for r in rows:
            mkts = r[7]
            if isinstance(mkts, str):
                try:
                    mkts = json.loads(mkts)
                except Exception:
                    mkts = ["h2h", "totals", "spreads"]
            elif not isinstance(mkts, list):
                mkts = ["h2h", "totals", "spreads"]
            leagues.append({
                "key": r[0],
                "title": r[1],
                "category": r[2] or "soccer",
                "enabled": bool(r[3]),
                "min_drop_pct": float(r[4]),
                "min_odds": float(r[5]),
                "max_odds": float(r[6]),
                "markets": mkts,
            })
        return leagues
    except Exception:
        return None

def ensure_league_thresholds_table(cur, conn):
    """Гарантує наявність таблиці league_thresholds у БД."""
    if cur is None or conn is None:
        return
    try:
        cur.execute("""
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
        """)
        conn.commit()
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass


def save_all_leagues_batch(cur, conn, leagues_list):
    """
    Зберігає повний список ліг у БД в одній транзакції (надійний захист від тайм-аутів та втрати стану).
    """
    if cur is None or conn is None:
        return False, "Відсутнє підключення до БД"
    try:
        ensure_league_thresholds_table(cur, conn)
        for item in leagues_list:
            cur.execute("""
                INSERT INTO league_thresholds (sport_key, title, category, enabled, min_drop_pct, min_odds, max_odds, markets, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (sport_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    enabled = EXCLUDED.enabled,
                    min_drop_pct = EXCLUDED.min_drop_pct,
                    min_odds = EXCLUDED.min_odds,
                    max_odds = EXCLUDED.max_odds,
                    markets = EXCLUDED.markets,
                    updated_at = NOW();
            """, (
                item["key"],
                item.get("title", item["key"]),
                item.get("category", "soccer"),
                bool(item.get("enabled", True)),
                float(item.get("min_drop_pct", 5.0)),
                float(item.get("min_odds", 1.40)),
                float(item.get("max_odds", 4.00)),
                json.dumps(item.get("markets", ["h2h", "totals", "spreads"]))
            ))
        conn.commit()
        return True, f"Успішно збережено {len(leagues_list)} ліг у базі даних."
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False, f"Помилка пакетного збереження ліг: {e}"


def sync_leagues_to_db(cur, conn, config=None, force=False):
    """
    Синхронізує конфігурацію ліг у БД: якщо таблиця порожня або force=True,
    заповнює її даними з config/leagues.json або DEFAULT_LEAGUES_CONFIG.
    """
    if cur is None or conn is None:
        return False, "Відсутнє підключення до БД"
    try:
        # Гарантуємо наявність таблиці
        cur.execute("""
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
        """)

        if not force:
            cur.execute("SELECT COUNT(*) FROM league_thresholds;")
            cnt = cur.fetchone()[0]
            if cnt > 0:
                conn.commit()
                return True, f"Таблиця вже містить {cnt} ліг."

        cfg = config or load_leagues_config()
        leagues = cfg.get("leagues", [])
        if not leagues:
            leagues = DEFAULT_LEAGUES_CONFIG.get("leagues", [])

        for item in leagues:
            cur.execute("""
                INSERT INTO league_thresholds (sport_key, title, category, enabled, min_drop_pct, min_odds, max_odds, markets, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (sport_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    enabled = EXCLUDED.enabled,
                    min_drop_pct = EXCLUDED.min_drop_pct,
                    min_odds = EXCLUDED.min_odds,
                    max_odds = EXCLUDED.max_odds,
                    markets = EXCLUDED.markets,
                    updated_at = NOW();
            """, (
                item["key"],
                item.get("title", item["key"]),
                item.get("category", "soccer"),
                bool(item.get("enabled", True)),
                float(item.get("min_drop_pct", 5.0)),
                float(item.get("min_odds", 1.40)),
                float(item.get("max_odds", 4.00)),
                json.dumps(item.get("markets", ["h2h", "totals", "spreads"]))
            ))
        conn.commit()
        return True, f"Успішно синхронізовано {len(leagues)} ліг у БД."
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False, f"Помилка синхронізації: {e}"

def save_league_threshold(cur, conn, sport_key, title=None, category=None, enabled=None, min_drop_pct=None, min_odds=None, max_odds=None, markets=None):
    """
    Зберігає або оновлює конфігурацію конкретної ліги в БД.
    """
    if cur is None or conn is None:
        return False, "Відсутнє підключення до БД"
    try:
        cur.execute("SELECT title, category, enabled, min_drop_pct, min_odds, max_odds, markets FROM league_thresholds WHERE sport_key = %s;", (sport_key,))
        row = cur.fetchone()
        
        cur_title = title if title is not None else (row[0] if row else sport_key)
        cur_cat = category if category is not None else (row[1] if row else "soccer")
        cur_en = enabled if enabled is not None else (row[2] if row else True)
        cur_drop = float(min_drop_pct) if min_drop_pct is not None else (float(row[3]) if row else 5.0)
        cur_min_k = float(min_odds) if min_odds is not None else (float(row[4]) if row else 1.40)
        cur_max_k = float(max_odds) if max_odds is not None else (float(row[5]) if row else 4.00)
        cur_mkts = markets if markets is not None else (row[6] if row else ["h2h", "totals", "spreads"])
        
        mkts_json = json.dumps(cur_mkts) if isinstance(cur_mkts, list) else cur_mkts

        cur.execute("""
            INSERT INTO league_thresholds (sport_key, title, category, enabled, min_drop_pct, min_odds, max_odds, markets, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
            ON CONFLICT (sport_key) DO UPDATE SET
                title = EXCLUDED.title,
                category = EXCLUDED.category,
                enabled = EXCLUDED.enabled,
                min_drop_pct = EXCLUDED.min_drop_pct,
                min_odds = EXCLUDED.min_odds,
                max_odds = EXCLUDED.max_odds,
                markets = EXCLUDED.markets,
                updated_at = NOW();
        """, (sport_key, cur_title, cur_cat, cur_en, cur_drop, cur_min_k, cur_max_k, mkts_json))
        conn.commit()
        return True, f"Лігу {sport_key} оновлено."
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False, f"Помилка збереження ліги {sport_key}: {e}"

def save_all_leagues_to_file(leagues_list, config_path=None):
    """Зберігає конфігурацію ліг у файл JSON (якщо він доступний для запису)."""
    path = resolve_config_path(config_path)
    try:
        data = {
            "version": "1.0",
            "leagues": leagues_list
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, f"Збережено у {path}"
    except Exception as e:
        return False, str(e)

def reset_league_thresholds_to_default(cur=None, conn=None):
    """
    Скидає конфігурацію ліг у БД до дефолтної (з config/leagues.json або DEFAULT_LEAGUES_CONFIG).
    """
    base_file = resolve_config_path()
    cfg = DEFAULT_LEAGUES_CONFIG
    if base_file.exists():
        try:
            with open(base_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = DEFAULT_LEAGUES_CONFIG
    
    if cur and conn:
        return sync_leagues_to_db(cur, conn, config=cfg, force=True)
    return True, "Скинуто до дефолтної конфігурації."

def load_leagues_config(config_path=None, cur=None, db_url=None):
    """
    Завантажує конфігурацію ліг із БД або JSON-файлу.
    Якщо є підключення до БД, накладає збережені налаштування з league_thresholds (DB is source of truth).
    """
    # 1. Завантажуємо базовий список усіх ліг з файлу leagues.json
    path = resolve_config_path(config_path)
    base_data = DEFAULT_LEAGUES_CONFIG
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "leagues" in data and isinstance(data["leagues"], list):
                    base_data = data
        except Exception as e:
            print(f"Warning: Failed to load leagues config from {path}: {e}. Using fallback defaults.")

    # 2. Якщо передано cur або можна з'єднатися через db_url чи SUPABASE_DB_URL
    db_cur = cur
    db_conn_to_close = None
    if db_cur is None:
        url = db_url or os.environ.get("SUPABASE_DB_URL", "")
        if url:
            try:
                import psycopg2
                db_conn_to_close = psycopg2.connect(url, connect_timeout=5)
                db_cur = db_conn_to_close.cursor()
            except Exception:
                db_cur = None

    if db_cur is not None:
        try:
            db_leagues = fetch_db_leagues(db_cur)
            if db_leagues:
                db_map = {lg["key"]: lg for lg in db_leagues}
                merged_leagues = []
                seen_keys = set()
                for base_lg in base_data.get("leagues", []):
                    k = base_lg["key"]
                    seen_keys.add(k)
                    if k in db_map:
                        item = dict(base_lg)
                        item.update(db_map[k])
                        merged_leagues.append(item)
                    else:
                        merged_leagues.append(base_lg)
                for k, db_lg in db_map.items():
                    if k not in seen_keys:
                        merged_leagues.append(db_lg)
                base_data = {"version": "2.0", "leagues": merged_leagues}
        except Exception as e:
            print(f"Warning: Failed to merge leagues from DB: {e}")
        finally:
            if db_conn_to_close:
                try:
                    db_cur.close()
                    db_conn_to_close.close()
                except Exception:
                    pass

    return base_data

def get_active_sports_map(config=None, cur=None):
    """Повертає словник {sport_key: localized_title} тільки для активних ліг (enabled=True)."""
    cfg = config or load_leagues_config(cur=cur)
    res = {}
    for item in cfg.get("leagues", []):
        if item.get("enabled", True):
            res[item["key"]] = item.get("title", item["key"])
    return res

def get_active_target_sports(config=None, cur=None):
    """Повертає список ключів активних ліг (enabled=True)."""
    cfg = config or load_leagues_config(cur=cur)
    return [item["key"] for item in cfg.get("leagues", []) if item.get("enabled", True)]

def get_league_thresholds(sport_key, config=None, cur=None):
    """
    Повертає налаштування порогів для конкретної ліги:
    - min_drop_pct: мінімальне просідання (%)
    - min_odds: мінімальний коефіцієнт
    - max_odds: максимальний коефіцієнт
    - markets: перелік маркетів
    - enabled: статус активності
    """
    if cur is not None:
        try:
            cur.execute("""
                SELECT min_drop_pct, min_odds, max_odds, markets, enabled
                FROM league_thresholds
                WHERE sport_key = %s;
            """, (sport_key,))
            r = cur.fetchone()
            if r:
                mkts = r[3]
                if isinstance(mkts, str):
                    try:
                        mkts = json.loads(mkts)
                    except Exception:
                        mkts = ["h2h", "totals", "spreads"]
                return {
                    "min_drop_pct": float(r[0]),
                    "min_odds": float(r[1]),
                    "max_odds": float(r[2]),
                    "markets": mkts if isinstance(mkts, list) else ["h2h", "totals", "spreads"],
                    "enabled": bool(r[4]),
                }
        except Exception:
            pass

    cfg = config or load_leagues_config(cur=cur)
    for item in cfg.get("leagues", []):
        if item.get("key") == sport_key:
            return {
                "min_drop_pct": float(item.get("min_drop_pct", 5.0)),
                "min_odds": float(item.get("min_odds", 1.40)),
                "max_odds": float(item.get("max_odds", 4.00)),
                "markets": item.get("markets", ["h2h", "totals", "spreads"]),
                "enabled": bool(item.get("enabled", True)),
            }

    # Значення за замовчуванням для тенісу (динамічні турніри)
    if sport_key and str(sport_key).startswith("tennis_"):
        return {
            "min_drop_pct": 5.0,
            "min_odds": 1.35,
            "max_odds": 4.00,
            "markets": ["h2h", "totals", "spreads"],
            "enabled": True,
        }

    # Значення за замовчуванням
    return {
        "min_drop_pct": 5.0,
        "min_odds": 1.40,
        "max_odds": 4.00,
        "markets": ["h2h", "totals", "spreads"],
        "enabled": True,
    }
