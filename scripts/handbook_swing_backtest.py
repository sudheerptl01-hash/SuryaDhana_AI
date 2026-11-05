#!/usr/bin/env python
"""
SuryaDhana Scanner Handbook (Oct 2026) — the rules-only swing system, backtested.

Implements the handbook's funnel, sizing and exits on the survivorship-free NSE bhavcopy panel
(split/bonus adjusted, delisted stocks included). Settings fixed before the first run
(2026-10-11); nothing below was tuned on results:

Stage 1  tradability: EQ series · price ≥ ₹50 (Tier A) · 20-day median traded value ≥ ₹5 cr ·
         ≥ 200 sessions of history · not stuck in a 2%/5% band (no ±2/5% circuit closes with all
         moves ≤ 5.2% in 60 sessions) · circuit closes on < 20% of the last 250 sessions (non-F&O).
         NOT available point-in-time, so NOT applied: ASM/GSM/ESM lists, market cap, pledge.
Stage 2  regime score 0–4 (one point each): Nifty 500 above a rising 200-DMA · ≥ 50% of tradable
         stocks above both their 50- and 200-DMA · Market Monitor 10-day ratio ≥ 1.5 and 10-day
         average of new highs − new lows > 0 · ≤ 4 distribution days in 25 (index ≤ −0.2% on higher
         universe turnover) and India VIX below its 1-year 80th percentile.
         Caps: 4 → 100% invested, 5 new entries/week, breakouts + pullbacks; 3 → 75%, 4/week,
         breakouts + pullbacks; 2 → 40%, 2/week, pullbacks only; 0–1 → no new entries.
         (Follow-through-day pilot buys are "a design choice to test": not used.)
Stage 3  score = 0.4·RS pct + 0.3·vol-adjusted-z pct + 0.3·p52 pct − 0.05 if frog-in-the-pan ID is
         in the jumpiest fifth; keep the top 30% of tradable stocks. RS rating = percentile of
         0.4·r63 + 0.2·r126 + 0.2·r189 + 0.2·r252 × 99. Industry rank: equal-weighted 3-month
         median return per NSE industry (ranking input, not a gate).
Stage 4  Trend Template TT1–TT8 as a score; soft gate TT ≥ 6 (VCP needs ≥ 7).
Stage 5  setups (signals at the close of day t, orders for t+1):
         A base breakout  buy-stop just above the base high; base 15–65 sessions, depth 8–35%,
                          base high ≥ 5 sessions old and within 3% of the 52-week high
         B VCP            ATR10/ATR50 ≤ 0.6, 10d/50d volume ≤ 0.6 with a day < 0.5×, final
                          contraction ≤ 15%, prior rise ≥ 30% in 6 months; buy-stop above the
                          10-day high
         C pocket pivot   up day, volume > every down-day volume of the last 10 sessions, close
                          within 3% of the 10-DMA, above the 50-DMA; buy at the next open
         D buyable gap-up open ≥ prior high + 0.75·ATR40, volume ≥ 1.5× average; buy next open,
                          stop = gap-day low
         E momentum burst close ≥ +4% on higher volume; buy next open, stop = burst-day low,
                          hold 5 sessions
         F RSI(2) pullback leader (TT ≥ 6, RS ≥ 70) above its 200-DMA with RSI(2) < 5; buy next
                          open; exit on a close above the 5-day SMA or RSI(2) > 70, 10-day limit
         G Holy Grail     ADX(14) > 30 and rising, first touch of the 20-EMA in 10 sessions;
                          buy-stop above the touch day's high, stop below its low, target the
                          prior 20-day high
         Buy-stops are stop-limit orders (limit = trigger + 0.76%), cancelled after 5 sessions.
Stage 6  ranking = composite without fundamentals/catalysts (no point-in-time data):
         (0.25 RS + 0.15 industry + 0.15 p52 + 0.10 TT/8 + 0.10 setup quality) / 0.75.
Sizing   shares = floor(equity × r / (entry − stop)); r = 0.5% (Tier A); stop structural, never
         more than 8% below entry; position ≤ 25% of equity and ≤ 1% of 20-day median turnover;
         total open risk ≤ 6%; ≤ 8 positions; ≤ 2 per industry; skip a candidate whose 60-day
         correlation with a holding is > 0.75.
Exits    initial stop (gaps fill at the open) · stop to breakeven at +1.5R · sell a third at +2R ·
         after +1.5R, trail the rest: first close below the 20-EMA, sell next open · time stop:
         not +1R within 10 sessions → sell next open · failed breakout (A/B): close back below the
         pivot within 3 sessions → sell next open. Results-date rule: no data, not applied.
Costs    shared/trading_costs.py per leg (default ICICI MoneySaver; --cost-profile to compare)
         + 0.15% slippage per side. Idle cash earns nothing. Pre-tax.
"Promising" (decided before running): beats Nifty 500 (price) CAGR, max drawdown no worse than
−25%, expectancy > +0.2R per trade after costs, ≥ 100 trades. Only then run 2011 → today.

    python scripts/handbook_swing_backtest.py --start 2020-01-01 [--risk 0.005] [--cost-profile icici_moneysaver]
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb
import httpx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.momentum import industries as nse_industries  # noqa: E402
from shared.nse_panel import load_panel  # noqa: E402
from shared.trading_costs import PROFILES, CostModel  # noqa: E402

REGIME_CAP = {4: (1.00, 5), 3: (0.75, 4), 2: (0.40, 2), 1: (0.0, 0), 0: (0.0, 0)}
BREAKOUT_SETUPS = {"A_breakout", "A_breakout_confirmed", "B_vcp", "C_pocket_pivot", "D_gap_up", "E_burst"}
PULLBACK_SETUPS = {"F_rsi2", "G_holy_grail"}
SLIPPAGE = 0.0015
MAX_STOP = 0.08
MAX_POSITIONS = 8
PER_INDUSTRY = 2
OPEN_RISK_CAP = 0.06
POS_CAP = 0.25
LIMIT_ABOVE_TRIGGER = 0.0076
ORDER_LIFE = 5


# ── data ────────────────────────────────────────────────────────────────────────

def nifty500(start: str) -> pd.Series:
    p1 = int(datetime.fromisoformat(start).timestamp())
    r = httpx.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ECRSLDX",
                  params={"period1": p1, "period2": int(time.time()), "interval": "1d"},
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
    idx = pd.to_datetime(r["timestamp"], unit="s", utc=True).tz_convert("Asia/Kolkata").normalize().tz_localize(None)
    return pd.Series(r["indicators"]["quote"][0]["close"], index=idx, dtype=float).dropna().groupby(level=0).last()


def load(start: str) -> dict:
    db = ROOT / "data" / "market.duckdb"
    tmp = Path(tempfile.mkdtemp(prefix="hbsw_"))
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        panel = load_panel(con, start=start)
        vix = con.execute("SELECT date, close FROM market_index_daily WHERE symbol='INDIAVIX' ORDER BY date").df()
        fo = con.execute("SELECT DISTINCT date, symbol FROM nse_fo_daily WHERE kind='stock'").df()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    vix["date"] = pd.to_datetime(vix["date"])
    fo["date"] = pd.to_datetime(fo["date"])
    return {"panel": panel, "vix": vix.set_index("date")["close"], "fo": fo, "nifty500": nifty500(start)}


# ── indicators (wide frames: date × symbol) ─────────────────────────────────────

def wilder(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def rsi(c: pd.DataFrame, n: int) -> pd.DataFrame:
    d = c.diff()
    up, dn = wilder(d.clip(lower=0), n), wilder((-d).clip(lower=0), n)
    return 100 - 100 / (1 + up / dn.where(dn > 0))


def pct_rank(x: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    return x.where(mask).rank(axis=1, pct=True)


def zscore(x: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    v = x.where(mask)
    return v.sub(v.mean(axis=1), axis=0).div(v.std(axis=1), axis=0)


def build(data: dict) -> dict:
    p = data["panel"]
    o, h, lo, c, v = p["open"], p["high"], p["low"], p["close"], p["volume"]
    raw, to, series = p["raw_close"], p["turnover_cr"], p["series"]
    idx = c.index
    ret = c.pct_change(fill_method=None)
    hist = c.notna().cumsum()

    # Stage 1
    fo_set = data["fo"].assign(f=True).pivot_table(index="date", columns="symbol", values="f", aggfunc="any")
    is_fo = fo_set.reindex(index=idx, columns=c.columns).ffill(limit=5).fillna(False).astype(bool)
    hit = pd.DataFrame(False, index=idx, columns=c.columns)
    small_band_hit = pd.DataFrame(False, index=idx, columns=c.columns)
    for b in (0.02, 0.05, 0.10, 0.20):
        near = (ret.abs() - b).abs() <= 0.0015
        at_edge = ((ret > 0) & (c >= h * 0.9995)) | ((ret < 0) & (c <= lo * 1.0005))
        hit |= near & at_edge
        if b <= 0.05:
            small_band_hit |= near & at_edge
    small_band = (ret.abs().rolling(60, min_periods=20).max() <= 0.052) & (small_band_hit.rolling(60, min_periods=1).sum() > 0)
    circuit_freq = hit.astype(float).rolling(250, min_periods=60).mean()
    med_to20 = to.rolling(20, min_periods=15).median()
    tradable = (series.eq("EQ") & (raw >= 50) & (med_to20 >= 5) & (hist >= 200) & ~small_band
                & ((circuit_freq < 0.20) | is_fo))

    cols = tradable.columns[tradable.any(axis=0)]
    keep = lambda f: f[cols]  # noqa: E731
    o, h, lo, c, v, to, ret, tradable, med_to20 = map(keep, (o, h, lo, c, v, to, ret, tradable, med_to20))

    sma = {n: c.rolling(n, min_periods=int(n * 0.8)).mean() for n in (5, 10, 50, 150, 200)}
    ema20 = c.ewm(span=20, adjust=False, min_periods=20).mean()
    prev_c = c.shift(1)
    tr = np.maximum(h - lo, np.maximum((h - prev_c).abs(), (lo - prev_c).abs()))
    atr = {n: tr.rolling(n, min_periods=int(n * 0.8)).mean() for n in (10, 20, 40, 50)}
    vol50 = v.rolling(50, min_periods=40).mean()
    hi52, lo52 = h.rolling(252, min_periods=200).max(), lo.rolling(252, min_periods=200).min()
    r = {n: c / c.shift(n) - 1 for n in (63, 126, 189, 252)}

    # Stage 3
    rs_raw = 0.4 * r[63] + 0.2 * r[126] + 0.2 * r[189] + 0.2 * r[252]
    rs_rating = pct_rank(rs_raw, tradable) * 99
    vol_ann = ret.rolling(252, min_periods=200).std() * math.sqrt(252)
    z = 0.5 * zscore(r[126] / vol_ann, tradable) + 0.5 * zscore(r[252] / vol_ann, tradable)
    p52 = c / hi52
    up_days = (ret > 0).astype(float).rolling(252, min_periods=200).mean()
    dn_days = (ret < 0).astype(float).rolling(252, min_periods=200).mean()
    fip = np.sign(r[252]) * (dn_days - up_days)
    jumpy = pct_rank(fip, tradable) > 0.8
    s3 = 0.4 * pct_rank(rs_raw, tradable) + 0.3 * pct_rank(z, tradable) + 0.3 * pct_rank(p52, tradable) - 0.05 * jumpy
    leaders = pct_rank(s3, tradable) >= 0.70

    ind_map = nse_industries()
    ind = pd.Series([ind_map.get(s, "Unknown") for s in cols], index=cols)
    r63_t = r[63].where(tradable)
    ind_med = r63_t.T.groupby(ind).median().T
    ind_pct = ind_med.rank(axis=1, pct=True)
    ind_rs = pd.DataFrame({s: ind_pct[ind[s]] for s in cols}, index=idx)

    # Stage 4
    tt = ((c > sma[150]) & (c > sma[200])).astype(int) + (sma[150] > sma[200]).astype(int) \
        + (sma[200] > sma[200].shift(21)).astype(int) + ((sma[50] > sma[150]) & (sma[50] > sma[200])).astype(int) \
        + (c > sma[50]).astype(int) + (c >= 1.3 * lo52).astype(int) + (c >= 0.75 * hi52).astype(int) \
        + (rs_rating >= 70).astype(int)
    funnel = tradable & leaders & (tt >= 6)

    # ADX(14)
    up_move, dn_move = h.diff(), -lo.diff()
    pdm = up_move.where((up_move > dn_move) & (up_move > 0), 0.0)
    mdm = dn_move.where((dn_move > up_move) & (dn_move > 0), 0.0)
    atr14 = wilder(tr, 14)
    pdi, mdi = 100 * wilder(pdm, 14) / atr14, 100 * wilder(mdm, 14) / atr14
    adx = wilder(100 * (pdi - mdi).abs() / (pdi + mdi), 14)

    return dict(o=o, h=h, lo=lo, c=c, v=v, ret=ret, tradable=tradable, med_to20=med_to20, sma=sma, ema20=ema20,
                atr=atr, vol50=vol50, hi52=hi52, lo52=lo52, rs_rating=rs_rating, p52=p52, ind=ind, ind_rs=ind_rs,
                tt=tt, funnel=funnel, adx=adx, rsi2=rsi(c, 2), cols=cols, idx=idx,
                rs_pct=pct_rank(rs_raw, tradable), p52_pct=pct_rank(p52, tradable))


def regime(f: dict, data: dict) -> pd.DataFrame:
    idx, c, h, lo, v, ret, t = f["idx"], f["c"], f["h"], f["lo"], f["v"], f["ret"], f["tradable"]
    n5 = data["nifty500"].reindex(idx).ffill()
    sma200 = n5.rolling(200, min_periods=180).mean()
    trend = (n5 > sma200) & (sma200 > sma200.shift(20))
    n_t = t.sum(axis=1).replace(0, np.nan)
    above = ((c > f["sma"][50]) & t).sum(axis=1) / n_t
    above200 = ((c > f["sma"][200]) & t).sum(axis=1) / n_t
    breadth = (above >= 0.5) & (above200 >= 0.5)
    vol_up = v > v.shift(1)
    up4 = ((ret >= 0.04) & vol_up & t).sum(axis=1)
    dn4 = ((ret <= -0.04) & vol_up & t).sum(axis=1)
    mm10 = up4.rolling(10).sum() / dn4.rolling(10).sum().replace(0, np.nan)
    nh = ((h >= f["hi52"]) & t).sum(axis=1)
    nl = ((lo <= f["lo52"]) & t).sum(axis=1)
    participation = (mm10 >= 1.5) & ((nh - nl).rolling(10).mean() > 0)
    universe_to = (f["c"] * f["v"]).where(t).sum(axis=1)
    dist = (n5.pct_change() <= -0.002) & (universe_to > universe_to.shift(1))
    vix = data["vix"].reindex(idx).ffill()
    vix_pct = vix.rolling(252, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    risk = (dist.rolling(25).sum() <= 4) & (vix_pct < 0.80)
    score = trend.astype(int) + breadth.astype(int) + participation.fillna(False).astype(int) + risk.astype(int)
    return pd.DataFrame({"score": score, "trend": trend, "breadth": breadth, "participation": participation,
                         "risk": risk, "pct_above50": above, "mm10": mm10, "nifty500": n5})


# ── setups: (date × symbol) signal frames + order parameters ────────────────────

def setups(f: dict) -> dict[str, dict[str, pd.DataFrame]]:
    o, h, lo, c, v, atr, sma = f["o"], f["h"], f["lo"], f["c"], f["v"], f["atr"], f["sma"]
    funnel, tt, vol50 = f["funnel"], f["tt"], f["vol50"]
    out: dict[str, dict[str, pd.DataFrame]] = {}

    # A base breakout: smallest base length with valid depth whose high is ≥ 5 sessions old
    pivot = pd.DataFrame(np.nan, index=c.index, columns=c.columns)
    for L in (65, 50, 40, 30, 25, 20, 15):             # smaller L overwrites → the tightest valid base
        bh, bl = h.rolling(L, min_periods=L).max(), lo.rolling(L, min_periods=L).min()
        depth = (bh - bl) / bh
        age_ok = h.rolling(5, min_periods=5).max() < bh  # the base high is not in the last 5 sessions
        ok = (depth >= 0.08) & (depth <= 0.35) & age_ok & (bh >= 0.97 * f["hi52"]) & (c < bh)
        pivot = pivot.where(~ok, bh)
    a_sig = funnel & pivot.notna()
    out["A_breakout"] = {"signal": a_sig, "trigger": pivot * 1.001,
                         "stop": lo.rolling(10, min_periods=10).min() * 0.995, "pivot": pivot}
    # Alternative reading (robustness): the handbook's close-confirmed breakout rule
    # C > base high (yesterday's pivot) and V ≥ 1.5×SMA50 and close in the top 40% and p52 ≥ 0.97,
    # bought at the next open.
    prev_pivot = pivot.shift(1)
    confirmed = (funnel.shift(1, fill_value=False) & prev_pivot.notna() & (c > prev_pivot) & (v >= 1.5 * vol50)
                 & (c >= lo + 0.6 * (h - lo)) & (f["p52"] >= 0.97))
    out["A_breakout_confirmed"] = {"signal": confirmed, "stop": lo.rolling(10, min_periods=10).min() * 0.995,
                                   "pivot_open": prev_pivot}

    # B VCP (simplified: contraction + dry-up conditions, pivot = 10-day high)
    hi10, lo10 = h.rolling(10, min_periods=10).max(), lo.rolling(10, min_periods=10).min()
    prior_rise = h.rolling(126, min_periods=100).max() / lo.rolling(126, min_periods=100).min() >= 1.30
    dry = (v.rolling(10).mean() / vol50 <= 0.6) & ((v / vol50).rolling(10).min() < 0.5)
    vcp = (funnel & (tt >= 7) & prior_rise & dry & (atr[10] / atr[50] <= 0.6)
           & ((hi10 - lo10) / hi10 <= 0.15) & (c < hi10))
    out["B_vcp"] = {"signal": vcp, "trigger": hi10 * 1.001, "stop": lo10 * 0.995, "pivot": hi10}

    # C pocket pivot (buy next open)
    down_vol = v.where(c < c.shift(1))
    max_down10 = down_vol.shift(1).rolling(10, min_periods=1).max()
    pp = funnel & (c > c.shift(1)) & (v > max_down10) & ((c / sma[10] - 1).abs() <= 0.03) & (c > sma[50])
    out["C_pocket_pivot"] = {"signal": pp, "stop": np.minimum(sma[10], lo.rolling(5).min()) * 0.995}

    # D buyable gap-up (buy next open, stop = gap-day low)
    gap = funnel & (o >= h.shift(1) + 0.75 * atr[40]) & (v >= 1.5 * vol50)
    out["D_gap_up"] = {"signal": gap, "stop": lo * 0.995}

    # E momentum burst (buy next open, stop = burst-day low, hold 5 sessions)
    burst = funnel & (c / c.shift(1) - 1 >= 0.04) & (v > v.shift(1))
    out["E_burst"] = {"signal": burst, "stop": lo * 0.995}

    # F RSI(2) pullback in leaders (buy next open, stop 1.5×ATR20 capped by the 8% rule)
    lead = f["tradable"] & (tt >= 6) & (f["rs_rating"] >= 70)
    rsi2 = lead & (c > sma[200]) & (f["rsi2"] < 5)
    out["F_rsi2"] = {"signal": rsi2, "stop": c - 1.5 * atr[20]}

    # G Holy Grail (buy-stop above the touch-day high, stop below its low, target prior 20-day high)
    touch = lo <= f["ema20"]
    first = touch & (touch.shift(1).rolling(10, min_periods=10).sum() == 0)
    hg = lead & (f["adx"] > 30) & (f["adx"] > f["adx"].shift(1)) & first & (c > f["ema20"] * 0.97)
    out["G_holy_grail"] = {"signal": hg, "trigger": h * 1.001, "stop": lo * 0.999,
                           "target": h.rolling(20, min_periods=20).max()}
    return out


def setup_quality(f: dict) -> pd.DataFrame:
    """Share of four quality checks (handbook Stage 6 'Setup'): volume dry-up, ATR contraction,
    NR7/inside day on the signal day, prior advance ≥ 50%."""
    h, lo, v, vol50, atr = f["h"], f["lo"], f["v"], f["vol50"], f["atr"]
    rng = h - lo
    nr7 = rng <= rng.rolling(7).min()
    inside = (h < h.shift(1)) & (lo > lo.shift(1))
    checks = [(v.rolling(10).mean() / vol50 <= 0.6), (atr[10] / atr[50] <= 0.6), (nr7 | inside),
              (h.rolling(126, min_periods=100).max() / lo.rolling(126, min_periods=100).min() >= 1.5)]
    return sum(x.astype(float) for x in checks) / len(checks)


# ── portfolio simulation ────────────────────────────────────────────────────────

@dataclass
class Position:
    sym: str
    setup: str
    entry_date: pd.Timestamp
    entry: float
    stop: float
    shares: int
    risk_per_share: float
    pivot: float | None = None
    target: float | None = None
    partial_done: bool = False
    breakeven: bool = False
    max_high: float = 0.0
    days: int = 0
    exit_flag: str | None = None
    cash_in: float = 0.0          # ₹ received from sells (net of costs)
    cash_out: float = 0.0         # ₹ paid for the buy (incl. costs)
    shares0: int = 0


@dataclass
class Order:
    sym: str
    setup: str
    kind: str                     # "stop" (buy-stop) or "open" (market at the next open)
    created: int
    trigger: float = 0.0
    stop: float = 0.0
    pivot: float | None = None
    target: float | None = None
    score: float = 0.0


@dataclass
class Book:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)
    costs: float = 0.0


def simulate(f: dict, reg: pd.DataFrame, sig: dict, quality: pd.DataFrame, start: str, capital: float,
             risk: float, cost_model: CostModel, setups_on: set[str]) -> tuple[pd.DataFrame, Book]:
    idx = f["idx"]
    o, h, lo, c = (f[k].to_numpy() for k in ("o", "h", "lo", "c"))
    ema20, med_to = f["ema20"].to_numpy(), f["med_to20"].to_numpy()
    sma5, rsi2 = f["sma"][5].to_numpy(), f["rsi2"].to_numpy()
    cols = list(f["c"].columns)
    col = {s: i for i, s in enumerate(cols)}
    ind = f["ind"]
    rets = f["ret"]
    comp = ((0.25 * f["rs_pct"] + 0.15 * f["ind_rs"] + 0.15 * f["p52_pct"] + 0.10 * f["tt"] / 8
             + 0.10 * quality) / 0.75)
    comp_np = comp.to_numpy()
    s0 = idx.searchsorted(pd.Timestamp(start))
    book = Book(cash=capital)
    orders: list[Order] = []
    entries_week: dict[tuple[int, int], int] = {}
    curve = []

    def sell(pos: Position, shares: int, price: float, day: int, reason: str) -> None:
        px = price * (1 - SLIPPAGE)
        value = shares * px
        cost = cost_model.leg(value, "sell").total
        book.cash += value - cost
        book.costs += cost
        pos.cash_in += value - cost
        pos.shares -= shares
        if pos.shares == 0:
            pnl = pos.cash_in - pos.cash_out
            book.trades.append({"symbol": pos.sym, "setup": pos.setup, "entry_date": pos.entry_date.date(),
                                "exit_date": idx[day].date(), "days": pos.days, "entry": round(pos.entry, 2),
                                "exit": round(px, 2), "shares": pos.shares0, "pnl": round(pnl, 2),
                                "R": round(pnl / (pos.risk_per_share * pos.shares0), 3), "reason": reason})
            del book.positions[pos.sym]

    def equity(day: int) -> float:
        val = book.cash
        for p in book.positions.values():
            px = c[day, col[p.sym]]
            val += p.shares * (px if np.isfinite(px) else p.entry)
        return val

    for d in range(s0, len(idx)):
        eq_prev = curve[-1]["equity"] if curve else capital
        reg_prev = int(reg["score"].iloc[d - 1]) if d > 0 else 0

        # 1. exits flagged at yesterday's close → sell at today's open
        for pos in list(book.positions.values()):
            j = col[pos.sym]
            if pos.exit_flag and np.isfinite(o[d, j]):
                sell(pos, pos.shares, o[d, j], d, pos.exit_flag)

        # 2. intraday: stops first (pessimistic), then targets
        for pos in list(book.positions.values()):
            j = col[pos.sym]
            if not np.isfinite(o[d, j]):
                continue
            if o[d, j] <= pos.stop:
                sell(pos, pos.shares, o[d, j], d, "stop (gap)")
                continue
            if lo[d, j] <= pos.stop:
                sell(pos, pos.shares, pos.stop, d, "stop")
                continue
            if pos.setup == "G_holy_grail" and pos.target and h[d, j] >= pos.target:
                sell(pos, pos.shares, max(o[d, j], pos.target), d, "target")
                continue
            two_r = pos.entry + 2 * pos.risk_per_share
            if pos.setup in BREAKOUT_SETUPS and not pos.partial_done and h[d, j] >= two_r and pos.shares >= 3:
                sell(pos, pos.shares // 3, max(o[d, j], two_r), d, "partial 2R")
                pos.partial_done = True

        # 3. entries
        week = tuple(idx[d].isocalendar()[:2])
        cap_frac, week_limit = REGIME_CAP[reg_prev]
        live = []
        for od in orders:
            if d - od.created > ORDER_LIFE or od.sym in book.positions:
                continue
            j = col[od.sym]
            if not np.isfinite(o[d, j]):
                live.append(od)
                continue
            if od.kind == "open":
                fill = o[d, j]
            else:
                if o[d, j] > od.trigger * (1 + LIMIT_ABOVE_TRIGGER):
                    live.append(od)          # gapped past the limit: no fill today
                    continue
                if h[d, j] < od.trigger:
                    live.append(od)
                    continue
                fill = max(o[d, j], od.trigger)
            od.trigger = fill
            live.append(od)
        filled = [od for od in live if od.kind == "open" or (np.isfinite(h[d, col[od.sym]]) and h[d, col[od.sym]] >= od.trigger
                                                              and o[d, col[od.sym]] <= od.trigger * (1 + LIMIT_ABOVE_TRIGGER))]
        filled.sort(key=lambda x: -x.score)
        done = set()
        for od in filled:
            if od.sym in book.positions or od.sym in done:
                continue
            j = col[od.sym]
            fill = od.trigger * (1 + SLIPPAGE) if od.kind == "stop" else o[d, j] * (1 + SLIPPAGE)
            if not np.isfinite(fill) or fill <= 0:
                continue                                  # no opening print (halted / suspended)
            if od.setup in BREAKOUT_SETUPS and reg_prev < 3:
                continue
            if entries_week.get(week, 0) >= week_limit or len(book.positions) >= MAX_POSITIONS:
                break
            stop = max(od.stop, fill * (1 - MAX_STOP))
            if not np.isfinite(stop) or stop >= fill:
                continue
            per_share = fill - stop
            shares = int(eq_prev * risk // per_share)
            shares = min(shares, int(POS_CAP * eq_prev // fill),
                         int(0.01 * med_to[d - 1, j] * 1e7 // fill) if np.isfinite(med_to[d - 1, j]) else 0)
            invested = sum(p.shares * c[d - 1, col[p.sym]] for p in book.positions.values()
                           if np.isfinite(c[d - 1, col[p.sym]]))
            room = cap_frac * eq_prev - invested
            shares = min(shares, int(max(room, 0) // fill))
            open_risk = sum(max(p.entry - p.stop, 0) * p.shares for p in book.positions.values())
            if open_risk + shares * per_share > OPEN_RISK_CAP * eq_prev:
                shares = int(max(OPEN_RISK_CAP * eq_prev - open_risk, 0) // per_share)
            if sum(1 for p in book.positions.values() if ind[p.sym] == ind[od.sym] and ind[od.sym] != "Unknown") >= PER_INDUSTRY:
                continue
            if book.positions:
                window = rets.iloc[max(0, d - 60):d]
                held = [p.sym for p in book.positions.values()]
                corr = window[held].corrwith(window[od.sym])
                if (corr > 0.75).any():
                    continue
            value = shares * fill
            cost = cost_model.leg(value, "buy").total if shares > 0 else 0.0
            if shares < 1 or value + cost > book.cash:
                continue
            book.cash -= value + cost
            book.costs += cost
            book.positions[od.sym] = Position(od.sym, od.setup, idx[d], fill, stop, shares, per_share, od.pivot,
                                              od.target, max_high=h[d, j], cash_out=value + cost, shares0=shares)
            entries_week[week] = entries_week.get(week, 0) + 1
            done.add(od.sym)
        orders = [od for od in live if od.sym not in done and od.kind == "stop" and d - od.created < ORDER_LIFE]

        # 4. close: trade management for tomorrow
        for pos in list(book.positions.values()):
            j = col[pos.sym]
            if not np.isfinite(c[d, j]):
                # Suspended, delisted or renamed (the panel splits renamed symbols): after 5 sessions
                # without a print, close at the last traded price rather than hold a dead slot forever.
                last = f["c"][pos.sym].iloc[:d + 1].last_valid_index()
                if last is not None and (d - idx.get_loc(last)) >= 5:
                    sell(pos, pos.shares, float(f["c"][pos.sym].loc[last]), d, "no prices (suspended/renamed)")
                continue
            pos.days += 1
            pos.max_high = max(pos.max_high, h[d, j])
            R = pos.risk_per_share
            if pos.max_high >= pos.entry + 1.5 * R and not pos.breakeven:
                pos.stop, pos.breakeven = max(pos.stop, pos.entry), True
            flag = None
            if pos.setup in BREAKOUT_SETUPS:
                if pos.setup in ("A_breakout", "A_breakout_confirmed", "B_vcp") and pos.days <= 3 and pos.pivot and c[d, j] < pos.pivot:
                    flag = "failed breakout"
                elif pos.setup == "E_burst" and pos.days >= 5:
                    flag = "burst 5-day exit"
                elif pos.breakeven and c[d, j] < ema20[d, j]:
                    flag = "trail 20-EMA"
                elif pos.days >= 10 and pos.max_high < pos.entry + R:
                    flag = "time stop"
            elif pos.setup == "F_rsi2":
                if c[d, j] > sma5[d, j] or rsi2[d, j] > 70:
                    flag = "rsi2 exit"
                elif pos.days >= 10:
                    flag = "time stop"
            elif pos.setup == "G_holy_grail" and pos.days >= 10:
                flag = "time stop"
            pos.exit_flag = flag

        # 5. tonight's signals → tomorrow's orders
        score_today = int(reg["score"].iloc[d])
        allowed = set()
        if score_today >= 3:
            allowed |= BREAKOUT_SETUPS | PULLBACK_SETUPS
        elif score_today == 2:
            allowed |= PULLBACK_SETUPS
        allowed &= setups_on
        pending = {od.sym for od in orders}
        for name in allowed:
            s = sig[name]
            row = s["signal"].iloc[d]
            for sym in row.index[row.to_numpy(dtype=bool)]:
                if sym in book.positions or sym in pending:
                    continue
                j = col[sym]
                sc = comp_np[d, j] if np.isfinite(comp_np[d, j]) else 0.0
                if "trigger" in s:
                    orders.append(Order(sym, name, "stop", d, float(s["trigger"].iat[d, j]), float(s["stop"].iat[d, j]),
                                        float(s["pivot"].iat[d, j]) if "pivot" in s else None,
                                        float(s["target"].iat[d, j]) if "target" in s else None, sc))
                else:
                    pv = float(s["pivot_open"].iat[d, j]) if "pivot_open" in s else None
                    orders.append(Order(sym, name, "open", d, 0.0, float(s["stop"].iat[d, j]), pv, None, sc))
                pending.add(sym)

        eq = equity(d)
        invested = eq - book.cash
        curve.append({"date": idx[d], "equity": eq, "cash": book.cash, "invested_pct": invested / eq if eq else 0,
                      "positions": len(book.positions), "regime": score_today})
    return pd.DataFrame(curve).set_index("date"), book


class _NoCost:
    """Gross run: no charges (to separate the rules' edge from costs)."""
    class _Z:
        total = 0.0

    def leg(self, value: float, side: str) -> "_NoCost._Z":
        return self._Z()


# ── reporting ───────────────────────────────────────────────────────────────────

def stats(curve: pd.Series) -> dict:
    r = curve.pct_change().dropna()
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    dd = curve / curve.cummax() - 1
    return {"cagr_pct": round(((curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1) * 100, 2),
            "total_return_pct": round((curve.iloc[-1] / curve.iloc[0] - 1) * 100, 1),
            "max_dd_pct": round(dd.min() * 100, 2),
            "sharpe": round(r.mean() / r.std() * math.sqrt(252), 2) if r.std() > 0 else None,
            "vol_pct": round(r.std() * math.sqrt(252) * 100, 1)}


def trade_stats(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0}
    wins, losses = t[t["R"] > 0], t[t["R"] <= 0]
    return {"trades": len(t), "win_rate_pct": round(len(wins) / len(t) * 100, 1),
            "avg_win_R": round(wins["R"].mean(), 2) if len(wins) else 0,
            "avg_loss_R": round(losses["R"].mean(), 2) if len(losses) else 0,
            "expectancy_R": round(t["R"].mean(), 3), "median_days": float(t["days"].median()),
            "best_R": round(t["R"].max(), 2), "worst_R": round(t["R"].min(), 2)}


def main() -> None:
    global SLIPPAGE
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--capital", type=float, default=500_000)
    ap.add_argument("--risk", type=float, default=0.005)
    ap.add_argument("--cost-profile", default="icici_moneysaver", choices=sorted(PROFILES) + ["none"])
    ap.add_argument("--slippage", type=float, default=SLIPPAGE)
    ap.add_argument("--setups", default="A_breakout,B_vcp,C_pocket_pivot,D_gap_up,E_burst,F_rsi2,G_holy_grail")
    ap.add_argument("--out", default="reports/handbook_swing")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    warm = (pd.Timestamp(args.start) - pd.Timedelta(days=600)).date().isoformat()
    data = load(warm)
    f = build(data)
    reg = regime(f, data)
    sig = setups(f)
    quality = setup_quality(f)
    SLIPPAGE = args.slippage
    cm = CostModel(PROFILES[args.cost_profile]) if args.cost_profile != "none" else _NoCost()
    variant = "confirmed" if "A_breakout_confirmed" in args.setups else "gtt"
    tag = f"{args.start[:4]}_{args.cost_profile}_s{args.slippage}_r{args.risk}_{variant}"
    curve, book = simulate(f, reg, sig, quality, args.start, args.capital, args.risk, cm, set(args.setups.split(",")))
    trades = pd.DataFrame(book.trades)
    trades.to_csv(out / f"trades_{tag}.csv", index=False)
    curve.to_csv(out / f"equity_{tag}.csv")
    n5 = reg["nifty500"].loc[curve.index]
    summary = {
        "window": [str(curve.index[0].date()), str(curve.index[-1].date())], "capital": args.capital,
        "risk_per_trade": args.risk, "cost_profile": args.cost_profile, "slippage_per_side": SLIPPAGE,
        "strategy": stats(curve["equity"]), "nifty500_price": stats(n5),
        "trades": trade_stats(trades), "costs_paid": round(book.costs, 0),
        "avg_invested_pct": round(curve["invested_pct"].mean() * 100, 1),
        "regime_days_pct": {int(k): round(v * 100, 1) for k, v in curve["regime"].value_counts(normalize=True).sort_index().items()},
        "by_setup": {k: trade_stats(g) for k, g in trades.groupby("setup")} if len(trades) else {},
        "by_exit": trades["reason"].value_counts().to_dict() if len(trades) else {},
        "by_year": {int(y): round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1)
                    for y, g in curve["equity"].groupby(curve.index.year)},
        "nifty500_by_year": {int(y): round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1) for y, g in n5.groupby(n5.index.year)},
        "open_positions": [{"symbol": q.sym, "setup": q.setup, "entry_date": str(q.entry_date.date()), "entry": round(q.entry, 2),
                            "shares": q.shares, "days": q.days,
                            "last_close": round(float(f["c"][q.sym].dropna().iloc[-1]), 2),
                            "last_traded": str(f["c"][q.sym].dropna().index[-1].date())} for q in book.positions.values()],
        "universe_symbols": len(f["cols"]), "runtime_s": round(time.time() - t0),
    }
    (out / f"summary_{tag}.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
