import re
import requests
import statistics
from datetime import datetime
from statmonitor.config import INITIAL_BANKROLL, API_KEY, API_KEY_RESERVE, KYIV_TZ
from statmonitor.notifier import send_tg

# Еталонні букмекерські контори для розрахунку медіанного коефіцієнта (SPEC-18)
BENCHMARK_BOOKMAKERS = {
    "pinnacle",
    "betfair_ex_eu",
    "betfair",
    "unibet_eu",
    "unibet",
    "marathonbet",
}

def parse_pick_label(pick_lbl, match_name=""):
    """
    Розбирає лейбл ставки (наприклад, 'Ф2 (+4.5)', 'ТБ 2.5', 'П1 (Arsenal)')
    на складові: (market_key, outcome_name, point).
    """
    if not pick_lbl:
        return None, None, None
    p = str(pick_lbl).strip()
    parts = [x.strip() for x in str(match_name).split(" - ", 1)]
    h_t = parts[0] if len(parts) >= 1 else ""
    a_t = parts[1] if len(parts) >= 2 else ""

    # 1. Totals (ТБ / ТМ / Over / Under)
    m_tb = re.search(r"(?:^|\b|\()(?:тб|over)\s*\(?([0-9.]+)\)?", p, re.I)
    if m_tb:
        return "totals", "Over", float(m_tb.group(1))
    m_tm = re.search(r"(?:^|\b|\()(?:тм|under)\s*\(?([0-9.]+)\)?", p, re.I)
    if m_tm:
        return "totals", "Under", float(m_tm.group(1))

    # 2. Spreads / Фора
    m_f1 = re.search(r"(?:^|\b|\()(?:ф1|фора\s*1)\s*\(?([+-]?[0-9.]+)\)?", p, re.I)
    if m_f1:
        return "spreads", h_t, float(m_f1.group(1))
    m_f2 = re.search(r"(?:^|\b|\()(?:ф2|фора\s*2)\s*\(?([+-]?[0-9.]+)\)?", p, re.I)
    if m_f2:
        return "spreads", a_t, float(m_f2.group(1))

    m_fo = re.search(r"фора\s+(.+?)\s*\(?([+-]?[0-9.]+)\)?", p, re.I)
    if m_fo:
        team_part = m_fo.group(1).strip()
        pt = float(m_fo.group(2))
        if h_t and (team_part.lower() == h_t.lower() or team_part.lower() in h_t.lower()):
            return "spreads", h_t, pt
        if a_t and (team_part.lower() == a_t.lower() or team_part.lower() in a_t.lower()):
            return "spreads", a_t, pt
        return "spreads", team_part, pt

    # 3. Moneyline (H2H)
    if re.search(r"(?:^|\b|\()п1(?:\b|\)|$)", p, re.I) or (h_t and h_t.lower() in p.lower() and not re.search(r"[+-][0-9]", p)):
        return "h2h", h_t, None
    if re.search(r"(?:^|\b|\()п2(?:\b|\)|$)", p, re.I) or (a_t and a_t.lower() in p.lower() and not re.search(r"[+-][0-9]", p)):
        return "h2h", a_t, None
    if re.search(r"(?:^|\b|\()[хx](?:\b|\)|$)", p, re.I) or "нічия" in p.lower() or "draw" in p.lower():
        return "h2h", "Draw", None

    return None, None, None

