"""Stage 3: walk-forward models (L.walk_forward2: expanding yearly folds 2023-2026, embargo h+2,
date_step=2, n_jobs=2, scores ALL U rows in each test year). Features = L.FEATURES (lab v2).
Usage: python3 s3_wf.py TAG [TAG ...]
"""
import os
import sys
import time

import numpy as np

from common import OUT, L, save

SPECS = {
    # tag: (h, label key, kind, transform)
    "M_REL": (20, "pct", "regression", "pct"),      # pure relative (XR_neu) regression on pct-0.5
    "M_RUP": (20, "REL", "binary", "up"),           # P(REL top-30%)
    "M_RDN": (20, "REL", "binary", "dn"),           # P(REL bottom-30%)  -> relative avoid model
    "M_ABS": (20, "ABS", "binary", "up"),           # P(r > +50bp)       -> pure absolute
    "M_BAR": (20, "BAR", "binary", "up"),           # P(A2 barrier +1)   -> pure absolute, path
    "M_DUAL": (20, "DUAL", "binary", "up"),         # P(DUAL +1)
    "M_DUALP": (20, "DUALP", "binary", "up"),       # P(DUALP +1)
    "M_DDN": (20, "DUAL", "binary", "dn"),          # P(DUAL -1)         -> dual avoid model
    "M_DUALmc": (20, "DUAL", "multiclass", "mc"),   # P(+1)-P(-1) of DUAL
    "M_RELG": (20, "pct", "regression", "pct"),     # pure relative, trained+scored only on G_trend rows
    "M_DUALt300": (20, "DUAL_t300", "binary", "up"),  # stricter absolute leg: r > +300bp
    "M_REL10": (10, "pct", "regression", "pct"),
    "M_DUAL10": (10, "DUAL", "binary", "up"),
}

tags = sys.argv[1:]
t0 = time.time()
U = np.load(f"{OUT}/meta.npz")["U"]
P = L.load_panel(["date", "entity"])
F = L.load_features(L.FEATURES)
GATE = U & (F["dist_sma200"].values > 0) & (F["xr_mom60"].values > 0.7)   # input-side sample filter
print("loaded", round(time.time() - t0, 1), flush=True)
for tag in tags:
    h, key, kind, tf = SPECS[tag]
    fn = f"{OUT}/wf_{tag}.npz"
    if os.path.exists(fn):
        print("exists", tag)
        continue
    Zl = np.load(f"{OUT}/labels_h{h}.npz")
    if key == "DUAL_t300":
        rel, rr = Zl["REL"].astype("float64"), Zl["r"].astype("float64")
        lab = np.where((rel == 1) & (rr > 0.03), 1.0, np.where((rel == -1) & (rr < -0.03), -1.0, 0.0))
        lab[~np.isfinite(rel) | ~np.isfinite(rr)] = np.nan
    else:
        lab = Zl[key].astype("float64")
    mask = GATE if tag == "M_RELG" else U
    if tf == "pct":
        y = lab - 0.5
    elif tf == "up":
        y = np.where(np.isfinite(lab), (lab == 1).astype(float), np.nan)
    elif tf == "dn":
        y = np.where(np.isfinite(lab), (lab == -1).astype(float), np.nan)
    else:
        y = lab
    t1 = time.time()
    score = L.walk_forward2(y, mask, P, F, h, kind=kind, features=L.FEATURES, date_step=2, n_jobs=2, verbose=True)
    np.savez_compressed(fn, score=score.astype(np.float32))
    save(f"s3_wf_{tag}", {"h": h, "label": key, "kind": kind, "transform": tf, "secs": time.time() - t1,
                          "train_pos_rate": float(np.nanmean(y[mask])) if kind == "binary" else None,
                          "mask_rows": int(mask.sum()), "scored_rows": int(np.isfinite(score[mask]).sum())})
    print("done", tag, round(time.time() - t1, 1), flush=True)
