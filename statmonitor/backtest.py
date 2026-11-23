"""
StatMonitor - Quantitative Backtest Engine (SPEC-42).
Хронологічна симуляційна платформа для тестування стратегій управління капіталом
(Kelly vs Flat vs % of Bank), оцінки ризиків (Max Drawdown, Sharpe, Sortino)
та контрфактичного аналізу ШІ-фільтрації.
"""

import math
import re
from datetime import datetime
from statmonitor.novig import calculate_real_stake
from statmonitor.config import DEFAULT_MIN_CONFIDENCE

def _to_records(data):
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        return data.to_dict(orient="records")
    if isinstance(data, list):
        return [dict(d) if isinstance(d, dict) else d for d in data]
    return list(data)

def calculate_sharpe_ratio(returns_list, risk_free_rate=0.0):
    """
    Обчислює коефіцієнт Шарпа на основі процентних прибутків/збитків на ставку.
    """
    if not returns_list or len(returns_list) < 2:
        return 0.0
    
    n = len(returns_list)
    mean_ret = sum(returns_list) / n
    excess_mean = mean_ret - risk_free_rate
    
    var = sum((r - mean_ret) ** 2 for r in returns_list) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    
    if std == 0.0:
        return 0.0
    return round(excess_mean / std, 3)

def calculate_sortino_ratio(returns_list, risk_free_rate=0.0):
    """
    Обчислює коефіцієнт Сортіно (ризик тільки негативної волатильності).
    """
    if not returns_list or len(returns_list) < 2:
        return 0.0
    
    n = len(returns_list)
    mean_ret = sum(returns_list) / n
    excess_mean = mean_ret - risk_free_rate
    
    downside_sq = sum(min(0.0, r - risk_free_rate) ** 2 for r in returns_list)
    downside_std = math.sqrt(downside_sq / (n - 1)) if downside_sq > 0 else 0.0
    
    if downside_std == 0.0:
        return 0.0
    return round(excess_mean / downside_std, 3)

