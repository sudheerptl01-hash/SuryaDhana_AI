"""
backtest_engine.py — Institutional-grade simulation core for the Backtest Lab.

Pure-Python / numpy / pandas. No FastAPI, no DuckDB imports here so the math is
unit-testable in isolation (see tests/test_backtest_engine.py). All I/O (DuckDB
loads, HTTP, streaming) lives in routers/analytics.py.

Design pillars enforced here:
  1. Friction realism      — every trade's return is net of a round-trip cost.
  2. Risk controls         — stop-loss, trailing-stop, time-stop trade resolution.
  3. Capital compounding   — finite capital, max concurrent positions, MTM NAV.
  4. Benchmark + factors   — equal-weight benchmark, beta/alpha (Jensen, rf=0).
  5. Bias isolation        — fundamental fields are tagged separately from
                             trailing/point-in-time technicals.

MODE is always PAPER: this module never places an order, it only replays history.
"""
from __future__ import annotations

from typing import Callable, Optional, Any
import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Fundamental fields come from a single current snapshot (stock_metrics) and are
# therefore NOT point-in-time. Technicals below are trailing and bias-free.
FUNDAMENTAL_FIELDS: set[str] = {"pe_ratio", "div_yld_pct", "mktcap_cr", "roce_pct"}

# Numeric filter field -> dataframe column produced by compute_indicators()
# / compute_market_relative(). Every column here is strictly trailing (no
# look-ahead): the value on day T only consumes prices/volume up to and incl. T.
FIELD_MAP: dict[str, str] = {
    "pe_ratio": "pe_ratio",
    "div_yld_pct": "div_yld_pct",
    "mktcap_cr": "mktcap_cr",
    "roce_pct": "roce_pct",
    "rsi_14": "rsi_14",
    "atr_14_pct": "atr_pct",
    "above_52w_low_pct": "above_52w_low_pct",
    "within_52w_high_pct": "within_52w_high_pct",
    "dist_ma200_pct": "dist_ma200_pct",
    # ── Advanced alpha factors (Pillar 1) ──────────────────────────────────
    "vmi_ratio": "vmi_ratio",                       # Volume Market Impact ratio
    "vol_zscore_20": "vol_zscore_20",               # VIPT volume thrust z-score
    "intraday_intention": "intraday_intention",     # 3-day aggregated close-location value
    "squeeze_ratio": "squeeze_ratio",               # BB-width / KC-width (<1 ⇒ compression)
    "sector_rel_mom_14_pct": "sector_rel_mom_14_pct",  # 14d momentum vs sector composite
    "corr_nifty_30": "corr_nifty_30",               # rolling 30d Pearson corr to market
}


def _boolcol(name: str) -> "Callable[[pd.DataFrame], pd.Series]":
    """
    Predicate that reads a *pre-computed* boolean column, degrading to all-False
    when the column is absent (e.g. compute_market_relative wasn't run). Keeps
    apply_filters crash-proof on partially-prepared frames.
    """
    def _pred(d: pd.DataFrame) -> "pd.Series":
        if name in d.columns:
            return d[name].fillna(False).astype(bool)
        return pd.Series(False, index=d.index)
    return _pred


# Boolean toggle filters -> vectorised predicate over the day's dataframe
BOOLEAN_FILTERS: dict[str, Callable[[pd.DataFrame], "pd.Series[bool]"]] = {
    "price_gt_ma50": lambda d: d["close"] > d["ma50"],
    "price_gt_ma200": lambda d: d["close"] > d["ma200"],
    "ma50_gt_ma200": lambda d: d["ma50"] > d["ma200"],
    "volume_gt_avg": lambda d: d["volume"] > d["vol20"],
    # ── Advanced alpha factors (Pillar 1) ──────────────────────────────────
    "vipt_breakout": _boolcol("vipt_breakout"),                # N-day breakout on >3σ volume
    "squeeze_on": _boolcol("squeeze_on"),                      # Bollinger inside Keltner
    "intention_pullback": _boolcol("intention_pullback"),      # high CLV during 3-day dip
    "sector_positive_regime": _boolcol("sector_positive_regime"),  # sector composite mom > 0
    "decoupled_leader": _boolcol("decoupled_leader"),          # low corr in a market pullback
}


