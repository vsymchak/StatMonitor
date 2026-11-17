import unittest
from statmonitor.paper_trading import (
    format_pick,
    eval_outcome,
    parse_pick_label,
    resolve_alert_from_history,
    get_market_median_odds,
    recalculate_historical_paper_bets,
    BENCHMARK_BOOKMAKERS,
)
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


class TestParsePickLabel(unittest.TestCase):
    """Тестування розбору ставок на маркет, сторону та фору/тотал (SPEC-18)."""

    def test_parse_spreads(self):
        mkt, out, pt = parse_pick_label("Ф2 (+4.5)", "Daniil Medvedev - Flavio Cobolli")
        self.assertEqual(mkt, "spreads")
        self.assertEqual(out, "Flavio Cobolli")
        self.assertEqual(pt, 4.5)

        mkt, out, pt = parse_pick_label("Ф1 (-3.5)", "Daniil Medvedev - Flavio Cobolli")
        self.assertEqual(mkt, "spreads")
        self.assertEqual(out, "Daniil Medvedev")
        self.assertEqual(pt, -3.5)

        mkt, out, pt = parse_pick_label("Фора Chelsea (+1.5)", "Arsenal - Chelsea")
        self.assertEqual(mkt, "spreads")
        self.assertEqual(out, "Chelsea")
        self.assertEqual(pt, 1.5)

    def test_parse_totals(self):
        mkt, out, pt = parse_pick_label("ТБ 2.5", "Arsenal - Chelsea")
        self.assertEqual(mkt, "totals")
        self.assertEqual(out, "Over")
        self.assertEqual(pt, 2.5)

        mkt, out, pt = parse_pick_label("ТМ 210.5", "Lakers - Warriors")
        self.assertEqual(mkt, "totals")
        self.assertEqual(out, "Under")
        self.assertEqual(pt, 210.5)

    def test_parse_h2h(self):
        mkt, out, pt = parse_pick_label("П1", "Arsenal - Chelsea")
        self.assertEqual(mkt, "h2h")
        self.assertEqual(out, "Arsenal")
        self.assertIsNone(pt)

        mkt, out, pt = parse_pick_label("П2 (Cobolli)", "Daniil Medvedev - Flavio Cobolli")
        self.assertEqual(mkt, "h2h")
        self.assertEqual(out, "Flavio Cobolli")
        self.assertIsNone(pt)

        mkt, out, pt = parse_pick_label("Х (Нічия)", "Arsenal - Chelsea")
        self.assertEqual(mkt, "h2h")
        self.assertEqual(out, "Draw")
        self.assertIsNone(pt)


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


