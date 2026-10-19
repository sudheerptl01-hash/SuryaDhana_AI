"""Stage 1: date-level timing dataset (one row per trading date, all PIT) + the stock-level
evidence that absolute labels mostly encode the market.

Targets (signal at close of date g, executable):
  n500_f{h}  = Nifty 500 open[g+1] -> close[g+h]                       (L.market_fwd logic)
  ew_f{h}    = mean over elig_base rows on g of open[t+1] -> close[t+h]  (L.fwd_return; NaN rows dropped)
  pos{h}     = share of those rows with r_h > 0  (= the absolute sign label's daily +1 share)
Features (date-level, PIT): the 10 lab market features + vix_med250 / vix_rel (trailing 250d
median incl. today, min 120 obs) + index open-to-open return for exact index-overlay tests.
"""
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, MKT_FEATS, DEV, nw_corr_t

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "elig_liq5"] + MKT_FEATS)
fw = L.Fwd(P)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
U = F["elig_base"].values.astype(bool)
print("loaded", round(time.time() - t0, 1), flush=True)

# ------------------------------------------------------------------ date-level features
fm = F[MKT_FEATS].copy()
fm["d"] = dates
g = fm.groupby("d")
nun = g.nunique().max()
D = g.first().reindex(cal)
D.index = pd.DatetimeIndex(cal)
D.index.name = "date"
print("max per-date distinct values (should be <=1):", nun.to_dict(), flush=True)

vix = L.market_series("India VIX")["close"].reindex(D.index).ffill()
assert np.allclose(vix.values, D["vix"].values, equal_nan=True), "vix mismatch"
D["vix_med250"] = vix.rolling(250, min_periods=120).median()
D["vix_rel"] = vix / D["vix_med250"] - 1

mk = L.market_series("Nifty 500").reindex(D.index).ffill()
mo, mc = mk["open"].values.astype(float), mk["close"].values.astype(float)
D["n500_open"], D["n500_close"] = mo, mc
nC = len(cal)
for h in (10, 20):
    f = np.full(nC, np.nan)
    gg = np.arange(nC)
    ok = gg + h < nC
    f[ok] = mc[gg[ok] + h] / mo[gg[ok] + 1] - 1
    D[f"n500_f{h}"] = f
# open[g] -> open[g+1] (an overlay decided at close g holds open[g+1] -> open[g+2] = r_oo[g+1])
D["n500_r_oo"] = np.r_[mo[1:] / mo[:-1] - 1, np.nan]
D["n500_r_cc"] = np.r_[np.nan, mc[1:] / mc[:-1] - 1]

# ------------------------------------------------------------------ EW-universe targets
for h in (10, 20):
    r = L.fwd_return(P, fw, h)
    V = U & np.isfinite(r)
    s = pd.DataFrame({"d": dates[V], "r": r[V]})
    agg = s.groupby("d").r.agg(["mean", "count", lambda x: (x > 0).mean()])
    agg.columns = ["mean", "n", "pos"]
    agg = agg.reindex(cal)
    nU = pd.Series(U).groupby(dates).sum().reindex(cal).values
    D[f"ew_f{h}"] = agg["mean"].values
    D[f"ew_n{h}"] = agg["n"].values
    D[f"ew_cov{h}"] = agg["n"].values / np.maximum(nU, 1)
    D[f"pos{h}"] = agg["pos"].values
    if h == 20:
        r20, V20 = r, V
D["n_elig"] = pd.Series(U).groupby(dates).sum().reindex(cal).values
D["year"] = D.index.year
D.to_parquet(f"{OUT}/dateset.parquet")
print("dateset saved", D.shape, round(time.time() - t0, 1), flush=True)

# ------------------------------------------------------------------ absolute label = market?
out = {}
x = r20[V20]
dd = dates[V20]
lo, hi = np.nanpercentile(x, [0.5, 99.5])
xc = np.clip(x, lo, hi)
s = pd.DataFrame({"d": dd, "r": xc, "y": (x > 0).astype(float)})
for col in ("r", "y"):
    gm = s.groupby("d")[col].transform("mean").values
    tot = ((s[col].values - s[col].mean()) ** 2).sum()
    btw = ((gm - s[col].mean()) ** 2).sum()
    out[f"between_date_var_share_{col}"] = float(btw / tot)
for nm, (a, b) in (("dev", DEV), ("holdout", ("2026-01-01", "2026-12-31")), ("all", ("2021-01-01", "2026-12-31"))):
    sub = D[(D.index >= a) & (D.index <= b)].dropna(subset=["pos20", "n500_f20", "ew_f20"])
    rho_n, t_n = nw_corr_t(sub["pos20"].values, sub["n500_f20"].values, 20)
    rho_e, t_e = nw_corr_t(sub["pos20"].values, sub["ew_f20"].values, 20)
    out[nm] = {"dates": int(len(sub)),
               "pos20_mean": float(sub.pos20.mean()), "pos20_min": float(sub.pos20.min()),
               "pos20_max": float(sub.pos20.max()), "pos20_sd": float(sub.pos20.std()),
               "pearson_pos20_vs_n500_f20": float(np.corrcoef(sub.pos20, sub.n500_f20)[0, 1]),
               "pearson_pos20_vs_ew_f20": float(np.corrcoef(sub.pos20, sub.ew_f20)[0, 1]),
               "spearman_pos20_vs_n500_f20": rho_n, "nw_t": t_n,
               "spearman_pos20_vs_ew_f20": rho_e, "nw_t_ew": t_e,
               "n500_f20_gt0_share": float((sub.n500_f20 > 0).mean()),
               "n500_f20_gt1pct_share": float((sub.n500_f20 > 0.01).mean()),
               "ew_f20_gt0_share": float((sub.ew_f20 > 0).mean()),
               "corr_n500_f20_ew_f20": float(np.corrcoef(sub.n500_f20, sub.ew_f20)[0, 1]),
               "n500_f20_mean": float(sub.n500_f20.mean()), "ew_f20_mean": float(sub.ew_f20.mean()),
               "n500_f20_sd": float(sub.n500_f20.std()), "ew_f20_sd": float(sub.ew_f20.std())}
# by year base rates of the three timing targets
by = {}
for y, sub0 in D.dropna(subset=["n500_f20"]).groupby("year"):
    sub = sub0.dropna(subset=["ew_f20"])
    by[int(y)] = {"dates_n500": int(len(sub0)), "dates_ew": int(len(sub)),
                  "first_ew_date": str(sub.index.min())[:10] if len(sub) else None,
                  "n500_gt0": float((sub0.n500_f20 > 0).mean()),
                  "n500_gt1": float((sub0.n500_f20 > 0.01).mean()),
                  "ew_gt0": float((sub.ew_f20 > 0).mean()),
                  "n500_gt0_same_dates_as_ew": float((sub.n500_f20 > 0).mean()),
                  "pos20_mean": float(sub.pos20.mean()),
                  "ew_cov20_mean": float(sub.ew_cov20.mean()),
                  "n500_f20_mean": float(sub0.n500_f20.mean()), "ew_f20_mean": float(sub.ew_f20.mean())}
out["targets_by_year"] = by
# NaN availability of features by year
out["feature_nan_share_by_year"] = {c: {int(y): float(v) for y, v in D[c].isna().groupby(D.year).mean().items()}
                                    for c in MKT_FEATS + ["vix_rel"]}
save("s1_dateset", out)
print(out, flush=True)
print("total", round(time.time() - t0, 1))
