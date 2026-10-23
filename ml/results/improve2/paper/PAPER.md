# Paper book: forward record

Source of every number: `ml/results/improve2/paper/paper.json` (spec hash `327a8d3801b37d58`; extension 1 spec hash `a8d20cae4d930197`, as of session 2026-10-22). Specification and definitions: `ml/paper/SPEC.md`; daily procedure: `ml/paper/RUNBOOK.md`. No capital; the paper book is N = 1 and adds no trial.

## Status

- Inception signal date 2026-10-19; last store session 2026-10-22; last signal date 2026-10-22; last marked session 2026-10-22.
- Ledger rows: signals 1521, marks 8, monitors 48 (the four frozen books); extension 1: signals 607, marks 4, monitors 15.
- Models: 2026-09 (monitor only (logistic sign-flip baseline), logistic, trained as of 2026-09-01 on 682,669 rows 2024-07-19..2026-07-31); 2026-10 (paper model, lgbm, lambdarank, catboost, logistic, trained as of 2026-10-01 on 683,106 rows 2024-08-20..2026-08-31)
- Extension 1 (SPEC.md amendment 10, registered 2026-10-23T09:17:13Z, spec hash `a8d20cae4d930197`; the frozen books' spec hash `327a8d3801b37d58` is unchanged): books challenger_expanding, capacity_expanding; expanding-window models: 2026-10 (lgbm, trained as of 2026-10-01 on 2,170,733 rows 2017-10-03..2026-08-31).

## Sessions ingested after the research data, and store writes

| Date | Weekday | Decision | DATE1 | Echo of previous | PR bundle | EQ/BE rows |
|---|---|---|---|---|---|---:|
| 2026-10-19 | Monday | session: ingest | 19-Oct-2026 | False (file bytes identical: None) | present | 2922 |
| 2026-10-20 | Tuesday | closure: holiday echo of the previous session (duplicate-day guard) and no PR bundle | 19-Oct-2026 | True (file bytes identical: True) | absent | 2922 |
| 2026-10-21 | Wednesday | session: ingest | 21-Oct-2026 | False (file bytes identical: False) | present | 2916 |
| 2026-10-22 | Thursday | session: ingest | 22-Oct-2026 | False (file bytes identical: False) | present | 2915 |
| 2026-10-23 | Friday | pending: file not yet published |  |  |  |  |

Write (2026-10-23): 10218 rows upserted, lock held 89.0 s, verified True, backup deleted after verification True. Continuity scan on the new sessions (share of names whose prev_close differs from the stored previous close): 2026-10-19 1 of 2922 (0.03%), 2026-10-21 0 of 2915 (0.00%), 2026-10-22 0 of 2912 (0.00%); duplicate EQ/BE pairs 0. Per-name prev_close breaks above 22% (checked by the later features_rebuild write of 2026-10-23): 2026-10-19 1 of 2922, 2026-10-21 0 of 2915, 2026-10-22 0 of 2912 (2026-10-19 CCAVENUE prev_close 138.3 vs stored close 13.83 of 2026-10-12 (x10): explained by feed); unexplained 0. equity_eod through 2026-10-16: identical True; equity_features non-label columns of 3935 tickers unchanged except the tickers whose feed lines changed True (changed: ['JSWDULUX']); forward label columns (fwd_ret_2d..5d, label_up_2d..5d) changed on 14704 rows dated 2026-04-15..2026-10-16: 14610 were each ticker's last 5 rows (NaN before; build_features shifts by rows, so they now reach the new sessions), 94 belong to the tickers whose feed lines changed, 0 unexplained.
New validated corporate actions (cumulative since the research end, as of this write): [('JSWDULUX', '2026-10-22', 0.1)]. Unvalidated split/bonus in the window: []. Price breaks (unadjustable actions): 0. Upcoming split/bonus ex-dates: [('AZADIND', '2026-10-23')]. Rebuilt feed equals the ten-year feed through the research end: True. New ETF symbols: [].

**Repair write (2026-10-23, no new session): `ml/paper/ingest.py --rebuild-features`.** Reason: CCAVENUE 10:1 consolidation (record date 2026-10-13, suspended 13-16 Oct, first print 2026-10-19) unadjusted: parser extension and widened live window (SPEC.md amendment 4). Live feed lines added: [{'ticker': 'CCAVENUE', 'ex_date': '2026-10-13'}]; the live feed is the ten-year feed's bytes plus 2 lines (757 rows, starts with the ten-year bytes True). Parser extension: purposes read ['CNSLDATN RE 1 TO RS 10', 'CNSLDATNRE1 TO RS10', 'CNSLDATNRS10 TO RS1000'], ex-dates taken from the record date [('CCAVENUE', '2026-10-13'), ('KAUSHALYA', '2024-01-12'), ('SIGNET', '2018-08-14')]. Lock held 98.5 s, verified True ({'row_count_as_expected': True, 'equity_features_rows_equal_eq_be_rows': True, 'no_duplicate_eq_be_pairs': True, 'continuity_share_below_5pct': True, 'no_unexplained_price_break': True, 'non_forward_unchanged_except_changed_ca_tickers': True, 'equity_eod_through_research_end_identical': True, 'forward_label_changes_explained': True}), backup deleted after verification True. Sessions re-checked: ['2026-10-19', '2026-10-21', '2026-10-22']. Per-name prev_close breaks above 22% (checked by this write): 2026-10-19 1 of 2922, 2026-10-21 0 of 2915, 2026-10-22 0 of 2912 (2026-10-19 CCAVENUE prev_close 138.3 vs stored close 13.83 of 2026-10-12 (x10): explained by feed); unexplained 0. equity_eod through 2026-10-16: identical True; equity_features non-label columns of 3935 tickers unchanged except the tickers whose feed lines changed True (changed: ['CCAVENUE']); forward label columns (fwd_ret_2d..5d, label_up_2d..5d) changed on 132 rows dated 2026-02-03..2026-10-12: 0 were each ticker's last 5 rows (NaN before; build_features shifts by rows, so they now reach the new sessions), 132 belong to the tickers whose feed lines changed, 0 unexplained.
Research-period events the parser extension finds and the ten-year feed lacks (reported, not applied): [['KAUSHALYA', '2024-01-12', 100.0], ['SHEKHAWATI', '2024-08-28', 10.0], ['VERTOZ', '2025-06-25', 10.0]]; rebuilt feed equals the ten-year feed apart from the extension: True.

## Superseded first ledger (regenerated from inception on 2026-10-23)

The first ledger (written on 2026-10-23 for signal dates 2026-10-19, 2026-10-21 and 2026-10-22, held only in work-in-progress commits) was built before CCAVENUE's 10:1 consolidation was adjusted: its bc record ('CNSLDATNRE1 TO RS10', EX_DT empty, record date 2026-10-13, PR121026.zip) was not read by the corporate-action parser, and the live window kept only ex-dates after 2026-10-16 while CCAVENUE was suspended 13-16 October and first printed again on 2026-10-19. Its features on all three signal dates carried ret_1d = +8.40 (true -0.060), and it sat in every book. The store was repaired (ml/paper/ingest.py --rebuild-features, verified) and the ledger regenerated from inception with the same frozen construction and the same October models (ml/paper/SPEC.md section 3 and amendment 4).

Superseded files: `ml/results/improve2/paper/superseded_2026-10-23` ({'signals': 1521, 'marks': 8, 'monitors': 48}). The regenerated ledger uses the same frozen construction, the same October models (content hashes {'lgbm': True, 'lambdarank': True, 'catboost': True, 'logistic': True}) and the repaired store. CCAVENUE's neutral LightGBM score: 2026-10-19 0.979 -> 0.392, 2026-10-21 0.967 -> 0.428, 2026-10-22 0.978 -> 0.262.

| Signal date | Book | Names before | Names after | Left the book | Entered the book |
|---|---|---:|---:|---|---|
| 2026-10-19 | primary | 152 | 152 | CCAVENUE | NORTHARC |
| 2026-10-19 | capacity | 50 | 50 | GAIL | GMRAIRPORT |
| 2026-10-19 | challenger | 152 | 152 | THERMAX, TIMEX | STARHEALTH, STEELCAS |
| 2026-10-19 | control_plain | 152 | 152 | AUGMONT, CCAVENUE | COFORGE, WELENT |
| 2026-10-21 | primary | 152 | 152 | CCAVENUE | SHILPAMED |
| 2026-10-21 | capacity | 50 | 50 | ASTRAMICRO, CCAVENUE | MANORAMA, NBCC |
| 2026-10-21 | challenger | 152 | 152 | UNIPARTS | ELGIEQUIP |
| 2026-10-21 | control_plain | 152 | 152 | CCAVENUE, SKYGOLD | CCL, IFBIND |
| 2026-10-22 | primary | 153 | 153 | CCAVENUE, KIMS | CUPID, GREENPLY |
| 2026-10-22 | capacity | 50 | 50 | SBCL | ACMESOLAR |
| 2026-10-22 | challenger | 153 | 153 | RANEHOLDIN | WESTLIFE |
| 2026-10-22 | control_plain | 153 | 153 | CCAVENUE, GLAND | FOSECOIND, PVRINOX |

## Consistency proof (scoring frame vs `ml/data_10y`)

Rule: exact equality per cell (NaN equals NaN); max_abs_diff over finite pairs.

| Rows compared | Common rows | Only frame | Only 10y | Max abs diff (52 features) | Cells differing | Unexplained cells | Bit-identical | Equal except the new corporate action's rounding |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 2026-10-16 | 1527 | 0 | 0 | 3.4e-13 | 16 | 0 | False | True |
| every date through 2026-10-16 | 2226504 | 0 | 0 | 6.1e-13 | 5438 | 0 | False | True |

Why not bit-identical: the live corporate-action feed adds CCAVENUE (price ratio 10, ex 2026-10-13), JSWDULUX (price ratio 0.1, ex 2026-10-22) to the ten-year feed, so build_features rescales those tickers' earlier prices by the ratio; every price ratio is unchanged up to floating-point rounding. On 2026-10-16 the 16 differing cells are all in JSWDULUX (16 features, at most 3.4e-13); the other 1526 rows of that date are bit-identical. Over every date, 5438 cells differ (at most 6.1e-13) on 165 dates in 1188 tickers (cells by feature: ret_1d 116, log_ret_1d 116, gap_pct 226, range_pct 245, close_pos_in_range 272, dist_sma_5 153, dist_sma_10 162, dist_sma_20 151, dist_sma_50 119, macd_norm 273, mom_5 111, mom_10 121, mom_20 97, vol_5 266, vol_10 269, vol_20 237, rsi_14 213, atr_pct 238, dist_52w_high 140, dist_52w_low 126, rsi_2 243, ret_63d 80, ret_126d 14, dist_200dma 26, amihud_20 1424), every one of them a rescaled ticker's own row or a cross-sectional feature (`amihud_20` z-score, ranks) on a date where a rescaled ticker is in the universe, which is why so many tickers carry a rounding-level `amihud_20` difference; 0 are unexplained. Rule of explanation: a cell of a ticker whose pre-ex prices the new event rescales, or a cross-sectional feature (ranks, amihud_20 z-score) on a date where that ticker is in the universe.

Point in time: signal dates 2026-10-19, 2026-10-21 and 2026-10-22 were scored on 2026-10-23 (the day this stream started) from the store as of 2026-10-22, after the corporate-action repair of that day. Every feature looks back only, so a date's frame rows do not depend on later sessions except through a corporate action added later, which rescales that ticker's earlier prices (here JSWDULUX, split ex 2026-10-22): the consistency proof above is exactly that check at 2026-10-16 (a frame built through 2026-10-22 against the research frame built through 2026-10-16), and it differs only by floating-point rounding in that one ticker. CCAVENUE's consolidation (record date 2026-10-13) was announced in the 2026-10-12 bundle, so adjusting it before scoring 2026-10-19 uses no later information. From 2026-10-23 on, each session is scored on its own evening.

Trainer reproduction: the paper trainer on the research holdout fold (train end 2026-07-02, 682,309 training rows) scores 47,117 holdout rows; max |score − ten-year control score| = 0.0; identical True (every holdout row the research data could label (label exit on or before the research end) is present in both and scores exactly the same). Not compared: 3 test rows whose label exits after the research end, so the research data could not label them (CCAVENUE 2026-09-10 exit 2026-10-19, CCAVENUE 2026-09-11 exit 2026-10-21, CCAVENUE 2026-09-15 exit 2026-10-22; a 20-row label window that crosses a trading suspension into the sessions after the research end).

## Inception baskets (signal date 2026-10-19, entry at the next session's open)

Model 2026-10; universe 1523 names, liquid tercile 503. Scores: neutralised percentile for the neutral books, LightGBM probability for the plain reference.

| Book | Names | Top 10 (rank: ticker) |
|---|---:|---|
| primary | 152 | 1: MENONBE, 2: GLOBAL, 3: UNITEDPOLY, 4: KIRLFER, 5: MANGLMCEM, 6: ULTRAMAR, 7: ARROWGREEN, 8: BLISSGVS, 9: MANBA, 10: SWANDEF |
| capacity | 50 | 1: MARINE, 2: KARAMTARA, 3: AYE, 4: DIACABS, 5: XPROINDIA, 6: POLICYBZR, 7: ENTERO, 8: KMEW, 9: AEQUS, 10: NEOGEN |
| challenger | 152 | 1: GLOBAL, 2: KIRLFER, 3: KOVAI, 4: IIFLCAPS, 5: MANGLMCEM, 6: ULTRAMAR, 7: KAPSTON, 8: MANBA, 9: AAREYDRUGS, 10: MENONBE |
| control_plain | 152 | 1: KOVAI, 2: HAL, 3: MENONBE, 4: POWERGRID, 5: ICICIBANK, 6: GAIL, 7: INDHOTEL, 8: IIFLCAPS, 9: POLICYBZR, 10: ONEPOINT |
| challenger_expanding (model 2026-10 expanding) | 152 | 1: CNL, 2: GLOBAL, 3: ARROWGREEN, 4: AAREYDRUGS, 5: MMFL, 6: KAPSTON, 7: INDOTECH, 8: DHARMAJ, 9: MODIS, 10: YASHO |
| capacity_expanding (model 2026-10 expanding) | 50 | 1: AUGMONT, 2: ENTERO, 3: XPROINDIA, 4: AKUMS, 5: UNIMECH, 6: AETHER, 7: SENORES, 8: KMEW, 9: QPOWER, 10: SHADOWFAX |

Latest signal date 2026-10-22: primary 153 names, capacity 50 names, challenger 153 names, control_plain 153 names, challenger_expanding 153 names, capacity_expanding 50 names.

## Extension 1: expanding-window challenger (SPEC.md amendment 10)

Registered 2026-10-23T09:17:13Z; extension spec hash `a8d20cae4d930197`; the frozen books' spec hash `327a8d3801b37d58` and their rows are unchanged byte for byte.

Why: Plan 2 amendment A1 (Q9): the control with an expanding training window passed the primary AUC mark (delta CV-mean AUC +0.0079, 95% CI [+0.0047, +0.0113], ml/results/improve2/expanding/EXPANDING.md); the plan says a pass is evidence for a forward test, not a promotion, and until this amendment no forward book ran it. The hypothesis was formed after the CPCV reading was seen, so this record, not the backtest, is the test.

What: challenger_expanding is the primary book in every respect (LightGBM champion configuration, the 52 features, per-date vol+size neutralisation on the full universe, full-universe top decile, 20 overlapping tranches, entry at the next open, 20-session hold, 20 bps and name-level costs, equal-weight universe benchmark) except the monthly model's training window: every labelled clean row whose label exit date is before the model date, from the first dataset row (2017-10-03), with no 504-session cap (ml/improve/ab.py q9_expanding). capacity_expanding is its liquid-tercile version, as the capacity book is to the primary (benchmark: the equal-weight liquid tercile).

Backfill: The two books were added on 2026-10-23 and backfilled from inception (signal dates 2026-10-19, 2026-10-21 and 2026-10-22) with the 2026-10 expanding-window model, trained as of 2026-10-01 on the data available then: rows dated up to 2026-08-31 (train_end, 22 sessions before the model date) whose label exit date is before 2026-10-01 (exit-date purge), exactly as the frozen October model was trained but with the expanding window. This is legitimate: the three signal dates are after the research data (which end 2026-10-16), the model uses no data dated after its model date, and every choice in the books' definition was fixed by amendment A1 before Q9 ran. The frozen books' first three signal dates were themselves scored in one catch-up run on 2026-10-23; the extension's were scored the same day, after the frozen books' first two marked sessions (2026-10-21, 2026-10-22) were in the ledger. No parameter of the extension depends on those marks.

Model 2026-10 (`ml/paper/models/expanding/2026-10.json`): trained as of 2026-10-01 (train_end 2026-08-31), 2,170,733 rows, 2209 sessions 2017-10-03..2026-08-31, 2451 tickers, 0 rows removed by the exit-date purge, label mean 0.5002; fit 96.8 s with two threads; LightGBM file SHA-256 `2bff7d9757ea4fd2`.

Trainer reproduction: the paper's expanding-window trainer on the research holdout fold (train end 2026-07-02, 2,110,109 training rows 2017-10-03..2026-07-02, the same rows as Q9's fold) scores 47,117 holdout rows; max |score - Q9 score| = 5.98e-05; bit-identical (every holdout row the research data could label (label exit on or before the research end) is present in both and scores exactly the same): False. Not compared: 3 test rows whose label exits after the research end (CCAVENUE 2026-09-10, CCAVENUE 2026-09-11, CCAVENUE 2026-09-15).

