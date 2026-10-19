"""Verifier v5 (own code): D1c hedge with synthetic Midcap Select futures (price - (1D rate - 1.07%/yr)), own ex-ante
beta and own overlay; plus random F&O short (own seeds) vs cash, from v3 series."""
import json
import sys
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_twoway"
sys.path.insert(0, LAB)
sys.path.insert(0, OUT)
import lablib as L  # noqa: E402
from vbook import VBook, hedge  # noqa: E402


def my_nw_t(x, lag=20):
    x = np.asarray(x, float)
    n = len(x)
    u = x - x.mean()
    s = u @ u / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (u[k:] @ u[:-k]) / n
    return x.mean() / np.sqrt(s / n)


P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base"])
fw = L.Fwd(P)
E = F["elig_base"].values.astype(bool)
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz", allow_pickle=True)["prod"].astype("float64")
d = P["date"].values.astype("datetime64[D]")
cal = np.unique(d)
calI = pd.DatetimeIndex(cal)
lv = lambda nm: L.market_series(nm)["close"].astype(float).reindex(calI).ffill()  # noqa: E731
cl = lv("Nifty 1D Rate Index").values
r1 = pd.Series(cl, index=calI).pct_change()
msf = (1 + (lv("Nifty Midcap Select").pct_change() - (r1 - 0.0107 / 252)).fillna(0)).cumprod().values
VB = VBook(P["open"].values.astype(float), P["close"].values.astype(float), np.searchsorted(cal, d), fw.end, fw.lb_cs, cal, cl)
del P
legs = [dict(score=prod, mask=E, k=20, side="long", mode="cash", a=1.0, c=0.005)]


def pavg(lst):
    c = lst[0].index
    for x in lst[1:]:
        c = c.intersection(x.index)
    return pd.Series(np.mean([x.reindex(c).values for x in lst], 0), index=c)


books = {}
for per, (a, b) in {"dev": ("2023-01-01", "2025-12-31"), "2026": ("2026-01-01", None), "contig": ("2023-01-01", None)}.items():
    g0 = int(np.searchsorted(cal, np.datetime64(a)))
    books[per] = [VB.run(str(cal[g0 + k]), b, legs, record=True) for k in range(5)]
base_c = pavg([pd.Series(x["r"], index=pd.DatetimeIndex(x["dates"])) for x in books["contig"]])
xr = pd.Series(msf, index=calI).pct_change().reindex(base_c.index)
y = base_c.copy()
y.iloc[:20] = np.nan
beta = (y.shift(1).rolling(60, min_periods=40).cov(xr.shift(1)) / xr.shift(1).rolling(60, min_periods=40).var()).clip(0, 2).fillna(1.0)
me = pd.Series(calI.to_period("M"), index=calI)
me = (me != me.shift(-1)).values
out = {"beta_ms_mean_dev": float(beta.loc["2023-03-01":"2025-12-31"].mean()), "beta_ms_mean_2026": float(beta.loc["2026-01-01":].mean())}
for per in ("dev", "2026"):
    hs, bs = [], []
    for rr in books[per]:
        gi = rr["g_idx"]
        dts = pd.DatetimeIndex(rr["dates"])
        reset = np.zeros(len(gi), bool)
        reset[::5] = True
        hr, _ = hedge(rr["r"], rr["plan"], msf[gi], cl[gi], beta.reindex(dts).fillna(1.0).values, reset, me[gi])
        hs.append(pd.Series(hr, index=dts))
        bs.append(pd.Series(rr["r"], index=dts))
    h, bse = pavg(hs), pavg(bs)
    x = (h - bse).values
    eq = np.cumprod(1 + h.values)
    out[f"D1c|{per}"] = {"cagr": float(eq[-1] ** (252 / len(h)) - 1), "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
                         "vs_base_ann": float(x.mean() * 252), "vs_base_t": float(my_nw_t(x))}
# random F&O short vs cash from v3 series
z = np.load(OUT + "/v3_series.npz", allow_pickle=True)
SER = {k: pd.Series(z[f"v{i}"], index=pd.DatetimeIndex(z[f"d{i}"])) for i, k in enumerate(z["keys"])}
for per in ("dev", "2026"):
    s = SER[f"R_D4|{per}|signal"]
    rc = pd.Series(cl, index=calI).pct_change().reindex(s.index).values
    x = s.values - rc
    out[f"R_D4_vs_cash|{per}"] = {"diff_ann": float(x.mean() * 252), "nw_t": float(my_nw_t(x))}
print(json.dumps(out, indent=1))
json.dump(out, open(OUT + "/v5_d1c.json", "w"), indent=1)
