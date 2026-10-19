"""Stage 8: what does each model's score load on? (diagnostic, no selection)
  * mean per-date Spearman(score, characteristic) on dev and holdout for vol_20, beta_60, log_turn20,
    mom_12_1, mom_20, mom_5, idio_vol_60, dist_sma200, deliv_pct
  * top-20 pick profile: mean cross-sectional percentile of those characteristics among the daily
    top-20 (0.5 = universe average) + share fno_proxy + share liq5
  * pairwise per-date Spearman between model scores (dev / holdout)
Usage: python3 s8_loadings.py tag1 tag2 ...
"""
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, save

tags = sys.argv[1:]
t0 = time.time()
CH = ["vol_20", "beta_60", "log_turn20", "mom_12_1", "mom_20", "mom_5", "idio_vol_60", "dist_sma200", "deliv_pct"]
P = L.load_panel(["date"])
F = L.load_features(CH)
meta = np.load(f"{OUT}/meta.npz")
E, fno, liq5 = meta["E"], meta["fno"], meta["liq5"]
dates = P["date"].values.astype("datetime64[D]")
yr = pd.DatetimeIndex(dates).year.values
m0 = E & (dates >= np.datetime64("2023-01-01"))
idx = np.flatnonzero(m0)
d = dates[idx]
sub = (pd.Series(np.arange(len(idx))).groupby(d).ngroup().values % 5) == 0   # every 5th date (speed)
idx, d = idx[sub], d[sub]
grp = pd.Series(d)


def xr(x):
    return pd.Series(x).groupby(d).rank(pct=True).values


chr_ = {c: xr(F[c].values[idx].astype("float64")) for c in CH}
scores = {t: np.load(f"{OUT}/wf_{t}.npz")["score"][idx].astype("float64") for t in tags}
srk = {t: xr(s) for t, s in scores.items()}
period = np.where(yr[idx] >= 2026, "hold", "dev")
out = {}


def date_corr(a, b):
    df = pd.DataFrame({"d": d, "a": a, "b": b, "p": period}).dropna()
    c = df.groupby("d").apply(lambda g: g.a.corr(g.b), include_groups=False)
    p = df.groupby("d").p.first()
    return {"dev": float(c[p == "dev"].mean()), "hold": float(c[p == "hold"].mean())}


for t in tags:
    o = {"spearman": {c: date_corr(srk[t], chr_[c]) for c in CH}}
    # top-20 profile
    df = pd.DataFrame({"d": d, "s": scores[t], "p": period, "fno": fno[idx], "liq5": liq5[idx],
                       **{c: chr_[c] for c in CH}})
    df = df[np.isfinite(df.s)]
    top = df.sort_values(["d", "s"], ascending=[True, False]).groupby("d").head(20)
    o["top20_profile"] = {p: {**{c: round(float(g[c].mean()), 3) for c in CH},
                              "fno_share": float(g.fno.mean()), "liq5_share": float(g.liq5.mean())}
                          for p, g in top.groupby("p")}
    out[t] = o
    print(t, {c: round(v["dev"], 3) for c, v in o["spearman"].items()}, round(time.time() - t0, 1), flush=True)
pc = {}
for i, a in enumerate(tags):
    for b in tags[i + 1:]:
        pc[f"{a}|{b}"] = date_corr(srk[a], srk[b])
out["pairwise_score_spearman"] = pc
save("s8_loadings", out)
