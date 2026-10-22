# A/B comparison (v2)

Protocol: 43 purged monthly folds, rolling 504-session window, exit-date purge; paired 20-session block bootstrap (B = 1000) on the pooled 887 CV dates; identical draws for every model.

Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): primary: paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= 0.003; secondary: per-date rank-IC delta Newey-West t (lag 20) >= 2.0; ab1_inversion: mean AUC over ['2023-07', '2024-01', '2025-04', '2025-05', '2026-03', '2026-04'] improves by >= 0.02

| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |
|---|---:|---|---|---:|---:|---:|---|---:|---:|
| control | 52 | 0.5359 ± 0.0320 | [0.5274, 0.5456] | 88% | 0.466 | 0.5203 | +0.0687 (7.3) | 0.508 | +0.34% |
| lr_l2 | 52 | 0.5396 ± 0.0494 | [0.5264, 0.5543] | 84% | 0.402 | 0.5003 | +0.0735 (5.1) | 0.479 | -0.06% |
| baseline_mom | 1 | 0.4954 ± 0.0309 | [0.4866, 0.5034] | 42% | 0.431 | 0.4690 | -0.0109 (-1.3) | 0.509 | +0.04% |

| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---:|---|---|
| lr_l2 - control | +0.0037 | [-0.0043, +0.0125] | 26/43 | +0.0048 (0.6) | -0.030 | -0.0200 | FAIL | FAIL |
| baseline_mom - control | -0.0405 | [-0.0544, -0.0272] | 8/43 | -0.0797 (-5.8) | +0.001 | -0.0513 | FAIL | FAIL |
