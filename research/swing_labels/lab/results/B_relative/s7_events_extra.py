"""Stage 2: event-rate scorecard for every relative label (and the absolute control).
Usage: python3 s2_events.py <h>
Outputs events_h{h}.json (full event_report incl. monthly series) and a compact summary in
results.json. Also: absolute-P&L coherence of each class by regime/year (the key risk of relative
labels), composition tilt vs market (beta / vol tilt of +1 vs -1 per date, corr with the market
window return), overlap autocorrelation and date-clustering (eta^2) of the +1 indicator.
"""
import json
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, save

h = int(sys.argv[1])
ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None
t0 = time.time()
P = L.load_panel(["date", "entity", "seg_break", "label_block"])
F = L.load_features(["mkt_dist_sma200", "mkt_mom20", "log_turn20", "beta_60", "vol_20", "fno_proxy"])
fw = L.Fwd(P)
meta = np.load(f"{OUT}/meta.npz")
U, fno, known = meta["U"], meta["fno"], meta["known"]
Z = dict(np.load(f"{OUT}/labels_h{h}.npz"))
from common import tercile_label
for k_, p_ in np.load(f"{OUT}/labels_h{h}_v.npz").items():
    for q in (30, 20, 10):
        Z[f"XR_{k_[4:]}_{q}"] = tercile_label(p_.astype("float64"), q / 100)
r = Z["r"].astype("float64")
m = Z["m"].astype("float64")
dates = P["date"].values.astype("datetime64[D]")
years = pd.DatetimeIndex(dates).year.values
reg = np.where(F["mkt_dist_sma200"].values > 0, "bull", "bear")
reg = np.char.add(reg.astype(str), np.where(F["mkt_mom20"].values > 0, "_up20", "_dn20"))
beta = np.clip(F["beta_60"].values.astype("float64"), 0, 3)
vol = F["vol_20"].values.astype("float64")
print("loaded", round(time.time() - t0, 1), flush=True)

LABELS0 = ["ABS_dz", "MX_dz", "BR_dz", "SR_dz"] + [f"XR_{k}_{q}" for k in ("raw", "br", "vn", "vnx") for q in (30, 20, 10)]
full, summ = {}, {}
LABELS = ONLY if ONLY else LABELS0
for name in LABELS:
    lab = Z[name].astype("float64")
    mk = U & ~np.isnan(lab)
    rep = L.event_report(lab, mk, P, F)
    full[name] = rep
    s = {"n": rep["n"], "overall": rep["overall"],
         "by_year_pos": {y: v.get("1.0") for y, v in rep["by_year"].items()},
         "by_year_neg": {y: v.get("-1.0") for y, v in rep["by_year"].items()},
         "monthly_pos": {k: rep["monthly_pos"][k] for k in ("mean", "std", "min", "max")},
         "by_regime_pos": {k: v.get("1.0") for k, v in rep["by_regime"].items()},
         "by_regime_neg": {k: v.get("-1.0") for k, v in rep["by_regime"].items()},
         "by_liq_pos": {k: v.get("1.0") for k, v in rep["by_liquidity_tercile"].items()},
         "corr_monthly_pos_vs_mkt_ret": rep.get("corr_monthly_pos_vs_mkt_ret")}
    # --- absolute P&L coherence of each class (key risk) ---
    df = pd.DataFrame({"y": lab[mk], "r": r[mk], "reg": reg[mk], "yr": years[mk], "fno": fno[mk]})
    coh = {}
    for cls in (1.0, -1.0):
        g = df[df.y == cls]
        if len(g) == 0:
            continue
        def _c(x):
            return {"n": int(len(x)), "mean_r_bps": float(x.r.mean() * 1e4), "median_r_bps": float(x.r.median() * 1e4),
                    "p_abs_loss_gross": float((x.r <= 0).mean()) if cls == 1 else float((x.r >= 0).mean()),
                    "p_abs_loss_net50": float((x.r < 0.005).mean()) if cls == 1 else float((x.r > -0.005).mean())}
        coh[str(cls)] = {"all": _c(g), "by_regime": {k: _c(v) for k, v in g.groupby("reg")},
                         "by_year": {int(k): _c(v) for k, v in g.groupby("yr")},
                         "fno_only": _c(g[g.fno])}
    sp = df.groupby("reg").apply(lambda x: float((x.r[x.y == 1].mean() - x.r[x.y == -1].mean()) * 1e4), include_groups=False)
    coh["spread_pos_minus_neg_bps_by_regime"] = sp.to_dict()
    coh["spread_pos_minus_neg_bps_by_year"] = df.groupby("yr").apply(
        lambda x: float((x.r[x.y == 1].mean() - x.r[x.y == -1].mean()) * 1e4), include_groups=False).to_dict()
    s["coherence"] = coh
    # --- composition tilt vs market (residual regime bias of relative labels) ---
    td = pd.DataFrame({"d": dates[mk], "y": lab[mk], "b": beta[mk], "v": vol[mk], "m": m[mk]})
    pos_ = td[td.y == 1].groupby("d")[["b", "v"]].mean()
    neg_ = td[td.y == -1].groupby("d")[["b", "v"]].mean()
    mm = td.groupby("d").m.first()
    tl = (pos_ - neg_).join(mm, how="inner").dropna()
    s["tilt"] = {"mean_beta_tilt": float(tl.b.mean()), "mean_vol_tilt": float(tl.v.mean()),
                 "corr_beta_tilt_vs_mkt_window_ret": float(tl.b.corr(tl.m)),
                 "corr_vol_tilt_vs_mkt_window_ret": float(tl.v.corr(tl.m)),
                 "beta_tilt_mkt_up_windows": float(tl.b[tl.m > 0].mean()),
                 "beta_tilt_mkt_down_windows": float(tl.b[tl.m <= 0].mean())}
    # --- overlap and clustering of the +1 indicator ---
    ypos = np.where(np.isnan(lab), np.nan, (lab == 1).astype(float))
    ypos_m = np.where(mk, ypos, np.nan)
    vl = fw.at(ypos_m, -1)
    ok = ~np.isnan(ypos_m) & ~np.isnan(vl)
    idx = np.flatnonzero(ok)
    idx = np.random.default_rng(0).choice(idx, min(300000, len(idx)), replace=False)
    s["lag1_autocorr_pos"] = float(np.corrcoef(ypos_m[idx], vl[idx])[0, 1])
    yy = pd.Series(ypos_m[mk])
    dm = yy.groupby(dates[mk]).transform("mean")
    s["eta2_date_pos"] = float(dm.var() / yy.var())
    summ[name] = s
    print(name, round(time.time() - t0, 1), json.dumps({"overall": rep["overall"], "mstd": s["monthly_pos"]["std"],
                                                        "corr": s["corr_monthly_pos_vs_mkt_ret"],
                                                        "eta2": s["eta2_date_pos"], "tilt": s["tilt"]["corr_beta_tilt_vs_mkt_window_ret"]}), flush=True)

