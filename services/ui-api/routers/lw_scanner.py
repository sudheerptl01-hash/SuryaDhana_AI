"""Larry Williams Cycle Scanner & Volatility Breakout Screener — UI API router."""
from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import os

import duckdb
import pandas as pd
import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException

router = APIRouter()

DB_PATH     = os.getenv("DUCKDB_PATH", "/app/data/market.duckdb")
DATA_DIR    = Path(os.getenv("DATABASE_URL", "/app/data/market.duckdb")).parent
SCAN_CSV    = DATA_DIR / "larry_williams_scan_results.csv"
SCRIPTS_DIR = Path("/app/scripts")

_jobs: dict[str, dict] = {}


def _load_ohlcv_flat(limit_days: int = 400) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load OHLCV from DuckDB; returns (df_stocks, df_market_proxy)."""
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = con.execute(f"""
            SELECT ticker, date, open, high, low, close, volume
            FROM ohlcv
            WHERE date >= (SELECT MAX(date)::DATE - INTERVAL '{limit_days} days' FROM ohlcv)
            ORDER BY ticker, date
        """).fetchall()
    finally:
        con.close()

    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])

    # Numeric stock_id required by LarryWilliamsMasterScanner
    id_map = {t: i for i, t in enumerate(sorted(df["ticker"].unique()))}
    df["stock_id"] = df["ticker"].map(id_map)

    # Equal-weight market proxy (stands in for SPY/NIFTY)
    market = (
        df.groupby("date")[["open", "high", "low", "close", "volume"]]
        .mean()
        .reset_index()
    )
    market["ticker"] = "NIFTY_PROXY"

    return df, market


def _load_ohlcv_multiindex(days: int = 500) -> pd.DataFrame:
    """Load OHLCV as MultiIndex (date, ticker) for the screener."""
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = con.execute(f"""
            SELECT date, ticker, open, high, low, close, volume
            FROM ohlcv
            WHERE date >= (SELECT MAX(date)::DATE - INTERVAL '{days} days' FROM ohlcv)
            ORDER BY date, ticker
        """).fetchall()
    finally:
        con.close()

    df = pd.DataFrame(rows, columns=["date", "ticker", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index(["date", "ticker"]).sort_index()


# ── Screener endpoint ─────────────────────────────────────────────────────────

@router.get("/screener")
async def run_screener(days: int = 500):
    """Run LW Volatility Breakout Screener on real NSE OHLCV data."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from larry_williams_screener import VolatilityBreakoutScreener, ScreenerConfig
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Screener script not found: {e}")

    try:
        df = _load_ohlcv_multiindex(days)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB load failed: {e}")

    if len(df) == 0:
        raise HTTPException(status_code=404, detail="No OHLCV data in DuckDB")

    try:
        screener = VolatilityBreakoutScreener(df, ScreenerConfig())
        results = screener.screen_with_breakdown()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screener error: {e}")

    # Cast numpy scalar types to native Python for JSON serialisation
    filter_counts = {k: int(v) for k, v in results.get("filter_counts", {}).items()}
    actionable = results.get("actionable", pd.DataFrame())

    out_rows = []
    if not actionable.empty:
        for ticker, row in actionable.iterrows():
            out_rows.append({
                "ticker": str(ticker),
                "close":      round(float(row.get("close", 0)), 2),
                "atr_14":     round(float(row.get("atr_14", 0)), 3),
                "williams_r": round(float(row.get("williams_r_14", 0)), 1),
                "adv_20_cr":  round(float(row.get("adv_20", 0)) / 1e7, 2),
                "pass_squeeze":          bool(row.get("pass_squeeze", False)),
                "pass_oops":             bool(row.get("pass_oops", False)),
                "pass_oversold_uptrend": bool(row.get("pass_oversold_uptrend", False)),
                "pass_liquidity":        bool(row.get("pass_liquidity", False)),
            })

    scan_date = df.index.get_level_values("date").max()
    return {
        "scan_date":      scan_date.strftime("%Y-%m-%d"),
        "universe_size":  int(results.get("universe_size", 0)),
        "filter_counts":  filter_counts,
        "combined_pass":  int(results.get("combined_pass_count", len(out_rows))),
        "results":        out_rows,
    }


# ── Cycle scan: read cached CSV ───────────────────────────────────────────────

