"""Validate BookSim (E0 settings) bit-exact against L.Sim.run: PROD on all 5 phases DEV and 2026, random seeds
1-5 on phase 0 DEV and 2026; plus the per-row-cost path and the weighted-sum (fill=1) path."""
import numpy as np

from bk_setup import setup, C

T = setup()
S, E, BS, prod = T["S"], T["E"], T["BS"], T["prod"]
val = {}
worst = 0.0
for per in ("dev", "hold"):
    a, b = C.PER[per]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    for k in range(5):
        st = str(S.cal[g0 + k])
        r1 = BS.run(prod, E, start=st, end_exit=b)
        r2 = S.run(prod, E, 20, top_k=20, step=5, cost_bps=50, start=st, end_exit=b)
        dmax = float(np.abs(r1["_daily"] - r2["_daily_ret"]).max())
        val[f"PROD_{per}_phase{k}"] = {"max_abs_daily_diff": dmax, "cagr_booksim": r1["cagr"], "cagr_lablib": r2["cagr"],
                                       "mean_trade_booksim": r1["mean_trade_net"], "mean_trade_lablib": r2["mean_trade_net"]}
        worst = max(worst, dmax)
    for s_ in (1, 2, 3, 4, 5):
        r1 = BS.run(None, E, start=a, end_exit=b, random_seed=s_)
        r2 = S.run(None, E, 20, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, random_seed=s_)
        dmax = float(np.abs(r1["_daily"] - r2["_daily_ret"]).max())
        val[f"random_s{s_}_{per}_phase0"] = {"max_abs_daily_diff": dmax}
        worst = max(worst, dmax)
    # per-row cost path at a flat 50 bps and weighted-sum path (fill = 1)
    r1 = BS.run(prod, E, start=a, end_exit=b, cost_row=np.full(S.n, 0.005))
    r3 = BS.run(prod, E, start=a, end_exit=b, fill=np.ones(S.n))
    r2 = S.run(prod, E, 20, top_k=20, step=5, cost_bps=50, start=a, end_exit=b)
    val[f"costrow_{per}"] = float(np.abs(r1["_daily"] - r2["_daily_ret"]).max())
    val[f"fill1_{per}"] = float(np.abs(r3["_daily"] - r2["_daily_ret"]).max())
    # 80 bps
    r1 = BS.run(prod, E, start=a, end_exit=b, cost_bps=80)
    r2 = S.run(prod, E, 20, top_k=20, step=5, cost_bps=80, start=a, end_exit=b)
    val[f"c80_{per}"] = float(np.abs(r1["_daily"] - r2["_daily_ret"]).max())
val["worst_max_abs_daily_diff_E0_vs_lablib"] = worst
C.log("validation worst", worst, {k: v for k, v in val.items() if not isinstance(v, dict)})
assert worst < 1e-12, worst
C.set_agent("R3_book")
C.save("booksim_validation", val)
