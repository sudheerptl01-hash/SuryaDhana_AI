# Paper book: frozen specification, definitions and deviations (stream Q1)

Written on 2026-10-23, before the first run of `ml/paper/job.py` produced any number.
Binding sources: `ml/IMPROVEMENT_PLAN_2.md` (Q1), `ml/PROGRAM_REPORT.md` §10 and §13.7.
The machine-readable copy of everything below is `ml/paper/config.py` (`SPEC`, hashed into
`SPEC_HASH`); `ml/paper/ledger/state.json` carries that hash, so a change to the specification
is visible in the ledger. The paper book is N = 1 and adds no trial; Deflated Sharpe readings use
N = 261 and V[SR] = 0.00387 (`ml/results/improve/books/books.json`,
`dsr_common.var_sr_daily_across_66_books`). Section 5 (amendment 10, 2026-10-23 09:17:13 UTC) adds two books, the
expanding-window challenger and its liquid-tercile version, with their own machine-readable specification
(`config.SPEC_EXT`, hashed into `SPEC_EXT_HASH`); it changes nothing in sections 1-4 and leaves `SPEC_HASH` as it was.

## 1. What is frozen (unchanged from the plan)

| Item | Frozen value |
|---|---|
| Features | the 52 features of `ml/data_10y/manifest.json`, built with `ml.data.build_dataset` (ETF exclusion list, `universe_price_col="close_unadj"`, NaN indicators pinned to `ml/data_5y_v2/manifest.json`, store opened read-only) plus `ml.integrity.build_v2.extra_columns` (`deliv_value_share_20`, `amihud_20`, `exit_date`) |
| Universe | the point-in-time filter of `ml/data.py` (raw close ≥ ₹10, 20-session median turnover ≥ ₹1 crore), ETFs removed before every cross-sectional step |
| Primary model | LightGBM, `ml.scale5y.make_model("all51")`, raw preprocessing |
| Challenger | rank-average (per-date percentile ranks, equal weights) of LightGBM, LambdaRank and CatBoost with the exact parameters of `ml/improve/ab.py` |
| Retraining | one model set per calendar month, trained at the month's first session |
| Neutralisation | `ml.books.engine.neutralise(kind="vol+size")`: per-date OLS residual of the score's percentile rank on the ranks of `atr_pct` and `log_turnover`, re-ranked |
| Primary book | full-universe top decile of the neutralised LightGBM score |
| Capacity book | top decile of the liquid tercile (`cs_rank_turnover` ≥ 0.67) of the same neutralised score |
| Challenger book | full-universe top decile of the neutralised ensemble score |
| Reference book | plain (un-neutralised) LightGBM full-universe top decile |
| Tranches | 20 overlapping, equal weight; signal date t, entry at the open of t+1, exit at the open of t+21 |
| Benchmarks | equal-weight universe (primary, challenger, reference) and equal-weight liquid tercile (capacity), same tranche mechanics, no costs (see 2.12 for the capacity book) |
| Costs | 20 bps per side on the traded weight net of the tranche replaced; the phase-1 name-level model (`ml.books.engine.name_cost_fracs`: max(11 bps, Corwin-Schultz half-spread + 0.1 σ √(q/ADV20)), ₹100 crore book) |
| Inception | signal date 2026-10-19 (the first session after the research data, which end 2026-10-16) |
| Seed / threads | 108 / 2 |

## 2. Definitions this stream had to make precise (no pass mark is involved)

