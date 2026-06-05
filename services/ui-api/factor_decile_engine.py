"""
factor_decile_engine.py — Vectorized Factor Decile Profiler core.

Pure-Python / numpy / pandas. No FastAPI, no DuckDB imports here so the math is
unit-testable in isolation (see tests/test_factor_decile_engine.py). All I/O
(DuckDB snapshot loads, indicator prep, HTTP) lives in routers/analytics.py and
reuses the *same* prepared price/indicator matrix the Backtest Lab consumes — so
a decile boundary computed here is identical to a filter threshold there.

Methodology (institutional factor diagnostics, a.k.a. decile/quantile IC study):
  1. TRAILING features, FORWARD label.  The indicator value on date T is strictly
     point-in-time (computed upstream by backtest_engine.compute_indicators). The
     label is the *forward* net return over T..T+N — the supervised target. Using a
     forward target is correct and is NOT the look-ahead bias the repo forbids;
     that rule is about never letting future data leak into a *feature*.
  2. Friction realism.  Forward return is netted of the same round-trip friction
     (default 15 bps) the backtest charges, so the base rate here matches a real,
     cost-aware win rate — never a gross fantasy number.
  3. Vectorized bucketing.  pd.qcut(..., labels=False, duplicates='drop') assigns
     every row to one of N equal-population deciles in a single columnar pass.
     There are NO iterative row scans anywhere in this module.
  4. Degeneracy-safe.  Repeated/identical factor values collapse quantile edges;
     duplicates='drop' yields fewer-than-N buckets instead of raising, and a
     constant factor falls back to a single bucket. Every edge case returns a
     well-formed payload.

MODE is always PAPER: this module replays history, it never places an order.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_FRICTION_BPS = 15.0   # round-trip cost, basis points (0.15%) — matches backtest_engine
DEFAULT_DECILES = 10


# ── Forward-return target labeling (vectorized, no look-ahead on features) ────────

def compute_forward_labels(
    df: pd.DataFrame,
    forward_days: int,
    win_threshold_pct: float = 0.0,
    friction_bps: float = DEFAULT_FRICTION_BPS,
    price_col: str = "close",
) -> pd.DataFrame:
    """
    Attach the binary forward-event label to every (ticker, date) row.

    For each ticker (sorted by date) the forward net return over the next
    `forward_days` trading bars is:

        gross_%  = (close[T+N] / close[T] - 1) * 100
        net_%    = gross_% - friction_bps / 100            # round-trip cost
        label    = 1 if net_% > win_threshold_pct else 0

    Rows whose forward window runs past the end of that ticker's history get
    label = NaN (no fabricated future) and must be dropped by the caller. The
    shift is a single grouped vector op — no row-by-row iteration.

    Returns a copy of `df` with two new columns: `fwd_net_return_pct`, `label`.
    """
    if forward_days < 1:
        raise ValueError("forward_days must be >= 1")
    out = df.sort_values(["ticker", "date"]).copy()
    grp = out.groupby("ticker", sort=False)[price_col]
    fwd_close = grp.shift(-int(forward_days))
    entry = out[price_col]
    gross_pct = (fwd_close / entry - 1.0) * 100.0
    net_pct = gross_pct - friction_bps / 100.0
    # NaN forward price (window past end) or non-positive entry → undefined label.
    valid = fwd_close.notna() & (entry > 0)
    out["fwd_net_return_pct"] = net_pct.where(valid)
    out["label"] = np.where(valid, (net_pct > win_threshold_pct).astype(float), np.nan)
    return out


# ── Decile profile (the vectorized core) ──────────────────────────────────────────

def _spearman(order: list[int], rates: list[float]) -> float:
    """Rank correlation of event-rate vs decile index — a monotonicity score."""
    if len(rates) < 2 or float(np.ptp(rates)) == 0.0:
        # Constant event rate across deciles → correlation undefined; report flat.
        return 0.0
    c = pd.Series(order, dtype=float).corr(pd.Series(rates, dtype=float), method="spearman")
    return round(float(c), 4) if pd.notna(c) else 0.0


def decile_profile(
    values: pd.Series | np.ndarray,
    labels: pd.Series | np.ndarray,
    n_deciles: int = DEFAULT_DECILES,
) -> dict:
    """
    Bucket `values` into up to `n_deciles` equal-population quantiles and map each
    bucket against its binary `labels` (1 = positive event / win, 0 = loss).

    Returns:
        {
          deciles: [{decile, lo, hi, obs_lo, obs_hi, samples, positives,
                     event_rate, lift}],   # lo/hi = quantile edges, obs_* = realised range
          global_base_rate, total_samples, total_positives,
          n_deciles_requested, n_deciles_effective, monotonicity_spearman,
          best_decile, worst_decile, degenerate
        }

    Edge cases (all return a well-formed payload, never raise):
      • empty / all-NaN input        → zero-sample envelope, degenerate=True
      • constant factor (1 unique)   → single bucket spanning [v, v]
      • fewer uniques than n_deciles → duplicates='drop' collapses to k<N buckets
    """
    n_deciles = max(1, int(n_deciles))
    frame = pd.DataFrame({"v": pd.to_numeric(pd.Series(values).reset_index(drop=True), errors="coerce"),
                          "y": pd.to_numeric(pd.Series(labels).reset_index(drop=True), errors="coerce")})
    frame = frame.dropna()
    total = int(len(frame))

    if total == 0:
        return _empty_profile(n_deciles)

    total_pos = int(frame["y"].sum())
    base_rate = total_pos / total * 100.0

    # Bucketing — single vectorized pass. duplicates='drop' folds repeated edges.
    nunique = int(frame["v"].nunique())
    if nunique < 2 or total < 2:
        # Constant (or single-sample) factor: one bucket spanning the value range.
        codes = np.zeros(total, dtype=int)
        lo_hi = [(float(frame["v"].min()), float(frame["v"].max()))]
        k = 1
    else:
        q = min(n_deciles, nunique)
        codes_series, edges = pd.qcut(frame["v"], q=q, labels=False, retbins=True, duplicates="drop")
        codes = codes_series.to_numpy()
        k = len(edges) - 1
        lo_hi = [(float(edges[i]), float(edges[i + 1])) for i in range(k)]

    frame = frame.assign(_d=codes)
    grouped = frame.groupby("_d", sort=True)["y"]
    samples = grouped.size()
    positives = grouped.sum()
    obs_lo = frame.groupby("_d", sort=True)["v"].min()
    obs_hi = frame.groupby("_d", sort=True)["v"].max()

    deciles: list[dict] = []
    for code in range(k):
        s = int(samples.get(code, 0))
        if s == 0:
            continue
        p = int(positives.get(code, 0))
        er = p / s * 100.0
        edge_lo, edge_hi = lo_hi[code]
        deciles.append({
            "decile": code + 1,
            "lo": round(edge_lo, 4),
            "hi": round(edge_hi, 4),
            "obs_lo": round(float(obs_lo.get(code, edge_lo)), 4),
            "obs_hi": round(float(obs_hi.get(code, edge_hi)), 4),
            "samples": s,
            "positives": p,
            "event_rate": round(er, 2),
            "lift": round(er - base_rate, 2),
        })

    rates = [d["event_rate"] for d in deciles]
    order = [d["decile"] for d in deciles]
    best = max(deciles, key=lambda d: d["event_rate"])["decile"] if deciles else None
    worst = min(deciles, key=lambda d: d["event_rate"])["decile"] if deciles else None

    return {
        "deciles": deciles,
        "global_base_rate": round(base_rate, 2),
        "total_samples": total,
        "total_positives": total_pos,
        "n_deciles_requested": n_deciles,
        "n_deciles_effective": len(deciles),
        "monotonicity_spearman": _spearman(order, rates),
        "best_decile": best,
        "worst_decile": worst,
        "degenerate": len(deciles) < 2,
    }


def _empty_profile(n_deciles: int) -> dict:
    return {
        "deciles": [],
        "global_base_rate": 0.0,
        "total_samples": 0,
        "total_positives": 0,
        "n_deciles_requested": int(n_deciles),
        "n_deciles_effective": 0,
        "monotonicity_spearman": 0.0,
        "best_decile": None,
        "worst_decile": None,
        "degenerate": True,
    }


# ── End-to-end convenience (used by the API layer + integration tests) ────────────

def profile_factor(
    df: pd.DataFrame,
    factor_col: str,
    forward_days: int,
    win_threshold_pct: float = 0.0,
    friction_bps: float = DEFAULT_FRICTION_BPS,
    n_deciles: int = DEFAULT_DECILES,
    as_of_mask: Optional[pd.Series] = None,
) -> dict:
    """
    Label the full price matrix, restrict to the analysis window (`as_of_mask`, a
    boolean Series aligned to `df.index`, typically date ∈ [from, to]), then build
    the decile profile of `factor_col`.

    `df` is the *prepared* frame from analytics._load_prepared: it carries the
    upstream warm-up and forward-look rows so forward returns are fully realised on
    every in-window row; the mask trims the study population back to the window.
    """
    if factor_col not in df.columns:
        raise KeyError(f"factor column '{factor_col}' not present in prepared frame")
    labeled = compute_forward_labels(df, forward_days, win_threshold_pct, friction_bps)
    sub = labeled[labeled["label"].notna() & labeled[factor_col].notna()]
    if as_of_mask is not None:
        sub = sub[as_of_mask.reindex(sub.index, fill_value=False)]
    return decile_profile(sub[factor_col], sub["label"], n_deciles)
