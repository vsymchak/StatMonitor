import unittest
import tempfile
import os
import json
from statmonitor.league_config import (
    load_leagues_config,
    get_active_sports_map,
    get_active_target_sports,
    get_league_thresholds,
    DEFAULT_LEAGUES_CONFIG,
)

class TestLeagueConfig(unittest.TestCase):
    def test_load_default_config(self):
        cfg = load_leagues_config()
        self.assertIsInstance(cfg, dict)
        self.assertIn("leagues", cfg)
        self.assertGreaterEqual(len(cfg["leagues"]), 14)

    def test_get_active_sports_map_and_targets(self):
        cfg = load_leagues_config()
        s_map = get_active_sports_map(cfg)
        targets = get_active_target_sports(cfg)

        self.assertIn("soccer_epl", s_map)
        self.assertEqual(s_map["soccer_epl"], "Англія (АПЛ)")
        self.assertIn("basketball_nba", targets)
        self.assertEqual(len(s_map), len(targets))

    def test_disabled_league_filtering(self):
        mock_cfg = {
            "version": "1.0",
            "leagues": [
                {"key": "soccer_epl", "title": "EPL", "enabled": True},
                {"key": "soccer_paused", "title": "Paused League", "enabled": False},
                {"key": "soccer_default", "title": "Default Enabled"},
            ]
        }
        s_map = get_active_sports_map(mock_cfg)
        targets = get_active_target_sports(mock_cfg)

        self.assertIn("soccer_epl", s_map)
        self.assertIn("soccer_default", s_map)
        self.assertNotIn("soccer_paused", s_map)
        self.assertNotIn("soccer_paused", targets)

    def test_league_thresholds(self):
        mock_cfg = {
            "version": "1.0",
            "leagues": [
                {
                    "key": "basketball_nba",
                    "title": "NBA",
                    "min_drop_pct": 3.8,
                    "min_odds": 1.30,
                    "max_odds": 4.50,
                    "markets": ["h2h", "spreads"],
                }
            ]
        }
        th_nba = get_league_thresholds("basketball_nba", mock_cfg)
        self.assertEqual(th_nba["min_drop_pct"], 3.8)
        self.assertEqual(th_nba["min_odds"], 1.30)
        self.assertEqual(th_nba["max_odds"], 4.50)
        self.assertEqual(th_nba["markets"], ["h2h", "spreads"])

        # Невідомий турнір -> дефолт
        th_def = get_league_thresholds("unknown_sport", mock_cfg)
        self.assertEqual(th_def["min_drop_pct"], 5.0)
        self.assertEqual(th_def["min_odds"], 1.40)
        self.assertEqual(th_def["max_odds"], 4.00)

    def test_fallback_on_missing_or_corrupt_file(self):
        # 1. Неіснуючий файл
        cfg_missing = load_leagues_config("/path/to/non_existent_file.json")
        self.assertEqual(cfg_missing, DEFAULT_LEAGUES_CONFIG)

        # 2. Пошкоджений JSON
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
            f.write("{corrupt json content...")
            corrupt_path = f.name

        try:
            cfg_corrupt = load_leagues_config(corrupt_path)
            self.assertEqual(cfg_corrupt, DEFAULT_LEAGUES_CONFIG)
        finally:
            if os.path.exists(corrupt_path):
                os.remove(corrupt_path)

if __name__ == "__main__":
    unittest.main()
