"""Stage 6: assemble html_tables, charts and the summary (every quoted number is copied from computed sections)."""
import json
import sys
import numpy as np
import pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C
C.set_agent("R3_twoway")
R = C.load_res()
S4, S1, S3m, S5, DG = R["s4_stats"], R["s1_outcomes"], R["s3_runs_meta"], R["s5_boring_avoid"], R["diag_hedge_timing"]
z = np.load(f"{LAB}/results/R3_twoway/series_s3.npz", allow_pickle=True)
keys = list(z["keys"])
SER = {k: pd.Series(z[f"v{i}"], index=pd.DatetimeIndex(z[f"d{i}"])) for i, k in enumerate(keys)}
T = []
DESC = {"BASE": "Frozen PROD long book (top-20, cash, unhedged)",
        "D0": "Avoid veto only: equal-weight all eligible minus PROD bottom 30%",
        "D1a": "BASE + short Nifty 50 futures, hedge ratio 1.0",
        "D1b": "BASE + short Nifty 50 futures, ex-ante 60d beta",
        "D1c": "BASE + short Midcap Select (synthetic futures), ex-ante beta",
        "D2_K10_cash": "F&O long top-10 (cash) / short bottom-10 (stock futures)",
        "D2_K10_fut": "F&O long top-10 / short bottom-10, both via futures",
        "D2_K20_cash": "F&O long top-20 (cash) / short bottom-20 (stock futures)",
        "D2_K20_fut": "F&O long top-20 / short bottom-20, both via futures",
        "X1_D2_K20_cash_beta": "Extra: D2 K20 cash with beta-matched short notional",
        "D3": "BASE + 50% overlay short of F&O bottom-20 (stock futures)",
        "D4": "Short-only F&O bottom-20 (stock futures) on cash collateral",
        "EW": "Baseline: equal-weight all eligible stocks", "RAND": "Baseline: random top-20 (5 seeds)",
        "R_D4_randshort": "Baseline: random F&O short-20 on cash collateral",
        "R_D2_K20_cash_rand": "Baseline: random F&O long-20 / random short-20",
        "R_D3_randshort": "Baseline: BASE + 50% random F&O short overlay"}
STR_ORDER = ["BASE", "D0", "D1a", "D1b", "D1c", "D2_K10_cash", "D2_K10_fut", "D2_K20_cash", "D2_K20_fut",
             "X1_D2_K20_cash_beta", "D3", "D4", "EW", "RAND", "R_D4_randshort", "R_D2_K20_cash_rand", "R_D3_randshort"]


def g(x):
    return None if x is None else float(x)


# ---------------------------------------------------------------- T1 label classes
rows = []
for per, lab in (("dev", "2023-25 (DEV)"), ("2026", "2026 YTD")):
    for c, cn in (("1", "+1 (top 30% residual)"), ("0", "0 (middle 40%)"), ("-1", "-1 (bottom 30% residual)")):
        s = S1["label_classes"][f"{per}|all"][c]
        rows.append([lab, cn, s["mean"], s["median"], s["p_pos"], s["p_lt_m5"], s["n"]])
    u = S1["label_classes"][f"{per}|all"]["universe"]
    rows.append([lab, "all eligible rows", u["mean"], u["median"], u["p_pos"], u["p_lt_m5"], u["n"]])
T.append(C.table("What each realised label class meant in money (20-day hold, after 50 bps)",
                 ["Period", "Label class", "Mean net return", "Median net return", "Share profitable", "Share losing >5%", "Rows"], rows,
                 "Realised (ex-post) classes of the frozen XR_neumom h=20 label. Net = buy at next open, sell at close 20 trading "
                 "days later, minus 50 bps. The label is relative, but the classes are strongly separated in absolute money too. "
                 "These classes are known only afterwards; the tradable version is the score deciles below."))
# ---------------------------------------------------------------- T2 PROD deciles (all)
rows = []
for k in range(1, 11):
    a = S1["prod_deciles_all"]["dev|all"][f"d{k}"]
    b = S1["prod_deciles_all"]["2026|all"][f"d{k}"]
    rows.append([f"Decile {k}" + (" (avoid tail)" if k == 1 else " (top)" if k == 10 else ""), a["mean"], a["p_pos"], a["p_lt_m5"],
                 b["mean"], b["p_pos"], b["p_lt_m5"]])
