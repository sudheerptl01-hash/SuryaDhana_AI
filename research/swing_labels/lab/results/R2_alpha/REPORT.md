# R2_alpha — Alpha source & ensemble (lab v2)

Agent R2_alpha, round 2. Lab v2 only: no sector data, ETFs excluded, `elig_base` as rebuilt. U = `elig_base`.
Entry is open[t+1] and labels are NaN where `fw.ok(h)` fails. Filters choose rows and never change label values.
Models use `walk_forward2` with yearly expanding folds 2023-2026, an embargo of h+2 = 22, `date_step` 2, `n_jobs` 2,
default LightGBM, and the 52 point-in-time features. Learnability uses per-date cross-sectional IC and AUC with
non-overlapping t, the same calculation as `L.xs_metrics`. Investability uses `L.Sim` with a horizon-matched
5-seed random baseline on the same mask (the same maths as `S.compare`) at 50 and 80 bps.
DEV = 2023-01-01..2025-12-31. HOLDOUT = 2026-01-01..2026-10-14, reported only and never used to choose.

## 0. Verdict

1. **The ensemble does not add alpha. It adds a regime bet.** Equal-weight rank averaging of XR_neu (relative), A2 barrier (absolute) and TSX trend-scan (market-excess) won the pre-declared DEV selection. Its DEV phase-averaged excess vs random was +15.4%/yr (NW t +4.37) against +15.2%/yr (t +3.81) for XR alone. That higher t comes from a smoother excess, not more return. The paired DEV difference ENS3 − XR is +0.1%/yr (t +0.06). **In the 2026 holdout the selected ensemble fails**: -7.0%/yr vs random (t -0.80), with every one of the 5 calendar phases negative and every one of the 8 K x step cells negative. XR alone made +3.3%/yr (t +0.44). Paired 2026 difference: -10.3%/yr (t -1.55).
2. **Why: absolute and market-excess targets teach the model regime-conditional factor tilts.** In the BAR model, market/regime features carry 61%→86% of the gain importance across folds. In TSX they carry 29%→57%. In XR they carry 13%→19%. In 2026 the BAR/TSX/ensemble top-20 rotated into large, liquid, low-vol names. ENS3 picks moved to a vol_20 percentile of 0.38 (DEV 0.62), idio-vol 0.26 and turnover 0.83. That was exactly the wrong side of 2026: low-vol LS -18.9%/yr, small-minus-big +5.6%/yr. Their picks still had positive factor-neutral skill (realised XR percentile 0.517 vs 0.539 in DEV), so the losses came from the tilt. Removing the 10 market features from BAR/TSX/ENS3 cost DEV (-10.9%, -3.4%, -3.8%/yr). It added +13.9%, +15.4% and +13.5%/yr in 2026. The regime tilt paid in every DEV year for BAR and ENS3 (2 of 3 for TSX) and lost in 2026: it is a market-timing bet hidden inside a stock-selection score.
3. **Feature ablation (XR_neu model).** Delivery data is the only group whose removal significantly lowers IC in both windows: ΔIC -0.0064 DEV (NW t -4.99, non-overlap t -2.44) and -0.0135 in 2026 (NW t -3.68, non-overlap t -2.85). **NSE delivery data adds value**, about 10-25% of the model's IC, but its book-level effect is -2.1%/yr (t -1.19) and not individually significant. Momentum, technicals, xs-ranks and volume are redundant for IC (|ΔIC| ≤ 0.002 in DEV). Momentum still matters for the top tail: dropping it costs the top-20 book -3.2%/yr in DEV (t -1.70) and -4.4% in 2026, the largest book-level loss of any group. Market/regime features add nothing significant in DEV (ΔIC -0.0033) and removing them raised 2026 IC by +0.0279. XR's importance ranking is stable across folds (Spearman 0.90-0.97).
4. **Factor attribution: the long edge is not just low-vol or reversal.** For XR's K20 book the DEV excess is +15.2%/yr. After size, momentum, 5d reversal, low-vol, low-beta and EW-market factors built from the same universe with the same Sim, alpha is +14.1%/yr (NW t +3.33, R² 0.10). The book loads **negatively** on low-vol (t -3.36) and only weakly on reversal (t +1.19). Adding low-idio-vol and trend leaves alpha +12.6% (t +3.15). A static 7-factor composite with the model's own DEV loadings reproduces XR's IC (0.059 vs 0.060) but only through the bottom tail (AUC_bottom 0.561, AUC_top 0.500). Its top-20 book earns +2.0%/yr (t +0.29). **The avoid side is largely a linear factor effect (high idio-vol / lottery names). The long side's edge is model-specific.**
5. **Practical consequence.** Factor-neutralising a score (per-date residual on 7 characteristic ranks) keeps most of the long edge in DEV (XR_FN +12.9%/yr, t +3.22). It makes the avoid overlay robust: DEV t +5.55/+7.70/+8.10 and 2026 +2.3% (t +2.93), +2.2% (t +3.30), +2.2% (t +3.70) for XR/ENS3/TSX. The raw-score avoid overlays had 2026 t of 0.4-0.8. DEV alone already prefers the FN avoid screen (higher t). It does **not** prefer FN for the long book. The long-book FN improvement in 2026 is holdout-informed and must be treated as a pre-registered hypothesis, not a result.
6. **Recommendation for the label stack.** Keep the selection label XR_neu (relative, factor-neutral). Do **not** ensemble it with absolute (barrier) or market-excess (trend-scan) models. Keep regime/market features out of the stock-selection score, or at least size their contribution explicitly in the regime layer. Use a factor-neutralised score for the AVOID screen. Delivery features stay in. Verdict on my candidates: XR_all *promising* (as R2_rel found), ENS3 *reject* (fails holdout), BAR/TSX as alpha sources *reject* for the long book and *weak* as avoid inputs, FN avoid overlay *promising*.
7. **Variants:** 12 walk-forward models, 11 derived scores (ensembles/decompositions), 102 distinct DEV strategy specs at 50 bps, 10 label variants screened on event rates, and 7 formal selection candidates. One-sided 5% Bonferroni hurdle: t = 3.30 for this agent, 3.93 programme-wide (~1190 specs).

## 1. Labels, models, checks

| id | family | exact definition (h = 20; r20 = open[t+1] → close[t+20], adjusted; NaN unless fw.ok(20)) | model |
|---|---|---|---|
| XR (XR_neu) | relative, factor-neutral | per date over V = U ∩ finite(r20): winsorise r20 at 1/99%, OLS on [1, 0.5·clip(beta_60,0,3)+0.5, vol_20, log_turn20], residual → per-date pct rank; target pct−0.5 | `walk_forward2` regression |
| BAR (A2) | absolute, path | `L.barrier_labels(h=20, pt=3.0·ATR, sl=1.5·ATR, tau=50bp)`, stop checked first, gap fills at open; target 1{BAR=+1} | binary |
| TSX (TSX_T5) | market-excess trend scan | y_0=0, y_k = log(close[t+k]/open[t+1]) − log(N500 close[date t+k]/N500 open[date t+1]); OLS-slope t for L=5..20 (var floor 1e-6); L* = argmax abs(t); label sign(t*) if abs(t*) ≥ 5 else 0 | multiclass (P(+1)−P(−1)) |
| ENS3 / ENS_XB / ENS_XT / ENS_BT | ensemble | equal-weight mean of per-date percentile ranks of the OOS scores (no fitted weights) | — |
| *_FN | factor-neutral score | per date: residual of the score's pct rank on pct ranks of [log_turn20, mom_12_1, mom_5, vol_20, beta_60, idio_vol_60, dist_sma200] | — |
| *_FC | static factor composite | Σ w_k·rank_k with w = DEV-average of the per-date projection coefficients (a 'boring' linear factor tilt) | — |

Checks. My XR_neu pct equals R2_rel's `pct_neu` on 1,289,713 rows (max abs diff 3.0e-08). My BAR equals R2_dual's BAR (agreement 1.0000, 0 NaN-pattern mismatches). My copy of `walk_forward2` (it adds per-fold gain importance) is bit-identical to `L.walk_forward2` (max abs diff 0.0). The XR_all OOS score is bit-identical to R2_rel's `h20_neu_RANK`, and BAR_all to R2_dual's `M_BAR`. My per-date metric code reproduces `L.xs_metrics` exactly (DEV IC 0.060411 both, t 6.1606 both). XR_all K20/s5/50 bps reproduces R2_rel's DEV CAGR 29.8% and excess t +3.75.

Phase averaging. The signal calendar is shifted by 0..step−1 trading days and the daily returns are averaged.
This is a daily-staggered book, and the random baseline gets the same treatment. Phase 0 is the plain `S.compare` number.
R2_dual showed that the phase alone moves a K20 book's 2026 CAGR by 10-14 pp, so the **phase-averaged (PA) excess and its
NW t (lag 20) are the primary statistics** below, and the phase range is shown.

## 2. Event rates of the three alpha-source labels (U = elig_base, n = rows with a defined label)

| label | n | +1 / 0 / −1 | daily +1 share mean / std / min / max | monthly +1 std (min-max) | corr(daily +1 share, N500 same window) | corr(monthly +1, N500 month) |
|---|---|---|---|---|---|---|
| XR | 1,289,713 | 30.0% / 40.0% / 29.9% | 30.0% / 0.0% / 30.0% / 30.1% | 0.0% (30.0%-30.1%) | 0.07 | 0.04 |
| BAR | 1,289,713 | 36.7% / 1.6% / 61.7% | 37.1% / 20.7% / 1.8% / 94.8% | 14.9% (13.0%-65.6%) | 0.71 | 0.63 |
| TSX | 1,289,713 | 25.7% / 35.7% / 38.7% | 25.7% / 8.6% / 7.1% / 62.4% | 6.1% (13.4%-39.9%) | 0.18 | 0.05 |

+1 share by year (−1 share in brackets):

| label | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|
| XR | 30.1% (29.9%) | 30.1% (29.9%) | 30.1% (29.9%) | 30.0% (30.0%) | 30.0% (29.9%) | 30.0% (30.0%) |
| BAR | 37.9% (60.6%) | 35.6% (62.9%) | 46.4% (51.6%) | 33.8% (64.8%) | 32.5% (65.8%) | 36.0% (62.5%) |
| TSX | 22.7% (42.2%) | 25.1% (37.9%) | 28.8% (35.2%) | 24.5% (40.3%) | 22.7% (42.4%) | 29.7% (34.2%) |

+1 share by regime at t (Nifty 500 vs 200dma × 20d momentum) and by liquidity tercile (low/mid/high log_turn20, per month):

| label | bear_dn20 | bear_up20 | bull_dn20 | bull_up20 | liq low | liq mid | liq high |
|---|---|---|---|---|---|---|---|
| XR | 30.0% | 30.0% | 30.0% | 30.0% | 29.4% | 30.9% | 29.9% |
| BAR | 41.2% | 41.8% | 35.2% | 35.2% | 35.9% | 36.7% | 37.5% |
| TSX | 27.6% | 27.2% | 25.6% | 24.9% | 23.2% | 25.6% | 28.2% |

Label/P&L coherence at 50 bps (mean net return per class; P(net>0); mean excess vs same-date EW universe):