def run_backtest(bets_data, config=None):
    """
    Головний кількісний симулятор бектесту (SPEC-42).
    
    Параметри конфігурації (config):
    - initial_bankroll: float (дефолт: 10,000 ₴)
    - staking_model: 'KELLY_FRACTION' | 'FLAT' | 'PERCENT_BANK'
    - fraction: float (дефолт: 0.10 для Kelly)
    - flat_amount: float (дефолт: 100.0 ₴)
    - percent_bank: float (дефолт: 0.02, тобто 2%)
    - min_confidence: int (дефолт: 8, Золотий стандарт якості ШІ)
    - min_odds: float (дефолт: 1.10)
    - max_odds: float (дефолт: 10.00)
    - include_shadow: bool (дефолт: False)
    - enforce_walkaway: bool (дефолт: False)
    - selected_sports: list[str] | None
    - min_stake_uah: float (дефолт: 20.0 ₴)
    - max_stake_cap_pct: float (дефолт: 0.05, тобто 5%)
    """
    cfg = config or {}
    initial_bankroll = float(cfg.get("initial_bankroll", 10000.0))
    staking_model = str(cfg.get("staking_model", "KELLY_FRACTION")).upper()
    fraction = float(cfg.get("fraction", 0.10))
    flat_amount = float(cfg.get("flat_amount", 100.0))
    percent_bank = float(cfg.get("percent_bank", 0.02))
    min_confidence = int(cfg.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
    min_odds = float(cfg.get("min_odds", 1.10))
    max_odds = float(cfg.get("max_odds", 10.00))
    include_shadow = bool(cfg.get("include_shadow", False))
    enforce_walkaway = bool(cfg.get("enforce_walkaway", False))
    selected_sports = cfg.get("selected_sports")
    min_stake_uah = float(cfg.get("min_stake_uah", 20.0))
    max_stake_cap_pct = float(cfg.get("max_stake_cap_pct", 0.05))

    raw_records = _to_records(bets_data)
    if not raw_records:
        return _empty_backtest_result(initial_bankroll)

    # 1. Відбір та фільтрація ставок
    filtered_bets = []
    skipped_count = 0

    for b in raw_records:
        # Статус ставки
        st = str(b.get("status", "")).upper()
        sh_st = str(b.get("shadow_status", "")).upper()
        is_sh = bool(b.get("is_shadow", False) or st == "FILTERED")

        # Перевірка на розрахованість (Settled)
        resolved_status = None
        if is_sh:
            if not include_shadow:
                skipped_count += 1
                continue
            # Для Shadow-ставок статус дивимося в shadow_status
            if sh_st in ("WON", "LOST", "VOID"):
                resolved_status = sh_st
            elif st in ("WON", "LOST", "VOID"):
                resolved_status = st
        else:
            if st in ("WON", "LOST", "VOID"):
                resolved_status = st

        if not resolved_status:
            skipped_count += 1
            continue

        # Фільтр за коефіцієнтом
        try:
            k = float(b.get("odds", 0.0) or 0.0)
        except (ValueError, TypeError):
            skipped_count += 1
            continue
        
        if k < min_odds or k > max_odds:
            skipped_count += 1
            continue

        # Фільтр за силою сигналу (Confidence Score)
        c_score = b.get("confidence_score")
        if c_score is not None:
            try:
                c_val = int(c_score)
                if c_val < min_confidence:
                    skipped_count += 1
                    continue
            except (ValueError, TypeError):
                pass
        else:
            # Якщо оцінка відсутня, пропускаємо при строгому фільтрі >= 7
            if min_confidence > 0 and not is_sh:
                # Зберігаємо старі ставки без оцінки тільки якщо min_confidence <= 5
                if min_confidence > 5:
                    skipped_count += 1
                    continue

        # Фільтр за Walkaway Odds (+EV)
        if enforce_walkaway:
            w_odds = b.get("walkaway_odds")
            if w_odds is not None:
                try:
                    w_val = float(w_odds)
                    if k < w_val:
                        skipped_count += 1
                        continue
                except (ValueError, TypeError):
                    pass

        # Фільтр за видами спорту
        if selected_sports:
            sp = b.get("sport")
            if sp and sp not in selected_sports:
                skipped_count += 1
                continue

        # Формуємо нормалізований об'єкт
        clean_item = dict(b)
        clean_item["_sim_status"] = resolved_status
        clean_item["_sim_odds"] = k

        # Час для хронологічного сортування
        c_time = b.get("settled_at") or b.get("commence_time") or b.get("created_at") or ""
        clean_item["_sort_time"] = str(c_time)
        clean_item["_id"] = b.get("id", 0)

        filtered_bets.append(clean_item)

    if not filtered_bets:
        return _empty_backtest_result(initial_bankroll, skipped_count=skipped_count)

    # 2. Хронологічне сортування
    filtered_bets.sort(key=lambda x: (x["_sort_time"], x["_id"]))

    # 3. Покрокова симуляція капіталу
    current_bank = initial_bankroll
    peak_bank = initial_bankroll
    max_dd_uah = 0.0
    max_dd_pct = 0.0

    equity_curve = [{
        "step": 0,
        "balance": round(current_bank, 2),
        "drawdown_pct": 0.0,
        "drawdown_uah": 0.0,
        "pnl": 0.0,
        "stake": 0.0,
        "odds": 0.0,
        "status": "START",
        "match": "Start of simulation",
        "time": filtered_bets[0]["_sort_time"] if filtered_bets else ""
    }]

    executed_bets = []
    trade_returns = [] # для Sharpe / Sortino

    won_cnt = 0
    lost_cnt = 0
    void_cnt = 0
    gross_wins = 0.0
    gross_losses = 0.0
    total_turnover = 0.0

    curr_win_streak = 0
    max_win_streak = 0
    curr_loss_streak = 0
    max_loss_streak = 0

    for idx, bet in enumerate(filtered_bets, 1):
        # Якщо збанкрутували
        if current_bank < min_stake_uah:
            # Зупинка симуляції через брак капіталу
            break

        k = bet["_sim_odds"]
        st = bet["_sim_status"]

        # Розрахунок розміру ставки залежно від моделі
        if staking_model == "FLAT":
            stake = min(current_bank, flat_amount)
        elif staking_model == "PERCENT_BANK":
            raw_s = current_bank * percent_bank
            stake = max(min_stake_uah, min(current_bank * max_stake_cap_pct, raw_s))
        else: # KELLY_FRACTION (за замовчуванням)
            k_pct = bet.get("kelly_pct")
            stk_calc, _, _ = calculate_real_stake(
                odds=k,
                real_balance=current_bank,
                kelly_pct=k_pct,
                fraction=fraction,
                min_stake=min_stake_uah,
                max_pct=max_stake_cap_pct
            )
            stake = min(current_bank, stk_calc if stk_calc > 0 else min_stake_uah)

        # Округлення до цілої гривні
        stake = float(round(stake))
        if stake < min_stake_uah:
            stake = min_stake_uah
        if stake > current_bank:
            stake = float(math.floor(current_bank))

        # Розрахунок PnL угоди
        if st == "WON":
            pnl = round(stake * (k - 1.0), 2)
            won_cnt += 1
            gross_wins += pnl
            curr_win_streak += 1
            max_win_streak = max(max_win_streak, curr_win_streak)
            curr_loss_streak = 0
            ret = (k - 1.0) * (stake / current_bank)
        elif st == "LOST":
            pnl = -round(stake, 2)
            lost_cnt += 1
            gross_losses += abs(pnl)
            curr_loss_streak += 1
            max_loss_streak = max(max_loss_streak, curr_loss_streak)
            curr_win_streak = 0
            ret = -(stake / current_bank)
        else: # VOID
            pnl = 0.0
            void_cnt += 1
            ret = 0.0

        current_bank = round(current_bank + pnl, 2)
        total_turnover += stake
        trade_returns.append(ret)

        # Drawdown розрахунок
        if current_bank > peak_bank:
            peak_bank = current_bank
        dd_uah = round(peak_bank - current_bank, 2)
        dd_pct = round((dd_uah / peak_bank) * 100.0, 2) if peak_bank > 0 else 0.0

        if dd_uah > max_dd_uah:
            max_dd_uah = dd_uah
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        step_record = {
            "step": idx,
            "id": bet.get("id"),
            "match": bet.get("match_name", ""),
            "pick": bet.get("pick_label", ""),
            "sport": bet.get("sport", ""),
            "odds": k,
            "stake": stake,
            "status": st,
            "pnl": pnl,
            "balance": current_bank,
            "peak": peak_bank,
            "drawdown_pct": dd_pct,
            "drawdown_uah": dd_uah,
            "time": bet["_sort_time"]
        }
        equity_curve.append(step_record)
        executed_bets.append(step_record)

    # 4. Підсумкові метрики
    total_trades = won_cnt + lost_cnt + void_cnt
    net_profit = round(current_bank - initial_bankroll, 2)
    roi_pct = round((net_profit / total_turnover) * 100.0, 2) if total_turnover > 0 else 0.0
    cagr_pct = round((net_profit / initial_bankroll) * 100.0, 2)
    resolved_count = won_cnt + lost_cnt
    win_rate = round((won_cnt / resolved_count) * 100.0, 1) if resolved_count > 0 else 0.0
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)
    sharpe = calculate_sharpe_ratio(trade_returns)
    sortino = calculate_sortino_ratio(trade_returns)

    avg_stake = round(total_turnover / total_trades, 1) if total_trades > 0 else 0.0
    avg_odds = round(sum(b["odds"] for b in executed_bets) / total_trades, 2) if total_trades > 0 else 0.0

    metrics = {
        "initial_bankroll": initial_bankroll,
        "final_balance": current_bank,
        "net_profit": net_profit,
        "cagr_pct": cagr_pct,
        "roi_pct": roi_pct,
        "total_turnover": round(total_turnover, 2),
        "total_trades": total_trades,
        "won_count": won_cnt,
        "lost_count": lost_cnt,
        "void_count": void_cnt,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_dd_pct,
        "max_drawdown_uah": max_dd_uah,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "avg_stake": avg_stake,
        "avg_odds": avg_odds,
        "skipped_count": skipped_count
    }

    return {
        "config": cfg,
        "metrics": metrics,
        "equity_curve": equity_curve,
        "executed_bets": executed_bets,
        "skipped_count": skipped_count
    }