if ONLY:
    save(f"s7_events_h{h}_extra", summ)
    with open(f"{OUT}/events_h{h}_extra.json", "w") as fh:
        json.dump(full, fh, default=float)
    sys.exit(0)
# continuous label summaries (distribution + monthly mean vs market)
cont = {}
mret = L.market_series("Nifty 500")["close"].resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)
for name in ("r", "ex", "br", "sr"):
    x = Z[name].astype("float64")
    mk = U & np.isfinite(x)
    xs = x[mk]
    mon = pd.Series(xs).groupby(pd.DatetimeIndex(dates[mk]).to_period("M").astype(str)).mean()
    j = pd.concat([mon, mret], axis=1, join="inner").dropna()
    cont[name] = {"mean_bps": float(xs.mean() * 1e4), "median_bps": float(np.median(xs) * 1e4), "std_bps": float(xs.std() * 1e4),
                  "p_gt_50bps": float((xs > 0.005).mean()), "p_lt_m50bps": float((xs < -0.005).mean()),
                  "monthly_mean_std_bps": float(mon.std() * 1e4),
                  "corr_monthly_mean_vs_mkt_ret": float(j.iloc[:, 0].corr(j.iloc[:, 1])),
                  "eta2_date": float(pd.Series(xs).groupby(dates[mk]).transform("mean").var() / xs.var()),
                  "by_year_mean_bps": pd.Series(xs).groupby(years[mk]).mean().mul(1e4).to_dict()}
summ["_continuous"] = cont
# SR label split by sector-known vs NA (snapshot-sector caveat)
lab = Z["SR_dz"].astype("float64")
mk = U & ~np.isnan(lab)
summ["_SR_by_sector_known"] = {str(k): {str(c): float((lab[mk & (known == k)] == c).mean()) for c in (-1.0, 0.0, 1.0)}
                               for k in (True, False)}
summ["_SR_use_sector_median_share"] = float(Z["use_sec"][mk].mean())
with open(f"{OUT}/events_h{h}.json", "w") as fh:
    json.dump(full, fh, default=float)
save(f"s2_events_h{h}", summ)
print("done", round(time.time() - t0, 1))
