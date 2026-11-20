"""
Unit tests for Quantitative Backtest Engine (SPEC-42).
"""

import unittest
from statmonitor.backtest import (
    run_backtest,
    run_benchmark_comparison,
    calculate_sharpe_ratio,
    calculate_sortino_ratio
)

class TestBacktestEngine(unittest.TestCase):
    def setUp(self):
        self.sample_bets = [
            {
                "id": 1,
                "match_name": "Team A - Team B",
                "pick_label": "П1",
                "odds": 2.00,
                "status": "WON",
                "confidence_score": 8,
                "kelly_pct": 2.5,
                "walkaway_odds": 1.90,
                "sport": "soccer_epl",
                "settled_at": "2026-11-10T15:00:00Z"
            },
            {
                "id": 2,
                "match_name": "Team C - Team D",
                "pick_label": "ТБ 2.5",
                "odds": 1.90,
                "status": "LOST",
                "confidence_score": 7,
                "kelly_pct": 2.0,
                "walkaway_odds": 1.85,
                "sport": "soccer_epl",
                "settled_at": "2026-11-11T17:00:00Z"
            },
            {
                "id": 3,
                "match_name": "Team E - Team F",
                "pick_label": "Ф1 (0)",
                "odds": 1.85,
                "status": "VOID",
                "confidence_score": 7,
                "kelly_pct": 1.5,
                "walkaway_odds": 1.80,
                "sport": "basketball_nba",
                "settled_at": "2026-11-12T19:00:00Z"
            },
            {
                "id": 4,
                "match_name": "Team G - Team H (Shadow)",
                "pick_label": "П2",
                "odds": 2.50,
                "status": "FILTERED",
                "shadow_status": "LOST",
                "is_shadow": True,
                "confidence_score": 5,
                "kelly_pct": 1.0,
                "walkaway_odds": 2.45,
                "sport": "soccer_spain",
                "settled_at": "2026-11-13T21:00:00Z"
            },
            {
                "id": 5,
                "match_name": "Team I - Team J",
                "pick_label": "П1",
                "odds": 1.70,
                "status": "WON",
                "confidence_score": 9,
                "kelly_pct": 3.0,
                "walkaway_odds": 1.75, # Note: odds < walkaway_odds (-EV)
                "sport": "basketball_nba",
                "settled_at": "2026-11-14T20:00:00Z"
            }
        ]

    def test_empty_backtest(self):
        res = run_backtest([], {"initial_bankroll": 5000.0})
        m = res["metrics"]
        self.assertEqual(m["initial_bankroll"], 5000.0)
        self.assertEqual(m["final_balance"], 5000.0)
        self.assertEqual(m["total_trades"], 0)
        self.assertEqual(m["net_profit"], 0.0)

    def test_flat_staking(self):
        cfg = {
            "initial_bankroll": 1000.0,
            "staking_model": "FLAT",
            "flat_amount": 100.0,
            "min_confidence": 7,
            "include_shadow": False,
            "enforce_walkaway": False
        }
        res = run_backtest(self.sample_bets, cfg)
        m = res["metrics"]
        # Executed: #1 (WON: +100 ₴), #2 (LOST: -100 ₴), #3 (VOID: 0 ₴), #5 (WON: +70 ₴)
        self.assertEqual(m["total_trades"], 4)
        self.assertEqual(m["won_count"], 2)
        self.assertEqual(m["lost_count"], 1)
        self.assertEqual(m["void_count"], 1)
        self.assertEqual(m["net_profit"], 70.0)
        self.assertEqual(m["final_balance"], 1070.0)
        self.assertAlmostEqual(m["win_rate"], 66.7, places=1) # 2 / 3

    def test_percent_bank_staking(self):
        cfg = {
            "initial_bankroll": 1000.0,
            "staking_model": "PERCENT_BANK",
            "percent_bank": 0.05, # 5% per bet
            "min_confidence": 7
        }
        res = run_backtest(self.sample_bets, cfg)
        m = res["metrics"]
        self.assertEqual(m["total_trades"], 4)
        self.assertGreater(m["final_balance"], 1000.0)
        self.assertGreater(len(res["equity_curve"]), 1)

    def test_kelly_staking_model(self):
        cfg = {
            "initial_bankroll": 3000.0,
            "staking_model": "KELLY_FRACTION",
            "fraction": 0.10,
            "min_confidence": 7
        }
        res = run_backtest(self.sample_bets, cfg)
        m = res["metrics"]
        self.assertEqual(m["total_trades"], 4)
        self.assertGreater(m["final_balance"], 3000.0)
        self.assertGreaterEqual(m["profit_factor"], 1.0)

    def test_include_shadow_bets(self):
        # Without shadow: 4 bets (conf >= 7)
        res_no_sh = run_backtest(self.sample_bets, {"min_confidence": 0, "include_shadow": False})
        self.assertEqual(res_no_sh["metrics"]["total_trades"], 4)

        # With shadow: 5 bets (including #4 with confidence 5 and status FILTERED)
        res_sh = run_backtest(self.sample_bets, {"min_confidence": 0, "include_shadow": True})
        self.assertEqual(res_sh["metrics"]["total_trades"], 5)
        self.assertEqual(res_sh["metrics"]["lost_count"], 2) # #2 and #4

    def test_enforce_walkaway_odds(self):
        # Bet #5 has odds 1.70 < walkaway 1.75
        res_walk = run_backtest(self.sample_bets, {"min_confidence": 7, "enforce_walkaway": True})
        # Bet #5 should be skipped
        self.assertEqual(res_walk["metrics"]["total_trades"], 3)
        trade_ids = [b["id"] for b in res_walk["executed_bets"]]
        self.assertNotIn(5, trade_ids)

    def test_drawdown_calculation(self):
        # Series of losses
        losing_bets = [
            {"id": 1, "odds": 2.0, "status": "LOST", "confidence_score": 8, "settled_at": "2026-11-01"},
            {"id": 2, "odds": 2.0, "status": "LOST", "confidence_score": 8, "settled_at": "2026-11-02"},
            {"id": 3, "odds": 2.0, "status": "LOST", "confidence_score": 8, "settled_at": "2026-11-03"},
        ]
        res = run_backtest(losing_bets, {"initial_bankroll": 1000.0, "staking_model": "FLAT", "flat_amount": 100.0})
        m = res["metrics"]
        self.assertEqual(m["final_balance"], 700.0)
        self.assertEqual(m["max_drawdown_uah"], 300.0)
        self.assertEqual(m["max_drawdown_pct"], 30.0)
        self.assertEqual(m["max_loss_streak"], 3)

    def test_sharpe_and_sortino_ratios(self):
        returns = [0.05, -0.02, 0.08, -0.01, 0.04]
        sharpe = calculate_sharpe_ratio(returns)
        sortino = calculate_sortino_ratio(returns)
        self.assertGreater(sharpe, 0.0)
        self.assertGreater(sortino, 0.0)

        # Zero or empty returns
        self.assertEqual(calculate_sharpe_ratio([]), 0.0)
        self.assertEqual(calculate_sortino_ratio([]), 0.0)
        self.assertEqual(calculate_sharpe_ratio([0.05]), 0.0)

    def test_benchmark_comparison(self):
        benchmarks = run_benchmark_comparison(self.sample_bets, initial_bank=5000.0)
        self.assertEqual(len(benchmarks), 5)
        self.assertIn("Live Real", benchmarks[0]["Стратегія"])
        self.assertIn("Aggressive Kelly", benchmarks[1]["Стратегія"])
        self.assertIn("Conservative Flat", benchmarks[2]["Стратегія"])
        self.assertIn("No-AI Baseline", benchmarks[3]["Стратегія"])
        self.assertIn("Elite EV", benchmarks[4]["Стратегія"])

if __name__ == "__main__":
    unittest.main()
