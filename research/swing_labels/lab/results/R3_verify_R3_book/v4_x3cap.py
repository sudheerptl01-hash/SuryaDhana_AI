"""Verifier check 4 (own code): capacity curve of the RECOMMENDED X3 execution (same impact model, Y=1, liq2,
uncapped and 5% cap) and Nifty 500 crossings vs the price index and vs an approximate total-return index (+1.2%/yr)."""
import json, sys, time
import numpy as np, pandas as pd
VD = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab/results/R3_verify_R3_book"
sys.path.insert(0, VD)
from vsim import LAB, L, Data, phase_series, pavg, cagr
T0 = time.time()
D = Data(extra_panel=("turnover",), extra_feat=("vol_20",))
E = D.E
prod = np.load(f"{LAB}/results/_lead/prod_h20.npz")["prod"].astype(float)
cal = pd.DatetimeIndex(D.cal)
lv1 = L.market_series("Nifty 1D Rate Index")["close"].astype(float); lv1.index = pd.DatetimeIndex(lv1.index)
cash_lv = lv1.reindex(lv1.index.union(cal)).ffill().bfill().reindex(cal).values
adv = pd.Series(D.P["turnover"].values.astype(float)).groupby(D.segid).rolling(20, min_periods=1).median() \
    .reset_index(level=0, drop=True).sort_index().values
vol = D.F["vol_20"].values.astype(float)
v2 = json.load(open(f"{VD}/v2_checks.json"))
AUM = {"1cr": 1e7, "5cr": 5e7, "20cr": 2e8, "50cr": 5e8, "100cr": 1e9}
res = {"X3_uncapped": {}, "X3_cap5": {}}
for an, A in AUM.items():
    Q = A / 80.0
    imp = np.minimum(vol * np.sqrt(Q / adv), 0.10); imp = np.where(np.isfinite(imp), imp, 0.10)
    s = pavg(phase_series(D, "2023-01-01", "2025-12-31", score=prod, mode="X3", cost_rt=0.005 + 2 * imp, cash_lv=cash_lv)[0])
    res["X3_uncapped"][f"{an}_dev"] = {"cagr": cagr(s.values)}
    fill = np.minimum(1.0, 0.05 * adv / Q); fill = np.where(np.isfinite(fill), fill, 0.0)
    imp2 = np.minimum(vol * np.sqrt(Q * fill / adv), 0.10); imp2 = np.where(np.isfinite(imp2), imp2, 0.10)
    s2 = pavg(phase_series(D, "2023-01-01", "2025-12-31", score=prod, mode="X3", cost_rt=0.005 + 2 * imp2, cash_lv=cash_lv, fill=fill)[0])
    res["X3_cap5"][f"{an}_dev"] = {"cagr": cagr(s2.values)}
    print(f"[{time.time()-T0:6.1f}s]", an, res["X3_uncapped"][f"{an}_dev"], res["X3_cap5"][f"{an}_dev"], flush=True)

def crossing(tbl, target, tiers):
    xs = np.log10([AUM[t] / 1e7 for t in tiers]); ys = np.array([tbl[f"{t}_dev"]["cagr"] for t in tiers])
    if ys[0] <= target: return "below_first"
    for i in range(len(ys) - 1):
        if ys[i] > target >= ys[i + 1]:
            f = (ys[i] - target) / (ys[i] - ys[i + 1]); return float(10 ** (xs[i] + f * (xs[i + 1] - xs[i])))
    return "above_last"
n5p = v2["capacity"]["refs"]["dev"]["nifty500_cagr_own"]; ew = v2["capacity"]["refs"]["dev"]["ew_cagr_own"]
n5tr = (1 + n5p) * 1.012 - 1
e0u = v2["capacity"]["a_liq2_Y1"]
e0c = {k: v for k, v in v2["capacity"]["b_liq2_cap5_Y1"].items()}
out = {"targets": {"nifty500_price": n5p, "nifty500_TR_approx_plus1.2pct": n5tr, "ew": ew}, "x3_curves": res,
       "crossings": {
           "E0_uncapped_vs_N500price": crossing(e0u, n5p, list(AUM)), "E0_uncapped_vs_N500TR": crossing(e0u, n5tr, list(AUM)),
           "E0_cap5_vs_N500TR_(tiers 20/50/100 only)": crossing(e0c, n5tr, ["20cr", "50cr", "100cr"]),
           "E0_uncapped_vs_EW": crossing(e0u, ew, list(AUM)),
           "X3_uncapped_vs_N500price": crossing(res["X3_uncapped"], n5p, list(AUM)),
           "X3_uncapped_vs_N500TR": crossing(res["X3_uncapped"], n5tr, list(AUM)),
           "X3_cap5_vs_N500price": crossing(res["X3_cap5"], n5p, list(AUM)),
           "X3_cap5_vs_N500TR": crossing(res["X3_cap5"], n5tr, list(AUM)),
           "X3_uncapped_vs_EW": crossing(res["X3_uncapped"], ew, list(AUM))}}
# E0 cap5 between 5cr and 20cr needs the 5cr cap5 point: cap5 at 5cr == uncapped at 5cr up to fills (fill<1 for 0.15% of picks)
e0c2 = dict(e0c); e0c2["5cr_dev"] = e0u["5cr_dev"]; e0c2["1cr_dev"] = e0u["1cr_dev"]
out["crossings"]["E0_cap5_vs_N500TR_(5cr point = uncapped)"] = crossing(e0c2, n5tr, list(AUM))
print(json.dumps(out, indent=1, default=float))
json.dump(out, open(f"{VD}/v4_x3cap.json", "w"), indent=1, default=float)
