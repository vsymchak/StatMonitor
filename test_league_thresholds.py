import unittest
import tempfile
import os
import json
from unittest.mock import MagicMock
from statmonitor.league_config import (
    fetch_db_leagues,
    sync_leagues_to_db,
    save_league_threshold,
    save_all_leagues_to_file,
    reset_league_thresholds_to_default,
    get_league_thresholds,
    load_leagues_config,
    DEFAULT_LEAGUES_CONFIG,
)

class TestLeagueThresholds(unittest.TestCase):
    def test_fetch_db_leagues(self):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("soccer_epl", "Англія (АПЛ)", "soccer", True, 5.0, 1.40, 4.00, '["h2h", "totals", "spreads", "btts"]'),
            ("basketball_nba", "США (NBA)", "basketball", False, 4.0, 1.35, 4.20, ["h2h", "spreads"]),
        ]
        leagues = fetch_db_leagues(mock_cur)
        self.assertIsNotNone(leagues)
        self.assertEqual(len(leagues), 2)
        
        epl = leagues[0]
        self.assertEqual(epl["key"], "soccer_epl")
        self.assertEqual(epl["title"], "Англія (АПЛ)")
        self.assertTrue(epl["enabled"])
        self.assertEqual(epl["min_drop_pct"], 5.0)
        self.assertIn("btts", epl["markets"])

        nba = leagues[1]
        self.assertEqual(nba["key"], "basketball_nba")
        self.assertFalse(nba["enabled"])
        self.assertEqual(nba["markets"], ["h2h", "spreads"])

    def test_fetch_db_leagues_empty_or_none(self):
        self.assertIsNone(fetch_db_leagues(None))
        
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        self.assertIsNone(fetch_db_leagues(mock_cur))

    def test_save_league_threshold(self):
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_cur.fetchone.return_value = ("Англія (АПЛ)", "soccer", True, 5.0, 1.40, 4.00, ["h2h", "totals"])

        ok, msg = save_league_threshold(
            mock_cur, mock_conn,
            sport_key="soccer_epl",
            enabled=False,
            min_drop_pct=6.5,
            min_odds=1.50,
            max_odds=3.80,
            markets=["h2h", "btts"],
        )
        self.assertTrue(ok)
        mock_conn.commit.assert_called_once()
        self.assertIn("soccer_epl", msg)

    def test_sync_leagues_to_db_and_force(self):
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        
        # 1. Якщо вже заповнено і force=False
        mock_cur.fetchone.return_value = [25]
        ok, msg = sync_leagues_to_db(mock_cur, mock_conn, force=False)
        self.assertTrue(ok)
        self.assertIn("вже містить 25 ліг", msg)

        # 2. force=True -> перезаписує
        ok2, msg2 = sync_leagues_to_db(mock_cur, mock_conn, force=True)
        self.assertTrue(ok2)
        self.assertIn("Успішно синхронізовано", msg2)
        mock_conn.commit.assert_called()

    def test_save_all_leagues_to_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            temp_path = f.name

        try:
            sample_leagues = [
                {"key": "soccer_test", "title": "Test League", "enabled": True, "min_drop_pct": 5.5, "min_odds": 1.45, "max_odds": 3.90, "markets": ["h2h"]}
            ]
            ok, msg = save_all_leagues_to_file(sample_leagues, config_path=temp_path)
            self.assertTrue(ok)
            
            with open(temp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("leagues", data)
            self.assertEqual(data["leagues"][0]["key"], "soccer_test")
            self.assertEqual(data["leagues"][0]["min_drop_pct"], 5.5)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_get_league_thresholds_with_db_cur(self):
        mock_cur = MagicMock()
        # Повертає (min_drop_pct, min_odds, max_odds, markets, enabled)
        mock_cur.fetchone.return_value = (6.0, 1.45, 3.80, '["h2h", "totals", "btts"]', False)

        th = get_league_thresholds("soccer_epl", cur=mock_cur)
        self.assertEqual(th["min_drop_pct"], 6.0)
        self.assertEqual(th["min_odds"], 1.45)
        self.assertEqual(th["max_odds"], 3.80)
        self.assertFalse(th["enabled"])
        self.assertIn("btts", th["markets"])

    def test_save_all_leagues_batch(self):
        from statmonitor.league_config import save_all_leagues_batch
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        leagues = [
            {"key": "icehockey_nhl", "title": "НХЛ", "category": "icehockey", "enabled": True, "min_drop_pct": 4.5, "min_odds": 1.35, "max_odds": 4.20, "markets": ["h2h", "totals"]},
            {"key": "basketball_nba", "title": "NBA", "category": "basketball", "enabled": True, "min_drop_pct": 4.0, "min_odds": 1.35, "max_odds": 4.20, "markets": ["h2h"]},
        ]
        ok, msg = save_all_leagues_batch(mock_cur, mock_conn, leagues)
        self.assertTrue(ok)
        self.assertIn("Успішно збережено 2 ліг", msg)
        mock_conn.commit.assert_called()

    def test_load_leagues_config_with_cur_merge(self):
        mock_cur = MagicMock()
        # Імітуємо збережену в БД НХЛ як enabled=True
        mock_cur.fetchall.return_value = [
            ("icehockey_nhl", "США/Канада (НХЛ / NHL)", "icehockey", True, 4.5, 1.35, 4.20, ["h2h", "totals", "spreads"])
        ]
        cfg = load_leagues_config(cur=mock_cur)
        nhl_matches = [lg for lg in cfg["leagues"] if lg["key"] == "icehockey_nhl"]
        self.assertTrue(len(nhl_matches) > 0)
        self.assertTrue(nhl_matches[0]["enabled"])

    def test_reset_league_thresholds_to_default(self):
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        ok, msg = reset_league_thresholds_to_default(mock_cur, mock_conn)
        self.assertTrue(ok)
        mock_conn.commit.assert_called()

if __name__ == "__main__":
    unittest.main()
