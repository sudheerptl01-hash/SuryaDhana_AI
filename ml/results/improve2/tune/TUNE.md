# Q7: nested hyper-parameter tuning of the control LightGBM

Plan: `ml/IMPROVEMENT_PLAN_2.md` Q7 (1 configuration, 2 books = 3 trials of N = 261). Code: `ml/improve/tune.py` (selection), `ml/improve/ab.py` config `q7_tuned` (outer run). Every number below is quoted from `ml/results/improve2/tune/tune.json` and `selected_params.json`.

## Design (fixed before any result)

- Grid: the incumbent `nl63_mdl200_ff0.8` plus num_leaves {31, 127} x min_data_in_leaf {200, 2000} x feature_fraction {0.5, 0.8}; 9 settings, all with 300 trees, learning rate 0.05, bagging 0.8 every iteration, seed 108, the rest as `ml/scale5y.make_model("all51")`. The fitted trees were checked to honour the three overrides (smoke).
- Rule: mean AUC over the last 3 21-session blocks before the anchor (each block: rolling 504-session training window ending 22 sessions before its first session, exit-date purge against that session); best mean wins (ties: grid order, incumbent first) but the incumbent is kept unless the best beats it by >= 0.002; a year without 3 blocks whose training windows hold >= 120 sessions keeps the incumbent.
- Anchor for year Y: `train_end` of fold Y-01 in `ml/data_10y/splits.json`. The anchor is embargo-adjusted, so an inner row's label exits before the first test session of year Y unless its ticker has missing sessions (sentence corrected after the selection: such rows exist; the audit below counts them and shows that no choice depends on them).
- The outer run (`python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --configs q7_tuned`) trains each fold exactly like the control with its calendar year's setting; the holdout (test window from 2026-08-03) takes the 2026 setting.

Deviations and interpretations (written before the selection ran):

