"""
StatMonitor - Real Bankroll Management (SPEC-31: Wave 10).
Облік реальних грошей, депозитів, виведень та зв'язку з реальними ставками в БК.
"""

from decimal import Decimal

def ensure_real_bankroll_tables(cur, conn):
    """Створює необхідні таблиці та колонки для режиму гри на реальні гроші."""
    cur.execute("""
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS is_real_bet BOOLEAN DEFAULT FALSE;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_stake_uah NUMERIC(10, 2);
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_odds NUMERIC(6, 3);
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS bookmaker_name TEXT;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS slip_image_path TEXT;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS slip_meta JSONB;

        CREATE TABLE IF NOT EXISTS real_bankroll_ledger (
            id SERIAL PRIMARY KEY,
            transaction_type TEXT NOT NULL,
            amount_uah NUMERIC(10, 2) NOT NULL,
            balance_after_uah NUMERIC(10, 2) NOT NULL,
            bet_id INTEGER REFERENCES paper_bets(id) ON DELETE SET NULL,
            description TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_paper_bets_is_real ON paper_bets (is_real_bet);
        CREATE INDEX IF NOT EXISTS idx_real_bankroll_created ON real_bankroll_ledger (created_at DESC);

        DELETE FROM real_bankroll_ledger 
        WHERE transaction_type = 'INITIAL' AND description = 'Початковий реальний банк';
    """)
    conn.commit()


def get_real_bankroll_summary(cur, conn=None):
    """
    Повертає зведення стану реального банку:
    - current_balance: актуальний баланс з леджера (формується депозитами)
    - initial_bank: сума внесених депозитів
    - total_real_bets: кількість відмічених реальних ставок
    - real_profit: чистий прибуток на реальних ставках
    - real_turnover: реальний оборот коштів
    - real_roi_pct: окупність реальних ставок
    - real_win_rate: відсоток перемог реальних ставок
    """
    summary = {
        "current_balance": 0.0,
        "initial_bank": 0.0,
        "total_real_bets": 0,
        "pending_real": 0,
        "won_real": 0,
        "lost_real": 0,
        "void_real": 0,
        "real_turnover": 0.0,
        "real_profit": 0.0,
        "real_roi_pct": 0.0,
        "real_win_rate": 0.0,
        "total_deposits": 0.0,
        "total_withdrawals": 0.0,
    }

    try:
        # 1. Поточний баланс з леджера
        cur.execute("SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1;")
        row_b = cur.fetchone()
        if row_b and row_b[0] is not None:
            summary["current_balance"] = float(row_b[0])

        # 2. Сума депозитів та виведень (банк формується депозитами)
        cur.execute("""
            SELECT 
                COALESCE(SUM(amount_uah) FILTER (WHERE transaction_type = 'DEPOSIT'), 0),
                COALESCE(SUM(amount_uah) FILTER (WHERE transaction_type = 'WITHDRAWAL'), 0)
            FROM real_bankroll_ledger;
        """)
        row_dep = cur.fetchone()
        if row_dep:
            summary["total_deposits"] = float(row_dep[0] or 0.0)
            summary["total_withdrawals"] = abs(float(row_dep[1] or 0.0))
            summary["initial_bank"] = summary["total_deposits"]

        # 3. Статистика ставок paper_bets WHERE is_real_bet = TRUE
        cur.execute("""
            SELECT 
                COUNT(*),
                COUNT(*) FILTER (WHERE status = 'PENDING'),
                COUNT(*) FILTER (WHERE status = 'WON'),
                COUNT(*) FILTER (WHERE status = 'LOST'),
                COUNT(*) FILTER (WHERE status = 'VOID'),
                COALESCE(SUM(COALESCE(real_stake_uah, stake_uah)) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0),
                COALESCE(SUM(profit_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0)
            FROM paper_bets
            WHERE is_real_bet = TRUE;
        """)
        row_bets = cur.fetchone()
        if row_bets:
            summary["total_real_bets"] = int(row_bets[0] or 0)
            summary["pending_real"] = int(row_bets[1] or 0)
            summary["won_real"] = int(row_bets[2] or 0)
            summary["lost_real"] = int(row_bets[3] or 0)
            summary["void_real"] = int(row_bets[4] or 0)
            summary["real_turnover"] = float(row_bets[5] or 0.0)
            summary["real_profit"] = float(row_bets[6] or 0.0)

            if summary["real_turnover"] > 0:
                summary["real_roi_pct"] = round((summary["real_profit"] / summary["real_turnover"]) * 100.0, 2)

            settled_cnt = summary["won_real"] + summary["lost_real"]
            if settled_cnt > 0:
                summary["real_win_rate"] = round((summary["won_real"] / settled_cnt) * 100.0, 1)

    except Exception as e:
        print(f"Помилка отримання зведення реального банку: {e}")

    return summary


