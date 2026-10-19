"""Stage 3: walk-forward models (L.walk_forward2; yearly expanding folds 2023-2026, embargo h+2,
date_step=2, n_jobs=2, default LightGBM params, 52 PIT features). Scores ALL elig_base rows of each
test year. Usage: python3 s3_wf.py <h> <neut> <form> [<h> <neut> <form> ...]
  form RANK -> regression on pct-0.5 ; C30/C20/C33 -> multiclass (score = P(+1)-P(-1));
  T30 -> binary top-30 (score = P(top)); B30 -> binary bottom-30 (stored score = -P(bottom), so
  higher = better long candidate for every model).
"""
import sys
import time

import numpy as np

from common import OUT, L, save, form_label

args = sys.argv[1:]
jobs = [(int(args[i]), args[i + 1], args[i + 2]) for i in range(0, len(args), 3)]
t0 = time.time()
P = L.load_panel(["date"])
F = L.load_features(L.FEATURES)
E = np.load(f"{OUT}/meta.npz")["E"]
print("loaded", round(time.time() - t0, 1), flush=True)
for h, nt, form in jobs:
    t1 = time.time()
    tag = f"h{h}_{nt}_{form}"
    pct = np.load(f"{OUT}/labels_h{h}.npz")[f"pct_{nt}"].astype("float64")
    y = form_label(pct, form)
    kind = {"RANK": "regression", "C30": "multiclass", "C20": "multiclass", "C33": "multiclass"}.get(form, "binary")
    sc = L.walk_forward2(y, E, P, F, h, kind=kind, date_step=2, n_jobs=2, verbose=True)
    if form.startswith("B"):
        sc = -sc
    np.savez_compressed(f"{OUT}/wf_{tag}.npz", score=sc.astype(np.float32))
    info = {"h": h, "neut": nt, "form": form, "kind": kind, "secs": round(time.time() - t1, 1),
            "scored_rows": int(np.isfinite(sc).sum()), "train_rows_labelled": int((E & np.isfinite(y)).sum())}
    save(f"s3_wf_{tag}", info)
    print("done", tag, info, flush=True)
