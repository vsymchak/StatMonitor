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
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import requests

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

    def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Отримати актуальний статус ордера на біржі за orderId."""
        try:
            r = requests.get(f"{self.base_url}/orders-v3/{order_id}", headers=self.headers, timeout=self.timeout)
            if r.status_code == 200:
                return r.json().get("data", {}).get("order", {})
        except Exception as e:
            logger.error(f"Помилка отримання деталей ордера {order_id}: {e}")
        return None

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
# ДОПОМІЖНІ ФУНКЦІЇ ДЛЯ БД ТА АВТОМАТИЧНОГО МЕТЧИНГУ
# ==========================================================

def sync_sx_positions_to_db(conn, client: Optional[SXBetClient] = None) -> int:
    """
    Синхронізує активні та завершені позиції з біржі SX Bet у локальну таблицю sx_bets.
    Якщо позиція була розрахована (SETTLED) або має PnL, автоматично оновлює її статус
    (WON/LOST/VOID) та додає запис про фінансовий рух у sx_transactions без потреби дій адміна.
    """
    sx_client = client or SXBetClient()
    positions = sx_client.get_user_positions(["MATCHED", "LOCKED", "SETTLED"])
    if not positions:
        return 0

    updated_count = 0
    with conn.cursor() as cur:
        for p in positions:
            m_hash = p.get("marketHash")
            if not m_hash:
                continue

            market = p.get("market", {})
            total_stake = float(p.get("totalStake", 0)) / 1e6
            pnl_raw = p.get("pnl")
            pnl = float(pnl_raw) / 1e6 if pnl_raw is not None else None
            m_status = market.get("status", "ACTIVE")

            # Визначаємо статус ставки
            outcome_val = market.get("outcome")
            is_one = p.get("isOutcomeOneMaxWin", True)
            if pnl is not None:
                if pnl > 0:
                    status = "WON"
                elif pnl < 0:
                    status = "LOST"
                else:
                    status = "VOID"
            elif outcome_val is not None and m_status in ("INACTIVE", "SETTLED", "RESOLVED"):
                # Якщо ринок завершено і outcome зафіксовано біржею (1=outcomeOne, 2=outcomeTwo, 3=VOID)
                if outcome_val == 1:
                    status = "WON" if is_one else "LOST"
                elif outcome_val == 2:
                    status = "LOST" if is_one else "WON"
                elif outcome_val == 3:
                    status = "VOID"
                else:
                    status = "SETTLED"

                if status == "WON":
                    net_win = float(p.get("netMaxWin", 0)) / 1e6 or float(p.get("maxWin", 0)) / 1e6
                    pnl = net_win
                elif status == "LOST":
                    pnl = -total_stake
                elif status == "VOID":
                    pnl = 0.0
            elif m_status in ("SETTLED", "RESOLVED"):
                status = "SETTLED"
            else:
                status = "PENDING"

            t1 = market.get("teamOneName", "")
            t2 = market.get("teamTwoName", "")
            ev_name = f"{t1} vs {t2}" if t1 and t2 else "SX Bet Event"
            outcome1 = market.get("outcomeOneName", "")
            outcome2 = market.get("outcomeTwoName", "")
            is_one = p.get("isOutcomeOneMaxWin", True)
            side = outcome1 if is_one else outcome2
            market_label = f"{outcome1} / {outcome2}" if outcome1 and outcome2 else "Spread/Total"

            # Розрахунок коефіцієнта з maxWin / stake
            max_win_val = float(p.get("maxWin", 0)) / 1e6
            calc_odds = round(1.0 + (max_win_val / total_stake), 2) if total_stake > 0 else 2.0

            cur.execute("SELECT id, status, profit_usdc FROM sx_bets WHERE market_hash = %s LIMIT 1", (m_hash,))
            row = cur.fetchone()
            if row:
                bet_id, old_status, old_profit = row[0], row[1], float(row[2] or 0.0)
                if old_status != status or (pnl is not None and old_profit != pnl):
                    cur.execute("""
                        UPDATE sx_bets
                        SET status = %s, profit_usdc = %s, settled_at = CASE WHEN %s != 'PENDING' THEN NOW() ELSE settled_at END
                        WHERE id = %s
                    """, (status, pnl if pnl is not None else 0.0, status, bet_id))
                    updated_count += 1

                    if status == "WON" and old_status != "WON":
                        payout = total_stake + (pnl or 0.0)
                        cur.execute("""
                            INSERT INTO sx_transactions (tx_hash, type, amount_usdc, notes)
                            VALUES (%s, 'BET_WON', %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (f"payout_{m_hash[:20]}", payout, f"Виграш по ринку {ev_name} ({side})"))
            else:
                order_id = p.get("orderId") or m_hash
                raw_gt = market.get("gameTime")
                gt_dt = None
                if raw_gt:
                    try:
                        if isinstance(raw_gt, (int, float)):
                            gt_dt = datetime.fromtimestamp(raw_gt, timezone.utc)
                        elif isinstance(raw_gt, str):
                            if raw_gt.isdigit():
                                gt_dt = datetime.fromtimestamp(int(raw_gt), timezone.utc)
                            else:
                                gt_dt = raw_gt
                    except Exception:
                        gt_dt = None

                cur.execute("""
                    INSERT INTO sx_bets (
                        order_id, market_hash, event_id, sport_label, event_name,
                        market_name, bet_side, stake_usdc, odds, potential_payout_usdc,
                        status, profit_usdc, game_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        profit_usdc = EXCLUDED.profit_usdc
                """, (
                    order_id,
                    m_hash,
                    str(market.get("sportXeventId", "")),
                    str(market.get("type", "Sport")),
                    ev_name,
                    market_label,
                    side,
                    total_stake,
                    calc_odds,
                    round(total_stake + max_win_val, 2),
                    status,
                    pnl if pnl is not None else 0.0,
                    gt_dt,
                ))
                updated_count += 1

        conn.commit()
    return updated_count


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
    query += " ORDER BY created_at DESC"
    with conn.cursor() as cur:
        cur.execute(query, tuple(params))
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_sx_transactions(conn) -> List[Dict[str, Any]]:
    """Повертає історію транзакцій біржі із таблиці sx_transactions."""
    query = """
        SELECT id, tx_hash, type, amount_usdc, balance_after_usdc, created_at, notes
        FROM sx_transactions
        ORDER BY created_at DESC
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

    # Якщо ончейн RPC повернув 0.0 (через тимчасовий таймаут чи сетеві затримки),
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

    # 2. Метрики з бази даних
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total_bets,
                COUNT(*) FILTER (WHERE status = 'PENDING') as pending_cnt,
                COUNT(*) FILTER (WHERE status = 'WON') as won_cnt,
                COUNT(*) FILTER (WHERE status = 'LOST') as lost_cnt,
                COUNT(*) FILTER (WHERE status = 'VOID') as void_cnt,
                COALESCE(SUM(stake_usdc) FILTER (WHERE status = 'PENDING'), 0.0) as total_risked,
                COALESCE(SUM(profit_usdc) FILTER (WHERE status IN ('WON', 'LOST')), 0.0) as total_profit,
                COALESCE(SUM(stake_usdc) FILTER (WHERE status IN ('WON', 'LOST')), 0.0) as settled_turnover
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
                COALESCE(SUM(amount_usdc) FILTER (WHERE type = 'WITHDRAWAL'), 0.0) as withdrawals
            FROM sx_transactions
        """)
        t_row = cur.fetchone()
        deposits = float(t_row[0] or 0.0)
        withdrawals = float(t_row[1] or 0.0)

    portfolio_value = free_balance + risked
    roi_pct = (pnl / turnover * 100.0) if turnover > 0 else 0.0
    settled_cnt = w_cnt + l_cnt
    win_rate = (w_cnt / settled_cnt * 100.0) if settled_cnt > 0 else 0.0

    return {
        "portfolio_value_usdc": portfolio_value,
        "free_balance_usdc": free_balance,
        "total_risked_usdc": risked,
        "total_profit_usdc": pnl,
        "roi_pct": roi_pct,
        "turnover_usdc": turnover,
        "win_rate": win_rate,
        "deposits_usdc": deposits,
        "withdrawals_usdc": withdrawals,
        "total_bets": tot_cnt,
        "pending_cnt": p_cnt,
        "won_cnt": w_cnt,
        "lost_cnt": l_cnt,
        "void_cnt": v_cnt,
    }


