"""Stage 10: generate REPORT.md from results.json (all numbers are read, none typed by hand except where
explicitly quoted in prose, which is cross-checked against the tables)."""
import json
import math
import os

import numpy as np

import report_tables as T
from common import OUT, save

D = T.D
H20 = [m for m in T.MODELS if m.startswith("h20_") and f"s3_wf_{m}" in D]
sel_table, M = T.t_selection(H20)
selected = M.index[0]
runner_up = M.index[1]


# ------------------------------------------------------------------ variant count
def count_variants():
    n_label = 3 * 4 * 6                                 # h x neutraliser x {C30,C20,C33,T30,B30,RANK} event-rate screen
    n_label += 3                                        # T10/T20/T50 at h20 neu
    n_models = sum(1 for k in D if k.startswith("s3_wf_"))
    n_sim_dev = sum(sum(1 for r in v if r["period"] == "dev") for k, v in D.items() if k.startswith("s5_"))
    n_ref = sum(1 for k in D.get("s6_ref_sorts_h20", {}) if k.endswith("_dev"))
    n_xh = sum(1 for k in D.get("s6_cross_horizon", {}) if k.endswith("_dev"))
    n_phase = sum(v2["n_phases"] for k, v in D.items() if k.startswith("s7_phase_") for kk, v2 in v.items()
                  if kk.endswith("_dev"))
    n_spec50 = sum(sum(1 for r in v if r["period"] == "dev" and r["cfg"]["cost_bps"] == 50)
                   for k, v in D.items() if k.startswith("s5_"))
    return {"label_constructions_screened": n_label, "walk_forward_models": n_models,
            "distinct_specs_dev_50bp": n_spec50 + n_ref + n_xh,
            "portfolio_configs_dev_S_compare": n_sim_dev, "reference_sorts_dev": n_ref,
            "cross_horizon_dev": n_xh, "phase_shift_runs_dev": n_phase,
            "total_portfolio_tests_dev": n_sim_dev + n_ref + n_xh + n_phase}


V = count_variants()
NT = V["total_portfolio_tests_dev"]
from scipy.stats import norm  # noqa: E402
bonf = float(norm.ppf(1 - 0.05 / NT))
bonf_spec = float(norm.ppf(1 - 0.05 / V["distinct_specs_dev_50bp"]))
bonf_all = float(norm.ppf(1 - 0.05 / (V["distinct_specs_dev_50bp"] + 600)))
save("s10_variant_count", {**V, "bonferroni_one_sided_5pct_hurdle_t": bonf, "bonf_distinct_specs": bonf_spec,
                           "bonf_distinct_specs_plus_round1_600": bonf_all, "selected_dev": selected,
                           "runner_up_dev": runner_up,
                           "selection_metrics": {m: {k: (None if (isinstance(v, float) and math.isnan(v)) else v)
                                                     for k, v in M.loc[m].to_dict().items()} for m in M.index}})

sim = T.find_sim
ph = T.phase


def g(m, per="dev", **kw):
    kw.setdefault("K", 20)
    kw.setdefault("step", 5)
    kw.setdefault("cost", 50)
    return sim(m, per=per, **kw)


S_dev, S_hold = g(selected), g(selected, "hold")
S80_dev, S80_hold = g(selected, cost=80), g(selected, "hold", cost=80)
P_dev, P_hold = ph(selected, "K20_s5", "dev"), ph(selected, "K20_s5", "hold")
A_dev = T.find_sim(selected, K=None, step=5, cost=50, per="dev", q=(0.3, 1.0))
A_hold = T.find_sim(selected, K=None, step=5, cost=50, per="hold", q=(0.3, 1.0))
AP_dev, AP_hold = ph(selected, "avoid30_s5", "dev"), ph(selected, "avoid30_s5", "hold")
pct, num = T.pct, T.num
bench = {2023: 0.2516, 2024: 0.1493, 2025: 0.0618, 2026: -0.0783}

