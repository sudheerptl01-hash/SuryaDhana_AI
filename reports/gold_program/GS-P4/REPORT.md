# GS-P4 · Month-of-year seasonality of gold in rupees — result tables

Generated 2026-11-04T22:26 by `scripts/gold_studies/gs_p4_seasonality_in_inr.py` from the plan in `PLAN.md`. Long sample (World Bank monthly average × DEXINUS monthly mean, GC=F spliced after Dec 2024): 1973-02-28 → 2026-09-30, 644 months, halves at 1999-12-31. Tradable sample (GC=F month-end × DEXINUS month-end): 2000-10-31 → 2026-09-30, 312 months, halves at 2013-12-31. Rupee drift 4.63 %/yr (log, not seasonal). Monthly log returns, plain t. Costs 0.15 % per switch (every flat→long and long→flat transition).

## Gold in rupees, long sample, by calendar month

`t` = the month's mean vs zero (pre-registered; void, N4); `t_excess` = the month's mean minus the all-month mean of the same sample / half (drift-adjusted); `verdict` = the drift-adjusted verdict capped at CONTEXT-ONLY (post-hoc statistic). PASS needs |t| ≥ 2 with the same sign in both halves + the same sign 2000 → month-ends.

| month | n | mean_pct | hit_pct | t | excess_pct | t_excess | h1_mean | h1_t | h1_t_excess | h1_n | h2_mean | h2_t | h2_t_excess | h2_n | verdict_pre | verdict_adj | verdict | tradable_excess_pct | tradable_t_excess | tradable_verdict | post_hoc_cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 53 | 2.58 | 60.00 | 2.64 | 1.55 | 1.58 | 2.77 | 1.49 | 0.97 | 26 | 2.40 | 3.18 | 1.74 | 27 | CONTEXT-ONLY | FAIL | FAIL | 1.51 | 1.70 | FAIL | 0 |
| Feb | 54 | 1.46 | 59.00 | 2.56 | 0.43 | 0.75 | 0.86 | 0.99 | −0.14 | 27 | 2.06 | 2.77 | 1.31 | 27 | CONTEXT-ONLY | FAIL | FAIL | 0.42 | 0.48 | FAIL | 0 |
| Mar | 54 | 0.10 | 59.00 | 0.13 | −0.93 | −1.28 | 0.03 | 0.02 | −0.75 | 27 | 0.17 | 0.22 | −1.21 | 27 | FAIL | FAIL | FAIL | −1.43 | −1.69 | FAIL | 0 |
| Apr | 54 | 0.42 | 50.00 | 0.79 | −0.61 | −1.15 | 0.30 | 0.45 | −1.03 | 27 | 0.54 | 0.64 | −0.64 | 27 | FAIL | FAIL | FAIL | 0.15 | 0.16 | FAIL | 0 |
| May | 54 | 0.80 | 57.00 | 1.56 | −0.23 | −0.46 | 0.44 | 0.59 | −0.73 | 27 | 1.16 | 1.63 | 0.10 | 27 | FAIL | FAIL | FAIL | 0.00 | 0.00 | FAIL | 0 |
| Jun | 54 | 0.40 | 57.00 | 0.67 | −0.63 | −1.03 | 0.80 | 0.84 | −0.19 | 27 | 0.01 | 0.02 | −1.38 | 27 | FAIL | FAIL | FAIL | −1.68 | −1.69 | FAIL | 0 |
| Jul | 54 | 0.58 | 54.00 | 0.93 | −0.46 | −0.74 | 0.66 | 0.60 | −0.29 | 27 | 0.49 | 0.82 | −0.99 | 27 | FAIL | FAIL | FAIL | −0.13 | −0.18 | FAIL | 0 |
| Aug | 54 | 1.69 | 63.00 | 2.71 | 0.65 | 1.05 | 1.11 | 1.29 | 0.16 | 27 | 2.26 | 2.51 | 1.30 | 27 | CONTEXT-ONLY | FAIL | FAIL | 2.34 | 2.32 | CONTEXT-ONLY | 0 |
| Sep | 54 | 2.00 | 67.00 | 2.75 | 0.97 | 1.33 | 2.33 | 1.89 | 1.10 | 27 | 1.67 | 2.11 | 0.74 | 27 | CONTEXT-ONLY | FAIL | FAIL | −0.68 | −0.61 | FAIL | 0 |
| Oct | 53 | 0.98 | 55.00 | 1.97 | −0.05 | −0.10 | 1.60 | 1.98 | 0.76 | 27 | 0.34 | 0.61 | −1.33 | 26 | FAIL | FAIL | FAIL | −0.83 | −1.02 | FAIL | 0 |
| Nov | 53 | 0.61 | 45.00 | 1.00 | −0.42 | −0.70 | −0.02 | −0.02 | −1.02 | 27 | 1.26 | 1.74 | 0.24 | 26 | FAIL | FAIL | FAIL | 0.51 | 0.48 | FAIL | 0 |
| Dec | 53 | 0.79 | 55.00 | 1.33 | −0.24 | −0.41 | 0.94 | 0.94 | −0.04 | 27 | 0.63 | 0.99 | −0.72 | 26 | FAIL | FAIL | FAIL | −0.16 | −0.19 | FAIL | 0 |

