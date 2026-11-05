"""
Value-Area breakout → Point-of-Control return study (NSE equities, daily bars).

Question: when a stock that has been balancing inside its ~1-month value area
closes OUTSIDE it (above VAH / below VAL), how often — and how many times — does
price come back to that profile's Point of Control (POC) in the following days?
And is that more than chance, per stock, persistently?

Method (all point-in-time, no look-ahead)
-----------------------------------------
* Profile at day t is built from bars [t-W, t-1] only (W = 20 ≈ one month).
  Daily bars have no intraday volume-at-price, so each bar's volume is spread
  uniformly over its [low, high] range (standard daily-bar approximation).
  POC = highest-volume bin; Value Area = bins around POC holding 70% of volume.
* Event at t: the previous `balance_days` closes were all inside [VAL, VAH]
  (the stock was "in balance") and close[t] > VAH (UP) or < VAL (DOWN).
  Events of one stock never overlap: the next one can start after t + H.
* Follow-up over t+1..t+H: did price reach the POC, on how many days did the
  bar trade through the POC, days to first reach, VA re-entry, H-day return.
* Chance baseline: a POC sitting `d` ATRs away is reached by pure volatility
  some of the time. For each event we look up, from the SAME stock's full
  history, P(max adverse excursion over H days ≥ d ATR). Excess = actual − chance.
  Per-stock significance uses the Poisson-binomial z-score + Benjamini–Hochberg.
* Persistence (the out-of-sample test): does a stock's first-half excess predict
  its second-half excess? If "character" is real, the ranks must carry over.
* Tradability (long-only, NSE delivery cannot be shorted overnight):
  DOWN events → buy next open, exit at POC limit or at close t+H;
  UP events → buy next open (continuation), exit at close t+H.
  Both net of `cost_pct` round trip and compared with the equal-weight universe
  return over the same dates (market-neutral excess).

Reads an isolated snapshot of data/market.duckdb (data-service holds the write
lock). Outputs to reports/value_area/.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/value_area_study.py [--window 20 --horizon 5] [--sweep]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DUCKDB_PATH", ROOT / "data" / "market.duckdb"))
OUT_DIR = ROOT / "reports" / "value_area"

log = logging.getLogger("value_area_study")


@dataclass(frozen=True)
class StudyConfig:
    window: int = 20          # profile look-back in trading days (~1 month)
    n_bins: int = 50          # price bins per profile
    va_pct: float = 0.70      # value-area volume share
    balance_days: int = 5     # closes inside VA required before a breakout counts
    horizon: int = 5          # follow-up days after the breakout
    atr_len: int = 14
    cost_pct: float = 0.15    # round-trip transaction cost, percent
    min_bars: int = 250       # skip stocks with less history


# ── profile ─────────────────────────────────────────────────────────────────────

def volume_profile(high: np.ndarray, low: np.ndarray, volume: np.ndarray,
                   n_bins: int = 50, va_pct: float = 0.70) -> tuple[float, float, float]:
    """(POC, VAL, VAH) for a set of bars, volume spread uniformly over each bar's range."""
    lo, hi = float(np.min(low)), float(np.max(high))
    if not hi > lo:
        return (math.nan,) * 3
    edges = np.linspace(lo, hi, n_bins + 1)
    rng = high - low
    overlap = np.clip(np.minimum(high[:, None], edges[None, 1:]) - np.maximum(low[:, None], edges[None, :-1]), 0.0, None)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(rng[:, None] > 0, overlap / rng[:, None], 0.0)
    flat = np.flatnonzero(rng <= 0)                      # doji bar: all volume in its bin
    if flat.size:
        idx = np.clip(np.searchsorted(edges, high[flat], side="right") - 1, 0, n_bins - 1)
        w[flat, idx] = 1.0
    hist = (w * volume[:, None]).sum(axis=0)
    total = hist.sum()
    if total <= 0:
        return (math.nan,) * 3

    poc_i = int(np.argmax(hist))
    lo_i = hi_i = poc_i
    acc, target = hist[poc_i], va_pct * total
    while acc < target and (lo_i > 0 or hi_i < n_bins - 1):
        up = hist[hi_i + 1] if hi_i < n_bins - 1 else -1.0
        dn = hist[lo_i - 1] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1
            acc += up
        else:
            lo_i -= 1
            acc += dn
    poc = (edges[poc_i] + edges[poc_i + 1]) / 2
    return poc, float(edges[lo_i]), float(edges[hi_i + 1])


