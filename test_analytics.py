"""
Тести для модуля розширеної аналітики ефективності та ризиків (SPEC-24).
"""

import unittest
from statmonitor.analytics import (
    classify_market_group,
    calculate_drawdown,
    calculate_streaks,
    calculate_league_breakdown,
    calculate_market_breakdown,
)

class TestAnalytics(unittest.TestCase):
    def test_classify_market_group(self):
        self.assertEqual(classify_market_group("Тотал більше (2.5)"), "Тотали")
        self.assertEqual(classify_market_group("Total Under 215.5"), "Тотали")
        self.assertEqual(classify_market_group("ТБ (2.0)"), "Тотали")
        self.assertEqual(classify_market_group("Фора (+1.5)"), "Фори")
        self.assertEqual(classify_market_group("Arsenal (+0.5)"), "Фори")
        self.assertEqual(classify_market_group("Обидві заб'ють (Так)"), "Обидві заб'ють")
        self.assertEqual(classify_market_group("Перемога команди 1"), "1X2 / Переможець")
        self.assertEqual(classify_market_group(""), "1X2 / Переможець")
        self.assertEqual(classify_market_group(None), "1X2 / Переможець")

    def test_calculate_drawdown(self):
        # 1. Порожній список
        res_empty = calculate_drawdown([])
        self.assertEqual(res_empty["max_drawdown_pct"], 0.0)
        self.assertEqual(res_empty["max_drawdown_uah"], 0.0)

        # 2. Серія ставок: банк 10000 -> +500 (10500) -> -1000 (9500) -> +2000 (11500) -> -500 (11000)
        # Пік 1: 10500, спад до 9500 -> просідання 1000 грн (1000/10500 = 9.52%)
        # Пік 2: 11500, спад до 11000 -> просідання 500 грн (500/11500 = 4.35%)
        # Максимальне просідання: 1000 грн, 9.52%
        bets = [
            {"id": 1, "status": "WON", "profit_uah": 500.0, "settled_at": "2026-11-10 10:00:00"},
            {"id": 2, "status": "LOST", "profit_uah": -1000.0, "settled_at": "2026-11-11 10:00:00"},
            {"id": 3, "status": "WON", "profit_uah": 2000.0, "settled_at": "2026-11-12 10:00:00"},
            {"id": 4, "status": "LOST", "profit_uah": -500.0, "settled_at": "2026-11-13 10:00:00"},
        ]
        dd = calculate_drawdown(bets, initial_bankroll=10000.0)
        self.assertEqual(dd["max_drawdown_uah"], 1000.0)
        self.assertEqual(dd["max_drawdown_pct"], 9.52)
        self.assertEqual(dd["peak_balance"], 11500.0)
        self.assertEqual(dd["current_drawdown_pct"], 4.35)

    def test_calculate_streaks(self):
        # 1. Порожній список
        st_empty = calculate_streaks([])
        self.assertEqual(st_empty["max_win_streak"], 0)
        self.assertEqual(st_empty["max_loss_streak"], 0)
        self.assertEqual(st_empty["current_streak_type"], "-")

        # 2. Серія: W, W, W, L, W, L, L, W, W
        # Win streaks: 3, 1, 2 (max = 3)
        # Loss streaks: 1, 2 (max = 2)
        # Current streak: 2W
        bets = [
            {"id": 1, "status": "WON", "settled_at": "2026-11-10 01:00:00"},
            {"id": 2, "status": "WON", "settled_at": "2026-11-10 02:00:00"},
            {"id": 3, "status": "WON", "settled_at": "2026-11-10 03:00:00"},
            {"id": 4, "status": "LOST", "settled_at": "2026-11-10 04:00:00"},
            {"id": 5, "status": "WON", "settled_at": "2026-11-10 05:00:00"},
            {"id": 6, "status": "LOST", "settled_at": "2026-11-10 06:00:00"},
            {"id": 7, "status": "LOST", "settled_at": "2026-11-10 07:00:00"},
            {"id": 8, "status": "WON", "settled_at": "2026-11-10 08:00:00"},
            {"id": 9, "status": "WON", "settled_at": "2026-11-10 09:00:00"},
        ]
        res = calculate_streaks(bets)
        self.assertEqual(res["max_win_streak"], 3)
        self.assertEqual(res["max_loss_streak"], 2)
        self.assertEqual(res["current_streak_type"], "W")
        self.assertEqual(res["current_streak_count"], 2)

    def test_calculate_league_breakdown(self):
        bets = [
            {"sport": "soccer_epl", "status": "WON", "stake_uah": 200, "profit_uah": 180},
            {"sport": "soccer_epl", "status": "LOST", "stake_uah": 200, "profit_uah": -200},
            {"sport": "basketball_nba", "status": "WON", "stake_uah": 300, "profit_uah": 270},
            {"sport": "basketball_nba", "status": "WON", "stake_uah": 300, "profit_uah": 300},
            {"sport": "soccer_la_liga", "status": "PENDING", "stake_uah": 150, "profit_uah": 0},
        ]
        sports_map = {"soccer_epl": "АПЛ", "basketball_nba": "НБА"}
        lb = calculate_league_breakdown(bets, sports_map=sports_map)
        
        # PENDING ставки не входять у розрахунок прибутку ліг
        self.assertEqual(len(lb), 2)
        # Перша за прибутком - NBA (+570 грн)
        self.assertEqual(lb[0]["sport"], "basketball_nba")
        self.assertEqual(lb[0]["league_title"], "НБА")
        self.assertEqual(lb[0]["bets_count"], 2)
        self.assertEqual(lb[0]["won"], 2)
        self.assertEqual(lb[0]["win_rate"], 100.0)
        self.assertEqual(lb[0]["profit_uah"], 570.0)
        self.assertEqual(lb[0]["roi_pct"], 95.0)

        # Друга - EPL (-20 грн)
        self.assertEqual(lb[1]["sport"], "soccer_epl")
        self.assertEqual(lb[1]["league_title"], "АПЛ")
        self.assertEqual(lb[1]["profit_uah"], -20.0)
        self.assertEqual(lb[1]["roi_pct"], -5.0)

    def test_calculate_market_breakdown(self):
        bets = [
            {"pick_label": "Тотал більше (2.5)", "status": "WON", "stake_uah": 200, "profit_uah": 200},
            {"pick_label": "Total Under (2.5)", "status": "WON", "stake_uah": 200, "profit_uah": 180},
            {"pick_label": "Arsenal", "status": "LOST", "stake_uah": 100, "profit_uah": -100},
        ]
        mb = calculate_market_breakdown(bets)
        self.assertEqual(len(mb), 2)
        # Перший за прибутком - Тотали (+380 грн)
        self.assertEqual(mb[0]["market_group"], "Тотали")
        self.assertEqual(mb[0]["bets_count"], 2)
        self.assertEqual(mb[0]["won"], 2)
        self.assertEqual(mb[0]["profit_uah"], 380.0)
        self.assertEqual(mb[0]["roi_pct"], 95.0)

        # Другий - 1X2 (-100 грн)
        self.assertEqual(mb[1]["market_group"], "1X2 / Переможець")
        self.assertEqual(mb[1]["profit_uah"], -100.0)

if __name__ == "__main__":
    unittest.main()
