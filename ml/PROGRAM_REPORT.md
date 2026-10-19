# SuryaDhana research program: final report

**Date:** 2026-10-19 · **Program lead:** evaluation lead (this session) · **Scope:** NSE cash equities, end-of-day bhavcopy data, 5 years (2021-10 to 2026-10) · **Companion report:** `ml/report/program_report.html` (built by `python3 -m ml.make_program_report`)

**Status: complete.** The 5-year walk-forward, its paired block bootstrap, regime table, rank-ensemble challenger and paper portfolio are all in (`ml/results/scale5y/SCALE5Y.md`). Every number below is read from a committed JSON or Markdown artifact named in the text; nothing is estimated from memory.

---

## 1. Verdict in one page

**There is a real but small cross-sectional signal in NSE end-of-day data, and it is not yet a demonstrated tradable edge.**

- **Signal.** Over 43 monthly out-of-sample folds (January 2023 to July 2026), a LightGBM classifier on all end-of-day features ranks stocks by 20-session relative performance with mean AUC 0.5366, above 0.50 in 81% of months, worst month 0.453 (March 2026). The honest nested-selection variant scores 0.5359 (20-session block-bootstrap 95% interval [0.5250, 0.5483]; per-date rank IC +0.065, Newey-West t 6.0, positive in 38 of 43 months). A one-feature momentum rule scores 0.4951. The pilot's 10-feature subset, chosen on 2026 data, scores 0.5251 at 5 years (−0.0115 [−0.0159, −0.0071] against all features): its selection did not transfer. (`ml/results/scale5y/*.json`)
- **Size.** Per-date rank information coefficient (IC) is 0.04 to 0.05 on the pilot and 0.065 over the five years. That is the size the literature finds at the frontier: GKX's neural nets imply a forecast-return correlation of about 0.06 on US data, Qlib's LightGBM reaches IC 0.045 on CSI300. (`ml/research/SOTA_FORECASTING.md`)
- **Economics.** Over 913 out-of-sample signal dates (January 2023 to September 2026), net of 20 bps per side, **no single machine-learned model's top decile beats simply holding the universe equally weighted** (+19.4% a year): the LightGBM books trail it by 0.7 to 1.2 points a year and beat it in 20 of 45 months. The pre-registered three-model rank ensemble is the one exception: +7.0% a year over the universe, information ratio 1.26 with a 95% interval of [0.32, 2.37], positive in every calendar year. Its Deflated Sharpe Ratio at an honestly counted 177 trials is 0.16 (0.04 for the liquid book pre-registered as the paper portfolio), so it does not survive multiple-testing adjustment. (`ml/results/scale5y/SCALE5Y.md`)
- **Pre-registered promotion gates (`ml/SCALE_UP.md`).** LightGBM with nested selection passes **0 of 5**, LightGBM on all features **0 of 5**, the rank ensemble **1 of 5**. Gate 1 (beats L2 logistic on mean CV AUC with an interval excluding zero) fails for all three: the logistic model's mean is higher (delta −0.0056 [−0.0150, +0.0024] for nested LightGBM). Gate 2 (fold floor ≥ 0.50 in ≥ 90% of months): 86%, 81%, 91% (the ensemble's one pass). Gate 3 (top decile beats the equal-weight universe in ≥ 75% of months net of 20 bps): 44%, 44%, 73%. Gate 4 (selected-feature overlap ≥ 7 of 10 across yearly re-selections): 4, 4, 5. Gate 5 (DSR ≥ 0.95 on the liquid top decile, N = 177): 0.000, 0.000, 0.040. **The pre-registered criteria for committing capital are not met by any model.**
- **Integrity.** The pipeline is clean: labels and features recompute exactly from raw data, point-in-time universe verified, label-permutation null 0.500 ± 0.001, no duplicate sessions in 1,245 trading days. The pilot's headline (CV AUC 0.531, "only model above chance") was inflated by feature selection on test months and has been corrected in `ml/MODEL_SELECTION.md`. (`ml/results/audit/AUDIT.md`)

### The three deliverables

| Deliverable | Decision | Evidence |
|---|---|---|
| **Feature set** | The 52 end-of-day candidates: the 50 base features plus `deliv_value_share_20` and `amihud_20`, the two that honest yearly re-selection keeps picking. The single-model reference feeds all 52 to LightGBM without hand selection; the ensemble as tested re-selects 5 to 15 of them each year, which buys nothing on AUC (−0.0007 [−0.0052, +0.0038]). The pilot's 10-feature subset is retired. No further feature engineering on bhavcopy-derived inputs; the next gains require external data (corporate actions first). | §5, §6.3 |
| **Label set** | Primary `label_beat_mkt_20d` (20-session next-open excess vs the cross-sectional median, clean-masked). Economics judged against the equal-weight universe **mean**, rank-IC and net spread reported beside AUC, ETFs excluded, 40-day label carried as a candidate, `up_5d` demoted to a negative control. | §4 |
| **Model** | For paper trading only: the pre-registered rank-average ensemble (LightGBM champion config + LambdaRank + CatBoost with fixed tree budgets, per-date rank average), frozen as one strategy. Single-model reference: LightGBM, fixed 300 trees, all features, rolling 504-session window, monthly retrain, 22-session embargo, exit-date purge. L2 logistic (C = 0.01) kept as the drift monitor, not a scorer. Deep sequence models, transformers, DLinear, time-series foundation models and reinforcement learning are dropped with evidence. **Nothing is promoted to capital.** | §6, §7 |

**Recommendation:** commit no capital. Paper-trade the ensemble's liquid-tercile top decile as one frozen, pre-registered strategy from November 2026 (a fresh test with N = 1; at its observed information ratio of 0.85 it needs about 4 years of track record to reach a 95% probabilistic Sharpe), with the monitoring in §10. Put the next research effort into volatility-neutral book construction and into data (corporate actions, sector classification, F&O membership, fundamentals) rather than into new model families.

---

## 2. What was asked, and how the work was organised

Management asked for a Renaissance-grade, evidence-based answer to five questions: how well do the features predict each label type; which labels should be modelled; are the features sufficient or do they need enhancement; what do classic ML, deep learning, reinforcement learning, transformers and state-of-the-art forecasters achieve on this problem; and is there a strategy with a promising return on capital. The standing rule was: nothing inflated, every number reproducible, bifurcate what does not work.

The program ran as a team of specialist agents under one shared evaluation harness (`ml/evaluation.py`, `ml/data.py`): purged walk-forward splits, 22-session embargo, seed 108, train-only preprocessing, one result schema. Each team wrote its own code and verdict:

