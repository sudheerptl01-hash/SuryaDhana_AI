"""Stage 3: walk-forward learnability (L.walk_forward, yearly expanding folds, embargo h+2,
date_step=2, n_jobs=2). Usage: python3 s3_wf.py <cid> <side> <binary|multiclass> [years csv]
Saves OOS score (npz) + metrics json; can be run fold-subsets and merged.
"""
import json
import os
import sys
import time

import numpy as np

from abar import L, OUT, update_results

cid, side, kind = sys.argv[1], sys.argv[2], sys.argv[3]
years = tuple(int(y) for y in sys.argv[4].split(",")) if len(sys.argv) > 4 and sys.argv[4] != "all" else (2023, 2024, 2025, 2026)
fset = sys.argv[5] if len(sys.argv) > 5 else "full"
MKT = ["mkt_mom5", "mkt_mom20", "mkt_mom60", "mkt_dist_sma50", "mkt_dist_sma200", "mkt_vol20", "vix",
       "breadth50", "breadth_ad", "dispersion"]
feats = [f for f in L.FEATURES if f not in MKT] if fset == "nomkt" else list(L.FEATURES)
h = int(cid[1:3])
t0 = time.time()
lab = np.load(f"{OUT}/labels_{'control' if cid.startswith('T') else 'shortlist'}.npz")[f"{cid}_{side}_lab"].astype("float64")
P = L.load_panel(["date", "entity"])
F = L.load_features(L.FEATURES + ["elig_base"])
mask = F["elig_base"].values.astype(bool) & ~np.isnan(lab)
if kind == "binary":
    y = np.where(np.isnan(lab), np.nan, (lab == 1).astype(float))
else:
    y = lab
print("loaded", round(time.time() - t0, 1), flush=True)
score, met = L.walk_forward(y, mask, P, F, h, kind=kind, features=feats, test_years=years, date_step=2, n_jobs=2)
met["features"] = feats
tag = f"{cid}_{side}_{kind}_" + "-".join(str(x) for x in years) + ("" if fset == "full" else f"_{fset}")
np.savez_compressed(f"{OUT}/wf_{tag}.npz", score=score.astype(np.float32))
with open(f"{OUT}/wf_{tag}.json", "w") as fh:
    json.dump(met, fh, indent=1)
update_results(f"wf_{tag}", met)
print("done", tag, round(time.time() - t0, 1), json.dumps({k: v for k, v in met.items() if k != "folds"}))
