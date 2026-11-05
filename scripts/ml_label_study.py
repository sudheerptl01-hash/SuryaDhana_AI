#!/usr/bin/env python
"""
ML labels and features: an audit of the v2 production labels and a walk-forward test of
cross-sectional (v3) labels and NSE positioning features.

Pre-registered 2026-09-29, before any model below was fitted:

  Universe   the Decision Desk's: on each signal date the 300 most liquid EQ stocks (126-session
             median turnover), price ≥ ₹20, ≥ 250 sessions of history, no ETFs. Survivorship-free,
             split/bonus-adjusted NSE bhavcopy panel from 2010 (shared/nse_panel.py).
  Dates      signals after the close of the last session of each week (training + IC) and of each
             month (monthly book); entry at the next open.
  Features   shared/xs_features.py, per-date percentiles within the universe.
  Labels     same technical features, same model, three targets:
               A0  v2 production label: 5-session close-to-close return > 0.15% (classifier)
               A1  5-session next-open return minus the universe mean, per-date percentile
               A2  20-session next-open return minus the universe mean, per-date percentile
  Model      LightGBM with the fixed parameters in PARAMS (no tuning); expanding window refit every
             January; training rows end horizon + 1 sessions before the test year; tests 2013 → 2026.
  Yardsticks identical for every candidate: rank IC against the 20- and 5-session next-open excess
             (weekly, Newey-West t); a 20-stock book with the Desk's 1.5× buffer rebalanced monthly and
             weekly, next open to next open, net of ICICI costs at ₹25,000 a position, measured against
             the universe's equal-weight return. Baseline: the Desk's momentum score (mom_nse).
  Features   with label A2, 2021 → 2026: technical vs technical + market-wide NSE data (delivery, F&O
             OI, bulk deals, MTF) on the full universe; technical vs technical + per-company data
             (insider, shareholding), both restricted to the symbols those were collected for, because
             that set is chosen by 2026 liquidity (survivorship).
  Rules      A2 replaces A0 if it beats A0 on IC_20 and on the monthly net book, over 2013 → 2026 and
             in 2024 → 2026. An ML ranking is worth pursuing only if it beats mom_nse on the same two
             measures in both spans. A feature group is worth adding only if the paired weekly IC_20
             difference has a Newey-West t ≥ 2 and the monthly net book does not get worse.

    python scripts/ml_label_study.py [--out reports/ml_labels]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared import xs_features as xf  # noqa: E402
from shared import xs_labels as xl  # noqa: E402
from shared.momentum import MIN_HISTORY, MIN_PRICE, UNIVERSE_SIZE, is_etf, select  # noqa: E402
from shared.momentum import signals as desk_signals  # noqa: E402
from shared.nse_panel import load_panel  # noqa: E402
from shared.trading_costs import default_model  # noqa: E402

PANEL_START = "2010-01-01"
TEST_YEARS = list(range(2013, 2027))
FEATURE_TEST_YEARS = list(range(2021, 2027))
RECENT = pd.Timestamp("2024-01-01")
POSITION_RS = 25_000
N_BOOK = 20
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=800, subsample=0.7,
              subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0, n_jobs=8, verbose=-1, random_state=7)


# ── data ────────────────────────────────────────────────────────────────────────

def load() -> dict:
    db = ROOT / "data" / "market.duckdb"
    tmp = Path(tempfile.mkdtemp(prefix="mllab_"))
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        panel = load_panel(con, start=PANEL_START)
        q = lambda s: con.execute(s).df()  # noqa: E731
        out = {
            "panel": panel,
            "fo": q("SELECT date, symbol, kind, fut_oi, call_oi, put_oi FROM nse_fo_daily"),
            "deals": q("SELECT date, kind, symbol, client_name, side, qty FROM nse_deals WHERE kind = 'bulk'"),
            "mtf": q("SELECT date, symbol, qty_financed FROM nse_mtf"),
            "insider": q("SELECT symbol, category, mode, value, from_date, to_date, intimation_date "
                         "FROM nse_insider_trades WHERE intimation_date IS NOT NULL"),
            "shp": q("SELECT * FROM nse_shareholding"),
            "ml_label_tickers": set(q("SELECT DISTINCT ticker FROM ml_labels")["ticker"]),
            "ml_label_start": q("SELECT MIN(date) AS d FROM ml_labels")["d"].iloc[0],
        }
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for k in ("fo", "deals", "mtf"):
        out[k]["date"] = pd.to_datetime(out[k]["date"])
    out["covered"] = set(out["shp"]["symbol"])      # per-company filings were fetched for these
    return out


def week_ends(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx.to_series().groupby(idx.to_period("W")).max().to_numpy())


def month_ends(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx.to_series().groupby(idx.to_period("M")).max().to_numpy())


def desk_universe(panel: dict, sig: dict, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """shared.momentum.eligible, vectorised over dates."""
    cols = panel["close"].columns
    etf = pd.Series([is_etf(s) for s in cols], index=cols)
    ok = (panel["series"].loc[dates].eq("EQ") & panel["close"].loc[dates].ge(MIN_PRICE)
          & sig["hist"].loc[dates].ge(MIN_HISTORY) & ~etf)
    liq = sig["liq"].loc[dates].where(ok)
    return liq.rank(axis=1, ascending=False, method="first").le(UNIVERSE_SIZE)


# ── statistics ──────────────────────────────────────────────────────────────────

def newey_west_t(x: pd.Series, lags: int) -> float:
    x = pd.Series(x).dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 10:
        return float("nan")
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(var / n)) if var > 0 else float("nan")


def daily_ic(df: pd.DataFrame, score: str, target: str) -> pd.Series:
    d = df[["date", score, target]].dropna()
    r = d.groupby("date")[[score, target]].rank()
    r["date"] = d["date"]
    return r.groupby("date").apply(lambda g: g[score].corr(g[target]), include_groups=False)


def ic_summary(ic: pd.Series, lags: int) -> dict:
    out = {}
    for name, part in (("all", ic), ("to_2023", ic[ic.index < RECENT]), ("from_2024", ic[ic.index >= RECENT])):
        out[f"ic_{name}"] = round(float(part.mean()), 4) if len(part) else np.nan
        out[f"t_{name}"] = round(newey_west_t(part, lags), 2)
    out["ic_positive_pct"] = round(float((ic > 0).mean() * 100), 1)
    return out


# ── books ───────────────────────────────────────────────────────────────────────

def period_returns(open_: pd.DataFrame, dates: pd.DatetimeIndex, max_gap: int) -> pd.DataFrame:
    """Return from the open after dates[k] to the open after dates[k+1] (last traded open if
    the stock stopped trading), indexed by dates[k]."""
    entry = open_.shift(-1).reindex(dates)
    exit_ = open_.ffill(limit=max_gap).shift(-1).reindex(dates).shift(-1)
    return exit_ / entry - 1


def run_book(scores: pd.DataFrame, rets: pd.DataFrame, universe: pd.DataFrame, cost_side: float) -> pd.DataFrame:
    """Top-N with the Desk's buffer on each rebalance date; excess over the universe EW return."""
    held: set[str] = set()
    rows = []
    for d in scores.index:
        if d not in rets.index or rets.loc[d].isna().all():
            continue
        members = universe.loc[d]
        s = scores.loc[d].where(members).dropna()
        if len(s) < 50:
            continue
        pick = select(s, held, N_BOOK, buffer=1.5)
        traded = len(set(pick) ^ held)
        r = rets.loc[d]
        gross = r.reindex(pick).fillna(0).mean()
        bench = r.where(members).mean()
        cost = traded / N_BOOK * cost_side
        rows.append({"date": d, "gross": gross, "bench": bench, "cost": cost, "net_excess": gross - cost - bench,
                     "turnover": traded / (2 * N_BOOK)})
        held = set(pick)
    return pd.DataFrame(rows).set_index("date")


