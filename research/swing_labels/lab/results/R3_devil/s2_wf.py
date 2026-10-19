"""Stage 2 (devil): walk-forward models on the self-built label.
Usage: python3 s2_wf.py <job> [<job> ...]
  main          : L.walk_forward2 regression on pct-0.5, mask elig_base, h=20, date_step 2, n_jobs 2 (as specified)
  seedK         : same with LightGBM random_state=K (model-noise perturbation)
  trainA/trainB : train only on entity half A (resp. B) rows (target NaN elsewhere); score ALL elig rows,
                  so the other half is scored out-of-entity
"""
import sys
import time

import numpy as np

from common import OUT, L, log, save, entity_half

jobs = sys.argv[1:]
P = L.load_panel(["date", "entity"])
F = L.load_features(L.FEATURES + ["elig_base"])
E = F["elig_base"].values.astype(bool)
pct = np.load(f"{OUT}/label_h20_neumom.npz")["pct"]
y = pct - 0.5
half = entity_half(P["entity"].values)
log("loaded; half A share of elig rows", float((half[E] == 0).mean()))
for job in jobs:
    t1 = time.time()
    params = None
    yy = y
    if job.startswith("seed"):
        params = {"random_state": int(job[4:])}
    elif job == "trainA":
        yy = np.where(half == 0, y, np.nan)
    elif job == "trainB":
        yy = np.where(half == 1, y, np.nan)
    sc = L.walk_forward2(yy, E, P, F, 20, kind="regression", date_step=2, n_jobs=2, params=params, verbose=True)
    np.savez_compressed(f"{OUT}/wf_{job}.npz", score=sc)
    info = {"job": job, "secs": round(time.time() - t1, 1), "scored_rows": int(np.isfinite(sc).sum()),
            "train_rows_labelled": int((E & np.isfinite(yy)).sum())}
    if job == "main":
        try:
            s2 = np.load(f"{L.LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
            b = np.isfinite(sc) & np.isfinite(s2)
            info["vs_R2_rel_score"] = {"finite_mismatch": int((np.isfinite(sc) != np.isfinite(s2)).sum()),
                                       "corr": float(np.corrcoef(sc[b], s2[b])[0, 1]),
                                       "max_abs_diff": float(np.abs(sc[b] - s2[b]).max())}
        except Exception as e:  # noqa: BLE001
            info["vs_R2_rel_score"] = str(e)
    save(f"s2_wf_{job}", info)
    log("done", info)
