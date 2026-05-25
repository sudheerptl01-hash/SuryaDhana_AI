from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from shared.config import Settings, get_settings

router = APIRouter(prefix="/signals", tags=["signals"])


class PredictBatchRequest(BaseModel):
    tickers: list[str]


@router.post("/generate")
async def generate_signals(req: PredictBatchRequest, settings: Settings = Depends(get_settings)):
    """
    Full signal generation pipeline:
    1. Get OHLCV from data-service
    2. Calculate features from feature-service
    3. Get ML predictions from ml-service
    4. Optimize portfolio with rl-service
    """
    all_signals = []
    errors = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for ticker in req.tickers:
            try:
                # Step 1: Get OHLCV
                ohlcv_resp = await client.get(f"{settings.data_service_url}/ohlcv/{ticker}")
                if ohlcv_resp.status_code != 200:
                    errors.append(f"{ticker}: no OHLCV data")
                    continue

                ohlcv_data = ohlcv_resp.json()["data"]

                # Step 2: Calculate features
                feat_resp = await client.post(
                    f"{settings.feature_service_url}/calculate/features",
                    json={"ticker": ticker, "ohlcv": ohlcv_data},
                )
                if feat_resp.status_code != 200:
                    errors.append(f"{ticker}: feature calculation failed")
                    continue

                features_data = feat_resp.json()["features"]
                if not features_data:
                    continue
                latest_features = features_data[-1]  # most recent row

                # Step 3: ML prediction
                pred_resp = await client.post(
                    f"{settings.ml_service_url}/predict",
                    json={"ticker": ticker, "features": latest_features},
                )
                if pred_resp.status_code != 200:
                    errors.append(f"{ticker}: prediction failed")
                    continue

                signal = pred_resp.json()
                signal["ticker"] = ticker
                if signal.get("is_high_confidence"):
                    all_signals.append(signal)

            except Exception as exc:
                errors.append(f"{ticker}: {exc}")

    # Step 4: RL portfolio optimization
    portfolio_allocation = {}
    if all_signals:
        rl_resp = await client.post(
            f"{settings.rl_service_url}/optimize/portfolio",
            json={"signals": all_signals},
        )
        if rl_resp.status_code == 200:
            portfolio_allocation = rl_resp.json()["allocations"]

    return {
        "total_scanned": len(req.tickers),
        "high_confidence_signals": len(all_signals),
        "signals": all_signals,
        "portfolio_allocation": portfolio_allocation,
        "errors": errors,
    }
