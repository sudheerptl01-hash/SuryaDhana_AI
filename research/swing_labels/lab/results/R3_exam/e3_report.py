"""R3_exam stage 3: build the report text, final process, expected performance, forward protocol and the structured
summary strings FROM results.json (every number below is formatted from a computed value), and save them."""
import json
import sys

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_exam")
d = C.load_res()
EX, FW, AD, EP, PW, IM, SC = d["exam"], d["forward_estimate"]["PROD"], d["adoption"], d["expected_performance"], d["forward_power"], d["imported"], d["spot_checks"]
H, D, H8, D8 = EX["hold_c50"], EX["dev_c50"], EX["hold_c80"], EX["dev_c80"]
P_, S_, E3 = H["PROD"], H["single"], H["ens3"]
pc = lambda x, n=1: f"{100 * x:+.{n}f}%"  # noqa: E731
pp = lambda x, n=1: f"{100 * x:.{n}f}%"  # noqa: E731
tt = lambda x: f"{x:.2f}"  # noqa: E731
f5, fe, f25 = FW["random5"], FW["ew"], FW["random25"]
x3 = AD["X3_evidence"]
kr, k0 = IM["kill_rules_b40_H1a"], IM["kill_rules_b40_H0"]
rows24 = [r for r in PW["rows"] if r["months"] == 24][0]
rows48 = [r for r in PW["rows"] if r["months"] == 48][0]
rows12 = [r for r in PW["rows"] if r["months"] == 12][0]
g = EP["absolute_grid_additive"]
tax = IM["tax_with_cess_verifier"]
cross = IM["capacity_crossings_verifier"]
ops = IM["ops_E0_dev"]
pr = IM["participation_20cr_dev"]
sl = IM["slippage_budget"]

verdict = (f"The frozen process is alive but unproven. In 2023-25 the PROD book led random picks by {pc(D['PROD']['excess_vs_random5_ann'])}/yr "
           f"(t {tt(D['PROD']['nw_t_vs_random5'])}; robust to the t-stat method: {tt(D['PROD']['SC4_t_lag']['lag60'])} with 60 lags, "
           f"{tt(D['PROD']['SC4_t_lag']['nonoverlap_20d_blocks_t'])} on non-overlapping blocks). In the 2026 exam (7 Jan - 7 Oct, 185 days) it made "
           f"{pp(P_['cagr'])} annualised ({pp(P_['total_return'])} total), level with the pre-registered 5-seed random book ({pc(P_['excess_vs_random5_ann'])}/yr, "
           f"t {tt(P_['nw_t_vs_random5'])}) and {pc(P_['excess_vs_ew_ann'])}/yr ahead of the equal-weight universe (t {tt(P_['nw_t_vs_ew'])}); not significant. "
           f"The precision-weighted forward estimate (2023-25 lead after a Bonferroni haircut for ~{f5['haircut_programme']['N']} trials, combined with 2026) is "
           f"{pc(f5['bonf_haircut_programme']['combined'])}/yr vs random picks (s.e. {pp(f5['bonf_haircut_programme']['combined_se'])}; P(>0) {f5['p_combined_gt0_primary']:.2f}) "
           f"and {pc(fe['bonf_haircut_programme']['combined'])}/yr vs the equal-weight universe. Of 21 add-ons only the X3 execution timing is adopted (as a disclosed post-hoc execution "
           f"convention, not skill); everything else is rejected. Trade it at <= Rs 20 cr with the C2 kill rule; the clean exam is data after 2026-10-14.")

adoption_decisions = []
for r in AD["rows"]:
    ev = (f"DEV gain {pc(r['dev_gain_ann'], 2)}/yr vs {r['baseline']} (paired NW t {tt(r['dev_nw_t'])}), maxDD change {pc(r['dev_maxdd_change'], 2)} (+ = shallower); "
          f"2026 (report only) {pc(r['hold_gain_ann'], 2)} (t {tt(r['hold_nw_t'])}). Declared in advance: {r['pre_declared']}. Executable: {r['executable']}. {r['reason']}.")
    adoption_decisions.append({"addon": f"{r['addon']} ({r['source']}): {r['description']}", "decision": r["decision"], "evidence": ev})
