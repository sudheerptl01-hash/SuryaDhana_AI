"""Curated markdown tables for REPORT.md (all numbers read from saved JSON/CSV)."""
import json
import os

import numpy as np
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(f"{OUT}/results.json"))
EV = json.load(open(f"{OUT}/events_shortlist.json"))
G = pd.read_csv(f"{OUT}/grid.csv")
SIG = json.load(open(f"{OUT}/significance.json"))
T = {}


def pct(x, d=1):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.{d}f}"


def f(x, d=2):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def md(df):
    cols = list(df.columns)
    s = "| " + " | ".join(map(str, cols)) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    for _, r in df.iterrows():
        s += "| " + " | ".join(str(r[c]) for c in cols) + " |\n"
    return s


G["geometry"] = np.where(G.kind == "fix", "fix " + G.a.astype(str) + "/" + G.b.astype(str),
                         "sqrt " + G.a.astype(str) + "/" + G.b.astype(str))

# T1: geometry outcomes, long, h in 10,20
for h in (5, 10, 15, 20):
    t = G[(G.side == "long") & (G.h == h)]
    T[f"geom_long_h{h}"] = md(pd.DataFrame({
        "geometry (pt/sl)": t.geometry, "pt x ATR": t.pt_mult.round(2), "sl x ATR": t.sl_mult.round(2),
        "median tgt %": (100 * t.med_pt_pct).round(1), "median stop %": (100 * t.med_sl_pct).round(1),
        "P(tgt)": t.sh_pt.map(pct), "P(stop)": t.sh_sl.map(pct), "P(time)": t.sh_time.map(pct),
        "med bars tgt": t.medk_pt.astype(int), "med bars stop": t.medk_sl.astype(int), "mean bars held": t.meank_all.round(1),
        "P(+1) t50": t.p1_t50.map(pct), "P(-1) t50": t.m1_t50.map(pct), "P(0) t50": t.z_t50.map(pct),
        "net|+1": t.net_p1_t50.map(pct), "net|-1": t.net_m1_t50.map(pct),
        "uncond net/trade 23-25": t.net_all_sel.map(lambda x: pct(x, 2)), "uncond net 2026": t.net_all_2026.map(lambda x: pct(x, 2)),
        "mon std P(+1)": t.mon_std_t50.map(pct), "corr mon vs mkt": t.mon_corr_mkt_t50.round(2)}))
    t = G[(G.side == "short") & (G.h == h)]
    T[f"geom_short_h{h}"] = md(pd.DataFrame({
        "geometry (pt/sl)": t.geometry, "P(tgt)": t.sh_pt.map(pct), "P(stop)": t.sh_sl.map(pct), "P(time)": t.sh_time.map(pct),
        "P(+1) t50": t.p1_t50.map(pct), "P(-1) t50": t.m1_t50.map(pct),
        "net|+1": t.net_p1_t50.map(pct), "net|-1": t.net_m1_t50.map(pct),
        "uncond net/trade 23-25": t.net_all_sel.map(lambda x: pct(x, 2)), "uncond net 2026": t.net_all_2026.map(lambda x: pct(x, 2)),
        "P(+1) 2023": t.p1_t50_2023.map(pct), "P(+1) 2024": t.p1_t50_2024.map(pct), "P(+1) 2025": t.p1_t50_2025.map(pct),
        "P(+1) 2026": t.p1_t50_2026.map(pct), "corr mon vs mkt": t.mon_corr_mkt_t50.round(2)}))

# T2: tau sensitivity (all h, long) compact: P(+1) at tau 0/50/100 and touch-only
t = G[G.side == "long"]
T["tau_long"] = md(pd.DataFrame({"h": t.h, "geometry": t.geometry,
                                 "P(+1) tau0": t.p1_t0.map(pct), "P(+1) tau50": t.p1_t50.map(pct), "P(+1) tau100": t.p1_t100.map(pct),
                                 "P(0) tau0": t.z_t0.map(pct), "P(0) tau50": t.z_t50.map(pct), "P(0) tau100": t.z_t100.map(pct),
                                 "P(+1) touch-only (=P(tgt))": t.sh_pt.map(pct),
                                 "+1 labels net>0 @tau0": t.coh_p1_t0.map(pct), "+1 net>0 @tau50": t.coh_p1_t50.map(pct)}))

