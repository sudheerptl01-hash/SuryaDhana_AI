"""J_pm check 2: execution realism. Same selected book (h20_neumom_RANK, K20, step 5, 50 bps), entry at
open[t+1] (lab default) vs entry at vwap[t+1] (what a larger book gets when it works the order over day 1).
Random baseline gets the same entry rule. DEV and 2026, phase-averaged over the 5 calendar phases."""
import sys, json, time, numpy as np, pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB); import lablib as L
R = LAB + "/results"
P = L.load_panel(["date", "entity", "seg_break", "label_block", "open", "high", "low", "close", "vwap"])
F = L.load_features(["elig_base"])
mask = F.elig_base.values.astype(bool)
fw = L.Fwd(P)
sc = np.load(R + "/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
P2 = P.copy(); v = P2["vwap"].values.astype("float64")
P2["open"] = np.where(np.isfinite(v) & (v > 0), v, P2["open"].values)
S_open = L.Sim(P, None, fw); S_vwap = L.Sim(P2, None, fw)
cal = S_open.cal
out = {}
t0 = time.time()
for win, kw in {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}.items():
    for name, S in (("open", S_open), ("vwap", S_vwap)):
        sm_l, rm_l, ex_l = [], [], []
        dates_ref = None
        for ph in range(5):
            g0 = int(np.searchsorted(cal, np.datetime64(kw["start"]))) + ph
            st = str(cal[g0])
            st_run = S.run(sc, mask, 20, step=5, top_k=20, cost_bps=50.0, start=st, end_exit=kw["end_exit"])
            rb = S.random_band(mask, 20, seeds=(1, 2, 3), step=5, top_k=20, cost_bps=50.0, start=st, end_exit=kw["end_exit"])
            s = pd.Series(st_run["_daily_ret"], index=st_run["_dates"]); r = pd.Series(rb["_daily_ret_mean"], index=rb["_dates"])
            sm_l.append(s); rm_l.append(r); ex_l.append(st_run["cagr"] - rb["cagr_mean"])
        idx = sm_l[-1].index
        for s in sm_l: idx = idx.intersection(s.index)
        sm = np.mean([s.loc[idx].values for s in sm_l], 0); rm = np.mean([r.loc[idx].values for r in rm_l], 0)
        yrs = (idx[-1] - idx[0]).days / 365.25
        eq = np.cumprod(1 + sm)
        out[f"{win}_{name}"] = dict(pa_cagr=float(eq[-1] ** (1 / yrs) - 1), pa_random_cagr=float(np.prod(1 + rm) ** (1 / yrs) - 1),
                                    pa_excess_ann=float((sm - rm).mean() * 252), pa_nw_t=float(L.nw_t(sm - rm, lag=20)),
                                    pa_maxdd=float((eq / np.maximum.accumulate(eq) - 1).min()),
                                    phase_excess=[round(float(x), 4) for x in ex_l])
        print(win, name, out[f"{win}_{name}"], f"{time.time()-t0:.0f}s", flush=True)
json.dump(out, open(R + "/J_pm/c2_vwap.json", "w"), indent=1)
