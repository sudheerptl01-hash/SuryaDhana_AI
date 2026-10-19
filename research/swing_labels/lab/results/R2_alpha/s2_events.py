"""Stage 2: event-rate scorecard of the three alpha-source labels on U = elig_base (h=20).

XR (30/40/30 form of the XR_neu pct), BAR (A2 barrier), TSX (trend-scan T5). For each:
L.event_report (overall / year / month / regime / liquidity tercile / corr with Nifty month),
per-date share of +1 vs the Nifty 500 return over the same executable window (sharper regime test),
label/P&L coherence (mean net at 50 bps, P(net>0), excess vs same-date EW mean, per class),
and agreement between labels (row-level class agreement; per-date Spearman of the continuous forms).
Event-rate sensitivity: XR cut q in {0.2, 0.3, 1/3}; BAR geometry pt/sl in {2/2, 3/1.5, 3/3, 4/2};
TSX threshold T in {3, 5, 8}.
"""
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from common import OUT, L, save, date_blocks

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["log_turn20", "mkt_dist_sma200", "mkt_mom20", "atr_pct"])
Z = np.load(f"{OUT}/labels.npz")
U = Z["U"]
dates = P["date"].values.astype("datetime64[D]")
r = Z["r20"].astype("float64")
m20 = Z["m20"].astype("float64")
ew = Z["ew20"].astype("float64")
pct = Z["pct"].astype("float64")
bar = Z["bar"].astype("float64")
tsx = Z["tsx"].astype("float64")
tsx_t = Z["tsx_t"].astype("float64")


def cls3(p, q):
    out = np.where(p > 1 - q, 1.0, np.where(p <= q, -1.0, 0.0))
    out[~np.isfinite(p)] = np.nan
    return out


XR = cls3(pct, 0.3)
LABS = {"XR": XR, "BAR": bar, "TSX": tsx}
out = {}
for nm, y in LABS.items():
    rep = L.event_report(y, U, P, F)
    rep["monthly_pos"].pop("series", None)
    m = U & np.isfinite(y)
    # per-date +1 share vs market over the same window
    df = pd.DataFrame({"d": dates[m], "pos": (y[m] == 1).astype(float), "m": m20[m]})
    g = df.groupby("d").agg(pos=("pos", "mean"), m=("m", "mean"))
    rep["daily_pos_share"] = {"mean": float(g.pos.mean()), "std": float(g.pos.std()),
                              "min": float(g.pos.min()), "max": float(g.pos.max()),
                              "corr_with_mkt_same_window": float(g.pos.corr(g.m))}
    # coherence
    net = r - 0.005
    xs = r - ew
    coh = {}
    for c in (1.0, 0.0, -1.0):
        mm = m & (y == c)
        coh[str(int(c))] = {"share": float(mm.sum() / m.sum()), "mean_net_bps": float(np.nanmean(net[mm]) * 1e4),
                            "p_net_pos": float(np.nanmean(net[mm] > 0)),
                            "mean_excess_vs_ew_bps": float(np.nanmean(xs[mm]) * 1e4)}
    rep["coherence_50bps"] = coh
    yrs = pd.DatetimeIndex(dates[m]).year
    t = pd.DataFrame({"y": y[m], "net": net[m], "yr": yrs})
    rep["coherence_by_year"] = {int(a): {"p_net_pos_given_pos": float((gq.net[gq.y == 1] > 0).mean()),
                                         "mean_net_bps_pos": float(gq.net[gq.y == 1].mean() * 1e4),
                                         "mean_net_bps_neg": float(gq.net[gq.y == -1].mean() * 1e4)}
                                for a, gq in t.groupby("yr")}
    out[nm] = rep
    print(nm, rep["overall"], rep["daily_pos_share"], flush=True)

