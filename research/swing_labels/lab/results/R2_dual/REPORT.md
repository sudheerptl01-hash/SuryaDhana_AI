# R2_dual — "both conditions must accept" (relative AND absolute), formalised and tested

Lab v2 (no sector data, ETFs excluded, rebuilt `elig_base`). Universe U = `elig_base`. Entry at open[t+1], exit at close[t+h]. Labels are NaN where `fw.ok(h)` is false. Filters choose samples and never change label values. Models: `L.walk_forward2` (yearly expanding folds 2023-2026, embargo h+2, date_step 2, 52 features, n_jobs 2). Learnability: `L.xs_metrics`, per-date IC/AUC only (no pooled AUC). Investability: `L.Sim`, daily mark-to-market, slot sizing, staggered sleeves, h=20, step 5, top-20 unless stated, horizon-matched random baseline on the same mask (5 seeds), NW t of the daily excess with lag 20. Costs: 50 bps central and 80 bps stress. DEV = 2023-01-01 to 2025-12-31 (exits by DEV end). HOLDOUT = 2026-01-01 to 2026-10-14, reported separately and never used for selection. The holdout is lightly contaminated because round 1 reported 2026.

## Verdict

**No.** Requiring an absolute condition as well as a relative one does not make more money and does not reduce drawdowns compared with a pure-relative label. This holds once the comparison controls for the model's loss function. DUAL is roughly equal to the same-loss pure-relative model. Its apparent gain over the XR_neu regression comes from the loss function, not from the absolute condition.

* **Label-side DUAL vs pure relative with the same loss (binary top-30%, M_RUP).** The comparison is averaged over 5 signal-calendar phases (K20, step 5, 50 bp). On DEV, DUAL minus RUP is +0.5%/yr (range -1.7% to +1.9%, 4/5 phases positive, mean NW t 0.25). In the 2026 holdout it is +3.0%/yr (range -8.9% to +9.6%, mean t 0.43). The path version is worse: DUALP minus RUP is -4.6%/yr on DEV (0/5 phases positive). Over the 8-cell K x step grid at phase 0, DUAL beats RUP in 3/8 DEV cells and DUALP in 1/8. The DUAL and RUP model scores have a 0.90 per-date rank correlation. **The absolute leg is neutral at best, inside noise in both windows.**
* **DUAL does beat the pure-relative regression model (XR_neu, `REL`):** +5.1%/yr on DEV (5/5 phases, mean t 1.39; 8/8 grid cells). That gain comes entirely from switching the target from a full-rank regression to a top-tail classifier. RUP minus REL is +4.6%/yr (5/5 phases, mean t 1.34).
* **No fewer drawdowns.** Phase-mean DEV maxDD: REL -29.5%, RUP -31.0%, DUAL -32.3%, DUALP -31.8%. Book beta at phase 0: REL 1.26, RUP 1.33, DUAL 1.35. The top-tail books carry more beta than REL, and the absolute leg does not lower it on DEV.
* **Two-model ANDs do not help either.** rank(REL)+rank(ABS) gives +1.1%/yr on DEV vs REL and -3.3%/yr in the holdout (0/8 grid cells positive in the holdout). P(top30) x P(abs up) vs RUP gives -4.1%/yr on DEV (t -1.66). 'REL top-20 only among ABS-model top half' gives -0.8%/yr on DEV.
* **Input-side gates (sample filters) do not add skill on DEV either.** Inside close>sma200 AND xr_mom60>0.7, a random pick earns about 1%/yr more than in U (t 0.4), and the relative model inside the gate is not better than the relative model on all of U. In the 2026 holdout the trend gate by itself was worth +15%/yr (t 2.1). That is not selectable on DEV, and the model added nothing inside the gate.
* **Avoid side.** The explicit DUAL_down model is accurate as a classifier (per-date AUC 0.57 DEV / 0.56 holdout). As an avoid overlay it gives +1.9%/yr vs the universe on DEV (t 1.6) and **fails in 2026** with -2.6%/yr (0/5 phases positive). REL_down behaves the same. The robust avoid overlay is to drop the 30% of names with the lowest P(relative top-30): +3.3%/yr on DEV (t 4.6) and +5.8%/yr in 2026 (t 6.0), 5/5 phases in both windows. The DUAL-up version of the same overlay is slightly worse: +3.2% / +5.0%.

**Recommendation:** keep the label purely relative. Use XR_neu residual ranks, and train the selection model as a **binary top-30% classifier** (or blend it with the XR_neu regression score). Use **low P(top-30)** as the avoid screen. Put the absolute or market condition in a separate regime/exposure layer (R2_regime). It does not belong in the stock label: there it only adds market beta and timing information that a cross-sectional book cannot use.

Variants tried by this agent: 11 walk-forward models, 130 distinct DEV book configurations (each also run at 80 bps and on the holdout), and about 56 label variants screened on event rates (tau x q x h grid of 42, 3 barrier geometries with their DUALP versions, and 8 base labels). Under the null, the expected maximum t of 130 tries is about 2.6. For about 730 programme-wide tries (including round 1) it is about 3.2. No DUAL-vs-relative paired t comes anywhere close. On top of that, the signal-calendar phase alone moves a K20 book's 2026 CAGR by 10-14 pp (section 4.7), so single-phase holdout differences of a few %/yr are noise.

## 1. Label definitions (h = 20 unless stated)

| id | family | formula (r = open[t+1] -> close[t+h], adjusted; NaN unless fw.ok(h)) |
|---|---|---|
| REL (XR_neu) | pure relative | per date: winsorise r at 1/99%, OLS on [1, 0.5*beta_60+0.5, vol_20, log_turn20] over U; residual percentile pct; +1 pct>0.7, -1 pct<=0.3, else 0 |
| ABS | pure absolute | +1 r > +50 bp, -1 r < -50 bp, else 0 (cost dead zone) |
| BAR (A2) | pure absolute, path | L.barrier_labels(h=20, pt=3.0 ATR, sl=1.5 ATR, tau 50 bp); stop checked first, gap fills |
| DUAL | label-side AND | +1 if REL=+1 AND r > +tau; -1 if REL=-1 AND r < -tau; else 0; tau = 50 bp (= covers the 50 bp round trip) |
| DUALP | label-side AND, path | +1 if REL=+1 AND BAR=+1; -1 if REL=-1 AND BAR=-1; else 0 |
| DUAL_t300 | stricter AND | as DUAL with tau = 300 bp |

Models (walk_forward2; a binary target is the event vs the rest): `M_REL` = regression on pct-0.5. `M_RUP` = P(REL=+1), the **same-loss pure-relative control**. `M_RDN` = P(REL=-1). `M_ABS` = P(r>50bp). `M_BAR` = P(BAR=+1). `M_DUAL`, `M_DUALP`, `M_DUALt300` = P(+1). `M_DDN` = P(DUAL=-1), the DUAL avoid model. `M_DUALmc` = multiclass DUAL, scored P(+1)-P(-1). `M_RELG` = M_REL trained and scored only inside the input gate G_trend. Combinations: SUM_REL_ABS = rank(M_REL)+rank(M_ABS). SUM_REL_BAR. SUM_REL_DUAL. SUM_REL_RUP (the pure-relative control for SUM_REL_DUAL). PROD_RUP_ABS = P(top30) x P(r>50bp). AND_REL_ABS50 = M_REL top-20 among names whose M_ABS is in the top half that day.

## 2. Event rates — the DUAL +1 share now moves with the market

| label | +1 | 0 | -1 | monthly +1 sd | monthly min | monthly max | corr(daily +1 share, N500 same window) DEV | +1 share per +10% mkt | +1 share, mkt window up | mkt window down | mkt window < -5% | corr monthly +1 vs N500 month |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REL | 30.0% | 40.0% | 30.0% | 0.0% | 30.0% | 30.1% | 0.04 | +0.0% | 30.0% | 30.0% | 30.0% | 0.04 |
| ABS | 47.0% | 4.3% | 48.7% | 17.5% | 11.7% | 75.3% | 0.87 | +48.1% | 60.2% | 27.4% | 11.9% | 0.47 |
| BAR | 36.7% | 1.6% | 61.7% | 14.9% | 13.0% | 65.6% | 0.71 | +38.3% | 46.7% | 22.4% | 10.5% | 0.63 |
| DUAL | 27.2% | 45.4% | 27.3% | 4.2% | 11.4% | 30.1% | 0.70 | +10.1% | 29.7% | 23.3% | 11.9% | 0.42 |
| DUALP | 20.5% | 52.2% | 27.3% | 4.9% | 9.8% | 28.4% | 0.57 | +11.0% | 23.3% | 16.3% | 8.6% | 0.66 |

