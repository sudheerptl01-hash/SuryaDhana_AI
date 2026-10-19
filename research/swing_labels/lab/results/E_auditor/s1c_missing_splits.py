#!/usr/bin/env python3
"""Stage 1c: refine the 'missed split/bonus' detector (exclude market-wide shock days and
lower-circuit locks) and measure label/feature materiality of all residual CA defects."""
import numpy as np
import pandas as pd

from common import L, save

P = L.load_panel(["date", "entity", "symbol", "series", "close", "high", "low", "raw_close", "raw_open",
                  "ca_event", "ca_ratio", "label_block", "volume", "seg_break"])
F = L.load_features(["elig_base", "fno_proxy"])
n = len(P)
ent = P.entity.values
newent = np.r_[True, ent[1:] != ent[:-1]]
rc, ro, c = P.raw_close.values, P.raw_open.values, P.close.values
lb = P.label_block.values
ratio = P.ca_ratio.values
dates = P.date.values.astype("datetime64[D]")
eb = F.elig_base.values
fno = F.fno_proxy.values
rc_prev = np.r_[np.nan, rc[:-1]]
rc_prev[newent] = np.nan
oj = ro / rc_prev
cj = rc / rc_prev
mk = L.market_series("Nifty 500")
mgap = (mk.open / mk.close.shift() - 1).reindex(pd.DatetimeIndex(P.date.values)).values
mday = (mk.close / mk.close.shift() - 1).reindex(pd.DatetimeIndex(P.date.values)).values
ca_near = np.zeros(n, bool)
cae = P.ca_event.values & (ratio < 0.95)
for k in range(-3, 4):
    ca_near |= np.roll(cae, k)
FACT = np.array([1 / 2, 1 / 3, 2 / 3, 1 / 4, 3 / 4, 1 / 5, 4 / 5, 5 / 6, 1 / 10, 2 / 5, 3 / 5, 1 / 6, 2 / 7, 5 / 7, 1 / 20])
best = np.full(n, np.nan)
for f in FACT:
    m = (np.abs(np.log(oj) - np.log(f)) < 0.015) & np.isnan(best)
    best = np.where(m, f, best)
# vol persistence: median raw volume next 20 vs previous 20 bars (same entity)
v = P.volume.values.astype(float)
s = pd.Series(v)
g = pd.Series(ent)
prev_med = s.groupby(g).transform(lambda x: x.shift(1).rolling(20, min_periods=10).median()).values
next_med = s.groupby(g).transform(lambda x: x[::-1].rolling(20, min_periods=10).median()[::-1]).values
volratio = next_med / prev_med
locked_low = np.isclose(P.close.values, P.low.values) & np.isclose(P.high.values, P.low.values)
cand = np.isfinite(best) & (oj < 0.86) & ~ca_near & ~newent
quiet_mkt = np.abs(np.nan_to_num(mgap)) < 0.015
strict = cand & quiet_mkt & (np.abs(np.log(cj) - np.log(best)) < 0.05) & ~locked_low & (volratio > 1.0 / best * 0.6)
R = {}
R["detector_v1_candidates"] = int(cand.sum())
R["detector_v2_strict"] = int(strict.sum())
idx = np.flatnonzero(strict)
R["strict_label_blocked"] = int(lb[idx].sum())
R["strict_not_blocked"] = int((~lb[idx]).sum())
R["strict_by_factor"] = pd.Series(np.round(best[idx], 4)).value_counts().to_dict()
R["strict_prev_elig_base"] = int(eb[idx - 1].sum())
R["strict_prev_fno"] = int(fno[idx - 1].sum())
R["strict_list"] = pd.DataFrame({"symbol": P.symbol.values[idx], "date": dates[idx].astype(str),
                                 "series": P.series.values[idx], "open_jump": oj[idx] - 1, "close_jump": cj[idx] - 1,
                                 "factor": best[idx], "vol_ratio_next/prev": volratio[idx], "label_block": lb[idx],
                                 "prev_elig": eb[idx - 1], "prev_fno": fno[idx - 1]}).to_dict("records")
# materiality for labels: h=10/20 valid elig windows (fw.ok) containing a strict, non-blocked missed CA
fw = L.Fwd(P)
for nm, rows in (("strict_not_blocked", idx[~lb[idx]]),):
    flag = np.zeros(n, bool)
    flag[rows] = True
    cs = np.cumsum(flag)
    for h in (10, 20):
        j = np.clip(np.arange(n) + h, 0, n - 1)
        cont = ((cs[j] - cs) > 0) & fw.ok(h) & eb
        R[f"{nm}_h{h}_valid_elig_windows_hit"] = int(cont.sum())
        R[f"{nm}_h{h}_share"] = float(cont.sum() / (fw.ok(h) & eb).sum())
# feature contamination from ALL label_block rows (demergers, unlocated splits, double-applied, etc.)
bad = lb.copy()
cs = np.cumsum(bad)
st = np.maximum.accumulate(np.where(newent, np.arange(n), 0))
for W in (20, 60, 250):
    lo = np.maximum(np.arange(n) - W, st)
    cnt = cs - np.where(lo > 0, cs[np.maximum(lo - 1, 0)], 0)
    cnt = np.where(lo > 0, cs - cs[lo - 1], cs)
    cont = (cnt > 0) & eb
    R[f"elig_share_any_label_block_in_last_{W}_bars"] = float(cont.sum() / eb.sum())
    R[f"fno_elig_share_any_label_block_in_last_{W}_bars"] = float((cont & fno).sum() / (eb & fno).sum())
save("s1c_missing_splits", R)
print({k: v for k, v in R.items() if k != "strict_list"})
for r in R["strict_list"][:60]:
    print(r)