# agreement between labels (row level) on rows where all three are defined
m3 = U & np.isfinite(XR) & np.isfinite(bar) & np.isfinite(tsx)
agree = {}
for a, b in (("XR", "BAR"), ("XR", "TSX"), ("BAR", "TSX")):
    ya, yb = LABS[a][m3], LABS[b][m3]
    agree[f"{a}_vs_{b}"] = {"P(b=+1|a=+1)": float((yb[ya == 1] == 1).mean()),
                            "P(b=-1|a=-1)": float((yb[ya == -1] == -1).mean()),
                            "P(b=-1|a=+1)": float((yb[ya == 1] == -1).mean()),
                            "P(b=+1|a=-1)": float((yb[ya == -1] == 1).mean()),
                            "row_corr": float(np.corrcoef(ya, yb)[0, 1])}
# per-date Spearman between continuous forms (XR pct, BAR signed net return, TSX t*)
cont = {"XR": pct, "BARret": Z["bar_ret"].astype("float64"), "TSXt": tsx_t, "r20": r}
idx, b0, e0 = date_blocks(dates, np.flatnonzero(m3))
recs = []
for s_, t_ in zip(b0, e0):
    ii = idx[s_:t_]
    if len(ii) < 30:
        continue
    rk = {k: rankdata(v[ii]) for k, v in cont.items()}
    recs.append({f"{a}~{b}": np.corrcoef(rk[a], rk[b])[0, 1]
                 for i, a in enumerate(cont) for b in list(cont)[i + 1:]})
agree["per_date_spearman_mean"] = pd.DataFrame(recs).mean().to_dict()
out["agreement"] = agree
print(agree, flush=True)

# event-rate sensitivity maps
sens = {}
mU = U & np.isfinite(pct)
for q in (0.2, 0.3, 1 / 3):
    y = cls3(pct, q)[mU]
    sens[f"XR_q{q:.3f}"] = {"+1": float((y == 1).mean()), "0": float((y == 0).mean()), "-1": float((y == -1).mean())}
fw = L.Fwd(P)
for pt_, sl_ in ((2.0, 2.0), (3.0, 1.5), (3.0, 3.0), (4.0, 2.0)):
    bl = L.barrier_labels(P, F, fw, h=20, pt=pt_, sl=sl_, tau_bps=50)
    y = bl["label"][U]
    tch = bl["touch"][U]
    ok = np.isfinite(y)
    y, tch = y[ok], tch[ok]
    mon = pd.Series((y == 1).astype(float)).groupby(pd.DatetimeIndex(dates[U][ok]).to_period("M")).mean()
    sens[f"BAR_pt{pt_}_sl{sl_}"] = {"+1": float((y == 1).mean()), "0": float((y == 0).mean()),
                                   "-1": float((y == -1).mean()), "target": float((tch == "pt").mean()),
                                   "stop": float((tch == "sl").mean()), "time": float((tch == "time").mean()),
                                   "monthly_pos_std": float(mon.std()), "monthly_pos_min": float(mon.min()),
                                   "monthly_pos_max": float(mon.max())}
    print("BAR", pt_, sl_, sens[f"BAR_pt{pt_}_sl{sl_}"], flush=True)
    del bl
for T in (3.0, 5.0, 8.0):
    yy = np.where(tsx_t >= T, 1.0, np.where(tsx_t <= -T, -1.0, 0.0))
    yy[~np.isfinite(tsx_t)] = np.nan
    y = yy[U]
    ok = np.isfinite(y)
    mon = pd.Series((y[ok] == 1).astype(float)).groupby(pd.DatetimeIndex(dates[U][ok]).to_period("M")).mean()
    sens[f"TSX_T{T:g}"] = {"+1": float((y[ok] == 1).mean()), "0": float((y[ok] == 0).mean()),
                           "-1": float((y[ok] == -1).mean()), "monthly_pos_std": float(mon.std()),
                           "monthly_pos_min": float(mon.min()), "monthly_pos_max": float(mon.max())}
out["sensitivity"] = sens
print(sens, flush=True)
save("s2_events", out)
print("total", round(time.time() - t0, 1))
