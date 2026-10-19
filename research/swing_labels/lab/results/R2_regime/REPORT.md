# R2_regime — Market regime & exposure layer (lab v2)

Agent R2_regime, round 2. Question: absolute labels mostly encode the market, so can the market be timed *separately* and used as an exposure scaler on top of a regime-free relative book, net of whipsaw? Lab v2 only (no sector data, ETFs excluded, rebuilt `elig_base`). Next-open entry, NaN where undefined, filters never change labels, models via `L.walk_forward2`, investability via the `L.Sim` maths (my `PathSim` re-implementation is verified bit-identical: max |equity diff| = 0.0 vs `L.Sim.run` for the EW, XR20 and random books), 50 and 80 bps, selection on DEV (2023-2025) only, 2026 (Jan 1 - Oct 14) reported separately. A third window, PRE (2021-09 .. 2022-12), is used only for parameter-free rules (no fitting) as an extra out-of-sample check; it was never used for selection.

## 1. Verdict

**Market timing does not reliably help net of whipsaw. Do not put a direction-timing layer in the label stack.** The evidence:

1. **The premise holds: absolute labels are mostly market.** Date effects carry 22.9% of 20-day stock-return variance and 18.5% of the variance of the 0/1 sign label. The daily share of +1 labels correlates 0.88 (DEV) / 0.95 (2026) with the Nifty-500 next-20d return and 0.98 with the equal-weight universe return. On DEV it ranges 6.5%..96.7%.
2. **The market part is not predictable from PIT regime features in this sample.** Of 14 pre-declared timing signals (5 rules, 9 walk-forward models), only breadth50>0.5 (AUC 0.61 for EW>0), mom60>0 (0.56) and the VOTE composite that contains them (0.53) beat 0.5 on DEV. All 9 walk-forward models are *anti*-predictive on DEV (AUC 0.39-0.47): their coefficients flip sign between folds. Single-feature correlations with the next-20d return change sign between 2021-22, 2023-25 and 2026. The 200-dma rule has AUC 0.47 on DEV and 0.31 in 2026. Only one signal, breadth, beats the trivial 'always risk-on' accuracy on DEV, and only barely (0.622 vs 0.603).
3. **The DEV-best gate wins in one episode on DEV and is mixed out of sample.** The pre-declared criterion (EW book, sleeve gating, 50 bps, DEV gain in cash-adjusted Sharpe) picks breadth50>0.5 with 0% risk-off. EW book on DEV: CAGR 10.8% -> 15.6%, Sharpe_xs 0.32 -> 0.77, maxDD -28.9% -> -12.9%. Its circular-shift null p is 0.085 as a single test, against 28 variants per book, so it fails multiple testing. The DEV gain is one episode: 2025 went from -14.2% to 4.2%, while 2024 went from 13.3% to 4.2%. Out of sample it is mixed. In PRE (2021-22) it loses: CAGR -4.9 pp, Sharpe_xs -0.73, null p 0.915. In 2026 it beats its own random-timing null (phase-0 p 0.000 for Sharpe and 0.000 for maxDD): random de-risking was expensive in 2026's V-shaped year (null mean dSharpe -0.40), and breadth avoided that cost. Against always-in it merely breaks even: EW +0.6 pp CAGR, Sharpe_xs +0.05; XR20 -3.7 pp. Its yearly AUC vs E0 is above 0.5 in 3 of 6 years. The classic 200-dma rule changes 2026 CAGR by -20.3 pp (EW) and -23.7 pp (XR20).
4. **Drawdown cuts are mostly mechanical.** A coin-flip timer (50% block accuracy, invested about half the time) cuts DEV maxDD of the EW book by 13.6 pp. A static mix with the same average exposure is Sharpe-neutral, and its maxDD is only 4-8 pp worse than the best timers on DEV. On PRE, the breadth gate's maxDD is 9.3 pp *worse* than the static mix's.
5. **Whipsaw makes it worse, and the result depends on how the rule is implemented.** In a noisy-oracle test, sleeve gating (switching only at the book's own rebalances, no extra trades) needs about 60% block accuracy for a reliable gain. A daily overlay paying 50 bps per round-trip switch needs about 70%. The same rule changes sign with the implementation: the 200-dma rule is -1.0 pp as a sleeve gate and +3.2 pp as a daily overlay on DEV. As pure index timing, breadth is -8.3 pp on DEV and +15.7 pp in 2026.
6. **The selection edge does not depend on the regime, so timing only scales beta.** The XR_neu top-20 excess over random is +1.21% per 20-day trade when the market rises and +1.28% when it falls (slope on the market return t = 0.39). No regime signal splits it significantly (|t| <= 1.02 on DEV). The relative label is regime-free, as round 1 found. A regime layer cannot improve selection; it can only change how much capital is exposed.
7. **A risk-based scaler fails too.** Volatility targeting, x = min(1, median vol / current vol), gives EW DEV Sharpe -0.13 (null p 0.82) and -0.36 in 2026. Indian 20-day index returns mean-reverted after stress in 2021-22 and 2026, so de-risking on high vol or broken trends sold near lows.

**Recommendation for the label stack.** Primary = a regime-free relative label (XR_neu / R2_rel's neumom). Regime layer = **none as a return source**. Set the long book's gross exposure as a fixed, client-chosen policy. Static de-risking keeps the cash-adjusted Sharpe and cuts drawdown roughly in proportion. If the client insists on a drawdown governor, the least-bad pre-registered option is breadth50<0.5 => 50% risk-off, applied only at the sleeve's own rebalance (no extra trades). On XR20 it changed CAGR by -1.3 pp (DEV) and -1.5 pp (2026), and maxDD by +10.8 / +8.0 pp. Against a static mix with the same exposure that is +3.2 / -0.0 pp CAGR and +5.2 / +4.3 pp maxDD. On the EW book in PRE it cost -4.4 pp vs static. Treat it as insurance with uncertain, possibly negative, expected cost, not as alpha. Never use a 200-dma or VIX trend filter: both were harmful in 2 of 3 windows, and the 200-dma rule lost about 20 pp of CAGR in 2026. Absolute (market-direction) labels should not be modelled per stock. Their day-to-day class mix is almost entirely the market's next 20 days (corr 0.88-0.98), and that part is not forecastable here. The stock-specific part is exactly what the relative label already isolates.

## 2. Setup

* **Date-level dataset** (`dateset.parquet`, 1,434 trading dates 2021-01-01..2026-10-14): the 10 lab market features (`mkt_mom5/20/60, mkt_dist_sma50/200, mkt_vol20, vix, breadth50, breadth_ad, dispersion`; constant per date, verified) + `vix_rel = vix / trailing-250d median - 1` (PIT, min 120 obs).
* **Targets** (signal at close g, executable): `N0 = 1{N500 open[g+1]->close[g+20] > 0}`, `N1 = ... > +1%`, `E0 = 1{mean over elig_base of open[t+1]->close[t+20] > 0}` (rows with `fw.ok(20)` false dropped; coverage 99.7-99.9%). EW targets start 2021-06-29 (120-bar seasoning).
* **Rules** (parameter-free, pre-declared): R200 `mkt_dist_sma200>0`; RBR `breadth50>0.5`; RVIX `vix_rel<0`; RM60 `mkt_mom60>0`; VOTE graded exposure = mean of the four.
* **Walk-forward models**: yearly expanding folds 2023..2026, embargo h+2 = 22 trading days, trained on dates from 2021-01-01 with complete features (325 dates for the 2023 fold, 1,069 for 2026, i.e. about 16-53 independent 20-day windows). LOG4 = L2-logit (C=0.1, standardized) on [dist_sma200, breadth50, vix_rel, mom60]; LOG10 = L2-logit on the 10 features; LGB10 = LightGBM depth 2, 100 trees, min_child 60. Risk-on = p >= 0.5 (pre-declared, never tuned).
* **Books** (h=20, step=5, 4 staggered sleeves, next-open entry, time exit, half cost per side, cash 6.5%): **EW** = every elig_base name equal-weight (`sizing='equal', select_quantile=(0,1)`); **XR20** = long top-20 of the XR_neu walk-forward regression (label identical to R2_rel `neu`, max diff 3.0e-08; score corr 0.9988 with R2_alpha's; xs IC vs r20 DEV 0.072 (t 4.31), 2026 0.047 (t 1.46)); **RND20** = 5-seed random top-20 on the same mask.
* **Exposure implementations.** (A) *Sleeve gating* (primary): at each signal date the rebalancing sleeve invests x of its equity (1 risk-on, 0.5 or 0 risk-off; VOTE graded) and keeps the rest in cash. Sleeves turn over fully every 20 days anyway, so gating adds no trades, and portfolio exposure moves in 25% steps. Exact and linear: path_x = (1-x)*cash + x*path_1. (B) *Daily overlay*: the always-in book's daily return is scaled by the state from close d-2 (one extra day of lag, conservative), and every exposure change pays |dx|*cost/2. (C) *Pure index timing*: Nifty-500 open-to-open returns, state at close g traded at open g+1, 10 bps per side (and 0).
* **Benchmarks for every gated run.** Always-in (x=1). A static mix with the same average exposure. A circular-shift null: 200 random cyclic shifts of the state inside the window, which keep the exposure and persistence but destroy the timing. Foresight canaries.
* **Sharpe.** `Sharpe_xs` = (mean daily return - 6.5%/252) / sd * sqrt(252). The lab's `Sim` Sharpe is not cash-adjusted, and it rewards holding cash. A static 55%-invested EW mix raises the raw DEV Sharpe from 0.67 to 0.91 with zero skill, while Sharpe_xs is unchanged (0.32). All deltas below use Sharpe_xs. 'pavg' = average over the 5 signal-calendar phases (robust to the entry-day grid); null p-values use phase 0.

## 3. Absolute labels encode the market (quantified)

| window | dates | daily +1 share mean | min / max | sd | Pearson vs N500 f20 | Pearson vs EW f20 | Spearman vs N500 f20 (NW t) | corr N500 f20 vs EW f20 |
|---|---|---|---|---|---|---|---|---|
| DEV 2023-25 | 744 | 50.7% | 6.5% / 96.7% | 21.2% | 0.875 | 0.979 | 0.884 (t 20.0) | 0.861 |
| 2026 holdout | 174 | 48.7% | 7.2% / 96.2% | 22.0% | 0.948 | 0.979 | 0.946 (t 33.0) | 0.945 |
| All 2021-26 | 1294 | 49.5% | 4.5% / 96.7% | 21.7% | 0.876 | 0.978 | 0.877 (t 26.0) | 0.864 |

Between-date share of variance (elig_base, h=20, 2021-26): continuous return 22.9%, 0/1 sign label 18.5%. Any absolute label's day-to-day class mix is driven by the market's next 20 days.

## 4. Timing targets: event rates

| year | dates | N0 = N500 f20>0 | N1 = N500 f20>1% | E0 = EW f20>0 | mean N500 f20 | mean EW f20 |
|---|---|---|---|---|---|---|
| 2021 | 248 | 71.8% | 59.7% | 57.8% (128 d) | 1.93% | 1.47% |
| 2022 | 248 | 50.4% | 43.5% | 54.4% (248 d) | 0.07% | 0.04% |
| 2023 | 246 | 64.6% | 61.0% | 75.2% (246 d) | 1.88% | 3.47% |
| 2024 | 249 | 62.7% | 56.2% | 58.6% (249 d) | 0.77% | 1.08% |
| 2025 | 249 | 62.7% | 45.0% | 47.4% (249 d) | 0.57% | -0.39% |
| 2026 | 174 | 50.6% | 36.8% | 64.9% (174 d) | -0.52% | 1.31% |

By regime (`bull` = N500 above 200-dma, `up20` = 20d momentum > 0; share of dates with target = 1):

| window | regime | dates | N0 | N1 | E0 | mean N500 f20 | mean EW f20 |
|---|---|---|---|---|---|---|---|
| PRE | bull_up20 | 166 | 41.0% | 30.7% | 48.2% | -1.27% | -0.51% |
| PRE | bull_dn20 | 85 | 55.3% | 44.7% | 62.4% | 0.24% | -0.06% |
| PRE | bear_up20 | 22 | 72.7% | 72.7% | 72.7% | 4.15% | 2.95% |
| PRE | bear_dn20 | 59 | 67.8% | 61.0% | 61.0% | 2.54% | 2.73% |
| DEV | bull_up20 | 432 | 66.0% | 54.4% | 61.6% | 1.09% | 1.49% |
| DEV | bull_dn20 | 186 | 52.2% | 44.6% | 53.8% | 0.47% | 0.87% |
| DEV | bear_up20 | 46 | 97.8% | 95.7% | 93.5% | 4.15% | 6.01% |
| DEV | bear_dn20 | 80 | 55.0% | 50.0% | 50.0% | 0.60% | -0.73% |
| HOLD | bull_up20 | 68 | 32.4% | 19.1% | 47.1% | -2.66% | -2.21% |
| HOLD | bull_dn20 | 18 | 27.8% | 5.6% | 27.8% | -3.30% | -2.83% |
| HOLD | bear_up20 | 29 | 44.8% | 17.2% | 82.8% | -0.44% | 1.71% |
| HOLD | bear_dn20 | 79 | 81.4% | 76.3% | 88.1% | 2.76% | 6.43% |

DEV monthly share of N0 dates: mean 64.0%, sd 37.0%, min 0.0%, max 100.0%. 33% of months are all-0 or all-1 (E0: 44%). The target is extremely persistent, so the 744 DEV dates hold only about 37 independent 20-day observations. The regime relationship flips between windows. In DEV, 'bull_up20' dates were followed by N500 gains 66.0% of the time; in 2026 only 32.4%, and in PRE 41.0%. 'bear_dn20' dates were followed by gains 81.4% of the time in 2026 (20-day mean reversion).

## 5. Single-feature predictability (Spearman with next-20d return, NW t lag 20)

| feature | N500 PRE | N500 DEV | N500 2026 | EW PRE | EW DEV | EW 2026 |
|---|---|---|---|---|---|---|
| mkt_mom5 | -0.003 (-0.0) | +0.039 (+0.5) | -0.189 (-1.8) | +0.060 (+0.6) | +0.066 (+1.0) | -0.186 (-1.6) |
| mkt_mom20 | -0.102 (-0.6) | +0.172 (+1.7) | -0.398 (-2.4) | -0.011 (-0.1) | +0.220 (+2.0) | -0.421 (-2.7) |
| mkt_mom60 | -0.165 (-0.9) | +0.054 (+0.4) | -0.345 (-1.7) | -0.147 (-0.8) | +0.125 (+1.0) | -0.443 (-2.6) |
| mkt_dist_sma50 | -0.206 (-1.2) | +0.167 (+1.6) | -0.203 (-1.1) | -0.131 (-0.7) | +0.256 (+2.3) | -0.218 (-1.1) |
| mkt_dist_sma200 | -0.297 (-1.6) | +0.004 (+0.0) | -0.590 (-5.2) | -0.245 (-1.3) | +0.039 (+0.3) | -0.696 (-6.6) |
| mkt_vol20 | +0.117 (+0.7) | +0.061 (+0.5) | +0.223 (+1.0) | +0.087 (+0.5) | +0.036 (+0.3) | +0.309 (+1.4) |
| vix | +0.119 (+0.8) | +0.044 (+0.4) | +0.539 (+4.3) | +0.089 (+0.5) | +0.020 (+0.2) | +0.651 (+6.4) |
| breadth50 | -0.305 (-1.8) | +0.133 (+1.2) | -0.061 (-0.3) | -0.286 (-1.5) | +0.242 (+2.2) | -0.040 (-0.2) |
| breadth_ad | -0.008 (-0.1) | +0.034 (+0.9) | +0.013 (+0.2) | +0.008 (+0.1) | +0.075 (+2.2) | +0.026 (+0.4) |
| dispersion | -0.293 (-2.4) | +0.157 (+2.3) | +0.115 (+1.0) | -0.195 (-1.7) | +0.160 (+2.0) | +0.217 (+2.0) |
| vix_rel | +0.021 (+0.1) | +0.168 (+1.4) | +0.535 (+4.2) | +0.021 (+0.1) | +0.115 (+0.8) | +0.645 (+6.4) |

No feature has the same sign and |t| > 2 in all three windows. Trend features (dist_sma200, mom20/60, dist_sma50, breadth50) are negative in PRE and in 2026 and weakly positive in DEV. VIX is contrarian (high VIX -> higher returns) in 2026 (rho +0.54) and in DEV it is ~0.

## 6. Timing signals at the date level

| signal | definition | window | risk-on share | flips/yr | AUC N0 | AUC E0 | N500 f20 on-off pp (NW t) | EW f20 on-off pp (NW t) | accuracy E0 / always-on |
|---|---|---|---|---|---|---|---|---|---|
| R200 | N500 > 200d SMA | DEV | 83% | 4.0 | 0.473 | 0.480 | -0.99 (-0.8) | -0.43 (-0.2) | 0.550 / 0.603 |
| R200 | N500 > 200d SMA | HOLD | 44% | 19.2 | 0.310 | 0.262 | -4.50 (-3.3) | -7.21 (-3.4) | 0.282 / 0.649 |
| R200 | N500 > 200d SMA | PRE | 76% | 9.0 | 0.414 | 0.458 | -3.74 (-1.7) | -3.14 (-1.2) | 0.488 / 0.557 |
| RBR | breadth50 > 0.5 | DEV | 58% | 15.4 | 0.580 | 0.610 | +0.99 (+1.4) | +2.16 (+1.8) | 0.622 / 0.603 |
| RBR | breadth50 > 0.5 | HOLD | 51% | 7.7 | 0.534 | 0.635 | +0.71 (+0.3) | +0.12 (+0.0) | 0.644 / 0.649 |
| RBR | breadth50 > 0.5 | PRE | 56% | 15.1 | 0.396 | 0.383 | -2.50 (-2.0) | -2.96 (-1.6) | 0.392 / 0.557 |
| RVIX | VIX < 250d median | DEV | 60% | 12.7 | 0.415 | 0.421 | -1.05 (-1.6) | -1.15 (-0.9) | 0.445 / 0.603 |
| RVIX | VIX < 250d median | HOLD | 31% | 14.0 | 0.301 | 0.297 | -3.58 (-3.1) | -5.11 (-2.9) | 0.259 / 0.649 |
| RVIX | VIX < 250d median | PRE | 48% | 16.6 | 0.522 | 0.542 | +0.32 (+0.2) | +1.23 (+0.7) | 0.539 / 0.557 |
| RM60 | N500 60d mom > 0 | DEV | 71% | 7.3 | 0.546 | 0.558 | +0.59 (+0.6) | +1.77 (+1.1) | 0.598 / 0.603 |
| RM60 | N500 60d mom > 0 | HOLD | 40% | 16.6 | 0.478 | 0.500 | -0.73 (-0.4) | -2.21 (-0.8) | 0.483 / 0.649 |
| RM60 | N500 60d mom > 0 | PRE | 58% | 15.1 | 0.498 | 0.503 | -0.93 (-0.5) | -0.13 (-0.1) | 0.512 / 0.557 |
| VOTE | graded: #rules on / 4 | DEV | 68% | 36.4 | 0.492 | 0.529 | -0.09 (-0.1) | +1.70 (+0.6) | n/a |
| VOTE | graded: #rules on / 4 | HOLD | 41% | 51.1 | 0.345 | 0.373 | -3.96 (-1.7) | -7.11 (-1.9) | n/a |
| VOTE | graded: #rules on / 4 | PRE | 59% | 54.2 | 0.440 | 0.454 | -2.70 (-1.2) | -1.92 (-0.7) | n/a |
| LOG4_N0 | logit(4 feats) -> P(N500 f20>0) | DEV | 59% | 9.3 | 0.447 | 0.446 | -0.11 (-0.1) | -0.58 (-0.4) | 0.487 / 0.603 |
| LOG4_N0 | logit(4 feats) -> P(N500 f20>0) | HOLD | 100% | 0.0 | 0.704 | 0.795 | n/a (n/a) | n/a (n/a) | 0.649 / 0.649 |
| LOG4_N1 | logit(4 feats) -> P(N500 f20>1%) | DEV | 42% | 9.0 | 0.451 | 0.449 | -0.13 (-0.1) | -0.62 (-0.4) | 0.454 / 0.603 |
| LOG4_N1 | logit(4 feats) -> P(N500 f20>1%) | HOLD | 93% | 1.3 | 0.694 | 0.791 | +0.44 (+0.3) | +3.45 (+1.6) | 0.655 / 0.649 |
| LOG4_E0 | logit(4 feats) -> P(EW f20>0) | DEV | 77% | 16.0 | 0.449 | 0.422 | -1.07 (-1.4) | -1.83 (-1.3) | 0.503 / 0.603 |
| LOG4_E0 | logit(4 feats) -> P(EW f20>0) | HOLD | 100% | 0.0 | 0.660 | 0.767 | n/a (n/a) | n/a (n/a) | 0.649 / 0.649 |
| LOG10_N0 | logit(10 feats) -> P(N500 f20>0) | DEV | 62% | 30.0 | 0.440 | 0.386 | -0.64 (-0.9) | -1.75 (-1.4) | 0.444 / 0.603 |
| LOG10_N0 | logit(10 feats) -> P(N500 f20>0) | HOLD | 92% | 12.8 | 0.347 | 0.428 | -7.28 (-5.7) | -12.26 (-6.5) | 0.586 / 0.649 |
| LOG10_N1 | logit(10 feats) -> P(N500 f20>1%) | DEV | 51% | 18.0 | 0.455 | 0.407 | -0.80 (-1.0) | -2.28 (-1.8) | 0.398 / 0.603 |
| LOG10_N1 | logit(10 feats) -> P(N500 f20>1%) | HOLD | 68% | 17.9 | 0.356 | 0.437 | -2.65 (-1.3) | -5.39 (-1.8) | 0.546 / 0.649 |
| LOG10_E0 | logit(10 feats) -> P(EW f20>0) | DEV | 82% | 21.4 | 0.464 | 0.389 | -1.28 (-1.8) | -3.66 (-3.6) | 0.469 / 0.603 |
| LOG10_E0 | logit(10 feats) -> P(EW f20>0) | HOLD | 83% | 28.1 | 0.398 | 0.493 | -2.61 (-1.1) | -5.37 (-1.5) | 0.598 / 0.649 |
| LGB10_N0 | LGBM d2(10 feats) -> P(N500 f20>0) | DEV | 69% | 16.7 | 0.449 | 0.470 | -0.50 (-0.6) | -0.73 (-0.6) | 0.509 / 0.603 |
| LGB10_N0 | LGBM d2(10 feats) -> P(N500 f20>0) | HOLD | 74% | 34.5 | 0.468 | 0.486 | +1.19 (+0.6) | +1.59 (+0.6) | 0.569 / 0.649 |
| LGB10_N1 | LGBM d2(10 feats) -> P(N500 f20>1%) | DEV | 54% | 21.4 | 0.463 | 0.449 | -0.14 (-0.2) | -0.72 (-0.6) | 0.473 / 0.603 |
| LGB10_N1 | LGBM d2(10 feats) -> P(N500 f20>1%) | HOLD | 61% | 20.4 | 0.525 | 0.557 | +0.51 (+0.3) | +1.50 (+0.6) | 0.529 / 0.649 |
| LGB10_E0 | LGBM d2(10 feats) -> P(EW f20>0) | DEV | 74% | 26.0 | 0.436 | 0.419 | -0.04 (-0.1) | -0.04 (-0.0) | 0.542 / 0.603 |
| LGB10_E0 | LGBM d2(10 feats) -> P(EW f20>0) | HOLD | 62% | 33.2 | 0.515 | 0.588 | +0.87 (+0.5) | +2.11 (+0.8) | 0.586 / 0.649 |

By-year AUC vs E0 (EW universe up next 20d) and risk-on share:

| signal | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| R200 | 0.50 / 100% | 0.44 / 67% | 0.48 / 84% | 0.49 / 99% | 0.43 / 66% | 0.26 / 44% |
| RBR | 0.31 / 67% | 0.39 / 54% | 0.78 / 71% | 0.44 / 68% | 0.57 / 35% | 0.64 / 51% |
| RVIX | 0.45 / 91% | 0.57 / 35% | 0.43 / 90% | 0.35 / 22% | 0.39 / 69% | 0.30 / 31% |
| RM60 | 0.41 / 91% | 0.54 / 50% | 0.63 / 72% | 0.57 / 82% | 0.47 / 58% | 0.50 / 40% |
| VOTE | 0.29 / 82% | 0.48 / 52% | 0.68 / 79% | 0.41 / 68% | 0.41 / 57% | 0.37 / 41% |
| LOG4_N0 |  |  | 0.26 / 69% | 0.41 / 12% | 0.68 / 97% | 0.80 / 100% |
| LOG4_N1 |  |  | 0.28 / 52% | 0.40 / 1% | 0.71 / 72% | 0.79 / 93% |
| LOG4_E0 |  |  | 0.25 / 80% | 0.40 / 51% | 0.69 / 100% | 0.77 / 100% |
| LOG10_N0 |  |  | 0.25 / 57% | 0.34 / 28% | 0.69 / 100% | 0.43 / 92% |
| LOG10_N1 |  |  | 0.28 / 42% | 0.34 / 12% | 0.71 / 99% | 0.44 / 68% |
| LOG10_E0 |  |  | 0.27 / 65% | 0.45 / 80% | 0.68 / 100% | 0.49 / 83% |
| LGB10_N0 |  |  | 0.41 / 92% | 0.46 / 16% | 0.39 / 98% | 0.49 / 74% |
| LGB10_N1 |  |  | 0.38 / 63% | 0.45 / 6% | 0.47 / 92% | 0.56 / 61% |
| LGB10_E0 |  |  | 0.42 / 87% | 0.48 / 41% | 0.32 / 95% | 0.59 / 62% |

**Caveat (monitor, do not select).** The walk-forward logits rank 2025-26 well (LOG4 AUC vs E0: 2025 0.69-0.71, 2026 0.77-0.80) after ranking 2023-24 badly (0.25-0.45). In 2026 their calibrated probabilities never fell below the pre-declared 0.5 (risk-on 93-100%), so they changed no exposure. Their DEV AUC is below 0.5, so DEV selection cannot pick them, and a threshold re-chosen after seeing 2026 would be holdout selection. The coefficients that stabilised from the 2025 fold read 'buy fear, avoid over-extension' (dist_sma200 < 0, vix_rel > 0, mom60 > 0). This is the one timing hypothesis worth re-testing in round 3 on data after 2026-10.


Walk-forward coefficient instability (standardized L2-logit, target N0; sign flips across folds):

| model | test year | train dates | train base rate | dist_sma200 | breadth50 | vix_rel | mom60 |
|---|---|---|---|---|---|---|---|
| LOG4_N0 | 2023 | 325 | 56% | -0.59 | -0.63 | -0.68 | +0.18 |
| LOG4_N0 | 2024 | 571 | 57% | -0.65 | -0.09 | -0.22 | +0.39 |
| LOG4_N0 | 2025 | 820 | 61% | -0.33 | +0.01 | +0.27 | +0.37 |
| LOG4_N0 | 2026 | 1069 | 61% | -0.39 | +0.07 | +0.25 | +0.36 |
| LOG4_E0 | 2023 | 325 | 60% | -0.48 | -0.60 | -0.69 | +0.05 |
| LOG4_E0 | 2024 | 571 | 64% | -0.50 | +0.02 | -0.21 | +0.35 |
| LOG4_E0 | 2025 | 820 | 65% | -0.33 | +0.09 | +0.10 | +0.26 |
| LOG4_E0 | 2026 | 1069 | 60% | -0.39 | +0.22 | +0.24 | +0.31 |

## 7. Exposure scaler on the universe equal-weight book (sleeve gating, 50 bps, phase-averaged)

Null p-values: share of 200 circular shifts of the same state series (same exposure and persistence) whose improvement over always-in is at least the observed one (phase 0, equal exposure, so raw and cash-adjusted Sharpe give the same ranking). A low p means the timing beat random timing with the same exposure. It does not mean the timing beat always-in.

**DEV 2023-25.** Always-in: CAGR 10.8%, Sharpe_xs 0.32, maxDD -28.9%, exposure 93%.

| signal | risk-off x | CAGR | Sharpe_xs | maxDD | exposure | switches/yr | dCAGR pp | dSharpe_xs | dMaxDD pp | dCAGR vs static | dMaxDD vs static | NW t vs static | null p Sharpe | null p maxDD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R200 | 50% | 10.5% | 0.32 | -21.6% | 85% | 2.0 | -0.4 | -0.00 | +7.3 | -0.1 | +4.8 | -0.07 | 0.515 | 0.110 |
| R200 | 0% | 9.8% | 0.29 | -18.6% | 77% | 2.0 | -1.0 | -0.03 | +10.4 | -0.5 | +5.4 | -0.08 | 0.585 | 0.145 |
| RBR | 50% | 13.4% | 0.53 | -19.4% | 74% | 7.1 | +2.6 | +0.21 | +9.5 | +3.2 | +3.8 | +1.26 | 0.090 | 0.190 |
| RBR | 0% | 15.6% | 0.77 | -12.9% | 55% | 7.1 | +4.8 | +0.45 | +16.0 | +6.2 | +4.2 | +1.26 | 0.085 | 0.230 |
| RVIX | 50% | 8.7% | 0.23 | -21.6% | 74% | 6.7 | -2.1 | -0.09 | +7.3 | -1.4 | +1.4 | -0.63 | 0.445 | 0.435 |
| RVIX | 0% | 6.3% | 0.05 | -15.8% | 55% | 6.7 | -4.5 | -0.27 | +13.1 | -3.0 | +1.0 | -0.61 | 0.475 | 0.075 |
| RM60 | 50% | 13.3% | 0.50 | -17.9% | 79% | 4.6 | +2.5 | +0.18 | +11.0 | +2.9 | +6.7 | +1.01 | 0.095 | 0.045 |
| RM60 | 0% | 15.4% | 0.67 | -14.3% | 65% | 4.6 | +4.6 | +0.35 | +14.7 | +5.6 | +5.9 | +1.01 | 0.100 | 0.120 |
| VOTE | 50% | 11.5% | 0.40 | -20.1% | 78% | 15.8 | +0.7 | +0.08 | +8.8 | +1.2 | +4.2 | +0.54 | 0.180 | 0.015 |
| VOTE | 0% | 11.9% | 0.50 | -11.5% | 63% | 15.8 | +1.1 | +0.18 | +17.5 | +2.2 | +8.1 | +0.53 | 0.170 | 0.015 |
| LOG4_N0 | 50% | 9.4% | 0.27 | -24.9% | 73% | 5.4 | -1.5 | -0.05 | +4.1 | -0.8 | -1.9 | -0.31 | 0.530 | 0.525 |
| LOG4_N0 | 0% | 7.6% | 0.16 | -22.8% | 54% | 5.4 | -3.2 | -0.17 | +6.2 | -1.7 | -6.2 | -0.29 | 0.530 | 0.535 |
| LOG4_N1 | 50% | 8.4% | 0.21 | -23.6% | 66% | 3.5 | -2.4 | -0.11 | +5.3 | -1.4 | -3.1 | -0.50 | 0.680 | 0.700 |
| LOG4_N1 | 0% | 5.7% | -0.01 | -19.9% | 39% | 3.5 | -5.1 | -0.33 | +9.0 | -2.9 | -8.4 | -0.48 | 0.705 | 0.700 |
| LOG4_E0 | 50% | 8.4% | 0.20 | -28.0% | 82% | 5.9 | -2.5 | -0.12 | +0.9 | -2.1 | -2.5 | -0.92 | 0.740 | 0.550 |
| LOG4_E0 | 0% | 5.8% | 0.03 | -27.5% | 71% | 5.9 | -5.1 | -0.29 | +1.4 | -4.3 | -5.5 | -0.92 | 0.770 | 0.550 |
| LOG10_N0 | 50% | 7.6% | 0.15 | -26.8% | 75% | 7.1 | -3.3 | -0.17 | +2.2 | -2.7 | -3.5 | -1.09 | 0.635 | 0.595 |
| LOG10_N0 | 0% | 4.1% | -0.10 | -26.1% | 56% | 7.1 | -6.7 | -0.42 | +2.9 | -5.3 | -8.7 | -1.07 | 0.640 | 0.600 |
| LOG10_N1 | 50% | 6.4% | 0.07 | -25.6% | 70% | 4.6 | -4.4 | -0.25 | +3.3 | -3.6 | -3.9 | -1.37 | 0.595 | 0.570 |
| LOG10_N1 | 0% | 1.8% | -0.32 | -24.3% | 46% | 4.6 | -9.0 | -0.64 | +4.6 | -7.2 | -10.4 | -1.36 | 0.645 | 0.575 |
| LOG10_E0 | 50% | 7.0% | 0.12 | -28.9% | 84% | 5.9 | -3.9 | -0.21 | +0.0 | -3.6 | -2.6 | -2.24 | 0.940 | 0.870 |
| LOG10_E0 | 0% | 3.2% | -0.12 | -28.9% | 76% | 5.9 | -7.7 | -0.44 | +0.0 | -7.1 | -5.3 | -2.22 | 0.920 | 0.850 |
| LGB10_N0 | 50% | 9.5% | 0.27 | -24.2% | 78% | 5.8 | -1.3 | -0.05 | +4.8 | -0.8 | +0.2 | -0.38 | 0.495 | 0.390 |
| LGB10_N0 | 0% | 7.9% | 0.17 | -19.9% | 63% | 5.8 | -2.9 | -0.15 | +9.1 | -1.8 | -0.4 | -0.37 | 0.535 | 0.395 |
| LGB10_N1 | 50% | 9.2% | 0.26 | -22.5% | 71% | 7.5 | -1.7 | -0.06 | +6.4 | -0.9 | -0.4 | -0.35 | 0.520 | 0.505 |
| LGB10_N1 | 0% | 7.2% | 0.12 | -17.0% | 49% | 7.5 | -3.7 | -0.20 | +11.9 | -1.9 | -2.3 | -0.34 | 0.520 | 0.520 |
| LGB10_E0 | 50% | 10.6% | 0.34 | -24.9% | 81% | 9.3 | -0.3 | +0.01 | +4.0 | +0.2 | +0.2 | +0.04 | 0.535 | 0.465 |
| LGB10_E0 | 0% | 10.1% | 0.33 | -21.7% | 68% | 9.3 | -0.7 | +0.01 | +7.2 | +0.2 | -0.4 | +0.05 | 0.585 | 0.465 |
| ORACLE_E | 50% | 25.4% | 1.26 | -15.1% | 75% | 8.5 | +14.6 | +0.93 | +13.8 | +15.2 | +8.3 | +7.70 | - | - |
| ORACLE_E | 0% | 41.3% | 2.53 | -7.2% | 57% | 8.5 | +30.5 | +2.21 | +21.7 | +31.8 | +10.3 | +7.80 | - | - |
| ORACLE_N | 50% | 23.1% | 1.09 | -15.0% | 76% | 8.7 | +12.2 | +0.77 | +13.9 | +12.8 | +8.8 | +6.21 | - | - |
| ORACLE_N | 0% | 36.1% | 2.08 | -8.1% | 59% | 8.7 | +25.3 | +1.76 | +20.9 | +26.5 | +10.3 | +6.27 | - | - |
| ANTI_E | 50% | -3.7% | -0.67 | -29.2% | 64% | 8.5 | -14.5 | -0.99 | -0.3 | -13.5 | -9.2 | -7.68 | - | - |
| ANTI_E | 0% | -16.6% | -2.20 | -42.4% | 36% | 8.5 | -27.4 | -2.52 | -13.5 | -25.0 | -32.0 | -7.74 | - | - |

**2026 holdout (not used for selection).** Always-in: CAGR 7.5%, Sharpe_xs 0.15, maxDD -16.7%, exposure 87%.

| signal | risk-off x | CAGR | Sharpe_xs | maxDD | exposure | switches/yr | dCAGR pp | dSharpe_xs | dMaxDD pp | dCAGR vs static | dMaxDD vs static | NW t vs static | null p Sharpe | null p maxDD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R200 | 50% | -3.0% | -0.65 | -12.9% | 65% | 10.2 | -10.4 | -0.80 | +3.7 | -10.4 | -0.5 | -2.55 | 1.000 | 0.575 |
| R200 | 0% | -12.9% | -2.21 | -10.7% | 43% | 10.2 | -20.3 | -2.36 | +5.9 | -20.0 | -2.6 | -2.53 | 1.000 | 0.630 |
| RBR | 50% | 8.2% | 0.20 | -8.8% | 68% | 4.7 | +0.7 | +0.05 | +7.8 | +0.7 | +4.2 | +0.07 | 0.000 | 0.000 |
| RBR | 0% | 8.1% | 0.20 | -5.5% | 50% | 4.7 | +0.6 | +0.05 | +11.1 | +0.8 | +3.9 | +0.05 | 0.000 | 0.000 |
| RVIX | 50% | 1.1% | -0.39 | -10.0% | 57% | 7.1 | -6.3 | -0.54 | +6.6 | -6.2 | +0.8 | -2.13 | 1.000 | 0.415 |
| RVIX | 0% | -5.6% | -1.86 | -5.3% | 27% | 7.1 | -13.1 | -2.00 | +11.4 | -12.4 | -0.4 | -2.12 | 1.000 | 0.490 |
| RM60 | 50% | 4.6% | -0.09 | -8.4% | 63% | 5.5 | -2.9 | -0.24 | +8.2 | -2.8 | +3.6 | -0.62 | 0.710 | 0.050 |
| RM60 | 0% | 0.9% | -0.72 | -4.2% | 39% | 5.5 | -6.5 | -0.87 | +12.5 | -6.1 | +3.0 | -0.63 | 0.715 | 0.000 |
| VOTE | 50% | 2.7% | -0.24 | -10.0% | 63% | 21.0 | -4.8 | -0.39 | +6.7 | -4.7 | +2.1 | -1.30 | 0.850 | 0.000 |
| VOTE | 0% | -2.6% | -1.31 | -4.0% | 40% | 21.0 | -10.0 | -1.46 | +12.7 | -9.6 | +3.5 | -1.30 | 0.935 | 0.030 |
| LOG4_N0 | 50% | 7.5% | 0.15 | -16.7% | 87% | 0.0 | +0.0 | +0.00 | +0.0 | +0.0 | +0.0 | +0.00 | 1.000 | 1.000 |
| LOG4_N0 | 0% | 7.5% | 0.15 | -16.7% | 87% | 0.0 | +0.0 | +0.00 | +0.0 | +0.0 | +0.0 | +0.00 | 1.000 | 1.000 |
| LOG4_N1 | 50% | 8.8% | 0.22 | -16.4% | 84% | 1.3 | +1.4 | +0.07 | +0.2 | +1.4 | -0.4 | +0.53 | 0.000 | 0.170 |
| LOG4_N1 | 0% | 10.2% | 0.29 | -16.2% | 80% | 1.3 | +2.7 | +0.14 | +0.4 | +2.7 | -0.8 | +0.54 | 0.000 | 0.170 |
| LOG4_E0 | 50% | 7.5% | 0.15 | -16.7% | 87% | 0.0 | +0.0 | +0.00 | +0.0 | +0.0 | +0.0 | +0.00 | 1.000 | 1.000 |
| LOG4_E0 | 0% | 7.5% | 0.15 | -16.7% | 87% | 0.0 | +0.0 | +0.00 | +0.0 | +0.0 | +0.0 | +0.00 | 1.000 | 1.000 |
| LOG10_N0 | 50% | 2.8% | -0.12 | -15.5% | 84% | 2.9 | -4.7 | -0.27 | +1.1 | -4.7 | +0.5 | -0.97 | 1.000 | 0.090 |
| LOG10_N0 | 0% | -1.8% | -0.44 | -14.4% | 80% | 2.9 | -9.3 | -0.59 | +2.2 | -9.3 | +1.0 | -0.97 | 1.000 | 0.090 |
| LOG10_N1 | 50% | 1.6% | -0.23 | -13.9% | 76% | 9.2 | -5.8 | -0.37 | +2.7 | -5.8 | +0.6 | -1.28 | 0.850 | 0.480 |
| LOG10_N1 | 0% | -4.1% | -0.77 | -11.7% | 65% | 9.2 | -11.6 | -0.91 | +5.0 | -11.5 | +0.8 | -1.27 | 0.845 | 0.465 |
| LOG10_E0 | 50% | 3.9% | -0.06 | -14.8% | 81% | 5.5 | -3.5 | -0.21 | +1.8 | -3.6 | +0.8 | -0.84 | 0.820 | 0.230 |
| LOG10_E0 | 0% | 0.4% | -0.33 | -13.1% | 76% | 5.5 | -7.1 | -0.48 | +3.5 | -7.1 | +1.4 | -0.83 | 0.820 | 0.245 |
| LGB10_N0 | 50% | 9.3% | 0.25 | -12.8% | 77% | 8.9 | +1.8 | +0.10 | +3.8 | +1.8 | +1.8 | +0.48 | 0.155 | 0.055 |
| LGB10_N0 | 0% | 10.9% | 0.37 | -9.2% | 66% | 8.9 | +3.4 | +0.22 | +7.4 | +3.4 | +3.5 | +0.48 | 0.160 | 0.035 |
| LGB10_N1 | 50% | 9.5% | 0.27 | -12.1% | 71% | 11.8 | +2.1 | +0.12 | +4.6 | +2.0 | +1.6 | +0.46 | 0.115 | 0.020 |
| LGB10_N1 | 0% | 11.4% | 0.45 | -7.4% | 56% | 11.8 | +3.9 | +0.30 | +9.2 | +4.0 | +3.2 | +0.47 | 0.100 | 0.000 |
| LGB10_E0 | 50% | 10.3% | 0.31 | -13.6% | 73% | 12.0 | +2.8 | +0.16 | +3.0 | +2.8 | +0.4 | +0.75 | 0.090 | 0.415 |
| LGB10_E0 | 0% | 13.0% | 0.51 | -10.6% | 60% | 12.0 | +5.5 | +0.36 | +6.1 | +5.6 | +0.8 | +0.75 | 0.095 | 0.370 |
| ORACLE_E | 50% | 20.6% | 0.88 | -11.2% | 72% | 11.0 | +13.1 | +0.73 | +5.4 | +13.1 | +2.5 | +3.28 | - | - |
| ORACLE_E | 0% | 34.8% | 1.84 | -5.7% | 56% | 11.0 | +27.3 | +1.69 | +11.0 | +27.4 | +5.0 | +3.30 | - | - |
| ORACLE_N | 50% | 20.4% | 0.92 | -10.8% | 66% | 10.5 | +13.0 | +0.77 | +5.8 | +13.0 | +1.7 | +3.53 | - | - |
| ORACLE_N | 0% | 34.4% | 2.06 | -4.8% | 44% | 10.5 | +26.9 | +1.91 | +11.8 | +27.2 | +3.5 | +3.53 | - | - |
| ANTI_E | 50% | -4.5% | -0.76 | -13.9% | 59% | 11.0 | -12.0 | -0.91 | +2.8 | -11.9 | -2.7 | -3.25 | - | - |
| ANTI_E | 0% | -15.6% | -2.57 | -12.6% | 31% | 11.0 | -23.1 | -2.72 | +4.1 | -22.4 | -7.0 | -3.25 | - | - |

**PRE 2021-09..2022-12 (rules only; parameter-free).** Always-in: CAGR -1.8%, Sharpe_xs -0.32, maxDD -26.0%, exposure 90%.

| signal | risk-off x | CAGR | Sharpe_xs | maxDD | exposure | switches/yr | dCAGR pp | dSharpe_xs | dMaxDD pp | dCAGR vs static | dMaxDD vs static | NW t vs static | null p Sharpe | null p maxDD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R200 | 50% | -3.8% | -0.50 | -22.1% | 79% | 3.7 | -2.0 | -0.19 | +3.9 | -3.3 | +0.5 | -0.97 | 0.960 | 0.025 |
| R200 | 0% | -6.1% | -0.71 | -20.6% | 67% | 3.7 | -4.3 | -0.39 | +5.4 | -6.8 | -1.6 | -0.98 | 0.965 | 0.080 |
| RBR | 50% | -4.0% | -0.63 | -23.3% | 70% | 9.9 | -2.3 | -0.31 | +2.7 | -4.4 | -3.2 | -1.27 | 0.845 | 0.590 |
| RBR | 0% | -6.7% | -1.05 | -23.1% | 50% | 9.9 | -4.9 | -0.73 | +2.8 | -8.9 | -9.3 | -1.27 | 0.915 | 0.635 |
| RVIX | 50% | 3.5% | -0.15 | -15.0% | 65% | 9.2 | +5.3 | +0.17 | +11.0 | +2.7 | +3.6 | +0.69 | 0.105 | 0.045 |
| RVIX | 0% | 8.1% | 0.21 | -10.0% | 40% | 9.2 | +9.9 | +0.53 | +16.0 | +5.0 | +0.8 | +0.67 | 0.105 | 0.130 |
| RM60 | 50% | 0.8% | -0.32 | -17.4% | 70% | 7.0 | +2.6 | +0.00 | +8.6 | +0.5 | +2.6 | +0.08 | 0.360 | 0.020 |
| RM60 | 0% | 2.7% | -0.27 | -11.0% | 50% | 7.0 | +4.5 | +0.05 | +15.0 | +0.5 | +2.9 | +0.06 | 0.345 | 0.025 |
| VOTE | 50% | -0.9% | -0.42 | -19.4% | 71% | 22.4 | +0.9 | -0.10 | +6.6 | -1.1 | +0.9 | -0.44 | 0.580 | 0.075 |
| VOTE | 0% | -0.4% | -0.55 | -13.8% | 52% | 22.4 | +1.3 | -0.23 | +12.2 | -2.5 | +0.6 | -0.45 | 0.575 | 0.040 |
| ORACLE_E | 50% | 15.8% | 0.70 | -12.6% | 71% | 8.7 | +17.6 | +1.02 | +13.4 | +15.6 | +7.7 | +4.65 | - | - |
| ORACLE_E | 0% | 35.6% | 2.68 | -5.7% | 52% | 8.7 | +37.3 | +3.00 | +20.3 | +33.5 | +8.9 | +4.75 | - | - |
| ORACLE_N | 50% | 15.2% | 0.67 | -12.6% | 70% | 8.7 | +16.9 | +0.99 | +13.4 | +14.8 | +7.3 | +4.69 | - | - |
| ORACLE_N | 0% | 34.0% | 2.71 | -6.1% | 49% | 8.7 | +35.8 | +3.02 | +19.9 | +31.7 | +7.4 | +4.79 | - | - |
| ANTI_E | 50% | -12.9% | -1.15 | -28.5% | 64% | 8.7 | -11.1 | -0.84 | -2.5 | -13.8 | -10.3 | -4.61 | - | - |
| ANTI_E | 0% | -23.1% | -2.25 | -32.0% | 38% | 8.7 | -21.3 | -1.93 | -6.0 | -26.3 | -21.9 | -4.67 | - | - |

## 8. Exposure scaler on the relative-model top-20 book (XR20, sleeve gating, 50 bps, phase-averaged)

**DEV 2023-25.** Always-in XR20: CAGR 28.9% vs random 11.6% (excess +17.3 pp, NW t 3.49; phase-0 29.8%, t 3.75), Sharpe_xs 1.04, maxDD -29.2%.

| signal | risk-off x | CAGR | Sharpe_xs | maxDD | exposure | dCAGR pp | dSharpe_xs | dMaxDD pp | dCAGR vs static | gated random CAGR | excess vs gated random pp | NW t | null p Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R200 | 50% | 27.0% | 1.08 | -20.6% | 85% | -1.9 | +0.04 | +8.6 | +0.0 | 11.2% | +15.8 | 3.44 | 0.300 |
| R200 | 0% | 24.7% | 1.03 | -17.2% | 77% | -4.2 | -0.01 | +12.1 | -0.3 | 10.5% | +14.2 | 3.17 | 0.480 |
| RBR | 50% | 27.6% | 1.22 | -18.5% | 74% | -1.3 | +0.18 | +10.8 | +3.2 | 14.0% | +13.6 | 3.33 | 0.135 |
| RBR | 0% | 25.7% | 1.31 | -14.3% | 55% | -3.2 | +0.27 | +14.9 | +5.7 | 16.1% | +9.5 | 2.57 | 0.135 |
| RVIX | 50% | 23.5% | 1.06 | -20.5% | 74% | -5.4 | +0.02 | +8.7 | -0.8 | 9.4% | +14.1 | 3.58 | 0.345 |
| RVIX | 0% | 17.7% | 0.88 | -13.1% | 55% | -11.2 | -0.16 | +16.1 | -2.0 | 6.8% | +10.9 | 3.15 | 0.350 |
| RM60 | 50% | 29.2% | 1.23 | -17.4% | 79% | +0.4 | +0.19 | +11.8 | +3.7 | 14.0% | +15.2 | 3.49 | 0.120 |
| RM60 | 0% | 28.9% | 1.32 | -17.2% | 65% | +0.0 | +0.28 | +12.0 | +6.7 | 16.1% | +12.8 | 3.06 | 0.140 |
| VOTE | 50% | 26.9% | 1.17 | -18.8% | 78% | -2.0 | +0.13 | +10.4 | +1.6 | 12.2% | +14.7 | 3.54 | 0.085 |
| VOTE | 0% | 24.4% | 1.29 | -12.1% | 63% | -4.4 | +0.25 | +17.1 | +2.7 | 12.5% | +11.9 | 3.39 | 0.090 |
| LOG4_N0 | 50% | 22.6% | 0.96 | -27.1% | 73% | -6.3 | -0.08 | +2.1 | -1.6 | 10.2% | +12.4 | 3.19 | 0.550 |
| LOG4_N0 | 0% | 16.1% | 0.69 | -25.0% | 54% | -12.8 | -0.35 | +4.2 | -3.4 | 8.4% | +7.7 | 2.20 | 0.560 |
| LOG4_N1 | 50% | 20.1% | 0.88 | -25.6% | 66% | -8.7 | -0.16 | +3.6 | -2.3 | 9.2% | +11.0 | 3.19 | 0.660 |
| LOG4_N1 | 0% | 11.4% | 0.42 | -22.3% | 39% | -17.5 | -0.62 | +6.9 | -4.5 | 6.4% | +5.0 | 1.76 | 0.705 |
| LOG4_E0 | 50% | 23.7% | 0.94 | -29.2% | 82% | -5.2 | -0.10 | -0.0 | -2.6 | 9.1% | +14.5 | 3.34 | 0.585 |
| LOG4_E0 | 0% | 18.4% | 0.74 | -29.2% | 71% | -10.5 | -0.30 | -0.0 | -5.2 | 6.5% | +11.9 | 2.94 | 0.640 |
| LOG10_N0 | 50% | 21.1% | 0.86 | -28.9% | 74% | -7.7 | -0.18 | +0.3 | -3.4 | 8.5% | +12.6 | 3.12 | 0.615 |
| LOG10_N0 | 0% | 13.5% | 0.50 | -28.6% | 56% | -15.4 | -0.54 | +0.7 | -6.6 | 5.3% | +8.2 | 2.23 | 0.645 |
| LOG10_N1 | 50% | 19.0% | 0.79 | -28.0% | 69% | -9.8 | -0.25 | +1.2 | -4.3 | 7.2% | +11.8 | 3.09 | 0.620 |
| LOG10_N1 | 0% | 9.4% | 0.27 | -26.9% | 46% | -19.5 | -0.77 | +2.4 | -8.3 | 2.7% | +6.7 | 1.97 | 0.630 |
| LOG10_E0 | 50% | 23.3% | 0.88 | -29.2% | 84% | -5.6 | -0.16 | +0.0 | -3.6 | 7.7% | +15.6 | 3.44 | 0.790 |
| LOG10_E0 | 0% | 17.8% | 0.65 | -29.2% | 76% | -11.1 | -0.39 | +0.1 | -7.0 | 3.9% | +13.9 | 3.28 | 0.840 |
| LGB10_N0 | 50% | 23.8% | 0.99 | -25.5% | 78% | -5.1 | -0.05 | +3.7 | -1.5 | 10.2% | +13.6 | 3.28 | 0.415 |
| LGB10_N0 | 0% | 18.4% | 0.80 | -21.9% | 63% | -10.5 | -0.24 | +7.3 | -3.3 | 8.5% | +9.9 | 2.63 | 0.435 |
| LGB10_N1 | 50% | 22.8% | 1.00 | -23.7% | 71% | -6.1 | -0.04 | +5.5 | -0.8 | 9.8% | +13.0 | 3.48 | 0.525 |
| LGB10_N1 | 0% | 16.3% | 0.75 | -18.8% | 48% | -12.6 | -0.29 | +10.5 | -1.9 | 7.6% | +8.7 | 2.77 | 0.525 |
| LGB10_E0 | 50% | 26.6% | 1.10 | -25.7% | 80% | -2.3 | +0.06 | +3.5 | +0.6 | 11.2% | +15.3 | 3.45 | 0.440 |
| LGB10_E0 | 0% | 24.0% | 1.08 | -23.0% | 68% | -4.9 | +0.04 | +6.2 | +1.0 | 10.7% | +13.3 | 3.19 | 0.475 |
| ORACLE_E | 50% | 41.5% | 1.85 | -16.3% | 75% | +12.6 | +0.81 | +12.9 | +16.9 | 26.2% | +15.2 | 3.41 | - |
| ORACLE_E | 0% | 54.7% | 2.85 | -8.0% | 57% | +25.9 | +1.81 | +21.3 | +34.5 | 42.2% | +12.5 | 2.83 | - |
| ANTI_E | 50% | 7.3% | 0.13 | -28.8% | 64% | -21.6 | -0.91 | +0.5 | -14.8 | -3.3% | +10.6 | 3.25 | - |
| ANTI_E | 0% | -11.3% | -1.40 | -33.4% | 36% | -40.2 | -2.44 | -4.2 | -26.5 | -16.6% | +5.3 | 2.26 | - |

**2026 holdout.** Always-in XR20: CAGR 13.8% vs random 9.0% (excess +4.8 pp, NW t 0.64; phase-0 12.5%, t 0.87), Sharpe_xs 0.42, maxDD -17.4%.

| signal | risk-off x | CAGR | Sharpe_xs | maxDD | exposure | dCAGR pp | dSharpe_xs | dMaxDD pp | dCAGR vs static | gated random CAGR | excess vs gated random pp | NW t | null p Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R200 | 50% | 1.4% | -0.25 | -13.7% | 65% | -12.4 | -0.67 | +3.7 | -10.7 | -2.1% | +3.5 | 0.66 | 1.000 |
| R200 | 0% | -10.0% | -1.61 | -10.6% | 43% | -23.7 | -2.02 | +6.9 | -20.2 | -12.5% | +2.5 | 0.69 | 1.000 |
| RBR | 50% | 12.3% | 0.44 | -9.4% | 68% | -1.5 | +0.02 | +8.0 | -0.0 | 9.6% | +2.7 | 0.43 | 0.000 |
| RBR | 0% | 10.1% | 0.34 | -6.2% | 50% | -3.7 | -0.07 | +11.3 | -0.7 | 9.2% | +0.9 | 0.15 | 0.000 |
| RVIX | 50% | 5.1% | -0.03 | -10.7% | 57% | -8.7 | -0.44 | +6.7 | -6.3 | 2.0% | +3.1 | 0.69 | 1.000 |
| RVIX | 0% | -3.5% | -1.31 | -5.3% | 27% | -17.3 | -1.72 | +12.1 | -12.2 | -5.3% | +1.7 | 0.64 | 1.000 |
| RM60 | 50% | 9.9% | 0.31 | -8.6% | 63% | -3.8 | -0.11 | +8.8 | -2.0 | 5.7% | +4.2 | 0.71 | 0.680 |
| RM60 | 0% | 5.4% | -0.08 | -5.8% | 39% | -8.4 | -0.49 | +11.6 | -4.4 | 1.6% | +3.8 | 0.75 | 0.705 |
| VOTE | 50% | 7.1% | 0.12 | -10.6% | 63% | -6.6 | -0.30 | +6.8 | -4.8 | 3.7% | +3.4 | 0.63 | 0.855 |
| VOTE | 0% | 0.3% | -0.74 | -4.9% | 40% | -13.5 | -1.16 | +12.5 | -9.6 | -1.9% | +2.2 | 0.59 | 0.900 |
| LOG4_N0 | 50% | 13.8% | 0.42 | -17.4% | 87% | +0.0 | +0.00 | +0.0 | +0.0 | 9.0% | +4.8 | 0.64 | 1.000 |
| LOG4_N0 | 0% | 13.8% | 0.42 | -17.4% | 87% | +0.0 | +0.00 | +0.0 | +0.0 | 9.0% | +4.8 | 0.64 | 1.000 |
| LOG4_N1 | 50% | 14.1% | 0.44 | -17.2% | 84% | +0.3 | +0.02 | +0.2 | +0.5 | 10.2% | +3.9 | 0.54 | 0.000 |
| LOG4_N1 | 0% | 14.4% | 0.45 | -17.0% | 80% | +0.6 | +0.04 | +0.4 | +1.0 | 11.3% | +3.1 | 0.44 | 0.000 |
| LOG4_E0 | 50% | 13.8% | 0.42 | -17.4% | 87% | +0.0 | +0.00 | +0.0 | +0.0 | 9.0% | +4.8 | 0.64 | 1.000 |
| LOG4_E0 | 0% | 13.8% | 0.42 | -17.4% | 87% | +0.0 | +0.00 | +0.0 | +0.0 | 9.0% | +4.8 | 0.64 | 1.000 |
| LOG10_N0 | 50% | 9.3% | 0.24 | -16.4% | 84% | -4.5 | -0.18 | +1.0 | -4.2 | 4.2% | +5.1 | 0.71 | 1.000 |
| LOG10_N0 | 0% | 4.9% | 0.01 | -15.4% | 80% | -8.9 | -0.41 | +2.0 | -8.3 | -0.5% | +5.4 | 0.79 | 1.000 |
| LOG10_N1 | 50% | 7.4% | 0.14 | -15.0% | 76% | -6.4 | -0.27 | +2.4 | -5.5 | 3.3% | +4.1 | 0.62 | 0.825 |
| LOG10_N1 | 0% | 1.2% | -0.26 | -13.0% | 65% | -12.6 | -0.68 | +4.4 | -10.9 | -2.3% | +3.5 | 0.58 | 0.850 |
| LOG10_E0 | 50% | 9.2% | 0.23 | -15.8% | 81% | -4.6 | -0.19 | +1.6 | -4.2 | 5.5% | +3.6 | 0.52 | 0.845 |
| LOG10_E0 | 0% | 4.6% | -0.02 | -14.2% | 76% | -9.1 | -0.43 | +3.2 | -8.3 | 2.1% | +2.6 | 0.40 | 0.860 |
| LGB10_N0 | 50% | 15.7% | 0.54 | -13.5% | 77% | +1.9 | +0.13 | +3.9 | +2.7 | 11.0% | +4.7 | 0.72 | 0.145 |
| LGB10_N0 | 0% | 17.4% | 0.69 | -9.5% | 66% | +3.7 | +0.27 | +7.9 | +5.2 | 12.8% | +4.6 | 0.78 | 0.145 |
| LGB10_N1 | 50% | 15.0% | 0.53 | -12.9% | 71% | +1.2 | +0.11 | +4.5 | +2.4 | 11.4% | +3.6 | 0.60 | 0.130 |
| LGB10_N1 | 0% | 15.9% | 0.67 | -8.2% | 56% | +2.2 | +0.25 | +9.2 | +4.6 | 13.6% | +2.3 | 0.46 | 0.130 |
| LGB10_E0 | 50% | 17.1% | 0.61 | -14.5% | 73% | +3.4 | +0.19 | +2.9 | +4.3 | 12.3% | +4.9 | 0.73 | 0.060 |
| LGB10_E0 | 0% | 20.5% | 0.84 | -11.5% | 60% | +6.8 | +0.43 | +5.9 | +8.8 | 15.4% | +5.2 | 0.81 | 0.060 |
| ORACLE_E | 50% | 26.4% | 1.03 | -11.7% | 72% | +12.6 | +0.61 | +5.7 | +13.7 | 22.5% | +3.9 | 0.50 | - |
| ORACLE_E | 0% | 39.8% | 1.79 | -6.1% | 56% | +26.0 | +1.38 | +11.3 | +28.4 | 37.0% | +2.8 | 0.29 | - |
| ANTI_E | 50% | -0.8% | -0.39 | -14.5% | 59% | -14.6 | -0.81 | +2.9 | -12.3 | -4.0% | +3.2 | 0.71 | - |
| ANTI_E | 0% | -13.9% | -2.10 | -12.8% | 31% | -27.6 | -2.51 | +4.6 | -22.7 | -15.9% | +2.0 | 0.65 | - |

## 9. Cost stress (80 bps) for the main signals (sleeve gating, phase-averaged)

| book | window | signal | risk-off x | CAGR | Sharpe_xs | maxDD | dCAGR pp | dSharpe_xs |
|---|---|---|---|---|---|---|---|---|
| EW | DEV | always-in | - | 6.9% | 0.12 | -30.2% | - | - |
| EW | DEV | R200 | 50% | 6.9% | 0.11 | -23.1% | -0.0 | -0.01 |
| EW | DEV | R200 | 0% | 6.6% | 0.09 | -21.2% | -0.3 | -0.03 |
| EW | DEV | RBR | 50% | 10.1% | 0.32 | -20.4% | +3.3 | +0.20 |
| EW | DEV | RBR | 0% | 13.1% | 0.58 | -13.5% | +6.2 | +0.47 |
| EW | DEV | RM60 | 50% | 9.9% | 0.29 | -18.8% | +3.0 | +0.18 |
| EW | DEV | RM60 | 0% | 12.5% | 0.48 | -14.6% | +5.7 | +0.37 |
| EW | DEV | VOTE | 50% | 8.1% | 0.19 | -21.1% | +1.3 | +0.07 |
| EW | DEV | VOTE | 0% | 9.2% | 0.28 | -13.1% | +2.3 | +0.17 |
| EW | DEV | LGB10_E0 | 50% | 7.1% | 0.12 | -25.9% | +0.3 | +0.01 |
| EW | DEV | LGB10_E0 | 0% | 7.2% | 0.12 | -22.4% | +0.4 | +0.01 |
| EW | HOLD | always-in | - | 3.9% | -0.03 | -17.1% | - | - |
| EW | HOLD | R200 | 50% | -5.4% | -0.84 | -13.4% | -9.3 | -0.81 |
| EW | HOLD | R200 | 0% | -14.3% | -2.39 | -11.7% | -18.2 | -2.36 |
| EW | HOLD | RBR | 50% | 5.3% | -0.01 | -9.1% | +1.5 | +0.02 |
| EW | HOLD | RBR | 0% | 6.0% | 0.00 | -5.6% | +2.1 | +0.03 |
| EW | HOLD | RM60 | 50% | 2.0% | -0.30 | -8.7% | -1.8 | -0.27 |
| EW | HOLD | RM60 | 0% | -0.6% | -0.93 | -4.4% | -4.4 | -0.90 |
| EW | HOLD | VOTE | 50% | 0.2% | -0.45 | -10.3% | -3.7 | -0.41 |
| EW | HOLD | VOTE | 0% | -4.1% | -1.55 | -4.2% | -7.9 | -1.52 |
| EW | HOLD | LGB10_E0 | 50% | 7.2% | 0.13 | -14.0% | +3.3 | +0.16 |
| EW | HOLD | LGB10_E0 | 0% | 10.4% | 0.34 | -10.8% | +6.5 | +0.37 |
| XR20 | DEV | always-in | - | 24.3% | 0.86 | -29.8% | - | - |
| XR20 | DEV | R200 | 50% | 22.8% | 0.89 | -21.2% | -1.4 | +0.03 |
| XR20 | DEV | R200 | 0% | 21.0% | 0.85 | -17.5% | -3.3 | -0.01 |
| XR20 | DEV | RBR | 50% | 23.9% | 1.04 | -19.2% | -0.3 | +0.18 |
| XR20 | DEV | RBR | 0% | 22.9% | 1.14 | -14.6% | -1.3 | +0.28 |
| XR20 | DEV | RM60 | 50% | 25.3% | 1.05 | -17.9% | +1.0 | +0.19 |
| XR20 | DEV | RM60 | 0% | 25.7% | 1.16 | -17.5% | +1.4 | +0.30 |
| XR20 | DEV | VOTE | 50% | 23.0% | 0.98 | -19.6% | -1.2 | +0.12 |
| XR20 | DEV | VOTE | 0% | 21.4% | 1.09 | -12.3% | -2.9 | +0.23 |
| XR20 | DEV | LGB10_E0 | 50% | 22.6% | 0.91 | -26.3% | -1.6 | +0.05 |
| XR20 | DEV | LGB10_E0 | 0% | 20.7% | 0.90 | -23.6% | -3.6 | +0.04 |
| XR20 | HOLD | always-in | - | 10.0% | 0.26 | -17.8% | - | - |
| XR20 | HOLD | R200 | 50% | -1.2% | -0.42 | -14.0% | -11.1 | -0.68 |
| XR20 | HOLD | R200 | 0% | -11.5% | -1.77 | -11.0% | -21.4 | -2.03 |
| XR20 | HOLD | RBR | 50% | 9.3% | 0.25 | -9.6% | -0.6 | -0.01 |
| XR20 | HOLD | RBR | 0% | 8.0% | 0.17 | -6.4% | -2.0 | -0.09 |
| XR20 | HOLD | RM60 | 50% | 7.2% | 0.13 | -8.8% | -2.7 | -0.13 |
| XR20 | HOLD | RM60 | 0% | 3.8% | -0.26 | -6.2% | -6.2 | -0.52 |
| XR20 | HOLD | VOTE | 50% | 4.5% | -0.06 | -10.9% | -5.5 | -0.32 |
| XR20 | HOLD | VOTE | 0% | -1.2% | -0.94 | -5.3% | -11.2 | -1.20 |
| XR20 | HOLD | LGB10_E0 | 50% | 13.8% | 0.45 | -14.8% | +3.9 | +0.20 |
| XR20 | HOLD | LGB10_E0 | 0% | 17.8% | 0.70 | -11.8% | +7.8 | +0.44 |

At 80 bps the gating deltas are almost the same as at 50 bps. Gating removes no trades (sleeves rebalance anyway), and the always-in book pays the same cost per unit of exposure.

## 10. Calendar-year returns (phase-averaged, 50 bps)

| book | year | always-in | RBR x=0 | RBR x=0.5 | RM60 x=0 | R200 x=0 | VOTE x=0 |
|---|---|---|---|---|---|---|---|
| EW | 2021 | 1.0% | 0.9% | 1.0% | -0.0% | 1.0% | 0.6% |
| EW | 2022 | -4.5% | -9.5% | -6.8% | 3.2% | -10.0% | -1.8% |
| EW | 2023 | 37.0% | 39.5% | 38.4% | 30.7% | 28.9% | 33.3% |
| EW | 2024 | 13.3% | 4.2% | 8.8% | 13.7% | 12.1% | 7.2% |
| EW | 2025 | -14.2% | 4.2% | -5.1% | 2.2% | -10.3% | -3.4% |
| EW | 2026 | 5.6% | 6.1% | 6.2% | 0.7% | -10.0% | -1.9% |
| XR20 | 2023 | 52.2% | 44.3% | 48.3% | 39.2% | 39.1% | 42.8% |
| XR20 | 2024 | 40.7% | 21.8% | 31.1% | 39.9% | 38.3% | 25.8% |
| XR20 | 2025 | -2.9% | 10.1% | 3.9% | 8.3% | -2.0% | 5.2% |
| XR20 | 2026 | 10.3% | 7.6% | 9.2% | 4.1% | -7.7% | 0.2% |

(2021 = Sep-Dec only; DEV years end at the DEV exit cutoff; 2026 = Jan 1 - Oct 14.) The breadth gate's DEV gain is concentrated in 2025, the Sep-2024 to Mar-2025 drawdown. It gave back most of it in 2024 and lost in 2022.

## 11. Whipsaw: three implementations of the same signals (risk-off x = 0)

| window | signal | EW sleeve gating dCAGR / dSharpe_xs / dMaxDD (switches/yr) | EW daily overlay 50 bps (flips/yr; switch cost) | N500 index timing 10 bps/side | index null p Sharpe_xs |
|---|---|---|---|---|---|
| PRE | R200 | -4.3 / -0.39 / +5.4 (3.7) | -2.5 / -0.27 / +6.2 (9.2; cost 2.29%/yr) | -6.5 / -0.49 / +1.5 (9.0) | 0.950 |
| PRE | RBR | -4.9 / -0.73 / +2.8 (9.9) | -1.9 / -0.51 / +9.0 (15.1; cost 3.78%/yr) | -2.0 / -0.27 / +6.6 (15.1) | 0.510 |
| PRE | RVIX | +9.9 / +0.53 / +16.0 (9.2) | +2.2 / -0.20 / +8.5 (16.8; cost 4.20%/yr) | +3.8 / +0.24 / +4.2 (16.6) | 0.150 |
| PRE | RM60 | +4.5 / +0.05 / +15.0 (7.0) | -1.7 / -0.50 / +8.9 (15.3; cost 3.81%/yr) | -3.8 / -0.40 / +4.8 (15.1) | 0.710 |
| PRE | VOTE | +1.3 / -0.23 / +12.2 (22.4) | -0.8 / -0.47 / +10.7 (54.8; cost 3.52%/yr) | -2.0 / -0.30 / +6.1 (54.2) | 0.620 |
| DEV | R200 | -1.0 / -0.03 / +10.4 (2.0) | +3.2 / +0.23 / +14.7 (4.0; cost 1.01%/yr) | -2.4 / -0.05 / +7.5 (4.0) | 0.425 |
| DEV | RBR | +4.8 / +0.45 / +16.0 (7.1) | +0.4 / +0.13 / +14.2 (15.4; cost 3.85%/yr) | -8.3 / -0.51 / +4.8 (15.4) | 0.750 |
| DEV | RVIX | -4.5 / -0.27 / +13.1 (6.7) | -11.7 / -0.87 / -0.4 (12.8; cost 3.19%/yr) | -11.1 / -0.78 / +6.8 (12.7) | 0.925 |
| DEV | RM60 | +4.6 / +0.35 / +14.7 (4.6) | -0.0 / +0.04 / +13.1 (7.4; cost 1.85%/yr) | -0.7 / +0.12 / +11.3 (7.3) | 0.055 |
| DEV | VOTE | +1.1 / +0.18 / +17.5 (15.8) | -1.9 / -0.05 / +12.9 (36.5; cost 2.47%/yr) | -5.5 / -0.23 / +8.7 (36.4) | 0.555 |
| DEV | LGB10_E0 | -0.7 / +0.01 / +7.2 (9.3) | -1.5 / -0.05 / +7.3 (26.2; cost 6.55%/yr) | -5.9 / -0.33 / +7.2 (26.0) | 0.525 |
| DEV | LOG4_N1 | -5.1 / -0.33 / +9.0 (3.5) | -8.2 / -0.57 / +4.8 (8.4; cost 2.10%/yr) | -7.6 / -0.45 / +5.9 (8.7) | 0.705 |
| HOLD | R200 | -20.3 / -2.36 / +5.9 (10.2) | -25.9 / -3.22 / +0.8 (19.7; cost 4.92%/yr) | -6.8 / -2.16 / -0.0 (19.2) | 1.000 |
| HOLD | RBR | +0.6 / +0.05 / +11.1 (4.7) | +4.0 / +0.35 / +11.0 (9.2; cost 2.29%/yr) | +15.7 / +0.90 / +9.6 (7.7) | 0.015 |
| HOLD | RVIX | -13.1 / -2.00 / +11.4 (7.1) | -15.7 / -2.27 / +10.1 (14.4; cost 3.61%/yr) | -1.0 / -2.12 / +4.8 (14.1) | 1.000 |
| HOLD | RM60 | -6.5 / -0.87 / +12.5 (5.5) | -7.6 / -0.99 / +11.8 (17.0; cost 4.26%/yr) | +9.2 / -0.08 / +10.2 (16.7) | 0.620 |
| HOLD | VOTE | -10.0 / -1.46 / +12.7 (21.0) | -11.6 / -1.75 / +12.1 (53.8; cost 3.61%/yr) | +4.0 / -1.34 / +9.0 (51.3) | 0.985 |
| HOLD | LGB10_E0 | +5.5 / +0.36 / +6.1 (12.0) | -0.9 / -0.06 / +3.9 (32.8; cost 8.20%/yr) | -0.3 / -0.45 / +1.5 (32.0) | 0.750 |
| HOLD | LOG4_N1 | +2.7 / +0.14 / +0.4 (1.3) | +4.6 / +0.23 / +0.0 (2.6; cost 0.66%/yr) | +4.7 / +0.29 / +0.9 (1.3) | 0.105 |

Buy-and-hold Nifty 500 (price index, no dividends, which flatters timing): CAGR PRE 4.4%, DEV 15.6%, 2026 -9.7%; Sharpe_xs -0.02 / 0.65 / -0.90; maxDD -18.7% / -20.4% / -14.3%.

Noisy-oracle break-even (EW book, risk-off 0, 50 draws per level). The state is the true sign of the EW 20-day return, flipped in random 10-day blocks with probability 1 - accuracy:

| block accuracy | DEV sleeve gating dCAGR / dSharpe_xs / dMaxDD (P[dCAGR>0]) | DEV daily overlay 50 bps | 2026 sleeve gating | 2026 daily overlay |
|---|---|---|---|---|
| 0.50 | -2.1 / -0.05 / +13.6 (22%) | -10.4 / -0.70 / +5.0 (2%) | +0.2 / -0.11 / +8.2 (44%) | -8.5 / -0.76 / +6.0 (26%) |
| 0.55 | +0.4 / +0.15 / +14.2 (48%) | -7.2 / -0.47 / +6.4 (16%) | +4.4 / +0.27 / +8.8 (68%) | -6.1 / -0.54 / +6.0 (28%) |
| 0.60 | +4.3 / +0.48 / +15.8 (90%) | -4.0 / -0.23 / +9.0 (24%) | +6.3 / +0.41 / +8.4 (76%) | -5.9 / -0.51 / +6.1 (30%) |
| 0.65 | +7.0 / +0.71 / +16.2 (100%) | -0.9 / +0.00 / +8.6 (42%) | +8.3 / +0.58 / +8.9 (80%) | -0.8 / -0.13 / +6.9 (52%) |
| 0.70 | +10.7 / +1.00 / +18.5 (100%) | +3.6 / +0.30 / +12.4 (72%) | +12.5 / +0.95 / +9.9 (98%) | +2.7 / +0.11 / +6.9 (58%) |
| 0.80 | +16.5 / +1.38 / +19.8 (100%) | +11.7 / +0.82 / +14.5 (98%) | +17.4 / +1.20 / +10.4 (98%) | +7.6 / +0.41 / +7.4 (80%) |
| 0.90 | +23.8 / +1.81 / +20.9 (100%) | +19.1 / +1.22 / +17.0 (100%) | +23.7 / +1.58 / +10.5 (100%) | +13.5 / +0.71 / +7.0 (94%) |
| 1.00 | +30.9 / +2.19 / +21.5 (100%) | +28.7 / +1.72 / +19.4 (100%) | +29.9 / +1.89 / +11.2 (100%) | +21.2 / +1.08 / +7.3 (100%) |

Compare the real signals' DEV accuracy vs E0 in section 6. Only RBR (0.622) beats always-on (0.603). The walk-forward models score 0.40-0.54. Even a coin flip cuts maxDD by about 13 pp, because it is out of the market half the time.

## 12. Is the relative edge regime-dependent? (XR20 vs random, per signal date, all 5 phases)

| window | signal dates | XR20 mean net/trade | random | EW universe | excess (NW t) | excess if mkt up | excess if mkt down | slope of excess on mkt (t) | XR20 beta to EW |
|---|---|---|---|---|---|---|---|---|---|
| DEV_50 | 723 | 2.31% | 1.06% | 1.00% | 1.24% (t 4.12) | 1.21% | 1.28% | +0.022 (t 0.39) | 1.03 (t 19.3) |
| HOLD_50 | 173 | 1.30% | 0.94% | 0.81% | 0.36% (t 0.79) | 0.13% | 0.67% | -0.127 (t -1.52) | 0.89 (t 10.4) |

Excess per 20-day trade, risk-on vs risk-off dates (DEV, 50 bps):

| signal | on share | excess on | excess off | on-off pp (t) | EW universe on-off pp (t) | 2026 excess on-off pp (t) |
|---|---|---|---|---|---|---|
| R200 | 83% | 1.25% | 1.21% | +0.04 (+0.06) | -0.27 (-0.12) | +0.31 (+0.35) |
| RBR | 60% | 1.12% | 1.42% | -0.29 (-0.62) | +1.95 (+1.53) | -0.57 (-0.57) |
| RVIX | 59% | 1.40% | 1.01% | +0.39 (+0.76) | -0.97 (-0.76) | +0.23 (+0.27) |
| RM60 | 70% | 1.28% | 1.15% | +0.14 (+0.23) | +1.97 (+1.19) | +0.68 (+0.78) |
| VOTE | 83% | 1.21% | 1.38% | -0.17 (-0.23) | +1.22 (+0.57) | +0.50 (+0.49) |
| LOG4_N0 | 58% | 1.02% | 1.54% | -0.52 (-1.02) | -0.39 (-0.29) | n/a |
| LOG4_N1 | 42% | 0.96% | 1.45% | -0.49 (-0.89) | -0.74 (-0.52) | -1.68 (-3.01) |
| LOG4_E0 | 76% | 1.20% | 1.39% | -0.19 (-0.39) | -1.70 (-1.18) | n/a |
| LOG10_N0 | 61% | 1.07% | 1.50% | -0.42 (-0.77) | -1.59 (-1.27) | +2.13 (+2.16) |
| LOG10_N1 | 50% | 1.09% | 1.39% | -0.30 (-0.53) | -2.11 (-1.66) | +0.33 (+0.34) |
| LOG10_E0 | 81% | 1.32% | 0.91% | +0.41 (+0.69) | -3.53 (-3.38) | -0.99 (-0.81) |
| LGB10_N0 | 68% | 1.10% | 1.53% | -0.43 (-0.90) | -0.58 (-0.45) | +0.44 (+0.36) |
| LGB10_N1 | 52% | 1.25% | 1.23% | +0.02 (+0.05) | -0.51 (-0.42) | -0.28 (-0.24) |
| LGB10_E0 | 73% | 1.32% | 1.03% | +0.28 (+0.68) | +0.12 (+0.11) | +0.61 (+0.56) |

## 13. Parameter-sensitivity map (EW book, sleeve gating, risk-off 0, 50 bps, phase-averaged)

The 'event rate' of a timing rule is its risk-on share. The table shows how it, and the outcome, move with the threshold.

| rule | PRE on | PRE dCAGR | PRE dSh_xs | PRE dMaxDD | DEV on | DEV dCAGR | DEV dSh_xs | DEV dMaxDD | 2026 on | 2026 dCAGR | 2026 dSh_xs | 2026 dMaxDD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| breadth50>0.35 | 76% | -5.2 | -0.51 | +0.2 | 78% | +0.1 | +0.04 | +10.4 | 72% | -13.4 | -1.10 | +6.4 |
| breadth50>0.40 | 72% | -6.5 | -0.64 | -0.5 | 71% | +1.7 | +0.16 | +13.4 | 68% | -10.3 | -0.87 | +8.6 |
| breadth50>0.45 | 66% | -6.8 | -0.73 | -0.5 | 65% | +3.4 | +0.30 | +14.9 | 59% | -2.4 | -0.21 | +10.9 |
| breadth50>0.50 | 56% | -4.9 | -0.73 | +2.8 | 58% | +4.8 | +0.45 | +16.0 | 51% | +0.6 | +0.05 | +11.1 |
| breadth50>0.55 | 48% | -4.9 | -0.84 | +4.8 | 53% | +4.9 | +0.51 | +17.2 | 43% | +2.9 | +0.29 | +11.3 |
| breadth50>0.60 | 37% | -3.9 | -0.91 | +7.8 | 47% | +6.9 | +0.78 | +21.1 | 36% | +2.1 | +0.25 | +11.6 |
| breadth50>0.65 | 28% | -1.4 | -0.83 | +12.9 | 39% | +8.0 | +1.02 | +23.0 | 28% | +0.6 | +0.10 | +11.6 |
| breadth_hyst_0.55/0.45 | 57% | -6.0 | -0.78 | +1.4 | 57% | +6.2 | +0.52 | +14.9 | 56% | -1.9 | -0.18 | +11.1 |
| mom60>-0.04 | 81% | -5.0 | -0.43 | +3.8 | 83% | +3.8 | +0.27 | +14.4 | 75% | -17.4 | -1.35 | +3.9 |
| mom60>-0.02 | 72% | -0.9 | -0.27 | +9.2 | 77% | +5.1 | +0.36 | +14.7 | 60% | -14.4 | -1.42 | +8.4 |
| mom60>+0.00 | 58% | +4.5 | +0.05 | +15.0 | 71% | +4.6 | +0.35 | +14.7 | 40% | -6.5 | -0.87 | +12.5 |
| mom60>+0.02 | 49% | +6.7 | +0.23 | +15.8 | 63% | +4.6 | +0.37 | +14.7 | 29% | -6.9 | -1.14 | +13.3 |
| mom60>+0.04 | 40% | +6.5 | +0.20 | +15.9 | 50% | +2.5 | +0.30 | +14.7 | 18% | -4.3 | -0.87 | +14.3 |
| dma200>-0.04 | 83% | -3.1 | -0.26 | +5.0 | 92% | +0.8 | +0.07 | +9.2 | 86% | -15.6 | -1.09 | +3.5 |
| dma200>-0.02 | 79% | -5.4 | -0.42 | +4.1 | 88% | +0.9 | +0.08 | +12.0 | 69% | -18.9 | -1.60 | +4.5 |
| dma200>+0.00 | 76% | -4.3 | -0.39 | +5.4 | 83% | -1.0 | -0.03 | +10.4 | 44% | -20.3 | -2.36 | +5.9 |
| dma200>+0.02 | 66% | -4.3 | -0.48 | +7.0 | 76% | +0.0 | +0.04 | +11.5 | 12% | -7.4 | -2.25 | +13.0 |
| dma200>+0.04 | 54% | -1.6 | -0.40 | +11.3 | 61% | -0.7 | +0.01 | +11.3 | 3% | -4.1 | -1.87 | +14.2 |
| dma200_hyst_+1%/-1% | 74% | -7.7 | -0.60 | +2.0 | 83% | -1.7 | -0.07 | +9.1 | 43% | -20.2 | -2.23 | +5.8 |
| vix_rel<-0.20 | 13% | +9.8 | +0.87 | +22.8 | 23% | -2.6 | +0.10 | +21.0 | 3% | -4.1 | -1.87 | +14.2 |
| vix_rel<-0.10 | 24% | +9.2 | +0.54 | +21.2 | 44% | -2.2 | -0.01 | +17.6 | 7% | -5.2 | -1.58 | +13.5 |
| vix_rel<+0.00 | 48% | +9.9 | +0.53 | +16.0 | 60% | -4.5 | -0.27 | +13.1 | 31% | -13.1 | -2.00 | +11.4 |
| vix_rel<+0.10 | 68% | +3.3 | +0.02 | +11.4 | 76% | -4.9 | -0.29 | +4.5 | 51% | -16.6 | -1.90 | +8.2 |
| vix_rel<+0.20 | 81% | -1.6 | -0.25 | +2.4 | 87% | -3.2 | -0.17 | +1.0 | 63% | -19.7 | -1.82 | +5.1 |

Same grid on the XR20 book (risk-off 0):

| rule | DEV dCAGR | DEV dSh_xs | DEV dMaxDD | 2026 dCAGR | 2026 dSh_xs | 2026 dMaxDD |
|---|---|---|---|---|---|---|
| breadth50>0.35 | -3.7 | +0.04 | +11.3 | -17.1 | -1.04 | +6.9 |
| breadth50>0.40 | -2.4 | +0.16 | +12.2 | -13.9 | -0.83 | +9.0 |
| breadth50>0.45 | -1.7 | +0.25 | +13.8 | -6.3 | -0.28 | +10.7 |
| breadth50>0.50 | -3.2 | +0.27 | +14.9 | -3.7 | -0.07 | +11.3 |
| breadth50>0.55 | -4.1 | +0.30 | +17.3 | -1.1 | +0.16 | +11.5 |
| breadth50>0.60 | -4.0 | +0.45 | +20.9 | -1.9 | +0.14 | +11.7 |
| breadth50>0.65 | -4.3 | +0.58 | +22.0 | -2.3 | +0.14 | +12.0 |
| breadth_hyst_0.55/0.45 | -1.7 | +0.30 | +13.9 | -5.3 | -0.20 | +10.8 |
| mom60>-0.04 | +1.1 | +0.25 | +12.0 | -17.2 | -0.98 | +4.1 |
| mom60>-0.02 | +1.7 | +0.33 | +12.1 | -15.8 | -1.06 | +8.9 |
| mom60>+0.00 | +0.0 | +0.28 | +12.0 | -8.4 | -0.49 | +11.6 |
| mom60>+0.02 | -2.5 | +0.20 | +12.0 | -9.3 | -0.66 | +12.9 |
| mom60>+0.04 | -6.8 | +0.07 | +12.0 | -6.1 | -0.16 | +15.0 |
| dma200>-0.04 | -1.4 | +0.07 | +9.6 | -15.0 | -0.78 | +3.3 |
| dma200>-0.02 | -2.0 | +0.06 | +11.8 | -18.0 | -1.08 | +4.6 |
| dma200>+0.00 | -4.2 | -0.01 | +12.1 | -23.7 | -2.02 | +6.9 |
| dma200>+0.02 | -3.3 | +0.07 | +12.1 | -13.0 | -1.98 | +13.9 |
| dma200>+0.04 | -6.5 | -0.05 | +12.0 | -9.9 | -1.73 | +15.5 |
| dma200_hyst_+1%/-1% | -4.7 | -0.04 | +11.8 | -24.6 | -2.03 | +6.3 |
| vix_rel<-0.20 | -14.9 | +0.30 | +24.0 | -9.9 | -1.73 | +15.5 |
| vix_rel<-0.10 | -12.1 | +0.06 | +21.8 | -11.0 | -1.52 | +14.5 |
| vix_rel<+0.00 | -11.2 | -0.16 | +16.1 | -17.3 | -1.72 | +12.1 |
| vix_rel<+0.10 | -8.6 | -0.16 | +5.5 | -18.4 | -1.46 | +8.7 |
| vix_rel<+0.20 | -5.3 | -0.09 | +1.0 | -19.7 | -1.30 | +4.7 |

Reading the map. Breadth is a broad DEV plateau: every threshold from 0.45 to 0.65 is positive and gets better as it tightens. It is negative at every threshold in PRE, and in 2026 it is negative below 0.50. The 200-dma rule is about 0 on DEV and strongly negative in 2026 at every band, hysteresis included. mom60 is positive on DEV at every threshold and negative in 2026 at every threshold. VIX is the mirror image: positive in PRE, negative in DEV and 2026. Each family is stable inside a window and unstable across windows. The cliff is the window, not the parameter, which is what a regime-dependent (non-stationary) timing relationship looks like.

## 14. Risk-based exposure: volatility targeting (one variant)

| book | window | bps | always-in CAGR | VOLT CAGR | always-in Sh_xs | VOLT Sh_xs | always-in maxDD | VOLT maxDD | static-mix maxDD | exposure | switches/yr | null p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EW | PRE | 50 | -1.8% | -1.3% | -0.32 | -0.40 | -26.0% | -23.1% | -21.9% | 77% | 32.8 | 0.690 |
| EW | PRE | 80 | -5.2% | -4.2% | -0.50 | -0.60 | -27.7% | -24.5% | -23.3% | 77% | 32.8 | - |
| EW | DEV | 50 | 10.8% | 8.3% | 0.32 | 0.19 | -28.9% | -25.9% | -25.7% | 82% | 25.1 | 0.820 |
| EW | DEV | 80 | 6.9% | 4.8% | 0.12 | -0.02 | -30.2% | -27.0% | -26.9% | 82% | 25.1 | - |
| EW | HOLD | 50 | 7.5% | 2.7% | 0.15 | -0.21 | -16.7% | -10.4% | -12.4% | 65% | 35.9 | 1.000 |
| EW | HOLD | 80 | 3.9% | 0.1% | -0.03 | -0.41 | -17.1% | -10.6% | -12.7% | 65% | 35.9 | - |
| XR20 | DEV | 50 | 28.9% | 24.3% | 1.04 | 0.95 | -29.2% | -26.0% | -26.1% | 82% | 25.1 | 0.685 |
| XR20 | DEV | 80 | 24.3% | 20.3% | 0.86 | 0.77 | -29.8% | -26.7% | -26.7% | 82% | 25.1 | - |
| XR20 | HOLD | 50 | 13.8% | 8.7% | 0.42 | 0.22 | -17.4% | -10.9% | -13.1% | 65% | 35.9 | 1.000 |
| XR20 | HOLD | 80 | 10.0% | 5.9% | 0.26 | 0.04 | -17.8% | -11.2% | -13.4% | 65% | 35.9 | - |

## 15. DEV selection, holdout and multiple testing

* **Pre-declared selection criterion:** the largest phase-averaged DEV gain in Sharpe_xs on the EW book under sleeve gating at 50 bps. The EW book is the purest test of market timing; static de-risking leaves Sharpe_xs unchanged, so this gain is also the gain over a static mix.

| DEV rank: signal | risk-off x | EW DEV dSharpe_xs | EW DEV dCAGR | null p (single test) | EW 2026 dSh_xs / dCAGR | EW PRE dSh_xs / dCAGR | XR20 DEV | XR20 2026 |
|---|---|---|---|---|---|---|---|---|
| RBR | 0% | +0.45 | +4.8 | 0.085 | +0.05 / +0.6 | -0.73 / -4.9 | +0.27 / -3.2 | -0.07 / -3.7 |
| RM60 | 0% | +0.35 | +4.6 | 0.100 | -0.87 / -6.5 | +0.05 / +4.5 | +0.28 / +0.0 | -0.49 / -8.4 |
| RBR | 50% | +0.21 | +2.6 | 0.090 | +0.05 / +0.7 | -0.31 / -2.3 | +0.18 / -1.3 | +0.02 / -1.5 |
| VOTE | 0% | +0.18 | +1.1 | 0.170 | -1.46 / -10.0 | -0.23 / +1.3 | +0.25 / -4.4 | -1.16 / -13.5 |
| RM60 | 50% | +0.18 | +2.5 | 0.095 | -0.24 / -2.9 | +0.00 / +2.6 | +0.19 / +0.4 | -0.11 / -3.8 |
| VOTE | 50% | +0.08 | +0.7 | 0.180 | -0.39 / -4.8 | -0.10 / +0.9 | +0.13 / -2.0 | -0.30 / -6.6 |

* **Variants tried.** 14 primary timing signals (5 rules + 9 walk-forward models) x 2 risk-off levels = 28. Sensitivity grid: 20 new rule thresholds/hysteresis x 2 = 40. Vol target: 1. Total **69 distinct timing variants** (signal x exposure map). Applied as 222 book-level DEV specifications at base cost: sleeve gating on EW and XR20 for all variants, daily overlay on EW and XR20, and index timing for the 28 primary variants. Also 22 single-feature correlation tests, 1 XR_neu walk-forward model, 9 walk-forward timing models, and canaries plus noisy oracles (diagnostics, not counted). Costs (50/80 bps; 10/0 bps for the index) and phases are sensitivities, not new specifications.
* **Multiple testing.** The best DEV circular-shift p-value among the 28 primary EW variants is 0.085. Bonferroni over 28 gives about 1.0 (one-sided 5% needs p < 0.0018). Nothing survives, even before counting the other 194 specifications. The NW t of the best gate's daily return over the static mix is +1.26.
* **Holdout honesty.** 2026 was never used for any choice. The rules have no fitted parameters. The 0.5 probability threshold and the C/depth settings of the models were fixed before the first run and never tuned. PRE is pre-DEV data used only for the rules. The 2026 holdout is lightly contaminated, because round-1 reports showed 2026 market levels.

## 16. Candidate scorecard (pros / cons / failure modes)

| candidate | verdict | pros | cons / failure mode |
|---|---|---|---|
| Absolute timing labels N0/N1/E0 (date-level) | reject as stock labels; diagnostic only | Clean, executable, NaN-safe; base rates 51-75% by year | ~37 independent obs in DEV; persistent (33-44% of months all-0/1); relationship flips sign across windows |
| Walk-forward timing models (LOG4/LOG10/LGB10 x N0/N1/E0) | reject | PIT, embargoed, few parameters | DEV AUC 0.39-0.47 (anti-predictive); coefficients flip sign; LOG4 never risk-off in 2026; 2026 results scattered (LGB10 + a few pp, LOG10 -5 to -12 pp) |
| R200 (N500 > 200dma) | reject | Low turnover (2-4 switches/yr gated); cuts DEV maxDD 10 pp | No DEV return gain; -20 pp (EW) / -24 pp (XR20) CAGR in 2026; negative in PRE; whipsaw at the turn |
| RBR (breadth50 > 0.5) | weak (only as optional drawdown insurance at 50% risk-off) | DEV-best; broad DEV threshold plateau; positive Sharpe_xs in 2026 on EW; maxDD -29% -> -13% on DEV | null p 0.085 single-test (fails Bonferroni); DEV gain = one episode (2025); loses in PRE at every threshold (null p 0.915); 2026 beats its random-timing null (p<0.005) but only breaks even vs always-in (EW +0.6 pp, XR20 -3.7 pp) |
| RM60 (60d momentum > 0) | reject | Positive on DEV at all thresholds; index-timing null p 0.055 on DEV | -6.5 pp (EW) / -8.4 pp (XR20) CAGR in 2026 at x=0; mixed in PRE |
| RVIX (VIX < median) | reject | Helped in PRE | Anti-predictive DEV and 2026 (high VIX precedes rebounds) |
| VOTE (graded) | reject | Lowest maxDD on DEV (-11.5%) | 36 switches/yr; -10 pp CAGR in 2026; negative PRE Sharpe |
| VOLT (vol target) | reject | Risk-based, no direction forecast | DEV Sharpe_xs -0.13 (null p 0.82), 2026 -0.36; sells after vol spikes that mean-revert |
| XR20 always-in (reference relative book) | keep (R2_rel's call) | Selection edge regime-independent (excess +1.2%/trade in up and down markets) | Full beta (1.03 to EW); maxDD -29% on DEV - risk must be set by fixed exposure policy, not timing |

## 17. Lab notes / issues found

* `Sim.run`'s `sharpe` is not cash-adjusted, so any book holding cash looks better. A static 55%/45% EW/cash mix lifts the DEV Sharpe from 0.67 to 0.91 with no skill. Compare de-risked books on Sharpe in excess of cash, or against a static mix with the same exposure.
* The EW-universe target drops rows whose 20d window fails `fw.ok` (suspension, label_block). Mean coverage is 99.84%, so the survivorship effect is negligible here. Sleeves that have not started yet hold un-yielding cash for the first 15 days of a window (minor; it affects every variant equally).
* Nifty 500 is a price index while stock series are dividend-adjusted. In 2026 the EW universe's mean 20d return was +1.3% while Nifty 500's was -0.5%, and the N0 vs E0 base rates diverge (51% vs 65%). A timer trained on the index target can de-risk an EW/small-cap book at the wrong time. Use E0 for EW books.
* No leakage found: the date-level features are constant per date, the targets start at open g+1, and the model folds use a 22-day embargo. The foresight canaries behave as expected (oracle +31 pp DEV CAGR, anti-oracle -27 pp).

Files (all in this directory): `common.py` (PathSim, compose, HAC helpers), `s1_dateset.py`, `s2_timing.py`, `s3_xrneu.py`, `s4a_paths.py`, `s4b_eval.py`, `s4c_overlay.py`, `s4d_conditional.py`, `s5_sensitivity.py`, `s6_voltarget.py`, `s7_report.py` (this report), `s8_summary.py` (results.json 'summary'). Data: `dateset.parquet`, `timing_signals.parquet` (rule states and OOS probabilities per date), `xrneu.npz` (score, label), `paths_cache.pkl`, `gating_results.pkl`, `gating_null.pkl`, `overlay_results.pkl`, `sensitivity.pkl`, `gating_daily.npz` (phase-0 daily returns), `results.json`.
