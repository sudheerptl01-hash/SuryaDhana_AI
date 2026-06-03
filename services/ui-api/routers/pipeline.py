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
    )
    _FEATURE_ENGINE_AVAILABLE = True
except ImportError:
    _FEATURE_ENGINE_AVAILABLE = False
    _ENGINE_FEATURE_COLS = []


def _get_or_create_queue(job_id: str) -> queue.Queue:
    if job_id not in _train_log_queues:
        _train_log_queues[job_id] = queue.Queue(maxsize=500)
    return _train_log_queues[job_id]


def _emit(job_id: str, msg: str, event: str = "log") -> None:
    q = _train_log_queues.get(job_id)
    if q:
        try:
            q.put_nowait(f"event: {event}\ndata: {json.dumps({'msg': msg, 'ts': datetime.now().isoformat()})}\n\n")
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


def _fetch_macro_data(days: int = 600) -> "pd.DataFrame":
    """Fetch NIFTY50 + INDIAVIX via yfinance (data-service holds the DuckDB write lock)."""
    import pandas as pd

    try:
        import yfinance as yf
        from datetime import date as _date, timedelta
        end = _date.today()
        start = end - timedelta(days=days)
        nifty_raw = yf.download("^NSEI",     start=str(start), end=str(end), progress=False)
        vix_raw   = yf.download("^INDIAVIX", start=str(start), end=str(end), progress=False)

        def _to_df(raw):
            d = raw.copy().reset_index()
            d.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in d.columns]
            if "close" not in d.columns and "adj close" in d.columns:
                d["close"] = d["adj close"]
            return d[["date", "close"]].dropna()

        nifty_df = _to_df(nifty_raw)
        vix_df   = _to_df(vix_raw)
        if not nifty_df.empty and not vix_df.empty:
            return compute_macro_features(nifty_df, vix_df)
    except Exception:
        pass

    return pd.DataFrame()


async def _run_feature_generation(job_id: str):
    """
    Batch-compute full ML feature set for all tickers.

    Strategy:
    - If feature_engine is importable (local dev + Docker with shared mount):
        load OHLCV bulk from DuckDB, fetch macro via yfinance, compute features
        in-process — significantly faster than per-ticker HTTP.
    - Fallback: call feature-service /calculate/features per ticker over HTTP.

    Writes: DuckDB ml_features + ml_labels tables, Parquet files as backup.
    """
    import pandas as pd

    start = datetime.now()

    if _FEATURE_ENGINE_AVAILABLE:
        await _run_feature_generation_direct(job_id, start)
    else:
        await _run_feature_generation_http(job_id, start)


