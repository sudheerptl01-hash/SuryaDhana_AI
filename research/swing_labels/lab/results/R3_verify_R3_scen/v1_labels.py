#!/usr/bin/env python3
"""R3_verify_R3_scen v1: independent re-computation of label event-rate headline numbers.

Own code (does not import or copy R3_scen scripts). Uses only the panel/feature/index files,
the frozen label file (R3_devil/label_h20_neumom.npz) and lablib only for a sanity cross-check.
"""
import json
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = f"{LAB}/results/R3_verify_R3_scen"
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


P = pd.read_parquet(f"{LAB}/panel.parquet",
                    columns=["date", "entity", "open", "close", "raw_close", "seg_break", "label_block"])
E = pd.read_parquet(f"{LAB}/features.parquet", columns=["elig_base"])["elig_base"].values.astype(bool)
n = len(P)
dates = P["date"].values.astype("datetime64[D]")
ent = P["entity"].values
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
rc = P["raw_close"].values.astype("float64")
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
log("loaded", n, "rows", ncal, "days")


def fwd_val(arr, k):
    j = ii + k
    ok = j <= seg_end
    out = np.full(n, np.nan)
    out[ok] = arr[j[ok]]
    return out


def valid_window(h):
    j = np.minimum(ii + h, n - 1)
    inseg = (ii + h) <= seg_end
    span = (dates[j] - dates).astype("int64")
    cap = int(np.ceil(h * 7 / 5)) + 8
    clean = (lbcum[j] - lbcum) == 0
    return inseg & (span <= cap) & clean


def exec_ret(h):
    r = fwd_val(c, h) / fwd_val(o, 1) - 1
    r[~valid_window(h)] = np.nan
    return r


# Nifty 500 on the panel calendar
idx = pd.read_parquet(f"{LAB}/index.parquet")
mk = idx[idx["index"] == "Nifty 500"].drop_duplicates("date").set_index("date").sort_index()
mkc = mk.reindex(pd.DatetimeIndex(cal)).ffill()
mo, mcl = mkc["open"].values, mkc["close"].values


def mkt_window(h):
    out = np.full(ncal, np.nan)
    g = np.arange(ncal - h)
    out[g] = mcl[g + h] / mo[g + 1] - 1
    return out


g_dev0 = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
g_dev_last = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
g_hold0 = int(np.searchsorted(cal, np.datetime64("2026-01-01")))


def dev_rows(h):
    return (didx >= g_dev0) & (didx + h <= g_dev_last)


HOLD = didx >= g_hold0


def daily_share(lab_pos, valid, min_rows=30):
    cnt = np.bincount(didx[valid], minlength=ncal).astype(float)
    pos = np.bincount(didx[valid & lab_pos], minlength=ncal).astype(float)
    ok = cnt >= min_rows
    return np.where(ok, pos / np.maximum(cnt, 1), np.nan)


def cor(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1])


res = {}
# ---------------------------------------------------------------- sanity: my r20 vs lablib
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

