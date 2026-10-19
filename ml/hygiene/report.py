#!/usr/bin/env python3
"""HYGIENE.md for the P5 stream: every number is read from pbo.json, delivery_durability.json and
uniqueness.json in ml/results/improve/hygiene/ (nothing is recomputed here).

Run:  PYTHONDONTWRITEBYTECODE=1 python3 -m ml.hygiene.report
"""
from __future__ import annotations

import json
import time

from ml.hygiene.common import OUT, log

VARIANTS = [("primary_S16_drop_end", "**S = 16, drop end (reading)**"),
            ("sens_S16_drop_start", "S = 16, drop start"),
            ("sens_S16_near_equal_all_periods", "S = 16, all periods (blocks of 2–3)"),
            ("sens_S14_drop_end", "S = 14, drop end")]
ANALYSES = [("a_configurations_auc", "(a) Configurations: 9 models × monthly fold AUC"),
            ("b_books_all24", "(b) Books: 24 books × monthly net-of-20-bps value"),
            ("c_books_long_only16", "(c) Long-only books: 16 books × monthly net excess over EW")]
FEATS = ["deliv_pct_sma_20", "deliv_value_share_20"]


def f3(x, sign=True):
    return "n/a" if x is None else (f"{x:+.3f}" if sign else f"{x:.3f}")


def f4(x, sign=True):
    return "n/a" if x is None else (f"{x:+.4f}" if sign else f"{x:.4f}")


