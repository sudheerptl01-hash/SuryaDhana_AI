"""Stage 2: event rates + label diagnostics for every (h, neutraliser, label form).

Per construction (on V_h = elig_base & finite r_h):
  * class shares overall / by year / by regime (bull|bear x up20|dn20 at t) / by liquidity tercile
    (per-date tercile of log_turn20) / fno_proxy and liq5 sub-universes; monthly +1 share stats;
    corr(monthly +1 share, Nifty-500 monthly return)
  * label/P&L coherence: mean net (r - 50 bps) per class, P(net>0 | class), mean excess vs same-date
    universe EW per class; by year; corr(monthly P(net>0|+1), Nifty month)
  * composition tilt (+1 minus -1, cross-sectional z units) in beta_60, vol_20, log_turn20, mom_12_1,
    mom_20; date-level corr of the beta/vol tilt with the market window return (dev dates only)
  * overlap autocorr of pct (lag 1, lag h/2) and non-overlapping persistence corr(pct_t, pct_{t+h})
  * class disagreement vs the neu construction
"""
import time

import numpy as np
import pandas as pd

from common import HS, NEUTS, OUT, L, save, form_label, date_groups

t0 = time.time()
P = L.load_panel(["date", "entity", "seg_break", "label_block"])
F = L.load_features(["mkt_dist_sma200", "mkt_mom20", "log_turn20", "beta_60", "vol_20", "mom_12_1", "mom_20"])
fw = L.Fwd(P)
meta = np.load(f"{OUT}/meta.npz")
E, liq5, fno = meta["E"], meta["liq5"], meta["fno"]
dates = P["date"].values.astype("datetime64[D]")
di = pd.DatetimeIndex(dates)
year = di.year.values
month = di.to_period("M").astype(str).values
reg = np.where(F["mkt_dist_sma200"].values > 0, "bull", "bear").astype(object) + \
    np.where(F["mkt_mom20"].values > 0, "_up20", "_dn20").astype(object)
lt = F["log_turn20"].values.astype("float64")
dev = (dates >= np.datetime64(L.DEV[0])) & (dates <= np.datetime64(L.DEV[1]))
mk = L.market_series("Nifty 500")["close"]
mret = mk.resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)
COST = 0.005

# per-date z-scores of characteristics among E
chars = {}
for c in ("beta_60", "vol_20", "log_turn20", "mom_12_1", "mom_20"):
    x = np.where(E, F[c].values.astype("float64"), np.nan)
    s = pd.Series(x).groupby(dates)
    chars[c] = ((x - s.transform("mean").values) / s.transform("std").values)
del F