Rows are U samples from 2021 to 2026. Daily statistics are DEV dates. The market window is the Nifty 500 open on the row's t+1 date to the close on its t+h date, the same executable window as the stock.

**Reading:** by construction REL has a constant 30% +1 share (corr 0.04). Adding the absolute leg (DUAL) makes the share move with the market: corr 0.70, and +10 pp of share for every +10% of market window return. The share falls from 29.7% in up windows to 23.3% in down windows and to 11.9% when the market window falls more than 5%. Its level dependence is still about 5x smaller than pure ABS (slope 48 pp per 10%), because the relative leg caps the share at 30%.

| label | +1 2021 | +1 2022 | +1 2023 | +1 2024 | +1 2025 | +1 2026 | -1 2021 | -1 2022 | -1 2023 | -1 2024 | -1 2025 | -1 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REL | 30.1% | 30.1% | 30.1% | 30.0% | 30.0% | 30.0% | 29.9% | 29.9% | 30.0% | 30.0% | 30.0% | 30.0% |
| ABS | 46.5% | 43.6% | 57.6% | 45.6% | 42.5% | 46.6% | 49.1% | 52.5% | 37.7% | 50.2% | 52.9% | 49.3% |
| BAR | 37.9% | 35.6% | 46.4% | 33.8% | 32.5% | 36.0% | 60.6% | 62.9% | 51.6% | 64.8% | 65.8% | 62.5% |
| DUAL | 28.6% | 25.5% | 29.4% | 27.0% | 26.3% | 27.4% | 28.1% | 27.2% | 26.2% | 27.6% | 28.1% | 27.0% |
| DUALP | 21.5% | 19.4% | 23.3% | 19.5% | 19.4% | 20.7% | 27.5% | 27.1% | 26.4% | 27.7% | 28.0% | 27.2% |

| label (+1 / -1) | bull_up20 | bull_dn20 | bear_up20 | bear_dn20 | liq T1 (low) | liq T2 | liq T3 (high) |
|---|---|---|---|---|---|---|---|
| REL | 30.0% / 30.0% | 30.0% / 30.0% | 30.0% / 30.0% | 30.0% / 30.0% | 29.4% / 31.9% | 30.9% / 31.0% | 29.9% / 27.0% |
| ABS | 44.4% / 51.2% | 44.8% / 50.7% | 55.5% / 40.3% | 54.4% / 41.9% | 45.4% / 50.5% | 46.6% / 49.2% | 49.1% / 46.2% |
| BAR | 35.2% / 63.2% | 35.2% / 63.0% | 41.8% / 56.7% | 41.2% / 57.4% | 35.9% / 62.5% | 36.7% / 61.7% | 37.5% / 60.9% |
| DUAL | 27.3% / 28.4% | 26.9% / 27.7% | 28.9% / 26.2% | 26.5% / 23.6% | 26.2% / 28.7% | 28.0% / 28.5% | 27.5% / 24.8% |
| DUALP | 20.6% / 28.1% | 20.1% / 27.5% | 21.6% / 26.6% | 20.1% / 25.0% | 19.7% / 28.8% | 21.2% / 28.4% | 20.6% / 24.8% |

Regimes are measured at the signal date (N500 vs its 200dma, and N500 20d momentum). Signal-date regime barely moves the DUAL share (26.5-28.9%). What moves it is the realised market path over the window (table above), and that is unknown at entry.

**What the absolute leg removes from REL +1.** Overall 9.4% of REL +1 labels become 0. By year: 2021 5.0%, 2022 15.2%, 2023 2.3%, 2024 10.1%, 2025 12.5%, 2026 8.6%. The removed rows are relative winners that lost money: mean net -336 bps, mean residual +568 bps, beta 1.26. The kept rows have mean net +1382 bps and beta 1.17. At h=10, 11.1% are removed.

### 2a. Label / P&L coherence (mean net return per class, net = r - 50 bp)

| label | +1 net bps (hit) 2021-25 | 0 | -1 | +1 net 2026 | 0 2026 | -1 2026 | +1 resid bps | -1 resid bps |
|---|---|---|---|---|---|---|---|---|
| REL | +1206 (90%) | -73 (45%) | -938 (6%) | +1299 | -60 | -942 | +1118 | -971 |
| ABS | +966 (100%) | -50 (0%) | -824 (0%) | +1068 | -50 | -836 | +633 | -601 |
| BAR | +943 (92%) | -50 (0%) | -479 (22%) | +1041 | -50 | -463 | +604 | -355 |
| DUAL | +1369 (100%) | -78 (44%) | -1038 (0%) | +1451 | -43 | -1093 | +1175 | -992 |
| DUALP | +1457 (98%) | +59 (51%) | -1011 (2%) | +1539 | +92 | -1038 | +1215 | -985 |

All labels are coherent with P&L by construction. DUAL +1 is 100% profitable net by definition, and its spread (+1 minus -1) is the widest. That is a mechanical consequence of conditioning on the outcome and says nothing about predictability (section 3).

### 2b. Sensitivity map: how DUAL event rates move with tau (absolute hurdle), q (relative cut) and h

| h | q | tau bp | +1 share DEV | daily sd | corr mkt | +1 in up windows | +1 in down windows | +1 share 2026 | corr mkt 2026 | +1 mean net bps | -1 share | -1 corr mkt | -1 mean net bps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20 | 0.2 | 0 | 19.2% | 2.5% | 0.56 | 20.0% | 18.0% | 19.3% | 0.61 | +1635 | 19.3% | -0.46 | -1161 |
| 20 | 0.2 | 50 | 19.1% | 2.7% | 0.58 | 20.0% | 17.7% | 19.2% | 0.62 | +1645 | 19.2% | -0.49 | -1170 |
| 20 | 0.2 | 500 | 17.2% | 4.7% | 0.75 | 19.6% | 13.3% | 17.5% | 0.77 | +1804 | 15.8% | -0.72 | -1335 |
| 20 | 0.3 | 0 | 27.6% | 5.3% | 0.67 | 29.8% | 24.1% | 27.6% | 0.72 | +1351 | 27.7% | -0.60 | -1023 |
| 20 | 0.3 | 25 | 27.4% | 5.4% | 0.68 | 29.8% | 23.7% | 27.5% | 0.73 | +1359 | 27.5% | -0.61 | -1030 |
| 20 | 0.3 | 50 | 27.2% | 5.6% | 0.70 | 29.7% | 23.3% | 27.3% | 0.74 | +1369 | 27.3% | -0.63 | -1038 |
| 20 | 0.3 | 100 | 26.8% | 5.9% | 0.72 | 29.6% | 22.3% | 27.0% | 0.76 | +1389 | 26.7% | -0.65 | -1056 |
| 20 | 0.3 | 200 | 25.9% | 6.7% | 0.76 | 29.4% | 20.4% | 26.3% | 0.79 | +1434 | 25.5% | -0.70 | -1098 |
| 20 | 0.3 | 300 | 24.9% | 7.3% | 0.79 | 29.1% | 18.3% | 25.4% | 0.81 | +1484 | 24.0% | -0.73 | -1146 |
| 20 | 0.3 | 500 | 22.7% | 8.5% | 0.83 | 27.9% | 14.4% | 23.3% | 0.86 | +1597 | 20.7% | -0.78 | -1257 |
| 20 | 0.4 | 0 | 34.5% | 8.7% | 0.77 | 39.2% | 27.2% | 34.8% | 0.81 | +1184 | 34.7% | -0.69 | -939 |
| 20 | 0.4 | 50 | 33.9% | 9.1% | 0.79 | 38.9% | 25.8% | 34.2% | 0.82 | +1209 | 33.9% | -0.71 | -959 |
| 20 | 0.4 | 500 | 26.5% | 12.0% | 0.84 | 33.8% | 14.9% | 26.3% | 0.91 | +1484 | 24.1% | -0.81 | -1210 |
| 10 | 0.2 | 0 | 19.1% | 2.6% | 0.59 | 20.0% | 17.9% | 19.3% | 0.48 | +1093 | 19.2% | -0.45 | -867 |
| 10 | 0.2 | 50 | 18.9% | 2.9% | 0.62 | 20.0% | 17.4% | 19.1% | 0.52 | +1105 | 19.0% | -0.49 | -875 |
| 10 | 0.2 | 500 | 15.5% | 5.7% | 0.79 | 18.9% | 10.7% | 15.4% | 0.76 | +1296 | 13.5% | -0.75 | -1081 |
| 10 | 0.3 | 0 | 27.2% | 5.6% | 0.71 | 29.8% | 23.6% | 27.4% | 0.63 | +902 | 27.8% | -0.57 | -760 |
| 10 | 0.3 | 25 | 27.0% | 5.9% | 0.72 | 29.7% | 23.1% | 27.1% | 0.64 | +911 | 27.5% | -0.58 | -766 |
| 10 | 0.3 | 50 | 26.7% | 6.1% | 0.73 | 29.7% | 22.5% | 26.8% | 0.66 | +922 | 27.2% | -0.60 | -775 |
| 10 | 0.3 | 100 | 26.1% | 6.7% | 0.75 | 29.5% | 21.2% | 26.2% | 0.69 | +943 | 26.4% | -0.64 | -793 |
| 10 | 0.3 | 200 | 24.7% | 7.6% | 0.78 | 29.1% | 18.5% | 24.6% | 0.74 | +990 | 24.5% | -0.70 | -839 |
| 10 | 0.3 | 300 | 23.1% | 8.4% | 0.80 | 28.3% | 15.9% | 22.6% | 0.79 | +1045 | 22.1% | -0.75 | -896 |
| 10 | 0.3 | 500 | 19.4% | 9.1% | 0.82 | 25.1% | 11.3% | 18.5% | 0.85 | +1182 | 16.8% | -0.79 | -1036 |
| 10 | 0.4 | 0 | 34.1% | 9.2% | 0.77 | 39.1% | 27.0% | 34.0% | 0.72 | +787 | 35.1% | -0.66 | -693 |
| 10 | 0.4 | 50 | 33.1% | 9.8% | 0.79 | 38.8% | 25.2% | 32.7% | 0.76 | +812 | 33.9% | -0.69 | -715 |
| 10 | 0.4 | 500 | 21.3% | 11.5% | 0.83 | 28.3% | 11.4% | 20.2% | 0.89 | +1137 | 19.0% | -0.81 | -1012 |

