import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from statmonitor.ai import extract_confidence_score
from statmonitor.paper_trading import place_paper_bet, calculate_kelly_fraction

class TestAIConfidenceAndValueFiltering(unittest.TestCase):

    def test_extract_confidence_score_standard(self):
        verdict = """
        📌 **Коротка ставка:** П1 (Arsenal)
        🎯 **Рекомендована ставка:** Брати П1 через кадровий голод суперника
        ⭐ **Оцінка впевненості (Confidence Score):** 8/10 (Рівень ризику: Low)
        """
        score, risk = extract_confidence_score(verdict)
        self.assertEqual(score, 8)
        self.assertEqual(risk, "LOW")

    def test_extract_confidence_score_alternative_formats(self):
        v1 = "Впевненість: 7 з 10 (середній ризик)"
        s1, r1 = extract_confidence_score(v1)
        self.assertEqual(s1, 7)
        self.assertEqual(r1, "MEDIUM")

        v2 = "Confidence Score: 9/10, Risk: High"
        s2, r2 = extract_confidence_score(v2)
        self.assertEqual(s2, 9)
        self.assertEqual(r2, "HIGH")

    def test_extract_confidence_score_skip_recommendation(self):
        verdict = """
        📌 **Коротка ставка:** Пропустити матч
        🎯 **Рекомендована ставка:** Краще пропустити цей матч через незрозумілу форму
        """
        score, risk = extract_confidence_score(verdict)
        self.assertLessEqual(score, 4)
        self.assertEqual(risk, "HIGH")

    def test_extract_confidence_score_none_or_empty(self):
        s1, r1 = extract_confidence_score(None)
        self.assertIsNone(s1)
        self.assertIsNone(r1)

        s2, r2 = extract_confidence_score("Текст без оцінки сили сигналу")
        self.assertIsNone(s2)
        self.assertIsNone(r2)

    def test_place_paper_bet_filter_low_confidence(self):
        cur = MagicMock()
        conn = MagicMock()
        now = datetime.now(timezone.utc)

        # Ставка з оцінкою 6/10 має бути автоматично відхилена фільтром валую
        res = place_paper_bet(
            cur, conn, "ev_low", "soccer_epl", "Team A - Team B", now,
            "П1", 2.10, drop_pct=15.0, confidence=6, risk_level="MEDIUM"
        )
        self.assertFalse(res)
        cur.execute.assert_not_called()

    def test_place_paper_bet_accept_high_confidence(self):
        cur = MagicMock()
        conn = MagicMock()
        now = datetime.now(timezone.utc)

        # Mock: ставка ще не існує, банк доступний
        cur.fetchone.side_effect = [
            None,          # SELECT 1 FROM paper_bets WHERE event_id=%s
            (500.0, 0.0),  # profit, locked
        ]

        # Ставка з оцінкою 8/10 має бути успішно прийнята
        res = place_paper_bet(
            cur, conn, "ev_high", "soccer_epl", "Team A - Team B", now,
            "П1", 2.10, drop_pct=15.0, confidence=8, risk_level="LOW"
        )
        self.assertTrue(res)
        self.assertTrue(cur.execute.called)
        conn.commit.assert_called()

    def test_kelly_fraction_modulated_by_confidence(self):
        k = 2.00
        drop = 15.0
        frac_c7 = calculate_kelly_fraction(k, drop_pct=drop, confidence=7)
        frac_c10 = calculate_kelly_fraction(k, drop_pct=drop, confidence=10)
        self.assertGreaterEqual(frac_c10, frac_c7)

if __name__ == "__main__":
    unittest.main()