def record_real_transaction(cur, conn, tx_type, amount, description="", bet_id=None):
    """
    Записує фінансову транзакцію в журнал реального банку:
    - tx_type: 'INITIAL', 'DEPOSIT', 'WITHDRAWAL', 'BET_RESULT', 'ADJUSTMENT'
    - amount: сума транзакції (позитивна або від'ємна)
    """
    try:
        cur.execute("SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1;")
        row_last = cur.fetchone()
        current_b = float(row_last[0]) if (row_last and row_last[0] is not None) else 0.0

        amt = float(amount)
        tx_type_upper = str(tx_type).upper()

        if tx_type_upper == "DEPOSIT":
            new_balance = round(current_b + abs(amt), 2)
            amt_signed = abs(amt)
        elif tx_type_upper == "WITHDRAWAL":
            new_balance = round(max(0.0, current_b - abs(amt)), 2)
            amt_signed = -abs(amt)
        elif tx_type_upper == "BET_RESULT":
            new_balance = round(current_b + amt, 2)
            amt_signed = amt
        elif tx_type_upper in ("INITIAL", "ADJUSTMENT"):
            new_balance = round(amt, 2)
            amt_signed = amt
        else:
            new_balance = round(current_b + amt, 2)
            amt_signed = amt

        cur.execute("""
            INSERT INTO real_bankroll_ledger (transaction_type, amount_uah, balance_after_uah, bet_id, description)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
        """, (tx_type_upper, amt_signed, new_balance, bet_id, description))
        conn.commit()
        return True, new_balance, f"Транзакцію [{tx_type_upper}] на суму {amt_signed:+.2f} ₴ успішно збережено. Новий баланс: {new_balance:,.2f} ₴."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, 0.0, f"Помилка запису транзакції: {e}"


def toggle_real_bet(cur, conn, bet_id, is_real=True, real_stake=None, real_odds=None, bookmaker=None, slip_meta=None):
    """
    Позначає ставку як реальну або повертає її у віртуальний Paper режим.
    Може додатково оновити фактичні коефіцієнт та суму з купона БК.
    """
    try:
        cur.execute("SELECT id, match_name, odds, stake_uah FROM paper_bets WHERE id = %s;", (bet_id,))
        row = cur.fetchone()
        if not row:
            return False, f"Ставку #{bet_id} не знайдено."

        bid, m_name, orig_odds, orig_stake = row

        updates = ["is_real_bet = %s"]
        params = [bool(is_real)]

        if is_real:
            if real_stake is not None and float(real_stake) > 0:
                updates.append("real_stake_uah = %s")
                params.append(float(real_stake))
            else:
                updates.append("real_stake_uah = COALESCE(real_stake_uah, %s)")
                params.append(float(orig_stake or 0.0))

            if real_odds is not None and float(real_odds) > 1.0:
                updates.append("real_odds = %s")
                params.append(float(real_odds))
            else:
                updates.append("real_odds = COALESCE(real_odds, %s)")
                params.append(float(orig_odds or 0.0))
        else:
            # При знятті відмітки ставка залишається віртуальною (Paper)
            pass

        if bookmaker:
            updates.append("bookmaker_name = %s")
            params.append(str(bookmaker))

        if slip_meta:
            import json
            updates.append("slip_meta = %s::jsonb")
            params.append(json.dumps(slip_meta) if isinstance(slip_meta, dict) else str(slip_meta))

        params.append(bet_id)
        sql = f"UPDATE paper_bets SET {', '.join(updates)} WHERE id = %s;"
        cur.execute(sql, tuple(params))
        conn.commit()

        status_str = "🟢 Реальна ставка (Real Money)" if is_real else "⚪ Віртуальна ставка (Paper)"
        return True, f"Ставку #{bid} ({m_name}) успішно оновлено як {status_str}."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Помилка оновлення статусу ставки: {e}"


def settle_real_bet_in_ledger(cur, conn, bet_id, status, profit_uah, stake_uah=None):
    """
    При розрахунку ставки, якщо вона позначена як is_real_bet,
    фіксує результат у real_bankroll_ledger (захист від повторних записів).
    """
    try:
        cur.execute("SELECT is_real_bet, match_name FROM paper_bets WHERE id = %s;", (bet_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return False, "Ставка не є реальною."

        m_name = row[1]
        # Перевіряємо, чи вже був запис у леджері для цієї ставки
        cur.execute("SELECT 1 FROM real_bankroll_ledger WHERE bet_id = %s AND transaction_type = 'BET_RESULT';", (bet_id,))
        if cur.fetchone():
            return False, f"Результат ставки #{bet_id} вже зафіксовано в леджері."

        p_val = float(profit_uah or 0.0)
        desc = f"Результат ставки #{bet_id} ({m_name}): {status} ({p_val:+.2f} ₴)"
        ok, _, msg = record_real_transaction(cur, conn, "BET_RESULT", p_val, description=desc, bet_id=bet_id)
        return ok, msg
    except Exception as e:
        return False, f"Помилка фіксації результату ставки в леджері: {e}"
