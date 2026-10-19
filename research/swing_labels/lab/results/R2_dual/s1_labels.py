"""Stage 1: build relative (XR_neu), absolute, path (A2 barrier) and DUAL labels for h in {10, 20}.

r_h   = open[t+1] -> close[t+h] (adjusted), NaN unless fw.ok(h)            [L.fwd_return]
m_h   = Nifty 500 open on the row's t+1 date -> close on the row's t+h date (same executable window)
resid = per-date OLS residual (r winsorised 1/99 per date) on [1, 0.5*beta_60+0.5, vol_20, log_turn20]
        among U = elig_base rows with finite r (U already excludes ETFs/MF units in lab v2)
pct   = per-date percentile of resid among the same rows
REL   = +1 pct>0.7 / -1 pct<=0.3 / 0                                       (pure relative, XR_neu)
ABS   = +1 r>+50bp / -1 r<-50bp / 0                                         (pure absolute, cost dead zone)
BAR   = L.barrier_labels(h=20, pt=3.0, sl=1.5 ATR, tau=50bp)               (pure absolute, path; A2)
DUAL  = +1 if REL=+1 and r>+tau ; -1 if REL=-1 and r<-tau ; else 0 (tau = 50 bp)   [label-side AND]
DUALP = +1 if REL=+1 and BAR=+1 ; -1 if REL=-1 and BAR=-1 ; else 0                 [path version]
All NaN where the underlying window is undefined; filters never change values.
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, neutral_resid, xs_pct, cls3

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "atr_pct", "beta_60", "vol_20", "log_turn20"])
fw = L.Fwd(P)
U = F["elig_base"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
mk = L.market_series("Nifty 500").reindex(pd.DatetimeIndex(cal)).ffill()
mo, mc = mk["open"].values, mk["close"].values
pos = np.searchsorted(cal, dates).astype(float)
beta_s = 0.5 * F["beta_60"].values.astype("float64") + 0.5
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
np.savez_compressed(f"{OUT}/meta.npz", U=U)
print("loaded", round(time.time() - t0, 1), flush=True)

diag = {"U_rows": int(U.sum())}
for h in (10, 20):
    r = L.fwd_return(P, fw, h)
    p1, ph = fw.at(pos, 1), fw.at(pos, h)
    okm = np.isfinite(p1) & np.isfinite(ph) & np.isfinite(r)
    m = np.full(len(P), np.nan)
    m[okm] = mc[ph[okm].astype(int)] / mo[p1[okm].astype(int)] - 1
    V = U & np.isfinite(r)
    resid = neutral_resid(r, dates, V, [beta_s, vol, lt])
    pct = xs_pct(resid, dates, V)
    REL = cls3(pct, 0.3)
    ABS = np.where(r > 0.005, 1.0, np.where(r < -0.005, -1.0, 0.0))
    ABS[~np.isfinite(r)] = np.nan
    DUAL = np.where((REL == 1) & (r > 0.005), 1.0, np.where((REL == -1) & (r < -0.005), -1.0, 0.0))
    DUAL[~np.isfinite(REL) | ~np.isfinite(r)] = np.nan
    out = {"r": r, "m": m, "resid": resid, "pct": pct, "REL": REL, "ABS": ABS, "DUAL": DUAL}
    if h == 20:
        b = L.barrier_labels(P, F, fw, h=20, pt=3.0, sl=1.5, tau_bps=50)
        BAR = b["label"]
        out["BAR"] = BAR
        out["BAR_ret"] = b["ret"]
        out["BAR_k"] = b["k"]
        DUALP = np.where((REL == 1) & (BAR == 1), 1.0, np.where((REL == -1) & (BAR == -1), -1.0, 0.0))
        DUALP[~np.isfinite(REL) | ~np.isfinite(BAR)] = np.nan
        out["DUALP"] = DUALP
        # alternative barrier geometries for the sensitivity map (event rates only)
        for nm, (pt_, sl_) in {"BAR22": (2.0, 2.0), "BAR21": (2.0, 1.0)}.items():
            out[nm] = L.barrier_labels(P, F, fw, h=20, pt=pt_, sl=sl_, tau_bps=50)["label"]
    np.savez_compressed(f"{OUT}/labels_h{h}.npz", **{k: np.asarray(a, dtype=np.float32) for k, a in out.items()})
    d = {"valid_U_rows": int(V.sum()), "valid_share_of_U": float(V.sum() / U.sum()),
         "resid_defined_share_of_valid": float(np.isfinite(resid[V]).mean()),
         "corr_r_resid": float(np.corrcoef(r[V & np.isfinite(resid)], resid[V & np.isfinite(resid)])[0, 1])}
    for k in ("REL", "ABS", "DUAL") + (("BAR", "DUALP") if h == 20 else ()):
        x = out[k][U]
        x = x[np.isfinite(x)]
        d[k] = {"n": int(len(x)), "+1": float((x == 1).mean()), "0": float((x == 0).mean()),
                "-1": float((x == -1).mean())}
    diag[f"h{h}"] = d
    print(h, "done", round(time.time() - t0, 1), d, flush=True)
save("s1_label_build", diag)
