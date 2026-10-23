# SuryaDhana improvement phase 2: pre-registered plan

**Date fixed:** 2026-10-23, before any result of this phase existed · **Owner:** program lead · **Follows:** `ml/IMPROVEMENT_PLAN.md` (phase 1, N = 241) and `ml/ROADMAP.md` · **Governs:** `ml/paper/`, `ml/results/improve2/`, `ml/data_10y_liq*/`, `ml/data_10y_h40/`, `ml/data_ext/events*`.

Phase 1 left four questions that this environment can answer, one product step it can take, and one deliverable it owes:

1. **Capacity.** The volatility+size-neutral book beats the equal-weight universe in every year 2018-2026, but its liquid-tercile version earned nothing over ten years. Can a model built for liquid names fix that?
2. **The short side.** Futures data for every F&O stock now exists. Does a market-neutral long-short book on F&O names work net of futures costs?
3. **Horizon.** The 40-day label was carried as a candidate and never tested at scale.
4. **New information.** The exchange's daily announcement files (2016-2026, on disk) are the one reachable source of company-event information: results dates, the price reaction to results, management changes, ratings, orders. The earnings-announcement-return drift is among the best-documented anomalies.
5. **Accuracy levers not yet pulled honestly:** hyper-parameters were fixed in the pilot and never tuned at scale.
6. **Proof:** one walk-forward path is one draw; combinatorial purged cross-validation gives several.
7. **Product:** freeze the construction and start the forward record (the only route to Stage 2).
8. **Deliverable:** the improvement process written as a reusable prompt.

## 1. Rules (unchanged from phase 1 unless stated)

- Ten-year dataset `ml/data_10y/` (103 monthly folds 2018-01..2026-07, rolling 504-session training window, 22-session embargo, exit-date purge, holdout 2026-08-03..2026-09-16 scored once), seed 108, harness `ml/improve/ab.py`, books `ml/improve/ab_books.py` (P2 construction), gates `ml/improve/gates.py`.
- Control: LightGBM (champion configuration) on the 52 features, 10y run in `ml/results/improve/ab/10y/` (CV AUC 0.5455, rank IC 0.088; neutral top decile +10.5%/yr IR 2.32; liquid neutral +1.2%/yr IR 0.21).
- Primary A/B mark (model changes): paired fold-level CV-mean AUC delta vs the control ≥ +0.003 with the 20-session block-bootstrap 95% CI excluding zero. Book marks are stated per stream.
- **Trial ledger.** Fixed now: Q2 1 + Q3 6 + Q4 2 + Q5 5 + Q6 3 + Q7 3 = 20 new trials, **N = 261**. Every DSR in this phase is at N = 261 with the cross-trial Sharpe variance of `ml/results/improve/books/books.json` (0.00387).
- No feature, parameter or rule is chosen on test months. The paper book is N = 1 and adds no trial.
- DuckDB has one writer (Q1, lock-file protocol of phase 1). Everyone else reads `ml/results/improve/cache/*_10y.parquet`.

## 2. Streams and pass marks

### Q1. Paper book and forward record (product; no pass mark)
Frozen specification (`ml/PROGRAM_REPORT.md` §13.7): LightGBM, 52 features, retrained on the first session of each month on the trailing 504 sessions of rows whose label has exited before the signal date; score residualised per date on the ranks of `atr_pct` and `log_turnover` and re-ranked; **primary book** full-universe top decile; **capacity book** liquid-tercile top decile; **challenger** the rank ensemble (LightGBM + LambdaRank + CatBoost) on the 52 features, neutralised the same way; 20 overlapping tranches, entry at the next open, exit 20 sessions later; equal-weight universe benchmark; 20 bps and name-level costs both reported. Inception: the first session after the research data (2026-10-19). The ledger is append-only and committed. Monitors of §10 plus the two of §13.7. Deliverables: `ml/paper/` (daily job, idempotent), `ml/paper/ledger/`, `ml/paper/RUNBOOK.md`.

### Q2. Combinatorial purged cross-validation of the frozen construction (1 trial)
CPCV (López de Prado) on the 103 fold-months: N = 8 contiguous groups, k = 2 test groups → 28 splits, 7 backtest paths; training = every row outside the two test groups after purging labels that overlap a test group and a 22-session embargo after each test group. Model: the control. Readings fixed now: for the neutral full-universe top decile and for the liquid neutral top decile, the share of the 7 paths with positive net (20 bps) excess over the equal-weight universe; the construction is called **robust across paths** if the full-universe book is positive in ≥ 6 of 7 paths, and the **liquid book** likewise. CPCV trains on data after the test window by design; it measures path dependence, not forward performance.