## Hypotheses

| hypothesis | months | per_month | verdict_pre | verdict |
|---|---|---|---|---|
| H1 festival (Sep/Oct/Nov) | Sep, Oct, Nov | Sep 2.00 % (t vs 0 2.75; excess 0.97 % t 1.33, halves 1.10/0.74) FAIL; Oct 0.98 % (t vs 0 1.97; excess −0.05 % t −0.10, halves 0.76/−1.33) FAIL; Nov 0.61 % (t vs 0 1.00; excess −0.42 % t −0.70, halves −1.02/0.24) FAIL | CONTEXT-ONLY | FAIL |
| H1b Akshaya Tritiya (Apr/May) | Apr, May | Apr 0.42 % (t vs 0 0.79; excess −0.61 % t −1.15, halves −1.03/−0.64) FAIL; May 0.80 % (t vs 0 1.56; excess −0.23 % t −0.46, halves −0.73/0.10) FAIL | FAIL | FAIL |
| H2 Dec/Jan carry-over | Dec, Jan | Dec 0.79 % (t vs 0 1.33; excess −0.24 % t −0.41, halves −0.04/−0.72) FAIL; Jan 2.58 % (t vs 0 2.64; excess 1.55 % t 1.58, halves 0.97/1.74) FAIL | CONTEXT-ONLY | FAIL |

## Gold in rupees, tradable month-end sample (2000 →)

