#!/usr/bin/env python3
"""Stage 4: walk-forward canaries (L.walk_forward, date_step=2, n_jobs=2).
Label (h=10): executable return open[t+1]->close[t+10] > +50 bps, NaN where undefined; mask elig_base.
Variants (argv[1]):
  base    real label, all 53 lab features
  shuf    label shuffled WITHIN date (keeps each date's base rate -> any AUC is pure market timing)
  leak    + feature = true fwd return + Gaussian noise (sd = 1 x cross-sectional sd)  -> must be caught
  leak1d  + feature = day-1 intraday return close[t+1]/open[t+1]-1 (one day of look-ahead) -> subtle leak
  nosec   all features EXCEPT sec_rel_mom20 (sector map is a 2026 snapshot -> look-ahead test)
Saves OOS score to wf_<variant>.npz and metrics to results.json."""
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from common import OUT, L, save

var = sys.argv[1]
t0 = time.time()
H = 10
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
feats = list(L.FEATURES)
F = L.load_features(feats + ["elig_base"])
fw = L.Fwd(P)
r = L.fwd_return(P, fw, H)
mask = F.elig_base.values & np.isfinite(r)
y = np.where(np.isfinite(r), (r > 0.005).astype(float), np.nan)
y[~F.elig_base.values] = np.nan
dates = P.date.values.astype("datetime64[D]")
rng = np.random.default_rng(123)
if var == "shuf":
    idx = np.flatnonzero(mask)
    d = pd.DataFrame({"i": idx, "d": dates[idx], "u": rng.random(len(idx))})
    d = d.sort_values(["d", "u"])
    # permute labels within each date
    perm = d.groupby("d").i.transform(lambda s: s.sample(frac=1.0, random_state=1).values).values
    ys = y.copy()
    ys[d.i.values] = y[perm]
    y = ys
elif var == "leak":
    sd = np.nanstd(r[mask])
    F["leak_fwd"] = (r + rng.normal(0, sd, len(r))).astype("float32")
    feats = feats + ["leak_fwd"]
elif var == "leak1d":
    F["leak_d1"] = (fw.at(P.close.values, 1) / fw.at(P.open.values, 1) - 1).astype("float32")
    feats = feats + ["leak_d1"]
elif var == "nosec":
    feats = [f for f in feats if f != "sec_rel_mom20"]
print("prep", time.time() - t0, flush=True)
score, met = L.walk_forward(y, mask, P, F, H, kind="binary", features=feats, date_step=2, n_jobs=2)
print("wf", time.time() - t0, flush=True)
np.savez_compressed(os.path.join(OUT, f"wf_{var}.npz"), score=score.astype("float32"))
# extra diagnostics: per-date cross-sectional AUC, timing-only AUC, decile return spread
yy = (r > 0.005).astype(float)
ext = []
for Y in (2023, 2024, 2025, 2026):
    m = mask & np.isfinite(score) & (pd.DatetimeIndex(dates).year.values == Y)
    if m.sum() < 1000:
        continue
    df = pd.DataFrame({"d": dates[m], "s": score[m], "y": y[m], "ytrue": yy[m], "r": r[m]})
    xs = df.groupby("d").apply(lambda g: roc_auc_score(g.y, g.s) if 0 < g.y.mean() < 1 and len(g) > 30 else np.nan,
                               include_groups=False).dropna()
    dm = df.groupby("d").agg(sm=("s", "mean"), ym=("y", "mean"))
    df["sm"] = df.d.map(dm.sm)
    timing_auc = roc_auc_score(df.y, df.sm)
    df["rk"] = df.groupby("d").s.rank(pct=True)
    top = df[df.rk > 0.9].r.mean()
    bot = df[df.rk <= 0.1].r.mean()
    ext.append({"year": Y, "pooled_auc": float(roc_auc_score(df.y, df.s)), "mean_daily_xs_auc": float(xs.mean()),
                "xs_auc_t_nonoverlap": float(xs.iloc[::H].mean() - 0.5) / float(xs.iloc[::H].std() / np.sqrt(len(xs.iloc[::H]))),
                "timing_only_auc(date-mean score)": float(timing_auc),
                "top_decile_fwd_ret_bps": float(top * 1e4), "bottom_decile_fwd_ret_bps": float(bot * 1e4),
                "all_fwd_ret_bps": float(df.r.mean() * 1e4),
                "top_decile_true_label_rate": float(df[df.rk > 0.9].ytrue.mean()), "base_rate_true": float(df.ytrue.mean())})
    print(ext[-1], flush=True)
met["extra"] = ext
met["features_used"] = len(feats)
met["runtime_s"] = time.time() - t0
save(f"s4_wf_{var}", met)