1. **"Trailing 504 sessions of rows whose label has exited before the session."** The model for
   month M is trained on `ml.scale5y_nested.window_rows` with the walk-forward fold definition of
   `ml/data.py`: `train_end` = the session 22 sessions before M's first session (the 22-session
   embargo of §10), the window = 504 sessions back from `train_end` (505 sessions inclusive: `window_rows`
   sets the first session 504 positions before `train_end`, the convention of the research walk-forward),
   labelled clean rows only, and the exit-date purge at M's first session (`exit_date >= test_start`
   removed). The training rows are read from the store as it stands at the training run; a corporate
   action added later rescales that ticker's earlier prices, which changes ratios only by floating-point
   rounding. The metadata's `training_frame_sha256` is therefore information about the run, not the
   model's identity: the lost-state check compares the model contents and the reference-prediction
   checksums (amendment 6). `spec.test_end` in the metadata is the month's last session in the frame at
   the training run (a record of the run date); it plays no part in training. This is
   exactly how the research walk-forward trained every monthly model, so the October 2026 model is
   the model the research harness would have trained for a fold "2026-10". Proof that the trainer
   is the research trainer: it is re-run on the research holdout fold and must reproduce the
   ten-year control's holdout scores (`ml/results/improve/ab/10y/preds/control__beat_mkt_20d.parquet`)
   on every holdout row the research data could label; test rows whose label exits after the research
   end (after the CCAVENUE repair: three CCAVENUE rows of 2026-09-10..15 whose 20-row label windows cross
   its suspension) are listed in `trainer_reproduction.json` and not compared.
2. **Daily marks.** A paper book is marked once a day after the close. Each of the 20 tranche
   slots holds its tranche from the entry open to the exit open: on the entry session the mark is
   open → close, on the following sessions close → close, on the exit session close → open, and on
   that same session the slot's capital rolls into the tranche entering at that open (open →
   close). A tranche's marks therefore compound to open(t+21)/open(t+1) − 1, the label's window,
   i.e. the same tranche total as the research engine (`ml.strategy_backtest`), whose daily series
   is open-to-open. Book return of a session = mean over the active slots; `exposure` = active
   slots / 20 (the engine's fixed 1/20 capital per tranche, ramping up over the first 20 sessions).
   Prices are the split/bonus-adjusted `equity_features` open and close; a name with no print on a
   session is carried at its last print (the engine's forward fill); a name with no print at its
   entry open enters at its next print (the engine's back-fill) and is cash until then.
3. **Universe of a live signal date.** The research books used rows with a clean label
   (`y_clean_20d`), a screen that looks at the next 21 sessions. A live book cannot; it holds every
   universe name of the signal date. Live tranches can therefore contain the circuit, suspension and
   corporate-action windows that the research screen removed. This is a known, unavoidable difference
   between the forward record and the backtest.
4. **Costs at inception.** The engine charges tranches without a predecessor the median steady-state
   turnover (a backtest device for the sample ends). A live book really buys its first 20 tranches
   in full: tranches 1-20 pay entry costs on 100% of their weight. Exits are netted against the
   tranche entering at the same open (traded weight = Σ max(w_old − w_new, 0)); entries against the
   tranche they replace (Σ max(w_new − w_old, 0)), as the engine does. The name-level model is
   evaluated on the price data up to the tranche's own signal date (entry) and up to the successor's
   signal date (exit).
5. **Capacity book neutralisation.** As in `ml/improve/ab_books.py`: the score is neutralised on
   the full universe of the date, then the liquid tercile's top decile is taken.
6. **Session calendar.** A candidate session is accepted only if its `sec_bhavdata_full` file
   parses, names the session in its own `DATE1` column, is not a fingerprint echo of the previous
   stored session (the duplicate-day guard of `nse_historical_ingest`), and the exchange's PR bundle
   for that date exists and carries that date in its `pd` member. A weekday whose files echo the
   previous session and whose PR bundle is absent is recorded as a closure in
   `ml/paper/calendar_live.json` (with the evidence) and never ingested. A date that is neither is
   held: nothing after it is ingested until it is resolved.
7. **Corporate actions.** The split/bonus/consolidation logic of `ml/integrity/corporate_actions.py`
   is run over every PR bundle on disk with the paper's parser extension (`ml.paper.ingest.ca_extension`,
   amendment 4): the CNSLDATN spelling of a face-value consolidation is read as a consolidation, and a
   split/bonus/consolidation record whose `EX_DT` is empty takes its record date as the ex-date (T+1
   settlement). Every event still has to pass the module's own validation (observed open(ex)/close(ex-1)
   ratio within ±15%, ex-date shift within ±3 sessions). The live window is: validated events the
   ten-year feed lacks whose ex-date is after 2026-10-16, or whose ex-date is on or before 2026-10-16 while
   the ticker's first print on or after the ex-date comes after 2026-10-16 (a suspension across the
   research end, validated at that first print). `ml/data_ext/corporate_actions_feed_live.csv` is the
   ten-year feed's bytes followed by one line per such event (ratio written exactly, `repr`), staged in
   `ml/paper/state/ca/` and put in place only after `build_features(con, ca_csv=<staged feed>)` has run.
   The ten-year feed is never edited; research-period events found only by the extension are reported in
   `ingest.json` and not applied, so `equity_features` through the research end keep the ten-year
   adjustments. Rights issues, demergers, schemes and capital reductions in the new window are
   reported as price breaks (alert), not adjusted. Per name, every new session's `prev_close` is checked
   against the ticker's stored previous close: a move beyond 22% must be explained by the live feed's
   events in between (within ±15%) or by a recorded unadjustable action, or the write fails verification
   and the job stops before scoring (amendment 5).
