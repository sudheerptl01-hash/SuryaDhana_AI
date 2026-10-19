"""Stage 1 (devil): re-derive XR_neumom h=20 continuous residual rank from scratch.

Own implementation (no refiner code):
  * segments, forward window validity and the executable return are computed here from raw panel
    columns and then cross-checked against lablib's Fwd / fwd_return (to audit the lab too);
  * per-date winsorisation via groupby quantile; per-date OLS via stacked normal equations
    (np.add.reduceat + batched solve), not lstsq;
  * percentile rank of the residual per date (average ties), in (0,1].
Cross-check against R2_rel's stored label at the end.
"""
import numpy as np
import pandas as pd

from common import OUT, L, log, save

H = 20
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "beta_60", "vol_20", "log_turn20", "mom_12_1", "fno_proxy", "elig_liq5"])
n = len(P)
log("loaded", n)

# ---------------------------------------------------------------- own forward window
ent = P["entity"].values
brk = P["seg_break"].values.astype(bool)
seg = np.cumsum(np.r_[True, ent[1:] != ent[:-1]] | brk)
d = P["date"].values.astype("datetime64[D]")
lb = P["label_block"].values.astype(bool)
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
i = np.arange(n)
j1 = np.minimum(i + 1, n - 1)
jh = np.minimum(i + H, n - 1)
same1 = (i + 1 < n) & (seg[j1] == seg)
sameh = (i + H < n) & (seg[jh] == seg)
span = (d[jh] - d).astype("int64")
cap = int(np.ceil(H * 7 / 5)) + 8
lbc = np.cumsum(lb)
clean = (lbc[jh] - lbc) == 0                      # no label_block in rows (t, t+H]
ok = sameh & same1 & (span <= cap) & clean
r = np.full(n, np.nan)
r[ok] = c[jh[ok]] / o[j1[ok]] - 1
r[~np.isfinite(r)] = np.nan

# audit vs lablib
fw = L.Fwd(P)
r_lab = L.fwd_return(P, fw, H)
both = np.isfinite(r) & np.isfinite(r_lab)
audit = {"rows_finite_own": int(np.isfinite(r).sum()), "rows_finite_lablib": int(np.isfinite(r_lab).sum()),
         "finite_mismatch": int((np.isfinite(r) != np.isfinite(r_lab)).sum()),
         "max_abs_diff": float(np.nanmax(np.abs(r[both] - r_lab[both])))}
log("audit fwd", audit)
del fw, r_lab

# ---------------------------------------------------------------- cross-section V_t
E = F["elig_base"].values.astype(bool)
V = E & np.isfinite(r)
iv = np.flatnonzero(V)
dv = d[iv]
order = np.argsort(dv, kind="stable")
iv, dv = iv[order], dv[order]
starts = np.flatnonzero(np.r_[True, dv[1:] != dv[:-1]])
gid = np.cumsum(np.r_[True, dv[1:] != dv[:-1]]) - 1
ng = len(starts)
cnt = np.diff(np.r_[starts, len(iv)])
log("V rows", len(iv), "dates", ng, "min/median names", cnt.min(), np.median(cnt))

y = r[iv]
df = pd.DataFrame({"g": gid, "y": y})
q = df.groupby("g")["y"].quantile([0.01, 0.99]).unstack()
lo, hi = q[0.01].values[gid], q[0.99].values[gid]
yw = np.clip(y, lo, hi)

beta = 0.5 * np.clip(F["beta_60"].values.astype("float64")[iv], 0.0, 3.0) + 0.5
vol = F["vol_20"].values.astype("float64")[iv]
lt = F["log_turn20"].values.astype("float64")[iv]
mom = F["mom_12_1"].values.astype("float64")[iv]
med = pd.Series(mom).groupby(gid).median().reindex(np.arange(ng)).fillna(0.0).values
mom_f = np.where(np.isnan(mom), med[gid], mom)
X = np.column_stack([np.ones(len(iv)), beta, vol, lt, mom_f])
assert np.isfinite(X).all(), "non-finite regressor"
k = X.shape[1]
XtX = np.empty((ng, k, k))
Xty = np.empty((ng, k))
for a in range(k):
    Xty[:, a] = np.add.reduceat(X[:, a] * yw, starts)
    for b in range(a, k):
        v_ = np.add.reduceat(X[:, a] * X[:, b], starts)
        XtX[:, a, b] = v_
        XtX[:, b, a] = v_
