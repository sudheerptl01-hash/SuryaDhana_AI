"""Stage 6b: persistence-matched random null for the long top-K book.

A skill-less score with the SAME time persistence as the model's score: per-entity
  s = sqrt(w)*c_entity + sqrt(1-w)*AR1(rho)    (Gaussian; c constant per entity)
autocorr(L) = w + (1-w)*rho^L. w and rho are fitted to the model's within-entity rank-score
autocorrelation (lags 5 and 120 on elig rows). 40 seeds -> distribution of excess-vs-random CAGR and NW t
(same 5-seed iid baseline as compare). This calibrates the luck band for a rotating model.
Usage: python3 s6b_matched_null.py tag [K] [step]
"""
import sys
import time

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from common import OUT, L, save

tag = sys.argv[1]
K = int(sys.argv[2]) if len(sys.argv) > 2 else 20
step = int(sys.argv[3]) if len(sys.argv) > 3 else 5
h = int(tag.split("_")[0][1:])
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = np.load(f"{OUT}/meta.npz")["E"]
dates = P["date"].values.astype("datetime64[D]")
sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
rk = pd.Series(np.where(E & np.isfinite(sc), sc, np.nan)).groupby(dates).rank(pct=True).values
ac = {}
for lag in (1, 5, 20, 60, 120, 250):
    a = fw.at(rk, -lag)
    ok = np.isfinite(rk) & np.isfinite(a)
    ac[lag] = float(np.corrcoef(rk[ok], a[ok])[0, 1])
w = max(min(ac[250], 0.95), 0.0)
rho5 = max((ac[5] - w) / (1 - w), 1e-6)
rho = rho5 ** (1 / 5)
print("autocorr", ac, "w", round(w, 3), "rho_daily", round(rho, 4), flush=True)
ent = P["entity"].values
first = np.r_[True, ent[1:] != ent[:-1]]
ent_code = np.unique(ent, return_inverse=True)[1]
out = {"autocorr_model_rank": ac, "w": w, "rho_daily": rho}
for per, kw in {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]),
                "hold": dict(start="2026-01-01", end_exit=None)}.items():
    base = dict(top_k=K, step=step, cost_bps=50, **kw)
    rb = S.random_band(E, h, **base)
    stm = S.run(sc, E, h, **base)
    mex = stm["cagr"] - rb["cagr_mean"]
    mt = L.nw_t(stm["_daily_ret"] - rb["_daily_ret_mean"], lag=h)
    res, achk = [], []
    for s in range(40):
        g = np.random.default_rng(5000 + s)
        c = g.standard_normal(ent_code.max() + 1)[ent_code]
        eps = g.standard_normal(len(P)) * np.sqrt(1 - rho ** 2)
        eps[first] = g.standard_normal(first.sum())   # stationary start for each entity
        x = lfilter([1.0], [1.0, -rho], eps)
        # remove bleed across entity boundaries: subtract the carried component rho^k * (prev tail)
        # (negligible after ~5/(1-rho) rows; eligibility needs >=120 seasoned bars)
        z = np.sqrt(w) * c + np.sqrt(1 - w) * x
        st = S.run(z, E, h, **base)
        res.append((st["cagr"] - rb["cagr_mean"], L.nw_t(st["_daily_ret"] - rb["_daily_ret_mean"], lag=h)))
        if s == 0:
            zr = pd.Series(np.where(E, z, np.nan)).groupby(dates).rank(pct=True).values
            for lag in (5, 120):
                a = fw.at(zr, -lag)
                ok = np.isfinite(zr) & np.isfinite(a)
                achk.append(float(np.corrcoef(zr[ok], a[ok])[0, 1]))
    r = np.array(res)
    out[per] = {"model_excess": mex, "model_nw_t": mt, "null_autocorr_lag5_lag120": achk,
                "null_excess_mean": float(r[:, 0].mean()), "null_excess_sd": float(r[:, 0].std()),
                "null_excess_p95": float(np.percentile(r[:, 0], 95)), "null_excess_max": float(r[:, 0].max()),
                "null_t_mean": float(r[:, 1].mean()), "null_t_sd": float(r[:, 1].std()),
                "null_t_p95": float(np.percentile(r[:, 1], 95)), "null_t_max": float(r[:, 1].max()),
                "model_excess_pctile_in_null": float((r[:, 0] < mex).mean()),
                "model_excess_z_vs_null": float((mex - r[:, 0].mean()) / r[:, 0].std()),
                "model_t_deflated_by_null_sd": float(mt / r[:, 1].std())}
    print(per, out[per], round(time.time() - t0, 1), flush=True)
save(f"s6b_matched_null_{tag}_K{K}_s{step}", out)
