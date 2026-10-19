#!/usr/bin/env python3
"""Stage 7: investability of each walk-forward canary score (fastsim == lablib.portfolio_sim).
Long top-20 every 5 days, h=10, 50/80 bps; short bottom-20 on fno_proxy (F&O-shortable proxy).
Also: share of picks that are ETFs (ISIN INF..) and that have a 2026-snapshot sector (look-ahead)."""
import os

import numpy as np
import pandas as pd

from common import OUT, L, load_res, save
from fastsim import Sim

H, STEP, K = 10, 5, 20
P = L.load_panel(["date", "entity", "isin", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "fno_proxy", "sector"])
fw = L.Fwd(P)
sim = Sim(P, fw, H)
eb = F.elig_base.values
fno = eb & F.fno_proxy.values
etf = pd.Series(P["isin"].values).str.startswith("INF").values
known = F.sector.values != "NA"
W = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", "2026-09-10"), "full": ("2023-01-01", "2026-09-10")}
res = load_res().get("s7_wf_portfolios", {})
for var in ("base", "nosec", "shuf", "leak", "leak1d"):
    fn = os.path.join(OUT, f"wf_{var}.npz")
    if not os.path.exists(fn):
        continue
    sc = np.load(fn)["score"].astype(float)
    R = {}
    for win in ("dev", "hold", "full"):
        for cost in (50.0, 80.0):
            r = sim.run(sc, eb, "eb", step=STEP, top_k=K, cost_bps=cost, start=W[win][0], end=W[win][1],
                        return_cohorts=True)
            pk = r.pop("picks")
            r.pop("cohort_rets")
            r.pop("cohort_dates")
            if cost == 50.0:
                r["etf_share_of_picks"] = float(etf[pk].mean())
                r["sector_known_share_of_picks"] = float(known[pk].mean())
            R[f"long_{win}_{int(cost)}"] = r
        rs = sim.run(sc, fno, "fno", step=STEP, top_k=K, side="short", cost_bps=50.0, start=W[win][0], end=W[win][1])
        R[f"short_fno_{win}_50"] = rs
        rl = sim.run(sc, fno, "fno", step=STEP, top_k=K, side="long", cost_bps=50.0, start=W[win][0], end=W[win][1])
        R[f"long_fno_{win}_50"] = rl
    R["random_sector_known_share_elig"] = float(known[eb].mean())
    R["random_etf_share_elig"] = float(etf[eb].mean())
    res[var] = R
    print(var, {k: (round(v["cagr"], 4), round(v["sharpe"], 3), v["by_year"]) for k, v in R.items() if isinstance(v, dict)}, flush=True)
# random fno baselines (3 seeds) for the short/long fno comparisons
rb = {}
for win in ("dev", "hold", "full"):
    for side in ("long", "short"):
        cs = []
        for sd in range(5):
            r = sim.run(None, fno, "fno", step=STEP, top_k=K, side=side, cost_bps=50.0, start=W[win][0], end=W[win][1],
                        random_seed=sd)
            cs.append((r["cagr"], r["sharpe"]))
        rb[f"{side}_fno_{win}_50"] = {"cagr_mean": float(np.mean([c[0] for c in cs])),
                                      "sharpe_mean": float(np.mean([c[1] for c in cs]))}
res["random_fno_5seeds"] = rb
print(rb)
save("s7_wf_portfolios", res)
