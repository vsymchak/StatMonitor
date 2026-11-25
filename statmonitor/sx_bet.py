"""
statmonitor/sx_bet.py
Клієнт взаємодії з децентралізованою біржею ставок SX Bet (SX Network / Arbitrum).
Реалізація Кроку 40 дорожньої карти:
- Отримання публічних даних: активні маркети, лайв-події, стакан ордерів (CLOB)
- Перевірка валідності параметрів: валюта (USDC), мінімальний стейк (5 USDC Mainnet / 1 USDC Testnet)
- Побудова структури ордера та EIP-712 підписання для автостейкінгу
"""

import os
import re
import json
import time
import secrets
import logging
import unicodedata
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import requests

try:
    from statmonitor.paper_trading import calculate_kelly_fraction
except Exception:
    calculate_kelly_fraction = None

# Автоматичне завантаження з .env файлу
def _load_env_file():
    candidates = [
        ".env",
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), ".env"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
            break

_load_env_file()

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

# Відомі ончейн адреси користувача (SX Network)
DEFAULT_SX_WALLET_ADDRESS = "0xd4689DEE01C14Eb75688DF439f5aFb13dfD11071"
DEFAULT_SX_PROXY_ADDRESS = "0x5ef7F65D6c810fF8Ce4CEdcffcfeb53e0bD1c043"
DEFAULT_SX_SAFE_ADDRESS = "0xf7466D286A0Fe1Cbd55E2925d5b7399E4990f503"

# Відповідність ключів The Odds API до SX Bet sportId / leagueId
ODDS_API_TO_SX_MAP = {
    "basketball_nba": {"sport_id": 1, "league_id": 1},
    "basketball_ncaab": {"sport_id": 1, "league_id": 2},
    "icehockey_nhl": {"sport_id": 2, "league_id": 3},
    "baseball_mlb": {"sport_id": 3, "league_id": 171},
    "americanfootball_nfl": {"sport_id": 8, "league_id": 243},
    "soccer_epl": {"sport_id": 5, "league_id": 29},
    "soccer_efl_champ": {"sport_id": 5, "league_id": 1313},
    "soccer_uefa_champs_league": {"sport_id": 5, "league_id": 30},
    "soccer_uefa_europa_league": {"sport_id": 5, "league_id": 31},
    "soccer_uefa_conference_league": {"sport_id": 5, "league_id": 1309},
    "soccer_spain_la_liga": {"sport_id": 5, "league_id": 1114},
    "soccer_germany_bundesliga": {"sport_id": 5, "league_id": 244},
    "soccer_germany_bundesliga2": {"sport_id": 5, "league_id": 1836},
    "soccer_italy_serie_a": {"sport_id": 5, "league_id": 1113},
    "soccer_france_ligue_one": {"sport_id": 5, "league_id": 1112},
}

DEFAULT_SX_CONFIG = {
    "stake_mode": "kelly",       # 'kelly' або 'fixed_pct'
    "min_pct": 2.0,              # Мін. % від банку USDC (2.0% -> ~$1.30 на $65 банку)
    "max_pct": 5.0,              # Макс. % від банку USDC (5.0%)
    "fixed_pct": 3.0,            # Фіксований % у режимі fixed_pct
    "min_stake_usdc": 1.0,       # Абсолютний мінімум біржі (1.00 USDC)
    "min_confidence": 7,         # Мінімальний рейтинг впевненості AI (7/10)
}


