#!/usr/bin/env python3
"""Stage 7: label-execution mismatch under PERFECT foresight of the label.
If a model predicted the label exactly, how much of the label's 'natural' move can an executable
exit capture?  For each label and class (+1 long, -1 short), sample <=60k eq rows (2023-2025 and
2026 separately), exit them with fixed 10d / fixed 20d / ATR trail (m=2,3) / running trend-scan exit
and report mean NET (50 bp) return, bars held, net per bar.  Unconditional rows = baseline."""
import numpy as np
import pandas as pd

from common import OUT, L, eq_universe, make_label, save
from simlib import Engine

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "fno_proxy", "atr_pct", "vol_20"])
fw = L.Fwd(P)
eng = Engine(P, F, fw)
eq = eq_universe(P, F)
Z = dict(np.load(f"{OUT}/labels.npz"))
dates = P["date"].values.astype("datetime64[D]")
yr = pd.DatetimeIndex(dates).year.values
rng = np.random.default_rng(11)
RULES = [("fixed10", dict(rule="fixed", h=10)), ("fixed20", dict(rule="fixed", h=20)),
         ("atr2", dict(rule="atr", m=2.0)), ("atr3", dict(rule="atr", m=3.0)), ("tsexit", dict(rule="tsexit", t_exit=0.0))]
natural = {"TSA_T5": Z["tsA_r"], "TSX_T5": Z["tsX_r"], "FP20": Z["fp20_ret"], "RA10": Z["r10"], "FX10_pm50": Z["r10"],
           "FX20_pm50": Z["r20"], "MQ_vol1.0": Z["r20"]}
out = {}
base_ok = eq & Z["v20"] & (yr >= 2023)
for name in ["ALL", "TSA_T5", "TSX_T5", "MQ_vol1.0", "FP20", "RA10", "FX10_pm50", "FX20_pm50"]:
    y = np.zeros(len(eq)) if name == "ALL" else make_label(name, Z, F["vol_20"].values)
    for cl, side in ((1, "long"), (-1, "short")):
        if name == "ALL" and cl == -1:
            side = "short"
        for wn, wsel in (("dev", yr <= 2025), ("2026", yr == 2026)):
            sel = base_ok & wsel & ((y == cl) if name != "ALL" else True)
            idx = np.flatnonzero(sel)
            if len(idx) > 60000:
                idx = np.sort(rng.choice(idx, 60000, replace=False))
            d = {"n_pool": int(sel.sum())}
            if name != "ALL":
                nat = natural[name].astype(float)[idx]
                d["natural_net"] = float(np.nanmean((nat if side == "long" else -nat)) - 0.005)
            for rn, kw in RULES:
                r, k = eng.exit_returns(idx, side=side, **kw)
                net = r - 0.005
                d[rn] = {"net": float(np.nanmean(net)), "bars": float(np.nanmean(k)),
                         "net_per_bar_bps": float(np.nanmean(net) / np.nanmean(k) * 1e4), "hit": float(np.nanmean(net > 0))}
            out[f"{name}|{cl:+d}|{wn}"] = d
            print(name, cl, wn, d.get("natural_net"), {rn: round(d[rn]["net"] * 100, 2) for rn, _ in RULES}, flush=True)
save("s7_oracle", out)
