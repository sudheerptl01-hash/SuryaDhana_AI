"""Stage 2: event rates, regime dependence, label/P&L coherence, composition tilts, and the
tau x q x h sensitivity map of the DUAL label (all on U = elig_base; dev = 2021-2025 dates,
holdout = 2026 reported separately)."""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, regime, cls3

t0 = time.time()
P = L.load_panel(["date", "entity", "seg_break", "label_block"])
F = L.load_features(["elig_base", "mkt_dist_sma200", "mkt_mom20", "log_turn20", "beta_60", "vol_20",
                     "fno_proxy"])
U = np.load(f"{OUT}/meta.npz")["U"]
dates = P["date"].values.astype("datetime64[D]")
year = pd.DatetimeIndex(dates).year.values
reg = regime(F["mkt_dist_sma200"].values, F["mkt_mom20"].values)
beta = F["beta_60"].values.astype("float64")
vol = F["vol_20"].values.astype("float64")
lt = F["log_turn20"].values.astype("float64")
COST = 0.005
res = {}


def daily_share(lab, m, mask, val=1):
    ok = mask & np.isfinite(lab)
    df = pd.DataFrame({"d": dates[ok], "y": (lab[ok] == val).astype(float), "m": m[ok]})
    g = df.groupby("d").agg(sh=("y", "mean"), m=("m", "median"))
    return g


def regime_stats(g):
    """daily share series g (sh, m) -> stats incl. slope of share on same-window market return."""
    x = g.dropna()
    out = {"daily_mean": float(x.sh.mean()), "daily_std": float(x.sh.std()),
           "daily_p5": float(x.sh.quantile(0.05)), "daily_p95": float(x.sh.quantile(0.95)),
           "daily_min": float(x.sh.min()), "daily_max": float(x.sh.max()),
           "corr_daily_share_vs_mkt_window": float(x.sh.corr(x.m)) if x.sh.std() > 0 else 0.0}
    if x.sh.std() > 0:
        b = np.polyfit(x.m.values, x.sh.values, 1)
        out["slope_share_per_10pct_mkt"] = float(b[0] * 0.10)
    else:
        out["slope_share_per_10pct_mkt"] = 0.0
    out["share_when_mkt_window_up"] = float(x.sh[x.m > 0].mean())
    out["share_when_mkt_window_down"] = float(x.sh[x.m <= 0].mean())
    out["share_when_mkt_window_lt_m5pct"] = float(x.sh[x.m < -0.05].mean()) if (x.m < -0.05).any() else None
    return out


def coherence(lab, r, resid, mask):
    ok = mask & np.isfinite(lab) & np.isfinite(r)
    df = pd.DataFrame({"y": lab[ok], "net": r[ok] - COST, "res": resid[ok], "yr": year[ok]})
    out = {}
    for c, g in df.groupby("y"):
        out[str(int(c))] = {"n": int(len(g)), "mean_net_bps": float(g.net.mean() * 1e4),
                            "median_net_bps": float(g.net.median() * 1e4),
                            "hit_net_pos": float((g.net > 0).mean()), "mean_resid_bps": float(g.res.mean() * 1e4)}
    by = {}
    for (yr, c), g in df.groupby(["yr", "y"]):
        by.setdefault(int(yr), {})[str(int(c))] = float(g.net.mean() * 1e4)
    out["mean_net_bps_by_year"] = by
    return out


def tilt(lab, m, mask):
    """mean beta/vol/size of +1 vs -1 class when the market window is up vs down (composition)."""
    ok = mask & np.isfinite(lab) & np.isfinite(m)
    df = pd.DataFrame({"y": lab[ok], "up": m[ok] > 0, "b": beta[ok], "v": vol[ok] * np.sqrt(252), "lt": lt[ok]})
    out = {}
    for (up, c), g in df.groupby(["up", "y"]):
        out[f"{'mktUp' if up else 'mktDn'}_{int(c)}"] = {"beta": float(g.b.mean()), "ann_vol": float(g.v.mean()),
                                                         "log_turn": float(g["lt"].mean()), "n": int(len(g))}
    return out


