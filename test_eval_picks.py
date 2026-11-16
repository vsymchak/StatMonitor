import unittest
from statmonitor.paper_trading import format_pick, eval_outcome
from statmonitor.ai import extract_short_pick

class TestFormatPick(unittest.TestCase):
    """Тестування форматування назви ставки в зрозумілий український лейбл."""

    def test_already_formatted(self):
        self.assertEqual(format_pick("h2h", "П1", None, "Arsenal - Chelsea"), "П1")
        self.assertEqual(format_pick("spreads", "Ф2 (+1.5)", 1.5, "Arsenal - Chelsea"), "Ф2 (+1.5)")
        self.assertEqual(format_pick("totals", "ТБ 2.5", 2.5, "Arsenal - Chelsea"), "ТБ 2.5")
        self.assertEqual(format_pick("totals", "ТМ 3", 3.0, "Arsenal - Chelsea"), "ТМ 3")
        self.assertEqual(format_pick("h2h", "Х", None, "Arsenal - Chelsea"), "Х")

    def test_totals_over_under(self):
        # Футбол
        self.assertEqual(format_pick("totals", "Over", 2.5, "Arsenal - Chelsea"), "ТБ 2.5")
        self.assertEqual(format_pick("totals", "Under", 3.0, "Arsenal - Chelsea"), "ТМ 3")
        # Баскетбол високий тотал
        self.assertEqual(format_pick("totals", "over", 215.5, "Lakers - Warriors"), "ТБ 215.5")
        self.assertEqual(format_pick("totals", "under", 210.0, "Lakers - Warriors"), "ТМ 210")
        # Без точки
        self.assertEqual(format_pick("totals", "Over", None, "Arsenal - Chelsea"), "ТБ")

    def test_spreads_handicaps(self):
        # Домашня команда Ф1
        self.assertEqual(format_pick("spreads", "Arsenal", -1.5, "Arsenal - Chelsea"), "Ф1 (-1.5)")
        self.assertEqual(format_pick("spreads", "Arsenal", 0.0, "Arsenal - Chelsea"), "Ф1 (+0)")
        self.assertEqual(format_pick("spreads", "Arsenal", 1.0, "Arsenal - Chelsea"), "Ф1 (+1)")
        # Гостьова команда Ф2
        self.assertEqual(format_pick("spreads", "Chelsea", 1.5, "Arsenal - Chelsea"), "Ф2 (+1.5)")
        self.assertEqual(format_pick("spreads", "Chelsea", -0.5, "Arsenal - Chelsea"), "Ф2 (-0.5)")
        # Стороння назва команди (наприклад, neutral venue)
        self.assertEqual(format_pick("spreads", "Liverpool", -2.5, "Arsenal - Chelsea"), "Фора Liverpool (-2.5)")

    def test_h2h_moneyline(self):
        self.assertEqual(format_pick("h2h", "Arsenal", None, "Arsenal - Chelsea"), "П1 (Arsenal)")
        self.assertEqual(format_pick("h2h", "Chelsea", None, "Arsenal - Chelsea"), "П2 (Chelsea)")
        self.assertEqual(format_pick("h2h", "Draw", None, "Arsenal - Chelsea"), "Х (Нічия)")
        self.assertEqual(format_pick("h2h", "draw", None, "Arsenal - Chelsea"), "Х (Нічия)")


