from datetime import datetime, timezone, timedelta
from sys_watchdog import detect_stale_heartbeat, format_watchdog_alert

def test_detect_stale_heartbeat_alert():
    # Симуляція денного часу: 15:00 UTC (17:00 Київ)
    now = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
    # Попередній пінг був 180 хвилин тому (12:00 UTC) -> перевищує 150 хв
    last_ping = now - timedelta(minutes=180)

    res = detect_stale_heartbeat(last_ping, now_utc=now, max_gap_minutes=150)
    assert res is not None
    assert res["gap_minutes"] == 180
    assert "14:00" in res["last_ping_kyiv"] or "12:00" in res["last_ping_kyiv"] or ":" in res["last_ping_kyiv"]

def test_detect_stale_heartbeat_normal():
    now = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
    # Попередній пінг був 75 хвилин тому -> норма
    last_ping = now - timedelta(minutes=75)

    res = detect_stale_heartbeat(last_ping, now_utc=now, max_gap_minutes=150)
    assert res is None

def test_format_watchdog_alert():
    stale_info = {"gap_minutes": 190, "last_ping_kyiv": "16.11 12:00"}
    missed = [{
        "id": 1,
        "target_time": datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc),
        "trigger_type": "PRE_MATCH",
        "description": "Перед грою: Chelsea - Arsenal",
        "delay_minutes": 45,
    }]

    alert_text = format_watchdog_alert(missed_points=missed, stale_info=stale_info)
    assert "Watchdog Alert" in alert_text
    assert "190 хв" in alert_text
    assert "Chelsea - Arsenal" in alert_text
    assert "45 хв" in alert_text

def test_detect_missed_checkpoints_dedup():
    from sys_watchdog import detect_missed_checkpoints
    class MockCursor:
        def __init__(self):
            self.queries = []
        def execute(self, q, params=None):
            self.queries.append((q, params))
        def fetchone(self):
            return (1,) # table exists
        def fetchall(self):
            t_old = datetime(2026, 11, 16, 14, 45, tzinfo=timezone.utc)
            # 3 дублікати одного матчу
            return [
                (101, t_old, "PRE_MATCH", "Перед грою: Alcaraz - Tiafoe"),
                (102, t_old, "PRE_MATCH", "Перед грою: Alcaraz - Tiafoe"),
                (103, t_old, "PRE_MATCH", "Перед грою: Alcaraz - Tiafoe"),
            ]
    class MockConn:
        def commit(self): pass

    cur = MockCursor()
    conn = MockConn()
    t_now = datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc)
    missed = detect_missed_checkpoints(cur, conn, now_utc=t_now, threshold_minutes=25)
    # Повинна залишитися лише 1 дедуплікована точка замість 3
    assert len(missed) == 1
    assert missed[0]["description"] == "Перед грою: Alcaraz - Tiafoe"

if __name__ == "__main__":
    test_detect_stale_heartbeat_alert()
    test_detect_stale_heartbeat_normal()
    test_format_watchdog_alert()
    test_detect_missed_checkpoints_dedup()
    print("Всі тести watchdog успішно пройдено!")
