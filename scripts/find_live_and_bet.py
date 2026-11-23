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
print("Base URL:", client.base_url)
print("Wallet Address:", client.wallet_address)

# Check active markets
markets = client.get_active_markets()
print(f"Total active markets: {len(markets)}")
now_ts = int(time.time())
print(f"Current timestamp: {now_ts} ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now_ts))} UTC)")

# Also check if SX Bet has a specific live endpoint or parameter
# Let's check GET /markets/active?onlyLive=true or similar
r_live = requests.get(f"{client.base_url}/markets/active", headers=client.headers, params={"onlyLive": "true"})
print("GET /markets/active?onlyLive=true status:", r_live.status_code)
if r_live.status_code == 200:
    live_mkts = r_live.json().get("data", {}).get("markets", [])
    print(f"Markets with onlyLive=true: {len(live_mkts)}")
    for lm in live_mkts[:5]:
        print("  LIVE:", lm.get("teamOneName"), "vs", lm.get("teamTwoName"), "| gameTime:", lm.get("gameTime"), "| sport:", lm.get("sportLabel"))

# Look for in-play events in all active markets
in_play = []
for m in markets:
    gt = m.get("gameTime", 0)
    # If the game has already started and started within last 3 hours (10800 sec)
    if gt and (0 < (now_ts - gt) < 14400):
        in_play.append(m)

print(f"\nMarkets started in the last 4 hours (currently in-play): {len(in_play)}")
for m in in_play[:10]:
    print("  IN-PLAY:", m.get("teamOneName"), "vs", m.get("teamTwoName"), "| started", (now_ts - m.get("gameTime")) // 60, "mins ago | hash:", m.get("marketHash"))

# Let's check sports available
r_sports = requests.get(f"{client.base_url}/sports", headers=client.headers)
print("GET /sports code:", r_sports.status_code)
if r_sports.status_code == 200:
    sports_data = r_sports.json().get("data", [])
    print(f"Total sports: {len(sports_data)}")
    for s in sports_data:
        print("  Sport:", s.get("sportId"), s.get("label"))

# Fetch markets with onlyMainLine=true and paginate using paginationKey
all_markets = []
next_key = None

for page in range(10):  # fetch up to 10 pages
    params = {"onlyMainLine": "true"}
    if next_key:
        params["paginationKey"] = next_key
    r = requests.get(f"{client.base_url}/markets/active", headers=client.headers, params=params)
    if r.status_code != 200:
        print(f"Page {page} error: {r.status_code}")
        break
    data = r.json().get("data", {})
    mkts = data.get("markets", [])
    all_markets.extend(mkts)
    next_key = data.get("nextKey")
    print(f"Page {page}: got {len(mkts)} markets, nextKey={bool(next_key)}")
    if not next_key:
        break

print(f"\nTotal main-line markets fetched: {len(all_markets)}")
now_ts = int(time.time())
print(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now_ts))} UTC (timestamp: {now_ts})")

matches = {}
for m in all_markets:
    ev = f"{m.get('teamOneName')} vs {m.get('teamTwoName')}"
    if ev not in matches:
        matches[ev] = {"sport": m.get("sportLabel"), "gameTime": m.get("gameTime"), "markets": []}
    matches[ev]["markets"].append(m)

# Check which active markets actually have orders in the book or are live
print("\n--- Scanning for active markets with resting orders (liquidity) or live games ---")

# Let's check matches starting within +/- 2 hours from now
candidates = []
for m in all_markets:
    gt = m.get("gameTime", 0)
    if gt and abs(gt - now_ts) < 7200:  # within 2 hours of right now (past 2 hours or next 2 hours)
        candidates.append(m)

print(f"Candidates within 2 hours of now: {len(candidates)}")
for c in candidates[:15]:
    m_hash = c.get("marketHash")
    r_book = requests.get(f"{client.base_url}/orders-v3", headers=client.headers, params={"marketHash": m_hash})
    num_orders = 0
    best_maker = "None"
    if r_book.status_code == 200:
        orders = r_book.json().get("data", {}).get("orders", [])
        num_orders = len(orders)
        if orders:
            o0 = orders[0]
            pct = int(o0.get("percentageOdds", 0)) / 1e20
            k = round(1.0 / pct, 2) if pct > 0 else 0
            best_maker = f"{k} ({pct*100:.1f}%) ${int(o0.get('totalBetSize',0))/1e6:.2f}"
    gt = c.get("gameTime", 0)
    diff_m = (gt - now_ts) // 60 if gt else 0
    print(f"  [{c.get('sportLabel')}] {c.get('teamOneName')} vs {c.get('teamTwoName')} | {c.get('outcomeOneName')} | in {diff_m}m | Orders: {num_orders} | Best: {best_maker} | Hash: {m_hash}")