def rolling_profiles(high: np.ndarray, low: np.ndarray, volume: np.ndarray,
                     cfg: StudyConfig) -> np.ndarray:
    """Array (n, 3) of POC/VAL/VAH where row t uses bars t-W..t-1 only."""
    n = len(high)
    out = np.full((n, 3), np.nan)
    for t in range(cfg.window, n):
        s = slice(t - cfg.window, t)
        out[t] = volume_profile(high[s], low[s], volume[s], cfg.n_bins, cfg.va_pct)
    return out


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum.reduce([high - low, np.abs(high - prev), np.abs(low - prev)])
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def excursions(high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray,
               h: int) -> tuple[np.ndarray, np.ndarray]:
    """Per day s: max drop below and max rise above close[s] over s+1..s+h, in ATR units.
    NaN where the horizon is incomplete. Used only as the chance baseline."""
    n = len(close)
    atr = np.where(atr > 0, atr, np.nan)                          # suspended / flat stretches
    down = np.full(n, np.nan)
    up = np.full(n, np.nan)
    if n > h:
        fut_low = sliding_window_view(low[1:], h).min(axis=1)     # window starting at s+1
        fut_high = sliding_window_view(high[1:], h).max(axis=1)
        m = len(fut_low)                                          # = n - h
        down[:m] = (close[:m] - fut_low) / atr[:m]
        up[:m] = (fut_high - close[:m]) / atr[:m]
    return down, up


# ── events ──────────────────────────────────────────────────────────────────────

def detect_events(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, vol: np.ndarray,
                  prof: np.ndarray, atr: np.ndarray, cfg: StudyConfig) -> list[dict]:
    """Balanced → breakout events with their follow-up outcomes. Events whose
    follow-up window is still open (end of data) are returned with complete=False."""
    n, H, B = len(c), cfg.horizon, cfg.balance_days
    events: list[dict] = []
    t = max(cfg.window, B)
    while t < n:
        poc, val, vah = prof[t]
        if np.isnan(poc) or atr[t] <= 0:
            t += 1
            continue
        prior = c[t - B:t]
        balanced = bool(np.all((prior >= val) & (prior <= vah)))
        direction = "UP" if c[t] > vah else "DOWN" if c[t] < val else None
        if not (balanced and direction):
            t += 1
            continue

        f = slice(t + 1, min(t + 1 + H, n))
        fh, fl, fc, fo = h[f], l[f], c[f], o[f]
        complete = len(fc) == H
        reached = fl <= poc if direction == "UP" else fh >= poc
        first = int(np.argmax(reached)) + 1 if reached.any() else None
        ev = {
            "t": t, "direction": direction, "complete": complete,
            "close": c[t], "poc": poc, "val": val, "vah": vah, "atr": atr[t],
            "va_width_pct": (vah - val) / poc * 100,
            "turnover_cr": float(np.median(c[t - cfg.window:t] * vol[t - cfg.window:t]) / 1e7),
            "dist_poc_atr": abs(c[t] - poc) / atr[t],
            "dist_poc_pct": (poc / c[t] - 1) * 100,
            "poc_reached": bool(reached.any()),
            "days_to_poc": first,
            "poc_touch_days": int(((fl <= poc) & (fh >= poc)).sum()),
            "va_reentry": bool(((fc >= val) & (fc <= vah)).any()),
            "fwd_ret_pct": (fc[-1] / c[t] - 1) * 100 if complete else math.nan,
        }
        if complete:
            entry = fo[0]
            if direction == "DOWN":                      # long reversion to POC
                exit_px = fc[-1]
                if entry >= poc:
                    exit_px = entry                       # gapped to target at the open
                else:
                    hit = np.flatnonzero(fh >= poc)
                    if hit.size:
                        d = hit[0]
                        exit_px = max(fo[d], poc)          # gap through the POC fills at the open
            else:                                        # long continuation
                exit_px = fc[-1]
            ev["trade_ret_pct"] = (exit_px / entry - 1) * 100 - cfg.cost_pct
            ev["hold_oc_ret_pct"] = (fc[-1] / entry - 1) * 100   # for the universe benchmark join
        else:
            ev["trade_ret_pct"] = ev["hold_oc_ret_pct"] = math.nan
        events.append(ev)
        t += H + 1
    return events


