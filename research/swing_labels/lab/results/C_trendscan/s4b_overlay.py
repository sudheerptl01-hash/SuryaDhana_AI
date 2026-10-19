#!/usr/bin/env python3
"""Stage 4b: long-only uses of a two-sided score that do not rely on the extreme top-20 tail.
Pre-registered (before looking at any model's overlay result):
  avoid30   : drop the bottom 30% of the date's scores, then 20 RANDOM picks from the rest
              (value of the 'down/avoid' side for a cash-only trader who cannot short)
  top30rand : 20 RANDOM picks from the top 30% of the date's scores (broad tilt, no tail bet)
Both vs. 20 random picks from the whole eq universe; 5 seeds each; fixed 10d and 20d exits; 50/80 bps.
usage: python3 s4b_overlay.py [names...]"""
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, eq_universe, save
from simlib import Engine, run

t0 = time.time()
names = sys.argv[1:] or sorted(os.path.basename(p)[3:-4] for p in glob.glob(f"{OUT}/wf_*.npz"))
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "fno_proxy", "atr_pct"])
fw = L.Fwd(P)
eng = Engine(P, F, fw)
eq = eq_universe(P, F)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
START, END = "2023-01-01", "2026-09-10"
SEEDS = (0, 1, 2, 3, 4)


def dev_end(h):
    j = np.searchsorted(cal, np.datetime64("2026-01-01")) - 1
    return cal[j - h]


def summarize(picks_by_seed, rule_h):
    out = {}
    for cost in (50.0, 80.0):
        for wn in ("full", "dev", "hold2026"):
            acc = []
            for pk in picks_by_seed:
                if wn == "dev":
                    pk = [(d, p) for d, p in pk if d <= dev_end(rule_h)]
                elif wn == "hold2026":
                    pk = [(d, p) for d, p in pk if d >= np.datetime64("2026-01-01")]
                r = run(eng, pk, rule="fixed", h=rule_h, side="long", h_slots=rule_h, step=5, cost_bps=cost)
                acc.append(r)
            d = {f: float(np.mean([a[f] for a in acc])) for f in ("cagr", "sharpe", "sharpe_rho_adj", "max_dd",
                                                                 "hit_rate", "mean_trade_net")}
            d["cagr_sd_seeds"] = float(np.std([a["cagr"] for a in acc]))
            if wn == "full":
                yrs = sorted(acc[0]["by_year"])
                d["by_year"] = {int(y): float(np.mean([a["by_year"][y] for a in acc])) for y in yrs}
            out[f"fixed{rule_h}_c{int(cost)}_{wn}"] = d
    return out


res = {}
for name in names:
    sc = np.load(f"{OUT}/wf_{name}.npz")["score"].astype(float)
    m = eq & np.isfinite(sc) & (dates >= np.datetime64(START))
    pr = np.full(len(sc), np.nan)
    pr[m] = pd.Series(sc[m]).groupby(dates[m]).rank(pct=True).values
    blk = {}
    for ov, mk in (("avoid30", m & (pr > 0.3)), ("top30rand", m & (pr > 0.7))):
        for h in (10, 20):
            pks = [eng.pick(None, mk, f"{name}_{ov}", h, start=START, end=END, random_seed=s) for s in SEEDS]
            blk[f"{ov}_h{h}"] = summarize(pks, h)
    res[name] = blk
    print(name, {k: round(v["fixed10_c50_dev"]["cagr"] if "fixed10_c50_dev" in v else v["fixed20_c50_dev"]["cagr"], 4)
                 for k, v in blk.items()}, round(time.time() - t0, 1), flush=True)
# matching random baseline over the same eq universe (identical function, mask = all scored rows)
if "s4b_random" not in (__import__("common").load_res()):
    any_sc = np.load(f"{OUT}/wf_{names[0]}.npz")["score"].astype(float)
    m = eq & np.isfinite(any_sc) & (dates >= np.datetime64(START))
    base = {}
    for h in (10, 20):
        pks = [eng.pick(None, m, "rand_scored", h, start=START, end=END, random_seed=s) for s in SEEDS]
        base[f"random_h{h}"] = summarize(pks, h)
    save("s4b_random", base)
for name, blk in res.items():
    save(f"s4b_{name}", blk)
print("done", round(time.time() - t0, 1))
