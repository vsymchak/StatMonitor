"""
test_sx_bet.py
Юніт-тести для модуля взаємодії з децентралізованою біржею SX Bet (Крок 40).
"""

import unittest
from statmonitor.sx_bet import (
    SXBetClient,
    MIN_BET_MAINNET_USDC,
    MIN_BET_TESTNET_USDC,
)


class TestSXBetClient(unittest.TestCase):
    def test_sx_bet_client_initialization(self):
        client = SXBetClient(api_key="test_key_123", testnet=False)
        self.assertEqual(client.base_url, "https://api.sx.bet")
        self.assertEqual(client.headers["x-sx-api-key"], "test_key_123")
        self.assertEqual(client.headers["X-Api-Key"], "test_key_123")

    def test_sx_bet_client_testnet_initialization(self):
        client = SXBetClient(testnet=True)
        self.assertEqual(client.base_url, "https://api.toronto.sx.bet")

    def test_metadata_endpoint(self):
        client = SXBetClient()
        meta = client.get_metadata()
        self.assertIn("limits", meta)
        self.assertEqual(meta["limits"]["orderSizeMinimum"], "1")
        self.assertEqual(meta["activeAsset"]["symbol"], "USDC")

    def test_odds_conversion(self):
        client = SXBetClient()
        # 2.00 decimal odds = 50% implied probability = 5 * 10^19
        pct_odds = client.convert_odds_to_percentage(2.00)
        self.assertEqual(pct_odds, "50000000000000000000")
        dec_odds = client.convert_percentage_to_odds(pct_odds)
        self.assertEqual(dec_odds, 2.0)

        # 1.50 decimal odds = 66.666% (округлюється до найближчого кроку 125)
        pct_odds_150 = client.convert_odds_to_percentage(1.50)
        dec_odds_150 = client.convert_percentage_to_odds(pct_odds_150)
        self.assertAlmostEqual(dec_odds_150, 1.5, delta=0.01)

    def test_invalid_odds_conversion(self):
        client = SXBetClient()
        with self.assertRaises(ValueError):
            client.convert_odds_to_percentage(0.95)

    def test_bet_validation_currency_and_amount(self):
        client = SXBetClient(testnet=False)

        # 1. Помилка: USDT замість USDC
        res_usdt = client.validate_bet_parameters(amount=10.0, currency="USDT")
        self.assertFalse(res_usdt["valid"])
        self.assertTrue(any("USDT" in err for err in res_usdt["errors"]))

        # 2. Помилка: Менше мінімальної суми (0.50 замість 1.0 USDC на OBv3)
        res_small = client.validate_bet_parameters(amount=0.50, currency="USDC")
        self.assertFalse(res_small["valid"])
        self.assertTrue(any("мінімально дозволений ліміт" in err for err in res_small["errors"]))

        # 3. Успіх: Валідна ставка 1.0 USDC та 5.0 USDC
        res_1 = client.validate_bet_parameters(amount=1.0, currency="USDC")
        self.assertTrue(res_1["valid"])
        res_ok = client.validate_bet_parameters(amount=5.0, currency="USDC")
        self.assertTrue(res_ok["valid"])
        self.assertEqual(len(res_ok["errors"]), 0)

    def test_testnet_min_bet_validation(self):
        client = SXBetClient(testnet=True)
        # На Testnet дозволено від 1.0 USDC, але 0.50 все одно мало
        res_05 = client.validate_bet_parameters(amount=0.50, currency="USDC")
        self.assertFalse(res_05["valid"])

        res_10 = client.validate_bet_parameters(amount=1.0, currency="USDC")
        self.assertTrue(res_10["valid"])

    def test_build_order_payload_and_dry_run(self):
        test_pk = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a0f3674ff"
        client = SXBetClient(private_key=test_pk, testnet=False)

        self.assertTrue(client.wallet_address.startswith("0x"))

        order = client.build_order_payload(
            market_hash="0x903d6db8019c9778f8d82d1e07f63000af0d1cb67188a028fbd917e7554e5db1",
            total_bet_size_usdc=10.0,
            decimal_odds=1.95,
            is_betting_outcome_one=True,
        )

        self.assertEqual(order["marketHash"], "0x903d6db8019c9778f8d82d1e07f63000af0d1cb67188a028fbd917e7554e5db1")
        self.assertEqual(order["maker"], client.wallet_address)
        self.assertEqual(order["totalBetSize"], "10000000")  # 10 USDC * 10^6
        self.assertTrue(order["isMakerBettingOutcomeOne"])

        # Підписання ордера
        sig = client.sign_order(order)
        self.assertTrue(sig.startswith("0x"))

        # Тест Dry-Run
        dry_result = client.place_order(order, signature=sig, dry_run=True)
        self.assertEqual(dry_result["status"], "DRY_RUN_SUCCESS")
        self.assertTrue(dry_result["has_signature"])

    def test_get_user_positions_parsing(self):
        from unittest.mock import patch, MagicMock
        client = SXBetClient(api_key="test_api_key", testnet=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "positions": [
                    {
                        "marketHash": "0x903d6db8019c9778f8d82d1e07f63000af0d1cb67188a028fbd917e7554e5db1",
                        "totalStake": "1000000",
                        "maxWin": "1247191",
                        "market": {
                            "teamOneName": "Dallas Cowboys",
                            "teamTwoName": "Philadelphia Eagles",
                            "outcomeOneName": "Over 49.5",
                            "outcomeTwoName": "Under 49.5",
                            "status": "ACTIVE",
                        }
                    }
                ]
            }
        }
        with patch("requests.get", return_value=mock_resp):
            positions = client.get_user_positions(["MATCHED"])
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0]["marketHash"], "0x903d6db8019c9778f8d82d1e07f63000af0d1cb67188a028fbd917e7554e5db1")

    def test_team_normalization_and_matching(self):
        from statmonitor.sx_bet import match_paper_bet_to_sx_market, normalize_team_text

        # 1. Нормалізація
        self.assertEqual(normalize_team_text("FC Barcelona"), "barcelona")
        self.assertEqual(normalize_team_text("Manchester City FC"), "manchester")

        # 2. Метчинг
        active_markets = [
            {
                "marketHash": "0x123",
                "teamOneName": "Dallas Cowboys",
                "teamTwoName": "Philadelphia Eagles",
                "outcomeOneName": "Over 49.5",
                "outcomeTwoName": "Under 49.5",
            },
            {
                "marketHash": "0x456",
                "teamOneName": "Arsenal FC",
                "teamTwoName": "Chelsea FC",
                "outcomeOneName": "Arsenal",
                "outcomeTwoName": "Chelsea",
            }
        ]

        paper_bet_match = {
            "match_name": "Dallas Cowboys vs Philadelphia Eagles",
            "pick_label": "Over 49.5",
            "odds": 2.25,
        }
        res = match_paper_bet_to_sx_market(paper_bet_match, active_markets)
        self.assertIsNotNone(res)
        self.assertEqual(res["marketHash"], "0x123")

        # Не знайдено
        paper_bet_none = {
            "match_name": "Real Madrid vs Juventus",
            "pick_label": "Real Madrid",
        }
        self.assertIsNone(match_paper_bet_to_sx_market(paper_bet_none, active_markets))

    def test_exact_market_line_time_and_side_matching(self):
        from datetime import datetime, timezone
        from statmonitor.sx_bet import match_paper_bet_and_side

        gt_nov26 = int(datetime(2026, 11, 26, 0, 30, tzinfo=timezone.utc).timestamp())
        gt_dec26 = int(datetime(2026, 12, 26, 1, 0, tzinfo=timezone.utc).timestamp())
        gt_ucl = int(datetime(2026, 11, 25, 17, 45, tzinfo=timezone.utc).timestamp())

        markets = [
            # Wrong future date Dec 26 (swapped)
            {
                "marketHash": "0x_dec26",
                "type": 226,
                "teamOneName": "Minnesota Timberwolves",
                "teamTwoName": "Oklahoma City Thunder",
                "outcomeOneName": "Minnesota Timberwolves",
                "outcomeTwoName": "Oklahoma City Thunder",
                "gameTime": gt_dec26,
            },
            # Right date Nov 26
            {
                "marketHash": "0x_nov26",
                "type": 226,
                "teamOneName": "Oklahoma City Thunder",
                "teamTwoName": "Minnesota Timberwolves",
                "outcomeOneName": "Oklahoma City Thunder",
                "outcomeTwoName": "Minnesota Timberwolves",
                "gameTime": gt_nov26,
            },
            # Soccer Total 2.0 (wrong line) vs Total 2.5 (right line)
            {
                "marketHash": "0x_tot20",
                "type": 2,
                "line": 2.0,
                "teamOneName": "SK Slavia Praha",
                "teamTwoName": "Villarreal",
                "outcomeOneName": "Over 2.0",
                "outcomeTwoName": "Under 2.0",
                "gameTime": gt_ucl,
            },
            {
                "marketHash": "0x_tot25",
                "type": 2,
                "line": 2.5,
                "teamOneName": "SK Slavia Praha",
                "teamTwoName": "Villarreal",
                "outcomeOneName": "Over 2.5",
                "outcomeTwoName": "Under 2.5",
                "gameTime": gt_ucl,
            },
            # Soccer 1X2 type 1
            {
                "marketHash": "0x_1x2_away",
                "type": 1,
                "teamOneName": "Lille",
                "teamTwoName": "FC Bayern Munich",
                "outcomeOneName": "FC Bayern Munich",
                "outcomeTwoName": "Not FC Bayern Munich",
                "gameTime": gt_ucl,
            },
        ]

        # 1. Time check picks Nov 26, not Dec 26, and correctly picks Minnesota (outcomeTwo -> False)
        pb_nba = {
            "match_name": "Oklahoma City Thunder - Minnesota Timberwolves",
            "pick_label": "П2 (Minnesota Timberwolves)",
            "commence_time": "2026-11-26T00:40:00Z",
        }
        m_nba, is_one_nba = match_paper_bet_and_side(pb_nba, markets)
        self.assertIsNotNone(m_nba)
        self.assertEqual(m_nba["marketHash"], "0x_nov26")
        self.assertFalse(is_one_nba)

        # 2. Exact line 2.5 check skips 2.0 and matches Under 2.5 (outcomeTwo -> False)
        pb_tot = {
            "match_name": "Slavia Praha - Villarreal",
            "pick_label": "ТМ 2.5",
            "commence_time": "2026-11-25T17:45:00Z",
        }
        m_tot, is_one_tot = match_paper_bet_and_side(pb_tot, markets)
        self.assertIsNotNone(m_tot)
        self.assertEqual(m_tot["marketHash"], "0x_tot25")
        self.assertFalse(is_one_tot)

        # 3. Soccer 1X2 Away matches "FC Bayern Munich / Not FC Bayern Munich" with outcomeOne=True
        pb_1x2 = {
            "match_name": "Lille - Bayern Munich",
            "pick_label": "П2",
            "commence_time": "2026-11-25T17:45:00Z",
        }
        m_1x2, is_one_1x2 = match_paper_bet_and_side(pb_1x2, markets)
        self.assertIsNotNone(m_1x2)
        self.assertEqual(m_1x2["marketHash"], "0x_1x2_away")
        self.assertTrue(is_one_1x2)

    def test_dynamic_percent_staking_usdc(self):
        from statmonitor.sx_bet import calculate_sx_stake_usdc

        # 1. На банку $100 при фіксованому 3% має бути рівно $3.00 USDC
        stake_fx, pct_fx = calculate_sx_stake_usdc(
            100.0, 90.0, 2.10, config={"stake_mode": "fixed_pct", "fixed_pct": 3.0, "min_stake_usdc": 1.0}
        )
        self.assertEqual(stake_fx, 3.0)
        self.assertEqual(pct_fx, 3.0)

        # 2. Динамічний Келлі на банку $64.90 дає ставку > $1.00 USDC (пропорційно % банку)
        stake_k, pct_k = calculate_sx_stake_usdc(
            64.90, 62.90, 2.09, kelly_pct=1.4, confidence=8,
            config={"stake_mode": "kelly", "min_pct": 2.0, "max_pct": 5.0, "min_stake_usdc": 1.0}
        )
        self.assertGreater(stake_k, 1.0)
        self.assertGreaterEqual(pct_k, 2.0)
        self.assertLessEqual(pct_k, 5.0)

        # 3. Захист мінімуму 1.00 USDC навіть на малому банку ($20 * 2% = $0.40 -> $1.00)
        stake_min, _ = calculate_sx_stake_usdc(
            20.0, 15.0, 2.50, config={"stake_mode": "fixed_pct", "fixed_pct": 2.0, "min_stake_usdc": 1.0}
        )
        self.assertEqual(stake_min, 1.0)

        # 4. Недостатньо балансу (< $1.00) -> 0.0
        stake_zero, _ = calculate_sx_stake_usdc(10.0, 0.50, 2.00)
        self.assertEqual(stake_zero, 0.0)

    def test_best_taker_offer_calculation(self):
        from unittest.mock import patch, MagicMock
        client = SXBetClient(api_key="test_key")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {
                "outcomeOne": [{"percentageOdds": "58750000000000000000", "size": "500000000"}],
                "outcomeTwo": [{"percentageOdds": "40000000000000000000", "size": "200000000"}],
            },
        }
        with patch("requests.get", return_value=mock_resp):
            # Ставимо на Outcome Two -> беремо maker odds з outcomeOne (58.75%) -> taker prob = 41.25% -> odds ~ 2.424
            offer_two = client.get_best_taker_offer("0xabc", is_betting_outcome_one=False, min_size_usdc=1.0)
            self.assertIsNotNone(offer_two)
            self.assertAlmostEqual(offer_two["decimal_odds"], 2.424, delta=0.01)

            # Ставимо на Outcome One -> maker outcomeTwo (40%) -> taker prob = 60% -> odds ~ 1.667
            offer_one = client.get_best_taker_offer("0xabc", is_betting_outcome_one=True, min_size_usdc=1.0)
            self.assertIsNotNone(offer_one)
            self.assertAlmostEqual(offer_one["decimal_odds"], 1.667, delta=0.01)

    def test_place_order_surfaces_403_body_and_uses_proxy_ua(self):
        from unittest.mock import patch, MagicMock
        import requests as _req
        with patch.dict("os.environ", {"SX_BET_PROXY_URL": "http://eu-proxy:8080"}):
            client = SXBetClient(api_key="k", private_key="0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a0f3674ff")
        self.assertIn("User-Agent", client.headers)
        self.assertEqual(client._proxies, {"http": "http://eu-proxy:8080", "https": "http://eu-proxy:8080"})

        bad_resp = MagicMock()
        bad_resp.status_code = 403
        bad_resp.reason = "Forbidden"
        bad_resp.url = "https://api.sx.bet/orders-v3"
        bad_resp.text = '{"error":"Geo blocked"}'
        order = client.build_order_payload("0x" + "1" * 64, 1.0, 2.0, True)
        with patch("statmonitor.sx_bet.requests.post", return_value=bad_resp) as mock_post:
            with self.assertRaises(_req.HTTPError) as ctx:
                client.place_order(order, dry_run=False)
            self.assertIn("Geo blocked", str(ctx.exception))
            self.assertEqual(mock_post.call_args[1]["proxies"]["https"], "http://eu-proxy:8080")

    def test_local_sx_worker_cycle(self):
        from unittest.mock import patch, MagicMock
        import scripts.sx_local_worker as worker

        mock_conn = MagicMock()
        mock_conn.server_version = 160000
        mock_conn.closed = False
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (True,)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        fake_cli = MagicMock()
        fake_cli.api_key = "k"
        fake_cli.private_key = "0x1"

        with patch.object(worker, "SUPABASE_DB_URL", "postgresql://u:p@h:5432/db"), \
             patch.object(worker, "SXBetClient", return_value=fake_cli), \
             patch.object(worker, "get_db", return_value=mock_conn), \
             patch.object(worker, "sync_sx_exchange_full", return_value={"free_balance_usdc": 63.1, "trades_fetched": 2, "updated_bets": 1, "settled_bets": 0, "expired_cleaned": 0}), \
             patch.object(worker, "is_sx_autostake_enabled", return_value=(True, "OK")), \
             patch.object(worker, "auto_sync_and_stake_from_paper", return_value=[{"paper_bet_id": 252, "event": "Espanyol - Getafe", "stake_usdc": 2.0, "pct": 3.0, "odds": 2.1, "mode": "MAKER", "order_id": "0xord"}]):
            res = worker.run_sx_cycle()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["placed"], 1)
        mock_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
