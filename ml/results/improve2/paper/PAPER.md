# Paper book: forward record

Source of every number: `ml/results/improve2/paper/paper.json` (spec hash `327a8d3801b37d58`, as of session 2026-10-22). Specification and definitions: `ml/paper/SPEC.md`; daily procedure: `ml/paper/RUNBOOK.md`. No capital; the paper book is N = 1 and adds no trial.

## Status

- Inception signal date 2026-10-19; last store session 2026-10-22; last signal date 2026-10-22; last marked session 2026-10-22.
- Ledger rows: signals 1521, marks 8, monitors 48.
- Models: 2026-09 (monitor only (logistic sign-flip baseline), logistic, trained as of 2026-09-01 on 682,669 rows 2024-07-19..2026-07-31); 2026-10 (paper model, lgbm, lambdarank, catboost, logistic, trained as of 2026-10-01 on 683,106 rows 2024-08-20..2026-08-31)

## Sessions ingested after the research data

| Date | Weekday | Decision | DATE1 | Echo of previous | PR bundle | EQ/BE rows |
|---|---|---|---|---|---|---:|
| 2026-10-19 | Monday | session: ingest | 19-Oct-2026 | False (file bytes identical: None) | present | 2922 |
| 2026-10-20 | Tuesday | closure: holiday echo of the previous session (duplicate-day guard) and no PR bundle | 19-Oct-2026 | True (file bytes identical: True) | absent | 2922 |
| 2026-10-21 | Wednesday | session: ingest | 21-Oct-2026 | False (file bytes identical: False) | present | 2916 |
| 2026-10-22 | Thursday | session: ingest | 22-Oct-2026 | False (file bytes identical: False) | present | 2915 |
| 2026-10-23 | Friday | pending: file not yet published |  |  |  |  |

Write: 10218 rows upserted, lock held 89.0 s, verified True, backup deleted after verification True. Continuity on the new sessions: 2026-10-19 1 of 2922 (0.03%), 2026-10-21 0 of 2915 (0.00%), 2026-10-22 0 of 2912 (0.00%); duplicate EQ/BE pairs 0. equity_eod through 2026-10-16: identical True; equity_features non-label columns of 3935 tickers unchanged except new corporate-action tickers True (changed: ['JSWDULUX']); forward label columns (fwd_ret_2d..5d, label_up_2d..5d) changed on 14704 rows dated 2026-04-15..2026-10-16: 14610 were each ticker's last 5 rows (NaN before; build_features shifts by rows, so they now reach the new sessions), 94 belong to the new corporate-action ticker, 0 unexplained.
New validated corporate actions: [{'ticker': 'JSWDULUX', 'ex_date': '2026-10-22', 'ratio': 0.1, 'kind': 'split', 'source': 'PR151026.zip/bc15102026.csv'}]. Unvalidated split/bonus in the window: []. Price breaks: 0. Upcoming split/bonus ex-dates: [('AZADIND', '2026-10-23')]. Rebuilt feed equals the ten-year feed through the research end: True. New ETF symbols: [].

## Consistency proof (scoring frame vs `ml/data_10y`)

Rule: exact equality per cell (NaN equals NaN); max_abs_diff over finite pairs.

| Rows compared | Common rows | Only frame | Only 10y | Max abs diff (52 features) | Cells differing | Unexplained cells | Bit-identical | Equal except the new corporate action's rounding |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 2026-10-16 | 1527 | 0 | 0 | 3.4e-13 | 16 | 0 | False | True |
| every date through 2026-10-16 | 2226504 | 0 | 0 | 5.8e-13 | 3204 | 0 | False | True |

Why not bit-identical: the live corporate-action feed adds JSWDULUX (price ratio 0.1, ex 2026-10-22) after the research end, so build_features rescales that ticker's earlier prices by the ratio; every price ratio is unchanged up to floating-point rounding. On 2026-10-16 the 16 differing cells are all in JSWDULUX (16 features, at most 3.4e-13); the other 1526 rows of that date are bit-identical. Over every date, 3204 cells differ (at most 5.8e-13) on 119 dates, every one of them that ticker's own row or a cross-sectional feature (`amihud_20` z-score, ranks) on a date where that ticker is in the universe; 0 are unexplained. Rule of explanation: a cell of a ticker whose pre-ex prices the new event rescales, or a cross-sectional feature (ranks, amihud_20 z-score) on a date where that ticker is in the universe.