for h in (5, 20):
    r = exec_ret(h)
    if h == 20:
        Pp = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
        rl = L.fwd_return(Pp, L.Fwd(Pp), 20)
        del Pp
        res["sanity_r20_vs_lablib"] = {"finite_mismatch": int((np.isfinite(r) != np.isfinite(rl)).sum()),
                                       "max_abs_diff": float(np.nanmax(np.abs(r - rl)))}
        log("sanity", res["sanity_r20_vs_lablib"])
        del rl
    V = E & np.isfinite(r)
    cs = r > 0
    d = {}
    d["n_valid_elig"] = int(V.sum())
    d["cs_up_share_all"] = float(cs[V].mean())
    d["cs_up_share_dev"] = float(cs[V & dev_rows(h)].mean())
    d["cs_up_share_2026"] = float(cs[V & HOLD].mean())
    ds = daily_share(cs, V)
    x = ds[np.isfinite(ds)]
    d["daily_up_share"] = {"mean": float(x.mean()), "sd": float(x.std()), "p5": float(np.percentile(x, 5)),
                           "p95": float(np.percentile(x, 95)), "n_days": int(len(x))}
    mw = mkt_window(h)
    d["corr_daily_up_vs_mkt_same_window"] = cor(ds, mw)
    # monthly atlas-style: month of signal vs calendar-month index return
    mon = pd.DatetimeIndex(cal).to_period("M")
    cntm = pd.Series(np.bincount(didx[V], minlength=ncal)).groupby(mon).sum()
    posm = pd.Series(np.bincount(didx[V & cs], minlength=ncal)).groupby(mon).sum()
    ms = (posm / cntm.replace(0, np.nan))
    mret = mk["close"].groupby(mk.index.to_period("M")).last().pct_change()
    d["corr_monthly_atlas"] = cor(ms.values, mret.reindex(ms.index).values)
    # ---- old repo label
    ofwd = fwd_val(rc, h) / rc - 1
    old = ofwd > 0                       # NaN -> False -> 0
    cc = fwd_val(c, h) / c - 1
    both = E & np.isfinite(r) & np.isfinite(ofwd)
    d["old_share_nan_to_0"] = float((E & ~np.isfinite(ofwd)).sum() / E.sum())
    d["old_nan_share_of_zero_class"] = float((E & ~np.isfinite(ofwd)).sum() / (E & ~old).sum())
    d["old_vs_cs_disagree"] = float((old[both] != cs[both]).mean())
    d["old_sign_flip_raw_vs_adj"] = float(((ofwd[both] > 0) != (cc[both] > 0)).mean())
    d["old_fake_crash"] = int((both & (ofwd < -0.3) & (cc > -0.1)).sum())
    d["old_up_share_all"] = float(old[E].mean())
    d["old_up_share_dev"] = float(old[E & dev_rows(h)].mean())
    d["old_up_share_2026"] = float(old[E & HOLD].mean())
    fin = E & np.isfinite(r)
    d["close_entry_mean_all"] = float(np.nanmean(cc[fin]))
    d["exec_mean_all"] = float(r[fin].mean())
    d["close_entry_mean_dev"] = float(np.nanmean(cc[fin & dev_rows(h)]))
    d["exec_mean_dev"] = float(r[fin & dev_rows(h)].mean())
    d["exec_median_all"] = float(np.median(r[fin]))
    # how much of old's NaN->0 lies in the final h days (no future yet)
    tail = didx > (ncal - 1 - h)
    d["old_nan_rows_in_last_h_days_share"] = float((E & ~np.isfinite(ofwd) & tail).sum() / max((E & ~np.isfinite(ofwd)).sum(), 1))
    res[f"h{h}"] = d
    log("h", h, json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items() if k != "daily_up_share"}),
        {k: round(v, 4) for k, v in d["daily_up_share"].items()})
    if h == 20:
        r20, cs20, ds_cs20, mw20 = r, cs, ds, mw
    del ofwd, old, cc

# ---------------------------------------------------------------- frozen XR_neumom and DUAL at h=20
zd = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")
pct = zd["pct"].astype("float64")
rz = zd["r"].astype("float64")
res["frozen_r_vs_my_r20_maxdiff"] = float(np.nanmax(np.abs(rz - r20)))
V = E & np.isfinite(r20) & np.isfinite(pct)
res["frozen_rows_vs_myvalid"] = {"frozen_finite_in_E": int((E & np.isfinite(pct)).sum()), "my_valid_E": int((E & np.isfinite(r20)).sum())}
up = pct > 0.7
dn = pct <= 0.3
net = r20 - 0.005
xr = {"up_share_all": float(up[V].mean()), "down_share_all": float(dn[V].mean()),
      "up_share_dev": float(up[V & dev_rows(20)].mean()), "up_share_2026": float(up[V & HOLD].mean()),
      "mean_net_up": float(net[V & up].mean()), "mean_net_down": float(net[V & dn].mean()),
      "p_net_pos_up": float((net[V & up] > 0).mean())}
dsx = daily_share(up, V)
xr["daily_sd"] = float(np.nanstd(dsx))
xr["corr_same_window"] = cor(dsx, mw20)
res["xr_neumom_h20"] = xr
dual_up = up & (r20 > 0.005)
dsd = daily_share(dual_up, V)
x = dsd[np.isfinite(dsd)]
res["dual_h20"] = {"up_share_all": float(dual_up[V].mean()), "up_share_dev": float(dual_up[V & dev_rows(20)].mean()),
                   "up_share_2026": float(dual_up[V & HOLD].mean()), "daily_sd": float(x.std()),
                   "p5": float(np.percentile(x, 5)), "corr_same_window": cor(dsd, mw20)}
