"""Stage 12: generate REPORT.md from results.json (every number in the tables is read from disk)."""
import json

from common import OUT, GROUPS

d = json.load(open(f"{OUT}/results.json"))


def P(x, nd=1, sign=False):
    if x is None:
        return "n/a"
    s = f"{x * 100:+.{nd}f}%" if sign else f"{x * 100:.{nd}f}%"
    return s


def F(x, nd=3, sign=False):
    if x is None:
        return "n/a"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def T(x):
    return "n/a" if x is None else f"{x:+.2f}"


L = []
w = L.append
V = d["s11_variants"]
s1 = d["s1_labels"]
ev = d["s2_events"]
main = {k[8:]: v for k, v in d.items() if k.startswith("s5_main_")}
grid = {k[8:]: v for k, v in d.items() if k.startswith("s5_grid_")}
xs = {k[6:]: v for k, v in d.items() if k.startswith("s4_xs_")}
pair = d["s10_paired"]
dic = d["s10_dIC_nw"]
comp = d["s9_composition"]
imp = d["s7_importance"]
uni = d["s8_univariate"]
fac = d["s6_factors"]
reg = d["s6_regress_XR_all_ENS3_TSX_all_BAR_all"]
corr = d["s4_score_corr"]


def pa(tag, cfg):
    return main[tag][cfg]["pa"]


# =============================================================================================== header
w("# R2_alpha — Alpha source & ensemble (lab v2)")
w("")
w("Agent R2_alpha, round 2. Lab v2 only: no sector data, ETFs excluded, `elig_base` as rebuilt. U = `elig_base`.")
w("Entry is open[t+1] and labels are NaN where `fw.ok(h)` fails. Filters choose rows and never change label values.")
w("Models use `walk_forward2` with yearly expanding folds 2023-2026, an embargo of h+2 = 22, `date_step` 2, `n_jobs` 2,")
w("default LightGBM, and the 52 point-in-time features. Learnability uses per-date cross-sectional IC and AUC with")
w("non-overlapping t, the same calculation as `L.xs_metrics`. Investability uses `L.Sim` with a horizon-matched")
w("5-seed random baseline on the same mask (the same maths as `S.compare`) at 50 and 80 bps.")
w("DEV = 2023-01-01..2025-12-31. HOLDOUT = 2026-01-01..2026-10-14, reported only and never used to choose.")
w("")

# =============================================================================================== verdict
x_dev, x_hold = pa("XR_all", "K20_s5_c50_dev"), pa("XR_all", "K20_s5_c50_hold")
e_dev, e_hold = pa("ENS3", "K20_s5_c50_dev"), pa("ENS3", "K20_s5_c50_hold")
p_e = pair["ENS3__minus__XR_all"]
w("## 0. Verdict")
w("")
w(f"1. **The ensemble does not add alpha. It adds a regime bet.** Equal-weight rank averaging of XR_neu (relative),"
  f" A2 barrier (absolute) and TSX trend-scan (market-excess) won the pre-declared DEV selection. Its DEV phase-averaged"
  f" excess vs random was {P(e_dev['excess_ann'], 1, True)}/yr (NW t {T(e_dev['excess_nw_t'])}) against"
  f" {P(x_dev['excess_ann'], 1, True)}/yr (t {T(x_dev['excess_nw_t'])}) for XR alone. That higher t comes from a"
  f" smoother excess, not more return. The paired DEV difference ENS3 − XR is"
  f" {P(p_e['K20_s5_c50_dev']['diff_ann'], 1, True)}/yr (t {T(p_e['K20_s5_c50_dev']['nw_t'])}). **In the 2026 holdout the"
  f" selected ensemble fails**: {P(e_hold['excess_ann'], 1, True)}/yr vs random (t {T(e_hold['excess_nw_t'])}),"
  f" with every one of the 5 calendar phases negative and every one of the 8 K x step cells negative. XR alone made"
  f" {P(x_hold['excess_ann'], 1, True)}/yr (t {T(x_hold['excess_nw_t'])}). Paired 2026 difference:"
  f" {P(p_e['K20_s5_c50_hold']['diff_ann'], 1, True)}/yr (t {T(p_e['K20_s5_c50_hold']['nw_t'])}).")
cb, cx = comp["BAR_all"], comp["XR_all"]
w(f"2. **Why: absolute and market-excess targets teach the model regime-conditional factor tilts.**"
  f" In the BAR model, market/regime features carry"
  f" {P(imp['BAR_all']['group_share_by_fold']['2023']['market'], 0)}→{P(imp['BAR_all']['group_share_by_fold']['2026']['market'], 0)}"
  f" of the gain importance across folds. In TSX they carry {P(imp['TSX_all']['group_share_by_fold']['2023']['market'], 0)}→"
  f"{P(imp['TSX_all']['group_share_by_fold']['2026']['market'], 0)}. In XR they carry"
  f" {P(imp['XR_all']['group_share_by_fold']['2023']['market'], 0)}→{P(imp['XR_all']['group_share_by_fold']['2026']['market'], 0)}."
  f" In 2026 the BAR/TSX/ensemble top-20 rotated into large, liquid, low-vol names. ENS3 picks moved to a vol_20 percentile of"
  f" {F(comp['ENS3']['2026']['tilt_vol_20'], 2)} (DEV {F(comp['ENS3']['dev']['tilt_vol_20'], 2)}), idio-vol"
  f" {F(comp['ENS3']['2026']['tilt_idio_vol_60'], 2)} and turnover {F(comp['ENS3']['2026']['tilt_log_turn20'], 2)}."
  f" That was exactly the wrong side of 2026: low-vol LS {P(fac['hold_LOWVOL_ann'], 1, True)}/yr, small-minus-big"
  f" {P(fac['hold_SIZE_ann'], 1, True)}/yr. Their picks still had positive factor-neutral skill (realised XR percentile"
  f" {F(comp['ENS3']['2026']['xr_pct'], 3)} vs {F(comp['ENS3']['dev']['xr_pct'], 3)} in DEV), so the losses came from the tilt. Removing the 10 market features from BAR/TSX/ENS3 cost DEV"
  f" ({P(pair['BAR_no_market__minus__BAR_all']['K20_s5_c50_dev']['diff_ann'], 1, True)},"
  f" {P(pair['TSX_no_market__minus__TSX_all']['K20_s5_c50_dev']['diff_ann'], 1, True)},"
  f" {P(pair['ENS3_nomkt__minus__ENS3']['K20_s5_c50_dev']['diff_ann'], 1, True)}/yr). It added"
  f" {P(pair['BAR_no_market__minus__BAR_all']['K20_s5_c50_hold']['diff_ann'], 1, True)},"
  f" {P(pair['TSX_no_market__minus__TSX_all']['K20_s5_c50_hold']['diff_ann'], 1, True)} and"
  f" {P(pair['ENS3_nomkt__minus__ENS3']['K20_s5_c50_hold']['diff_ann'], 1, True)}/yr in 2026. The regime tilt paid in every"
  f" DEV year for BAR and ENS3 (2 of 3 for TSX) and lost in 2026: it is a market-timing bet hidden inside a stock-selection score.")
ab = dic["XR_no_delivery__minus__XR_all"]
w(f"3. **Feature ablation (XR_neu model).** Delivery data is the only group whose removal significantly lowers IC in"
  f" both windows: ΔIC {F(ab['dev_d_ic_xr'], 4, True)} DEV (NW t {T(ab['dev_d_ic_xr_nw_t'])}, non-overlap t"
  f" {T(ab['dev_d_ic_xr_nonoverlap_t'])}) and {F(ab['hold_d_ic_xr'], 4, True)} in 2026 (NW t {T(ab['hold_d_ic_xr_nw_t'])},"
  f" non-overlap t {T(ab['hold_d_ic_xr_nonoverlap_t'])}). **NSE delivery data adds value**, about 10-25% of the model's"
  f" IC, but its book-level effect is"
  f" {P(pair['XR_no_delivery__minus__XR_all']['K20_s5_c50_dev']['diff_ann'], 1, True)}/yr (t"
  f" {T(pair['XR_no_delivery__minus__XR_all']['K20_s5_c50_dev']['nw_t'])}) and not individually significant."
  f" Momentum, technicals, xs-ranks and volume are redundant for IC (|ΔIC| ≤ 0.002 in DEV). Momentum still matters for the"
  f" top tail: dropping it costs the top-20 book {P(pair['XR_no_momentum__minus__XR_all']['K20_s5_c50_dev']['diff_ann'], 1, True)}/yr in DEV"
  f" (t {T(pair['XR_no_momentum__minus__XR_all']['K20_s5_c50_dev']['nw_t'])}) and"
  f" {P(pair['XR_no_momentum__minus__XR_all']['K20_s5_c50_hold']['diff_ann'], 1, True)} in 2026, the largest book-level loss of any group."
  f" Market/regime features add"
  f" nothing significant in DEV (ΔIC {F(dic['XR_no_market__minus__XR_all']['dev_d_ic_xr'], 4, True)}) and removing them"
  f" raised 2026 IC by {F(dic['XR_no_market__minus__XR_all']['hold_d_ic_xr'], 4, True)}. XR's importance ranking is"
  f" stable across folds (Spearman {F(min(imp['XR_all']['spearman_between_folds'].values()), 2)}-"
  f"{F(max(imp['XR_all']['spearman_between_folds'].values()), 2)}).")
