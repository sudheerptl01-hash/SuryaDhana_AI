"""R3_book summary: copies (never retypes) the headline numbers from the computed sections into one section."""
import json, sys
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C
C.set_agent("R3_book")
R = C.load_res()
I1, I2, I2b, I3, I4 = R["item1_repro"], R["item2_exits"], R["item2b_x3_decomposition"], R["item3_capacity"], R["item4_ops_tax"]
H = {}
for nm in ("PROD", "single", "ens3"):
    for per in ("dev", "hold"):
        for c in (50, 80):
            p = I1[nm][f"{per}_c{c}"]
            H[f"{nm}_{per}_c{c}"] = {k: p[k] for k in ("pa_cagr", "pa_random_cagr", "pa_ew_cagr", "pa_excess_ann", "pa_nw_t",
                                                       "pa_excess_vs_ew_ann", "pa_vs_ew_nw_t", "pa_maxdd", "pa_sharpe", "pa_vol",
                                                       "phase_excess_min", "phase_excess_max", "start", "end")}
            H[f"{nm}_{per}_c{c}"]["nifty500_cagr"] = p["nifty500_stats"]["cagr"]
H["PROD_vs_single_ens3_paired"] = I1["paired_vs_PROD"]
H["top20_overlap_PROD_with"] = I1["top20_overlap_PROD_with"]
H["PROD_trade_stats_dev_c50"] = I1["PROD"]["dev_c50"]["trade_stats_phase_mean"]
H["PROD_trade_stats_hold_c50"] = I1["PROD"]["hold_c50"]["trade_stats_phase_mean"]
H["PROD_contig_by_year"] = I1["PROD"]["contig_c50"]["by_year"]
H["PROD_contig_c50"] = {k: I1["PROD"]["contig_c50"][k] for k in ("pa_cagr", "pa_random_cagr", "pa_ew_cagr", "pa_excess_ann", "pa_nw_t", "pa_maxdd", "start", "end")}
H["quarters_negative_vs_random_contig"] = sum(1 for v in I1["PROD"]["contig_c50"]["by_quarter"].values() if v["ex_vs_random"] < 0)
H["quarters_total_contig"] = len(I1["PROD"]["contig_c50"]["by_quarter"])
A = {}
for v in ("X1", "E1", "X3", "E2w", "E2d", "E3", "S1"):
    A[v] = {}
    for key in ("dev_c50", "hold_c50", "dev_c80", "hold_c80"):
        s = I2[v][key]
        A[v][key] = {"pa_cagr": s["pa_cagr"], "gain_vs_E0_ann": s["paired_vs_E0"]["diff_ann"], "paired_t_vs_E0": s["paired_vs_E0"]["nw_t"],
                     "pa_maxdd": s["pa_maxdd"], "delta_maxdd_vs_E0": s["delta_maxdd_vs_E0"], "pa_excess_vs_random": s["pa_excess_ann"],
                     "traded_x_book_per_yr": s["turnover"]["traded_x_book_per_yr"], "round_trips_per_yr": s["turnover"]["round_trips_per_yr"],
                     "cost_drag_per_yr": s["turnover"]["cost_drag_per_yr"], "orders_per_week": s["turnover"]["orders_per_week"],
                     "early_exit_share": s["early_exit_share"], "carried_share": s["carried_share"],
                     "beta_adj_alpha_ann": s["paired_vs_E0_beta_adj_alpha_ann"], "beta_adj_alpha_t": s["paired_vs_E0_beta_adj_alpha_t"],
                     "beta_to_EW": s["paired_vs_E0_beta_to_EW"], "by_year_gain": s["paired_vs_E0_by_year"]}
        if "paired_vs_X1" in s:
            A[v][key]["paired_t_vs_X1"] = s["paired_vs_X1"]["nw_t"]
E0 = {key: {"pa_cagr": I2["E0"][key]["pa_cagr"], "pa_maxdd": I2["E0"][key]["pa_maxdd"], **I2["E0"][key]["turnover"],
            "avg_names_held": I2["E0"][key]["avg_names_held"]} for key in ("dev_c50", "hold_c50", "dev_c80", "hold_c80")}
