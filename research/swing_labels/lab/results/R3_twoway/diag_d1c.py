"""Diagnostic (not a variant): decompose the D1c/D1b 2026 hedge P&L by month — beta path, notional, hedge P&L —
and a fixed-beta counterfactual to measure the lagging-beta timing cost. Reported for attribution only."""
import sys
import numpy as np
import pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB); sys.path.insert(0, LAB + "/results/R3_twoway")
import r3common as C
from twsim import TwoWay, hedge_overlay
L = C.L
C.set_agent("R3_twoway")
P, F, fw, S, E = C.load_sim()
prod = C.load_prod()["prod"].astype("float64")
cal = pd.DatetimeIndex(S.cal)
lv = lambda n: L.market_series(n)["close"].reindex(cal).ffill()
cl1d = lv("Nifty 1D Rate Index").values
T = TwoWay(S, fw, cl1d)
z = np.load(f"{LAB}/results/R3_twoway/series_s3.npz", allow_pickle=True)
keys = list(z["keys"])
SER = {k: pd.Series(z[f"v{i}"], index=pd.DatetimeIndex(z[f"d{i}"])) for i, k in enumerate(keys)}
r1d = pd.Series(cl1d, index=cal).pct_change()
ms_fut = (1 + (lv("Nifty Midcap Select").pct_change() - (r1d - 0.0107 / 252)).fillna(0)).cumprod()
fut50 = lv("Nifty 50 Futures Index")
me = pd.Series(cal.to_period("M"), index=cal); me = (me != me.shift(-1)).values
out = {}
for per, (a, b) in (("hold", ("2026-01-01", None)), ("dev", C.DEV)):
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    for hn, lvl, bkey in (("D1c", ms_fut, "beta_msfut"), ("D1b", fut50, "beta_n50fut")):
        rows = []
        for mode in ("ex_ante", "fixed_mean"):
            phase = []
            for k in range(5):
                rr = T.run(prod, E, None, aL=1.0, start=str(S.cal[g0 + k]), end_exit=b)
                dts = pd.DatetimeIndex(rr["_dates"]); gi = np.searchsorted(S.cal, rr["_dates"])
                ex = rr["_expL"]; exn = np.r_[ex[1:], ex[-1]]
                bt = SER[bkey].reindex(dts).fillna(1.0).values
                if mode == "fixed_mean":
                    bt = np.full(len(dts), float(np.mean(bt)))
                fl = lvl.reindex(dts).values
                reset = np.zeros(len(dts), bool); reset[::5] = True
                hr, hnot, _ = hedge_overlay(rr["_daily"], dts, exn, fl, cl1d[gi], bt, reset, me[gi])
                fr = pd.Series(fl, index=dts).pct_change().fillna(0).values
                hp = -np.r_[0, hnot[:-1]] * fr                     # hedge P&L per unit NAV (approx)
                phase.append(pd.DataFrame({"h": hr, "b": rr["_daily"], "hp": hp, "n": hnot, "beta": bt}, index=dts))
            common = phase[0].index
            for x in phase[1:]:
                common = common.intersection(x.index)
            avg = sum(x.reindex(common) for x in phase) / 5
            rows.append((mode, avg))
        ea, fx = rows[0][1], rows[1][1]
        mon = pd.DataFrame({"base": (1 + ea.b).groupby(ea.index.to_period("M")).prod() - 1,
                            "hedged_ex_ante": (1 + ea.h).groupby(ea.index.to_period("M")).prod() - 1,
                            "hedged_fixed_beta": (1 + fx.h).groupby(fx.index.to_period("M")).prod() - 1,
                            "hedge_pnl_ex_ante": ea.hp.groupby(ea.index.to_period("M")).sum(),
                            "mean_notional": ea.n.groupby(ea.index.to_period("M")).mean(),
                            "mean_beta": ea.beta.groupby(ea.index.to_period("M")).mean()})
        out[f"{hn}|{per}"] = {"ann_mean_hedged_ex_ante": float(ea.h.mean() * 252), "ann_mean_hedged_fixed_beta": float(fx.h.mean() * 252),
                              "ann_mean_base": float(ea.b.mean() * 252), "ann_hedge_pnl_ex_ante": float(ea.hp.mean() * 252),
                              "ann_hedge_pnl_fixed_beta": float(fx.hp.mean() * 252), "fixed_beta_value": float(fx.beta.iloc[0]),
                              "corr_notional_vs_fut_ret": float(np.corrcoef(ea.n.shift(1).fillna(ea.n.iloc[0]).values,
                                                                             lvl.reindex(ea.index).pct_change().fillna(0).values)[0, 1]),
                              "monthly": {str(k): {c: float(v) for c, v in r.items()} for k, r in mon.iterrows()}}
        if per == "hold":
            print(hn, per, C.short({k: v for k, v in out[f"{hn}|{per}"].items() if k != "monthly"}))
            print(mon.round(4))
        else:
            print(hn, per, C.short({k: v for k, v in out[f"{hn}|{per}"].items() if k != "monthly"}))
C.save("diag_hedge_timing", out)
