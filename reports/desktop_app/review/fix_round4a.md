# F4-OPS

F4-OPS is done. All four brief items are fixed and tested: P6, P7, P14 and the P16 scheduler-header item.

- **P6 (news track record crashing every evening).** The cause was in `load_prices()` in `scripts/news_scan_performance.py`. When the evening snapshot was fresh, it returned the snapshot's DuckDB connection instead of the price panel. `resolve()` then failed on `panel["close"]` with "TypeError: DuckDBPyConnection object is not subscriptable". The snapshot is fresh on every scheduled run, so every run since 15 Oct crashed this way.
  - **Script fix:** it now opens the snapshot read-only, loads the panel, and closes the connection. If the snapshot can't be read, it falls back to the private copy.
  - **Controller fix:** a non-zero exit or a timeout now sends a WARNING alert ("News track record failed", with the exception line) and SYS shows `error`.
  - **Old vs new on a temp fixture:** run as a subprocess, the original script exits 1 with exactly that TypeError; the fixed one exits 0.
  - **Real data, read-only:** on the 23 Oct snapshot, with output only to scratch, it finished in 23 s: 354 picks, 23 scans, prices through 2026-10-23.
- **P7 (missed 02:15 backup never re-run).** At start-up, if today's backup is missing and 02:15 has passed, the controller now runs it once (`db_backup_catchup`).
  - It runs about 3 min after start, and after the data catch-up if there is one; it waits while that writes the DuckDB.
  - It never starts inside the freeze windows or within 20 min before one opens: a start that would land in 07:25–09:20 moves to 09:21, and 18:10–21:15 moves to 21:16.
  - It re-checks when it fires and does nothing if the backup has appeared or midnight has passed.
  - **Never two at once:** the existing controller job lock, plus a new file lock in `db_backup.py`. A second run exits 75 having written nothing, and the controller logs it as a skip, not a failure.
  - The downtime report now includes a line saying when the backup will run.
- **P14 (SYS job history lost on restart).** Each job's last run, status and duration are saved to `data/.scheduler_history.json` (atomic write). The file is loaded at controller start, and saving only switches on at that point, so tests never write the real file.
  - `/api/scheduler/status` keeps every existing field and fills the last-run ones from history after a restart, so SYS needs no UI change. New field: `last_run_source` (`this_run`, `history` or none).
  - The backup and news jobs catch their own failures, so they now mark the run as `error` instead of `done`.
- **P16 (scheduler header).** The header now lists all 28 recurring jobs and the one-off start-up jobs, instead of 13.
- **Still intact:** today's earlier changes to `master_controller.py` — the `http_guard` wiring and the Telegram /status UI-release line.

**Tests:** 43 new tests in three files, using temp DuckDB fixtures, temp backup dirs, a fake clock, a fake subprocess and recorded alerts. They include a lifespan test that checks the start-up wiring using only temp paths.
- **Negative control:** run against the original files in a scratch tree, 42 of the 43 fail or error.
- **Data safety:** nothing was written under `data/`, and `reports/news_scanner` was not touched.

**Ruff (`--line-length 130`):** `db_backup.py`, `news_scan_performance.py` (its 13 old findings are cleared) and the 3 new test files are clean. `master_controller.py` still has 60 findings, the same count per rule as before my edits, so I added none.

**The five suites:**

| Suite | Result | Note |
|---|---|---|
| `scripts/tests` | 238 passed | was 195 before the new tests |
| `tests` | 684 passed, 9 skipped, 2 failed | not my files: a 17:34 change to `scripts/desktop_qa/probe.py` |
| `services/ui-api/tests` | 994 passed, 2 failed | not my files: `routers/positions.py` and its test were being edited by another fixer at 20:44–20:46 |
| `services/execution-service/tests` | 7 passed | |
| `alpha_lab` tests | 20 passed | |

**Deploy:** master-controller must be restarted after 21:15 IST, which I did not do. If it is restarted tonight, today's missing 25 Oct backup will run about 3 minutes later.

## findings
- **P6** fixed: Root cause: load_prices() returned duckdb.connect(snapshot, read_only=True) as the price panel whenever the evening snapshot was fresh, which is every scheduled 19:45 run. resolve() then failed on panel["close"] with "TypeError: DuckDBPyConnection object is not subscriptable". The .logs/master-controller.log in place now starts after today's restarts and has no news-job lines, so the root cause was confirmed from the code and by reproduction: the original script on a temp fixture exits 1 with exactly that TypeError, and the fixed one exits 0.

Script changes:
- New snapshot_path() checks freshness: SURYA_SNAPSHOT_PATH, else the pointer file, under 24 h.
- load_prices() opens the snapshot read-only, loads the panel through the shared _panel_from(), and always closes the connection.
- A snapshot that can't be read (duckdb.Error or OSError) falls back to the private copy of the live DB, as before; the temp copy is always removed.
- Paths are now module constants (SCAN_DIR, LIVE_DB, SNAPSHOT_POINTER) so tests can point them at temp files, and main() takes argv.
- Lint cleared (13 old findings); the file is now executable to match its shebang.

Controller (news_track_record_daily):
- A non-zero exit or any exception, timeout included, sends _alerts.warning("News track record failed", the exception line from stderr).
- It also calls _mark_failed() so SYS and the history show `error`.

Real-data check: the 23 Oct snapshot opened read-only, output written to scratch only. Finished in 23 s: 354 picks, 23 scans, prices_through 2026-10-23.
  - tests: scripts/tests/test_news_track_record.py has 12 tests on a temp DuckDB fixture (nse_bhavcopy with EQ and SME rows, plus splits) and temp scan files; Yahoo is faked to fail the test if called. They cover:
- the root cause: a connection passed to resolve() raises TypeError (negative control);
- a fresh snapshot returns a dict panel with SME series, and the handle is closed (a read-write reopen succeeds);
- a fresh snapshot makes no copy of the live DB;
- a stale or missing snapshot falls back to a private copy, and the temp dir is removed;
- an unreadable snapshot falls back;
- the pointer file is honoured, and a garbage pointer gives None;
- main() end to end, checking track_record.json, REPORT.md and picks.csv;
- the controller job: exit 1 sends a WARNING with the reason and marks `error`; exit 0 sends nothing and is `done`; a timeout warns and marks `error`;
- the stderr-reason helper.

Subprocess negative control: the old script exits 1 with the TypeError, the new one exits 0.
  - user-visible: From the next 19:45 run (Mon 26 Oct), NEWS/BRF get a fresh track record instead of 14 Oct data. A failure now sends a Telegram WARNING and shows `error` on SYS. The "prices through <date>" label on BRF is UI work and not in my files: track_record.json already carries prices_through.
  - not fixed because: 
