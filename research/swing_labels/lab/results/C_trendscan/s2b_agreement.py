#!/usr/bin/env python3
"""Stage 2b: how different are the adaptive / move-quality labels from plain fixed-horizon labels?
Pairwise agreement and crosstabs on the eq universe (rows where both labels are defined), plus
per-year +1/-1 shares in the dev window (2023-2025) vs the 2026 holdout for the WF candidates."""
import numpy as np
import pandas as pd

from common import OUT, L, eq_universe, make_label, save

P = L.load_panel(["date", "entity"])
F = L.load_features(["elig_base", "vol_20"])
Z = dict(np.load(f"{OUT}/labels.npz"))
eq = eq_universe(P, F)
names = ["TSA_T5", "TSX_T5", "MQ_vol1.0", "FP20", "RA10", "RA20", "FX10_pm50", "FX20_pm50"]
labs = {n: make_label(n, Z, F["vol_20"].values) for n in names}
out = {"agree_same_class": {}, "kappa": {}, "crosstab": {}}
for i, a in enumerate(names):
    for b in names[i + 1:]:
        m = eq & np.isfinite(labs[a]) & np.isfinite(labs[b])
        x, y = labs[a][m], labs[b][m]
        po = float((x == y).mean())
        pe = float(sum((x == c).mean() * (y == c).mean() for c in (-1, 0, 1)))
        out["agree_same_class"][f"{a}|{b}"] = po
        out["kappa"][f"{a}|{b}"] = (po - pe) / (1 - pe)
for a, b in (("TSA_T5", "FX20_pm50"), ("TSA_T5", "FX10_pm50"), ("TSA_T5", "RA20"), ("MQ_vol1.0", "FP20")):
    m = eq & np.isfinite(labs[a]) & np.isfinite(labs[b])
    ct = pd.crosstab(labs[a][m], labs[b][m], normalize=True).round(4)
    out["crosstab"][f"{a}|{b}"] = {str(int(r)): {str(int(c)): float(ct.loc[r, c]) for c in ct.columns} for r in ct.index}
save("s2b_agreement", out)
for k, v in out["kappa"].items():
    print(k, round(out["agree_same_class"][k], 3), round(v, 3))
print(out["crosstab"])
