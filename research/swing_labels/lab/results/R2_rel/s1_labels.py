"""Stage 1: relative-label targets on lab v2 for h in {10,15,20}.

r_h   = open[t+1] -> close[t+h] (adjusted), NaN unless fw.ok(h)   [L.fwd_return]
V_h   = elig_base & isfinite(r_h)          (cross-section used for winsorising / OLS / ranking)
rw_h  = r_h winsorised at the per-date 1st/99th percentile over V_h
resid = per-date OLS residual of rw_h on a neutraliser set (intercept always included):
   neu    : [shrunk beta = 0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20]       (= XR_neu)
   neumom : neu + mom_12_1 (NaN mom_12_1 -> per-date median of V_h; 11.8% of elig rows)
   size   : [log_turn20]
   none   : []  (rank of winsorised raw return == rank of excess-vs-index return)
pct   = per-date percentile rank (0,1] of resid over V_h.  Labels are derived from pct (common.form_label).
Labels are NaN outside V_h-with-finite-r; eligibility never changes values.
"""
import time

import numpy as np
import pandas as pd

from common import HS, NEUTS, OUT, L, save, date_groups

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "elig_liq5", "fno_proxy", "beta_60", "vol_20", "log_turn20", "mom_12_1"])
fw = L.Fwd(P)
E = F["elig_base"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
beta_s = 0.5 * np.clip(F["beta_60"].values.astype("float64"), 0.0, 3.0) + 0.5
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
mom = F["mom_12_1"].values.astype("float64")
mk = L.market_series("Nifty 500").reindex(pd.DatetimeIndex(cal)).ffill()
mo, mc = mk["open"].values, mk["close"].values
pos = np.searchsorted(cal, dates).astype(float)
np.savez_compressed(f"{OUT}/meta.npz", E=E, liq5=F["elig_liq5"].values.astype(bool),
                    fno=F["fno_proxy"].values.astype(bool))
diag = {"elig_base_rows": int(E.sum()),
        "beta_clip_share": float(((F["beta_60"].values[E] < 0) | (F["beta_60"].values[E] > 3)).mean()),
        "mom_12_1_nan_share_on_elig": float(np.isnan(mom[E]).mean())}
print("loaded", round(time.time() - t0, 1), flush=True)

for h in HS:
    r = L.fwd_return(P, fw, h)
    V = E & np.isfinite(r)
    # market return over the stock's own executable window
    p1, ph = fw.at(pos, 1), fw.at(pos, h)
    okm = np.isfinite(p1) & np.isfinite(ph) & np.isfinite(r)
    m = np.full(len(P), np.nan)
    m[okm] = mc[ph[okm].astype(int)] / mo[p1[okm].astype(int)] - 1
    idx, b, e = date_groups(dates, np.flatnonzero(V))
    rw = np.full(len(P), np.nan)
    mom_f = mom.copy()
    ew = np.full(len(P), np.nan)          # same-date equal-weight universe mean of r (for excess)
    n_dates_small = 0
    for s_, t_ in zip(b, e):
        ii = idx[s_:t_]
        y = r[ii]
        lo, hi = np.percentile(y, [1, 99])
        rw[ii] = np.clip(y, lo, hi)
        ew[ii] = y.mean()
        mm = mom[ii]
        if np.isnan(mm).any():
            med = np.nanmedian(mm) if np.isfinite(mm).any() else 0.0
            mom_f[ii] = np.where(np.isnan(mm), med, mm)
    out = {"r": r, "rw": rw, "m": m, "ew": ew}
    for nt in NEUTS:
        cols = {"neu": [beta_s, vol, lt], "neumom": [beta_s, vol, lt, mom_f], "size": [lt], "none": []}[nt]
        resid = np.full(len(P), np.nan)
        r2 = []
        for s_, t_ in zip(b, e):
            ii = idx[s_:t_]
            if len(ii) < 30:
                n_dates_small += 1
                continue
            y = rw[ii]
            X = np.column_stack([np.ones(len(ii))] + [c[ii] for c in cols])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            res_ = y - X @ coef
            resid[ii] = res_
            r2.append(1 - res_.var() / y.var() if y.var() > 0 else np.nan)
        pct = pd.Series(resid).groupby(dates).rank(pct=True, method="average").values
        out[f"res_{nt}"] = resid
        out[f"pct_{nt}"] = pct
        diag[f"h{h}_{nt}_mean_xs_R2"] = float(np.nanmean(r2))
        print(h, nt, "R2", round(float(np.nanmean(r2)), 4), round(time.time() - t0, 1), flush=True)
    diag[f"h{h}"] = {"valid_rows": int(V.sum()), "valid_share_of_elig": float(V.sum() / E.sum()),
                     "dates": int(len(b)), "dates_lt30": int(n_dates_small // len(NEUTS)),
                     "median_names_per_date": float(np.median(e - b)),
                     "spearman_pct_neu_vs_none": float(np.corrcoef(out["pct_neu"][V], out["pct_none"][V])[0, 1]),
                     "spearman_pct_neu_vs_size": float(np.corrcoef(out["pct_neu"][V], out["pct_size"][V])[0, 1]),
                     "spearman_pct_neu_vs_neumom": float(np.corrcoef(out["pct_neu"][V], out["pct_neumom"][V])[0, 1])}
    np.savez_compressed(f"{OUT}/labels_h{h}.npz", **{k: np.asarray(a, dtype=np.float32) for k, a in out.items()})
    print(h, "saved", diag[f"h{h}"], round(time.time() - t0, 1), flush=True)
save("s1_label_build", diag)
