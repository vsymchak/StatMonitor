import unittest
from unittest.mock import MagicMock
from statmonitor.novig import (
    calculate_novig_2way,
    calculate_novig_3way,
    calculate_edge_and_ev,
    calculate_walkaway_odds,
    calculate_real_stake,
)
from statmonitor.real_bankroll import (
    prepare_real_stakes_batch,
    apply_real_stakes_batch,
)

class MockCursor:
    def __init__(self, fetchall_data=None, fetchone_data=None):
        self.fetchall_data = fetchall_data or []
        self.fetchone_data = fetchone_data
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.fetchall_data

    def fetchone(self):
        return self.fetchone_data

class MockConn:
    def commit(self): pass
    def rollback(self): pass


class TestNovigEdge(unittest.TestCase):
    def test_calculate_novig_2way_equal_odds(self):
        res = calculate_novig_2way(1.90, 1.90)
        self.assertIsNotNone(res)
        self.assertEqual(res["fair_prob_1"], 0.50)
        self.assertEqual(res["fair_prob_2"], 0.50)
        self.assertEqual(res["fair_odds_1"], 2.0)
        self.assertEqual(res["fair_odds_2"], 2.0)
        self.assertAlmostEqual(res["margin_pct"], 5.26, delta=0.1)

    def test_calculate_novig_2way_unequal_odds(self):
        # 1.50 vs 2.70
        res = calculate_novig_2way(1.50, 2.70)
        self.assertIsNotNone(res)
        self.assertGreater(res["fair_prob_1"], res["fair_prob_2"])
        self.assertAlmostEqual(res["fair_prob_1"] + res["fair_prob_2"], 1.0, places=3)
        self.assertTrue(res["fair_odds_1"] > 1.50)
        self.assertTrue(res["fair_odds_2"] > 2.70)

    def test_calculate_novig_2way_invalid(self):
        self.assertIsNone(calculate_novig_2way(1.0, 2.0))
        self.assertIsNone(calculate_novig_2way("abc", 2.0))
        self.assertIsNone(calculate_novig_2way(None, None))

    def test_calculate_novig_3way(self):
        res = calculate_novig_3way(2.10, 3.40, 3.60)
        self.assertIsNotNone(res)
        p_sum = res["fair_prob_1"] + res["fair_prob_x"] + res["fair_prob_2"]
        self.assertAlmostEqual(p_sum, 1.0, places=3)
        self.assertGreater(res["margin_pct"], 0.0)

    def test_calculate_edge_and_ev_positive(self):
        # Offered 2.10 with fair prob 0.52 -> EV = (2.10 * 0.52) - 1 = 1.092 - 1 = +0.092 (+9.2%)
        edge, ev, is_pos = calculate_edge_and_ev(2.10, 0.52)
        self.assertTrue(is_pos)
        self.assertEqual(edge, 9.2)
        self.assertEqual(ev, 0.092)

    def test_calculate_edge_and_ev_negative(self):
        # Offered 1.85 with fair prob 0.50 -> EV = (1.85 * 0.50) - 1 = -0.075 (-7.5%)
        edge, ev, is_pos = calculate_edge_and_ev(1.85, 0.50)
        self.assertFalse(is_pos)
        self.assertEqual(edge, -7.5)
        self.assertEqual(ev, -0.075)

    def test_calculate_walkaway_odds(self):
        # Fair prob = 0.50, min edge = 2% (0.02) -> (1 + 0.02) / 0.50 = 2.04
        walkaway = calculate_walkaway_odds(0.50, min_edge=0.02)
        self.assertEqual(walkaway, 2.04)

    def test_calculate_real_stake_proportional_to_real_balance(self):
        # Real bankroll = 3,000 ₴ (NOT 10,000 ₴!)
        stake, pct, msg = calculate_real_stake(
            odds=1.95,
            real_balance=3000.0,
            fair_prob=0.55,
            fraction=0.10,
            min_stake=20.0,
            max_pct=0.05
        )
        self.assertEqual(msg, "OK")
        # Stake should be between min 20 ₴ and max 5% of 3000 (150 ₴)
        self.assertGreaterEqual(stake, 20.0)
        self.assertLessEqual(stake, 150.0)
        self.assertLessEqual(pct, 5.0)

    def test_calculate_real_stake_insufficient_balance(self):
        # Real balance 10 ₴ < min 20 ₴
        stake, pct, msg = calculate_real_stake(odds=1.95, real_balance=10.0, min_stake=20.0)
        self.assertEqual(stake, 0.0)
        self.assertIn("Недостатній баланс", msg)

    def test_calculate_real_stake_negative_ev_blocked(self):
        # Offered odds 1.80 against fair prob 0.50 -> EV < 0
        stake, pct, msg = calculate_real_stake(odds=1.80, real_balance=5000.0, fair_prob=0.50)
        self.assertEqual(stake, 0.0)
        self.assertIn("не має математичної переваги", msg)

    def test_calculate_real_stake_fallback_drop_pct(self):
        # Without fair_prob, uses drop_pct + confidence
        stake, pct, msg = calculate_real_stake(
            odds=1.90,
            real_balance=4000.0,
            drop_pct=8.5,
            confidence=8,
            fraction=0.10,
            min_stake=20.0,
            max_pct=0.05
        )
        self.assertEqual(msg, "OK")
        self.assertGreaterEqual(stake, 20.0)
        self.assertLessEqual(stake, 200.0) # 5% of 4000 is 200

    def test_prepare_real_stakes_batch(self):
        cur = MockCursor(
            fetchall_data=[
                (42, "Arsenal - Chelsea", "Ф1 (0)", 1.85, "soccer_epl", 0.025, None, None, False),
                (43, "Lakers - Jazz", "ТБ 224.5", 1.92, "basketball_nba", 0.030, None, None, False),
            ],
            fetchone_data=(5000.0,) # Real balance = 5000 ₴
        )
        bal, proposals = prepare_real_stakes_batch(cur, [42, 43])
        self.assertEqual(bal, 5000.0)
        self.assertEqual(len(proposals), 2)
        self.assertEqual(proposals[0]["id"], 42)
        self.assertGreaterEqual(proposals[0]["recommended_stake"], 20.0)
        self.assertLessEqual(proposals[0]["recommended_stake"], 250.0) # 5% of 5000

    def test_apply_real_stakes_batch(self):
        cur = MockCursor(
            fetchone_data=(42, "Arsenal - Chelsea", 1.85, 250.0)
        )
        conn = MockConn()
        configs = [
            {"id": 42, "real_stake": 120.0, "real_odds": 1.88}
        ]
        ok, count, total_staked, msg = apply_real_stakes_batch(cur, conn, configs)
        self.assertTrue(ok)
        self.assertEqual(count, 1)
        self.assertEqual(total_staked, 120.0)
        self.assertIn("120.00", msg)

if __name__ == "__main__":
    unittest.main()
