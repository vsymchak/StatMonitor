from datetime import datetime, timezone, timedelta
from psycopg2.extras import execute_values

def ensure_poll_log_table(cur, conn):
    """Створює таблицю обліку опитувань ліг, якщо вона ще не існує."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sports_poll_log (
            sport TEXT PRIMARY KEY,
            last_polled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            poll_count INT NOT NULL DEFAULT 1,
            tier TEXT NOT NULL DEFAULT 'COLD'
        );
    """)
    conn.commit()

def get_budget_mode(remaining_credits):
    """
    Визначає режим економії на основі залишку запитів The Odds API:
    - NORMAL: > 200 кредитів
    - ECO: 50..200 кредитів
    - CRITICAL: < 50 кредитів
    """
    if remaining_credits is None:
        return "NORMAL"
    try:
        rem = float(str(remaining_credits).strip())
    except (ValueError, TypeError):
        return "NORMAL"

    if rem > 200:
        return "NORMAL"
    elif rem >= 50:
        return "ECO"
    else:
        return "CRITICAL"

def classify_sports_urgency(cur, sports_keys, now_utc=None):
    """
    Класифікує ліги на основі часу найближчого матчу в базі даних:
    - HOT: матч через < 6 годин (або вже почався в межах 2 год)
    - WARM: матч через 6..24 години
    - COLD: матч через > 24 години або подій немає в розкладі
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # Запитуємо найближчий матч для кожної ліги
    cur.execute("""
        SELECT sport, MIN(commence_time)
        FROM events
        WHERE commence_time > NOW() - INTERVAL '2 hours'
        GROUP BY sport;
    """)
    earliest_map = {}
    for r in cur.fetchall():
        sp, c_time = r[0], r[1]
        if c_time and c_time.tzinfo is None:
            c_time = c_time.replace(tzinfo=timezone.utc)
        earliest_map[sp] = c_time

    tiers = {}
    for sp in sports_keys:
        t_game = earliest_map.get(sp)
        if not t_game:
            tiers[sp] = "COLD"
            continue

        hours_to_game = (t_game - now_utc).total_seconds() / 3600.0
        if hours_to_game <= 6.0:
            tiers[sp] = "HOT"
        elif hours_to_game <= 24.0:
            tiers[sp] = "WARM"
        else:
            tiers[sp] = "COLD"

    return tiers

def filter_sports_to_poll(cur, conn, sports_map, remaining_credits=None, now_utc=None):
    """
    Розумний фільтр ліг:
    Визначає, які ліги дійсно потрібно опитати в цьому циклі, щоб не витрачати квоту на порожні ліги.
    """
    if not sports_map:
        return {}, "NORMAL", {}

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    ensure_poll_log_table(cur, conn)
    mode = get_budget_mode(remaining_credits)
    sports_keys = list(sports_map.keys())
    tiers = classify_sports_urgency(cur, sports_keys, now_utc=now_utc)

    # Зчитуємо історію останніх опитувань
    cur.execute("SELECT sport, last_polled_at FROM sports_poll_log;")
    history = {}
    for r in cur.fetchall():
        sp, last_t = r[0], r[1]
        if last_t and last_t.tzinfo is None:
            last_t = last_t.replace(tzinfo=timezone.utc)
        history[sp] = last_t

    # Пороги мінімального інтервалу між опитуваннями (у хвилинах) залежно від режиму
    if mode == "CRITICAL":
        intervals = {"HOT": 60, "WARM": 99999, "COLD": 99999}
    elif mode == "ECO":
        intervals = {"HOT": 60, "WARM": 120, "COLD": 360}
    else:  # NORMAL
        intervals = {"HOT": 45, "WARM": 90, "COLD": 240}

    selected = {}
    for sp, title in sports_map.items():
        tier = tiers.get(sp, "COLD")
        last_t = history.get(sp)

        # Якщо ліга ще ніколи не опитувалась — додаємо її
        if not last_t:
            selected[sp] = title
            continue

        elapsed_m = (now_utc - last_t).total_seconds() / 60.0
        required_interval = intervals.get(tier, 360)

        if elapsed_m >= required_interval:
            selected[sp] = title

    return selected, mode, tiers

def record_poll_success(cur, conn, polled_sports, tiers=None, now_utc=None):
    """Фіксує успішне опитування ліг у таблиці sports_poll_log."""
    if not polled_sports:
        return
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    tiers = tiers or {}

    rows = []
    for sp in polled_sports:
        tier = tiers.get(sp, "COLD")
        rows.append((sp, now_utc, 1, tier))

    try:
        execute_values(
            cur,
            """
            INSERT INTO sports_poll_log (sport, last_polled_at, poll_count, tier)
            VALUES %s
            ON CONFLICT (sport) DO UPDATE SET
                last_polled_at = EXCLUDED.last_polled_at,
                poll_count = sports_poll_log.poll_count + 1,
                tier = EXCLUDED.tier;
            """,
            rows,
        )
    except Exception:
        for r in rows:
            cur.execute(
                """
                INSERT INTO sports_poll_log (sport, last_polled_at, poll_count, tier)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (sport) DO UPDATE SET
                    last_polled_at = EXCLUDED.last_polled_at,
                    poll_count = sports_poll_log.poll_count + 1,
                    tier = EXCLUDED.tier;
                """,
                r,
            )
    conn.commit()


def compute_sports_quota_breakdown(poll_data, leagues_config=None, total_monthly_limit=2500):
    """
    Аналізує розподіл витрати API-токенів / запитів The Odds API за видами спорту (SPEC-10 & SPEC-25).
    Показує, який саме вид спорту та які конкретно ліги спожили квоту.
    """
    # Нормалізація вхідних даних у список словників
    records = []
    if poll_data is not None:
        if hasattr(poll_data, "to_dict"):
            records = poll_data.to_dict("records")
        elif isinstance(poll_data, list):
            for item in poll_data:
                if isinstance(item, dict):
                    records.append(item)
                elif isinstance(item, (list, tuple)) and len(item) >= 4:
                    records.append({
                        "sport": item[0],
                        "tier": item[1],
                        "last_polled_at": item[2],
                        "poll_count": item[3]
                    })

    # Створюємо мапу назв та категорій із конфігурації ліг
    title_map = {}
    cat_map = {}
    if leagues_config and isinstance(leagues_config, dict) and "leagues" in leagues_config:
        for lg in leagues_config["leagues"]:
            k = lg.get("key")
            if k:
                title_map[k] = lg.get("title", k)
                cat_map[k] = lg.get("category", "")

    CATEGORY_METADATA = {
        "soccer": {"name": "⚽ Футбол", "order": 1},
        "basketball": {"name": "🏀 Баскетбол", "order": 2},
        "tennis": {"name": "🎾 Теніс", "order": 3},
        "icehockey": {"name": "🏒 Хокей", "order": 4},
        "mma": {"name": "🥊 ММА / Бокс", "order": 5},
        "americanfootball": {"name": "🏈 Американський футбол", "order": 6},
        "baseball": {"name": "⚾ Бейсбол", "order": 7},
        "other": {"name": "🎯 Інші види спорту", "order": 8},
    }

    def detect_category(sport_key):
        if not sport_key:
            return "other"
        sk = str(sport_key).lower()
        if sk in cat_map and cat_map[sk] in CATEGORY_METADATA:
            return cat_map[sk]
        for prefix in ("soccer", "basketball", "tennis", "icehockey", "mma", "boxing", "americanfootball", "baseball"):
            if sk.startswith(prefix):
                return "mma" if prefix == "boxing" else prefix
        return "other"

    total_polls = 0
    grouped_cats = {}
    for c_key, c_info in CATEGORY_METADATA.items():
        grouped_cats[c_key] = {
            "category_key": c_key,
            "category_name": c_info["name"],
            "order": c_info["order"],
            "poll_count": 0,
            "leagues": [],
        }

    for r in records:
        sp_key = r.get("sport") or ""
        p_cnt = int(r.get("poll_count") or 0)
        total_polls += p_cnt
        cat = detect_category(sp_key)
        disp_title = title_map.get(sp_key, sp_key)

        league_entry = {
            "sport": sp_key,
            "title": disp_title,
            "tier": str(r.get("tier", "COLD")),
            "last_polled_at": r.get("last_polled_at"),
            "poll_count": p_cnt,
            "category_key": cat,
            "category_name": CATEGORY_METADATA[cat]["name"],
        }
        grouped_cats[cat]["poll_count"] += p_cnt
        grouped_cats[cat]["leagues"].append(league_entry)

    categories_list = []
    for c_key, c_data in grouped_cats.items():
        p_cnt = c_data["poll_count"]
        pct_used = round((p_cnt / total_polls * 100.0), 1) if total_polls > 0 else 0.0
        pct_limit = round((p_cnt / float(total_monthly_limit) * 100.0), 1) if total_monthly_limit > 0 else 0.0

        c_data["leagues"].sort(key=lambda x: x["poll_count"], reverse=True)
        top_lg = c_data["leagues"][0] if c_data["leagues"] else None
        top_desc = f"{top_lg['title']} ({top_lg['poll_count']})" if top_lg else "—"

        categories_list.append({
            "category_key": c_key,
            "category_name": c_data["category_name"],
            "poll_count": p_cnt,
            "pct_of_used": pct_used,
            "pct_of_limit": pct_limit,
            "leagues_count": len(c_data["leagues"]),
            "top_league_title": top_desc,
            "leagues": c_data["leagues"],
        })

    # Сортуємо види спорту за кількістю запитів у порядку спадання
    categories_list.sort(key=lambda x: x["poll_count"], reverse=True)

    quota_used_pct = round((total_polls / float(total_monthly_limit) * 100.0), 1) if total_monthly_limit > 0 else 0.0

    return {
        "total_polls": total_polls,
        "total_limit": total_monthly_limit,
        "quota_used_pct": quota_used_pct,
        "categories": categories_list,
    }

