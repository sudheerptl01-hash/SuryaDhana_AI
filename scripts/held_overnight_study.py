#!/usr/bin/env python
"""
Held-overnight study — do NSE's "who is holding" datasets predict swing returns?

Pre-registered hypotheses (docs/NSE_DATA_DICTIONARY.md), fixed before looking at results:

  H1  Delivery accumulation. On each week's last session, among liquid EQ stocks, the top
      decile of delivery surge (5-day mean delivered shares / prior 60-day mean) with a
      positive 20-day return beats random picks over the next 5 and 20 sessions.
      Control: positive 20-day return with a middling delivery surge (deciles 4–6), which
      isolates delivery from plain momentum.
  H2  Long build-up vs short covering. Among F&O stocks, a 5-day price rise > 3% with
      futures OI (all expiries) up > 10% continues over 5 and 10 sessions; a rise with OI
      down > 10% (short covering) does not. Windows containing an expiry are skipped.
  H3  Named institutional buying. A bulk-deal net BUY by a mutual fund or insurer is
      followed by positive excess drift over 5 and 20 sessions; other net buyers and net
      sellers are reported alongside.

Added 2026-09-28 after H1–H3, again fixed before looking at results:

  H4  Insider purchases. Open-market purchases ("Market Purchase") of ≥ ₹10 lakh by promoters,
      promoter group, directors or key managerial personnel, dated by the intimation date
      (entry at the open after the first session on or after it), beat turnover-matched random
      picks over 20 and 60 sessions. Open-market sales by the same people are reported alongside.
  H5  Leverage crowding. Within 5% of the 52-week high, the top decile of 20-session growth in
      MTF-financed shares (known one session after the position date) underperforms and has
      more 20-session drops of ≥ 10% than stocks near the high with middling MTF growth.
      MTF data starts in 2022, so this test splits discovery ≤ 2024-06 / holdout ≥ 2024-07.
  H6  Ownership drift. Between consecutive quarter-end shareholding filings, falling shareholder
      count with FPI + MF holding up > 0.5 pp (accumulation) beats matched random picks over 20
      and 60 sessions after the filing's broadcast date; holders up > 5% with FPI + MF down
      > 0.5 pp (distribution) lags.

Added 2026-09-28 after H4–H6. Both historical periods have been seen, so this one is judged
only on data that did not exist yet:

  H4b Fresh insider buying. The first H4-qualifying purchase in a stock with no such purchase in
      the previous 90 days beats liquidity-matched random picks over 20 and 60 sessions. Forward
      test: intimations from 2026-10-01 only, judged once there are 100 events (positive excess,
      |t_nw| ≥ 2; tradeable if the excess also exceeds the round-trip cost).

Method (as in the earlier value-area and idea-lab studies):
  * point in time: every input is published by the evening of day t; entry at the next open;
  * excess = trade return − mean return of the same universe on the same date (random picks);
  * costs: shared/trading_costs.py round trip on a ₹50,000 position;
  * statistics clustered by week (one observation per week); discovery 2019-10…2023-12,
    holdout 2024-01…present. A signal counts only if it holds in both periods, and it is
    tradeable only if its holdout excess exceeds the round-trip cost.

    python scripts/held_overnight_study.py [--out reports/held_overnight] [--tests H1,H2,H3,H4,H4B,H5,H6]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.nse_panel import load_panel  # noqa: E402
from shared.deal_filters import INSTITUTION_RE, net_bulk_deals  # noqa: E402,F401  (re-exported for tests)
from shared.trading_costs import default_model  # noqa: E402

DISCOVERY_END = pd.Timestamp("2023-12-31")
POSITION_RS = 50_000


# ── data ────────────────────────────────────────────────────────────────────────

def load_data(start: str = "2019-06-01") -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, dict]:
    db = ROOT / "data" / "market.duckdb"
    tmp = Path(tempfile.mkdtemp(prefix="hold_"))
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        panel = load_panel(con, start=start)
        fo = con.execute("SELECT date, symbol, near_expiry, fut_oi FROM nse_fo_daily WHERE kind = 'stock'").df()
        deals = con.execute("SELECT date, symbol, client_name, side, qty FROM nse_deals WHERE kind = 'bulk'").df()
        extra = {
            "insider": con.execute("SELECT symbol, category, mode, txn_type, value, from_date, to_date, intimation_date "
                                   "FROM nse_insider_trades WHERE intimation_date IS NOT NULL").df(),
            "mtf": con.execute("SELECT date, symbol, qty_financed FROM nse_mtf").df(),
            "shareholding": con.execute("SELECT * FROM nse_shareholding").df(),
        }
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for df in (fo, deals, extra["mtf"]):
        df["date"] = pd.to_datetime(df["date"])
    return panel, fo, deals, extra


# ── shared helpers ──────────────────────────────────────────────────────────────

def forward_open_returns(open_: pd.DataFrame, h: int) -> pd.DataFrame:
    """Signal known after the close of t → buy at open t+1, sell at open t+1+h."""
    return open_.shift(-(1 + h)) / open_.shift(-1) - 1.0


def week_ends(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(dates, index=dates)
    return pd.DatetimeIndex(s.groupby(dates.to_period("W")).max().values)


def week_clustered(excess: pd.Series, dates: pd.Series) -> tuple[float, float, int]:
    """Mean of weekly mean excess, its t-statistic, and the number of weeks."""
    weekly = excess.groupby(pd.to_datetime(dates).dt.to_period("W")).mean().dropna()
    n = len(weekly)
    if n < 3:
        return float(weekly.mean()) if n else float("nan"), float("nan"), n
    sd = float(weekly.std(ddof=1))
    if sd == 0.0:
        return float(weekly.mean()), (float("inf") if weekly.mean() != 0 else float("nan")), n
    return float(weekly.mean()), float(weekly.mean() / (sd / np.sqrt(n))), n


def newey_west_t(weekly: pd.Series, lags: int) -> float:
    """t-statistic of a weekly series whose forward windows overlap (horizon > 1 week), with a
    Bartlett-weighted Newey-West variance. Plain weekly t-stats overstate significance then."""
    x = weekly.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 3:
        return float("nan")
    e = x - x.mean()
    s = e @ e / n
    for lag in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - lag / (lags + 1)) * (e[lag:] @ e[:-lag]) / n
    return float(x.mean() / np.sqrt(s / n)) if s > 0 else float("nan")


def summarize(events: pd.DataFrame, cost: float, label: str, horizon: int,
              split: pd.Timestamp = DISCOVERY_END) -> list[dict]:
    """events: date, symbol, fwd, base → one row per period with excess stats."""
    rows = []
    for period, mask in (("discovery", events["date"] <= split), ("holdout", events["date"] > split),
                         ("all", events["date"].notna())):
        ev = events[mask].dropna(subset=["fwd", "base"])
        if ev.empty:
            rows.append({"test": label, "h": horizon, "period": period, "events": 0})
            continue
        ex = ev["fwd"] - ev["base"]
        mean_ex, t_ex, weeks = week_clustered(ex, ev["date"])
        weekly = ex.groupby(pd.to_datetime(ev["date"]).dt.to_period("W")).mean().sort_index()
        t_nw = newey_west_t(weekly, max(1, horizon // 5))
        rows.append({
            "test": label, "h": horizon, "period": period, "events": len(ev), "weeks": weeks,
            "mean_fwd_pct": round(100 * ev["fwd"].mean(), 2), "mean_base_pct": round(100 * ev["base"].mean(), 2),
            "excess_pct": round(100 * mean_ex, 2), "t_excess": round(t_ex, 2), "t_nw": round(t_nw, 2),
            "beat_random_pct": round(100 * (ex > 0).mean(), 1),
            "tail10_pct": round(100 * (ev["fwd"] <= -0.10).mean(), 1),
            "net_after_cost_pct": round(100 * (ev["fwd"].mean() - cost), 2),
            "excess_after_cost_pct": round(100 * (mean_ex - cost), 2),
        })
    return rows


def verdict(rows: list[dict], cost: float) -> str:
    d = next((r for r in rows if r["period"] == "discovery"), {})
    h = next((r for r in rows if r["period"] == "holdout"), {})
    if not d.get("events") or not h.get("events"):
        return "NOT ENOUGH DATA"
    same_sign = np.sign(d["excess_pct"]) == np.sign(h["excess_pct"])
    # Overlapping forward windows: judge on the Newey-West t (stricter than the plain weekly t).
    td, th = d.get("t_nw", d["t_excess"]), h.get("t_nw", h["t_excess"])
    real = same_sign and abs(td) >= 2 and abs(th) >= 2
    if not real:
        return "NO RELIABLE EDGE"
    if h["excess_pct"] > 0 and h["excess_pct"] / 100 > cost:
        return "SUPPORTED · beats random after costs"
    return "REAL BUT TOO SMALL · excess below round-trip cost" if h["excess_pct"] > 0 else "REAL · NEGATIVE (avoid signal)"


def forward_verdict(rows: list[dict], cost: float, min_events: int = 100) -> str:
    """Forward-only test: the period after the split is the whole sample."""
    f = next((r for r in rows if r["period"] == "holdout"), {})
    n = int(f.get("events") or 0)
    if n < min_events:
        return f"FORWARD TEST · {n} of {min_events} events so far"
    if f["excess_pct"] <= 0 or abs(f.get("t_nw", f["t_excess"])) < 2:
        return "NO RELIABLE EDGE"
    return "SUPPORTED · beats random after costs" if f["excess_pct"] / 100 > cost else \
        "REAL BUT TOO SMALL · excess below round-trip cost"


# ── H1 delivery accumulation ────────────────────────────────────────────────────

def h1_events(panel: dict[str, pd.DataFrame], horizons=(5, 20)) -> dict[tuple[str, int], pd.DataFrame]:
    close, open_ = panel["close"], panel["open"]
    delivered = panel["volume"] * panel["deliv_pct"] / 100.0
    surge = delivered.rolling(5, min_periods=4).mean() / delivered.shift(5).rolling(60, min_periods=40).mean()
    ret20 = close / close.shift(20) - 1.0
    liquid = (panel["turnover_cr"].rolling(60, min_periods=40).median() >= 5.0) & (close >= 20)
    eq = panel["series"].eq("EQ")
    out: dict[tuple[str, int], list] = {}
    fwd = {h: forward_open_returns(open_, h) for h in horizons}
    for t in week_ends(close.index):
        if t not in close.index:
            continue
        ok = liquid.loc[t] & eq.loc[t] & surge.loc[t].notna() & ret20.loc[t].notna()
        syms = ok[ok].index
        if len(syms) < 50:
            continue
        rank = surge.loc[t, syms].rank(pct=True)
        groups = {
            "H1 delivery surge top decile + price up": syms[(rank >= 0.9) & (ret20.loc[t, syms] > 0)],
            "H1 control: price up, middling delivery": syms[(rank >= 0.3) & (rank <= 0.6) & (ret20.loc[t, syms] > 0)],
            "H1 delivery surge top decile + price down": syms[(rank >= 0.9) & (ret20.loc[t, syms] <= 0)],
        }
        for h in horizons:
            f = fwd[h].loc[t, syms]
            base = f.mean()
            for name, g in groups.items():
                out.setdefault((name, h), []).extend(
                    {"date": t, "symbol": s, "fwd": f.get(s), "base": base} for s in g)
    return {k: pd.DataFrame(v) for k, v in out.items()}


# ── H2 long build-up vs short covering ──────────────────────────────────────────

def classify_buildup(dp: float, doi: float, p_th: float = 0.03, oi_th: float = 0.10) -> str | None:
    if dp > p_th and doi > oi_th:
        return "long build-up"
    if dp > p_th and doi < -oi_th:
        return "short covering"
    if dp < -p_th and doi > oi_th:
        return "short build-up"
    if dp < -p_th and doi < -oi_th:
        return "long unwinding"
    return None


def h2_events(panel: dict[str, pd.DataFrame], fo: pd.DataFrame, horizons=(5, 10)) -> dict[tuple[str, int], pd.DataFrame]:
    close, open_ = panel["close"], panel["open"]
    oi = fo.pivot_table(index="date", columns="symbol", values="fut_oi", aggfunc="sum").reindex(close.index)
    near = fo.pivot_table(index="date", columns="symbol", values="near_expiry", aggfunc="first").reindex(close.index)
    dp5 = close / close.shift(5) - 1.0
    doi5 = oi / oi.shift(5) - 1.0
    same_series = near.eq(near.shift(5))          # no expiry inside the 5-day window
    fwd = {h: forward_open_returns(open_, h) for h in horizons}
    out: dict[tuple[str, int], list] = {}
    for t in week_ends(close.index):
        if t not in oi.index or oi.loc[t].notna().sum() < 50:
            continue
        syms = [s for s in oi.columns if s in close.columns and pd.notna(oi.loc[t, s]) and pd.notna(dp5.loc[t, s])]
        for h in horizons:
            f = fwd[h].loc[t, syms]
            base = f.mean()
            for s in syms:
                if not bool(same_series.loc[t, s]):
                    continue
                cls = classify_buildup(dp5.loc[t, s], doi5.loc[t, s])
                if cls:
                    out.setdefault((f"H2 {cls}", h), []).append({"date": t, "symbol": s, "fwd": f.get(s), "base": base})
    return {k: pd.DataFrame(v) for k, v in out.items()}


# ── H3 named institutional buying ───────────────────────────────────────────────

def h3_events(panel: dict[str, pd.DataFrame], deals: pd.DataFrame, horizons=(5, 20)) -> dict[tuple[str, int], pd.DataFrame]:
    close, open_ = panel["close"], panel["open"]
    med_to = panel["turnover_cr"].rolling(60, min_periods=40).median()
    tradable = (med_to >= 2.0) & (close >= 20) & panel["series"].eq("EQ")
    universe = (close >= 20) & panel["series"].eq("EQ") & med_to.notna()
    quint = med_to.where(universe).rank(axis=1, pct=True).mul(5).clip(upper=4.999).floordiv(1)
    fwd = {h: forward_open_returns(open_, h) for h in horizons}
    base = {}
    for h in horizons:            # turnover-quintile-matched random picks on the same date
        f = fwd[h].where(universe)
        base[h] = {q: f.where(quint == q).mean(axis=1) for q in range(5)}
    ev = net_bulk_deals(deals)
    ev = ev[ev["date"].isin(close.index) & ev["symbol"].isin(close.columns)]
    labels = {(True, "buy"): "H3 institutional net BUY (MF/insurer)", (False, "buy"): "H3 other net BUY",
              (True, "sell"): "H3 institutional net SELL", (False, "sell"): "H3 other net SELL"}
    out: dict[tuple[str, int], list] = {}
    for key, grp in ev.groupby(["institution", "direction"]):
        name = labels[key]
        grp = grp.drop_duplicates(["date", "symbol"])
        for h in horizons:
            rows = []
            for r in grp.itertuples():
                if not bool(tradable.at[r.date, r.symbol]) or pd.isna(quint.at[r.date, r.symbol]):
                    continue
                q = int(quint.at[r.date, r.symbol])
                rows.append({"date": r.date, "symbol": r.symbol, "fwd": fwd[h].at[r.date, r.symbol],
                             "base": base[h][q].at[r.date]})
            out[(name, h)] = rows
    return {k: pd.DataFrame(v) for k, v in out.items()}


# ── matched baseline (H3, H4, H6) ───────────────────────────────────────────────

def matched_baseline(panel: dict[str, pd.DataFrame], horizons) -> tuple:
    """Tradable mask, turnover quintile per stock-day, forward returns and the same-date mean
    forward return of each turnover quintile (random picks of similar liquidity)."""
    close, open_ = panel["close"], panel["open"]
    med_to = panel["turnover_cr"].rolling(60, min_periods=40).median()
    tradable = (med_to >= 2.0) & (close >= 20) & panel["series"].eq("EQ")
    universe = (close >= 20) & panel["series"].eq("EQ") & med_to.notna()
    quint = med_to.where(universe).rank(axis=1, pct=True).mul(5).clip(upper=4.999).floordiv(1)
    fwd = {h: forward_open_returns(open_, h) for h in horizons}
    base = {h: {q: fwd[h].where(universe).where(quint == q).mean(axis=1) for q in range(5)} for h in horizons}
    return tradable, quint, fwd, base


def matched_events(panel, events: pd.DataFrame, horizons, prepared=None) -> dict[int, pd.DataFrame]:
    """events: date (signal session), symbol → per horizon: date, symbol, fwd, base."""
    tradable, quint, fwd, base = prepared or matched_baseline(panel, horizons)
    close = panel["close"]
    ev = events[events["date"].isin(close.index) & events["symbol"].isin(close.columns)].drop_duplicates(["date", "symbol"])
    out = {}
    for h in horizons:
        rows = []
        for r in ev.itertuples():
            if not bool(tradable.at[r.date, r.symbol]) or pd.isna(quint.at[r.date, r.symbol]):
                continue
            rows.append({"date": r.date, "symbol": r.symbol, "fwd": fwd[h].at[r.date, r.symbol],
                         "base": base[h][int(quint.at[r.date, r.symbol])].at[r.date]})
        out[h] = pd.DataFrame(rows, columns=["date", "symbol", "fwd", "base"])
    return out


def to_session(dates: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Map calendar dates to the first trading session on or after them (NaT beyond the data)."""
    d = pd.to_datetime(dates)
    pos = index.searchsorted(d.values)
    return pd.Series([index[p] if (p < len(index) and v >= index[0]) else pd.NaT for p, v in zip(pos, d)],
                     index=dates.index)


