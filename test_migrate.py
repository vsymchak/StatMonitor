import os
import unittest
from unittest.mock import MagicMock, patch
from migrate import get_migration_files, run_migrations

class TestMigrate(unittest.TestCase):
    def test_get_migration_files_order_and_parsing(self):
        files = get_migration_files()
        self.assertGreaterEqual(len(files), 3)

        versions = [f["version"] for f in files]
        self.assertEqual(versions, sorted(versions))

        # Перевірка перших трьох обов'язкових міграцій
        self.assertEqual(files[0]["version"], "001")
        self.assertEqual(files[0]["description"], "base_schema")
        self.assertEqual(files[0]["filename"], "001_base_schema.sql")

        self.assertEqual(files[1]["version"], "002")
        self.assertEqual(files[1]["description"], "performance_indexes")

        self.assertEqual(files[2]["version"], "003")
        self.assertEqual(files[2]["description"], "v_odds_alerts")

    def test_sql_files_content_validity(self):
        files = get_migration_files()
        for f in files:
            path = f["path"]
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as sql_f:
                content = sql_f.read().strip()
            self.assertGreater(len(content), 20, f"Файл {path} занадто короткий або порожній")

            # Перевірка наявності ключових операторів DDL
            if f["version"] == "001":
                self.assertIn("CREATE TABLE IF NOT EXISTS events", content)
                self.assertIn("CREATE TABLE IF NOT EXISTS odds_history", content)
                self.assertIn("CREATE TABLE IF NOT EXISTS paper_bets", content)
            elif f["version"] == "002":
                self.assertIn("CREATE INDEX IF NOT EXISTS", content)
            elif f["version"] == "003":
                self.assertIn("CREATE OR REPLACE VIEW v_odds_alerts", content)

    @patch("migrate.get_db_connection")
    def test_run_migrations_dry_run(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value = (mock_conn, None)
        mock_conn.cursor.return_value = mock_cur

        # Припустимо, що в базі ще немає жодної міграції
        mock_cur.fetchall.return_value = []

        applied = run_migrations(db_url="postgresql://test:test@localhost/test", dry_run=True)
        self.assertIn("001", applied)
        self.assertIn("002", applied)
        self.assertIn("003", applied)
        self.assertIn("004", applied)
        # У режимі dry_run commit викликається лише один раз для ensure_migrations_table
        self.assertEqual(mock_conn.commit.call_count, 1)

    @patch("migrate.get_db_connection")
    def test_already_applied_migrations_skipped(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_get_conn.return_value = (mock_conn, None)
        mock_conn.cursor.return_value = mock_cur

        # В базі вже є версії 001 та 002
        mock_cur.fetchall.return_value = [
            ("001", "base_schema", None),
            ("002", "performance_indexes", None),
        ]

        applied = run_migrations(db_url="postgresql://test:test@localhost/test", dry_run=True)
        self.assertIn("003", applied)
        self.assertIn("004", applied)
        self.assertNotIn("001", applied)
        self.assertNotIn("002", applied)

if __name__ == "__main__":
    unittest.main()
