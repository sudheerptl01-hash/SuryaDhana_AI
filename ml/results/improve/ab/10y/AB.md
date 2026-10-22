# A/B comparison (10y)

Protocol: 103 purged monthly folds, rolling 504-session window, exit-date purge; paired 20-session block bootstrap (B = 1000) on the pooled 2126 CV dates; identical draws for every model.

Pass marks (fixed in `ml/IMPROVEMENT_PLAN.md`): primary: paired CV-mean AUC delta vs control: 95% CI excludes 0 and delta >= 0.003; secondary: per-date rank-IC delta Newey-West t (lag 20) >= 2.0; ab1_inversion: mean AUC over ['2023-07', '2024-01', '2025-04', '2025-05', '2026-03', '2026-04'] improves by >= 0.02

| Configuration | #feat | CV AUC ± sd | 95% CI | Folds ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | Inversion-month AUC | Top-decile gross excess vs EW, 20d |
|---|---:|---|---|---:|---:|---:|---|---:|---:|
| control | 52 | 0.5455 ± 0.0491 | [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.0878 (9.8) | 0.514 | +0.92% |
| lr_l2 | 52 | 0.5423 ± 0.0681 | [0.5297, 0.5545] | 74% | 0.341 | 0.5003 | +0.0818 (6.6) | 0.479 | +0.32% |
| baseline_mom | 1 | 0.5000 ± 0.0420 | [0.4930, 0.5073] | 47% | 0.369 | 0.4690 | +0.0008 (0.1) | 0.498 | -0.35% |

| Variant − control | Δ CV mean | 95% CI | Folds won | Δ rank IC (NW t) | Δ inversion-month AUC | Δ holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---:|---|---|
| lr_l2 - control | -0.0032 | [-0.0104, +0.0033] | 48/103 | -0.0060 (-0.8) | -0.034 | -0.0190 | FAIL | FAIL |
| baseline_mom - control | -0.0456 | [-0.0573, -0.0333] | 24/103 | -0.0871 (-6.9) | -0.016 | -0.0503 | FAIL | FAIL |