adoption_decisions.append({"addon": "X2 (R3_book): E1 + best early exit", "decision": "not run",
                           "evidence": "Conditional on an early exit passing; none did (R3_book)."})

final_exam = (
    "Frozen E0 book (weekly, 4 sleeves, top-20 PROD, 20-day hold, liq2, 50 bps), phase-averaged over 5 entry weekdays.\n"
    f"2026 exam ({H['window'][0]} to {H['window'][1]}, {H['n_days']} trading days; CAGR annualised / total; lead per yr with NW t):\n"
    f"- PROD (pre-registered): {pp(P_['cagr'])} / {pp(P_['total_return'])}; vs random-5 {pc(P_['excess_vs_random5_ann'])} (t {tt(P_['nw_t_vs_random5'])}); vs EW {pc(P_['excess_vs_ew_ann'])} (t {tt(P_['nw_t_vs_ew'])}); vs random-25 {pc(P_['excess_vs_random25_ann'])} (t {tt(P_['nw_t_vs_random25'])}); maxDD {pp(P_['maxdd'])}; Sharpe {tt(P_['sharpe'])}; 80 bps CAGR {pp(H8['PROD']['cagr'])}.\n"
    f"- Single model: {pp(S_['cagr'])} / {pp(S_['total_return'])}; vs random-5 {pc(S_['excess_vs_random5_ann'])} (t {tt(S_['nw_t_vs_random5'])}); vs EW {pc(S_['excess_vs_ew_ann'])} (t {tt(S_['nw_t_vs_ew'])}); maxDD {pp(S_['maxdd'])}.\n"
    f"- 3-seed ensemble: {pp(E3['cagr'])}; vs random-5 {pc(E3['excess_vs_random5_ann'])} (t {tt(E3['nw_t_vs_random5'])}); vs EW {pc(E3['excess_vs_ew_ann'])}.\n"
    f"- PROD minus single (paired): 2026 {pc(H['paired_PROD_minus_single']['diff_ann'])} (t {tt(H['paired_PROD_minus_single']['nw_t'])}); DEV {pc(D['paired_PROD_minus_single']['diff_ann'])} (t {tt(D['paired_PROD_minus_single']['nw_t'])}). Noise; PROD stays (pre-registered).\n"
    f"- Baselines 2026: random-5 {pp(H['random5']['cagr'])}, random-25 {pp(H['random25']['cagr'])}, EW {pp(H['ew']['cagr'])}, Nifty 500 price {pp(H['nifty500_price']['cagr'])} (TR proxy {pp(H['nifty500_tr_proxy_cagr'])}), cash {pp(H['cash_1d_rate']['cagr'])}.\n"
    f"- Entry-weekday spread of PROD's 2026 lead: {pc(min(P_['phase_excess_ann_vs_random']))} to {pc(max(P_['phase_excess_ann_vs_random']))}/yr. Trades {P_['trades_phase_mean']:.0f}, hit rate {pp(P_['hit_rate_phase_mean'])}, mean net trade {pc(P_['mean_trade_net_phase_mean'], 2)}.\n"
    f"- Adopted X3 execution in 2026 (R3_book, verified): CAGR {pp(x3['hold']['x3_cagr'])}; gain vs E0 {pc(x3['hold']['x3_minus_e0']['diff_ann'])} (t {tt(x3['hold']['x3_minus_e0']['nw_t'])}); vs timing-matched random {pc(x3['hold']['x3_vs_timing_matched_random']['diff_ann'])} (t {tt(x3['hold']['x3_vs_timing_matched_random']['nw_t'])}).\n"
    f"DEV reference (2023-25): PROD {pp(D['PROD']['cagr'])}, lead vs random-5 {pc(D['PROD']['excess_vs_random5_ann'])} (t {tt(D['PROD']['nw_t_vs_random5'])}), vs EW {pc(D['PROD']['excess_vs_ew_ann'])} (t {tt(D['PROD']['nw_t_vs_ew'])}), vs random-25 {pc(D['PROD']['excess_vs_random25_ann'])} (t {tt(D['PROD']['nw_t_vs_random25'])}); single {pc(D['single']['excess_vs_random5_ann'])} (t {tt(D['single']['nw_t_vs_random5'])}); random-5 {pp(D['random5']['cagr'])}, random-25 {pp(D['random25']['cagr'])}, EW {pp(D['ew']['cagr'])}.\n"
    f"Precision-weighted forward estimate (PROD): vs random-5 (pre-declared primary) {pc(f5['bonf_haircut_programme']['combined'])}/yr, s.e. {pp(f5['bonf_haircut_programme']['combined_se'])} "
    f"[inputs: DEV {pc(f5['dev_excess'])} -> haircut {pc(f5['haircut_programme']['haircut_excess_ann'])} (s.e. {pp(f5['dev_se'])}); 2026 {pc(f5['hold_excess'])} (s.e. {pp(f5['hold_se'])}); weight on 2026 {f5['bonf_haircut_programme']['weight_hold']:.2f}]; "
    f"vs EW {pc(fe['bonf_haircut_programme']['combined'])}; vs random-25 {pc(f25['bonf_haircut_programme']['combined'])}; sensitivity vs random-5: upper trial count {pc(f5['bonf_haircut_upper']['combined'])}, no haircut {pc(f5['raw_dev']['combined'])}. "
    f"2026 sits {tt(f5['z_hold_vs_dev_raw'])} s.e. from the raw DEV lead and {tt(f5['z_hold_vs_dev_haircut'])} s.e. from the haircut one.")

