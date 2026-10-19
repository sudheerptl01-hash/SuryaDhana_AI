#!/usr/bin/env python3
"""Stage 6: are the adaptive / move-quality labels teaching the model anything different from a
fixed-horizon label?  (a) mean daily Spearman correlation between model scores, (b) paired daily
rank-IC difference vs the fixed-horizon controls (FX10_pm50, FX20_pm50) on r10 and r20, with
non-overlapping t-stats, dev (2023-2025) and 2026 holdout separately."""
import glob
import os

import numpy as np
import pandas as pd

from common import OUT, L, eq_universe, save

P = L.load_panel(["date", "entity"])
F = L.load_features(["elig_base"])
eq = eq_universe(P, F)
Z = dict(np.load(f"{OUT}/labels.npz"))
dates = P["date"].values.astype("datetime64[D]")
names = sorted(os.path.basename(p)[3:-4] for p in glob.glob(f"{OUT}/wf_*.npz"))
S = {n: np.load(f"{OUT}/wf_{n}.npz")["score"].astype(float) for n in names}
m = eq & np.isfinite(S[names[0]]) & (dates >= np.datetime64("2023-01-01"))
for n in names:
    m &= np.isfinite(S[n])
d = dates[m]
yr = pd.DatetimeIndex(d).year.values
df = pd.DataFrame({"d": d, "yr": yr})
for n in names:
    df[n] = S[n][m]
    df[n] = df.groupby("d")[n].rank()
for h in (10, 20):
    df[f"r{h}"] = Z[f"r{h}"].astype(float)[m]
    df[f"r{h}"] = df.groupby("d")[f"r{h}"].rank()


def day_corr(a, b, sub):
    x = sub[a] - sub.groupby("d")[a].transform("mean")
    y = sub[b] - sub.groupby("d")[b].transform("mean")
    t = pd.DataFrame({"d": sub.d, "xy": x * y, "xx": x * x, "yy": y * y}).groupby("d").sum()
    return t.xy / np.sqrt(t.xx * t.yy)


out = {"score_corr_dev": {}, "ic_diff": {}}
dev = df[df.yr <= 2025]
for i, a in enumerate(names):
    for b in names[i + 1:]:
        out["score_corr_dev"][f"{a}|{b}"] = float(day_corr(a, b, dev).mean())
for h in (10, 20):
    sub = df[np.isfinite(df[f"r{h}"])]
    ic = {n: day_corr(n, f"r{h}", sub) for n in names}
    yrs = pd.Series(pd.DatetimeIndex(ic[names[0]].index).year, index=ic[names[0]].index)
    for ctrl in ("FX10_pm50", "FX20_pm50"):
        if ctrl not in ic:
            continue
        for n in names:
            if n == ctrl:
                continue
            dif = (ic[n] - ic[ctrl]).dropna()
            res = {}
            for wn, sel in (("dev", yrs.loc[dif.index] <= 2025), ("2026", yrs.loc[dif.index] == 2026)):
                s = dif[sel.values].iloc[::h]
                res[wn] = {"mean_diff": float(dif[sel.values].mean()),
                           "t_nonoverlap": float(s.mean() / (s.std() / np.sqrt(len(s)))) if len(s) > 3 else None,
                           "n_nonoverlap": int(len(s))}
            res["by_year"] = {int(y): float(g.mean()) for y, g in dif.groupby(yrs.loc[dif.index].values)}
            out["ic_diff"][f"r{h}|{n}-{ctrl}"] = res
save("s6_compare", out)
for k, v in out["score_corr_dev"].items():
    print(k, round(v, 3))
for k, v in out["ic_diff"].items():
    print(k, {a: (round(b["mean_diff"], 4), round(b["t_nonoverlap"] or 0, 2)) for a, b in v.items() if a != "by_year"},
          {a: round(b, 4) for a, b in v["by_year"].items()})