| label | +1: net bps / P(net>0) / excess bps | 0: net / P / excess | −1: net / P / excess |
|---|---|---|---|
| XR | +1221 / 91% / +1163 | -71 / 45% / -129 | -938 / 6% / -996 |
| BAR | +958 / 92% / +652 | -50 / 0% / -251 | -476 / 22% / -381 |
| TSX | +1162 / 87% / +996 | +63 / 51% / -9 | -682 / 17% / -653 |

Label agreement (rows where all three are defined): XR vs BAR: P(+1|+1) 68%, P(−1|−1) 91%, row corr 0.49; XR vs TSX: P(+1|+1) 61%, P(−1|−1) 76%, row corr 0.61; BAR vs TSX: P(+1|+1) 53%, P(−1|−1) 57%, row corr 0.55.
Per-date Spearman of the continuous forms: XR~TSX t* 0.73, XR~BAR return 0.56, BAR~TSX 0.56, XR~r20 0.974.

**How event rates move with parameters** (share of +1 / 0 / −1 on U; barrier exits; monthly +1 std):

| variant | +1 | 0 | −1 | target / stop / time exits | monthly +1 std (min-max) |
|---|---|---|---|---|---|
| XR_q0.200 | 20.1% | 60.0% | 19.9% | — | 0.0% (rank label: constant) |
| XR_q0.300 | 30.0% | 40.0% | 29.9% | — | 0.0% (rank label: constant) |
| XR_q0.333 | 33.4% | 33.3% | 33.3% | — | 0.0% (rank label: constant) |
| BAR_pt2.0_sl2.0 | 48.8% | 1.5% | 49.7% | 43.8% / 41.5% / 14.7% | 14.7% (24.6%-76.6%) |
| BAR_pt3.0_sl1.5 | 36.7% | 1.6% | 61.7% | 26.6% / 56.6% / 16.8% | 14.9% (13.0%-65.6%) |
| BAR_pt3.0_sl3.0 | 48.0% | 3.1% | 48.9% | 32.2% / 25.8% / 42.0% | 16.1% (17.5%-75.7%) |
| BAR_pt4.0_sl2.0 | 40.0% | 2.6% | 57.3% | 19.6% / 46.0% / 34.4% | 16.2% (11.4%-70.0%) |
| TSX_T3 | 38.3% | 10.2% | 51.6% | — | 7.6% (22.2%-55.0%) |
| TSX_T5 | 25.7% | 35.7% | 38.7% | — | 6.1% (13.4%-39.9%) |
| TSX_T8 | 10.9% | 68.6% | 20.5% | — | 3.3% (4.5%-20.1%) |

Reading. The XR rank label is regime-free by construction: daily +1 share std is 0.03% and its correlation with the market is 0.07. The A2 barrier is a market label: the daily +1 share ranges 2%-95% with correlation 0.71. Moving the target from 2 to 4 ATR (stop 2) takes P(+1) from 48.8% to 40.0% and target exits from 43.8% to 19.6%. Widening the stop from 1.5 to 3 ATR (target 3) takes P(+1) from 36.7% to 48.0% and time exits from 16.8% to 42.0%. No geometry lowers the monthly +1 std below 14.7%. TSX sits between XR and BAR (daily corr 0.18). Its threshold T trades class balance for rarity: T=3 gives 38.3% +1 and T=8 gives 10.9%. As round 1 found, abs(t*) ≥ 5 is not a significance level.

## 3. Learnability (walk-forward OOS, per-date cross-section; t from every 20th date)

ic_xr = IC vs the XR_neu20 pct (relative yardstick); ic_raw = IC vs r20; ic_tsx = IC vs TSX t*; AUC_top = AUC for XR +1 (pct>0.7); AUC_bot = AUC of −score for XR −1 (pct≤0.3); own AUC = AUC vs the model's own +1 class.

| score | DEV ic_xr (t) | DEV ic_raw (t) | DEV AUC_top / AUC_bot | DEV own AUC | 2026 ic_xr (t) | 2026 ic_raw | 2026 AUC_top / AUC_bot | ic_xr by year 23/24/25/26 |
|---|---|---|---|---|---|---|---|---|
| XR_all | 0.060 (+6.16) | 0.072 (+4.31) | 0.517 / 0.544 | — | 0.054 (+4.39) | 0.047 | 0.503 / 0.553 | 0.023 / 0.088 / 0.070 / 0.054 |
| BAR_all | 0.032 (+4.80) | 0.036 (+3.57) | 0.515 / 0.516 | 0.524 | 0.044 (+3.70) | 0.033 | 0.504 / 0.543 | 0.012 / 0.044 / 0.041 / 0.044 |
| TSX_all | 0.061 (+6.71) | 0.072 (+6.07) | 0.528 / 0.534 | 0.544 | 0.068 (+3.85) | 0.059 | 0.513 / 0.559 | 0.035 / 0.091 / 0.056 / 0.068 |
| ENS3 | 0.058 (+6.41) | 0.069 (+5.93) | 0.523 / 0.535 | — | 0.061 (+4.07) | 0.050 | 0.507 / 0.558 | 0.027 / 0.085 / 0.063 / 0.061 |
| ENS_XB | 0.053 (+5.91) | 0.062 (+4.84) | 0.518 / 0.534 | — | 0.053 (+3.89) | 0.042 | 0.503 / 0.553 | 0.020 / 0.075 / 0.062 / 0.053 |
| ENS_XT | 0.065 (+6.76) | 0.077 (+6.19) | 0.524 / 0.541 | — | 0.064 (+4.20) | 0.055 | 0.508 / 0.560 | 0.033 / 0.094 / 0.067 / 0.064 |
| ENS_BT | 0.051 (+6.19) | 0.060 (+5.58) | 0.524 / 0.527 | — | 0.060 (+3.96) | 0.049 | 0.509 / 0.555 | 0.026 / 0.074 / 0.053 / 0.060 |
| XR_no_market | 0.057 (+5.53) | 0.066 (+3.97) | 0.515 / 0.542 | — | 0.082 (+5.13) | 0.074 | 0.520 / 0.564 | 0.012 / 0.089 / 0.069 / 0.082 |
| BAR_no_market | 0.031 (+4.28) | 0.038 (+3.68) | 0.509 / 0.522 | 0.524 | 0.051 (+5.90) | 0.063 | 0.522 / 0.532 | -0.005 / 0.058 / 0.040 / 0.051 |
| TSX_no_market | 0.055 (+6.59) | 0.071 (+5.65) | 0.524 / 0.533 | 0.548 | 0.083 (+4.27) | 0.077 | 0.529 / 0.558 | 0.015 / 0.091 / 0.059 / 0.083 |
| ENS3_nomkt | 0.055 (+6.18) | 0.067 (+5.05) | 0.518 / 0.537 | — | 0.083 (+5.70) | 0.081 | 0.527 / 0.560 | 0.008 / 0.091 / 0.065 / 0.083 |
| XR_all_FN | 0.041 (+5.72) | 0.043 (+5.94) | 0.520 / 0.520 | — | 0.049 (+3.83) | 0.051 | 0.524 / 0.526 | 0.028 / 0.055 / 0.041 / 0.049 |
| ENS3_FN | 0.046 (+6.82) | 0.047 (+7.22) | 0.524 / 0.522 | — | 0.050 (+3.64) | 0.052 | 0.526 / 0.526 | 0.041 / 0.058 / 0.039 / 0.050 |
| TSX_all_FN | 0.046 (+6.39) | 0.047 (+6.90) | 0.525 / 0.520 | — | 0.052 (+3.19) | 0.053 | 0.529 / 0.524 | 0.041 / 0.058 / 0.038 / 0.052 |
| XR_all_FC | 0.059 (+7.37) | 0.077 (+4.07) | 0.500 / 0.561 | — | 0.044 (+2.11) | 0.024 | 0.493 / 0.556 | 0.054 / 0.069 / 0.053 / 0.044 |

Score correlations (mean per-date Spearman of OOS scores) and top-20 overlap:

| pair | DEV Spearman | 2026 Spearman | DEV top-20 overlap | 2026 top-20 overlap |
|---|---|---|---|---|
| XR_all ~ BAR_all | 0.56 | 0.64 | 24% | 17% |
| XR_all ~ TSX_all | 0.71 | 0.72 | 28% | 19% |
| BAR_all ~ TSX_all | 0.64 | 0.68 | 24% | 19% |
| XR_all ~ ENS3 | 0.86 | 0.89 | 44% | 31% |
| TSX_all ~ ENS3 | 0.90 | 0.90 | 48% | 43% |

Reading. TSX ranks the XR target as well as the XR model itself in DEV and better in 2026: ic_xr 0.061 vs 0.060 DEV, and 0.068 vs 0.054 in 2026. BAR is the weakest ranker (0.032). The three scores are related but far from identical (Spearman 0.56-0.71; top-20 overlap 24-28%), which is the precondition for an ensemble to help. Section 5 shows that higher IC did **not** translate into a better top-20 book for TSX/ENS3 in 2026.

## 4. Investability (L.Sim, h=20, U, long top-K, phase-averaged excess vs horizon-matched random)

### 4a. Long top-20, step 5

