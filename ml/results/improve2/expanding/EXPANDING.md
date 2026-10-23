# Q9 (amendment A1): the control with an expanding training window

Plan: `ml/IMPROVEMENT_PLAN_2.md` section 4, A1 (motivated by the CPCV reading; a pass is evidence for a forward test, not a promotion). Every number is quoted from `expanding.json`.

| Model, 103 folds | CV AUC | 95% CI | Months >= 0.50 | Worst | Holdout | Rank IC (NW t) |
|---|---:|---|---:|---:|---:|---|
| rolling 504 sessions (control) | 0.5455 | [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.0878 (9.8) |
| expanding window | 0.5534 | [0.5435, 0.5624] | 86% | 0.414 | 0.5401 | +0.1031 (11.4) |

Primary mark: Δ CV-mean AUC +0.0079 [+0.0047, +0.0113], folds won 55/103, Δ rank IC +0.0153 (NW t 4.6): **PASS**.

| Book (net 20 bps vs EW) | Excess/yr | IR [95% CI] | Months ahead | Turnover | Name-level excess | DSR (N = 264) |
|---|---:|---|---:|---:|---:|---:|
| control, neutral top decile | +10.5% | +2.32 [+1.51, +3.10] | 83/105 | 78% | +3.9% | 0.069 |
| expanding, neutral top decile | +14.9% | +3.06 [+2.29, +3.86] | 85/105 | 75% | +8.2% | 0.767 |
| control, neutral liquid top decile | +1.2% | +0.21 [-0.52, +0.93] | 55/105 | 82% | -3.1% | 0.000 |
| expanding, neutral liquid top decile | +5.2% | +0.78 [+0.06, +1.54] | 67/105 | 81% | +0.6% | 0.000 |
| control, plain liquid top decile | -0.0% | +0.01 [-0.73, +0.71] | 52/105 | 76% | -2.8% | 0.000 |
| expanding, plain liquid top decile | +1.3% | +0.19 [-0.52, +0.83] | 56/105 | 73% | -1.3% | 0.000 |

Paired monthly excess, expanding minus control, vol+size|liq_top_decile: +4.06 pp/yr; iid-month CI [+1.71, +6.39] pp/yr; 3-month-block CI [+1.50, +6.47] pp/yr; expanding ahead in 60/105 months.
Paired monthly excess, expanding minus control, vol+size|top_decile: +4.42 pp/yr; iid-month CI [+2.77, +5.99] pp/yr; 3-month-block CI [+2.40, +6.78] pp/yr; expanding ahead in 61/105 months.

Book mark (Q3 rule on the liquid neutral book): IR >= 0.5 with CI above 0: True; paired iid CI above 0: True (3-month blocks: True). **PASS**.
