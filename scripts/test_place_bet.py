"""
scripts/test_place_bet.py
Скрипт для тестування виставлення ставки на живу подію в SX Bet (Крок 40).
"""

import sys
import os
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from statmonitor.sx_bet import SXBetClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    print("=" * 60)
    print("⚡ SX Bet Live Staking Test (OrderBook V3)")
    print("=" * 60)

    client = SXBetClient()

    # 1. Перевірка API ключа
    if not client.api_key:
        print("⚠️ УВАГА: Ключ 'x-sx-api-key' (MY_GEM_BOT / SX_BET_API_KEY) не знайдено в локальному .env!")
        print("   Для виконання запитів на SX Bet сервер вимагає цей заголовок.")
    else:
        masked = client.api_key[:6] + "..." + client.api_key[-4:] if len(client.api_key) > 10 else "***"
        print(f"🔑 Знайдено API ключ: {masked}")

    # Перевірка гаманця
    if client.wallet_address:
        print(f"👛 Адреса акаунту (EOA): {client.wallet_address}")
        # Перевірка Proxy Wallet через API
        import requests
        try:
            r = requests.get(f"{client.base_url}/user/proxy", headers=client.headers, timeout=10)
            if r.status_code == 200:
                pdata = r.json().get("data", {})
                proxy_addr = pdata.get("obv3ProxyWalletAddress")
                is_deployed = pdata.get("deployed")
                print(f"📦 Proxy Wallet: {proxy_addr} (Deployed: {is_deployed})")
                # Перевірка балансу USDC в Proxy
                rpc = "https://rpc-rollup.sx.technology"
                usdc = "0x6629Ce1Cf35Cc1329ebB4F63202F3f197b3F050B"
                data = "0x70a08231" + proxy_addr[2:].lower().zfill(64)
                rr = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": usdc, "data": data}, "latest"]})
                bal = int(rr.json().get("result", "0x0"), 16) / 1e6
                print(f"💰 Баланс USDC у Proxy: {bal:.4f} USDC")
        except Exception as e:
            print(f"Помилка перевірки Proxy: {e}")

    # 2. Отримання актуального лайв-ринку
    print("\n🔍 Пошук активних Live-подій...")
    live_markets = client.get_active_markets(live_only=True)
    if not live_markets:
        print("❌ Не знайдено активних live-ринків на біржі у цей момент.")
        return

    m = live_markets[0]
    market_hash = m["marketHash"]
    sport = m.get("sportLabel", "Sport")
    team1 = m.get("teamOneName", "Team 1")
    team2 = m.get("teamTwoName", "Team 2")
    out1 = m.get("outcomeOneName", "Outcome 1")
    out2 = m.get("outcomeTwoName", "Outcome 2")

    print(f"🎯 Обрано лайв-подію: {sport} · {team1} vs {team2}")
    print(f"   Маркет: {out1} / {out2}")
    print(f"   MarketHash: {market_hash}")

    # 3. Валідація параметрів ставки 1 USDC
    amount_usdc = 1.0
    val = client.validate_bet_parameters(amount_usdc, "USDC")
    print(f"\n📋 Валідація: {amount_usdc} USDC -> {'✅ Успішно' if val['valid'] else '❌ Помилка'}")

    # 4. Формування ордера
    # Якщо гаманець не задано, генеруємо тимчасовий тестовий гаманець для перевірки структури
    temp_wallet = False
    if not client.wallet_address:
        from eth_account import Account
        temp_acc = Account.create()
        client.wallet_address = temp_acc.address
        client.private_key = temp_acc.key.hex()
        temp_wallet = True
        print(f"ℹ️ Створено тимчасовий EVM тестовий гаманець: {client.wallet_address}")

    order = client.build_order_payload(
        market_hash=market_hash,
        total_bet_size_usdc=amount_usdc,
        decimal_odds=1.90,
        is_betting_outcome_one=True,
    )
    print("\n📦 Сформований Payload ордера (OBv3):")
    print(json.dumps(order, indent=2))

    # 5. EIP-712 підпис
    sig = client.sign_order(order)
    print(f"\n✍️ Цифровий підпис (ECDSA/EIP-712): {sig[:18]}...{sig[-10:]}")

    # 6. Відправка ордера на сервер SX Bet (POST /orders-v3)
    print("\n🚀 Відправка ордера на https://api.sx.bet/orders-v3 ...")
    try:
        res = client.place_order(order, signature=sig, dry_run=False)
        print("🎉 ВІДПОВІДЬ СЕРВЕРА SX BET:")
        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"❌ Сервер SX Bet відхилив запит: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"   Код статусу: {e.response.status_code}")
            print(f"   Тіло відповіді: {e.response.text}")


if __name__ == "__main__":
    main()
