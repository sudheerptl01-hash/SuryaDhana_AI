"""Stage 4: learnability (cross-sectional only; never pooled AUC for absolute labels).
For every walk-forward score: per-date rank IC vs the relative target (resid20) and vs raw r20, and
per-date AUC vs each binary event (REL+1, DUAL+1, DUALP+1, ABS+1, BAR+1, REL-1, DUAL-1), dev vs
holdout, non-overlapping t-stats (L.xs_metrics). Plus: score-score rank correlations, top-decile
realised outcomes (net bps, resid bps, event rates), and the timing content of the absolute
models' cross-sectional MEAN probability (corr with next-20d market return)."""
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, xs_pct

t0 = time.time()
P = L.load_panel(["date"])
U = np.load(f"{OUT}/meta.npz")["U"]
dates = P["date"].values.astype("datetime64[D]")
Z = np.load(f"{OUT}/labels_h20.npz")
r = Z["r"].astype("float64")
resid = Z["resid"].astype("float64")
m = Z["m"].astype("float64")
B = {}
for k in ("REL", "DUAL", "DUALP", "ABS", "BAR"):
    x = Z[k].astype("float64")
    B[f"{k}+1"] = np.where(np.isfinite(x), (x == 1).astype(float), np.nan)
    if k in ("REL", "DUAL", "DUALP"):
        B[f"{k}-1"] = np.where(np.isfinite(x), (x == -1).astype(float), np.nan)
DOWN = {"M_RDN", "M_DDN"}
scores = {}
for fn in sorted(glob.glob(f"{OUT}/wf_M_*.npz")):
    tag = os.path.basename(fn)[3:-4]
    if tag.endswith("10"):
        continue
    if len(sys.argv) > 1 and sys.argv[1] != "corr" and tag not in sys.argv[1:]:
        continue
    s = np.load(fn)["score"].astype("float64")
    scores[tag] = -s if tag in DOWN else s          # oriented: higher = better long candidate
done = {}
ONLY_CORR = len(sys.argv) > 1 and sys.argv[1] == "corr"
for tag, s in scores.items():
    if ONLY_CORR:
        break
    out = {"ic_resid": L.xs_metrics(s, resid, U, P, 20), "ic_raw": L.xs_metrics(s, r, U, P, 20)}
    for bk, b in B.items():
        sc = -s if bk.endswith("-1") else s          # AUC of "more likely to be this event"
        mt = L.xs_metrics(sc, resid, U, P, 20, binary_target=b)
        out[f"auc_{bk}"] = {k: v for k, v in mt.items() if "auc" in k}
    # top-decile / bottom-decile realised outcomes per date
    sp = xs_pct(s, dates, U)
    rows = []
    for nm, sel in (("top10", sp > 0.9), ("bot10", sp <= 0.1), ("all", np.isfinite(sp))):
        for wn, (a, b_) in (("dev", ("2023-01-01", "2025-12-31")), ("hold", ("2026-01-01", "2100-01-01"))):
            w = U & sel & (dates >= np.datetime64(a)) & (dates <= np.datetime64(b_)) & np.isfinite(r)
            d = {"sel": nm, "win": wn, "n": int(w.sum()), "mean_net_bps": float(np.mean(r[w] - 0.005) * 1e4),
                 "mean_resid_bps": float(np.mean(resid[w]) * 1e4)}
            for bk, b in B.items():
                d[f"rate_{bk}"] = float(np.nanmean(b[w]))
            rows.append(d)
    out["deciles"] = rows
    # timing content of the score LEVEL (xs mean) -> next-20d market window return (dev and holdout)
    raw = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    df = pd.DataFrame({"d": dates[U], "s": raw[U], "m": m[U]}).dropna()
    g = df.groupby("d").agg(s=("s", "mean"), m=("m", "median"))
    for wn, (a, b_) in (("dev", ("2023-01-01", "2025-12-31")), ("hold", ("2026-01-01", "2100-01-01"))):
        gg = g[(g.index >= np.datetime64(a)) & (g.index <= np.datetime64(b_))]
        nov = gg.iloc[::20]
        out[f"level_timing_{wn}"] = {"corr_daily": float(gg.s.corr(gg.m)), "corr_nonoverlap": float(nov.s.corr(nov.m)),
                                     "n_nonoverlap": int(len(nov))}
    done[tag] = out
    save(f"s4_xs_{tag}", out)
    print(tag, round(time.time() - t0, 1), {k: round(v, 4) for k, v in out["ic_resid"].items() if not isinstance(v, dict)},
          flush=True)
# pairwise per-date rank correlation of scores (dev dates, every 5th date for speed)
if not ONLY_CORR:
    raise SystemExit(0)
tags = list(scores)
cal = np.unique(dates[U & (dates >= np.datetime64("2023-01-01")) & (dates <= np.datetime64("2025-12-31"))])[::5]
sel = U & np.isin(dates, cal)
pcts = {t: xs_pct(scores[t], dates, sel) for t in tags}
C = {}
for i, a in enumerate(tags):
    for b in tags[i + 1:]:
        ok = sel & np.isfinite(pcts[a]) & np.isfinite(pcts[b])
        df = pd.DataFrame({"d": dates[ok], "a": pcts[a][ok], "b": pcts[b][ok]})
        C[f"{a}|{b}"] = float(df.groupby("d").apply(lambda g: g.a.corr(g.b), include_groups=False).mean())
save("s4_score_corr_dev", C)
print("done", round(time.time() - t0, 1))
