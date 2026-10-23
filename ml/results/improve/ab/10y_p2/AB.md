# A/B comparison (10y_p2)

Protocol: 103 purged monthly folds, rolling 504-session window, exit-date purge; paired 20-session block bootstrap (B = 1000) on the pooled 2126 CV dates; identical draws for every model.

Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): primary: paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= 0.003; secondary: per-date rank-IC delta Newey-West t (lag 20) >= 2.0; ab1_inversion: mean AUC over ['2023-07', '2024-01', '2025-04', '2025-05', '2026-03', '2026-04'] improves by >= 0.02

| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |
|---|---:|---|---|---:|---:|---:|---|---:|---:|
| control | 52 | 0.5455 ± 0.0491 | [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.0878 (9.8) | 0.514 | +0.92% |
| lr_l2 | 52 | 0.5423 ± 0.0681 | [0.5297, 0.5545] | 74% | 0.341 | 0.5003 | +0.0818 (6.6) | 0.479 | +0.32% |
| ae1_events | 62 | 0.5447 ± 0.0472 | [0.5357, 0.5537] | 84% | 0.401 | 0.5272 | +0.0874 (10.1) | 0.515 | +1.00% |
| q7_tuned | 52 | 0.5459 ± 0.0509 | [0.5364, 0.5555] | 84% | 0.399 | 0.5230 | +0.0891 (9.6) | 0.512 | +0.97% |
| q9_expanding | 52 | 0.5534 ± 0.0497 | [0.5435, 0.5624] | 86% | 0.414 | 0.5401 | +0.1031 (11.4) | 0.518 | +1.05% |
| control_s109 | 52 | 0.5457 ± 0.0490 | [0.5361, 0.5548] | 83% | 0.402 | 0.5190 | +0.0882 (9.8) | 0.514 | +0.97% |
| control_s110 | 52 | 0.5454 ± 0.0495 | [0.5359, 0.5546] | 84% | 0.398 | 0.5170 | +0.0880 (9.7) | 0.513 | +0.90% |
| control_s111 | 52 | 0.5461 ± 0.0497 | [0.5365, 0.5554] | 83% | 0.403 | 0.5194 | +0.0890 (9.8) | 0.514 | +0.95% |
| q9_expanding_s109 | 52 | 0.5536 ± 0.0499 | [0.5437, 0.5625] | 86% | 0.407 | 0.5404 | +0.1033 (11.4) | 0.519 | +1.05% |
| q9_expanding_s110 | 52 | 0.5535 ± 0.0498 | [0.5437, 0.5624] | 87% | 0.406 | 0.5402 | +0.1033 (11.3) | 0.517 | +1.04% |

| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---:|---|---|
| lr_l2 - control | -0.0032 | [-0.0104, +0.0033] | 48/103 | -0.0060 (-0.8) | -0.034 | -0.0190 | FAIL | FAIL |
| ae1_events - control | -0.0008 | [-0.0035, +0.0017] | 51/103 | -0.0004 (-0.2) | +0.001 | +0.0079 | FAIL | FAIL |
| q7_tuned - control | +0.0004 | [-0.0006, +0.0014] | 34/103 | +0.0013 (1.3) | -0.002 | +0.0037 | FAIL | FAIL |
| q9_expanding - control | +0.0079 | [+0.0047, +0.0113] | 55/103 | +0.0153 (4.6) | +0.004 | +0.0209 | PASS | PASS |
| control_s109 - control | +0.0001 | [-0.0005, +0.0008] | 49/103 | +0.0004 (0.7) | +0.000 | -0.0003 | FAIL | FAIL |
| control_s110 - control | -0.0001 | [-0.0007, +0.0006] | 48/103 | +0.0001 (0.2) | -0.001 | -0.0023 | FAIL | FAIL |
| control_s111 - control | +0.0006 | [-0.0002, +0.0013] | 58/103 | +0.0012 (1.8) | -0.000 | +0.0001 | FAIL | FAIL |
| q9_expanding_s109 - control | +0.0081 | [+0.0046, +0.0116] | 68/103 | +0.0155 (4.7) | +0.005 | +0.0212 | PASS | PASS |
| q9_expanding_s110 - control | +0.0079 | [+0.0045, +0.0115] | 67/103 | +0.0154 (4.5) | +0.003 | +0.0210 | PASS | PASS |
