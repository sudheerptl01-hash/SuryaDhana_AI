# Post-results drift on NSE (PEAD)

Generated 2026-10-11 23:42 by `scripts/results_drift_study.py`; plan fixed beforehand in `PLAN.md` (read it first). Release times from NSE (`nse_results`), prices: split/bonus-adjusted bhavcopy.

- Events: **16,247** quarterly results of 651 stocks; entries 2015-01-15 → 2026-10-09 (60-session results through entries of 2026-07-16).
- Discovery 7,820 events (2015–2021) · holdout 8,427 (2022 →).
- Round-trip cost 0.95% (ICICI, ₹50,000). Excess = vs the equal-weight liquid NSE universe, entry at the next open after the reaction session.

## Verdicts (pre-registered)

| hypothesis | result | detail |
|---|---|---|
| H1 · drift after strong good news (≥ +5% excess reaction) | **FAIL** | 60d excess 2.72% (t 1.37) / 3.58% (t 3.98); holdout after costs 2.62% |
| H2 · drift after strong bad news (≤ −5%) | **PASS** | 60d excess -3.69% (t -2.77) / -1.82% (t -2.5) |
| H3 · strong-up minus strong-down spread > 0 | **PASS** | 7.38% (t 2.79) / 5.41% (t 2.85) |

## Forward excess by reaction bucket — 20 sessions

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | avg_return | excess_after_costs |
|---|---|---|---|---|---|---|---|---|---|
| strong up | discovery | 421 | 145 | 1.99 | 0.4 | 52.5 | 0.82 | 3.55 | 1.03 |
| strong up | holdout | 582 | 99 | 1.86 | 1.0 | 54.1 | 3.2 | 2.13 | 0.91 |
| up | discovery | 930 | 203 | 0.17 | -0.95 | 44.8 | 0.59 | 1.3 | -0.78 |
| up | holdout | 1145 | 114 | 1.15 | 0.25 | 50.7 | 1.92 | 1.88 | 0.19 |
| flat | discovery | 4732 | 273 | 0.13 | -0.76 | 45.9 | -1.38 | 0.66 | -0.82 |
| flat | holdout | 4692 | 137 | -0.01 | -0.98 | 44.5 | -1.39 | 0.86 | -0.96 |
| down | discovery | 1344 | 217 | -1.25 | -1.88 | 40.3 | -2.17 | -0.01 | -2.2 |
| down | holdout | 1464 | 122 | 0.1 | -0.94 | 45.1 | 0.15 | 1.04 | -0.85 |
| strong down | discovery | 387 | 119 | -1.69 | -3.26 | 37.2 | -1.25 | -0.19 | -2.65 |
| strong down | holdout | 536 | 100 | -1.49 | -2.52 | 39.4 | -4.08 | -0.89 | -2.45 |
| all | discovery | 7814 | 283 | -0.09 | -1.06 | 44.7 | -1.56 | 0.74 | -1.05 |
| all | holdout | 8419 | 152 | 0.2 | -0.79 | 45.8 | -0.92 | 1.0 | -0.75 |

## Forward excess by reaction bucket — 60 sessions

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | avg_return | excess_after_costs |
|---|---|---|---|---|---|---|---|---|---|
| strong up | discovery | 420 | 145 | 2.72 | -1.5 | 47.4 | 1.37 | 8.65 | 1.76 |
| strong up | holdout | 570 | 97 | 3.58 | 1.55 | 53.5 | 3.98 | 7.96 | 2.62 |
| up | discovery | 930 | 203 | 0.24 | -1.94 | 45.2 | -0.16 | 4.65 | -0.71 |
| up | holdout | 1101 | 111 | 1.16 | -0.53 | 48.2 | 1.13 | 5.3 | 0.21 |
| flat | discovery | 4725 | 273 | -0.21 | -1.51 | 45.7 | -1.6 | 2.55 | -1.16 |
| flat | holdout | 4364 | 134 | -0.04 | -2.16 | 42.7 | -1.52 | 3.59 | -1.0 |
| down | discovery | 1344 | 217 | -0.68 | -3.97 | 40.4 | -0.39 | 4.12 | -1.64 |
| down | holdout | 1417 | 119 | -0.0 | -2.76 | 42.5 | 0.14 | 4.2 | -0.96 |
| strong down | discovery | 387 | 119 | -3.69 | -4.72 | 34.1 | -2.77 | 2.68 | -4.64 |
| strong down | holdout | 526 | 98 | -1.82 | -3.96 | 38.6 | -2.5 | 1.58 | -2.77 |
| all | discovery | 7806 | 283 | -0.25 | -2.09 | 44.2 | -2.01 | 3.41 | -1.2 |
| all | holdout | 7978 | 149 | 0.27 | -1.99 | 43.9 | -1.1 | 4.12 | -0.68 |