log("xr", json.dumps(res["xr_neumom_h20"]))
log("dual", json.dumps(res["dual_h20"]))

# ---------------------------------------------------------------- scenarios at h=20 (my own state definitions)
mclose = mk["close"]
sma200 = mclose.rolling(200, min_periods=200).mean()
d200 = (mclose / sma200 - 1).reindex(pd.DatetimeIndex(cal)).ffill().values
mom20 = (mclose / mclose.shift(20) - 1).reindex(pd.DatetimeIndex(cal)).ffill().values
vx = idx[idx["index"] == "India VIX"].drop_duplicates("date").set_index("date").sort_index()["close"]
vxc = vx.reindex(pd.DatetimeIndex(cal)).ffill().values
vxp = np.full(ncal, np.nan)
for g in range(ncal):
    w = vxc[max(0, g - 251):g + 1]
    w = w[np.isfinite(w)]
    if len(w) >= 126 and np.isfinite(vxc[g]):
        # average-rank percentile (pandas rank(pct=True) convention: ties averaged)
        vxp[g] = ((w < vxc[g]).sum() + 0.5 * ((w == vxc[g]).sum() - 1) + 1) / len(w)
Fb = pd.read_parquet(f"{LAB}/features.parquet", columns=["breadth50", "mkt_dist_sma200", "mkt_mom20"])
b50 = pd.Series(Fb["breadth50"].values).groupby(didx).median().reindex(np.arange(ncal)).values
f200 = pd.Series(Fb["mkt_dist_sma200"].values).groupby(didx).median().reindex(np.arange(ncal)).values
fm20 = pd.Series(Fb["mkt_mom20"].values).groupby(didx).median().reindex(np.arange(ncal)).values
del Fb
okd = np.isfinite(f200) & np.isfinite(d200)
res["state_agreement_with_features"] = {
    "above200_agree": float(((f200 > 0) == (d200 > 0))[okd].mean()),
    "mom20_agree": float(((fm20 > 0) == (mom20 > 0))[np.isfinite(fm20) & np.isfinite(mom20)].mean())}
log("state agreement", res["state_agreement_with_features"])
STATES = {
    "N500 above 200-dma": d200 > 0, "N500 below 200-dma": d200 <= 0,
    "Mkt 20d momentum up": mom20 > 0, "Mkt 20d momentum down": mom20 <= 0,
    "Breadth50 >= 50%": b50 >= 0.5, "Breadth50 < 50%": b50 < 0.5,
    "VIX low tercile (trailing 1y)": vxp <= 1 / 3, "VIX mid tercile": (vxp > 1 / 3) & (vxp <= 2 / 3),
    "VIX high tercile": vxp > 2 / 3,
    "Ex-post mkt next 20d < -5%": mw20 < -0.05, "Ex-post mkt -5%..0": (mw20 >= -0.05) & (mw20 < 0),
    "Ex-post mkt 0..+5%": (mw20 >= 0) & (mw20 <= 0.05), "Ex-post mkt > +5%": mw20 > 0.05,
}
scen = {}
Vx = E & np.isfinite(r20) & np.isfinite(pct)
for sn, sd in STATES.items():
    srow = np.nan_to_num(sd.astype(float), nan=0).astype(bool)[didx]
    v1 = E & np.isfinite(r20) & srow
    v2 = Vx & srow
    scen[sn] = {"cs_up_share": float(cs20[v1].mean()),
                "xr_mean_net_up": float(net[v2 & up].mean()), "xr_p_net_pos_up": float((net[v2 & up] > 0).mean()),
                "n_days": int(len(np.unique(didx[v1])))}
res["scenarios_all_years"] = scen
for k, v in scen.items():
    log(f"{k:32s}", {kk: round(vv, 4) for kk, vv in v.items()})
np.savez(f"{OUT}/v1_states.npz", cal=cal.astype(str), d200=d200, mom20=mom20, b50=b50, vxp=vxp, mw20=mw20,
         f200=f200, fm20=fm20)
with open(f"{OUT}/v1_results.json", "w") as fh:
    json.dump(res, fh, indent=1)
log("done")