# ── Indicator engine (trailing / point-in-time, no look-ahead) ──────────────────

def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder-style RSI on a 1-D close array; trailing only."""
    if len(prices) < 2:
        return np.full(len(prices), np.nan)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = pd.Series(gains).rolling(window=period, min_periods=period).mean()
    avg_loss = pd.Series(losses).rolling(window=period, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([[np.nan], rsi.values])


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach trailing technical indicators. Input columns required:
    ticker, date, close, volume, high, low. All rolling windows are strictly
    backward-looking, so there is zero look-ahead on technicals.
    """
    df = df.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker")

    df["ma50"] = g["close"].transform(lambda x: x.rolling(50, min_periods=20).mean())
    df["ma200"] = g["close"].transform(lambda x: x.rolling(200, min_periods=50).mean())
    df["vol20"] = g["volume"].transform(lambda x: x.rolling(20, min_periods=5).mean())
    df["low52w"] = g["low"].transform(lambda x: x.rolling(252, min_periods=50).min())
    df["hi52w"] = g["high"].transform(lambda x: x.rolling(252, min_periods=50).max())
    df["rsi_14"] = g["close"].transform(lambda x: pd.Series(_rsi(x.values, 14), index=x.index))

    # ATR(14) from true range. Fully vectorised + per-ticker grouped rolling — robust
    # for a single-ticker frame (a 1-name watchlist must not crash the sim) and any
    # ticker count. prev-close is the grouped shift so true range never bleeds across
    # ticker boundaries.
    prev_close = g["close"].shift(1)
    true_range = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = true_range.groupby(df["ticker"]).transform(
        lambda x: x.rolling(14, min_periods=14).mean())
    df["atr"] = df["atr"].fillna(0.0)
    df["atr_pct"] = (df["atr"] / df["close"] * 100).fillna(0.0)
    df["dist_ma200_pct"] = ((df["close"] - df["ma200"]) / df["ma200"] * 100).fillna(0.0)
    df["above_52w_low_pct"] = ((df["close"] - df["low52w"]) / df["low52w"] * 100).fillna(0.0)
    df["within_52w_high_pct"] = ((df["hi52w"] - df["close"]) / df["hi52w"] * 100).fillna(0.0)

    _compute_advanced_factors(df, g)
    return df


