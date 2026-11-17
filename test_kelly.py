import unittest
from unittest.mock import MagicMock
from statmonitor.paper_trading import calculate_kelly_fraction, place_paper_bet
from statmonitor.bot import cmd_bets

class TestKellyStaking(unittest.TestCase):
    def test_calculate_kelly_fraction_basic(self):
        # Odds 1.50 with 10% drop -> positive fraction within [0.01, 0.05]
        frac = calculate_kelly_fraction(1.50, drop_pct=10.0)
        self.assertGreaterEqual(frac, 0.01)
        self.assertLessEqual(frac, 0.05)
        # Low odds has higher Kelly fraction than high odds
        frac_low = calculate_kelly_fraction(1.45, drop_pct=12.0)
        frac_high = calculate_kelly_fraction(3.50, drop_pct=12.0)
        self.assertGreaterEqual(frac_low, frac_high)

    def test_calculate_kelly_fraction_no_drop(self):
        # Fallback when drop_pct is None
        frac = calculate_kelly_fraction(2.00)
        self.assertGreaterEqual(frac, 0.01)
        self.assertLessEqual(frac, 0.05)

    def test_calculate_kelly_fraction_clamping(self):
        # Large drop cannot exceed max_pct (0.05)
        frac_huge_drop = calculate_kelly_fraction(1.20, drop_pct=35.0)
        self.assertLessEqual(frac_huge_drop, 0.05)
        self.assertGreaterEqual(frac_huge_drop, 0.01)

        # High odds cannot go below min_pct (0.01)
        frac_tiny = calculate_kelly_fraction(15.0, drop_pct=2.0)
        self.assertEqual(frac_tiny, 0.01)

    def test_calculate_kelly_fraction_invalid_odds(self):
        self.assertEqual(calculate_kelly_fraction(1.00), 0.0)
        self.assertEqual(calculate_kelly_fraction(0.5), 0.0)
        self.assertEqual(calculate_kelly_fraction("invalid"), 0.0)
        self.assertEqual(calculate_kelly_fraction(None), 0.0)

    def test_place_paper_bet_with_kelly(self):
        cur = MagicMock()
        conn = MagicMock()

        # No existing bet, bank has 10000 avail
        cur.fetchone.side_effect = [
            None,                # SELECT existing
            (0.0, 0.0),          # prof, locked -> avail = 10000.0
        ]

        res = place_paper_bet(cur, conn, "ev_test_kelly", "soccer_epl", "Arsenal - Chelsea", "2026-11-17T20:00:00Z", "П1 (Arsenal)", 1.85, drop_pct=12.0)
        self.assertTrue(res)

        # Verify execute was called with kelly_pct
        calls = cur.execute.call_args_list
        insert_call = calls[-1]
        query_sql, params = insert_call[0]
        self.assertIn("paper_bets", query_sql)
        self.assertEqual(params[0], "ev_test_kelly")
        # Odds = 1.85
        self.assertEqual(params[5], 1.85)
        # Stake should be between 100 and 500 (1% to 5% of 10000)
        stake = params[6]
        self.assertGreaterEqual(stake, 100.0)
        self.assertLessEqual(stake, 500.0)
        # kelly_pct should be parameter 7
        if len(params) >= 8:
            kelly_pct = params[7]
            self.assertGreaterEqual(kelly_pct, 1.0)
            self.assertLessEqual(kelly_pct, 5.0)

    def test_cmd_bets_shows_kelly_pct(self):
        cur = MagicMock()
        cur.fetchone.return_value = (500.0,) # profit -> current_bank = 10500
        cur.fetchall.return_value = [
            (10, "Arsenal - Chelsea", "soccer_epl", "П1", 1.95, 300.0, "2026-11-17T20:00:00Z", 2.9)
        ]

        msg = cmd_bets(cur)
        self.assertIn("АКТИВНІ СТАВКИ В ГРІ", msg)
        self.assertIn("Arsenal - Chelsea", msg)
        self.assertIn("300.00 грн", msg)
        self.assertIn("2.9%", msg)
        self.assertIn("Келлі", msg)

if __name__ == "__main__":
    unittest.main()
