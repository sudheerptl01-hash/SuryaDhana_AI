"""
Analytics — institutional Backtest Lab.

Capital-managed, friction-aware, risk-controlled historical simulation over the
DuckDB OHLCV + fundamentals tables. The deterministic math lives in
`backtest_engine` (unit-tested); this module owns DuckDB I/O, request contracts,
the synchronous endpoints, and an NDJSON streaming endpoint for live progress.

MODE = PAPER at all times — nothing here places an order.
"""
import asyncio
import json
import os
import queue
import shutil
import threading
import time
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


class WFOBacktestRequest(BacktestRequest):
    in_sample_days: int = 180
    out_sample_days: int = 60
    monte_carlo_runs: int = 1000


# ── DuckDB load + indicator prep ──────────────────────────────────────────────────

# Factors whose computation needs the (heavier) cross-sectional market/sector
# composites. Computed lazily so a vanilla technical backtest stays fast.
MARKET_RELATIVE_FIELDS: set[str] = {
    "sector_rel_mom_14_pct", "corr_nifty_30",
    "sector_positive_regime", "decoupled_leader",
}


def _load_prepared(con, from_dt, to_dt, forward_days: int, scope_tickers: Optional[list[str]],
                   need_market_relative: bool = False):
    """Load OHLCV (+warm-up / forward look) and attach trailing indicators.

    `need_market_relative` gates the cross-sectional sector/market-coupling pass
    (rolling correlation over the whole frame) so it only runs when a filter or a
    factor profile actually references those columns.
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
        """SELECT ticker, pe_ratio, roce_pct, div_yld_pct, mktcap_cr FROM stock_metrics
           WHERE ticker IS NOT NULL ORDER BY as_of_date NULLS FIRST"""
    ).fetchall()
    mdf = pd.DataFrame(metrics_rows, columns=["ticker", "pe_ratio", "roce_pct", "div_yld_pct", "mktcap_cr"])
    # stock_metrics has duplicate tickers (e.g. RELIANCE x3). A naive merge fans
    # out OHLCV rows into duplicate same-day candidates → capital-destroying key
    # collisions in the sim. Keep only the latest snapshot per ticker.
    mdf = mdf.drop_duplicates(subset=["ticker"], keep="last")
    df = df.merge(mdf, on="ticker", how="left")

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

    # 2) Equal-weight top-100 proxy
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
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)

    scope_tickers = [t.upper() for t in req.tickers] if req.scope == "watchlist" else None
    if req.scope == "watchlist" and not scope_tickers:
        raise HTTPException(status_code=400, detail="Watchlist scope selected but no tickers provided")

    # Compliance floor: clamp friction to >= 15 bps (0.15%) regardless of payload.
    friction = max(float(req.friction_bps), MIN_FRICTION_BPS)

    need_mr = any(fc.field in MARKET_RELATIVE_FIELDS for fc in req.filters)

    progress(5, "Connecting to market database")
    con, owns = _acquire_readonly(progress)
    try:
        progress(10, "Loading OHLCV history")
        df = _load_prepared(con, from_dt, to_dt, req.forward_days, scope_tickers,
                            need_market_relative=need_mr)
        if df is None or df.empty:
            return _empty_result(req)
        progress(28, "Computing trailing indicators")
        bench_daily, bench_source = _build_benchmark(con, from_ts, to_ts)
        try:
            fund_as_of = con.execute("SELECT MAX(as_of_date) FROM stock_metrics").fetchone()[0]
        except Exception:
            fund_as_of = None
    finally:
        if owns:
            try:
                con.close()
            except Exception:
                pass

    # Global trading calendar + per-ticker chronological arrays (point-in-time safe)
    all_dates = sorted(df["date"].unique())
    date_to_gidx = {d: i for i, d in enumerate(all_dates)}

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
        }

    def price_at(idx: int, ticker: str) -> Optional[float]:
        s = tkr_series.get(ticker)
        if not s:
            return None
        return s["close_by_gidx"].get(int(idx))

    # Build resolved entry candidates per day
    in_range = df[(df["date"] >= from_ts) & (df["date"] <= to_ts)].copy()
    filters = [fc.model_dump() for fc in req.filters]
    fund_active = be.fundamental_filters_active(filters)

    entries_by_idx: dict[int, list[dict]] = {}
    grouped = list(in_range.groupby("date"))
    n_groups = max(len(grouped), 1)
    last_year = None
    for gi, (entry_date, day_df) in enumerate(grouped):
        candidates = be.apply_filters(day_df, filters)
        if candidates.empty:
            continue
        # Defensive: never allow the same ticker twice in one day's candidate set.
        candidates = candidates.drop_duplicates(subset=["ticker"], keep="first")
        if "mktcap_cr" in candidates.columns:
            candidates = candidates.sort_values("mktcap_cr", ascending=False, na_position="last")
        candidates = candidates.head(req.max_stocks_per_day)

        next_open = (req.entry_timing == "next_open")
        sig = date_to_gidx[entry_date]   # the day the signal fires (filters evaluated here)
        for _, row in candidates.iterrows():
            tkr = row["ticker"]
            s = tkr_series.get(tkr)
            if not s:
                continue
            lp_sig = s["gidx_to_lp"].get(int(sig))
            if lp_sig is None:
                continue
            # next_open enters the bar AFTER the signal (no same-bar look-ahead);
            # "close" enters on the signal bar's close.
            entry_lp = lp_sig + 1 if next_open else lp_sig
            if entry_lp + 1 >= len(s["close"]):   # need the entry bar + ≥1 forward bar
                continue
            entry_price = float(s["open"][entry_lp]) if next_open else float(s["close"][entry_lp])
            fwd = slice(entry_lp + 1, entry_lp + 1 + req.forward_days)
            fwd_hi, fwd_lo, fwd_cl, fwd_op = s["high"][fwd], s["low"][fwd], s["close"][fwd], s["open"][fwd]
            if len(fwd_cl) == 0:
                continue
            ex = be.resolve_trade_exit(
                fwd_hi, fwd_lo, fwd_cl, entry_price, req.forward_days,
                friction_bps=friction, stop_loss_pct=req.stop_loss_pct,
                trailing_stop_pct=req.trailing_stop_pct, win_threshold=req.win_threshold,
                opens=fwd_op,
            )
            entry_gidx = int(s["gidx"][entry_lp])
            exit_gidx = int(s["gidx"][entry_lp + ex["holding_days"]])
            entries_by_idx.setdefault(entry_gidx, []).append({
                "ticker": tkr,
                "entry_price": round(entry_price, 4),
                "exit_price": ex["exit_price"],
                "exit_idx": exit_gidx,
                "net_return_pct": ex["net_return_pct"],
                "gross_return_pct": ex["gross_return_pct"],
                "holding_days": ex["holding_days"],
                "exit_reason": ex["exit_reason"],
                "win_threshold": req.win_threshold,
                "entry_date": str(all_dates[entry_gidx])[:10],
                "exit_date": str(all_dates[exit_gidx])[:10],
            })

        yr = pd.Timestamp(entry_date).year
        if yr != last_year:
            last_year = yr
            progress(28 + 42 * (gi / n_groups), f"Simulating {yr}")

    # Capital-managed compounding simulation
    progress(74, "Running capital-managed portfolio simulation")
    gidxs = [date_to_gidx[d] for d in all_dates if from_ts <= d <= to_ts]
    if not gidxs:
        return _empty_result(req)
    from_idx, to_idx = min(gidxs), max(gidxs)
    equity, trades = be.simulate_portfolio(
        all_dates, from_idx, to_idx, entries_by_idx, price_at,
        starting_capital=req.starting_capital, max_positions=req.max_positions,
        max_drawdown_halt_pct=req.max_drawdown_halt_pct,
    )

    # Tag every trade with its sector (for the blotter's sector grouping / export).
    sec = _sector_map()
    for t in trades:
        t["sector"] = sec.get(str(t.get("ticker", "")).upper(), "Unknown")

    # Benchmark NAV aligned to equity dates + drawdown profile
    progress(88, "Aligning benchmark & computing analytics")
    equity_dates = [e["date"] for e in equity]
    bench_nav = be.equal_weight_benchmark_nav(bench_daily, equity_dates, req.starting_capital)
    nav_series = [e["nav"] for e in equity] or [req.starting_capital]
    run_max = np.maximum.accumulate(np.asarray(nav_series, dtype=float))
    for i, e in enumerate(equity):
        e["benchmark_nav"] = bench_nav[i]
        e["drawdown_pct"] = round((nav_series[i] / run_max[i] - 1) * 100, 2)

    metrics = be.compute_metrics(equity, trades, bench_nav, req.starting_capital)
    progress(100, "Done")

    return {
        "mode": MODE,
        "config": {
            "from_date": req.from_date, "to_date": req.to_date,
            "forward_days": req.forward_days, "win_threshold": req.win_threshold,
            "starting_capital": req.starting_capital, "friction_bps": friction,
            "stop_loss_pct": req.stop_loss_pct, "trailing_stop_pct": req.trailing_stop_pct,
            "max_positions": req.max_positions, "max_drawdown_halt_pct": req.max_drawdown_halt_pct,
            "scope": req.scope, "entry_timing": req.entry_timing,
            "n_tickers": int(df["ticker"].nunique()),
            "benchmark_label": bench_source,
            "fundamentals_as_of": str(fund_as_of) if fund_as_of else None,
        },
        "fundamental_lookahead_active": fund_active,
        **metrics,
        "equity_curve": equity,
        "trades": trades[-1000:],
        "_all_trades": trades,  # internal, stripped before WFO/JSON if large
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


def _augment_wfo(result: dict, req: WFOBacktestRequest, on_progress=None) -> dict:
    """Slice the continuous sim into out-of-sample windows + Monte Carlo."""
    all_trades = result.pop("_all_trades", result.get("trades", []))
    rets = [t["return_pct"] for t in all_trades]

    from_dt = datetime.strptime(req.from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(req.to_date, "%Y-%m-%d").date()

    windows = []
    cur = from_dt
    while cur <= to_dt:
        w_end = min(cur + timedelta(days=req.out_sample_days), to_dt)
        windows.append((cur, w_end))
        cur = w_end + timedelta(days=1)

    wfo_windows = []
    for w_start, w_end in windows:
        s, e = str(w_start), str(w_end)
        w_trades = [t for t in all_trades if s <= t["exit_date"] <= e]
        if not w_trades:
            continue
        w_rets = [t["return_pct"] for t in w_trades]
        w_wins = sum(1 for t in w_trades if t["is_win"])
        wfo_windows.append({
            "start": s, "end": e, "trades": len(w_trades),
            "return_pct": round(sum(w_rets) / len(w_rets), 2),
            "total_return_pct": round(sum(w_rets), 2),
            "win_rate": round(w_wins / len(w_trades) * 100, 1),
            "best": round(max(w_rets), 2), "worst": round(min(w_rets), 2),
        })

    if on_progress:
        on_progress({"event": "progress", "pct": 95, "label": "Monte Carlo simulation"})
    result["wfo_windows"] = wfo_windows
    result["monte_carlo"] = be.monte_carlo_drawdowns(rets, req.monte_carlo_runs)
    return result


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
        result = _core_backtest(req)
        return _strip_internal(_augment_wfo(result, req))
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
            result = _core_backtest(req, on_progress)
            if is_wfo:
                result = _augment_wfo(result, req, on_progress)
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
