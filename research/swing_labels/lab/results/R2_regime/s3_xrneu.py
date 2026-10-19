"""Stage 3: XR_neu relative label (h=20) and its walk-forward regression score.

r20    = open[t+1] -> close[t+20] (adjusted; NaN unless fw.ok(20))           [L.fwd_return]
V      = elig_base & finite(r20)
XR_neu = per date over V: winsorise r20 at the 1st/99th pct, OLS on
         [1, 0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20]; residual -> per-date pct rank (0,1].
Target = pct - 0.5 (regression). Same construction as R2_rel 'neu' / R2_alpha 'XR' (cross-checked).
Model  = L.walk_forward2(kind='regression', 52 PIT features, folds 2023..2026, embargo 22, date_step 2).
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save

t0 = time.time()
H = 20
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(L.FEATURES + ["elig_base", "elig_liq5"])
fw = L.Fwd(P)
dates = P["date"].values.astype("datetime64[D]")
U = F["elig_base"].values.astype(bool)
print("loaded", round(time.time() - t0, 1), flush=True)

r = L.fwd_return(P, fw, H)
V = U & np.isfinite(r)
beta_s = 0.5 * np.clip(F["beta_60"].values.astype("float64"), 0.0, 3.0) + 0.5
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
okx = V & np.isfinite(beta_s) & np.isfinite(vol) & np.isfinite(lt)
idx = np.flatnonzero(okx)
order = np.argsort(dates[idx], kind="stable")
idx = idx[order]
dd = dates[idx]
b = np.flatnonzero(np.r_[True, dd[1:] != dd[:-1]])
e = np.r_[b[1:], len(idx)]
res = np.full(len(P), np.nan)
for s_, t_ in zip(b, e):
    ii = idx[s_:t_]
    if len(ii) < 30:
        continue
    y = r[ii]
    lo, hi = np.percentile(y, [1, 99])
    yw = np.clip(y, lo, hi)
    X = np.column_stack([np.ones(len(ii)), beta_s[ii], vol[ii], lt[ii]])
    coef, *_ = np.linalg.lstsq(X, yw, rcond=None)
    res[ii] = yw - X @ coef
pct = pd.Series(res).groupby(dates).rank(pct=True, method="average").values
target = pct - 0.5
print("label built", round(time.time() - t0, 1), flush=True)

diag = {"U_rows": int(U.sum()), "V_rows": int(V.sum()), "label_rows": int(np.isfinite(pct).sum())}
try:
    z = np.load(f"{L.LAB}/results/R2_rel/labels_h20.npz")
    o = z["pct_neu"].astype("float64")
    mm = np.isfinite(o) & np.isfinite(pct)
    diag["xcheck_R2_rel_pct_neu"] = {"both": int(mm.sum()), "max_abs_diff": float(np.abs(o[mm] - pct[mm]).max()),
                                     "only_mine": int((np.isfinite(pct) & ~np.isfinite(o)).sum()),
                                     "only_theirs": int((~np.isfinite(pct) & np.isfinite(o)).sum())}
except Exception as ex:  # noqa: BLE001
    diag["xcheck_R2_rel_pct_neu"] = str(ex)
print(diag, flush=True)

score = L.walk_forward2(target, U, P, F, H, kind="regression", date_step=2, n_jobs=2, verbose=True)
print("wf done", round(time.time() - t0, 1), flush=True)
np.savez_compressed(f"{OUT}/xrneu.npz", score=score.astype("float32"), pct=pct.astype("float32"),
                    r20=r.astype("float32"), U=U, liq5=F["elig_liq5"].values.astype(bool))
xs = L.xs_metrics(score, r, U, P, H, binary_target=np.where(np.isfinite(pct), (pct > 0.7).astype(float), np.nan))
xs_lab = L.xs_metrics(score, pct, U, P, H)
diag["xs_vs_r20_top30auc"] = xs
diag["xs_vs_label_pct"] = {k: v for k, v in xs_lab.items() if "ic" in k}
try:
    z = np.load(f"{L.LAB}/results/R2_alpha/wf_XR_all.npz")
    k0 = [k for k in z.files][0]
    o = z[k0].astype("float64")
    mm = np.isfinite(o) & np.isfinite(score)
    diag["xcheck_R2_alpha_wf_XR_all"] = {"key": k0, "both": int(mm.sum()),
                                         "corr": float(np.corrcoef(o[mm], score[mm])[0, 1]),
                                         "max_abs_diff": float(np.abs(o[mm] - score[mm]).max())}
except Exception as ex:  # noqa: BLE001
    diag["xcheck_R2_alpha_wf_XR_all"] = str(ex)
save("s3_xrneu", diag)
print(diag, flush=True)
print("total", round(time.time() - t0, 1))