md = []
w = md.append
w("# R2_rel - Relative (selection) label architecture, lab v2\n")
w("Agent: R2_rel. Scope: the definitive cross-sectional relative label for a 5-20 day NSE swing trader, "
  "h in {10, 15, 20}. Lab v2 only (no sector data, ETFs excluded, elig_base as rebuilt). Entry open[t+1], "
  "exit close[t+h]; labels NaN where `fw.ok(h)` fails; eligibility selects rows and never changes a label. "
  "Models: `L.walk_forward2` (yearly expanding folds 2023-2026, embargo h+2, date_step 2, n_jobs 2, default "
  "LightGBM, 52 PIT features). Learnability: per-date cross-sectional IC/AUC with non-overlapping t "
  "(identical to `L.xs_metrics`; cross-checked to 1e-12 on the first model). Investability: `L.Sim` maths "
  "with the horizon-matched 5-seed random baseline on the same mask (random bands cached on disk, otherwise "
  "identical to `S.compare`), 50/80/130 bps. Selection on DEV 2023-2025 only; 2026 (Jan 1 - Oct 14) is "
  "reported separately and never used to choose.\n")

w("## 1. Headline\n")
w(f"* **Selected on DEV (composite of 7 DEV-only criteria, fixed before the last 6 models were trained; Section 9): `{selected}`** "
  f"(runner-up `{runner_up}`).")
w(f"* `{selected}`, long top-20, step 5, 50 bps: DEV CAGR {pct(S_dev['cagr'])} vs horizon-matched random "
  f"{pct(S_dev['random']['cagr_mean'])} (excess {pct(S_dev['excess_cagr_vs_random'], sign=True)}, NW t "
  f"{num(S_dev['excess_daily_nw_t'])}); maxDD {pct(S_dev['max_dd'])}; 80 bps {pct(S80_dev['cagr'])}. "
  f"Phase-averaged (all 5 entry phases) DEV excess {pct(P_dev['phaseavg_excess_ann'], sign=True)}/yr, t "
  f"{num(P_dev['phaseavg_nw_t'])}.")
w(f"* 2026 holdout (not used for selection): CAGR {pct(S_hold['cagr'])} vs random {pct(S_hold['random']['cagr_mean'])} "
  f"(excess {pct(S_hold['excess_cagr_vs_random'], sign=True)}, t {num(S_hold['excess_daily_nw_t'])}); 80 bps "
  f"{pct(S80_hold['cagr'])}; phase-averaged excess {pct(P_hold['phaseavg_excess_ann'], sign=True)}/yr (t "
  f"{num(P_hold['phaseavg_nw_t'])}). Nifty 500 2026 YTD {pct(bench[2026])}.")
w(f"* AVOID overlay with the same score (equal-weight all elig names except the model's bottom 30%): DEV "
  f"{pct(A_dev['cagr'])} vs random-70% {pct(A_dev['random']['cagr_mean'])} / universe EW {pct(A_dev['ew']['cagr'])}, "
  f"excess {pct(A_dev['excess_cagr_vs_random'], sign=True)} (t {num(A_dev['excess_daily_nw_t'])}); 2026 "
  f"{pct(A_hold['cagr'])} vs EW {pct(A_hold['ew']['cagr'])} (excess {pct(A_hold['excess_cagr_vs_random'], sign=True)}, "
  f"t {num(A_hold['excess_daily_nw_t'])}).")
w(f"* Variants: {V['label_constructions_screened']} label constructions screened for event rates, "
  f"{V['walk_forward_models']} walk-forward models, {V['portfolio_configs_dev_S_compare']} S.compare configurations "
  f"on DEV, {V['reference_sorts_dev']} reference sorts, {V['cross_horizon_dev']} cross-horizon runs and "
  f"{V['phase_shift_runs_dev']} phase-shift runs = {NT} DEV portfolio runs; **{V['distinct_specs_dev_50bp']} distinct "
  f"DEV strategy specifications at 50 bps** (costs 80/130 and phase shifts are not new specs). One-sided 5% "
  f"Bonferroni hurdle: t = {bonf_spec:.2f} for the distinct specs, {bonf_all:.2f} adding round 1's ~600 variants, "
  f"{bonf:.2f} counting every run (all very conservative: the tests are highly correlated).\n")
w("@@HEADLINE_PROSE@@\n")

