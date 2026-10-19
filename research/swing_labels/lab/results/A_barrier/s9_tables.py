"""Generate markdown tables from saved results (grid, events, wf, invest) -> tables_autogen.md"""
import glob
import json
import os

import numpy as np
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
G = pd.read_csv(f"{OUT}/grid.csv")
G["cfg"] = np.where(G.kind == "fix", "fix " + G.a.astype(str) + "/" + G.b.astype(str) + " ATR",
                    "sqrt " + G.a.astype(str) + "/" + G.b.astype(str) + " ATR*sqrt(h)")
lines = []


def pct(x, d=1):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.{d}f}"


def md(df):
    cols = list(df.columns)
    s = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    for _, r in df.iterrows():
        s += "| " + " | ".join(str(r[c]) for c in cols) + " |\n"
    return s


# --- Table 1: geometry outcome table (long), all h
for side in ("long", "short"):
    t = G[G.side == side].copy()
    o = pd.DataFrame({
        "h": t.h, "geometry": t.cfg, "med tgt %": (t.med_pt_pct * 100).round(1), "med stop %": (t.med_sl_pct * 100).round(1),
        "P(target)": t.sh_pt.map(pct), "P(stop)": t.sh_sl.map(pct), "P(time)": t.sh_time.map(pct),
        "med bars tgt": t.medk_pt, "med bars stop": t.medk_sl, "mean bars": t.meank_all.round(1),
        "net|+1 (50bp)": t.net_p1_t50.map(pct), "net|-1": t.net_m1_t50.map(pct), "net|0": t.net_z_t50.map(pct),
        "uncond net 23-25": t.net_all_sel.map(lambda x: pct(x, 2)), "uncond net 2026": t.net_all_2026.map(lambda x: pct(x, 2)),
    })
    lines.append(f"\n### Geometry outcomes, {side} side (elig_base, all years, tau=50 for class nets)\n\n" + md(o))

# --- Table 2: event-rate surface P(+1)/P(-1)/P(0) per tau
for side in ("long", "short"):
    t = G[G.side == side].copy()
    o = pd.DataFrame({"h": t.h, "geometry": t.cfg})
    for tau in (0, 50, 100):
        o[f"tau{tau} +1/-1/0"] = [f"{pct(a)}/{pct(b)}/{pct(c)}" for a, b, c in zip(t[f"p1_t{tau}"], t[f"m1_t{tau}"], t[f"z_t{tau}"])]
    o["touch-only +1 (=P(tgt))"] = t.sh_pt.map(pct)
    o["coh +1 tau0"] = t.coh_p1_t0.map(pct)
    lines.append(f"\n### Event-rate surface, {side} (P(+1)/P(-1)/P(0) %, by time-barrier dead zone tau bps)\n\n" + md(o))

# --- Table 3: regime dependence + by-year (tau=50), long
for side in ("long", "short"):
    t = G[G.side == side].copy()
    o = pd.DataFrame({"h": t.h, "geometry": t.cfg})
    for y in range(2021, 2027):
        o[str(y)] = t[f"p1_t50_{y}"].map(pct)
    o["mon mean"] = t.mon_mean_t50.map(pct)
    o["mon std"] = t.mon_std_t50.map(pct)
    o["mon min-max"] = [f"{pct(a)}-{pct(b)}" for a, b in zip(t.mon_min_t50, t.mon_max_t50)]
    o["corr mon vs mkt"] = t.mon_corr_mkt_t50.round(2)
    for r in ("bull_up20", "bull_dn20", "bear_up20", "bear_dn20"):
        o[r] = t[f"p1_t50_{r}"].map(pct)
    lines.append(f"\n### P(+1) by year / month / regime, {side} (tau=50)\n\n" + md(o))

with open(f"{OUT}/tables_autogen.md", "w") as fh:
    fh.write("\n".join(lines))
print("ok", len(lines))


# ------------------------------------------------------------------ learnability + investability
def f4(x, d=3):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


inv_files = sorted(glob.glob(f"{OUT}/invest_*.json"))
cmp = json.load(open(f"{OUT}/compare_learnability.json")) if os.path.exists(f"{OUT}/compare_learnability.json") else {}
rows = []
for p in inv_files:
    d = json.load(open(p))
    tag = d["tag"]
    wf = json.load(open(f"{OUT}/wf_{tag}.json"))
    folds = {f["year"]: f for f in wf["folds"]}
    for y, o in d["diag"].items():
        y = int(y)
        c = cmp.get(tag, {}).get(str(y), {})
        rows.append({"label/model": tag.replace("_2023-2024-2025-2026", ""), "year": y,
                     "pooled AUC(+1)": f4(folds[y].get("auc_up")),
                     "AUC(-1) inv": f4(folds[y].get("auc_down_inverted")),
                     "xs-AUC own label": f4(o["xs_auc_mean"]), "timing AUC (date-mean)": f4(o["timing_auc_datemean_only"]),
                     "base P(+1)": pct(o["base_pos"]), "top10 P(+1)": pct(o["top10_pos"]), "bot10 P(+1)": pct(o["bot10_pos"]),
                     "top10 net": pct(o["top10_net50"], 2), "all net": pct(o["all_net50"], 2), "bot10 net": pct(o["bot10_net50"], 2),
                     "IC vs 20d ret": f4(c.get("ic20")), "t(IC20) non-ovl": f4(c.get("ic20_t_nonoverlap"), 2),
                     "top10-all 20d ret": pct(c.get("top10_minus_all_r20"), 2),
                     "xs-AUC vs B20sym": f4(c.get("xs_auc_vs_B20sym"))})
