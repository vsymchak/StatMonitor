"""
StatMonitor - Головний оркестратор виконання (SPEC-13 Modular Decomposition & SPEC-18 Accurate Market Odds).
"""

import sys
import time
from statmonitor import (
    INITIAL_BANKROLL,
    KYIV_TZ,
    SPORTS_MAP,
    TARGET_SPORTS,
    API_KEY,
    API_KEY_RESERVE,
    API_KEY_RESERVE1,
    SUPABASE_DB_URL,
    TG_BOT_TOKEN,
    TG_CHAT_ID,
    GEMINI_API_KEY,
    get_db,
    get_cols,
    pick,
    pick_v,
    ensure_tables,
    send_tg,
    send_photo,
    esc,
    fmt_kyiv,
    get_sports_map,
    check_odds_api_quota,
    fetch_and_save_odds,
    build_chart,
    analyze_gemini,
    extract_short_pick,
    format_pick,
    place_paper_bet,
    eval_outcome,
    settle_and_report,
    check_alerts_and_notify,
    parse_pick_label,
    resolve_alert_from_history,
    get_market_median_odds,
    recalculate_historical_paper_bets,
    update_pending_bet_odds,
)

def run_pipeline():
    t_start = time.time()
    from datetime import datetime
    print("=" * 60)
    print("🚀 StatMonitor v3.4.1 [Safe match_name + Cloudflare Edge Cron]")
    try:
        print(f"⏰ Час старту: {datetime.now(KYIV_TZ).strftime('%d.%m.%Y %H:%M:%S')} (Київ)")
    except Exception:
        pass
    print("=" * 60)
    s_map = get_sports_map()
    fetch_and_save_odds(s_map)
    check_alerts_and_notify(s_map, t_start=t_start)

def run_recalc(db_url=None):
    """Перерахунок коефіцієнтів у вже розрахованих та активних ставках paper_bets."""
    print("🔄 Запуск перевірки та перерахунку коефіцієнтів у paper_bets...")
    conn = get_db(db_url=db_url)
    if not conn:
        print("❌ Помилка підключення до бази даних.")
        print("   Встановіть змінну середовища SUPABASE_DB_URL або передайте рядок підключення аргументом:")
        print("   python main.py --recalc-bets \"postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres\"")
        return
    cur = conn.cursor()
    ensure_tables(cur, conn)
    updated = recalculate_historical_paper_bets(cur, conn)
    print(f"✅ Перевірку завершено. Оновлено {len(updated)} ставок до реальних ринкових коефіцієнтів.")
    for u in updated:
        print(f"  • [{u['id']}] {u['match_name']} | {u['pick_label']}: {u['old_odds']} ➔ {u['new_odds']} (Статус: {u['status']}, Профіт: {u['old_profit']} ➔ {u['new_profit']} грн)")
    cur.close()
    conn.close()

def run_edit_odds(bet_id, new_odds, db_url=None):
    """Оновлення коефіцієнта для нерозрахованої ставки."""
    conn = get_db(db_url=db_url)
    if not conn:
        print("❌ Помилка підключення до бази даних.")
        return
    cur = conn.cursor()
    ensure_tables(cur, conn)
    ok, msg, old_k = update_pending_bet_odds(cur, conn, bet_id, new_odds)
    if ok:
        print(f"✅ {msg}")
    else:
        print(f"❌ {msg}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--recalc-bets", "--recalc", "-r"):
        custom_url = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else None
        run_recalc(db_url=custom_url)
    elif len(sys.argv) > 1 and sys.argv[1] in ("--edit-odds", "--edit-bet", "-e"):
        if len(sys.argv) < 4:
            print("Використання: python main.py --edit-odds <ID_ставки> <новий_коефіцієнт> [DB_URL]")
            sys.exit(1)
        try:
            b_id = int(sys.argv[2])
            n_k = float(sys.argv[3])
        except ValueError:
            print("❌ ID ставки має бути цілим числом, а коефіцієнт — числом.")
            sys.exit(1)
        custom_url = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("-") else None
        run_edit_odds(b_id, n_k, db_url=custom_url)
    else:
        run_pipeline()
