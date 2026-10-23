# SuryaDhana research program: final report

**Date:** 2026-10-19 · **Program lead:** evaluation lead (this session) · **Scope:** NSE cash equities, end-of-day bhavcopy data, 5 years (2021-10 to 2026-10) · **Companion report:** `ml/report/program_report.html` (built by `python3 -m ml.make_program_report`)

**Status: complete; improvement phases added 2026-10-22 (§13) and 2026-10-23 (§14). Verdict unchanged: no capital; one model-side gain above the bar (an expanding training window, exploratory) now runs in the forward record as a challenger.** Section 1's recommendation, the Model row of its deliverables table and §11 item 1 are superseded: since 2026-10-19 the paper book of record is the volatility+size-neutral LightGBM construction of §13.7 (primary: full-universe top decile; capacity: its liquid-tercile version), with the rank ensemble as challenger, the plain score as reference and, since 2026-10-23, the expanding-window challenger and its capacity version (§14.4). The 5-year walk-forward, its paired block bootstrap, regime table, rank-ensemble challenger and paper portfolio are all in (`ml/results/scale5y/SCALE5Y.md`). Every number below is read from a committed JSON or Markdown artifact named in the text; nothing is estimated from memory.

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
| **Short horizon** (mom_5/10, dist_sma_5/10/20, ret_1d, rsi_2, gap_pct, vol_z_20, flag_split_20d) | | all \|t\| < 1, sign consistency no better than 0.63 | Dead weight. Adding more of them has negative expected value. |

Other facts that shape the design: edge is not confined to the illiquid tail (composite IC by turnover tercile 0.049 / 0.073 / 0.058 from least to most liquid); the one interaction that earns a slot is momentum × volatility (+1.1 pp double difference, same sign in 86% of months); delivery and momentum are substitutes, not a confirmation pair; daily ICs are nearly fully dependent draws (mom_12_1 lag-1 autocorrelation 0.968), so only date-block significance is honest; **March 2026 is a common-mode inversion month**, the worst IC month for 25 of 40 features at once, which is why every model's April 2026 fold was adversarial and why the 5-year fold for March 2026 is the worst month for every model (§6.3).

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
| XGBoost | GBM | 0.5023 | 0.479 | 0.565 | |
| LSTM | deep | 0.5018 | 0.482 | 0.542 | |
| Momentum rule (1 feature) | baseline | 0.4934 | 0.487 | 0.530 | clean rerun 0.4906 |
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
| Rank ensemble (`nested_ensemble_rank`: LightGBM + LambdaRank + CatBoost on the nested sets) | 5 to 15 | 0.5330 ± 0.035 | [0.5232, 0.5438] | **39 / 43 (91%)** | 0.463 (2025-01) | **0.552 (+2.86%)** | |
| CatBoost, 600 fixed trees (ensemble member) | 5 to 15 | 0.5378 ± 0.043 | | 37 / 43 (86%) | 0.426 (2026-03) | 0.529 (−0.51%) | |
| LambdaRank (ensemble member) | 5 to 15 | 0.5032 ± 0.045 | | 25 / 43 (58%) | 0.361 (2025-01) | 0.572 (+6.68%) | |
| LightGBM, pilot 10 features (`champion10`) | 10 | 0.5251 ± 0.038 | [0.5150, 0.5362] | 31 / 43 (72%) | 0.449 (2025-05) | 0.529 (−0.43%) | +0.74% (27 / 43) |
| L2 logistic, all features (`lr_l2`) | 50 | **0.5415 ± 0.060** | [0.5257, 0.5592] | 35 / 43 (81%) | **0.379** (2026-03) | 0.509 (**−3.62%**) | +1.08% (25 / 43) |
| L2 logistic, nested selection (`nested_lr_l2`) | 5 to 15 | 0.5430 ± 0.064 | [0.5263, 0.5620] | 34 / 43 (79%) | 0.367 (2026-03) | 0.517 (−0.90%) | |
| Momentum rule (`baseline_mom`) | 1 | 0.4951 ± 0.035 | [0.4851, 0.5053] | 17 / 43 (40%) | 0.407 (2026-03) | 0.530 (**+2.95%**) | +0.27% (24 / 43) |

Head-to-head by fold: all features beat the pilot's 10 in 32 of 43; nested beat the pilot's 10 in 29 of 43; nested vs all features 18 of 43 (a tie); all features beat the momentum rule in 34 of 43.

**Paired 20-session block bootstrap** (B = 1000, 45 blocks per replicate over the pooled 881 test dates, identical draws for every model; `bootstrap_5y.json`): nested selection vs all features −0.0007 [−0.0052, +0.0038] (a tie); pilot 10 features vs all features −0.0115 [−0.0159, −0.0071] (a real loss); nested LightGBM vs L2 logistic −0.0056 [−0.0150, +0.0024]; ensemble vs L2 logistic −0.0085 [−0.0222, +0.0027]. The program cannot claim that any machine-learning model beats the linear benchmark on AUC.

