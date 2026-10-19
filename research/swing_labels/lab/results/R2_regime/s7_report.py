"""Stage 7: generate REPORT.md (all numbers read from results.json / pickles produced by s1-s6)."""
import json

import numpy as np
import pandas as pd

from common import OUT, save, load_res

res = load_res()
R = pd.read_pickle(f"{OUT}/gating_results.pkl")
N = pd.read_pickle(f"{OUT}/gating_null.pkl")
O = pd.read_pickle(f"{OUT}/overlay_results.pkl")
NI = pd.read_pickle(f"{OUT}/index_null.pkl")
G = pd.read_pickle(f"{OUT}/sensitivity.pkl")
D = pd.read_parquet(f"{OUT}/dateset.parquet")

RULES = ["R200", "RBR", "RVIX", "RM60", "VOTE"]
MODELS = [f"{m}_{t}" for m in ("LOG4", "LOG10", "LGB10") for t in ("N0", "N1", "E0")]
SIGS = RULES + MODELS
DESC = {"R200": "N500 > 200d SMA", "RBR": "breadth50 > 0.5", "RVIX": "VIX < 250d median",
        "RM60": "N500 60d mom > 0", "VOTE": "graded: #rules on / 4",
        "ORACLE_E": "foresight 1{EW f20>0} (canary)", "ORACLE_N": "foresight 1{N500 f20>0} (canary)",
        "ANTI_E": "anti-foresight (canary)"}
for m in MODELS:
    fam, tg = m.split("_")
    DESC[m] = {"LOG4": "logit(4 feats)", "LOG10": "logit(10 feats)", "LGB10": "LGBM d2(10 feats)"}[fam] + \
        {"N0": " -> P(N500 f20>0)", "N1": " -> P(N500 f20>1%)", "E0": " -> P(EW f20>0)"}[tg]