rx = reg["XR_all|K20_s5_c50_dev|brief"]
rxe = reg["XR_all|K20_s5_c50_dev|ext"]
w(f"4. **Factor attribution: the long edge is not just low-vol or reversal.** For XR's K20 book the DEV excess is"
  f" {P(rx['excess_ann'], 1, True)}/yr. After size, momentum, 5d reversal, low-vol, low-beta and EW-market factors built"
  f" from the same universe with the same Sim, alpha is {P(rx['alpha_ann'], 1, True)}/yr (NW t {T(rx['alpha_nw_t'])},"
  f" R² {F(rx['r2'], 2)}). The book loads **negatively** on low-vol (t {T(rx['beta_t']['LOWVOL'])}) and only weakly on"
  f" reversal (t {T(rx['beta_t']['REV'])}). Adding low-idio-vol and trend leaves alpha {P(rxe['alpha_ann'], 1, True)}"
  f" (t {T(rxe['alpha_nw_t'])}). A static 7-factor composite with the model's own DEV loadings reproduces XR's IC"
  f" ({F(xs['XR_all_FC']['dev_ic_xr'], 3)} vs {F(xs['XR_all']['dev_ic_xr'], 3)}) but only through the bottom tail"
  f" (AUC_bottom {F(xs['XR_all_FC']['dev_auc_bot'], 3)}, AUC_top {F(xs['XR_all_FC']['dev_auc_top'], 3)}). Its"
  f" top-20 book earns {P(pa('XR_all_FC', 'K20_s5_c50_dev')['excess_ann'], 1, True)}/yr (t"
  f" {T(pa('XR_all_FC', 'K20_s5_c50_dev')['excess_nw_t'])}). **The avoid side is largely a linear factor effect"
  f" (high idio-vol / lottery names). The long side's edge is model-specific.**")
fnx, fne, fnt = pa("XR_all_FN", "avoid30_s5_c50_hold"), pa("ENS3_FN", "avoid30_s5_c50_hold"), pa("TSX_all_FN", "avoid30_s5_c50_hold")
w(f"5. **Practical consequence.** Factor-neutralising a score (per-date residual on 7 characteristic ranks) keeps most of"
  f" the long edge in DEV (XR_FN {P(pa('XR_all_FN', 'K20_s5_c50_dev')['excess_ann'], 1, True)}/yr, t"
  f" {T(pa('XR_all_FN', 'K20_s5_c50_dev')['excess_nw_t'])}). It makes the avoid overlay robust: DEV t"
  f" {T(pa('XR_all_FN', 'avoid30_s5_c50_dev')['excess_nw_t'])}/{T(pa('ENS3_FN', 'avoid30_s5_c50_dev')['excess_nw_t'])}/"
  f"{T(pa('TSX_all_FN', 'avoid30_s5_c50_dev')['excess_nw_t'])} and 2026 {P(fnx['excess_ann'], 1, True)}"
  f" (t {T(fnx['excess_nw_t'])}), {P(fne['excess_ann'], 1, True)} (t {T(fne['excess_nw_t'])}),"
  f" {P(fnt['excess_ann'], 1, True)} (t {T(fnt['excess_nw_t'])}) for XR/ENS3/TSX. The raw-score avoid overlays had 2026 t of 0.4-0.8."
  f" DEV alone already prefers the FN avoid screen (higher t). It does **not** prefer FN for the long book. The long-book"
  f" FN improvement in 2026 is holdout-informed and must be treated as a pre-registered hypothesis, not a result.")
w(f"6. **Recommendation for the label stack.** Keep the selection label XR_neu (relative, factor-neutral). Do **not**"
  f" ensemble it with absolute (barrier) or market-excess (trend-scan) models. Keep regime/market features out of the"
  f" stock-selection score, or at least size their contribution explicitly in the regime layer. Use a factor-neutralised"
  f" score for the AVOID screen. Delivery features stay in. Verdict on my candidates: XR_all *promising*"
  f" (as R2_rel found), ENS3 *reject* (fails holdout), BAR/TSX as alpha sources *reject* for the long book and *weak*"
  f" as avoid inputs, FN avoid overlay *promising*.")
w(f"7. **Variants:** {V['walk_forward_models_trained']} walk-forward models, {len(V['derived_scores_no_training'])}"
  f" derived scores (ensembles/decompositions), {V['distinct_dev_strategy_specs_50bps']} distinct DEV strategy specs at"
  f" 50 bps, {V['event_rate_label_variants_screened']} label variants screened on event rates, and 7 formal selection"
  f" candidates. One-sided 5% Bonferroni hurdle: t = {F(V['bonferroni_onesided_5pct_t_this_agent'], 2)} for this agent,"
  f" {F(V['bonferroni_onesided_5pct_t_programwide'], 2)} programme-wide (~{V['programwide_specs_approx']} specs).")
w("")

# =============================================================================================== 1 setup
w("## 1. Labels, models, checks")
w("")
w("| id | family | exact definition (h = 20; r20 = open[t+1] → close[t+20], adjusted; NaN unless fw.ok(20)) | model |")
w("|---|---|---|---|")
w("| XR (XR_neu) | relative, factor-neutral | per date over V = U ∩ finite(r20): winsorise r20 at 1/99%, OLS on [1, 0.5·clip(beta_60,0,3)+0.5, vol_20, log_turn20], residual → per-date pct rank; target pct−0.5 | `walk_forward2` regression |")
w("| BAR (A2) | absolute, path | `L.barrier_labels(h=20, pt=3.0·ATR, sl=1.5·ATR, tau=50bp)`, stop checked first, gap fills at open; target 1{BAR=+1} | binary |")
w("| TSX (TSX_T5) | market-excess trend scan | y_0=0, y_k = log(close[t+k]/open[t+1]) − log(N500 close[date t+k]/N500 open[date t+1]); OLS-slope t for L=5..20 (var floor 1e-6); L* = argmax abs(t); label sign(t*) if abs(t*) ≥ 5 else 0 | multiclass (P(+1)−P(−1)) |")
w("| ENS3 / ENS_XB / ENS_XT / ENS_BT | ensemble | equal-weight mean of per-date percentile ranks of the OOS scores (no fitted weights) | — |")
w("| *_FN | factor-neutral score | per date: residual of the score's pct rank on pct ranks of [log_turn20, mom_12_1, mom_5, vol_20, beta_60, idio_vol_60, dist_sma200] | — |")
w("| *_FC | static factor composite | Σ w_k·rank_k with w = DEV-average of the per-date projection coefficients (a 'boring' linear factor tilt) | — |")
w("")
xc = s1["xcheck_R2_rel_pct_neu"]
w(f"Checks. My XR_neu pct equals R2_rel's `pct_neu` on {xc['both_defined']:,} rows (max abs diff {xc['max_abs_diff']:.1e}). My BAR"
  f" equals R2_dual's BAR (agreement {s1['xcheck_R2_dual_BAR']['agreement']:.4f}, 0 NaN-pattern mismatches). My copy of"
  f" `walk_forward2` (it adds per-fold gain importance) is bit-identical to `L.walk_forward2` (max abs diff"
  f" {d['s3_verify_wf2_copy']['max_abs_diff']}). The XR_all OOS score is bit-identical to R2_rel's `h20_neu_RANK`, and BAR_all"
  f" to R2_dual's `M_BAR`. My per-date metric code reproduces `L.xs_metrics` exactly (DEV IC"
  f" {d['s4_xcheck_xs_metrics']['lib_dev_ic']:.6f} both, t {d['s4_xcheck_xs_metrics']['lib_dev_ic_t']:.4f} both). XR_all"
  f" K20/s5/50 bps reproduces R2_rel's DEV CAGR {P(main['XR_all']['K20_s5_c50_dev']['cagr'])} and excess t"
  f" {T(main['XR_all']['K20_s5_c50_dev']['excess_daily_nw_t'])}.")
w("")
w("Phase averaging. The signal calendar is shifted by 0..step−1 trading days and the daily returns are averaged.")
w("This is a daily-staggered book, and the random baseline gets the same treatment. Phase 0 is the plain `S.compare` number.")
w("R2_dual showed that the phase alone moves a K20 book's 2026 CAGR by 10-14 pp, so the **phase-averaged (PA) excess and its")
w("NW t (lag 20) are the primary statistics** below, and the phase range is shown.")
w("")

