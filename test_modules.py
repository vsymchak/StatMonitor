import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from statmonitor.config import INITIAL_BANKROLL, KYIV_TZ, SPORTS_MAP, TARGET_SPORTS
from statmonitor.notifier import esc, fmt_kyiv
from statmonitor.database import pick, pick_v
from statmonitor.ai import extract_short_pick
from statmonitor.paper_trading import format_pick, eval_outcome
import main

class TestModularDecomposition(unittest.TestCase):
    def test_config_constants(self):
        self.assertEqual(INITIAL_BANKROLL, 10000.00)
        self.assertIsNotNone(KYIV_TZ)
        self.assertGreater(len(SPORTS_MAP), 10)
        self.assertIn("soccer_epl", TARGET_SPORTS)

    def test_notifier_helpers(self):
        self.assertEqual(esc("Arsenal & Chelsea <3>"), "Arsenal &amp; Chelsea &lt;3&gt;")
        dt_utc = datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc)
        self.assertIn("12:00", fmt_kyiv(dt_utc))

    def test_database_pick_helpers(self):
        cols = {"event_id", "created_at", "price"}
        self.assertEqual(pick(cols, ("match_id", "event_id")), "event_id")
        self.assertIsNone(pick(cols, ("missing_col",)))

        d = {"status": "WON", "stake": 250}
        self.assertEqual(pick_v(d, ("st", "stake")), 250)
        self.assertEqual(pick_v(d, ("not_there",), default=10), 10)

    def test_ai_extract_short_pick(self):
        verdict = (
            "📌 **Коротка ставка:** Ф2 (+1.5)\n"
            "🎯 **Рекомендована ставка:** Брати фору гостей.\n"
            "🏥 **Склади:** Основні гравці готові."
        )
        self.assertEqual(extract_short_pick(verdict, fallback="П1"), "Ф2 (+1.5)")

        skip_verdict = (
            "📌 **Коротка ставка:** Пропустити\n"
            "🎯 **Рекомендована ставка:** Пропустити матч через високу маржу."
        )
        self.assertEqual(extract_short_pick(skip_verdict, fallback="П1"), "⏭ Пропустити матч")

    def test_paper_trading_format_and_eval(self):
        # 1. Totals
        pick_lbl = format_pick("totals", "Over", 2.5, "Arsenal - Chelsea")
        self.assertEqual(pick_lbl, "ТБ 2.5")

        # 2. Spreads
        pick_lbl_sp = format_pick("spreads", "Arsenal", -1.0, "Arsenal - Chelsea")
        self.assertEqual(pick_lbl_sp, "Ф1 (-1)")

        # 3. Outcomes
        self.assertEqual(eval_outcome("ТБ 2.5", "Arsenal - Chelsea", 2, 1), "WON")
        self.assertEqual(eval_outcome("ТБ 2.5", "Arsenal - Chelsea", 1, 1), "LOST")
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 2, 0), "WON")
        self.assertEqual(eval_outcome("Ф1 (-1)", "Arsenal - Chelsea", 2, 1), "VOID")
        self.assertEqual(eval_outcome("П1", "Arsenal - Chelsea", 2, 1), "WON")
        self.assertEqual(eval_outcome("П2", "Arsenal - Chelsea", 0, 1), "WON")

    def test_main_backward_compatibility(self):
        # Перевірка, що main.py продовжує експортувати ключові символи для зворотної сумісності
        self.assertTrue(hasattr(main, "get_db"))
        self.assertTrue(hasattr(main, "ensure_tables"))
        self.assertTrue(hasattr(main, "send_tg"))
        self.assertTrue(hasattr(main, "fmt_kyiv"))
        self.assertTrue(hasattr(main, "esc"))
        self.assertTrue(hasattr(main, "build_chart"))
        self.assertTrue(hasattr(main, "analyze_gemini"))
        self.assertTrue(hasattr(main, "place_paper_bet"))
        self.assertTrue(hasattr(main, "settle_and_report"))
        self.assertTrue(hasattr(main, "run_pipeline"))

    def test_pipeline_active_bets_deduplication(self):
        from unittest.mock import MagicMock, patch
        import statmonitor.pipeline as pipe

        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        mock_cur.description = [
            ("event_id",), ("sport",), ("match_name",), ("commence_time",), ("bookmaker",),
            ("market_key",), ("outcome_name",), ("point",), ("start_odds",), ("current_odds",),
            ("drop_pct",), ("start_time",), ("last_time",)
        ]

        now = datetime.now(timezone.utc)
        row1 = ("ev_1", "soccer_epl", "Arsenal - Chelsea", now, "pinnacle", "h2h", "Arsenal", None, 2.2, 1.8, -18.0, now, now)
        row2 = ("ev_2", "soccer_epl", "Liverpool - City", now, "pinnacle", "h2h", "Liverpool", None, 2.5, 2.0, -20.0, now, now)

        mock_cur.fetchall.side_effect = [
            [row1, row2],
            [("ev_1",)],
            [], [], [], []
        ]

        with patch("statmonitor.pipeline.get_db", return_value=mock_conn), \
             patch("statmonitor.pipeline.ensure_tables"), \
             patch("statmonitor.pipeline.settle_and_report"), \
             patch("statmonitor.pipeline.resolve_alert_from_history", return_value=(None, None, None, None)), \
             patch("statmonitor.pipeline.get_cols", return_value={"event_id", "outcome", "price", "recorded_at"}), \
             patch("statmonitor.pipeline.build_chart", return_value=b"fake_chart"), \
             patch("statmonitor.pipeline.analyze_gemini", return_value="Аналіз"), \
             patch("statmonitor.pipeline.send_tg") as mock_send_tg, \
             patch("statmonitor.pipeline.send_photo") as mock_send_photo, \
             patch("statmonitor.pipeline.place_paper_bet"):
            pipe.check_alerts_and_notify({"soccer_epl": "EPL"})

            # ev_1 should be skipped, only ev_2 should proceed to photo/alert notification
            self.assertEqual(mock_send_photo.call_count, 1)
            caption = mock_send_photo.call_args[0][1]
            self.assertIn("Liverpool - City", caption)
            self.assertNotIn("Arsenal - Chelsea", caption)

            # SPEC-30: AI-аналіз не надсилається окремим повідомленням у Telegram
            tg_calls = [c[0][0] for c in mock_send_tg.call_args_list if c[0]]
            for msg in tg_calls:
                self.assertNotIn("AI-аналіз: Liverpool - City", msg)

            # SPEC-30: Підсумкове зведення містить посилання на гостьовий дашборд
            summary_msg = [m for m in tg_calls if "ЗВЕДЕННЯ СТАВОК" in m]
            self.assertTrue(len(summary_msg) > 0)
            self.assertIn("Відкрити гостьовий дашборд", summary_msg[0])
            self.assertIn("https://statmonitor-6zj9cutprcpvckgecdxrk4.streamlit.app", summary_msg[0])

    def test_check_odds_api_quota(self):
        from statmonitor.fetcher import check_odds_api_quota

        # 1. П'ять ключів активні (5 * 500 = 2500)
        mock_resp_p = MagicMock(status_code=200)
        mock_resp_p.headers = {"x-requests-remaining": "460", "x-requests-used": "40"}
        mock_resp_r = MagicMock(status_code=200)
        mock_resp_r.headers = {"x-requests-remaining": "500", "x-requests-used": "0"}
        mock_resp_r1 = MagicMock(status_code=200)
        mock_resp_r1.headers = {"x-requests-remaining": "500", "x-requests-used": "0"}
        mock_resp_r2 = MagicMock(status_code=200)
        mock_resp_r2.headers = {"x-requests-remaining": "500", "x-requests-used": "0"}
        mock_resp_r3 = MagicMock(status_code=200)
        mock_resp_r3.headers = {"x-requests-remaining": "500", "x-requests-used": "0"}

        with patch("requests.get", side_effect=[mock_resp_p, mock_resp_r, mock_resp_r1, mock_resp_r2, mock_resp_r3]):
            quota = check_odds_api_quota(
                api_key="key_primary_123",
                api_key_reserve="key_reserve_456",
                api_key_reserve1="key_reserve1_789",
                api_key_reserve2="key_reserve2_101",
                api_key_reserve3="key_reserve3_102",
            )
            self.assertEqual(quota["primary"]["remaining"], 460)
            self.assertEqual(quota["primary"]["used"], 40)
            self.assertEqual(quota["reserve"]["remaining"], 500)
            self.assertEqual(quota["reserve1"]["remaining"], 500)
            self.assertEqual(quota["reserve2"]["remaining"], 500)
            self.assertEqual(quota["reserve3"]["remaining"], 500)
            self.assertEqual(quota["total_remaining"], 2460)
            self.assertEqual(quota["total_limit"], 2500)
            self.assertEqual(quota["active_key"], "primary")

        # 2. Основний вичерпано (402/429) -> резервний 1 активний
        mock_resp_p_err = MagicMock(status_code=429)
        with patch("requests.get", side_effect=[mock_resp_p_err, mock_resp_r, mock_resp_r1, mock_resp_r2, mock_resp_r3]):
            quota_rot = check_odds_api_quota(
                api_key="key_primary_123",
                api_key_reserve="key_reserve_456",
                api_key_reserve1="key_reserve1_789",
                api_key_reserve2="key_reserve2_101",
                api_key_reserve3="key_reserve3_102",
            )
            self.assertEqual(quota_rot["primary"]["status"], "exhausted")
            self.assertEqual(quota_rot["primary"]["remaining"], 0)
            self.assertEqual(quota_rot["reserve"]["remaining"], 500)
            self.assertEqual(quota_rot["active_key"], "reserve")

        # 3. Основний, перший і другий резервні вичерпано -> резервний 3 (reserve2) активний
        mock_resp_r_err = MagicMock(status_code=402)
        mock_resp_r1_err = MagicMock(status_code=401)
        with patch("requests.get", side_effect=[mock_resp_p_err, mock_resp_r_err, mock_resp_r1_err, mock_resp_r2, mock_resp_r3]):
            quota_rot3 = check_odds_api_quota(
                api_key="key_primary_123",
                api_key_reserve="key_reserve_456",
                api_key_reserve1="key_reserve1_789",
                api_key_reserve2="key_reserve2_101",
                api_key_reserve3="key_reserve3_102",
            )
            self.assertEqual(quota_rot3["primary"]["status"], "exhausted")
            self.assertEqual(quota_rot3["reserve"]["status"], "exhausted")
            self.assertEqual(quota_rot3["reserve1"]["status"], "invalid_key")
            self.assertEqual(quota_rot3["reserve2"]["remaining"], 500)
            self.assertEqual(quota_rot3["active_key"], "reserve2")

    def test_get_sports_map_tennis_dynamic_discovery(self):
        from statmonitor.fetcher import get_sports_map

        mock_sports_api = [
            {"key": "soccer_epl", "title": "EPL", "active": True, "group": "Soccer"},
            {"key": "tennis_atp_brisbane", "title": "ATP Brisbane", "active": True, "group": "Tennis"},
            {"key": "tennis_davis_cup", "title": "Davis Cup", "active": True, "group": "Tennis"},
            {"key": "cricket_ipl", "title": "IPL", "active": True, "group": "Cricket"},
        ]
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = mock_sports_api

        with patch("requests.get", return_value=mock_resp), \
             patch("statmonitor.fetcher.API_KEY", "test_key"):
            s_map = get_sports_map()
            self.assertIn("soccer_epl", s_map)
            self.assertIn("tennis_atp_brisbane", s_map)
            self.assertIn("tennis_davis_cup", s_map)
            self.assertNotIn("cricket_ipl", s_map)

    def test_propline_priority_and_fallback(self):
        from statmonitor.fetcher import get_sports_map, check_odds_api_quota, fetch_and_save_odds

        # 1. check_odds_api_quota з активним PROPLINE_API
        pl_quota_resp = MagicMock(status_code=200)
        pl_quota_resp.headers = {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "920"}
        odds_resp = MagicMock(status_code=200)
        odds_resp.headers = {"x-requests-remaining": "150", "x-requests-used": "350"}
        with patch("requests.get", side_effect=[pl_quota_resp, odds_resp]):
            q = check_odds_api_quota(api_key="odds_k", propline_api_key="pl_k_123456")
            self.assertEqual(q["propline"]["status"], "active")
            self.assertEqual(q["propline"]["remaining"], 920)
            self.assertEqual(q["propline"]["limit"], 1000)
            self.assertEqual(q["preferred_source"], "propline")

        # 2. get_sports_map бере PropLine першим без запиту до The Odds API
        pl_sports_resp = MagicMock(status_code=200)
        pl_sports_resp.json.return_value = [
            {"key": "soccer_epl", "title": "EPL PropLine", "active": True, "group": "Soccer"}
        ]
        with patch("requests.get", return_value=pl_sports_resp) as mock_get, \
             patch("statmonitor.fetcher.PROPLINE_API_KEY", "pl_k_123456"), \
             patch("statmonitor.fetcher.API_KEY", "odds_k"):
            s_map = get_sports_map()
            self.assertEqual(s_map.get("soccer_epl"), "EPL PropLine")
            self.assertIn("prop-line.com", mock_get.call_args_list[0][0][0])

        # 3. fetch_and_save_odds: PropLine використовується першим; при 429 падає в fallback на The Odds API
        pl_429 = MagicMock(status_code=429, headers={"x-ratelimit-remaining": "0"}, text="rate limit")
        odds_200 = MagicMock(status_code=200, headers={"x-requests-remaining": "140"})
        odds_200.json.return_value = [{
            "id": "ev_fb_1",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "commence_time": "2026-11-26T20:00:00Z",
            "bookmakers": [{
                "key": "pinnacle",
                "markets": [{"key": "h2h", "outcomes": [{"name": "Arsenal", "price": 1.95}]}]
            }],
        }]
        with patch("requests.get", side_effect=[pl_429, odds_200]) as mock_get_fetch, \
             patch("statmonitor.fetcher.PROPLINE_API_KEY", "pl_k_123456"), \
             patch("statmonitor.fetcher.API_KEY", "odds_k"), \
             patch("statmonitor.fetcher.API_KEY_RESERVE", None), \
             patch("statmonitor.fetcher.API_KEY_RESERVE1", None), \
             patch("statmonitor.fetcher.API_KEY_RESERVE2", None), \
             patch("statmonitor.fetcher.API_KEY_RESERVE3", None), \
             patch("statmonitor.fetcher.get_db", return_value=None):
            ev_cnt, odds_cnt, _ = fetch_and_save_odds({"soccer_epl": "EPL"})
            self.assertEqual(ev_cnt, 1)
            self.assertEqual(odds_cnt, 1)
            self.assertIn("prop-line.com", mock_get_fetch.call_args_list[0][0][0])
            self.assertIn("the-odds-api.com", mock_get_fetch.call_args_list[1][0][0])

        # 4. Захист від NumericValueOutOfRange: відсікання >= 1000.0 та конвертація від'ємних American odds
        from statmonitor.fetcher import _append_events_and_odds
        ev_b, o_raw = [], []
        _append_events_and_odds([{
            "id": "ev_ovf",
            "home_team": "A",
            "away_team": "B",
            "commence_time": "2026-11-26T20:00:00Z",
            "bookmakers": [{
                "key": "bm1",
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "A", "price": 1200},
                    {"name": "B", "price": -150},
                    {"name": "Draw", "price": 3.45},
                ]}]
            }]
        }], "soccer_epl", datetime.now(timezone.utc), ev_b, o_raw)
        prices = {x["outcome"]: x["price"] for x in o_raw}
        self.assertNotIn("A", prices)
        self.assertAlmostEqual(prices["B"], 1.667, places=3)
        self.assertEqual(prices["Draw"], 3.45)

    def test_propline_odds_league_mapping_and_common_filter(self):
        from statmonitor.fetcher import (
            resolve_propline_sport_key,
            get_common_supported_sports,
            _parse_sports_list,
        )

        # 1. Співставлення ключів ЛЧ та тенісу
        self.assertEqual(resolve_propline_sport_key("soccer_uefa_champs_league"), "soccer_uefa_champions_league")
        self.assertEqual(resolve_propline_sport_key("tennis_atp"), "tennis")

        parsed = _parse_sports_list(
            [{"key": "soccer_uefa_champions_league", "title": "UEFA Champions League", "active": True}],
            map_propline=True,
        )
        self.assertIn("soccer_uefa_champs_league", parsed)

        # 2. Перетин спільних ліг PropLine ∩ The Odds API
        pl_sports = MagicMock(status_code=200)
        pl_sports.json.return_value = [
            {"key": "soccer_uefa_champions_league", "active": True},
            {"key": "soccer_epl", "active": True},
            {"key": "basketball_nba", "active": True},
            {"key": "tennis", "active": True},
        ]
        odds_sports = MagicMock(status_code=200)
        odds_sports.json.return_value = [
            {"key": "soccer_uefa_champs_league", "active": True},
            {"key": "soccer_epl", "active": True},
            {"key": "basketball_nba", "active": True},
            {"key": "soccer_ukraine_premier_league", "active": True},
        ]
        with patch("requests.get", side_effect=[pl_sports, odds_sports]):
            res = get_common_supported_sports(propline_api_key="pl_k", odds_api_keys=["odds_k"])
            self.assertIn("soccer_uefa_champs_league", res["common_keys"])
            self.assertIn("soccer_epl", res["common_keys"])
            self.assertIn("basketball_nba", res["common_keys"])
            self.assertNotIn("soccer_ukraine_premier_league", res["common_keys"])
            self.assertEqual(res["mapping"].get("soccer_uefa_champs_league"), "soccer_uefa_champions_league")

    def test_events_batch_dedup_on_alias_overlap(self):
        from statmonitor.fetcher import fetch_and_save_odds

        pl_200 = MagicMock(status_code=200, headers={"x-ratelimit-remaining": "950"})
        pl_200.json.return_value = [{
            "id": "ev_conf_1",
            "home_team": "Jablonec",
            "away_team": "Lugano",
            "commence_time": "2026-11-26T17:45:00Z",
            "bookmakers": [{
                "key": "pinnacle",
                "markets": [{"key": "h2h", "outcomes": [{"name": "Jablonec", "price": 2.10}]}]
            }],
        }]
        with patch("requests.get", return_value=pl_200) as mock_get, \
             patch("statmonitor.fetcher.PROPLINE_API_KEY", "pl_k_123"), \
             patch("statmonitor.fetcher.get_db", return_value=None):
            ev_cnt, odds_cnt, _ = fetch_and_save_odds({
                "soccer_uefa_conference_league": "Ліга Конференцій",
                "soccer_uefa_europa_conference_league": "Ліга Конференцій (alt)",
            })
            self.assertEqual(ev_cnt, 1)
            self.assertEqual(odds_cnt, 1)
            self.assertEqual(mock_get.call_count, 1)

    def test_fetcher_skips_events_beyond_5_days(self):
        from statmonitor.fetcher import _append_events_and_odds
        now_utc = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
        max_utc = now_utc + timedelta(days=5)
        ev_b, o_raw = [], []
        _append_events_and_odds([
            {
                "id": "ev_ok",
                "home_team": "A",
                "away_team": "B",
                "commence_time": "2026-11-30T20:00:00Z",
                "bookmakers": [{"key": "bm", "markets": [{"key": "h2h", "outcomes": [{"name": "A", "price": 2.0}]}]}],
            },
            {
                "id": "ev_too_far",
                "home_team": "C",
                "away_team": "D",
                "commence_time": "2026-12-07T21:45:00Z",
                "bookmakers": [{"key": "bm", "markets": [{"key": "h2h", "outcomes": [{"name": "C", "price": 1.7}]}]}],
            },
        ], "soccer_italy_serie_a", now_utc, ev_b, o_raw, max_commence_utc=max_utc)
        self.assertEqual(len(ev_b), 1)
        self.assertEqual(ev_b[0][0], "ev_ok")
        self.assertEqual(len(o_raw), 1)

if __name__ == "__main__":
    unittest.main()