w("## 2. Label construction\n")
w("```\nr_h    = open[t+1] -> close[t+h]  (adjusted; NaN unless fw.ok(h))\n"
  "V_h    = elig_base & isfinite(r_h)          # cross-section for winsorising, OLS and ranking\n"
  "rw_h   = clip(r_h, per-date 1st pct, per-date 99th pct) over V_h\n"
  "resid  = rw_h - X b_t   (per-date OLS over V_h, intercept always)\n"
  "   neu    : X = [0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20]     (= round-1 XR_neu, shrunk beta)\n"
  "   neumom : neu + mom_12_1 (NaN -> per-date median; 11.8% of elig rows)\n"
  "   size   : X = [log_turn20]\n"
  "   none   : X = []  (rank of winsorised raw return == rank of return minus index)\n"
  "pct    = per-date percentile rank of resid over V_h  (0,1]\n"
  "forms  : RANK = pct-0.5 (regression) | C30 +1 pct>0.7 / -1 pct<=0.3 | C20 | C33 (multiclass, score P(+1)-P(-1))\n"
  "         T30/T20/T10/T50 = 1{pct > 1-q} (binary) | B30 = 1{pct <= 0.3} (binary AVOID; score = -P)\n```\n")
w(T.t_construction() + "\n")
w("Neutralisation explains only 1-4% of the cross-sectional variance of 20-day returns, so the label "
  "changes by a few percent of rows, but (Section 3) it removes the market-dependent composition tilt.\n")

w("## 3. Event rates and label diagnostics\n")
w("### 3a. Class shares and stability (30/40/30 form, all h x neutralisers)\n")
w(T.t_events_c30() + "\n")
w("@@EVENTS_PROSE@@\n")
w("### 3b. Label/P&L coherence: relative classes are NOT absolute outcomes\n")
w(T.t_coherence() + "\n")
reg, yr = T.t_regime()
w("By regime and by year (h=20, neu, 30/40/30):\n")
w(reg + "\n")
w(yr + "\n")
w("### 3c. Composition tilt of the label (+1 minus -1, cross-sectional z) and persistence\n")
w(T.t_tilt() + "\n")
w("@@TILT_PROSE@@\n")
w("### 3d. Rank-cut sensitivity of the label (neu)\n")
w(T.t_rankcut() + "\n")

w("## 4. Learnability (walk-forward OOS, per-date cross-section)\n")
w(T.t_xs() + "\n")
w("@@XS_PROSE@@\n")
w("Selection precision of the long book (daily top-20, all dates, overlapping) and of the avoid list:\n")
w(T.t_precision() + "\n")

w("## 5. Investability headline (long top-20, step 5, liq2, S.compare vs horizon-matched random)\n")
w(T.t_invest_headline() + "\n")
w("By year (strategy vs 5-seed random, same mask; Nifty 500: 2023 +25.2%, 2024 +14.9%, 2025 +6.2%, 2026 YTD -7.8%):\n")
w(T.t_by_year() + "\n")
w("@@INVEST_PROSE@@\n")

w("## 6. Parameter-sensitivity map\n")
w("### 6a. Horizon x cost (neu RANK models, K=20)\n")
w(T.t_horizon_cost() + "\n")
w("### 6b. Training horizon vs holding horizon (neu RANK scores, K20 step 5, 50 bps)\n")
w(T.t_xh() + "\n")
for m in ("h20_neumom_RANK", "h20_neumom_C20", "h20_neumom_T30", "h20_neu_RANK"):
    if f"s5_full_{m}" in D:
        w(f"### 6c. K x step map: `{m}` (liq2, 50 bps; dev CAGR 80bp column = cost stress)\n")
        w(T.t_k_step(m) + "\n")
w("### 6d. Liquidity tier (liq2 = Rs2cr 20d turnover, liq5 = Rs5cr; model trained on liq2)\n")
w(T.t_liq() + "\n")
w("### 6e. AVOID overlay (EW all names except the model's bottom 30%)\n")
w(T.t_avoid() + "\n")
w("Avoid overlay vs cost and liquidity tier:\n")
w(T.t_avoid_cost() + "\n")
w("Avoid cut sensitivity (how much of the universe to drop):\n")
w(T.t_avoidcut() + "\n")
w("### 6f. Equal-weight quantile books (plateau check beyond top-K)\n")
w(T.t_quant() + "\n")
w("### 6g. Calendar-phase robustness (start shifted 0..step-1 days; phase-average = daily-staggered book)\n")
w(T.t_phase() + "\n")
w("@@SENS_PROSE@@\n")

