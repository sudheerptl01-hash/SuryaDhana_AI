"""Stage 10: significance of top-20 selection vs the universe mean (= expected random pick),
per signal date, for each OOS score. Non-overlapping t-stat (every h-th date).
Exits: time (open[t+1]->close[t+h]) and the label's own barrier return.
Periods: selection 2023-25 and holdout 2026 (dates <= 2026-09-10)."""
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
dates = P["date"].values.astype("datetime64[D]")
labz = np.load(f"{OUT}/labels_shortlist.npz")
rets = {"time20": L.fwd_return(P, fw, 20), "time10": L.fwd_return(P, fw, 10),
        "barrierB20sym": labz["B20_f2.0_2.0_long_ret"].astype("float64"),
        "barrierB20asym": labz["B20_f3.0_1.5_long_ret"].astype("float64"),
        "barrierB10": labz["B10_f2.0_1.5_long_ret"].astype("float64")}
res = {}
for f in sorted(glob.glob(f"{OUT}/wf_*_2023-2024-2025-2026*.npz")):
    tag = os.path.basename(f)[3:-4]
    s = np.load(f)["score"].astype("float64")
    out = {}
    for rn, r in rets.items():
        h = 10 if rn in ("time10", "barrierB10") else 20
        m = elig & np.isfinite(s) & np.isfinite(r)
        df = pd.DataFrame({"d": dates[m], "s": s[m], "r": r[m]})
        df = df[(df.d >= np.datetime64("2023-01-01")) & (df.d <= np.datetime64("2026-09-10"))]
        df["rk"] = df.groupby("d").s.rank(ascending=False, method="first")
        top = df[df.rk <= 20].groupby("d").r.mean()
        allm = df.groupby("d").r.mean()
        ex = (top - allm).dropna()
        o = {}
        for pn, lo, hi in (("2023_25", "2023-01-01", "2025-12-31"), ("2026", "2026-01-01", "2026-09-10")):
            e = ex[(ex.index >= pd.Timestamp(lo)) & (ex.index <= pd.Timestamp(hi))]
            sub = e.iloc[::h]
            o[pn] = {"mean_excess_per_trade": float(e.mean()), "n_dates": int(len(e)), "n_nonoverlap": int(len(sub)),
                     "t_nonoverlap": float(sub.mean() / (sub.std() / np.sqrt(len(sub)))),
                     "t_eff_all_dates": float(e.mean() / (e.std() / np.sqrt(len(e) / h))),
                     "share_dates_positive": float((e > 0).mean())}
        for y in (2023, 2024, 2025):
            e = ex[ex.index.year == y]
            sub = e.iloc[::h]
            o[str(y)] = {"mean_excess_per_trade": float(e.mean()), "t_nonoverlap": float(sub.mean() / (sub.std() / np.sqrt(len(sub)))),
                         "t_eff_all_dates": float(e.mean() / (e.std() / np.sqrt(len(e) / h)))}
        out[rn] = o
    res[tag] = out
    print(tag, {rn: {p: (round(v["mean_excess_per_trade"] * 100, 2), round(v["t_eff_all_dates"], 2)) for p, v in o.items()} for rn, o in out.items()}, flush=True)
with open(f"{OUT}/significance.json", "w") as fh:
    json.dump(res, fh, indent=1)
update_results("significance_top20_vs_universe", res)