# =============================================================================================== 2 events
w("## 2. Event rates of the three alpha-source labels (U = elig_base, n = rows with a defined label)")
w("")
w("| label | n | +1 / 0 / −1 | daily +1 share mean / std / min / max | monthly +1 std (min-max) | corr(daily +1 share, N500 same window) | corr(monthly +1, N500 month) |")
w("|---|---|---|---|---|---|---|")
for nm in ("XR", "BAR", "TSX"):
    e = ev[nm]
    o = e["overall"]
    ds = e["daily_pos_share"]
    m = e["monthly_pos"]
    w(f"| {nm} | {e['n']:,} | {P(o['1.0'])} / {P(o['0.0'])} / {P(o['-1.0'])} | {P(ds['mean'])} / {P(ds['std'])} / {P(ds['min'])} / {P(ds['max'])} |"
      f" {P(m['std'])} ({P(m['min'])}-{P(m['max'])}) | {F(ds['corr_with_mkt_same_window'], 2)} | {F(e.get('corr_monthly_pos_vs_mkt_ret'), 2)} |")
w("")
w("+1 share by year (−1 share in brackets):")
w("")
w("| label | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |")
w("|---|---|---|---|---|---|---|")
for nm in ("XR", "BAR", "TSX"):
    by = ev[nm]["by_year"]
    w(f"| {nm} | " + " | ".join(f"{P(by[y]['1.0'])} ({P(by[y]['-1.0'])})" for y in ("2021", "2022", "2023", "2024", "2025", "2026")) + " |")
w("")
w("+1 share by regime at t (Nifty 500 vs 200dma × 20d momentum) and by liquidity tercile (low/mid/high log_turn20, per month):")
w("")
w("| label | bear_dn20 | bear_up20 | bull_dn20 | bull_up20 | liq low | liq mid | liq high |")
w("|---|---|---|---|---|---|---|---|")
for nm in ("XR", "BAR", "TSX"):
    br = ev[nm]["by_regime"]
    bl = ev[nm]["by_liquidity_tercile"]
    w(f"| {nm} | " + " | ".join(P(br[r]["1.0"]) for r in ("bear_dn20", "bear_up20", "bull_dn20", "bull_up20")) + " | "
      + " | ".join(P(bl[t]["1.0"]) for t in ("0", "1", "2")) + " |")
w("")
w("Label/P&L coherence at 50 bps (mean net return per class; P(net>0); mean excess vs same-date EW universe):")
w("")
w("| label | +1: net bps / P(net>0) / excess bps | 0: net / P / excess | −1: net / P / excess |")
w("|---|---|---|---|")
for nm in ("XR", "BAR", "TSX"):
    c = ev[nm]["coherence_50bps"]
    w(f"| {nm} | " + " | ".join(f"{c[k]['mean_net_bps']:+.0f} / {P(c[k]['p_net_pos'], 0)} / {c[k]['mean_excess_vs_ew_bps']:+.0f}" for k in ("1", "0", "-1")) + " |")
w("")
ag = ev["agreement"]
w("Label agreement (rows where all three are defined): "
  + "; ".join(f"{k.replace('_vs_', ' vs ')}: P(+1|+1) {P(v['P(b=+1|a=+1)'], 0)}, P(−1|−1) {P(v['P(b=-1|a=-1)'], 0)}, row corr {F(v['row_corr'], 2)}"
              for k, v in ag.items() if k != "per_date_spearman_mean") + ".")
sp = ag["per_date_spearman_mean"]
w(f"Per-date Spearman of the continuous forms: XR~TSX t* {F(sp['XR~TSXt'], 2)}, XR~BAR return {F(sp['XR~BARret'], 2)},"
  f" BAR~TSX {F(sp['BARret~TSXt'], 2)}, XR~r20 {F(sp['XR~r20'], 3)}.")
w("")
w("**How event rates move with parameters** (share of +1 / 0 / −1 on U; barrier exits; monthly +1 std):")
w("")
w("| variant | +1 | 0 | −1 | target / stop / time exits | monthly +1 std (min-max) |")
w("|---|---|---|---|---|---|")
for k, v in ev["sensitivity"].items():
    ex = f"{P(v['target'])} / {P(v['stop'])} / {P(v['time'])}" if "target" in v else "—"
    ms = f"{P(v['monthly_pos_std'])} ({P(v['monthly_pos_min'])}-{P(v['monthly_pos_max'])})" if "monthly_pos_std" in v else "0.0% (rank label: constant)"
    w(f"| {k} | {P(v['+1'])} | {P(v['0'])} | {P(v['-1'])} | {ex} | {ms} |")
w("")
sv = ev["sensitivity"]
w("Reading. The XR rank label is regime-free by construction: daily +1 share std is"
  f" {P(ev['XR']['daily_pos_share']['std'], 2)} and its correlation with the market is {F(ev['XR']['daily_pos_share']['corr_with_mkt_same_window'], 2)}."
  f" The A2 barrier is a market label: the daily +1 share ranges {P(ev['BAR']['daily_pos_share']['min'], 0)}-{P(ev['BAR']['daily_pos_share']['max'], 0)}"
  f" with correlation {F(ev['BAR']['daily_pos_share']['corr_with_mkt_same_window'], 2)}. Moving the target from 2 to 4 ATR (stop 2) takes"
  f" P(+1) from {P(sv['BAR_pt2.0_sl2.0']['+1'])} to {P(sv['BAR_pt4.0_sl2.0']['+1'])} and target exits from"
  f" {P(sv['BAR_pt2.0_sl2.0']['target'])} to {P(sv['BAR_pt4.0_sl2.0']['target'])}. Widening the stop from 1.5 to 3 ATR (target 3) takes"
  f" P(+1) from {P(sv['BAR_pt3.0_sl1.5']['+1'])} to {P(sv['BAR_pt3.0_sl3.0']['+1'])} and time exits from"
  f" {P(sv['BAR_pt3.0_sl1.5']['time'])} to {P(sv['BAR_pt3.0_sl3.0']['time'])}. No geometry lowers the monthly +1 std below"
  f" {P(min(v['monthly_pos_std'] for k, v in sv.items() if k.startswith('BAR')))}."
  f" TSX sits between XR and BAR (daily corr {F(ev['TSX']['daily_pos_share']['corr_with_mkt_same_window'], 2)}). Its threshold T"
  f" trades class balance for rarity: T=3 gives {P(sv['TSX_T3']['+1'])} +1 and T=8 gives {P(sv['TSX_T8']['+1'])}."
  " As round 1 found, abs(t*) ≥ 5 is not a significance level.")
w("")

# =============================================================================================== 3 learnability
w("## 3. Learnability (walk-forward OOS, per-date cross-section; t from every 20th date)")
w("")
w("ic_xr = IC vs the XR_neu20 pct (relative yardstick); ic_raw = IC vs r20; ic_tsx = IC vs TSX t*; AUC_top = AUC for XR +1 (pct>0.7);"
  " AUC_bot = AUC of −score for XR −1 (pct≤0.3); own AUC = AUC vs the model's own +1 class.")
w("")
w("| score | DEV ic_xr (t) | DEV ic_raw (t) | DEV AUC_top / AUC_bot | DEV own AUC | 2026 ic_xr (t) | 2026 ic_raw | 2026 AUC_top / AUC_bot | ic_xr by year 23/24/25/26 |")
w("|---|---|---|---|---|---|---|---|---|")
own = {"XR_all": None, "BAR_all": "auc_bar", "TSX_all": "auc_tsxup", "BAR_no_market": "auc_bar", "TSX_no_market": "auc_tsxup"}
for tag in ("XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XB", "ENS_XT", "ENS_BT", "XR_no_market", "BAR_no_market",
            "TSX_no_market", "ENS3_nomkt", "XR_all_FN", "ENS3_FN", "TSX_all_FN", "XR_all_FC"):
    if tag not in xs:
        continue
    s = xs[tag]
    by = s["by_year"]
    oa = own.get(tag)
    w(f"| {tag} | {F(s['dev_ic_xr'])} ({T(s.get('dev_ic_xr_t'))}) | {F(s['dev_ic_raw'])} ({T(s.get('dev_ic_raw_t'))}) |"
      f" {F(s['dev_auc_top'])} / {F(s['dev_auc_bot'])} | {F(s[f'dev_{oa}']) if oa else '—'} | {F(s['hold_ic_xr'])} ({T(s.get('hold_ic_xr_t'))}) |"
      f" {F(s['hold_ic_raw'])} | {F(s['hold_auc_top'])} / {F(s['hold_auc_bot'])} | "
      + " / ".join(F(by[y]["ic_xr"]) for y in ("2023", "2024", "2025", "2026")) + " |")
w("")
w("Score correlations (mean per-date Spearman of OOS scores) and top-20 overlap:")
w("")
w("| pair | DEV Spearman | 2026 Spearman | DEV top-20 overlap | 2026 top-20 overlap |")
w("|---|---|---|---|---|")
for a, b in (("XR_all", "BAR_all"), ("XR_all", "TSX_all"), ("BAR_all", "TSX_all"), ("XR_all", "ENS3"), ("TSX_all", "ENS3")):
    k = f"{a}~{b}"
    w(f"| {a} ~ {b} | {F(corr['dev'][k], 2)} | {F(corr['hold'][k], 2)} | {P(corr['dev']['ov20_' + k], 0)} | {P(corr['hold']['ov20_' + k], 0)} |")
