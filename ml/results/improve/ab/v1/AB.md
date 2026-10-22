# A/B comparison (v1)

Protocol: 43 purged monthly folds, rolling 504-session window, exit-date purge; paired 20-session block bootstrap (B = 1000) on the pooled 881 CV dates; identical draws for every model.

Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): primary: paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= 0.003; secondary: per-date rank-IC delta Newey-West t (lag 20) >= 2.0; ab1_inversion: mean AUC over ['2023-07', '2024-01', '2025-04', '2025-05', '2026-03', '2026-04'] improves by >= 0.02

| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |
|---|---:|---|---|---:|---:|---:|---|---:|---:|
| control | 52 | 0.5379 ± 0.0421 | [0.5268, 0.5509] | 84% | 0.453 | 0.5300 | +0.0699 (6.2) | 0.504 | +0.25% |
| all51 | 50 | 0.5366 ± 0.0426 | [0.5254, 0.5498] | 81% | 0.453 | 0.5327 | +0.0671 (5.8) | 0.501 | +0.23% |
| ab7_subsample5 | 52 | 0.5359 ± 0.0396 | [0.5258, 0.5480] | 86% | 0.444 | 0.5358 | +0.0662 (6.2) | 0.503 | +0.36% |
| ab8_uniqueness_w | 52 | 0.5390 ± 0.0422 | [0.5279, 0.5520] | 84% | 0.454 | 0.5295 | +0.0719 (6.4) | 0.507 | +0.32% |

| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---:|---|---|
| all51 - control | -0.0014 | [-0.0026, -0.0002] | 16/43 | -0.0028 (-2.4) | -0.002 | +0.0027 | FAIL | FAIL |
| ab7_subsample5 - control | -0.0020 | [-0.0041, -0.0000] | 18/43 | -0.0037 (-1.8) | -0.001 | +0.0058 | FAIL | FAIL |
| ab8_uniqueness_w - control | +0.0011 | [-0.0002, +0.0023] | 25/43 | +0.0019 (1.5) | +0.003 | -0.0005 | FAIL | FAIL |