class TestEvalOutcome(unittest.TestCase):
    """Тестування розрахунку результатів ставок (WON, LOST, VOID)."""

    def test_totals_won_lost_void(self):
        # ТБ 2.5
        self.assertEqual(eval_outcome("ТБ 2.5", "Arsenal - Chelsea", 2, 1), "WON")
        self.assertEqual(eval_outcome("ТБ 2.5", "Arsenal - Chelsea", 1, 1), "LOST")
        # ТБ 3.0 (цілий тотал -> можливість VOID)
        self.assertEqual(eval_outcome("ТБ 3", "Arsenal - Chelsea", 2, 1), "VOID")
        self.assertEqual(eval_outcome("ТБ 3", "Arsenal - Chelsea", 3, 1), "WON")
        self.assertEqual(eval_outcome("ТБ 3", "Arsenal - Chelsea", 1, 1), "LOST")
        # ТМ 2.5
        self.assertEqual(eval_outcome("ТМ 2.5", "Arsenal - Chelsea", 1, 1), "WON")
        self.assertEqual(eval_outcome("ТМ 2.5", "Arsenal - Chelsea", 2, 1), "LOST")
        # ТМ 2.0 (VOID)
        self.assertEqual(eval_outcome("ТМ 2", "Arsenal - Chelsea", 1, 1), "VOID")

    def test_totals_basketball(self):
        self.assertEqual(eval_outcome("Over 215.5", "Lakers - Warriors", 112, 108), "WON") # 220 > 215.5
        self.assertEqual(eval_outcome("Under 215.5", "Lakers - Warriors", 105, 102), "WON") # 207 < 215.5
        self.assertEqual(eval_outcome("Under 215.5", "Lakers - Warriors", 115, 110), "LOST") # 225 > 215.5

    def test_spreads_f1(self):
        # Ф1 (-1.5)
        self.assertEqual(eval_outcome("Ф1 (-1.5)", "Arsenal - Chelsea", 3, 1), "WON")  # 3 - 1.5 - 1 = +0.5 > 0
        self.assertEqual(eval_outcome("Ф1 (-1.5)", "Arsenal - Chelsea", 2, 1), "LOST") # 2 - 1.5 - 1 = -0.5 < 0
        # Ф1 (-1) ціла фора
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 2, 1), "VOID")  # 2 - 1 - 1 = 0
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 3, 1), "WON")
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 1, 1), "LOST")
        # Ф1 (+1.5)
        self.assertEqual(eval_outcome("Ф1 (+1.5)", "Arsenal - Chelsea", 1, 2), "WON")  # 1 + 1.5 - 2 = +0.5 > 0
        self.assertEqual(eval_outcome("Ф1 (+1.5)", "Arsenal - Chelsea", 0, 2), "LOST") # 0 + 1.5 - 2 = -0.5 < 0

    def test_spreads_f2(self):
        # Ф2 (+1.5)
        self.assertEqual(eval_outcome("Ф2 (+1.5)", "Arsenal - Chelsea", 2, 1), "WON")  # 1 + 1.5 - 2 = +0.5 > 0
        self.assertEqual(eval_outcome("Ф2 (+1.5)", "Arsenal - Chelsea", 3, 1), "LOST") # 1 + 1.5 - 3 = -0.5 < 0
        # Ф2 (-0.5) перемога гостей
        self.assertEqual(eval_outcome("Ф2 (-0.5)", "Arsenal - Chelsea", 1, 2), "WON")  # 2 - 0.5 - 1 = +0.5 > 0
        self.assertEqual(eval_outcome("Ф2 (-0.5)", "Arsenal - Chelsea", 1, 1), "LOST") # 1 - 0.5 - 1 = -0.5 < 0
        # Ф2 (+1) ціла фора -> VOID
        self.assertEqual(eval_outcome("Ф2 (+1)", "Arsenal - Chelsea", 2, 1), "VOID")

    def test_moneyline_1x2(self):
        # П1
        self.assertEqual(eval_outcome("П1 (Arsenal)", "Arsenal - Chelsea", 2, 1), "WON")
        self.assertEqual(eval_outcome("П1 (Arsenal)", "Arsenal - Chelsea", 1, 1), "LOST")
        self.assertEqual(eval_outcome("П1 (Arsenal)", "Arsenal - Chelsea", 0, 2), "LOST")
        # П2
        self.assertEqual(eval_outcome("П2 (Chelsea)", "Arsenal - Chelsea", 0, 1), "WON")
        self.assertEqual(eval_outcome("П2 (Chelsea)", "Arsenal - Chelsea", 2, 1), "LOST")
        # Нічия
        self.assertEqual(eval_outcome("Х (Нічия)", "Arsenal - Chelsea", 1, 1), "WON")
        self.assertEqual(eval_outcome("Х (Нічия)", "Arsenal - Chelsea", 2, 1), "LOST")
        self.assertEqual(eval_outcome("Нічия", "Arsenal - Chelsea", 0, 0), "WON")

    def test_unrecognized_pick_returns_none(self):
        self.assertIsNone(eval_outcome("Обидві заб'ють (Так)", "Arsenal - Chelsea", 1, 1))
        self.assertIsNone(eval_outcome("", "Arsenal - Chelsea", 1, 1))


class TestExtractShortPick(unittest.TestCase):
    """Тестування парсингу та нормалізації рекомендацій ставок від Gemini AI."""

    def test_none_or_empty_returns_fallback(self):
        self.assertEqual(extract_short_pick(None, "Ф1 (+0)"), "Ф1 (+0)")
        self.assertEqual(extract_short_pick("", "ТБ 2.5"), "ТБ 2.5")

    def test_markdown_pick_extraction(self):
        ai_text = (
            "📌 **Коротка ставка:** Ф2 (+1.5)\n"
            "🎯 **Рекомендована ставка:** Взяти плюсову фору на гостей.\n"
        )
        self.assertEqual(extract_short_pick(ai_text, "fallback"), "Ф2 (+1.5)")

    def test_html_pick_extraction(self):
        ai_text = (
            "📌 <b>Коротка ставка:</b> ТБ 2.5\n"
            "🎯 <b>Рекомендована ставка:</b> Тотал більше 2.5 голів.\n"
        )
        self.assertEqual(extract_short_pick(ai_text, "fallback"), "ТБ 2.5")

    def test_skip_recommendation(self):
        ai_text = "📌 **Коротка ставка:** Пропустити матч через високі ризики ротації."
        self.assertEqual(extract_short_pick(ai_text, "fallback"), "⏭ Пропустити матч")

        ai_text2 = "📌 **Коротка ставка:** Краще утриматися від ставки."
        self.assertEqual(extract_short_pick(ai_text2, "fallback"), "⏭ Пропустити матч")

    def test_strips_odds_mention(self):
        ai_text = "📌 **Коротка ставка:** П1 (Arsenal) з коефіцієнтом 1.85"
        self.assertEqual(extract_short_pick(ai_text, "fallback"), "П1 (Arsenal)")

        ai_text2 = "📌 **Коротка ставка:** ТБ 2.5 @ 1.95"
        self.assertEqual(extract_short_pick(ai_text2, "fallback"), "ТБ 2.5")

    def test_balanced_parentheses(self):
        # Якщо в кінці обрізалась дужка
        ai_text = "📌 **Коротка ставка:** Ф2 (+1.5"
        self.assertEqual(extract_short_pick(ai_text, "fallback"), "Ф2 (+1.5)")

    def test_fallback_to_recommended_stake_tag(self):
        ai_text = (
            "Аналіз зустрічі.\n"
            "🎯 **Рекомендована ставка:** П2 (Chelsea) за 2.10\n"
        )
        self.assertEqual(extract_short_pick(ai_text, "fallback"), "П2 (Chelsea)")


if __name__ == "__main__":
    unittest.main()
