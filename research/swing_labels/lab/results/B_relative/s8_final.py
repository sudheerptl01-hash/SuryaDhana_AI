"""Stage 8: significance of excess over random + index-hedged variant + liquidity robustness.
 * per-cohort excess of model top-K over the mean of 10 random-pick seeds (same mask, same dates),
   t-stat on NON-overlapping cohorts (every ceil(h/step)-th), separately dev / holdout, by year
 * index-hedged long book (F&O-trader variant without single-stock shorts):
   long top-K, short Nifty-500 over the same executable window, extra 10 bps hedge cost
 * liquidity robustness: same score on elig_liq5 (20d turnover >= Rs 5 cr) universe + its own random
 * pick profile: median 20d turnover (Rs cr), fno_proxy share, liq5 share
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, Sim, stats_from_cohorts

E = f"{OUT}/../E_auditor"
CONFIGS = [  # name, path, h, step, K
    ("R10_neu", f"{OUT}/wf_R10_neu.npz", 10, 5, 20), ("R10_raw", f"{OUT}/wf_R10_raw.npz", 10, 5, 20),
    ("R10_vn", f"{OUT}/wf_R10_vn.npz", 10, 5, 20), ("B10_mx", f"{OUT}/wf_B10_mx.npz", 10, 5, 20),
    ("ABS10_E", f"{E}/wf_nosec.npz", 10, 5, 20), ("R10_neu_k50", f"{OUT}/wf_R10_neu.npz", 10, 5, 50),
    ("R5_neu", f"{OUT}/wf_R5_neu.npz", 5, 5, 20), ("R20_neu", f"{OUT}/wf_R20_neu.npz", 20, 5, 20),
    ("R20_neu_s10", f"{OUT}/wf_R20_neu.npz", 20, 10, 20),
]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_liq5", "log_turn20"])
fw = L.Fwd(P)
meta = np.load(f"{OUT}/meta.npz")
U, fno = meta["U"], meta["fno"]
liq5 = F["elig_liq5"].values.astype(bool)
turn_cr = np.expm1(F["log_turn20"].values.astype("float64")) / 1e7
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
sims = {}
out = {}


def tt(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 3 else np.nan


def nw_t(x, lags):
    """Newey-West (Bartlett) t-stat of the mean using all (overlapping) cohorts."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return np.nan
    e = x - x.mean()
    v = e @ e / n
    for l in range(1, lags + 1):
        v += 2 * (1 - l / (lags + 1)) * (e[l:] @ e[:-l]) / n
    return float(x.mean() / np.sqrt(v / n))


