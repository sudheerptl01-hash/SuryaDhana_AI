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
- **Metrics**: ROC AUC (headline), PR AUC, Brier, hit rate at 0.5, decile
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
  GOALS.md             "how good is good enough": measurable criteria by stage, with external anchors
  MODEL_SELECTION.md   pilot model-selection memo (with the post-audit correction and 5-year outcome)
  SCALE_UP.md          5-year plan and the five pre-registered promotion gates (scored)
  PROCESS.md           the improvement cycle: steps, the failure each prevents, what moved the numbers
  PROMPT.md            the cycle, the daily paper book and a single A/B as agent prompts
  ROADMAP.md           what is open, the next action and the data each item needs
  IMPROVEMENT_PLAN*.md pre-registrations (phase 1, phase 2) with dated amendments and the trial ledger
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
  make_community_report.py generates report/community_calibration.html
  models/              one module per model family (incl. models/sota.py)
  research/            literature review (SOTA_FORECASTING.md, sota_map.json)
  research/community/  what the internet reports (122 graded entries) + COMMUNITY_CALIBRATION.md
  results/             pilot league *.json (committed) + preds/ (gitignored)
  results/feature_study/      feature EDA + A/B outputs
  results/feature_sufficiency/ FEATURE_SUFFICIENCY.md + evidence
  results/label_study/        LABEL_STUDY.md + IC/AUC matrices
  results/audit/              AUDIT.md + audit.json
  results/strategy/           STRATEGY.md + strategy.json + monthly tables
  results/sota/               SOTA_MODELS.md + league_summary.json
  results/scale5y/            5-year results, nested_selection.json, SCALE5Y.md
  report/              generated HTML reports (index, feature_study, program_report, community_calibration)
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

## Improvement phase (October 2026; `ml/IMPROVEMENT_PLAN.md`, results in `ml/results/improve/`)

Pre-registered plan first, then five streams and a lead-run compute queue:

- `ml/integrity/` – missing and mis-dated sessions, corporate-action feed from the archive's PR bundles, ETF lists, the one writer of `nse_market.duckdb` (lock-file protocol), v2 and ten-year dataset builders (`ml/data_5y_v2/`, `ml/data_10y/`, gitignored); reports in `results/improve/integrity/`.
- `ml/books/` – book construction on out-of-sample scores: neutralisation, buffered baskets, 40-session hold, name-level costs, DSR; `results/improve/books/`.
- `ml/extdata/` – F&O, index, VIX, participant-OI and industry data from the archive; feature families F1-F4 and the sector placebo (`ml/data_ext/`, gitignored); `results/improve/extdata/`.
- `ml/history/` – 2016-10..2021-09 backfill from legacy CM bhavcopy, MTO delivery files and PR bundles (`ml/data_hist/`, gitignored); `results/improve/history/`.
- `ml/hygiene/` – probability of backtest overfitting (CSCV), delivery durability, label uniqueness; `results/improve/hygiene/`.
- `ml/improve/ab.py` (A/B harness: walk-forward, exit-date purge, paired block bootstrap, pass marks), `ml/improve/ab_books.py` (every configuration as a book), `ml/improve/gates.py` (the five gates at the phase's N); outputs under `results/improve/ab/<tag>/` (v1, v2, 10y).
- Results of record: `ml/results/improve/IMPROVEMENT_RESULTS.md`; what stays open: `ml/ROADMAP.md`.

## Improvement phase 2 (October 2026; `ml/IMPROVEMENT_PLAN_2.md`, results in `ml/results/improve2/`)

- `ml/paper/` – the forward record (paper book, no capital): `job.py` (the one daily command), `ingest.py` (store writes under the lock, with the consolidation-spelling extension), `frame.py`, `models.py`, `book.py`, `monitors.py`, `report.py`, `prove.py` (byte-identical rebuild), `SPEC.md` (frozen specification and its dated amendments), `RUNBOOK.md`, `ledger/` (append-only, committed), `state/` (gitignored); report in `results/improve2/paper/`.
- `ml/events/` – announcement records from the PR bundles' `an` files: parser, rule-based classifier (`vocabulary.json`), ten point-in-time event features, checks, IC study; `results/improve2/events/`.
- `ml/improve/liquid.py` (Q3, liquid-universe models), `fo_ls.py` (Q4, F&O long-short through stock futures), `h40.py` (Q5, 40-day horizon), `tune.py` (Q7, nested tuning), `cpcv.py` (Q2, combinatorial purged CV), `q9.py` (expanding training window), `q10.py` (seed calibration); outputs under `results/improve2/<stream>/`, the A/B tag `results/improve/ab/10y_p2/` (configurations, seed replicates, books and gates at N = 270), queue scripts in `results/improve2/queue/`.
- Results of record: `ml/results/improve2/IMPROVEMENT_RESULTS.md`. The method as a reusable cycle: `ml/PROCESS.md`; the same as prompts an agent team can run: `ml/PROMPT.md`.
