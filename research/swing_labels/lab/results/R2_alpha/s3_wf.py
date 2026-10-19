"""Stage 3: walk-forward OOS scores (yearly expanding folds 2023-2026, embargo h+2 = 22, date_step 2,
n_jobs 2, default LightGBM params). Every model scores ALL U rows of each test year.

Usage: python3 s3_wf.py job [job ...]
  verify          : L.walk_forward2 vs common.wf2_imp on the 2023 fold of XR (must be bit-identical)
  XR:all          : XR_neu regression (target pct-0.5), 52 features
  BAR:all         : A2 barrier binary 1{BAR=+1}, 52 features
  TSX:all         : TSX_T5 multiclass (score = P(+1)-P(-1)), 52 features
  XR:-<group>     : XR_neu regression without one feature group (ablation)
Scores -> wf_<tag>.npz ; per-fold gain importance -> results.json s3_wf_<tag>.
"""
import sys
import time

import numpy as np

from common import OUT, L, H, GROUPS, save, wf2_imp

jobs = sys.argv[1:]
t0 = time.time()
P = L.load_panel(["date"])
F = L.load_features(L.FEATURES)
Xall = F[L.FEATURES].values.astype(np.float32)
del F
Z = np.load(f"{OUT}/labels.npz")
U = Z["U"]
TARGETS = {}
pct = Z["pct"].astype("float64")
TARGETS["XR"] = (pct - 0.5, "regression")
bar = Z["bar"].astype("float64")
yb = np.where(np.isfinite(bar), (bar == 1).astype(float), np.nan)
TARGETS["BAR"] = (yb, "binary")
TARGETS["TSX"] = (Z["tsx"].astype("float64"), "multiclass")
print("loaded", round(time.time() - t0, 1), flush=True)


class _FProxy:
    """Minimal stand-in so L.walk_forward2 can read features without reloading the parquet."""

    def __init__(self, X, cols):
        self.X, self.cols = X, list(cols)

    def __getitem__(self, feats):
        idx = [self.cols.index(f) for f in feats]

        class _V:
            values = self.X[:, idx]
        return _V


for job in jobs:
    t1 = time.time()
    if job == "verify":
        y, kind = TARGETS["XR"]
        s_lib = L.walk_forward2(y, U, P, _FProxy(Xall, L.FEATURES), H, kind=kind, test_years=(2023,),
                                date_step=2, n_jobs=2)
        s_mine, _ = wf2_imp(y, U, P, None, H, kind=kind, test_years=(2023,), date_step=2, n_jobs=2,
                            X=Xall, verbose=False)
        both = np.isfinite(s_lib) & np.isfinite(s_mine)
        info = {"scored_lib": int(np.isfinite(s_lib).sum()), "scored_mine": int(np.isfinite(s_mine).sum()),
                "nan_pattern_equal": bool((np.isfinite(s_lib) == np.isfinite(s_mine)).all()),
                "max_abs_diff": float(np.abs(s_lib[both] - s_mine[both]).max()),
                "secs": round(time.time() - t1, 1)}
        save("s3_verify_wf2_copy", info)
        print("verify", info, flush=True)
        continue
    tgt, spec = job.split(":")
    y, kind = TARGETS[tgt]
    if spec == "all":
        feats = list(L.FEATURES)
        tag = f"{tgt}_all"
    else:
        grp = spec.lstrip("-")
        feats = [f for f in L.FEATURES if f not in GROUPS[grp]]
        tag = f"{tgt}_no_{grp}"
    cols = [L.FEATURES.index(f) for f in feats]
    X = Xall if len(cols) == len(L.FEATURES) else np.ascontiguousarray(Xall[:, cols])
    sc, imps = wf2_imp(y, U, P, None, H, kind=kind, features=feats, date_step=2, n_jobs=2, X=X, verbose=True)
    if X is not Xall:
        del X
    np.savez_compressed(f"{OUT}/wf_{tag}.npz", score=sc.astype(np.float32))
    info = {"target": tgt, "kind": kind, "n_features": len(feats), "dropped": [f for f in L.FEATURES if f not in feats],
            "scored_rows": int(np.isfinite(sc).sum()), "train_rows_labelled": int((U & np.isfinite(y)).sum()),
            "secs": round(time.time() - t1, 1), "importance_gain_share_by_fold": imps}
    save(f"s3_wf_{tag}", info)
    print("done", tag, {k: v for k, v in info.items() if k != "importance_gain_share_by_fold"}, flush=True)
print("total", round(time.time() - t0, 1))