def resolve_alert_from_history(cur, event_id, bookmaker, price, outcome=None):
    """
    Якщо v_odds_alerts не містить точного point або market_key,
    перевіряє в odds_history за event_id, bookmaker і price,
    чи це справді h2h, чи фора spreads / тотал totals.
    Повертає кортеж: (market_key, point, outcome_name, price)
    """
    if not cur or not event_id:
        return None, None, outcome, price
    try:
        p_val = float(price) if price is not None else 0.0

        # 1. Пошук з урахуванням outcome_name, якщо передано
        if outcome:
            cur.execute("""
                SELECT market_key, point, outcome_name, price
                FROM odds_history
                WHERE event_id = %s
                  AND bookmaker = %s
                  AND (LOWER(TRIM(outcome_name)) = LOWER(TRIM(%s)) OR outcome_name ILIKE %s)
                  AND (price = %s OR ABS(price - %s) <= 0.01)
                ORDER BY recorded_at DESC
                LIMIT 1;
            """, (event_id, bookmaker, outcome, outcome, p_val, p_val))
            row = cur.fetchone()
            if row:
                return row[0], (float(row[1]) if row[1] is not None else None), row[2], float(row[3])

        # 2. Пошук суто за event_id, bookmaker та ціною
        cur.execute("""
            SELECT market_key, point, outcome_name, price
            FROM odds_history
            WHERE event_id = %s
              AND bookmaker = %s
              AND (price = %s OR ABS(price - %s) <= 0.01)
            ORDER BY recorded_at DESC
            LIMIT 1;
        """, (event_id, bookmaker, p_val, p_val))
        row = cur.fetchone()
        if row:
            return row[0], (float(row[1]) if row[1] is not None else None), row[2], float(row[3])
    except Exception as e:
        print(f"resolve_alert_from_history err: {e}")

    return None, None, outcome, price

def get_market_median_odds(cur, event_id, pick_label, match_name="", fallback_odds=None, at_time=None):
    """
    Обчислює реальний медіанний коефіцієнт ринку або еталонних БК (pinnacle, betfair_ex_eu, unibet_eu, marathonbet)
    на основі записів в odds_history для конкретного маркету, результату та фори/тоталу.
    Якщо вказано at_time, враховує коефіцієнти, актуальні на цей момент часу (для перерахунку розрахованих матчів).
    """
    mkt, out_name, pt = parse_pick_label(pick_label, match_name)
    fb = float(fallback_odds) if fallback_odds is not None else 1.0
    if not cur or not event_id or not mkt:
        return fb

    try:
        # Якщо назва матчу була неповною, підтягуємо з events
        if not out_name and match_name:
            cur.execute("SELECT match_name FROM events WHERE id=%s LIMIT 1;", (event_id,))
            ev_row = cur.fetchone()
            if ev_row and ev_row[0]:
                match_name = ev_row[0]
                mkt, out_name, pt = parse_pick_label(pick_label, match_name)

        params = [event_id, mkt]

        # Побудова фільтрації за маркетом та результатом
        outcome_filter = ""
        if mkt == "totals":
            outcome_filter = "AND LOWER(outcome_name) = LOWER(%s)"
            params.append(out_name)
        elif mkt == "spreads":
            outcome_filter = "AND (LOWER(TRIM(outcome_name)) = LOWER(TRIM(%s)) OR outcome_name ILIKE %s)"
            params.extend([out_name, out_name])
        elif mkt == "h2h":
            if out_name == "Draw":
                outcome_filter = "AND (LOWER(outcome_name) IN ('draw', 'draws') OR outcome_name ILIKE '%draw%' OR outcome_name ILIKE '%нічия%')"
            else:
                outcome_filter = "AND (LOWER(TRIM(outcome_name)) = LOWER(TRIM(%s)) OR outcome_name ILIKE %s)"
                params.extend([out_name, out_name])

        point_filter = ""
        if pt is not None:
            point_filter = "AND ABS(point - %s) < 0.01"
            params.append(pt)
        else:
            point_filter = "AND (point IS NULL OR point = 0)" if mkt == "h2h" else "AND point IS NULL"

        time_filter = ""
        if at_time is not None:
            time_filter = "AND recorded_at <= %s AND recorded_at >= %s - INTERVAL '48 hours'"
            params.extend([at_time, at_time])
        else:
            time_filter = "AND recorded_at >= NOW() - INTERVAL '48 hours'"

        query = f"""
            SELECT bookmaker, price
            FROM (
                SELECT bookmaker, price,
                       ROW_NUMBER() OVER (PARTITION BY bookmaker ORDER BY recorded_at DESC) as rn
                FROM odds_history
                WHERE event_id = %s
                  AND market_key = %s
                  {outcome_filter}
                  {point_filter}
                  {time_filter}
            ) sub
            WHERE rn = 1;
        """
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        # Якщо на момент at_time записів не знайдено, спробуємо розширене вікно навколо ref_time
        if not rows and at_time is not None:
            query_relaxed = f"""
                SELECT bookmaker, price
                FROM (
                    SELECT bookmaker, price,
                           ROW_NUMBER() OVER (PARTITION BY bookmaker ORDER BY recorded_at DESC) as rn
                    FROM odds_history
                    WHERE event_id = %s
                      AND market_key = %s
                      {outcome_filter}
                      {point_filter}
                      AND recorded_at >= %s - INTERVAL '7 days'
                      AND recorded_at <= %s + INTERVAL '24 hours'
                ) sub
                WHERE rn = 1;
            """
            cur.execute(query_relaxed, tuple(params[:-2] + [at_time, at_time]))
            rows = cur.fetchall()

        # Якщо все ще немає записів (наприклад, минулий матч без передачі at_time або великий часовий розрив)
        if not rows:
            query_any_time = f"""
                SELECT bookmaker, price
                FROM (
                    SELECT bookmaker, price,
                           ROW_NUMBER() OVER (PARTITION BY bookmaker ORDER BY recorded_at DESC) as rn
                    FROM odds_history
                    WHERE event_id = %s
                      AND market_key = %s
                      {outcome_filter}
                      {point_filter}
                ) sub
                WHERE rn = 1;
            """
            base_params = [params[0], params[1]]
            if outcome_filter:
                if mkt == "spreads":
                    base_params.extend([out_name, out_name])
                elif mkt == "totals":
                    base_params.append(out_name)
                elif mkt == "h2h" and out_name != "Draw":
                    base_params.extend([out_name, out_name])
            if pt is not None:
                base_params.append(pt)
            cur.execute(query_any_time, tuple(base_params))
            rows = cur.fetchall()

        if not rows:
            return fb

        bm_prices = [float(p) for bm, p in rows if bm.lower() in BENCHMARK_BOOKMAKERS and float(p) > 1.0]
        all_prices = [float(p) for _, p in rows if float(p) > 1.0]

        if bm_prices:
            return round(float(statistics.median(bm_prices)), 2)
        elif all_prices:
            return round(float(statistics.median(all_prices)), 2)
    except Exception as e:
        print(f"get_market_median_odds err: {e}")

    return fb

