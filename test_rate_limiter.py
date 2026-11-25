import unittest
from datetime import datetime, timezone, timedelta
from statmonitor.limiter import (
    get_budget_mode,
    classify_sports_urgency,
    filter_sports_to_poll,
    record_poll_success,
    compute_sports_quota_breakdown,
)

class MockCursor:
    def __init__(self, fetchall_data=None):
        self.fetchall_data = fetchall_data or []
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.fetchall_data

    def fetchone(self):
        return self.fetchall_data[0] if self.fetchall_data else None

class MockConn:
    def commit(self):
        pass

class TestRateLimiter(unittest.TestCase):
    def test_budget_modes(self):
        self.assertEqual(get_budget_mode(450), "NORMAL")
        self.assertEqual(get_budget_mode("300"), "NORMAL")
        self.assertEqual(get_budget_mode(200), "ECO")
        self.assertEqual(get_budget_mode("120"), "ECO")
        self.assertEqual(get_budget_mode(50), "ECO")
        self.assertEqual(get_budget_mode(49), "CRITICAL")
        self.assertEqual(get_budget_mode("15"), "CRITICAL")
        self.assertEqual(get_budget_mode(0), "CRITICAL")
        self.assertEqual(get_budget_mode(None), "NORMAL")
        self.assertEqual(get_budget_mode("invalid"), "NORMAL")

    def test_classify_sports_urgency(self):
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        cur = MockCursor(fetchall_data=[
            ("soccer_epl", now + timedelta(hours=2)),       # HOT (< 6h)
            ("basketball_nba", now + timedelta(hours=10)),  # WARM (6..24h)
            ("tennis_atp", now + timedelta(hours=36)),      # COLD (> 24h)
        ])

        sports_keys = ["soccer_epl", "basketball_nba", "tennis_atp", "soccer_spain_la_liga"]
        tiers = classify_sports_urgency(cur, sports_keys, now_utc=now)

        self.assertEqual(tiers["soccer_epl"], "HOT")
        self.assertEqual(tiers["basketball_nba"], "WARM")
        self.assertEqual(tiers["tennis_atp"], "COLD")
        self.assertEqual(tiers["soccer_spain_la_liga"], "COLD") # немає подій в БД

    def test_filter_sports_to_poll(self):
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        
        # Симулюємо події та історію опитувань
        cur = MockCursor()
        conn = MockConn()

        # Перший виклик: таблиця порожня, всі ліги повинні бути додані
        cur.fetchall_data = [] # Немає записів в history
        sports_map = {
            "soccer_epl": "EPL",
            "basketball_nba": "NBA",
        }
        selected, mode, tiers = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=300, now_utc=now)
        self.assertEqual(mode, "NORMAL")
        self.assertIn("soccer_epl", selected)
        self.assertIn("basketball_nba", selected)

    def test_filter_sports_recently_polled(self):
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        # Опитування було 10 хвилин тому (< 25 хв для HOT)
        cur = MockCursor()
        conn = MockConn()

        # Mock: подія через 2 год (HOT), але опитана 10 хв тому
        # 1-й fetchall (events):
        def custom_fetchall():
            if "FROM events" in cur.queries[-1][0]:
                return [("soccer_epl", now + timedelta(hours=2))]
            elif "FROM sports_poll_log" in cur.queries[-1][0]:
                return [("soccer_epl", now - timedelta(minutes=10))]
            return []

        cur.fetchall = custom_fetchall
        sports_map = {"soccer_epl": "EPL"}
        selected, mode, tiers = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=300, now_utc=now)
        # Має бути пропущено, бо минуло лише 10 хв
        self.assertEqual(len(selected), 0)

    def test_filter_sports_critical_mode(self):
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        cur = MockCursor()
        conn = MockConn()

        def custom_fetchall():
            if "FROM events" in cur.queries[-1][0]:
                return [
                    ("soccer_epl", now + timedelta(hours=2)),      # HOT
                    ("basketball_nba", now + timedelta(hours=14)), # WARM
                ]
            elif "FROM sports_poll_log" in cur.queries[-1][0]:
                # Обидва опитувались 60 хв тому
                return [
                    ("soccer_epl", now - timedelta(minutes=60)),
                    ("basketball_nba", now - timedelta(minutes=60)),
                ]
            return []

        cur.fetchall = custom_fetchall
        sports_map = {"soccer_epl": "EPL", "basketball_nba": "NBA"}
        # Залишок 20 кредитів -> CRITICAL режим
        selected, mode, tiers = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=20, now_utc=now)
        self.assertEqual(mode, "CRITICAL")
        # Тільки HOT ліга має потрапити, WARM відсікається в режимі CRITICAL
        self.assertIn("soccer_epl", selected)
        self.assertNotIn("basketball_nba", selected)

    def test_record_poll_success(self):
        cur = MockCursor()
        conn = MockConn()
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        record_poll_success(cur, conn, ["soccer_epl"], tiers={"soccer_epl": "HOT"}, now_utc=now)
        self.assertEqual(len(cur.queries), 1)
        self.assertIn("INSERT INTO sports_poll_log", cur.queries[0][0])
        self.assertIn("ON CONFLICT (sport) DO UPDATE", cur.queries[0][0])

    def test_compute_sports_quota_breakdown(self):
        poll_records = [
            {"sport": "soccer_epl", "tier": "HOT", "last_polled_at": "2026-11-20T12:00:00Z", "poll_count": 600},
            {"sport": "soccer_spain_la_liga", "tier": "WARM", "last_polled_at": "2026-11-20T11:00:00Z", "poll_count": 120},
            {"sport": "basketball_nba", "tier": "HOT", "last_polled_at": "2026-11-20T12:30:00Z", "poll_count": 340},
            {"sport": "tennis_atp", "tier": "COLD", "last_polled_at": "2026-11-20T10:00:00Z", "poll_count": 150},
            {"sport": "icehockey_nhl", "tier": "WARM", "last_polled_at": "2026-11-20T09:00:00Z", "poll_count": 50},
        ]
        cfg = {
            "leagues": [
                {"key": "soccer_epl", "title": "Англія (АПЛ)", "category": "soccer"},
                {"key": "soccer_spain_la_liga", "title": "Іспанія (Ла Ліга)", "category": "soccer"},
                {"key": "basketball_nba", "title": "США (NBA)", "category": "basketball"},
                {"key": "tennis_atp", "title": "Теніс (ATP)", "category": "tennis"},
                {"key": "icehockey_nhl", "title": "США/Канада (NHL)", "category": "icehockey"},
            ]
        }
        res = compute_sports_quota_breakdown(poll_records, leagues_config=cfg, total_monthly_limit=2500)
        self.assertEqual(res["total_polls"], 1260)
        self.assertAlmostEqual(res["quota_used_pct"], 50.4, places=1)
        
        cats = res["categories"]
        # Футбол має бути на першому місці
        self.assertEqual(cats[0]["category_name"], "⚽ Футбол")
        self.assertEqual(cats[0]["poll_count"], 720)
        self.assertAlmostEqual(cats[0]["pct_of_used"], 57.1, places=1)
        self.assertAlmostEqual(cats[0]["pct_of_limit"], 28.8, places=1)
        
        # Баскетбол на другому
        self.assertEqual(cats[1]["category_name"], "🏀 Баскетбол")
        self.assertEqual(cats[1]["poll_count"], 340)

    def test_updated_tier_intervals(self):
        now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
        cur = MockCursor()
        conn = MockConn()

        def make_fetchall(hot_m, warm_m, cold_m):
            def _fn():
                if "FROM events" in cur.queries[-1][0]:
                    return [
                        ("soccer_epl", now + timedelta(hours=2)),       # HOT
                        ("basketball_nba", now + timedelta(hours=10)),  # WARM
                        ("tennis_atp", now + timedelta(hours=36)),      # COLD
                    ]
                elif "FROM sports_poll_log" in cur.queries[-1][0]:
                    return [
                        ("soccer_epl", now - timedelta(minutes=hot_m)),
                        ("basketball_nba", now - timedelta(minutes=warm_m)),
                        ("tennis_atp", now - timedelta(minutes=cold_m)),
                    ]
                return []
            return _fn

        sports_map = {"soccer_epl": "EPL", "basketball_nba": "NBA", "tennis_atp": "ATP"}

        # NORMAL (>200): HOT=45, WARM=90, COLD=240 -> 44/89/239 хв пропуск, 45/90/240 хв опитування
        cur.fetchall = make_fetchall(44, 89, 239)
        sel, mode, _ = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=300, now_utc=now)
        self.assertEqual(mode, "NORMAL")
        self.assertEqual(sel, {})

        cur.fetchall = make_fetchall(45, 90, 240)
        sel, _, _ = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=300, now_utc=now)
        self.assertEqual(set(sel.keys()), {"soccer_epl", "basketball_nba", "tennis_atp"})

        # ECO (50..200): HOT=60, WARM=120, COLD=360
        cur.fetchall = make_fetchall(55, 110, 350)
        sel, mode, _ = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=100, now_utc=now)
        self.assertEqual(mode, "ECO")
        self.assertEqual(sel, {})

        cur.fetchall = make_fetchall(60, 120, 360)
        sel, _, _ = filter_sports_to_poll(cur, conn, sports_map, remaining_credits=100, now_utc=now)
        self.assertEqual(set(sel.keys()), {"soccer_epl", "basketball_nba", "tennis_atp"})

if __name__ == "__main__":
    unittest.main()
