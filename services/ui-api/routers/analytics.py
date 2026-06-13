"""
Analytics — institutional Backtest Lab.

Capital-managed, friction-aware, risk-controlled historical simulation over the
DuckDB OHLCV + fundamentals tables. The deterministic math lives in
`backtest_engine` (unit-tested); this module owns DuckDB I/O, request contracts,
the synchronous endpoints, and an NDJSON streaming endpoint for live progress.

MODE = PAPER at all times — nothing here places an order.
"""
import asyncio
import itertools
import json
import os
import queue
import shutil
import threading
import time
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from typing import Callable, Optional

import duckdb
import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import backtest_engine as be
import factor_decile_engine as fde
import db
from db import get_conn

router = APIRouter()

MODE = "PAPER"

DATA_SVC = os.getenv("DATA_SERVICE_URL", "http://data-service:8001")

# Analytics reads off an isolated snapshot when data-service holds the live
# write-lock (DuckDB is single-writer; on Docker Desktop/virtioFS a cross-process
# reader is rejected). A read replica is the standard pattern for serving
# analytics off a write-busy OLTP store.
_SNAPSHOT = "/tmp/bt_snapshot.duckdb"
_SNAPSHOT_TTL = 600  # seconds


def _ensure_snapshot() -> str:
    src = db.DB_PATH
    stale = (not os.path.exists(_SNAPSHOT)) or (time.time() - os.path.getmtime(_SNAPSHOT) > _SNAPSHOT_TTL)
    if stale:
        tmp = f"{_SNAPSHOT}.{os.getpid()}.tmp"
        shutil.copy2(src, tmp)
        os.replace(tmp, _SNAPSHOT)
    return _SNAPSHOT


def _acquire_readonly(progress) -> tuple[duckdb.DuckDBPyConnection, bool]:
    """
    Return (connection, owns) for read-only analytics.
    Fast path: the shared read-only handle when ui-api owns the read lock.
    Fallback: an isolated snapshot copy when the live DB is write-locked.
    `owns=True` means the caller must close the connection.
    """
    try:
        with get_conn() as c:
            cur = c.cursor()
            if cur.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0] > 0:
                return cur, False
    except Exception:
        pass
    progress(7, "Preparing isolated data snapshot")
    last = None
    for _ in range(2):
        try:
            return duckdb.connect(_ensure_snapshot(), read_only=True), True
        except Exception as exc:  # torn copy → drop + retry once
            last = exc
            try:
                os.remove(_SNAPSHOT)
            except OSError:
                pass
    raise HTTPException(status_code=503, detail=f"Market database busy; snapshot unavailable: {last}")
BENCHMARK_LABEL = "Nifty-50 proxy (top-100 mkt-cap, equal-weight)"

# Mandatory friction floor — CLAUDE.md: never account for < 0.15% round-trip cost.
# Enforced server-side so a tampered/legacy client payload can't model a fee-free
# fantasy. 15 bps = 0.15%.
MIN_FRICTION_BPS = 15.0

# Ticker → sector map for trade-level sector tagging (the blotter's sector grouping).
# stock_metrics carries no sector column, so it is resolved from the locked universe
# CSV (data/NSE_1500.csv). Loaded once and cached for the process lifetime.
_SECTOR_MAP: Optional[dict[str, str]] = None


def _sector_map() -> dict[str, str]:
    global _SECTOR_MAP
    if _SECTOR_MAP is not None:
        return _SECTOR_MAP
    candidates = [
        os.getenv("STOCK_UNIVERSE_PATH", ""),
        "/app/data/NSE_1500.csv",
        os.path.join(os.path.dirname(getattr(db, "DB_PATH", "")), "NSE_1500.csv") if getattr(db, "DB_PATH", "") else "",
    ]
    mapping: dict[str, str] = {}
    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            udf = pd.read_csv(path, usecols=["ticker", "sector"])
            for t, s in zip(udf["ticker"], udf["sector"]):
                if isinstance(t, str):
                    mapping[t.upper()] = s.strip() if isinstance(s, str) and s.strip() else "Unknown"
            break
        except Exception:
            continue
    _SECTOR_MAP = mapping
    return mapping


# ── G2: as-of index membership + delisting (survivorship control) ─────────────────
#
# A backtest restricted to *today's* index constituents is survivorship-biased: it
# only ever sees the names that made it to the present, silently dropping every
# stock that was delisted, acquired, or relegated out of the index along the way.
# These helpers resolve membership AS OF each bar and surface delisting returns so a
# dead name actually exits the book. Both degrade gracefully: when the optional
# `index_membership` / `delistings` tables are absent (the current DuckDB), the loader
# falls back to the full traded universe and flags `membership_pit=False`, so behaviour
# is unchanged until the historical tables are backfilled.

def _table_exists(con, name: str) -> bool:
    try:
        return con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1", [name]
        ).fetchone() is not None
    except Exception:
        return False


def _load_membership_intervals(con, index_name: Optional[str]):
    """Return a sorted membership panel [ticker, effective_from, effective_to] or None.

    `effective_to` NULL ⇒ still a member (mapped to +∞). None is returned when the
    table is absent or empty so callers stay on the survivorship-biased full-universe
    path explicitly (never silently)."""
    if not _table_exists(con, "index_membership"):
        return None
    try:
        rows = con.execute(
            """SELECT ticker, effective_from, effective_to FROM index_membership
               WHERE (? IS NULL OR index_name = ?)""",
            [index_name, index_name],
        ).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    mem = pd.DataFrame(rows, columns=["ticker", "effective_from", "effective_to"])
    mem["ticker"] = mem["ticker"].astype(str).str.upper()
    mem["effective_from"] = pd.to_datetime(mem["effective_from"], errors="coerce")
    mem["effective_to"] = pd.to_datetime(mem["effective_to"], errors="coerce").fillna(pd.Timestamp.max)
    mem = mem.dropna(subset=["effective_from"]).sort_values(["ticker", "effective_from"])
    return mem if len(mem) else None


