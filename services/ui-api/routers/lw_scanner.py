"""Larry Williams Cycle Scanner & Volatility Breakout Screener — UI API router."""
from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import os

import duckdb
import httpx
import pandas as pd
import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException

router = APIRouter()

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "market.duckdb")
DB_PATH     = os.getenv("DUCKDB_PATH", os.getenv("DATABASE_URL", _DEFAULT_DB))
DATA_DIR    = Path(DB_PATH).parent
DATA_SVC    = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
SCAN_CSV    = DATA_DIR / "larry_williams_scan_results.csv"
_DEFAULT_SCRIPTS = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
SCRIPTS_DIR = Path(os.getenv("SCRIPTS_DIR", _DEFAULT_SCRIPTS))

_jobs: dict[str, dict] = {}


def _fetch_ohlcv_bulk(days: int) -> pd.DataFrame:
    """Fetch recent OHLCV from data-service over HTTP.

    ui-api must NOT open its own DuckDB connection: on Docker Desktop (Mac,
    virtioFS) a second connection fails with "Conflicting lock is held in PID 0"
    even read-only. data-service owns the lock and serves /db/ohlcv-bulk.
    """
    fetch_days = max(int(days) + 30, 60)  # headroom for the last-complete-day trim
    with httpx.Client(timeout=httpx.Timeout(120.0)) as client:
        r = client.get(f"{DATA_SVC}/db/ohlcv-bulk", params={"days": fetch_days})
    r.raise_for_status()
    data = r.json().get("data", [])
    cols = ["ticker", "date", "open", "high", "low", "close", "volume"]
    if not data:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    return df[cols]


def _last_complete_date_from_df(df: pd.DataFrame, min_tickers: int = 100) -> pd.Timestamp:
    """Most recent date with ≥ min_tickers rows (guards against partial days)."""
    if df.empty:
        return pd.Timestamp("2020-01-01")
    counts = df.groupby("date")["ticker"].nunique().sort_index(ascending=False)
    for d, n in counts.items():
        if n >= min_tickers:
            return d
    return counts.index[0]


def _load_ohlcv_flat(limit_days: int = 400) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load OHLCV via data-service; returns (df_stocks, df_market_proxy)."""
    df = _fetch_ohlcv_bulk(limit_days)
    if df.empty:
        return df, df
    last_full = _last_complete_date_from_df(df)
    lo = last_full - pd.Timedelta(days=limit_days)
    df = df[(df["date"] >= lo) & (df["date"] <= last_full)].copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

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
    """Load OHLCV as MultiIndex (date, ticker) for the screener, trimmed to the
    last complete trading day to avoid partial-day distortion.
    """
    df = _fetch_ohlcv_bulk(days)
    if df.empty:
        return df.set_index(["date", "ticker"])
    last_full = _last_complete_date_from_df(df)
    lo = last_full - pd.Timedelta(days=days)
    df = df[(df["date"] >= lo) & (df["date"] <= last_full)]
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

    # Build per-filter Series so we can build the relaxed union output
    # The screener's `screen()` requires ALL 4 to pass, which is too strict.
    # We override: show stocks passing LIQUIDITY AND at least one signal filter.
    last_date = df.index.get_level_values("date").max()
    try:
        f_squeeze  = screener.filter_the_squeeze().loc[last_date]
        f_oops     = screener.filter_oops_reversal().loc[last_date]
        f_oversold = screener.filter_extreme_oversold_uptrend().loc[last_date]
        f_liquid   = screener.filter_liquidity().loc[last_date]
        any_signal = f_squeeze | f_oops | f_oversold
        passes_any = f_liquid & any_signal
        today_data = df.loc[last_date].copy()
        actionable = today_data[passes_any].copy()
        actionable["pass_squeeze"]          = f_squeeze[passes_any]
        actionable["pass_oops"]             = f_oops[passes_any]
        actionable["pass_oversold_uptrend"] = f_oversold[passes_any]
        actionable["pass_liquidity"]        = f_liquid[passes_any]
    except Exception:
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
    """Return OHLCV candles for a ticker in lightweight-charts format.

    Sourced from data-service /ohlcv/{ticker} over HTTP — ui-api never opens its
    own DuckDB connection (the virtioFS concurrent-lock made this 500 for every
    ticker: "Failed to load OHLCV").
    """
    from datetime import date as _date, timedelta as _td

    start = (_date.today() - _td(days=int(days) + 10)).isoformat()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/ohlcv/{ticker}", params={"start": start})
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"No OHLCV data for {ticker}")
        r.raise_for_status()
        rows = r.json().get("data", [])
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"data-service unreachable: {exc}")

    if not rows:
        raise HTTPException(status_code=404, detail=f"No OHLCV data for {ticker}")

    candles = []
    for row in rows:
        try:
            candles.append({
                "time":   str(row.get("date"))[:10],   # lightweight-charts wants YYYY-MM-DD
                "open":   round(float(row["open"]),  2),
                "high":   round(float(row["high"]),  2),
                "low":    round(float(row["low"]),   2),
                "close":  round(float(row["close"]), 2),
                "volume": int(row["volume"]) if row.get("volume") is not None else 0,
            })
        except (KeyError, TypeError, ValueError):
            continue

    return {"ticker": ticker, "days": days, "candles": candles}
