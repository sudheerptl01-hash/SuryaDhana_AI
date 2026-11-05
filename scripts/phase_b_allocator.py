"""
Phase B (docs/PRODUCT_STRATEGY.md §4 R1–R3): can a MONTHLY, low-turnover equity
allocator make money after REAL costs and tax, within a −15% drawdown budget?

Everything below is fixed before looking at results (pre-registered):

Universe (each month, point in time, from NSE full bhavcopy: survivorship-free)
  EQ series, adjusted close ≥ ₹20, 250+ sessions of history, then the 300 most
  liquid names by 126-day median turnover (a Nifty-200-like large/mid proxy).
Signals (computed at the last close of the month; trades at next session's open)
  mom_nse : NSE Momentum-30 style: mean of z(6m return / σ) and z(12m return / σ),
            σ = 1-year daily return volatility
  mom_121 : 12-month return skipping the latest month (academic 12-1)
  lowvol  : lowest 1-year daily volatility
Portfolio
  top N (10 or 20) equal weight; BUFFER: a holding is kept while its rank ≤ 1.5·N;
  continuing positions are not resized (turnover control); new names are bought
  with cash at 1/N of equity. Whole shares only (unaffordable names are skipped).
Overlays
  none | nifty200 (all cash when NIFTY < 200DMA at signal) |
  nifty200_vt (nifty200 + exposure = min(1, 15% / 60-day realised book vol))
Cash earns 6.0%/yr (liquid fund). Costs: shared/trading_costs.py (default ICICI
MoneySaver). Tax: STCG 20% / LTCG 12.5% above ₹1.25L, 4% cess, FIFO lots,
settled at each financial-year end.
Evaluation
  discovery = before 2024-07-01, holdout = after. Pass = beats NIFTY (price index)
  after costs+tax in BOTH periods, Deflated Sharpe > 0.95 across all variants
  tested, full-sample max drawdown ≥ −15%.

Extended out-of-sample run (pre-registered 2026-09-27, grid UNCHANGED): with the
panel loaded from 2010, the backtest starts ~Jan 2011 and "untouched" = start → Oct 2020,
a decade no research here had seen. It passes if variants beat NIFTY there with
Deflated Sharpe > 0.95 (24 trials), and the liquid-fund mixes, at the equity shares
FIXED from the 2020–24 run (FIXED_MIX), stay within −15%.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/phase_b_allocator.py \
        [--panel-start 2010-01-01] [--out reports/phase_b_extended]
    (original run: --panel-start 2019-10-01 --out reports/phase_b)
Outputs: results.csv, equity_curves.csv, yearly.csv, mixes.csv, summary.json
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from shared.nse_panel import load_panel  # noqa: E402
from shared.trading_costs import CostModel, TaxRules, capital_gains_tax, default_model  # noqa: E402

HOLDOUT_START = pd.Timestamp("2024-07-01")
ORIGINAL_START = pd.Timestamp("2020-11-01")        # first run's backtest start; before it = untouched
# equity share of each mix, fixed from the 2020–24 discovery drawdown in the first run
FIXED_MIX = {"mom_nse|N20|nifty200_vt": 0.66, "mom_121|N20|none": 0.40,
             "mom_nse|N20|none": 0.50, "mom_121|N20|nifty200_vt": 0.45}
CASH_YIELD = 0.06
MAX_DD_BUDGET = -0.15
VOL_TARGET = 0.15

log = logging.getLogger("phase_b")


@dataclass(frozen=True)
class Variant:
    signal: str          # mom_nse | mom_121 | lowvol | blend (mom_nse + lowvol)
    n: int
    overlay: str         # none | nifty200 | nifty200_vt
    sector_cap: float | None = None   # off in the pre-registered grid
    avoid_bulk_buy_days: int = 0      # candidate filter (scripts/desk_filter_backtest.py)

    @property
    def name(self) -> str:
        sc = f"|sc{int(self.sector_cap * 100)}" if self.sector_cap else ""
        bulk = f"|nobulk{self.avoid_bulk_buy_days}" if self.avoid_bulk_buy_days else ""
        return f"{self.signal}|N{self.n}|{self.overlay}{sc}{bulk}"

    def config(self) -> StrategyConfig:
        return StrategyConfig(signal=self.signal, n=self.n, overlay=self.overlay, vol_target=VOL_TARGET,
                              sector_cap=self.sector_cap, avoid_bulk_buy_days=self.avoid_bulk_buy_days)


# ── data ────────────────────────────────────────────────────────────────────────

def load_data(panel_start: str = "2010-01-01", with_bulk_events: bool = False) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    db = ROOT / "data" / "market.duckdb"
    tmp = Path(tempfile.mkdtemp(prefix="phaseb_"))
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        panel = load_panel(con, start=panel_start)
        nifty = con.execute("SELECT date, close FROM market_index_daily WHERE symbol='NIFTY50' ORDER BY date").df()
        if with_bulk_events:
            from shared.deal_filters import non_institutional_buy_events
            deals = con.execute("SELECT date, symbol, client_name, side, qty FROM nse_deals WHERE kind = 'bulk'").df()
            deals["date"] = pd.to_datetime(deals["date"])
            panel["bulk_buy_events"] = non_institutional_buy_events(deals)
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    nifty = nifty.assign(date=pd.to_datetime(nifty["date"])).set_index("date")["close"]
    return panel, nifty


# ── strategy logic lives in shared/momentum.py (same code as the live Decision Desk) ──
from shared.momentum import (  # noqa: E402
    StrategyConfig, compute_targets, eligible, equity_symbols, etf_symbols, is_etf, select, signals,
)


# ── portfolio simulator ─────────────────────────────────────────────────────────

@dataclass
class Lot:
    units: float
    cost_per_unit: float
    day: pd.Timestamp


@dataclass
class Book:
    cash: float
    units: dict[str, float] = field(default_factory=dict)
    lots: dict[str, list[Lot]] = field(default_factory=dict)
    realized: dict[str, dict[str, float]] = field(default_factory=dict)   # FY → {"st": , "lt": }
    costs: float = 0.0
    taxes: float = 0.0
    trades: int = 0
    skipped_unaffordable: int = 0


def fy_of(d: pd.Timestamp) -> str:
    return f"FY{d.year + 1 if d.month >= 4 else d.year}"


def sell(book: Book, sym: str, units: float, px: float, day: pd.Timestamp, cm: CostModel) -> None:
    value = units * px
    cost = cm.leg(value, "sell").total
    book.cash += value - cost
    book.costs += cost
    book.trades += 1
    left = units
    fy = book.realized.setdefault(fy_of(day), {"st": 0.0, "lt": 0.0})
    while left > 1e-12 and book.lots.get(sym):
        lot = book.lots[sym][0]
        take = min(lot.units, left)
        gain = take * (px - lot.cost_per_unit) - cost * (take / units)
        fy["lt" if (day - lot.day).days > 365 else "st"] += gain
        lot.units -= take
        left -= take
        if lot.units <= 1e-12:
            book.lots[sym].pop(0)
    book.units[sym] = book.units.get(sym, 0.0) - units
    if book.units[sym] <= 1e-9:
        book.units.pop(sym, None)
        book.lots.pop(sym, None)


def buy(book: Book, sym: str, target_value: float, adj_px: float, raw_px: float, day: pd.Timestamp,
        cm: CostModel) -> None:
    qty = math.floor(target_value / raw_px) if raw_px > 0 else 0
    if qty <= 0:
        book.skipped_unaffordable += 1
        return
    value = qty * raw_px
    cost = cm.leg(value, "buy").total
    if value + cost > book.cash:
        qty = math.floor((book.cash - cost) / raw_px)
        if qty <= 0:
            return
        value = qty * raw_px
        cost = cm.leg(value, "buy").total
    units = value / adj_px                                    # units of adjusted price
    book.cash -= value + cost
    book.costs += cost
    book.trades += 1
    book.units[sym] = book.units.get(sym, 0.0) + units
    book.lots.setdefault(sym, []).append(Lot(units, (value + cost) / units, day))


def settle_tax(book: Book, fy: str, rules: TaxRules = TaxRules()) -> None:
    g = book.realized.get(fy)
    if not g:
        return
    st, lt = g["st"], g["lt"]
    if st < 0:                        # short-term loss offsets STCG then LTCG
        lt += st
        st = 0.0
    # long-term loss only offsets LTCG (already netted in lt); carry-forward ignored (conservative)
    tax = capital_gains_tax(max(st, 0), 1, 0, rules)[0] + capital_gains_tax(max(lt, 0), 400, rules.ltcg_exemption,
                                                                             rules)[0]
    book.cash -= tax
    book.taxes += tax


def simulate(v: Variant, panel: dict, sig: dict, nifty: pd.Series, capital: float, cm: CostModel,
             start: pd.Timestamp, end: pd.Timestamp | None = None,
             decisions: list | None = None) -> tuple[pd.Series, Book]:
    idx = panel["close"].index
    cfg = v.config()
    O, C, RAW = panel["open"], panel["close"], panel["raw_close"]
    raw_open = panel["open"] * (panel["raw_close"] / panel["close"])      # undo back-adjustment
    months = pd.Series(idx, index=idx).groupby(idx.to_period("M")).first()
    reb_days = set(months[(months >= start) & ((months <= end) if end is not None else True)])
    book = Book(cash=capital)
    eq = {}
    last_px: dict[str, float] = {}
    missing: dict[str, int] = {}
    daily_cash = (1 + CASH_YIELD) ** (1 / 252) - 1
    prev_fy = None
    for i, day in enumerate(idx):
        if day < start or (end is not None and day > end):
            continue
        fy = fy_of(day)
        if prev_fy and fy != prev_fy:
            settle_tax(book, prev_fy)
        prev_fy = fy
        book.cash *= 1 + daily_cash
        # delisted / suspended holdings: exit at last price after 20 sessions without a print
        for sym in list(book.units):
            px = C.iat[i, C.columns.get_loc(sym)]
            if np.isfinite(px):
                last_px[sym], missing[sym] = px, 0
            else:
                missing[sym] = missing.get(sym, 0) + 1
                if missing[sym] > 20:
                    sell(book, sym, book.units[sym], last_px.get(sym, 0.0), day, cm)
        if day in reb_days and i > 0:
            s = i - 1
            decision = compute_targets(cfg, panel, sig, nifty, s, set(book.units),
                                       pd.Series(eq) if cfg.overlay == "nifty200_vt" else None)
            if decisions is not None:
                decisions.append(decision)
            target = decision.targets
            opens = O.iloc[i]
            for sym in list(book.units):
                if sym not in target:
                    px = opens.get(sym)
                    sell(book, sym, book.units[sym], px if np.isfinite(px) else last_px.get(sym, 0.0), day, cm)
            equity = book.cash + sum(u * (opens.get(s_) if np.isfinite(opens.get(s_, np.nan)) else last_px.get(s_, 0))
                                     for s_, u in book.units.items())
            expo = decision.exposure
            per_name = equity * expo / max(v.n, 1)
            for sym in target:
                if sym in book.units:
                    continue
                apx, rpx = opens.get(sym), raw_open.iat[i, raw_open.columns.get_loc(sym)]
                if np.isfinite(apx) and np.isfinite(rpx) and apx > 0:
                    buy(book, sym, min(per_name, book.cash), apx, rpx, day, cm)
        # mark every holding at today's close, including names bought at today's open
        closes = C.iloc[i]
        for s_ in book.units:
            px = closes.get(s_)
            if px is not None and np.isfinite(px):
                last_px[s_] = px
        mtm = sum(u * last_px.get(s_, 0.0) for s_, u in book.units.items())
        eq[day] = book.cash + mtm
    if prev_fy:
        settle_tax(book, prev_fy)
        eq[max(eq)] = book.cash + sum(u * last_px.get(s_, 0.0) for s_, u in book.units.items())
    return pd.Series(eq), book


# ── metrics ─────────────────────────────────────────────────────────────────────

def metrics(eq: pd.Series, rf: float = CASH_YIELD) -> dict:
    eq = eq.dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    r = eq.pct_change().dropna()
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    vol = r.std() * math.sqrt(252)
    sharpe = ((r.mean() - ((1 + rf) ** (1 / 252) - 1)) / r.std() * math.sqrt(252)) if r.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": cagr, "vol": vol, "sharpe": sharpe, "max_dd": dd, "calmar": cagr / abs(dd) if dd < 0 else np.nan,
            "years": yrs, "skew": r.skew(), "kurt": r.kurt(), "n_obs": len(r)}


def deflated_sharpe(sr_annual: float, n_obs: int, skew: float, kurt: float, sr_trials: list[float]) -> float:
    """Bailey & López de Prado: P(true SR > 0) after selecting the best of len(sr_trials)."""
    from math import erf, sqrt
    n_trials = max(len(sr_trials), 1)
    sr = sr_annual / math.sqrt(252)
    var_trials = np.nanvar(np.array(sr_trials) / math.sqrt(252)) if n_trials > 1 else 0.0
    emc = 0.5772156649
    from scipy.stats import norm
    sr0 = math.sqrt(var_trials) * ((1 - emc) * norm.ppf(1 - 1 / n_trials) + emc * norm.ppf(1 - 1 / (n_trials * math.e))) \
        if n_trials > 1 else 0.0
    denom = math.sqrt(max(1 - skew * sr + (kurt + 2) / 4 * sr ** 2, 1e-12))   # kurt = excess kurtosis
    return float(norm.cdf((sr - sr0) * math.sqrt(n_obs - 1) / denom))


# ── driver ──────────────────────────────────────────────────────────────────────

VARIANTS = [Variant(sg, n, ov) for sg, n, ov in itertools.product(
    ("mom_nse", "mom_121", "lowvol", "blend"), (10, 20), ("none", "nifty200", "nifty200_vt"))]
CAPITALS = (100_000, 500_000, 1_000_000)


def _seg(x: pd.Series, a: pd.Timestamp, b: pd.Timestamp | None) -> pd.Series:
    return x[(x.index >= a) & ((x.index < b) if b is not None else True)]


def mix_curve(curve: pd.Series, share: float) -> pd.Series:
    """Strategy share + liquid fund, rebalanced daily (≈ monthly rebalancing)."""
    r = curve.pct_change().fillna(0)
    return (1 + share * r + (1 - share) * ((1 + CASH_YIELD) ** (1 / 252) - 1)).cumprod()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel-start", default="2010-01-01")
    ap.add_argument("--out", default=str(ROOT / "reports" / "phase_b_extended"))
    args = ap.parse_args()
    out_dir = Path(args.out)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    panel, nifty = load_data(args.panel_start)
    sig = signals(panel)
    idx = panel["close"].index
    first = idx[sig["hist"].max(axis=1) >= 260][0] if (sig["hist"].max(axis=1) >= 260).any() else idx[0]
    start = pd.Timestamp(first) + pd.offsets.MonthBegin(1)
    cm = default_model()
    periods = {"full": (start, None)}
    if start < ORIGINAL_START - pd.Timedelta(days=365):
        periods["untouched"] = (start, ORIGINAL_START)
        periods["discovery"] = (ORIGINAL_START, HOLDOUT_START)
    else:
        periods["discovery"] = (start, HOLDOUT_START)
    periods["holdout"] = (HOLDOUT_START, None)
    log.info("panel %s × %s, backtest from %s, periods %s, cost profile %s (%.0fs)", *panel["close"].shape,
             start.date(), list(periods), cm.broker.name, time.time() - t0)

    rows, curves = [], {}
    nifty_seg = nifty[nifty.index >= start]
    for cap in CAPITALS:
        for v in VARIANTS:
            eq, book = simulate(v, panel, sig, nifty, cap, cm, start)
            curves[f"{v.name}|{cap}"] = eq
            rec = {"variant": v.name, "signal": v.signal, "n": v.n, "overlay": v.overlay, "capital": cap,
                   "costs_inr": round(book.costs), "taxes_inr": round(book.taxes), "trades": book.trades,
                   "skipped_unaffordable": book.skipped_unaffordable}
            for per, (a, b) in periods.items():
                m, mn = metrics(_seg(eq, a, b)), metrics(_seg(nifty_seg, a, b))
                rec.update({f"{per}_{k}": m[k] for k in ("cagr", "vol", "sharpe", "max_dd", "calmar")})
                rec[f"{per}_nifty_cagr"] = mn["cagr"]
                rec[f"{per}_excess_cagr"] = m["cagr"] - mn["cagr"]
                rec.update({f"{per}_skew": m["skew"], f"{per}_kurt": m["kurt"], f"{per}_nobs": m["n_obs"]})
            rows.append(rec)
        log.info("capital %s done (%.0fs)", cap, time.time() - t0)

    res = pd.DataFrame(rows)
    for per in ("full", "untouched"):
        if f"{per}_sharpe" not in res:
            continue
        for cap, g in res.groupby("capital"):
            trials = g[f"{per}_sharpe"].tolist()
            res.loc[g.index, f"{per}_deflated_sharpe"] = [
                deflated_sharpe(getattr(r, f"{per}_sharpe"), int(getattr(r, f"{per}_nobs")),
                                getattr(r, f"{per}_skew"), getattr(r, f"{per}_kurt"), trials)
                for r in g.itertuples()]
    res["passes_original_rule"] = ((res["discovery_excess_cagr"] > 0) & (res["holdout_excess_cagr"] > 0)
                                   & (res["full_deflated_sharpe"] > 0.95) & (res["full_max_dd"] >= MAX_DD_BUDGET))
    if "untouched_excess_cagr" in res:
        res["passes_untouched"] = (res["untouched_excess_cagr"] > 0) & (res["untouched_deflated_sharpe"] > 0.95)
    res = res.drop(columns=[c for c in res.columns if c.endswith(("_skew", "_kurt", "_nobs"))])
    res.to_csv(out_dir / "results.csv", index=False)
    curves_df = pd.DataFrame(curves)
    curves_df.to_csv(out_dir / "equity_curves.csv")

    # calendar-year returns at ₹5L vs NIFTY (crash years visible)
    yr = curves_df[[c for c in curves_df if c.endswith("|500000")]].resample("YE").last()
    yr = pd.concat([curves_df[[c for c in curves_df if c.endswith("|500000")]].iloc[[0]], yr]).pct_change().iloc[1:]
    ny = nifty_seg.resample("YE").last()
    ny = pd.concat([nifty_seg.iloc[[0]], ny]).pct_change().iloc[1:]
    yr["NIFTY50"] = ny.to_numpy()[: len(yr)]
    yr.index = yr.index.year
    yr.round(4).to_csv(out_dir / "yearly.csv")

    mixes = []
    for name, share in FIXED_MIX.items():
        for cap in CAPITALS:
            c = curves_df[f"{name}|{cap}"].dropna()
            for per, (a, b) in periods.items():
                m = metrics(mix_curve(_seg(c, a, b), share))
                mn = metrics(_seg(nifty_seg, a, b))
                mixes.append({"strategy": name, "equity_share": share, "capital": cap, "period": per,
                              "cagr": m["cagr"], "max_dd": m["max_dd"], "nifty_cagr": mn["cagr"],
                              "nifty_max_dd": mn["max_dd"], "within_dd_budget": m["max_dd"] >= MAX_DD_BUDGET})
    mixes = pd.DataFrame(mixes)
    mixes.to_csv(out_dir / "mixes.csv", index=False)

    nm = {per: metrics(_seg(nifty_seg, a, b)) for per, (a, b) in periods.items()}
    summary = {"start": str(start.date()), "end": str(idx[-1].date()), "cost_profile": cm.broker.name,
               "periods": {k: [str(a.date()), str(b.date()) if b is not None else None] for k, (a, b) in periods.items()},
               "variants": len(VARIANTS), "capitals": CAPITALS, "nifty": nm,
               "passing_original_rule": res[res["passes_original_rule"]][["variant", "capital"]].to_dict("records"),
               "passing_untouched": (res[res["passes_untouched"]][["variant", "capital"]].to_dict("records")
                                     if "passes_untouched" in res else None)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("done (%.0fs) → %s", time.time() - t0, out_dir)


if __name__ == "__main__":
    main()
