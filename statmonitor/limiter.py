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
        intervals = {"HOT": 45, "WARM": 99999, "COLD": 99999}
    elif mode == "ECO":
        intervals = {"HOT": 25, "WARM": 360, "COLD": 720}
    else:  # NORMAL
        intervals = {"HOT": 25, "WARM": 120, "COLD": 360}

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
