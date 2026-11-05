# Handbook swing backtest — post-mortem

As-written run: 2020-01-01 → 2026-10-09, ₹5 lakh, 0.5% risk per trade, ICICI MoneySaver + 0.15% slippage per side, GTT breakout entries. Gross run = same rules, no costs.

## 1. Holding period (trading sessions)

Median **3** sessions, mean 4.6, 25% of trades ≤ 1, 75% ≤ 5, 90% ≤ 9, longest 83. The handbook describes holds of 2–8 weeks (10–40 sessions); 10% of trades lasted 10 sessions or more.

| sessions held | trades | win_pct | avg_R | share_pct |
|---|---|---|---|---|
| 1 | 358 | 6.10 | -0.73 | 32.50 |
| 2 | 165 | 20.00 | -0.54 | 15.00 |
| 3–5 | 440 | 48.00 | 0.08 | 39.90 |
| 6–10 | 73 | 17.80 | -0.49 | 6.60 |
| 11–20 | 31 | 58.10 | 0.16 | 2.80 |
| 21–40 | 28 | 89.30 | 1.59 | 2.50 |
| > 40 | 8 | 87.50 | 3.25 | 0.70 |

By setup (median days for winners and losers):

| setup | trades | median_days | mean_days | win_days | loss_days |
|---|---|---|---|---|---|
| A_breakout | 348 | 1.00 | 6.10 | 23.00 | 1.00 |
| B_vcp | 8 | 1.00 | 1.10 |  | 1.00 |
| C_pocket_pivot | 69 | 6.00 | 9.10 | 17.00 | 4.50 |
| D_gap_up | 13 | 2.00 | 4.70 | 9.50 | 2.00 |
| E_burst | 504 | 5.00 | 3.60 | 5.00 | 3.00 |
| F_rsi2 | 158 | 2.00 | 2.60 | 2.00 | 2.00 |
| G_holy_grail | 3 | 3.00 | 4.70 | 10.00 | 2.00 |

## 2. Activity

- **1,103 trades in 1,683 sessions = 0.66 new trades per day**, 3.3 per week, 13.8 per month.
- Days with at least one entry: 23% · busiest day 5 entries · weeks with an entry: 276 of 336.
- Positions held at once: average 3.0, maximum 8 (cap 8).
- Capital at work: average 21% (the rest idle in cash, earning nothing).
- Round trips cost ≈ 1.30% each (ICICI + slippage); total charges paid ₹-286,143 vs the gross run's P&L.

Signals the scanner produced (before portfolio limits):

| index | signals per day (avg) | allowed by regime per day |
|---|---|---|
| A_breakout | 91.67 | 87.97 |
| B_vcp | 0.75 | 0.82 |
| C_pocket_pivot | 7.36 | 8.19 |
| D_gap_up | 0.99 | 1.17 |
| E_burst | 13.99 | 15.83 |
| F_rsi2 | 7.20 | 6.60 |
| G_holy_grail | 0.07 | 0.07 |

Trades per year:

| entry_date | trades | win_pct | expectancy_R |
|---|---|---|---|
| 2020 | 141 | 36.88 | -0.15 |
| 2021 | 209 | 32.06 | -0.18 |
| 2022 | 157 | 28.66 | -0.27 |
| 2023 | 180 | 32.22 | -0.16 |
| 2024 | 208 | 25.96 | -0.34 |
| 2025 | 112 | 23.21 | -0.38 |
| 2026 | 96 | 28.12 | -0.36 |

## 3. Winners vs losers

| win | trades | avg_R | median_days | avg_mfe_R | avg_mae_R |
|---|---|---|---|---|---|
| losers | 774 | -0.76 | 2.00 | 0.50 | -1.02 |
| winners | 329 | 0.95 | 5.00 | 2.07 | -0.42 |

MFE = the best price reached while held, in R; MAE = the worst. A loser with MFE ≥ +1R was a winner first.

- 329 winners (30%) vs 774 losers.
- **111 losers (14%) were up at least +1R before they lost** (median MFE of all losers 0.31R).
- 76 stops were hit by an overnight gap, average -1.52R (worse than the planned −1R).
- Average stop distance 7.0% of price; 54% of stops sat at the 8% cap.

Why trades ended:

| reason | trades | win_pct | avg_R | median_days | avg_mfe_R |
|---|---|---|---|---|---|
| stop | 306 | 4.20 | -1.01 | 2.00 | 0.79 |
| burst 5-day exit | 268 | 63.10 | 0.48 | 5.00 | 1.51 |
| failed breakout | 248 | 0.80 | -0.38 | 1.00 | 0.26 |
| rsi2 exit | 121 | 70.20 | 0.28 | 3.00 | 0.85 |
| stop (gap) | 76 | 2.60 | -1.52 | 1.00 | 0.42 |
| trail 20-EMA | 45 | 100.00 | 1.96 | 27.00 | 4.44 |
| time stop | 38 | 34.20 | -0.20 | 10.00 | 0.69 |
| no prices (suspended/renamed) | 1 | 0.00 | -0.20 | 5.00 | 0.32 |

## 4. What if they had been held longer?

### (a) Every entry held a fixed number of sessions, no stop

| held from entry | 5 sessions | 10 sessions | 20 sessions | 40 sessions | 60 sessions |
|---|---|---|---|---|---|
| avg return % | -0.14 | 0.65 | 1.24 | 3.30 | 5.05 |
| median return % | -0.75 | -0.06 | 0.28 | 0.58 | 1.56 |
| avg vs universe % | -0.61 | -0.35 | -0.45 | 0.00 | -0.17 |
| % beating universe | 41.07 | 42.70 | 44.24 | 45.15 | 41.98 |
| avg after costs % | -1.44 | -0.66 | -0.06 | 2.00 | 3.75 |
| avg after costs R | -0.22 | -0.11 | 0.03 | 0.36 | 0.71 |
| % profitable after costs | 38.17 | 42.61 | 46.42 | 47.96 | 48.50 |

For comparison the actual exits averaged -0.251R per trade after costs.

Excess over the universe by setup:

| setup | 5d vs universe % | 20d vs universe % | 60d vs universe % |
|---|---|---|---|
| A_breakout | -0.53 | -0.90 | -1.11 |
| B_vcp | -1.71 | 0.80 | 0.24 |
| C_pocket_pivot | -1.21 | 1.04 | 0.11 |
| D_gap_up | -1.30 | 7.03 | 21.37 |
| E_burst | -0.98 | -0.99 | -0.62 |
| F_rsi2 | 0.79 | 0.99 | 1.19 |
| G_holy_grail | -2.39 | -4.89 | 17.42 |

### (b) What each trade did AFTER its actual exit

| group | 5 sessions later % | 10 sessions later % | 20 sessions later % | 40 sessions later % | 5 sessions later vs universe % | 10 sessions later vs universe % | 20 sessions later vs universe % | 40 sessions later vs universe % |
|---|---|---|---|---|---|---|---|---|
| winners | 1.50 | 2.77 | 2.83 | 5.88 | 0.65 | 1.49 | 1.11 | 2.66 |
| losers | 0.23 | 0.82 | 1.83 | 3.46 | -0.30 | -0.21 | 0.36 | 0.08 |
| stopped out | 0.09 | 1.00 | 2.04 | 3.46 | -0.73 | -0.43 | 0.10 | -0.48 |
| failed breakout | 0.42 | 0.86 | 1.64 | 3.83 | 0.12 | 0.17 | 0.37 | 0.59 |
| trailed out (20-EMA) | 2.00 | 4.56 | 2.61 | 6.20 | 1.14 | 3.23 | 2.49 | 3.81 |
| time stop | 1.49 | 2.65 | 3.36 | 2.75 | 0.82 | 1.51 | 2.72 | 2.30 |

## 5. Where the money went

- Gross expectancy -0.029R per trade; after ICICI costs and slippage -0.251R. The rules have no edge before costs, and costs take a further ≈0.22R per trade.

By setup:

| setup | gross R | after-cost R | cost drag R |
|---|---|---|---|
| A_breakout | 0.08 | -0.20 | 0.28 |
| B_vcp | -0.23 | -0.43 | 0.21 |
| C_pocket_pivot | -0.38 | -0.58 | 0.20 |
| D_gap_up | -0.46 | -0.52 | 0.05 |
| E_burst | -0.09 | -0.28 | 0.20 |
| F_rsi2 | 0.15 | -0.08 | 0.23 |
| G_holy_grail | -0.15 | -0.40 | 0.25 |

By regime score on the entry day (the handbook allows breakouts at 3–4, pullbacks at 2+):

| regime | trades | win_pct | avg_R |
|---|---|---|---|
| 2 | 137 | 51.80 | -0.08 |
| 3 | 490 | 30.20 | -0.23 |
| 4 | 476 | 23.10 | -0.32 |

