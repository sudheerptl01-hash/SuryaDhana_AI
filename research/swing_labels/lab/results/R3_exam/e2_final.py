"""R3_exam stage 2: adoption rule on every add-on (from the builders' saved DEV numbers, verified by the verifiers),
SC3 (Sharpe vs cash from R3_twoway series), SC6, imports of verified/corrected numbers with provenance,
expected performance arithmetic, forward-protocol power calculations, final process spec, html_tables, charts."""
import json
import sys

import numpy as np
import pandas as pd
from scipy import stats

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_exam")
R = f"{LAB}/results"
ME = C.load_res()
BK = C.load_res("R3_book")
TW = C.load_res("R3_twoway")
RK = C.load_res("R3_risk")
SN = C.load_res("R3_scen")
DVL = C.load_res("R3_devil")
VB = {k: json.load(open(f"{R}/R3_verify_R3_book/{k}.json")) for k in ("v3_misc", "v4_x3cap")}
VR = json.load(open(f"{R}/R3_verify_R3_risk/v4_out.json"))
VT = json.load(open(f"{R}/R3_verify_R3_twoway/v4_extra.json"))
VT6 = json.load(open(f"{R}/R3_verify_R3_twoway/v6_ytd.json"))
VS4 = json.load(open(f"{R}/R3_verify_R3_scen/v4_results.json"))
EX = ME["exam"]
FWD = ME["forward_estimate"]
SC2 = ME["SC2_D0_avoid_veto"]

# =====================================================================================================
# 1. Adoption rule on every add-on (DEV select; 2026 reported)
# =====================================================================================================
rows = []


def add(src, name, desc, predecl, executable, dev_gain, dev_t, dd_change, h_gain, h_t, decision, reason, baseline="frozen book"):
    passes = bool(dev_t is not None and dev_t >= 2 and dd_change is not None and dd_change >= -0.03)
    rows.append({"source": src, "addon": name, "description": desc, "pre_declared": predecl, "executable": executable,
                 "baseline": baseline, "dev_gain_ann": dev_gain, "dev_nw_t": dev_t, "dev_maxdd_change": dd_change,
                 "hold_gain_ann": h_gain, "hold_nw_t": h_t, "numeric_rule_pass": passes, "decision": decision,
                 "reason": reason})


IE = BK["item2_exits"]
book_desc = {"X1": "idle cash earns the Nifty 1D Rate (control)",
             "E1": "carry as specified: keep re-picked names, decided and traded at the same close",
             "X3": "executable carry: hold through the rebalance close, trade at the next open, keep re-picked names",
             "E2w": "weekly early exit when a held name falls into the PROD avoid tail (<=0.30)",
             "E2d": "daily early exit on the same avoid-tail test",
             "E3": "catastrophe stop: exit next open if close <= 0.75 x entry",
             "S1": "inverse-vol_20 position sizing (cap 2x)"}
for v in ("X1", "E1", "X3", "E2w", "E2d", "E3", "S1"):
    dv, hd = IE[v]["dev_c50"], IE[v]["hold_c50"]
    pr = dv["paired_vs_E0"]
    ph = hd["paired_vs_E0"]
    predecl = {"X1": "yes (declared extra, control)", "X3": "no: disclosed post-hoc extra (executable form of E1)"}.get(v, "yes")
    exe = "no (house rule 6: decides and trades at the same close)" if v == "E1" else "yes"
    if v == "X1":
        dec, why = "passes, immaterial", "t >= 2 but worth about +0.01%/yr; optional operational default (park idle cash in an overnight fund), not an edge"
    elif v == "E1":
        dec, why = "rejected (not executable)", "numeric test passes but the keep/sell decision uses the same close it trades at; superseded by X3"
    elif v == "X3":
        dec, why = ("adopted as the execution convention",
                    "the only executable carry rule; passes t >= 2 and maxDD; about 83% of the gain is the overnight premium that random picks also earn, so skill is measured against a timing-matched random book")
    else:
        dec, why = "rejected", "DEV paired t below 2"
    add("R3_book", v, book_desc[v], predecl, exe, pr["diff_ann"], pr["nw_t"], dv["delta_maxdd_vs_E0"], ph["diff_ann"], ph["nw_t"], dec, why)

S4d, S4h = TW["s4_stats"]["dev|c50"], TW["s4_stats"]["hold|c50"]
tw_desc = {"D1a": "short Nifty 50 futures, hedge ratio 1.0, weekly", "D1b": "short Nifty 50 futures, ex-ante 60-day beta",
           "D1c": "short synthetic Midcap Select futures, ex-ante beta",
           "D2_K10_cash": "F&O long/short K=10, cash long", "D2_K10_fut": "F&O long/short K=10, futures long",
           "D2_K20_cash": "F&O long/short K=20, cash long", "D2_K20_fut": "F&O long/short K=20, futures long",
           "X1_D2_K20_cash_beta": "F&O long/short K=20, beta-matched short (extra)",
           "D3": "frozen book + 50% overlay short of F&O bottom-20", "D4": "F&O short-only bottom-20 on cash collateral"}
# D0 first (judged vs EW in round 2; vs the frozen book it does not apply)
add("R3_twoway", "D0", "avoid veto: equal-weight universe minus PROD bottom 30%", "yes", "yes",
    SC2["dev"]["D0_minus_frozen_book"]["diff_ann"], SC2["dev"]["D0_minus_frozen_book"]["nw_t"],
    S4d["D0"]["maxdd_change_vs_base"], SC2["hold"]["D0_minus_frozen_book"]["diff_ann"], SC2["hold"]["D0_minus_frozen_book"]["nw_t"],
    "not an add-on to the frozen book; kept as the avoid list",
    "vs the equal-weight universe it passes (DEV +3.39%/yr, t 3.51); vs the frozen book it is far lower; the frozen top-20 never holds bottom-30% names, so the veto binds only on names outside the model book")
for v in tw_desc:
    dv = S4d[v]
    add("R3_twoway", v, tw_desc[v], "yes" if v != "X1_D2_K20_cash_beta" else "yes (declared extra)", "yes",
        dv["vs_base"]["diff_ann"], dv["vs_base"]["nw_t"], dv["maxdd_change_vs_base"],
        S4h[v]["vs_base"]["diff_ann"], S4h[v]["vs_base"]["nw_t"], "rejected",
        "DEV paired t below 2 (return cost); hedges are a risk dial only" if v.startswith("D1") else "DEV paired t below 2")