| Team | Agent deliverable | Code | Verdict file |
|---|---|---|---|
| Data engineering | 5-year ingest with duplicate-day guard, body-type detection, resume; dataset builder | `nse_historical_ingest.py`, `ml/data.py`, `ml/build_5y.py` | `ml/results/scale5y/manifest_5y.json` |
| Quant (labels) | Feature × label predictive-power matrix across 28 label variants | `ml/label_study.py` | `ml/results/label_study/LABEL_STUDY.md` |
| Quant (features) | Feature EDA, 23 engineered features, A/B against a pre-registered bar | `ml/eda_features.py`, `ml/features_ext.py`, `ml/feature_ab.py` | `ml/report/feature_study.html`, `feature_ab_verdict.json` |
| Data science | Unused bhavcopy information, residual-IC test, external-data gap list | `ml/feature_sufficiency.py` | `ml/results/feature_sufficiency/FEATURE_SUFFICIENCY.md` |
| Classic ML / DL / RL | Logistic family, trees, GBMs, MLP, GRU/LSTM, REINFORCE bandit | `ml/models/*` | `ml/MODEL_SELECTION.md` |
| ML (state of the art) | LambdaRank, Huber, CatBoost, PatchTST-lite, cross-sectional transformer, DLinear, rank ensemble | `ml/models/sota.py` | `ml/results/sota/SOTA_MODELS.md` |
| Research | Literature review with 71 references, calibration of our numbers against published ones | | `ml/research/SOTA_FORECASTING.md` |
| Testing (red team) | Leakage, permutation null, point-in-time, best-of-N, honest nested selection | `ml/audit.py` | `ml/results/audit/AUDIT.md` |
| Portfolio quant | Net-of-cost backtest, capacity, Deflated Sharpe, bifurcation | `ml/strategy_backtest.py` | `ml/results/strategy/STRATEGY.md` |
| Scale-up | 5-year walk-forward, nested selection, duel, regimes, gates | `ml/scale5y.py`, `ml/scale5y_nested.py`, `ml/scale5y_report.py` | `ml/results/scale5y/SCALE5Y.md` |
| Analytics / product | This report, the HTML report, monitoring spec | `ml/make_program_report.py` | this file |

---

## 3. Data

**Store.** `nse_market.duckdb` holds 3,078,294 raw bhavcopy rows over 1,245 sessions from 2021-10-01 to 2026-10-16 (4,219 ticker codes across all series; 2,722,591 feature rows). Sessions per calendar year: 63 (Q4 2021), 248, 245, 247, 247, 195 (to 16 October 2026), consistent with the NSE calendar.

**Modelling datasets.**

| Dataset | Rows | Tickers | Dates | Folds | Holdout |
|---|---:|---:|---|---|---|
| Pilot (`ml/data/`) | 507,163 | 2,096 | 2025-06-02 to 2026-10-14 | 4 monthly (Apr to Jul 2026) | 2026-08-03 to 2026-09-11 |
| 5-year (`ml/data_5y/`) | 1,357,383 | 2,480 | 2022-10-03 to 2026-10-16 | 43 monthly (2023-01 to 2026-07) | 2026-08-03 to 2026-09-16 |

Universe filter is point-in-time: close ≥ ₹10 and trailing 20-day median turnover ≥ ₹1 crore. The first year of history is feature warm-up.

**Quality.**

- **Holiday echo (found and fixed).** The archive mirror re-served the prior session's file on 12 NSE holidays in 2026 (2.9% of pilot sessions). The ingest now carries a holiday calendar and a duplicate-day fingerprint guard; the pilot was rebuilt and re-validated with the model ranking unchanged.
- **Full-history scan (this report).** Across all 1,245 sessions, the largest share of tickers repeating the previous day's close and volume is 0.35% (2026-07-23), the normal footprint of illiquid names. No echo exists in the 5-year store.
- **Ingest resilience.** The 5-year backfill exposed an archive day served as an Excel workbook under a `.csv` name; the reader now detects the body type by magic bytes, falls back to Latin-1, rejects HTML bodies and skips a bad day instead of aborting. 19 of 19 ingest tests pass.
- **Known gap: corporate actions.** Prices are unadjusted. The `y_clean_20d` mask drops 0.4% to 0.6% of labelled rows around splits and suspensions, and `flag_split_20d` fires on 0.51% of rows. Over 5 years this is the single largest data-integrity risk and the first external feed to add (§11).
- **Known gap: ETFs.** 137 ETFs (6.1% of rows) sit inside the "stock" universe. They carry higher delivery share and higher mean excess return. The label study recommends excluding them (§4).

---

## 4. Labels: which target to model

Source: `ml/results/label_study/LABEL_STUDY.md` (28 label variants: 1, 2, 3, 5, 10, 20 and 40 sessions; close-to-close and next-open entry; raw, excess, rank and vol-scaled targets; 40 features; 1,106 testable hypotheses).

**Findings.**

1. **Predictability falls with horizon.** 21 to 22 of 40 features pass Benjamini-Hochberg q < 0.05 at 1 day, 4 to 5 at 20 days, none at 40 days once overlapping windows are corrected for. Selecting features on the first 8 months and scoring the rest gives an out-of-sample IC of +0.05 at 1 to 2 days (t 2.8 to 4.2), +0.03 at 5 days (t ≈ 1), and about zero from 10 to 20 days, because of the March-2026 regime break. Delivery is the one pillar that ranks in the top five at every horizon and for both entry conventions (t 4.5 at 20 days even with ETFs excluded); at 40 days the single best feature is `dist_52w_high` (IC 0.10).
2. **The excess label is the most predictable by a model, at any horizon.** Model rank-IC is flat at about 0.044 from 3 to 20 days; CV AUC sits between 0.518 and 0.524 at every horizon. The raw > 0 labels post the highest CV AUC (0.559) but that is market timing, not stock selection: their fold base rates swing from 0.44 to 0.72, their holdout AUC in a down market is 0.47 to 0.51 and their cross-sectional rank-IC is a quarter to two-fifths of the excess label's.
3. **Only the 20-day label clears realistic costs.** Its long-short decile spread breaks even at 26.7 bps per side at 100% turnover and nets +3.4% to +5.6% a year (at 100% and at measured turnover), with a gross spread t of only 1.28 over 6 out-of-sample months; horizons of 5 days or less lose 8% to 61% a year after costs. Long-only, every horizon is negative after costs against the equal-weight universe mean, because the top decile holds a lottery tail that does worse than deciles 7 to 9.
4. **The universe median is a soft benchmark.** Right skew puts the equal-weight universe's own "excess over the median" at +1.4% to +2.0% per 20 days (about 22% a year in the strategy study). Measured against the universe mean, the pilot champion's top-decile excess was positive in 3 of 5 windows, not 5 of 5.
5. **Multiple testing.** 1,106 hypotheses; 407 nominal p < 0.05 and 297 BH discoveries observed. Under a dependence-preserving month-sign-flip null the 95th percentile of nominal hits is 229, so the grid is significant at about p = 0.005. But the evidence is effectively 17 monthly draws, and the selection test shows it does not carry forward beyond about 5 days.