res = {}
for h in HS:
    Z = np.load(f"{OUT}/labels_h{h}.npz")
    r = Z["r"].astype("float64")
    ew = Z["ew"].astype("float64")
    m = Z["m"].astype("float64")
    V = E & np.isfinite(r)
    net = r - COST
    exs = r - ew
    # per-date liquidity tercile among V
    ltr = pd.Series(np.where(V, lt, np.nan)).groupby(dates).rank(pct=True).values
    terc = np.where(ltr <= 1 / 3, 0, np.where(ltr <= 2 / 3, 1, 2))
    pct_neu = Z["pct_neu"].astype("float64")
    c30_neu = form_label(pct_neu, "C30")
    for nt in NEUTS:
        pct = Z[f"pct_{nt}"].astype("float64")
        # overlap / persistence on pct (independent of the form)
        a1 = fw.at(pct, -1)
        ah = fw.at(pct, -(h // 2))
        aH = fw.at(pct, h)
        ok1 = V & np.isfinite(a1)
        okh = V & np.isfinite(ah)
        okH = V & np.isfinite(aH)
        pers = {"autocorr_lag1": float(np.corrcoef(pct[ok1], a1[ok1])[0, 1]),
                f"autocorr_lag{h // 2}": float(np.corrcoef(pct[okh], ah[okh])[0, 1]),
                f"persistence_pct_t_vs_t+{h}": float(np.corrcoef(pct[okH], aH[okH])[0, 1])}
        for form in ("C30", "C20", "C33", "T30", "B30"):
            lab = form_label(pct, form)
            mk_ = V & np.isfinite(lab)
            y = lab[mk_]
            pos_cls = 1.0
            classes = sorted(np.unique(y).tolist())
            df = pd.DataFrame({"y": y, "yr": year[mk_], "mo": month[mk_], "reg": reg[mk_], "t": terc[mk_],
                               "net": net[mk_], "exs": exs[mk_], "d": dates[mk_], "dev": dev[mk_],
                               "fno": fno[mk_], "liq5": liq5[mk_]})
            o = {"n": int(mk_.sum()), "overall": {str(c): float((y == c).mean()) for c in classes}}

            def shares(g):
                return {str(c): round(float((g.y == c).mean()), 4) for c in classes}
            o["by_year"] = {int(k): shares(g) for k, g in df.groupby("yr")}
            o["by_regime"] = {k: shares(g) for k, g in df.groupby("reg")}
            o["by_liq_tercile"] = {int(k): shares(g) for k, g in df.groupby("t")}
            o["fno_subset"] = shares(df[df.fno])
            o["liq5_subset"] = shares(df[df.liq5])
            mon = df.groupby("mo").y.apply(lambda s: float((s == pos_cls).mean()))
            o["monthly_pos"] = {"mean": float(mon.mean()), "std": float(mon.std()), "min": float(mon.min()),
                                "max": float(mon.max())}
            j = pd.concat([mon, mret], axis=1, join="inner").dropna()
            o["corr_monthly_pos_vs_mkt_ret"] = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
            # coherence
            coh = {}
            for c in classes:
                g = df[df.y == c]
                coh[str(c)] = {"mean_net_bps": float(g.net.mean() * 1e4), "p_net_pos": float((g.net > 0).mean()),
                               "mean_excess_vs_ew_bps": float(g.exs.mean() * 1e4),
                               "mean_net_bps_by_year": {int(k): round(float(gg.net.mean() * 1e4), 1)
                                                        for k, gg in g.groupby("yr")},
                               "p_net_pos_by_year": {int(k): round(float((gg.net > 0).mean()), 4)
                                                     for k, gg in g.groupby("yr")},
                               "p_net_pos_by_regime": {k: round(float((gg.net > 0).mean()), 4)
                                                       for k, gg in g.groupby("reg")}}
            o["coherence"] = coh
            gp = df[df.y == pos_cls]
            mp = gp.groupby("mo").net.apply(lambda s: float((s > 0).mean()))
            j2 = pd.concat([mp, mret], axis=1, join="inner").dropna()
            o["monthly_p_net_pos_given_pos"] = {"std": float(mp.std()), "min": float(mp.min()),
                                                "max": float(mp.max()),
                                                "corr_vs_mkt_ret": float(j2.iloc[:, 0].corr(j2.iloc[:, 1]))}
            # per-date top-minus-bottom spread (forms with a -1 / 0 class)
            if form in ("C30", "C20", "C33"):
                lo_c = -1.0
            else:
                lo_c = 0.0
            sp = df.groupby("d").apply(lambda g: g.net[g.y == pos_cls].mean() - g.net[g.y == lo_c].mean(),
                                       include_groups=False)
            o["xs_spread_pos_minus_neg_bps"] = {"mean": float(sp.mean() * 1e4), "std": float(sp.std() * 1e4)}
            # composition tilt (+1 minus lowest class) in z units; corr with market window return on dev
            if form in ("C30", "B30"):
                tilt = {}
                dd = dates[mk_]
                for cname, z in chars.items():
                    zz = z[mk_]
                    tp = pd.Series(np.where(y == pos_cls, zz, np.nan)).groupby(dd).mean()
                    tn = pd.Series(np.where(y == lo_c, zz, np.nan)).groupby(dd).mean()
                    tl = (tp - tn).dropna()
                    mm = pd.Series(m[mk_]).groupby(dd).mean().reindex(tl.index)
                    isdev = (tl.index >= np.datetime64(L.DEV[0])) & (tl.index <= np.datetime64(L.DEV[1]))
                    tilt[cname] = {"mean_z": float(tl.mean()),
                                   "mean_z_up_mkt": float(tl[(mm > 0).values].mean()),
                                   "mean_z_dn_mkt": float(tl[(mm <= 0).values].mean()),
                                   "corr_with_mkt_window_ret_dev": float(tl[isdev].corr(mm[isdev]))}
                o["composition_tilt"] = tilt
            if form == "C30":
                o["persistence"] = pers
                if nt != "neu":
                    both = V & np.isfinite(lab) & np.isfinite(c30_neu)
                    o["class_disagreement_vs_neu"] = float((lab[both] != c30_neu[both]).mean())
            res[f"h{h}_{nt}_{form}"] = o
            print(h, nt, form, round(time.time() - t0, 1), o["overall"],
                  {k: v["mean_net_bps"] for k, v in coh.items()}, flush=True)
    save("s2_events", res)
save("s2_events", res)
