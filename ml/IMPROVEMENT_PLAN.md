# SuryaDhana improvement phase: pre-registered plan

**Date fixed:** 2026-10-19, before any result of this phase existed · **Owner:** program lead · **Governs:** everything under `ml/results/improve/`, `ml/data_5y_v2/`, `ml/data_10y/`, `ml/data_ext/`, `ml/data_hist/`.

The five-year program (`ml/PROGRAM_REPORT.md`) ended with a real but small signal (rank IC 0.065, AUC 0.536), one book with economics (the rank ensemble, +7.0%/yr over the equal-weight universe, DSR 0.16 at N = 177) and a verdict of *no capital, paper-trade one frozen strategy*. Its §11 ranked twelve next steps. This phase executes the ones that can be executed from this environment, under the same discipline: hypotheses, metrics and pass marks are written here first; every new model configuration and every new book is a trial in the ledger; nothing is promoted on a number that was not pre-registered.

## 0. Facts verified on 2026-10-19 that shape the plan

1. **`archives.nseindia.com` is reachable from this environment** (the `www.nseindia.com` API is not). Reachable and tested: security-wise bhavcopy with delivery (`sec_bhavdata_full`, from about 2019-10), legacy `cm<DDMONYYYY>bhav.csv.zip` (to 2024-07-05) and UDiFF CM bhavcopy, `MTO_<ddmmyyyy>.DAT` delivery files (2016 onward), the daily `PR<ddmmyy>.zip` bundle (2016 onward; contains `bc` corporate actions with ex-dates and purposes, `etf` lists, `pd` with a corporate-action indicator, `sme`), F&O bhavcopy (legacy `fo<DDMONYYYY>bhav.csv.zip` to 2024-07-05, UDiFF `BhavCopy_NSE_FO_*` after; 2016 onward), `ind_close_all_<ddmmyyyy>.csv` (all indices incl. India VIX, P/E, P/B, 2016 onward), `fao_participant_oi_<ddmmyyyy>.csv` (FII/DII/Pro/Client open interest, 2021 onward tested), index constituent lists with NSE industry (Nifty 50/500, Midcap 150, Smallcap 250, Microcap 250), `EQUITY_L.csv` (listing dates, ISIN, face value).
2. **Six trading sessions are missing from `nse_market.duckdb`**, found by a prev_close continuity scan (share of tickers whose stored previous close differs from the reported `prev_close`): 2023-11-12 (Sunday Muhurat), 2024-03-02 and 2024-05-18 (Saturday special live sessions), 2025-02-01 and 2026-02-01 (weekend Budget sessions), 2025-10-21 (Muhurat session wrongly listed as a holiday in the ingest). The ingest iterates Monday to Friday only. All six files exist in the archive. A seventh date, 2022-03-08 (10.7% mismatch), is unexplained and will be investigated.
3. **Corporate actions are not adjusted and `prev_close` does not reveal them** (NSE reports the unadjusted previous close on ex-dates: NESTLEIND 2024-01-05, IRCTC 2021-10-28, TATASTEEL 2022-07-28, RELIANCE 2024-10-28 all confirmed). The authoritative daily feed is the `bc` file inside each `PR` bundle (ex-date and purpose text such as `FVSPLT FRM RS 10 TO RS 2`, `BONUS 1:1`).
4. **ISIN is empty on every stored row**, so the label study's ETF rule (ISIN prefix INF) could not be applied; the `etf` file in each `PR` bundle lists ETFs point-in-time.
5. **Compute** (43 folds + holdout, 2 threads): LightGBM on all features about 30 to 50 minutes, L2 logistic 3 minutes, LambdaRank about 30 minutes, CatBoost about 25 minutes. The box has 4 cores and 15 GB; disk headroom 22 GB.

## 1. Rules of the phase

- **Harness unchanged.** Purged walk-forward, 43 monthly folds 2023-01..2026-07, rolling 504-session window, 22-session embargo, exit-date purge, untouched holdout 2026-08-03..2026-09-16 (used once per configuration, never to choose). Seed 108. Metrics as in `ml/scale5y_report.py`: fold AUC, paired 20-session block bootstrap (B = 1000), per-date rank IC with Newey-West t, portfolio via `ml/strategy_backtest.py` at 10/20/40 bps per side against the equal-weight universe.
- **Trial ledger.** The five-year run fixed N = 177. This phase adds, before any result: 42 books (P2), 12 model configurations and books (P3), 1 configuration (P5), 3 re-runs on corrected data (P1) and 3 re-runs on the longer history (P4) = **61 new trials, N = 238**. Every Deflated Sharpe in this phase uses N = 238. Re-runs of an unchanged configuration on corrected data are counted although they test no new hypothesis; that is the conservative direction.
- **No selection on test months.** Feature lists for every A/B are fixed by family below. No feature is added or dropped because of its IC on the CV months (audit T9/T11).
- **The release criterion does not move.** The five pre-registered gates in `ml/SCALE_UP.md` decide promotion. A configuration that passes an A/B pass mark becomes a *candidate*; it is promoted only if it passes the gates on the 43 folds (gate 5 at N = 238).
- **Integrity before alpha.** Data fixes (P1) are judged on integrity criteria, never on AUC. If a fix lowers AUC, the lower number is the honest one.
- **Reporting.** Every stream writes machine-readable JSON first and Markdown that quotes it. The pass or fail of every pre-registered test is stated in the stream's Markdown. Nothing in this phase is described as "accuracy".