**Decision.** Keep `label_beat_mkt_20d` (20-session next-open excess vs the cross-sectional median, clean-masked) as the primary label. Shorter labels are statistically easier but costs dominate them; next-open entry is realistic and costs nothing in predictability; raw, excess and rank targets give identical per-date ICs so the cross-sectional target choice does not matter; vol-scaling adds nothing. Four changes:

- (a) judge economics against the equal-weight universe mean, not the median;
- (b) report rank-IC and net spread next to AUC in every league table;
- (c) carry a 40-day label as a candidate horizon for the 5-year run (needs an embargo of at least 41 sessions; untestable on the pilot);
- (d) drop the 137 ETFs (6.1% of rows) from the stock universe.

The exact column names, definitions, clean masks, embargo lengths, the ETF exclusion rule and the reporting formulas for rank-IC, net spread and the equal-weight benchmark are in `LABEL_STUDY.md`, section "Labels to carry to the 5-year run"; that section is the label specification for the production team.

`up_5d` is not a stock-selection label: regime-exposed (monthly base rate 0.37 to 0.72), close-to-close entry, 730 split-poisoned rows because it is unmasked, holdout AUC 0.507, rank-IC 0.010. It stays only as a negative control: the gap between its pooled and cross-sectional AUC measures how much "skill" is market timing.

---

## 5. Features: predictive power, sufficiency, enhancement

### 5.1 What the features predict (`ml/results/feature_study/eda_features.json`, 16 months, 469,152 clean labelled rows)

| Family | Representative | Monthly IC vs 20-day excess | Verdict |
|---|---|---|---|
| **Delivery** (NSE delivery %, the one non-price input) | `deliv_pct`, `deliv_pct_sma_20` | +0.069 (t 4.35, same sign in 15 of 16 months); +0.076 (t 3.37); works in up and down tapes (+0.106 / +0.059) | The regime anchor and the strongest pillar. Its IC fell from about +0.13 in 2025 to about +0.04 over the 2026 test months (worst −0.143 in March 2026). No peer-reviewed study of NSE delivery share exists; the signal is internal evidence only. |
| **Long momentum** | `ret_126d`, `mom_12_1`, `ret_63d` | +0.052 (t 1.6); mom_12_1 daily IC +0.099 on up dates vs +0.013 on down dates (t of difference 4.11); U-shaped deciles | Real, state-dependent, textbook (Cooper, Gutierrez & Hameed). Linear terms waste it; trees or an explicit market-state interaction capture it. |
| **52-week high / low distance** | `dist_52w_high`, `dist_52w_low` | selected in 3 of 4 yearly re-selections at 5 years | Stable carrier of trend and drawdown state. |
| **Volatility** | `atr_pct`, `vol_20`, `cs_rank_vol_20` | atr_pct averaged −0.147 for 9 months (2025-06 to 2026-02), then +0.091 from March 2026 | A regime variable, not alpha. Every challenger model that drifted off the champion collapsed onto this factor (§6.2). |
| **Liquidity / size proxies** | `log_turnover`, `cs_rank_turnover`, `amihud_20` | amihud_20 residual IC −0.040 (t −3.07, q 0.089); the only feature selected in all four yearly re-selections | Carries information the pilot's 10 features lacked. |
| **Short horizon** (mom_5/10, dist_sma_5/10/20, ret_1d, rsi_2, gap_pct, vol_z_20, flag_split_20d) | | all \|t\| < 1, sign consistency ≤ 0.56 | Dead weight. Adding more of them has negative expected value. |

Other facts that shape the design: edge is not confined to the illiquid tail (composite IC by turnover tercile 0.049 / 0.073 / 0.058 from least to most liquid); the one interaction that earns a slot is momentum × volatility (+1.05 pp double difference, same sign in 86% of months); delivery and momentum are substitutes, not a confirmation pair; daily ICs are nearly fully dependent draws (mom_12_1 lag-1 autocorrelation 0.968), so only date-block significance is honest; **March 2026 is a common-mode inversion month**, the worst IC month for 25 of 40 features at once, which is why every model's April 2026 fold was adversarial and why the 5-year fold for March 2026 is the worst month for every model (§6.3).

### 5.2 Sufficiency: three attempts to improve the features, one modest success

| Study | What was tried | Pass mark (fixed in advance) | Result |
|---|---|---|---|
| Feature study A/B (`feature_ab_verdict.json`) | 23 engineered features (regime inputs, interactions, listing age, rank twins, accumulation) in 5 variants | CV ≥ 0.5364 (control 0.5314 + 0.005), every fold ≥ 0.50 | **All five fail.** Best `lgbm_fe_top18` 0.5268 (worst fold 0.494); all 74 features 0.5135; regime variant 0.5139. Cause: redundancy (rank twins correlate 0.96 to 0.99 with existing features). |
| Feature sufficiency (`FEATURE_SUFFICIENCY.md`) | 23 features from bhavcopy fields the pilot never read (`trades`, `vwap`, `last`, `prev_close`, delivery value), Amihud illiquidity, idiosyncratic vol, a 12-cluster sector proxy from return correlations | residual IC vs the champion's 10 ranks, BH q ≤ 0.1; then the same harness A/B | **2 of 23 pass BH**: `deliv_value_share_20` (q 0.055) and `amihud_20` (q 0.089), both re-expressions of delivery and liquidity. The A/B with the top 5 reached 0.5342 (fail), and its selection window included the CV months. Fields never read carry no robust signal (lowest q 0.24). The sector proxy is real (recovers IT, PSU banks, private banks, defence, metals) but adds nothing (q ≥ 0.56). |
| 5-year nested re-selection (`nested_selection.json`) | The pilot's selection method re-run inside each training history, once per calendar year, on 50 base features + the 2 BH survivors | none (descriptive) | `amihud_20` selected every year; `deliv_value_share_20`, `dist_52w_high`, `atr_pct`, `vol_20` in 3 of 4 years. Selected sets overlap in only 2 to 3 features year to year; chosen k alternates 15 / 5 / 15 / 5. The pilot's 10 overlap the yearly picks by 4 / 1 / 8 / 2. |

