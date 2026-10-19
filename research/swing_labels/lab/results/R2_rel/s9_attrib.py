"""Stage 9: light factor attribution of candidate books (is the edge a boring factor tilt?).

Factor returns (same universe, same Sim mechanics h=20 step 5, 50 bps both legs so costs ~cancel):
  LS_c = EW book of the top 30% by characteristic c  minus  EW book of the bottom 30%   (daily MTM)
  c in {vol_20 (high-low), mom_12_1, log_turn20 (liquid-illiquid), mom_5 (winners-losers 5d),
        beta_60, dist_sma200}
Regress the candidate's daily excess-vs-random (K20 step 5 50 bps, and avoid30 vs random-70%) on the
6 factor series (OLS); alpha (annualised) with Newey-West t (lag h), R^2 and betas; dev and holdout.
Usage: python3 s9_attrib.py tag1 tag2 ...
"""
import sys
import time

import numpy as np

from common import OUT, L, save

tags = sys.argv[1:]
t0 = time.time()
CH = ["vol_20", "mom_12_1", "log_turn20", "mom_5", "beta_60", "dist_sma200"]
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"] + CH)
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = np.load(f"{OUT}/meta.npz")["E"]
PER = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
H = 20


def nw_reg(y, X, lag):
    """OLS with Newey-West (Bartlett) standard errors."""
    X = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n = len(y)
    XtX_inv = np.linalg.inv(X.T @ X)
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        G = Xe[k:].T @ Xe[:-k] / n
        Sm += w * (G + G.T)
    V = n * XtX_inv @ Sm @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - e.var() / y.var()
    return b, b / se, r2


out = {}
for per, kw in PER.items():
    fac = {}
    for c in CH:
        x = F[c].values.astype("float64")
        hi = S.run(x, E, H, step=5, cost_bps=50, select_quantile=(0.7, 1.0), sizing="equal", **kw)
        lo = S.run(-x, E, H, step=5, cost_bps=50, select_quantile=(0.7, 1.0), sizing="equal", **kw)
        fac[c] = hi["_daily_ret"] - lo["_daily_ret"]
        print(per, c, "LS ann", round(fac[c].mean() * 252, 4), round(time.time() - t0, 1), flush=True)
    Xf = np.column_stack([fac[c] for c in CH])
    out[f"factor_ls_ann_{per}"] = {c: float(fac[c].mean() * 252) for c in CH}
    out[f"factor_corr_{per}"] = np.corrcoef(Xf.T).round(3).tolist()
    for mode, base in (("K20_s5", dict(top_k=20, step=5, cost_bps=50)),
                       ("avoid30_s5", dict(step=5, cost_bps=50, select_quantile=(0.3, 1.0), sizing="equal"))):
        rb = S.random_band(E, H, **base, **kw)
        for tag in tags:
            sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
            h = int(tag.split("_")[0][1:])
            st = S.run(sc, E, h, **base, **kw)
            if h != H:
                continue
            y = st["_daily_ret"] - rb["_daily_ret_mean"]
            b, t, r2 = nw_reg(y, Xf, H)
            out[f"{tag}_{mode}_{per}"] = {"excess_ann": float(y.mean() * 252), "alpha_ann": float(b[0] * 252),
                                          "alpha_nw_t": float(t[0]), "r2": float(r2),
                                          "betas": {c: float(b[i + 1]) for i, c in enumerate(CH)},
                                          "beta_t": {c: float(t[i + 1]) for i, c in enumerate(CH)}}
            print(tag, mode, per, {k: (round(v, 3) if isinstance(v, float) else {a: round(z, 2) for a, z in v.items()})
                                   for k, v in out[f"{tag}_{mode}_{per}"].items()}, flush=True)
save("s9_attrib", out)