# T3: shortlist scorecard
rows = []
for cid, o in EV.items():
    for side in ("long", "short"):
        s = o[side]
        r = s["event_report_tau50"]
        bp = s["by_period"]
        rows.append({"candidate": f"{cid} {side}", "pt/sl x ATR": f"{o['pt_mult_atr']:.2f}/{o['sl_mult_atr']:.2f}",
                     "n": r["n"],
                     "P(tgt)/P(stop)/P(time) 23-25": f"{pct(bp['2023_25']['p_pt'])}/{pct(bp['2023_25']['p_sl'])}/{pct(bp['2023_25']['p_time'])}",
                     "P(+1)/P(-1)/P(0) all": f"{pct(r['overall'].get('1.0'))}/{pct(r['overall'].get('-1.0'))}/{pct(r['overall'].get('0.0'))}",
                     **{str(y): pct(r["by_year"][str(y)]["1.0"]) for y in range(2021, 2027)},
                     "mon mean/std": f"{pct(r['monthly_pos']['mean'])}/{pct(r['monthly_pos']['std'])}",
                     "mon min-max": f"{pct(r['monthly_pos']['min'])}-{pct(r['monthly_pos']['max'])}",
                     "corr mon vs mkt": f(r.get("corr_monthly_pos_vs_mkt_ret")),
                     "corr daily P(+1) vs same-window mkt": f(s["regime_daily"]["corr_daily_pos_vs_mktfwd_all"]),
                     "daily P(+1) p5-p95": f"{pct(s['regime_daily']['daily_pos_p05_p95'][0])}-{pct(s['regime_daily']['daily_pos_p05_p95'][1])}",
                     "mean bars": f(bp["2023_25"]["mean_k"], 1)})
T["shortlist_events"] = md(pd.DataFrame(rows))
rows = []
for cid, o in EV.items():
    for side in ("long", "short"):
        s = o[side]
        r = s["event_report_tau50"]
        reg = r["by_regime"]
        lt = r["by_liquidity_tercile"]
        rows.append({"candidate": f"{cid} {side}",
                     **{k: pct(reg[k]["1.0"]) for k in ("bull_up20", "bull_dn20", "bear_up20", "bear_dn20")},
                     "liq T1(low)": pct(lt["0"]["1.0"]), "liq T2": pct(lt["1"]["1.0"]), "liq T3(high)": pct(lt["2"]["1.0"]),
                     "fno_proxy P(+1)": pct(s["fno_event_report_tau50"]["overall"].get("1.0")),
                     "touch-only P(+1)": pct(s["touch_only_report"]["overall"].get("1.0")),
                     "ACF lag1": f(s["autocorr"]["1"]), "ACF lag5": f(s["autocorr"]["5"]),
                     "var. inflation 1+2*sum(rho)": f(s["variance_inflation_1p2sum_rho"], 1),
                     "net|+1": pct(s["class_pnl"]["1"]["mean_net50"]), "net|-1": pct(s["class_pnl"]["-1"]["mean_net50"]),
                     "+1 still >0 at 80bp": pct(s["class_pnl"]["1"]["share_net80_pos"])})
T["shortlist_regime"] = md(pd.DataFrame(rows))
reg_counts = EV["B20_f2.0_2.0"]["long"]["event_report_tau50"]["by_regime"]
T["regime_counts"] = ", ".join(f"{k}: n={v['n']:,}" for k, v in reg_counts.items())