class SXBetClient:
    """
    Клієнт для взаємодії з REST API та ончейн ордербуком SX Bet.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        private_key: Optional[str] = None,
        wallet_address: Optional[str] = None,
        proxy_address: Optional[str] = None,
        safe_address: Optional[str] = None,
        testnet: bool = False,
        timeout: int = 15,
    ):
        self.testnet = testnet
        self.base_url = SX_TESTNET_API if testnet else SX_MAINNET_API

        # Перевірка Streamlit Secrets (якщо запущено у хмарі Streamlit Cloud)
        st_sec = {}
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                st_sec = st.secrets
        except Exception:
            pass

        # Читаємо API ключ із переданих параметрів, змінних оточення або Streamlit Secrets (підтримуємо MY_GEM_BOT)
        self.api_key = (
            api_key
            or os.getenv("SX_BET_API_KEY")
            or os.getenv("MY_GEM_BOT")
            or os.getenv("SX_API_KEY")
            or st_sec.get("MY_GEM_BOT")
            or st_sec.get("SX_BET_API_KEY")
            or st_sec.get("SX_API_KEY")
        )
        self.private_key = (
            private_key
            or os.getenv("SX_BET_PRIVATE_KEY")
            or os.getenv("ETH_PRIVATE_KEY")
            or st_sec.get("SX_BET_PRIVATE_KEY")
            or st_sec.get("ETH_PRIVATE_KEY")
        )
        self.wallet_address = (
            wallet_address
            or os.getenv("SX_BET_WALLET_ADDRESS")
            or st_sec.get("SX_BET_WALLET_ADDRESS")
            or DEFAULT_SX_WALLET_ADDRESS
        )
        self.proxy_address = (
            proxy_address
            or os.getenv("SX_BET_PROXY_ADDRESS")
            or st_sec.get("SX_BET_PROXY_ADDRESS")
            or DEFAULT_SX_PROXY_ADDRESS
        )
        self.safe_address = (
            safe_address
            or os.getenv("SX_BET_SAFE_ADDRESS")
            or st_sec.get("SX_BET_SAFE_ADDRESS")
            or DEFAULT_SX_SAFE_ADDRESS
        )
        self.timeout = timeout

        if self.private_key and not wallet_address:
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

    def get_active_markets(
        self,
        sport_id: Optional[int] = None,
        league_id: Optional[int] = None,
        live_only: bool = False,
        max_pages: int = 12,
    ) -> List[Dict[str, Any]]:
        """
        Отримати активні ринки зі стакану SX Bet з підтримкою пагінації та фільтрації за sportIds / leagueId.
        """
        markets: List[Dict[str, Any]] = []
        next_key: Optional[str] = None
        seen_keys = set()

        for _ in range(max_pages):
            params: Dict[str, Any] = {}
            if sport_id:
                params["sportIds"] = [int(sport_id)]
            if league_id:
                params["leagueId"] = int(league_id)
            if next_key:
                params["paginationKey"] = next_key

            r = requests.get(f"{self.base_url}/markets/active", params=params, headers=self.headers, timeout=self.timeout)
            r.raise_for_status()
            data = r.json().get("data", {})
            batch = data.get("markets", [])
            if not batch:
                break
            markets.extend(batch)
            next_key = data.get("nextKey")
            if not next_key or next_key in seen_keys:
                break
            seen_keys.add(next_key)

        if live_only:
            markets = [
                m for m in markets
                if m.get("liveEnabled") or m.get("liveWorld") or "LIVE" in str(m.get("status", "")).upper()
            ]

        return markets

    def get_orders(self, market_hash: Optional[str] = None) -> List[Dict[str, Any]]:
        """Отримати відкриті/активні мейкер-ордери користувача або за ринком (OrderBook V3)."""
        params = {"marketHash": market_hash} if market_hash else {}
        try:
            r = requests.get(f"{self.base_url}/orders-v3", params=params, headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json().get("data", {})
                return data.get("orders", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception as e:
            logger.warning(f"Помилка отримання ордерів ({market_hash or 'user'}): {e}")
        return []

    def get_orderbook_snapshot(self, market_hash: str) -> Dict[str, Any]:
        """Отримати поточний знімок ліквідності стакану (GET /orderbook-v3/snapshot/market)."""
        try:
            r = requests.get(
                f"{self.base_url}/orderbook-v3/snapshot/market",
                params={"marketHash": market_hash},
                headers=self.headers,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return r.json().get("data", {}) or {}
        except Exception as e:
            logger.warning(f"Помилка отримання стакану для {market_hash}: {e}")
        return {}

    def get_best_taker_offer(
        self, market_hash: str, is_betting_outcome_one: bool, min_size_usdc: float = 0.5
    ) -> Optional[Dict[str, Any]]:
        """
        Знаходить найкращий зустрічний коефіцієнт для миттєвого тейкер-виконання у стакані SX Bet.
        Для ставки на Outcome One аналізуються мейкер-ордери у outcomeTwo (і навпаки):
        taker_prob = 1.0 - maker_prob, taker_odds = 1.0 / taker_prob.
        """
        snap = self.get_orderbook_snapshot(market_hash)
        opposing_key = "outcomeTwo" if is_betting_outcome_one else "outcomeOne"
        levels = snap.get(opposing_key, []) or []
        best_offer = None

        for lvl in levels:
            try:
                maker_pct = int(lvl.get("percentageOdds", 0))
                size_usdc = int(lvl.get("size", 0)) / 1e6
                if size_usdc < min_size_usdc or maker_pct <= 0 or maker_pct >= 10**20:
                    continue
                taker_prob = 1.0 - (maker_pct / 1e20)
                if taker_prob <= 0.001 or taker_prob >= 0.999:
                    continue
                dec_odds = round(1.0 / taker_prob, 3)
                if best_offer is None or dec_odds > best_offer["decimal_odds"]:
                    best_offer = {
                        "decimal_odds": dec_odds,
                        "taker_prob": taker_prob,
                        "size_usdc": round(size_usdc, 2),
                    }
            except Exception:
                continue
        return best_offer

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

    def convert_odds_to_percentage(self, decimal_odds: float, step_size: int = 125) -> str:
        """
        Конвертує десятковий коефіцієнт (наприклад 2.00) у формат ймовірності SX Bet (10^20)
        із обов'язковим округленням до сходинки oddsLadderStepSize (за замовчуванням 125).
        Формула сходинки: step = step_size * 10^15
        """
        if decimal_odds <= 1.0:
            raise ValueError(f"Десятковий коефіцієнт має бути > 1.0, отримано {decimal_odds}")
        implied_prob = 1.0 / decimal_odds
        raw_val = int(implied_prob * (10**20))

        # Винятки для екстремумів 0.1% та 99.9%
        exc_low = 10**17
        exc_high = 999 * (10**17)
        if raw_val == exc_low or raw_val == exc_high:
            return str(raw_val)

        # Округлення до дозволеної сітки сходинки (odds ladder)
        ladder_step = step_size * (10**15)
        valid_val = raw_val - (raw_val % ladder_step)
        return str(valid_val)

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
        total_bet_size_base = str(int(round(float(total_bet_size_usdc) * 1_000_000)))
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

    def get_proxy_info(self) -> Dict[str, Any]:
        """Отримати адресу та статус ончейн Proxy Wallet."""
        try:
            r = requests.get(f"{self.base_url}/user/proxy", headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json().get("data", {})
                if data and data.get("obv3ProxyWalletAddress"):
                    return data
        except Exception as e:
            logger.error(f"Помилка отримання даних Proxy: {e}")

        # Fallback до надійних ончейн адрес користувача
        return {
            "obv3ProxyWalletAddress": getattr(self, "proxy_address", None) or DEFAULT_SX_PROXY_ADDRESS,
            "multisigSafeAddress": getattr(self, "safe_address", None) or DEFAULT_SX_SAFE_ADDRESS,
            "deployed": True,
        }

    def get_proxy_usdc_balance(self, proxy_address: Optional[str] = None) -> float:
        """Отримати актуальний баланс USDC у Proxy Wallet через ончейн RPC (SX Network)."""
        proxy = (
            proxy_address
            or getattr(self, "proxy_address", None)
            or DEFAULT_SX_PROXY_ADDRESS
        )
        if not proxy or proxy == DEFAULT_SX_PROXY_ADDRESS:
            info = self.get_proxy_info()
            proxy = info.get("obv3ProxyWalletAddress") or proxy

        rpc_urls = [
            "https://rpc-rollup.sx.technology",
        ] if not self.testnet else [
            "https://rpc-rollup.toronto.sx.technology",
        ]
        usdc_contract = USDC_ADDRESS_SX_NETWORK if not self.testnet else "0x1BC6326EA6aF2aB8E4b6Bc83418044B1923b2956"
        data = "0x70a08231" + proxy[2:].lower().zfill(64)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for rpc_url in rpc_urls:
            try:
                r = requests.post(
                    rpc_url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdc_contract, "data": data}, "latest"]},
                    headers=headers,
                    timeout=8,
                )
                if r.status_code == 200:
                    resp_json = r.json()
                    res = resp_json.get("result")
                    if res and res != "0x":
                        val = int(res, 16) / 1e6
                        return round(val, 2)
            except Exception as e:
                logger.warning(f"Помилка отримання балансу USDC через RPC {rpc_url}: {e}")
                continue

        return 0.0

    def _get_order_with_status(self, order_id: str) -> Tuple[Optional[Dict[str, Any]], int]:
        """Отримати деталі ордера та HTTP статус-код (200 / 404 / тощо)."""
        try:
            r = requests.get(f"{self.base_url}/orders-v3/{order_id}", headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                return r.json().get("data", {}).get("order", {}), 200
            return None, r.status_code
        except Exception as e:
            logger.error(f"Помилка отримання деталей ордера {order_id}: {e}")
            return None, 0

    def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Отримати актуальний статус ордера на біржі за orderId."""
        order, _ = self._get_order_with_status(order_id)
        return order

    def get_user_trades(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        """
        Отримує повну історію виконаних та активних угод користувача (GET /trades-v3).
        Містить точні суми ставок, виплати, статус SETTLED/LOCKED та дату розрахунку.
        """
        trades: List[Dict[str, Any]] = []
        next_key: Optional[str] = None
        seen_keys = set()

        for _ in range(max_pages):
            params: Dict[str, Any] = {}
            if next_key:
                params["paginationKey"] = next_key
            try:
                r = requests.get(f"{self.base_url}/trades-v3", params=params, headers=self.headers, timeout=self.timeout)
                if r.status_code != 200:
                    logger.error(f"Помилка отримання trades-v3 [{r.status_code}]: {r.text}")
                    break
                data = r.json().get("data", {})
                batch = data.get("trades", []) if isinstance(data, dict) else []
                if not batch:
                    break
                trades.extend(batch)
                next_key = data.get("nextKey") if isinstance(data, dict) else None
                if not next_key or next_key in seen_keys:
                    break
                seen_keys.add(next_key)
            except Exception as e:
                logger.error(f"Виняток при отриманні trades-v3: {e}")
                break
        return trades

    def get_markets_by_hashes(self, market_hashes: List[str]) -> Dict[str, Dict[str, Any]]:
        """Отримує метадані та результати ринків пакетами за списком marketHash (GET /markets/find)."""
        clean_hashes = [h for h in dict.fromkeys(market_hashes) if h]
        result: Dict[str, Dict[str, Any]] = {}
        chunk_size = 25
        for i in range(0, len(clean_hashes), chunk_size):
            chunk = clean_hashes[i:i + chunk_size]
            try:
                r = requests.get(
                    f"{self.base_url}/markets/find",
                    params={"marketHashes": chunk},
                    headers=self.headers,
                    timeout=self.timeout,
                )
                if r.status_code == 200:
                    items = r.json().get("data", []) or []
                    for m in items:
                        mh = m.get("marketHash")
                        if mh:
                            result[mh] = m
            except Exception as e:
                logger.warning(f"Помилка отримання /markets/find: {e}")
        return result

    def get_user_positions(self, statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Отримує активні та розраховані позиції користувача з біржі SX Bet (GET /positions-v3).
        Доступні статуси: MATCHED, LOCKED, SETTLED, FAILED.
        """
        st_list = statuses or ["MATCHED", "LOCKED", "SETTLED"]
        try:
            r = requests.get(
                f"{self.base_url}/positions-v3",
                headers=self.headers,
                params={"status": st_list},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                resp_json = r.json()
                if isinstance(resp_json, dict):
                    data = resp_json.get("data", {})
                    if isinstance(data, dict):
                        return data.get("positions", [])
                    elif isinstance(data, list):
                        return data
                elif isinstance(resp_json, list):
                    return resp_json
                return []
            else:
                logger.error(f"Помилка отримання позицій SX Bet [{r.status_code}]: {r.text}")
        except Exception as e:
            logger.error(f"Виняток при отриманні позицій SX Bet: {e}")
        return []


# ==========================================================
# НАЛАШТУВАННЯ ТА РОЗРАХУНОК % СТАВКИ ВІД БАНКУ USDC
# ==========================================================

def ensure_sx_config_table(cur, conn=None):
    """Створює таблицю налаштувань авто-стейкінгу SX Bet у БД."""
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sx_settings (
                key TEXT PRIMARY KEY,
                value_json JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        if conn:
            conn.commit()
    except Exception as e:
        logger.debug(f"ensure_sx_config_table notice: {e}")


def get_sx_staking_config(conn) -> Dict[str, Any]:
    """Читає параметри ризик-менеджменту (% від банку USDC) для SX Bet із БД."""
    cfg = dict(DEFAULT_SX_CONFIG)
    if not conn:
        return cfg
    try:
        with conn.cursor() as cur:
            ensure_sx_config_table(cur, conn)
            cur.execute("SELECT value_json FROM sx_settings WHERE key = 'staking_config' LIMIT 1;")
            row = cur.fetchone()
            if row and isinstance(row[0], dict):
                for k, v in row[0].items():
                    if k in cfg and v is not None:
                        cfg[k] = v
    except Exception as e:
        logger.debug(f"get_sx_staking_config fallback: {e}")
    return cfg


def save_sx_staking_config(
    conn,
    stake_mode: str = "kelly",
    min_pct: float = 2.0,
    max_pct: float = 5.0,
    fixed_pct: float = 3.0,
    min_stake_usdc: float = 1.0,
    min_confidence: int = 7,
) -> Dict[str, Any]:
    """Зберігає параметри відсоткового стейкінгу SX Bet у БД."""
    cfg = {
        "stake_mode": stake_mode if stake_mode in ("kelly", "fixed_pct") else "kelly",
        "min_pct": max(0.5, min(20.0, float(min_pct))),
        "max_pct": max(0.5, min(25.0, float(max_pct))),
        "fixed_pct": max(0.5, min(20.0, float(fixed_pct))),
        "min_stake_usdc": max(1.0, float(min_stake_usdc)),
        "min_confidence": max(1, min(10, int(min_confidence))),
    }
    if cfg["max_pct"] < cfg["min_pct"]:
        cfg["max_pct"] = cfg["min_pct"]

    if conn:
        with conn.cursor() as cur:
            ensure_sx_config_table(cur, conn)
            cur.execute("""
                INSERT INTO sx_settings (key, value_json, updated_at)
                VALUES ('staking_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value_json = EXCLUDED.value_json,
                    updated_at = NOW();
            """, (json.dumps(cfg),))
            conn.commit()
    return cfg


def calculate_sx_stake_usdc(
    bank_usdc: float,
    free_usdc: float,
    odds: float,
    kelly_pct: Optional[float] = None,
    confidence: Optional[int] = None,
    drop_pct: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[float, float]:
    """
    Розраховує розмір ставки в USDC як відсоток від банку (з мінімальним порогом 1.00 USDC).
    Повертає кортеж: (stake_usdc, applied_pct).
    Якщо вільного балансу < min_stake_usdc, повертає (0.0, 0.0).
    """
    cfg = config or DEFAULT_SX_CONFIG
    min_stake = max(1.0, float(cfg.get("min_stake_usdc", 1.0) or 1.0))
    if free_usdc < min_stake or bank_usdc <= 0:
        return 0.0, 0.0

    stake_mode = cfg.get("stake_mode", "kelly")
    min_pct = max(0.5, float(cfg.get("min_pct", 2.0) or 2.0))
    max_pct = max(min_pct, float(cfg.get("max_pct", 5.0) or 5.0))
    fixed_pct = max(0.5, float(cfg.get("fixed_pct", 3.0) or 3.0))

    if stake_mode == "fixed_pct":
        pct = fixed_pct
    else:
        # Використовуємо оцінку Келлі та масштабуємо до налаштованого коридору [min_pct, max_pct]
        if calculate_kelly_fraction is not None:
            raw_frac = calculate_kelly_fraction(
                odds, drop_pct=drop_pct, confidence=confidence,
                fraction=0.40, min_pct=min_pct / 100.0, max_pct=max_pct / 100.0
            )
            pct = round(raw_frac * 100.0, 2)
        elif kelly_pct is not None and float(kelly_pct) > 0:
            pct = float(kelly_pct)
        else:
            pct = min_pct

        # Якщо в paper_bets зафіксовано вищий келлі-процент (напр. 2.5%), враховуємо максимум із них
        if kelly_pct is not None and float(kelly_pct) > 0:
            # Масштабуємо Quarter-Kelly (1-5%) до Half-Kelly коридору [min_pct, max_pct]
            scaled_paper_pct = float(kelly_pct) * 1.4
            pct = max(pct, min(max_pct, scaled_paper_pct))

        pct = max(min_pct, min(max_pct, round(pct, 2)))

    raw_stake = round(bank_usdc * (pct / 100.0), 2)
    final_stake = max(min_stake, raw_stake)
    final_stake = min(final_stake, round(free_usdc, 2))
    if final_stake < min_stake:
        return 0.0, 0.0
    return round(final_stake, 2), round(pct, 2)


# ==========================================================
# СИНХРОНІЗАЦІЯ З БІРЖЕЮ SX BET (/trades-v3, /positions-v3, /markets/find)
# ==========================================================

def _parse_sx_timestamp(raw_val: Any) -> Optional[datetime]:
    """Універсальний парсер часу з SX Bet API (ISO рядок або Unix epoch у секундах/мілісекундах)."""
    if not raw_val:
        return None
    try:
        if isinstance(raw_val, datetime):
            return raw_val if raw_val.tzinfo else raw_val.replace(tzinfo=timezone.utc)
        if isinstance(raw_val, (int, float)):
            ts = float(raw_val)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, timezone.utc)
        if isinstance(raw_val, str):
            s = raw_val.strip()
            if s.isdigit():
                ts = float(s)
                if ts > 1e12:
                    ts /= 1000.0
                return datetime.fromtimestamp(ts, timezone.utc)
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def sync_sx_exchange_full(conn, client: Optional[SXBetClient] = None) -> Dict[str, Any]:
    """
    Повна синхронізація суто з біржею SX Bet та ончейн Proxy Wallet:
    1. Отримує актуальний ончейн баланс USDC Proxy Wallet.
    2. Завантажує ВСІ реальні трейди (GET /trades-v3), позиції (GET /positions-v3),
       активні мейкер-ордери (GET /orders-v3) та метадані/результати ринків (GET /markets/find).
    3. Оновлює та розраховує всі завершені ставки (WON/LOST/VOID) із точним settleReturnAmount та settleDate.
    4. Додає відсутні історичні ставки, зроблені безпосередньо на sx.bet.
    5. Очищує прострочені/невиконані лімітні ордери (404 / EXPIRED), звільняючи уявно заблокований банк.
    6. Повністю звіряє та оновлює касовий журнал sx_transactions і баланси.
    """
    sx_client = client or SXBetClient()
    stats: Dict[str, Any] = {
        "free_balance_usdc": 0.0,
        "trades_fetched": 0,
        "updated_bets": 0,
        "settled_bets": 0,
        "expired_cleaned": 0,
        "tx_synced": 0,
    }

    free_balance = sx_client.get_proxy_usdc_balance()
    stats["free_balance_usdc"] = free_balance

    trades = sx_client.get_user_trades()
    positions = sx_client.get_user_positions(["MATCHED", "LOCKED", "SETTLED"])
    open_orders = sx_client.get_orders()
    stats["trades_fetched"] = len(trades)

    # Індексуємо позиції по marketHash як резерв метаданих ринку
    pos_market_map: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        mh = p.get("marketHash")
        if mh and p.get("market"):
            pos_market_map[mh] = p["market"]

    # Збираємо всі marketHash, щоб підтягнути свіжі результати ринків одним пакетним запитом
    all_hashes = [t.get("marketHash") for t in trades if t.get("marketHash")]
    all_hashes.extend(list(pos_market_map.keys()))

    with conn.cursor() as cur:
        cur.execute("SELECT market_hash FROM sx_bets WHERE status IN ('PENDING', 'OPEN_ORDER');")
        for r_mh in cur.fetchall():
            if r_mh and r_mh[0]:
                all_hashes.append(r_mh[0])

    markets_map = sx_client.get_markets_by_hashes(all_hashes)

    updated_count = 0
    settled_count = 0
    active_trade_mhashes = set()
    active_trade_order_ids = set()
    open_order_ids = set()

    for oo in open_orders:
        oo_id = oo.get("id") or oo.get("orderId")
        if oo_id:
            open_order_ids.add(oo_id)

    # Сортуємо трейди хронологічно (від найстарішого до найновішого)
    trades_sorted = sorted(
        trades,
        key=lambda x: str(x.get("betTime") or x.get("createdAt") or ""),
    )

    with conn.cursor() as cur:
        # Допоміжний обхід по кожному реальному трейду
        for t in trades_sorted:
            trade_id = t.get("tradeId")
            m_hash = t.get("marketHash")
            if not trade_id or not m_hash:
                continue

            active_trade_mhashes.add(m_hash)
            own_oids = [oid for oid in (t.get("ownOrderIds") or []) if oid]
            for oid in own_oids:
                active_trade_order_ids.add(oid)
            active_trade_order_ids.add(trade_id)

            market = markets_map.get(m_hash) or pos_market_map.get(m_hash) or {}
            total_stake = round(float(t.get("totalStake", 0)) / 1e6, 2)
            raw_total_ret = float(t.get("totalReturn", 0)) / 1e6
            net_total_ret = float(t.get("netTotalReturn") or t.get("totalReturn") or 0) / 1e6

            if total_stake > 0 and raw_total_ret > 0:
                calc_odds = round(raw_total_ret / total_stake, 2)
            elif t.get("weightedAverageOdds"):
                calc_odds = round(sx_client.convert_percentage_to_odds(str(t["weightedAverageOdds"])), 2)
            else:
                calc_odds = 2.0

            potential_payout = round(net_total_ret if net_total_ret > 0 else total_stake * calc_odds, 2)
            is_one = bool(t.get("isBettingOutcomeOne", True))

            t_status = str(t.get("status", "")).upper()
            settlement = t.get("settlement") or {}
            m_status = str(market.get("status", "")).upper()
            outcome_val = settlement.get("outcome") if settlement.get("outcome") is not None else market.get("outcome")

            profit = 0.0
            settled_dt = None
            status = "PENDING"
            total_received = 0.0

            if t_status == "SETTLED" or (outcome_val is not None and m_status in ("INACTIVE", "SETTLED", "RESOLVED")):
                if settlement and settlement.get("settleReturnAmount") is not None:
                    settle_ret = float(settlement.get("settleReturnAmount", 0)) / 1e6
                    ce_refund = float(settlement.get("settleCeRefundAmount", 0)) / 1e6
                    total_received = round(settle_ret + ce_refund, 2)
                    profit = round(total_received - total_stake, 2)
                    if outcome_val == 3 or (abs(profit) <= 0.01 and total_received > 0):
                        status = "VOID"
                        profit = 0.0
                    elif profit > 0:
                        status = "WON"
                    else:
                        status = "LOST"
                        profit = -total_stake if total_received == 0 else profit
                else:
                    if outcome_val == 3:
                        status = "VOID"
                        profit = 0.0
                        total_received = total_stake
                    elif (outcome_val == 1 and is_one) or (outcome_val == 2 and not is_one):
                        status = "WON"
                        profit = round(potential_payout - total_stake, 2)
                        total_received = round(total_stake + profit, 2)
                    else:
                        status = "LOST"
                        profit = -total_stake
                        total_received = 0.0

                settled_dt = _parse_sx_timestamp(settlement.get("settleDate") or t.get("updatedAt")) or datetime.now(timezone.utc)
            elif t_status == "FAILED":
                status = "CANCELLED"
                profit = 0.0
                settled_dt = _parse_sx_timestamp(t.get("updatedAt")) or datetime.now(timezone.utc)

            t1 = market.get("teamOneName", "")
            t2 = market.get("teamTwoName", "")
            ev_name = f"{t1} vs {t2}" if t1 and t2 else f"SX Market {m_hash[:10]}"
            outcome1 = market.get("outcomeOneName", "")
            outcome2 = market.get("outcomeTwoName", "")
            side = outcome1 if is_one else outcome2
            if not side:
                side = "Outcome 1" if is_one else "Outcome 2"
            market_label = f"{outcome1} / {outcome2}" if outcome1 and outcome2 else str(market.get("type") or "Market")
            sport_lbl = str(market.get("sportLabel") or market.get("leagueLabel") or market.get("type") or "Sport")
            gt_dt = _parse_sx_timestamp(market.get("gameTime") or t.get("gameTime"))
            bet_dt = _parse_sx_timestamp(t.get("betTime") or t.get("createdAt")) or datetime.now(timezone.utc)

            # Шукаємо наявний запис в sx_bets (за order_id, tradeId або по market_hash)
            lookup_ids = list(dict.fromkeys([trade_id] + own_oids + [m_hash]))
            cur.execute("""
                SELECT id, order_id, status, profit_usdc, settled_at, odds, event_name, sport_label
                FROM sx_bets
                WHERE order_id = ANY(%s)
                   OR (market_hash = %s AND (raw_order->>'tradeId' IS NULL OR raw_order->>'tradeId' = %s))
                ORDER BY id ASC
                LIMIT 1;
            """, (lookup_ids, m_hash, trade_id))
            row = cur.fetchone()

            if row:
                bet_id, db_oid, old_status, old_profit, old_settled, old_odds, old_ev, old_sport = row
                old_profit_f = float(old_profit or 0.0)
                needs_update = (
                    old_status != status
                    or round(old_profit_f, 2) != round(profit, 2)
                    or (settled_dt is not None and old_settled is None)
                    or ("SX Market" in str(old_ev) and "vs" in ev_name)
                    or (str(old_sport).isdigit() and not sport_lbl.isdigit())
                )
                if needs_update:
                    cur.execute("""
                        UPDATE sx_bets
                        SET status = %s,
                            profit_usdc = %s,
                            settled_at = COALESCE(%s, settled_at),
                            odds = %s,
                            potential_payout_usdc = %s,
                            event_name = CASE WHEN %s != '' THEN %s ELSE event_name END,
                            market_name = CASE WHEN %s != '' THEN %s ELSE market_name END,
                            bet_side = CASE WHEN %s != '' THEN %s ELSE bet_side END,
                            sport_label = CASE WHEN %s != '' THEN %s ELSE sport_label END,
                            raw_order = %s::jsonb
                        WHERE id = %s;
                    """, (
                        status, profit, settled_dt, calc_odds, potential_payout,
                        ev_name, ev_name, market_label, market_label, side, side, sport_lbl, sport_lbl,
                        json.dumps(t), bet_id
                    ))
                    updated_count += 1
                    if old_status == "PENDING" and status in ("WON", "LOST", "VOID"):
                        settled_count += 1
            else:
                primary_oid = own_oids[0] if own_oids else trade_id
                cur.execute("""
                    INSERT INTO sx_bets (
                        order_id, market_hash, event_id, sport_label, event_name,
                        market_name, bet_side, stake_usdc, odds, potential_payout_usdc,
                        status, profit_usdc, game_time, created_at, settled_at, raw_order
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (order_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        profit_usdc = EXCLUDED.profit_usdc,
                        settled_at = COALESCE(EXCLUDED.settled_at, sx_bets.settled_at),
                        odds = EXCLUDED.odds,
                        potential_payout_usdc = EXCLUDED.potential_payout_usdc,
                        raw_order = EXCLUDED.raw_order;
                """, (
                    primary_oid, m_hash, str(market.get("sportXeventId") or ""), sport_lbl, ev_name,
                    market_label, side, total_stake, calc_odds, potential_payout,
                    status, profit, gt_dt, bet_dt, settled_dt, json.dumps(t)
                ))
                updated_count += 1
                if status in ("WON", "LOST", "VOID"):
                    settled_count += 1

            # --- Журнал транзакцій sx_transactions ---
            place_hashes = [h for h in ([f"bet_{trade_id[:20]}"] + own_oids + [f"bet_live_{m_hash[:10]}"]) if h]
            cur.execute("SELECT id, amount_usdc FROM sx_transactions WHERE tx_hash = ANY(%s) LIMIT 1;", (place_hashes,))
            tx_p = cur.fetchone()
            if tx_p:
                # Коригуємо знак суми, якщо раніше було записано з +1.00 замість -1.00
                if float(tx_p[1] or 0) > 0:
                    cur.execute(
                        "UPDATE sx_transactions SET amount_usdc = %s, created_at = %s WHERE id = %s;",
                        (-abs(total_stake), bet_dt, tx_p[0])
                    )
                    stats["tx_synced"] += 1
            else:
                cur.execute("""
                    INSERT INTO sx_transactions (tx_hash, type, amount_usdc, created_at, notes)
                    VALUES (%s, 'BET_PLACED', %s, %s, %s)
                    ON CONFLICT (tx_hash) DO NOTHING;
                """, (
                    f"bet_{trade_id[:20]}",
                    -abs(total_stake),
                    bet_dt,
                    f"Ставка SX Bet: {ev_name} ({side} @ {calc_odds:.2f})"
                ))
                stats["tx_synced"] += 1

            if status in ("WON", "VOID") and total_received > 0:
                payout_hashes = [f"payout_{trade_id[:20]}", f"payout_{m_hash[:20]}"]
                tx_type = "BET_WON" if status == "WON" else "BET_REFUND"
                note_prefix = "Виграш" if status == "WON" else "Повернення"
                cur.execute("SELECT id FROM sx_transactions WHERE tx_hash = ANY(%s) LIMIT 1;", (payout_hashes,))
                if not cur.fetchone():
                    cur.execute("""
                        INSERT INTO sx_transactions (tx_hash, type, amount_usdc, created_at, notes)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (tx_hash) DO NOTHING;
                    """, (
                        f"payout_{trade_id[:20]}",
                        tx_type,
                        total_received,
                        settled_dt or datetime.now(timezone.utc),
                        f"{note_prefix}: {ev_name} ({side})"
                    ))
                    stats["tx_synced"] += 1

        # Синхронізація лімітних мейкер-ордерів (OPEN_ORDER) та очищення прострочених (EXPIRED)
        cur.execute("SELECT id, order_id, market_hash, game_time, status FROM sx_bets WHERE status IN ('PENDING', 'OPEN_ORDER');")
        local_pending = cur.fetchall()
        now_utc = datetime.now(timezone.utc)
        for lp_id, lp_oid, lp_mh, lp_gt, lp_status in local_pending:
            if lp_oid in active_trade_order_ids or lp_mh in active_trade_mhashes:
                continue
            # Якщо ордер активно висить у стакані (/orders-v3), позначаємо як OPEN_ORDER (ще не списав USDC)
            if lp_oid in open_order_ids:
                if lp_status != "OPEN_ORDER":
                    cur.execute("UPDATE sx_bets SET status = 'OPEN_ORDER' WHERE id = %s;", (lp_id,))
                    updated_count += 1
                continue

            # Перевіряємо живий статус ордера на SX Bet
            ord_obj, http_st = sx_client._get_order_with_status(lp_oid)
            m_info = markets_map.get(lp_mh) or {}
            m_st = str(m_info.get("status", "")).upper()
            is_market_closed = m_st in ("INACTIVE", "SETTLED", "RESOLVED", "CANCELLED")
            is_past_game = lp_gt is not None and (_parse_sx_timestamp(lp_gt) or now_utc) < now_utc

            ord_st = str((ord_obj or {}).get("status", "")).upper()
            fill_amt = float((ord_obj or {}).get("filledAmount", 0) or 0)
            if ord_st == "ACTIVE" and fill_amt == 0:
                if lp_status != "OPEN_ORDER":
                    cur.execute("UPDATE sx_bets SET status = 'OPEN_ORDER' WHERE id = %s;", (lp_id,))
                    updated_count += 1
            elif http_st == 404 or ord_st in ("CANCELLED", "EXPIRED", "FAILED") or (ord_obj is None and (is_market_closed or is_past_game)):
                if fill_amt == 0:
                    cur.execute("""
                        UPDATE sx_bets
                        SET status = 'EXPIRED', profit_usdc = 0.0, settled_at = NOW()
                        WHERE id = %s;
                    """, (lp_id,))
                    stats["expired_cleaned"] += 1
                    updated_count += 1

        # Звіряємо фінансовий стан з ончейн Proxy Wallet (враховуємо лише реально виконані LOCKED ставки!)
        if free_balance > 0:
            cur.execute("""
                SELECT
                    COALESCE(SUM(amount_usdc) FILTER (WHERE type = 'DEPOSIT'), 0.0),
                    COALESCE(SUM(ABS(amount_usdc)) FILTER (WHERE type = 'WITHDRAWAL'), 0.0)
                FROM sx_transactions;
            """)
            dep_sum, with_sum = cur.fetchone()
            dep_sum = float(dep_sum or 0.0)
            with_sum = float(with_sum or 0.0)

            cur.execute("""
                SELECT
                    COALESCE(SUM(profit_usdc) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0.0),
                    COALESCE(SUM(stake_usdc) FILTER (WHERE status = 'PENDING'), 0.0)
                FROM sx_bets;
            """)
            net_pnl, active_risked = cur.fetchone()
            net_pnl = float(net_pnl or 0.0)
            active_risked = float(active_risked or 0.0)

            expected_free = round(dep_sum - with_sum + net_pnl - active_risked, 2)
            diff = round(free_balance - expected_free, 2)
            if abs(diff) >= 0.10:
                if diff > 0:
                    cur.execute("""
                        INSERT INTO sx_transactions (tx_hash, type, amount_usdc, balance_after_usdc, notes)
                        VALUES (%s, 'DEPOSIT', %s, %s, %s);
                    """, (f"dep_sync_{int(time.time())}", diff, free_balance, "Автосинхронізація поповнення Proxy Wallet USDC"))
                else:
                    cur.execute("""
                        INSERT INTO sx_transactions (tx_hash, type, amount_usdc, balance_after_usdc, notes)
                        VALUES (%s, 'WITHDRAWAL', %s, %s, %s);
                    """, (f"with_sync_{int(time.time())}", diff, free_balance, "Автосинхронізація виведення з Proxy Wallet USDC"))
                stats["tx_synced"] += 1

        # Перераховуємо хронологічний balance_after_usdc у sx_transactions
        cur.execute("SELECT id, amount_usdc FROM sx_transactions ORDER BY created_at ASC, id ASC;")
        all_txs = cur.fetchall()
        running_bal = 0.0
        for tx_id, tx_amt in all_txs:
            running_bal = round(running_bal + float(tx_amt or 0.0), 2)
            cur.execute("UPDATE sx_transactions SET balance_after_usdc = %s WHERE id = %s;", (running_bal, tx_id))

        # Фіксуємо точний ончейн баланс на останній транзакції, якщо відхилення лише в копійках комісій
        if free_balance > 0 and all_txs:
            cur.execute("UPDATE sx_transactions SET balance_after_usdc = %s WHERE id = %s;", (free_balance, all_txs[-1][0]))

        conn.commit()

    stats["updated_bets"] = updated_count
    stats["settled_bets"] = settled_count
    return stats


def sync_sx_positions_to_db(conn, client: Optional[SXBetClient] = None) -> int:
    """
    Синхронізує активні та завершені позиції/трейди з біржі SX Bet у локальну БД.
    Повертає кількість оновлених/доданих позицій.
    """
    res = sync_sx_exchange_full(conn, client=client)
    return int(res.get("updated_bets", 0) or 0)


def fetch_sx_bets(conn, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Повертає список ставок із таблиці sx_bets."""
    query = """
        SELECT id, order_id, market_hash, event_id, sport_label, event_name,
               market_name, bet_side, stake_usdc, odds, potential_payout_usdc,
               status, profit_usdc, paper_bet_id, game_time, created_at, settled_at
        FROM sx_bets
    """
    params = []
    if status:
        query += " WHERE status = %s"
        params.append(status)
    query += " ORDER BY created_at DESC, id DESC"
    with conn.cursor() as cur:
        cur.execute(query, tuple(params))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_sx_transactions(conn) -> List[Dict[str, Any]]:
    """Повертає історію транзакцій біржі із таблиці sx_transactions."""
    query = """
        SELECT id, tx_hash, type, amount_usdc, balance_after_usdc, created_at, notes
        FROM sx_transactions
        ORDER BY created_at DESC, id DESC
    """
    with conn.cursor() as cur:
        cur.execute(query)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_sx_summary(conn, client: Optional[SXBetClient] = None) -> Dict[str, Any]:
    """
    Агрегує загальний фінансовий стан акаунту SX Bet:
    - Вільний баланс Proxy Wallet (on-chain RPC)
    - Заблокований капітал у грі (Total Risked)
    - Загальний портфель (Portfolio Value)
    - Прибуток/збиток (PnL), ROI %, вінрейт та лічильники ставок
    """
    sx_client = client or SXBetClient()

    # 1. Ончейн вільний баланс
    free_balance = sx_client.get_proxy_usdc_balance()

    # Якщо ончейн RPC повернув 0.0 (через тимчасовий таймаут чи мережеві затримки),
    # використовуємо останній зафіксований баланс із бази даних sx_transactions
    if free_balance == 0.0 and conn:
        try:
            with conn.cursor() as cur_fb:
                cur_fb.execute("SELECT balance_after_usdc FROM sx_transactions WHERE balance_after_usdc IS NOT NULL ORDER BY created_at DESC, id DESC LIMIT 1")
                row_last = cur_fb.fetchone()
                if row_last and row_last[0] is not None and float(row_last[0]) > 0.0:
                    free_balance = float(row_last[0])
        except Exception:
            pass

    # 2. Метрики з бази даних (виключаємо EXPIRED / CANCELLED із активного ризику та оборотів)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status NOT IN ('EXPIRED', 'CANCELLED', 'FAILED', 'OPEN_ORDER')) as total_bets,
                COUNT(*) FILTER (WHERE status = 'PENDING') as pending_cnt,
                COUNT(*) FILTER (WHERE status = 'WON') as won_cnt,
                COUNT(*) FILTER (WHERE status = 'LOST') as lost_cnt,
                COUNT(*) FILTER (WHERE status = 'VOID') as void_cnt,
                COALESCE(SUM(stake_usdc) FILTER (WHERE status = 'PENDING'), 0.0) as total_risked,
                COALESCE(SUM(profit_usdc) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0.0) as total_profit,
                COALESCE(SUM(stake_usdc) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0.0) as settled_turnover
            FROM sx_bets
        """)
        row = cur.fetchone()
        tot_cnt = int(row[0] or 0)
        p_cnt = int(row[1] or 0)
        w_cnt = int(row[2] or 0)
        l_cnt = int(row[3] or 0)
        v_cnt = int(row[4] or 0)
        risked = float(row[5] or 0.0)
        pnl = float(row[6] or 0.0)
        turnover = float(row[7] or 0.0)

        cur.execute("""
            SELECT
                COALESCE(SUM(amount_usdc) FILTER (WHERE type = 'DEPOSIT'), 0.0) as deposits,
                COALESCE(SUM(ABS(amount_usdc)) FILTER (WHERE type = 'WITHDRAWAL'), 0.0) as withdrawals
            FROM sx_transactions
        """)
        t_row = cur.fetchone()
        deposits = float(t_row[0] or 0.0)
        withdrawals = float(t_row[1] or 0.0)

    portfolio_value = round(free_balance + risked, 2)
    roi_pct = (pnl / turnover * 100.0) if turnover > 0 else 0.0
    settled_cnt = w_cnt + l_cnt
    win_rate = (w_cnt / settled_cnt * 100.0) if settled_cnt > 0 else 0.0

    return {
        "portfolio_value_usdc": portfolio_value,
        "free_balance_usdc": round(free_balance, 2),
        "total_risked_usdc": round(risked, 2),
        "total_profit_usdc": round(pnl, 2),
        "roi_pct": roi_pct,
        "turnover_usdc": round(turnover, 2),
        "win_rate": win_rate,
        "deposits_usdc": round(deposits, 2),
        "withdrawals_usdc": round(withdrawals, 2),
        "total_bets": tot_cnt,
        "pending_cnt": p_cnt,
        "won_cnt": w_cnt,
        "lost_cnt": l_cnt,
        "void_cnt": v_cnt,
    }


def normalize_team_text(text: str) -> str:
    """Очищення, транслітерація діакритики та нормалізація назв команд для зіставлення."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", ascii_text.lower())
    stop_words = {
        "fc", "cf", "sc", "afc", "fk", "sk", "ac", "as", "rc", "bc", "sl",
        "united", "city", "de", "la", "the", "club", "real",
    }
    tokens = [t for t in cleaned.split() if t not in stop_words and len(t) > 2]
    if not tokens:
        tokens = [t for t in cleaned.split() if len(t) > 1]
    return " ".join(tokens)


def _teams_similar(p_team: str, sx_team: str) -> bool:
    """Гнучке порівняння назв команд з урахуванням аліасів (e.g. Bayern Munich vs FC Bayern Munich, Praha vs Prague)."""
    if not p_team or not sx_team:
        return False
    if p_team in sx_team or sx_team in p_team:
        return True
    aliases = {
        "praha": "prague",
        "munchen": "munich",
        "bayern": "bayern",
        "wolves": "timberwolves",
        "sixers": "76ers",
        "inter": "internazionale",
        "st": "saint",
        "ny": "new",
    }
    p_toks = {aliases.get(t, t) for t in p_team.split()}
    s_toks = {aliases.get(t, t) for t in sx_team.split()}
    if not p_toks or not s_toks:
        return False
    common = p_toks & s_toks
    return len(common) >= 1 and (len(common) / min(len(p_toks), len(s_toks)) >= 0.5 or any(len(c) >= 5 for c in common))


def fetch_markets_for_paper_bets(sx_client: SXBetClient, paper_bets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Швидко й повно завантажує активні ринки з SX Bet для всіх видів спорту/ліг, присутніх у кандидатах Paper Bank.
    """
    league_ids = set()
    sport_ids = set()
    for pb in paper_bets:
        sp = str(pb.get("sport") or "").lower().strip()
        if sp in ODDS_API_TO_SX_MAP:
            info = ODDS_API_TO_SX_MAP[sp]
            if info.get("league_id"):
                league_ids.add(info["league_id"])
            elif info.get("sport_id"):
                sport_ids.add(info["sport_id"])
        elif sp.startswith("soccer"):
            sport_ids.add(5)
        elif sp.startswith("basketball"):
            sport_ids.add(1)
        elif sp.startswith("icehockey"):
            sport_ids.add(2)
        elif sp.startswith("tennis"):
            sport_ids.add(6)
        elif sp.startswith("americanfootball"):
            sport_ids.add(8)
        elif sp.startswith("mma"):
            sport_ids.add(7)

    by_hash: Dict[str, Dict[str, Any]] = {}
    for lid in league_ids:
        try:
            for m in sx_client.get_active_markets(league_id=lid, max_pages=15):
                mh = m.get("marketHash")
                if mh:
                    by_hash[mh] = m
        except Exception as e:
            logger.warning(f"Помилка завантаження ліги SX Bet {lid}: {e}")

    for sid in sport_ids:
        try:
            for m in sx_client.get_active_markets(sport_id=sid, max_pages=18):
                mh = m.get("marketHash")
                if mh:
                    by_hash[mh] = m
        except Exception as e:
            logger.warning(f"Помилка завантаження спорту SX Bet {sid}: {e}")

    if not league_ids and not sport_ids:
        try:
            for m in sx_client.get_active_markets(max_pages=20):
                mh = m.get("marketHash")
                if mh:
                    by_hash[mh] = m
        except Exception as e:
            logger.warning(f"Помилка завантаження загальних маркетів SX Bet: {e}")

    return list(by_hash.values())


def _extract_number_from_pick(text: str) -> Optional[float]:
    m = re.search(r"([+-]?\d+(?:[.,]\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def match_paper_bet_and_side(
    paper_bet: Dict[str, Any], active_markets: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Точно зіставляє прогноз із Paper Bank із ринком на SX Bet:
    - Перевіряє збіг команд (включно з реверсним порядком господар/гість).
    - Перевіряє збіг дати початку гри (±12 годин), щоб не плутати матчі різних турів.
    - Ігнорує періоди/тайми/четверті для ставок на весь матч.
    - Суворо підбирає тип ринку (Totals type 2/28, Spreads type 3/342, 1X2 type 1, Moneyline type 226)
      та точну лінію (наприклад Over/Under 2.5, Фора +1.5).
    Повертає (market_dict, is_betting_outcome_one).
    """
    match_name = str(paper_bet.get("match_name", ""))
    if " vs " in match_name:
        parts = match_name.split(" vs ", 1)
    elif " - " in match_name:
        parts = match_name.split(" - ", 1)
    else:
        return None, True

    p_t1 = normalize_team_text(parts[0])
    p_t2 = normalize_team_text(parts[1])
    if not p_t1 or not p_t2:
        return None, True

    pb_dt = _parse_sx_timestamp(paper_bet.get("commence_time"))
    pick_raw = str(paper_bet.get("pick_label", "")).strip()
    pick_lbl = pick_raw.lower()

    is_total = any(k in pick_lbl for k in ["тб", "тм", "over", "under", "тотал"])
    is_spread = (any(k in pick_lbl for k in ["ф1", "ф2", "фора", "spread"]) or bool(re.search(r"[+-]\d", pick_lbl))) and not is_total
    is_draw = pick_lbl in ("х", "x", "нічия", "draw", "tie") or "нічия" in pick_lbl or "draw" in pick_lbl
    is_moneyline = not is_total and not is_spread

    target_line: Optional[float] = None
    if is_total:
        target_line = _extract_number_from_pick(pick_lbl)
    elif is_spread:
        # Витягуємо форове значення з дужок або після ф1/ф2 (не сам номер команди!)
        m_sp = re.search(r"\(([+-]?\d+(?:[.,]\d+)?)\)", pick_lbl)
        if not m_sp:
            m_sp = re.search(r"(?:ф[12]|фора|spread)\s*([+-]?\d+(?:[.,]\d+)?)", pick_lbl)
        if not m_sp:
            m_sp = re.search(r"([+-]\d+(?:[.,]\d+)?)", pick_lbl)
        if m_sp:
            target_line = float(m_sp.group(1).replace(",", "."))

    # Збираємо кандидатів за командами та часом матчу
    candidates: List[Dict[str, Any]] = []
    for m in active_markets:
        sx_t1 = normalize_team_text(m.get("teamOneName", ""))
        sx_t2 = normalize_team_text(m.get("teamTwoName", ""))
        if not sx_t1 or not sx_t2:
            continue

        match_direct = _teams_similar(p_t1, sx_t1) and _teams_similar(p_t2, sx_t2)
        match_rev = _teams_similar(p_t1, sx_t2) and _teams_similar(p_t2, sx_t1)
        if not (match_direct or match_rev):
            continue

        # Перевірка часу матчу (±12 годин), якщо обидві дати відомі
        if pb_dt and m.get("gameTime"):
            m_dt = _parse_sx_timestamp(m.get("gameTime"))
            if m_dt and abs((m_dt - pb_dt).total_seconds()) > 12 * 3600:
                continue

        # Відфільтровуємо тайми/періоди/чверті, якщо в прогнозі це не прописано
        o1_l = str(m.get("outcomeOneName", "")).lower()
        o2_l = str(m.get("outcomeTwoName", "")).lower()
        if any(sub in o1_l or sub in o2_l for sub in ["1st half", "2nd half", "1st period", "2nd period", "3rd period", "quarter"]):
            if not any(sub in pick_lbl for sub in ["half", "тайм", "період", "period", "чверт"]):
                continue

        candidates.append(m)

    if not candidates:
        return None, True

    best_m: Optional[Dict[str, Any]] = None
    is_outcome_one = True

    if is_total:
        want_over = "тб" in pick_lbl or "over" in pick_lbl
        want_under = "тм" in pick_lbl or "under" in pick_lbl
        total_mkts = []
        for m in candidates:
            m_type = m.get("type")
            o1 = str(m.get("outcomeOneName", "")).lower()
            o2 = str(m.get("outcomeTwoName", "")).lower()
            if m_type in (2, 28) or ("over" in o1 and "under" in o2) or ("under" in o1 and "over" in o2):
                total_mkts.append(m)

        # Шукаємо точний збіг лінії (наприклад 2.5 == 2.5)
        for m in total_mkts:
            m_line = m.get("line")
            if target_line is not None and m_line is not None:
                try:
                    if abs(float(m_line) - float(target_line)) <= 0.05:
                        best_m = m
                        break
                except (ValueError, TypeError):
                    pass
            elif target_line is not None:
                o1_num = _extract_number_from_pick(str(m.get("outcomeOneName", "")))
                if o1_num is not None and abs(o1_num - target_line) <= 0.05:
                    best_m = m
                    break

        if best_m:
            o1 = str(best_m.get("outcomeOneName", "")).lower()
            if want_under:
                is_outcome_one = "under" in o1 or "тм" in o1
            else:
                is_outcome_one = "over" in o1 or "тб" in o1
            return best_m, is_outcome_one
        return None, True

    if is_spread:
        want_team = p_t2 if ("ф2" in pick_lbl or (_teams_similar(p_t2, normalize_team_text(pick_raw)) and "ф1" not in pick_lbl)) else p_t1
        spread_mkts = []
        for m in candidates:
            m_type = m.get("type")
            o1 = str(m.get("outcomeOneName", ""))
            o2 = str(m.get("outcomeTwoName", ""))
            if m_type in (3, 342) or (any(ch in o1 for ch in ("+", "-")) and any(ch in o2 for ch in ("+", "-"))):
                spread_mkts.append(m)

        for m in spread_mkts:
            o1_str = str(m.get("outcomeOneName", ""))
            o2_str = str(m.get("outcomeTwoName", ""))
            for idx_one, o_txt in [(True, o1_str), (False, o2_str)]:
                if _teams_similar(want_team, normalize_team_text(o_txt)):
                    o_val = _extract_number_from_pick(o_txt)
                    if target_line is None or (o_val is not None and abs(o_val - target_line) <= 0.05):
                        return m, idx_one
        return None, True

    # Moneyline / 1X2
    want_team = None
    if not is_draw:
        if "п2" in pick_lbl or pick_lbl == "2" or "(2)" in pick_lbl:
            want_team = p_t2
        elif "п1" in pick_lbl or pick_lbl == "1" or "(1)" in pick_lbl:
            want_team = p_t1
        elif _teams_similar(p_t2, normalize_team_text(pick_raw)):
            want_team = p_t2
        elif _teams_similar(p_t1, normalize_team_text(pick_raw)):
            want_team = p_t1
        else:
            want_team = p_t1

    # 1) Шукаємо 2-way Moneyline (type 226)
    for m in candidates:
        if m.get("type") == 226 or (
            m.get("type") is None
            and "not " not in str(m.get("outcomeTwoName", "")).lower()
            and "over" not in str(m.get("outcomeOneName", "")).lower()
        ):
            if is_draw:
                continue
            o1_norm = normalize_team_text(m.get("outcomeOneName", ""))
            o2_norm = normalize_team_text(m.get("outcomeTwoName", ""))
            if _teams_similar(want_team, o1_norm):
                return m, True
            if _teams_similar(want_team, o2_norm):
                return m, False

    # 2) Шукаємо футбольний 1X2 ринок (type 1: Team / Not Team або Tie / Not tie)
    for m in candidates:
        if m.get("type") == 1 or "not " in str(m.get("outcomeTwoName", "")).lower():
            o1_str = str(m.get("outcomeOneName", "")).lower()
            if is_draw:
                if "tie" in o1_str or "draw" in o1_str:
                    return m, True
            else:
                o1_norm = normalize_team_text(m.get("outcomeOneName", ""))
                if _teams_similar(want_team, o1_norm):
                    return m, True

    # 3) Fallback на Draw No Bet (type 52), якщо 1X2 недоступний
    if not is_draw:
        for m in candidates:
            if m.get("type") == 52:
                o1_norm = normalize_team_text(m.get("outcomeOneName", ""))
                o2_norm = normalize_team_text(m.get("outcomeTwoName", ""))
                if _teams_similar(want_team, o1_norm):
                    return m, True
                if _teams_similar(want_team, o2_norm):
                    return m, False

    return None, True


def match_paper_bet_to_sx_market(
    paper_bet: Dict[str, Any], active_markets: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Повертає підібраний словник ринку SX Bet (або None), зберігаючи сумісність інтерфейсу.
    """
    m, _ = match_paper_bet_and_side(paper_bet, active_markets)
    return m


def auto_sync_and_stake_from_paper(
    conn,
    client: Optional[SXBetClient] = None,
    min_confidence: Optional[int] = None,
    stake_usdc: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Автоматичний сканер та стейкер SX Bet:
    1. Завантажує налаштування ризик-менеджменту (% від банку USDC, мін. 1.00 USDC, поріг впевненості).
    2. Отримує кандидатів з paper_bets (PENDING, is_shadow=FALSE), які ще не мають активної/закритої ставки на біржі.
    3. Пошук ринків виконується з пагінацією за відповідними лігами/видами спорту, перевіркою часу матчу та лінії.
    4. Розраховує ставку як % від поточного портфелю/вільного балансу USDC (але не менше 1.00 USDC).
    5. Перевіряє реальний стакан (GET /orderbook-v3/snapshot/market) для миттєвого виконання (Taker) або виставляє лімітний ордер.
    """
    sx_client = client or SXBetClient()
    if not sx_client.api_key or not sx_client.private_key:
        logger.warning("API-ключ або приватний ключ SX Bet не налаштовано. Пропуск авто-стейкінгу.")
        return []

    cfg = get_sx_staking_config(conn)
    eff_min_conf = int(min_confidence if min_confidence is not None else cfg.get("min_confidence", 7))

    # 1. Знаходимо кандидатів у paper_bets
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, sport, match_name, commence_time, pick_label, odds, kelly_pct, confidence_score, walkaway_odds
            FROM paper_bets
            WHERE status = 'PENDING'
              AND is_shadow = FALSE
              AND COALESCE(confidence_score, 0) >= %s
              AND commence_time > NOW() + INTERVAL '5 minutes'
              AND id NOT IN (
                  SELECT paper_bet_id FROM sx_bets
                  WHERE paper_bet_id IS NOT NULL
                    AND status NOT IN ('EXPIRED', 'CANCELLED', 'FAILED')
              )
            ORDER BY commence_time ASC, id DESC
            LIMIT 10
        """, (eff_min_conf,))
        cols = [desc[0] for desc in cur.description]
        candidates = [dict(zip(cols, row)) for row in cur.fetchall()]

    if not candidates:
        return []

    # 2. Завантажуємо активні ринки SX Bet по відповідних лігах та видах спорту
    active_markets = fetch_markets_for_paper_bets(sx_client, candidates)
    if not active_markets:
        return []

    # 3. Отримуємо поточний баланс та портфель у USDC для відсоткового розрахунку
    summary = fetch_sx_summary(conn, sx_client)
    free_usdc = float(summary.get("free_balance_usdc", 0.0) or 0.0)
    portfolio_usdc = float(summary.get("portfolio_value_usdc", 0.0) or free_usdc)
    bank_base_usdc = max(free_usdc, portfolio_usdc)

    placed_results = []
    now_ts = int(time.time())

    for pb in candidates:
        matched_m, is_outcome_one = match_paper_bet_and_side(pb, active_markets)
        if not matched_m:
            continue

        market_hash = matched_m["marketHash"]
        paper_odds = float(pb.get("odds", 1.90) or 1.90)
        walkaway = float(pb.get("walkaway_odds") or 0.0)
        min_acceptable_odds = max(1.05, walkaway if walkaway > 1.05 else round(paper_odds * 0.90, 2))

        # Розрахунок ставки у % від банку USDC (але не менше 1.00 USDC)
        if stake_usdc is not None:
            bet_size_usdc = round(float(stake_usdc), 2)
            applied_pct = round((bet_size_usdc / bank_base_usdc) * 100.0, 2) if bank_base_usdc > 0 else 0.0
        else:
            bet_size_usdc, applied_pct = calculate_sx_stake_usdc(
                bank_usdc=bank_base_usdc,
                free_usdc=free_usdc,
                odds=paper_odds,
                kelly_pct=float(pb["kelly_pct"]) if pb.get("kelly_pct") is not None else None,
                confidence=int(pb["confidence_score"]) if pb.get("confidence_score") is not None else None,
                config=cfg,
            )

        if bet_size_usdc < 1.0 or free_usdc < bet_size_usdc:
            logger.info(f"Недостатньо вільного USDC ({free_usdc:.2f}) для ставки {bet_size_usdc:.2f} по #{pb['id']}")
            continue

        # Перевіряємо живий стакан SX Bet (ліквідність для миттєвого виконання)
        best_taker = sx_client.get_best_taker_offer(market_hash, is_outcome_one, min_size_usdc=bet_size_usdc)
        if best_taker and best_taker["decimal_odds"] >= min_acceptable_odds:
            order_odds = best_taker["decimal_odds"]
            expiry_sec = 1800
            exec_mode = "TAKER"
        else:
            # Якщо зустрічна пропозиція нижча за мінімум — виставляємо лімітний ордер до старту гри (макс 4 год)
            if best_taker and best_taker["decimal_odds"] < min_acceptable_odds:
                logger.info(
                    f"[SX Bet] Коеф. у стакані для #{pb['id']} ({best_taker['decimal_odds']}) нижчий за поріг ({min_acceptable_odds}). Ставимо лімітний ордер за {paper_odds}."
                )
            order_odds = paper_odds
            gt_ts = int(_parse_sx_timestamp(matched_m.get("gameTime")).timestamp()) if matched_m.get("gameTime") else (now_ts + 4 * 3600)
            expiry_sec = max(900, min(4 * 3600, gt_ts - now_ts - 120))
            exec_mode = "MAKER"

        try:
            order = sx_client.build_order_payload(
                market_hash=market_hash,
                total_bet_size_usdc=bet_size_usdc,
                decimal_odds=order_odds,
                is_betting_outcome_one=is_outcome_one,
                expiry_seconds=expiry_sec,
            )
            sig = sx_client.sign_order(order)
            res = sx_client.place_order(order, signature=sig, dry_run=False)

            order_data = res.get("data", {}).get("orders", [{}])[0]
            order_id = order_data.get("orderId") or order.get("marketHash")

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sx_bets (
                        order_id, market_hash, event_id, sport_label, event_name,
                        market_name, bet_side, stake_usdc, odds, potential_payout_usdc,
                        status, paper_bet_id, game_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO NOTHING
                """, (
                    order_id,
                    market_hash,
                    matched_m.get("sportXeventId"),
                    matched_m.get("sportLabel"),
                    f"{matched_m.get('teamOneName')} vs {matched_m.get('teamTwoName')}",
                    f"{matched_m.get('outcomeOneName')} / {matched_m.get('outcomeTwoName')}",
                    matched_m.get("outcomeOneName") if is_outcome_one else matched_m.get("outcomeTwoName"),
                    bet_size_usdc,
                    order_odds,
                    round(bet_size_usdc * order_odds, 2),
                    "OPEN_ORDER",
                    pb["id"],
                    pb.get("commence_time"),
                ))
                conn.commit()

            free_usdc = round(free_usdc - bet_size_usdc, 2)
            placed_results.append({
                "paper_bet_id": pb["id"],
                "order_id": order_id,
                "event": pb["match_name"],
                "stake_usdc": bet_size_usdc,
                "pct": applied_pct,
                "odds": order_odds,
                "mode": exec_mode,
                "status": "PLACED",
            })
            logger.info(
                f"Авто-ставка SX Bet ({exec_mode}) для paper #{pb['id']}: ${bet_size_usdc:.2f} USDC ({applied_pct}%) @ {order_odds} | order {order_id}"
            )
        except Exception as e:
            logger.error(f"Помилка розміщення авто-ставки для #{pb['id']}: {e}")
            try:
                from statmonitor.database import log_system_error
                log_system_error(
                    conn,
                    "sx_bet",
                    f"Помилка авто-ставки SX Bet (Paper #{pb['id']} {pb.get('match_name')}): {e}",
                    severity="ERROR",
                    error_code="STAKE_FAILED",
                    details={"paper_id": pb["id"], "match": pb.get("match_name"), "error": str(e)},
                )
            except Exception:
                pass

    # Даємо блокчейну SX Rollup 2 сек для фіналізації Taker-трейдів і синхронізуємо угоди та баланси
    if placed_results:
        time.sleep(2.0)
        try:
            sync_sx_exchange_full(conn, client=sx_client)
        except Exception as se:
            logger.warning(f"Пост-стейк синхронізація SX Bet notice: {se}")

    return placed_results

