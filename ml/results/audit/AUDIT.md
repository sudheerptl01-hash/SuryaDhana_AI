# SuryaDhana pilot — red-team audit

**Date:** 2026-10-19 · **From:** red-team / testing lead · **Code:** `ml/audit.py` (seed 108, 2 threads) · **Numbers:** `ml/results/audit/audit.json`

**Bottom line.** The pipeline is clean and the champion's signal is not an artefact, but the headline numbers are inflated by choosing its features on the test months. Re-running the same selection without seeing each test month gives CV AUC **0.513** (claimed 0.531). On the untouched holdout the champion (0.518) does not beat a one-feature momentum rule (0.531).

| # | Test | Status | Key number |
|---|---|---|---|
| T0 | Champion reproduces | PASS | CV 0.531445, holdout 0.517996, exact |
| T1 | Label-permutation null (10 seeds) | PASS | null CV 0.5000 ± 0.0011 (max 0.5010), z = 28; holdout null 0.4998 ± 0.0032, z = 5.6 |
| T2 | Leak detector | INFO | features(t+1): CV 0.5357 (+0.004 only); features(t+21): 0.9446 |
| T3 | Embargo | FAIL (minor) | 3 of 1.62M train rows exit on/after test start (one illiquid ticker); 81 labels span >21 sessions |
| T4 | Labels recomputed from raw EOD | PASS | 471,867 labels, max diff 0 |
| T5 | Point-in-time | PASS | universe identical; 0/450 values of the champion's features (and rank inputs) change when recomputed from data ≤ t |
| T6 | Noise features | FAIL | 5/10 champion features inside the univariate AUC range of persistent pure noise (max 0.512); +30 iid noise *raised* CV +0.002 |
| T7 | Best-of-N | INFO | see below |
| T8 | Duplicates, coverage | PASS | 0 duplicates; clean preds = harness rows exactly |
| T9 | Holdout used once | FAIL | holdout labels chose feature_ab's top-8 new features; champion features chosen on CV test folds |
| T10 | Preds sanity | PASS | parquet AUC = JSON; fold base rates 0.501–0.502 |
| T11 | Honest nested selection | FAIL | CV 0.5132 (−0.018), holdout 0.5164, April 0.494 |
| T12 | 5 random 10-feature sets | INFO | CV 0.513 ± 0.006 (none ≥ 0.531); holdout 0.531, 4/5 beat the champion |
| T13 | Future-price label mask | INFO | drops 0.4% of test rows; CV 0.5314 → 0.5306 without it |
| T14 | Dependence-aware CI | INFO | 10-session-block CI [0.517, 0.545]; holdout champion − momentum −0.013 [−0.034, +0.004] |

## Chance and best-of-N

Shuffling labels within each date gives a null CV AUC of 0.5000 ± 0.0011 (max 0.5010). The champion sits 28 sd above it, so its score is not produced by the harness or by fitting noise. That null is only the iid floor, though: consecutive 20-day labels overlap 95%, so honest uncertainty is about 7× larger, σ(CV mean) ≈ 0.0075–0.008 (block bootstrap; month-to-month spread).

Expected best of N null trials: E[max] = μ0 + σ0·e_N, with e_N = ∫ x·N·φ(x)·Φ(x)^(N−1) dx, and P(any ≥ a) = 1 − Φ((a − μ0)/σ0)^N. The program has run 38 distinct full configurations on this task (151 counting hyper-parameter and univariate screens).

- **Permutation σ:** best-of-151 is 0.503, P ≈ 10⁻¹⁷³. Distinguishable.
- **Month-level σ:** best-of-151 is 0.520–0.522, P = 0.002–0.011. Still distinguishable, narrowly.
- **Cross-config spread (σ 0.011, upper bound):** P = 0.34. Not distinguishable.

Counting configurations misses the search over features done on the same folds; T11 measures that directly.

## Selection bias — the main finding

The ten features were ranked by univariate AUC on the four CV *test* months and by permutation importance on the June *test* month, and k = 10 was picked by CV AUC. The CV score is partly in-sample.

Re-running the identical procedure per fold on pre-fold data only gave the following. Inner validation used the last two training months, and k was fixed at 10, which favours the champion.

- Fold AUCs 0.494 / 0.505 / 0.522 / 0.531, holdout 0.516.
- CV mean 0.513: lower in every fold, removing 58% of the claimed edge over 0.5.
- That is level with lr_l2 (0.517) and random feature sets (0.513).
- The chosen sets are unstable: 2–9 of the champion's features per fold.

## Construction issues

1. **Feature selection used the CV test folds** (above). Material.
2. **Embargo vs label horizon.** The embargo counts market sessions; labels count a ticker's own rows. 3 train rows overlap the June test window, and 81 labels run to 37 sessions. Negligible; purge on the actual exit date at 5 years.
3. **Holdout in selection.** feature_ab's top-8 used IC over all dates, including the holdout. The memo's CV-over-holdout ruling was also made after the holdout was seen. Neither touched the champion's features.
4. **Pre-fix league rows.** Rows for the other models are pre-fix runs; 29 preds files still hold phantom-day rows.
5. **Verified clean:** labels, point-in-time universe, features, duplicates, the y_clean mask.

## Verdict and allowed wording

The headline does not survive as written.

- **"CV AUC 0.531"** is selection-inflated.
- **"Only model above chance at 95%"** is false: random forest and lr_l2_clean also clear it on CV, and every model clears it on the holdout.
- **"≥ 0.50 in all five windows"** fails under honest selection (April 0.494).

Wording I would allow:

> "In a six-month pilot, a LightGBM model on ten price and delivery features ranked NSE stocks by 20-day relative performance slightly better than chance: AUC 0.518 on an untouched six-week holdout, and about 0.513 across four monthly test folds when its features are chosen without seeing those months. The signal is not a data or code artefact: labels and features recompute exactly, no leakage was found, and shuffled labels score 0.500 ± 0.001. But it is small, rests on five monthly windows, and on the holdout it was no better than a one-feature momentum rule. It justifies the five-year walk-forward test; it is not evidence of a tradable edge."
