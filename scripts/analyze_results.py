import json
import os

with open("data/backtest_grid_search_results.json", "r", encoding="utf-8") as f:
    results = json.load(f)

print(f"Total tests in dataset: {len(results)}")

# 1. Best Kelly configurations
kellys = [r for r in results if r["staking_model"] == "KELLY_FRACTION" and r["initial_bankroll"] == 10000.0 and not r.get("selected_sports") and not r.get("enforce_walkaway") and not r.get("include_shadow")]
kellys_sorted = sorted(kellys, key=lambda x: x["net_profit"], reverse=True)
print("\n=== TOP-5 KELLY STRATEGIES (10,000 ₴ BANK) ===")
for r in kellys_sorted[:5]:
    p = r["net_profit"]
    roi = r["roi_pct"]
    wr = r["win_rate"]
    dd = r["max_drawdown_pct"]
    sh = r["sharpe_ratio"]
    tr = r["total_trades"]
    print(f"{r['name']}: Profit = {p:+,.2f} UAH | ROI = {roi:+.2f}% | WR = {wr:.1f}% | Max DD = {dd:.1f}% | Sharpe = {sh:.2f} | Trades = {tr}")

# 2. Best Flat configurations
flats = [r for r in results if r["staking_model"] == "FLAT" and r["initial_bankroll"] == 10000.0 and not r.get("selected_sports") and not r.get("enforce_walkaway") and not r.get("include_shadow")]
flats_sorted = sorted(flats, key=lambda x: x["net_profit"], reverse=True)
print("\n=== TOP-5 FLAT STRATEGIES (10,000 ₴ BANK) ===")
for r in flats_sorted[:5]:
    p = r["net_profit"]
    roi = r["roi_pct"]
    wr = r["win_rate"]
    dd = r["max_drawdown_pct"]
    sh = r["sharpe_ratio"]
    tr = r["total_trades"]
    print(f"{r['name']}: Profit = {p:+,.2f} UAH | ROI = {roi:+.2f}% | WR = {wr:.1f}% | Max DD = {dd:.1f}% | Sharpe = {sh:.2f} | Trades = {tr}")

# 3. Best % of Bank configurations
pcts = [r for r in results if r["staking_model"] == "PERCENT_BANK" and r["initial_bankroll"] == 10000.0 and not r.get("selected_sports") and not r.get("enforce_walkaway") and not r.get("include_shadow")]
pcts_sorted = sorted(pcts, key=lambda x: x["net_profit"], reverse=True)
print("\n=== TOP-5 % OF BANK STRATEGIES (10,000 ₴ BANK) ===")
for r in pcts_sorted[:5]:
    p = r["net_profit"]
    roi = r["roi_pct"]
    wr = r["win_rate"]
    dd = r["max_drawdown_pct"]
    sh = r["sharpe_ratio"]
    tr = r["total_trades"]
    print(f"{r['name']}: Profit = {p:+,.2f} UAH | ROI = {roi:+.2f}% | WR = {wr:.1f}% | Max DD = {dd:.1f}% | Sharpe = {sh:.2f} | Trades = {tr}")

# 4. Confidence filter impact (holding model constant: Flat 100 ₴, Kelly 0.10x, % Bank 2.0%)
print("\n=== IMPACT OF AI CONFIDENCE (Holding Sizing Constant) ===")
for m_name, filter_fn in [
    ("Flat 100 ₴", lambda r: r["staking_model"] == "FLAT" and "100" in r["name"] and not r.get("enforce_walkaway") and not r.get("include_shadow") and not r.get("selected_sports")),
    ("Kelly 0.10x", lambda r: r["staking_model"] == "KELLY_FRACTION" and "0.10x" in r["name"] and not r.get("enforce_walkaway") and not r.get("include_shadow") and not r.get("selected_sports")),
    ("% Bank 2.0%", lambda r: r["staking_model"] == "PERCENT_BANK" and "2.0%" in r["name"] and not r.get("enforce_walkaway") and not r.get("include_shadow") and not r.get("selected_sports")),
]:
    print(f"\n{m_name}:")
    sub = [r for r in results if filter_fn(r)]
    sub = sorted(sub, key=lambda x: x["min_confidence"])
    for r in sub:
        p = r["net_profit"]
        roi = r["roi_pct"]
        wr = r["win_rate"]
        dd = r["max_drawdown_pct"]
        tr = r["total_trades"]
        print(f"  Conf >= {r['min_confidence']}: Profit = {p:+,.2f} UAH | WR = {wr:.1f}% | ROI = {roi:+.2f}% | Max DD = {dd:.1f}% | Trades = {tr}")

# 5. Sports comparison (Soccer vs NBA vs Tennis)
print("\n=== SPORTS BREAKDOWN (Conf >= 7, 10k bank) ===")
sports_res = [r for r in results if r.get("selected_sports") and r.get("min_confidence") == 7]
for r in sports_res:
    p = r["net_profit"]
    roi = r["roi_pct"]
    wr = r["win_rate"]
    tr = r["total_trades"]
    dd = r["max_drawdown_pct"]
    print(f"{r['name']}: Profit = {p:+,.2f} UAH | ROI = {roi:+.2f}% | WR = {wr:.1f}% | Max DD = {dd:.1f}% | Trades = {tr}")

# 6. Walkaway Odds Impact
print("\n=== WALKAWAY ODDS IMPACT (True vs False) ===")
for frac in [0.05, 0.10, 0.20]:
    for conf in [7, 8]:
        pair = [r for r in results if r["staking_model"] == "KELLY_FRACTION" and f"{frac:.2f}x" in r["name"] and r.get("min_confidence") == conf and not r.get("selected_sports") and not r.get("include_shadow")]
        w_off = next((r for r in pair if not r.get("enforce_walkaway")), None)
        w_on = next((r for r in pair if r.get("enforce_walkaway")), None)
        if w_off and w_on:
            print(f"Kelly {frac:.2f}x Conf>={conf}:")
            print(f"  - Без Walkaway: {w_off['net_profit']:+,.2f} UAH | ROI: {w_off['roi_pct']}% | Max DD: {w_off['max_drawdown_pct']}% | Ставок: {w_off['total_trades']}")
            print(f"  - З Walkaway:   {w_on['net_profit']:+,.2f} UAH | ROI: {w_on['roi_pct']}% | Max DD: {w_on['max_drawdown_pct']}% | Ставок: {w_on['total_trades']}")

# 7. Real Bank (3000 UAH Starting)
print("\n=== REAL BANK CONFIGURATIONS (3000 UAH Starting Bank) ===")
real_b = [r for r in results if r.get("initial_bankroll") == 3000.0]
for r in sorted(real_b, key=lambda x: x["net_profit"], reverse=True):
    p = r["net_profit"]
    roi = r["roi_pct"]
    wr = r["win_rate"]
    dd = r["max_drawdown_pct"]
    sh = r["sharpe_ratio"]
    tr = r["total_trades"]
    print(f"{r['name']}: Profit = {p:+,.2f} UAH | ROI = {roi:+.2f}% | WR = {wr:.1f}% | Max DD = {dd:.1f}% | Sharpe = {sh:.2f} | Trades = {tr}")
