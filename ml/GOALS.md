# SuryaDhana goals: how good is good enough?

**Date:** 2026-10-19 · **Owner:** program lead · **Inputs:** `ml/PROGRAM_REPORT.md`, `ml/results/scale5y/SCALE5Y.md`, `ml/research/SOTA_FORECASTING.md`, and the community calibration `ml/research/community/COMMUNITY_CALIBRATION.md` (every external anchor below is sourced there).

The question from management is "how good does the model have to be?". The answer depends on what it is for. A model can be good enough to **study**, good enough to **paper-trade**, good enough for **small capital**, or good enough to **scale**. Each stage has measurable criteria fixed here, before the next test, so that passing them cannot be arranged after the fact.

## Where the program stands

| Measure (five-year walk-forward, 43 monthly folds, 2023-01 to 2026-07) | Value | Source |
|---|---|---|
| AUC, LightGBM on all features / nested selection | 0.5366 / 0.5359, 95% block-bootstrap CI [0.5250, 0.5483] | `scale5y_summary.json` |
| Rank IC per date, nested LightGBM | +0.065, Newey-West t 6.0, positive in 38 of 43 months | `SCALE5Y.md` |
| Months with AUC ≥ 0.50 | 86% (nested LightGBM), 91% (rank ensemble) | `SCALE5Y.md` |
| Worst month | 0.431 (March 2026 rebound); every candidate except the LambdaRank member below 0.50 that month | `regimes_5y.md` |
| Directional hit rate implied by rank IC 0.065 | about 52.1% (Sheppard: ½ + arcsin(IC)/π); the AUC of 0.536 gives Somers' D 0.073 | arithmetic |
| IC stability (per-month mean/sd) | about 0.9 from the Newey-West t of 6.0 over 43 months; about 1.3 implied by the ensemble's 91% of months above 0.50 | arithmetic |
| Long-only top decile vs equal-weight universe, net 20 bps | single models −0.7% to −3.4% a year; rank ensemble +7.0% a year, IR 1.26 [0.32, 2.37] | `portfolio_5y.json` |
| Deflated Sharpe, N = 177 trials | 0.000 (LightGBM books), 0.163 (ensemble top decile), 0.040 (ensemble liquid book), 0.490 (ensemble long-short) | `portfolio_5y.json` |
| Pre-registered gates passed | 0 of 5 (LightGBM), 1 of 5 (ensemble) | `SCALE_UP.md` |

## The ladder

Each stage must be met **by one frozen, pre-registered configuration**, judged on data that configuration never saw. Passing a lower stage is necessary for the next; it is never sufficient.

### Stage 0: research-grade signal (status: **met**)

A model is worth studying further when its ranking of stocks is distinguishable from chance in a way that is not a data or code artefact.

| Criterion | Threshold | SuryaDhana | External anchor |
|---|---|---|---|
| AUC on a cross-sectional relative-return label | block-bootstrap 95% CI excludes 0.50 over ≥ 36 monthly folds | 0.5359 [0.5250, 0.5483] over 43 folds: met | Published frontier: GKX neural nets imply forecast-return correlation ≈ 0.06; Qlib LightGBM IC 0.045 on CSI300 |
| Rank IC per date | mean ≥ 0.03 with Newey-West t ≥ 3 | +0.065, t 6.0: met | MSCI Barra (Gleiser and McKenna 2010): "many portfolio managers would view a 'good' IC as 0.05 and a 'very good' IC as 0.10"; the M6 organisers' tiers are 0.05 moderate, 0.10 good, 0.15 exceptional; Quantopian's community bar for keeping a factor was mean IC above 0.01 at p < 0.05 |
| Null and leakage tests | label-permutation null 0.500 ± 0.001; features and labels recompute exactly; point-in-time universe | all pass (`AUDIT.md`) | An IC of 0.05 implies a 51.6% hit rate and 0.10 implies 53.2%, so a claimed daily directional accuracy far above 55% implies IC above 0.15 and is a leakage warning first. The online examples are all price-level fits or leaks: a 1.36-million-view tutorial's "near-perfect" LSTM, Kaggle notebooks titled "99% accuracy" and "0.99 R²", an LSTM scoring R² 0.89 on a pure random walk, 87.6% direction on about 15 test days, 98% training accuracy from label leakage |
| Not one regime | mean AUC > 0.50 with the best six-month run and the worst month removed | 0.5267 over the other 36 months: met, narrowly | |
| Honest selection | features and hyper-parameters chosen inside the training window | nested selection used; hyper-parameters fixed on 2026-04..07 (4 of 43 folds contaminated) | de Prado: no more than about 45 independent configurations on five years of data |

### Stage 1: paper-trading eligibility (status: **met by the rank ensemble only**)

A model earns a frozen paper book when a pre-registered portfolio built from it beats the honest benchmark with an interval clear of zero, is not fragile month to month, and could be traded at size.