RA = RK["item2_exposure"]["adoption"]
RR = RK["item2_exposure"]["results"]
for v, desc in (("X80", "static 80% invested, rest in Nifty 1D Rate"), ("X60", "static 60% invested, rest in Nifty 1D Rate"),
                ("G50", "breadth governor: 50% invested when breadth50 < 0.5")):
    hp = RR[f"PROD_hold_c50_{v}"]["paired_vs_X100"]
    add("R3_risk", v, desc, "yes", "yes", RA[f"{v}_dev_paired_diff_ann"], RA[f"{v}_dev_paired_nw_t"], RA[f"{v}_dev_maxdd_change"],
        hp["diff_ann"], hp["nw_t"], "rejected" if v == "G50" else "rejected as an add-on (risk-appetite dial only)",
        "DEV paired t below 2; benefit is one sell-off and it whipsawed in 2022" if v == "G50" else "DEV paired t below 2; scales return and drawdown together (Sharpe vs cash unchanged)")
adoption = {"rule": "adopt iff pre-declared (or disclosed extra) AND executable AND DEV paired NW t >= 2 AND maxDD worsens by <= 3 pp (dev_maxdd_change >= -0.03; positive = shallower drawdown)",
            "rows": rows, "n_addons": len(rows),
            "n_numeric_pass": int(sum(r["numeric_rule_pass"] for r in rows)),
            "adopted": [r["addon"] for r in rows if r["decision"].startswith("adopted")],
            "passes_immaterial": [r["addon"] for r in rows if r["decision"].startswith("passes")],
            "rejected": [r["addon"] for r in rows if not (r["decision"].startswith("adopted") or r["decision"].startswith("passes"))],
            "not_run": {"X2": "E1 + best early exit: conditional, not run because no early exit passed (R3_book)"},
            "diagnostics_not_addons": ["B1 vol veto", "B2 beta veto (R3_twoway factor-tilt checks)", "R3_scen: descriptive atlas, no add-ons"]}
X3D = BK["item2b_x3_decomposition"]
adoption["X3_evidence"] = {
    "dev": {"x3_minus_e0": IE["X3"]["dev_c50"]["paired_vs_E0"], "x3_minus_e1": X3D["dev_c50"]["X3_minus_E1"],
            "e1_minus_e0": X3D["dev_c50"]["E1_minus_E0"], "random_timing_gain": X3D["dev_c50"]["random_timing_gain"],
            "x3_vs_timing_matched_random": X3D["dev_c50"]["X3_excess_vs_timing_matched_random"],
            "x3_cagr": IE["X3"]["dev_c50"]["pa_cagr"], "x3_maxdd": IE["X3"]["dev_c50"]["pa_maxdd"],
            "share_of_gain_from_exit_timing": X3D["dev_c50"]["X3_minus_E1"]["diff_ann"] / IE["X3"]["dev_c50"]["paired_vs_E0"]["diff_ann"]},
    "hold": {"x3_minus_e0": IE["X3"]["hold_c50"]["paired_vs_E0"], "random_timing_gain": X3D["hold_c50"]["random_timing_gain"],
             "x3_vs_timing_matched_random": X3D["hold_c50"]["X3_excess_vs_timing_matched_random"],
             "x3_cagr": IE["X3"]["hold_c50"]["pa_cagr"], "x3_maxdd": IE["X3"]["hold_c50"]["pa_maxdd"]},
    "overnight_gap_exit_names": {"dev_mean": BK["item2c_overnight_gap_check"]["dev"]["model_exits"]["mean_gap"],
                                 "dev_by_year_mean": BK["item2c_overnight_gap_check"]["dev"]["model_exits"]["by_year_mean"],
                                 "hold_mean": BK["item2c_overnight_gap_check"]["hold"]["model_exits"]["mean_gap"],
                                 "hold_median": BK["item2c_overnight_gap_check"]["hold"]["model_exits"]["median_gap"],
                                 "hold_share_positive": BK["item2c_overnight_gap_check"]["hold"]["model_exits"]["share_positive"]},
    "provenance": "R3_book results.json item2_exits / item2b_x3_decomposition / item2c_overnight_gap_check; X3 reproduced independently by R3_verify_R3_book (series max abs diff 2.7e-16)"}
C.save("adoption", adoption)

# =====================================================================================================
# 2. SC3 Sharpe vs cash from R3_twoway series; SC6 Nifty 500 TR proxy; spot-check summary
# =====================================================================================================
z = np.load(f"{R}/R3_twoway/series_s3.npz", allow_pickle=True)
keys = [str(k) for k in z["keys"]]
SER = {k: pd.Series(z[f"v{i}"], index=pd.DatetimeIndex(z[f"d{i}"])) for i, k in enumerate(keys)}
cash = SER["CASH1D"]
sc3 = {"frozen_book_my_series": ME["SC3_sharpe_vs_cash"]["frozen_book_my_series"]}
for per in ("dev", "hold"):
    for v in ("BASE", "D1a", "D1b", "D3", "D4"):
        r = SER[f"{v}|{per}|c50"].dropna()
        c = cash.reindex(r.index).fillna(0.0)
        x = r - c
        sc3[f"{v}|{per}"] = {"sharpe_raw": float(r.mean() / r.std() * np.sqrt(252)),
                             "sharpe_vs_cash": float(x.mean() / x.std() * np.sqrt(252))}
sc3["verifier_values_dev"] = {k: VT["sharpe_downmonths|dev"][k]["excess_of_cash_sharpe"] for k in ("BASE", "D1a", "D1b", "D3")}
C.save("SC3_sharpe_vs_cash", sc3)