A smooth plateau with no cliffs. Raising tau from 0 to 500 bp (q=0.3, h=20) cuts the +1 share from 27.6% to 22.7%. Market dependence rises from corr 0.67 to 0.83, and the down-window +1 share falls from 24.1% to 14.4%. Widening q to 0.4 raises market dependence further (corr 0.77-0.84). Narrowing it to 0.2 lowers it (0.56-0.75). h=10 behaves like h=20 with slightly higher corr. The stricter the absolute hurdle, the more the label becomes a market-timing label.

| barrier pt/sl ATR | BAR +1 share | BAR corr mkt | DUALP +1 share | DUALP corr mkt | DUALP +1 net bps | DUALP -1 share |
|---|---|---|---|---|---|---|
| 3.0/1.5 | 37.3% | 0.71 | 20.6% | 0.57 | +1457 | 27.3% |
| 2.0/2.0 | 49.3% | 0.71 | 24.2% | 0.56 | +1371 | 24.7% |
| 2.0/1.0 | 34.5% | 0.57 | 17.2% | 0.47 | +1458 | 26.2% |

Overlap autocorrelation (lag 1, within entity): REL 0.84, DUAL 0.83, DUALP 0.80. At lag 5: REL 0.61, DUAL 0.60. Overlapping 20d labels give about 1/20 independent observations per row, so every t-stat here is either NW (lag 20) or non-overlapping.

## 3. Learnability (cross-sectional, walk-forward OOS)

| model | IC vs resid DEV (t) | IC vs resid 2026 (t) | IC 2023/24/25 | IC vs raw r DEV/2026 | AUC REL+1 DEV/2026 | AUC DUAL+1 | AUC DUALP+1 | AUC ABS+1 | AUC REL-1 | AUC DUAL-1 |
|---|---|---|---|---|---|---|---|---|---|---|
| M_REL | 0.063 (6.6) | 0.057 (3.7) | 0.026 / 0.091 / 0.072 | 0.074 / 0.049 | 0.518 / 0.504 | 0.525 / 0.502 | 0.530 / 0.506 | 0.542 / 0.519 | 0.545 / 0.555 | 0.543 / 0.550 |
| M_RUP | 0.035 (3.1) | 0.079 (6.2) | 0.022 / 0.064 / 0.018 | 0.030 / 0.093 | 0.542 / 0.563 | 0.544 / 0.566 | 0.545 / 0.564 | 0.521 / 0.557 | 0.492 / 0.516 | 0.490 / 0.517 |
| M_DUAL | 0.038 (4.0) | 0.081 (6.4) | 0.030 / 0.064 / 0.021 | 0.034 / 0.085 | 0.543 / 0.559 | 0.545 / 0.564 | 0.546 / 0.560 | 0.523 / 0.552 | 0.495 / 0.523 | 0.492 / 0.517 |
| M_DUALP | 0.031 (3.6) | 0.076 (5.6) | 0.024 / 0.054 / 0.016 | 0.025 / 0.085 | 0.538 / 0.558 | 0.539 / 0.563 | 0.547 / 0.570 | 0.518 / 0.551 | 0.492 / 0.519 | 0.490 / 0.514 |
| M_DUALt300 | 0.030 (3.0) | 0.075 (5.7) | 0.019 / 0.057 / 0.012 | 0.021 / 0.079 | 0.544 / 0.560 | 0.545 / 0.564 | 0.545 / 0.560 | 0.516 / 0.548 | 0.486 / 0.516 | 0.482 / 0.509 |
| M_DUALmc | 0.063 (7.0) | 0.059 (5.3) | 0.026 / 0.093 / 0.070 | 0.073 / 0.052 | 0.517 / 0.503 | 0.522 / 0.501 | 0.525 / 0.503 | 0.541 / 0.520 | 0.547 / 0.559 | 0.546 / 0.556 |
| M_ABS | 0.052 (6.5) | 0.049 (3.8) | 0.025 / 0.065 / 0.067 | 0.066 / 0.034 | 0.524 / 0.498 | 0.527 / 0.499 | 0.527 / 0.499 | 0.536 / 0.515 | 0.529 / 0.554 | 0.530 / 0.547 |
| M_BAR | 0.032 (4.9) | 0.044 (3.7) | 0.012 / 0.044 / 0.041 | 0.036 / 0.033 | 0.515 / 0.504 | 0.515 / 0.502 | 0.523 / 0.512 | 0.521 / 0.508 | 0.517 / 0.543 | 0.520 / 0.535 |
| M_RDN | 0.060 (7.5) | 0.025 (2.4) | 0.017 / 0.078 / 0.086 | 0.081 / 0.001 | 0.488 / 0.466 | 0.496 / 0.461 | 0.502 / 0.465 | 0.542 / 0.488 | 0.573 / 0.561 | 0.571 / 0.554 |
| M_DDN | 0.058 (6.8) | 0.013 (2.3) | 0.013 / 0.076 / 0.084 | 0.078 / -0.003 | 0.487 / 0.459 | 0.493 / 0.454 | 0.498 / 0.457 | 0.539 / 0.486 | 0.571 / 0.556 | 0.572 / 0.556 |
| M_RELG | 0.055 (4.5) | 0.056 (2.4) | 0.040 / 0.056 / 0.067 | 0.067 / 0.059 | 0.519 / 0.516 | 0.522 / 0.512 | 0.520 / 0.513 | 0.533 / 0.531 | 0.536 / 0.552 | 0.535 / 0.558 |

Down models (M_RDN, M_DDN) are scored as -P(down) for IC, and as P(down) for the -1 AUCs. Every AUC is a per-date cross-sectional AUC averaged over dates, and t-stats use every 20th date. M_RELG is scored only inside G_trend.