## 2. Streams

### P1. Data integrity (owner: data-integrity agent; DuckDB's only writer)

Deliverables: `ml/integrity/` (code), `ml/data_ext/corporate_actions_feed.csv` (ticker, ex_date, ratio, kind, source, validated), `ml/data_ext/etf_list.csv`, `ml/data_ext/equity_master.csv`, the six missing sessions upserted, the 2022-03-08 anomaly explained or fixed, the ingest's calendar fixed (special sessions, 2025-10-21 not a holiday), `equity_features` rebuilt on split/bonus-adjusted prices, the **v2 five-year dataset** in `ml/data_5y_v2/` (same folds and holdout as v1; ETFs excluded; 52 features including `deliv_value_share_20` and `amihud_20`), and `ml/results/improve/integrity/{integrity.json, INTEGRITY.md}`.

Pre-registered pass marks (integrity, not alpha):
- I1: after the fix, no session has more than 5% of tickers with a prev_close mismatch, except mismatches explained by parsed corporate actions.
- I2: parsed split and bonus ratios agree with the observed close(ex−1)/open(ex) ratio within ±15% for at least 95% of events; disagreements are listed.
- I3: `flag_split_20d` fires on fewer rows in v2 than in v1 (0.51% of rows), and `y_clean_20d` coverage rises.
- I4: zero ETFs remain in the v2 universe (checked against the daily `etf` lists).