def recalculate_historical_paper_bets(cur, conn):
    """
    Переглядає всі уже створені/розраховані ставки в paper_bets,
    якщо для матчу є аналіз ШІ — синхронізує pick_label з AI short_pick,
    підтягує з odds_history реальний медіанний коефіцієнт ринку/еталонних БК на момент ставки,
    оновлює odds та перераховує profit_uah для виграшних ставок.
    """
    if not cur or not conn:
        return []

    try:
        from statmonitor.ai import extract_short_pick
    except ImportError:
        extract_short_pick = lambda txt, fb: fb

    cur.execute("""
        SELECT pb.id, pb.event_id, pb.match_name, pb.pick_label, pb.odds, pb.stake_uah, pb.status, pb.profit_uah, pb.created_at, pb.commence_time, ai.verdict_text
        FROM paper_bets pb
        LEFT JOIN ai_match_analysis ai ON pb.event_id = ai.event_id
        ORDER BY pb.id ASC;
    """)
    rows = cur.fetchall()
    updated = []

    for row in rows:
        if len(row) >= 11:
            bid, eid, m_name, pick_lbl, old_odds, stake, st, old_prof, cr_at, c_time, ai_txt = row[:11]
        else:
            bid, eid, m_name, pick_lbl, old_odds, stake, st, old_prof, cr_at, c_time = row[:10]
            ai_txt = None
        old_k = float(old_odds)
        ref_time = cr_at or c_time

        # Строга заборона зміни активних ставок: перерахунок застосовується виключно до розрахованих матчів!
        if st == "PENDING":
            continue

        # Синхронізація з вердиктом ШІ для історичних розрахованих матчів
        effective_pick = pick_lbl
        if ai_txt:
            ai_pick = extract_short_pick(ai_txt, fallback=pick_lbl)
            if ai_pick and not any(w in ai_pick.lower() for w in ("пропустити", "утриматися")):
                effective_pick = ai_pick

        real_k = get_market_median_odds(cur, eid, effective_pick, m_name, fallback_odds=old_k, at_time=ref_time)

        changed = False
        if effective_pick != pick_lbl or abs(real_k - old_k) > 0.01:
            changed = True

        if changed:
            stk = float(stake)
            new_prof = float(old_prof)
            if st == "WON":
                new_prof = round(stk * (real_k - 1.0), 2)
            elif st == "LOST":
                new_prof = round(-stk, 2)
            elif st == "VOID":
                new_prof = 0.0

            cur.execute("""
                UPDATE paper_bets
                SET pick_label = %s, odds = %s, profit_uah = %s
                WHERE id = %s;
            """, (effective_pick, real_k, new_prof, bid))

            updated.append({
                "id": bid,
                "event_id": eid,
                "match_name": m_name,
                "old_pick": pick_lbl,
                "pick_label": effective_pick,
                "old_odds": old_k,
                "new_odds": real_k,
                "status": st,
                "old_profit": float(old_prof),
                "new_profit": new_prof,
            })

    conn.commit()
    return updated

