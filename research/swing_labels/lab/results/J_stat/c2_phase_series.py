"""J_stat check 2: rebuild the phase-averaged (daily-staggered) daily series for the leading h=20 books
so we can (a) test the DEV excess under longer-memory dependence (NW lags 20..250, moving-block bootstrap),
(b) do leave-one-year-out, (c) measure MODEL NOISE as the paired difference between near-identical models
(R2_rel neu RANK with clipped beta vs R2_dual REL with unclipped beta; label corr 0.99986).
Saves the series to pa_series.npz; statistics are computed in c3."""
import sys
import time
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = np.load(f"{LAB}/results/R2_rel/meta.npz")["E"]
cal = S.cal
SC = {
    "neumom_RANK": f"{LAB}/results/R2_rel/wf_h20_neumom_RANK.npz",
    "neu_RANK": f"{LAB}/results/R2_rel/wf_h20_neu_RANK.npz",
    "dual_REL": f"{LAB}/results/R2_dual/wf_M_REL.npz",
    "neumom_T30": f"{LAB}/results/R2_rel/wf_h20_neumom_T30.npz",
}
scores = {}
for k, f in SC.items():
    z = np.load(f)
    key = "score" if "score" in z.files else z.files[0]
    scores[k] = z[key].astype("float64")
    print(k, z.files, scores[k].shape, flush=True)
h, step = 20, 5
PER = {"dev": L.DEV, "hold": ("2026-01-01", None)}
out = {}
for per, (a, b) in PER.items():
    g0 = int(np.searchsorted(cal, np.datetime64(a)))
    series = {}
    for k in range(step):
        kw = dict(step=step, cost_bps=50, start=str(cal[g0 + k]), end_exit=b)
        for nm, sc in scores.items():
            st = S.run(sc, E, h, top_k=20, **kw)
            series.setdefault(f"long_{nm}", []).append(pd.Series(st["_daily_ret"], index=st["_dates"]))
        rb = S.random_band(E, h, top_k=20, **kw)
        series.setdefault("long_random", []).append(pd.Series(rb["_daily_ret_mean"], index=rb["_dates"]))
        for nm in ("neumom_RANK", "neumom_T30"):
            av = S.run(scores[nm], E, h, select_quantile=(0.3, 1.0), sizing="equal", **kw)
            series.setdefault(f"avoid_{nm}", []).append(pd.Series(av["_daily_ret"], index=av["_dates"]))
        ew = S.run(np.zeros(len(E)), E, h, select_quantile=(0.0, 1.0), sizing="equal", **kw)
        series.setdefault("ew", []).append(pd.Series(ew["_daily_ret"], index=ew["_dates"]))
        print(per, "phase", k, "done", round(time.time() - t0, 1), "s", flush=True)
    common = None
    for lst in series.values():
        for x in lst:
            common = x.index if common is None else common.intersection(x.index)
    for nm, lst in series.items():
        out[f"{per}__{nm}"] = np.mean([x.reindex(common).values for x in lst], 0)
    out[f"{per}__dates"] = np.array([str(d)[:10] for d in common])
np.savez(f"{LAB}/results/J_stat/pa_series.npz", **out)
print("saved", round(time.time() - t0, 1), "s")
