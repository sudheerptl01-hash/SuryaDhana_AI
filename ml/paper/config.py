"""Frozen specification of the paper book (ml/IMPROVEMENT_PLAN_2.md Q1; ml/PROGRAM_REPORT.md §10, §13.7).

Everything the paper book does is fixed here as constants.  SPEC_HASH (SHA-256 of the canonical JSON of
SPEC) is written into ml/paper/ledger/state.json on every run; a run whose code parameters disagree with
SPEC stops before it scores anything (``check_code_matches_spec``).  Definitions and the live-book
interpretations are explained in ml/paper/SPEC.md.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ML_DIR = REPO / "ml"
PAPER_DIR = ML_DIR / "paper"
LEDGER_DIR = PAPER_DIR / "ledger"
MODELS_META_DIR = PAPER_DIR / "models"
STATE_DIR = PAPER_DIR / "state"                     # gitignored: raw files, models, frame, scores
RESULTS_DIR = ML_DIR / "results" / "improve2" / "paper"
DB_PATH = REPO / "nse_market.duckdb"
LOCK_FILE = ML_DIR / "results" / "improve" / "LOCK_duckdb_write"
DATA_EXT = ML_DIR / "data_ext"
CA_FEED_10Y = DATA_EXT / "corporate_actions_feed_10y.csv"
CA_FEED_LIVE = DATA_EXT / "corporate_actions_feed_live.csv"
ETF_10Y = DATA_EXT / "etf_list_10y.csv"
ETF_LIVE = DATA_EXT / "etf_list_live.csv"
DATA_10Y = ML_DIR / "data_10y"
DATA_V2 = ML_DIR / "data_5y_v2"
CONTROL_10Y_PREDS = ML_DIR / "results" / "improve" / "ab" / "10y" / "preds" / "control__beat_mkt_20d.parquet"
BOOKS_JSON = ML_DIR / "results" / "improve" / "books" / "books.json"
CALENDAR_LIVE = PAPER_DIR / "calendar_live.json"
PR_DIRS_RESEARCH = [ML_DIR / "data_raw" / "pr", ML_DIR / "data_raw" / "hist" / "pr"]

SEED = 108
N_THREADS = 2
RESEARCH_END = "2026-10-16"              # last session of the research data
INCEPTION_SIGNAL_DATE = "2026-10-19"     # first session after it
H = 20                                   # tranche horizon and number of slots
TOP_FRAC = 0.10
LIQ_CUT = 0.67
COST_BPS = 20
TRAIN_SESSIONS = 504
EMBARGO_SESSIONS = 22
DATASET_START = "2017-10-02"             # ml/integrity/build_10y.py
HOLDOUT_START = "2026-08-01"
FOLDS_10Y = [(y, m) for y in range(2018, 2026) for m in range(1, 13)] + [(2026, m) for m in range(1, 8)]
COST_PRICE_START = "2026-01-01"          # name-level cost inputs need 60 + 20 sessions of history
N_TRIALS_DSR = 261
VAR_SR_DSR = 0.003868632661070771        # books.json dsr_common.var_sr_daily_across_66_books

LGBM_PARAMS = dict(num_leaves=63, learning_rate=0.05, n_estimators=300, feature_fraction=0.8,
                   bagging_fraction=0.8, bagging_freq=1, min_data_in_leaf=200, random_state=SEED)
RANKER_PARAMS = dict(objective="lambdarank", feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                     min_data_in_leaf=200, num_leaves=63, learning_rate=0.05, n_estimators=300,
                     random_state=SEED)
CB_PARAMS = dict(depth=6, learning_rate=0.05, iterations=600, l2_leaf_reg=5, random_seed=SEED)
LR_PARAMS = dict(C=0.01, max_iter=1000)

BOOKS = {
    "primary":       {"scorer": "lgbm", "neutralisation": "vol+size", "basket": "top_decile",
                      "benchmark": "ew_universe"},
    "capacity":      {"scorer": "lgbm", "neutralisation": "vol+size", "basket": "liq_top_decile",
                      "benchmark": "ew_liquid"},
    "challenger":    {"scorer": "ensemble", "neutralisation": "vol+size", "basket": "top_decile",
                      "benchmark": "ew_universe"},
    "control_plain": {"scorer": "lgbm", "neutralisation": "none", "basket": "top_decile",
                      "benchmark": "ew_universe"},
}
BOOK_ORDER = list(BOOKS)

MONITORS = {
    "delivery_resid_ic": {"rule": "monthly mean per-date residual IC of deliv_pct_sma_20 (controls log_turnover, "
                                  "atr_pct, mom_12_1) vs y_excess_20d", "threshold": 0.02,
                          "alert": "below threshold for 2 consecutive complete months"},
    "live_model_auc": {"rule": "AUC of the month's model on its month's signal dates (matured labels)",
                       "threshold": 0.50, "alert": "below threshold"},
    "rank_ic_nw_t_12m": {"rule": "per-date rank IC of the primary model score vs y_excess_20d, trailing 12 months "
                                 "of matured signal dates, Newey-West t (20 lags)", "threshold": 2.0,
                         "alert": "below threshold"},
    "logistic_sign_flips": {"rule": "L2 logistic monitor (C = 0.01, scaled), top 5 coefficients by magnitude, "
                                    "sign vs the previous month's fit", "threshold": 0, "alert": "any flip"},
    "feature_psi": {"rule": "PSI of each of the 52 features, trailing 20 sessions vs the current model's "
                            "training window, 10 training-quantile bins", "threshold": 0.25,
                    "alert": "any feature above threshold"},
    "paper_active_ir_6m": {"rule": "daily active return (net 20 bps book minus benchmark), trailing 6 months, "
                                   "month-block bootstrap IR CI", "threshold": 0.0,
                           "alert": "CI entirely below zero"},
    "feature_inversion": {"rule": "share of the 52 features whose monthly IC has the opposite sign of their IC "
                                  "over the current model's training window", "threshold": 0.5,
                          "alert": "more than half"},
    "ensemble_atr_corr": {"rule": "monthly mean of the per-date Spearman correlation of the raw ensemble score "
                                  "with atr_pct", "threshold": 0.20, "alert": "absolute value above threshold"},
    "neutral_score_corr": {"rule": "per-date Spearman correlation of the neutralised primary and challenger "
                                   "scores with atr_pct and log_turnover", "threshold": 0.05,
                           "alert": "absolute value above threshold"},
    "universe_etf_count": {"rule": "universe names on the signal date that appear in an ETF list", "threshold": 0,
                           "alert": "above threshold"},
    "split_flag_rate": {"rule": "share of universe names with flag_split_20d = 1 on the signal date",
                        "threshold": 0.01, "alert": "above threshold"},
    "data_quality": {"rule": "new sessions: duplicate EQ/BE pairs, prev_close continuity share, unresolved "
                             "calendar dates, unvalidated corporate actions", "threshold": 0.05,
                     "alert": "duplicates > 0, continuity share > threshold, or an unresolved date"},
}

SPEC = {
    "name": "SuryaDhana paper book",
    "version": 1,
    "frozen_on": "2026-10-23",
    "sources": ["ml/IMPROVEMENT_PLAN_2.md Q1", "ml/PROGRAM_REPORT.md section 10", "ml/PROGRAM_REPORT.md section 13.7"],
    "research_end": RESEARCH_END, "inception_signal_date": INCEPTION_SIGNAL_DATE,
    "dataset": {"code_path": "ml.data.build_dataset + ml.integrity.build_v2.extra_columns",
                "dataset_start": DATASET_START, "holdout_start": HOLDOUT_START, "fold_months": "2018-01..2026-07",
                "universe_price_col": "close_unadj", "isnan_features": "pinned to ml/data_5y_v2/manifest.json",
                "exclude_tickers": "etf_list_10y.csv + etf members of the live PR bundles", "read_only": True,
                "min_price": 10.0, "min_median_turnover_20d": 1e7},
    "training": {"retrain": "first session of each calendar month", "train_sessions": TRAIN_SESSIONS,
                 "embargo_sessions": EMBARGO_SESSIONS, "exit_date_purge": True,
                 "rows": "labelled, y_clean_20d", "window_rule": "ml.scale5y_nested.window_rows"},
    "models": {"lgbm": LGBM_PARAMS, "lambdarank": {**RANKER_PARAMS, "grade": "floor(10 * y_rank_20d) clipped 0..9",
                                                   "score": "sigmoid(raw)"},
               "catboost": CB_PARAMS, "ensemble": "mean of per-date percentile ranks of lgbm, lambdarank, catboost",
               "monitor_logistic": {**LR_PARAMS, "preprocess": "scaled"}, "preprocess": "raw (median impute)",
               "threads": N_THREADS, "seed": SEED},
    "books": BOOKS, "top_frac": TOP_FRAC, "liq_cut": LIQ_CUT,
    "tranches": {"H": H, "slots": H, "entry": "open of t+1", "exit": "open of t+21", "weights": "equal",
                 "marks": "entry open->close, close->close, exit close->open (SPEC.md 2.2)"},
    "costs": {"flat_bps_per_side": COST_BPS, "netting": "entry vs the tranche replaced, exit vs the tranche entering",
              "inception": "first 20 tranches buy 100%", "name_level": "ml.books.engine.name_cost_fracs, AUM 1e9 Rs",
              "cost_price_start": COST_PRICE_START},
    "dsr": {"N": N_TRIALS_DSR, "var_sr": VAR_SR_DSR},
    "monitors": MONITORS,
}


def spec_hash(spec: dict = SPEC) -> str:
    blob = json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(blob).hexdigest()


SPEC_HASH = spec_hash()


def check_code_matches_spec() -> dict:
    """The shared research code must still carry the frozen parameters (guards against silent drift)."""
    import ml.scale5y as s5
    from ml.scale5y_nested import CB_PARAMS as CB_CODE
    import ml.strategy_backtest as sb
    p = s5.make_model("all51", N_THREADS).get_params()
    bad = {k: (p.get(k), v) for k, v in LGBM_PARAMS.items() if p.get(k) != v}
    bad.update({f"cb.{k}": (CB_CODE.get(k), v) for k, v in CB_PARAMS.items() if CB_CODE.get(k) != v})
    lr = s5.make_model("lr_l2", N_THREADS).get_params()
    bad.update({f"lr.{k}": (lr.get(k), v) for k, v in LR_PARAMS.items() if lr.get(k) != v})
    if sb.TOP_FRAC != TOP_FRAC or sb.LIQ_CUT != LIQ_CUT or sb.HORIZON != H:
        bad["strategy_backtest"] = (sb.TOP_FRAC, sb.LIQ_CUT, sb.HORIZON)
    if bad:
        raise SystemExit(f"research code no longer matches the frozen paper specification: {bad}")
    return {"lgbm": "match", "catboost": "match", "logistic": "match", "strategy_backtest": "match"}