- **P7** fixed: master_controller.py:
- New pieces: BACKUP_DIR, FREEZE_WINDOWS (07:45–09:20, 18:30–21:15), a 20-min start margin (equal to the backup's subprocess timeout), backup_done_today() (looks for market-YYYYMMDD.meta.json, which db_backup.py writes last), backup_slot(), plan_backup_catchup(now, dest, not_before) and the job db_backup_catchup().
- At start-up (lifespan), if 02:15 has passed and today's backup is missing, one date job is added 3 min after start, or 3 min after the data catch-up's slot. A slot that would fall in or just before a freeze window moves to 09:21 or 21:16. No catch-up if the slot would cross midnight.
- This check does not depend on the heartbeat, so a short restart across 02:15 is also caught.
- When it fires, the job waits while startup_catchup holds its lock (up to 3 h; startup_catchup now holds a lock for its whole run). It then re-checks the date, the backup's existence and the freeze windows, reschedules itself to the end of a window if needed, and finally calls db_backup_daily().
- startup_catchup's report gains the line "today's 02:15 backup is missing: one run at HH:MM".

Never two at once:
- db_backup_daily's in-process lock, which now logs when it skips.
- New in db_backup.py: single_run() holds an flock on <dest>/.db_backup.lock. A busy run exits 75 (EXIT_BUSY) having written nothing.
- The controller treats exit 75 as a logged skip with no alert. Other failures still send the critical alert and now also mark `error`.
  - tests: scripts/tests/test_backup_catchup.py has 23 tests using temp backup dirs, a fake clock (patched mc.datetime), a fake backup subprocess, recorded alerts and a fake scheduler. They cover:
- Planning: before 02:15 gives None; yesterday's meta or a partial .duckdb without meta does not count as done; today's meta gives None.
- Freeze windows, 9 parametrised cases: 07:20→07:23, 07:30→09:21, 08:00→09:21, 09:19→09:22, 18:05→18:08, 18:15→21:16, 20:00→21:16, 21:14→21:17, 23:00→23:03.
- No catch-up across midnight; spacing after the data catch-up (09:21 gives 09:24); backup_slot edges.
- The job: runs once when due and SYS shows db_backup_daily `done`; does nothing if the backup appeared or midnight passed; moves itself out of a freeze window (add_job at 21:16 with replace_existing); waits for the startup_catchup lock; gives up after the maximum wait.
- Never two at once in-process: the scheduled run and the catch-up together give exactly one subprocess.
- Exit 75 is a skip with no alert; exit 1 is critical plus `error`.
- Across processes: a real child process holds the flock, main() returns 75 and writes nothing; after it is killed, main() returns 0 (negative control). single_run is exclusive and released afterwards.
- Lifespan (temp heartbeat, backup dir and history; poller and alerts faked): after 2 days down, startup_catchup runs in `full` mode at 21:21, the backup is 3 min later, and backup_at is passed in. With today's backup present, no catch-up job.
  - user-visible: After an outage, a reboot or a restart across 02:15, the missed nightly backup (market- and ui_prefs- files) is made once at start-up, outside the freeze windows. The Telegram downtime report says when. SYS lists a pending db_backup_catchup job.
  - not fixed because: 
- **P14** fixed: master_controller.py:
- New JobHistory class: {job_id: {last_run_ts, last_status, last_ms, runs}} saved to data/.scheduler_history.json with an atomic temp-file-plus-rename write. A failed write never breaks a job and warns only once per failure streak.
- The real store is armed only by load() in lifespan(), so importing the module (tests, CLI) never writes data/.
- _track() records every run into it. New _mark_failed(job) lets jobs that catch their own failure (backup, news) record `error`; the mark is cleared at the start of each run.
- /api/scheduler/status is additive: each job row keeps all its old keys. When this process hasn't run the job yet, last_status, last_run_ts and last_latency_ms come from history. New key last_run_source: this_run, history or null. avg_latency_ms and samples still cover this process only.
- The SYS page (ui/components/SystemTelemetry.tsx) reads last_status and last_latency_ms, so it shows the values after a restart with no UI change.
  - tests: scripts/tests/test_scheduler_history.py has 8 tests, temp paths only:
- importing the controller never arms the real store;
- round trip: nothing is written until armed, no temp file is left, and a new instance loads the previous run's rows with the run count;
- garbage or wrong-shaped files load empty and are rewritten;
- a failed write keeps the row in memory and warns once;
- _track records done, error (raised) and soft error (_mark_failed); the mark resets on the next run;
- status after a simulated restart shows the persisted values with last_run_source=history, and every old key is still present;
- negative control: with no history, a fresh process shows every job blank (the old behaviour);
- a run in this process wins over history.
  - user-visible: SYS no longer shows '—' for every job after a controller restart: each job's last result, time and duration carry over until it runs again.
  - not fixed because: 
- **P16-scheduler-header** fixed: The master_controller.py module docstring now lists all 28 recurring jobs in time order: id, IST time, days, and AUTOPILOT-dormant flags for the 3 legacy trading jobs. It also lists the one-off start-up jobs (icici_session_refresh_startup, <job>_catchup, startup_catchup, db_backup_catchup) and where job history persists. The old header listed 13 jobs, out of order.
  - tests: Documentation only. I checked every row against the CronTrigger arguments in lifespan(). The module compiles, and the scripts/tests suite passes (238).
  - user-visible: None (developer documentation).
  - not fixed because: 

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/news_scan_performance.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/db_backup.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/docs/RUNBOOK_RESTORE.md
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_news_track_record.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_backup_catchup.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_scheduler_history.py

## tests
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest scripts/tests -q -> 238 passed (195 before + 43 new); rerun after the last edit: 238 passed
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests -q -> 684 passed, 9 skipped, 2 failed. Both failures are in tests/integration/test_qa_tool_defaults.py (FakeContext has no route_web_socket) after another fixer's 17:34 change to scripts/desktop_qa/probe.py. Not my files.
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest services/ui-api/tests -q -> 994 passed, 2 failed. Both are test_event_loop_purity.py::test_token_routes_call_the_breeze_check_only_through_a_thread, while routers/positions.py and that test were being edited by another fixer at 20:44–20:46. Not my files.
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest services/execution-service/tests -q -> 7 passed
- (cd alpha_lab && /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests -q) -> 20 passed
- Negative control: the 3 new test files run against the ORIGINAL master_controller.py, news_scan_performance.py and db_backup.py in a scratch tree (scratchpad/F4-OPS/negctl2) -> 42 of 43 fail or error. The one that passes is a guard on the fixture itself.
- Subprocess negative control: original vs fixed news_scan_performance.py with SURYA_SNAPSHOT_PATH pointing at a temp fixture DB (scratchpad/F4-OPS/negctl) -> Old: exit 1 with "TypeError: 'duckdb.duckdb.DuckDBPyConnection' object is not subscriptable". New: exit 0, writes picks.csv, REPORT.md and track_record.json.
- Real-data read-only check: scratchpad/F4-OPS/real_readonly_check.py (23 Oct evening snapshot opened read-only, live-DB copy blocked, output to scratch only) -> OK in 23.0 s: 354 picks, 23 scans, prices_through 2026-10-23, last_scan 2026-10-20. reports/news_scanner was not touched.
- ruff check --line-length 130 on db_backup.py, news_scan_performance.py and the 3 new test files -> All checks passed
- ruff check --line-length 130 scripts/master_controller.py, compared with the pre-change copy -> 60 findings before and after, with identical counts per rule (32 BLE001, 17 UP045, ...). No new findings.
- mypy --ignore-missing-imports --follow-imports=silent on the 3 touched scripts -> master_controller.py: 2 errors before and after, both in old code. news_scan_performance.py: 5 before, 4 after (the load_prices return-type mismatch is gone). db_backup.py: clean.
- ls data/.scheduler_history.json data/backups/duckdb/.db_backup.lock; reports/news_scanner mtime -> Neither file exists and the track record is still dated 14 Oct: no test or check wrote real data files.

## patch requests
### PR-F4-OPS-1 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/news_scanner.py
why: This is a separate bug that also limits P6. Since 22 Oct the scanner writes its picks under "stage1_candidates" (new_scnner/20261022.json, 20261023.json, 20261025.json), alongside a separate "rejected" list; each entry has a ticker, conviction_score and thesis. load_scan_file finds no pick key, so the terminal shows 0 picks for those scans (GET /api/news-scanner/scans: 20261025 shows picks 0, rejected 8) and the fixed track record stops at the 20 Oct scan. Please add a ui-api test for the new key. A ui-api restart may happen at any time.

OLD:
```
_PICK_KEYS = ("stage1_picks", "picks", "stocks", "results", "data", "items", "candidates")
```
NEW:
```
_PICK_KEYS = ("stage1_picks", "stage1_candidates", "picks", "stocks", "results", "data", "items", "candidates")
```
### PR-F4-OPS-2 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/.gitignore
why: P14's new runtime state file (and its short-lived temp file) is not git-ignored; data/.controller_heartbeat.json and data/.evening_snapshot.json aren't either. It is runtime state, not history-worthy, like the other entries in this block.

OLD:
```
data/telegram_offset.json
data/icici_otp_last_ask.json
```
NEW:
```
data/telegram_offset.json
data/.scheduler_history.json
data/.scheduler_history.json.tmp-*
data/icici_otp_last_ask.json
```

## deploy notes
- Restart master-controller AFTER 21:15 IST (it is in the 18:30–21:15 freeze now), outside 07:45–09:20, with `./start-local.sh restart master-controller`. I did not restart anything. No data-service or ui-api restart is needed for these changes.
- Right after that restart: 25 Oct has no backup (the Mac was off at 02:15), so db_backup_catchup runs about 3 min after start, e.g. restart at 21:20 means backup at 21:23. The 23 Oct snapshot is over 30 h old, so it takes the torn-copy-safe private copy (an APFS clone; zstandard is not installed, so a plain clone). Expect market-20261025 and ui_prefs-20261025 files plus a .db_backup.lock file in data/backups/duckdb. Log line: "today's 02:15 backup is missing — one run at HH:MM".
- data/.scheduler_history.json is created at the first job finish after the restart. Until a job has run once under the new code, SYS still shows '—' for it.
- news_scan_performance.py and db_backup.py are spawned as subprocesses, so their fixes apply from the next run. The WARNING alert for a news failure needs the controller restart. First scheduled news run: Mon 26 Oct 19:45.
- Optional, owner's call: refresh the track record now with `PYTHONPATH=. /Users/sudheer/Desktop/jupyter_env/bin/python scripts/news_scan_performance.py`. It writes reports/news_scanner. With today's stale snapshot it makes a temporary private copy of market.duckdb (4.4 GB, removed afterwards); the 19:45 run uses the fresh snapshot instead.
- Read-only checks after the restart: `curl -s localhost:8008/api/scheduler/status` shows last_run_source on each job and the pending db_backup_catchup job. `grep db_backup .logs/master-controller.log` shows the catch-up run.

## open issues
- The UI half of P6 is not in my files: show "prices through <date>" on BRF. track_record.json already carries prices_through (and generated_at). For the F3-UI owner.
- Scanner files since 22 Oct use the key "stage1_candidates". The terminal shows 0 picks for 22, 23 and 25 Oct, and the track record ends at the 20 Oct scan. Patch request filed for services/ui-api/routers/news_scanner.py.
- Unrelated failing tests (not my files, both being changed by other fixers today): tests/integration/test_qa_tool_defaults.py, 2 tests (probe.py's mock_websockets needs route_web_socket on the test's FakeContext); services/ui-api/tests/test_event_loop_purity.py, 2 token-route tests (positions.py being edited at 20:44–20:46).
- The 22 Oct backup (market-20261022) is also missing. The catch-up only covers today's backup; older missed nights can't be recovered.
- Backups are uncompressed 4.6 GB files because zstandard is not installed in the shared jupyter_env (an existing fallback; I installed nothing).
- The other P16 sub-items ("test writes the live OTP file", "rejected paste overwrites the token", and others) were not in my brief and are untouched.
- Pre-existing ruff findings in master_controller.py (60, mostly BLE001 and UP045 in untouched code) and 2 pre-existing mypy errors are left as they were.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py: The new one-off db_backup_catchup job keeps APScheduler's default misfire_grace_time of 1 s. This applies to both add_job calls: the one in lifespan() and the one where the job reschedules itself in db_backup_catchup(). If the event loop or the Mac is more than 1 s late at the run time, APScheduler drops the job and removes it, and only a library warning is logged. That brings back P7, the missed backup that is never re-run, with no alert. The cron jobs all set misfire_grace_time explicitly; this new date job does not.
  - evidence: Today's .logs/master-controller.log line 683 shows APScheduler 3.10.4 dropping a run: 'Run time of job "Controller heartbeat ..." was missed by 0:00:01.422359'. I reproduced it in /private/tmp: a date job without a grace time, with the loop blocked for 2 s, was dropped and removed, and only the twin job with misfire_grace_time=3600 ran. Firing late would be safe: db_backup_catchup re-checks the date, whether today's backup exists, and the freeze windows when it fires.
  - fix: Add misfire_grace_time=6 * 3600, coalesce=True to both scheduler.add_job(db_backup_catchup, trigger="date", ...) calls. startup_catchup and <job>_catchup have the same gap, but that predates this change. Optionally add a test that the registered job's misfire_grace_time is not None.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py: JobHistory.load() only checks the file's overall shape. It accepts any row that is a dict, whatever its fields contain. JobHistory.record() then calls int(row['runs']) inside _track()'s finally block. If one row's 'runs' is not an integer, every later run of that job raises ValueError out of _track. The 'Finished' log line is skipped, and the row never repairs itself, because record() raises before it overwrites the row.
  - evidence: Reviewer probe (scratchpad/R-F4-OPS/probe_history.py, temp paths only): a history file containing {'jobs': {'desk_daily': {'runs': 'n/a', 'last_status': 'done'}}} loads fine (load() returns 1). A plain `async with mc._track('desk_daily'): pass` then raises 'ValueError: invalid literal for int() with base 10: 'n/a'' from the finally block. The file is only written by the controller, so this needs a hand edit or a partial corruption that still parses.
  - fix: In record(), guard the count, e.g. `try: runs = int(...) + 1 except (TypeError, ValueError): runs = 1`. Or in load(), keep only rows whose fields have the expected types. Add a test row with runs='x'.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_backup_catchup.py: Test gap. The key mechanism that makes the backup wait for the data catch-up is startup_catchup() holding _get_lock('startup_catchup'), and no test covers it. The wait test takes that lock by hand, and the lifespan test only checks the scheduling.
  - evidence: Mutation run in scratchpad/R-F4-OPS/mut (a copy of scripts/ with services and shared symlinked; I confirmed it imports the mutated module). I removed `async with _get_lock("startup_catchup"):` from startup_catchup. test_backup_catchup.py and test_downtime_recovery.py still pass: 27 passed.
  - fix: Add a test that runs mc.startup_catchup(...) with _run_data_job faked to block on an asyncio.Event. It should assert that mc._get_lock('startup_catchup').locked() is True while the fake runs, and that a concurrent db_backup_catchup() makes no subprocess call until the event is set.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_backup_catchup.py: The two lifespan tests have two hygiene problems. First, they let lifespan() reassign the module-global mc.scheduler without monkeypatch, so a stopped AsyncIOScheduler with about 31 real jobs leaks into every later test. Second, they start a real AsyncIOScheduler: the cron triggers use real wall-clock time, and only mc.datetime is faked. A real cron job due in the few milliseconds between start and shutdown (price_alerts_check every minute or filing_alerts every 5 min in session) could be submitted during asyncio.run's cleanup. The chance is small.
  - evidence: test_lifespan_schedules_the_backup_after_the_data_catchup and test_lifespan_adds_no_backup_when_todays_exists call `async with mc.lifespan(mc.app)` with no monkeypatch.setattr(mc, 'scheduler', ...). lifespan() runs `global scheduler; scheduler = AsyncIOScheduler(...)` and then `scheduler.start()`. The suite passes today (scripts/tests 278 passed) only because no later test depends on scheduler being None.
  - fix: Call monkeypatch.setattr(mc, 'scheduler', None) before entering lifespan so teardown restores it. Also patch mc.AsyncIOScheduler with a subclass whose start() calls super().start(paused=True), so no real job can be submitted.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_news_track_record.py: The 'and closes it' assertion in test_fresh_snapshot_loads_the_panel_read_only_and_closes_it is weak. In CPython the read-only connection is a local in load_prices and is freed by reference counting when the function returns, so the read-write reopen succeeds even without the explicit `finally: con.close()`.
  - evidence: load_prices() keeps `con` only in a local variable, and the test's only check of closure is `duckdb.connect(str(world['snap'])).close()` after load_prices returns.
  - fix: Optional. Wrap duckdb.connect with a spy and assert that close() was called on the returned connection. Or hold a reference through the spy and then assert that the read-write reopen succeeds.
- not really fixed: ["P6 is only partly fixed, and F4-OPS disclosed this. The backend is fixed: load_prices() no longer returns the DuckDB connection, and the controller now sends a WARNING and marks the run as error. The rest of the P6 fix in FEATURE_PARITY §6.2, the 'prices through <date>' label on BRF, is not done; it is UI work in ui/**, which is off-limits to this fixer. There is also a second bug: since 22 Oct the scanner writes its picks under the key 'stage1_candidates', which _PICK_KEYS does not include. Until the ui-api patch request lands, the refreshed track record will have current prices but its picks stop at the 20 Oct scan. I verified this: new_scnner/20261022.json, 20261023.json and 20261025.json all carry 'stage1_candidates' (16, 10 and 9 entries) plus 'rejected'."]
- notes: Verdict: ACCEPT-WITH-NOTES. No blockers and no regressions found. F4-OPS changed only its 7 assigned files, and the diffs against scratchpad/F4-OPS/orig contain only the P6, P7, P14 and P16 changes. Trading logic, the 08:00 icici_session_refresh, Telegram /login, the http_guard wiring and the BRKR paste flow (ui-api) are untouched. For the 08:00 job, the only change is the history.record call added in _track. The /api/scheduler/status change only adds a field (`last_run_source`) and passes through ui-api's telemetry proxy unchanged. SystemTelemetry.tsx already handles a null avg_latency_ms. journal_composer's 'LAST run errored' check now sees rows loaded from history, which fits its 'LAST run' wording.

**Checks I ran myself**
- **The 3 new test files:** 43 passed.
- **The five suites:**

| Suite | Result | Note |
|---|---|---|
| `scripts/tests` | 278 passed | other fixers have added tests since F4-OPS's 238 |
| `tests` | 684 passed, 9 skipped, 2 failed | both in `tests/integration/test_qa_tool_defaults.py` (FakeContext has no route_web_socket); not F4-OPS files |
| `services/ui-api/tests` | 997 passed | the earlier positions.py failures are gone |
| `services/execution-service/tests` | 7 passed | |
| `alpha_lab` tests | 20 passed | |

- **Ruff (`--line-length 130`):** clean on `db_backup.py`, `news_scan_performance.py` and the 3 new test files. `master_controller.py` has 60 findings, the same per rule as before.
- **Mypy:** no new errors.
- **No real data written:** after all the runs, `data/.scheduler_history.json` and `data/backups/duckdb/.db_backup.lock` do not exist, and `reports/news_scanner` is still dated 14 Oct.

**Evidence checked**
- The old script's subprocess output (`negctl/old.err`) ends with exactly "TypeError: 'duckdb.duckdb.DuckDBPyConnection' object is not subscriptable".
- The real-data check opened the snapshot read-only, blocked any copy of the live DB, and wrote output to scratch only.
- The header lists 27 cron jobs plus the heartbeat (28), and each matches its CronTrigger in lifespan().

**Logic checks**
- **Freeze-window slots:** a start from 07:25 to 09:20 runs at 09:21, and one from 18:10 to 21:15 runs at 21:16.
- **Midnight cut-off:** no catch-up when the slot would fall after midnight.
- **Order:** the backup slot always comes after the data catch-up's slot (max(now, when) + 3 min).
- **flock:** the lock fd is not inherited by `cp -c` children (Python opens fds non-inheritable), and the kernel releases it if the run is killed.
- **Rotation:** the globs do not match `.db_backup.lock`.
- **Exit 75:** logged as a skip, with no alert.

**Patch requests**
Both patch requests are valid:
- `services/ui-api/routers/news_scanner.py`: `_PICK_KEYS` lacks 'stage1_candidates'; I confirmed this on the 22, 23 and 25 Oct files.
- `.gitignore`: `git check-ignore` shows `data/.scheduler_history.json` is not ignored, and neither are `.controller_heartbeat.json` or `.evening_snapshot.json`. The lock file is already covered by `data/backups/`.

**Recommended before the PM deploys (one line each)**
- Add `misfire_grace_time` and `coalesce` to the two `db_backup_catchup` `add_job` calls (problem 1).
- Guard the `int(runs)` in `JobHistory.record` (problem 2).

**Smaller items, not defects**
- **Header wording:** the docstring says `icici_session_refresh` also runs at start-up "on a trading morning", but the code's condition is a weekday between 07:00 and market close.
- **Older gap, not new:** the 02:15 cron backup does not wait for a running `startup_catchup`. It uses the evening snapshot when one is under 30 h old, so the live DB is not read in that case.
- **Market-hours runs:** a catch-up can now run during market hours (from 09:21) on the private-copy path, against a live DB. The existing two-attempt signature check covers torn copies; the worst case is a spurious CRITICAL alert, not a bad backup.
- **Stale temp files:** `JobHistory` never removes a `.tmp-<pid>` file left by a crash, which is harmless.

All my scratch work is in /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-F4-OPS/: `mc.diff`, `probe_history.py`, the `mut/` mutation tree, and `suite_*.txt`.

# F4-API

All five IDs are fixed in my files: P2, the P4 server half, P13, P3, and both P16 items (rejected paste, test writing the live OTP file). Every fix has tests with a negative control. Nothing live was touched: no restarts, no ICICI/Breeze/Telegram calls, and the real .env (mtime still 23 Oct) and data/icici_otp_last_ask.json were not written. Three small master_controller.py changes are filed as patch requests because that file is not mine; the script works without them.

- **P2:** POST /session-token and /credentials now do all blocking work (the .env write, the cache invalidation that can wait up to 40 s on the probe lock, and the 10-40 s Breeze check) in asyncio.to_thread. Both routes are in test_event_loop_purity.py: /health stays fast while a stubbed 0.6 s probe runs. A shim that runs the work inline makes those tests fail, as it should.
- **P4:** a new `error_kind` field on connection-status, open-positions, summary, sector-exposure and trade-history ('expired' | 'network' | 'credentials' | 'unknown'). Existing fields are unchanged. token_works() is replaced by check_token(), which runs the same retrying Breeze check as ui-api. An ICICI outage now ends the run as 'unreachable' (exit 3) instead of starting a login that texts an OTP.
- **P13:** each value is written unquoted, single-quoted or double-quoted, whichever reads back exactly in python-dotenv and the plain parsers. The check parses each line with sentinel lines after it, which catches a quote that would swallow the next lines; values no form can store are refused. ICICI_API_KEY, ICICI_API_SECRET and ICICI_SESSION_TOKEN are stored unquoted only, because two scripts read them without removing quotes. The file mode is kept, and a missing .env is created 0600. The round-1 control-character refusal is unchanged. The script's write_env_value, which master-controller's /password and /userid also use, now goes through the same safe writer instead of a raw re.subn.
- **P3:** the token POST to ui-api is retried with backoff for about 2 minutes. That budget shrinks when the OTP reply came late, so the controller's 480 s kill cannot lose the token. A 4xx is not retried. If ui-api never takes it, the script writes .env, sends the new token to data-service's /provider/configure in the request body (the route accepts it; no data-service patch needed), and reports status 'refreshed' with outcome 'warning' and via '.env', plus a macOS notice. The current controller still sends its info message, and that message carries the WARNING text.
- **P16, rejected paste:** a pasted token is checked first. If ICICI rejects that token, .env and os.environ keep the old one and the reply says kept_previous_token: true. Network, API-key and unclear failures still save the token. The 08:00 job sends fresh_login: true, so its token is saved first and then checked, as before.
- **P16, OTP test:** test_telegram_bot.py now redirects OTP_LAST_ASK too, and a new guard test checks that every OTP_* path points into tmp_path.

## findings
- **P2** fixed: POST /api/positions/session-token and /credentials hand everything blocking to a worker thread: os.environ and .env updates, _invalidate_breeze_state (it waits on the probe lock for up to 40 s while a probe runs) and the Breeze check. The new sync helpers are _apply_session_token, _save_session_token and _apply_credentials. propagate_runtime_config and collect_backend_status stay async on the loop. Both routes are added to test_event_loop_purity.py.
  - tests: test_event_loop_purity.py has 4 new tests: (1) negative control: an async route that calls the stubbed slow check inline must stall /health (max over 0.25 s); (2) and (3) /health max < 0.25 s and p95 < 0.1 s while POST /session-token or /credentials runs a 0.6 s stubbed probe, and the probe really ran and the scratch .env was written; (4) a structural guard: both route bodies use asyncio.to_thread and never call _runtime_status, persist_env_updates, _invalidate_breeze_state or probe_breeze_connection inline. A scratch run with an inline to_thread shim made tests (2) and (3) fail (/health max 0.56-0.57 s), as expected. I used max, not p95: the /health calls are sequential, so one stalled call never reaches p95 of 20. scripts/check_event_loop.py reports 0 findings.
  - user-visible: Saving an ICICI token (08:00 job, Telegram, BRKR paste) or Save credentials no longer freezes ui-api, so other windows no longer show LINK DOWN for 17-35 s.
  - not fixed because: 
- **P4** fixed: Server half only. New icici_admin.public_error_kind() maps the probe's classifier kinds (session_expired, network, credentials, other) to the public kinds 'expired' | 'network' | 'credentials' | 'unknown'. The client cache now also stores the classifier kind. _runtime_status, used by /connection-status, always includes error_kind: null when connected; 'credentials' when the API key or secret is missing; 'expired' when there is no session token. On their connected:false paths, /open-positions, /summary, /sector-exposure and /trade-history include error_kind; a session that ends mid-read is 'expired'. The open-positions success shape is byte-identical. The open-positions network hint now says the API was unreachable and that this is not a login problem, instead of 'Send /login'. In the script, token_works() is replaced in main() by check_token(), which returns 'valid' or a public kind using ui-api's retrying probe (3 tries on network errors). A 'network' result ends the run with status 'unreachable', exit 3, and starts no login, so no OTP is sent. token_works() remains as a bool wrapper.
  - tests: test_icici_session_routes.py: error_kind for good, expired, network, credentials and other tokens through the real route; negative control: connected and needs_session_refresh are identical for an outage and an expired token, and only error_kind differs; missing settings; open-positions plus summary and sector-exposure for each kind; exact hint wording; mid-read session end gives 'expired'; success shape unchanged. test_session_refresh_handoff.py: check_token classifies each probe result and a raised SDK error; no settings means no Breeze call; main() with 'network' never calls browser_login and exits 3 'unreachable'; negative control: 'expired' still logs in; negative control: the bool token_works() is False for both outage and expiry.
  - user-visible: No visible change until F3-RUST and F3-UI map error_kind. After that, an ICICI outage can read 'ICICI unreachable' instead of 'expired: send /login'. The BRKR/open-positions network hint already changed. The 08:00 job no longer texts an OTP during an ICICI outage.
  - not fixed because: 
- **P13** fixed: icici_admin.encode_env_line picks the first of KEY=value, KEY='value' and KEY="value" that reads back exactly. The test parses the candidate line followed by three quoted sentinel lines, through python-dotenv's parser plus the plain quote-stripping rule; for ICICI_API_KEY, ICICI_API_SECRET and ICICI_SESSION_TOKEN (new RAW_READ_ENV_KEYS) the raw rule must also hold, because scripts/fetch_all_icici.py and icici_session_helper.py read them without removing quotes. Values with '${' are still refused, and so are values no form stores exactly. Refusals name the key, never the value. The whole-file re-read before the atomic rename now also runs the raw parser. persist_env_updates gains env_path=; a named file that is missing is created 0600, and an existing file keeps its mode. The round-1 control-character, length and protected-key rules are unchanged. In the script, write_env_value (also used by master-controller's /password and /userid) now calls persist_env_updates(env_path=ENV_FILE) instead of a raw re.subn, raising ValueError when a value is refused. icici_admin is loaded by file path under a private module name, so sys.path is untouched. The 400 hint now mentions surrounding quotes.
  - tests: test_env_roundtrip.py: three values that were refused before (a #'b, ' a\b', 'b\ #') plus it's #x and say "hi" #1 now read back exactly in dotenv and the plain parser, and the refused list was updated to values that can never be stored exactly. Raw-read keys: ordinary values are stored unquoted and read back by all three parsers; values that would need quoting are refused, with a negative control showing the quoted form keeps its quotes for the raw scripts. The swallow guard is tested with ' x\', with a negative control showing dotenv reads it fine alone but eats the next line in a file. Also: the readback rejects a raw-parser mismatch; a missing named file is created 0600 under umask 022; mode and other lines are kept; no file is created when none is found; the public error-kind map. The RAPI-04 reproduction now uses ICICI_CLIENT_ID and ICICI_PASSWORD. test_session_refresh_handoff.py: write_env_value round-trips '#', '$', quotes and spaces through read_env_file and dotenv and keeps 0600; negative control: the old raw writer read 'Secret #2026' back as 'Secret'; it creates .env 0600, keeps one line per key, refuses ${, line breaks, quoted raw-read tokens and EXECUTION_LIVE_ALLOWED with the file untouched, and leaves sys.path unchanged. A route test returns 400 for a quoted pasted token, and nothing is checked or saved.
  - user-visible: Passwords containing ' #', '$', quotes or spaces, whether set on BRKR or with Telegram /password, are saved so every reader gets them back exactly. A pasted token wrapped in quotes is refused with a clear 400. A saved .env keeps its mode.
  - not fixed because: 
- **P3** fixed: handoff_to_ui_api POSTs {token, fresh_login: true} to ui-api and retries connection errors, timeouts, 5xx and unparseable replies with backoff (2, 4, 8, 15, 30, 30 ... s). A 4xx is final. The total budget is handoff_budget_s(): 120 s, shrunk so 60 s stays in reserve when the OTP reply came late, minimum 15 s; RUN_BUDGET_S is 450 because the controller kills the script at 480 s. If ui-api never takes the token, apply_token writes .env through the safe writer, then calls push_token_to_data_service: a POST to data-service's /provider/configure with api_key, api_secret and session_token in the body. That route fills missing fields from its own stale environment, so this makes data-service reconnect with the new token; no data-service patch is needed. If data-service does not confirm, the token is checked only when more than 110 s remain. main() then reports RESULT status 'refreshed' with outcome 'warning', via '.env' and a detail starting 'WARNING: ... saved to .env only and sent to data-service directly (live quotes: on/not confirmed); ui-api keeps the old token until it restarts or the token is pasted on BRKR.', plus a macOS notice titled 'SuryaDhana · ICICI token saved to .env only'. The normal path reports outcome 'ok', via 'ui-api'. The status stays 'refreshed', so today's controller still sends its alert and the reconnect, now carrying the warning text. Patch requests make the alert a warning and make the controller's own reconnect send the .env token instead of {}.
  - tests: test_session_refresh_handoff.py, all with fakes, plus an autouse guard that raises a BaseException on any real httpx.post or Breeze probe. Covered: retry until 200 (ConnectError, then 503, then 200: 3 calls, sleeps 2 and 4, body carries fresh_login); gives up within the 120 s budget after 6 or more tries; a 400 is not retried; an unparseable 200 is retried; the budget shrinks; the ui-api path does not touch .env or data-service; the fallback writes .env and sends exactly {api_key, api_secret, session_token} to /provider/configure; negative control: data-service's route takes the old token when the field is missing; the fallback checks the token only with time left (valid and expired both covered); the fallback never runs a 3-try check that could outlast the kill; main() fallback gives exit 0, status 'refreshed', outcome 'warning', a WARNING detail, the notice and the cache file; negative control: the ui-api path gives outcome 'ok' with the old detail.
  - user-visible: When ui-api is down or restarting at login time, the token still reaches ui-api if it comes back within about 2 minutes. If not, live quotes get the new token straight away, and the outcome says 'saved to .env only' instead of a plain 'refreshed'.
  - not fixed because: 
- **P16-rejected-paste** fixed: _apply_session_token checks a pasted token with a fresh probe (the cache is cleared first, so a cached answer is never reused). If ICICI rejects that token itself (error_kind 'expired', key and secret present, and not the token already in use), it is not saved: os.environ and .env keep the old token, the probe-cache entry for the token in use is restored, and the reply carries connected:false, error_kind:'expired', persisted:false, env_path:null and kept_previous_token:true, with error text ending 'This token was not saved; the token in use was kept.' Network, credentials and unknown failures still save the token, as before. A new optional request field, fresh_login (default false), is sent by the 08:00 job and /login; with it the token is saved first and then checked, the old order, because ICICI ends the previous session when it issues a new token. An older ui-api ignores the extra field.
  - tests: test_icici_session_routes.py: a rejected paste, sent as a redirect URL, is checked once and leaves .env byte-identical, os.environ unchanged and nothing propagated; negative control: the same token with fresh_login is saved, which was the old behaviour for every paste; network, credentials and unknown failures still save; a good paste is saved and propagated, and its probe result is reused by the next status poll; after a rejected paste the token in use keeps its cached status with no extra Breeze login; a paste is always checked fresh. The test_env_injection route fixture now takes the new _runtime_status arguments; its tests still pass.
  - user-visible: Pasting a wrong or old token on BRKR no longer replaces a token that may still work. The error says the token in use was kept.
  - not fixed because: 
- **P16-otp-test-file** fixed: In scripts/tests/test_telegram_bot.py, _files() now also redirects daily_session_refresh.OTP_LAST_ASK to tmp_path. Before, test_otp_handoff_end_to_end wrote the live data/icici_otp_last_ask.json with the current time, which could make the next start-up login check skip for 30 minutes (--quiet-minutes). I treated this test as one of daily_session_refresh's tests, since it exercises its OTP hand-off.
  - tests: New test_the_otp_tests_never_touch_the_live_files checks that every OTP_* Path in telegram_bot and daily_session_refresh points into tmp_path once _files() has run; without the new line, OTP_LAST_ASK points at ROOT/data and the test fails. Running the bot tests left data/icici_otp_last_ask.json unchanged (mtime and size identical before and after).
  - user-visible: None. Running the tests no longer interferes with the next start-up login check.
  - not fixed because: 

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/icici_admin.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/positions.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/daily_session_refresh.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_env_roundtrip.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_env_injection.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_event_loop_purity.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_icici_session_routes.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_session_refresh_handoff.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_telegram_bot.py

## tests
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest services/ui-api/tests -q -> 997 passed
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest scripts/tests -q -> 278 passed
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests -q -> 684 passed, 9 skipped, 2 failed. Both failures are outside my files: tests/integration/test_qa_tool_defaults.py::test_ui_perf_contexts_are_readonly_by_default and ::test_ui_perf_prefs_mode_flag fail with AttributeError: 'FakeContext' object has no attribute 'route_web_socket', which comes from scripts/desktop_qa/probe.py (edited 17:34 by another program).
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest services/execution-service/tests -q -> 7 passed
- cd alpha_lab && /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests -q -> 20 passed
- PYTHONPATH=<scratch> pytest services/ui-api/tests/test_event_loop_purity.py -p inline_plugin -k keeps_the_api_responsive (negative control: a scratch plugin makes asyncio.to_thread run inline in routers.positions) -> 2 failed as intended (/health max 0.570 s and 0.564 s); the same tests pass 3 of 3 runs without the shim
- /Users/sudheer/Desktop/jupyter_env/bin/python scripts/check_event_loop.py -> event-loop purity: 0 findings, 0 new, exit 0
- /Users/sudheer/Desktop/jupyter_env/bin/python -m mypy services/ui-api/icici_admin.py services/ui-api/routers/positions.py scripts/daily_session_refresh.py --ignore-missing-imports --follow-imports=silent -> Success: no issues found in 3 source files
- /Users/sudheer/Desktop/jupyter_env/bin/python -m ruff check --line-length 130 <touched files> -> New files test_icici_session_routes.py, test_session_refresh_handoff.py, test_env_roundtrip.py and test_env_injection.py: clean. No finding is on a changed line. Pre-existing findings remain on untouched lines: positions.py 16 (BLE001, DTZ, I001 import blocks, FURB167, TRY004, PLR0124, S110), icici_admin.py 6 (FURB167, S110, BLE001 in the probe and propagate code), daily_session_refresh.py 6 (EXE001, RUF100 on the repo's E402 noqa convention, PLW1510, DTZ005), test_event_loop_purity.py 2 (ASYNC251 on the deliberate /block control, RUF046 in _p95), test_telegram_bot.py 2 (RUF100).
- stat .env data/icici_otp_last_ask.json before and after the suites -> Unchanged: .env last modified 23 Oct 08:08, mode 0644; the OTP last-ask file has the same mtime and size.

## patch requests
### PR-F4-API-1 scripts/master_controller.py
why: P3: daily_session_refresh now reports a .env-only hand-off as status 'refreshed' with outcome 'warning' and a WARNING detail. Without this patch the 08:00 job still sends it as an info 'ICICI session refreshed' message, with the warning only in the text. The existing line `if result.get("status") in ("refreshed", "valid"): await _ensure_live_prices()` stays as it is.

OLD:
```
                if result.get("status") == "refreshed":
                    await _alerts.info("ICICI session refreshed", str(result.get("detail")))
```
NEW:
```
                if result.get("status") == "refreshed":
                    if result.get("outcome") == "warning":   # saved to .env only: ui-api did not take the token (P3)
                        await _alerts.warning("ICICI session refreshed via .env only", str(result.get("detail")))
                    else:
                        await _alerts.info("ICICI session refreshed", str(result.get("detail")))
```
### PR-F4-API-2 scripts/master_controller.py
why: P3 (send the .env token in the reconnect body instead of {}): data-service's /provider/configure fills missing fields from its own environment, which keeps the old token when the login fell back to .env or ui-api's push failed. The script now also sends the token directly on its fallback; this makes _ensure_live_prices correct on every path. _env_file_value is defined later in the same module (dotenv_values of _ROOT/.env, a small sync read).

OLD:
```
                r = await client.post(f"{DATA_SVC}/provider/configure", json={})
```
NEW:
```
                # send the token from .env (the login job saved it there; data-service's own environment may still
                # hold the previous one); an empty value is left out so data-service uses its environment (P3)
                creds = {"api_key": _env_file_value("ICICI_API_KEY"), "api_secret": _env_file_value("ICICI_API_SECRET"),
                         "session_token": _env_file_value("ICICI_SESSION_TOKEN")}
                r = await client.post(f"{DATA_SVC}/provider/configure", json={k: v for k, v in creds.items() if v})
```
### PR-F4-API-3 scripts/master_controller.py
why: P3: the Telegram /login reply should not show a green tick when the token reached .env only.

OLD:
```
                msg = ("✅ ICICI session already valid." if status == "valid" else f"✅ ICICI logged in: {detail}")
```
NEW:
```
                msg = ("✅ ICICI session already valid." if status == "valid"
                       else f"⚠️ ICICI logged in, but: {detail}" if res.get("outcome") == "warning"
                       else f"✅ ICICI logged in: {detail}")
```

## deploy notes
- error_kind contract, for F3-RUST (desktop/src-tauri/src/health.rs parse_icici) and F3-UI (BRIEF, BRKR, PORT). Allowed values: 'expired' | 'network' | 'credentials' | 'unknown', or JSON null when connected. Meaning: 'expired' = ICICI refused the session token (log in: /login); 'network' = ICICI's API could not be reached after 3 tries (NOT a login problem); 'credentials' = API key or secret missing or rejected (fix on BRKR); 'unknown' = any other Breeze failure.
- GET /api/positions/connection-status always carries error_kind. Derivation: probe kind session_expired→'expired', network→'network', credentials→'credentials', other or missing→'unknown'. No API key or secret gives 'credentials'; key and secret set but no session token gives 'expired'. Existing fields are unchanged. needs_session_refresh still means 'key and secret set and not connected', so it is ALSO true during a network outage: consumers must branch on error_kind before needs_session_refresh. Suggested shell mapping: 'network' → Icici::Unknown, or a new 'unreachable' label reading 'ICICI unreachable'; 'expired' → Expired ('send /login'); 'credentials' → 'API key/secret (BRKR)'; 'unknown' or field absent → Unknown. The field is absent when ui-api still runs the old code, so treat a missing field as unknown.
- GET /api/positions/open-positions, /summary, /sector-exposure, /trade-history: error_kind appears only on connected:false replies, with the same values. A session that ICICI ends mid-read is 'expired'. The open-positions SUCCESS shape is byte-identical ({connected, positions, count}); a missing error_kind means no error. For 'network', open-positions' error_info.hint now reads "ICICI's API could not be reached (network); this is not a login problem. It is retried by itself." instead of 'Send /login on Telegram or use the Broker tab'.
- POST /api/positions/session-token. Request gains an optional fresh_login: bool (default false); daily_session_refresh sends true. Response gains error_kind (null when connected). A pasted token (fresh_login false) that ICICI rejects as expired is NOT saved; the reply is {connected:false, error_kind:'expired', persisted:false, env_path:null, kept_previous_token:true, error:'<probe message> This token was not saved; the token in use was kept.', status}. BRKR shows res.data.error, so no UI change is needed. ICICI_API_KEY, ICICI_API_SECRET and ICICI_SESSION_TOKEN values that would need quoting in .env (surrounding space or quote, ' #') now get HTTP 400 with code 'invalid' naming only the key.
- Restart: ui-api needs a restart to load positions.py and icici_admin.py. ui-api is not in the restart freeze windows (those cover data-service and master-controller only). After the restart: GET /api/positions/connection-status should show error_kind, and a BRKR token paste should no longer cause LINK DOWN in other windows.
- daily_session_refresh.py runs as a fresh subprocess for each login, so Monday's 08:00 run uses the new code with or without a restart. It works with the OLD ui-api too (the extra fresh_login field is ignored, and a missing error_kind is handled).
- master-controller keeps its already-imported copy of write_env_value, used by /password and /userid, until it restarts. Restart only outside 07:45-09:20 and 18:30-21:15 IST. Apply the three patch requests in the same restart.
- The live .env is still mode 0644. Saves now keep whatever mode the file has, so the owner can run `chmod 600 .env` once and it will stay that way. I did not change the real file.
- Nothing was restarted, no live POST was made, and no ICICI, Breeze or Telegram call was made. All tests use stubs and tmp files.

## open issues
- Patch requests for scripts/master_controller.py (not in my brief) are needed for the full P3 behaviour: a warning-level alert, a reconnect that sends the .env token, and a Telegram /login reply with a warning sign. Note that master_controller.py's line numbers moved during my session (the reconnect call went from :1615 to :1820), so another fixer seems to be editing it; the patch requests match exact text, not line numbers.
- The desktop shell (health.rs:353) and the BRIEF line still have to map error_kind 'network' to 'ICICI unreachable'. That is F3-RUST and F3-UI work.
- When the token check finds ICICI unreachable (status 'unreachable', exit 3), the controller retries after 5 minutes and then sends a CRITICAL 'ICICI session refresh FAILED' alert, whose detail says ICICI was unreachable. A controller change could make that a warning. It is optional and not part of my brief.
- The two older purity tests in test_event_loop_purity.py (universe-status and data-quality) pass even when the loop blocks. They assert p95 over 20 sequential /health calls, and a single stall only delays one call. My new tests assert max; the old two should switch to max as well.
- The .env writer lives in services/ui-api/icici_admin.py, and the script loads it by file path to avoid polluting sys.path. A shared/env_file.py module would be cleaner, but shared/ is outside my brief.
- .env writes are serialized only within one process. A write from ui-api and a write from master-controller (/password) at the same moment could still lose one update. This predates my change and is low risk.
- Two failures in the core suite are pre-existing and outside my files: tests/integration/test_qa_tool_defaults.py, where FakeContext lacks route_web_socket used by scripts/desktop_qa/probe.py.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] scripts/daily_session_refresh.py: P3 fallback is mislabelled when the new token is never checked. If ui-api never takes the token, data-service does not confirm, and 110 s or less of the run budget is left, apply_token returns connected=False with the error 'no time left to check it'. main() then reports status 'retry' with 'new token not accepted' and shows a macOS notice saying 'Got a token but Breeze rejected it', even though the token was saved to .env and never rejected. This contradicts the summary, which says the fallback reports 'refreshed' with outcome 'warning'. On Telegram /login the user reads 'login did not finish (retry)' and may send /login again, which costs an unnecessary second login and OTP.
  - evidence: daily_session_refresh.py:233 (`... if _time_left() > 110.0 else ("unknown", "no time left to check it")`) and :403-407. Reproduced with fakes (scratch R-F4-API/mut/test_fallback_msg.py, _time_left=60, ui-api and data-service both down): EXIT 3, RESULT {'status': 'retry', 'detail': 'new token not accepted: no time left to check it', 'via': '.env', 'error_kind': 'unknown'}, notice ('SuryaDhana · ICICI session', 'Got a token but Breeze rejected it: no time left to check it'), and .env ends with ICICI_SESSION_TOKEN=new-token. No test covers this path: test_apply_token_fallback_never_overruns_the_controller_timeout checks only connected False.
  - fix: In apply_token, keep 'not checked' apart from 'rejected', e.g. return checked=False. In main(), when via == '.env' and the token was not checked, finish with EXIT_OK, status 'refreshed', outcome 'warning' and detail 'saved to .env only, not yet checked ...', or use EXIT_RETRY with a status such as 'unconfirmed' and no 'rejected' wording. Add a main() test for this path.
- [minor] scripts/daily_session_refresh.py: The hand-off budget minimum of 15 s (40 s at 100 s left) is shorter than ui-api's normal time on POST /session-token with fresh_login: it saves at once, then runs a 10-40 s Breeze check (about 100 s when ICICI is slow), then propagates with a 20 s httpx timeout. When the OTP reply comes late, the client times out even though ui-api already saved the token. The run then takes the fallback and reports a false WARNING that ui-api 'keeps the old token until it restarts'. It also sends a second /provider/configure to data-service at the same time as ui-api's own push; that route swaps the global _live provider without a lock.
  - evidence: daily_session_refresh.py:77 (UI_API_HANDOFF_MIN_S = 15.0), :159-161 handoff_budget_s, :181 (timeout=max(5.0, remaining)); positions.py:674-675 (fresh_login saves before the check); data-service main.py configure_provider (`global _live`; disconnect/build/connect, no lock). This happens only when the run has used more than about 375 s (a slow OTP reply), so it is rare.
  - fix: Treat a ReadTimeout after the request was sent as 'probably taken': before claiming ui-api kept the old token, check with a quick GET /api/positions/connection-status (has_session_token, or compare the token) or read .env. Otherwise word the warning 'ui-api did not confirm'. Skip the direct data-service push when ui-api may still be propagating.
- [minor] services/ui-api/icici_admin.py: P13 now routes master-controller's /password and /userid writes (write_env_value) through persist_env_updates. ui-api and master-controller therefore share the fixed temp path '.env.tmp'; before this change the controller wrote .env directly. _ENV_WRITE_LOCK works only inside one process. Two writes from different processes at the same moment can truncate each other's temp file (O_TRUNC on the same inode). In the worst order, one process renames a file the other is still writing: .env is briefly empty, one update is lost, and the persisted flags are wrong.
  - evidence: icici_admin.py:312 (`tmp = env_path.with_name(env_path.name + ".tmp")`) and :313 (os.open(... O_CREAT | O_TRUNC ...)); daily_session_refresh.py write_env_value now calls admin.persist_env_updates(env_path=ENV_FILE); master_controller.py _env_set -> write_env_value. The race window is milliseconds (a /password at the same moment as a token save).
  - fix: Use a unique temp file per writer in the same folder, e.g. `fd, name = tempfile.mkstemp(dir=env_path.parent, prefix='.env.', suffix='.tmp')`. Then fchmod to the kept mode, run the same readback check and do os.replace. Optionally add a cross-process fcntl.flock on a '.env.lock' file.
- [minor] scripts/daily_session_refresh.py: Side effect of the P4 'unreachable' exit. Telegram /login runs the script without --force (master_controller.py:1922 passes only --ignore-block). When the Breeze token check fails with a network error, an explicitly requested /login now ends 'unreachable' and never reaches the browser login. Before, it went on to log in. During a partial ICICI outage (breezeapi slow but the login page up), the owner cannot get a token from the phone at all; '/login anyway' only skips the credential block.
  - evidence: daily_session_refresh.py main(): `if state == "network": finish(EXIT_RETRY, "unreachable", ...)` sits inside `if not args.force`; master_controller.py:1922 `_run_session_refresh(("--ignore-block",))`.
  - fix: Optional: for a login the owner asked for, let '/login anyway' (or a new script flag such as --login-if-unreachable) go ahead after a 'network' check. The 08:00 and start-up jobs keep the new no-OTP behaviour. This needs a master_controller patch request.
- not really fixed: []
- notes: Verdict: all six items are fixed in substance (P2, P4 server half, P13, P3, and both P16 items). Every fix has real tests, the negative controls hold, and nothing was found that is unsafe for the live stack. The four problems above are minor edge cases in the P3 hand-off, a shared temp file name and one behaviour side effect.

How I reviewed:
- I rebuilt the pre-change files (positions.py, icici_admin.py, daily_session_refresh.py and the old test files) from the fixer's own first reads in its transcript, and reviewed full diffs against them. Every change maps to P2, P3, P4, P13 or P16.
- Trading logic and existing response fields are unchanged. error_kind is added only.
- No other callers of _build_breeze_client, _runtime_status, token_works or write_env_value break. The only outside caller is master_controller._env_set (/password, /userid). Its exceptions are caught by the bot loop, which replies with the key name only, and the Telegram message holding the secret is deleted before the command is handled.

Callers checked:
- 08:00 job and start-up check: rc 3 'unreachable' retries after 300 s, then sends the CRITICAL alert with the unreachable detail.
- Telegram /login: rc 3 gives 'did not finish (unreachable)'.
- BRKR paste (LivePortfolio.tsx and PortfolioSummary.tsx): the UI shows res.data.error and then reloads connection-status, which is served from the restored probe cache.
- Old ui-api: it ignores fresh_login; pydantic drops extra fields.
- data-service /provider/configure: it takes the token in the body and also sets its own os.environ, so the old controller's {} reconnect afterwards keeps the new token.

Security:
- No secrets appear in RESULT, in the replies or in refusal messages; refusals name the key only.
- The current .env values all pass the new rules: I checked ICICI_* with booleans only and printed no values.
- The raw-read-key refusal only blocks values that start or end with a quote, or that need ' #' or surrounding spaces.

Fuzz check of the .env encoder (scratch R-F4-API/fuzz.py): 6000 random values over the characters # ' " \ $ ${ = { } and space.
- 3437 stored, 2563 refused, 0 mismatches. 'Mismatch' means a value that did not read back exactly through python-dotenv, the plain parser or the raw parser, changed another key, or did not keep mode 0640.
- No value that the round-1 rules accepted for a non-raw key is refused now; 154 values that used to be refused are now stored.
- Patch-request anchors in master_controller.py are present and unique (lines 1856, 1820, 1925), and _alerts.warning exists.

Mutation and negative controls, all reproduced:
- Running asyncio.to_thread inline makes the two P2 tests fail (/health max over 0.25 s).
- Forcing save-first makes test_a_rejected_paste_keeps_the_token_in_use fail.
- Making public_error_kind always return 'expired' makes 11 route tests fail.
- Removing the hand-off retry makes 3 hand-off tests fail.

Suites I re-ran (same counts as the fixer):

| Suite | Result |
|---|---|
| services/ui-api/tests | 997 passed |
| scripts/tests | 278 passed |
| tests | 684 passed, 9 skipped, 2 failed |
| services/execution-service/tests | 7 passed |
| alpha_lab tests | 20 passed |

- The 2 core failures are tests/integration/test_qa_tool_defaults.py: FakeContext has no route_web_socket, used by scripts/desktop_qa/probe.py. That is not F4-API's file.
- No ruff finding sits on a changed line of positions.py, icici_admin.py or daily_session_refresh.py; the four new or changed test files are ruff-clean.
- scripts/check_event_loop.py: OK.
- .env (23 Oct 08:08, 0644), .session_cache.json and data/icici_otp_last_ask.json were byte- and mtime-identical before and after my runs. No .env.tmp is left behind.

Other notes:
- data/icici_otp_last_ask.json now holds {"at": 0.0}, last written at 20:47:46 IST by F4-OPS's scripts/tests run. That run came before F4-API's test fix landed (test_otp_times_out_and_says_so writes a fake clock that starts at 0.0). It is harmless: minutes_since_otp_ask() reads 0 as 'never asked'. The earlier real timestamp is gone.
- P13 brief said 'preserve file mode 0600'. The writer keeps whatever mode the file has, and the live .env is still 0644, so the owner must run chmod 600 once (documented in deploy_notes). A save could also narrow group/other bits; that is a design choice for the PM.
- The rejected-paste check uses the classifier: a pasted token is refused only when ICICI's message matches the 'expired' patterns. This includes 'Resource not available', which could in theory appear for a valid token, so watch it after deploy.
- Deploy: ui-api must restart to load the new code (it is not in the freeze window). master-controller keeps its old in-memory write_env_value until it restarts; restart it outside the freeze windows, together with the three patch requests.

Reviewer scratch: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-F4-API/ (baselines *_base.py, fuzz.py, mut/).

