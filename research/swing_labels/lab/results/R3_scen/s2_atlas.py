#!/usr/bin/env python3
"""R3_scen stage 2: event-rate atlas.
  A. label zoo x horizon on elig_base (class shares, daily +1 share dispersion, market dependence, coherence)
  B. old-label defects (measured)
  C. filters ("conditions") x label at h=20
  D. scenarios (ex-ante / ex-post) x label at h=20
  E. PROD (frozen score) by scenario: top-20 net, excess vs universe, avoid-tail excess, rank IC
Net = open[t+1] -> close[t+h] minus 50 bps. Labels from s1 (labels_h*.npz)."""
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_scen")
L = C.L
OUT = C.OUT
COST = 0.005
P = L.load_panel(["date", "label_block"])
F = L.load_features(["elig_base", "elig_liq5", "fno_proxy", "dist_sma200", "xr_mom60", "deliv_pct", "volz_20",
                     "mkt_dist_sma200", "mkt_mom20", "breadth50"])
n = len(P)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
ncal = len(cal)
didx = np.searchsorted(cal, dates)
E = F["elig_base"].values.astype(bool)
LB = P["label_block"].values.astype(bool)
yr_cal = pd.DatetimeIndex(cal).year.values
yr = yr_cal[didx]
mon_cal = pd.DatetimeIndex(cal).to_period("M").astype(str).values
mon_codes, mon_idx_cal = np.unique(mon_cal, return_inverse=True)
nmon = len(mon_codes)
g_dev0 = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
g_dev_end = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
g_hold0 = int(np.searchsorted(cal, np.datetime64("2026-01-01")))
HOLD = didx >= g_hold0
ALL = np.ones(n, bool)


def dev_mask(h):
    return (didx >= g_dev0) & (didx + h <= g_dev_end)


mk = L.market_series("Nifty 500")
mret = mk["close"].resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)
mret_m = mret.reindex(mon_codes).values
mkc = mk.reindex(pd.DatetimeIndex(cal)).ffill()
mo, mcl = mkc["open"].values, mkc["close"].values


def mwin(h):
    g = np.arange(ncal)
    out = np.full(ncal, np.nan)
    ok = g + h < ncal
    out[ok] = mcl[g[ok] + h] / mo[g[ok] + 1] - 1
    return out


def per_date(v, x=None):
    if x is None:
        return np.bincount(didx[v], minlength=ncal).astype(float)
    return np.bincount(didx[v], weights=x[v], minlength=ncal)