**Reading:** the DUAL model is learnable (AUC on DUAL+1 0.545 DEV / 0.564 2026), but **no more learnable than the pure-relative binary model**. M_RUP scores 0.544 / 0.566 on the DUAL+1 event itself, and its scores have a 0.90 rank correlation with M_DUAL. Both binary-up models have lower full-cross-section IC than the regression M_REL (0.035-0.039 vs 0.063 DEV), because they ignore the loser tail (AUC REL-1 below 0.5). Their 2026 IC is higher (0.079-0.081 vs 0.057). The absolute models carry raw-return IC on DEV (0.066) that collapses in 2026 (0.034). The down models classify down events robustly (AUC 0.57 / 0.56) but their full-cross-section IC collapses in 2026 (0.013-0.025).

| model | decile | net bps DEV | resid bps DEV | DUAL+1 rate DEV | net bps 2026 | resid bps 2026 | DUAL+1 rate 2026 |
|---|---|---|---|---|---|---|---|
| M_REL | top10 | +152 | +67 | 30.7% | +94 | +25 | 28.5% |
| M_REL | bot10 | -39 | -90 | 25.2% | +13 | -113 | 26.7% |
| M_RUP | top10 | +167 | +88 | 33.0% | +241 | +140 | 35.4% |
| M_RUP | bot10 | -1 | -84 | 22.3% | -119 | -161 | 19.0% |
| M_DUAL | top10 | +172 | +93 | 33.3% | +212 | +119 | 34.6% |
| M_DUAL | bot10 | -15 | -95 | 22.0% | -65 | -145 | 20.4% |
| M_DUALP | top10 | +160 | +78 | 32.2% | +221 | +124 | 34.7% |
| M_DUALP | bot10 | -5 | -91 | 22.2% | -61 | -134 | 20.0% |
| M_ABS | top10 | +147 | +52 | 30.1% | +16 | -24 | 25.2% |
| M_ABS | bot10 | -49 | -97 | 23.5% | +18 | -99 | 26.6% |
| M_DDN | top10 | +98 | -5 | 24.7% | -25 | -71 | 21.0% |
| M_DDN | bot10 | -21 | -75 | 26.9% | +96 | -31 | 30.6% |
| universe | all | +80 | 0 | 27.4% | +84 | 0 | 27.4% |

For M_DDN, 'top10' means lowest P(down) and 'bot10' means highest P(down), the names an avoid overlay would drop. In 2026 those names had a raw net return (+96 bps) above the universe average even though their residual was negative. That is why the DUAL-down avoid overlay fails (section 4.4).

| score A | score B | mean per-date rank corr (DEV) |
|---|---|---|
| DUAL | RUP | 0.90 |
| DUAL | REL | 0.59 |
| DUALP | RUP | 0.81 |
| DUALt300 | RUP | 0.87 |
| RUP | REL | 0.61 |
| ABS | REL | 0.69 |
| DDN | RDN | 0.92 |
| DDN | DUAL | 0.10 |
| REL | RELG | 0.78 |

## 4. Investability (L.Sim, h=20)

### 4.1 Long top-20, step 5, U — DEV (selection) and 2026 holdout (report only)

| score | DEV CAGR 50bp | excess vs random | NW t | maxDD | Sharpe | beta | DEV CAGR 80bp | excess 80bp | 2026 CAGR 50bp | 2026 excess | 2026 t | 2026 maxDD | DEV vs REL /yr | DEV vs RUP /yr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REL | 28.7% | +16.9% | 3.18 | -29.5% | 1.33 | 1.26 | 24.1% | +16.3% | 13.6% | +6.8% | 0.94 | -18.2% | – | – |
| RUP | 33.7% | +21.9% | 3.62 | -32.6% | 1.40 | 1.33 | 28.9% | +21.1% | 25.2% | +18.3% | 2.32 | -17.1% | +4.3% | – |
| DUAL | 31.4% | +19.6% | 3.55 | -33.6% | 1.32 | 1.35 | 26.7% | +18.9% | 14.8% | +7.9% | 1.16 | -17.1% | +2.6% | -1.7% |
| DUALP | 28.8% | +17.0% | 3.35 | -31.8% | 1.26 | 1.29 | 24.2% | +16.4% | 29.0% | +22.1% | 2.64 | -16.5% | +0.3% | -4.0% |
| DUALt300 | 33.4% | +21.6% | 3.36 | -33.4% | 1.40 | 1.30 | 28.6% | +20.9% | 19.9% | +13.0% | 1.53 | -16.0% | +4.1% | -0.3% |
| DUALmc | 26.5% | +14.7% | 2.84 | -28.7% | 1.31 | 1.23 | 21.9% | +14.2% | 13.3% | +6.4% | 1.11 | -16.4% | -2.1% | -6.4% |
| ABS | 21.1% | +9.3% | 2.06 | -32.8% | 1.06 | 1.27 | 16.7% | +9.0% | 3.5% | -3.4% | -0.35 | -14.6% | -6.3% | -10.6% |
| BAR | 20.7% | +8.9% | 2.00 | -27.5% | 1.09 | 1.17 | 16.4% | +8.6% | 6.6% | -0.3% | -0.06 | -15.6% | -6.9% | -11.2% |
| SUM_REL_ABS | 30.2% | +18.4% | 3.63 | -29.7% | 1.40 | 1.29 | 25.6% | +17.8% | 10.4% | +3.5% | 0.35 | -16.4% | +1.1% | -3.2% |
| SUM_REL_BAR | 29.1% | +17.3% | 3.64 | -26.9% | 1.39 | 1.23 | 24.5% | +16.7% | 5.8% | -1.0% | -0.12 | -16.6% | +0.1% | -4.2% |
| PROD_RUP_ABS | 28.6% | +16.8% | 3.17 | -32.5% | 1.25 | 1.31 | 24.0% | +16.2% | 22.1% | +15.2% | 2.04 | -14.7% | +0.2% | -4.1% |
| AND_REL_ABS50 | 27.8% | +16.0% | 3.00 | -29.3% | 1.30 | 1.26 | 23.2% | +15.4% | 16.6% | +9.7% | 1.25 | -18.0% | -0.8% | -5.1% |
| SUM_REL_DUAL | 32.3% | +20.5% | 3.57 | -33.0% | 1.39 | 1.31 | 27.6% | +19.8% | 23.5% | +16.6% | 2.32 | -17.9% | +3.1% | -1.3% |
| SUM_REL_RUP | 31.6% | +19.8% | 3.96 | -30.5% | 1.38 | 1.27 | 26.9% | +19.1% | 24.6% | +17.7% | 2.59 | -17.4% | +2.5% | -1.8% |

Random baseline (same mask, 5 seeds): DEV 11.8% at 50 bp (sd 2.9%), 7.8% at 80 bp. 2026: 6.9% at 50 bp. The 2026 CAGR is annualised over 9.5 months. Exposure is about 0.93 for all books.

### 4.2 Paired daily differences (the decisive test), 50 bp, K20 step 5

