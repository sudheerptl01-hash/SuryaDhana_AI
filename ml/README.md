# SuryaDhana ML Evaluation

Multi-agent research program on the repo's NSE feature/label logic: a
6-month pilot that picked the algorithm family, a set of follow-up studies
(features, labels, sufficiency, audit, strategy, state-of-the-art models),
and a 5-year walk-forward. **Start with `ml/PROGRAM_REPORT.md`** (verdicts,
status, deliverables) or its HTML form `ml/report/program_report.html`;
each study's own verdict file is listed in the layout below.

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
  PROGRAM_REPORT.md    program verdicts, status board, deliverables, recommendations
  MODEL_SELECTION.md   pilot model-selection memo (with the post-audit correction)
  SCALE_UP.md          5-year plan and the five pre-registered promotion gates
  data.py              dataset builder (features + labels + splits); parameterised
  build_5y.py          5-year dataset (ml/data_5y/, 43 monthly folds 2023-01..2026-07)
  evaluation.py        shared walk-forward harness (THE protocol)
  feature_selection.py feature ranking / elimination study
  profile_data.py      data-quality profile
  eval_aggregate.py    pilot league table + date-block bootstrap significance
  make_report.py       generates report/index.html (pilot report)
  eda_features.py      feature EDA: monthly IC, decile shapes, pairs, liquidity
  features_ext.py      23 engineered features (look-ahead checked)
  feature_ab.py        engineered-feature A/B through the harness
  make_feature_study.py generates report/feature_study.html
  feature_sufficiency.py unused bhavcopy information, residual IC, external-data gaps
  label_study.py       feature x label predictive-power matrix over 28 label variants
  audit.py             red-team audit: leakage, permutation null, best-of-N, nested selection
  strategy_backtest.py net-of-cost portfolio engine, capacity, Deflated Sharpe
  scale5y.py           5-year walk-forward runner (rolling 504-session window, parallel)
  scale5y_nested.py    nested per-year feature selection + exit-date purge + ensemble
  scale5y_report.py    5-year league, block bootstrap, regimes, portfolio, gates
  make_program_report.py generates report/program_report.html
  models/              one module per model family (incl. models/sota.py)
  research/            literature review (SOTA_FORECASTING.md, sota_map.json)
  results/             pilot league *.json (committed) + preds/ (gitignored)
  results/feature_study/      feature EDA + A/B outputs
  results/feature_sufficiency/ FEATURE_SUFFICIENCY.md + evidence
  results/label_study/        LABEL_STUDY.md + IC/AUC matrices
  results/audit/              AUDIT.md + audit.json
  results/strategy/           STRATEGY.md + strategy.json + monthly tables
  results/sota/               SOTA_MODELS.md + league_summary.json
  results/scale5y/            5-year results, nested_selection.json, SCALE5Y.md
  report/              generated HTML reports (index, feature_study, program_report)
  data/, data_5y/      parquet + manifest + splits (gitignored)
```

`eval_aggregate.py` reads every JSON directly in `results/` as a pilot league
entry, so every follow-up study writes to its own subfolder. Prediction
parquets (`results/*/preds/`) and the selection cache are gitignored.

## 5-year protocol (`ml/SCALE_UP.md`)

Same harness, 43 monthly folds (2023-01 to 2026-07), rolling 504-session
training window, 22-session embargo, training rows purged on each label's
actual exit date, holdout 2026-08-03 to 2026-09-16 used once. Feature
selection, where used, is nested inside each training history
(`scale5y_nested.py`). Significance uses 20-session block bootstraps. The
first year of folds trains on short windows (the dataset starts 2022-10-03),
which every per-year table must state.
