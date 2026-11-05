"""
What changes the POC-magnet rate? Conditional study + strategy gauntlet.

Builds on scripts/value_area_study.py (same events: 20-day daily volume profile,
5 closes in balance → close outside VA). For every event we add point-in-time
context known at the close of day t — trend (MA50/MA200), where the moving
averages sit relative to the POC, breakout-day volume and close strength,
breakout size, VA width, 52-week-high proximity, momentum, volatility, and the
market regime (NIFTY vs its 200DMA, breadth, India VIX).

Honesty controls (pre-registered, not tuned):
* Discovery = events before HOLDOUT_START; holdout = on/after it. Bucket edges
  come from discovery only. A result counts only if it holds in the holdout.
* Condition-matched chance: a stock under its 50DMA drifts down anyway, so the
  "POC return" for UP events is compared with how often ANY stock-day in the
  same bucket falls that many ATRs in 5 days — not with the unconditional rate.
* Returns are net of COST_PCT round trip and relative to the equal-weight
  universe over the same days; t-stats are clustered by entry week (events of
  one week share market moves and are not independent).
* Strategies trade only names with ≥ ₹10 Cr median daily turnover at the event,
  use the project's per-trade rules: 2·ATR stop, 5-day time stop, long only.

Outputs: reports/poc_conditional/ (magnet_tables.csv, feature_spreads.csv,
strategy_stats.csv, strategy_trades.csv, portfolio.json, summary.json)

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/poc_conditional_study.py
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import value_area_study as va  # noqa: E402

OUT_DIR = va.ROOT / "reports" / "poc_conditional"
HOLDOUT_START = pd.Timestamp("2024-07-01")
COST_PCT = 0.15
HOLD_DAYS = 5          # time stop (trading sessions incl. entry day)
STOP_ATR = 2.0         # project per-trade stop: k·ATR, k = 2
LIQUID_CR = 10.0
CFG = va.StudyConfig(window=20, horizon=5, balance_days=5, cost_pct=COST_PCT)

log = logging.getLogger("poc_conditional")

DAY_FEATURES = ["above_ma50", "above_ma200", "ma50_gt_ma200", "ma50_slope", "relvol", "clv",
                "prox_52w_high", "mom60", "atr_pct", "nifty_above_ma200", "breadth50", "vix"]
EVENT_FEATURES = ["ma50_between", "ma200_between", "gap_break", "ext_atr", "va_width_atr"]
BINARY = {"above_ma50", "above_ma200", "ma50_gt_ma200", "nifty_above_ma200",
          "ma50_between", "ma200_between", "gap_break"}


# ── per-stock worker ────────────────────────────────────────────────────────────

def _long_trade(o, h, l, c, entry_day: int, entry_px: float, stop_px: float) -> tuple[int, float, bool] | None:
    """Hold from entry_day for HOLD_DAYS sessions with a hard stop.
    Returns (exit_day, exit_px, stopped). A low under the stop on the entry day
    counts as stopped (conservative: intraday order of high/low is unknown)."""
    n = len(c)
    last = entry_day + HOLD_DAYS - 1
    if last >= n:
        return None
    for d in range(entry_day, last + 1):
        if d > entry_day and o[d] <= stop_px:           # gap through the stop
            return d, o[d], True
        if l[d] <= stop_px:
            return d, stop_px, True
    return last, c[last], False


def analyse(args: tuple[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ticker, df = args
    df = df[df["volume"] > 0].reset_index(drop=True)
    if len(df) < CFG.min_bars:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    dates = pd.to_datetime(df["date"]).to_numpy()
    cs, vs = pd.Series(c), pd.Series(v)
    atr = va.wilder_atr(h, l, c, CFG.atr_len)
    ma50 = cs.rolling(50).mean().to_numpy()
    ma200 = cs.rolling(200).mean().to_numpy()
    rng = h - l
    feats = pd.DataFrame({
        "date": dates,
        "above_ma50": (c > ma50).astype(float),
        "above_ma200": (c > ma200).astype(float),
        "ma50_gt_ma200": (ma50 > ma200).astype(float),
        "ma50_slope": (pd.Series(ma50) / pd.Series(ma50).shift(10) - 1).to_numpy() * 100,
        "relvol": v / vs.shift(1).rolling(20).median().to_numpy(),
        "clv": np.where(rng > 0, (c - l) / np.where(rng > 0, rng, 1), 0.5),
        "prox_52w_high": c / pd.Series(h).rolling(252, min_periods=120).max().to_numpy(),
        "mom60": (cs / cs.shift(60) - 1).to_numpy() * 100,
        "atr_pct": atr / c * 100,
    })
    for col in ("above_ma50", "above_ma200", "ma50_gt_ma200"):   # undefined before the MA exists
        feats.loc[np.isnan(ma50 if col == "above_ma50" else ma200), col] = np.nan
    down_exc, up_exc = va.excursions(h, l, c, atr, CFG.horizon)
    feats["down_exc"], feats["up_exc"] = down_exc, up_exc
    feats["ticker"] = ticker

    prof = va.rolling_profiles(h, l, v, CFG)
    evs = va.detect_events(o, h, l, c, v, prof, atr, CFG)
    down_sorted = np.sort(down_exc[~np.isnan(down_exc)])
    up_sorted = np.sort(up_exc[~np.isnan(up_exc)])
    rows, trades = [], []
    n = len(c)
    rng_ctl = np.random.default_rng(abs(hash(ticker)) % (2**32))            # S0 random-entry control
    for ev in evs:
        t = ev["t"]
        if not ev["complete"] or t + 1 >= n:
            continue
        up = ev["direction"] == "UP"
        poc, val, vah = ev["poc"], ev["val"], ev["vah"]
        srt = down_sorted if up else up_sorted
        ev["p_chance"] = float((len(srt) - np.searchsorted(srt, ev["dist_poc_atr"])) / len(srt))
        lo_, hi_ = (poc, c[t]) if up else (c[t], poc)
        ev.update({
            "ticker": ticker, "date": dates[t],
            "ma50_between": float(lo_ < ma50[t] < hi_) if not np.isnan(ma50[t]) else np.nan,
            "ma200_between": float(lo_ < ma200[t] < hi_) if not np.isnan(ma200[t]) else np.nan,
            "gap_break": float(o[t] > vah) if up else float(o[t] < val),
            "ext_atr": ((c[t] - vah) if up else (val - c[t])) / atr[t],
            "va_width_atr": (vah - val) / atr[t],
            # plain next-open → close t+H hold, for the conditional forward-return tables
            "hold_ret_pct": (c[t + CFG.horizon] / o[t + 1] - 1) * 100 if t + CFG.horizon < n else np.nan,
            "hold_exit_date": dates[t + CFG.horizon] if t + CFG.horizon < n else pd.NaT,
            "hold_entry_date": dates[t + 1],
        })
        for k in DAY_FEATURES:
            if k in feats:
                ev[k] = feats.at[t, k]
        eid = f"{ticker}|{pd.Timestamp(dates[t]).date()}"
        ev["event_id"] = eid
        rows.append(ev)

        def add(strategy: str, e_day: int, e_px: float) -> None:
            if e_day >= n:
                return
            for stop_mult, tag in ((STOP_ATR, ""), (None, "|nostop")):
                stop = e_px - stop_mult * atr[t] if stop_mult else -np.inf
                res = _long_trade(o, h, l, c, e_day, e_px, stop)
                if res is None:
                    return
                x_day, x_px, stopped = res
                trades.append({"strategy": strategy + tag, "event_id": eid, "ticker": ticker,
                               "entry_date": dates[e_day], "exit_date": dates[x_day],
                               "ret_pct": (x_px / e_px - 1) * 100 - COST_PCT,
                               "stopped": stopped})

        r_day = int(rng_ctl.integers(CFG.window + 1, n - HOLD_DAYS))
        add("S0_random_control", r_day, o[r_day])
        if up:
            add("S1_breakout_continuation", t + 1, o[t + 1])                 # buy next open
            for k in range(t + 1, min(t + 1 + CFG.horizon, n - 1)):           # S2: POC retest seen today
                if l[k] <= poc:
                    add("S2_poc_retest_buy", k + 1, o[k + 1])                 # → buy next open
                    break
            for k in range(t + 1, min(t + 4, n - 1)):                         # S4: failed breakout
                if c[k] <= vah:
                    add("S4_failed_breakout_long", k + 1, o[k + 1])
                    break
        else:
            add("S5_breakdown_long", t + 1, o[t + 1])                         # buy the breakdown
            for k in range(t + 1, min(t + 4, n - 1)):                         # S3: reclaim of VAL
                if c[k] >= val:
                    add("S3_failed_breakdown_reclaim", k + 1, o[k + 1])
                    break
    ev_df = pd.DataFrame(rows).drop(columns=["t"], errors="ignore")
    keep = ["date", "ticker", "down_exc", "up_exc"] + [k for k in DAY_FEATURES if k in feats]
    return ev_df, feats[keep].astype({k: "float32" for k in keep if k not in ("date", "ticker")}), pd.DataFrame(trades)


# ── market context ──────────────────────────────────────────────────────────────

class UniverseBench:
    """Equal-weight universe return over an exact trade span: mean over stocks of
    close[exit] / open[entry] − 1 (same open→close timing as the trade)."""

    def __init__(self, prices: pd.DataFrame, liquid_cr: float | None = None):
        p = prices.assign(date=pd.to_datetime(prices["date"]))
        self.o = p.pivot(index="date", columns="ticker", values="open")
        self.c = p.pivot(index="date", columns="ticker", values="close").reindex(self.o.index)
        self.pos = pd.Series(np.arange(len(self.o)), index=self.o.index)
        self._O, self._C = self.o.to_numpy(), self.c.to_numpy()
        if liquid_cr is not None:
            # only names that were liquid (known before entry) count in the benchmark
            v = p.pivot(index="date", columns="ticker", values="volume").reindex(self.o.index)
            turn = (self.c * v).rolling(20, min_periods=10).median().shift(1) / 1e7
            self._O = np.where(turn.to_numpy() >= liquid_cr, self._O, np.nan)

    def span(self, entry: pd.Series, exit_: pd.Series) -> np.ndarray:
        e = self.pos.reindex(pd.to_datetime(entry)).to_numpy()
        x = self.pos.reindex(pd.to_datetime(exit_)).to_numpy()
        out = np.full(len(e), np.nan)
        ok = ~(np.isnan(e) | np.isnan(x))
        pairs = pd.DataFrame({"e": e[ok].astype(int), "x": x[ok].astype(int)})
        cache = {}
        for ei, xi in pairs.drop_duplicates().itertuples(index=False):
            with np.errstate(invalid="ignore", divide="ignore"):
                r = np.clip(self._C[xi] / self._O[ei] - 1, -0.5, 0.5)
            cache[(ei, xi)] = np.nanmean(r) * 100
        out[ok] = [cache[(a, b)] for a, b in zip(pairs["e"], pairs["x"])]
        return out


def market_context(daily: pd.DataFrame) -> pd.DataFrame:
    """Per-date NIFTY>200DMA, India VIX, breadth (% above 50DMA)."""
    con_df = _load_index()
    nifty = con_df[con_df["symbol"] == "NIFTY50"].set_index("date")["close"].sort_index()
    vix = con_df[con_df["symbol"] == "INDIAVIX"].set_index("date")["close"].sort_index()
    ctx = pd.DataFrame({"nifty_above_ma200": (nifty > nifty.rolling(200).mean()).astype(float),
                        "vix": vix}).sort_index()
    ctx.loc[nifty.rolling(200).mean().isna(), "nifty_above_ma200"] = np.nan
    breadth = daily.groupby("date")["above_ma50"].mean() * 100
    ctx = ctx.join(breadth.rename("breadth50"), how="outer").sort_index()
    ctx["vix"] = ctx["vix"].ffill()
    ctx["nifty_above_ma200"] = ctx["nifty_above_ma200"].ffill()
    return ctx


def _load_index() -> pd.DataFrame:
    import duckdb
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="poc_idx_"))
    snap = tmp / "s.duckdb"
    shutil.copy2(va.DB_PATH, snap)
    if Path(f"{va.DB_PATH}.wal").exists():
        shutil.copy2(f"{va.DB_PATH}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        out = con.sql("SELECT symbol, date, close FROM market_index_daily").df()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out["date"] = pd.to_datetime(out["date"])
    return out


# ── statistics ──────────────────────────────────────────────────────────────────

def weekly_means(values: pd.Series, dates: pd.Series) -> pd.Series:
    wk = pd.to_datetime(dates).dt.to_period("W")
    return values.groupby(wk.to_numpy()).mean().dropna()


def clustered_t(values: pd.Series, dates: pd.Series) -> tuple[float, int]:
    """t-stat of the week-weighted mean (weeks = independent draws). One crash week
    with 500 events counts once, not 500 times."""
    m = weekly_means(values, dates)
    if len(m) < 5 or m.std(ddof=1) == 0:
        return math.nan, len(m)
    return float(m.mean() / m.std(ddof=1) * math.sqrt(len(m))), len(m)


def spread_t(top: pd.DataFrame, bottom: pd.DataFrame, col: str) -> tuple[float, float]:
    """Week-matched top-minus-bottom difference and its t-stat."""
    a, b = weekly_means(top[col], top["date"]), weekly_means(bottom[col], bottom["date"])
    d = (a - b).dropna()
    if len(d) >= 20 and d.std(ddof=1) > 0:
        return float(d.mean()), float(d.mean() / d.std(ddof=1) * math.sqrt(len(d)))
    # market-level features (breadth, VIX): top and bottom live in different weeks →
    # Welch t on the two sets of weekly means
    if len(a) < 5 or len(b) < 5:
        return math.nan, math.nan
    se = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float(a.mean() - b.mean()), float((a.mean() - b.mean()) / se) if se > 0 else math.nan


def bucketize(s: pd.Series, feat: str, edges: dict) -> pd.Series:
    if feat in BINARY:
        return s.map({0.0: "no", 1.0: "yes"})
    e = edges[feat]
    return pd.cut(s, e, labels=[f"Q{i + 1}" for i in range(len(e) - 1)], include_lowest=True).astype(str).replace("nan", np.nan)


def matched_chance(ev: pd.DataFrame, daily: pd.DataFrame, feat: str, edges: dict) -> pd.Series:
    """P(reach POC distance by chance) using only stock-days in the same bucket & period."""
    eb, db = bucketize(ev[feat], feat, edges), bucketize(daily[feat], feat, edges)
    out = pd.Series(np.nan, index=ev.index)
    for per in ("discovery", "holdout"):
        dmask = daily["period"] == per
        for b in eb.dropna().unique():
            pool_mask = dmask & (db == b)
            for direction, col in (("UP", "down_exc"), ("DOWN", "up_exc")):
                pool = np.sort(daily.loc[pool_mask, col].dropna().to_numpy())
                m = (eb == b) & (ev["period"] == per) & (ev["direction"] == direction)
                if len(pool) < 500 or not m.any():
                    continue
                d = ev.loc[m, "dist_poc_atr"].to_numpy()
                out[m] = (len(pool) - np.searchsorted(pool, d)) / len(pool)
    return out


def magnet_tables(ev: pd.DataFrame, daily: pd.DataFrame, edges: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per feature bucket: raw POC-return rate, chance (stock-level and condition-
    matched), week-weighted excess, forward market-relative return. Also the
    top-vs-bottom spread per feature with a week-matched t-stat."""
    rows, spreads = [], []
    for feat in DAY_FEATURES + EVENT_FEATURES:
        pm = matched_chance(ev, daily, feat, edges) if feat in DAY_FEATURES else ev["p_chance"]
        b = bucketize(ev[feat], feat, edges)
        g = ev.assign(bucket=b, p_match=pm).dropna(subset=["bucket"])
        g["exc"] = g["poc_reached"].astype(float) - g["p_match"]
        for (d, per, bk), x in g.groupby(["direction", "period", "bucket"]):
            xe = x.dropna(subset=["exc"])
            xf = x.dropna(subset=["hold_excess_pct"])
            t, _ = clustered_t(xe["exc"], xe["date"])
            ft, _ = clustered_t(xf["hold_excess_pct"], xf["date"])
            rows.append({"feature": feat, "direction": d, "period": per, "bucket": bk, "n": len(x),
                         "lo": float(x[feat].min()), "hi": float(x[feat].max()),
                         "poc_return_rate": x["poc_reached"].mean(), "chance_stock": x["p_chance"].mean(),
                         "chance_matched": x["p_match"].mean(),
                         "excess_wk": weekly_means(xe["exc"], xe["date"]).mean(), "excess_t": t,
                         "fwd_excess_wk_pct": weekly_means(xf["hold_excess_pct"], xf["date"]).mean(), "fwd_excess_t": ft})
        hi_b, lo_b = ("yes", "no") if feat in BINARY else ("Q5", "Q1")
        for d in ("UP", "DOWN"):
            rec = {"feature": feat, "direction": d, "top": hi_b, "bottom": lo_b}
            for per in ("discovery", "holdout"):
                gp = g[(g["direction"] == d) & (g["period"] == per)]
                top, bot = gp[gp["bucket"] == hi_b], gp[gp["bucket"] == lo_b]
                rec[f"{per}_rate_top"], rec[f"{per}_rate_bottom"] = top["poc_reached"].mean(), bot["poc_reached"].mean()
                rec[f"{per}_excess_spread"], rec[f"{per}_excess_spread_t"] = spread_t(
                    top.dropna(subset=["exc"]), bot.dropna(subset=["exc"]), "exc")
                rec[f"{per}_fwd_spread_pct"], rec[f"{per}_fwd_spread_t"] = spread_t(
                    top.dropna(subset=["hold_excess_pct"]), bot.dropna(subset=["hold_excess_pct"]), "hold_excess_pct")
            rec["magnet_modifier_replicates"] = bool(
                abs(rec["discovery_excess_spread_t"]) >= 2 and abs(rec["holdout_excess_spread_t"]) >= 2
                and np.sign(rec["discovery_excess_spread"]) == np.sign(rec["holdout_excess_spread"]))
            rec["return_modifier_replicates"] = bool(
                abs(rec["discovery_fwd_spread_t"]) >= 2 and abs(rec["holdout_fwd_spread_t"]) >= 2
                and np.sign(rec["discovery_fwd_spread_pct"]) == np.sign(rec["holdout_fwd_spread_pct"]))
            spreads.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(spreads)