def format_pick(market, outcome, point, match_name):
    out_s = str(outcome or "").strip()
    if re.match(r"^(?:П1|П2|Х|Ф1|Ф2|ТБ|ТМ)\b", out_s):
        return out_s
    m_name = str(match_name or "").strip()
    parts = [p.strip() for p in m_name.split(" - ", 1)] if " - " in m_name else ([m_name] if m_name else [])
    h_t, a_t = (parts[0], parts[1]) if len(parts) == 2 else ("", "")
    if market == "totals" or out_s.lower() in ("over", "under"):
        pt = f"{float(point):g}" if point is not None else ""
        return f"{'ТБ' if out_s.lower() == 'over' else 'ТМ'} {pt}".strip()
    if market == "spreads" or point is not None:
        pt = f"{float(point):+g}" if point is not None else ""
        if out_s and out_s == h_t: return f"Ф1 ({pt})"
        if out_s and out_s == a_t: return f"Ф2 ({pt})"
        return f"Фора {out_s} ({pt})" if out_s else f"Фора ({pt})"
    if out_s and out_s == h_t: return f"П1 ({h_t})"
    if out_s and out_s == a_t: return f"П2 ({a_t})"
    return "Х (Нічия)" if out_s.lower() == "draw" else out_s

def calculate_kelly_fraction(odds, drop_pct=None, confidence=None, fraction=0.25, min_pct=0.01, max_pct=0.05):
    """
    Розраховує частку вільного банку за дробовим критерієм Келлі (Fractional Kelly Criterion).
    f* = Edge / (odds - 1)
    f_fractional = fraction * f*
    За замовчуванням fraction = 0.25 (Quarter Kelly) із захисними межами [1%, 5%].
    Повертає десяткову частку (наприклад, 0.032 для 3.2%).
    """
    try:
        k = float(odds)
        if k <= 1.01:
            return 0.0
    except (ValueError, TypeError):
        return 0.0

    b = k - 1.0
    # 1. Оцінка переваги (Edge) на основі сили прогрузу (drop_pct) або рівня впевненості
    if drop_pct is not None and float(drop_pct) > 0:
        d = min(float(drop_pct), 40.0)
        edge = 0.03 + (d / 100.0) * 0.30
    elif confidence is not None:
        c = max(1.0, min(10.0, float(confidence)))
        edge = 0.02 + (c / 10.0) * 0.06
    else:
        # Консервативна базова перевага відбору
        edge = 0.07 if k <= 1.75 else (0.06 if k <= 2.35 else 0.05)

    full_kelly = edge / b
    frac_kelly = full_kelly * fraction
    clamped = max(min_pct, min(max_pct, frac_kelly))
    return round(clamped, 4)

