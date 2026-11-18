"""
StatMonitor - Модуль розширеної аналітики ефективності та ризиків (SPEC-24).
Розрахунок Max Drawdown, серій виграшів/програшів (streaks), сегментація по лігах та маркетах.
"""

import re
from decimal import Decimal
from statmonitor.config import INITIAL_BANKROLL

def _to_records(data):
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        return data.to_dict(orient="records")
    if isinstance(data, list):
        return [dict(d) if isinstance(d, dict) else d for d in data]
    return list(data)

def classify_market_group(pick_label):
    """
    Класифікує назву ставки у стандартну категорію ринків:
    - Тотали (Total Over/Under)
    - Фори (Handicap / Spreads)
    - Обидві заб'ють (BTTS)
    - 1X2 / Переможець (H2H)
    """
    if not pick_label:
        return "1X2 / Переможець"
    lbl = str(pick_label).lower()
    if any(k in lbl for k in ("тотал", "більше", "менше", "over", "under", "тб", "тм")):
        return "Тотали"
    if any(k in lbl for k in ("фора", "handicap", "spread")) or ("+" in lbl or "-" in lbl and "(" in lbl):
        return "Фори"
    if any(k in lbl for k in ("обидві", "btts", "обе забьют", "оз:", "оз -", "оз (")) or re.search(r"(?:^|\b|\()оз(?:\b|\)|$)", lbl):
        return "Обидві заб'ють"
    return "1X2 / Переможець"

def calculate_clv_value(bet_odds, closing_odds):
    """
    Обчислює Closing Line Value (CLV) для окремої ставки:
    - clv_pct = ((bet_odds / closing_odds) - 1.0) * 100.0
    - beat_closing_line = (bet_odds > closing_odds)
    """
    try:
        b_k = float(bet_odds)
        c_k = float(closing_odds)
        if b_k > 1.0 and c_k > 1.0:
            clv = round(((b_k / c_k) - 1.0) * 100.0, 2)
            beat = (b_k > c_k)
            return clv, beat
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return 0.0, False

def calculate_clv_metrics(bets):
    """
    Агрегує показники Closing Line Value (CLV) по набору ставок (SPEC-20):
    - total_with_clv: кількість ставок із зафіксованою лінією закриття
    - beat_count: кількість ставок, де вдалося побити лінію закриття
    - beat_line_pct: % ставок, які побили лінію закриття (Beat the Closing Line %)
    - avg_clv_pct: середнє значення математичної переваги (+EV) над ринком
    - positive_clv_count: кількість ставок із позитивним CLV (> 0%)
    - negative_clv_count: кількість ставок із негативним CLV (< 0%)
    """
    records = _to_records(bets)
    clv_list = []
    beat_count = 0
    pos_count = 0
    neg_count = 0

    for b in records:
        clv_val = b.get("clv_pct")
        beat_val = b.get("beat_closing_line")
        b_k = b.get("odds")
        c_k = b.get("closing_odds")

        # Якщо CLV ще не обчислено в базі, але є коефіцієнт та лінія закриття
        if clv_val is None and b_k and c_k:
            clv_val, beat_val = calculate_clv_value(b_k, c_k)

        if clv_val is not None:
            try:
                clv_f = float(clv_val)
                clv_list.append(clv_f)
                if beat_val is True or (beat_val is None and clv_f > 0):
                    beat_count += 1
                if clv_f > 0:
                    pos_count += 1
                elif clv_f < 0:
                    neg_count += 1
            except (ValueError, TypeError):
                pass

    tot = len(clv_list)
    if tot == 0:
        return {
            "total_with_clv": 0,
            "beat_count": 0,
            "beat_line_pct": 0.0,
            "avg_clv_pct": 0.0,
            "positive_clv_count": 0,
            "negative_clv_count": 0,
        }

    beat_pct = round((beat_count / tot) * 100.0, 1)
    avg_clv = round(sum(clv_list) / tot, 2)

    return {
        "total_with_clv": tot,
        "beat_count": beat_count,
        "beat_line_pct": beat_pct,
        "avg_clv_pct": avg_clv,
        "positive_clv_count": pos_count,
        "negative_clv_count": neg_count,
    }

