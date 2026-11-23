"""
StatMonitor - Quantitative Backtest Engine Grid Search (SPEC-42).
Runs 150+ backtest simulations on historical settled bets to find
the optimal capital management, filtering, and sizing strategy.
"""

import json
import os
import sys

# Додаємо корінь проєкту до sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import psycopg2
from psycopg2.extras import RealDictCursor
from statmonitor.backtest import run_backtest

DB_URL = "postgresql://postgres.qmjeomovyoyogkjbgerr:ALTECsrs1989_@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"

def fetch_historical_bets():
    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM paper_bets ORDER BY commence_time ASC;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

def generate_grid_configurations():
    configs = []
    
    # 1. Kelly Staking Variations across Confidence and Walkaway
    kelly_fractions = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
    conf_levels = [0, 6, 7, 8, 9]
    walkaways = [False, True]
    shadows = [False, True]
    
    # Grid A: Kelly fraction x Confidence (Walkaway=False, Shadow=False, All Sports, 10k bank)
    for frac in kelly_fractions:
        for conf in conf_levels:
            configs.append({
                "name": f"Kelly {frac:.2f}x | Conf ≥ {conf}",
                "initial_bankroll": 10000.0,
                "staking_model": "KELLY_FRACTION",
                "fraction": frac,
                "min_confidence": conf,
                "enforce_walkaway": False,
                "include_shadow": False,
                "min_odds": 1.10,
                "max_odds": 10.0
            })

    # Grid B: Kelly with Walkaway Odds enforcement
    for frac in [0.05, 0.10, 0.15, 0.20, 0.25, 0.35]:
        for conf in [0, 7, 8]:
            configs.append({
                "name": f"Kelly {frac:.2f}x | Conf ≥ {conf} | +Walkaway",
                "initial_bankroll": 10000.0,
                "staking_model": "KELLY_FRACTION",
                "fraction": frac,
                "min_confidence": conf,
                "enforce_walkaway": True,
                "include_shadow": False,
                "min_odds": 1.10,
                "max_odds": 10.0
            })

    # Grid C: Flat Staking Variations (amounts 30 to 500) x Confidence
    flat_amounts = [30.0, 50.0, 75.0, 100.0, 150.0, 200.0, 250.0, 300.0, 400.0, 500.0]
    for flat in flat_amounts:
        for conf in [0, 7, 8]:
            configs.append({
                "name": f"Flat {flat:,.0f} ₴ | Conf ≥ {conf}",
                "initial_bankroll": 10000.0,
                "staking_model": "FLAT",
                "flat_amount": flat,
                "min_confidence": conf,
                "enforce_walkaway": False,
                "include_shadow": False,
                "min_odds": 1.10,
                "max_odds": 10.0
            })

    # Grid D: Percent of Bankroll Variations (0.5% to 5.0%) x Confidence
    pct_banks = [0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05]
    for pct in pct_banks:
        for conf in [0, 7, 8]:
            configs.append({
                "name": f"% of Bank {pct*100:.1f}% | Conf ≥ {conf}",
                "initial_bankroll": 10000.0,
                "staking_model": "PERCENT_BANK",
                "percent_bank": pct,
                "min_confidence": conf,
                "enforce_walkaway": False,
                "include_shadow": False,
                "min_odds": 1.10,
                "max_odds": 10.0
            })

    # Grid E: Counterfactual No-AI (Shadow Bets Included)
    for model, param_name, param_val in [
        ("KELLY_FRACTION", "fraction", 0.05),
        ("KELLY_FRACTION", "fraction", 0.10),
        ("KELLY_FRACTION", "fraction", 0.20),
        ("KELLY_FRACTION", "fraction", 0.25),
        ("FLAT", "flat_amount", 100.0),
        ("FLAT", "flat_amount", 200.0),
        ("PERCENT_BANK", "percent_bank", 0.02),
        ("PERCENT_BANK", "percent_bank", 0.03),
    ]:
        cfg = {
            "name": f"Shadow/No-AI | {model} {param_val}",
            "initial_bankroll": 10000.0,
            "staking_model": model,
            "min_confidence": 0,
            "enforce_walkaway": False,
            "include_shadow": True,
            "min_odds": 1.10,
            "max_odds": 10.0
        }
        cfg[param_name] = param_val
        configs.append(cfg)

    # Grid F: Odds Range Restrictions (Favorites vs Mid-range vs Longshots)
    odds_ranges = [
        ("Favs (1.20-1.80)", 1.20, 1.80),
        ("Mid (1.40-2.50)", 1.40, 2.50),
        ("High (2.00-6.00)", 2.00, 6.00),
        ("Standard (1.25-3.50)", 1.25, 3.50),
    ]
    for label, min_k, max_k in odds_ranges:
        for frac in [0.10, 0.20]:
            configs.append({
                "name": f"Kelly {frac:.2f}x | {label} | Conf ≥ 7",
                "initial_bankroll": 10000.0,
                "staking_model": "KELLY_FRACTION",
                "fraction": frac,
                "min_confidence": 7,
                "min_odds": min_k,
                "max_odds": max_k,
                "enforce_walkaway": False,
                "include_shadow": False
            })

    # Grid G: Sport Specialization (Soccer vs Basketball vs Tennis)
    soccer_sports = [
        "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
        "soccer_germany_bundesliga", "soccer_france_ligue_one",
        "soccer_poland_ekstraklasa", "soccer_uefa_nations_league"
    ]
    sport_groups = [
        ("Soccer Only", soccer_sports),
        ("NBA Only", ["basketball_nba"]),
        ("Tennis Only", ["tennis_atp_finals", "tennis_wta_finals"]),
    ]
    for s_name, s_list in sport_groups:
        for model_choice in [
            ("Kelly 0.10x", "KELLY_FRACTION", {"fraction": 0.10}),
            ("Kelly 0.25x", "KELLY_FRACTION", {"fraction": 0.25}),
            ("Flat 100 ₴", "FLAT", {"flat_amount": 100.0}),
            ("% Bank 2.0%", "PERCENT_BANK", {"percent_bank": 0.02}),
        ]:
            cfg = {
                "name": f"{s_name} | {model_choice[0]} | Conf ≥ 7",
                "initial_bankroll": 10000.0,
                "staking_model": model_choice[1],
                "min_confidence": 7,
                "selected_sports": s_list,
                "enforce_walkaway": False,
                "include_shadow": False,
                "min_odds": 1.10,
                "max_odds": 10.0
            }
            cfg.update(model_choice[2])
            configs.append(cfg)

    # Grid H: Real Bank Deposit Sizing (3000 ₴ Starting Bank)
    for frac in [0.05, 0.10, 0.15, 0.20]:
        configs.append({
            "name": f"Real Bank (3000 ₴) | Kelly {frac:.2f}x | Conf ≥ 7",
            "initial_bankroll": 3000.0,
            "staking_model": "KELLY_FRACTION",
            "fraction": frac,
            "min_confidence": 7,
            "enforce_walkaway": False,
            "include_shadow": False,
            "min_odds": 1.10,
            "max_odds": 10.0
        })
    for flat in [50.0, 100.0, 150.0]:
        configs.append({
            "name": f"Real Bank (3000 ₴) | Flat {flat:.0f} ₴ | Conf ≥ 7",
            "initial_bankroll": 3000.0,
            "staking_model": "FLAT",
            "flat_amount": flat,
            "min_confidence": 7,
            "enforce_walkaway": False,
            "include_shadow": False,
            "min_odds": 1.10,
            "max_odds": 10.0
        })

    return configs

