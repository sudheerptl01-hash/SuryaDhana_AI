# Post-results drift on NSE (PEAD)

Generated 2026-10-14 02:53 by `scripts/results_drift_study.py`; plan fixed beforehand in `PLAN.md` (read it first). Release times from NSE (`nse_results`), prices: split/bonus-adjusted bhavcopy.

- Events: **16,271** quarterly results of 660 stocks; entries 2015-01-15 → 2026-10-13 (60-session results through entries of 2026-07-20).
- Discovery 7,826 events (2015–2021) · holdout 8,445 (2022 →).
- Round-trip cost 0.95% (ICICI, ₹50,000). Excess = vs the equal-weight liquid NSE universe, entry at the next open after the reaction session.

## Verdicts (pre-registered)

| hypothesis | result | detail |
|---|---|---|
| H1 · drift after strong good news (≥ +5% excess reaction) | **FAIL** | 60d excess 2.72% (t 1.37) / 3.4% (t 3.41); holdout after costs 2.44% |
| H2 · drift after strong bad news (≤ −5%) | **PASS** | 60d excess -3.74% (t -2.76) / -2.04% (t -3.03) |
| H3 · strong-up minus strong-down spread > 0 | **PASS** | 7.57% (t 2.78) / 5.39% (t 3.5) |

## Forward excess by reaction bucket — 20 sessions

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | avg_return | excess_after_costs |
|---|---|---|---|---|---|---|---|---|---|
| strong up | discovery | 421 | 145 | 1.99 | 0.4 | 52.5 | 0.82 | 3.55 | 1.03 |
| strong up | holdout | 815 | 114 | 1.78 | 0.75 | 53.6 | 3.7 | 1.9 | 0.83 |
| up | discovery | 930 | 203 | 0.17 | -0.95 | 44.8 | 0.59 | 1.3 | -0.78 |
| up | holdout | 1256 | 122 | 0.94 | 0.05 | 50.3 | 1.6 | 1.22 | -0.02 |
| flat | discovery | 4734 | 273 | 0.13 | -0.76 | 45.9 | -1.38 | 0.67 | -0.82 |
| flat | holdout | 3819 | 144 | -0.17 | -1.01 | 44.3 | -2.03 | 0.5 | -1.13 |
| down | discovery | 1347 | 217 | -1.25 | -1.88 | 40.3 | -2.17 | -0.03 | -2.21 |
| down | holdout | 1803 | 131 | -0.24 | -1.18 | 43.9 | -2.28 | 0.34 | -1.2 |
| strong down | discovery | 388 | 120 | -1.73 | -3.27 | 37.1 | -1.39 | -0.21 | -2.68 |
| strong down | holdout | 744 | 118 | -1.71 | -2.52 | 38.0 | -5.08 | -1.03 | -2.66 |
| all | discovery | 7820 | 283 | -0.09 | -1.06 | 44.7 | -1.57 | 0.73 | -1.05 |
| all | holdout | 8437 | 159 | 0.03 | -0.86 | 45.4 | -1.91 | 0.57 | -0.92 |

## Forward excess by reaction bucket — 60 sessions

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | avg_return | excess_after_costs |
|---|---|---|---|---|---|---|---|---|---|
| strong up | discovery | 420 | 145 | 2.72 | -1.5 | 47.4 | 1.37 | 8.65 | 1.76 |
| strong up | holdout | 765 | 109 | 3.4 | 1.33 | 52.3 | 3.41 | 7.12 | 2.44 |
| up | discovery | 930 | 203 | 0.24 | -1.94 | 45.2 | -0.16 | 4.65 | -0.71 |
| up | holdout | 1188 | 118 | 1.06 | -0.6 | 48.2 | 0.7 | 4.74 | 0.1 |
| flat | discovery | 4727 | 273 | -0.21 | -1.51 | 45.7 | -1.62 | 2.55 | -1.16 |
| flat | holdout | 3624 | 140 | -0.01 | -2.05 | 42.9 | -1.84 | 3.94 | -0.96 |
| down | discovery | 1347 | 217 | -0.7 | -3.98 | 40.3 | -0.4 | 4.09 | -1.65 |
| down | holdout | 1697 | 127 | -0.59 | -3.18 | 41.1 | -1.89 | 2.95 | -1.55 |
| strong down | discovery | 388 | 120 | -3.74 | -4.72 | 34.0 | -2.76 | 2.63 | -4.7 |
| strong down | holdout | 696 | 114 | -2.04 | -3.84 | 39.5 | -3.03 | 1.51 | -2.99 |
| all | discovery | 7812 | 283 | -0.26 | -2.1 | 44.2 | -2.05 | 3.4 | -1.21 |
| all | holdout | 7970 | 155 | 0.17 | -1.99 | 43.9 | -1.53 | 3.94 | -0.78 |