# ── H4 insider purchases ────────────────────────────────────────────────────────

KEY_PEOPLE = re.compile(r"promoter|director|key managerial", re.I)


def _insider_key_trades(panel, insider: pd.DataFrame) -> pd.DataFrame:
    """Promoter / director / KMP trades of ≥ ₹10 lakh, dated by the session after intimation."""
    ins = insider.copy()
    ins = ins[ins["category"].fillna("").str.contains(KEY_PEOPLE) & (pd.to_numeric(ins["value"], errors="coerce") >= 1_000_000)]
    if "to_date" in ins:            # filings carry typos (years 1925, 2028): keep disclosures 0–30 days after the trade
        lag = (pd.to_datetime(ins["intimation_date"]) - pd.to_datetime(ins["to_date"].fillna(ins.get("from_date")))).dt.days
        ins = ins[lag.between(0, 30)]
    ins["date"] = to_session(ins["intimation_date"], panel["close"].index)
    ins["mode_l"] = ins["mode"].fillna("").str.lower()
    return ins.dropna(subset=["date"])


def h4_events(panel, insider: pd.DataFrame, horizons=(20, 60)) -> dict[tuple[str, int], pd.DataFrame]:
    ins = _insider_key_trades(panel, insider)
    prepared = matched_baseline(panel, horizons)
    out = {}
    for label, mask in (("H4 insider open-market BUY (≥ ₹10 lakh)", ins["mode_l"].str.contains("market purchase")),
                        ("H4 insider open-market SELL (≥ ₹10 lakh)", ins["mode_l"].str.contains("market sale"))):
        for h, df in matched_events(panel, ins[mask][["date", "symbol"]], horizons, prepared).items():
            out[(label, h)] = df
    return out


