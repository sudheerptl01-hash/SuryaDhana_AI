"""R3_risk item 4 inputs: per-signal-date monitoring metrics of the frozen PROD score.
  ic        = Spearman(PROD, label pct) over elig_base rows with both finite (label known at t+20)
  rel_hit   = share of PROD top-20 with label pct > 0.5 (beat the median residual)
  abs_hit   = share of PROD top-20 with net 20d return (r - 50 bps) > 0
  top_ex    = mean r(top-20) - mean r(universe)
  avoid_ex  = mean r(bottom 30% PROD) - mean r(universe)
  ovl20     = share of today's top-20 entities that were in the top-20 20 trading days earlier (same sleeve)
  ovl5      = same vs 5 trading days earlier (previous weekly signal)
Saved per calendar date to ic_series.npz; DEV / 2026 summaries and weekly normal bands to results.json."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402
import lablib as L  # noqa: E402

OUT = C.set_agent("R3_risk")
P = L.load_panel(["date", "entity"])
F = L.load_features(["elig_base"])
E = F["elig_base"].values.astype(bool)
del F
Z = C.load_prod()
prod = Z["prod"]
lab = np.load(f"{LAB}/results/R3_devil/label_h20_neumom.npz")
C.log("label keys", lab.files)
pct = lab["pct"].astype("float64")
r = lab["r"].astype("float64")
C.log("pct identical to PROD file pct:", bool(np.allclose(np.nan_to_num(pct, nan=-9), np.nan_to_num(Z["pct"], nan=-9))))
d = P["date"].values.astype("datetime64[D]")
cal = np.unique(d)
didx = np.searchsorted(cal, d)
ent = pd.factorize(P["entity"].values)[0]
del P

# ---------------- IC per date (vectorised Spearman)
m = E & np.isfinite(prod) & np.isfinite(pct)
df = pd.DataFrame({"g": didx[m], "s": prod[m], "y": pct[m]})
df["rs"] = df.groupby("g").s.rank()
df["ry"] = df.groupby("g").y.rank()
df["xy"] = df.rs * df.ry
df["xx"] = df.rs * df.rs
df["yy"] = df.ry * df.ry
gs = df.groupby("g").agg(n=("rs", "size"), sx=("rs", "sum"), sy=("ry", "sum"), sxy=("xy", "sum"), sxx=("xx", "sum"),
                         syy=("yy", "sum"))
cov = gs.sxy - gs.sx * gs.sy / gs.n
ic = cov / np.sqrt((gs.sxx - gs.sx ** 2 / gs.n) * (gs.syy - gs.sy ** 2 / gs.n))
ic[gs.n < 30] = np.nan
IC = np.full(len(cal), np.nan)
IC[ic.index.values] = ic.values
C.log("IC dates", int(np.isfinite(IC).sum()), "first", str(cal[np.isfinite(IC)][0]), "last", str(cal[np.isfinite(IC)][-1]))

# ---------------- book-level per-date metrics
ms = E & np.isfinite(prod)
rows = pd.DataFrame({"g": didx[ms], "i": np.flatnonzero(ms), "s": prod[ms]})
rows = rows.sort_values(["g", "s"], ascending=[True, False])
rows["rk"] = rows.groupby("g").cumcount()
rows["pr"] = rows.groupby("g").s.rank(pct=True)
top = rows[rows.rk < 20]
bot = rows[rows.pr <= 0.30]
NC = len(cal)
rel_hit, abs_hit, top_ex, avoid_ex, ovl20, ovl5, n_univ = (np.full(NC, np.nan) for _ in range(7))
ri = r[rows.i.values]
uni_mean = pd.Series(ri).groupby(rows.g.values).mean()        # nan-skipping mean of r over the universe
n_univ_s = pd.Series(np.isfinite(ri)).groupby(rows.g.values).sum()
t_i = top.i.values
t_g = top.g.values
tr = r[t_i]
tp = pct[t_i]
s_rel = pd.Series(np.where(np.isfinite(tp), (tp > 0.5).astype(float), np.nan)).groupby(t_g).mean()
s_abs = pd.Series(np.where(np.isfinite(tr), (tr - 0.005 > 0).astype(float), np.nan)).groupby(t_g).mean()
s_top = pd.Series(tr).groupby(t_g).mean()
s_bot = pd.Series(r[bot.i.values]).groupby(bot.g.values).mean()
for arr, s in ((rel_hit, s_rel), (abs_hit, s_abs)):
    arr[s.index.values] = s.values
top_ex[s_top.index.values] = s_top.values - uni_mean.reindex(s_top.index).values
avoid_ex[s_bot.index.values] = s_bot.values - uni_mean.reindex(s_bot.index).values
n_univ[n_univ_s.index.values] = n_univ_s.values
# overlap of top-20 entity sets
top_sets = {g: set(ent[ii]) for g, ii in top.groupby("g").i}
for g in top_sets:
    for lagk, arr in ((20, ovl20), (5, ovl5)):
        if g - lagk in top_sets:
            arr[g] = len(top_sets[g] & top_sets[g - lagk]) / 20.0
# matured: metrics needing r / pct are NaN when the 20d window is not finished (r NaN for all rows)
ser = pd.DataFrame({"ic": IC, "rel_hit": rel_hit, "abs_hit": abs_hit, "top_ex": top_ex, "avoid_ex": avoid_ex,
                    "ovl20": ovl20, "ovl5": ovl5, "n_univ_labelled": n_univ}, index=pd.DatetimeIndex(cal))
ser = ser[ser.index >= "2023-01-01"]
np.savez(f"{OUT}/ic_series.npz", dates=ser.index.values.astype("datetime64[D]").astype(str),
         **{c: ser[c].values for c in ser.columns})

# ---------------- summaries: DEV (labels matured inside DEV) and 2026
g_dev_end = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
dev_last_sig = cal[g_dev_end - 20]
dev = ser[(ser.index >= "2023-01-01") & (ser.index <= str(dev_last_sig))]
hold = ser[ser.index >= "2026-01-01"].dropna(subset=["ic"])
wk = lambda x: x.groupby(x.index.to_period("W-FRI")).mean()  # noqa: E731


def band(s):
    s = s.dropna()
    return {"mean": float(s.mean()), "p10": float(s.quantile(0.10)), "p50": float(s.quantile(0.5)),
            "p90": float(s.quantile(0.90)), "min": float(s.min()), "max": float(s.max()), "n": int(len(s))}


summ = {"dev_last_signal_date_with_matured_label": str(dev_last_sig),
        "hold_last_signal_date_with_matured_label": str(hold.index[-1].date()) if len(hold) else None}
for name, sub in (("dev", dev), ("hold_2026", hold)):
    w = wk(sub)
    out = {}
    for c in ("ic", "rel_hit", "abs_hit", "top_ex", "avoid_ex", "ovl20", "ovl5"):
        out[c] = {"daily": band(sub[c]), "weekly": band(w[c]), "rolling13w": band(w[c].rolling(13, min_periods=13).mean())}
    out["n_signal_dates"] = int(sub.ic.notna().sum())
    # IC non-overlapping t (every 20th date)
    x = sub.ic.dropna().iloc[::20]
    out["ic_t_nonoverlap"] = float(x.mean() / (x.std() / np.sqrt(len(x))))
    out["ic_autocorr_daily_lag1"] = float(sub.ic.dropna().autocorr(1))
    out["ic_autocorr_daily_lag20"] = float(sub.ic.dropna().autocorr(20))
    summ[name] = out
    C.log(name, "IC", C.short(out["ic"]["daily"]), "rel_hit", C.short(out["rel_hit"]["daily"]),
          "abs_hit", C.short(out["abs_hit"]["daily"]), "avoid_ex", C.short(out["avoid_ex"]["daily"]),
          "top_ex", C.short(out["top_ex"]["daily"]), "ovl20", C.short(out["ovl20"]["daily"]), "t", out["ic_t_nonoverlap"])
# IC by year
summ["ic_by_year"] = {int(y): float(g.ic.mean()) for y, g in ser.dropna(subset=["ic"]).groupby(ser.dropna(subset=["ic"]).index.year)}
summ["avoid_ex_by_year"] = {int(y): float(g.avoid_ex.mean()) for y, g in ser.dropna(subset=["avoid_ex"]).groupby(
    ser.dropna(subset=["avoid_ex"]).index.year)}
summ["top_ex_by_year"] = {int(y): float(g.top_ex.mean()) for y, g in ser.dropna(subset=["top_ex"]).groupby(
    ser.dropna(subset=["top_ex"]).index.year)}
summ["rel_hit_by_year"] = {int(y): float(g.rel_hit.mean()) for y, g in ser.dropna(subset=["rel_hit"]).groupby(
    ser.dropna(subset=["rel_hit"]).index.year)}
C.log("by year IC", C.short(summ["ic_by_year"]), "avoid", C.short(summ["avoid_ex_by_year"]),
      "top", C.short(summ["top_ex_by_year"]), "relhit", C.short(summ["rel_hit_by_year"]))
C.save("item4_monitor_metrics", summ)
C.log("done")
