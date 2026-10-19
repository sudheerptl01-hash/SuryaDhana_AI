#!/usr/bin/env python3
"""Stage 12 (lab check): does L.portfolio_sim's time exit (fw.at(close,h)) let trades span a
label_block row (unadjustable CA / unexplained jump)?  fw.at checks only the segment, not label_block."""
import numpy as np
from common import L, eq_universe, save
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base"])
fw = L.Fwd(P)
eq = eq_universe(P, F)
out = {}
for h in (10, 20):
    e = fw.at(P.open.values, 1)
    x = fw.at(P.close.values, h)
    fin = np.isfinite(x / e)
    j = np.clip(fw.idx + h, 0, fw.n - 1)
    lb_inside = (fw.lb_cs[j] - fw.lb_cs) > 0
    bad = eq & fin & lb_inside & fw.exists(h)
    r = x / e - 1
    out[f"h{h}"] = {"eq_rows_tradeable": int((eq & fin).sum()), "rows_spanning_label_block": int(bad.sum()),
                    "share": float(bad.sum() / (eq & fin).sum()),
                    "mean_ret_spanning": float(np.nanmean(r[bad])), "median_ret_spanning": float(np.nanmedian(r[bad])),
                    "p5_p95": [float(np.nanquantile(r[bad], .05)), float(np.nanquantile(r[bad], .95))],
                    "mean_ret_clean": float(np.nanmean(r[eq & fin & ~lb_inside]))}
print(out)
save("s12_label_block_in_sim", out)