| pair | window | ann. diff | NW t | daily corr | N500>200dma days | N500<200dma days | N500 20d up | N500 20d down |
|---|---|---|---|---|---|---|---|---|
| DUAL - REL | dev | +2.6% | 0.67 | 0.950 | +2.7% | +2.2% | +2.8% | +2.1% |
| DUAL - RUP | dev | -1.7% | -0.61 | 0.975 | -2.0% | -0.6% | -3.2% | +0.9% |
| DUALP - REL | dev | +0.3% | 0.10 | 0.947 | +0.8% | -1.9% | -0.7% | +2.3% |
| DUALP - RUP | dev | -4.0% | -1.09 | 0.963 | -3.8% | -4.8% | -6.7% | +1.0% |
| DUALt300 - RUP | dev | -0.3% | -0.08 | 0.972 | +0.0% | -1.6% | -2.0% | +2.8% |
| DUALt300 - DUAL | dev | +1.5% | 0.59 | 0.978 | +2.0% | -1.0% | +1.2% | +2.0% |
| RUP - REL | dev | +4.3% | 1.10 | 0.957 | +4.6% | +2.8% | +6.0% | +1.3% |
| ABS - REL | dev | -6.3% | -1.78 | 0.938 | -6.7% | -4.7% | -7.6% | -4.0% |
| BAR - REL | dev | -6.9% | -1.74 | 0.932 | -8.6% | +1.5% | -12.6% | +3.5% |
| SUM_REL_ABS - REL | dev | +1.1% | 0.41 | 0.972 | +0.5% | +4.1% | -0.6% | +4.2% |
| SUM_REL_BAR - REL | dev | +0.1% | 0.04 | 0.965 | -0.6% | +3.8% | -4.0% | +7.5% |
| AND_REL_ABS50 - REL | dev | -0.8% | -1.43 | 0.998 | -0.3% | -2.9% | -0.8% | -0.7% |
| PROD_RUP_ABS - RUP | dev | -4.1% | -1.66 | 0.982 | -5.6% | +3.0% | -6.1% | -0.5% |
| SUM_REL_DUAL - REL | dev | +3.1% | 1.01 | 0.977 | +4.4% | -3.6% | +3.6% | +2.1% |
| SUM_REL_DUAL - RUP | dev | -1.3% | -0.44 | 0.974 | -0.2% | -6.4% | -2.4% | +0.8% |
| DUALmc - REL | dev | -2.1% | -0.65 | 0.964 | -4.5% | +9.7% | -2.9% | -0.5% |
| SUM_REL_DUAL - SUM_REL_RUP | dev | +0.6% | 0.34 | 0.990 | +2.0% | -6.5% | +0.9% | -0.0% |
| SUM_REL_RUP - REL | dev | +2.5% | 1.04 | 0.980 | +2.4% | +2.9% | +2.7% | +2.1% |
| DUAL - REL | hold | +1.0% | 0.12 | 0.921 | -6.9% | +7.4% | +12.8% | -11.3% |
| DUAL - RUP | hold | -8.9% | -1.71 | 0.972 | -17.3% | -2.0% | -11.3% | -6.5% |
| DUALP - REL | hold | +12.8% | 1.13 | 0.898 | -3.9% | +26.5% | +20.2% | +5.2% |
| DUALP - RUP | hold | +2.9% | 0.32 | 0.944 | -14.3% | +17.1% | -3.9% | +10.0% |
| DUALt300 - RUP | hold | -4.6% | -0.67 | 0.954 | -4.9% | -4.3% | -0.6% | -8.6% |
| DUALt300 - DUAL | hold | +4.3% | 0.84 | 0.962 | +12.4% | -2.3% | +10.6% | -2.2% |
| RUP - REL | hold | +9.9% | 1.61 | 0.938 | +10.4% | +9.4% | +24.1% | -4.8% |
| ABS - REL | hold | -10.4% | -1.17 | 0.920 | -13.2% | -8.1% | -14.2% | -6.5% |
| BAR - REL | hold | -7.4% | -0.81 | 0.920 | -7.5% | -7.3% | -9.2% | -5.6% |
| SUM_REL_ABS - REL | hold | -3.3% | -0.49 | 0.960 | -3.1% | -3.5% | -7.0% | +0.5% |
| SUM_REL_BAR - REL | hold | -7.8% | -1.05 | 0.959 | -16.9% | -0.4% | -14.8% | -0.7% |
| AND_REL_ABS50 - REL | hold | +2.6% | 1.48 | 0.997 | +2.4% | +2.7% | +1.5% | +3.7% |
| PROD_RUP_ABS - RUP | hold | -2.8% | -0.54 | 0.953 | -2.2% | -3.3% | -14.0% | +8.8% |
| SUM_REL_DUAL - REL | hold | +8.3% | 1.56 | 0.967 | +3.0% | +12.7% | +10.7% | +5.8% |
| SUM_REL_DUAL - RUP | hold | -1.6% | -0.31 | 0.970 | -7.5% | +3.3% | -13.4% | +10.6% |
| DUALmc - REL | hold | -0.5% | -0.07 | 0.970 | -8.9% | +6.3% | +0.4% | -1.5% |
| SUM_REL_DUAL - SUM_REL_RUP | hold | -1.0% | -0.28 | 0.988 | -4.7% | +2.0% | -1.2% | -0.8% |
| SUM_REL_RUP - REL | hold | +9.3% | 1.77 | 0.977 | +7.7% | +10.7% | +12.0% | +6.6% |

Bear days (N500 below its 200dma) are 17% of DEV and 55% of 2026. The regime splits are conditional means of the daily difference. They are descriptive and have no t-stats.

### 4.3 Robustness across K in {10,20,30,50} x step in {5,10} (50 bp): how many cells the first book wins

| pair | window | cells positive | median diff /yr | min | max | median NW t | cells t>2 |
|---|---|---|---|---|---|---|---|
| DUAL - REL | dev | 8/8 | +3.1% | +1.8% | +10.3% | 1.03 | 0 |
| DUAL - REL | hold | 7/8 | +3.4% | -3.8% | +5.9% | 0.37 | 0 |
| DUAL - RUP | dev | 3/8 | -0.3% | -4.4% | +2.7% | -0.12 | 0 |
| DUAL - RUP | hold | 4/8 | +0.4% | -8.9% | +10.5% | 0.08 | 0 |
| DUALP - REL | dev | 8/8 | +1.7% | +0.3% | +14.5% | 0.48 | 1 |
| DUALP - REL | hold | 6/8 | +10.6% | -10.5% | +18.1% | 1.12 | 0 |
| DUALP - RUP | dev | 1/8 | -2.6% | -4.0% | +4.0% | -0.67 | 0 |
| DUALP - RUP | hold | 7/8 | +4.0% | -3.7% | +16.2% | 0.52 | 2 |
| DUALt300 - RUP | dev | 2/8 | -0.4% | -3.7% | +3.2% | -0.13 | 0 |
| DUALt300 - RUP | hold | 6/8 | +4.4% | -4.6% | +12.8% | 0.74 | 0 |
| RUP - REL | dev | 8/8 | +4.6% | +2.2% | +10.5% | 1.23 | 0 |
| RUP - REL | hold | 6/8 | +4.2% | -6.9% | +9.9% | 0.56 | 0 |
| ABS - REL | dev | 0/8 | -4.5% | -11.9% | -0.4% | -1.16 | 0 |
| ABS - REL | hold | 0/8 | -12.9% | -17.9% | -10.4% | -1.65 | 0 |
| SUM_REL_ABS - REL | dev | 2/8 | -0.5% | -1.9% | +1.1% | -0.19 | 0 |
| SUM_REL_ABS - REL | hold | 0/8 | -5.7% | -14.7% | -1.4% | -1.15 | 0 |
| AND_REL_ABS50 - REL | dev | 2/8 | -0.1% | -1.5% | +0.0% | -0.16 | 0 |
| AND_REL_ABS50 - REL | hold | 7/8 | +0.8% | -1.1% | +2.6% | 0.53 | 0 |
| SUM_REL_DUAL - REL | dev | 8/8 | +4.3% | +2.5% | +16.1% | 2.10 | 5 |
| SUM_REL_DUAL - REL | hold | 8/8 | +6.3% | +0.8% | +8.3% | 0.89 | 0 |
| SUM_REL_DUAL - SUM_REL_RUP | dev | 8/8 | +0.6% | +0.1% | +3.6% | 0.49 | 0 |
| SUM_REL_DUAL - SUM_REL_RUP | hold | 3/8 | -0.6% | -4.8% | +5.7% | -0.17 | 0 |
| SUM_REL_RUP - REL | dev | 8/8 | +3.7% | +2.2% | +13.1% | 1.66 | 3 |
| SUM_REL_RUP - REL | hold | 7/8 | +6.7% | -0.7% | +10.4% | 1.58 | 1 |

Excess CAGR vs the horizon-matched random baseline:

| score | DEV s5 K10 | DEV s5 K20 | DEV s5 K30 | DEV s5 K50 | DEV s10 K10 | DEV s10 K20 | DEV s10 K30 | DEV s10 K50 | 2026 s5 K10 | 2026 s5 K20 | 2026 s5 K30 | 2026 s5 K50 | 2026 s10 K10 | 2026 s10 K20 | 2026 s10 K30 | 2026 s10 K50 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REL | +20.6% | +16.9% | +15.1% | +13.2% | +9.0% | +10.9% | +11.7% | +10.2% | +12.9% | +6.8% | +5.9% | +9.4% | +23.5% | +15.9% | +11.4% | +12.9% |
| RUP | +28.1% | +21.9% | +18.5% | +15.3% | +21.2% | +18.0% | +15.1% | +15.4% | +5.2% | +18.3% | +9.7% | +16.8% | +14.9% | +25.1% | +13.5% | +18.9% |
| DUAL | +22.3% | +19.6% | +18.7% | +16.0% | +20.9% | +13.9% | +18.6% | +15.0% | +8.5% | +7.9% | +9.7% | +14.7% | +28.2% | +16.5% | +15.4% | +20.1% |
| DUALP | +24.6% | +17.0% | +15.4% | +14.1% | +26.5% | +13.8% | +12.6% | +12.4% | +9.8% | +22.1% | +23.9% | +19.9% | +10.6% | +30.5% | +34.1% | +24.9% |
| DUALt300 | +27.4% | +21.6% | +18.0% | +14.7% | +25.1% | +16.8% | +15.2% | +10.8% | +16.9% | +13.0% | +17.6% | +17.2% | +31.3% | +22.6% | +24.9% | +21.9% |
| SUM_REL_RUP | +32.5% | +19.8% | +19.6% | +15.5% | +24.7% | +13.6% | +16.0% | +14.3% | +13.2% | +17.7% | +14.4% | +16.2% | +22.8% | +26.3% | +24.0% | +19.7% |
| SUM_REL_DUAL | +37.5% | +20.5% | +20.2% | +16.0% | +28.7% | +13.7% | +17.9% | +15.1% | +16.7% | +16.6% | +14.8% | +12.3% | +30.1% | +26.1% | +20.6% | +13.9% |
| ABS | +6.5% | +9.3% | +11.3% | +10.0% | +2.4% | +2.9% | +8.9% | +9.6% | -5.9% | -3.4% | -7.0% | -3.2% | +5.8% | +3.4% | -1.2% | -1.1% |

### 4.4 Avoid overlays: equal-weight U minus the model's bottom 30% (`select_quantile=(0.3,1)`, `sizing='equal'`)

| mask | overlay (what is dropped) | DEV CAGR | DEV vs universe /yr | t | DEV maxDD | 2026 CAGR | 2026 vs universe /yr | 2026 t | DEV vs AVOID_RUPup | 2026 vs AVOID_RUPup |
|---|---|---|---|---|---|---|---|---|---|---|
| U | UNIVERSE_EW | 11.2% | – | – | -29.4% | 6.4% | – | – | – | – |
| U | AVOID_DDN | 13.5% | +1.8% | 1.49 | -27.3% | 4.4% | -2.1% | -1.09 | – | – |
| U | AVOID_RDN | 13.4% | +1.7% | 1.25 | -26.9% | 4.6% | -2.0% | -0.90 | – | – |
| U | AVOID_RUPup | 14.7% | +3.3% | 4.56 | -28.8% | 12.2% | +5.6% | 5.72 | – | – |
| U | AVOID_DUALup | 14.6% | +3.1% | 4.49 | -28.7% | 11.2% | +4.5% | 4.06 | -0.2% | -1.0% |
| U | AVOID_DUALPup | 14.2% | +2.8% | 3.75 | -29.0% | 11.8% | +5.0% | 4.73 | -0.5% | -0.5% |
| U | AVOID_DUALt300up | 14.3% | +2.9% | 3.82 | -28.8% | 11.4% | +4.8% | 5.04 | -0.3% | -0.8% |
| U | AVOID_REL | 15.0% | +3.2% | 3.06 | -27.3% | 7.9% | +1.3% | 0.75 | -0.0% | -4.3% |
| U | AVOID_ABS | 15.3% | +3.7% | 4.99 | -27.9% | 7.4% | +0.8% | 0.46 | +0.4% | -4.7% |
| U | AVOID_BAR | 13.8% | +2.4% | 3.39 | -29.0% | 8.0% | +1.4% | 0.89 | -0.9% | -4.2% |
| U | AVOID_DUALmc | 14.8% | +3.1% | 2.85 | -27.5% | 7.1% | +0.5% | 0.34 | -0.2% | -5.1% |
| liq5 | UNIVERSE_EW | 12.4% | – | – | -28.3% | 5.3% | – | – | – | – |
| liq5 | AVOID_DDN | 14.0% | +1.1% | 0.88 | -26.6% | 2.9% | -2.5% | -1.15 | – | – |
| liq5 | AVOID_RDN | 13.8% | +0.9% | 0.65 | -26.1% | 3.2% | -2.2% | -0.98 | – | – |
| liq5 | AVOID_RUPup | 15.1% | +2.5% | 3.29 | -28.3% | 11.1% | +5.6% | 5.80 | – | – |
| liq5 | AVOID_DUALup | 14.8% | +2.3% | 3.04 | -28.1% | 10.3% | +4.7% | 4.47 | -0.2% | -0.8% |
| liq5 | AVOID_DUALPup | 14.5% | +2.0% | 2.56 | -28.3% | 11.2% | +5.6% | 5.43 | -0.5% | +0.0% |
| liq5 | AVOID_DUALt300up | 14.6% | +2.2% | 2.53 | -28.4% | 10.5% | +5.0% | 4.80 | -0.3% | -0.6% |
| liq5 | AVOID_REL | 15.2% | +2.3% | 2.09 | -26.9% | 5.8% | +0.3% | 0.18 | -0.2% | -5.2% |
| liq5 | AVOID_ABS | 15.6% | +2.9% | 3.82 | -27.3% | 6.1% | +0.6% | 0.31 | +0.4% | -5.0% |
| liq5 | AVOID_BAR | 14.1% | +1.6% | 2.24 | -28.3% | 6.9% | +1.4% | 0.87 | -0.9% | -4.1% |
| liq5 | AVOID_DUALmc | 15.0% | +2.2% | 1.90 | -26.9% | 5.7% | +0.2% | 0.15 | -0.3% | -5.3% |

AVOID_DDN drops the highest P(DUAL=-1) and AVOID_RDN the highest P(REL=-1). AVOID_xxxup drops the lowest P(xxx=+1). AVOID_REL drops the lowest M_REL score. 80 bp results shift every row by the same cost drag (see results.json).

### 4.5 Input-side conditions (sample filters) vs label-side conditions

| gate | share of U | daily share sd | names/day | random-in-gate DEV CAGR | gate value vs random-in-U | t | random maxDD | random-in-gate 2026 | gate value 2026 | t 2026 |
|---|---|---|---|---|---|---|---|---|---|---|
| U | 100.0% | 0.0% | 1094 | 11.8% | +0.0% | 0.00 | -29.7% | 6.9% | +0.0% | 0.00 |
| G_sma200 | 58.0% | 21.9% | 654 | 13.6% | +1.8% | 1.01 | -29.3% | 10.3% | +3.4% | 0.55 |
| G_rs70 | 30.0% | 0.3% | 329 | 12.7% | +0.9% | 0.42 | -29.3% | 11.2% | +4.4% | 0.59 |
| G_trend | 26.3% | 6.0% | 306 | 12.7% | +0.9% | 0.42 | -29.4% | 22.4% | +15.5% | 2.08 |
| G_mkt200 | 74.3% | 44.0% | 1068 | 5.3% | -6.5% | -1.07 | -21.8% | -14.9% | -21.7% | -1.29 |

| score@gate | DEV CAGR | excess vs random-in-gate | t | maxDD | beta | 2026 CAGR | 2026 excess | 2026 t | 2026 maxDD |
|---|---|---|---|---|---|---|---|---|---|
| REL@U | 28.7% | +16.9% | 3.18 | -29.5% | 1.26 | 13.6% | +6.8% | 0.94 | -18.2% |
| DUAL@U | 31.4% | +19.6% | 3.55 | -33.6% | 1.35 | 14.8% | +7.9% | 1.16 | -17.1% |
| ABS@U | 21.1% | +9.3% | 2.06 | -32.8% | 1.27 | 3.5% | -3.4% | -0.35 | -14.6% |
| REL@G_sma200 | 27.0% | +13.4% | 2.72 | -31.4% | 1.24 | 16.7% | +6.4% | 0.81 | -13.5% |
| DUAL@G_sma200 | 26.2% | +12.6% | 2.41 | -36.9% | 1.33 | 20.2% | +10.0% | 1.48 | -14.8% |
| REL@G_rs70 | 26.9% | +14.2% | 3.26 | -32.4% | 1.26 | 17.6% | +6.4% | 0.84 | -13.2% |
| DUAL@G_rs70 | 26.1% | +13.3% | 3.05 | -36.2% | 1.31 | 22.9% | +11.7% | 1.92 | -12.8% |
| REL@G_trend | 27.6% | +15.0% | 3.44 | -32.1% | 1.27 | 18.7% | -3.6% | -0.33 | -12.7% |
| DUAL@G_trend | 25.5% | +12.8% | 2.65 | -35.9% | 1.31 | 20.2% | -2.1% | -0.22 | -13.3% |
| ABS@G_trend | 24.2% | +11.6% | 2.88 | -31.3% | 1.26 | 1.7% | -20.7% | -2.65 | -12.0% |
| RELG@G_trend | 23.0% | +10.4% | 2.38 | -31.1% | 1.31 | 19.8% | -2.6% | -0.22 | -13.4% |
| REL@G_mkt200 | 22.4% | +17.1% | 3.76 | -15.8% | 0.92 | -12.6% | +2.3% | 0.70 | -12.1% |
| DUAL@G_mkt200 | 22.5% | +17.2% | 3.85 | -20.5% | 0.98 | -15.4% | -0.5% | -0.09 | -14.7% |