final_process = (
    "LABEL: XR_neumom, h = 20 - per date, the rank of the executable 20-day return (open t+1 to close t+20, corporate-action adjusted) after OLS-removing shrunk beta, vol_20, log turnover and 12-1 momentum among elig_base; classes 30/40/30 for reporting only.\n"
    "SCORE: PROD = mean per-date percentile rank of 10 LightGBM regressors (seeds 1-5 x date offsets 0/1) on 55 point-in-time features; annual walk-forward retrain.\n"
    "UNIVERSE: elig_base - NSE EQ-series equities, raw price >= Rs 20, 20-day turnover >= Rs 2 cr, >= 120 bars, not locked, ATR 0.5-15%.\n"
    "BOOK: one fixed weekday, signal after the close; 4 sleeves of 25% each, one renewed per week; each sleeve holds its top-20 PROD names at 1/20 of the sleeve (unfilled slots in cash); 20-trading-day holds; "
    f"about {ops['avg_names_held']:.0f} names across 80 slots, about {ops['orders_per_week']:.0f} orders a week, {ops['round_trips_per_yr']:.0f} round trips a year.\n"
    "ENTRIES/EXITS (X3, adopted): at a sleeve's renewal keep names still in its new top-20; sell the others and buy the new names in the next morning's opening session; forced exit at the last valid close on suspension/label_block. "
    "No stops, no early avoid-tail exits, no inverse-vol sizing (all rejected).\n"
    "AVOID VETO (-1 side): bottom 30% of PROD on the signal date is a do-not-buy/exit list for any name outside the model book; the frozen top-20 never holds such names. Never short in cash; no F&O single-stock shorts, long/short or short overlay (all lost money or failed the rule).\n"
    "EXPOSURE/HEDGE: 100% invested. A static 80%/60% (rest in an overnight fund) is allowed only as a risk-appetite dial (Sharpe vs cash unchanged); no breadth governor; a Nifty 50 futures hedge is an optional risk dial outside the core, not adopted.\n"
    f"CAPACITY: <= Rs 20 cr AUM (about Rs 25 lakh per name); each order <= 5% of the 20-day median traded value, excess stays in cash. Frozen-book crossing vs a dividend-inclusive Nifty 500 is about Rs {cross['E0_uncapped_vs_N500TR']:.1f} cr (Rs {cross['E0_cap5_vs_N500TR_(5cr point = uncapped)']:.1f} cr with the cap).\n"
    f"COSTS: budget 50 bps round trip (statutory {sl['statutory_round_trip_bps']} bps + {sl['slippage_budget_bps_per_side_central']} bps/side slippage vs the official open); stress 80 bps.\n"
    "MONITORING/KILL: weekly dashboard (matured rank IC, top-20 relative/absolute hit, top-20 lead over the universe, avoid-tail return, overlap/turnover, slippage vs official open, overnight gap of names sold). "
    "Review if 6-month lead < -5% (K1) or 3-month matured IC < 0.02 (K2) or 12-month lead < 0 (K3); kill (stop new entries, let sleeves run off) if K3 and K2 fire at the same weekly check (C2).")

