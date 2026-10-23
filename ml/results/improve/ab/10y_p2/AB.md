# A/B comparison (10y_p2)

Protocol: 103 purged monthly folds, rolling 504-session window, exit-date purge; paired 20-session block bootstrap (B = 1000) on the pooled 2126 CV dates; identical draws for every model.

Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): primary: paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= 0.003; secondary: per-date rank-IC delta Newey-West t (lag 20) >= 2.0; ab1_inversion: mean AUC over ['2023-07', '2024-01', '2025-04', '2025-05', '2026-03', '2026-04'] improves by >= 0.02

| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |
|---|---:|---|---|---:|---:|---:|---|---:|---:|
| control | 52 | 0.5455 ± 0.0491 | [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.0878 (9.8) | 0.514 | +0.92% |
| ae1_events | 62 | 0.5447 ± 0.0472 | [0.5357, 0.5537] | 84% | 0.401 | 0.5272 | +0.0874 (10.1) | 0.515 | +1.00% |
| q7_tuned | 52 | 0.5459 ± 0.0509 | [0.5364, 0.5555] | 84% | 0.399 | 0.5230 | +0.0891 (9.6) | 0.512 | +0.97% |

| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---:|---|---|
| ae1_events - control | -0.0008 | [-0.0035, +0.0017] | 51/103 | -0.0004 (-0.2) | +0.001 | +0.0079 | FAIL | FAIL |
| q7_tuned - control | +0.0004 | [-0.0006, +0.0014] | 34/103 | +0.0013 (1.3) | -0.002 | +0.0037 | FAIL | FAIL |