H4B_START = pd.Timestamp("2026-10-01")
H4B_LABEL = "H4b fresh insider BUY (first in 90 days, forward)"


def fresh_buys(buys: pd.DataFrame, gap_days: int = 90) -> pd.DataFrame:
    """First buy per stock after at least `gap_days` without one (history before the window counts)."""
    b = buys.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"])
    prev = b.groupby("symbol")["date"].shift()
    return b[prev.isna() | ((b["date"] - prev).dt.days > gap_days)]


def h4b_events(panel, insider: pd.DataFrame, horizons=(20, 60),
               start: pd.Timestamp = H4B_START) -> dict[tuple[str, int], pd.DataFrame]:
    ins = _insider_key_trades(panel, insider)
    fresh = fresh_buys(ins[ins["mode_l"].str.contains("market purchase")][["date", "symbol"]])
    fresh = fresh[fresh["date"] >= start]
    if fresh.empty:
        return {(H4B_LABEL, h): pd.DataFrame(columns=["date", "symbol", "fwd", "base"]) for h in horizons}
    return {(H4B_LABEL, h): df for h, df in matched_events(panel, fresh, horizons).items()}


# ── H5 leverage crowding ────────────────────────────────────────────────────────

H5_SPLIT = pd.Timestamp("2024-06-30")