def book_summary(b: pd.DataFrame, per_year: int) -> dict:
    out = {}
    for name, part in (("all", b), ("to_2023", b[b.index < RECENT]), ("from_2024", b[b.index >= RECENT])):
        ex = part["net_excess"]
        out[f"net_excess_ann_{name}"] = round(float(ex.mean() * per_year * 100), 2) if len(ex) else np.nan
        out[f"ir_{name}"] = round(float(ex.mean() / ex.std(ddof=1) * np.sqrt(per_year)), 2) if len(ex) > 2 else np.nan
    out["gross_excess_ann"] = round(float((b["gross"] - b["bench"]).mean() * per_year * 100), 2)
    out["cost_ann"] = round(float(b["cost"].mean() * per_year * 100), 2)
    out["turnover_per_rebalance"] = round(float(b["turnover"].mean()), 3)
    out["periods_beating_universe_pct"] = round(float((b["net_excess"] > 0).mean() * 100), 1)
    return out


# ── models ──────────────────────────────────────────────────────────────────────

def walk_forward(df: pd.DataFrame, feats: list[str], target: str, horizon: int, years: list[int],
                 sessions: pd.DatetimeIndex, classifier: bool = False, train_mask: pd.Series | None = None) -> tuple:
    import lightgbm as lgb
    scores = pd.Series(np.nan, index=df.index)
    importance = pd.Series(0.0, index=feats)
    trainable = df["is_week"] & df[target].notna()
    if train_mask is not None:
        trainable &= train_mask
    for y in years:
        start = pd.Timestamp(f"{y}-01-01")
        first = sessions.searchsorted(start)
        if first - horizon - 1 < 0:
            continue
        cutoff = sessions[first - horizon - 1]
        tr = trainable & (df["date"] <= cutoff)
        te = df["date"].dt.year == y
        if train_mask is not None:
            te &= train_mask
        if tr.sum() < 5000 or te.sum() == 0:
            continue
        model = (lgb.LGBMClassifier if classifier else lgb.LGBMRegressor)(**PARAMS)
        model.fit(df.loc[tr, feats], df.loc[tr, target].astype(int) if classifier else df.loc[tr, target])
        pred = model.predict_proba(df.loc[te, feats])[:, 1] if classifier else model.predict(df.loc[te, feats])
        scores.loc[te] = pred
        importance += pd.Series(model.booster_.feature_importance("gain"), index=feats)
    return scores, importance / max(importance.sum(), 1e-12)


