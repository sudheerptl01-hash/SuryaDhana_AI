#!/usr/bin/env python3
"""R3_verify_R3_scen v2: independent PROD-by-scenario (top-20 vs universe, avoid tail, rank IC).

Own per-date loop + own Newey-West. Also tests the sensitivity of dropping top-20 picks whose
20-day window is invalid (the book would force-exit them at the last valid close instead)."""
import json
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = f"{LAB}/results/R3_verify_R3_scen"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def nw(x, lag=20):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return float("nan")
    u = x - x.mean()
    v = u @ u / n
    for k in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return float(x.mean() / np.sqrt(v / n))


P = pd.read_parquet(f"{LAB}/panel.parquet", columns=["date", "entity", "open", "close", "seg_break", "label_block"])
E = pd.read_parquet(f"{LAB}/features.parquet", columns=["elig_base"])["elig_base"].values.astype(bool)
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
seg_end = np.r_[firsts[1:] - 1, n - 1][segid]
lbcum = np.cumsum(lb)
ii = np.arange(n)
cal = np.unique(dates)
ncal = len(cal)
didx = np.searchsorted(cal, dates)
H = 20
# executable r20 (my own window logic, validated bit-exact vs lablib in v1)
j = np.minimum(ii + H, n - 1)
inseg = (ii + H) <= seg_end
span = (dates[j] - dates).astype("int64")
valid = inseg & (span <= int(np.ceil(H * 7 / 5)) + 8) & ((lbcum[j] - lbcum) == 0)
e1 = np.where(ii + 1 <= seg_end, o[np.minimum(ii + 1, n - 1)], np.nan)
r20 = np.where(valid, c[j] / e1 - 1, np.nan)
# forced-exit variant (book-like): exit at the last close before the window breaks (segment end,
# label_block row, or day cap g+20 on the calendar)
kk = np.zeros(n, int)
for k in range(1, H + 1):
    jj = np.minimum(ii + k, n - 1)
    ok = ((ii + k) <= seg_end) & ((lbcum[jj] - lbcum) == 0) & (didx[jj] <= didx + H)
    kk = np.where(ok & (kk == k - 1), k, kk)
rf = np.where(kk >= 1, c[np.minimum(ii + np.maximum(kk, 1), n - 1)] / e1 - 1, np.nan)
log("r20 built; valid", int(np.isfinite(r20).sum()), "forced-exit finite", int(np.isfinite(rf).sum()))

Z = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)
prod = Z["prod"].astype("float64")
pct = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")["pct"].astype("float64")
del Z
g_dev0 = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
g_dev_last = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
g_hold0 = int(np.searchsorted(cal, np.datetime64("2026-01-01")))
okp = E & np.isfinite(prod)
order = np.argsort(didx, kind="stable")
bnd = np.searchsorted(didx[order], np.arange(ncal + 1))
rows = []
n_top_nan = 0
n_top = 0
for g in range(ncal):
    rr_idx = order[bnd[g]:bnd[g + 1]]
    rr_idx = rr_idx[okp[rr_idx]]
    if len(rr_idx) == 0:
        continue
    r = r20[rr_idx]
    f = np.isfinite(r)
    if f.sum() < 30:
        continue
    s = prod[rr_idx]
    top = rr_idx[np.argsort(-s, kind="stable")[:20]]
    rt = r20[top]
    n_top += 20
    n_top_nan += int((~np.isfinite(rt)).sum())
    um = r[f].mean()
    top_mean = np.nanmean(rt)
    # forced-exit variant: keep every top-20 pick and every universe row with a defined entry
    rtf = rf[top]
    uf = rf[rr_idx]
    top_f = np.nanmean(rtf)
    um_f = np.nanmean(uf)
    pr = (rankdata(s) - 0.5) / len(s)                    # not used for cut; use pandas-like pct below
    prp = rankdata(s, method="average") / len(s)         # pandas rank(pct=True) convention
    av = f & (prp <= 0.3)
    fl = f & np.isfinite(pct[rr_idx])
    ic_l = np.corrcoef(rankdata(s[fl]), rankdata(pct[rr_idx][fl]))[0, 1]
    ic_r = np.corrcoef(rankdata(s[f]), rankdata(r[f]))[0, 1]
    rows.append((g, top_mean - um, r[av].mean() - um, ic_l, ic_r, top_mean - 0.005, um - 0.005, top_f - um_f))