def analyse_stock(args: tuple[str, pd.DataFrame, StudyConfig]) -> tuple[list[dict], dict | None, pd.DataFrame]:
    """Worker: events (with chance baseline), current state, and the stock's
    open→close H-day returns for the universe benchmark."""
    ticker, df, cfg = args
    df = df[df["volume"] > 0].reset_index(drop=True)
    if len(df) < cfg.min_bars:
        return [], None, pd.DataFrame()
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    dates = df["date"].to_numpy()
    atr = wilder_atr(h, l, c, cfg.atr_len)
    prof = rolling_profiles(h, l, v, cfg)
    down_exc, up_exc = excursions(h, l, c, atr, cfg.horizon)
    down_sorted = np.sort(down_exc[~np.isnan(down_exc)])
    up_sorted = np.sort(up_exc[~np.isnan(up_exc)])

    def p_reach(sorted_exc: np.ndarray, d: float) -> float:
        return float((len(sorted_exc) - np.searchsorted(sorted_exc, d, side="left")) / len(sorted_exc))

    events = detect_events(o, h, l, c, v, prof, atr, cfg)
    for ev in events:
        ev["ticker"] = ticker
        ev["date"] = pd.Timestamp(dates[ev.pop("t")]).date()
        ev["p_chance"] = p_reach(down_sorted if ev["direction"] == "UP" else up_sorted, ev["dist_poc_atr"])

    # current state on the last bar: profile of the last W bars *before* it
    last = len(c) - 1
    poc, val, vah = prof[last]
    inside = (c >= prof[:, 1]) & (c <= prof[:, 2])
    streak = 0
    for k in range(last, -1, -1):
        if not inside[k]:
            break
        streak += 1
    state = {
        "ticker": ticker, "last_date": pd.Timestamp(dates[last]).date(), "last_close": c[last],
        "poc": poc, "val": val, "vah": vah,
        "position": "ABOVE_VA" if c[last] > vah else "BELOW_VA" if c[last] < val else "INSIDE_VA",
        "inside_streak_days": streak,
        "dist_poc_pct": (poc / c[last] - 1) * 100 if not math.isnan(poc) else math.nan,
        "turnover_cr": float(np.median((c * v)[-20:]) / 1e7),
    }
    H = cfg.horizon
    if len(c) > H:
        oc = pd.DataFrame({"date": dates[:-H], "ret": (c[H:] / o[1:len(c) - H + 1] - 1) * 100})
    else:
        oc = pd.DataFrame()
    return events, state, oc


# ── statistics ──────────────────────────────────────────────────────────────────

def _norm_sf(z: np.ndarray) -> np.ndarray:
    return 0.5 * np.vectorize(math.erfc)(np.asarray(z, float) / math.sqrt(2))


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float)
    n = len(p)
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out


def excess_test(hits: np.ndarray, p: np.ndarray) -> tuple[float, float, float]:
    """(excess rate, z, two-sided p) for Bernoulli outcomes with per-trial chance p."""
    n = len(hits)
    if n == 0:
        return math.nan, math.nan, math.nan
    var = float(np.sum(p * (1 - p)))
    diff = float(np.sum(hits) - np.sum(p))
    z = diff / math.sqrt(var) if var > 0 else 0.0
    return diff / n, z, float(2 * _norm_sf(abs(z)))


