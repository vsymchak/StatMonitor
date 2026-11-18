import os
import sys
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import execute_values

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))

DB_URL = os.environ.get("SUPABASE_DB_URL")

def get_db():
    if not DB_URL:
        return None
    return psycopg2.connect(DB_URL)

def ensure_scheduler_tables(cur, conn):
    cur.execute("""
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
        CREATE INDEX IF NOT EXISTS idx_scheduler_target ON scheduler_plan (target_time, status);
    """)
    conn.commit()

def cluster_events(events, threshold_minutes=25):
    """
    Об'єднує події, що починаються з різницею менше ніж threshold_minutes.
    """
    if not events:
        return []

    sorted_events = sorted(events, key=lambda x: x["commence_time"])
    clusters = []
    current_cluster = [sorted_events[0]]

    for ev in sorted_events[1:]:
        prev_time = current_cluster[-1]["commence_time"]
        curr_time = ev["commence_time"]
        diff = (curr_time - prev_time).total_seconds() / 60.0
        if diff <= threshold_minutes:
            current_cluster.append(ev)
        else:
            clusters.append(current_cluster)
            current_cluster = [ev]

    if current_cluster:
        clusters.append(current_cluster)

    return clusters

def generate_schedule_points(events, pending_bets, now_utc=None, horizon_hours=36, require_pending=True):
    """
    Генерує контрольні точки розкладу:
    1. PRE_MATCH: за 15 хвилин до старту гри (тільки для матчів з активними ставками у Paper Bank).
    2. SETTLE: через 115 хвилин після старту гри для активних ставок у Paper Bank.
    Матчі без активних ставок не створюють зобов'язувальних точок у scheduler_plan, щоб уникнути хибних тривог Watchdog.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    points = []

    pending_ids = {str(b.get("event_id") or "") for b in (pending_bets or []) if b.get("event_id")}

    # Відбираємо події: якщо require_pending=True, тільки ті події, де є активна ставка у Paper Bank
    if require_pending:
        relevant_events = [e for e in (events or []) if str(e.get("id")) in pending_ids]
    else:
        relevant_events = list(events or [])

    # Додаємо події безпосередньо з pending_bets, якщо їх немає в events
    existing_ids = {str(e.get("id")) for e in relevant_events if "id" in e}
    for b in (pending_bets or []):
        bid = str(b.get("event_id") or "")
        if bid and bid not in existing_ids:
            relevant_events.append({
                "id": bid,
                "match_name": b.get("match_name", ""),
                "commence_time": b.get("commence_time"),
            })

    # 1. Передматчеві точки (PRE_MATCH) тільки для активних ставок
    upcoming = [
        e for e in relevant_events
        if e.get("commence_time") and e["commence_time"] > now_utc and e["commence_time"] <= now_utc + timedelta(hours=horizon_hours)
    ]
    clusters = cluster_events(upcoming, threshold_minutes=25)

    for cl in clusters:
        first_ev = cl[0]
        target_t = first_ev["commence_time"] - timedelta(minutes=15)
        if target_t >= now_utc - timedelta(minutes=5):
            ev_names = [e.get("match_name") or f"{e.get('home_team', '')} - {e.get('away_team', '')}".strip(" -") or e.get("id") for e in cl]
            if len(ev_names) == 1:
                desc = f"Перед грою (активна ставка): {ev_names[0]}"
            else:
                desc = f"Перед грою (активні ставки {len(ev_names)}): {ev_names[0]} та ін."
            points.append({
                "target_time": target_t,
                "trigger_type": "PRE_MATCH",
                "event_ids": [e["id"] for e in cl if "id" in e],
                "description": desc,
            })

    # 2. Точки розрахунку ставок (SETTLE)
    for b in (pending_bets or []):
        c_time = b.get("commence_time")
        if not c_time:
            continue
        if c_time.tzinfo is None:
            c_time = c_time.replace(tzinfo=timezone.utc)
        settle_t = c_time + timedelta(minutes=115)
        if settle_t >= now_utc - timedelta(minutes=15) and settle_t <= now_utc + timedelta(hours=horizon_hours):
            m_name = b.get("match_name") or b.get("event_id") or "матч"
            points.append({
                "target_time": settle_t,
                "trigger_type": "SETTLE",
                "event_ids": [b.get("event_id", "")],
                "description": f"Розрахунок: {m_name}",
            })

    # Сортування та об'єднання точок з дельтою < 15 хвилин
    points.sort(key=lambda p: p["target_time"])
    merged = []
    for p in points:
        if not merged:
            merged.append(p)
            continue
        prev = merged[-1]
        delta_min = (p["target_time"] - prev["target_time"]).total_seconds() / 60.0
        if delta_min < 15:
            prev["event_ids"] = list(set(prev["event_ids"] + p["event_ids"]))
            if p["description"] not in prev["description"]:
                prev["description"] += f"; {p['description']}"
        else:
            merged.append(p)

    return merged

def sync_schedule_to_db(cur, conn, points):
    """
    Зберігає актуальні точки розкладу в таблицю scheduler_plan з дедуплікацією.
    """
    if not points:
        return
    ensure_scheduler_tables(cur, conn)
    # Позначаємо застарілі невиконані точки як SKIPPED
    cur.execute("UPDATE scheduler_plan SET status='SKIPPED' WHERE status='PLANNED' AND target_time < NOW() - INTERVAL '1 hour';")
    
    # Отримуємо вже наявні точки у статусах PLANNED або EXECUTED, щоб уникнути дублювання
    cur.execute("SELECT target_time, description FROM scheduler_plan WHERE status IN ('PLANNED', 'EXECUTED') AND target_time > NOW() - INTERVAL '6 hours';")
    existing_keys = set()
    for row in cur.fetchall():
        t_exist = row[0]
        if t_exist.tzinfo is None:
            t_exist = t_exist.replace(tzinfo=timezone.utc)
        existing_keys.add((t_exist.strftime("%Y-%m-%d %H:%M"), row[1]))

    rows = []
    for p in points:
        t_target = p["target_time"]
        if t_target.tzinfo is None:
            t_target = t_target.replace(tzinfo=timezone.utc)
        key = (t_target.strftime("%Y-%m-%d %H:%M"), p["description"])
        if key in existing_keys:
            continue
        existing_keys.add(key)
        rows.append((
            t_target,
            p["trigger_type"],
            p["event_ids"],
            p["description"],
            "PLANNED",
        ))
    if rows:
        try:
            execute_values(
                cur,
                """
                INSERT INTO scheduler_plan (target_time, trigger_type, event_ids, description, status)
                VALUES %s;
                """,
                rows,
            )
        except Exception:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO scheduler_plan (target_time, trigger_type, event_ids, description, status)
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    r,
                )
    conn.commit()

def mark_checkpoints_executed(cur, conn, now_utc=None, window_minutes=35):
    """
    Позначає контрольні точки як EXECUTED, якщо поточний запуск покриває їхнє часове вікно.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    t_start = now_utc - timedelta(minutes=window_minutes)
    t_end = now_utc + timedelta(minutes=15)
    cur.execute(
        """
        UPDATE scheduler_plan 
        SET status = 'EXECUTED', executed_at = %s 
        WHERE status = 'PLANNED' AND target_time >= %s AND target_time <= %s;
        """,
        (now_utc, t_start, t_end),
    )
    conn.commit()

