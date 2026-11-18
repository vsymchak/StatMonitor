import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from dashboard import compute_metrics, INITIAL_BANKROLL, format_verdict_markdown, format_kyiv_time, get_dashboard_odds_quota

class TestDashboard(unittest.TestCase):
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
                        "total_remaining": 950,
                        "total_limit": 1000,
                        "active_key": "primary"
                    }
                }
            }
        ]
        with patch.dict("os.environ", {}, clear=True):
            quota, source = get_dashboard_odds_quota(mock_hb)
            self.assertEqual(source, "heartbeat")
            self.assertIsNotNone(quota)
            self.assertEqual(quota["total_remaining"], 950)
            self.assertEqual(quota["active_key"], "primary")

    def test_get_dashboard_odds_quota_live(self):
        # 2. Live API перевірка за наявності ключів
        mock_quota = {
            "primary": {"remaining": 420, "used": 80, "limit": 500, "status": "active"},
            "reserve": {"remaining": 500, "used": 0, "limit": 500, "status": "standby"},
            "total_remaining": 920,
            "total_limit": 1000,
            "active_key": "primary",
        }
        with patch.dict("os.environ", {"ODDS_API_KEY": "test_key_12345"}):
            with patch("statmonitor.fetcher.check_odds_api_quota", return_value=mock_quota):
                quota, source = get_dashboard_odds_quota(None)
                self.assertEqual(source, "live")
                self.assertEqual(quota["total_remaining"], 920)

if __name__ == "__main__":
    unittest.main()