async def _run_feature_generation_direct(job_id: str, start: datetime):
    """Fast path: bulk HTTP load from data-service + in-process feature_engine computation.

    data-service holds the DuckDB write lock, so we fetch OHLCV and fundamentals
    via HTTP rather than opening a competing DuckDB connection.
    """
    import pandas as pd

    _jobs[job_id]["status"] = "loading_data"

    # ── 1. Load ALL OHLCV via data-service HTTP ─────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.get(f"{DATA_SVC}/db/ohlcv-bulk", params={"days": 700})
            resp.raise_for_status()
            ohlcv_records = resp.json().get("data", [])
    except Exception as e:
        _jobs[job_id].update({"status": "error", "errors": [{"general": f"OHLCV bulk load failed: {e}"}]})
        return

    ohlcv_all = pd.DataFrame(ohlcv_records)
    if ohlcv_all.empty:
        _jobs[job_id].update({"status": "error", "errors": [{"general": "No OHLCV data returned from data-service"}]})
        return
    ohlcv_all["date"] = pd.to_datetime(ohlcv_all["date"])
    tickers = sorted(ohlcv_all["ticker"].unique().tolist())

    _jobs[job_id]["total"] = len(tickers)
    _jobs[job_id]["status"] = "computing_macro"

    # ── 2. Macro features (fetched once, merged to all tickers) ─────────────────
    macro_df = await asyncio.to_thread(_fetch_macro_data, 700)

    # ── 3. Market breadth ────────────────────────────────────────────────────────
    try:
        breadth_df = compute_market_breadth(ohlcv_all)
        if macro_df is not None and not macro_df.empty and not breadth_df.empty:
            breadth_df["date"] = pd.to_datetime(breadth_df["date"])
            macro_df["date"]   = pd.to_datetime(macro_df["date"])
            macro_df = macro_df.merge(breadth_df, on="date", how="left")
    except Exception:
        pass  # breadth is optional

    # ── 4. Load fundamentals via data-service HTTP ──────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(f"{DATA_SVC}/db/fundamentals-bulk")
            resp.raise_for_status()
            fund_records = resp.json().get("data", [])
        fund_all = pd.DataFrame(fund_records)
        if not fund_all.empty and "as_of_date" in fund_all.columns:
            fund_all["as_of_date"] = pd.to_datetime(fund_all["as_of_date"])
    except Exception:
        fund_all = pd.DataFrame()

    # ── 5. Per-ticker feature computation ────────────────────────────────────────
    _jobs[job_id]["status"] = "computing_features"
    all_features: list[pd.DataFrame] = []
    all_labels:   list[pd.DataFrame] = []
    errors: list[dict] = []

    for i, ticker in enumerate(tickers):
        try:
            ohlcv_t = ohlcv_all[ohlcv_all["ticker"] == ticker].drop(columns=["ticker"]).copy()
            if len(ohlcv_t) < 60:
                _jobs[job_id]["progress"] = i + 1
                continue

            fund_t = fund_all[fund_all["ticker"] == ticker].drop(columns=["ticker"]).copy() \
                     if not fund_all.empty else pd.DataFrame()

            feat_df = build_ticker_features(ticker, ohlcv_t, fund_t, macro_df)
            if not feat_df.empty:
                all_features.append(feat_df)

            # Triple-barrier labels
            lbl_df = build_triple_barrier_labels(ohlcv_t.copy(), horizon=5,
                                                  profit_target_pct=2.0, stop_loss_pct=2.0)
            lbl_df = lbl_df.dropna(subset=["label_barrier"])
            if not lbl_df.empty:
                lbl_df["ticker"] = ticker
                lbl_df["date"]   = pd.to_datetime(lbl_df["date"]).dt.strftime("%Y-%m-%d")
                lbl_out = lbl_df[["ticker","date","horizon_days","label_direction",
                                   "label_return_pct","label_barrier",
                                   "profit_target_pct","stop_loss_pct"]].copy()
                all_labels.append(lbl_out)

        except Exception as e:
            errors.append({"ticker": ticker, "error": str(e)})

        _jobs[job_id]["progress"] = i + 1

    _jobs[job_id]["errors"] = errors

    # ── 6. Persist ───────────────────────────────────────────────────────────────
    _jobs[job_id]["status"] = "saving"

    if all_features:
        feat_df = pd.concat(all_features, ignore_index=True)
        feat_df["date"] = feat_df["date"].astype(str).str[:10]
        feat_df.to_parquet(str(FEATURES_PARQUET), index=False)

    if all_labels:
        lbl_df = pd.concat(all_labels, ignore_index=True)
        lbl_df.to_parquet(str(LABELS_PARQUET), index=False)

    # Import Parquet → DuckDB via data-service (avoids write-lock conflicts)
    _jobs[job_id]["status"] = "importing_to_db"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{DATA_SVC}/admin/import-ml-data")
            if resp.status_code == 200:
                _jobs[job_id]["db_import"] = resp.json()
            else:
                errors.append({"general": f"DuckDB import: data-service returned {resp.status_code}: {resp.text[:200]}"})
    except Exception as e:
        errors.append({"general": f"DuckDB import request failed: {e}"})

    elapsed = (datetime.now() - start).total_seconds()
    _jobs[job_id].update({
        "status":        "done",
        "elapsed_secs":  elapsed,
        "features_rows": len(feat_df) if all_features else 0,
        "labels_rows":   len(lbl_df)  if all_labels   else 0,
        "tickers_done":  len(tickers),
    })


