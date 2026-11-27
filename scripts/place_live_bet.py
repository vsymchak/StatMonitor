"""Допоміжний CLI-скрипт для тестового або ручного розміщення ордера на SX Bet."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from statmonitor.config import _load_env_file
from statmonitor.sx_bet import SXBetClient


def main():
    _load_env_file()
    parser = argparse.ArgumentParser(description="Place or dry-run a single SX Bet order")
    parser.add_argument("--market-hash", required=True, help="SX Bet marketHash")
    parser.add_argument("--stake", type=float, default=1.00, help="Stake in USDC (default 1.00)")
    parser.add_argument("--odds", type=float, default=1.90, help="Decimal odds (default 1.90)")
    parser.add_argument("--outcome-one", action="store_true", default=True, help="Bet on outcomeOne")
    parser.add_argument("--live", action="store_true", help="Execute real order (dry_run=False)")
    args = parser.parse_args()

    client = SXBetClient()
    markets = client.get_markets_by_hashes([args.market_hash])
    mkt_live = markets.get(args.market_hash)
    if not mkt_live:
        print(f"Market {args.market_hash} not found.")
        sys.exit(1)

    gt = mkt_live.get("gameTime")
    gt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(gt)) if gt else "N/A"
    print(
        f"Market {args.market_hash}: {mkt_live.get('teamOneName')} vs {mkt_live.get('teamTwoName')} | "
        f"sport: {mkt_live.get('sportLabel')} | type: {mkt_live.get('marketType')} | {gt_str} UTC"
    )
    print("Outcomes:", mkt_live.get("outcomeOneName"), "/", mkt_live.get("outcomeTwoName"))

    order = client.build_order_payload(
        market_hash=args.market_hash,
        total_bet_size_usdc=args.stake,
        decimal_odds=args.odds,
        is_betting_outcome_one=args.outcome_one,
    )
    sig = client.sign_order(order)
    res = client.place_order(order, signature=sig, dry_run=not args.live)
    print("Placement result:", res)


if __name__ == "__main__":
    main()
