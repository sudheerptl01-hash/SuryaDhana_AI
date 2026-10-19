"""Stage 7: importance stability by year (gain share per walk-forward fold) for XR_all / BAR_all / TSX_all.

Per model: group-level gain shares by fold (2023..2026 test-year models; each fold is trained only on
data before that year), top-10 features per fold, Spearman correlation of the 52-feature importance
vectors between folds, and the rank of every feature in every fold (stability = std of ranks).
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import L, GROUPS, FEAT_GROUP, save, load_res

res = load_res()
out = {}
for tag in ("XR_all", "BAR_all", "TSX_all"):
    sec = res.get(f"s3_wf_{tag}")
    if not sec:
        continue
    imp = pd.DataFrame(sec["importance_gain_share_by_fold"])          # rows: features, cols: folds
    imp = imp.reindex(L.FEATURES)
    grp = imp.groupby(imp.index.map(FEAT_GROUP)).sum()
    ranks = imp.rank(ascending=False)
    folds = list(imp.columns)
    sp = {f"{a}~{b}": float(spearmanr(imp[a], imp[b]).correlation) for i, a in enumerate(folds) for b in folds[i + 1:]}
    rec = {"group_share_by_fold": grp.round(4).to_dict(),
           "top10_by_fold": {f: imp[f].sort_values(ascending=False).head(10).round(4).to_dict() for f in folds},
           "spearman_between_folds": sp,
           "mean_share": imp.mean(axis=1).sort_values(ascending=False).round(4).to_dict(),
           "rank_std_top15": ranks.loc[imp.mean(axis=1).sort_values(ascending=False).index[:15]].std(axis=1).round(2).to_dict(),
           "rank_by_fold_top15": ranks.loc[imp.mean(axis=1).sort_values(ascending=False).index[:15]].astype(int).to_dict()}
    out[tag] = rec
    print(tag)
    print(grp.round(3))
    print(sp)
save("s7_importance", out)
