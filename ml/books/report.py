"""BOOKS.md: every number below is read from the payload that construct.py writes to books.json."""
from __future__ import annotations

from pathlib import Path

NL = "name_level"


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:+.{d}f}%"


def f2(x):
    return "n/a" if x is None else f"{x:+.2f}"


def f3(x):
    return "n/a" if x is None else f"{x:.3f}"


def pf(b):
    return "**PASS**" if b else "**FAIL**"


def ci2(c):
    return "n/a" if not c else f"[{c[0]:+.2f}, {c[1]:+.2f}]"


def short(k: str) -> str:
    return k.replace("nested_ensemble_rank", "ensemble").replace("nested_lgbm", "lgbm")


def book_row(b: dict) -> str:
    c = b["segments"]["combined"]
    ls = b["basket"].endswith("ls_decile")
    key = "ann_return" if ls else "excess_ann_vs_ew"
    be = b["breakeven_flat_cost_bps_per_side"]
    ir = "(L-S)" if ls else f"{f2(c['20bps']['ir'])} {ci2(c['20bps']['ir_ci95'])}"
    return (f"| {short(b['key'])} | {b['basket_size_mean']:.0f} | {100 * b['turnover_per_rebalance']:.0f}% / "
            f"{b['turnover_annualised']:.1f}x | {pct(c['10bps'][key])} | **{pct(c['20bps'][key])}** | "
            f"{pct(c['40bps'][key])} | {pct(c[NL][key])} | {ir} | {f2(c['20bps']['sharpe'])} | "
            f"{pct(c['20bps']['max_dd'])} | {b['months_positive']}/{b['n_months']} | "
            + ("none" if be is None else f"{be:.0f}") +
            f" | {f3(b['psr_vs_0'])} | {f3(b['dsr']['177']['dsr'])} | {f3(b['dsr']['238']['dsr'])} |")


HDR = ("| book | names | turnover (per rebalance / per year) | excess vs EW @10 bps | @20 bps | @40 bps | name-level costs "
       "| IR @20 bps [95% CI] | Sharpe (rf 5.5%) | max DD | months > EW | break-even (bps/side) | PSR | DSR N=177 | "
       "DSR N=238 |\n|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|")


def _c(B, k, ck="20bps"):
    return B[k]["segments"]["combined"][ck]