async def _run_feature_generation_http(job_id: str, start: datetime):
    """Fallback: call feature-service /calculate/features per ticker over HTTP."""
    import pandas as pd

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(f"{DATA_SVC}/db/ohlcv-meta")
            resp.raise_for_status()
            tickers = [row["ticker"] for row in resp.json().get("data", [])]
    except Exception as e:
        _jobs[job_id].update({"status": "error", "errors": [{"general": f"Ticker list load failed: {e}"}]})
        return

    _jobs[job_id]["total"] = len(tickers)
    all_features: list[dict] = []
    all_labels:   list[dict] = []

    async with httpx.AsyncClient(timeout=120) as client:
        for i, ticker in enumerate(tickers):
            try:
                ohlcv_resp = await client.get(f"{DATA_SVC}/ohlcv/{ticker}", params={"limit": 1500})
                if ohlcv_resp.status_code != 200:
                    _jobs[job_id]["errors"].append({"ticker": ticker, "error": f"data-service {ohlcv_resp.status_code}"})
                    _jobs[job_id]["progress"] = i + 1
                    continue

                ohlcv_rows = ohlcv_resp.json().get("data", [])
                if len(ohlcv_rows) < 60:
                    _jobs[job_id]["progress"] = i + 1
                    continue

                feat_resp = await client.post(
                    f"{FEATURE_SVC}/calculate/features",
                    json={"ticker": ticker, "ohlcv": ohlcv_rows},
                    timeout=60,
                )
                if feat_resp.status_code == 200:
                    for row in feat_resp.json().get("features", []):
                        row["ticker"] = ticker
                        all_features.append(row)

                # Simple forward-return labels as fallback
                ohlcv_df = pd.DataFrame(ohlcv_rows)
                ohlcv_df["date"] = pd.to_datetime(ohlcv_df["date"]).dt.strftime("%Y-%m-%d")
                ohlcv_df = ohlcv_df.sort_values("date").reset_index(drop=True)
                future_close = ohlcv_df["close"].shift(-5)
                ohlcv_df["label_direction"]  = (future_close > ohlcv_df["close"]).astype(float)
                ohlcv_df["label_return_pct"] = ((future_close - ohlcv_df["close"]) / ohlcv_df["close"]) * 100
                for _, row in ohlcv_df[ohlcv_df["label_return_pct"].notna()].iterrows():
                    all_labels.append({
                        "ticker": ticker,
                        "date": str(row["date"])[:10],
                        "label_direction": int(row["label_direction"]),
                        "label_return_pct": float(row["label_return_pct"]),
                    })

            except Exception as e:
                _jobs[job_id]["errors"].append({"ticker": ticker, "error": str(e)})

            _jobs[job_id]["progress"] = i + 1

    if all_features:
        pd.DataFrame(all_features).to_parquet(str(FEATURES_PARQUET), index=False)
    if all_labels:
        pd.DataFrame(all_labels).to_parquet(str(LABELS_PARQUET), index=False)

    elapsed = (datetime.now() - start).total_seconds()
    _jobs[job_id].update({"status": "done", "elapsed_secs": elapsed})


