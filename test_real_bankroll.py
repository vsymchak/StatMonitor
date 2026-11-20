import unittest
from unittest.mock import MagicMock
from statmonitor.real_bankroll import (
    ensure_real_bankroll_tables,
    get_real_bankroll_summary,
    record_real_transaction,
    toggle_real_bet,
    settle_real_bet_in_ledger,
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
    def commit(self): pass
    def rollback(self): pass

class TestRealBankroll(unittest.TestCase):
    def test_ensure_real_bankroll_tables(self):
        cur = MockCursor()
        conn = MockConn()
        ensure_real_bankroll_tables(cur, conn)
        self.assertTrue(len(cur.queries) >= 1)
        sql = cur.queries[0][0]
        self.assertIn("real_bankroll_ledger", sql)
        self.assertIn("is_real_bet", sql)

    def test_get_real_bankroll_summary_defaults(self):
        cur = MockCursor(fetchone_data=None)
        summary = get_real_bankroll_summary(cur)
        self.assertEqual(summary["current_balance"], 0.0)
        self.assertEqual(summary["initial_bank"], 0.0)
        self.assertEqual(summary["total_deposits"], 0.0)
        self.assertEqual(summary["total_real_bets"], 0)
        self.assertEqual(summary["real_profit"], 0.0)
        self.assertEqual(summary["real_roi_pct"], 0.0)

    def test_get_real_bankroll_summary_with_data(self):
        cur = MockCursor()
        # Mock answers for 3 queries in get_real_bankroll_summary
        call_count = [0]
        def custom_fetchone():
            call_count[0] += 1
            if call_count[0] == 1:
                return (12450.00,) # balance_after_uah
            elif call_count[0] == 2:
                return (10000.00, 0.0) # deposits, withdrawals
            elif call_count[0] == 3:
                # count, pending, won, lost, void, turnover, profit
                return (5, 1, 3, 1, 0, 1000.00, 2450.00)
            return None

        cur.fetchone = custom_fetchone
        summary = get_real_bankroll_summary(cur)
        self.assertEqual(summary["current_balance"], 12450.00)
        self.assertEqual(summary["initial_bank"], 10000.00)
        self.assertEqual(summary["total_deposits"], 10000.00)
        self.assertEqual(summary["total_real_bets"], 5)
        self.assertEqual(summary["won_real"], 3)
        self.assertEqual(summary["lost_real"], 1)
        self.assertEqual(summary["pending_real"], 1)
        self.assertEqual(summary["real_turnover"], 1000.00)
        self.assertEqual(summary["real_profit"], 2450.00)
        self.assertEqual(summary["real_roi_pct"], 245.0)
        self.assertEqual(summary["real_win_rate"], 75.0)

    def test_record_real_transaction_deposit(self):
        cur = MockCursor(fetchone_data=(10000.0,))
        conn = MockConn()
        ok, new_bal, msg = record_real_transaction(cur, conn, "DEPOSIT", 5000.0, "Поповнення з картки")
        self.assertTrue(ok)
        self.assertEqual(new_bal, 15000.0)
        self.assertIn("DEPOSIT", msg)
        self.assertIn("15,000.00", msg)

    def test_record_real_transaction_withdrawal(self):
        cur = MockCursor(fetchone_data=(15000.0,))
        conn = MockConn()
        ok, new_bal, msg = record_real_transaction(cur, conn, "WITHDRAWAL", 3000.0, "Виведення виграшу")
        self.assertTrue(ok)
        self.assertEqual(new_bal, 12000.0)
        self.assertIn("WITHDRAWAL", msg)

    def test_record_real_transaction_adjustment(self):
        cur = MockCursor(fetchone_data=(12000.0,))
        conn = MockConn()
        ok, new_bal, msg = record_real_transaction(cur, conn, "ADJUSTMENT", 20000.0, "Синхронізація з касою БК")
        self.assertTrue(ok)
        self.assertEqual(new_bal, 20000.0)

    def test_record_real_transaction_bet_result(self):
        cur = MockCursor(fetchone_data=(20000.0,))
        conn = MockConn()
        ok, new_bal, msg = record_real_transaction(cur, conn, "BET_RESULT", 350.50, "Виграш ставки #44", bet_id=44)
        self.assertTrue(ok)
        self.assertEqual(new_bal, 20350.50)

    def test_toggle_real_bet_to_real(self):
        cur = MockCursor(fetchone_data=(42, "Arsenal - Chelsea", 1.95, 300.0))
        conn = MockConn()
        ok, msg = toggle_real_bet(cur, conn, 42, is_real=True, real_stake=500.0, real_odds=1.92, bookmaker="Favbet")
        self.assertTrue(ok)
        self.assertIn("Реальна ставка", msg)
        self.assertIn("#42", msg)
        # Check update query
        q, params = cur.queries[-1]
        self.assertIn("UPDATE paper_bets", q)
        self.assertIn("is_real_bet = %s", q)
        self.assertIn("real_stake_uah = %s", q)
        self.assertIn("real_odds = %s", q)
        self.assertIn("bookmaker_name = %s", q)
        self.assertEqual(params[0], True)
        self.assertEqual(params[1], 500.0)
        self.assertEqual(params[2], 1.92)
        self.assertEqual(params[3], "Favbet")

    def test_toggle_real_bet_to_paper(self):
        cur = MockCursor(fetchone_data=(42, "Arsenal - Chelsea", 1.95, 300.0))
        conn = MockConn()
        ok, msg = toggle_real_bet(cur, conn, 42, is_real=False)
        self.assertTrue(ok)
        self.assertIn("Віртуальна ставка", msg)

    def test_settle_real_bet_in_ledger_success(self):
        cur = MockCursor()
        # 1st query: check is_real_bet -> (True, "Arsenal - Chelsea")
        # 2nd query: check already settled -> None
        # 3rd query: get last balance in record_real_transaction -> (10000.0,)
        # 4th query: INSERT returning id -> (1,)
        call_seq = [(True, "Arsenal - Chelsea"), None, (10000.0,), (1,)]
        def seq_fetchone():
            return call_seq.pop(0) if call_seq else None
        cur.fetchone = seq_fetchone
        conn = MockConn()

        ok, msg = settle_real_bet_in_ledger(cur, conn, 42, "WON", 450.0, stake_uah=500.0)
        self.assertTrue(ok)
        self.assertIn("10,450.00", msg)

    def test_settle_real_bet_in_ledger_not_real(self):
        cur = MockCursor(fetchone_data=(False, "Arsenal - Chelsea"))
        conn = MockConn()
        ok, msg = settle_real_bet_in_ledger(cur, conn, 42, "WON", 450.0)
        self.assertFalse(ok)
        self.assertIn("не є реальною", msg)

    def test_real_stake_integer_rounding(self):
        from statmonitor.novig import calculate_real_stake
        # При балансі 7,686 ₴ та 5% ліміті (384.30 ₴) ставка має бути рівно цілими гривнями (384 ₴ або 380 ₴), без копійок!
        stake, pct, msg = calculate_real_stake(
            odds=1.49,
            real_balance=7686.0,
            confidence=9,
            drop_pct=10.0,
            fraction=0.10,
            max_pct=0.05
        )
        self.assertEqual(msg, "OK")
        self.assertEqual(stake, round(stake))
        self.assertEqual(stake % 1.0, 0.0)

        # Тест toggle_real_bet з копійками -> має округлити до цілих гривень
        cur = MockCursor(fetchone_data=(56, "Ben Shelton - Rafael Jodar", 1.49, 384.30))
        conn = MockConn()
        ok, _ = toggle_real_bet(cur, conn, 56, is_real=True, real_stake=384.30)
        self.assertTrue(ok)
        q, params = cur.queries[1]
        self.assertEqual(params[1], 384.0)

    def test_settle_real_bet_in_ledger_duplicate(self):
        cur = MockCursor()
        cur.fetchone = lambda: (True, "Arsenal - Chelsea") if len(cur.queries) == 1 else (1,)
        conn = MockConn()
        ok, msg = settle_real_bet_in_ledger(cur, conn, 42, "WON", 450.0)
        self.assertFalse(ok)
        self.assertIn("вже зафіксовано в леджері", msg)

if __name__ == "__main__":
    unittest.main()