**Regimes** (defined from market data before any AUC was split by them; `regimes_5y.md`): models score higher in down months (nested LightGBM 0.571 over 14 months) than in up months (0.519 over 29), and higher in low-volatility months (0.547) than in high-volatility ones (0.524). One episode lifts the five-year mean: the September 2025 to February 2026 run (five of six months down, four low-volatility) carries every model to a window mean of 0.58 to 0.63; without it and March 2026, nested LightGBM averages 0.5267 over the other 36 months. March 2026 was a V-shaped rebound after the February sell-off (equal-weight universe +9.2% in 20 days, volatility 33%) in which 62% of features had their IC against its usual sign; six of 43 months had a majority of features inverted (2023-07, 2024-01, 2025-04, 2025-05, 2026-03, 2026-04).

**By calendar year** (mean fold AUC; **the 2023 folds train on short windows** because the dataset starts in October 2022: 41,733 training rows for 2023-01, 292,582 for 2023-12, the full 504-session window of 580k+ rows only from 2024-10):

| Year | Folds | nested_lgbm | all51 | champion10 | lr_l2 | baseline_mom |
|---|---:|---:|---:|---:|---:|---:|
| 2023 (short training windows) | 12 | 0.517 | 0.509 | 0.498 | 0.515 | 0.502 |
| 2024 | 12 | 0.536 | 0.551 | 0.538 | 0.549 | 0.500 |
| 2025 | 12 | 0.557 | 0.552 | 0.534 | 0.573 | 0.488 |
| 2026 (Jan to Jul) | 7 | 0.532 | 0.532 | 0.534 | 0.521 | 0.487 |

Every model moves together month to month: over the six months from September 2025 to February 2026 every model averages 0.58 to 0.63 (individual months 0.55 to 0.67), and in March 2026, the inversion month the EDA identified, every candidate except the LambdaRank member falls to 0.38 to 0.47 (the worst month for six of the nine). The common component is the market regime, not the algorithm.

**Four findings from the 5-year run.**

1. **Feature selection did not transfer, and is not needed.** The pilot's 10 features lose to all features by 0.0115 AUC [0.0071, 0.0159] and in 32 of 43 months; they average 0.4979 in 2023. Honest yearly re-selection recovers the full-feature score exactly (0.5359 vs 0.5366) at the price of unstable, alternating sets; it helped in 2023 and 2025 (0.5565 vs 0.5524) and hurt in 2024 (0.5363 vs 0.5505). LightGBM's own regularisation does the job. The single-model reference uses all 52 features.
2. **The linear model has the highest mean and the worst risk.** L2 logistic scores 0.5415 (0.5430 nested), above LightGBM, so pre-registered gate 1 fails as written. It is the purest defensive-factor ranker in the league: per-date score correlation −0.50 with `atr_pct`, −0.45 with Amihud illiquidity and +0.49 with the 52-week high (LightGBM: −0.30, −0.29, +0.25). AUC rewards that tilt in down months (0.607) and punishes it in rebounds (0.379 in March 2026); its month-to-month spread is 1.4× LightGBM's and its holdout decile spread is −3.6%, with its bottom decile its best decile. Nonlinearity here buys stability and sane tails, not a higher mean AUC, which matches the literature's modest GBM-over-linear gains (GKX: 0.33 to 0.40% vs 0.11 to 0.27% monthly R²).
3. **AUC and tradability disagree.** AUC 0.536 with an IC t of 6 coexists with no long-only edge (§7.2). The label "beat the universe median" rewards low-volatility names, which cross the median often but do not beat the mean of a right-skewed, rising universe, so the classifiers' top deciles are defensive: nested LightGBM's trails the equal-weight universe by 0.58% per 20 days in up months, net of costs. The negative holdout decile spreads (every classifier −0.4% to −3.6%, the momentum rule +2.95%) are the same tilt over one 32-day window; across the 43 folds the LightGBM models' mean decile spreads are positive (+1.25% to +1.32%, positive in 30 to 33 months). The ensemble shows the fix: adding the high-volatility LambdaRank makes the blended score volatility-neutral (correlation with `atr_pct` −0.05), costs 0.003 of AUC and turns −0.7% a year into +7.0% a year over the universe. AUC is necessary, not sufficient; models are judged on net excess over the equal-weight universe.
4. **Hyperparameters are a mild contamination of 2026.** The LightGBM configuration (num_leaves 63, learning rate 0.05, 300 trees, feature and bagging fraction 0.8, min_data_in_leaf 200) was chosen in the pilot, which saw April to July 2026. Those 4 folds and the holdout are therefore not fully out-of-sample for the configuration; the 39 folds from 2023-01 to 2026-03 are. Removing those folds leaves the ranking unchanged (39 folds, 2023-01 to 2026-03: all features 0.5376, nested 0.5364, pilot 10 features 0.5240, L2 logistic 0.5441, momentum rule 0.4956; derived from the per-fold JSONs).

### 6.4 Bifurcation: what is dropped and the evidence

