import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from statmonitor.config import INITIAL_BANKROLL, KYIV_TZ, SPORTS_MAP, TARGET_SPORTS
from statmonitor.notifier import esc, fmt_kyiv
from statmonitor.database import pick, pick_v
from statmonitor.ai import extract_short_pick
from statmonitor.paper_trading import format_pick, eval_outcome
import main

class TestModularDecomposition(unittest.TestCase):
    def test_config_constants(self):
        self.assertEqual(INITIAL_BANKROLL, 10000.00)
        self.assertIsNotNone(KYIV_TZ)
        self.assertGreater(len(SPORTS_MAP), 10)
        self.assertIn("soccer_epl", TARGET_SPORTS)

    def test_notifier_helpers(self):
        self.assertEqual(esc("Arsenal & Chelsea <3>"), "Arsenal &amp; Chelsea &lt;3&gt;")
        dt_utc = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
        self.assertIn("12:00", fmt_kyiv(dt_utc))

    def test_database_pick_helpers(self):
        cols = {"event_id", "created_at", "price"}
        self.assertEqual(pick(cols, ("match_id", "event_id")), "event_id")
        self.assertIsNone(pick(cols, ("missing_col",)))

        d = {"status": "WON", "stake": 250}
        self.assertEqual(pick_v(d, ("st", "stake")), 250)
        self.assertEqual(pick_v(d, ("not_there",), default=10), 10)

    def test_ai_extract_short_pick(self):
        verdict = (
            "📌 **Коротка ставка:** Ф2 (+1.5)\n"
            "🎯 **Рекомендована ставка:** Брати фору гостей.\n"
            "🏥 **Склади:** Основні гравці готові."
        )
        self.assertEqual(extract_short_pick(verdict, fallback="П1"), "Ф2 (+1.5)")

        skip_verdict = (
            "📌 **Коротка ставка:** Пропустити\n"
            "🎯 **Рекомендована ставка:** Пропустити матч через високу маржу."
        )
        self.assertEqual(extract_short_pick(skip_verdict, fallback="П1"), "⏭ Пропустити матч")

    def test_paper_trading_format_and_eval(self):
        # 1. Totals
        pick_lbl = format_pick("totals", "Over", 2.5, "Arsenal - Chelsea")
        self.assertEqual(pick_lbl, "ТБ 2.5")

        # 2. Spreads
        pick_lbl_sp = format_pick("spreads", "Arsenal", -1.0, "Arsenal - Chelsea")
        self.assertEqual(pick_lbl_sp, "Ф1 (-1)")

        # 3. Outcomes
        self.assertEqual(eval_outcome("ТБ 2.5", "Arsenal - Chelsea", 2, 1), "WON")
        self.assertEqual(eval_outcome("ТБ 2.5", "Arsenal - Chelsea", 1, 1), "LOST")
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 2, 0), "WON")
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 2, 1), "VOID")
        self.assertEqual(eval_outcome("П1", "Arsenal - Chelsea", 2, 1), "WON")
        self.assertEqual(eval_outcome("П2", "Arsenal - Chelsea", 0, 1), "WON")

    def test_main_backward_compatibility(self):
        # Перевірка, що main.py продовжує експортувати ключові символи для зворотної сумісності
        self.assertTrue(hasattr(main, "get_db"))
        self.assertTrue(hasattr(main, "ensure_tables"))
        self.assertTrue(hasattr(main, "send_tg"))
        self.assertTrue(hasattr(main, "fmt_kyiv"))
        self.assertTrue(hasattr(main, "esc"))
        self.assertTrue(hasattr(main, "build_chart"))
        self.assertTrue(hasattr(main, "analyze_gemini"))
        self.assertTrue(hasattr(main, "place_paper_bet"))
        self.assertTrue(hasattr(main, "settle_and_report"))
        self.assertTrue(hasattr(main, "run_pipeline"))

    def test_pipeline_active_bets_deduplication(self):
        from unittest.mock import MagicMock, patch
        import statmonitor.pipeline as pipe

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.description = [
            ("event_id",), ("sport",), ("match_name",), ("commence_time",), ("bookmaker",),
            ("market_key",), ("outcome_name",), ("point",), ("start_odds",), ("current_odds",),
            ("drop_pct",), ("start_time",), ("last_time",)
        ]

        now = datetime.now(timezone.utc)
        row1 = ("ev_1", "soccer_epl", "Arsenal - Chelsea", now, "pinnacle", "h2h", "Arsenal", None, 2.2, 1.8, -18.0, now, now)
        row2 = ("ev_2", "soccer_epl", "Liverpool - City", now, "pinnacle", "h2h", "Liverpool", None, 2.5, 2.0, -20.0, now, now)

        mock_cur.fetchall.side_effect = [
            [row1, row2],
            [("ev_1",)],
            [], [], [], []
        ]

        with patch("statmonitor.pipeline.get_db", return_value=mock_conn), \
             patch("statmonitor.pipeline.ensure_tables"), \
             patch("statmonitor.pipeline.settle_and_report"), \
             patch("statmonitor.pipeline.resolve_alert_from_history", return_value=(None, None, None, None)), \
             patch("statmonitor.pipeline.get_cols", return_value={"event_id", "outcome", "price", "recorded_at"}), \
             patch("statmonitor.pipeline.build_chart", return_value=b"fake_chart"), \
             patch("statmonitor.pipeline.analyze_gemini", return_value="Аналіз"), \
             patch("statmonitor.pipeline.send_tg"), \
             patch("statmonitor.pipeline.send_photo") as mock_send_photo, \
             patch("statmonitor.pipeline.place_paper_bet"):
            pipe.check_alerts_and_notify({"soccer_epl": "EPL"})

            # ev_1 should be skipped, only ev_2 should proceed to photo/alert notification
            self.assertEqual(mock_send_photo.call_count, 1)
            caption = mock_send_photo.call_args[0][1]
            self.assertIn("Liverpool - City", caption)
            self.assertNotIn("Arsenal - Chelsea", caption)

    def test_check_odds_api_quota(self):
        from statmonitor.fetcher import check_odds_api_quota

        # 1. Три ключі активні (500 + 500 + 500 = 1500)
        mock_resp_p = MagicMock(status_code=200)
        mock_resp_p.headers = {"x-requests-remaining": "460", "x-requests-used": "40"}
        mock_resp_r = MagicMock(status_code=200)
        mock_resp_r.headers = {"x-requests-remaining": "500", "x-requests-used": "0"}
        mock_resp_r1 = MagicMock(status_code=200)
        mock_resp_r1.headers = {"x-requests-remaining": "500", "x-requests-used": "0"}

        with patch("requests.get", side_effect=[mock_resp_p, mock_resp_r, mock_resp_r1]):
            quota = check_odds_api_quota(api_key="key_primary_123", api_key_reserve="key_reserve_456", api_key_reserve1="key_reserve1_789")
            self.assertEqual(quota["primary"]["remaining"], 460)
            self.assertEqual(quota["primary"]["used"], 40)
            self.assertEqual(quota["reserve"]["remaining"], 500)
            self.assertEqual(quota["reserve1"]["remaining"], 500)
            self.assertEqual(quota["total_remaining"], 1460)
            self.assertEqual(quota["total_limit"], 1500)
            self.assertEqual(quota["active_key"], "primary")

        # 2. Основний вичерпано (402/429) -> резервний 1 активний
        mock_resp_p_err = MagicMock(status_code=429)
        with patch("requests.get", side_effect=[mock_resp_p_err, mock_resp_r, mock_resp_r1]):
            quota_rot = check_odds_api_quota(api_key="key_primary_123", api_key_reserve="key_reserve_456", api_key_reserve1="key_reserve1_789")
            self.assertEqual(quota_rot["primary"]["status"], "exhausted")
            self.assertEqual(quota_rot["primary"]["remaining"], 0)
            self.assertEqual(quota_rot["reserve"]["remaining"], 500)
            self.assertEqual(quota_rot["reserve1"]["remaining"], 500)
            self.assertEqual(quota_rot["active_key"], "reserve")

        # 3. Основний і перший резервний вичерпано -> резервний 2 (reserve1) активний
        mock_resp_r_err = MagicMock(status_code=402)
        with patch("requests.get", side_effect=[mock_resp_p_err, mock_resp_r_err, mock_resp_r1]):
            quota_rot2 = check_odds_api_quota(api_key="key_primary_123", api_key_reserve="key_reserve_456", api_key_reserve1="key_reserve1_789")
            self.assertEqual(quota_rot2["primary"]["status"], "exhausted")
            self.assertEqual(quota_rot2["reserve"]["status"], "exhausted")
            self.assertEqual(quota_rot2["reserve1"]["remaining"], 500)
            self.assertEqual(quota_rot2["active_key"], "reserve1")

    def test_get_sports_map_tennis_dynamic_discovery(self):
        from statmonitor.fetcher import get_sports_map

        mock_sports_api = [
            {"key": "soccer_epl", "title": "EPL", "active": True, "group": "Soccer"},
            {"key": "tennis_atp_brisbane", "title": "ATP Brisbane", "active": True, "group": "Tennis"},
            {"key": "tennis_davis_cup", "title": "Davis Cup", "active": True, "group": "Tennis"},
            {"key": "cricket_ipl", "title": "IPL", "active": True, "group": "Cricket"},
        ]
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = mock_sports_api

        with patch("requests.get", return_value=mock_resp), \
             patch("statmonitor.fetcher.API_KEY", "test_key"):
            s_map = get_sports_map()
            self.assertIn("soccer_epl", s_map)
            self.assertIn("tennis_atp_brisbane", s_map)
            self.assertIn("tennis_davis_cup", s_map)
            self.assertNotIn("cricket_ipl", s_map)

if __name__ == "__main__":
    unittest.main()