AD = I2["adoption_rule_dev_c50"]
adoption = {"rule": "DEV 50 bps paired NW t >= 2 vs frozen E0 and maxDD not worse by > 3 pp (early exits also vs X1)",
            "mechanical_result": AD, "X2": I2["X2_definition"],
            "adopted": ["X3 executable carry"] if AD["X3"] else [],
            "rejected": [v for v in ("E2w", "E2d", "E3", "S1") if not AD[v]],
            "not_adoptable": {"E1": "passes the statistical rule but its keep/sell decision at the rebalance close uses that close's signal (house rule 6); superseded by X3",
                              "X1": "control (cash yield on idle cash), +0.01%/yr"}}
cap = {"refs": I3["refs"], "crossings_aum_cr": I3["crossings_aum_cr"],
       "liq2_uncapped_Y1_dev_cagr": {a: I3["policies"]["a_liq2"][f"Y1.0_{a}_dev"]["pa_cagr"] for a in ("1cr", "5cr", "20cr", "50cr", "100cr")},
       "liq2_uncapped_Y05_dev_cagr": {a: I3["policies"]["a_liq2"][f"Y0.5_{a}_dev"]["pa_cagr"] for a in ("1cr", "5cr", "20cr", "50cr", "100cr")},
       "liq2_uncapped_Y1_hold_cagr": {a: I3["policies"]["a_liq2"][f"Y1.0_{a}_hold"]["pa_cagr"] for a in ("1cr", "5cr", "20cr", "50cr", "100cr")},
       "liq2_cap5_Y1_dev_cagr": {a: I3["policies"]["b_liq2_cap5"][f"Y1.0_{a}_dev"]["pa_cagr"] for a in ("1cr", "5cr", "20cr", "50cr", "100cr")},
       "liq5_uncapped_Y1_dev_cagr": {a: I3["policies"]["c_liq5"][f"Y1.0_{a}_dev"]["pa_cagr"] for a in ("1cr", "5cr", "20cr", "50cr", "100cr")},
       "zero_impact_dev": {p: I3["policies"][p]["zero_impact_dev"]["pa_cagr"] for p in I3["policies"]},
       "zero_impact_hold": {p: I3["policies"][p]["zero_impact_hold"]["pa_cagr"] for p in I3["policies"]},
       "participation_dev": I3["participation"]["dev"], "participation_hold_20cr": I3["participation"]["hold"]["20cr"],
       "picks_adv_hold": {k: I3["participation"]["hold"][k] for k in ("model_adv_cr_median", "model_adv_cr_mean", "random_adv_cr_median")}}
tax = {nm: {"stcg": {k: I4[nm]["tax_stcg"][k] for k in ("pre_tax_cagr", "post_tax_cagr", "tax_drag_cagr")},
            "business": {k: I4[nm]["tax_business_income"][k] for k in ("pre_tax_cagr", "post_tax_cagr", "tax_drag_cagr")},
            "by_year_stcg": I4[nm]["tax_stcg"]["by_year"]} for nm in ("E0", "X3")}
tax["nifty500_buy_hold"] = I4["nifty500_buy_hold"]
tax["window"] = I4["window"]
variants = {"addon_variants_for_adoption": 7, "list": ["X1", "E1", "X3", "E2w", "E2d", "E3", "S1"],
            "pre_declared": ["E1", "E2w", "E2d", "E3", "S1"], "extras_pre_declared": ["X1"], "extras_post_hoc_disclosed": ["X3"],
            "X2": "conditional, not run", "reproduced_scores_no_selection": 3,
            "capacity_scenario_cells": 40, "diagnostic_baselines": ["random top-20 with X3 timing (5 seeds)"]}
C.save("summary", {"overnight_gap_check": R["item2c_overnight_gap_check"], "headline": H, "addons": A, "E0_baseline": E0, "x3_decomposition": I2b, "adoption": adoption,
                   "capacity": cap, "tax": tax, "variants": variants,
                   "validation": {"booksim_vs_lablib_max_abs_daily_diff": R["booksim_validation"]["worst_max_abs_daily_diff_E0_vs_lablib"],
                                  "contig_E0_vs_item1": R["charts_check"]["E0_contig_booksim_vs_item1_max_abs_diff"]}})
