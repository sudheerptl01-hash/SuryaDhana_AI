# Q2: combinatorial purged cross-validation of the frozen construction

Plan: `ml/IMPROVEMENT_PLAN_2.md` Q2 (1 trial of N = 261). Code: `ml/improve/cpcv.py`; books through `ml/improve/ab_books.py --folds-only`. Every number below is quoted from `ml/results/improve2/cpcv/cpcv.json`.

## Design (fixed before any result)

- Groups: the 103 fold months of `ml/data_10y/splits.json`, in order, cut into 8 contiguous groups of 13, 13, 13, 13, 13, 13, 13 and 12 months (g0 = 2018-01..2019-01, ..., g7 = 2025-08..2026-07).
- Splits: every pair of groups as the test set, C(8, 2) = 28 splits, in lexicographic order (s00 = g0+g1, s01 = g0+g2, ..., s27 = g6+g7).
- Test rows: the clean labelled rows of the two groups' fold test windows.
- Training rows: every clean labelled row of `ml/data_10y` outside the two test groups and outside the holdout window, after (a) the purge of rows whose label span [date, exit_date] intersects either test group's span [first test date, last test date] and (b) a 22-session embargo after each test group's last test date (sessions of the dataset's calendar). The 2017-10..2017-12 warm-up rows are trainable.
- Model: the control (the champion LightGBM of `ml/scale5y.make_model("all51")`, 52 features, raw preprocessing fitted on the training rows, seed 108), as `ml/improve/ab.py` fits it.
- Paths: each group is tested in 7 of the 28 splits; path j takes, for every group, that group's j-th test occurrence in split order (the standard CPCV assignment: 2/8 x 28 = 7 paths, each covering all 103 months once). Path 1 therefore scores g0 with s00 (g0+g1), g1 with s00, g2 with s01 (g0+g2), and so on; the full table is `design.path_assignment` in `cpcv.json`.
- Readings, per path: fold-month AUCs, per-date rank IC (Newey-West t, lag 20), and books with the P2 construction (`ml/improve/ab_books`): the vol+size-neutral full-universe top decile and the vol+size-neutral liquid-tercile top decile, net 20 bps per side vs the equal-weight universe, IR with its month-block 95% CI, DSR at N = 261 with V[SR] = 0.00387. **Robust across paths** if the full-universe book has positive net excess in >= 6 of 7 paths; the liquid book is read the same way.
- CPCV trains on months after the test window by design: it measures path dependence, not forward performance.

## Interpretations and deviations (written before the full run)

- **Holdout never observed.** Besides the rows dated in the holdout window (2026-08-03..2026-09-16), the training rows whose label exit date is on or after 2026-08-03 are dropped (30,004 clean labelled rows: 30,003 dated in July 2026 and one dated 2023-10-25 whose ticker's next 21 rows run past the holdout start), so no training label contains a holdout-window price. This is the walk-forward's own rule for its holdout fold and the reading of "the holdout is never used"; it removes rows only from splits whose test groups exclude g7 (with g7 tested, the same rows are test rows or fall to the g7 purge).
- **Books on 103 months.** A CPCV path has no holdout predictions, so its books run on the 103 fold months only (`ab_books --folds-only`). The book engine requires a non-empty second segment; the hook therefore labels the last fold month (2026-07) as the engine's 'holdout' segment as a placeholder, and every reading uses the 'combined' segment (all 103 months). The walk-forward control's books in `ml/results/improve/ab/10y/` cover 105 months (with the holdout), so the like-for-like reference here is `wf_control`: the walk-forward control's own predictions on the same 103 months, scored through the same hook.
- **Training-set size.** The brief estimated about 1.9M rows per split; the measured count is 1,351,005 to 1,756,525 (mean 1,528,278; `smoke/smoke.json` `n_train_range`, `n_train_mean`): 2,187,230 clean labelled rows less the 47,117 holdout rows, the two test groups (about 0.5M), the purge and embargo, and the 30,004 rows whose label exits in the holdout window.

## Smoke (timing only; `smoke/smoke.json`)

- Split s00 (g0+g1, the largest training set, 1,756,525 rows) fitted on a 20% sample (351,062 rows, seed 108) in one forked worker: preprocess 0.9 s, fit 19.4 s, predict 4.4 s on 323,822 test rows; worker peak RSS 2.25 GB (shared frame pages included).
- Full-run estimate for the 28 fits at 2 workers: 13 min (a line through the smoke point and the walk-forward control's measured fold times) to 22 min (5 x the smoke fit, scaled by each split's rows); on a busy shared box allow 20-35 min. The paths, books (8 scorers x 4 books) and report stages add about 10 min.

## Design check (row masks of all 28 splits, no fitting; `smoke/invariants.json`)

All passed: True. Asserted on every split: train and test disjoint; every row clean and labelled; no training row dated inside a test group's [first, last] test date; no training row whose [date, exit_date] intersects a test group's span (purge); no training row dated in the 22 sessions after a test group (embargo; fewer only at the end of the calendar); no training row dated in the holdout window or with its label exit on or after the holdout start; test rows per month equal the walk-forward control's CV rows for that month; paths: every (split, group) test occurrence used by exactly one path; each path holds every group once.
Training rows per split 1,351,005..1,756,525; warm-up rows (before 2018-01) used in training 32,424..50,230 per split; training rows dated after the earlier test group 0..1,724,101 per split (CPCV trains on later months by design).

## Results

Not run yet: the lead queues `fit`, `paths`, `books` and `report`.