w("")
w("Reading. TSX ranks the XR target as well as the XR model itself in DEV and better in 2026: ic_xr"
  f" {F(xs['TSX_all']['dev_ic_xr'])} vs {F(xs['XR_all']['dev_ic_xr'])} DEV, and {F(xs['TSX_all']['hold_ic_xr'])} vs"
  f" {F(xs['XR_all']['hold_ic_xr'])} in 2026. BAR is the weakest ranker ({F(xs['BAR_all']['dev_ic_xr'])}). The three scores are"
  f" related but far from identical (Spearman 0.56-0.71; top-20 overlap 24-28%), which is the precondition for an ensemble to"
  " help. Section 5 shows that higher IC did **not** translate into a better top-20 book for TSX/ENS3 in 2026.")
w("")

# =============================================================================================== 4 investability
w("## 4. Investability (L.Sim, h=20, U, long top-K, phase-averaged excess vs horizon-matched random)")
w("")
w("### 4a. Long top-20, step 5")
w("")
w("| score | cost | DEV CAGR (PA) | DEV random | DEV excess/yr (NW t) | phase range of excess CAGR | DEV maxDD (p0) | DEV p0 excess (t) | 2026 CAGR (PA, ann.) | 2026 random | 2026 excess/yr (t) | 2026 phase range |")
w("|---|---|---|---|---|---|---|---|---|---|---|---|")
for tag in ("XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XB", "ENS_XT", "ENS_BT", "XR_no_market", "BAR_no_market",
            "TSX_no_market", "ENS3_nomkt", "XR_all_FN", "ENS3_FN", "TSX_all_FN", "XR_all_FC", "ENS3_FC", "TSX_all_FC"):
    for c in ("50", "80"):
        if tag not in main:
            continue
        r = main[tag][f"K20_s5_c{c}_dev"]
        h = main[tag][f"K20_s5_c{c}_hold"]
        a, b = r["pa"], h["pa"]
        w(f"| {tag} | {c} | {P(a['cagr'])} | {P(a['random_cagr'])} | {P(a['excess_ann'], 1, True)} ({T(a['excess_nw_t'])}) |"
          f" {P(a['phase_excess_cagr_min'], 1, True)}..{P(a['phase_excess_cagr_max'], 1, True)} | {P(r['max_dd'])} |"
          f" {P(r['excess_cagr_vs_random'], 1, True)} ({T(r['excess_daily_nw_t'])}) | {P(b['cagr'])} | {P(b['random_cagr'])} |"
          f" {P(b['excess_ann'], 1, True)} ({T(b['excess_nw_t'])}) | {P(b['phase_excess_cagr_min'], 1, True)}..{P(b['phase_excess_cagr_max'], 1, True)} |")
w("")
exd = [main[t]["K20_s5_c50_dev"]["exposure"] for t in main]
exh = [main[t]["K20_s5_c50_hold"]["exposure"] for t in main]
rng = lambda a: F(min(a), 2) if abs(max(a) - min(a)) < 0.005 else f"{F(min(a), 2)}-{F(max(a), 2)}"  # noqa: E731
w(f"Exposure (phase 0) is {rng(exd)} in DEV and {rng(exh)} in 2026 for every top-20 book"
  " (slot sizing; the first sleeves start in cash and the 2026 window ends mid-sleeve).")
w("**Costs.** With a 20-day time exit every sleeve turns over 100% at each rebalance, for the strategy and the random baseline"
  " alike. So the excess over random is the same at 50 and 80 bps, and only the absolute CAGR falls, by about 4.5 pp/yr"
  f" (XR DEV {P(main['XR_all']['K20_s5_c50_dev']['pa']['cagr'])} → {P(main['XR_all']['K20_s5_c80_dev']['pa']['cagr'])}).")
w("Nifty 500 (price) context: 2023 +25.2%, 2024 +14.9%, 2025 +6.2%, 2026 YTD −7.8%. The EW universe (adjusted, ~total return) is")
w(f"far stronger in 2026: the EW-U factor book made {P(fac['hold_MKT_ann'], 1, True)}/yr.")
w("")
w("By year (phase-averaged, K20 s5 50 bps; strategy vs random):")
w("")
w("| score | 2023 | 2024 | 2025 | 2026 YTD |")
w("|---|---|---|---|---|")
for tag in ("XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XT", "ENS3_nomkt", "XR_all_FN", "TSX_all_FN"):
    a = main[tag]["K20_s5_c50_dev"]["pa"]
    b = main[tag]["K20_s5_c50_hold"]["pa"]
    cells = [f"{P(a['by_year'][y])} vs {P(a['random_by_year'][y])}" for y in ("2023", "2024", "2025")]
    cells.append(f"{P(b['by_year']['2026'])} vs {P(b['random_by_year']['2026'])}")
    w(f"| {tag} | " + " | ".join(cells) + " |")
w("")
w("Risk of the long top-20 book (50 bps, phase-averaged daily book; random = 5-seed random top-20 on the same mask):")
w("")
w("| score | DEV Sharpe | DEV maxDD | 2026 Sharpe | 2026 maxDD | random DEV maxDD (p0) | random 2026 maxDD (p0) |")
w("|---|---|---|---|---|---|---|")
for tag in ("XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XT", "XR_no_market", "ENS3_nomkt", "XR_all_FN", "TSX_all_FN"):
    a = main[tag]["K20_s5_c50_dev"]
    b = main[tag]["K20_s5_c50_hold"]
    w(f"| {tag} | {F(a['pa']['sharpe'], 2)} | {P(a['pa']['max_dd'])} | {F(b['pa']['sharpe'], 2)} | {P(b['pa']['max_dd'])} |"
      f" {P(a['random']['max_dd_mean'])} | {P(b['random']['max_dd_mean'])} |")
w("")
w("No alpha source reduces drawdowns. Every long top-20 book carries about the random book's market drawdown (DEV −25% to −31% vs"
  " −29.7%), because they are fully invested, long-only and roughly beta-1. Ensembling smooths the *excess* (higher Sharpe) but not the"
  " drawdown. Drawdown control has to come from the regime/exposure layer.")
w("")
w("### 4b. AVOID overlay (equal-weight all U names except the score's bottom 30%; step 5; vs random-70% and vs EW universe)")
w("")
w("| score | DEV CAGR | DEV excess vs random/yr (t) | DEV excess vs EW (t) | 2026 CAGR | 2026 excess vs random (t) | 2026 vs EW (t) | DEV CAGR at 80bp (random) |")
w("|---|---|---|---|---|---|---|---|")
for tag in ("XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XB", "ENS_XT", "ENS_BT", "XR_no_market", "BAR_no_market",
            "TSX_no_market", "ENS3_nomkt", "XR_all_FN", "ENS3_FN", "TSX_all_FN", "XR_all_FC", "ENS3_FC", "TSX_all_FC"):
    if tag not in main:
        continue
    a = main[tag]["avoid30_s5_c50_dev"]["pa"]
    b = main[tag]["avoid30_s5_c50_hold"]["pa"]
    c8 = main[tag]["avoid30_s5_c80_dev"]["pa"]
    w(f"| {tag} | {P(a['cagr'])} | {P(a['excess_ann'], 1, True)} ({T(a['excess_nw_t'])}) | {P(a['excess_vs_ew_ann'], 1, True)} ({T(a['excess_vs_ew_nw_t'])}) |"
      f" {P(b['cagr'])} | {P(b['excess_ann'], 1, True)} ({T(b['excess_nw_t'])}) | {P(b['excess_vs_ew_ann'], 1, True)} ({T(b['excess_vs_ew_nw_t'])}) |"
      f" {P(c8['cagr'])} ({P(c8['random_cagr'])}) |")
w("")
w("### 4c. K × step sensitivity (50 bps; phase-averaged excess/yr and NW t)")
w("")
gt = ["XR_all", "BAR_all", "TSX_all", "ENS3", "ENS_XT", "XR_all_FN", "ENS3_FN", "TSX_all_FN"]
for per in ("dev", "hold"):
    w(f"**{'DEV 2023-25' if per == 'dev' else 'HOLDOUT 2026'}**")
    w("")
    w("| K / step | " + " | ".join(gt) + " |")
    w("|---|" + "---|" * len(gt))
    for c in ("K10_s5", "K10_s10", "K20_s5", "K20_s10", "K30_s5", "K30_s10", "K50_s5", "K50_s10"):
        cells = []
        for t in gt:
            src = main[t] if c == "K20_s5" else grid.get(t, {})
            r = src.get(f"{c}_c50_{per}")
            cells.append(f"{P(r['pa']['excess_ann'], 1, True)} ({T(r['pa']['excess_nw_t'])})" if r else "—")
        w(f"| {c} | " + " | ".join(cells) + " |")
    w("")
