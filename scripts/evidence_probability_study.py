#!/usr/bin/env python
"""
Evidence → probability: every condition this project's studies tested, re-measured on ONE frame, turned into
conditional probabilities, merged into one P(outperform), and checked out of sample; plus label diagnostics for
short / swing / long horizons.

Pre-registered in reports/evidence_probability/PLAN.md (14 Oct 2026, 18:10 IST) before any number was computed.

    PYTHONPATH=. python scripts/evidence_probability_study.py [--out reports/evidence_probability] [--quick]

Reads a snapshot copy of data/market.duckdb (safe while data-service runs). Writes REPORT.md + CSVs to --out.
Research only: nothing here changes the Decision Desk or any trading rule.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from shared import xs_features as xf  # noqa: E402
from shared import xs_labels as xl  # noqa: E402
from shared.deal_filters import net_bulk_deals  # noqa: E402
from shared.momentum import is_etf, select  # noqa: E402
from shared.momentum import signals as desk_signals  # noqa: E402
from shared.nse_panel import load_panel  # noqa: E402
from shared.trading_costs import default_model  # noqa: E402
from ml_label_study import desk_universe, month_ends, period_returns, week_ends  # noqa: E402
from results_drift_study import build_events as results_events  # noqa: E402
from value_area_study import volume_profile  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)

PANEL_START = "2010-01-01"
SIGNAL_START = pd.Timestamp("2011-01-01")
P2_START = pd.Timestamp("2019-10-01")          # NSE event data (bulk deals, F&O, insider backfill) starts
P3_START = pd.Timestamp("2024-01-01")          # holdout
NSE_EVENTS_START = pd.Timestamp("2019-10-01")
HORIZONS = (5, 20, 60)
LABEL_HORIZONS = (5, 10, 20, 60, 120)
NW_LAGS = {5: 1, 10: 2, 20: 4, 60: 12, 120: 24}
PRIMARY_H = 20
MIN_PRICE, MIN_TURNOVER_CR, MIN_HISTORY = 20.0, 5.0, 250
POSITION_RS, BOOK_POSITION_RS = 50_000, 25_000
TEST_YEARS = list(range(2016, 2027))
VA_WINDOW, VA_BALANCE, HIGH_RELVOL = 20, 5, 2.0
TB_K = 1.0                                       # relative triple barrier at ±k·σ_rel·√h
LOGIT_C = 0.1                                    # L2 strength of the merged model (fixed, not tuned)
MIN_TRAIN_WEEKS = 26                             # a flag needs this many weeks with events to get a scorecard weight
PERIODS = {"P1 2011–19": (SIGNAL_START, P2_START), "P2 2019–23": (P2_START, P3_START),
           "P3 2024+": (P3_START, pd.Timestamp("2100-01-01")), "pre-2024": (SIGNAL_START, P3_START),
           "all": (SIGNAL_START, pd.Timestamp("2100-01-01"))}


@dataclass(frozen=True)
class Cond:
    key: str
    label: str
    family: str
    expected: int          # +1 expected to beat the market, −1 expected to lag, 0 no prior
    source: str
    universe: str = "L"    # "T": defined on the Desk's top 300 only (ML scores)


CONDITIONS = [
    Cond("mom_top10", "Momentum score, top decile", "Momentum & trend", +1, "phase_b (ADOPTED)"),
    Cond("mom_bot10", "Momentum score, bottom decile", "Momentum & trend", -1, "phase_b / ml_labels"),
    Cond("below_200dma", "Close below its 200-day average", "Momentum & trend", -1, "trend"),
    Cond("near_52w_high", "Within 5% of the 52-week high", "Momentum & trend", +1, "poc_conditional"),
    Cond("near_52w_low", "Within 10% of the 52-week low", "Momentum & trend", -1, "ml_labels"),
    Cond("high_vol", "60-day volatility, top decile", "Risk", -1, "ml_labels"),
    Cond("high_beta", "Beta, top decile", "Risk", -1, "ml_labels"),
    Cond("lottery_max", "Biggest 1-day gain in 20 days, top decile", "Risk", -1, "idea_lab (MAX)"),
    Cond("illiquid", "Amihud illiquidity, top decile", "Risk", 0, "ml_labels"),
    Cond("abnormal_volume", "Abnormal volume (5d vs 60d), top decile", "Volume & attention", -1, "idea_lab"),
    Cond("overnight_mom", "20-day overnight return, top decile", "Volume & attention", -1, "idea_lab"),
    Cond("delivery_surge_up", "Delivery surge top decile + 20d return > 0", "Volume & attention", 0, "held_overnight H1"),
    Cond("va_up_break", "Upside value-area break, last 5 sessions", "Price action", -1, "value_area"),
    Cond("va_up_break_hivol", "Upside VA break on ≥ 2× volume", "Price action", -1, "poc_conditional"),
    Cond("va_down_break_hivol", "Downside VA break on ≥ 2× volume", "Price action", -1, "poc_conditional"),
    Cond("breakout_52w", "52-week-high breakout on volume, last 5 sessions", "Price action", -1, "handbook A"),
    Cond("burst", "Burst: day ≥ +4% on higher volume, last 5 sessions", "Price action", -1, "handbook E"),
    Cond("rsi2_pullback", "RSI(2) < 5 above the 200-day average", "Price action", +1, "handbook F"),
    Cond("rsi2_leader", "RSI(2) < 5 in a momentum leader", "Price action", +1, "handbook F"),
    Cond("loser_5d", "5-day return, bottom decile", "Reversal", +1, "idea_lab"),
    Cond("quiet_loser_5d", "5-day bottom decile on below-normal volume", "Reversal", +1, "idea_lab"),
    Cond("loser_20d", "20-day return, bottom decile", "Reversal", +1, "classic reversal"),
    Cond("results_strong_down", "Strong bad results (≤ −5% vs market), last 60 sessions", "Results & corporate", -1,
         "results_drift H2"),
    Cond("results_strong_up", "Strong good results (≥ +5%), last 60 sessions", "Results & corporate", +1,
         "results_drift H1"),
    Cond("results_recent", "Any results, last 20 sessions", "Results & corporate", 0, "descriptive"),
    Cond("post_split", "Split / bonus ex-date, last 20 sessions", "Results & corporate", -1, "idea_lab"),
    Cond("bulk_other_buy", "Non-institutional bulk-deal net buy, last 20 sessions", "Flows", -1, "held_overnight H3"),
    Cond("bulk_inst_buy", "MF / insurer bulk-deal net buy, last 20 sessions", "Flows", +1, "held_overnight H3"),
    Cond("bulk_other_sell", "Non-institutional bulk-deal net sell, last 20 sessions", "Flows", 0, "held_overnight H3"),
    Cond("insider_fresh_buy", "Fresh insider buy (≥ ₹10 lakh), last 21 sessions", "Flows", +1, "held_overnight H4b"),
    Cond("insider_sale", "Insider sale (≥ ₹10 lakh), last 63 sessions", "Flows", 0, "held_overnight H4"),
    Cond("fo_long_buildup", "F&O long build-up (5d price > +3%, OI > +10%)", "Flows", 0, "held_overnight H2"),
    Cond("fo_short_buildup", "F&O short build-up (5d price < −3%, OI > +10%)", "Flows", 0, "held_overnight H2"),
    Cond("pcr_high", "Put/call OI ratio, top quintile of F&O stocks", "Flows", +1, "ml_labels (lead)"),
    Cond("mtf_surge_near_high", "Near 52w high + MTF growth top decile", "Flows", -1, "held_overnight H5"),
    Cond("shp_accumulation", "Shareholding accumulation filed, last 20 sessions", "Flows", +1, "held_overnight H6"),
    Cond("ml_bottom30", "ML A2 score, bottom 30% of the top 300", "ML", -1, "ml_labels §6 (lead)", "T"),
    Cond("ml_top10", "ML A2 score, top decile of the top 300", "ML", +1, "ml_labels", "T"),
]
BY_KEY = {c.key: c for c in CONDITIONS}
L_KEYS = [c.key for c in CONDITIONS if c.universe == "L"]
T_KEYS = [c.key for c in CONDITIONS]
NESTED = {"rsi2_leader", "quiet_loser_5d", "va_up_break_hivol"}   # subsets of another flag: not double-counted
COVERAGE = ["cov_results", "cov_insider", "cov_shp", "cov_fo", "cov_mtf", "cov_deals", "cov_deliv"]
# Coverage chosen with hindsight: results / insider / shareholding were fetched for stocks that are liquid NOW. As model
# inputs they leak the future ("this stock became a big liquid name"), so they are kept in training (each event flag is
# then measured against comparable covered stocks) but set to their training mean when predicting (correction after
# the first run, which let the model reward membership itself: reports/evidence_probability/first_run_coverage_leak/).
HINDSIGHT_COV = {"cov_results", "cov_insider", "cov_shp"}
# Post-hoc (added after the first run, not part of the merge): event-time versions of two state flags, to reconcile this
# weekly frame with the event studies (results_drift H2, held_overnight H3) that measured from the event itself.
EXPLORATORY = [
    Cond("results_strong_down_fresh", "Strong bad results in the last 5 sessions", "Exploratory (post-hoc)", -1,
         "results_drift H2, event time"),
    Cond("results_strong_up_fresh", "Strong good results in the last 5 sessions", "Exploratory (post-hoc)", +1,
         "results_drift H1, event time"),
    Cond("bulk_other_buy_fresh", "Non-institutional bulk-deal net buy in the last 5 sessions", "Exploratory (post-hoc)", -1,
         "held_overnight H3, event time"),
]
BY_KEY.update({c.key: c for c in EXPLORATORY})


# ── statistics ──────────────────────────────────────────────────────────────────

def nw_mean_se(x, lags: int) -> tuple[float, float, int]:
    """Mean, Newey-West (Bartlett) standard error and count of a weekly series with overlapping windows."""
    a = pd.Series(x, dtype=float).dropna().to_numpy()
    n = len(a)
    if n == 0:
        return float("nan"), float("nan"), 0
    m = float(a.mean())
    if n < 8:
        return m, float("nan"), n
    e = a - m
    s = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return m, (float(math.sqrt(s / n)) if s > 0 else float("nan")), n


def eb_shrink(theta: np.ndarray, se: np.ndarray, tau2: float | None = None) -> dict:
    """Empirical-Bayes normal shrinkage: true effects ~ N(0, τ²), τ² by method of moments (or given).
    Returns τ², posterior means / sds and P(the true effect has the posterior mean's sign)."""
    theta, se = np.asarray(theta, float), np.asarray(se, float)
    ok = np.isfinite(theta) & np.isfinite(se) & (se > 0)
    if tau2 is None:
        tau2 = float(max(0.0, np.mean(theta[ok] ** 2 - se[ok] ** 2))) if ok.any() else 0.0
    shrink = np.where(ok, se ** 2 / (se ** 2 + tau2) if tau2 > 0 else 1.0, np.nan)
    mean = (1 - shrink) * theta
    sd = np.sqrt((1 - shrink)) * se
    with np.errstate(invalid="ignore", divide="ignore"):
        p_sign = np.where(sd > 0, norm.cdf(np.abs(mean) / sd), 0.5)
    return {"tau2": tau2, "shrink": shrink, "mean": mean, "sd": sd, "p_sign": np.where(ok, p_sign, np.nan)}


def verdict(pre: dict, post: dict, min_weeks: int = 20) -> str:
    """PLAN.md rule on the weekly mean-excess difference (flagged minus covered stocks, same weeks)."""
    if not pre or not post or pre.get("weeks", 0) < min_weeks or post.get("weeks", 0) < min_weeks:
        return "too little data"
    s1, s2 = np.sign(pre["d_ex"]), np.sign(post["d_ex"])
    t1, t2 = abs(pre["t_ex"]), abs(post["t_ex"])
    if not (np.isfinite(t1) and np.isfinite(t2)):
        return "too little data"
    if s1 == s2 and t1 >= 2 and t2 >= 2:
        return "Robust"
    if s1 == s2 and max(t1, t2) >= 2 and min(t1, t2) >= 1:
        return "Holds (weaker)"
    if s1 != s2 and max(t1, t2) >= 2:
        return "Unstable"
    return "No effect"


def weekly_series(d: pd.DataFrame, cond: str, ex: str, rk: str) -> pd.DataFrame:
    """Per signal week: flagged (A) vs all covered (E) stocks: mean excess, win, bottom- and top-quintile rates."""
    x = d.loc[d[cond].notna() & d[ex].notna() & d[rk].notna(), ["date", cond, ex, rk]]
    if x.empty:
        return pd.DataFrame()
    x = x.assign(win=(x[ex] > 0).astype(float), bot=(x[rk] <= 0.2).astype(float), top=(x[rk] > 0.8).astype(float))
    e = x.groupby("date").agg(nE=(ex, "size"), exE=(ex, "mean"), winE=("win", "mean"), botE=("bot", "mean"),
                              topE=("top", "mean"))
    a = x[x[cond] == 1].groupby("date").agg(nA=(ex, "size"), exA=(ex, "mean"), winA=("win", "mean"),
                                           botA=("bot", "mean"), topA=("top", "mean"))
    if a.empty:
        return pd.DataFrame()
    out = a.join(e, how="left")
    out["d_ex"], out["d_win"], out["d_bot"] = out.exA - out.exE, out.winA - out.winE, out.botA - out.botE
    return out


def summarize(ws: pd.DataFrame, lags: int, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    if ws is None or ws.empty:
        return {}
    w = ws[(ws.index >= start) & (ws.index < end)]
    if w.empty:
        return {}
    n = float(w.nA.sum())

    def pooled(col: str) -> float:
        return float((w[col] * w.nA).sum() / n * 100)
    out = {"weeks": int(len(w)), "events": int(n), "exA": pooled("exA"), "winA": pooled("winA"), "winE": pooled("winE"),
           "botA": pooled("botA"), "botE": pooled("botE"), "topA": pooled("topA")}
    for k in ("ex", "win", "bot"):
        m, se, _ = nw_mean_se(w[f"d_{k}"], lags)
        out[f"d_{k}"], out[f"se_{k}"] = m * 100, se * 100
        out[f"t_{k}"] = m / se if se and np.isfinite(se) and se > 0 else float("nan")
    return out


def weekly_ic(d: pd.DataFrame, score: str, target: str) -> pd.Series:
    x = d[["date", score, target]].dropna()
    if x.empty:
        return pd.Series(dtype=float)
    r = x.groupby("date")[[score, target]].rank()
    r["date"] = x["date"].to_numpy()
    return r.groupby("date").apply(lambda g: g[score].corr(g[target]) if len(g) > 10 else np.nan,
                                   include_groups=False).dropna()


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


# ── value-area events (worker) ──────────────────────────────────────────────────

def va_one(args: tuple) -> tuple:
    """Balanced (5 closes inside the prior 20-day value area) → close outside it: upside / downside break, and the
    break-day volume vs the prior 20-day median. Same profile as scripts/value_area_study.py."""
    sym, hi, lo, cl, vo = args
    n = len(cl)
    up, dn, rv = np.zeros(n, bool), np.zeros(n, bool), np.full(n, np.nan)
    for t in range(VA_WINDOW, n):
        s = slice(t - VA_WINDOW, t)
        med = float(np.median(vo[s]))
        if med > 0:
            rv[t] = vo[t] / med
        poc, val, vah = volume_profile(hi[s], lo[s], vo[s], 50, 0.70)
        if not np.isfinite(poc):
            continue
        prior = cl[t - VA_BALANCE:t]
        if np.all((prior >= val) & (prior <= vah)):
            if cl[t] > vah:
                up[t] = True
            elif cl[t] < val:
                dn[t] = True
    return sym, up, dn, rv


def va_frames(P: dict, workers: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c, h, lo, v = P["close"], P["high"], P["low"], P["volume"]
    idx, cols = c.index, c.columns
    H, Lo, C, V = (f.to_numpy(float) for f in (h, lo, c, v))
    tasks, where = [], {}
    for j, s in enumerate(cols):
        ok = np.isfinite(H[:, j]) & np.isfinite(Lo[:, j]) & np.isfinite(C[:, j]) & np.isfinite(V[:, j])
        pos = np.flatnonzero(ok)
        if len(pos) <= VA_WINDOW + VA_BALANCE:
            continue
        where[s] = pos
        tasks.append((s, H[pos, j], Lo[pos, j], C[pos, j], V[pos, j]))
    up = np.zeros(C.shape, np.float32)
    dn = np.zeros(C.shape, np.float32)
    rv = np.full(C.shape, np.nan, np.float32)
    col_of = {s: j for j, s in enumerate(cols)}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for s, u, d, r in ex.map(va_one, tasks, chunksize=8):
            j, pos = col_of[s], where[s]
            up[pos, j], dn[pos, j], rv[pos, j] = u, d, r
    mk = lambda a: pd.DataFrame(a, index=idx, columns=cols)  # noqa: E731
    return mk(up), mk(dn), mk(rv)


# ── data ────────────────────────────────────────────────────────────────────────

def load() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="evidence_"))
    db = ROOT / "data" / "market.duckdb"
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    con = duckdb.connect(str(snap))
    try:
        q = lambda s: con.execute(s).df()  # noqa: E731
        out = {
            "panel": load_panel(con, start=PANEL_START),
            "fo": q("SELECT date, symbol, kind, fut_oi, call_oi, put_oi FROM nse_fo_daily"),
            "deals": q("SELECT date, kind, symbol, client_name, side, qty FROM nse_deals WHERE kind = 'bulk'"),
            "mtf": q("SELECT date, symbol, qty_financed FROM nse_mtf"),
            "insider": q("SELECT symbol, category, mode, value, from_date, to_date, intimation_date "
                         "FROM nse_insider_trades WHERE intimation_date IS NOT NULL"),
            "insider_symbols": set(q("SELECT DISTINCT symbol FROM nse_insider_trades")["symbol"]),
            "shp": q("SELECT * FROM nse_shareholding"),
            "releases": q("SELECT symbol, period_end, released_at FROM nse_results "
                          "WHERE released_at IS NOT NULL AND released_at >= TIMESTAMP '2010-03-01'"),
            "nifty": q("SELECT date, close FROM market_index_daily WHERE symbol = 'NIFTY50' ORDER BY date"),
        }
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    for k in ("fo", "deals", "mtf"):
        out[k]["date"] = pd.to_datetime(out[k]["date"])
    n = out["nifty"]
    out["nifty"] = pd.Series(n["close"].to_numpy(float), index=pd.to_datetime(n["date"]))
    return out


def holdings_symbols() -> list[str]:
    try:
        return [p["symbol"] for p in json.loads((ROOT / "data" / "last_holdings.json").read_text())["positions"]]
    except (OSError, ValueError, KeyError):
        return []


def liquid_universe(P: dict) -> pd.DataFrame:
    """Universe L: EQ, raw close ≥ ₹20, 20-session median turnover ≥ ₹5 cr, ≥ 250 sessions, no ETFs (point in time)."""
    c = P["close"]
    etf = pd.Series([is_etf(s) for s in c.columns], index=c.columns)
    med20 = P["turnover_cr"].rolling(20, min_periods=10).median()
    hist = c.notna().cumsum()
    return P["series"].eq("EQ") & P["raw_close"].ge(MIN_PRICE) & med20.ge(MIN_TURNOVER_CR) & hist.ge(MIN_HISTORY) & ~etf


def event_frame(ev: pd.DataFrame, like: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """1.0 on (session, symbol) of each event, 0.0 elsewhere. Event dates must be sessions of `like`."""
    a = np.zeros(like.shape, np.float32)
    if ev is not None and len(ev):
        e = ev[[date_col, "symbol"]].dropna()
        r = like.index.get_indexer(pd.to_datetime(e[date_col]))
        c = like.columns.get_indexer(e["symbol"])
        ok = (r >= 0) & (c >= 0)
        a[r[ok], c[ok]] = 1.0
    return pd.DataFrame(a, index=like.index, columns=like.columns)


def recent(events: pd.DataFrame, n: int) -> pd.DataFrame:
    return events.rolling(n, min_periods=1).max()


def since_first(first: pd.Series, like: pd.DataFrame) -> pd.DataFrame:
    """True from each symbol's first event session onward (symbols without one: never)."""
    pos = pd.Series(like.index.searchsorted(pd.to_datetime(first.to_numpy())), index=first.index)
    p = pos.reindex(like.columns).fillna(len(like.index) + 1).to_numpy()
    return pd.DataFrame(np.arange(len(like.index))[:, None] >= p[None, :], index=like.index, columns=like.columns)


def shp_accumulation(shp: pd.DataFrame, index: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.Series]:
    """H6 events (shareholder count down, FPI + MF up > 0.5 pp vs the previous quarter), dated by broadcast session,
    and each symbol's first broadcast session (coverage)."""
    s = shp.copy()
    s["period_end"] = pd.to_datetime(s["period_end"], errors="coerce")
    s = s[s["period_end"].dt.is_quarter_end.fillna(False) & s["total_holders"].notna()]
    s["broadcast"] = pd.to_datetime(s["broadcast_ts"].astype(str).str.slice(0, 11), format="%d-%b-%Y", errors="coerce")
    s = s.sort_values(["symbol", "period_end", "broadcast"]).drop_duplicates(["symbol", "period_end"], keep="last")
    s["inst"] = (s["fpi_pct"].fillna(0) + s["mf_pct"].fillna(0)).where(s["fpi_pct"].notna() | s["mf_pct"].notna())
    g = s.groupby("symbol")
    consecutive = (s["period_end"] - g["period_end"].shift()).dt.days.between(80, 100)
    s["d_holders"] = g["total_holders"].pct_change().where(consecutive)
    s["d_inst"] = g["inst"].diff().where(consecutive)
    s["date"] = xf.to_session(s["broadcast"], index)
    s = s.dropna(subset=["date"])
    acc = s[(s["d_holders"] < 0) & (s["d_inst"] > 0.5)][["date", "symbol"]]
    return acc, s.groupby("symbol")["date"].min()


# ── models ──────────────────────────────────────────────────────────────────────

def design(d: pd.DataFrame, keys: list[str], cov: list[str], mom_col: str) -> np.ndarray:
    m = d[mom_col].fillna(0.5).to_numpy(float)
    return np.column_stack([d[keys].fillna(0.0).to_numpy(float), d[cov].fillna(0.0).to_numpy(float), m])


def scorecard_weights(ws: dict, keys: list[str], cutoff: pd.Timestamp, target: str, base: float,
                      h: int = PRIMARY_H) -> pd.Series:
    """Per flag: the weekly win- (or bottom-) rate difference vs covered stocks up to `cutoff`, as a log-odds shift
    around `base`, shrunk across flags (empirical Bayes). Flags with < MIN_TRAIN_WEEKS weeks of events get 0."""
    scale = base * (1 - base)
    rows = []
    for k in keys:
        s = ws.get(k)
        if s is None or s.empty:
            continue
        s = s[s.index <= cutoff]
        if len(s) < MIN_TRAIN_WEEKS:
            continue
        m, se, _ = nw_mean_se(s[f"d_{target}"], NW_LAGS[h])
        rows.append((k, m / scale, se / scale))
    if not rows:
        return pd.Series(dtype=float)
    k, w, se = zip(*rows)
    eb = eb_shrink(np.array(w), np.array(se))
    return pd.Series(np.nan_to_num(eb["mean"]), index=list(k))


def walk_forward(df: pd.DataFrame, uni: str, ex: str, rk: str, keys: list[str], cov: list[str], mom_col: str,
                 ws: dict, sessions: pd.DatetimeIndex, years: list[int], log, final_cutoff: pd.Timestamp | None = None,
                 h: int = PRIMARY_H) -> tuple[pd.DataFrame, list[dict], dict]:
    """Yearly refits (training ends h + 1 sessions before the test year). Models: A momentum only, B the scorecard,
    C the L2 logistic on all flags. Targets: win (excess > 0) and bot (bottom quintile). Hindsight-chosen coverage
    flags are set to their training mean when predicting (HINDSIGHT_COV).
    With final_cutoff, one more fit on everything labelled up to it, used for today's readings."""
    from sklearn.linear_model import LogisticRegression
    rows = df[uni].astype(bool)
    y_all = {"win": (df[ex] > 0).astype(float).where(df[ex].notna()),
             "bot": (df[rk] <= 0.2).astype(float).where(df[rk].notna())}
    starts = {k: df.loc[df[k].notna() & rows, "date"].min() for k in keys + cov}
    out = pd.DataFrame(index=df.index[rows])
    log_rows: list[dict] = []
    final: dict = {}
    plan = [(y, sessions[sessions.searchsorted(pd.Timestamp(f"{y}-01-01")) - h - 1]) for y in years]
    if final_cutoff is not None:
        plan.append(("final", final_cutoff))
    for y, cutoff in plan:
        tr = rows & df["is_week"] & (df["date"] <= cutoff) & y_all["win"].notna()
        te = rows & ((df["date"].dt.year == y) if y != "final" else (df["date"] == df["date"].max()))
        if te.sum() == 0 or tr.sum() < 5000:
            continue

        def ok(k: str) -> bool:
            return pd.notna(starts[k]) and starts[k] <= cutoff - pd.DateOffset(years=2)
        kk, cc = [k for k in keys if ok(k)], [k for k in cov if ok(k)]
        dtr, dte = df.loc[tr], df.loc[te]
        Xtr, Xte = design(dtr, kk, cc, mom_col), design(dte, kk, cc, mom_col)
        neutral = {cv: float(Xtr[:, len(kk) + i].mean()) for i, cv in enumerate(cc) if cv in HINDSIGHT_COV}
        Xtr_n, Xte_n = Xtr.copy(), Xte.copy()
        for i, cv in enumerate(cc):
            if cv in neutral:
                Xtr_n[:, len(kk) + i] = neutral[cv]
                Xte_n[:, len(kk) + i] = neutral[cv]
        mtr, mte = dtr[mom_col].fillna(0.5).to_numpy(float), dte[mom_col].fillna(0.5).to_numpy(float)
        rec: dict = {"year": y, "cutoff": str(cutoff.date()), "train_rows": int(tr.sum()), "test_rows": int(te.sum()),
                     "flags": len(kk)}
        for target in ("win", "bot"):
            ytr = y_all[target][tr].to_numpy(float)
            base = float(ytr.mean())
            a = LogisticRegression(C=1.0, max_iter=300).fit(np.column_stack([mtr, mtr ** 2]), ytr)
            cm = LogisticRegression(C=LOGIT_C, max_iter=500).fit(Xtr, ytr)
            w = scorecard_weights(ws, [k for k in kk if k not in NESTED], cutoff, target, base, h)
            score_te = dte[list(w.index)].fillna(0.0).to_numpy(float) @ w.to_numpy() if len(w) else 0.0
            score_tr = dtr[list(w.index)].fillna(0.0).to_numpy(float) @ w.to_numpy() if len(w) else 0.0
            p_c_tr = cm.predict_proba(Xtr_n)[:, 1]
            p_b_tr = sigmoid(logit(base) + score_tr)
            q = 0.9 if target == "win" else 0.8
            preds = {
                f"pA_{target}": a.predict_proba(np.column_stack([mte, mte ** 2]))[:, 1],
                f"pB_{target}": sigmoid(logit(base) + score_te) * np.ones(len(dte)),
                f"pC_{target}": cm.predict_proba(Xte_n)[:, 1],
                f"thrB_{target}": np.full(len(dte), np.quantile(p_b_tr, q)),
                f"thrC_{target}": np.full(len(dte), np.quantile(p_c_tr, q)),
                f"base_{target}": np.full(len(dte), base),
            }
            for col, val in preds.items():
                out.loc[dte.index, col] = val
            rec[f"base_{target}"] = round(base, 4)
            coefs = dict(zip(kk + cc + ["mom_pct"], cm.coef_[0]))
            if y == "final":
                final[target] = {"coef": coefs, "intercept": float(cm.intercept_[0]), "scorecard": w.to_dict(),
                                 "base": base, "thrC": float(np.quantile(p_c_tr, q)), "neutral": neutral}
            else:
                rec[f"coef_{target}"] = {k: round(float(v), 4) for k, v in coefs.items()}
        log_rows.append(rec)
        log(f"  {uni} h={h} {y}: train {rec['train_rows']:,} rows, {len(kk)} flags, test {rec['test_rows']:,}")
    return out, log_rows, final


def calibration(p: np.ndarray, y: np.ndarray, base: np.ndarray) -> dict:
    ok = np.isfinite(p) & np.isfinite(y) & np.isfinite(base)
    p, y, base = p[ok], y[ok], base[ok]
    if len(p) < 100:
        return {}
    brier, brier0 = float(np.mean((y - p) ** 2)), float(np.mean((y - base) ** 2))
    vp = float(np.var(p))
    slope = float(np.cov(y, p, bias=True)[0, 1] / vp) if vp > 0 else float("nan")
    bins = pd.qcut(pd.Series(p), 10, labels=False, duplicates="drop")
    table = pd.DataFrame({"p": p, "y": y, "bin": bins.to_numpy()}).groupby("bin").agg(
        predicted=("p", "mean"), realised=("y", "mean"), rows=("y", "size"))
    return {"rows": int(len(p)), "brier": brier, "brier_base": brier0, "skill": 1 - brier / brier0, "slope": slope,
            "mean_p": float(p.mean()), "mean_y": float(y.mean()), "table": table}


def run_book(score: pd.DataFrame, rets: pd.DataFrame, uni: pd.DataFrame, cost_side: float,
             blocked: pd.DataFrame | None = None, n: int = 20) -> pd.DataFrame:
    """Top-n with the Desk's 1.5× buffer each month; `blocked` names are never newly bought (held ones may stay)."""
    held: set[str] = set()
    rows = []
    for d in score.index:
        if d not in rets.index or rets.loc[d].isna().all():
            continue
        members = uni.loc[d]
        s = score.loc[d].where(members).dropna()
        if len(s) < 50:
            continue
        blk = None
        if blocked is not None and d in blocked.index:
            b = blocked.loc[d].fillna(False).astype(bool)
            blk = set(b.index[b.to_numpy()])
        pick = select(s, held, n, buffer=1.5, blocked=blk)
        traded = len(set(pick) ^ held)
        r = rets.loc[d]
        gross, bench = r.reindex(pick).fillna(0).mean(), r.where(members).mean()
        cost = traded / n * cost_side
        rows.append({"date": d, "gross": gross, "bench": bench, "cost": cost, "net_excess": gross - cost - bench,
                     "turnover": traded / (2 * n)})
        held = set(pick)
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def book_summary(b: pd.DataFrame) -> dict:
    out = {}
    for name, part in (("2016–23", b[b.index < P3_START]), ("2024+", b[b.index >= P3_START]), ("all", b)):
        ex = part["net_excess"]
        out[f"net_{name}"] = round(float(ex.mean() * 12 * 100), 2) if len(ex) else float("nan")
        out[f"ir_{name}"] = round(float(ex.mean() / ex.std(ddof=1) * math.sqrt(12)), 2) if len(ex) > 2 else float("nan")
    out["turnover"] = round(float(b["turnover"].mean()), 3)
    out["cost_pa"] = round(float(b["cost"].mean() * 12 * 100), 2)
    out["months"] = int(len(b))
    return out


# ── label diagnostics ───────────────────────────────────────────────────────────

def relative_triple_barrier(C: np.ndarray, O: np.ndarray, I: np.ndarray, on: np.ndarray, sig: np.ndarray,
                            pos: np.ndarray, h: int, k: float) -> tuple[np.ndarray, np.ndarray]:
    """For signal rows `pos` (session positions) × all columns: the first touch of ±k·σ√h by the stock's price
    relative to the equal-weight universe index, from the next open; 0 if neither within h sessions.
    Returns (label in {−1, 0, +1} or NaN, sessions to the touch)."""
    n = C.shape[0]
    entry_pos = pos + 1
    valid_rows = entry_pos + h < n
    lab = np.full((len(pos), C.shape[1]), np.nan)
    days = np.full_like(lab, np.nan)
    if not valid_rows.any():
        return lab, days
    p = pos[valid_rows]
    o_entry = O[p + 1]
    i_entry = I[p] * (1 + np.nan_to_num(on[p + 1]))
    bar = k * sig[p] * math.sqrt(h)
    res = np.zeros_like(o_entry)
    dd = np.full_like(o_entry, np.nan)
    done = np.zeros(o_entry.shape, bool)
    for j in range(1, h + 1):
        rel = (C[p + j] / o_entry) / (I[p + j] / i_entry)[:, None] - 1
        upj, dnj = (rel >= bar) & ~done, (rel <= -bar) & ~done
        res[upj], res[dnj] = 1.0, -1.0
        dd[upj | dnj] = j
        done |= upj | dnj
    ok = np.isfinite(o_entry) & np.isfinite(bar) & np.isfinite(C[p + h])
    res[~ok], dd[~ok] = np.nan, np.nan
    lab[valid_rows], days[valid_rows] = res, dd
    return lab, days


# ── report helpers ──────────────────────────────────────────────────────────────

def f(v, d: int = 2, pct: bool = False, sign: bool = False) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    s = f"{v:+.{d}f}" if sign else f"{v:.{d}f}"
    return s + ("%" if pct else "")


def n_(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) and np.isfinite(v) else "0"


def md(rows: list[list], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


# ── main ────────────────────────────────────────────────────────────────────────

def main() -> None:  # noqa: C901 — one linear pipeline, kept in one place so the plan maps onto it
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/evidence_probability")
    ap.add_argument("--quick", action="store_true", help="a sample of symbols from 2015, to test the pipeline")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--symbols", default="", help="extra symbols for today's readings (default: data/last_holdings.json)")
    args = ap.parse_args()
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)  # noqa: E731

    data = load()
    full = data["panel"]
    sessions = full["close"].index
    log(f"panel {full['close'].shape}, {sessions.min().date()} → {sessions.max().date()}")
    weeks = week_ends(sessions)
    months = month_ends(sessions)
    start = pd.Timestamp("2015-01-01") if args.quick else SIGNAL_START
    weeks, months = weeks[weeks >= start], months[months >= start]
    dates = weeks.union(months)
    last = dates.max()

    sig_full = desk_signals(full)
    L_full = liquid_universe(full)
    T_full = desk_universe(full, sig_full, dates)
    wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or holdings_symbols()
    hold = [s for s in wanted if s in full["close"].columns]
    ev_res = results_events(full, data["releases"])               # benchmark = every liquid name, as in that study
    log(f"results events {len(ev_res):,}; holdings {hold}")
    in_any = L_full.reindex(dates).fillna(False).any(axis=0) | T_full.any(axis=0)
    members = in_any[in_any].index.union(pd.Index(hold))
    if args.quick:
        rng = np.random.default_rng(7)
        members = pd.Index(sorted(set(rng.choice(members.to_numpy(), size=min(500, len(members)), replace=False))
                                  | set(hold)))
    P = {k: (v[members] if isinstance(v, pd.DataFrame) and v.index.equals(sessions) else v) for k, v in full.items()}
    L = L_full[members]
    mom = sig_full["mom_nse"][members]
    Td = T_full.reindex(index=dates, columns=members).fillna(False).astype(bool)
    del full, sig_full, L_full, T_full
    Ld = L.reindex(dates).fillna(False).astype(bool)
    Hd = pd.DataFrame(False, index=dates, columns=members)
    if hold:
        Hd.loc[last, hold] = True
    rankL = Ld | Hd
    rowmask = (Ld | Td | Hd).to_numpy()
    ri, ci = np.nonzero(rowmask)
    df = pd.DataFrame({"date": dates[ri], "symbol": members[ci], "inL": Ld.to_numpy()[ri, ci],
                       "inT": Td.to_numpy()[ri, ci], "held": Hd.to_numpy()[ri, ci]})
    df["is_week"], df["is_month"] = df["date"].isin(weeks), df["date"].isin(months)
    log(f"{len(members)} symbols, {len(dates)} signal dates, {len(df):,} stock-dates "
        f"(L {int(df.inL.sum()):,}, top-300 {int(df.inT.sum()):,})")

    def take(frame: pd.DataFrame) -> np.ndarray:
        return frame.reindex(index=dates, columns=members).to_numpy(dtype=float, na_value=np.nan)[ri, ci]

    def xs_rank(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
        return frame.reindex(index=dates, columns=members).where(mask).rank(axis=1, pct=True)

    def flag(cond: pd.DataFrame, valid: pd.DataFrame) -> pd.DataFrame:
        return cond.astype(float).where(valid)

    # ── outcomes ─────────────────────────────────────────────────────────────────
    c, o, hi, lo, v = P["close"], P["open"], P["high"], P["low"], P["volume"]
    for h in sorted(set(HORIZONS) | set(LABEL_HORIZONS)):
        fwd = xl.forward_open_returns(o, h).where(xl.clean_windows(c, h + 1)).reindex(dates)
        exL = fwd.where(Ld)
        exL = exL.sub(exL.mean(axis=1), axis=0)
        exT = fwd.where(Td)
        exT = exT.sub(exT.mean(axis=1), axis=0)
        df[f"fwd_{h}"], df[f"exL_{h}"], df[f"exT_{h}"] = take(fwd), take(exL), take(exT)
        df[f"rkL_{h}"], df[f"rkT_{h}"] = take(exL.rank(axis=1, pct=True)), take(exT.rank(axis=1, pct=True))
    log("outcomes done")

    # ── conditions ───────────────────────────────────────────────────────────────
    r = c.pct_change(fill_method=None)
    mom_r = xs_rank(mom, rankL)
    df["mom_raw"], df["mom_pctL"] = take(mom), take(mom_r)
    df["mom_pctT"] = take(mom.reindex(index=dates, columns=members).where(Td).rank(axis=1, pct=True))
    df["mom_top10"], df["mom_bot10"] = take(flag(mom_r >= 0.9, mom_r.notna())), take(flag(mom_r <= 0.1, mom_r.notna()))
    sma50, sma200 = c.rolling(50, min_periods=40).mean(), c.rolling(200, min_periods=150).mean()
    hi252, lo252 = c.rolling(252, min_periods=200).max(), c.rolling(252, min_periods=200).min()
    df["below_200dma"] = take(flag(c < sma200, sma200.notna() & c.notna()))
    near_high = c >= 0.95 * hi252
    df["near_52w_high"] = take(flag(near_high, hi252.notna() & c.notna()))
    df["near_52w_low"] = take(flag(c <= 1.10 * lo252, lo252.notna() & c.notna()))
    df["hi_ratio"] = take(c / hi252)

    vol60 = r.rolling(60, min_periods=45).std()
    df["vol60"] = take(vol60)
    prev_member = L.shift(1, fill_value=False)
    mkt = r.where(prev_member).mean(axis=1)
    cov_ = r.mul(mkt, axis=0).rolling(252, min_periods=200).mean() - r.rolling(252, min_periods=200).mean().mul(
        mkt.rolling(252, min_periods=200).mean(), axis=0)
    beta = cov_.div(mkt.rolling(252, min_periods=200).var(ddof=0), axis=0)
    max20 = r.rolling(20, min_periods=15).max()
    amihud = (r.abs() / P["turnover_cr"].where(P["turnover_cr"] > 0)).rolling(60, min_periods=45).mean()
    volr = np.log(v.rolling(5, min_periods=4).mean() / v.rolling(60, min_periods=45).mean()).replace([np.inf, -np.inf], np.nan)
    on20 = np.log(o / c.shift(1)).replace([np.inf, -np.inf], np.nan).rolling(20, min_periods=15).sum()
    ret5, ret20 = c / c.shift(5) - 1, c / c.shift(20) - 1
    df["ret5"], df["ret20"] = take(ret5), take(ret20)
    for key, frame, top in (("high_vol", vol60, True), ("high_beta", beta, True), ("lottery_max", max20, True),
                            ("illiquid", amihud, True), ("abnormal_volume", volr, True), ("overnight_mom", on20, True),
                            ("loser_5d", ret5, False), ("loser_20d", ret20, False)):
        rk = xs_rank(frame, rankL)
        df[key] = take(flag(rk >= 0.9 if top else rk <= 0.1, rk.notna()))
    volr_w = volr.reindex(index=dates, columns=members)
    rk5 = xs_rank(ret5, rankL)
    df["quiet_loser_5d"] = take(flag((rk5 <= 0.1) & (volr_w < 0), rk5.notna() & volr_w.notna()))
    delivered = v * P["deliv_pct"] / 100.0
    surge = delivered.rolling(5, min_periods=4).mean() / delivered.shift(5).rolling(60, min_periods=40).mean()
    surge = surge.replace([np.inf, -np.inf], np.nan)
    rks = xs_rank(surge, rankL)
    ret20_w = ret20.reindex(index=dates, columns=members)
    df["delivery_surge_up"] = take(flag((rks >= 0.9) & (ret20_w > 0), rks.notna() & ret20_w.notna()))
    df["cov_deliv"] = take(surge.notna().astype(float))
    log("price / risk / volume flags done")

    up_ev, dn_ev, relvol = va_frames(P, args.workers)
    valid_c = c.notna()
    df["va_up_break"] = take(flag(recent(up_ev, 5) > 0, valid_c))
    df["va_up_break_hivol"] = take(flag(recent((up_ev > 0) & (relvol >= HIGH_RELVOL), 5) > 0, valid_c))
    df["va_down_break_hivol"] = take(flag(recent((dn_ev > 0) & (relvol >= HIGH_RELVOL), 5) > 0, valid_c))
    del up_ev, dn_ev, relvol
    log("value-area flags done")

    prior_hi = c.shift(1).rolling(252, min_periods=200).max()
    vol50 = v.shift(1).rolling(50, min_periods=40).mean()
    rng_ = hi - lo
    brk = (c > prior_hi) & (v >= 1.5 * vol50) & (rng_ > 0) & ((c - lo) >= 0.6 * rng_)
    df["breakout_52w"] = take(flag(recent(brk.astype(float), 5) > 0, prior_hi.notna()))
    burst = (r >= 0.04) & (v > v.shift(1))
    df["burst"] = take(flag(recent(burst.astype(float), 5) > 0, valid_c))
    rsi2 = xf._rsi(c, 2)
    pull = flag((rsi2 < 5) & (c > sma200), rsi2.notna() & sma200.notna())
    df["rsi2_pullback"] = take(pull)
    pull_w = pull.reindex(index=dates, columns=members)
    df["rsi2_leader"] = take(flag((pull_w == 1) & (mom_r >= 0.7), pull_w.notna() & mom_r.notna()))

    # results, splits
    res_first = data["releases"].groupby("symbol")["released_at"].min()
    cov_res = since_first(res_first, c)
    ev = ev_res.rename(columns={"reaction_date": "date"})
    df["results_strong_down"] = take(flag(recent(event_frame(ev[ev.bucket == "strong down"], c), 60) > 0, cov_res))
    df["results_strong_up"] = take(flag(recent(event_frame(ev[ev.bucket == "strong up"], c), 60) > 0, cov_res))
    df["results_recent"] = take(flag(recent(event_frame(ev, c), 20) > 0, cov_res))
    df["results_strong_down_fresh"] = take(flag(recent(event_frame(ev[ev.bucket == "strong down"], c), 5) > 0, cov_res))
    df["results_strong_up_fresh"] = take(flag(recent(event_frame(ev[ev.bucket == "strong up"], c), 5) > 0, cov_res))
    df["cov_results"] = take(cov_res.astype(float))
    ca = P["corporate_actions"]
    df["post_split"] = take(flag(recent(event_frame(ca[ca["k"] < 1], c), 20) > 0, valid_c))

    # bulk deals
    net = net_bulk_deals(data["deals"])
    net["date"] = pd.to_datetime(net["date"])
    live = pd.DataFrame(np.broadcast_to((c.index >= NSE_EVENTS_START)[:, None], c.shape), index=c.index, columns=c.columns)
    for key, inst, side in (("bulk_other_buy", False, "buy"), ("bulk_inst_buy", True, "buy"),
                            ("bulk_other_sell", False, "sell")):
        e = net[(net["institution"] == inst) & (net["direction"] == side)]
        df[key] = take(flag(recent(event_frame(e, c), 20) > 0, live))
        if key == "bulk_other_buy":
            df["bulk_other_buy_fresh"] = take(flag(recent(event_frame(e, c), 5) > 0, live))
    df["cov_deals"] = take(live.astype(float))

    # insider (covered symbols, from 2019-10)
    ins = xf.per_company_features(P, data["insider"], None, data["insider_symbols"])
    df["insider_fresh_buy"] = take(flag(ins["insider_fresh_buy_21d"] > 0, ins["insider_fresh_buy_21d"].notna()))
    df["insider_sale"] = take(flag(ins["insider_sell_63d"] > 0, ins["insider_sell_63d"].notna()))
    df["cov_insider"] = take(ins["insider_fresh_buy_21d"].notna().astype(float))
    del ins

    # shareholding accumulation (319 covered symbols)
    acc, shp_first = shp_accumulation(data["shp"], c.index)
    cov_shp = since_first(shp_first, c)
    df["shp_accumulation"] = take(flag(recent(event_frame(acc, c), 20) > 0, cov_shp))
    df["cov_shp"] = take(cov_shp.astype(float))

    # F&O
    fo = data["fo"]
    stock_fo = fo[fo["kind"] == "stock"]
    oi = xf._wide(stock_fo, "fut_oi", c)
    callo, puto = xf._wide(stock_fo, "call_oi", c), xf._wide(stock_fo, "put_oi", c)
    dp5, doi5 = c / c.shift(5) - 1, oi / oi.shift(5) - 1
    valid_fo = oi.notna() & oi.shift(5).notna() & dp5.notna()
    df["fo_long_buildup"] = take(flag((dp5 > 0.03) & (doi5 > 0.10), valid_fo))
    df["fo_short_buildup"] = take(flag((dp5 < -0.03) & (doi5 > 0.10), valid_fo))
    pcr = (puto / callo.where(callo > 0)).replace([np.inf, -np.inf], np.nan)
    rkp = xs_rank(pcr, rankL)
    df["pcr_high"] = take(flag(rkp >= 0.8, rkp.notna()))
    df["cov_fo"] = take(oi.notna().astype(float))

    # MTF (from 2022)
    q = xf._wide(data["mtf"], "qty_financed", c).shift(1)
    mtf_chg = (q / q.shift(20) - 1).replace([np.inf, -np.inf], np.nan)
    nh_w = near_high.reindex(index=dates, columns=members).fillna(False).astype(bool)
    rkm = xs_rank(mtf_chg, rankL & nh_w)
    df["mtf_surge_near_high"] = take(flag(rkm >= 0.9, rkm.notna()))
    df["cov_mtf"] = take(mtf_chg.notna().astype(float))
    log("event flags done")

    # ML A2 scores (walk-forward, out of sample, top 300 only)
    sc = pd.read_parquet(ROOT / "reports" / "ml_labels" / "scores.parquet",
                         columns=["date", "symbol", "score::A2 20d next-open excess rank"])
    a2 = sc.pivot_table(index="date", columns="symbol", values="score::A2 20d next-open excess rank", aggfunc="last")
    a2 = a2.reindex(index=dates, columns=members).where(Td)
    rka2 = a2.rank(axis=1, pct=True)
    df["ml_bottom30"], df["ml_top10"] = take(flag(rka2 <= 0.3, rka2.notna())), take(flag(rka2 >= 0.9, rka2.notna()))
    df["cov_ml"] = take(rka2.notna().astype(float))
    df["ml_a2_pct"] = take(rka2)
    for k in T_KEYS + COVERAGE + ["cov_ml"] + [e.key for e in EXPLORATORY]:
        df[k] = df[k].astype(np.float32)

    # regime inputs (market level)
    nifty = data["nifty"].reindex(c.index).ffill()
    above50 = (c > sma50).where(L)
    breadth = above50.sum(axis=1) / L.sum(axis=1).replace(0, np.nan)
    on_ret = (o / c.shift(1) - 1).where(prev_member).mean(axis=1)
    idx_level = (1 + mkt.fillna(0)).cumprod()
    sig_rel = r.sub(mkt, axis=0).rolling(60, min_periods=45).std()
    C_np, O_np = c.to_numpy(float), o.to_numpy(float)
    I_np, on_np, sig_np = idx_level.to_numpy(float), on_ret.to_numpy(float), sig_rel.to_numpy(float)
    del r, beta, cov_, max20, amihud, volr, on20, surge, delivered, oi, callo, puto, pcr, q, mtf_chg
    log("all flags done")

    # ── 1. conditional probability map ───────────────────────────────────────────
    W = df[df["is_week"]]
    stats_rows, ws_store = [], {}
    for uni, ex_p, rk_p in (("L", "exL", "rkL"), ("T", "exT", "rkT")):
        sub = W[W[f"in{uni}"]]
        for h in HORIZONS:
            for cnd in CONDITIONS + EXPLORATORY:
                if uni == "L" and cnd.universe == "T":
                    continue
                ws = weekly_series(sub, cnd.key, f"{ex_p}_{h}", f"{rk_p}_{h}")
                ws_store[(uni, h, cnd.key)] = ws
                per = {p: summarize(ws, NW_LAGS[h], a, b) for p, (a, b) in PERIODS.items()}
                row = {"universe": uni, "h": h, "key": cnd.key, "label": cnd.label, "family": cnd.family,
                       "expected": cnd.expected, "source": cnd.source,
                       "verdict": verdict(per["pre-2024"], per["P3 2024+"])}
                for p, s in per.items():
                    for k2, v2 in s.items():
                        row[f"{p}|{k2}"] = v2
                stats_rows.append(row)
        log(f"conditional tables done for {uni}")
    cond_df = pd.DataFrame(stats_rows)
    cond_df.to_csv(out_dir / "conditions.csv", index=False)

    # ── 2. credibility (empirical Bayes) ──────────────────────────────────────────
    cred_rows = []
    for uni in ("L", "T"):
        for h in HORIZONS:
            part = cond_df[(cond_df.universe == uni) & (cond_df.h == h)].reset_index(drop=True)
            prereg = ~part["family"].str.startswith("Exploratory").to_numpy()
            th_pre, se_pre = part["pre-2024|d_ex"].to_numpy(float), part["pre-2024|se_ex"].to_numpy(float)
            th_post, se_post = part["P3 2024+|d_ex"].to_numpy(float), part["P3 2024+|se_ex"].to_numpy(float)
            tau_pre = eb_shrink(th_pre[prereg], se_pre[prereg])["tau2"]
            eb_pre = eb_shrink(th_pre, se_pre, tau_pre)
            w1, w2 = 1 / se_pre ** 2, 1 / se_post ** 2
            both = np.isfinite(w1) & np.isfinite(w2)
            th_all = np.where(both, (th_pre * w1 + th_post * w2) / (w1 + w2), np.where(np.isfinite(th_pre), th_pre, th_post))
            se_all = np.where(both, 1 / np.sqrt(w1 + w2), np.where(np.isfinite(se_pre), se_pre, se_post))
            eb_all = eb_shrink(th_all, se_all, eb_shrink(th_all[prereg], se_all[prereg])["tau2"])
            pred_rep = norm.cdf(np.abs(eb_pre["mean"]) / np.sqrt(eb_pre["sd"] ** 2 + se_post ** 2))
            realised = np.sign(th_post) == np.sign(eb_pre["mean"])
            for i, rw in part.iterrows():
                cred_rows.append({
                    "universe": uni, "h": h, "key": rw["key"], "label": rw["label"], "expected": rw["expected"],
                    "pre_effect": th_pre[i], "pre_se": se_pre[i], "post_effect": th_post[i], "post_se": se_post[i],
                    "pre_shrunk": eb_pre["mean"][i], "pred_replicate": pred_rep[i],
                    "replicated": bool(realised[i]) if np.isfinite(th_post[i]) and np.isfinite(eb_pre["mean"][i]) else None,
                    "effect": th_all[i], "effect_se": se_all[i], "shrunk": eb_all["mean"][i], "shrunk_sd": eb_all["sd"][i],
                    "p_sign": eb_all["p_sign"][i], "tau": math.sqrt(eb_all["tau2"]), "verdict": rw["verdict"],
                    "prereg": bool(prereg[i])})
    cred = pd.DataFrame(cred_rows)
    cred.to_csv(out_dir / "credibility.csv", index=False)
    log("credibility done")

    # ── 3. merge: walk-forward models ─────────────────────────────────────────────
    years = [y for y in TEST_YEARS if pd.Timestamp(f"{y}-01-01") > start + pd.DateOffset(years=3)]
    ws_L = {k: ws_store[("L", PRIMARY_H, k)] for k in L_KEYS}
    ws_T = {k: ws_store[("T", PRIMARY_H, k)] for k in T_KEYS}
    final_cut = sessions[len(sessions) - PRIMARY_H - 2]
    predL, logL, finalL = walk_forward(df, "inL", "exL_20", "rkL_20", L_KEYS, COVERAGE, "mom_pctL", ws_L, sessions,
                                       years, log, final_cutoff=final_cut)
    predT, logT, _ = walk_forward(df, "inT", "exT_20", "rkT_20", T_KEYS, COVERAGE + ["cov_ml"], "mom_pctT", ws_T,
                                  sessions, years, log)
    df = pd.concat([df, predL.add_prefix("L_").reindex(df.index), predT.add_prefix("T_").reindex(df.index)], axis=1)
    log("walk-forward done")
    # exploratory (post-hoc): the same merge for short (5) and long (60) holding periods
    explo: dict = {}
    for hx in (5, 60):
        yrs = [y for y in years if pd.Timestamp(f"{y}-01-01") > start + pd.DateOffset(years=3)]
        ws_h = {k: ws_store[("L", hx, k)] for k in L_KEYS}
        ph, _, _ = walk_forward(df, "inL", f"exL_{hx}", f"rkL_{hx}", L_KEYS, COVERAGE, "mom_pctL", ws_h, sessions, yrs,
                                log, h=hx)
        df = pd.concat([df, ph[[c_ for c_ in ph.columns if c_.startswith(("pA_", "pC_", "thrC_", "base_"))]]
                        .add_prefix(f"L{hx}_").reindex(df.index)], axis=1)
        o_ = df[df["inL"] & df["is_week"] & df["date"].dt.year.isin(yrs) & df[f"exL_{hx}"].notna()
                & df[f"L{hx}_pC_win"].notna()]
        res: dict = {"ic": {}, "cal": {}, "buckets": []}
        for model in ("A", "C"):
            s_ = weekly_ic(o_, f"L{hx}_p{model}_win", f"exL_{hx}")
            res["ic"][model] = s_
        d_ = (res["ic"]["C"] - res["ic"]["A"]).dropna()
        for name, since in (("all", SIGNAL_START), ("2024+", P3_START)):
            part_c = res["ic"]["C"][res["ic"]["C"].index >= since]
            part_a = res["ic"]["A"][res["ic"]["A"].index >= since]
            part_d = d_[d_.index >= since]
            mc, sc_, _ = nw_mean_se(part_c, NW_LAGS[hx])
            ma, sa, _ = nw_mean_se(part_a, NW_LAGS[hx])
            md_, sd_, nd = nw_mean_se(part_d, NW_LAGS[hx])
            res[f"ic_{name}"] = {"A": (ma, ma / sa if sa else np.nan), "C": (mc, mc / sc_ if sc_ else np.nan),
                                 "gain": (md_, md_ / sd_ if sd_ else np.nan, nd)}
        for name, selm in (("2016–23", o_["date"] < P3_START), ("2024+", o_["date"] >= P3_START)):
            pp_ = o_[selm]
            res["cal"][name] = calibration(pp_[f"L{hx}_pC_win"].to_numpy(float), (pp_[f"exL_{hx}"] > 0).to_numpy(float),
                                           pp_[f"L{hx}_base_win"].to_numpy(float))
            buy = pp_[f"L{hx}_pC_win"] > pp_[f"L{hx}_thrC_win"]
            avoid = pp_[f"L{hx}_pC_bot"] > pp_[f"L{hx}_thrC_bot"]
            lab_ = np.where(avoid, "AVOID", np.where(buy, "BUY", "NEUTRAL"))
            for bname in ("BUY", "NEUTRAL", "AVOID"):
                g = pp_[lab_ == bname]
                if len(g):
                    res["buckets"].append({"period": name, "bucket": bname, "share": len(g) / len(pp_) * 100,
                                           "win": (g[f"exL_{hx}"] > 0).mean() * 100, "excess": g[f"exL_{hx}"].mean() * 100,
                                           "bottom": (g[f"rkL_{hx}"] <= 0.2).mean() * 100, "raw": g[f"fwd_{hx}"].mean() * 100,
                                           "after_cost": (g[f"fwd_{hx}"] - default_model().round_trip_pct(POSITION_RS) / 100).mean() * 100,
                                           "p_profit": (g[f"fwd_{hx}"] > default_model().round_trip_pct(POSITION_RS) / 100).mean() * 100})
        explo[hx] = res
    log("exploratory 5 / 60-session merges done")

    oos = df[df["inL"] & df["is_week"] & df["date"].dt.year.isin(years) & df["exL_20"].notna() & df["L_pC_win"].notna()]
    ic_rows, ic_series = [], {}
    for model in ("A", "B", "C"):
        for target in ("win", "bot"):
            col = f"L_p{model}_{target}"
            s = weekly_ic(oos, col, "exL_20")
            if target == "bot":
                s = -s                                         # higher P(bottom) should mean lower excess
            ic_series[f"{model}_{target}"] = s
            for name, (a_, b_) in (("2016–23", (SIGNAL_START, P3_START)), ("2024+", (P3_START, pd.Timestamp("2100-01-01"))),
                                   ("all", (SIGNAL_START, pd.Timestamp("2100-01-01")))):
                part = s[(s.index >= a_) & (s.index < b_)]
                m, se, n = nw_mean_se(part, NW_LAGS[PRIMARY_H])
                ic_rows.append({"model": model, "target": target, "period": name, "ic": m, "t": m / se if se else np.nan,
                                "weeks": n})
    paired = {}
    for target in ("win", "bot"):
        dlt = (ic_series[f"C_{target}"] - ic_series[f"A_{target}"]).dropna()
        for name, sel in (("all", dlt), ("2024+", dlt[dlt.index >= P3_START]), ("2016–23", dlt[dlt.index < P3_START])):
            m, se, n = nw_mean_se(sel, NW_LAGS[PRIMARY_H])
            paired[f"{target}|{name}"] = {"gain": m, "t": m / se if se else np.nan, "weeks": n}
    ic_df = pd.DataFrame(ic_rows)
    ic_df.to_csv(out_dir / "merge_ic.csv", index=False)

    cal = {}
    for target, ycol in (("win", (oos["exL_20"] > 0).astype(float)), ("bot", (oos["rkL_20"] <= 0.2).astype(float))):
        for model in ("A", "B", "C"):
            for name, sel in (("2016–23", oos["date"] < P3_START), ("2024+", oos["date"] >= P3_START)):
                part = oos[sel]
                cal[(target, model, name)] = calibration(part[f"L_p{model}_{target}"].to_numpy(float),
                                                         ycol[sel].to_numpy(float), part[f"L_base_{target}"].to_numpy(float))
    rt = default_model().round_trip_pct(POSITION_RS) / 100
    buckets = []
    oos_all = df[df["inL"] & df["is_week"] & df["date"].dt.year.isin(years) & df["L_pC_win"].notna()]
    for model in ("B", "C"):
        bw = oos_all[f"L_p{model}_win"] > oos_all[f"L_thr{model}_win"]     # strict: the scorecard has ties at the base
        bb = oos_all[f"L_p{model}_bot"] > oos_all[f"L_thr{model}_bot"]
        lab = np.where(bb, "AVOID", np.where(bw, "BUY", "NEUTRAL"))
        for name, sel in (("2016–23", oos_all["date"] < P3_START), ("2024+", oos_all["date"] >= P3_START)):
            part = oos_all.loc[sel].copy()
            part["bucket"] = lab[sel.to_numpy()]
            part = part[part["exL_20"].notna()]
            for bname, g in part.groupby("bucket"):
                buckets.append({"model": model, "period": name, "bucket": bname, "share": len(g) / len(part) * 100,
                                "rows": len(g), "win": (g.exL_20 > 0).mean() * 100, "excess": g.exL_20.mean() * 100,
                                "bottom": (g.rkL_20 <= 0.2).mean() * 100, "top": (g.rkL_20 > 0.8).mean() * 100,
                                "raw": g.fwd_20.mean() * 100, "after_cost": (g.fwd_20 - rt).mean() * 100,
                                "p_profit": (g.fwd_20 > rt).mean() * 100})
    bucket_df = pd.DataFrame(buckets)
    bucket_df.to_csv(out_dir / "decision_buckets.csv", index=False)
    log("merge evaluation done")

    # Desk book test (top 300, monthly)
    mo = df[df["inT"] & df["is_month"] & df["date"].dt.year.isin(years)]
    pv = lambda col: mo.pivot(index="date", columns="symbol", values=col)  # noqa: E731
    rets_m = period_returns(P["open"], months[months >= start], 30)
    uni_m = pv("inT").fillna(False).astype(bool)
    rt_book = default_model().round_trip_pct(BOOK_POSITION_RS) / 100
    momp, pcw, a2p = pv("mom_raw"), pv("T_pC_win"), pv("ml_a2_pct")
    veto_c = pcw.rank(axis=1, pct=True) <= 0.3
    veto_a2 = a2p <= 0.3
    books = {
        "Momentum (Desk)": run_book(momp, rets_m.reindex(columns=momp.columns), uni_m, rt_book / 2),
        "Momentum + merged veto (C bottom 30%)": run_book(momp, rets_m.reindex(columns=momp.columns), uni_m, rt_book / 2,
                                                          blocked=veto_c),
        "Momentum + ML A2 veto (bottom 30%)": run_book(momp, rets_m.reindex(columns=momp.columns), uni_m, rt_book / 2,
                                                       blocked=veto_a2),
        "Merged P(win) ranking (C)": run_book(pcw, rets_m.reindex(columns=pcw.columns), uni_m, rt_book / 2),
    }
    book_sum = {k: book_summary(b) for k, b in books.items() if not b.empty}
    pd.concat({k: b for k, b in books.items() if not b.empty}, names=["book"]).to_csv(out_dir / "books.csv")
    log("books done")

    # ── 4. regime (market level) ──────────────────────────────────────────────────
    wk = df[df["inL"] & df["is_week"]]
    basket = wk.groupby("date").agg(ew20=("fwd_20", "mean"), p_profit=("fwd_20", lambda x: (x.dropna() > rt).mean()))
    n_pos = sessions.get_indexer(basket.index)
    nf = nifty.to_numpy(float)
    nifty_fwd = np.where(n_pos + PRIMARY_H < len(nf), nf[np.minimum(n_pos + PRIMARY_H, len(nf) - 1)] / nf[n_pos] - 1, np.nan)
    ma200 = nifty.rolling(200, min_periods=180).mean().to_numpy(float)
    basket["nifty_fwd"] = nifty_fwd
    basket["above200"] = nf[n_pos] > ma200[n_pos]
    basket["breadth"] = breadth.reindex(basket.index).to_numpy(float)
    cuts = basket.loc[basket.index < P2_START, "breadth"].quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
    basket["breadth_q"] = np.searchsorted(cuts, basket["breadth"].to_numpy(float)) + 1
    regime_rows = []
    for name, (a_, b_) in (("2011–23", (SIGNAL_START, P3_START)), ("2024+", (P3_START, pd.Timestamp("2100-01-01")))):
        part = basket[(basket.index >= a_) & (basket.index < b_)].dropna(subset=["ew20"])
        for state, g in list(part.groupby("above200")) + [(f"breadth Q{int(q)}", g) for q, g in part.groupby("breadth_q")]:
            label = state if isinstance(state, str) else ("NIFTY above 200-DMA" if state else "NIFTY below 200-DMA")
            regime_rows.append({"period": name, "state": label, "weeks": len(g), "p_basket_up": (g.ew20 > 0).mean() * 100,
                                "basket_20d": g.ew20.mean() * 100, "p_nifty_up": (g.nifty_fwd > 0).mean() * 100,
                                "nifty_20d": g.nifty_fwd.mean() * 100, "p_stock_profit": g.p_profit.mean() * 100})
    regime_df = pd.DataFrame(regime_rows)
    regime_df.to_csv(out_dir / "regime.csv", index=False)
    log(f"regime done (breadth cut-offs {np.round(cuts, 3).tolist()})")

    # ── 5. label diagnostics ──────────────────────────────────────────────────────
    lab_rows, sig_ic_rows, book_rows, tb_rows = [], [], [], []
    wl = df[df["inL"] & df["is_week"]]
    signals_ = {"momentum (+)": wl["mom_raw"], "20d reversal (−ret20)": -wl["ret20"], "5d reversal (−ret5)": -wl["ret5"],
                "low volatility (−vol60)": -wl["vol60"], "near 52w high (c/high)": wl["hi_ratio"]}
    for h in LABEL_HORIZONS:
        x = wl[["date", "symbol", f"fwd_{h}", f"exL_{h}", f"rkL_{h}", "vol60"]].dropna()
        raw, exh = x[f"fwd_{h}"], x[f"exL_{h}"]
        date_mean = raw.groupby(x["date"]).transform("mean")
        exvol = exh / (x["vol60"] * math.sqrt(h))
        rkw = x.pivot(index="date", columns="symbol", values=f"rkL_{h}")
        pers = []
        for i in range(1, len(rkw)):
            a_, b_ = rkw.iloc[i - 1], rkw.iloc[i]
            both = a_.notna() & b_.notna()
            if both.sum() > 30:
                pers.append(np.corrcoef(a_[both], b_[both])[0, 1])
        lab_rows.append({
            "h": h, "rows": len(x), "market_share_var": float(date_mean.var() / raw.var() * 100),
            "p_raw_gt_cost": float((raw > rt).mean() * 100), "p_raw_gt_0": float((raw > 0).mean() * 100),
            "p_win": float((exh > 0).mean() * 100), "dead_zone": float((exh.abs() < rt).mean() * 100),
            "win_but_loses_money": float(((exh > 0) & (raw < rt)).sum() / max((exh > 0).sum(), 1) * 100),
            "mean_abs_excess": float(exh.abs().mean() * 100), "sd_excess": float(exh.std() * 100),
            "persistence": float(np.nanmean(pers)) if pers else float("nan"),
            "tern_up": float((exh > rt).mean() * 100), "tern_down": float((exh < -rt).mean() * 100),
            "exvol_sd": float(exvol.std())})
        tgt = wl[f"exL_{h}"]
        for sname, s in signals_.items():
            tmp = pd.DataFrame({"date": wl["date"], "s": s, "y": tgt})
            ic = weekly_ic(tmp, "s", "y")
            for name, sel in (("all", ic), ("2024+", ic[ic.index >= P3_START])):
                m, se, n = nw_mean_se(sel, NW_LAGS[h])
                sig_ic_rows.append({"h": h, "signal": sname, "period": name, "ic": m, "t": m / se if se else np.nan})
        if h == PRIMARY_H:
            tmp = wl[["date", "L_pC_win", f"exL_{h}"]].dropna()
            ic = weekly_ic(tmp, "L_pC_win", f"exL_{h}")
            for name, sel in (("all", ic), ("2024+", ic[ic.index >= P3_START])):
                m, se, n = nw_mean_se(sel, NW_LAGS[h])
                sig_ic_rows.append({"h": h, "signal": "merged P(win), model C (OOS)", "period": name, "ic": m,
                                    "t": m / se if se else np.nan})
        # momentum decile book held h sessions (non-overlapping rebalances)
        step = max(1, h // 5)
        rb_dates = weeks[::step]
        prev_top: set[str] = set()
        gross, gross_bot, turn, n_reb = [], [], [], 0
        for d in rb_dates:
            g = wl[wl["date"] == d][["symbol", "mom_pctL", f"exL_{h}"]].dropna()
            if len(g) < 100:
                continue
            top = set(g.loc[g.mom_pctL >= 0.9, "symbol"])
            bot = g.mom_pctL <= 0.1
            gross.append(g.loc[g.mom_pctL >= 0.9, f"exL_{h}"].mean())
            gross_bot.append(g.loc[bot, f"exL_{h}"].mean())
            turn.append(1 - len(top & prev_top) / max(len(top), 1) if prev_top else 1.0)
            prev_top = top
            n_reb += 1
        per_year = 52 / step
        g_, t_ = np.nanmean(gross), np.nanmean(turn)
        book_rows.append({"h": h, "rebalances": n_reb, "top_gross_pa": g_ * per_year * 100,
                          "top_turnover": t_, "top_cost_pa": t_ * rt * per_year * 100,
                          "top_net_pa": (g_ - t_ * rt) * per_year * 100, "bottom_pa": np.nanmean(gross_bot) * per_year * 100})
    # relative triple barrier labels
    wpos = sessions.get_indexer(weeks)
    for h in HORIZONS:
        lab, days = relative_triple_barrier(C_np, O_np, I_np, on_np, sig_np, wpos, h, TB_K)
        lab_df = pd.DataFrame(lab, index=weeks, columns=members).where(Ld.reindex(weeks))
        day_df = pd.DataFrame(days, index=weeks, columns=members).where(Ld.reindex(weeks))
        tb = lab_df.stack().rename("tb").reset_index()
        tb.columns = ["date", "symbol", "tb"]
        x = wl[["date", "symbol", "mom_raw", f"exL_{h}"]].merge(tb, on=["date", "symbol"], how="inner").dropna()
        agree = (np.sign(x[f"exL_{h}"]) == x["tb"])[x["tb"] != 0].mean()
        ic = weekly_ic(x, "mom_raw", "tb")
        m, se, _ = nw_mean_se(ic, NW_LAGS[h])
        ic_ex = weekly_ic(x, "mom_raw", f"exL_{h}")
        m2, se2, _ = nw_mean_se(ic_ex, NW_LAGS[h])
        tb_rows.append({"h": h, "up": (x.tb == 1).mean() * 100, "flat": (x.tb == 0).mean() * 100,
                        "down": (x.tb == -1).mean() * 100, "median_days": float(np.nanmedian(day_df.to_numpy())),
                        "agree_with_excess_sign": agree * 100, "mom_ic_tb": m, "mom_t_tb": m / se if se else np.nan,
                        "mom_ic_excess": m2, "mom_t_excess": m2 / se2 if se2 else np.nan})
    lab_df_out = pd.DataFrame(lab_rows)
    sig_ic_df = pd.DataFrame(sig_ic_rows)
    hbook_df = pd.DataFrame(book_rows)
    tb_df = pd.DataFrame(tb_rows)
    lab_df_out.to_csv(out_dir / "label_diagnostics.csv", index=False)
    sig_ic_df.to_csv(out_dir / "label_signal_ic.csv", index=False)
    hbook_df.to_csv(out_dir / "label_holding_period_book.csv", index=False)
    tb_df.to_csv(out_dir / "label_triple_barrier.csv", index=False)
    log("label diagnostics done")

    # ── 6. today's readings (research only) ───────────────────────────────────────
    snap = df[(df["date"] == last) & (df["inL"] | df["held"])].copy()
    snap_rows = []
    if finalL:
        for target in ("win", "bot"):
            fi = finalL[target]
            keys_used = [k for k in fi["coef"] if k != "mom_pct"]
            X = snap[keys_used].fillna(0.0).copy()
            for cv, val in fi.get("neutral", {}).items():
                if cv in X.columns:
                    X[cv] = val
            X = X.to_numpy(float)
            z = X @ np.array([fi["coef"][k] for k in keys_used]) + fi["coef"]["mom_pct"] * snap["mom_pctL"].fillna(0.5).to_numpy()
            snap[f"p_{target}"] = sigmoid(z + fi["intercept"])
            snap[f"thr_{target}"] = fi["thrC"]
        flags_on = snap[L_KEYS].fillna(0).astype(bool)
        snap["flags"] = [", ".join(k for k in L_KEYS if row[k]) for _, row in flags_on.iterrows()]
        snap["call"] = np.where(snap["p_bot"] > snap["thr_bot"], "AVOID",
                                np.where(snap["p_win"] > snap["thr_win"], "BUY", "NEUTRAL"))
        snap_rows = snap[["symbol", "inL", "held", "p_win", "p_bot", "call", "mom_pctL", "flags"]]
        snap_rows.to_csv(out_dir / "today.csv", index=False)
        coef_rows = []
        for target in ("win", "bot"):
            fi = finalL[target]
            for k, w in fi["coef"].items():
                coef_rows.append({"target": target, "feature": k, "coef": w, "scorecard": fi["scorecard"].get(k, np.nan)})
        pd.DataFrame(coef_rows).to_csv(out_dir / "final_model.csv", index=False)
    log("today's readings done")

    meta = {"generated": f"{datetime.now():%Y-%m-%d %H:%M}", "runtime_s": round(time.time() - t0),
            "symbols": len(members), "signal_dates": len(dates), "rows": len(df), "rows_L": int(df.inL.sum()),
            "rows_T": int(df.inT.sum()), "last_date": str(last.date()), "round_trip_pct": round(rt * 100, 3),
            "book_round_trip_pct": round(rt_book * 100, 3), "test_years": years, "breadth_cuts": cuts.tolist(),
            "quick": bool(args.quick)}
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, "paired_ic": paired, "books": book_sum,
                                                      "walk_forward_L": logL, "walk_forward_T": logT}, indent=1, default=str))
    report = render(meta, cond_df, cred, ic_df, paired, cal, bucket_df, book_sum, regime_df, lab_df_out, sig_ic_df,
                    hbook_df, tb_df, snap_rows, finalL, explo)
    (out_dir / "REPORT.md").write_text(report)
    log("report written")


# ── rendering ───────────────────────────────────────────────────────────────────

def render(meta, cond_df, cred, ic_df, paired, cal, bucket_df, book_sum, regime_df, lab_df, sig_ic_df, hbook_df, tb_df,
           snap, finalL, explo) -> str:
    L_ = ["# Evidence → probability: one frame for every condition, merged and tested", "",
          f"Generated {meta['generated']} by `scripts/evidence_probability_study.py` (plan: `PLAN.md`, written before "
          f"any number). {meta['rows']:,} stock-dates ({meta['rows_L']:,} in the liquid universe L, {meta['rows_T']:,} "
          f"in the Desk's top 300), {meta['symbols']:,} symbols, {meta['signal_dates']} signal dates to {meta['last_date']}. "
          f"Round trip {meta['round_trip_pct']}% at ₹{POSITION_RS:,}. Runtime {meta['runtime_s']} s."
          + (" **QUICK RUN (sample): numbers are not the study.**" if meta["quick"] else ""), "",
          "> **Correction to the first run (same evening):** the merged model's inputs included three coverage flags "
          "chosen with hindsight (stocks whose results / insider / shareholding data were fetched because they are "
          "liquid today). The model rewarded membership itself (+5 points for the shareholding set). They now stay in "
          "training but are set to their average when predicting. The first run's outputs are kept in "
          "`first_run_coverage_leak/`. Rows marked *Exploratory (post-hoc)* were added after the first run and are not "
          "part of the merge.", ""]

    def cred_of(uni, h, key):
        r = cred[(cred.universe == uni) & (cred.h == h) & (cred.key == key)]
        return r.iloc[0] if len(r) else None

    for uni, title in (("L", "liquid universe L"), ("T", "Desk top 300")):
        hs = HORIZONS if uni == "L" else (PRIMARY_H,)
        for h in hs:
            part = cond_df[(cond_df.universe == uni) & (cond_df.h == h)]
            L_ += [f"## Conditional probabilities: {title}, {h} sessions", "",
                   "P(beat) = share of flagged stocks that beat the universe's average over the next "
                   f"{h} sessions (entry next open), vs all covered stocks the same weeks. Lift and mean excess: weekly "
                   "difference, flagged minus covered (Newey-West t). P(bottom 20%) = share that landed in the worst fifth "
                   "(20% by construction for the covered set). Credibility: empirical-Bayes P(the effect has this sign).", ""]
            rows = []
            for _, rw in part.iterrows():
                cr = cred_of(uni, h, rw["key"])
                rows.append([rw["family"], rw["label"], {1: "+", -1: "−", 0: "0"}[rw["expected"]],
                             f"{n_(rw.get('pre-2024|events'))} / {n_(rw.get('P3 2024+|events'))}",
                             f"{f(rw.get('all|winA'), 1)} vs {f(rw.get('all|winE'), 1)}",
                             f"{f(rw.get('pre-2024|d_win'), 1, sign=True)} / {f(rw.get('P3 2024+|d_win'), 1, sign=True)}",
                             f"{f(rw.get('pre-2024|d_ex'), 2, sign=True)} ({f(rw.get('pre-2024|t_ex'), 1)}) / "
                             f"{f(rw.get('P3 2024+|d_ex'), 2, sign=True)} ({f(rw.get('P3 2024+|t_ex'), 1)})",
                             f"{f(rw.get('all|botA'), 1)} vs {f(rw.get('all|botE'), 1)}",
                             rw["verdict"], f(cr["p_sign"] * 100, 0) + "%" if cr is not None and np.isfinite(cr["p_sign"]) else "—"])
            L_ += [md(rows, ["Family", "Condition", "Exp.", "Events pre / 2024+", "P(beat) % flagged vs base",
                             "Lift pp pre / 2024+", "Mean excess % (t) pre / 2024+", "P(bottom 20%) flagged vs base",
                             "Verdict", "Credibility"]), ""]

    L_ += ["## Credibility as a forecast", "",
           "Shrinkage fitted on pre-2024 data predicts whether each effect keeps its sign in 2024+; this is how often it did.", ""]
    rows = []
    for (uni, h), g in cred.groupby(["universe", "h"]):
        g = g[g["replicated"].notna() & g["prereg"]]
        if g.empty:
            continue
        rep = g["replicated"].astype(float)
        hi_ = g["pred_replicate"] >= 0.8
        rows.append([uni, h, len(g), f(g["pred_replicate"].mean() * 100, 0) + "%", f(rep.mean() * 100, 0) + "%",
                     f"{int(hi_.sum())}: {f(rep[hi_].mean() * 100, 0)}%" if hi_.any() else "—",
                     f(g["tau"].iloc[0], 3)])
    L_ += [md(rows, ["Universe", "h", "Conditions", "Predicted replication (mean)", "Actual", "Predicted ≥ 80%: actual",
                     "τ (spread of true effects, %)"]), ""]

    L_ += ["## Merge: walk-forward models (L, 20 sessions)", "",
           "A = momentum percentile only · B = scorecard (shrunk naive Bayes) · C = L2 logistic on every flag + coverage "
           "flags + momentum. Rank IC of each model's P(win) (and −P(bottom)) against the 20-session excess, weekly.", ""]
    rows = []
    for (model, target), g in ic_df.groupby(["model", "target"]):
        cells = {r_["period"]: f"{f(r_['ic'], 4)} ({f(r_['t'], 1)})" for _, r_ in g.iterrows()}
        rows.append([model, target, cells.get("2016–23", "—"), cells.get("2024+", "—"), cells.get("all", "—")])
    L_ += [md(rows, ["Model", "Target", "IC 2016–23 (t)", "IC 2024+ (t)", "IC all (t)"]), ""]
    rows = [[k.split("|")[0], k.split("|")[1], f(v["gain"], 4), f(v["t"], 2), v["weeks"]] for k, v in paired.items()]
    L_ += ["Paired weekly IC gain, C minus A:", "", md(rows, ["Target", "Period", "IC gain", "t (NW)", "Weeks"]), ""]

    L_ += ["### Calibration (does a predicted 55% come true 55% of the time?)", ""]
    rows = []
    for (target, model, name), cdict in cal.items():
        if cdict:
            rows.append([target, model, name, f"{cdict['rows']:,}", f(cdict["mean_p"] * 100, 1), f(cdict["mean_y"] * 100, 1),
                         f(cdict["slope"], 2), f(cdict["skill"] * 100, 2, sign=True) + "%"])
    L_ += [md(rows, ["Target", "Model", "Period", "Rows", "Mean predicted %", "Realised %", "Slope", "Brier skill"]), ""]
    cc = cal.get(("win", "C", "2024+"))
    if cc:
        t = cc["table"]
        L_ += ["Model C, P(win), 2024+, by predicted decile:", "",
               md([[int(i) + 1, f(r_.predicted * 100, 1), f(r_.realised * 100, 1), f"{int(r_.rows):,}"] for i, r_ in t.iterrows()],
                  ["Decile", "Predicted %", "Realised %", "Rows"]), ""]
    cb = cal.get(("bot", "C", "2024+"))
    if cb:
        t = cb["table"]
        L_ += ["Model C, P(bottom 20%), 2024+, by predicted decile:", "",
               md([[int(i) + 1, f(r_.predicted * 100, 1), f(r_.realised * 100, 1), f"{int(r_.rows):,}"] for i, r_ in t.iterrows()],
                  ["Decile", "Predicted %", "Realised %", "Rows"]), ""]

    L_ += ["### Decision buckets (out of sample)", "",
           "BUY = P(win) in the top 10% of that year's training predictions and not AVOID; AVOID = P(bottom) in the top "
           "20%. Excess vs the liquid universe over 20 sessions; raw = the stock's own return; after cost = raw − round trip.", ""]
    rows = [[r_.model, r_.period, r_.bucket, f(r_.share, 1), f"{int(r_.rows):,}", f(r_.win, 1), f(r_.excess, 2, sign=True),
             f(r_.bottom, 1), f(r_.top, 1), f(r_.raw, 2, sign=True), f(r_.after_cost, 2, sign=True), f(r_.p_profit, 1)]
            for r_ in bucket_df.itertuples()]
    L_ += [md(rows, ["Model", "Period", "Bucket", "Share %", "Rows", "P(beat) %", "Excess %", "Bottom 20% %", "Top 20% %",
                     "Raw %", "After cost %", "P(profit after cost) %"]), ""]

    L_ += ["### Desk book test (top 300, monthly, net of ICICI costs at ₹25,000 a position, vs the universe)", ""]
    rows = [[k, f(v.get("net_2016–23"), 2, sign=True), f(v.get("net_2024+"), 2, sign=True), f(v.get("net_all"), 2, sign=True),
             f(v.get("ir_all"), 2), f(v.get("turnover"), 3), f(v.get("cost_pa"), 2), v.get("months")] for k, v in book_sum.items()]
    L_ += [md(rows, ["Book", "Net excess %/yr 2016–23", "2024+", "All", "IR", "Turnover", "Costs %/yr", "Months"]), ""]

    L_ += ["## Exploratory (post-hoc): the same merge for short (5) and long (60) holding periods", "",
           "Not pre-registered; added after the first run because the plan only merged at 20 sessions. Same models, "
           "same rules, training purged h + 1 sessions before each test year.", ""]
    for hx, res in explo.items():
        rows = []
        for name in ("all", "2024+"):
            r_ = res.get(f"ic_{name}")
            if r_:
                rows.append([name, f"{f(r_['A'][0], 4)} ({f(r_['A'][1], 1)})", f"{f(r_['C'][0], 4)} ({f(r_['C'][1], 1)})",
                             f"{f(r_['gain'][0], 4)} ({f(r_['gain'][1], 1)})"])
        L_ += [f"**{hx} sessions**: rank IC of P(win) vs the {hx}-session excess", "",
               md(rows, ["Period", "A momentum (t)", "C merged (t)", "C − A (t)"]), ""]
        rows = [[k, f(v.get("mean_p", np.nan) * 100, 1), f(v.get("mean_y", np.nan) * 100, 1), f(v.get("slope"), 2),
                 f(v.get("skill", np.nan) * 100, 2, sign=True) + "%"] for k, v in res["cal"].items() if v]
        L_ += [md(rows, ["Period", "Mean predicted %", "Realised %", "Calibration slope", "Brier skill"]), ""]
        rows = [[b["period"], b["bucket"], f(b["share"], 1), f(b["win"], 1), f(b["excess"], 2, sign=True), f(b["bottom"], 1),
                 f(b["raw"], 2, sign=True), f(b["after_cost"], 2, sign=True), f(b["p_profit"], 1)] for b in res["buckets"]]
        L_ += [md(rows, ["Period", "Bucket", "Share %", "P(beat) %", "Excess %", "Bottom 20% %", "Raw %", "After cost %",
                         "P(profit after cost) %"]), ""]

    L_ += ["## Market regime (is it a good time to own stocks at all?)", "",
           "Basket = equal-weight liquid universe, next open → 20 sessions. Single stock = share of stocks whose own "
           "20-session return beat the round-trip cost.", ""]
    rows = [[r_.period, r_.state, r_.weeks, f(r_.p_basket_up, 1), f(r_.basket_20d, 2, sign=True), f(r_.p_nifty_up, 1),
             f(r_.nifty_20d, 2, sign=True), f(r_.p_stock_profit, 1)] for r_ in regime_df.itertuples()]
    L_ += [md(rows, ["Period", "State", "Weeks", "P(basket up) %", "Basket 20d %", "P(NIFTY up) %", "NIFTY 20d %",
                     "P(stock profit after cost) %"]), ""]

    L_ += ["## Labels: what a model should learn from", "", "### The label itself, by horizon (liquid universe, weekly, 2011+)", ""]
    rows = [[int(r_.h), f"{int(r_.rows):,}", f(r_.market_share_var, 1), f(r_.p_raw_gt_0, 1), f(r_.p_raw_gt_cost, 1),
             f(r_.p_win, 1), f(r_.dead_zone, 1), f(r_.win_but_loses_money, 1), f(r_.mean_abs_excess, 2), f(r_.persistence, 2),
             f"{f(r_.tern_up, 0)} / {f(100 - r_.tern_up - r_.tern_down, 0)} / {f(r_.tern_down, 0)}"] for r_ in lab_df.itertuples()]
    L_ += [md(rows, ["h", "Rows", "Market share of variance %", "P(raw > 0) %", "P(raw > cost) %", "P(beat universe) %",
                     "Inside ±cost dead zone %", "'Beat' labels that lose money %", "Mean |excess| %",
                     "Week-to-week persistence", "Ternary +/0/− %"]), ""]
    L_ += ["### Which horizon carries information (rank IC of fixed signals vs the excess label; t)", ""]
    piv = sig_ic_df[sig_ic_df.period == "all"].pivot(index="signal", columns="h", values="ic")
    pt = sig_ic_df[sig_ic_df.period == "all"].pivot(index="signal", columns="h", values="t")
    rows = [[s] + [f"{f(piv.loc[s, h], 4)} ({f(pt.loc[s, h], 1)})" if h in piv.columns and np.isfinite(piv.loc[s, h]) else "—"
                   for h in LABEL_HORIZONS] for s in piv.index]
    L_ += [md(rows, ["Signal"] + [f"h={h}" for h in LABEL_HORIZONS]), ""]
    L_ += ["### Can the horizon pay its costs? Momentum top decile held h sessions, non-overlapping rebalances", ""]
    rows = [[int(r_.h), r_.rebalances, f(r_.top_gross_pa, 1, sign=True), f(r_.top_turnover, 2), f(r_.top_cost_pa, 1),
             f(r_.top_net_pa, 1, sign=True), f(r_.bottom_pa, 1, sign=True)] for r_ in hbook_df.itertuples()]
    L_ += [md(rows, ["h", "Rebalances", "Top-decile excess %/yr (gross)", "Turnover", "Costs %/yr", "Net %/yr",
                     "Bottom decile %/yr"]), ""]
    L_ += ["### Relative triple-barrier labels (±1·σ√h on the stock-vs-universe line)", ""]
    rows = [[int(r_.h), f(r_.up, 1), f(r_.flat, 1), f(r_.down, 1), f(r_.median_days, 0), f(r_.agree_with_excess_sign, 1),
             f"{f(r_.mom_ic_tb, 4)} ({f(r_.mom_t_tb, 1)})", f"{f(r_.mom_ic_excess, 4)} ({f(r_.mom_t_excess, 1)})"]
            for r_ in tb_df.itertuples()]
    L_ += [md(rows, ["h", "Up %", "Neither %", "Down %", "Median days to touch", "Agrees with excess sign %",
                     "Momentum IC vs barrier label (t)", "Momentum IC vs plain excess (t)"]), ""]

    if isinstance(snap, pd.DataFrame) and len(snap):
        L_ += ["## Today's readings (research only: not a trading signal, nothing changes in the Desk)", "",
               f"Final model C fitted on everything labelled up to {meta['last_date']} minus 21 sessions. "
               "BUY / AVOID thresholds = top 10% / top 20% of its training predictions.", ""]
        top = snap[snap["inL"] & (snap["call"] == "BUY")].sort_values("p_win", ascending=False).head(25)
        avoid = snap[snap["inL"] & (snap["call"] == "AVOID")].sort_values("p_bot", ascending=False).head(25)
        held = snap[snap["held"]]
        for title, part in (("Highest P(beat), not AVOID", top), ("Highest P(bottom 20%)", avoid), ("Your holdings", held)):
            rows = [[r_.symbol, f(r_.p_win * 100, 1), f(r_.p_bot * 100, 1), r_.call, f(r_.mom_pctL * 100, 0) if
                     np.isfinite(r_.mom_pctL) else "—", r_.flags or "—", "" if r_.inL else "outside L"] for r_ in part.itertuples()]
            L_ += [f"**{title}**", "", md(rows, ["Symbol", "P(beat) %", "P(bottom 20%) %", "Call", "Momentum pct", "Flags on", ""]), ""]
    return "\n".join(L_) + "\n"


if __name__ == "__main__":
    main()
