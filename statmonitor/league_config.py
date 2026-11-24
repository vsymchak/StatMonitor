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
            {"key": "soccer_epl", "title": "Англія (Прем'єр-ліга / АПЛ)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_spain_la_liga", "title": "Іспанія (Ла Ліга)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_italy_serie_a", "title": "Італія (Серія А)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_germany_bundesliga", "title": "Німеччина (Бундесліга)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_france_ligue_one", "title": "Франція (Ліга 1)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_ukraine_premier_league", "title": "Україна (УПЛ)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_poland_ekstraklasa", "title": "Польща (Екстракласа)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_uefa_champs_league", "title": "Ліга Чемпіонів УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_uefa_europa_league", "title": "Ліга Європи УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_uefa_conference_league", "title": "Ліга Конференцій УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
            {"key": "soccer_uefa_nations_league", "title": "Ліга Націй УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
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
            WHERE sport_key != '__default__'
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
        clean_list = [lg for lg in leagues_list if lg.get("key") != "__default__"]
        for item in clean_list:
            mkts = item.get("markets", ["h2h", "totals", "spreads"])
            if isinstance(mkts, list):
                mkts = [m for m in mkts if m != "btts"]
            if not mkts:
                mkts = ["h2h", "totals", "spreads"]

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
                json.dumps(mkts)
            ))
        conn.commit()
        return True, f"Успішно збережено {len(clean_list)} ліг у базі даних."
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
            cur.execute("SELECT COUNT(*) FROM league_thresholds WHERE sport_key != '__default__';")
            cnt = cur.fetchone()[0]
            if cnt > 0:
                conn.commit()
                return True, f"Таблиця вже містить {cnt} ліг."

        cfg = config or load_leagues_config()
        leagues = cfg.get("leagues", [])
        if not leagues:
            leagues = DEFAULT_LEAGUES_CONFIG.get("leagues", [])

        clean_leagues = [lg for lg in leagues if lg.get("key") != "__default__"]
        for item in clean_leagues:
            mkts = item.get("markets", ["h2h", "totals", "spreads"])
            if isinstance(mkts, list):
                mkts = [m for m in mkts if m != "btts"]
            if not mkts:
                mkts = ["h2h", "totals", "spreads"]

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
                json.dumps(mkts)
            ))
        conn.commit()
        return True, f"Успішно синхронізовано {len(clean_leagues)} ліг у БД."
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
    """Зберігає конфігурацію ліг у файл JSON (якщо він доступний для запису), зберігаючи defaults та version."""
    path = resolve_config_path(config_path)
    try:
        existing = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        if not isinstance(existing, dict):
            existing = {}

        existing["version"] = existing.get("version", "2.0")
        clean_leagues = [dict(lg) for lg in leagues_list if lg.get("key") != "__default__"]
        for lg in clean_leagues:
            if "markets" in lg and isinstance(lg["markets"], list):
                lg["markets"] = [m for m in lg["markets"] if m != "btts"]
                if not lg["markets"]:
                    lg["markets"] = ["h2h", "totals", "spreads"]
        existing["leagues"] = clean_leagues

        if "defaults" in existing and isinstance(existing["defaults"], dict):
            if "markets" in existing["defaults"] and isinstance(existing["defaults"]["markets"], list):
                existing["defaults"]["markets"] = [m for m in existing["defaults"]["markets"] if m != "btts"]
                if not existing["defaults"]["markets"]:
                    existing["defaults"]["markets"] = ["h2h", "totals", "spreads"]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
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
            if config_path is not None and cur is None and db_url is None:
                return DEFAULT_LEAGUES_CONFIG
    elif config_path is not None:
        return DEFAULT_LEAGUES_CONFIG

    # Якщо користувач передав окремий тестовий чи локальний config_path і не надав cur/db_url,
    # не підключаємося до глобальної віддаленої БД Supabase
    if config_path is not None and cur is None and db_url is None:
        return base_data

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
                    if k == "__default__":
                        continue
                    seen_keys.add(k)
                    if k in db_map:
                        item = dict(base_lg)
                        item.update(db_map[k])
                        merged_leagues.append(item)
                    else:
                        merged_leagues.append(base_lg)
                for k, db_lg in db_map.items():
                    if k not in seen_keys and k != "__default__":
                        merged_leagues.append(db_lg)
                res = dict(base_data)
                res["leagues"] = merged_leagues
                base_data = res
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

DEFAULT_GLOBAL_THRESHOLDS = {
    "min_drop_pct": 5.0,
    "min_odds": 1.40,
    "max_odds": 4.00,
    "min_confidence": 8,
    "markets": ["h2h", "totals", "spreads"],
    "enabled": True,
}