Re-runs on v2 (lead's compute queue, 3 trials): LightGBM all 52 features (the control for every A/B in P3), L2 logistic, momentum rule. Reported next to v1 with paired fold deltas; no pass mark.

### P2. Book construction and costs on the existing out-of-sample scores (owner: book-construction agent)

Why first: the program's gap is economics, not AUC. The ensemble's +7%/yr came from an accidental volatility-neutral blend; the classifiers' top deciles are defensive and trail the universe. Turnover of 67% to 77% per rebalance puts costs at one third of gross active return.

Inputs: v1 predictions (`ml/results/scale5y/preds/`), v1 dataset, `ml/results/improve/cache/features_prices_export_v1.parquet` (open/high/low/close/turnover; the DuckDB is not touched), NSE industry map.

Fixed grid (42 trials): scorers {nested_lgbm, all51, nested_ensemble_rank} × neutralisation {none; volatility (`atr_pct`); volatility + size (`atr_pct`, `log_turnover`); volatility + size + industry (industry-demeaned, NSE classification where known, else "Unclassified")} × basket {top decile; top quintile; buffered decile (enter top 10%, hold while within top 20%)} = 36 long-only books; plus the three scorers' liquid-tercile buffered volatility+size-neutral books (3); plus the three scorers' volatility+size-neutral top decile held 40 sessions (3). Neutralisation = per-date OLS residual of the score's percentile rank on the controls' percentile ranks, re-ranked. Costs: 20 bps per side headline (10/40 reported) and one pre-specified name-level model: Corwin-Schultz high-low spread (60-session median) half-spread per side plus square-root impact 0.1·σ_daily·√(order/ADV) for a ₹100 crore book, floored at 11 bps statutory per side.

Pass marks:
- B1 (deliberate neutralisation recovers economics in a single model): for nested_lgbm or all51, the volatility+size-neutral top decile beats the equal-weight universe net of 20 bps with the 95% month-block CI of the IR excluding zero and IR ≥ 0.5.
- B2 (turnover is the first lever): the buffered decile cuts turnover per rebalance by ≥ 30% and its monthly net excess is not lower than the plain decile's (paired monthly difference CI not entirely below zero).
- B3 (longer holding): the 40-session book's annual net excess is within 1 pp of the 20-session book's with turnover at most half.
- The original 24 books must reproduce `portfolio_5y.json` before any variant is run (acceptance test).
- DSR for every book at N = 238; gates 3 and 5 re-scored for any book passing B1.

### P3. External data and market state (owner: external-data agent; A/Bs run by the lead)

Ingest 2021-10-01..2026-10-16 into staging parquet under `ml/data_ext/` (never into the DuckDB): stock futures and options (near-month settle, total OI, OI change, basis, put/call OI), all indices (close, P/E, P/B, India VIX), participant-wise open interest, industry map, equity master.

Feature families (point-in-time, from data dated ≤ t):
- F1 market state (10): EW-universe 20d and 63d return, 252d drawdown, 20d volatility, breadth above 200-DMA, sessions since a −8% 20d move, cross-sectional dispersion of mom_20, India VIX close and 20d change, Nifty 50 P/E.
- F2 sector (about 10): industry median mom_20 and ret_63d, stock-minus-industry mom_20 and ret_126d, delivery relative to industry, industry-neutral ranks of mom_20, ret_126d, deliv_pct_sma_20, atr_pct; mapped sector-index 20d return.
- F3 F&O (about 8): membership, near-month basis, 5d and 20d log change of total futures OI, 60d OI z-score, put/call OI ratio and its 5d change, option OI to turnover.
- F4 flows (about 4): FII net index-futures positioning and its 5d change, FII net stock-futures positioning, client index-option put/call.

A/Bs on the v2 dataset, control = LightGBM on 52 features (6 configurations, each also scored as a volatility+size-neutral top-decile book = 12 trials): AB1 control + F1; AB2 control + F2; AB3 control + F3; AB4 control + F4; AB5 control + all; AB6 the three-member rank ensemble on all 52 features without yearly re-selection (the A/B queued in §11 item 4).

Pass mark per A/B: paired fold-level AUC delta vs control with the 20-session block-bootstrap 95% CI excluding zero **and** mean delta ≥ +0.003; secondary: rank-IC delta with Newey-West t ≥ 2; for AB1 additionally mean AUC over the six inversion months (2023-07, 2024-01, 2025-04, 2025-05, 2026-03, 2026-04) improves by ≥ +0.02. Economics of each book are reported; the gates decide.

### P4. History 2016-10..2021-09 (owner: history agent; dataset and re-runs by the lead)

Parse legacy CM bhavcopy + MTO delivery + PR bundles for about 1,235 sessions into `ml/data_hist/` staging parquet with the `equity_eod` schema. After P1's write window, the lead upserts, applies the corporate-action feed to the full history, rebuilds features and builds `ml/data_10y/` (folds 2018-01..2026-07, 103 months, same embargo and holdout). Re-runs (3 trials): control, L2 logistic, momentum. No pass mark: the purpose is evidence across the 2018 small-cap bear, the 2020 crash and the 2021 boom, and a Stage-0 "not one regime" test over eight years instead of one episode.

### P5. Hygiene and delivery durability (owner: hygiene agent)

- Probability of backtest overfitting (Bailey, Borwein, López de Prado & Zhu CSCV, S = 16) on the five-year run: configurations × monthly AUC and books × monthly net excess. Reading fixed in advance: PBO above 0.5 means selection among those trials was no better than chance.
- Delivery durability: IC of `deliv_pct_sma_20` and `deliv_value_share_20` by year × liquidity tercile × market direction; residual IC after per-date regression on `log_turnover`, `atr_pct`, `mom_12_1`; the pre/post March-2026 difference with a block bootstrap. "Durable" = residual IC > 0 with 95% CI excluding zero in at least 3 of the 4 calendar years and in both liquidity halves.
- Uniqueness weights: computed for one training window; if average uniqueness is near-constant (fixed-horizon labels), the item is closed with that evidence. AB7 (1 trial): LightGBM control trained on every fifth signal date, to measure what overlapping labels add or inflate.

### P6. Integration (lead)

Gates re-scored for any candidate; trial ledger updated to N = 238; `ml/PROGRAM_REPORT.md` gains a section for this phase; `ml/GOALS.md` status updated; the HTML program report regenerated; PR #2 updated. Items that stay open are written as a roadmap with the exact next action and what it needs.

## 3. Coordination

- **DuckDB has one writer.** Only P1 opens `nse_market.duckdb` read-write. While it writes it creates `ml/results/improve/LOCK_duckdb_write`; every other process uses the parquet exports in `ml/results/improve/cache/` and never opens the DuckDB while the lock exists.
- **v1 artefacts are frozen.** `ml/data_5y/`, `ml/results/scale5y/`, `ml/results/preds/` are read-only for this phase.
- **Downloads** go to `ml/data_raw/<stream>/` (gitignored), resume-safe, browser user agent, random 1.0 to 2.0 s delay, 60 s back-off on 403/429/5xx, never more than one request in flight per stream.
- **Compute** is a single queue run by the lead: OMP_NUM_THREADS=2, at most two worker processes per job, one training job at a time while agents are active.
- **Nothing in `ml/data_*`, `ml/results/*/preds/`, `*.duckdb`, `ml/data_raw/` is committed.**

## 4. What would change the verdict

- A single-model book passing B1 and then gates 3 and 5 at N = 238 would make the paper-trading candidate a deliberate construction rather than an accidental blend.
- An A/B passing its pass mark would be the first evidence in this program that information outside the bhavcopy adds to the signal; it would still have to pass the gates.
- Eight years of folds showing the Stage-0 criteria hold outside the 2025-09..2026-02 episode would move the proof from one regime to several.
- None of these can supply a live track record. Stage 2 is still decided by the paper book.

## 5. Amendments (each dated, each before its result existed)

- **A1, 2026-10-19 13:00. AB0: LightGBM on 52 features against the 50-feature `all51` on the frozen v1 data.** `ml/PROGRAM_REPORT.md` §11 item 4 queued this A/B; running it on v1 isolates the two sufficiency features from the data fixes of P1. Pass mark: the primary mark of P3 with the sign reversed (52 beats 50 by ≥ +0.003 CV-mean AUC with the paired block-bootstrap 95% CI excluding zero). One configuration: **N = 239**.