for name, path, h, step, K in CONFIGS:
    if h not in sims:
        sims[h] = (Sim(P, fw, h), np.load(f"{OUT}/labels_h{h}.npz")["m"].astype("float64"),
                   np.load(f"{OUT}/labels_h{h}.npz")["r"].astype("float64"))
    sim, mrow, r = sims[h]
    M = U & np.isfinite(r)
    dev_end = cal[np.searchsorted(cal, np.datetime64("2025-12-31"), side="right") - 1 - h]
    sc = np.load(path)["score"].astype("float64")
    R = {"h": h, "step": step, "K": K}
    S = int(np.ceil(h / step))
    for cost in (50.0, 80.0):
        cd, cr, pk = sim.cohorts(sc, M, "M", step=step, top_k=K, cost_bps=cost)
        rruns = [sim.cohorts(None, M, "M", step=step, top_k=K, cost_bps=cost, random_seed=s) for s in range(10)]
        rnd = np.mean([x[1] for x in rruns], axis=0)
        ex = cr - rnd
        res = {}
        for w, sel in (("dev", cd <= dev_end), ("hold", cd >= np.datetime64("2026-01-01"))):
            e = ex[sel]
            res[w] = {"mean_excess_bps_per_cohort": float(e.mean() * 1e4), "t_nonoverlap": tt(e[::S]), "t_newey_west_all": nw_t(e, 2 * S),
                      "n_nonoverlap": int(len(e[::S])), "share_cohorts_positive": float((e > 0).mean())}
        yrs = pd.DatetimeIndex(cd).year
        res["by_year_mean_excess_bps"] = {int(y): float(ex[yrs == y].mean() * 1e4) for y in np.unique(yrs)}
        R[f"excess_vs_random_{int(cost)}"] = res
        if cost == 50.0:
            allp = np.concatenate([p for p in pk if len(p)])
            R["pick_profile"] = {"median_turnover20_cr": float(np.median(turn_cr[allp])),
                                 "p25_turnover20_cr": float(np.percentile(turn_cr[allp], 25)),
                                 "fno_share": float(fno[allp].mean()), "liq5_share": float(liq5[allp].mean()),
                                 "universe_median_turnover20_cr": float(np.median(turn_cr[M & (dates >= np.datetime64("2023-01-01"))]))}
        # index-hedged long book
        hed = np.array([np.nanmean(sim.tr_long[p] - mrow[p]) - cost / 1e4 - 10 / 1e4 if len(p) else 0.0 for p in pk])
        hres = {}
        for w, sel in (("full", np.ones(len(cd), bool)), ("dev", cd <= dev_end), ("hold", cd >= np.datetime64("2026-01-01"))):
            st = stats_from_cohorts(cd[sel], hed[sel], h, step)
            hres[w] = {k: st[k] for k in ("cagr", "sharpe", "sharpe_adj", "max_dd", "by_year")}
        R[f"index_hedged_{int(cost)}"] = hres
        # same hedge applied to the random baseline (removes the equal- vs cap-weight size effect)
        rh = {}
        for w, sel in (("full", np.ones(len(cd), bool)), ("dev", cd <= dev_end), ("hold", cd >= np.datetime64("2026-01-01"))):
            vals = []
            for x in rruns:
                hx = np.array([np.nanmean(sim.tr_long[p] - mrow[p]) - cost / 1e4 - 10 / 1e4 if len(p) else 0.0 for p in x[2]])
                vals.append(stats_from_cohorts(x[0][sel], hx[sel], h, step)["cagr"])
            rh[w] = float(np.mean(vals))
        R[f"index_hedged_random_cagr_{int(cost)}"] = rh
    # liquidity robustness (liq5 universe), 50 / 80 bps
    if name in ("R10_neu", "R20_neu", "R20_neu_s10", "R10_raw"):
        M5 = M & liq5
        for cost in (50.0, 80.0):
            cd, cr, pk = sim.cohorts(sc, M5, "M5", step=step, top_k=K, cost_bps=cost)
            rr = [sim.cohorts(None, M5, "M5", step=step, top_k=K, cost_bps=cost, random_seed=s) for s in range(5)]
            lres = {}
            for w, sel in (("full", np.ones(len(cd), bool)), ("dev", cd <= dev_end), ("hold", cd >= np.datetime64("2026-01-01"))):
                st = stats_from_cohorts(cd[sel], cr[sel], h, step)
                rs = [stats_from_cohorts(x[0][sel], x[1][sel], h, step)["cagr"] for x in rr]
                lres[w] = {"cagr": st["cagr"], "sharpe": st["sharpe"], "max_dd": st["max_dd"], "random_cagr": float(np.mean(rs)),
                           "by_year": st["by_year"]}
            R[f"liq5_LO_{int(cost)}"] = lres
    out[name] = R
    print(name, round(time.time() - t0, 1), {k: v for k, v in R["excess_vs_random_50"].items() if k != "by_year_mean_excess_bps"},
          "hedged50", {w: round(v["cagr"], 3) for w, v in R["index_hedged_50"].items()}, "rand_hedged50", {w: round(v, 3) for w, v in R["index_hedged_random_cagr_50"].items()},
          "liq5", {w: (round(v["cagr"], 3), round(v["random_cagr"], 3)) for w, v in R.get("liq5_LO_50", {}).items()}, flush=True)
save("s8_final", out)
