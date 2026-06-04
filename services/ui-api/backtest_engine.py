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
}

# Boolean toggle filters -> vectorised predicate over the day's dataframe
BOOLEAN_FILTERS: dict[str, Callable[[pd.DataFrame], "pd.Series[bool]"]] = {
    "price_gt_ma50": lambda d: d["close"] > d["ma50"],
    "price_gt_ma200": lambda d: d["close"] > d["ma200"],
    "ma50_gt_ma200": lambda d: d["ma50"] > d["ma200"],
    "volume_gt_avg": lambda d: d["volume"] > d["vol20"],
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

    # ATR(14) from true range. df is pre-sorted by (ticker, date), so iterating
    # unique tickers and concatenating preserves row order (index-aligned via .index).
    def _atr_group(s: pd.DataFrame) -> pd.Series:
        close_prev = np.concatenate([[np.nan], s["close"].values[:-1]])
        tr = np.maximum.reduce([
            s["high"].values - s["low"].values,
            np.abs(s["high"].values - close_prev),
            np.abs(s["low"].values - close_prev),
        ])
        return pd.Series(pd.Series(tr).rolling(14, min_periods=14).mean().values, index=s.index)

    df["atr"] = g[["high", "low", "close"]].apply(_atr_group).reset_index(level=0, drop=True)
    df["atr"] = df["atr"].fillna(0.0)
    df["atr_pct"] = (df["atr"] / df["close"] * 100).fillna(0.0)
    df["dist_ma200_pct"] = ((df["close"] - df["ma200"]) / df["ma200"] * 100).fillna(0.0)
    df["above_52w_low_pct"] = ((df["close"] - df["low52w"]) / df["low52w"] * 100).fillna(0.0)
    df["within_52w_high_pct"] = ((df["hi52w"] - df["close"]) / df["hi52w"] * 100).fillna(0.0)
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
) -> dict:
    """
    Resolve a single trade's exit under real trading physics.

    Walks the forward price path (day 1..N). Priority each day:
      1. Stop-loss   — if the day's LOW pierces entry*(1 - sl%), fill at the stop.
      2. Trailing    — else if LOW pierces peak*(1 - trail%), fill at the trail level.
      3. Time-stop   — if neither triggers by day N, exit at the Nth close.

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
        sl_price = entry_price * (1 - stop_loss_pct / 100.0) if stop_loss_pct else None
        trail_price = peak * (1 - trailing_stop_pct / 100.0) if trailing_stop_pct else None

        if sl_price is not None and lo <= sl_price:
            exit_price, holding, reason = sl_price, i + 1, "stop_loss"
            break
        if trail_price is not None and lo <= trail_price:
            exit_price, holding, reason = trail_price, i + 1, "trailing_stop"
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

        # 2) Entries (only within the requested [from, to] window)
        if from_idx <= idx <= to_idx and len(open_pos) < max_positions:
            nav = cash
            for p in open_pos.values():
                px = price_at(idx, p["ticker"])
                nav += p["shares"] * (px if px is not None else p["entry_price"])
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
