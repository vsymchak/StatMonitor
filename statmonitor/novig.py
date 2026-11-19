"""
StatMonitor - No-Vig Fair Odds & Quantitative Staking Engine (SPEC-34).
Розрахунок справедливих ймовірностей без маржі (de-vigging), відсікання -EV
та незалежний розрахунок ставок для реального банку (Independent Real Bank Staking).
"""

import math

def calculate_novig_2way(odds_1, odds_2):
    """
    Знімає маржу з 2-сторонньої лінії (тотали, фори, теніс, BTTS).
    Multiplicative De-vig метод.
    Повертає словник із чесними ймовірностями, чесними коефіцієнтами та маржею.
    """
    try:
        k1 = float(odds_1)
        k2 = float(odds_2)
        if k1 <= 1.01 or k2 <= 1.01:
            return None
    except (ValueError, TypeError):
        return None

    # Overround (сумарна ймовірність з маржею)
    s = (1.0 / k1) + (1.0 / k2)
    if s <= 0:
        return None

    p1_fair = (1.0 / k1) / s
    p2_fair = (1.0 / k2) / s

    fair_odds_1 = 1.0 / p1_fair if p1_fair > 0 else 0.0
    fair_odds_2 = 1.0 / p2_fair if p2_fair > 0 else 0.0
    margin_pct = (s - 1.0) * 100.0

    return {
        "fair_prob_1": round(p1_fair, 4),
        "fair_prob_2": round(p2_fair, 4),
        "fair_odds_1": round(fair_odds_1, 3),
        "fair_odds_2": round(fair_odds_2, 3),
        "overround": round(s, 4),
        "margin_pct": round(margin_pct, 2),
    }


def calculate_novig_3way(odds_1, odds_x, odds_2):
    """
    Знімає маржу з 3-сторонньої лінії (1X2 футбол).
    Повертає словник із чесними ймовірностями, коефіцієнтами та маржею.
    """
    try:
        k1 = float(odds_1)
        kx = float(odds_x)
        k2 = float(odds_2)
        if k1 <= 1.01 or kx <= 1.01 or k2 <= 1.01:
            return None
    except (ValueError, TypeError):
        return None

    s = (1.0 / k1) + (1.0 / kx) + (1.0 / k2)
    if s <= 0:
        return None

    p1 = (1.0 / k1) / s
    px = (1.0 / kx) / s
    p2 = (1.0 / k2) / s

    return {
        "fair_prob_1": round(p1, 4),
        "fair_prob_x": round(px, 4),
        "fair_prob_2": round(p2, 4),
        "fair_odds_1": round(1.0 / p1, 3) if p1 > 0 else 0.0,
        "fair_odds_x": round(1.0 / px, 3) if px > 0 else 0.0,
        "fair_odds_2": round(1.0 / p2, 3) if p2 > 0 else 0.0,
        "overround": round(s, 4),
        "margin_pct": round((s - 1.0) * 100.0, 2),
    }


def calculate_edge_and_ev(offered_odds, fair_prob):
    """
    Розраховує математичне очікування (EV) та Edge у відсотках:
    EV = (offered_odds * fair_prob) - 1.0
    edge_pct = EV * 100.0
    Повертає: (edge_pct, EV, is_positive_ev)
    """
    try:
        k = float(offered_odds)
        p = float(fair_prob)
        if k <= 1.0 or p <= 0.0 or p >= 1.0:
            return 0.0, 0.0, False
    except (ValueError, TypeError):
        return 0.0, 0.0, False

    ev = (k * p) - 1.0
    edge_pct = round(ev * 100.0, 2)
    return edge_pct, round(ev, 4), ev > 0


