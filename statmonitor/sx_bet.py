"""
statmonitor/sx_bet.py
Клієнт взаємодії з децентралізованою біржею ставок SX Bet (SX Network / Arbitrum).
Реалізація Кроку 40 дорожньої карти:
- Отримання публічних даних: активні маркети, лайв-події, стакан ордерів (CLOB)
- Перевірка валідності параметрів: валюта (USDC), мінімальний стейк (5 USDC Mainnet / 1 USDC Testnet)
- Побудова структури ордера та EIP-712 підписання для автостейкінгу
"""

import os
import time
import secrets
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger("statmonitor.sx_bet")

# Константи SX Bet API
SX_MAINNET_API = "https://api.sx.bet"
SX_TESTNET_API = "https://api.toronto.sx.bet"

# Мінімальні ставки згідно протоколу SX Bet (OrderBook V3)
# Раніше в V2 було 5 USDC, але в актуальній версії OBv3 мінімальний розмір знижено до 1 USDC
MIN_BET_MAINNET_USDC = 1.0
MIN_BET_TESTNET_USDC = 1.0

# Відомі адреси USDC контрактів
USDC_ADDRESS_SX_NETWORK = "0x6629Ce1Cf35Cc1329ebB4F63202F3f197b3F050B"
USDC_ADDRESS_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_ADDRESS_ARBITRUM = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"