Point in time: signal dates 2026-10-19, 2026-10-21 and 2026-10-22 were scored on 2026-10-23 (the day this stream started) from the store as of 2026-10-22. Every feature looks back only, so a date's frame rows do not depend on later sessions except through a corporate action added later, which rescales that ticker's earlier prices (here JSWDULUX, ex 2026-10-22): the consistency proof above is exactly that check at 2026-10-16 (a frame built through 2026-10-22 against the research frame built through 2026-10-16), and it differs only by floating-point rounding in that one ticker. From 2026-10-23 on, each session is scored on its own evening.

Trainer reproduction: the paper trainer on the research holdout fold (train end 2026-07-02, 682,309 training rows) scores 47,117 holdout rows; max |score − ten-year control score| = 0.0; identical True.

## Inception baskets (signal date 2026-10-19, entry at the next session's open)

Model 2026-10; universe 1523 names, liquid tercile 503. Scores: neutralised percentile for the neutral books, LightGBM probability for the plain reference.

| Book | Names | Top 10 (rank: ticker) |
|---|---:|---|
| primary | 152 | 1: MENONBE, 2: GLOBAL, 3: UNITEDPOLY, 4: KIRLFER, 5: MANGLMCEM, 6: ULTRAMAR, 7: ARROWGREEN, 8: BLISSGVS, 9: MANBA, 10: SWANDEF |
| capacity | 50 | 1: MARINE, 2: KARAMTARA, 3: AUGMONT, 4: DIACABS, 5: XPROINDIA, 6: AYE, 7: KMEW, 8: POLICYBZR, 9: ENTERO, 10: AEQUS |
| challenger | 152 | 1: GLOBAL, 2: KIRLFER, 3: KOVAI, 4: IIFLCAPS, 5: MANGLMCEM, 6: ULTRAMAR, 7: MANBA, 8: KAPSTON, 9: AAREYDRUGS, 10: MENONBE |
| control_plain | 152 | 1: KOVAI, 2: HAL, 3: MENONBE, 4: POWERGRID, 5: ICICIBANK, 6: GAIL, 7: INDHOTEL, 8: IIFLCAPS, 9: POLICYBZR, 10: ONEPOINT |

Latest signal date 2026-10-22: primary 153 names, capacity 50 names, challenger 153 names, control_plain 153 names.

## Marks (fixed capital: 1/20 per tranche, idle capital at zero)

| Book | Sessions | Exposure (last) | Gross | Net 20 bps | Net name-level | Benchmark | Active net 20 bps |
|---|---:|---:|---:|---:|---:|---:|---:|
| primary | 2 (2026-10-21..2026-10-22) | 0.10 | -0.21% | -0.23% | -0.26% | -0.23% (ew_universe) | -0.00% |
| capacity | 2 (2026-10-21..2026-10-22) | 0.10 | -0.24% | -0.26% | -0.28% | -0.21% (ew_liquid) | -0.05% |
| challenger | 2 (2026-10-21..2026-10-22) | 0.10 | -0.18% | -0.20% | -0.23% | -0.23% (ew_universe) | +0.03% |
| control_plain | 2 (2026-10-21..2026-10-22) | 0.10 | -0.16% | -0.18% | -0.19% | -0.23% (ew_universe) | +0.05% |

A few sessions of a ramping book say nothing about the strategy; these lines exist so that the record starts on the day it should.

## Monitors as of 2026-10-22

