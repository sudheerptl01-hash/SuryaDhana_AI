# Paper book: runbook

The paper book is the forward record of the frozen construction (`ml/paper/SPEC.md`). It holds no capital and
places no orders. Everything below is done by one command; this page says when to run it, what to check, and what
to do when something is off.

## 1. The daily run

**When.** On every NSE trading day after about 19:00 IST. The exchange publishes the day's
`sec_bhavdata_full` file and PR bundle in the evening; a run before that finds the day "pending" and does nothing
for it (on 2026-10-23 at 08:15 IST the day's file returned 404, as expected). Running on a weekend or holiday is
harmless: no candidate session, or a closure recorded, nothing appended.

**Command** (from the repository root, shared 4-core box: two threads):

```
cd /home/user/SuryaDhana_AI && OMP_NUM_THREADS=2 python3 -I ml/paper/job.py
```

What it does, in order (each step is skipped when there is nothing new):

1. **Ingest** (`ml/paper/ingest.py`): candidate dates from `nse_historical_ingest.trading_days` (its holiday and
   special-session sets plus `ml/paper/calendar_live.json`); per date `fetch_day` through a polite client
   (browser user agent, 1-2 s between requests, 60 s back-off on 403/429/5xx, one request in flight), the file's own
   `DATE1`, the duplicate-day guard, and the PR bundle. Corporate actions from every PR bundle on disk; new validated
   split/bonus events go to `ml/data_ext/corporate_actions_feed_live.csv`. Then the write under the lock protocol:
   backup copy of the store in the scratchpad (free space checked), `ml/results/improve/LOCK_duckdb_write`, one
   transaction (`DuckDBStore.upsert`, rolled back on any duplicate EQ/BE pair), `build_features(con,
   ca_csv=<live feed>)`, lock removed, verification, backup deleted when verification passes.
2. **Frame** (`ml/paper/frame.py`): the ten-year dataset's code path on the updated store, rebuilt only when the
   store, the live feed or the ETF list changed.
3. **Signals**: for each new session, the month's models (trained at the month's first session if they do not exist
   yet, about 10-15 minutes, CatBoost dominating), scores, the four baskets, rows appended to `ledger/signals.csv`.
4. **Marks**: every book from the first entry open to the last session; new sessions appended to `ledger/marks.csv`;
   all earlier sessions are recomputed and compared with the ledger (never rewritten).
5. **Monitors** as of each new session, appended to `ledger/monitors.csv`.
6. `ledger/state.json`, `ml/results/improve2/paper/paper.json` and `PAPER.md`.

Typical duration: 6-10 minutes on an ordinary day (the 2.8 GB backup copy is about 75 s, the lock window about 90 s,
the frame about 2 minutes), plus model training on the first session of a month (4-5 minutes for the four members
with two threads).

Memory: the ingest write (`build_features`) and the frame build (`ml.data.build_dataset` over 4.8 million rows) run in
child processes and peak at about 8 GB; the scoring, marks and monitors process stays near 1.6 GB. On the shared box
run the job when about 9 GB is free (`free -g`); an out-of-memory kill leaves nothing half-written that the next run
does not repair (the write is one transaction plus a rebuild the next run redoes if needed; ledger rows are appended
only after a step completes).

## 2. Checks after every run

Read the summary the job prints and `ml/results/improve2/paper/PAPER.md`.

| Check | Expected | If not |
|---|---|---|
| Ingest decisions | each new weekday is `session: ingest` or a recorded `closure`; today may be `pending` | `unresolved`: section 4 |
| Write | `verified: true`, lock file absent, backup deleted | section 5 |
| Continuity on new sessions | share of mismatching `prev_close` well under 5% (a few names on an ex-date are normal) | over 5%: a session is missing or mis-dated, section 4 |
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
| `data_quality` | duplicates, continuity above 5%, an unvalidated split/bonus on the date, or an unverified write | section 4 or 5. |

## 4. Holiday echoes, mis-dated files and special sessions

* **Holiday echo (handled automatically).** On some closures the archive answers with the previous session's file
  (2026-10-20, Dussehra: `sec_bhavdata_full_20102026.csv` is byte-identical to 19-Oct's, its `DATE1` says
  19-Oct-2026, and the PR bundle `PR201026.zip` is absent). The job records such a date as a closure in
  `ml/paper/calendar_live.json` with the evidence and never ingests it.
* **Unresolved date.** The evidence disagrees (for example the file names the right date but the PR bundle is
  missing, or the PR bundle exists but the file is an echo). The job ingests nothing from that date on. Check the
  exchange's holiday calendar and the files in `ml/paper/state/raw/`; if it is a closure, add it to
  `calendar_live.json` under `"closures"` with a short evidence note; if it is a session whose PR bundle is late,
  re-run later. Do not edit `nse_historical_ingest.NSE_TRADING_HOLIDAYS` for this.
