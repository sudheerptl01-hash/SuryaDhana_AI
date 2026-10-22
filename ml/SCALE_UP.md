# Scale-up plan: 6-month pilot → 5-year run

Executes the decision in `MODEL_SELECTION.md`: **LightGBM on the selected
feature subset** as champion, **L2 logistic regression** as the interpretable
benchmark. RL and RNNs are out, with evidence. The pilot's purpose was
algorithm selection; the 5-year run's purpose is to confirm the edge is real,
regime-diverse, and economically meaningful net of costs.

## Phase 1 — Data (gating)

1. **Ingest 5 years** (≈2021-10 → 2026-10) with `nse_historical_ingest.py`
   — now carrying the holiday calendar, the duplicate-day ("holiday echo")
   guard, and the label NaN fix shipped during the pilot. ~1,240 trading
   days; resume-safe; ~1–2 h wall at polite throttle.
2. **Corporate actions become mandatory.** Over 5 years splits/bonuses are
   frequent; feed `--ca corp_actions.csv` (`ticker,ex_date,ratio`) so price
   features/labels are computed on adjusted prices. Keep the `y_clean_20d`
   mask as defense-in-depth and re-audit the `flag_split_20d` rate after
   adjustment (pilot: 0.51%).
3. **Data forensics across the full history**: re-run the duplicate-day
   fingerprint scan and the calendar audit per year; cross-validate monthly
   breadth and spot tickers against the production store (the pilot's
   cross-pipeline validation pattern — it caught the holiday echo).
4. **Optional feature parity with production v2**: excess carry needs an F&O
   bhavcopy ingest; `flag_bad_results_60d` needs an announcements feed. Both
   are new sources — scope separately; the pilot's edge did not depend on them.

## Phase 2 — Evaluation protocol at scale

- Same harness (`ml/data.py` + `ml/evaluation.py`), more folds: **monthly
  purged walk-forward over the last ~42 months** (22-session embargo
  unchanged), first year reserved as feature warm-up, and a final 6-month
  holdout touched exactly once.
- **Re-run feature selection first**: `ret_252d`/`mom_12_1`/`dist_200dma`
  were 21–58% NaN in the pilot; with full history the top-10 subset may
  change. Then the champion duel: LGBM-selected vs LGBM-full-features vs
  lr_l2 (plus RF as a cheap challenger) — this resolves the pilot's
  CV↔holdout contradiction with ~40 windows instead of 5.
- **Significance**: the same date-block bootstrap, now over thousands of
  test dates; the pilot's champion-vs-linear gap becomes decidable.
- **Pre-registered promotion criteria** (decide before looking):
  1. champion beats lr_l2 on CV mean with a bootstrap CI excluding zero;
  2. monthly fold-AUC floor ≥ 0.50 in ≥ 90% of months;
  3. top-decile book beats the **equal-weight universe** (not the universe
     median, which cross-sectional skew makes a soft bar: the EW universe
     beat it by +1.8% per 20 days in the pilot) in ≥ 75% of months, net of
     ~20 bps per side;
  4. selected-feature overlap ≥ 7/10 across yearly re-selections
     (stability of the signal, not just the score);
  5. Deflated Sharpe Ratio ≥ 0.95 for the paper portfolio, with the trial
     count N stated before the run (the pilot's best book had DSR 0.08 over
     132 days; the observed edge needs ~2.8 years of track record to reach
     PSR 95%).

## Phase 3 — Productionization (after promotion)

- Nightly scoring after EOD ingest; monthly re-train on an expanding window;
  champion–challenger (LGBM-selected vs LGBM-full) rather than a single model.
- Drift monitoring: lr_l2 per-σ coefficients tracked over time + feature
  PSI; alert on sign flips of the top-5 coefficients.
- Portfolio layer is **explicit construction, not RL** (pilot verdict):
  top-decile ranker + turnover-penalized selection/hysteresis, position
  caps, and the cost model — this captures the only thing RL was adding,
  deterministically.

## Feature-study changes

A follow-up EDA and an engineered-feature A/B (`ml/report/feature_study.html`,
outputs in `ml/results/feature_study/`) change this plan in four places.

- **No feature rebuild before the run.** None of the five engineered variants
  beat the champion (best 0.5268 against 0.5314, pass mark 0.5364). Phase 2
  starts from the pilot's 10 features.
- **Re-selection on the full history is required.** The March-2026 regime
  break flipped the volatility family's sign and shrank the delivery and
  52-week-high signals, and the pilot's selection saw only the post-break
  phase. cs_rank_mom_20 (t = 0.42 over 16 months) is the first candidate to
  drop.