| score | cost | DEV CAGR (PA) | DEV random | DEV excess/yr (NW t) | phase range of excess CAGR | DEV maxDD (p0) | DEV p0 excess (t) | 2026 CAGR (PA, ann.) | 2026 random | 2026 excess/yr (t) | 2026 phase range |
|---|---|---|---|---|---|---|---|---|---|---|---|
| XR_all | 50 | 29.3% | 11.8% | +15.2% (+3.81) | +15.6%..+20.1% | -29.4% | +18.0% (+3.75) | 12.9% | 10.0% | +3.3% (+0.44) | +0.4%..+7.2% |
| XR_all | 80 | 24.7% | 7.8% | +15.2% (+3.81) | +15.0%..+19.4% | -30.0% | +17.4% (+3.75) | 9.1% | 6.3% | +3.3% (+0.44) | +0.4%..+7.0% |
| BAR_all | 50 | 22.1% | 11.8% | +9.1% (+2.38) | +6.0%..+12.4% | -27.5% | +8.9% (+2.00) | 2.8% | 10.0% | -7.3% (-0.87) | -12.0%..+0.6% |
| BAR_all | 80 | 17.7% | 7.8% | +9.1% (+2.38) | +5.8%..+12.0% | -28.9% | +8.6% (+2.00) | -0.6% | 6.3% | -7.3% (-0.87) | -11.6%..+0.6% |
| TSX_all | 50 | 24.7% | 11.8% | +11.4% (+3.18) | +9.1%..+16.1% | -28.8% | +12.1% (+2.85) | 2.9% | 10.0% | -7.0% (-0.82) | -10.5%..-4.5% |
| TSX_all | 80 | 20.2% | 7.8% | +11.4% (+3.18) | +8.8%..+15.5% | -29.8% | +11.6% (+2.85) | -0.6% | 6.3% | -7.0% (-0.82) | -10.1%..-4.4% |
| ENS3 | 50 | 29.7% | 11.8% | +15.4% (+4.37) | +15.8%..+20.4% | -27.6% | +20.4% (+4.59) | 3.0% | 10.0% | -7.0% (-0.80) | -11.8%..-3.2% |
| ENS3 | 80 | 25.0% | 7.8% | +15.4% (+4.37) | +15.2%..+19.7% | -28.2% | +19.7% (+4.59) | -0.5% | 6.3% | -7.0% (-0.80) | -11.4%..-3.1% |
| ENS_XB | 50 | 27.3% | 11.8% | +13.5% (+3.59) | +13.6%..+17.3% | -26.8% | +16.3% (+3.37) | 4.3% | 10.0% | -5.5% (-0.66) | -12.7%..+0.6% |
| ENS_XB | 80 | 22.8% | 7.8% | +13.5% (+3.59) | +13.1%..+16.7% | -28.0% | +15.7% (+3.37) | 0.8% | 6.3% | -5.5% (-0.66) | -12.3%..+0.6% |
| ENS_XT | 50 | 29.8% | 11.8% | +15.5% (+4.21) | +16.4%..+19.4% | -29.0% | +17.8% (+3.91) | 2.9% | 10.0% | -6.8% (-0.77) | -9.4%..-4.3% |
| ENS_XT | 80 | 25.1% | 7.8% | +15.5% (+4.21) | +15.9%..+18.8% | -29.9% | +17.2% (+3.91) | -0.5% | 6.3% | -6.8% (-0.77) | -9.1%..-4.2% |
| ENS_BT | 50 | 27.1% | 11.8% | +13.3% (+3.88) | +9.8%..+20.2% | -26.1% | +20.2% (+4.56) | -0.2% | 10.0% | -10.3% (-1.16) | -13.5%..-3.2% |
| ENS_BT | 80 | 22.5% | 7.8% | +13.3% (+3.88) | +9.5%..+19.4% | -27.1% | +19.4% (+4.56) | -3.6% | 6.3% | -10.3% (-1.16) | -13.1%..-3.1% |
| XR_no_market | 50 | 26.9% | 11.8% | +13.3% (+3.16) | +12.0%..+18.0% | -31.1% | +15.3% (+3.10) | 19.5% | 10.0% | +9.1% (+1.62) | +7.0%..+12.2% |
| XR_no_market | 80 | 22.4% | 7.8% | +13.3% (+3.16) | +11.5%..+17.3% | -32.2% | +14.8% (+3.10) | 15.5% | 6.3% | +9.1% (+1.62) | +6.8%..+11.8% |
| BAR_no_market | 50 | 9.8% | 11.8% | -1.8% (-0.57) | -4.4%..-0.0% | -31.2% | -4.1% (-0.98) | 17.0% | 10.0% | +6.6% (+0.86) | +3.7%..+10.9% |
| BAR_no_market | 80 | 5.9% | 7.8% | -1.8% (-0.57) | -4.3%..-0.0% | -31.8% | -4.0% (-0.98) | 13.1% | 6.3% | +6.6% (+0.86) | +3.6%..+10.5% |
| TSX_no_market | 50 | 20.5% | 11.8% | +8.0% (+2.12) | +6.5%..+10.4% | -33.8% | +7.9% (+1.77) | 19.3% | 10.0% | +8.4% (+0.86) | +1.6%..+14.1% |
| TSX_no_market | 80 | 16.2% | 7.8% | +8.0% (+2.12) | +6.3%..+10.0% | -34.7% | +7.6% (+1.77) | 15.3% | 6.3% | +8.4% (+0.86) | +1.6%..+13.6% |
| ENS3_nomkt | 50 | 25.1% | 11.8% | +11.6% (+3.36) | +11.9%..+13.9% | -29.2% | +13.7% (+3.10) | 17.4% | 10.0% | +6.5% (+1.21) | +1.7%..+12.7% |
| ENS3_nomkt | 80 | 20.6% | 7.8% | +11.6% (+3.36) | +11.4%..+13.4% | -30.3% | +13.2% (+3.10) | 13.5% | 6.3% | +6.5% (+1.21) | +1.6%..+12.3% |
| XR_all_FN | 50 | 26.2% | 11.8% | +12.9% (+3.22) | +10.3%..+19.3% | -25.5% | +10.3% (+2.23) | 14.7% | 10.0% | +4.7% (+0.59) | -3.4%..+12.4% |
| XR_all_FN | 80 | 21.6% | 7.8% | +12.9% (+3.22) | +10.0%..+18.6% | -27.0% | +10.0% (+2.23) | 10.8% | 6.3% | +4.7% (+0.59) | -3.3%..+12.0% |
| ENS3_FN | 50 | 21.3% | 11.8% | +8.4% (+2.73) | +3.4%..+14.9% | -23.9% | +9.8% (+2.41) | 19.1% | 10.0% | +8.5% (+1.39) | +5.7%..+13.5% |
| ENS3_FN | 80 | 16.9% | 7.8% | +8.4% (+2.73) | +3.3%..+14.3% | -25.2% | +9.5% (+2.41) | 15.1% | 6.3% | +8.5% (+1.39) | +5.5%..+13.0% |
| TSX_all_FN | 50 | 21.7% | 11.8% | +8.7% (+2.90) | +5.9%..+11.9% | -27.6% | +10.3% (+2.41) | 22.2% | 10.0% | +11.0% (+2.04) | +7.3%..+14.9% |
| TSX_all_FN | 80 | 17.4% | 7.8% | +8.7% (+2.90) | +5.7%..+11.5% | -28.8% | +9.9% (+2.41) | 18.2% | 6.3% | +11.0% (+2.04) | +7.1%..+14.4% |
| XR_all_FC | 50 | 14.8% | 11.8% | +2.0% (+0.29) | +2.3%..+4.2% | -20.4% | +2.6% (+0.24) | -4.1% | 10.0% | -14.5% (-1.19) | -15.2%..-10.1% |
| XR_all_FC | 80 | 10.7% | 7.8% | +2.0% (+0.29) | +2.2%..+4.1% | -21.7% | +2.5% (+0.24) | -7.3% | 6.3% | -14.5% (-1.19) | -14.7%..-9.8% |
| ENS3_FC | 50 | 17.7% | 11.8% | +5.2% (+0.96) | +3.4%..+8.1% | -23.9% | +6.9% (+1.18) | -0.8% | 10.0% | -10.3% (-0.84) | -14.2%..-5.1% |
| ENS3_FC | 80 | 13.5% | 7.8% | +5.2% (+0.96) | +3.3%..+7.8% | -25.1% | +6.7% (+1.18) | -4.1% | 6.3% | -10.3% (-0.85) | -13.7%..-4.9% |
| TSX_all_FC | 50 | 19.4% | 11.8% | +7.0% (+1.13) | +5.9%..+9.0% | -26.5% | +7.2% (+1.11) | -2.4% | 10.0% | -11.7% (-0.88) | -14.1%..-9.1% |
| TSX_all_FC | 80 | 15.1% | 7.8% | +7.0% (+1.13) | +5.7%..+8.7% | -28.2% | +7.0% (+1.11) | -5.6% | 6.3% | -11.7% (-0.88) | -13.7%..-8.8% |

Exposure (phase 0) is 0.93 in DEV and 0.87 in 2026 for every top-20 book (slot sizing; the first sleeves start in cash and the 2026 window ends mid-sleeve).
**Costs.** With a 20-day time exit every sleeve turns over 100% at each rebalance, for the strategy and the random baseline alike. So the excess over random is the same at 50 and 80 bps, and only the absolute CAGR falls, by about 4.5 pp/yr (XR DEV 29.3% → 24.7%).
Nifty 500 (price) context: 2023 +25.2%, 2024 +14.9%, 2025 +6.2%, 2026 YTD −7.8%. The EW universe (adjusted, ~total return) is
far stronger in 2026: the EW-U factor book made +10.1%/yr.

By year (phase-averaged, K20 s5 50 bps; strategy vs random):

| score | 2023 | 2024 | 2025 | 2026 YTD |
|---|---|---|---|---|
| XR_all | 52.5% vs 38.6% | 42.2% vs 13.7% | -1.2% vs -11.6% | 9.5% vs 7.4% |
| BAR_all | 42.4% vs 38.6% | 37.0% vs 13.7% | -7.4% vs -11.6% | 2.1% vs 7.4% |
| TSX_all | 48.9% vs 38.6% | 29.4% vs 13.7% | -0.3% vs -11.6% | 2.1% vs 7.4% |
| ENS3 | 53.0% vs 38.6% | 44.1% vs 13.7% | -2.1% vs -11.6% | 2.2% vs 7.4% |
| ENS_XT | 57.5% vs 38.6% | 38.0% vs 13.7% | -0.5% vs -11.6% | 2.2% vs 7.4% |
| ENS3_nomkt | 48.6% vs 38.6% | 38.3% vs 13.7% | -5.5% vs -11.6% | 12.7% vs 7.4% |
| XR_all_FN | 49.4% vs 38.6% | 45.7% vs 13.7% | -8.5% vs -11.6% | 10.8% vs 7.4% |
| TSX_all_FN | 36.6% vs 38.6% | 34.5% vs 13.7% | -2.5% vs -11.6% | 16.2% vs 7.4% |

Risk of the long top-20 book (50 bps, phase-averaged daily book; random = 5-seed random top-20 on the same mask):

| score | DEV Sharpe | DEV maxDD | 2026 Sharpe | 2026 maxDD | random DEV maxDD (p0) | random 2026 maxDD (p0) |
|---|---|---|---|---|---|---|
| XR_all | 1.37 | -29.1% | 0.67 | -17.8% | -29.7% | -16.6% |
| BAR_all | 1.14 | -27.6% | 0.25 | -16.7% | -29.7% | -16.6% |
| TSX_all | 1.20 | -28.4% | 0.25 | -14.2% | -29.7% | -16.6% |
| ENS3 | 1.42 | -26.4% | 0.26 | -15.6% | -29.7% | -16.6% |
| ENS_XT | 1.41 | -27.5% | 0.25 | -15.8% | -29.7% | -16.6% |
| XR_no_market | 1.28 | -30.5% | 0.93 | -16.5% | -29.7% | -16.6% |
| ENS3_nomkt | 1.29 | -29.7% | 0.97 | -15.3% | -29.7% | -16.6% |
| XR_all_FN | 1.20 | -26.2% | 0.75 | -18.3% | -29.7% | -16.6% |
| TSX_all_FN | 1.18 | -25.3% | 1.09 | -17.7% | -29.7% | -16.6% |

No alpha source reduces drawdowns. Every long top-20 book carries about the random book's market drawdown (DEV −25% to −31% vs −29.7%), because they are fully invested, long-only and roughly beta-1. Ensembling smooths the *excess* (higher Sharpe) but not the drawdown. Drawdown control has to come from the regime/exposure layer.

### 4b. AVOID overlay (equal-weight all U names except the score's bottom 30%; step 5; vs random-70% and vs EW universe)