def calculate_drawdown(settled_bets, initial_bankroll=INITIAL_BANKROLL):
    """
    Розраховує показники максимального просідання капіталу (Max Drawdown):
    - max_drawdown_pct: максимальне відносне просідання від локального піку (%)
    - max_drawdown_uah: максимальне абсолютне просідання (грн)
    - peak_balance: найвищий зафіксований баланс (грн)
    - current_drawdown_pct: поточне просідання від піку (%)
    """
    bets = _to_records(settled_bets)
    valid_bets = [b for b in bets if b.get("status") in ("WON", "LOST", "VOID")]

    init_b = float(initial_bankroll)
    if not valid_bets:
        return {
            "max_drawdown_pct": 0.0,
            "max_drawdown_uah": 0.0,
            "peak_balance": init_b,
            "current_drawdown_pct": 0.0,
        }

    # Сортування за часом розрахунку, якщо доступно
    try:
        valid_bets.sort(key=lambda x: str(x.get("settled_at") or x.get("commence_time") or x.get("id") or ""))
    except Exception:
        pass

    peak = init_b
    current_balance = init_b
    max_dd_uah = 0.0
    max_dd_pct = 0.0

    for b in valid_bets:
        prof = float(b.get("profit_uah") or 0.0)
        current_balance += prof
        if current_balance > peak:
            peak = current_balance

        dd_uah = peak - current_balance
        dd_pct = (dd_uah / peak * 100.0) if peak > 0 else 0.0

        if dd_uah > max_dd_uah:
            max_dd_uah = dd_uah
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    curr_dd_uah = peak - current_balance
    curr_dd_pct = (curr_dd_uah / peak * 100.0) if peak > 0 else 0.0

    return {
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_uah": round(max_dd_uah, 2),
        "peak_balance": round(peak, 2),
        "current_drawdown_pct": round(curr_dd_pct, 2),
    }

def calculate_streaks(settled_bets):
    """
    Розраховує довжину переможних та програшних серій (streaks):
    - max_win_streak: максимальна кількість виграшів поспіль
    - max_loss_streak: максимальна кількість програшів поспіль
    - current_streak_type: тип поточної серії ('W', 'L', або '-')
    - current_streak_count: довжина поточної серії
    """
    bets = _to_records(settled_bets)
    # Фільтруємо лише розраховані ставки з результатом
    resolved = [b for b in bets if b.get("status") in ("WON", "LOST")]

    if not resolved:
        return {
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "current_streak_type": "-",
            "current_streak_count": 0,
        }

    try:
        resolved.sort(key=lambda x: str(x.get("settled_at") or x.get("commence_time") or x.get("id") or ""))
    except Exception:
        pass

    max_w = 0
    max_l = 0
    curr_w = 0
    curr_l = 0

    for b in resolved:
        st = b.get("status")
        if st == "WON":
            curr_w += 1
            curr_l = 0
            if curr_w > max_w:
                max_w = curr_w
        elif st == "LOST":
            curr_l += 1
            curr_w = 0
            if curr_l > max_l:
                max_l = curr_l

    # Визначаємо поточну серію за останніми ставками
    last_status = resolved[-1].get("status")
    last_type = "W" if last_status == "WON" else "L"
    last_count = 0
    for b in reversed(resolved):
        if b.get("status") == last_status:
            last_count += 1
        else:
            break

    return {
        "max_win_streak": max_w,
        "max_loss_streak": max_l,
        "current_streak_type": last_type,
        "current_streak_count": last_count,
    }