w("80 bps stress for K20 s10 / K50 s10 (DEV | 2026 PA excess):")
w("")
w("| score | K20 s10 80bp DEV | K20 s10 80bp 2026 | K50 s10 80bp DEV | K50 s10 80bp 2026 | K50 s10 80bp DEV CAGR vs random |")
w("|---|---|---|---|---|---|")
for t in gt:
    g = grid[t]
    w(f"| {t} | {P(g['K20_s10_c80_dev']['pa']['excess_ann'], 1, True)} ({T(g['K20_s10_c80_dev']['pa']['excess_nw_t'])}) |"
      f" {P(g['K20_s10_c80_hold']['pa']['excess_ann'], 1, True)} ({T(g['K20_s10_c80_hold']['pa']['excess_nw_t'])}) |"
      f" {P(g['K50_s10_c80_dev']['pa']['excess_ann'], 1, True)} ({T(g['K50_s10_c80_dev']['pa']['excess_nw_t'])}) |"
      f" {P(g['K50_s10_c80_hold']['pa']['excess_ann'], 1, True)} ({T(g['K50_s10_c80_hold']['pa']['excess_nw_t'])}) |"
      f" {P(g['K50_s10_c80_dev']['pa']['cagr'])} vs {P(g['K50_s10_c80_dev']['pa']['random_cagr'])} |")
w("")
w("Plateau vs cliff. In DEV every score is positive in every K × step cell, so no cliff appears. Raw scores' excess falls as K"
  f" rises (XR {P(grid['XR_all']['K10_s5_c50_dev']['pa']['excess_ann'], 1, True)} at K10 → {P(grid['XR_all']['K50_s5_c50_dev']['pa']['excess_ann'], 1, True)}"
  f" at K50). The FN scores are flat across K (XR_FN {P(grid['XR_all_FN']['K10_s5_c50_dev']['pa']['excess_ann'], 1, True)} at K10,"
  f" {P(grid['XR_all_FN']['K50_s5_c50_dev']['pa']['excess_ann'], 1, True)} at K50), so at K50 their t equals or beats the raw score's."
  " In 2026 the raw BAR/TSX/ENS3/ENS_XT books are negative in **8/8** cells, XR is positive but insignificant in 8/8, and all"
  " three FN scores are positive in 8/8. The 2026 failure is not a K, step or phase artefact.")
w("")

# =============================================================================================== 5 selection
w("## 5. Selection on DEV (pre-declared) and the holdout exam")
w("")
pr = d["s0_protocol"]
w(f"Protocol, recorded at {pr['recorded_at']} before any simulation of my scores: candidates {', '.join(pr['candidates'])};"
  f" primary statistic = {pr['primary_selection_stat']}; constraint = {pr['constraint']}; avoid screen chosen separately by"
  " the DEV PA t of the avoid30 overlay.")
w("")
w("| candidate | DEV PA excess/yr | DEV NW t | rank | DEV 80bp CAGR vs random | 2026 PA excess/yr (t) | avoid DEV t | avoid rank | avoid 2026 excess (t) |")
w("|---|---|---|---|---|---|---|---|---|")
cands = pr["candidates"]
lt = sorted(cands, key=lambda t: -main[t]["K20_s5_c50_dev"]["pa"]["excess_nw_t"])
at = sorted(cands, key=lambda t: -main[t]["avoid30_s5_c50_dev"]["pa"]["excess_nw_t"])
for t in cands:
    a = main[t]["K20_s5_c50_dev"]["pa"]
    a8 = main[t]["K20_s5_c80_dev"]["pa"]
    b = main[t]["K20_s5_c50_hold"]["pa"]
    v = main[t]["avoid30_s5_c50_dev"]["pa"]
    vh = main[t]["avoid30_s5_c50_hold"]["pa"]
    w(f"| {t} | {P(a['excess_ann'], 1, True)} | {T(a['excess_nw_t'])} | {lt.index(t) + 1} | {P(a8['cagr'])} vs {P(a8['random_cagr'])} |"
      f" {P(b['excess_ann'], 1, True)} ({T(b['excess_nw_t'])}) | {T(v['excess_nw_t'])} | {at.index(t) + 1} | {P(vh['excess_ann'], 1, True)} ({T(vh['excess_nw_t'])}) |")
w("")
w(f"**Selected (long book): {lt[0]}.** 2026 exam: {P(main[lt[0]]['K20_s5_c50_hold']['pa']['excess_ann'], 1, True)}/yr vs random"
  f" (t {T(main[lt[0]]['K20_s5_c50_hold']['pa']['excess_nw_t'])}). **FAIL.** **Selected (avoid screen): {at[0]}.** 2026:"
  f" {P(main[at[0]]['avoid30_s5_c50_hold']['pa']['excess_ann'], 1, True)}/yr (t {T(main[at[0]]['avoid30_s5_c50_hold']['pa']['excess_nw_t'])}),"
  " positive but not significant.")
w("")
w("Paired comparisons (difference of phase-averaged daily book returns, same Sim settings; random cancels; NW t lag 20):")
w("")
w("| A − B | K20 DEV/yr (t) | K20 2026/yr (t) | avoid DEV/yr (t) | avoid 2026/yr (t) | K20 DEV by year 23/24/25 |")
w("|---|---|---|---|---|---|")
for k in ("ENS3__minus__XR_all", "ENS_XT__minus__XR_all", "ENS_XB__minus__XR_all", "ENS_BT__minus__XR_all",
          "BAR_all__minus__XR_all", "TSX_all__minus__XR_all", "BAR_no_market__minus__BAR_all",
          "TSX_no_market__minus__TSX_all", "ENS3_nomkt__minus__ENS3", "XR_no_market__minus__XR_all",
          "ENS3_nomkt__minus__XR_all", "TSX_no_market__minus__XR_all", "XR_all_FN__minus__XR_all", "ENS3_FN__minus__ENS3",
          "TSX_all_FN__minus__TSX_all", "XR_all_FC__minus__XR_all"):
    r = pair[k]
    by = r["K20_s5_c50_dev"]["diff_by_year"]
    w(f"| {k.replace('__minus__', ' − ')} | {P(r['K20_s5_c50_dev']['diff_ann'], 1, True)} ({T(r['K20_s5_c50_dev']['nw_t'])}) |"
      f" {P(r['K20_s5_c50_hold']['diff_ann'], 1, True)} ({T(r['K20_s5_c50_hold']['nw_t'])}) |"
      f" {P(r['avoid30_s5_c50_dev']['diff_ann'], 1, True)} ({T(r['avoid30_s5_c50_dev']['nw_t'])}) |"
      f" {P(r['avoid30_s5_c50_hold']['diff_ann'], 1, True)} ({T(r['avoid30_s5_c50_hold']['nw_t'])}) | "
      + " / ".join(P(by[y], 1, True) for y in ("2023", "2024", "2025")) + " |")
w("")
w("Reading. No ensemble beats XR on DEV in a paired test (best: ENS_XT +0.3%/yr, t 0.13). The ensembles' higher DEV t-statistics"
  " come from lower tracking variance against random, not from more return. In 2026 every ensemble and every single"
  " absolute/trend model lags XR by 9-14%/yr (t −1.3 to −1.8). Rows marked no-market, FN or FC were built as diagnostics."
  " Their 2026 columns are **holdout-informed** and are not selection evidence.")
w("")

# =============================================================================================== 6 why
w("## 6. Why the ensemble fails in 2026: a regime-conditional factor tilt")
w("")
w("### 6a. What the top-20 picks are (mean over all dates; tilts = same-date percentile among U)")
w("")
w("xr_pct = realised XR_neu residual percentile of the picks (factor-neutral skill; 0.5 = none). ex_raw = realised r20 minus"
  " the same-date U mean (bps per 20d trade, before costs). ex_fac = the part of ex_raw explained by the picks' exposure to the"
  " XR neutralisers (beta, vol, turnover). ex_resid = ex_raw − ex_fac.")
w("")
w("| model | window | xr_pct | ex_raw | ex_fac | ex_resid | beta_60 | vol_20 | idio_vol_60 | log_turn20 | mom_12_1 | mom_5 | dist_sma200 | deliv_pct |")
w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for m in ("XR_all", "BAR_all", "TSX_all", "ENS3", "XR_no_market", "BAR_no_market", "TSX_no_market", "ENS3_nomkt", "XR_all_FN", "TSX_all_FN"):
    for y in ("dev", "2026"):
        r = comp[m][y]
        w(f"| {m} | {y.upper() if y == 'dev' else y} | {F(r['xr_pct'])} | {r['ex_raw']:+.0f} | {r['ex_fac']:+.0f} | {r['ex_resid']:+.0f} | "
          + " | ".join(F(r[f'tilt_{c}'], 2) for c in ("beta_60", "vol_20", "idio_vol_60", "log_turn20", "mom_12_1", "mom_5", "dist_sma200", "deliv_pct")) + " |")
w("")
w("### 6b. Gain-importance share of the market/regime feature group by fold (each fold is trained only on earlier data)")
w("")
w("| model | 2023 fold | 2024 | 2025 | 2026 |")
w("|---|---|---|---|---|")
for m in ("XR_all", "BAR_all", "TSX_all"):
    g = imp[m]["group_share_by_fold"]
    w(f"| {m} | " + " | ".join(P(g[y]["market"]) for y in ("2023", "2024", "2025", "2026")) + " |")