# ── label audit ─────────────────────────────────────────────────────────────────

def label_audit(panel: dict, uni: pd.DataFrame, weeks: pd.DatetimeIndex, rt: float, data: dict,
                labels: dict) -> dict:
    c, h, lo = panel["close"], panel["high"], panel["low"]
    wk = weeks[weeks >= pd.Timestamp("2013-01-01")]
    m = uni.loc[wk]
    cc5 = (c.shift(-5) / c - 1).loc[wk].where(m)
    oo5 = labels["fwd5"].loc[wk].where(m)
    a: dict = {}
    between = cc5.mean(axis=1).var()
    a["market_share_of_5d_variance_pct"] = round(float(between / np.nanvar(cc5.to_numpy()) * 100), 1)
    cc20 = (c.shift(-20) / c - 1).loc[wk].where(m)
    a["market_share_of_20d_variance_pct"] = round(float(cc20.mean(axis=1).var() / np.nanvar(cc20.to_numpy()) * 100), 1)
    up = (cc5 * 100 > 0.15).where(cc5.notna())
    rate = up.mean(axis=1)
    a["weeks_label_mostly_market_pct"] = round(float(((rate > 0.7) | (rate < 0.3)).mean() * 100), 1)
    a["label_up_rate_range_by_year"] = [round(float(v), 3) for v in rate.groupby(rate.index.year).mean().agg(["min", "max"])]
    ups = cc5.stack()
    ups = ups[ups * 100 > 0.15]
    a["up_labels_losing_after_real_costs_pct"] = round(float((ups < rt).mean() * 100), 1)
    both = pd.DataFrame({"cc5": cc5.stack(), "oo5": oo5.stack()}).dropna()
    a["corr_close_vs_next_open_5d"] = round(float(both.corr().iloc[0, 1]), 3)
    rev = (c / c.shift(1) - 1).loc[wk].where(m).rank(axis=1, pct=True)
    ex_cc = cc5.sub(cc5.mean(axis=1), axis=0)
    ex_oo = oo5.sub(oo5.mean(axis=1), axis=0)
    a["ic_ret1d_vs_close_label"] = round(float(rev.T.corrwith(ex_cc.T, method="spearman").mean()), 4)
    a["ic_ret1d_vs_next_open_label"] = round(float(rev.T.corrwith(ex_oo.T, method="spearman").mean()), 4)
    # ±2% triple barrier over 5 sessions from the signal close (the v2 definition)
    tgt, stp = c * 1.02, c * 0.98
    resolved = pd.DataFrame(False, index=c.index, columns=c.columns)
    first_both = pd.DataFrame(False, index=c.index, columns=c.columns)
    for k in range(1, 6):
        uk, dk = h.shift(-k) >= tgt, lo.shift(-k) <= stp
        first_both |= uk & dk & ~resolved
        resolved |= uk | dk
    hit, amb = resolved.loc[wk].where(m), first_both.loc[wk].where(m)
    a["barrier_2pct_touched_pct"] = round(float(np.nanmean(hit.to_numpy(dtype=float)) * 100), 1)
    a["barrier_2pct_same_bar_ambiguous_pct"] = round(float(np.nanmean(amb.to_numpy(dtype=float)) * 100), 1)
    vol = (c.pct_change(fill_method=None).rolling(60, min_periods=45).std()).loc[wk].where(m)
    a["median_daily_vol_pct"] = round(float(np.nanmedian(vol.to_numpy()) * 100), 2)
    # survivorship: universe members the Yahoo-based ml_labels never had
    since = wk[wk >= pd.Timestamp("2021-01-01")]
    ex20 = labels["ex20"].loc[since].where(uni.loc[since])
    present = pd.Series([s in data["ml_label_tickers"] for s in ex20.columns], index=ex20.columns)
    a["universe_rows_missing_from_ml_labels_pct"] = round(float(ex20.loc[:, ~present].notna().sum().sum()
                                                                / ex20.notna().sum().sum() * 100), 1)
    a["missing_names_mean_20d_excess_pct"] = round(float(np.nanmean(ex20.loc[:, ~present].to_numpy()) * 100), 2)
    a["ml_labels_start"] = str(data["ml_label_start"])
    a["panel_start"] = str(c.index.min().date())
    # coverage bias of the per-company datasets (insider, shareholding): covered = liquid in 2026
    early = wk[(wk >= pd.Timestamp("2019-10-01")) & (wk < RECENT)]
    e20 = labels["ex20"].loc[early].where(uni.loc[early])
    cov = pd.Series([s in data["covered"] for s in e20.columns], index=e20.columns)
    a["covered_names_mean_20d_excess_2019_2023_pct"] = round(float(np.nanmean(e20.loc[:, cov].to_numpy()) * 100), 2)
    a["uncovered_names_mean_20d_excess_2019_2023_pct"] = round(float(np.nanmean(e20.loc[:, ~cov].to_numpy()) * 100), 2)
    return a


