#!/usr/bin/env python3
"""Stage 8: what does each label teach?  Feature profile of every model's long top-20 picks
(and bottom-20 F&O shorts) vs the eq universe on the same dates, pick overlap (Jaccard) between
models, and names per cohort that are in the F&O proxy."""
import glob
import os

import numpy as np
import pandas as pd

from common import OUT, L, eq_universe, save
from simlib import Engine

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block", "raw_close"])
COLS = ["vol_20", "atr_pct", "mom_5", "mom_20", "mom_60", "dist_sma50", "dist_sma200", "hi52_dist", "rsi_14",
        "log_turn20", "beta_60", "idio_vol_60", "volz_20", "deliv_pct", "up_frac_20", "max_ret_20", "min_ret_20"]
F = L.load_features(COLS + ["elig_base", "fno_proxy"])
fw = L.Fwd(P)
eng = Engine(P, F, fw)
eq = eq_universe(P, F)
fno = eq & F["fno_proxy"].values
dates = P["date"].values.astype("datetime64[D]")
names = sorted(os.path.basename(p)[3:-4] for p in glob.glob(f"{OUT}/wf_*.npz"))
START, END = "2023-01-01", "2026-09-10"
picks = {}
out = {"profile_long": {}, "profile_short_fno": {}}
first = None
for n in names:
    sc = np.load(f"{OUT}/wf_{n}.npz")["score"].astype(float)
    pk = eng.pick(sc, eq, "eq", 10, start=START, end=END)
    if first is None:
        first = pk
    rows = np.concatenate([p for _, p in pk])
    picks[n] = {d: set(p.tolist()) for d, p in pk}
    prof = {c: float(np.nanmedian(F[c].values[rows])) for c in COLS}
    prof["raw_close_median"] = float(np.median(P["raw_close"].values[rows]))
    prof["fno_share"] = float(F["fno_proxy"].values[rows].mean())
    prof["unique_entities"] = int(len(np.unique(P["entity"].values[rows])))
    prof["n_picks"] = int(len(rows))
    out["profile_long"][n] = prof
    pks = eng.pick(sc, fno, "fno", 10, side="short", start=START, end=END)
    rs = np.concatenate([p for _, p in pks])
    out["profile_short_fno"][n] = {c: float(np.nanmedian(F[c].values[rs])) for c in COLS}
# universe profile on the same signal dates
sig = np.array([d for d, _ in first])
um = eq & np.isin(dates, sig)
out["profile_universe"] = {c: float(np.nanmedian(F[c].values[um])) for c in COLS}
out["profile_universe"]["raw_close_median"] = float(np.median(P["raw_close"].values[um]))
out["profile_universe"]["fno_share"] = float(F["fno_proxy"].values[um].mean())
umf = fno & np.isin(dates, sig)
out["profile_universe_fno"] = {c: float(np.nanmedian(F[c].values[umf])) for c in COLS}
jac = {}
for i, a in enumerate(names):
    for b in names[i + 1:]:
        js = [len(picks[a][d] & picks[b][d]) / max(1, len(picks[a][d] | picks[b][d])) for d in picks[a]]
        jac[f"{a}|{b}"] = float(np.mean(js))
out["jaccard_top20"] = jac
save("s8_profile", out)
df = pd.DataFrame(out["profile_long"]).T
df.loc["UNIVERSE"] = pd.Series(out["profile_universe"])
print(df.round(3).to_string())
print(pd.Series(jac).round(3).to_string())
