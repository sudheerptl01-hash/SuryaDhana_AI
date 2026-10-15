# SuryaDhana ML Evaluation — Pilot (6-month sample)

Multi-agent evaluation of candidate learning algorithms on the repo's
existing NSE feature/label logic, to pick 1–2 algorithms worth scaling to
the full 5-year history.

## Protocol (fixed — do not deviate per-model)

- **Data**: real NSE EOD bhavcopy, Mar-2025 → Oct-2026, ingested by
  `nse_historical_ingest.py` into DuckDB; modeling rows Jun-2025 onward.
  The extra year before the evaluation window is feature warm-up.
- **Universe**: point-in-time filter — close ≥ ₹10 and trailing-20d median
  turnover ≥ ₹1 crore (no survivorship bias).
- **Features** (~40): the repo's Layer-4 swing features + production-v2
  style additions (`rsi_2`, `ret_63/126/252d`, `mom_12_1`, 200-DMA
  distance/flag, 52w-low flag, split flag, log turnover, cross-sectional
  ranks). Carry and announcement flags are out of scope here (need
  F&O/announcement feeds this repo doesn't ingest).
- **Tasks**:
  - **PRIMARY `beat_mkt_20d`** — will the stock beat the universe median
    over the next 20 sessions, entered at next open? (production v3 label
    convention; `y_clean_20d` masks split/suspension-poisoned labels)
  - **SECONDARY `up_5d`** — the repo's existing 5-day close-to-close label.
- **Splits**: purged walk-forward, 22-session embargo between train end and
  test start (covers the 20-session label overlap). Folds = test months
  Apr, May, Jun, Jul 2026; **holdout = Aug-1 → mid-Sep 2026**, used once,
  never for tuning. Tune on the four CV folds only (or inner splits of
  train).
- **Metrics**: ROC AUC (headline), PR AUC, Brier, accuracy@0.5, decile
  spread and top-decile mean forward return (economic view).
- **Seeds**: 108 everywhere. **CPU**: shared 4-core box — keep `n_jobs ≤ 2`.

## How a modeling agent plugs in

```python
from ml.evaluation import run_standard_eval, load_dataset, iter_folds

run_standard_eval(
    model_name="xgboost", family="trees", agent="quant-trees",
    make_model=lambda task: XGBClassifier(...), preprocess="raw",
    params={...}, notes="tuned on inner validation of CV train")
```

sklearn-style models: `run_standard_eval` does folds, metrics, result JSON
(`ml/results/<model>__<task>.json`) and per-row score dumps
(`ml/results/preds/`). Custom models (PyTorch sequences, RL): use
`iter_folds` / `Fold.train_df` / `Fold.test_df` and write through
`compute_metrics` + `save_results` + `save_preds` with the same schema.

Labels/forward returns (`y_*`, `fwd_*`, `label_*`) use FUTURE prices —
train targets only, never features.

## Layout

```
ml/
  data.py              dataset builder (features + labels + splits)
  evaluation.py        shared walk-forward harness (THE protocol)
  feature_selection.py feature ranking / elimination study
  profile_data.py      data-quality profile
  eval_aggregate.py    league table + date-block bootstrap significance
  make_report.py       generates report/index.html (pilot report)
  eda_features.py      feature EDA: monthly IC, decile shapes, pairs, liquidity
  features_ext.py      23 engineered features (look-ahead checked)
  feature_ab.py        engineered-feature A/B through the harness
  make_feature_study.py generates report/feature_study.html
  models/              one module per model family
  results/             *.json (committed) + preds/ (gitignored)
  results/feature_study/ feature-study outputs, kept out of the league glob
  report/              generated HTML reports
  data/                parquet + manifest + splits (gitignored)
```

`eval_aggregate.py` reads every JSON directly in `results/` as a league entry,
so follow-up studies write to their own subfolder.
