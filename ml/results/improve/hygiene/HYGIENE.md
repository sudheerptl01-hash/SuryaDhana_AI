# SuryaDhana improvement phase, stream P5: backtest overfitting, delivery durability, label uniqueness

**Date:** 2026-10-19 · **Owner:** hygiene stream (P5) · **Code:** `ml/hygiene/` (`pbo.py`, `delivery.py`, `uniqueness.py`, `report.py`) · **Numbers:** `pbo.json`, `delivery_durability.json`, `uniqueness.json` in this folder; run log `log.txt`. Inputs are the frozen five-year artefacts, read-only; `nse_market.duckdb` was not opened. Seed 108, 2 threads. Governing plan: `ml/IMPROVEMENT_PLAN.md` §2-P5 (readings fixed before any result). This stream adds no trial to the ledger: nothing here fits a model or scores a test month for selection.

## Pre-registered readings

| test | reading fixed in advance | result | verdict |
|---|---|---|---|
| PBO (a) Configurations | PBO > 0.5 ⇒ selection no better than chance | PBO = 0.248 (other partitions 0.137 to 0.264) | **PASS**: selection better than chance |
| PBO (b) Books | PBO > 0.5 ⇒ selection no better than chance | PBO = 0.184 (other partitions 0.036 to 0.063) | **PASS**: selection better than chance |
| PBO (c) Long-only books | PBO > 0.5 ⇒ selection no better than chance | PBO = 0.227 (other partitions 0.042 to 0.165) | **PASS**: selection better than chance |
| Delivery `deliv_pct_sma_20` | residual IC CI > 0 in ≥ 3 of 4 years and in both liquidity halves | 3 of 4 years; halves both | **PASS** |
| Delivery `deliv_value_share_20` | residual IC CI > 0 in ≥ 3 of 4 years and in both liquidity halves | 4 of 4 years; halves both | **PASS** |
| Uniqueness, fold 2025-01 | near-constant (≥ 95% of rows within ±10% of 1/21) ⇒ weights cannot change the fit; item closes | 87.5% within ±10% | **FAIL: stays open** |

## For management

1. **Choosing the best model or book from the five-year record was better than a coin toss, but the winner's record overstates what it delivers next.** The in-sample winner finished at or below the out-of-sample median in only 25% (models), 18% (all books) and 23% (long-only books) of the 12,870 splits, against 50% to 56% for pure luck. The winning model was usually the nested L2 logistic (72% of splits); the winning books were mostly the rank ensemble's (70% of splits among all books, 80% among long-only books). Their out-of-sample Sharpe was about 29% (all books) and 21% (long-only) of the in-sample figure, and in 33% of splits the winning long-only book lost to its benchmark out of sample. The ranking is informative; the size of past performance is inflated. This is consistent with paper-trading an ensemble book; it does not change the no-capital verdict.

2. **The delivery signal passes the durability test, but only the part that is not liquidity, volatility or momentum.** That residual signal is positive with an interval clear of zero in 3 of 4 years (`deliv_pct_sma_20`) and 4 of 4 (`deliv_value_share_20`), in illiquid and liquid names, and it did not weaken after March 2026 (+0.046 before, +0.042 after). The raw signal is less dependable: close to zero in 2023 (+0.006) and in rising months (+0.013 vs +0.124 in falling months), and its drop after March 2026 (+0.059 to +0.012) came from the part of delivery that volatility, turnover and momentum explain (delivery leans to low-volatility, lower-turnover names), not from the delivery-specific part. Among the most liquid third of stocks it is essentially a falling-market effect (residual IC +0.003 in up months, +0.089 in down months).

3. **Overlapping 20-day labels mean the 641,030 training rows of the 2025-01 fold hold only about 33,932 non-overlapping labels (19 times fewer), and uniqueness weights do not fix that.** The weights equal 1/21 for 82% of rows and differ only at the edges of the training window and for illiquid names drifting in and out of the universe. Because 12.5% of rows deviate by more than 10%, more than the 5% allowed in advance, the item does not close on this evidence. The cheapest decisive next step is the plan's AB7 fit (every fifth signal date), or one uniqueness-weighted fit. Either would be a new trial.

## 1. Probability of backtest overfitting (`pbo.json`)

