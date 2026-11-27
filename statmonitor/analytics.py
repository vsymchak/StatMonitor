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
    if any(k in lbl for k in ("тотал", "більше", "менше", "over", "under")) or re.search(r"(?:^|[\s(])(?:тб|тм)(?:[\s()\d.]|$)", lbl):
        return "Тотали"
    if any(k in lbl for k in ("фора", "handicap", "spread")) or re.search(r"(?:ф[12]\s*\(?[+-]|\([+-]\d+(?:[.,]\d+)?\))", lbl):
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


def calculate_counterfactual_audit(bets):
    """
    SPEC-35: Розрахунок метрик контрфактичного аудиту для порівняння
    активних ставок (AI Confidence >= 8 · Золотий стандарт) проти відсіяних Shadow-ставок (Confidence < 8 або Skip).
    
    Повертає словник:
    - live: {total, won, lost, void, pending, turnover, profit, roi_pct, win_rate}
    - shadow: {total, won, lost, void, pending, turnover, profit, roi_pct, win_rate}
    - combined: {total, won, lost, void, turnover, profit, roi_pct, win_rate} (гіпотеза без фільтрації)
    - value_add: {delta_roi_pct, delta_win_rate, capital_saved_uah, verdict}
    """
    records = _to_records(bets)
    if not records:
        return {
            "live": {"total": 0, "won": 0, "lost": 0, "void": 0, "pending": 0, "turnover": 0.0, "profit": 0.0, "roi_pct": 0.0, "win_rate": 0.0},
            "shadow": {"total": 0, "won": 0, "lost": 0, "void": 0, "pending": 0, "turnover": 0.0, "profit": 0.0, "roi_pct": 0.0, "win_rate": 0.0},
            "combined": {"total": 0, "won": 0, "lost": 0, "void": 0, "turnover": 0.0, "profit": 0.0, "roi_pct": 0.0, "win_rate": 0.0},
            "value_add": {"delta_roi_pct": 0.0, "delta_win_rate": 0.0, "capital_saved_uah": 0.0, "verdict": "INSUFFICIENT_DATA"}
        }

    # 1. Розділення на Live та Shadow
    live_settled = []
    live_pending = 0
    shadow_settled = []
    shadow_pending = 0

    for b in records:
        is_sh = bool(b.get("is_shadow")) or b.get("status") == "FILTERED"
        st = str(b.get("status") or "").upper()
        sh_st = str(b.get("shadow_status") or "").upper()

        if is_sh:
            if sh_st in ("WON", "LOST", "VOID"):
                shadow_settled.append(b)
            elif sh_st == "PENDING" or st == "FILTERED":
                shadow_pending += 1
        else:
            if st in ("WON", "LOST", "VOID"):
                live_settled.append(b)
            elif st == "PENDING":
                live_pending += 1

    # 2. Метрики Live
    l_won = sum(1 for b in live_settled if str(b.get("status")).upper() == "WON")
    l_lost = sum(1 for b in live_settled if str(b.get("status")).upper() == "LOST")
    l_void = sum(1 for b in live_settled if str(b.get("status")).upper() == "VOID")
    l_tot = l_won + l_lost + l_void
    l_turnover = sum(float(b.get("stake_uah") or 0.0) for b in live_settled)
    l_profit = sum(float(b.get("profit_uah") or 0.0) for b in live_settled)
    l_roi = round((l_profit / l_turnover * 100.0), 2) if l_turnover > 0 else 0.0
    l_win_rate = round((l_won / (l_won + l_lost) * 100.0), 1) if (l_won + l_lost) > 0 else 0.0

    # 3. Метрики Shadow
    s_won = sum(1 for b in shadow_settled if str(b.get("shadow_status") or b.get("status")).upper() in ("WON", "FILTERED_WON"))
    s_lost = sum(1 for b in shadow_settled if str(b.get("shadow_status") or b.get("status")).upper() in ("LOST", "FILTERED_LOST"))
    s_void = sum(1 for b in shadow_settled if str(b.get("shadow_status") or b.get("status")).upper() in ("VOID", "FILTERED_VOID"))
    s_tot = s_won + s_lost + s_void
    s_turnover = sum(float(b.get("stake_uah") or 0.0) for b in shadow_settled)
    s_profit = sum(float(b.get("shadow_profit_uah") or b.get("profit_uah") or 0.0) for b in shadow_settled)
    s_roi = round((s_profit / s_turnover * 100.0), 2) if s_turnover > 0 else 0.0
    s_win_rate = round((s_won / (s_won + s_lost) * 100.0), 1) if (s_won + s_lost) > 0 else 0.0

    # 4. Комбінована модель (без фільтрації)
    c_tot = l_tot + s_tot
    c_won = l_won + s_won
    c_lost = l_lost + s_lost
    c_void = l_void + s_void
    c_turnover = l_turnover + s_turnover
    c_profit = l_profit + s_profit
    c_roi = round((c_profit / c_turnover * 100.0), 2) if c_turnover > 0 else 0.0
    c_win_rate = round((c_won / (c_won + c_lost) * 100.0), 1) if (c_won + c_lost) > 0 else 0.0

    # 5. Оцінка доданої вартості ШІ (Alpha)
    delta_roi = round(l_roi - s_roi, 2)
    delta_win_rate = round(l_win_rate - s_win_rate, 1)
    capital_saved = round(-s_profit, 2)

    if s_tot < 3:
        verdict = "INSUFFICIENT_DATA"
    elif delta_roi > 2.0 or capital_saved > 0:
        verdict = "POSITIVE"
    elif delta_roi < -2.0 and s_profit > 0:
        verdict = "NEGATIVE"
    else:
        verdict = "NEUTRAL"

    return {
        "live": {
            "total": l_tot, "won": l_won, "lost": l_lost, "void": l_void, "pending": live_pending,
            "turnover": l_turnover, "profit": l_profit, "roi_pct": l_roi, "win_rate": l_win_rate,
        },
        "shadow": {
            "total": s_tot, "won": s_won, "lost": s_lost, "void": s_void, "pending": shadow_pending,
            "turnover": s_turnover, "profit": s_profit, "roi_pct": s_roi, "win_rate": s_win_rate,
        },
        "combined": {
            "total": c_tot, "won": c_won, "lost": c_lost, "void": c_void,
            "turnover": c_turnover, "profit": c_profit, "roi_pct": c_roi, "win_rate": c_win_rate,
        },
        "value_add": {
            "delta_roi_pct": delta_roi,
            "delta_win_rate": delta_win_rate,
            "capital_saved_uah": capital_saved,
            "verdict": verdict,
        }
    }


