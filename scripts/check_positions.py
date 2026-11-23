import os
import sys
import time
import json
import requests
sys.path.insert(0, os.path.abspath("."))

from statmonitor.sx_bet import SXBetClient

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

client = SXBetClient()
positions = client.get_user_positions(["MATCHED", "LOCKED", "SETTLED"])
print(f"Total positions on SX Bet: {len(positions)}")
for i, p in enumerate(positions):
    m = p.get("market", {})
    t1 = m.get("teamOneName")
    t2 = m.get("teamTwoName")
    gt = m.get("gameTime")
    gt_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(gt)) if gt else "N/A"
    o1 = m.get("outcomeOneName")
    o2 = m.get("outcomeTwoName")
    side = o1 if p.get("isOutcomeOneMaxWin") else o2
    stake = int(p.get("totalStake", 0)) / 1e6
    win = int(p.get("maxWin", 0)) / 1e6
    print(f"\n[Position #{i+1}]")
    print(f"  Event: {t1} vs {t2}")
    print(f"  Side: {side} (Market: {o1} / {o2})")
    print(f"  Stake: ${stake:.2f} USDC | Max Win: ${win:.2f} USDC")
    print(f"  GameTime: {gt_str} UTC | Market Status: {m.get('status')}")
    print(f"  MarketHash: {p.get('marketHash')}")

# Also check open orders on the exchange
r_orders = requests.get(f"{client.base_url}/orders-v3", headers=client.headers, params={"maker": client.wallet_address})
print(f"\nOpen/resting orders for maker: status {r_orders.status_code}")
if r_orders.status_code == 200:
    ords = r_orders.json().get("data", {}).get("orders", [])
    print(f"Found {len(ords)} open/resting orders:")
    for o in ords:
        size = int(o.get("totalBetSize", 0)) / 1e6
        print(f"  Order ID: {o.get('orderId')} | Size: ${size:.2f} | Hash: {o.get('marketHash')} | Status: {o.get('status')}")

# Check on-chain balance
bal = client.get_proxy_usdc_balance()
print(f"\nOn-chain Proxy Wallet USDC Balance: ${bal:.4f} USDC")

# Sync to Supabase DB
import psycopg2
from statmonitor.sx_bet import sync_sx_positions_to_db, fetch_sx_bets, fetch_sx_summary
db_url = os.environ.get("SUPABASE_DB_URL")
if db_url:
    conn = psycopg2.connect(db_url)
    up = sync_sx_positions_to_db(conn, client)
    print(f"Synced {up} positions to Supabase DB!")
    bets = fetch_sx_bets(conn)
    print(f"Total sx_bets in DB: {len(bets)}")
    for b in bets:
        print(f"  #{b['id']}: {b['event_name']} | {b['bet_side']} | ${b['stake_usdc']} @ {b['odds']} | status: {b['status']}")
    # Insert transaction for the live bet if not already present
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sx_transactions (tx_hash, type, amount_usdc, balance_after_usdc, notes)
            VALUES (%s, 'BET_PLACED', %s, %s, %s)
            ON CONFLICT (tx_hash) DO NOTHING
        """, ("bet_live_0x37ea9d87", 1.00, bal, "Авто-ставка на лайв матч SC Internacional vs Esporte Clube Vitoria"))
        conn.commit()
    
    summary = fetch_sx_summary(conn, client)
    print("\nUpdated SX Summary:", summary)
    conn.close()