def place_paper_bet(cur, conn, ev_id, sport, match, c_time, pick_lbl, odds, drop_pct=None, confidence=None):
    try:
        if any(w in pick_lbl.lower() for w in ("пропустити", "утриматися")):
            return False
        # Строга заборона зміни активних або існуючих ставок:
        # Ставка фіксується один раз і є незмінною для всіх автоматичних процесів!
        cur.execute("SELECT 1 FROM paper_bets WHERE event_id=%s;", (ev_id,))
        if cur.fetchone():
            return False
        cur.execute("SELECT COALESCE(SUM(profit_uah),0), COALESCE(SUM(CASE WHEN status='PENDING' THEN stake_uah ELSE 0 END),0) FROM paper_bets;")
        prof, locked = cur.fetchone()
        avail = round(max(0.0, INITIAL_BANKROLL + float(prof) - float(locked)), 2)
        if avail < 50:
            return False
        k = float(odds)
        
        # Розрахунок розміру ставки за дробовим критерієм Келлі (SPEC-22)
        frac = calculate_kelly_fraction(k, drop_pct=drop_pct, confidence=confidence, fraction=0.25)
        kelly_pct = round(frac * 100.0, 1)
        stake = min(round(avail * frac, 2), avail)

        try:
            cur.execute(
                "INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah, kelly_pct) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING;",
                (ev_id, sport, match, c_time, pick_lbl, k, stake, kelly_pct),
            )
        except Exception:
            if conn:
                conn.rollback()
            cur.execute(
                "INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING;",
                (ev_id, sport, match, c_time, pick_lbl, k, stake),
            )
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Place bet err: {e}")
        return False

def eval_outcome(pick_lbl, match_name, h_sc, a_sc):
    p = str(pick_lbl or "").lower()
    m_name = str(match_name or "").strip()
    parts = [x.strip().lower() for x in m_name.split(" - ", 1)] if " - " in m_name else []
    h_t, a_t = (parts[0], parts[1]) if len(parts) == 2 else ("", "")
    m_tb = re.search(r"(?:тб|over)\s*\(?([0-9.]+)\)?", p)
    if m_tb:
        ln = float(m_tb.group(1))
        return "WON" if (h_sc + a_sc) > ln else ("LOST" if (h_sc + a_sc) < ln else "VOID")
    m_tm = re.search(r"(?:тм|under)\s*\(?([0-9.]+)\)?", p)
    if m_tm:
        ln = float(m_tm.group(1))
        return "WON" if (h_sc + a_sc) < ln else ("LOST" if (h_sc + a_sc) > ln else "VOID")
    m_f = re.search(r"ф([12])\s*\(?([+-]?[0-9.]+)\)?", p)
    if m_f:
        hv = float(m_f.group(2))
        diff = (h_sc + hv - a_sc) if m_f.group(1) == "1" else (a_sc + hv - h_sc)
        return "WON" if diff > 0 else ("LOST" if diff < 0 else "VOID")
    if re.search(r"(?:^|\b|\()п1(?:\b|\)|$)", p) or (h_t and h_t in p):
        return "WON" if h_sc > a_sc else "LOST"
    if re.search(r"(?:^|\b|\()п2(?:\b|\)|$)", p) or (a_t and a_t in p):
        return "WON" if a_sc > h_sc else "LOST"
    if re.search(r"(?:^|\b|\()[хx](?:\b|\)|$)", p) or "нічия" in p:
        return "WON" if h_sc == a_sc else "LOST"
    return None

