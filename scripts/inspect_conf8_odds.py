import os
import sys

# Додаємо корінь проєкту до sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import psycopg2
from psycopg2.extras import RealDictCursor
from statmonitor.backtest import run_backtest

DB_URL = "postgresql://postgres.qmjeomovyoyogkjbgerr:ALTECsrs1989_@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"

def main():
    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, match_name, sport, odds, pick_label, status, shadow_status, is_shadow, confidence_score, walkaway_odds, profit_uah, kelly_pct, commence_time
        FROM paper_bets
        WHERE confidence_score >= 8
        ORDER BY odds ASC;
    """)
    rows = [dict(r) for r in cur.fetchall()]
    
    # Also fetch all rows for backtest
    cur.execute("SELECT * FROM paper_bets ORDER BY commence_time ASC;")
    all_bets = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    print(f"Total bets with confidence >= 8 in DB: {len(rows)}")
    settled = [r for r in rows if r['status'] in ('WON', 'LOST', 'VOID')]
    print(f"Settled bets with confidence >= 8: {len(settled)}")
    print("\n--- Listing of Settled Bets with Conf >= 8 by Odds ---")
    for r in settled:
        k = float(r['odds'])
        st = r['status']
        print(f"#{r['id']:<3} | k={k:<4.2f} | Conf={r['confidence_score']} | {st:<4} | {r['sport']:<25} | {r['match_name']} ({r['pick_label']})")

    # Now let's test a dense grid of odds ranges!
    # User specifically mentioned:
    # 1.5 - 2.8
    # 1.7 - 2.6
    # and other variations!
    # Let's test min_odds from 1.10 to 2.00, and max_odds from 2.00 to 5.00
    min_candidates = [1.10, 1.20, 1.30, 1.40, 1.50, 1.60, 1.70, 1.80, 1.85]
    max_candidates = [2.20, 2.40, 2.50, 2.60, 2.70, 2.80, 3.00, 3.20, 3.50, 4.00, 5.00, 10.00]

    grid_results = []
    for min_k in min_candidates:
        for max_k in max_candidates:
            if min_k >= max_k:
                continue
            cfg = {
                "initial_bankroll": 10000.0,
                "staking_model": "KELLY_FRACTION",
                "fraction": 0.10,
                "min_confidence": 8,
                "min_odds": min_k,
                "max_odds": max_k,
                "enforce_walkaway": False,
                "include_shadow": False
            }
            res = run_backtest(all_bets, cfg)
            m = res["metrics"]
            grid_results.append({
                "range": f"{min_k:.2f} - {max_k:.2f}",
                "min_odds": min_k,
                "max_odds": max_k,
                "trades": m["total_trades"],
                "won": m["won_count"],
                "lost": m["lost_count"],
                "void": m["void_count"],
                "wr": m["win_rate"],
                "profit": m["net_profit"],
                "roi": m["roi_pct"],
                "max_dd_pct": m["max_drawdown_pct"],
                "max_dd_uah": m["max_drawdown_uah"],
                "sharpe": m["sharpe_ratio"],
                "sortino": m["sortino_ratio"],
                "pf": m["profit_factor"],
                "final_bank": m["final_balance"]
            })

    # Sort by profit
    by_profit = sorted(grid_results, key=lambda x: (x["profit"], x["roi"]), reverse=True)
    # Sort by Sharpe (min 10 trades)
    by_sharpe = sorted([r for r in grid_results if r["trades"] >= 10], key=lambda x: x["sharpe"], reverse=True)

    print("\n" + "=" * 95)
    print("🏆 ТОП-15 ДІАПАЗОНІВ КОЕФІЦІЄНТІВ ЗА МАКСИМАЛЬНИМ ПРИБУТКОМ (Kelly 0.10x, Conf ≥ 8):")
    print("=" * 95)
    hdr = f"{'#':<3} | {'Діапазон коеф.':<16} | {'Ставок':<6} | {'W/L':<7} | {'Win Rate':<8} | {'Прибуток (₴)':<13} | {'ROI %':<8} | {'Max DD %':<8} | {'Sharpe':<6}"
    print(hdr)
    print("-" * 95)
    for i, r in enumerate(by_profit[:15], 1):
        wl = f"{r['won']}/{r['lost']}"
        line = f"{i:<3} | {r['range']:<16} | {r['trades']:<6} | {wl:<7} | {r['wr']:>6.1f}% | {r['profit']:>+11,.2f} ₴ | {r['roi']:>+6.2f}% | {r['max_dd_pct']:>6.1f}% | {r['sharpe']:>6.2f}"
        print(line)

    print("\n" + "=" * 95)
    print("🛡️ ТОП-10 НАЙБІЛЬШ ЗБАЛАНСОВАНИХ ДІАПАЗОНІВ ЗА SHARPE RATIO (Мін. 10 ставок):")
    print("=" * 95)
    print(hdr)
    print("-" * 95)
    for i, r in enumerate(by_sharpe[:10], 1):
        wl = f"{r['won']}/{r['lost']}"
        line = f"{i:<3} | {r['range']:<16} | {r['trades']:<6} | {wl:<7} | {r['wr']:>6.1f}% | {r['profit']:>+11,.2f} ₴ | {r['roi']:>+6.2f}% | {r['max_dd_pct']:>6.1f}% | {r['sharpe']:>6.2f}"
        print(line)

    # Let's specifically print user's highlighted ranges:
    print("\n" + "=" * 95)
    print("🎯 ТОЧКОВИЙ АНАЛІЗ ЗАПИТАНИХ КОРИСТУВАЧЕМ ДІАПАЗОНІВ:")
    print("=" * 95)
    specific_ranges = ["1.50 - 2.80", "1.70 - 2.60", "1.40 - 2.50", "1.50 - 2.50", "1.30 - 3.00", "1.10 - 10.00"]
    for s_rng in specific_ranges:
        match = next((r for r in grid_results if r["range"] == s_rng), None)
        if match:
            wl = f"{match['won']}/{match['lost']}"
            print(f"Діапазон {match['range']:<12}: Ставок: {match['trades']:<2} ({wl}) | WR: {match['wr']:>5.1f}% | Прибуток: {match['profit']:>+9,.2f} ₴ | ROI: {match['roi']:>+6.2f}% | Max DD: {match['max_dd_pct']:>4.1f}% | Sharpe: {match['sharpe']:>4.2f}")

if __name__ == "__main__":
    main()
