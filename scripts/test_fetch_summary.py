import os
import sys
sys.path.insert(0, os.path.abspath("."))
import psycopg2
from statmonitor.sx_bet import SXBetClient, fetch_sx_summary, fetch_sx_bets, fetch_sx_transactions, sync_sx_positions_to_db

if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

db_url = os.environ.get("SUPABASE_DB_URL")
if not db_url:
    print("No DB URL")
    exit(1)

conn = psycopg2.connect(db_url)
client = SXBetClient()

synced = sync_sx_positions_to_db(conn, client)
print(f"Synced {synced} positions from SX Bet API to DB!")

summary = fetch_sx_summary(conn, client)
print("SX Summary:", summary)
bets = fetch_sx_bets(conn)
print("SX Bets count:", len(bets))
if bets:
    print("First bet:", bets[0]["order_id"], bets[0]["event_name"], bets[0]["stake_usdc"], bets[0]["odds"], bets[0]["status"])
txs = fetch_sx_transactions(conn)
print("SX Transactions count:", len(txs))
if txs:
    print("First tx:", txs[0]["type"], txs[0]["amount_usdc"], txs[0]["created_at"])
conn.close()