| month | n | mean_pct | hit_pct | t | excess_pct | t_excess | h1_mean | h1_t | h1_t_excess | h1_n | h2_mean | h2_t | h2_t_excess | h2_n | verdict_pre | verdict_adj | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 26 | 2.62 | 65.00 | 2.95 | 1.51 | 1.70 | 1.31 | 0.98 | 0.14 | 13 | 3.93 | 3.53 | 2.54 | 13 | CONTEXT-ONLY | FAIL | FAIL |
| Feb | 26 | 1.52 | 65.00 | 1.75 | 0.42 | 0.48 | 1.38 | 1.29 | 0.25 | 13 | 1.67 | 1.17 | 0.40 | 13 | FAIL | FAIL | FAIL |
| Mar | 26 | −0.32 | 46.00 | −0.38 | −1.43 | −1.69 | −0.77 | −0.90 | −2.20 | 13 | 0.13 | 0.09 | −0.65 | 13 | FAIL | FAIL | FAIL |
| Apr | 26 | 1.26 | 73.00 | 1.39 | 0.15 | 0.16 | 0.24 | 0.14 | −0.52 | 13 | 2.27 | 3.77 | 1.94 | 13 | FAIL | FAIL | FAIL |
| May | 26 | 1.11 | 69.00 | 1.55 | 0.00 | 0.00 | 2.21 | 2.02 | 1.00 | 13 | 0.01 | 0.02 | −1.26 | 13 | FAIL | FAIL | FAIL |
| Jun | 26 | −0.58 | 46.00 | −0.58 | −1.68 | −1.69 | −1.17 | −0.96 | −1.87 | 13 | 0.02 | 0.01 | −0.67 | 13 | FAIL | FAIL | FAIL |
| Jul | 26 | 0.97 | 65.00 | 1.31 | −0.13 | −0.18 | 1.07 | 0.92 | −0.04 | 13 | 0.88 | 0.91 | −0.23 | 13 | FAIL | FAIL | FAIL |
| Aug | 26 | 3.44 | 77.00 | 3.42 | 2.34 | 2.32 | 4.07 | 2.48 | 1.80 | 13 | 2.82 | 2.34 | 1.43 | 13 | PASS | CONTEXT-ONLY | CONTEXT-ONLY |
| Sep | 26 | 0.43 | 46.00 | 0.39 | −0.68 | −0.61 | 1.95 | 1.12 | 0.48 | 13 | −1.09 | −0.85 | −1.70 | 13 | FAIL | FAIL | FAIL |
| Oct | 26 | 0.28 | 54.00 | 0.35 | −0.83 | −1.02 | −0.69 | −0.55 | −1.44 | 14 | 1.41 | 1.52 | 0.33 | 12 | FAIL | FAIL | FAIL |
| Nov | 26 | 1.62 | 58.00 | 1.54 | 0.51 | 0.48 | 3.90 | 2.81 | 2.00 | 14 | −1.04 | −0.83 | −1.71 | 12 | FAIL | FAIL | FAIL |
| Dec | 26 | 0.94 | 69.00 | 1.10 | −0.16 | −0.19 | −0.07 | −0.05 | −0.82 | 14 | 2.13 | 2.99 | 1.44 | 12 | FAIL | FAIL | FAIL |

## The two legs, long sample: gold in USD and USD/INR

| month | n | mean_pct | hit_pct | t | excess_pct | t_excess | h1_mean | h1_t | h1_t_excess | h1_n | h2_mean | h2_t | h2_t_excess | h2_n | verdict_pre | verdict_adj | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 53 | 2.51 | 66.00 | 2.59 | 1.87 | 1.92 | 2.37 | 1.27 | 1.02 | 26 | 2.66 | 3.86 | 2.64 | 27 | CONTEXT-ONLY | FAIL | FAIL |
| Feb | 54 | 1.26 | 57.00 | 1.99 | 0.61 | 0.97 | 0.50 | 0.49 | 0.05 | 27 | 2.02 | 2.80 | 1.64 | 27 | FAIL | FAIL | FAIL |
| Mar | 54 | −0.15 | 52.00 | −0.20 | −0.80 | −1.04 | −0.31 | −0.23 | −0.58 | 27 | −0.00 | −0.00 | −1.00 | 27 | FAIL | FAIL | FAIL |
| Apr | 54 | 0.40 | 44.00 | 0.76 | −0.25 | −0.47 | −0.01 | −0.01 | −0.65 | 27 | 0.81 | 1.05 | −0.04 | 27 | FAIL | FAIL | FAIL |
| May | 54 | 0.24 | 35.00 | 0.46 | −0.41 | −0.78 | −0.03 | −0.04 | −0.66 | 27 | 0.51 | 0.70 | −0.44 | 27 | FAIL | FAIL | FAIL |
| Jun | 54 | −0.22 | 52.00 | −0.33 | −0.86 | −1.31 | 0.17 | 0.15 | −0.27 | 27 | −0.60 | −0.77 | −1.84 | 27 | FAIL | FAIL | FAIL |
| Jul | 54 | −0.03 | 52.00 | −0.06 | −0.68 | −1.25 | −0.25 | −0.28 | −0.80 | 27 | 0.19 | 0.29 | −1.01 | 27 | FAIL | FAIL | FAIL |
| Aug | 54 | 1.05 | 57.00 | 1.69 | 0.40 | 0.65 | 0.50 | 0.53 | 0.04 | 27 | 1.60 | 1.93 | 0.92 | 27 | FAIL | FAIL | FAIL |
| Sep | 54 | 1.27 | 50.00 | 1.76 | 0.62 | 0.86 | 1.41 | 1.14 | 0.78 | 27 | 1.12 | 1.45 | 0.37 | 27 | FAIL | FAIL | FAIL |
| Oct | 53 | 0.86 | 53.00 | 1.65 | 0.21 | 0.41 | 1.41 | 1.69 | 1.15 | 27 | 0.28 | 0.47 | −0.92 | 26 | FAIL | FAIL | FAIL |
| Nov | 53 | 0.14 | 51.00 | 0.21 | −0.51 | −0.80 | −0.53 | −0.53 | −0.99 | 27 | 0.83 | 1.08 | −0.01 | 26 | FAIL | FAIL | FAIL |
| Dec | 53 | 0.46 | 53.00 | 0.74 | −0.19 | −0.30 | 0.31 | 0.29 | −0.14 | 27 | 0.62 | 0.96 | −0.33 | 26 | FAIL | FAIL | FAIL |

