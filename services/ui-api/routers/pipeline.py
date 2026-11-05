"""Pipeline: feature generation, model training, and orchestration."""
import os
import sys
import uuid
import asyncio
import subprocess
import json
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator

import httpx
import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from errors import degraded
from routers import _features_explorer
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
router = APIRouter()

FEATURE_SVC = os.getenv("FEATURE_SERVICE_URL", "http://feature-service:8002")
ML_SVC      = os.getenv("ML_SERVICE_URL",      "http://ml-service:8003")
RL_SVC      = os.getenv("RL_SERVICE_URL",       "http://rl-service:8004")
DATA_SVC    = os.getenv("DATA_SERVICE_URL",     "http://data-service:8001")
# Parquet cache paths written by pipeline feature generation.
# Derive the data dir from the configured DB path (DUCKDB_PATH/DATABASE_URL) so it
# resolves to /app/data in Docker. The parent-walk from __file__ is correct in local
# dev (services/ui-api/routers/pipeline.py -> <project>/data) but WRONG in the
# container, where pipeline.py lives at /app/routers/ -> resolves to /data (which
# does not exist) -> training falsely reported "No features found".
_DB_PATH_ENV      = os.getenv("DUCKDB_PATH") or os.getenv("DATABASE_URL")
DATA_DIR          = (Path(_DB_PATH_ENV).resolve().parent if _DB_PATH_ENV
                     else Path(__file__).resolve().parent.parent.parent.parent / "data")
FEATURES_PARQUET  = DATA_DIR / "computed_features.parquet"
RL_METRICS_PATH   = DATA_DIR / "rl_training_metrics.json"
LABELS_PARQUET    = DATA_DIR / "computed_labels.parquet"

_jobs: dict[str, dict] = {}
_train_log_queues: dict[str, queue.Queue] = {}

# ── feature_engine import (local dev: direct; Docker: sys.path from shared mount) ──
_FE_PATH = str(Path(__file__).resolve().parents[2] / "feature-service")
if _FE_PATH not in sys.path:
    sys.path.insert(0, _FE_PATH)
try:
    from feature_engine import (
        build_ticker_features,
        compute_macro_features,
        compute_market_breadth,
        build_triple_barrier_labels,
        FEATURE_COLS as _ENGINE_FEATURE_COLS,
        DEFAULT_TRAIN_FEATURES as _DEFAULT_TRAIN_FEATURES,
    )
    _FEATURE_ENGINE_AVAILABLE = True
except ImportError:
    _FEATURE_ENGINE_AVAILABLE = False
    _ENGINE_FEATURE_COLS = []
    _DEFAULT_TRAIN_FEATURES = []

# Columns that come from ml_labels (computed from FUTURE prices) or are metadata.
# They must never be used as model inputs.
_LABEL_AND_META_COLS = {
    "ticker", "date", "created_at", "feature_version", "stock_id",
    "label_direction", "label_return_pct", "label_barrier", "label_return",
    "fwd_return", "target", "horizon_days", "profit_target_pct", "stop_loss_pct",
    "cost_hurdle_pct",
}


def _get_or_create_queue(job_id: str) -> queue.Queue:
    if job_id not in _train_log_queues:
        _train_log_queues[job_id] = queue.Queue(maxsize=500)
    return _train_log_queues[job_id]


def _emit(job_id: str, msg: str, event: str = "log") -> None:
    q = _train_log_queues.get(job_id)
    if q:
        try:
            q.put_nowait(f"event: {event}\ndata: {json.dumps({'msg': msg, 'ts': datetime.now().astimezone().isoformat()})}\n\n")
        except queue.Full:
            pass


def _safe_queue_get(q: queue.Queue, timeout: float = 2.0) -> str | None:
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


# Use expanded feature set from engine when available; fall back to legacy list
FEATURE_COLS = _ENGINE_FEATURE_COLS if _FEATURE_ENGINE_AVAILABLE else [
    "sma_ratio_20_50", "price_vs_sma20", "price_vs_sma50",
    "macd", "macd_signal", "macd_hist", "uptrend_20_50", "uptrend_50_200",
    "rsi_14", "rsi_28", "rsi_7", "stoch_k", "stoch_d",
    "roc_5", "roc_10", "roc_20", "williams_r",
    "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
    "is_green_candle",
    "bb_width", "atr_14_pct",
    "high_low_ratio", "close_position", "gap_pct",
    "volume_ratio", "mfi_14", "cmf_20",
    "day_of_week", "month",
]


class ServiceHealth(BaseModel):
    service: str
    status: str
    model_loaded: Optional[bool] = None
    message: str = ""


class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: int = 0
    total: int = 0
    elapsed_secs: float = 0.0
    errors_count: int = 0


class FeatureImportanceItem(BaseModel):
    feature: str
    importance: float
    rank: int


class ModelMetrics(BaseModel):
    accuracy: float = 0.0
    f1_score: float = 0.0
    log_loss: float = 0.0
    auc_roc: float = 0.0
    model_version: str = "untrained"


async def _ping_service(url: str, timeout: int = 5) -> tuple[str, Optional[dict]]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{url}/health")
            if resp.status_code == 200:
                return "LIVE", resp.json()
            return "DOWN", None
    except Exception:
        return "DOWN", None