| Monitor | Scope | Value | Threshold | Status | Detail |
|---|---|---:|---:|---|---|
| delivery_resid_ic | pre-inception | 0.0823414 | 0.02 | ok | months 2026-07 +0.0407, 2026-08 +0.0823 (raw IC +0.0522, +0.0294) |
| live_model_auc | pre-inception | 0.519292 | 0.5 | warming up (needs every 2026-10 signal date's 20-session label; the month's last signal date's label exits 21 sessions after it) | research walk-forward: fold 2026-07 0.5474, holdout 2026-08-03..2026-09-16 0.5193 |
| rank_ic_nw_t_12m | pre-inception | 4.02305 | 2 | ok | 223 matured signal dates in the trailing 12 months (0 live), mean IC +0.0865; last matured date 2026-09-16 |
| logistic_sign_flips | 2026-09 -> 2026-10 | 0 | 0 | ok | top 5: log_turnover -0.1719 (prev -0.2024), cs_rank_turnover +0.1688 (prev +0.1867), macd_norm -0.1612 (prev -0.1872), dist_52w_high +0.1263 (prev +0.1314), amihud_20 -0.1244 (prev -0.1351) |
| feature_psi | trailing 20 sessions vs 2026-10 training window | 0.259355 | 0.25 | ALERT | highest: ret_126d 0.259, dist_sma_50 0.141, dist_sma_20 0.134, rsi_14 0.133, mom_20 0.129; features above 0.25: 1 |
| paper_active_ir_6m | primary |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) -0.0023%; benchmark ew_universe |
| paper_active_ir_6m | capacity |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) -0.0526%; benchmark ew_liquid |
| paper_active_ir_6m | challenger |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) +0.0263%; benchmark ew_universe |
| paper_active_ir_6m | control_plain |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) +0.0485%; benchmark ew_universe |
| feature_inversion | pre-inception | 0.634615 | 0.5 | ALERT | month 2026-08: 33 of 52 features against their training-window sign (gap_pct, range_pct, dist_sma_5, dist_sma_10, dist_sma_20, dist_sma_50, macd_norm, mom_5 ...) |
| ensemble_atr_corr | month 2026-10 to date | 0.0770095 | 0.2 | ok | 3 signal dates; per-date range +0.045..+0.094 |
| neutral_score_corr | primary | 0.0394913 | 0.05 | ok | atr_pct -0.0095, log_turnover +0.0395 |
| neutral_score_corr | challenger | 0.0399362 | 0.05 | ok | atr_pct +0.0105, log_turnover +0.0399 |
| universe_etf_count | signal date | 0 | 0 | ok | 1527 universe names |
| split_flag_rate | signal date | 0.00261952 | 0.01 | ok | 4 of 1527 universe names |
| data_quality | store | 0 | 0.05 | ok | continuity mismatches 0 of 2912; duplicate EQ/BE pairs 0; write verified True; unvalidated split/bonus on this date 0; price breaks 0; recorded closures to date ['2026-10-20'] |

Deflated Sharpe of the daily active net-20 bps series (N = 261, V[SR] = 0.00387): primary warming up (needs marks); capacity warming up (needs marks); challenger warming up (needs marks); control_plain warming up (needs marks).

## Idempotency proof

A second run on the same data (ml/paper/job.py --prove-idempotency, run after the first full run on the same store; scoring frame rebuilt from the store in this run: False; ingest decisions [['2026-10-23', 'pending: file not yet published']]): ledger SHA-256 before and after identical True; rows appended 0; recomputed signals of 2026-10-22 equal the ledger True; recomputed marks equal the ledger True.

| File | SHA-256 before | SHA-256 after |
|---|---|---|
| signals | `3534d3d7961f3677` | `3534d3d7961f3677` |
| marks | `823d5bec0929e5cc` | `823d5bec0929e5cc` |
| monitors | `6ce48f110ab264f3` | `6ce48f110ab264f3` |
| state | `43e6bb1abfd9abf7` | `43e6bb1abfd9abf7` |

## Lost-state check

ml/paper/state/models/2026-10/ (all four model files) and ml/paper/state/scores/scores_2026-10-19.parquet deleted; then OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --no-ingest: the October models were retrained and equal the committed metadata ({'training_frame_sha256': True, 'reference_prediction_sha256': True, 'model_contents_sha256': True}); regenerated score files ['2026-10-19'] byte-identical True; ledger and model metadata unchanged True. CatBoost .cbm bytes carry train_finish_time and a random model_guid; its identity is the SHA-256 of the model exported without model_info (content_sha256); predictions of the original and the retrained CatBoost on 83,754 rows (2026-08-01..2026-10-22) differ by 0.0.

Live corporate-action feed: ml/data_ext/corporate_actions_feed_live.csv deleted; ml.paper.ingest.regenerate_live_feed (the path a run takes when the feed is missing after the research end) rebuilt it from the store's EQ/BE rows and every PR bundle on disk; byte-identical to the original True, equal to the hash in state.json True (756 rows).

## Determinism proof (ledger regenerated from inception)

ml/paper/prove.py: the job (--no-ingest) run from an empty ledger in ml/paper/state/regen/ with the same store, scoring frame and month models; every write redirected to the sandbox. Rows regenerated: {'signals': 1521, 'marks': 8, 'monitors': 48} for signal dates ['2026-10-19', '2026-10-21', '2026-10-22']; ledger byte-identical to the committed files True; per-date score files identical True; committed ledger untouched True.

| File | Committed SHA-256 | Regenerated SHA-256 |
|---|---|---|
| signals | `3534d3d7961f3677` | `3534d3d7961f3677` |
| marks | `823d5bec0929e5cc` | `823d5bec0929e5cc` |
| monitors | `6ce48f110ab264f3` | `6ce48f110ab264f3` |
| state | `43e6bb1abfd9abf7` | `43e6bb1abfd9abf7` |