def update_pending_bet_odds(cur=None, conn=None, bet_id=None, new_odds=None):
    """
    Оновлює коефіцієнт для нерозрахованої ставки (status = 'PENDING').
    Повертає кортеж (success: bool, message: str, old_odds: float | None).
    """
    should_close = False
    if not conn or not cur:
        from statmonitor.database import get_db
        conn = get_db()
        if not conn:
            return False, "База даних недоступна", None
        cur = conn.cursor()
        should_close = True

    try:
        k = float(new_odds)
        if k <= 1.0 or k > 100.0:
            return False, f"Неприпустимий коефіцієнт: {new_odds}. Очікується значення від 1.01 до 100.0.", None
    except (ValueError, TypeError):
        return False, f"Некоректний формат коефіцієнта: '{new_odds}'. Очікується десяткове число (наприклад, 1.75).", None
    finally:
        pass

    try:
        cur.execute("""
            SELECT id, match_name, pick_label, odds, stake_uah, status
            FROM paper_bets
            WHERE id = %s;
        """, (bet_id,))
        row = cur.fetchone()
        if not row:
            return False, f"Ставку #{bet_id} не знайдено в базі даних.", None

        bid, m_name, pk, old_k_raw, stake, st = row
        old_k = float(old_k_raw)

        if st != "PENDING":
            return False, f"Неможливо змінити коефіцієнт: ставка #{bid} ({m_name}) вже має статус '{st}'. Редагування дозволено тільки для нерозрахованих ставок (PENDING).", old_k

        cur.execute("""
            UPDATE paper_bets
            SET odds = %s
            WHERE id = %s AND status = 'PENDING';
        """, (k, bid))
        conn.commit()

        pot_profit = round(float(stake) * (k - 1.0), 2)
        msg = f"Коефіцієнт для ставки #{bid} ({m_name} | {pk}) успішно змінено з {old_k:.2f} на {k:.2f}. Новий потенційний профіт: +{pot_profit:.2f} грн."
        return True, msg, old_k
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Помилка бази даних під час оновлення коефіцієнта: {e}", None
    finally:
        if should_close:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass

def manual_settle_bet(cur, conn, bet_id, score_str, forced_status=None):
    """
    Дозволяє вручну розрахувати ставку (наприклад, для тенісних матчів з форою по геймах,
    скасованих матчів або подій, яких немає в автоматичному API).
    """
    try:
        cur.execute("SELECT id, match_name, pick_label, odds, stake_uah FROM paper_bets WHERE id=%s;", (bet_id,))
        row = cur.fetchone()
        if not row:
            return False, f"Ставку #{bet_id} не знайдено."
        bid, m_name, pk, odds, st = row

        res = (forced_status or "").upper() if forced_status else None
        if not res or res not in ("WON", "LOST", "VOID"):
            # Спробуємо визначити результат за рахунком
            m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", str(score_str))
            if m:
                hs, as_ = int(m.group(1)), int(m.group(2))
                res = eval_outcome(pk, m_name, hs, as_)

        if res in ("WON", "LOST", "VOID"):
            prof = round(float(st) * (float(odds) - 1.0), 2) if res == "WON" else (round(-float(st), 2) if res == "LOST" else 0.0)
            cur.execute("UPDATE paper_bets SET status=%s, match_score=%s, profit_uah=%s, settled_at=NOW() WHERE id=%s;", (res, score_str, prof, bid))
            conn.commit()
            return True, f"Ставку #{bid} ({m_name}) успішно розраховано як {res} ({score_str}) з профітом {prof:+.2f} грн."
        return False, f"Не вдалося визначити статус WON/LOST/VOID для рахунку '{score_str}'."
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Помилка розрахунку ставки: {e}"