@router.get("/service-health", response_model=dict[str, ServiceHealth])
async def get_service_health():
    services = [
        ("data-service",    DATA_SVC),
        ("feature-service", FEATURE_SVC),
        ("ml-service",      ML_SVC),
        ("rl-service",      RL_SVC),
    ]
    health = {}
    for name, url in services:
        status, data = await _ping_service(url)
        health[name] = ServiceHealth(
            service=name,
            status=status,
            model_loaded=data.get("model_loaded") if data else None,
            message=data.get("message", "") if data else ""
        )
    return health


# ── Feature generation: ONE pipeline, owned by data-service ─────────────────────
# The dataset (ml_features + ml_labels) is built by data-service's
# POST /jobs/build-ml-dataset — the only process allowed to write DuckDB. ui-api
# just starts that job and relays its progress; it no longer computes features
# in-process (which blocked this event loop and raced the parquet import).

_REMOTE_STATUS = {"running": "computing_features", "done": "done", "error": "error"}


@router.post("/generate-features")
async def trigger_feature_generation():
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{DATA_SVC}/jobs/build-ml-dataset")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}")
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", r.text[:300]))
    remote = r.json()
    job_id = remote["job_id"]
    _jobs[job_id] = {
        "status": "loading_data",
        "progress": 0,
        "total": 0,
        "errors": [],
        "start_time": datetime.now(),
        "engine": "data-service",
        "remote_job_id": job_id,
    }
    return {
        "job_id": job_id,
        "status": "loading_data",
        "progress": 0,
        "total": remote.get("total", 0),
        "engine": "data-service",
        "feature_count": len(FEATURE_COLS),
        "already_running": remote.get("already_running", False),
    }


async def _sync_remote_job(job_id: str) -> None:
    job = _jobs[job_id]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{DATA_SVC}/jobs/{job['remote_job_id']}")
        if r.status_code != 200:
            return
        remote = r.json()
    except Exception:
        return  # transient — keep last known state
    job["status"] = _REMOTE_STATUS.get(remote.get("status"), remote.get("status", "running"))
    job["progress"] = remote.get("progress", 0)
    job["total"] = remote.get("total", 0)
    if remote.get("error"):
        job["errors"] = [{"general": remote["error"]}]
    if remote.get("status") in ("done", "error"):
        job["result"] = remote.get("result")
        job["elapsed_secs"] = (datetime.now() - job["start_time"]).total_seconds()
        job.pop("start_time", None)


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if _jobs[job_id].get("remote_job_id") and _jobs[job_id]["status"] not in ("done", "error"):
        await _sync_remote_job(job_id)
    job = _jobs[job_id]
    elapsed = job.get("elapsed_secs", 0.0)
    if "start_time" in job and isinstance(job["start_time"], datetime):
        elapsed = (datetime.now() - job["start_time"]).total_seconds()

    return JobStatus(
        job_id=job_id,
        status=job["status"],
        progress=job.get("progress", 0),
        total=job.get("total", 0),
        elapsed_secs=elapsed,
        errors_count=len(job.get("errors", []))
    )


async def _run_model_training(job_id: str, model_type: str = "xgboost", selected_features: list | None = None):
    """Train via ml-service from the SINGLE SOURCE — DuckDB ml_features + ml_labels.

    Pulls a memory-safe training sample from data-service /db/training-sample (DuckDB
    performs the join + last-N-per-ticker windowing server-side) instead of loading the
    full ~426 MB feature parquet + labels + merge into the 2 GB ui-api container — which
    OOM-killed it exactly like feature generation did before the streaming fix."""
    import pandas as pd
    import math

    try:
        _jobs[job_id]["status"] = "loading_data"
        async with httpx.AsyncClient(timeout=300) as client:
            # stride=5 (= label horizon): non-overlapping labels across the FULL
            # history, date-ordered — not just the most recent 200 days.
            r = await client.get(f"{DATA_SVC}/db/training-sample", params={"stride": 5})
            if r.status_code != 200:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = f"training-sample HTTP {r.status_code}: {r.text[:300]}"
                return
            merged = pd.DataFrame(r.json().get("data", []))

        if len(merged) < 500:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = (f"Only {len(merged)} joined rows in ml_features/ml_labels — "
                                      "run Phase 3 (Feature Engineering) first.")
            return

        # Encode nifty_regime categorical → integer (bull=1, bear=-1, range=0)
        if "nifty_regime" in merged.columns:
            regime_map = {"bull": 1, "range": 0, "bear": -1}
            merged["nifty_regime"] = merged["nifty_regime"].map(regime_map).fillna(0).astype(int)

        # Valid feature columns present in merged df (only numeric)
        feature_pool = selected_features if selected_features else (_DEFAULT_TRAIN_FEATURES or FEATURE_COLS)
        valid_cols = [c for c in feature_pool if c in merged.columns
                      and c not in _LABEL_AND_META_COLS
                      and merged[c].dtype.kind in "fiub"      # float/int/uint/bool only
                      and merged[c].notna().any()]            # all-NULL columns drop every row

        _jobs[job_id]["status"] = "training"
        _jobs[job_id]["progress"] = 20

        # Build payload — replace NaN/inf with None for JSON serialization
        train_cols = valid_cols + ["ticker", "date", "label_direction", "label_return_pct"]
        payload_df = merged[[c for c in train_cols if c in merged.columns]].copy()

        # Cast label columns to plain Python types (avoids numpy dtype serialization errors)
        payload_df["label_direction"] = payload_df["label_direction"].astype(float)
        payload_df["label_return_pct"] = payload_df["label_return_pct"].astype(float)

        # Replace NaN / inf with None so json.dumps() doesn't produce invalid tokens
        import math
        def _clean(v):
            if v is None:
                return None
            try:
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return None
            except Exception:
                pass
            return v

        records = payload_df.to_dict(orient="records")
        records = [{k: _clean(val) for k, val in row.items()} for row in records]

        present_feat_cols = [c for c in valid_cols if c in payload_df.columns]
        payload = {
            "features": records,
            "feature_cols": present_feat_cols,
            "target_direction": "label_direction",
            "target_return": "label_return_pct",
            "date_col": "date",
            "run_walk_forward": False,
            "save_models": True,
            "model_type": model_type,
        }

        _jobs[job_id]["progress"] = 30
        _jobs[job_id]["total_rows"] = len(records)

        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(f"{ML_SVC}/train", json=payload)

        _jobs[job_id]["progress"] = 100
        if resp.status_code in [200, 202]:
            _jobs[job_id]["status"] = "done"
            try:
                _jobs[job_id]["result"] = resp.json()
            except Exception:
                pass
        else:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = f"ml-service returned {resp.status_code}: {resp.text[:500]}"

    except Exception as e:
        import traceback
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}"


