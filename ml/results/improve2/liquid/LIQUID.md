# Q3. A model for the liquid universe

**Verdict: FAIL** · Plan: `ml/IMPROVEMENT_PLAN_2.md` §2 Q3 (2 configurations, 4 books = 6 trials) · Code: `ml/improve/liquid.py` · JSON: `ml/results/improve2/liquid/build.json`, `liquid.json`, `selftest.json`, `smoke.json`

**Pass mark (fixed):** for L1 or L2, the neutral liquid book's IR ≥ 0.5 with its month-block 95% CI excluding zero over the 105 signal months **and** its paired monthly excess over the control's neutral liquid book has a bootstrap 95% CI excluding zero.

## Definitions and deviations (fixed before any result of this stream existed)

1. **Datasets.** L1 = rows of `ml/data_10y/model_dataset.parquet` with `cs_rank_turnover >= 0.67` on that date (the
   full-universe rank, as stored); L2 = rows with `cs_rank_turnover >= 0.33`. Same columns and dtypes, the 52-feature
   manifest, `splits.json` copied byte for byte (103 folds, embargo 22, holdout 2026-08-03..2026-09-16), `exit_date`
   kept. Features, including the `cs_rank_*` columns and the per-date z-score `amihud_20` computed on the full
   universe, are unchanged, as the lead fixed.
2. **Labels.** Recomputed inside each restricted universe with `ml/data.py`'s own rule (lines 198-202):
   per-date median of `y_raw_20d` over every universe row with a non-missing `y_raw_20d` (clean or not, pandas skips
   NaN), `y_excess_20d = y_raw_20d - median`, `y_rank_20d` = per-date percentile rank of `y_excess_20d`,
   `label_beat_mkt_20d = 1(y_excess_20d > 0)` where `y_excess_20d` is not NaN. The same function applied to the full
   universe must reproduce the stored labels exactly (identity test), and five dates drawn with seed 108 are
   recomputed by a separate hand path (sort, middle value, scipy ranks).
3. **Model and books.** The control configuration through `ml/improve/ab.py` (rolling 504 sessions, exit-date purge,
   holdout once) on each dataset, then `ml/improve/ab_books.py` on the dataset's own base. In L1 every base row is
   liquid, so the liquid book is `control|vol+size|top_decile` (neutral) and `control|none|top_decile` (plain) and
   its benchmark (`ew_universe` of L1) is the equal-weight liquid tercile. In L2 the liquid book is
   `control|vol+size|liq_top_decile` / `control|none|liq_top_decile` with benchmark `ew_liquid`. The volatility+size
   neutralisation is the per-date regression on the dataset's own base rows: inside the liquid tercile for L1, inside
   the top two terciles for L2 (the control's neutral liquid book neutralises over the full universe, then picks the
   liquid decile). This is the construction the plan describes ("trained and scored on liquid rows only").