**Method.** CSCV (Bailey, Borwein, López de Prado & Zhu 2017), generic code in `ml/hygiene/pbo.py`. The T periods are cut into S = 16 contiguous blocks of equal length (L = T // 16 = 2), the remainder is dropped from the end, and all C(16, 8) = 12,870 in-sample/out-of-sample splits are enumerated. In each split the trial with the best in-sample statistic (mean fold AUC; Sharpe = mean / sd of the monthly series) is ranked among all M trials out of sample; r = (rank − 0.5) / M, logit = ln(r / (1 − r)); **PBO = share of logits ≤ 0**. Also: the degradation regression (OOS statistic of the in-sample best on its IS statistic), the probability of loss (OOS below zero skill, i.e. below 0 for returns and below 0.5 for AUC, and below the median of the M trials), and first-order stochastic dominance of the in-sample best's OOS distribution over the pooled OOS distribution of all trials. A self-test (exact agreement with a brute-force loop; null simulations at the chance level; a known-skill simulation with mean PBO 0.075) passed before any real input was read.

**Dropped months.** With T = 43 (configurations) or 45 (books) and S = 16, equal blocks are 2 periods long and the primary analysis uses 32 periods (2023-01..2025-08): 11 folds (2025-09..2026-07) or 13 months (2025-09..2026-09) are dropped from the end. The dropped stretch holds the 2025-09..2026-02 run and the March-2026 inversion, so the sensitivity variants that keep it are reported next to the reading.

**Near-duplicate trials.** baseline_mom and heuristic_mom20 books are identical in 36 (top_decile), 36 (ls_decile), 39 (liq_top_decile) of 45 months (one-feature logistic on the momentum rank vs the momentum rank itself), so 3 pairs among the 24 books are near-duplicates; OOS ties are average-ranked, which is why some OOS ranks are fractional.

### (a) Configurations: 9 models × monthly fold AUC

Input: fold AUC, 43 monthly folds 2023-01..2026-07 (holdout excluded) x 9 models. Statistic: IS/OOS mean of fold AUC.

| | **S = 16, drop end (reading)** | S = 16, drop start | S = 16, all periods (blocks of 2–3) | S = 14, drop end |
|---|---:|---:|---:|---:|
| periods used | 32 (2023-01..2025-08) | 32 (2023-12..2026-07) | 43 (2023-01..2026-07) | 42 (2023-01..2026-06) |
| periods dropped | 11 | 11 | 0 | 1 |
| **PBO (logit ≤ 0)** | **0.248** | **0.137** | **0.248** | **0.264** |
| PBO strict (logit < 0) / mid-rank | 0.082 / 0.165 | 0.050 / 0.093 | 0.122 / 0.185 | 0.134 / 0.199 |
| chance level of PBO (≤ 0 rule) | 0.556 | 0.556 | 0.556 | 0.556 |
| logit mean / median / sd | +1.56 / +1.61 / 1.27 | +1.70 / +1.61 / 1.14 | +1.36 / +1.61 / 1.18 | +1.25 / +1.61 / 1.15 |
| logit 5% / 95% | -0.45 / +2.83 | -0.45 / +2.83 | -0.45 / +2.83 | -0.45 / +2.83 |
| mean OOS rank fraction of IS-best | 0.762 | 0.794 | 0.741 | 0.726 |
| IS-best: mean IS → mean OOS statistic | 0.5366 → 0.5302 | 0.5546 → 0.5493 | 0.5439 → 0.5390 | 0.5434 → 0.5381 |
| degradation slope / intercept (R²) | -0.580 / +0.841 (0.43) | -0.758 / +0.970 (0.71) | -0.741 / +0.942 (0.68) | -0.761 / +0.952 (0.74) |
| P(OOS of IS-best below zero skill) | 0.000 | 0.000 | 0.000 | 0.000 |
| P(OOS of IS-best below trials' OOS median) | 0.082 | 0.050 | 0.122 | 0.134 |
| first-order dominance holds | no (max CDF excess 0.0087) | no (max CDF excess 0.0037) | no (max CDF excess 0.0047) | no (max CDF excess 0.013) |
| second-order dominance holds | yes | yes | yes | yes |
| mean OOS: IS-best vs all trials | 0.5302 vs 0.5199 | 0.5493 vs 0.5341 | 0.5390 vs 0.5280 | 0.5381 vs 0.5274 |

Who is the in-sample best (primary partition): `nested_lr_l2` 71.9% of splits (mean OOS rank fraction 0.83); `all51` 12.6% of splits (mean OOS rank fraction 0.49); `nested_catboost` 6.7% of splits (mean OOS rank fraction 0.67); `lr_l2` 5.7% of splits (mean OOS rank fraction 0.78); `nested_ensemble_rank` 2.7% of splits (mean OOS rank fraction 0.33).

**Pre-registered reading:** PBO = 0.248 (not above 0.5): by the pre-registered reading, selection among these 9 model configurations was better than chance. PBO at or below 0.5 says only that the in-sample best usually finished in the out-of-sample top half; it is not by itself evidence of skill. With M = 9 (odd) the chance level of the 'lambda <= 0' rule is 0.556; strict rule PBO = 0.082, mid-rank PBO = 0.165 (chance 0.5). **PASS** (PASS = PBO not above 0.5).

### (b) Books: 24 books × monthly net-of-20-bps value

Input: monthly_20bps, 45 months 2023-01..2026-09 x 24 books; long-only = net 20d return minus the book's EW benchmark (ew_universe or ew_liquid); long-short = own net 20d return. Statistic: IS/OOS Sharpe (mean / sd, ddof 1) of the monthly series, not annualised.

| | **S = 16, drop end (reading)** | S = 16, drop start | S = 16, all periods (blocks of 2–3) | S = 14, drop end |
|---|---:|---:|---:|---:|
| periods used | 32 (2023-01..2025-08) | 32 (2024-02..2026-09) | 45 (2023-01..2026-09) | 42 (2023-01..2026-06) |
| periods dropped | 13 | 13 | 0 | 3 |
| **PBO (logit ≤ 0)** | **0.184** | **0.061** | **0.036** | **0.063** |
| PBO strict (logit < 0) / mid-rank | 0.184 / 0.184 | 0.061 / 0.061 | 0.036 / 0.036 | 0.063 / 0.063 |
| chance level of PBO (≤ 0 rule) | 0.500 | 0.500 | 0.500 | 0.500 |
| logit mean / median / sd | +1.47 / +1.47 / 1.74 | +2.48 / +2.71 / 1.58 | +3.48 / +3.85 / 1.05 | +3.05 / +3.85 / 1.43 |
| logit 5% / 95% | -1.61 / +3.85 | -0.08 / +3.85 | +0.42 / +3.85 | -0.25 / +3.85 |
| mean OOS rank fraction of IS-best | 0.730 | 0.850 | 0.941 | 0.898 |
| IS-best: mean IS → mean OOS statistic | 0.5315 → 0.1563 | 0.6757 → 0.4450 | 0.6833 → 0.6147 | 0.6309 → 0.4966 |
| degradation slope / intercept (R²) | -0.335 / +0.334 (0.07) | -0.657 / +0.889 (0.26) | -0.738 / +1.119 (0.34) | -0.648 / +0.905 (0.21) |
| P(OOS of IS-best below zero skill) | 0.292 | 0.101 | 0.027 | 0.068 |
| P(OOS of IS-best below trials' OOS median) | 0.184 | 0.061 | 0.036 | 0.063 |
| first-order dominance holds | no (max CDF excess 0.0007) | no (max CDF excess 1.9e-05) | yes | yes |
| second-order dominance holds | yes | yes | yes | yes |
| mean OOS: IS-best vs all trials | 0.1563 vs -0.0391 | 0.4450 vs 0.0677 | 0.6147 vs 0.0193 | 0.4966 vs 0.0345 |

Who is the in-sample best (primary partition): `nested_ensemble_rank|ls_decile` 54.4% of splits (mean OOS rank fraction 0.91); `nested_lr_l2|ls_decile` 11.4% of splits (mean OOS rank fraction 0.62); `nested_ensemble_rank|liq_top_decile` 9.9% of splits (mean OOS rank fraction 0.43); `lr_l2|ls_decile` 6.7% of splits (mean OOS rank fraction 0.48); `nested_lgbm|ls_decile` 6.1% of splits (mean OOS rank fraction 0.67).

**Pre-registered reading:** PBO = 0.184 (not above 0.5): by the pre-registered reading, selection among these 24 books was better than chance. PBO at or below 0.5 says only that the in-sample best usually finished in the out-of-sample top half; it is not by itself evidence of skill. **PASS** (PASS = PBO not above 0.5).

### (c) Long-only books: 16 books × monthly net excess over EW

Input: the 16 long-only books of (b): top_decile vs ew_universe, liq_top_decile vs ew_liquid. Statistic: IS/OOS Sharpe (mean / sd, ddof 1) of the monthly series, not annualised.

| | **S = 16, drop end (reading)** | S = 16, drop start | S = 16, all periods (blocks of 2–3) | S = 14, drop end |
|---|---:|---:|---:|---:|
| periods used | 32 (2023-01..2025-08) | 32 (2024-02..2026-09) | 45 (2023-01..2026-09) | 42 (2023-01..2026-06) |
| periods dropped | 13 | 13 | 0 | 3 |
| **PBO (logit ≤ 0)** | **0.227** | **0.165** | **0.042** | **0.079** |
| PBO strict (logit < 0) / mid-rank | 0.226 / 0.227 | 0.165 / 0.165 | 0.042 / 0.042 | 0.079 / 0.079 |
| chance level of PBO (≤ 0 rule) | 0.500 | 0.500 | 0.500 | 0.500 |
| logit mean / median / sd | +1.44 / +1.69 / 1.83 | +2.38 / +3.43 / 1.93 | +2.70 / +3.43 / 1.17 | +2.44 / +3.43 / 1.37 |
| logit 5% / 95% | -2.27 / +3.43 | -2.27 / +3.43 | +0.38 / +3.43 | -0.65 / +3.43 |
| mean OOS rank fraction of IS-best | 0.725 | 0.824 | 0.899 | 0.866 |
| IS-best: mean IS → mean OOS statistic | 0.3977 → 0.0852 | 0.4569 → 0.3015 | 0.4938 → 0.3948 | 0.4608 → 0.3355 |
| degradation slope / intercept (R²) | -0.426 / +0.254 (0.09) | -0.848 / +0.689 (0.22) | -0.880 / +0.829 (0.45) | -0.910 / +0.755 (0.43) |
| P(OOS of IS-best below zero skill) | 0.331 | 0.162 | 0.035 | 0.064 |
| P(OOS of IS-best below trials' OOS median) | 0.226 | 0.165 | 0.042 | 0.079 |
| first-order dominance holds | no (max CDF excess 0.0032) | yes | no (max CDF excess 2.9e-05) | no (max CDF excess 0.00027) |
| second-order dominance holds | no | yes | yes | no |
| mean OOS: IS-best vs all trials | 0.0852 vs -0.1173 | 0.3015 vs -0.0229 | 0.3948 vs -0.0615 | 0.3355 vs -0.0417 |

Who is the in-sample best (primary partition): `nested_ensemble_rank|top_decile` 57.3% of splits (mean OOS rank fraction 0.90); `nested_ensemble_rank|liq_top_decile` 23.0% of splits (mean OOS rank fraction 0.67); `heuristic_mom20|liq_top_decile` 8.8% of splits (mean OOS rank fraction 0.33); `nested_lr_l2|top_decile` 4.7% of splits (mean OOS rank fraction 0.31); `baseline_mom|liq_top_decile` 2.7% of splits (mean OOS rank fraction 0.27).

**Pre-registered reading:** PBO = 0.227 (not above 0.5): by the pre-registered reading, selection among these 16 long-only books was better than chance. PBO at or below 0.5 says only that the in-sample best usually finished in the out-of-sample top half; it is not by itself evidence of skill. **PASS** (PASS = PBO not above 0.5).

**Self-test** (`pbo.json` → `self_test`): brute-force agreement on 6 small cases (max logit difference 0.0e+00); null simulations (200 matrices each, T = 32, S = 16): M9_mean mean PBO 0.571 (expected 0.556); M24_sharpe mean PBO 0.489 (expected 0.500); M16_sharpe mean PBO 0.540 (expected 0.500); known-skill simulation mean PBO 0.075. The M = 16 null value at seed 108 (0.540) was re-checked on independent seeds (0.494, 0.507; `log.txt`): sampling noise.

## 2. Delivery durability (`delivery_durability.json`)

**Method.** v1 dataset rows with y_clean_20d True and y_excess_20d present; OOS signal dates 2023-01-02..2026-09-16, pre-OOS 2022-10-03..2022-12-30 reported separately. Per signal date (≥ 100 names), on the complete cases of feature, controls (`log_turnover`, `atr_pct`, `mom_12_1`) and label: IC = Spearman(feature, `y_excess_20d`); residual IC = Spearman of the residual of a per-date OLS of the feature's percentile rank on the controls' percentile ranks. Liquidity subsets re-rank inside the subset. Means over dates with a Newey-West t (20 lags) and a circular 20-session block-bootstrap 95% CI (B = 1000, seed 108). Complete-case coverage: 87.3% (`deliv_pct_sma_20`) and 87.8% (`deliv_value_share_20`) of 1,312,247 universe rows; the loss is mostly names with under a year of history (`mom_12_1` missing). Both delivery features were first identified on the pilot's 16 months (ml/data/, 2025-06-02..2026-09); 2023 and 2024 are the years that played no part in finding them.

The two features are nearly the same signal (mean per-date Spearman 0.92); both lean to low-volatility and lower-turnover names (with `atr_pct` -0.36 / -0.44, with `log_turnover` -0.27 / -0.19). The three controls explain on average 27% / 30% of the cross-sectional variance of the delivery rank.

### By calendar year (all names)

| feature | group | dates | IC | NW t | 95% CI | residual IC | NW t | 95% CI |
|---|---|---:|---:|---:|---|---:|---:|---|
| `deliv_pct_sma_20` | OOS 2023-01-02..2026-09-16 | 913 | +0.0525 | +4.18 | [+0.028, +0.077] | +0.0453 | +5.56 | [+0.029, +0.061] |
| `deliv_pct_sma_20` | pre-OOS 2022-10..12 | 59 | +0.0282 | +1.09 | [-0.014, +0.076] | +0.0182 | +1.46 | [-0.004, +0.041] |
| `deliv_pct_sma_20` | 2023 | 245 | +0.0061 | +0.32 | [-0.026, +0.042] | +0.0180 | +1.12 | [-0.012, +0.048] |
| `deliv_pct_sma_20` | 2024 | 247 | +0.0668 | +3.71 | [+0.034, +0.102] | +0.0561 | +4.36 | [+0.032, +0.083] |
| `deliv_pct_sma_20` | 2025 | 247 | +0.0962 | +3.75 | [+0.043, +0.145] | +0.0595 | +3.75 | [+0.028, +0.089] |
| `deliv_pct_sma_20` | 2026 (to 09-16) | 174 | +0.0354 | +1.37 | [-0.019, +0.079] | +0.0481 | +3.14 | [+0.017, +0.075] |
| `deliv_value_share_20` | OOS 2023-01-02..2026-09-16 | 913 | +0.0587 | +4.73 | [+0.034, +0.084] | +0.0465 | +6.90 | [+0.033, +0.060] |
| `deliv_value_share_20` | pre-OOS 2022-10..12 | 59 | +0.0285 | +1.24 | [-0.011, +0.070] | +0.0164 | +1.34 | [-0.008, +0.039] |
| `deliv_value_share_20` | 2023 | 245 | +0.0186 | +0.96 | [-0.013, +0.056] | +0.0280 | +2.02 | [+0.002, +0.054] |
| `deliv_value_share_20` | 2024 | 247 | +0.0726 | +4.03 | [+0.039, +0.107] | +0.0543 | +4.43 | [+0.032, +0.080] |
| `deliv_value_share_20` | 2025 | 247 | +0.1042 | +4.30 | [+0.057, +0.150] | +0.0581 | +4.86 | [+0.034, +0.081] |
| `deliv_value_share_20` | 2026 (to 09-16) | 174 | +0.0306 | +1.16 | [-0.022, +0.077] | +0.0452 | +3.76 | [+0.021, +0.065] |

### By liquidity (whole OOS window; `cs_rank_turnover`)

| feature | group | dates | IC | NW t | 95% CI | residual IC | NW t | 95% CI |
|---|---|---:|---:|---:|---|---:|---:|---|
| `deliv_pct_sma_20` | tercile < 0.33 (least liquid) | 913 | +0.0803 | +6.58 | [+0.057, +0.104] | +0.0640 | +9.06 | [+0.050, +0.077] |
| `deliv_pct_sma_20` | tercile 0.33–0.67 | 913 | +0.0603 | +5.16 | [+0.038, +0.083] | +0.0485 | +6.59 | [+0.035, +0.063] |
| `deliv_pct_sma_20` | tercile ≥ 0.67 (most liquid) | 913 | +0.0452 | +2.21 | [+0.006, +0.086] | +0.0334 | +2.54 | [+0.008, +0.059] |
| `deliv_pct_sma_20` | illiquid half < 0.5 | 913 | +0.0735 | +6.48 | [+0.051, +0.096] | +0.0602 | +9.26 | [+0.048, +0.073] |
| `deliv_pct_sma_20` | liquid half ≥ 0.5 | 913 | +0.0493 | +2.89 | [+0.017, +0.084] | +0.0359 | +3.27 | [+0.015, +0.057] |
| `deliv_value_share_20` | tercile < 0.33 (least liquid) | 913 | +0.0798 | +6.66 | [+0.057, +0.103] | +0.0578 | +9.42 | [+0.046, +0.070] |
| `deliv_value_share_20` | tercile 0.33–0.67 | 913 | +0.0657 | +6.00 | [+0.044, +0.088] | +0.0492 | +8.30 | [+0.037, +0.061] |
| `deliv_value_share_20` | tercile ≥ 0.67 (most liquid) | 913 | +0.0514 | +2.59 | [+0.014, +0.091] | +0.0406 | +3.61 | [+0.019, +0.063] |
| `deliv_value_share_20` | illiquid half < 0.5 | 913 | +0.0750 | +6.72 | [+0.053, +0.097] | +0.0565 | +10.38 | [+0.046, +0.067] |
| `deliv_value_share_20` | liquid half ≥ 0.5 | 913 | +0.0562 | +3.41 | [+0.024, +0.090] | +0.0414 | +4.53 | [+0.024, +0.060] |

### By market direction of the month (all names)

| feature | group | dates | IC | NW t | 95% CI | residual IC | NW t | 95% CI |
|---|---|---:|---:|---:|---|---:|---:|---|
| `deliv_pct_sma_20` | up months | 587 | +0.0130 | +1.03 | [-0.014, +0.037] | +0.0222 | +2.53 | [+0.004, +0.039] |
| `deliv_pct_sma_20` | down months | 326 | +0.1236 | +10.27 | [+0.101, +0.146] | +0.0868 | +12.16 | [+0.072, +0.101] |
| `deliv_value_share_20` | up months | 587 | +0.0187 | +1.56 | [-0.007, +0.041] | +0.0284 | +3.93 | [+0.013, +0.042] |
| `deliv_value_share_20` | down months | 326 | +0.1306 | +9.82 | [+0.104, +0.154] | +0.0791 | +11.67 | [+0.066, +0.092] |

Direction is `portfolio_5y.json` `direction_by_month`: the sign of the EW universe's forward 20-day return over the month's signal dates. It is known only after the month, so it describes, it does not time.

### Year × liquidity half and the most liquid tercile: IC and residual IC with 95% CI, by year and by market direction

| feature | subset | statistic | 2023 | 2024 | 2025 | 2026 | up months | down months |
|---|---|---|---|---|---|---|---|---|
| `deliv_pct_sma_20` | illiquid half | residual IC | +0.046 [+0.024, +0.067] | +0.056 [+0.038, +0.076] | +0.081 [+0.054, +0.107] | +0.058 [+0.034, +0.079] | +0.040 [+0.027, +0.051] | +0.097 [+0.084, +0.111] |
| `deliv_pct_sma_20` | illiquid half | IC | +0.040 [+0.013, +0.068] | +0.072 [+0.046, +0.100] | +0.127 [+0.082, +0.170] | +0.047 [-0.006, +0.093] | +0.033 [+0.011, +0.053] | +0.146 [+0.122, +0.169] |
| `deliv_pct_sma_20` | liquid half | residual IC | -0.002 [-0.045, +0.043] | +0.059 [+0.026, +0.096] | +0.047 [+0.008, +0.082] | +0.040 [+0.002, +0.077] | +0.008 [-0.017, +0.033] | +0.086 [+0.064, +0.106] |
| `deliv_pct_sma_20` | liquid half | IC | -0.013 [-0.063, +0.044] | +0.077 [+0.033, +0.127] | +0.102 [+0.038, +0.163] | +0.023 [-0.046, +0.080] | -0.005 [-0.041, +0.027] | +0.148 [+0.120, +0.174] |
| `deliv_pct_sma_20` | most liquid tercile | residual IC | -0.002 [-0.053, +0.050] | +0.062 [+0.022, +0.109] | +0.039 [-0.008, +0.081] | +0.035 [-0.013, +0.082] | +0.003 [-0.028, +0.031] | +0.089 [+0.060, +0.114] |
| `deliv_pct_sma_20` | most liquid tercile | IC | -0.018 [-0.078, +0.053] | +0.081 [+0.024, +0.144] | +0.097 [+0.018, +0.172] | +0.010 [-0.072, +0.082] | -0.017 [-0.062, +0.024] | +0.157 [+0.122, +0.192] |
| `deliv_value_share_20` | illiquid half | residual IC | +0.052 [+0.033, +0.072] | +0.055 [+0.037, +0.075] | +0.071 [+0.050, +0.091] | +0.045 [+0.027, +0.062] | +0.041 [+0.031, +0.052] | +0.084 [+0.070, +0.097] |
| `deliv_value_share_20` | illiquid half | IC | +0.050 [+0.021, +0.080] | +0.080 [+0.051, +0.108] | +0.124 [+0.083, +0.164] | +0.035 [-0.016, +0.081] | +0.036 [+0.013, +0.055] | +0.145 [+0.122, +0.166] |
| `deliv_value_share_20` | liquid half | residual IC | +0.010 [-0.027, +0.051] | +0.057 [+0.027, +0.089] | +0.052 [+0.024, +0.078] | +0.048 [+0.017, +0.078] | +0.019 [-0.004, +0.040] | +0.082 [+0.065, +0.099] |
| `deliv_value_share_20` | liquid half | IC | -0.001 [-0.049, +0.054] | +0.080 [+0.035, +0.124] | +0.112 [+0.051, +0.169] | +0.023 [-0.045, +0.085] | +0.003 [-0.032, +0.033] | +0.152 [+0.121, +0.182] |
| `deliv_value_share_20` | most liquid tercile | residual IC | +0.007 [-0.037, +0.058] | +0.060 [+0.024, +0.102] | +0.049 [+0.014, +0.082] | +0.047 [+0.008, +0.085] | +0.013 [-0.013, +0.037] | +0.090 [+0.068, +0.112] |
| `deliv_value_share_20` | most liquid tercile | IC | -0.011 [-0.069, +0.057] | +0.082 [+0.026, +0.140] | +0.110 [+0.035, +0.180] | +0.013 [-0.068, +0.084] | -0.010 [-0.052, +0.027] | +0.162 [+0.123, +0.199] |

### By calendar half-year (all names; 2026 H2 = July to 16 September)

| feature | group | dates | IC | NW t | 95% CI | residual IC | NW t | 95% CI |
|---|---|---:|---:|---:|---|---:|---:|---|
| `deliv_pct_sma_20` | 2023 H1 | 122 | +0.0406 | +1.44 | [-0.009, +0.091] | +0.0423 | +1.79 | [-0.002, +0.083] |
| `deliv_pct_sma_20` | 2023 H2 | 123 | -0.0281 | -1.73 | [-0.056, +0.005] | -0.0062 | -0.37 | [-0.036, +0.027] |
| `deliv_pct_sma_20` | 2024 H1 | 121 | +0.0322 | +1.78 | [-0.001, +0.065] | +0.0251 | +2.18 | [+0.004, +0.046] |
| `deliv_pct_sma_20` | 2024 H2 | 126 | +0.1000 | +3.94 | [+0.046, +0.141] | +0.0859 | +5.40 | [+0.054, +0.112] |
| `deliv_pct_sma_20` | 2025 H1 | 122 | +0.0519 | +1.46 | [-0.021, +0.118] | +0.0454 | +2.27 | [+0.002, +0.078] |
| `deliv_pct_sma_20` | 2025 H2 | 125 | +0.1393 | +5.42 | [+0.086, +0.189] | +0.0734 | +3.22 | [+0.027, +0.114] |
| `deliv_pct_sma_20` | 2026 H1 | 119 | +0.0327 | +0.90 | [-0.045, +0.097] | +0.0433 | +2.06 | [-0.000, +0.081] |
| `deliv_pct_sma_20` | 2026 H2 | 55 | +0.0413 | +3.17 | [+0.027, +0.058] | +0.0584 | +4.61 | [+0.035, +0.084] |
| `deliv_value_share_20` | 2023 H1 | 122 | +0.0487 | +1.54 | [-0.003, +0.103] | +0.0448 | +2.09 | [+0.005, +0.081] |
| `deliv_value_share_20` | 2023 H2 | 123 | -0.0111 | -0.70 | [-0.039, +0.019] | +0.0113 | +0.74 | [-0.015, +0.042] |
| `deliv_value_share_20` | 2024 H1 | 121 | +0.0454 | +2.52 | [+0.012, +0.081] | +0.0260 | +2.93 | [+0.011, +0.043] |
| `deliv_value_share_20` | 2024 H2 | 126 | +0.0987 | +3.54 | [+0.041, +0.145] | +0.0814 | +4.85 | [+0.048, +0.108] |
| `deliv_value_share_20` | 2025 H1 | 122 | +0.0604 | +1.74 | [-0.012, +0.125] | +0.0473 | +3.01 | [+0.014, +0.074] |
| `deliv_value_share_20` | 2025 H2 | 125 | +0.1469 | +6.87 | [+0.101, +0.188] | +0.0687 | +4.21 | [+0.036, +0.098] |
| `deliv_value_share_20` | 2026 H1 | 119 | +0.0247 | +0.68 | [-0.051, +0.091] | +0.0407 | +2.44 | [+0.006, +0.069] |
| `deliv_value_share_20` | 2026 H2 | 55 | +0.0434 | +2.31 | [+0.018, +0.071] | +0.0549 | +9.35 | [+0.043, +0.064] |

Cells with fewer than 100 dates (2026 H2: 55; pre-OOS: 59) rest on about three 20-session blocks per bootstrap replicate; their intervals are indicative only.

### Pre/post March 2026 (all names; OOS dates < 2026-03-01 vs ≥ 2026-03-01)

| feature | statistic | before (dates) | after (dates) | after − before | 95% CI of difference | NW t of difference |
|---|---|---:|---:|---:|---|---:|
| `deliv_pct_sma_20` | IC | +0.0594 (779) | +0.0121 (134) | -0.0473 | [-0.1134, +0.0088] | -1.42 |
| `deliv_pct_sma_20` | residual IC | +0.0458 (779) | +0.0424 (134) | -0.0034 | [-0.0467, +0.0330] | -0.16 |
| `deliv_value_share_20` | IC | +0.0678 (779) | +0.0058 (134) | -0.0620 | [-0.1271, -0.0059] | -1.89 |
| `deliv_value_share_20` | residual IC | +0.0475 (779) | +0.0408 (134) | -0.0067 | [-0.0406, +0.0210] | -0.40 |

### Pre-registered reading

Durable = residual IC > 0 with the 95% block-bootstrap CI excluding zero in at least 3 of the 4 calendar years AND, over the whole OOS window, in both liquidity halves.

| feature | years passing (residual IC CI > 0) | illiquid half | liquid half | verdict | stricter check: ≥ 3 of 4 years inside each half |
|---|---|---|---|---|---|
| `deliv_pct_sma_20` | 3 of 4: 2024 (+0.056), 2025 (+0.060), 2026 (+0.048) | +0.060 [+0.048, +0.073] | +0.036 [+0.015, +0.057] | **PASS** | passes (illiquid 4/4, liquid 3/4) |
| `deliv_value_share_20` | 4 of 4: 2023 (+0.028), 2024 (+0.054), 2025 (+0.058), 2026 (+0.045) | +0.057 [+0.046, +0.067] | +0.041 [+0.024, +0.060] | **PASS** | passes (illiquid 4/4, liquid 3/4) |

## 3. Label uniqueness, fold 2025-01 (`uniqueness.json`)

**Method.** Training window of fold 2025-01 exactly as the harness builds it: 2022-11-15..2024-11-29 (505 sessions), labeled clean rows, exit-date purge (4 rows purged): **641,030 rows, 1,957 tickers** (all tickers; it is cheap). Label span = sessions t+1..exit (the ticker's own row t+21; 99.98% of spans are exactly 21 sessions). Concurrency = number of the same ticker's training rows whose span covers the session; average uniqueness = mean of 1/concurrency over the row's span (López de Prado). Code checked against a brute-force loop on 25 random tickers (max error 3.4e-15).

| | training rows (the reading) | sensitivity: concurrency over every labeled row |
|---|---:|---:|
| mean | 0.0529 | 0.0509 |
| sd | 0.0227 | 0.0187 |
| coefficient of variation | 0.4282 | 0.3684 |
| 1st percentile | 0.0476 | 0.0476 |
| median | 0.0476 | 0.0476 |
| 95th percentile | 0.0835 | 0.0623 |
| 99th percentile | 0.1736 | 0.1282 |
| max | 1.0000 | 1.0000 |
| share exactly 1/21 | 82.0% | 89.8% |
| **share within ±10% of 1/21 = 0.0476** | **87.5%** | 92.7% |
| Kish weight efficiency (Σu)²/(N Σu²) | 0.845 | 0.880 |
| effective non-overlapping labels Σu | 33,932 | 32,602 |

| position in the window | share of rows | mean uniqueness | share within ±10% of 1/21 |
|---|---:|---:|---:|
| first 20 sessions | 3.2% | 0.0758 | 31.8% |
| interior | 92.5% | 0.0511 | 92.0% |
| last 20 sessions | 4.3% | 0.0745 | 32.8% |

**Where the deviations sit.** Rows in the first and last 20 sessions of the window carry on average 1.58 times the weight 1/21 of a fully overlapped row (their spans overlap fewer training labels). Inside the window, 7.4% of all rows deviate; an interior row can deviate only if the same ticker lacks a training row within 20 sessions of it (the name left the universe filter, its label was masked, it listed or delisted) or its span is longer than 21 sessions (0.1% of these rows). 87% of the deviating interior rows are in the illiquid half, against 47% of the rows within ±10% of 1/21.

**How much weights could move things, without a model fit** (training rows only, no test month): the label base rate moves from 0.5026 to 0.4981; the 50 features' univariate AUCs move by 0.0012 on average and at most 0.0052 (`atr_pct` 0.4816 → 0.4764), against a mean univariate edge |AUC − 0.5| of 0.0088; the ordering of features by edge is unchanged (Spearman 0.98). The largest moves are in the volatility and turnover features: the weights mostly re-weight the first and last weeks of the window and the illiquid names at the edge of the universe; they do not correct an overlap that varies across the bulk of the rows. Moves of 0.005 are the size of this phase's A/B pass mark (+0.003), so the effect on a fitted model cannot be assumed away.

**Pre-registered reading.** The plan fixed the consequence (near-constant ⇒ the item closes) but not the threshold; this stream set it and wrote it in the code and `log.txt` before the computation (near-constant iff share of training rows within +-10% of 1/21 >= 0.95). Share = 87.5% → **NOT near-constant: the item does not close on this evidence**.

## What this stream does not claim

- A low PBO does not show that the selected strategy has an edge. It shows that, inside this trial set, past rank predicted future rank more often than not. The set includes clearly weaker trials (momentum rules, the pilot's 10 features), which makes beating the median easier. The Deflated Sharpe (N = 177 for the five-year run, N = 239 in this phase after amendment A1) is still the hurdle, and no book clears it.

- The primary PBO uses 2023-01..2025-08 only (equal blocks of 2 months, remainder dropped from the end as pre-specified). Across the three partitions that move or keep the dropped months, PBO ranges from 0.036 to 0.264, always below 0.5, so the reading does not depend on that choice.

- The delivery result is internal evidence on one market and one data source. 2025 and 2026 overlap the months in which both features were found, and 2023 is the weakest year. Market direction is an ex-post label.

- The uniqueness numbers describe one training window (fold 2025-01) and count overlap in time within a ticker only; the dependence among some 1,300 names whose labels cover the same 21 sessions is not in them. AB7 and any weighted fit were not run here: they are model fits, which belong to the lead's single compute queue.

