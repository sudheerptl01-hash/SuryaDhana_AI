# SuryaDhana 5-year walk-forward: the decisive evidence

**Date:** 2026-10-19 · **From:** scale-up lead · **Code:** `ml/scale5y.py` (core duel), `ml/scale5y_nested.py` (nested selection and nested models), `ml/scale5y_report.py` (league, bootstrap, regimes, portfolio, gates). Seed 108, 2 threads per process.
**Numbers:** `scale5y_summary.json`, `bootstrap_5y.json`, `regimes_5y.json` / `regimes_5y.md`, `portfolio_5y.json`, `nested_selection.json`; every table is in `tables.md`.

## Verdict

**No model is promoted.** On the five pre-registered gates, nested_lgbm passes 0, all51 passes 0 and nested_ensemble_rank passes 1.

- **The signal is real and small.** Honest nested LightGBM scores CV AUC **0.5359** over 43 monthly folds (20-session block-bootstrap 95% CI [0.5250, 0.5483]). Its rank-IC is +0.065 (Newey–West t 6.0, positive in 38 of 43 months).
- **The clean figure is the 39-fold mean.** The configuration was fixed on Apr–Jul 2026, so the folds from 2023-01 to 2026-03 are the only ones it never saw. There it scores 0.5364.
- **It is no better than the simpler alternatives.** LightGBM on all 50 features scores 0.5366 (Δ −0.0007, CI [−0.0052, +0.0038]). An L2 logistic scores 0.5415 (Δ −0.0056, CI [−0.0150, +0.0024]).
- **No single machine-learning model's long-only book beats the equal-weight (EW) universe** net of 20 bps. The nested_lgbm top decile trails it by 0.7%/yr and beats it in only 20 of 45 months. Only the one-feature momentum baselines' liquid books edge out EW-liquid (+1.5% to +2.0%/yr, IR ≤ 0.26, CIs spanning zero).
- **The ensemble is the one economic exception.** The pre-registered rank-average ensemble earns +7.0%/yr over EW (IR 1.26, CI [0.32, 2.37]), positive in every calendar year. It still fails 4 of 5 gates, including the deflated Sharpe (DSR 0.16 at N = 177).

## Protocol as run