8. **ETFs.** `exclude_tickers` = `ml/data_ext/etf_list_10y.csv` ∪ every symbol of the `etf` members
   of the PR bundles fetched by this stream (written to `ml/data_ext/etf_list_live.csv`).
9. **Ledger format.** `marks.csv` carries one column beyond the brief's list,
   `net_return_name_level`, because the plan requires both cost readings. Numbers are written with
   12 significant digits; rows are appended in (date, book, rank) order and never rewritten.
10. **Monitors.** §10's alerts plus the two of §13.7, each with its pre-registered threshold. Ones that
    need matured labels or months of marks are reported as "warming up (needs ...)" until computable.
    Where the latest complete month predates inception, the reading is computed on the research
    record (the frame's matured labels, the ten-year walk-forward scores) and labelled
    `pre-inception`; live months replace it as their labels mature. PSI is computed on the trailing 20
    sessions of the universe against the current model's training window (10 training-quantile bins,
    0.5% floor per bin), since the plan fixes no window. The feature-inversion monitor takes each
    feature's usual sign from the current model's training window; when the tested month lies inside
    that window (the pre-inception reading of 2026-08 against the October window 2024-08-20..2026-08-31,
    and in live operation a month tested by a model trained after it) the month contributes about 1/24
    of the "usual" IC, which makes an inversion slightly less likely to show. The rule is frozen in
    `config.MONITORS` (hashed); this overlap is stated here rather than changed.
11. **State and determinism.** Models, fetched files, the scoring frame and per-date scores live in
    `ml/paper/state/` (gitignored); committed metadata (`ml/paper/models/<YYYY-MM>.json`) carries the
    training window, row counts, parameters, feature list, a SHA-256 of the training frame and of each
    model file, and a prediction checksum, so a retrain from a lost state can be verified. No wall-clock
    time is written to any committed file; a second run on the same data changes no ledger byte.
12. **Capacity book benchmark.** `ml/PROGRAM_REPORT.md` §10 words the paper-book alert as "active return
    vs equal-weight universe" and the plan names the equal-weight universe benchmark. For the capacity
    book the active return is read against the equal-weight liquid tercile, as the research engine does
    (`ml.strategy_backtest.Engine.bench_for` maps `liq_` baskets to `ew_liquid`) and as the ten-year figure
    it is compared with (+1.2%/yr, `ml/results/improve/ab/10y/books.json`
    `control|vol+size|liq_top_decile`, benchmark `ew_liquid`) is measured. The capacity book against the
    equal-weight universe is derivable from the ledger: the primary book's `benchmark_return` of the same
    session is that benchmark.

## 3. Deviations from the plan

Items 2-4 above are the nearest faithful live versions of rules that were written for a backtest (a
label-window path, a clean-label universe, a median cost at sample ends); they change no definition of the
books or of the models.

**The ledger was regenerated from inception once, on 2026-10-23** (amendment 4). The first ledger rows
(signal dates 2026-10-19, 2026-10-21, 2026-10-22; written on 2026-10-23, held only in work-in-progress
commits, never released) were built on a data error: CCAVENUE's 10:1 consolidation (record date
2026-10-13, trading suspended 13-16 October, first print 2026-10-19) was not adjusted, so its features on
all three signal dates carried a +840% one-day return and it entered every book. Because the error was
found before the record was released, the store was repaired and the ledger rebuilt from inception with
the same frozen construction and the same October models, instead of appending corrections; the
superseded rows, their hashes and the basket differences are kept in
`ml/results/improve2/paper/superseded_2026-10-23/`. From here on the ledger is append-only and corrections
are appended (RUNBOOK section 5).