| Dropped | Evidence |
|---|---|
| Reinforcement learning (REINFORCE contextual bandit) | CV 0.5085; fails to beat its own initialisation on 2 of 4 folds; its own portfolio simulation loses to a free momentum heuristic out of sample; its best numbers come from 30 holdout dates (DSR 0.38). Literature: "no decent profitability" for RL in cross-sectional selection; RL works where a simulator exists (execution, hedging). |
| GRU / LSTM / MLP | At or below chance on CV (0.489 / 0.502 / 0.503). A 20-session temporal view adds nothing the features do not already carry. |
| Temporal transformer (PatchTST-lite), DLinear | 0.514 / 0.510 CV, 0.448 / 0.461 holdout; nearly identical fold paths, so attention adds about 0.004 over a two-layer linear model; both are a low-volatility bet in disguise. |
| Cross-sectional set-attention transformer | 0.520 ± 0.035, April and May below 0.50, holdout 0.501, rank-IC not significant. The label is already cross-sectional and the rank features already normalise across stocks. |
| Time-series foundation models (Chronos, TimesFM) | Not run; literature reports negative zero-shot R² on daily stock returns and directional hit rates near 50%. |
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
| LightGBM all features, top decile | +18.2% | −1.2% | 0.71 | −0.21 [−1.37, 0.94] | −27.9% | 68% | 20 / 45 | 0.34 | 0.000 |
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
| Feature-inversion monitor | more than half of the features with IC against their usual sign in a month | 6 of 43 months were inversion months and every candidate except the LambdaRank member failed in March 2026 |
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
- It does not claim that any model is reliable month to month: the single-model candidates fall below 0.50 in 6 to 9 of 43 months, and every candidate except the LambdaRank member did in March 2026.
- It does not claim the delivery signal is durable. Its IC fell by two-thirds after one regime break and there is no external literature.
- It does not claim the 2023 fold results are representative: those models trained on 2 to 13 months of data.
- It does not claim the 2026 folds are fully out-of-sample for the LightGBM configuration, which was tuned on them in the pilot.
- It does not claim that AUC differences of 0.01 between models are decidable on these samples: the paired block-bootstrap intervals are about ±0.004 to ±0.014 wide.
- It does not claim realistic costs for the illiquid tail or for any short book.
- It does not claim that the volatility+size-neutral books of §13.2 are independent evidence: the construction was read from the same 43 folds it is tested on; only the forward record can confirm it.
- It does not claim that the sector features of §13.4 carry industry information: a placebo with permuted industries earns almost the same book, so the gain is the look-ahead in today's index membership.

---

## 13. Improvement phase (19 to 22 October 2026)

**Governing document:** `ml/IMPROVEMENT_PLAN.md` (hypotheses, pass marks and the trial ledger were fixed before any result; amendments A1-A4 are dated in its §5). **Results of record:** `ml/results/improve/IMPROVEMENT_RESULTS.md`, which quotes every number from a stream's JSON. **Trial ledger:** N = 241 (177 from the five-year run, 64 new configurations and books). **Status:** complete, the ten-year re-runs included.

The phase executed the items of §11 that this environment can reach. The NSE archive host turned out to be reachable, which made three things possible that the program had written off: the corporate-action feed, five more years of history, and derivatives, index and positioning data.

### 13.1 Data: three defects found and fixed (`ml/results/improve/integrity/`)

- **Nine sessions were wrong.** Six trading sessions were never ingested (weekend Budget sessions 2025-02-01 and 2026-02-01, Saturday special sessions 2024-03-02 and 2024-05-18, the Muhurat sessions 2023-11-12 and 2025-10-21, the last wrongly listed as a holiday), and three closures carried another day's file (2021-11-05, 2023-06-29, 2024-01-22 re-dated to 2021-11-04, 2023-06-28, 2024-01-20). One archive file lacked every BE-series row (2022-03-07; rebuilt) and 28 mid-2023 sessions lacked some (1,679 rows rebuilt). Every 20-session window spanning these dates had been off by one. After the fix the ingest calendar matches the archive's own on all 1,842 days (I1: no session with more than 0.15% of names discontinuous, before 99%).
- **Corporate actions were unadjusted.** The daily `bc` file of the archive's PR bundle is the authoritative feed: 501 split, bonus and consolidation events now adjust 230,722 rows, and 98.0% of them agree with the observed ex-date price ratio within ±15% (I2). Rights issues, demergers and capital reductions (341 dates) are flagged for label masking. `flag_split_20d` falls from 0.557% to 0.095% of rows; label coverage rises from 96.67% to 97.23% (I3).
- **ETFs were inside the stock universe** because ISIN was empty on every row; the daily ETF lists give 469 symbols, and the label study's name rule had missed 61 of them. 215 ETF tickers (5.5% of rows) are out (I4).
- **Corrected datasets.** v2 (`ml/data_5y_v2/`): 1,290,062 rows, 2,265 tickers, 52 features, the 43 folds and the holdout unchanged in structure. Ten-year (`ml/data_10y/`): 2016-10 to 2026-10 in the store (5,237,728 rows; a merged feed of 755 validated events), 2,226,504 dataset rows, 103 monthly folds 2018-01 to 2026-07 with v2's 43 identical inside them.

### 13.2 Economics: the ensemble's mechanism, built on purpose (`ml/results/improve/books/BOOKS.md`)