- **Data.** The 5-year dataset has 1,357,383 rows and 2,480 tickers. There are 43 purged monthly folds (2023-01 to 2026-07, 22-session embargo) and a holdout (2026-08-03 to 09-16). Each fold trains on a rolling 504-session window.
- **Exit-date purge (audit T3).** Training rows whose label exit (the ticker's own row t+21) falls on or after test_start are dropped. That removed **143 rows** across the 44 nested fits, out of 21.6M training-row instances; 36 of them were in fold 2023-09. The core-duel models were run without the purge, and the same 143 rows sit in their windows.
- **Nested selection (audit T11's code path).** Once per year, the pilot's method was rerun using only data dated on or before that year's first train_end: univariate AUC, LightGBM gain and permutation importance, redundancy clusters, combined rank.
  - **Candidates:** 52, i.e. the 50 base features plus `amihud_20` and `deliv_value_share_20`, rebuilt from the DuckDB read-only.
  - **Choice of k:** k ∈ {5, 8, 10, 15}, picked by mean AUC over three inner 21-session blocks, each with its own embargo and purge.
  - **Window start:** every window starts on 2022-01-03. The 5-year dataset has only 43 labeled sessions before the 2023-01 train_end, so 2022 rows were rebuilt with ml/data.py's code; they are bit-identical to the dataset where the two overlap. These rows joined every year's selection window, which matters for 2023 and 2024. Models train on dataset rows only.
- **Small training sets in 2023.** The window is truncated until about 2024-10: 41,732 rows (2023-01), 145,984 (2023-06), 292,578 (2023-12), and the full 580,275 only from 2024-10. The 2023 AUCs are therefore small-training-set results. They stay in the headline because the 43 folds were pre-registered; the 2024-10+ column is post-hoc.
- **nested_ensemble_rank.** This is the per-date rank average of three models, all trained on the **per-year nested sets**, not on all features:
  - nested_lgbm;
  - LGBMRanker with lambdarank, relevance = floor(10·y_rank_20d);
  - CatBoost with 600 fixed trees.

  The nested sets match the registered spec and isolate the learner effect in the ensemble-vs-nested_lgbm comparison. They also avoid the pilot's 51-feature ranker and CatBoost variants, which failed.

## League (43 folds + holdout)

| model | CV AUC ± sd | 39-fold (clean) | post-hoc 2024-10+ | folds ≥ 0.50 | worst fold | 2023 | 2024 | 2025 | 2026 Jan–Jul | CV 95% CI | holdout (decile spread) |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| **nested_lgbm** | 0.5359 ± 0.0409 | 0.5364 | 0.5455 | 86% | 2026-03 0.4306 | 0.5170 | 0.5363 | 0.5565 | 0.5325 | [0.5250, 0.5483] | 0.5283 (−0.61%) |
| **nested_ensemble_rank** | 0.5330 ± 0.0355 | 0.5320 | 0.5412 | **91%** | 2025-01 0.4626 | 0.5204 | 0.5294 | 0.5432 | 0.5432 | [0.5232, 0.5438] | **0.5525 (+2.86%)** |
| nested_catboost (member) | 0.5378 ± 0.0433 | 0.5386 | 0.5460 | 86% | 2026-03 0.4264 | 0.5190 | 0.5405 | 0.5569 | 0.5330 | — | 0.5291 (−0.51%) |
| nested_lambdarank (member) | 0.5032 ± 0.0448 | 0.4992 | 0.5045 | 58% | 2025-01 0.3607 | 0.5135 | 0.4900 | 0.4833 | 0.5423 | — | 0.5724 (+6.68%) |
| nested_lr_l2 | 0.5430 ± 0.0644 | 0.5456 | 0.5524 | 79% | 2026-03 0.3667 | 0.5126 | 0.5533 | 0.5766 | 0.5197 | [0.5263, 0.5620] | 0.5170 (−0.90%) |
| all51 | 0.5366 ± 0.0426 | 0.5376 | 0.5445 | 81% | 2026-03 0.4528 | 0.5092 | 0.5505 | 0.5524 | 0.5325 | [0.5254, 0.5498] | 0.5327 (−0.61%) |
| champion10 (look-ahead reference) | 0.5251 ± 0.0379 | 0.5240 | 0.5340 | 72% | 2025-05 0.4486 | 0.4979 | 0.5379 | 0.5343 | 0.5337 | [0.5150, 0.5362] | 0.5292 (−0.43%) |
| lr_l2 | 0.5415 ± 0.0602 | 0.5441 | 0.5514 | 81% | 2026-03 0.3792 | 0.5148 | 0.5487 | 0.5730 | 0.5210 | [0.5257, 0.5592] | 0.5091 (−3.62%) |
| baseline_mom | 0.4951 ± 0.0354 | 0.4956 | 0.4881 | 40% | 2026-03 0.4071 | 0.5016 | 0.4997 | 0.4885 | 0.4875 | [0.4851, 0.5053] | 0.5302 (+2.95%) |
| momentum rank (no fit) | 0.5017 ± 0.0357 | 0.5029 | 0.5010 | 47% | 2026-03 0.4071 | 0.5016 | 0.4997 | 0.5122 | 0.4875 | [0.4924, 0.5121] | 0.5302 |

Mean training rows per fold were 162k in 2023, 476k in 2024, 679k in 2025 and 719k in 2026. The sd uses ddof = 0, as in the harness JSON (nested_lgbm 0.040947). The bootstrap draws 45 blocks of 20 sessions per replicate over the pooled 881 test dates, B = 1000, with identical draws for every model.

## Nested selection

| year | window (sessions) | k | selected | ∩ pilot 10 |
|---|---|---:|---|---:|
| 2023 | 2022-01-03 → 2022-12-01 (227) | 15 | cs_rank_mom_20, macd_norm, ret_126d, vol_20, mom_10, vol_z_20, vol_10, atr_pct, dist_52w_low, deliv_pct, vol_ratio_20, amihud_20, mom_20, deliv_value_share_20, range_pct | 4 |
| 2024 | → 2023-11-29 (472) | 5 | dist_52w_high, deliv_value_share_20, amihud_20, ret_252d, vol_20 | 1 |
| 2025 | → 2024-11-29 (719) | 15 | dist_52w_high, amihud_20, cs_rank_vol_20, deliv_pct_sma_20, dist_52w_low, mom_12_1, ret_63d, cs_rank_turnover, deliv_pct, dist_sma_20, atr_pct, vol_ratio_20, mom_20, cs_rank_ret_126, mom_10 | 8 |
| 2026 | → 2025-12-01 (966) | 5 | deliv_value_share_20, atr_pct, dist_52w_high, amihud_20, vol_20 | 2 |

- Consecutive years share only **4, 4 and 5** of their top-10 features, and k swings between 15 and 5.
- **amihud_20** is the only feature selected in all four years; **deliv_value_share_20** is selected in three. Both sufficiency survivors therefore earn a place under honest selection.

## Regimes

Regimes are defined from market data only, before any AUC was split by them:

- **Direction:** the sign of the EW universe's forward 20-day return over the month's signal dates.
- **Volatility:** the EW daily-return volatility in the month, high when above the 43-month median of 16.6%.

| regime (CV months) | months | mean n_train | nested_lgbm | all51 | ensemble | lr_l2 | momentum | nested_lgbm top decile − EW (20d, gross) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| up | 29 | 452k | 0.5191 | 0.5202 | 0.5246 | 0.5101 | 0.4910 | −0.31% |
| down | 14 | 552k | 0.5708 | 0.5704 | 0.5506 | 0.6067 | 0.5239 | +1.45% |
| low-vol / high-vol | 22 / 21 | 428k / 544k | 0.5473 / 0.5239 | 0.5475 / 0.5251 | 0.5409 / 0.5248 | 0.5599 / 0.5222 | 0.5101 / 0.4929 | +0.67% / −0.17% |
| 2025-09 → 2026-02 run | 6 | 708k | 0.6087 | 0.6084 | 0.5993 | 0.6322 | 0.5381 | +2.14% |
| 2026-03 (EW +9.2%, vol 33%) | 1 | 717k | 0.4306 | 0.4528 | 0.4657 | 0.3792 | 0.4071 | −3.93% |
| 43 months ex 2025-09 → 2026-03 | 36 | 441k | 0.5267 | 0.5269 | 0.5238 | 0.5309 | 0.4983 | +0.07% |

- **One episode lifts the five-year mean.** The run (five of its six months down, four of them low-vol) carries every model to about 0.58–0.63. Without it and March 2026, nested_lgbm averages 0.5267.
- **March 2026 was a V-shaped rebound after the February sell-off.** That month, 62% of features had their IC against its usual sign. Every model collapsed to 0.37–0.47, except the high-volatility LambdaRank (0.567).
- **Inversions recur.** Six of 43 months had a majority of features inverted (2023-07, 2024-01, 2025-04, 2025-05, 2026-03, 2026-04). Two other months, 2025-05 and 2026-03, were at least as inverted as April 2026 (inverted share 0.57).

## Portfolio

The portfolio covers the combined out-of-sample period: 913 signal dates, 2023-01-02 to 2026-09-16, net of 20 bps per side, using the ml/strategy_backtest.py engine.

**N was fixed in the code before any portfolio number existed: N = 177.** It counts:

- 10 model configurations on these folds;
- 24 books;
- the pilot's 77 configurations (audit T7);
- the pilot's 66 portfolio cells.

| book | ann. return | excess vs EW | Sharpe [95% CI] | IR [95% CI] | max DD | turnover | months > 0 | PSR | DSR |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| *EW universe (passive)* | +19.4% | — | 0.69 [−0.27, 1.80] | — | −27.8% | 7% | — | — | — |
| nested_lgbm top decile | +18.7% | −0.7% | 0.73 [−0.19, 1.75] | −0.11 [−1.21, 0.96] | −27.0% | 67% | 20/45 | 0.42 | 0.000 |
| nested_lgbm liquid top decile | +16.3% | −3.4% | 0.56 | −0.53 [−1.56, 0.45] | −29.3% | 72% | 18/45 | 0.16 | 0.000 |
| nested_lgbm long–short | +8.9% | (L–S) | 0.97 [−0.12, 2.10] | — | −9.8% | 67% | 25/45 | 0.97 | 0.056 |
| all51 top decile | +18.2% | −1.2% | 0.71 | −0.21 [−1.37, 0.94] | −27.9% | 68% | 20/45 | 0.35 | 0.000 |
| all51 long–short | +7.7% | (L–S) | 0.84 [−0.36, 1.99] | — | −15.0% | 68% | 25/45 | 0.95 | 0.033 |
| **ensemble top decile** | +26.5% | **+7.0%** | 0.99 [0.06, 2.10] | **1.26 [0.32, 2.37]** | −28.9% | 70% | 33/45 | 0.99 | 0.163 |
| ensemble liquid top decile (paper book) | +25.5% | +5.7% | 0.88 [−0.01, 1.88] | 0.85 [−0.21, 1.99] | −29.1% | 77% | 29/45 | 0.94 | 0.040 |
| ensemble long–short | +16.0% | (L–S) | **1.77 [0.82, 2.91]** | — | −8.3% | 70% | 34/45 | 1.00 | **0.490** |
| lr_l2 top decile | +16.5% | −2.9% | 0.71 | −0.31 | −20.1% | 43% | 17/45 | 0.28 | 0.000 |
| momentum rank top decile | +19.2% | −0.2% | 0.60 | +0.09 | −29.6% | 87% | 25/45 | 0.57 | 0.001 |

- **Costs.** At 10 / 40 bps, the ensemble's top-decile excess is +8.8% / +3.4%; nested_lgbm's is +1.0% / −4.1%.
- **Capacity.** The full ensemble top decile can carry about ₹245 cr; 30% of its names trade under ₹5 cr a day. The liquid book can carry about ₹1,050 cr.
- **Deflation.** The expected maximum Sharpe at N = 177 is 1.79/yr, which every book misses. With only the 34 trials of this run, the ensemble long–short book's DSR would be 0.75.

## Gates (as pre-registered in SCALE_UP.md)

| gate | nested_lgbm | all51 | nested_ensemble_rank |
|---|---|---|---|
| 1. beats lr_l2 on CV mean, CI excludes 0 | −0.0056 [−0.0150, +0.0024] **FAIL** | −0.0050 [−0.0155, +0.0039] **FAIL** | −0.0085 [−0.0222, +0.0027] **FAIL** |
| 2. fold AUC ≥ 0.50 in ≥ 90% of months | 86% (37/43) **FAIL** | 81% (35/43) **FAIL** | 91% (39/43) **PASS** |
| 3. top decile beats EW in ≥ 75% of months, net 20 bps | 20/45 = 44% **FAIL** | 20/45 = 44% **FAIL** | 33/45 = 73% **FAIL** |
| 4. selected-feature overlap ≥ 7/10 across years | 4, 4, 5 **FAIL** | 4, 4, 5* **FAIL** | 4, 4, 5 **FAIL** |
| 5. DSR ≥ 0.95, liquid top decile, N = 177 | 0.000 **FAIL** | 0.000 **FAIL** | 0.040 **FAIL** |

\*all51 selects nothing, so read literally the test is vacuous. It is scored on the same yearly re-selection because the gate asks for a stable signal.

**Post-hoc, not a gate.** On stability, lr_l2 has sd 0.060 against 0.043 (all51) and 0.036 (ensemble), a worst fold of 0.379 against 0.453 and 0.463, and a holdout decile spread of −3.6% against −0.6% and +2.9%. The gate verdicts above stand as scored.

## The five questions

**(a) Why the pilot's 10 features underperformed all features, and whether selection buys anything.**

- **The pilot's 10 lose to all features.** all51 beats champion10 by +0.0115 (CI [+0.0071, +0.0159]), wins 32 of 43 folds, and champion10 averages 0.4979 in 2023.
- **They were chosen on Apr–Jul 2026, the regime after the March break.** Honest yearly selection keeps only 1–8 of them, and its own choices change by half each year. A set fitted to one regime discards information that matters in others: liquidity, delivery value, distance from the 52-week low.
- **Selection buys nothing over LightGBM on all features:** −0.0007 (CI [−0.0052, +0.0038]), 18 of 43 folds won, holdout −0.0045. It only helped in 2023, with small training sets (0.5170 against 0.5092, post-hoc).

**(b) The lr_l2 paradox.**

- **What lr_l2 is.** It is the purest defensive-factor ranker in the league. Its per-date score correlation is −0.50 with atr_pct, −0.45 with Amihud and +0.49 with the 52-week high; LightGBM's are −0.30, −0.29 and +0.25.
- **Why its AUC is high.** AUC rewards that tilt when markets fall (0.607 in down months, 0.632 in the run) and punishes it in rebounds (0.379 in March 2026). Fourteen down months, five of them inside the 2025-09 → 2026-02 run, give it the top CV mean, though not significantly so.
- **Why it trades badly.** Its extremes are factor extremes that do not out-earn EW: the top decile is −2.9%/yr and beats EW in only 17 of 45 months. In the holdout, its bottom decile was its best decile (+4.0% per 20 days).

**(c) AUC versus tradability.**

- **The negative holdout spreads come from one 32-day window.** Over 43 folds the ML decile spreads are positive: nested_lgbm +1.32% per 20 days in 33 of 43 folds, all51 +1.25% in 30. Momentum manages +0.27% (positive in 24 folds) with CV AUC 0.495–0.502. The ensemble, also an ML model, had a positive holdout spread (+2.86%).
- **The deeper lesson holds over five years.** AUC 0.536 with IC t 6 coexists with no long-only edge. The label "beat the universe median" rewards low-volatility names, which cross the median often. But they do not beat the mean of a right-skewed, rising universe, so the classifiers' top deciles are defensive: nested_lgbm's trails EW by 0.58% per 20 days in up months, net of costs.
- **The ensemble shows the fix.** Adding the high-volatility LambdaRank makes the score volatility-neutral (correlation with atr_pct −0.05). That costs 0.003 AUC and turns −0.7% into +7.0%/yr.
- **AUC is necessary but not sufficient.** Models should be judged on net excess versus EW.

**(d) Recommended feature set and model, for paper trading only.**

- **Scorer: nested_ensemble_rank as tested.** Yearly honest re-selection over the 52 candidates, including amihud_20 and deliv_value_share_20, then three fixed-budget learners and a per-date rank average. It is the only book whose excess return has a CI clear of zero. It is positive in every year (+0.43% to +0.71% per 20 days), has a beta of 1.01 to EW, has the most stable folds and has the best holdout among the candidates.
- **Single-model reference: LightGBM on all 50 base features.** It matches nested_lgbm on AUC and is simpler.
- **Drop:** champion10, lr_l2 as a scorer (keep it as a drift monitor) and momentum as anything other than a benchmark.

**(e) What the program still cannot claim.**

- That machine learning beats a linear model.
- That any model is reliable month to month: the single-model candidates (nested_lgbm, all51, lr_l2, nested_lr_l2) fall below 0.50 in 6–9 of 43 months, and every candidate did in March 2026 (only the high-volatility LambdaRank member did not).
- That any book survives multiple testing: the best DSR is 0.49, for a long–short book that needs shorts NSE cash offers only on about 200 F&O names.
- That the ensemble's +7%/yr is skill rather than a favourable factor mix over 45 months of one, mostly rising, market.
- Fully clean out-of-sample results: the configurations were fixed on 2026-04..07, 2023 used small training sets, and prices are not adjusted for corporate actions.

## Management-safe statement

> "Over five years of monthly walk-forward tests (43 months, January 2023 to July 2026, plus a six-week holdout), our models ranked NSE stocks by 20-day relative performance better than chance — AUC about 0.536, rank correlation about 0.065 — and the signal is not a data or code artefact. None of them meets the promotion criteria we fixed in advance. They are not better than a simple logistic regression. Every candidate model failed in the March-2026 rebound. Their feature choices change from year to year. No portfolio passes the multiple-testing-adjusted Sharpe test. No single model's top-ranked tenth of stocks beat simply holding the whole universe equally weighted after costs. A pre-registered three-model blend did, by about 7% a year, in every year, but it fails four of the five criteria. That justifies paper trading the blend; it does not justify capital."

## What to do next

1. **Paper-trade the ensemble's liquid book as one frozen, pre-registered strategy** from November 2026, with no new trials: a fresh test with N = 1. The five-year history cannot reach DSR 0.95, because the expected maximum Sharpe at N = 177 (1.79/yr) is above the book's IR of 0.85. At that IR, PSR 95% needs about 4 years (994 sessions) of track record.
2. **Run a pre-registered test of volatility-neutral construction:** each classifier's score residualised on volatility and size per date, with a pass mark fixed in advance. The ensemble suggests this is where the money is.
3. **A/B test all51 plus amihud_20 and deliv_value_share_20** with a fixed pass mark.
4. **Test the short side only where it exists:** long–short restricted to F&O names via stock futures, with borrow costs and costs at 40 bps.
5. **Address the March-2026 failure mode** with market-state inputs (queued in SCALE_UP.md) and a monthly feature-inversion monitor (6 of 43 months). Then extend the history before 2021 and add corporate-action adjustment.