def calculate_walkaway_odds(fair_prob, min_edge=0.015):
    """
    Розраховує мінімально прийнятний коефіцієнт (Walkaway Odds):
    коефіцієнт, нижче якого ставка перестає давати мінімальну перевагу (+EV >= min_edge).
    k_min = (1.0 + min_edge) / fair_prob
    """
    try:
        p = float(fair_prob)
        if p <= 0.0 or p >= 1.0:
            return None
        min_e = float(min_edge)
        return round((1.0 + min_e) / p, 2)
    except (ValueError, TypeError):
        return None


def calculate_real_stake(
    odds,
    real_balance,
    fair_prob=None,
    drop_pct=None,
    confidence=None,
    fraction=0.10,
    min_stake=20.0,
    max_pct=0.05
):
    """
    Розраховує розмір ставки у гривнях строго від балансу РЕАЛЬНОГО банку (SPEC-34).
    Використовує ультра-консервативний дробовий Келлі (default: 0.10 * Kelly):
    
    Параметри:
    - odds: запропонований коефіцієнт у БК
    - real_balance: актуальний баланс реального банку з леджера
    - fair_prob: чесна ймовірність без маржі (якщо відома)
    - drop_pct: відсоток просідання лінії (fallback)
    - confidence: оцінка сили сигналу Gemini (1-10)
    - fraction: коефіцієнт Келлі для реального банку (за замовчуванням 0.10)
    - min_stake: мінімальна ставка в БК (за замовчуванням 20.0 ₴)
    - max_pct: максимальний ліміт ризику на одну ставку (за замовчуванням 5%)
    
    Повертає: (stake_uah, pct_of_real_bank, status_msg)
    """
    try:
        bal = float(real_balance or 0.0)
        k = float(odds or 0.0)
        if bal < min_stake:
            return 0.0, 0.0, f"Недостатній баланс реального банку ({bal:,.2f} ₴ < мін. {min_stake:,.0f} ₴). Потрібен депозит."
        if k <= 1.01:
            return 0.0, 0.0, "Неприпустимий коефіцієнт (<= 1.01)."
    except (ValueError, TypeError):
        return 0.0, 0.0, "Некоректні параметри коефіцієнта або балансу."

    b = k - 1.0

    # 1. Якщо передано de-vig fair_prob — рахуємо чистий математичний EV
    if fair_prob is not None:
        try:
            p = float(fair_prob)
            if 0.0 < p < 1.0:
                ev = (k * p) - 1.0
                if ev <= 0:
                    return 0.0, 0.0, f"Ставка не має математичної переваги (EV: {ev*100:+.2f}%, p_fair: {p:.3f})."
                full_kelly = ev / b
            else:
                full_kelly = 0.02 / b
        except (ValueError, TypeError):
            full_kelly = 0.02 / b
    else:
        # 2. Fallback оцінка Edge на основі сили прогрузу та Confidence
        d = min(float(drop_pct or 0.0), 30.0)
        edge = 0.02 + (d / 100.0) * 0.18
        if confidence is not None:
            c = max(1.0, min(10.0, float(confidence)))
            edge *= (0.6 + (c / 10.0) * 0.4)
        full_kelly = edge / b

    # 3. Дробовий консервативний Келлі для реального банку
    frac_k = full_kelly * float(fraction)
    # Межі для реальних грошей: від 1% до max_pct (за замовчуванням 5%)
    clamped_pct = max(0.01, min(float(max_pct), frac_k))

    # 4. Розрахунок номіналу ставки та округлення до красивих круглих сум
    raw_stake = clamped_pct * bal

    # Округлюємо: для суми до 100 грн — до 5 грн, вище — до 10 грн
    if raw_stake < 100.0:
        stake = round(raw_stake / 5.0) * 5.0
    else:
        stake = round(raw_stake / 10.0) * 10.0

    # Захисні межі ставки
    stake = max(min_stake, stake)
    max_allowed = round(bal * float(max_pct), 2)
    if stake > max_allowed:
        stake = max_allowed
    if stake > bal:
        stake = bal

    actual_pct = round((stake / bal) * 100.0, 1)
    return round(stake, 2), actual_pct, "OK"