if rows:
    lines.append("\n### Walk-forward learnability (OOS, per test year; 2026 = holdout)\n\n" + md(pd.DataFrame(rows)))


def inv_row(name, v, rnd=None):
    s1 = v.get("sel_2023_25") or {}
    s2 = v.get("hold_2026") or {}
    by = v["by_year"]
    r = {"strategy": name, "CAGR": pct(v["cagr"]), "Sharpe": f4(v["sharpe"], 2), "maxDD": pct(v["max_dd"]),
         "hit": pct(v.get("hit_rate")), "mean trade": pct(v.get("mean_trade_net"), 2),
         "2023": pct(by.get("2023", by.get(2023))), "2024": pct(by.get("2024", by.get(2024))),
         "2025": pct(by.get("2025", by.get(2025))), "2026 YTD (holdout)": pct(by.get("2026", by.get(2026))),
         "sel 23-25 CAGR": pct(s1.get("cagr")), "sel Sharpe": f4(s1.get("sharpe"), 2)}
    if rnd:
        r["random sel CAGR"] = pct(rnd["sel_2023_25"]["cagr"])
        r["random sel Sharpe"] = f4(rnd["sel_2023_25"]["sharpe"], 2)
        r["random 2026"] = pct(rnd["by_year"].get("2026", rnd["by_year"].get(2026)))
    return r


for p in inv_files:
    d = json.load(open(p))
    tag = d["tag"]
    vp = f"{OUT}/variants_{tag}.json"
    V = json.load(open(vp)) if os.path.exists(vp) else {}
    rr = []
    blocks = [("barrier exit (label geometry)", d.get("long_barrier")), ("time exit h", d.get("long_time")),
              ("target-only (no stop)", V.get("target_only")),
              ("stop-only (no target)", V.get("stop_only")),
              ("time exit, sector cap 4", V.get("long_time_sector4")),
              ("time exit, min P(+1)>=0.5", V.get("long_time_minscore0.5")),
              ("barrier exit, min P(+1)>=0.5", V.get("long_barrier_minscore0.5")),
              ("time exit, step=h single sleeve", V.get("long_time_step_h")),
              ("barrier top_k=10", d.get("long_barrier_k10")), ("barrier top_k=40", d.get("long_barrier_k40")),
              ("SHORT fno barrier", d.get("short_barrier_fno")), ("SHORT fno time", V.get("short_time_fno"))]
    for name, blk in blocks:
        if not blk:
            continue
        for c in (50, 80):
            if f"model_{c}" in blk:
                rr.append(inv_row(f"{name} @{c}bp", blk[f"model_{c}"], blk.get(f"random_{c}")))
            if f"random_{c}" in blk:
                rb = blk[f"random_{c}"]
                rr.append({"strategy": f"  random (5 seeds) {name} @{c}bp", "CAGR": pct(rb["cagr"]), "Sharpe": f4(rb["sharpe"], 2),
                           "maxDD": pct(rb["max_dd"]), "hit": pct(rb["hit_rate"]), "mean trade": pct(rb["mean_trade_net"], 2),
                           "2023": pct(rb["by_year"].get("2023")), "2024": pct(rb["by_year"].get("2024")),
                           "2025": pct(rb["by_year"].get("2025")), "2026 YTD (holdout)": pct(rb["by_year"].get("2026")),
                           "sel 23-25 CAGR": pct(rb["sel_2023_25"]["cagr"]), "sel Sharpe": f4(rb["sel_2023_25"]["sharpe"], 2)})
    b = d["benchmark_nifty500"]
    rr.append({"strategy": "Nifty 500 (price index)", "CAGR": pct(b["cagr"]), "Sharpe": f4(b["sharpe"], 2), "maxDD": pct(b["max_dd"]),
               "2023": pct(b["by_year"].get("2023")), "2024": pct(b["by_year"].get("2024")), "2025": pct(b["by_year"].get("2025")),
               "2026 YTD (holdout)": pct(b["by_year"].get("2026")), "sel 23-25 CAGR": pct(d["benchmark_nifty500_2023_25"]["cagr"]),
               "sel Sharpe": f4(d["benchmark_nifty500_2023_25"]["sharpe"], 2)})
    df = pd.DataFrame(rr).fillna("")
    lines.append(f"\n### Investability: {tag} (top_k=20, step=5, 2023-01-01..2026-09-10)\n\n" + md(df))

with open(f"{OUT}/tables_autogen.md", "w") as fh:
    fh.write("\n".join(lines))
print("ok2", len(lines))