**Verdict on sufficiency.** The end-of-day bhavcopy has been mined to its resolvable limit at this sample size. Two liquidity and delivery re-expressions carry information the 10-feature champion lacked and earn a place in the candidate set; nothing else does. Feature selection itself is unstable (gate 4 fails) and, at 5 years, buys nothing over giving LightGBM every feature (0.5359 nested vs 0.5366 all features, paired delta −0.0007 [−0.0052, +0.0038], 18 of 43 fold wins: a tie). **The candidate set is therefore the 52 end-of-day features; the single-model reference uses all of them without hand selection, and the ensemble as tested re-selects yearly from the same 52** (an all-52 ensemble A/B is queued). Further engineering on these inputs is stopped. The remaining feature upside is external data, ranked in §11.

### 5.3 What the pilot got wrong about features, and how it was found

The pilot's 10 features were ranked by univariate AUC on the four CV test months and by permutation importance on the June test month. The red team's honest re-run (`AUDIT.md`, T11) scored 0.5132 instead of 0.5307, level with random 10-feature subsets (0.513 ± 0.006). At 5 years the same subset scores 0.5251 and loses to all features in 32 of 43 folds. The mechanism is visible in the yearly re-selections: the pilot's set is the 2025/2026 regime's set (overlap 8 of 10 with the 2025 pick, 1 of 10 with 2024's).

---

## 6. Models

### 6.1 Pilot league (6 months, 4 CV folds + holdout; `ml/MODEL_SELECTION.md`, clean reruns where available)

| Model | Family | CV AUC | Worst fold | Holdout AUC | Note |
|---|---|---:|---:|---:|---|
| LightGBM, 10 selected features | GBM | 0.5314 | 0.507 | 0.518 | selection-inflated; honest nested value 0.5132 |
| L2 logistic (= L1 = elastic net) | linear | 0.5171 | 0.487 | 0.527 | |
| Random forest | trees | 0.5167 | 0.471 | 0.533 | |
| REINFORCE contextual bandit | RL | 0.5085 | 0.483 | 0.568 | fails to beat its own init on 2 of 4 folds |
| Decision tree | trees | 0.5058 | 0.488 | 0.536 | |
| LightGBM, all features | GBM | 0.5044 | 0.481 | 0.563 | |
| MLP | deep | 0.5025 | 0.481 | 0.538 | |
| XGBoost | GBM | 0.5023 | 0.480 | 0.565 | |
| LSTM | deep | 0.5018 | 0.482 | 0.542 | |
| Momentum rule (1 feature) | baseline | 0.4934 | 0.487 | 0.530 | |
| GRU | deep | 0.4889 | 0.473 | 0.547 | |

Twelve of thirteen candidates scored better on the single holdout than on CV, and the two views rank models in near-opposite order (Spearman −0.60): one regime change sitting on the CV/holdout boundary. That is why the program moved to 43 folds.

### 6.2 State-of-the-art challengers (same folds; `ml/results/sota/SOTA_MODELS.md`; bar fixed in advance: CV ≥ 0.5364 with every fold ≥ 0.50)

| Model | CV AUC ± sd | Worst fold | Holdout AUC | Rank-IC (Newey-West t) | Pass |
|---|---|---:|---:|---|---|
| Rank-average ensemble (LightGBM + LambdaRank + CatBoost) | **0.5357 ± 0.008** | **0.524** | 0.548 | +0.065 (3.6) | no, by 0.0007 |
| CatBoost, fixed 600 trees | 0.5299 ± 0.012 | 0.512 | 0.523 | +0.055 (3.5) | no |
| LightGBM LambdaRank | 0.5293 ± 0.024 | 0.497 | 0.566 | +0.050 (2.1) | no |
| LightGBM Huber regression | 0.5223 ± 0.007 | 0.513 | 0.530 | +0.046 (3.3) | no (most stable) |
| Cross-sectional set-attention transformer | 0.5197 ± 0.035 | 0.493 | 0.501 | +0.027 (0.7) | no |
| PatchTST-lite (temporal transformer) | 0.5143 ± 0.044 | 0.452 | 0.448 | +0.024 (0.6) | no |
| DLinear (sequence control) | 0.5103 ± 0.039 | 0.457 | 0.461 | +0.016 (0.4) | no |

Why trees win here: the signal is weak and lives in a few slow features (IC about 0.05); extra capacity mainly buys the ability to fit the training window's regime, and every challenger that drifted collapsed onto the volatility factor (LambdaRank long high-vol: score correlation with `atr_pct` +0.66; the networks short it: −0.52 to −0.59); 140 to 230 training dates with overlapping labels are 7 to 11 independent cross-sections; and the March-2026 break sits inside every early-stopping validation tail, so each early-stopped model paid for it while the champion's fixed 300 trees did not. The CatBoost result shows the gap was protocol, not algorithm: with fixed trees it ties LightGBM. The literature agrees on all three points (`SOTA_FORECASTING.md` §1, §3, §4): on engineered tabular features GBMs beat deep nets; temporal transformers lose to linear models; zero-shot time-series foundation models have negative R² on daily returns.

### 6.3 Five-year walk-forward (43 monthly folds, rolling 504-session training window, 22-session embargo; `ml/results/scale5y/`)

| Model | Features | CV AUC ± sd | 95% CI (20-session blocks) | Folds ≥ 0.50 | Worst fold | Holdout AUC (decile spread) | Mean fold decile spread (positive folds) |
|---|---:|---|---|---:|---:|---:|---|
| LightGBM, all features (`all51`) | 50 | **0.5366 ± 0.043** | [0.5254, 0.5498] | 35 / 43 (81%) | 0.453 (2026-03) | 0.533 (−0.61%) | +1.25% (30 / 43) |
| LightGBM, nested yearly selection (`nested_lgbm`, exit-date purge) | 5 to 15 | 0.5359 ± 0.041 | [0.5250, 0.5483] | 37 / 43 (86%) | 0.431 (2026-03) | 0.528 (−0.61%) | **+1.32% (33 / 43)** |
| Rank ensemble (`nested_ensemble_rank`: LightGBM + LambdaRank + CatBoost on the nested sets) | 5 to 15 | 0.5330 ± 0.036 | [0.5232, 0.5438] | **39 / 43 (91%)** | 0.463 (2025-01) | **0.553 (+2.86%)** | |
| CatBoost, 600 fixed trees (ensemble member) | 5 to 15 | 0.5378 ± 0.043 | | 37 / 43 (86%) | 0.426 (2026-03) | 0.529 (−0.51%) | |
| LambdaRank (ensemble member) | 5 to 15 | 0.5032 ± 0.045 | | 25 / 43 (58%) | 0.361 (2025-01) | 0.572 (+6.68%) | |
| LightGBM, pilot 10 features (`champion10`) | 10 | 0.5251 ± 0.038 | [0.5150, 0.5362] | 31 / 43 (72%) | 0.449 (2025-05) | 0.529 (−0.43%) | +0.74% (27 / 43) |
| L2 logistic, all features (`lr_l2`) | 50 | **0.5415 ± 0.060** | [0.5257, 0.5592] | 35 / 43 (81%) | **0.379** (2026-03) | 0.509 (**−3.62%**) | +1.08% (25 / 43) |
| L2 logistic, nested selection (`nested_lr_l2`) | 5 to 15 | 0.5430 ± 0.064 | [0.5263, 0.5620] | 34 / 43 (79%) | 0.367 (2026-03) | 0.517 (−0.90%) | |
| Momentum rule (`baseline_mom`) | 1 | 0.4951 ± 0.035 | [0.4851, 0.5053] | 17 / 43 (40%) | 0.407 (2026-03) | 0.530 (**+2.95%**) | +0.27% (24 / 43) |

Head-to-head by fold: all features beat the pilot's 10 in 32 of 43; nested beat the pilot's 10 in 29 of 43; nested vs all features 18 of 43 (a tie); all features beat the momentum rule in 34 of 43.

**Paired 20-session block bootstrap** (B = 1000, 45 blocks per replicate over the pooled 881 test dates, identical draws for every model; `bootstrap_5y.json`): nested selection vs all features −0.0007 [−0.0052, +0.0038] (a tie); pilot 10 features vs all features −0.0115 [−0.0159, −0.0071] (a real loss); nested LightGBM vs L2 logistic −0.0056 [−0.0150, +0.0024]; ensemble vs L2 logistic −0.0085 [−0.0222, +0.0027]. The program cannot claim that any machine-learning model beats the linear benchmark on AUC.

**Regimes** (defined from market data before any AUC was split by them; `regimes_5y.md`): models score higher in down months (nested LightGBM 0.571 over 14 months) than in up months (0.519 over 29), and higher in low-volatility months (0.547) than in high-volatility ones (0.524). One episode lifts the five-year mean: the September 2025 to February 2026 run (five of six months down, four low-volatility) carries every model to about 0.60; without it and March 2026, nested LightGBM averages 0.5267 over the other 36 months. March 2026 was a V-shaped rebound after the February sell-off (equal-weight universe +9.2% in 20 days, volatility 33%) in which 62% of features had their IC against its usual sign; six of 43 months had a majority of features inverted (2023-07, 2024-01, 2025-04, 2025-05, 2026-03, 2026-04).

**By calendar year** (mean fold AUC; **the 2023 folds train on short windows** because the dataset starts in October 2022: 41,733 training rows for 2023-01, 292,582 for 2023-12, the full 504-session window of 580k+ rows only from 2024-10):

| Year | Folds | nested_lgbm | all51 | champion10 | lr_l2 | baseline_mom |
|---|---:|---:|---:|---:|---:|---:|
| 2023 (short training windows) | 12 | 0.517 | 0.509 | 0.498 | 0.515 | 0.502 |
| 2024 | 12 | 0.536 | 0.551 | 0.538 | 0.549 | 0.500 |
| 2025 | 12 | 0.557 | 0.552 | 0.534 | 0.573 | 0.489 |
| 2026 (Jan to Jul) | 7 | 0.533 | 0.533 | 0.534 | 0.521 | 0.488 |

Every model moves together month to month: all of them run 0.60 to 0.66 from September 2025 to February 2026 and all of them crash in March 2026 (0.37 to 0.45), the inversion month the EDA identified. The common component is the market regime, not the algorithm.

**Four findings from the 5-year run.**

1. **Feature selection did not transfer, and is not needed.** The pilot's 10 features lose to all features by 0.0115 AUC [0.0071, 0.0159] and in 32 of 43 months; they average 0.4979 in 2023. Honest yearly re-selection recovers the full-feature score exactly (0.5359 vs 0.5366) at the price of unstable, alternating sets, and it helped only in 2023, with small training sets. LightGBM's own regularisation does the job. The single-model reference uses all 52 features.
2. **The linear model has the highest mean and the worst risk.** L2 logistic scores 0.5415 (0.5430 nested), above LightGBM, so pre-registered gate 1 fails as written. It is the purest defensive-factor ranker in the league: per-date score correlation −0.50 with `atr_pct`, −0.45 with Amihud illiquidity and +0.49 with the 52-week high (LightGBM: −0.30, −0.29, +0.25). AUC rewards that tilt in down months (0.607) and punishes it in rebounds (0.379 in March 2026); its month-to-month spread is 1.4× LightGBM's and its holdout decile spread is −3.6%, with its bottom decile its best decile. Nonlinearity here buys stability and sane tails, not mean accuracy, which matches the literature's modest GBM-over-linear gains (GKX: 0.33 to 0.40% vs 0.11 to 0.27% monthly R²).
3. **AUC and tradability disagree.** AUC 0.536 with an IC t of 6 coexists with no long-only edge (§7.2). The label "beat the universe median" rewards low-volatility names, which cross the median often but do not beat the mean of a right-skewed, rising universe, so the classifiers' top deciles are defensive: nested LightGBM's trails the equal-weight universe by 0.58% per 20 days in up months, net of costs. The negative holdout decile spreads (every classifier −0.4% to −3.6%, the momentum rule +2.95%) are the same tilt over one 32-day window; across the 43 folds the classifiers' mean decile spreads are positive (+1.25% to +1.32%, positive in 30 to 33 months). The ensemble shows the fix: adding the high-volatility LambdaRank makes the blended score volatility-neutral (correlation with `atr_pct` −0.05), costs 0.003 of AUC and turns −0.7% a year into +7.0% a year over the universe. AUC is necessary, not sufficient; models are judged on net excess over the equal-weight universe.
4. **Hyperparameters are a mild contamination of 2026.** The LightGBM configuration (num_leaves 63, learning rate 0.05, 300 trees, feature and bagging fraction 0.8, min_data_in_leaf 200) was chosen in the pilot, which saw April to July 2026. Those 4 folds and the holdout are therefore not fully out-of-sample for the configuration; the 39 folds from 2023-01 to 2026-03 are. Removing those folds leaves the ranking unchanged (39 folds, 2023-01 to 2026-03: all features 0.5376, nested 0.5364, pilot 10 features 0.5240, L2 logistic 0.5441, momentum rule 0.4956; derived from the per-fold JSONs).

### 6.4 Bifurcation: what is dropped and the evidence

| Dropped | Evidence |
|---|---|
| Reinforcement learning (REINFORCE contextual bandit) | CV 0.5085; fails to beat its own initialisation on 2 of 4 folds; its own portfolio simulation loses to a free momentum heuristic out of sample; its best numbers come from 30 holdout dates (DSR 0.38). Literature: "no decent profitability" for RL in cross-sectional selection; RL works where a simulator exists (execution, hedging). |
| GRU / LSTM / MLP | At or below chance on CV (0.489 / 0.502 / 0.503). A 20-session temporal view adds nothing the features do not already carry. |
| Temporal transformer (PatchTST-lite), DLinear | 0.514 / 0.510 CV, 0.448 / 0.461 holdout; nearly identical fold paths, so attention adds about 0.004 over a two-layer linear model; both are a low-volatility bet in disguise. |
| Cross-sectional set-attention transformer | 0.520 ± 0.035, April and May below 0.50, holdout 0.501, rank-IC not significant. The label is already cross-sectional and the rank features already normalise across stocks. |
| Time-series foundation models (Chronos, TimesFM) | Not run; literature reports negative zero-shot R² on daily stock returns and direction accuracy near 50%. |
| 51-feature LambdaRank and CatBoost variants, Huber as a scorer | Below the champion; Huber stays only as an IC monitor (most stable fold path). |
| Pilot 10-feature subset | 0.5251 at 5 years; selection fitted to the 2026 regime. |
| Decision tree, L1 / elastic-net logistic | Dominated by their ensembles; identical to L2 to three decimals. |
| Short leg, illiquid tail, top-20 books, `up_5d` native book | Strategy study §7: shorts need SLB or F&O (about 200 names), the bottom decile is small caps with unmodelled borrow; the illiquid tail caps capacity at ₹257 cr; top-20 books lose to the universe (−10.5% a year); the 5-day book nets −0.1% a year. |

---

## 7. Strategy: is there a promising return on capital?

### 7.1 Pilot (113 signal dates, April to September 2026; `ml/results/strategy/STRATEGY.md`)

Engine: 20 overlapping tranches, one rebalanced per session, entry at the next open and exit 20 sessions later, exact open-to-open marks (reproduces the label on 99.995% of rows), costs netted against the tranche replaced, daily statistics weighted by exposure.

| Book (20 bps per side) | Annualised net | Active vs equal-weight universe | IR [95% CI] | Max drawdown | Turnover |
|---|---:|---:|---|---:|---:|
| Champion top decile, long-only (~155 names) | +30.6% | **+4.2%** | 0.99 [−2.36, +4.34] | −3.1% | 80% |
| Champion liquid-tercile top decile (~51 names, capacity ₹1,129 cr) | +24.2% | +4.0% (CV +7.1%, holdout −4.5%) | 0.72 [−1.62, +2.57] | | |
| Momentum heuristic (free) | +36.8% | +11.4% (beta 1.28; beta-adjusted alpha +4.0% vs champion +8.6%) | 1.53 [−1.20, +3.56] | −6.4% | 86% |
| Equal-weight universe (passive) | +26.1% | | | −4.8% | 5% |

Deflated Sharpe with N = 96 trials: champion active book PSR 0.75, **DSR 0.08**; best cell in the whole grid (RL liquid long-short) DSR 0.38. No cell survives. At its observed IR the champion needs about 705 trading days (2.8 years) of track record to reach PSR 95%. What does look solid is cost headroom (break-even 39 to 41 bps per side against a realistic 15 to 25) and capacity (about ₹1,100 cr in the liquid book).

Two measurement lessons from this study now bind the whole program: the equal-weight universe beats the universe median by +1.78% per 20 days (skew, not skill), so every "beats the median" hit rate is inflated; and the naive fully-invested average would have flipped the champion's active return from +4.2% to −5.3% a year, so exposure-weighting is mandatory.

### 7.2 Five years (913 signal dates, 2023-01-02 to 2026-09-16; `ml/results/scale5y/portfolio_5y.json`)

Same engine and costs as the pilot. **N = 177 trials was fixed in the code before any portfolio number existed**: 10 model configurations and 24 books on these folds, plus the pilot's 77 configurations and 66 portfolio cells.

| Book (20 bps per side) | Annualised net | Excess vs equal-weight universe | Sharpe [95% CI] | IR [95% CI] | Max drawdown | Turnover | Months beating the universe | PSR | DSR (N = 177) |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| Equal-weight universe (passive) | +19.4% | | 0.69 [−0.27, 1.80] | | −27.8% | 7% | | | |
| Nested LightGBM, top decile | +18.7% | −0.7% | 0.73 [−0.19, 1.75] | −0.11 [−1.21, 0.96] | −27.0% | 67% | 20 / 45 | 0.42 | 0.000 |
| Nested LightGBM, liquid top decile | +16.3% | −3.4% | 0.56 | −0.53 [−1.56, 0.45] | −29.3% | 72% | 18 / 45 | 0.16 | 0.000 |
| LightGBM all features, top decile | +18.2% | −1.2% | 0.71 | −0.21 [−1.37, 0.94] | −27.9% | 68% | 20 / 45 | 0.35 | 0.000 |
| **Rank ensemble, top decile** | +26.5% | **+7.0%** | 0.99 [0.06, 2.10] | **1.26 [0.32, 2.37]** | −28.9% | 70% | 33 / 45 | 0.99 | 0.163 |
| Rank ensemble, liquid top decile (the pre-registered paper book) | +25.5% | +5.7% | 0.88 [−0.01, 1.88] | 0.85 [−0.21, 1.99] | −29.1% | 77% | 29 / 45 | 0.94 | 0.040 |
| Rank ensemble, long-short | +16.0% | | **1.77 [0.82, 2.91]** | | −8.3% | 70% | 34 / 45 | 1.00 | **0.490** |
| L2 logistic, top decile | +16.5% | −2.9% | 0.71 | −0.31 | −20.1% | 43% | 17 / 45 | 0.28 | 0.000 |
| Momentum rank, top decile | +19.2% | −0.2% | 0.60 | +0.09 | −29.6% | 87% | 25 / 45 | 0.57 | 0.001 |

- **Costs.** At 10 / 40 bps per side the ensemble's top-decile excess is +8.8% / +3.4% a year; nested LightGBM's is +1.0% / −4.1%.
- **Capacity.** The full ensemble top decile carries about ₹245 crore (30% of its names trade under ₹5 crore a day); the liquid book about ₹1,050 crore.
- **Deflation.** The expected maximum Sharpe under the null at N = 177 is 1.79 a year; every book misses it. Counting only this run's 34 trials, the ensemble long-short book's DSR would be 0.75. That book also needs shorts that NSE cash offers only on about 200 F&O names.
- **Why the ensemble and not the classifiers.** It is close to volatility-neutral while the classifiers lean to low-volatility names (§6.3, finding 3); its excess is positive in every calendar year (+0.43% to +0.71% per 20 days) with a beta of 1.01 to the universe. It is also the best of 34 trials in this run, which is exactly what the DSR charges for.

**ROC verdict: no capital.** The ensemble's economics are the one result in the program with an interval clear of zero, and they fail the multiple-testing test. The historical record cannot reach DSR 0.95 at N = 177; only a fresh, frozen paper track record can (about 4 years at IR 0.85 for PSR 95%).

---

## 8. Integrity: what the red team found (`ml/results/audit/AUDIT.md`, 15 tests)

| Area | Result |
|---|---|
| Reproduction | champion CV 0.531445 and holdout 0.517996 reproduce exactly |
| Null distribution | label permutation within date, 10 seeds: CV 0.5000 ± 0.0011 (max 0.5010); champion z = 28 against this null |
| Leakage | features shifted by +1 session: +0.004 AUC only; by +21 sessions: 0.945 (the detector works); labels recomputed from raw EOD: 471,867 labels, max difference 0; point-in-time universe identical; 0 of 450 champion feature values change when recomputed from data ≤ t |
| Embargo | 3 of 1.62M training rows exit on or after test start; 81 labels span more than 21 sessions. Fixed at 5 years by purging on each label's actual exit date (143 rows purged across the 43 folds) |
| Noise control | 5 of 10 pilot champion features sit inside the univariate AUC range of persistent pure noise (max 0.512); adding 30 iid noise features raised CV by +0.002 |
| Selection bias | features chosen on CV test months (T9 fail); honest nested re-selection 0.5132 vs claimed 0.5307 (T11); 5 random 10-feature sets 0.513 ± 0.006, 4 of 5 beat the champion on the holdout (T12) |
| Best-of-N | 38 full configurations (151 with screens) on the pilot task. Against the permutation σ the champion is distinguishable (P ≈ 10⁻¹⁷³); against month-level σ narrowly (P 0.002 to 0.011); against the cross-configuration spread it is not (P 0.34) |
| Dependence | 10-session block CI for the champion's CV mean [0.517, 0.545]; champion minus momentum on the holdout −0.013 [−0.034, +0.004] |

**Corrections made.** `ml/MODEL_SELECTION.md` now opens with the correction; the PR description is updated with it; the 5-year protocol nests selection inside each training window, purges on exit dates, and reports block bootstraps. The allowed wording for the pilot is the audit's: *"slightly better than chance … not a data or code artefact … not evidence of a tradable edge."*

---

## 9. Status board

**Working**

- Data pipeline: 5 years ingested, resilient to archive quirks, no duplicate sessions, resume-safe, 19 of 19 tests.
- Evaluation harness: purged walk-forward, nested selection, exit-date purging, block bootstraps, pre-registered pass marks, one result schema that every team used.
- The signal: delivery and long momentum, AUC 0.53 to 0.54 over 43 months, above 0.50 in 81% to 86% of months, consistent with published frontier numbers.
- Model choice: LightGBM with fixed trees on all features; it is the most stable thing in the league and nothing from deep learning, ranking losses or attention beats it.
- Honesty: the one inflated claim was found by the program's own red team and corrected before any capital decision.
- The ensemble's five-year economics: +7.0% a year over the universe with an interval clear of zero, positive in every year; the only book in the program with that property.

**Not working**

- Tradable edge: not demonstrated. No single model's long-only book beats the equal-weight universe net of costs over five years; the ensemble's does, with DSR 0.16 (0.04 for the paper book) at 177 trials.
- Pre-registered gates: nested LightGBM 0 of 5, all-features LightGBM 0 of 5, ensemble 1 of 5.
- Machine learning over a linear model: not shown; the logistic model's mean AUC is higher and every paired interval includes zero.
- Feature selection: unstable year to year; buys nothing on AUC.
- Extreme-decile economics: the top decile holds a lottery tail in down markets; book construction must change (liquidity filter, equal-weight benchmark, possibly top quintile or rank-weighted rather than top decile).
- The linear model as a scorer: highest mean, worst tails; demoted to drift monitor.
- Deep learning, transformers, foundation models, reinforcement learning: nothing beats trees here; stopped.

**Pending**

- Nothing. Every run in the program is complete and committed. (The label study closed with a clean end-to-end rerun that reproduced all 13 of its JSON outputs with zero numeric differences.)

**Unknown (cannot be decided with this data)**

- Whether the ensemble's +7% a year is skill or a favourable factor mix over 45 months of one, mostly rising, market.
- Whether delivery % is a durable signal or a 2025 artefact: its IC fell by two-thirds after March 2026; it needs the 5-year by-year test and, ideally, independent literature that does not exist.
- Anything that needs several market cycles: market-state conditioning, seasonality, sector rotation.
- Realistic costs in the illiquid tail: name-level spread and impact are not modelled.

---

## 10. Product and monitoring specification (paper trading, no capital)

**Daily job (after EOD ingest).** Ingest → feature build → score every universe name with the frozen rank ensemble, the LightGBM all-features reference and the L2 logistic monitor → write ranks and the liquid-tercile top-decile paper list → paper-portfolio mark-to-market with 20 overlapping tranches at 20 bps per side → dashboard.

**Monthly job.** Retrain the three ensemble members on the trailing 504 sessions (22-session embargo, exit-date purge) on the year's frozen feature set, re-selected once a year; run the LightGBM reference as champion-challenger; log the trial count (the paper book is N = 1 and stays N = 1).

**Alerts (pre-registered thresholds).**

| Signal | Threshold | Why |
|---|---|---|
| Delivery monthly IC (`deliv_pct_sma_20` vs 20-day excess) | below +0.02 for 2 consecutive months | the pillar faded from +0.13 to +0.04 after March 2026 |
| Monthly fold AUC of the live model | below 0.50 | 2026-03-type inversion months recur; floor is the headline stability metric |
| Rank-IC, Newey-West t over trailing 12 months | below 2.0 | the honest significance statistic |
| L2 logistic coefficient sign flips, top 5 by magnitude | any flip | regime drift, cheap to compute |
| Feature population stability index | > 0.25 on any champion feature | distribution drift (atr_pct kurtosis ≈ 13,900: tails move) |
| Paper book active return vs equal-weight universe, trailing 6 months | IR confidence interval entirely below zero | the economics, measured the honest way |
| Feature-inversion monitor | more than half of the features with IC against their usual sign in a month | 6 of 43 months were inversion months and every model failed in March 2026 |
| Ensemble score correlation with `atr_pct`, per date | absolute value above 0.20 for a month | the book's edge rests on staying volatility-neutral (−0.05 as tested) |
| Universe ETF count, split flag rate | ETFs > 0 after the exclusion rule; `flag_split_20d` > 1% | data integrity |

**Dashboard.** The 43-fold AUC strip with live months appended; IC by family; paper book vs equal-weight universe with the DSR trial count; gate table; data-quality tiles (sessions, duplicates, split flags, ETFs).

**Not a product yet.** No order routing, no short book, no capital. The program's own gate table is the release criterion.

---

## 11. Recommendations, ranked by expected value per unit of effort

1. **Paper-trade the ensemble's liquid book as one frozen, pre-registered strategy from November 2026** with the specification in §10 and no new trials (N = 1). At IR 0.85 it needs about 4 years (994 sessions) of track record to reach PSR 95%; the clock starts only when the book exists.
2. **Pre-registered test of volatility-neutral construction:** each classifier's score residualised on volatility and size per date, pass mark fixed in advance. The ensemble's +7% a year says this is where the money is; a deliberate construction should capture it without depending on a LambdaRank member that scores 0.503 on its own.
3. **Corporate-actions feed** (NSE corporate actions, splits and bonuses, ex-dates and ratios). A data-integrity item, not a feature item: it removes split artefacts from every rolling feature and from the 0.4% to 0.6% of labels the mask drops.
4. **Two A/Bs with fixed pass marks:** LightGBM on all 52 features (50 plus `amihud_20` and `deliv_value_share_20`) against the 50; and the ensemble on all 52 without yearly re-selection against the ensemble as tested.
5. **Delivery validation, pre-registered:** IC by year, liquidity tier and market state, orthogonalised against turnover and volatility. The strongest signal in the program has no external literature.
6. **Name-level costs:** high-low spread estimator plus square-root impact by liquidity tier; asymmetric STT and stamp duty. This is what turns the 39 to 41 bps break-even into a real capacity number.
7. **The short side only where it exists:** long-short restricted to F&O names via stock futures, with borrow costs and 40 bps per side. The ensemble long-short book (Sharpe 1.77, DSR 0.49) is the only candidate; it is untested under those constraints.
8. **Address the March-2026 failure mode:** market-state inputs (trailing universe momentum, drawdown, days since a sell-off) pre-registered against the full-feature baseline, plus the monthly feature-inversion monitor. Six of 43 months were inversion months; the 5-year window has enough sell-offs to test on.
9. **External data in order of mechanism strength:** sector / industry classification (industry momentum, sector-neutral ranking); index and F&O membership (shortability, inclusion pressure); fundamentals (value, profitability, accruals, earnings surprise); options-implied volatility and India VIX (the regime conditioner); institutional flows; surveillance lists, SLB and pledges.
10. **Book construction research:** top quintile vs top decile, rank-weighting, turnover bands or hysteresis (Novy-Marx & Velikov: a buy/hold spread is the best cost mitigation). Deterministic, cheap, and it replaces the only thing RL was adding.
11. **Hygiene still open:** probability of backtest overfitting across the candidate set, combinatorial purged CV for the final choice, uniqueness weights for overlapping labels, history before 2021.
12. **Do not spend the next unit of effort on** transformers, foundation models, reinforcement learning, or more bhavcopy-derived feature engineering. The evidence in §5 and §6 is against all four.

---

## 12. What this program does not claim

- It does not claim a tradable edge. No model passes more than one of five pre-registered gates, and the best Deflated Sharpe in the program is 0.49, for a long-short book that cannot be traded as tested.
- It does not claim that machine learning beats a linear model on this problem; the logistic benchmark's mean AUC is higher and every paired interval includes zero.
- It does not claim that the ensemble's +7% a year over the universe is skill rather than a favourable volatility-factor mix over 45 months of one, mostly rising, market.
- It does not claim that any model is reliable month to month: the single-model candidates fall below 0.50 in 6 to 9 of 43 months, and every candidate did in March 2026.
- It does not claim the delivery signal is durable. Its IC fell by two-thirds after one regime break and there is no external literature.
- It does not claim the 2023 fold results are representative: those models trained on 2 to 12 months of data.
- It does not claim the 2026 folds are fully out-of-sample for the LightGBM configuration, which was tuned on them in the pilot.
- It does not claim that AUC differences of 0.01 between models are decidable on these samples: the paired block-bootstrap intervals are about ±0.005 to ±0.015 wide.
- It does not claim realistic costs for the illiquid tail or for any short book.

---

## Appendix A. Reproduction

```bash
# data
python3 nse_historical_ingest.py --start 2021-10-01 --end 2026-10-16          # 5-year store (resume-safe)
python3 -m ml.data                                                              # pilot dataset (ml/data/)
python3 -m ml.build_5y                                                          # 5-year dataset (ml/data_5y/)
# studies
python3 -m ml.eval_aggregate && python3 -m ml.make_report                       # pilot league + report
python3 -m ml.eda_features && python3 -m ml.feature_ab && python3 -m ml.make_feature_study
python3 -m ml.feature_sufficiency
python3 -m ml.label_study
python3 -m ml.audit
python3 -m ml.models.sota
python3 -m ml.strategy_backtest
# 5-year walk-forward
python3 -m ml.scale5y --data ml/data_5y --out ml/results/scale5y --models champion10 all51 lr_l2 baseline_mom --train-sessions 504 --n-jobs 2 --n-threads 2
python3 -m ml.scale5y_nested --stages prep,select,run --n-jobs 2
python3 -m ml.scale5y_nested --stages run --ensemble
python3 -m ml.scale5y_report
# this report
python3 -m ml.make_program_report
```

Seed 108 everywhere; OMP_NUM_THREADS=2 on the shared 4-core box.

## Appendix B. Trial ledger (for Deflated Sharpe and best-of-N accounting)

Pilot primary task: 38 full-protocol configurations, 151 including hyper-parameter and univariate screens (`AUDIT.md` T7). Strategy grid: 96 trials (60 scorer × basket cells, 6 diagnostics, 30 program configurations). SOTA study: 12 configurations. Feature A/Bs: 5 + 6 variants. Label study: 7 model-level runs, 1,106 feature-label hypotheses. Five-year run: N = 177, fixed in the code before any portfolio number existed: 10 model configurations and 24 books on the 43 folds, plus the pilot's 77 configurations and 66 portfolio cells (`portfolio_5y.json`). The paper book from November 2026 is N = 1 and must stay N = 1.