@router.get("/scan-results")
async def get_scan_results(top_n: int = 50):
    """Return cached cycle-scanner results from last run."""
    if not SCAN_CSV.exists():
        return {"status": "no_data", "results": [], "last_run": None, "total": 0}

    try:
        df = pd.read_csv(SCAN_CSV).sort_values("composite_score", ascending=False).head(top_n)
        results = []
        for _, row in df.iterrows():
            results.append({
                "ticker":            str(row.get("ticker", "")),
                "composite_score":   round(float(row.get("composite_score", 0)), 4),
                "cycle_edge":        round(float(row.get("cycle_edge", 0)), 3),
                "cycle_pvalue":      round(float(row.get("cycle_pvalue", 1)), 4),
                "divergence_count":  int(row.get("divergence_count", 0)),
                "divergence_intensity": round(float(row.get("divergence_intensity", 0)), 3),
                "recent_divergence": bool(row.get("recent_divergence", False)),
                "failed_breakouts":  int(row.get("failed_breakouts", 0)),
                "failure_rate":      round(float(row.get("failure_rate", 0)), 4),
                "blast_off_signals": int(row.get("blast_off_signals", 0)),
                "momentum_strength": round(float(row.get("momentum_strength", 0)), 3),
                "is_active_momentum": bool(row.get("is_active_momentum", False)),
                "momentum_direction": round(float(row.get("momentum_direction", 0)), 2),
            })
        last_run = datetime.fromtimestamp(SCAN_CSV.stat().st_mtime).strftime("%Y-%m-%d %H:%M IST")
        return {"status": "ok", "results": results, "last_run": last_run, "total": len(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Cycle scan: background job ────────────────────────────────────────────────

async def _run_cycle_scan(job_id: str, n_stocks: int):
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from larry_williams_cycle_scanner import LarryWilliamsMasterScanner, ScannerConfig

        _jobs[job_id]["status"] = "loading_data"
        df_stocks, df_market = _load_ohlcv_flat(limit_days=400)

        # Limit to n_stocks to keep runtime reasonable
        tickers = list(df_stocks["ticker"].unique())[:n_stocks]
        df_stocks = df_stocks[df_stocks["ticker"].isin(tickers)].copy()

        _jobs[job_id].update({"status": "scanning", "total": len(tickers)})

        config = ScannerConfig(n_stocks=len(tickers), n_days=400)
        scanner = LarryWilliamsMasterScanner(config)
        results_df = scanner.scan_all_stocks(df_stocks, df_market)

        results_df.to_csv(str(SCAN_CSV), index=False)

        _jobs[job_id].update({
            "status":       "done",
            "progress":     len(tickers),
            "elapsed_secs": (datetime.now() - _jobs[job_id]["start_time"]).total_seconds(),
        })
    except Exception as e:
        import traceback
        _jobs[job_id].update({
            "status": "error",
            "error":  f"{type(e).__name__}: {e}\n{traceback.format_exc()[-600:]}",
        })


@router.post("/run-cycle-scan")
async def trigger_cycle_scan(background_tasks: BackgroundTasks, n_stocks: int = 200):
    """Trigger a background cycle scan on real NSE OHLCV data."""
    # Reject if one is already running
    running = [j for j in _jobs.values() if j.get("status") in ("queued", "loading_data", "scanning")]
    if running:
        raise HTTPException(status_code=409, detail="A scan is already in progress")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status":     "queued",
        "progress":   0,
        "total":      n_stocks,
        "start_time": datetime.now(),
        "error":      None,
    }
    background_tasks.add_task(_run_cycle_scan, job_id, n_stocks)
    return {"job_id": job_id, "status": "queued", "n_stocks": n_stocks}


@router.get("/job/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    elapsed = (datetime.now() - job["start_time"]).total_seconds() if isinstance(job.get("start_time"), datetime) else 0.0
    return {
        "job_id":       job_id,
        "status":       job["status"],
        "progress":     job.get("progress", 0),
        "total":        job.get("total", 0),
        "elapsed_secs": round(elapsed, 1),
        "error":        job.get("error"),
    }


# ── OHLCV for interactive charting ───────────────────────────────────────────

@router.get("/ohlcv/{ticker}")
async def get_ticker_ohlcv(ticker: str, days: int = 120):
    """Return OHLCV candles for a ticker in lightweight-charts format (UNIX timestamp)."""
    import time as _time

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = con.execute(f"""
            SELECT date, open, high, low, close, volume
            FROM ohlcv
            WHERE ticker = ?
              AND date >= (SELECT MAX(date)::DATE - INTERVAL '{days} days' FROM ohlcv)
            ORDER BY date
        """, [ticker]).fetchall()
    finally:
        con.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No OHLCV data for {ticker}")

    candles = []
    for date, open_, high, low, close, volume in rows:
        # lightweight-charts requires UNIX timestamp (seconds) or 'YYYY-MM-DD' string
        if hasattr(date, "strftime"):
            ts = date.strftime("%Y-%m-%d")
        else:
            ts = str(date)[:10]
        candles.append({
            "time":   ts,
            "open":   round(float(open_),  2),
            "high":   round(float(high),   2),
            "low":    round(float(low),    2),
            "close":  round(float(close),  2),
            "volume": int(volume) if volume is not None else 0,
        })

    return {"ticker": ticker, "days": days, "candles": candles}