spot = [
    {"id": "SC1", "flag": "R3_verify_R3_scen: random baseline not reproduced by an independent 100-book simulator (seed noise)",
     "check": "25-seed random top-20 (seeds 1-25), phase-averaged, 50 bps",
     "result": {"dev_random5_cagr": EX["dev_c50"]["random5"]["cagr"], "dev_random25_cagr": EX["dev_c50"]["random25"]["cagr"],
                "dev_ew_cagr": EX["dev_c50"]["ew"]["cagr"], "hold_random5_cagr": EX["hold_c50"]["random5"]["cagr"],
                "hold_random25_cagr": EX["hold_c50"]["random25"]["cagr"], "hold_ew_cagr": EX["hold_c50"]["ew"]["cagr"],
                "dev_random5_minus_random25_ann": EX["dev_c50"]["random5_minus_random25_ann"],
                "hold_random5_minus_random25_ann": EX["hold_c50"]["random5_minus_random25_ann"],
                "PROD_hold_excess_vs_random25": EX["hold_c50"]["PROD"]["excess_vs_random25_ann"],
                "PROD_hold_t_vs_random25": EX["hold_c50"]["PROD"]["nw_t_vs_random25"],
                "verifier_100book_dev": VS4.get("B_own_sim", {}).get("h20_c50_dev", None) if isinstance(VS4.get("B_own_sim"), dict) else None},
     "verdict": "confirmed: the pre-registered 5-seed random sits above its expectation (25-seed and EW agree); PROD's 2026 excess is about +1.8%/yr against the better baseline instead of +0.4%; still far from significant"},
    {"id": "SC2", "flag": "R3_verify_R3_twoway: D0 passes only against EW, not against the frozen book",
     "check": "D0 re-run phase-averaged vs EW and vs the frozen book",
     "result": SC2, "verdict": "confirmed: D0 vs EW DEV +3.39%/yr (t 3.51), 2026 +1.48% (t 1.07); D0 minus frozen book DEV -12.66%/yr (t -3.83). The avoid list is a veto, not an add-on"},
    {"id": "SC3", "flag": "R3_verify_R3_twoway: 'Sharpe unchanged' with index hedges holds only for raw Sharpe",
     "check": "Sharpe in excess of the Nifty 1D Rate: frozen book from my series, hedges from R3_twoway's series",
     "result": sc3, "verdict": "confirmed: in excess of cash the hedges lower DEV Sharpe (BASE 1.15 vs D1a 1.05, D1b 0.95)"},
    {"id": "SC4", "flag": "R3_verify_R3_scen: NW lag-20 t can be inflated on overlapping data",
     "check": "book-level PROD excess t with NW lags 20/40/60 and non-overlapping 20-day blocks",
     "result": {"dev": EX["dev_c50"]["PROD"]["SC4_t_lag"], "hold": EX["hold_c50"]["PROD"]["SC4_t_lag"]},
     "verdict": "book-level t is robust: DEV 3.97 (lag 20), 3.64 (40), 3.44 (60), 3.93 non-overlapping; 2026 near 0 under every choice"},
    {"id": "SC5", "flag": "R3_verify_R3_risk: a live single-phase book is noisier than the phase average",
     "check": "tracking error vs 5-seed random: each entry phase vs the phase average",
     "result": {"dev": EX["dev_c50"]["PROD"]["SC5_tracking_error"], "hold": EX["hold_c50"]["PROD"]["SC5_tracking_error"],
                "verifier_single_phase_p_neg_year_plus5": VR["single_phase_mean"]["p_neg_year_plus5"]},
     "verdict": "confirmed: single-phase tracking error about 7.1% (DEV) and 7.7% (2026) vs 6.4% / 7.1% phase-averaged; quote client odds with the single-phase numbers"},
    {"id": "SC6", "flag": "R3_verify_R3_book: Nifty 500 is a price index; capacity crossings should use a dividend proxy",
     "check": "Nifty 500 price CAGR on the exam calendars, +1.2%/yr total-return proxy",
     "result": {"dev_price": EX["dev_c50"]["nifty500_price"]["cagr"], "dev_tr_proxy": EX["dev_c50"]["nifty500_tr_proxy_cagr"],
                "hold_price": EX["hold_c50"]["nifty500_price"]["cagr"], "hold_tr_proxy": EX["hold_c50"]["nifty500_tr_proxy_cagr"],
                "verifier_E0_crossing_vs_TR_cr": VB["v4_x3cap"]["crossings"]["E0_uncapped_vs_N500TR"],
                "verifier_E0_cap5_crossing_vs_TR_cr": VB["v4_x3cap"]["crossings"]["E0_cap5_vs_N500TR_(5cr point = uncapped)"]},
     "verdict": "confirmed: DEV TR proxy 17.99% (price 16.59%); the frozen book's DEV capacity against a dividend-inclusive Nifty 500 is about Rs 19-21 cr"},
    {"id": "SC7", "flag": "all verifiers: headline book numbers",
     "check": "own phase loop vs C.phase_avg and vs R3_book's reported values",
     "result": {"dev_check": EX["dev_c50"]["check_vs_C_phase_avg"], "hold_check": EX["hold_c50"]["check_vs_C_phase_avg"]},
     "verdict": "exact (max abs daily diff 0.0); PROD DEV +15.30%/yr (t 3.97), 2026 +0.41%/yr (t 0.06) reproduced"},
]
C.save("spot_checks", spot)

