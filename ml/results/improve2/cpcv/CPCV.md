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

## Verdict

- Full-universe neutral top decile: positive net excess in 7/7 paths -> **ROBUST**.
- Liquid neutral top decile: positive net excess in 7/7 paths -> **ROBUST**.
- CPCV trains on months after the test window by design: it measures path dependence, not forward performance.

## Model readings per path

| Path | CV AUC ± sd | Worst month | Months >= 0.50 | Rank IC (NW t) | IC months positive | Rank corr with walk-forward |
|---|---|---:|---:|---|---:|---:|
| path1 | 0.5559 ± 0.0486 | 0.416 | 88% | +0.1088 (12.4) | 91/103 | 0.527 |
| path2 | 0.5594 ± 0.0548 | 0.413 | 89% | +0.1147 (11.7) | 91/103 | 0.557 |
| path3 | 0.5604 ± 0.0538 | 0.420 | 86% | +0.1160 (12.0) | 90/103 | 0.553 |
| path4 | 0.5590 ± 0.0536 | 0.414 | 88% | +0.1130 (11.8) | 89/103 | 0.544 |
| path5 | 0.5595 ± 0.0553 | 0.412 | 88% | +0.1152 (11.7) | 90/103 | 0.550 |
| path6 | 0.5611 ± 0.0533 | 0.419 | 90% | +0.1184 (12.2) | 92/103 | 0.543 |
| path7 | 0.5591 ± 0.0514 | 0.415 | 89% | +0.1144 (12.3) | 91/103 | 0.545 |
| wf_control | 0.5455 ± 0.0491 | 0.399 | 84% | +0.0878 (9.8) | 87/103 |  |

Path mean AUC across the 7 paths: mean 0.5592, range [0.5559, 0.5611], sd 0.0017.

## Full-universe neutral top decile (`vol+size|top_decile`), net 20 bps vs EW

| Path | Excess vs EW | IR [95% CI] | Months beating EW | Turnover | Name-level excess | DSR (N = 261) |
|---|---:|---|---:|---:|---:|---:|
| path1 | +15.3% | +2.93 [+2.23, +3.68] | 87/103 | 74% | +8.7% | 0.634 |
| path2 | +15.9% | +3.22 [+2.51, +3.96] | 87/103 | 74% | +9.3% | 0.883 |
| path3 | +15.5% | +3.08 [+2.40, +3.84] | 83/103 | 74% | +8.9% | 0.791 |
| path4 | +14.3% | +2.91 [+2.10, +3.70] | 81/103 | 74% | +7.7% | 0.612 |
| path5 | +15.9% | +3.22 [+2.48, +4.00] | 86/103 | 73% | +9.4% | 0.885 |
| path6 | +17.1% | +3.55 [+2.84, +4.30] | 87/103 | 74% | +10.4% | 0.985 |
| path7 | +16.7% | +3.34 [+2.62, +4.10] | 90/103 | 73% | +10.1% | 0.942 |
| wf_control (same 103 months) | +10.3% | +2.26 [+1.46, +3.09] | 81/103 | 79% | +3.7% | 0.053 |

Positive in 7/7 paths; IR CI excludes zero in 7/7; excess across paths mean +15.8%, range [+14.3%, +17.1%]. **ROBUST.**

## Liquid-tercile neutral top decile (`vol+size|liq_top_decile`), net 20 bps vs EW

| Path | Excess vs EW | IR [95% CI] | Months beating EW | Turnover | Name-level excess | DSR (N = 261) |
|---|---:|---|---:|---:|---:|---:|
| path1 | +5.4% | +0.75 [+0.01, +1.47] | 63/103 | 79% | +1.0% | 0.000 |
| path2 | +6.3% | +0.91 [+0.11, +1.67] | 66/103 | 80% | +1.8% | 0.000 |
| path3 | +4.9% | +0.70 [-0.01, +1.45] | 62/103 | 80% | +0.3% | 0.000 |
| path4 | +4.8% | +0.70 [-0.06, +1.49] | 64/103 | 80% | +0.2% | 0.000 |
| path5 | +5.3% | +0.78 [+0.01, +1.56] | 58/103 | 80% | +0.7% | 0.000 |
| path6 | +8.7% | +1.25 [+0.50, +2.00] | 73/103 | 80% | +4.1% | 0.000 |
| path7 | +5.8% | +0.86 [+0.12, +1.65] | 66/103 | 80% | +1.3% | 0.000 |
| wf_control (same 103 months) | +0.8% | +0.14 [-0.57, +0.87] | 53/103 | 82% | -3.5% | 0.000 |

Positive in 7/7 paths; IR CI excludes zero in 5/7; excess across paths mean +5.9%, range [+4.8%, +8.7%]. **ROBUST.**

## Splits

