import unittest
from statmonitor.analytics import calculate_confidence_calibration

class TestConfidenceCalibrationDashboard(unittest.TestCase):
    def test_calibration_empty_and_no_decided(self):
        # 1. Empty bets
        cal_empty = calculate_confidence_calibration([])
        self.assertEqual(len(cal_empty["buckets"]), 4)
        self.assertEqual(len(cal_empty["granular_scores"]), 10)
        self.assertIsNone(cal_empty["overall_brier_score"])
        self.assertIsNone(cal_empty["expected_calibration_error"])
        self.assertIsNone(cal_empty["brier_skill_score"])
        self.assertEqual(cal_empty["calibration_verdict"], "INSUFFICIENT_DATA")

        # 2. Only pending bets
        pending_bets = [
            {"status": "PENDING", "confidence_score": 7, "stake_uah": 100},
            {"status": "PENDING", "confidence_score": 8, "stake_uah": 100},
        ]
        cal_pend = calculate_confidence_calibration(pending_bets)
        self.assertIsNone(cal_pend["overall_brier_score"])
        self.assertEqual(cal_pend["calibration_verdict"], "INSUFFICIENT_DATA")

    def test_calibration_comprehensive_metrics(self):
        bets = [
            # Low confidence (1-4) -> Should be lost (well calibrated)
            {"status": "FILTERED", "shadow_status": "LOST", "confidence_score": 2, "stake_uah": 100, "profit_uah": 0, "shadow_profit_uah": -100, "clv_pct": -3.0, "is_shadow": True},
            {"status": "FILTERED", "shadow_status": "LOST", "confidence_score": 4, "stake_uah": 100, "profit_uah": 0, "shadow_profit_uah": -100, "clv_pct": -1.0, "is_shadow": True},
            # Questionable (5-6)
            {"status": "FILTERED", "shadow_status": "WON", "confidence_score": 5, "stake_uah": 100, "profit_uah": 0, "shadow_profit_uah": 95, "clv_pct": 0.5, "is_shadow": True},
            {"status": "FILTERED", "shadow_status": "LOST", "confidence_score": 6, "stake_uah": 100, "profit_uah": 0, "shadow_profit_uah": -100, "clv_pct": 0.0, "is_shadow": True},
            # Standard value (7-8)
            {"status": "WON", "confidence_score": 7, "stake_uah": 100, "profit_uah": 85, "clv_pct": 3.0, "is_shadow": False},
            {"status": "WON", "confidence_score": 7, "stake_uah": 100, "profit_uah": 90, "clv_pct": 4.0, "is_shadow": False},
            {"status": "LOST", "confidence_score": 8, "stake_uah": 100, "profit_uah": -100, "clv_pct": 2.5, "is_shadow": False},
            {"status": "WON", "confidence_score": 8, "stake_uah": 100, "profit_uah": 110, "clv_pct": 5.0, "is_shadow": False},
            # High confidence (9-10)
            {"status": "WON", "confidence_score": 9, "stake_uah": 100, "profit_uah": 95, "clv_pct": 6.0, "is_shadow": False},
            {"status": "WON", "confidence_score": 10, "stake_uah": 100, "profit_uah": 105, "clv_pct": 7.5, "is_shadow": False},
        ]

        cal = calculate_confidence_calibration(bets)

        # Buckets validation
        buckets = {b["bucket"]: b for b in cal["buckets"]}
        self.assertEqual(len(buckets), 4)

        # Bucket 1-4: 0 wins, 2 losses -> win rate 0.0%
        b1_4 = buckets["1-4"]
        self.assertEqual(b1_4["total_bets"], 2)
        self.assertEqual(b1_4["win_rate"], 0.0)
        self.assertLess(b1_4["brier_score"], 0.15)

        # Bucket 7-8: 3 wins, 1 loss -> win rate 75.0%
        b7_8 = buckets["7-8"]
        self.assertEqual(b7_8["total_bets"], 4)
        self.assertEqual(b7_8["win_rate"], 75.0)
        self.assertGreater(b7_8["roi_pct"], 0)

        # Bucket 9-10: 2 wins, 0 losses -> win rate 100.0%
        b9_10 = buckets["9-10"]
        self.assertEqual(b9_10["total_bets"], 2)
        self.assertEqual(b9_10["win_rate"], 100.0)

        # Overall Brier Score
        self.assertIsNotNone(cal["overall_brier_score"])
        self.assertGreater(cal["overall_brier_score"], 0.0)
        self.assertLess(cal["overall_brier_score"], 0.25)

        # Expected Calibration Error (ECE)
        self.assertIsNotNone(cal["expected_calibration_error"])
        self.assertIsNotNone(cal["ece_pct"])
        self.assertLessEqual(cal["ece_pct"], 25.0)

        # Brier Skill Score (BSS)
        self.assertIsNotNone(cal["brier_skill_score"])

        # Calibration Verdict
        self.assertIn(cal["calibration_verdict"], ["EXCELLENT", "GOOD", "OVERCONFIDENT", "UNDERCONFIDENT"])
        self.assertTrue(len(cal["calibration_verdict_label"]) > 0)

        # Granular scores validation
        granular = {g["score"]: g for g in cal["granular_scores"]}
        self.assertEqual(len(granular), 10)
        self.assertEqual(granular[7]["total_bets"], 2)
        self.assertEqual(granular[7]["win_rate"], 100.0)
        self.assertEqual(granular[7]["expected_win_rate"], 70.0)
        self.assertEqual(granular[8]["total_bets"], 2)
        self.assertEqual(granular[8]["win_rate"], 50.0)
        self.assertEqual(granular[10]["total_bets"], 1)
        self.assertEqual(granular[10]["win_rate"], 100.0)

    def test_verdict_classifications(self):
        # 1. Perfectly calibrated (win rate matches probability closely)
        well_calibrated_bets = []
        # Score 7: 7 won, 3 lost
        for _ in range(7):
            well_calibrated_bets.append({"status": "WON", "confidence_score": 7, "stake_uah": 100, "profit_uah": 90, "is_shadow": False})
        for _ in range(3):
            well_calibrated_bets.append({"status": "LOST", "confidence_score": 7, "stake_uah": 100, "profit_uah": -100, "is_shadow": False})
        
        cal_well = calculate_confidence_calibration(well_calibrated_bets)
        self.assertEqual(cal_well["calibration_verdict"], "EXCELLENT")
        self.assertLessEqual(cal_well["ece_pct"], 10.0)

        # 2. Overconfident (high predicted confidence but all lost)
        overconfident_bets = [
            {"status": "LOST", "confidence_score": 10, "stake_uah": 100, "profit_uah": -100, "is_shadow": False},
            {"status": "LOST", "confidence_score": 9, "stake_uah": 100, "profit_uah": -100, "is_shadow": False},
            {"status": "LOST", "confidence_score": 9, "stake_uah": 100, "profit_uah": -100, "is_shadow": False},
            {"status": "LOST", "confidence_score": 10, "stake_uah": 100, "profit_uah": -100, "is_shadow": False},
        ]
        cal_over = calculate_confidence_calibration(overconfident_bets)
        self.assertEqual(cal_over["calibration_verdict"], "OVERCONFIDENT")

if __name__ == "__main__":
    unittest.main()