def _compute_advanced_factors(df: pd.DataFrame, g) -> None:
    """
    Attach the Pillar-1 structural alpha factors in place. Every window below is
    strictly backward-looking. Division-by-zero / flat-bar / warm-up cases resolve
    to NaN (numeric) or False (boolean) so a degenerate row never breaks the sim.

    `g` is the (ticker)-groupby of `df` created by the caller; we also build a few
    fresh groupbys for columns added after `g` was constructed.
    """
    if df.empty:
        for c in ("dollar_vol", "vmi_ratio", "vol_zscore_20", "intraday_intention", "squeeze_ratio"):
            df[c] = pd.Series(dtype=float)
        for c in ("vipt_breakout", "squeeze_on", "intention_pullback"):
            df[c] = pd.Series(dtype=bool)
        return

    # ── Volume Market Impact (VMI) ────────────────────────────────────────────
    # VMI = (dollarVol_T / mean_20d dollarVol) / ATR%_T. Captures an outsized print
    # relative to its own liquidity baseline, dampened by the name's volatility.
    df["dollar_vol"] = df["close"] * df["volume"]
    gdv = df.groupby("ticker")["dollar_vol"]
    adv20 = gdv.transform(lambda x: x.rolling(20, min_periods=10).mean()).to_numpy()
    dv = df["dollar_vol"].to_numpy()
    atr_pct = df["atr_pct"].to_numpy()
    rel_dv = np.full(dv.shape, np.nan)
    np.divide(dv, adv20, out=rel_dv, where=adv20 > 0)
    vmi = np.full(dv.shape, np.nan)
    np.divide(rel_dv, atr_pct, out=vmi, where=atr_pct > 0)
    df["vmi_ratio"] = vmi

    # ── Volume-Induced Price Thrust (VIPT) ────────────────────────────────────
    # Volume z-score vs the *prior* 20-day baseline (shift(1) → today excluded, so
    # the spike is measured against an established mean, never against itself).
    gvol = df.groupby("ticker")["volume"]
    vmean_prev = gvol.transform(lambda x: x.shift(1).rolling(20, min_periods=10).mean())
    vstd_prev = gvol.transform(lambda x: x.shift(1).rolling(20, min_periods=10).std())
    df["vol_zscore_20"] = np.where(vstd_prev > 0, (df["volume"] - vmean_prev) / vstd_prev, np.nan)
    # Breakout out of an N=20-day consolidation: close clears the prior 20-day high
    # on a >3σ volume thrust. Prior high uses shift(1) so the break is genuine.
    prior_high = df.groupby("ticker")["high"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=10).max())
    df["vipt_breakout"] = (
        (df["close"] > prior_high) & (df["vol_zscore_20"] > 3.0)
    ).fillna(False)

    # ── Intraday Intention (3-day aggregated close-location value) ─────────────
    # CLV_t = (C-L)/(H-L) ∈ [0,1]; flat bars (H==L) are undefined → NaN. The 3-day
    # mean skips NaNs (nanmean) and only emits NaN when *all* 3 bars are flat.
    rng = (df["high"] - df["low"]).to_numpy()
    clv = np.full(rng.shape, np.nan)
    np.divide((df["close"].to_numpy() - df["low"].to_numpy()), rng, out=clv, where=rng > 0)
    df["_clv"] = clv

    def _nanmean3(x: np.ndarray) -> float:
        return float(np.nanmean(x)) if np.isfinite(x).any() else np.nan

    df["intraday_intention"] = df.groupby("ticker")["_clv"].transform(
        lambda s: s.rolling(3, min_periods=1).apply(_nanmean3, raw=True))
    close_3ago = g["close"].transform(lambda x: x.shift(3))
    # Setup: buyers defending the close (>0.8) through a 3-day price pullback.
    df["intention_pullback"] = (
        (df["intraday_intention"] > 0.8) & (df["close"] < close_3ago)
    ).fillna(False)

    # ── Volatility Compression (the Squeeze: Bollinger inside Keltner) ─────────
    ma20 = g["close"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    std20 = g["close"].transform(lambda x: x.rolling(20, min_periods=20).std())
    bb_w = 4.0 * std20                 # Bollinger(20, 2σ) full width = 4σ
    kc_w = 3.0 * df["atr"]             # Keltner(20, 1.5·ATR) full width = 3·ATR
    df["squeeze_ratio"] = np.where(kc_w > 0, bb_w / kc_w, np.nan)
    bb_u, bb_l = ma20 + 2 * std20, ma20 - 2 * std20
    kc_u, kc_l = ma20 + 1.5 * df["atr"], ma20 - 1.5 * df["atr"]
    df["squeeze_on"] = ((bb_u < kc_u) & (bb_l > kc_l)).fillna(False)

    df.drop(columns=["_clv"], inplace=True, errors="ignore")


def compute_market_relative(
    df: pd.DataFrame,
    sector_of: dict[str, str],
    mom_window: int = 14,
    corr_window: int = 30,
    market_ret_by_date: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Attach reference-relative factors (Sector Momentum Dispersion + Beta-Adjusted
    Market Coupling). No external index is required: the *market* is the equal-weight
    daily return of the loaded constituents and each *sector* is the equal-weight
    return of its members (sector_of: TICKER→sector). A real index can be injected
    via `market_ret_by_date` (date→daily return) to override the internal proxy.

    Bias note: the day-T market/sector composite uses only day-T constituent returns
    (a contemporaneous cross-sectional average — not look-ahead). The rolling
    correlation/momentum windows are strictly trailing.
    """
    if df is None or df.empty:
        return df
    df = df.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker")

    df["ret_1d"] = g["close"].transform(lambda x: x.pct_change())

    if market_ret_by_date is None:
        market_ret_by_date = df.groupby("date")["ret_1d"].mean().to_dict()
    df["mkt_ret_1d"] = df["date"].map(market_ret_by_date).astype(float)

    # Market index level (for a trailing 5-day market return used by the de-coupling
    # regime flag). Built once from the daily series, then mapped back by date.
    mser = pd.Series(market_ret_by_date, dtype=float).sort_index()
    mlevel = (1.0 + mser.fillna(0.0)).cumprod()
    mret5 = (mlevel / mlevel.shift(5) - 1.0)
    df["mkt_ret5"] = df["date"].map(mret5.to_dict()).astype(float)

    # ── Sector Momentum Dispersion ────────────────────────────────────────────
    df["_mom14"] = g["close"].transform(lambda x: x.pct_change(mom_window)) * 100.0
    df["_sector"] = df["ticker"].astype(str).str.upper().map(sector_of).fillna("Unknown")
    df["_sector_mom14"] = df.groupby(["_sector", "date"])["_mom14"].transform("mean")
    df["sector_rel_mom_14_pct"] = (df["_mom14"] - df["_sector_mom14"]).astype(float)
    df["sector_positive_regime"] = (df["_sector_mom14"] > 0).fillna(False)

    # ── Beta-Adjusted Market Coupling (rolling 30d Pearson corr to the market) ──
    def _roll_corr(s: pd.DataFrame) -> pd.Series:
        return s["ret_1d"].rolling(corr_window, min_periods=corr_window).corr(s["mkt_ret_1d"])

    corr = df.groupby("ticker", group_keys=False)[["ret_1d", "mkt_ret_1d"]].apply(_roll_corr)
    df["corr_nifty_30"] = corr.reindex(df.index).astype(float)

    # De-coupled leader: correlation collapses (<0.2) while the market is pulling
    # back (5d<0) yet the name itself holds positive idiosyncratic momentum (5d>0).
    df["_ret5"] = g["close"].transform(lambda x: x.pct_change(5))
    df["decoupled_leader"] = (
        (df["corr_nifty_30"] < 0.2) & (df["mkt_ret5"] < 0) & (df["_ret5"] > 0)
    ).fillna(False)

    df.drop(columns=["_mom14", "_sector", "_sector_mom14", "_ret5"], inplace=True, errors="ignore")
    return df


def apply_filters(day_df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    """Apply numeric + boolean filters (AND) to one day's candidate rows."""
    candidates = day_df
    for fc in filters:
        field, op, value = fc["field"], fc.get("op", "gt"), fc.get("value", 0.0)
        if field in FIELD_MAP:
            col = FIELD_MAP[field]
            if op == "lt":
                candidates = candidates[candidates[col] < value]
            elif op == "gt":
                candidates = candidates[candidates[col] > value]
            elif op == "lte":
                candidates = candidates[candidates[col] <= value]
            elif op == "gte":
                candidates = candidates[candidates[col] >= value]
        elif field in BOOLEAN_FILTERS:
            candidates = candidates[BOOLEAN_FILTERS[field](candidates)]
    return candidates


def fundamental_filters_active(filters: list[dict]) -> bool:
    return any(fc.get("field") in FUNDAMENTAL_FIELDS for fc in filters)


# ── Trade-level risk engine ─────────────────────────────────────────────────────

def resolve_trade_exit(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    entry_price: float,
    forward_days: int,
    friction_bps: float = 15.0,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    win_threshold: float = 0.0,
    opens: Optional[np.ndarray] = None,
) -> dict:
    """
    Resolve a single trade's exit under real trading physics.

    Walks the forward price path (day 1..N). Priority each day:
      1. Stop-loss   — if the day's LOW pierces entry*(1 - sl%), fill at the stop.
      2. Trailing    — else if LOW pierces peak*(1 - trail%), fill at the trail level.
      3. Time-stop   — if neither triggers by day N, exit at the Nth close.

    Gap realism: if `opens` is supplied and the bar OPENS already below the stop
    level (overnight gap-down), the fill is the open, not the stop — you cannot
    fill better than where the market reopened.

    `peak` trails the highest HIGH seen on *prior* days (conservative: a high that
    occurs the same day as the low cannot be assumed to precede it). Returns are
    net of `friction_bps` round-trip (basis points, e.g. 15 = 0.15%).
    """
    n = min(forward_days, len(closes))
    exit_price = float(closes[n - 1]) if n > 0 else float(entry_price)
    holding = n
    reason = "time_stop"
    peak = float(entry_price)

    for i in range(n):
        hi, lo = float(highs[i]), float(lows[i])
        op = float(opens[i]) if (opens is not None and i < len(opens)) else None
        sl_price = entry_price * (1 - stop_loss_pct / 100.0) if stop_loss_pct else None
        trail_price = peak * (1 - trailing_stop_pct / 100.0) if trailing_stop_pct else None

        if sl_price is not None and lo <= sl_price:
            fill = sl_price if (op is None or op >= sl_price) else op   # gap-down → fill at open
            exit_price, holding, reason = fill, i + 1, "stop_loss"
            break
        if trail_price is not None and lo <= trail_price:
            fill = trail_price if (op is None or op >= trail_price) else op
            exit_price, holding, reason = fill, i + 1, "trailing_stop"
            break
        peak = max(peak, hi)  # trail off prior peaks only

    gross_return_pct = (exit_price - entry_price) / entry_price * 100.0
    net_return_pct = gross_return_pct - friction_bps / 100.0  # round-trip friction
    return {
        "exit_price": round(float(exit_price), 4),
        "gross_return_pct": round(gross_return_pct, 4),
        "net_return_pct": round(net_return_pct, 4),
        "holding_days": int(holding),
        "exit_reason": reason,
        "is_win": bool(net_return_pct > win_threshold),
    }


# ── Capital-managed compounding portfolio simulation ────────────────────────────

def simulate_portfolio(
    all_dates: list,
    from_idx: int,
    to_idx: int,
    entries_by_idx: dict[int, list[dict]],
    price_at: Callable[[int, str], Optional[float]],
    starting_capital: float = 10_000_000.0,
    max_positions: int = 5,
    max_drawdown_halt_pct: Optional[float] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Event-driven, finite-capital portfolio simulation with daily mark-to-market.

    entries_by_idx[idx] = ordered list of candidate dicts, each:
        {ticker, entry_price, exit_idx, net_return_pct, gross_return_pct,
         exit_price, exit_reason, entry_date, exit_date}

    Sizing: each new position is allocated min(cash, NAV / max_positions).
    Positions are capped at `max_positions` concurrent. Exits realise proceeds
    back to cash; the equity curve is the true compounded NAV (cash + MTM longs).

    Returns (equity_curve, trades). The calendar auto-extends past `to_idx` to let
    late entries fully wind down, so every entered trade is realised.
    """
    cash = float(starting_capital)
    peak_nav = float(starting_capital)
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    equity: list[dict] = []

    last_exit_idx = to_idx
    for idx in range(from_idx, to_idx + 1):
        for cand in entries_by_idx.get(idx, []):
            last_exit_idx = max(last_exit_idx, cand["exit_idx"])
    end_idx = min(len(all_dates) - 1, last_exit_idx)

    def _mtm_nav() -> float:
        total = cash
        for p in open_pos.values():
            px = price_at(p["mtm_idx_ticker_idx"], p["ticker"])
            total += p["shares"] * (px if px is not None else p["entry_price"])
        return total

    for idx in range(from_idx, end_idx + 1):
        date = all_dates[idx]

        # 1) Exits first (free up capital before sizing new entries)
        for pid in [k for k, p in open_pos.items() if p["exit_idx"] == idx]:
            p = open_pos.pop(pid)
            proceeds = p["alloc"] * (1 + p["net_return_pct"] / 100.0)
            cash += proceeds
            trades.append({
                "entry_date": p["entry_date"],
                "exit_date": p["exit_date"],
                "ticker": p["ticker"],
                "entry_price": round(p["entry_price"], 2),
                "exit_price": round(p["exit_price"], 2),
                "gross_return_pct": round(p["gross_return_pct"], 2),
                "return_pct": round(p["net_return_pct"], 2),
                "holding_days": p["holding_days"],
                "exit_reason": p["exit_reason"],
                "capital_allocated": round(p["alloc"], 2),
                "pnl": round(proceeds - p["alloc"], 2),
                "is_win": bool(p["net_return_pct"] > p["win_threshold"]),
            })

        # update MTM index pointer for open positions to today
        for p in open_pos.values():
            p["mtm_idx_ticker_idx"] = idx

        # 2) Risk gate + entries (only within the requested [from, to] window).
        # Mark-to-market NAV drives both position sizing and the drawdown halt.
        nav = cash
        for p in open_pos.values():
            px = price_at(idx, p["ticker"])
            nav += p["shares"] * (px if px is not None else p["entry_price"])
        peak_nav = max(peak_nav, nav)
        dd_halt = (
            max_drawdown_halt_pct is not None and peak_nav > 0
            and (nav / peak_nav - 1) * 100.0 <= -abs(max_drawdown_halt_pct)
        )
        if from_idx <= idx <= to_idx and not dd_halt and len(open_pos) < max_positions:
            held = {p["ticker"] for p in open_pos.values()}
            for cand in entries_by_idx.get(idx, []):
                if len(open_pos) >= max_positions or cash <= 1.0:
                    break
                # No double-holding the same name (also makes the open_pos key safe).
                if cand["ticker"] in held:
                    continue
                alloc = min(cash, nav / max_positions)
                if alloc < 1.0 or cand["entry_price"] <= 0:
                    continue
                held.add(cand["ticker"])
                shares = alloc / cand["entry_price"]
                cash -= alloc
                open_pos[f"{idx}-{cand['ticker']}"] = {
                    "ticker": cand["ticker"],
                    "entry_date": cand["entry_date"],
                    "exit_date": cand["exit_date"],
                    "exit_idx": cand["exit_idx"],
                    "entry_price": cand["entry_price"],
                    "exit_price": cand["exit_price"],
                    "net_return_pct": cand["net_return_pct"],
                    "gross_return_pct": cand["gross_return_pct"],
                    "holding_days": cand["holding_days"],
                    "exit_reason": cand["exit_reason"],
                    "win_threshold": cand.get("win_threshold", 0.0),
                    "alloc": alloc,
                    "shares": shares,
                    "mtm_idx_ticker_idx": idx,
                }

        # 3) Mark-to-market NAV snapshot
        nav = cash
        for p in open_pos.values():
            px = price_at(idx, p["ticker"])
            nav += p["shares"] * (px if px is not None else p["entry_price"])
        equity.append({
            "date": str(date)[:10],
            "nav": round(nav, 2),
            "cash": round(cash, 2),
            "positions": len(open_pos),
        })

    return equity, trades


# ── Benchmark + risk/return analytics ───────────────────────────────────────────

def equal_weight_benchmark_nav(
    daily_returns_by_date: dict[str, float],
    equity_dates: list[str],
    starting_capital: float,
) -> list[float]:
    """Compound an equal-weight benchmark NAV aligned to the portfolio dates."""
    nav = starting_capital
    out: list[float] = []
    for d in equity_dates:
        r = daily_returns_by_date.get(d, 0.0)
        nav *= (1 + r)
        out.append(round(nav, 2))
    return out


def daily_returns(nav: list[float]) -> np.ndarray:
    arr = np.asarray(nav, dtype=float)
    if len(arr) < 2:
        return np.array([])
    return arr[1:] / arr[:-1] - 1.0


def max_drawdown(nav: list[float]) -> float:
    """Maximum peak-to-trough drawdown of a NAV series, as a negative %."""
    arr = np.asarray(nav, dtype=float)
    if len(arr) == 0:
        return 0.0
    running_max = np.maximum.accumulate(arr)
    dd = (arr / running_max - 1.0) * 100.0
    return float(np.min(dd))


def max_drawdown_duration(nav: list[float]) -> int:
    """
    Longest peak-to-recovery span in trading days: the max number of periods the
    NAV spent below a prior peak before reclaiming it (or until series end if it
    never recovers).
    """
    arr = np.asarray(nav, dtype=float)
    if len(arr) < 2:
        return 0
    peak = arr[0]
    peak_idx = 0
    max_dur = 0
    underwater = False
    for i in range(1, len(arr)):
        if arr[i] < peak:
            underwater = True
            max_dur = max(max_dur, i - peak_idx)          # ongoing underwater span
        elif arr[i] >= peak:
            if underwater:
                max_dur = max(max_dur, i - peak_idx)       # include the recovery day
            peak = arr[i]
            peak_idx = i
            underwater = False
    return int(max_dur)


def beta_alpha(port_rets: np.ndarray, bench_rets: np.ndarray) -> tuple[float, float]:
    """
    Jensen's alpha & beta (risk-free = 0). Beta = cov(p,b)/var(b).
    Alpha is annualised and returned in percent.
    """
    n = min(len(port_rets), len(bench_rets))
    if n < 2:
        return 0.0, 0.0
    p = np.asarray(port_rets[:n], dtype=float)
    b = np.asarray(bench_rets[:n], dtype=float)
    var_b = np.var(b)
    if var_b < 1e-12:
        return 0.0, 0.0
    beta = float(np.cov(p, b, bias=True)[0, 1] / var_b)
    alpha_daily = float(np.mean(p) - beta * np.mean(b))
    alpha_annual_pct = alpha_daily * TRADING_DAYS * 100.0
    return round(beta, 3), round(alpha_annual_pct, 2)


def sharpe(port_rets: np.ndarray) -> float:
    if len(port_rets) < 2:
        return 0.0
    sd = float(np.std(port_rets, ddof=1))
    if sd < 1e-12:
        return 0.0
    return round(float(np.mean(port_rets)) / sd * np.sqrt(TRADING_DAYS), 2)


def sortino(port_rets: np.ndarray, target: float = 0.0) -> float:
    if len(port_rets) < 2:
        return 0.0
    excess = np.asarray(port_rets, dtype=float) - target
    downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
    if downside < 1e-12:
        return 0.0
    return round(float(np.mean(excess) / downside * np.sqrt(TRADING_DAYS)), 2)


def expectancy(win_rate_pct: float, avg_win: float, avg_loss: float) -> float:
    """Expected net % per trade: (WinRate*AvgWin) - (LossRate*|AvgLoss|)."""
    wr = win_rate_pct / 100.0
    return round(wr * avg_win - (1 - wr) * abs(avg_loss), 4)


def profit_factor(returns: list[float]) -> float:
    wins = sum(r for r in returns if r > 0)
    losses = sum(r for r in returns if r < 0)
    if abs(losses) < 1e-9:
        return float("inf") if wins > 0 else 0.0
    return round(wins / abs(losses), 2)


def monte_carlo_drawdowns(trade_returns: list[float], n_runs: int = 1000) -> dict:
    """Bootstrap the distribution of max drawdown by resampling trade returns."""
    arr = np.asarray(trade_returns, dtype=float)
    if len(arr) == 0:
        return {"p5": 0, "p25": 0, "p50": 0, "p75": 0, "p95": 0, "histogram": []}
    max_dds = []
    for _ in range(int(n_runs)):
        shuffled = np.random.choice(arr, size=len(arr), replace=True)
        equity = np.cumprod(1 + shuffled / 100.0)
        running_max = np.maximum.accumulate(equity)
        dd = (equity / running_max - 1.0) * 100.0
        max_dds.append(float(np.min(dd)))
    histogram, _ = np.histogram(max_dds, bins=30)
    return {
        "p5": float(np.percentile(max_dds, 5)),
        "p25": float(np.percentile(max_dds, 25)),
        "p50": float(np.percentile(max_dds, 50)),
        "p75": float(np.percentile(max_dds, 75)),
        "p95": float(np.percentile(max_dds, 95)),
        "histogram": histogram.tolist(),
    }


def compute_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    bench_nav: list[float],
    starting_capital: float,
) -> dict:
    """Assemble the full Bloomberg-style metric matrix from the simulation output."""
    nav_series = [e["nav"] for e in equity_curve] or [starting_capital]
    p_rets = daily_returns(nav_series)
    b_rets = daily_returns(bench_nav) if bench_nav else np.array([])

    total = len(trades)
    rets = [t["return_pct"] for t in trades]
    win_rets = [r for r in rets if r > 0]
    loss_rets = [r for r in rets if r <= 0]
    wins = len(win_rets)
    win_rate = round(wins / total * 100, 1) if total else 0.0
    avg_win = round(sum(win_rets) / len(win_rets), 2) if win_rets else 0.0
    avg_loss = round(sum(loss_rets) / len(loss_rets), 2) if loss_rets else 0.0

    final_nav = nav_series[-1]
    n_days = max(len(nav_series) - 1, 1)
    total_return_pct = (final_nav / starting_capital - 1) * 100.0
    cagr_pct = ((final_nav / starting_capital) ** (TRADING_DAYS / n_days) - 1) * 100.0
    mdd = max_drawdown(nav_series)
    beta, alpha = beta_alpha(p_rets, b_rets)

    bench_final = bench_nav[-1] if bench_nav else starting_capital
    bench_total_return_pct = (bench_final / starting_capital - 1) * 100.0

    exit_breakdown = {"stop_loss": 0, "trailing_stop": 0, "time_stop": 0}
    for t in trades:
        exit_breakdown[t.get("exit_reason", "time_stop")] = exit_breakdown.get(t.get("exit_reason", "time_stop"), 0) + 1

    return {
        "starting_capital": round(starting_capital, 2),
        "final_nav": round(final_nav, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "benchmark_total_return_pct": round(bench_total_return_pct, 2),
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": win_rate,
        "avg_return": round(sum(rets) / len(rets), 2) if rets else 0.0,
        "avg_win_return": avg_win,
        "avg_loss_return": avg_loss,
        "win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss else 0.0,
        "expectancy": expectancy(win_rate, avg_win, avg_loss),
        "profit_factor": profit_factor(rets),
        "sharpe_ratio": sharpe(p_rets),
        "sortino_ratio": sortino(p_rets),
        "calmar_ratio": round(abs(cagr_pct / mdd), 2) if mdd else 0.0,
        "max_drawdown": round(mdd, 2),
        "max_drawdown_duration_days": max_drawdown_duration(nav_series),
        "beta": beta,
        "alpha_annual_pct": alpha,
        "exit_breakdown": exit_breakdown,
    }
