import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta
import psycopg2

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))

DB_URL = os.environ.get("SUPABASE_DB_URL")
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL")

def get_db():
    if not DB_URL:
        return None
    return psycopg2.connect(DB_URL)

def ensure_heartbeat_table(cur, conn):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_heartbeat (
            service_name TEXT PRIMARY KEY,
            last_ping_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_status TEXT NOT NULL DEFAULT 'OK',
            last_duration_sec NUMERIC(6,2),
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    conn.commit()

def detect_stale_heartbeat(last_ping_at, now_utc=None, max_gap_minutes=150):
    """
    Перевіряє, чи не завис планувальник між попереднім і поточним запусками.
    У денний час (08:00 - 23:00 за Києвом) пауза більше max_gap_minutes вважається затримкою.
    """
    if not last_ping_at:
        return None
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if last_ping_at.tzinfo is None:
        last_ping_at = last_ping_at.replace(tzinfo=timezone.utc)

    gap_minutes = (now_utc - last_ping_at).total_seconds() / 60.0
    now_kyiv = now_utc.astimezone(KYIV_TZ)

    # Перевірка лише в активний денний час (08:00 - 23:00)
    if 8 <= now_kyiv.hour <= 23 and gap_minutes > max_gap_minutes:
        return {
            "gap_minutes": int(gap_minutes),
            "last_ping_kyiv": last_ping_at.astimezone(KYIV_TZ).strftime("%d.%m %H:%M"),
        }
    return None

def detect_missed_checkpoints(cur, conn, now_utc=None, threshold_minutes=25):
    """
    Знаходить заплановані контрольні точки в scheduler_plan, які запізнилися більш ніж на threshold_minutes.
    Переводить їх у статус MISSED або SKIPPED.
    У нічний час (00:00 - 08:00 за Києвом) застарілі точки переводить у SKIPPED без тривожних алертів.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    # Перевіряємо наявність таблиці scheduler_plan
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='scheduler_plan';")
    if not cur.fetchone():
        return []

    cutoff = now_utc - timedelta(minutes=threshold_minutes)
    cur.execute(
        """
        SELECT id, target_time, trigger_type, description 
        FROM scheduler_plan 
        WHERE status = 'PLANNED' AND target_time < %s
        ORDER BY target_time ASC;
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    if not rows:
        return []

    now_kyiv = now_utc.astimezone(KYIV_TZ)
    is_night = (0 <= now_kyiv.hour < 8)

    # Нічний режим тиші (00:00 - 08:00 за Києвом):
    # Застарілі точки переводимо у SKIPPED тихо, не надсилаючи алерту у Telegram
    if is_night:
        ids_to_skip = [r[0] for r in rows]
        cur.execute("UPDATE scheduler_plan SET status = 'SKIPPED' WHERE id = ANY(%s);", (ids_to_skip,))
        conn.commit()
        return []

    missed = []
    ids_to_update = []
    seen = set()
    for r in rows:
        t_target = r[1]
        if t_target.tzinfo is None:
            t_target = t_target.replace(tzinfo=timezone.utc)
        delay_m = int((now_utc - t_target).total_seconds() / 60.0)
        desc = r[3]
        key = (t_target.strftime("%Y-%m-%d %H:%M"), desc)
        if key not in seen:
            seen.add(key)
            missed.append({
                "id": r[0],
                "target_time": t_target,
                "trigger_type": r[2],
                "description": desc,
                "delay_minutes": delay_m,
            })
        ids_to_update.append(r[0])

    if ids_to_update:
        cur.execute("UPDATE scheduler_plan SET status = 'MISSED' WHERE id = ANY(%s);", (ids_to_update,))
        conn.commit()

    return missed

def format_watchdog_alert(missed_points=None, stale_info=None):
    """
    Форматує тривожне або інформаційне повідомлення про затримки планувальника.
    """
    if not missed_points and not stale_info:
        return ""

    lines = ["⚠️ <b>Увага: Затримка планувальника (Watchdog Alert)</b>"]

    if stale_info:
        lines.append(
            f"⏱ <b>Виявлено паузу між запусками:</b> <code>{stale_info['gap_minutes']} хв</code>\n"
            f"   (Попередній успішний пульс: <code>{stale_info['last_ping_kyiv']}</code>)"
        )

    if missed_points:
        lines.append(f"\n🚨 <b>Пропущено/затримано контрольних точок: {len(missed_points)}</b>")
        for p in missed_points[:4]:
            t_str = p["target_time"].astimezone(KYIV_TZ).strftime("%H:%M")
            lines.append(f"  • <code>{t_str}</code> (затримка <b>{p['delay_minutes']} хв</b>): {p['description']}")

    lines.append("\n<i>Причина: затримка черги GitHub Actions або тимчасовий збій крону.</i>")
    return "\n".join(lines)

def record_heartbeat(cur, conn, duration_sec=0.0, status="OK", metadata=None):
    """
    Оновлює пульс сервісу в таблиці system_heartbeat.
    """
    ensure_heartbeat_table(cur, conn)
    meta_json = json.dumps(metadata or {})
    cur.execute(
        """
        INSERT INTO system_heartbeat (service_name, last_ping_at, last_status, last_duration_sec, metadata)
        VALUES ('StatMonitor', NOW(), %s, %s, %s::jsonb)
        ON CONFLICT (service_name) DO UPDATE SET
            last_ping_at = EXCLUDED.last_ping_at,
            last_status = EXCLUDED.last_status,
            last_duration_sec = EXCLUDED.last_duration_sec,
            metadata = EXCLUDED.metadata;
        """,
        (status, duration_sec, meta_json),
    )
    conn.commit()

def ping_external_watchdog(url=HEALTHCHECK_URL):
    """
    Надсилає HTTP GET пінг на зовнішній монітор (Healthchecks.io / Cronitor), якщо задано URL.
    """
    if not url:
        return False
    try:
        r = requests.get(url, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"External watchdog ping err: {e}")
        return False

def check_watchdog_before_run(cur, conn):
    """
    Виконується на початку main.py: перевіряє простій та прострочені контрольні точки.
    Повертає рядок алерта для відправки в TG (якщо є проблеми) або None.
    """
    try:
        ensure_heartbeat_table(cur, conn)
        cur.execute("SELECT last_ping_at FROM system_heartbeat WHERE service_name='StatMonitor';")
        row = cur.fetchone()
        last_ping = row[0] if row else None

        stale_info = detect_stale_heartbeat(last_ping)
        missed = detect_missed_checkpoints(cur, conn)

        if stale_info or missed:
            return format_watchdog_alert(missed, stale_info)
    except Exception as e:
        print(f"Watchdog check err: {e}")
    return None

if __name__ == "__main__":
    conn = get_db()
    if not conn:
        print("SUPABASE_DB_URL не знайдено.")
        sys.exit(1)
    cur = conn.cursor()
    ensure_heartbeat_table(cur, conn)
    alert = check_watchdog_before_run(cur, conn)
    if alert:
        print("Watchdog знайшов проблеми:\n", alert)
    else:
        print("Watchdog: стан планувальника в нормі.")
    record_heartbeat(cur, conn, duration_sec=1.5, status="OK", metadata={"cli": True})
    print("Heartbeat оновлено.")
    cur.close()
    conn.close()
