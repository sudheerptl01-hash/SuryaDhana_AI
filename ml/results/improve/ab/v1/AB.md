# A/B comparison (v1)

Protocol: 43 purged monthly folds, rolling 504-session window, exit-date purge; paired 20-session block bootstrap (B = 1000) on the pooled 881 CV dates; identical draws for every model.

Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): primary: paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= 0.003; secondary: per-date rank-IC delta Newey-West t (lag 20) >= 2.0; ab1_inversion: mean AUC over ['2023-07', '2024-01', '2025-04', '2025-05', '2026-03', '2026-04'] improves by >= 0.02

| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |
|---|---:|---|---|---:|---:|---:|---|---:|---:|
| control | 52 | 0.5379 ± 0.0421 | [0.5268, 0.5509] | 84% | 0.453 | 0.5300 | +0.0699 (6.2) | 0.504 | +0.25% |
| all51 | 50 | 0.5366 ± 0.0426 | [0.5254, 0.5498] | 81% | 0.453 | 0.5327 | +0.0671 (5.8) | 0.501 | +0.23% |

| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---:|---|---|
| all51 - control | -0.0014 | [-0.0026, -0.0002] | 16/43 | -0.0028 (-2.4) | -0.002 | +0.0027 | FAIL | FAIL |
