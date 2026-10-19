"""Stage 2: validate TwoWay against L.Sim.run (long-only and short-only, PROD and random picks, DEV and 2026)."""
import sys, time
import numpy as np
import pandas as pd
sys.path.insert(0, "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab")
sys.path.insert(0, "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab/results/R3_twoway")
import r3common as C
from twsim import TwoWay
L = C.L
C.set_agent("R3_twoway")
P, F, fw, S, E = C.load_sim(extra_feat=("fno_proxy",))
fno = F["fno_proxy"].values.astype(bool) & E
prod = C.load_prod()["prod"].astype("float64")
cl = L.market_series("Nifty 1D Rate Index")["close"].reindex(pd.DatetimeIndex(S.cal)).ffill().values
T = TwoWay(S, fw, cl)
out = {}
for per, (a, b) in C.PER.items():
    t0 = time.time()
    v1 = T.run(prod, E, None, aL=1.0, aS=0.0, cL=0.005, start=a, end_exit=b)
    t1 = time.time() - t0
    v2 = S.run(prod, E, 20, top_k=20, step=5, cost_bps=50, start=a, end_exit=b)
    out[f"long_prod_{per}"] = {"max_abs_daily_diff": float(np.abs(v1["_daily"] - v2["_daily_ret"]).max()),
                               "cagr_tw": v1["cagr"], "cagr_lablib": v2["cagr"], "secs_tw": t1}
    v1 = T.run(None, E, None, aL=1.0, cL=0.005, start=a, end_exit=b, seedL=3)
    v2 = S.run(None, E, 20, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, random_seed=3)
    out[f"long_random3_{per}"] = {"max_abs_daily_diff": float(np.abs(v1["_daily"] - v2["_daily_ret"]).max())}
    v1 = T.run(prod, None, fno, aL=0.0, aS=1.0, kS=20, cS=0.0025, start=a, end_exit=b, carry=False, cash="zero")
    v2 = S.run(prod, fno, 20, top_k=20, step=5, cost_bps=25, side="short", start=a, end_exit=b)
    out[f"short_prod_fno_{per}"] = {"max_abs_daily_diff": float(np.abs(v1["_daily"] - v2["_daily_ret"]).max()),
                                    "cagr_tw": v1["cagr"], "cagr_lablib": v2["cagr"]}
    v1 = T.run(None, None, fno, aL=0.0, aS=1.0, kS=20, cS=0.0025, start=a, end_exit=b, carry=False, cash="zero", seedS=2)
    v2 = S.run(None, fno, 20, top_k=20, step=5, cost_bps=25, side="short", start=a, end_exit=b, random_seed=2)
    out[f"short_random2_fno_{per}"] = {"max_abs_daily_diff": float(np.abs(v1["_daily"] - v2["_daily_ret"]).max())}
    C.log(per, C.short(out[f"long_prod_{per}"]), C.short(out[f"short_prod_fno_{per}"], 6))
out["worst"] = max(v["max_abs_daily_diff"] for v in out.values())
C.log("worst max abs daily diff", out["worst"])
assert out["worst"] < 1e-12
C.save("s2_engine_validation", out)