| month | n | mean_pct | hit_pct | t | excess_pct | t_excess | h1_mean | h1_t | h1_t_excess | h1_n | h2_mean | h2_t | h2_t_excess | h2_n | verdict_pre | verdict_adj | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 53 | 0.07 | 51.00 | 0.37 | −0.32 | −1.73 | 0.41 | 1.43 | −0.42 | 26 | −0.26 | −1.15 | −2.25 | 27 | FAIL | FAIL | FAIL |
| Feb | 54 | 0.20 | 59.00 | 1.10 | −0.19 | −1.03 | 0.36 | 1.18 | −0.56 | 27 | 0.04 | 0.21 | −1.01 | 27 | FAIL | FAIL | FAIL |
| Mar | 54 | 0.25 | 52.00 | 0.82 | −0.13 | −0.44 | 0.33 | 0.65 | −0.37 | 27 | 0.17 | 0.49 | −0.23 | 27 | FAIL | FAIL | FAIL |
| Apr | 54 | 0.02 | 52.00 | 0.10 | −0.36 | −1.76 | 0.31 | 1.08 | −0.76 | 27 | −0.26 | −0.89 | −1.73 | 27 | FAIL | FAIL | FAIL |
| May | 54 | 0.56 | 67.00 | 2.44 | 0.17 | 0.75 | 0.47 | 1.85 | −0.21 | 27 | 0.64 | 1.68 | 1.04 | 27 | CONTEXT-ONLY | FAIL | FAIL |
| Jun | 54 | 0.62 | 72.00 | 3.06 | 0.24 | 1.16 | 0.63 | 2.05 | 0.34 | 27 | 0.61 | 2.25 | 1.35 | 27 | PASS | FAIL | FAIL |
| Jul | 54 | 0.61 | 50.00 | 1.50 | 0.22 | 0.55 | 0.91 | 1.15 | 0.49 | 27 | 0.31 | 1.58 | 0.31 | 27 | FAIL | FAIL | FAIL |
| Aug | 54 | 0.64 | 69.00 | 3.77 | 0.25 | 1.48 | 0.62 | 2.82 | 0.43 | 27 | 0.65 | 2.50 | 1.56 | 27 | PASS | FAIL | FAIL |
| Sep | 54 | 0.73 | 69.00 | 3.40 | 0.35 | 1.61 | 0.92 | 3.72 | 1.60 | 27 | 0.54 | 1.54 | 0.84 | 27 | CONTEXT-ONLY | FAIL | FAIL |
| Oct | 53 | 0.12 | 55.00 | 0.52 | −0.26 | −1.10 | 0.18 | 0.83 | −1.54 | 27 | 0.06 | 0.14 | −0.42 | 26 | FAIL | FAIL | FAIL |
| Nov | 53 | 0.47 | 72.00 | 3.30 | 0.09 | 0.61 | 0.52 | 3.49 | −0.03 | 27 | 0.42 | 1.69 | 0.71 | 26 | CONTEXT-ONLY | FAIL | FAIL |
| Dec | 53 | 0.33 | 58.00 | 1.79 | −0.06 | −0.32 | 0.63 | 2.25 | 0.39 | 27 | 0.01 | 0.03 | −1.11 | 26 | FAIL | FAIL | FAIL |