class TrainModelRequest(BaseModel):
    model_type: str = "xgboost"
    selected_features: Optional[list[str]] = None
    make_active: bool = True


@router.post("/train-model")
async def trigger_model_training(background_tasks: BackgroundTasks, req: Optional[TrainModelRequest] = None):
    job_id = str(uuid.uuid4())

    _jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": 100,
        "errors": [],
        "start_time": datetime.now(),
    }

    background_tasks.add_task(
        _run_model_training, job_id,
        req.model_type if req else "xgboost",
        req.selected_features if req else None,
    )
    return {"job_id": job_id, "status": "running", "progress": 0, "total": 100}


@router.get("/data-quality")
async def get_data_quality():
    """Return training data quality metrics via data-service HTTP (avoids DuckDB lock conflicts)."""
    import pandas as pd

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            db_stats_resp  = await client.get(f"{DATA_SVC}/db/stats")
            # fields=core (payload budget S2): this page needs 3 of the 19 per-ticker
            # fields; today's data-service ignores the param, the patched one trims.
            ohlcv_meta_resp = await client.get(f"{DATA_SVC}/db/ohlcv-meta", params={"fields": "core"})
            ml_stats_resp   = await client.get(f"{DATA_SVC}/db/ml-stats")

        db_stats   = db_stats_resp.json()   if db_stats_resp.status_code   == 200 else {}
        ohlcv_meta = ohlcv_meta_resp.json() if ohlcv_meta_resp.status_code == 200 else {}
        ml_stats   = ml_stats_resp.json()   if ml_stats_resp.status_code   == 200 else {}

        # ── OHLCV stats from ohlcv-meta ──────────────────────────────────────────
        meta_rows = ohlcv_meta.get("data", [])
        total_tickers = len(meta_rows)
        total_candles = sum(r.get("total_rows", 0) for r in meta_rows)
        all_dates = [r.get("latest_date") or r.get("last_date") for r in meta_rows]
        all_dates = [d for d in all_dates if d]
        min_date  = min(all_dates) if all_dates else "—"
        max_date  = max(all_dates) if all_dates else "—"

        candle_buckets = {"<500": 0, "500-1000": 0, "1000-1500": 0, ">1500": 0}
        for r in meta_rows:
            cnt = r.get("total_rows", 0)
            if cnt < 500:        candle_buckets["<500"] += 1
            elif cnt < 1000:     candle_buckets["500-1000"] += 1
            elif cnt < 1500:     candle_buckets["1000-1500"] += 1
            else:                candle_buckets[">1500"] += 1

        stale = sorted(meta_rows, key=lambda r: r.get("latest_date") or r.get("last_date") or "")[:10]
        stale_tickers = [{"ticker": r["ticker"], "last_date": r.get("latest_date") or r.get("last_date", "")} for r in stale]

        # ── Feature stats — prefer ml-stats from DB, fall back to Parquet ────────
        feat_ml = ml_stats.get("features", {})
        feat_tickers = feat_ml.get("tickers", 0)
        feat_rows    = feat_ml.get("rows", 0)
        sparse_tickers = 0
        avg_rows_per_ticker = round(feat_rows / feat_tickers, 0) if feat_tickers else 0.0

        if feat_rows == 0 and FEATURES_PARQUET.exists():
            # F2.2: the 352 MB parquet read must never run on the event loop; only counts are
            # needed, so project a single column and do it in a worker thread.
            def _feat_stats():
                df = pd.read_parquet(str(FEATURES_PARQUET), columns=["ticker"])
                per = df.groupby("ticker").size()
                return len(per), len(df), int((per < 100).sum()), (round(float(per.mean()), 0) if len(per) else 0)
            try:
                (feat_tickers, feat_rows,
                 sparse_tickers, avg_rows_per_ticker) = await asyncio.to_thread(_feat_stats)
            except Exception:
                pass

        # ── Label stats — prefer ml-stats from DB, fall back to Parquet ──────────
        lbl_ml = ml_stats.get("labels", {})
        total_labels      = lbl_ml.get("rows", 0)
        up_labels         = lbl_ml.get("up_labels", 0)
        down_labels       = lbl_ml.get("down_labels", 0)
        class_balance_pct = lbl_ml.get("class_balance_pct", 0.0)
        avg_ret           = lbl_ml.get("avg_return_pct", 0.0)
        std_ret           = lbl_ml.get("std_return_pct", 0.0)
        has_triple_barrier = total_labels > 0  # ml_labels only populated via triple-barrier labels

        if total_labels == 0 and LABELS_PARQUET.exists():
            def _label_stats():
                import pyarrow.parquet as pq
                cols = pq.read_schema(str(LABELS_PARQUET)).names
                df = pd.read_parquet(str(LABELS_PARQUET), columns=["label_direction", "label_return_pct"])
                n = len(df)
                up = int((df["label_direction"] == 1).sum())
                return (n, up, int((df["label_direction"] == 0).sum()),
                        round(up / n * 100, 1) if n else 0,
                        round(float(df["label_return_pct"].mean()), 4),
                        round(float(df["label_return_pct"].std()), 4),
                        "label_barrier" in cols)
            try:
                (total_labels, up_labels, down_labels, class_balance_pct,
                 avg_ret, std_ret, has_triple_barrier) = await asyncio.to_thread(_label_stats)
            except Exception:
                pass

        return {
            "ohlcv": {
                "total_tickers": total_tickers,
                "total_candles": total_candles,
                "min_date": min_date,
                "max_date": max_date,
                "avg_candles_per_ticker": round(total_candles / total_tickers, 0) if total_tickers else 0,
                "candle_distribution": [{"bucket": k, "count": v} for k, v in candle_buckets.items()],
                "stale_tickers": stale_tickers,
            },
            "features": {
                "tickers_processed": feat_tickers,
                "total_rows": feat_rows,
                "coverage_pct": round(feat_tickers / total_tickers * 100, 1) if total_tickers else 0,
                "sparse_tickers": sparse_tickers,
                "avg_rows_per_ticker": avg_rows_per_ticker,
                "feature_count": len(FEATURE_COLS),
                "engine": "feature_engine_v2" if _FEATURE_ENGINE_AVAILABLE else "legacy",
            },
            "labels": {
                "total_labels": total_labels,
                "up_labels": up_labels,
                "down_labels": down_labels,
                "class_balance_pct": class_balance_pct,
                "avg_return_pct": avg_ret,
                "std_return_pct": std_ret,
                "triple_barrier": has_triple_barrier,
            },
            "readiness": {
                "has_ohlcv":         total_candles > 0,
                "has_features":      feat_rows > 0,
                "has_labels":        total_labels > 0,
                "ready_to_train":    feat_rows >= 500 and total_labels >= 500,
                "feature_col_count": len(FEATURE_COLS),
                "feature_engine":    "v2_direct" if _FEATURE_ENGINE_AVAILABLE else "v1_http",
            }
        }

    except Exception as e:
        return degraded({"error": str(e)}, "internal", str(e))


