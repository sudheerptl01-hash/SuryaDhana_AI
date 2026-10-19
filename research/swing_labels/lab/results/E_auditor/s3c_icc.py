#!/usr/bin/env python3
"""Stage 3c: effective sample size of absolute vs relative labels (h=10).
ICC = share of label variance explained by the date (common market move); design effect
DE_cs = 1 + (m-1)*ICC; overlapping-window design effect DE_t = 1 + 2*sum(rho_k)."""
import numpy as np
import pandas as pd
from common import L, save
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base"])
fw = L.Fwd(P)
R = {}
for h in (10, 20):
    r = L.fwd_return(P, fw, h)
    mf = L.market_fwd(P, h)
    v = F.elig_base.values & np.isfinite(r) & np.isfinite(mf)
    d = P.date.values[v]
    labs = {"abs_gt50": (r > 0.005).astype(float),
            "excess_gt50": ((r - mf) > 0.005).astype(float)}
    df = pd.DataFrame({"d": d, "r": r[v]})
    rk = df.groupby("d").r.rank(pct=True).values
    tmp = np.full(len(r), np.nan); tmp[v] = (rk > 0.7).astype(float)
    labs["xs_top30"] = tmp
    out = {}
    for k, y in labs.items():
        yy = np.where(v, y, np.nan)
        yv = yy[v]
        pm = pd.Series(yv).groupby(d).agg(["mean", "size"])
        pbar = yv.mean()
        icc = np.average((pm["mean"] - pbar) ** 2, weights=pm["size"]) / (pbar * (1 - pbar))
        rho = []
        for lag in range(1, h + 1):
            yl = fw.at(yy, -lag); m = np.isfinite(yy) & np.isfinite(yl)
            rho.append(np.corrcoef(yy[m], yl[m])[0, 1])
        de_t = 1 + 2 * np.sum(rho)
        mbar = pm["size"].mean()
        de_cs = max(1 + (mbar - 1) * icc, 1.0)
        N = int(v.sum())
        out[k] = {"N": N, "base_rate": float(pbar), "icc": float(icc), "lag1_autocorr": float(rho[0]),
                  "DE_time": float(de_t), "DE_cs": float(de_cs), "N_eff": float(N / de_t / de_cs),
                  "N_eff_time_only": float(N / de_t)}
        print(h, k, out[k], flush=True)
    R[f"h{h}"] = out
save("s3c_icc", R)