## 4. Amendments (no frozen definition and no `SPEC_HASH` change; amendment 4 changed data and ledger rows, section 3)

Made on 2026-10-23 during the verification pass after the restart, after the ledger's first rows existed. Each was
checked against the recorded record before any run that could produce a result: the 2026-10-20 closure decision is
the same under the amended rule (confirmed by the 2026-10-21 session of the same run), and the ledger was regenerated
from inception with the amended code and compared byte for byte (`ml/results/improve2/paper/regeneration.json`).
`SPEC_HASH` is unchanged; it covers the construction, not the operating procedure.

1. **Closure confirmation (item 6).** A closure, whether an echo with no PR bundle or no file and no PR bundle, is
   recorded in `calendar_live.json` only when a later candidate of the same run is accepted as a session. Until
   then the date is `pending` and its fetched files are dropped from the disk cache. Reason: a recorded closure is
   permanent, and a late file (a run after midnight IST) or an echo served on the evening itself would otherwise drop
   a real session from the forward record.
2. **Unverified write stops the job.** When the latest store write in `ingest.json` failed verification, the job
   stops before scoring, on that run and every later one, until a verified write supersedes it or an operator
   records an acceptance (`--accept-unverified-write`). Before, the failure was recorded and alerted (the
   `data_quality` monitor), but the run went on to score.
3. **Missing live feed.** When `ml/data_ext/corporate_actions_feed_live.csv` is missing after the store has sessions
   past the research end, it is rebuilt by the same code path and checked against the hash in `state.json`. Before,
   the ten-year feed was copied in its place, which is right only before the first write.

Made on 2026-10-23 after an adversarial review, before the store repair and the ledger regeneration they caused
(these change data and ledger rows, which is why they are listed with their effect; `SPEC_HASH` is unchanged):

4. **Corporate-action parser extension and live window (item 7).** The review found CCAVENUE's consolidation
   unadjusted: the bc record reads `CNSLDATNRE1 TO RS10` with an empty `EX_DT` (record date 2026-10-13), which the
   module's RE_CONSOL does not read and its ex-date filter drops, and the stream's window kept only ex-dates after
   2026-10-16, while CCAVENUE's first post-ex print is 2026-10-19 (suspended 13-16 October). Fix: the extension and
   the widened window of item 7. Effect: one event added to the live feed (CCAVENUE, ex 2026-10-13, ratio 10.0,
   observed 9.81); `equity_features` rebuilt under the lock protocol (`ml/paper/ingest.py --rebuild-features`);
   the scoring frame rebuilt; the ledger regenerated from inception (section 3). The extension also finds three
   research-period consolidations the ten-year feed lacks (KAUSHALYA ex 2024-01-12 ratio 100, SHEKHAWATI ex
   2024-08-28 ratio 10, VERTOZ ex 2025-06-25 ratio 10): reported in `ingest.json`, not applied (the research data
   are outside this stream; raised with the program lead).
5. **Per-name price-break check (item 7).** The continuity scan flags a session only when more than 5% of names
   mismatch, so one unadjusted 10x `prev_close` break passed as ok. Now every write's verification checks each new
   session's names (|prev_close / stored previous close - 1| > 22%); an unexplained break fails verification. A
   failed write holds every later ingest and stops the job until a verified write re-checks its sessions (a
   re-ingest after restoring the backup, or `--rebuild-features`, which re-checks every session after the
   research end) or an operator accepts it (`--accept-unverified-write`). Before, a later day's verified write
   superseded a failed one even without re-checking it.
6. **Lost-state identity of a model (item 2.1).** A retrain from a lost state must reproduce the committed model
   contents and reference-prediction checksums; the training-frame SHA-256 is compared and reported but no longer
   decides, because it depends on the store at the run (the October hash was taken after the JSWDULUX rescale of
   2026-10-22, and the CCAVENUE repair changes it again at rounding level without changing the model). Tested after
   the repair (`ml/results/improve2/paper/lost_state_check.json`): the retrained October model files are
   byte-identical, CatBoost equal in content and predictions; only the training-frame hash differs.
