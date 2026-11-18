import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from statmonitor.analytics import calculate_clv_value, calculate_clv_metrics
from statmonitor.paper_trading import capture_closing_lines
from statmonitor.database import ensure_tables

class TestCLVTracking(unittest.TestCase):
    def test_calculate_clv_value_positive(self):
        # Взяли коеф 2.10, закрився 1.85 -> лінію побито на +13.51%
        clv, beat = calculate_clv_value(2.10, 1.85)
        self.assertEqual(clv, 13.51)
        self.assertTrue(beat)

    def test_calculate_clv_value_negative(self):
        # Взяли коеф 1.80, закрився 1.95 -> програли лінії -7.69%
        clv, beat = calculate_clv_value(1.80, 1.95)
        self.assertEqual(clv, -7.69)
        self.assertFalse(beat)

    def test_calculate_clv_value_edge_cases(self):
        # Рівні коефіцієнти
        clv, beat = calculate_clv_value(2.00, 2.00)
        self.assertEqual(clv, 0.0)
        self.assertFalse(beat)

        # Некоректні/нульові значення
        self.assertEqual(calculate_clv_value(0, 1.90), (0.0, False))
        self.assertEqual(calculate_clv_value(1.90, None), (0.0, False))
        self.assertEqual(calculate_clv_value("invalid", 1.90), (0.0, False))

    def test_calculate_clv_metrics_empty(self):
        res = calculate_clv_metrics([])
        self.assertEqual(res["total_with_clv"], 0)
        self.assertEqual(res["beat_line_pct"], 0.0)
        self.assertEqual(res["avg_clv_pct"], 0.0)

    def test_calculate_clv_metrics_aggregation(self):
        bets = [
            {"odds": 2.10, "closing_odds": 1.85, "clv_pct": 13.51, "beat_closing_line": True},
            {"odds": 1.90, "closing_odds": 1.70, "clv_pct": 11.76, "beat_closing_line": True},
            {"odds": 1.80, "closing_odds": 1.95, "clv_pct": -7.69, "beat_closing_line": False},
            {"odds": 1.95, "closing_odds": None, "clv_pct": None, "beat_closing_line": None}, # Без закриття
        ]
        res = calculate_clv_metrics(bets)
        self.assertEqual(res["total_with_clv"], 3)
        self.assertEqual(res["beat_count"], 2)
        self.assertEqual(res["beat_line_pct"], 66.7)
        # (13.51 + 11.76 - 7.69) / 3 = 17.58 / 3 = 5.86%
        self.assertEqual(res["avg_clv_pct"], 5.86)
        self.assertEqual(res["positive_clv_count"], 2)
        self.assertEqual(res["negative_clv_count"], 1)

    def test_calculate_clv_metrics_dynamic_calculation(self):
        # Якщо clv_pct не передано в словнику, але є odds і closing_odds
        bets = [
            {"odds": 2.00, "closing_odds": 1.80},
            {"odds": 1.75, "closing_odds": 1.90},
        ]
        res = calculate_clv_metrics(bets)
        self.assertEqual(res["total_with_clv"], 2)
        self.assertEqual(res["beat_count"], 1)
        self.assertEqual(res["beat_line_pct"], 50.0)
        self.assertGreater(res["avg_clv_pct"], 0)

    @patch("statmonitor.paper_trading.get_market_median_odds")
    def test_capture_closing_lines(self, mock_median):
        mock_median.return_value = 1.85

        cur = MagicMock()
        conn = MagicMock()
        # Повертаємо 1 нерозраховану ставку з commence_time
        cur.fetchall.return_value = [
            (101, "ev123", "Arsenal - Chelsea", "П1", 2.10, datetime.now(timezone.utc), "PENDING")
        ]

        updated = capture_closing_lines(cur, conn)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["id"], 101)
        self.assertEqual(updated[0]["closing_odds"], 1.85)
        self.assertEqual(updated[0]["clv_pct"], 13.51)
        self.assertTrue(updated[0]["beat_line"])

        # Перевірка виклику UPDATE в базі даних
        cur.execute.assert_called()
        conn.commit.assert_called()

    def test_database_ensure_tables_clv(self):
        cur = MagicMock()
        conn = MagicMock()
        ensure_tables(cur, conn)
        calls = [str(c) for c in cur.execute.mock_calls]
        clv_calls = [c for c in calls if "closing_odds" in c]
        self.assertTrue(len(clv_calls) > 0)

if __name__ == "__main__":
    unittest.main()
