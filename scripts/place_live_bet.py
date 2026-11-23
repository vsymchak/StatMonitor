import os
import sys
import time
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

# Find the market in all_markets
mkt_live = None
for m in all_markets:
    if m.get("marketHash") == m_hash_live:
        mkt_live = m
        break

print("Actual market for hash 0x37ea9d...:", mkt_live.get("teamOneName"), "vs", mkt_live.get("teamTwoName"), "| sport:", mkt_live.get("sportLabel"), "| type:", mkt_live.get("marketType"))
print("Outcomes:", mkt_live.get("outcomeOneName"), "/", mkt_live.get("outcomeTwoName"))
print("GameTime:", mkt_live.get("gameTime"), "(", time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(mkt_live.get("gameTime"))), "UTC)")

    # Let's try placing a 1.00 USDC bet on SC Internacional at odds 1.90
    order = client.build_order_payload(
        market_hash=m_hash_live,
        total_bet_size_usdc=1.00,
        decimal_odds=1.90,
        is_betting_outcome_one=True,
    )
    sig = client.sign_order(order)
    print("Signed order:", order)
    print("Attempting dry_run=False placement on live match...")
    res = client.place_order(order, signature=sig, dry_run=False)
    print("Placement result:", res)
