"""Stage 4: cross-sectional learnability of each walk-forward score.

Per-date (dates with >=30 names) Spearman IC of the OOS score vs
  own   : the model's own continuous target (pct of its neutraliser at its h)
  neu20 : common yardstick = XR_neu residual rank at h=20
  raw   : raw executable return r_h at the model's h (what a long book actually earns, rank)
and per-date AUC of the score for the top-30% class (+1) and for the bottom-30% class (score
inverted: AUC_down = P(score_bottom < score_rest)). Means over all dates; t-stats from every h-th date
(non-overlapping), exactly as L.xs_metrics. Split dev 2023-25 / holdout 2026 + by year.
Cross-checked against L.xs_metrics for the first model.
Usage: python3 s4_xs.py tag1 tag2 ...   (tag = h{h}_{neut}_{form})
"""
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from common import OUT, L, save, load_res

t0 = time.time()
P = L.load_panel(["date"])
dates = P["date"].values.astype("datetime64[D]")
E = np.load(f"{OUT}/meta.npz")["E"]
Z20 = np.load(f"{OUT}/labels_h20.npz")
neu20 = Z20["pct_neu"].astype("float64")
cache = {}


def per_date(score, targets, binaries, mask):
    m = mask & np.isfinite(score)
    idx = np.flatnonzero(m)
    order = np.argsort(dates[idx], kind="stable")
    idx = idx[order]
    d = dates[idx]
    b = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    e = np.r_[b[1:], len(idx)]
    rows = []
    for s_, t_ in zip(b, e):
        i0 = idx[s_:t_]
        rec = {"d": d[s_]}
        for k, t in targets.items():
            ii = i0[np.isfinite(t[i0])]
            if len(ii) >= 30:
                rec[f"ic_{k}"] = np.corrcoef(rankdata(score[ii]), rankdata(t[ii]))[0, 1]
        for k, (bb, sign) in binaries.items():
            ii = i0[np.isfinite(bb[i0])]
            if len(ii) < 30:
                continue
            pos = bb[ii] == 1
            n1, n0 = pos.sum(), (~pos).sum()
            if n1 > 5 and n0 > 5:
                rr = rankdata(score[ii] * sign)
                rec[f"auc_{k}"] = (rr[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
        if len(rec) > 1:
            rows.append(rec)
    return pd.DataFrame(rows).set_index("d")


def summarize(t, h):
    out = {}
    for name, (a, b) in (("dev", L.DEV), ("holdout", ("2026-01-01", "2100-01-01"))):
        sub = t[(t.index >= np.datetime64(a)) & (t.index <= np.datetime64(b))]
        if not len(sub):
            continue
        nov = sub.iloc[::max(1, h)]
        for col in sub.columns:
            x = nov[col].dropna()
            out[f"{name}_{col}_mean"] = float(sub[col].mean())
            if len(x) > 3:
                ctr = 0.0 if col.startswith("ic") else 0.5
                out[f"{name}_{col}_t"] = float((x.mean() - ctr) / (x.std() / np.sqrt(len(x))))
        out[f"{name}_n_dates"] = int(len(sub))
    yrs = pd.DatetimeIndex(t.index).year
    out["by_year"] = {int(y): {c: round(float(g[c].mean()), 4) for c in t.columns} for y, g in t.groupby(yrs)}
    return out


for tag in sys.argv[1:]:
    h = int(tag.split("_")[0][1:])
    nt = tag.split("_")[1]
    sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    if h not in cache:
        Z = np.load(f"{OUT}/labels_h{h}.npz")
        cache[h] = {k: Z[k].astype("float64") for k in ("r", "pct_neu", "pct_neumom", "pct_size", "pct_none")}
    Zh = cache[h]
    own = Zh[f"pct_{nt}"]
    targets = {"own": own, "neu20": neu20, "raw": Zh["r"]}
    binaries = {"top30": (np.where(np.isnan(own), np.nan, (own > 0.7).astype(float)), 1),
                "bot30": (np.where(np.isnan(own), np.nan, (own <= 0.3).astype(float)), -1)}
    t = per_date(sc, targets, binaries, E)
    s = summarize(t, h)
    if tag == sys.argv[1]:
        chk = L.xs_metrics(sc, own, E, P, h, binary_target=np.where(np.isnan(own), np.nan, (own > 0.7).astype(float)))
        s["check_L_xs_metrics"] = {k: v for k, v in chk.items() if "by_year" not in k}
    save(f"s4_xs_{tag}", s)
    print(tag, round(time.time() - t0, 1), {k: round(v, 4) for k, v in s.items()
                                             if isinstance(v, float) and ("mean" in k)}, flush=True)