def get_global_defaults(config=None, cur=None):
    """
    Повертає загальні (дефолтні) налаштування системи.
    Якщо налаштування збережено в БД (sport_key = '__default__') або у config/leagues.json, бере їх.
    """
    defaults = dict(DEFAULT_GLOBAL_THRESHOLDS)

    # 1. Читання з БД (sport_key = '__default__')
    if cur is not None:
        try:
            cur.execute("""
                SELECT min_drop_pct, min_odds, max_odds, markets, enabled
                FROM league_thresholds
                WHERE sport_key = '__default__';
            """)
            r = cur.fetchone()
            if r:
                if r[0] is not None:
                    defaults["min_drop_pct"] = float(r[0])
                if r[1] is not None:
                    defaults["min_odds"] = float(r[1])
                if r[2] is not None:
                    defaults["max_odds"] = float(r[2])
                if r[3] is not None:
                    mkts = r[3]
                    if isinstance(mkts, str):
                        try:
                            mkts = json.loads(mkts)
                        except Exception:
                            mkts = defaults["markets"]
                    if isinstance(mkts, list) and mkts:
                        defaults["markets"] = mkts
                if r[4] is not None:
                    defaults["enabled"] = bool(r[4])
                return defaults
        except Exception:
            pass

    # 2. Читання з JSON-файлу
    cfg = config or load_leagues_config(cur=cur)
    if isinstance(cfg, dict) and "defaults" in cfg and isinstance(cfg["defaults"], dict):
        d = cfg["defaults"]
        if "min_drop_pct" in d and d["min_drop_pct"] is not None:
            defaults["min_drop_pct"] = float(d["min_drop_pct"])
        if "min_odds" in d and d["min_odds"] is not None:
            defaults["min_odds"] = float(d["min_odds"])
        if "max_odds" in d and d["max_odds"] is not None:
            defaults["max_odds"] = float(d["max_odds"])
        if "min_confidence" in d and d["min_confidence"] is not None:
            defaults["min_confidence"] = int(d["min_confidence"])
        if "markets" in d and isinstance(d["markets"], list) and d["markets"]:
            defaults["markets"] = d["markets"]
        if "enabled" in d and d["enabled"] is not None:
            defaults["enabled"] = bool(d["enabled"])

    return defaults

def save_global_defaults(cur, conn, min_drop_pct=5.0, min_odds=1.50, max_odds=2.40, min_confidence=8, markets=None, enabled=True, config_path=None):
    """
    Зберігає загальні дефолтні налаштування системи в БД (sport_key = '__default__')
    та оновлює файл config/leagues.json у секції 'defaults'.
    """
    mkts = markets or ["h2h", "totals", "spreads"]
    mkts = [m for m in mkts if m != "btts"]
    if not mkts:
        mkts = ["h2h", "totals", "spreads"]
    mkts_json = json.dumps(mkts)

    # 1. Запис у файл конфігурації
    path = resolve_config_path(config_path)
    try:
        data = {}
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if not isinstance(data, dict):
            data = {"version": "2.0", "leagues": []}
        data["defaults"] = {
            "min_drop_pct": float(min_drop_pct),
            "min_odds": float(min_odds),
            "max_odds": float(max_odds),
            "min_confidence": int(min_confidence),
            "markets": mkts,
            "enabled": bool(enabled)
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as fe:
        print(f"Warning: Failed to save global defaults to file: {fe}")

    # 2. Запис у базу даних PostgreSQL
    if cur and conn:
        try:
            ensure_league_thresholds_table(cur, conn)
            cur.execute("""
                INSERT INTO league_thresholds (sport_key, title, category, enabled, min_drop_pct, min_odds, max_odds, markets, updated_at)
                VALUES ('__default__', 'Загальні системні налаштування (Дефолт)', 'system', %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (sport_key) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    enabled = EXCLUDED.enabled,
                    min_drop_pct = EXCLUDED.min_drop_pct,
                    min_odds = EXCLUDED.min_odds,
                    max_odds = EXCLUDED.max_odds,
                    markets = EXCLUDED.markets,
                    updated_at = NOW();
            """, (bool(enabled), float(min_drop_pct), float(min_odds), float(max_odds), mkts_json))
            conn.commit()
            return True, "Загальні системні налаштування успішно збережено в базі даних."
        except Exception as dbe:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return False, f"Помилка збереження дефолтних налаштувань у БД: {dbe}"

    return True, "Загальні системні налаштування збережено локально."

def get_league_thresholds(sport_key, config=None, cur=None):
    """
    Повертає налаштування порогів для конкретної ліги.
    Якщо для окремої ліги не встановлено індивідуальних параметрів,
    система автоматично використовує глобальні дефолтні налаштування.
    """
    glob = get_global_defaults(config=config, cur=cur)

    if cur is not None and sport_key != '__default__':
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
                        mkts = glob["markets"]
                return {
                    "min_drop_pct": float(r[0]) if r[0] is not None else glob["min_drop_pct"],
                    "min_odds": float(r[1]) if r[1] is not None else glob["min_odds"],
                    "max_odds": float(r[2]) if r[2] is not None else glob["max_odds"],
                    "markets": mkts if isinstance(mkts, list) and mkts else glob["markets"],
                    "enabled": bool(r[4]) if r[4] is not None else glob["enabled"],
                }
        except Exception:
            pass

    cfg = config or load_leagues_config(cur=cur)
    for item in cfg.get("leagues", []):
        if item.get("key") == sport_key:
            mkts = item.get("markets")
            return {
                "min_drop_pct": float(item.get("min_drop_pct", glob["min_drop_pct"])),
                "min_odds": float(item.get("min_odds", glob["min_odds"])),
                "max_odds": float(item.get("max_odds", glob["max_odds"])),
                "markets": mkts if isinstance(mkts, list) and mkts else glob["markets"],
                "enabled": bool(item.get("enabled", glob["enabled"])),
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

    # Якщо для ліги немає запису — повертаємо глобальні системні налаштування
    return glob