def main():
    print("=" * 70)
    print("🚀 Квантитативний Бектест та Симуляція (SPEC-42)")
    print("Завантаження історії розрахованих ставок із PostgreSQL...")
    print("=" * 70)
    
    bets = fetch_historical_bets()
    print(f"✅ Успішно завантажено {len(bets)} ставок із бази даних.")
    
    configs = generate_grid_configurations()
    total_tests = len(configs)
    print(f"📊 Сформовано {total_tests} тестових конфігурацій для Grid Search.")
    print("Запуск покрокової хронологічної симуляції капіталу...\n")
    
    results = []
    for idx, cfg in enumerate(configs, 1):
        res = run_backtest(bets, cfg)
        m = res["metrics"]
        results.append({
            "test_id": idx,
            "name": cfg.get("name", f"Test #{idx}"),
            "initial_bankroll": cfg.get("initial_bankroll", 10000.0),
            "staking_model": cfg.get("staking_model"),
            "min_confidence": cfg.get("min_confidence"),
            "enforce_walkaway": cfg.get("enforce_walkaway"),
            "include_shadow": cfg.get("include_shadow"),
            "min_odds": cfg.get("min_odds"),
            "max_odds": cfg.get("max_odds"),
            "selected_sports": cfg.get("selected_sports"),
            "total_trades": m["total_trades"],
            "won_count": m["won_count"],
            "lost_count": m["lost_count"],
            "void_count": m["void_count"],
            "win_rate": m["win_rate"],
            "final_balance": m["final_balance"],
            "net_profit": m["net_profit"],
            "cagr_pct": m["cagr_pct"],
            "roi_pct": m["roi_pct"],
            "total_turnover": m["total_turnover"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "max_drawdown_uah": m["max_drawdown_uah"],
            "profit_factor": m["profit_factor"],
            "sharpe_ratio": m["sharpe_ratio"],
            "sortino_ratio": m["sortino_ratio"],
            "max_win_streak": m["max_win_streak"],
            "max_loss_streak": m["max_loss_streak"],
            "avg_stake": m["avg_stake"],
            "avg_odds": m["avg_odds"],
            "skipped_count": m["skipped_count"]
        })

    # Збереження результатів у JSON
    os.makedirs("data", exist_ok=True)
    out_file = "data/backtest_grid_search_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 Результати {total_tests} тестів збережено у '{out_file}'.\n")

    # Сортування за чистим прибутком
    sorted_by_profit = sorted(results, key=lambda x: x["net_profit"], reverse=True)
    # Сортування за Sharpe ratio
    sorted_by_sharpe = sorted(
        [r for r in results if r["total_trades"] >= 20],
        key=lambda x: x["sharpe_ratio"],
        reverse=True
    )
    # Сортування за Profit Factor
    sorted_by_pf = sorted(
        [r for r in results if r["total_trades"] >= 20 and r["profit_factor"] < 50],
        key=lambda x: x["profit_factor"],
        reverse=True
    )

    print("=" * 95)
    print("🏆 ТОП-10 СТРАТЕГІЙ ЗА МАКСИМАЛЬНИМ ЧИСТИМ ПРИБУТКОМ (NET PROFIT):")
    print("=" * 95)
    header = f"{'#':<3} | {'Стратегія':<38} | {'Ставок':<6} | {'WR %':<6} | {'Прибуток (₴)':<14} | {'ROI %':<8} | {'Max DD %':<8} | {'Sharpe':<6}"
    print(header)
    print("-" * 95)
    for i, r in enumerate(sorted_by_profit[:10], 1):
        line = f"{i:<3} | {r['name']:<38} | {r['total_trades']:<6} | {r['win_rate']:>5.1f}% | {r['net_profit']:>+12,.2f} ₴ | {r['roi_pct']:>+6.2f}% | {r['max_drawdown_pct']:>6.1f}% | {r['sharpe_ratio']:>6.2f}"
        print(line)

    print("\n" + "=" * 95)
    print("🛡️ ТОП-10 НАЙБІЛЬШ ЗБАЛАНСОВАНИХ СТРАТЕГІЙ ЗА SHARPE RATIO (Мін. 20 ставок):")
    print("=" * 95)
    print(header)
    print("-" * 95)
    for i, r in enumerate(sorted_by_sharpe[:10], 1):
        line = f"{i:<3} | {r['name']:<38} | {r['total_trades']:<6} | {r['win_rate']:>5.1f}% | {r['net_profit']:>+12,.2f} ₴ | {r['roi_pct']:>+6.2f}% | {r['max_drawdown_pct']:>6.1f}% | {r['sharpe_ratio']:>6.2f}"
        print(line)

    print("\n" + "=" * 95)
    print("📉 НАЙГІРШІ СТРАТЕГІЇ (АНТИПАТЕРНИ / МАКСИМАЛЬНИЙ МІНУС ТА ПРОСІДАННЯ):")
    print("=" * 95)
    print(header)
    print("-" * 95)
    worst = sorted(results, key=lambda x: x["net_profit"])[:5]
    for i, r in enumerate(worst, 1):
        line = f"{i:<3} | {r['name']:<38} | {r['total_trades']:<6} | {r['win_rate']:>5.1f}% | {r['net_profit']:>+12,.2f} ₴ | {r['roi_pct']:>+6.2f}% | {r['max_drawdown_pct']:>6.1f}% | {r['sharpe_ratio']:>6.2f}"
        print(line)

if __name__ == "__main__":
    main()