def _attach_membership(df: pd.DataFrame, mem: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Mark each (ticker, date) row with whether the name was an index member on that
    bar. Vectorised as-of join: the last interval opened on/before the bar is active,
    and the bar must precede that interval's close. Absent table ⇒ all True (full
    universe, survivorship-biased) with `membership_pit=False`."""
    if mem is None:
        df["index_member"] = True
        df.attrs["membership_pit"] = False
        return df
    left = df.sort_values("date")[["ticker", "date"]].copy()
    left["ticker"] = left["ticker"].astype(str).str.upper()
    # merge_asof requires the `on` key sorted globally on BOTH sides (not just within `by`).
    right = (mem.rename(columns={"effective_from": "date"})[["ticker", "date", "effective_to"]]
                .sort_values("date"))
    joined = pd.merge_asof(left, right, on="date", by="ticker", direction="backward")
    member = joined["effective_to"].notna() & (joined["date"] < joined["effective_to"])
    df["index_member"] = member.to_numpy()
    df.attrs["membership_pit"] = True
    return df


def _delisting_map(con) -> dict[str, tuple]:
    """{TICKER → (delist_date: Timestamp, delist_return_pct: float)} from the optional
    `delistings` table (or `corporate_events` rows tagged 'delisting'/'acquired').
    A missing `delist_return_pct` defaults to −100% (full wipe-out — the conservative
    survivorship penalty). Empty dict when no source exists."""
    out: dict[str, tuple] = {}
    if _table_exists(con, "delistings"):
        try:
            rows = con.execute(
                "SELECT ticker, delist_date, delist_return_pct FROM delistings WHERE ticker IS NOT NULL"
            ).fetchall()
            for tkr, d, r in rows:
                ts = pd.to_datetime(d, errors="coerce")
                if pd.isna(ts):
                    continue
                out[str(tkr).upper()] = (ts, float(r) if r is not None else -100.0)
        except Exception:
            pass
    if not out and _table_exists(con, "corporate_events"):
        try:
            rows = con.execute(
                """SELECT ticker, event_date FROM corporate_events
                   WHERE LOWER(event_type) IN ('delisting','delisted','acquired','merger')
                   AND ticker IS NOT NULL"""
            ).fetchall()
            for tkr, d in rows:
                ts = pd.to_datetime(d, errors="coerce")
                if pd.isna(ts):
                    continue
                out[str(tkr).upper()] = (ts, -100.0)
        except Exception:
            pass
    return out


class FilterCondition(BaseModel):
    field: str
    op: str = "gt"      # lt | gt | lte | gte
    value: float = 0.0


FILTER_CATALOG = {
    "pe_ratio": {"category": "Valuation", "label": "P/E Ratio", "unit": "x", "desc": "Price-to-earnings ratio", "fundamental": True},
    "div_yld_pct": {"category": "Valuation", "label": "Dividend Yield", "unit": "%", "desc": "Annual dividend / price", "fundamental": True},
    "mktcap_cr": {"category": "Valuation", "label": "Market Cap", "unit": "Cr", "desc": "Market capitalization", "fundamental": True},
    "roce_pct": {"category": "Quality", "label": "ROCE", "unit": "%", "desc": "Return on capital employed", "fundamental": True},
    "price_gt_ma50": {"category": "Technical", "label": "Price > 50-day MA", "unit": "", "desc": "Above short-term trend", "fundamental": False},
    "price_gt_ma200": {"category": "Technical", "label": "Price > 200-day MA", "unit": "", "desc": "Above long-term trend", "fundamental": False},
    "ma50_gt_ma200": {"category": "Technical", "label": "50-day MA > 200-day MA", "unit": "", "desc": "Golden cross", "fundamental": False},
    "rsi_14": {"category": "Technical", "label": "RSI (14)", "unit": "0-100", "desc": "Oversold <30, overbought >70", "fundamental": False},
    "atr_14_pct": {"category": "Technical", "label": "ATR % (14)", "unit": "%", "desc": "Volatility (% of close)", "fundamental": False},
    "above_52w_low_pct": {"category": "Volatility", "label": "% above 52-week Low", "unit": "%", "desc": "Bounce strength", "fundamental": False},
    "within_52w_high_pct": {"category": "Volatility", "label": "% within 52-week High", "unit": "%", "desc": "Nearness to yearly peak", "fundamental": False},
    "dist_ma200_pct": {"category": "Volatility", "label": "Distance from 200-day MA", "unit": "%", "desc": "Overbought/oversold", "fundamental": False},
    "volume_gt_avg": {"category": "Volume", "label": "Volume > 20-day Avg", "unit": "", "desc": "Accumulation", "fundamental": False},
    # ── Advanced alpha factors (Pillar 1) — all strictly trailing, zero look-ahead ──
    "vmi_ratio": {"category": "Microstructure", "label": "Volume Market Impact (VMI)", "unit": "x", "desc": "Dollar-volume vs 20d avg, vol-normalized", "fundamental": False},
    "vol_zscore_20": {"category": "Microstructure", "label": "Volume Thrust z-score", "unit": "σ", "desc": "Volume vs prior-20d baseline (VIPT core)", "fundamental": False},
    "vipt_breakout": {"category": "Microstructure", "label": "VIPT Breakout", "unit": "", "desc": "20d range breakout on >3σ volume", "fundamental": False},
    "intraday_intention": {"category": "Microstructure", "label": "Intraday Intention", "unit": "0-1", "desc": "3-day aggregated close-location value", "fundamental": False},
    "intention_pullback": {"category": "Microstructure", "label": "Intention on Pullback", "unit": "", "desc": "CLV>0.8 through a 3-day dip", "fundamental": False},
    "squeeze_ratio": {"category": "Volatility", "label": "Squeeze Ratio (BB/KC)", "unit": "x", "desc": "Bollinger width / Keltner width (<1 ⇒ squeeze)", "fundamental": False},
    "squeeze_on": {"category": "Volatility", "label": "Squeeze ON", "unit": "", "desc": "Bollinger Bands inside Keltner Channels", "fundamental": False},
    "sector_rel_mom_14_pct": {"category": "Relative Strength", "label": "Sector-Relative Momentum (14d)", "unit": "%", "desc": "14d return minus sector composite", "fundamental": False},
    "sector_positive_regime": {"category": "Relative Strength", "label": "Positive Sector Regime", "unit": "", "desc": "Sector composite 14d momentum > 0", "fundamental": False},
    "corr_nifty_30": {"category": "Relative Strength", "label": "Market Correlation (30d)", "unit": "ρ", "desc": "Rolling 30d Pearson corr to market", "fundamental": False},
    "decoupled_leader": {"category": "Relative Strength", "label": "De-coupled Leader", "unit": "", "desc": "Low corr in a market pullback, holding up", "fundamental": False},
}


@router.get("/filters")
async def get_filter_catalog():
    return FILTER_CATALOG


# ── Request contracts (all new params have safe defaults → never crashes on load) ─

class BacktestRequest(BaseModel):
    from_date: str
    to_date: str
    forward_days: int = 5
    win_threshold: float = 0.0
    filters: list[FilterCondition] = []
    max_stocks_per_day: int = 50
    # Pillar 1 — friction + risk + capital
    starting_capital: float = 10_000_000.0
    friction_bps: float = 15.0           # round-trip cost, basis points (0.15%)
    stop_loss_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    max_positions: int = 5
    max_drawdown_halt_pct: Optional[float] = None   # circuit breaker: halt new entries past this DD
    # Pillar 2 — scoping
    scope: str = "universe"              # "universe" | "watchlist"
    tickers: list[str] = []
    # Fidelity
    entry_timing: str = "next_open"      # "next_open" (no same-bar look-ahead) | "close"
    # Advanced risk sizing (opt-in; all None/False ⇒ identical to plain equal-weight)
    atr_stop_mult: Optional[float] = None    # per-trade stop = k × signal-day ATR%
    vol_target_pct: Optional[float] = None   # volatility-target position sizing
    max_position_pct: Optional[float] = None  # hard per-position cap (% of NAV)
    max_sector_pct: Optional[float] = None    # per-sector exposure cap (% of NAV)
    regime_filter: bool = False               # enable market-regime exposure control
    regime_model: str = "sma"                 # "sma" (benchmark MA) | "hmm" (2-state Gaussian HMM)
    regime_mode: str = "gate"                 # "gate" (hard on/off) | "soft" (P(bull) throttle)
    max_participation_pct: Optional[float] = None  # ADV cap: fill ≤ this % of avg daily $ vol
    impact_coef: Optional[float] = None       # vol-scaled √-law market impact (≈1 typical; None ⇒ off)
    # Candidate selection: "mktcap" (size tilt, default) | "sector_neutral" (within-sector
    # z-score of `selection_factor` → removes the unhedged size/beta bet; G6)
    selection: str = "mktcap"
    selection_factor: str = "dist_ma200_pct"
    amihud_coef: Optional[float] = None       # endogenous Amihud/Kyle-λ permanent impact (None ⇒ off)
    kelly_fraction: Optional[float] = None     # fractional-Kelly sizing (0.5 = half-Kelly; None ⇒ equal-weight)
    allow_lookahead_fundamentals: bool = False # opt back into broadcast (non-PIT) fundamentals (G1)
    # As-of index membership + delisting (G2). `index_universe` restricts candidates to
    # the as-of constituents of that index (e.g. "NIFTY50"); None ⇒ any membership row.
    # `survivorship_adjust` applies terminal delisting returns to open positions. Both
    # are inert until the `index_membership` / `delistings` tables are backfilled.
    index_universe: Optional[str] = None
    survivorship_adjust: bool = True


class WFOBacktestRequest(BacktestRequest):
    """Real walk-forward optimization.

    Each rolling window optimizes a *filter combination* in-sample, freezes it,
    and measures it out-of-sample across an embargo gap that exceeds the holding
    horizon (so a trade opened near the in-sample edge cannot leak its forward
    label into the out-of-sample fold). The reported headline metrics are the
    *stitched out-of-sample* track record — not an in-sample fit.

    Search space: `candidate_filters` (falls back to the inherited `filters` when
    empty) are combined via itertools up to `max_combo_size`; `base_filters` are
    always applied on top of every candidate combination.
    """
    in_sample_days: int = 365            # rolling in-sample length (calendar days)
    out_sample_days: int = 90            # out-of-sample length per window
    embargo_days: int = 7                # IS→OOS gap; auto-raised to exceed the holding horizon
    monte_carlo_runs: int = 1000
    objective: str = "sharpe"            # sharpe | calmar | profit_factor | total_return
    candidate_filters: list[FilterCondition] = []   # search pool (defaults to `filters`)
    base_filters: list[FilterCondition] = []         # always-on screen applied to every combo
    max_combo_size: int = 3              # cap on simultaneously-active candidate filters
    min_is_trades: int = 20              # in-sample trade floor; below it a combo is not selectable


# ── DuckDB load + indicator prep ──────────────────────────────────────────────────

# Factors whose computation needs the (heavier) cross-sectional market/sector
# composites. Computed lazily so a vanilla technical backtest stays fast.
MARKET_RELATIVE_FIELDS: set[str] = {
    "sector_rel_mom_14_pct", "corr_nifty_30",
    "sector_positive_regime", "decoupled_leader",
}


def _load_prepared(con, from_dt, to_dt, forward_days: int, scope_tickers: Optional[list[str]],
                   need_market_relative: bool = False, allow_lookahead: bool = False,
                   index_name: Optional[str] = None):
    """Load OHLCV (+warm-up / forward look) and attach trailing indicators.

    `need_market_relative` gates the cross-sectional sector/market-coupling pass
    (rolling correlation over the whole frame) so it only runs when a filter or a
    factor profile actually references those columns.

    Fundamentals are joined **point-in-time** (G1): each bar T receives only the latest
    `stock_metrics` snapshot with `as_of_date ≤ T` via `merge_asof(direction="backward")`,
    so a 2026 P/E never lands on a 2021 bar. When the source has < 2 distinct as_of_dates
    (cannot be PIT) or `allow_lookahead=True`, it falls back to broadcasting the latest
    snapshot per ticker — flagged elsewhere via `fundamental_lookahead_active`.
    """
    lookback_dt = from_dt - timedelta(days=400)
    lookahead_dt = to_dt + timedelta(days=forward_days * 3 + 25)

    cols = "ticker, date, open, high, low, close, volume, adjusted_close"
    if scope_tickers:
        placeholders = ",".join(["?"] * len(scope_tickers))
        rows = con.execute(
            f"""SELECT {cols} FROM ohlcv
                WHERE date BETWEEN ? AND ? AND ticker IN ({placeholders})
                ORDER BY ticker, date""",
            [lookback_dt, lookahead_dt, *[t.upper() for t in scope_tickers]],
        ).fetchall()
    else:
        rows = con.execute(
            f"""SELECT {cols} FROM ohlcv
               WHERE date BETWEEN ? AND ? ORDER BY ticker, date""",
            [lookback_dt, lookahead_dt],
        ).fetchall()

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume", "adjusted_close"])
    df["date"] = pd.to_datetime(df["date"])
    # Split/dividend adjustment: scale OHLC onto the adjusted-close basis so returns
    # and indicators are corporate-action-consistent (no split-day jumps). Falls back
    # to raw prices when adjusted_close is missing.
    for c in ("open", "high", "low", "close", "adjusted_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    adj = (df["adjusted_close"] / df["close"]).where((df["close"] > 0) & df["adjusted_close"].notna(), 1.0)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c] * adj
    df = df.drop(columns=["adjusted_close"])
    df = be.compute_indicators(df)

    metrics_rows = con.execute(
        """SELECT ticker, as_of_date, pe_ratio, roce_pct, div_yld_pct, mktcap_cr FROM stock_metrics
           WHERE ticker IS NOT NULL"""
    ).fetchall()
    mdf = pd.DataFrame(metrics_rows,
                       columns=["ticker", "as_of_date", "pe_ratio", "roce_pct", "div_yld_pct", "mktcap_cr"])
    mdf["as_of_date"] = pd.to_datetime(mdf["as_of_date"], errors="coerce")
    n_asof = int(mdf["as_of_date"].dropna().nunique())
    fund_cols = ["pe_ratio", "roce_pct", "div_yld_pct", "mktcap_cr"]
    if n_asof >= 2 and not allow_lookahead:
        # Point-in-time: bar T ← latest snapshot with as_of_date ≤ T. No future leak.
        mdf = (mdf.dropna(subset=["as_of_date"]).sort_values(["as_of_date", "ticker"])
                  .drop_duplicates(subset=["ticker", "as_of_date"], keep="last")
                  .rename(columns={"as_of_date": "date"}))
        df = df.sort_values("date")
        df = pd.merge_asof(df, mdf[["ticker", "date", *fund_cols]], on="date", by="ticker",
                           direction="backward")
        df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
        pit_applied = True
    else:
        # Degenerate source (≤1 snapshot date) or explicit opt-in → broadcast the latest
        # per ticker. This is the look-ahead path (flagged via fundamental_lookahead_active);
        # drop_duplicates avoids fanning OHLCV rows into duplicate same-day candidates.
        mdf = mdf.sort_values("as_of_date", na_position="first").drop_duplicates(
            subset=["ticker"], keep="last").drop(columns=["as_of_date"])
        df = df.merge(mdf, on="ticker", how="left")
        pit_applied = False
    cov = pd.to_datetime(pd.Series(metrics_rows and [r[1] for r in metrics_rows]), errors="coerce").dropna()
    df.attrs["pit_fundamentals"] = pit_applied
    df.attrs["fund_coverage_start"] = str(cov.min().date()) if len(cov) else None

    # As-of index membership (G2): mark each bar in/out of the index so candidate
    # selection sees the universe as it was, not today's survivors. No-op (all True)
    # when the `index_membership` table is absent.
    df = _attach_membership(df, _load_membership_intervals(con, index_name))
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Attach reference-relative factors (sector momentum dispersion + market
    # coupling) only when requested. The market proxy is the equal-weight return of
    # the loaded constituents; sectors come from the locked-universe map. Both are
    # strictly trailing. Wrapped so a composite failure never breaks the core sim.
    if need_market_relative:
        try:
            df = be.compute_market_relative(df, _sector_map())
        except Exception:
            for col in ("sector_rel_mom_14_pct", "corr_nifty_30"):
                if col not in df.columns:
                    df[col] = np.nan
            for col in ("sector_positive_regime", "decoupled_leader"):
                if col not in df.columns:
                    df[col] = False
    return df


def _build_benchmark(con, from_ts, to_ts) -> tuple[dict[str, float], str]:
    """
    Daily benchmark returns. Prefers a real NIFTY series if it has been ingested
    into `ohlcv`; otherwise falls back to an equal-weight top-100-by-mkt-cap proxy.
    Returns (returns_by_date, source_label) so beta/alpha auto-upgrade when the
    actual index lands.
    """
    start, end = from_ts.date() - timedelta(days=7), to_ts.date()

    # 1) Real index, if present
    nifty_syms = ["NIFTY", "NIFTY50", "NSEI"]
    ph = ",".join(["?"] * len(nifty_syms))
    nrows = con.execute(
        f"SELECT date, close FROM ohlcv WHERE ticker IN ({ph}) AND date BETWEEN ? AND ? ORDER BY date",
        [*nifty_syms, start, end],
    ).fetchall()
    if len(nrows) > 5:
        ndf = pd.DataFrame(nrows, columns=["date", "close"]).sort_values("date")
        ndf["date"] = pd.to_datetime(ndf["date"])
        ndf["ret"] = ndf["close"].pct_change()
        daily = ndf.set_index("date")["ret"]
        return ({str(d.date()): (float(r) if pd.notna(r) else 0.0) for d, r in daily.items()},
                "NIFTY 50 (actual index)")

    # 2) Equal-weight top-100 proxy. Pick the 100 most-liquid names that ACTUALLY trade
    # in this window (avg dollar volume over [start,end]), not today's largest caps —
    # otherwise a historical window selects recently-listed mega-caps with no in-window
    # history and the proxy collapses to empty (silently killing beta/regime).
    top = con.execute(
        """SELECT ticker FROM ohlcv
           WHERE date BETWEEN ? AND ?
           GROUP BY ticker
           HAVING COUNT(*) >= 60
           ORDER BY AVG(close * volume) DESC
           LIMIT 100""",
        [start, end],
    ).fetchall()
    tickers = [r[0] for r in top]
    if not tickers:
        # Last-resort: today's largest caps (pre-coverage windows with sparse OHLCV).
        top = con.execute(
            "SELECT ticker FROM stock_metrics WHERE mktcap_cr IS NOT NULL ORDER BY mktcap_cr DESC LIMIT 100"
        ).fetchall()
        tickers = [r[0] for r in top]
    if not tickers:
        return {}, "none"
    placeholders = ",".join(["?"] * len(tickers))
    rows = con.execute(
        f"""SELECT date, ticker, close FROM ohlcv
            WHERE ticker IN ({placeholders}) AND date BETWEEN ? AND ? ORDER BY date""",
        [*tickers, start, end],
    ).fetchall()
    if not rows:
        return {}, "none"
    bdf = pd.DataFrame(rows, columns=["date", "ticker", "close"])
    bdf["date"] = pd.to_datetime(bdf["date"])
    bdf = bdf.sort_values(["ticker", "date"])
    bdf["ret"] = bdf.groupby("ticker")["close"].pct_change()
    daily = bdf.groupby("date")["ret"].mean()
    return ({str(d.date()): (float(r) if pd.notna(r) else 0.0) for d, r in daily.items()},
            BENCHMARK_LABEL)


# ── Core simulation (shared by sync + streaming + WFO) ────────────────────────────
#
# Architecture: the heavy DuckDB load + indicator prep + per-ticker chronological
# arrays are built ONCE into a `_SimContext`. A single backtest simulates one window
# over that context; the walk-forward optimizer simulates hundreds of windows over
# the *same* loaded context (in-memory) without ever re-reading the database. Exit
# resolution for a (signal-day, ticker) pair is independent of the filter set (it
# depends only on the fixed entry-timing / forward / stop / friction params), so it
# is memoised and shared across every candidate combination the optimizer evaluates.


class _SimContext:
    """Loaded-once market state for in-memory window simulation.

    Holds the full prepared frame's chronological arrays, the trading calendar,
    the benchmark, and a memoised (signal_gidx, ticker) → resolved-exit cache.
    """
    __slots__ = (
        "req", "all_dates", "date_to_gidx", "tkr_series", "bench_daily",
        "bench_source", "fund_as_of", "friction", "grouped", "grouped_keys",
        "n_tickers", "regime_ok", "regime_scale", "regime_meta",
        "factor_returns", "auto_impact", "fund_pit", "fund_cov_start",
        "membership_pit", "delist_by_ticker", "n_delistings", "_resolved",
        # C1/C2/C3 — at-scale auto-safeguard completes the cost stack: the permanent
        # Amihud/Kyle-λ leg, the physical ADV participation cap, and the per-name
        # temporary-leg coefficient. All None ⇒ retail scale / explicit-knob path.
        "auto_amihud", "auto_participation", "amihud_coef_map", "impact_coef_map",
    )

    def __init__(self, req, all_dates, date_to_gidx, tkr_series, bench_daily,
                 bench_source, fund_as_of, friction, grouped, grouped_keys, n_tickers,
                 regime_ok=None, factor_returns=None, auto_impact=None):
        self.req = req
        self.all_dates = all_dates
        self.date_to_gidx = date_to_gidx
        self.tkr_series = tkr_series
        self.bench_daily = bench_daily
        self.bench_source = bench_source
        self.fund_as_of = fund_as_of
        self.friction = friction
        self.grouped = grouped                 # [(date_key, day_df), ...] over [from, to]
        self.grouped_keys = grouped_keys        # [Timestamp, ...] aligned to grouped, sorted
        self.n_tickers = n_tickers
        self.regime_ok = regime_ok              # {date_str → bool} hard gate, else None
        self.regime_scale = None                # {date_str → P(bull)} HMM soft throttle, else None
        self.regime_meta = None                 # regime classifier metadata (model + HMM params)
        self.factor_returns = factor_returns    # date-indexed factor return panel (universe scope)
        self.auto_impact = auto_impact          # impact_coef auto-enabled at scale (G4), else None
        # C1/C2/C3 — completed at-scale safeguard (set by _calibrate_auto_impact, else None).
        self.auto_amihud = None                 # permanent Kyle-λ coefficient auto-enabled at scale
        self.auto_participation = None          # ADV participation cap (% of avg daily $ vol) auto-on
        self.amihud_coef_map = None             # {ticker → per-name Amihud λ} endogenous permanent coef
        self.impact_coef_map = None             # {ticker → per-name Y_i} endogenous temporary-leg coef (C2)
        self.fund_pit = False                   # whether fundamentals were joined point-in-time (G1)
        self.fund_cov_start = None              # earliest fundamental as_of_date (coverage start)
        self.membership_pit = False             # whether candidates were filtered as-of index membership (G2)
        self.delist_by_ticker = None            # {ticker → (delist_gidx, delist_return_pct)} survivorship adj (G2)
        self.n_delistings = 0                   # count of delisting events intersecting the window
        self._resolved: dict[tuple, Optional[dict]] = {}

    def price_at(self, idx: int, ticker: str) -> Optional[float]:
        s = self.tkr_series.get(ticker)
        if not s:
            return None
        return s["close_by_gidx"].get(int(idx))

    def resolve(self, sig: int, ticker: str) -> Optional[dict]:
        """Resolve a single (signal-day, ticker) into a fully-priced entry dict.

        Filter-independent → memoised so the WFO optimizer pays the exit-resolution
        cost once per pair even across hundreds of candidate combinations. Returns
        None when there is no entry bar + forward window available.
        """
        key = (sig, ticker)
        cached = self._resolved.get(key, _MISSING)
        if cached is not _MISSING:
            return cached
        req = self.req
        s = self.tkr_series.get(ticker)
        res: Optional[dict] = None
        if s is not None:
            lp_sig = s["gidx_to_lp"].get(int(sig))
            if lp_sig is not None:
                next_open = (req.entry_timing == "next_open")
                # next_open enters the bar AFTER the signal (no same-bar look-ahead);
                # "close" enters on the signal bar's close.
                entry_lp = lp_sig + 1 if next_open else lp_sig
                if entry_lp + 1 < len(s["close"]):   # need the entry bar + ≥1 forward bar
                    entry_price = float(s["open"][entry_lp]) if next_open else float(s["close"][entry_lp])
                    fwd = slice(entry_lp + 1, entry_lp + 1 + req.forward_days)
                    fwd_hi, fwd_lo, fwd_cl, fwd_op = s["high"][fwd], s["low"][fwd], s["close"][fwd], s["open"][fwd]
                    if len(fwd_cl) > 0:
                        # Per-trade stop: a k×ATR stop (from the signal-day ATR%) when
                        # `atr_stop_mult` is set, else the fixed `stop_loss_pct`. Both
                        # are req-level constants, so the resolved exit stays cacheable.
                        atr_pct_sig = s["atr_pct_by_gidx"].get(int(sig))
                        stop_pct = req.stop_loss_pct
                        mult = getattr(req, "atr_stop_mult", None)
                        if mult and atr_pct_sig and atr_pct_sig > 0:
                            stop_pct = float(mult) * float(atr_pct_sig)
                        ex = be.resolve_trade_exit(
                            fwd_hi, fwd_lo, fwd_cl, entry_price, req.forward_days,
                            friction_bps=self.friction, stop_loss_pct=stop_pct,
                            trailing_stop_pct=req.trailing_stop_pct, win_threshold=req.win_threshold,
                            opens=fwd_op,
                        )
                        entry_gidx = int(s["gidx"][entry_lp])
                        exit_gidx = int(s["gidx"][entry_lp + ex["holding_days"]])
                        res = {
                            "ticker": ticker,
                            "entry_price": round(entry_price, 4),
                            "exit_price": ex["exit_price"],
                            "exit_idx": exit_gidx,
                            "entry_gidx": entry_gidx,
                            "net_return_pct": ex["net_return_pct"],
                            "gross_return_pct": ex["gross_return_pct"],
                            "holding_days": ex["holding_days"],
                            "exit_reason": ex["exit_reason"],
                            "win_threshold": req.win_threshold,
                            "entry_date": str(self.all_dates[entry_gidx])[:10],
                            "exit_date": str(self.all_dates[exit_gidx])[:10],
                            # Risk-sizing inputs consumed by simulate_portfolio (opt-in gates)
                            "atr_pct": (float(atr_pct_sig) if atr_pct_sig is not None else None),
                            "adv": s["adv20_by_gidx"].get(int(sig)),
                            "amihud": s["amihud_by_gidx"].get(int(sig)),
                            "sector": _sector_map().get(str(ticker).upper(), "Unknown"),
                        }
        self._resolved[key] = res
        return res


_MISSING = object()


def _regime_by_date(bench_daily: dict, fast: int = 50, slow: int = 200) -> dict:
    """Market regime flag per date from the benchmark: risk-on when the benchmark
    level sits above its own `slow`-day SMA (a classic trend filter). Strictly
    trailing — day-T uses only returns up to and including T. Returns {date_str → bool};
    days before the SMA warms up default to risk-on (no suppression on cold start).
    """
    if not bench_daily:
        return {}
    s = pd.Series({pd.Timestamp(k): v for k, v in bench_daily.items()}).sort_index()
    level = (1.0 + s.fillna(0.0)).cumprod()
    sma = level.rolling(slow, min_periods=max(20, slow // 4)).mean()
    risk_on = (level >= sma)
    return {str(d.date()): (bool(v) if pd.notna(sma.loc[d]) else True)
            for d, v in risk_on.items()}


def _hmm_regime_by_date(bench_daily: dict):
    """Causal HMM P(bull|data≤t) per date from the benchmark daily returns.
    Returns ({date_str → P(bull)}, params) or None when the series is too short."""
    if not bench_daily:
        return None
    s = pd.Series({pd.Timestamp(k): v for k, v in bench_daily.items()}).sort_index()
    res = be.gaussian_hmm_regime(s.to_numpy(dtype=float))
    if res is None:
        return None
    p_bull, params = res
    return ({str(d.date()): float(p) for d, p in zip(s.index, p_bull)}, params)


# ── C1/C2/C3 — at-scale auto-impact calibration ──────────────────────────────────
# The prior G4 auto-path enabled only the temporary √-law leg with a flat global
# coefficient (1.0) and left the permanent Amihud/Kyle-λ leg and the physical ADV
# participation cap OFF — so a billionaire-tier run filled 100%+ of a name's ADV in one
# bar and was charged the cheapest third of the true cost. This module completes the
# stack: under the SAME `per_pos/med_adv > 0.005` scale trigger it auto-enables all three,
# and replaces the flat 1.0 with a per-name temporary coefficient calibrated from the
# engine's own endogenous Amihud illiquidity (microcaps cost more than large-caps).
_AUTO_SCALE_TRIGGER = 0.005          # per-position notional / median ADV that flips impact on
_AUTO_PARTICIPATION_PCT = 10.0       # ADV cap (φ ≤ 10%): √-law domain-of-validity guard (§3.1)
_YI_FLOOR, _YI_CEIL = 0.5, 3.0       # bound the per-name temp coefficient (√-law calibration band)
_AMIHUD_COEF = 1.0                   # permanent-leg multiplier λ_mult; per-name ILLIQ carries the scale


def _calibrate_auto_impact(df: "pd.DataFrame", req: BacktestRequest) -> Optional[dict]:
    """Compute the at-scale auto-impact calibration (C1/C2/C3), or None if not at scale.

    Returns a dict {auto_impact, auto_amihud, auto_participation, impact_coef_map,
    amihud_coef_map} when the per-position notional crosses the scale trigger relative to
    the median name's ADV; None at retail scale (frictionless fills are correct there) or
    when the caller passed an explicit `impact_coef` (manual override wins).

    Fully vectorized; every degenerate input (NaN/0/inf ADV or Amihud) resolves to a sane
    neutral default — this never raises, so the caller's existing try/except simply gets
    None and falls back to legacy behaviour (zero regression, mirrors membership_pit=False).
    """
    if "adv20" not in df.columns or getattr(req, "impact_coef", None) is not None:
        return None
    # Last observed ADV + Amihud per name (point-in-time: the frame is already trailing).
    last = df.sort_values("date").groupby("ticker").agg(
        adv20=("adv20", "last"),
        amihud=("amihud_illiq", "last") if "amihud_illiq" in df.columns else ("adv20", "last"),
    )
    adv = last["adv20"].to_numpy(dtype=float)
    valid_adv = adv[np.isfinite(adv) & (adv > 0)]
    if valid_adv.size == 0:
        return None
    med_adv = float(np.median(valid_adv))
    per_pos = float(req.starting_capital) / max(int(req.max_positions), 1)
    if med_adv <= 0 or (per_pos / med_adv) <= _AUTO_SCALE_TRIGGER:
        return None   # retail scale — frictionless fills are correct; do not charge impact

    # C2 — per-name temporary-leg coefficient Y_i = g(ILLIQ_i). Scale the coefficient by the
    # name's Amihud illiquidity relative to the universe median, so a microcap (high ILLIQ)
    # is charged a stiffer √-law than a large-cap. Bounded to [_YI_FLOOR, _YI_CEIL] to keep
    # the √-law inside its calibrated domain. Names with no ILLIQ default to 1.0 (neutral).
    if "amihud_illiq" in df.columns:
        illiq = last["amihud"].to_numpy(dtype=float)
        finite = illiq[np.isfinite(illiq) & (illiq > 0)]
        med_illiq = float(np.median(finite)) if finite.size else 0.0
        if med_illiq > 0:
            ratio = np.divide(illiq, med_illiq, out=np.full_like(illiq, 1.0),
                              where=np.isfinite(illiq) & (illiq > 0))
            # √-compress the dispersion (illiquidity ratios are heavy-tailed) then clip.
            yi = np.clip(np.sqrt(np.where(ratio > 0, ratio, 1.0)), _YI_FLOOR, _YI_CEIL)
        else:
            yi = np.ones_like(illiq)
        yi = np.where(np.isfinite(yi), yi, 1.0)
        impact_coef_map = {str(t): float(v) for t, v in zip(last.index, yi)}
        amihud_coef_map = {str(t): float(a) if (np.isfinite(a) and a > 0) else 0.0
                           for t, a in zip(last.index, last["amihud"].to_numpy(dtype=float))}
    else:
        impact_coef_map = None
        amihud_coef_map = None

    return {
        "auto_impact": 1.0,                       # fallback scalar when a name has no per-name Y_i
        "auto_amihud": _AMIHUD_COEF,              # C1 — permanent Kyle-λ leg now auto-on
        "auto_participation": _AUTO_PARTICIPATION_PCT,  # C3 — physical ADV cap now auto-on
        "impact_coef_map": impact_coef_map,       # C2 — per-name temporary coefficient
        "amihud_coef_map": amihud_coef_map,       # C2 — per-name permanent ILLIQ (already per-name)
    }


def _auto_impact_status(req: BacktestRequest, ctx: "_SimContext") -> dict:
    """Observability dict for the completed at-scale cost stack (C1/C2/C3).

    Surfaces, per the audit's UI re-wiring directive, whether each of the three cost legs
    actually fired so the desk never reads a headline number without knowing which costs
    were charged. `impact_full_stack_auto` is True only when all three auto-legs are live —
    i.e. the old 'scale-fiction' state (temp-leg-only) can no longer occur silently.
    """
    explicit = getattr(req, "impact_coef", None) is not None
    temp_on = explicit or ctx.auto_impact is not None
    perm_on = (getattr(req, "amihud_coef", None) is not None) or (ctx.auto_amihud is not None)
    cap_on = (getattr(req, "max_participation_pct", None) is not None) or (ctx.auto_participation is not None)
    return {
        "impact_temp_leg_on": bool(temp_on),
        "impact_permanent_leg_on": bool(perm_on),
        "impact_adv_cap_on": bool(cap_on),
        "impact_full_stack_auto": bool(ctx.auto_impact is not None and ctx.auto_amihud is not None
                                       and ctx.auto_participation is not None),
        "impact_coef_per_name": ctx.impact_coef_map is not None,   # C2 — endogenous per-name Y_i
        "auto_participation_pct": ctx.auto_participation,
    }


def _load_context(req: BacktestRequest, from_dt, to_dt, need_mr: bool,
                  progress: Callable[[float, str], None]) -> Optional["_SimContext"]:
    """Read DuckDB once, prep indicators, build the chronological context."""
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)
    scope_tickers = [t.upper() for t in req.tickers] if req.scope == "watchlist" else None
    if req.scope == "watchlist" and not scope_tickers:
        raise HTTPException(status_code=400, detail="Watchlist scope selected but no tickers provided")

    # Compliance floor: clamp friction to >= 15 bps (0.15%) regardless of payload.
    friction = max(float(req.friction_bps), MIN_FRICTION_BPS)

    progress(5, "Connecting to market database")
    con, owns = _acquire_readonly(progress)
    try:
        progress(10, "Loading OHLCV history")
        df = _load_prepared(con, from_dt, to_dt, req.forward_days, scope_tickers,
                            need_market_relative=need_mr,
                            allow_lookahead=getattr(req, "allow_lookahead_fundamentals", False),
                            index_name=getattr(req, "index_universe", None))
        if df is None or df.empty:
            return None
        progress(28, "Computing trailing indicators")
        bench_daily, bench_source = _build_benchmark(con, from_ts, to_ts)
        try:
            fund_as_of = con.execute("SELECT MAX(as_of_date) FROM stock_metrics").fetchone()[0]
        except Exception:
            fund_as_of = None
        # Delisting/acquisition map for survivorship adjustment (G2). Raw {ticker →
        # (date, return%)}; mapped to global calendar indices below once the calendar
        # is built. Empty when no delisting source exists (current DuckDB).
        raw_delist = _delisting_map(con) if getattr(req, "survivorship_adjust", True) else {}
    finally:
        if owns:
            try:
                con.close()
            except Exception:
                pass

    # Global trading calendar + per-ticker chronological arrays (point-in-time safe)
    all_dates = sorted(df["date"].unique())
    date_to_gidx = {d: i for i, d in enumerate(all_dates)}

    has_atr = "atr_pct" in df.columns
    has_adv = "adv20" in df.columns
    has_illiq = "amihud_illiq" in df.columns
    tkr_series: dict[str, dict] = {}
    for tkr, sub in df.groupby("ticker"):
        sub = sub.sort_values("date")
        gidx = np.array([date_to_gidx[d] for d in sub["date"].values])
        tkr_series[tkr] = {
            "gidx": gidx,
            "open": sub["open"].values.astype(float),
            "close": sub["close"].values.astype(float),
            "high": sub["high"].values.astype(float),
            "low": sub["low"].values.astype(float),
            "gidx_to_lp": {int(g): i for i, g in enumerate(gidx)},
            "close_by_gidx": {int(g): float(c) for g, c in zip(gidx, sub["close"].values)},
            # Signal-day ATR% per gidx — feeds the k×ATR stop and vol-target sizing.
            "atr_pct_by_gidx": ({int(g): float(a) for g, a in zip(gidx, sub["atr_pct"].values)}
                                if has_atr else {}),
            # Signal-day 20d avg dollar volume — feeds the ADV cap + market impact.
            "adv20_by_gidx": ({int(g): float(a) for g, a in zip(gidx, sub["adv20"].values)}
                              if has_adv else {}),
            # Signal-day Amihud illiquidity — feeds the endogenous permanent impact leg.
            "amihud_by_gidx": ({int(g): float(a) for g, a in zip(gidx, sub["amihud_illiq"].values)}
                               if has_illiq else {}),
        }

    in_range = df[(df["date"] >= from_ts) & (df["date"] <= to_ts)].copy()
    grouped = list(in_range.groupby("date"))                # sorted by date
    grouped_keys = [pd.Timestamp(k) for k, _ in grouped]     # for window bisect
    ctx = _SimContext(req, all_dates, date_to_gidx, tkr_series, bench_daily,
                      bench_source, fund_as_of, friction, grouped, grouped_keys,
                      int(df["ticker"].nunique()))
    ctx.fund_pit = bool(df.attrs.get("pit_fundamentals", False))
    ctx.fund_cov_start = df.attrs.get("fund_coverage_start")
    # G2: as-of membership flag + delist map snapped to the global calendar. A delist
    # date is mapped to the first trading bar on/after it (searchsorted) so a name that
    # stops trading mid-window is force-closed on the next available bar.
    ctx.membership_pit = bool(df.attrs.get("membership_pit", False))
    if raw_delist:
        delist_gidx: dict[str, tuple] = {}
        cal = np.asarray(all_dates)
        for tkr, (dts, ret) in raw_delist.items():
            pos = int(np.searchsorted(cal, np.datetime64(pd.Timestamp(dts)), side="left"))
            if pos < len(cal):
                delist_gidx[tkr] = (pos, float(ret))
        ctx.delist_by_ticker = delist_gidx or None
        ctx.n_delistings = len(delist_gidx)
    if getattr(req, "regime_filter", False):
        model = getattr(req, "regime_model", "sma")
        mode = getattr(req, "regime_mode", "gate")
        hmm = _hmm_regime_by_date(bench_daily) if model == "hmm" else None
        if hmm is not None:
            scale_map, params = hmm
            ctx.regime_meta = {"model": "hmm", "mode": mode, **params}
            if mode == "soft":
                ctx.regime_scale = scale_map                       # smooth P(bull) throttle
            else:
                ctx.regime_ok = {d: (p >= 0.5) for d, p in scale_map.items()}   # gate at 0.5
        else:
            ctx.regime_ok = _regime_by_date(bench_daily)            # SMA(200) fallback
            ctx.regime_meta = {"model": "sma", "mode": "gate"}
    # Cross-sectional factor returns (Fama-French/Carhart) need universe breadth.
    if req.scope != "watchlist" and df["ticker"].nunique() >= 30:
        try:
            ctx.factor_returns = be.compute_factor_returns(df)
        except Exception:
            ctx.factor_returns = None
    # Default-on-at-scale market impact (G4 + C1/C2/C3): when the per-position notional
    # exceeds ~0.5% of the median name's ADV, frictionless fills are a fantasy. The prior
    # G4 path auto-enabled ONLY the temporary √-law leg with a flat global coefficient and
    # left the permanent Amihud/Kyle-λ leg and the physical ADV participation cap off — so a
    # billionaire-tier run filled 100%+ of a name's ADV in one bar and was charged the
    # cheapest third of the true cost. `_calibrate_auto_impact` now completes the stack:
    # under the SAME trigger it auto-enables all three legs and replaces the flat 1.0 with a
    # per-name temporary coefficient from the engine's own endogenous Amihud illiquidity.
    if has_adv and getattr(req, "impact_coef", None) is None:
        try:
            cal = _calibrate_auto_impact(df, req)
            if cal is not None:
                ctx.auto_impact = cal["auto_impact"]
                ctx.auto_amihud = cal["auto_amihud"]                 # C1 — permanent leg auto-on
                ctx.auto_participation = cal["auto_participation"]   # C3 — ADV cap auto-on
                ctx.impact_coef_map = cal["impact_coef_map"]         # C2 — per-name temp coef
                ctx.amihud_coef_map = cal["amihud_coef_map"]         # C2 — per-name permanent ILLIQ
        except Exception:
            # Graceful degradation (mirrors the membership_pit / fund_pit pattern): on any
            # failure fall back to legacy single-leg behaviour rather than crash the run.
            ctx.auto_impact = None
            ctx.auto_amihud = None
            ctx.auto_participation = None
            ctx.impact_coef_map = None
            ctx.amihud_coef_map = None
    return ctx


def _simulate_window(ctx: "_SimContext", req: BacktestRequest, filters: list[dict],
                     from_ts: pd.Timestamp, to_ts: pd.Timestamp,
                     attribute: bool = False) -> Optional[dict]:
    """Run one capital-managed simulation over [from_ts, to_ts] with `filters`.

    Pure in-memory: candidate selection (filter → mktcap-sort → cap) mirrors the
    single-backtest path exactly; exit resolution is served from the shared memo.
    Returns a dict of metrics + equity + trades, or None when the window is empty.
    """
    # Restrict the grouped day-frames to the window via bisect (grouped is sorted).
    lo = bisect_left(ctx.grouped_keys, from_ts)
    hi = bisect_right(ctx.grouped_keys, to_ts)

    entries_by_idx: dict[int, list[dict]] = {}
    for entry_date, day_df in ctx.grouped[lo:hi]:
        candidates = be.apply_filters(day_df, filters)
        if candidates.empty:
            continue
        # As-of index membership (G2): drop names that were not constituents on this
        # bar, so the screen never selects a stock the index hadn't admitted yet (or
        # had already ejected). No-op when membership is unavailable (column all True).
        if "index_member" in candidates.columns:
            candidates = candidates[candidates["index_member"]]
            if candidates.empty:
                continue
        # Defensive: never allow the same ticker twice in one day's candidate set.
        candidates = candidates.drop_duplicates(subset=["ticker"], keep="first")
        sel = getattr(req, "selection", "mktcap")
        sel_factor = getattr(req, "selection_factor", "dist_ma200_pct")
        if sel == "sector_neutral" and sel_factor in candidates.columns and len(candidates) > 1:
            # Rank by the within-sector z-score of the selection factor, so the bet is the
            # *residual* signal, not a size/sector tilt (Grinold-Kahn neutralization).
            sct = candidates["ticker"].astype(str).str.upper().map(_sector_map()).fillna("Unknown")
            grp = candidates.groupby(sct.values)[sel_factor]
            mu, sd = grp.transform("mean"), grp.transform("std")
            zsel = ((candidates[sel_factor] - mu) / sd.replace(0, np.nan)).fillna(0.0)
            candidates = candidates.assign(_zsel=zsel).sort_values(
                "_zsel", ascending=False, na_position="last")
        elif "mktcap_cr" in candidates.columns:
            # Size-sorted, but fall back to trailing dollar-volume (adv20) where the
            # point-in-time market-cap is unavailable (pre-coverage), so the ordering
            # stays deterministic and look-ahead-free (G1) instead of arbitrary on NaN.
            sort_cols = ["mktcap_cr"] + (["adv20"] if "adv20" in candidates.columns else [])
            candidates = candidates.sort_values(sort_cols, ascending=False, na_position="last")
        candidates = candidates.head(req.max_stocks_per_day)

        sig = ctx.date_to_gidx[entry_date]   # the day the signal fires
        for tkr in candidates["ticker"].tolist():
            ent = ctx.resolve(sig, tkr)
            if ent is None:
                continue
            entries_by_idx.setdefault(ent["entry_gidx"], []).append(ent)

    gidxs = [ctx.date_to_gidx[d] for d in ctx.all_dates if from_ts <= d <= to_ts]
    if not gidxs:
        return None
    from_idx, to_idx = min(gidxs), max(gidxs)
    equity, trades = be.simulate_portfolio(
        ctx.all_dates, from_idx, to_idx, entries_by_idx, ctx.price_at,
        starting_capital=req.starting_capital, max_positions=req.max_positions,
        max_drawdown_halt_pct=req.max_drawdown_halt_pct,
        vol_target_pct=getattr(req, "vol_target_pct", None),
        max_position_pct=getattr(req, "max_position_pct", None),
        max_sector_pct=getattr(req, "max_sector_pct", None),
        regime_ok_by_date=(ctx.regime_ok if getattr(req, "regime_filter", False) else None),
        regime_scale_by_date=(ctx.regime_scale if getattr(req, "regime_filter", False) else None),
        # Effective impact stack (G4 + C1/C2/C3): an explicit caller knob always wins; else
        # the at-scale auto-safeguard supplies ALL THREE legs — temporary √-law (per-name Y_i
        # via impact_coef_map), permanent Amihud/Kyle-λ (amihud_coef), and the physical ADV
        # participation cap (max_participation_pct). At retail scale every ctx.auto_* is None,
        # so this reduces to the legacy frictionless path exactly (zero regression).
        impact_coef=(getattr(req, "impact_coef", None) if getattr(req, "impact_coef", None) is not None
                     else ctx.auto_impact),
        impact_coef_map=ctx.impact_coef_map,                         # C2 — per-name temp coefficient
        max_participation_pct=(getattr(req, "max_participation_pct", None)
                               if getattr(req, "max_participation_pct", None) is not None
                               else ctx.auto_participation),         # C3 — auto ADV cap at scale
        amihud_coef=(getattr(req, "amihud_coef", None)
                     if getattr(req, "amihud_coef", None) is not None
                     else ctx.auto_amihud),                          # C1 — auto permanent leg at scale
        kelly_fraction=getattr(req, "kelly_fraction", None),
        delist_by_ticker=ctx.delist_by_ticker,
    )

    # Tag every trade with its sector (for the blotter's sector grouping / export).
    sec = _sector_map()
    for t in trades:
        t["sector"] = sec.get(str(t.get("ticker", "")).upper(), "Unknown")

    equity_dates = [e["date"] for e in equity]
    bench_nav = be.equal_weight_benchmark_nav(ctx.bench_daily, equity_dates, req.starting_capital)
    nav_series = [e["nav"] for e in equity] or [req.starting_capital]
    run_max = np.maximum.accumulate(np.asarray(nav_series, dtype=float))
    for i, e in enumerate(equity):
        e["benchmark_nav"] = bench_nav[i]
        e["drawdown_pct"] = round((nav_series[i] / run_max[i] - 1) * 100, 2)

    metrics = be.compute_metrics(equity, trades, bench_nav, req.starting_capital,
                                 factor_returns=ctx.factor_returns if attribute else None)
    return {"equity": equity, "trades": trades, "bench_nav": bench_nav, **metrics}


def _core_backtest(req: BacktestRequest, on_progress: Optional[Callable[[dict], None]] = None) -> dict:
    t0 = time.time()

    def progress(pct: float, label: str):
        if on_progress:
            elapsed = time.time() - t0
            eta = (elapsed / pct * (100 - pct)) if pct > 1 else None
            on_progress({"event": "progress", "pct": round(pct, 1), "label": label,
                         "eta_seconds": round(eta, 1) if eta else None})

    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()

    filters = [fc.model_dump() for fc in req.filters]
    need_mr = any(f["field"] in MARKET_RELATIVE_FIELDS for f in filters)

    ctx = _load_context(req, from_dt, to_dt, need_mr, progress)
    if ctx is None:
        return _empty_result(req)

    progress(45, "Resolving entry candidates & simulating portfolio")
    sim = _simulate_window(ctx, req, filters, pd.Timestamp(from_dt), pd.Timestamp(to_dt),
                           attribute=True)
    if sim is None:
        return _empty_result(req)
    progress(92, "Aligning benchmark & computing analytics")

    trades = sim["trades"]
    metric_only = {k: v for k, v in sim.items() if k not in ("equity", "trades", "bench_nav")}
    progress(100, "Done")
    return {
        "mode": MODE,
        "config": {
            "from_date": req.from_date, "to_date": req.to_date,
            "forward_days": req.forward_days, "win_threshold": req.win_threshold,
            "starting_capital": req.starting_capital, "friction_bps": ctx.friction,
            "stop_loss_pct": req.stop_loss_pct, "trailing_stop_pct": req.trailing_stop_pct,
            "max_positions": req.max_positions, "max_drawdown_halt_pct": req.max_drawdown_halt_pct,
            "scope": req.scope, "entry_timing": req.entry_timing,
            "atr_stop_mult": req.atr_stop_mult, "vol_target_pct": req.vol_target_pct,
            "max_position_pct": req.max_position_pct, "max_sector_pct": req.max_sector_pct,
            "regime_filter": req.regime_filter, "regime": ctx.regime_meta,
            "max_participation_pct": req.max_participation_pct, "impact_coef": req.impact_coef,
            "amihud_coef": req.amihud_coef, "kelly_fraction": req.kelly_fraction,
            "impact_auto_enabled": (req.impact_coef is None and ctx.auto_impact is not None),
            **_auto_impact_status(req, ctx),   # C1/C2/C3 — completed-stack observability
            "selection": req.selection,
            "n_tickers": ctx.n_tickers,
            "benchmark_label": ctx.bench_source,
            "fundamentals_as_of": str(ctx.fund_as_of) if ctx.fund_as_of else None,
            "fundamentals_pit": ctx.fund_pit,
            "fundamentals_coverage_start": ctx.fund_cov_start,
            "index_universe": req.index_universe,
            "membership_pit": ctx.membership_pit,
            "survivorship_adjusted": bool(ctx.delist_by_ticker),
            "n_delistings": ctx.n_delistings,
        },
        "fundamental_lookahead_active": be.fundamental_filters_active(filters),
        **metric_only,
        "equity_curve": sim["equity"],
        "trades": trades[-1000:],
        "_all_trades": trades,  # internal, stripped before JSON if large
    }


def _empty_result(req: BacktestRequest) -> dict:
    return {
        "mode": MODE,
        "config": {"scope": req.scope, "n_tickers": 0, "benchmark_label": BENCHMARK_LABEL,
                   "starting_capital": req.starting_capital},
        "fundamental_lookahead_active": be.fundamental_filters_active([fc.model_dump() for fc in req.filters]),
        "starting_capital": req.starting_capital, "final_nav": req.starting_capital,
        "total_return_pct": 0.0, "cagr_pct": 0.0, "benchmark_total_return_pct": 0.0,
        "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
        "avg_return": 0.0, "avg_win_return": 0.0, "avg_loss_return": 0.0,
        "win_loss_ratio": 0.0, "expectancy": 0.0, "profit_factor": 0.0,
        "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "calmar_ratio": 0.0,
        "max_drawdown": 0.0, "max_drawdown_duration_days": 0,
        "beta": 0.0, "alpha_annual_pct": 0.0,
        "exit_breakdown": {"stop_loss": 0, "trailing_stop": 0, "time_stop": 0},
        "equity_curve": [], "trades": [],
    }


# ── Real walk-forward optimization (in-sample fit → out-of-sample test) ────────────
#
# Each rolling window: (1) optimize a filter combination in-sample, (2) freeze it,
# (3) measure it out-of-sample across an embargo gap that exceeds the holding
# horizon — so a trade opened at the in-sample edge cannot leak its forward label
# into the OOS fold. The headline metrics are the *stitched OOS* curve, never an
# in-sample fit. A full-period in-sample best is reported alongside purely to expose
# the optimism gap (overfitting = in-sample objective ≫ out-of-sample objective).

_OBJECTIVES = {"sharpe", "calmar", "profit_factor", "total_return"}


def _wfo_windows(from_dt, to_dt, in_sample_days: int, out_sample_days: int,
                 embargo_days: int) -> list[tuple]:
    """Rolling (in-sample, out-of-sample) date windows with an embargo gap.

    Out-of-sample windows tile contiguously (cursor advances by out_sample_days),
    so the stitched OOS curve is a clean, gap-free forward track record.
    """
    windows = []
    cur = from_dt
    while True:
        is_start = cur
        is_end = is_start + timedelta(days=in_sample_days)
        oos_start = is_end + timedelta(days=embargo_days)
        if oos_start > to_dt:
            break
        oos_end = min(oos_start + timedelta(days=out_sample_days), to_dt)
        windows.append((is_start, is_end, oos_start, oos_end))
        if oos_end >= to_dt:
            break
        cur = cur + timedelta(days=out_sample_days)
    return windows


def _candidate_combos(pool: list[dict], max_combo_size: int, cap: int = 63) -> list[list[dict]]:
    """All non-empty combinations of the filter pool up to `max_combo_size` (capped).

    An empty pool degenerates to a single empty config (no optimization possible).
    """
    n = len(pool)
    if n == 0:
        return [[]]
    k_max = max(1, min(int(max_combo_size), n))
    combos: list[list[dict]] = []
    for k in range(1, k_max + 1):
        for idx in itertools.combinations(range(n), k):
            combos.append([pool[i] for i in idx])
            if len(combos) >= cap:
                return combos
    return combos


def _objective(metrics: dict, name: str) -> float:
    """Scalar selection objective extracted from a simulation's metric dict."""
    if name == "calmar":
        return float(metrics.get("calmar_ratio", 0.0) or 0.0)
    if name == "profit_factor":
        pf = metrics.get("profit_factor", 0.0)
        return 1e6 if pf == float("inf") else float(pf or 0.0)
    if name == "total_return":
        return float(metrics.get("total_return_pct", 0.0) or 0.0)
    return float(metrics.get("sharpe_ratio", 0.0) or 0.0)   # default: sharpe


