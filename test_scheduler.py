from datetime import datetime, timezone, timedelta
from scheduler import cluster_events, generate_schedule_points, format_schedule_for_tg

def test_cluster_events():
    t0 = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 16, 18, 15, tzinfo=timezone.utc) # +15 min (same cluster)
    t2 = datetime(2026, 11, 16, 18, 20, tzinfo=timezone.utc) # +5 min (same cluster)
    t3 = datetime(2026, 11, 16, 21, 0, tzinfo=timezone.utc)  # +160 min (new cluster)

    events = [
        {"id": "e1", "commence_time": t0, "match_name": "Match 1"},
        {"id": "e2", "commence_time": t1, "match_name": "Match 2"},
        {"id": "e3", "commence_time": t2, "match_name": "Match 3"},
        {"id": "e4", "commence_time": t3, "match_name": "Match 4"},
    ]

    clusters = cluster_events(events, threshold_minutes=25)
    assert len(clusters) == 2
    assert len(clusters[0]) == 3
    assert len(clusters[1]) == 1
    assert clusters[0][0]["id"] == "e1"
    assert clusters[1][0]["id"] == "e4"

def test_generate_schedule_points():
    now = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
    kickoff = datetime(2026, 11, 16, 19, 0, tzinfo=timezone.utc)

    events = [
        {"id": "ev_arsenal", "commence_time": kickoff, "match_name": "Arsenal - Chelsea"}
    ]
    pending_bets = [
        {"id": 1, "event_id": "ev_arsenal", "commence_time": kickoff, "match_name": "Arsenal - Chelsea"}
    ]

    points = generate_schedule_points(events, pending_bets, now_utc=now)
    assert len(points) == 2

    # PRE_MATCH: kickoff - 15 min -> 18:45
    pre_point = points[0]
    assert pre_point["trigger_type"] == "PRE_MATCH"
    assert pre_point["target_time"] == datetime(2026, 11, 16, 18, 45, tzinfo=timezone.utc)

    # SETTLE: kickoff + 115 min -> 20:55
    settle_point = points[1]
    assert settle_point["trigger_type"] == "SETTLE"
    assert settle_point["target_time"] == datetime(2026, 11, 16, 20, 55, tzinfo=timezone.utc)

def test_format_schedule_for_tg():
    t_target = datetime(2026, 11, 16, 18, 45, tzinfo=timezone.utc)
    points = [{
        "target_time": t_target,
        "trigger_type": "PRE_MATCH",
        "description": "Перед грою: Arsenal - Chelsea"
    }]
    msg = format_schedule_for_tg(points)
    assert "Наступні контрольні точки моніторингу" in msg
    assert "20:45" in msg  # 18:45 UTC is 20:45 Kyiv time (UTC+2)
    assert "Arsenal - Chelsea" in msg

def test_mark_checkpoints_executed():
    from scheduler import mark_checkpoints_executed
    class MockCursor:
        def __init__(self):
            self.queries = []
        def execute(self, q, params=None):
            self.queries.append((q, params))
    class MockConn:
        def commit(self): pass

    cur = MockCursor()
    conn = MockConn()
    t_now = datetime(2026, 11, 16, 14, 50, tzinfo=timezone.utc)
    mark_checkpoints_executed(cur, conn, now_utc=t_now, window_minutes=35)
    assert len(cur.queries) == 1
    assert "UPDATE scheduler_plan" in cur.queries[0][0]
    assert "SET status = 'EXECUTED'" in cur.queries[0][0]

if __name__ == "__main__":
    test_cluster_events()
    test_generate_schedule_points()
    test_format_schedule_for_tg()
    test_mark_checkpoints_executed()
    print("Всі юніт-тести планувальника успішно пройдено!")