for h in (20, 10):
    Z = np.load(f"{OUT}/labels_h{h}.npz")
    r = Z["r"].astype("float64")
    m = Z["m"].astype("float64")
    resid = Z["resid"].astype("float64")
    pct = Z["pct"].astype("float64")
    labs = {k: Z[k].astype("float64") for k in ("REL", "ABS", "DUAL", "BAR", "DUALP") if k in Z.files}
    dev = dates < np.datetime64("2026-01-01")
    hold = ~dev
    out_h = {}
    for nm, lab in labs.items():
        e_up = L.event_report(lab, U, P, F, positive=1)
        e_dn = L.event_report(lab, U, P, F, positive=-1)
        d = {"overall": e_up["overall"], "n": e_up["n"], "by_year": e_up["by_year"],
             "by_regime": e_up["by_regime"], "by_liquidity_tercile": e_up["by_liquidity_tercile"],
             "monthly_pos": {k: v for k, v in e_up["monthly_pos"].items() if k != "series"},
             "monthly_neg": {k: v for k, v in e_dn["monthly_pos"].items() if k != "series"},
             "corr_monthly_pos_vs_mkt_ret": e_up.get("corr_monthly_pos_vs_mkt_ret"),
             "corr_monthly_neg_vs_mkt_ret": e_dn.get("corr_monthly_pos_vs_mkt_ret")}
        d["daily_up"] = {"dev": regime_stats(daily_share(lab, m, U & dev, 1)),
                         "holdout": regime_stats(daily_share(lab, m, U & hold, 1))}
        d["daily_dn"] = {"dev": regime_stats(daily_share(lab, m, U & dev, -1)),
                         "holdout": regime_stats(daily_share(lab, m, U & hold, -1))}
        d["coherence"] = coherence(lab, r, resid, U)
        d["coherence_dev"] = coherence(lab, r, resid, U & dev)
        d["coherence_holdout"] = coherence(lab, r, resid, U & hold)
        d["tilt"] = tilt(lab, m, U & dev)
        d["autocorr_lag1"] = L.overlap_autocorr(np.where(U, lab, np.nan), P, 1)
        d["autocorr_lag5"] = L.overlap_autocorr(np.where(U, lab, np.nan), P, 5)
        out_h[nm] = d
        print(h, nm, round(time.time() - t0, 1), d["overall"], d["daily_up"]["dev"]["corr_daily_share_vs_mkt_window"],
              flush=True)
    # what the absolute condition removes from REL+1: "relative winners that lost money"
    rel, dual = labs["REL"], labs["DUAL"]
    dropped = U & (rel == 1) & (dual != 1) & np.isfinite(dual)
    kept = U & (dual == 1)
    df = pd.DataFrame({"yr": year, "drop": dropped, "relp": U & (rel == 1)})
    share_drop = (df[df.relp].groupby("yr")["drop"].mean()).to_dict()
    out_h["rel_plus_removed_by_abs"] = {
        "share_of_REL+1_removed_overall": float(dropped.sum() / (U & (rel == 1)).sum()),
        "by_year": {int(k): float(v) for k, v in share_drop.items()},
        "mean_net_bps_removed": float(np.nanmean(r[dropped] - COST) * 1e4),
        "mean_resid_bps_removed": float(np.nanmean(resid[dropped]) * 1e4),
        "mean_net_bps_kept": float(np.nanmean(r[kept] - COST) * 1e4),
        "mean_resid_bps_kept": float(np.nanmean(resid[kept]) * 1e4),
        "mean_beta_removed": float(np.nanmean(beta[dropped])), "mean_beta_kept": float(np.nanmean(beta[kept])),
    }
    # ---- sensitivity map: tau x q (event rates, regime dependence, coherence) ----
    sens = []
    V = U & np.isfinite(pct) & np.isfinite(r)
    for q in (0.2, 0.3, 0.4):
        rq = cls3(pct, q)
        for tau_bps in (0, 25, 50, 100, 200, 300, 500):
            tau = tau_bps / 1e4
            du = np.where((rq == 1) & (r > tau), 1.0, np.where((rq == -1) & (r < -tau), -1.0, 0.0))
            du[~np.isfinite(rq) | ~np.isfinite(r)] = np.nan
            row = {"h": h, "q": q, "tau_bps": tau_bps}
            for side, val in (("up", 1), ("dn", -1)):
                for wn, wm in (("dev", V & dev), ("hold", V & hold)):
                    g = daily_share(du, m, wm, val).dropna()
                    row[f"{side}_{wn}_share"] = float(g.sh.mean())
                    row[f"{side}_{wn}_daily_std"] = float(g.sh.std())
                    row[f"{side}_{wn}_corr_mkt"] = float(g.sh.corr(g.m))
                    row[f"{side}_{wn}_share_mktdn"] = float(g.sh[g.m <= 0].mean())
                    row[f"{side}_{wn}_share_mktup"] = float(g.sh[g.m > 0].mean())
                sel = V & dev & (du == val)
                row[f"{side}_dev_mean_net_bps"] = float(np.mean(r[sel] - COST) * 1e4)
                row[f"{side}_dev_mean_resid_bps"] = float(np.mean(resid[sel]) * 1e4)
                row[f"{side}_dev_beta"] = float(np.nanmean(beta[sel]))
            # share of rows where at least one name on the date is +1 (empty-date risk)
            g = daily_share(du, m, V, 1)
            row["dates_with_zero_up"] = int((g.sh == 0).sum())
            sens.append(row)
        print(h, "sens q", q, round(time.time() - t0, 1), flush=True)
    out_h["sensitivity"] = sens
    if h == 20:
        bsens = {}
        rel = labs["REL"]
        for nm in ("BAR", "BAR22", "BAR21"):
            b = Z[nm].astype("float64")
            dp = np.where((rel == 1) & (b == 1), 1.0, np.where((rel == -1) & (b == -1), -1.0, 0.0))
            dp[~np.isfinite(rel) | ~np.isfinite(b)] = np.nan
            row = {}
            for k_, lab_ in ((nm, b), ("DUALP_" + nm, dp)):
                for side, val in (("up", 1), ("dn", -1)):
                    g = daily_share(lab_, m, V & dev, val).dropna()
                    row[f"{k_}_{side}_dev_share"] = float(g.sh.mean())
                    row[f"{k_}_{side}_dev_daily_std"] = float(g.sh.std())
                    row[f"{k_}_{side}_dev_corr_mkt"] = float(g.sh.corr(g.m))
                    sel = V & dev & (lab_ == val)
                    row[f"{k_}_{side}_dev_mean_net_bps"] = float(np.mean(r[sel] - COST) * 1e4)
            bsens[nm] = row
        out_h["barrier_geometry_sensitivity"] = bsens
    res[f"h{h}"] = out_h
    save(f"s2_events_h{h}", out_h)
print("done", round(time.time() - t0, 1))