def _filter_label(f: dict) -> str:
    """Human-readable one-line label for a filter condition."""
    field = f.get("field", "?")
    if field in be.BOOLEAN_FILTERS:
        return field
    sym = {"gt": ">", "lt": "<", "gte": "≥", "lte": "≤"}.get(f.get("op", "gt"), f.get("op", ""))
    val = f.get("value", 0.0)
    return f"{field}{sym}{val:g}"


def _pick_best(ctx: "_SimContext", req: WFOBacktestRequest, base: list[dict],
               combos: list[list[dict]], from_ts, to_ts, objective: str,
               min_trades: int):
    """Evaluate every candidate combo over a window; return the best (score, combo, sim).

    Selection rule: maximize the objective among combos that clear the trade floor;
    tie-break toward more trades then fewer filters. If *no* combo clears the floor,
    fall back to the combo with the most trades (flagged low-confidence by score=-inf).
    """
    best = None
    for combo in combos:
        sim = _simulate_window(ctx, req, base + combo, from_ts, to_ts)
        if sim is None:
            continue
        ntr = int(sim.get("total_trades", 0))
        obj = _objective(sim, objective)
        score = obj if ntr >= min_trades else float("-inf")
        rank = (score, ntr, -len(combo))
        if best is None or rank > best[0]:
            best = (rank, combo, sim, obj, ntr)
    return best


