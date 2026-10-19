#!/usr/bin/env python3
"""R3_verify_R3_scen v3: independent overnight-vs-session split and overnight tax.

overnight[t] = open[t]/close[t-1]-1, session[t] = close[t]/open[t]-1 (adjusted, same segment);
equal weight over names eligible (elig_base) at t-1; DEV = 2023-01-01..2025-12-31, 2026 = 2026-01-01..
Also: sensitivity without the label_block exclusion, and a robust (median-of-names) variant."""
import json
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = f"{LAB}/results/R3_verify_R3_scen"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


P = pd.read_parquet(f"{LAB}/panel.parquet", columns=["date", "entity", "open", "close", "seg_break", "label_block"])
F = pd.read_parquet(f"{LAB}/features.parquet", columns=["elig_base", "log_turn20"])
E = F["elig_base"].values.astype(bool)
lt = F["log_turn20"].values.astype("float64")
del F
n = len(P)
dates = P["date"].values.astype("datetime64[D]")
ent = P["entity"].values
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
lb = P["label_block"].values.astype(bool)
newseg = np.r_[True, ent[1:] != ent[:-1]] | P["seg_break"].values.astype(bool)
del P, ent
segid = np.cumsum(newseg) - 1
firsts = np.flatnonzero(newseg)
seg_start = firsts[segid]
seg_end = np.r_[firsts[1:] - 1, n - 1][segid]
lbcum = np.cumsum(lb)
ii = np.arange(n)
cal = np.unique(dates)
ncal = len(cal)
didx = np.searchsorted(cal, dates)
has_prev = ii - 1 >= seg_start
ip = np.maximum(ii - 1, 0)
cprev = np.where(has_prev, c[ip], np.nan)
eprev = has_prev & E[ip]
ltprev = np.where(has_prev, lt[ip], np.nan)
on = o / cprev - 1
se = c / o - 1
cc1 = c / cprev - 1
base = eprev & np.isfinite(cprev) & (cprev > 0) & (o > 0) & np.isfinite(c)


def ew(x, m):
    s = np.bincount(didx[m], weights=x[m], minlength=ncal)
    k = np.bincount(didx[m], minlength=ncal)
    return pd.Series(np.where(k > 0, s / np.maximum(k, 1), np.nan), index=pd.DatetimeIndex(cal))


def ann(sr, a, b):
    q = sr[(sr.index >= a) & (sr.index <= b)].dropna()
    return {"ann": float(np.prod(1 + q.values) ** (252 / len(q)) - 1), "mean_bps": float(q.mean() * 1e4),
            "n_days": int(len(q))}


res = {}
PER = {"dev": ("2023-01-01", "2025-12-31"), "hold": ("2026-01-01", "2100-01-01")}
for tag, m in (("excl_label_block", base & ~lb), ("incl_label_block", base)):
    for nm, x in (("overnight", on), ("session", se), ("close_to_close", cc1)):
        sr = ew(x, m)
        for per, (a, b) in PER.items():
            res[f"{tag}_{nm}_{per}"] = ann(sr, a, b)
# liquidity terciles (log_turn20 at t-1, ranked per day within the eligible set)
m0 = base & ~lb
rk = pd.Series(np.where(m0 & np.isfinite(ltprev), ltprev, np.nan)).groupby(didx).rank(pct=True).values
terc = np.full(n, -1)
fk = np.isfinite(rk)
terc[fk] = np.minimum((rk[fk] * 3).astype(int), 2)
for t_, nm_ in ((2, "liq_high"), (0, "liq_low")):
    for nm, x in (("overnight", on), ("session", se)):
        sr = ew(x, m0 & (terc == t_))
        res[f"{nm_}_{nm}_dev"] = ann(sr, *PER["dev"])
# robust: per-day MEDIAN overnight/session (not driven by a few illiquid jumps)
dfm = pd.DataFrame({"g": didx[m0], "on": on[m0], "se": se[m0]})
med = dfm.groupby("g").median()
medi = pd.DataFrame({"on": med["on"].values, "se": med["se"].values}, index=pd.DatetimeIndex(cal[med.index.values]))
for nm in ("on", "se"):
    q = medi[nm][(medi.index >= "2023-01-01") & (medi.index <= "2025-12-31")]
    res[f"median_name_{nm}_dev_mean_bps"] = float(q.mean() * 1e4)
for k, v in res.items():
    log(f"{k:45s}", v)

# ---------------------------------------------------------------- overnight tax by h (DEV, date-weighted)
g_dev0 = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
g_dev_last = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
g_hold0 = int(np.searchsorted(cal, np.datetime64("2026-01-01")))
tax = {}
for h in (5, 10, 15, 20):
    j = np.minimum(ii + h, n - 1)
    inseg = (ii + h) <= seg_end
    span = (dates[j] - dates).astype("int64")
    valid = inseg & (span <= int(np.ceil(h * 7 / 5)) + 8) & ((lbcum[j] - lbcum) == 0)
    e1 = np.where(ii + 1 <= seg_end, o[np.minimum(ii + 1, n - 1)], np.nan)
    r = np.where(valid, c[j] / e1 - 1, np.nan)
    ccx = np.where(valid, c[j] / c - 1, np.nan)
    for per, pm in (("dev", (didx >= g_dev0) & (didx + h <= g_dev_last)), ("hold", didx >= g_hold0)):
        m = E & np.isfinite(r) & np.isfinite(ccx) & pm
        a_ = ew(ccx, m).dropna()
        b_ = ew(r, m).dropna()
        gp = ew((1 + ccx) / (1 + r) - 1, m).dropna()
        mc, mr, mg = float(a_.mean()), float(b_.mean()), float(gp.mean())
        tax[f"h{h}_{per}"] = {"close_entry": mc, "open_entry": mr, "gap": mg, "fraction": (mc - mr) / mc,
                              "annual_gap_drag": mg * 252 / h}
    log("tax h", h, {k: round(v, 4) for k, v in tax[f"h{h}_dev"].items()}, {k: round(v, 4) for k, v in tax[f"h{h}_hold"].items()})
res["tax"] = tax
with open(f"{OUT}/v3_results.json", "w") as fh:
    json.dump(res, fh, indent=1)
log("done")