expected_performance = (
    f"Edge: forward lead over random picks of the same style {pc(EP['forward_excess_vs_random5'])}/yr (pre-declared primary; 90% range {pc(EP['forward_90lo'])} to {pc(EP['forward_90hi'])}; P(>0) {EP['p_edge_positive']:.2f}); "
    f"over the equal-weight universe {pc(EP['forward_excess_vs_ew'])}/yr (90% range {pc(EP['forward_90lo_vs_ew'])} to {pc(EP['forward_90hi_vs_ew'])}). "
    f"Absolute (pre-tax, after 50 bps, additive): if the market repeats 2023-25 (EW {pp(g['like_2023_25_ew']['ew_cagr'])}) the book makes about {pp(g['like_2023_25_ew']['book_conservative_plan'])}-{pp(g['like_2023_25_ew']['book_forward_central'])}; "
    f"a 2026-like year (EW {pp(g['like_2026_ew']['ew_cagr'])}) about {pp(g['like_2026_ew']['book_conservative_plan'])}-{pp(g['like_2026_ew']['book_forward_central'])}; a 2021-22-like period (EW {pp(g['like_2021_22_ew']['ew_cagr'])}) about {pp(g['like_2021_22_ew']['book_conservative_plan'])}-{pp(g['like_2021_22_ew']['book_forward_central'])}. "
    f"X3 opening-session execution adds the overnight premium: {pc(EP['x3_overnight_premium_random_dev'])}/yr (2023-25) and {pc(EP['x3_overnight_premium_random_hold'])}/yr (2026) on random picks, and shrinking. "
    f"Costs already deducted: {pp(EP['cost_drag_E0_dev'])}/yr; short-term capital-gains tax incl. cess costs a further {pp(EP['tax_drag_E0_stcg_with_cess'])}/yr ({pp(EP['tax_drag_X3_stcg_with_cess'])} with X3). "
    f"Risk: worst fall 2023-25 {pp(D['PROD']['maxdd'])}, 2026 {pp(P_['maxdd'])}; median worst fall over 2 years {pp(IM['risk_expectations_b40_plus5']['maxdd_24m']['p50'])}, P(deeper than -30%) {IM['risk_expectations_b40_plus5']['maxdd_24m']['p_worse_than_minus30']:.2f}; "
    f"P(losing 12 months) {IM['risk_expectations_b40_plus5']['absolute_12m']['p_neg']:.2f}; P(trailing random picks in a calendar year, live single schedule) {IM['risk_single_phase_verifier']['p_neg_year_plus5']:.2f}; "
    f"a dead book still shows a > +5% lead in {IM['risk_dead_book_p_above_plus5']:.2f} of years.")

