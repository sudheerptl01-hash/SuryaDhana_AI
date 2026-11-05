# GS-P1 · GLD daily tonnes vs COMEX gold — result tables

Generated 2026-11-04T22:26 by `scripts/gold_studies/gs_p1_gld_tonnes.py` from the plan in `PLAN.md`. Trust dates 5515 (2004-11-18 → 2026-10-22), 5515 with a COMEX entry; median lag trust date → entry 1 days (max 5); halves split at 2015-12-31; costs 0.15 % per round trip.

## Forecast tests (signal known at T, entry = close of the first session after T)

IC = Spearman(signal, forward return); t = Newey-West t of the rank slope (lags h−1); tercile cut-offs expanding on past values; OOS = walk-forward long/flat rule after costs vs buy-and-hold scaled to its exposure.

| signal | h | n | ic | t_ic | ic_h1 | t_h1 | ic_h2 | t_h2 | top_mean | bottom_mean | spread | t_spread | oos_from | oos_exposure_pct | oos_excess_pa_pct | oos_t | oos_strat_cagr | oos_bh_cagr | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | 5 | 5510 | 0.01 | −0.13 | 0.02 | 0.52 | −0.01 | −0.78 | 0.26 | 0.18 | 0.08 | 0.69 | 2013-08-27 | 25.80 | −2.31 | −1.80 | −0.17 | 8.23 | FAIL |
| S1 | 20 | 5495 | 0.01 | 0.33 | 0.01 | 0.19 | 0.01 | 0.22 | 1.00 | 0.76 | 0.24 | 0.68 | 2013-08-27 | 31.70 | −1.40 | −1.64 | 1.32 | 8.23 | FAIL |
| S2 | 5 | 5506 | 0.02 | 0.08 | 0.04 | 0.44 | −0.01 | −0.54 | 0.24 | 0.27 | −0.02 | −0.22 | 2013-08-29 | 29.20 | −0.75 | −0.42 | 1.63 | 8.37 | FAIL |
| S2 | 20 | 5491 | 0.02 | 0.75 | 0.01 | 0.44 | 0.03 | 0.68 | 0.83 | 0.87 | −0.04 | 0.02 | 2013-08-29 | 32.50 | −0.94 | −0.77 | 1.83 | 8.37 | FAIL |
| S3 | 5 | 5491 | 0.04 | 1.06 | 0.03 | 0.51 | 0.04 | 1.05 | 0.28 | 0.17 | 0.10 | 0.69 | 2013-09-12 | 25.50 | 2.14 | 1.06 | 4.36 | 8.93 | FAIL |
| S3 | 20 | 5476 | 0.04 | 1.00 | 0.01 | 0.26 | 0.07 | 1.43 | 0.86 | 0.84 | 0.02 | 0.11 | 2013-09-12 | 28.40 | 1.50 | 0.87 | 3.96 | 8.93 | FAIL |

## Robustness: entry one session later (T+2)

| signal | h | n | ic | t_ic | ic_h1 | t_h1 | ic_h2 | t_h2 | top_mean | bottom_mean | spread | t_spread | oos_from | oos_exposure_pct | oos_excess_pa_pct | oos_t | oos_strat_cagr | oos_bh_cagr | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S2 (entry T+2) | 5 | 5505 | 0.03 | 0.68 | 0.05 | 0.70 | 0.01 | 0.11 | 0.33 | 0.24 | 0.09 | 0.43 | 2013-08-29 | 29.20 | 0.41 | 0.24 | 2.80 | 8.26 | FAIL |
| S2 (entry T+2) | 20 | 5490 | 0.02 | 0.83 | 0.01 | 0.39 | 0.03 | 0.91 | 0.83 | 0.86 | −0.03 | 0.04 | 2013-08-29 | 32.60 | −0.80 | −0.67 | 1.94 | 8.26 | FAIL |
| S3 (entry T+2) | 5 | 5490 | 0.04 | 1.10 | 0.03 | 0.37 | 0.04 | 1.35 | 0.29 | 0.18 | 0.11 | 0.68 | 2013-09-12 | 25.50 | 2.18 | 1.08 | 4.37 | 8.86 | FAIL |
| S3 (entry T+2) | 20 | 5475 | 0.04 | 1.01 | 0.01 | 0.26 | 0.07 | 1.42 | 0.86 | 0.85 | 0.01 | 0.09 | 2013-09-12 | 28.70 | 1.47 | 0.86 | 3.94 | 8.86 | FAIL |

## Negative controls (must not PASS)

| signal | h | n | ic | t_ic | ic_h1 | t_h1 | ic_h2 | t_h2 | top_mean | bottom_mean | spread | t_spread | oos_from | oos_exposure_pct | oos_excess_pa_pct | oos_t | oos_strat_cagr | oos_bh_cagr | verdict | control_ok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S3 lagged 60 sessions (placebo) | 5 | 5431 | 0.03 | 1.03 | 0.05 | 0.90 | 0.01 | 0.54 | 0.43 | 0.20 | 0.23 | 1.05 | 2013-11-01 | 24.80 | 1.81 | 0.99 | 4.01 | 9.00 | FAIL | 1 |
| S3 lagged 60 sessions (placebo) | 20 | 5416 | 0.05 | 1.18 | 0.11 | 1.39 | −0.02 | −0.01 | 1.16 | 0.83 | 0.32 | 0.45 | 2013-11-01 | 24.80 | 0.78 | 0.49 | 3.00 | 9.00 | FAIL | 1 |
| S3 shuffled (seed) | 5 | 5491 | −0.01 | −0.39 | −0.01 | −0.18 | −0.00 | −0.40 | 0.26 | 0.29 | −0.03 | −0.34 | 2013-08-28 | 32.90 | −0.97 | −0.98 | 1.94 | 8.37 | FAIL | 1 |
| S3 shuffled (seed) | 20 | 5476 | −0.01 | −0.41 | −0.01 | −0.71 | −0.01 | 0.09 | 0.94 | 1.07 | −0.13 | −0.81 | 2013-08-28 | 32.30 | −0.12 | −0.29 | 2.81 | 8.37 | FAIL | 1 |

## Description (not a forecast)

Same day: Spearman 0.185 (h1 0.145, h2 0.228, n 5514). Same week: 0.294 (h1 0.281, h2 0.310, n 1144) → PASS as description.

| k_sessions | spearman | reads |
|---|---|---|
| −5 | 0.01 | tonnes lead price |
| −4 | −0.01 | tonnes lead price |
| −3 | 0.01 | tonnes lead price |
| −2 | 0.01 | tonnes lead price |
| −1 | 0.06 | tonnes lead price |
| 0 | 0.18 | same day |
| 1 | 0.11 | price leads tonnes |
| 2 | 0.08 | price leads tonnes |
| 3 | 0.05 | price leads tonnes |
| 4 | 0.04 | price leads tonnes |
| 5 | 0.06 | price leads tonnes |

## Overall: **CONTEXT-ONLY** (controls ok: True)
