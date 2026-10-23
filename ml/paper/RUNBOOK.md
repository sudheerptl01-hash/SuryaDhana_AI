# Paper book: runbook

The paper book is the forward record of the frozen construction (`ml/paper/SPEC.md`). It holds no capital and
places no orders. Everything below is done by one command; this page says when to run it, what to check, and what
to do when something is off.

## 1. The daily run

**When.** On every NSE trading day after about 19:00 IST. The exchange publishes the day's
`sec_bhavdata_full` file and PR bundle in the evening; a run before that finds the day "pending" and does nothing
for it (on 2026-10-23 the day's file returned 404 on every attempt from 08:30 IST on, as expected). Running on a
weekend or holiday is harmless: there is no candidate session, or the holiday shows as `pending` until the next
session is published, when it is recorded as a closure (section 4); nothing is appended.

**Command** (from the repository root, shared 4-core box: two threads):

```
cd /home/user/SuryaDhana_AI && OMP_NUM_THREADS=2 python3 -I ml/paper/job.py
```

What it does, in order (each step is skipped when there is nothing new):

1. **Ingest** (`ml/paper/ingest.py`): candidate dates from `nse_historical_ingest.trading_days` (its holiday and
   special-session sets plus `ml/paper/calendar_live.json`); per date `fetch_day` through a polite client
   (browser user agent, 1-2 s between requests, 60 s back-off on 403/429/5xx, one request in flight), the file's own
   `DATE1`, the duplicate-day guard, and the PR bundle. Corporate actions from every PR bundle on disk (with the
   paper's parser extension, `SPEC.md` 2.7); new validated split/bonus/consolidation events of the live window are
   appended to the ten-year feed's bytes in a staged copy of `ml/data_ext/corporate_actions_feed_live.csv`. Then
   the write under the lock protocol: backup copy of the store in `ml/paper/state/backup/` (or `$PAPER_BACKUP_DIR`;
   free space checked: the store's size plus max(2 GB, half of it)), `ml/results/improve/LOCK_duckdb_write`, one
   transaction (`DuckDBStore.upsert`, rolled back on any duplicate EQ/BE pair), `build_features(con, ca_csv=<staged
   feed>)`, lock removed, the staged feed put in place, verification (row counts, duplicates, the continuity scan,
   the per-name `prev_close` breaks of the new sessions, fingerprints through 2026-10-16), backup deleted when
   verification passes.
2. **Frame** (`ml/paper/frame.py`): the ten-year dataset's code path on the updated store, rebuilt only when the
   store, the live feed or the ETF list changed.
3. **Signals**: for each new session, the month's models (trained at the month's first session if they do not exist
   yet, about 10-15 minutes, CatBoost dominating), scores, the four baskets, rows appended to `ledger/signals.csv`.
4. **Marks**: every book from the first entry open to the last session; new sessions appended to `ledger/marks.csv`;
   all earlier sessions are recomputed and compared with the ledger (never rewritten).
5. **Monitors** as of each new session, appended to `ledger/monitors.csv`.
6. `ledger/state.json`, `ml/results/improve2/paper/paper.json` and `PAPER.md`.

Typical duration: 6-10 minutes on an ordinary day (the 3.4 GB backup copy is about 110 s, the lock window about
100 s, the frame about 2 minutes), plus model training on the first session of a month (4-5 minutes for the four
members with two threads). Disk: the backup needs the store's size free (3.4 GB) plus headroom; check `df -h /`.

Memory: the ingest write (`build_features`) and the frame build (`ml.data.build_dataset` over 4.8 million rows) run in
child processes and peak at about 8 GB; the scoring, marks and monitors process stays near 1.6 GB. On the shared box
run the job when about 9 GB is free (`free -g`); an out-of-memory kill leaves nothing half-written that the next run
does not repair (the write is one transaction plus a rebuild the next run redoes if needed; ledger rows are appended
only after a step completes).

## 2. Checks after every run

Read the summary the job prints and `ml/results/improve2/paper/PAPER.md`.

| Check | Expected | If not |
|---|---|---|
| Ingest decisions | each new weekday is `session: ingest` or a recorded `closure`; today, or a holiday not yet followed by a published session, may be `pending` | `unresolved`: section 4 |
| Write | `verified: true`, lock file absent, backup deleted | the job stops before scoring; section 5 |
| Continuity on new sessions | share of mismatching `prev_close` well under 5% | over 5%: a session is missing or mis-dated, section 4 |
| Per-name `prev_close` breaks | every name whose `prev_close` is more than 22% away from its stored previous close is `explained_by_feed` (a split, bonus or consolidation in the live feed) | `unexplained`: verification fails and the job stops, section 5; `recorded_price_break` (rights, demerger, scheme, capital reduction): alert, recorded, not adjusted |
| Duplicate EQ/BE pairs | 0 | the transaction rolls back by itself; nothing was written |
| Basket sizes | about 10% of the universe for primary, challenger and control (about 150-160 names), about 10% of the liquid tercile for capacity (about 50) | a much smaller universe means a partial file: compare the day's EQ/BE row count with the previous session's |
| Exposure | rises by 0.05 per session until 1.00 on the 20th entry, then stays at 1.00 | a gap means a missed session, section 6 |
| Ledger diff | only added lines: `git diff ml/paper/ledger | grep '^-[^-]'` prints nothing except `state.json` changes | a removed or changed ledger line is a bug: restore the file from git and stop |
| Monitors | `ok`, `warming up (...)` or `ALERT` | `ALERT`: section 3 |

Then commit the ledger, the model metadata, the calendar and the results (the lead commits; the job never does):
`ml/paper/ledger/`, `ml/paper/models/*.json`, `ml/paper/calendar_live.json`, `ml/results/improve2/paper/*.json`,
`ml/results/improve2/paper/PAPER.md`.

## 3. Alert responses (thresholds fixed in `ml/paper/config.py`, from `ml/PROGRAM_REPORT.md` §10 and §13.7)

Nothing in the paper book is re-tuned in response to an alert. Alerts are recorded, reviewed, and written up; the
construction changes only through a new pre-registered plan.

| Monitor | Alert | Response |
|---|---|---|
| `delivery_resid_ic` | residual delivery IC below +0.02 in 2 consecutive complete months | note it in the monthly review; it is the signal's main pillar fading. Two more months below: raise it for the next plan. |
| `live_model_auc` | a live month's AUC below 0.50 | expected in about one month in six (the research record had 16% of months below 0.50). Three in a row: review for a regime change. |
| `rank_ic_nw_t_12m` | trailing 12-month Newey-West t below 2.0 | the signal is no longer distinguishable from noise at the program's bar; flag for review. |
| `logistic_sign_flips` | any of the top 5 logistic coefficients changes sign month to month | look at which feature flipped; a flip in a delivery or volatility feature is a regime signal. |
| `feature_psi` | any feature's PSI above 0.25 | check whether it is a market-wide move (e.g. `ret_1d`, `mom_5` on a sharp day) or a data change (a delivery or turnover column shifted for every name: check the day's files). |
| `paper_active_ir_6m` | trailing 6-month IR interval entirely below zero | the economics are failing out of sample; the program's own release criterion is not met. Report it. |
| `feature_inversion` | more than half the features against their usual sign in a month | an inversion month (2026-03 type); no action beyond the record. |
| `ensemble_atr_corr` | monthly mean of the raw ensemble score's correlation with `atr_pct` beyond ±0.20 | the volatility tilt is back; the neutral books are unaffected by design; record it. |
| `neutral_score_corr` | neutralised score's correlation with `atr_pct` or `log_turnover` beyond ±0.05 | the neutralisation is not doing its job on that date: check for NaN-heavy `atr_pct` or a tiny universe. |
| `universe_etf_count` | any ETF in the universe | an ETF missing from `etf_list_live.csv`: the next run adds every symbol of the bundles' etf files; if it persists, check the bundle's etf member. |
| `split_flag_rate` | more than 1% of the universe with `flag_split_20d` | an unadjusted split or bonus: check the corporate-action section of `ingest.json` for unvalidated events. |
| `data_quality` | duplicates, continuity above 5%, a per-name `prev_close` break that is unexplained or a recorded unadjustable action, an unvalidated split/bonus on the date, or an unverified write | section 4 or 5. |

## 4. Holiday echoes, mis-dated files and special sessions

* **Holiday echo (handled automatically).** On some closures the archive answers with the previous session's file
  (2026-10-20, Dussehra: `sec_bhavdata_full_20102026.csv` is byte-identical to 19-Oct's, its `DATE1` says
  19-Oct-2026, and the PR bundle `PR201026.zip` is absent). The job records such a date as a closure in
  `ml/paper/calendar_live.json` with the evidence and never ingests it.
* **A closure is recorded only once the archive has moved on.** A recorded closure joins the holiday set of every
  later run, so a mistake would silently drop a session from the forward record. The job therefore records a closure
  (an echo with no PR bundle, or no file and no PR bundle) only when a later weekday of the same run is accepted as a
  session; 2026-10-20 was confirmed by 2026-10-21. Until then the date is reported as
  `pending: ... recorded as a closure only once a later session is published`, and the files fetched for it are
  dropped from `ml/paper/state/raw/` so the next run fetches them again rather than re-reading a stale copy. This
  covers a run after midnight IST that finds a late file missing, and an echo served on the evening itself. If a
  session's file is so late that the next session is published first, that date is recorded as a closure; the next
  session's `prev_close` continuity check then flags it (over 5% of names), verification fails and the job stops
  (section 5): remove the wrong closure from `calendar_live.json`, restore the backup and re-run.
* **Unresolved date.** The evidence disagrees (for example the file names the right date but the PR bundle is
  missing, or the PR bundle exists but the file is an echo). The job ingests nothing from that date on. Check the
  exchange's holiday calendar and the files in `ml/paper/state/raw/`; if it is a closure, add it to
  `calendar_live.json` under `"closures"` with a short evidence note; if it is a session whose PR bundle is late,
  re-run later. Do not edit `nse_historical_ingest.NSE_TRADING_HOLIDAYS` for this.
* **Special sessions** (Muhurat on a weekend, Budget-day Saturdays). `trading_days` only proposes a weekend date
  when it is listed. Before the evening of such a session add it to `calendar_live.json` under
  `"special_sessions"` (date: description). The 2026 Muhurat session is expected on Sunday 2026-11-08 (Diwali);
  confirm the date and timing from the exchange's circular.
* **Weekday closures not in the ingest's list.** `nse_historical_ingest.NSE_TRADING_HOLIDAYS` has no closure between
  2026-10-02 and 2026-12-25 (it lacked Dussehra on 2026-10-20 too). The November 2026 closures, expected on
  2026-11-10 (Diwali Balipratipada) and 2026-11-24 (Guru Nanak Jayanti) (confirm from the exchange's holiday
  circular), are decided from the archive's evidence as above. Each shows as `pending` on its own evening and is
  recorded as a closure on the next session's run.
* **A file served under the wrong date** (seen in 2021-2024: a closure answered with the next session's file). The
  `DATE1` check rejects it; the PR bundle's `pd` member date is checked too.

## 5. Corporate actions and a failed write

* **Splits, bonuses, consolidations.** The bc member of each PR bundle announces them days ahead
  (`upcoming_adjustable_events` in `ingest.json`: AZADIND 1:5 split ex 2026-10-23 at inception). On the run of the
  first session on or after the ex-date the event is validated against the observed open/close ratio (±15%) and
  appended to the live feed; the ticker's earlier prices are rescaled, which leaves every return and every feature
  ratio unchanged up to floating-point rounding (the JSWDULUX split of 2026-10-22 changed 16 cells of 2026-10-16 by
  at most 3.4e-13). No ledger row changes.
* **Consolidations with a trading suspension** (CCAVENUE: "CNSLDATNRE1 TO RS10", no `EX_DT`, record date
  2026-10-13, suspended 13-16 October, first print 2026-10-19). The parser extension reads the CNSLDATN spelling and
  takes the record date as the ex-date; the event is validated at the first print after the suspension, also when
  the ex-date fell before the research end. If a consolidation, split or bonus is spelled in a way neither the
  module nor the extension reads, the per-name break check catches it (below).
* **A per-name `prev_close` break that nothing explains** (the exchange's `prev_close` more than 22% away from the
  stored previous close, and no live-feed event or recorded unadjustable action in between). Verification fails;
  the store keeps the session (the raw prints are the exchange's), the job stops before scoring and holds later
  sessions. `ingest.json` (`write.after.price_breaks.breaks`) lists the name, both prices, the stored previous date
  and the gap in calendar days. Read the day's announcements (`an` member of the PR bundle) and the bc records of
  the name. Then one of:
  * a corporate action the parser does not read: extend `ca_extension` in `ml/paper/ingest.py` (record it as an
    amendment in `SPEC.md` section 4), then `OMP_NUM_THREADS=2 python3 -I ml/paper/ingest.py --rebuild-features
    "<reason>"`: it re-derives the live feed, rebuilds `equity_features` under the lock protocol and re-checks every
    session after 2026-10-16; a verified repair resolves the failed write, and the next job run scores;
  * a relisting after a long suspension with a reset price, or another break with no adjustable action: accept it
    once with `OMP_NUM_THREADS=2 python3 -I ml/paper/job.py --accept-unverified-write "<reason>"`. On the 2026
    research sessions the rule would have fired 4 times in 196 sessions, all relistings after suspensions of
    6 months to 4.5 years (AHLWEST 2026-04-06, GAYAPROJ 2026-04-09, BFUTILITIE 2026-04-21, SUPREMEINF 2026-05-05).
* **An unvalidated split/bonus** (listed, but the observed ratio disagrees): alert. Inspect the purpose text and the
  prices. If the exchange moved the ex-date, the corporate-action logic finds it within ±3 sessions on a later run.
  Do not hand-edit the feed; if a tranche was marked across an unadjusted split, append a correction (below).
* **Rights, demergers, schemes, capital reductions** are price breaks, not adjustments; they appear in
  `price_breaks_in_window` and the affected marks stand as recorded.
* **Corrections** are appended, never substituted: a row in `ledger/monitors.csv` with `monitor = correction`, the
  affected session and book in `scope`, the corrected value in `value` and the reason in `detail` (use
  `ml.paper.common.append_rows` with `MONITORS_COLS`).
* **The write failed or verification failed.** The lock is removed in every case. If verification failed, the
  backup is kept (`ml/paper/state/backup/nse_market_backup_pre_q1_<date>.duckdb`, or under `$PAPER_BACKUP_DIR`),
  the job stops before it scores anything, and every later run holds new sessions and stops again until the failed
  write is resolved. `write.checks` in `ingest.json` names the failed check; `write.after` has the detail
  (continuity, per-name breaks, duplicates, row counts, fingerprints). A failed write is resolved by a later
  verified write that re-checks its sessions, or by an operator's acceptance; a later day's write alone does not
  resolve it. If the store is wrong, copy the backup back over `nse_market.duckdb` (nobody else writes it), fix the
  cause (e.g. a wrong closure in `calendar_live.json`) and re-run: the re-ingest makes a new, verified write of the
  same sessions. If only the adjustments are wrong, repair with `--rebuild-features` (above). If the store is right
  and the failed check is understood, record that once with `OMP_NUM_THREADS=2 python3 -I ml/paper/job.py
  --accept-unverified-write "<reason>"`; the reason is kept in `ingest.json` next to the write. A run killed between
  the upsert and `build_features` leaves `equity_features` behind `equity_eod`; the next run detects it and rebuilds
  the features under the lock. A lock file left by a killed process: check that no `python3` process holds the store
  (`fuser nse_market.duckdb`), then delete the lock.

## 6. Re-running safely

* The job is idempotent: running it again on the same data appends nothing and rewrites nothing
  (`--prove-idempotency` records the ledger hashes before and after in `ml/results/improve2/paper/idempotency.json`).
* The ledger is deterministic: `OMP_NUM_THREADS=2 python3 -I ml/paper/prove.py` regenerates it from inception in a
  sandbox (`ml/paper/state/regen/`) with the current code and compares it byte for byte with the committed files
  (`ml/results/improve2/paper/regeneration.json`). The committed ledger is not touched. Run it after any code change
  to `ml/paper/` and before committing that change: a difference means the code no longer reproduces the record.
* `--no-ingest` skips the network and the store write (useful when the archive is unreachable).
* `--force-frame` rebuilds the scoring frame even when the store did not change.
* **Lost state.** `ml/paper/state/` (models, raw files, frame, per-date scores) is not in git. A run without it
  re-fetches nothing that is already in the store, rebuilds the frame, retrains each needed month at its fixed
  window and checks the result against the committed `ml/paper/models/<YYYY-MM>.json`: the model contents and the
  reference-prediction checksums must match, and so must the training window and row count (CatBoost's `.cbm` bytes
  carry a fit timestamp and a random GUID, so its identity is the model exported without that block). The
  training-frame SHA-256 is compared and logged (`ml/paper/state/lost_state_retrains.jsonl`) but does not decide: it
  depends on the store at the training run, and a later corporate action on a training-window ticker changes it at
  rounding level without changing the model (`SPEC.md` 2.1). A mismatch stops the job instead of scoring with a
  different model. Missing per-date score files of ledger dates are regenerated and checked against the ledger's
  baskets. This path was tested on 2026-10-23 after the CCAVENUE repair
  (`ml/results/improve2/paper/lost_state_check.json`): the October model files came back byte-identical (CatBoost
  equal in content and in its predictions on 83,754 rows), the training-frame hash differed as expected, and the
  regenerated score file was byte-identical.
* **Local inputs outside git.** `ml/data_ext/` is gitignored, like the store: `corporate_actions_feed_live.csv`
  (the ten-year feed's bytes plus one line per validated event of the live window) and `etf_list_live.csv` exist
  only on this machine.
  `ingest.json` records each write's new events and the feed's SHA-256, and `state.json` records both files' hashes.
  If the live feed is missing, the next run rebuilds it from the store's EQ/BE rows and every PR bundle on disk, with
  the same code path, and checks it against `state.json`. A mismatch stops the job and removes the rebuilt file:
  the store's `equity_features` were built with the recorded feed, so recover that file (from a backup, or from the
  ten-year feed plus the events listed in `ingest.json`) before running again. A missing ETF list is rebuilt from
  the ten-year list and the PR bundles in `ml/paper/state/raw/pr/`.
* **A missed session** (the job was not run for a few days) is simply caught up: every new session is processed in
  date order. A signal date can never be inserted before the ledger's last one; if that is ever needed the
  ledger has to be rebuilt from inception, which is a decision for the program lead, not the job.

## 7. Running it as a scheduled cloud task (described, not created)

A scheduled task could run the daily job without a person at the keyboard. What it would need:

* **Schedule**: weekdays at 19:31 IST (`CRON_TZ=Asia/Kolkata 31 19 * * 1-5`), plus a second attempt at 21:31 IST for
  late files. Weekends and closures cost one or two archive requests and append nothing.
* **The store and the state**: `nse_market.duckdb` (3.4 GB) and `ml/paper/state/` are not in git; the
  backup copy before each write needs as much free disk again (`PAPER_BACKUP_DIR` can point it elsewhere on the
  same machine). The task must run
  where they persist (this machine, or a cloud environment with a persistent volume holding both). A fresh clone
  alone cannot run the job.
* **Network**: `archives.nseindia.com` reachable from the environment (it is from this sandbox through the proxy).
* **Steps**: `cd` to the repository, `OMP_NUM_THREADS=2 python3 -I ml/paper/job.py`, then commit
  `ml/paper/ledger/`, `ml/paper/models/*.json`, `ml/paper/calendar_live.json` and `ml/results/improve2/paper/` to the
  working branch and push; finish with a short message listing new sessions, basket sizes and every monitor row
  whose status is `ALERT` or an ingest decision that is `unresolved`.
* **Guard rails**: the task must not create or change any other schedule, must not edit `ml/paper/config.py` or the
  ledger by hand, must never pass `--accept-unverified-write` or run `ml/paper/ingest.py --rebuild-features` (both
  are a person's decision, section 5), and must stop (not retry in a loop) when the job exits non-zero; the exit
  message is the alert.