def format_schedule_for_tg(points, limit=3):
    """
    Форматує найближчі точки розкладу у вигляді тексту для повідомлення Telegram.
    """
    if not points:
        return ""
    lines = ["⏰ <b>Наступні контрольні точки моніторингу:</b>"]
    for p in points[:limit]:
        t_kyiv = p["target_time"].astimezone(KYIV_TZ)
        time_str = t_kyiv.strftime("%d.%m %H:%M")
        desc = p["description"]
        icon = "🎯" if p["trigger_type"] == "PRE_MATCH" else "⚖️"
        lines.append(f"  {icon} <code>{time_str}</code> — {desc}")
    return "\n".join(lines)

def run_schedule_update(cur, conn):
    """
    Головна функція для оновлення розкладу з БД:
    Зчитує найближчі події та ставки, формує точки розкладу, записує в БД і повертає текст для Telegram.
    """
    try:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='events';")
        ev_cols = {r[0] for r in cur.fetchall()}
        id_c = "id" if "id" in ev_cols else "event_id"
        h_team = "home_team" if "home_team" in ev_cols else "match_name"
        a_team = "away_team" if "away_team" in ev_cols else "match_name"

        cur.execute(f"SELECT {id_c}, {h_team}, {a_team}, commence_time FROM events WHERE commence_time > NOW() - INTERVAL '2 hours' AND commence_time < NOW() + INTERVAL '36 hours';")
        events = []
        for r in cur.fetchall():
            c_time = r[3]
            if c_time and c_time.tzinfo is None:
                c_time = c_time.replace(tzinfo=timezone.utc)
            events.append({
                "id": str(r[0]),
                "home_team": str(r[1] or ""),
                "away_team": str(r[2] or ""),
                "commence_time": c_time,
            })

        cur.execute("SELECT id, event_id, match_name, commence_time FROM paper_bets WHERE status='PENDING';")
        pending = []
        for r in cur.fetchall():
            c_time = r[3]
            if c_time and c_time.tzinfo is None:
                c_time = c_time.replace(tzinfo=timezone.utc)
            pending.append({
                "id": r[0],
                "event_id": str(r[1]),
                "match_name": str(r[2]),
                "commence_time": c_time,
            })

        points = generate_schedule_points(events, pending)
        sync_schedule_to_db(cur, conn, points)
        return format_schedule_for_tg(points)
    except Exception as e:
        print(f"Schedule update err: {e}")
        return ""

if __name__ == "__main__":
    conn = get_db()
    if not conn:
        print("Помилка: SUPABASE_DB_URL не знайдено.")
        sys.exit(1)
    cur = conn.cursor()
    txt = run_schedule_update(cur, conn)
    print("Результат розкладу:\n", txt or "Немає запланованих точок.")
    cur.close()
    conn.close()
