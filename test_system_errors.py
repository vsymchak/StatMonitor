import unittest
from unittest.mock import MagicMock
from statmonitor.database import log_system_error, fetch_system_errors, resolve_system_errors

class TestSystemErrors(unittest.TestCase):
    def test_log_system_error(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock(spec=["execute", "fetchall", "fetchone", "description", "close"])
        mock_conn.cursor.return_value = mock_cur

        log_system_error(
            mock_conn,
            source="odds_api",
            message="Test error 422",
            severity="ERROR",
            error_code="HTTP_422",
            details={"sport": "soccer_uefa_champs_league"}
        )

        mock_cur.execute.assert_called_once()
        args = mock_cur.execute.call_args[0]
        self.assertIn("INSERT INTO system_errors", args[0])
        params = args[1]
        self.assertEqual(params[0], "odds_api")
        self.assertEqual(params[1], "ERROR")
        self.assertEqual(params[2], "HTTP_422")
        self.assertEqual(params[3], "Test error 422")
        self.assertIn("soccer_uefa_champs_league", params[4])
        mock_conn.commit.assert_called_once()

    def test_fetch_system_errors(self):
        mock_cur = MagicMock(spec=["execute", "fetchall", "fetchone", "description", "close"])
        mock_cur.fetchall.return_value = [
            (10, "sx_bet", "ERROR", "INSUFFICIENT_BALANCE", "Balance < 1.0", None, "2026-11-24T12:00:00Z")
        ]
        res = fetch_system_errors(mock_cur, limit=5, unresolved_only=True)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], 10)
        self.assertEqual(res[0]["source"], "sx_bet")
        self.assertEqual(res[0]["error_code"], "INSUFFICIENT_BALANCE")

    def test_resolve_system_errors(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock(spec=["execute", "fetchall", "fetchone", "description", "close"])
        mock_conn.cursor.return_value = mock_cur

        # Вирішення всіх
        resolve_system_errors(mock_conn)
        self.assertIn("UPDATE system_errors SET resolved_at = NOW()", mock_cur.execute.call_args[0][0])
        mock_conn.commit.assert_called_once()

        # Вирішення списку ID
        resolve_system_errors(mock_conn, error_ids=[1, 2, 3])
        self.assertIn("WHERE id = ANY(%s)", mock_cur.execute.call_args[0][0])

if __name__ == "__main__":
    unittest.main()