# ── Model Investigation Endpoints (proxy ml-service + compute from Parquet) ────

@router.get("/confusion-matrix")
async def get_confusion_matrix():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/confusion-matrix")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    raise HTTPException(status_code=503, detail="Train model first")


@router.get("/roc-curve")
async def get_roc_curve():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/roc-curve")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    raise HTTPException(status_code=503, detail="Train model first")


@router.get("/score-distribution")
async def get_score_distribution():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/score-distribution")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    raise HTTPException(status_code=503, detail="Train model first")


@router.get("/calibration")
async def get_calibration():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/calibration")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    raise HTTPException(status_code=503, detail="Train model first")


@router.get("/model-params")
async def get_model_params():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/model-params")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    raise HTTPException(status_code=503, detail="No model loaded")


@router.post("/shap-global")
async def get_shap_global():
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{ML_SVC}/shap-global")
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/pdp")
async def get_pdp(feature: str):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{ML_SVC}/pdp", params={"feature": feature})
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# The Inspector opens several panels at once and each used to pull its own ~170 MB
# JSON sample. The sample only changes when the dataset is rebuilt, so keep one copy
# per dataset version (ml-stats row count + latest date) and fetch it single-flight.
_SAMPLE_TTL_S = 900.0
_sample_lock = asyncio.Lock()
_sample_cache: dict = {"key": None, "at": 0.0, "df": None}


async def _feature_sample_df(n: int = 80000):
    """SINGLE-SOURCE feature sample (ml_features ⋈ ml_labels) from data-service — the
    same canonical DuckDB store the gauges, training and prediction read. The Inspector
    no longer reads the parquet directly, so every panel agrees by construction."""
    import time as _t

    async with httpx.AsyncClient(timeout=30) as client:
        stats = (await client.get(f"{DATA_SVC}/db/ml-stats")).json().get("features", {})
    key = (stats.get("rows"), stats.get("latest_date"), n)
    async with _sample_lock:
        if (_sample_cache["key"] == key and _sample_cache["df"] is not None
                and _t.monotonic() - _sample_cache["at"] < _SAMPLE_TTL_S):
            return _sample_cache["df"].copy()
        df = await _fetch_feature_sample(n)
        _sample_cache.update(key=key, at=_t.monotonic(), df=df)
        return df.copy()


async def _fetch_feature_sample(n: int):
    import pandas as pd
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(f"{DATA_SVC}/db/feature-sample", params={"n": n})
        r.raise_for_status()
        df = await asyncio.to_thread(lambda: pd.DataFrame(r.json().get("data", [])))
    # nifty_regime is stored as text (bull/range/bear); numeric panels need a number.
    if "nifty_regime" in df.columns and not pd.api.types.is_numeric_dtype(df["nifty_regime"]):
        df["nifty_regime"] = df["nifty_regime"].map({"bull": 1, "range": 0, "bear": -1}).astype("float64")
    return df