def calculate_league_breakdown(settled_bets, sports_map=None):
    """
    Групує історію розрахованих ставок за лігами/турнірами:
    Повертає список словників: sport, league_title, bets_count, won, lost, void, win_rate, turnover, profit_uah, roi_pct.
    """
    bets = _to_records(settled_bets)
    valid_bets = [b for b in bets if b.get("status") in ("WON", "LOST", "VOID")]
    s_map = sports_map or {}

    grouped = {}
    for b in valid_bets:
        sp = b.get("sport") or "other"
        if sp not in grouped:
            grouped[sp] = {
                "sport": sp,
                "league_title": s_map.get(sp, sp),
                "bets_count": 0,
                "won": 0,
                "lost": 0,
                "void": 0,
                "turnover": 0.0,
                "profit_uah": 0.0,
            }
        g = grouped[sp]
        g["bets_count"] += 1
        st = b.get("status")
        if st == "WON":
            g["won"] += 1
        elif st == "LOST":
            g["lost"] += 1
        elif st == "VOID":
            g["void"] += 1

        g["turnover"] += float(b.get("stake_uah") or 0.0)
        g["profit_uah"] += float(b.get("profit_uah") or 0.0)

    res = []
    for sp, g in grouped.items():
        wl_sum = g["won"] + g["lost"]
        win_rate = (g["won"] / wl_sum * 100.0) if wl_sum > 0 else 0.0
        roi_pct = (g["profit_uah"] / g["turnover"] * 100.0) if g["turnover"] > 0 else 0.0
        res.append({
            "sport": sp,
            "league_title": g["league_title"],
            "bets_count": g["bets_count"],
            "won": g["won"],
            "lost": g["lost"],
            "void": g["void"],
            "win_rate": round(win_rate, 1),
            "turnover": round(g["turnover"], 2),
            "profit_uah": round(g["profit_uah"], 2),
            "roi_pct": round(roi_pct, 2),
        })

    # Сортуємо за прибутком за замовчуванням
    res.sort(key=lambda x: x["profit_uah"], reverse=True)
    return res

def calculate_market_breakdown(settled_bets):
    """
    Групує історію розрахованих ставок за типами маркетів (1X2, Тотали, Фори тощо):
    Повертає список словників: market_group, bets_count, won, lost, void, win_rate, turnover, profit_uah, roi_pct.
    """
    bets = _to_records(settled_bets)
    valid_bets = [b for b in bets if b.get("status") in ("WON", "LOST", "VOID")]

    grouped = {}
    for b in valid_bets:
        mkt = classify_market_group(b.get("pick_label"))
        if mkt not in grouped:
            grouped[mkt] = {
                "market_group": mkt,
                "bets_count": 0,
                "won": 0,
                "lost": 0,
                "void": 0,
                "turnover": 0.0,
                "profit_uah": 0.0,
            }
        g = grouped[mkt]
        g["bets_count"] += 1
        st = b.get("status")
        if st == "WON":
            g["won"] += 1
        elif st == "LOST":
            g["lost"] += 1
        elif st == "VOID":
            g["void"] += 1

        g["turnover"] += float(b.get("stake_uah") or 0.0)
        g["profit_uah"] += float(b.get("profit_uah") or 0.0)

    res = []
    for mkt, g in grouped.items():
        wl_sum = g["won"] + g["lost"]
        win_rate = (g["won"] / wl_sum * 100.0) if wl_sum > 0 else 0.0
        roi_pct = (g["profit_uah"] / g["turnover"] * 100.0) if g["turnover"] > 0 else 0.0
        res.append({
            "market_group": mkt,
            "bets_count": g["bets_count"],
            "won": g["won"],
            "lost": g["lost"],
            "void": g["void"],
            "win_rate": round(win_rate, 1),
            "turnover": round(g["turnover"], 2),
            "profit_uah": round(g["profit_uah"], 2),
            "roi_pct": round(roi_pct, 2),
        })

    res.sort(key=lambda x: x["profit_uah"], reverse=True)
    return res