def h5_events(panel, mtf: pd.DataFrame, horizons=(20,)) -> dict[tuple[str, int], pd.DataFrame]:
    close, open_ = panel["close"], panel["open"]
    q = mtf.pivot_table(index="date", columns="symbol", values="qty_financed", aggfunc="sum").reindex(close.index)
    known = q.shift(1)                                   # report for day T is published on T+1
    chg20 = known / known.shift(20) - 1.0
    near_high = close >= 0.95 * close.rolling(250, min_periods=200).max()
    liquid = (panel["turnover_cr"].rolling(60, min_periods=40).median() >= 5.0) & (close >= 20) & panel["series"].eq("EQ")
    fwd = {h: forward_open_returns(open_, h) for h in horizons}
    out: dict[tuple[str, int], list] = {}
    for t in week_ends(close.index):
        if t not in chg20.index or chg20.loc[t].notna().sum() < 100:
            continue
        ok = liquid.loc[t] & chg20.loc[t].notna() & (known.loc[t] > 0)
        syms = ok[ok].reindex(close.columns, fill_value=False)
        syms = syms[syms].index
        if len(syms) < 100:
            continue
        rank = chg20.loc[t, syms].rank(pct=True)
        high = near_high.loc[t, syms]
        groups = {"H5 near 52w high + MTF surge (top decile)": syms[(rank >= 0.9) & high],
                  "H5 control: near 52w high, middling MTF growth": syms[(rank >= 0.3) & (rank <= 0.6) & high]}
        for h in horizons:
            f = fwd[h].loc[t, syms]
            base = f.mean()
            for name, g in groups.items():
                out.setdefault((name, h), []).extend({"date": t, "symbol": s, "fwd": f.get(s), "base": base} for s in g)
    return {k: pd.DataFrame(v) for k, v in out.items()}


