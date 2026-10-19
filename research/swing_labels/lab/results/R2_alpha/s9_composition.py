"""Stage 9: what the top-20 picks of each model ARE, by year (diagnostic for the 2026 failure).

On every 5th trading date (signal dates of phase 0 and the four other phases = every date) take each
model's top-20 by score among U. Report, averaged over dates, by year:
  xr_pct   : realised XR_neu residual percentile of the picks (0.5 = no factor-neutral skill)
  ex_raw   : realised r20 of picks minus the same-date U mean r20 (bps; what the long book earns
             relative to an EW universe before costs)
  ex_fac   : part of ex_raw explained by the picks' exposures to the XR neutralisers
             (per-date OLS slopes of r20 on [beta_s, vol_20, log_turn20] applied to the picks'
             average exposure gap) -> ex_raw = ex_fac + ex_resid (approximately)
  tilts    : mean same-date percentile (among U) of beta_60, vol_20, idio_vol_60, log_turn20,
             mom_12_1, mom_5, dist_sma200, deliv_pct, hi52_dist
"""
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from common import OUT, L, save, date_blocks

t0 = time.time()
P = L.load_panel(["date"])
dates = P["date"].values.astype("datetime64[D]")
CH = ["beta_60", "vol_20", "idio_vol_60", "log_turn20", "mom_12_1", "mom_5", "dist_sma200", "deliv_pct", "hi52_dist"]
F = L.load_features(CH)
C = np.column_stack([F[c].values.astype("float64") for c in CH])
del F
Z = np.load(f"{OUT}/labels.npz")
U = Z["U"]
pct = Z["pct"].astype("float64")
r20 = Z["r20"].astype("float64")
beta_s = 0.5 * np.clip(C[:, 0], 0, 3) + 0.5
vol, lt = C[:, 1], C[:, 3]
MODELS = ["XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XT", "XR_no_market", "BAR_no_market", "TSX_no_market", "ENS3_nomkt", "XR_all_FN", "TSX_all_FN"]
S = {m: np.load(f"{OUT}/wf_{m}.npz")["score"].astype("float64") for m in MODELS}
m0 = U & (dates >= np.datetime64("2023-01-01")) & np.isfinite(S["XR_all"])
idx, b0, e0 = date_blocks(dates, np.flatnonzero(m0))
rows = []
for s_, t_ in zip(b0, e0):
    ii = idx[s_:t_]
    if len(ii) < 100:
        continue
    d = dates[ii[0]]
    ok = np.isfinite(r20[ii])
    jj = ii[ok]
    if len(jj) < 100:
        continue
    # per-date factor slopes of r20 on the neutralisers (same regression as the label, unwinsorised)
    X = np.column_stack([np.ones(len(jj)), beta_s[jj], vol[jj], lt[jj]])
    cf, *_ = np.linalg.lstsq(X, r20[jj], rcond=None)
    mu_r = r20[jj].mean()
    mu_x = X[:, 1:].mean(0)
    crank = np.column_stack([rankdata(np.where(np.isfinite(C[ii, k]), C[ii, k], np.nanmedian(C[ii, k]))) / len(ii)
                             for k in range(len(CH))])
    for mname in MODELS:
        sc = S[mname][ii]
        top = np.argsort(-sc, kind="stable")[:20]
        pk = ii[top]
        okp = np.isfinite(r20[pk])
        rec = {"d": d, "model": mname,
               "xr_pct": float(np.nanmean(pct[pk])),
               "ex_raw": float((r20[pk][okp].mean() - mu_r) * 1e4) if okp.any() else np.nan}
        Xp = np.column_stack([beta_s[pk], vol[pk], lt[pk]])[okp]
        rec["ex_fac"] = float(((Xp.mean(0) - mu_x) @ cf[1:]) * 1e4) if okp.any() else np.nan
        for k, c in enumerate(CH):
            rec[f"tilt_{c}"] = float(crank[top, k].mean())
        rows.append(rec)
df = pd.DataFrame(rows)
df["year"] = pd.DatetimeIndex(df.d).year
df["ex_resid"] = df.ex_raw - df.ex_fac
out = {}
for mname, g in df.groupby("model"):
    out[mname] = {int(y): {c: float(gq[c].mean()) for c in gq.columns if c not in ("d", "model", "year")}
                  for y, gq in g.groupby("year")}
    g2 = g[g.year <= 2025]
    out[mname]["dev"] = {c: float(g2[c].mean()) for c in g2.columns if c not in ("d", "model", "year")}
save("s9_composition", out)
pd.set_option("display.width", 250)
print(df.groupby(["model", "year"])[["xr_pct", "ex_raw", "ex_fac", "ex_resid", "tilt_beta_60", "tilt_vol_20",
                                     "tilt_log_turn20", "tilt_mom_12_1", "tilt_dist_sma200", "tilt_deliv_pct"]]
      .mean().round(3))
print("total", round(time.time() - t0, 1))
