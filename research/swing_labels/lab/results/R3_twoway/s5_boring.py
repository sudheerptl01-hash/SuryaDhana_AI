"""Stage 5 (extra variants B1/B2, declared in 'predeclared_amendment' before running): is the avoid veto (D0) just a
factor tilt? B1 = EW minus the top-30% vol_20 names; B2 = EW minus the top-30% beta_60 names (same engine, step 5,
equal weight, phase-averaged). Regress D0's daily excess vs EW on B1's/B2's excess vs EW -> residual alpha + NW t."""
import sys, time
import numpy as np
import pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C
L = C.L
C.set_agent("R3_twoway")
C.save("predeclared_amendment", {
    "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "note": "Written before running B1/B2. After seeing that the F&O bottom-20 short picks are high-vol (xs pct 0.76) and "
            "high-beta (0.64), test whether the avoid veto D0 is a boring low-vol/low-beta tilt. B1/B2 are diagnostic "
            "baselines (not adoption candidates) but are counted as extra variants (X1 + B1 + B2 = 3, the maximum).",
    "B1": "EW elig_base minus top-30% vol_20 (score = -vol_20, select_quantile=(0.3,1), sizing equal, step 5, 50/80 bps)",
    "B2": "EW elig_base minus top-30% beta_60 (score = -beta_60, same settings)",
    "test": "OLS of daily (D0 - EW) on (B - EW) with intercept; NW t (lag 20) of the intercept (residual avoid alpha)"})
P, F, fw, S, E = C.load_sim(extra_feat=("vol_20", "beta_60"))
prod = C.load_prod()["prod"].astype("float64")
sc = {"B1_volveto": -F["vol_20"].values.astype("float64"), "B2_betaveto": -F["beta_60"].values.astype("float64")}
out = {}
for cost in (50, 80):
    kw0 = dict(step=5, cost_bps=cost, select_quantile=(0.3, 1.0), sizing="equal")
    for per in ("dev", "hold"):
        r0, d0, _, ew = C.phase_avg(S, prod, E, "liq2", 20, kw0, per, with_ew=True)
        res = {"D0": {"pa_cagr": r0["pa_cagr"], "pa_excess_vs_ew_ann": r0["pa_excess_vs_ew_ann"], "pa_vs_ew_nw_t": r0["pa_vs_ew_nw_t"]}}
        for nm, s in sc.items():
            rb, sb, _, ewb = C.phase_avg(S, s, E, "liq2", 20, kw0, per, with_ew=True)
            c = d0.index.intersection(sb.index)
            y = (d0 - ew).reindex(c).values
            x = (sb - ewb).reindex(c).values
            X = np.c_[np.ones(len(c)), x]
            coef = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ coef
            res[nm] = {"pa_cagr": rb["pa_cagr"], "pa_excess_vs_ew_ann": rb["pa_excess_vs_ew_ann"], "pa_vs_ew_nw_t": rb["pa_vs_ew_nw_t"],
                       "pa_maxdd": rb["pa_maxdd"], "corr_excess_with_D0": float(np.corrcoef(x, y)[0, 1]),
                       "D0_on_B_slope": float(coef[1]), "D0_residual_alpha_ann": float((coef[0] + resid.mean()) * 252),
                       "D0_residual_alpha_nw_t": L.nw_t(coef[0] + resid, 20)}
        out[f"{per}|c{cost}"] = res
        C.log(per, cost, C.short(res))
C.save("s5_boring_avoid", out)
