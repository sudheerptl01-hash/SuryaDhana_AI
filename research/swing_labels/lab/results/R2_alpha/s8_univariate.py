"""Stage 8: univariate per-date rank IC of each of the 52 PIT features vs the XR_neu20 target (pct) and
vs raw r20, on U; DEV mean + non-overlapping t (every 20th date), HOLD mean, by year. Also the partial
IC of the delivery features after removing (per date, rank-OLS) log_turn20, vol_20, mom_5 and
volz_20 — i.e. is delivery information distinct from liquidity / volatility / reversal / volume?
Used to interpret the group ablation (unique vs shared information).
"""
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from common import OUT, L, H, FEAT_GROUP, save, date_blocks

t0 = time.time()
P = L.load_panel(["date"])
dates = P["date"].values.astype("datetime64[D]")
F = L.load_features(L.FEATURES)
X = F[L.FEATURES].values.astype("float64")
del F
Z = np.load(f"{OUT}/labels.npz")
U = Z["U"]
pct = Z["pct"].astype("float64")
r20 = Z["r20"].astype("float64")
m = U & np.isfinite(pct) & (dates >= np.datetime64("2023-01-01"))
idx, b0, e0 = date_blocks(dates, np.flatnonzero(m))
DELIV = ["deliv_pct", "deliv_z20", "deliv_ratio", "xr_deliv_z"]
CTRL = ["log_turn20", "vol_20", "mom_5", "volz_20"]
di = [L.FEATURES.index(f) for f in DELIV]
ci = [L.FEATURES.index(f) for f in CTRL]
rows = []
for s_, t_ in zip(b0, e0):
    ii = idx[s_:t_]
    if len(ii) < 30:
        continue
    Xi = X[ii]
    ry = rankdata(pct[ii])
    rr = rankdata(r20[ii])
    rec = {"d": dates[ii[0]]}
    for k, f in enumerate(L.FEATURES):
        v = Xi[:, k]
        ok = np.isfinite(v)
        if ok.sum() < 30 or np.nanstd(v) == 0:
            continue
        rv = rankdata(v[ok])
        rec[f"xr|{f}"] = np.corrcoef(rv, rankdata(pct[ii][ok]))[0, 1]
        rec[f"raw|{f}"] = np.corrcoef(rv, rankdata(r20[ii][ok]))[0, 1]
    # partial IC of delivery features vs XR target controlling for CTRL (rank space)
    Cr = np.column_stack([np.ones(len(ii))] + [rankdata(np.nan_to_num(Xi[:, c], nan=np.nanmedian(Xi[:, c]))) for c in ci])
    ey = ry - Cr @ np.linalg.lstsq(Cr, ry, rcond=None)[0]
    for k, f in zip(di, DELIV):
        v = Xi[:, k]
        v = np.where(np.isfinite(v), v, np.nanmedian(v))
        rv = rankdata(v)
        ev = rv - Cr @ np.linalg.lstsq(Cr, rv, rcond=None)[0]
        rec[f"pxr|{f}"] = np.corrcoef(ev, ey)[0, 1]
    rows.append(rec)
t = pd.DataFrame(rows).set_index("d")
print("per-date done", round(time.time() - t0, 1), flush=True)
out = {}
for col in t.columns:
    kind, f = col.split("|")
    rec = {}
    for name, (a, b) in (("dev", L.DEV), ("hold", ("2026-01-01", "2100-01-01"))):
        sub = t[col][(t.index >= np.datetime64(a)) & (t.index <= np.datetime64(b))]
        x = sub.iloc[::H].dropna()
        rec[name] = float(sub.mean())
        rec[f"{name}_t"] = float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 3 else None
    yrs = pd.DatetimeIndex(t.index).year
    rec["by_year"] = {int(y): float(g.mean()) for y, g in t[col].groupby(yrs)}
    rec["group"] = FEAT_GROUP[f]
    out[col] = rec
save("s8_univariate", out)
top = sorted([(k, v["dev"], v["dev_t"], v["hold"]) for k, v in out.items() if k.startswith("xr|")],
             key=lambda z: -abs(z[1]))[:20]
for k, a, b, c in top:
    print(f"{k:22s} dev {a:+.4f} (t {b:+.2f}) hold {c:+.4f}")
for k, v in out.items():
    if k.startswith("pxr|") or k.split("|")[1] in DELIV:
        print(k, {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "by_year"})
print("total", round(time.time() - t0, 1))
