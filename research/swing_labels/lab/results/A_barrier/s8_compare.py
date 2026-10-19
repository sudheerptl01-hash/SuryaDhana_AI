"""Stage 8: apples-to-apples learnability across all walk-forward scores against COMMON
yardsticks: per-date Spearman IC vs executable 20d and 10d returns (open[t+1]->close[t+h]),
top-decile minus universe mean 20d return, xs-AUC vs the B20 2/2 barrier +1 label.
Non-overlapping t-stat uses every h-th date. Per year, 2026 = holdout."""
import glob
import json
import os

import numpy as np
import pandas as pd

from abar import L, OUT, update_results

P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base"])
fw = L.Fwd(P)
elig = F["elig_base"].values.astype(bool)
r20 = L.fwd_return(P, fw, 20)
r10 = L.fwd_return(P, fw, 10)
labB = np.load(f"{OUT}/labels_shortlist.npz")["B20_f2.0_2.0_long_lab"].astype("float64")
dates = P["date"].values.astype("datetime64[D]")
year = pd.DatetimeIndex(P["date"].values).year.values
files = sorted(glob.glob(f"{OUT}/wf_*_2023-2024-2025-2026*.npz"))
res = {}
for f in files:
    tag = os.path.basename(f)[3:-4]
    s = np.load(f)["score"].astype("float64")
    m = elig & np.isfinite(s) & np.isfinite(r20) & np.isfinite(r10) & ~np.isnan(labB)
    df = pd.DataFrame({"d": dates[m], "y": year[m], "s": s[m], "r20": r20[m], "r10": r10[m],
                       "pos": (labB[m] == 1).astype(float)})
    df["rk"] = df.groupby("d").s.rank()
    df["pr"] = df.groupby("d").s.rank(pct=True)
    df["r20k"] = df.groupby("d").r20.rank()
    df["r10k"] = df.groupby("d").r10.rank()
    out = {}
    for y, g in df.groupby("y"):
        ic20 = g.groupby("d").apply(lambda x: x.rk.corr(x.r20k), include_groups=False)
        ic10 = g.groupby("d").apply(lambda x: x.rk.corr(x.r10k), include_groups=False)
        s20 = ic20.iloc[::20]
        s10 = ic10.iloc[::10]
        top = g[g.pr > 0.9].groupby("d").r20.mean()
        allm = g.groupby("d").r20.mean()
        bot = g[g.pr <= 0.1].groupby("d").r20.mean()

        def xs_auc(x):
            p = x.pos.values
            npos = p.sum()
            if npos == 0 or npos == len(p):
                return np.nan
            return (x.rk.values[p == 1].sum() - npos * (npos + 1) / 2) / (npos * (len(p) - npos))
        auc = g.groupby("d").apply(xs_auc, include_groups=False)
        out[int(y)] = {"ic20": float(ic20.mean()), "ic20_t_nonoverlap": float(s20.mean() / (s20.std() / np.sqrt(len(s20)))),
                       "ic10": float(ic10.mean()), "ic10_t_nonoverlap": float(s10.mean() / (s10.std() / np.sqrt(len(s10)))),
                       "top10_minus_all_r20": float((top - allm).mean()), "bot10_minus_all_r20": float((bot - allm).mean()),
                       "xs_auc_vs_B20sym": float(auc.mean())}
    res[tag] = out
    print(tag, json.dumps({y: {k: round(v, 4) for k, v in o.items()} for y, o in out.items()}), flush=True)
with open(f"{OUT}/compare_learnability.json", "w") as fh:
    json.dump(res, fh, indent=1)
update_results("compare_learnability", res)