# =====================================================================================================
# 3. Imports (verified numbers, with corrections applied) for the process / expectations
# =====================================================================================================
E0b = BK["summary"]["E0_baseline"]
x3dev = IE["X3"]["dev_c50"]
imp = {
    "provenance": "copied from builder/verifier results.json files (paths in each key); all re-computed by a verifier unless marked",
    "ops_E0_dev": {k: E0b["dev_c50"][k] for k in ("traded_x_book_per_yr", "round_trips_per_yr", "orders_per_week", "cost_drag_per_yr", "avg_names_held")},
    "ops_E0_hold": {k: E0b["hold_c50"][k] for k in ("traded_x_book_per_yr", "round_trips_per_yr", "orders_per_week", "cost_drag_per_yr", "avg_names_held")},
    "ops_E0_dev_c80_cost_drag": E0b["dev_c80"]["cost_drag_per_yr"],
    "ops_X3_dev": {"turnover_x_book": x3dev["turnover"] if not isinstance(x3dev["turnover"], dict) else x3dev["turnover"]},
    "capacity_E0_dev_Y1_liq2_uncapped": BK["summary"]["capacity"]["curves"] if "curves" in BK["summary"]["capacity"] else None,
    "capacity_crossings_verifier": VB["v4_x3cap"]["crossings"],
    "capacity_X3_curves_verifier": VB["v4_x3cap"]["x3_curves"],
    "capacity_targets_verifier": VB["v4_x3cap"]["targets"],
    "capacity_E0_crossings_book": {k: BK["item3_capacity"]["crossings_aum_cr"][k] for k in ("a_liq2_Y1.0_dev", "b_liq2_cap5_Y1.0_dev", "a_liq2_Y1.0_hold")},
    "participation_20cr_dev": {k: BK["item3_capacity"]["participation"]["dev"]["20cr"][k] for k in ("position_lakh", "median_participation", "share_gt10pct", "impact_bps_side_Y1_mean")},
    "tax_with_cess_verifier": VB["v3_misc"]["tax_cess"],
    "tax_business_income_book": {"E0": BK["summary"]["tax"]["E0"]["business"], "X3": BK["summary"]["tax"]["X3"]["business"]},
    "risk_expectations_b40_plus5": {"p_negative_excess_year": RK["item3_expectations"]["dev_b40_t5"]["p_negative_excess_year"],
                                    "p_at_least_one_negative_year_in_2": RK["item3_expectations"]["dev_b40_t5"]["p_at_least_one_negative_year_in_2"],
                                    "excess_12m": RK["item3_expectations"]["dev_b40_t5"]["excess_12m"],
                                    "absolute_12m": RK["item3_expectations"]["dev_b40_t5"]["absolute_12m"],
                                    "maxdd_24m": RK["item3_expectations"]["dev_b40_t5"]["maxdd_24m"]},
    "risk_dead_book_p_above_plus5": RK["item3_expectations"]["dev_b40_t0"]["excess_12m"]["p_above_plus5"],
    "risk_single_phase_verifier": VR["single_phase_mean"],
    "risk_K3_fire_prob_given_path_verifier": VR["K3_fire_prob_given_realised_path"],
    "kill_rules_b40_H1a": RK["item4_kill_bootstrap"]["b40_H1a"], "kill_rules_b40_H0": RK["item4_kill_bootstrap"]["b40_H0"],
    "kill_rules_b40_H1b_C2": RK["item4_kill_bootstrap"]["b40_H1b"]["C2_kill"],
    "kill_last_check": RK["item4_kill_historical"]["last_check"],
    "monitor_dev_ic_rolling13w": RK["item4_monitor_metrics"]["dev"]["ic"]["rolling13w"],
    "monitor_dev_rel_hit_weekly": RK["item4_monitor_metrics"]["dev"]["rel_hit"]["weekly"],
    "slippage_budget": RK["item4_slippage_budget"],
    "ew_pre_2021_09_2022_12": {k: RR["EW_pre_c50_X100"][k] for k in ("cagr", "maxdd")},
    "risk_worst_drawdown_episode": RK["item1_drawdowns"]["top5"][0] if isinstance(RK["item1_drawdowns"]["top5"], list) else None,
    "twoway_2026_ytd_verifier": VT6,
    "twoway_D4": {"dev_cagr": S4d["D4"]["cagr"], "hold_cagr": S4h["D4"]["cagr"], "dev_maxdd": S4d["D4"]["maxdd"]},
    "twoway_D1b": {"dev_cagr": S4d["D1b"]["cagr"], "dev_maxdd": S4d["D1b"]["maxdd"], "hold_cagr": S4h["D1b"]["cagr"]},
    "twoway_veto_5factor_residual_verifier": {"dev_ann": VT["multifactor|dev"]["resid_alpha_ann_insample"], "dev_t": VT["multifactor|dev"]["resid_alpha_t_insample"]},
    "scen_key": {k: SN["key_numbers"][k] for k in ("clean_sign_h20_corr_same_window", "xr_neumom_h20_corr_same_window", "dual_h20_corr_same_window")},
    "devil_planning": {"bonf_haircut_programme_N": DVL["s5_dsr"]["hlz_bonferroni_haircut_phaseavg_dev"]["programme_total"]["N"]},
}
C.save("imported", imp)

# =====================================================================================================
# 4. Expected performance (plain numbers) — arithmetic on the numbers above
# =====================================================================================================
fp = FWD["PROD"]
prim = fp["random5"]["bonf_haircut_programme"]
z90 = float(stats.norm.ppf(0.95))
exp_ = {"forward_excess_vs_random5": prim["combined"], "forward_se": prim["combined_se"],
        "forward_90lo": prim["combined"] - z90 * prim["combined_se"], "forward_90hi": prim["combined"] + z90 * prim["combined_se"],
        "forward_excess_vs_ew": fp["ew"]["bonf_haircut_programme"]["combined"],
        "forward_se_vs_ew": fp["ew"]["bonf_haircut_programme"]["combined_se"],
        "forward_90lo_vs_ew": fp["ew"]["bonf_haircut_programme"]["combined"] - z90 * fp["ew"]["bonf_haircut_programme"]["combined_se"],
        "forward_90hi_vs_ew": fp["ew"]["bonf_haircut_programme"]["combined"] + z90 * fp["ew"]["bonf_haircut_programme"]["combined_se"],
        "forward_excess_vs_random25": fp["random25"]["bonf_haircut_programme"]["combined"],
        "forward_excess_vs_random5_upperN": fp["random5"]["bonf_haircut_upper"]["combined"],
        "forward_excess_vs_random5_no_haircut": fp["random5"]["raw_dev"]["combined"],
        "p_edge_positive": fp["random5"]["p_combined_gt0_primary"],
        "x3_overnight_premium_random_dev": X3D["dev_c50"]["random_timing_gain"]["diff_ann"],
        "x3_overnight_premium_random_hold": X3D["hold_c50"]["random_timing_gain"]["diff_ann"],
        "cost_drag_E0_dev": E0b["dev_c50"]["cost_drag_per_yr"],
        "tax_drag_E0_stcg_with_cess": VB["v3_misc"]["tax_cess"]["E0"]["drag_with_cess"],
        "tax_drag_X3_stcg_with_cess": VB["v3_misc"]["tax_cess"]["X3"]["drag_with_cess"]}
scen_mk = {"like_2023_25_ew": EX["dev_c50"]["ew"]["cagr"], "like_2026_ew": EX["hold_c50"]["ew"]["cagr"],
           "like_2021_22_ew": RR["EW_pre_c50_X100"]["cagr"]}
grid = {}
for mk, ew in scen_mk.items():
    grid[mk] = {"ew_cagr": ew, "book_no_edge": ew, "book_conservative_plan": ew + exp_["forward_excess_vs_random5"],
                "book_forward_low90": ew + exp_["forward_90lo_vs_ew"],
                "book_forward_central": ew + exp_["forward_excess_vs_ew"], "book_forward_high90": ew + exp_["forward_90hi_vs_ew"],
                "book_central_plus_x3_premium_2026": ew + exp_["forward_excess_vs_ew"] + exp_["x3_overnight_premium_random_hold"],
                "book_central_after_stcg_tax": ew + exp_["forward_excess_vs_ew"] - exp_["tax_drag_E0_stcg_with_cess"]}
exp_["absolute_grid_additive"] = grid
exp_["note"] = ("book ~ equal-weight-universe return + lead over equal weight (additive approximation, pre-tax, after 50 bps costs, E0 timing). "
                "Market scenarios use the equal-weight tradable universe's realised CAGR in 2023-25, 2026 and 2021-09..2022-12. The range is the 90% "
                "interval of the precision-weighted forward estimate vs EW. X3 execution adds the overnight premium on top (2026: +2.1%/yr for random picks).")