7. **Live feed as bytes.** The live feed is the ten-year file's bytes plus appended lines (before, a pandas
   round trip rewrote 35 ratios to 16 significant digits: harmless under pandas' default parser, not under an
   exact one); a write asserts the prefix.
8. **Backup location.** The store backup goes to `PAPER_BACKUP_DIR` or `ml/paper/state/backup/` (gitignored), not a
   session's scratch folder; `ingest.json` records repository-relative paths. Free space required: the store's
   size plus max(2 GB, half the store).
9. **Monitor detail.** `paper_active_ir_6m` reports the cumulative active return from the first marked session (it
   printed `nan` for a single session); `data_quality` reports the per-name break count of its session.

## 5. Amendment 10: extension 1, the expanding-window challenger (registered 2026-10-23 09:17:13 UTC)

Registered on 2026-10-23 at 09:17:13 UTC (system clock, the moment `config.SPEC_EXT` was written), before the
expanding-window model was trained and before any ledger row of the two new books existed. This is a dated amendment
to the frozen specification. It adds two books; it changes no definition, no parameter and no row of the four
existing books.

**Unchanged byte for byte.** The primary book, the capacity book, the ensemble challenger and the plain reference
are unchanged: `config.SPEC` and `SPEC_HASH` (`327a8d3801b37d580ece4446a2d5d101e7cd0c1c8663ff266335285959ed8643`)
are as frozen, their scores, baskets, marks and monitors are computed by the same code paths with the same models, and
their per-date score files are not touched (the extension writes its own, `ml/paper/state/scores_expanding/`). Proofs:
the backfill run hashes the ledger files before it and the same bytes after it
(`ml/results/improve2/paper/extension_backfill.json`); `ml/paper/prove.py` rebuilds the six-book ledger from inception
and compares it byte for byte, and rebuilds it a second time with the extension switched off, whose files must equal the
committed ledger's rows of the four frozen books byte for byte, with the pre-amendment ledger as their prefix
(`ml/results/improve2/paper/regeneration.json`). `ledger/state.json` keeps the frozen books' fields as they were (counts
of the four frozen books' rows) and carries the extension's spec hash, models and score files under `extension`;
without that key it is the file the job writes with the extension off, which `prove.py` also checks. The book
benchmark tranches already hold every universe name of each
signal date, so the extension adds no column to the price and cost grids that the frozen books' marks are computed on.

**Why.** Plan 2 amendment A1 (Q9): the control with an expanding training window passed the primary AUC mark (delta
CV-mean AUC +0.0079, 95% CI [+0.0047, +0.0113], `ml/results/improve2/expanding/EXPANDING.md`). The plan says that a pass
"is evidence for a forward test, not a promotion", and no forward book ran the expanding window. The hypothesis was
formed after the CPCV reading was seen, so the forward record, not the backtest, is the test. The seed calibration of
amendment A2 (Q10) is still running and decides nothing here; the extension is a forward record either way.

**Definition (machine-readable: `config.SPEC_EXT`; hash `SPEC_EXT_HASH` =
`a8d20cae4d930197ecc3e07c1f3bc4ac13484ebd4b627b852c0c73258349764f`).**

