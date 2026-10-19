"""Stage 7: paired comparisons and drawdown/regime diagnostics from the daily return series of the
Sim books (s5). Answers: does the label-side AND (DUAL) or a two-model AND beat (a) the pure-relative
regression book and (b) the pure-relative BINARY top-30 book (same loss, no absolute leg)?"""
import itertools

import numpy as np
import pandas as pd

from common import OUT, L, save

D = dict(np.load(f"{OUT}/daily_main_ksens_liq5_avoid.npz"))
G = dict(np.load(f"{OUT}/daily_main_ksens_liq5_gates_avoid.npz"))
P = L.load_panel(["date"])
cal = np.unique(P["date"].values.astype("datetime64[D]"))
mk = L.market_series("Nifty 500")["close"].reindex(pd.DatetimeIndex(cal)).ffill()
sma200 = mk.rolling(200, min_periods=150).mean()
reg_bull = pd.Series((mk > sma200).values, index=cal)
mom20 = pd.Series((mk / mk.shift(20) - 1).values, index=cal)
mret = pd.Series(mk.pct_change().values, index=cal)
S = L.Sim(P.assign(open=1.0, high=1.0, low=1.0, close=1.0, entity=0, seg_break=False, label_block=False))


def dates_for(win, n):
    a, b = (L.DEV if win == "dev" else (L.HOLDOUT[0], None))
    g0 = int(np.searchsorted(cal, np.datetime64(a)))
    return cal[g0:g0 + n]


def key(name, mask="U", win="dev", cost=50.0, step=5, k=20, sizing="slot", sq=None):
    return "|".join(map(str, (name, mask, win, cost, step, k, sizing, sq)))


def stats(r, d):
    eq = np.cumprod(1 + r)
    dd = eq / np.maximum.accumulate(eq) - 1
    yrs = max((d[-1] - d[0]).astype(int) / 365.25, 1e-9)
    mr = mret.reindex(d).values
    ok = np.isfinite(mr)
    w20 = float(np.min(eq[20:] / eq[:-20] - 1))
    cagr = float(eq[-1] ** (1 / yrs) - 1)
    return {"cagr": cagr, "ann_vol": float(r.std() * np.sqrt(252)), "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
            "max_dd": float(dd.min()), "calmar": cagr / abs(float(dd.min())), "worst_20d": w20,
            "beta": float(np.cov(r[ok], mr[ok])[0, 1] / np.var(mr[ok], ddof=1)),
            "down_capture": float(r[ok & (mr < 0)].mean() / mr[ok & (mr < 0)].mean()),
            "up_capture": float(r[ok & (mr > 0)].mean() / mr[ok & (mr > 0)].mean())}


out = {}
# 1) drawdown / risk table for the main books (K20 s5, U)
names = ["REL", "RUP", "DUAL", "DUALP", "DUALt300", "DUALmc", "ABS", "BAR", "SUM_REL_ABS", "SUM_REL_BAR",
         "PROD_RUP_ABS", "AND_REL_ABS50", "SUM_REL_DUAL", "SUM_REL_RUP"]
risk = []
for win in ("dev", "hold"):
    for cost in (50.0, 80.0):
        for nm in names:
            k = key(nm, win=win, cost=cost)
            if k not in D:
                continue
            r = D[k]
            d = dates_for(win, len(r))
            risk.append({"name": nm, "win": win, "cost": cost, **stats(r, d)})
out["risk_main"] = risk
# 2) paired differences (daily, NW lag 20) for the questions that matter
pairs = [("DUAL", "REL"), ("DUAL", "RUP"), ("DUALP", "REL"), ("DUALP", "RUP"), ("DUALt300", "RUP"),
         ("DUALt300", "DUAL"), ("RUP", "REL"), ("ABS", "REL"), ("BAR", "REL"), ("SUM_REL_ABS", "REL"),
         ("SUM_REL_BAR", "REL"), ("AND_REL_ABS50", "REL"), ("PROD_RUP_ABS", "RUP"), ("SUM_REL_DUAL", "REL"),
         ("SUM_REL_DUAL", "RUP"), ("DUALmc", "REL"), ("SUM_REL_DUAL", "SUM_REL_RUP"), ("SUM_REL_RUP", "REL")]
