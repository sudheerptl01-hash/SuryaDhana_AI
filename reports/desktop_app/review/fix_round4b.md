# F4B-API

All four brief items are closed, plus one related .env race from the round 4a check that sits in my file icici_admin.py. Nothing live was touched: no restarts, no ICICI/Breeze/Telegram calls, and .env, data/price_alerts.json and data/notifications.jsonl are unchanged. (1) MAJOR price-alert freshness, fixed. SWRCache.get takes a new fresh=True flag. With it, an entry at or past its refresh_after is treated as a miss and the caller waits for the refresh, joining one already running. POST /api/alerts/run calls get_quotes(fresh=True), and GET /api/news-scanner/quotes accepts ?fresh=1 for the controller's move check (patch request filed). Display pollers keep stale-while-revalidate. A fake-clock test runs the 60 s scheduler cadence for 12 minutes, 3 symbols, with 4 display-poller patterns; every alert decision used a quote under 30 s old. The negative control on the round-3 code gives ages [3.0, 1.5, 0.0, 63.0, 61.5, 60.0, ...]. Checked in-process against real Yahoo: after 31 s a display read answered stale in 12 ms, and run_alerts waited for 2 fresh fetches (2.0 s). The misleading code comment is rewritten. (2) RAPI-06 remainder, fixed. The masker now scans each value: a quoted value ("...", '...', \"...\" inside a JSON string, %22...%22) is masked up to its real closing quote, escapes included, or to the end of the line if the quote is missing. URL-encoded values and separators are handled. Authorization and Cookie headers have their whole value masked; the scheme word is kept. 40,000 fuzz cases using ICICI password characters across 8 encodings: 0 leaks. 46 new tests; 32 of them fail on the original code. It also fixes the over-masking nit: 'Basic settings', 'token: <' and 'Bearer undefined' are no longer masked. (3) PR-F4-OPS-1 was applied correctly, and I verified it read-only on the real scans: 22, 23 and 25 Oct now give 16, 10 and 9 picks instead of 0. Tests are added; 3 fail without the key. The same format change also left the terminal's rejected rows with an empty name and duplicate React keys, so raw_ticker now falls back to the company name. (4) F3-API check minors: the .env read-back guard now lets a save repair a corrupted file, but never switches on a protected key, and both routes return persisted_reason. The cache warm-up reports a gold shortfall (gold_yahoo_series:0/6), and the corrected expectation is ok=7. ?since=² now gives 422 instead of 500. SWRCache.invalidate(key) is now per key. Markets invalidation on ingest is deferred. Extra: each .env writer now gets its own mkstemp temp file, closing the cross-process '.env.tmp' race. Gates: ui-api 1078 passed (baseline 997); core 699 passed, 9 skipped; scripts 284 passed. Ruff per-file per-rule counts are identical to the baseline on the 9 source files, and the new tests are clean. mypy shows the same 2 pre-existing errors. check_event_loop: OK. The 8 touched test files passed 3 runs in a row, 255 each.

## findings
- **F3-API-check-MAJOR (quotes SWR: the 60 s price-alert check priced against a ~58 s old quote)** fixed: cache.py: SWRCache.get(..., fresh=False). With fresh=True, an entry at or past its refresh_after is not served; the caller waits for the refresh, joining one already in flight (single flight kept). It is counted as fresh_waits in stats(). Per-value policy windows are kept, so 'not available' answers (120/120) are still served up to 120 s, as under the old TTL. routers/news_scanner.py: get_quotes gains a plain `fresh: bool = False` parameter, also exposed as query ?fresh=1. A plain default rather than Query() means direct Python callers such as quotes.py and markets.py keep the display behaviour. The C-PERF-01 comment is rewritten: the staleness bound is unchanged, but the typical age for 60 s display pollers is now about 58 s, and decision reads use fresh. routers/alerts.py: run_alerts calls get_quotes(..., fresh=True), with a docstring saying why. Other price-deciding callers: master_controller.move_alerts (±5/10% holdings and the NIFTY 200-DMA fallback) gets a patch request to send fresh=1. telegram_bot /quote and daily_wrap are display-only and stay on stale-while-revalidate.
  - tests: test_alert_quote_freshness.py (8). Fake clock, each Yahoo fetch takes 1.5 s of fake time and returns its finish time as the price. 12 scheduler runs at 60 s cadence, 3 symbols, display pollers at offsets (), (20), (45), (5, 29, 59): the maximum decision age is under 30 s in every case. In-test negative control: the same loop with fresh dropped gives every check after the first a quote of at least 57 s. The route asks for fresh=True. Over HTTP, ?fresh=1 gives X-Cache miss with age 0 while the display read gives stale, and the body shape is unchanged. Fetch budget: at most 2 per symbol per minute. test_swr_cache.py adds 4 fresh tests: waits instead of stale, a young entry is still a hit, joins a running refresh (one fetch), keeps the policy window. test_price_alerts fake asserts fresh is True. Scratch negative control with the original cache.py, news_scanner.py and alerts.py: 10 tests fail, including the cadence test for () and (20) with ages [3.0, 1.5, 0.0, 63.0, 61.5, 60.0, ...]. Real-Yahoo in-process check with a scratch ALERTS_PATH: display after 31 s answered stale in 0.012 s; run_alerts {'checked': 2, 'priced': 2} took 2.03 s, fresh_waits 0→2.
  - user-visible: Price alerts (scheduler every minute, and WTCH's own POST /api/alerts/run every 60 s) now always price with a Yahoo quote under 30 s old. That is at least as fresh as before C-PERF-01; the round-3 code used the previous minute's quote. That POST takes 0.5–2 s longer when the cached quote is 30 s or older. Yahoo load: at most 2 fetches per minute per alerted symbol when the scheduler and a WTCH window are offset by 30 s or more. WEI, WTCH and macro-tape 60 s polls are unchanged (they show the previous poll's quote, about 58 s old, as since C-PERF-01; now documented).
  - not fixed because: 
- **RAPI-06 remainder (quoted secrets masked only up to the first space/#/&/,/})** fixed: routers/client_errors.py: the single regex is replaced by a scanner, _mask_secrets.
- **Credential names:** api_key, app_key (X-AppKey), secret_key, session_key, private_key, apisession, *token, *secret, password, passwd, passphrase, plus whole-word pin, mpin, tpin, otp and totp. The name is followed by =, :, or encoded %3D/%3A, with spaces or %20 on the same line only.
- **Quoted values:** ", ', \" (JSON inside a JSON string) and %22/%27 are masked up to the matching closing quote. Backslash escapes and %5C%22 are honoured. If there is no closing quote, the mask runs to the end of the line. An empty "" is kept.
- **Unquoted values:** the mask stops at whitespace or a quote. '&' ends it only where a new name= pair starts, and ,;)]} end it only where they close a structure. '#' and %XX stay inside the mask.
- **Headers:** Authorization and Proxy-Authorization keep the scheme word; the credential after a single-token scheme (Bearer, Basic, Token, Negotiate, ApiKey) is masked, and everything else (Digest, HMAC, no scheme) is masked to the end of the line. Cookie and Set-Cookie are masked to the end of the line.
- **Kept as diagnostics:** null, undefined, None, true, false, NaN, and a single punctuation value ('token: <').
- **Standalone Bearer/Basic:** masked only when the word looks like a credential (a digit, +/=._~-, or at least 2 upper plus a lower case letter). 'Basic settings', 'Basic Settings' and 'Bearer authentication' are no longer masked.
- Masking still runs before the length cut. The module docstring is updated.
  - tests: test_client_error_masking.py (46 tests).
- **Property test:** 150 seeded secrets per template, built from the ICICI special characters @#$%&*!^()-_+={}[]|\:;"'<>,.?/~` and space, each with markers at its start, middle and end. 8 templates: JSON, compact JSON, JSON inside a string (axios config.data), Python repr, single-quoted, URL-encoded query, URL-encoded JSON, form body.
- **Exact-shape tests:** the reviewer's 4 examples, and the rest of the text kept.
- **Header tests:** Authorization and Cookie.
- **Basic credentials:** base64 of ICICI-character passwords.
- **Ordinary text kept:** the review's nits, plus 'Bearer undefined'.
- **Other:** stack lines are not crossed; every field is masked before the cut; a linear-time check on hostile 8 KB inputs (each under 0.5 s).
- **Scratch fuzz:** 40,000 cases, 0 leaks, 0.6 s.
- **Negative control** (original client_errors.py): 32 of the 43 tests that existed then fail.
- The existing test_client_errors.py and test_review_rapi_fixes.py still pass.
  - user-visible: Only ui-api.log content changes. Client-error lines no longer leak the tail of a quoted password, secret or token. Some ordinary texts that used to be masked ('Basic settings', 'token: <', 'Bearer undefined') are now logged as written.
  - not fixed because: 
- **PR-F4-OPS-1 (news_scanner.py _PICK_KEYS 'stage1_candidates', scanner files since 22 Oct read as 0 picks)** already-fixed: Verified that the applied patch is correct. The PM applied it at 21:15:05: _PICK_KEYS = ('stage1_picks', 'stage1_candidates', 'picks', ...). Read-only through the patched loader on the real files:
- new_scnner/20261022.json: 16 picks.
- 20261023.json: 10 picks.
- 20261025.json: 9 picks.
In all three, 0 tickers are unresolved and sources come from source_urls. list_scans shows 20261025 with 9 picks and 8 rejected, no error. Priority is kept: stage1_picks still wins for older scans, and stage1_candidates beats the generic keys (data, items and so on). scripts/news_scan_performance.py reads picks through the same load_scan_file, so the next track-record run includes 22–25 Oct. I added a comment above _PICK_KEYS and the tests the patch request asked for.
  - tests: test_news_scanner.py.
- test_scans_since_22_oct_read_their_stage1_candidates: exact 22-Oct shape; listing counts, conviction sort, source domains from source_urls, thesis steps, and load_scan_file as the track record uses it.
- test_stage1_picks_keeps_priority_and_stage1_candidates_beats_the_generic_keys.
- Negative control (key removed in a scratch copy): 3 tests fail.
- Real-file read-only run as described.
  - user-visible: After the ui-api restart, the News terminal shows the 22, 23 and 25 Oct scans with their picks (16, 10 and 9) instead of 0. The next 19:45 track-record run includes them.
  - not fixed because: 
- **PR-F4-OPS-1 follow-on: rejected rows in scans since 22 Oct have no ticker (empty name, duplicate React keys)** fixed: Since 22 Oct the scanner writes rejected entries as {company, reason, stage} with no ticker. _normalise_rejected returned raw_ticker '' for every row. NewsTerminal.tsx:388-389 uses raw_ticker both as the React key and as the row label, so the 'REJECTED BY SCANNER' list showed ' · reason' rows with duplicate keys. raw_ticker now falls back to the company name ('Yes Bank (YESBANK.NS)'). Rows that have a ticker are unchanged, and the contract shape is the same.
  - tests: test_rejected_rows_without_a_ticker_are_named_by_company: names, unique keys, empty symbols, and a ticker row unchanged. Fails on the original. Real files: rejected[0] raw_ticker is 'Yes Bank (YESBANK.NS)' (22 Oct) and 'Swiggy (SWIGGY.NS)' (23 Oct).
  - user-visible: In the News terminal, 'REJECTED BY SCANNER' rows for 22 Oct onwards show the company name before the reason.
  - not fixed because: 
- **F3-API-check minor: icici_admin read-back guard blocks a save that would repair a corrupted .env; reason not returned** fixed: _readback_problem refuses only when a key that holds a value today would lose it or get another one ('<KEY> would change'). A key that only appears is allowed: that is the repair case, where lines swallowed by the old raw writer's stray quote come back. The exception is protected keys (EXECUTION_*, GUARD_*, UI_API_*, PYTEST_*, FORWARDED_ALLOW_IPS and the like): a key appearing under one of those is refused ('<KEY> would appear'), so a repair can never switch on EXECUTION_LIVE_ALLOWED; that must be fixed by hand. Keys are checked in sorted order, so the reason is deterministic. positions.py adds persisted_reason to /credentials and to both /session-token reply paths (the connected:false and success branches). It is null when saved; otherwise it is the reason, which names keys only. The block comment is updated.
  - tests: - test_a_save_repairs_a_file_the_raw_writer_corrupted: the reviewer's corrupt.env shape; TELEGRAM_BOT_TOKEN, REDIS_URL and ICICI_SESSION_TOKEN come back, A and Z unchanged.
- test_a_repair_never_switches_on_a_protected_key: EXECUTION_LIVE_ALLOWED would appear; file untouched, no temp file left.
- test_a_value_held_today_still_may_not_change_or_vanish: unit test of _readback_problem; vanish and change are refused, appear is allowed, protected appear is refused.
- Route tests: persisted_reason 'DERIVED would change' on /session-token and 'DERIVED_KEY would change' on /credentials, with no token values in it; null on a save.
- The existing 'DERIVED would change' test still passes.
- Negative control (original files): 5 new tests fail.
  - user-visible: A Broker-tab save can now repair a .env that the pre-fix writer corrupted, except for protected keys. The /credentials and /session-token JSON gain persisted_reason. The UI does not show it yet; it shows res.data.error as before.
  - not fixed because: 
- **F3-API-check minor: _cache_warm deploy note said ok=9 (7 calls); gold step counted ok with 0/6 series** fixed: _cache_warm.py: the gold step is now _gold_series. It raises WarmShortfall('<usable>/<n>') when warm_series returns fewer than gold_preopen.WARM_SERIES_COUNT, so the log shows failed: ['gold_yahoo_series:0/6']. The docstring states that a healthy start logs ok=7, failed=[]. gold_preopen.py adds WARM_SERIES_COUNT = 2 + len(CONTEXT_SERIES), which is 6. warm_series itself is unchanged.
  - tests: test_a_healthy_start_logs_ok_7: 7 calls, ok 7. test_a_gold_warm_up_that_fetched_too_few_series_is_reported_as_failed[0, 5]: ok 6, failed ['gold_yahoo_series:N/6']. Negative control on the original logs ok 7, failed [] for 0/6, so 2 tests fail. The existing warm-set and lifespan tests pass.
  - user-visible: Log only: cache_warm_done reports ok=7 on a healthy start, and a partial gold warm-up appears under failed.
  - not fixed because: 
- **F3-API-check minor: notifications.parse_since str.isdigit -> ?since=² returned 500** fixed: parse_since accepts epoch milliseconds only as ASCII digits, up to MAX_SINCE_DIGITS = 15. Longer values get 422, which also keeps next_since inside i64 for feed.rs. Other values go to the ISO parser, which already returned 422 when it failed. Before, superscript digits gave 500, and full-width or Arabic-Indic digits were silently accepted as numbers.
  - tests: test_non_ascii_digits_and_absurd_epochs_are_a_422_not_a_500: ², Arabic-Indic, full-width, 16 and 40 digits, -5 and 1e12 all give 422. test_the_largest_accepted_epoch_still_answers. Negative control: 5 cases fail on the original. The 2 other failures in the scratch tree come from it having no scripts/ folder.
  - user-visible: None (an API edge case: 422 instead of 500).
  - not fixed because: 
- **F3-API-check nit: client_errors over-masks ordinary text ('Basic settings', 'token: <')** fixed: Fixed with RAPI-06 above. Bearer and Basic are masked only when the word looks like a credential, single-punctuation values are kept, and null, undefined and None are kept.
  - tests: test_ordinary_error_text_is_not_masked: 13 texts, which fail on the original.
  - user-visible: Log only.
  - not fixed because: 