4. **Same benchmark.** `liquid.py compare` rebuilds the books' base panel of each dataset with `ml/books/data.py
   load_base` and checks that the benchmark rows (date, ticker, `y_raw_20d`) equal the control's `ew_liquid` rows
   (labeled clean liquid rows of the fold windows and the holdout). Identical rows mean an identical benchmark: each
   row's tranche path comes from the same price parquet and is pinned to `1 + y_raw_20d` at exit. If they differ,
   the paired monthly series is recomputed against the control's benchmark (the per-signal-date tranche benchmark
   difference added back by month), the IR is flagged as not on the identical benchmark, and the verdict reads
   UNDETERMINED instead of PASS/FAIL.
5. **IR interval (deviation).** The plan says "month-block 95% CI over the 105 signal months". The phase's IR and
   interval are the engine's (`ml/strategy_backtest.py series_stats` on the daily active series, exposure-weighted,
   month-block bootstrap B = 1000, seed 108, as written by `ab_books.py`). Its blocks are the calendar months of the
   daily return days, which run 20 sessions past the last signal date, so the block count is one more than the 105
   signal months (the exact count is recorded in `liquid.json` under `design.ir_interval_month_blocks`). The engine's
   reading is used unchanged because it is how the control's liquid IR (0.21) and every other book IR in both phases
   were measured. A daily series cannot be blocked by signal month without reassigning days that carry tranches of
   two signal months.
6. **Paired monthly excess.** For each of the 105 signal months: `monthly_net_20bps` of the set's neutral liquid book
   minus the control's (both are net 20 bps 20-session tranche returns minus the same EW liquid benchmark, averaged
   by signal month), so the benchmark cancels. Mean with a bootstrap 95% CI: months resampled with replacement,
   B = 1000, seed 108. This is the binding reading. "Excluding zero" is read on the positive side: the lower bound
   must be above zero and the mean positive (a CI wholly below zero would mean the set is worse than the control).
   A 3-month moving-block bootstrap (non-circular, ceil(105/3) blocks, fresh generator seeded 108) is reported beside
   it, because tranches of adjacent signal months overlap; if the two readings disagree, the verdict line says so.
   Annualised figures multiply the per-tranche mean by 252/20.
7. **Two configurations.** The mark is "L1 or L2". Both are counted in the trial ledger (6 trials), and each book's
   DSR is at N = 261 with V[SR] = 0.00387. The control's books (written at N = 241) are re-deflated at N = 261 from
   their stored moments.
8. **Descriptive only.** The models' CV AUC and rank IC are measured on each set's restricted label and are not
   comparable with the control's 0.5455. Name-level costs fill missing spreads and volatilities with the
   cross-sectional median of the dataset's own ticker set, so name-level figures can differ slightly from the
   control's for identical baskets. Neither enters the pass mark.
9. **Code-path test.** `liquid.py selftest` (and the first step of `compare`) runs the pass-mark code on the control's
   liquid books against themselves: the difference must be identically zero, the CI [0, 0] and part 2 FAIL.

## Datasets (`build.json`)

Identity test: the label function applied to the full universe reproduces the stored labels: **True** (max |Δ| `y_excess_20d` 0.0e+00, `y_rank_20d` 0.0e+00, NaN patterns equal).

| Set | Filter | Rows (share) | Tickers | Sessions | Names/date mean [min, max] | Label mean (labeled / clean) | Per-date label mean, p05..p95 [min, max] | Dates within 0.45-0.55 | Labels differing from full universe | Benchmark rows = control `ew_liquid` | Hand check |
|---|---|---:|---:|---:|---|---|---|---:|---:|---|---|
| L1 | `cs_rank_turnover >= 0.67` | 735,860 (33.1%) | 2,144 | 2,241 | 328 [151, 507] | 0.4992 / 0.5000 | 0.497..0.500 [0.492, 0.500] | 100.0% (2,220 dates) | 5.4% | True (705,312 vs 705,312 rows) | True |
| L2 | `cs_rank_turnover >= 0.33` | 1,492,914 (67.1%) | 2,408 | 2,241 | 666 [305, 1029] | 0.4996 / 0.5002 | 0.499..0.500 [0.496, 0.500] | 100.0% (2,220 dates) | 2.1% | True (705,312 vs 705,312 rows) | True |

Rows per year (all rows / labeled clean rows / names per date):

| Year | L1 | L2 |
|---|---:|---:|
| 2017 | 16,679 / 16,547 / 269 | 33,822 / 33,647 / 546 |
| 2018 | 56,938 / 56,519 / 231 | 115,432 / 114,910 / 469 |
| 2019 | 42,437 / 41,913 / 173 | 86,064 / 85,354 / 351 |
| 2020 | 52,525 / 51,754 / 208 | 106,510 / 105,581 / 423 |
| 2021 | 78,824 / 78,703 / 318 | 159,908 / 159,700 / 645 |
| 2022 | 83,075 / 82,860 / 335 | 168,552 / 168,123 / 680 |
| 2023 | 91,713 / 91,437 / 373 | 186,085 / 185,436 / 756 |
| 2024 | 113,098 / 112,589 / 454 | 229,501 / 228,656 / 922 |
| 2025 | 108,769 / 108,438 / 437 | 220,729 / 220,076 / 886 |
| 2026 | 91,802 / 81,099 / 468 | 186,311 / 164,499 / 951 |

Hand cross-check (five dates drawn with seed 108; median by sorting, ranks by scipy):

| Set | Date | Rows (with y_raw) | Median y_raw by hand | Median implied by stored labels | Above / at / below | Label mean | max abs Δ excess, rank | Label mismatches |
|---|---|---:|---:|---:|---|---:|---|---:|
| L1 | 2017-10-17 | 252 (252) | -0.012251 | -0.012251 | 126 / 0 / 126 | 0.5000 | 0e+00, 0e+00 | 0 |
| L1 | 2019-03-01 | 173 (173) | +0.085532 | +0.085532 | 86 / 1 / 86 | 0.4971 | 0e+00, 0e+00 | 0 |
| L1 | 2023-06-02 | 354 (352) | +0.040760 | +0.040760 | 176 / 0 / 176 | 0.5000 | 0e+00, 0e+00 | 0 |
| L1 | 2025-05-30 | 433 (432) | +0.030091 | +0.030091 | 216 / 0 / 216 | 0.5000 | 0e+00, 0e+00 | 0 |
| L1 | 2026-04-24 | 473 (473) | +0.006522 | +0.006522 | 236 / 1 / 236 | 0.4989 | 0e+00, 0e+00 | 0 |
| L2 | 2017-10-17 | 512 (512) | -0.009028 | -0.009028 | 256 / 0 / 256 | 0.5000 | 0e+00, 0e+00 | 0 |
| L2 | 2019-03-01 | 351 (350) | +0.080330 | +0.080330 | 175 / 0 / 175 | 0.5000 | 0e+00, 0e+00 | 0 |
| L2 | 2023-06-02 | 717 (714) | +0.044980 | +0.044980 | 357 / 0 / 357 | 0.5000 | 0e+00, 0e+00 | 0 |
| L2 | 2025-05-30 | 880 (878) | +0.023599 | +0.023599 | 439 / 0 / 439 | 0.5000 | 0e+00, 0e+00 | 0 |
| L2 | 2026-04-24 | 961 (959) | +0.010623 | +0.010623 | 479 / 1 / 479 | 0.4995 | 0e+00, 0e+00 | 0 |

Per-date median of `y_raw_20d`, restricted minus full universe: L1 mean +0.31% per 20 sessions (sd 1.44%); L2 mean +0.13% per 20 sessions (sd 0.61%).

## Pass mark (`liquid.json`)

Cost 20 bps per side. IR interval month blocks: 106 calendar months (2018-01..2026-10, 2177 return days) for 105 signal months. Paired CI: B = 1000, seed 108. DSR at N = 261, V[SR] = 0.00387.

| Book | Benchmark | Excess vs EW liquid /yr | IR [95% CI] | Months beating EW | Turnover / rebalance | Break-even bps/side | Capacity ₹ cr | Name-level excess /yr | DSR (N = 261) |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| control (full-universe model), neutral (`control|vol+size|liq_top_decile`) | EW liquid tercile (`ew_liquid`) | +1.2% | +0.21 [-0.52, +0.93] | 55/105 | 82% | 26 | 603 | -3.1% | 0.000 |
| control (full-universe model), plain (`control|none|liq_top_decile`) | EW liquid tercile (`ew_liquid`) | -0.0% | +0.01 [-0.73, +0.71] | 52/105 | 76% | 20 | 785 | -2.8% | 0.000 |
| L1, neutral (`control|vol+size|top_decile`) | EW liquid tercile (L1's `ew_universe`) | +1.2% | +0.27 [-0.49, +1.02] | 50/105 | 84% | 26 | 671 | -2.8% | 0.000 |
| L1, plain (`control|none|top_decile`) | EW liquid tercile (L1's `ew_universe`) | +2.1% | +0.39 [-0.36, +1.10] | 53/105 | 79% | 31 | 806 | -0.7% | 0.000 |
| L2, neutral (`control|vol+size|liq_top_decile`) | EW liquid tercile (`ew_liquid`) | +2.3% | +0.40 [-0.30, +1.14] | 60/105 | 83% | 31 | 617 | -1.9% | 0.000 |
| L2, plain (`control|none|liq_top_decile`) | EW liquid tercile (`ew_liquid`) | +2.1% | +0.34 [-0.39, +1.02] | 57/105 | 77% | 31 | 809 | -0.7% | 0.000 |

| Set | Paired vs control neutral liquid: mean /yr | iid 95% CI (/tranche) | 3-month block 95% CI | Months set > control | Part 1 (IR ≥ 0.5, CI > 0) | Part 2 (paired CI > 0) | Readings agree | Benchmark identical | **Result** |
|---|---:|---|---|---:|---|---|---|---|---|
| L1 | +0.04% | [-0.0021, +0.0021] | [-0.0023, +0.0018] | 49/105 | FAIL | FAIL | True | True | **FAIL** |
| L2 | +1.08% | [-0.0004, +0.0021] | [-0.0002, +0.0020] | 57/105 | FAIL | FAIL | True | True | **FAIL** |

Plain liquid books, paired against the control's plain liquid book (descriptive, not a pass mark): L1 +2.39%/yr, iid CI [+0.0001, +0.0036] per tranche; L2 +2.21%/yr, iid CI [+0.0006, +0.0029] per tranche.

Neutral liquid books by signal year: excess vs EW liquid per year (mean of the signal months x 252/20, 20 bps), and the paired difference against the control (descriptive):

| Year | Control | L1 | L1 − control | L2 | L2 − control |
|---|---:|---:|---:|---:|---:|
| 2018 | -6.7% | -0.8% | +5.9% | -4.6% | +2.1% |
| 2019 | -5.3% | -10.7% | -5.4% | -5.6% | -0.4% |
| 2020 | -1.4% | -1.2% | +0.2% | +1.0% | +2.4% |
| 2021 | +4.3% | +5.6% | +1.3% | +4.5% | +0.3% |
| 2022 | +4.1% | -4.6% | -8.6% | +3.4% | -0.7% |
| 2023 | -3.6% | +2.5% | +6.1% | -0.4% | +3.3% |
| 2024 | +3.1% | +5.4% | +2.3% | +5.3% | +2.2% |
| 2025 | +4.1% | +6.7% | +2.6% | +6.4% | +2.3% |
| 2026 | +18.5% | +13.0% | -5.4% | +15.8% | -2.7% |

Models (descriptive, each on its own restricted label): L1 CV AUC 0.5305 [+0.5218, +0.5390], holdout 0.4948, rank IC +0.0603 (NW t 6.9); L2 CV AUC 0.5403 [+0.5305, +0.5499], holdout 0.5093, rank IC +0.0767 (NW t 8.3).

**Verdict: FAIL.**

## Code-path test (`selftest.json`)

Control's liquid books against themselves: difference identically zero **True**, benchmark identical True, iid CI [+0.0000, +0.0000], block CI [+0.0000, +0.0000], part 2 False (expected False).

## Smoke run (`smoke.json`; code path and runtime only, outputs deleted)

- `python3 -m ml.improve.ab run --data ml/data_10y_liq --tag 10y_liq --configs control --folds 2025-06 2025-07 --skip-holdout --n-jobs 1`: ran (33 s). Seconds per fold [15.1, 13.9], training rows [217634, 215915].
- `python3 -m ml.improve.ab run --data ml/data_10y_liq2 --tag 10y_liq2 --configs control --folds 2025-06 2025-07 --skip-holdout --n-jobs 1`: ran (46 s). Seconds per fold [20.6, 19.6], training rows [441853, 438336].
- `python3 -m ml.improve.ab_books --tag <tag> --data <scratch dir> --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --n-trials 261 --folds-only`: ran (10y_liq 13 s, 10y_liq2 14 s).
  - L1: top_decile and liq_top_decile baskets coincide (every L1 row is liquid), benchmark ew_universe = EW liquid tercile.
  - L2: liq_top_decile with benchmark ew_liquid.
  - base 19,415 (L1) / 39,423 (L2) rows, 44 signal dates, exit-mark/label match 1.00000.
  - Smoke-only deviation: ml/books/data.py load_scores asserts a finite score on every base row, and a two-fold run scores 2 of the 103 fold months, so ab_books on the tag with --data ml/data_10y_liq* stops (685,897 rows without a score). The smoke therefore pointed --data at a scratch folder holding a symbolic link to the set's model_dataset.parquet and a splits.json cut to the two smoke folds, with ab_books' own --folds-only hook (no holdout rows). The full runs use the real dataset folder and splits; nothing in ab_books or ml/books was changed.
- `python3 -m ml.improve.ab compare --data ml/data_10y_liq* --tag 10y_liq*`: ran (6 s).
  - compare.json carries every key liquid.py reads (cv_auc_mean, cv_mean_ci95, holdout_auc, rank_ic_cv_mean, rank_ic_nw_t, rank_ic_months_positive, pct_folds_ge_050).
- `python3 -m ml.improve.liquid compare --allow-partial --out <scratch>`: ran (53 s).
  - self-test on the control's own liquid books: difference identically zero, iid and block CIs [0, 0], part 2 False.
  - benchmark rows of L1 (ew_universe) and of L2 (ew_liquid) equal the control's ew_liquid rows: 705,312 = 705,312, no row only on one side, y_raw_20d identical, 2,158 = 2,158 signal dates.
  - coverage check reports the partial smoke months (2 of 105) and, without --allow-partial, the run would stop.
  - LIQUID.md pass-mark section rendered from the smoke JSON in a scratch copy (tables, by-year table, model line, verdict line, verdict note when the iid and block readings disagree).

Deleted: `ml/results/improve/ab/10y_liq/`, `ml/results/improve/ab/10y_liq2/`. Full-run estimate: about 33 minutes (ab run L1 (104 fits, n-jobs 2) 11; ab run L2 (104 fits, n-jobs 2) 15; ab_books L1 1; ab_books L2 2; ab compare x2 2; liquid compare 2); on a busy shared box add 20-30%. Basis: control 10y full run: 1,005 s wall for 104 fits at --n-jobs 2 (mean 19.3 s per fit per process) against 28 s on the 2025-06/07 folds, so a mean fit is about 0.69 of a 2025 fit; L1 and L2 2025 fits took 15 s and 20 s.

## Reproduce

```
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.liquid build
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab run --data ml/data_10y_liq --tag 10y_liq --configs control --n-jobs 2
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab run --data ml/data_10y_liq2 --tag 10y_liq2 --configs control --n-jobs 2
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab_books --tag 10y_liq --data ml/data_10y_liq --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --n-trials 261
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab_books --tag 10y_liq2 --data ml/data_10y_liq2 --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --n-trials 261
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab compare --data ml/data_10y_liq --tag 10y_liq
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.ab compare --data ml/data_10y_liq2 --tag 10y_liq2
cd /home/user/SuryaDhana_AI && python3 -m ml.improve.liquid compare
```

## Lead's note on books not in the plan

`ml/results/improve/ab/10y_liq2/BOOKS_AB.md` and `books.json` also hold L2's top-decile books over the whole top-two-tercile universe (`control|none|top_decile` and `control|vol+size|top_decile`, measured against that universe's equal weight). The label 'control' there means the L2 model, not the program's control. They were computed by the books harness, never registered, and are now counted as two trials (ml/IMPROVEMENT_PLAN_2.md section 4, ledger corrections; N = 270). They are context, not a capacity result: the Q3 mark is read on the liquid-tercile book only.