### Q3. A model for the liquid universe (2 configurations, 4 books = 6 trials)
- **L1**: universe = liquid tercile (`cs_rank_turnover` ≥ 0.67 at t); label recomputed as beating the liquid-tercile median that date; trained and scored on liquid rows only.
- **L2**: universe = top two terciles (`cs_rank_turnover` ≥ 0.33); label vs the top-two-tercile median.
- Books: plain and neutral liquid-tercile top decile vs the equal-weight liquid tercile.
- **Pass mark (fixed):** for L1 or L2, the neutral liquid book's IR ≥ 0.5 with its month-block 95% CI excluding zero over the 105 signal months **and** its paired monthly excess over the control's neutral liquid book has a bootstrap 95% CI excluding zero.

### Q4. Market-neutral long-short on F&O names via stock futures (2 books)
Universe on date t = F&O members (a stock future exists). Long the top quintile of the control's score (plain; and neutralised) in cash; short the bottom quintile through the near-month future (next month when fewer than 3 sessions to expiry), rolled at expiry; equal weights; 20-session overlapping tranches as in the engine. Costs: long 20 bps per side; short 40 bps per side plus 10 bps per roll; short-leg return from futures settlement prices (basis convergence included). Data 2018-01..2026-09. **Pass mark:** net annualised Sharpe ≥ 1.0 with month-block 95% CI lower bound > 0, and beta to the Nifty 50 within ±0.2.

### Q5. The 40-day horizon (1 configuration, 4 books = 5 trials)
Labels on the 10y dataset: `y_raw_40d` = open[t+41]/open[t+1] − 1, excess vs the per-date universe median, binary beat label, clean mask (opens > 0, all 41 sessions present, span ≤ 88 days, no |ret_1d| > 22% on t+1..t+41, after corporate-action adjustment), exit date; splits with a **42-session embargo**. Model: the control configuration trained on the 40-day label. Books held 40 sessions (neutral full-universe and neutral liquid top decile) for the 40-day model and, as comparators, for the 20-day control's score. **Pass mark:** the 40-day model's neutral full-universe 40-session book beats the 20-day control's 40-session neutral book with a paired monthly CI excluding zero, **and** its flat break-even cost per side is higher.

### Q6. Company events from the exchange's announcement files (1 configuration, 2 books = 3 trials)
Parse every `An*.txt` in the PR bundles 2016-10..2026-10 into (date, symbol, category, text). Family E, fixed now (point in time: an announcement in the bundle of session t is usable at t, entry at t+1): `sess_since_results` (capped 126), `results_last_5`, `results_last_20`, `ear_3d` (stock minus equal-weight universe return from the close before the results session to the close after it, for the most recent results announcement within 60 sessions, NaN until t ≥ that session + 1), `ear_vol_z` (volume on the results session vs its 20-session mean), `ann_count_20` (non-routine announcements in 20 sessions; routine = NAV, trading window, newspaper publication, loss of share certificates, depository certificates), `rating_20`, `mgmt_change_60` (resignation, cessation, change in management, directors, auditors), `orders_20` (bagging/receiving of orders), `insolvency_60`. A/B **AE1** = control + family E on the 10y data. **Pass mark:** the primary mark. Secondary, descriptive: rank IC of `ear_3d` among names with a results announcement in the last 60 sessions, Newey-West t.

### Q7. Nested hyper-parameter tuning (1 configuration, 2 books = 3 trials)
Grid fixed now: `num_leaves` ∈ {31, 127} × `min_data_in_leaf` ∈ {200, 2000} × `feature_fraction` ∈ {0.5, 0.8}, with 300 trees at learning rate 0.05, plus the incumbent (63, 200, 0.8): 9 settings. Selection once per calendar year 2018..2026 on training data only: mean AUC over the last 3 inner blocks of 21 sessions before the year's first `train_end`, each block with its own rolling-504, embargo and exit-date purge; choose the best, but keep the incumbent unless a setting beats it by ≥ 0.002. Outer run on the 103 folds with each year's choice. **Pass mark:** the primary mark.

### Q8. The process as a prompt (deliverable)
`ml/PROCESS.md` (the improvement cycle as this program ran it) and `ml/PROMPT.md` (a prompt that makes an AI agent team run one cycle the same way: pre-registration, integrity first, pass marks, trial ledger, adversarial review, honest reporting).

## 3. What would change the verdict
- Q3 passing would give the program a capacity-bearing book with economics; it is the single result that could move Stage 2 within reach of a small allocation after a forward record.
- Q4 passing would give a market-neutral book on the names that can be shorted.
- Q6 or Q7 passing would be the first model-side gain above the bar in either phase.
- Nothing here replaces the forward record; Q1 starts it.
