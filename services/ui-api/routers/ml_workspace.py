"""
ML Engine Workspace — live, cancellable XGBoost direction-model training desk.

Trains a binary up/down classifier on `ml_features` ⋈ `ml_labels` (5-day horizon),
streaming per-round telemetry (log-loss, AUC, Gini) over NDJSON so the cockpit can
plot a convergence curve in real time.

Kill-switch contract: a per-run `threading.Event` is observed by an XGBoost
`TrainingCallback`. Setting it stops boosting cleanly at the next round boundary,
preserves the partial model (persisted to disk), and the run terminates as
`TERMINATED_BY_USER` — no leaked thread, no torn state, no half-written file.

Look-ahead discipline: the train/validation split is strictly chronological — the
validation fold is always the most-recent slice of dates (never shuffled), exactly
as CLAUDE.md mandates for time-series. Features are trailing; the label is forward.
Because the label is a forward 5-day window, training rows adjacent to the split
would otherwise observe validation-era prices, so a López de Prado *purge gap*
(label_horizon + embargo trading days) is removed ahead of the validation start;
optional exponential time-decay sample weights let recent regimes dominate.

MODE = PAPER: this module only fits models; it never places an order.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers import analytics as _an  # reuse the read-replica snapshot helpers

router = APIRouter()

MODE = "PAPER"

# Curated, leakage-safe trailing feature set (the label is the forward 5-day
# direction from ml_labels; every column below is computed up to and incl. day T).
FEATURE_COLUMNS: list[str] = [
    "ret_1d", "ret_5d", "ret_20d", "log_ret",
    "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "rsi_14", "rsi_7", "rsi_28",
    "macd", "macd_signal", "macd_hist",
    "bollinger_pctb", "bb_width", "atr_14_pct", "realized_vol_20d",
    "volume_zscore", "volume_ratio", "obv", "gap_pct", "high_low_ratio", "close_position",
    "stoch_k", "stoch_d", "williams_r", "roc_5", "roc_10", "roc_20", "mfi_14", "cmf_20",
    "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
    "india_vix", "vix_zscore", "nifty_ret_5d", "nifty_regime", "market_breadth", "usd_inr",
    "trailing_pe", "price_to_book", "ev_to_ebitda", "peg_ratio",
    "revenue_growth", "gross_margins", "operating_margins", "profit_margins",
    "return_on_equity", "return_on_assets", "debt_to_equity", "current_ratio", "altman_z",
]

MODEL_DIR = os.getenv("ML_WORKSPACE_MODEL_DIR",
                      os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "ml_workspace"))


# ── Run registry (in-memory; one process serves the cockpit) ──────────────────────

class _RunState:
    __slots__ = ("run_id", "cancel", "status", "created_at", "iteration", "total_rounds")

    def __init__(self, run_id: str, total_rounds: int):
        self.run_id = run_id
        self.cancel = threading.Event()
        self.status = "TRAINING"
        self.created_at = time.time()
        self.iteration = 0
        self.total_rounds = total_rounds


_RUNS: dict[str, _RunState] = {}
_RUNS_LOCK = threading.Lock()
_MAX_RUNS = 32  # bound the registry so long-lived processes don't leak run rows


def _register(total_rounds: int) -> _RunState:
    rid = uuid.uuid4().hex[:16]
    st = _RunState(rid, total_rounds)
    with _RUNS_LOCK:
        if len(_RUNS) >= _MAX_RUNS:  # evict oldest finished runs
            for k in sorted(_RUNS, key=lambda k: _RUNS[k].created_at):
                if _RUNS[k].status != "TRAINING":
                    _RUNS.pop(k, None)
                if len(_RUNS) < _MAX_RUNS:
                    break
        _RUNS[rid] = st
    return st


# ── Request contracts ─────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    mode: str = "sample"                 # "sample" (fast health check) | "production"
    tickers: list[str] = []              # empty → universe (production) / auto-pick (sample)
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    n_estimators: int = 300              # boosting rounds (sample clamps to a small slice)
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    valid_fraction: float = 0.25         # most-recent date slice held out (chronological)
    # Leakage control (López de Prado purging/embargo for overlapping forward labels):
    label_horizon: int = 5               # forward label horizon in trading days (ml_labels=5)
    embargo_days: int = 5                # extra trading-day gap purged ahead of the label window
    weight_halflife_days: int = 0        # >0 ⇒ exponential time-decay sample weights (0 = uniform)
    # López de Prado labelling (G7):
    label_kind: str = "direction"        # "direction" (up/down) | "barrier" (profit-target reached)
    meta_labeling: bool = False          # train a secondary meta-model: P(primary signal is correct)
    # Robust generalization estimate (G8): purged K-fold CV (mean ± std AUC/Gini):
    robust_eval: bool = False
    robust_folds: int = 5


class StopRequest(BaseModel):
    run_id: str


# ── Data assembly ─────────────────────────────────────────────────────────────────

def _present_features(con) -> list[str]:
    cols = {r[1] for r in con.execute("PRAGMA table_info('ml_features')").fetchall()}
    return [c for c in FEATURE_COLUMNS if c in cols]


def _load_training_frame(req: TrainRequest) -> tuple[pd.DataFrame, list[str]]:
    """Assemble the supervised matrix (features + forward-direction label), sorted
    chronologically. Returns (df, feature_columns)."""
    con, owns = _an._acquire_readonly(lambda *a, **k: None)
    try:
        feats = _present_features(con)
        if not feats:
            raise HTTPException(status_code=503, detail="ml_features table is empty/unavailable")

        # Resolve the window. Sample mode = a small recent slice over 5 liquid names.
        max_date = con.execute("SELECT MAX(date) FROM ml_features").fetchone()[0]
        if max_date is None:
            raise HTTPException(status_code=503, detail="No ml_features rows ingested yet")
        max_date = pd.Timestamp(max_date).date()

        tickers = [t.upper() for t in req.tickers] if req.tickers else []
        if req.mode == "sample":
            to_d = max_date
            from_d = req.from_date and datetime.strptime(req.from_date, "%Y-%m-%d").date() \
                or (to_d - timedelta(days=185))
            if not tickers:
                tickers = [r[0] for r in con.execute(
                    "SELECT ticker FROM stock_metrics WHERE mktcap_cr IS NOT NULL "
                    "ORDER BY mktcap_cr DESC LIMIT 5").fetchall()]
        else:
            to_d = datetime.strptime(req.to_date, "%Y-%m-%d").date() if req.to_date else max_date
            from_d = datetime.strptime(req.from_date, "%Y-%m-%d").date() if req.from_date \
                else (to_d - timedelta(days=365 * 3))

        feat_sql = ", ".join(f"f.{c}" for c in feats)
        params: list = [from_d, to_d]
        ticker_clause = ""
        if tickers:
            ticker_clause = "AND f.ticker IN (" + ",".join(["?"] * len(tickers)) + ")"
            params.extend(tickers)
        # Pull both labels + the barrier thresholds so the target can be re-derived
        # without another query. label_direction filters NULLs; barrier needs return.
        sql = f"""
            SELECT f.date, f.ticker, {feat_sql},
                   l.label_direction AS y_dir, l.label_return_pct AS y_ret,
                   l.profit_target_pct AS y_tgt, l.label_barrier AS y_bar
            FROM ml_features f
            JOIN ml_labels l ON f.ticker = l.ticker AND f.date = l.date
            WHERE l.horizon_days = 5 AND l.label_return_pct IS NOT NULL
              AND f.date BETWEEN ? AND ? {ticker_clause}
            ORDER BY f.date, f.ticker
        """
        rows = con.execute(sql, params).fetchdf()
    finally:
        if owns:
            try:
                con.close()
            except Exception:
                pass

    if rows is None or rows.empty:
        raise HTTPException(status_code=422, detail="No labelled feature rows in the selected window/scope")
    # nifty_regime is stored as text (bull/range/bear); XGBoost needs numbers
    # ("could not convert string to float: 'range'"). Encode it, and coerce any other
    # non-numeric feature column so a future text column can't crash training.
    if "nifty_regime" in rows.columns:
        rows["nifty_regime"] = rows["nifty_regime"].map({"bull": 1, "range": 0, "bear": -1})
    for c in feats:
        if c in rows.columns and not pd.api.types.is_numeric_dtype(rows[c]):
            rows[c] = pd.to_numeric(rows[c], errors="coerce")
    rows = rows.replace([np.inf, -np.inf], np.nan)
    # Derive the supervised target (G7). "barrier" = did price TOUCH the profit target
    # before the stop within the horizon (triple-barrier, label_barrier == +1). Older
    # datasets without path labels fall back to the terminal-return approximation.
    # "direction" = beat the round-trip cost hurdle over the horizon.
    if req.label_kind == "barrier":
        rows = rows[rows["y_ret"].notna()].copy()
        if rows["y_bar"].notna().any():
            rows = rows[rows["y_bar"].notna()]
            rows["y"] = (rows["y_bar"] == 1).astype(int)
        else:
            rows["y"] = (rows["y_ret"] >= rows["y_tgt"].fillna(2.0)).astype(int)
    else:
        rows = rows[rows["y_dir"].notna()].copy()
        rows["y"] = rows["y_dir"].astype(int).clip(0, 1)
    rows = rows.drop(columns=["y_dir", "y_ret", "y_tgt", "y_bar"], errors="ignore")
    rows["date"] = pd.to_datetime(rows["date"])
    return rows, feats


def _purged_split(udates: np.ndarray, valid_fraction: float, horizon: int, embargo: int):
    """Chronological split with a *purge gap* between training labels and validation.

    The validation fold is the most-recent `valid_fraction` of distinct trading dates.
    A training sample at date d carries a label observing returns over (d, d+horizon];
    if that window reaches into the validation period its label "saw" validation-era
    prices → leakage. We therefore purge the `horizon + embargo` trading days
    immediately before the split so no training label overlaps (or sits adjacent to)
    the validation fold.

    Returns (split_date, purge_date, cut_i, purge_i): training keeps date < purge_date,
    validation keeps date >= split_date.
    """
    n = len(udates)
    vf = min(max(valid_fraction, 0.05), 0.5)
    cut_i = max(1, min(int(n * (1 - vf)), n - 1))
    split_date = udates[cut_i]
    gap = max(0, int(horizon) + int(embargo))
    purge_i = max(0, cut_i - gap)
    purge_date = udates[purge_i]
    return split_date, purge_date, cut_i, purge_i


def _purged_kfold_bounds(n_dates: int, k: int, gap: int) -> list[tuple]:
    """Index bounds into the sorted unique dates for a Purged K-Fold CV (López de Prado
    AFML ch. 7). Each fold yields (test_lo, test_hi, purge_lo, purge_hi): the test block
    is udates[test_lo:test_hi]; training uses every date OUTSIDE udates[purge_lo:purge_hi],
    where the purge zone extends `gap = horizon + embargo` trading days around the test
    block on both sides so no training label overlaps the test fold."""
    k = max(2, int(k))
    fold = max(1, n_dates // k)
    out = []
    for i in range(k):
        lo = i * fold
        hi = (i + 1) * fold if i < k - 1 else n_dates
        if lo >= n_dates:
            break
        out.append((lo, hi, max(0, lo - gap), min(n_dates, hi + gap)))
    return out


def _robust_purged_eval(xgb, df, feats: list[str], params: dict, rounds: int,
                        k: int, gap: int) -> Optional[dict]:
    """Purged K-Fold generalization estimate: AUC/Gini mean ± std across `k` purged
    folds, so the OOS metric is a distribution rather than a single point. Reuses the
    same purge gap as the chronological split. Returns None when history is too short."""
    from sklearn.metrics import roc_auc_score
    udates = np.sort(df["date"].unique())
    n = len(udates)
    if n < k * 4:
        return None
    aucs, n_test = [], []
    for lo, hi, plo, phi in _purged_kfold_bounds(n, k, gap):
        test_dates = set(udates[lo:hi])
        purge_dates = set(udates[plo:phi])
        te = df[df["date"].isin(test_dates)]
        tr = df[~df["date"].isin(purge_dates)]
        if len(te) < 20 or len(tr) < 50:
            continue
        y_tr = tr["y"].to_numpy(dtype=int); y_te = te["y"].to_numpy(dtype=int)
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            continue
        booster = xgb.train(params, xgb.DMatrix(tr[feats].to_numpy(float), label=y_tr,
                            feature_names=feats), num_boost_round=min(int(rounds), 120),
                            verbose_eval=False)
        proba = booster.predict(xgb.DMatrix(te[feats].to_numpy(float), feature_names=feats))
        try:
            aucs.append(float(roc_auc_score(y_te, proba)))
            n_test.append(int(len(te)))
        except Exception:
            continue
    if len(aucs) < 2:
        return None
    aucs = np.asarray(aucs)
    ginis = 2.0 * aucs - 1.0
    return {
        "n_folds": int(len(aucs)),
        "mean_auc": round(float(aucs.mean()), 4),
        "std_auc": round(float(aucs.std(ddof=1)), 4),
        "min_auc": round(float(aucs.min()), 4),
        "max_auc": round(float(aucs.max()), 4),
        "mean_gini": round(float(ginis.mean()), 4),
        "std_gini": round(float(ginis.std(ddof=1)), 4),
        "fold_aucs": [round(float(a), 4) for a in aucs],
        "avg_test_rows": int(np.mean(n_test)),
    }


# ── XGBoost streaming callback ────────────────────────────────────────────────────

def _build_callback(xgb, state: _RunState, emit):
    """A TrainingCallback that streams per-round metrics and honours the kill-switch."""
    class _StreamCB(xgb.callback.TrainingCallback):
        def after_iteration(self, model, epoch, evals_log) -> bool:
            state.iteration = epoch + 1

            def _last(split, metric):
                try:
                    return float(evals_log[split][metric][-1])
                except Exception:
                    return None

            auc = _last("valid", "auc")
            emit({
                "event": "epoch",
                "iteration": epoch + 1,
                "train_logloss": _last("train", "logloss"),
                "valid_logloss": _last("valid", "logloss"),
                "valid_auc": auc,
                "gini": (2.0 * auc - 1.0) if auc is not None else None,
                "elapsed": round(time.time() - state.created_at, 2),
            })
            # Returning True tells XGBoost to stop *after* this round — the booster
            # retains everything trained so far (clean partial-model preservation).
            return state.cancel.is_set()

    return _StreamCB()


def _final_metrics(xgb, booster, dvalid, y_valid: np.ndarray) -> dict:
    from sklearn.metrics import roc_auc_score, log_loss, accuracy_score
    proba = booster.predict(dvalid)
    pred = (proba >= 0.5).astype(int)
    out: dict = {"n_valid": int(len(y_valid))}
    try:
        auc = float(roc_auc_score(y_valid, proba)) if len(np.unique(y_valid)) > 1 else None
    except Exception:
        auc = None
    out["valid_auc"] = round(auc, 4) if auc is not None else None
    out["gini"] = round(2 * auc - 1, 4) if auc is not None else None
    try:
        out["valid_logloss"] = round(float(log_loss(y_valid, proba, labels=[0, 1])), 4)
    except Exception:
        out["valid_logloss"] = None
    out["accuracy"] = round(float(accuracy_score(y_valid, pred)), 4)
    # Confusion counts for the cockpit
    out["confusion"] = {
        "tp": int(((pred == 1) & (y_valid == 1)).sum()),
        "fp": int(((pred == 1) & (y_valid == 0)).sum()),
        "tn": int(((pred == 0) & (y_valid == 0)).sum()),
        "fn": int(((pred == 0) & (y_valid == 1)).sum()),
    }
    return out


def _train_meta_model(xgb, X_train, y_train, p_train, X_valid, y_valid, p_valid,
                      params: dict, rounds: int, feats: list[str]):
    """Meta-labeling (López de Prado, AFML ch. 3). The *primary* model decides the side
    (predicts 1 = up); the *meta* model decides whether to ACT on the primary's positive
    calls — its target is meta_label = 1{the primary's up-call was correct}. This lifts
    the precision / bet-sizing of the entries without touching the primary's recall.
    Returns a metrics block, or None when there is too little signal to fit a meta-model.
    """
    from sklearn.metrics import roc_auc_score
    m_tr = p_train >= 0.5                      # primary says "up" on the training rows
    m_va = p_valid >= 0.5
    if int(m_tr.sum()) < 50 or int(m_va.sum()) < 20:
        return None
    meta_y_tr = (y_train[m_tr] == 1).astype(int)
    if len(np.unique(meta_y_tr)) < 2:
        return None
    mp = dict(params)
    pos = float(meta_y_tr.sum()); neg = float(len(meta_y_tr) - pos)
    mp["scale_pos_weight"] = (neg / pos) if pos > 0 else 1.0
    meta = xgb.train(mp, xgb.DMatrix(X_train[m_tr], label=meta_y_tr, feature_names=feats),
                     num_boost_round=min(int(rounds), 150), verbose_eval=False)
    meta_y_va = (y_valid[m_va] == 1).astype(int)
    proba = meta.predict(xgb.DMatrix(X_valid[m_va], feature_names=feats))
    try:
        auc = float(roc_auc_score(meta_y_va, proba)) if len(np.unique(meta_y_va)) > 1 else None
    except Exception:
        auc = None
    base_prec = float(meta_y_va.mean())                       # precision of taking ALL primary up-calls
    take = proba >= 0.5
    meta_prec = float(meta_y_va[take].mean()) if take.any() else 0.0   # precision when the meta says act
    return {
        "meta_valid_auc": round(auc, 4) if auc is not None else None,
        "base_precision": round(base_prec, 4),
        "meta_precision": round(meta_prec, 4),
        "precision_lift": round(meta_prec - base_prec, 4),
        "n_meta_train": int(m_tr.sum()), "n_meta_valid": int(m_va.sum()),
        "n_meta_acted": int(take.sum()),
    }


# ── Core training routine (runs in a worker thread) ───────────────────────────────

def _run_training(req: TrainRequest, state: _RunState, emit) -> dict:
    try:
        import xgboost as xgb
    except Exception as e:  # pragma: no cover - dependency guard
        raise HTTPException(status_code=503, detail=f"xgboost unavailable in ui-api image: {e}")

    df, feats = _load_training_frame(req)

    # Chronological split — no shuffle, split on a DATE boundary so no single date
    # straddles both folds. A *purge gap* (horizon + embargo trading days) is removed
    # ahead of the validation start so no training label's forward window leaks into
    # the validation period (overlapping-label leakage; CLAUDE.md temporal purity).
    n = len(df)
    udates = np.sort(df["date"].unique())
    split_date, purge_date, cut_i, purge_i = _purged_split(
        udates, req.valid_fraction, req.label_horizon, req.embargo_days)
    train_df = df[df["date"] < purge_date]
    valid_df = df[df["date"] >= split_date]
    purged = int(((df["date"] >= purge_date) & (df["date"] < split_date)).sum())
    purge_applied = True
    if train_df.empty or valid_df.empty:  # purge starved a fold → fall back to plain seam
        train_df = df[df["date"] < split_date]
        valid_df = df[df["date"] >= split_date]
        purged, purge_applied = 0, False
    if train_df.empty or valid_df.empty:  # tiny-window fallback → row split
        vf = min(max(req.valid_fraction, 0.05), 0.5)
        split = max(1, min(int(n * (1 - vf)), n - 1))
        train_df, valid_df = df.iloc[:split], df.iloc[split:]
        purged, purge_applied = 0, False
    X_train, y_train = train_df[feats].to_numpy(dtype=float), train_df["y"].to_numpy(dtype=int)
    X_valid, y_valid = valid_df[feats].to_numpy(dtype=float), valid_df["y"].to_numpy(dtype=int)

    # Optional exponential time-decay sample weights (recent regimes weigh more).
    # Strictly point-in-time: age is measured back from each train row's own date.
    w_train = None
    hl = int(req.weight_halflife_days)
    if hl > 0 and len(train_df):
        ref = train_df["date"].max()
        age_days = (ref - train_df["date"]).dt.days.to_numpy(dtype=float)
        w_train = np.power(0.5, age_days / float(hl))

    rounds = int(req.n_estimators)
    if req.mode == "sample":
        rounds = min(rounds, 80)  # lightweight health-check
    state.total_rounds = rounds

    up_rate = float(np.mean(df["y"])) if n else 0.0
    emit({
        "event": "start", "run_id": state.run_id, "mode": req.mode,
        "n_samples": int(n), "n_train": int(len(train_df)), "n_valid": int(len(valid_df)),
        "n_features": len(feats), "features": feats,
        "up_rate": round(up_rate, 4), "total_rounds": rounds,
        "train_span": [str(train_df["date"].min().date()), str(train_df["date"].max().date())],
        "valid_span": [str(valid_df["date"].min().date()), str(valid_df["date"].max().date())],
        # Leakage-control telemetry: how many rows the purge removed at the seam.
        "purge_applied": purge_applied,
        "purged_rows": purged,
        "purge_gap_days": int(req.label_horizon) + int(req.embargo_days),
        "weight_decay_halflife": hl,
        "label_kind": req.label_kind,
        "meta_labeling_enabled": bool(getattr(req, "meta_labeling", False)),
    })

    dtrain = xgb.DMatrix(X_train, label=y_train, weight=w_train, feature_names=feats)
    dvalid = xgb.DMatrix(X_valid, label=y_valid, feature_names=feats)

    # Class imbalance correction so AUC/Gini aren't dominated by the majority class.
    pos = float(y_train.sum()); neg = float(len(y_train) - pos)
    spw = (neg / pos) if pos > 0 else 1.0
    params = {
        "objective": "binary:logistic",
        "eval_metric": ["logloss", "auc"],
        "tree_method": "hist",
        "max_depth": int(req.max_depth),
        "eta": float(req.learning_rate),
        "subsample": float(req.subsample),
        "colsample_bytree": float(req.colsample_bytree),
        "scale_pos_weight": spw,
        "seed": 42,
    }

    booster = xgb.train(
        params, dtrain, num_boost_round=rounds,
        evals=[(dtrain, "train"), (dvalid, "valid")],
        callbacks=[_build_callback(xgb, state, emit)],
        verbose_eval=False,
    )

    terminated = state.cancel.is_set()
    state.status = "TERMINATED_BY_USER" if terminated else "COMPLETED"

    metrics = _final_metrics(xgb, booster, dvalid, y_valid)

    # Meta-labeling (G7): secondary model on whether the primary's up-calls are correct.
    meta = None
    if getattr(req, "meta_labeling", False) and not terminated:
        try:
            meta = _train_meta_model(xgb, X_train, y_train, booster.predict(dtrain),
                                     X_valid, y_valid, booster.predict(dvalid),
                                     params, rounds, feats)
        except Exception:
            meta = None

    # Purged K-Fold robust eval (G8): a distribution of OOS AUC, not one point estimate.
    robust = None
    if getattr(req, "robust_eval", False) and not terminated:
        try:
            robust = _robust_purged_eval(xgb, df, feats, params, rounds,
                                         int(req.robust_folds), int(req.label_horizon) + int(req.embargo_days))
        except Exception:
            robust = None

    score = booster.get_score(importance_type="gain")
    importance = sorted(
        ({"feature": k, "gain": round(float(v), 2)} for k, v in score.items()),
        key=lambda d: d["gain"], reverse=True,
    )[:20]

    # Preserve the (partial-or-full) model on disk so a kill-switch never loses work.
    model_path = None
    try:
        os.makedirs(MODEL_DIR, exist_ok=True)
        model_path = os.path.join(MODEL_DIR, f"{state.run_id}.json")
        booster.save_model(model_path)
    except Exception:
        model_path = None

    return {
        "event": "result",
        "run_id": state.run_id,
        "status": state.status,
        "mode": req.mode,
        "rounds_completed": state.iteration,
        "rounds_requested": rounds,
        "up_rate": round(up_rate, 4),
        "model_path": model_path,
        "feature_importance": importance,
        "purge_applied": purge_applied,
        "purged_rows": purged,
        "purge_gap_days": int(req.label_horizon) + int(req.embargo_days),
        "weight_decay_halflife": hl,
        "label_kind": req.label_kind,
        "meta_labeling": meta,
        "robust_eval": robust,
        **metrics,
        "mode_flag": MODE,
    }


def _stream(req: TrainRequest):
    # Bounded queue (G11): epoch telemetry is loss-tolerant, so a slow/stalled client
    # cannot accumulate unbounded epoch frames in memory. Critical frames (start /
    # result / error / accepted) always block-put and are never dropped.
    q: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
    state = _register(int(req.n_estimators))

    def emit(evt: dict):
        if evt.get("event") == "epoch":
            try:
                q.put_nowait(evt)               # drop this telemetry frame if the queue is full
            except queue.Full:
                pass
        else:
            q.put(evt)                          # start/result/error must not be lost

    def worker():
        try:
            result = _run_training(req, state, emit)
            q.put(result)
        except HTTPException as he:
            state.status = "ERROR"
            q.put({"event": "error", "run_id": state.run_id, "detail": str(he.detail)})
        except Exception as e:  # pragma: no cover
            import traceback
            traceback.print_exc()
            state.status = "ERROR"
            q.put({"event": "error", "run_id": state.run_id, "detail": str(e)})
        finally:
            q.put({"event": "__done__"})

    threading.Thread(target=worker, daemon=True, name=f"mltrain-{state.run_id}").start()

    def generate():
        # Hand the client its run_id immediately so STOP works before round 1.
        yield json.dumps({"event": "accepted", "run_id": state.run_id, "mode": req.mode}) + "\n"
        try:
            while True:
                evt = q.get()
                if evt.get("event") == "__done__":
                    break
                yield json.dumps(evt, default=str) + "\n"
        finally:
            # Client disconnect / stream close before completion → signal the worker to
            # stop at the next round boundary so an abandoned run frees xgboost memory
            # promptly instead of training to completion in the background (G11).
            if state.status == "TRAINING":
                state.cancel.set()

    return generate


# ── Endpoints ─────────────────────────────────────────────────────────────────────

@router.post("/train/stream")
async def train_stream(req: TrainRequest):
    """Start a training run and stream NDJSON telemetry (accepted → start → epoch* → result)."""
    if req.mode not in ("sample", "production"):
        raise HTTPException(status_code=400, detail="mode must be 'sample' or 'production'")
    return StreamingResponse(_stream(req)(), media_type="application/x-ndjson")


@router.post("/stop")
async def stop_run(req: StopRequest):
    """Kill-switch: signal the run to stop at the next round boundary (model preserved)."""
    with _RUNS_LOCK:
        st = _RUNS.get(req.run_id)
    if not st:
        raise HTTPException(status_code=404, detail=f"Unknown run_id {req.run_id}")
    st.cancel.set()
    return {"run_id": req.run_id, "status": "STOP_SIGNALLED", "iteration": st.iteration}


# (dead routes /runs and /health removed — Bloomberg program F1.5; ui-api /health is the
#  service health endpoint, and run state is returned by /train + /stop responses)