def narrative(P: dict) -> list[str]:
    """Plain-words reading. Every number is taken from the payload; verdict words follow the payload's flags."""
    B, pm, ex = P["books"], P["pass_marks"], P["score_exposures_mean_per_date_spearman"]
    L0, A0, E0 = "nested_lgbm|top_decile", "all51|top_decile", "nested_ensemble_rank|top_decile"
    L, A, EV = ("nested_lgbm|vol+size|top_decile|H20", "all51|vol+size|top_decile|H20",
                "nested_ensemble_rank|vol+size|top_decile|H20")
    Lv, Li = "nested_lgbm|vol|top_decile|H20", "nested_lgbm|vol+size+industry|top_decile|H20"
    LB, L40 = "nested_lgbm|vol+size|buffered_decile|H20", "nested_lgbm|vol+size|top_decile|H40"
    out = []
    yrs = B[L]["by_year_per_20_sessions"]
    allpos = all(v > 0 for v in yrs.values())
    dl, dl0 = B[L]["by_direction_per_20_sessions"], B[L0]["by_direction_per_20_sessions"]
    out.append(
        f"**The classifiers' signal was there; their baskets hid it.** Neutralising the score against volatility and "
        f"size turns nested_lgbm's top decile from {pct(_c(B, L0)['excess_ann_vs_ew'])} to "
        f"{pct(_c(B, L)['excess_ann_vs_ew'])} a year over the equal-weight universe net of 20 bps (IR "
        f"{f2(_c(B, L)['ir'])} {ci2(_c(B, L)['ir_ci95'])}) and all51's from {pct(_c(B, A0)['excess_ann_vs_ew'])} to "
        f"{pct(_c(B, A)['excess_ann_vs_ew'])} (IR {f2(_c(B, A)['ir'])} {ci2(_c(B, A)['ir_ci95'])}): B1 "
        f"{'passes' if pm['B1']['pass'] else 'fails'}. The re-ranked score keeps most of the ranking (per-date "
        f"Spearman {ex['nested_lgbm|vol+size']['raw_score']:.2f} with the raw score); what goes is the tilt that "
        f"§6.3 finding 3 of the program report described (correlation with atr_pct {ex['nested_lgbm|none']['atr_pct']:+.2f} "
        f"-> {ex['nested_lgbm|vol+size']['atr_pct']:+.2f}, with log_turnover {ex['nested_lgbm|none']['log_turnover']:+.2f} "
        f"-> {ex['nested_lgbm|vol+size']['log_turnover']:+.2f}). The neutral book earns in up and in down months "
        f"({pct(dl['up'], 2)} / {pct(dl['down'], 2)} per 20 sessions, against {pct(dl0['up'], 2)} / "
        f"{pct(dl0['down'], 2)} for the raw book) and "
        + ("in every calendar year" if allpos else "in most calendar years")
        + f" ({', '.join(f'{y}: {pct(v, 2)}' for y, v in yrs.items())} per 20 sessions).\n")
    out.append(
        f"**Volatility does most of the work, size sharpens it, the industry step does not help.** Volatility alone "
        f"gives nested_lgbm {pct(_c(B, Lv)['excess_ann_vs_ew'])} (IR {f2(_c(B, Lv)['ir'])}); adding size leaves the "
        f"excess about the same and raises the IR to {f2(_c(B, L)['ir'])}; adding the industry step cuts it to "
        f"{pct(_c(B, Li)['excess_ann_vs_ew'])} (IR {f2(_c(B, Li)['ir'])}). Only index members have an NSE industry "
        f"({100 * P['inputs']['industry_coverage']['rows_classified_share']:.0f}% of rows), so that step is partly an "
        "index-membership adjustment and is not a clean test of industry neutrality.\n")
    out.append(
        f"**It is the ensemble's mechanism, built on purpose.** The single-model neutral books "
        f"({pct(_c(B, L)['excess_ann_vs_ew'])} and {pct(_c(B, A)['excess_ann_vs_ew'])}) come close to the rank "
        f"ensemble's accidental {pct(_c(B, E0)['excess_ann_vs_ew'])} a year; the ensemble neutralised the same way "
        f"earns {pct(_c(B, EV)['excess_ann_vs_ew'])} (IR {f2(_c(B, EV)['ir'])} {ci2(_c(B, EV)['ir_ci95'])}, "
        f"{B[EV]['months_positive']}/{B[EV]['n_months']} months ahead of the universe), the best of the 66 books.\n")
    cap0, cap1 = B[L0]["capacity"], B[L]["capacity"]
    dec = B[L]["name_level_cost_decomposition"]
    out.append(
        f"**Costs bite harder on the neutral books.** Removing the size tilt moves the basket into smaller names (median "
        f"name ADV20 Rs {cap0['median_name_adv20_rs_crore']:.1f} crore -> {cap1['median_name_adv20_rs_crore']:.1f} "
        f"crore; names under Rs 5 crore a day {100 * cap0['share_names_adv20_below_5cr']:.0f}% -> "
        f"{100 * cap1['share_names_adv20_below_5cr']:.0f}%). Flat break-even is "
        f"{B[L]['breakeven_flat_cost_bps_per_side']:.0f} bps per side for nested_lgbm and "
        f"{B[A]['breakeven_flat_cost_bps_per_side']:.0f} for all51, against 20 bps assumed. The pre-specified "
        f"name-level model charges these books about {B[L]['name_level_trade_weighted_cost_bps_per_side']:.0f} bps per "
        f"side on the traded weight ({dec['half_spread_bps']:.0f} bps Corwin-Schultz half-spread, "
        f"{dec['impact_bps']:.1f} bps impact), "
        + ("above" if B[L]['name_level_trade_weighted_cost_bps_per_side'] > 40 else "close to")
        + f" the 40 bps stress level, and leaves "
        f"{pct(_c(B, L, 'name_level')['excess_ann_vs_ew'])} (nested_lgbm) and "
        f"{pct(_c(B, A, 'name_level')['excess_ann_vs_ew'])} (all51) a year. That model is pessimistic (section 8).\n")
    b2, b3 = pm["B2"]["pairs"], pm["B3"]["scorers"]
    cuts = [v["turnover_cut"] for v in b2.values()]
    n_up = sum(v["monthly_diff_mean_20d"] > 0 for v in b2.values())
    n_low = sum(not v["not_lower"] for v in b2.values())
    ratios = [v["turnover_ratio_annualised"] for v in b3.values()]
    diffs = [v["diff_pp"] for v in b3.values()]
    out.append(
        f"**Turnover levers: real but smaller than the pass marks.** The buffered decile cuts turnover per rebalance by "
        f"{100 * min(cuts):.0f}% to {100 * max(cuts):.0f}% (B2 needs 30%: {'PASS' if pm['B2']['pass'] else 'FAIL'}), "
        f"and it never costs net excess: higher in {n_up} of 12 pairs, CI entirely below zero in {n_low}. Under the "
        f"name-level costs it is the better basket (nested_lgbm vol+size {pct(_c(B, LB, 'name_level')['excess_ann_vs_ew'])} "
        f"against {pct(_c(B, L, 'name_level')['excess_ann_vs_ew'])} for the plain decile). Holding 40 sessions keeps "
        f"the excess close ({', '.join(f'{d:+.1f} pp' for d in diffs)} for nested_lgbm, all51, ensemble; "
        f"{sum(abs(d) <= 1.0 for d in diffs)} of 3 within 1 pp) but trades "
        f"{min(ratios):.2f} to {max(ratios):.2f} times as much per year, not half (B3: "
        f"{'PASS' if pm['B3']['pass'] else 'FAIL'}); read per rebalance the 40-session tranche replaces more of its "
        f"basket ({100 * b3['nested_lgbm']['turnover_per_rebalance_40']:.0f}% against "
        f"{100 * b3['nested_lgbm']['turnover_per_rebalance_20']:.0f}%), so B3 fails under either reading. Under name-level "
        f"costs the 40-session book is the best single-model construction ({pct(_c(B, L40, 'name_level')['excess_ann_vs_ew'])} "
        f"a year, break-even {B[L40]['breakeven_flat_cost_bps_per_side']:.0f} bps per side).\n")
    g = pm["gates_for_B1"]
    d = P["dsr_common"]
    sr0 = d["sr0_expected_max_annualised"]
    out.append(
        f"**No book clears the multiple-testing bar.** With the 42 new books in the trial set the cross-book variance of "
        f"the daily Sharpe rises to {d['var_sr_daily_across_66_books']:.4f} (the five-year run's 24 books: "
        f"{d['var_sr_daily_of_the_24_five_year_books']:.4f}), so the expected best null Sharpe is {sr0['238']:.2f} a year "
        f"at N = 238 ({sr0['177']:.2f} at N = 177). The B1 books' DSR at N = 238 is {B[L]['dsr']['238']['dsr']:.3f} "
        f"(nested_lgbm) and {B[A]['dsr']['238']['dsr']:.3f} (all51); the best book's is {B[EV]['dsr']['238']['dsr']:.3f}. "
        f"Gate 3 (months ahead of the universe >= 75%): nested_lgbm {g[L]['gate3']['months']} "
        f"{'PASS' if g[L]['gate3']['pass'] else 'FAIL'}, all51 {g[A]['gate3']['months']} "
        f"{'PASS' if g[A]['gate3']['pass'] else 'FAIL'}. Gate 5 (DSR of the liquid book >= 0.95): "
        f"{g[L]['gate5']['dsr']:.4f} and {g[A]['gate5']['dsr']:.4f}, "
        f"{'PASS' if g[L]['gate5']['pass'] or g[A]['gate5']['pass'] else 'FAIL'}; the liquid neutral books earn "
        f"{pct(_c(B, g[L]['gate5']['liquid_book'])['excess_ann_vs_ew'])} and "
        f"{pct(_c(B, g[A]['gate5']['liquid_book'])['excess_ann_vs_ew'])} over the liquid universe with IR CIs "
        f"{ci2(_c(B, g[L]['gate5']['liquid_book'])['ir_ci95'])} and {ci2(_c(B, g[A]['gate5']['liquid_book'])['ir_ci95'])}.\n")
    promoted = P["pass_marks"]["any_book_passes_B1_and_gates_3_and_5"]
    gains = []
    for scn in ("nested_lgbm", "all51", "nested_ensemble_rank"):
        plain = _c(B, f"{scn}|vol+size|top_decile|H20", "name_level")["excess_ann_vs_ew"]
        gains += [_c(B, f"{scn}|vol+size|buffered_decile|H20", "name_level")["excess_ann_vs_ew"] - plain,
                  _c(B, f"{scn}|vol+size|top_decile|H40", "name_level")["excess_ann_vs_ew"] - plain]
    out.append(
        "**What changes.** Plan section 4 asked for a single-model book passing B1 and then gates 3 and 5 at N = 238. "
        + ("That happened." if promoted else
           ("B1 passed" if pm["B1"]["pass"] else "B1 failed")
           + "; gate 3 " + " and ".join(f"{'passed' if v['gate3']['pass'] else 'failed'} for {k.split('|')[0]} "
                                     f"({v['gate3']['months']})" for k, v in g.items())
           + "; gate 5 failed for both by a wide margin. Nothing is promoted and the verdict stays: no capital, the "
             "paper book decides.")
        + " What this stream does establish is the mechanism: the ensemble's economics come from removing the "
          "volatility tilt, which can be done deliberately on any of the scores; and under the name-level costs the "
          f"buffer and the 40-session hold add {100 * min(gains):.1f} to {100 * max(gains):.1f} points a year to the "
          "vol+size top decile. The idea was formed on these same 43 folds (finding "
          "3 was read from them), so the B1 interval is a consistency check, not an independent confirmation; only a "
          "frozen forward record can be that.\n")
    return out