| Item | Value |
|---|---|
| `challenger_expanding` | identical to the primary book (LightGBM `ml.scale5y.make_model("all51")`, the 52 features, raw preprocessing, per-date vol+size neutralisation on the full universe, full-universe top decile, 20 overlapping tranches, entry at the next open, 20-session hold, 20 bps and name-level costs, equal-weight universe benchmark) **except** the monthly model's training window |
| `capacity_expanding` | the liquid-tercile version (`cs_rank_turnover` >= 0.67, top decile of the same neutralised score, neutralised on the full universe), as the capacity book is to the primary; benchmark the equal-weight liquid tercile |
| Training window | every labelled clean row (`y_clean_20d`) from the first dataset row (2017-10-03) to `train_end` (22 sessions before the month's first session), exit-date purge at the month's first session (`exit_date >= test_start` removed), no 504-session cap: `ml.scale5y_nested.window_rows(train_sessions=0)`, exactly `ml/improve/ab.py` `q9_expanding` |
| Retraining | one model per calendar month, at the month's first session (the LightGBM member only; seed 108, two threads) |
| First signal date | 2026-10-19 (the frozen inception) |
| Backfill | signal dates 2026-10-19, 2026-10-21, 2026-10-22, all with the 2026-10 expanding-window model trained as of 2026-10-01 (train_end 2026-08-31, exit-date purge at 2026-10-01) |
| Deflated Sharpe | N = 270 (the trial ledger at registration, plan 2 section 4, A2), V[SR] = 0.00387; the frozen books keep N = 261 |
| Files | models `ml/paper/state/models/expanding/<YYYY-MM>/` (gitignored), committed metadata `ml/paper/models/expanding/<YYYY-MM>.json` (same fields as the frozen models', plus `variant`, `train_sessions` and `extension_spec_hash`); scores `ml/paper/state/scores_expanding/` |
| Research record | `ml/results/improve/ab/10y_p2/preds/q9_expanding__beat_mkt_20d.parquet` and `q9_expanding__beat_mkt_20d.json`, hashed into `SPEC_EXT`; a run stops when either differs |

**Backfill from inception, and why it is legitimate.** The three signal dates are after the research data (which end
2026-10-16), and the October model uses no data dated after its model date: rows dated up to 2026-08-31 whose label
exit date is before 2026-10-01, the same rows and rule the frozen October model was trained with, without the
504-session cap. Every choice in the definition was fixed by amendment A1 before Q9 ran. The frozen books' three
signal dates were themselves scored in one catch-up run on 2026-10-23; the extension's were scored later the same
day, when the frozen books' first two marked sessions (2026-10-21, 2026-10-22) were already in the ledger. No parameter
of the extension depends on those marks. The model is trained once per month on the frame as the store stands at the
run, as the frozen models are (section 2.1, amendment 6). Proof that the trainer is Q9's
(`ml/results/improve2/paper/trainer_reproduction_expanding.json`): on the research holdout fold and the research frame
(`ml/data_10y`) it reproduces Q9's holdout scores exactly (2,110,109 training rows, 47,117 holdout rows, max |diff| 0).
On the paper frame, whose training cells of two tickers carry the live corporate-action feed's rounding-level rescaling
(1,949 cells, at most 6.1e-13, no label), the same fit gives scores within 6e-05 of Q9's, the same holdout AUC to five
decimals and the same top decile on every holdout date. The frozen trainer's reproduction came out exact; this one is
exact on the research frame and equal for every book-relevant purpose on the paper frame.

**Ledger order (extends 2.9 for the new rows only).** The new books' rows go into the same three ledger files. The
frozen books' rows for dates up to 2026-10-22 come first (the ledger as it stood at the amendment, unchanged), then the
extension books' rows for those dates (the backfill block, appended once), then from 2026-10-23 on every date's rows in
(date, book, rank) order over the six books, frozen books first (`primary, capacity, challenger, control_plain,
challenger_expanding, capacity_expanding`). Marks follow the same blocks by session. Monitors: per session, the frozen
monitors' rows first, then the extension's. A regeneration from inception writes the same order
(`ml.paper.book.signal_key`, `mark_key`; `ml.paper.job.process_monitors`); a run refuses to append a row that sorts
before the ledger's last row.

**Monitors of the new books (`config.EXT_MONITORS`, thresholds as their frozen counterparts).**
`live_model_auc_expanding` (AUC of the month's expanding-window model on its month's matured signal dates, alert below
0.50; before a live month matures, the Q9 research walk-forward: fold 2026-07 and the holdout),
`rank_ic_nw_t_12m_expanding` (trailing 12-month per-date rank IC of the expanding score, Newey-West t with 20 lags, alert
below 2.0; Q9's walk-forward before inception), `paper_active_ir_6m` for `challenger_expanding` and
`capacity_expanding` (each book's own benchmark, alert when the 6-month month-block IR interval is entirely below zero),
and `neutral_score_corr` for `challenger_expanding` (the neutralised expanding score's per-date Spearman correlation with
`atr_pct` and `log_turnover`, alert above 0.05 in absolute value). The data monitors (delivery IC, PSI, feature
inversion, logistic sign flips, ETF count, split flags, data quality) watch the store and the frame, not a book; they
are shared and their rows are the frozen ones. PSI and inversion stay referenced to the primary model's 504-session
window: against a nine-year window every market-wide feature would read as drifted, and the question they answer (has
the market moved away from recent training data) is the same for both models.

**Operating cost.** The expanding-window model is trained on the first session of each month on about 2.2 million rows
(2,170,733 for 2026-10, growing by about 30,000 a month), in a child process that reads the whole frame; see
`ml/paper/RUNBOOK.md` section 8.

**What it is not.** Not a promotion and not a new trial: the books are the forward record of Q9's configuration, whose
books are already counted (N = 264, then 270). The frozen books remain the paper book of record; nothing in them is
re-tuned in response to the extension's record.

## 6. Amendment 11: the champion-challenger decision rule, and an erratum to amendment 10 (registered 2026-10-23 12:55:56 UTC, commit 3792bd9)

Registered when the extension's live record held two marked sessions (2026-10-21, 2026-10-22), before any live month
had matured, so no live comparison could inform it. It changes no book, no parameter, no definition, no ledger row and
neither `SPEC_HASH` nor `SPEC_EXT_HASH`; it fixes how the forward record will be read.

**Decision rule (owner: the program lead; management decides on the lead's report).** "Live month" means a calendar
month of signal dates whose 20-session marks have all matured.

| Read | When | What is computed | What it decides |
|---|---|---|---|
| Six months | first trading day after 2027-04-19 | paired monthly net (20 bps) excess `challenger_expanding` − `primary` and `capacity_expanding` − `capacity`, with month-block 95% intervals; per live month, the mean per-date rank IC (Spearman, universe names, raw score against the realised 20-session excess) of the expanding and the rolling LightGBM scores; every monitor row | nothing: descriptive only, no switch |
| Twelve months | first trading day after 2027-10-19 | the same, over twelve live months | the expanding window replaces the rolling window in the book of record (by a new pre-registered plan and a dated amendment, never by editing this specification) only if all three hold: (i) the mean paired monthly excess `challenger_expanding` − `primary` is above zero; (ii) the expanding score's monthly rank IC is above the rolling score's in at least 7 of the 12 live months; (iii) neither `challenger_expanding` nor `capacity_expanding` has a `paper_active_ir_6m` alert at the read. Otherwise both books run on. |
| Twenty-four months | first trading day after 2028-10-19, if the twelve-month read did not switch | the same, over twenty-four live months | switch only if the paired month-block 95% interval of `challenger_expanding` − `primary` lies above zero; if the mean paired excess is at or below zero, the expanding books are stopped as challengers (their rows stay in the ledger); otherwise both run on |

**Why these thresholds.** The seed-averaged backtest gain of the full-universe expanding book is +4.44 pp a year
[+2.90, +5.97] over 105 months (`ml/results/improve2/seeds/seeds.json`): at twelve live months its interval would be
about ±4.5 pp, so requiring it to exclude zero at twelve months would usually fail even if the gain is real. The
twelve-month rule therefore asks for agreement in sign on the book and a majority of months on the ranking, and the
interval test waits for twenty-four months. The capacity pair (`capacity_expanding` − `capacity`) is reported at every
read but decides nothing: at the backtest IR of about 0.8 its interval is uninformative for years. A switch changes the
paper book of record only; capital stays governed by Stage 2 of `ml/GOALS.md` and the five gates of `ml/SCALE_UP.md`.

**Erratum to amendment 10 (section 5).** "Every choice in the definition was fixed by amendment A1 before Q9 ran"
is not exact. Plan 2's amendment A1 was committed at 07:55:02 UTC, 20 s after the Q9 job started (07:54:42 UTC,
`ml/results/improve2/queue/queue_d.log`) and before its first fold result (about 07:56:28); plan 2 section 4, erratum
(i). The correct statement is: every choice in the definition was fixed by amendment A1 before Q9 produced any result.
The same sentence in `ml/paper/report.py` (`EXT_BACKFILL_NOTE`) is corrected with this amendment; `PAPER.md` and
`paper.json` carry the corrected sentence from the next run of the job.