def corr(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 5 else None


def coh(lab, v, r, classes, pm=None):
    vr = v & np.isfinite(r) & (True if pm is None else pm)
    net = r - COST
    d = {}
    for c in classes:
        m = vr & (lab == c)
        if m.sum() == 0:
            continue
        x = net[m]
        d[str(int(c))] = {"n": int(m.sum()), "mean_net": float(x.mean()), "median_net": float(np.median(x)),
                          "p_net_pos": float((x > 0).mean())}
    lo = str(int(min(classes)))
    if "1" in d and lo in d:
        d["spread_top_minus_bottom"] = d["1"]["mean_net"] - d[lo]["mean_net"]
    return d


def label_stats(lab, mask, r, h, bret=None, btouch=None):
    lab = np.asarray(lab, dtype="float64")
    v = mask & np.isfinite(lab)
    out = {"n": int(v.sum())}
    cnt = per_date(v)
    out["rows_per_day_median"] = float(np.median(cnt[cnt > 0]))
    out["days_with_rows"] = int((cnt > 0).sum())
    classes = [c for c in (-1.0, 0.0, 1.0) if (lab[v] == c).any()]
    DEV = dev_mask(h)
    for per, pm in (("all", ALL), ("dev", DEV), ("hold", HOLD)):
        vv = v & pm
        out[f"shares_{per}"] = {str(int(c)): float((lab[vv] == c).mean()) for c in classes} if vv.any() else {}
    out["pos_by_year"] = {int(y): float((lab[v & (yr == y)] == 1).mean()) for y in np.unique(yr[v])}
    pos = per_date(v & (lab == 1))
    ok = cnt >= 30
    ds = np.where(ok, pos / np.maximum(cnt, 1), np.nan)
    x = ds[ok]
    out["daily_pos"] = {"mean": float(x.mean()), "sd": float(x.std()), "p5": float(np.percentile(x, 5)),
                        "p95": float(np.percentile(x, 95)), "min": float(x.min()), "max": float(x.max()),
                        "n_days": int(ok.sum())}
    mc_ = np.bincount(mon_idx_cal[didx[v]], minlength=nmon).astype(float)
    mp_ = np.bincount(mon_idx_cal[didx[v & (lab == 1)]], minlength=nmon).astype(float)
    ms = np.where(mc_ > 0, mp_ / np.maximum(mc_, 1), np.nan)
    out["corr_monthly_pos_vs_mkt_month"] = corr(ms, mret_m)
    out["corr_daily_pos_vs_mkt_same_window"] = corr(ds, mwin(h))
    out["coherence_all"] = coh(lab, v, r, classes)
    out["coherence_dev"] = coh(lab, v, r, classes, DEV)
    out["coherence_hold"] = coh(lab, v, r, classes, HOLD)
    if bret is not None:
        vb = v & np.isfinite(bret)
        out["barrier_exit_mean_net"] = {str(int(c)): float((bret[vb & (lab == c)] - COST).mean())
                                        for c in classes if (vb & (lab == c)).any()}
        tc = btouch[v]
        out["touch_shares"] = {"pt": float((tc == 1).mean()), "sl": float((tc == -1).mean()),
                               "time": float((tc == 0).mean())}
    return out, ds, ms


LABS = [("old", "Old repo label"), ("cs", "Clean sign"), ("three", "Cost-aware 3-class"),
        ("b22", "Barrier 2.0/2.0"), ("b315", "Barrier 3.0/1.5"), ("pct_neu", "XR_neu 30/40/30"),
        ("pct_neumom", "XR_neumom 30/40/30"), ("dual", "DUAL (XR_neumom & cost)")]


def get_lab(z, k, none=False):
    if k in ("pct_neu", "pct_neumom"):
        p = z[k + ("_none" if none else "")].astype("float64")
        # +1e-7: stored float32 turns an exact 0.3 into 0.30000001 (pct = k/N spacing >= 3e-4, so safe)
        c = np.where(p > 0.7 + 1e-7, 1.0, np.where(p <= 0.3 + 1e-7, -1.0, 0.0))
        c[~np.isfinite(p)] = np.nan
        return c
    if k == "dual" and none:
        return z["dual_none"].astype("float64")
    return z[k].astype("float64")


# ------------------------------------------------------------------ A + B: zoo x horizon
zoo, defects, series = {}, {}, {}
for h in (5, 10, 15, 20):
    t1 = time.time()
    z = np.load(f"{OUT}/labels_h{h}.npz")
    r = z["r"].astype("float64")
    for k, nm in LABS:
        lab = get_lab(z, k)
        bret = z[k + "ret"].astype("float64") if k in ("b22", "b315") else None
        btc = z[k + "touch"] if k in ("b22", "b315") else None
        st, ds, ms = label_stats(lab, E, r, h, bret, btc)
        zoo[f"{k}_h{h}"] = st
        if h == 20 and k in ("cs", "pct_neumom", "dual", "b315", "three"):
            series[f"daily_pos_{k}"] = ds
            series[f"monthly_pos_{k}"] = ms
    # old-label defects
    old_fwd = z["old_fwd"].astype("float64")
    cc = z["cc"].astype("float64")
    cs = z["cs"].astype("float64")
    v = E
    fin = np.isfinite(r)
    both = v & fin & np.isfinite(old_fwd)
    defects[f"h{h}"] = {
        "rows_elig": int(v.sum()),
        "share_nan_to_0": float((v & ~np.isfinite(old_fwd)).sum() / v.sum()),
        "share_labelled_but_clean_window_undefined": float((v & np.isfinite(old_fwd) & ~fin).sum() / v.sum()),
        "share_old_label_0_due_to_nan_among_old_0": float((v & ~np.isfinite(old_fwd)).sum() / (v & (z["old"] == 0)).sum()),
        "share_sign_flip_raw_vs_adjusted_close": float(((old_fwd[both] > 0) != (cc[both] > 0)).mean()),
        "n_fake_crash_raw_lt_m30_adj_gt_m10": int((both & (old_fwd < -0.3) & (cc > -0.1)).sum()),
        "share_old_vs_clean_sign_disagree": float((z["old"][both] != cs[both]).mean()),
        "mean_close_entry_ret": float(np.nanmean(cc[v & fin])), "mean_exec_ret": float(np.nanmean(r[v & fin])),
        "mean_close_entry_ret_dev": float(np.nanmean(cc[v & fin & dev_mask(h)])),
        "mean_exec_ret_dev": float(np.nanmean(r[v & fin & dev_mask(h)])),
        "mean_close_entry_ret_hold": float(np.nanmean(cc[v & fin & HOLD])),
        "mean_exec_ret_hold": float(np.nanmean(r[v & fin & HOLD])),
        "median_exec_ret": float(np.nanmedian(r[v & fin])),
    }
    C.log("zoo h", h, round(time.time() - t1, 1), "s")
    del z, r
C.save("zoo", zoo)
C.save("old_label_defects", defects)
np.savez(f"{OUT}/series_s2.npz", cal=cal.astype(str), mon_codes=mon_codes, mret_m=mret_m, **series)

# ------------------------------------------------------------------ C: filters x label (h=20)
z = np.load(f"{OUT}/labels_h20.npz")
r20 = z["r"].astype("float64")
zb = np.load(f"{LAB}/results/R2_event/base.npz")
bdd10 = zb["bdd10"].astype("float64")
assert len(bdd10) == n
brd = np.load(f"{LAB}/results/R2_event/brd_day.npy")
assert len(brd) == ncal
brd_row = brd[didx]
dp = F["deliv_pct"].values.astype("float64")
dpr = pd.Series(np.where(E & np.isfinite(dp), dp, np.nan)).groupby(didx).rank(pct=True).values
FILTERS = {
    "none": ~LB,
    "elig": E,
    "liq5": E & F["elig_liq5"].values.astype(bool),
    "fno": E & F["fno_proxy"].values.astype(bool),
    "trend": E & (F["dist_sma200"].values > 0) & (F["xr_mom60"].values > 0.7),
    "washout": E & (bdd10 < 0) & (F["volz_20"].values > 0) & (F["mkt_mom20"].values < 0) & (brd_row >= 0.05),
    "deliv": E & (dpr > 2 / 3),
}
filt = {}
for fk, fm in FILTERS.items():
    rowd = {}
    for k, nm in LABS:
        lab = get_lab(z, k, none=(fk == "none" and k in ("pct_neu", "pct_neumom", "dual")))
        st, _, _ = label_stats(lab, fm, r20, 20)
        ref = int((E & np.isfinite(get_lab(z, k))).sum())
        st["share_of_elig_rows"] = st["n"] / ref if ref else None
        for key in ("pos_by_year",):
            st.pop(key, None)
        rowd[k] = st
    vv = fm & np.isfinite(r20)
    rowd["_filter"] = {"rows_valid": int(vv.sum()), "mean_net_all_rows": float((r20[vv] - COST).mean()),
                       "mean_net_all_rows_dev": float((r20[vv & dev_mask(20)] - COST).mean()),
                       "mean_net_all_rows_hold": float((r20[vv & HOLD] - COST).mean()),
                       "p_net_pos_all_rows": float(((r20[vv] - COST) > 0).mean()),
                       "share_days_active": float((per_date(vv) > 0).mean()),
                       "rows_per_active_day": float(np.mean(per_date(vv)[per_date(vv) > 0]))}
    filt[fk] = rowd
    C.log("filter", fk, rowd["_filter"])
C.save("filters_h20", filt)

# ------------------------------------------------------------------ D: scenarios x label (h=20, elig_base)
vx = L.market_series("India VIX")["close"].reindex(pd.DatetimeIndex(cal)).ffill()
try:
    vxp = vx.rolling(252, min_periods=126).rank(pct=True).values
except Exception:  # noqa: BLE001
    vxp = vx.rolling(252, min_periods=126).apply(lambda w: (w <= w[-1]).mean(), raw=True).values
d200 = pd.Series(F["mkt_dist_sma200"].values).groupby(didx).first().reindex(np.arange(ncal)).values
m20 = pd.Series(F["mkt_mom20"].values).groupby(didx).first().reindex(np.arange(ncal)).values
b50 = pd.Series(F["breadth50"].values).groupby(didx).first().reindex(np.arange(ncal)).values
mw20 = mwin(20)
STATES = {
    "N500 above 200-dma": d200 > 0, "N500 below 200-dma": d200 <= 0,
    "Mkt 20d momentum up": m20 > 0, "Mkt 20d momentum down": m20 <= 0,
    "Breadth50 >= 50%": b50 >= 0.5, "Breadth50 < 50%": b50 < 0.5,
    "VIX low tercile (trailing 1y)": vxp <= 1 / 3, "VIX mid tercile": (vxp > 1 / 3) & (vxp <= 2 / 3),
    "VIX high tercile": vxp > 2 / 3,
    "Ex-post mkt next 20d < -5%": mw20 < -0.05, "Ex-post mkt -5%..0": (mw20 >= -0.05) & (mw20 < 0),
    "Ex-post mkt 0..+5%": (mw20 >= 0) & (mw20 <= 0.05), "Ex-post mkt > +5%": mw20 > 0.05,
}
labs20 = {k: get_lab(z, k) for k, _ in LABS}
scen = {}
for sn, sday in STATES.items():
    srow = np.nan_to_num(sday, nan=0).astype(bool)[didx]
    d = {}
    for per, pm in (("all", ALL), ("dev", dev_mask(20)), ("hold", HOLD)):
        dd = {}
        for k, _ in LABS:
            lab = labs20[k]
            v = E & srow & pm & np.isfinite(lab) & np.isfinite(r20)
            if v.sum() == 0:
                continue
            net = r20[v] - COST
            lv = lab[v]
            lo = -1.0 if (lv == -1).any() else 0.0
            dd[k] = {"n": int(v.sum()), "n_days": int((per_date(v) > 0).sum()),
                     "pos_share": float((lv == 1).mean()),
                     "p_net_pos_given_pos": float((net[lv == 1] > 0).mean()) if (lv == 1).any() else None,
                     "mean_net_given_pos": float(net[lv == 1].mean()) if (lv == 1).any() else None,
                     "mean_net_given_down": float(net[lv == lo].mean()) if (lv == lo).any() else None,
                     "down_class": int(lo)}
        allv = E & srow & pm & np.isfinite(r20)
        dd["_state"] = {"share_of_days": float(np.nanmean(np.nan_to_num(sday, nan=0)[
            np.unique(didx[pm & E])])) if (pm & E).any() else None,
            "mean_net_all": float((r20[allv] - COST).mean()) if allv.any() else None}
        d[per] = dd
    scen[sn] = d
C.save("scenarios_h20", scen)
C.log("scenarios done")

# ------------------------------------------------------------------ E: PROD by scenario
Z = C.load_prod()
prod = Z["prod"].astype("float64")
pctl = z["pct_neumom"].astype("float64")
okp = E & np.isfinite(prod)
idx = np.flatnonzero(okp)
order = np.argsort(didx[idx], kind="stable")
idx = idx[order]
gd = didx[idx]
b = np.flatnonzero(np.r_[True, gd[1:] != gd[:-1]])
e = np.r_[b[1:], len(idx)]
rows = []
for s_, t_ in zip(b, e):
    ii = idx[s_:t_]
    g = didx[ii[0]]
    rr = r20[ii]
    fr = np.isfinite(rr)
    if fr.sum() < 30:
        continue
    sc = prod[ii]
    top = ii[np.argsort(-sc, kind="stable")[:20]]
    rt = r20[top]
    rt = rt[np.isfinite(rt)]
    pr = pd.Series(sc).rank(pct=True).values
    av = fr & (pr <= 0.3)
    um = rr[fr].mean()
    rk_s = pd.Series(sc[fr]).rank().values
    ic_r = float(np.corrcoef(rk_s, pd.Series(rr[fr]).rank().values)[0, 1])
    fp = fr & np.isfinite(pctl[ii])
    ic_l = float(np.corrcoef(pd.Series(sc[fp]).rank().values, pd.Series(pctl[ii][fp]).rank().values)[0, 1])
    rows.append((g, rt.mean() - COST, um - COST, rt.mean() - um, rr[av].mean() - um, ic_l, ic_r, len(rt)))
pdf = pd.DataFrame(rows, columns=["g", "top20_net", "univ_net", "excess", "avoid_excess", "ic_label", "ic_raw", "n_top"])
pdf["dev"] = (pdf.g >= g_dev0) & (pdf.g + 20 <= g_dev_end)
pdf["hold"] = pdf.g >= g_hold0
prod_scen = {}
for sn, sday in list(STATES.items()) + [("All days", np.ones(ncal, bool))]:
    sd_ = np.nan_to_num(sday, nan=0).astype(bool)
    d = {}
    for per in ("dev", "hold"):
        q = pdf[pdf[per] & sd_[pdf.g.values]]
        if len(q) < 5:
            d[per] = {"n_days": int(len(q))}
            continue
        d[per] = {"n_days": int(len(q)), "top20_mean_net": float(q.top20_net.mean()),
                  "universe_mean_net": float(q.univ_net.mean()), "excess_vs_universe": float(q.excess.mean()),
                  "excess_nw_t": L.nw_t(q.excess.values, lag=20), "avoid_tail_excess": float(q.avoid_excess.mean()),
                  "avoid_nw_t": L.nw_t(q.avoid_excess.values, lag=20), "ic_vs_label": float(q.ic_label.mean()),
                  "ic_vs_raw_return": float(q.ic_raw.mean()), "share_days_top20_beats_universe": float((q.excess > 0).mean())}
    prod_scen[sn] = d
C.save("prod_by_scenario_h20", prod_scen)
pdf.to_parquet(f"{OUT}/prod_daily_s2.parquet")
C.log("PROD by scenario done", prod_scen["All days"])