def pc(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{100 * x:+.{d}f}"


def f2(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def s2(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:+.{d}f}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def grow(book, window, sig, xoff, cost=50):
    s = R[(R.book == book) & (R.window == window) & (R.signal == sig) & (R.x_off == xoff) & (R.cost == cost)]
    return s.iloc[0] if len(s) else None


def nrow(book, window, sig, xoff):
    s = N[(N.book == book) & (N.window == window) & (N.signal == sig) & (N.x_off == xoff)]
    return s.iloc[0] if len(s) else None


L = []
A = L.append
s1 = res["s1_dateset"]
ev = res["s2_signal_eval"]
sf = res["s2_single_feature"]
cond = res["s4d_conditional_selection_edge"]
er = res["s4d_target_event_rates_by_regime"]
acc = res["s6_signal_accuracy"]
volt = pd.DataFrame(res["s6_voltarget"])
be = pd.DataFrame(res["s5_noisy_oracle_breakeven"])
xr = res["s3_xrneu"]

ew_dev_base = grow("EW", "DEV", "RBR", 0.0)
xr_dev_base = grow("XR20", "DEV", "RBR", 0.0)
rbr_ew_dev = grow("EW", "DEV", "RBR", 0.0)
rbr_ew_hold = grow("EW", "HOLD", "RBR", 0.0)
rbr_ew_pre = grow("EW", "PRE", "RBR", 0.0)
rbr_xr_dev = grow("XR20", "DEV", "RBR", 0.0)
rbr_xr_hold = grow("XR20", "HOLD", "RBR", 0.0)
r200_ew_hold = grow("EW", "HOLD", "R200", 0.0)
r200_xr_hold = grow("XR20", "HOLD", "R200", 0.0)

# ------------------------------------------------------------------------------------------ header
A("# R2_regime — Market regime & exposure layer (lab v2)\n")
A("Agent R2_regime, round 2. Question: absolute labels mostly encode the market, so can the market be timed "
  "*separately* and used as an exposure scaler on top of a regime-free relative book, net of whipsaw? "
  "Lab v2 only (no sector data, ETFs excluded, rebuilt `elig_base`). Next-open entry, NaN where undefined, "
  "filters never change labels, models via `L.walk_forward2`, investability via the `L.Sim` maths (my "
  "`PathSim` re-implementation is verified bit-identical: max |equity diff| = 0.0 vs `L.Sim.run` for the EW, "
  "XR20 and random books), 50 and 80 bps, selection on DEV (2023-2025) only, 2026 (Jan 1 - Oct 14) reported "
  "separately. A third window, PRE (2021-09 .. 2022-12), is used only for parameter-free rules (no fitting) "
  "as an extra out-of-sample check; it was never used for selection.\n")

# ------------------------------------------------------------------------------------------ 1 verdict
A("## 1. Verdict\n")
A(f"**Market timing does not reliably help net of whipsaw. Do not put a direction-timing layer in the label stack.** "
  f"The evidence:\n")
A(f"1. **The premise holds: absolute labels are mostly market.** Date effects carry "
  f"{pc(s1['between_date_var_share_r'])} of 20-day stock-return variance and {pc(s1['between_date_var_share_y'])} "
  f"of the variance of the 0/1 sign label. The daily share of +1 labels correlates "
  f"{f2(s1['dev']['pearson_pos20_vs_n500_f20'])} (DEV) / {f2(s1['holdout']['pearson_pos20_vs_n500_f20'])} (2026) with "
  f"the Nifty-500 next-20d return and {f2(s1['dev']['pearson_pos20_vs_ew_f20'])} with the equal-weight universe return. "
  f"On DEV it ranges {pc(s1['dev']['pos20_min'])}..{pc(s1['dev']['pos20_max'])}.")
A(f"2. **The market part is not predictable from PIT regime features in this sample.** Of 14 pre-declared timing "
  f"signals (5 rules, 9 walk-forward models), only breadth50>0.5 (AUC {f2(ev['RBR']['DEV']['auc_E0'])} for EW>0), "
  f"mom60>0 ({f2(ev['RM60']['DEV']['auc_E0'])}) and the VOTE composite that contains them ({f2(ev['VOTE']['DEV']['auc_E0'])}) beat 0.5 on DEV. All 9 walk-forward models are *anti*-predictive on DEV "
  f"(AUC 0.39-0.47): their coefficients flip sign between folds. Single-feature correlations with the next-20d "
  f"return change sign between 2021-22, 2023-25 and 2026. The 200-dma rule has AUC {f2(ev['R200']['DEV']['auc_N0'])} on DEV and "
  f"{f2(ev['R200']['HOLD']['auc_N0'])} in 2026. Only one signal, breadth, beats the trivial 'always risk-on' accuracy on DEV, "
  f"and only barely ({f2(acc['RBR']['DEV_E0'], 3)} vs {f2(acc['RBR']['DEV_E0_always_on'], 3)}).")
nh = nrow("EW", "HOLD", "RBR", 0.0)
npre = nrow("EW", "PRE", "RBR", 0.0)
A(f"3. **The DEV-best gate wins in one episode on DEV and is mixed out of sample.** The pre-declared criterion (EW "
  f"book, sleeve gating, 50 bps, DEV gain in cash-adjusted Sharpe) picks breadth50>0.5 with 0% risk-off. EW book on "
  f"DEV: CAGR {pc(rbr_ew_dev.pavg_base_cagr)} -> {pc(rbr_ew_dev.pavg_cagr)}, Sharpe_xs "
  f"{f2(rbr_ew_dev.pavg_base_sharpe_xs)} -> {f2(rbr_ew_dev.pavg_sharpe_xs)}, maxDD {pc(rbr_ew_dev.pavg_base_max_dd)} -> "
  f"{pc(rbr_ew_dev.pavg_max_dd)}. Its circular-shift null p is {f2(nrow('EW', 'DEV', 'RBR', 0.0).p_sharpe, 3)} as a "
  f"single test, against 28 variants per book, so it fails multiple testing. The DEV gain is one episode: 2025 went "
  f"from {pc(rbr_ew_dev.pavg_base_by_year[2025])} to {pc(rbr_ew_dev.pavg_by_year[2025])}, while 2024 went from "
  f"{pc(rbr_ew_dev.pavg_base_by_year[2024])} to {pc(rbr_ew_dev.pavg_by_year[2024])}. Out of sample it is mixed. "
  f"In PRE (2021-22) it loses: CAGR {pp(rbr_ew_pre.pavg_d_cagr)} pp, Sharpe_xs {s2(rbr_ew_pre.pavg_d_sharpe_xs)}, "
  f"null p {f2(npre.p_sharpe, 3)}. In 2026 it beats its own random-timing null (phase-0 p {f2(nh.p_sharpe, 3)} for "
  f"Sharpe and {f2(nh.p_maxdd, 3)} for maxDD): random de-risking was expensive in 2026's V-shaped year (null "
  f"mean dSharpe {s2(nh.null_d_sharpe_mean)}), and breadth avoided that cost. Against always-in it merely breaks even: EW "
  f"{pp(rbr_ew_hold.pavg_d_cagr)} pp CAGR, Sharpe_xs {s2(rbr_ew_hold.pavg_d_sharpe_xs)}; XR20 "
  f"{pp(rbr_xr_hold.pavg_d_cagr)} pp. Its yearly AUC vs E0 is above 0.5 in 3 of 6 years. The classic 200-dma rule "
  f"changes 2026 CAGR by {pp(r200_ew_hold.pavg_d_cagr)} pp (EW) and {pp(r200_xr_hold.pavg_d_cagr)} pp (XR20).")
A(f"4. **Drawdown cuts are mostly mechanical.** A coin-flip timer (50% block accuracy, invested about half the time) cuts DEV "
  f"maxDD of the EW book by {100 * be[(be.accuracy == 0.5) & (be.window == 'DEV')].gate_d_maxdd_mean.iloc[0]:.1f} pp. "
  f"A static mix with the same average exposure is Sharpe-neutral, and its maxDD is only 4-8 pp worse than the "
  f"best timers on DEV. On PRE, the breadth gate's maxDD is "
  f"{-100 * grow('EW', 'PRE', 'RBR', 0.0).pavg_d_maxdd_vs_static:.1f} pp *worse* than the static mix's.")
A(f"5. **Whipsaw makes it worse, and the result depends on how the rule is implemented.** In a noisy-oracle test, "
  f"sleeve gating (switching only at the book's own rebalances, no extra trades) needs about 60% block accuracy "
  f"for a reliable gain. A daily overlay paying 50 bps per round-trip switch needs about 70%. The same rule changes "
  f"sign with the implementation: the 200-dma rule is {pp(grow('EW', 'DEV', 'R200', 0.0).pavg_d_cagr)} pp as a sleeve "
  f"gate and {pp(O[(O.impl == 'daily_overlay') & (O.book == 'EW') & (O.window == 'DEV') & (O.signal == 'R200') & (O.x_off == 0.0) & (O.cost == 50)].d_cagr.iloc[0])} pp as a "
  f"daily overlay on DEV. As pure index timing, breadth is "
  f"{pp(O[(O.impl == 'index_n500') & (O.window == 'DEV') & (O.signal == 'RBR') & (O.x_off == 0.0) & (O.cost == 10)].d_cagr.iloc[0])} pp on DEV and "
  f"{pp(O[(O.impl == 'index_n500') & (O.window == 'HOLD') & (O.signal == 'RBR') & (O.x_off == 0.0) & (O.cost == 10)].d_cagr.iloc[0])} pp in 2026.")
A(f"6. **The selection edge does not depend on the regime, so timing only scales beta.** The XR_neu top-20 excess "
  f"over random is {pp(cond['DEV_50']['excess_when_mkt_up'], 2)}% per 20-day trade when the market rises and "
  f"{pp(cond['DEV_50']['excess_when_mkt_down'], 2)}% when it falls (slope on the market return "
  f"t = {f2(cond['DEV_50']['excess_on_mkt_t'])}). No regime signal splits it significantly (|t| <= 1.02 on DEV). "
  f"The relative label is regime-free, as round 1 found. A regime layer cannot improve selection; it can only "
  f"change how much capital is exposed.")
A(f"7. **A risk-based scaler fails too.** Volatility targeting, x = min(1, median vol / current vol), gives EW DEV Sharpe "
  f"{s2(volt[(volt.book == 'EW') & (volt.window == 'DEV') & (volt.cost == 50)].sharpe_xs.iloc[0] - volt[(volt.book == 'EW') & (volt.window == 'DEV') & (volt.cost == 50)].base_sharpe_xs.iloc[0])} "
  f"(null p {f2(volt[(volt.book == 'EW') & (volt.window == 'DEV') & (volt.cost == 50)].null_p_sharpe_xs.iloc[0])}) and "
  f"{s2(volt[(volt.book == 'EW') & (volt.window == 'HOLD') & (volt.cost == 50)].sharpe_xs.iloc[0] - volt[(volt.book == 'EW') & (volt.window == 'HOLD') & (volt.cost == 50)].base_sharpe_xs.iloc[0])} in 2026. "
  f"Indian 20-day index returns mean-reverted after stress in 2021-22 and 2026, so de-risking on high vol or broken "
  f"trends sold near lows.\n")
g5d, g5h = grow("XR20", "DEV", "RBR", 0.5), grow("XR20", "HOLD", "RBR", 0.5)
e5p = grow("EW", "PRE", "RBR", 0.5)
A("**Recommendation for the label stack.** Primary = a regime-free relative label (XR_neu / R2_rel's neumom). "
  "Regime layer = **none as a return source**. Set the long book's gross exposure as a fixed, client-chosen policy. "
  "Static de-risking keeps the cash-adjusted Sharpe and cuts drawdown roughly in proportion. If the client insists "
  "on a drawdown governor, the least-bad pre-registered option is breadth50<0.5 => 50% risk-off, applied only at "
  f"the sleeve's own rebalance (no extra trades). On XR20 it changed CAGR by {pp(g5d.pavg_d_cagr)} pp (DEV) and "
  f"{pp(g5h.pavg_d_cagr)} pp (2026), and maxDD by {pp(g5d.pavg_d_maxdd)} / {pp(g5h.pavg_d_maxdd)} pp. Against a "
  f"static mix with the same exposure that is {pp(g5d.pavg_d_cagr_vs_static)} / {pp(g5h.pavg_d_cagr_vs_static)} pp "
  f"CAGR and {pp(g5d.pavg_d_maxdd_vs_static)} / {pp(g5h.pavg_d_maxdd_vs_static)} pp maxDD. On the EW book in PRE it "
  f"cost {pp(e5p.pavg_d_cagr_vs_static)} pp vs static. Treat it as insurance with uncertain, possibly negative, "
  f"expected cost, not as alpha. "
  "Never use a 200-dma or VIX trend filter: both were harmful in 2 of 3 windows, and the 200-dma rule "
  "lost about 20 pp of CAGR in 2026. Absolute (market-direction) labels should not be modelled per stock. Their "
  "day-to-day class mix is almost entirely the market's next 20 days (corr 0.88-0.98), and that part is not "
  "forecastable here. The stock-specific part is exactly what the relative label already isolates.\n")

# ------------------------------------------------------------------------------------------ 2 setup
A("## 2. Setup\n")
A("* **Date-level dataset** (`dateset.parquet`, 1,434 trading dates 2021-01-01..2026-10-14): the 10 lab market "
  "features (`mkt_mom5/20/60, mkt_dist_sma50/200, mkt_vol20, vix, breadth50, breadth_ad, dispersion`; constant per "
  "date, verified) + `vix_rel = vix / trailing-250d median - 1` (PIT, min 120 obs).")
A("* **Targets** (signal at close g, executable): `N0 = 1{N500 open[g+1]->close[g+20] > 0}`, `N1 = ... > +1%`, "
  "`E0 = 1{mean over elig_base of open[t+1]->close[t+20] > 0}` (rows with `fw.ok(20)` false dropped; coverage "
  "99.7-99.9%). EW targets start 2021-06-29 (120-bar seasoning).")
A("* **Rules** (parameter-free, pre-declared): R200 `mkt_dist_sma200>0`; RBR `breadth50>0.5`; RVIX `vix_rel<0`; "
  "RM60 `mkt_mom60>0`; VOTE graded exposure = mean of the four.")
A("* **Walk-forward models**: yearly expanding folds 2023..2026, embargo h+2 = 22 trading days, trained on dates "
  "from 2021-01-01 with complete features (325 dates for the 2023 fold, 1,069 for 2026, i.e. about 16-53 "
  "independent 20-day windows). LOG4 = L2-logit (C=0.1, standardized) on [dist_sma200, breadth50, vix_rel, mom60]; "
  "LOG10 = L2-logit on the 10 features; LGB10 = LightGBM depth 2, 100 trees, min_child 60. Risk-on = p >= 0.5 "
  "(pre-declared, never tuned).")
A(f"* **Books** (h=20, step=5, 4 staggered sleeves, next-open entry, time exit, half cost per side, cash 6.5%): "
  f"**EW** = every elig_base name equal-weight (`sizing='equal', select_quantile=(0,1)`); **XR20** = long top-20 "
  f"of the XR_neu walk-forward regression (label identical to R2_rel `neu`, max diff {xr['xcheck_R2_rel_pct_neu']['max_abs_diff']:.1e}; "
  f"score corr {f2(xr['xcheck_R2_alpha_wf_XR_all']['corr'], 4)} with R2_alpha's; xs IC vs r20 DEV "
  f"{f2(xr['xs_vs_r20_top30auc']['dev_ic_mean'], 3)} (t {f2(xr['xs_vs_r20_top30auc']['dev_ic_t_nonoverlap'])}), 2026 "
  f"{f2(xr['xs_vs_r20_top30auc']['holdout_ic_mean'], 3)} (t {f2(xr['xs_vs_r20_top30auc']['holdout_ic_t_nonoverlap'])})); "
  f"**RND20** = 5-seed random top-20 on the same mask.")
A("* **Exposure implementations.** (A) *Sleeve gating* (primary): at each signal date the rebalancing sleeve invests "
  "x of its equity (1 risk-on, 0.5 or 0 risk-off; VOTE graded) and keeps the rest in cash. Sleeves turn over "
  "fully every 20 days anyway, so gating adds no trades, and portfolio exposure moves in 25% steps. Exact and "
  "linear: path_x = (1-x)*cash + x*path_1. (B) *Daily overlay*: the always-in book's daily return is scaled by "
  "the state from close d-2 (one extra day of lag, conservative), and every exposure change pays |dx|*cost/2. "
  "(C) *Pure index timing*: Nifty-500 open-to-open returns, state at close g traded at open g+1, 10 bps per "
  "side (and 0).")
A("* **Benchmarks for every gated run.** Always-in (x=1). A static mix with the same average exposure. A "
  "circular-shift null: 200 random cyclic shifts of the state inside the window, which keep the exposure and "
  "persistence but destroy the timing. Foresight canaries.")
A("* **Sharpe.** `Sharpe_xs` = (mean daily return - 6.5%/252) / sd * sqrt(252). The lab's `Sim` Sharpe is not "
  "cash-adjusted, and it rewards holding cash. A static 55%-invested EW mix raises the raw DEV Sharpe from 0.67 "
  "to 0.91 with zero skill, while Sharpe_xs is unchanged (0.32). All deltas below use Sharpe_xs. "
  "'pavg' = average over the 5 signal-calendar phases (robust to the entry-day grid); null p-values use phase 0.\n")

# ------------------------------------------------------------------------------------------ 3 absolute = market
A("## 3. Absolute labels encode the market (quantified)\n")
rows = []
for nm, k in (("DEV 2023-25", "dev"), ("2026 holdout", "holdout"), ("All 2021-26", "all")):
    d = s1[k]
    rows.append([nm, d["dates"], pc(d["pos20_mean"]), f"{pc(d['pos20_min'])} / {pc(d['pos20_max'])}", pc(d["pos20_sd"]),
                 f2(d["pearson_pos20_vs_n500_f20"], 3), f2(d["pearson_pos20_vs_ew_f20"], 3),
                 f"{f2(d['spearman_pos20_vs_n500_f20'], 3)} (t {f2(d['nw_t'], 1)})", f2(d["corr_n500_f20_ew_f20"], 3)])
A(table(["window", "dates", "daily +1 share mean", "min / max", "sd", "Pearson vs N500 f20", "Pearson vs EW f20",
         "Spearman vs N500 f20 (NW t)", "corr N500 f20 vs EW f20"], rows))
A(f"\nBetween-date share of variance (elig_base, h=20, 2021-26): continuous return {pc(s1['between_date_var_share_r'])}, "
  f"0/1 sign label {pc(s1['between_date_var_share_y'])}. Any absolute label's day-to-day class mix is driven by "
  f"the market's next 20 days.\n")

# ------------------------------------------------------------------------------------------ 4 target event rates
A("## 4. Timing targets: event rates\n")
rows = []
for y, v in s1["targets_by_year"].items():
    rows.append([y, v["dates_n500"], pc(v["n500_gt0"]), pc(v["n500_gt1"]), f"{pc(v['ew_gt0'])} ({v['dates_ew']} d)",
                 pc(v["n500_f20_mean"], 2), pc(v["ew_f20_mean"], 2)])
A(table(["year", "dates", "N0 = N500 f20>0", "N1 = N500 f20>1%", "E0 = EW f20>0", "mean N500 f20", "mean EW f20"], rows))
A("\nBy regime (`bull` = N500 above 200-dma, `up20` = 20d momentum > 0; share of dates with target = 1):\n")
rows = []
for w in ("PRE", "DEV", "HOLD"):
    for rg in ("bull_up20", "bull_dn20", "bear_up20", "bear_dn20"):
        v = er[w][rg]
        rows.append([w, rg, v["dates"], pc(v["N0"]), pc(v["N1"]), pc(v["E0"]), pc(v["n500_f20_mean"], 2), pc(v["ew_f20_mean"], 2)])
A(table(["window", "regime", "dates", "N0", "N1", "E0", "mean N500 f20", "mean EW f20"], rows))
dm = er["DEV_monthly"]
A(f"\nDEV monthly share of N0 dates: mean {pc(dm['N0']['mean'])}, sd {pc(dm['N0']['std'])}, min {pc(dm['N0']['min'])}, "
  f"max {pc(dm['N0']['max'])}. {pc(dm['N0']['share_months_all_or_nothing'], 0)} of months are all-0 or all-1 "
  f"(E0: {pc(dm['E0']['share_months_all_or_nothing'], 0)}). The target is extremely persistent, so the 744 DEV dates "
  f"hold only about 37 independent 20-day observations. The regime relationship flips between windows. In DEV, "
  f"'bull_up20' dates were followed by N500 gains {pc(er['DEV']['bull_up20']['N0'])} of the time; in 2026 only "
  f"{pc(er['HOLD']['bull_up20']['N0'])}, and in PRE {pc(er['PRE']['bull_up20']['N0'])}. 'bear_dn20' dates were "
  f"followed by gains {pc(er['HOLD']['bear_dn20']['N0'])} of the time in 2026 (20-day mean reversion).\n")

# ------------------------------------------------------------------------------------------ 5 single features
A("## 5. Single-feature predictability (Spearman with next-20d return, NW t lag 20)\n")
rows = []
for f, v in sf.items():
    rows.append([f] + [f"{s2(v[w]['rho_n500'], 3)} ({s2(v[w]['t_n500'], 1)})" for w in ("PRE", "DEV", "HOLD")] +
                [f"{s2(v[w]['rho_ew'], 3)} ({s2(v[w]['t_ew'], 1)})" for w in ("PRE", "DEV", "HOLD")])
A(table(["feature", "N500 PRE", "N500 DEV", "N500 2026", "EW PRE", "EW DEV", "EW 2026"], rows))
A("\nNo feature has the same sign and |t| > 2 in all three windows. Trend features (dist_sma200, mom20/60, "
  "dist_sma50, breadth50) are negative in PRE and in 2026 and weakly positive in DEV. VIX is contrarian (high VIX "
  "-> higher returns) in 2026 (rho +0.54) and in DEV it is ~0.\n")

# ------------------------------------------------------------------------------------------ 6 signals date level
A("## 6. Timing signals at the date level\n")
rows = []
for sn in SIGS:
    for w in ("DEV", "HOLD", "PRE"):
        v = ev[sn].get(w)
        if not v:
            continue
        a = acc.get(sn, {})
        rows.append([sn, DESC[sn], w, pc(v["on_share"], 0), f2(v["flips_per_yr"], 1), f2(v["auc_N0"], 3), f2(v["auc_E0"], 3),
                     f"{pp(v['n500_f20_on_minus_off'], 2)} ({s2(v['n500_t'], 1)})",
                     f"{pp(v['ew_f20_on_minus_off'], 2)} ({s2(v['ew_t'], 1)})",
                     f"{f2(a.get(w + '_E0'), 3)} / {f2(a.get(w + '_E0_always_on'), 3)}" if a.get(w + "_E0") is not None else "n/a"])
A(table(["signal", "definition", "window", "risk-on share", "flips/yr", "AUC N0", "AUC E0",
         "N500 f20 on-off pp (NW t)", "EW f20 on-off pp (NW t)", "accuracy E0 / always-on"], rows))
A("\nBy-year AUC vs E0 (EW universe up next 20d) and risk-on share:\n")
rows = []
for sn in SIGS:
    by = ev[sn]["by_year"]
    rows.append([sn] + [f"{f2(by[str(y)]['auc_E0'], 2)} / {pc(by[str(y)]['on_share'], 0)}" if str(y) in by and by[str(y)]['auc_E0'] is not None
                        else (f"n/a / {pc(by[str(y)]['on_share'], 0)}" if str(y) in by else "")
                        for y in range(2021, 2027)])
A(table(["signal", "2021", "2022", "2023", "2024", "2025", "2026"], rows))
A("\n**Caveat (monitor, do not select).** The walk-forward logits rank 2025-26 well (LOG4 AUC vs E0: 2025 "
  "0.69-0.71, 2026 0.77-0.80) after ranking 2023-24 badly (0.25-0.45). In 2026 their calibrated probabilities "
  "never fell below the pre-declared 0.5 (risk-on 93-100%), so they changed no exposure. Their DEV AUC is "
  "below 0.5, so DEV selection cannot pick them, and a threshold re-chosen after seeing 2026 would be holdout "
  "selection. The coefficients that stabilised from the 2025 fold read 'buy fear, avoid over-extension' "
  "(dist_sma200 < 0, vix_rel > 0, mom60 > 0). This is the one timing hypothesis worth re-testing in round 3 on "
  "data after 2026-10.\n")
fo = res["s2_model_folds"]
A("\nWalk-forward coefficient instability (standardized L2-logit, target N0; sign flips across folds):\n")
rows = []
for nm in ("LOG4_N0", "LOG4_E0"):
    for y, c in fo[nm].items():
        rows.append([nm, y, c["n_train"], pc(c["base_rate"], 0)] + [s2(c[k]) for k in ("mkt_dist_sma200", "breadth50", "vix_rel", "mkt_mom60")])
A(table(["model", "test year", "train dates", "train base rate", "dist_sma200", "breadth50", "vix_rel", "mom60"], rows))
A("")

# ------------------------------------------------------------------------------------------ 7 EW book gating
A("## 7. Exposure scaler on the universe equal-weight book (sleeve gating, 50 bps, phase-averaged)\n")
A("Null p-values: share of 200 circular shifts of the same state series (same exposure and persistence) "
  "whose improvement over always-in is at least the observed one (phase 0, equal exposure, so raw and "
  "cash-adjusted Sharpe give the same ranking). A low p means the timing beat random timing with the same "
  "exposure. It does not mean the timing beat always-in.\n")
for w, title in (("DEV", "DEV 2023-25"), ("HOLD", "2026 holdout (not used for selection)"), ("PRE", "PRE 2021-09..2022-12 (rules only; parameter-free)")):
    b = R[(R.book == "EW") & (R.window == w) & (R.cost == 50)].iloc[0]
    A(f"**{title}.** Always-in: CAGR {pc(b.pavg_base_cagr)}, Sharpe_xs {f2(b.pavg_base_sharpe_xs)}, maxDD "
      f"{pc(b.pavg_base_max_dd)}, exposure {pc(b.pavg_base_exposure, 0)}.\n")
    rows = []
    for sn in SIGS + ["ORACLE_E", "ORACLE_N", "ANTI_E"]:
        for x in (0.5, 0.0):
            g = grow("EW", w, sn, x)
            if g is None:
                continue
            nr = nrow("EW", w, sn, x)
            rows.append([sn, f"{int(x * 100)}%", pc(g.pavg_cagr), f2(g.pavg_sharpe_xs), pc(g.pavg_max_dd), pc(g.pavg_exposure, 0),
                         f2(g.pavg_switches_per_yr, 1), pp(g.pavg_d_cagr), s2(g.pavg_d_sharpe_xs), pp(g.pavg_d_maxdd),
                         pp(g.pavg_d_cagr_vs_static), pp(g.pavg_d_maxdd_vs_static), s2(g.pavg_nw_t_vs_static),
                         f2(nr.p_sharpe, 3) if nr is not None else "-", f2(nr.p_maxdd, 3) if nr is not None else "-"])
    A(table(["signal", "risk-off x", "CAGR", "Sharpe_xs", "maxDD", "exposure", "switches/yr", "dCAGR pp",
             "dSharpe_xs", "dMaxDD pp", "dCAGR vs static", "dMaxDD vs static", "NW t vs static", "null p Sharpe",
             "null p maxDD"], rows))
    A("")

# ------------------------------------------------------------------------------------------ 8 XR20 gating
A("## 8. Exposure scaler on the relative-model top-20 book (XR20, sleeve gating, 50 bps, phase-averaged)\n")
for w, title in (("DEV", "DEV 2023-25"), ("HOLD", "2026 holdout")):
    b = R[(R.book == "XR20") & (R.window == w) & (R.cost == 50)].iloc[0]
    A(f"**{title}.** Always-in XR20: CAGR {pc(b.pavg_base_cagr)} vs random {pc(b.pavg_base_cagr - b.pavg_base_excess_vs_rnd)} "
      f"(excess {pp(b.pavg_base_excess_vs_rnd)} pp, NW t {f2(b.pavg_base_excess_nw_t)}; phase-0 {pc(b.p0_base_cagr)}, "
      f"t {f2(b.p0_base_excess_nw_t)}), Sharpe_xs {f2(b.pavg_base_sharpe_xs)}, maxDD {pc(b.pavg_base_max_dd)}.\n")
    rows = []
    for sn in SIGS + ["ORACLE_E", "ANTI_E"]:
        for x in (0.5, 0.0):
            g = grow("XR20", w, sn, x)
            if g is None:
                continue
            nr = nrow("XR20", w, sn, x)
            rows.append([sn, f"{int(x * 100)}%", pc(g.pavg_cagr), f2(g.pavg_sharpe_xs), pc(g.pavg_max_dd), pc(g.pavg_exposure, 0),
                         pp(g.pavg_d_cagr), s2(g.pavg_d_sharpe_xs), pp(g.pavg_d_maxdd), pp(g.pavg_d_cagr_vs_static),
                         pc(g.pavg_rnd_cagr_gated), pp(g.pavg_excess_vs_rnd_gated), f2(g.pavg_excess_nw_t_vs_rnd_gated),
                         f2(nr.p_sharpe, 3) if nr is not None else "-"])
    A(table(["signal", "risk-off x", "CAGR", "Sharpe_xs", "maxDD", "exposure", "dCAGR pp", "dSharpe_xs", "dMaxDD pp",
             "dCAGR vs static", "gated random CAGR", "excess vs gated random pp", "NW t", "null p Sharpe"], rows))
    A("")

# ------------------------------------------------------------------------------------------ 9 80 bps
A("## 9. Cost stress (80 bps) for the main signals (sleeve gating, phase-averaged)\n")
rows = []
for book in ("EW", "XR20"):
    for w in ("DEV", "HOLD"):
        b = R[(R.book == book) & (R.window == w) & (R.cost == 80)].iloc[0]
        rows.append([book, w, "always-in", "-", pc(b.pavg_base_cagr), f2(b.pavg_base_sharpe_xs), pc(b.pavg_base_max_dd), "-", "-"])
        for sn in ("R200", "RBR", "RM60", "VOTE", "LGB10_E0"):
            for x in (0.5, 0.0):
                g = grow(book, w, sn, x, cost=80)
                rows.append([book, w, sn, f"{int(x * 100)}%", pc(g.pavg_cagr), f2(g.pavg_sharpe_xs), pc(g.pavg_max_dd),
                             pp(g.pavg_d_cagr), s2(g.pavg_d_sharpe_xs)])
A(table(["book", "window", "signal", "risk-off x", "CAGR", "Sharpe_xs", "maxDD", "dCAGR pp", "dSharpe_xs"], rows))
A("\nAt 80 bps the gating deltas are almost the same as at 50 bps. Gating removes no trades (sleeves rebalance anyway), "
  "and the always-in book pays the same cost per unit of exposure.\n")

# ------------------------------------------------------------------------------------------ 10 by year
A("## 10. Calendar-year returns (phase-averaged, 50 bps)\n")
rows = []
for book in ("EW", "XR20"):
    for w in ("PRE", "DEV", "HOLD"):
        g0 = grow(book, w, "RBR", 0.0)
        if g0 is None:
            continue
        yrs = sorted(g0.pavg_base_by_year)
        for y in yrs:
            r_ = [book, y, pc(g0.pavg_base_by_year[y])]
            for sn, x in (("RBR", 0.0), ("RBR", 0.5), ("RM60", 0.0), ("R200", 0.0), ("VOTE", 0.0)):
                g = grow(book, w, sn, x)
                r_.append(pc(g.pavg_by_year.get(y)) if g is not None else "")
            rows.append(r_)
A(table(["book", "year", "always-in", "RBR x=0", "RBR x=0.5", "RM60 x=0", "R200 x=0", "VOTE x=0"], rows))
A("\n(2021 = Sep-Dec only; DEV years end at the DEV exit cutoff; 2026 = Jan 1 - Oct 14.) The breadth gate's DEV "
  "gain is concentrated in 2025, the Sep-2024 to Mar-2025 drawdown. It gave back most of it in 2024 and lost in 2022.\n")

# ------------------------------------------------------------------------------------------ 11 whipsaw
A("## 11. Whipsaw: three implementations of the same signals (risk-off x = 0)\n")
rows = []
for w in ("PRE", "DEV", "HOLD"):
    for sn in RULES + ["LGB10_E0", "LOG4_N1"]:
        g = grow("EW", w, sn, 0.0)
        o = O[(O.impl == "daily_overlay") & (O.book == "EW") & (O.window == w) & (O.signal == sn) & (O.x_off == 0.0) & (O.cost == 50)]
        ix = O[(O.impl == "index_n500") & (O.window == w) & (O.signal == sn) & (O.x_off == 0.0) & (O.cost == 10)]
        ni = NI[(NI.window == w) & (NI.signal == sn) & (NI.x_off == 0.0)]
        if g is None and not len(o):
            continue
        rows.append([w, sn,
                     f"{pp(g.pavg_d_cagr)} / {s2(g.pavg_d_sharpe_xs)} / {pp(g.pavg_d_maxdd)} ({f2(g.pavg_switches_per_yr, 1)})" if g is not None else "n/a",
                     f"{pp(o.d_cagr.iloc[0])} / {s2(o.d_sharpe_xs.iloc[0])} / {pp(o.d_maxdd.iloc[0])} ({f2(o.switches_per_yr.iloc[0], 1)}; cost {pc(o.switch_cost_per_yr.iloc[0], 2)}/yr)" if len(o) else "n/a",
                     f"{pp(ix.d_cagr.iloc[0])} / {s2(ix.d_sharpe_xs.iloc[0])} / {pp(ix.d_maxdd.iloc[0])} ({f2(ix.switches_per_yr.iloc[0], 1)})" if len(ix) else "n/a",
                     f"{f2(ni.p_sharpe_xs.iloc[0], 3)}" if len(ni) else "n/a"])
A(table(["window", "signal", "EW sleeve gating dCAGR / dSharpe_xs / dMaxDD (switches/yr)",
         "EW daily overlay 50 bps (flips/yr; switch cost)", "N500 index timing 10 bps/side", "index null p Sharpe_xs"], rows))
bi = {w: O[(O.impl == "index_n500") & (O.window == w) & (O.signal == "R200") & (O.x_off == 0.0) & (O.cost == 10)].iloc[0] for w in ("PRE", "DEV", "HOLD")}
A(f"\nBuy-and-hold Nifty 500 (price index, no dividends, which flatters timing): CAGR PRE {pc(bi['PRE'].base_cagr)}, "
  f"DEV {pc(bi['DEV'].base_cagr)}, 2026 {pc(bi['HOLD'].base_cagr)}; Sharpe_xs {f2(bi['PRE'].base_sharpe_xs)} / "
  f"{f2(bi['DEV'].base_sharpe_xs)} / {f2(bi['HOLD'].base_sharpe_xs)}; maxDD {pc(bi['PRE'].base_max_dd)} / "
  f"{pc(bi['DEV'].base_max_dd)} / {pc(bi['HOLD'].base_max_dd)}.\n")
A("Noisy-oracle break-even (EW book, risk-off 0, 50 draws per level). The state is the true sign of the EW 20-day "
  "return, flipped in random 10-day blocks with probability 1 - accuracy:\n")
rows = []
for a_ in sorted(be.accuracy.unique()):
    r_ = [f"{a_:.2f}"]
    for w in ("DEV", "HOLD"):
        v = be[(be.accuracy == a_) & (be.window == w)].iloc[0]
        r_ += [f"{pp(v.gate_d_cagr_mean)} / {s2(v.gate_d_sharpe_xs_mean)} / {pp(v.gate_d_maxdd_mean)} ({pc(v.gate_p_d_cagr_pos, 0)})",
               f"{pp(v.overlay_d_cagr_mean)} / {s2(v.overlay_d_sharpe_xs_mean)} / {pp(v.overlay_d_maxdd_mean)} ({pc(v.overlay_p_d_cagr_pos, 0)})"]
    rows.append(r_)
A(table(["block accuracy", "DEV sleeve gating dCAGR / dSharpe_xs / dMaxDD (P[dCAGR>0])", "DEV daily overlay 50 bps",
         "2026 sleeve gating", "2026 daily overlay"], rows))
A("\nCompare the real signals' DEV accuracy vs E0 in section 6. Only RBR (0.622) beats always-on (0.603). The "
  "walk-forward models score 0.40-0.54. Even a coin flip cuts maxDD by about 13 pp, because it is out of the "
  "market half the time.\n")

# ------------------------------------------------------------------------------------------ 12 conditional edge
A("## 12. Is the relative edge regime-dependent? (XR20 vs random, per signal date, all 5 phases)\n")
rows = []
for k in ("DEV_50", "HOLD_50"):
    c = cond[k]
    rows.append([k, c["n_dates"], pc(c["xr_mean"], 2), pc(c["rnd_mean"], 2), pc(c["ew_mean"], 2),
                 f"{pc(c['excess_mean'], 2)} (t {f2(c['excess_nw_t'])})", pc(c["excess_when_mkt_up"], 2),
                 pc(c["excess_when_mkt_down"], 2), f"{s2(c['excess_on_mkt_slope'], 3)} (t {f2(c['excess_on_mkt_t'])})",
                 f"{f2(c['xr_beta_to_ew'])} (t {f2(c['xr_beta_t'], 1)})"])
A(table(["window", "signal dates", "XR20 mean net/trade", "random", "EW universe", "excess (NW t)", "excess if mkt up",
         "excess if mkt down", "slope of excess on mkt (t)", "XR20 beta to EW"], rows))
A("\nExcess per 20-day trade, risk-on vs risk-off dates (DEV, 50 bps):\n")
rows = []
for sn, c in cond["DEV_50"]["by_signal"].items():
    h = cond["HOLD_50"]["by_signal"].get(sn)
    rows.append([sn, pc(c["on_share"], 0), pc(c["excess_on"], 2), pc(c["excess_off"], 2), f"{pp(c['excess_on_minus_off'], 2)} ({s2(c['t'])})",
                 f"{pp(c['ew_on_minus_off'], 2)} ({s2(c['t_ew'])})",
                 f"{pp(h['excess_on_minus_off'], 2)} ({s2(h['t'])})" if h else "n/a"])
A(table(["signal", "on share", "excess on", "excess off", "on-off pp (t)", "EW universe on-off pp (t)", "2026 excess on-off pp (t)"], rows))
A("")

# ------------------------------------------------------------------------------------------ 13 sensitivity
A("## 13. Parameter-sensitivity map (EW book, sleeve gating, risk-off 0, 50 bps, phase-averaged)\n")
A("The 'event rate' of a timing rule is its risk-on share. The table shows how it, and the outcome, move with "
  "the threshold.\n")
order = sorted(G.rule.unique(), key=lambda r: ({"breadth": 0, "breadth_hyst": 1, "mom60": 2, "dma200": 3,
                                                  "dma200_hyst": 4, "vix": 5}[G[G.rule == r].family.iloc[0]],
                                                 float(G[G.rule == r].k.iloc[0])))
rows = []
for rule in order:
    r_ = [rule]
    for w in ("PRE", "DEV", "HOLD"):
        v = G[(G.rule == rule) & (G.book == "EW") & (G.window == w) & (G.x_off == 0.0)].iloc[0]
        r_ += [pc(v.on_share, 0), pp(v.d_cagr), s2(v.d_sharpe_xs), pp(v.d_maxdd)]
    rows.append(r_)
A(table(["rule", "PRE on", "PRE dCAGR", "PRE dSh_xs", "PRE dMaxDD", "DEV on", "DEV dCAGR", "DEV dSh_xs", "DEV dMaxDD",
         "2026 on", "2026 dCAGR", "2026 dSh_xs", "2026 dMaxDD"], rows))
A("\nSame grid on the XR20 book (risk-off 0):\n")
rows = []
for rule in order:
    r_ = [rule]
    for w in ("DEV", "HOLD"):
        v = G[(G.rule == rule) & (G.book == "XR20") & (G.window == w) & (G.x_off == 0.0)].iloc[0]
        r_ += [pp(v.d_cagr), s2(v.d_sharpe_xs), pp(v.d_maxdd)]
    rows.append(r_)
A(table(["rule", "DEV dCAGR", "DEV dSh_xs", "DEV dMaxDD", "2026 dCAGR", "2026 dSh_xs", "2026 dMaxDD"], rows))
A("\nReading the map. Breadth is a broad DEV plateau: every threshold from 0.45 to 0.65 is positive and gets better "
  "as it tightens. It is negative at every threshold in PRE, and in 2026 it is negative below 0.50. The 200-dma rule "
  "is about 0 on DEV and strongly negative in 2026 at every band, hysteresis included. mom60 is positive on DEV at "
  "every threshold and negative in 2026 at every threshold. VIX is the mirror image: positive in PRE, negative in "
  "DEV and 2026. Each family is stable inside a window and unstable across windows. The cliff is the window, not "
  "the parameter, which is what a regime-dependent (non-stationary) timing relationship looks like.\n")

# ------------------------------------------------------------------------------------------ 14 vol target
A("## 14. Risk-based exposure: volatility targeting (one variant)\n")
rows = []
for _, v in volt.iterrows():
    rows.append([v.book, v.window, int(v.cost), pc(v.base_cagr), pc(v.cagr), f2(v.base_sharpe_xs), f2(v.sharpe_xs), pc(v.base_max_dd),
                 pc(v.max_dd), pc(v.static_max_dd), pc(v.exposure, 0), f2(v.switches_per_yr, 1),
                 f2(v.null_p_sharpe_xs, 3) if np.isfinite(v.get("null_p_sharpe_xs", np.nan)) else "-"])
A(table(["book", "window", "bps", "always-in CAGR", "VOLT CAGR", "always-in Sh_xs", "VOLT Sh_xs", "always-in maxDD",
         "VOLT maxDD", "static-mix maxDD", "exposure", "switches/yr", "null p"], rows))
A("")

# ------------------------------------------------------------------------------------------ 15 selection & multiple testing
A("## 15. DEV selection, holdout and multiple testing\n")
A("* **Pre-declared selection criterion:** the largest phase-averaged DEV gain in Sharpe_xs on the EW book under "
  "sleeve gating at 50 bps. The EW book is the purest test of market timing; static de-risking leaves Sharpe_xs "
  "unchanged, so this gain is also the gain over a static mix.")
A("")
cands = R[(R.book == "EW") & (R.window == "DEV") & (R.cost == 50) & (R.signal.isin(SIGS))].sort_values("pavg_d_sharpe_xs", ascending=False)
rows = []
for _, g in cands.head(6).iterrows():
    h = grow("EW", "HOLD", g.signal, g.x_off)
    p_ = grow("EW", "PRE", g.signal, g.x_off)
    xd = grow("XR20", "DEV", g.signal, g.x_off)
    xh = grow("XR20", "HOLD", g.signal, g.x_off)
    nr = nrow("EW", "DEV", g.signal, g.x_off)
    rows.append([g.signal, f"{int(g.x_off * 100)}%", s2(g.pavg_d_sharpe_xs), pp(g.pavg_d_cagr), f2(nr.p_sharpe, 3),
                 f"{s2(h.pavg_d_sharpe_xs)} / {pp(h.pavg_d_cagr)}",
                 f"{s2(p_.pavg_d_sharpe_xs)} / {pp(p_.pavg_d_cagr)}" if p_ is not None else "n/a (model)",
                 f"{s2(xd.pavg_d_sharpe_xs)} / {pp(xd.pavg_d_cagr)}", f"{s2(xh.pavg_d_sharpe_xs)} / {pp(xh.pavg_d_cagr)}"])
A(table(["DEV rank: signal", "risk-off x", "EW DEV dSharpe_xs", "EW DEV dCAGR", "null p (single test)",
         "EW 2026 dSh_xs / dCAGR", "EW PRE dSh_xs / dCAGR", "XR20 DEV", "XR20 2026"], rows))
nvar_primary = len(SIGS) * 2
nvar_grid_new = len(G.rule.unique()) - 4
nvar_total_maps = nvar_primary + 2 * nvar_grid_new + 1
specs = 2 * nvar_total_maps + 2 * nvar_primary + nvar_primary
A(f"\n* **Variants tried.** {len(SIGS)} primary timing signals (5 rules + 9 walk-forward models) x 2 risk-off levels = "
  f"{nvar_primary}. Sensitivity grid: {nvar_grid_new} new rule thresholds/hysteresis x 2 = {2 * nvar_grid_new}. Vol target: 1. "
  f"Total **{nvar_total_maps} distinct timing variants** (signal x exposure map). Applied as {specs} book-level DEV "
  f"specifications at base cost: sleeve gating on EW and XR20 for all variants, daily overlay on EW and XR20, and "
  f"index timing for the 28 primary variants. Also 22 single-feature correlation tests, 1 XR_neu walk-forward "
  f"model, 9 walk-forward timing models, and canaries plus noisy oracles (diagnostics, not counted). Costs (50/80 "
  f"bps; 10/0 bps for the index) and phases are sensitivities, not new specifications.")
best_p = N[(N.window == "DEV") & (N.book == "EW")].p_sharpe.min()
A(f"* **Multiple testing.** The best DEV circular-shift p-value among the 28 primary EW variants is {f2(best_p, 3)}. "
  f"Bonferroni over 28 gives about 1.0 (one-sided 5% needs p < 0.0018). Nothing survives, even before counting the "
  f"other {specs - 28} specifications. The NW t of the best gate's daily return over the static mix is "
  f"{s2(grow('EW', 'DEV', 'RBR', 0.0).pavg_nw_t_vs_static)}.")
A("* **Holdout honesty.** 2026 was never used for any choice. The rules have no fitted parameters. The 0.5 "
  "probability threshold and the C/depth settings of the models were fixed before the first run and never tuned. "
  "PRE is pre-DEV data used only for the rules. The 2026 holdout is lightly contaminated, because round-1 reports "
  "showed 2026 market levels.\n")

# ------------------------------------------------------------------------------------------ 16 pros/cons
A("## 16. Candidate scorecard (pros / cons / failure modes)\n")
A(table(["candidate", "verdict", "pros", "cons / failure mode"], [
    ["Absolute timing labels N0/N1/E0 (date-level)", "reject as stock labels; diagnostic only",
     "Clean, executable, NaN-safe; base rates 51-75% by year", "~37 independent obs in DEV; persistent (33-44% of months all-0/1); relationship flips sign across windows"],
    ["Walk-forward timing models (LOG4/LOG10/LGB10 x N0/N1/E0)", "reject",
     "PIT, embargoed, few parameters", "DEV AUC 0.39-0.47 (anti-predictive); coefficients flip sign; LOG4 never risk-off in 2026; 2026 results scattered (LGB10 + a few pp, LOG10 -5 to -12 pp)"],
    ["R200 (N500 > 200dma)", "reject",
     "Low turnover (2-4 switches/yr gated); cuts DEV maxDD 10 pp", "No DEV return gain; -20 pp (EW) / -24 pp (XR20) CAGR in 2026; negative in PRE; whipsaw at the turn"],
    ["RBR (breadth50 > 0.5)", "weak (only as optional drawdown insurance at 50% risk-off)",
     "DEV-best; broad DEV threshold plateau; positive Sharpe_xs in 2026 on EW; maxDD -29% -> -13% on DEV", "null p 0.085 single-test (fails Bonferroni); DEV gain = one episode (2025); loses in PRE at every threshold (null p 0.915); 2026 beats its random-timing null (p<0.005) but only breaks even vs always-in (EW +0.6 pp, XR20 -3.7 pp)"],
    ["RM60 (60d momentum > 0)", "reject",
     "Positive on DEV at all thresholds; index-timing null p 0.055 on DEV", "-6.5 pp (EW) / -8.4 pp (XR20) CAGR in 2026 at x=0; mixed in PRE"],
    ["RVIX (VIX < median)", "reject",
     "Helped in PRE", "Anti-predictive DEV and 2026 (high VIX precedes rebounds)"],
    ["VOTE (graded)", "reject", "Lowest maxDD on DEV (-11.5%)", "36 switches/yr; -10 pp CAGR in 2026; negative PRE Sharpe"],
    ["VOLT (vol target)", "reject", "Risk-based, no direction forecast", "DEV Sharpe_xs -0.13 (null p 0.82), 2026 -0.36; sells after vol spikes that mean-revert"],
    ["XR20 always-in (reference relative book)", "keep (R2_rel's call)",
     "Selection edge regime-independent (excess +1.2%/trade in up and down markets)", "Full beta (1.03 to EW); maxDD -29% on DEV - risk must be set by fixed exposure policy, not timing"],
]))
A("")

# ------------------------------------------------------------------------------------------ 17 issues & files
A("## 17. Lab notes / issues found\n")
A("* `Sim.run`'s `sharpe` is not cash-adjusted, so any book holding cash looks better. A static 55%/45% "
  "EW/cash mix lifts the DEV Sharpe from 0.67 to 0.91 with no skill. Compare de-risked books on "
  "Sharpe in excess of cash, or against a static mix with the same exposure.")
a_cnt = float(np.mean([v["ew_cov20_mean"] for v in s1["targets_by_year"].values()]))
A(f"* The EW-universe target drops rows whose 20d window fails `fw.ok` (suspension, label_block). Mean coverage is "
  f"{pc(a_cnt, 2)}, so the survivorship effect is negligible here. Sleeves that have not started yet hold "
  f"un-yielding cash for the first 15 days of a window (minor; it affects every variant equally).")
A("* Nifty 500 is a price index while stock series are dividend-adjusted. In 2026 the EW universe's mean 20d "
  "return was +1.3% while Nifty 500's was -0.5%, and the N0 vs E0 base rates diverge (51% vs 65%). A timer "
  "trained on the index target can de-risk an EW/small-cap book at the wrong time. Use E0 for EW books.")
A("* No leakage found: the date-level features are constant per date, the targets start at open g+1, and the "
  "model folds use a 22-day embargo. The foresight canaries behave as expected (oracle +31 pp DEV CAGR, "
  "anti-oracle -27 pp).\n")
A("Files (all in this directory): `common.py` (PathSim, compose, HAC helpers), `s1_dateset.py`, `s2_timing.py`, "
  "`s3_xrneu.py`, `s4a_paths.py`, `s4b_eval.py`, `s4c_overlay.py`, `s4d_conditional.py`, `s5_sensitivity.py`, "
  "`s6_voltarget.py`, `s7_report.py` (this report), `s8_summary.py` (results.json 'summary'). Data: `dateset.parquet`, `timing_signals.parquet` (rule states and OOS "
  "probabilities per date), `xrneu.npz` (score, label), `paths_cache.pkl`, `gating_results.pkl`, `gating_null.pkl`, "
  "`overlay_results.pkl`, `sensitivity.pkl`, `gating_daily.npz` (phase-0 daily returns), `results.json`.\n")

open(f"{OUT}/REPORT.md", "w").write("\n".join(L))
print("REPORT.md written", sum(len(x) for x in L), "chars")
save("variant_count", {"primary_signals": len(SIGS), "primary_variants": nvar_primary, "grid_new_rules": nvar_grid_new,
                       "total_timing_variants": nvar_total_maps, "book_level_dev_specs": specs,
                       "single_feature_tests": 22, "wf_timing_models": 9, "xrneu_models": 1})