# ── H6 ownership drift ──────────────────────────────────────────────────────────

def h6_events(panel, shp: pd.DataFrame, horizons=(20, 60)) -> dict[tuple[str, int], pd.DataFrame]:
    s = shp.copy()
    s["period_end"] = pd.to_datetime(s["period_end"])
    s = s[s["period_end"].dt.is_quarter_end & s["total_holders"].notna()]
    s["broadcast"] = pd.to_datetime(s["broadcast_ts"].str.slice(0, 11), format="%d-%b-%Y", errors="coerce")
    s = s.sort_values(["symbol", "period_end", "broadcast"]).drop_duplicates(["symbol", "period_end"], keep="last")
    # A filing with neither category parsed is unread, not zero: it must not look like a 30 pp swing.
    s["inst"] = (s["fpi_pct"].fillna(0) + s["mf_pct"].fillna(0)).where(s["fpi_pct"].notna() | s["mf_pct"].notna())
    g = s.groupby("symbol")
    s["d_holders"] = g["total_holders"].pct_change()
    s["d_inst"] = g["inst"].diff()
    s["gap_q"] = (s["period_end"] - g["period_end"].shift()).dt.days
    s = s[(s["gap_q"] >= 80) & (s["gap_q"] <= 100)]           # consecutive quarters only
    s["date"] = to_session(s["broadcast"], panel["close"].index)
    prepared = matched_baseline(panel, horizons)
    out = {}
    for label, mask in (("H6 accumulation (holders down, FPI+MF up)", (s["d_holders"] < 0) & (s["d_inst"] > 0.5)),
                        ("H6 distribution (holders up >5%, FPI+MF down)", (s["d_holders"] > 0.05) & (s["d_inst"] < -0.5))):
        ev = s[mask].dropna(subset=["date"])[["date", "symbol"]]
        for h, df in matched_events(panel, ev, horizons, prepared).items():
            out[(label, h)] = df
    return out