def stock_stats(ev: pd.DataFrame, min_events: int = 8, shrink_k: float = 10.0) -> pd.DataFrame:
    rows = []
    for (tk, d), g in ev.groupby(["ticker", "direction"]):
        hits, p = g["poc_reached"].to_numpy(float), g["p_chance"].to_numpy(float)
        exc, z, pv = excess_test(hits, p)
        rows.append({
            "ticker": tk, "direction": d, "n_events": len(g),
            "poc_return_rate": hits.mean(), "chance_rate": p.mean(), "excess": exc,
            "shrunk_excess": (hits.sum() - p.sum()) / (len(g) + shrink_k),
            "z": z, "p_value": pv,
            "avg_poc_touch_days": g["poc_touch_days"].mean(),
            "median_days_to_poc": g["days_to_poc"].median(),
            "va_reentry_rate": g["va_reentry"].mean(),
            "avg_trade_ret_pct": g["trade_ret_pct"].mean(),
            "avg_gross_excess_ret_pct": g["excess_ret_pct"].mean(),
        })
    st = pd.DataFrame(rows)
    st["q_value"] = bh_qvalues(st["p_value"].fillna(1).to_numpy())

    def label(r: pd.Series) -> str:
        if r.n_events < min_events:
            return "INSUFFICIENT"
        rev = "REVERTER" if r.direction == "UP" else "BOUNCER"    # UP fails back / DOWN bounces back
        hold = "BREAKOUT_HOLDER" if r.direction == "UP" else "BREAKDOWN_HOLDER"
        if r.q_value < 0.10:
            return f"{rev} (significant)" if r.z > 0 else f"{hold} (significant)"
        if r.p_value < 0.05:
            return f"leans {rev}" if r.z > 0 else f"leans {hold}"
        return "NO_EDGE"
    st["classification"] = st.apply(label, axis=1)
    return st.sort_values(["direction", "shrunk_excess"], ascending=[True, False]).reset_index(drop=True)


def persistence(ev: pd.DataFrame, split: pd.Timestamp, min_each: int = 5) -> dict:
    """Does per-stock excess in the first half predict the second half?"""
    out = {}
    ev = ev.assign(half=np.where(pd.to_datetime(ev["date"]) < split, "A", "B"),
                   exc=ev["poc_reached"].astype(float) - ev["p_chance"])
    for d, g in ev.groupby("direction"):
        agg = g.groupby(["ticker", "half"])["exc"].agg(["mean", "count"]).unstack("half")
        ok = (agg[("count", "A")] >= min_each) & (agg[("count", "B")] >= min_each)
        a, b = agg.loc[ok, ("mean", "A")], agg.loc[ok, ("mean", "B")]
        if len(a) < 20:
            out[d] = {"stocks": int(len(a))}
            continue
        q = pd.qcut(a.rank(method="first"), 5, labels=False)
        out[d] = {
            "stocks": int(len(a)),
            "spearman_first_vs_second_half": round(float(a.corr(b, method="spearman")), 4),
            "second_half_excess_top_quintile": round(float(b[q == 4].mean()), 4),
            "second_half_excess_bottom_quintile": round(float(b[q == 0].mean()), 4),
        }
    return out


