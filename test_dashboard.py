import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from dashboard import compute_metrics, INITIAL_BANKROLL, format_verdict_markdown, format_kyiv_time, get_dashboard_odds_quota, get_sport_icon

class TestDashboard(unittest.TestCase):
    def test_get_sport_icon(self):
        self.assertEqual(get_sport_icon("soccer_epl"), "⚽")
        self.assertEqual(get_sport_icon("soccer_spain_la_liga"), "⚽")
        self.assertEqual(get_sport_icon("basketball_nba"), "🏀")
        self.assertEqual(get_sport_icon("tennis_atp_finals"), "🎾")
        self.assertEqual(get_sport_icon("icehockey_nhl"), "🏒")
        self.assertEqual(get_sport_icon("mma_mixed_martial_arts"), "🥊")
        self.assertEqual(get_sport_icon("americanfootball_nfl"), "🏈")
        self.assertEqual(get_sport_icon("baseball_mlb"), "⚾")
        self.assertEqual(get_sport_icon("unknown_sport"), "🏆")
    def test_format_verdict_markdown(self):
        raw_html = "📌 <b>Коротка ставка:</b> Ф2 (+1.5)<br>🎯 <b>Рекомендована ставка:</b> Ставити &amp; вигравати!"
        formatted = format_verdict_markdown(raw_html)
        self.assertNotIn("<b>", formatted)
        self.assertNotIn("</b>", formatted)
        self.assertNotIn("<br>", formatted)
        self.assertIn("**Коротка ставка:**", formatted)
        self.assertNotIn("&amp;", formatted)
        self.assertIn("&", formatted)

    def test_format_kyiv_time(self):
        # 14:45 UTC у листопаді (EET, UTC+2) -> 16:45
        dt_utc = datetime(2026, 11, 17, 14, 45, tzinfo=timezone.utc)
        self.assertEqual(format_kyiv_time(dt_utc), "17.11 16:45")
        
        # Рядок ISO UTC
        self.assertEqual(format_kyiv_time("2026-11-17T14:45:00Z"), "17.11 16:45")
        self.assertEqual(format_kyiv_time("2026-11-17 14:45:00+00:00"), "17.11 16:45")
        
        # Порожні значення
        self.assertEqual(format_kyiv_time(None), "")
        self.assertEqual(format_kyiv_time(""), "")

    def test_compute_metrics_empty(self):
        m = compute_metrics([])
        self.assertEqual(m["current_bank"], INITIAL_BANKROLL)
        self.assertEqual(m["net_profit"], 0.0)
        self.assertEqual(m["roi_pct"], 0.0)
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["total_bets"], 0)

    def test_compute_metrics_with_bets(self):
        data = [
            {"status": "WON", "stake_uah": 300.0, "profit_uah": 270.0},
            {"status": "LOST", "stake_uah": 200.0, "profit_uah": -200.0},
            {"status": "VOID", "stake_uah": 100.0, "profit_uah": 0.0},
            {"status": "PENDING", "stake_uah": 250.0, "profit_uah": 0.0},
        ]
        m = compute_metrics(data)

        # Net profit: 270 - 200 = 70.0 грн
        self.assertEqual(m["net_profit"], 70.0)
        # Bankroll: 10000 + 70 = 10070.0 грн
        self.assertEqual(m["current_bank"], 10070.0)
        # Turnover: 300 + 200 + 100 = 600 грн
        self.assertEqual(m["turnover"], 600.0)
        # ROI: (70 / 600) * 100% = 11.67%
        self.assertEqual(round(m["roi_pct"], 2), 11.67)
        # Win rate: 1 won / (1 won + 1 lost) = 50.0%
        self.assertEqual(m["win_rate"], 50.0)
        self.assertEqual(m["total_bets"], 4)
        self.assertEqual(m["pending"], 1)

    def test_get_dashboard_odds_quota_from_heartbeat(self):
        # 1. Fallback до heartbeat metadata (якщо live API не налаштовано)
        mock_hb = [
            {
                "service_name": "StatMonitor",
                "last_status": "OK",
                "metadata": {
                    "odds_quota": {
                        "primary": {"remaining": 450, "used": 50, "limit": 500, "status": "active"},
                        "reserve": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
                        "reserve1": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
                        "reserve2": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
                        "reserve3": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
                        "total_remaining": 2450,
                        "total_limit": 2500,
                        "active_key": "primary"
                    }
                }
            }
        ]
        with patch.dict("os.environ", {}, clear=True):
            quota, source = get_dashboard_odds_quota(mock_hb)
            self.assertEqual(source, "heartbeat")
            self.assertIsNotNone(quota)
            self.assertEqual(quota["total_remaining"], 2450)
            self.assertEqual(quota["total_limit"], 2500)
            self.assertEqual(quota["active_key"], "primary")

    def test_get_dashboard_odds_quota_live(self):
        # 2. Live API перевірка за наявності ключів
        mock_quota = {
            "primary": {"remaining": 420, "used": 80, "limit": 500, "status": "active"},
            "reserve": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
            "reserve1": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
            "reserve2": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
            "reserve3": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
            "total_remaining": 2420,
            "total_limit": 2500,
            "active_key": "primary",
        }
        with patch.dict("os.environ", {"ODDS_API_KEY": "test_key_12345"}):
            with patch("statmonitor.fetcher.check_odds_api_quota", return_value=mock_quota):
                quota, source = get_dashboard_odds_quota(None)
                self.assertEqual(source, "live")
                self.assertEqual(quota["total_remaining"], 2420)
                self.assertEqual(quota["total_limit"], 2500)

    def test_get_dashboard_system_errors(self):
        from dashboard import get_dashboard_system_errors
        # Тестуємо поведінку при відсутності БД або mock-з'єднанні
        with patch("dashboard.get_db_connection", return_value=(None, None)):
            res = get_dashboard_system_errors("fake_url")
            self.assertEqual(res, [])

        mock_conn = MagicMock()
        mock_cur = MagicMock(spec=["execute", "fetchall", "fetchone", "description", "close"])
        mock_cur.fetchall.return_value = [
            (1, "odds_api", "ERROR", "HTTP_422", "Invalid market btts", None, datetime.now(timezone.utc))
        ]
        mock_conn.cursor.return_value = mock_cur
        with patch("dashboard.get_db_connection", return_value=(mock_conn, None)):
            res = get_dashboard_system_errors("fake_url")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["source"], "odds_api")
            self.assertEqual(res[0]["error_code"], "HTTP_422")

if __name__ == "__main__":
    unittest.main()