# T5: exit economics + ambiguity
X = R["extras_ambiguity_exitcost"]
rows = []
for cid in ("B10_f2.0_1.5", "B15_f2.0_2.0", "B20_f2.0_2.0", "B20_f3.0_1.5", "B10_s0.75_0.75", "B10_s1.5_1.0"):
    o = X[cid]
    rows.append({"candidate": cid, "same-bar ambiguous %": pct(o["ambiguous_same_bar_share"], 2),
                 "gap-through stop %": pct(o["gap_stop_share"], 1), "gap-through target %": pct(o["gap_tgt_share"], 1),
                 "barrier net/trade 21-22": pct(o["barrier_net50_2021_22"], 2), "23-25": pct(o["barrier_net50_2023_25"], 2),
                 "2026": pct(o["barrier_net50_2026"], 2),
                 "gross/day barrier 23-25 (bp)": f(1e4 * o["barrier_gross_perday_2023_25"], 1),
                 "gross/day time-exit 23-25 (bp)": f(1e4 * o["time_gross_perday_2023_25"], 1),
                 "P(tgt) ATR terciles lo/mid/hi": "/".join(pct(o["ptgt_by_atr_tercile"][k]) for k in ("0", "1", "2")),
                 "P(stop) ATR terciles": "/".join(pct(o["psl_by_atr_tercile"][k]) for k in ("0", "1", "2")),
                 "P(+1) ATR terciles": "/".join(pct(o["p1_by_atr_tercile"][k]) for k in ("0", "1", "2"))})
T["exit_econ"] = md(pd.DataFrame(rows))
rows = []
for h in (5, 10, 15, 20):
    o = X[f"time_exit_h{h}"]
    rows.append({"h": h, **{f"net/trade {p}": pct(o[p]["net50_mean"], 2) for p in ("2021_22", "2023_25", "2026")},
                 **{f"P(net>0) {p}": pct(o[p]["p_net_pos"]) for p in ("2021_22", "2023_25", "2026")}})
T["time_exit_uncond"] = md(pd.DataFrame(rows))

# T8: cross-model investability summary
names = {"B20_f2.0_2.0_long_binary_2023-2024-2025-2026": "A1 B20 sym 2/2 binary (PRIMARY)",
         "B20_f3.0_1.5_long_binary_2023-2024-2025-2026": "A2 B20 asym 3/1.5 binary",
         "B10_f2.0_1.5_long_binary_2023-2024-2025-2026": "A3 B10 2/1.5 binary",
         "B20_f2.0_2.0_long_multiclass_2023-2024-2025-2026": "A1m B20 sym multiclass",
         "B20_f2.0_2.0_long_binary_2023-2024-2025-2026_nomkt": "A1x B20 sym binary, no market feats",
         "T20_time_pm50_long_binary_2023-2024-2025-2026": "CTRL 20d time-only sign label"}
rows = []
for tag, nm in names.items():
    I = R[f"invest_{tag}"]
    V = R.get(f"variants_{tag}", {})
    for key, lab, src in (("long_barrier", "barrier exit (own geometry; CTRL uses 2/2)", I), ("long_time", "time exit 20d" if "B10" not in tag else "time exit 10d", I),
                          ("target_only", "target-only (no stop)", V), ("stop_only", "stop-only", V)):
        b = src.get(key)
        if not b:
            continue
        for c in (50, 80):
            m = b[f"model_{c}"]
            rn = b.get(f"random_{c}")
            rows.append({"model": nm, "exit": lab, "cost": c,
                         "sel 23-25 CAGR": pct(m["sel_2023_25"]["cagr"]), "sel Sharpe": f(m["sel_2023_25"]["sharpe"]),
                         "random sel CAGR": pct(rn["sel_2023_25"]["cagr"]) if rn else "", "random sel Sharpe": f(rn["sel_2023_25"]["sharpe"]) if rn else "",
                         "full CAGR": pct(m["cagr"]), "full maxDD": pct(m["max_dd"]), "hit": pct(m["hit_rate"]),
                         "mean trade": pct(m["mean_trade_net"], 2),
                         "2026 holdout": pct(m["by_year"].get("2026")), "random 2026": pct(rn["by_year"].get("2026")) if rn else ""})