## Exploratory (not pre-registered; qualifies, never overturns, the verdicts)

| slice | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|---|---|---|
| strong up · gap held (close ≥ open) | discovery | 395 | 143 | 3.03 | -1.33 | 47.8 | 1.51 | 2.08 |
| strong up · gap held (close ≥ open) | holdout | 534 | 96 | 3.54 | 1.57 | 53.6 | 3.75 | 2.58 |
| strong up · gap faded (close < open) | discovery | 25 | 20 | -2.22 | -5.61 | 40.0 | -1.03 | -3.18 |
| strong up · gap faded (close < open) | holdout | 36 | 27 | 4.13 | 1.08 | 52.8 | 2.55 | 3.17 |
| strong up · after-close releases | discovery | 284 | 107 | 2.51 | -2.11 | 46.8 | 1.36 | 1.56 |
| strong up · after-close releases | holdout | 429 | 92 | 3.17 | 1.42 | 52.9 | 3.34 | 2.21 |
| strong up · market-hours releases | discovery | 133 | 91 | 3.33 | -0.74 | 48.1 | 1.38 | 2.38 |
| strong up · market-hours releases | holdout | 138 | 68 | 4.58 | 1.79 | 54.3 | 1.3 | 3.62 |
| strong up · turnover ≥ ₹50 cr | discovery | 250 | 109 | 0.96 | -2.7 | 42.4 | 0.54 | 0.01 |
| strong up · turnover ≥ ₹50 cr | holdout | 358 | 86 | 2.96 | 1.5 | 52.8 | 3.95 | 2.0 |
| strong up · turnover < ₹50 cr | discovery | 170 | 93 | 5.3 | 2.46 | 54.7 | 2.86 | 4.35 |
| strong up · turnover < ₹50 cr | holdout | 212 | 75 | 4.62 | 1.82 | 54.7 | 1.88 | 3.67 |
| strong down · turnover ≥ ₹50 cr | discovery | 207 | 99 | -3.83 | -4.58 | 35.3 | -2.14 | -4.79 |
| strong down · turnover ≥ ₹50 cr | holdout | 324 | 89 | -1.06 | -2.93 | 41.4 | -1.81 | -2.01 |
| reaction ≥ +10% | discovery | 83 | 56 | 4.21 | -1.52 | 48.2 | 1.86 | 3.26 |
| reaction ≥ +10% | holdout | 118 | 61 | 2.39 | -0.41 | 47.5 | 1.05 | 1.44 |
| reaction ≤ −10% | discovery | 46 | 34 | -2.7 | -2.15 | 43.5 | -1.03 | -3.66 |
| reaction ≤ −10% | holdout | 71 | 39 | 0.47 | -5.03 | 35.2 | -0.4 | -0.48 |

### Strong buckets by year (60 sessions)

| year | events | strong_up_n | strong_up_ex60 | strong_down_n | strong_down_ex60 |
|---|---|---|---|---|---|
| 2015 | 890 | 34 | 1.56 | 49 | -6.94 |
| 2016 | 952 | 46 | -1.85 | 34 | -3.42 |
| 2017 | 1179 | 26 | 12.41 | 12 | 2.72 |
| 2018 | 1169 | 21 | 4.58 | 15 | -12.71 |
| 2019 | 943 | 62 | 2.59 | 51 | 1.87 |
| 2020 | 1137 | 103 | 2.61 | 83 | -0.68 |
| 2021 | 1536 | 128 | 2.54 | 143 | -5.96 |
| 2022 | 1463 | 122 | 2.69 | 119 | -3.57 |
| 2023 | 1670 | 137 | 5.61 | 111 | -0.83 |
| 2024 | 1913 | 171 | 4.14 | 196 | -2.98 |
| 2025 | 1875 | 89 | 2.26 | 70 | 2.66 |
| 2026 | 1057 | 51 | 0.65 | 30 | -1.38 |

### Reaction sizes

Median absolute excess reaction 1.60%; share ≥ +5%: 6.2%, ≤ −5%: 5.7%. Timing: {'after close': 11193, 'market hours': 4960, 'pre-open': 94}.