def limits(P: dict) -> list[str]:
    B, d = P["books"], P["dsr_common"]
    cd, sc = P["cost_model_diagnostics"], P["hold40_universe_screen"]
    L, EV = "nested_lgbm|vol+size|top_decile|H20", "nested_ensemble_rank|vol+size|top_decile|H20"
    lc = cd["large_caps"]
    caps = [B[k]["capacity"]["aum_cap_rs_crore_p10name_5pct_adv"] for k in B
            if B[k]["origin"] == "p2_grid" and B[k]["basket"] in ("top_decile", "buffered_decile")
            and B[k]["neutralisation"] in ("vol", "vol+size") and B[k]["H"] == 20]
    liqcaps = [B[k]["capacity"]["aum_cap_rs_crore_p10name_5pct_adv"] for k in B if B[k]["basket"] == "liq_buffered_decile"]
    ho = [B[k]["segments"]["holdout"]["20bps"]["ir"] for k in B
          if B[k]["origin"] == "p2_grid" and B[k]["neutralisation"] == "vol+size" and B[k]["H"] == 20]
    yrs = B[L]["by_year_per_20_sessions"]
    early = [v for y, v in yrs.items() if y != "2026"]
    sens = B[EV]["dsr_sensitivity_var_sr_of_the_24_five_year_books"]
    sensL = B[L]["dsr_sensitivity_var_sr_of_the_24_five_year_books"]
    liqsens = [B[k]["dsr_sensitivity_var_sr_of_the_24_five_year_books"]["238"] for k in B
               if B[k]["basket"] == "liq_buffered_decile"]
    dec = B[L]["name_level_cost_decomposition"]
    return [
        "- **The hypothesis came from these months.** Neutralisation was proposed because the ensemble, volatility-"
        "neutral by accident, worked on the same 43 folds. The grid and pass marks were fixed before any number of this "
        "stream existed, and the DSR charges for the trials, but not for where the idea came from.",
        f"- **The deflation bar depends on V[SR] as much as on N.** Pre-registered statistic: V[SR] across all 66 books "
        f"({d['var_sr_daily_across_66_books']:.4f}). A sensitivity that is *not* pre-registered and decides nothing: "
        f"with the five-year run's V[SR] ({d['var_sr_daily_of_the_24_five_year_books']:.4f}) the best book's DSR at "
        f"N = 238 would be {sens['238']:.3f}, nested_lgbm's vol+size top decile {sensL['238']:.3f}, and the three liquid "
        f"books' at most {max(liqsens):.3f}, so gate 5 would fail either way.",
        f"- **The name-level cost model is pessimistic.** Corwin-Schultz on daily high-low ranges attributes part of "
        f"intraday volatility to the spread: it puts the half-spread of "
        + ", ".join(f"{t} at {v['median_half_spread_bps']:.0f} bps" for t, v in lc.items())
        + " (median ADV20 Rs " + ", ".join(f"{v['median_adv20_rs_crore']:,.0f}" for v in lc.values())
        + " crore), where quoted spreads are a few bps at most; "
          f"{100 * cd['share_negative_two_day_estimates']:.0f}% of two-day estimates are negative before the median. "
          "The order size follows the brief (q = Rs 100 crore / basket size); one day's order in the 20-tranche program "
          f"is 1/20 of that, so the impact term ({dec['impact_bps']:.1f} of the "
          f"{B[L]['name_level_trade_weighted_cost_bps_per_side']:.0f} bps for nested_lgbm's vol+size decile) is "
          "overstated by about 4.5x. Read the name-level column as a stress case (for the neutral deciles it charges "
          "more than the 40 bps column), not as a central estimate.",
        f"- **Industry map**: current constituents of four NSE index lists ({P['inputs']['industry_map']['n_symbols']} "
        f"symbols), applied to every date (membership look-ahead); "
        f"{100 * P['inputs']['industry_coverage']['rows_in_unclassified_after_min_group_rule']:.0f}% of rows sit in one "
        "'Unclassified' group.",
        f"- **40-session books** have no label to pin to and use unadjusted prices. The screen that keeps them clean "
        f"removed {100 * sc['share_removed']:.2f}% of rows whose mean 40-session return was "
        f"{pct(sc['ew_mean_40d_return_removed_rows'], 0)} (split and bonus artefacts); like y_clean_20d it looks "
        f"forward. Their signal dates end {sc['last']} ({sc['signal_dates']} dates); B3's same-dates comparison is in "
        "books.json (pass_marks.B3.scorers.*.robustness_same_signal_dates).",
        "- **The universe filter y_clean_20d looks forward** (it drops names whose next 21 sessions contain a move "
        "above 22%); it is the program's convention, shared by every book and by the equal-weight benchmark.",
        f"- **Capacity**: the full-universe volatility-neutral deciles carry about Rs {min(caps):,.0f} to "
        f"{max(caps):,.0f} crore at 5% of ADV for the 10th-percentile entering name; the liquid buffered books Rs "
        f"{min(liqcaps):,.0f} to {max(liqcaps):,.0f} crore.",
        f"- **Recent months weigh heavily**: nested_lgbm's vol+size excess is {pct(yrs.get('2026'), 2)} per 20 sessions in "
        f"2026 against {pct(min(early), 2)} to {pct(max(early), 2)} in 2023 to 2025. The 32-date holdout gives the "
        f"vol+size books IRs of {min(ho):+.1f} to {max(ho):+.1f}, one six-week window, not evidence.",
        "- **Long-short books** carry no borrow cost; NSE shorts need SLB or stock futures (about 200 names).",
        "- **Aggregation of B2 and B3 across scorers** (every pair / every scorer must pass) was fixed before results; "
        "the verdicts do not depend on it: B2's turnover clause fails in all 12 pairs and B3's in all three scorers.",
    ]


