import unittest
from datetime import datetime, timezone, timedelta
from statmonitor.real_bankroll import (
    check_daily_stop_loss,
    check_max_exposure,
    check_correlation_guard,
    evaluate_real_risk_guardrails,
    apply_real_stakes_batch,
    prepare_real_stakes_batch,
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
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

class TestRiskGuardrails(unittest.TestCase):
    def test_daily_stop_loss_normal_profit(self):
        """Перевіряє, що при позитивному денному PnL Stop-Loss не спрацьовує."""
        cur = MockCursor()
        # 1-й fetchone: PnL = +450.0 ₴
        # 2-й fetchone: start balance = 10000.0 ₴
        call_seq = [(450.0,), (10000.0,)]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None

        res = check_daily_stop_loss(cur, threshold_pct=7.0)
        self.assertFalse(res["is_triggered"])
        self.assertEqual(res["daily_pnl_uah"], 450.0)
        self.assertEqual(res["drawdown_pct"], 0.0)
        self.assertIn("Денний прибуток", res["message"])

    def test_daily_stop_loss_minor_drawdown(self):
        """Перевіряє, що невелике просідання (3% < 7%) не активує Stop-Loss."""
        cur = MockCursor()
        # 1-й: PnL = -300.0 ₴ (3%)
        # 2-й: start balance = 10000.0 ₴
        call_seq = [(-300.0,), (10000.0,)]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None

        res = check_daily_stop_loss(cur, threshold_pct=7.0)
        self.assertFalse(res["is_triggered"])
        self.assertEqual(res["drawdown_pct"], 3.0)
        self.assertIn("3.0%", res["message"])

    def test_daily_stop_loss_triggered(self):
        """Перевіряє, що при просіданні >= 7% Stop-Loss блокує нові ставки."""
        cur = MockCursor()
        # 1-й: PnL = -750.0 ₴ (7.5% від 10000)
        # 2-й: start balance = 10000.0 ₴
        call_seq = [(-750.0,), (10000.0,)]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None

        res = check_daily_stop_loss(cur, threshold_pct=7.0)
        self.assertTrue(res["is_triggered"])
        self.assertEqual(res["drawdown_pct"], 7.5)
        self.assertIn("🛑 Stop-Loss активовано", res["message"])

    def test_max_exposure_normal(self):
        """Перевіряє нормальний рівень експозиції (< 20%)."""
        cur = MockCursor()
        # 1-й: balance = 10000.0
        # 2-й: deposits = 10000.0
        # 3-й: active exposure = 1200.0, count = 3
        call_seq = [(10000.0,), (10000.0,), (1200.0, 3)]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None

        res = check_max_exposure(cur, new_stake_total=300.0, max_exposure_pct=20.0)
        self.assertFalse(res["is_breached"])
        self.assertEqual(res["projected_exposure_uah"], 1500.0)
        self.assertEqual(res["exposure_pct"], 15.0)
        self.assertIn("🟢 Експозиція у нормі", res["message"])

    def test_max_exposure_breached(self):
        """Перевіряє фіксацію порушення ліміту експозиції (> 20%)."""
        cur = MockCursor()
        # 1-й: balance = 10000.0
        # 2-й: deposits = 10000.0
        # 3-й: active exposure = 1800.0, count = 4
        call_seq = [(10000.0,), (10000.0,), (1800.0, 4)]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None

        res = check_max_exposure(cur, new_stake_total=500.0, max_exposure_pct=20.0)
        self.assertTrue(res["is_breached"])
        self.assertEqual(res["projected_exposure_uah"], 2300.0)
        self.assertEqual(res["exposure_pct"], 23.0)
        self.assertIn("⚠️ Перевищення експозиції", res["message"])

    def test_correlation_guard_clean(self):
        """Перевіряє відсутність кореляцій для незалежних матчів."""
        cur = MockCursor()
        # active bets: Arsenal - Chelsea
        # candidate bets: Liverpool - Man City
        cur.fetchall = lambda: [(1, "ev1", "Arsenal - Chelsea", "П1")]
        res = check_correlation_guard(cur, candidate_bet_ids=[2])
        self.assertFalse(res["has_correlations"])

    def test_correlation_guard_detected(self):
        """Перевіряє виявлення ставок на один і той самий матч."""
        cur = MockCursor()
        call_count = [0]
        def custom_fetchall():
            call_count[0] += 1
            if call_count[0] == 1:
                # active bet on Real - Barca
                return [(10, "ev_el_clasico", "Real Madrid - Barcelona", "ТБ 2.5")]
            else:
                # candidate bet also on Real - Barca (Фора)
                return [(11, "ev_el_clasico", "Real Madrid - Barcelona", "Ф1 (0)")]

        cur.fetchall = custom_fetchall
        res = check_correlation_guard(cur, candidate_bet_ids=[11])
        self.assertTrue(res["has_correlations"])
        self.assertEqual(len(res["correlated_matches"]), 1)
        self.assertEqual(res["correlated_matches"][0]["count"], 2)
        self.assertIn("Real Madrid - Barcelona", res["message"])

    def test_evaluate_risk_guardrails_blocks_on_stop_loss(self):
        """Перевіряє, що evaluate_real_risk_guardrails блокує допуск ставок при Stop-Loss."""
        cur = MockCursor()
        # mock check_daily_stop_loss triggered
        call_seq = [
            (-900.0,), (10000.0,), # stop loss -> -9.0% >= 7%
            (10000.0,), (10000.0,), (500.0, 1), # max exposure
        ]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None
        cur.fetchall = lambda: [] # no correlations

        eval_res = evaluate_real_risk_guardrails(cur, candidate_configs=[{"id": 1, "real_stake": 200.0}])
        self.assertFalse(eval_res["can_place_bets"])
        self.assertTrue(len(eval_res["blocks"]) > 0)
        self.assertIn("Stop-Loss", eval_res["blocks"][0])

    def test_apply_real_stakes_batch_blocked_by_guardrails(self):
        """Перевіряє, що apply_real_stakes_batch відмовляє у фіксації ставок при блокуванні."""
        cur = MockCursor()
        call_seq = [
            (-900.0,), (10000.0,), # stop loss triggered (-9%)
            (10000.0,), (10000.0,), (500.0, 1),
        ]
        cur.fetchone = lambda: call_seq.pop(0) if call_seq else None
        cur.fetchall = lambda: []
        conn = MockConn()

        ok, cnt, tot, msg = apply_real_stakes_batch(cur, conn, [{"id": 1, "real_stake": 200.0}])
        self.assertFalse(ok)
        self.assertEqual(cnt, 0)
        self.assertIn("Запобіжники капіталу заблокували ставки", msg)
        self.assertFalse(conn.committed)

    def test_apply_real_stakes_batch_bypass_guardrails(self):
        """Перевіряє, що з прапорцем bypass_guardrails=True адміністратор може форсувати дію."""
        cur = MockCursor()
        # toggle_real_bet queries: SELECT id, match_name, odds, stake_uah FROM paper_bets WHERE id = %s
        cur.fetchone = lambda: (1, "Arsenal - Chelsea", 1.95, 300.0)
        conn = MockConn()

        ok, cnt, tot, msg = apply_real_stakes_batch(
            cur, conn, [{"id": 1, "real_stake": 200.0, "real_odds": 1.95}],
            bypass_guardrails=True
        )
        self.assertTrue(ok)
        self.assertEqual(cnt, 1)
        self.assertEqual(tot, 200.0)
        self.assertTrue(conn.committed)

if __name__ == "__main__":
    unittest.main()
