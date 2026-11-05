from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))    # feature_engine, indicators, labels
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # shared

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from feature_engine import (
    build_ticker_features,
    compute_price_technical,
    merge_fundamentals,
    build_triple_barrier_labels,
    FEATURE_COLS,
    LABEL_COLS,
    _FUND_COLS,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging("feature-service", settings.log_level)
    logger.info("Feature service started — %d feature columns", len(FEATURE_COLS))
    yield
    logger.info("Feature service stopped")


app = FastAPI(
    title="SuryaDhana — Feature Service",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Health ──────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "feature-service"}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready", "feature_count": len(FEATURE_COLS)}


@app.get("/features/list")
async def list_features() -> dict:
    return {"features": FEATURE_COLS, "count": len(FEATURE_COLS), "label_cols": LABEL_COLS}


# ── Single-ticker feature calculation ───────────────────────────────────────────

class CalculateFeaturesRequest(BaseModel):
    ticker: str
    ohlcv: list[dict]
    fundamentals: Optional[list[dict]] = None  # list of fundamental snapshot dicts


class CalculateFeaturesResponse(BaseModel):
    ticker: str
    rows: int
    features: list[dict]


@app.post("/calculate/features", response_model=CalculateFeaturesResponse)
async def calculate_features(req: CalculateFeaturesRequest) -> CalculateFeaturesResponse:
    if not req.ohlcv:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No OHLCV data provided")

    ohlcv_df = pd.DataFrame(req.ohlcv)
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(ohlcv_df.columns):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing OHLCV columns: {required - set(ohlcv_df.columns)}",
        )

    ohlcv_df["date"] = pd.to_datetime(ohlcv_df["date"])
    ohlcv_df = ohlcv_df.sort_values("date").reset_index(drop=True)

    fund_df = pd.DataFrame(req.fundamentals) if req.fundamentals else pd.DataFrame()

    df = build_ticker_features(
        ticker=req.ticker,
        ohlcv_df=ohlcv_df,
        fund_df=fund_df,
        macro_df=None,  # macro not available per-ticker over HTTP; caller must add if needed
    )

    if df.empty:
        return CalculateFeaturesResponse(ticker=req.ticker, rows=0, features=[])

    df["date"] = df["date"].astype(str).str[:10]
    records = df.to_dict(orient="records")

    return CalculateFeaturesResponse(
        ticker=req.ticker,
        rows=len(records),
        features=records,
    )


# ── Single-ticker label building ────────────────────────────────────────────────

class BuildLabelsRequest(BaseModel):
    ticker: str
    ohlcv: list[dict]
    horizon: int = 5
    profit_target_pct: float = 2.0
    stop_loss_pct: float = 2.0


class BuildLabelsResponse(BaseModel):
    ticker: str
    rows_with_labels: int
    up_pct: float
    data: list[dict]


@app.post("/build/labels", response_model=BuildLabelsResponse)
async def build_labels_endpoint(req: BuildLabelsRequest) -> BuildLabelsResponse:
    if not req.ohlcv:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No OHLCV data provided")

    df = pd.DataFrame(req.ohlcv)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df = build_triple_barrier_labels(
        df,
        horizon=req.horizon,
        profit_target_pct=req.profit_target_pct,
        stop_loss_pct=req.stop_loss_pct,
    )
    labeled = df.dropna(subset=["label_direction"])

    up_pct = float(labeled["label_direction"].mean() * 100) if len(labeled) else 0.0

    out_cols = ["date", "close", "label_direction", "label_return_pct", "label_barrier",
                "horizon_days", "profit_target_pct", "stop_loss_pct"]
    out_cols = [c for c in out_cols if c in labeled.columns]

    records = labeled[out_cols].copy()
    records["date"] = records["date"].astype(str).str[:10]

    return BuildLabelsResponse(
        ticker=req.ticker,
        rows_with_labels=len(records),
        up_pct=round(up_pct, 1),
        data=records.to_dict(orient="records"),
    )


# ── Price-only features (lightweight, no fundamentals/macro) ────────────────────

class PriceFeaturesRequest(BaseModel):
    ticker: str
    ohlcv: list[dict]


@app.post("/calculate/price-features")
async def calculate_price_features(req: PriceFeaturesRequest) -> dict:
    """Compute only the 45 price/technical features. Fast endpoint for real-time use."""
    if not req.ohlcv:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No OHLCV data")

    df = pd.DataFrame(req.ohlcv)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    df = compute_price_technical(df)
    price_feat_cols = [c for c in FEATURE_COLS if c in df.columns
                       and c not in _FUND_COLS + ["altman_z", "peg_ratio",
                                                   "insider_hold_pct", "inst_hold_pct",
                                                   "india_vix", "vix_zscore",
                                                   "nifty_ret_5d", "nifty_regime", "market_breadth"]]

    result = df[["date"] + price_feat_cols].dropna(subset=["rsi_14", "macd"]).copy()
    result["date"] = result["date"].astype(str).str[:10]

    return {
        "ticker": req.ticker,
        "rows": len(result),
        "features": result.to_dict(orient="records"),
    }
