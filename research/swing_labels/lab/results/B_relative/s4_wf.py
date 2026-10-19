"""Stage 4: walk-forward learnability (L.walk_forward: expanding yearly folds 2023-2026, embargo h+2,
date_step=2, n_jobs=2). Features = L.FEATURES minus sec_rel_mom20 (auditor HIGH leak).
Usage: python3 s4_wf.py <tag> <h> <target> <regression|binary|multiclass> [years csv]
  target: pct_raw | pct_vn | pct_neu | pct_br50 ...  (regression on xs percentile - 0.5)
          XR_<k>_30 (binary: +1 vs rest; multiclass: -1/0/+1)
"""
import json
import sys
import time

import numpy as np

from common import FEATS, OUT, L, save

tag, h, tgt, kind = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
years = tuple(int(y) for y in sys.argv[5].split(",")) if len(sys.argv) > 5 else (2023, 2024, 2025, 2026)
t0 = time.time()
Z = np.load(f"{OUT}/labels_h{h}.npz")
if tgt in Z.files:
    y = Z[tgt].astype("float64")
else:
    y = np.load(f"{OUT}/labels_h{h}_v.npz")[tgt].astype("float64")
if kind == "regression":
    y = y - 0.5
elif kind == "binary":
    y = np.where(np.isnan(y), np.nan, (y == 1).astype(float))
U = np.load(f"{OUT}/meta.npz")["U"]
P = L.load_panel(["date", "entity"])
F = L.load_features(FEATS)
mask = U & ~np.isnan(y)
print("loaded", round(time.time() - t0, 1), "n", int(mask.sum()), flush=True)
score, met = L.walk_forward(y, mask, P, F, h, kind=kind, features=FEATS, test_years=years, date_step=2, n_jobs=2)
met.update({"tag": tag, "h": h, "target": tgt, "kind": kind, "n_features": len(FEATS), "secs": time.time() - t0})
suffix = "" if len(years) == 4 else "_" + "-".join(map(str, years))
np.savez_compressed(f"{OUT}/wf_{tag}{suffix}.npz", score=score.astype(np.float32))
save(f"s4_wf_{tag}{suffix}", met)
print("done", tag, round(time.time() - t0, 1), json.dumps({k: v for k, v in met.items() if k != "folds"}), flush=True)