C.save("expected_performance", exp_)

# =====================================================================================================
# 5. Forward protocol: power of the fresh-data exam (normal approximation)
# =====================================================================================================
te_candidates = {"dev_phaseavg_iid": EX["dev_c50"]["PROD"]["SC5_tracking_error"]["phase_avg"],
                 "hold_phaseavg_iid": EX["hold_c50"]["PROD"]["SC5_tracking_error"]["phase_avg"],
                 "dev_nw_implied": EX["dev_c50"]["PROD"]["se_vs_random5_ann"] * np.sqrt(EX["dev_c50"]["n_days"] / 252),
                 "hold_nw_implied": EX["hold_c50"]["PROD"]["se_vs_random5_ann"] * np.sqrt(EX["hold_c50"]["n_days"] / 252)}
TE = float(max(te_candidates.values()))
prior_m, prior_se = prim["combined"], prim["combined_se"]
power = {"te_used": TE, "te_candidates": te_candidates, "prior_mean": prior_m, "prior_se": prior_se, "rows": []}
for months in (6, 12, 18, 24, 36, 48):
    T = months / 12
    se_f = TE / np.sqrt(T)
    wp, wf = 1 / prior_se ** 2, 1 / se_f ** 2
    post_se = np.sqrt(1 / (wp + wf))
    row = {"months": months, "fresh_se": float(se_f), "posterior_se": float(post_se)}
    thr_post = max(((z90 * post_se) * (wp + wf) - prior_m * wp) / wf, 0.0)
    thr_conf = z90 * se_f
    thr_rej = prior_m - z90 * np.sqrt(se_f ** 2 + prior_se ** 2)
    row.update({"fresh_threshold_confirm": float(thr_conf), "fresh_threshold_plan_reject": float(thr_rej),
                "fresh_threshold_posterior_confirm": float(thr_post)})
    for lab, mu in (("mu0", 0.0), ("mu_plan", prior_m), ("mu_ew_est", fp["ew"]["bonf_haircut_programme"]["combined"])):
        row[f"p_fresh_pos_{lab}"] = float(stats.norm.sf(0, loc=mu, scale=se_f))
        # clean exam: fresh-only one-sided 5% test
        row[f"p_confirm_{lab}"] = float(stats.norm.sf(thr_conf, loc=mu, scale=se_f))
        # plan rejected: fresh lead significantly below the planning estimate
        row[f"p_plan_reject_{lab}"] = float(stats.norm.cdf(thr_rej, loc=mu, scale=se_f))
        # diagnostic: prior+fresh posterior z > 1.645 (leans on the in-sample prior)
        row[f"p_posterior_confirm_{lab}"] = float(stats.norm.sf(thr_post, loc=mu, scale=se_f))
    power["rows"].append(row)
power["mu_values"] = {"mu0": 0.0, "mu_plan": prior_m, "mu_ew_est": fp["ew"]["bonf_haircut_programme"]["combined"]}
power["note"] = ("Normal approximation. Clean exam = fresh data only (after 2026-10-14), one-sided 5%: confirmed if fresh lead > 1.645 x fresh s.e. "
                 "Plan rejected if fresh lead < planning estimate - 1.645 x sqrt(fresh s.e.^2 + prior s.e.^2). The posterior rule leans on the "
                 "in-sample prior and has a 14-16% false-confirm rate at zero edge, so it is only used to update the planning number.")
k_chal = 4
power["challenger_t_threshold_bonferroni_k4"] = float(stats.norm.ppf(1 - 0.05 / k_chal))
C.save("forward_power", power)

# =====================================================================================================
# 6. html_tables
# =====================================================================================================
H = EX["hold_c50"]
D = EX["dev_c50"]
H8 = EX["hold_c80"]
D8 = EX["dev_c80"]
T = []
cols1 = ["Book", "Annualised return", "Return over the period", "Lead over random picks (per yr)", "t-stat", "Lead over all-stock equal weight (per yr)", "t-stat (vs equal weight)", "Lead over 25-seed random (per yr)", "Worst fall", "Sharpe", "Annualised return at 0.8% cost"]


def exam_rows(B, B8):
    rws = []
    for nm, lab in (("PROD", "PROD book (frozen production score) - the exam"), ("single", "Single model (devil's)"), ("ens3", "3-seed ensemble")):
        s = B[nm]
        rws.append([lab, s["cagr"], s["total_return"], s["excess_vs_random5_ann"], s["nw_t_vs_random5"], s["excess_vs_ew_ann"],
                    s["nw_t_vs_ew"], s.get("excess_vs_random25_ann"), s["maxdd"], s["sharpe"], B8[nm]["cagr"]])
    rws.append(["Random 20 stocks, 5 seeds (pre-registered yardstick)", B["random5"]["cagr"], B["random5"]["total_return"], None, None, None, None, None, B["random5"]["maxdd"], B["random5"]["sharpe"], B8["random5"]["cagr"]])
    rws.append(["Random 20 stocks, 25 seeds (spot-check)", B["random25"]["cagr"], B["random25"]["total_return"], None, None, None, None, None, B["random25"]["maxdd"], B["random25"]["sharpe"], None])
    rws.append(["All tradable stocks, equal weight", B["ew"]["cagr"], B["ew"]["total_return"], None, None, None, None, None, B["ew"]["maxdd"], B["ew"]["sharpe"], B8["ew"]["cagr"]])
    rws.append(["Nifty 500 (price index, no dividends)", B["nifty500_price"]["cagr"], B["nifty500_price"]["total_return"], None, None, None, None, None, B["nifty500_price"]["maxdd"], B["nifty500_price"]["sharpe"], None])
    rws.append(["Overnight cash (Nifty 1D Rate)", B["cash_1d_rate"]["cagr"], B["cash_1d_rate"]["total_return"], None, None, None, None, None, None, None, None])
    return rws


T.append(C.table("1. Final exam: the frozen process in 2026 (7 Jan - 7 Oct 2026, never used to choose anything)", cols1, exam_rows(H, H8),
                 "Weekly book of the 20 top-scored stocks, 4 overlapping sleeves, 20-day holds, 0.5% round-trip cost (0.8% stress in the last column), averaged over the 5 possible weekday entry schedules. "
                 "'Lead' = average daily return difference x 252. A t-stat below 2 means the lead cannot be told apart from luck. The 2026 window is only 185 trading days."))
T.append(C.table("2. For reference: the same books in 2023-2025 (the period used to build and select everything)", cols1, exam_rows(D, D8),
                 "These numbers are in-sample for the selection process (about 2,000 variants were tried across the programme), so they overstate what to expect."))
