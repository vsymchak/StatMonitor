import unittest
from datetime import datetime, timezone, timedelta
from statmonitor.real_bankroll import (
    record_real_transaction,
    get_real_bankroll_summary,
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
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

class TestOrchestrationSyncAndACID(unittest.TestCase):
    def test_adjustment_atomicity_and_sum_reconciliation(self):
        """
        Перевіряє, що для ADJUSTMENT сума amt_signed розраховується як (new_balance - current_b),
        щоб SUM(amount_uah) у леджері завжди точно дорівнювала новому балансу (SPEC-38).
        """
        # Поточний баланс 10 000 грн
        cur = MockCursor(fetchone_data=(10000.00,))
        conn = MockConn()

        # Коригуємо до 12 500 грн (+2500)
        ok, new_bal, msg = record_real_transaction(cur, conn, "ADJUSTMENT", 12500.00, "Синхронізація з касою")
        self.assertTrue(ok)
        self.assertEqual(new_bal, 12500.00)
        self.assertTrue(conn.committed)

        # Перевіряємо вставлені параметри
        insert_query, params = cur.queries[-1]
        self.assertIn("INSERT INTO real_bankroll_ledger", insert_query)
        tx_type, amt_signed, bal_after, b_id, desc = params
        self.assertEqual(tx_type, "ADJUSTMENT")
        self.assertEqual(amt_signed, 2500.00)  # Дельта!
        self.assertEqual(bal_after, 12500.00)

    def test_adjustment_negative_delta(self):
        """
        Перевіряє коректність від'ємної дельти при зменшенні балансу через ADJUSTMENT.
        """
        # Поточний баланс 15 000 грн
        cur = MockCursor(fetchone_data=(15000.00,))
        conn = MockConn()

        # Коригуємо до 11 000 грн (-4000)
        ok, new_bal, msg = record_real_transaction(cur, conn, "ADJUSTMENT", 11000.00, "Коригування після аудиту")
        self.assertTrue(ok)
        self.assertEqual(new_bal, 11000.00)

        insert_query, params = cur.queries[-1]
        amt_signed = params[1]
        self.assertEqual(amt_signed, -4000.00)

    def test_adjustment_negative_amount_as_delta(self):
        """
        Перевіряє, що від'ємна сума (наприклад -22.25) коректно зменшує баланс на цю дельту.
        """
        cur = MockCursor(fetchone_data=(3000.00,))
        conn = MockConn()

        ok, new_bal, msg = record_real_transaction(cur, conn, "ADJUSTMENT", -22.25, "Списання / коригування", is_delta=True)
        self.assertTrue(ok)
        self.assertEqual(new_bal, 2977.75)
        self.assertEqual(cur.queries[-1][1][1], -22.25)
        self.assertEqual(cur.queries[-1][1][2], 2977.75)

    def test_ledger_summary_reconciles_sum_over_stale_balance(self):
        """
        Перевіряє, що get_real_bankroll_summary використовує математичну суму леджера,
        якщо останнє поле balance_after_uah застаріло або розійшлося.
        """
        cur = MockCursor()
        call_count = [0]
        def custom_fetchone():
            call_count[0] += 1
            if call_count[0] == 1:
                # balance_after_uah = 10000, але SUM(amount_uah) = 11200
                return (10000.00, 11200.00)
            elif call_count[0] == 2:
                return (10000.00, 0.0)
            elif call_count[0] == 3:
                return (1, 0, 1, 0, 0, 500.0, 1200.0)
            return None

        cur.fetchone = custom_fetchone
        summary = get_real_bankroll_summary(cur)
        # Сума має перевагу над застарілим значенням рядка
        self.assertEqual(summary["current_balance"], 11200.00)
        self.assertEqual(summary["ledger_sum"], 11200.00)

    def test_duplicate_bet_settlement_blocked(self):
        """
        Перевіряє захист від повторного зарахування результату ставки у леджер.
        """
        cur = MockCursor()
        # 1-й запит: ставка є реальною
        # 2-й запит: ставка вже розрахована в леджері (повертає рядок 1)
        cur.fetchone = lambda: (True, "Real - Barca") if len(cur.queries) == 1 else (1,)
        conn = MockConn()

        ok, msg = settle_real_bet_in_ledger(cur, conn, 99, "WON", 500.0)
        self.assertFalse(ok)
        self.assertIn("вже зафіксовано в леджері", msg)

    def test_zero_cost_edge_rules_simulation(self):
        """
        Імітація логіки Zero-Cost Gate, що реалізована у Cloudflare Worker (checkShouldRunSupabase).
        """
        now = datetime.now(timezone.utc)

        def evaluate_edge_gate(planned_checkpoints, pending_bets, last_heartbeat):
            # 1. Запланована контрольна точка у вікні [-25m, +7m]
            t_past = now - timedelta(minutes=25)
            t_future = now + timedelta(minutes=7)
            for cp in planned_checkpoints:
                if cp["status"] == "PLANNED" and t_past <= cp["target_time"] <= t_future:
                    return True, f"Контрольна точка [{cp.get('type', 'POINT')}]"

            # 2. Ставка очікує розрахунку (почалась > 85 хв тому)
            t_due = now - timedelta(minutes=85)
            for bet in pending_bets:
                if bet["status"] == "PENDING" and bet["commence_time"] <= t_due:
                    return True, f"Ставка #{bet['id']} очікує негайного розрахунку"

            # 3. Періодичний фоновий пульс (>= 80 хв)
            if last_heartbeat is None:
                return True, "Пульс scheduler_run відсутній, перший запуск"
            mins = (now - last_heartbeat).total_seconds() / 60.0
            if mins >= 80.0:
                return True, f"Періодичний скан ліній (минуло {int(mins)} хв)"

            return False, "Zero-cost gate: пропуск"

        # Сценарій 1: Немає активностей -> Gate блокує виклик (0 хв білінгу)
        should_run, reason = evaluate_edge_gate(
            planned_checkpoints=[],
            pending_bets=[],
            last_heartbeat=now - timedelta(minutes=15)
        )
        self.assertFalse(should_run)
        self.assertIn("Zero-cost gate: пропуск", reason)

        # Сценарій 2: Є контрольна точка через 3 хв -> Gate пропускає
        should_run, reason = evaluate_edge_gate(
            planned_checkpoints=[{"status": "PLANNED", "target_time": now + timedelta(minutes=3), "type": "PRE_MATCH"}],
            pending_bets=[],
            last_heartbeat=now - timedelta(minutes=15)
        )
        self.assertTrue(should_run)
        self.assertIn("PRE_MATCH", reason)

        # Сценарій 3: Матч почався 90 хв тому -> Gate пропускає для розрахунку
        should_run, reason = evaluate_edge_gate(
            planned_checkpoints=[],
            pending_bets=[{"id": 77, "status": "PENDING", "commence_time": now - timedelta(minutes=90)}],
            last_heartbeat=now - timedelta(minutes=15)
        )
        self.assertTrue(should_run)
        self.assertIn("#77", reason)

        # Сценарій 4: Минуло 85 хв без сканування -> Gate пропускає для оновлення ліній
        should_run, reason = evaluate_edge_gate(
            planned_checkpoints=[],
            pending_bets=[],
            last_heartbeat=now - timedelta(minutes=85)
        )
        self.assertTrue(should_run)
        self.assertIn("Періодичний скан", reason)

if __name__ == "__main__":
    unittest.main()
