from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from shared.config import Settings, get_settings

router = APIRouter(prefix="/data", tags=["data"])


def _data_url(settings: Settings) -> str:
    return settings.data_service_url


class FetchHistoricalRequest(BaseModel):
    tickers: list[str]
    years: int = 5


@router.post("/fetch/historical")
async def fetch_historical(req: FetchHistoricalRequest, settings: Settings = Depends(get_settings)):
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(f"{_data_url(settings)}/fetch/historical", json=req.model_dump())
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


@router.get("/ohlcv/{ticker}")
async def get_ohlcv(ticker: str, start: str | None = None, end: str | None = None, settings: Settings = Depends(get_settings)):
    params = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{_data_url(settings)}/ohlcv/{ticker}", params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()


@router.get("/live/quote/{ticker}")
async def get_live_quote(ticker: str, settings: Settings = Depends(get_settings)):
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_data_url(settings)}/live/quote/{ticker}")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