Why not bit-identical: the same trainer on the research frame (`ml/data_10y`, the frame Q9 ran on) reproduces Q9's holdout scores exactly (47,117 rows, max |diff| 0.0), so the trainer is Q9's. The paper frame carries the live corporate-action feed's rescaling (consistency proof above): 1,949 training cells differ from the research frame (at most 6.1e-13, in 136 rows of 2 tickers; label cells differing 0); LightGBM's bin boundaries and split thresholds come from the training values, so the fitted trees differ slightly (the frozen trainer's 504-session reproduction happened to come out exact). Effect on the holdout: AUC 0.54009 on the paper frame vs 0.54009 for Q9; per-date Spearman correlation with Q9's scores min 0.99999998, mean 1.00000000; per-date top-decile overlap min 100.0%, mean 100.0% (32 dates).

Lost-state check (`ml/results/improve2/paper/lost_state_check_expanding.json`): extension 1: ml/paper/state/models/expanding/2026-10/ (lgbm.txt, preprocess.pkl) and ml/paper/state/scores_expanding/scores_2026-10-19.parquet deleted; then OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --no-ingest (no ingest, store and frame unchanged): the model was retrained in a child process and equals the committed metadata ({'reference_predictions': True, 'model_contents': True, 'training_frame_sha256_equal': True, 'training_rows_equal': True, 'training_window_equal': True}); regenerated score files ['2026-10-19']; every file byte-identical to before True (the retrained LightGBM text model and the pickled preprocessor are byte-identical to the deleted ones; the regenerated score file is byte-identical and its baskets equal the ledger's; the ledger, state.json and the committed metadata are unchanged).

Backfill proof (`ml/results/improve2/paper/extension_backfill.json`): the run appended {'signals': 607, 'marks': 4, 'monitors': 15} rows ({'signals': {'challenger_expanding': 457, 'capacity_expanding': 150}, 'marks': {'challenger_expanding': 2, 'capacity_expanding': 2}, 'monitors': {'extension': 15, 'frozen': 0}}) for signal dates ['2026-10-19', '2026-10-21', '2026-10-22'] and marked sessions ['2026-10-21', '2026-10-22']; only extension rows appended True; the existing rows {'signals': 1521, 'marks': 8, 'monitors': 48} are unchanged byte for byte True; ingest run False, frame rebuilt False.

| File | Bytes before | SHA-256 before | SHA-256 of the same bytes after | Unchanged |
|---|---:|---|---|---|
| signals | 97188 | `d673191e6e44e480` | `d673191e6e44e480` | True |
| marks | 858 | `d82156ed4411ac17` | `d82156ed4411ac17` | True |
| monitors | 7956 | `5258b13a813a9c4d` | `5258b13a813a9c4d` | True |

Overlap with the frozen books (names in both baskets on the signal date):

| Signal date | Book | Names | Shared with primary | Share | Shared with counterpart | Share |
|---|---|---:|---:|---:|---:|---:|
| 2026-10-19 | challenger_expanding | 152 | 87 of 152 | 57% | 87 of 152 (primary) | 57% |
| 2026-10-19 | capacity_expanding | 50 | 11 of 152 | 22% | 23 of 50 (capacity) | 46% |
| 2026-10-21 | challenger_expanding | 152 | 85 of 152 | 56% | 85 of 152 (primary) | 56% |
| 2026-10-21 | capacity_expanding | 50 | 15 of 152 | 30% | 23 of 50 (capacity) | 46% |
| 2026-10-22 | challenger_expanding | 153 | 76 of 153 | 50% | 76 of 153 (primary) | 50% |
| 2026-10-22 | capacity_expanding | 50 | 10 of 153 | 20% | 16 of 50 (capacity) | 32% |

Score agreement with the primary model (Spearman over the date's universe): 2026-10-19 raw 0.858, neutralised 0.817 (1523 names); 2026-10-21 raw 0.836, neutralised 0.780 (1524 names); 2026-10-22 raw 0.801, neutralised 0.751 (1527 names).

## Marks (fixed capital: 1/20 per tranche, idle capital at zero)

| Book | Sessions | Exposure (last) | Gross | Net 20 bps | Net name-level | Benchmark | Active net 20 bps |
|---|---:|---:|---:|---:|---:|---:|---:|
| primary | 2 (2026-10-21..2026-10-22) | 0.10 | -0.21% | -0.23% | -0.26% | -0.23% (ew_universe) | +0.00% |
| capacity | 2 (2026-10-21..2026-10-22) | 0.10 | -0.24% | -0.26% | -0.28% | -0.21% (ew_liquid) | -0.05% |
| challenger | 2 (2026-10-21..2026-10-22) | 0.10 | -0.18% | -0.20% | -0.23% | -0.23% (ew_universe) | +0.03% |
| control_plain | 2 (2026-10-21..2026-10-22) | 0.10 | -0.15% | -0.17% | -0.19% | -0.23% (ew_universe) | +0.05% |
| challenger_expanding | 2 (2026-10-21..2026-10-22) | 0.10 | -0.21% | -0.23% | -0.26% | -0.23% (ew_universe) | -0.00% |
| capacity_expanding | 2 (2026-10-21..2026-10-22) | 0.10 | -0.23% | -0.25% | -0.27% | -0.21% (ew_liquid) | -0.04% |

A few sessions of a ramping book say nothing about the strategy; these lines exist so that the record starts on the day it should.

## Monitors as of 2026-10-22

| Monitor | Scope | Value | Threshold | Status | Detail |
|---|---|---:|---:|---|---|
| delivery_resid_ic | pre-inception | 0.0823414 | 0.02 | ok | months 2026-07 +0.0407, 2026-08 +0.0823 (raw IC +0.0522, +0.0294) |
| live_model_auc | pre-inception | 0.519292 | 0.5 | warming up (needs every 2026-10 signal date's 20-session label; the month's last signal date's label exits 21 sessions after it) | research walk-forward: fold 2026-07 0.5474, holdout 2026-08-03..2026-09-16 0.5193 |
| rank_ic_nw_t_12m | pre-inception | 4.02305 | 2 | ok | 223 matured signal dates in the trailing 12 months (0 live), mean IC +0.0865; last matured date 2026-09-16 |
| logistic_sign_flips | 2026-09 -> 2026-10 | 0 | 0 | ok | top 5: log_turnover -0.1719 (prev -0.2024), cs_rank_turnover +0.1688 (prev +0.1867), macd_norm -0.1612 (prev -0.1872), dist_52w_high +0.1263 (prev +0.1314), amihud_20 -0.1244 (prev -0.1351) |
| feature_psi | trailing 20 sessions vs 2026-10 training window | 0.259106 | 0.25 | ALERT | highest: ret_126d 0.259, dist_sma_50 0.141, dist_sma_20 0.134, rsi_14 0.133, mom_20 0.129; features above 0.25: 1 |
| paper_active_ir_6m | primary |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) +0.0011%; benchmark ew_universe |
| paper_active_ir_6m | capacity |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) -0.0525%; benchmark ew_liquid |
| paper_active_ir_6m | challenger |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) +0.0288%; benchmark ew_universe |
| paper_active_ir_6m | control_plain |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) +0.0545%; benchmark ew_universe |
| feature_inversion | pre-inception | 0.634615 | 0.5 | ALERT | month 2026-08: 33 of 52 features against their training-window sign (gap_pct, range_pct, dist_sma_5, dist_sma_10, dist_sma_20, dist_sma_50, macd_norm, mom_5 ...) |
| ensemble_atr_corr | month 2026-10 to date | 0.0755509 | 0.2 | ok | 3 signal dates; per-date range +0.043..+0.093 |
| neutral_score_corr | primary | 0.0395689 | 0.05 | ok | atr_pct -0.0099, log_turnover +0.0396 |
| neutral_score_corr | challenger | 0.0397487 | 0.05 | ok | atr_pct +0.0104, log_turnover +0.0397 |
| universe_etf_count | signal date | 0 | 0 | ok | 1527 universe names |
| split_flag_rate | signal date | 0.00196464 | 0.01 | ok | 3 of 1527 universe names |
| data_quality | store | 0 | 0.05 | ok | continuity mismatches 0 of 2912; per-name prev_close breaks > 22%: 0; duplicate EQ/BE pairs 0; write verified True; unvalidated split/bonus on this date 0; price breaks 0; recorded closures to date ['2026-10-20'] |
| live_model_auc_expanding | pre-inception | 0.540147 | 0.5 | warming up (needs every 2026-10 signal date's 20-session label; the month's last signal date's label exits 21 sessions after it) | Q9 research walk-forward (expanding window): fold 2026-07 0.5659, holdout 2026-08-03..2026-09-16 0.5401 |
| rank_ic_nw_t_12m_expanding | pre-inception | 5.3592 | 2 | ok | 223 matured signal dates in the trailing 12 months (0 live), mean IC +0.1205; last matured date 2026-09-16; Q9 research walk-forward before inception |
| paper_active_ir_6m | challenger_expanding |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) -0.0026%; benchmark ew_universe |
| paper_active_ir_6m | capacity_expanding |  | 0 | warming up (needs 6 months of marks; 2 sessions in 1 month(s)) | IR not reported before 6 months; cumulative active net 20 bps (fixed capital) -0.0392%; benchmark ew_liquid |
| neutral_score_corr | challenger_expanding | 0.055575 | 0.05 | ALERT | atr_pct -0.0037, log_turnover +0.0556 |

