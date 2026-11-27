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
        mock_cur.fetchone.return_value = None
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
             patch("statmonitor.pipeline.analyze_gemini", return_value="Аналіз\nConfidence Score: 8/10"), \
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
                    {"name": "C", "price": 225},
                    {"name": "Draw", "price": 3.45},
                ]}]
            }]
        }], "soccer_epl", datetime.now(timezone.utc), ev_b, o_raw)
        prices = {x["outcome"]: x["price"] for x in o_raw}
        self.assertNotIn("A", prices)
        self.assertAlmostEqual(prices["B"], 1.667, places=3)
        self.assertAlmostEqual(prices["C"], 3.25, places=3)
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

    def test_to_decimal_odds_and_place_paper_bet_normalization(self):
        from statmonitor.paper_trading import to_decimal_odds, place_paper_bet

        self.assertEqual(to_decimal_odds(147.0), 2.47)
        self.assertEqual(to_decimal_odds(-200.0), 1.50)
        self.assertEqual(to_decimal_odds(2.05), 2.05)
        self.assertIsNone(to_decimal_odds(1.0))
        self.assertIsNone(to_decimal_odds(60.0))
        self.assertIsNone(to_decimal_odds(1500.0))

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, (0.0, 0.0)]
        ok = place_paper_bet(
            mock_cur, mock_conn, "ev_dec", "soccer_epl", "A - B",
            datetime.now(timezone.utc), "П1", 147.0, confidence=8,
        )
        self.assertTrue(ok)
        inserted_args = mock_cur.execute.call_args[0][1]
        self.assertEqual(inserted_args[5], 2.47)

        mock_cur_bad = MagicMock()
        self.assertFalse(place_paper_bet(
            mock_cur_bad, mock_conn, "ev_bad", "soccer_epl", "A - B",
            datetime.now(timezone.utc), "П1", 0.9, confidence=8,
        ))
        mock_cur_bad.execute.assert_not_called()

    def test_pipeline_skips_paper_bet_without_ai_confidence(self):
        import statmonitor.pipeline as pipe

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_cur.fetchall.side_effect = [
            [(
                "ev_no_ai", "soccer_epl", "Arsenal - Chelsea",
                datetime.now(timezone.utc) + timedelta(hours=3),
                "Arsenal", 2.10, 1.80, -14.3, 1.80,
            )],
            [], [], [], [],
        ]

        with patch("statmonitor.pipeline.get_db", return_value=mock_conn), \
             patch("statmonitor.pipeline.ensure_tables"), \
             patch("statmonitor.pipeline.settle_and_report"), \
             patch("statmonitor.pipeline.resolve_alert_from_history", return_value=(None, None, None, None)), \
             patch("statmonitor.pipeline.get_cols", return_value={"event_id", "outcome", "price", "recorded_at"}), \
             patch("statmonitor.pipeline.build_chart", return_value=b"fake_chart"), \
             patch("statmonitor.pipeline.analyze_gemini", return_value=None), \
             patch("statmonitor.pipeline.send_tg"), \
             patch("statmonitor.pipeline.send_photo"), \
             patch("statmonitor.pipeline.place_paper_bet") as mock_place:
            pipe.check_alerts_and_notify({"soccer_epl": "EPL"})
            mock_place.assert_not_called()

    def test_find_score_event_fallback_by_team_names(self):
        from statmonitor.paper_trading import _find_score_event
        score_events = [
            {
                "id": "espn_999",
                "home_team": "Sunderland",
                "away_team": "Jagiellonia Bialystok",
                "completed": True,
                "scores": [{"name": "Sunderland", "score": "1"}, {"name": "Jagiellonia Bialystok", "score": "1"}],
            },
            {
                "id": "espn_888",
                "home_team": "Inter Milan",
                "away_team": "VfB Stuttgart",
                "completed": True,
                "scores": [{"name": "Inter Milan", "score": "2"}, {"name": "VfB Stuttgart", "score": "0"}],
            },
        ]
        ev1 = _find_score_event("old_propline_id", "Sunderland - Jagiellonia Białystok", {}, score_events)
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1["id"], "espn_999")

        ev2 = _find_score_event("missing_id", "Inter Milan - VfB Stuttgart", {}, score_events)
        self.assertIsNotNone(ev2)
        self.assertEqual(ev2["id"], "espn_888")

    def test_fetcher_dedups_team_and_duplicate_totals(self):
        from statmonitor.fetcher import _append_events_and_odds
        now_utc = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
        ev_b, o_raw = [], []
        _append_events_and_odds([
            {
                "id": "723566",
                "home_team": "Espanyol",
                "away_team": "Getafe",
                "commence_time": "2026-11-30T20:00:00Z",
                "bookmakers": [
                    {
                        "key": "eplay24",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "point": 0.5, "price": 1.60},
                                    {"name": "Under", "point": 0.5, "price": 2.22},
                                    {"name": "Over", "point": 0.5, "price": 1.09},
                                    {"name": "Under", "point": 0.5, "price": 6.15},
                                    {"name": "Over", "point": 0.5, "price": 1.30},
                                    {"name": "Under", "point": 0.5, "price": 3.25},
                                ],
                            },
                            {
                                "key": "totals",
                                "description": "1st Half Totals",
                                "outcomes": [
                                    {"name": "Under", "point": 1.5, "price": 1.45},
                                ],
                            },
                        ],
                    }
                ],
            }
        ], "soccer_spain_la_liga", now_utc, ev_b, o_raw)
        self.assertEqual(len(o_raw), 2)
        over_rows = [r for r in o_raw if r["outcome"] == "Over"]
        under_rows = [r for r in o_raw if r["outcome"] == "Under"]
        self.assertEqual(len(over_rows), 1)
        self.assertEqual(over_rows[0]["price"], 1.09)
        self.assertEqual(len(under_rows), 1)
        self.assertEqual(under_rows[0]["price"], 6.15)

    def test_auto_enable_tennis_tournaments(self):
        from statmonitor.league_config import auto_enable_tennis_tournaments, is_tennis_sport

        self.assertTrue(is_tennis_sport("tennis"))
        self.assertTrue(is_tennis_sport("tennis_atp_miami_open"))
        self.assertTrue(is_tennis_sport("tennis_davis_cup"))
        self.assertFalse(is_tennis_sport("soccer_epl", "EPL"))

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, (False,), (True,)]
        res = auto_enable_tennis_tournaments(
            mock_cur,
            mock_conn,
            {
                "tennis_atp_dubai": "Теніс (ATP Dubai)",
                "tennis_davis_cup": "Теніс (Кубок Девіса)",
                "tennis_wta": "Теніс (WTA Tour)",
                "soccer_epl": "EPL",
            },
        )
        # Навмисно вимкнена тенісна ліга (tennis_davis_cup=False) НЕ перевмикається автоматично (A-04)
        self.assertEqual(res, ["tennis_atp_dubai"])
        mock_conn.commit.assert_called_once()

    def test_reject_high_odds_and_low_hockey_totals(self):
        from statmonitor.paper_trading import place_paper_bet
        from statmonitor.fetcher import _append_events_and_odds

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # 1. Коеф > 4.0 має відхилятися на рівні place_paper_bet
        self.assertFalse(place_paper_bet(
            mock_cur, mock_conn, "ev_high", "soccer_epl", "A - B",
            datetime.now(timezone.utc), "П1", 4.50, confidence=8,
        ))
        # 2. Хокей тотал < 4.0 має відхилятися (2.5 та 3.5), а 5.5 — проходити
        self.assertFalse(place_paper_bet(
            mock_cur, mock_conn, "ev_hk25", "icehockey_nhl", "Devils - Flames",
            datetime.now(timezone.utc), "ТМ 2.5", 3.64, confidence=8,
        ))
        self.assertFalse(place_paper_bet(
            mock_cur, mock_conn, "ev_hk35", "icehockey_nhl", "Bruins - Leafs",
            datetime.now(timezone.utc), "ТМ 3.5", 2.10, confidence=8,
        ))
        mock_cur.fetchone.side_effect = [None, (0.0, 0.0)]
        self.assertTrue(place_paper_bet(
            mock_cur, mock_conn, "ev_hk55", "icehockey_nhl", "Bruins - Leafs",
            datetime.now(timezone.utc), "ТМ 5.5", 2.10, confidence=8,
        ))

        # 3. _append_events_and_odds фільтрує хокейні тотали < 4.0
        now_utc = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)
        ev_b, o_raw = [], []
        _append_events_and_odds([
            {
                "id": "hk_1",
                "home_team": "Devils",
                "away_team": "Flames",
                "commence_time": "2026-11-28T01:00:00Z",
                "bookmakers": [{
                    "key": "pinnacle",
                    "markets": [{
                        "key": "totals",
                        "outcomes": [
                            {"name": "Under", "point": 2.5, "price": 3.64},
                            {"name": "Under", "point": 3.5, "price": 2.40},
                            {"name": "Under", "point": 5.5, "price": 1.95},
                        ],
                    }],
                }],
            }
        ], "icehockey_nhl", now_utc, ev_b, o_raw)
        self.assertEqual(len(o_raw), 1)
        self.assertEqual(o_raw[0]["point"], 5.5)

        # 4. Баскетбол: тотали < 150.0 відхиляються в fetcher та place_paper_bet
        self.assertFalse(place_paper_bet(
            mock_cur, mock_conn, "ev_bk116", "basketball_nba", "Blazers - Warriors",
            datetime.now(timezone.utc), "ТБ 116.5", 2.11, confidence=8,
        ))
        ev_bk, o_bk = [], []
        _append_events_and_odds([
            {
                "id": "bk_1",
                "home_team": "Pistons",
                "away_team": "Bucks",
                "commence_time": "2026-11-28T01:00:00Z",
                "bookmakers": [{
                    "key": "pinnacle",
                    "markets": [{
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 116.5, "price": 1.90},
                            {"name": "Over", "point": 224.5, "price": 1.91},
                        ],
                    }],
                }],
            }
        ], "basketball_nba", now_utc, ev_bk, o_bk)
        self.assertEqual(len(o_bk), 1)
        self.assertEqual(o_bk[0]["point"], 224.5)

    def test_security_and_runtime_audit_fixes(self):
        from statmonitor.config import get_secret
        from trigger_dispatch import trigger_via_webhook
        from statmonitor.digest import generate_weekly_digest
        from statmonitor.paper_trading import get_market_median_odds
        from scheduler import should_execute_pipeline

        # 1. get_secret без Streamlit читає env і не падає
        with patch.dict("os.environ", {"TEST_SECRET_KEY": "abc_secret_123"}):
            self.assertEqual(get_secret("TEST_SECRET_KEY"), "abc_secret_123")
        self.assertEqual(get_secret("MISSING_SECRET_KEY_XYZ", "fallback_v"), "fallback_v")

        # 2. trigger_via_webhook перевіряє секрет і статус відповіді
        ok_no_sec, _ = trigger_via_webhook(secret="", url="https://example.com")
        self.assertFalse(ok_no_sec)
        with patch("trigger_dispatch.requests.get", return_value=MagicMock(status_code=202)) as mock_trig:
            ok_trig, msg_trig = trigger_via_webhook(secret="topsecret", source="telegram_bot", url="https://example.com/trigger")
            self.assertTrue(ok_trig)
            self.assertIn("202", msg_trig)
            mock_trig.assert_called_once()

        # 3. digest.py використовує total_with_clv та beat_line_pct
        mock_cur_dig = MagicMock()
        mock_conn_dig = MagicMock()
        mock_cur_dig.description = [
            ("id",), ("match_name",), ("sport",), ("pick_label",), ("odds",),
            ("stake_uah",), ("status",), ("profit_uah",), ("settled_at",),
            ("created_at",), ("closing_odds",), ("clv_pct",), ("beat_closing_line",),
        ]
        now_t = datetime.now(timezone.utc)
        mock_cur_dig.fetchall.return_value = [
            (1, "A - B", "soccer_epl", "П1", 2.0, 200.0, "WON", 200.0, now_t, now_t, 1.85, 8.1, True),
            (2, "C - D", "soccer_epl", "П2", 2.1, 200.0, "LOST", -200.0, now_t, now_t, 2.0, 5.0, True),
        ]
        with patch("statmonitor.digest.calculate_clv_metrics", return_value={"total_with_clv": 5, "avg_clv_pct": 4.2, "beat_line_pct": 80.0}), \
             patch("statmonitor.digest.build_weekly_equity_chart", return_value=None), \
             patch("statmonitor.digest.send_tg") as mock_dig_tg:
            generate_weekly_digest(mock_cur_dig, mock_conn_dig, force=True, send_telegram=True)
            cap = mock_dig_tg.call_args[0][0]
            self.assertIn("4.2%", cap)
            self.assertIn("80.0%", cap)

        # 4. get_market_median_odds query_any_time підтримує btts без IndexError
        mock_cur_btts = MagicMock()
        mock_cur_btts.fetchall.side_effect = [[], [("pinnacle", 1.88)]]
        res_btts = get_market_median_odds(mock_cur_btts, "ev_btts", "Обидві заб'ють (Так)", "A - B", fallback_odds=1.80)
        self.assertEqual(res_btts, 1.88)

        # 5. scheduler.should_execute_pipeline шукає 'StatMonitor' або 'scheduler_run'
        mock_cur_sch = MagicMock()
        mock_conn_sch = MagicMock()
        fresh_ping = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_cur_sch.fetchone.side_effect = [None, None, (fresh_ping,), None]
        should_run, _, mode = should_execute_pipeline(mock_cur_sch, mock_conn_sch, trigger_source="cron_5m")
        self.assertFalse(should_run)
        self.assertEqual(mode, "SKIP")
        q_joined = "\n".join(str(c[0][0]) for c in mock_cur_sch.execute.call_args_list)
        self.assertIn("StatMonitor", q_joined)

        # 6. render_service PIPELINE_LOCK не дозволяє одночасного запуску
        import render_service
        with patch("main.run_pipeline") as mock_rp:
            self.assertTrue(render_service.PIPELINE_LOCK.acquire(blocking=False))
            try:
                render_service._run_pipeline_guarded(force=True)
                mock_rp.assert_not_called()
            finally:
                render_service.PIPELINE_LOCK.release()

    def test_audit_security_and_ai_fixes(self):
        import time as _t
        from statmonitor.notifier import _redact_secrets
        from statmonitor.ai import analyze_gemini, _is_model_available, _MODEL_EXHAUSTED_UNTIL
        from statmonitor.config import EXHAUSTED_MODELS
        from statmonitor.cold_archive import upload_to_r2

        # 1. Notifier redacts bot token and query API key
        red = _redact_secrets("HTTPS error for https://api.telegram.org/bot123456:SECRET_ABC/sendMessage?key=XYZ999")
        self.assertNotIn("SECRET_ABC", red)
        self.assertNotIn("XYZ999", red)
        self.assertIn("bot<REDACTED>", red)

        # 2. Gemini API key sent in header (never query param) + TTL expiry restores model
        EXHAUSTED_MODELS.clear()
        _MODEL_EXHAUSTED_UNTIL.clear()
        with patch("statmonitor.ai.GEMINI_API_KEY", "test_gem_key"), \
             patch("statmonitor.ai.requests.post") as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=429),
                MagicMock(status_code=429),
                MagicMock(
                    status_code=200,
                    json=lambda: {"candidates": [{"content": {"parts": [{"text": "📌 Коротка ставка: П1\nВпевнений прогноз на фаворита матчу та хороший тонус."}]}}]},
                ),
            ]
            out = analyze_gemini("Arsenal - Chelsea", "АПЛ", "27.11 22:00", "drop 8%")
            self.assertIsNotNone(out)
            called_url = mock_post.call_args_list[0][0][0]
            called_hdrs = mock_post.call_args_list[0][1]["headers"]
            self.assertNotIn("?key=", called_url)
            self.assertEqual(called_hdrs.get("x-goog-api-key"), "test_gem_key")
            self.assertFalse(_is_model_available("gemini-3.5-flash-lite", now_ts=_t.time()))
            # Expired TTL makes model available again
            _MODEL_EXHAUSTED_UNTIL["gemini-3.5-flash-lite"] = _t.time() - 5
            self.assertTrue(_is_model_available("gemini-3.5-flash-lite", now_ts=_t.time()))
            EXHAUSTED_MODELS.clear()
            _MODEL_EXHAUSTED_UNTIL.clear()

        # 3. Cold archive URL-encodes '=' in partition key per SigV4
        with patch("statmonitor.cold_archive.R2_ACCOUNT_ID", "acc"), \
             patch("statmonitor.cold_archive.R2_ACCESS_KEY_ID", "kid"), \
             patch("statmonitor.cold_archive.R2_SECRET_ACCESS_KEY", "sec"), \
             patch("statmonitor.cold_archive.R2_BUCKET_NAME", "bkt"), \
             patch("statmonitor.cold_archive.requests.put", return_value=MagicMock(status_code=200)) as mock_put:
            ok_r2, uri_r2, kind_r2 = upload_to_r2(b"abc", "odds_history/year=2026/month=11/d.parquet")
            self.assertTrue(ok_r2)
            self.assertEqual(kind_r2, "R2")
            put_url = mock_put.call_args[0][0]
            self.assertIn("year%3D2026/month%3D11", put_url)

    def test_audit_sx_bet_derby_and_guardrails(self):
        from statmonitor.sx_bet import (
            SXBetClient,
            match_paper_bet_and_side,
            evaluate_sx_risk_guardrails,
            sync_sx_exchange_full,
        )

        # 1. Derby rejection: Real Madrid vs Atletico Madrid / Manchester City vs Manchester United
        markets = [
            {
                "marketHash": "0x_derby_1",
                "type": 1,
                "teamOneName": "Atletico Madrid",
                "teamTwoName": "Sevilla FC",
                "outcomeOneName": "Atletico Madrid",
                "outcomeTwoName": "Not Atletico Madrid",
            },
            {
                "marketHash": "0x_derby_2",
                "type": 226,
                "teamOneName": "Manchester United",
                "teamTwoName": "Manchester City",
                "outcomeOneName": "Manchester United",
                "outcomeTwoName": "Manchester City",
            },
        ]
        m_rm, _ = match_paper_bet_and_side({"match_name": "Real Madrid - Sevilla", "pick_label": "П1 (Real Madrid)"}, markets)
        self.assertIsNone(m_rm)
        m_wrong, _ = match_paper_bet_and_side({"match_name": "Manchester City - Arsenal", "pick_label": "П1"}, [markets[1]])
        self.assertIsNone(m_wrong)
        m_mc, is_one_mc = match_paper_bet_and_side({"match_name": "Manchester City - Manchester United", "pick_label": "П1 (Manchester City)"}, markets)
        self.assertIsNotNone(m_mc)
        self.assertFalse(is_one_mc)

        # 2. Kill-switch and guardrails
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [("sx_autostake_enabled", False)]
        ok_g, reason_g = evaluate_sx_risk_guardrails(mock_conn, 2.0, free_usdc=50.0, portfolio_usdc=50.0)
        self.assertFalse(ok_g)
        self.assertIn("kill-switch", reason_g.lower())

        # Stop-loss triggered (-10 USDC on $100 portfolio >= 7%)
        mock_cur.fetchall.return_value = [("sx_autostake_enabled", True)]
        mock_cur.fetchone.return_value = (-10.0, 0.0, 0.0)
        ok_sl, reason_sl = evaluate_sx_risk_guardrails(mock_conn, 2.0, free_usdc=90.0, portfolio_usdc=100.0)
        self.assertFalse(ok_sl)
        self.assertIn("Stop-Loss", reason_sl)

        # 3. RPC error returns None instead of misleading 0.0
        cli = SXBetClient(proxy_address="0x" + "1" * 40)
        with patch("statmonitor.sx_bet.requests.post", side_effect=RuntimeError("rpc down")):
            self.assertIsNone(cli.get_proxy_usdc_balance())

        # 4. Sync reconciliation uses RECONCILIATION_DIFF (never synthetic DEPOSIT/WITHDRAWAL)
        cli_ok = SXBetClient(api_key="k", proxy_address="0x" + "1" * 40)
        cli_ok.get_proxy_usdc_balance = lambda: 65.0
        cli_ok.get_user_trades = lambda: [{"tradeId": "tr1", "marketHash": "0x1", "totalStake": "1000000", "totalReturn": "2000000", "status": "MATCHED", "betTime": 1700000000}]
        cli_ok.get_user_positions = lambda *a, **kw: []
        cli_ok.get_orders = lambda *a, **kw: []
        cli_ok.get_markets_by_hashes = lambda *a, **kw: {}
        sync_conn = MagicMock()
        sync_cur = MagicMock()
        sync_conn.cursor.return_value.__enter__.return_value = sync_cur
        sync_cur.fetchone.side_effect = [
            None,               # existing sx_bets
            None,               # existing tx BET_PLACED
            (50.0, 0.0, 0.0),   # deposits, withdrawals, recon
            (0.0, 1.0),         # net_pnl, active_risked -> expected=49, diff=+16
        ]
        sync_cur.fetchall.side_effect = [[], [], [(1, 16.0)]]
        sync_sx_exchange_full(sync_conn, client=cli_ok)
        ins_sqls = [str(c[0][0]) for c in sync_cur.execute.call_args_list if "RECONCILIATION_DIFF" in str(c[0][0])]
        self.assertTrue(len(ins_sqls) >= 1)

    def test_audit_ledger_settlement_and_analytics(self):
        from statmonitor.analytics import classify_market_group
        from statmonitor.real_bankroll import record_real_transaction, get_real_bankroll_summary
        from statmonitor.paper_trading import place_paper_bet, capture_closing_lines, settle_and_report, eval_outcome
        import sys_watchdog

        # 1. Q-06 market classification precedence
        self.assertEqual(classify_market_group("Atlético-MG"), "1X2 / Переможець")
        self.assertEqual(classify_market_group("Футбол: П1"), "1X2 / Переможець")
        self.assertEqual(classify_market_group("Arsenal (+0.5)"), "Фори")
        self.assertEqual(classify_market_group("ТМ 2.5"), "Тотали")

        # 2. F-06 WITHDRAWAL overdraft rejected + Q-09 NULL real_profit_uah not fallen back to paper
        cur_w = MagicMock()
        conn_w = MagicMock()
        cur_w.fetchone.return_value = (100.00,)
        ok_w, bal_w, msg_w = record_real_transaction(cur_w, conn_w, "WITHDRAWAL", 500.00, "Overdraft test")
        self.assertFalse(ok_w)
        self.assertEqual(bal_w, 100.0)
        self.assertIn("Недостатньо коштів", msg_w)

        cur_sum = MagicMock()
        cur_sum.fetchone.side_effect = [(1000.0, 1000.0), (1000.0, 0.0), (1, 0, 1, 0, 0, 100.0, 0.0)]
        sum_res = get_real_bankroll_summary(cur_sum)
        q_sql = str(cur_sum.execute.call_args_list[-1][0][0])
        self.assertIn("COALESCE(real_profit_uah, 0.0)", q_sql)
        self.assertEqual(sum_res["real_profit"], 0.0)

        # 3. F-02 fail-closed on missing AI confidence
        cur_p = MagicMock()
        conn_p = MagicMock()
        cur_p.fetchone.return_value = None
        ok_p = place_paper_bet(cur_p, conn_p, "ev_no_ai", "soccer_epl", "A - B", datetime.now(timezone.utc), "П1", 2.0, confidence=None)
        self.assertFalse(ok_p)
        ins_calls = [str(c[0][1]) for c in cur_p.execute.call_args_list if "INSERT INTO paper_bets" in str(c[0][0])]
        self.assertTrue(any("AI_UNAVAILABLE" in c for c in ins_calls))

        # 4. F-12 capture_closing_lines never fakes closing_odds = bet_k
        cur_clv = MagicMock()
        conn_clv = MagicMock()
        cur_clv.fetchall.return_value = [(77, "ev_no_close", "A - B", "П1", 2.15, datetime.now(timezone.utc), "PENDING")]
        with patch("statmonitor.paper_trading.get_market_median_odds", return_value=None):
            res_clv = capture_closing_lines(cur_clv, conn_clv)
        self.assertEqual(res_clv, [])

        # 5. Q-07 Inter vs Inter Miami team boundary
        self.assertEqual(eval_outcome("Inter Miami", "Inter - Inter Miami", 0, 2), "WON")
        self.assertEqual(eval_outcome("Inter Miami", "Inter - Inter Miami", 2, 0), "LOST")

        # 6. F-08 Tennis non-h2h auto-settlement skipped when score is only set count
        cur_t = MagicMock()
        conn_t = MagicMock()
        cur_t.fetchall.return_value = [
            (91, "ev_ten_1", "tennis_atp_dubai", "Player A - Player B", "ТБ 22.5", 1.90, 200.0, False, None, None, "PENDING", False, datetime.now(timezone.utc)),
        ]
        fake_ev = {"id": "ev_ten_1", "home_team": "Player A", "away_team": "Player B", "completed": True, "scores": [{"name": "Player A", "score": "2"}, {"name": "Player B", "score": "0"}]}
        with patch("statmonitor.config.PROPLINE_API_KEY", ""), \
             patch("statmonitor.paper_trading.API_KEY", "k_test"), \
             patch("statmonitor.paper_trading.requests.get", return_value=MagicMock(status_code=200, json=lambda: [fake_ev])), \
             patch("statmonitor.paper_trading.fetch_espn_scores_for_sport", return_value=[]):
            settle_and_report(cur_t, conn_t)
        upd_calls = [str(c[0][0]) for c in cur_t.execute.call_args_list if "UPDATE paper_bets" in str(c[0][0])]
        self.assertEqual(len(upd_calls), 0)

        # 7. A-02 record_heartbeat updates both StatMonitor and scheduler_run
        cur_hb = MagicMock()
        conn_hb = MagicMock()
        sys_watchdog.record_heartbeat(cur_hb, conn_hb, duration_sec=1.2)
        hb_svcs = [c[0][1][0] for c in cur_hb.execute.call_args_list if len(c[0]) > 1 and c[0][1] and "INSERT INTO system_heartbeat" in str(c[0][0])]
        self.assertIn("StatMonitor", hb_svcs)
        self.assertIn("scheduler_run", hb_svcs)

        # 8. A-01 run_pipeline aborts when pg_try_advisory_lock returns False
        mock_lock_conn = MagicMock()
        mock_lock_conn.server_version = 160000
        mock_lock_cur = MagicMock()
        mock_lock_cur.fetchone.return_value = (False,)
        mock_lock_conn.cursor.return_value = mock_lock_cur
        with patch("main.get_db", return_value=mock_lock_conn), \
             patch("main.get_sports_map") as mock_sm:
            main.run_pipeline(force=True)
            mock_sm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