def strategy_stats(tr: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ctl_trades = {k: g.rename(columns={"entry_date": "date"})
                  for k, g in tr[tr["strategy"].str.startswith("S0_random_control")].groupby(["strategy", "filter", "period"])}
    for (s, flt, per), x in tr.groupby(["strategy", "filter", "period"]):
        t, weeks = clustered_t(x["excess_pct"], x["entry_date"])
        ctl_name = "S0_random_control" + ("|nostop" if s.endswith("|nostop") else "")
        ctl = ctl_trades.get((ctl_name, flt, per))
        _, t_ctl = (spread_t(x.rename(columns={"entry_date": "date"}), ctl, "excess_pct")
                    if ctl is not None and not s.startswith("S0_") else (math.nan, math.nan))
        rows.append({"strategy": s, "filter": flt, "period": per, "trades": len(x), "weeks": weeks,
                     "net_ret_pct": x["ret_pct"].mean(), "win_rate": (x["ret_pct"] > 0).mean(),
                     "excess_vs_universe_pct": x["excess_pct"].mean(), "t_weekly": t, "t_vs_control": t_ctl,
                     "stop_rate": x["stopped"].mean()})
    st = pd.DataFrame(rows)
    ctl = st[st["strategy"].str.startswith("S0_random_control")].copy()
    ctl["variant"] = np.where(ctl["strategy"].str.endswith("|nostop"), "|nostop", "")
    ctl_map = ctl.set_index(["variant", "filter", "period"])["excess_vs_universe_pct"].to_dict()
    variant = np.where(st["strategy"].str.endswith("|nostop"), "|nostop", "")
    st["excess_vs_random_control_pct"] = st["excess_vs_universe_pct"] - [
        ctl_map.get((v, f, p), np.nan) for v, f, p in zip(variant, st["filter"], st["period"])]
    piv = st.pivot_table(index=["strategy", "filter"], columns="period",
                         values=["trades", "excess_vs_universe_pct", "excess_vs_random_control_pct", "t_weekly", "t_vs_control"])
    ok = ((piv[("excess_vs_universe_pct", "discovery")] > 0) & (piv[("excess_vs_universe_pct", "holdout")] > 0)
          & (piv[("excess_vs_random_control_pct", "discovery")] > 0)
          & (piv[("t_weekly", "holdout")] >= 2) & (piv[("trades", "holdout")] >= 200))
    avoid = ((piv[("t_vs_control", "discovery")] <= -2) & (piv[("t_vs_control", "holdout")] <= -2))
    key = st.set_index(["strategy", "filter"]).index
    st["survives"] = key.map(ok.to_dict()).fillna(False)
    st["avoid_signal"] = key.map(avoid.to_dict()).fillna(False)   # reliably worse than random entry
    return st


def portfolio(tr: pd.DataFrame, slots: int = 5, weight: float = 0.15) -> dict:
    """Slot-limited book: ≤5 positions at 15% each (project risk rules); first-come by
    entry date, ties broken by liquidity. Equity marks P&L at each exit date."""
    tr = tr.sort_values(["entry_date", "turnover_cr"], ascending=[True, False])
    active: list[pd.Timestamp] = []
    pnl: list[tuple[pd.Timestamp, float]] = []
    for r in tr.itertuples():
        active = [x for x in active if x >= r.entry_date]
        if len(active) >= slots:
            continue
        active.append(r.exit_date)
        pnl.append((r.exit_date, weight * r.ret_pct / 100))
    if not pnl:
        return {}
    s = pd.Series(dict(pd.DataFrame(pnl).groupby(0)[1].sum())).sort_index()
    eq = (1 + s).cumprod()
    years = (eq.index[-1] - tr["entry_date"].min()).days / 365.25
    dd = (eq / eq.cummax() - 1).min()
    return {"trades": len(pnl), "cagr_pct": round((eq.iloc[-1] ** (1 / years) - 1) * 100, 2),
            "max_drawdown_pct": round(dd * 100, 2), "final_multiple": round(float(eq.iloc[-1]), 3)}


# ── driver ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prices = va.load_prices()
    groups = list(prices.groupby("ticker", sort=False))
    evs, dailies, trades = [], [], []
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 2)) as pool:
        for e, d, t in pool.map(analyse, groups, chunksize=8):
            if len(e):
                evs.append(e)
            if len(d):
                dailies.append(d)
            if len(t):
                trades.append(t)
    ev, daily, tr = pd.concat(evs, ignore_index=True), pd.concat(dailies, ignore_index=True), pd.concat(trades, ignore_index=True)
    ev["date"] = pd.to_datetime(ev["date"])
    log.info("events %s, stock-days %s, trades %s (%.0fs)", len(ev), len(daily), len(tr), time.time() - t0)

    ctx = market_context(daily)
    bench = UniverseBench(prices)
    bench_liquid = UniverseBench(prices, liquid_cr=LIQUID_CR)
    daily = daily.join(ctx[["nifty_above_ma200", "vix", "breadth50"]], on="date")
    ev = ev.join(ctx[["nifty_above_ma200", "vix", "breadth50"]], on="date")
    for df in (ev, daily):
        df["period"] = np.where(df["date"] < HOLDOUT_START, "discovery", "holdout")

    # market-relative forward return of the plain hold (entry next open ≈ close t)
    ev["hold_excess_pct"] = ev["hold_ret_pct"] - bench.span(ev["hold_entry_date"], ev["hold_exit_date"])

    disc = ev[ev["period"] == "discovery"]
    edges = {}
    for f in DAY_FEATURES + EVENT_FEATURES:
        if f in BINARY:
            continue
        q = disc[f].replace([np.inf, -np.inf], np.nan).dropna().quantile([0.2, 0.4, 0.6, 0.8]).to_list()
        edges[f] = [-np.inf, *q, np.inf]

    tab, spreads = magnet_tables(ev, daily, edges)
    tab.to_csv(OUT_DIR / "magnet_tables.csv", index=False)
    spreads.to_csv(OUT_DIR / "feature_spreads.csv", index=False)
    log.info("magnet tables done (%.0fs)", time.time() - t0)

    # strategies: benchmark = universe from the close before entry to the exit close
    tr["entry_date"], tr["exit_date"] = pd.to_datetime(tr["entry_date"]), pd.to_datetime(tr["exit_date"])
    tr["excess_pct"] = tr["ret_pct"] - bench_liquid.span(tr["entry_date"], tr["exit_date"])
    tr = tr.merge(ev[["event_id", "turnover_cr", "above_ma200", "ma50_gt_ma200", "relvol", "clv", "ma50_slope",
                      "atr_pct", "va_width_atr", "prox_52w_high", "nifty_above_ma200", "ma50_between", "period"]],
                  on="event_id", how="left")
    tr = tr[tr["turnover_cr"] >= LIQUID_CR]
    relvol_hi = edges["relvol"][4]                       # discovery top-quintile cut
    filters = {
        "all": pd.Series(True, index=tr.index),
        "stock_uptrend": (tr["above_ma200"] == 1) & (tr["ma50_gt_ma200"] == 1),
        "stock_downtrend": (tr["above_ma200"] == 0) & (tr["ma50_gt_ma200"] == 0),
        "market_uptrend": tr["nifty_above_ma200"] == 1,
        "quality_breakout": (tr["above_ma200"] == 1) & (tr["relvol"] >= relvol_hi) & (tr["clv"] >= 0.7),
        "near_52w_high": tr["prox_52w_high"] >= 0.95,
        "ma50_support_between": tr["ma50_between"] == 1,
        # round-2 filters from the replicated return modifiers (edges = discovery quintiles)
        "relvol_top_q": tr["relvol"] >= edges["relvol"][4],
        "relvol_bottom_q": tr["relvol"] <= edges["relvol"][1],
        "ma50_slope_top_q": tr["ma50_slope"] >= edges["ma50_slope"][4],
        "atr_pct_top_q": tr["atr_pct"] >= edges["atr_pct"][4],
        "va_width_top_q": tr["va_width_atr"] >= edges["va_width_atr"][4],
    }
    parts = [tr[m].assign(filter=name) for name, m in filters.items()]
    trf = pd.concat(parts, ignore_index=True)
    stats = strategy_stats(trf)
    stats.to_csv(OUT_DIR / "strategy_stats.csv", index=False)
    trf.to_csv(OUT_DIR / "strategy_trades.csv", index=False)

    surv = stats[stats["survives"]][["strategy", "filter"]].drop_duplicates()
    book = {}
    for s, f in surv.itertuples(index=False):
        x = trf[(trf["strategy"] == s) & (trf["filter"] == f)]
        book[f"{s}|{f}"] = {per: portfolio(x[x["period"] == per]) for per in ("discovery", "holdout")}
    nifty = _load_index().query("symbol == 'NIFTY50'").set_index("date")["close"].sort_index()
    for per, (a, b) in {"discovery": (ev["date"].min(), HOLDOUT_START), "holdout": (HOLDOUT_START, ev["date"].max())}.items():
        seg = nifty[(nifty.index >= a) & (nifty.index < b)]
        yrs = (seg.index[-1] - seg.index[0]).days / 365.25
        book.setdefault("NIFTY50_buy_hold", {})[per] = {"cagr_pct": round(((seg.iloc[-1] / seg.iloc[0]) ** (1 / yrs) - 1) * 100, 2)}
    (OUT_DIR / "portfolio.json").write_text(json.dumps(book, indent=2, default=str))

    summary = {"events": len(ev), "holdout_start": str(HOLDOUT_START.date()),
               "magnet_modifiers_replicating": spreads[spreads["magnet_modifier_replicates"]].to_dict("records"),
               "return_modifiers_replicating": spreads[spreads["return_modifier_replicates"]].to_dict("records"),
               "surviving_strategies": surv.to_dict("records"),
               "avoid_signals": stats[stats["avoid_signal"]][["strategy", "filter"]].drop_duplicates().to_dict("records"),
               "portfolio": book}
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("done (%.0fs) → %s", time.time() - t0, OUT_DIR)


if __name__ == "__main__":
    main()
