import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from statmonitor.novig import (
    calculate_walkaway_odds,
    estimate_walkaway_odds,
    format_walkaway_instruction,
)
from statmonitor.paper_trading import place_paper_bet
from statmonitor.real_bankroll import prepare_real_stakes_batch
from statmonitor.bot import cmd_bets, handle_command


class TestWalkawayOdds(unittest.TestCase):
    def test_calculate_walkaway_odds_basic(self):
        # fair_prob = 0.50, min_edge = 0.015 -> 1.015 / 0.50 = 2.03
        self.assertEqual(calculate_walkaway_odds(0.50, min_edge=0.015), 2.03)
        # fair_prob = 0.55, min_edge = 0.02 -> 1.02 / 0.55 = 1.8545 -> 1.85
        self.assertEqual(calculate_walkaway_odds(0.55, min_edge=0.02), 1.85)

    def test_calculate_walkaway_odds_invalid(self):
        self.assertIsNone(calculate_walkaway_odds(0.0))
        self.assertIsNone(calculate_walkaway_odds(1.0))
        self.assertIsNone(calculate_walkaway_odds(-0.1))
        self.assertIsNone(calculate_walkaway_odds("invalid"))
        self.assertIsNone(calculate_walkaway_odds(None))

    def test_estimate_walkaway_odds_with_fair_prob(self):
        # k = 2.10, fair_prob = 0.52 -> calculate_walkaway = 1.015 / 0.52 = 1.95
        w = estimate_walkaway_odds(2.10, fair_prob=0.52, min_edge=0.015)
        self.assertEqual(w, 1.95)
        self.assertLess(w, 2.10)

    def test_estimate_walkaway_odds_heuristic(self):
        # Heuristic fallback using drop_pct and confidence
        w = estimate_walkaway_odds(2.05, drop_pct=10.0, confidence=8)
        self.assertIsNotNone(w)
        self.assertIsInstance(w, float)
        self.assertLessEqual(w, 2.05)
        self.assertGreater(w, 1.50)

    def test_estimate_walkaway_odds_invalid_odds(self):
        self.assertIsNone(estimate_walkaway_odds(1.01))
        self.assertIsNone(estimate_walkaway_odds(0.95))
        self.assertIsNone(estimate_walkaway_odds("bad"))

    def test_format_walkaway_instruction(self):
        self.assertEqual(format_walkaway_instruction(1.88), "🎯 Ставити, поки коеф ≥ 1.88")
        self.assertEqual(format_walkaway_instruction(2.155), "🎯 Ставити, поки коеф ≥ 2.15")
        self.assertEqual(format_walkaway_instruction(None), "")
        self.assertEqual(format_walkaway_instruction(0), "")

    def test_place_paper_bet_records_walkaway(self):
        cur = MagicMock()
        conn = MagicMock()
        now = datetime.now(timezone.utc)
        # 1st query: check existing bet -> None
        # 2nd query: bankroll availability -> (0.0, 0.0)
        cur.fetchone.side_effect = [None, (0.0, 0.0)]

        res = place_paper_bet(
            cur, conn, "ev_walkaway_1", "soccer_epl", "Arsenal - Chelsea", now,
            "П1", 2.00, drop_pct=8.0, confidence=8, walkaway_odds=1.92
        )
        self.assertTrue(res)
        self.assertTrue(cur.execute.called)
        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO paper_bets" in str(c[0][0])]
        self.assertTrue(len(insert_calls) > 0)
        params = insert_calls[0][0][1]
        self.assertIn(1.92, params)

    def test_prepare_real_stakes_batch_includes_walkaway_odds(self):
        cur = MagicMock()
        # Mock ledger balance query
        cur.fetchone.return_value = (2500.0,)
        # Mock paper_bets row with walkaway_odds
        cur.fetchall.return_value = [
            (501, "Arsenal - Chelsea", "П1", 2.05, "soccer_epl", 2.5, 100.0, 2.05, True, 1.95)
        ]

        bal, proposals = prepare_real_stakes_batch(cur, [501])
        self.assertEqual(bal, 2500.0)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["walkaway_odds"], 1.95)
        self.assertEqual(proposals[0]["odds"], 2.05)

    def test_bot_bets_displays_walkaway(self):
        cur = MagicMock()
        now = datetime.now(timezone.utc)
        # Mock rows with 12 items: including walkaway_odds
        cur.fetchall.return_value = [
            (42, "Bayern - Dortmund", "soccer_germany", "ТБ 2.5", 1.95, 250.0, now, 2.5, 8, "Low", False, 1.88)
        ]

        res = cmd_bets(cur)
        self.assertIn("ID #42", res)
        self.assertIn("ТБ 2.5", res)
        self.assertIn("1.95", res)
        self.assertIn("Поріг: ≥ <code>1.88</code>", res)

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_bot_edit_odds_warns_on_breach_walkaway(self):
        cur = MagicMock()
        conn = MagicMock()

        # Update succeeds
        with patch("statmonitor.paper_trading.update_pending_bet_odds", return_value=(True, "OK", 2.00)):
            # Mock paper_bets row returning (m_name, pk, stk, k, walkaway_odds)
            cur.fetchone.return_value = ("Bayern - Dortmund", "ТБ 2.5", 250.0, 1.80, 1.92)

            msg, kb = handle_command("/edit_odds 42 1.80", 123456789, cur, conn)
            self.assertIn("Коефіцієнт успішно змінено", msg)
            self.assertIn("1.80", msg)
            self.assertIn("УВАГА (-EV)", msg)
            self.assertIn("1.92", msg)


if __name__ == "__main__":
    unittest.main()