T.append(C.table("3. Is the 2026 yardstick lucky? Random picks with 5 vs 25 random seeds",
                 ["Period", "Random 20 (5 seeds)", "Random 20 (25 seeds)", "All stocks equal weight", "5-seed minus 25-seed (per yr)", "PROD lead vs 5-seed random", "PROD lead vs 25-seed random", "t-stat vs 25-seed"],
                 [["2023-2025", D["random5"]["cagr"], D["random25"]["cagr"], D["ew"]["cagr"], D["random5_minus_random25_ann"], D["PROD"]["excess_vs_random5_ann"], D["PROD"]["excess_vs_random25_ann"], D["PROD"]["nw_t_vs_random25"]],
                  ["2026 (Jan-Oct)", H["random5"]["cagr"], H["random25"]["cagr"], H["ew"]["cagr"], H["random5_minus_random25_ann"], H["PROD"]["excess_vs_random5_ann"], H["PROD"]["excess_vs_random25_ann"], H["PROD"]["nw_t_vs_random25"]]],
                 "The pre-registered 5-seed random book happened to land above its average in 2026; with 25 seeds it matches the equal-weight universe, as theory says it should. Against the better yardstick PROD led by about 1.8%/yr in 2026 - still well inside luck."))
fr = []
for base, lab in (("random5", "random 20 (5 seeds, pre-registered)"), ("ew", "all stocks equal weight"), ("random25", "random 20 (25 seeds)")):
    f = fp[base]
    fr.append([lab, f["dev_excess"], f["haircut_programme"]["haircut_excess_ann"], f["dev_se"], f["hold_excess"], f["hold_se"],
               f["bonf_haircut_programme"]["weight_hold"], f["bonf_haircut_programme"]["combined"], f["bonf_haircut_programme"]["combined_se"],
               f["raw_dev"]["combined"], f["z_hold_vs_dev_raw"], f["z_hold_vs_dev_haircut"]])
T.append(C.table("4. Best estimate of the forward edge of the PROD book (precision-weighted)",
                 ["Measured against", "2023-25 lead", "2023-25 lead after multiple-testing haircut", "Uncertainty (1 s.e.) 2023-25", "2026 lead", "Uncertainty (1 s.e.) 2026",
                  "Weight given to 2026", "Forward estimate (central)", "Forward estimate s.e.", "Forward estimate with no haircut", "2026 vs raw 2023-25 (z)", "2026 vs haircut 2023-25 (z)"],
                 fr, "The 2023-25 lead is cut by a Bonferroni haircut for the ~1,991 variants tried in the programme, then averaged with 2026, each weighted by its precision. "
                     "The 2026 result is about 1.9 standard errors below the raw 2023-25 lead but consistent with the haircut one."))
ad_rows = [[r["addon"], r["source"], r["description"], r["pre_declared"], r["executable"], r["dev_gain_ann"], r["dev_nw_t"], r["dev_maxdd_change"],
            r["hold_gain_ann"], r["hold_nw_t"], "yes" if r["numeric_rule_pass"] else "no", r["decision"]] for r in rows]
T.append(C.table("5. Every add-on tested in round 3 against the pre-registered adoption rule",
                 ["Add-on", "Tested by", "What it does", "Declared in advance?", "Can it be traded as specified?", "Gain vs frozen book 2023-25 (per yr)", "t-stat",
                  "Change in worst fall (+ = shallower)", "Gain in 2026 (report only)", "t-stat 2026", "Passes the numeric rule?", "Decision"],
                 ad_rows, "Rule (PREREG): adopt only if the 2023-25 gain over the frozen book has t >= 2 and the worst fall is not more than 3 points deeper. 2026 is shown but never used to decide. "
                          "D0 is the avoid list measured against the frozen book; against the equal-weight universe it adds +3.39%/yr (t 3.51)."))
sc_rows = [[s["id"], s["flag"], s["check"], s["verdict"]] for s in spot]
T.append(C.table("6. What the verifiers flagged, and what my own re-runs found", ["Check", "Flag raised", "What I re-ran", "Finding"], sc_rows,
                 "All headline numbers of the four round-3 teams were re-computed by independent verifiers; I re-ran the flagged items myself."))
proc = [
    ["Label (what the model learns)", "XR_neumom, 20 days: each day, rank stocks by their next-open-to-20-day-close return after removing what beta, volatility, size (turnover) and 12-1 momentum explain. Top 30% = +1, bottom 30% = -1 (for reporting)."],
    ["Score", "PROD: average rank of 10 LightGBM models (5 seeds x 2 date halves), 55 point-in-time features, retrained once a year on all data up to 22 trading days before 1 January."],
    ["Universe", "NSE EQ-series equities with price >= Rs 20, 20-day turnover >= Rs 2 cr, >= 120 trading days of history, not circuit-locked, ATR 0.5-15%."],
    ["Book", "One fixed weekday: after the close, rank the universe. Capital is split into 4 sleeves (25% each); each week one sleeve is renewed. A sleeve holds the top 20 names, 1/20 of the sleeve each (about 80 slots, about 74 names held). Hold 20 trading days."],
    ["Entries and exits (adopted X3 timing)", "At a sleeve's renewal, keep names that are still in its new top 20; sell the rest and buy the new names in the next morning's opening session (pre-open auction). No stops, no early exits, no volatility-based sizing (all rejected)."],
    ["Avoid veto (the -1 side)", "Bottom 30% of PROD on the signal day is a do-not-buy list for anything outside the model book (own ideas, tips). Never short it in cash; F&O shorts lost money and are not used."],
    ["Exposure and hedge", "Fully invested. Holding 80% or 60% (rest in an overnight fund) is allowed purely as a risk-appetite dial; no market-timing governor; a Nifty futures hedge is optional and costs about 8-9%/yr in a rising market."],
    ["Capacity", "At most about Rs 20 cr; each order <= 5% of the stock's 20-day median traded value (excess stays in cash)."],
    ["Costs", "Budget 0.5% round trip (0.223% statutory + up to 0.14% slippage per side vs the official open); stress test 0.8%."],
    ["Monitoring", "Weekly dashboard; review if any of: 6-month lead < -5%, 3-month IC < 0.02, 12-month lead < 0. Stop new entries only if the 12-month lead < 0 AND the 3-month IC < 0.02 at the same weekly check."],
]
T.append(C.table("7. The final investment process (what the trader does each week)", ["Element", "Rule"], proc,
                 "Everything except the X3 execution timing was frozen before round 3. X3 is a disclosed post-hoc execution convention; skill is always judged against random picks traded with the same timing."))
