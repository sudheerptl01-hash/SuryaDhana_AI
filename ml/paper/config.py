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


# =====================================================================================================================
# Extension 1 (ml/paper/SPEC.md section 5, amendment 10; registered 2026-10-23T09:17:13Z, before the expanding model
# was trained and before any row of the two new books existed).  SPEC and SPEC_HASH above are unchanged: they cover
# the four frozen books.  The extension has its own specification (SPEC_EXT) and hash (SPEC_EXT_HASH).
# Source: ml/IMPROVEMENT_PLAN_2.md section 4, A1 (Q9, the control with an expanding training window: "a pass is
# evidence for a forward test, not a promotion"); result ml/results/improve2/expanding/EXPANDING.md.
# =====================================================================================================================
EXT_NAME = "expanding"
EXT_REGISTERED_UTC = "2026-10-23T09:17:13Z"
EXT_TRAIN_SESSIONS = 0                    # 0 = expanding: every labelled clean row from the frame's first session
EXT_FIRST_DATASET_SESSION = "2017-10-03"  # the first row of the dataset (DATASET_START 2017-10-02 was a closure)
EXT_FIRST_SIGNAL_DATE = INCEPTION_SIGNAL_DATE
EXT_BACKFILL_THROUGH = "2026-10-22"       # the ledger's last signal date and marked session when the extension was added
EXT_N_TRIALS_DSR = 270                    # the trial ledger at registration (plan 2 section 4, A2)
EXT_BOOKS = {
    "challenger_expanding": {"scorer": "lgbm_expanding", "neutralisation": "vol+size", "basket": "top_decile",
                             "benchmark": "ew_universe"},
    "capacity_expanding":   {"scorer": "lgbm_expanding", "neutralisation": "vol+size", "basket": "liq_top_decile",
                             "benchmark": "ew_liquid"},
}
EXT_BOOK_ORDER = list(EXT_BOOKS)
ALL_BOOKS = {**BOOKS, **EXT_BOOKS}
ALL_BOOK_ORDER = BOOK_ORDER + EXT_BOOK_ORDER
EXT_COUNTERPART = {"challenger_expanding": "primary", "capacity_expanding": "capacity"}

# The research record of Q9 (pre-inception readings of the extension's model monitors).  Both files are hashed into
# SPEC_EXT; a run stops when either differs (ml/paper/RUNBOOK.md section 8).
Q9_DIR = ML_DIR / "results" / "improve" / "ab" / "10y_p2"
Q9_PREDS = Q9_DIR / "preds" / "q9_expanding__beat_mkt_20d.parquet"
Q9_JSON = Q9_DIR / "q9_expanding__beat_mkt_20d.json"
Q9_PREDS_SHA256 = "191c396f7c542f60603d8f773d8ecb9b0f3f85f6cb7b20ecd54eae2363fe4067"
Q9_JSON_SHA256 = "bb5794fe0f389073263b28cf25877ab04169eeaf917733a20087aa7073323256"

EXT_MONITORS = {
    "live_model_auc_expanding": {"rule": "AUC of the month's expanding-window model on its month's signal dates "
                                         "(matured labels); before a live month matures, the Q9 research walk-forward "
                                         "(last fold, holdout)", "threshold": 0.50, "alert": "below threshold"},
    "rank_ic_nw_t_12m_expanding": {"rule": "per-date rank IC of the expanding-window model score vs y_excess_20d, "
                                           "trailing 12 months of matured signal dates (the Q9 research walk-forward "
                                           "before inception, live scores after), Newey-West t (20 lags)",
                                   "threshold": 2.0, "alert": "below threshold"},
    "paper_active_ir_6m": {"books": EXT_BOOK_ORDER, "rule": "as the frozen monitor of the same name, per extension book "
                                                            "(benchmark of the book)", "threshold": 0.0,
                           "alert": "CI entirely below zero"},
    "neutral_score_corr": {"books": ["challenger_expanding"], "rule": "per-date Spearman correlation of the "
                                                                      "neutralised expanding-window score with atr_pct "
                                                                      "and log_turnover", "threshold": 0.05,
                           "alert": "absolute value above threshold"},
}
for _k in ("paper_active_ir_6m", "neutral_score_corr"):
    assert EXT_MONITORS[_k]["threshold"] == MONITORS[_k]["threshold"], _k