* **Special sessions** (Muhurat on a weekend, Budget-day Saturdays). `trading_days` only proposes a weekend date
  when it is listed. Before the evening of such a session add it to `calendar_live.json` under
  `"special_sessions"` (date: description). The 2026 Muhurat session is expected on Sunday 2026-11-08; the
  exchange's calendar lists 2026-11-10 and 2026-11-24 as closures, which the job will find on its own.
* **A file served under the wrong date** (seen in 2021-2024: a closure answered with the next session's file). The
  `DATE1` check rejects it; the PR bundle's `pd` member date is checked too.

## 5. Corporate actions and a failed write

* **Splits, bonuses, consolidations.** The bc member of each PR bundle announces them days ahead
  (`upcoming_adjustable_events` in `ingest.json`: AZADIND 1:5 split ex 2026-10-23 at inception). On the ex-date's
  run the event is validated against the observed open/close ratio (±15%) and appended to the live feed; the
  ticker's earlier prices are rescaled, which leaves every return and every feature ratio unchanged up to floating-point
  rounding (the JSWDULUX split of 2026-10-22 changed 16 cells of 2026-10-16 by at most 3.4e-13). No ledger row
  changes.
* **An unvalidated split/bonus** (listed, but the observed ratio disagrees): alert. Inspect the purpose text and the
  prices. If the exchange moved the ex-date, the corporate-action logic finds it within ±3 sessions on a later run.
  Do not hand-edit the feed; if a tranche was marked across an unadjusted split, append a correction (below).
* **Rights, demergers, schemes, capital reductions** are price breaks, not adjustments; they appear in
  `price_breaks_in_window` and the affected marks stand as recorded.
* **Corrections** are appended, never substituted: a row in `ledger/monitors.csv` with `monitor = correction`, the
  affected session and book in `scope`, the corrected value in `value` and the reason in `detail` (use
  `ml.paper.common.append_rows` with `MONITORS_COLS`).
* **The write failed or verification failed.** The lock is removed in every case. If verification failed the
  backup is kept in the scratchpad (`.../scratchpad/q1/nse_market_backup_pre_q1_<date>.duckdb`): compare, and if the
  store is wrong copy the backup back over `nse_market.duckdb` (nobody else writes it) and re-run. A run killed between
  the upsert and `build_features` leaves `equity_features` behind `equity_eod`; the next run detects it and rebuilds
  the features under the lock. A lock file left by a killed process: check that no `python3` process holds the store
  (`fuser nse_market.duckdb`), then delete the lock.

## 6. Re-running safely

* The job is idempotent: running it again on the same data appends nothing and rewrites nothing
  (`--prove-idempotency` records the ledger hashes before and after in `ml/results/improve2/paper/idempotency.json`).
* `--no-ingest` skips the network and the store write (useful when the archive is unreachable).
* `--force-frame` rebuilds the scoring frame even when the store did not change.
* **Lost state.** `ml/paper/state/` (models, raw files, frame, per-date scores) is not in git. A run without it
  re-fetches nothing that is already in the store, rebuilds the frame, retrains each needed month at its fixed
  window and checks the result against the committed `ml/paper/models/<YYYY-MM>.json` (training-frame SHA-256,
  reference-prediction checksums and model contents; CatBoost's `.cbm` bytes carry a fit timestamp and a random GUID,
  so its identity is the model exported without that block); a mismatch stops the job instead of scoring with a
  different model. Missing per-date score files of ledger dates are regenerated and checked against the ledger's
  baskets. This path was tested on 2026-10-23 (`ml/results/improve2/paper/lost_state_check.json`): the October models
  came back equal on all three checks and the regenerated score file was byte-identical.
* **A missed session** (the job was not run for a few days) is simply caught up: every new session is processed in
  date order. A signal date can never be inserted before the ledger's last one; if that is ever needed the
  ledger has to be rebuilt from inception, which is a decision for the program lead, not the job.

## 7. Running it as a scheduled cloud task (described, not created)

A scheduled task could run the daily job without a person at the keyboard. What it would need:

* **Schedule**: weekdays at 19:31 IST (`CRON_TZ=Asia/Kolkata 31 19 * * 1-5`), plus a second attempt at 21:31 IST for
  late files. Weekends and closures cost one or two archive requests and append nothing.
* **The store and the state**: `nse_market.duckdb` (2.8 GB) and `ml/paper/state/` are not in git. The task must run
  where they persist (this machine, or a cloud environment with a persistent volume holding both). A fresh clone
  alone cannot run the job.
* **Network**: `archives.nseindia.com` reachable from the environment (it is from this sandbox through the proxy).
* **Steps**: `cd` to the repository, `OMP_NUM_THREADS=2 python3 -I ml/paper/job.py`, then commit
  `ml/paper/ledger/`, `ml/paper/models/*.json`, `ml/paper/calendar_live.json` and `ml/results/improve2/paper/` to the
  working branch and push; finish with a short message listing new sessions, basket sizes and every monitor row
  whose status is `ALERT` or an ingest decision that is `unresolved`.
* **Guard rails**: the task must not create or change any other schedule, must not edit `ml/paper/config.py` or the
  ledger by hand, and must stop (not retry in a loop) when the job exits non-zero; the exit message is the alert.