forward_protocol = (
    "1 FROZEN SPEC: label results/R3_devil/label_h20_neumom.npz recipe; PROD recipe (build_prod.py: 10 walk_forward2 regressors, y = pct - 0.5, seeds 1-5 x date_offset 0/1, date_step 2, default parameters, 55 features); "
    "book as in the final process with X3 execution for the live account; costs 50/80 bps; liq2 universe; avoid list = bottom 30%; 100% exposure; no hedge, no regime layer, no event sleeve.\n"
    "2 CLOCK: fresh data = signal dates from 2026-10-15; first fresh entries at the next open. The lab recomputes weekly, phase-averaged: the E0 PROD paper book (the exam book), the X3 PROD book (live timing), "
    "random top-20 with 25 seeds under both timings, the EW universe, Nifty 500 price and a +1.2%/yr total-return proxy. The live account (one entry weekday) is reported alongside.\n"
    "3 RETRAIN: once a year in the first week of January (first: Jan 2027), identical recipe: train rows 2021-09-01 to 22 trading days before 1 January, same 10 members, no feature/parameter/label change. "
    "Before the first retrain, re-fit the 2026 fold and check its scores against prod_h20.npz; log any data fix. Until then score new rows with the 2026-fold recipe.\n"
    f"4 SUCCESS: primary statistic = fresh annualised lead of the E0 PROD paper book vs 25-seed random (secondary: vs EW), NW(20) t, at each annual review. "
    f"Confirmed if one-sided t >= 1.645 (5% false-confirm at zero edge); power at the planning edge {pc(PW['prior_mean'])}: {rows12['p_confirm_mu_plan']:.2f} at 12 months, {rows24['p_confirm_mu_plan']:.2f} at 24, {rows48['p_confirm_mu_plan']:.2f} at 48 "
    f"(at {pc(PW['mu_values']['mu_ew_est'])}: {rows24['p_confirm_mu_ew_est']:.2f} at 24, {rows48['p_confirm_mu_ew_est']:.2f} at 48). "
    f"Plan rejected if the fresh lead < plan - 1.645 x sqrt(fresh s.e.^2 + {pp(PW['prior_se'])}^2) (threshold {pc(rows24['fresh_threshold_plan_reject'])}/yr at 24 months): then the planning number becomes the updated posterior, and a posterior <= 0 stops the strategy. "
    "The planning number is updated each year by precision weighting (prior + fresh).\n"
    f"5 KILL/REVIEW: review on K1/K2/K3 (any review within 24 months for a good book {kr['C1_review']['p_fire_24m']:.2f}); kill on C2 (false alarm {kr['C2_kill']['p_fire_24m']:.3f}, single schedule {IM['risk_single_phase_verifier'].get('p_neg_year_plus5', 0):.2f} is not the C2 figure - see R3_risk; "
    f"detection of a dead book {k0['C2_kill']['p_fire_24m']:.3f}, median {k0['C2_kill']['median_first_fire_days']:.0f} trading days). K3 is likely to trigger a review by 31-Mar-2027 (P {IM['risk_K3_fire_prob_given_path_verifier']['plan_5pct']['2027-03-31']}). "
    f"Operations: 3-month average slippage vs the official open > {sl['slippage_budget_bps_per_side_central']} bps/side -> review; > {sl['slippage_budget_bps_per_side_stress']} bps/side -> stop adding capital. "
    "X3 check: if the 6-month mean overnight gap of names sold turns negative, revert to E0 close exits.\n"
    f"6 CHALLENGERS (shadow only, fresh data only): single model, 3-seed ensemble, E2w avoid-tail weekly exit, liq5 universe. Promotion after >= 24 months only if the paired fresh lead over PROD has t >= {PW['challenger_t_threshold_bonferroni_k4']:.2f} (Bonferroni, 4 challengers) and maxDD is not > 3 pp deeper.")
