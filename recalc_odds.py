"""
CLI скрипт для перерахунку коефіцієнтів у вже розрахованих/активних ставках paper_bets
на основі реальної медіани ринку (Pinnacle, Betfair, Unibet, Marathonbet) з odds_history.
"""

import sys
from statmonitor.database import get_db, ensure_tables
from statmonitor.paper_trading import recalculate_historical_paper_bets, update_pending_bet_odds

def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--edit-odds", "--edit-bet", "-e"):
        if len(sys.argv) < 4:
            print("Використання: python recalc_odds.py --edit-odds <ID_ставки> <новий_коефіцієнт> [DB_URL]")
            sys.exit(1)
        try:
            b_id = int(sys.argv[2])
            n_k = float(sys.argv[3])
        except ValueError:
            print("❌ ID ставки має бути цілим числом, а коефіцієнт — числом.")
            sys.exit(1)
        db_url = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("-") else None
        conn = get_db(db_url=db_url)
        if not conn:
            print("❌ Помилка підключення до бази даних.")
            sys.exit(1)
        cur = conn.cursor()
        ensure_tables(cur, conn)
        ok, msg, _ = update_pending_bet_odds(cur, conn, b_id, n_k)
        if ok:
            print(f"✅ {msg}")
        else:
            print(f"❌ {msg}")
        cur.close()
        conn.close()
        return

    print("🔄 Запуск перевірки та перерахунку коефіцієнтів у paper_bets...")
    db_url = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        db_url = sys.argv[1]

    conn = get_db(db_url=db_url)
    if not conn:
        print("❌ Помилка підключення до бази даних.")
        print("   Встановіть змінну середовища SUPABASE_DB_URL або передайте рядок підключення аргументом:")
        print("   python recalc_odds.py \"postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres\"")
        sys.exit(1)

    cur = conn.cursor()
    ensure_tables(cur, conn)
    updated = recalculate_historical_paper_bets(cur, conn)
    print(f"✅ Перевірку завершено. Оновлено {len(updated)} ставок до реальних ринкових коефіцієнтів:")
    for u in updated:
        print(f"  • [{u['id']}] {u['match_name']} | {u['pick_label']}: {u['old_odds']} ➔ {u['new_odds']} (Статус: {u['status']}, Профіт: {u['old_profit']} ➔ {u['new_profit']} грн)")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
