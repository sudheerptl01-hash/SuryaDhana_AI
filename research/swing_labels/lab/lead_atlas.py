#!/usr/bin/env python3
"""Lead's event-rate atlas on lab v2 (no model training): label event rates
across horizons 5/10/15/20, regime dependence, the old repo label vs clean
labels, triple-barrier class shares, and the cost-drag curve of random books."""
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

OUT = os.path.join(LAB, "results", "_lead")
os.makedirs(OUT, exist_ok=True)
P = L.load_panel(["date", "entity", "symbol", "isin", "open", "high", "low", "close", "raw_close",
                  "seg_break", "label_block"])
F = L.load_features(["elig_base", "atr_pct", "mkt_dist_sma200", "mkt_mom20", "log_turn20", "vol_20"])
fw = L.Fwd(P)
m = F.elig_base.values
dates = pd.DatetimeIndex(P.date.values)
yr = dates.year.values
mon = dates.to_period("M").astype(str).values
mk = L.market_series("Nifty 500")["close"]
mret = mk.resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)
regime = np.where(F.mkt_dist_sma200.values > 0, "bull", "bear")
atlas = {}


def summarize(lab, mask, name, positive=1):
    lab = np.asarray(lab, dtype="float64")
    ok = mask & np.isfinite(lab)
    y = lab[ok]
    classes = sorted(np.unique(y).tolist())
    d = {"n": int(ok.sum()), "overall": {str(c): round(float((y == c).mean()), 4) for c in classes}}
    df = pd.DataFrame({"y": y, "yr": yr[ok], "mon": mon[ok], "reg": regime[ok]})
    d["by_year"] = {int(k): round(float((g.y == positive).mean()), 4) for k, g in df.groupby("yr")}
    d["by_regime"] = {k: round(float((g.y == positive).mean()), 4) for k, g in df.groupby("reg")}
    ms = df.groupby("mon").y.apply(lambda s: float((s == positive).mean()))
    d["monthly_pos"] = {"mean": round(float(ms.mean()), 4), "std": round(float(ms.std()), 4),
                        "min": round(float(ms.min()), 4), "max": round(float(ms.max()), 4)}
    j = pd.concat([ms, mret], axis=1, join="inner").dropna()
    d["corr_monthly_pos_vs_mkt"] = round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 3)
    d["monthly_series"] = {k: round(v, 4) for k, v in ms.items()}
    atlas[name] = d
    print(name, d["overall"], "monthly sd", d["monthly_pos"]["std"], "corr", d["corr_monthly_pos_vs_mkt"], flush=True)


for h in (5, 10, 15, 20):
    r = L.fwd_return(P, fw, h)                       # executable open[t+1] -> close[t+h]
    # old repo label: close[t] entry, raw (unadjusted) prices, NaN -> 0 after the cast
    rc = P.raw_close.values
    old_fwd = fw.at(rc, h) / rc - 1                   # within segment only (kinder than the repo)
    old_lab = (old_fwd > 0).astype(float)             # NaN > 0 is False -> 0 (the repo bug)
    summarize(old_lab, m, f"old_repo_label_h{h}")
    summarize(np.where(np.isfinite(r), (r > 0).astype(float), np.nan), m, f"clean_sign_h{h}")
    tau = 0.005
    three = np.where(np.isfinite(r), np.where(r > tau, 1.0, np.where(r < -tau, -1.0, 0.0)), np.nan)
    summarize(three, m, f"cost_aware_3class_h{h}")
    atlas[f"exec_return_h{h}"] = {"mean_bps": float(np.nanmean(r[m]) * 1e4),
                                  "median_bps": float(np.nanmedian(r[m]) * 1e4),
                                  "close_entry_mean_bps": float(np.nanmean((fw.at(P.close.values, h) / P.close.values - 1)[m & np.isfinite(r)]) * 1e4)}
    # triple barrier, sqrt(h)-scaled symmetric-ish geometry used by the team
    for pt, sl in ((2.0, 2.0), (3.0, 1.5)):
        tb = L.barrier_labels(P, F, fw, h, pt * np.sqrt(h / 20), sl * np.sqrt(h / 20))
        summarize(tb["label"], m, f"barrier_{pt}_{sl}_h{h}")
        t = pd.Series(tb["touch"][m & tb["valid"]])
        atlas[f"barrier_{pt}_{sl}_h{h}"]["touch_shares"] = {k: round(float(v), 4) for k, v in t.value_counts(normalize=True).items()}
        atlas[f"barrier_{pt}_{sl}_h{h}"]["mean_net_by_class"] = {
            str(c): float(np.nanmean((tb["ret"] - 0.005)[m & (tb["label"] == c)])) for c in (-1, 0, 1)}
    # relative 30/40/30 rank of residual (cross-sectional, regime-free by construction)
    df = pd.DataFrame({"d": P.date.values, "r": r, "m": m})
    rk = df[df.m].groupby("d").r.rank(pct=True)
    rel = np.full(len(P), np.nan)
    rel[rk.index] = np.where(rk > 0.7, 1.0, np.where(rk <= 0.3, -1.0, 0.0))
    rel[~np.isfinite(r)] = np.nan
    summarize(rel, m, f"relative_rank_30_40_30_h{h}")
    del r, old_fwd, old_lab, three, df, rk, rel

# cost-drag curve: random top-20 books by horizon and cost (dev and holdout)
S = L.Sim(P, F, fw)
curve = {}
for h in (5, 10, 15, 20):
    for cost in (0, 50, 80):
        for win, (a, b) in (("dev", L.DEV), ("holdout", ("2026-01-01", None))):
            rb = S.random_band(m, h, seeds=(1, 2, 3), step=5, top_k=20, cost_bps=cost, start=a, end_exit=b)
            curve[f"h{h}_c{cost}_{win}"] = {"cagr": rb["cagr_mean"], "sd": rb["cagr_sd"], "sharpe": rb["sharpe_mean"],
                                            "maxdd": rb["max_dd_mean"]}
            print("random", h, cost, win, round(rb["cagr_mean"], 4), flush=True)
atlas["random_cost_curve"] = curve
atlas["nifty500_dev"] = L.benchmark(P, start=L.DEV[0], end=L.DEV[1])
atlas["nifty500_holdout"] = L.benchmark(P, start="2026-01-01")
json.dump(atlas, open(os.path.join(OUT, "atlas_v2.json"), "w"), indent=1, default=float)
print("WROTE atlas_v2.json")