sa, sb = S1["prod_deciles_all"]["dev|all"]["spread"], S1["prod_deciles_all"]["2026|all"]["spread"]
rows.append(["Top minus bottom (per-date mean)", sa["top_minus_bottom_mean"], None, None, sb["top_minus_bottom_mean"], None, None])
T.append(C.table("Tradable signal: 20-day net return by PROD score decile (all eligible stocks)",
                 ["Decile", "DEV mean net", "DEV share profitable", "DEV share losing >5%", "2026 mean net", "2026 share profitable",
                  "2026 share losing >5%"], rows,
                 f"Deciles formed each day from the frozen PROD score (known at the close). DEV spread t = "
                 f"{sa['nonoverlap_t']:.2f} (non-overlapping), deciles perfectly ordered (rank corr {sa['spearman_decile_vs_mean']:.2f}); "
                 f"2026 spread t = {sb['nonoverlap_t']:.2f}, rank corr {sb['spearman_decile_vs_mean']:.2f}. Even the bottom decile "
                 f"is roughly break-even in absolute terms: the low side is 'worse than the rest', rarely 'falls in absolute terms'."))
# ---------------------------------------------------------------- T3 within F&O
rows = []
for per, lab in (("dev", "2023-25 (DEV)"), ("2026", "2026 YTD")):
    x = S1["prod_deciles_fno"][f"{per}|all"]
    rows.append([lab, x["d10"]["mean"], x["d1"]["mean"], x["spread"]["top_minus_bottom_mean"], x["spread"]["nonoverlap_t"],
                 x["d1_short_net"]["mean"], x["d1_short_net"]["p_pos"], x["universe_short_net"]["mean"]])
T.append(C.table("Inside the F&O list (where single-stock shorting is possible) the signal is weak",
                 ["Period", "Top decile mean net (long)", "Bottom decile mean net (long)", "Top minus bottom", "t (non-overlap)",
                  "Bottom decile as a futures short: mean net", "Share of shorts profitable", "Random F&O short: mean net"], rows,
                 "PROD re-ranked within fno_proxy (top-200 by turnover) and eligible names. Short net = minus the stock's 20-day return "
                 "plus the futures carry (Nifty 1D Rate) minus 25 bps. Shorting the model's bottom decile loses money on average in both "
                 "windows; in 2026 the bottom F&O decile actually rose the most."))
# ---------------------------------------------------------------- T4 market states
rows = []
for per, lab in (("dev", "DEV"), ("2026", "2026")):
    for st, sn in (("above200", "Nifty 500 above 200-dma"), ("below200", "Nifty 500 below 200-dma"),
                   ("mom20_up", "Nifty 500 20d momentum up"), ("mom20_down", "Nifty 500 20d momentum down")):
        dd = S1["prod_deciles_all"].get(f"{per}|{st}")
        lc = S1["label_classes"][f"{per}|{st}"]
        if dd is None:
            continue
        rows.append([lab, sn, dd["universe"]["n"], dd["universe"]["mean"], dd["d10"]["mean"], dd["d1"]["mean"],
                     dd["spread"]["top_minus_bottom_mean"] if dd["spread"] else None, lc["-1"]["mean"], lc["-1"]["p_pos"]])
T.append(C.table("Does the signal depend on the market state? (known at the signal date)",
                 ["Period", "Market state", "Rows", "All stocks mean net", "Top decile mean net", "Bottom decile mean net",
                  "Top minus bottom", "Realised -1 class mean net", "Realised -1: share profitable"], rows,
                 "States use the Nifty 500 at the signal close. The spread (top minus bottom) is positive in every state in both "
                 "windows but not significant below the 200-dma (DEV non-overlap t "
                 f"{S1['prod_deciles_all']['dev|below200']['spread']['nonoverlap_t']:.2f}); the absolute level of every group moves with "
                 f"the market. Share of signal dates above the 200-dma: DEV {S1['state_shares']['dev']['share_dates_above200']:.2f}, "
                 f"2026 {S1['state_shares']['2026']['share_dates_above200']:.2f}."))