def _empty_backtest_result(initial_bankroll, skipped_count=0):
    return {
        "config": {},
        "metrics": {
            "initial_bankroll": initial_bankroll,
            "final_balance": initial_bankroll,
            "net_profit": 0.0,
            "cagr_pct": 0.0,
            "roi_pct": 0.0,
            "total_turnover": 0.0,
            "total_trades": 0,
            "won_count": 0,
            "lost_count": 0,
            "void_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_uah": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "avg_stake": 0.0,
            "avg_odds": 0.0,
            "skipped_count": skipped_count
        },
        "equity_curve": [{
            "step": 0,
            "balance": initial_bankroll,
            "drawdown_pct": 0.0,
            "drawdown_uah": 0.0,
            "pnl": 0.0,
            "stake": 0.0,
            "odds": 0.0,
            "status": "START",
            "match": "No data",
            "time": ""
        }],
        "executed_bets": [],
        "skipped_count": skipped_count
    }

def run_benchmark_comparison(bets_data, initial_bank=10000.0):
    """
    Генерує мультистратегічне порівняння 5 стандартних квантитативних бенчмарків (SPEC-42).
    """
    benchmarks = [
        {
            "name": "1. Live Real (0.10x Kelly, Conf ≥ 8 · Золотий стандарт)",
            "cfg": {
                "initial_bankroll": initial_bank,
                "staking_model": "KELLY_FRACTION",
                "fraction": 0.10,
                "min_confidence": 8,
                "include_shadow": False
            }
        },
        {
            "name": "2. Aggressive Kelly (0.25x Kelly, Conf ≥ 8)",
            "cfg": {
                "initial_bankroll": initial_bank,
                "staking_model": "KELLY_FRACTION",
                "fraction": 0.25,
                "min_confidence": 8,
                "include_shadow": False
            }
        },
        {
            "name": "3. Conservative Flat (100 ₴, Conf ≥ 8)",
            "cfg": {
                "initial_bankroll": initial_bank,
                "staking_model": "FLAT",
                "flat_amount": 100.0,
                "min_confidence": 8,
                "include_shadow": False
            }
        },
        {
            "name": "4. No-AI Baseline (0.10x Kelly, Всі ставки)",
            "cfg": {
                "initial_bankroll": initial_bank,
                "staking_model": "KELLY_FRACTION",
                "fraction": 0.10,
                "min_confidence": 0,
                "include_shadow": True
            }
        },
        {
            "name": "5. Elite EV (0.10x Kelly, Conf ≥ 9, Walkaway)",
            "cfg": {
                "initial_bankroll": initial_bank,
                "staking_model": "KELLY_FRACTION",
                "fraction": 0.10,
                "min_confidence": 9,
                "enforce_walkaway": True,
                "include_shadow": False
            }
        }
    ]

    results = []
    for b in benchmarks:
        res = run_backtest(bets_data, b["cfg"])
        m = res["metrics"]
        results.append({
            "Стратегія": b["name"],
            "Ставок": m["total_trades"],
            "Win Rate": f"{m['win_rate']:.1f}%",
            "Чистий прибуток": f"{m['net_profit']:+,.2f} ₴",
            "Прибуток (число)": m["net_profit"],
            "ROI": f"{m['roi_pct']:+.2f}%",
            "Max Drawdown": f"{m['max_drawdown_pct']:.1f}%",
            "Max DD (число)": m["max_drawdown_pct"],
            "Profit Factor": f"{m['profit_factor']:.2f}",
            "Sharpe Ratio": f"{m['sharpe_ratio']:.2f}",
            "Баланс": f"{m['final_balance']:,.0f} ₴"
        })

    return results
