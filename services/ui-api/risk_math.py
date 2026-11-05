"""Pure portfolio-risk math for the RSK dashboard (worldclass program W5).

No I/O in this module: every function takes pandas/numpy inputs and returns plain
numbers or small dicts, so tests/test_risk_math.py can pin the math by hand.

Conventions (stated on the page; do not change silently):

- **Historical-simulation VaR** at level `a` over n daily returns is the k-th worst
  return with k = ceil((1-a)·n) — the empirical order statistic, no interpolation —
  reported as a positive loss fraction. **Expected shortfall** at level `a` is the
  mean of those k worst returns (also positive). n=750: a=0.95 → k=38, a=0.99 → k=8.
- **Multi-day VaR** scales 1-day VaR by sqrt(h). This is an APPROXIMATION (i.i.d.
  daily returns, no autocorrelation or vol clustering) and is labeled as such
  wherever it is shown.
- **Panel alignment**: the panel calendar is the union of the included symbols'
  trading dates; a symbol's missing session is a 0.0 return (price carried over a
  day it did not trade). This slightly understates the volatility of illiquid
  names; a symbol with fewer than `min_obs` real observations is EXCLUDED instead,
  with the reason returned to the caller.
- **beta** = cov(r_s, r_m) / var(r_m) on the common dates of the two series.
- **Risk contribution** of holding i = w_i · cov(r_i, r_p) / σ_p (Euler
  decomposition of volatility): contributions sum to the portfolio stdev σ_p.
- **Stress window return** compounds the holding's ACTUAL daily returns over the
  window (start, end] close-to-close. A holding whose history does not reach back
  to the window start (within `grace_days`) or that has no session inside the
  window is excluded — honest replay, never an extrapolation.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

# ── Severity thresholds (shown verbatim in the UI; the Trading Rules themselves are
#    CLAUDE.md's and are only *read* here: −20% HARD emergency stop, −2% daily halt,
#    40% per-industry cap) ──────────────────────────────────────────────────────────
EMERGENCY_DD_PCT = -20.0      # HARD: sell everything at the next open (CLAUDE.md)
DAILY_HALT_PCT = -2.0         # HARD: halt trading for the day (CLAUDE.md)
SECTOR_CAP_PCT = 40.0         # max 40% of positions per NSE industry (CLAUDE.md)

VAR_WARN_PCT_OF_BOOK = 1.0    # VaR95 1d ≥ 1% of book: one bad tail day eats half the −2% halt
VAR_CRIT_PCT_OF_BOOK = 2.0    # a 1-in-20 day is expected to trip the −2% daily halt
BETA_WARN = 1.2               # book moves ≥1.2× NIFTY
BETA_CRIT = 1.5
DD_WARN_PCT = -10.0           # half-way to the −20% HARD stop
DD_CRIT_PCT = -15.0           # three quarters of the way to the HARD stop
SECTOR_WARN_FRACTION = 0.8    # within 80% of the 40% cap

THRESHOLDS_DOC: dict[str, str] = {
    "var": f"VaR95 1d as % of book: ok < {VAR_WARN_PCT_OF_BOOK}% · warn {VAR_WARN_PCT_OF_BOOK}–"
           f"{VAR_CRIT_PCT_OF_BOOK}% · crit ≥ {VAR_CRIT_PCT_OF_BOOK}% (a 1-in-20 day trips the −2% daily halt)",
    "beta": f"portfolio beta vs NIFTY50: ok ≤ {BETA_WARN} · warn {BETA_WARN}–{BETA_CRIT} · crit > {BETA_CRIT}",
    "sector": f"positions per NSE industry: ok < {SECTOR_WARN_FRACTION * SECTOR_CAP_PCT:.0f}% · warn ≥ "
              f"{SECTOR_WARN_FRACTION * SECTOR_CAP_PCT:.0f}% · crit > {SECTOR_CAP_PCT:.0f}% (rule breach)",
    "dd": f"drawdown from peak: ok > {DD_WARN_PCT}% · warn {DD_WARN_PCT}% to {DD_CRIT_PCT}% · crit ≤ {DD_CRIT_PCT}% "
          f"(HARD stop at {EMERGENCY_DD_PCT}%) · crit while the emergency stop is engaged",
}


# ── Returns & panel ────────────────────────────────────────────────────────────────

def daily_returns(closes: pd.Series) -> pd.Series:
    """Simple daily returns from a date-indexed close series (sorted, NaN closes dropped)."""
    s = pd.to_numeric(closes, errors="coerce").dropna().sort_index()
    s = s[s > 0]
    return s.pct_change().dropna()


def build_panel(
    returns_by_symbol: Mapping[str, pd.Series],
    lookback: int,
    min_obs: int = 60,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Align per-symbol daily returns on the union calendar, keep the last `lookback`
    sessions, fill a symbol's missing sessions with 0.0 (price carried). Symbols with
    fewer than `min_obs` real observations inside the window are excluded.

    Returns (panel DataFrame [date × symbol], {excluded_symbol: reason}).
    """
    excluded: dict[str, str] = {}
    series: dict[str, pd.Series] = {}
    for sym, r in returns_by_symbol.items():
        r = r.dropna()
        if r.empty:
            excluded[sym] = "no usable price history"
            continue
        series[sym] = r
    if not series:
        return pd.DataFrame(), excluded
    panel = pd.DataFrame(series).sort_index()
    panel = panel.tail(lookback)
    for sym in list(panel.columns):
        obs = int(panel[sym].notna().sum())
        if obs < min_obs:
            excluded[sym] = f"only {obs} sessions in the lookback window (need ≥ {min_obs})"
            panel = panel.drop(columns=[sym])
    return panel.fillna(0.0), excluded