def settle_and_report(cur, conn):
    try:
        cur.execute("SELECT id, event_id, sport, match_name, pick_label, odds, stake_uah FROM paper_bets WHERE status='PENDING' AND commence_time < NOW() - INTERVAL '2 hours 15 minutes';")
        pending = cur.fetchall()
        if pending:
            scores = {}
            cur_k = API_KEY or API_KEY_RESERVE
            for sp in {r[2] for r in pending}:
                r = requests.get(f"https://api.the-odds-api.com/v4/sports/{sp}/scores/", params={"apiKey": cur_k, "daysFrom": 3}, timeout=12)
                if r.status_code != 200 and API_KEY_RESERVE and cur_k != API_KEY_RESERVE:
                    cur_k = API_KEY_RESERVE
                    r = requests.get(f"https://api.the-odds-api.com/v4/sports/{sp}/scores/", params={"apiKey": cur_k, "daysFrom": 3}, timeout=12)
                if r.status_code == 200:
                    for ev in r.json():
                        if ev.get("completed") and ev.get("scores"):
                            scores[ev["id"]] = ev
            for bid, eid, sp, m_name, pk, odds, st in pending:
                ev = scores.get(eid)
                if not ev:
                    continue
                sc_map = {s["name"]: int(re.findall(r"\d+", str(s["score"]))[0]) for s in ev["scores"] if re.findall(r"\d+", str(s.get("score", "")))}
                hs, as_ = sc_map.get(ev.get("home_team")), sc_map.get(ev.get("away_team"))
                if hs is None or as_ is None:
                    continue
                res = eval_outcome(pk, f"{ev.get('home_team')} - {ev.get('away_team')}", hs, as_)
                if res in ("WON", "LOST", "VOID"):
                    prof = round(float(st) * (float(odds) - 1), 2) if res == "WON" else (round(-float(st), 2) if res == "LOST" else 0.0)
                    cur.execute("UPDATE paper_bets SET status=%s, match_score=%s, profit_uah=%s, settled_at=NOW() WHERE id=%s;", (res, f"{hs}:{as_}", prof, bid))
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Settle err: {e}")

    try:
        kyiv_now = datetime.now(KYIV_TZ)
        if kyiv_now.hour >= 8:
            cur.execute("SELECT 1 FROM paper_daily_reports WHERE report_date=%s;", (kyiv_now.date(),))
            if not cur.fetchone():
                cur.execute("""
                    SELECT COUNT(*), COUNT(*) FILTER (WHERE status='WON'), COUNT(*) FILTER (WHERE status='LOST'),
                           COUNT(*) FILTER (WHERE status='VOID'), COUNT(*) FILTER (WHERE status='PENDING'),
                           COALESCE(SUM(stake_uah) FILTER (WHERE status IN ('WON','LOST','VOID')),0),
                           COALESCE(SUM(profit_uah) FILTER (WHERE status IN ('WON','LOST','VOID')),0)
                    FROM paper_bets;
                """)
                tot, won, lost, void, pend, turn, net = cur.fetchone()
                fin = round(INITIAL_BANKROLL + float(net), 2)
                roi = round((float(net) / float(turn)) * 100, 2) if float(turn) > 0 else 0.0
                send_tg(
                    f"💼 <b>ЩОДЕННИЙ ЗВІТ PAPER BANK ({kyiv_now.strftime('%d.%m.%Y')})</b>\n\n"
                    f"🏦 Початковий банк: <code>{INITIAL_BANKROLL:,.2f} грн</code>\n"
                    f"💰 Кінцевий банк: <b><code>{fin:,.2f} грн</code></b> (<code>{fin - INITIAL_BANKROLL:+.2f} грн</code>)\n"
                    f"📈 ROI: <b><code>{roi:+.2f}%</code></b>\n\n"
                    f"📊 Всього ставок: <b>{tot}</b> (в грі: {pend})\n"
                    f"✅ Виграшні: <b>{won}</b> | ❌ Програшні: <b>{lost}</b> | 🔄 Повернення: <b>{void}</b>"
                )
                cur.execute("INSERT INTO paper_daily_reports (report_date) VALUES (%s) ON CONFLICT DO NOTHING;", (kyiv_now.date(),))
                conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Daily summary err: {e}")