| Split | Test groups | Train rows | Train sessions | Test rows | AUC (pooled) | AUC by group | Fit seconds |
|---|---|---:|---:|---:|---:|---|---:|
| s00_g0g1 | [0, 1] | 1,756,525 | 1590 | 323,822 | 0.5896 | g0 0.5950, g1 0.5827 | 72.6 |
| s01_g0g2 | [0, 2] | 1,681,793 | 1542 | 368,476 | 0.5722 | g0 0.6067, g2 0.5396 | 68.2 |
| s02_g0g3 | [0, 3] | 1,584,804 | 1545 | 455,242 | 0.5682 | g0 0.6063, g3 0.5412 | 63.4 |
| s03_g0g4 | [0, 4] | 1,583,467 | 1543 | 450,228 | 0.5739 | g0 0.6059, g4 0.5522 | 63.7 |
| s04_g0g5 | [0, 5] | 1,502,301 | 1544 | 525,279 | 0.5665 | g0 0.6080, g5 0.5432 | 63.4 |
| s05_g0g6 | [0, 6] | 1,473,791 | 1540 | 550,520 | 0.5697 | g0 0.6062, g6 0.5508 | 63.5 |
| s06_g0g7 | [0, 7] | 1,565,119 | 1609 | 517,946 | 0.5721 | g0 0.5997, g7 0.5570 | 64.2 |
| s07_g1g2 | [1, 2] | 1,755,528 | 1589 | 325,088 | 0.5666 | g1 0.5948, g2 0.5441 | 69.4 |
| s08_g1g3 | [1, 3] | 1,634,321 | 1549 | 411,854 | 0.5600 | g1 0.5934, g3 0.5411 | 67.1 |
| s09_g1g4 | [1, 4] | 1,632,983 | 1547 | 406,840 | 0.5662 | g1 0.5930, g4 0.5513 | 67.8 |
| s10_g1g5 | [1, 5] | 1,551,817 | 1548 | 481,891 | 0.5600 | g1 0.5963, g5 0.5436 | 65.3 |
| s11_g1g6 | [1, 6] | 1,523,307 | 1544 | 507,132 | 0.5647 | g1 0.5942, g6 0.5524 | 65.3 |
| s12_g1g7 | [1, 7] | 1,614,635 | 1613 | 474,558 | 0.5651 | g1 0.5850, g7 0.5563 | 71.7 |
| s13_g2g3 | [2, 3] | 1,618,790 | 1587 | 456,508 | 0.5440 | g2 0.5448, g3 0.5434 | 70.1 |
| s14_g2g4 | [2, 4] | 1,580,617 | 1542 | 451,494 | 0.5487 | g2 0.5440, g4 0.5517 | 68.8 |
| s15_g2g5 | [2, 5] | 1,499,451 | 1543 | 526,545 | 0.5451 | g2 0.5444, g5 0.5455 | 66.0 |
| s16_g2g6 | [2, 6] | 1,470,941 | 1539 | 551,786 | 0.5503 | g2 0.5465, g6 0.5525 | 65.9 |
| s17_g2g7 | [2, 7] | 1,562,269 | 1608 | 519,212 | 0.5544 | g2 0.5439, g7 0.5607 | 70.1 |
| s18_g3g4 | [3, 4] | 1,528,893 | 1588 | 538,260 | 0.5455 | g3 0.5387, g4 0.5520 | 66.1 |
| s19_g3g5 | [3, 5] | 1,402,462 | 1546 | 613,311 | 0.5395 | g3 0.5372, g5 0.5414 | 60.2 |
| s20_g3g6 | [3, 6] | 1,373,952 | 1542 | 638,552 | 0.5459 | g3 0.5391, g6 0.5508 | 58.4 |
| s21_g3g7 | [3, 7] | 1,465,280 | 1611 | 605,978 | 0.5525 | g3 0.5409, g7 0.5618 | 65.6 |
| s22_g4g5 | [4, 5] | 1,447,538 | 1587 | 608,297 | 0.5461 | g4 0.5501, g5 0.5439 | 63.1 |
| s23_g4g6 | [4, 6] | 1,372,615 | 1540 | 633,538 | 0.5506 | g4 0.5524, g6 0.5492 | 59.8 |
| s24_g4g7 | [4, 7] | 1,463,943 | 1609 | 600,964 | 0.5592 | g4 0.5533, g7 0.5638 | 60.5 |
| s25_g5g6 | [5, 6] | 1,351,005 | 1584 | 708,589 | 0.5505 | g5 0.5458, g6 0.5549 | 57.7 |
| s26_g5g7 | [5, 7] | 1,382,779 | 1610 | 676,015 | 0.5539 | g5 0.5436, g7 0.5645 | 57.5 |
| s27_g6g7 | [6, 7] | 1,410,858 | 1649 | 701,256 | 0.5590 | g6 0.5531, g7 0.5655 | 57.7 |

