#!/usr/bin/env python3
"""Train the pre-registered production ensemble (PREREG_R3.md): 10 walk_forward2 regression
models on the frozen XR_neumom h=20 label, random_state {1..5} x date_offset {0,1}; PROD is the
per-date mean of cross-sectional percentile ranks over elig_base rows with a finite score."""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

OUT = os.path.join(LAB, "results", "_lead")
os.makedirs(OUT, exist_ok=True)
T0 = time.time()
P = L.load_panel(["date", "entity"])
F = L.load_features(L.FEATURES + ["elig_base"])
E = F["elig_base"].values.astype(bool)
pct = np.load(os.path.join(LAB, "results", "R3_devil", "label_h20_neumom.npz"))["pct"]
y = pct - 0.5
members, tags = [], []
for off in (0, 1):
    for seed in (1, 2, 3, 4, 5):
        t1 = time.time()
        sc = L.walk_forward2(y, E, P, F, 20, kind="regression", date_step=2, n_jobs=4,
                             params={"random_state": seed}, date_offset=off)
        members.append(sc.astype(np.float32))
        tags.append(f"s{seed}_o{off}")
        print(f"[{time.time() - T0:6.0f}s] model s{seed}_o{off} done in {time.time() - t1:.0f}s "
              f"scored {int(np.isfinite(sc).sum())}", flush=True)

M = np.vstack(members)
d = P["date"].values
ranks = np.full(M.shape, np.nan, dtype=np.float32)
for i in range(M.shape[0]):
    s = pd.Series(np.where(E, M[i], np.nan))
    ranks[i] = s.groupby(d).rank(pct=True).values.astype(np.float32)
prod = np.nanmean(np.where(np.isfinite(ranks), ranks, np.nan), axis=0)
prod[~np.isfinite(M).any(0)] = np.nan
prod = np.where(E, prod, np.nan)
np.savez_compressed(os.path.join(OUT, "prod_h20.npz"), prod=prod.astype(np.float64), members=M,
                    tags=np.array(tags), pct=pct)

# sanity: member agreement and learnability (xs IC dev/holdout)
fin = np.isfinite(prod)
cors = np.corrcoef(np.nan_to_num(ranks[:, fin], nan=0.5))
info = {"tags": tags, "mean_pairwise_rank_corr": float(cors[np.triu_indices(len(tags), 1)].mean()),
        "scored_rows": int(fin.sum()), "secs": round(time.time() - T0, 1)}
xs = L.xs_metrics(prod, pct, E, P, 20)
info["xs_prod"] = {k: v for k, v in xs.items() if not isinstance(v, (list, dict)) or k in ("dev", "holdout")}
json.dump(info, open(os.path.join(OUT, "prod_h20_info.json"), "w"), indent=1, default=float)
print(json.dumps(info, indent=1, default=float)[:3000])