# ---------------------------------------------------------------- T5-T7 strategies
def strat_table(key, title, note):
    rows = []
    res = S4[key]
    for nm in STR_ORDER:
        if nm not in res:
            continue
        r = res[nm]
        vb = r.get("vs_base", {})
        adopt = r.get("adopt_rule_pass")
        if nm == "D0":
            vb = r["vs_ew"]
            adopt = r.get("adopt_rule_pass_vs_ew")
        rows.append([nm, DESC.get(nm, nm), r["cagr"], r["vol"], r["sharpe"], r["maxdd"], r["worst_month"], r["pct_pos_months"],
                     r["corr_n500_daily"], r["down_months_mean_ret"], vb.get("diff_ann"), vb.get("nw_t"),
                     ("yes" if adopt else "no") if adopt is not None else "-"])
    return C.table(title, ["Id", "Strategy", "CAGR", "Volatility", "Sharpe", "Max drawdown", "Worst month", "Share of positive months",
                           "Correlation with Nifty 500", "Avg return in months Nifty 500 fell >3%", "Gain vs BASE per yr (D0: vs EW)",
                           "t-stat of gain", "Adopted (rule)"], rows, note)


T.append(strat_table("dev|c50", "Using the down side: all strategies, 2023-2025 selection window (50 bps)",
                     "Phase-averaged daily mark-to-market. Gain = annualised mean daily difference vs the frozen BASE book with "
                     "Newey-West t (lag 20); D0 is compared with the equal-weight universe. Adoption rule (pre-registered): t >= 2 and "
                     "max drawdown not worse by more than 3 pp. Futures carry, margin (index 15%, stock 25%, half in cash at the "
                     "Nifty 1D Rate) and costs as declared in 'predeclared'. 3 months with Nifty 500 down >3% in this window."))
T.append(strat_table("hold|c50", "Same strategies in 2026 (Jan to mid-Oct): report only, never used to choose",
                     "2026 was a large-cap decline (Nifty 50 futures -22% annualised) while small caps rose: index hedges look "
                     "brilliant and single-stock shorts of high-momentum names lose. Treat as one regime, not a verdict."))
T.append(strat_table("contig|c50", "One contiguous run, Jan-2023 to Oct-2026 (context)",
                     "Single uninterrupted book (no reset at 2026). 6 months with Nifty 500 down >3%."))
# ---------------------------------------------------------------- T8 stress
rows = []
for nm in ["BASE", "D0", "D1a", "D1b", "D1c", "D2_K10_cash", "D2_K10_fut", "D2_K20_cash", "D2_K20_fut", "X1_D2_K20_cash_beta", "D3", "D4"]:
    a, b = S4["dev|c80"][nm], S4["hold|c80"][nm]
    vb = a["vs_ew"] if nm == "D0" else a.get("vs_base", {})
    rows.append([nm, a["cagr"], a["sharpe"], a["maxdd"], vb.get("diff_ann"), vb.get("nw_t"), b["cagr"], b["sharpe"], b["maxdd"]])
T.append(C.table("Cost stress: cash trades at 80 bps, futures at 40 bps, hedge costs x1.6",
                 ["Id", "DEV CAGR", "DEV Sharpe", "DEV max drawdown", "DEV gain vs BASE (D0: vs EW)", "t-stat", "2026 CAGR", "2026 Sharpe",
                  "2026 max drawdown"], rows, "Conclusions are unchanged under stress; D2 long/short falls below the cash rate."))
# ---------------------------------------------------------------- T9 selection skill of shorts
rows = []
for nm, lab in (("D4_vs_random_short", "Short-only bottom-20 vs random F&O short-20"),
                ("D2_K20_cash_vs_random_LS", "Long/short K20 vs random long/random short"),
                ("D3_vs_D3_random_short", "BASE + model short overlay vs BASE + random short overlay"),
                ("random_short_vs_cash", "Random F&O short vs cash (market drift)")):
    a, b = S4["dev|c50"]["selection"][nm], S4["hold|c50"]["selection"][nm]
    rows.append([lab, a["diff_ann"], a["nw_t"], b["diff_ann"], b["nw_t"]])