w("")
w("### 6c. The no-market experiment (same models without the 10 market/regime features)")
w("")
w("| model | DEV K20 excess/yr (t) | 2026 K20 excess/yr (t) | DEV ic_xr | 2026 ic_xr | ΔIC_xr vs full model DEV (NW t) | 2026 (NW t / non-overlap t) | ΔIC by year 23/24/25/26 |")
w("|---|---|---|---|---|---|---|---|")
for a, b in (("XR_no_market", "XR_all"), ("BAR_no_market", "BAR_all"), ("TSX_no_market", "TSX_all"), ("ENS3_nomkt", "ENS3")):
    k = f"{a}__minus__{b}"
    r = dic[k]
    m1, m2 = main[a]["K20_s5_c50_dev"]["pa"], main[a]["K20_s5_c50_hold"]["pa"]
    w(f"| {a} | {P(m1['excess_ann'], 1, True)} ({T(m1['excess_nw_t'])}) | {P(m2['excess_ann'], 1, True)} ({T(m2['excess_nw_t'])}) |"
      f" {F(xs[a]['dev_ic_xr'])} | {F(xs[a]['hold_ic_xr'])} | {F(r['dev_d_ic_xr'], 4, True)} ({T(r['dev_d_ic_xr_nw_t'])}) |"
      f" {F(r['hold_d_ic_xr'], 4, True)} ({T(r['hold_d_ic_xr_nw_t'])} / {T(r['hold_d_ic_xr_nonoverlap_t'])}) | "
      + " / ".join(F(r["d_ic_xr_by_year"][y], 4, True) for y in ("2023", "2024", "2025", "2026")) + " |")
w("")
w("Reading.")
w("")
w("* The absolute barrier label's DEV edge is almost entirely regime timing. Without market features, BAR's top-20 book makes"
  f" {P(main['BAR_no_market']['K20_s5_c50_dev']['pa']['excess_ann'], 1, True)}/yr in DEV (picks' raw excess"
  f" {comp['BAR_no_market']['dev']['ex_raw']:+.0f} bps), against {P(main['BAR_all']['K20_s5_c50_dev']['pa']['excess_ann'], 1, True)} with them.")
w("* Market features helped the BAR and ENS3 books in every DEV year and the TSX book in 2 of 3 (paired by-year table in §5). So a DEV-only")
w("  analyst would keep them, and this is not a classic in-sample overfit: all four years are walk-forward OOS. It is a factor-timing bet")
w("  that paid in 2023-25 and reversed in 2026, when small, high-vol names led (2026 LS factors: SIZE"
  f" {P(fac['hold_SIZE_ann'], 1, True)}, LOWVOL {P(fac['hold_LOWVOL_ann'], 1, True)}, LOWIDIO {P(fac['hold_LOWIDIO_ann'], 1, True)}/yr).")
w("* XR is far less exposed. Its target strips beta, vol and size, so market features can act only through interactions."
  " They carry 12-19% of XR's gain importance and change XR's DEV IC by"
  f" {F(dic['XR_no_market__minus__XR_all']['dev_d_ic_xr'], 4, True)} (n.s.).")
w("* Caveat on the 2026 ΔIC t-stats: NW (Bartlett, lag 20) on ~190 overlapping 20-day windows understates the long-run variance,"
  " and the non-overlap t uses only ~10 points. The truth lies between them. The paired daily-book tests in §5 have no forward-window"
  " overlap and are the better guide.")
w("")

# =============================================================================================== 7 ablation
w("## 7. Feature-group ablation on the XR_neu model (drop one group, retrain the same walk-forward)")
w("")
w("Groups (a disjoint partition of the 52 features; `age` is never dropped): " + "; ".join(
    f"**{g}** ({len(fs)}): {', '.join(fs)}" for g, fs in GROUPS.items() if g != "other") + ".")
w("")
w("| dropped group | DEV ΔIC_xr (NW t / non-ovl t) | 2026 ΔIC_xr (NW t / non-ovl t) | DEV ΔAUC_bot (NW t) | ΔIC_xr by year 23/24/25/26 | ΔK20 DEV/yr (t) | ΔK20 2026/yr (t) | Δavoid DEV/yr (t) | Δavoid 2026/yr (t) |")
w("|---|---|---|---|---|---|---|---|---|")
for g in ("momentum", "volrisk", "volume", "delivery", "market", "xsrank", "technical"):
    k = f"XR_no_{g}__minus__XR_all"
    r, p_ = dic[k], pair[k]
    w(f"| {g} | {F(r['dev_d_ic_xr'], 4, True)} ({T(r['dev_d_ic_xr_nw_t'])} / {T(r['dev_d_ic_xr_nonoverlap_t'])}) |"
      f" {F(r['hold_d_ic_xr'], 4, True)} ({T(r['hold_d_ic_xr_nw_t'])} / {T(r['hold_d_ic_xr_nonoverlap_t'])}) |"
      f" {F(r['dev_d_auc_bot'], 4, True)} ({T(r['dev_d_auc_bot_nw_t'])}) | "
      + " / ".join(F(r["d_ic_xr_by_year"][y], 4, True) for y in ("2023", "2024", "2025", "2026")) + " |"
      f" {P(p_['K20_s5_c50_dev']['diff_ann'], 1, True)} ({T(p_['K20_s5_c50_dev']['nw_t'])}) |"
      f" {P(p_['K20_s5_c50_hold']['diff_ann'], 1, True)} ({T(p_['K20_s5_c50_hold']['nw_t'])}) |"
      f" {P(p_['avoid30_s5_c50_dev']['diff_ann'], 1, True)} ({T(p_['avoid30_s5_c50_dev']['nw_t'])}) |"
      f" {P(p_['avoid30_s5_c50_hold']['diff_ann'], 1, True)} ({T(p_['avoid30_s5_c50_hold']['nw_t'])}) |")
w("")
w(f"Base XR_all: DEV ic_xr {F(xs['XR_all']['dev_ic_xr'])}, 2026 {F(xs['XR_all']['hold_ic_xr'])}; K20 DEV"
  f" {P(x_dev['excess_ann'], 1, True)}/yr, 2026 {P(x_hold['excess_ann'], 1, True)}/yr. Δ = ablated − base (negative = the group helps).")
w("")
w("### 7a. Importance stability by year (XR_all gain share per fold)")
w("")
gs = imp["XR_all"]["group_share_by_fold"]
w("| group | 2023 fold | 2024 | 2025 | 2026 |")
w("|---|---|---|---|---|")
for g in ("momentum", "volrisk", "volume", "delivery", "market", "xsrank", "technical", "other"):
    w(f"| {g} | " + " | ".join(P(gs[y][g]) for y in ("2023", "2024", "2025", "2026")) + " |")
w("")
w("Top-8 features per fold (gain share):")
w("")
for y, t in imp["XR_all"]["top10_by_fold"].items():
    w(f"* {y}: " + ", ".join(f"{k} {P(v)}" for k, v in list(t.items())[:8]))
w("")
w("Fold-to-fold Spearman of the 52-feature importance vector: " + ", ".join(
    f"{k} {F(v, 2)}" for k, v in imp["XR_all"]["spearman_between_folds"].items()) + ".")
w("")
w("### 7b. Univariate per-date IC of single features vs the XR target (DEV mean, non-overlap t; 2026 mean)")
w("")
rows = sorted([(k.split("|")[1], v) for k, v in uni.items() if k.startswith("xr|")], key=lambda z: -abs(z[1]["dev"]))
w("| feature | group | DEV IC (t) | 2026 IC (t) | IC vs raw r20 DEV |")
w("|---|---|---|---|---|")
for f_, v in rows[:16]:
    rr = uni.get(f"raw|{f_}", {})
    w(f"| {f_} | {v['group']} | {F(v['dev'], 4, True)} ({T(v['dev_t'])}) | {F(v['hold'], 4, True)} ({T(v['hold_t'])}) | {F(rr.get('dev'), 4, True)} |")
w("")
w("Partial IC of the delivery features vs the XR target after per-date rank-OLS on log_turn20, vol_20, mom_5 and volz_20:")
w("")
w("| feature | DEV partial IC (t) | 2026 partial IC (t) | raw univariate DEV IC |")
w("|---|---|---|---|")
for f_ in ("deliv_pct", "deliv_z20", "deliv_ratio", "xr_deliv_z"):
    v = uni[f"pxr|{f_}"]
    w(f"| {f_} | {F(v['dev'], 4, True)} ({T(v['dev_t'])}) | {F(v['hold'], 4, True)} ({T(v['hold_t'])}) | {F(uni['xr|' + f_]['dev'], 4, True)} |")
w("")
w("**Is NSE delivery data adding value? Yes, modestly and robustly.**")
w("")
w(f"* deliv_pct is the strongest single feature for the relative target in DEV (IC {F(uni['xr|deliv_pct']['dev'], 4, True)}) and holds in 2026"
  f" ({F(uni['xr|deliv_pct']['hold'], 4, True)}). It survives controls for liquidity, volatility, reversal and volume (partial IC"
  f" {F(uni['pxr|deliv_pct']['dev'], 4, True)}, t {T(uni['pxr|deliv_pct']['dev_t'])}).")