### Decomposition per month (log INR = log USD + log FX)

| month | n | usd_mean_pct | usd_t | fx_mean_pct | fx_t | inr_mean_pct | dominant_leg |
|---|---|---|---|---|---|---|---|
| Jan | 53 | 2.51 | 2.59 | 0.07 | 0.37 | 2.58 | USD gold |
| Feb | 54 | 1.26 | 1.99 | 0.20 | 1.10 | 1.46 | USD gold |
| Mar | 54 | −0.15 | −0.20 | 0.25 | 0.82 | 0.10 | USD/INR |
| Apr | 54 | 0.40 | 0.76 | 0.02 | 0.10 | 0.42 | USD gold |
| May | 54 | 0.24 | 0.46 | 0.56 | 2.44 | 0.80 | USD/INR |
| Jun | 54 | −0.22 | −0.33 | 0.62 | 3.06 | 0.40 | USD/INR |
| Jul | 54 | −0.03 | −0.06 | 0.61 | 1.50 | 0.58 | USD/INR |
| Aug | 54 | 1.05 | 1.69 | 0.64 | 3.77 | 1.69 | USD gold |
| Sep | 54 | 1.27 | 1.76 | 0.73 | 3.40 | 2.00 | USD gold |
| Oct | 53 | 0.86 | 1.65 | 0.12 | 0.52 | 0.98 | USD gold |
| Nov | 53 | 0.14 | 0.21 | 0.47 | 3.30 | 0.61 | USD/INR |
| Dec | 53 | 0.46 | 0.74 | 0.33 | 1.79 | 0.79 | USD gold |

## GOLDBEES.NS month-ends (2009-02-28 → 2026-09-30; duty, premium and expense ratio included)