w("## 7. Luck calibration\n")
lt, lt2 = T.t_luck()
w(lt + "\n")
w("Persistence-matched null (random scores with the model's own rank autocorrelation, 40 seeds):\n")
w(lt2 + "\n")
w("@@LUCK_PROSE@@\n")

w("## 8. What the scores load on: factor attribution and reference sorts\n")
w(T.t_loadings() + "\n")
at, fac = T.t_attrib()
w("Long-short factor returns (top-30% minus bottom-30% EW, h=20 step 5):\n")
w(fac + "\n")
w("Regression of daily excess-vs-random on the 6 factor series (NW t, lag 20):\n")
w(at + "\n")
w("Single-characteristic reference sorts (not candidates; same Sim, excess vs random):\n")
w(T.t_ref() + "\n")
w("@@FACTOR_PROSE@@\n")

w("## 9. Selection on DEV and the holdout exam\n")
w("Rule (fixed before the last six models - T20, T10, T50, neumom T30, neumom C20, h15 T30 - were trained; DEV data only; h=20 because DEV net CAGR at 80 and 130 bps is highest at h=20 for every model "
  "family, Section 6a): rank each h=20 candidate on 7 DEV-only criteria (S.compare t, phase-averaged t at "
  "step 5 and 10, mean t over the K x step grid, factor-adjusted alpha t, avoid-overlay phase-averaged t, "
  "IC t on the common XR_neu20 yardstick) and take the best mean rank. Constraints shown: DEV CAGR at 80 bps "
  "and worst DEV-year excess.\n")
w(sel_table + "\n")
w("@@SELECT_PROSE@@\n")

w("## 10. Pros, cons, failure modes\n")
w("@@PROSCONS@@\n")
w("## 11. Lab issues found\n")
w("@@LABISSUES@@\n")
w("## 12. Files\n")
w("Scripts `s1_labels.py` (targets) `s2_events.py` (event rates) `s3_wf.py` (walk_forward2) `s4_xs.py` (IC/AUC) "
  "`s5_sim.py` (S.compare grids, cached random bands in `rb_cache/`) `s6_nulls.py` / `s6b_matched_null.py` "
  "(luck bands, reference sorts, cross-horizon) `s7_phase.py` (phase robustness) `s8_loadings.py` "
  "`s9_attrib.py` (factor attribution) `s11_precision.py` `s12_impl.py` `report_tables.py` + `s10_report.py` "
  "(this report). Arrays: `labels_h{10,15,20}.npz` (r, rw, market window, EW mean, res_*/pct_* per "
  "neutraliser), `wf_<tag>.npz` (OOS scores), `daily_*.npz` (daily returns of 50 bps configs). All numbers: "
  "`results.json`.\n")

from prose import PROSE as prose  # noqa: E402
TOP = list(M.index[:3]) + [m for m in ("h20_neu_C20", "h20_neu_T30", "h20_neu_RANK", "h20_none_RANK")
                           if m in M.index and m not in list(M.index[:3])]
tok = {"{NSPEC}": str(V["distinct_specs_dev_50bp"]), "{BONF_SPEC}": f"{bonf_spec:.2f}",
       "{BONF_ALL}": f"{bonf_all:.2f}", "@@HOLDOUT_TABLE@@": T.t_holdout_exam(TOP)}
for k in list(prose):
    for a, b in tok.items():
        prose[k] = prose[k].replace(a, b)
txt = "\n".join(md)
for k in ("HEADLINE_PROSE", "EVENTS_PROSE", "TILT_PROSE", "XS_PROSE", "INVEST_PROSE", "SENS_PROSE", "LUCK_PROSE",
          "FACTOR_PROSE", "SELECT_PROSE", "PROSCONS", "LABISSUES"):
    txt = txt.replace(f"@@{k}@@", prose.get(k, ""))
with open(os.path.join(OUT, "REPORT.md"), "w") as fh:
    fh.write(txt)
print("REPORT.md written", len(txt), "chars; selected", selected, "runner-up", runner_up, V, "bonf", round(bonf, 2))
