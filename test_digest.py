import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import io

from statmonitor.chart import build_weekly_equity_chart
from statmonitor.digest import generate_weekly_digest
from statmonitor.bot import handle_command

class TestWeeklyDigest(unittest.TestCase):

    def test_build_weekly_equity_chart_empty(self):
        buf = build_weekly_equity_chart([])
        self.assertIsNone(buf)

    def test_build_weekly_equity_chart_valid(self):
        now = datetime.now(timezone.utc)
        pts = [
            (now - timedelta(days=5), 10000.0),
            (now - timedelta(days=3), 10800.0),
            (now - timedelta(days=1), 11500.0),
            (now, 12200.0),
        ]
        buf = build_weekly_equity_chart(pts, start_bank=10000.0, end_bank=12200.0)
        self.assertIsNotNone(buf)
        self.assertIsInstance(buf, io.BytesIO)
        self.assertGreater(len(buf.getvalue()), 1000)

    @patch("statmonitor.digest.send_photo")
    @patch("statmonitor.digest.send_tg")
    def test_generate_weekly_digest_no_bets(self, mock_tg, mock_photo):
        cur = MagicMock()
        conn = MagicMock()
        cur.description = [("status",)]
        cur.fetchone.return_value = None  # no previous digest
        cur.fetchall.return_value = []    # no bets

        res = generate_weekly_digest(cur, conn, force=False, send_telegram=True)
        self.assertEqual(res["status"], "NO_BETS")
        mock_photo.assert_not_called()
        mock_tg.assert_not_called()

    @patch("statmonitor.digest.send_photo")
    def test_generate_weekly_digest_skip_if_already_sent(self, mock_photo):
        cur = MagicMock()
        conn = MagicMock()
        cur.fetchone.return_value = ("SENT",)

        res = generate_weekly_digest(cur, conn, force=False, send_telegram=True)
        self.assertEqual(res["status"], "SKIPPED_ALREADY_SENT")
        mock_photo.assert_not_called()

    @patch("statmonitor.digest.send_photo")
    def test_generate_weekly_digest_success(self, mock_photo):
        cur = MagicMock()
        conn = MagicMock()
        cur.description = [
            ("id",), ("match_name",), ("sport",), ("pick_label",),
            ("odds",), ("stake_uah",), ("status",), ("profit_uah",),
            ("settled_at",), ("created_at",), ("closing_odds",),
            ("clv_pct",), ("beat_closing_line",)
        ]
        # First query: duplicate check (None = not sent yet)
        # Second query: fetch settled bets
        cur.fetchone.return_value = None
        now = datetime.now(timezone.utc)
        cur.fetchall.return_value = [
            (1, "Arsenal - Chelsea", "soccer_epl", "П1", 2.10, 1000.0, "WON", 1100.0, now - timedelta(days=2), now - timedelta(days=3), 1.95, 7.69, True),
            (2, "Real - Barca", "soccer_laliga", "ТБ 2.5", 1.85, 1000.0, "LOST", -1000.0, now - timedelta(days=1), now - timedelta(days=2), 1.90, -2.63, False),
            (3, "Sinner - Alcaraz", "tennis_atp", "П1", 2.00, 1000.0, "WON", 1000.0, now, now - timedelta(hours=5), 1.80, 11.11, True),
        ]

        res = generate_weekly_digest(cur, conn, force=True, send_telegram=True)
        self.assertEqual(res["status"], "SENT")
        m = res["metrics"]
        self.assertEqual(m["total_bets"], 3)
        self.assertEqual(m["won"], 2)
        self.assertEqual(m["lost"], 1)
        self.assertEqual(m["net_profit"], 1100.0)
        self.assertAlmostEqual(m["roi_pct"], 36.67, places=1)
        self.assertEqual(m["current_bank"], 11100.0)
        self.assertTrue(m["has_chart"])
        mock_photo.assert_called_once()
        cur.execute.assert_called()
        conn.commit.assert_called()

    @patch("statmonitor.bot.TG_CHAT_ID", "12345")
    @patch("statmonitor.digest.generate_weekly_digest")
    def test_bot_cmd_digest(self, mock_digest):
        mock_digest.return_value = {
            "status": "SENT",
            "week_key": "2026-W46",
            "metrics": {"net_profit": 1100.0, "roi_pct": 36.7},
        }
        cur = MagicMock()
        conn = MagicMock()
        resp, markup = handle_command("/digest", chat_id="12345", cur=cur, conn=conn)
        self.assertIn("Щотижневий графічний дайджест", resp)
        mock_digest.assert_called_once_with(cur, conn, force=True, send_telegram=True)

if __name__ == "__main__":
    unittest.main()