## Exploratory (not pre-registered; qualifies, never overturns, the verdicts)

| slice | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|---|---|---|
| strong up · gap held (close ≥ open) | discovery | 395 | 143 | 3.03 | -1.33 | 47.8 | 1.51 | 2.08 |
| strong up · gap held (close ≥ open) | holdout | 712 | 107 | 3.54 | 1.5 | 52.5 | 3.48 | 2.58 |
| strong up · gap faded (close < open) | discovery | 25 | 20 | -2.22 | -5.61 | 40.0 | -1.03 | -3.18 |
| strong up · gap faded (close < open) | holdout | 53 | 40 | 1.48 | -1.34 | 49.1 | 0.39 | 0.53 |
| strong up · after-close releases | discovery | 284 | 107 | 2.51 | -2.11 | 46.8 | 1.36 | 1.56 |
| strong up · after-close releases | holdout | 627 | 104 | 3.13 | 0.97 | 51.4 | 2.88 | 2.18 |
| strong up · market-hours releases | discovery | 133 | 91 | 3.33 | -0.74 | 48.1 | 1.38 | 2.38 |
| strong up · market-hours releases | holdout | 134 | 68 | 4.89 | 2.24 | 56.0 | 1.53 | 3.94 |
| strong up · turnover ≥ ₹50 cr | discovery | 250 | 109 | 0.96 | -2.7 | 42.4 | 0.54 | 0.01 |
| strong up · turnover ≥ ₹50 cr | holdout | 481 | 101 | 3.44 | 1.06 | 51.8 | 4.32 | 2.49 |
| strong up · turnover < ₹50 cr | discovery | 170 | 93 | 5.3 | 2.46 | 54.7 | 2.86 | 4.35 |
| strong up · turnover < ₹50 cr | holdout | 284 | 91 | 3.32 | 1.58 | 53.2 | 1.39 | 2.37 |
| strong down · turnover ≥ ₹50 cr | discovery | 207 | 99 | -3.83 | -4.58 | 35.3 | -2.14 | -4.79 |
| strong down · turnover ≥ ₹50 cr | holdout | 426 | 108 | -1.32 | -2.52 | 43.2 | -2.26 | -2.28 |
| reaction ≥ +10% | discovery | 83 | 56 | 4.21 | -1.52 | 48.2 | 1.86 | 3.26 |
| reaction ≥ +10% | holdout | 176 | 79 | 1.97 | -0.09 | 49.4 | 1.12 | 1.01 |
| reaction ≤ −10% | discovery | 46 | 34 | -2.7 | -2.15 | 43.5 | -1.03 | -3.66 |
| reaction ≤ −10% | holdout | 92 | 53 | -2.25 | -5.31 | 34.8 | -2.96 | -3.21 |

### Strong buckets by year (60 sessions)

| year | events | strong_up_n | strong_up_ex60 | strong_down_n | strong_down_ex60 |
|---|---|---|---|---|---|
| 2015 | 891 | 34 | 1.56 | 49 | -6.94 |
| 2016 | 952 | 46 | -1.85 | 34 | -3.42 |
| 2017 | 1180 | 26 | 12.41 | 12 | 2.72 |
| 2018 | 1170 | 21 | 4.58 | 15 | -12.71 |
| 2019 | 943 | 62 | 2.59 | 51 | 1.87 |
| 2020 | 1137 | 103 | 2.61 | 83 | -0.68 |
| 2021 | 1539 | 128 | 2.54 | 144 | -6.09 |
| 2022 | 1464 | 123 | 2.58 | 119 | -3.57 |
| 2023 | 1677 | 137 | 5.61 | 113 | -0.26 |
| 2024 | 1927 | 172 | 4.25 | 198 | -3.09 |
| 2025 | 1866 | 197 | 1.87 | 138 | 0.12 |
| 2026 | 1036 | 136 | 3.04 | 128 | -2.88 |

### Reaction sizes

Median absolute excess reaction 1.86%; share ≥ +5%: 7.6%, ≤ −5%: 7.0%. Timing: {'after close': 11857, 'market hours': 4312, 'pre-open': 102}.

