#!/usr/bin/env python3
"""R3_scen stage 3: horizon economics.
  a. phase-averaged 5-seed random top-20 book (step 5, slot sizing, next-open entry) by h x cost x period
     + phase-averaged equal-weight universe book at 50 bps, + Nifty 500 price index (L.benchmark)
  b. overnight (close[t-1] -> open[t]) vs intraday (open[t] -> close[t]) split of the equal-weight
     elig_base universe (eligibility as of t-1), DEV and 2026, by liquidity tercile
  c. overnight tax by hold length: close-entry vs next-open-entry h-day return (date-weighted)."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_scen")
L = C.L
OUT = C.OUT
P, F, fw, S, E = C.load_sim(extra_feat=("log_turn20",))


def pa_series(fn_daily, h, period):
    a, b = C.PER[period]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    ser = []
    for k in range(5):
        kk = dict(top_k=20, step=5, start=str(S.cal[g0 + k]), end_exit=b)
        ser.append(fn_daily(kk))
    common = ser[0].index
    for x in ser[1:]:
        common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in ser], 0), index=common)


def stats(m):
    m = m.values
    eq = np.cumprod(1 + m)
    return {"cagr": float(eq[-1] ** (252 / len(m)) - 1), "sharpe": float(m.mean() / m.std() * np.sqrt(252)),
            "vol": float(m.std() * np.sqrt(252)), "maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()),
            "n_days": int(len(m))}


econ = {}
for h in (5, 10, 15, 20):
    for cost in (0, 50, 80):
        for per in ("dev", "hold"):
            def rnd(kk, cost=cost, h=h):
                kk = dict(kk, cost_bps=cost)
                summ, daily, dts = C.random_band(S, E, "liq2", h, kk)
                return pd.Series(daily[:len(dts)], index=pd.DatetimeIndex(dts))
            econ[f"random_h{h}_c{cost}_{per}"] = stats(pa_series(rnd, h, per))
            if cost == 50:
                def ew(kk, h=h):
                    kk = dict(kk, cost_bps=50)
                    summ, daily, dts = C.ew_band(S, E, "liq2", h, kk)
                    return pd.Series(daily[:len(dts)], index=pd.DatetimeIndex(dts))
                econ[f"ew_h{h}_c50_{per}"] = stats(pa_series(ew, h, per))
            C.log(h, cost, per, round(econ[f"random_h{h}_c{cost}_{per}"]["cagr"], 4))
econ["nifty500_price_dev"] = L.benchmark(P, start=C.DEV[0], end=C.DEV[1])
econ["nifty500_price_hold"] = L.benchmark(P, start="2026-01-01")
C.save("horizon_random_books", econ)

# ------------------------------------------------------------------ b. overnight vs intraday
o = P["open"].values.astype("float64")
c = P["close"].values.astype("float64")
LB = P["label_block"].values.astype(bool)
cprev = fw.at(c, -1)
eprev = fw.at(E.astype(float), -1) == 1
ok = eprev & np.isfinite(cprev) & (cprev > 0) & (o > 0) & ~LB
on = o / cprev - 1
intra = c / o - 1
cc1 = c / cprev - 1
dates = P["date"].values.astype("datetime64[D]")
cal = S.cal
didx = S.didx
ltp = fw.at(F["log_turn20"].values.astype("float64"), -1)
rk = pd.Series(np.where(ok & np.isfinite(ltp), ltp, np.nan)).groupby(didx).rank(pct=True).values
terc = np.where(np.isfinite(rk), np.minimum((rk * 3).astype(int), 2), -1)


def ew_daily(x, m):
    s = np.bincount(didx[m], weights=x[m], minlength=len(cal))
    k = np.bincount(didx[m], minlength=len(cal))
    out = pd.Series(np.where(k > 0, s / np.maximum(k, 1), np.nan), index=pd.DatetimeIndex(cal))
    return out


split = {}
daily = {}
for grp, gm in (("all", ok), ("liq_low", ok & (terc == 0)), ("liq_mid", ok & (terc == 1)), ("liq_high", ok & (terc == 2))):
    for nm, x in (("overnight", on), ("intraday", intra), ("close_to_close", cc1)):
        sr = ew_daily(x, gm)
        if grp == "all":
            daily[nm] = sr
        for per, (a, b) in (("dev", C.DEV), ("hold", ("2026-01-01", "2100-01-01"))):
            q = sr[(sr.index >= a) & (sr.index <= b)].dropna()
            split[f"{grp}_{nm}_{per}"] = {"ann_compounded": float(np.prod(1 + q.values) ** (252 / len(q)) - 1),
                                          "mean_daily_bps": float(q.mean() * 1e4), "share_days_pos": float((q > 0).mean()),
                                          "n_days": int(len(q))}
C.save("overnight_intraday_split", split)
dd = pd.DataFrame(daily)
dd = dd[(dd.index >= "2023-01-01")].dropna()
cum = (1 + dd).cumprod()
cm = cum.resample("ME").last()
np.savez(f"{OUT}/series_s3.npz", months=cm.index.strftime("%Y-%m").values.astype(str),
         overnight=cm["overnight"].values, intraday=cm["intraday"].values, cc=cm["close_to_close"].values)

# ------------------------------------------------------------------ c. overnight tax by hold length
tax = {}
g_dev0 = int(np.searchsorted(cal, np.datetime64("2023-01-01")))
g_dev_end = int(np.searchsorted(cal, np.datetime64("2025-12-31"), side="right")) - 1
g_hold0 = int(np.searchsorted(cal, np.datetime64("2026-01-01")))
for h in (5, 10, 15, 20):
    z = np.load(f"{OUT}/labels_h{h}.npz")
    r = z["r"].astype("float64")
    ccz = z["cc"].astype("float64")
    v = E & np.isfinite(r) & np.isfinite(ccz)
    gap = (1 + ccz) / (1 + r) - 1
    for per, pm in (("dev", (didx >= g_dev0) & (didx + h <= g_dev_end)), ("hold", didx >= g_hold0)):
        m = v & pm
        dcc = ew_daily(ccz, m).dropna()
        dr = ew_daily(r, m).dropna()
        dg = ew_daily(gap, m).dropna()
        mc_, mr_, mg_ = float(dcc.mean()), float(dr.mean()), float(dg.mean())
        tax[f"h{h}_{per}"] = {"mean_close_entry_ret": mc_, "mean_next_open_entry_ret": mr_,
                              "mean_overnight_gap_forfeited": mg_,
                              "fraction_of_close_entry_return_forfeited": (mc_ - mr_) / mc_ if mc_ != 0 else None,
                              "annual_overnight_drag_if_rolled_every_h_days": mg_ * 252 / h,
                              "annual_cost_drag_50bps_if_rolled_every_h_days": 0.005 * 252 / h,
                              "n_days": int(len(dr))}
    del z, r, ccz
C.save("overnight_tax_by_h", tax)
C.log("done", tax["h20_dev"], split["all_overnight_dev"], split["all_intraday_dev"])
