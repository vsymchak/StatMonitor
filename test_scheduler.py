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
    assert len(points) >= 2

    # PRE_MATCH: kickoff - 15 min -> 18:45
    pre_point = points[0]
    assert pre_point["trigger_type"] == "PRE_MATCH"
    assert pre_point["target_time"] == datetime(2026, 11, 16, 18, 45, tzinfo=timezone.utc)

    # SETTLE: періодично кожні 3 год (перший слот >= kickoff + 3h = 22:00 -> 00:00 UTC)
    settle_points = [p for p in points if p["trigger_type"] == "SETTLE"]
    assert len(settle_points) >= 1
    assert settle_points[0]["target_time"] == datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)

def test_generate_schedule_points_no_pending_bets_no_noise():
    now = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
    kickoff = datetime(2026, 11, 16, 19, 0, tzinfo=timezone.utc)

    # Матч є в базі, але активної ставки немає
    events = [
        {"id": "ev_toronto", "commence_time": kickoff, "match_name": "Toronto Raptors - New York Knicks"}
    ]
    pending_bets = []

    # За замовчуванням точки не повинні генеруватися, щоб уникнути шуму та хибних тривог
    points = generate_schedule_points(events, pending_bets, now_utc=now, require_pending=True)
    assert len(points) == 0

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

def test_should_execute_pipeline():
    from scheduler import should_execute_pipeline

    class SmartMockCursor:
        def __init__(self, checkpoint=None, due_settle=None, last_ping=None, next_point=None):
            self.checkpoint = checkpoint
            self.due_settle = due_settle
            self.last_ping = last_ping
            self.next_point = next_point
            self.last_query = ""

        def execute(self, q, params=None):
            self.last_query = q

        def fetchone(self):
            if "FROM scheduler_plan" in self.last_query and "target_time >=" in self.last_query:
                return self.checkpoint
            if "FROM paper_bets" in self.last_query:
                return self.due_settle
            if "FROM system_heartbeat" in self.last_query:
                return (self.last_ping,) if self.last_ping else None
            if "FROM scheduler_plan" in self.last_query and "target_time >" in self.last_query:
                return self.next_point
            return None

    class MockConn:
        def commit(self): pass

    # 1. Ручний запуск завжди виконується
    run, reason, mode = should_execute_pipeline(None, None, trigger_source="manual")
    assert run is True
    assert mode == "FORCE"

    # 2. cron_5m з контрольною точкою розкладу (PRE_MATCH)
    cur = SmartMockCursor(
        checkpoint=(1, "PRE_MATCH", "Перед грою Arsenal", datetime.now(timezone.utc)),
    )
    run, reason, mode = should_execute_pipeline(cur, MockConn(), trigger_source="cron_5m")
    assert run is True
    assert mode == "PRE_MATCH"

    # 3. cron_5m з матчем, готовим до розрахунку (SETTLE кожні 3 год)
    cur = SmartMockCursor(
        due_settle=(10, "Arsenal - Chelsea", datetime.now(timezone.utc) - timedelta(hours=4)),
        last_ping=datetime.now(timezone.utc) - timedelta(hours=3, minutes=10),
    )
    run, reason, mode = should_execute_pipeline(cur, MockConn(), trigger_source="cron_5m")
    assert run is True
    assert mode == "SETTLE"

    # 4. cron_5m з періодичним оновленням ліній (>80 хв)
    cur = SmartMockCursor(
        last_ping=datetime.now(timezone.utc) - timedelta(minutes=95)
    )
    run, reason, mode = should_execute_pipeline(cur, MockConn(), trigger_source="cron_5m")
    assert run is True
    assert mode == "DISCOVERY"

    # 5. cron_5m без подій та зі свіжим сервісом -> холостий тік (SKIP, 0 витрат квоти)
    cur = SmartMockCursor(
        last_ping=datetime.now(timezone.utc) - timedelta(minutes=10),
        next_point=(datetime.now(timezone.utc) + timedelta(minutes=40), "Перед грою Lakers")
    )
    run, reason, mode = should_execute_pipeline(cur, MockConn(), trigger_source="cron_5m")
    assert run is False
    assert mode == "SKIP"
    assert "Немає завдань у поточному вікні" in reason

if __name__ == "__main__":
    test_cluster_events()
    test_generate_schedule_points()
    test_generate_schedule_points_no_pending_bets_no_noise()
    test_format_schedule_for_tg()
    test_mark_checkpoints_executed()
    test_should_execute_pipeline()
    print("Всі юніт-тести планувальника успішно пройдено!")
