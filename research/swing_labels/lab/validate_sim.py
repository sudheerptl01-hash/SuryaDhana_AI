#!/usr/bin/env python3
"""Validate lablib.Sim against hand calculations and known-answer canaries."""
import json
import os
import sys

import numpy as np

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

P = L.load_panel(["date", "entity", "symbol", "isin", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "atr_pct", "mom_20"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
m = F.elig_base.values
out = {}

# 1. hand calculation: one stock, h=10, step=10, top_k=1, score = mom_20, single cohort window
h = 10
r = S.run(F.mom_20.values, m, h, step=10, top_k=1, start="2024-03-01", end_exit="2024-03-29",
          cost_bps=50, keep_trades=True)
g = int(np.searchsorted(S.cal, np.datetime64("2024-03-01")))
cand = S.rows_on(g)
cand = cand[m[cand] & np.isfinite(F.mom_20.values[cand])]
i = cand[np.argmax(F.mom_20.values[cand])]
e = P.open.values[i + 1]
x = P.close.values[i + h]
hand = (x / e - 1) - 0.005
out["hand_trade"] = {"symbol": P.symbol.values[i], "hand_net": float(hand),
                     "sim_trade_net": r["_trades"][0][2] if r.get("_trades") else None,
                     "sim_total_return": r["total_return"],
                     "hand_total_return_slot": float((1 - 0.0025) * (x / e) * (1 - 0.0025) - 1)}

# 2. random baselines (dev) at h=10 and h=20
for hh in (10, 20):
    rb = S.random_band(m, hh, seeds=(1, 2, 3), step=5, top_k=20, cost_bps=50)
    out[f"random_h{hh}"] = {k: v for k, v in rb.items() if not k.startswith("_")}

# 3. canaries: perfect foresight and its negation
fr = L.fwd_return(P, fw, 10)
cmp_ = S.compare(fr, m, 10, seeds=(1, 2), step=5, top_k=20, cost_bps=50)
out["canary_foresight"] = {k: cmp_[k] for k in ("cagr", "sharpe", "max_dd", "excess_daily_nw_t", "exposure", "forced_exits")}
cmp2 = S.compare(-fr, m, 10, seeds=(1, 2), step=5, top_k=20, cost_bps=50)
out["canary_anti_foresight"] = {k: cmp2[k] for k in ("cagr", "sharpe", "max_dd", "excess_daily_nw_t")}
# 4. barrier exits run and produce sane exposure
rbar = S.run(F.mom_20.values, m, 20, step=5, top_k=20, exit_rule="barrier", pt=2.0, sl=2.0, cost_bps=50)
out["barrier_mom20"] = {k: rbar[k] for k in ("cagr", "sharpe", "max_dd", "exposure", "avg_bars", "trades")}
# 5. old vs new sim on the same random picks (expect similar CAGR, lower new Sharpe)
old = L.portfolio_sim(np.zeros(len(P)), m, P, F, fw, 10, step=5, top_k=20, random_seed=1,
                      start="2023-01-01", end="2025-12-15")
out["old_portfolio_sim_random_seed1"] = {k: old[k] for k in ("cagr", "sharpe", "max_dd")}
print(json.dumps(out, indent=1, default=float))
json.dump(out, open(os.path.join(LAB, "validate_sim.json"), "w"), indent=1, default=float)