g = exp_["absolute_grid_additive"]
ep = [["Expected lead over random picks of the same style (per yr, central)", exp_["forward_excess_vs_random5"]],
      ["  90% range of that lead: low", exp_["forward_90lo"]], ["  90% range of that lead: high", exp_["forward_90hi"]],
      ["Expected lead over the equal-weight universe (per yr)", exp_["forward_excess_vs_ew"]],
      ["  90% range of that lead: low", exp_["forward_90lo_vs_ew"]], ["  90% range of that lead: high", exp_["forward_90hi_vs_ew"]],
      ["Chance the true lead over random picks is above zero", exp_["p_edge_positive"]],
      ["Extra return from opening-session execution (X3), measured on random picks, 2023-25 (per yr)", exp_["x3_overnight_premium_random_dev"]],
      ["  same, 2026 (per yr)", exp_["x3_overnight_premium_random_hold"]],
      ["Trading-cost drag already deducted (per yr, 0.5% round trip)", exp_["cost_drag_E0_dev"]],
      ["Short-term capital-gains tax drag incl. 4% cess (per yr)", exp_["tax_drag_E0_stcg_with_cess"]],
      ["If small caps repeat 2023-25: equal-weight universe", g["like_2023_25_ew"]["ew_cagr"]], ["  book, conservative (+4.4% lead)", g["like_2023_25_ew"]["book_conservative_plan"]], ["  book, central (+6.9% lead)", g["like_2023_25_ew"]["book_forward_central"]],
      ["If the market repeats 2026: equal-weight universe", g["like_2026_ew"]["ew_cagr"]], ["  book, conservative (+4.4% lead)", g["like_2026_ew"]["book_conservative_plan"]], ["  book, central (+6.9% lead)", g["like_2026_ew"]["book_forward_central"]],
      ["If the market repeats Sep-2021..2022: equal-weight universe", g["like_2021_22_ew"]["ew_cagr"]], ["  book, conservative (+4.4% lead)", g["like_2021_22_ew"]["book_conservative_plan"]], ["  book, central (+6.9% lead)", g["like_2021_22_ew"]["book_forward_central"]],
      ["Chance of a losing 12 months (planned edge, 2023-25 market drift)", imp["risk_expectations_b40_plus5"]["absolute_12m"]["p_neg"]],
      ["Chance of trailing random picks over a calendar year (live single schedule)", imp["risk_single_phase_verifier"]["p_neg_year_plus5"]],
      ["Typical worst fall over 2 years (median)", imp["risk_expectations_b40_plus5"]["maxdd_24m"]["p50"]],
      ["Chance the worst fall over 2 years is deeper than -30%", imp["risk_expectations_b40_plus5"]["maxdd_24m"]["p_worse_than_minus30"]],
      ["Worst fall seen 2023-25 (Dec-2024 to Mar-2025)", D["PROD"]["maxdd"]]]
T.append(C.table("8. What to expect, in plain numbers (pre-tax unless stated, after 0.5% costs)", ["Item", "Value"], ep,
                 "Book return is approximated as the equal-weight universe return plus the lead. The market scenarios are history, not forecasts; 2023-25 was an unusually strong small-cap period."))
kr = imp["kill_rules_b40_H1a"]
k0 = imp["kill_rules_b40_H0"]
mon = [["K1 review: 6-month lead over random < -5%", kr["K1"]["p_fire_24m"], k0["K1"]["p_fire_24m"], k0["K1"]["median_first_fire_days"]],
       ["K2 review: 3-month average matured IC < 0.02", kr["K2"]["p_fire_24m"], k0["K2"]["p_fire_24m"], k0["K2"]["median_first_fire_days"]],
       ["K3 review: 12-month lead over random < 0", kr["K3"]["p_fire_24m"], k0["K3"]["p_fire_24m"], k0["K3"]["median_first_fire_days"]],
       ["Any review (K1 or K2 or K3)", kr["C1_review"]["p_fire_24m"], k0["C1_review"]["p_fire_24m"], k0["C1_review"]["median_first_fire_days"]],
       ["KILL: K3 and K2 at the same weekly check", kr["C2_kill"]["p_fire_24m"], k0["C2_kill"]["p_fire_24m"], k0["C2_kill"]["median_first_fire_days"]]]
T.append(C.table("9. Review and kill rules: false alarms vs detection in the first 24 months", ["Rule", "False alarm for a good book (+5%/yr)", "Detection of a dead book (0%/yr)", "Typical trading days to detect"], mon,
                 "Calibrated by R3_risk with a 40-day block bootstrap (verified). A review means investigate, not stop. Probability that K3 triggers a review by 31-Mar-2027 given the path so far: "
                 f"{imp['risk_K3_fire_prob_given_path_verifier']['plan_5pct']['2027-03-31']} under the planned edge."))
pw = [[r["months"], r["fresh_se"], r["p_fresh_pos_mu_plan"], r["p_confirm_mu0"], r["p_confirm_mu_plan"], r["p_confirm_mu_ew_est"],
       r["p_plan_reject_mu_plan"], r["p_plan_reject_mu0"], r["p_posterior_confirm_mu0"]] for r in power["rows"]]
T.append(C.table("10. How quickly can fresh data settle the question? (forward exam power)",
                 ["Months of fresh data", "Uncertainty of the fresh lead (1 s.e.)", "P(fresh lead > 0) at the planning edge",
                  "P(confirmed) if there is no edge", "P(confirmed) at the planning edge (+4.4%/yr)", "P(confirmed) at +6.9%/yr",
                  "P(plan rejected) at the planning edge", "P(plan rejected) if there is no edge", "P(prior+fresh 'confirmed') if no edge (not used)"], pw,
                 "Confirmed = the fresh-data lead alone is significant (one-sided 5%). Plan rejected = the fresh lead is significantly below the planning edge. "
                 "Normal approximation with the largest measured tracking error. Even a real edge needs several years of fresh data to be confirmed; the kill rule (table 9) is the fast safety net."))
chal = [["Single model (devil recipe)", "model averaging check", "paired lead vs PROD"],
        ["3-seed ensemble", "model averaging check", "paired lead vs PROD"],
        ["E2w weekly avoid-tail exit", "de-risking (shallower falls in 2023-25)", "paired lead and worst fall vs PROD book"],
        ["liq5 universe (turnover >= Rs 5 cr)", "capacity", "lead vs its own random picks; impact-adjusted"]]