| score | DEV CAGR | DEV excess vs random/yr (t) | DEV excess vs EW (t) | 2026 CAGR | 2026 excess vs random (t) | 2026 vs EW (t) | DEV CAGR at 80bp (random) |
|---|---|---|---|---|---|---|---|
| XR_all | 14.7% | +3.1% (+2.99) | +3.2% (+3.00) | 9.3% | +0.6% (+0.38) | +0.6% (+0.39) | 10.6% (7.1%) |
| BAR_all | 13.6% | +2.4% (+3.52) | +2.4% (+3.53) | 9.6% | +0.9% (+0.61) | +1.0% (+0.63) | 9.5% (7.1%) |
| TSX_all | 15.4% | +3.9% (+4.19) | +3.9% (+4.21) | 10.5% | +1.7% (+0.82) | +1.8% (+0.84) | 11.3% (7.1%) |
| ENS3 | 15.0% | +3.5% (+4.07) | +3.5% (+4.08) | 10.1% | +1.3% (+0.75) | +1.4% (+0.77) | 10.9% (7.1%) |
| ENS_XB | 14.5% | +3.1% (+3.70) | +3.1% (+3.69) | 9.7% | +1.0% (+0.58) | +1.0% (+0.60) | 10.4% (7.1%) |
| ENS_XT | 15.3% | +3.7% (+3.92) | +3.8% (+3.92) | 10.0% | +1.3% (+0.67) | +1.3% (+0.69) | 11.2% (7.1%) |
| ENS_BT | 14.9% | +3.5% (+4.33) | +3.5% (+4.35) | 10.4% | +1.6% (+0.88) | +1.6% (+0.90) | 10.8% (7.1%) |
| XR_no_market | 14.5% | +3.0% (+2.65) | +3.0% (+2.65) | 10.8% | +2.0% (+1.21) | +2.0% (+1.24) | 10.4% (7.1%) |
| BAR_no_market | 13.5% | +2.1% (+3.51) | +2.2% (+3.53) | 11.2% | +2.4% (+1.64) | +2.4% (+1.69) | 9.4% (7.1%) |
| TSX_no_market | 15.1% | +3.5% (+3.72) | +3.6% (+3.73) | 12.1% | +3.2% (+1.60) | +3.3% (+1.64) | 10.9% (7.1%) |
| ENS3_nomkt | 14.9% | +3.3% (+3.52) | +3.3% (+3.52) | 11.9% | +3.0% (+1.73) | +3.0% (+1.77) | 10.7% (7.1%) |
| XR_all_FN | 13.7% | +2.3% (+5.55) | +2.4% (+5.51) | 11.0% | +2.3% (+2.93) | +2.3% (+3.09) | 9.6% (7.1%) |
| ENS3_FN | 14.3% | +2.9% (+7.70) | +2.9% (+7.76) | 10.9% | +2.2% (+3.30) | +2.2% (+3.56) | 10.2% (7.1%) |
| TSX_all_FN | 14.3% | +2.9% (+8.10) | +2.9% (+8.16) | 10.9% | +2.2% (+3.70) | +2.3% (+3.91) | 10.2% (7.1%) |
| XR_all_FC | 13.6% | +2.1% (+1.86) | +2.1% (+1.88) | 9.1% | +0.3% (+0.11) | +0.3% (+0.12) | 9.5% (7.1%) |
| ENS3_FC | 13.4% | +2.0% (+2.58) | +2.1% (+2.61) | 9.6% | +0.9% (+0.44) | +0.9% (+0.46) | 9.3% (7.1%) |
| TSX_all_FC | 13.8% | +2.4% (+2.95) | +2.5% (+2.99) | 10.3% | +1.6% (+0.78) | +1.6% (+0.80) | 9.7% (7.1%) |

### 4c. K × step sensitivity (50 bps; phase-averaged excess/yr and NW t)

**DEV 2023-25**

| K / step | XR_all | BAR_all | TSX_all | ENS3 | ENS_XT | XR_all_FN | ENS3_FN | TSX_all_FN |
|---|---|---|---|---|---|---|---|---|
| K10_s5 | +20.4% (+4.48) | +10.8% (+2.37) | +13.5% (+3.35) | +19.2% (+4.79) | +20.7% (+5.04) | +13.5% (+2.51) | +9.4% (+2.15) | +9.6% (+2.11) |
| K10_s10 | +19.2% (+4.26) | +9.3% (+2.08) | +11.9% (+2.81) | +17.8% (+4.40) | +19.3% (+4.53) | +12.3% (+2.30) | +8.0% (+1.81) | +8.0% (+1.77) |
| K20_s5 | +15.2% (+3.81) | +9.1% (+2.38) | +11.4% (+3.18) | +15.4% (+4.37) | +15.5% (+4.21) | +12.9% (+3.22) | +8.4% (+2.73) | +8.7% (+2.90) |
| K20_s10 | +15.5% (+4.14) | +9.2% (+2.45) | +11.5% (+3.37) | +15.5% (+4.76) | +15.8% (+4.72) | +13.1% (+3.14) | +8.7% (+2.64) | +8.7% (+2.85) |
| K30_s5 | +14.2% (+3.96) | +8.9% (+2.52) | +12.7% (+3.70) | +14.1% (+4.14) | +14.1% (+4.26) | +13.6% (+3.79) | +9.4% (+3.65) | +9.9% (+3.65) |
| K30_s10 | +13.7% (+3.76) | +8.2% (+2.28) | +12.0% (+3.47) | +13.6% (+3.88) | +13.5% (+3.97) | +13.0% (+3.53) | +9.0% (+3.40) | +9.3% (+3.42) |
| K50_s5 | +11.5% (+3.69) | +7.3% (+2.45) | +12.1% (+4.11) | +12.2% (+4.02) | +11.8% (+3.99) | +12.1% (+4.20) | +9.4% (+4.58) | +8.3% (+4.06) |
| K50_s10 | +11.3% (+3.67) | +7.0% (+2.35) | +11.8% (+4.14) | +12.0% (+4.06) | +11.6% (+4.04) | +12.0% (+4.17) | +9.3% (+4.45) | +8.2% (+3.84) |

**HOLDOUT 2026**

| K / step | XR_all | BAR_all | TSX_all | ENS3 | ENS_XT | XR_all_FN | ENS3_FN | TSX_all_FN |
|---|---|---|---|---|---|---|---|---|
| K10_s5 | +4.2% (+0.39) | -8.0% (-0.80) | -5.1% (-0.50) | -8.9% (-0.78) | -6.9% (-0.64) | +5.8% (+0.56) | +8.3% (+1.08) | +12.0% (+1.69) |
| K10_s10 | +7.7% (+0.64) | -5.6% (-0.52) | -1.8% (-0.18) | -5.8% (-0.48) | -3.6% (-0.32) | +10.1% (+0.88) | +13.5% (+1.65) | +17.7% (+2.36) |
| K20_s5 | +3.3% (+0.44) | -7.3% (-0.87) | -7.0% (-0.82) | -7.0% (-0.80) | -6.8% (-0.77) | +4.7% (+0.59) | +8.5% (+1.39) | +11.0% (+2.04) |
| K20_s10 | +4.7% (+0.62) | -6.6% (-0.77) | -5.7% (-0.65) | -5.9% (-0.66) | -5.2% (-0.56) | +7.1% (+0.95) | +11.7% (+1.97) | +14.7% (+2.61) |
| K30_s5 | +4.3% (+0.63) | -5.3% (-0.65) | -5.4% (-0.67) | -5.5% (-0.64) | -3.0% (-0.36) | +8.4% (+1.06) | +9.5% (+1.45) | +10.9% (+1.81) |
| K30_s10 | +4.7% (+0.68) | -5.1% (-0.61) | -4.8% (-0.57) | -5.1% (-0.58) | -2.3% (-0.26) | +10.1% (+1.35) | +11.5% (+1.78) | +13.5% (+2.33) |
| K50_s5 | +4.1% (+0.81) | -5.1% (-0.76) | -4.4% (-0.63) | -4.8% (-0.67) | -3.3% (-0.48) | +9.4% (+1.53) | +10.6% (+2.03) | +10.9% (+2.10) |
| K50_s10 | +2.2% (+0.42) | -7.1% (-0.91) | -6.2% (-0.84) | -6.8% (-0.86) | -5.1% (-0.67) | +8.8% (+1.40) | +10.1% (+1.90) | +10.7% (+2.05) |

80 bps stress for K20 s10 / K50 s10 (DEV | 2026 PA excess):

| score | K20 s10 80bp DEV | K20 s10 80bp 2026 | K50 s10 80bp DEV | K50 s10 80bp 2026 | K50 s10 80bp DEV CAGR vs random |
|---|---|---|---|---|---|
| XR_all | +15.5% (+4.14) | +4.7% (+0.62) | +11.3% (+3.67) | +2.2% (+0.42) | 19.4% vs 7.2% |
| BAR_all | +9.2% (+2.44) | -6.6% (-0.76) | +7.0% (+2.35) | -7.1% (-0.91) | 14.6% vs 7.2% |
| TSX_all | +11.5% (+3.37) | -5.7% (-0.65) | +11.8% (+4.14) | -6.2% (-0.84) | 20.0% vs 7.2% |
| ENS3 | +15.5% (+4.76) | -5.9% (-0.66) | +12.0% (+4.06) | -6.8% (-0.86) | 20.4% vs 7.2% |
| ENS_XT | +15.8% (+4.72) | -5.2% (-0.56) | +11.6% (+4.04) | -5.1% (-0.67) | 19.9% vs 7.2% |
| XR_all_FN | +13.1% (+3.14) | +7.1% (+0.95) | +12.0% (+4.17) | +8.8% (+1.40) | 20.0% vs 7.2% |
| ENS3_FN | +8.7% (+2.64) | +11.7% (+1.97) | +9.3% (+4.45) | +10.1% (+1.90) | 17.3% vs 7.2% |
| TSX_all_FN | +8.7% (+2.85) | +14.7% (+2.61) | +8.2% (+3.85) | +10.7% (+2.05) | 16.2% vs 7.2% |

Plateau vs cliff. In DEV every score is positive in every K × step cell, so no cliff appears. Raw scores' excess falls as K rises (XR +20.4% at K10 → +11.5% at K50). The FN scores are flat across K (XR_FN +13.5% at K10, +12.1% at K50), so at K50 their t equals or beats the raw score's. In 2026 the raw BAR/TSX/ENS3/ENS_XT books are negative in **8/8** cells, XR is positive but insignificant in 8/8, and all three FN scores are positive in 8/8. The 2026 failure is not a K, step or phase artefact.

## 5. Selection on DEV (pre-declared) and the holdout exam

Protocol, recorded at 2026-10-15T15:51:57 before any simulation of my scores: candidates XR_all, BAR_all, TSX_all, ENS3, ENS_XB, ENS_XT, ENS_BT; primary statistic = DEV phase-averaged (5 phases) excess-vs-random NW t (lag 20), long top-20, step 5, 50 bps, h=20, mask U; constraint = DEV phase-averaged CAGR at 80 bps must exceed the 80 bps random baseline; avoid screen chosen separately by the DEV PA t of the avoid30 overlay.