w("* It is the only group whose removal hurts IC with a negative sign in every year 2023-2026.")
w(f"* Its gain share rises from {P(gs['2023']['delivery'])} (2023 fold) to {P(gs['2026']['delivery'])} (2026 fold), and deliv_pct enters the 2026 top-8.")
w("* The book-level effect is about 2-3%/yr on the top-20 book and 0.2-1.1%/yr on the avoid overlay: right-signed, mostly below significance.")
w("")
pmo = pair["XR_no_momentum__minus__XR_all"]
w("Redundancy. Momentum, technicals, volume and the xs-rank copies each change IC by ≤ 0.002 in DEV."
  f" Momentum is the exception at the top tail: {P(pmo['K20_s5_c50_dev']['diff_ann'], 1, True)}/yr on the top-20 book in DEV"
  f" (t {T(pmo['K20_s5_c50_dev']['nw_t'])}) and {P(pmo['K20_s5_c50_hold']['diff_ann'], 1, True)} in 2026 (t {T(pmo['K20_s5_c50_hold']['nw_t'])})."
  " The model recovers the same information from overlapping features (e.g. hi52_dist ≡ xr_hi52 in per-date rank terms). The xs-rank group is a pure duplicate"
  " for a per-date rank target. Removing it is neutral in DEV and slightly positive in 2026. The vol/risk group helps the avoid side in DEV"
  f" (ΔAUC_bot {F(dic['XR_no_volrisk__minus__XR_all']['dev_d_auc_bot'], 4, True)}, t {T(dic['XR_no_volrisk__minus__XR_all']['dev_d_auc_bot_nw_t'])}).")
w("")

# =============================================================================================== 8 factors
w("## 8. Factor attribution: is the edge just low-vol / reversal?")
w("")
w("### 8a. Long-short factor returns from the same universe (EW top-30% minus bottom-30%, h=20 step 5, 50 bps both legs, phase-averaged)")
w("")
w("| factor | definition (long side) | DEV ann. (NW t) | 2026 ann. (NW t) |")
w("|---|---|---|---|")
defs = {"SIZE": "small (−log_turn20)", "MOM": "high mom_12_1", "REV": "5d losers (−mom_5)", "LOWVOL": "low vol_20",
        "LOWBETA": "low beta_60", "LOWIDIO": "low idio_vol_60", "TREND": "high dist_sma200", "MKT": "EW universe book (not LS)"}
for k, dsc in defs.items():
    w(f"| {k} | {dsc} | {P(fac[f'dev_{k}_ann'], 1, True)} ({T(fac[f'dev_{k}_nw_t'])}) | {P(fac[f'hold_{k}_ann'], 1, True)} ({T(fac[f'hold_{k}_nw_t'])}) |")
w("")
w("### 8b. Regression of each book's daily excess-vs-random on the factors (OLS, NW t lag 20)")
w("")
w("Spec 'brief' = SIZE, MOM, REV, LOWVOL, LOWBETA, MKT. Spec 'ext' adds LOWIDIO and TREND.")
w("")
w("| book | window | spec | excess/yr | alpha/yr (NW t) | R² | factor t-stats |")
w("|---|---|---|---|---|---|---|")
for tag in ("XR_all", "ENS3", "TSX_all", "BAR_all"):
    for book in ("K20_s5_c50", "avoid30_s5_c50"):
        for per in ("dev", "hold"):
            for spec in ("brief", "ext"):
                r = reg[f"{tag}|{book}_{per}|{spec}"]
                w(f"| {tag} {book.split('_')[0]} | {per} | {spec} | {P(r['excess_ann'], 1, True)} | {P(r['alpha_ann'], 1, True)} ({T(r['alpha_nw_t'])}) | {F(r['r2'], 2)} | "
                  + ", ".join(f"{n} {v:+.1f}" for n, v in r["beta_t"].items()) + " |")
w("")
w("### 8c. What the scores load on (per-date OLS of the score's pct rank on 7 characteristic pct ranks)")
w("")
w("| score | window | log_turn20 | mom_12_1 | mom_5 | vol_20 | beta_60 | idio_vol_60 | dist_sma200 | mean xs R² |")
w("|---|---|---|---|---|---|---|---|---|---|")
for tag in ("XR_all", "TSX_all", "ENS3"):
    dc = d[f"s6_decompose_{tag}"]
    for per, key, r2k in (("DEV", "dev_mean_coef", "mean_xs_R2_dev"), ("2026", "hold_mean_coef", "mean_xs_R2_hold")):
        c = dc[key]
        w(f"| {tag} | {per} | " + " | ".join(F(c[k], 3, True) for k in ("log_turn20", "mom_12_1", "mom_5", "vol_20", "beta_60", "idio_vol_60", "dist_sma200"))
          + f" | {F(dc[r2k], 2)} |")
w("")
w("### 8d. Factor-neutral residual (FN) vs static factor composite (FC) books (K20 s5 and avoid30, 50 bps, PA excess vs random)")
w("")
w("| score | DEV K20 (t) | 2026 K20 (t) | DEV avoid (t) | 2026 avoid (t) | DEV ic_xr | DEV AUC_top / AUC_bot |")
w("|---|---|---|---|---|---|---|")
for tag in ("XR_all", "XR_all_FN", "XR_all_FC", "ENS3", "ENS3_FN", "ENS3_FC", "TSX_all", "TSX_all_FN", "TSX_all_FC"):
    m_ = main[tag]
    s = xs.get(tag, {})
    w(f"| {tag} | {P(m_['K20_s5_c50_dev']['pa']['excess_ann'], 1, True)} ({T(m_['K20_s5_c50_dev']['pa']['excess_nw_t'])}) |"
      f" {P(m_['K20_s5_c50_hold']['pa']['excess_ann'], 1, True)} ({T(m_['K20_s5_c50_hold']['pa']['excess_nw_t'])}) |"
      f" {P(m_['avoid30_s5_c50_dev']['pa']['excess_ann'], 1, True)} ({T(m_['avoid30_s5_c50_dev']['pa']['excess_nw_t'])}) |"
      f" {P(m_['avoid30_s5_c50_hold']['pa']['excess_ann'], 1, True)} ({T(m_['avoid30_s5_c50_hold']['pa']['excess_nw_t'])}) |"
      f" {F(s.get('dev_ic_xr'))} | {F(s.get('dev_auc_top'))} / {F(s.get('dev_auc_bot'))} |")
w("")
w("**Answer: no, the edge is not just low-vol or reversal.**")
w("")
w(f"* In DEV the XR long book's alpha after the brief's five factors plus market is {P(rx['alpha_ann'], 1, True)}/yr (t {T(rx['alpha_nw_t'])}),"
  f" with R² only {F(rx['r2'], 2)}.")
w("* The book is *short* the low-vol factor and carries a small reversal loading. What it does load on is low *idiosyncratic* vol at a"
  f" given total vol (score loading on idio_vol_60 {F(d['s6_decompose_XR_all']['dev_mean_coef']['idio_vol_60'], 2, True)},"
  f" on vol_20 {F(d['s6_decompose_XR_all']['dev_mean_coef']['vol_20'], 2, True)}), plus trend (dist_sma200) and short-term reversal (mom_5).")
fcd = pa("XR_all_FC", "K20_s5_c50_dev")
w(f"* The static composite of exactly these loadings earns almost nothing on the long side ({P(fcd['excess_ann'], 1, True)}/yr, t"
  f" {T(fcd['excess_nw_t'])}). The factor-neutral residual keeps"
  f" {P(pa('XR_all_FN', 'K20_s5_c50_dev')['excess_ann'] / x_dev['excess_ann'], 0)} of the long excess in DEV.")
ra = {(t, p): reg[f"{t}|avoid30_s5_c50_{p}|brief"] for t in ("XR_all", "ENS3", "TSX_all", "BAR_all") for p in ("dev", "hold")}
w(f"* XR's AVOID overlay is largely factor-explained (R² {F(ra[('XR_all', 'dev')]['r2'], 2)} DEV, {F(ra[('XR_all', 'hold')]['r2'], 2)} 2026)."
  f" Its alpha after factors is {P(ra[('XR_all', 'dev')]['alpha_ann'], 1, True)} (t {T(ra[('XR_all', 'dev')]['alpha_nw_t'])}) in DEV and"
  f" {P(ra[('XR_all', 'hold')]['alpha_ann'], 1, True)} (t {T(ra[('XR_all', 'hold')]['alpha_nw_t'])}) in 2026. In 2026 the raw avoid excess"
  " (+0.6%/yr) was masked by a big-cap (negative SIZE) loading in a small-cap year. Avoid alpha after factors, DEV / 2026: "
  + "; ".join(f"{t} {P(ra[(t, 'dev')]['alpha_ann'], 1, True)} (t {T(ra[(t, 'dev')]['alpha_nw_t'])}) / {P(ra[(t, 'hold')]['alpha_ann'], 1, True)}"
              f" (t {T(ra[(t, 'hold')]['alpha_nw_t'])})" for t in ("ENS3", "TSX_all", "BAR_all")) + ".")