def normalize_weights(weights: Mapping[str, float], symbols: Sequence[str]) -> dict[str, float]:
    """Weights restricted to `symbols`, renormalized to sum to 1 (empty dict if nothing left)."""
    w = {s: float(weights[s]) for s in symbols if weights.get(s, 0.0) > 0}
    total = sum(w.values())
    return {s: v / total for s, v in w.items()} if total > 0 else {}


def portfolio_returns(panel: pd.DataFrame, weights: Mapping[str, float]) -> pd.Series:
    """Daily portfolio returns at CURRENT weights (renormalized over the panel's columns)."""
    w = normalize_weights(weights, list(panel.columns))
    if not w or panel.empty:
        return pd.Series(dtype=float)
    vec = np.array([w.get(c, 0.0) for c in panel.columns])
    return pd.Series(panel.values @ vec, index=panel.index)


# ── VaR / ES ───────────────────────────────────────────────────────────────────────

def hist_var_es(returns: Sequence[float] | pd.Series, level: float) -> tuple[Optional[float], Optional[float]]:
    """Historical-simulation (VaR, ES) at `level` as positive loss fractions.

    k = ceil((1-level)·n), clamped to [1, n]; VaR = −(k-th worst return);
    ES = −mean(worst k returns). None when the sample is empty.
    """
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    n = r.size
    if n == 0:
        return None, None
    # ceil with an epsilon guard: (1−0.95)·100 is 5.000000000000004 in floats and must stay k=5
    k = min(n, max(1, math.ceil((1.0 - level) * n - 1e-9)))
    worst = np.sort(r)[:k]
    return float(-worst[k - 1]), float(-worst.mean())


def sqrt_horizon(value: Optional[float], days: int) -> Optional[float]:
    """sqrt-time scaling of a 1-day risk number — an i.i.d. APPROXIMATION, label it."""
    return None if value is None else float(value) * math.sqrt(days)


def histogram(returns: Sequence[float] | pd.Series, bins: int = 31) -> list[dict[str, float]]:
    """Histogram of daily returns for the UI: [{x0, x1, n}] (empty list when no data)."""
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size == 0:
        return []
    counts, edges = np.histogram(r, bins=bins)
    return [{"x0": float(edges[i]), "x1": float(edges[i + 1]), "n": int(c)} for i, c in enumerate(counts)]


# ── Beta & decomposition ───────────────────────────────────────────────────────────