def ci(c, k=3):
    if c is None or c[0] is None:
        return "n/a"
    return f"[{c[0]:+.{k}f}, {c[1]:+.{k}f}]"


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def pbo_section(P: dict) -> list[str]:
    md = []
    md.append("## 1. Probability of backtest overfitting (`pbo.json`)\n")
    md.append("**Method.** CSCV (Bailey, Borwein, López de Prado & Zhu 2017), generic code in `ml/hygiene/pbo.py`. "
              "The T periods are cut into S = 16 contiguous blocks of equal length (L = T // 16 = 2), the remainder is "
              "dropped from the end, and all C(16, 8) = 12,870 in-sample/out-of-sample splits are enumerated. In each "
              "split the trial with the best in-sample statistic (mean fold AUC; Sharpe = mean / sd of the monthly "
              "series) is ranked among all M trials out of sample; r = (rank − 0.5) / M, logit = ln(r / (1 − r)); "
              "**PBO = share of logits ≤ 0**. Also: the degradation regression (OOS statistic of the in-sample best on "
              "its IS statistic), the probability of loss (OOS below zero skill, i.e. below 0 for returns and below "
              "0.5 for AUC, and below the median of the M trials), and first-order stochastic dominance of the "
              "in-sample best's OOS distribution over the pooled OOS distribution of all trials. A self-test "
              "(exact agreement with a brute-force loop; null simulations at the chance level; a known-skill "
              "simulation with mean PBO "
              f"{P['self_test']['skill']['mean_pbo']:.3f}) passed before any real input was read.\n")
    md.append(f"**Dropped months.** {P['dropped_periods_warning']}\n")
    md.append(f"**Near-duplicate trials.** {P['duplicate_trials_note']}\n")
    for key, title in ANALYSES:
        a = P["analyses"][key]
        md.append(f"### {title}\n")
        md.append(f"Input: {a['input']}. Statistic: {a['statistic']}.\n")
        md.append("| | " + " | ".join(v[1] for v in VARIANTS) + " |")
        md.append("|---|" + "---:|" * len(VARIANTS))
        rows = [
            ("periods used", lambda r: f"{r['design']['periods_used']} ({r['design']['first_used']}..{r['design']['last_used']})"),
            ("periods dropped", lambda r: str(r['design']['periods_dropped'])),
            ("**PBO (logit ≤ 0)**", lambda r: f"**{r['pbo']:.3f}**"),
            ("PBO strict (logit < 0) / mid-rank", lambda r: f"{r['pbo_strict_lt0']:.3f} / {r['pbo_mid_rank']:.3f}"),
            ("chance level of PBO (≤ 0 rule)", lambda r: f"{r['chance_level']['le_0']:.3f}"),
            ("logit mean / median / sd", lambda r: f"{r['logit']['mean']:+.2f} / {r['logit']['median']:+.2f} / {r['logit']['sd']:.2f}"),
            ("logit 5% / 95%", lambda r: f"{r['logit']['q05']:+.2f} / {r['logit']['q95']:+.2f}"),
            ("mean OOS rank fraction of IS-best", lambda r: f"{r['oos_rank_fraction_of_is_best']['mean']:.3f}"),
            ("IS-best: mean IS → mean OOS statistic", lambda r: f"{r['degradation']['is_best_stat']['mean']:.4f} → {r['degradation']['oos_best_stat']['mean']:.4f}"),
            ("degradation slope / intercept (R²)", lambda r: f"{r['degradation']['slope']:+.3f} / {r['degradation']['intercept']:+.3f} ({r['degradation']['r2']:.2f})"),
            ("P(OOS of IS-best below zero skill)", lambda r: f"{r['prob_loss']['below_zero_skill']:.3f}"),
            ("P(OOS of IS-best below trials' OOS median)", lambda r: f"{r['prob_loss']['below_oos_median_of_trials']:.3f}"),
            ("first-order dominance holds", lambda r: ("yes" if r['stochastic_dominance']['first_order_holds'] else
                                                     f"no (max CDF excess {r['stochastic_dominance']['max_F_best_minus_F_all']:.2g})")),
            ("second-order dominance holds", lambda r: "yes" if r['stochastic_dominance']['second_order_holds'] else "no"),
            ("mean OOS: IS-best vs all trials", lambda r: f"{r['stochastic_dominance']['mean_oos_is_best']:.4f} vs {r['stochastic_dominance']['mean_oos_all_trials']:.4f}"),
        ]
        for name, fn in rows:
            md.append(f"| {name} | " + " | ".join(fn(a[v[0]]) for v in VARIANTS) + " |")
        r = a["primary_S16_drop_end"]
        sel = sorted(r["trials"], key=lambda t: -t["share_combinations_selected_is_best"])[:5]
        md.append("\nWho is the in-sample best (primary partition): " + "; ".join(
            f"`{t['trial']}` {pct(t['share_combinations_selected_is_best'])} of splits (mean OOS rank fraction "
            f"{t['mean_oos_rank_fraction_when_selected']:.2f})" for t in sel if t["share_combinations_selected_is_best"] > 0) + ".\n")
        rd = P["readings"][key]
        md.append(f"**Pre-registered reading:** {rd['text']} "
                  f"**{'FAIL' if rd['above_0_5'] else 'PASS'}** (PASS = PBO not above 0.5).\n")
    st = P["self_test"]
    md.append("**Self-test** (`pbo.json` → `self_test`): brute-force agreement on 6 small cases "
              f"(max logit difference {max(x['max_abs_logit_diff'] for x in st['brute_force_agreement']):.1e}); "
              "null simulations (200 matrices each, T = 32, S = 16): " + "; ".join(
                  f"{k} mean PBO {v['mean_pbo_le0']:.3f} (expected {v['expected']['le_0']:.3f})" for k, v in st["null"].items())
              + f"; known-skill simulation mean PBO {st['skill']['mean_pbo']:.3f}. The M = 16 null value at seed 108 "
                "(0.540) was re-checked on independent seeds (0.494, 0.507; `log.txt`): sampling noise.\n")
    return md


def cellrow(r):
    t = "n/a" if r.get("nw_t") is None else format(r["nw_t"], "+.2f")
    return f"{f4(r['mean'])} | {t} | {ci(r.get('ci95'))}"