# ── main ────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/ml_labels")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)  # noqa: E731

    data = load()
    full = data["panel"]
    log(f"panel {full['close'].shape}, {full['close'].index.min().date()} → {full['close'].index.max().date()}")
    sig = desk_signals(full)
    sessions = full["close"].index
    weeks, months = week_ends(sessions), month_ends(sessions)
    weeks, months = weeks[weeks >= pd.Timestamp("2011-01-01")], months[months >= pd.Timestamp("2011-01-01")]
    dates = weeks.union(months)
    uni_full = desk_universe(full, sig, dates)
    members = uni_full.columns[uni_full.any(axis=0)]
    panel = {k: (v[members] if isinstance(v, pd.DataFrame) and v.index.equals(sessions) else v) for k, v in full.items()}
    mom_nse = sig["mom_nse"][members]
    uni = uni_full[members]
    del full, sig
    log(f"universe: {len(members)} symbols ever in the Desk's top {UNIVERSE_SIZE}, {len(dates)} signal dates")

    # labels
    fwd5, fwd20 = xl.forward_open_returns(panel["open"], 5), xl.forward_open_returns(panel["open"], 20)
    fwd5 = fwd5.where(xl.clean_windows(panel["close"], 6))
    fwd20 = fwd20.where(xl.clean_windows(panel["close"], 21))
    u_all = uni.reindex(sessions).fillna(False).astype(bool)
    labels = {"fwd5": fwd5, "fwd20": fwd20, "ex5": xl.excess_returns(fwd5, u_all), "ex20": xl.excess_returns(fwd20, u_all)}
    labels["rank5"], labels["rank20"] = xl.rank_label(labels["ex5"]), xl.rank_label(labels["ex20"])
    labels["legacy"] = xl.legacy_direction_label(panel["close"], 5, 0.15)
    rt = default_model().round_trip_pct(POSITION_RS) / 100
    audit = label_audit(panel, u_all, weeks, rt, data, labels)
    log(f"label audit done: {audit}")

    # features
    tech = xf.technical_features(panel)
    tech["mom_nse"] = mom_nse
    wide_mkt = xf.market_wide_features(panel, data["fo"], data["deals"], data["mtf"])
    wide_co = xf.per_company_features(panel, data["insider"], data["shp"], data["covered"])
    df = xf.stack({**tech, **wide_mkt, **wide_co}, dates, uni)
    for name in ("ex5", "ex20", "rank5", "rank20", "legacy"):
        df[name] = labels[name].reindex(index=dates).stack(future_stack=True).reindex(
            pd.MultiIndex.from_arrays([df["date"], df["symbol"]])).to_numpy()
    df["is_week"] = df["date"].isin(weeks)
    df["is_month"] = df["date"].isin(months)
    df["covered"] = df["symbol"].isin(data["covered"])
    df["mom_raw"] = mom_nse.reindex(index=dates).stack(future_stack=True).reindex(
        pd.MultiIndex.from_arrays([df["date"], df["symbol"]])).to_numpy()
    del tech, wide_mkt, wide_co
    log(f"dataset: {len(df):,} rows × {len(xf.TECHNICAL) + len(xf.MARKET_WIDE) + len(xf.PER_COMPANY)} features")

    # models
    T, M, C = list(xf.TECHNICAL), list(xf.MARKET_WIDE), list(xf.PER_COMPANY)
    runs: dict[str, pd.Series] = {}
    imps: dict[str, pd.Series] = {}
    runs["A0 v2 label (5d close > 0.15%)"], imps["A0"] = walk_forward(df, T, "legacy", 5, TEST_YEARS, sessions, classifier=True)
    log("A0 done")
    runs["A1 5d next-open excess rank"], imps["A1"] = walk_forward(df, T, "rank5", 5, TEST_YEARS, sessions)
    log("A1 done")
    runs["A2 20d next-open excess rank"], imps["A2"] = walk_forward(df, T, "rank20", 20, TEST_YEARS, sessions)
    log("A2 done")
    runs["B1 technical (2021+)"], imps["B1"] = walk_forward(df, T, "rank20", 20, FEATURE_TEST_YEARS, sessions)
    runs["B2 technical + market-wide NSE (2021+)"], imps["B2"] = walk_forward(df, T + M, "rank20", 20, FEATURE_TEST_YEARS, sessions)
    log("B1/B2 done")
    runs["C1 technical, covered symbols (2021+)"], imps["C1"] = walk_forward(df, T, "rank20", 20, FEATURE_TEST_YEARS, sessions,
                                                                             train_mask=df["covered"])
    runs["C2 technical + per-company NSE, covered (2021+)"], imps["C2"] = walk_forward(
        df, T + C, "rank20", 20, FEATURE_TEST_YEARS, sessions, train_mask=df["covered"])
    log("C1/C2 done")
    runs["mom_nse (Desk baseline)"] = df["mom_raw"]
    for k, s in runs.items():
        df[f"score::{k}"] = s

    # evaluation
    rets_m = period_returns(panel["open"], months, 30)
    rets_w = period_returns(panel["open"], weeks, 10)
    rows, ic_series, books = [], {}, {}
    for name in runs:
        col = f"score::{name}"
        years = FEATURE_TEST_YEARS if name.startswith(("B", "C")) else TEST_YEARS
        span = df["date"].dt.year.isin(years) & df[col].notna()
        if name.startswith("C"):
            span &= df["covered"]
        if name.startswith("mom_nse"):
            span &= df["date"].dt.year.isin(TEST_YEARS)
        wk = df[span & df["is_week"]]
        ic20, ic5 = daily_ic(wk, col, "ex20"), daily_ic(wk, col, "ex5")
        ic_series[name] = ic20
        r = {"run": name, "weeks": len(ic20)}
        r.update({f"{k}_20": v for k, v in ic_summary(ic20, 4).items()})
        r.update({f"{k}_5": v for k, v in ic_summary(ic5, 1).items()})
        mo = df[span & df["is_month"]].pivot(index="date", columns="symbol", values=col)
        uni_m = uni.reindex(index=mo.index, columns=mo.columns).fillna(False).astype(bool)
        bm = run_book(mo, rets_m.reindex(columns=mo.columns), uni_m, rt / 2)
        books[f"{name} | monthly"] = bm
        r.update({f"monthly_{k}": v for k, v in book_summary(bm, 12).items()})
        if not name.startswith(("B", "C")):
            wkp = wk.pivot(index="date", columns="symbol", values=col)
            uni_w = uni.reindex(index=wkp.index, columns=wkp.columns).fillna(False).astype(bool)
            bw = run_book(wkp, rets_w.reindex(columns=wkp.columns), uni_w, rt / 2)
            books[f"{name} | weekly"] = bw
            r.update({f"weekly_{k}": v for k, v in book_summary(bw, 52).items()})
        rows.append(r)
        log(f"evaluated {name}")
    res = pd.DataFrame(rows)
    res.to_csv(out / "results.csv", index=False)
    pd.DataFrame(ic_series).to_csv(out / "ic20_weekly.csv")
    pd.concat({k: v for k, v in books.items()}, names=["book"]).to_csv(out / "books.csv")

    # paired feature tests
    paired = {}
    for a_name, b_name in (("B1 technical (2021+)", "B2 technical + market-wide NSE (2021+)"),
                           ("C1 technical, covered symbols (2021+)", "C2 technical + per-company NSE, covered (2021+)")):
        diff = (ic_series[b_name] - ic_series[a_name]).dropna()
        paired[b_name] = {"mean_ic_gain": round(float(diff.mean()), 4), "t_nw": round(newey_west_t(diff, 4), 2),
                          "weeks": len(diff)}
    # univariate IC of each NSE feature vs the 20-session excess (2020+, weekly)
    wk_all = df[df["is_week"] & (df["date"] >= pd.Timestamp("2020-01-01"))]
    uni_ic = {}
    for f_name in M + C:
        s = wk_all if f_name in M else wk_all[wk_all["covered"]]
        ic = daily_ic(s, f_name, "ex20")
        uni_ic[f_name] = {"ic": round(float(ic.mean()), 4), "t_nw": round(newey_west_t(ic, 4), 2), "weeks": len(ic)}
    importance = pd.DataFrame(imps).round(4)
    importance.to_csv(out / "feature_importance.csv")

    # where the ranking skill sits (descriptive): mean 20-session excess by score decile, weekly, 2013+
    deciles = {}
    test_wk = df[df["is_week"] & df["date"].dt.year.isin(TEST_YEARS)]
    for name in ("A0 v2 label (5d close > 0.15%)", "A2 20d next-open excess rank", "mom_nse (Desk baseline)"):
        col = f"score::{name}"
        d = test_wk[["date", col, "ex20"]].dropna()
        d["decile"] = d.groupby("date")[col].rank(pct=True).mul(10).clip(upper=9.999).floordiv(1).astype(int) + 1
        deciles[name] = (d.groupby(["date", "decile"])["ex20"].mean().groupby("decile").mean() * 100).round(2)
    agree = test_wk[["date", "score::A2 20d next-open excess rank", "score::mom_nse (Desk baseline)"]].dropna()
    ranks = agree.groupby("date")[["score::A2 20d next-open excess rank", "score::mom_nse (Desk baseline)"]].rank()
    ranks["date"] = agree["date"]
    rank_corr = ranks.groupby("date").apply(lambda g: g.iloc[:, 0].corr(g.iloc[:, 1]), include_groups=False).mean()
    keep = ["date", "symbol", "ex5", "ex20", "is_week", "is_month", "covered"] + [c for c in df.columns if c.startswith("score::")]
    df[keep].to_parquet(out / "scores.parquet", index=False)

    meta = {"generated": f"{datetime.now():%Y-%m-%d %H:%M}", "rows": len(df), "symbols": len(members),
            "signal_dates": len(dates), "round_trip_pct": round(rt * 100, 3), "runtime_s": round(time.time() - t0)}
    meta["a2_vs_mom_rank_corr"] = round(float(rank_corr), 3)
    (out / "REPORT.md").write_text(render(res, audit, paired, uni_ic, importance, books, meta, pd.DataFrame(deciles)))
    log("report written")