| Criterion | Threshold | SuryaDhana | External anchor |
|---|---|---|---|
| Net excess over the equal-weight universe | 95% month-block CI excludes zero over ≥ 36 months, costs ≥ 20 bps per side | ensemble top decile +7.0% a year, IR 1.26 [0.32, 2.37]: met; every single model: not met | Microsoft Qlib's reference LightGBM earns 9.0% a year excess at IR 1.02 net of 5/15 bps on CSI300; Quantopian's community called "a Q Sharpe of 1 and above … a good candidate"; in the live M6 competition only 28.8% of 163 teams beat the equal-weight portfolio over 12 months and none did in every month |
| Fold floor | AUC ≥ 0.50 in ≥ 90% of months | ensemble 91%: met; LightGBM 86%: not met | Numerai: a live participant's per-era correlation Sharpe 1.32, Numerai's own example model 2 on validation; 91% of months above 0.50 implies a per-month mean/sd of about 1.3 |
| Capacity | ≥ ₹500 crore at 5% of 20-day ADV for the liquid book | ≈ ₹1,050 crore: met | |
| Cost headroom | break-even cost per side ≥ 2 × realistic cost (15 to 25 bps) | ensemble excess still +3.4% a year at 40 bps: met | India statutory charges ≈ 11 bps per side; realistic liquid-name total 15 to 25 bps |
| Frozen specification | features, model, book rule, rebalance and costs written down; trial count N = 1 thereafter | written in `SCALE5Y.md` and `PROGRAM_REPORT.md` §10: met | |
| Monitoring live | delivery IC, fold floor, inversion monitor, drift, PSI, paper IR | specified, not yet running | Quantopian and QuantConnect both treated six months out of sample as the minimum observation period (QuantConnect weights a strategy by days live over 180) |

### Stage 2: small-capital eligibility (status: **not met**)

Capital follows a track record the model did not get to choose. The deflated and probabilistic Sharpe ratios are the test; the historical record cannot pass it at N = 177, so this stage is decided by the paper book.

| Criterion | Threshold | SuryaDhana | External anchor |
|---|---|---|---|
| Probabilistic Sharpe of the frozen paper book | PSR ≥ 0.95 against SR* = 0, on the live record alone | needs about 4 years at IR 0.85 (994 sessions); shorter if the live IR is higher | QuantConnect Alpha Streams required PSR(true Sharpe > 1) > 80%, and only 9 of 280 strategies (3.2%) passed; Quantopian found in-sample Sharpe explained out-of-sample Sharpe with R² below 0.025 across 888 algorithms |
| Deflated Sharpe | DSR ≥ 0.95 with the full trial ledger | 0.04 to 0.49 on the historical record: not met | WorldQuant BRAIN (third-party sources): 5-year Sharpe > 1.25, fitness > 1, daily turnover 1% to 70%; de Prado's worked example: Sharpe 2.5 over 5 years with 100 trials gives DSR 0.90 |
| Consistency | excess over the universe positive in ≥ 60% of months; relative drawdown ≤ 10% | historical ensemble: 33 of 45 months (73%) | |
| Monitors | no alarm in the trailing 12 months (delivery IC, inversion, drift, atr_pct neutrality) | not yet running | |
| Data integrity | corporate-action-adjusted prices; ETF exclusion; name-level costs | not done | |
| All five pre-registered gates | pass on the combined historical and live record | 1 of 5 | |

### Stage 3: scale (status: **not met**)

| Criterion | Threshold | External anchor |
|---|---|---|
| Live Sharpe after all costs | ≥ 1.0 over ≥ 3 years, DSR ≥ 0.95 | Numerai One reported Sharpe 2.75 for 2024 from a meta-model of thousands of signals; Medallion's edge was a 50.75% hit rate over millions of trades; the JPX Kaggle winner's gross Sharpe of 5.96 over three months is within the luck range of 2,033 entrants, so a short record proves nothing at any Sharpe |
| Capacity | ≥ ₹1,000 crore with name-level impact modelled | |
| Short side | F&O-restricted long-short validated with borrow and 40 bps | |
| Independent data | at least one external feed (corporate actions, sector, F&O membership) in production | |

## Position on the external ladder

The community research derived a five-rung ladder from live competitions, allocator platforms and industry rules of thumb (`COMMUNITY_CALIBRATION.md` §3). On it, SuryaDhana's single models are rung 1 (a real factor whose long-only book does not beat equal weight) and the rank ensemble is rung 2 (a good model that earns a paper book: IC 0.065, stability about 1.3, IR 1.26 with an interval clear of zero, beats equal weight and the momentum baseline over 45 months). Rung 3, allocatable, needs a factor-neutralised IC of at least 0.05, a five-year Sharpe above 1.25, PSR(SR > 1) of 80%, DSR 0.95 and a live record; none of these is in hand. That is the same answer the stages above give.

## What "good enough" means in plain words

- **To keep researching:** the model must beat chance in a way the red team cannot break. SuryaDhana does: AUC 0.536, rank IC 0.065, clean audit. That is the size of edge the published frontier finds, and it is small.
- **To paper-trade:** a frozen book must beat holding the whole universe equally weighted, after costs, with an interval clear of zero. One configuration does, the rank ensemble, by about 7% a year over 45 months. Every single model fails this.
- **For capital:** the book must prove itself on time it did not choose. Four years of paper track record at the observed information ratio, or less if the edge is larger live. Nothing in the program has this yet, and no amount of further backtesting can supply it.
- **What would make the bar lower:** nothing legitimate. A higher information coefficient per bet (better features, external data) or more independent bets per year (breadth, a shorter horizon only if costs allow) shortens the time to proof; they do not change the proof required.

## Not goals

- A directional accuracy above 60%, an AUC above 0.60 or a backtest Sharpe above 3 on end-of-day data. Numbers like these appear online in the most-viewed stock-prediction tutorials (0.59 to 1.36 million views each) and in Kaggle notebooks titled "99% accuracy" or "0.99 R²"; all are price-level fits that a repeat-yesterday forecast matches (`ml/research/community/COMMUNITY_CALIBRATION.md` §2). In this program such numbers appeared only in one six-month regime run (window means of 0.58 to 0.63 from September 2025 to February 2026) that reversed in March 2026.
- Beating the linear benchmark on AUC. The program could not show it, and the economics do not depend on it.
- A new model family. The evidence in `PROGRAM_REPORT.md` §6 is against spending on transformers, foundation models or reinforcement learning.