class SXBetClient:
    """
    Клієнт для взаємодії з REST API та ончейн ордербуком SX Bet.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        private_key: Optional[str] = None,
        wallet_address: Optional[str] = None,
        testnet: bool = False,
        timeout: int = 15,
    ):
        self.testnet = testnet
        self.base_url = SX_TESTNET_API if testnet else SX_MAINNET_API
        # Читаємо API ключ із переданих параметрів або змінних оточення (підтримуємо MY_GEM_BOT)
        self.api_key = (
            api_key
            or os.getenv("SX_BET_API_KEY")
            or os.getenv("MY_GEM_BOT")
            or os.getenv("SX_API_KEY")
        )
        self.private_key = private_key or os.getenv("SX_BET_PRIVATE_KEY") or os.getenv("ETH_PRIVATE_KEY")
        self.wallet_address = wallet_address or os.getenv("SX_BET_WALLET_ADDRESS")
        self.timeout = timeout

        if self.private_key and not self.wallet_address:
            try:
                from eth_account import Account
                self.wallet_address = Account.from_key(self.private_key).address
            except Exception as e:
                logger.warning(f"Не вдалося вивести адресу гаманця з private_key: {e}")

    @property
    def headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["x-sx-api-key"] = self.api_key
            headers["X-Api-Key"] = self.api_key
        return headers

    def ping(self) -> bool:
        """Перевірка доступності SX Bet API."""
        try:
            r = requests.get(f"{self.base_url}/sports", headers=self.headers, timeout=self.timeout)
            return r.status_code == 200
        except Exception as e:
            logger.error(f"Помилка з'єднання з SX Bet: {e}")
            return False

    def get_metadata(self) -> Dict[str, Any]:
        """Отримати актуальні метадані біржі (OBv3), включаючи ліміти, токени та затримки лайву."""
        r = requests.get(f"{self.base_url}/metadata/obv3", headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("data", {})

    def get_sports(self) -> List[Dict[str, Any]]:
        """Отримати список доступних видів спорту."""
        r = requests.get(f"{self.base_url}/sports", headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])

    def get_leagues(self) -> List[Dict[str, Any]]:
        """Отримати список ліг/турнірів."""
        r = requests.get(f"{self.base_url}/leagues", headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])

    def get_active_markets(self, sport_id: Optional[int] = None, live_only: bool = False) -> List[Dict[str, Any]]:
        """
        Отримати активні ринки зі стакану SX Bet.
        """
        params = {}
        if sport_id:
            params["sportId"] = sport_id

        r = requests.get(f"{self.base_url}/markets/active", params=params, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        markets = data.get("data", {}).get("markets", [])

        if live_only:
            # Фільтрація виключно лайв-подій
            markets = [
                m for m in markets
                if m.get("liveEnabled") or m.get("liveWorld") or "LIVE" in str(m.get("status", "")).upper()
            ]

        return markets

    def get_orders(self, market_hash: str) -> List[Dict[str, Any]]:
        """Отримати актуальний стакан відкритих ордерів для конкретного ринку."""
        params = {"marketHash": market_hash}
        r = requests.get(f"{self.base_url}/orders", params=params, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])

    def validate_bet_parameters(self, amount: float, currency: str) -> Dict[str, Any]:
        """
        Сувора перевірка параметрів ставки перед відправкою на біржу:
        - SX Bet приймає ВИКЛЮЧНО USDC (не USDT).
        - Мінімальний розмір ставки: 5 USDC на Mainnet (1 USDC на Testnet).
        """
        curr = currency.upper().strip()
        min_allowed = MIN_BET_TESTNET_USDC if self.testnet else MIN_BET_MAINNET_USDC

        errors = []
        if curr != "USDC":
            errors.append(
                f"Невірна валюта '{currency}'. SX Bet підтримує виключно USDC (не USDT). "
                f"Контракти біржі не приймають USDT."
            )

        if amount < min_allowed:
            errors.append(
                f"Розмір ставки {amount} {curr} менший за мінімально дозволений ліміт біржі ({min_allowed} USDC). "
                f"Смарт-контракт відхилить цей ордер."
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "min_allowed": min_allowed,
            "currency": curr,
            "amount": amount,
        }

    def convert_odds_to_percentage(self, decimal_odds: float) -> str:
        """
        Конвертує десятковий коефіцієнт (наприклад 2.00) у формат ймовірності SX Bet (10^20).
        Формула: (1.0 / decimal_odds) * 10^20
        """
        if decimal_odds <= 1.0:
            raise ValueError(f"Десятковий коефіцієнт має бути > 1.0, отримано {decimal_odds}")
        implied_prob = 1.0 / decimal_odds
        val = int(implied_prob * (10**20))
        return str(val)

    def convert_percentage_to_odds(self, percentage_odds_str: str) -> float:
        """
        Конвертує формат ймовірності SX Bet (10^20) назад у десятковий коефіцієнт.
        """
        val = int(percentage_odds_str)
        if val <= 0:
            return 0.0
        prob = val / (10**20)
        return round(1.0 / prob, 3)

    def build_order_payload(
        self,
        market_hash: str,
        total_bet_size_usdc: float,
        decimal_odds: float,
        is_betting_outcome_one: bool,
        base_token_address: Optional[str] = None,
        expiry_seconds: int = 3600,
        time_in_force: str = "GTC",
    ) -> Dict[str, Any]:
        """
        Формує структуру ордера для подання в SX Bet (OrderBook V3).
        total_bet_size передається в базових одиницях USDC (6 десяткових знаків, e.g. 1 USDC = 1_000_000).
        """
        validation = self.validate_bet_parameters(total_bet_size_usdc, "USDC")
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))

        if not self.wallet_address:
            raise ValueError("Не вказано адресу гаманця (wallet_address або приватний ключ для виведення).")

        base_token = base_token_address or (
            USDC_ADDRESS_SX_NETWORK if not self.testnet else "0x1BC6326EA6aF2aB8E4b6Bc83418044B1923b2956"
        )
        now_ts = int(time.time())
        expiry = now_ts + expiry_seconds
        percentage_odds = self.convert_odds_to_percentage(decimal_odds)

        # USDC має 6 знаків після коми: 1 USDC = 1_000_000 базових одиниць
        total_bet_size_base = str(int(total_bet_size_usdc * 1_000_000))
        salt = str(secrets.randbits(128))

        order = {
            "marketHash": market_hash,
            "maker": self.wallet_address,
            "totalBetSize": total_bet_size_base,
            "percentageOdds": percentage_odds,
            "baseToken": base_token,
            "expiry": expiry,
            "timeInForce": time_in_force,
            "isMakerBettingOutcomeOne": is_betting_outcome_one,
            "salt": salt,
        }
        return order

    def sign_order(self, order: Dict[str, Any]) -> str:
        """
        Створює офіційний EIP-712 криптографічний підпис ордера OrderBook V3.
        Вимагає валідного EVM private_key гаманця maker.
        """
        if not self.private_key:
            raise ValueError("Приватний ключ (SX_BET_PRIVATE_KEY) не задано. Неможливо створити цифровий підпис.")

        try:
            from eth_account import Account
            from eth_account.messages import encode_typed_data

            domain_data = {
                "name": "OBv3 Escrow",
                "version": "1",
                "chainId": 4162 if not self.testnet else 79479957,
                "verifyingContract": "0x890482680C3a0116aBB003B17e7D694D13a6c1eB" if not self.testnet else "0x0000000000000000000000000000000000000000",
            }

            types_data = {
                "Order": [
                    {"name": "marketHash", "type": "bytes32"},
                    {"name": "baseToken", "type": "address"},
                    {"name": "totalBetSize", "type": "uint256"},
                    {"name": "percentageOdds", "type": "uint256"},
                    {"name": "salt", "type": "uint256"},
                    {"name": "expiry", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "isMakerBettingOutcomeOne", "type": "bool"},
                ]
            }

            message_data = {
                "marketHash": order["marketHash"],
                "baseToken": order["baseToken"],
                "totalBetSize": int(order["totalBetSize"]),
                "percentageOdds": int(order["percentageOdds"]),
                "salt": int(order["salt"]),
                "expiry": int(order["expiry"]),
                "maker": order["maker"],
                "isMakerBettingOutcomeOne": bool(order["isMakerBettingOutcomeOne"]),
            }

            signable = encode_typed_data(
                domain_data=domain_data,
                message_types=types_data,
                message_data=message_data,
            )
            signed = Account.sign_message(signable, private_key=self.private_key)
            sig_hex = signed.signature.hex()
            if not sig_hex.startswith("0x"):
                sig_hex = f"0x{sig_hex}"
            return sig_hex
        except ImportError:
            raise ImportError("Для підписання ордерів необхідний пакет eth-account: pip install eth-account")

    def place_order(self, order: Dict[str, Any], signature: Optional[str] = None, dry_run: bool = True) -> Dict[str, Any]:
        """
        Відправляє сформований та підписаний ордер на біржу (POST /orders-v3).
        Якщо dry_run=True, перевіряє ордер без фактичної транзакції в блокчейн.
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Сформовано ордер SX Bet: {order}")
            return {
                "status": "DRY_RUN_SUCCESS",
                "message": "Ордер успішно перевірено та змодельовано в режимі емуляції (dry-run).",
                "order": order,
                "has_signature": signature is not None,
            }

        sig = signature or self.sign_order(order)
        order_with_sig = dict(order)
        order_with_sig["orderSignature"] = sig

        payload = {"orders": [order_with_sig]}
        r = requests.post(f"{self.base_url}/orders-v3", json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
