"""R3_risk: summary numbers + report text, composed ONLY from values already in results.json."""
import sys

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

C.set_agent("R3_risk")
R = C.load_res()
pa = R["item1_phase_avg"]
dd = R["item1_drawdowns"]
ex = R["item2_exposure"]["results"]
ad = R["item2_exposure"]["adoption"]
ga = R["item2_governor_attribution"]
shc = R["item2_sharpe_vs_cash"]
xp = R["item3_expectations"]
kb = R["item4_kill_bootstrap"]
kn = R["item4_kill_null_books"]
kh = R["item4_kill_historical"]
mm = R["item4_monitor_metrics"]
sl = R["item4_slippage_budget"]
qx = R["item1_quarterly_excess"]["quarters"]
y26 = sum(v["excess_vs_random"] for k, v in qx.items() if k.startswith("2026"))
q25q4 = qx["2025Q4"]["excess_vs_random"]
yr_sums = {y: sum(v["excess_vs_random"] for k, v in qx.items() if k.startswith(str(y))) for y in (2023, 2024, 2025, 2026)}
C.save("item1_excess_by_year_sum", {"by_year_sum_of_daily_excess": yr_sums, "q2025Q4": q25q4, "sum_2026_ytd": y26,
                                    "note": "sums of daily (book - random) on the contiguous phase-averaged book; 2026 to Oct-14"})
t1 = dd["top5"][0]
b40 = {h: kb[f"b40_{h}"] for h in ("H1a", "H1b", "H0")}
fa_rng = {k: (min(kb[f"b{b}_H1a"][k]["p_fire_24m"] for b in (20, 40, 60)),
              max(kb[f"b{b}_H1a"][k]["p_fire_24m"] for b in (20, 40, 60))) for k in b40["H1a"]}
P = lambda x: f"{100 * x:.1f}%"  # noqa: E731
F3 = lambda x: f"{x:.3f}"  # noqa: E731

