import unittest
from datetime import datetime, timezone

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

if __name__ == "__main__":
    unittest.main()