class TestMarketMedianOdds(unittest.TestCase):
    """Тестування розрахунку медіанних ринкових коефіцієнтів та добору з odds_history (SPEC-18)."""

    def test_resolve_alert_from_history_found_spread(self):
        # Якщо v_odds_alerts повернув без point за 1.72, з odds_history підтягується spreads -3.5
        cur = MockCursor(fetchone_data=("spreads", -3.5, "Daniil Medvedev", 1.72))
        mkt, pt, out, price = resolve_alert_from_history(cur, "ev_medvedev", "pinnacle", 1.72, "Daniil Medvedev")
        self.assertEqual(mkt, "spreads")
        self.assertEqual(pt, -3.5)
        self.assertEqual(price, 1.72)

    def test_resolve_alert_from_history_found_h2h(self):
        # Якщо v_odds_alerts повернув без point за 1.28, з odds_history підтягується h2h
        cur = MockCursor(fetchone_data=("h2h", None, "Daniil Medvedev", 1.28))
        mkt, pt, out, price = resolve_alert_from_history(cur, "ev_medvedev", "pinnacle", 1.28, "Daniil Medvedev")
        self.assertEqual(mkt, "h2h")
        self.assertIsNone(pt)
        self.assertEqual(price, 1.28)

    def test_get_market_median_odds_with_benchmarks(self):
        # Pinnacle: 1.57, Betfair: 1.58, Unibet: 1.59, Marathonbet: 1.58 -> Медіана: 1.58
        cur = MockCursor(fetchall_data=[
            ("pinnacle", 1.57),
            ("betfair_ex_eu", 1.58),
            ("unibet_eu", 1.59),
            ("marathonbet", 1.58),
            ("williamhill", 1.54),
        ])
        k = get_market_median_odds(cur, "ev_medvedev", "Ф2 (+4.5)", "Daniil Medvedev - Flavio Cobolli", fallback_odds=3.25)
        self.assertEqual(k, 1.58)

    def test_get_market_median_odds_all_bookmakers(self):
        # Тільки звичайні БК без еталонних: [1.56, 1.58, 1.60] -> Медіана: 1.58
        cur = MockCursor(fetchall_data=[
            ("betclic", 1.56),
            ("bwin", 1.58),
            ("betonlineag", 1.60),
        ])
        k = get_market_median_odds(cur, "ev_medvedev", "Ф2 (+4.5)", "Daniil Medvedev - Flavio Cobolli", fallback_odds=3.25)
        self.assertEqual(k, 1.58)

    def test_get_market_median_odds_fallback(self):
        # Немає даних в odds_history -> повертає fallback_odds
        cur = MockCursor(fetchall_data=[])
        k = get_market_median_odds(cur, "ev_medvedev", "Ф2 (+4.5)", "Daniil Medvedev - Flavio Cobolli", fallback_odds=1.58)
        self.assertEqual(k, 1.58)

    def test_recalculate_historical_paper_bets(self):
        # Перевірка оновлення уже розрахованих матчів: Medvedev - Cobolli Ф2 (+4.5) з 3.25 перераховується на 1.58
        conn = MockConn()
        cur = MockCursor()

        # Перший виклик SELECT для paper_bets, другий для odds_history
        rows_bets = [
            (1, "ev_medvedev", "Daniil Medvedev - Flavio Cobolli", "Ф2 (+4.5)", 3.25, 300.0, "WON", 675.0, None, None)
        ]
        rows_history = [
            ("pinnacle", 1.57),
            ("betfair_ex_eu", 1.58),
            ("marathonbet", 1.58),
        ]

        def custom_fetchall():
            q = cur.queries[-1][0]
            if "paper_bets" in q and "SELECT" in q:
                return rows_bets
            elif "odds_history" in q:
                return rows_history
            return []

        cur.fetchall = custom_fetchall

        updated = recalculate_historical_paper_bets(cur, conn)
        self.assertEqual(len(updated), 1)
        u = updated[0]
        self.assertEqual(u["id"], 1)
        self.assertEqual(u["old_odds"], 3.25)
        self.assertEqual(u["new_odds"], 1.58)
        # Профіт для WON перераховується: 300 * (1.58 - 1.0) = 174.00 грн
        self.assertEqual(u["new_profit"], 174.0)

    def test_recalculate_syncs_ai_pick(self):
        """Перевіряє, що якщо ставка була П2, а ШІ дав вердикт Ф2 (+4.5), вона синхронізується"""
        cur = MockCursor()
        conn = MockConn()
        rows_bets = [
            (28, "ev_med", "Daniil Medvedev - Flavio Cobolli", "П2", 3.89, 78.4, "PENDING", 0.0, None, None,
             "📌 Коротка ставка: Ф2 (+4.5)\n🎯 Рекомендована ставка: Утримати фору")
        ]
        rows_history = [
            ("pinnacle", 1.66),
            ("betfair_ex_eu", 1.68),
        ]

        def custom_fetchall():
            q = cur.queries[-1][0]
            if "paper_bets" in q and "SELECT" in q:
                return rows_bets
            elif "odds_history" in q:
                return rows_history
            return []

        cur.fetchall = custom_fetchall
        updated = recalculate_historical_paper_bets(cur, conn)
        self.assertEqual(len(updated), 1)
        u = updated[0]
        self.assertEqual(u["id"], 28)
        self.assertEqual(u["old_pick"], "П2")
        self.assertEqual(u["pick_label"], "Ф2 (+4.5)")
        self.assertEqual(u["new_odds"], 1.67)

    def test_manual_settle_bet(self):
        from statmonitor.paper_trading import manual_settle_bet
        cur = MockCursor(fetchone_data=(28, "Daniil Medvedev - Flavio Cobolli", "Ф2 (+4.5)", 1.67, 78.40))
        conn = MockConn()
        ok, msg = manual_settle_bet(cur, conn, 28, "13:9", forced_status="WON")
        self.assertTrue(ok)
        self.assertIn("WON", msg)
        self.assertIn("52.53", msg)


if __name__ == "__main__":
    unittest.main()