# dates where mom_12_1 is NaN for every name (before 250 bars of history exist) have a constant
# mom column -> drop it there (equivalent to the minimum-norm least-squares solution)
n_mom = pd.Series(np.isfinite(mom)).groupby(gid).sum().reindex(np.arange(ng)).fillna(0).values
const_mom = n_mom == 0
B = np.zeros((ng, k))
full = ~const_mom
B[full] = np.linalg.solve(XtX[full], Xty[full][..., None])[..., 0]
if const_mom.any():
    B[const_mom, :4] = np.linalg.solve(XtX[const_mom][:, :4, :4], Xty[const_mom][:, :4, None])[..., 0]
log("dates with no mom_12_1 (mom column dropped):", int(const_mom.sum()))
res = yw - (X * B[gid]).sum(1)
tss = pd.Series((yw - pd.Series(yw).groupby(gid).transform("mean").values) ** 2).groupby(gid).sum().values
rss = pd.Series(res ** 2).groupby(gid).sum().values
r2 = 1 - rss / tss
pct_v = pd.Series(res).groupby(gid).rank(pct=True, method="average").values

pct = np.full(n, np.nan)
pct[iv] = pct_v
resid = np.full(n, np.nan)
resid[iv] = res
cls = np.where(pct > 0.7, 1.0, np.where(pct <= 0.3, -1.0, 0.0))
cls[np.isnan(pct)] = np.nan

# ---------------------------------------------------------------- diagnostics
yr = pd.DatetimeIndex(d[iv]).year
cv = cls[iv]
ev = {"overall": {str(cc): float((cv == cc).mean()) for cc in (-1, 0, 1)},
      "by_year": {int(Y): {str(cc): float((cv[yr == Y] == cc).mean()) for cc in (-1, 0, 1)} for Y in np.unique(yr)},
      "fno_proxy": {str(cc): float((cls[V & F["fno_proxy"].values.astype(bool)] == cc).mean()) for cc in (-1, 0, 1)},
      "liq5": {str(cc): float((cls[V & F["elig_liq5"].values.astype(bool)] == cc).mean()) for cc in (-1, 0, 1)}}
daily_pos = pd.Series(cv == 1).groupby(gid).mean()
ev["daily_pos_share_sd"] = float(daily_pos.std())
ev["mean_xs_R2"] = float(np.nanmean(r2))
ev["coef_mean"] = {nm: float(B[:, a].mean()) for a, nm in enumerate(["const", "beta_s", "vol_20", "log_turn20", "mom_12_1"])}
ev["mom_nan_share_V"] = float(np.isnan(mom).mean())
ev["V_rows"] = int(len(iv))
ev["V_share_of_elig"] = float(len(iv) / E.sum())
log("event rates", ev["overall"], "R2", ev["mean_xs_R2"])

# ---------------------------------------------------------------- compare with R2_rel's stored label
cmp = {}
try:
    z = np.load(f"{L.LAB}/results/R2_rel/labels_h20.npz")
    p2 = z["pct_neumom"].astype("float64")
    m = np.isfinite(pct) | np.isfinite(p2)
    cmp["finite_mismatch"] = int((np.isfinite(pct) != np.isfinite(p2))[m].sum())
    bb = np.isfinite(pct) & np.isfinite(p2)
    cmp["max_abs_diff_pct"] = float(np.abs(pct[bb] - p2[bb]).max())
    cmp["corr"] = float(np.corrcoef(pct[bb], p2[bb])[0, 1])
    c2 = np.where(p2 > 0.7, 1, np.where(p2 <= 0.3, -1, 0))
    cmp["class_disagree_share"] = float((cls[bb] != c2[bb]).mean())
except Exception as e:  # noqa: BLE001
    cmp["error"] = str(e)
log("vs R2_rel", cmp)

np.savez_compressed(f"{OUT}/label_h20_neumom.npz", pct=pct.astype(np.float64), r=r, resid=resid)
save("s1_label", {"audit_fwd_vs_lablib": audit, "event_rates": ev, "vs_R2_rel_label": cmp,
                  "definition": "r=close[t+20]/open[t+1]-1 (NaN unless same segment, span<=36d, no label_block in "
                                "(t,t+20]); V_t=elig_base&finite r; winsorise 1/99 pct per date; OLS on [1, "
                                "0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20, mom_12_1(NaN->date median over V_t)]; "
                                "pct rank of residual per date"})
