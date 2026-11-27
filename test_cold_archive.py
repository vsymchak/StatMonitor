import unittest
import os
import io
import tempfile
import shutil
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
try:
    import pandas as pd
except ImportError:
    pd = None

from statmonitor.cold_archive import (
    records_to_parquet_bytes,
    upload_to_r2,
    archive_cold_odds,
    get_cold_archive_summary,
    _get_signature_key,
    _sign,
)

@unittest.skipIf(pd is None, "pandas is not installed in local Python environment")
class TestColdOddsArchive(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_records_to_parquet_bytes(self):
        # 1. Empty records
        self.assertEqual(records_to_parquet_bytes([]), b"")

        # 2. Non-empty records
        records = [
            {
                "id": 1,
                "event_id": "ev_101",
                "sport": "soccer_epl",
                "bookmaker": "Pinnacle",
                "market_key": "h2h",
                "outcome_name": "Arsenal",
                "point": None,
                "price": 1.95,
                "recorded_at": "2026-11-19 14:00:00",
            },
            {
                "id": 2,
                "event_id": "ev_101",
                "sport": "soccer_epl",
                "bookmaker": "Pinnacle",
                "market_key": "h2h",
                "outcome_name": "Chelsea",
                "point": None,
                "price": 3.80,
                "recorded_at": "2026-11-19 14:00:00",
            },
        ]
        pq_bytes = records_to_parquet_bytes(records)
        self.assertGreater(len(pq_bytes), 0)

        # Read back with pandas
        df_read = pd.read_parquet(io.BytesIO(pq_bytes))
        self.assertEqual(len(df_read), 2)
        self.assertEqual(list(df_read["bookmaker"]), ["Pinnacle", "Pinnacle"])
        self.assertAlmostEqual(df_read["price"].iloc[0], 1.95)

    def test_upload_local_fallback(self):
        data = b"PARQUET_TEST_BYTES"
        obj_key = "odds_history/year=2026/month=11/odds_2026_11_19.parquet"

        with patch("statmonitor.cold_archive.R2_ACCESS_KEY_ID", None), \
             patch("statmonitor.cold_archive.LOCAL_ARCHIVE_DIR", self.test_dir):
            success, uri, st_type = upload_to_r2(data, obj_key)
            self.assertTrue(success)
            self.assertEqual(st_type, "LOCAL")
            self.assertTrue(uri.startswith("local://"))
            
            # File should exist on disk
            expected_file = os.path.join(self.test_dir, obj_key.replace("/", os.sep))
            self.assertTrue(os.path.exists(expected_file))
            with open(expected_file, "rb") as f:
                self.assertEqual(f.read(), data)

    def test_upload_to_r2_sigv4_mocked(self):
        data = b"PARQUET_BINARY_CONTENT"
        obj_key = "test_key.parquet"

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("statmonitor.cold_archive.R2_ACCOUNT_ID", "fake_acc"), \
             patch("statmonitor.cold_archive.R2_ACCESS_KEY_ID", "fake_key_id"), \
             patch("statmonitor.cold_archive.R2_SECRET_ACCESS_KEY", "fake_secret"), \
             patch("statmonitor.cold_archive.R2_BUCKET_NAME", "my-bucket"), \
             patch("statmonitor.cold_archive.requests.put", return_value=mock_resp) as mock_put:

            success, uri, st_type = upload_to_r2(data, obj_key)
            self.assertTrue(success)
            self.assertEqual(st_type, "R2")
            self.assertEqual(uri, "r2://my-bucket/test_key.parquet")
            mock_put.assert_called_once()

            # Verify SigV4 Authorization header was passed
            call_kwargs = mock_put.call_args[1]
            self.assertIn("Authorization", call_kwargs["headers"])
            self.assertTrue(call_kwargs["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256"))

    def test_archive_cold_odds_execution(self):
        dt_old = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        mock_rows = [
            (101, "ev_1", "soccer_epl", "Arsenal - Chelsea", dt_old, "Pinnacle", "h2h", "Arsenal", None, 1.95, dt_old),
            (102, "ev_1", "soccer_epl", "Arsenal - Chelsea", dt_old, "Pinnacle", "h2h", "Draw", None, 3.40, dt_old),
        ]

        mock_cur = MagicMock()
        mock_conn = MagicMock()

        # Mock get_cols to return recorded_at
        with patch("statmonitor.cold_archive.get_cols", return_value={"recorded_at", "event_id", "price"}), \
             patch("statmonitor.cold_archive.LOCAL_ARCHIVE_DIR", self.test_dir), \
             patch("statmonitor.cold_archive.R2_ACCESS_KEY_ID", None):

            mock_cur.fetchall.return_value = mock_rows

            res = archive_cold_odds(mock_cur, mock_conn, min_age_days=3.5)
            self.assertTrue(res["success"])
            self.assertEqual(res["total_records"], 2)
            self.assertEqual(res["files_created"], 1)
            self.assertGreater(res["total_bytes"], 0)
            mock_conn.commit.assert_called()

    def test_get_cold_archive_summary(self):
        mock_cur = MagicMock()
        # Row 1: files_count, total_records, total_bytes, latest_partition, latest_archive_time
        mock_cur.fetchone.return_value = (5, 12500, 2097152, "2026-11-19", datetime(2026, 11, 23, 10, 0))
        # Row 2: history
        mock_cur.fetchall.return_value = [
            (1, "2026-11-19", "R2", "r2://bucket/key.parquet", 512000, 3000, "sha256abc", datetime(2026, 11, 23, 10, 0))
        ]

        summary = get_cold_archive_summary(mock_cur)
        self.assertTrue(summary["has_data"])
        self.assertEqual(summary["files_count"], 5)
        self.assertEqual(summary["total_records"], 12500)
        self.assertEqual(summary["total_mb"], 2.0)
        self.assertEqual(summary["latest_partition"], "2026-11-19")
        self.assertEqual(len(summary["recent_files"]), 1)
        self.assertEqual(summary["recent_files"][0]["storage_type"], "R2")

if __name__ == "__main__":
    unittest.main()
