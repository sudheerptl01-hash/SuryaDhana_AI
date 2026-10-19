"""Stage 3 (devil): re-simulate the self-built model with L.Sim.compare (headline) and phase-averaging.
Usage: python3 s3_repro.py [score_job=main]
"""
import sys

import numpy as np
import pandas as pd

from common import OUT, L, PER, log, save, load_sim, compare, phase_avg, short

job = sys.argv[1] if len(sys.argv) > 1 else "main"
P, F, fw, S, E = load_sim()
sc = np.load(f"{OUT}/wf_{job}.npz")["score"].astype("float64")
log("sim ready")
H = 20
out = {}
# 1) literal Sim.compare (no cache) for the headline cells
for per, (a, b) in PER.items():
    for cost in (50, 80):
        r = S.compare(sc, E, H, top_k=20, step=5, cost_bps=cost, start=a, end_exit=b)
        keep = {k: r[k] for k in ("cagr", "sharpe", "max_dd", "ann_vol", "exposure", "trades", "hit_rate",
                                  "mean_trade_net", "by_year", "excess_cagr_vs_random", "excess_daily_nw_t",
                                  "excess_ann_return", "forced_exits")}
        keep["random_cagr"] = r["random"]["cagr_mean"]
        keep["random_cagr_sd"] = r["random"]["cagr_sd"]
        keep["random_maxdd"] = r["random"]["max_dd_mean"]
        keep["random_by_year"] = r["random"]["by_year_mean"]
        out[f"compare_{per}_c{cost}"] = keep
        log(per, cost, short({k: keep[k] for k in ("cagr", "random_cagr", "excess_cagr_vs_random",
                                                   "excess_daily_nw_t", "max_dd")}))
# benchmark on the same windows
for per, (a, b) in PER.items():
    bm = L.benchmark(None, start=a, end=b)
    out[f"nifty500_{per}"] = {k: bm[k] for k in ("cagr", "total_return", "max_dd")}

# 2) phase-averaged books (5 entry phases), with EW-universe baseline; keep daily series for later stages
series = {}
for per in PER:
    pa, sm, rm, em = phase_avg(S, sc, E, "liq2", H, dict(top_k=20, step=5, cost_bps=50), per, with_ew=True)
    out[f"phaseavg_{per}_c50"] = pa
    series[f"{per}_strat"] = sm
    series[f"{per}_rand"] = rm
    series[f"{per}_ew"] = em
    log("phase-avg", per, short({k: pa[k] for k in ("pa_cagr", "pa_random_cagr", "pa_excess_ann", "pa_nw_t",
                                                       "pa_ew_cagr", "pa_excess_vs_ew_ann", "pa_vs_ew_nw_t",
                                                       "pa_maxdd", "phase_excess")}))
    # calendar-year breakdown of the phase-averaged excess vs random / EW
    df = pd.DataFrame({"s": sm, "r": rm, "e": em})
    by = {}
    for Y, g in df.groupby(df.index.year):
        by[int(Y)] = {"strat": float(np.prod(1 + g.s) - 1), "random": float(np.prod(1 + g.r) - 1),
                      "ew": float(np.prod(1 + g.e) - 1), "ex_vs_random_ann": float((g.s - g.r).mean() * 252),
                      "ex_vs_ew_ann": float((g.s - g.e).mean() * 252), "days": int(len(g))}
    out[f"phaseavg_{per}_by_year"] = by
    log(per, "by year", short(by))
np.savez_compressed(f"{OUT}/pa_series_{job}.npz",
                    **{k: v.values for k, v in series.items()},
                    **{k + "__dates": v.index.values.astype("datetime64[D]").astype(str) for k, v in series.items()})

# 3) learnability of the self-built model vs its own label
pct = np.load(f"{OUT}/label_h20_neumom.npz")["pct"]
xm = L.xs_metrics(sc, pct, E, P, H, binary_target=np.where(np.isnan(pct), np.nan, (pct <= 0.3).astype(float)))
xm_top = L.xs_metrics(sc, pct, E, P, H, binary_target=np.where(np.isnan(pct), np.nan, (pct > 0.7).astype(float)))
out["xs_metrics_vs_label"] = {"ic_and_auc_bottom30_score_low": xm, "auc_top30": {k: v for k, v in xm_top.items()
                                                                                  if "auc" in k}}
log("xs", short(xm))
save(f"s3_repro_{job}", out)
