# Paper book: frozen specification, definitions and deviations (stream Q1)

Written on 2026-10-23, before the first run of `ml/paper/job.py` produced any number.
Binding sources: `ml/IMPROVEMENT_PLAN_2.md` (Q1), `ml/PROGRAM_REPORT.md` §10 and §13.7.
The machine-readable copy of everything below is `ml/paper/config.py` (`SPEC`, hashed into
`SPEC_HASH`); `ml/paper/ledger/state.json` carries that hash, so a change to the specification
is visible in the ledger. The paper book is N = 1 and adds no trial; Deflated Sharpe readings use
N = 261 and V[SR] = 0.00387 (`ml/results/improve/books/books.json`,
`dsr_common.var_sr_daily_across_66_books`).

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