@router.get("/feature-stats")
async def get_feature_stats():
    """Univariate statistics for every feature from the canonical ml_features (DuckDB)."""
    import pandas as pd

    merged = await _feature_sample_df()
    if merged.empty:
        raise HTTPException(status_code=404,
                            detail="No features in ml_features — run Phase 3 (Feature Engineering) first")
    # ~70 columns x 80k rows of pandas stats: run off the event loop.
    return {"features": await asyncio.to_thread(_compute_feature_stats, merged)}


def _compute_feature_stats(merged) -> list[dict]:
    import pandas as pd

    result = []
    for col in FEATURE_COLS:
        if col not in merged.columns or not pd.api.types.is_numeric_dtype(merged[col]):
            continue
        s = merged[col]
        s_clean = s.dropna()
        if len(s_clean) < 10:
            continue

        # Point-biserial correlation with binary target using pandas (equivalent to scipy)
        target_corr = 0.0
        if "label_direction" in merged.columns:
            try:
                joined = pd.concat([s, merged["label_direction"]], axis=1).dropna()
                if len(joined) > 10:
                    target_corr = round(float(joined[col].corr(joined["label_direction"])), 4)
            except Exception:
                pass

        result.append({
            "feature": col,
            "mean":     round(float(s_clean.mean()), 4),
            "std":      round(float(s_clean.std()), 4),
            "min":      round(float(s_clean.min()), 4),
            "max":      round(float(s_clean.max()), 4),
            "p25":      round(float(s_clean.quantile(0.25)), 4),
            "p50":      round(float(s_clean.quantile(0.50)), 4),
            "p75":      round(float(s_clean.quantile(0.75)), 4),
            "skew":     round(float(s_clean.skew()), 4),
            "kurtosis": round(float(s_clean.kurtosis()), 4),
            "nan_pct":  round(float(s.isna().mean() * 100), 2),
            "target_corr": target_corr,
        })
    return result


@router.get("/feature-correlations")
async def get_feature_correlations():
    """Pearson correlation matrix for top features (canonical ml_features / DuckDB)."""
    import pandas as pd

    feat_df = await _feature_sample_df()
    if feat_df.empty:
        raise HTTPException(status_code=404, detail="No features in ml_features — run Phase 3 first")
    valid_cols = [c for c in FEATURE_COLS if c in feat_df.columns
                  and pd.api.types.is_numeric_dtype(feat_df[c]) and feat_df[c].notna().any()]
    if len(valid_cols) < 2:
        raise HTTPException(status_code=400, detail="Not enough features")

    def _corr():
        sample = feat_df[valid_cols].dropna(how="all").sample(min(8000, len(feat_df)), random_state=42)
        return sample[valid_cols].corr().round(3).fillna(0).values.tolist()

    return {"features": valid_cols, "matrix": await asyncio.to_thread(_corr)}


@router.get("/feature-distribution")
async def get_feature_distribution(feature: str):
    """Histogram of a feature split by label (UP=1 vs DOWN=0)."""
    import pandas as pd

    if feature not in FEATURE_COLS:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    merged = await _feature_sample_df()
    if merged.empty or feature not in merged.columns:
        raise HTTPException(status_code=404, detail="No feature data — run Phase 3 first")
    merged = merged[["ticker", "date", feature, "label_direction"]].dropna()

    col = merged[feature]
    p1, p99 = float(col.quantile(0.01)), float(col.quantile(0.99))
    bins = np.linspace(p1, p99, 31)
    bin_centers = [(bins[i] + bins[i + 1]) / 2 for i in range(len(bins) - 1)]

    up_data   = merged[merged["label_direction"] == 1][feature].clip(p1, p99)
    down_data = merged[merged["label_direction"] == 0][feature].clip(p1, p99)

    up_counts,   _ = np.histogram(up_data,   bins=bins)
    down_counts, _ = np.histogram(down_data, bins=bins)

    # Normalize to density
    up_total   = float(up_counts.sum())
    down_total = float(down_counts.sum())

    return {
        "feature": feature,
        "bins": [round(float(c), 4) for c in bin_centers],
        "up":   [round(float(c) / up_total * 100, 2) if up_total > 0 else 0 for c in up_counts],
        "down": [round(float(c) / down_total * 100, 2) if down_total > 0 else 0 for c in down_counts],
    }


@router.get("/features-explorer")
async def features_explorer(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=200),
    ticker: Optional[str] = None,
    sort_by: str = Query(default="date"),
    sort_dir: str = Query(default="desc"),
    v: int = Query(default=1, ge=1, le=2),
):
    """Paginated feature grid with data health statistics. `v=2` reads the v2 matrix
    (computed_features_v2.parquet: v1 + carry/momentum/evidence flags + v3 label columns —
    the y_* columns are TRAIN TARGETS, shown here for inspection only).

    Desktop review C2-performance-04: the read is routers/_features_explorer.py, which returns the same
    response as the old whole-file read (kept there as legacy_page and compared in the tests) without
    loading the 352 MB matrix per click: health and sort order are cached per file signature, and only
    the rows of the requested page are decoded."""
    loop = asyncio.get_running_loop()

    v2_path = FEATURES_PARQUET.with_name("computed_features_v2.parquet")
    src = v2_path if v == 2 else FEATURES_PARQUET

    def _read():
        if not src.exists():
            return None, ("No v2 matrix yet — run scripts/build_features_v2.py." if v == 2
                          else "No feature data. Run Phase 3 (Compute Features) first.")
        return _features_explorer.explorer.page(src, page=page, page_size=page_size, ticker=ticker,
                                                sort_by=sort_by, sort_dir=sort_dir, v=v,
                                                feature_cols=FEATURE_COLS), None

    result, error = await loop.run_in_executor(None, _read)
    if error:
        raise HTTPException(status_code=404, detail=error)
    return result


