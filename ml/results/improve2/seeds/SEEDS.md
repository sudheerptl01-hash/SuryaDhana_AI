# Q10 (amendment A2): seed calibration of the book marks

Plan: `ml/IMPROVEMENT_PLAN_2.md` section 4, A2. Every number is quoted from `seeds.json`. Net 20 bps per side, excess over the equal-weight benchmark of the book (universe or liquid tercile).

## Seed spread

| Book | Configuration | Seed | Excess/yr | IR [95% CI] | Months ahead |
|---|---|---:|---:|---|---:|
| vol+size|liq_top_decile | control | 108 | +1.2% | +0.21 [-0.52, +0.93] | 55/105 |
| vol+size|liq_top_decile | control | 109 | +1.8% | +0.30 [-0.41, +1.05] | 59/105 |
| vol+size|liq_top_decile | control | 110 | +2.3% | +0.36 [-0.38, +1.08] | 57/105 |
| vol+size|liq_top_decile | control | 111 | +1.8% | +0.31 [-0.40, +0.99] | 53/105 |
| vol+size|liq_top_decile | expanding | 108 | +5.2% | +0.78 [+0.06, +1.54] | 67/105 |
| vol+size|liq_top_decile | expanding | 109 | +4.9% | +0.74 [-0.05, +1.51] | 68/105 |
| vol+size|liq_top_decile | expanding | 110 | +5.6% | +0.86 [+0.07, +1.67] | 70/105 |
| vol+size|top_decile | control | 108 | +10.5% | +2.32 [+1.51, +3.10] | 83/105 |
| vol+size|top_decile | control | 109 | +10.4% | +2.29 [+1.48, +3.10] | 79/105 |
| vol+size|top_decile | control | 110 | +9.9% | +2.19 [+1.39, +2.99] | 78/105 |
| vol+size|top_decile | control | 111 | +10.5% | +2.32 [+1.53, +3.09] | 78/105 |
| vol+size|top_decile | expanding | 108 | +14.9% | +3.06 [+2.29, +3.86] | 85/105 |
| vol+size|top_decile | expanding | 109 | +14.9% | +3.08 [+2.29, +3.89] | 84/105 |
| vol+size|top_decile | expanding | 110 | +14.5% | +2.99 [+2.19, +3.77] | 86/105 |
| none|liq_top_decile | control | 108 | -0.0% | +0.01 [-0.73, +0.71] | 52/105 |
| none|liq_top_decile | control | 109 | +0.8% | +0.14 [-0.57, +0.80] | 53/105 |
| none|liq_top_decile | control | 110 | +1.1% | +0.17 [-0.59, +0.87] | 57/105 |
| none|liq_top_decile | control | 111 | +0.8% | +0.13 [-0.57, +0.79] | 51/105 |
| none|liq_top_decile | expanding | 108 | +1.3% | +0.19 [-0.52, +0.83] | 56/105 |
| none|liq_top_decile | expanding | 109 | +1.5% | +0.22 [-0.48, +0.87] | 60/105 |
| none|liq_top_decile | expanding | 110 | +2.0% | +0.28 [-0.42, +0.94] | 58/105 |
| none|top_decile | control | 108 | +7.5% | +1.37 [+0.51, +2.21] | 69/105 |
| none|top_decile | control | 109 | +8.0% | +1.46 [+0.58, +2.30] | 68/105 |
| none|top_decile | control | 110 | +7.3% | +1.35 [+0.45, +2.19] | 68/105 |
| none|top_decile | control | 111 | +7.8% | +1.43 [+0.56, +2.26] | 70/105 |
| none|top_decile | expanding | 108 | +9.5% | +1.67 [+0.90, +2.39] | 72/105 |
| none|top_decile | expanding | 109 | +9.3% | +1.65 [+0.83, +2.36] | 73/105 |
| none|top_decile | expanding | 110 | +9.3% | +1.67 [+0.88, +2.39] | 71/105 |

## Seed-averaged comparison (expanding minus control)

| Book | Control mean (range) | Expanding mean (range) | Paired, pp/yr | iid CI | 3-month-block CI | Min expanding seed > max control seed | Reading |
|---|---|---|---:|---|---|---|---|
| vol+size|liq_top_decile | +1.8% (+1.2..+2.3) | +5.2% (+4.9..+5.6) | +3.54 | [+1.30, +5.67] | [+1.08, +5.86] | True | **REAL** |
| vol+size|top_decile | +10.3% (+9.9..+10.5) | +14.8% (+14.5..+14.9) | +4.44 | [+2.90, +5.97] | [+2.59, +6.56] | True | **REAL** |
| none|liq_top_decile | +0.7% (-0.0..+1.1) | +1.6% (+1.3..+2.0) | +1.08 | [-1.31, +3.48] | [-1.48, +3.38] | True | **not shown** |
| none|top_decile | +7.6% (+7.3..+8.0) | +9.4% (+9.3..+9.5) | +1.82 | [-0.23, +3.93] | [-0.63, +4.11] | True | **not shown** |

AUC: control seeds 0.5455, 0.5457, 0.5454, 0.5461 (sd 0.0003); expanding seeds 0.5534, 0.5536, 0.5535 (sd 0.0001). Seed-averaged delta +0.0078, 3-fold-block CI [+0.0044, +0.0116], expanding ahead in 62/103 folds.

Registered reading (neutral liquid book decides): **Q9 book gain REAL**.