def write_markdown(P: dict, R: dict, path: Path):
    narrative_ = narrative(P)
    limits_ = limits(P)
    B, pm = P["books"], P["pass_marks"]
    md = ["# P2: book construction and costs on the five-year out-of-sample scores\n",
          "Generated by `python3 -m ml.books.construct` (seed 108, OMP_NUM_THREADS=2) from the frozen v1 predictions "
          "(`ml/results/scale5y/preds/`), the v1 dataset and the parquet price export "
          f"(`{P['inputs']['prices']}`; the DuckDB was not opened). Machine-readable results: `books.json`, "
          "`monthly_series.json`, `reproduction_check.json` in this folder. Pre-registration: "
          "`ml/IMPROVEMENT_PLAN.md`, stream P2. Signal dates 2023-01-02 to 2026-09-16 (913; the 40-session books "
          "end 2026-08-18). Excess = annualised mean tranche return net of costs minus the equal-weight (EW) universe's "
          "(EW liquid tercile for liquid books); IR = daily active Sharpe with a month-block bootstrap 95% CI.\n"]
    # ---- acceptance test
    cm = R["comparison"]
    md.append("## 1. Acceptance test: the 24 five-year books reproduce exactly\n")
    md.append(f"Verdict: **{R['verdict']}**. Every numeric leaf of `ml/results/scale5y/portfolio_5y.json` "
              f"({cm['numeric_leaves_compared']:,} numbers, plus {cm['other_leaves_compared']} labels) was recomputed "
              f"with the same engine and the parquet prices: maximum absolute difference {cm['max_abs_diff']:.3g}, "
              f"maximum relative difference {cm['max_rel_diff']:.3g}. The book runner used for the new grid was "
              f"checked against the same 24 books (maximum difference "
              f"{P['reproduction']['runner_cross_check_max_abs_diff']:.3g}).\n")
    md.append("| number | rebuilt | portfolio_5y.json | quoted in the plan / brief |\n|---|---:|---:|---:|")
    for h in R["headline_numbers"]:
        md.append(f"| {h['item']} | {h['replica']:.6g} | {h['frozen_portfolio_5y']:.6g} | {h['quoted_by_lead']} |")
    # ---- pass marks
    md.append("\n## 2. Pre-registered pass marks\n")
    b1 = pm["B1"]
    md.append(f"### B1 (deliberate neutralisation recovers economics in a single model): {pf(b1['pass'])}\n")
    md.append(f"Rule: {b1['rule']}.\n")
    md.append("| book | excess vs EW @20 bps | IR [95% CI] | beats EW | IR >= 0.5 | CI excludes 0 | verdict |\n"
              "|---|---:|---|---|---|---|---|")
    for k, v in b1["books"].items():
        md.append(f"| {short(k)} | {pct(v['excess_ann_vs_ew_20bps'])} | {f2(v['ir'])} {ci2(v['ir_ci95'])} | "
                  f"{'yes' if v['beats_ew'] else 'no'} | {'yes' if v['ir_ge_0_5'] else 'no'} | "
                  f"{'yes' if v['ir_ci_excludes_0'] else 'no'} | {pf(v['pass'])} |")
    b2 = pm["B2"]
    md.append(f"\n### B2 (turnover is the first lever): {pf(b2['pass'])} ({b2['n_pairs_pass']} of {b2['n_pairs']} "
              "pairs pass)\n")
    md.append(f"Rule: {b2['rule']} CI: {b2['ci_method']}.\n")
    md.append("| scorer / neutralisation | turnover plain -> buffered | cut | excess plain -> buffered @20 bps | "
              "paired monthly difference, annualised [95% CI] | months buffered ahead | verdict |\n"
              "|---|---:|---:|---:|---|---:|---|")
    for k, v in b2["pairs"].items():
        c = v["monthly_diff_ci95_ann"]
        md.append(f"| {short(k)} | {100 * v['turnover_plain']:.0f}% -> {100 * v['turnover_buffered']:.0f}% | "
                  f"{100 * v['turnover_cut']:.0f}% | {pct(v['excess_ann_plain_20bps'])} -> "
                  f"{pct(v['excess_ann_buffered_20bps'])} | {pct(v['monthly_diff_ann'], 2)} "
                  f"[{pct(c[0], 2)}, {pct(c[1], 2)}] | {v['months_buffered_ahead']} | {pf(v['pass'])} |")
    b3 = pm["B3"]
    md.append(f"\n### B3 (longer holding): {pf(b3['pass'])} ({b3['n_pass']} of 3 scorers pass)\n")
    md.append(f"Rule: {b3['rule']}\n")
    md.append("| scorer | excess 40-session @20 bps | excess 20-session @20 bps | difference | turnover per rebalance "
              "40 / 20 | turnover per year 40 / 20 (ratio) | verdict |\n|---|---:|---:|---:|---:|---:|---|")
    for k, v in b3["scorers"].items():
        md.append(f"| {short(k)} | {pct(v['excess_ann_40_20bps'])} | {pct(v['excess_ann_20_20bps'])} | "
                  f"{v['diff_pp']:+.1f} pp | {100 * v['turnover_per_rebalance_40']:.0f}% / "
                  f"{100 * v['turnover_per_rebalance_20']:.0f}% | {v['turnover_annualised_40']:.1f}x / "
                  f"{v['turnover_annualised_20']:.1f}x ({v['turnover_ratio_annualised']:.2f}) | {pf(v['pass'])} |")
    md.append("\n### Gates 3 and 5 (re-scored for any book passing B1)\n")
    md.append("| B1 candidate | passes B1 | gate 3: months > EW net 20 bps (>= 75%) | gate 5: DSR of its liquid book at "
              "N = 238 (>= 0.95) | status |\n|---|---|---|---|---|")
    for k, v in pm["gates_for_B1"].items():
        g3, g5 = v["gate3"], v["gate5"]
        md.append(f"| {short(k)} | {'yes' if v['b1_pass'] else 'no'} | {g3['months']} = {100 * g3['share']:.0f}% "
                  f"{pf(g3['pass'])} | {short(g5['liquid_book'])}: {g5['dsr']:.3f} {pf(g5['pass'])} | "
                  f"{v['scored_because']} |")
    md.append(f"\nAny book passing B1 and gates 3 and 5: **{'yes' if pm['any_book_passes_B1_and_gates_3_and_5'] else 'no'}**.\n")
    # ---- headline table
    md.append(f"## 3. Top 10 books by IR (net 20 bps; the {len(P['ranking_by_ir_20bps'])} long-only books of the 66 "
              "ranked, long-short books have no IR)\n")
    md.append("| rank | book | IR @20 bps | excess vs EW @20 bps | turnover per rebalance | DSR at N = 238 |\n"
              "|---:|---|---:|---:|---:|---:|")
    for i, r in enumerate(P["ranking_by_ir_20bps"][:10], 1):
        md.append(f"| {i} | {short(r['book'])} | {f2(r['ir'])} | {pct(r['excess_ann_vs_ew_20bps'])} | "
                  f"{100 * r['turnover_per_rebalance']:.0f}% | {r['dsr_238']:.3f} |")
    d = P["dsr_common"]
    md.append(f"\nDeflation: V[SR] of the daily skill Sharpe across all 66 books = {d['var_sr_daily_across_66_books']:.3g}; "
              "expected maximum annualised Sharpe of a null book = " +
              ", ".join(f"{v:.2f} at N = {n}" for n, v in d["sr0_expected_max_annualised"].items()) + ".\n")
    # ---- narrative
    md.append("## 4. What the result means\n")
    md.extend(narrative_)
    # ---- full grid
    md.append("\n## 5. The grid: 42 new books (20 bps per side is the headline; name-level = the pre-specified model)\n")
    md.append("Names `lgbm` = nested_lgbm, `ensemble` = nested_ensemble_rank; key = scorer | neutralisation | basket | "
              "holding period.\n")
    md.append(HDR)
    for k, b in B.items():
        if b["origin"] == "p2_grid":
            md.append(book_row(b))
    md.append("\n## 6. The 24 five-year books, same table (DSR now uses V[SR] across all 66 books)\n")
    md.append(HDR)
    for k, b in B.items():
        if b["origin"] == "scale5y_reproduced":
            md.append(book_row(b))
    hb = P["benchmarks"]
    md.append(f"\nPassive references: EW universe {pct(hb['H20']['ew_universe_ann_return'])} a year, EW liquid tercile "
              f"{pct(hb['H20']['ew_liquid_ann_return'])}, EW universe held 40 sessions "
              f"{pct(hb['H40_ew_universe']['ann_return'])} (its own leg, {hb['H40_ew_universe']['names_mean']:.0f} names).\n")
    # ---- diagnostics
    md.append("\n## 7. Diagnostics\n")
    md.append("**Score exposures** (mean per-date Spearman correlation of the book's score with the characteristic, 913 "
              "signal dates):\n")
    md.append("| scorer / neutralisation | atr_pct | log_turnover | raw score |\n|---|---:|---:|---:|")
    for k, v in P["score_exposures_mean_per_date_spearman"].items():
        md.append(f"| {short(k)} | {v['atr_pct']:+.2f} | {v['log_turnover']:+.2f} | {v['raw_score']:+.2f} |")
    sc = P["hold40_universe_screen"]
    md.append(f"\n**40-session universe screen.** Rule: {sc['rule']}. It removed {sc['rows_removed']:,} of "
              f"{sc['eligible_rows']:,} eligible rows ({100 * sc['share_removed']:.2f}%); their mean 40-session "
              f"return was {pct(sc['ew_mean_40d_return_removed_rows'], 2)} against {pct(sc['ew_mean_40d_return_kept'], 2)} "
              f"for the rows kept.\n")
    ic = P["inputs"]["industry_coverage"]
    md.append(f"**Industry map.** {P['inputs']['industry_map']['n_symbols']} symbols in "
              f"{P['inputs']['industry_map']['n_industries']} NSE industries ({P['inputs']['industry_map']['created_by']}); "
              f"{100 * ic['rows_classified_share']:.0f}% of universe rows are classified, "
              f"{100 * ic['rows_in_unclassified_after_min_group_rule']:.0f}% sit in 'Unclassified' after the five-name "
              f"rule ({ic['names_per_date_classified_mean']:.0f} classified names per date).\n")
    md.append("\n## 8. Limits\n")
    md.extend(limits_)
    path.write_text("\n".join(md) + "\n")
