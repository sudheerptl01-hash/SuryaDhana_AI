# Does FII index-futures positioning predict NIFTY?

Generated 2026-10-11 23:59 by `scripts/fii_positioning_study.py`; plan fixed beforehand in `PLAN.md`.
1,735 sessions 2019-10-01 → 2026-10-09; target = NIFTY 50 return from the close after the signal day. Overlapping windows → Newey-West t with lags = horizon.

## Verdicts (pre-registered)

| hypothesis | result | detail |
|---|---|---|
| H1 · 5-day FII futures flow: top minus bottom tercile → next 20 sessions | **FAIL** | spread -0.529% (t -1.34); halves -0.928% / -0.295% |
| H2 · FII long ratio in the bottom 10% of its year → next 20 sessions vs average | **FAIL** | excess 0.05% (t 0.07, 250 days); halves -0.397% / 0.382% |

## S1 · flow terciles

| horizon | period | days | top_n | bottom_n | top_mean | bottom_mean | spread | t_nw |
|---|---|---|---|---|---|---|---|---|
| 5 | full | 1604 | 574 | 586 | 0.295 | 0.247 | 0.048 | 0.26 |
| 5 | 2019–2022 | 681 | 242 | 234 | 0.722 | 0.296 | 0.426 | 1.34 |
| 5 | 2023–2026 | 923 | 332 | 352 | -0.016 | 0.214 | -0.23 | -1.0 |
| 20 | full | 1589 | 572 | 578 | 0.843 | 1.372 | -0.529 | -1.34 |
| 20 | 2019–2022 | 681 | 242 | 234 | 1.55 | 2.478 | -0.928 | -1.5 |
| 20 | 2023–2026 | 908 | 330 | 344 | 0.325 | 0.62 | -0.295 | -0.57 |

## S2 · positioning extreme (bottom decile of the trailing year)

| horizon | period | days | extreme_days | extreme_mean | all_mean | excess | t_nw |
|---|---|---|---|---|---|---|---|
| 5 | full | 1610 | 250 | 0.328 | 0.33 | -0.002 | -0.01 |
| 5 | 2019–2022 | 687 | 109 | 0.436 | 0.591 | -0.155 | -0.38 |
| 5 | 2023–2026 | 923 | 141 | 0.245 | 0.136 | 0.108 | 0.44 |
| 20 | full | 1595 | 250 | 1.322 | 1.271 | 0.05 | 0.07 |
| 20 | 2019–2022 | 687 | 109 | 1.761 | 2.158 | -0.397 | -0.28 |
| 20 | 2023–2026 | 908 | 141 | 0.982 | 0.601 | 0.382 | 0.54 |

FII long ratio today: 9.6% (trailing-year percentile 22).