T.append(C.table("Does the model pick better shorts than chance?",
                 ["Comparison", "DEV gain per yr", "DEV t-stat", "2026 gain per yr", "2026 t-stat"], rows,
                 "Same engine, costs, carry and margin; only the short picks differ (5 random seeds). The model's short picks "
                 "beat random shorts in DEV (not significant) and lost badly to them in 2026; shorting itself (random) bleeds "
                 "with the market's upward drift."))
# ---------------------------------------------------------------- T10 boring explanation for the avoid veto
rows = []
for per, lab in (("dev|c50", "DEV"), ("hold|c50", "2026")):
    x = S5[per]
    rows.append([lab, x["D0"]["pa_excess_vs_ew_ann"], x["D0"]["pa_vs_ew_nw_t"], x["B1_volveto"]["pa_excess_vs_ew_ann"],
                 x["B2_betaveto"]["pa_excess_vs_ew_ann"], x["B1_volveto"]["corr_excess_with_D0"],
                 x["B1_volveto"]["D0_residual_alpha_ann"], x["B1_volveto"]["D0_residual_alpha_nw_t"],
                 x["B2_betaveto"]["D0_residual_alpha_ann"], x["B2_betaveto"]["D0_residual_alpha_nw_t"]])
T.append(C.table("Is the avoid veto just 'avoid volatile stocks'? No.",
                 ["Period", "Avoid veto gain vs EW per yr", "t-stat", "Veto top-30% volatility instead", "Veto top-30% beta instead",
                  "Correlation with vol-veto", "Avoid alpha after removing vol tilt", "t-stat", "Avoid alpha after removing beta tilt", "t-stat"],
                 rows, "Simple factor vetoes earn nothing in DEV and lose in 2026. The PROD avoid list overlaps with high-volatility "
                       "names (corr 0.77) but keeps about 3% a year of stock-specific value in both windows once that tilt is regressed out "
                       "(t-stats ignore slope estimation error)."))
# ---------------------------------------------------------------- T11 verdict by trader type
d0d, d0h = S4["dev|c50"]["D0"]["vs_ew"], S4["hold|c50"]["D0"]["vs_ew"]
d1d, d1h = S4["dev|c50"]["D1b"], S4["hold|c50"]["D1b"]
d3d, d3h = S4["dev|c50"]["D3"], S4["hold|c50"]["D3"]
d4d, d4h = S4["dev|c50"]["D4"], S4["hold|c50"]["D4"]
d2d, d2h = S4["dev|c50"]["D2_K10_fut"], S4["hold|c50"]["D2_K10_fut"]
rows = [
    ["Cash only (no F&O)", "Use the -1 side as a VETO/EXIT list (D0); never as a short", d0d["diff_ann"], d0h["diff_ann"],
     "Viable: the only add-on that passes the rule (vs EW); stock-specific, not a vol tilt"],
    ["Cash + Nifty index futures", "Optional hedge D1b (risk dial, not alpha)", d1d["vs_base"]["diff_ann"], d1h["vs_base"]["diff_ann"],
     "Not adopted: costs ~8-9%/yr in DEV; max drawdown 17% vs 27%; 2026 windfall = large-cap fall"],
    ["Full F&O: overlay short", "BASE + 50% short of F&O bottom-20 (D3)", d3d["vs_base"]["diff_ann"], d3h["vs_base"]["diff_ann"],
     "Not adopted: smoother in DEV, but lower return and failed in 2026"],
    ["Full F&O: long/short", "F&O top-10 vs bottom-10 via futures (D2, best DEV variant)", d2d["vs_base"]["diff_ann"], d2h["vs_base"]["diff_ann"],
     "Not viable: below cash over 2023-26, -24% in 2026"],
    ["Full F&O: short only", "Short F&O bottom-20 on cash collateral (D4)", d4d["vs_base"]["diff_ann"], d4h["vs_base"]["diff_ann"],
     "Not viable: loses money in both windows"],
]
T.append(C.table("Verdict: how an Indian swing trader can use the 'down' signal",
                 ["Trader type", "Use of the -1 side", "DEV gain per yr (D0 vs EW, others vs BASE)", "2026 gain per yr", "Verdict"], rows,
                 "Gains are annualised mean daily differences (phase-averaged, 50 bps). Only the veto passes the pre-registered "
                 "adoption rule on DEV."))

