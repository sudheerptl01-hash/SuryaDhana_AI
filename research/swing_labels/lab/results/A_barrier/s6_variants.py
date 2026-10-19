"""Stage 6: execution/investability variants for a chosen OOS score (selection 2023-25).
Usage: python3 s6_variants.py <wf_tag>
Variants (all L.portfolio_sim, top_k=20, 2023-01-01..2026-09-10, 50 & 80 bps, random 5 seeds):
  exit decomposition: barrier pt/sl (label geometry), stop-only (pt=99), target-only (sl=99), time h
  short side on fno_proxy with time exit
  time exit with step=h (single sleeve, non-overlapping), max_per_sector=4, min_score gating
"""
import sys
import time

import numpy as np

import s4_eval as E  # reuses loaded P/F/fw + memoized barrier (module runs no tags when argv empty)
from abar import OUT, save_json, update_results

tag = sys.argv[1]
cid = "_".join(tag.split("_")[:3])
h, pt, sl = E.GEOM[cid]
score = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
m_long = E.elig & np.isfinite(score)
m_short = m_long & E.fno
res = {"tag": tag}
t0 = time.time()
res["stop_only"] = E.run_sims(score, m_long, h, 99.0, sl, "long")
print("stop_only", round(time.time() - t0, 1), flush=True)
res["target_only"] = E.run_sims(score, m_long, h, pt, 99.0, "long")
print("target_only", round(time.time() - t0, 1), flush=True)
res["short_time_fno"] = E.run_sims(score, m_short, h, pt, sl, "short", exit_rule="time")
res["long_time_step_h"] = E.run_sims(score, m_long, h, pt, sl, "long", exit_rule="time", step=h)
res["long_time_sector4"] = {}
for c in (50, 80):
    r = E.L.portfolio_sim(score, m_long, E.P, E.F, E.fw, h, step=5, top_k=20, side="long", exit_rule="time",
                          cost_bps=c, start=E.START, end=E.END, max_per_sector=4)
    res["long_time_sector4"][f"model_{c}"] = E.slim(r, 5)
# gating: only take names whose P(+1) >= 0.5 (absolute-probability use of the label)
if "binary" in tag:
    for thr in (0.5,):
        res[f"long_time_minscore{thr}"] = {}
        res[f"long_barrier_minscore{thr}"] = {}
        for c in (50, 80):
            r = E.L.portfolio_sim(score, m_long, E.P, E.F, E.fw, h, step=5, top_k=20, side="long", exit_rule="time",
                                  cost_bps=c, start=E.START, end=E.END, min_score=thr)
            res[f"long_time_minscore{thr}"][f"model_{c}"] = E.slim(r, 5)
            r = E.L.portfolio_sim(score, m_long, E.P, E.F, E.fw, h, step=5, top_k=20, side="long", exit_rule="barrier",
                                  pt=pt, sl=sl, cost_bps=c, start=E.START, end=E.END, min_score=thr)
            res[f"long_barrier_minscore{thr}"][f"model_{c}"] = E.slim(r, 5)
        # share of signal dates where >=1 / >=20 names pass
        import pandas as pd
        d = E.dates[m_long]
        s = score[m_long]
        g = pd.DataFrame({"d": d, "ok": s >= 0.5}).groupby("d").ok.sum()
        g = g[g.index >= np.datetime64(E.START)]
        res["minscore0.5_coverage"] = {"share_dates_ge1": float((g >= 1).mean()), "share_dates_ge20": float((g >= 20).mean()),
                                       "median_names": float(g.median())}
save_json(f"{OUT}/variants_{tag}.json", res)
update_results(f"variants_{tag}", res)
print("done", round(time.time() - t0, 1))