G_sma200 = close>sma200. G_rs70 = xr_mom60>0.7. G_trend = both, which is the client's 'absolute uptrend AND relatively strong' as an input condition. G_mkt200 = Nifty 500 above its 200dma: market timing, with an empty book (cash at 0% yield) on off days. RELG = the REL model retrained on G_trend rows only.

### 4.6 Liquidity tier (elig_liq5, 20d turnover >= Rs 5 cr), K20 step 5

| score | DEV CAGR | excess | t | maxDD | DEV CAGR 80bp | 2026 CAGR | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|
| REL | 24.8% | +13.0% | 2.65 | -30.2% | 20.3% | 12.7% | +7.3% | 1.00 |
| RUP | 27.1% | +15.3% | 2.98 | -33.2% | 22.5% | 19.8% | +14.4% | 1.99 |
| DUAL | 24.9% | +13.2% | 2.80 | -34.4% | 20.4% | 11.6% | +6.2% | 0.91 |
| DUALP | 27.0% | +15.2% | 3.05 | -32.1% | 22.4% | 24.6% | +19.2% | 2.22 |
| DUALt300 | 26.9% | +15.1% | 2.74 | -33.4% | 22.4% | 18.4% | +12.9% | 1.34 |
| ABS | 19.5% | +7.7% | 1.80 | -34.0% | 15.2% | 3.8% | -1.6% | -0.20 |
| SUM_REL_ABS | 27.5% | +15.7% | 3.00 | -30.5% | 22.9% | 10.2% | +4.8% | 0.47 |
| AND_REL_ABS50 | 25.3% | +13.5% | 2.67 | -30.1% | 20.8% | 15.1% | +9.7% | 1.20 |

### 4.7 Signal-calendar phase sensitivity (K20, step 5, 50 bp; calendar shifted by 0-4 trading days)

| book | DEV CAGR (5-phase mean) | DEV range | DEV excess vs random | DEV maxDD | 2026 CAGR mean | 2026 range | 2026 excess | 2026 maxDD |
|---|---|---|---|---|---|---|---|---|
| REL | 28.3% | 27.7% .. 29.3% | +16.7% | -29.5% | 14.1% | 6.6% .. 20.7% | +5.1% | -17.9% |
| RUP | 33.6% | 32.3% .. 34.8% | +22.0% | -31.0% | 17.6% | 10.8% .. 25.2% | +8.6% | -18.6% |
| DUAL | 34.2% | 31.4% .. 36.8% | +22.7% | -32.3% | 21.1% | 14.8% .. 24.6% | +12.1% | -17.5% |
| DUALP | 27.8% | 25.6% .. 29.8% | +16.2% | -31.8% | 19.5% | 13.9% .. 29.0% | +10.5% | -17.3% |
| SUM_REL_RUP | 33.4% | 31.6% .. 36.3% | +21.9% | -30.3% | 19.1% | 14.8% .. 24.6% | +10.1% | -18.1% |
| SUM_REL_DUAL | 34.7% | 32.3% .. 38.1% | +23.2% | -31.2% | 20.8% | 14.5% .. 24.2% | +11.8% | -18.3% |
| ABS | 22.7% | 21.1% .. 26.5% | +11.1% | -30.9% | -0.7% | -7.7% .. 5.3% | -9.7% | -15.2% |

| paired difference | DEV mean /yr | DEV range | DEV phases >0 | DEV mean t | 2026 mean /yr | 2026 range | 2026 phases >0 | 2026 mean t |
|---|---|---|---|---|---|---|---|---|
| DUAL-RUP | +0.5% | -1.7% .. +1.9% | 4/5 | 0.25 | +3.0% | -8.9% .. +9.6% | 4/5 | 0.43 |
| DUALP-RUP | -4.6% | -6.4% .. -2.0% | 0/5 | -1.32 | +1.5% | -5.7% .. +5.9% | 4/5 | 0.19 |
| DUAL-REL | +5.1% | +2.6% .. +6.2% | 5/5 | 1.39 | +6.2% | +1.0% .. +10.7% | 5/5 | 0.58 |
| RUP-REL | +4.6% | +4.0% .. +5.0% | 5/5 | 1.34 | +3.2% | -1.0% .. +9.9% | 3/5 | 0.44 |
| SUM_REL_DUAL-SUM_REL_RUP | +1.0% | +0.5% .. +1.4% | 5/5 | 0.66 | +1.4% | -1.4% .. +5.7% | 3/5 | 0.30 |

| avoid overlay vs universe EW | DEV mean /yr | DEV range | DEV mean t | 2026 mean /yr | 2026 range | 2026 mean t | 2026 phases >0 |
|---|---|---|---|---|---|---|---|
| AVOID_RUPup | +3.3% | +3.2% .. +3.5% | 4.62 | +5.8% | +5.6% .. +6.0% | 5.99 | 5/5 |
| AVOID_DUALup | +3.2% | +3.1% .. +3.3% | 4.60 | +5.0% | +4.5% .. +5.2% | 4.54 | 5/5 |
| AVOID_REL | +3.3% | +3.2% .. +3.5% | 3.19 | +1.0% | +0.5% .. +1.3% | 0.62 | 5/5 |
| AVOID_ABS | +3.8% | +3.6% .. +3.9% | 5.00 | +0.4% | -0.3% .. +0.8% | 0.20 | 4/5 |
| AVOID_DDN | +1.9% | +1.6% .. +2.2% | 1.56 | -2.6% | -2.9% .. -2.1% | -1.37 | 0/5 |
| AVOID_RDN | +1.8% | +1.7% .. +1.9% | 1.34 | -2.4% | -2.9% .. -2.0% | -1.15 | 0/5 |

The phase-0 tables above (4.1-4.6) are one draw. For a 20-name book, the phase moves 2026 CAGR by 10-14 pp and DEV CAGR by 2-5 pp. The single-phase holdout result 'DUAL -8.9%/yr vs RUP' (4.2) was an extreme draw: the phase mean is +3.0%/yr. Differences between the label variants sit inside this band. The avoid overlays hold about 700 names, so they are phase-stable (range under 1 pp).

## 5. Drawdowns, beta and what the books buy

| book (K20 s5 50bp) | DEV maxDD | worst 20d | ann vol | Calmar | beta | down capt. | up capt. | 2026 maxDD | 2026 worst 20d | 2026 beta | 2026 down capt. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| REL | -29.5% | -17.1% | 20.9% | 0.97 | 1.26 | 1.16 | 1.28 | -18.2% | -13.4% | 1.20 | 0.97 |
| RUP | -32.6% | -18.9% | 23.0% | 1.03 | 1.33 | 1.25 | 1.40 | -17.1% | -12.8% | 1.14 | 0.84 |
| DUAL | -33.6% | -19.0% | 23.1% | 0.94 | 1.35 | 1.26 | 1.40 | -17.1% | -12.2% | 1.12 | 0.92 |
| DUALP | -31.8% | -18.5% | 22.3% | 0.90 | 1.29 | 1.22 | 1.34 | -16.5% | -13.0% | 1.13 | 0.86 |
| DUALt300 | -33.4% | -18.2% | 22.8% | 1.00 | 1.30 | 1.21 | 1.37 | -16.0% | -12.4% | 1.09 | 0.89 |
| ABS | -32.8% | -16.6% | 20.4% | 0.64 | 1.27 | 1.25 | 1.27 | -14.6% | -11.4% | 1.00 | 0.88 |
| BAR | -27.5% | -15.3% | 19.1% | 0.75 | 1.17 | 1.17 | 1.20 | -15.6% | -12.6% | 0.99 | 0.81 |
| SUM_REL_ABS | -29.7% | -16.3% | 20.7% | 1.02 | 1.29 | 1.19 | 1.32 | -16.4% | -13.0% | 1.14 | 0.93 |
| SUM_REL_RUP | -30.5% | -17.7% | 21.9% | 1.04 | 1.27 | 1.17 | 1.32 | -17.4% | -13.1% | 1.18 | 0.89 |
| SUM_REL_DUAL | -33.0% | -19.0% | 22.2% | 0.98 | 1.31 | 1.19 | 1.35 | -17.9% | -13.1% | 1.14 | 0.87 |