| candidate | DEV PA excess/yr | DEV NW t | rank | DEV 80bp CAGR vs random | 2026 PA excess/yr (t) | avoid DEV t | avoid rank | avoid 2026 excess (t) |
|---|---|---|---|---|---|---|---|---|
| XR_all | +15.2% | +3.81 | 4 | 24.7% vs 7.8% | +3.3% (+0.44) | +2.99 | 7 | +0.6% (+0.38) |
| BAR_all | +9.1% | +2.38 | 7 | 17.7% vs 7.8% | -7.3% (-0.87) | +3.52 | 6 | +0.9% (+0.61) |
| TSX_all | +11.4% | +3.18 | 6 | 20.2% vs 7.8% | -7.0% (-0.82) | +4.19 | 2 | +1.7% (+0.82) |
| ENS3 | +15.4% | +4.37 | 1 | 25.0% vs 7.8% | -7.0% (-0.80) | +4.07 | 3 | +1.3% (+0.75) |
| ENS_XB | +13.5% | +3.59 | 5 | 22.8% vs 7.8% | -5.5% (-0.66) | +3.70 | 5 | +1.0% (+0.58) |
| ENS_XT | +15.5% | +4.21 | 2 | 25.1% vs 7.8% | -6.8% (-0.77) | +3.92 | 4 | +1.3% (+0.67) |
| ENS_BT | +13.3% | +3.88 | 3 | 22.5% vs 7.8% | -10.3% (-1.16) | +4.33 | 1 | +1.6% (+0.88) |

**Selected (long book): ENS3.** 2026 exam: -7.0%/yr vs random (t -0.80). **FAIL.** **Selected (avoid screen): ENS_BT.** 2026: +1.6%/yr (t +0.88), positive but not significant.

Paired comparisons (difference of phase-averaged daily book returns, same Sim settings; random cancels; NW t lag 20):

| A − B | K20 DEV/yr (t) | K20 2026/yr (t) | avoid DEV/yr (t) | avoid 2026/yr (t) | K20 DEV by year 23/24/25 |
|---|---|---|---|---|---|
| ENS3 − XR_all | +0.1% (+0.06) | -10.3% (-1.55) | +0.4% (+0.74) | +0.8% (+1.44) | +0.5% / +1.1% / -1.1% |
| ENS_XT − XR_all | +0.3% (+0.13) | -10.1% (-1.52) | +0.6% (+1.52) | +0.7% (+1.03) | +3.5% / -3.4% / +0.9% |
| ENS_XB − XR_all | -1.7% (-0.79) | -8.8% (-1.63) | -0.1% (-0.18) | +0.4% (+0.89) | -2.5% / +2.3% / -5.0% |
| ENS_BT − XR_all | -2.0% (-0.61) | -13.6% (-1.83) | +0.3% (+0.39) | +1.0% (+1.42) | -4.1% / -2.9% / +1.1% |
| BAR_all − XR_all | -6.1% (-1.67) | -10.6% (-1.30) | -0.8% (-0.75) | +0.3% (+0.53) | -7.1% / -4.0% / -7.2% |
| TSX_all − XR_all | -3.8% (-1.09) | -10.3% (-1.29) | +0.7% (+0.97) | +1.1% (+1.15) | -2.1% / -10.1% / +1.0% |
| BAR_no_market − BAR_all | -10.9% (-2.99) | +13.9% (+0.99) | -0.2% (-0.37) | +1.5% (+1.31) | -6.1% / -10.3% / -16.3% |
| TSX_no_market − TSX_all | -3.4% (-1.14) | +15.4% (+2.16) | -0.4% (-0.72) | +1.5% (+2.64) | -3.6% / +0.6% / -7.3% |
| ENS3_nomkt − ENS3 | -3.8% (-1.58) | +13.5% (+2.21) | -0.2% (-0.56) | +1.7% (+2.76) | -3.1% / -4.6% / -3.6% |
| XR_no_market − XR_all | -1.9% (-0.90) | +5.8% (+0.99) | -0.2% (-0.61) | +1.4% (+2.64) | -6.3% / -3.3% / +3.9% |
| ENS3_nomkt − XR_all | -3.7% (-1.13) | +3.2% (+0.47) | +0.2% (+0.46) | +2.4% (+3.02) | -2.7% / -3.6% / -4.7% |
| TSX_no_market − XR_all | -7.2% (-2.17) | +5.1% (+0.45) | +0.4% (+0.75) | +2.6% (+2.62) | -5.7% / -9.5% / -6.3% |
| XR_all_FN − XR_all | -2.3% (-0.48) | +1.5% (+0.15) | -0.8% (-1.08) | +1.7% (+1.24) | -1.7% / +2.6% / -8.0% |
| ENS3_FN − ENS3 | -6.9% (-1.65) | +15.5% (+1.42) | -0.6% (-0.89) | +0.9% (+0.52) | -11.0% / -7.2% / -2.6% |
| TSX_all_FN − TSX_all | -2.8% (-0.62) | +18.0% (+1.64) | -1.0% (-1.30) | +0.5% (+0.24) | -9.5% / +3.7% / -2.7% |
| XR_all_FC − XR_all | -13.2% (-1.66) | -17.8% (-1.28) | -1.1% (-1.50) | -0.3% (-0.21) | -17.0% / -24.4% / +2.0% |

Reading. No ensemble beats XR on DEV in a paired test (best: ENS_XT +0.3%/yr, t 0.13). The ensembles' higher DEV t-statistics come from lower tracking variance against random, not from more return. In 2026 every ensemble and every single absolute/trend model lags XR by 9-14%/yr (t −1.3 to −1.8). Rows marked no-market, FN or FC were built as diagnostics. Their 2026 columns are **holdout-informed** and are not selection evidence.

## 6. Why the ensemble fails in 2026: a regime-conditional factor tilt

### 6a. What the top-20 picks are (mean over all dates; tilts = same-date percentile among U)

xr_pct = realised XR_neu residual percentile of the picks (factor-neutral skill; 0.5 = none). ex_raw = realised r20 minus the same-date U mean (bps per 20d trade, before costs). ex_fac = the part of ex_raw explained by the picks' exposure to the XR neutralisers (beta, vol, turnover). ex_resid = ex_raw − ex_fac.

| model | window | xr_pct | ex_raw | ex_fac | ex_resid | beta_60 | vol_20 | idio_vol_60 | log_turn20 | mom_12_1 | mom_5 | dist_sma200 | deliv_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XR_all | DEV | 0.532 | +132 | +8 | +124 | 0.48 | 0.64 | 0.56 | 0.59 | 0.59 | 0.49 | 0.65 | 0.57 |
| XR_all | 2026 | 0.529 | +35 | -9 | +44 | 0.51 | 0.58 | 0.50 | 0.65 | 0.44 | 0.38 | 0.33 | 0.56 |
| BAR_all | DEV | 0.522 | +74 | +10 | +64 | 0.50 | 0.65 | 0.51 | 0.59 | 0.51 | 0.35 | 0.55 | 0.59 |
| BAR_all | 2026 | 0.517 | -46 | -50 | +5 | 0.38 | 0.46 | 0.34 | 0.73 | 0.54 | 0.27 | 0.40 | 0.71 |
| TSX_all | DEV | 0.532 | +95 | +17 | +79 | 0.60 | 0.57 | 0.47 | 0.66 | 0.63 | 0.38 | 0.65 | 0.58 |
| TSX_all | 2026 | 0.507 | -47 | -9 | -39 | 0.42 | 0.34 | 0.25 | 0.88 | 0.63 | 0.39 | 0.50 | 0.64 |
| ENS3 | DEV | 0.539 | +128 | +16 | +113 | 0.53 | 0.62 | 0.49 | 0.62 | 0.59 | 0.38 | 0.62 | 0.61 |
| ENS3 | 2026 | 0.517 | -48 | -39 | -8 | 0.40 | 0.38 | 0.26 | 0.83 | 0.56 | 0.31 | 0.40 | 0.70 |
| XR_no_market | DEV | 0.528 | +113 | +4 | +109 | 0.47 | 0.63 | 0.55 | 0.59 | 0.61 | 0.50 | 0.66 | 0.57 |
| XR_no_market | 2026 | 0.543 | +86 | -1 | +87 | 0.50 | 0.57 | 0.52 | 0.65 | 0.55 | 0.42 | 0.42 | 0.58 |
| BAR_no_market | DEV | 0.502 | -12 | -4 | -8 | 0.46 | 0.59 | 0.53 | 0.47 | 0.48 | 0.38 | 0.50 | 0.57 |
| BAR_no_market | 2026 | 0.522 | +72 | +14 | +57 | 0.46 | 0.57 | 0.59 | 0.47 | 0.52 | 0.40 | 0.48 | 0.53 |
| TSX_no_market | DEV | 0.520 | +73 | +13 | +61 | 0.55 | 0.61 | 0.52 | 0.63 | 0.63 | 0.38 | 0.68 | 0.53 |
| TSX_no_market | 2026 | 0.537 | +85 | -10 | +95 | 0.45 | 0.50 | 0.43 | 0.77 | 0.65 | 0.37 | 0.58 | 0.57 |
| ENS3_nomkt | DEV | 0.530 | +102 | +13 | +89 | 0.49 | 0.63 | 0.51 | 0.61 | 0.59 | 0.41 | 0.64 | 0.57 |
| ENS3_nomkt | 2026 | 0.539 | +64 | -10 | +74 | 0.39 | 0.48 | 0.39 | 0.72 | 0.65 | 0.35 | 0.55 | 0.67 |
| XR_all_FN | DEV | 0.518 | +103 | -16 | +119 | 0.56 | 0.71 | 0.72 | 0.42 | 0.47 | 0.53 | 0.52 | 0.59 |
| XR_all_FN | 2026 | 0.509 | +50 | +19 | +31 | 0.56 | 0.74 | 0.77 | 0.45 | 0.42 | 0.59 | 0.54 | 0.51 |
| TSX_all_FN | DEV | 0.520 | +73 | -12 | +85 | 0.47 | 0.57 | 0.61 | 0.45 | 0.48 | 0.52 | 0.47 | 0.68 |
| TSX_all_FN | 2026 | 0.529 | +104 | +4 | +100 | 0.52 | 0.64 | 0.68 | 0.45 | 0.42 | 0.47 | 0.42 | 0.64 |

### 6b. Gain-importance share of the market/regime feature group by fold (each fold is trained only on earlier data)

| model | 2023 fold | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| XR_all | 12.5% | 17.6% | 18.4% | 18.9% |
| BAR_all | 61.1% | 74.1% | 82.6% | 86.5% |
| TSX_all | 29.4% | 40.5% | 49.6% | 57.4% |

### 6c. The no-market experiment (same models without the 10 market/regime features)