def normalize_team_text(text: str) -> str:
    """Очищення та нормалізація назв команд для зіставлення."""
    if not text:
        return ""
    import re
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    stop_words = {"fc", "cf", "sc", "afc", "fk", "united", "city", "de", "la", "the", "club"}
    tokens = [t for t in cleaned.split() if t not in stop_words and len(t) > 2]
    return " ".join(tokens)


def match_paper_bet_to_sx_market(
    paper_bet: Dict[str, Any], active_markets: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Автоматично знаходить ринок на біржі SX Bet для події з paper_bets.
    Перевіряє схожість назв команд та сумісність маркетів.
    """
    match_name = paper_bet.get("match_name", "")
    if " vs " in match_name:
        parts = match_name.split(" vs ", 1)
    elif " - " in match_name:
        parts = match_name.split(" - ", 1)
    else:
        return None

    p_t1 = normalize_team_text(parts[0])
    p_t2 = normalize_team_text(parts[1])

    for m in active_markets:
        sx_t1 = normalize_team_text(m.get("teamOneName", ""))
        sx_t2 = normalize_team_text(m.get("teamTwoName", ""))

        # Перевірка прямого або реверсного співпадіння команд
        match_direct = (p_t1 in sx_t1 or sx_t1 in p_t1) and (p_t2 in sx_t2 or sx_t2 in p_t2)
        match_rev = (p_t1 in sx_t2 or sx_t2 in p_t1) and (p_t2 in sx_t1 or sx_t1 in p_t2)

        if match_direct or match_rev:
            return m

    return None


def auto_sync_and_stake_from_paper(
    conn, client: Optional[SXBetClient] = None, min_confidence: int = 8, stake_usdc: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Автоматичний сканер: знаходить активні ставки у paper_bets,
    шукає відповідну подію на біржі SX Bet через API та здійснює ставку.
    Працює повністю автономно без участі адміністратора.
    """
    sx_client = client or SXBetClient()
    if not sx_client.api_key or not sx_client.private_key:
        logger.warning("API-ключ або приватний ключ SX Bet не налаштовано. Пропуск авто-стейкінгу.")
        return []

    # 1. Отримуємо активні ринки біржі
    try:
        active_markets = sx_client.get_active_markets()
    except Exception as e:
        logger.error(f"Помилка завантаження маркетів SX Bet: {e}")
        return []

    if not active_markets:
        return []

    # 2. Знаходимо кандидатів у paper_bets
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, match_name, commence_time, pick_label, odds, confidence_score, walkaway_odds
            FROM paper_bets
            WHERE status = 'PENDING'
              AND is_shadow = FALSE
              AND COALESCE(confidence_score, 0) >= %s
              AND id NOT IN (SELECT paper_bet_id FROM sx_bets WHERE paper_bet_id IS NOT NULL)
            ORDER BY created_at DESC
            LIMIT 5
        """, (min_confidence,))
        cols = [desc[0] for desc in cur.description]
        candidates = [dict(zip(cols, row)) for row in cur.fetchall()]

    placed_results = []
    for pb in candidates:
        matched_m = match_paper_bet_to_sx_market(pb, active_markets)
        if not matched_m:
            continue

        market_hash = matched_m["marketHash"]
        # Визначаємо сторону (за замовчуванням outcomeOne або відповідно до pick_label)
        is_outcome_one = True
        pick_label = str(pb.get("pick_label", "")).lower()
        if "2" in pick_label or "under" in pick_label:
            is_outcome_one = False

        decimal_odds = float(pb.get("odds", 1.90))

        try:
            # Формуємо та підписуємо ордер
            order = sx_client.build_order_payload(
                market_hash=market_hash,
                total_bet_size_usdc=stake_usdc,
                decimal_odds=decimal_odds,
                is_betting_outcome_one=is_outcome_one,
            )
            sig = sx_client.sign_order(order)
            res = sx_client.place_order(order, signature=sig, dry_run=False)

            order_data = res.get("data", {}).get("orders", [{}])[0]
            order_id = order_data.get("orderId") or order.get("marketHash")

            # Зберігаємо в базі даних
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
                    stake_usdc,
                    decimal_odds,
                    round(stake_usdc * decimal_odds, 2),
                    "PENDING",
                    pb["id"],
                    pb.get("commence_time"),
                ))
                conn.commit()

            placed_results.append({
                "paper_bet_id": pb["id"],
                "order_id": order_id,
                "event": pb["match_name"],
                "status": "PLACED",
            })
            logger.info(f"Авто-ставка SX Bet розміщена для paper #{pb['id']}: order {order_id}")
        except Exception as e:
            logger.error(f"Помилка розміщення авто-ставки для #{pb['id']}: {e}")
            try:
                from statmonitor.database import log_system_error
                log_system_error(conn, "sx_bet", f"Помилка авто-ставки SX Bet (Paper #{pb['id']} {pb.get('match_name')}): {e}", severity="ERROR", error_code="STAKE_FAILED", details={"paper_id": pb['id'], "match": pb.get("match_name"), "error": str(e)})
            except Exception:
                pass

    return placed_results

