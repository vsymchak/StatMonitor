import unittest
from unittest.mock import MagicMock, patch

from statmonitor.paper_trading import (
    parse_score_sets_and_games,
    eval_outcome_from_score,
    manual_settle_bet,
)
from statmonitor.bot import handle_command


class TestTennisSettle(unittest.TestCase):
    def test_parse_tennis_scores(self):
        # 1. Two sets
        p1 = parse_score_sets_and_games("7:6, 7:5")
        self.assertTrue(p1["is_multi"])
        self.assertEqual(p1["h_sets"], 2)
        self.assertEqual(p1["a_sets"], 0)
        self.assertEqual(p1["h_games"], 14)
        self.assertEqual(p1["a_games"], 11)

        # 2. Three sets
        p2 = parse_score_sets_and_games("6:4, 3:6, 6:3")
        self.assertTrue(p2["is_multi"])
        self.assertEqual(p2["h_sets"], 2)
        self.assertEqual(p2["a_sets"], 1)
        self.assertEqual(p2["h_games"], 15)
        self.assertEqual(p2["a_games"], 13)

        # 3. Simple single score (football)
        p3 = parse_score_sets_and_games("2:1")
        self.assertFalse(p3["is_multi"])
        self.assertEqual(p3["h_sc"], 2)
        self.assertEqual(p3["a_sc"], 1)

    def test_shelton_jodar_eval_outcome(self):
        match_name = "Ben Shelton - Rafael Jodar"
        score_str = "7:6, 7:5"

        # 1. Handicap Ф1 (-1.5) must be WON
        res_h1 = eval_outcome_from_score("Ф1 (-1.5)", match_name, score_str)
        self.assertEqual(res_h1, "WON")

        # 2. Moneyline П1 must be WON
        res_p1 = eval_outcome_from_score("П1", match_name, score_str)
        self.assertEqual(res_p1, "WON")

        # 3. Opposite Handicap Ф2 (+1.5) must be LOST
        res_h2 = eval_outcome_from_score("Ф2 (+1.5)", match_name, score_str)
        self.assertEqual(res_h2, "LOST")

        # 4. Totals: 14 + 11 = 25 games
        res_tb = eval_outcome_from_score("ТБ (21.5)", match_name, score_str)
        self.assertEqual(res_tb, "WON")

        res_tm = eval_outcome_from_score("ТМ (22.5)", match_name, score_str)
        self.assertEqual(res_tm, "LOST")

    def test_manual_settle_bet_auto_won(self):
        cur = MagicMock()
        conn = MagicMock()
        # id=56, match_name, pick_label, odds, stake_uah, is_real_bet, real_stake, real_odds, status, is_shadow
        cur.fetchone.return_value = (56, "Ben Shelton - Rafael Jodar", "Ф1 (-1.5)", 1.49, 384.30, False, None, None, "LOST", False)

        ok, msg = manual_settle_bet(cur, conn, 56, "7:6, 7:5")
        self.assertTrue(ok)
        self.assertIn("WON", msg)
        self.assertIn("188.31", msg)
        cur.execute.assert_called()
        conn.commit.assert_called()

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_bot_settle_command(self):
        cur = MagicMock()
        conn = MagicMock()
        cur.fetchone.return_value = (56, "Ben Shelton - Rafael Jodar", "Ф1 (-1.5)", 1.49, 384.30, False, None, None, "LOST", False)

        # 1. /settle 56 7:6, 7:5
        resp, _ = handle_command("/settle 56 7:6, 7:5", "123456789", cur, conn)
        self.assertIn("Результат ставки оновлено", resp)
        self.assertIn("WON", resp)

        # 2. /settle 56 won
        resp2, _ = handle_command("/settle 56 won", "123456789", cur, conn)
        self.assertIn("Результат ставки оновлено", resp2)
        self.assertIn("WON", resp2)


if __name__ == "__main__":
    unittest.main()