def aggregate(ev: pd.DataFrame, liquid_cr: float | None = None) -> dict:
    """Direction-level results. `gross_excess_vs_universe_pct` is before cost: to pay
    for itself a signal needs it above the round-trip cost (0.15%+)."""
    res = {}
    if liquid_cr is not None:
        ev = ev[ev["turnover_cr"] >= liquid_cr]
    for d, g in ev.groupby("direction"):
        hits, p = g["poc_reached"].to_numpy(float), g["p_chance"].to_numpy(float)
        exc, z, _ = excess_test(hits, p)
        tr, xr = g["trade_ret_pct"].dropna(), g["excess_ret_pct"].dropna()
        res[d] = {
            "events": int(len(g)), "stocks": int(g["ticker"].nunique()),
            "poc_return_rate": round(hits.mean(), 4), "chance_rate": round(p.mean(), 4),
            "excess": round(exc, 4), "z": round(z, 2),
            "avg_poc_touch_days": round(g["poc_touch_days"].mean(), 3),
            "median_days_to_poc": float(g["days_to_poc"].median()),
            "va_reentry_rate": round(g["va_reentry"].mean(), 4),
            "median_dist_poc_atr": round(g["dist_poc_atr"].median(), 3),
            "trade_net_mean_pct": round(tr.mean(), 4), "trade_win_rate": round((tr > 0).mean(), 4),
            "trade_t": round(tr.mean() / tr.std(ddof=1) * math.sqrt(len(tr)), 2) if len(tr) > 2 else None,
            "gross_excess_vs_universe_pct": round(xr.mean(), 4),
            "excess_vs_universe_t": round(xr.mean() / xr.std(ddof=1) * math.sqrt(len(xr)), 2) if len(xr) > 2 else None,
        }
        by_year = g.assign(y=pd.to_datetime(g["date"]).dt.year).groupby("y")
        res[d]["by_year"] = {
            int(y): {"n": int(len(gy)),
                     "excess": round(float((gy["poc_reached"] - gy["p_chance"]).mean()), 4),
                     "excess_ret_pct": round(float(gy["excess_ret_pct"].mean()), 4)}
            for y, gy in by_year
        }
        dist = pd.cut(g["dist_poc_atr"], [0, 0.5, 1, 1.5, 2, 3, np.inf])
        res[d]["by_distance_atr"] = {
            str(k): {"n": int(len(gb)), "rate": round(float(gb["poc_reached"].mean()), 4),
                     "chance": round(float(gb["p_chance"].mean()), 4)}
            for k, gb in g.groupby(dist, observed=True)
        }
    return res


# ── driver ──────────────────────────────────────────────────────────────────────

