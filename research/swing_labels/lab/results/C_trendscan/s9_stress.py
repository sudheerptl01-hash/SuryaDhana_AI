#!/usr/bin/env python3
"""Stage 9: robustness of the long top-20 results (no re-selection, same models):
  (a) cost ladder 50/80/100/130 bp and break-even cost (dev, 2026) for fixed 10d and 20d holds;
  (b) liquidity: same model scores, universe restricted to elig_liq5 (20d turnover >= Rs 5 cr),
      vs a random baseline on the same restricted universe (5 seeds)."""
import glob
import os

import numpy as np

from common import OUT, L, eq_universe, save
from simlib import Engine, run

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "elig_liq5", "fno_proxy", "atr_pct"])
fw = L.Fwd(P)
eng = Engine(P, F, fw)
eq = eq_universe(P, F)
liq5 = eq & F["elig_liq5"].values
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
names = sorted(os.path.basename(p)[3:-4] for p in glob.glob(f"{OUT}/wf_*.npz"))
START, END = "2023-01-01", "2026-09-10"


def dev_end(h):
    j = np.searchsorted(cal, np.datetime64("2026-01-01")) - 1
    return cal[j - h]


def win(pk, wn, h):
    if wn == "dev":
        return [(d, p) for d, p in pk if d <= dev_end(h)]
    return [(d, p) for d, p in pk if d >= np.datetime64("2026-01-01")]


out = {}
for n in names + ["RANDOM"]:
    sc = None if n == "RANDOM" else np.load(f"{OUT}/wf_{n}.npz")["score"].astype(float)
    res = {}
    for uni, mk in (("eq", eq), ("liq5", liq5)):
        seeds = (0, 1, 2, 3, 4) if n == "RANDOM" else (None,)
        for h in (10, 20):
            pks = [eng.pick(sc, mk, uni, h, start=START, end=END, random_seed=s) for s in seeds]
            for wn in ("dev", "2026"):
                gross = []
                cg = {}
                for cost in (50, 80, 100, 130):
                    vals = [run(eng, win(pk, wn, h), rule="fixed", h=h, side="long", h_slots=h, step=5, cost_bps=cost)
                            for pk in pks]
                    cg[cost] = {"cagr": float(np.mean([v["cagr"] for v in vals])),
                                "sharpe": float(np.mean([v["sharpe"] for v in vals])),
                                "mean_trade_net": float(np.mean([v["mean_trade_net"] for v in vals]))}
                    if cost == 50:
                        gross = float(np.mean([v["mean_trade_net"] for v in vals])) + 0.005
                res[f"{uni}_h{h}_{wn}"] = {"by_cost": cg, "mean_trade_gross": gross,
                                           "breakeven_cost_bps_trade": gross * 1e4}
    out[n] = res
    print(n, {k: (round(v["by_cost"][50]["cagr"], 3), round(v["by_cost"][80]["cagr"], 3), round(v["by_cost"][130]["cagr"], 3),
                  round(v["breakeven_cost_bps_trade"])) for k, v in res.items()}, flush=True)
save("s9_stress", out)