Deflated Sharpe of the daily active net-20 bps series (N = 261, V[SR] = 0.00387): primary warming up (needs marks); capacity warming up (needs marks); challenger warming up (needs marks); control_plain warming up (needs marks).
Extension books (N = 270, the trial ledger at registration; V[SR] = 0.00387): challenger_expanding warming up (needs marks); capacity_expanding warming up (needs marks).

## Idempotency proof

A second run on the same data (ml/paper/job.py --prove-idempotency, run after the first full run on the same store; scoring frame rebuilt from the store in this run: False; ingest decisions None): ledger SHA-256 before and after identical True; rows appended 0; recomputed signals of 2026-10-22 equal the ledger True; recomputed marks equal the ledger True; recomputed extension signals of 2026-10-22 equal the ledger True (expanding scores max |diff| 0.0).

| File | SHA-256 before | SHA-256 after |
|---|---|---|
| signals | `9fb7aeb776dedd47` | `9fb7aeb776dedd47` |
| marks | `989c4c89ee8b3457` | `989c4c89ee8b3457` |
| monitors | `aa6653fc5b51a334` | `aa6653fc5b51a334` |
| state | `43f32fbc4937815f` | `43f32fbc4937815f` |

## Lost-state check

ml/paper/state/models/2026-10/ (the four model files) and ml/paper/state/scores/scores_2026-10-19.parquet deleted; then OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --no-ingest (repaired store, scoring frame rebuilt after the CCAVENUE repair): the October models were retrained and equal the committed metadata ({'reference_prediction_sha256': True, 'model_contents_sha256': True, 'training_window_and_rows': True, 'training_frame_sha256 (information only)': False}); regenerated score files ['2026-10-19'] byte-identical True; ledger and model metadata unchanged True. CatBoost .cbm bytes carry train_finish_time and a random model_guid; its identity is the SHA-256 of the model exported without model_info (content_sha256); predictions of the original and the retrained CatBoost on 83,754 rows (2026-08-03..2026-10-22) differ by 0.0.