def _core_wfo(req: WFOBacktestRequest, on_progress: Optional[Callable[[dict], None]] = None) -> dict:
    """Genuine walk-forward: per-window in-sample optimization → embargoed OOS test."""
    t0 = time.time()

    def progress(pct: float, label: str):
        if on_progress:
            elapsed = time.time() - t0
            eta = (elapsed / pct * (100 - pct)) if pct > 1 else None
            on_progress({"event": "progress", "pct": round(pct, 1), "label": label,
                         "eta_seconds": round(eta, 1) if eta else None})

    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)

    base = [fc.model_dump() for fc in req.base_filters]
    pool = [fc.model_dump() for fc in (req.candidate_filters or req.filters)]
    objective = req.objective if req.objective in _OBJECTIVES else "sharpe"
    # Embargo must exceed the holding horizon (a trade opened at the IS edge holds
    # forward_days bars; the gap guarantees that window never overlaps the OOS fold).
    embargo = max(int(req.embargo_days), int(req.forward_days) + 2)

    need_mr = any(f["field"] in MARKET_RELATIVE_FIELDS for f in (base + pool))
    progress(4, "Loading market history (once)")
    ctx = _load_context(req, from_dt, to_dt, need_mr, progress)
    if ctx is None:
        return _empty_result(req)

    combos = _candidate_combos(pool, req.max_combo_size)
    optimized = len(pool) > 0
    windows = _wfo_windows(from_dt, to_dt, req.in_sample_days, req.out_sample_days, embargo)
    min_trades = max(0, int(req.min_is_trades))

    stitched_equity: list[dict] = []
    oos_trades_all: list[dict] = []
    wfo_windows: list[dict] = []
    is_objs: list[float] = []
    oos_objs: list[float] = []
    running = float(req.starting_capital)
    nwin = max(len(windows), 1)

    for wi, (is_s, is_e, oos_s, oos_e) in enumerate(windows):
        progress(8 + 80 * wi / nwin,
                 f"Window {wi + 1}/{len(windows)} · optimizing in-sample {is_s}→{is_e}")
        best = _pick_best(ctx, req, base, combos,
                          pd.Timestamp(is_s), pd.Timestamp(is_e), objective, min_trades)
        if best is None:
            continue
        (score, _, _), combo, is_sim, is_obj, is_ntr = best
        low_conf = (score == float("-inf"))

        # Freeze the in-sample winner; test it untouched out-of-sample.
        oos_sim = _simulate_window(ctx, req, base + combo,
                                   pd.Timestamp(oos_s), pd.Timestamp(oos_e))
        if oos_sim is None:
            continue
        oos_obj = _objective(oos_sim, objective)
        is_objs.append(is_obj)
        oos_objs.append(oos_obj)

        # Stitch the OOS window onto the running compounded curve.
        scale = running / float(req.starting_capital)
        for e in oos_sim["equity"]:
            stitched_equity.append({
                "date": e["date"],
                "nav": round(e["nav"] * scale, 2),
                "cash": round(e.get("cash", 0.0) * scale, 2),
                "positions": e.get("positions", 0),
            })
        if oos_sim["equity"]:
            running = oos_sim["equity"][-1]["nav"] * scale
        oos_trades_all.extend(oos_sim["trades"])

        w_rets = [t["return_pct"] for t in oos_sim["trades"]]
        w_wins = sum(1 for t in oos_sim["trades"] if t["is_win"])
        wfo_windows.append({
            # Backward-compatible window shape (UI table) — these describe the OOS fold.
            "start": str(oos_s), "end": str(oos_e), "trades": len(oos_sim["trades"]),
            "return_pct": round(sum(w_rets) / len(w_rets), 2) if w_rets else 0.0,
            "total_return_pct": round(float(oos_sim.get("total_return_pct", 0.0)), 2),
            "win_rate": round(w_wins / len(w_rets) * 100, 1) if w_rets else 0.0,
            "best": round(max(w_rets), 2) if w_rets else 0.0,
            "worst": round(min(w_rets), 2) if w_rets else 0.0,
            # Real-WFO honesty extras (optional UI; safe to ignore).
            "is_start": str(is_s), "is_end": str(is_e),
            "chosen_filters": [_filter_label(f) for f in combo] or ["(no filter)"],
            "is_trades": is_ntr,
            "is_objective": round(is_obj, 3),
            "oos_objective": round(oos_obj, 3),
            "is_sharpe": is_sim.get("sharpe_ratio", 0.0),
            "oos_sharpe": oos_sim.get("sharpe_ratio", 0.0),
            "degradation": round(is_obj - oos_obj, 3),
            "low_confidence": bool(low_conf),
        })

    if not stitched_equity:
        res = _empty_result(req)
        res["validation"] = "walk_forward_oos"
        res["walk_forward"] = {
            "n_windows": 0, "objective": objective, "embargo_days": embargo,
            "in_sample_days": req.in_sample_days, "out_sample_days": req.out_sample_days,
            "note": ("No out-of-sample windows fit the date range. Widen the span, or "
                     "shrink in_sample_days / out_sample_days."),
        }
        return res

    # Aggregate OOS metrics off the stitched compounded curve + concatenated OOS trades.
    bench_nav = be.equal_weight_benchmark_nav(
        ctx.bench_daily, [e["date"] for e in stitched_equity], req.starting_capital)
    nav_series = [e["nav"] for e in stitched_equity]
    run_max = np.maximum.accumulate(np.asarray(nav_series, dtype=float))
    for i, e in enumerate(stitched_equity):
        e["benchmark_nav"] = bench_nav[i]
        e["drawdown_pct"] = round((nav_series[i] / run_max[i] - 1) * 100, 2)
    metrics = be.compute_metrics(stitched_equity, oos_trades_all, bench_nav, req.starting_capital,
                                 factor_returns=ctx.factor_returns)

    # Full-period evaluation of every candidate — yields the in-sample overfit contrast
    # AND the trial-Sharpe distribution needed to Deflate the stitched OOS Sharpe (G3).
    progress(92, "Computing full-period contrast + multiple-testing correction")
    full_best = None
    full_trial_sharpes: list[float] = []
    for combo in combos:
        fsim = _simulate_window(ctx, req, base + combo, from_ts, to_ts)
        if fsim is None:
            continue
        full_trial_sharpes.append(float(fsim.get("sharpe_ratio", 0.0) or 0.0))
        ntr = int(fsim.get("total_trades", 0))
        score = _objective(fsim, objective) if ntr >= min_trades else float("-inf")
        if full_best is None or score > full_best[0]:
            full_best = (score, combo, fsim)
    in_sample_full = None
    if full_best is not None:
        _, fcombo, fsim = full_best
        in_sample_full = {
            "best_filters": [_filter_label(f) for f in fcombo] or ["(no filter)"],
            "sharpe_ratio": fsim.get("sharpe_ratio", 0.0),
            "cagr_pct": fsim.get("cagr_pct", 0.0),
            "max_drawdown": fsim.get("max_drawdown", 0.0),
            "total_return_pct": fsim.get("total_return_pct", 0.0),
            "total_trades": fsim.get("total_trades", 0),
            "profit_factor": fsim.get("profit_factor", 0.0),
        }

    # Deflated Sharpe of the stitched OOS curve against the breadth of the search.
    oos_nav = np.asarray([e["nav"] for e in stitched_equity], dtype=float)
    oos_daily = (oos_nav[1:] / oos_nav[:-1] - 1.0) if len(oos_nav) > 1 else np.array([])
    dsr = be.deflated_sharpe_ratio(
        oos_daily, full_trial_sharpes or [float(metrics.get("sharpe_ratio", 0.0))])

    avg_is = round(float(np.mean(is_objs)), 3) if is_objs else 0.0
    avg_oos = round(float(np.mean(oos_objs)), 3) if oos_objs else 0.0
    efficiency = round(avg_oos / avg_is, 3) if abs(avg_is) > 1e-9 else None

    progress(96, "Monte Carlo on out-of-sample trades")
    mc = be.monte_carlo_drawdowns([t["return_pct"] for t in oos_trades_all], req.monte_carlo_runs)
    progress(100, "Done")

    return {
        "mode": MODE,
        "validation": "walk_forward_oos",
        "config": {
            "from_date": req.from_date, "to_date": req.to_date,
            "forward_days": req.forward_days, "win_threshold": req.win_threshold,
            "starting_capital": req.starting_capital, "friction_bps": ctx.friction,
            "stop_loss_pct": req.stop_loss_pct, "trailing_stop_pct": req.trailing_stop_pct,
            "max_positions": req.max_positions, "max_drawdown_halt_pct": req.max_drawdown_halt_pct,
            "scope": req.scope, "entry_timing": req.entry_timing,
            "atr_stop_mult": req.atr_stop_mult, "vol_target_pct": req.vol_target_pct,
            "max_position_pct": req.max_position_pct, "max_sector_pct": req.max_sector_pct,
            "regime_filter": req.regime_filter, "regime": ctx.regime_meta,
            "max_participation_pct": req.max_participation_pct, "impact_coef": req.impact_coef,
            "amihud_coef": req.amihud_coef, "kelly_fraction": req.kelly_fraction,
            "impact_auto_enabled": (req.impact_coef is None and ctx.auto_impact is not None),
            **_auto_impact_status(req, ctx),   # C1/C2/C3 — completed-stack observability
            "selection": req.selection,
            "n_tickers": ctx.n_tickers,
            "benchmark_label": ctx.bench_source,
            "fundamentals_as_of": str(ctx.fund_as_of) if ctx.fund_as_of else None,
            "fundamentals_pit": ctx.fund_pit,
            "fundamentals_coverage_start": ctx.fund_cov_start,
            "index_universe": req.index_universe,
            "membership_pit": ctx.membership_pit,
            "survivorship_adjusted": bool(ctx.delist_by_ticker),
            "n_delistings": ctx.n_delistings,
        },
        "fundamental_lookahead_active": be.fundamental_filters_active(base + pool),
        **metrics,
        "equity_curve": stitched_equity,
        "trades": oos_trades_all[-1000:],
        "wfo_windows": wfo_windows,
        "monte_carlo": mc,
        "in_sample_full": in_sample_full,
        "walk_forward": {
            "n_windows": len(wfo_windows),
            "in_sample_days": req.in_sample_days,
            "out_sample_days": req.out_sample_days,
            "embargo_days": embargo,
            "objective": objective,
            "optimized": optimized,
            "n_candidates": len(combos),
            "max_combo_size": req.max_combo_size,
            "min_is_trades": min_trades,
            "avg_is_objective": avg_is,
            "avg_oos_objective": avg_oos,
            "efficiency": efficiency,   # OOS/IS objective ratio (≪1 ⇒ overfit)
            # Deflated Sharpe of the stitched OOS curve, corrected for the trial count.
            "deflated_sharpe": round(dsr["dsr"], 3),       # ≳0.95 survives multiple-testing
            "dsr_sr_annual": dsr["sr_annual"],
            "dsr_sr0_annual": dsr["sr0_annual"],           # expected max-Sharpe under the null
            "dsr_n_trials": dsr["n_trials"],
        },
    }