T.append(C.table("11. Challengers: tracked only on data after 14-Oct-2026, never on history", ["Challenger", "Why", "Measured as"], chal,
                 f"A challenger replaces the incumbent only after >= 24 months of fresh data with a paired t >= {power['challenger_t_threshold_bonferroni_k4']:.2f} (Bonferroni for 4 challengers) and a worst fall no more than 3 points deeper."))
C.save("html_tables", T)

# =====================================================================================================
# 7. charts
# =====================================================================================================
S_ = np.load(f"{OUT}/exam_series.npz", allow_pickle=True)


def growth(per, cname, keys_, freq):
    dts = pd.DatetimeIndex(S_[f"{per}_{cname}_dates"])
    df = pd.DataFrame({k: S_[f"{per}_{cname}_{k}"] if k != "random25" else S_[f"{per}_random25"] for k in keys_}, index=dts)
    eq = (1 + df).cumprod()
    eq = eq.resample(freq).last()
    return [str(x)[:10] for x in eq.index], {k: [float(v) for v in eq[k].values] for k in keys_}


names = {"PROD": "PROD book", "single": "Single model", "random5": "Random 20 (5 seeds)", "random25": "Random 20 (25 seeds)", "ew": "All stocks equal weight", "n500": "Nifty 500 (price)"}
ch = {}
x, sr = growth("hold", "c50", ["PROD", "single", "random5", "random25", "ew", "n500"], "W-FRI")
ch["exam_2026_growth_weekly"] = {"type": "line", "x": x, "series": {names[k]: v for k, v in sr.items()},
                                 "note": "Growth of Rs 1 in 2026 (fresh-start books from 7 Jan, weekly points, after 0.5% costs). The PROD book ended level with random picks and slightly above the equal-weight universe; the Nifty 500 fell."}
x, sr = growth("dev", "c50", ["PROD", "single", "random5", "random25", "ew", "n500"], "ME")
ch["exam_dev_growth_monthly"] = {"type": "line", "x": x, "series": {names[k]: v for k, v in sr.items()},
                                 "note": "Growth of Rs 1 over 2023-2025 (monthly points). This is the selection period, so the gap overstates the future edge."}
ch["exam_lead_dev_vs_2026"] = {"type": "bar", "x": ["2023-25 vs random (5 seeds)", "2023-25 vs equal weight", "2026 vs random (5 seeds)", "2026 vs equal weight", "2026 vs random (25 seeds)"],
                               "series": {lab: [EX["dev_c50"][nm]["excess_vs_random5_ann"], EX["dev_c50"][nm]["excess_vs_ew_ann"], EX["hold_c50"][nm]["excess_vs_random5_ann"],
                                                EX["hold_c50"][nm]["excess_vs_ew_ann"], EX["hold_c50"][nm]["excess_vs_random25_ann"]]
                                          for nm, lab in (("PROD", "PROD"), ("single", "Single model"), ("ens3", "3-seed ensemble"))},
                               "note": "Yearly lead of each score's book over the yardsticks. Big in 2023-25, close to zero in 2026 for PROD and the 3-seed ensemble; the single model's 2026 lead (+3.9%) is not significant (t 0.6)."}
ch["forward_estimate"] = {"type": "bar", "x": ["2023-25 lead (raw)", "2023-25 lead after haircut", "2026 lead", "Forward estimate (central)", "Forward estimate, no haircut"],
                          "series": {base: [fp[base]["dev_excess"], fp[base]["haircut_programme"]["haircut_excess_ann"], fp[base]["hold_excess"],
                                            fp[base]["bonf_haircut_programme"]["combined"], fp[base]["raw_dev"]["combined"]]
                                     for base in ("random5", "ew", "random25")},
                          "note": "How the forward estimate is built (per year): the 2023-25 lead is cut for multiple testing, then averaged with 2026 by precision. Series = the yardstick used."}
ch["addon_gain_dev"] = {"type": "bar", "x": [r["addon"] for r in rows], "series": {"Gain vs frozen book 2023-25 (per yr)": [r["dev_gain_ann"] for r in rows],
                                                                                 "t-stat / 100": [r["dev_nw_t"] / 100 for r in rows]},
                        "note": "Every add-on's 2023-25 gain over the frozen book (t-stat divided by 100 so it fits the same axis; adoption needs t >= 2, i.e. >= 0.02 here). Only X3 (execution timing) and the trivial X1 clear it; E1 clears it but cannot be traded as specified."}
ch["phase_lead_2026"] = {"type": "bar", "x": [f"Entry weekday schedule {k + 1}" for k in range(5)],
                         "series": {lab: EX["hold_c50"][nm]["phase_excess_ann_vs_random"] for nm, lab in (("PROD", "PROD"), ("single", "Single model"), ("ens3", "3-seed ensemble"))},
                         "note": "2026 lead over random picks for each of the 5 possible weekly entry days. The spread across entry days is as large as the average lead: luck of timing dominates a 9-month window."}
mo = EX["hold_c50"]["PROD"]["monthly"]
ch["monthly_lead_2026"] = {"type": "bar", "x": list(mo.keys()),
                           "series": {"PROD minus random (5 seeds)": [v["s"] - v["r5"] for v in mo.values()],
                                      "PROD minus equal weight": [v["s"] - v["ew"] for v in mo.values()]},
                           "note": "Month-by-month lead of the PROD book in 2026 (January starts on the 7th, October ends on the 7th)."}
ch["forward_power"] = {"type": "line", "x": [r["months"] for r in power["rows"]],
                       "series": {"P(confirmed) if no edge": [r["p_confirm_mu0"] for r in power["rows"]],
                                  "P(confirmed) at the planning edge": [r["p_confirm_mu_plan"] for r in power["rows"]],
                                  "P(confirmed) at +6.9%/yr": [r["p_confirm_mu_ew_est"] for r in power["rows"]],
                                  "P(plan rejected) if no edge": [r["p_plan_reject_mu0"] for r in power["rows"]]},
                       "note": "Chance that fresh data alone (after 14-Oct-2026) confirms the edge, or rejects the plan, by months of fresh data. A real edge of this size needs years to be confirmed."}
C.save("charts", ch)
C.log("tables", len(T), "charts", len(ch), "adoption rows", len(rows))
print(json.dumps({"adopted": adoption["adopted"], "passes_immaterial": adoption["passes_immaterial"], "n": adoption["n_addons"]}, indent=0))
print(json.dumps(C.short(exp_, 4), indent=0)[:3000])
print(json.dumps(C.short(power, 4), indent=0)[:3500])
print(json.dumps(C.short(sc3, 4), indent=0)[:1500])