# ── report ──────────────────────────────────────────────────────────────────────

def render(results: pd.DataFrame, verdicts: dict, cost: float, meta: dict) -> str:
    lines = ["# Held-overnight study (H1–H6)", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Data {meta['start']} → {meta['end']}. "
             f"Round-trip cost on a ₹{POSITION_RS:,} position: {100 * cost:.2f}%.", "",
             "Excess = trade return minus random picks from the same universe on the same date. "
             "t-statistics use one observation per week; t_nw corrects for overlapping holding windows "
             "(Newey-West) and verdicts use it. Discovery ≤ 2023-12, holdout ≥ 2024-01 (H5: ≤ / ≥ mid-2024; "
             "H4b: forward only, its 'holdout' rows are the data since 2026-10-01).", "",
             "## Verdicts", "", "| Test | Horizon | Verdict |", "|---|---|---|"]
    for (test, h), v in verdicts.items():
        lines.append(f"| {test} | {h}d | {v} |")
    lines += ["", "## Detail", ""]
    cols = ["test", "h", "period", "events", "weeks", "mean_fwd_pct", "mean_base_pct", "excess_pct", "t_excess",
            "t_nw", "beat_random_pct", "tail10_pct", "excess_after_cost_pct"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * len(cols))
    # a forward-only test (H4b) has no completed holding windows for its first weeks: show the rows it has, blank
    for r in results.reindex(columns=cols).fillna("").itertuples(index=False):
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    lines += ["", "## Data", "", *(f"- {k}: {v}" for k, v in meta.items() if k not in ("start", "end"))]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/held_overnight")
    ap.add_argument("--tests", default="H1,H2,H3,H4,H4B,H5,H6")
    args = ap.parse_args()
    tests = {t.strip().upper() for t in args.tests.split(",")}
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    panel, fo, deals, extra = load_data()
    cost = default_model().round_trip_pct(POSITION_RS) / 100.0
    meta = {"start": str(panel["close"].index.min().date()), "end": str(panel["close"].index.max().date()),
            "stocks_in_panel": panel["close"].shape[1], "fo_rows": len(fo),
            "fo_range": f"{fo['date'].min().date() if len(fo) else '—'} → {fo['date'].max().date() if len(fo) else '—'}",
            "bulk_deal_rows": len(deals), "insider_rows": len(extra["insider"]), "mtf_rows": len(extra["mtf"]),
            "shareholding_rows": len(extra["shareholding"])}
    all_events = {}
    if "H1" in tests:
        all_events.update(h1_events(panel))
    if "H2" in tests and len(fo):
        all_events.update(h2_events(panel, fo))
    if "H3" in tests and len(deals):
        all_events.update(h3_events(panel, deals))
    if "H4" in tests and len(extra["insider"]):
        all_events.update(h4_events(panel, extra["insider"]))
    if "H4B" in tests and len(extra["insider"]):
        all_events.update(h4b_events(panel, extra["insider"]))
    if "H5" in tests and len(extra["mtf"]):
        all_events.update(h5_events(panel, extra["mtf"]))
    if "H6" in tests and len(extra["shareholding"]):
        all_events.update(h6_events(panel, extra["shareholding"]))
    rows, verdicts = [], {}
    for (name, h), ev in sorted(all_events.items()):
        split = H5_SPLIT if name.startswith("H5") else H4B_START - pd.Timedelta(days=1) if name.startswith("H4b") \
            else DISCOVERY_END
        r = summarize(ev, cost, name, h, split) if len(ev) else [{"test": name, "h": h, "period": "all", "events": 0}]
        rows.extend(r)
        verdicts[(name, h)] = forward_verdict(r, cost) if name.startswith("H4b") else verdict(r, cost)
        ev.to_csv(out / f"events_{re.sub(r'[^a-z0-9]+', '_', name.lower())}_{h}d.csv", index=False)
    results = pd.DataFrame(rows)
    results.to_csv(out / "results.csv", index=False)
    (out / "REPORT.md").write_text(render(results, verdicts, cost, meta))
    print(render(results, verdicts, cost, meta))


if __name__ == "__main__":
    main()
