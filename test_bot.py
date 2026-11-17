import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from statmonitor.bot import (
    is_authorized,
    cmd_start_help,
    cmd_status,
    cmd_bank,
    cmd_bets,
    cmd_today,
    cmd_schedule,
    cmd_run_now,
    handle_command,
    process_telegram_update,
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

class TestBot(unittest.TestCase):
    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_authorization(self):
        self.assertTrue(is_authorized(123456789))
        self.assertTrue(is_authorized("123456789"))
        self.assertFalse(is_authorized(987654321))
        self.assertFalse(is_authorized("attacker_chat"))

    def test_cmd_start_help(self):
        txt = cmd_start_help()
        self.assertIn("StatMonitor AI Assistant", txt)
        self.assertIn("/status", txt)
        self.assertIn("/bank", txt)
        self.assertIn("/bets", txt)
        self.assertIn("/run_now", txt)

    def test_cmd_status(self):
        now = datetime(2026, 11, 16, 14, 0, tzinfo=timezone.utc)
        cur = MockCursor()

        # Налаштовуємо динамічну відповідь для різних запитів
        def custom_fetchone():
            q = cur.queries[-1][0]
            if "system_heartbeat" in q:
                return (now, "OK", 1.25, {})
            elif "scheduler_plan" in q:
                return (now + timedelta(minutes=45), "PRE_MATCH", "Перед грою: Arsenal - Chelsea")
            return None

        def custom_fetchall():
            q = cur.queries[-1][0]
            if "sports_poll_log" in q:
                return [("HOT", 4), ("WARM", 6), ("COLD", 4)]
            return []

        cur.fetchone = custom_fetchone
        cur.fetchall = custom_fetchall

        txt = cmd_status(cur)
        self.assertIn("СТАТУС СИСТЕМИ", txt)
        self.assertIn("Пульс:", txt)
        self.assertIn("HOT (< 6 год): <b>4</b>", txt)
        self.assertIn("Arsenal - Chelsea", txt)

    def test_cmd_bank(self):
        cur = MockCursor(fetchall_data=[
            ("WON", 300.0, 270.0),
            ("LOST", 200.0, -200.0),
            ("VOID", 100.0, 0.0),
            ("PENDING", 250.0, 0.0),
        ])

        txt = cmd_bank(cur)
        self.assertIn("ФІНАНСОВИЙ ЗВІТ", txt)
        self.assertIn("10,070.00 грн", txt) # Поточний капітал: 10000 + 70 = 10070
        self.assertIn("9,820.00 грн", txt)  # Вільні кошти: 10070 - 250 = 9820
        self.assertIn("+70.00 грн", txt)    # Чистий профіт
        self.assertIn("11.67%", txt)        # ROI
        self.assertIn("50.0%", txt)         # Вінрейт: 1 won / 2 settled

    def test_cmd_bets_empty(self):
        cur = MockCursor(fetchall_data=[])
        txt = cmd_bets(cur)
        self.assertIn("Наразі немає активних ставок", txt)

    def test_cmd_bets_with_items(self):
        now = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)
        cur = MockCursor(fetchall_data=[
            ("Arsenal - Chelsea", "soccer_epl", "Ф1 (-1.5)", 1.95, 300.0, now)
        ])
        txt = cmd_bets(cur)
        self.assertIn("АКТИВНІ СТАВКИ", txt)
        self.assertIn("Arsenal - Chelsea", txt)
        self.assertIn("Ф1 (-1.5)", txt)
        self.assertIn("300.00 грн", txt)

    def test_cmd_today_empty(self):
        cur = MockCursor(fetchall_data=[])
        txt = cmd_today(cur)
        self.assertIn("немає розрахованих ставок", txt)

    def test_cmd_today_with_items(self):
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        cur = MockCursor(fetchall_data=[
            ("Arsenal - Chelsea", "Ф1 (-1.5)", 1.95, 300.0, "WON", 285.0, "3:1", now),
            ("Real - Barca", "ТБ 2.5", 1.80, 200.0, "LOST", -200.0, "1:0", now),
        ])
        txt = cmd_today(cur)
        self.assertIn("РЕЗУЛЬТАТИ ЗА ДОБУ", txt)
        self.assertIn("+85.00 грн", txt)
        self.assertIn("Arsenal - Chelsea", txt)
        self.assertIn("[Рахунок: 3:1]", txt)

    def test_cmd_schedule(self):
        now = datetime(2026, 11, 16, 18, 45, tzinfo=timezone.utc)
        cur = MockCursor(fetchall_data=[
            (now, "PRE_MATCH", "Перед грою: Arsenal - Chelsea")
        ])
        txt = cmd_schedule(cur)
        self.assertIn("КОНТРОЛЬНІ ТОЧКИ", txt)
        self.assertIn("Arsenal - Chelsea", txt)

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_handle_command_unauthorized(self):
        cur = MockCursor()
        conn = MockConn()
        resp, markup = handle_command("/status", 999999999, cur, conn)
        self.assertIn("Доступ обмежено", resp)
        self.assertIsNone(markup)

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_handle_command_unknown(self):
        cur = MockCursor()
        conn = MockConn()
        resp, markup = handle_command("/foobar", 123456789, cur, conn)
        self.assertIn("Невідома команда", resp)
        self.assertIsNotNone(markup)

    @patch("statmonitor.bot.send_tg")
    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_process_telegram_update(self, mock_send):
        cur = MockCursor()
        conn = MockConn()
        update = {
            "update_id": 1001,
            "message": {
                "chat": {"id": 123456789},
                "text": "/help",
            }
        }
        res = process_telegram_update(update, cur, conn)
        self.assertIsNotNone(res)
        self.assertIn("StatMonitor AI Assistant", res)
        mock_send.assert_called_once()

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_handle_command_edit_odds_usage(self):
        cur = MockCursor()
        conn = MockConn()
        resp, markup = handle_command("/edit_odds", 123456789, cur, conn)
        self.assertIn("Формат команди", resp)
        self.assertIn("/edit_odds", resp)
        self.assertIn("новий_коефіцієнт", resp)

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    def test_handle_command_edit_odds_invalid_args(self):
        cur = MockCursor()
        conn = MockConn()
        resp, markup = handle_command("/edit_odds abc def", 123456789, cur, conn)
        self.assertIn("Помилка аргументів", resp)

    @patch("statmonitor.bot.TG_CHAT_ID", "123456789")
    @patch("statmonitor.paper_trading.update_pending_bet_odds")
    def test_handle_command_edit_odds_success(self, mock_update):
        mock_update.return_value = (True, "OK", 3.25)
        cur = MockCursor(fetchone_data=("Medvedev - Cobolli", "Ф2 (+4.5)", 100.0, 1.58))
        conn = MockConn()
        resp, markup = handle_command("/edit_odds 28 1.58", 123456789, cur, conn)
        self.assertIn("Коефіцієнт успішно змінено", resp)
        self.assertIn("Medvedev - Cobolli", resp)
        self.assertIn("1.58", resp)
        self.assertIn("58.00 грн", resp)

if __name__ == "__main__":
    unittest.main()