# ---------------------------------------------------------------- charts
CH = {}


def monthly_eq(s):
    eq = (1 + s.fillna(0)).cumprod()
    m = eq.groupby(eq.index.to_period("M")).last()
    return m


base_c = SER["BASE|contig|c50"]
idx = base_c.index
series = {"BASE (PROD long, unhedged)": base_c, "D0 avoid veto (EW minus bottom 30%)": SER["D0|contig|c50"],
          "EW universe": SER["EW|contig|c50"], "D1b BASE + Nifty 50 futures hedge": SER["D1b|contig|c50"],
          "D3 BASE + 50% F&O short overlay": SER["D3|contig|c50"], "D2 F&O long/short K10 (futures)": SER["D2_K10_fut|contig|c50"],
          "D4 F&O short-only": SER["D4|contig|c50"], "Nifty 500 (price index)": SER["N500"].reindex(idx),
          "Cash (Nifty 1D Rate)": SER["CASH1D"].reindex(idx)}
mq = {k: monthly_eq(v.reindex(idx)) for k, v in series.items()}
xs = [str(p) for p in mq["BASE (PROD long, unhedged)"].index]
CH["equity_contig_monthly"] = {"type": "line", "x": xs, "series": {k: [float(v) for v in m.values] for k, m in mq.items()},
                               "note": "Growth of 1 rupee, Jan-2023 to Oct-2026, month-end values, 50 bps costs, phase-averaged. Nifty 500 is a price "
                                       "index (about 1.2%/yr dividends missing); stock books are dividend-adjusted."}
CH["decile_mean_net"] = {"type": "bar", "x": [f"D{k}" for k in range(1, 11)],
                         "series": {"2023-25 (DEV)": [S1["prod_deciles_all"]["dev|all"][f"d{k}"]["mean"] for k in range(1, 11)],
                                    "2026 YTD": [S1["prod_deciles_all"]["2026|all"][f"d{k}"]["mean"] for k in range(1, 11)]},
                         "note": "Average 20-day net return (after 50 bps) by PROD score decile, all eligible stocks. D1 = avoid tail, D10 = top."}
CH["fno_decile_mean_net"] = {"type": "bar", "x": [f"D{k}" for k in range(1, 11)],
                             "series": {"2023-25 (DEV)": [S1["prod_deciles_fno"]["dev|all"][f"d{k}"]["mean"] for k in range(1, 11)],
                                        "2026 YTD": [S1["prod_deciles_fno"]["2026|all"][f"d{k}"]["mean"] for k in range(1, 11)]},
                             "note": "Same, inside the F&O list only (where shorts are possible): the ordering is weak and flips in 2026."}
nm_dm = ["BASE", "D0", "EW", "D1a", "D1b", "D1c", "D2_K10_fut", "D2_K20_cash", "D3", "D4"]
CH["down_month_returns"] = {"type": "bar", "x": nm_dm,
                            "series": {"Avg return in Nifty-500-down months (2023-26)": [S4["contig|c50"][n]["down_months_mean_ret"] for n in nm_dm]},
                            "note": f"Average monthly return in the {S4['contig|c50']['BASE']['n500_down_months_n']} months when the Nifty 500 fell more "
                                    f"than 3% (its average in those months: {S4['contig|c50']['BASE']['down_months_n500_mean']:.3f})."}
nm_c = ["BASE", "D0", "D1a", "D1b", "D1c", "D2_K10_cash", "D2_K10_fut", "D2_K20_cash", "D2_K20_fut", "X1_D2_K20_cash_beta", "D3", "D4"]
CH["cagr_dev_vs_2026"] = {"type": "bar", "x": nm_c,
                          "series": {"CAGR 2023-25 (DEV)": [S4["dev|c50"][n]["cagr"] for n in nm_c],
                                     "CAGR 2026 YTD (annualised)": [S4["hold|c50"][n]["cagr"] for n in nm_c]},
                          "note": "Compound annual growth, 50 bps. DEV is the selection window; 2026 is report-only."}
