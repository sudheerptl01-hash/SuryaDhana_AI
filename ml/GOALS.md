# SuryaDhana goals: how good is good enough?

**Date:** 2026-10-19 · **Owner:** program lead · **Inputs:** `ml/PROGRAM_REPORT.md`, `ml/results/scale5y/SCALE5Y.md`, `ml/research/SOTA_FORECASTING.md`, and the community calibration in `ml/research/community/` (external anchors are filled from it; cells marked *[research]* are pending that study).

The question from management is "how good does the model have to be?". The answer depends on what it is for. A model can be good enough to **study**, good enough to **paper-trade**, good enough for **small capital**, or good enough to **scale**. Each stage has measurable criteria fixed here, before the next test, so that passing them cannot be arranged after the fact.

## Where the program stands

| Measure (five-year walk-forward, 43 monthly folds, 2023-01 to 2026-07) | Value | Source |
|---|---|---|
| AUC, LightGBM on all features / nested selection | 0.5366 / 0.5359, 95% block-bootstrap CI [0.5250, 0.5483] | `scale5y_summary.json` |
| Rank IC per date, nested LightGBM | +0.066, Newey-West t 6.0, positive in 38 of 43 months | `SCALE5Y.md` |
| Months with AUC ≥ 0.50 | 86% (nested LightGBM), 91% (rank ensemble) | `SCALE5Y.md` |
| Worst month | 0.431 (March 2026 rebound); every model below 0.50 that month | `regimes_5y.md` |
| Directional hit rate implied by AUC 0.536 | about 52% | arithmetic |
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
| Rank IC per date | mean ≥ 0.03 with Newey-West t ≥ 3 | +0.066, t 6.0: met | Grinold and Kahn: IC 0.05 "good", 0.10 "exceptional" *[research: exact quote and page]* |
| Null and leakage tests | label-permutation null 0.500 ± 0.001; features and labels recompute exactly; point-in-time universe | all pass (`AUDIT.md`) | Practitioner rule: a claimed accuracy far above 55% signals leakage *[research]* |
| Not one regime | mean AUC > 0.50 with the best six-month run and the worst month removed | 0.5267 over the other 36 months: met, narrowly | |
| Honest selection | features and hyper-parameters chosen inside the training window | nested selection used; hyper-parameters fixed on 2026-04..07 (4 of 43 folds contaminated) | de Prado: no more than about 45 independent configurations on five years of data |

### Stage 1: paper-trading eligibility (status: **met by the rank ensemble only**)

A model earns a frozen paper book when a pre-registered portfolio built from it beats the honest benchmark with an interval clear of zero, is not fragile month to month, and could be traded at size.

| Criterion | Threshold | SuryaDhana | External anchor |
|---|---|---|---|
| Net excess over the equal-weight universe | 95% month-block CI excludes zero over ≥ 36 months, costs ≥ 20 bps per side | ensemble top decile +7.0% a year, IR 1.26 [0.32, 2.37]: met; every single model: not met | Quantopian allocation criteria and WorldQuant BRAIN thresholds *[research]* |
| Fold floor | AUC ≥ 0.50 in ≥ 90% of months | ensemble 91%: met; LightGBM 86%: not met | |
| Capacity | ≥ ₹500 crore at 5% of 20-day ADV for the liquid book | ≈ ₹1,050 crore: met | |
| Cost headroom | break-even cost per side ≥ 2 × realistic cost (15 to 25 bps) | ensemble excess still +3.4% a year at 40 bps: met | India statutory charges ≈ 11 bps per side; realistic liquid-name total 15 to 25 bps |
| Frozen specification | features, model, book rule, rebalance and costs written down; trial count N = 1 thereafter | written in `SCALE5Y.md` and `PROGRAM_REPORT.md` §10: met | |
| Monitoring live | delivery IC, fold floor, inversion monitor, drift, PSI, paper IR | specified, not yet running | |

### Stage 2: small-capital eligibility (status: **not met**)

Capital follows a track record the model did not get to choose. The deflated and probabilistic Sharpe ratios are the test; the historical record cannot pass it at N = 177, so this stage is decided by the paper book.

| Criterion | Threshold | SuryaDhana | External anchor |
|---|---|---|---|
| Probabilistic Sharpe of the frozen paper book | PSR ≥ 0.95 against SR* = 0, on the live record alone | needs about 4 years at IR 0.85 (994 sessions); shorter if the live IR is higher | Bailey and López de Prado; the pilot needed 705 sessions at IR 0.99 |
| Deflated Sharpe | DSR ≥ 0.95 with the full trial ledger | 0.04 to 0.49 on the historical record: not met | WorldQuant BRAIN: Sharpe > 1.25 after their costs *[research: exact criteria]* |
| Consistency | excess over the universe positive in ≥ 60% of months; relative drawdown ≤ 10% | historical ensemble: 33 of 45 months (73%) | |
| Monitors | no alarm in the trailing 12 months (delivery IC, inversion, drift, atr_pct neutrality) | not yet running | |
| Data integrity | corporate-action-adjusted prices; ETF exclusion; name-level costs | not done | |
| All five pre-registered gates | pass on the combined historical and live record | 1 of 5 | |

### Stage 3: scale (status: **not met**)

| Criterion | Threshold | External anchor |
|---|---|---|
| Live Sharpe after all costs | ≥ 1.0 over ≥ 3 years, DSR ≥ 0.95 | Numerai, WorldQuant and Kaggle finance competitions: typical winning correlations and Sharpes *[research]* |
| Capacity | ≥ ₹1,000 crore with name-level impact modelled | |
| Short side | F&O-restricted long-short validated with borrow and 40 bps | |
| Independent data | at least one external feed (corporate actions, sector, F&O membership) in production | |

## What "good enough" means in plain words

- **To keep researching:** the model must beat chance in a way the red team cannot break. SuryaDhana does: AUC 0.536, rank IC 0.066, clean audit. That is the size of edge the published frontier finds, and it is small.
- **To paper-trade:** a frozen book must beat holding the whole universe equally weighted, after costs, with an interval clear of zero. One configuration does, the rank ensemble, by about 7% a year over 45 months. Every single model fails this.
- **For capital:** the book must prove itself on time it did not choose. Four years of paper track record at the observed information ratio, or less if the edge is larger live. Nothing in the program has this yet, and no amount of further backtesting can supply it.
- **What would make the bar lower:** nothing legitimate. A higher information coefficient per bet (better features, external data) or more independent bets per year (breadth, a shorter horizon only if costs allow) shortens the time to proof; they do not change the proof required.

## Not goals

- A directional accuracy above 60%, an AUC above 0.60 or a backtest Sharpe above 3 on end-of-day data. Numbers like these appear online *[research: examples and why they are wrong]* and in this program they appeared only in one six-month regime run (0.60 to 0.66 from September 2025 to February 2026) that reversed in March 2026.
- Beating the linear benchmark on AUC. The program could not show it, and the economics do not depend on it.
- A new model family. The evidence in `PROGRAM_REPORT.md` §6 is against spending on transformers, foundation models or reinforcement learning.