pr = []
for win in ("dev", "hold"):
    for cost in (50.0,):
        for a, b in pairs:
            ka, kb = key(a, win=win, cost=cost), key(b, win=win, cost=cost)
            if ka not in D or kb not in D:
                continue
            dd_ = D[ka] - D[kb]
            d = dates_for(win, len(dd_))
            bull = reg_bull.reindex(d).values.astype(bool)
            up20 = (mom20.reindex(d).values > 0)
            pr.append({"a": a, "b": b, "win": win, "cost": cost, "ann_diff": float(dd_.mean() * 252),
                       "nw_t": L.nw_t(dd_, lag=20), "corr": float(np.corrcoef(D[ka], D[kb])[0, 1]),
                       "ann_diff_bull200": float(dd_[bull].mean() * 252), "ann_diff_bear200": float(dd_[~bull].mean() * 252),
                       "ann_diff_mkt_up20": float(dd_[up20].mean() * 252), "ann_diff_mkt_dn20": float(dd_[~up20].mean() * 252),
                       "share_days_bear200": float((~bull).mean())})
out["paired_main"] = pr
# 3) sign consistency over the dev K x step grid (50 bps)
grid = []
for a, b in [("DUAL", "REL"), ("DUAL", "RUP"), ("DUALP", "REL"), ("DUALP", "RUP"), ("DUALt300", "RUP"), ("RUP", "REL"),
             ("ABS", "REL"), ("SUM_REL_ABS", "REL"), ("AND_REL_ABS50", "REL"), ("SUM_REL_DUAL", "REL"),
             ("SUM_REL_DUAL", "SUM_REL_RUP"), ("SUM_REL_RUP", "REL")]:
    for win in ("dev", "hold"):
        diffs, ts = [], []
        for step in (5, 10):
            for k in (10, 20, 30, 50):
                ka, kb = key(a, win=win, step=step, k=k), key(b, win=win, step=step, k=k)
                if ka in D and kb in D:
                    x = D[ka] - D[kb]
                    diffs.append(float(x.mean() * 252))
                    ts.append(L.nw_t(x, lag=20))
        if diffs:
            grid.append({"a": a, "b": b, "win": win, "n_cells": len(diffs), "n_positive": int(np.sum(np.array(diffs) > 0)),
                         "median_ann_diff": float(np.median(diffs)), "min_ann_diff": float(np.min(diffs)),
                         "max_ann_diff": float(np.max(diffs)), "median_t": float(np.median(ts)),
                         "n_t_gt_2": int(np.sum(np.array(ts) > 2))})
out["grid_consistency"] = grid
# 4) regime-conditional mean returns of the books themselves (dev+hold pooled, K20 s5, 50 bps)
reg_rows = []
for nm in ["REL", "RUP", "DUAL", "DUALP", "ABS", "BAR", "SUM_REL_ABS"]:
    rs, ds = [], []
    for win in ("dev", "hold"):
        k = key(nm, win=win)
        if k in D:
            rs.append(D[k])
            ds.append(dates_for(win, len(D[k])))
    r = np.concatenate(rs)
    d = np.concatenate(ds)
    bull = reg_bull.reindex(d).values.astype(bool)
    up20 = mom20.reindex(d).values > 0
    mr = mret.reindex(d).values
    row = {"name": nm}
    for nmr, m_ in (("bull200", bull), ("bear200", ~bull), ("mkt_up20", up20), ("mkt_dn20", ~up20)):
        row[f"ann_ret_{nmr}"] = float(r[m_].mean() * 252)
        row[f"beta_{nmr}"] = float(np.cov(r[m_], mr[m_])[0, 1] / np.var(mr[m_], ddof=1))
    reg_rows.append(row)
out["regime_books"] = reg_rows
# 5) number of distinct strategy configurations evaluated on DEV (multiple-testing count)
dev_keys = set()
for src in (D, G):
    for k in src:
        p = k.split("|")
        if p[2] == "dev":
            dev_keys.add((p[0], p[1], p[4], p[5], p[6], p[7]))
out["n_dev_strategy_configs"] = len(dev_keys)
save("s7_paired", out)
pd.set_option("display.width", 250)
print(pd.DataFrame(risk).round(3).to_string())
print(pd.DataFrame(pr).round(3).to_string())
print(pd.DataFrame(grid).round(3).to_string())
print(pd.DataFrame(reg_rows).round(3).to_string())
print("dev configs", len(dev_keys))