bn, bm = SER["beta_n50fut"], SER["beta_msfut"]
wk = bn.index[::5]
CH["hedge_beta_ex_ante"] = {"type": "line", "x": [str(d)[:10] for d in wk],
                            "series": {"Beta to Nifty 50 futures": [float(v) for v in bn.reindex(wk).values],
                                       "Beta to Midcap Select (synthetic futures)": [float(v) for v in bm.reindex(wk).values]},
                            "note": "Ex-ante 60-day beta of the BASE book (data up to the previous day), weekly samples; 1.0 before 40 observations."}
CH["label_class_by_state_dev"] = {"type": "bar", "x": ["above 200-dma", "below 200-dma", "20d mom up", "20d mom down"],
                                  "series": {f"class {c}": [S1["label_classes"][f"dev|{s}"][c]["mean"] for s in
                                                            ("above200", "below200", "mom20_up", "mom20_down")] for c in ("1", "0", "-1")},
                                  "note": "Mean 20-day net return of realised label classes by Nifty 500 state at the signal date, DEV."}

# ---------------------------------------------------------------- summary (all numbers copied from computed sections)
summ = {
    "variants_tested": 13,
    "variants_detail": "10 pre-declared strategies (D0, D1a, D1b, D1c, D2 x4, D3, D4) + 3 extra (X1 beta-matched D2; B1 vol-veto, "
                       "B2 beta-veto diagnostics); each at 50 and 80 bps; baselines (BASE, EW, random top-20, random shorts) not counted",
    "BASE": {"dev_cagr": S4["dev|c50"]["BASE"]["cagr"], "hold_cagr": S4["hold|c50"]["BASE"]["cagr"],
             "dev_vs_random": S4["dev|c50"]["BASE"]["vs_random"], "hold_vs_random": S4["hold|c50"]["BASE"]["vs_random"],
             "dev_maxdd": S4["dev|c50"]["BASE"]["maxdd"], "hold_maxdd": S4["hold|c50"]["BASE"]["maxdd"],
             "dev_sharpe": S4["dev|c50"]["BASE"]["sharpe"], "hold_sharpe": S4["hold|c50"]["BASE"]["sharpe"]},
    "D0": {"dev_vs_ew": d0d, "hold_vs_ew": d0h, "dev_cagr": S4["dev|c50"]["D0"]["cagr"], "hold_cagr": S4["hold|c50"]["D0"]["cagr"],
           "dev_ew_cagr": S4["dev|c50"]["EW"]["cagr"], "hold_ew_cagr": S4["hold|c50"]["EW"]["cagr"],
           "dev_maxdd_change_vs_ew": S4["dev|c50"]["D0"]["maxdd_change_vs_ew"], "adopted_vs_ew": S4["dev|c50"]["D0"]["adopt_rule_pass_vs_ew"],
           "dev_residual_alpha_after_vol": S5["dev|c50"]["B1_volveto"]["D0_residual_alpha_ann"],
           "dev_residual_alpha_after_vol_t": S5["dev|c50"]["B1_volveto"]["D0_residual_alpha_nw_t"],
           "hold_residual_alpha_after_vol": S5["hold|c50"]["B1_volveto"]["D0_residual_alpha_ann"],
           "hold_residual_alpha_after_vol_t": S5["hold|c50"]["B1_volveto"]["D0_residual_alpha_nw_t"],
           "dev_volveto_vs_ew": S5["dev|c50"]["B1_volveto"]["pa_excess_vs_ew_ann"], "hold_volveto_vs_ew": S5["hold|c50"]["B1_volveto"]["pa_excess_vs_ew_ann"],
           "c80_dev_vs_ew": S4["dev|c80"]["D0"]["vs_ew"]},
    "strategies": {nm: {"dev": {k: S4["dev|c50"][nm][k] for k in ("cagr", "vol", "sharpe", "maxdd", "worst_month", "pct_pos_months",
                                                                  "corr_n500_daily", "down_months_mean_ret")} | {
                                    "vs_base": S4["dev|c50"][nm].get("vs_base"), "adopt": S4["dev|c50"][nm].get("adopt_rule_pass"),
                                    "maxdd_change_vs_base": S4["dev|c50"][nm].get("maxdd_change_vs_base")},
                        "hold": {k: S4["hold|c50"][nm][k] for k in ("cagr", "vol", "sharpe", "maxdd", "worst_month", "pct_pos_months",
                                                                    "corr_n500_daily", "down_months_mean_ret")} | {
                                    "vs_base": S4["hold|c50"][nm].get("vs_base")},
                        "contig": {k: S4["contig|c50"][nm][k] for k in ("cagr", "sharpe", "maxdd", "down_months_mean_ret")},
                        "c80_dev_cagr": S4["dev|c80"][nm]["cagr"], "c80_hold_cagr": S4["hold|c80"][nm]["cagr"]}
                   for nm in ["BASE", "D0", "D1a", "D1b", "D1c", "D2_K10_cash", "D2_K10_fut", "D2_K20_cash", "D2_K20_fut",
                              "X1_D2_K20_cash_beta", "D3", "D4"]},
    "selection_vs_random": {"dev": S4["dev|c50"]["selection"], "hold": S4["hold|c50"]["selection"]},
    "outcomes": {"dev_spread": S1["prod_deciles_all"]["dev|all"]["spread"]["top_minus_bottom_mean"],
                 "dev_spread_t": S1["prod_deciles_all"]["dev|all"]["spread"]["nonoverlap_t"],
                 "hold_spread": S1["prod_deciles_all"]["2026|all"]["spread"]["top_minus_bottom_mean"],
                 "hold_spread_t": S1["prod_deciles_all"]["2026|all"]["spread"]["nonoverlap_t"],
                 "dev_d1_mean": S1["prod_deciles_all"]["dev|all"]["d1"]["mean"], "dev_d10_mean": S1["prod_deciles_all"]["dev|all"]["d10"]["mean"],
                 "dev_univ_mean": S1["prod_deciles_all"]["dev|all"]["universe"]["mean"],
                 "hold_d1_mean": S1["prod_deciles_all"]["2026|all"]["d1"]["mean"], "hold_d10_mean": S1["prod_deciles_all"]["2026|all"]["d10"]["mean"],
                 "hold_univ_mean": S1["prod_deciles_all"]["2026|all"]["universe"]["mean"],
                 "dev_rank_corr": S1["prod_deciles_all"]["dev|all"]["spread"]["spearman_decile_vs_mean"],
                 "hold_rank_corr": S1["prod_deciles_all"]["2026|all"]["spread"]["spearman_decile_vs_mean"],
                 "fno_dev_spread": S1["prod_deciles_fno"]["dev|all"]["spread"]["top_minus_bottom_mean"],
                 "fno_dev_spread_t": S1["prod_deciles_fno"]["dev|all"]["spread"]["nonoverlap_t"],
                 "fno_hold_spread": S1["prod_deciles_fno"]["2026|all"]["spread"]["top_minus_bottom_mean"],
                 "fno_dev_d1_short_net": S1["prod_deciles_fno"]["dev|all"]["d1_short_net"]["mean"],
                 "fno_hold_d1_short_net": S1["prod_deciles_fno"]["2026|all"]["d1_short_net"]["mean"],
                 "fno_dev_univ_short_net": S1["prod_deciles_fno"]["dev|all"]["universe_short_net"]["mean"],
                 "class_dev": {c: S1["label_classes"]["dev|all"][c] for c in ("1", "0", "-1")},
                 "class_hold": {c: S1["label_classes"]["2026|all"][c] for c in ("1", "0", "-1")}},
    "hedge": {"beta_ex_ante": S3m["beta_ex_ante"], "notional_over_nav": S3m["hedge_notional_over_nav"],
              "d1c_2026_timing": {k: v for k, v in DG["D1c|hold"].items() if k != "monthly"},
              "d1b_2026_timing": {k: v for k, v in DG["D1b|hold"].items() if k != "monthly"}},
    "tilts_fno_short_picks": R["s4_fno_pick_tilts"],
    "reference": {k: S4["reference_series"][k] for k in ("N50FUT|dev", "N50FUT|hold", "N500|dev", "N500|hold", "CASH1D|dev", "CASH1D|hold",
                                                         "MSFUT|dev", "MSFUT|hold")},
}
C.save("summary", summ)
C.save("html_tables", T)
C.save("charts", CH)
C.log("tables", len(T), "charts", list(CH))
