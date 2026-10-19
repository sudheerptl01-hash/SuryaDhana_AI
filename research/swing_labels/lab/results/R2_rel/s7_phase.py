"""Stage 7: calendar-phase robustness. The Sim signal calendar starts at `start` and takes every
step-th trading day, so a step-10 book only ever trades 1 of 10 possible phases. We shift the start by
k = 0..step-1 trading days (random baseline shifted identically), and report the distribution of the
excess over phases plus the PHASE-AVERAGED book (mean of the daily returns of all phases = a book that
staggers entries every day), whose excess NW t is the phase-robust statistic.
Usage: python3 s7_phase.py tag1 [tag2 ...]
configs: long K20 step 5 / step 10; long K50 step 10; avoid (0.3,1) equal step 5 / step 10; 50 bps; liq2
"""
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, save

tags = sys.argv[1:]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = np.load(f"{OUT}/meta.npz")["E"]
cal = S.cal
PER = {"dev": (L.DEV[0], L.DEV[1]), "hold": ("2026-01-01", None)}
CFGS = {"K20_s5": dict(top_k=20, step=5), "K20_s10": dict(top_k=20, step=10), "K50_s10": dict(top_k=50, step=10),
        "avoid30_s5": dict(step=5, select_quantile=(0.3, 1.0), sizing="equal"),
        "avoid30_s10": dict(step=10, select_quantile=(0.3, 1.0), sizing="equal")}
rb_cache = {}
for tag in tags:
    h = int(tag.split("_")[0][1:])
    sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    out = {}
    for cname, ckw in CFGS.items():
        for per, (a, b) in PER.items():
            g0 = int(np.searchsorted(cal, np.datetime64(a)))
            ex, tt, sd, rd = [], [], [], []
            for k in range(ckw["step"]):
                kw = dict(ckw, cost_bps=50, start=str(cal[g0 + k]), end_exit=b)
                st = S.run(sc, E, h, **kw)
                key = (h, cname, per, k)
                if key not in rb_cache:
                    rb_cache[key] = S.random_band(E, h, **kw)
                rb = rb_cache[key]
                n = min(len(st["_daily_ret"]), len(rb["_daily_ret_mean"]))
                ex.append(st["cagr"] - rb["cagr_mean"])
                tt.append(L.nw_t(st["_daily_ret"][:n] - rb["_daily_ret_mean"][:n], lag=h))
                sd.append(pd.Series(st["_daily_ret"], index=st["_dates"]))
                rd.append(pd.Series(rb["_daily_ret_mean"], index=rb["_dates"]))
            # align phases on the COMMON calendar dates (each phase starts k days later and may end
            # earlier); the phase-average is a book that staggers entries on every day of the cycle
            common = sd[0].index
            for x in sd + rd:
                common = common.intersection(x.index)
            sm = np.mean([x.reindex(common).values for x in sd], 0)
            rm = np.mean([x.reindex(common).values for x in rd], 0)
            n = len(common)
            yrs = n / 252
            out[f"{cname}_{per}"] = {
                "phase_excess_mean": float(np.mean(ex)), "phase_excess_min": float(np.min(ex)),
                "phase_excess_max": float(np.max(ex)), "phase_excess_sd": float(np.std(ex)),
                "phase_t_mean": float(np.mean(tt)), "phase_t_min": float(np.min(tt)), "phase_t_max": float(np.max(tt)),
                "share_phases_positive": float(np.mean(np.array(ex) > 0)),
                "phaseavg_cagr": float(np.prod(1 + sm) ** (1 / yrs) - 1),
                "phaseavg_random_cagr": float(np.prod(1 + rm) ** (1 / yrs) - 1),
                "phaseavg_excess_ann": float((sm - rm).mean() * 252),
                "phaseavg_nw_t": L.nw_t(sm - rm, lag=h),
                "phaseavg_sharpe": float(sm.mean() / sm.std() * np.sqrt(252)),
                "phaseavg_maxdd": float((np.cumprod(1 + sm) / np.maximum.accumulate(np.cumprod(1 + sm)) - 1).min()),
                "n_phases": ckw["step"]}
            print(tag, cname, per, {k: round(v, 3) for k, v in out[f"{cname}_{per}"].items()},
                  round(time.time() - t0, 1), flush=True)
    save(f"s7_phase_{tag}", out)
