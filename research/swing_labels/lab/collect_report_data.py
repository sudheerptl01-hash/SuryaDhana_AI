#!/usr/bin/env python3
"""Collect chart/table data for the swing-label report from saved lab results (rounds 1-3).
Light: reads JSON/NPZ outputs and index.parquet only; never rebuilds the panel."""
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

OUT = os.path.join(LAB, "results", "_lead", "report_data.json")
R = lambda *p: os.path.join(LAB, "results", *p)  # noqa: E731
D = {}

atlas = json.load(open(R("_lead", "atlas_v2.json")))

# --- Nifty 500: forward 20-session return from each session (open t+1 -> close t+20), monthly mean
n5 = L.market_series("Nifty 500").astype("float64")
cal = n5.index
fwd = {}
for h in (5, 10, 15, 20):
    o1 = n5["open"].shift(-1)
    ch = n5["close"].shift(-h)
    fwd[h] = (ch / o1 - 1)
mon = cal.to_period("M").astype(str)
mk_fwd20_m = fwd[20].groupby(mon).mean()
mk_month_ret = n5["close"].resample("ME").last().pct_change()
mk_month_ret.index = mk_month_ret.index.to_period("M").astype(str)

# --- bias chart: monthly +1 share of absolute vs relative labels (h=20), with the market move
def mseries(key):
    return pd.Series(atlas[key]["monthly_series"])

abs20 = mseries("clean_sign_h20")
bar20 = mseries("barrier_3.0_1.5_h20")
rel20 = mseries("relative_rank_30_40_30_h20")
old20 = mseries("old_repo_label_h20")
months = [m for m in abs20.index if m in mk_fwd20_m.index and m >= "2021-06" and m <= "2026-09"]
D["bias_monthly"] = {
    "months": months,
    "abs_sign_h20": [round(float(abs20[m]), 4) for m in months],
    "barrier_h20": [round(float(bar20.get(m, np.nan)), 4) for m in months],
    "relative_h20": [round(float(rel20.get(m, np.nan)), 4) for m in months],
    "old_repo_h20": [round(float(old20.get(m, np.nan)), 4) for m in months],
    "mkt_fwd20_mean": [round(float(mk_fwd20_m[m]), 4) for m in months],
}

# --- event-rate stability table by label family x horizon
fam = [("old_repo_label", "Repo's current label (close to close > 0, raw prices, NaN as 0)"),
       ("clean_sign", "Clean direction label (next open to close > 0)"),
       ("cost_aware_3class", "Cost-aware 3-class (beyond +/-50 bps)"),
       ("barrier_2.0_2.0", "Triple barrier, 2.0/2.0 ATR"),
       ("barrier_3.0_1.5", "Triple barrier, 3.0/1.5 ATR"),
       ("relative_rank_30_40_30", "Relative rank 30/40/30")]
rows = []
for k, name in fam:
    for h in (5, 10, 15, 20):
        a = atlas[f"{k}_h{h}"]
        pos = "1.0"
        ov = a["overall"]
        rows.append({"family": k, "name": name, "h": h,
                     "up": ov.get(pos), "flat": ov.get("0.0") if k != "old_repo_label" and k != "clean_sign" else None,
                     "down": ov.get("-1.0") if "-1.0" in ov else ov.get("0.0"),
                     "m_mean": a["monthly_pos"]["mean"], "m_sd": a["monthly_pos"]["std"],
                     "m_min": a["monthly_pos"]["min"], "m_max": a["monthly_pos"]["max"],
                     "corr_m": a["corr_monthly_pos_vs_mkt"], "by_year": a["by_year"],
                     "bull": a["by_regime"].get("bull"), "bear": a["by_regime"].get("bear")})
D["event_rate_table"] = rows
D["exec_vs_close_entry"] = {h: atlas[f"exec_return_h{h}"] for h in (5, 10, 15, 20)}

# --- random-book cost curve by horizon (DEV and 2026)
cc = atlas["random_cost_curve"]
D["cost_curve"] = {f"h{h}": {f"c{c}": {"dev": cc[f"h{h}_c{c}_dev"]["cagr"], "hold": cc[f"h{h}_c{c}_holdout"]["cagr"]}
                             for c in (0, 50, 80)} for h in (5, 10, 15, 20)}
D["nifty500"] = {"dev": atlas["nifty500_dev"], "hold": atlas["nifty500_holdout"]}

# --- index annual returns (context)
yr = n5["close"].groupby(cal.year).agg(["first", "last"])
D["n500_by_year"] = {int(y): float(r["last"] / r["first"] - 1) for y, r in yr.iterrows()}

# --- devil robustness series
dv = json.load(open(R("_lead", "round2_results.json")))["devil"]
D["devil_text"] = {k: dv[k] for k in ("verdict", "final_recommendation")}

# --- round-3 outputs (if present): copy html_tables and charts verbatim
for agent in ("R3_book", "R3_twoway", "R3_scen", "R3_risk", "R3_exam"):
    fn = R(agent, "results.json")
    if os.path.exists(fn):
        res = json.load(open(fn))
        D[agent] = {"html_tables": res.get("html_tables"), "charts": res.get("charts")}

json.dump(D, open(OUT, "w"), default=float)
print("wrote", OUT, os.path.getsize(OUT), "bytes; keys", list(D.keys()))
print("bias months", len(months), months[0], months[-1])
print("abs range", min(D["bias_monthly"]["abs_sign_h20"]), max(D["bias_monthly"]["abs_sign_h20"]))
print("corr abs vs mkt fwd20 monthly", np.corrcoef(D["bias_monthly"]["abs_sign_h20"], D["bias_monthly"]["mkt_fwd20_mean"])[0, 1])
print("corr rel vs mkt fwd20 monthly", np.corrcoef(D["bias_monthly"]["relative_h20"], D["bias_monthly"]["mkt_fwd20_mean"])[0, 1])
print("n500 by year", D["n500_by_year"])