def _md(df: pd.DataFrame) -> str:
    head = "| " + " | ".join([str(df.index.name or "")] + [str(c).split(" | ")[0] for c in df.columns]) + " |"
    rows = ["| " + " | ".join([str(i)] + ["" if pd.isna(v) else f"{v}" for v in r]) + " |" for i, r in df.iterrows()]
    return "\n".join([head, "|---" * (len(df.columns) + 1) + "|", *rows])


def render(res, audit, paired, uni_ic, importance, books, meta, deciles: pd.DataFrame) -> str:
    L = ["# ML labels and features: audit and walk-forward test", "",
         f"Generated {meta['generated']} by `scripts/ml_label_study.py` (pre-registered rules in its docstring). "
         f"{meta['rows']:,} stock-dates, {meta['symbols']} symbols that were ever in the Desk's top-300 universe, "
         f"{meta['signal_dates']} signal dates. Costs: {meta['round_trip_pct']}% round trip at ₹{POSITION_RS:,} a position.", "",
         "## Audit of the v2 labels", "", "| Measure | Value |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in audit.items()]
    L += ["", "## Ranking quality (rank IC vs next-open excess return; weekly; Newey-West t)", "",
          "| Run | IC 20d all | t | IC 20d ≤2023 | t | IC 20d 2024+ | t | IC 5d all | t | weeks IC>0 % |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in res.itertuples(index=False):
        L.append(f"| {r.run} | {r.ic_all_20} | {r.t_all_20} | {r.ic_to_2023_20} | {r.t_to_2023_20} | {r.ic_from_2024_20} | "
                 f"{r.t_from_2024_20} | {r.ic_all_5} | {r.t_all_5} | {r.ic_positive_pct_20} |")
    L += ["", "## 20-stock book, net of costs, excess over the universe's equal-weight return (annualised %)", "",
          "| Run | Monthly: all | ≤2023 | 2024+ | IR all | gross | costs | turnover | Weekly: all | 2024+ | costs |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res.to_dict("records"):
        L.append(f"| {r['run']} | {r['monthly_net_excess_ann_all']} | {r['monthly_net_excess_ann_to_2023']} | "
                 f"{r['monthly_net_excess_ann_from_2024']} | {r['monthly_ir_all']} | {r['monthly_gross_excess_ann']} | "
                 f"{r['monthly_cost_ann']} | {r['monthly_turnover_per_rebalance']} | {r.get('weekly_net_excess_ann_all', '')} | "
                 f"{r.get('weekly_net_excess_ann_from_2024', '')} | {r.get('weekly_cost_ann', '')} |")
    L += ["", "## Where the ranking skill sits: mean 20-session excess by score decile (%, weekly, 2013+)", "",
          _md(deciles.rename_axis("decile")), "",
          f"Average per-date rank correlation between the A2 model and mom_nse: {meta['a2_vs_mom_rank_corr']}.", ""]
    L += ["", "## Feature groups (paired weekly IC_20 difference, label A2)", "", "| Added group | Mean IC gain | t (NW) | Weeks |",
          "|---|---|---|---|"]
    L += [f"| {k} | {v['mean_ic_gain']} | {v['t_nw']} | {v['weeks']} |" for k, v in paired.items()]
    L += ["", "## Each NSE feature alone (rank IC vs 20-session excess, weekly, 2020+)", "", "| Feature | IC | t (NW) | Weeks |",
          "|---|---|---|---|"]
    L += [f"| {k} | {v['ic']} | {v['t_nw']} | {v['weeks']} |" for k, v in uni_ic.items()]
    L += ["", "## Feature importance (share of total gain, summed over refits)", "",
          "| Feature | " + " | ".join(importance.columns) + " |", "|---" * (len(importance.columns) + 1) + "|"]
    top = importance.fillna(0).sort_values("A2", ascending=False)
    L += [f"| {f} | " + " | ".join(f"{v:.3f}" for v in row) + " |" for f, row in top.iterrows()]
    yearly = {k: v["net_excess"].groupby(v.index.year).sum().mul(100).round(1) for k, v in books.items() if k.endswith("monthly")}
    L += ["", "## Monthly book, net excess by year (%)", "", _md(pd.DataFrame(yearly)) if yearly else "",
          "", f"Runtime {meta['runtime_s']} s."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