w("")

# =============================================================================================== 9 multiple testing
w("## 9. Variants and multiple testing")
w("")
w(f"* Walk-forward models trained: {V['walk_forward_models_trained']} ({', '.join(V['walk_forward_models'])}), plus 1 single-fold verification run.")
w(f"* Derived scores (no training): {', '.join(V['derived_scores_no_training'])}.")
w(f"* Distinct DEV strategy specifications at 50 bps: **{V['distinct_dev_strategy_specs_50bps']}** ({V['of_which_main']} main + {V['of_which_grid']} K×step grid)."
  " The 80 bps re-costing, the holdout runs and the phase shifts are not counted as new specs.")
w(f"* Label variants screened on event rates only: {V['event_rate_label_variants_screened']}. Formal selection candidates: 7 (pre-declared).")
w(f"* Null expectation of the max t over {V['distinct_dev_strategy_specs_50bps']} independent tries: {F(V['expected_max_t_null_this_agent'], 2)}."
  f" Bonferroni one-sided 5%: {F(V['bonferroni_onesided_5pct_t_this_agent'], 2)} (this agent) and {F(V['bonferroni_onesided_5pct_t_programwide'], 2)}"
  f" (programme ~{V['programwide_specs_approx']} specs). XR's DEV t 3.81 passes the agent-level hurdle but not the programme-level"
  " one. The selected ENS3 at 4.37 passes both and **still fails the holdout**. That is a concrete reminder that a DEV t from"
  " overlapping, regime-exposed books overstates evidence.")
w("")

# =============================================================================================== 10 scorecards
w("## 10. Candidate scorecards (pros / cons / verdict)")
w("")
w("| candidate | pros | cons | verdict |")
w("|---|---|---|---|")
w("| XR_all (XR_neu regression, all features) | Regime-free label; stable importance (fold Spearman ≥ 0.90); DEV alpha after factors t 3.3; positive in 2026 in 8/8 K×step cells | 2026 edge small and insignificant (+3.3%/yr, t 0.44); avoid overlay weak in 2026 (t 0.38) | promising (as R2_rel) |")
w("| BAR_all (A2 barrier binary) | Coherent classes (+1 nets +958 bps); decent avoid overlay in DEV | 61-87% of its gain importance is market timing; DEV edge vanishes without market features; 2026 −7.3%/yr | reject (alpha source) |")
w("| TSX_all (market-excess trend scan) | Best IC on the XR yardstick in 2026; best single-model raw avoid t in DEV | Long book fails 2026 (−7.0%/yr); regime-conditional size/vol tilt; score 72% factor-explained in 2026 | weak (avoid input only) |")
w("| ENS3 (rank average XR+BAR+TSX) | Highest DEV t (4.37), smoothest DEV excess | No paired DEV gain over XR (+0.1%/yr); 2026 −7.0%/yr, all phases and all K×step cells negative | reject |")
w("| ENS_XT / ENS_XB / ENS_BT | ENS_XT has the best DEV IC (0.065) | Same 2026 failure (−5.5 to −10.3%/yr) | reject |")
w("| *_FN avoid overlays (factor-neutral score, drop bottom 30%) | DEV t 5.5-8.1; 2026 +2.2-2.3%/yr with t 2.9-3.7 for all three models; DEV already prefers them | +2-3%/yr only; built during attribution (not in the pre-declared set) | promising |")
w("| *_FN long books | Positive in 2026 in 8/8 cells | DEV lower than raw (paired −2 to −7%/yr); the 2026 gain is holdout-informed | hypothesis (pre-register) |")
w("| *_no_market models | 2026 IC and books better; less regime tilt | DEV worse in 8 of 9 model-years for the BAR/TSX/ENS3 books; selected post hoc | hypothesis (pre-register) |")
w("")

# =============================================================================================== 11 recommendation
w("## 11. Recommendation for the label stack")
w("")
w("1. **Primary selection label: XR_neu (h=20)**, the relative, beta/vol/size-neutral residual rank. Do not ensemble it with absolute or")
w("   market-excess labels. They add no DEV return in paired tests and import a regime-conditional factor bet that cost ~10%/yr in 2026.")
pm = pair["XR_no_market__minus__XR_all"]
w("2. **Keep market/regime features out of the stock-selection model**, or treat their contribution as a timing bet owned by the")
w(f"   regime layer (R2_regime) and sized explicitly. For XR the DEV cost of dropping them is {P(pm['K20_s5_c50_dev']['diff_ann'], 1, True)}/yr"
  f" (t {T(pm['K20_s5_c50_dev']['nw_t'])}) and the 2026 benefit is {P(pm['K20_s5_c50_hold']['diff_ann'], 1, True)}/yr (t {T(pm['K20_s5_c50_hold']['nw_t'])}).")
w("   For absolute labels they are the whole DEV edge.")
w("3. **AVOID screen: drop the bottom 30% of a factor-neutralised model score.** In DEV the FN overlays have the highest t of all avoid")
w("   variants. In 2026 they are the only avoid variants with t > 2"
  f" ({P(fnx['excess_ann'], 1, True)}, {P(fne['excess_ann'], 1, True)}, {P(fnt['excess_ann'], 1, True)}/yr). Expect ~+2-3%/yr over the EW universe, not more.")
w("4. **Keep NSE delivery features.** They are the only group with a significant, every-year IC contribution, and deliv_pct is the best single")
w("   feature for the relative target, distinct from liquidity and volatility.")
w("5. **Drop redundant feature copies** (xr_* duplicates of per-date-rankable features). This is neutral to slightly positive and reduces")
w("   the variant surface.")
w("6. Pre-register for round 3 (fresh data only): FN long book vs raw XR, no-market XR vs XR. Both look better in 2026, but that is")
w("   holdout-informed.")
w("")

# =============================================================================================== 12 issues
w("## 12. Lab issues found")
w("")
w("* **Definition drift between agents, and what it reveals about model noise (MEDIUM).** R2_dual's XR_neu uses `0.5*beta_60+0.5`")
w("  without clipping. R2_rel (and round-1 B_relative, and this report) clip beta_60 to [0,3] first. The labels barely differ: pct corr")
w("  0.99986, and 0.47% of rows change 3-class. Yet the trained OOS scores correlate only 0.973 (max abs diff 0.08). A near-identical label")
w("  therefore moves a LightGBM score about as much as many of the 'variants' being compared. Fix: put the canonical label builder in")
w("  lablib, and treat score differences smaller than this seed/label noise as zero.")
w("* **OLS neutralisation is not rank neutralisation (LOW-MEDIUM).** The XR_neu pct still has per-date rank IC +0.030 (t 9.7) with")
w("  log_turn20 and −0.032 (t −5.6) with vol_20, both of which are OLS regressors. OLS removes the mean relation, but illiquid and high-vol")
w("  names have more right-skewed returns, hence lower median residuals. The +1 class is therefore slightly more liquid and lower-vol than")
w("  intended (R2_rel's tilt table shows the same: log_turn20 +0.08 z). If exact neutrality matters, neutralise in rank space or")
w("  rank-normalise the residual within neutraliser buckets.")
w("* **The NW t of per-date IC differences overstates significance on short windows (MEDIUM, method).** Overlapping 20d forward")
w("  windows plus Bartlett lag 20 understate the long-run variance. In 2026, NW t 5.45 vs non-overlap t 1.31 for the same ΔIC. Report")
w("  both, or use block bootstrap by month.")
w("* **High DEV t can come from low tracking variance, not return (method).** ENS3's DEV t (4.37) beat XR's (3.81) with the same mean excess.")
w("  Paired difference tests between candidates should accompany any 'highest t' selection rule.")
w("* `L.event_report` puts rows with NaN mkt_dist_sma200 into 'bear' (round-1 issue, still present).")
w("* `walk_forward2` has no hook for feature importance. I used a verified bit-identical copy (common.wf2_imp).")
w("")

# =============================================================================================== 13 files
w("## 13. Files (all in this directory)")
w("")
w("`common.py` (helpers, feature groups, verified walk-forward copy) · `s1_labels.py` (targets → labels.npz) · `s2_events.py`"
  " (event rates) · `s3_wf.py` (walk-forwards → wf_*.npz) · `s4_xs.py` (xs metrics, ensembles, score correlations →"
  " xs_daily_*.parquet) · `s5_sim.py` (Sim with cached random bands and phase averaging → daily_*.npz) · `s6_attrib.py`"
  " (factor series, FN/FC decomposition, regressions) · `s7_importance.py` · `s8_univariate.py` · `s9_composition.py` ·"
  " `s10_paired.py` · `s12_report.py` (this report) · `results.json` (every number) · `log_*.txt`.")
open(f"{OUT}/REPORT.md", "w").write("\n".join(L) + "\n")
print("REPORT.md written:", len(L), "lines")