| month | n | mean_pct | hit_pct | t | excess_pct | t_excess | h1_mean | h1_t | h1_t_excess | h1_n | h2_mean | h2_t | h2_t_excess | h2_n | verdict_pre | verdict_adj | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 17 | 2.94 | 65.00 | 2.49 | 1.92 | 1.63 | 1.63 | 1.42 | 0.91 | 8 | 4.11 | 2.09 | 1.34 | 9 | CONTEXT-ONLY | FAIL | FAIL |
| Feb | 18 | 1.36 | 72.00 | 1.41 | 0.34 | 0.35 | 2.19 | 1.40 | 1.02 | 9 | 0.52 | 0.45 | −0.81 | 9 | FAIL | FAIL | FAIL |
| Mar | 18 | −0.65 | 44.00 | −0.66 | −1.67 | −1.69 | −1.83 | −2.73 | −3.61 | 9 | 0.53 | 0.29 | −0.51 | 9 | FAIL | FAIL | FAIL |
| Apr | 18 | 2.70 | 83.00 | 2.58 | 1.68 | 1.61 | 1.51 | 0.93 | 0.57 | 9 | 3.89 | 3.03 | 1.89 | 9 | CONTEXT-ONLY | FAIL | FAIL |
| May | 18 | 0.05 | 56.00 | 0.05 | −0.97 | −1.07 | −0.47 | −0.29 | −0.65 | 9 | 0.57 | 0.64 | −1.00 | 9 | FAIL | FAIL | FAIL |
| Jun | 18 | −0.86 | 39.00 | −0.85 | −1.88 | −1.87 | −0.28 | −0.22 | −0.66 | 9 | −1.43 | −0.91 | −1.83 | 9 | FAIL | FAIL | FAIL |
| Jul | 18 | 1.29 | 67.00 | 1.20 | 0.27 | 0.25 | 0.66 | 0.37 | 0.04 | 9 | 1.91 | 1.49 | 0.35 | 9 | FAIL | FAIL | FAIL |
| Aug | 18 | 3.60 | 78.00 | 3.22 | 2.59 | 2.31 | 5.02 | 3.23 | 2.85 | 9 | 2.19 | 1.41 | 0.47 | 9 | CONTEXT-ONLY | CONTEXT-ONLY | CONTEXT-ONLY |
| Sep | 18 | −0.24 | 39.00 | −0.27 | −1.26 | −1.40 | −0.48 | −0.62 | −1.38 | 9 | −0.01 | −0.00 | −0.87 | 9 | FAIL | FAIL | FAIL |
| Oct | 17 | 1.72 | 76.00 | 2.68 | 0.70 | 1.09 | 0.15 | 0.22 | −0.64 | 9 | 3.48 | 4.67 | 2.71 | 8 | CONTEXT-ONLY | FAIL | FAIL |
| Nov | 17 | 0.61 | 59.00 | 0.57 | −0.41 | −0.38 | 1.55 | 0.92 | 0.57 | 9 | −0.44 | −0.33 | −1.44 | 8 | FAIL | FAIL | FAIL |
| Dec | 17 | −0.24 | 47.00 | −0.28 | −1.25 | −1.51 | −2.48 | −2.63 | −3.25 | 9 | 2.29 | 3.30 | 1.19 | 8 | FAIL | FAIL | FAIL |

## H3 · walk-forward best-6-months rule, tradable sample

| oos_from | oos_months | oos_mid | exposure_pct | strat_cagr | bh_cagr | strat_sharpe | bh_sharpe | strat_maxdd | excess_vs_scaled_pa_pct | t | t_h1 | t_h2 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2005 | 261 | 2015-11-30 | 50.20 | 8.40 | 15.07 | 0.69 | 0.91 | −18.80 | 1.10 | 0.59 | 0.97 | −0.26 | FAIL |

Month set chosen for the last year: Jan, Feb, Apr, May, Aug, Nov.

### The same rule on the long (average-price, non-tradable) sample, for reference

| oos_from | oos_months | exposure_pct | strat_cagr | bh_cagr | excess_vs_scaled_pa_pct | t | t_h1 | t_h2 | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1978 | 585 | 50.10 | 6.15 | 12.36 | 0.24 | 0.20 | −0.07 | 0.42 | FAIL |

## Negative controls

Relabelled months (month labels shuffled across observations (seed 20261026; null rates over 100 further seeds)). Drift-adjusted: PASS months [] → ok True; null PASS rate 3%, months at |t| ≥ 2 per run 0.6. Vs zero (pre-registered): PASS months ['Feb', 'Nov'] → ok False; null PASS rate 44%, months at t ≥ 2 per run 4.42 → statistic void: True. H3 on shuffled returns: t −1.09 → ok True; |t| ≥ 2 in 7% of seeds.


## Overall: **VOID (pre-registered statistic) / FAIL (post-hoc drift-adjusted, capped)** (badge consequence: FAIL) — PASS months [], CONTEXT-ONLY months [] (post-hoc capped: []), vs-zero months at t ≥ 2 ['Jan', 'Feb', 'Aug', 'Sep'] (void), H3 FAIL (drift-adjusted controls ok: True)
