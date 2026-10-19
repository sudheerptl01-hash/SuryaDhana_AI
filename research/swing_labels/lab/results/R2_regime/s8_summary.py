"""Stage 8: compact candidate summary -> results.json['summary'] (numbers for the structured output)."""
import json
import numpy as np
import pandas as pd
from common import OUT, save, load_res

R = pd.read_pickle(f"{OUT}/gating_results.pkl")
res = load_res()
ev = res["s2_signal_eval"]
volt = pd.DataFrame(res["s6_voltarget"])


def g(book, w, sig, x, cost=50):
    s = R[(R.book == book) & (R.window == w) & (R.signal == sig) & (R.x_off == x) & (R.cost == cost)]
    return s.iloc[0]


out = {}
b = g("XR20", "DEV", "RBR", 0.0)
h = g("XR20", "HOLD", "RBR", 0.0)
b8 = g("XR20", "DEV", "RBR", 0.0, 80)
out["XR20_ALWAYS_IN"] = {"dev_cagr_50": b.pavg_base_cagr, "dev_cagr_80": b8.pavg_base_cagr, "dev_maxdd": b.pavg_base_max_dd,
                         "dev_random_cagr_50": b.pavg_base_cagr - b.pavg_base_excess_vs_rnd, "dev_excess_nw_t": b.pavg_base_excess_nw_t,
                         "holdout_cagr_50": h.pavg_base_cagr, "holdout_random_cagr_50": h.pavg_base_cagr - h.pavg_base_excess_vs_rnd,
                         "holdout_excess_nw_t": h.pavg_base_excess_nw_t, "dev_sharpe_xs": b.pavg_base_sharpe_xs,
                         "holdout_sharpe_xs": h.pavg_base_sharpe_xs, "holdout_maxdd": h.pavg_base_max_dd}
for sig, x in (("RBR", 0.0), ("RBR", 0.5), ("RM60", 0.0), ("R200", 0.0), ("RVIX", 0.0), ("VOTE", 0.0), ("LGB10_E0", 0.0), ("LOG4_N0", 0.0)):
    d, d8, hh = g("XR20", "DEV", sig, x), g("XR20", "DEV", sig, x, 80), g("XR20", "HOLD", sig, x)
    e, eh = g("EW", "DEV", sig, x), g("EW", "HOLD", sig, x)
    rec = {"dev_cagr_50": d.pavg_cagr, "dev_cagr_80": d8.pavg_cagr, "dev_maxdd": d.pavg_max_dd,
           "dev_random_cagr_50": d.pavg_rnd_cagr_gated, "dev_excess_nw_t": d.pavg_excess_nw_t_vs_rnd_gated,
           "holdout_cagr_50": hh.pavg_cagr, "holdout_random_cagr_50": hh.pavg_rnd_cagr_gated,
           "holdout_excess_nw_t": hh.pavg_excess_nw_t_vs_rnd_gated,
           "xr_dev_d_cagr": d.pavg_d_cagr, "xr_dev_d_sharpe_xs": d.pavg_d_sharpe_xs, "xr_dev_d_maxdd": d.pavg_d_maxdd,
           "xr_hold_d_cagr": hh.pavg_d_cagr, "xr_hold_d_sharpe_xs": hh.pavg_d_sharpe_xs, "xr_hold_d_maxdd": hh.pavg_d_maxdd,
           "ew_dev_d_cagr": e.pavg_d_cagr, "ew_dev_d_sharpe_xs": e.pavg_d_sharpe_xs, "ew_dev_d_maxdd": e.pavg_d_maxdd,
           "ew_hold_d_cagr": eh.pavg_d_cagr, "ew_hold_d_sharpe_xs": eh.pavg_d_sharpe_xs, "ew_hold_d_maxdd": eh.pavg_d_maxdd,
           "dev_on_share": ev[sig]["DEV"]["on_share"], "hold_on_share": ev[sig]["HOLD"]["on_share"],
           "dev_auc_E0": ev[sig]["DEV"]["auc_E0"], "hold_auc_E0": ev[sig]["HOLD"]["auc_E0"],
           "dev_auc_N0": ev[sig]["DEV"]["auc_N0"], "hold_auc_N0": ev[sig]["HOLD"]["auc_N0"],
           "switches_per_yr_dev": d.pavg_switches_per_yr}
    if "PRE" in ev[sig]:
        p_ = g("EW", "PRE", sig, x)
        rec.update({"ew_pre_d_cagr": p_.pavg_d_cagr, "ew_pre_d_sharpe_xs": p_.pavg_d_sharpe_xs, "pre_on_share": ev[sig]["PRE"]["on_share"],
                    "pre_auc_E0": ev[sig]["PRE"]["auc_E0"]})
    out[f"GATE_{sig}_x{int(x * 100)}"] = rec
v = volt
out["VOLT"] = {k: float(v[(v.book == bk) & (v.window == w) & (v.cost == c)][col].iloc[0])
               for k, (bk, w, c, col) in {"xr_dev_cagr_50": ("XR20", "DEV", 50, "cagr"), "xr_dev_cagr_80": ("XR20", "DEV", 80, "cagr"),
                                          "xr_dev_maxdd": ("XR20", "DEV", 50, "max_dd"), "xr_hold_cagr_50": ("XR20", "HOLD", 50, "cagr"),
                                          "ew_dev_sharpe_xs": ("EW", "DEV", 50, "sharpe_xs"), "ew_dev_base_sharpe_xs": ("EW", "DEV", 50, "base_sharpe_xs"),
                                          "ew_hold_sharpe_xs": ("EW", "HOLD", 50, "sharpe_xs"), "ew_hold_base_sharpe_xs": ("EW", "HOLD", 50, "base_sharpe_xs"),
                                          "ew_dev_null_p": ("EW", "DEV", 50, "null_p_sharpe_xs")}.items()}
out["headline"] = ("Market timing does not reliably help net of whipsaw: no PIT regime signal predicts the next-20d market "
                   "consistently; the DEV-best gate (breadth50>0.5) is a one-episode, non-significant win that lost in "
                   "2021-22 and only broke even vs always-in in 2026; the relative edge is regime-independent, so the "
                   "regime layer should be a fixed exposure policy, not a timer.")
save("summary", out)
print(json.dumps(out, indent=1, default=float)[:6000])