txt = f"""# R3_risk — exposure, drawdowns, expectations, monitoring and kill rules

Frozen PROD book (PREREG_R3): weekly, 4 staggered sleeves, top-20, 20-day time exit, elig_base (liq2), 50 bps
(80 bps stress), phase-averaged over the 5 weekly entry phases. DEV = 2023-2025 (selection), 2026 = reported only.
All numbers below are in results/R3_risk/results.json. Pre-declaration (incl. the 3 extra kill-rule combos) was
saved in results.json before any number was computed (section `predeclared`).

## 1. Drawdown anatomy (contiguous 2023-01 -> 2026-10, phase-averaged, 50 bps)
* Book: CAGR {P(pa['contig_c50']['pa_cagr'])}, excess vs random {P(pa['contig_c50']['pa_excess_ann'])}/yr (NW t {pa['contig_c50']['pa_nw_t']:.2f}),
  maxDD {P(pa['contig_c50']['pa_maxdd'])}; random top-20 maxDD {P(dd['underwater']['random']['maxdd'])}, EW universe
  {P(dd['underwater']['ew']['maxdd'])}, Nifty 500 (price) {P(dd['underwater']['nifty500']['maxdd'])}.
* Worst episode: peak {t1['peak']} -> trough {t1['trough']} ({P(t1['depth'])}, {t1['days_peak_to_trough']} trading days), back to peak
  {t1['recovery']} ({t1['days_peak_to_recovery']} trading days). Same window: random {P(t1['random_peak_to_trough'])}, EW
  {P(t1['ew_peak_to_trough'])}, Nifty 500 {P(t1['nifty500_peak_to_trough'])}. Boring explanation confirmed: a market-wide
  small/mid-cap sell-off, not a model failure (book minus random {P(t1['excess_vs_random_peak_to_trough'])}).
* 5th episode is still open: peak {dd['top5'][4]['peak']}, {P(dd['top5'][4]['depth'])} so far, {P(dd['top5'][4]['excess_vs_random_peak_to_trough'])} vs random.
* Monthly ({dd['monthly_dist']['book']['n_months']} months): mean {P(dd['monthly_dist']['book']['mean'])}, sd {P(dd['monthly_dist']['book']['sd'])},
  worst {P(dd['monthly_dist']['book']['min'])}; beat random in {P(dd['monthly_beat']['dev']['pct_months_beat_random'])} of DEV months and
  {P(dd['monthly_beat']['hold_2026']['pct_months_beat_random'])} of 2026 months. In Nifty-500 months below -3% the book averaged
  {P(dd['monthly_conditional_on_market']['n500_down_gt3']['book_mean'])} vs Nifty {P(dd['monthly_conditional_on_market']['n500_down_gt3']['nifty500_mean'])}:
  a full-beta mid/small-cap long book with no downside protection.
* Excess by year (sum of daily excess, contiguous): 2023 {P(yr_sums[2023])}, 2024 {P(yr_sums[2024])}, 2025 {P(yr_sums[2025])},
  2026 YTD {P(y26)}.

## 2. Exposure policies (pre-declared X100 / X80 / X60 / G50)
* Validation: own sleeve simulator = L.Sim bit-exact (max abs daily diff {R['item2_validation']['PROD']['max_abs_daily_diff']}).
* PROD DEV: X100 CAGR {P(ex['PROD_dev_c50_X100']['cagr'])} / maxDD {P(ex['PROD_dev_c50_X100']['maxdd'])}; X80 {P(ex['PROD_dev_c50_X80']['cagr'])} /
  {P(ex['PROD_dev_c50_X80']['maxdd'])}; X60 {P(ex['PROD_dev_c50_X60']['cagr'])} / {P(ex['PROD_dev_c50_X60']['maxdd'])}; G50 {P(ex['PROD_dev_c50_G50']['cagr'])} /
  {P(ex['PROD_dev_c50_G50']['maxdd'])} (risk-off on {P(ex['PROD_dev_c50_G50']['share_signals_risk_off'])} of signals,
  {ex['PROD_dev_c50_G50']['switches_per_year']:.1f} switches/yr).
* 2026: X100 {P(ex['PROD_hold_c50_X100']['cagr'])} / {P(ex['PROD_hold_c50_X100']['maxdd'])}; G50 {P(ex['PROD_hold_c50_G50']['cagr'])} /
  {P(ex['PROD_hold_c50_G50']['maxdd'])}. PRE 2021-09..2022-12 (EW book only, no PROD scores before 2023): X100
  {P(ex['EW_pre_c50_X100']['cagr'])} / {P(ex['EW_pre_c50_X100']['maxdd'])}; G50 {P(ex['EW_pre_c50_G50']['cagr'])} / {P(ex['EW_pre_c50_G50']['maxdd'])}
  with {ex['EW_pre_c50_G50']['switches_per_year']:.1f} switches/yr (whipsaw).
* Adoption rule: G50 DEV gain {P(ad['G50_dev_paired_diff_ann'])}/yr, NW t {ad['G50_dev_paired_nw_t']:.2f} -> NOT adopted (needs t >= 2).
  Its maxDD benefit is one episode: +{P(ga['diff_sum_in_top1_dd_window'])} inside {ga['window'][0]}..{ga['window'][1]},
  {P(ga['diff_sum_rest_of_dev'])} over the rest of DEV.
* Static cash is a risk dial, not alpha: Sharpe in excess of cash DEV X100 {shc['PROD_dev_c50_X100']:.2f}, X80 {shc['PROD_dev_c50_X80']:.2f},
  X60 {shc['PROD_dev_c50_X60']:.2f} (the rf=0 Sharpe rise {ex['PROD_dev_c50_X100']['sharpe']:.2f} -> {ex['PROD_dev_c50_X60']['sharpe']:.2f} is the cash yield).

## 3. Expectations (circular block bootstrap of DEV daily excess, 40-day blocks primary, 10,000 paths)
* +5%/yr plan: 12-month excess p5 {P(xp['dev_b40_t5']['excess_12m']['p5'])}, median {P(xp['dev_b40_t5']['excess_12m']['p50'])}, p95
  {P(xp['dev_b40_t5']['excess_12m']['p95'])}; P(negative excess year) {P(xp['dev_b40_t5']['p_negative_excess_year'])} (20-day blocks
  {P(xp['dev_b20_t5']['p_negative_excess_year'])}, 60-day {P(xp['dev_b60_t5']['p_negative_excess_year'])}); P(at least one negative year in two)
  {P(xp['dev_b40_t5']['p_at_least_one_negative_year_in_2'])}; 24-month excess median {P(xp['dev_b40_t5']['excess_24m']['p50'])}, P(<0)
  {P(xp['dev_b40_t5']['excess_24m']['p_neg'])}.
* Dead book (0%): P(12-month excess > +5%) {P(xp['dev_b40_t0']['excess_12m']['p_above_plus5'])} -> one year cannot separate skill from luck.
* Absolute (EW universe + excess, EW at its DEV mean, EW CAGR {P(xp['ew_dev_cagr'])}): +5% plan 12-month p5 {P(xp['dev_b40_t5']['absolute_12m']['p5'])},
  median {P(xp['dev_b40_t5']['absolute_12m']['p50'])}, p95 {P(xp['dev_b40_t5']['absolute_12m']['p95'])}, P(loss) {P(xp['dev_b40_t5']['absolute_12m']['p_neg'])};
  2-year worst fall median {P(xp['dev_b40_t5']['maxdd_24m']['p50'])}, P(worse than -20%) {P(xp['dev_b40_t5']['maxdd_24m']['p_worse_than_minus20'])},
  P(worse than -30%) {P(xp['dev_b40_t5']['maxdd_24m']['p_worse_than_minus30'])}.
* Daily excess autocorrelation is small (lag 20: {xp['excess_autocorr_dev']['20']:.3f}), so blocks widen the 12-month spread only modestly
  (sd {P(xp['dev_b1_t5']['excess_12m']['sd'])} iid -> {P(xp['dev_b40_t5']['excess_12m']['sd'])} 40-day blocks). Dependence matters far more
  for the IC (overlapping 20-day labels): see section 4.

## 4. Kill / review rules (weekly checks over the first 24 months; joint (excess, IC) block bootstrap on DEV)
H1a = +5%/yr with IC {F3(kb['ic_target_H1a'])} (as observed), H1b = +5%/yr with IC {F3(kb['ic_target_H1b'])} (IC scaled with the edge),
H0 = 0%/yr and IC 0. IC of signal date t is known at t+20. 40-day blocks (range over 20/60-day blocks in brackets).
| rule | false alarm H1a | false alarm H1b | detect H0 24m | median days |
|---|---|---|---|---|
""" + "\n".join(
    f"| {k} | {P(b40['H1a'][k]['p_fire_24m'])} ({P(fa_rng[k][0])}-{P(fa_rng[k][1])}) | {P(b40['H1b'][k]['p_fire_24m'])} | "
    f"{P(b40['H0'][k]['p_fire_24m'])} | {b40['H0'][k]['median_first_fire_days']} |" for k in b40["H1a"]) + f"""

* K1 = 6m excess < -5%; K2 = 3m mean matured IC < 0.02; K3 = 12m excess < 0; C1 = any; C2 = K3 AND K2; C3 = K1 AND K2.
* iid resampling (reference only, NOT used) would put K2's H1a false alarm at {P(kb['b1_H1a']['K2']['p_fire_24m'])} vs
  {P(b40['H1a']['K2']['p_fire_24m'])} with 40-day blocks: ignoring the IC's persistence badly understates false alarms.
* Persistence-matched null books (100 AR(1)+entity scores fitted to PROD's rank autocorrelation, w {kn['w']:.3f}, rho {kn['rho']:.3f}):
  C2 detection {P(kn['H0']['C2_kill']['p_fire_24m'])}, false alarm H1a {P(kn['H1a']['C2_kill']['p_fire_24m'])}. Null books have lower
  tracking error ({P(kn['null_tracking_error_daily_ann'])} vs model {P(kn['model_tracking_error_contig'])}) and IC noise
  ({kn['null_ic_daily_sd']:.3f} vs {kn['model_ic_daily_sd_contig']:.3f}), so their false alarms are optimistic; the bootstrap is primary.
* On our own backtest only K1 ever fired ({', '.join(kh['K1']['fire_dates_dev'])}; false alarm: 12m excess never below
  {P(kh['min_values']['ex12m_min'])}); the 3m IC minimum was {F3(kh['min_values']['ic3m_min'])} ({kh['min_values']['ic3m_min_date']}).
  Last check {kh['last_check']['date']}: 6m {P(kh['last_check']['ex6m'])}, 12m {P(kh['last_check']['ex12m'])}, IC {F3(kh['last_check']['ic3m'])} -> no rule active.
  Watch-out: the 12m figure still contains 2025-Q4 ({P(q25q4)}); 2026 YTD excess is only {P(y26)}, so K3 can trigger a review in early 2027.

Recommended rule set: REVIEW (investigate, no automatic action) when any of K1, K2, K3 fires — expect at least one review
in 24 months even for a good book ({P(b40['H1a']['C1_review']['p_fire_24m'])}). KILL (stop new entries, let sleeves run off)
when C2 fires: {P(b40['H1a']['C2_kill']['p_fire_24m'])} false alarm vs {P(b40['H0']['C2_kill']['p_fire_24m'])} detection, typically ~{b40['H0']['C2_kill']['median_first_fire_days']:.0f}
trading days after a book dies. The K2 review is the early warning: a dead signal trips it at the first possible check
({b40['H0']['K2']['median_first_fire_days']:.0f} trading days). If the true IC of a good book were only ~{F3(kb['ic_target_H1b'])} (H1b), C2's
false alarm would be {P(b40['H1b']['C2_kill']['p_fire_24m'])}: re-calibrate if the 13-week IC runs below its DEV 10th percentile
({F3(mm['dev']['ic']['rolling13w']['p10'])}) while excess stays positive.

## 5. Weekly dashboard (DEV normal ranges; 2026 reported)
* Rank IC: DEV {F3(mm['dev']['ic']['daily']['mean'])} (weekly p10 {F3(mm['dev']['ic']['weekly']['p10'])}, p90 {F3(mm['dev']['ic']['weekly']['p90'])}); 2026 {F3(mm['hold_2026']['ic']['daily']['mean'])}.
* Top-20 relative hit (label pct > 0.5): DEV {F3(mm['dev']['rel_hit']['daily']['mean'])}, 2026 {F3(mm['hold_2026']['rel_hit']['daily']['mean'])}; absolute hit (net > 0):
  DEV {F3(mm['dev']['abs_hit']['daily']['mean'])}, 2026 {F3(mm['hold_2026']['abs_hit']['daily']['mean'])}.
* Top-20 raw 20d return minus universe: DEV {P(mm['dev']['top_ex']['daily']['mean'])}, 2026 {P(mm['hold_2026']['top_ex']['daily']['mean'])};
  avoid tail (bottom 30%) minus universe: DEV {P(mm['dev']['avoid_ex']['daily']['mean'])}, 2026 {P(mm['hold_2026']['avoid_ex']['daily']['mean'])}.
  2026 = signal intact, monetisation gone (consistent with factor tilts; not verified here).
* Turnover: top-20 overlap with the same sleeve 4 weeks earlier DEV {F3(mm['dev']['ovl20']['daily']['mean'])}, 2026 {F3(mm['hold_2026']['ovl20']['daily']['mean'])}
  (every pick is a full round trip under the frozen time exit).
* Slippage vs open: budget {sl['slippage_budget_bps_per_side_central']:.2f} bps/side beyond ~{sl['statutory_round_trip_bps']} bps statutory (50 bps all-in);
  stress {sl['slippage_budget_bps_per_side_stress']:.2f} bps/side (80 bps), which cost {P(sl['cagr_drag_50_to_80_dev'])}/yr of DEV CAGR.

## Pros
* Drawdowns are market drawdowns: worst episode matched random/EW; overall maxDD shallower than random and EW over 2023-2026.
* A money-AND-signal kill rule (C2) separates good from dead books far better than money-only rules.
* The IC is a fast, objective diagnostic (matures in 20 days) and stayed normal through 2026.
* Static exposure is a clean risk dial (Sharpe vs cash unchanged), letting the client pick risk without touching the edge.
## Cons
* No exposure policy passes the adoption rule; the breadth governor's benefit is one episode and it whipsawed in 2022.
* One year cannot tell a +5% book from a dead one; money-only rules give 52-61% false alarms in 24 months.
* IC-based rules assume a good book keeps IC near its DEV level; if IC scales down with the edge, C2's false alarm jumps.
* Full-beta mid/small-cap book: ~1 in 4.5 chance of a losing 12 months even with the planned edge; typical 2-year worst fall ~-21%.
## Caveats
* PROD exists only 2023+ (walk-forward); PRE uses the EW-universe book. Nifty 500 is a price index (no dividends).
* Absolute ranges use the DEV equal-weight drift (a strong small-cap period). The +5%/yr plan is round-2's haircut, not estimated here.
* 20-day excess and IC are nearly uncorrelated in DEV (corr {kb['corr_20d_excess_vs_ic']:.3f}); that is why C2 (AND) cuts false alarms so
  much. 20-60-day blocks cannot represent year-long joint slumps of money and signal, so C2's false alarm may be optimistic
  if such regimes exist. The IC is persistent only inside the label window (daily autocorr lag 1 {mm['dev']['ic_autocorr_daily_lag1']:.2f},
  lag 20 {mm['dev']['ic_autocorr_daily_lag20']:.3f}).
* 2026 money vs signal disagreement: IC {F3(mm['hold_2026']['ic']['daily']['mean'])} and relative hit {F3(mm['hold_2026']['rel_hit']['daily']['mean'])} were
  normal, but the 13-week top-20 raw lead averaged {P(mm['hold_2026']['top_ex']['rolling13w']['mean'])} per 20 days (DEV {P(mm['dev']['top_ex']['rolling13w']['mean'])}).
  The rules, by design, keep such a book running; the client must accept that.
* Variants: exposure 3 policies (+1 diagnostic) on 2 books x 3 periods; kill rules 3 pre-declared + 3 pre-justified combos. Selection on DEV only.
"""
C.save("report_md", txt)
C.log("report chars", len(txt))
print(txt)