def delivery_section(Dl: dict) -> list[str]:
    md = ["## 2. Delivery durability (`delivery_durability.json`)\n"]
    m = Dl["method"]
    cov = Dl["coverage"]
    md.append("**Method.** " + m["universe"] + ". Per signal date (≥ 100 names), on the complete cases of feature, "
              "controls (`log_turnover`, `atr_pct`, `mom_12_1`) and label: IC = Spearman(feature, `y_excess_20d`); "
              "residual IC = Spearman of the residual of a per-date OLS of the feature's percentile rank on the "
              "controls' percentile ranks. Liquidity subsets re-rank inside the subset. Means over dates with a "
              "Newey-West t (20 lags) and a circular 20-session block-bootstrap 95% CI (B = 1000, seed 108). "
              f"Complete-case coverage: {pct(cov['deliv_pct_sma_20']['complete_case_share'])} "
              f"(`deliv_pct_sma_20`) and {pct(cov['deliv_value_share_20']['complete_case_share'])} "
              f"(`deliv_value_share_20`) of {cov['universe_rows']:,} universe rows; the loss is mostly names with "
              "under a year of history (`mom_12_1` missing). " + m["discovery_overlap_note"] + "\n")
    rel = Dl["relations_oos"]
    C = rel["mean_per_date_spearman"]
    md.append(f"The two features are nearly the same signal (mean per-date Spearman {C[0][1]:.2f}); both lean to "
              f"low-volatility and lower-turnover names (with `atr_pct` {C[0][3]:+.2f} / {C[1][3]:+.2f}, with "
              f"`log_turnover` {C[0][2]:+.2f} / {C[1][2]:+.2f}). The three controls explain on average "
              f"{pct(Dl['results']['deliv_pct_sma_20']['by_subset']['all']['mean_r2_controls_oos'], 0)} / "
              f"{pct(Dl['results']['deliv_value_share_20']['by_subset']['all']['mean_r2_controls_oos'], 0)} of the "
              "cross-sectional variance of the delivery rank.\n")
    hdr = "| feature | group | dates | IC | NW t | 95% CI | residual IC | NW t | 95% CI |\n|---|---|---:|---:|---:|---|---:|---:|---|"

    def table(title, subset, groups):
        out = [f"### {title}\n", hdr]
        for f in FEATS:
            R = Dl["results"][f]["by_subset"][subset]
            for g, lab in groups:
                a, b = R["ic"][g], R["resid_ic"][g]
                out.append(f"| `{f}` | {lab} | {a['n_dates']} | {cellrow(a)} | {cellrow(b)} |")
        return out + [""]

    years = [("oos_all", "OOS 2023-01-02..2026-09-16"), ("pre_oos_2022q4", "pre-OOS 2022-10..12"),
             ("year_2023", "2023"), ("year_2024", "2024"), ("year_2025", "2025"), ("year_2026", "2026 (to 09-16)")]
    md += table("By calendar year (all names)", "all", years)
    md.append("### By liquidity (whole OOS window; `cs_rank_turnover`)\n")
    md.append(hdr)
    for f in FEATS:
        for s, lab in [("tercile_low", "tercile < 0.33 (least liquid)"), ("tercile_mid", "tercile 0.33–0.67"),
                       ("tercile_high", "tercile ≥ 0.67 (most liquid)"), ("half_illiquid", "illiquid half < 0.5"),
                       ("half_liquid", "liquid half ≥ 0.5")]:
            R = Dl["results"][f]["by_subset"][s]
            md.append(f"| `{f}` | {lab} | {R['ic']['oos_all']['n_dates']} | {cellrow(R['ic']['oos_all'])} | "
                      f"{cellrow(R['resid_ic']['oos_all'])} |")
    md.append("")
    md += table("By market direction of the month (all names)", "all",
                [("direction_up", "up months"), ("direction_down", "down months")])
    md.append("Direction is `portfolio_5y.json` `direction_by_month`: the sign of the EW universe's forward 20-day "
              "return over the month's signal dates. It is known only after the month, so it describes, it does "
              "not time.\n")
    md.append("### Year × liquidity half and the most liquid tercile: IC and residual IC with 95% CI, by year and by market direction\n")
    cols = ["year_2023", "year_2024", "year_2025", "year_2026", "direction_up", "direction_down"]
    md.append("| feature | subset | statistic | 2023 | 2024 | 2025 | 2026 | up months | down months |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for f in FEATS:
        for s, lab in [("half_illiquid", "illiquid half"), ("half_liquid", "liquid half"), ("tercile_high", "most liquid tercile")]:
            for st, sl in [("resid_ic", "residual IC"), ("ic", "IC")]:
                R = Dl["results"][f]["by_subset"][s][st]
                md.append(f"| `{f}` | {lab} | {sl} | " + " | ".join(
                    f"{f3(R[c]['mean'])} {ci(R[c]['ci95'])}" for c in cols) + " |")
    md.append("")
    halves = [(f"half_{y}H{h}", f"{y} H{h}") for y in (2023, 2024, 2025, 2026) for h in (1, 2)]
    md += table("By calendar half-year (all names; 2026 H2 = July to 16 September)", "all", halves)
    md.append("Cells with fewer than 100 dates (2026 H2: 55; pre-OOS: 59) rest on about three 20-session blocks per "
              "bootstrap replicate; their intervals are indicative only.\n")
    md.append("### Pre/post March 2026 (all names; OOS dates < 2026-03-01 vs ≥ 2026-03-01)\n")
    md.append("| feature | statistic | before (dates) | after (dates) | after − before | 95% CI of difference | NW t of difference |")
    md.append("|---|---|---:|---:|---:|---|---:|")
    for f in FEATS:
        for st, sl in [("ic", "IC"), ("resid_ic", "residual IC")]:
            r = Dl["results"][f]["by_subset"]["all"]["prepost_march_2026"][st]
            md.append(f"| `{f}` | {sl} | {f4(r['mean_pre'])} ({r['n_pre']}) | {f4(r['mean_post'])} ({r['n_post']}) | "
                      f"{f4(r['diff_post_minus_pre'])} | {ci(r['diff_ci95'], 4)} | {r['diff_nw_t']:+.2f} |")
    md.append("")
    md.append("### Pre-registered reading\n")
    md.append("Durable = residual IC > 0 with the 95% block-bootstrap CI excluding zero in at least 3 of the 4 "
              "calendar years AND, over the whole OOS window, in both liquidity halves.\n")
    md.append("| feature | years passing (residual IC CI > 0) | illiquid half | liquid half | verdict | stricter check: ≥ 3 of 4 years inside each half |")
    md.append("|---|---|---|---|---|---|")
    for f in FEATS:
        rd = Dl["readings"][f]
        R = Dl["results"][f]["by_subset"]
        yr = ", ".join(f"{y} ({f3(R['all']['resid_ic'][f'year_{y}']['mean'])})" for y in rd["years_residual_ic_ci_above_zero"])
        hi = R["half_illiquid"]["resid_ic"]["oos_all"]
        hl = R["half_liquid"]["resid_ic"]["oos_all"]
        sx = rd["stricter_reading_year_x_half"]
        md.append(f"| `{f}` | {rd['n_years_pass']} of 4: {yr} | {f3(hi['mean'])} {ci(hi['ci95'])} | "
                  f"{f3(hl['mean'])} {ci(hl['ci95'])} | **{rd['verdict']}** | "
                  f"{'passes' if sx['passes'] else 'fails'} (illiquid {len(sx['years_pass_by_half']['half_illiquid'])}/4, "
                  f"liquid {len(sx['years_pass_by_half']['half_liquid'])}/4) |")
    md.append("")
    return md


def uniq_section(U: dict) -> list[str]:
    md = ["## 3. Label uniqueness, fold 2025-01 (`uniqueness.json`)\n"]
    m, w, A, B = U["method"], U["window"], U["distribution_training_rows"], U["sensitivity_concurrency_all_labeled_rows"]
    md.append(f"**Method.** Training window of fold {m['fold']} exactly as the harness builds it: "
              f"{m['window_first_session']}..{m['train_end']} ({m['window_sessions_inclusive']} sessions), labeled "
              f"clean rows, exit-date purge ({w['purged_exit_ge_test_start']} rows purged): **{w['training_rows']:,} rows, "
              f"{w['tickers']:,} tickers** (all tickers; it is cheap). Label span = sessions t+1..exit (the ticker's "
              f"own row t+21; {pct(w['share_span_21'], 2)} of spans are exactly 21 sessions). Concurrency = number of "
              "the same ticker's training rows whose span covers the session; average uniqueness = mean of "
              "1/concurrency over the row's span (López de Prado). Code checked against a brute-force loop on 25 "
              f"random tickers (max error {U['brute_force_check_max_abs_error_25_tickers']:.1e}).\n")
    md.append("| | training rows (the reading) | sensitivity: concurrency over every labeled row |")
    md.append("|---|---:|---:|")
    for k, lab in [("mean", "mean"), ("sd", "sd"), ("cv", "coefficient of variation"), ("p01", "1st percentile"),
                   ("median", "median"), ("p95", "95th percentile"), ("p99", "99th percentile"), ("max", "max")]:
        md.append(f"| {lab} | {A[k]:.4f} | {B[k]:.4f} |")
    md.append(f"| share exactly 1/21 | {pct(A['share_exactly_1_over_21'])} | {pct(B['share_exactly_1_over_21'])} |")
    md.append(f"| **share within ±10% of 1/21 = 0.0476** | **{pct(A['share_within_10pct_of_1_over_21'])}** | "
              f"{pct(B['share_within_10pct_of_1_over_21'])} |")
    md.append(f"| Kish weight efficiency (Σu)²/(N Σu²) | {A['kish_weight_efficiency']:.3f} | {B['kish_weight_efficiency']:.3f} |")
    md.append(f"| effective non-overlapping labels Σu | {A['effective_labels_sum_u']:,.0f} | {B['effective_labels_sum_u']:,.0f} |")
    md.append("")
    bp = U["by_position_in_window"]
    md.append("| position in the window | share of rows | mean uniqueness | share within ±10% of 1/21 |")
    md.append("|---|---:|---:|---:|")
    for k, lab in [("window_start_20_sessions", "first 20 sessions"), ("interior", "interior"),
                   ("window_end_20_sessions", "last 20 sessions")]:
        md.append(f"| {lab} | {pct(bp[k]['share_of_rows'])} | {bp[k]['mean_u']:.4f} | {pct(bp[k]['share_within_10pct'])} |")
    md.append("")
    wu, pe = U["who_is_up_weighted"], U["possible_effect_without_fit"]
    ua = pe["univariate_auc"]
    md.append(f"**Where the deviations sit.** Rows in the first and last 20 sessions of the window carry on average "
              f"{wu['mean_weight_multiplier_window_edges']:.2f} times the weight 1/21 of a fully overlapped row (their "
              "spans overlap fewer training labels). Inside the window, "
              f"{pct(U['interior_rows_deviating']['share_of_all_rows'])} of all rows deviate; an interior row can "
              "deviate only if the same ticker lacks a training row within 20 sessions of it (the name left the "
              "universe filter, its label was masked, it listed or delisted) or its span is longer than 21 sessions "
              f"({pct(U['interior_rows_deviating']['share_with_span_not_21'], 1)} of these rows). "
              f"{pct(wu['share_illiquid_half_among_interior_deviating_rows'], 0)} of the deviating interior rows are in "
              f"the illiquid half, against {pct(wu['share_illiquid_half_among_other_rows'], 0)} of the rows within "
              "±10% of 1/21.\n")
    md.append(f"**How much weights could move things, without a model fit** (training rows only, no test month): the "
              f"label base rate moves from {pe['label_base_rate']['unweighted']:.4f} to "
              f"{pe['label_base_rate']['uniqueness_weighted']:.4f}; the 50 features' univariate AUCs move by "
              f"{ua['mean_abs_delta']:.4f} on average and at most {ua['max_abs_delta']:.4f} "
              f"(`{ua['largest_deltas'][0]['feature']}` {ua['largest_deltas'][0]['auc_unweighted']:.4f} → "
              f"{ua['largest_deltas'][0]['auc_weighted']:.4f}), against a mean univariate edge |AUC − 0.5| of "
              f"{ua['mean_abs_auc_minus_half_unweighted']:.4f}; the ordering of features by edge is unchanged "
              f"(Spearman {ua['spearman_feature_order_weighted_vs_unweighted']:.2f}). The largest moves are in the "
              "volatility and turnover features: the weights mostly re-weight the first and last weeks of the "
              "window and the illiquid names at the edge of the universe; they do not correct an overlap that "
              "varies across the bulk of the rows. Moves of 0.005 are the size of this phase's A/B pass mark "
              "(+0.003), so the effect on a fitted model cannot be assumed away.\n")
    rd = U["reading"]
    md.append(f"**Pre-registered reading.** The plan fixed the consequence (near-constant ⇒ the item closes) but not "
              f"the threshold; this stream set it and wrote it in the code and `log.txt` before the computation "
              f"({rd['criterion']}). Share = {pct(rd['share_within_10pct'])} → "
              f"**{'near-constant: the item closes' if rd['near_constant'] else 'NOT near-constant: the item does not close on this evidence'}**.\n")
    return md


def main() -> None:
    P = json.loads((OUT / "pbo.json").read_text())
    Dl = json.loads((OUT / "delivery_durability.json").read_text())
    U = json.loads((OUT / "uniqueness.json").read_text())
    md = []
    md.append("# SuryaDhana improvement phase, stream P5: backtest overfitting, delivery durability, label uniqueness\n")
    md.append(f"**Date:** {time.strftime('%Y-%m-%d')} · **Owner:** hygiene stream (P5) · **Code:** `ml/hygiene/` "
              "(`pbo.py`, `delivery.py`, `uniqueness.py`, `report.py`) · **Numbers:** `pbo.json`, "
              "`delivery_durability.json`, `uniqueness.json` in this folder; run log `log.txt`. Inputs are the frozen "
              "five-year artefacts, read-only; `nse_market.duckdb` was not opened. Seed 108, 2 threads. Governing "
              "plan: `ml/IMPROVEMENT_PLAN.md` §2-P5 (readings fixed before any result). This stream adds no trial "
              "to the ledger: nothing here fits a model or scores a test month for selection.\n")
    md.append("## Pre-registered readings\n")
    md.append("| test | reading fixed in advance | result | verdict |")
    md.append("|---|---|---|---|")
    for key, title in ANALYSES:
        rd = P["readings"][key]
        md.append(f"| PBO {title.split(':')[0]} | PBO > 0.5 ⇒ selection no better than chance | PBO = {rd['pbo']:.3f} "
                  f"(other partitions {min(v for k, v in rd['sensitivity_pbo'].items() if k != 'primary_S16_drop_end'):.3f} "
                  f"to {max(v for k, v in rd['sensitivity_pbo'].items() if k != 'primary_S16_drop_end'):.3f}) | "
                  f"**{'FAIL' if rd['above_0_5'] else 'PASS'}**: selection {'no better than' if rd['above_0_5'] else 'better than'} chance |")
    for f in FEATS:
        rd = Dl["readings"][f]
        md.append(f"| Delivery `{f}` | residual IC CI > 0 in ≥ 3 of 4 years and in both liquidity halves | "
                  f"{rd['n_years_pass']} of 4 years; halves {'both' if all(rd['halves_residual_ic_ci_above_zero'].values()) else 'not both'} | "
                  f"**{rd['verdict']}** |")
    rdu = U["reading"]
    md.append(f"| Uniqueness, fold 2025-01 | near-constant (≥ 95% of rows within ±10% of 1/21) ⇒ weights cannot change the fit; item closes | "
              f"{pct(rdu['share_within_10pct'])} within ±10% | **{'PASS: closes' if rdu['near_constant'] else 'FAIL: stays open'}** |")
    md.append("")
    # management conclusions, numbers from the JSON
    b, c = P["analyses"]["b_books_all24"]["primary_S16_drop_end"], P["analyses"]["c_books_long_only16"]["primary_S16_drop_end"]
    a = P["analyses"]["a_configurations_auc"]["primary_S16_drop_end"]
    d1 = Dl["results"]["deliv_pct_sma_20"]["by_subset"]
    d2 = Dl["results"]["deliv_value_share_20"]["by_subset"]
    pp1 = d1["all"]["prepost_march_2026"]
    share = lambda r, pref: sum(t["share_combinations_selected_is_best"] for t in r["trials"] if t["trial"].startswith(pref))
    sel_a = share(a, "nested_lr_l2")
    sel_b = share(b, "nested_ensemble_rank|")
    sel_c = share(c, "nested_ensemble_rank|")
    A = U["distribution_training_rows"]
    md.append("## For management\n")
    md.append(f"1. **Choosing the best model or book from the five-year record was better than a coin toss, but the "
              f"winner's record overstates what it delivers next.** The in-sample winner finished at or below the "
              f"out-of-sample median in only {pct(a['pbo'], 0)} (models), {pct(b['pbo'], 0)} (all books) and "
              f"{pct(c['pbo'], 0)} (long-only books) of the 12,870 splits, against 50% to 56% for pure luck. The "
              f"winning model was usually the nested L2 logistic ({pct(sel_a, 0)} of splits); the winning books were "
              f"mostly the rank ensemble's ({pct(sel_b, 0)} of splits among all books, {pct(sel_c, 0)} among long-only "
              f"books). Their out-of-sample Sharpe was about "
              f"{b['degradation']['oos_best_stat']['mean'] / b['degradation']['is_best_stat']['mean']:.0%} (all books) and "
              f"{c['degradation']['oos_best_stat']['mean'] / c['degradation']['is_best_stat']['mean']:.0%} (long-only) of the "
              f"in-sample figure, and in {pct(c['prob_loss']['below_zero_skill'], 0)} of splits the winning long-only "
              "book lost to its benchmark out of sample. The ranking is informative; the size of past performance is "
              "inflated. This is consistent with paper-trading an ensemble book; it does not change the no-capital "
              "verdict.\n")
    md.append(f"2. **The delivery signal passes the durability test, but only the part that is not liquidity, "
              f"volatility or momentum.** That residual signal is positive with an interval clear of zero in "
              f"{Dl['readings']['deliv_pct_sma_20']['n_years_pass']} of 4 years (`deliv_pct_sma_20`) and "
              f"{Dl['readings']['deliv_value_share_20']['n_years_pass']} of 4 (`deliv_value_share_20`), in illiquid and "
              f"liquid names, and it did not weaken after March 2026 ({f3(pp1['resid_ic']['mean_pre'])} before, "
              f"{f3(pp1['resid_ic']['mean_post'])} after). The raw signal is less dependable: close to zero in 2023 "
              f"({f3(d1['all']['ic']['year_2023']['mean'])}) and in rising months ({f3(d1['all']['ic']['direction_up']['mean'])} "
              f"vs {f3(d1['all']['ic']['direction_down']['mean'])} in falling months), and its drop after March 2026 "
              f"({f3(pp1['ic']['mean_pre'])} to {f3(pp1['ic']['mean_post'])}) came from the part of delivery that "
              "volatility, turnover and momentum explain (delivery leans to low-volatility, lower-turnover names), "
              "not from the delivery-specific part. Among the most liquid third of stocks it is "
              f"essentially a falling-market effect (residual IC {f3(d1['tercile_high']['resid_ic']['direction_up']['mean'])} "
              f"in up months, {f3(d1['tercile_high']['resid_ic']['direction_down']['mean'])} in down months).\n")
    md.append(f"3. **Overlapping 20-day labels mean the {A['n_rows']:,} training rows of the 2025-01 fold hold only about "
              f"{A['effective_labels_sum_u']:,.0f} non-overlapping labels ({A['n_rows'] / A['effective_labels_sum_u']:.0f} "
              f"times fewer), and uniqueness weights do not fix that.** The weights equal 1/21 for {pct(A['share_exactly_1_over_21'], 0)} of rows and "
              "differ only at the edges of the training window and for illiquid names drifting in and out of the "
              f"universe. Because {pct(1 - A['share_within_10pct_of_1_over_21'], 1)} of rows deviate by more than 10%, "
              "more than the 5% allowed in advance, the item does not close on this evidence. The cheapest decisive "
              "next step is the plan's AB7 fit (every fifth signal date), or one uniqueness-weighted fit. Either "
              "would be a new trial.\n")
    md += pbo_section(P)
    md += delivery_section(Dl)
    md += uniq_section(U)
    md.append("## What this stream does not claim\n")
    md.append("- A low PBO does not show that the selected strategy has an edge. It shows that, inside this trial "
              "set, past rank predicted future rank more often than not. The set includes clearly weaker trials "
              "(momentum rules, the pilot's 10 features), which makes beating the median easier. The Deflated Sharpe "
              "(N = 177 for the five-year run, N = 239 in this phase after amendment A1) is still the hurdle, and no "
              "book clears it.\n")
    sens = [x for rd in P["readings"].values() for k, x in rd["sensitivity_pbo"].items() if k != "primary_S16_drop_end"]
    md.append("- The primary PBO uses 2023-01..2025-08 only (equal blocks of 2 months, remainder dropped from the end "
              f"as pre-specified). Across the three partitions that move or keep the dropped months, PBO ranges from "
              f"{min(sens):.3f} to {max(sens):.3f}, always below 0.5, so the reading does not depend on that choice.\n")
    md.append("- The delivery result is internal evidence on one market and one data source. 2025 and 2026 overlap "
              "the months in which both features were found, and 2023 is the weakest year. Market direction is an "
              "ex-post label.\n")
    md.append("- The uniqueness numbers describe one training window (fold 2025-01) and count overlap in time within "
              "a ticker only; the dependence among some 1,300 names whose labels cover the same 21 sessions is not in "
              "them. AB7 and any weighted fit were not run here: they are model fits, which belong to the lead's "
              "single compute queue.\n")
    (OUT / "HYGIENE.md").write_text("\n".join(md) + "\n")
    log(f"report: wrote {OUT / 'HYGIENE.md'}", "report")


if __name__ == "__main__":
    main()
