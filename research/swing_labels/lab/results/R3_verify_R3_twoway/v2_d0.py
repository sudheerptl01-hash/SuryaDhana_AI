"""Verifier v2 (own code): D0 avoid veto (EW elig_base minus PROD bottom 30%) vs the EW universe, phase-averaged
over the 5 weekly entry phases with my own loop over raw L.Sim.run (no rb_cache), DEV and 2026, 50 and 80 bps.
Also: a vol-veto (top-30% vol_20 removed) for the residual-alpha check, with the DEV slope applied out of sample to 2026."""
import json
import sys
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_twoway"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "elig_base", "vol_20"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = F["elig_base"].values.astype(bool)
volsc = -F["vol_20"].values.astype("float64")
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)["prod"].astype("float64")
print("share of elig_base rows 2023+ without finite PROD:",
      float((~np.isfinite(prod[E & (P['date'].values >= np.datetime64('2023-01-01'))])).mean()), flush=True)
del P


def my_nw_t(x, lag=20):
    x = np.asarray(x, float)
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return x.mean() / np.sqrt(s / n)


def phased(score, sq, per, cost):
    a, b = per
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    ser = []
    for k in range(5):
        st = S.run(score, E, 20, step=5, cost_bps=cost, start=str(S.cal[g0 + k]), end_exit=b,
                   select_quantile=sq, sizing="equal")
        ser.append(pd.Series(st["_daily_ret"], index=pd.DatetimeIndex(st["_dates"])))
    common = ser[0].index
    for x in ser[1:]:
        common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in ser], 0), index=common)


def st(r):
    eq = np.cumprod(1 + r.values)
    return {"cagr": float(eq[-1] ** (252 / len(r)) - 1), "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
            "n": int(len(r))}


out = {}
slope_dev = None
for cost in (50, 80):
    for pn, per in (("dev", ("2023-01-01", "2025-12-31")), ("2026", ("2026-01-01", None))):
        d0 = phased(prod, (0.3, 1.0), per, cost)
        ew = phased(np.ones(len(E)), (0.0, 1.0), per, cost)
        vv = phased(volsc, (0.3, 1.0), per, cost)
        c = d0.index.intersection(ew.index).intersection(vv.index)
        y = (d0 - ew).reindex(c).values
        x = (vv - ew).reindex(c).values
        X = np.c_[np.ones(len(c)), x]
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        res = {"D0": st(d0), "EW": st(ew), "VOLVETO": st(vv), "d0_vs_ew_ann": float(y.mean() * 252), "d0_vs_ew_nw_t": float(my_nw_t(y)),
               "volveto_vs_ew_ann": float(x.mean() * 252), "corr": float(np.corrcoef(x, y)[0, 1]), "slope": float(coef[1]),
               "resid_alpha_ann_insample": float(coef[0] * 252), "resid_alpha_t_insample": float(my_nw_t(y - coef[1] * x))}
        if pn == "dev" and cost == 50:
            slope_dev = coef[1]
        if slope_dev is not None:
            z = y - slope_dev * x
            res["resid_alpha_ann_dev_slope"] = float(z.mean() * 252)
            res["resid_alpha_t_dev_slope"] = float(my_nw_t(z))
        out[f"{pn}|c{cost}"] = res
        print(pn, cost, json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}), flush=True)
json.dump(out, open(OUT + "/v2_d0.json", "w"), indent=1)