D = pd.DataFrame(rows, columns=["g", "excess", "avoid", "ic_l", "ic_r", "top_net", "univ_net", "excess_forced"])
D["dev"] = (D.g >= g_dev0) & (D.g + H <= g_dev_last)
D["hold"] = D.g >= g_hold0
log("days", len(D), "top-20 picks with NaN r20:", n_top_nan, "of", n_top)

S = np.load(f"{OUT}/v1_states.npz", allow_pickle=True)
d200, mom20, b50, vxp, mw20 = S["d200"], S["mom20"], S["b50"], S["vxp"], S["mw20"]
STATES = {
    "N500 above 200-dma": d200 > 0, "N500 below 200-dma": d200 <= 0,
    "Mkt 20d momentum up": mom20 > 0, "Mkt 20d momentum down": mom20 <= 0,
    "Breadth50 >= 50%": b50 >= 0.5, "Breadth50 < 50%": b50 < 0.5,
    "VIX low tercile (trailing 1y)": vxp <= 1 / 3, "VIX mid tercile": (vxp > 1 / 3) & (vxp <= 2 / 3),
    "VIX high tercile": vxp > 2 / 3,
    "Ex-post mkt next 20d < -5%": mw20 < -0.05, "Ex-post mkt -5%..0": (mw20 >= -0.05) & (mw20 < 0),
    "Ex-post mkt 0..+5%": (mw20 >= 0) & (mw20 <= 0.05), "Ex-post mkt > +5%": mw20 > 0.05,
    "All days": np.ones(ncal, bool),
}
out = {}
for sn, sd in STATES.items():
    sd = np.nan_to_num(sd.astype(float), nan=0).astype(bool)
    d = {}
    for per in ("dev", "hold"):
        q = D[D[per] & sd[D.g.values]]
        if len(q) < 5:
            d[per] = {"n_days": len(q)}
            continue
        d[per] = {"n_days": int(len(q)), "excess": float(q.excess.mean()), "excess_t": nw(q.excess.values),
                  "avoid": float(q.avoid.mean()), "avoid_t": nw(q.avoid.values), "ic_label": float(q.ic_l.mean()),
                  "ic_raw": float(q.ic_r.mean()), "top_net": float(q.top_net.mean()), "univ_net": float(q.univ_net.mean()),
                  "excess_forced_exit_variant": float(q.excess_forced.mean()),
                  "excess_forced_t": nw(q.excess_forced.values)}
    out[sn] = d
    log(f"{sn:32s}", {p: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for p, x in d.items()})
# independent-period view for the 2026 strong-rally bin
q = D[D.hold & np.nan_to_num(STATES["Ex-post mkt > +5%"].astype(float), nan=0).astype(bool)[D.g.values]]
out["hold_boom_bin_signal_dates"] = [str(cal[g]) for g in q.g.values]
# non-overlapping (every 20th signal day) t for the headline DEV / 2026 excess
for per in ("dev", "hold"):
    q = D[D[per]].sort_values("g")
    tt = []
    for ph in range(20):
        x = q.excess.values[ph::20]
        tt.append(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))
    out[f"nonoverlap_t_excess_{per}"] = {"mean_over_20_offsets": float(np.mean(tt)), "min": float(np.min(tt)),
                                         "max": float(np.max(tt)), "n_per_offset": int(len(q) // 20)}
log("nonoverlap", out["nonoverlap_t_excess_dev"], out["nonoverlap_t_excess_hold"])
out["n_top_picks_nan_r20"] = n_top_nan
out["n_top_picks"] = n_top
with open(f"{OUT}/v2_results.json", "w") as fh:
    json.dump(out, fh, indent=1)
log("done")