Finding 3 of §6.3 said the classifiers' top deciles trail the universe because the label rewards low-volatility names, and that the rank ensemble beat it by accident of a volatility-neutral blend. The pre-registered test (B1) residualised each score per date on the ranks of `atr_pct` and `log_turnover` and re-ranked:

| Book, net 20 bps vs the equal-weight universe (five-year scores) | Excess/yr | IR [95% CI] | Months ahead | DSR (N = 238) |
|---|---:|---|---:|---:|
| nested LightGBM, plain top decile (§7.2) | −0.7% | −0.11 [−1.21, +0.96] | 20/45 | 0.000 |
| nested LightGBM, volatility+size-neutral top decile | **+6.9%** | +1.92 [+0.99, +3.01] | 33/45 | 0.053 |
| all-features LightGBM, volatility+size-neutral top decile | +6.5% | +1.85 [+0.93, +2.93] | 34/45 | 0.038 |
| rank ensemble, volatility+size-neutral top decile | +10.5% | +2.74 [+1.60, +3.90] | 38/45 | 0.469 |
| nested LightGBM, neutral **liquid** buffered decile (the paper-book shape) | +5.0% | +0.81 [−0.14, +1.93] | 29/45 | 0.000 |

B1 **passes**: the single-model books go from losing to beating the universe, in up and down months (the nested model's book in every calendar year; the all-features book dips to −0.07% per 20 sessions in 2023), while keeping 91% to 92% of the ranking. On the corrected data the same construction on the LightGBM control earns +7.8%/yr, IR 1.99 [0.91, 3.17] (liquid: +5.9%, IR 1.04 [0.03, 2.15]). The two turnover levers fail their marks: the buffered decile cuts turnover 18% to 26% (bar 30%) at no cost to returns, and the 40-session hold changes the excess by −0.2 to −1.0 points (two of three scorers within the one-point mark) but trades 0.54 times as much, not half (B2, B3 **fail**). Neutral baskets sit in smaller names (median name ADV ₹7 crore against ₹29 crore), so the pre-specified name-level cost model (Corwin-Schultz spread plus square-root impact; pessimistic for large caps) charges about 45 bps a side and leaves +1.5% to +2.0% a year. Adding 42 books raises the cross-trial Sharpe variance, so the expected best null Sharpe is 2.79 a year at N = 238: no book's Deflated Sharpe exceeds 0.47, and every liquid book's is 0.01 or less. The idea was read from the same 43 folds it is tested on; B1 is a consistency check, not an independent confirmation.

### 13.3 Hygiene (`ml/results/improve/hygiene/HYGIENE.md`)

- **Probability of backtest overfitting** (CSCV, 12,870 splits): 0.25 across the nine model configurations, 0.18 across the 24 books, 0.23 across the long-only books, against a chance level of 0.50 to 0.56. Selecting the best from the five-year record was better than a coin toss, but the winner's out-of-sample Sharpe is 21% to 29% of its in-sample figure.
- **Delivery is durable in its residual.** After per-date regression on turnover, volatility and 12-1 momentum, the IC of `deliv_pct_sma_20` (+0.045, t 5.6) and `deliv_value_share_20` (+0.047, t 6.9) is positive with intervals clear of zero in 3 of 4 and 4 of 4 calendar years and in both liquidity halves (pass mark met), and it did not move after March 2026 (+0.046 to +0.042). The raw IC's fall (+0.059 to +0.012) sits entirely in the part that volatility and turnover explain. §5.1's "works in up and down tapes" does not hold for the raw signal (+0.013 in up months against +0.124 in down months); the residual does.
- **Overlapping labels neither inflate nor hurt the fit.** Uniqueness weights are not near-constant (87.5% of rows within 10% of 1/21), so the item was tested: every fifth signal date loses 0.0020 AUC [−0.0041, −0.0000]; uniqueness-weighted fitting adds 0.0011 [−0.0002, +0.0023]. Closed.

### 13.4 Features and models: eight A/Bs, none passes (`ml/results/improve/ab/`)

Pass mark for every A/B: paired fold-level CV-mean AUC delta against the control with the 20-session block-bootstrap interval excluding zero **and** at least +0.003.

| A/B (control = LightGBM, 52 features) | Data | Δ AUC | 95% CI | Δ rank IC (NW t) | Verdict |
|---|---|---:|---|---|---|
| AB0: the two sufficiency features (52 vs 50) | v1 | +0.0014 | [+0.0002, +0.0026] | +0.0028 (2.4) | fail: real, below the bar |
| AB7: every fifth signal date | v1 | −0.0020 | [−0.0041, −0.0000] | −0.0037 (−1.8) | fail |
| AB8: uniqueness weights | v1 | +0.0011 | [−0.0002, +0.0023] | +0.0019 (1.5) | fail |
| AB1: market state (EW return, drawdown, breadth, dispersion, VIX, P/E) | v2 | −0.0047 | [−0.0115, +0.0018] | −0.0074 (−1.1) | fail; inversion months −0.008 |
| AB2: sector (NSE industry: relative momentum, industry-neutral ranks, sector index) | v2 | +0.0013 | [−0.0013, +0.0039] | +0.0045 (1.7) | fail |
| AB2P: the same with industries permuted (placebo) | v2 | −0.0020 | [−0.0062, +0.0014] | −0.0026 (−0.7) | fail |
| AB3: F&O (membership, basis, OI change, put/call) | v2 | **+0.0020** | **[+0.0006, +0.0032]** | +0.0032 (2.7) | fail: real, below the bar |
| AB4: flows (FII/DII/client positioning) | v2 | −0.0004 | [−0.0059, +0.0045] | −0.0011 (−0.2) | fail |
| AB5: all four families | v2 | +0.0024 | [−0.0043, +0.0082] | +0.0075 (1.1) | fail |
| AB6: rank ensemble on 52 features, no yearly re-selection | v2 | −0.0017 | [−0.0065, +0.0024] | −0.0052 (−1.1) | fail on AUC; see below |

Three readings. (1) Information outside the bhavcopy adds very little to a 20-day cross-sectional ranking: the F&O family is the only real gain, the size of the two delivery and liquidity re-expressions. (2) The NSE industry lists are a 2026 snapshot, and being in them predicts the past label (survivorship: AUC 0.53 to 0.56 for the membership flag against 0.50 to 0.54 for a point-in-time size flag); the sector books look best (+10.9%/yr, IR 3.2) but the placebo book with permuted industries is within a point of them (+10.1%, IR 3.0), so that gain is the partition, not industry information. (3) The ensemble needs no yearly re-selection: on all 52 features its plain top decile earns +7.7%/yr, IR 1.57 [0.62, 2.70] (nested, §7.2: +7.0%, IR 1.26), and its neutral liquid book +9.1%/yr, IR 1.58 [0.42, 2.82], DSR 0.011. §11 item 4 is answered.

### 13.5 The corrected data changes the measurement, not the verdict (`ml/results/improve/ab/v2/`)

LightGBM on 52 features: v1 0.5379 ± 0.0421 (84% of months ≥ 0.50, worst 0.453, holdout 0.5300, rank IC 0.070, NW t 6.2); v2 0.5359 ± 0.0320 (88%, worst 0.466, holdout 0.5203, rank IC 0.069, NW t 7.3). Less dispersion, a better floor, the same signal. The logistic benchmark keeps the higher mean (0.5396) and the worst tails (worst month 0.402, holdout 0.500); gate 1 still fails for the tree model (+0.0037 [−0.0043, +0.0125] for the logistic).

### 13.6 Eight years instead of five (`ml/results/improve/ab/10y/`)

The ten-year dataset's 103 folds (2018-01 to 2026-07; 2,126 test dates) span the 2018 small-cap bear, the 2020 crash and the 2021 boom. Same protocol and configurations, nothing tuned.

| Configuration, 103 folds | CV AUC ± sd | 95% CI | Months ≥ 0.50 | Worst | Holdout | Rank IC (NW t) |
|---|---|---|---:|---:|---:|---|
| LightGBM, 52 features | **0.5455 ± 0.0491** | [0.5359, 0.5549] | 84% | 0.399 (2020-11) | 0.5193 | +0.088 (9.8) |
| L2 logistic | 0.5423 ± 0.0681 | [0.5297, 0.5545] | 74% | 0.341 | 0.5003 | +0.082 (6.6) |
| momentum rule | 0.5000 ± 0.0420 | [0.4930, 0.5073] | 47% | 0.369 | 0.4690 | +0.001 (0.1) |

LightGBM's mean fold AUC by year: 2018 0.548, 2019 0.575, 2020 0.561, 2021 0.527, 2022 0.528, 2023 0.535, 2024 0.553, 2025 0.544, 2026 0.534 (the 2018 folds train on short windows, as 2023 did in §6.3). Without its best six-month run (2019-09 to 2020-02, mean 0.603) and its worst month, the other 96 folds average 0.5434: the Stage-0 "not one regime" criterion of `ml/GOALS.md` is met over eight years, and the 2018-2022 half (0.5478) is as strong as 2023-2026. The tree model now has the higher mean, +0.0032 over the logistic [−0.0033, +0.0104], but gate 1 still fails, and the logistic still has the worst tails.

Books over 105 signal months, net 20 bps vs the equal-weight universe: the plain top decile earns +7.5%/yr (IR 1.37 [0.51, 2.21]; +0.95% per 20 sessions in 2018-2022, +0.07% in 2023-2026: the volatility tilt's cost is a 2023-2026 phenomenon); the **volatility+size-neutral top decile +10.5%/yr, IR 2.32 [1.51, 3.10], ahead in 83 of 105 months and in every calendar year 2018-2026**; the liquid-tercile versions **earn nothing over ten years** (plain −0.0%, neutral +1.2%/yr, IR 0.21 [−0.52, +0.93]; the neutral liquid book was −0.08% per 20 sessions in 2018-2022 and +0.37% in 2023-2026). The economics are a small-cap effect: capacity about ₹157 crore (ten-year) to ₹214 crore (corrected five-year) for the control's neutral top decile, costs least known. Gates for the ten-year control at N = 241: 1 fail, 2 fail (84%), 3 plain fail (66%) and neutral pass (79%), 5 fail (DSR 0.000).

### 13.7 Gates at N = 241 and the verdict

For every configuration on the corrected data (`ml/results/improve/ab/v2/GATES.md`): gate 1 fails (none beats the logistic model with an interval clear of zero), gate 2 fails (best 88% of months ≥ 0.50, bar 90%), gate 5 fails (liquid-book DSR at most 0.011); gate 3 passes for the neutral top decile of the control (34/45 months) and of six other configurations (AB1, AB2, AB2P, AB5, the all-feature ensemble and its CatBoost member), and for the plain top decile of the all-feature ensemble (34/45); gate 4 does not apply to configurations that select nothing. **Nothing is promoted. The verdict of §1 stands: no capital.** What changes is the paper book: it becomes a deliberate construction (LightGBM on 52 features, score residualised per date on volatility and size ranks, full-universe top decile or buffered decile, 20-session hold, equal-weight benchmark, 20 bps and name-level costs both reported) instead of an accidental blend, with the all-feature rank ensemble as the champion-challenger and the liquid-tercile version watched alongside it. The ten-year record (§13.6) says the liquid version has earned nothing since 2018, so the book that is worth a forward record has a capacity of about ₹160 to 215 crore (₹200 to 280 crore for the ensemble's) and sits in names where costs are least known; that is stated, not hidden. The monitoring of §10 gains two alerts: the live score's correlation with `atr_pct` and `log_turnover` after neutralisation (within ±0.05) and the residual delivery IC in place of the raw one.

### 13.8 What this does to §11

Items 2 (neutral construction: done, passes B1), 3 (corporate actions: done), 4 (both A/Bs: done, both fail), 5 (delivery validation: done, durable in the residual), 6 (name-level costs: done, pessimistic model), 8 (market-state inputs: done, fail), 10 (book construction: done, buffer and 40-session hold measured) and 11 (PBO done, uniqueness closed, history before 2021 loaded; combinatorial purged CV still open) are closed. Item 9 is half done: sector, index, F&O and flows are tested; fundamentals, analyst and institutional data need a filings feed this environment does not have. Item 7 (the short side on F&O names) stays open. Item 12 is confirmed by AB0, AB7 and AB8. The ordered list of what remains, with the data each needs, is `ml/ROADMAP.md`.

## 14. Improvement phase 2 (23 October 2026)

**Governing document:** `ml/IMPROVEMENT_PLAN_2.md` (fixed before any result; amendments A1 and A2, ledger corrections and errata dated in its section 4). **Results of record:** `ml/results/improve2/IMPROVEMENT_RESULTS.md`, which quotes every number from a stream's JSON. **Trial ledger:** N = 270 (241 after §13; 20 planned; 4 found by review and counted; 5 from the two amendments). **Status:** complete. Every headline was recomputed independently from the raw predictions and price data by an adversarial verifier.

The phase asked the questions §13 left open: can the book carry capital (a liquid-universe model, a futures-hedged long-short), is the horizon right (40 days), does a new data source help (the exchange's announcement files), is the model mis-tuned, and is the construction robust to which months train it (CPCV). It also started the forward record.

### 14.1 What passed and what failed

| Question | Pre-registered mark | Result | Verdict |
|---|---|---|---|
| Q3: a model trained on liquid names | liquid neutral book IR ≥ 0.5 with CI > 0, and a paired gain over the control's liquid book with CI > 0 | L1 (liquid tercile) IR 0.27 [−0.49, +1.02], paired +0.04 pp/yr; L2 (top two terciles) IR 0.40 [−0.30, +1.14], paired +1.08 pp/yr [−0.44, +2.65] | **FAIL** |
| Q4: F&O long-short through stock futures | net Sharpe ≥ 1.0 with CI > 0, beta within ±0.2 | plain −0.65 [−1.43, +0.12], neutral −1.22 [−1.87, −0.53]; betas −0.15 and −0.05 | **FAIL** |
| Q5: a 40-day horizon | paired gain of the 40-session book with CI > 0 and a higher break-even | +0.33 pp/yr [−0.83, +1.48]; break-even 88 vs 83 bps | **FAIL** |
| Q6: company announcements (2,488 PR bundles: 4,956,205 announcement records, 91,226 board-meeting list rows) | ΔAUC ≥ +0.003 with CI > 0 | −0.0008 [−0.0035, +0.0017] | **FAIL** |
| Q7: nested hyper-parameter tuning | ΔAUC ≥ +0.003 with CI > 0 | +0.0004 [−0.0006, +0.0014] | **FAIL** |
| Q2: combinatorial purged CV (8 groups, 28 splits, 7 paths) | net excess > 0 in ≥ 6 of 7 paths | full-universe neutral +14.3% to +17.1%/yr, liquid neutral +4.8% to +8.7%/yr, 7/7 each | **ROBUST** |
| Q9 (amendment A1): an expanding training window | ΔAUC ≥ +0.003 with CI > 0; the Q3 rule on the liquid book | **+0.0079 [+0.0047, +0.0113]**; liquid neutral book IR 0.78 [0.06, 1.54], paired +4.06 pp/yr [+1.71, +6.39] | **PASS, both** (exploratory) |
| Q10 (amendment A2): is the Q9 book gain one seed draw? | seed-averaged paired CI > 0 and every Q9 seed above every control seed | liquid neutral **+3.54 pp/yr [+1.30, +5.67]**; full-universe neutral +4.44 [+2.90, +5.97]; both orderings hold | **REAL** |

The failures are informative. A liquid-only model throws information away: on the same liquid rows the full-universe model ranks as well as the liquid-only one (AUC 0.5322 against 0.5305). The futures hedge works (each leg's beta near one, the book's near zero), but the short leg loses net of carry and costs. Training on the 40-day label does not rank 40-day outcomes better (rank IC 0.079 against 0.087 for the 20-day model). The earnings-announcement drift is real (`ear_3d` rank IC +0.042, Newey-West t 7.9, positive in every year) but already mostly inside the model. Tuning moved six of nine years off the incumbent setting and bought nothing: the configuration was not the bottleneck.

### 14.2 The one lever that worked: training history

CPCV beat the walk-forward control by a wide margin on the same 103 months (liquid neutral book +4.8% to +8.7% a year against +0.8%; the CPCV books run on 103 signal months, the walk-forward book table below on 105). The verifier decomposed the gap: about 38% of the liquid gain sits in the first group (2018-01..2019-01), where CPCV trains on later data (look-ahead by construction), but the last group, which has no later data, gains as much as the others. That pointed at the amount of history, not at future knowledge, and amendment A1 tested it. A1 was committed 20 s after the Q9 job started (07:55:02 against 07:54:42 UTC), before its first fold result (about 07:56:28), and Q9 ran without the two pre-compute reviews (plan 2, errata (i) and (ii)): the same LightGBM, the same 52 features and folds, trained on every eligible row before the embargo instead of the last 504 sessions.

| 103 folds, ten-year data | CV AUC [95% CI] | Months ≥ 0.50 | Worst | Holdout | Rank IC (NW t) |
|---|---|---:|---:|---:|---|
| control, rolling 504 sessions | 0.5455 [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.088 (9.8) |
| **expanding window** | **0.5534 [0.5435, 0.5624]** | 86% | 0.414 | 0.5401 | **+0.103 (11.4)** |

| Book, net 20 bps vs the equal-weight universe, 105 months | Excess/yr | IR [95% CI] | Capacity (₹ cr) | Name-level excess | DSR (N = 270) |
|---|---:|---|---:|---:|---:|
| control, neutral top decile | +10.5% | +2.32 [+1.51, +3.10] | 157 | +3.9% | 0.066 |
| **expanding, neutral top decile** | **+14.9%** | **+3.06 [+2.29, +3.86]** | 147 | +8.2% | 0.761 |
| control, neutral liquid top decile | +1.2% | +0.21 [−0.52, +0.93] | 603 | −3.1% | 0.000 |
| **expanding, neutral liquid top decile** | **+5.2%** | **+0.78 [+0.06, +1.54]** | 555 | +0.6% | 0.000 |

Seed calibration (Q10) was registered because the verifier found that paired book tests against the seed-108 control also "passed" for configurations with no ranking gain. With seeds 108-111 for the control and 108-110 for the expanding window, the AUC gain is untouched (seed sd 0.0003 and 0.0001; seed-averaged +0.0078 [+0.0044, +0.0116]) and both neutral book gains survive. The seed-108 control turned out to be its own unluckiest liquid book (+1.2% against +1.8% to +2.3%), so every earlier paired comparison against it was slightly flattered.

What keeps this from changing the capital verdict:
1. **It is exploratory.** The hypothesis was formed after reading CPCV on the same months.
2. **It is regime-concentrated.** +0.024 AUC in 25 down months against +0.004 in 55 up months; +0.0043 without the 8 best folds. A model trained on two bull years generalises badly into a sell-off; one that remembers earlier sell-offs does better.
3. **The liquid book's interval is fragile.** It leans on 2026 (without 2026 and the holdout: IR 0.51, interval including zero), it includes zero for one of three seeds, and its edge after name-level costs is +0.6% a year.
4. **Deflation.** No liquid book's Deflated Sharpe exceeds 0.001 at N = 270.

### 14.3 Gates at N = 270 (`ml/results/improve/ab/10y_p2/GATES.md`)

The expanding window passes gate 1 on all three seeds (+0.0112 [+0.0049, +0.0179] over the logistic benchmark): the first gate-1 pass in the program. The logistic benchmark ran on the rolling window; whether an expanding logistic model closes the gap is untested. It also passes gate 3 for the neutral top decile (80% to 82% of months), and fails gate 2 (86% to 87% of months ≥ 0.50, bar 90%) and gate 5 (liquid DSR 0.000). The control passes 0 or 1 of the applicable gates depending on the seed; the event and tuned configurations pass 1. **Nothing is promoted. The verdict of §1 stands: no capital.**

### 14.4 The forward record (`ml/paper/`, `ml/results/improve2/paper/PAPER.md`)

The frozen construction of §13.7 started its forward record on 2026-10-19: one command a day (`ml/paper/RUNBOOK.md`), an append-only ledger with a specification hash, and a byte-identical rebuild proof. Since spec amendment 10 (2026-10-23) it runs six books: primary (neutral full-universe top decile, about 152 names), capacity (its liquid-tercile version, about 50 names), the rank-ensemble challenger, the plain reference, and the expanding-window challenger with its capacity version, backfilled from inception without changing a byte of the existing rows. Review caught one data defect in the live window: CCAVENUE's consolidation is spelled "CNSLDATN" with an empty ex-date and was missed, giving a fake +840% day; the parser was extended, the store repaired under the lock and the ledger re-issued once, with the superseded rows kept. Three research-period consolidations with the same spelling remain unadjusted (none is a universe row of the ten-year dataset). The research books exclude rows failing the forward-looking `y_clean_20d` screen (0.33% of rows, mostly crashes; about 0.4 pp a year of flattery); the live books hold every name, so live and backtest are not like-for-like. The first three signal dates (2026-10-19, 2026-10-21, 2026-10-22) were scored in one catch-up run on 2026-10-23, under the specification written that day before the job produced any number; the construction is §13.7's and the expanding books are Q9's configuration as amendment A1 registered it (research data through 2026-10-16), so no parameter depends on those sessions (`ml/paper/SPEC.md`, header and section 5). Three monitors were at alert on 2026-10-22: feature drift (`feature_psi` 0.259, threshold 0.25, on `ret_126d`), a pre-inception inversion month (`feature_inversion` 0.635, threshold 0.5, 2026-08) and, since amendment 10, the expanding challenger's `neutral_score_corr` (0.048, 0.058 and 0.056 on the three dates against 0.05, the `log_turnover` term; `ml/paper/RUNBOOK.md` section 8). The first tranche exits on 2026-11-18 (2026-11-19 if the Muhurat session is not added to `ml/paper/calendar_live.json` in time).

### 14.5 What this does to §11 and the roadmap

- **Closed with evidence:** a liquid-only model, a futures-hedged long-short (§11 item 7), a 40-day horizon, announcement-event features, hyper-parameter tuning, and combinatorial purged CV (§11 item 11). None should be retried without new information.
- **New leading candidate:** the expanding-window construction. It is in the forward record as a challenger, not promoted; six to twelve months of live comparison decide, not another backtest.
- **Process:** paired book comparisons need seed calibration; in-cycle follow-ups are dated amendments committed before their job and reviewed like any stream. Both are written into `ml/PROCESS.md` and `ml/PROMPT.md`.
- **Still open:** fundamentals and analyst data (no filings feed reachable here), the three research-store consolidations, a logistic benchmark on an expanding window. The ordered list is `ml/ROADMAP.md`.

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
# improvement phase 2 (ml/IMPROVEMENT_PLAN_2.md; queue scripts in ml/results/improve2/queue/; the streams' data builds come first, see each stream's report)
mkdir -p ml/results/improve/ab/10y_p2/preds && cp ml/results/improve/ab/10y/control__beat_mkt_20d.json ml/results/improve/ab/10y_p2/ && cp ml/results/improve/ab/10y/preds/control__beat_mkt_20d.parquet ml/results/improve/ab/10y_p2/preds/   # the ten-year control, copied byte for byte
sh ml/results/improve2/queue/queue_b.sh      # Q6, Q5, Q7
sh ml/results/improve2/queue/queue_c.sh      # Q3, Q2 (waits for queue B)
sh ml/results/improve2/queue/queue_d.sh      # Q9 (amendment A1)
cp ml/results/improve/ab/10y/lr_l2__beat_mkt_20d.json ml/results/improve/ab/10y_p2/ && cp ml/results/improve/ab/10y/preds/lr_l2__beat_mkt_20d.parquet ml/results/improve/ab/10y_p2/preds/   # the logistic benchmark for gate 1, copied byte for byte
sh ml/results/improve2/queue/queue_e.sh      # Q10: seed replicates, compare, books at N = 270, readings, gates
OMP_NUM_THREADS=2 python3 -I ml/paper/job.py                                    # the daily forward record (ml/paper/RUNBOOK.md)
```

Seed 108 everywhere; OMP_NUM_THREADS=2 on the shared 4-core box.

## Appendix B. Trial ledger (for Deflated Sharpe and best-of-N accounting)

Pilot primary task: 38 full-protocol configurations, 151 including hyper-parameter and univariate screens (`AUDIT.md` T7). Strategy grid: 96 trials (60 scorer × basket cells, 6 diagnostics, 30 program configurations). SOTA study: 12 configurations. Feature A/Bs: 5 + 6 variants. Label study: 7 model-level runs, 1,106 feature-label hypotheses. Five-year run: N = 177, fixed in the code before any portfolio number existed: 10 model configurations and 24 books on the 43 folds, plus the pilot's 77 configurations and 66 portfolio cells (`portfolio_5y.json`). Improvement phase 1: N = 241 (`ml/IMPROVEMENT_PLAN.md`); phase 2: N = 270 (`ml/IMPROVEMENT_PLAN_2.md` section 4 lists every addition). Each forward book of `ml/paper/` is one trial and must stay one trial.