def beta(stock: pd.Series, market: pd.Series, min_obs: int = 60) -> Optional[float]:
    """OLS beta = cov(r_s, r_m)/var(r_m) on common dates; None under `min_obs` overlap
    or a flat market sample."""
    df = pd.concat({"s": stock, "m": market}, axis=1, join="inner").dropna()
    if len(df) < min_obs:
        return None
    var_m = float(df["m"].var(ddof=1))
    if var_m <= 0 or not np.isfinite(var_m):
        return None
    return float(df["s"].cov(df["m"]) / var_m)


def risk_contributions(panel: pd.DataFrame, weights: Mapping[str, float]) -> tuple[float, dict[str, float]]:
    """Portfolio daily stdev σ_p and each holding's marginal contribution
    w_i·cov(r_i, r_p)/σ_p. Contributions sum to σ_p (Euler). ({}, 0.0) when degenerate."""
    w = normalize_weights(weights, list(panel.columns))
    if not w or len(panel) < 2:
        return 0.0, {}
    rp = portfolio_returns(panel, w)
    sigma_p = float(rp.std(ddof=1))
    if sigma_p <= 0 or not np.isfinite(sigma_p):
        return 0.0, {s: 0.0 for s in w}
    return sigma_p, {s: float(w[s] * panel[s].cov(rp) / sigma_p) for s in w}


# ── Stress replays ─────────────────────────────────────────────────────────────────

def window_return(rets: pd.Series, start: date, end: date, grace_days: int = 5) -> Optional[float]:
    """Compound the ACTUAL daily returns over (start, end] — close of `start` to close
    of `end`. None (→ excluded, stated) when the series' first return is later than
    start+grace (no base price at the window start) or no session falls inside."""
    r = rets.dropna().sort_index()
    if r.empty:
        return None
    idx = pd.DatetimeIndex(r.index)
    first = idx.min().date()
    if first > start + timedelta(days=grace_days):
        return None
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    inside = r[(idx > t0) & (idx <= t1)]
    if inside.empty:
        return None
    return float(np.prod(1.0 + inside.values) - 1.0)


def stress_scenario(
    rets_by_symbol: Mapping[str, pd.Series],
    values: Mapping[str, float],
    start: date,
    end: date,
    grace_days: int = 5,
) -> dict[str, Any]:
    """Replay one historical window on the CURRENT book: ₹ P&L = Σ value_i · r_i over
    the holdings whose history covers the window; the rest are excluded and named.
    `portfolio_pct` is P&L over the covered value (not over a book the window never saw)."""
    pnl = 0.0
    covered = 0.0
    total = sum(float(v) for v in values.values() if v and v > 0)
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for sym, v in values.items():
        v = float(v or 0.0)
        if v <= 0:
            continue
        r = window_return(rets_by_symbol.get(sym, pd.Series(dtype=float)), start, end, grace_days)
        if r is None:
            excluded.append({"symbol": sym, "reason": f"no history covering {start} → {end}"})
            continue
        pnl += v * r
        covered += v
        rows.append({"symbol": sym, "window_return_pct": r * 100.0, "pnl_inr": v * r})
    worst = min(rows, key=lambda x: x["window_return_pct"]) if rows else None
    return {
        "pnl_inr": pnl,
        "portfolio_pct": (pnl / covered * 100.0) if covered > 0 else None,
        "covered_value_pct": (covered / total * 100.0) if total > 0 else 0.0,
        "holdings": sorted(rows, key=lambda x: x["window_return_pct"]),
        "worst": ({"symbol": worst["symbol"], "window_return_pct": worst["window_return_pct"]} if worst else None),
        "excluded": excluded,
    }


# ── Sector concentration ───────────────────────────────────────────────────────────