| model | DEV K20 excess/yr (t) | 2026 K20 excess/yr (t) | DEV ic_xr | 2026 ic_xr | ΔIC_xr vs full model DEV (NW t) | 2026 (NW t / non-overlap t) | ΔIC by year 23/24/25/26 |
|---|---|---|---|---|---|---|---|
| XR_no_market | +13.3% (+3.16) | +9.1% (+1.62) | 0.057 | 0.082 | -0.0033 (-1.33) | +0.0279 (+5.45 / +1.31) | -0.0113 / +0.0017 / -0.0004 / +0.0279 |
| BAR_no_market | -1.8% (-0.57) | +6.6% (+0.86) | 0.031 | 0.051 | -0.0016 (-0.31) | +0.0071 (+0.68 / -0.29) | -0.0176 / +0.0142 / -0.0015 / +0.0071 |
| TSX_no_market | +8.0% (+2.12) | +8.4% (+0.86) | 0.055 | 0.083 | -0.0057 (-1.70) | +0.0150 (+3.79 / +0.54) | -0.0203 / -0.0001 / +0.0032 / +0.0150 |
| ENS3_nomkt | +11.6% (+3.36) | +6.5% (+1.21) | 0.055 | 0.083 | -0.0034 (-1.00) | +0.0224 (+3.87 / +0.80) | -0.0186 / +0.0062 / +0.0022 / +0.0224 |

Reading.

