# Q7: nested hyper-parameter tuning of the control LightGBM

Plan: `ml/IMPROVEMENT_PLAN_2.md` Q7 (1 configuration, 2 books = 3 trials of N = 261). Code: `ml/improve/tune.py` (selection), `ml/improve/ab.py` config `q7_tuned` (outer run). Every number below is quoted from `ml/results/improve2/tune/tune.json` and `selected_params.json`.

## Design (fixed before any result)

- Grid: the incumbent `nl63_mdl200_ff0.8` plus num_leaves {31, 127} x min_data_in_leaf {200, 2000} x feature_fraction {0.5, 0.8}; 9 settings, all with 300 trees, learning rate 0.05, bagging 0.8 every iteration, seed 108, the rest as `ml/scale5y.make_model("all51")`. The fitted trees were checked to honour the three overrides (smoke).
- Rule: mean AUC over the last 3 21-session blocks before the anchor (each block: rolling 504-session training window ending 22 sessions before its first session, exit-date purge against that session); best mean wins (ties: grid order, incumbent first) but the incumbent is kept unless the best beats it by >= 0.002; a year without 3 blocks whose training windows hold >= 120 sessions keeps the incumbent.
- Anchor for year Y: `train_end` of fold Y-01 in `ml/data_10y/splits.json`. The anchor is embargo-adjusted, so every label of an inner row has exited before the first test session of year Y: no outer test data is used.
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

## Outer walk-forward

Not run yet: the lead runs it after the selection finishes.