def sector_concentration(
    holdings: Sequence[Mapping[str, Any]],
    cap_pct: float = SECTOR_CAP_PCT,
) -> list[dict[str, Any]]:
    """Per-industry value share AND positions-count share. The Desk rule (CLAUDE.md)
    caps POSITIONS per NSE industry at 40%, so `breach` fires on the count share."""
    total_value = sum(float(h.get("value") or 0.0) for h in holdings)
    n = len([h for h in holdings if float(h.get("value") or 0.0) > 0])
    agg: dict[str, dict[str, float]] = {}
    for h in holdings:
        v = float(h.get("value") or 0.0)
        if v <= 0:
            continue
        sec = str(h.get("sector") or "Unknown")
        a = agg.setdefault(sec, {"value": 0.0, "count": 0.0})
        a["value"] += v
        a["count"] += 1
    rows = []
    for sec, a in agg.items():
        count_pct = a["count"] / n * 100.0 if n else 0.0
        rows.append({
            "sector": sec,
            "value_inr": a["value"],
            "value_pct": a["value"] / total_value * 100.0 if total_value else 0.0,
            "positions": int(a["count"]),
            "count_pct": count_pct,
            "breach": count_pct > cap_pct,
        })
    return sorted(rows, key=lambda r: -r["value_inr"])


# ── Drawdown ladder ────────────────────────────────────────────────────────────────

def drawdown_ladder(
    navs: Sequence[float],
    peak: Optional[float] = None,
    emergency_dd_pct: float = EMERGENCY_DD_PCT,
    daily_halt_pct: float = DAILY_HALT_PCT,
) -> dict[str, Any]:
    """Where the book sits against the −20% HARD emergency stop and the −2% daily halt.

    `navs`: NAV marks oldest→newest (the desk ledger's EOD series). `peak` defaults to
    the running max of the series. Distances are positive magnitudes:
    - further_fall_to_stop_pct: how much further NAV must fall (as % of current NAV)
      to touch peak·(1 + emergency_dd); 0.0 once at or through the stop.
    - room_before_halt_pct: today's return minus the −2% halt (0.0 = halt level hit).
    """
    xs = [float(v) for v in navs if v is not None and np.isfinite(v)]
    if not xs:
        return {"nav": None, "peak": None, "drawdown_pct": None, "stop_nav": None,
                "further_fall_to_stop_pct": None, "today_return_pct": None,
                "room_before_halt_pct": None,
                "emergency_stop_pct": emergency_dd_pct, "daily_halt_pct": daily_halt_pct}
    nav = xs[-1]
    pk = float(peak) if peak and peak > 0 else max(xs)
    pk = max(pk, nav)
    dd_pct = (nav / pk - 1.0) * 100.0
    stop_nav = pk * (1.0 + emergency_dd_pct / 100.0)
    further = max(0.0, (nav - stop_nav) / nav * 100.0)
    today = (xs[-1] / xs[-2] - 1.0) * 100.0 if len(xs) >= 2 and xs[-2] > 0 else None
    room = None if today is None else max(0.0, today - daily_halt_pct)
    return {"nav": nav, "peak": pk, "drawdown_pct": dd_pct, "stop_nav": stop_nav,
            "further_fall_to_stop_pct": further, "today_return_pct": today,
            "room_before_halt_pct": room,
            "emergency_stop_pct": emergency_dd_pct, "daily_halt_pct": daily_halt_pct}


# ── Severity chips ─────────────────────────────────────────────────────────────────

def severity_var(var95_1d_pct_of_book: Optional[float]) -> str:
    if var95_1d_pct_of_book is None:
        return "na"
    if var95_1d_pct_of_book >= VAR_CRIT_PCT_OF_BOOK:
        return "crit"
    return "warn" if var95_1d_pct_of_book >= VAR_WARN_PCT_OF_BOOK else "ok"


def severity_beta(portfolio_beta: Optional[float]) -> str:
    if portfolio_beta is None:
        return "na"
    if portfolio_beta > BETA_CRIT:
        return "crit"
    return "warn" if portfolio_beta > BETA_WARN else "ok"


def severity_sector(max_count_pct: Optional[float], cap_pct: float = SECTOR_CAP_PCT) -> str:
    if max_count_pct is None:
        return "na"
    if max_count_pct > cap_pct:
        return "crit"
    return "warn" if max_count_pct >= SECTOR_WARN_FRACTION * cap_pct else "ok"


def severity_dd(drawdown_pct: Optional[float], stopped: bool = False) -> str:
    if stopped:
        return "crit"
    if drawdown_pct is None:
        return "na"
    if drawdown_pct <= DD_CRIT_PCT:
        return "crit"
    return "warn" if drawdown_pct <= DD_WARN_PCT else "ok"