T["invest_summary"] = md(pd.DataFrame(rows))
b = R["invest_B20_f2.0_2.0_long_binary_2023-2024-2025-2026"]
T["nifty"] = (f"Nifty 500 price index: 2023-01-01..2026-09-10 CAGR {pct(b['benchmark_nifty500']['cagr'])}%, Sharpe {f(b['benchmark_nifty500']['sharpe'])}, "
              f"maxDD {pct(b['benchmark_nifty500']['max_dd'])}%; 2023-25 CAGR {pct(b['benchmark_nifty500_2023_25']['cagr'])}% (Sharpe {f(b['benchmark_nifty500_2023_25']['sharpe'])}); "
              f"2026 YTD {pct(b['benchmark_nifty500_2026']['total_return'])}%; by year " + ", ".join(f"{k}: {pct(v)}%" for k, v in b['benchmark_nifty500']['by_year'].items()))

# gating + short
rows = []
for tag, nm in names.items():
    V = R.get(f"variants_{tag}", {})
    I = R[f"invest_{tag}"]
    for key, lab, src in (("long_time_minscore0.5", "time exit, only P(+1)>=0.5", V), ("long_barrier_minscore0.5", "barrier exit, only P(+1)>=0.5", V),
                          ("short_barrier_fno", "SHORT fno, barrier", I), ("short_time_fno", "SHORT fno, time", V)):
        bb = src.get(key)
        if not bb:
            continue
        m = bb["model_50"]
        rn = bb.get("random_50")
        rows.append({"model": nm, "variant @50bp": lab, "sel CAGR": pct(m["sel_2023_25"]["cagr"]), "sel Sharpe": f(m["sel_2023_25"]["sharpe"]),
                     "full maxDD": pct(m["max_dd"]), "2026": pct(m["by_year"].get("2026")),
                     "random sel CAGR": pct(rn["sel_2023_25"]["cagr"]) if rn else "", "random 2026": pct(rn["by_year"].get("2026")) if rn else ""})
    cov = V.get("minscore0.5_coverage")
    if cov:
        rows.append({"model": nm, "variant @50bp": f"(gate coverage: dates with >=20 names passing {pct(cov['share_dates_ge20'])}%, >=1 name {pct(cov['share_dates_ge1'])}%)",
                     "sel CAGR": "", "sel Sharpe": "", "full maxDD": "", "2026": "", "random sel CAGR": "", "random 2026": ""})
T["gate_short"] = md(pd.DataFrame(rows))

# T9 significance
rows = []
for tag, nm in names.items():
    S = SIG[tag]
    for rn, lab in (("time20", "20d time exit"), ("barrierB20sym", "B20 2/2 barrier exit"), ("barrierB20asym", "B20 3/1.5 barrier exit")):
        o = S[rn]
        rows.append({"model": nm, "return measured": lab,
                     "excess/trade 23-25": pct(o["2023_25"]["mean_excess_per_trade"], 2), "t_eff 23-25": f(o["2023_25"]["t_eff_all_dates"]),
                     "2023": f"{pct(o['2023']['mean_excess_per_trade'], 2)} (t {f(o['2023']['t_eff_all_dates'])})",
                     "2024": f"{pct(o['2024']['mean_excess_per_trade'], 2)} (t {f(o['2024']['t_eff_all_dates'])})",
                     "2025": f"{pct(o['2025']['mean_excess_per_trade'], 2)} (t {f(o['2025']['t_eff_all_dates'])})",
                     "2026 holdout": f"{pct(o['2026']['mean_excess_per_trade'], 2)} (t {f(o['2026']['t_eff_all_dates'])})",
                     "% dates >0 23-25": pct(o["2023_25"]["share_dates_positive"])})
T["significance"] = md(pd.DataFrame(rows))
json.dump(T, open(f"{OUT}/curated_tables.json", "w"), indent=1)
for k, v in T.items():
    print("=====", k)
    print(v[:1500])