| book (DEV+2026 days) | ann. ret N500>200dma | ann. ret N500<200dma | beta bull | beta bear | ann. ret N500 20d up | ann. ret 20d down |
|---|---|---|---|---|---|---|
| REL | 39.9% | -19.0% | 1.18 | 1.32 | 65.5% | -39.3% |
| RUP | 45.2% | -13.2% | 1.21 | 1.36 | 74.6% | -39.6% |
| DUAL | 41.4% | -14.4% | 1.23 | 1.36 | 70.1% | -40.7% |
| DUALP | 40.1% | -8.0% | 1.19 | 1.32 | 68.3% | -36.2% |
| ABS | 32.4% | -25.2% | 1.21 | 1.17 | 56.8% | -44.0% |
| BAR | 31.4% | -21.5% | 1.11 | 1.14 | 53.5% | -38.2% |
| SUM_REL_ABS | 39.9% | -18.4% | 1.23 | 1.26 | 63.9% | -36.1% |

The binary-up books (RUP, DUAL, DUALP) lose less than REL on bear days (-14% to -8% vs -19% annualised). That effect comes from the binary loss, because RUP shows it without any absolute leg. DUALP's somewhat better bear-day number does not survive into a better DEV maxDD (-31.8% vs -29.5% for REL).

| window | top-20 by | net bps / 20d | resid bps | beta_60 | ann vol | log turnover | % above sma200 | xr_mom60 pct |
|---|---|---|---|---|---|---|---|---|
| dev | REL | +218 | +106 | 1.13 | 0.44 | 19.56 | 81% | 0.62 |
| dev | RUP | +252 | +153 | 1.24 | 0.49 | 18.91 | 86% | 0.69 |
| dev | DUAL | +244 | +149 | 1.17 | 0.48 | 18.94 | 84% | 0.69 |
| dev | DUALP | +222 | +124 | 1.15 | 0.51 | 18.96 | 87% | 0.70 |
| dev | ABS | +166 | +62 | 1.29 | 0.40 | 19.81 | 68% | 0.55 |
| dev | BAR | +152 | +53 | 1.19 | 0.46 | 19.56 | 70% | 0.55 |
| dev | SUM_REL_ABS | +230 | +123 | 1.24 | 0.42 | 19.69 | 77% | 0.59 |
| dev | universe | +92 | 0 | 1.19 | 0.38 | 19.03 | 63% | 0.50 |
| hold | REL | +123 | +59 | 1.15 | 0.43 | 20.03 | 33% | 0.33 |
| hold | RUP | +127 | +52 | 1.16 | 0.51 | 19.41 | 51% | 0.52 |
| hold | DUAL | +210 | +116 | 1.06 | 0.48 | 19.29 | 53% | 0.53 |
| hold | DUALP | +161 | +83 | 1.04 | 0.51 | 19.31 | 59% | 0.56 |
| hold | ABS | -40 | -49 | 1.10 | 0.30 | 21.20 | 33% | 0.35 |
| hold | BAR | -22 | -43 | 0.98 | 0.37 | 20.68 | 40% | 0.39 |
| hold | SUM_REL_ABS | +33 | +13 | 1.17 | 0.34 | 20.89 | 31% | 0.32 |
| hold | universe | +78 | 0 | 1.18 | 0.39 | 19.14 | 45% | 0.50 |

Top-20 overlap with the REL book (mean share of the same names, every 5th date, 2023-2026): RUP 43%, DUAL 38%, DUALP 33%, ABS 29%, BAR 23%, DUALmc 49%, SUM_REL_ABS 55%, AND_REL_ABS50 96%. DUAL vs RUP: 58%. The binary-up models lean toward trend and momentum (84-87% above sma200, xr_mom60 0.69-0.70 on DEV). The regression REL model turned contrarian in 2026 (33% above sma200).

## 6. Pros, cons, failure modes

**DUAL (label-side AND)**

* Pros: maximal label/P&L coherence (+1 is always a net winner, -1 always a net loser). No executable or NaN biases. Learnable (per-date AUC 0.545-0.564). Easy to explain to a discretionary trader.
* Cons: (1) Its +1 rate is 91% the same as REL's, so it adds almost no information about which stock to own. (2) The 9% it changes are chosen by the market's realised path, which re-introduces market timing (daily share corr 0.70 with the market window). A long-only top-K book is always invested and cannot use that timing. Models trained on top-tail events carry more beta (1.33-1.35 vs 1.26 for REL), and DUAL's phase-mean DEV maxDD is -32.3% vs -31.0% for RUP and -29.5% for REL. The absolute leg does not cushion drawdowns. (3) The stricter tau is, the more pronounced this becomes (tau=300bp: corr 0.79, no DEV gain vs RUP). (4) DUAL_down as an avoid label fails in 2026, because its high-P(down) names are high-vol names whose raw returns were fine.
* Failure mode: in 20-day windows where the market falls more than 5%, the DUAL +1 set shrinks from 30% to about 12% of names (2026 had 55% of days below the 200dma). Training sets become regime-imbalanced and the classifier's base rate drifts. The label then measures 'did the market go up' as much as 'was this the right stock'.

**DUALP (path version):** worse than RUP on DEV (-4.6%/yr phase mean, 0/5 phases, 1/8 grid cells). Its 2026 phase-0 result (+29%) was its best phase. The phase mean is 19.5% vs RUP 17.6%. Selection on DEV would not have picked it.

**Two-model AND / product / rank-sum with an absolute model:** never better than the pure-relative model on DEV beyond noise, and worse in 2026 (rank-sum 0/8 holdout cells). The absolute model's cross-sectional information overlaps the relative model's (rank corr 0.69). Its extra content is market timing, which does not help a cross-sectional book.

**Input-side gates:** these are honest sample filters and leave label values unchanged. They add no DEV skill (gate value +0.9%/yr, t 0.4), shrink the universe to about 300 names a day, and the model is no better inside the gate. G_trend made a lot of money in 2026, which is worth re-testing in round 3 as a regime-dependent tilt, but it cannot be selected on DEV.

## 7. What to use (for the judges)

1. **Primary selection label:** pure relative XR_neu residual rank at h=20, trained as a **binary top-30% classifier** (M_RUP). Alternatively blend it with the XR_neu regression (SUM_REL_RUP: best phase-0 DEV excess t 3.96; phase-mean DEV 33.4%, 2026 19.1% vs random about 7%). Do not add an absolute condition to the label. The only consistent hint in DUAL's favour is SUM_REL_DUAL vs SUM_REL_RUP at +1.0%/yr on DEV (5/5 phases, mean t 0.66), which is far below any significance bar.
2. **Avoid label:** the bottom 30% by P(relative top-30). Do not use a separately trained down model (DUAL_down or REL_down): those classify down events well but failed as an overlay in 2026.
3. **The absolute/market condition** belongs in an exposure layer (R2_regime) evaluated on its own, not inside the stock label.
4. Caveats: every DEV excess t here (3.0-4.0 for the relative books) is only modestly above the expected-max-of-N luck bar (about 2.6 for this agent's 130 configs, about 3.2 for the programme). The DUAL vs relative differences are well inside noise in both directions.

Scripts: s1_labels.py (labels), s2_events.py (event rates and sensitivity), s3_wf.py (walk-forward models), s4_xs.py (learnability), s5_invest.py (Sim books), s6_picks.py (pick characteristics), s7_paired.py (paired tests, drawdowns, regimes), s8_report.py (this file), s9_phase.py and s9b_phase_avoid.py (signal-calendar phase robustness), s10_summary.py (structured summary). All numbers are in results.json.