SPEC_EXT = {
    "name": "SuryaDhana paper book, extension 1: expanding-window challenger",
    "version": 1,
    "registered_utc": EXT_REGISTERED_UTC,
    "amendment": "ml/paper/SPEC.md section 5 (amendment 10)",
    "extends_spec_hash": SPEC_HASH,
    "frozen_books_unchanged": BOOK_ORDER,
    "sources": ["ml/IMPROVEMENT_PLAN_2.md section 4 A1 (Q9)", "ml/results/improve2/expanding/EXPANDING.md",
                "ml/improve/ab.py q9_expanding"],
    "books": EXT_BOOKS, "counterpart": EXT_COUNTERPART, "top_frac": TOP_FRAC, "liq_cut": LIQ_CUT,
    "model": {"member": "lgbm", "params": LGBM_PARAMS, "construction": 'ml.scale5y.make_model("all51")',
              "preprocess": "raw (median impute)", "features": "the 52 features of the frozen specification",
              "threads": N_THREADS, "seed": SEED},
    "training": {"retrain": "first session of each calendar month", "train_sessions": EXT_TRAIN_SESSIONS,
                 "window": "every labelled clean row (y_clean_20d) from the first dataset session "
                           f"({EXT_FIRST_DATASET_SESSION}) to train_end; no 504-session cap",
                 "embargo_sessions": EMBARGO_SESSIONS, "exit_date_purge": True,
                 "window_rule": "ml.scale5y_nested.window_rows(train_sessions=0), as ml/improve/ab.py q9_expanding"},
    "neutralisation": "ml.books.engine.neutralise(kind='vol+size') on the date's full universe, as the primary book",
    "tranches": SPEC["tranches"], "costs": SPEC["costs"],
    "first_signal_date": EXT_FIRST_SIGNAL_DATE,
    "backfill": {"through": EXT_BACKFILL_THROUGH, "signal_dates": ["2026-10-19", "2026-10-21", "2026-10-22"],
                 "model": "the 2026-10 expanding-window model, trained as of 2026-10-01 (train_end 2026-08-31, exit-date "
                          "purge at 2026-10-01)"},
    "ledger_order": "signals, marks, monitors: the rows of the frozen books for dates up to the backfill date first "
                    "(the ledger as it stood at the amendment), then the extension books' rows for the same dates (the "
                    "backfill block), then from the next date on every date's rows in (date, book, rank) order over "
                    "the six books, frozen books first; per monitor session the frozen monitors' rows, then the "
                    "extension's",
    "dsr": {"N": EXT_N_TRIALS_DSR, "var_sr": VAR_SR_DSR},
    "monitors": EXT_MONITORS,
    "reference_record": {"q9_walk_forward_preds": {"path": "ml/results/improve/ab/10y_p2/preds/q9_expanding__beat_mkt_20d.parquet",
                                                   "sha256": Q9_PREDS_SHA256},
                         "q9_summary": {"path": "ml/results/improve/ab/10y_p2/q9_expanding__beat_mkt_20d.json",
                                        "sha256": Q9_JSON_SHA256}},
}
SPEC_EXT_HASH = spec_hash(SPEC_EXT)


def ext_block(date: str, book_or_group: str) -> int:
    """Ledger block of a row (SPEC_EXT['ledger_order']): 0 = frozen rows up to the backfill date, 1 = extension rows
    up to it (the backfill block), 2 = every row after it."""
    if date > EXT_BACKFILL_THROUGH:
        return 2
    return 1 if book_or_group in EXT_BOOKS or book_or_group == EXT_NAME else 0


def check_extension_inputs() -> dict:
    """The research record the extension's pre-inception monitor readings use must be the registered one."""
    from ml.paper.common import sha256_file
    bad = {}
    for p, h in ((Q9_PREDS, Q9_PREDS_SHA256), (Q9_JSON, Q9_JSON_SHA256)):
        got = sha256_file(p) if p.exists() else None
        if got != h:
            bad[str(p.relative_to(REPO))] = got
    if bad:
        raise SystemExit(f"the Q9 research record registered in SPEC_EXT changed or is missing: {bad}; see "
                         "ml/paper/RUNBOOK.md section 8")
    return {"q9_preds": "match", "q9_summary": "match"}