Live corporate-action feed: ml/data_ext/corporate_actions_feed_live.csv deleted; ml.paper.ingest.regenerate_live_feed (the path a run takes when the feed is missing after the research end) rebuilt it from the store's EQ/BE rows and every PR bundle on disk; byte-identical to the original True, equal to the hash in state.json True (757 rows).

## Determinism proof (ledger regenerated from inception)

ml/paper/prove.py: the job (--no-ingest) run from an empty ledger in ml/paper/state/regen/ with the same store, scoring frame and month models (frozen and expanding-window); every write redirected to the sandbox; the rebuild covers the four frozen books and the two books of extension 1. Rows regenerated: {'signals': 1521, 'marks': 8, 'monitors': 48, 'signals_expanding': 607, 'marks_expanding': 4, 'monitors_expanding': 15} for signal dates ['2026-10-19', '2026-10-21', '2026-10-22']; ledger byte-identical to the committed files True; per-date score files identical True (extension score files identical True); committed ledger untouched True.

| File | Committed SHA-256 | Regenerated SHA-256 |
|---|---|---|
| signals | `9fb7aeb776dedd47` | `9fb7aeb776dedd47` |
| marks | `989c4c89ee8b3457` | `989c4c89ee8b3457` |
| monitors | `aa6653fc5b51a334` | `aa6653fc5b51a334` |
| state | `43f32fbc4937815f` | `43f32fbc4937815f` |

Frozen books without the extension: the same job with the extension switched off (ml/paper/state/regen_frozen/), compared with the committed ledger's frozen-book rows. The regenerated files equal the committed ledger's frozen-book rows byte for byte: True (signals True, marks True, monitors True, state True); and equal the ledger as it stood before the amendment: True. state.json without its `extension` key is the file the job writes with the extension off: True (equal to the pre-amendment state.json: True).