def calculate_confidence_calibration(bets):
    """
    SPEC-35 & SPEC-41: Калібровка AI Confidence Score та Brier Score Dashboard:
    - 1-4: Слабкі сигнали / Пропуск
    - 5-6: Сумнівні / Відсіяні
    - 7-8: Стандартний валуй (прохідний поріг)
    - 9-10: Висока впевненість
    
    Для кожного бакета рахується Win Rate, ROI %, середній CLV %, Brier Score,
    а також розраховується Expected Calibration Error (ECE), Brier Skill Score (BSS)
    та детальна сегментація за окремими оцінками 1-10.
    """
    records = _to_records(bets)
    buckets = {
        "1-4": {"name": "1-4 (Слабкі / Пропуск)", "range": (1, 4), "midpoint": 2.5, "bets": []},
        "5-6": {"name": "5-6 (Сумнівні / Відсіяні)", "range": (5, 6), "midpoint": 5.5, "bets": []},
        "7-8": {"name": "7-8 (Стандартний валуй)", "range": (7, 8), "midpoint": 7.5, "bets": []},
        "9-10": {"name": "9-10 (Висока впевненість)", "range": (9, 10), "midpoint": 9.5, "bets": []},
    }

    granular_dict = {i: [] for i in range(1, 11)}

    for b in records:
        conf = b.get("confidence_score")
        if conf is None:
            continue
        try:
            c_val = int(conf)
        except (ValueError, TypeError):
            continue

        if 1 <= c_val <= 10:
            granular_dict[c_val].append(b)

        for b_key, b_data in buckets.items():
            low, high = b_data["range"]
            if low <= c_val <= high:
                b_data["bets"].append(b)
                break

    results = []
    total_squared_errors = []
    all_decided_preds = []
    all_decided_actuals = []

    for b_key in ["1-4", "5-6", "7-8", "9-10"]:
        b_data = buckets[b_key]
        b_bets = b_data["bets"]

        settled = []
        for b in b_bets:
            is_sh = bool(b.get("is_shadow")) or b.get("status") == "FILTERED"
            res = (b.get("shadow_status") if is_sh else b.get("status")) or ""
            if str(res).upper() in ("WON", "LOST", "VOID"):
                settled.append((b, str(res).upper(), is_sh))

        won = sum(1 for _, res, _ in settled if res == "WON")
        lost = sum(1 for _, res, _ in settled if res == "LOST")
        void = sum(1 for _, res, _ in settled if res == "VOID")
        tot = won + lost + void

        turnover = sum(float(b.get("stake_uah") or 0.0) for b, _, _ in settled)
        profit = sum(
            float(b.get("shadow_profit_uah") if is_sh else b.get("profit_uah") or 0.0)
            for b, _, is_sh in settled
        )
        roi = round((profit / turnover * 100.0), 2) if turnover > 0 else 0.0
        win_rate = round((won / (won + lost) * 100.0), 1) if (won + lost) > 0 else 0.0

        clvs = [float(b.get("clv_pct")) for b, _, _ in settled if b.get("clv_pct") is not None]
        avg_clv = round(sum(clvs) / len(clvs), 2) if clvs else 0.0

        brier_bucket = []
        pred_probs = []
        for b, res, _ in settled:
            if res in ("WON", "LOST"):
                p_est = min(1.0, max(0.0, float(b.get("confidence_score") or 5) / 10.0))
                actual = 1.0 if res == "WON" else 0.0
                sq_err = (p_est - actual) ** 2
                brier_bucket.append(sq_err)
                total_squared_errors.append(sq_err)
                all_decided_preds.append(p_est)
                all_decided_actuals.append(actual)
                pred_probs.append(p_est * 100.0)

        bucket_brier = round(sum(brier_bucket) / len(brier_bucket), 4) if brier_bucket else None
        avg_pred_wr = round(sum(pred_probs) / len(pred_probs), 1) if pred_probs else round(b_data["midpoint"] * 10.0, 1)
        cal_diff = round(win_rate - avg_pred_wr, 1) if (won + lost) > 0 else 0.0

        results.append({
            "bucket": b_key,
            "label": b_data["name"],
            "total_bets": tot,
            "won": won,
            "lost": lost,
            "void": void,
            "win_rate": win_rate,
            "expected_win_rate": avg_pred_wr,
            "calibration_gap": cal_diff,
            "roi_pct": roi,
            "turnover": turnover,
            "profit": profit,
            "avg_clv_pct": avg_clv,
            "brier_score": bucket_brier,
        })

    # Granular scores 1..10 breakdown
    granular_results = []
    for score in range(1, 11):
        s_bets = granular_dict[score]
        settled_s = []
        for b in s_bets:
            is_sh = bool(b.get("is_shadow")) or b.get("status") == "FILTERED"
            res = (b.get("shadow_status") if is_sh else b.get("status")) or ""
            if str(res).upper() in ("WON", "LOST", "VOID"):
                settled_s.append((b, str(res).upper(), is_sh))

        won_s = sum(1 for _, res, _ in settled_s if res == "WON")
        lost_s = sum(1 for _, res, _ in settled_s if res == "LOST")
        void_s = sum(1 for _, res, _ in settled_s if res == "VOID")
        tot_s = won_s + lost_s + void_s

        turnover_s = sum(float(b.get("stake_uah") or 0.0) for b, _, _ in settled_s)
        profit_s = sum(
            float(b.get("shadow_profit_uah") if is_sh else b.get("profit_uah") or 0.0)
            for b, _, is_sh in settled_s
        )
        roi_s = round((profit_s / turnover_s * 100.0), 2) if turnover_s > 0 else 0.0
        win_rate_s = round((won_s / (won_s + lost_s) * 100.0), 1) if (won_s + lost_s) > 0 else 0.0

        clvs_s = [float(b.get("clv_pct")) for b, _, _ in settled_s if b.get("clv_pct") is not None]
        avg_clv_s = round(sum(clvs_s) / len(clvs_s), 2) if clvs_s else 0.0

        brier_s = []
        for b, res, _ in settled_s:
            if res in ("WON", "LOST"):
                p_est = score / 10.0
                actual = 1.0 if res == "WON" else 0.0
                brier_s.append((p_est - actual) ** 2)

        score_brier = round(sum(brier_s) / len(brier_s), 4) if brier_s else None
        expected_wr_s = round(score * 10.0, 1)

        granular_results.append({
            "score": score,
            "label": f"★ {score}/10",
            "total_bets": tot_s,
            "won": won_s,
            "lost": lost_s,
            "void": void_s,
            "win_rate": win_rate_s,
            "expected_win_rate": expected_wr_s,
            "calibration_gap": round(win_rate_s - expected_wr_s, 1) if (won_s + lost_s) > 0 else 0.0,
            "roi_pct": roi_s,
            "turnover": turnover_s,
            "profit": profit_s,
            "avg_clv_pct": avg_clv_s,
            "brier_score": score_brier,
        })

    overall_brier = round(sum(total_squared_errors) / len(total_squared_errors), 4) if total_squared_errors else None

    # Expected Calibration Error (ECE) across active buckets
    total_decided = len(all_decided_actuals)
    if total_decided > 0:
        ece_acc = 0.0
        for b in results:
            decided_b = b["won"] + b["lost"]
            if decided_b > 0:
                gap = abs(b["win_rate"] - b["expected_win_rate"]) / 100.0
                ece_acc += (decided_b / total_decided) * gap
        ece = round(ece_acc, 4)
        ece_pct = round(ece_acc * 100.0, 2)
    else:
        ece = None
        ece_pct = None

    # Brier Skill Score (BSS) vs Climatological reference
    if total_decided > 0 and overall_brier is not None:
        p_base = sum(all_decided_actuals) / total_decided
        brier_ref = p_base * (1.0 - p_base)
        if brier_ref > 0.0001:
            bss = round((1.0 - (overall_brier / brier_ref)) * 100.0, 2)
        else:
            bss = 0.0
    else:
        bss = None

    # Verdict
    if total_decided < 3 or overall_brier is None or ece_pct is None:
        verdict = "INSUFFICIENT_DATA"
        verdict_label = "Недостатньо розрахованих даних (<3 ставок)"
    elif ece_pct <= 10.0:
        verdict = "EXCELLENT"
        verdict_label = f"Відмінне калібрування (ECE {ece_pct:.1f}%)"
    elif ece_pct <= 20.0:
        verdict = "GOOD"
        verdict_label = f"Добре калібрування (ECE {ece_pct:.1f}%)"
    else:
        avg_pred = sum(all_decided_preds) / total_decided
        avg_act = sum(all_decided_actuals) / total_decided
        if avg_pred > avg_act:
            verdict = "OVERCONFIDENT"
            verdict_label = f"Надмірна впевненість ШІ (ECE {ece_pct:.1f}%)"
        else:
            verdict = "UNDERCONFIDENT"
            verdict_label = f"Занижена впевненість ШІ (ECE {ece_pct:.1f}%)"

    return {
        "buckets": results,
        "granular_scores": granular_results,
        "overall_brier_score": overall_brier,
        "expected_calibration_error": ece,
        "ece_pct": ece_pct,
        "brier_skill_score": bss,
        "calibration_verdict": verdict,
        "calibration_verdict_label": verdict_label,
        "total_evaluated_bets": total_decided,
    }