- **Three queued A/Bs against the re-selected baseline**, each with its pass
  mark fixed before the run: market-state inputs (median momentum, market
  drawdown, days since a sell-off), the mom_12_1 × cs_rank_vol_20 product, and
  listing age built from real listing dates.
- **A delivery-IC alert in production.** Delivery is the most consistent
  signal (positive in 15 of 16 months), but its monthly IC fell from +0.107
  to +0.020 after March 2026.

The linear benchmark (and any neural model) should get log1p on the
volatility family, ranks on raw returns and a top-decile volatility flag. The
champion's trees need none of these.

## Gate status (2026-10-19, 43 folds landed)

Scored by `ml/scale5y_report.py`; full tables in `ml/results/scale5y/SCALE5Y.md`.

| Gate | Pre-registered rule | nested_lgbm | all51 | nested_ensemble_rank |
|---|---|---|---|---|
| 1 | LightGBM beats lr_l2 on CV mean, bootstrap CI excluding zero | −0.0056 [−0.0150, +0.0024] **FAIL** | −0.0050 [−0.0155, +0.0039] **FAIL** | −0.0085 [−0.0222, +0.0027] **FAIL** |
| 2 | Fold AUC ≥ 0.50 in ≥ 90% of months | 86% (37/43) **FAIL** | 81% (35/43) **FAIL** | 91% (39/43) **PASS** |
| 3 | Top decile beats the EW universe in ≥ 75% of months, net of 20 bps | 20/45 = 44% **FAIL** | 20/45 = 44% **FAIL** | 33/45 = 73% **FAIL** |
| 4 | Selected-feature overlap ≥ 7/10 across yearly re-selections | top-10 overlaps 4, 4, 5 **FAIL** | 4, 4, 5 **FAIL** (selects nothing; scored on the same yearly re-selection) | 4, 4, 5 **FAIL** |
| 5 | DSR ≥ 0.95 on the liquid top decile, N = 177 fixed before the run | 0.000 **FAIL** | 0.000 **FAIL** | 0.040 **FAIL** |

No model passes more than one gate, so the pre-registered decision is **do
not promote to capital**. Phase 3 becomes paper trading of the ensemble's
liquid top decile as one frozen strategy (N = 1), with the monitoring
specified in `ml/PROGRAM_REPORT.md` §10. Post-hoc observations (a
stability-aware comparison favours LightGBM over the linear model; the
ensemble's +7.0%/yr over the EW universe has an interval clear of zero) are
reported as such and do not change the verdict.

## Gate status, improvement phase (2026-10-22, corrected data, N = 241)

Scored by `python3 -m ml.improve.gates --tag v2 --n-trials 241` from `ml/results/improve/ab/v2/` (full table in `GATES.md` there). The trial ledger grew from 177 to 241 under `ml/IMPROVEMENT_PLAN.md`; gate 4 does not apply to configurations that select nothing.

| Gate | Rule | LightGBM, 52 features (control) | Rank ensemble on 52 features (no re-selection) |
|---|---|---|---|
| 1 | beats lr_l2 on CV mean, bootstrap CI excluding zero | −0.0037 [−0.0125, +0.0043] **FAIL** | −0.0054 [−0.0171, +0.0051] **FAIL** |
| 2 | fold AUC ≥ 0.50 in ≥ 90% of months | 88% (worst 0.466) **FAIL** | 88% (worst 0.452) **FAIL** |
| 3 | top decile beats the EW universe in ≥ 75% of months, net 20 bps | plain 19/45 **FAIL**; volatility+size-neutral 34/45 = 76% **PASS** | plain 34/45 = 76% **PASS**; neutral 38/45 = 84% **PASS** |
| 4 | selected-feature overlap ≥ 7/10 | not applicable (no selection) | not applicable |
| 5 | DSR ≥ 0.95 on the liquid top decile, N = 241 | plain 0.000; neutral 0.000 **FAIL** | plain 0.000; neutral 0.011 **FAIL** |

Decision unchanged: **do not promote to capital.** The paper book of Phase 3 becomes the deliberate volatility+size-neutral construction (`ml/PROGRAM_REPORT.md` §13.7), with the all-feature rank ensemble as champion-challenger.

## Compute

The pilot's full 13-model bake-off ran ~2 h on 4 CPU cores. The 5-year
champion protocol is ~10× data × ~10× folds for two cheap model families —
hours, not days, on a modern workstation; no GPU required (DL excluded).