def _strip_internal(result: dict) -> dict:
    result.pop("_all_trades", None)
    return result


# ── Synchronous endpoints (fallback + scripting) ──────────────────────────────────

@router.post("/backtest")
async def run_backtest(req: BacktestRequest):
    try:
        return _strip_internal(_core_backtest(req))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wfo-backtest")
async def run_wfo_backtest(req: WFOBacktestRequest):
    try:
        return _strip_internal(_core_wfo(req))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ── NDJSON streaming endpoints (live progress + ETA) ──────────────────────────────

def _stream_runner(req, is_wfo: bool):
    """Run the backtest in a worker thread, yielding NDJSON progress then result."""
    q: "queue.Queue[dict]" = queue.Queue()

    def on_progress(evt: dict):
        q.put(evt)

    def worker():
        try:
            result = _core_wfo(req, on_progress) if is_wfo else _core_backtest(req, on_progress)
            q.put({"event": "result", "data": _strip_internal(result)})
        except HTTPException as he:
            q.put({"event": "error", "detail": str(he.detail)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            q.put({"event": "error", "detail": str(e)})
        finally:
            q.put({"event": "__done__"})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        while True:
            evt = q.get()
            if evt.get("event") == "__done__":
                break
            yield json.dumps(evt, default=str) + "\n"

    return generate


@router.post("/backtest/stream")
async def run_backtest_stream(req: BacktestRequest):
    return StreamingResponse(_stream_runner(req, is_wfo=False)(),
                             media_type="application/x-ndjson")


@router.post("/wfo-backtest/stream")
async def run_wfo_backtest_stream(req: WFOBacktestRequest):
    return StreamingResponse(_stream_runner(req, is_wfo=True)(),
                             media_type="application/x-ndjson")


# ── Legacy informational stubs (unchanged) ────────────────────────────────────────

@router.get("/signal-coverage")
async def get_signal_coverage():
    return {"stocks_with_signals": 0, "total_signals_generated": 0, "coverage_pct": 0,
            "last_signal_time": None, "note": "Signals table empty until ml-service runs"}


async def _ml_stats() -> dict:
    """Live ml_features/ml_labels stats from the data-service (owner of the DB)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{DATA_SVC}/db/ml-stats")
        r.raise_for_status()
        return r.json()


@router.get("/feature-quality")
async def get_feature_quality():
    try:
        feat = (await _ml_stats()).get("features", {})
        rows = int(feat.get("rows", 0) or 0)
        tickers = int(feat.get("tickers", 0) or 0)
        universe = tickers
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                ds = await client.get(f"{DATA_SVC}/db/stats")
                if ds.status_code == 200:
                    universe = int(ds.json().get("total_stocks", tickers) or tickers)
        except Exception:
            pass
        return {
            "stocks_with_features": tickers,
            "total_feature_rows": rows,
            "average_features_per_stock": round(rows / tickers) if tickers else 0,
            "feature_coverage_pct": round(tickers / universe * 100, 1) if universe else 0,
            "latest_date": feat.get("latest_date"),
        }
    except Exception as e:
        return {"stocks_with_features": 0, "total_feature_rows": 0, "average_features_per_stock": 0,
                "feature_coverage_pct": 0, "note": f"ml-stats unavailable: {e}"}


@router.get("/label-distribution")
async def get_label_distribution():
    try:
        lbl = (await _ml_stats()).get("labels", {})
        total = int(lbl.get("rows", 0) or 0)
        up = int(lbl.get("up_labels", 0) or 0)
        down = int(lbl.get("down_labels", 0) or 0)
        return {
            "total_labels": total,
            "up_labels_pct": round(up / total * 100, 1) if total else 0,
            "down_labels_pct": round(down / total * 100, 1) if total else 0,
            "average_return_pct": lbl.get("avg_return_pct", 0),
            "std_return_pct": lbl.get("std_return_pct", 0),
            "latest_date": lbl.get("latest_date"),
        }
    except Exception as e:
        return {"total_labels": 0, "up_labels_pct": 0, "down_labels_pct": 0,
                "average_return_pct": 0, "note": f"ml-stats unavailable: {e}"}


# ── Factor Decile Profiler (Pillar 2) ─────────────────────────────────────────────
# Generalized diagnostic: bucket any numeric factor into deciles and map each
# bucket against the forward win/loss base rate, so thresholds are chosen from the
# data instead of guessed. Reuses the *exact* backtest load + indicator path so a
# decile boundary here equals a filter threshold in the simulation.

class FactorProfileRequest(BaseModel):
    factor: str                          # numeric field key (must be in backtest_engine.FIELD_MAP)
    from_date: str
    to_date: str
    forward_days: int = 5                # forward holding horizon N (trading bars)
    win_threshold: float = 0.0           # net % a forward return must clear to be a "win"
    friction_bps: float = 15.0           # round-trip cost, basis points (matches backtest)
    scope: str = "universe"              # "universe" | "watchlist"
    tickers: list[str] = []
    n_deciles: int = 10


def _empty_factor_profile(req: "FactorProfileRequest", reason: str) -> dict:
    meta = FILTER_CATALOG.get(req.factor, {})
    return {
        "mode": MODE,
        "factor": req.factor,
        "factor_label": meta.get("label", req.factor),
        "unit": meta.get("unit", ""),
        "category": meta.get("category", ""),
        "lookahead_bias_present": req.factor in be.FUNDAMENTAL_FIELDS,
        "forward_days": req.forward_days,
        "win_threshold": req.win_threshold,
        "friction_bps": req.friction_bps,
        "config": {"scope": req.scope, "n_tickers": 0,
                   "from_date": req.from_date, "to_date": req.to_date},
        "note": reason,
        **fde._empty_profile(req.n_deciles),
    }


def _core_factor_profile(req: FactorProfileRequest) -> dict:
    if req.factor not in be.FIELD_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or non-numeric factor '{req.factor}'. "
                   f"Numeric factors: {sorted(be.FIELD_MAP)}",
        )
    col = be.FIELD_MAP[req.factor]
    try:
        from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
        to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)
    n_deciles = max(2, min(int(req.n_deciles), 20))
    friction = max(float(req.friction_bps), MIN_FRICTION_BPS)   # same compliance floor as backtest

    scope_tickers = [t.upper() for t in req.tickers] if req.scope == "watchlist" else None
    if req.scope == "watchlist" and not scope_tickers:
        raise HTTPException(status_code=400, detail="Watchlist scope selected but no tickers provided")

    conn, owns = _acquire_readonly(lambda *a, **k: None)
    try:
        df = _load_prepared(conn, from_dt, to_dt, req.forward_days, scope_tickers,
                            need_market_relative=req.factor in MARKET_RELATIVE_FIELDS)
    finally:
        if owns:
            try:
                conn.close()
            except Exception:
                pass

    if df is None or df.empty or col not in df.columns:
        return _empty_factor_profile(req, "No prepared data in the selected window/scope")

    as_of = (df["date"] >= from_ts) & (df["date"] <= to_ts)
    prof = fde.profile_factor(
        df, col, req.forward_days, req.win_threshold, friction,
        n_deciles=n_deciles, as_of_mask=as_of,
    )
    n_tickers = int(df.loc[as_of, "ticker"].nunique())
    meta = FILTER_CATALOG.get(req.factor, {})
    return {
        "mode": MODE,
        "factor": req.factor,
        "factor_label": meta.get("label", req.factor),
        "unit": meta.get("unit", ""),
        "category": meta.get("category", ""),
        # Structural look-ahead guard (Pillar 2): fundamentals are a current snapshot
        # applied to historical dates, so any decile study over them is bias-prone.
        "lookahead_bias_present": req.factor in be.FUNDAMENTAL_FIELDS,
        "forward_days": req.forward_days,
        "win_threshold": req.win_threshold,
        "friction_bps": friction,
        "config": {"scope": req.scope, "n_tickers": n_tickers,
                   "from_date": req.from_date, "to_date": req.to_date},
        **prof,
    }


@router.post("/factor-profile")
async def factor_profile(req: FactorProfileRequest):
    """
    Pillar 2 — vectorized decile profile of any numeric factor against the
    friction-aware forward base rate. Heavy DuckDB + pandas work runs in a worker
    thread so the event loop keeps serving.
    """
    return await asyncio.to_thread(_core_factor_profile, req)


# ── Glass-Box charting endpoints (Pillar 2 visual environments) ────────────────────
# Premium per-asset visual sub-panels backing the new structural filters:
#   • factor-series   → Rolling-Correlation panel + Squeeze alert dots (+ VMI/VIPT)
#   • rrg             → Relative Rotation Graph quadrant trajectories
#   • volume-profile  → horizontal Volume Profile (HVN/LVN/POC) + anchored VWAP

def _jsafe(v) -> Optional[float]:
    """NaN/inf → None so the JSON encoder never emits invalid tokens."""
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else round(f, 6)
    except Exception:
        return None


def _benchmark_level(con, from_ts, to_ts) -> tuple[dict, str]:
    """Compound the benchmark daily returns into a price *level* (base 100) keyed by
    Timestamp, for relative-strength ratios."""
    daily, label = _build_benchmark(con, from_ts, to_ts)
    if not daily:
        return {}, label
    s = pd.Series({pd.Timestamp(k): v for k, v in daily.items()}).sort_index()
    level = (1.0 + s.fillna(0.0)).cumprod() * 100.0
    return level.to_dict(), label


class FactorSeriesRequest(BaseModel):
    ticker: str
    from_date: str
    to_date: str
    corr_window: int = 30


def _core_factor_series(req: FactorSeriesRequest) -> dict:
    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)
    tkr = req.ticker.strip().upper()
    w = max(5, min(int(req.corr_window), 120))

    conn, owns = _acquire_readonly(lambda *a, **k: None)
    try:
        df = _load_prepared(conn, from_dt, to_dt, 5, [tkr], need_market_relative=False)
        bench_daily, bench_src = _build_benchmark(conn, from_ts - pd.Timedelta(days=90), to_ts)
    finally:
        if owns:
            try:
                conn.close()
            except Exception:
                pass

    if df is None or df.empty:
        return {"mode": MODE, "ticker": tkr, "benchmark": "none", "corr_window": w, "points": []}

    sub = df[df["ticker"] == tkr].sort_values("date").copy()
    sub["ret1"] = sub["close"].pct_change()
    sub["mkt"] = sub["date"].map(lambda d: bench_daily.get(str(pd.Timestamp(d).date()), np.nan))
    sub["corr30"] = sub["ret1"].rolling(w, min_periods=w).corr(sub["mkt"])

    win = sub[(sub["date"] >= from_ts) & (sub["date"] <= to_ts)]
    points = [{
        "date": str(r["date"])[:10],
        "open": _jsafe(r["open"]), "high": _jsafe(r["high"]),
        "low": _jsafe(r["low"]), "close": _jsafe(r["close"]),
        "volume": _jsafe(r["volume"]),
        "corr30": _jsafe(r.get("corr30")),
        "squeeze_on": bool(r.get("squeeze_on", False)),
        "squeeze_ratio": _jsafe(r.get("squeeze_ratio")),
        "vmi_ratio": _jsafe(r.get("vmi_ratio")),
        "vol_zscore_20": _jsafe(r.get("vol_zscore_20")),
        "vipt_breakout": bool(r.get("vipt_breakout", False)),
    } for _, r in win.iterrows()]
    return {"mode": MODE, "ticker": tkr, "benchmark": bench_src,
            "corr_window": w, "n": len(points), "points": points}


@router.post("/factor-series")
async def factor_series(req: FactorSeriesRequest):
    return await asyncio.to_thread(_core_factor_series, req)


class RRGRequest(BaseModel):
    tickers: list[str]
    from_date: str
    to_date: str
    window: int = 12        # smoothing/normalization window for RS-Ratio / RS-Momentum
    momentum: int = 5       # lookback for the RS-Ratio rate-of-change
    tail: int = 12          # trajectory length returned per ticker


def _quadrant(ratio: float, mom: float) -> str:
    if ratio >= 100 and mom >= 100:
        return "Leading"
    if ratio >= 100 and mom < 100:
        return "Weakening"
    if ratio < 100 and mom < 100:
        return "Lagging"
    return "Improving"


def _core_rrg(req: RRGRequest) -> dict:
    tickers = [t.strip().upper() for t in req.tickers if t.strip()][:40]
    if not tickers:
        raise HTTPException(status_code=400, detail="Provide at least one ticker")
    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)
    w = max(4, min(int(req.window), 60))
    m = max(1, min(int(req.momentum), 30))
    tail = max(1, min(int(req.tail), 40))

    conn, owns = _acquire_readonly(lambda *a, **k: None)
    try:
        df = _load_prepared(conn, from_dt, to_dt, 5, tickers, need_market_relative=False)
        level, bench_src = _benchmark_level(conn, from_ts - pd.Timedelta(days=120), to_ts)
    finally:
        if owns:
            try:
                conn.close()
            except Exception:
                pass

    if df is None or df.empty or not level:
        return {"mode": MODE, "benchmark": "none", "window": w, "tickers": {}}

    lvl = pd.Series(level).sort_index()
    out: dict[str, list] = {}
    for tkr in tickers:
        sub = df[df["ticker"] == tkr].sort_values("date").copy()
        if sub.empty:
            continue
        sub = sub.set_index("date")
        sub["bench"] = lvl.reindex(sub.index)
        sub = sub[sub["bench"].notna() & (sub["bench"] > 0)]
        if len(sub) < w + m:
            continue
        rs = sub["close"] / sub["bench"] * 100.0
        # JdK-style normalization: RS-Ratio centred on 100, RS-Momentum = normalized
        # rate-of-change of the ratio (both unit-less, comparable across names).
        rs_ratio = 100.0 + (rs - rs.rolling(w).mean()) / rs.rolling(w).std()
        roc = rs_ratio - rs_ratio.shift(m)
        rs_mom = 100.0 + (roc - roc.rolling(w).mean()) / roc.rolling(w).std()
        traj = pd.DataFrame({"rs_ratio": rs_ratio, "rs_mom": rs_mom}).dropna()
        traj = traj[(traj.index >= from_ts) & (traj.index <= to_ts)].tail(tail)
        if traj.empty:
            continue
        out[tkr] = [{
            "date": str(idx)[:10],
            "rs_ratio": _jsafe(row["rs_ratio"]),
            "rs_mom": _jsafe(row["rs_mom"]),
            "quadrant": _quadrant(row["rs_ratio"], row["rs_mom"]),
        } for idx, row in traj.iterrows()]
    return {"mode": MODE, "benchmark": bench_src, "window": w, "momentum": m, "tickers": out}


@router.post("/rrg")
async def rrg(req: RRGRequest):
    return await asyncio.to_thread(_core_rrg, req)


class VolumeProfileRequest(BaseModel):
    ticker: str
    from_date: str
    to_date: str
    bins: int = 24


def _core_volume_profile(req: VolumeProfileRequest) -> dict:
    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)
    tkr = req.ticker.strip().upper()
    nbins = max(6, min(int(req.bins), 60))

    conn, owns = _acquire_readonly(lambda *a, **k: None)
    try:
        df = _load_prepared(conn, from_dt, to_dt, 5, [tkr], need_market_relative=False)
    finally:
        if owns:
            try:
                conn.close()
            except Exception:
                pass

    if df is None or df.empty:
        return {"mode": MODE, "ticker": tkr, "bins": [], "ohlc": []}

    sub = df[(df["ticker"] == tkr) & (df["date"] >= from_ts) & (df["date"] <= to_ts)].sort_values("date").copy()
    if sub.empty:
        return {"mode": MODE, "ticker": tkr, "bins": [], "ohlc": []}

    tp = (sub["high"] + sub["low"] + sub["close"]) / 3.0       # typical price per bar
    lo, hi = float(sub["low"].min()), float(sub["high"].max())
    if hi <= lo:
        hi = lo + 1.0
    edges = np.linspace(lo, hi, nbins + 1)
    idx = np.clip(np.digitize(tp.to_numpy(), edges) - 1, 0, nbins - 1)
    vol = sub["volume"].to_numpy(dtype=float)
    bucket_vol = np.zeros(nbins)
    for i, v in zip(idx, vol):
        bucket_vol[i] += v

    total_v = float(bucket_vol.sum()) or 1.0
    poc_i = int(np.argmax(bucket_vol))
    mean_v = bucket_vol.mean()
    bins = [{
        "price_lo": round(float(edges[i]), 2),
        "price_hi": round(float(edges[i + 1]), 2),
        "price_mid": round(float((edges[i] + edges[i + 1]) / 2), 2),
        "volume": round(float(bucket_vol[i]), 2),
        "pct": round(bucket_vol[i] / total_v * 100, 2),
        "node": "HVN" if bucket_vol[i] >= mean_v else "LVN",   # high/low volume node
        "poc": i == poc_i,                                     # point of control
    } for i in range(nbins)]

    # Anchored VWAP from the window start (cumulative typical-price × volume).
    cum_pv = (tp * sub["volume"]).cumsum()
    cum_v = sub["volume"].cumsum().replace(0, np.nan)
    avwap = (cum_pv / cum_v)
    ohlc = [{
        "date": str(r["date"])[:10],
        "open": _jsafe(r["open"]), "high": _jsafe(r["high"]),
        "low": _jsafe(r["low"]), "close": _jsafe(r["close"]),
        "avwap": _jsafe(a),
    } for (_, r), a in zip(sub.iterrows(), avwap.to_numpy())]

    return {
        "mode": MODE, "ticker": tkr, "n_bars": len(sub),
        "price_lo": round(lo, 2), "price_hi": round(hi, 2),
        "poc_price": round(float((edges[poc_i] + edges[poc_i + 1]) / 2), 2),
        "bins": bins, "ohlc": ohlc,
    }


@router.post("/volume-profile")
async def volume_profile(req: VolumeProfileRequest):
    return await asyncio.to_thread(_core_volume_profile, req)
