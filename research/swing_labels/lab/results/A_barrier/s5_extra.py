"""Stage 5 extras: (a) same-bar ambiguity (both barriers inside one bar) share for
shortlisted geometries; (b) unconditional executable time-exit net per trade vs
barrier-exit net per trade (what the exit rule itself costs), by period;
(c) barrier hit-rate dependence on volatility (atr tercile) to check ATR scaling.
"""
import numpy as np
import pandas as pd

from abar import L, OUT, FwdMats, barrier, tau_label, geom, update_results, load_base

P, F, fw = load_base()
elig = F["elig_base"].values.astype(bool)
rows = np.flatnonzero(elig)
M = FwdMats(P, fw, rows)
atr = F["atr_pct"].values.astype("float64")[rows]
yr = pd.DatetimeIndex(P["date"].values[rows]).year.values
per = {"2021_22": yr <= 2022, "2023_25": (yr >= 2023) & (yr <= 2025), "2026": yr == 2026}
SH = {"B20_f2.0_2.0": (20, "fix", 2.0, 2.0), "B20_f3.0_1.5": (20, "fix", 3.0, 1.5),
      "B10_f2.0_1.5": (10, "fix", 2.0, 1.5), "B15_f2.0_2.0": (15, "fix", 2.0, 2.0),
      "B10_s0.75_0.75": (10, "sqrt", 0.75, 0.75), "B10_s1.5_1.0": (10, "sqrt", 1.5, 1.0)}
out = {}
# (b) time-exit baseline
e = M.entry
for h in (5, 10, 15, 20):
    r = M.C[:, h - 1] / e - 1
    v = M.ok[h] & np.isfinite(r)
    out[f"time_exit_h{h}"] = {p: {"net50_mean": float(r[v & m].mean() - 0.005), "net50_median": float(np.median(r[v & m]) - 0.005),
                                  "p_net_pos": float((r[v & m] > 0.005).mean())} for p, m in per.items()}
terc = pd.qcut(atr, 3, labels=False)
for cid, (h, kind, a, b) in SH.items():
    pm, sm = geom(kind, a, b, h)
    bb = barrier(M, pm * atr, sm * atr, h, "long")
    v = bb["valid"]
    # ambiguity: first event bar where low<=stop and high>=target both (non-gap)
    tgt, stp = e * (1 + pm * atr), e * (1 - sm * atr)
    k = bb["k"].astype(int) - 1
    rr = np.arange(len(e))
    hi_k, lo_k, o_k = M.H[rr, k], M.Lo[rr, k], M.O[rr, k]
    amb = v & (bb["touch"] == -1) & (hi_k >= tgt) & (o_k > stp)
    gap_stop = v & (bb["touch"] == -1) & (o_k <= stp)
    gap_tgt = v & (bb["touch"] == 1) & (o_k >= tgt)
    o = {"ambiguous_same_bar_share": float(amb.sum() / v.sum()),
         "gap_stop_share": float(gap_stop.sum() / v.sum()), "gap_tgt_share": float(gap_tgt.sum() / v.sum()),
         "p1_if_ambiguous_resolved_optimistic": float(((tau_label(bb, 50) == 1) | amb)[v].mean()),
         "p1_pessimistic": float((tau_label(bb, 50) == 1)[v].mean())}
    net = bb["ret"] - 0.005
    for p, m in per.items():
        mm = v & m
        o[f"barrier_net50_{p}"] = float(net[mm].mean())
        o[f"barrier_net50_perday_{p}"] = float(net[mm].mean() / bb["k"][mm].mean())
        o[f"barrier_gross_perday_{p}"] = float((net[mm] + 0.005).mean() / bb["k"][mm].mean())
        rt = M.C[:, h - 1] / e - 1
        o[f"time_gross_perday_{p}"] = float(np.nanmean(rt[mm]) / h)
    lab = tau_label(bb, 50)
    o["p1_by_atr_tercile"] = {int(t): float((lab[v & (terc == t)] == 1).mean()) for t in range(3)}
    o["ptgt_by_atr_tercile"] = {int(t): float((bb["touch"][v & (terc == t)] == 1).mean()) for t in range(3)}
    o["psl_by_atr_tercile"] = {int(t): float((bb["touch"][v & (terc == t)] == -1).mean()) for t in range(3)}
    out[cid] = o
    print(cid, {k_: (round(v_, 4) if isinstance(v_, float) else v_) for k_, v_ in o.items()}, flush=True)
for h in (5, 10, 15, 20):
    print(h, out[f"time_exit_h{h}"])
update_results("extras_ambiguity_exitcost", out)