- 2018 has no inner blocks: the first row of the 10-year dataset is dated 2017-10-03 (the store's first year, from 2016-10, is feature warm-up), so only 41 labelled sessions precede the 2018 anchor (2017-11-29). The rule keeps the incumbent; the reason is recorded in `selected_params.json`.
- 2019 and 2020 run with training windows shorter than 504 sessions (the data start truncates the rolling window); every block holds >= 120 training sessions, so both years are eligible (`plans` in `smoke/smoke.json`).
- Ties in the best mean inner AUC are broken by grid order with the incumbent first (no tie is expected).

## Smoke (one year, one block; `smoke/smoke.json`)

- Year 2026, block blk00 (test 2025-10-31..2025-12-01, inner train_end 2025-09-29), all 9 settings on 673,135 training rows, 2 workers, wall 225 s. Fit seconds: nl127_mdl200_ff0.5 42, nl127_mdl200_ff0.8 57, nl127_mdl2000_ff0.5 74, nl127_mdl2000_ff0.8 85, nl63_mdl200_ff0.8 37, nl31_mdl200_ff0.5 33, nl31_mdl200_ff0.8 38, nl31_mdl2000_ff0.5 30, nl31_mdl2000_ff0.8 32.
- Tree check (max leaves per tree <= num_leaves; max features used per tree <= ceil(feature_fraction x 52); smallest true leaf count >= 0.8 x min_data_in_leaf (LightGBM checks min_data_in_leaf on counts estimated from the hessians, so true counts of a logloss model sit slightly below it: the control itself shows 179 < 200)): nl127_mdl200_ff0.5 ok (leaves <= 127, smallest leaf 170, features/tree <= 23), nl127_mdl200_ff0.8 ok (leaves <= 127, smallest leaf 175, features/tree <= 34), nl127_mdl2000_ff0.5 ok (leaves <= 127, smallest leaf 1907, features/tree <= 24), nl127_mdl2000_ff0.8 ok (leaves <= 127, smallest leaf 1933, features/tree <= 34), nl63_mdl200_ff0.8 ok (leaves <= 63, smallest leaf 179, features/tree <= 30), nl31_mdl200_ff0.5 ok (leaves <= 31, smallest leaf 175, features/tree <= 18), nl31_mdl200_ff0.8 ok (leaves <= 31, smallest leaf 171, features/tree <= 23), nl31_mdl2000_ff0.5 ok (leaves <= 31, smallest leaf 1923, features/tree <= 19), nl31_mdl2000_ff0.8 ok (leaves <= 31, smallest leaf 1948, features/tree <= 23).
- Selection runtime estimate: 216 inner fits, about 54 min at 2 workers (sum over every eligible (year, block) of the smoke block's 9 fit seconds x (window rows / smoke window rows), divided by the worker count); the smoke's 9 fits are reused from the cache.
- Note: ok flags re-evaluated after the run with tree_check_rule (the first rule required true leaf counts >= min_data_in_leaf, which LightGBM does not guarantee); the recorded counts are unchanged.

## Harness checks (`harness_check.json`)

- `ml/improve/ab.py` with `ae1_events`, `q7_tuned` and the `tuned` kind added: compare on tag v1 re-run byte-identical to `ml/results/improve/ab/v1/compare.json`: True (sha256 aa3253eb8fc6...).
- `ml/improve/ab_books.py` with the phase-2 hooks off: the ten-year books re-run byte-identical to `ml/results/improve/ab/10y/books.json`: True.
- `q7_tuned` with every year set to the incumbent reproduces the control's fold 2026-07: AUC 0.547356 vs 0.547356, scores bit-identical on 32,841 rows: True.

## Inner selection

| Year | Anchor | Blocks (test windows) | Train sessions | Best setting | Best mean AUC | Incumbent mean AUC | Best - incumbent | Chosen |
|---|---|---|---|---|---:|---:|---:|---|
| 2018 | 2017-11-29 | none | | | | | | nl63_mdl200_ff0.8 (incumbent: only 41 labelled sessions up to the anchor 2017-11-29 (data start 2017-10-03): 3 blocks of 21 sessions behind a 22-session embargo with >= 120 training sessions need >= 204; 0 block(s) formable) |
| 2019 | 2018-11-29 | 2018-08-27..2018-09-26, 2018-09-27..2018-10-29, 2018-10-30..2018-11-29 | 203/224/245 | nl31_mdl2000_ff0.5 | 0.5819 | 0.5748 | +0.0071 | nl31_mdl2000_ff0.5 (switched) |
| 2020 | 2019-11-29 | 2019-08-27..2019-09-26, 2019-09-27..2019-10-30, 2019-10-31..2019-11-29 | 448/469/490 | nl31_mdl200_ff0.8 | 0.5760 | 0.5742 | +0.0018 | nl63_mdl200_ff0.8 |
| 2021 | 2020-12-01 | 2020-09-02..2020-09-30, 2020-10-01..2020-10-30, 2020-11-02..2020-12-01 | 505/505/505 | nl127_mdl2000_ff0.5 | 0.4879 | 0.4836 | +0.0043 | nl127_mdl2000_ff0.5 (switched) |
| 2022 | 2021-12-02 | 2021-09-01..2021-09-30, 2021-10-01..2021-11-01, 2021-11-02..2021-12-02 | 505/505/505 | nl31_mdl200_ff0.5 | 0.5351 | 0.5328 | +0.0024 | nl31_mdl200_ff0.5 (switched) |
| 2023 | 2022-12-01 | 2022-09-01..2022-09-29, 2022-09-30..2022-11-01, 2022-11-02..2022-12-01 | 505/505/505 | nl31_mdl200_ff0.8 | 0.5425 | 0.5381 | +0.0045 | nl31_mdl200_ff0.8 (switched) |
| 2024 | 2023-11-29 | 2023-08-29..2023-09-27, 2023-09-28..2023-10-30, 2023-10-31..2023-11-29 | 505/505/505 | nl31_mdl2000_ff0.5 | 0.5205 | 0.5183 | +0.0022 | nl31_mdl2000_ff0.5 (switched) |
| 2025 | 2024-11-29 | 2024-08-30..2024-09-27, 2024-09-30..2024-10-29, 2024-10-30..2024-11-29 | 505/505/505 | nl31_mdl200_ff0.5 | 0.5478 | 0.5460 | +0.0019 | nl63_mdl200_ff0.8 |
| 2026 | 2025-12-01 | 2025-09-01..2025-09-29, 2025-09-30..2025-10-30, 2025-10-31..2025-12-01 | 505/505/505 | nl31_mdl200_ff0.5 | 0.5938 | 0.5847 | +0.0091 | nl31_mdl200_ff0.5 (switched) |

Mean inner AUC by setting and year (3 blocks each):

| Setting | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| nl63_mdl200_ff0.8 (incumbent) | 0.5748 | 0.5742 | 0.4836 | 0.5328 | 0.5381 | 0.5183 | 0.5460 | 0.5847 |
| nl31_mdl200_ff0.5 | 0.5784 | 0.5746 | 0.4874 | 0.5351 | 0.5422 | 0.5176 | 0.5478 | 0.5938 |
| nl31_mdl200_ff0.8 | 0.5779 | 0.5760 | 0.4829 | 0.5333 | 0.5425 | 0.5186 | 0.5465 | 0.5906 |
| nl31_mdl2000_ff0.5 | 0.5819 | 0.5753 | 0.4840 | 0.5314 | 0.5425 | 0.5205 | 0.5471 | 0.5914 |
| nl31_mdl2000_ff0.8 | 0.5818 | 0.5751 | 0.4818 | 0.5332 | 0.5417 | 0.5163 | 0.5456 | 0.5907 |
| nl127_mdl200_ff0.5 | 0.5722 | 0.5714 | 0.4874 | 0.5293 | 0.5367 | 0.5185 | 0.5454 | 0.5773 |
| nl127_mdl200_ff0.8 | 0.5711 | 0.5732 | 0.4830 | 0.5289 | 0.5353 | 0.5180 | 0.5443 | 0.5777 |
| nl127_mdl2000_ff0.5 | 0.5808 | 0.5755 | 0.4879 | 0.5257 | 0.5371 | 0.5155 | 0.5403 | 0.5707 |
| nl127_mdl2000_ff0.8 | 0.5817 | 0.5757 | 0.4839 | 0.5239 | 0.5386 | 0.5166 | 0.5389 | 0.5696 |

Years that switched away from the incumbent: ['2019', '2021', '2022', '2023', '2024', '2026'].

### Audit: inner scoring rows whose label exits inside the outer test window

Added after the selection ran (post-hoc audit; no choice was revised); `tune.json` `audit_inner_exit`. Rule: an inner block that ends at the anchor can hold rows whose label exit date (the ticker's row t+21) is on or after the first test session of the outer fold Y-01 (tickers with missing sessions); the outer fold purges such rows from its training, the inner scoring (every clean labelled row of the block, as the design defines it) keeps them.  Removing k_pos of P positives and k_neg of N negatives changes a block's AUC by at most k_pos/P + k_neg/N; a setting's 3-block mean by at most B = the mean of that over the 3 blocks; a difference of two settings' means by at most 2B.  A kept incumbent cannot flip if every (setting - incumbent) + 2B < margin; a switch cannot flip if (best - incumbent) - 2B >= margin and the best leads every other setting by more than 2B.

| Year | Outer test start | Rows (block: k_pos + k_neg) | 2B | Best - incumbent | Chosen | Bound rules out a flip | Exact check without the rows |
|---|---|---|---:|---:|---|---|---|
| 2019 | 2019-01-01 | none | 0.00000 | +0.00711 | nl31_mdl2000_ff0.5 | yes |  |
| 2020 | 2020-01-01 | none | 0.00000 | +0.00182 | nl63_mdl200_ff0.8 | yes |  |
| 2021 | 2021-01-01 | none | 0.00000 | +0.00430 | nl127_mdl2000_ff0.5 | yes |  |
| 2022 | 2022-01-03 | none | 0.00000 | +0.00236 | nl31_mdl200_ff0.5 | yes |  |
| 2023 | 2023-01-02 | blk01: 1 + 0 | 0.00006 | +0.00446 | nl31_mdl200_ff0.8 | no | refit blk01 (max diff vs cached AUC 0.0e+00): best nl31_mdl200_ff0.8, best - incumbent +0.00446, chosen nl31_mdl200_ff0.8: same choice |
| 2024 | 2024-01-01 | blk01: 1 + 3 | 0.00021 | +0.00217 | nl31_mdl2000_ff0.5 | no | refit blk01 (max diff vs cached AUC 0.0e+00): best nl31_mdl2000_ff0.5, best - incumbent +0.00217, chosen nl31_mdl2000_ff0.5: same choice |
| 2025 | 2025-01-01 | blk01: 0 + 1 | 0.00005 | +0.00187 | nl63_mdl200_ff0.8 | yes |  |
| 2026 | 2026-01-01 | blk00: 1 + 2 | 0.00014 | +0.00910 | nl31_mdl200_ff0.5 | yes |  |

9 rows in all (where the bound cannot rule out a flip, every setting is refitted on each affected block (same seed, rows and threads; the refit must reproduce the cached AUC) and the block is re-scored without the rows; the selection rule is then re-applied). Every year's choice is the same without them: yes.

## Outer walk-forward (103 folds + holdout)

Source: `ml/results/improve/ab/10y_p2/compare.json`. Pass mark: primary: paired fold-level CV-mean AUC delta vs the control >= +0.003 with the 20-session block-bootstrap 95% CI excluding zero (ml/IMPROVEMENT_PLAN_2.md section 1).

| Model | CV AUC ± sd | 95% CI | Folds >= 0.50 | Worst fold | Holdout AUC | Rank IC (NW t) |
|---|---|---|---:|---:|---:|---|
| control | 0.5455 ± 0.0491 | [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.0878 (9.8) |
| q7_tuned | 0.5459 ± 0.0509 | [0.5364, 0.5555] | 84% | 0.399 | 0.5230 | +0.0891 (9.6) |

q7_tuned - control: delta CV mean +0.0004, 95% CI [-0.0006, +0.0014], folds won 34/103, rank-IC delta +0.0013 (NW t 1.3), holdout delta +0.0037. **Primary mark: FAIL.**

Books (P2 construction, 20 bps, DSR at N = 261; trial books: q7_tuned|vol+size|top_decile, q7_tuned|vol+size|liq_top_decile):

| Book | Excess vs EW | IR [95% CI] | Months beating EW | Turnover | Name-level excess | DSR |
|---|---:|---|---:|---:|---:|---:|
| control|none|top_decile | +7.5% | +1.37 [+0.51, +2.21] | 69/105 | 72% | +2.8% | 0.000 |
| control|none|liq_top_decile | -0.0% | +0.01 [-0.73, +0.71] | 52/105 | 76% | -2.8% | 0.000 |
| control|vol+size|top_decile | +10.5% | +2.32 [+1.51, +3.10] | 83/105 | 78% | +3.9% | 0.070 |
| control|vol+size|liq_top_decile | +1.2% | +0.21 [-0.52, +0.93] | 55/105 | 82% | -3.1% | 0.000 |
| q7_tuned|none|top_decile | +8.1% | +1.45 [+0.57, +2.28] | 70/105 | 71% | +3.4% | 0.000 |
| q7_tuned|none|liq_top_decile | +0.4% | +0.08 [-0.61, +0.75] | 52/105 | 75% | -2.4% | 0.000 |
| q7_tuned|vol+size|top_decile | +11.8% | +2.61 [+1.82, +3.38] | 82/105 | 78% | +5.3% | 0.271 |
| q7_tuned|vol+size|liq_top_decile | +2.8% | +0.45 [-0.24, +1.14] | 57/105 | 82% | -1.5% | 0.000 |

