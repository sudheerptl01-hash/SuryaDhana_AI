#!/usr/bin/env python3
"""Stage 2: event-rate screening of every C_trendscan label variant on the equity universe
(elig_base minus ETFs).  No model, no selection on 2026: all choices use 2021-2025 numbers.

Also: Monte-Carlo null distribution of the trend-scan statistic (driftless random walks),
label/P&L coherence by class, L* distribution, overlap autocorrelation.
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save

t0 = time.time()
P = L.load_panel(["date", "entity", "seg_break", "label_block"])
F = L.load_features(["mkt_dist_sma200", "mkt_mom20", "log_turn20", "fno_proxy", "vol_20", "atr_pct"])
Z = dict(np.load(f"{OUT}/labels.npz"))
eq = Z["eq"]
dates = pd.DatetimeIndex(P["date"].values)
year = dates.year.values
month = dates.to_period("M").astype(str).values
mk = L.market_series("Nifty 500")["close"]
mret = mk.resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)
print("loaded", round(time.time() - t0, 1), flush=True)

# ------------------------------------------------------------------ null distribution
rng = np.random.default_rng(7)


def ts_stat(Y):
    """Y: (N, 21) with Y[:,0]=0. Returns best t, L* for L=5..20 (same algebra as s1)."""
    best = np.full(len(Y), -1.0)
    bt = np.zeros(len(Y))
    bl = np.zeros(len(Y))
    for k in range(5, 21):
        x = np.arange(k + 1, dtype=float)
        y = Y[:, :k + 1]
        xm = x.mean()
        ym = y.mean(1, keepdims=True)
        sxx = ((x - xm) ** 2).sum()
        sxy = ((x - xm) * (y - ym)).sum(1)
        b = sxy / sxx
        res = y - ym - b[:, None] * (x - xm)
        s2 = np.maximum((res ** 2).sum(1) / (k - 1), 1e-6)
        t = b / np.sqrt(s2 / sxx)
        u = np.abs(t) > best
        best = np.where(u, np.abs(t), best)
        bt = np.where(u, t, bt)
        bl = np.where(u, k, bl)
    return bt, bl


null = {}
for nm, gen in (("gauss_iid", lambda N: rng.standard_normal((N, 20)) * 0.02),
                ("student_t4_iid", lambda N: rng.standard_t(4, (N, 20)) * 0.02 / np.sqrt(2)),
                ("gauss_iid_first_bar_half_var", lambda N: rng.standard_normal((N, 20)) * 0.02
                 * np.r_[np.sqrt(0.5), np.ones(19)])):
    inc = gen(200000)
    Y = np.c_[np.zeros(len(inc)), np.cumsum(inc, 1)]
    bt, bl = ts_stat(Y)
    a = np.abs(bt)
    null[nm] = {"abs_t_quantiles": {q: float(np.quantile(a, q)) for q in (.1, .25, .5, .75, .9, .95, .99)},
                "share_abs_t_ge": {T: float((a >= T).mean()) for T in (2, 3, 5, 8, 10, 12)},
                "Lstar_hist": {int(k): float(v) for k, v in pd.Series(bl).value_counts(normalize=True).sort_index().items()}}
save("s2_null", null)
print("null done", round(time.time() - t0, 1), flush=True)

# ------------------------------------------------------------------ label definitions
r10, r20, r5 = Z["r10"].astype(float), Z["r20"].astype(float), Z["r5"].astype(float)
mr10, mr20 = Z["mr10"].astype(float), Z["mr20"].astype(float)
v10, v20 = Z["v10"], Z["v20"]
vol = F["vol_20"].values.astype(float)
atr = F["atr_pct"].values.astype(float)


def tern(pos, neg, valid):
    y = np.where(pos, 1.0, np.where(neg, -1.0, 0.0))
    y[~valid] = np.nan
    return y


labels = {}
natural = {}  # natural exit return of the label (for coherence)
tsA, tsX = Z["tsA_t"].astype(float), Z["tsX_t"].astype(float)
for T in (2, 3, 5, 8, 10):
    labels[f"TSA_T{T}"] = tern(tsA >= T, tsA <= -T, v20 & np.isfinite(tsA))
    natural[f"TSA_T{T}"] = Z["tsA_r"].astype(float)
    labels[f"TSX_T{T}"] = tern(tsX >= T, tsX <= -T, v20 & np.isfinite(tsX))
    natural[f"TSX_T{T}"] = Z["tsX_r"].astype(float)
for h, rr in ((10, r10), (20, r20)):
    thr = np.maximum(0.5 * vol * np.sqrt(h), 0.005)
    labels[f"RA{h}"] = tern(rr >= thr, rr <= -thr, np.isfinite(rr) & np.isfinite(vol))
    natural[f"RA{h}"] = rr
    # without the 50 bps floor (as literally specified) for the coverage stat
    thr0 = 0.5 * vol * np.sqrt(h)
    labels[f"RA{h}_nofloor"] = tern(rr >= thr0, rr <= -thr0, np.isfinite(rr) & np.isfinite(vol))
    natural[f"RA{h}_nofloor"] = rr
mfe, mae = Z["mfe"].astype(float), Z["mae"].astype(float)
for nm, scale in (("vol", vol * np.sqrt(20)), ("atr", atr * np.sqrt(20))):
    for a in ((0.75, 1.0, 1.5) if nm == "vol" else (0.5, 1.0, 2.0)):
        thr = a * scale
        pos = (mfe >= thr) & (mfe >= 2 * np.abs(mae))
        neg = (np.abs(mae) >= thr) & (np.abs(mae) >= 2 * mfe)
        key = f"MQ_{nm}{a}"
        labels[key] = tern(pos, neg, v20 & np.isfinite(mfe) & np.isfinite(thr))
        natural[key] = r20
for hw in (20, 10):
    labels[f"FP{hw}"] = Z[f"fp{hw}_lab"].astype(float)
    natural[f"FP{hw}"] = Z[f"fp{hw}_ret"].astype(float)
for h, rr in ((10, r10), (20, r20)):
    labels[f"FX{h}_pm50"] = tern(rr > 0.005, rr < -0.005, np.isfinite(rr))
    natural[f"FX{h}_pm50"] = rr
save("s2_variants", {"n_label_variants_screened": len(labels), "names": list(labels)})


# ------------------------------------------------------------------ reports
def monthly_share(y, m, cls):
    s = pd.Series((y[m] == cls).astype(float)).groupby(month[m]).mean()
    return s


def corr_with_mkt(s, lo=None, hi=None):
    j = pd.concat([s, mret], axis=1, join="inner").dropna()
    if lo:
        j = j[j.index >= lo]
    if hi:
        j = j[j.index <= hi]
    return float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) > 4 else None


out = {}
for name, y in labels.items():
    m = eq & np.isfinite(y)
    rep = L.event_report(y, m, P, F)
    rep.pop("monthly_pos", None)
    mp = monthly_share(y, m, 1)
    mn = monthly_share(y, m, -1)
    rep["monthly_pos"] = {"mean": float(mp.mean()), "std": float(mp.std()), "min": float(mp.min()), "max": float(mp.max())}
    rep["monthly_neg"] = {"mean": float(mn.mean()), "std": float(mn.std()), "min": float(mn.min()), "max": float(mn.max())}
    dev = mp.index <= "2025-12"
    rep["monthly_pos_std_dev"] = float(mp[dev].std())
    rep["corr_pos_mkt_dev"] = corr_with_mkt(mp, hi="2025-12")
    rep["corr_pos_mkt_2026"] = corr_with_mkt(mp, lo="2026-01")
    rep["corr_neg_mkt_dev"] = corr_with_mkt(mn, hi="2025-12")
    # coherence: what each class earns under different executions (gross; subtract 50 bps for net)
    coh = {}
    nat = natural[name]
    for cl in (1.0, 0.0, -1.0):
        k = m & (y == cl)
        if k.sum() == 0:
            continue
        coh[str(int(cl))] = {
            "share": float(k.sum() / m.sum()),
            "natural_exit_net50": float(np.nanmean(nat[k]) - 0.005),
            "fixed10_net50": float(np.nanmean(r10[k]) - 0.005),
            "fixed20_net50": float(np.nanmean(r20[k]) - 0.005),
            "fixed10_excess_mkt": float(np.nanmean(r10[k] - mr10[k])),
            "p_fixed10_net_pos": float(np.nanmean((r10[k] - 0.005) > 0)),
            "p_fixed20_net_pos": float(np.nanmean((r20[k] - 0.005) > 0)),
        }
    rep["coherence"] = coh
    # fno_proxy share of classes (short side realism)
    fno = F["fno_proxy"].values
    mf = m & fno
    rep["fno_overall"] = {str(int(cl)): float((y[mf] == cl).mean()) for cl in (1.0, 0.0, -1.0)}
    rep["fno_n"] = int(mf.sum())
    out[name] = rep
    print(name, rep["n"], {k: round(v, 3) for k, v in rep["overall"].items()},
          "mstd", round(rep["monthly_pos"]["std"], 3), "corr", round(rep.get("corr_monthly_pos_vs_mkt_ret", np.nan), 2),
          round(time.time() - t0, 1), flush=True)
save("s2_event_rates", out)

# ------------------------------------------------------------------ L* distribution & L*-bucket coherence
lst = {}
for fam, Lk, rk in (("TSA", "tsA_L", "tsA_r"), ("TSX", "tsX_L", "tsX_r")):
    Ls = Z[Lk].astype(float)
    tt = tsA if fam == "TSA" else tsX
    m = eq & v20 & np.isfinite(Ls)
    d = {"hist_all": {int(k): float(v) for k, v in pd.Series(Ls[m]).value_counts(normalize=True).sort_index().items()}}
    for T in (3, 5, 8):
        for side, cond in (("up", tt >= T), ("down", tt <= -T)):
            k = m & cond
            d[f"hist_T{T}_{side}"] = {int(a): float(b) for a, b in pd.Series(Ls[k]).value_counts(normalize=True).sort_index().items()}
            d[f"mean_L_T{T}_{side}"] = float(Ls[k].mean())
    # by-L* bucket coherence for T=5 up/down (oracle exit vs fixed holds)
    bk = pd.cut(Ls, [4, 8, 12, 16, 20], labels=["5-8", "9-12", "13-16", "17-20"])
    for T in (5,):
        for side, cond, sg in (("up", tt >= T, 1), ("down", tt <= -T, -1)):
            k = m & cond
            df = pd.DataFrame({"b": bk[k], "rL": Z[rk].astype(float)[k], "r10": r10[k], "r20": r20[k], "r5": r5[k]})
            g = df.groupby("b", observed=True).agg(share=("rL", "size"), rL=("rL", "mean"), r5=("r5", "mean"),
                                                   r10=("r10", "mean"), r20=("r20", "mean"))
            g["share"] = g["share"] / g["share"].sum()
            d[f"bucket_T{T}_{side}"] = g.round(5).to_dict(orient="index")
    d["mean_L_by_year"] = pd.Series(Ls[m]).groupby(year[m]).mean().round(3).to_dict()
    lst[fam] = d
save("s2_Lstar", lst)

# ------------------------------------------------------------------ overlap autocorrelation
ac = {}
for name in ("TSA_T5", "TSX_T5", "RA10", "RA20", "MQ_vol1.0", "FP20", "FX10_pm50", "FX20_pm50"):
    y = labels[name].copy()
    y[~eq] = np.nan
    ac[name] = {f"lag{lg}": L.overlap_autocorr(y, P, lag_=lg) for lg in (1, 5, 10)}
    print("ac", name, ac[name], flush=True)
save("s2_autocorr", ac)
print("done", round(time.time() - t0, 1))