def load_prices() -> pd.DataFrame:
    """Copy the live DB (+WAL) to a temp snapshot so the data-service writer lock is untouched."""
    tmp = Path(tempfile.mkdtemp(prefix="va_snap_"))
    snap = tmp / "snap.duckdb"
    shutil.copy2(DB_PATH, snap)
    if Path(f"{DB_PATH}.wal").exists():
        shutil.copy2(f"{DB_PATH}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        df = con.sql("""
            SELECT o.ticker, o.date, o.open, o.high, o.low, o.close, o.volume
            FROM ohlcv o JOIN instruments i USING (ticker)
            WHERE i.instrument_type = 'EQUITY' AND i.ml_eligible
              AND o.high >= o.low AND o.close > 0
            ORDER BY o.ticker, o.date
        """).df()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return df


def run(prices: pd.DataFrame, cfg: StudyConfig, workers: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = [(tk, g, cfg) for tk, g in prices.groupby("ticker", sort=False)]
    events, states, ocs = [], [], []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for ev, st, oc in pool.map(analyse_stock, groups, chunksize=8):
            events.extend(ev)
            if st:
                states.append(st)
            if len(oc):
                ocs.append(oc)
    ev = pd.DataFrame(events)
    universe = pd.concat(ocs).groupby("date")["ret"].mean().rename("universe_ret_pct")
    universe.index = pd.to_datetime(universe.index).date
    ev = ev.join(universe, on="date")
    # gross (pre-cost) trade P&L minus what the average stock did over the same
    # entry→t+H days; cost is charged separately so both legs are like-for-like
    ev["excess_ret_pct"] = ev["trade_ret_pct"] + cfg.cost_pct - ev["universe_ret_pct"]
    return ev, pd.DataFrame(states)


def current_setups(ev: pd.DataFrame, states: pd.DataFrame, stats: pd.DataFrame, cfg: StudyConfig) -> pd.DataFrame:
    """Breakouts still inside their follow-up window, joined to each stock's history."""
    live = ev[~ev["complete"]].copy()
    if live.empty:
        return live
    live = live.drop(columns="turnover_cr").merge(
        states[["ticker", "last_close", "last_date", "turnover_cr"]], on="ticker", how="left")
    live["poc_dist_now_pct"] = (live["poc"] / live["last_close"] - 1) * 100
    hist = stats[["ticker", "direction", "n_events", "poc_return_rate", "chance_rate", "shrunk_excess",
                  "classification", "avg_trade_ret_pct"]]
    live = live.merge(hist, on=["ticker", "direction"], how="left")
    cols = ["ticker", "direction", "date", "close", "last_date", "last_close", "poc", "val", "vah",
            "poc_reached", "days_to_poc", "poc_dist_now_pct", "dist_poc_atr", "n_events",
            "poc_return_rate", "chance_rate", "shrunk_excess", "classification", "avg_trade_ret_pct", "turnover_cr"]
    return live[cols].sort_values(["direction", "shrunk_excess"], ascending=[True, False])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--window", type=int, default=20)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--balance-days", type=int, default=5)
    ap.add_argument("--sweep", action="store_true", help="also run window×horizon robustness grid")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = StudyConfig(window=args.window, horizon=args.horizon, balance_days=args.balance_days)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    prices = load_prices()
    log.info("loaded %s bars, %s equities (%.1fs)", f"{len(prices):,}", prices["ticker"].nunique(), time.time() - t0)

    ev, states = run(prices, cfg, args.workers)
    done = ev[ev["complete"]].copy()
    log.info("events: %s complete, %s still open (%.1fs)", len(done), (~ev["complete"]).sum(), time.time() - t0)

    stats = stock_stats(done)
    split = pd.Timestamp(pd.to_datetime(done["date"]).quantile(0.5))
    summary = {
        "config": asdict(cfg), "data_end": str(prices["date"].max()), "data_start": str(prices["date"].min()),
        "aggregate": aggregate(done),
        "aggregate_liquid_10cr": aggregate(done, liquid_cr=10.0),
        "persistence_split": str(split.date()), "persistence": persistence(done, split),
        "per_stock_tests": int(len(stats[stats["n_events"] >= 8])),
        "per_stock_nominal_p05": int(((stats["p_value"] < 0.05) & (stats["n_events"] >= 8)).sum()),
        "per_stock_fdr_q10": int(((stats["q_value"] < 0.10) & (stats["n_events"] >= 8)).sum()),
        "classification_counts": stats["classification"].value_counts().to_dict(),
    }
    if args.sweep:
        grid = {}
        for w in (10, 20, 40):
            for hz in (5, 10):
                c2 = StudyConfig(window=w, horizon=hz, balance_days=args.balance_days)
                e2, _ = run(prices, c2, args.workers)
                a2 = aggregate(e2[e2["complete"]])
                grid[f"W{w}_H{hz}"] = {d: {k: a2[d][k] for k in ("events", "poc_return_rate", "chance_rate", "excess",
                                                                  "z", "gross_excess_vs_universe_pct",
                                                                  "excess_vs_universe_t")} for d in a2}
                log.info("sweep W%s H%s done", w, hz)
        summary["sweep"] = grid

    done.to_csv(OUT_DIR / "events.csv", index=False)
    stats.to_csv(OUT_DIR / "stock_stats.csv", index=False)
    states.to_csv(OUT_DIR / "current_state.csv", index=False)
    current_setups(ev, states, stats, cfg).to_csv(OUT_DIR / "current_setups.csv", index=False)
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("wrote %s (%.1fs total)", OUT_DIR, time.time() - t0)
    print(json.dumps({k: v for k, v in summary.items() if k != "sweep"}, indent=2, default=str))
    if "sweep" in summary:
        print(json.dumps(summary["sweep"], indent=2))


if __name__ == "__main__":
    main()
