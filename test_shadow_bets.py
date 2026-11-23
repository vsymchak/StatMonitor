import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from statmonitor.paper_trading import place_paper_bet, manual_settle_bet, settle_and_report
from statmonitor.analytics import calculate_counterfactual_audit, calculate_confidence_calibration

class TestShadowCounterfactualBets(unittest.TestCase):

    def test_place_shadow_bet_low_confidence(self):
        cur = MagicMock()
        conn = MagicMock()
        now = datetime.now(timezone.utc)
        cur.fetchone.return_value = None  # event not exists yet

        # Placing bet with confidence 5/10
        res = place_paper_bet(
            cur, conn, "ev_shadow_1", "soccer_epl", "Man Utd - Liverpool", now,
            "П1", 2.40, drop_pct=12.0, confidence=5, risk_level="MEDIUM"
        )
        self.assertFalse(res)  # Not active
        self.assertTrue(cur.execute.called)

        # Check SQL insert contains FILTERED and LOW_CONFIDENCE
        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO paper_bets" in str(c[0][0])]
        self.assertTrue(len(insert_calls) > 0)
        sql, params = insert_calls[0][0][0], insert_calls[0][0][1]
        self.assertIn("'FILTERED'", sql)
        self.assertIn("LOW_CONFIDENCE (5/10 < 8)", params)
        conn.commit.assert_called()

    def test_place_shadow_bet_skip_recommendation(self):
        cur = MagicMock()
        conn = MagicMock()
        now = datetime.now(timezone.utc)
        cur.fetchone.return_value = None

        res = place_paper_bet(
            cur, conn, "ev_shadow_skip", "soccer_epl", "Chelsea - Tottenham", now,
            "Пропустити матч (висока дисперсія)", 1.95, drop_pct=8.0, confidence=8
        )
        self.assertFalse(res)
        insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO paper_bets" in str(c[0][0])]
        self.assertTrue(len(insert_calls) > 0)
        params = insert_calls[0][0][1]
        self.assertEqual(params[-1], "AI_SKIP")

    def test_manual_settle_shadow_bet_won(self):
        cur = MagicMock()
        conn = MagicMock()

        # row: id, match_name, pick_label, odds, stake_uah, is_real, real_stake, real_odds, status, is_shadow
        cur.fetchone.return_value = (101, "Arsenal - Chelsea", "П1", 2.00, 200.0, False, None, None, "FILTERED", True)

        ok, msg = manual_settle_bet(cur, conn, 101, "2:1")
        self.assertTrue(ok)
        self.assertIn("Shadow-ставку #101", msg)
        self.assertIn("WON", msg)
        self.assertIn("+200.00 грн", msg)

        # Check update query updated shadow_status and shadow_profit_uah
        update_calls = [c for c in cur.execute.call_args_list if "UPDATE paper_bets SET shadow_status=" in str(c[0][0])]
        self.assertTrue(len(update_calls) > 0)
        up_params = update_calls[0][0][1]
        self.assertEqual(up_params[0], "WON")
        self.assertEqual(up_params[1], 200.0)  # hypo profit

    def test_manual_settle_shadow_bet_lost(self):
        cur = MagicMock()
        conn = MagicMock()
        cur.fetchone.return_value = (102, "Arsenal - Chelsea", "П1", 2.00, 200.0, False, None, None, "FILTERED", True)

        ok, msg = manual_settle_bet(cur, conn, 102, "0:1")
        self.assertTrue(ok)
        self.assertIn("Shadow-ставку #102", msg)
        self.assertIn("LOST", msg)

        update_calls = [c for c in cur.execute.call_args_list if "UPDATE paper_bets SET shadow_status=" in str(c[0][0])]
        self.assertTrue(len(update_calls) > 0)
        up_params = update_calls[0][0][1]
        self.assertEqual(up_params[0], "LOST")
        self.assertEqual(up_params[1], -200.0)  # hypo loss

    def test_settle_and_report_handles_shadow_bets(self):
        cur = MagicMock()
        conn = MagicMock()

        # Mock: 1 live pending bet, 1 shadow pending bet
        mock_pending = [
            (1, "ev1", "soccer_epl", "Team A - Team B", "П1", 2.0, 100.0, False, None, None, "PENDING", False),
            (2, "ev2", "soccer_epl", "Team C - Team D", "П1", 2.5, 100.0, False, None, None, "FILTERED", True),
        ]
        cur.fetchall.return_value = mock_pending

        mock_scores_res = MagicMock()
        mock_scores_res.status_code = 200
        mock_scores_res.json.return_value = [
            {"id": "ev1", "completed": True, "home_team": "Team A", "away_team": "Team B", "scores": [{"name": "Team A", "score": "2"}, {"name": "Team B", "score": "0"}]},
            {"id": "ev2", "completed": True, "home_team": "Team C", "away_team": "Team D", "scores": [{"name": "Team C", "score": "0"}, {"name": "Team D", "score": "1"}]},
        ]

        with patch("statmonitor.paper_trading.API_KEY", "dummy_test_key"):
            with patch("statmonitor.paper_trading.capture_closing_lines"):
                with patch("requests.get", return_value=mock_scores_res):
                    settle_and_report(cur, conn)

        # Check live bet update: status='WON', profit_uah=100.0
        live_up = [c for c in cur.execute.call_args_list if "UPDATE paper_bets SET status=" in str(c[0][0])]
        self.assertTrue(len(live_up) > 0)
        self.assertEqual(live_up[0][0][1][0], "WON")
        self.assertEqual(live_up[0][0][1][2], 100.0)

        # Check shadow bet update: shadow_status='LOST', shadow_profit_uah=-100.0
        shadow_up = [c for c in cur.execute.call_args_list if "UPDATE paper_bets \n                                SET shadow_status =" in str(c[0][0]) or "UPDATE paper_bets" in str(c[0][0]) and "shadow_status" in str(c[0][0])]
        self.assertTrue(len(shadow_up) > 0)
        self.assertEqual(shadow_up[0][0][1][0], "LOST")
        self.assertEqual(shadow_up[0][0][1][1], -100.0)

    def test_calculate_counterfactual_audit(self):
        bets = [
            # Live bets (Confidence >= 7)
            {"id": 1, "status": "WON", "stake_uah": 300.0, "profit_uah": 300.0, "is_shadow": False},
            {"id": 2, "status": "WON", "stake_uah": 200.0, "profit_uah": 200.0, "is_shadow": False},
            {"id": 3, "status": "LOST", "stake_uah": 200.0, "profit_uah": -200.0, "is_shadow": False},
            # Shadow bets (Filtered)
            {"id": 4, "status": "FILTERED", "shadow_status": "LOST", "stake_uah": 250.0, "profit_uah": 0.0, "shadow_profit_uah": -250.0, "is_shadow": True},
            {"id": 5, "status": "FILTERED", "shadow_status": "LOST", "stake_uah": 250.0, "profit_uah": 0.0, "shadow_profit_uah": -250.0, "is_shadow": True},
            {"id": 6, "status": "FILTERED", "shadow_status": "WON", "stake_uah": 200.0, "profit_uah": 0.0, "shadow_profit_uah": 200.0, "is_shadow": True},
        ]

        audit = calculate_counterfactual_audit(bets)

        # Live: 2 Won, 1 Lost. Turnover = 700, Profit = 300. ROI = 300/700 = 42.86%, Win Rate = 66.7%
        self.assertEqual(audit["live"]["total"], 3)
        self.assertEqual(audit["live"]["won"], 2)
        self.assertEqual(audit["live"]["lost"], 1)
        self.assertEqual(audit["live"]["profit"], 300.0)
        self.assertEqual(round(audit["live"]["roi_pct"], 1), 42.9)
        self.assertEqual(round(audit["live"]["win_rate"], 1), 66.7)

        # Shadow: 1 Won, 2 Lost. Turnover = 700, Profit = -300. ROI = -300/700 = -42.86%, Win Rate = 33.3%
        self.assertEqual(audit["shadow"]["total"], 3)
        self.assertEqual(audit["shadow"]["won"], 1)
        self.assertEqual(audit["shadow"]["lost"], 2)
        self.assertEqual(audit["shadow"]["profit"], -300.0)
        self.assertEqual(round(audit["shadow"]["roi_pct"], 1), -42.9)
        self.assertEqual(round(audit["shadow"]["win_rate"], 1), 33.3)

        # Alpha: Delta ROI = 42.86 - (-42.86) = +85.71%
        self.assertGreater(audit["value_add"]["delta_roi_pct"], 80.0)
        # Capital saved = -(-300) = +300 грн
        self.assertEqual(audit["value_add"]["capital_saved_uah"], 300.0)
        self.assertEqual(audit["value_add"]["verdict"], "POSITIVE")

    def test_calculate_confidence_calibration(self):
        bets = [
            {"status": "FILTERED", "shadow_status": "LOST", "confidence_score": 4, "stake_uah": 100, "profit_uah": 0, "shadow_profit_uah": -100, "clv_pct": -2.0, "is_shadow": True},
            {"status": "FILTERED", "shadow_status": "LOST", "confidence_score": 6, "stake_uah": 100, "profit_uah": 0, "shadow_profit_uah": -100, "clv_pct": 1.0, "is_shadow": True},
            {"status": "WON", "confidence_score": 7, "stake_uah": 100, "profit_uah": 80, "clv_pct": 3.5, "is_shadow": False},
            {"status": "WON", "confidence_score": 8, "stake_uah": 100, "profit_uah": 90, "clv_pct": 4.0, "is_shadow": False},
            {"status": "WON", "confidence_score": 10, "stake_uah": 100, "profit_uah": 110, "clv_pct": 6.5, "is_shadow": False},
        ]

        cal = calculate_confidence_calibration(bets)
        buckets = cal["buckets"]
        self.assertEqual(len(buckets), 4)

        b1_4 = [b for b in buckets if b["bucket"] == "1-4"][0]
        self.assertEqual(b1_4["total_bets"], 1)
        self.assertEqual(b1_4["win_rate"], 0.0)

        b7_8 = [b for b in buckets if b["bucket"] == "7-8"][0]
        self.assertEqual(b7_8["total_bets"], 2)
        self.assertEqual(b7_8["win_rate"], 100.0)
        self.assertGreater(b7_8["roi_pct"], 0)

        b9_10 = [b for b in buckets if b["bucket"] == "9-10"][0]
        self.assertEqual(b9_10["total_bets"], 1)
        self.assertEqual(b9_10["win_rate"], 100.0)

        # Overall Brier Score exists and is a valid float
        self.assertIsNotNone(cal["overall_brier_score"])
        self.assertGreater(cal["overall_brier_score"], 0.0)

if __name__ == "__main__":
    unittest.main()