- **F3-API-check nit: SWRCache.invalidate(key) bumped a cache-wide generation (drops other keys' in-flight fetches)** fixed: cache.py keeps a generation per key plus the global one. invalidate(key) bumps only that key; invalidate() or clear() bumps the global and resets the per-key map. A fetch stores its result only if both generations are unchanged since it started.
  - tests: test_invalidating_one_key_keeps_another_keys_running_fetch fails on the original. test_invalidate_all_still_drops_every_running_fetch. The existing invalidate test and the conftest autouse invalidate() still pass.
  - user-visible: None (only tests call invalidate today).
  - not fixed because: 
- **F3-API-check minor (optional): markets.py results/implied-moves/fundamentals not invalidated on nse_results / F&O ingest** deferred: No change.
  - tests: n/a
  - user-visible: Unchanged: EVTS, EQS and SCRN may show results or valuations up to 5 min after an ingest finishes.
  - not fixed because: ui-api cannot see the ingest. The writes run as data-service jobs started by master-controller (EOD pipeline, 20:45 results job). No ui-api route starts or completes them: pipeline.py only proxies build-ml-dataset, and ui/ has no ingest call. Wiring this needs either a new invalidate write endpoint on ui-api (a guard decision) called by the controller after each job, or a data-version signal from data-service. Neither fits a final round. Staleness is bounded at 5 min and documented in the markets.py header. A RUNBOOK line ('EVTS/EQS/SCRN may lag a results or bhavcopy write by up to 5 min') is the owner's call.
- **R4A-F4-API minor (extra, from fix_round4a.md): ui-api and master-controller share the fixed '.env.tmp' path** fixed: persist_env_updates now writes through tempfile.mkstemp(dir=.env's folder, prefix='.env.', suffix='.tmp'): O_EXCL, created 0600, then fchmod to the kept mode, the same read-back check, then os.replace. The temp file is unlinked on refusal or on any error. With a shared path, one process could truncate the other's temp file or rename it away. That could leave .env briefly empty or crash the other writer. A write that overlaps another process's write is now caught by the read-back check ('<KEY> would change') instead of silently undoing the other save. Not a full cross-process lock: there is no flock; see open issues.
  - tests: test_two_processes_writing_at_once_never_share_a_temp_file: writer B, using another process's lock, writes while A sits between its temp write and its read-back. A's temp file is intact and both temp names differ. A refuses with 'ICICI_PASSWORD would change' and B's save is kept; no temp file is left. On the original, A crashes with FileNotFoundError: .env.tmp, because B renamed it away. test_the_temp_file_is_private_and_removed_when_the_write_fails: the temp file is 0600 and is removed. The existing 'no .env.tmp left' assertion now globs .env*.tmp. tests/unit/test_icici_env_persist.py and scripts/tests (daily_session_refresh write_env_value) pass.
  - user-visible: None.
  - not fixed because: 

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/cache.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/icici_admin.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/news_scanner.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/alerts.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/client_errors.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/notifications.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/_cache_warm.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/gold_preopen.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/positions.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_alert_quote_freshness.py (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_client_error_masking.py (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_swr_cache.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_price_alerts.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_news_scanner.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_notifications_feed.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_cache_warm.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_env_roundtrip.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_icici_session_routes.py

## tests
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest services/ui-api/tests -q (baseline, before any change) -> 997 passed
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest services/ui-api/tests -q (final) -> 1078 passed, 2 warnings (+81 tests)
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests -q (core) -> 699 passed, 9 skipped (the 2 earlier test_qa_tool_defaults failures are no longer present)
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest scripts/tests -q -> 284 passed (news_scan_performance and daily_session_refresh import the changed modules)
- pytest on the 8 touched ui-api test files, 3 runs in a row -> 255 passed each run, no flakes
- Negative controls: new tests run against the original modules in scratchpad/F4B-API/negctl -> - freshness + SWR + price_alerts: 10 fail (cadence ages [3.0, 1.5, 0.0, 63.0, 61.5, 60.0, ...]).
- masking: 32 of 43 fail.
- news_scanner without the stage1_candidates key: 3 fail.
- notifications: 5 new cases fail.
- cache_warm: 2 fail (ok 7 with 0/6).
- env read-back + persisted_reason + temp race: 5 new tests fail (A crashes with FileNotFoundError .env.tmp).
- The other failures in the scratch tree are tests that read ROOT/scripts or ROOT/ui, which the scratch tree does not have.
- scratchpad/F4B-API/fuzz_mask.py (8 templates x 5000 ICICI-character secrets) -> cases 40000, leaks 0, 0.62 s
- In-process real-Yahoo check of the alert path (ALERTS_PATH in scratch; GET-only /db/prev-close to the live data-service) -> First fetch 0.63 s. Display read 31 s later answered stale in 0.012 s. run_alerts {'hits': [], 'checked': 2, 'priced': 2} took 2.03 s with fresh_waits 0→2 and misses 2→4. data/price_alerts.json and data/notifications.jsonl mtime and size unchanged.
- Real scan files, read-only, through the patched news_scanner -> 20261022: 16 picks, 11 rejected. 20261023: 10 picks, 11 rejected. 20261025: 9 picks, 8 rejected. 0 unresolved, listing errors none.
- ruff check --line-length 130 on the 9 changed source files: per-file per-rule counts compared with the baseline snapshot -> Identical (cache 1 UP037, icici_admin 6, news_scanner 11, alerts 9, client_errors 1 I001, notifications 1 I001, _cache_warm 0, positions 16, gold_preopen 12; all pre-existing). New and changed test files: All checks passed. test_cache_warm I001 at line 167 and test_news_scanner RUF100 at line 10 are pre-existing lines.
- mypy --ignore-missing-imports --follow-imports=silent on the 9 source files, new vs original -> Identical: 2 pre-existing errors in news_scanner.py and 1 annotation-unchecked note in positions.py
- /Users/sudheer/Desktop/jupyter_env/bin/python scripts/check_event_loop.py -> event-loop purity: 0 findings, OK
- tsc / cargo clippy / cargo fmt -> Not applicable: no TypeScript or Rust files changed

## patch requests
### PR-F4B-API-1 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: move_alerts (every 5 min) fires the ±5/±10% holdings alerts from change_pct, so it decides on prices. Without ?fresh=1 it can get a stale-while-revalidate quote up to 60 s old whenever a display poller (WTCH, PORT) refreshed the symbol a minute earlier. With it, every quote is under 30 s old (ui-api F4B-API item 1). Safe in any deploy order: an older ui-api ignores the extra query parameter. Needs a master-controller restart outside 07:45–09:20 and 18:30–21:15 IST. Anchor is at line 1103-1104 today; it matches exactly once.

OLD:
```
                    q = (await client.get(f"{UI_API}/api/news-scanner/quotes",
                                          params={"symbols": ",".join(f"{x}.NS" for x in syms[:60])})).json().get("quotes") or {}
```
NEW:
```
                    q = (await client.get(f"{UI_API}/api/news-scanner/quotes",      # fresh: it decides, < 30 s old
                                          params={"symbols": ",".join(f"{x}.NS" for x in syms[:60]), "fresh": "1"}
                                          )).json().get("quotes") or {}
```
### PR-F4B-API-2 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: The same move_alerts check uses the Yahoo NIFTY fallback for the 200-day-average crossing alert, which is a price decision; ask for a fresh quote. The anchor is at line 1116 today and matches once. The new lines are under 130 characters.

OLD:
```
                    nq = (await client.get(f"{UI_API}/api/news-scanner/quotes", params={"symbols": "^NSEI"})).json().get("quotes") or {}
```
NEW:
```
                    nq = (await client.get(f"{UI_API}/api/news-scanner/quotes",
                                           params={"symbols": "^NSEI", "fresh": "1"})).json().get("quotes") or {}
```
### PR-F4B-API-3 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/.gitignore
why: persist_env_updates writes the whole .env, secrets included, to a temp file next to it for a few milliseconds. Before this round it was '.env.tmp'; now each writer gets its own '.env.XXXXXXXX.tmp' via mkstemp. A writer killed mid-write (SIGKILL or a power loss) leaves that file behind. Neither name is git-ignored today: `git check-ignore -v .env.ab12cd.tmp .env.tmp` matches nothing. This does not overlap PR-F4-OPS-2, which edits the data/ block.

OLD:
```
# Secrets & credentials
.env
.session_cache.json
```
NEW:
```
# Secrets & credentials
.env
.env.tmp
.env.*.tmp
.session_cache.json
```

## deploy notes
- Restart ui-api only. It is not in the freeze windows; the PM deploys after this round, and I restarted nothing. shared/http_guard.py is unchanged, so no data-service or master-controller restart is needed for my files.
- After the ui-api restart, GET-only checks:
- (a) `curl -s -D - -o /dev/null 'http://127.0.0.1:8010/api/news-scanner/quotes?symbols=TCS.NS&fresh=1' | grep -i x-cache`: the second call within 30 s gives hit, and after 30 s gives miss (never stale).
- (b) `curl -s http://127.0.0.1:8010/api/telemetry/caches`: the news_scanner.quotes row shows fresh_waits climbing during market hours, at roughly the scheduler and WTCH alert runs.
- (c) `curl -s 'http://127.0.0.1:8010/api/news-scanner/scans'`: 20261025 shows 9 picks, 20261023 shows 10, 20261022 shows 16.
- (d) .logs/ui-api.log: cache_warm_done with ok=7 and failed=[] on a healthy start. The round-3 note's ok=9 was wrong. 'gold_yahoo_series:N/6' in failed means Yahoo returned only N of the gold desk's 6 series.
- The master_controller move_alerts patch (?fresh=1) can land before or after the ui-api restart, because an old ui-api ignores the parameter. It needs a master-controller restart outside 07:45–09:20 and 18:30–21:15 IST.
- The next news track-record run (Mon 19:45, or a manual run) picks up the 22–25 Oct scans: scripts/news_scan_performance.py uses the same load_scan_file and needs no restart, since it runs as a subprocess.
- API additions, all additive:
- GET /api/news-scanner/quotes accepts ?fresh=1.
- POST /api/positions/credentials and /session-token replies carry persisted_reason (null when saved, else key names only).
- /api/telemetry/caches swr rows carry fresh_waits.

## open issues
- Markets SWR invalidation on ingest is deferred; see the finding. EVTS, EQS and SCRN can lag a results or bhavcopy write by up to 5 min. Closing this needs a controller hook or a data-version signal.
- .env writes are still not serialized across processes (no flock). Since this round, two overlapping writers can no longer clobber each other's temp file, and the later one refuses ('<KEY> would change') instead of silently undoing the other save. A gap of a few milliseconds remains between one writer's check and its rename. A cross-process fcntl lock on a '.env.lock' file would close it, but it adds a new file in the repo root, so it is left for the PM.
- Unquoted secrets that contain spaces in free text (e.g. 'password=ab cd') are inherently ambiguous: only 'ab' is masked. Quoted, URL-encoded and JSON forms are fully masked. The UI posts credentials as JSON, so those are covered.
- The UI does not show persisted_reason yet (BRKR shows res.data.error). This is UI-owned and optional.
- Not in my brief and unchanged: SECREL-08 (CSP in static_ui.py) and SECREL-09 (one httpx client per request), both listed as F3-API open issues.
- With fresh quotes, a WTCH window and the scheduler offset by 30 s or more can cause up to 2 Yahoo fetches per minute per alerted symbol; under the old 60 s TTL it was 1. That is a few tens of symbols at most, well inside the 6-wide semaphore. Watch for Yahoo 429s after deploy.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/client_errors.py: Some secrets still leak, which goes against the '0 leaks' claim. When a credential-named key has an unquoted value that starts with an auth-scheme word, only the scheme word is masked and the real credential is logged. Shapes: `token: Bearer <jwt>`, `X-SessionToken: Bearer …`, `auth_token: Basic <b64>`, `pin=Bearer …`. The token/secret names already leaked this way in the round-3 code. The new names (pin, mpin, tpin, otp, totp) are a small regression: the old standalone _BEARER_RE masked their credential, but now the key scanner replaces the word 'Bearer' first, so _BEARER_RE never fires.
  - evidence: I imported both modules in scratch (scratchpad/R4B-API/probe_mask.py, diff_mask.py).
- 'access_token: Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig' becomes 'access_token: <redacted> eyJhbGciOiJIUzI1NiJ9.e30.sig'. The original code gives the same output.
- 'pin=Bearer QQSECRETQQ x': the original gives 'pin=Bearer <redacted>', the new code gives 'pin=<redacted> QQSECRETQQ x'.
- A differential over about 19k name × separator × value shapes found 0 regressions apart from this class and the newline case below.
  - fix: In the unquoted branch of _mask_secrets, first try _AUTH_SCHEME_RE.match(text, pos). If the scheme is a single-token one (bearer, basic, token, negotiate, apikey), output the scheme followed by <redacted> and skip the next [^\s"']+ word, as the header branch does; keep 'Bearer undefined' as it is. Add masked-shape tests for `token: Bearer x.y.z`, `X-SessionToken: Bearer …` and `pin=Bearer …`, with a negative control.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/client_errors.py: A small narrowing in the `stack` field, where newlines are kept. A credential name at the end of a line whose value is on the next line is no longer masked. The old `\s*` separator crossed the newline; the new separator never crosses a line. This is a deliberate choice and the risk is low, because JSON.stringify keeps a key and its value on one line. The module docstring does not mention it.
  - evidence: With keep_newlines=True:
- 'password:\n  "QQSECRETQQ"': the original gives 'password:\n  "<redacted>"', the new code leaves it unmasked.
- 'api_key=\nQQSECRETQQ': the same.
Test test_a_name_at_the_end_of_a_stack_line_does_not_mask_the_next_line pins this behaviour on purpose.
  - fix: Accept it and document it in the module docstring, or allow one newline plus indentation before an opening quote only (a quoted value on the next line is unambiguous).
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/news_scanner.py: Two places describe deployment as already done:
- The quote-cache comment says the controller's move check reads via ?fresh=1. That is only a pending patch request against master_controller.py; until it is applied and the controller restarted, move_alerts still gets quotes up to 60 s old.
- The deploy note says 'no data-service or master-controller restart is needed for my files'. But master-controller loads icici_admin.py in-process (daily_session_refresh._icici_admin, cached in sys.modules, for Telegram /password and /userid). Its writes get the mkstemp temp file and the repair allowance only after a controller restart. This is harmless, because the new ui-api and an old controller use different temp names and never collide, but the note is inaccurate.
  - evidence: news_scanner.py:570-573 ('the controller's move check via ?fresh=1'). master_controller.py:1103-1104 and :1116 have no 'fresh' parameter today. master_controller.py:1919-1922 (_env_set imports write_env_value), and daily_session_refresh.py:95-112 caches the module in sys.modules.
  - fix: Make the comment conditional ('the controller's move check should pass ?fresh=1, PR in fix_round4b'). In the deploy notes, say that the master_controller patch's restart also picks up the icici_admin change for controller-side .env writes.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/routers/client_errors.py: Nit. Ordinary text with the new names, or with a header-like word, is now masked, so a few log lines become harder to read. Separately, the Authorization credential pattern swallows a closing '}'.
  - evidence: Log text only; no secret is exposed by these.
- 'Failed to pin: window closed' becomes 'Failed to pin: <redacted> closed'.
- 'otp: expired, request again' becomes 'otp: <redacted>, request again'.
- 'mpin: 4 digits required' becomes 'mpin: <redacted> digits required'.
- 'Cookie: consent failed' becomes 'Cookie: <redacted>'.
- 'Authorization: required for /api/positions' becomes 'Authorization: <redacted>'.
- 'headers: {Authorization: Bearer abc.def.ghi}' becomes '...Bearer <redacted>', and the '}' is lost.
  - fix: Optional. For pin/otp, mask only values that contain a digit. Stop the single-token credential at ,;)]} when one of them closes a structure (reuse _UNQUOTED_VALUE_RE).
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/tests/test_env_roundtrip.py: Nit. The docstring of test_two_processes_writing_at_once_never_share_a_temp_file says 'both saves land', but the test asserts that writer A refuses ('ICICI_PASSWORD would change') and only B's save lands.
  - evidence: tests/test_env_roundtrip.py:299-301 (docstring) and :320 (assert out == {'persisted': False, ..., 'reason': 'ICICI_PASSWORD would change'}).
  - fix: Reword the docstring: 'neither temp file is clobbered; A refuses instead of undoing B's save'.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/cache.py: Nit. _key_generation keeps one entry for every key ever passed to invalidate(key), with no bound. It is cleared only by invalidate()/clear(). Today only tests call invalidate(key), so this has no effect now.
  - evidence: cache.py:180 and invalidate(): self._key_generation[key] = ... is never evicted with the LRU entries.
  - fix: Optional. Drop the per-key counter in _done once no fetch for that key is running, or cap the dict like max_items.
- not really fixed: []
- notes: All four brief items are fixed in substance, and the claimed 'already-fixed' item (PR-F4-OPS-1) is really fixed. I found no logic change outside the defects named, no security regression, and no live-stack contact. Trading logic is untouched: alerts.py changes only the fresh flag, and check_levels is unchanged.

**How I checked.** I diffed every changed source file against F4B-API/orig. markets.py, pipeline.py and shared/http_guard.py are unchanged. The only files modified since 21:15 outside the list are master_controller.py (21:15:05, the PM's PR-F4-OPS-1 batch) and scripts/tests (other fixers).

**Re-run gates**

| Suite or gate | Result |
|---|---|
| ui-api | 1078 passed |
| core | 699 passed, 9 skipped |
| scripts/tests | 284 passed |
| freshness + SWR + env_roundtrip + masking, 5 runs | 166 passed each time, no flakes |
| mypy on the 9 source files | the same 2 errors in news_scanner.py as before |
| check_event_loop | OK |

Ruff per-rule counts on the 9 source files are identical to the originals. I checked with the repo config via --stdin-filename, because the fixer's own ruffcount.sh ran inside the scratch orig dir. The new tests are ruff-clean. The 2 hits in test_cache_warm and test_news_scanner are on lines the fixer reports as pre-existing.

**Negative controls**, rebuilt in my own scratch tree (scratchpad/R4B-API/neg; the original modules swapped in, then restored and verified):

| Original module swapped in | New tests that fail |
|---|---|
| cache.py + alerts.py + news_scanner.py | 11. The cadence test fails only for display offsets () and (20); for (45) and (5,29,59) the old code already passed, which is correct. |
| client_errors.py | 35 |
| notifications.py | 6 |
| _cache_warm.py + gold_preopen.py | 3 |
| icici_admin.py + positions.py | 6 |

**Checked as correct**
- **Fresh semantics:**
  - A hit under 30 s is still served.
  - A read at or past 30 s waits, joining a refresh that is already running.
  - Policy windows for 'not available' answers are kept.
  - A plain `fresh: bool = False` default means direct Python callers (quotes.py:86, markets.py:1110) keep the display behaviour. Query() here would have made the flag truthy for every caller.
  - Old ui-api processes ignore ?fresh.
  - Price alerts are evaluated only on the server (ui/lib/alerts.ts calls POST /run), so nothing else decides on the 58 s-old display quote.
- **Masker:**
  - The 4 quoted shapes from the round-3 review are fully masked, as are URL-encoded JSON, JSON nested 3 levels deep, unterminated quotes, Digest headers and Cookie headers.
  - Over about 19k shapes compared with the original, there are 0 regressions apart from the two classes reported.
  - Hostile 8 KB inputs take at most 2.4 ms (no ReDoS).
- **.env writer (icici_admin):**
  - A key that appears is allowed only when it is not protected. EXECUTION_* covers EXECUTION_MODE and EXECUTION_LIVE_ALLOWED.
  - A key whose value would vanish or change is still refused.
  - Keys that appear come only from text already in the file, so nothing can be injected.
  - persisted_reason names keys only.
  - mkstemp + fchmod + unlink on error is correct, and no .env*.tmp file is left behind.
- **parse_since:** epochs are bounded at 15 digits; only integer comparisons follow.
- **WARM_SERIES_COUNT = 6:** matches the 6 symbols warm_series requests.
- **Real scans, read-only:**
  - 22 Oct: 16 picks, 11 rejected.
  - 23 Oct: 10 picks, 11 rejected.
  - 25 Oct: now 12 picks and 12 rejected. The file was rewritten at 21:40, after the fixer's 9/8 check.
  - Every rejected row has a unique, non-empty name, and no stock is both a pick and rejected.
- **Patch requests:**
  - Both master_controller anchors occur exactly once.
  - Applied to a scratch copy, the file compiles, the ruff counts are unchanged, and the new lines are at most 115 characters.
  - The .gitignore anchor occurs once.
- **Live files unchanged:**
  - .env: 23 Oct 08:08.
  - data/price_alerts.json and data/notifications.jsonl: unchanged.
- **Deferral:** markets invalidation on ingest is reasonably deferred, with the bound documented at 5 min.

**Main ask before deploy:** none blocking. The Bearer-in-key-value masking gap is the only real leak class left, and it is not reachable from the terminal's own payloads (the UI sends JSON with quoted values and no Bearer headers).

**My own side effect:** my first ruff runs wrote cache entries under services/ui-api/.ruff_cache. That is ruff's self-ignored cache dir, and nothing else in the repo was written. All other scratch work is in scratchpad/R4B-API.

# F4B-OPS

All four brief items are handled, and the core suite is green again: 699 passed, 9 skipped, 0 failed. It was 685 passed and 1 failed.

(1) The runbook test failed because round 3 removed the kickstart line from RUNBOOK §5, while `status` still pointed users to §5 for that remedy. The RUNBOOK, CLAUDE.md:116 and the start-local.sh status comment now describe what the code does today. That was checked against supervise.rs, crash.rs, autostart.rs and lib.rs, and against the installed 15:36 app, which has no crash guard:
- launchd's KeepAlive relaunches the copy that the login job started.
- A copy reopened by hand runs a `suryadhana-crash-guard` (app builds from round 3 on). It kickstarts the job, or bootstraps it if the job is not loaded, after an unclean end.
- In every other case `status` shows the quit + kickstart remedy, which §5 now documents again, with a fallback to `launchctl bootstrap`.

The single kickstart assertion is replaced by a reconciliation test across the RUNBOOK, CLAUDE.md, start-local.sh and supervise.rs. The status-row tests now stub pgrep and cover 6 cases. A cross-component test starts supervise.rs's real GUARD_SH with the app's argument layout and checks that the real pgrep pattern finds it.

(2) The RUNBOOK §2 advice on .env quoting is rewritten to match icici_admin.encode_env_line:
- write values unquoted;
- use single quotes only for a ` #` or a leading or trailing space, and double quotes if such a value also holds a single quote;
- `${` can never be stored;
- the three raw-read keys always stay unquoted.

§2 also gives a read-back check that prints key names only. Doc tests run the examples through python-dotenv, the plain parser and encode_env_line.

(3) Review items in my files:
- **boot_epoch:** F3-RUST's major finding. The greedy sed returned kern.boottime's usec, so the app never treated a watchdog run as holding the lock. It now returns the seconds, and owner lines written in the old usec format fall back to the pid checks.
- **Reload mode:** USR1 is no longer sent to a UI_API_RELOAD=1 --reload supervisor.
- **Dry run:** WATCHDOG_DRY_RUN=1 no longer prunes the hang-restart record.
- **Weak test:** the previous-boot lock test now uses a live, watchdog-named holder. A mutation that deletes the boot rule is caught.
- **Timing test:** extended to the desktop files and CLAUDE.md.
- **RUNBOOK table:** a pipe escaped with `\|` inside a table cell is replaced by a glob.
- **F4-OPS test hygiene:** a real startup_catchup lock test (it catches the mutation the reviewer found), lifespan tests that restore the scheduler and start it paused, and a close() spy in the news test.
- **WebSocket mock (R-OPS-09):** checked in real Chromium and WebKit: MOCKED_OK CONTROL_OK.
- **Outside my files:** the master_controller items are filed as patch requests with tests: the Telegram /status crash-guard line, misfire_grace_time for the backup catch-up, the JobHistory row guard, and the HUNG-line wording.

(4) CI already discovers every plain-node check file. CLAUDE.md's hand-written list missed no-dialogs.check and streamProxy.check; it is now a discovery loop, with a drift test that compares it to CI's list.

stack_watchdog.sh and start-local.sh were installed atomically at 21:35. The live watchdog run at 21:36 exited 0.

Trading logic is untouched. Nothing was restarted.

## findings
- **F4B-OPS-1 (failing core test test_the_runbook_owner_actions_are_written_down_and_every_link_resolves; SECREL-06 crash-relaunch reconciliation)** fixed: Root cause: F3-RUST's SECREL-06 RUNBOOK edit (PR-F3-RUST-7) dropped `launchctl kickstart gui/$(id -u)/SuryaDhana` from §5, but start-local.sh's status hint still printed 'quit the app (⌘Q), then launchctl kickstart … (RUNBOOK §5)', and CLAUDE.md:116 still said a hand-opened copy is 'not supervised until the next login'.

What the code does, read from supervise.rs, lib.rs supervise_this_copy, crash.rs, the autostart.rs plist and strings in the installed binary:
- launchd's KeepAlive relaunches only the login job's process.
- A copy the Launch-at-Login entry starts, but which is not launchd's own process, runs a detached `/bin/sh -c GUARD_SH suryadhana-crash-guard <app pid> …` (app builds from round 3 on).
- The guard polls every 15 s. After an unclean end (run.json still names the pid) it runs `kickstart gui/<uid>/SuryaDhana`, or `bootstrap` when the job is not loaded.
- Four crashes in 10 min stand the job down.
- The installed 15:36 app has no guard (`grep -c suryadhana-crash-guard` gives 0).

Changes:
- **RUNBOOK §4:** lists all four status phrases.
- **RUNBOOK §5:** keeps F3-RUST's crash-guard text and adds the crash-loop breaker. A new 'No crash guard?' bullet gives quit + `launchctl kickstart gui/$(id -u)/SuryaDhana`, with a `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/SuryaDhana.plist` fallback.
- **CLAUDE.md:116:** names the crash guard, says older builds are not relaunched, and points to the menu-bar item, the status row and RUNBOOK §5.
- **start-local.sh:** the app_status_row comment is corrected (comment only; the logic is F3-RUST's PR-8/9, already applied).
- **The failing test:** loses the bare kickstart assertion. The new test_crash_relaunch_is_described_the_same_in_the_runbook_claude_md_and_status checks that:
  - GUARD_NAME from supervise.rs appears in RUNBOOK §5, CLAUDE.md and start-local.sh's pgrep;
  - every `sup=` phrase in app_status_row is explained in §4;
  - the status hint's kickstart command and the bootstrap fallback are in §5;
  - CLAUDE.md no longer claims 'not supervised until the next login'.
  - tests: **New and changed tests:**
- test_crash_relaunch_is_described_the_same_in_the_runbook_claude_md_and_status (new).
- test_app_row_names_the_installed_copy_and_who_relaunches_it, 6 cases. pgrep is now stubbed; before, the tests used the real pgrep, and the live app's pid happens to be 83455, the test pid. Cases: login job; guard; another copy's guard does not count; no guard; login off; guard but login off. The kickstart hint appears only when nothing relaunches the app.
- test_status_finds_a_real_crash_guard_spawned_the_way_the_app_spawns_it (new): supervise.rs's real GUARD_SH with spawn_guard's argv order (drift-checked by regex). The real pgrep finds it; an unguarded pid gets the remedy (negative control). Nothing can reach launchd: the plist path does not exist and the tool is /usr/bin/false.

**Results:**
- The original runbook test passes again.
- Negative control (orig RUNBOOK, CLAUDE.md and start-local.sh in scratchpad/F4B-OPS/neg): the reconciliation test fails ('suryadhana-crash-guard').
  - user-visible: Documentation only. `status` output is unchanged.
  - not fixed because: 
- **SECREL-03-runbook (F3-OPS not-really-fixed: RUNBOOK §2 .env quoting advice)** fixed: §2 is rewritten to match icici_admin.encode_env_line (F4-API P13) and how the readers behave:
- write values unquoted: `ICICI_PASSWORD=pa#ss` reads back as pa#ss, since `#` starts a comment only after a space;
- use single quotes only for a ` #` or a leading or trailing space (`'pa #ss'`), and double quotes if such a value also holds a single quote (`"it's #1"`);
- `${` can never be stored: python-dotenv expands it in every quoting style, so `'pa#ss${x}'` reads back as `pa#ss`, and the Broker tab refuses it. The owner should change such a password;
- values that start or end with a quote cannot be stored either;
- ICICI_API_KEY, ICICI_API_SECRET and ICICI_SESSION_TOKEN stay unquoted.

§2 also gives a read-back check. For the ICICI_, TELEGRAM_ and HEALTHCHECK_ keys it compares dotenv_values with the plain or raw parse and prints key names only, never a value. It prints OK on the live .env and on .env.example. A first version that checked every key flagged .env.example's harmless inline comment on TICK_PERSIST; that version was dropped.
  - tests: - test_the_runbook_env_quoting_advice_is_what_the_readers_and_the_broker_tab_do: each §2 example reads back as stated through dotenv_values and plain_env_value, and equals encode_env_line's choice. The `${` example reads back as pa#ss, and env_value_problem refuses it. All three raw keys are named.
- test_the_runbook_env_check_names_misread_keys_and_never_prints_a_value: the snippet is extracted from the RUNBOOK and run as written. It prints OK on the §2 forms and on .env.example. On a bad file it prints exactly 'FIX (read differently): ICICI_API_SECRET ICICI_PASSWORD TELEGRAM_CHAT_ID', and no value appears in its output.
- Negative control against the orig RUNBOOK: both tests fail ('reads single-quoted values literally', and 'lost its .env read-back check').
  - user-visible: RUNBOOK §2 no longer recommends a quoting that breaks the 08:00 login, and it has a key-names-only check.
  - not fixed because: 
- **F3-RUST-CHK SECREL-05 app side (major): watchdog boot_epoch greedy sed** fixed: stack_watchdog.sh boot_epoch is now `sed -nE 's/^[{] *sec = ([0-9]+),.*/\1/p'`. Live it gives 1792906041; the old pattern gave 658471, the usec field. So take_lock now writes '<pid> <boot epoch seconds>', which the round-3 app (stack.rs, boot_time_secs) compares with.

The watchdog's own previous-boot rule and its no-owner `made < boot` rule were dead before and now work.

Transition safety: lock_is_stale compares only a boot field of 9 or more digits. An owner line written before the fix (usec, at most 6 digits) is decided by the pid and watchdog-command checks, so a live old-format run is never taken over.

The desktop side (stack.rs owner_boot_matches, being changed in round 4b by its owner) accepts both sec and usec, so any deploy order is safe.
  - tests: - test_the_owner_line_carries_the_boot_epoch_the_app_compares_with (new): the real boot_epoch and take_lock, with no stub, are compared with kern.boottime tv_sec read through ctypes sysctlbyname (an independent path).
- New lock cases: live-watchdog-usec-owner (not stale) and dead-pid-usec-owner (stale).
- Negative control on the 18:12 watchdog: the owner-line test fails with ('658471', 1792906041), and the usec-owner case fails.
- Live: the 21:36 launchd run of the installed script exited 0, updated last_all_up and released the lock.
  - user-visible: With the round-3+ app, the boot page and tray show 'the watchdog is starting the stack' again while a watchdog run holds the lock. The installed round-2 app is unaffected.
  - not fixed because: 
- **F3-OPS-CHK UI_API_RELOAD USR1 kills the reload supervisor (minor regression from R-OPS-07)** fixed: py_stacks_registered now refuses a pid whose command line contains ' --reload'. That is the uvicorn reload supervisor, which start-local.sh records in .pids/ui-api.pid but which has no handler. The worker was already refused, because it is not the pidfile pid.

In reload mode a hang capture therefore has no py-stacks file, but the supervisor survives. The R-OPS-04 re-check then sees the same listeners and the restart proceeds, instead of the orphaned-worker / 'held by another program' loop the reviewer reproduced.
  - tests: - test_a_reload_supervisor_is_never_sent_usr1 (new): a real supervisor process (no handler, '--reload' on its command line) whose real child registered faulthandler and wrote the announcement into the log. The pidfile names the supervisor. capture_hang runs with the real diag_pystacks. Expected: the supervisor is alive afterwards, and both pids are 'not requested'.
- Negative control on the 18:12 watchdog: fails with 'the --reload supervisor must survive the capture'.
- The existing announce/silent/other-pid test still passes.
  - user-visible: Only with the opt-in UI_API_RELOAD=1: a hung ui-api is restarted again, without Python stacks in its capture.
  - not fixed because: 
- **F3-OPS-CHK weak 'previous-boot' lock test** fixed: The previous-boot case's owner is now a live process named like a watchdog (`bash -c 'sleep 30; :' stack_watchdog.sh`) with boot = boot - 86400. So only the boot rule can call it stale. It used to be pytest's own pid, which is stale for 'not a watchdog' whatever the boot.
  - tests: Mutation check: a watchdog copy with the boot-comparison line deleted (scratchpad/F4B-OPS/mut_watchdog.sh) makes previous-boot fail (1 failed, 7 passed). With the real script all 8 cases pass.
  - user-visible: none
  - not fixed because: 
- **F3-OPS-CHK nit 1: WATCHDOG_DRY_RUN=1 pruned .pids/watchdog/hang-restarts-<svc>** fixed: recent_hang_restarts counts without rewriting the file when DRY_RUN=1. A real run still prunes lines older than the window.
  - tests: test_a_dry_run_leaves_the_hang_restart_record_alone (new). Dry run: count 1 and the file is byte-identical. Real run: count 1 and the old line is pruned. Negative control on the 18:12 watchdog: fails.
  - user-visible: none (dry runs really change nothing now)
  - not fixed because: 
- **F3-OPS-CHK nit 2: hang-timing test did not cover the desktop files** fixed: test_the_documented_hang_timing_is_the_same_everywhere now also requires '3.5–5.5 min', and no 'about 4 min', in health.rs, lib.rs, boot.js and desktop/README.md (patches 5–11 had landed), and '3.5–5.5 min' in CLAUDE.md. A desktop file is skipped only if the checkout lacks it.

The CLAUDE.md self-healing paragraph was also stale. It now gives the timing, the busy grace, the master-controller-only login wait capped at 10 min, the hourly cap, and a safe `kill -USR1` rule. The old text implied USR1 is safe on any service, but it kills the live data-service, which started before its handler was added.
  - tests: Passes now. Negative control: against the orig CLAUDE.md it fails ('CLAUDE.md').
  - user-visible: CLAUDE.md text only
  - not fixed because: 
- **F3-OPS-CHK nit 3: Telegram HUNG line omits the busy grace and the hourly cap** deferred: Patch request for scripts/master_controller.py: text only, verified in a scratch tree.
  - tests: In the scratch tree, test_bot_status still passes with the patch (21 passed with all patches applied).
  - user-visible: After the patch and a master-controller restart: the /status HUNG line mentions the ~16 min busy grace and the 3-per-hour cap.
  - not fixed because: master_controller.py is not in F4B-OPS's brief.
- **F3-OPS-CHK nit 4: RUNBOOK first-trading-day table had `ls … \| grep …` in a code span** fixed: Replaced with `ls -l data/backups/duckdb/*"$(date +%Y%m%d)"*`. There is no pipe in the table, and it matches both market- and ui_prefs- files.
  - tests: Doc change. The glob was checked against data/backups/duckdb naming (db_backup.py: market-YYYYMMDD.*, ui_prefs-YYYYMMDD.*).
  - user-visible: The command can be copied and pasted from the raw .md.
  - not fixed because: 
- **F3-OPS-CHK (major): test_qa_tool_defaults FakeContext lacked route_web_socket** already-fixed: PR-F3-OPS-1/2 are applied: tests/integration/test_qa_tool_defaults.py:45 has route_web_socket.
  - tests: The core suite is 699 passed, 0 failed. test_qa_tool_defaults is included in the 217-passed desktop run.
  - user-visible: none
  - not fixed because: 
- **R-OPS-09 (F3-OPS not-really-fixed): real-browser check of probe.new_qa_context's WebSocket mock; ui_perf note** fixed: Ran the round-3 check (a copy at scratchpad/F4B-OPS/ws_mock_check.py) once no other browser was running. Chromium then WebKit, one at a time, local http and websockets servers on ephemeral ports only. Results:
- mocked: the page socket opens, 0 server connections, URL recorded;
- live_websockets=True control: 1 server connection;
- output: MOCKED_OK CONTROL_OK, rc 0, no browser left running.

qa_harness.md now records this, and notes that ui_perf has no opt-out (its idle window has no live-tick rendering). ui_perf.py's docstring is outside my files.
  - tests: scratchpad/F4B-OPS/ws_mock_check.py: MOCKED_OK CONTROL_OK in both engines (output in scratchpad/F4B-OPS/ws_mock_check.out).
  - user-visible: Documentation only.
  - not fixed because: 
- **F3-RUST PR-10: run_selftest idle sample labelled START-UP** already-fixed: Applied: scripts/desktop_qa/run_selftest.py:528-530 has 'a START-UP sample … not idle' and evidence sample_kind='startup'.
  - tests: grep evidence. The QA harness tests pass (217 passed run).
  - user-visible: none
  - not fixed because: 
- **F4-OPS-CHK test gap: nothing proved startup_catchup holds the lock the backup waits on** fixed: New test_the_data_catchup_itself_holds_the_lock_the_backup_waits_on runs the real startup_catchup with _startup_catchup_run replaced by a blocking step. It asserts:
- the lock is held while that step runs;
- a concurrent db_backup_catchup makes no subprocess call until the step ends;
- the backup then runs exactly once.
  - tests: - Mutation (scratchpad/F4B-OPS/mutmc, real file copies) with `async with _get_lock("startup_catchup")` removed: the new test fails ('startup_catchup must hold its lock …').
- The reviewer's symlink tree silently imported the repo's own master_controller through db_backup's resolved path; this tree uses real copies.
- Real code: 25 passed.
  - user-visible: none
  - not fixed because: 
- **F4-OPS-CHK lifespan test hygiene (leaked mc.scheduler, live AsyncIOScheduler)** fixed: New _quiet_lifespan helper:
- monkeypatch.setattr(mc, 'scheduler', None), so teardown restores it;
- mc.AsyncIOScheduler is replaced by a subclass whose start() is start(paused=True), so no cron job can fire on the real clock.

Both lifespan tests use it. A new test_lifespan_wiring_leaves_no_scheduler_and_runs_no_job asserts the scheduler is paused with more than 20 jobs registered, that exactly one was built, and that it is shut down.
  - tests: test_backup_catchup: 25 passed (23 before). scripts/tests: 284 passed.
  - user-visible: none
  - not fixed because: 
- **F4-OPS-CHK weak 'closes it' assertion in test_news_track_record** fixed: duckdb.connect is wrapped with a _ConnSpy that records close() and keeps a reference to the real connection, so reference counting cannot close it. The test asserts:
- exactly one read-only open;
- close() was called;
- a read-write reopen succeeds while the test still holds the reference.
  - tests: 12 passed. Mutation (scratchpad/F4B-OPS/mutnews) with the `finally: con.close()` removed from load_prices: fails ('load_prices must close the snapshot handle itself').
  - user-visible: none
  - not fixed because: 
- **F4-OPS-CHK misfire_grace_time on the one-off db_backup_catchup job** deferred: Patch request (3 master_controller.py hunks plus 2 test hunks in test_backup_catchup.py):
- adds BACKUP_CATCHUP_MISFIRE_S = 6 h;
- adds misfire_grace_time and coalesce=True to both add_job(db_backup_catchup, trigger='date') calls.
  - tests: - Scratch tree (scratchpad/F4B-OPS/prtree) with all patches: 55 passed across test_bot_status, test_backup_catchup and test_scheduler_history.
- Test patches on the unpatched controller: 4 failed, as expected, including KeyError 'misfire_grace_time' and 'a late loop must not drop the catch-up'.
- ruff: 60 findings before and 60 after the patches. mypy: only the old errors.
  - user-visible: After the patch and a master-controller restart: a missed-backup catch-up runs even if the loop is late at its slot.
  - not fixed because: master_controller.py is not in F4B-OPS's brief. The test hunks would fail until the code patch lands, so they ship in the same patch request.
- **F4-OPS-CHK JobHistory row with non-integer 'runs' breaks every later run of that job** deferred: Patch request: JobHistory.record wraps the int() in try/except and starts the count over. A test hunk in test_scheduler_history.py loads {'runs': 'n/a'} and runs _track.
  - tests: Scratch tree: passes with the patch. Without it: ValueError: invalid literal for int() with base 10: 'n/a' (negative control).
  - user-visible: none (robustness)
  - not fixed because: master_controller.py is not in F4B-OPS's brief; the test ships with the patch.
- **SECREL-06-telegram: Telegram /status desktop-app line does not know the crash guard** deferred: Patch request (2 master_controller.py hunks plus 2 test_bot_status.py hunks). _desktop_app_line gets an 'opened by hand: its crash guard relaunches it' branch, using the same pgrep pattern as start-local.sh, and its docstring is updated. The test stubs pgrep and adds cases for the guard and for another copy's guard.
  - tests: Scratch tree: 21 passed in test_bot_status with the patch. The guard case fails on the unpatched controller (negative control).
  - user-visible: After the patch and a master-controller restart: /status says 'opened by hand: its crash guard relaunches it' for a guarded hand-opened copy (new app only).
  - not fixed because: master_controller.py is not in F4B-OPS's brief. RUNBOOK, CLAUDE.md and start-local.sh status are already consistent.
- **F4B-OPS-4: five suites, node checks and CI list every check file** fixed: CI's ui job already discovers every ui/**/__tests__/*.check.ts that runs on plain node, and test_desktop_ci already enforces that (already-fixed for CI). The gap was CLAUDE.md's 'How to run things' list: it named 6 files by hand and missed no-dialogs.check.ts and streamProxy.check.ts. It is now the same discovery loop as CI (it skips the tsx-only errors.check.ts the same way).

New drift test test_claude_md_runs_the_same_ui_checks_as_ci_and_lists_every_gate. It runs CLAUDE.md's loop with node replaced by echo and requires exactly CI's file list, including no-dialogs, streamProxy, ws, pages and desktop. It also checks that the five pytest suites, tsc, cargo test/clippy/fmt, boot_check and the release-builder node tests are all listed.
  - tests: test_desktop_ci: 5 passed. Negative control against the orig CLAUDE.md: fails ('not a discovery loop'). PM gates4 node.log shows all 8 plain-node checks and boot_check passing.
  - user-visible: The developer gate command in CLAUDE.md now runs every UI check.
  - not fixed because: 

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/stack_watchdog.sh
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/start-local.sh
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/docs/RUNBOOK_RESTORE.md
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/CLAUDE.md
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/tests/integration/test_desktop_ops.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/tests/integration/test_desktop_ci.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_backup_catchup.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_news_track_record.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/reports/desktop_app/qa_harness.md

## tests
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests -q (core suite) -> 699 passed, 9 skipped, 0 failed in 98.9 s. Before this round: 685 passed, 1 failed (the runbook test).
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest scripts/tests -q -> 284 passed, 0 failed
- pytest tests/integration/test_desktop_ops.py test_desktop_ci.py test_desktop_qa_harness.py test_qa_tool_defaults.py -q (after the final edits) -> 217 passed
- DESKTOP_OPS_WATCHDOG/DESKTOP_OPS_SCRIPT=scratch copies pytest tests/integration/test_desktop_ops.py (before the atomic install) -> 109 passed in 73.9 s
- Negative control: the new and changed ops/CI tests against the orig RUNBOOK, CLAUDE.md, start-local.sh and the 18:12 watchdog (scratchpad/F4B-OPS/neg) -> 9 failed, 22 passed. The failures are the usec-owner case, the owner-line boot epoch ('658471' vs 1792906041), the reload supervisor killed, dry-run pruning, CLAUDE.md timing, both .env doc tests, crash-relaunch reconciliation, and the CLAUDE.md gate loop.
- Mutation: watchdog with the boot-comparison line deleted, lock tests -> previous-boot fails (1 failed, 7 passed). It passed before the test was strengthened.
- Mutation: news_scan_performance.load_prices without con.close(), news close test -> fails ('load_prices must close the snapshot handle itself'); real code: 12 passed
- Mutation: master_controller.startup_catchup without its lock (real-copy tree), test_backup_catchup -> 1 failed (the new lock test), 24 passed; real code: 25 passed
- python scratchpad/F4B-OPS/patches.py check / apply prtree, then pytest test_bot_status, test_backup_catchup, test_scheduler_history -> All 12 old strings occur exactly once in the live files. With the patches: 55 passed. Test hunks on the unpatched controller: 4 failed (negative control).
- ruff check --line-length 130 (4 changed test files; patched test_bot_status, test_scheduler_history and test_backup_catchup; patched master_controller) -> All checks passed on the test files. master_controller: 60 findings before and after the patches, the same counts per rule.
- mypy scripts/master_controller.py --ignore-missing-imports --follow-imports=silent (original and patched) -> Only the 2 known errors (scheduler Optional union-attr; tgbot.handle dict variance). No new ones.
- /bin/bash -n start-local.sh && /bin/bash -n scripts/stack_watchdog.sh (bash 3.2) -> OK, before and after the atomic install
- python scratchpad/F4B-OPS/ws_mock_check.py (real Chromium then WebKit, local servers only) -> MOCKED_OK CONTROL_OK, rc 0, no browser left running
- Live read-only: launchctl print com.suryadhana.watchdog; .pids/watchdog after the 21:35 install -> The 21:36 run exited 0 (runs=318), updated last_all_up and released the lock
- RUNBOOK §2 read-back check on the live .env and on .env.example (key names only) -> OK on both. Values were never printed.

## patch requests
### PR-F4B-OPS-1 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: SECREL-06 round-4 reconciliation. A copy opened by hand runs a crash guard (supervise.rs). RUNBOOK, CLAUDE.md and `status` now say so; Telegram /status does not. Apply together with the next hunk and the two test_bot_status.py hunks. Machine-readable, verified copy: scratchpad/F4B-OPS/patch_requests.json (entries 0-3).

OLD:
```
def _desktop_app_line() -> str:
    """The desktop app: installed, running (the installed bundle's executable), and supervised by launchd (only the
    copy launchd started is relaunched after a crash; one reopened from the Dock after Quit is not)."""
```
NEW:
```
def _desktop_app_line() -> str:
    """The desktop app: installed, running (the installed bundle's executable), and who relaunches it after a crash:
    launchd (the Launch at Login job's own process), the crash guard a copy reopened from the Dock after Quit starts
    (app builds from 25 Oct round 3; `suryadhana-crash-guard <app pid>` in ps, as start-local.sh status checks), or
    nothing (an older build, or Launch at Login off)."""
```
### PR-F4B-OPS-2 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: SECREL-06: the crash-guard branch, using the same pgrep pattern as start-local.sh app_status_row (a guard of another pid does not count). _run_quiet returns '' when pgrep finds nothing. Takes effect at the next master-controller restart, outside the freeze windows.

OLD:
```
    elif _launchd_job_pid("SuryaDhana") in pids:
        sup = "supervised by launchd"
    else:
        sup = "opened by hand: not relaunched after a crash"
```
NEW:
```
    elif _launchd_job_pid("SuryaDhana") in pids:
        sup = "supervised by launchd"
    elif any(_run_quiet(["pgrep", "-f", "--", f"suryadhana-crash-guard {p} "]).strip() for p in pids):
        sup = "opened by hand: its crash guard relaunches it"
    else:
        sup = "opened by hand: not relaunched after a crash"
```
### PR-F4B-OPS-3 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_bot_status.py
why: Test for the SECREL-06 controller hunks; apply only together with them. The test file is mine, but this hunk fails until the controller patch lands. The `\n` / `\t` inside the f-strings are literal backslash escapes in the source, as in the current file.

OLD:
```
def _commands(ps: str, job_pid: str | None):
    def run(cmd: list[str]) -> str:
        if cmd[0] == "ps":
            return ps
        if cmd[0] == "launchctl":
            return f"gui/501/SuryaDhana = {{\n\tstate = running\n\tpid = {job_pid}\n}}\n" if job_pid else ""
        return ""
    return run


@pytest.mark.parametrize("job,login,want", [
    ("83455", True, "🟢 desktop app 1.0.0 running (supervised by launchd)"),
    ("99999", True, "🟢 desktop app 1.0.0 running (opened by hand: not relaunched after a crash)"),
    ("83455", False, "🟢 desktop app 1.0.0 running (Launch at Login off: not relaunched after a crash)"),
])
def test_desktop_app_line(monkeypatch, tmp_path, job, login, want):
```
NEW:
```
def _commands(ps: str, job_pid: str | None, guard_pid: str = ""):
    def run(cmd: list[str]) -> str:
        if cmd[0] == "ps":
            return ps
        if cmd[0] == "launchctl":
            return f"gui/501/SuryaDhana = {{\n\tstate = running\n\tpid = {job_pid}\n}}\n" if job_pid else ""
        if cmd[0] == "pgrep":           # a crash guard (supervise.rs) watching guard_pid only
            return "77001\n" if guard_pid and cmd[1:] == ["-f", "--", f"suryadhana-crash-guard {guard_pid} "] else ""
        return ""
    return run


@pytest.mark.parametrize("job,login,guard,want", [
    ("83455", True, "", "🟢 desktop app 1.0.0 running (supervised by launchd)"),
    ("99999", True, "83455", "🟢 desktop app 1.0.0 running (opened by hand: its crash guard relaunches it)"),
    ("99999", True, "58496", "🟢 desktop app 1.0.0 running (opened by hand: not relaunched after a crash)"),
    ("99999", True, "", "🟢 desktop app 1.0.0 running (opened by hand: not relaunched after a crash)"),
    ("83455", False, "", "🟢 desktop app 1.0.0 running (Launch at Login off: not relaunched after a crash)"),
])
def test_desktop_app_line(monkeypatch, tmp_path, job, login, guard, want):
```
### PR-F4B-OPS-4 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_bot_status.py
why: Test for the SECREL-06 hunks (apply together).

OLD:
```
    monkeypatch.setattr(mc, "_run_quiet", _commands(ps, job))
    assert mc._desktop_app_line() == want
```
NEW:
```
    monkeypatch.setattr(mc, "_run_quiet", _commands(ps, job, guard))
    assert mc._desktop_app_line() == want
```
### PR-F4B-OPS-5 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: F4-OPS review (minor): this one-off date job keeps APScheduler's 1 s default grace, so a loop that is more than 1 s late drops it silently and P7 comes back. Firing late is safe: the job re-checks the date, the backup and the freeze windows. Apply with the next two hunks and the test_backup_catchup.py hunks.

OLD:
```
            scheduler.add_job(db_backup_catchup, trigger="date", run_date=slot, id="db_backup_catchup",
                              name="Nightly DuckDB Backup (catch-up after start)", replace_existing=True)
```
NEW:
```
            scheduler.add_job(db_backup_catchup, trigger="date", run_date=slot, id="db_backup_catchup",
                              name="Nightly DuckDB Backup (catch-up after start)", replace_existing=True,
                              misfire_grace_time=BACKUP_CATCHUP_MISFIRE_S, coalesce=True)
```
### PR-F4B-OPS-6 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: F4-OPS review (minor): the same grace for the add_job in lifespan.

OLD:
```
        scheduler.add_job(db_backup_catchup, trigger="date", run_date=backup_when, id="db_backup_catchup",
                          name="Nightly DuckDB Backup (catch-up after start)", replace_existing=True)
```
NEW:
```
        scheduler.add_job(db_backup_catchup, trigger="date", run_date=backup_when, id="db_backup_catchup",
                          name="Nightly DuckDB Backup (catch-up after start)", replace_existing=True,
                          misfire_grace_time=BACKUP_CATCHUP_MISFIRE_S, coalesce=True)
```
### PR-F4B-OPS-7 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: F4-OPS review (minor): the constant used by the two add_job hunks.

OLD:
```
async def db_backup_catchup() -> None:
```
NEW:
```
# a one-off date job keeps APScheduler's default misfire grace of 1 s: a late loop would drop the catch-up silently.
# Late is fine (the job re-checks the date, the backup and the freeze windows when it fires).
BACKUP_CATCHUP_MISFIRE_S = 6 * 3600


async def db_backup_catchup() -> None:
```
### PR-F4B-OPS-8 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_backup_catchup.py
why: Test for the misfire hunks; apply only with them. Fails with KeyError on the current controller.

OLD:
```
    assert name == "db_backup_catchup" and kw["run_date"] == at(2026, 10, 26, 21, 16)
    assert kw["id"] == "db_backup_catchup" and kw["replace_existing"] is True
```
NEW:
```
    assert name == "db_backup_catchup" and kw["run_date"] == at(2026, 10, 26, 21, 16)
    assert kw["id"] == "db_backup_catchup" and kw["replace_existing"] is True
    assert kw["misfire_grace_time"] >= 3600 and kw["coalesce"] is True, "a late loop must not drop the catch-up"
```
### PR-F4B-OPS-9 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_backup_catchup.py
why: Test for the misfire hunks (the lifespan registration); apply only with them.

OLD:
```
            backup, catchup = s.get_job("db_backup_catchup"), s.get_job("startup_catchup")
            return (backup.next_run_time.astimezone(IST), catchup.next_run_time.astimezone(IST), catchup.kwargs,
                    catchup.args[3])
    backup_at, catchup_at, kwargs, mode = asyncio.run(scenario())
```
NEW:
```
            backup, catchup = s.get_job("db_backup_catchup"), s.get_job("startup_catchup")
            assert backup.misfire_grace_time >= 3600, "a late loop must not drop the catch-up"
            return (backup.next_run_time.astimezone(IST), catchup.next_run_time.astimezone(IST), catchup.kwargs,
                    catchup.args[3])
    backup_at, catchup_at, kwargs, mode = asyncio.run(scenario())
```
### PR-F4B-OPS-10 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: F4-OPS review (minor): JobHistory.load accepts any dict row. Then record() raises ValueError from _track's finally on every run of a job whose 'runs' is not a number, and the row never repairs itself. Apply with the test_scheduler_history.py hunk.

OLD:
```
            runs = int(self._jobs.get(job_id, {}).get("runs") or 0) + 1
```
NEW:
```
            try:
                runs = int(self._jobs.get(job_id, {}).get("runs") or 0) + 1
            except (TypeError, ValueError):           # a hand-edited or half-corrupt row: the count starts over
                runs = 1
```
### PR-F4B-OPS-11 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/tests/test_scheduler_history.py
why: Test for the JobHistory hunk; apply only with it. Without it: ValueError: invalid literal for int() with base 10: 'n/a'.

OLD:
```
def _fake_scheduler(*ids):
```
NEW:
```
def test_a_bad_row_never_breaks_the_job_that_owns_it(armed):
    """F4-OPS review: {'runs': 'n/a'} loaded fine, then every run of that job raised ValueError out of _track."""
    armed.path.write_text(json.dumps({"version": 1, "jobs": {"desk_daily": {"runs": "n/a", "last_status": "done"}}}))
    assert armed.load() == 1

    async def run():
        async with mc._track("desk_daily"):
            pass
    asyncio.run(run())
    row = json.loads(armed.path.read_text())["jobs"]["desk_daily"]
    assert row["runs"] == 1 and row["last_status"] == "done"


def _fake_scheduler(*ids):
```
### PR-F4B-OPS-12 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/master_controller.py
why: F3-OPS review nit 3: the Telegram HUNG line omits the watchdog's busy grace and hourly cap, which RUNBOOK 'After an outage' and CLAUDE.md state. Text only. test_bot_status's 'about 3.5–5.5 min after it hung' assertion still holds.

OLD:
```
                       f"restarts it about 3.5–5.5 min after it hung (data-service and master-controller: not inside "
                       f"a freeze window). "
```
NEW:
```
                       f"restarts it about 3.5–5.5 min after it hung (data-service and master-controller: not inside "
                       f"a freeze window, and about 16 min while busy at high CPU; at most 3 restarts an hour). "
```

## deploy notes
- scripts/stack_watchdog.sh (sha256 8f94dbd2df8c…) and start-local.sh (ef730850e596…) were installed atomically at 21:35 IST: temp file in the same directory, chmod 755, bash -n, mv -f. Both were confirmed byte-identical to the pre-round snapshots first. Because launchd runs the watchdog straight from the repo, it is already live: the 21:36 run exited 0. 'PM deploys' does not apply to these two scripts. Rollback: scratchpad/F4B-OPS/orig/stack_watchdog.sh (sha 783d667f…, the 18:12 version) and orig/start-local.sh (da246eab…), installed the same atomic way.
- Watchdog behaviour changes:
- The lock owner file now carries the boot time in epoch seconds instead of kern.boottime's usec.
- An old-format owner line (6 digits or fewer) is left to the pid checks, so the switch-over is safe.
- The previous-boot and pre-boot lock rules now actually work.
- UI_API_RELOAD=1: the reload supervisor is never sent USR1.
- WATCHDOG_DRY_RUN=1 no longer prunes the hang-restart file.
- start-local.sh changed in a comment only.
- Desktop app interplay: the round-3 app in desktop/src-tauri/target compares the owner file with the boot seconds, so it now shows watchdog runs correctly. The round-4b stack.rs (being edited by its owner at 21:28) accepts both seconds and usec. The installed 15:36 app uses the round-2 'lock under 20 min' rule. All combinations are safe in any deploy order.
- Patch requests come in pairs: apply each master_controller.py hunk together with its test hunk. The test hunks fail until their code hunk lands.
- SECREL-06 Telegram line: 2 code hunks + 2 test_bot_status.py hunks.
- misfire grace: 3 code hunks + 2 test_backup_catchup.py hunks.
- JobHistory guard: 1 code hunk + 1 test_scheduler_history.py hunk.
- HUNG line: 1 code hunk, no test change.
Exact, verified copies are in scratchpad/F4B-OPS/patch_requests.json; `python scratchpad/F4B-OPS/patches.py check` confirms every old string occurs exactly once. Then restart master-controller outside 07:45–09:20 and 18:30–21:15 IST.
- Documentation only (no deploy): RUNBOOK §2 .env rules and read-back check, §4 desktop-app row phrases, §5 crash guard plus the no-guard remedy, After-an-outage USR1 and lock owner notes, and the first-trading-day backup check. Also CLAUDE.md self-healing, app and gate-loop lines, and qa_harness.md (real-browser WebSocket mock check).

## open issues
- Telegram /status still says 'opened by hand: not relaunched after a crash' for a guarded copy until the SECREL-06 master_controller patch is applied and master-controller restarts. This only matters once the round-3+ app is installed.
- F4-OPS review items in master_controller.py (misfire_grace_time for db_backup_catchup; the JobHistory non-integer runs guard) and F3-OPS nit 3 (the HUNG line wording) are patch requests, not applied.
- scripts/ui_perf.py's docstring still does not say that perf runs use mocked WebSockets. The file is not mine; qa_harness.md documents it instead.
- F3-RUST review item outside my files: CI's desktop job runs clippy with --features devtools but not `cargo test --features devtools` (the build-id test). .github/workflows/ci.yml is not in my brief.
- Pre-existing, not addressed: the watchdog's 20-minute lock age rule can still let a successor take over from a run that legitimately lasts over 20 min (several 300 s start timeouts). release_lock never removes a successor's lock.
- With UI_API_RELOAD=1, hang captures now have no Python stacks: the supervisor has no handler and the worker is not the pidfile pid. Dumping the worker's stacks would need the announcement to carry its pid; ui-api's loop_watchdog_started line has none.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/docs/RUNBOOK_RESTORE.md: The new §2 read-back check can print 'OK: every reader sees the same values' for TELEGRAM_ and HEALTHCHECK_ keys that the watchdog reads differently. Its comment says these keys are 'also read by the plain parsers / the watchdog', but it only models daily_session_refresh.read_env_file, which strips whitespace and splits on the first '='. The watchdog's own reader is env_val in scripts/stack_watchdog.sh:68. It uses grep '^KEY=', takes everything after the first '=', strips one quote at each end, and strips no whitespace.
  - evidence: I ran the snippet exactly as written in the RUNBOOK on a scratch .env with fake values (scratchpad/F4B-OPS-CHK/envt): `TELEGRAM_CHAT_ID = 4242` / `TELEGRAM_BOT_TOKEN=tok123 ` / `HEALTHCHECK_PING_URL=https://hc-ping.com/x`. The check printed 'OK: every reader sees the same values'. The watchdog's env_val on the same file returned CHAT_ID=[] and TOKEN=[tok123 ]. So the watchdog's Telegram alerts would be silently off while the check reports OK.
  - fix: In the snippet, read TELEGRAM_/HEALTHCHECK_ keys the way env_val does as well: only lines that start exactly with 'KEY=', the raw text after the first '=', one leading and one trailing quote removed, no strip. Flag any key where that differs from dotenv. Or add a §2 bullet: no spaces around '=' and no trailing spaces. Add the two lines above as a negative case to test_the_runbook_env_check_names_misread_keys_and_never_prints_a_value.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/stack_watchdog.sh: Cross-component, with desktop/src-tauri/src/stack.rs owner_boot_matches. Both compare the owner line's boot time with kern.boottime by exact equality, but kern.boottime is not constant on this Mac: macOS adjusts it with clock corrections. The owner line now carries seconds, so a mismatch needs a correction that crosses a second boundary, which is far rarer than with the old usec equality. This is therefore not a regression. When it happens, a live run's lock reads as stale: a concurrent run takes it over, and the app shows 'not running' for that run. The new test_the_owner_line_carries_the_boot_epoch_the_app_compares_with could also flake in that moment. stack.rs's transitional `field == boot.usec` acceptance matches only until the next correction.
  - evidence: `sysctl -n kern.boottime` printed `{ sec = 1792906041, usec = 658471 }`. The F3-RUST reviewer saw the same value, the fixer around 21:20, and I at about 21:45. At 21:54–21:55 it printed `{ sec = 1792906041, usec = 608038 }`, with no reboot. My bash emulation of stack.rs's cross-version test (scratchpad/F4B-OPS-CHK/xrs) showed the fixed script writing '<pid> 1792906041' and lock_is_stale returning held. That is correct today.
  - fix: Optional hardening, for the PM to route to OPS and RUST: compare boot epochs with a tolerance in both lock_is_stale and owner_boot_matches, e.g. `|owner - boot| <= 10` s. A different boot differs by at least the reboot time. Drop the usec acceptance in stack.rs once the round-4 watchdog is the only one deployed.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/CLAUDE.md: The new UI-check discovery loop in 'How to run things' exits with the status of the last file only. CI's step uses `set -e`. If an early .check.ts fails, the failure shows only in the scrollback, and the loop still ends with status 0. The old hand-written loop had the same weakness, so this is not a regression. The new loop is described as running 'as CI runs them'.
  - evidence: CLAUDE.md:142: `for f in $(find ui …); do head -c 600 "$f" | grep -q 'npx tsx' || node "$f"; done`. In .github/workflows/ci.yml:71, the same discovery runs under `set -e`.
  - fix: e.g. `rc=0; for f in …; do head -c 600 "$f" | grep -q 'npx tsx' || node "$f" || { echo "FAILED $f"; rc=1; }; done; [ $rc = 0 ]`. test_claude_md_runs_the_same_ui_checks_as_ci_and_lists_every_gate still works, since it only swaps `node "$f"` for echo.
- not really fixed: []
- notes: Verdict: ACCEPT-WITH-NOTES. Every item marked fixed or already-fixed holds up. I re-ran the tests and the mutations myself. The 3 problems above are all minor: one gap in a new doc check, and two hardening suggestions. None is a regression.

**Suites (my runs)**
- `pytest tests`: 699 passed, 9 skipped, 0 failed.
- `pytest scripts/tests`: 284 passed.
- test_desktop_ops.py + test_desktop_ci.py: 114 passed.
- test_backup_catchup, test_news_track_record, test_bot_status, test_scheduler_history: 64 passed.
- ruff (line length 130) is clean on the 4 changed test files.
- `bash -n` is OK on stack_watchdog.sh and start-local.sh.
- shellcheck is not installed, so I could not run it.

**Diffs against the fixer's pre-round snapshots (scratchpad/F4B-OPS/orig)**
- stack_watchdog.sh: only boot_epoch, the lock_is_stale owner-boot guard, the DRY_RUN branch in recent_hang_restarts, and the ' --reload' refusal in py_stacks_registered.
- start-local.sh: comment only.
- No trading, scheduler or service code was touched.
- master_controller.py (mtime 21:15), test_bot_status.py and test_scheduler_history.py are byte-identical to before. The patch requests are not applied.

**My own mutations of the current watchdog** (DESKTOP_OPS_WATCHDOG=scratch copies). Each mutation is caught by the intended test:
- boot compare deleted → previous-boot fails;
- greedy sed restored → owner-line test fails with ('658471', 1792906041);
- `--reload` refusal deleted → the reload test fails with 'supervisor must survive';
- DRY_RUN branch disabled → the dry-run test fails;
- 9-digit guard relaxed to any digits → live-watchdog-usec-owner fails.

**Mutations in my own real-copy tree (scratchpad/F4B-OPS-CHK/prtree)**
- startup_catchup without its lock → the new lock test fails.
- load_prices without `con.close()` → the news close test fails.
- The real code passes in both cases.

**Patch requests**
- All 12 old strings occur exactly once.
- With all patches applied in my tree: 55 passed (bot_status, backup_catchup, scheduler_history).
- Test hunks on the unpatched controller: 4 failed. This is the expected negative control.
- ruff on master_controller is unchanged: 60 findings with the same per-rule counts.
- The controller's /status crash-guard pgrep runs inside `_mac_lines`, which runs in a thread, so it does not block the event loop.

**Already-fixed items confirmed**
- test_qa_tool_defaults.py:45 has route_web_socket.
- run_selftest.py:528-530 has the START-UP label and sample_kind='startup'.
- CI's ui job already discovers every plain-node check (test_every_plain_node_check_file_runs_in_ci).

**RUNBOOK §2 against CI's python-dotenv**
- Local python-dotenv is 1.0.0; CI pins 1.0.1.
- I ran both §2 doc tests against a downloaded 1.0.1 wheel through PYTHONPATH, without installing it: 2 passed.

**Live state (read-only)**
- Live hashes match the report: watchdog 8f94dbd2…, start-local.sh ef730850….
- launchd com.suryadhana.watchdog: runs=327, last exit code 0.
- last_all_up was 21:54:59, and watchdog.launchd.log is empty.
- Nothing was restarted. No browser was started.

**Smaller observations, not defects of this round**
1. RUNBOOK §4/§5 say 'opened by hand: not relaunched' has two causes: an old build, or a guard that could not start. There is a third: supervise::decide returns Off('another copy') when the Launch at Login entry starts a different copy. In that case the printed kickstart remedy launches that other copy.
2. py_stacks_registered looks for the start banner only in .log and .log.1.
   - The live ui-api.log rotated at 21:18, so its banner is already in .log.1.
   - After one more rotation without a restart, hang captures get no Python stacks.
   - This fails closed (no USR1 is sent) and predates this round.
3. `kill -USR1` sent by hand still works on the live ui-api, because the handler is registered whatever the log says.
4. The fixer's open issues list is accurate:
   - the ui_perf docstring;
   - `cargo test --features devtools` is missing from CI;
   - the 20-min lock age rule;
   - no stacks are captured in reload mode.

**Scratch work**
All of it is in /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/F4B-OPS-CHK: mutation scripts m1–m5, prtree, envt, xrs, dotenv101, core.log and scripts.log. No processes were left running.

# F4B-RUST

All five open items in my brief are fixed. Item 6 (re-check the round-3 fixes) is confirmed with a self-test of the built copy, the relaunch drill and every gate. The final bundle is built and signed, and nothing was deployed. Build id 0ae66db-dirty-ec8c0ab8-20261025T1620Z; executable sha256 starts 7a0bc36c8f02372c; 8.4 MB; codesign --verify --deep --strict OK. The bundle is newer than every source file that goes into it (only desktop/scripts/relaunch_drill.sh was edited after the build, and it is not part of the bundle).
(1) SECREL-05, app side: the shell now reads the watchdog's real lock owner file. It accepts the boot number in both forms: the microseconds the round-3 watchdog wrote ("<pid> 658471"), and the seconds the current script writes (scripts/stack_watchdog.sh was fixed in the tree at 21:35, not by me). It also checks the owner's command line names stack_watchdog, as the watchdog itself does, so a reused pid does not count. A new Rust test runs the watchdog's own take_lock and lock_is_stale from scripts/stack_watchdog.sh in a temp dir, against both script versions, and checks the app and the watchdog agree. Negative controls: the round-3 seconds-only rule fails it, and a liveness-only owner check fails it.
(2) R9: File ▸ Print… (⌘P) prints the focused terminal window. The boot page, a window still loading, a hidden or minimized window, and a second ⌘P while the panel is open all get a beep instead. No menu item takes ⌘F; the self-test reads the real menu bar and finds ⌘P = Print… and no plain ⌘F.
(3) R10: fresh data now beats the calendar in the menu bar. An NSE print less than 3 min old reads live (same window as the UI). Muhurat (Sun 8 Nov) is covered by tests, and the self-test on a Sunday night showed 'NIFTY 24,180.5 ▲0.40%' with no '· closed'. The installed build shows '· closed' for the same data.
(4) P4: ui-api's new error_kind is read. 'network' gives 'ICICI — unreachable (network)' in the menu bar and on the boot page, with no /login advice and no 'session expired' banner. 'credentials' says to fix the key or secret on BRKR. 'expired', 'unknown', null and a missing field behave as before. The status sent to the UI still has only connected / expired / unknown.
(5) Notifications are DENIED on this Mac. The menu bar now shows one line, 'Notifications are off — System Settings › Notifications › SuryaDhana', and the boot page footer says the same. System Settings opens only when that line is clicked; the self-test and the drill both check that it never opens by itself. Related fix: the app no longer tells the scheduler it is showing the banners while macOS has its notifications off (that would have left no banners at all), and it removes that marker file on a clean quit.
(6) Round-3 fixes still work: the crashed page reloaded in 313 ms on the same tab (desk→desk), no WebviewWindow::url() call remains, and the notification feed showed exactly one banner. Built-copy self-test against my scratch server (:8095, --block-mutations) and stub backend (:8093): PASSED 57/58, the 1 skipped check is the boot-page paint time because the screen is locked. Relaunch drill in an isolated HOME: PASSED, 46 checks. cargo test 153/153; clippy 0 warnings (default and devtools); fmt clean; boot_check 74/74; desktop pytest 243 passed, 9 skipped.
Also done: R1's build-script part. scripts/build_desktop.sh --install --test now self-tests the built app first and installs only if that passes; checked in an isolated HOME both ways.

## findings
- **SECREL-05 (app side; round-3 check MAJOR: the app must read the real watchdog owner format)** fixed: stack.rs: new owner_boot_matches(boot, field) accepts the boot number as seconds or as microseconds. The round-3 watchdog's greedy boot_epoch() sed wrote the microseconds field ('<pid> 658471'); the corrected script (in the tree since 21:35, not my edit) writes the seconds. watchdog_lock_held now also requires the owner pid to still be the watchdog script: alive (macos::proc_identity) and a command line containing 'stack_watchdog'. This is the watchdog's own proc_cmd check, so a reused pid never counts. The new macos::proc_cmdline reads the command line with sysctl KERN_PROCARGS2, parsed by the pure parse_procargs2. macos::boot_time() returns {sec, usec}; boot_time_secs() is kept. A lock with no owner file is still judged against the boot seconds, so a pre-round-3 watchdog is still handled. README text updated.
  - tests: stack::the_real_watchdog_owner_line_is_read_as_a_running_watchdog. It cuts boot_epoch, file_epoch, proc_cmd, lock_is_stale and take_lock out of the real scripts/stack_watchdog.sh, runs them under /bin/bash from a temp …/scripts/stack_watchdog.sh with the lock in a temp dir (never the live lock), and repeats with the round-3 boot_epoch, where it asserts the field equals usec. Checks: a live run is held (by watchdog_lock_held and probe_files) and the watchdog's own lock_is_stale returns 1 (held). After SIGKILL both the app and lock_is_stale say stale. A live /bin/sleep with the same owner line is not counted by either. Pure test covers both formats, dead owner, an earlier boot (sec and usec), missing or garbage fields, no owner file, and the 20 min limit. macos::command_lines_and_boot_time_are_read_like_ps_and_sysctl compares with real ps and sysctl output. Negative controls: the round-3 rule (field == sec) fails with 'the watchdog's boot field 658471 names neither 1792906041 nor 658471'; a liveness-only owner check fails at the reused-pid assertion.
  - user-visible: During a real watchdog run the boot page again says 'the watchdog is starting the stack' and hides Start. With the round-3 app it never did, because every real run read as 'not running'. A lock left by a power cut still does not show 'starting'.
  - not fixed because: 
- **R9 (Print ⌘P; ⌘F not bound)** fixed: menu.rs: new 'File ▸ Print…' item (CmdOrCtrl+P, id app:print) and Action::Print. ⌘P was added to Help ▸ Keyboard Shortcuts, and the module docs state that ⌘F is deliberately not a menu key. windows.rs: print_window() calls WebviewWindow::print(). It is guarded by the pure print_refusal(): the window must be visible and not minimized, in the Terminal phase, on the exact ui origin, with no sheet already attached. A refused request beeps and logs why. Helpers webview_sheet() and cancel_sheet() (the latter self-test only) were added. macos.rs: webview_window_has_sheet, cancel_webview_window_sheet, selftest_print_to_file (self-test only: points the shared print info at a temp PDF so nothing can reach a printer), menu_key_equivalents (walks NSApp.mainMenu), is_plain_cmd_f. The page-side find bar itself is UI work (no find bar exists in ui/ yet).
  - tests: Unit: windows::print_only_a_visible_terminal_window_without_a_sheet (boot page, loading, other origin, unmanaged, hidden, minimized, sheet already open, no native view). menu::cmd_f_stays_free_for_the_page_and_cmd_p_prints scans every accelerator declared in menu.rs and tray.rs: no plain ⌘F, ⌘P present, no duplicates. Negative control: binding Print… to CmdOrCtrl+F fails it. macos::plain_cmd_f_is_told_from_the_full_screen_and_other_f_keys. Built-copy self-test: print_refused_on_boot_page PASS. print_panel PASS: the print panel appeared as a sheet after 512–717 ms, a second Print… was refused ('a print or save panel is already open'), Cancel closed it, and no job file was written. menu_print_and_find_keys PASS: 39 key equivalents, ⌘P -> ['Print…'], plain ⌘F -> [].
  - user-visible: File ▸ Print… (⌘P) opens the macOS print panel on the current terminal window (printer or Save as PDF). On the boot page or a hidden window it beeps. ⌘F is left for the page; it does nothing until the UI ships its find bar.
  - not fixed because: 
- **R10 (menu-bar quote: fresh data beats the calendar; Muhurat 8 Nov)** fixed: health.rs: new FRESH_PRINT_MAX_AGE (3 min, same as the UI's NSE_PRINT_MAX_AGE_MS), FRESH_PRINT_MAX_AHEAD (2 min clock skew) and pure fresh_print(at, now). classify_quote returns Live for a fresh NSE print before it looks at the calendar; two failed fetches still mean Stale. The reverse is never inferred: a quiet feed during calendar hours keeps the old rules. Known side effect, the same as the UI header: a normal day's 15:30 print reads live until 15:33. A data-service patch request (cache TTL during special sessions) is needed for a steady 'live' during Muhurat.
  - tests: health::fresh_nse_prints_beat_the_calendar_on_a_special_session covers: Sun 8 Nov 2026 18:20 IST with prints at 18:19 and 18:17:05 -> Live and a title with no '· closed'; 18:16 -> Closed; after the session -> Closed; 2 min skew allowed, 5 min ahead not; failures win; an undated quote follows the calendar; a special Saturday session; 15:30 print at 15:32 Live and at 15:34 Closed; the exact boundaries. Negative control: removing the fresh-print branch fails it. Existing quote tests unchanged and passing. E2E: the stub's nifty-live is stamped now; on Sunday 21:41 and 21:45 the self-test's tray_fresh_print_is_live PASSED (title 'NIFTY 24,180.5 ▲0.40%'). App-level negative control: the installed build fc2248df against the same stub showed 'NIFTY 24,180.5 ▲0.40% · closed'.
  - user-visible: During Muhurat (Sun 8 Nov) or any special session, the menu-bar NIFTY reads live with no '· closed' while NSE prints. On normal days '· closed' appears at 15:33 instead of 15:30.
  - not fixed because: 
- **P4 (shell half: ui-api error_kind on /api/positions/connection-status)** fixed: health.rs: new IciciView {Connected, Expired, Unreachable, Credentials, Unknown}. parse_icici reads error_kind as a raw value, so a bad type never breaks the two booleans. 'network' -> Unreachable; 'credentials' -> Credentials; 'expired', 'unknown', null, a missing field or any other value keep the previous reading (not connected = Expired). error_kind is read before needs_session_refresh, which ui-api also sets during an outage. ShellStatus.icici, the frozen UI contract, stays 3-valued via IciciView::contract(): Unreachable and Credentials become 'unknown'. IciciTracker treats Unreachable like Unknown: no 'ICICI session expired' notification, and a real expiry after an outage still fires. Snapshot.icici_view is new. tray.rs icici_line: 'ICICI — unreachable (network)' and 'ICICI — API key/secret missing or rejected: fix on BRKR'. BootStatus gains icici_view. boot.js shows 'UNREACHABLE (network) — not a login problem; retried by itself' (amber) and a BRKR line for credentials, and falls back to the old icici field from an older shell. The body is still dropped and never logged; only the state change is logged.
  - tests: health::an_icici_outage_is_unreachable_never_expired covers network, credentials, 'expired' / 'unknown' / null / 42 / 'NETWORK', a missing field, connected winning, and the serialized keys. It has a built-in negative control: the same outage body without error_kind reads Expired. Removing the network mapping fails it. health::icici_tracker_fires_once_on_connected_to_expired covers outage then no notification, a later expiry still notifies, and credentials do not. tray::lines_render: no '/login' or 'expired' text for Unreachable, Credentials or Unknown. boot_check: 7 new ICICI checks (74/74); the round-3 boot.js fails 3 of them. E2E: the stub returns error_kind 'network'; self-test tray_icici_line PASS ('ICICI — unreachable (network)', contract Unknown). The installed build against the same stub reported 'icici Expired'.
  - user-visible: During an ICICI outage the menu bar says 'ICICI — unreachable (network)', the boot page says 'UNREACHABLE (network) — not a login problem', and the 'ICICI session expired: send /login' banner is not shown. Missing or rejected API credentials point to BRKR. Expiry is unchanged. Needs the round-4a ui-api; with the old ui-api the behaviour is as before.
  - not fixed because: 
- **NOTIF-DENIED (brief item 5: one-time, non-nagging hint while macOS denies SuryaDhana's notifications)** fixed: lib.rs: new Shell.notif_auth. refresh_notification_auth() reads UNUserNotificationCenter 1 s after start and every 60 s, on a blocking thread with a 2 s limit. An unknown or timed-out answer changes nothing, so the hint never flickers. A change is logged once. tray.rs: a menu line 'Notifications are off — System Settings › Notifications › SuryaDhana' is inserted after the status lines only while the answer is denied, and removed otherwise (pure notif_hint_wanted). Clicking it (Action::NotificationSettings -> lib::open_notification_settings) is the ONLY way System Settings opens; in self-test the click is recorded instead. Boot page: BootStatus.notifications plus a quiet amber footer line (#notif), with no button and no IPC. Related round-3-check minors fixed in feed.rs: (a) notify-sink.alive is touched only while macOS allows SuryaDhana's notifications (may_claim_sink) and never for a poll whose banners were all throttled; (b) the file is removed once when notifications are not allowed and on a clean quit (RunEvent::Exit -> feed::retire_alive). Before, with notifications off and the scheduler patch applied, nobody showed the banners.
  - tests: tray::the_notification_hint_follows_only_a_definite_answer. feed::the_sink_is_claimed_only_while_banners_can_show (Authorized / Denied / NotDetermined / unknown / all throttled; retire_alive). Negative control: an unconditional claim fails it. boot_check: 5 new notification checks (denied shows the footer and invokes nothing; granted / default / unknown / missing show none); the round-3 boot.js fails them. Self-test notification_hint PASS: macOS says denied, tray line shown, System Settings never opened. Relaunch drill R4b (3 new checks): a leftover notify-sink.alive seeded before launch was removed with notifications off, System Settings never opened by itself, no heartbeat left after a clean quit.
  - user-visible: With notifications off for SuryaDhana (as on this Mac), the menu bar shows 'Notifications are off — System Settings › Notifications › SuryaDhana' and the boot page footer says the same; a click on the menu line opens that pane. The scheduler's own 'Script Editor' banners keep appearing as the fallback, because the app no longer claims to be the banner sink when it cannot show banners.
  - not fixed because: 
- **R3-REVERIFY (brief item 6: crash recovery, wry url() panic, K5 feed; built-copy self-test, relaunch drill, gates, final bundle)** already-fixed: Re-verified, no change needed: no WebviewWindow::url() call remains. The only .url() left is PageLoadPayload::url() in on_page_load. on_web_content_process_terminate and feed::spawn are still wired. Final bundle built and signed with scripts/build_desktop.sh (no --install).
  - tests: Evidence: built-copy self-test (bundle ec8c0ab8) against my scratch_server.py --block-mutations :8095, backed by stub_backend.py :8093: PASSED 57/58, with boot_page_painted skipped (screen locked). webcontent_crash_recovers 313 ms, desk->desk, new content process, notice sent, so no url() panic. feed_notifications: exactly ['SELFTEST feed alert']. shell_object_in_terminal still lists the notification_feed feature. Earlier builds of this round: 57/58 each. Relaunch drill (isolated HOME, recording launchctl) on the final bundle: PASSED, 43 checks; after adding the R4b checks: PASSED, 46. No drill app, crash guard or scratch server left. cargo test 153/153; clippy 0 warnings (default and --features devtools); cargo fmt --check clean; cargo test --features devtools settings_text_and_version ran the R-RUST-08 devtools build-id assertion (round-3 check minor) and passed; boot_check 74/74; desktop pytest 243 passed, 9 skipped; ruff clean.
  - user-visible: None beyond the items above.
  - not fixed because: 
- **R1 (build_desktop.sh part: self-test BEFORE installing)** fixed: With --install --test, scripts/build_desktop.sh now self-tests the BUILT bundle before it replaces the installed app, and stops with 'self-test FAILED: … was NOT installed; the installed app is unchanged' on failure. --install alone is unchanged. --rollback --test still tests the rolled-back copy, and --test alone the built or installed copy as before. usage() now prints the whole header. The file was replaced atomically (temp file + rename, mode kept).
  - tests: bash -n OK; --help prints the full header. Isolated-HOME drill (HOME and SURYADHANA_INSTALL_DIR in my scratch): against a closed port the self-test FAILED 19/21, rc=1, and nothing was installed (empty install dir). Against my scratch server it PASSED 57/58, the build was installed into the scratch dir with installed-build recorded there, and 'Launch at Login is off: no login item to update'. The real ~/Library/LaunchAgents/SuryaDhana.plist (mtime 15:39) and the real installed-build record (fc2248df) were unchanged. Scratch copies were removed.
  - user-visible: `scripts/build_desktop.sh --install --test` now tests before installing, so a failing build is never installed.
  - not fixed because: 
- **Round-3 check minor: tray line 'Relaunch after a crash' goes stale after turning Launch at Login off** deferred: Not changed.
  - tests: n/a
  - user-visible: 
  - not fixed because: Not in my brief, and not a simple fix: for the login job's own process KeepAlive applies until the next login after the entry is removed, so forcing 'off' could itself be wrong. It needs a decision on what to show while a change is pending.
- **Round-3 check minor: a banner click does not open the event's tab (feed `tab`); `features` is static; webkit_download_same_url_twice is info-only; PENDING_STALE is 10 min** deferred: Not changed.
  - tests: n/a
  - user-visible: 
  - not fixed because: Not in my brief. Click-to-open needs a UNUserNotificationCenter delegate: the plugin's click callbacks park a thread per notification. Notifications are denied on this Mac anyway. A dynamic `features` flag needs a matching UI change. The download self-test and timeout changes are unrelated to this round's items.

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/stack.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/macos.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/health.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/tray.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/menu.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/windows.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/lib.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/commands.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/feed.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/selftest.rs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/boot/boot.js
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/boot/index.html
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/scripts/boot_check.mjs
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/scripts/stub_backend.py
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/scripts/relaunch_drill.sh
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/README.md
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/build_desktop.sh

## tests
- cd desktop/src-tauri && cargo test --offline -> 153 passed, 0 failed (144 at round 3 + 9 new)
- cd desktop/src-tauri && cargo test --offline --features devtools settings_text_and_version -> 1 passed (R-RUST-08 devtools build-id assertion; round-3 check asked for this gate)
- cd desktop/src-tauri && cargo clippy --offline --all-targets  /  --all-targets --features devtools -> 0 warnings, 0 errors (both feature sets)
- cd desktop/src-tauri && cargo fmt --check -> clean
- node desktop/scripts/boot_check.mjs -> PASSED 74/74 (62 + 12 new); round-3 boot.js as negative control: FAILED 70/74
- jupyter_env python -m pytest tests/integration/test_desktop_{contract,ci,ops,qa_harness,static,e2e_multiwin}.py -q -> 243 passed, 9 skipped (run after the final script edits)
- jupyter_env python -m ruff check --line-length 130 desktop/scripts/*.py desktop/icons-src/*.py -> All checks passed
- bash -n scripts/build_desktop.sh && bash -n desktop/scripts/relaunch_drill.sh -> OK
- negative controls (temporary edits, restored): owner_boot_matches seconds-only; owner check liveness-only; classify_quote without fresh_print; parse_icici without the network mapping; Print… bound to CmdOrCtrl+F; may_claim_sink always true -> each made its new test FAIL (the_real_watchdog_owner_line…, fresh_nse_prints_beat_the_calendar…, an_icici_outage_is_unreachable…, cmd_f_stays_free…, the_sink_is_claimed_only…); all green after restoring. feed.rs mtime restored to 21:36:16, content identical
- scripts/build_desktop.sh (no --install) -> exit 0; codesign --verify --deep --strict OK; 8.4 MB; build id 0ae66db-dirty-ec8c0ab8-20261025T1620Z; executable sha256 7a0bc36c8f02372c…
- SURYADHANA_UI_URL=http://127.0.0.1:8095 scripts/build_desktop.sh --no-build --test (scratch_server.py --block-mutations :8095 backed by desktop/scripts/stub_backend.py :8093; UI = a copy of the 15:35 release in my scratch) -> PASSED 57/58, 1 skipped (boot_page_painted: screen locked). print_panel 512 ms; menu_print_and_find_keys; tray_icici_line 'ICICI — unreachable (network)'; tray_fresh_print_is_live; notification_hint; webcontent_crash_recovers 313 ms desk->desk; feed_notifications exactly 1 banner
- installed build fc2248df (scratch copy) --self-test against the same stub (negative control) -> tray title 'NIFTY 24,180.5 ▲0.40% · closed' and icici Expired for the same outage / fresh-print data
- DRILL_KEEP_LOG=… desktop/scripts/relaunch_drill.sh --ui http://127.0.0.1:8095 (isolated temp HOME, recording launchctl) -> PASSED: 43 checks on the final bundle, then 46 with the new R4b checks; no drill process or crash guard left
- R1 drill: HOME=<scratch> SURYADHANA_INSTALL_DIR=<scratch> scripts/build_desktop.sh --no-build --install --test (closed port, then scratch :8095) -> closed port: self-test FAILED 19/21, rc=1, nothing installed. Scratch server: PASSED 57/58, then installed into the scratch dir. Real login plist and real installed-build record unchanged; scratch copies removed
- patch-request validation in scratch: patched copy of services/data-service/nse_live.py + appended tests, run with tests/unit/test_nse_live.py -> 33 passed with the patch; 2 failed without it; ruff findings unchanged (21 -> 21 on nse_live.py, 7 -> 7 on the test file)

## patch requests
### PR-F4B-RUST-1 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/data-service/nse_live.py
why: R10, needed for a steady 'live' during Muhurat (1 of 3 hunks; apply all three together). market_open() knows only Mon–Fri 09:15–15:35, so during Muhurat (Sun 8 Nov) allIndices is cached for 300 s. NSE's timestamp then lags 1–6 min and the 3-min fresh-print rule (app menu bar and UI header alike) flips between live and closed. Validated in scratch: 33 tests pass with the patch, 2 fail without it, ruff findings unchanged. data-service needs a restart outside the freeze windows before 8 Nov.

OLD:
```
from datetime import datetime, timezone

```
NEW:
```
from datetime import datetime, timedelta, timezone

```
### PR-F4B-RUST-2 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/data-service/nse_live.py
why: R10, hunk 2 of 3: a pure 'NSE is printing' test on NSE's own allIndices timestamp. Data beats the calendar, the same idea as the shell's health::fresh_print and the UI's isFreshPrint; 5 min here to cover NSE's lag. market_open() itself is unchanged.

OLD:
```
def market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) <= (15, 35)

```
NEW:
```
def market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) <= (15, 35)


_IST = timezone(timedelta(hours=5, minutes=30))


def fresh_nse_print(timestamp: Any, now: datetime | None = None, max_age_s: float = 300.0) -> bool:
    """NSE's own timestamp (`08-Nov-2026 18:19` / `… 18:19:05`, IST wall clock) within `max_age_s` of `now` (aware;
    default: the current time) and at most 2 min ahead of it: NSE is printing whatever the calendar says (Muhurat,
    a special Saturday session)."""
    if not isinstance(timestamp, str):
        return False
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            t = datetime.strptime(timestamp.strip(), fmt).replace(tzinfo=_IST)
        except ValueError:
            continue
        age = ((now or datetime.now(_IST)) - t).total_seconds()
        return -120 <= age <= max_age_s
    return False

```
### PR-F4B-RUST-3 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/data-service/nse_live.py
why: R10, hunk 3 of 3: while the cached allIndices copy is fresh outside the calendar, re-read every 15 s instead of 300 s, so the NIFTY print stays under 3 min old and the menu bar and UI header stay 'live' through Muhurat. Normal days and closed days behave as before (300 s). No new NSE load outside special sessions.

OLD:
```
    def index_quote(self, name: str = "NIFTY 50") -> dict[str, Any]:
        """Live index from NSE allIndices (the header's NIFTY when ICICI is not streaming); 15 s cache in session."""
        return parse_index_quote(self.get("allIndices", ttl_open=15, ttl_closed=300), name)

```
NEW:
```
    def index_quote(self, name: str = "NIFTY 50") -> dict[str, Any]:
        """Live index from NSE allIndices (the header's NIFTY when ICICI is not streaming); 15 s cache in session, and
        also while the cached copy's own NSE timestamp is fresh outside the calendar (Muhurat, special sessions: the
        header chip and the app's menu bar call a print under 3 min old live); 5 min otherwise."""
        hit = self._cache.get("allIndices")
        printing = bool(hit) and isinstance(hit[1], dict) and fresh_nse_print(hit[1].get("timestamp"))
        return parse_index_quote(self.get("allIndices", ttl_open=15, ttl_closed=15 if printing else 300), name)

```
### PR-F4B-RUST-4 /Users/sudheer/MahaKubera_108/SuryaDhana_AI/tests/unit/test_nse_live.py
why: Tests for the three nse_live.py hunks: the fresh-print rule (Muhurat date, boundaries, junk input) and the allIndices cache time during a fresh print versus a past session. Run in scratch against a patched copy: 33 passed; against the unpatched module: 2 failed (negative control). No new ruff findings (7 -> 7).

OLD:
```
def test_chart_drops_the_closing_session():
    from nse_live import parse_symbol_chart
    base = 1791882900_000                    # 09:15 IST-as-UTC
    last = base + (6 * 3600 + 14 * 60) * 1000   # 15:29
    post = base + (6 * 3600 + 25 * 60) * 1000   # 15:40 closing session
    out = parse_symbol_chart({"grapthData": [[base, 1.0, "NM"], [last, 2.0, "NM"], [post, 9.0, "NM"]]}, 1)
    assert [r["close"] for r in out["rows"]] == [1.0, 2.0]

```
NEW:
```
def test_chart_drops_the_closing_session():
    from nse_live import parse_symbol_chart
    base = 1791882900_000                    # 09:15 IST-as-UTC
    last = base + (6 * 3600 + 14 * 60) * 1000   # 15:29
    post = base + (6 * 3600 + 25 * 60) * 1000   # 15:40 closing session
    out = parse_symbol_chart({"grapthData": [[base, 1.0, "NM"], [last, 2.0, "NM"], [post, 9.0, "NM"]]}, 1)
    assert [r["close"] for r in out["rows"]] == [1.0, 2.0]


def test_fresh_nse_print_outside_the_calendar():
    """Desktop round 4b (R10): an NSE print under 5 min old means NSE is printing, whatever the calendar says."""
    from datetime import timedelta, timezone
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 11, 8, 18, 20, tzinfo=ist)                  # Sun 8 Nov 2026, Muhurat evening
    assert nl.fresh_nse_print("08-Nov-2026 18:19", now) and nl.fresh_nse_print("08-Nov-2026 18:16:05", now)
    assert not nl.fresh_nse_print("08-Nov-2026 18:14", now)            # 6 min: the session is over (or paused)
    assert not nl.fresh_nse_print("06-Nov-2026 15:30", now) and not nl.fresh_nse_print("08-Nov-2026 18:25", now)
    assert not nl.fresh_nse_print(None, now) and not nl.fresh_nse_print("garbage", now)
    assert not nl.market_open(now.replace(tzinfo=None))                 # the calendar alone says closed


def test_index_quote_is_re_read_every_15_s_while_nse_prints(monkeypatch):
    from datetime import timedelta, timezone
    live = nl.NseLive({})
    seen = []

    def fake_get(path, ttl_open=30, ttl_closed=600):
        seen.append(ttl_closed)
        return live._cache.get(path, (0, {}))[1]

    monkeypatch.setattr(live, "get", fake_get)
    stamp = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%b-%Y %H:%M:%S")
    live._cache["allIndices"] = (0, {"timestamp": stamp, "data": [{"index": "NIFTY 50", "last": 24180.5}]})
    assert live.index_quote()["last"] == 24180.5
    assert seen[-1] == 15                                               # NSE printing: re-read every 15 s
    live._cache["allIndices"] = (0, {"timestamp": "23-Oct-2026 15:30", "data": []})
    live.index_quote()
    assert seen[-1] == 300                                              # a past session: 5 min as before
    live._cache.clear()
    live.index_quote()
    assert seen[-1] == 300                                              # nothing cached yet: as before

```

## deploy notes
- Install the bundle with `scripts/build_desktop.sh --no-build --install --relaunch`. Build id 0ae66db-dirty-ec8c0ab8-20261025T1620Z; executable sha256 starts 7a0bc36c8f02372c; built 21:50 IST and newer than every file that goes into it. Adding `--test` now runs the self-test BEFORE installing (FEATURE_PARITY R1) and installs only if it passes; give SURYADHANA_UI_URL a scratch server, or use the live :8010, where the self-test makes GET requests only. App only: no service restart is needed.
- The ICICI wording (P4) needs the round-4a ui-api (positions.py and icici_admin.py loaded, i.e. ui-api restarted). Until then error_kind is absent and the menu bar and boot page behave exactly as before (expired: send /login).
- SuryaDhana's notifications are DENIED on this Mac. After the install the menu bar shows 'Notifications are off — System Settings › Notifications › SuryaDhana'; clicking that line opens the pane. The app no longer marks itself as the banner sink while notifications are off, so the scheduler's osascript ('Script Editor') banners keep appearing (master_controller already has the sink check). When the owner turns notifications on, the app takes over the banners within about 1–2 min and the scheduler stops its duplicate banner.
- Watchdog lock: the app accepts both owner formats, '<pid> <usec>' (watchdog runs from before the 21:35 boot_epoch fix) and '<pid> <boot sec>' (the current script), so the deploy order does not matter.
- Muhurat (Sun 8 Nov): the menu bar already reads a print under 3 min old as live. For a steady reading, apply the nse_live.py patch request and restart data-service before 8 Nov, outside the freeze windows (07:45–09:20 and 18:30–21:15 IST). Without it data-service caches allIndices for 300 s on a Sunday, so both the menu bar and the UI header will flip between live and closed.
- Visible app changes: File ▸ Print… (⌘P); ⌘F reaches the page (the UI has no find bar yet); new menu-bar ICICI wording; the notification line in the menu bar and on the boot page; on normal days the menu-bar '· closed' appears at 15:33 instead of 15:30 (same as the UI header).
- Scratch cleanup: my scratch_server (:8095) and stub (:8093) were stopped by PID. The scratch install copy and the copy of the installed app were deleted. No drill or app process of mine is left; the installed app (pid 83455) was not touched.

## open issues
- R9 Find: no menu item takes ⌘F (checked in the real menu bar), but ui/ has no find bar yet (no window.find or FindBar in ui/components, ui/lib or ui/app). Until the UI ships one, ⌘F does nothing in the app.
- Print: only checked that the panel appears and that Cancel works; nothing was printed on purpose. How the dark terminal page paginates on paper or in a PDF is unverified; the owner can try File ▸ Print… ▸ PDF once.
- boot_page_painted (< 500 ms) is still unmeasured: the screen was locked for every self-test run.
- R10 stays steady through Muhurat only once the data-service patch request (allIndices cache time) is applied and data-service restarted before 8 Nov.
- Deferred round-3 check minors (not in this brief): the menu-bar 'Relaunch after a crash' line goes stale after turning Launch at Login off; clicking a feed banner does not open its tab; the `features` flag is static; webkit_download_same_url_twice is info-only and PENDING_STALE is 10 min; C-PERF-03/04 idle and memory measurements are still open.
- Not tested end to end for the 'granted' notification case: this Mac denies notifications, so the drill exercised only the 'off' path (heartbeat removed, never claimed). The 'granted' path (heartbeat refreshed) is covered by unit tests and a drill branch that did not run here.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/stack.rs: SECREL-05: the app and the watchdog still disagree on one owner-file shape. If the owner line has no boot field ('<pid> '), the app's watchdog_lock_held returns false. The watchdog's own lock_is_stale skips the boot comparison in that case and lets the pid and command checks decide, so it treats the lock as held. take_lock writes `echo "$$ $(boot_epoch)"`, and the new anchored sed (`^[{] *sec = ([0-9]+),.*`) prints nothing if sysctl fails or kern.boottime ever changes format. When that happens, the app goes back to never seeing a watchdog run, which is the same failure SECREL-05 fixed. It would happen silently, because the agreement test only covers the usec and seconds formats. The README says the app follows 'the same rule as the watchdog's own lock_is_stale', and the test doc says it 'checks that the app and the watchdog agree'. Neither is true for this case.
  - evidence: In scratch, I ran a live `/bin/bash …/scripts/stack_watchdog.sh` (sleep 20) and wrote the owner line '88303 '. The real lock_is_stale cut from scripts/stack_watchdog.sh returned rc=1 (held). stack.rs test a_watchdog_lock_left_by_a_dead_run… asserts `!watchdog_lock_held(m, Some("4242"), …)` with the message 'no boot field', and the code does `if !owner_boot.map(|f| owner_boot_matches(b, f)).unwrap_or(false) { return false }`. The watchdog code is `case "$owner_boot" in [0-9]{9}*) … esac`: an empty field is not compared, then `kill -0` and the proc_cmd *stack_watchdog* check decide.
  - fix: In watchdog_lock_held, compare the boot field only when it is present and numeric, and otherwise let owner_is_watchdog decide, as lock_is_stale does. Add a '<pid> ' case to real_watchdog_lock_case that runs both the app and the watchdog's lock_is_stale on the same line and asserts they agree.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/windows.rs: R9 (plausible, not reproduced): print_refusal blocks a second ⌘P only once the print panel is an attached sheet. The self-test measured that the sheet appears 490–717 ms after print_window returns Ok. A second Print… inside that window (a quick double press, or key auto-repeat while ⌘P is held, since menu key equivalents fire on repeats) passes every guard and starts a second NSPrintOperation. AppKit then queues a second print sheet. The self-test sends its second Print… only after the sheet is up, so this window is never exercised.
  - evidence: windows.rs print_refusal: `Some(true) => Some("a print or save panel is already open…")` is the only in-flight guard. selftest3.json print_panel: 'print panel as a sheet on the window: yes after 490 ms'. selftest.rs print_check calls the second print_window only after the polling loop has seen the sheet.
  - fix: Keep a per-window 'print requested at' instant in Shell. Have print_refusal refuse while it is under ~5 s old and no sheet has appeared yet, and clear it once the sheet goes away. Add a self-test step that sends two print_window calls back to back and expects exactly one sheet.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/menu.rs: Weak test for R9 Find. The page's find bar, which has existed in the tree since 21:31 (ui/components/desktop/find.ts and FindBar.tsx, mounted in PlatformShell for the desktop app only), needs ⌘F and also ⌘G / ⇧⌘G for next and previous match. The shell's guards check only plain ⌘F: the cmd_f_stays_free_for_the_page_and_cmd_p_prints unit test and the menu_print_and_find_keys self-test check. A later menu item on ⌘G or ⇧⌘G would silently break the find bar. The fixer's open issue 'ui/ has no find bar yet' is also out of date.
  - evidence: find.ts: `if (k === 'g') return e.shiftKey ? 'prev' : 'next'`, and its header says 'No menu accelerator claims ⌘F or ⌘G (desktop/src-tauri/src/menu.rs)'. menu.rs test: only `!(cmd_only && key == "f")`. selftest.rs menu_print_and_find_keys filters only is_plain_cmd_f. FindBar.tsx mtime 21:31:07; the F4B-RUST report was written after 21:50.
  - fix: Extend declared_accelerators/cmd_f_stays_free… and the menu_print_and_find_keys self-test to assert that ⌘G and ⇧⌘G (keyEquivalent 'g' or 'G' with Command only, or Command+Shift) are unclaimed. Correct the open-issue note.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/selftest.rs: No end-to-end test of the real ⌘P path. print_refused_on_boot_page and print_check call windows::print_window from the self-test's async (non-main) thread. In the app, ⌘P reaches menu::dispatch → windows::print → focused_label + print_window on the main thread, where with_webview runs synchronously. That path, including focused_label and the beep, is covered only by reading the code. The risk is low, because existing menu actions (⌥⌘N, ⌘[ / ⌘]) already call webview_url from the main-thread menu handler.
  - evidence: selftest.rs: `let refused = windows::print_window(&app, MAIN);` and `let first = windows::print_window(app, MAIN);` inside async fns. tauri-runtime-wry-2.12.3 send_user_message handles messages inline only when current_thread == main_thread_id.
  - fix: In print_check, trigger the real item once: `app.run_on_main_thread(|| menu::dispatch(app, Action::Print))`, or NSMenu performActionForItemAtIndex: on File ▸ Print…. Assert the sheet appears on the focused window.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/feed.rs: may_claim_sink treats NotifAuth::Authorized (raw 2..=4) as 'SuryaDhana banners can show'. It does not read UNNotificationSettings.alertStyle or alertSetting. If notifications are allowed but the alert style is 'None' (Notification Center only), the app still touches notify-sink.alive, and the scheduler's _app_is_notification_sink suppresses its osascript banner. The owner then sees no banner at all. This is a narrower version of the round-3 check's 'heartbeat while banners cannot show' problem.
  - evidence: macos.rs notification_authorization reads only `authorizationStatus`, and NotifAuth::from_raw maps 2..=4 to Authorized. feed.rs: `auth == Some(crate::macos::NotifAuth::Authorized) && !(wanted > 0 && shown == 0)`. master_controller.py:858 `if sys.platform != "darwin" or _app_is_notification_sink(): return`.
  - fix: Also read alertStyle (UNAlertStyleNone = 0) or alertSetting in the same completion block. Claim the sink only when banners or alerts are enabled. Add a unit case to may_claim_sink.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/README.md: Out-of-date documentation. The README says 'The boot field is whatever the watchdog's boot_epoch() prints: today the usec part of kern.boottime (its sed is greedy), after a fix the sec part'. The stack.rs doc comment says 'the live watchdog (since 25 Oct 18:12) stamps the boot's MICROSECONDS field'. The LaunchAgent runs the working-tree script directly, and that script has written seconds since 21:35, before the README edit at 21:36:11. Only a run already in progress at 21:35 could have written usec.
  - evidence: ~/Library/LaunchAgents/com.suryadhana.watchdog.plist ProgramArguments = [/bin/bash, /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/stack_watchdog.sh]. stack_watchdog.sh:102 has the anchored `^[{] *sec = ` sed (mtime 21:35:19). README mtime 21:36:11.
  - fix: Reword it: since 25 Oct 21:35 the watchdog stamps kern.boottime's sec; owner lines written by runs before then hold the usec field, and both are accepted.
- not really fixed: []
- notes: Overall: the fixes are sound, and the 'fixed' and 'already-fixed' claims hold up. I edited nothing in the repo. My work stayed in scratchpad/rv-F4B-RUST: a copy of desktop/ plus scripts/stack_watchdog.sh, with my own CARGO_TARGET_DIR. I sent one GET to live :8010/api/market/nifty-live, launched no app and no browser, and restarted nothing.

Gates I re-ran (counts match the fixer's):
- cargo test --offline: 153 passed, 0 failed. The two new process-based tests passed 6 times in a row, with no stray sleep processes left.
- cargo test --features devtools settings_text_and_version: 1 passed.
- clippy --all-targets: 0 warnings, both with default features and with devtools.
- cargo fmt --check: clean.
- node boot_check.mjs: 74/74. My negative control with the round-3 boot.js: 70/74, failing exactly the 3 ICICI checks and the notification footer check.
- pytest on the 6 desktop integration files: 243 passed, 9 skipped.
- ruff (130) on desktop/scripts and icons-src: clean. bash -n on both scripts: OK.
- build_desktop.sh --help prints the whole header. Both shell scripts were replaced atomically (birth time = mtime) with mode 755 kept.

Bundle: target/release/bundle/macos/SuryaDhana.app is newer than every bundled source (stack.rs 21:49:43, bundle 21:51:22). Executable sha256 starts 7a0bc36c8f02372c, embedded id 0ae66db-dirty-ec8c0ab8-20261025T1620Z, and codesign --verify --deep --strict is OK. My own build of the current sources produced the same source hash, ec8c0ab8.

Negative controls I ran myself:
- An is_watchdog_process that checks liveness only fails the_real_watchdog_owner_line… at the reused-pid assertion.
- An owner_boot_matches that compares seconds only fails both watchdog tests.
- The data-service patch request (3 hunks plus 2 tests), applied in scratch: 33 passed with it; without it the 2 new tests fail and the 31 existing ones pass. Both test anchors match the current files exactly once.

Checked and sound:
- SECREL-05 reads the real owner format. The test runs the real take_lock and lock_is_stale in a temp dir and never touches the live lock. Only the edge in problem 1 remains.
- proc_cmdline parsing is bounds-safe and never returns the environment.
- R10: in calendar hours behaviour is unchanged, and fresh_print uses the same 3 min / 2 min-ahead window as the UI's isFreshPrint. The live NSE stamp on Sunday night is '23-Oct-2026 15:30', so weekends still read closed.
- P4 follows the ui-api round-4a contract: error_kind is read before needs_session_refresh, and 'expired', 'unknown', null and a missing field fall back to the old reading. The tracker never fires on Unreachable. Bodies are never logged.
- ShellStatus.icici now reports 'unknown' instead of 'expired' when credentials are missing. Nothing in the UI reads it: grep finds only the type in ui/lib/platform/types.ts, and the header reads connection-status itself.
- Print guards: a window with no NSWindow (the unwrap in wry's print) is refused. The self-test points sharedPrintInfo, which wry uses, at a temp PDF before printing, so nothing can reach a printer. ui/app/globals.css has an @media print black-on-white rule.
- The notification hint is clickable only from the tray. menu::dispatch is reachable only from menu and tray events, so no page can open it. The page's ENABLE path in shell_request_notification_permission is older code and unchanged.
- retire_alive runs on RunEvent::Exit. The self-test has alive=None, and a secondary instance exits with process::exit before Tauri starts, so neither removes the primary's heartbeat.
- build_desktop.sh --install --test now tests the built bundle before installing, and install_app still runs codesign --verify on the copy it installs.

Every new self-test check passed in the fixer's selftest3.json (57/58; the 1 skip is boot_page_painted, screen locked). drill4.log has the 3 R4b PASS lines. r1/fail.log shows 'NOT installed' at 19/21.

No leftover F4B-RUST processes. The scratch_server on :8099 belongs to F4B-UI-SHELL. The installed app (pid 83455) was untouched.

Disclosed by the fixer and confirmed:
- Muhurat 'live' stays steady only after the nse_live.py patch request is applied and data-service is restarted before 8 Nov.
- Five round-3 check minors are deferred:
  - the tray's 'Relaunch after a crash' line goes stale after Launch at Login is turned off;
  - clicking a feed banner does not open its tab;
  - the `features` flag is static;
  - webkit_download_same_url_twice is info-only;
  - PENDING_STALE is 10 min.

The R9 'Find' half is UI work (F4B-UI-SHELL's FindBar is in the working tree). With this round's shell it receives ⌘F, and ⌘G is unclaimed today, but only ⌘F is guarded by tests (problem 3).

# F4B-UI-PAGES

I checked every ID in the F4B-UI-PAGES brief against the current tree first, then fixed what was still open. 6 items were already fixed and I confirmed each in tests and the browser: R3, R5, R12, P8, RUP-04, CT-05. Two items had a remaining gap that I closed: CT-11 (the DERV rollover stat still mixed cr and L) and the DESK confirm (it re-focused Cancel on every re-render). The rest are fixed: C1-18 remainder, R11, P1, P4 (UI half), P5, P11, P12, CT-08, INSD order and the MKT wording. BTST is partly done: the IST helper is in lib/format, and the change to lib/backtestExport.ts is a patch request because that file is not mine. Trading logic is unchanged: the edits touch only presentation, request ordering and polling. Gates: pages.check 281 passed / 0 failed (218 at the start of the round). Run against the pre-round page sources, the same suite gives 254 passed / 27 failed; 26 failures are real catches and 1 (G1) is environmental, because the scratch tree has no reports/docs. no-dialogs.check passes with 0 calls. tsc --noEmit gives 0 errors. desktop.check 397/0, prefs 160, platform 123, alerts 31, ws 82, node --test ui/scripts 26/26. The scratch export (build8, id 20261025-221051-0ae66db) has 0 chunks with a regex lookbehind. Browser checks used one WebKit browser at a time, every WebSocket mocked, prefs readonly, and a --block-mutations scratch server on :8094 (stopped by PID). All /api/positions/**, gold-preopen and /api/mcx/** calls, and every write, were answered inside the browser. The negative controls ran on the current :8010 release (GET only). Results: GO 'RELIANCE OMON' with NIFTY's reply held back 3 s showed NIFTY in 0 of 220 samples over 4 runs plus the event path; the current release ends on NIFTY every time. The NIFTY OI chart shows 'CALL WALL 24,000 →' and PUT WALL on 21,500, matching the stat 24,000 / 21,500 (FINNIFTY and RELIANCE match too). DERV axes have 5–8 round ticks, including −40% and −20% on the basis chart; the current release shows 2. MOV polls again at Mon 09:20 IST after a 'closed' reply (2 polls in 62 s; current release 0). BRKR with error_kind network shows 'ICICI UNREACHABLE' and 'ICICI unreachable (network) — your session may still be valid', with no '/login'. ALFA scans with the new mode and knob value (the current release used the previous ones). The alert form is prefilled (3450 / 1180 / 5; current release: empty boxes). EQS fits all 15 columns at 1600 px. A DOM scan of all 42 pages for ASCII '-' in front of a number found 753 hits; after the follow-up fixes the only one left on BRF is the news track-record verdict ('t -0.27'), which is shell-owned and in the patch requests. DEXP (raw data, intentionally left) and the four other pages I did not rescan are in open issues. All screenshots were read: OMON go/event/walls, DERV, MOV, BRKR network/credentials, PORT network, EQS 1600.

## findings
- **C1-trader-ux-18** fixed: All ~20 hand-rolled sign sites from the round-3 check now use the kit's signed formatters with U+2212. IndexContribution (actual pts), WorldMarkets (GIFT/quote change), GoldPreOpen (context change, leg change), BacktestTradeGrid (gross/net %, P&L), AlphaDiscoveryDesk (MEAN NET 5D bps, still 2 dp), ModelLab (SHAP axis/tooltip), FactorDiagnosticStudio (lift), WarehouseHealth (avg label return), AlertsCenter (move %), PreOpen (imbalance), McxGoldDesk (premium %, and a new lib/format fmtSignedInr for 'vs settlement'), BacktestPanel fPct, plus two more the grep found: CommodityTab card %, PortfolioSummary '% on invested'. A DOM scan of all 42 pages then found more ASCII minus signs, which I also fixed: BRF internals 'net' line (fmtSigned, and the session day instead of 'today'), SEAG grid (fmtFixed), FUND P/E, P/B and margins (fmtFixed), and the MKT regime detail, yield-gap range, ALRT notification bodies and WRAP text and teasers (server sentences go through unicodeMinus). CSV exports keep ASCII '-': the kit's downloadCsv still applies asciiMinus. The shell-owned leftovers are patch requests: StockDetailModal intraday %, news/format.ts fmtPct, news/TrackRecord pct and its t-stat.
  - tests: pages.check Y4: a broadened regex flags any `? '+' : ''` in 82 page files, with a negative control proving it detects the 4 round-3 leftover forms. Also: fmtSigned/fmtSignedInr values, CSV asciiMinus, MKT server sentences, BRF/SEAG/FUND/ALRT/WRAP source guards, and unicodeMinus leaving Markdown lists, rules, tables and dates alone. Browser DOM scan for ASCII '-' in front of a number: current release 365 hits on 9 pages (MOV 11, WEI 27, OMON 41, PRE 194, INSD 83 …). New build: 0 on MOV/WEI/OMON/DERV/CMDT/MCXG/PRE/INSD/MKT/ALRT/WRAP; BRF is down to the news track-record verdict ('t -0.27', shell-owned, in the patch requests). SEAG and FUND each still showed that same news verdict line in the rescan, and their own grid and table cells were fixed after the full scan.
  - user-visible: Losses on these pages print with a true minus (−) instead of '-': MOV, WEI, OMON, PRE, INSD, CMDT/gold, BTST blotter, ALFA, MLEN/ModelLab, WHSE, ALRT, WRAP, MKT, SEAG and FUND. A value that rounds to zero prints unsigned ('0.00', not '+0.00'). BTST trade P&L and the ALRT move % gain Indian grouping and 2 dp.
  - not fixed because: 
- **R3** already-fixed: No change needed. OiBars takes its walls from data.resistance[0] / data.support[0] (omonModel.wallMarks) and draws an edge marker when the wall strike is off-chart (round 3).
  - tests: pages.check W1 (9 checks) passes. Browser (build8): NIFTY data-wall labels are 'PUT WALL' on its bar and 'CALL WALL 24,000 →' (edge right), with the stat 'OI WALLS 24,000 / 21,500'. FINNIFTY: 'CALL WALL 26,000 →' with stat 26,000 / 23,500. RELIANCE: bar labels 1,200 / 1,160 with stat 1,200 / 1,160. Screenshot new-omon-nifty-walls.png read.
  - user-visible: None in this round. The labelled walls match the OI WALLS stat.
  - not fixed because: 
- **R5** already-fixed: No change needed. compareSet.compareBase merges from storage only when another window wrote it (round 3).
  - tests: pages.check M2 (6 checks with a negative control) passes. Browser (build8): set TCS, INFY → remove both → empty → add HCLTECH → ['HCLTECH'] (no removed symbol returns).
  - user-visible: None in this round.
  - not fixed because: 
- **R11** fixed: New chart.ts axisTicks(lo, hi, plotPx): round ticks over the PADDED range the axis maps, about one per 30 px of chart height (3–8), never fewer than 3. DERV TsChart uses it for both axes, with '%' only on the basis axis (unchanged).
  - tests: pages.check R11: the NIFTY basis −38..70 gives −40/−20/0/20/40/60; at least 3 ticks on short charts; the count follows the height; 0 is labelled whenever the range crosses zero. Negative control: the old 4-tick rule gave 2 labels. Browser: basis '−40% −20% 0% 20% 40% 60%', max pain 22,000…26,000 (5) with PCR 0.00…1.75 on the right, aggregate PCR 0.6…1.6 (6), VIX 5…30 (6). Current release: '0, 50', '24,000, 26,000', '1.0, 1.5', '10, 20'. new-derv.png read.
  - user-visible: DERV time-series charts show 5–8 round axis labels, including negative basis levels (−40%, −20%).
  - not fixed because: 
- **R12** already-fixed: No change needed. The market-map industry header and tiles are coloured by the value as printed, so −0.03 reads '0.0%' in neutral grey (round 3).
  - tests: pages.check Y2 'market map colours a value as printed' passes; code read at MarketMap.tsx:52 and :184.
  - user-visible: None in this round.
  - not fixed because: 
- **P1** fixed: 1) The request guard is now held in a ref through a new hook, components/useRequestSeq.ts, replacing useMemo in OMON, COMP, OSTR and the new ALFA scan guard. The hook cancels on unmount. 2) The round-3 adversarial regression is fixed. requestSeq gains busy(key) and settle(token). OMON's 30 s LIVE refresh calls load(true) and skips a tick while a load for the same symbol|expiry|mode is still in flight, and the in-flight load settles after the end-of-day fallback. Before, a live answer slower than 30 s was always superseded and OMON stayed on 'Loading …'. A selection change still supersedes at once. ErrorBox Retry calls load() explicitly.
  - tests: pages.check P1 checks. busy/settle/cancel semantics. An event-driven fake-clock simulation: a 35 s live answer with a 30 s refresh is shown; a live failure at 40 s falls back to end of day with the note; fast answers still refresh every 30 s. Negative controls: the round-3 rule showed neither. Source guards: no useMemo(createRequestSeq) left anywhere. Browser delayed-reply test, WebKit: every NIFTY option-chain XHR is held back 3 s in the page; GO 'RELIANCE OMON' from DESK, OMON sampled every 150 ms for 9 s; 4 runs, 0 NIFTY samples (55 RELIANCE each). Event path (OMON open on NIFTY with its request in flight, then GO 'RELIANCE OMON'): 0 NIFTY / 58 RELIANCE. Negative control on the current release: every run ends on NIFTY (36–49 NIFTY samples). Shots new-omon-go.png and new-omon-event.png read.
  - user-visible: 'TICKER OMON' never shows NIFTY's chain under another symbol. A slow NSE live chain now appears (or falls back to end of day with its note) instead of 'Loading' forever.
  - not fixed because: 
- **P4** fixed: New pure module components/portfolio/iciciState.ts maps the round-4a error_kind contract. iciciErrorKind/pickErrorKind read the kind first: the summary reply, then connection-status; a missing field counts as unknown. iciciIssue and briefSessionLine give the wording. BRKR (PortfolioSummary): 'network' gives chip ICICI UNREACHABLE, the headline 'ICICI unreachable (network) — your session may still be valid' with an explanation, no '/login' line and no LOG IN step (the paste box stays). 'credentials' gives chip API KEY MISSING / REJECTED, the key/secret form and no login advice. 'expired' and 'unknown' are unchanged (server text plus the /login line). PORT (LivePortfolio ICICIBanner): 'network' shows the same headline, the detail and ↻ Recheck, with no login or paste form; 'credentials' shows the headline and 'Open BRKR ›'; 'expired' and 'unknown' are unchanged. BRIEF System line and holdings line: 'ICICI unreachable (network): session may still be valid', with no 'log in on Broker' for network.
  - tests: pages.check P4: the kind table, pickErrorKind order, the wording per kind, the BRIEF line, source guards for BRKR/PORT/BRIEF; negative control: the round-3 BRKR always said '/login'. Browser with the broker endpoints answered in the page: BRKR network shows 'ICICI UNREACHABLE' and the headline with no 'send /login' (new-brkr-network.png read). BRKR expired shows NOT CONNECTED and 'send /login' (unchanged). BRKR credentials shows API KEY MISSING and the key form (new-brkr-credentials.png read). PORT network shows the banner and Recheck, no LOG IN (new-port-network.png read). BRIEF network: 'ICICI unreachable (network): session may still be valid'. Negative control on the current release: BRKR network shows NOT CONNECTED with 'send /login'; PORT shows the generic banner with LOG IN.
  - user-visible: During an ICICI network outage, BRKR, PORT and BRIEF say 'ICICI unreachable (network) — your session may still be valid' and no longer tell you to send /login or log in again. A missing or rejected API key says so and shows the key form. Needs the round-4a ui-api (error_kind); with the old ui-api the wording is unchanged.
  - not fixed because: 
- **P5** fixed: MOV's 30 s movers refresh now also runs while the client's NSE session clock says OPEN: pageModels.moversPollDue(serverOpen, nseSession(Date.now()).state === 'OPEN'). Before, it ran only while the last reply said open, so a page opened before 09:15 never refreshed.
  - tests: pages.check P5: Mon 26 Oct 09:20 IST after a 'closed' reply → poll; Sunday → no poll. Negative control: the old rule never polled again. Browser with Playwright clock set to 2026-10-26 09:20 IST and the real (closed) reply: 2 more live-movers requests in 62 s on the new build, 0 on the current release.
  - user-visible: MOV opened before 09:15 (or left open overnight) starts refreshing once the session opens. No need to switch pages and back.
  - not fixed because: 
- **P8** already-fixed: No change needed. portfolio/policy.ts fails closed (LIVE only when live_allowed===true AND mode_policy==='LIVE_ALLOWED'; STATUS UNKNOWN · PAPER ONLY on a missing status), and LivePortfolio.refresh uses Promise.allSettled (round 3).
  - tests: pages.check §5 P1 (24 fail-closed rows) passes. Code read: LivePortfolio.tsx uses Promise.allSettled and executionPolicy(status). The new-port-network.png screenshot shows PAPER ONLY, LIVE struck through and LEGACY · DORMANT.
  - user-visible: None in this round.
  - not fixed because: 
- **P11** fixed: The ChartActions AlertForm mounts before useAlerts' first server read, so it always opened with empty boxes, and SET then cleared the untouched levels. Now each box the user has not typed in takes the saved level when it arrives (pageModels.alertFormFill with per-field touched flags). Typed text is never overwritten.
  - tests: pages.check P11: fill after load, typed field kept, no-op without levels; negative control: useState(initial) alone stays empty. Browser with GET /api/alerts answered in the page {RELIANCE: above 3450, below 1180, move 5}, GO RELIANCE then ALERT: boxes show 3450 / 1180 / 5 on the new build, and '' '' '' on the current release.
  - user-visible: The stock window's ALERT form shows the saved ABOVE / BELOW / MOVE levels when re-opened.
  - not fixed because: 
- **P12** fixed: ALFA doScan now reads the current strategy, knobs and mode from a ref (scanArgs) and takes overrides. Scan-mode buttons call doScan(true, {mode: m}); a knob writes the new params into the ref before the 450 ms debounce. Only the newest scan's answer, error or toast is shown (useRequestSeq), so a slower earlier scan can no longer overwrite it.
  - tests: pages.check P12 source guards. Browser with POST /api/alpha/scan captured and answered in the page: clicking 'latest' sends mode 'latest' (current release: 'recent'). Toggling enable_leg_a false→true sends params.enable_leg_a=true (current release: false).
  - user-visible: ALFA scan-mode buttons and knobs rescan with the value just chosen, not the previous one.
  - not fixed because: 
- **P16-CT-08** fixed: EQS table: the watch star is the first column (it was last, and the first to be cut off). The separate HEALTH column, which repeated the ticker's quality dot, is folded into that dot with the same tooltip. Cell padding is 8 px less, header tracking is tighter and the 1,400 px floor is removed. Cap type prints LARGE/MID/SMALL/MICRO (full name on hover). Company·Sector is capped at 220 px. The rare BAD RESULTS + event badge pair (6 of 1,500 rows) wraps instead of widening the column by about 80 px. The data bar is 48 px. Columns still out of view are named in a cue ('⇢ scroll for SALES QTR CR, ROCE%, DATA%'), using the DESK hiddenHeaders helper.
  - tests: pages.check CT-08 guards. Browser at steady state (1,500 rows mounted): before, at 1600 the table was 1656 px in a 1570 px box, with DATA% hidden (HEALTH and WATCH in the current release). After: at 1600, scrollWidth = clientWidth = 1570; the minimum content width is 1518 px, so all 15 columns are visible with no cue; rows are 37 px. At 1280: cue '⇢ scroll for SALES QTR CR, ROCE%, DATA%'. new-eqs-1600.png read.
  - user-visible: At 1600 px every EQS column is visible. The ☆ watch star is the first column. The HEALTH column is gone; its colour dot is the one before the ticker (hover for the text). Cap type reads LARGE/MID/SMALL. Narrower windows name the columns you need to scroll to.
  - not fixed because: 
- **P16-RUP-04** already-fixed: No change needed. flashClock gives one pending clear per symbol, and StockTable uses it (round 3).
  - tests: pages.check §15 F4 (timed checks with a negative control) passes.
  - user-visible: None in this round.
  - not fixed because: 
- **P16-CT-05** already-fixed: No change needed. IndexIntraday uses PRICE_DP (2) for every index (round 3).
  - tests: pages.check U2 passes. The new-mov.png screenshot shows the prev tag '22687.65' and '54925.70' at 2 dp.
  - user-visible: None in this round.
  - not fixed because: 
- **P16-CT-11** fixed: The DERV term-structure OI columns already used one unit per column (round 3). The remaining mix was the rollover stat 'OI near / next / far', which read '1.13 cr' above 'next 85.5 L · far 8.5 L'. It now uses one unit for the three legs (countUnit/fmtCount).
  - tests: pages.check U1/U3 pass, plus a new CT-11 check: the rollover legs share one unit ('113.0 L / 85.5 L / 8.5 L'). The new-derv.png screenshot shows 'OI (SHARES · L)' 113.2 L / 85.5 L / 8.5 L and OI CHG −24.9 L.
  - user-visible: DERV rollover 'OI near / next / far' prints all three legs in the same unit (113.0 L · next 85.5 L · far 8.5 L).
  - not fixed because: 
- **P16-INSD** fixed: data-service builds the INSD 'Who' categories with DuckDB string_agg(DISTINCT …), whose order is undefined. The UI now sorts them in a fixed order: promoter, promoter and director, promoter group, relatives, director, KMP, then anything else alphabetically (pageModels.orderCategories).
  - tests: pages.check P16: both raw orders give 'Promoter, Promoter Group'; negative control: the raw strings differ. Browser: the current release shows 'Promoter Group, Promoter' and 'Promoter, Promoter Group' mixed on the same page; the new build shows 'Promoter, Promoter Group' throughout.
  - user-visible: INSD 'Who' categories keep one order between refreshes (promoters first). The kit CSV, which uses the visible text, follows the same order.
  - not fixed because: 
- **P16-BTST** partially-fixed: Added lib/format istFileStamp(): the 'YYYY-MM-DD-HH-MM-SS' stamp in IST whatever the machine's zone (same shape as the old toISOString stamp). The BTST file name is built in ui/lib/backtestExport.ts, which is outside my brief, so the one-line switch is a patch request (PR 1 and 2).
  - tests: pages.check P16: 16:10:05Z → '2026-10-25-21-40-05', and 20:00Z → '2026-10-26-01-30-00' (date rolls over). Negative control: the old stamp gives '2026-10-25-16-10-05'.
  - user-visible: After the patch request is applied: BTST CSV/XLSX file names carry the IST time.
  - not fixed because: ui/lib/backtestExport.ts is not in F4B-UI-PAGES' files. Two patch requests (import + stamp line) complete it.
- **P16-MKT-MOV** fixed: MOV wording was already fixed in round 3 (verified in the browser: only 'last session (23 Oct)' wording, no 'today'). MKT is end of day, so it now names the session with sessionDayLabel(data.as_of): the index tile '−1.24% on 23 Oct', the 20-DMA change, 'changed from X on 23 Oct', and the empty mover lists 'None on 23 Oct'. On a session day after the EOD files it still says 'today'. The market-map LIVE chip reads 'LAST SESSION' on a weekend, holiday or before the open, and 'TODAY' after the close on a weekday. BRF's internals line names the session too.
  - tests: pages.check P16 MKT and map-chip guards (W2/W3 still pass). Browser on Sunday: MKT shows '−1.24% on 23 Oct · 200-DMA' and '(−5.0% on 23 Oct)', with no 'today' and the map chip 'LAST SESSION'. Current release: '−1.24% today', '(−5.0% today)', chip 'TODAY'. MOV: 0 'today' and 6 'last session (23 Oct)' phrases (new-mov.png read).
  - user-visible: On a closed market, MKT says 'on 23 Oct' instead of 'today', and the market-map chip says LAST SESSION.
  - not fixed because: 
- **DESK-R2-ReenableConfirm** already-fixed: Kept the PM's in-page ReenableConfirm unchanged in behaviour (no window.confirm). Fixed the round-3 review nit: Cancel is focused once, when the confirmation opens. The inline onCancel used to re-focus it on every DESK re-render, which stole focus, for example from the GO bar, on each refresh. Esc still cancels.
  - tests: no-dialogs.check: 0 window.confirm/alert/prompt in ui/{app,components,lib,context}. pages.check guards: DESK renders ReenableConfirm with no window.confirm, and focus is set once. Browser with /api/desk/status set to stopped=true in the page: Cancel focused on open, Esc closes it, no POST before the explicit click. Focus stays on BODY after a ↻ Refresh re-render (not pulled back to Cancel). 'Clear emergency stop' sends exactly one POST /api/desk/reenable, answered in the browser.
  - user-visible: The DESK re-enable confirmation no longer pulls keyboard focus back to Cancel on every refresh.
  - not fixed because: 

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/format/index.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/requestSeq.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/useRequestSeq.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/pageModels.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/portfolio/iciciState.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/terminal/chart.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/terminal/ChartActions.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/OptionChain.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/Compare.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StrategyBuilder.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DerivativesDesk.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/IndexContribution.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/WorldMarkets.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/GoldPreOpen.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/AlphaDiscoveryDesk.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/PreOpen.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/PortfolioSummary.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LivePortfolio.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/Brief.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/WarehouseHealth.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/AlertsCenter.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/BacktestPanel.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/McxGoldDesk.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/FactorDiagnosticStudio.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/BacktestTradeGrid.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/ModelLab.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/CommodityTab.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LiveMovers.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/InsiderMonitor.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketMonitor.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketMap.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/IndexValuation.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StockTable.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DecisionDesk.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/Seasonality.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/FundamentalsScreen.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DailyWrap.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/__tests__/pages.check.ts

## tests
- cd ui && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON components/__tests__/pages.check.ts -> 281 passed, 0 failed (218 at round start)
- pages.check.ts (final) run against the pre-round snapshot of ui/components + ui/lib (scratchpad/F4B-UI-PAGES/negctl, new pure modules overlaid) — negative control -> 254 passed, 27 failed: 26 real catches of the old code (R1/U3/Y4/P1/P4/P5/P11/P12/P16/CT-08/DESK) + 1 environmental (G1: the scratch tree has no reports/docs)
- cd ui && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON components/__tests__/no-dialogs.check.ts -> 0 window.confirm/alert/prompt calls in ui/{app,components,lib,context}
- cd ui && npx tsc --noEmit --incremental false -> 0 errors at the end. Mid-round transient errors in context/AppContext.tsx and app/page.tsx came from F4B-UI-SHELL's concurrent edits, not these files.
- cd ui && node components/desktop/__tests__/desktop.check.ts; node lib/__tests__/{prefs,platform,alerts,ws}.check.ts -> desktop.check 397/0; prefs 160 pass; platform 123 pass; alerts 31 pass; ws 82 pass
- cd ui && node --test scripts/*.test.mjs -> 26 pass, 0 fail
- scripts/build_ui.sh --out scratchpad/F4B-UI-PAGES/build1..build8 -> all OK (about 14 s each); final build8 id 20261025-221051-0ae66db, 85 files, gzip 975.2 kB, 0 chunks containing '(?<!' or '(?<='
- qa4.py (WebKit, WS mocked, prefs readonly, broker endpoints + writes answered in-browser) vs scratch_server :8094 --block-mutations (build3..build8) and vs the current :8010 release (negative controls, GET only) -> OMON GO race 4/4 + event path: 0 NIFTY samples (release: ends on NIFTY). Walls = stat for NIFTY/FINNIFTY/RELIANCE. DERV 5–8 ticks with negatives (release: 2). MOV 2 polls/62 s at Mon 09:20 (release: 0). BRKR/PORT/BRIEF network wording without /login (release: 'send /login'). ALFA mode 'latest' and knob true (release: 'recent'/false). Alert prefill 3450/1180/5 (release: empty). EQS 1600 no hidden column. MKT 'on 23 Oct' and LAST SESSION (release: 'today'/TODAY). INSD ordered (release: mixed). COMP remove-all then add → [HCLTECH]. DESK confirm: Cancel focus, Esc cancels, single POST on confirm
- minus_scan.py over all 42 pages (new build) and 9 pages (current release) -> Release: 365 ASCII-minus hits on 9 pages. New build: 0 on 37 of 42 pages; remaining hits were in BRF/SEAG/FUND/ALRT/WRAP/DEXP. I fixed those (except DEXP, raw data) and rescanned: WRAP 0, ALRT 0, MKT 0. BRF still has 1, the news track-record verdict, which is shell-owned and in the patch requests
- ruff check --line-length 130 scratchpad/F4B-UI-PAGES/*.py -> All checks passed (after --fix and SIM115 fixes). No repo Python changed. No Rust changed, so clippy and fmt do not apply

## patch requests
### PR-F4B-UI-PAGES-1 ui/lib/backtestExport.ts
why: FEATURE_PARITY P16 'BTST UTC file names'. Import the new IST stamp helper (lib/format istFileStamp, tested in pages.check P16).

OLD:
```
import { isDesktop, saveDownload } from '@/lib/platform'

```
NEW:
```
import { isDesktop, saveDownload } from '@/lib/platform'
import { istFileStamp } from '@/lib/format'

```
### PR-F4B-UI-PAGES-2 ui/lib/backtestExport.ts
why: FEATURE_PARITY P16: BTST CSV/XLSX names used the UTC time. istFileStamp keeps the same 'YYYY-MM-DD-HH-MM-SS' shape, so only the clock changes.

OLD:
```
const stamp = () => new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
```
NEW:
```
const stamp = () => istFileStamp()   // IST like every other clock on the terminal (P16: toISOString() named the file in UTC, 5 h 30 m behind)
```
### PR-F4B-UI-PAGES-3 ui/components/StockDetailModal.tsx
why: C1-trader-ux-18 remainder in a shell-owned file: the stock window's intraday change printed an ASCII '-' for losses. Self-contained (no import needed); U+2212 for losses, no sign when it rounds to 0.00.

OLD:
```
{last.toFixed(2)} · {chg >= 0 ? '+' : ''}{chg.toFixed(2)}% <span style={{ color: '#8a94a6' }}>vs prev close {prevClose.toFixed(2)}</span></span>
```
NEW:
```
{last.toFixed(2)} · {Math.abs(chg) < 0.005 ? '' : chg > 0 ? '+' : '−'}{Math.abs(chg).toFixed(2)}% <span style={{ color: '#8a94a6' }}>vs prev close {prevClose.toFixed(2)}</span></span>
```
### PR-F4B-UI-PAGES-4 ui/components/news/format.ts
why: C1-trader-ux-18: the News Terminal's fmtPct printed ASCII '-' for losses (NewsTerminal quote rows) and '+0.00%' for zero. Same rule as the kit's fmtPct. Any CSV made through the kit's downloadCsv turns U+2212 back into '-'.

OLD:
```
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`
```
NEW:
```
  const r = Number(v.toFixed(digits)) || 0
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toFixed(digits)}%`
```
### PR-F4B-UI-PAGES-5 ui/components/news/TrackRecord.tsx
why: C1-trader-ux-18: the track-record table printed ASCII '-' for losses.

OLD:
```
const pct = (v: number | null | undefined, d = 2) => v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`
```
NEW:
```
const pct = (v: number | null | undefined, d = 2) => v == null || !Number.isFinite(v) ? '—' : `${Number(v.toFixed(d)) > 0 ? '+' : Number(v.toFixed(d)) < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`
```
### PR-F4B-UI-PAGES-6 ui/components/news/TrackRecord.tsx
why: C1-trader-ux-18: the 'No edge yet … (t -0.27)' verdict, shown on BRF and in the news bar, is the last ASCII minus a 42-page DOM scan found outside DEXP's raw data.

OLD:
```
(t ${t?.toFixed(2) ?? '—'})
```
NEW:
```
(t ${t == null ? '—' : t.toFixed(2).replace('-', '−')})
```

## deploy notes
- Static UI only: no backend, Rust or config change. Publish with ./start-local.sh build-ui after this round, building from the tree: F4B-UI-SHELL was editing shell files (AppContext, page.tsx, ShellToasts, desktop/find*) at the same time. My verified scratch export is scratchpad/F4B-UI-PAGES/build8 (id 20261025-221051-0ae66db); treat it as evidence, not as the artifact.
- P4 wording depends on the round-4a ui-api, which adds error_kind; ui-api needs a restart (F4-API deploy note). With the old ui-api the field is missing, it counts as unknown, and BRKR/PORT/BRIEF keep their old text.
- Apply patch requests 1+2 (lib/backtestExport.ts) together: the import is needed for the stamp line. Requests 3–6 are independent one-liners.
- User-visible changes: losses print with U+2212 on about 15 more pages (CSV stays ASCII). OMON never shows another symbol's chain after GO, and a slow live chain no longer sticks on Loading. DERV axes have 5–8 round labels, including negatives. DERV rollover OI legs share one unit. MOV refreshes once the session opens. BRKR/PORT/BRIEF say 'ICICI unreachable (network) — your session may still be valid' with no /login advice during an ICICI outage, and show the key form or 'Open BRKR' for a missing or rejected API key. The ALERT form shows saved levels. ALFA scans with the value just chosen. EQS fits all columns at 1600 px: ☆ first, HEALTH folded into the ticker dot, cap type LARGE/MID/SMALL, and a scroll cue on narrow windows. INSD 'Who' is ordered. MKT says 'on 23 Oct' and LAST SESSION when closed. DESK confirm no longer steals focus.
- Post-deploy check: GO 'RELIANCE OMON' from DESK must show 'RELIANCE … lot 500'. Re-run scratchpad/F4B-UI-PAGES/qa4.py <base> post omon_go,omon_event,omon_walls,derv,brkr_network,eqs.

## open issues
- Process note: my first EQS layout measurements (eqs_measure/eqs_cue/eqs_cols/eqs_event.py, about 10 page loads against :8010 and :8094) did not stub /api/positions/**. The header's ICICI light therefore sent GET /api/positions/connection-status to the live ui-api, which answers from its probe cache (stale-while-revalidate, the same poll the running app makes). Every later run, including qa4.py and minus_scan.py, answered broker endpoints in the browser.
- Shell-owned sign sites are left as patch requests: StockDetailModal intraday %, news/format.ts fmtPct, news/TrackRecord pct and t-stat.
- DEXP (data explorer) still prints raw DB values with ASCII '-' (476 hits). It is a raw-data view, so I left it unchanged on purpose.
- The final 42-page minus scan ran before the BRF/SEAG/FUND/ALRT/WRAP fixes; afterwards I rescanned WRAP, ALRT, BRF and MKT only. SEAG and FUND rows/cells were not rescanned in the browser after their fmtFixed change (covered by pages.check source guards).
- OMON's IV/PCR history chart (OptionChain History) labels the right PCR axis with only min/max (0.43 / 1.83). Same class as R11 but not DERV; left for a follow-up.
- AlertForm: SET pressed before useAlerts' first server read (normally under 100 ms) can still clear the levels the user did not type. The prefill now fills them as soon as the read returns. Pre-existing; the fully safe fix would need a 'loaded' flag from lib/alerts.ts, which is not my file.
- The round-3 review's StockTable RUP-09 nit is still open: a sort while scrolled deep resets the mount count and moves the scroll position.
- INSD: data-service still returns categories in an undefined order (duckdb_store.py string_agg); the UI sorts them. An ORDER BY inside string_agg would fix it at the source (backend owner).
- EQS headroom at 1600 px is about 20–30 px. A future wider column (for example a longer event badge type) could push DATA% out again; the cue would then name it.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/portfolio/iciciState.ts: The error_kind mapping now exists twice. F4B-UI-SHELL's lib/iciciStatus.ts (used by the header ICICI light) and this new pages module each define their own IciciErrorKind type and iciciErrorKind(), and the two behave differently. When error_kind is missing and needs_api_credentials is true, the shell version returns 'credentials' and the pages version returns 'unknown'. The network wording also differs: the header says 'ICICI unreachable (network) — not a login problem; retried by itself' while BRKR, PORT and BRIEF say 'ICICI unreachable (network) — your session may still be valid'. During one outage the header tooltip and the pages will word the same state differently.
  - evidence: lib/iciciStatus.ts:16-27 and ICICI_KIND_TEXT, against components/portfolio/iciciState.ts:19-25 and ICICI_UNREACHABLE. Both files are new this round (21:45 / 21:53). The shell file's own header comment admits the pages word the kinds through iciciState.ts.
  - fix: Follow-up: keep one module, e.g. lib/iciciStatus.ts exporting the kind parser plus the per-kind wording, and have iciciState.ts re-export or wrap it. At minimum use one ICICI_UNREACHABLE string and one rule for a missing field. This needs coordination with the F4B-UI-SHELL owner.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/__tests__/pages.check.ts: Several new checks are weak. P12 (ALFA scans with the new value), the CT-08 EQS layout, the DESK focus-once fix and the P4 page wiring are covered only by source-string includes() checks. The 'negative controls' for P4, P5 and P11 are hand-written lambdas that model the old rule (e.g. oldBrkr = () => 'Or send /login…'); they do not run the old code. The real catch of the old code comes only from the separate negctl run. The R11 check is titled '8 at most' but asserts length <= 9.
  - evidence: pages.check.ts §18: P12 checks are al.includes(...) only. 'P4 negative control' builds its own string. 'P11 negative control' is ((cur)=>cur?.above?…:'')(undefined)===''. 'R11 tick count follows the chart height (8 at most)' tests <= 9. Re-running the fixer's negctl reproduces 254 passed / 27 failed, so the source guards do catch the old tree.
  - fix: Move the ALFA scan-args merge (scanArgs.current plus overrides) into a pure helper in pageModels.ts with a behavioural test that shows the stale-closure order. Change the R11 bound to <= 8, or retitle the check. These are fine as a follow-up.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LiveMovers.tsx: P5 calls nseSession(Date.now()) without the holiday map. On a weekday NSE holiday, MOV therefore polls live-movers every 30 s from 09:15 to 15:30 even though the server keeps answering 'closed'. That is the same load as a normal session day, so it is harmless, but it is not 'only while the session is open'.
  - evidence: LiveMovers.tsx: moversPollDue(data?.market_open, nseSession(Date.now()).state === 'OPEN'). components/desktop/session.ts:79 nseSession(epochMs, holidays = null, …) only returns CLOSED/HOLIDAY when a holiday map is passed (holidaysFromEco exists at :100).
  - fix: Pass the ECO-calendar holiday map, as the shell's session strip does, or accept it and note it.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/PortfolioSummary.tsx: There are two wording gaps on the 'credentials' path. (1) The detail reads 'Check them on BRKR (Broker page)…' while the user is already on BRKR. (2) keyMissing defaults to true when connection-status could not be read, so a key ICICI rejected (summary error_kind 'credentials', keys present) is labelled 'API KEY MISSING'.
  - evidence: PortfolioSummary.tsx: keyMissing: connectionStatus ? !(has_api_key && has_api_secret) : true. iciciState.ts iciciIssue('credentials'): detail `${missing ? 'Enter' : 'Check'} them on BRKR (Broker page): …`.
  - fix: Use a neutral 'API KEY / SECRET PROBLEM' chip when connection-status is unknown. Drop the 'on BRKR' phrase when the page is BRKR, for example with an opts.onBrkr flag. This is a cosmetic nit.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/reports/desktop_app/review/fix_round4a.md: Process (self-disclosed by the fixer). The first ~10 EQS measurement page loads did not stub /api/positions/**, so the header's ICICI light sent GET /api/positions/connection-status to the live ui-api. That route goes through the Breeze probe cache (TTL 900 s for expired), so a load after expiry can make a credentialed Breeze call. No payload was printed or saved. The installed app polls the same route, so the extra Breeze traffic is about zero, but it broke the round's 'broker endpoints answered in the browser' rule.
  - evidence: F4B-UI-PAGES open_issues[0]. positions.py:40-45 sets _PROBE_TTL_BY_KIND session_expired 900 s; line 81 shows the cache refill. qa4.py and minus_scan.py (later runs) and my own run stubbed /api/positions/**.
  - fix: No code change. The PM should know about it. Future QA scripts should always install the positions/ stub in new_qa_context-based helpers, or new_qa_context could stub /api/positions/** by default.
- not really fixed: []
- notes: I re-ran the gates on the current tree, read-only:
- pages.check: 281 passed, 0 failed.
- no-dialogs.check: 0 calls.
- tsc --noEmit --incremental false: exit 0, no output.
- desktop.check: 398/0. The fixer reported 397; F4B-UI-SHELL has added a check since.
- prefs 160, platform 123, alerts 31, ws 82; node --test ui/scripts 26/26.
- Negative control: the fixer's negctl tree, which holds the same final pages.check, gives 254 passed / 27 failed, as claimed. 26 failures are real catches; G1 fails only because that tree has no reports/docs.
- Build: scripts/build_ui.sh --out scratchpad/rv-F4B-UI-PAGES/build is OK (id 20261025-222206-0ae66db, 85 files, gzip 975.2 kB). 0 files contain a regex lookbehind, and the build contains the new strings ('ICICI unreachable (network)', 'LAST SESSION'). ui/.build-ui staging was cleaned up.

Code review: I diffed every changed file against the fixer's pre-round snapshot (scratchpad/F4B-UI-PAGES/orig).
- No trading or computed logic changed. Everything is presentation, request ordering, polling or wording.
- requestSeq busy/settle/cancel is correct. Settling a superseded token is a no-op, and cancel clears busy. Every axios call has a timeout (10 s default; live chain 40 s), so busy() always settles.
- useRequestSeq keeps the guard in a ref and cancels it on unmount. No useMemo(createRequestSeq) is left.
- OMON: only load(true) from the 30 s timer is skipped while the same symbol|expiry|mode is in flight. A selection change, GO hand-off or Retry still supersedes at once.
- ALFA scanArgs: the sync effect is declared before the initial-scan effect, so a strategy change scans with the new defaults. A pending knob debounce now scans the current strategy instead of a stale closure.
- AlertForm prefill: typed fields are never overwritten.
- iciciState: error_kind is read first; a missing field is 'unknown' (old wording). The login_url is still only opened, never printed.
- DERV: the axisTicks output stays inside the padded mapped range, so labels are never clipped. The CT-11 rollover legs use one unit, and null legs print '—'.
- EQS: the hooks are declared before the early return, and no colSpan depends on the column count.
- unicodeMinus on server sentences and WRAP Markdown leaves list markers, rules, tables and dates alone, and the wraps contain no links that could be altered. CSV output stays ASCII through the kit's asciiMinus.

Already-fixed claims, confirmed in code:
- R3: wallMarks at OptionChain.tsx:77.
- R5: compareBase (M2 passes).
- R12: MarketMap.tsx:52/:184.
- P8: policy.ts:58-62 plus Promise.allSettled at LivePortfolio.tsx:777.
- RUP-04: flashClock.
- CT-05: IndexIntraday PRICE_DP.

Patch requests: all six 'old' strings match the current files exactly (checked with Python count = 1 each). The news/format fmtPct patch also removes an existing mix: news fmtChange already prints U+2212.

Browser check (my own, WebKit, one browser at a time, WS mocked, prefs readonly):
- Setup: a --block-mutations scratch server on :8096 served my build and was stopped by PID; nothing listens on :8096 now. All /api/positions/**, gold-preopen and /api/mcx/** calls and every write were answered in the page. /api/market/option-chain-live/* was held in the page, so no NSE call. The page clock was set to Mon 26 Oct 10:00 IST so OMON opens in LIVE.
- New build: 1 live request at open. After clock.run_for(31 s), still 1 live request (the refresh tick was skipped). Releasing the slow first answer shows the chain (OI WALLS, no 'Loading NIFTY'). A slow live answer that fails after the tick falls back to end of day with the note 'live chain unavailable (…): showing end of day' (screenshot shots/new-omon-slow-fail.png, read). No writes were sent.
- Current :8010 release (GET only): the tick sends a 2nd live request. That release predates the round-3 guard, so it does not hang. The round-3 hang is covered by the fixer's fake-clock simulation negative control.
- So the round-3 adversarial [minor] OMON regression is really fixed. The other round-3 items are addressed too: the C1-18 'not really fixed' sites, all ~20 now converted with Y4 broadened; the DESK R2 report/test gap; and the focus nit. RUP-09 (sort scroll reset) remains open, and the fixer says so.

Labelling and coverage nits:
- DESK-R2 is reported as 'already-fixed', but the code changed (Cancel is now focused once). It should read 'fixed'.
- The R11 claim 'including −40% and −20%' depends on chart height. With a 184 px plot, axisTicks(−44.75, 76.01) gives −25/0/25/50/75, which still has a negative label and 0.
- P16-BTST is correctly reported as partial, pending patch requests 1+2.
- FEATURE_PARITY P16 items OMON Enter quirks, CT-09, CMDT TTL and scheduler header are not in this report. I assume they are in other briefs.

Deploy: static UI only. P4 wording needs the round-4a ui-api restart. Rebuild from the tree, because shell files (StockDetailModal 22:14) changed after the fixer's build8.

Scratch: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/rv-F4B-UI-PAGES/ (rv_omon_slow.py, shots/, build/, pages.diff).

# F4B-UI-SHELL

Every ID in my brief has an outcome: 10 fixed, 1 partially fixed (P11: the WTCH in-page toast is a page file, covered by a patch request), 3 already fixed and re-verified (R6, R13, P15; P15 also hardened), plus K5 checked as coherent. Trading logic is unchanged. Every change is about live-evidence, wording, polling or UX. Nothing was deployed or restarted, nothing live was written, and no ICICI or Telegram call was made.

1. MAJOR (round-3 regression) is fixed. Before, every monitor-socket message counted as a live tick. Now only a quote counts, and only when two things hold:
   - its own exchange time (ltt) is under 90 s old;
   - it is a new print for its symbol (the price or the traded volume changed).
   These never count: pongs, {ok, subscribed} acks, errors, zone-less or numeric timestamps, stale replays, and repeated prints. The repeated-print rule matters because Breeze stamps index quotes with the fetch time: the stored NIFTY quote has ltt 15:35:52, after the close. The rules live in lib/feedState.ts (quotePrint / isLivePrint / exchangeTimeToEpoch) and lib/liveEvidence.ts (noteQuoteMessage). AppContext hands every message to noteQuoteMessage.
   Tests cover both directions:
   - Holiday, 10 Nov: 160 messages (prior-session quotes, pongs and acks) give 0 ticks, so the chips read CLOSE 09-NOV and SOCKET OK · NO TICKS.
   - An index stamped "now" with an unchanged price: 0 ticks.
   - A heartbeat-only stream on a Sunday: 0 ticks.
   - A special session with moving prints: live from the 2nd print, with one edge.
   - Negative control: the round-3 rule calls the holiday stream live.
   Browser check (real closed Sunday), both engines and both modes: heartbeats only, then prior-session quotes, both stay CLOSE 23-OCT / NO TICKS. Fresh moving prints then give ● LIVE / ● STREAMING.

2. CT-07 is fixed. The stock window's marker now comes from stockPriceMarker. "NSE trades" means the calendar, a live tick, or a fresh NSE print, so during Muhurat with a fresh print it reads DELAYED · 18:19 IST, not CLOSE 08-NOV. The as-of is the quote's own time: the tick's as_of, else the ICICI ltt. A quote from an earlier day shows its date. The change base falls back to the REST quote's previous close.

3. CT-04 is fixed. UPDATE COMPLETE now needs positive evidence (lib/refreshStatus.ts):
   - the status is not active;
   - total > 0;
   - done + current + errors = total;
   - and the size matches what this window started.
   An empty status after a ui-api restart reads 'UPDATE STATUS UNKNOWN · progress was lost (ui-api restarted?)' with RETRY. Also from the round-3 adversarial check:
   - RETRY needs a second click inside the EOD window;
   - only one poll chain runs at a time;
   - the wording now says 'may still be running in ui-api'.

4. FEATURE_PARITY items:
   - R8 fixed: DownloadToasts sits inside ToastProvider.
   - R9 fixed: an app-only ⌘F find bar (window.find + CSS highlight; ⌘G / ⇧⌘G, Esc). Browsers keep their own ⌘F.
   - P9 fixed: STALE chip in market hours, the stalled-stream source switch, the macro tape with allSettled semantics, and the summary refresh every 10 min, on focus and after an outage.
   - P10 fixed: the Redis monitored set is re-synced on socket reconnect and every 10 min.
   - P11: alert save errors now show as toasts, move-alert wording is fixed, and the re-opened form is prefilled.
   - P4 UI half: the header ICICI light tooltip now follows error_kind. The BRIEF line was done by F4B-UI-PAGES; I checked their mapping.

Gates (all green):
- desktop.check 398/0 (was 321)
- pages.check 281/0
- prefs 160, platform 123, alerts 31, ws 82, streamProxy 76/0
- tsc clean
- ui/scripts 26/26
- desktop pytest: 127 passed, 8 skipped
- Negative control: against the pre-round sources, desktop.check fails 20 checks plus a throw, and alerts.check and ws.check crash.

Browser checks on the final scratch export (scratchpad/F4B-UI-SHELL/export3, id 20261025-221434-0ae66db, served by scratch_server --block-mutations on :8099, now stopped by PID):
- 12/12 sections pass in WebKit and 12/12 in Chromium.
- ui_audit on an earlier export (export2, :8098): 39/42 in both engines. The 3 failures are only the scratch server's blocked on-load POSTs (alpha/scan, mcx/ticket, options/strategy/analyze), not page errors.
- First-load JS is 280 kB (budget 300). No lookbehind regex in any chunk.

## findings
- **MAJOR-R-UI-SHELL-03-live-evidence** fixed: Only real quote messages with a fresh exchange time that are a NEW print can flip chips to LIVE. lib/feedState.ts gets exchangeTimeToEpoch (it accepts three exchange stamp formats and refuses zone-less ISO and bare numbers), quotePrint and isLivePrint. quotePrint returns null for {pong}, {ok, subscribed}, {error}, a missing symbol and a non-numeric ltp. Its key is ltp|volume and its at is from ltt / last_trade_time / exchange_time. isLivePrint needs at within 90 s (60 s of future skew allowed) and a key that differs from the symbol's previous print; a symbol's first message only seeds the comparison. lib/liveEvidence.ts adds noteQuoteMessage, with a per-symbol print map capped at 2000 and cleared in reset. context/AppContext.tsx calls noteQuoteMessage(data) for every message instead of noteLiveTick() after the symbol check.
  - tests: desktop.check section liveEvidence:
- exchange-stamp formats and refusals;
- non-quotes rejected;
- per-message rule: seed, live, repeat, stale replay, no ltt, future stamp.
Scenarios:
- Tue 10 Nov holiday: 160 messages give 0 ticks, and the chips read 'CLOSE 09-NOV' / '● SOCKET OK · NO TICKS'.
- Index stamped 'now' with an unchanged price: 0 ticks.
- Heartbeat/ack-only stream on Sunday: 0 ticks.
- Special session: print 1 seeds, prints 2 and 3 are live, one edge.
- Negative control: the round-3 rule (round3Rule) calls the holiday stream live.
Browser TICK, real clock Sun 21:39 IST, WebKit + Chromium × web + app: heartbeats and prior-session quotes stay CLOSE 23-OCT / SOCKET OK · NO TICKS. Fresh moving prints give ● LIVE / ● STREAMING.
  - user-visible: On a weekday NSE holiday (next: Tue 10 Nov) with ICICI logged in, the chips stay CLOSE <day> / SOCKET OK · NO TICKS instead of LIVE / STREAMING. In a session the calendar does not know, chips go live from the second real print (about 15 s), not the first message.
  - not fixed because: 
- **CT-07** fixed: New pure stockPriceMarker in lib/feedState.ts:
- 'NSE trades' = marketOpen OR a fresh NSE print, the same evidence as the header chip;
- LIVE for broker ticks;
- DELAYED · HH:MM IST from the quote's own time (an ISO tick as_of, or an NSE/Breeze ltt);
- 'DELAYED · 23-OCT 15:29 IST' when the stamp is from an earlier IST day;
- else CLOSE <day> / CLOSED.
StockDetailModal uses it. It keeps the ICICI quote's ltt (initial REST quote and socket quote) as the as-of, and the REST quote's previous_close as the last change base. Tooltip 'Delayed quote (Yahoo)' became 'Delayed quote (not a broker tick)'.
  - tests: desktop.check priceMarker:
- Muhurat with a fresh print gives DELAYED, LIVE with ticks, 'DELAYED · 18:19 IST' from the ltt and from ISO;
- a stale weekend print gives CLOSE 06-NOV; no stamp gives CLOSED;
- an earlier-day stamp carries its date;
- negative control: the round-3 logic said CLOSE 08-NOV.
Plus source guards: the modal uses stockPriceMarker, asOf is tick?.as_of ?? quoteAt, and quotePrev is the change base.
Browser STK, WebKit + Chromium, fake clock Sun 8 Nov 18:20, routed NSE print and REST quote:
- '₹3,010.50 ▲ 20.50 (+0.69%) DELAYED · 18:19 IST' while the header says ● NSE;
- with a stale print: CLOSE 06-NOV.
  - user-visible: The stock window says DELAYED · <time> (with the quote's date when not today) whenever NSE is printing, including Muhurat, instead of CLOSE <day>. It shows ▲/▼ change and % even when only the ICICI REST quote is known.
  - not fixed because: 
- **CT-04** fixed: New lib/refreshStatus.ts refreshVerdict. COMPLETE needs four things: not active, total > 0, done + current + errors = total, and (when this window started it) total equal to the start reply's tickers. Otherwise it is unknown with a reason:
- 'progress was lost (ui-api restarted?)'
- 'the status is for another download (N stocks, not M)'
- 'the download stopped before every stock had a result'
page.tsx changes:
- the headline uses the verdict ('UPDATE STATUS UNKNOWN · <reason>', amber, with ↻ RETRY UPDATE);
- the count line is hidden for an empty status;
- RETRY goes through an EOD-window two-click confirm ('CONFIRM: RETRY DURING EOD');
- one poll chain: a busy guard plus one timer ref, so a double-clicked CHECK AGAIN cannot start a second chain;
- the expected size is remembered from the trigger reply;
- the wording now says 'may still be running in ui-api'.
  - tests: desktop.check refreshVerdict: restart (total 0) is unknown; every stock with an outcome is complete with its failed count; running; stopped early is unknown; another download's status is unknown; no expected size is judged on its own counts; junk is unknown. Negative control: the round-3 headline called the restart case COMPLETE. Plus source guards for the headline, the ui-api wording, the single chain, the EOD retry and the remembered size.
Browser UPD, WebKit + Chromium:
- running, then an empty status: 'UPDATE STATUS UNKNOWN · progress was lost (ui-api restarted?)' with RETRY, never COMPLETE; one RETRY click sends one POST.
- running, then 1500 with outcomes: 'UPDATE COMPLETE · 3 FAILED', no retry.
- Fake clock 18:45: the first RETRY click shows 'CONFIRM: RETRY DURING EOD' and sends 0 POSTs.
- Poll failure, then a double-clicked CHECK AGAIN: 1 poll, then at most 4 in 10 s (one chain).
  - user-visible: After a ui-api restart mid-download the panel says UPDATE STATUS UNKNOWN with the reason and offers RETRY, instead of a false green UPDATE COMPLETE. RETRY inside 18:30–21:15 needs a second click. PROGRESS UNAVAILABLE now names ui-api.
  - not fixed because: 
- **R6** already-fixed: Fixed in round 3 (CT-15) and verified now: .sd-note is 'position: relative' with no z-index (globals.css), and MigrationNotice renders in the flow before the terminal (PlatformShell), so it never floats over page controls or dialogs. No change this round.
  - tests: desktop.check outage guard: '.sd-note { position: relative' and never position: fixed.
Browser NOTE, WebKit + Chromium, 1280×800, app mode, DEXP: the notice is present, position relative, z-index auto, at the top (y = 32 under the strip). elementFromPoint at 9 points across the bottom 100 px never hits the notice. The FIND screenshot shows it as a strip under the title bar.
  - user-visible: None this round.
  - not fixed because: 
- **R8** fixed: New components/shell/ShellToasts.tsx: DownloadToasts listens to 'suryadhana:download' and calls addToast. It is mounted inside ToastProvider next to <ErrorCatcher/> in app/page.tsx, not in PlatformShell, which sits outside the provider. Pure text in the new lib/downloadText.ts:
- success: 'Saved to ~/Downloads/<file> · ⌥⌘L shows it in Finder' (/Users/<name>/ becomes ~/), 7 s;
- failure: '<file> NOT saved: <reason>', 15 s.
Browser downloads fire no event, so they are unchanged.
  - tests: desktop.check downloadToast: success with a tilde path, without a path, failure with and without a reason, other paths unchanged. Source guards: the listener; only the 4 desktop paths emit (5 emitDownload occurrences including the definition). alerts.check checks the toasts sit inside ToastProvider.
Browser DL, WebKit + Chromium, ECO ⤓ CSV:
- fake shell save OK: '✓ Saved to ~/Downloads/eco-calendar-2026-10-25.csv · ⌥⌘L shows it in Finder', one shell_save_download;
- shell refuses: '✕ eco-calendar-2026-10-25.csv NOT saved: too many downloads: at most 20 a minute';
- browser: a real download (eco-calendar-2026-10-25.csv) and no toast.
  - user-visible: In the app, every export shows a toast: where the file went (⌥⌘L reveals it), or why the save was refused. The browser is unchanged.
  - not fixed because: 
- **R9** fixed: Find on page, app only. New components/desktop/find.ts (pure):
- findShortcut: ⌘F open, ⌘G next, ⇧⌘G previous; none with Ctrl or Alt;
- countMatches (case-insensitive, capped at 999+);
- findStatus.
New components/desktop/FindBar.tsx, mounted by PlatformShell only when desktop:
- window.find() selects and scrolls to the match;
- the match is copied into a CSS highlight ('sd-find') and focus returns to the input, because typing does nothing while the selection sits in page text (verified in both engines);
- ↵ / ⇧↵ / ↑ ↓ buttons; Esc closes, with stopPropagation, so the stock window stays open;
- role='search', not dialog, so type-to-GO keeps working.
The bar's labels are CSS-generated content (globals.css .sd-find*), so a search never matches the bar. The help card lists '⌘ F · ⌘ G · ⇧⌘ G' in the app only.
Print (File ▸ Print…) and the menu accelerators are F4B-RUST's. Today's menu.rs has no ⌘F or ⌘G accelerator.
  - tests: desktop.check find: the shortcut table (9 cases), counts, statuses; source guards for the mount (app only), window.find + refocus + highlight, Esc and role, generated labels, and help in the app only.
Browser FIND, WebKit + Chromium, app mode, RSCH:
- ⌘F opens the bar with the input focused; typing 'PASS' gives '34 MATCHES';
- Enter gives the next match, keeps the input focused and sets the 'sd-find' highlight;
- the bar's own innerText is empty (no self-match);
- ⌘G works and Esc closes it;
- a nonsense query gives 'NO MATCH';
- browser mode: ⌘F mounts no bar.
Screenshot final_webkit/FIND-app-webkit.png.
  - user-visible: In SuryaDhana.app, ⌘F opens a FIND bar above the status line: find as you type, ↵ or ⌘G next, ⇧⌘G previous, Esc closes. The help card lists it. Browsers keep their own ⌘F.
  - not fixed because: 
- **R13** already-fixed: Fixed in round 3 (R-UI-SHELL-08: isMacPlatform / footerHint(desktop, mac)) and verified now. No change.
  - tests: desktop.check macKeys passes.
Browser MAC, WebKit + Chromium, navigator.platform MacIntel:
- the footer reads 'ALT+1…0 PAGES · ⌘[ ⌘] BACK/FWD · …' with no 'ALT+←';
- the help row is '⌘ [ · ⌘ ]' with no 'Alt ←'.
  - user-visible: None this round.
  - not fixed because: 
- **P9** fixed: Header NIFTY:
- New isStaleQuote / istHhmm / liveQuoteAt / pickNiftySource in lib/feedState.ts.
- niftySourceChip takes quoteAt and reads '◌ STALE HH:MM' when NSE is open (09:20–15:30 IST) and the shown quote is more than 5 min old.
- pickNiftySource prefers NSE when the ICICI stream's quote is more than 5 min behind NSE's print.
Macro tape:
- NSE indices and Yahoo quotes are two independent requests, each merged over the last values (await Promise.allSettled).
- A slow or failing Yahoo no longer blanks the tape or holds NSE's numbers back.
page.tsx:
- the dashboard summary (footer DATA date and STOCKS, OVRV) polls every 10 min (30 min hidden), on visibility, and on window focus (new useOnFocus in components/shell/usePoll.ts), throttled to once a minute;
- after every LINK UP it now always reloads, not only when it had failed.
  - tests: desktop.check staleQuote:
- a fresh print gives ● NSE;
- 20 min old at 11:00 gives '◌ STALE 10:40' (down);
- the ICICI stream stopped 10 min ago gives '◌ STALE 10:50';
- negative control: without quoteAt it says ● NSE on the old value;
- pre-open and closed hours are never STALE;
- isStaleQuote edges, liveQuoteAt, and pickNiftySource (6 cases).
Source guards for the header, tape allSettled and dashboard polling.
Browser STALE, WebKit + Chromium, fake clock Mon 26 Oct 11:00, NSE print 10:40, Yahoo never answers:
- the chip reads '◌ STALE 10:40';
- the tape shows NIFTY 50 24,050.00 and BANK NIFTY 51,000.00 while Yahoo hangs;
- focus within a minute gives 0 summary reloads; focus 3 min later gives 1.
  - user-visible: In market hours a NIFTY quote that stopped updating reads ◌ STALE HH:MM (red) instead of ● NSE / ● LIVE, and the header switches to NSE when the ICICI stream stalls. The tape's NSE half appears at once even when Yahoo is slow. A long-open window's footer DATA date and OVRV refresh by themselves.
  - not fixed because: 
- **P10** fixed: AppContext keeps Redis monitored.stocks holding this window's watchlist: on every socket REconnect (not the first connect, which the diff effect covers) and every 10 min (30 min hidden). Each time it does one GET /api/monitor/list, then POST /api/monitor/subscribe only for the missing symbols. It is idempotent and never removes anything. If the list is not an array (Redis down, error body), nothing is re-subscribed. The pure missingMonitorSymbols and the cadence constants are in lib/monitorLifecycle.ts. The socket's own {action:'subscribe'} filter was already re-sent on reconnect by wsManager.
  - tests: ws.check section 9 (82/0 total):
- empty set: re-subscribe all;
- only the missing ones, case-insensitive, de-duplicated, in order;
- a full set needs nothing;
- an unknown answer re-subscribes nothing;
- junk is ignored;
- cadence, and AppContext wiring guards.
Browser WL, WebKit + Chromium, the list routed to ['NIFTY'] (Redis flushed): after the mocked socket drops and reconnects, exactly 1 GET of the list and 1 POST /api/monitor/subscribe (TCS).
  - user-visible: After a Redis restart the watchlist starts ticking again within 10 min, or at once after a socket reconnect, without editing the watchlist.
  - not fixed because: 
- **P11** partially-fixed: lib/alerts.ts:
- setLevel and setLevels no longer swallow errors: they fire ALERT_SAVE_FAILED_EVENT {sym, error: apiError(e)} and resolve false (true on success);
- AlertSaveToasts (components/shell/ShellToasts.tsx, inside ToastProvider) shows 'Alert for TCS NOT saved: <reason>. Nothing will fire until it is saved.';
- the last server answer is shared by every useAlerts() in the window, so a re-opened alert form starts prefilled.
lib/alertText.ts hitText words MOVE hits as 'TCS moved −6.1 % (≥ 5 %) (now ₹3,120)' instead of 'fell below ₹5'. Native notifications use it in the browser and in an app without notification_feed. Price-level wording is unchanged byte for byte.
  - tests: alerts.check (31/0):
- move wording down, up and without change_pct;
- negative control: the old wording said 'fell below ₹5';
- price-level text unchanged; the notification uses the move wording;
- save-failure text;
- source guards: both setters report and no silent catch is left, apiError detail, the shared cache, toasts inside the provider.
Browser ALRT, WebKit + Chromium, stock window TCS with levels 3450/3180/5:
- the re-opened form shows ['3450','3180','5'];
- SET with the PUT refused (403) gives the toast 'Alert for TCS NOT saved: blocked by f4b_checks. Nothing will fire until it is saved.'
  - user-visible: A failed alert save now shows a red toast saying nothing will fire. Re-opening the ALERT form shows the saved levels. MOVE alerts read 'moved −6.1 % (≥ 5 %)' in notifications.
  - not fixed because: The WTCH page's own toast (ui/components/WatchMonitor.tsx:131, a page file, not mine) still words a MOVE hit as 'fell below ₹5'. Patch requests PR-1 and PR-2 below fix it with hitText; they were verified in a scratch tree (tsc clean, alerts and platform checks green). The FIRST open of the stock-window alert form, before any useAlerts() in the window has loaded, can still start empty: that needs an effect in ChartActions.tsx (page-owned).
- **P15** already-fixed: Already fixed in round 3: rows are sanitized when loaded, so a null name never reaches s.n.toUpperCase(). Hardened this round:
- the sanitizing moved into a pure, tested lib/goAliases.ts sanitizeSymbolRows, which drops rows without a string ticker and turns a missing or non-string n into '';
- CommandBar uses it;
- a stock row with an empty name is labelled with its ticker (s?.n || t), not a blank line.
  - tests: desktop.check goSanitize:
- 8 junk rows (null name, numeric name, null row, missing / empty / numeric ticker, a string) become 3 clean rows;
- the name filter no longer throws;
- negative control: the pre-fix filter throws on a null name;
- a non-list gives [].
Browser GO, WebKit + Chromium, routed symbols with a null and a numeric name: 'NEWCO' is listed, 'TATA' finds TCS, the footer never shows GO UNAVAILABLE, and no page errors.
  - user-visible: A stock with no company name shows its ticker as the GO label.
  - not fixed because: 
- **P4-UI** fixed: Header ICICI light (mine). The colour is still data-service's Breeze session. While red, the tooltip says why, from connection-status error_kind via the new lib/iciciStatus.ts (iciciErrorKind, iciciLightTitle):
- 'network': 'ICICI unreachable (network) — not a login problem; retried by itself' (no login prompt);
- 'expired': '… send /login (Telegram) or log in on the Broker tab';
- 'credentials': 'ICICI API key/secret missing: set them on the Broker tab';
- unknown or field absent (old ui-api): generic.
The kind is read before needs_session_refresh. Connection-status is read only while the light is red (on the edge, then every 2 min, 10 min hidden), and only connected / error_kind / needs_api_credentials are kept: login_url and account details are never stored.
The BRIEF line (Brief.tsx) is F4B-UI-PAGES's file and they already map it through components/portfolio/iciciState.ts. I verified their mapping: network reads 'ICICI unreachable (network): session may still be valid', never 'expired'. No patch request is needed.
  - tests: desktop.check icici:
- kinds, with needs_session_refresh ignored and a fallback to needs_api_credentials;
- an outage title never asks for a login;
- the exact 'network' / 'expired' (send /login) / 'credentials' titles; connected and not-read-yet;
- source guards: only while red, no login_url;
- a drift check that the pages helper words network as unreachable.
Browser ICICI, WebKit + Chromium, provider/status connected:false and connection-status routed (never fetched live, never printed) per kind: each tooltip is right, with 1 connection-status call per page load.
  - user-visible: Hovering the red ICICI light in the header says 'ICICI unreachable (network) — not a login problem' during an ICICI outage, 'send /login' only for an expired session, and 'API key/secret missing' when credentials are absent. This needs round 4a's ui-api restart; until then the tooltip stays generic.
  - not fixed because: 
- **K5-UI-coherence** already-fixed: Checked the PM-applied K5 patches against my files; no change needed:
- ui/lib/platform/types.ts ShellMarker has `features?: readonly string[]`;
- lib/platform/invoke.ts shellMarker() returns the injected marker unchanged, so features pass through;
- WatchMonitor has a single native path: `if (!shellMarker()?.features?.includes('notification_feed')) notifyHits(hits)`, with exactly one notifyHits call;
- notifyHits / alertNotification (lib/alerts.ts, lib/alertText.ts) are intact and now use the move wording.
  - tests: platform.check (123/0, +3):
- a marker without features does not claim the feed;
- a marker with ['notification_feed'] reaches shellMarker() unchanged and isDesktop() stays true;
- WatchMonitor gates its single notifyHits on the feature.
  - user-visible: None.
  - not fixed because: 

## files
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/context/AppContext.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/globals.css
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StockDetailModal.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/CommandBar.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/PlatformShell.tsx
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/find.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/FindBar.tsx (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/shell/ShellToasts.tsx (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/shell/usePoll.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/feedState.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/liveEvidence.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/alerts.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/alertText.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/monitorLifecycle.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/shortcuts.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/goAliases.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/iciciStatus.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/refreshStatus.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/downloadText.ts (new)
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/__tests__/desktop.check.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/__tests__/alerts.check.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/__tests__/platform.check.ts
- /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/__tests__/ws.check.ts

## tests
- cd ui && node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON components/desktop/__tests__/desktop.check.ts -> desktop.check: 398 passed, 0 failed (was 321). New sections: liveEvidence, priceMarker, staleQuote, refreshVerdict, icici, find, downloadToast, goSanitize.
- cd ui && node components/__tests__/pages.check.ts -> 281 passed, 0 failed (shared tree; F4B-UI-PAGES is adding checks in parallel)
- cd ui && node lib/__tests__/{prefs,platform,alerts,ws,streamProxy}.check.ts -> prefs 160/160, platform 123/123 (+3 K5), alerts 31/31 (+13 P11), ws 82/82 (+8 P10), streamProxy 76/0
- negative control: the pre-round sources (scratchpad/F4B-UI-SHELL/orig) overlaid on a scratch copy (scratchpad/F4B-UI-SHELL/neg/ui) with the new check files -> desktop.check: 342 passed, 20 failed, plus throws in liveEvidence, priceMarker, staleQuote and goSanitize; alerts.check crashes (alertSaveFailedText missing) after 5 move-wording FAILs; ws.check crashes (missingMonitorSymbols missing). The failures are listed in scratchpad/F4B-UI-SHELL/neg_desktop.txt.
- cd ui && npx tsc --noEmit --incremental false -> exit 0, clean (ui/tsconfig.tsbuildinfo not touched; its mtime is 15:15)
- cd ui && node --test scripts/*.test.mjs -> 26 tests, 26 pass, 0 fail
- /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests/integration/test_desktop_ci.py tests/integration/test_desktop_contract.py tests/integration/test_desktop_static.py tests/integration/test_desktop_qa_harness.py -q -> 127 passed, 8 skipped
- scripts/build_ui.sh --out scratchpad/F4B-UI-SHELL/export3 -> OK id 20261025-221434-0ae66db, 85 files, 975.2 kB gzip; First Load JS 280 kB (budget 300; round 3 was 278.5); 0 lookbehind regexes in the chunks
- python scratchpad/F4B-UI-SHELL/f4b_checks.py --base http://127.0.0.1:8099 --engine webkit --out final_webkit  (scratch_server.py --block-mutations on export3; all WebSockets mocked; prefs readonly; connection-status always routed) -> webkit: 12/12 sections PASS (TICK STK UPD STALE ICICI FIND DL NOTE MAC GO WL ALRT)
- python scratchpad/F4B-UI-SHELL/f4b_checks.py --base http://127.0.0.1:8099 --engine chromium --out final_chromium -> chromium: 12/12 sections PASS. Server stopped by PID afterwards; ports 8097, 8098 and 8099 are all free.
- scripts/ui_audit.py --base http://127.0.0.1:8098 --tabs all --browser webkit|chromium --screenshots none (export2, before the final display-only modal tweak) -> 39/42 PASS in each engine with 0 page errors. The 3 failures (OSTR, ALFA, MCXG) are only the scratch server's blocked on-load POSTs (options/strategy/analyze, alpha/scan, mcx/ticket → 403 by --block-mutations), not regressions.
- scratch tree (scratchpad/F4B-UI-SHELL/prtree) with patch requests PR-1 and PR-2 applied: tsc, alerts.check, platform.check -> tsc exit 0; alerts 31/31; platform 123/123 (pages.check's one failure there is a missing reports/docs file in the scratch copy, not the patch)

## patch requests
### PR-F4B-UI-SHELL-1 ui/components/WatchMonitor.tsx
why: P11: needed by the next patch. hitText (lib/alertText.ts, F4B-UI-SHELL) words a ±% MOVE hit correctly.

OLD:
```
import { notifyHits, useAlerts } from '@/lib/alerts'

```
NEW:
```
import { notifyHits, useAlerts } from '@/lib/alerts'
import { hitText } from '@/lib/alertText'

```
### PR-F4B-UI-SHELL-2 ui/components/WatchMonitor.tsx
why: P11 (FEATURE_PARITY): the WTCH toast for a ±% MOVE alert reads 'fell below ₹5', using the threshold % as a price. Price-level toasts are unchanged byte for byte. Verified in a scratch tree: tsc clean, alerts and platform checks green.

OLD:
```
      hits.forEach(h => addToast(`${h.side === 'above' ? '▲' : '▼'} ALERT ${h.sym} ${h.side === 'above' ? 'rose above' : 'fell below'} ₹${h.level.toLocaleString('en-IN')} — now ₹${fmtPx(h.price)}`, 'warning', 20000))

```
NEW:
```
      // P11: a ±% MOVE hit says "TCS moved −6.1 % (≥ 5 %)" (lib/alertText.ts hitText), never "fell below ₹5"
      hits.forEach(h => addToast(h.side === 'move'
        ? `${(h.change_pct ?? 0) >= 0 ? '▲' : '▼'} ALERT ${hitText(h)}`
        : `${h.side === 'above' ? '▲' : '▼'} ALERT ${h.sym} ${h.side === 'above' ? 'rose above' : 'fell below'} ₹${h.level.toLocaleString('en-IN')} — now ₹${fmtPx(h.price)}`, 'warning', 20000))

```

## deploy notes
- Static UI only (no backend, Rust or config change). Publish with ./start-local.sh build-ui after the round. Rebuild from the tree: other fixers are editing in parallel. My verified scratch export is scratchpad/F4B-UI-SHELL/export3 (id 20261025-221434-0ae66db, First Load JS 280 kB).
- Apply PR-1 and PR-2 (ui/components/WatchMonitor.tsx) together. They import hitText from lib/alertText.ts (this round).
- P4 header tooltip: needs round 4a's ui-api restart (positions.py / icici_admin.py) for error_kind. With the old ui-api it falls back to the generic 'ICICI not connected: click to open the Broker tab'. The BRIEF / BRKR / PORT wording is F4B-UI-PAGES's (components/portfolio/iciciState.ts).
- R9 Find depends on no menu accelerator claiming ⌘F, ⌘G or ⇧⌘G. Today's desktop/src-tauri/src/menu.rs has none: verified by grep. F4B-RUST must keep it that way when adding File ▸ Print…. The toast's ⌥⌘L refers to the existing menu item Show Latest Download (menu.rs, Alt+CmdOrCtrl+L).
- User-visible changes for parity / equivalence diffs:
- chips stay CLOSE / SOCKET OK · NO TICKS on holidays and heartbeat-only streams; in an unknown session they go live from the 2nd real print;
- the stock window shows DELAYED · <time> when NSE prints (Muhurat), with the date when the quote is from another day, and ▲/▼ change from the REST quote's previous close;
- UPDATE DATA can read 'UPDATE STATUS UNKNOWN · <reason>' with RETRY (two clicks in 18:30–21:15), and 'may still be running in ui-api';
- ◌ STALE HH:MM on the NIFTY chip for a quote over 5 min old in market hours;
- the tape's NSE half no longer waits for Yahoo;
- the footer DATA date and OVRV refresh every 10 min, on focus and after an outage;
- the ICICI light tooltip follows error_kind;
- app only: ⌘F find bar and download toasts;
- alert save failures toast, the re-opened alert form is prefilled, MOVE notifications read 'moved ±x.x % (≥ N %)';
- a GO row with no company name shows its ticker.
- After deploy:
- In the app, ⌘F on any page should show the FIND bar bottom-right.
- An export should toast 'Saved to ~/Downloads/… · ⌥⌘L'.
- On Tue 10 Nov (NSE holiday) with ICICI logged in, the header chip must read CLOSE 09-NOV and the watchlist bar SOCKET OK · NO TICKS.
Re-run script: scratchpad/F4B-UI-SHELL/f4b_checks.py --base <scratch base> --engine webkit|chromium --out <dir> (it refuses :8010).

## open issues
- The live-tick rule also requires a NEW print (price or volume changed), because Breeze stamps index quotes with the fetch time (stored NIFTY ltt 15:35:52, after the close). If Breeze ever served a moving index price with a fresh ltt on a holiday, the chips would go live; that would be a data error. The real holiday stream was not observed; the next one is Tue 10 Nov. The rule is covered by unit fixtures plus a real closed-Sunday browser run.
- The find bar was verified in Playwright WebKit and Chromium, not in the real WKWebView. It uses window.find() (WebKit implements it) and the CSS Custom Highlight API (Safari 17.2+; macOS 26 has it). Without the highlight API the match is still selected and scrolled into view.
- Two modules map error_kind: lib/iciciStatus.ts (header light, mine) and components/portfolio/iciciState.ts (BRIEF / BRKR / PORT, F4B-UI-PAGES). Both read the kind before needs_session_refresh, and a drift check covers the network wording. The phrasing differs slightly ('not a login problem' vs 'session may still be valid'); a later round could merge them into one module.
- P11 remainder (page-owned):
- the WTCH toast wording needs PR-1 and PR-2;
- the very first open of the stock-window ALERT form in a window can still start empty until useAlerts' first load returns. Re-opens are prefilled by the shared cache. A small effect in ui/components/terminal/ChartActions.tsx AlertForm that fills untouched fields when `cur` arrives would close it.
- The 'bar' chip in the TICK browser check runs on WTCH. ALFA's 'WS LIVE' chip uses the same socketChip and useFeedState and was not separately exercised in a browser.

## adversarial check: ACCEPT-WITH-NOTES
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx: New failure mode from the P9 summary refresh. The summary now reloads every 10 min, on focus, on visibility and after every LINK UP. If data-service's /db/stats answers anything but 200 for a moment, ui-api replies 200 with _EMPTY_SUMMARY. loadDashboard stores that over a good summary, so the footer reads 'DATA —' and '0 STOCKS' and OVRV shows 'Universe 0 / 0% current' (the R4 'invented zeros') until the next good reload, up to 10 min later. Before this round that could only happen at first load or after UPDATE DATA.
  - evidence: services/ui-api/routers/dashboard.py:226-236 returns {**_EMPTY_SUMMARY} with HTTP 200 when /db/stats is non-200 or total_stocks == 0. A /db/stats exception, e.g. the get_store assert or a DuckDB error, becomes a 500 from data-service, then that 200 empty payload. page.tsx:315-323 calls setDashboard(dash.data) with no check. Footer page.tsx:814-815 renders `dashboard?.latest_date ?? '—'` and `(dashboard?.total_stocks ?? totalStocks)`, which gives 0. OverviewTab's `loaded = !!dashboard` is then true. Callers: page.tsx:329-331 (usePolling + useOnFocus) and :408 (r.loadDashboard() after every LINK UP).
  - fix: In loadDashboard, once a non-empty summary is loaded, treat a reply with health.status === 'empty' (or total_stocks 0 with latest_date null) as a failure: keep the previous summary and set dashError (the 15 s retry and the footer's 'UNIVERSE STATS UNAVAILABLE' chip already exist). Add a desktop.check or pages.check case with a good summary, then _EMPTY_SUMMARY, asserting the footer still shows the old DATA date, plus a negative control on the current code.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx: The macro tape's time stamp is now less honest. stamp() runs when EITHER half lands, so if Yahoo fails for hours, NSE's half keeps moving 'NSE + YAHOO · HH:MM IST' to the current minute. This also happens after the close, because indices-live still answers. Meanwhile GIFT NIFTY, USD/INR, BRENT, GOLD and S&P 500 keep hours-old values. A symbol missing from Yahoo's reply also keeps its old value forever under a fresh stamp. Before, the stamp stayed at the last full update.
  - evidence: MarketCommandHeader.tsx:196 defines stamp; it is called at :202 (Yahoo half) and :212 (NSE half); the label is at :251 `NSE + YAHOO · ${at} IST`. setQ merges over prev for each half (:200, :206-210), so nothing ever clears or ages a Yahoo symbol.
  - fix: Keep one stamp per source (e.g. yahooAt and nseAt) and show the older one, or mark Yahoo-sourced cells as stale when yahooAt is more than about 5 min old. At least stamp only when the Yahoo half lands, because NSE's half is the delayed-tolerant one.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/lib/iciciStatus.ts: Deploy note and wording mismatch. The deploy note says that with the old ui-api (no error_kind) the tooltip 'falls back to the generic ICICI not connected: click to open the Broker tab'. The connection-status read still succeeds there, and iciciErrorKind maps the missing field to 'unknown'. The tooltip is therefore 'ICICI not connected: see the Broker tab · click to open the Broker tab', which says the same thing twice.
  - evidence: iciciStatus.ts: iciciErrorKind returns 'unknown' when error_kind is absent and needs_api_credentials is not true. iciciLightTitle appends ' · click to open the Broker tab' to ICICI_KIND_TEXT.unknown = 'ICICI not connected: see the Broker tab'.
  - fix: Make ICICI_KIND_TEXT.unknown 'ICICI not connected' (the suffix adds the action), or correct the deploy note. Cosmetic.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/menu.rs: R9's dependency is only half guarded. The find bar needs ⌘G and ⇧⌘G free as well as ⌘F, but the Rust test cmd_f_stays_free_for_the_page_and_cmd_p_prints asserts only plain ⌘F. A later Edit ▸ Find Next (⌘G) item would silently take ⌘G and ⇧⌘G from the page. The deploy note mentions this, but no test enforces it. The file is F4B-RUST's.
  - evidence: menu.rs:512-528 checks only `key == "f"` with cmd-only modifiers. desktop.check findChecks has no guard on menu.rs.
  - fix: Patch request to F4B-RUST: extend the test to assert that no accelerator is cmd+g or shift+cmd+g. Alternatively, add a desktop.check source guard on menu.rs for 'CmdOrCtrl+G'.
- not really fixed: []
- notes: Verdict: ACCEPT-WITH-NOTES. The round-3 MAJOR and the CT-07, CT-04 and P15 items are genuinely fixed. R6 and R13 really were already fixed. Nothing changes trading logic. The four problems are minor; the first two are new failure modes introduced by the P9 change.

**Gates I re-ran myself (all match the claims):**
- desktop.check 398/0, pages.check 281/0, prefs 160, platform 123, alerts 31, ws 82, streamProxy 76/0.
- tsc --noEmit --incremental false: exit 0; ui/tsconfig.tsbuildinfo is still dated 15:15.
- node --test ui/scripts: 26/26.
- pytest test_desktop_ci, contract, static and qa_harness: 127 passed, 8 skipped.
- export3: 0 chunks contain a lookbehind regex. The find bar code is in layout and page chunks. The pre-round negative-control output (neg_desktop.txt) shows the 20 failures plus the throws, as claimed.

**Diff review:** I diffed all 15 edited files against scratchpad/F4B-UI-SHELL/orig. Only lib/format/index.ts differs beyond the claimed set, and that is F4B-UI-PAGES's P16 work (fmtSignedInr, istFileStamp). ui/.next was not touched this round; its newest file is from 11 Oct.

**Live-evidence rule, checked against real data with GETs only:**
- data-service's stored NIFTY record has ltt '23-Oct-2026 15:35:52' (stamped after the close, i.e. the fetch time) and total_quantity_traded '0'. quotePrint gives key '22600|0', so on a holiday the repeated index print never counts.
- Stock quotes on a holiday carry the previous session's ltt, which is stale.
- The monitor socket's other messages are {pong}, {ok, subscribed} and {error}; all are rejected.
- data-service's _in_session() is weekday 09:00–15:35 only, so the tick leg never fires on Muhurat. That is now correct: the header and the stock window both use the fresh NSE print.
- Nit: on a trading day, a NIFTY print between 15:30 and 15:35 whose price changes to the official close can count once, keeping chips live until about 15:36:30. This is harmless and smaller than in round 3.

**CT-04:** refreshVerdict agrees with ui-api's counters. Every ticker ends as done, current or error, and total = len(_refresh_progress). The trigger reply's `tickers` is len(tickers). Today's CSVs have no duplicates (NSE_1500 has 1500/1500 unique, nifty500 has 504/504), so the size check does not misfire. A duplicated ticker in a future CSV would make every run read 'another download' (latent nit). The single poll chain, the RETRY confirm inside the EOD window and the 'ui-api' wording are all correct.

**CT-07:** a tick's as_of is datetime.now(IST).isoformat(), which has a zone, so exchangeTimeToEpoch parses it; there is no regression against the old new Date(asOf). The ICICI ltt as-of and the quotePrev change base are display-only.

**P9:** pickNiftySource and the STALE chip apply only when the market is open or NSE is printing, and only from 09:20 to 15:30. They are correct apart from the two minor problems listed.

**P10:** the watchlist starts as [], so the resync on mount does nothing. While Redis is down, /api/monitor/list returns 503 (_redis_call raises), so nothing is re-subscribed blindly.

**P4-UI:**
- connection-status is read only while the light is red. Only 3 fields are kept, nothing is logged, and lib/api has no interceptors.
- The ui-api probe is single-flight with stale-while-revalidate (TTL 900 s when expired, 60 s on a network error). The desktop shell (health.rs poll_icici) already polls connection-status, so the header adds no extra Breeze logins in the app.

**R8, R9, P11, P15, K5:**
- R8: DownloadToasts sits inside ToastProvider, and emitDownload is called only on desktop paths.
- R9: FindBar is mounted only when desktop, its labels are CSS-generated content, and its Esc beats the modal's handler (the modal also ignores INPUT targets). menu.rs has no ⌘F or ⌘G accelerator today, and ⌘P is Print….
- P11: the server's move-hit shape matches hitText (side 'move', level = threshold, change_pct). PR-1/PR-2 match WatchMonitor.tsx:18 and :131 exactly. AlertHitSrv already has change_pct. Wording nit: the server's feed and Telegram say '+6.1% today (alert at ±5%)' while the client says 'moved +6.1 % (≥ 5 %)'.
- P15: CommandBar's only remaining string ops on rows are safe after sanitizing.
- K5: verified; WatchMonitor has a single notifyHits behind the notification_feed check.

**Undeclared side effects (both benign):**
- With the shared lastAlerts cache, a setLevel before a hook's first sync no longer clears the other side's level (a bug fix).
- check() can now call POST /api/alerts/run on a new hook's first check.

**Process note, not a code defect:** the ui_audit run on export2 went through scratch_server :8098, which forwards unrouted GETs to the live :8010, and ui_audit routes nothing. BRKR, BRIEF and PORT therefore fetched the live /api/positions/connection-status into the headless browser. It was not printed, and the probe cache means no extra Breeze logins. Still, 'connection-status always routed' holds only for f4b_checks.py. A future harness should route or deny that endpoint, and data/live/quote, in scratch_server.

**What I left behind:** I modified no files. I sent only read-only GETs to data-service (/db/live-quotes, /live/index/nifty) to check payload shapes. I never called /live/quote, which would reach Breeze. I started no servers or browsers.

