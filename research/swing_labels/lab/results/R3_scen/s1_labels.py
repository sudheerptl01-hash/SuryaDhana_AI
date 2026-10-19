#!/usr/bin/env python3
"""R3_scen stage 1: label zoo for h in {5,10,15,20} -> labels_h{h}.npz (row-aligned with panel).

r      = open[t+1] -> close[t+h] adjusted (L.fwd_return; NaN unless fw.ok(h))
cc     = close[t] -> close[t+h] adjusted, same rows as r (close-entry, the phantom variant)
old    = raw close[t] -> raw close[t+h] > 0 within segment, NaN -> 0 (atlas_v2 definition of the repo label)
cs     = clean sign: r > 0 (NaN where r undefined)
three  = +1 r > +50 bps / -1 r < -50 bps / 0
b22/b315 = triple barrier (2.0/2.0, 3.0/1.5 ATR, x sqrt(h/20)), time exit dead zone +-50 bps
pct_neu / pct_neumom = R2_rel recipe, peer group elig_base; DUAL on XR_neumom
h=20 also: pct_neu_none / pct_neumom_none re-ranked among all valid rows (extra variant 1)
"""
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_scen")
L = C.L
OUT = C.OUT
T0 = time.time()

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "raw_close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "atr_pct", "beta_60", "vol_20", "log_turn20", "mom_12_1"])
fw = L.Fwd(P)
n = len(P)
E = F["elig_base"].values.astype(bool)
LB = P["label_block"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
beta_s = 0.5 * np.clip(F["beta_60"].values.astype("float64"), 0.0, 3.0) + 0.5
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
mom = F["mom_12_1"].values.astype("float64")
C.log("loaded", n)


def date_groups(idx):
    order = np.argsort(dates[idx], kind="stable")
    idx = idx[order]
    d = dates[idx]
    b = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    e = np.r_[b[1:], len(idx)]
    return idx, b, e


def rel_labels(r, V, fill_regressors=False):
    """R2_rel recipe (s1_labels.py) re-implemented: per-date winsorise 1/99 over V, OLS residual on
    [1, beta_s, vol_20, log_turn20] (+ mom_12_1 with NaN -> date median), percentile rank per date."""
    idx, b, e = date_groups(np.flatnonzero(V))
    rw = np.full(n, np.nan)
    mom_f = mom.copy()
    regs = [beta_s.copy(), vol.copy(), lt.copy()]
    for s_, t_ in zip(b, e):
        ii = idx[s_:t_]
        y = r[ii]
        lo, hi = np.percentile(y, [1, 99])
        rw[ii] = np.clip(y, lo, hi)
        mm = mom[ii]
        if np.isnan(mm).any():
            med = np.nanmedian(mm) if np.isfinite(mm).any() else 0.0
            mom_f[ii] = np.where(np.isnan(mm), med, mm)
        if fill_regressors:
            for a in regs:
                x = a[ii]
                if np.isnan(x).any():
                    med = np.nanmedian(x) if np.isfinite(x).any() else 0.0
                    a[ii] = np.where(np.isnan(x), med, x)
    out = {}
    for nt in ("neu", "neumom"):
        cols = regs + ([mom_f] if nt == "neumom" else [])
        resid = np.full(n, np.nan)
        for s_, t_ in zip(b, e):
            ii = idx[s_:t_]
            if len(ii) < 30:
                continue
            y = rw[ii]
            X = np.column_stack([np.ones(len(ii))] + [c[ii] for c in cols])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid[ii] = y - X @ coef
        out[nt] = pd.Series(resid).groupby(dates).rank(pct=True, method="average").values
    return out


def cls3(p):
    c = np.where(p > 0.7, 1.0, np.where(p <= 0.3, -1.0, 0.0))
    c[~np.isfinite(p)] = np.nan
    return c


TOUCH = {"pt": 1, "sl": -1, "time": 0}
checks = {}
for h in (5, 10, 15, 20):
    t1 = time.time()
    r = L.fwd_return(P, fw, h)
    cl = P["close"].values.astype("float64")
    cc = fw.at(cl, h) / cl - 1
    cc[~np.isfinite(r)] = np.nan
    rc = P["raw_close"].values.astype("float64")
    old_fwd = fw.at(rc, h) / rc - 1                    # within segment only (kinder than the repo)
    old = (old_fwd > 0).astype(np.float64)             # NaN > 0 is False -> 0 (the repo bug)
    cs = np.where(np.isfinite(r), (r > 0).astype(float), np.nan)
    three = np.where(np.isfinite(r), np.where(r > 0.005, 1.0, np.where(r < -0.005, -1.0, 0.0)), np.nan)
    out = {"r": r, "cc": cc, "old": old, "old_fwd": old_fwd, "cs": cs, "three": three}
    for nm, (pt, sl) in (("b22", (2.0, 2.0)), ("b315", (3.0, 1.5))):
        sc = np.sqrt(h / 20)
        tb = L.barrier_labels(P, F, fw, h, pt * sc, sl * sc, tau_bps=50)
        out[nm] = tb["label"]
        out[nm + "ret"] = tb["ret"]
        tc = np.full(n, -9, dtype=np.int8)
        for k_, v_ in TOUCH.items():
            tc[tb["touch"] == k_] = v_
        out[nm + "touch"] = tc
        del tb
    V = E & np.isfinite(r)
    rl = rel_labels(r, V)
    out["pct_neu"], out["pct_neumom"] = rl["neu"], rl["neumom"]
    cn = cls3(rl["neumom"])
    dual = np.where((cn == 1) & (r > 0.005), 1.0, np.where((cn == -1) & (r < -0.005), -1.0, 0.0))
    dual[~np.isfinite(cn) | ~np.isfinite(r)] = np.nan
    out["dual"] = dual
    if h == 20:
        Vn = np.isfinite(r) & ~LB
        rn = rel_labels(r, Vn, fill_regressors=True)
        out["pct_neu_none"], out["pct_neumom_none"] = rn["neu"], rn["neumom"]
        cnn = cls3(rn["neumom"])
        dn = np.where((cnn == 1) & (r > 0.005), 1.0, np.where((cnn == -1) & (r < -0.005), -1.0, 0.0))
        dn[~np.isfinite(cnn) | ~np.isfinite(r)] = np.nan
        out["dual_none"] = dn
    # ---- cross-checks against round-2 label files (same definitions)
    ck = {}
    if h in (10, 15, 20):
        z = np.load(f"{LAB}/results/R2_rel/labels_h{h}.npz")
        for k_ in ("neu", "neumom"):
            p2 = z[f"pct_{k_}"].astype("float64")
            p1 = out[f"pct_{k_}"]
            bb = np.isfinite(p1) & np.isfinite(p2)
            ck[f"pct_{k_}_vs_R2_rel"] = {"finite_mismatch": int((np.isfinite(p1) != np.isfinite(p2)).sum()),
                                         "max_abs_diff": float(np.abs(p1[bb] - p2[bb]).max()),
                                         "class_disagree": float((cls3(p1[bb]) != cls3(p2[bb])).mean())}
        r2 = z["r"].astype("float64")
        bb = np.isfinite(r) & np.isfinite(r2)
        ck["r_vs_R2_rel_max_abs_diff"] = float(np.abs(r[bb] - r2[bb]).max())
    if h == 20:
        zd = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")
        pdv = zd["pct"]
        bb = np.isfinite(pdv) & np.isfinite(out["pct_neumom"])
        ck["pct_neumom_vs_devil"] = {"finite_mismatch": int((np.isfinite(pdv) != np.isfinite(out["pct_neumom"])).sum()),
                                     "max_abs_diff": float(np.abs(pdv[bb] - out["pct_neumom"][bb]).max())}
    checks[f"h{h}"] = ck
    C.log("h", h, "built in", round(time.time() - t1, 1), "s", ck)
    np.savez(f"{OUT}/labels_h{h}.npz", **{k: (v if v.dtype == np.int8 else v.astype(np.float32)) for k, v in out.items()})
    del out, r, cc, old, old_fwd, cs, three, rl, cn, dual, V
C.save("s1_label_checks", checks)
C.log("done")