forward_protocol = forward_protocol.replace(
    f"kill on C2 (false alarm {kr['C2_kill']['p_fire_24m']:.3f}, single schedule {IM['risk_single_phase_verifier'].get('p_neg_year_plus5', 0):.2f} is not the C2 figure - see R3_risk; ",
    f"kill on C2 (false alarm for a good book {kr['C2_kill']['p_fire_24m']:.3f}; ")

spot_checks = [f"{s['id']}: {s['flag']} -> {s['verdict']}" for s in SC]

caveats = [
    f"2026 is short ({H['n_days']} trading days) and lightly contaminated (reported in earlier rounds); entry-weekday luck alone moves PROD's 2026 lead from {pc(min(P_['phase_excess_ann_vs_random']))} to {pc(max(P_['phase_excess_ann_vs_random']))}/yr.",
    f"The pre-registered 5-seed random yardstick is noisy: it sits {pc(H['random5_minus_random25_ann'])}/yr above the 25-seed book in 2026 and {pc(D['random5_minus_random25_ann'])}/yr in 2023-25, so the primary forward estimate ({pc(f5['bonf_haircut_programme']['combined'])}) is the conservative end; vs EW / 25-seed random it is {pc(fe['bonf_haircut_programme']['combined'])} / {pc(f25['bonf_haircut_programme']['combined'])}.",
    f"The forward estimate depends on the multiple-testing haircut: {pc(f5['bonf_haircut_upper']['combined'])} with the upper trial count, {pc(f5['raw_dev']['combined'])} with no haircut.",
    f"X3 is a disclosed post-hoc execution convention; {x3['dev']['share_of_gain_from_exit_timing']:.2f} of its 2023-25 gain is the overnight premium that random picks also earn; that premium shrank (exit-name gap {pc(x3['overnight_gap_exit_names']['dev_by_year_mean']['2024'], 2)} per night in 2024, {pc(x3['overnight_gap_exit_names']['hold_mean'], 2)} in 2026) and opening-auction depth is not modelled.",
    f"Capacity is a judgement: the frozen book falls to a dividend-inclusive Nifty 500 at about Rs {cross['E0_uncapped_vs_N500TR']:.1f} cr in 2023-25 under Y=1 impact; X3 models higher (Rs {cross['X3_uncapped_vs_N500TR']:.1f} cr) but all its trades sit in the opening session.",
    "Absolute-return scenarios are additive approximations on history (2023-25 was an unusually strong small-cap period); tax uses the verifier's cess-corrected STCG model, calendar years, and is not advice (frequent trading may be business income).",
    f"Power is low: a {pc(PW['prior_mean'])}/yr edge is confirmed by fresh data alone with probability {rows24['p_confirm_mu_plan']:.2f} after 24 months; the C2 kill rule, not the confirmation test, is the protection against a dead book.",
    "Nifty 500 is a price index (about 1.2%/yr dividends missing); lab prices include dividends.",
    "R3_exam ran no selection variants; diagnostics: 3 scores x 2 periods x 2 costs, 200 extra random books (SC1), D0 re-run (SC2), statistics-only checks SC3-SC6. 21 add-ons were judged from the builders' saved, verifier-reproduced numbers.",
    "REPORT.md is not written as a file because this subagent is instructed not to write report .md files; the report is in results.json section report_md.",
]