* The absolute barrier label's DEV edge is almost entirely regime timing. Without market features, BAR's top-20 book makes -1.8%/yr in DEV (picks' raw excess -12 bps), against +9.1% with them.
* Market features helped the BAR and ENS3 books in every DEV year and the TSX book in 2 of 3 (paired by-year table in §5). So a DEV-only
  analyst would keep them, and this is not a classic in-sample overfit: all four years are walk-forward OOS. It is a factor-timing bet
  that paid in 2023-25 and reversed in 2026, when small, high-vol names led (2026 LS factors: SIZE +5.6%, LOWVOL -18.9%, LOWIDIO -22.9%/yr).
* XR is far less exposed. Its target strips beta, vol and size, so market features can act only through interactions. They carry 12-19% of XR's gain importance and change XR's DEV IC by -0.0033 (n.s.).
* Caveat on the 2026 ΔIC t-stats: NW (Bartlett, lag 20) on ~190 overlapping 20-day windows understates the long-run variance, and the non-overlap t uses only ~10 points. The truth lies between them. The paired daily-book tests in §5 have no forward-window overlap and are the better guide.

## 7. Feature-group ablation on the XR_neu model (drop one group, retrain the same walk-forward)

Groups (a disjoint partition of the 52 features; `age` is never dropped): **momentum** (11): mom_5, mom_10, mom_20, mom_60, mom_120, mom_12_1, dist_sma20, dist_sma50, dist_sma200, rel_mom20, rel_mom60; **volrisk** (8): vol_20, vol_60, vol_ratio, atr_pct, beta_60, idio_vol_60, max_ret_20, min_ret_20; **volume** (2): volz_20, log_turn20; **delivery** (4): deliv_pct, deliv_z20, deliv_ratio, xr_deliv_z; **market** (10): mkt_mom5, mkt_mom20, mkt_mom60, mkt_dist_sma50, mkt_dist_sma200, mkt_vol20, vix, breadth50, breadth_ad, dispersion; **xsrank** (7): xr_mom20, xr_mom60, xr_mom120, xr_vol20, xr_volz, xr_dist_sma50, xr_hi52; **technical** (9): rsi_14, range_pos, hl_range, gap_open, intraday, hi52_dist, lo52_dist, hi20_dist, up_frac_20.

| dropped group | DEV ΔIC_xr (NW t / non-ovl t) | 2026 ΔIC_xr (NW t / non-ovl t) | DEV ΔAUC_bot (NW t) | ΔIC_xr by year 23/24/25/26 | ΔK20 DEV/yr (t) | ΔK20 2026/yr (t) | Δavoid DEV/yr (t) | Δavoid 2026/yr (t) |
|---|---|---|---|---|---|---|---|---|
| momentum | -0.0004 (-0.27 / +0.26) | -0.0042 (-1.08 / +0.51) | +0.0012 (+1.22) | +0.0038 / -0.0001 / -0.0050 / -0.0042 | -3.2% (-1.70) | -4.4% (-1.00) | -0.0% (-0.11) | -0.1% (-0.16) |
| volrisk | -0.0036 (-1.62 / -0.95) | +0.0098 (+2.16 / +1.08) | -0.0049 (-3.39) | -0.0076 / -0.0003 / -0.0029 / +0.0098 | +1.6% (+0.78) | +2.2% (+0.51) | -0.1% (-0.46) | +0.7% (+2.18) |
| volume | -0.0007 (-0.36 / -1.02) | -0.0096 (-4.17 / -0.64) | +0.0009 (+0.80) | -0.0092 / +0.0043 / +0.0027 / -0.0096 | +2.0% (+0.82) | -2.9% (-0.39) | -0.1% (-0.72) | -0.7% (-2.44) |
| delivery | -0.0064 (-4.99 / -2.44) | -0.0135 (-3.68 / -2.85) | -0.0022 (-3.08) | -0.0055 / -0.0113 / -0.0024 / -0.0135 | -2.1% (-1.19) | -3.3% (-1.07) | -0.2% (-1.73) | -1.1% (-2.54) |
| market | -0.0033 (-1.33 / -0.55) | +0.0279 (+5.45 / +1.31) | -0.0018 (-1.34) | -0.0113 / +0.0017 / -0.0004 / +0.0279 | -1.9% (-0.90) | +5.8% (+0.99) | -0.2% (-0.61) | +1.4% (+2.64) |
| xsrank | +0.0020 (+1.04 / +0.35) | +0.0079 (+2.74 / +2.70) | +0.0026 (+2.25) | -0.0050 / +0.0023 / +0.0085 / +0.0079 | +0.4% (+0.22) | -1.3% (-0.34) | +0.3% (+1.80) | +0.4% (+1.28) |
| technical | -0.0009 (-0.65 / +0.67) | -0.0021 (-0.78 / -0.33) | -0.0004 (-0.57) | -0.0009 / -0.0019 / +0.0002 / -0.0021 | -1.9% (-1.06) | -1.2% (-0.44) | +0.1% (+0.54) | +0.0% (+0.05) |

Base XR_all: DEV ic_xr 0.060, 2026 0.054; K20 DEV +15.2%/yr, 2026 +3.3%/yr. Δ = ablated − base (negative = the group helps).

### 7a. Importance stability by year (XR_all gain share per fold)

| group | 2023 fold | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| momentum | 20.9% | 21.1% | 19.3% | 20.4% |
| volrisk | 26.6% | 24.4% | 24.1% | 23.7% |
| volume | 5.7% | 5.5% | 5.4% | 5.4% |
| delivery | 3.1% | 3.6% | 5.0% | 5.4% |
| market | 12.5% | 17.6% | 18.4% | 18.9% |
| xsrank | 14.3% | 13.0% | 13.4% | 11.9% |
| technical | 12.0% | 11.3% | 11.2% | 11.0% |
| other | 4.9% | 3.5% | 3.2% | 3.2% |

Top-8 features per fold (gain share):

* 2023: mom_12_1 6.2%, log_turn20 5.1%, max_ret_20 5.0%, age 4.9%, lo52_dist 4.8%, idio_vol_60 4.3%, vol_60 4.1%, min_ret_20 4.1%
* 2024: mom_12_1 6.5%, idio_vol_60 5.2%, log_turn20 5.0%, xr_hi52 4.3%, max_ret_20 4.2%, lo52_dist 4.0%, beta_60 3.6%, dist_sma200 3.5%
* 2025: mom_12_1 6.2%, idio_vol_60 5.8%, xr_hi52 4.9%, log_turn20 4.9%, max_ret_20 3.9%, hi52_dist 3.7%, vol_60 3.6%, lo52_dist 3.5%
* 2026: mom_12_1 6.6%, idio_vol_60 6.2%, log_turn20 4.9%, mkt_dist_sma200 4.3%, hi52_dist 4.2%, deliv_pct 3.9%, xr_hi52 3.9%, vol_60 3.5%

Fold-to-fold Spearman of the 52-feature importance vector: 2023~2024 0.94, 2023~2025 0.92, 2023~2026 0.90, 2024~2025 0.97, 2024~2026 0.95, 2025~2026 0.97.

### 7b. Univariate per-date IC of single features vs the XR target (DEV mean, non-overlap t; 2026 mean)

| feature | group | DEV IC (t) | 2026 IC (t) | IC vs raw r20 DEV |
|---|---|---|---|---|
| deliv_pct | delivery | +0.0437 (+5.84) | +0.0447 (+4.15) | +0.0468 |
| idio_vol_60 | volrisk | -0.0434 (-5.57) | -0.0033 (-1.22) | -0.0620 |
| hi52_dist | technical | +0.0425 (+2.96) | +0.0700 (+2.20) | +0.0491 |
| xr_hi52 | xsrank | +0.0425 (+2.96) | +0.0700 (+2.20) | +0.0491 |
| vol_60 | volrisk | -0.0419 (-5.90) | -0.0109 (-1.81) | -0.0624 |
| mom_12_1 | momentum | +0.0391 (+3.03) | +0.0873 (+3.18) | +0.0390 |
| atr_pct | volrisk | -0.0363 (-4.45) | +0.0004 (-0.93) | -0.0570 |
| vol_20 | volrisk | -0.0324 (-5.61) | -0.0244 (-4.50) | -0.0522 |
| xr_vol20 | xsrank | -0.0324 (-5.61) | -0.0244 (-4.50) | -0.0522 |
| log_turn20 | volume | +0.0297 (+9.71) | +0.0250 (+5.15) | +0.0527 |
| min_ret_20 | volrisk | +0.0276 (+4.81) | +0.0102 (+0.87) | +0.0415 |
| hl_range | technical | -0.0260 (-4.91) | -0.0056 (-2.30) | -0.0378 |
| max_ret_20 | volrisk | -0.0256 (-3.97) | -0.0264 (-4.61) | -0.0428 |
| age | other | +0.0219 (+3.05) | +0.0039 (+0.52) | +0.0254 |
| deliv_ratio | delivery | +0.0173 (+3.63) | +0.0220 (+3.25) | +0.0177 |
| xr_mom120 | xsrank | +0.0165 (+1.24) | +0.0459 (+1.04) | +0.0153 |

Partial IC of the delivery features vs the XR target after per-date rank-OLS on log_turn20, vol_20, mom_5 and volz_20:

| feature | DEV partial IC (t) | 2026 partial IC (t) | raw univariate DEV IC |
|---|---|---|---|
| deliv_pct | +0.0422 (+4.99) | +0.0425 (+3.93) | +0.0437 |
| deliv_z20 | +0.0133 (+2.35) | +0.0179 (+2.67) | +0.0165 |
| deliv_ratio | +0.0143 (+2.60) | +0.0173 (+3.18) | +0.0173 |
| xr_deliv_z | +0.0133 (+2.35) | +0.0179 (+2.67) | +0.0165 |

**Is NSE delivery data adding value? Yes, modestly and robustly.**

* deliv_pct is the strongest single feature for the relative target in DEV (IC +0.0437) and holds in 2026 (+0.0447). It survives controls for liquidity, volatility, reversal and volume (partial IC +0.0422, t +4.99).
* It is the only group whose removal hurts IC with a negative sign in every year 2023-2026.
* Its gain share rises from 3.1% (2023 fold) to 5.4% (2026 fold), and deliv_pct enters the 2026 top-8.
* The book-level effect is about 2-3%/yr on the top-20 book and 0.2-1.1%/yr on the avoid overlay: right-signed, mostly below significance.

Redundancy. Momentum, technicals, volume and the xs-rank copies each change IC by ≤ 0.002 in DEV. Momentum is the exception at the top tail: -3.2%/yr on the top-20 book in DEV (t -1.70) and -4.4% in 2026 (t -1.00). The model recovers the same information from overlapping features (e.g. hi52_dist ≡ xr_hi52 in per-date rank terms). The xs-rank group is a pure duplicate for a per-date rank target. Removing it is neutral in DEV and slightly positive in 2026. The vol/risk group helps the avoid side in DEV (ΔAUC_bot -0.0049, t -3.39).

## 8. Factor attribution: is the edge just low-vol / reversal?

### 8a. Long-short factor returns from the same universe (EW top-30% minus bottom-30%, h=20 step 5, 50 bps both legs, phase-averaged)

| factor | definition (long side) | DEV ann. (NW t) | 2026 ann. (NW t) |
|---|---|---|---|
| SIZE | small (−log_turn20) | -4.4% (-0.85) | +5.6% (+0.72) |
| MOM | high mom_12_1 | +13.2% (+2.75) | +25.7% (+2.84) |
| REV | 5d losers (−mom_5) | +1.1% (+0.53) | +2.8% (+0.62) |
| LOWVOL | low vol_20 | -1.5% (-0.24) | -18.9% (-1.81) |
| LOWBETA | low beta_60 | -1.8% (-0.30) | -9.6% (-0.71) |
| LOWIDIO | low idio_vol_60 | -0.4% (-0.06) | -22.9% (-2.26) |
| TREND | high dist_sma200 | +9.3% (+1.64) | +19.4% (+1.51) |
| MKT | EW universe book (not LS) | +12.3% (+1.13) | +10.1% (+0.43) |

### 8b. Regression of each book's daily excess-vs-random on the factors (OLS, NW t lag 20)

Spec 'brief' = SIZE, MOM, REV, LOWVOL, LOWBETA, MKT. Spec 'ext' adds LOWIDIO and TREND.

| book | window | spec | excess/yr | alpha/yr (NW t) | R² | factor t-stats |
|---|---|---|---|---|---|---|
| XR_all K20 | dev | brief | +15.2% | +14.1% (+3.33) | 0.10 | SIZE -2.6, MOM +0.5, REV +1.2, LOWVOL -3.4, LOWBETA +0.9, MKT -1.3 |
| XR_all K20 | dev | ext | +15.2% | +12.6% (+3.15) | 0.14 | SIZE -0.5, MOM +0.7, REV +2.1, LOWVOL -4.3, LOWBETA +0.9, MKT -1.0, LOWIDIO +3.9, TREND +1.2 |
| XR_all K20 | hold | brief | +3.3% | +10.4% (+1.13) | 0.22 | SIZE -4.7, MOM -3.0, REV +3.5, LOWVOL -2.3, LOWBETA +3.1, MKT +1.7 |
| XR_all K20 | hold | ext | +3.3% | +8.5% (+1.03) | 0.32 | SIZE -4.0, MOM +1.2, REV +0.4, LOWVOL -2.9, LOWBETA +5.0, MKT +1.0, LOWIDIO +0.6, TREND -4.8 |
| XR_all avoid30 | dev | brief | +3.1% | +2.9% (+3.87) | 0.61 | SIZE -6.0, MOM +0.9, REV +0.0, LOWVOL +5.0, LOWBETA +1.3, MKT -1.3 |
| XR_all avoid30 | dev | ext | +3.1% | +2.5% (+3.58) | 0.66 | SIZE -1.9, MOM +0.3, REV +1.6, LOWVOL -1.6, LOWBETA +1.0, MKT -0.8, LOWIDIO +6.6, TREND +1.9 |
| XR_all avoid30 | hold | brief | +0.6% | +2.7% (+3.76) | 0.74 | SIZE -5.7, MOM +0.2, REV +1.6, LOWVOL +4.8, LOWBETA +2.0, MKT +2.8 |
| XR_all avoid30 | hold | ext | +0.6% | +2.7% (+4.09) | 0.83 | SIZE -4.0, MOM +2.7, REV +1.0, LOWVOL -2.7, LOWBETA +4.4, MKT +2.4, LOWIDIO +8.0, TREND -2.3 |
| ENS3 K20 | dev | brief | +15.4% | +13.1% (+3.45) | 0.13 | SIZE -4.6, MOM +1.2, REV +1.9, LOWVOL -3.6, LOWBETA +1.1, MKT -1.8 |
| ENS3 K20 | dev | ext | +15.4% | +11.4% (+3.25) | 0.19 | SIZE -1.5, MOM +0.4, REV +3.6, LOWVOL -3.9, LOWBETA +0.7, MKT -1.4, LOWIDIO +4.5, TREND +2.2 |
| ENS3 K20 | hold | brief | -7.0% | +1.3% (+0.21) | 0.46 | SIZE -6.3, MOM -1.7, REV +5.5, LOWVOL -0.4, LOWBETA +2.0, MKT -0.9 |
| ENS3 K20 | hold | ext | -7.0% | +0.5% (+0.08) | 0.55 | SIZE -4.6, MOM +2.2, REV +3.6, LOWVOL -3.3, LOWBETA +3.5, MKT -1.5, LOWIDIO +2.3, TREND -4.0 |
| ENS3 avoid30 | dev | brief | +3.5% | +3.0% (+3.64) | 0.20 | SIZE -6.5, MOM +1.5, REV +2.0, LOWVOL +0.0, LOWBETA +0.4, MKT -1.9 |
| ENS3 avoid30 | dev | ext | +3.5% | +2.7% (+3.47) | 0.30 | SIZE -1.9, MOM +0.3, REV +4.3, LOWVOL -2.6, LOWBETA -0.2, MKT -1.5, LOWIDIO +5.0, TREND +2.1 |
| ENS3 avoid30 | hold | brief | +1.3% | +2.5% (+4.25) | 0.82 | SIZE -8.7, MOM +2.5, REV +4.5, LOWVOL +3.8, LOWBETA +3.4, MKT +1.8 |
| ENS3 avoid30 | hold | ext | +1.3% | +2.6% (+4.27) | 0.87 | SIZE -8.1, MOM +3.8, REV +4.0, LOWVOL -3.7, LOWBETA +5.6, MKT +1.9, LOWIDIO +7.0, TREND -0.1 |
| TSX_all K20 | dev | brief | +11.4% | +8.9% (+2.46) | 0.19 | SIZE -5.4, MOM +1.2, REV +3.0, LOWVOL -2.0, LOWBETA -0.9, MKT -3.4 |
| TSX_all K20 | dev | ext | +11.4% | +7.0% (+2.20) | 0.25 | SIZE -2.3, MOM +0.6, REV +4.5, LOWVOL -3.8, LOWBETA -1.1, MKT -3.0, LOWIDIO +5.0, TREND +1.6 |
| TSX_all K20 | hold | brief | -7.0% | -3.6% (-0.71) | 0.38 | SIZE -4.6, MOM -0.2, REV +4.1, LOWVOL -0.4, LOWBETA +0.4, MKT -1.6 |
| TSX_all K20 | hold | ext | -7.0% | -4.7% (-0.91) | 0.49 | SIZE -3.6, MOM +3.8, REV +2.0, LOWVOL -3.8, LOWBETA +1.6, MKT -2.2, LOWIDIO +3.6, TREND -5.6 |
| TSX_all avoid30 | dev | brief | +3.9% | +3.3% (+3.36) | 0.17 | SIZE -5.7, MOM +1.6, REV +1.9, LOWVOL -0.2, LOWBETA -0.4, MKT -2.3 |
| TSX_all avoid30 | dev | ext | +3.9% | +2.9% (+3.18) | 0.24 | SIZE -1.9, MOM +0.9, REV +2.9, LOWVOL -2.3, LOWBETA -0.9, MKT -1.9, LOWIDIO +4.0, TREND +1.4 |
| TSX_all avoid30 | hold | brief | +1.7% | +1.9% (+2.54) | 0.86 | SIZE -7.9, MOM +5.0, REV +3.9, LOWVOL +3.2, LOWBETA +4.2, MKT +1.4 |
| TSX_all avoid30 | hold | ext | +1.7% | +2.0% (+2.37) | 0.89 | SIZE -7.6, MOM +5.3, REV +2.8, LOWVOL -5.1, LOWBETA +5.8, MKT +1.3, LOWIDIO +9.7, TREND -0.7 |
| BAR_all K20 | dev | brief | +9.1% | +7.0% (+1.74) | 0.12 | SIZE -3.0, MOM +1.3, REV +2.2, LOWVOL -3.8, LOWBETA +2.9, MKT -1.3 |
| BAR_all K20 | dev | ext | +9.1% | +6.0% (+1.53) | 0.16 | SIZE -0.9, MOM -0.1, REV +3.6, LOWVOL -3.8, LOWBETA +2.4, MKT -1.0, LOWIDIO +3.1, TREND +3.5 |
| BAR_all K20 | hold | brief | -7.3% | -1.0% (-0.16) | 0.51 | SIZE -5.0, MOM -1.7, REV +6.0, LOWVOL -0.9, LOWBETA +2.5, MKT -3.1 |
| BAR_all K20 | hold | ext | -7.3% | -0.8% (-0.13) | 0.53 | SIZE -3.6, MOM -0.9, REV +6.4, LOWVOL -2.8, LOWBETA +3.2, MKT -2.9, LOWIDIO +2.0, TREND -0.3 |
| BAR_all avoid30 | dev | brief | +2.4% | +1.8% (+2.56) | 0.25 | SIZE -2.5, MOM +2.0, REV +2.4, LOWVOL -2.6, LOWBETA +1.1, MKT -0.6 |
| BAR_all avoid30 | dev | ext | +2.4% | +1.6% (+2.48) | 0.30 | SIZE -0.3, MOM -0.1, REV +4.0, LOWVOL -2.8, LOWBETA +0.4, MKT -0.2, LOWIDIO +2.9, TREND +3.6 |
| BAR_all avoid30 | hold | brief | +0.9% | +2.0% (+3.50) | 0.75 | SIZE -8.0, MOM +1.3, REV +3.6, LOWVOL +2.2, LOWBETA +2.0, MKT -0.3 |
| BAR_all avoid30 | hold | ext | +0.9% | +2.2% (+3.88) | 0.80 | SIZE -7.1, MOM +0.1, REV +5.7, LOWVOL -3.3, LOWBETA +3.2, MKT -0.3, LOWIDIO +5.1, TREND +2.0 |

### 8c. What the scores load on (per-date OLS of the score's pct rank on 7 characteristic pct ranks)

| score | window | log_turn20 | mom_12_1 | mom_5 | vol_20 | beta_60 | idio_vol_60 | dist_sma200 | mean xs R² |
|---|---|---|---|---|---|---|---|---|---|
| XR_all | DEV | +0.073 | +0.036 | -0.123 | +0.167 | -0.081 | -0.545 | +0.305 | 0.42 |
| XR_all | 2026 | +0.136 | +0.208 | -0.142 | +0.171 | -0.052 | -0.593 | -0.067 | 0.40 |
| TSX_all | DEV | +0.096 | +0.026 | -0.196 | +0.149 | +0.118 | -0.465 | +0.380 | 0.49 |
| TSX_all | 2026 | +0.389 | +0.218 | -0.142 | +0.009 | -0.106 | -0.469 | +0.159 | 0.72 |
| ENS3 | DEV | +0.064 | -0.001 | -0.220 | +0.281 | +0.030 | -0.550 | +0.334 | 0.45 |
| ENS3 | 2026 | +0.276 | +0.221 | -0.208 | +0.188 | -0.116 | -0.597 | +0.056 | 0.58 |

### 8d. Factor-neutral residual (FN) vs static factor composite (FC) books (K20 s5 and avoid30, 50 bps, PA excess vs random)

| score | DEV K20 (t) | 2026 K20 (t) | DEV avoid (t) | 2026 avoid (t) | DEV ic_xr | DEV AUC_top / AUC_bot |
|---|---|---|---|---|---|---|
| XR_all | +15.2% (+3.81) | +3.3% (+0.44) | +3.1% (+2.99) | +0.6% (+0.38) | 0.060 | 0.517 / 0.544 |
| XR_all_FN | +12.9% (+3.22) | +4.7% (+0.59) | +2.3% (+5.55) | +2.3% (+2.93) | 0.041 | 0.520 / 0.520 |
| XR_all_FC | +2.0% (+0.29) | -14.5% (-1.19) | +2.1% (+1.86) | +0.3% (+0.11) | 0.059 | 0.500 / 0.561 |
| ENS3 | +15.4% (+4.37) | -7.0% (-0.80) | +3.5% (+4.07) | +1.3% (+0.75) | 0.058 | 0.523 / 0.535 |
| ENS3_FN | +8.4% (+2.73) | +8.5% (+1.39) | +2.9% (+7.70) | +2.2% (+3.30) | 0.046 | 0.524 / 0.522 |
| ENS3_FC | +5.2% (+0.96) | -10.3% (-0.84) | +2.0% (+2.58) | +0.9% (+0.44) | 0.050 | 0.507 / 0.544 |
| TSX_all | +11.4% (+3.18) | -7.0% (-0.82) | +3.9% (+4.19) | +1.7% (+0.82) | 0.061 | 0.528 / 0.534 |
| TSX_all_FN | +8.7% (+2.90) | +11.0% (+2.04) | +2.9% (+8.10) | +2.2% (+3.70) | 0.046 | 0.525 / 0.520 |
| TSX_all_FC | +7.0% (+1.13) | -11.7% (-0.88) | +2.4% (+2.95) | +1.6% (+0.78) | 0.049 | 0.513 / 0.539 |

**Answer: no, the edge is not just low-vol or reversal.**

* In DEV the XR long book's alpha after the brief's five factors plus market is +14.1%/yr (t +3.33), with R² only 0.10.
* The book is *short* the low-vol factor and carries a small reversal loading. What it does load on is low *idiosyncratic* vol at a given total vol (score loading on idio_vol_60 -0.55, on vol_20 +0.17), plus trend (dist_sma200) and short-term reversal (mom_5).
* The static composite of exactly these loadings earns almost nothing on the long side (+2.0%/yr, t +0.29). The factor-neutral residual keeps 85% of the long excess in DEV.
* XR's AVOID overlay is largely factor-explained (R² 0.61 DEV, 0.74 2026). Its alpha after factors is +2.9% (t +3.87) in DEV and +2.7% (t +3.76) in 2026. In 2026 the raw avoid excess (+0.6%/yr) was masked by a big-cap (negative SIZE) loading in a small-cap year. Avoid alpha after factors, DEV / 2026: ENS3 +3.0% (t +3.64) / +2.5% (t +4.25); TSX_all +3.3% (t +3.36) / +1.9% (t +2.54); BAR_all +1.8% (t +2.56) / +2.0% (t +3.50).

## 9. Variants and multiple testing

* Walk-forward models trained: 12 (XR_all, BAR_all, TSX_all, XR_no_momentum, XR_no_volrisk, XR_no_volume, XR_no_delivery, XR_no_market, XR_no_xsrank, XR_no_technical, BAR_no_market, TSX_no_market), plus 1 single-fold verification run.
* Derived scores (no training): ENS3, ENS3_FC, ENS3_FN, ENS3_nomkt, ENS_BT, ENS_XB, ENS_XT, TSX_all_FC, TSX_all_FN, XR_all_FC, XR_all_FN.
* Distinct DEV strategy specifications at 50 bps: **102** (46 main + 56 K×step grid). The 80 bps re-costing, the holdout runs and the phase shifts are not counted as new specs.
* Label variants screened on event rates only: 10. Formal selection candidates: 7 (pre-declared).
* Null expectation of the max t over 102 independent tries: 3.04. Bonferroni one-sided 5%: 3.30 (this agent) and 3.93 (programme ~1190 specs). XR's DEV t 3.81 passes the agent-level hurdle but not the programme-level one. The selected ENS3 at 4.37 passes both and **still fails the holdout**. That is a concrete reminder that a DEV t from overlapping, regime-exposed books overstates evidence.

## 10. Candidate scorecards (pros / cons / verdict)

| candidate | pros | cons | verdict |
|---|---|---|---|
| XR_all (XR_neu regression, all features) | Regime-free label; stable importance (fold Spearman ≥ 0.90); DEV alpha after factors t 3.3; positive in 2026 in 8/8 K×step cells | 2026 edge small and insignificant (+3.3%/yr, t 0.44); avoid overlay weak in 2026 (t 0.38) | promising (as R2_rel) |
| BAR_all (A2 barrier binary) | Coherent classes (+1 nets +958 bps); decent avoid overlay in DEV | 61-87% of its gain importance is market timing; DEV edge vanishes without market features; 2026 −7.3%/yr | reject (alpha source) |
| TSX_all (market-excess trend scan) | Best IC on the XR yardstick in 2026; best single-model raw avoid t in DEV | Long book fails 2026 (−7.0%/yr); regime-conditional size/vol tilt; score 72% factor-explained in 2026 | weak (avoid input only) |
| ENS3 (rank average XR+BAR+TSX) | Highest DEV t (4.37), smoothest DEV excess | No paired DEV gain over XR (+0.1%/yr); 2026 −7.0%/yr, all phases and all K×step cells negative | reject |
| ENS_XT / ENS_XB / ENS_BT | ENS_XT has the best DEV IC (0.065) | Same 2026 failure (−5.5 to −10.3%/yr) | reject |
| *_FN avoid overlays (factor-neutral score, drop bottom 30%) | DEV t 5.5-8.1; 2026 +2.2-2.3%/yr with t 2.9-3.7 for all three models; DEV already prefers them | +2-3%/yr only; built during attribution (not in the pre-declared set) | promising |
| *_FN long books | Positive in 2026 in 8/8 cells | DEV lower than raw (paired −2 to −7%/yr); the 2026 gain is holdout-informed | hypothesis (pre-register) |
| *_no_market models | 2026 IC and books better; less regime tilt | DEV worse in 8 of 9 model-years for the BAR/TSX/ENS3 books; selected post hoc | hypothesis (pre-register) |

## 11. Recommendation for the label stack

1. **Primary selection label: XR_neu (h=20)**, the relative, beta/vol/size-neutral residual rank. Do not ensemble it with absolute or
   market-excess labels. They add no DEV return in paired tests and import a regime-conditional factor bet that cost ~10%/yr in 2026.
2. **Keep market/regime features out of the stock-selection model**, or treat their contribution as a timing bet owned by the
   regime layer (R2_regime) and sized explicitly. For XR the DEV cost of dropping them is -1.9%/yr (t -0.90) and the 2026 benefit is +5.8%/yr (t +0.99).
   For absolute labels they are the whole DEV edge.
3. **AVOID screen: drop the bottom 30% of a factor-neutralised model score.** In DEV the FN overlays have the highest t of all avoid
   variants. In 2026 they are the only avoid variants with t > 2 (+2.3%, +2.2%, +2.2%/yr). Expect ~+2-3%/yr over the EW universe, not more.
4. **Keep NSE delivery features.** They are the only group with a significant, every-year IC contribution, and deliv_pct is the best single
   feature for the relative target, distinct from liquidity and volatility.
5. **Drop redundant feature copies** (xr_* duplicates of per-date-rankable features). This is neutral to slightly positive and reduces
   the variant surface.
6. Pre-register for round 3 (fresh data only): FN long book vs raw XR, no-market XR vs XR. Both look better in 2026, but that is
   holdout-informed.

## 12. Lab issues found

* **Definition drift between agents, and what it reveals about model noise (MEDIUM).** R2_dual's XR_neu uses `0.5*beta_60+0.5`
  without clipping. R2_rel (and round-1 B_relative, and this report) clip beta_60 to [0,3] first. The labels barely differ: pct corr
  0.99986, and 0.47% of rows change 3-class. Yet the trained OOS scores correlate only 0.973 (max abs diff 0.08). A near-identical label
  therefore moves a LightGBM score about as much as many of the 'variants' being compared. Fix: put the canonical label builder in
  lablib, and treat score differences smaller than this seed/label noise as zero.
* **OLS neutralisation is not rank neutralisation (LOW-MEDIUM).** The XR_neu pct still has per-date rank IC +0.030 (t 9.7) with
  log_turn20 and −0.032 (t −5.6) with vol_20, both of which are OLS regressors. OLS removes the mean relation, but illiquid and high-vol
  names have more right-skewed returns, hence lower median residuals. The +1 class is therefore slightly more liquid and lower-vol than
  intended (R2_rel's tilt table shows the same: log_turn20 +0.08 z). If exact neutrality matters, neutralise in rank space or
  rank-normalise the residual within neutraliser buckets.
* **The NW t of per-date IC differences overstates significance on short windows (MEDIUM, method).** Overlapping 20d forward
  windows plus Bartlett lag 20 understate the long-run variance. In 2026, NW t 5.45 vs non-overlap t 1.31 for the same ΔIC. Report
  both, or use block bootstrap by month.
* **High DEV t can come from low tracking variance, not return (method).** ENS3's DEV t (4.37) beat XR's (3.81) with the same mean excess.
  Paired difference tests between candidates should accompany any 'highest t' selection rule.
* `L.event_report` puts rows with NaN mkt_dist_sma200 into 'bear' (round-1 issue, still present).
* `walk_forward2` has no hook for feature importance. I used a verified bit-identical copy (common.wf2_imp).

## 13. Files (all in this directory)

`common.py` (helpers, feature groups, verified walk-forward copy) · `s1_labels.py` (targets → labels.npz) · `s2_events.py` (event rates) · `s3_wf.py` (walk-forwards → wf_*.npz) · `s4_xs.py` (xs metrics, ensembles, score correlations → xs_daily_*.parquet) · `s5_sim.py` (Sim with cached random bands and phase averaging → daily_*.npz) · `s6_attrib.py` (factor series, FN/FC decomposition, regressions) · `s7_importance.py` · `s8_univariate.py` · `s9_composition.py` · `s10_paired.py` · `s12_report.py` (this report) · `results.json` (every number) · `log_*.txt`.
