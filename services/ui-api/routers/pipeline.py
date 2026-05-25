"""Pipeline: feature generation, model training, and orchestration."""
import os
import uuid
import asyncio
import subprocess
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
import duckdb

router = APIRouter()

FEATURE_SVC = os.getenv("FEATURE_SERVICE_URL", "http://feature-service:8002")
ML_SVC      = os.getenv("ML_SERVICE_URL",      "http://ml-service:8003")
RL_SVC      = os.getenv("RL_SERVICE_URL",       "http://rl-service:8004")
DATA_SVC    = os.getenv("DATA_SERVICE_URL",     "http://data-service:8001")
DB_PATH     = os.getenv("DATABASE_URL",         "/app/data/market.duckdb")

# Parquet cache paths (writable, avoid DuckDB STRUCT schema issues)
DATA_DIR          = Path(os.getenv("DATABASE_URL", "/app/data/market.duckdb")).parent
FEATURES_PARQUET  = DATA_DIR / "computed_features.parquet"
LABELS_PARQUET    = DATA_DIR / "computed_labels.parquet"

_jobs: dict[str, dict] = {}

FEATURE_COLS = [
    "sma_ratio_20_50", "ema_ratio_12_26", "price_vs_sma20", "price_vs_sma50",
    "macd", "macd_signal", "macd_hist", "uptrend_20_50", "uptrend_50_200",
    "rsi_14", "rsi_28", "rsi_7", "stoch_k", "stoch_d",
    "roc_5", "roc_10", "roc_20", "williams_r",
    "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
    "is_green_candle",
    "bb_width", "bb_pct", "atr_14_pct", "hist_vol_20",
    "high_low_ratio", "close_position", "gap_pct",
    "volume_ratio", "obv_sma_20", "mfi_14", "cmf_20", "volume_spike",
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


async def _run_feature_generation(job_id: str):
    """Compute features + labels for all tickers via feature-service, persist to Parquet."""
    import pandas as pd

    start = datetime.now()

    # Get tickers from DuckDB
    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM ohlcv ORDER BY ticker").fetchall()]
        con.close()
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["errors"].append({"general": f"DB read failed: {e}"})
        return

    _jobs[job_id]["total"] = len(tickers)

    all_features: list[dict] = []
    all_labels:   list[dict] = []

    async with httpx.AsyncClient(timeout=120) as client:
        for i, ticker in enumerate(tickers):
            try:
                # Fetch OHLCV — data-service returns {"ticker":..., "rows":count, "data":[...]}
                ohlcv_resp = await client.get(
                    f"{DATA_SVC}/ohlcv/{ticker}", params={"limit": 1500}
                )
                if ohlcv_resp.status_code != 200:
                    _jobs[job_id]["errors"].append({"ticker": ticker, "error": f"data-service {ohlcv_resp.status_code}"})
                    _jobs[job_id]["progress"] = i + 1
                    continue

                ohlcv_rows = ohlcv_resp.json().get("data", [])  # KEY FIX: "data" not "rows"
                if len(ohlcv_rows) < 60:
                    _jobs[job_id]["progress"] = i + 1
                    continue

                # Compute features via feature-service
                feat_resp = await client.post(
                    f"{FEATURE_SVC}/calculate/features",
                    json={"ticker": ticker, "ohlcv": ohlcv_rows},
                    timeout=60,
                )
                if feat_resp.status_code != 200:
                    _jobs[job_id]["errors"].append({"ticker": ticker, "error": f"feature-service {feat_resp.status_code}"})
                    _jobs[job_id]["progress"] = i + 1
                    continue

                feature_rows = feat_resp.json().get("features", [])
                if not feature_rows:
                    _jobs[job_id]["progress"] = i + 1
                    continue

                # Attach ticker to each feature row
                for row in feature_rows:
                    row["ticker"] = ticker
                all_features.extend(feature_rows)

                # Compute 5-day forward return labels from OHLCV
                ohlcv_df = pd.DataFrame(ohlcv_rows)
                ohlcv_df["date"] = pd.to_datetime(ohlcv_df["date"]).dt.strftime("%Y-%m-%d")
                ohlcv_df = ohlcv_df.sort_values("date").reset_index(drop=True)
                horizon = 5
                future_close = ohlcv_df["close"].shift(-horizon)
                ohlcv_df["label_direction"]   = (future_close > ohlcv_df["close"]).astype(float)
                ohlcv_df["label_return_pct"]  = ((future_close - ohlcv_df["close"]) / ohlcv_df["close"]) * 100
                valid_mask = ~ohlcv_df["label_return_pct"].isna()

                for _, row in ohlcv_df[valid_mask].iterrows():
                    all_labels.append({
                        "ticker": ticker,
                        "date": str(row["date"])[:10],
                        "label_direction": int(row["label_direction"]),
                        "label_return_pct": float(row["label_return_pct"]),
                    })

            except Exception as e:
                _jobs[job_id]["errors"].append({"ticker": ticker, "error": str(e)})

            _jobs[job_id]["progress"] = i + 1

    # Save to Parquet for persistence (bypasses DuckDB STRUCT schema issues)
    try:
        if all_features:
            feat_df = pd.DataFrame(all_features)
            feat_df.to_parquet(str(FEATURES_PARQUET), index=False)

        if all_labels:
            lbl_df = pd.DataFrame(all_labels)
            lbl_df.to_parquet(str(LABELS_PARQUET), index=False)
    except Exception as e:
        _jobs[job_id]["errors"].append({"general": f"Parquet save failed: {e}"})

    elapsed = (datetime.now() - start).total_seconds()
    _jobs[job_id]["status"] = "done"
    _jobs[job_id]["elapsed_secs"] = elapsed


@router.post("/generate-features")
async def trigger_feature_generation(background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        count = con.execute("SELECT COUNT(DISTINCT ticker) FROM ohlcv").fetchone()[0]
        con.close()
    except Exception:
        count = 501

    # Pre-register job so first poll doesn't get 404
    _jobs[job_id] = {
        "status": "running",
        "progress": 0,
        "total": count,
        "errors": [],
        "start_time": datetime.now(),
    }

    background_tasks.add_task(_run_feature_generation, job_id)
    return {"job_id": job_id, "status": "running", "progress": 0, "total": count}


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

        # Valid feature columns present in merged df
        feature_pool = selected_features if selected_features else FEATURE_COLS
        valid_cols = [c for c in feature_pool if c in merged.columns]

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
    """Return training data quality metrics from DuckDB + Parquet cache."""
    import pandas as pd

    try:
        con = duckdb.connect(DB_PATH, read_only=True)

        ohlcv_stats = con.execute("""
            SELECT COUNT(DISTINCT ticker), COUNT(*), MIN(date), MAX(date)
            FROM ohlcv
        """).fetchone()

        ticker_counts = con.execute("""
            SELECT ticker, COUNT(*) as candles FROM ohlcv GROUP BY ticker ORDER BY candles DESC
        """).fetchall()

        stale_tickers = con.execute("""
            SELECT ticker, MAX(date) as last_date FROM ohlcv
            GROUP BY ticker ORDER BY last_date ASC LIMIT 10
        """).fetchall()

        con.close()

        total_tickers = ohlcv_stats[0] or 0
        total_candles = ohlcv_stats[1] or 0
        min_date = str(ohlcv_stats[2]) if ohlcv_stats[2] else "—"
        max_date = str(ohlcv_stats[3]) if ohlcv_stats[3] else "—"

        candle_buckets = {"<500": 0, "500-1000": 0, "1000-1500": 0, ">1500": 0}
        for _, cnt in ticker_counts:
            if cnt < 500:              candle_buckets["<500"] += 1
            elif cnt < 1000:           candle_buckets["500-1000"] += 1
            elif cnt < 1500:           candle_buckets["1000-1500"] += 1
            else:                      candle_buckets[">1500"] += 1

        # Feature stats from Parquet
        feat_tickers = 0
        feat_rows = 0
        sparse_tickers = 0
        avg_rows_per_ticker = 0.0

        if FEATURES_PARQUET.exists():
            try:
                feat_df = pd.read_parquet(str(FEATURES_PARQUET))
                feat_tickers = feat_df["ticker"].nunique()
                feat_rows = len(feat_df)
                per_ticker = feat_df.groupby("ticker").size()
                sparse_tickers = int((per_ticker < 100).sum())
                avg_rows_per_ticker = round(float(per_ticker.mean()), 0) if len(per_ticker) else 0
            except Exception:
                pass

        # Label stats from Parquet
        total_labels = 0
        up_labels = 0
        down_labels = 0
        class_balance_pct = 0.0
        avg_ret = 0.0
        std_ret = 0.0

        if LABELS_PARQUET.exists():
            try:
                lbl_df = pd.read_parquet(str(LABELS_PARQUET))
                total_labels = len(lbl_df)
                up_labels = int((lbl_df["label_direction"] == 1).sum())
                down_labels = int((lbl_df["label_direction"] == 0).sum())
                class_balance_pct = round(up_labels / total_labels * 100, 1) if total_labels else 0
                avg_ret = round(float(lbl_df["label_return_pct"].mean()), 4)
                std_ret = round(float(lbl_df["label_return_pct"].std()), 4)
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
                "stale_tickers": [{"ticker": t, "last_date": str(d)} for t, d in stale_tickers],
            },
            "features": {
                "tickers_processed": feat_tickers,
                "total_rows": feat_rows,
                "coverage_pct": round(feat_tickers / total_tickers * 100, 1) if total_tickers else 0,
                "sparse_tickers": sparse_tickers,
                "avg_rows_per_ticker": avg_rows_per_ticker,
            },
            "labels": {
                "total_labels": total_labels,
                "up_labels": up_labels,
                "down_labels": down_labels,
                "class_balance_pct": class_balance_pct,
                "avg_return_pct": avg_ret,
                "std_return_pct": std_ret,
            },
            "readiness": {
                "has_ohlcv": total_candles > 0,
                "has_features": feat_rows > 0,
                "has_labels": total_labels > 0,
                "ready_to_train": feat_rows >= 500 and total_labels >= 500,
                "feature_col_count": len(FEATURE_COLS),
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

    rows_per_ticker = int(config.pop("rows_per_ticker", 200))
    run_walk_forward = bool(config.pop("run_walk_forward", False))
    model_type_cfg = str(config.pop("model_type", "xgboost"))
    selected_features_cfg = config.pop("selected_features", None)
    warm_start = bool(config.pop("warm_start", False))
    model_params = config  # remaining keys are model hyperparams

    async def _run():
        import pandas as pd, math

        try:
            if not FEATURES_PARQUET.exists() or not LABELS_PARQUET.exists():
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = "No features found. Run Phase 3 first."
                return

            feat_df = pd.read_parquet(str(FEATURES_PARQUET))
            lbl_df  = pd.read_parquet(str(LABELS_PARQUET))
            feat_df["date"] = feat_df["date"].astype(str).str[:10]
            lbl_df["date"]  = lbl_df["date"].astype(str).str[:10]

            merged = feat_df.merge(lbl_df, on=["ticker", "date"], how="inner")
            merged = merged.dropna(subset=["label_direction", "label_return_pct"])
            feature_pool_cfg = selected_features_cfg if selected_features_cfg else FEATURE_COLS
            valid_cols = [c for c in feature_pool_cfg if c in merged.columns]
            merged = merged.sort_values("date").groupby("ticker").tail(rows_per_ticker).reset_index(drop=True)

            _jobs[job_id]["progress"] = 20

            train_cols = valid_cols + ["ticker", "date", "label_direction", "label_return_pct"]
            payload_df = merged[[c for c in train_cols if c in merged.columns]].copy()
            payload_df["label_direction"]   = payload_df["label_direction"].astype(float)
            payload_df["label_return_pct"]  = payload_df["label_return_pct"].astype(float)

            def _clean(v):
                if v is None: return None
                try:
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
                except Exception: pass
                return v

            records = [{k: _clean(val) for k, val in row.items()} for row in payload_df.to_dict(orient="records")]

            payload = {
                "features": records,
                "feature_cols": [c for c in valid_cols if c in payload_df.columns],
                "target_direction": "label_direction",
                "target_return": "label_return_pct",
                "date_col": "date",
                "run_walk_forward": run_walk_forward,
                "save_models": True,
                "model_type": model_type_cfg,
                "model_params": model_params if model_params else None,
                "warm_start": warm_start,
            }

            _jobs[job_id]["progress"] = 30

            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(f"{ML_SVC}/train", json=payload)

            _jobs[job_id]["progress"] = 100
            if resp.status_code in [200, 202]:
                _jobs[job_id]["status"] = "done"
            else:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = f"ml-service {resp.status_code}: {resp.text[:300]}"

        except Exception as e:
            import traceback
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}"

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

    async def _run_rl_training():
        try:
            _jobs[job_id] = {"status": "running", "start_time": datetime.now(), "progress": 0, "errors": []}
            script_path = "/app/scripts/rl_trainer.py"
            cmd = [
                "python", script_path,
                "--total-timesteps", str(payload.get("total_timesteps", 100000) if payload else 100000),
                "--n-candidates", str(payload.get("n_candidates", 15) if payload else 15),
                "--max-positions", str(payload.get("max_positions", 5) if payload else 5),
                "--log-frequency", str(payload.get("log_frequency", 1000) if payload else 1000),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            _jobs[job_id]["status"] = "done" if result.returncode == 0 else "error"
            if result.returncode != 0:
                _jobs[job_id]["error"] = result.stderr
        except Exception as e:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)

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
