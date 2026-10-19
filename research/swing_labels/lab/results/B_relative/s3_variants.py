"""Stage 3: residual-regime-bias screen of cross-sectional label constructions.

Rank labels are level-neutral by construction (positive share = 30% every day), but WHICH stocks
land in +1 can still depend on the market: e.g. raw-return ranks put high-beta names on top in up
windows. We measure, per signal date, the beta tilt (mean beta of +1 minus -1) and vol tilt and
correlate them with that date's Nifty-500 window return. ~0 = composition does not depend on the
market direction. Variants:
  raw   : rank of r                 (== rank of r - r_mkt; verified identical in s1)
  br_w  : rank of r - (w*beta60 + (1-w))*r_mkt, w in {0.25,0.5,0.75,1}  (w=1: plain beta_60)
  vn    : rank of r/(vol20*sqrt(h))
  neu   : rank of per-date OLS residual of r on [1, beta60, vol20, log_turn20] (ex-post neutral)
Shrinkage choice uses 2021-2025 dates only (2026 holdout untouched).
"""
import sys
import time

import numpy as np
import pandas as pd

from common import HS, OUT, L, save, xs_rank, tercile_label

t0 = time.time()
P = L.load_panel(["date"])
F = L.load_features(["beta_60", "vol_20", "log_turn20"])
meta = np.load(f"{OUT}/meta.npz")
U = meta["U"]
dates = P["date"].values.astype("datetime64[D]")
beta = np.clip(F["beta_60"].values.astype("float64"), 0, 3)
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
dev = dates < np.datetime64("2026-01-01")
res = {}


def tilt(lab, m, mk):
    td = pd.DataFrame({"d": dates[mk], "y": lab[mk], "b": beta[mk], "v": vol[mk], "lt": lt[mk], "m": m[mk],
                       "dev": dev[mk]})
    pos_ = td[td.y == 1].groupby("d")[["b", "v", "lt"]].mean()
    neg_ = td[td.y == -1].groupby("d")[["b", "v", "lt"]].mean()
    g = td.groupby("d")[["m", "dev"]].first()
    tl = (pos_ - neg_).join(g, how="inner").dropna()
    out = {}
    for nm, sub in (("all", tl), ("dev", tl[tl.dev.astype(bool)])):
        out[nm] = {"corr_beta_tilt": float(sub.b.corr(sub.m)), "corr_vol_tilt": float(sub.v.corr(sub.m)),
                   "corr_size_tilt": float(sub["lt"].corr(sub.m)),
                   "beta_tilt_up": float(sub.b[sub.m > 0].mean()), "beta_tilt_dn": float(sub.b[sub.m <= 0].mean()),
                   "vol_tilt_up_pct": float(sub.v[sub.m > 0].mean() * 100), "vol_tilt_dn_pct": float(sub.v[sub.m <= 0].mean() * 100)}
    return out


for h in HS:
    Z = dict(np.load(f"{OUT}/labels_h{h}.npz"))
    r = Z["r"].astype("float64")
    m = Z["m"].astype("float64")
    v = U & np.isfinite(r)
    out = {}
    newarr = {}
    cands = {"raw": Z["pct_raw"].astype("float64"), "vn": Z["pct_vn"].astype("float64"),
             "vnx": Z["pct_vnx"].astype("float64")}
    for w in (0.25, 0.5, 0.75, 1.0):
        x = r - (w * beta + (1 - w)) * m
        cands[f"br{int(w * 100)}"] = xs_rank(x, dates, v)
    # per-date OLS neutralisation
    idx = np.flatnonzero(v & np.isfinite(beta) & np.isfinite(vol) & np.isfinite(lt))
    order = np.argsort(dates[idx], kind="stable")
    idx = idx[order]
    d_s = dates[idx]
    b = np.flatnonzero(np.r_[True, d_s[1:] != d_s[:-1]])
    e_ = np.r_[b[1:], len(idx)]
    resid = np.full(len(r), np.nan)
    for s_, t_ in zip(b, e_):
        ii = idx[s_:t_]
        if len(ii) < 30:
            continue
        X = np.column_stack([np.ones(len(ii)), beta[ii], vol[ii], lt[ii]])
        y = r[ii]
        # winsorise y for the fit only (robust to a few extreme names); residual uses raw y
        lo, hi = np.percentile(y, [1, 99])
        coef, *_ = np.linalg.lstsq(X, np.clip(y, lo, hi), rcond=None)
        resid[ii] = y - X @ coef
    cands["neu"] = xs_rank(resid, dates, v)
    newarr["pct_neu"] = cands["neu"]
    for w in (0.25, 0.5, 0.75):
        newarr[f"pct_br{int(w * 100)}"] = cands[f"br{int(w * 100)}"]
    for nm, pct in cands.items():
        lab = tercile_label(pct, 0.3)
        mk = U & ~np.isnan(lab)
        out[nm] = tilt(lab, m, mk)
        # rank correlation of this construction with raw rank (how different is it?)
        out[nm]["spearman_vs_raw"] = float(np.corrcoef(pct[mk], Z["pct_raw"][mk])[0, 1])
        print(h, nm, round(time.time() - t0, 1), out[nm]["dev"], flush=True)
    np.savez_compressed(f"{OUT}/labels_h{h}_v.npz", **{k: np.asarray(a, np.float32) for k, a in newarr.items()})
    res[f"h{h}"] = out
save("s3_tilt_screen", res)
