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

    def test_odds_conversion(self):
        client = SXBetClient()
        # 2.00 decimal odds = 50% implied probability = 5 * 10^19
        pct_odds = client.convert_odds_to_percentage(2.00)
        self.assertEqual(pct_odds, "50000000000000000000")
        dec_odds = client.convert_percentage_to_odds(pct_odds)
        self.assertEqual(dec_odds, 2.0)

        # 1.50 decimal odds = 66.666%
        pct_odds_150 = client.convert_odds_to_percentage(1.50)
        dec_odds_150 = client.convert_percentage_to_odds(pct_odds_150)
        self.assertEqual(dec_odds_150, 1.5)

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

        # 2. Помилка: Менше мінімальної суми (0.50 замість 5.0 USDC на Mainnet)
        res_small = client.validate_bet_parameters(amount=0.50, currency="USDC")
        self.assertFalse(res_small["valid"])
        self.assertTrue(any("мінімально дозволений ліміт" in err for err in res_small["errors"]))

        # 3. Успіх: Валідна ставка 5.0 USDC
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


if __name__ == "__main__":
    unittest.main()