@router.post("/generate-features")
async def trigger_feature_generation(background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{DATA_SVC}/db/stats")
            count = r.json().get("total_stocks", 501) if r.status_code == 200 else 501
    except Exception:
        count = 501

    # Pre-register job so first poll doesn't 404
    _jobs[job_id] = {
        "status":     "loading_data",
        "progress":   0,
        "total":      count,
        "errors":     [],
        "start_time": datetime.now(),
        "engine":     "direct" if _FEATURE_ENGINE_AVAILABLE else "http",
    }

    background_tasks.add_task(_run_feature_generation, job_id)
    return {
        "job_id": job_id,
        "status": "loading_data",
        "progress": 0,
        "total": count,
        "engine": "direct" if _FEATURE_ENGINE_AVAILABLE else "http",
        "feature_count": len(FEATURE_COLS),
    }


@router.get("/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

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
    """Load features + labels from Parquet and train via ml-service."""
    import pandas as pd

    try:
        if not FEATURES_PARQUET.exists():
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = "No features found. Run Phase 3 (Feature Pipeline) first."
            return

        if not LABELS_PARQUET.exists():
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = "No labels found. Run Phase 3 (Feature Pipeline) first."
            return

        feat_df = pd.read_parquet(str(FEATURES_PARQUET))
        lbl_df  = pd.read_parquet(str(LABELS_PARQUET))

        # Normalise date column
        feat_df["date"] = feat_df["date"].astype(str).str[:10]
        lbl_df["date"]  = lbl_df["date"].astype(str).str[:10]

        # Join on ticker + date
        merged = feat_df.merge(lbl_df, on=["ticker", "date"], how="inner")
        merged = merged.dropna(subset=["label_direction", "label_return_pct"])

        if len(merged) < 500:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = f"Only {len(merged)} joined rows — need ≥500. Re-run Phase 3."
            return

        # Encode nifty_regime categorical → integer (bull=1, bear=-1, range=0)
        if "nifty_regime" in merged.columns:
            regime_map = {"bull": 1, "range": 0, "bear": -1}
            merged["nifty_regime"] = merged["nifty_regime"].map(regime_map).fillna(0).astype(int)

        # Valid feature columns present in merged df (only numeric)
        feature_pool = selected_features if selected_features else FEATURE_COLS
        valid_cols = [c for c in feature_pool if c in merged.columns
                      and merged[c].dtype.kind in "fiub"]  # float/int/uint/bool only

        # Sample: last 200 rows per ticker to keep payload <20MB
        merged = merged.sort_values("date").groupby("ticker").tail(200).reset_index(drop=True)

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
            ohlcv_meta_resp = await client.get(f"{DATA_SVC}/db/ohlcv-meta")
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
            try:
                feat_df = pd.read_parquet(str(FEATURES_PARQUET))
                feat_tickers = feat_df["ticker"].nunique()
                feat_rows = len(feat_df)
                per_ticker = feat_df.groupby("ticker").size()
                sparse_tickers = int((per_ticker < 100).sum())
                avg_rows_per_ticker = round(float(per_ticker.mean()), 0) if len(per_ticker) else 0
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
            try:
                lbl_df = pd.read_parquet(str(LABELS_PARQUET))
                total_labels = len(lbl_df)
                up_labels    = int((lbl_df["label_direction"] == 1).sum())
                down_labels  = int((lbl_df["label_direction"] == 0).sum())
                class_balance_pct  = round(up_labels / total_labels * 100, 1) if total_labels else 0
                avg_ret = round(float(lbl_df["label_return_pct"].mean()), 4)
                std_ret = round(float(lbl_df["label_return_pct"].std()), 4)
                has_triple_barrier = "label_barrier" in lbl_df.columns
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
        return {"error": str(e)}


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


@router.get("/feature-stats")
async def get_feature_stats():
    """Univariate statistics for every feature from the Parquet cache."""
    import pandas as pd

    if not FEATURES_PARQUET.exists() or not LABELS_PARQUET.exists():
        raise HTTPException(status_code=404, detail="Run Phase 3 first")

    feat_df = pd.read_parquet(str(FEATURES_PARQUET))
    lbl_df  = pd.read_parquet(str(LABELS_PARQUET))
    feat_df["date"] = feat_df["date"].astype(str).str[:10]
    lbl_df["date"]  = lbl_df["date"].astype(str).str[:10]
    merged = feat_df.merge(lbl_df[["ticker", "date", "label_direction"]], on=["ticker", "date"], how="inner")

    result = []
    for col in FEATURE_COLS:
        if col not in merged.columns:
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

    return {"features": result}


@router.get("/feature-correlations")
async def get_feature_correlations():
    """Pearson correlation matrix for top features (from Parquet)."""
    import pandas as pd

    if not FEATURES_PARQUET.exists():
        raise HTTPException(status_code=404, detail="Run Phase 3 first")

    feat_df = pd.read_parquet(str(FEATURES_PARQUET))
    valid_cols = [c for c in FEATURE_COLS if c in feat_df.columns]
    if len(valid_cols) < 2:
        raise HTTPException(status_code=400, detail="Not enough features")

    # Sample for performance
    sample = feat_df[valid_cols].dropna(how="all").sample(min(8000, len(feat_df)), random_state=42)
    corr = sample[valid_cols].corr().round(3)
    matrix = corr.fillna(0).values.tolist()
    return {"features": valid_cols, "matrix": matrix}


@router.get("/feature-distribution")
async def get_feature_distribution(feature: str):
    """Histogram of a feature split by label (UP=1 vs DOWN=0)."""
    import pandas as pd

    if not FEATURES_PARQUET.exists() or not LABELS_PARQUET.exists():
        raise HTTPException(status_code=404, detail="Run Phase 3 first")
    if feature not in FEATURE_COLS:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    feat_df = pd.read_parquet(str(FEATURES_PARQUET))
    lbl_df  = pd.read_parquet(str(LABELS_PARQUET))
    feat_df["date"] = feat_df["date"].astype(str).str[:10]
    lbl_df["date"]  = lbl_df["date"].astype(str).str[:10]

    if feature not in feat_df.columns:
        raise HTTPException(status_code=400, detail=f"Feature '{feature}' not in data")

    merged = feat_df[["ticker", "date", feature]].merge(
        lbl_df[["ticker", "date", "label_direction"]], on=["ticker", "date"], how="inner"
    ).dropna()

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
):
    """Paginated feature grid with data health statistics."""
    import pandas as pd
    loop = asyncio.get_running_loop()

    def _read():
        if not FEATURES_PARQUET.exists():
            return None, "No feature data. Run Phase 3 (Compute Features) first."
        df = pd.read_parquet(str(FEATURES_PARQUET))
        df["date"] = df["date"].astype(str).str[:10]
        if ticker:
            df = df[df["ticker"] == ticker.upper()]
        total_rows = len(df)
        total_tickers = int(df["ticker"].nunique()) if "ticker" in df.columns else 0
        date_min = str(df["date"].min()) if total_rows > 0 else None
        date_max = str(df["date"].max()) if total_rows > 0 else None
        valid_feat_cols = [c for c in FEATURE_COLS if c in df.columns]
        null_counts = {col: int(df[col].isna().sum()) for col in valid_feat_cols}
        avg_null_pct = round(
            sum(null_counts.values()) / max(len(valid_feat_cols) * total_rows, 1) * 100, 2
        )
        health = {
            "total_rows": total_rows,
            "total_tickers": total_tickers,
            "date_min": date_min,
            "date_max": date_max,
            "avg_null_pct": avg_null_pct,
            "null_counts": null_counts,
            "feature_count": len(valid_feat_cols),
        }
        sort_col = sort_by if sort_by in df.columns else "date"
        df = df.sort_values(sort_col, ascending=(sort_dir == "asc"))
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        page_df = df.iloc[offset : offset + page_size]
        display_cols = ["ticker", "date"] + [c for c in FEATURE_COLS if c in page_df.columns]
        records = page_df[display_cols].replace({float("nan"): None}).to_dict(orient="records")
        return {
            "health": health,
            "columns": display_cols,
            "rows": records,
            "page": page,
            "page_size": page_size,
            "total_rows": total_rows,
            "total_pages": total_pages,
        }, None

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
            _NON_FEATURE = {
                "ticker", "date", "created_at", "feature_version", "stock_id",
                "label_direction", "label_return_pct", "label_return", "fwd_return", "target",
            }
            if selected_features_cfg:
                feature_pool = selected_features_cfg
            else:
                feature_pool = [
                    c for c in merged.columns
                    if c not in _NON_FEATURE and pd.api.types.is_numeric_dtype(merged[c])
                ]
            valid_cols = [c for c in feature_pool if c in merged.columns and merged[c].notna().any()]
            _emit(job_id, f"Feature pool: {len(valid_cols)} usable columns "
                          f"({'custom selection' if selected_features_cfg else 'all available'})")
            merged = merged.sort_values("date").groupby("ticker").tail(rows_per_ticker).reset_index(drop=True)
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
    return {"ticker": ticker, "shap_values": [], "error": "Could not fetch SHAP values"}


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
    metrics_path    = Path("/app/data/rl_training_metrics.json")
    _get_or_create_queue(job_id)  # pre-register for SSE

    async def _run_rl_training():
        import pandas as pd, math
        _jobs[job_id] = {"status": "running", "start_time": datetime.now(), "progress": 0, "errors": []}
        _emit(job_id, f"RL training started — timesteps={total_timesteps:,} candidates={n_candidates}")

        # Signal training started so the frontend sees activity immediately
        metrics_path.write_text(json.dumps({
            "status": "training",
            "last_updated": datetime.now().isoformat(),
            "total_timesteps": total_timesteps,
            "metrics": [],
        }))

        try:
            # ── Build signals from computed features+labels parquet ──────────────
            if not FEATURES_PARQUET.exists() or not LABELS_PARQUET.exists():
                raise FileNotFoundError("No feature/label parquet. Run Phase 3 first.")

            feat_df = pd.read_parquet(str(FEATURES_PARQUET))
            lbl_df  = pd.read_parquet(str(LABELS_PARQUET))
            feat_df["date"] = feat_df["date"].astype(str).str[:10]
            lbl_df["date"]  = lbl_df["date"].astype(str).str[:10]
            merged = feat_df.merge(lbl_df, on=["ticker", "date"], how="inner").dropna(
                subset=["label_direction", "label_return_pct"]
            ).sort_values("date")

            _SIGNAL_COLS = [
                "prob_up", "confidence", "rsi_14", "bb_pct",
                "volume_ratio", "sma_ratio_20_50", "hist_vol_20",
            ]

            def _build_signal(row) -> dict:
                def _safe(v):
                    try:
                        return 0.0 if (v is None or math.isnan(float(v)) or math.isinf(float(v))) else float(v)
                    except Exception:
                        return 0.0
                return {
                    "ticker":               str(row.get("ticker", "")),
                    "date":                 str(row.get("date", "")),
                    "prob_up":              _safe(row.get("prob_up", 0.5)),
                    "confidence":           _safe(row.get("confidence", 0.0)),
                    "expected_return_pct":  _safe(row.get("label_return_pct", 0.0)),
                    "rsi_14":               _safe(row.get("rsi_14", 50.0)),
                    "bb_pct":               _safe(row.get("bb_pct", 0.5)),
                    "volume_ratio":         _safe(row.get("volume_ratio", 1.0)),
                    "sma_ratio_20_50":      _safe(row.get("sma_ratio_20_50", 1.0)),
                    "hist_vol_20":          _safe(row.get("hist_vol_20", 20.0)),
                    "sector_id":            int(row.get("sector_id", 0)) if "sector_id" in row else 0,
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

            _emit(job_id, f"Built {len(signals_data)} daily signal batches from {len(merged):,} rows")
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
                    "last_updated": datetime.now().isoformat(),
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
                "last_updated": datetime.now().isoformat(),
                "metrics": [],
            }))

    background_tasks.add_task(_run_rl_training)
    return {"job_id": job_id, "status": "queued"}


@router.get("/rl-training-metrics")
async def get_rl_training_metrics():
    metrics_path = "/app/data/rl_training_metrics.json"
    try:
        with open(metrics_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"status": "not_started", "last_updated": None, "metrics": []}
    except Exception as e:
        return {"status": "error", "error": str(e), "metrics": []}


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
