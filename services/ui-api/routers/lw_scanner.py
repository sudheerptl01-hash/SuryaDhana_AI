"""Larry Williams Cycle Scanner & Volatility Breakout Screener — UI API router.

Honesty (5 Nov 2026 review, M24 / m088): the cycle scan ranks the universe by liquidity (median traded value over the
last 60 sessions) instead of taking the first N tickers in alphabetical order; a scan reports its data date, how many
sessions old it is and STALE once it is more than one session behind; ACTIVE flags older than their horizon are
withheld (kept as `active_at_scan`); the per-stock calendar p-values carry a Benjamini–Hochberg q-value across every
test in the scan, with the number of tests and the false positives chance alone would give. The scores are
heuristics (badge), and the related swing study FAILS after costs.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
import os

import duckdb
import httpx
import pandas as pd
import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException

import bulk_cache
from errors import fail

router = APIRouter()

_DEFAULT_DB = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "market.duckdb")
DB_PATH     = os.getenv("DUCKDB_PATH", os.getenv("DATABASE_URL", _DEFAULT_DB))
DATA_DIR    = Path(DB_PATH).parent
DATA_SVC    = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
SCAN_CSV    = DATA_DIR / "larry_williams_scan_results.csv"
SCAN_META   = DATA_DIR / "larry_williams_scan_meta.json"     # data date + universe rule of the CSV beside it
IST = timezone(timedelta(hours=5, minutes=30))
LIQUIDITY_SESSIONS = 60          # median traded value over this many sessions ranks the universe
ACTIVE_HORIZON_SESSIONS = 5      # an ACTIVE flag (a pattern in the scan's last 3 sessions) implies a ≤ 5-session hold
STALE_AFTER_SESSIONS = 1         # a scan more than one session behind the last close is STALE
FDR_Q = 0.05
_DEFAULT_SCRIPTS = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
SCRIPTS_DIR = Path(os.getenv("SCRIPTS_DIR", _DEFAULT_SCRIPTS))

_jobs: dict[str, dict] = {}


_BULK_COLS = ["ticker", "date", "open", "high", "low", "close", "volume"]


def _fetch_ohlcv_bulk(days: int) -> pd.DataFrame:
    """Fetch recent OHLCV via the shared 60 s bulk cache (bulk_cache.py — D3 fix).

    ui-api must NOT open its own DuckDB connection: on Docker Desktop (Mac,
    virtioFS) a second connection fails with "Conflicting lock is held in PID 0"
    even read-only. data-service owns the lock and serves /db/ohlcv-bulk; the
    cache holds ONE parsed frame per (days, equity_only) key for 60 s so repeat
    screens stop re-pulling the ~84 MB payload. httpx errors propagate as before
    (the screener maps them to its 503). Downstream only mask-selects (which
    copies) before mutating — the cached frame is never written to.
    """
    fetch_days = max(int(days) + 30, 60)  # headroom for the last-complete-day trim
    # Operating companies only — ETFs / liquid funds are not breakout candidates.
    df = bulk_cache.get_bulk_ohlcv(fetch_days, equity_only=True)
    if df.empty:
        return pd.DataFrame(columns=_BULK_COLS)
    return df[_BULK_COLS]


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

# Sync handlers on purpose: they use a blocking HTTP client and seconds of pandas work;
# as `async def` they froze ui-api's event loop (every other UI request queued behind
# them). FastAPI runs plain `def` handlers — and BackgroundTasks — in a threadpool.
@router.get("/screener")
def run_screener(days: int = 500):
    """Run LW Volatility Breakout Screener on real NSE OHLCV data."""
    if days < 1:  # D7: days=-3 used to come back as a FALSE 404 "No OHLCV data in DuckDB"
        fail(422, "invalid", f"days must be >= 1 (got {days})")
    if days > 2000:  # C2 E1: unbounded days = unclamped full-panel pull + cache churn
        fail(422, "invalid", f"days must be <= 2000 (got {days})")
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from larry_williams_screener import VolatilityBreakoutScreener, ScreenerConfig
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Screener script not found: {e}")

    try:
        df = _load_ohlcv_multiindex(days)
    except httpx.HTTPStatusError as e:  # no internal URL on the wire (httpx reprs embed it)
        raise HTTPException(status_code=503, detail=f"DB load failed: data-service returned {e.response.status_code}")
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


# ── Cycle scan honesty helpers (pure) ─────────────────────────────────────────

def rank_by_liquidity(df: pd.DataFrame, n: int, sessions: int = LIQUIDITY_SESSIONS) -> list[str]:
    """The `n` most liquid tickers: median daily traded value (close × volume) over each ticker's last `sessions` bars,
    ties broken by ticker. Replaces `unique()[:n]`, which took 3MINDIA…BOROLTD only (M24)."""
    if df.empty or n <= 0:
        return []
    d = df.sort_values(["ticker", "date"])
    tv = (d["close"].astype(float) * d["volume"].astype(float)).rename("tv")
    recent = d.assign(tv=tv).groupby("ticker", sort=False).tail(sessions)
    med = recent.groupby("ticker")["tv"].median().fillna(0.0)
    ranked = sorted(med.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[:n]]


def bh_qvalues(pvalues: list[float]) -> list[float]:
    """Benjamini–Hochberg adjusted p-values (q-values), same order as the input. NaN p-values stay NaN."""
    p = np.asarray(pvalues, dtype=float)
    out = np.full(p.shape, np.nan)
    ok = np.isfinite(p)
    m = int(ok.sum())
    if m == 0:
        return out.tolist()
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx], kind="mergesort")]
    ranked = p[order] * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out[order] = np.minimum(q, 1.0)
    return out.tolist()


def last_close_session(now: datetime) -> date:
    """The last weekday session that has closed by `now` (IST, 15:30 close). NSE holidays are not modelled here, so
    session counts are weekdays: at most a holiday or two off, never enough to hide a three-week-old scan."""
    n = now.astimezone(IST)
    d = n.date() if n.time() >= time(15, 30) else n.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def sessions_between(a: date, b: date) -> int:
    """Weekday sessions strictly after `a` up to and including `b` (0 when b ≤ a)."""
    if b <= a:
        return 0
    return int(np.busday_count(a + timedelta(days=1), b + timedelta(days=1)))


def scan_as_of(meta: dict[str, Any] | None, run_at: datetime) -> tuple[date, str]:
    """The data date of a scan: the meta file's last bar when the scan wrote one, else the last session closed at the
    time the file was written (the CSV of 15 Oct 03:52 holds data to 14 Oct)."""
    if meta and meta.get("as_of"):
        try:
            return date.fromisoformat(str(meta["as_of"])[:10]), "scan"
        except ValueError:
            pass
    return last_close_session(run_at), "file time"


# ── Cycle scan: read cached CSV ───────────────────────────────────────────────

@router.get("/scan-results")
def get_scan_results(top_n: int = 50):
    """Return cached cycle-scanner results from last run, dated, with its staleness and FDR-adjusted p-values."""
    return scan_results_payload(top_n)


def scan_results_payload(top_n: int = 50, now: Optional[datetime] = None) -> dict[str, Any]:
    if not SCAN_CSV.exists():
        return {"status": "no_data", "results": [], "last_run": None, "total": 0}

    try:
        full = pd.read_csv(SCAN_CSV)
        n_tests = int(full["cycle_pvalue"].notna().sum()) if "cycle_pvalue" in full else 0
        if "cycle_pvalue" in full:
            full["cycle_qvalue"] = bh_qvalues(full["cycle_pvalue"].tolist())
        meta: dict[str, Any] | None = None
        try:
            meta = json.loads(SCAN_META.read_text()) if SCAN_META.exists() else None
        except (OSError, ValueError):
            meta = None
        run_at = datetime.fromtimestamp(SCAN_CSV.stat().st_mtime, tz=IST)
        as_of, as_of_source = scan_as_of(meta, run_at)
        last_close = last_close_session(now or datetime.now(IST))
        behind = sessions_between(as_of, last_close)
        stale = behind > STALE_AFTER_SESSIONS
        flags_expired = behind > ACTIVE_HORIZON_SESSIONS
        df = full.sort_values("composite_score", ascending=False).head(top_n)
        results = []
        for _, row in df.iterrows():
            q = row.get("cycle_qvalue")
            active_at_scan = bool(row.get("is_active_momentum", False))
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
                # an ACTIVE flag older than its horizon is withheld: it described the scan's last 3 sessions
                "is_active_momentum": active_at_scan and not flags_expired,
                "active_at_scan":     active_at_scan,
                "momentum_direction": round(float(row.get("momentum_direction", 0)), 2),
                "cycle_qvalue":       round(float(q), 4) if q is not None and np.isfinite(q) else None,
                "cycle_significant_fdr": bool(q is not None and np.isfinite(q) and q < FDR_Q),
            })
        universe = (meta or {}).get("universe") or "the first N tickers in alphabetical order (scan written before 6 Nov 2026)"
        return {
            "status": "ok", "results": results, "total": len(df),
            "last_run": run_at.strftime("%Y-%m-%d %H:%M IST"),
            "as_of": as_of.isoformat(), "as_of_source": as_of_source,
            "last_close": last_close.isoformat(), "sessions_behind": behind,
            "stale": stale, "active_flags_expired": flags_expired, "active_horizon_sessions": ACTIVE_HORIZON_SESSIONS,
            "universe": universe, "n_stocks": int(len(full)),
            "multiple_testing": {"method": "Benjamini–Hochberg", "q": FDR_Q, "n_tests": n_tests,
                                 "expected_false_positives_at_p05": round(n_tests * 0.05, 1),
                                 "raw_p_below_05": int((full.get("cycle_pvalue", pd.Series(dtype=float)) < 0.05).sum()),
                                 "significant_after_fdr": int((full.get("cycle_qvalue", pd.Series(dtype=float)) < FDR_Q).sum())},
            "badge": "heuristic",
            "verdict": {"verdict": "FAIL", "report": "reports/handbook_swing/REPORT.md",
                        "note": "Equal-weight pattern scores are a house heuristic; the related rules-only swing system "
                                "FAILS after ICICI costs. Describes, does not predict."},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Cycle scan: background job ────────────────────────────────────────────────

def _run_cycle_scan(job_id: str, n_stocks: int):
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from larry_williams_cycle_scanner import LarryWilliamsMasterScanner, ScannerConfig

        _jobs[job_id]["status"] = "loading_data"
        df_stocks, df_market = _load_ohlcv_flat(limit_days=400)

        # Limit to the n_stocks MOST LIQUID names (median traded value, last 60 sessions), not the first n
        # alphabetically (M24: the old cut only ever reached 3MINDIA…BOROLTD)
        tickers = rank_by_liquidity(df_stocks, n_stocks)
        df_stocks = df_stocks[df_stocks["ticker"].isin(tickers)].copy()
        as_of = str(pd.Timestamp(df_stocks["date"].max()).date()) if len(df_stocks) else None

        _jobs[job_id].update({"status": "scanning", "total": len(tickers)})

        config = ScannerConfig(n_stocks=len(tickers), n_days=400)
        scanner = LarryWilliamsMasterScanner(config)
        results_df = scanner.scan_all_stocks(df_stocks, df_market)

        results_df.to_csv(str(SCAN_CSV), index=False)
        try:
            SCAN_META.write_text(json.dumps({
                "as_of": as_of, "n_stocks": len(tickers), "run_at": datetime.now(IST).isoformat(timespec="seconds"),
                "universe": f"the {len(tickers)} most liquid NSE equities (median traded value over the last "
                            f"{LIQUIDITY_SESSIONS} sessions)"}))
        except OSError:
            pass

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


# The restart freeze windows (CLAUDE.md): the ICICI login + pre-open jobs and the EOD pipeline need the CPU and the
# DuckDB lock; a full-panel scan waits for an explicit confirm inside them.
FREEZE_WINDOWS_IST = ((time(7, 45), time(9, 20)), (time(18, 30), time(21, 15)))


def in_freeze_window(now: datetime) -> bool:
    t = now.astimezone(IST).time()
    return any(lo <= t < hi for lo, hi in FREEZE_WINDOWS_IST)


@router.post("/run-cycle-scan")
async def trigger_cycle_scan(background_tasks: BackgroundTasks, n_stocks: int = 200, confirm: bool = False):
    """Trigger a background cycle scan on real NSE OHLCV data (the most liquid `n_stocks`). Inside a freeze window it
    answers 409 unless `confirm=true`."""
    if in_freeze_window(datetime.now(IST)) and not confirm:
        raise HTTPException(status_code=409, detail="Inside a freeze window (07:45–09:20 / 18:30–21:15 IST): the scan "
                                                    "loads the full panel. Run it later, or confirm to run it now.")
    if not 20 <= n_stocks <= 1500:
        raise HTTPException(status_code=422, detail=f"n_stocks must be 20–1500 (got {n_stocks})")
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
