from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import pandas as pd
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from indicators import (
    add_trend_indicators,
    add_momentum_indicators,
    add_volatility_indicators,
    add_volume_indicators,
)
from labels import build_labels, validate_no_lookahead, get_train_features_and_labels

logger = get_logger(__name__)

FEATURE_COLS = [
    # trend
    "sma_ratio_20_50", "ema_ratio_12_26", "price_vs_sma20", "price_vs_sma50",
    "macd", "macd_signal", "macd_hist", "uptrend_20_50", "uptrend_50_200",
    # momentum
    "rsi_14", "rsi_28", "rsi_7", "stoch_k", "stoch_d",
    "roc_5", "roc_10", "roc_20", "williams_r",
    "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
    "is_green_candle",
    # volatility
    "bb_width", "bb_pct", "atr_14_pct", "hist_vol_20",
    "high_low_ratio", "close_position", "gap_pct",
    # volume
    "volume_ratio", "obv_sma_20", "mfi_14", "cmf_20", "volume_spike",
    # calendar
    "day_of_week", "month",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging("feature-service", settings.log_level)
    logger.info("Feature service started")
    yield
    logger.info("Feature service stopped")


app = FastAPI(
    title="SuryaDhana — Feature Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "feature-service"}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready", "feature_count": len(FEATURE_COLS)}


@app.get("/features/list")
async def list_features() -> dict:
    return {"features": FEATURE_COLS, "count": len(FEATURE_COLS)}


# ── Feature calculation ────────────────────────────────────────────────────────

class CalculateFeaturesRequest(BaseModel):
    ticker: str
    ohlcv: list[dict]  # list of OHLCV dicts from data-service


class CalculateFeaturesResponse(BaseModel):
    ticker: str
    rows: int
    features: list[dict]


@app.post("/calculate/features", response_model=CalculateFeaturesResponse)
async def calculate_features(req: CalculateFeaturesRequest) -> CalculateFeaturesResponse:
    if not req.ohlcv:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No OHLCV data provided")

    df = pd.DataFrame(req.ohlcv)
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required OHLCV columns: {required - set(df.columns)}",
        )

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Add calendar features before indicators
    df["day_of_week"] = df["date"].dt.dayofweek
    df["month"] = df["date"].dt.month

    df = add_trend_indicators(df)
    df = add_momentum_indicators(df)
    df = add_volatility_indicators(df)
    df = add_volume_indicators(df)

    feature_df = df[["date"] + [c for c in FEATURE_COLS if c in df.columns]].copy()
    feature_df = feature_df.dropna()

    return CalculateFeaturesResponse(
        ticker=req.ticker,
        rows=len(feature_df),
        features=feature_df.to_dict(orient="records"),
    )


# ── Label building ─────────────────────────────────────────────────────────────

class BuildLabelsRequest(BaseModel):
    ticker: str
    ohlcv: list[dict]
    horizon: int = 5


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
    df["ticker"] = req.ticker

    df = build_labels(df, horizon=req.horizon)
    labeled = df.dropna(subset=["label_direction"])

    up_pct = labeled["label_direction"].mean() * 100 if len(labeled) else 0.0

    return BuildLabelsResponse(
        ticker=req.ticker,
        rows_with_labels=len(labeled),
        up_pct=round(up_pct, 1),
        data=labeled[["date", "close", "label_direction", "label_return_pct"]].to_dict(orient="records"),
    )
