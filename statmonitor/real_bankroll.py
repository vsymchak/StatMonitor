"""
StatMonitor - Real Bankroll Management (SPEC-31: Wave 10).
Облік реальних грошей, депозитів, виведень та зв'язку з реальними ставками в БК.
"""

from decimal import Decimal
from datetime import datetime, timezone
from statmonitor.config import KYIV_TZ

def ensure_real_bankroll_tables(cur, conn):
    """Створює необхідні таблиці та колонки для режиму гри на реальні гроші."""
    cur.execute("""
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS is_real_bet BOOLEAN DEFAULT FALSE;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_stake_uah NUMERIC(10, 2);
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_odds NUMERIC(6, 3);
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS bookmaker_name TEXT;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS slip_image_path TEXT;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS slip_meta JSONB;
        ALTER TABLE paper_bets ADD COLUMN IF NOT EXISTS real_profit_uah NUMERIC(10, 2);

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
        # 1. Поточний баланс з леджера та агрегатна звірка сум (SPEC-38)
        cur.execute("""
            SELECT 
                (SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1),
                COALESCE(SUM(amount_uah), 0)
            FROM real_bankroll_ledger;
        """)
        row_b = cur.fetchone()
        if row_b and row_b[0] is not None:
            last_bal = float(row_b[0])
            sum_bal = float(row_b[1]) if (len(row_b) > 1 and row_b[1] is not None) else last_bal
            # У разі розбіжності між окремим полем і сумою леджера віддаємо перевагу математичній сумі
            summary["current_balance"] = round(sum_bal if abs(sum_bal - last_bal) > 0.01 and sum_bal > 0 else last_bal, 2)
            summary["ledger_sum"] = round(sum_bal, 2)

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
                COALESCE(SUM(COALESCE(real_profit_uah, profit_uah)) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0)
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


def record_real_transaction(cur, conn, tx_type, amount, description="", bet_id=None, is_delta=False):
    """
    Записує фінансову транзакцію в журнал реального банку з гарантією атомарності (SPEC-38):
    - tx_type: 'INITIAL', 'DEPOSIT', 'WITHDRAWAL', 'BET_RESULT', 'ADJUSTMENT'
    - amount: сума транзакції (позитивна або від'ємна)
    - is_delta: чи є сума дельтою (+/- до балансу) при коригуванні ADJUSTMENT
    - Гарантує SUM(amount_uah) == balance_after_uah для будь-якої транзакції.
    """
    try:
        cur.execute("SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1;")
        row_last = cur.fetchone()
        current_b = float(row_last[0]) if (row_last and row_last[0] is not None) else 0.0

        amt = float(amount)
        tx_type_upper = str(tx_type).upper()

        if tx_type_upper == "DEPOSIT":
            amt_signed = abs(amt)
            new_balance = round(current_b + amt_signed, 2)
        elif tx_type_upper == "WITHDRAWAL":
            amt_signed = -abs(amt)
            new_balance = round(max(0.0, current_b - abs(amt)), 2)
        elif tx_type_upper == "BET_RESULT":
            amt_signed = amt
            new_balance = round(current_b + amt, 2)
        elif tx_type_upper == "ADJUSTMENT":
            if is_delta or amt < 0:
                new_balance = round(max(0.0, current_b + amt), 2)
                amt_signed = round(new_balance - current_b, 2)
            else:
                new_balance = round(amt, 2)
                amt_signed = round(new_balance - current_b, 2)
        elif tx_type_upper == "INITIAL":
            new_balance = round(amt, 2)
            amt_signed = amt
        else:
            amt_signed = amt
            new_balance = round(current_b + amt, 2)

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


def toggle_real_bet(cur, conn, bet_id, is_real=True, real_stake=None, real_odds=None, bookmaker=None, slip_meta=None, enforce_single_active=False):
    """
    Позначає ставку як реальну або повертає її у віртуальний Paper режим.
    Може додатково оновити фактичні коефіцієнт та суму з купона БК.
    Якщо ставка переноситься в Реальний банк (is_real=True) і сума (real_stake) не задана вручну,
    вона автоматично розраховується від АКТУАЛЬНОГО БАЛАНСУ РЕАЛЬНОГО БАНКУ (SPEC-34),
    а не копіюється з Paper банку.
    При enforce_single_active=True забороняє переносити ставку, якщо вже є інша активна реальна ставка.
    """
    try:
        try:
            cur.execute("SELECT id, match_name, odds, stake_uah, kelly_pct FROM paper_bets WHERE id = %s;", (bet_id,))
            row = cur.fetchone()
        except Exception:
            cur.execute("SELECT id, match_name, odds, stake_uah FROM paper_bets WHERE id = %s;", (bet_id,))
            row = cur.fetchone()
        if not row:
            return False, f"Ставку #{bet_id} не знайдено."

        bid, m_name, orig_odds, orig_stake = row[:4]
        k_pct = row[4] if len(row) > 4 and row[4] is not None else None

        if is_real and enforce_single_active:
            cur.execute("""
                SELECT id, match_name, real_stake_uah 
                FROM paper_bets 
                WHERE is_real_bet = TRUE AND status = 'PENDING' AND id != %s;
            """, (bet_id,))
            ex_row = cur.fetchone()
            if ex_row:
                ex_id, ex_name, ex_stk = ex_row
                return False, f"Заборонено: у грі вже є активна ставка на реальні гроші (#{ex_id} {ex_name} — {float(ex_stk or 0):,.0f} ₴). Дочекайтесь розрахунку поточної ставки."

        updates = ["is_real_bet = %s"]
        params = [bool(is_real)]

        if is_real:
            # Визначаємо суму ставки:
            # 1. Якщо передано вручну - беремо її (округлену до цілих гривень)
            if real_stake is not None and float(real_stake) > 0:
                updates.append("real_stake_uah = %s")
                params.append(float(round(float(real_stake))))
            else:
                # 2. Розраховуємо суму від реального балансу за відсотком (Kelly % або динамічний % банку)
                from statmonitor.novig import calculate_real_stake
                cur.execute("SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1;")
                row_bal = cur.fetchone()
                real_bal = float(row_bal[0]) if (row_bal and row_bal[0] is not None) else 0.0

                eff_odds = float(real_odds) if (real_odds is not None and float(real_odds) > 1.0) else float(orig_odds or 1.85)
                if real_bal > 0:
                    rec_stk, _, _ = calculate_real_stake(eff_odds, real_bal, kelly_pct=k_pct, fraction=0.10)
                    auto_stake = float(round(rec_stk)) if rec_stk > 0 else 50.0
                else:
                    auto_stake = 50.0

                updates.append("real_stake_uah = %s")
                params.append(auto_stake)

            # Визначаємо коефіцієнт ставки
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


def update_real_bet_params(cur, conn, bet_id, new_odds=None, new_stake=None):
    """
    Коригує коефіцієнт та/або суму реальної ставки в грі (status = 'PENDING').
    Гарантує округлення суми до цілих гривень без копійок.
    Повертає: (ok: bool, msg: str)
    """
    try:
        cur.execute("""
            SELECT id, match_name, pick_label, odds, stake_uah, real_odds, real_stake_uah, status, is_real_bet, walkaway_odds
            FROM paper_bets
            WHERE id = %s;
        """, (bet_id,))
        row = cur.fetchone()
        if not row:
            return False, f"Ставку #{bet_id} не знайдено в базі."

        bid, m_name, pick, p_odds, p_stake, cur_r_odds, cur_r_stake, status, is_real, walkaway = row

        if str(status).upper() != "PENDING":
            return False, f"Ставка #{bid} вже має статус [{status}], коригування дозволено тільки для нерозрахованих (PENDING) ставок."

        updates = ["is_real_bet = TRUE"]
        params = []
        changes = []

        if new_odds is not None:
            k = float(new_odds)
            if k <= 1.01:
                return False, "Коефіцієнт повинен бути більше 1.01."
            updates.append("real_odds = %s")
            params.append(k)
            old_k_disp = float(cur_r_odds or p_odds or 0.0)
            changes.append(f"Коефіцієнт: {old_k_disp:.2f} ➔ {k:.2f}")

        if new_stake is not None:
            stk = float(round(float(new_stake)))
            if stk <= 0:
                return False, "Сума ставки повинна бути більшою за 0 грн."
            updates.append("real_stake_uah = %s")
            params.append(stk)
            old_stk_disp = float(cur_r_stake or 0.0)
            changes.append(f"Сума: {old_stk_disp:,.0f} ₴ ➔ {stk:,.0f} ₴")

        if not params:
            return False, "Не вказано нових параметрів для оновлення."

        params.append(bet_id)
        sql = f"UPDATE paper_bets SET {', '.join(updates)} WHERE id = %s;"
        cur.execute(sql, tuple(params))
        conn.commit()

        change_summary = "; ".join(changes)
        return True, f"Реальну ставку #{bid} ({m_name}) успішно оновлено! [{change_summary}]."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Помилка коригування реальної ставки: {e}"


def settle_real_bet_in_ledger(cur, conn, bet_id, status, profit_uah, stake_uah=None):
    """
    При розрахунку ставки, якщо вона позначена як is_real_bet,
    фіксує результат у real_bankroll_ledger (атомарний захист від повторних записів SPEC-38).
    """
    try:
        cur.execute("SELECT is_real_bet, match_name FROM paper_bets WHERE id = %s;", (bet_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            return False, "Ставка не є реальною."

        m_name = row[1]
        # Атомарна перевірка: чи вже був зафіксований результат ставки у леджері
        cur.execute("SELECT 1 FROM real_bankroll_ledger WHERE bet_id = %s AND transaction_type = 'BET_RESULT';", (bet_id,))
        if cur.fetchone():
            return False, f"Результат ставки #{bet_id} вже зафіксовано в леджері."

        p_val = float(profit_uah or 0.0)
        desc = f"Результат ставки #{bet_id} ({m_name}): {status} ({p_val:+.2f} ₴)"
        ok, _, msg = record_real_transaction(cur, conn, "BET_RESULT", p_val, description=desc, bet_id=bet_id)
        return ok, msg
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Помилка фіксації результату ставки в леджері: {e}"


def check_daily_stop_loss(cur, threshold_pct=7.0, now_dt=None):
    """
    SPEC-36: Перевіряє денний Stop-Loss Circuit Breaker.
    Якщо результат ставок за поточну добу (з 00:00 за Києвом) призвів до просідання >= threshold_pct,
    спрацьовує блокування відкриття нових реальних ставок.
    """
    try:
        if now_dt is None:
            now_dt = datetime.now(KYIV_TZ)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=KYIV_TZ)

        today_start_kyiv = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_kyiv.astimezone(timezone.utc)

        # 1. Результат закритих ставок за сьогодні (BET_RESULT)
        cur.execute("""
            SELECT COALESCE(SUM(amount_uah), 0)
            FROM real_bankroll_ledger
            WHERE transaction_type = 'BET_RESULT' AND created_at >= %s;
        """, (today_start_utc,))
        row_pnl = cur.fetchone()
        try:
            daily_pnl = float(row_pnl[0]) if (row_pnl and row_pnl[0] is not None) else 0.0
        except (ValueError, TypeError):
            daily_pnl = 0.0

        # 2. Баланс на початок доби (останній баланс до 00:00 сьогодні)
        cur.execute("""
            SELECT balance_after_uah
            FROM real_bankroll_ledger
            WHERE created_at < %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1;
        """, (today_start_utc,))
        row_start_b = cur.fetchone()

        if row_start_b and row_start_b[0] is not None:
            try:
                start_balance = float(row_start_b[0])
            except (ValueError, TypeError):
                start_balance = 0.0
        else:
            cur.execute("SELECT COALESCE(SUM(amount_uah) FILTER (WHERE transaction_type = 'DEPOSIT'), 0) FROM real_bankroll_ledger;")
            row_dep = cur.fetchone()
            try:
                start_balance = float(row_dep[0]) if (row_dep and row_dep[0] is not None) else 0.0
            except (ValueError, TypeError):
                start_balance = 0.0

        if start_balance > 0 and daily_pnl < 0:
            drawdown_pct = round((abs(daily_pnl) / start_balance) * 100.0, 2)
        else:
            drawdown_pct = 0.0

        is_triggered = bool(drawdown_pct >= threshold_pct and start_balance > 0)

        if is_triggered:
            msg = f"🛑 Stop-Loss активовано: денне просідання {drawdown_pct:.1f}% перевищує ліміт {threshold_pct}%. Нові реальні ставки заблоковано до 00:00."
        elif daily_pnl < 0:
            msg = f"⚠️ Денне просідання: -{abs(daily_pnl):,.2f} ₴ ({drawdown_pct:.1f}% / ліміт {threshold_pct}%)."
        elif daily_pnl > 0:
            msg = f"🟢 Денний прибуток: +{daily_pnl:,.2f} ₴ (Stop-Loss у нормі)."
        else:
            msg = "🟢 Денний PnL: 0.00 ₴ (Stop-Loss у нормі)."

        return {
            "is_triggered": is_triggered,
            "daily_pnl_uah": round(daily_pnl, 2),
            "start_balance_uah": round(start_balance, 2),
            "drawdown_pct": drawdown_pct,
            "threshold_pct": float(threshold_pct),
            "message": msg
        }
    except Exception as e:
        return {
            "is_triggered": False,
            "daily_pnl_uah": 0.0,
            "start_balance_uah": 0.0,
            "drawdown_pct": 0.0,
            "threshold_pct": float(threshold_pct),
            "message": f"Помилка розрахунку Stop-Loss: {e}"
        }


def check_max_exposure(cur, new_stake_total=0.0, max_exposure_pct=20.0):
    """
    SPEC-36: Перевіряє сумарну одночасну експозицію реального банку.
    Ліміт: відкриті ставки у грі (PENDING) не повинні перевищувати max_exposure_pct (20%) капіталу.
    """
    try:
        cur.execute("SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1;")
        row_b = cur.fetchone()
        try:
            current_balance = float(row_b[0]) if (row_b and row_b[0] is not None) else 0.0
        except (ValueError, TypeError):
            current_balance = 0.0

        cur.execute("SELECT COALESCE(SUM(amount_uah) FILTER (WHERE transaction_type = 'DEPOSIT'), 0) FROM real_bankroll_ledger;")
        row_dep = cur.fetchone()
        try:
            total_deposits = float(row_dep[0]) if (row_dep and row_dep[0] is not None) else 0.0
        except (ValueError, TypeError):
            total_deposits = 0.0

        base_capital = max(current_balance, total_deposits)

        cur.execute("""
            SELECT COALESCE(SUM(COALESCE(real_stake_uah, stake_uah)), 0), COUNT(*)
            FROM paper_bets
            WHERE is_real_bet = TRUE AND status = 'PENDING';
        """)
        row_exp = cur.fetchone()
        current_exposure = 0.0
        pending_count = 0
        if row_exp and len(row_exp) > 0:
            try:
                current_exposure = float(row_exp[0] or 0.0)
            except (ValueError, TypeError):
                current_exposure = 0.0
            if len(row_exp) > 1:
                try:
                    pending_count = int(row_exp[1] or 0)
                except (ValueError, TypeError):
                    pending_count = 0

        new_stk = float(new_stake_total or 0.0)
        projected_exposure = current_exposure + new_stk

        if base_capital > 0:
            exposure_pct = round((projected_exposure / base_capital) * 100.0, 1)
        else:
            exposure_pct = 0.0

        is_breached = bool(exposure_pct > max_exposure_pct and base_capital > 0)

        if is_breached:
            msg = f"⚠️ Перевищення експозиції: сума у грі ({projected_exposure:,.2f} ₴, {exposure_pct}%) перевищує ліміт {max_exposure_pct}% від банку ({base_capital:,.2f} ₴)."
        else:
            msg = f"🟢 Експозиція у нормі: {projected_exposure:,.2f} ₴ ({exposure_pct}% / ліміт {max_exposure_pct}%)."

        return {
            "is_breached": is_breached,
            "current_exposure_uah": round(current_exposure, 2),
            "new_stake_uah": round(new_stk, 2),
            "projected_exposure_uah": round(projected_exposure, 2),
            "exposure_pct": exposure_pct,
            "max_exposure_pct": float(max_exposure_pct),
            "base_capital_uah": round(base_capital, 2),
            "pending_count": pending_count,
            "message": msg
        }
    except Exception as e:
        return {
            "is_breached": False,
            "current_exposure_uah": 0.0,
            "new_stake_uah": 0.0,
            "projected_exposure_uah": 0.0,
            "exposure_pct": 0.0,
            "max_exposure_pct": float(max_exposure_pct),
            "base_capital_uah": 0.0,
            "pending_count": 0,
            "message": f"Помилка розрахунку експозиції: {e}"
        }


def check_correlation_guard(cur, candidate_bet_ids=None):
    """
    SPEC-36: Захист від корельованих ставок.
    Виявляє ситуації, коли кілька реальних ставок припадають на одну й ту саму подію (матч).
    """
    try:
        cur.execute("""
            SELECT id, event_id, match_name, pick_label
            FROM paper_bets
            WHERE is_real_bet = TRUE AND status = 'PENDING';
        """)
        active_rows = cur.fetchall() or []

        candidate_rows = []
        c_ids = [int(i) for i in (candidate_bet_ids or []) if str(i).isdigit()]
        if c_ids:
            cur.execute("""
                SELECT id, event_id, match_name, pick_label
                FROM paper_bets
                WHERE id = ANY(%s);
            """, (c_ids,))
            candidate_rows = cur.fetchall() or []

        matches_map = {}
        for r in active_rows:
            if not r or len(r) < 3:
                continue
            bid = r[0]
            eid = r[1] if len(r) > 1 else None
            m_name = r[2] if len(r) > 2 else ""
            pick = r[3] if len(r) > 3 else ""

            key = str(eid or m_name or bid).strip().lower()
            if key not in matches_map:
                matches_map[key] = {"match_name": m_name, "bets": []}
            matches_map[key]["bets"].append({"id": bid, "pick": pick, "type": "ACTIVE_PENDING"})

        for r in candidate_rows:
            if not r or len(r) < 3:
                continue
            bid = r[0]
            eid = r[1] if len(r) > 1 else None
            m_name = r[2] if len(r) > 2 else ""
            pick = r[3] if len(r) > 3 else ""

            key = str(eid or m_name or bid).strip().lower()
            if key not in matches_map:
                matches_map[key] = {"match_name": m_name, "bets": []}
            if not any(b["id"] == bid for b in matches_map[key]["bets"]):
                matches_map[key]["bets"].append({"id": bid, "pick": pick, "type": "CANDIDATE"})

        correlated_matches = []
        for key, data in matches_map.items():
            if len(data["bets"]) > 1:
                correlated_matches.append({
                    "match_name": data["match_name"],
                    "count": len(data["bets"]),
                    "bets": data["bets"]
                })

        has_correlations = len(correlated_matches) > 0
        if has_correlations:
            details = ", ".join([f"'{c['match_name']}' ({c['count']} ставки)" for c in correlated_matches])
            msg = f"⚠️ Виявлено кореляцію подій: на один матч припадає кілька ставок ({details}). Рекомендовано обмежитися 1 ставкою на гру."
        else:
            msg = "🟢 Кореляцій не виявлено (всі ставки на незалежні події)."

        return {
            "has_correlations": has_correlations,
            "correlated_matches": correlated_matches,
            "message": msg
        }
    except Exception as e:
        return {
            "has_correlations": False,
            "correlated_matches": [],
            "message": f"Помилка аналізу кореляцій: {e}"
        }


def evaluate_real_risk_guardrails(cur, candidate_configs=None, stop_loss_pct=7.0, max_exposure_pct=20.0):
    """
    SPEC-36: Комплексна оцінка ризик-запобіжників реального банку (Circuit Breakers).
    Повертає статус допуску до відкриття ставок та списки блокувань і попереджень.
    """
    candidate_configs = candidate_configs or []
    candidate_ids = [c["id"] for c in candidate_configs if isinstance(c, dict) and "id" in c]
    new_stake_total = sum(float(c.get("real_stake") or 0.0) for c in candidate_configs if isinstance(c, dict))

    sl_res = check_daily_stop_loss(cur, threshold_pct=stop_loss_pct)
    exp_res = check_max_exposure(cur, new_stake_total=new_stake_total, max_exposure_pct=max_exposure_pct)
    corr_res = check_correlation_guard(cur, candidate_bet_ids=candidate_ids)

    blocks = []
    warnings = []

    # 1. Жорстке блокування: Денний Stop-Loss
    if sl_res["is_triggered"]:
        blocks.append(sl_res["message"])

    # 2. Попередження при перевищенні експозиції
    if exp_res["is_breached"]:
        warnings.append(exp_res["message"])

    # 3. Попередження кореляції
    if corr_res["has_correlations"]:
        warnings.append(corr_res["message"])

    can_place = len(blocks) == 0

    return {
        "can_place_bets": can_place,
        "stop_loss": sl_res,
        "exposure": exp_res,
        "correlations": corr_res,
        "blocks": blocks,
        "warnings": warnings,
    }


def prepare_real_stakes_batch(cur, bet_ids, fraction=0.20, min_stake=20.0, max_pct=0.05, return_guardrails=False):
    """
    Підготовлює розрахунок розмірів ставок для списку bet_ids
    строго від ВІЛЬНОГО ЗАЛИШКУ реального банку (SPEC-34 & SPEC-36).
    Вільний залишок = Баланс леджера - Сума інших активних ставок у грі.
    Повертає: (free_real_balance, proposals_list) або (free_real_balance, proposals_list, guardrails)
    """
    from statmonitor.novig import calculate_real_stake

    # Розраховуємо загальний баланс леджера та експозицію інших ставок у грі
    try:
        cur.execute("""
            SELECT 
                (SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1),
                (SELECT COALESCE(SUM(COALESCE(real_stake_uah, stake_uah)), 0) 
                 FROM paper_bets 
                 WHERE is_real_bet = TRUE AND status = 'PENDING' AND NOT (id = ANY(%s)))
        """, (list(bet_ids or [0]),))
        row_b = cur.fetchone()
        ledger_balance = float(row_b[0]) if (row_b and row_b[0] is not None) else 0.0
        pending_exposure = float(row_b[1]) if (row_b and len(row_b) > 1 and row_b[1] is not None) else 0.0
    except Exception:
        cur.execute("SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1;")
        row_b = cur.fetchone()
        ledger_balance = float(row_b[0]) if (row_b and row_b[0] is not None) else 0.0
        pending_exposure = 0.0

    # Вільний залишок реального банку
    free_real_balance = max(0.0, ledger_balance - pending_exposure)
    real_balance = free_real_balance

    if not bet_ids:
        empty_guard = evaluate_real_risk_guardrails(cur, candidate_configs=[])
        if return_guardrails:
            return free_real_balance, [], empty_guard
        return free_real_balance, []

    # Витягуємо інформацію про вибрані ставки (включно з walkaway_odds, SPEC-37)
    try:
        cur.execute("""
            SELECT id, match_name, pick_label, odds, sport, kelly_pct, real_stake_uah, real_odds, is_real_bet, walkaway_odds
            FROM paper_bets
            WHERE id = ANY(%s) AND status = 'PENDING';
        """, (list(bet_ids),))
        rows = cur.fetchall()
        has_w_col = True
    except Exception:
        cur.execute("""
            SELECT id, match_name, pick_label, odds, sport, kelly_pct, real_stake_uah, real_odds, is_real_bet
            FROM paper_bets
            WHERE id = ANY(%s) AND status = 'PENDING';
        """, (list(bet_ids),))
        rows = cur.fetchall()
        has_w_col = False

    proposals = []
    for r in rows:
        b_id = r[0]
        m_name = r[1]
        pick = r[2]
        odds = r[3]
        sport = r[4]
        k_pct = r[5]
        cur_r_stake = r[6]
        cur_r_odds = r[7]
        is_real = r[8]
        w_val = float(r[9]) if (has_w_col and len(r) > 9 and r[9] is not None) else None

        eff_odds = float(cur_r_odds or odds or 1.85)

        if w_val is None:
            try:
                from statmonitor.novig import estimate_walkaway_odds
                w_val = estimate_walkaway_odds(eff_odds)
            except Exception:
                w_val = None

        # Розраховуємо суму від реального балансу з урахуванням розрахованого Kelly % ставки
        rec_stake, rec_pct, status_msg = calculate_real_stake(
            eff_odds,
            real_balance,
            kelly_pct=k_pct,
            fraction=fraction,
            min_stake=min_stake,
            max_pct=max_pct
        )

        proposals.append({
            "id": b_id,
            "match_name": m_name,
            "pick_label": pick,
            "odds": eff_odds,
            "walkaway_odds": w_val,
            "sport": sport,
            "real_balance": free_real_balance,
            "ledger_balance": ledger_balance,
            "pending_exposure": pending_exposure,
            "recommended_stake": float(round(rec_stake)),
            "recommended_pct": rec_pct,
            "current_real_stake": float(round(float(cur_r_stake))) if (cur_r_stake and float(cur_r_stake) not in (25.0, 30.0) and is_real) else float(round(rec_stake)),
            "is_real_bet": bool(is_real),
            "status_msg": status_msg
        })

    # Оцінюємо ризики для попередніх розрахунків
    provisional_configs = [{"id": p["id"], "real_stake": p["recommended_stake"]} for p in proposals]
    guardrails = evaluate_real_risk_guardrails(cur, candidate_configs=provisional_configs)
    for p in proposals:
        p["guardrails"] = guardrails

    if return_guardrails:
        return real_balance, proposals, guardrails
    return real_balance, proposals


def apply_real_stakes_batch(cur, conn, bet_configs, bypass_guardrails=False):
    """
    Пакетно оновлює ставки, переносячи їх у Реальний банк з визначеними сумами (SPEC-34 & SPEC-36).
    Перед застосуванням валідує Circuit Breakers (SPEC-36).
    bet_configs: список словників [{'id': 43, 'real_stake': 150.0, 'real_odds': 1.85}]
    """
    if not bet_configs:
        return False, 0, 0.0, "Список ставок для перенесення порожній."

    # SPEC-36: Circuit Breakers Risk Check
    if not bypass_guardrails:
        guardrails = evaluate_real_risk_guardrails(cur, candidate_configs=bet_configs)
        if not guardrails["can_place_bets"]:
            err_msg = " | ".join(guardrails["blocks"])
            return False, 0, 0.0, f"Запобіжники капіталу заблокували ставки: {err_msg}"

    try:
        updated_count = 0
        total_staked = 0.0

        for item in bet_configs:
            b_id = item.get("id")
            r_stake = float(round(float(item.get("real_stake") or 0.0)))
            r_odds = float(item.get("real_odds") or 0.0) if item.get("real_odds") else None

            if not b_id or r_stake <= 0:
                continue

            ok, _ = toggle_real_bet(
                cur, conn, b_id,
                is_real=True,
                real_stake=r_stake,
                real_odds=r_odds
            )
            if ok:
                updated_count += 1
                total_staked += r_stake

        conn.commit()
        return True, updated_count, total_staked, f"Успішно перенесено {updated_count} ставок у Реальний банк на загальну суму {total_staked:,.2f} ₴."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, 0, 0.0, f"Помилка пакетного перенесення ставок: {e}"
