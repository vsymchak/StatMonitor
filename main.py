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
    API_KEY_RESERVE2,
    API_KEY_RESERVE3,
    ALL_ODDS_API_KEYS,
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
    generate_weekly_digest,
)

def run_pipeline(force=False):
    t_start = time.time()
    import os
    from datetime import datetime
    print("=" * 60)
    print("🚀 StatMonitor v3.4.1 [Smart 5-min Self-Scheduled Executor]")
    try:
        print(f"⏰ Час старту: {datetime.now(KYIV_TZ).strftime('%d.%m.%Y %H:%M:%S')} (Київ)")
    except Exception:
        pass
    print("=" * 60)

    trigger_src = "force" if force else os.environ.get("TRIGGER_SOURCE", "manual")

    # Глобальний однопоточний замок (pg_try_advisory_lock) проти гонки Render / GH Actions / Daemon
    lock_conn = None
    lock_cur = None
    has_advisory_lock = False
    try:
        lock_conn = get_db()
        if lock_conn is not None and hasattr(lock_conn, "server_version"):
            lock_cur = lock_conn.cursor()
            lock_cur.execute("SELECT pg_try_advisory_lock(hashtext('statmonitor_pipeline'));")
            locked_row = lock_cur.fetchone()
            if locked_row and locked_row[0] is False:
                print("⏸️ [Single-Flight] Інший процес пайплайну вже триває. Вихід без дублювання.")
                lock_cur.close()
                lock_conn.close()
                return
            has_advisory_lock = True
    except Exception as le:
        print(f"⚠️ Single-flight lock warning: {le}")

    try:
        # Розумний шлюз виконання (Smart 5-min Gate)
        if trigger_src.lower() in ("cron_5m", "schedule", "cron"):
            from scheduler import should_execute_pipeline
            conn_gate = get_db()
            if conn_gate:
                cur_gate = conn_gate.cursor()
                try:
                    should_run, reason, run_mode = should_execute_pipeline(cur_gate, conn_gate, trigger_source=trigger_src)
                    if not should_run:
                        print("💤 [Smart Gate] Пропуск виконання (0 витрат квоти The Odds API та Gemini).")
                        print(f"   Причина: {reason}")
                        print("=" * 60)
                        cur_gate.close()
                        conn_gate.close()
                        return
                    else:
                        print(f"⚡ [Smart Gate] Запуск дозволено! Режим: {run_mode}")
                        print(f"   Причина: {reason}")
                except Exception as ge:
                    print(f"⚠️ Помилка перевірки Smart Gate: {ge}. Продовжуємо виконання.")
                finally:
                    if not conn_gate.closed:
                        cur_gate.close()
                        conn_gate.close()

        s_map = get_sports_map()
        fetch_and_save_odds(s_map)
        check_alerts_and_notify(s_map, t_start=t_start)
    finally:
        if lock_conn is not None:
            try:
                if has_advisory_lock and lock_cur is not None and not lock_conn.closed:
                    lock_cur.execute("SELECT pg_advisory_unlock(hashtext('statmonitor_pipeline'));")
            except Exception:
                pass
            try:
                if lock_cur is not None:
                    lock_cur.close()
                if not lock_conn.closed:
                    lock_conn.close()
            except Exception:
                pass

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

def run_weekly_digest(db_url=None, force=True):
    """Формування та відправка щотижневого графічного дайджесту у Telegram."""
    print("📊 Запуск генерації щотижневого фінансового дайджесту (SPEC-26)...")
    conn = get_db(db_url=db_url)
    if not conn:
        print("❌ Помилка підключення до бази даних.")
        return
    cur = conn.cursor()
    ensure_tables(cur, conn)
    res = generate_weekly_digest(cur, conn, force=force, send_telegram=True)
    print(f"✅ Результат виконання: {res.get('status')}")
    if res.get("status") == "NO_BETS":
        print("ℹ️ Немає розрахованих ставок у базі для формування дайджесту.")
    else:
        print(f"   Тиждень: {res.get('week_key')}")
        m = res.get("metrics", {})
        print(f"   Прибуток: {m.get('net_profit')} грн | ROI: {m.get('roi_pct')}% | WinRate: {m.get('won')}/{m.get('total_bets')}")
        print(f"   Графік побудовано: {m.get('has_chart')}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--weekly-digest", "--digest", "-d"):
        custom_url = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else None
        run_weekly_digest(db_url=custom_url, force=True)
    elif len(sys.argv) > 1 and sys.argv[1] in ("--recalc-bets", "--recalc", "-r"):
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
    elif len(sys.argv) > 1 and sys.argv[1] in ("--force", "-f"):
        run_pipeline(force=True)
    else:
        run_pipeline()
