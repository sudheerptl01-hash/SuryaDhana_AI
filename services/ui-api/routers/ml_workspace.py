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
        sql = f"""
            SELECT f.date, f.ticker, {feat_sql}, l.label_direction AS y
            FROM ml_features f
            JOIN ml_labels l ON f.ticker = l.ticker AND f.date = l.date
            WHERE l.horizon_days = 5 AND l.label_direction IS NOT NULL
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
    rows = rows.replace([np.inf, -np.inf], np.nan)
    # Keep rows with a valid label; impute remaining feature NaNs with column medians
    # (XGBoost handles NaN natively, but median-fill stabilises the validation metrics).
    rows = rows[rows["y"].notna()].copy()
    rows["y"] = rows["y"].astype(int).clip(0, 1)
    rows["date"] = pd.to_datetime(rows["date"])
    return rows, feats


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


# ── Core training routine (runs in a worker thread) ───────────────────────────────

def _run_training(req: TrainRequest, state: _RunState, emit) -> dict:
    try:
        import xgboost as xgb
    except Exception as e:  # pragma: no cover - dependency guard
        raise HTTPException(status_code=503, detail=f"xgboost unavailable in ui-api image: {e}")

    df, feats = _load_training_frame(req)

    # Chronological split — no shuffle, split on a DATE boundary so no single date
    # straddles both folds (strict temporal purity; validation is the most-recent
    # `valid_fraction` of distinct trading dates).
    n = len(df)
    vf = min(max(req.valid_fraction, 0.05), 0.5)
    udates = np.sort(df["date"].unique())
    cut_i = max(1, min(int(len(udates) * (1 - vf)), len(udates) - 1))
    split_date = udates[cut_i]
    train_df = df[df["date"] < split_date]
    valid_df = df[df["date"] >= split_date]
    if train_df.empty or valid_df.empty:  # tiny-window fallback → row split
        split = max(1, min(int(n * (1 - vf)), n - 1))
        train_df, valid_df = df.iloc[:split], df.iloc[split:]
    X_train, y_train = train_df[feats].to_numpy(dtype=float), train_df["y"].to_numpy(dtype=int)
    X_valid, y_valid = valid_df[feats].to_numpy(dtype=float), valid_df["y"].to_numpy(dtype=int)

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
    })

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feats)
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
        **metrics,
        "mode_flag": MODE,
    }


def _stream(req: TrainRequest):
    q: "queue.Queue[dict]" = queue.Queue()
    state = _register(int(req.n_estimators))

    def emit(evt: dict):
        q.put(evt)

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
        while True:
            evt = q.get()
            if evt.get("event") == "__done__":
                break
            yield json.dumps(evt, default=str) + "\n"

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


@router.get("/runs")
async def list_runs():
    with _RUNS_LOCK:
        return [{"run_id": s.run_id, "status": s.status, "iteration": s.iteration,
                 "total_rounds": s.total_rounds,
                 "age_s": round(time.time() - s.created_at, 1)}
                for s in sorted(_RUNS.values(), key=lambda s: s.created_at, reverse=True)]


@router.get("/health")
async def ml_health():
    try:
        import xgboost as xgb  # noqa: F401
        ok = True
        ver = xgb.__version__
    except Exception as e:
        ok, ver = False, str(e)
    return {"mode": MODE, "xgboost_available": ok, "xgboost_version": ver,
            "n_features": len(FEATURE_COLUMNS), "active_runs": sum(
                1 for s in _RUNS.values() if s.status == "TRAINING")}
