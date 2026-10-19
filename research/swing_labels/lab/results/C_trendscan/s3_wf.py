#!/usr/bin/env python3
"""Stage 3: one full walk-forward (multiclass LightGBM, yearly folds 2023-2026, embargo h+2,
date_step=2, n_jobs=2, features = L.FEATURES minus sec_rel_mom20) per invocation.
usage: python3 s3_wf.py <label_name>"""
import sys
import time

import numpy as np

from common import FEATS, OUT, WF_SET, L, eq_universe, make_label, save, wf_all

name = sys.argv[1]
h = WF_SET[name]
t0 = time.time()
P = L.load_panel(["date", "entity"])
F = L.load_features(FEATS + ["elig_base"])
Z = dict(np.load(f"{OUT}/labels.npz"))
eq = eq_universe(P, F)
y = make_label(name, Z, F["vol_20"].values)
print(name, "h", h, "labeled eq rows", int((eq & np.isfinite(y)).sum()), "load", round(time.time() - t0, 1), flush=True)
score, met = wf_all(y, eq, P, F, h=h, kind="multiclass", date_step=2, n_jobs=2)
met["seconds"] = time.time() - t0
met["features"] = FEATS
met["embargo_h"] = h
np.savez_compressed(f"{OUT}/wf_{name}.npz", score=score.astype("float32"))
save(f"s3_wf_{name}", met)
print("done", name, round(time.time() - t0, 1), {k: v for k, v in met.items() if k.startswith("mean_")}, flush=True)
