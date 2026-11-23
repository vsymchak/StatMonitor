import math
import random

# Initial conditions
initial_bank = 10000.0
days = 38 # from 23.11.2026 to 31.12.2026

# Historical performance for Conf >= 8 over 4.2 days:
# Variant A: Range 1.50 - 2.40
# 21 bets in 4.2 days -> 5.0 bets/day -> 190 bets in 38 days
# Net profit: +1,013.80 UAH on 10k bank -> +10.14% in 4.2 days
daily_growth_A = (1 + 1013.80 / 10000.0) ** (1 / 4.2) - 1.0 # ~2.30% per day

# Variant B: Range 1.50 - 2.80
# 22 bets in 4.2 days -> 5.2 bets/day -> 198 bets in 38 days
# Net profit: +866.60 UAH on 10k bank -> +8.67% in 4.2 days
daily_growth_B = (1 + 866.60 / 10000.0) ** (1 / 4.2) - 1.0 # ~1.98% per day

# Variant C: Conservative / Regression to Mean (Long-term EV)
# Assuming Win Rate 60%, Avg Odds 1.95, Kelly 0.10x -> Avg stake ~2.2% of bank
# Daily volume: 4.5 bets * 2.2% = ~10% daily turnover
# Long-term conservative ROI = +12.0%
# Daily growth = 10% * 12% = +1.20% per day
daily_growth_C = 0.0120

print(f"=== Проекція зростання капіталу з 10 000 ₴ до 31.12.2026 (38 днів) ===")
bank_A = initial_bank * ((1.0 + daily_growth_A) ** days)
bank_B = initial_bank * ((1.0 + daily_growth_B) ** days)
bank_C = initial_bank * ((1.0 + daily_growth_C) ** days)

print(f"1. Оптимальний сценарій (діапазон 1.50 - 2.40, +{daily_growth_A*100:.2f}%/день): {bank_A:,.2f} ₴ (Прибуток: +{bank_A-initial_bank:,.2f} ₴, x{bank_A/initial_bank:.2f})")
print(f"2. Робочий сценарій (діапазон 1.50 - 2.80, +{daily_growth_B*100:.2f}%/день): {bank_B:,.2f} ₴ (Прибуток: +{bank_B-initial_bank:,.2f} ₴, x{bank_B/initial_bank:.2f})")
print(f"3. Консервативний сценарій (з регресією до середнього, +{daily_growth_C*100:.2f}%/день): {bank_C:,.2f} ₴ (Прибуток: +{bank_C-initial_bank:,.2f} ₴, x{bank_C/initial_bank:.2f})")

# Monte Carlo simulation (10,000 iterations) for Variant A (Range 1.50 - 2.40)
# Historical sample: 14 WON, 7 LOST
# Avg win multiplier ~ 1.95 - 1.0 = +0.95, Kelly stake ~2.0%
mc_runs = 10000
mc_results = []
random.seed(42)

# Odds distribution from the 21 bets
hist_w_odds = [1.60, 1.62, 1.75, 1.75, 1.82, 1.87, 1.88, 1.92, 1.94, 1.99, 2.02, 2.10, 2.19, 2.24]
hist_l_odds = [1.82, 1.82, 1.83, 1.83, 1.92, 2.12, 2.30]

for _ in range(mc_runs):
    cur_b = 10000.0
    for _ in range(190): # 190 bets over 38 days
        # Sample an outcome based on historical frequency (14/21 = 66.7%)
        is_win = random.random() < (14.0 / 21.0)
        k = random.choice(hist_w_odds) if is_win else random.choice(hist_l_odds)
        # 0.10x Kelly stake with 20 UAH min and 5% cap
        edge = 0.08
        b_dec = k - 1.0
        stk_pct = max(0.01, min(0.05, (edge / b_dec) * 0.10))
        stake = round(cur_b * stk_pct)
        if stake < 20: stake = 20
        if is_win:
            cur_b += stake * (k - 1.0)
        else:
            cur_b -= stake
    mc_results.append(cur_b)

mc_results.sort()
p10 = mc_results[int(mc_runs * 0.10)]
p50 = mc_results[int(mc_runs * 0.50)]
p90 = mc_results[int(mc_runs * 0.90)]

print(f"\n=== Результати Монте-Карло симуляції (10 000 ітерацій, 190 ставок) ===")
print(f"P10 (Песимістичний сценарій, 90% ймовірність бути вище): {p10:,.2f} ₴")
print(f"P50 (Медіанний очікуваний баланс): {p50:,.2f} ₴")
print(f"P90 (Оптимістичний сценарій при сприятливій дисперсії): {p90:,.2f} ₴")
