"""
CLI скрипт для перерахунку коефіцієнтів у вже розрахованих/активних ставках paper_bets
на основі реальної медіани ринку (Pinnacle, Betfair, Unibet, Marathonbet) з odds_history.
"""

import sys
from statmonitor.database import get_db, ensure_tables
from statmonitor.paper_trading import recalculate_historical_paper_bets

def main():
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