@router.get("/ml-stream/{job_id}")
async def ml_training_stream(job_id: str, request: Request):
    """SSE stream for ML training progress. Connect before triggering /train-config."""
    q = _get_or_create_queue(job_id)

    async def _gen() -> AsyncGenerator[bytes, None]:
        job = _jobs.get(job_id, {})
        yield f"event: status\ndata: {json.dumps({'status': job.get('status', 'pending'), 'progress': job.get('progress', 0)})}\n\n".encode()
        loop = asyncio.get_running_loop()
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            job = _jobs.get(job_id, {})
            if job.get("status") in ("done", "error"):
                yield f"event: done\ndata: {json.dumps({'status': job.get('status'), 'error': job.get('error', '')})}\n\n".encode()
                break
            chunk = await loop.run_in_executor(None, _safe_queue_get, q)
            if chunk:
                idle = 0
                yield chunk.encode()
            else:
                idle += 1
                yield b": heartbeat\n\n"
                if idle > 120:
                    break

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/rl-stream/{job_id}")
async def rl_training_stream(job_id: str, request: Request):
    """SSE stream for RL training progress. Connect before triggering /rl-train."""
    q = _get_or_create_queue(job_id)

    async def _gen() -> AsyncGenerator[bytes, None]:
        job = _jobs.get(job_id, {})
        yield f"event: status\ndata: {json.dumps({'status': job.get('status', 'pending'), 'progress': job.get('progress', 0)})}\n\n".encode()
        loop = asyncio.get_running_loop()
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            job = _jobs.get(job_id, {})
            if job.get("status") in ("done", "error"):
                yield f"event: done\ndata: {json.dumps({'status': job.get('status'), 'error': job.get('error', '')})}\n\n".encode()
                break
            chunk = await loop.run_in_executor(None, _safe_queue_get, q)
            if chunk:
                idle = 0
                yield chunk.encode()
            else:
                idle += 1
                yield b": heartbeat\n\n"
                if idle > 120:
                    break

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/train-config")
async def trigger_training_with_config(background_tasks: BackgroundTasks, config: dict):
    """Trigger model training with custom hyperparameter configuration."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": 100,
        "errors": [],
        "start_time": datetime.now(),
    }
    _get_or_create_queue(job_id)  # pre-register so SSE stream can connect immediately

    rows_per_ticker = int(config.pop("rows_per_ticker", 200))
    run_walk_forward = bool(config.pop("run_walk_forward", False))
    model_type_cfg = str(config.pop("model_type", "xgboost"))
    selected_features_cfg = config.pop("selected_features", None)
    warm_start = bool(config.pop("warm_start", False))
    train_start: Optional[str] = config.pop("train_start", None)
    train_end: Optional[str] = config.pop("train_end", None)
    model_params = config  # remaining keys are model hyperparams

    async def _run():
        import pandas as pd, math

        def _prepare_data():
            """All blocking pandas I/O — runs in thread pool executor."""
            _emit(job_id, "Loading feature & label parquet files…")
            if not FEATURES_PARQUET.exists() or not LABELS_PARQUET.exists():
                return None, "No features found. Run Phase 3 first."
            feat_df = pd.read_parquet(str(FEATURES_PARQUET))
            lbl_df  = pd.read_parquet(str(LABELS_PARQUET))
            feat_df["date"] = feat_df["date"].astype(str).str[:10]
            lbl_df["date"]  = lbl_df["date"].astype(str).str[:10]
            merged = feat_df.merge(lbl_df, on=["ticker", "date"], how="inner")
            merged = merged.dropna(subset=["label_direction", "label_return_pct"])
            if train_start:
                merged = merged[merged["date"] >= train_start]
            if train_end:
                merged = merged[merged["date"] <= train_end]
            _emit(job_id, f"Date window: {merged['date'].min()} → {merged['date'].max()} | {len(merged):,} rows after filter")
            # Feature selection. If the caller passed an explicit `selected_features`
            # list, honor it. Otherwise use EVERY real feature column in the data
            # (not the legacy fixed FEATURE_COLS list) — every numeric column except
            # identifiers, labels, and metadata. All-empty columns are dropped since
            # they carry no signal.
            # Default = the curated scale-free set; label/meta columns are never allowed
            # (label_barrier is computed from future prices — using it is leakage).
            if selected_features_cfg:
                feature_pool = selected_features_cfg
            else:
                feature_pool = _DEFAULT_TRAIN_FEATURES or [
                    c for c in merged.columns if pd.api.types.is_numeric_dtype(merged[c])
                ]
            leaked = [c for c in feature_pool if c in _LABEL_AND_META_COLS]
            if leaked:
                _emit(job_id, f"Dropping label/meta columns from features (leakage guard): {leaked}")
            valid_cols = [c for c in feature_pool if c in merged.columns
                          and c not in _LABEL_AND_META_COLS and merged[c].notna().any()]
            _emit(job_id, f"Feature pool: {len(valid_cols)} usable columns "
                          f"({'custom selection' if selected_features_cfg else 'all available'})")
            # rows_per_ticker rows spread EVENLY over each ticker's full history (spans
            # regimes; spacing > label horizon keeps labels non-overlapping), date-ordered.
            merged = merged.sort_values(["ticker", "date"])
            pos = merged.groupby("ticker").cumcount()
            size = merged.groupby("ticker")["date"].transform("size")
            step = (size / rows_per_ticker).clip(lower=1.0)
            merged = merged[(pos % step.round().astype(int)) == 0]
            merged = merged.sort_values("date").reset_index(drop=True)
            train_cols = valid_cols + ["ticker", "date", "label_direction", "label_return_pct"]
            payload_df = merged[[c for c in train_cols if c in merged.columns]].copy()
            payload_df["label_direction"]  = payload_df["label_direction"].astype(float)
            payload_df["label_return_pct"] = payload_df["label_return_pct"].astype(float)

            def _clean(v):
                if v is None: return None
                try:
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
                except Exception: pass
                return v

            records = [{k: _clean(val) for k, val in row.items()} for row in payload_df.to_dict(orient="records")]
            feature_cols = [c for c in valid_cols if c in payload_df.columns]
            _emit(job_id, f"Built {len(records):,} training samples | {len(feature_cols)} features | {payload_df['ticker'].nunique()} tickers")
            return (records, feature_cols), None

        try:
            loop = asyncio.get_running_loop()
            _emit(job_id, f"Starting ML training — model={model_type_cfg} warm_start={warm_start}")
            result, error = await loop.run_in_executor(None, _prepare_data)

            if error:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = error
                _emit(job_id, f"ERROR: {error}", event="error")
                return

            records, feature_cols = result

            if len(records) < 500:
                msg = f"Only {len(records)} rows — need ≥500. Re-run Phase 3."
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = msg
                _emit(job_id, f"ERROR: {msg}", event="error")
                return

            _jobs[job_id]["progress"] = 30
            _jobs[job_id]["total_rows"] = len(records)
            _emit(job_id, f"Sending {len(records):,} rows to ml-service /train…")

            payload = {
                "features": records,
                "feature_cols": feature_cols,
                "target_direction": "label_direction",
                "target_return": "label_return_pct",
                "date_col": "date",
                "run_walk_forward": run_walk_forward,
                "save_models": True,
                "model_type": model_type_cfg,
                "model_params": model_params if model_params else None,
                "warm_start": warm_start,
            }

            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(f"{ML_SVC}/train", json=payload)

            _jobs[job_id]["progress"] = 100
            if resp.status_code in [200, 202]:
                _jobs[job_id]["status"] = "done"
                result_data = resp.json() if resp.text else {}
                acc = result_data.get("accuracy", result_data.get("metrics", {}).get("accuracy", "—"))
                _emit(job_id, f"Training complete ✓ | accuracy={acc}", event="done")
            else:
                msg = f"ml-service {resp.status_code}: {resp.text[:300]}"
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = msg
                _emit(job_id, f"ERROR: {msg}", event="error")

        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-600:]
            msg = f"{type(e).__name__}: {e}"
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = f"{msg}\n{tb}"
            _emit(job_id, f"ERROR: {msg}", event="error")

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "running", "progress": 0, "total": 100}


@router.get("/feature-importance", response_model=list[FeatureImportanceItem])
async def get_feature_importance():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/feature-importance")
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                return [
                    FeatureImportanceItem(feature=f["name"], importance=f.get("importance", 0.0), rank=i + 1)
                    for i, f in enumerate(features[:20])
                ]
    except Exception:
        pass
    return []


@router.get("/model-metrics", response_model=ModelMetrics)
async def get_model_metrics():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/metrics")
            if resp.status_code == 200:
                data = resp.json()
                return ModelMetrics(
                    accuracy=data.get("accuracy", 0.0),
                    f1_score=data.get("f1_score", 0.0),
                    log_loss=data.get("log_loss", 0.0),
                    auc_roc=data.get("auc_roc", 0.0),
                    model_version=data.get("version", "untrained")
                )
    except Exception:
        pass
    return ModelMetrics()


@router.post("/shap/{ticker}")
async def get_shap_values(ticker: str):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{ML_SVC}/explain", json={"ticker": ticker})
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return degraded({"ticker": ticker, "shap_values": [], "error": "Could not fetch SHAP values"},
                    "state", "Could not fetch SHAP values", hint="Train a model first (ModelLab)")


@router.get("/rl-status")
async def get_rl_status():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{RL_SVC}/health")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {"is_trained": False, "episode_count": 0, "avg_reward": 0.0, "status": "not_initialized"}


@router.post("/rl-train")
async def trigger_rl_training(background_tasks: BackgroundTasks, payload: dict = None):
    job_id = str(uuid.uuid4())
    p = payload or {}
    total_timesteps = int(p.get("total_timesteps", 100_000))
    n_candidates    = int(p.get("n_candidates", 15))
    max_positions   = int(p.get("max_positions", 5))
    # Same data dir as the DB (local: <repo>/data, Docker: /app/data). The hard-coded
    # /app/data path does not exist locally, so the job crashed on its first write.
    metrics_path    = RL_METRICS_PATH
    _get_or_create_queue(job_id)  # pre-register for SSE

    async def _run_rl_training():
        import pandas as pd, math
        _jobs[job_id] = {"status": "running", "start_time": datetime.now(), "progress": 0, "errors": []}
        _emit(job_id, f"RL training started — timesteps={total_timesteps:,} candidates={n_candidates}")

        try:
            # Inside try: any failure (incl. this write) must mark the job as error —
            # otherwise it stays "running" forever and the stream just idles out.
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            metrics_path.write_text(json.dumps({
                "status": "training",
                "last_updated": datetime.now().astimezone().isoformat(),
                "total_timesteps": total_timesteps,
                "metrics": [],
            }))

            # ── Build signals from the SINGLE SOURCE (DuckDB ml_features+ml_labels) ──
            # Memory-safe: data-service does the join + last-N-per-ticker windowing, so
            # we never load the full parquet (the old full read OOM-risked ui-api). Uses
            # REAL feature columns (correct names) and a TRAILING return — no look-ahead.
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.get(f"{DATA_SVC}/db/training-sample", params={"per_ticker": 120})
                r.raise_for_status()
                merged = pd.DataFrame(r.json().get("data", []))
            if merged.empty:
                raise ValueError("No ml_features/ml_labels rows — run Phase 3 (Feature Engineering) first.")
            merged = merged.sort_values("date")

            def _safe(v, d=0.0):
                try:
                    f = float(v)
                    return d if (math.isnan(f) or math.isinf(f)) else f
                except Exception:
                    return d

            def _build_signal(row) -> dict:
                rsi = _safe(row.get("rsi_14"), 50.0)
                # prob_up proxy from real momentum until per-row model scores are wired in
                prob_up = min(max(rsi / 100.0, 0.05), 0.95)
                return {
                    "ticker":               str(row.get("ticker", "")),
                    "date":                 str(row.get("date", "")),
                    "prob_up":              prob_up,
                    "confidence":           abs(prob_up - 0.5) * 2,
                    "expected_return_pct":  _safe(row.get("ret_5d"), 0.0),       # TRAILING 5d return — no look-ahead
                    "rsi_14":               rsi,
                    "bb_pct":               _safe(row.get("bollinger_pctb"), 0.5),
                    "volume_ratio":         _safe(row.get("volume_ratio"), 1.0),
                    "sma_ratio_20_50":      _safe(row.get("sma_ratio_20_50"), 1.0),
                    "hist_vol_20":          _safe(row.get("realized_vol_20d"), 20.0),
                    "sector_id":            0,
                }

            # Group by date to form daily signal batches (list[list[dict]])
            grouped = merged.groupby("date")
            signals_data: list[list[dict]] = []
            for _, grp in grouped:
                day_signals = [_build_signal(r) for r in grp.to_dict(orient="records")]
                if len(day_signals) >= n_candidates:
                    signals_data.append(day_signals)

            if not signals_data:
                raise ValueError("No valid signal batches built from feature data.")

            _n_rows = len(merged)
            del merged  # free the DataFrame before the large JSON serialization to rl-service
            _emit(job_id, f"Built {len(signals_data)} daily signal batches from {_n_rows:,} rows")
            _jobs[job_id]["progress"] = 20

            # ── Call rl-service /train synchronously (runs in background thread) ──
            train_payload = {
                "signals_data": signals_data,
                "total_timesteps": total_timesteps,
            }
            _emit(job_id, f"Sending signal batches to rl-service /train (this may take minutes)…")
            async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0, connect=10.0)) as client:
                resp = await client.post(f"{RL_SVC}/train", json=train_payload)

            if resp.status_code == 200:
                result = resp.json()
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["progress"] = 100
                _emit(job_id, f"RL training complete ✓ | timesteps={result.get('timesteps', total_timesteps):,}", event="done")
                metrics_path.write_text(json.dumps({
                    "status": "done",
                    "last_updated": datetime.now().astimezone().isoformat(),
                    "total_timesteps": result.get("timesteps", total_timesteps),
                    "metrics": [{
                        "episode": total_timesteps,
                        "timestep": total_timesteps,
                        "avg_reward": 0.0,
                        "portfolio_value": 1.0,
                        "sortino_ratio": 0.0,
                        "win_rate": 0.5,
                    }],
                }))
            else:
                raise RuntimeError(f"RL service returned {resp.status_code}: {resp.text[:200]}")

        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
            _emit(job_id, f"ERROR: {e}", event="error")
            metrics_path.write_text(json.dumps({
                "status": "error",
                "error": str(e),
                "last_updated": datetime.now().astimezone().isoformat(),
                "metrics": [],
            }))

    background_tasks.add_task(_run_rl_training)
    return {"job_id": job_id, "status": "queued"}


@router.get("/rl-training-metrics")
def get_rl_training_metrics():              # sync: FastAPI runs it on the worker pool (ASYNC230 blocking open, PLAN 0.8)
    metrics_path = RL_METRICS_PATH
    try:
        with open(metrics_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"status": "not_started", "last_updated": None, "metrics": []}
    except Exception as e:
        return degraded({"status": "error", "error": str(e), "metrics": []}, "internal", str(e))


# ── Model Registry / Catalog Proxy Endpoints ──────────────────────────────────

@router.get("/model-catalog")
async def get_model_catalog():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/catalog")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {}


@router.get("/model-registry")
async def get_model_registry():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{ML_SVC}/registry")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return []


@router.post("/model-registry/{model_id}/activate")
async def activate_registry_model(model_id: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{ML_SVC}/registry/{model_id}/activate")
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/model-registry/{model_id}")
async def delete_registry_model(model_id: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(f"{ML_SVC}/registry/{model_id}")
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/shap-beeswarm")
async def get_shap_beeswarm(n_samples: int = 200, n_features: int = 15):
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{ML_SVC}/shap-beeswarm",
                params={"n_samples": n_samples, "n_features": n_features},
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/shap-waterfall")
async def get_shap_waterfall(sample_idx: int = 0):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{ML_SVC}/shap-waterfall",
                params={"sample_idx": sample_idx},
            )
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