report = f"""# R3_exam: adversarial verification, final exam, adoption, forward protocol

All numbers are in `results/R3_exam/results.json`. Scripts: `e0_predeclare.py` (pre-declaration, saved first), `e1_exam.py` (exam, SC1, SC2, SC4, SC5, forward estimate), `e2_final.py` (adoption, SC3, SC6, imports, expectations, power, tables, charts), `e3_report.py` (this text). Logs: `log_e*.txt`. Daily series: `exam_series.npz`.

## Verdict
{verdict}

## 1. Verification (item 1 by the verifiers; my spot-checks)
All four verifiers reproduced the builders' headline numbers with their own code and found no look-ahead. I re-ran what they flagged:
""" + "\n".join(f"- {s}" for s in spot_checks) + f"""

## 2. Adoption rule on every add-on (DEV only; 2026 reported)
Rule: {AD['rule']}. {AD['n_addons']} add-ons judged; {AD['n_numeric_pass']} pass the numeric thresholds (X1, E1, X3).
- **Adopted:** X3 executable carry, as the execution convention. It is the only executable form of the pre-declared E1 (any carry decision made with the close-g signal can only trade at open g+1). DEV gain {pc(x3['dev']['x3_minus_e0']['diff_ann'], 2)}/yr (t {tt(x3['dev']['x3_minus_e0']['nw_t'])}), maxDD {pp(x3['dev']['x3_maxdd'], 2)} vs {pp(D['PROD']['maxdd'], 2)}. But random picks gain {pc(x3['dev']['random_timing_gain']['diff_ann'], 2)}/yr from the same timing; X3's lead over a timing-matched random book is {pc(x3['dev']['x3_vs_timing_matched_random']['diff_ann'])} (DEV) and {pc(x3['hold']['x3_vs_timing_matched_random']['diff_ann'])} (2026), the same skill as E0. Disclosed post-hoc.
- **Passes, immaterial:** X1 (idle cash at the overnight rate): about +0.01%/yr.
- **Rejected:** E1 (not executable), E2w, E2d, E3, S1, D1a, D1b, D1c, D2 x4, X1-beta, D3, D4, X80, X60, G50.
- **D0 (avoid veto):** vs EW it adds {pc(d['SC2_D0_avoid_veto']['dev']['D0_vs_ew_ann'], 2)}/yr (t {tt(d['SC2_D0_avoid_veto']['dev']['D0_vs_ew_t'])}); vs the frozen book {pc(d['SC2_D0_avoid_veto']['dev']['D0_minus_frozen_book']['diff_ann'])} (t {tt(d['SC2_D0_avoid_veto']['dev']['D0_minus_frozen_book']['nw_t'])}). It is the avoid list already in the frozen process, not an add-on.

## 3. Final exam
{final_exam}

## 4. Final investment process
{final_process}

## 5. Expected performance
{expected_performance}

## 6. Forward protocol (data after 2026-10-14)
{forward_protocol}

## Pros
- Every builder number was reproduced by an independent verifier, and my own phase loop equals C.phase_avg exactly (max abs daily diff 0.0).
- The book-level t-stat is robust to the t-stat method, and the PROD lead survives a better 25-seed yardstick.
- Only one add-on is adopted, and its mechanism (the overnight premium) is measured on random picks, so it cannot inflate the skill estimate.
- The forward protocol has pre-computed false-alarm and power numbers, a fast kill rule and Bonferroni-guarded challengers.

## Cons
- The 2026 exam did not show the DEV edge: the lead over the pre-registered yardstick is {pc(P_['excess_vs_random5_ann'])}/yr (t {tt(P_['nw_t_vs_random5'])}).
- The forward edge is modest ({pc(f5['bonf_haircut_programme']['combined'])} to {pc(fe['bonf_haircut_programme']['combined'])}/yr) next to {pp(EP['cost_drag_E0_dev'])}/yr costs and {pp(EP['tax_drag_E0_stcg_with_cess'])}/yr tax.
- Capacity is small (about Rs 20 cr) and confirmation on fresh data will take years.

## Caveats
""" + "\n".join(f"- {c}" for c in caveats) + "\n"

summary = {"verdict": verdict, "final_exam": final_exam, "final_process": final_process, "expected_performance": expected_performance,
           "forward_protocol": forward_protocol, "spot_checks": spot_checks, "caveats": caveats, "adoption_decisions": adoption_decisions}
C.save("summary", summary)
C.save("report_md", report)
print(json.dumps(summary, indent=1))
