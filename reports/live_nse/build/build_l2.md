# Live NSE round 2 — results and checks (5 Nov 2026, wf_234c58a7-689)

# L2-API

## summary
All three parts of the brief are built and tested. Nothing on the live stack was contacted: there were no requests to :8001, :8010 or :8008, no Yahoo, no NSE and no Breeze. Every suite ran with DATA_SERVICE_URL pointed at a dead port and a socket guard that refuses those ports and any non-loopback host. The only blocked attempts were the known, pre-existing ones from test_cache_warm.

(1) **Batch stored-close route.**
- data-service: new route `GET /db/closes?symbols=&days=&tail=`, one route block in main.py.
  - Takes up to 300 NSE symbols or index names and reads them in one DuckDB read.
  - Stock closes come from nse_bhavcopy, EQ/BE rows with EQ preferred. They are split/bonus-adjusted with the exact same `shared.nse_panel` functions (`pick_equity_rows` + `adjust`, using the splits table and the gap rule). This is proved equal to `load_panel` on the same rows.
  - Point in time: only sessions stored up to today.
  - `meta` per symbol: the company name from NSE's EQUITY_L copy (read-only), the high/low over the whole window, first/last date, ex-dates. `missing` gives a reason per symbol.
  - Indices come only from index_ohlc_daily (NSE's daily file), never from market_index_daily, whose rows can be Yahoo's.
  - A sync route, so it runs in the threadpool.
- ui-api: new route `GET /api/market/closes` in markets.py.
  - SWR cache: refresh after 10 min, never older than 1 h, single flight.
  - Body is the contract `{as_of, source: 'nse_bhavcopy', series}` plus `meta`, `missing`, `aliases` and a `note`.
  - Accepts '.NS' and Yahoo-style index tickers (`^NSEI` → 'NIFTY 50').
  - Bad requests get a 422 before any upstream call; upstream rows are validated; a missing route gives a 503 with a deploy hint.

(2) **EVTS/BRF results-reacting.** Every filer and the NIFTY 50 are now priced by the live hub in one batch. The old `/db/live-quotes` heatmap read, `/db/nifty-live` and the `get_quotes` path (which `LIVE_QUOTES_NSE=0` sends to Yahoo) are gone.
- Each row keeps all its old keys and adds source, state, age_s, ltt and reason. The top level adds market, nifty and price_source.
- A change counts as today's reaction only when the row is live or delayed, or is the session's close dated today. A stale EOD row's change is yesterday's and is never shown.
- An NSE holiday (the hub's session_date is not today) reads as phase 'closed' with no reaction.
- Pre-open rows say they are NSE's auction price (IEP), aged from the book's own timestamp.

(3) **news-scanner quotes base layer for '.NS'.**
- The name, 22-session spark and 52-week range now come from one `/db/closes` batch read per request (a micro-batcher in front of the per-symbol SWR cache). It replaces one `/db/security/{sym}/history` read per stock.
- The name is NSE's EQUITY_L name; it was null before.
- The NSE index tickers `^NSEI`, `^NSEBANK`, `^INDIAVIX` and `^CNXIT` on this route now answer from the live hub too (round 1 left them on Yahoo), keyed as asked.
- No Yahoo host is contacted: proven with the real Yahoo fetcher running behind a fake transport. Positive control: `^GSPC` does reach Yahoo's hosts. Negative control: the rollback lever puts RELIANCE.NS back on Yahoo and the transport sees it.

**Measured** on a synthetic temp DuckDB with 3,000 symbols × 900 sessions: `/db/closes` takes 71 ms / 66 KB for 60 symbols × 366 d with tail 22, 332 ms for 300 symbols, and 25–35 ms for COMP (9 symbols).

**Status.** ui-api suite 1318 passed. Core suite: 1275 passed, 9 skipped, and 1 failure in tests/integration/test_live_gates.py. That gate asserts results-reacting goes through `get_quotes`, which is exactly the path this brief removes. The patch request is below; with it applied in a scratch tree the gates file is 77 passed, and a mutation that brings back the old `get_quotes` path is caught.

## resolved
- [done] (1) data-service GET /db/closes?symbols=A,B&days=N: nse_bhavcopy EQ/BE, split/bonus-adjusted the way shared/nse_panel does it, PIT
  - One new route block in main.py, right after /db/security/{symbol}/history. It contains:
- `_closes_symbols`: canonical names; 422 on a bad or empty list or more than 300 symbols.
- `_closes_names`: EQUITY_L names from data/reference/nse_equity_list.csv, read-only, reloaded only when the file changes.
- `_closes_frames`: one locked read of nse_bhavcopy EQ/BE rows plus the splits table (SYM and SYM.NS); index_ohlc_daily for index names, or a 'not deployed' note when that table is missing.
- `_closes_payload`: runs `pick_equity_rows` + `adjust` outside the lock and builds the body.
- The route `db_closes`: days 5..3700 calendar days, an optional tail, and a symbols × days budget of 120,000 (422 above it).

Body: {as_of (newest stored session date), source 'nse_bhavcopy', from, to, tail, series {SYM: [{date, close}] oldest first}, meta {SYM: {source nse_bhavcopy|nse_index_file, name, first_date, last_date, sessions, high, low (adjusted, whole window), last_series, actions [{date, k}]}}, missing {SYM: reason}, generated_at}.
  - tests: tests/unit/test_live_closes.py, 14 passed:
- Adjusted closes never draw an ex-date as a crash (1:1 bonus via the gap rule; 2-for-1 split via the splits table under TCS.NS).
- Negative control: the raw closes do show a -50% day.
- Identical to `shared.nse_panel.load_panel` on the same rows.
- PIT: a future-dated row is excluded; EQ beats BE; BE-only names are served.
- `tail` trims the series but not the window's high/low.
- EQUITY_L names; indices from index_ohlc_daily.
- `missing` reasons; BZ-only and market_index_daily-only (Yahoo) rows are not served.
- 422s are raised before any read.
- The new batch read gives the same 22-point spark and 52-week high/low as the old per-symbol /db/security/{sym}/history path.
- No socket is opened.

Mutation runs: removing the adjustment fails 1 test; serving BZ rows fails 1 test.
- [done] (1) ui-api GET /api/market/closes (SWR 10 min) returning {as_of, source:'nse_bhavcopy', series:{SYM:[{date, close}]}}
  - New section at the end of routers/markets.py.
- Symbols are canonicalised with `live.nse_name` ('.NS' dropped; ^NSEI/^NSEBANK/^INDIAVIX/^CNXIT mapped to NSE names).
- 422 for more than 300 symbols or over the symbol-day budget, with no upstream call.
- One SWRCache keyed by (sorted symbols, days, tail): refresh after 600 s, max age 3,600 s, single flight.
- `coerce_closes` validates the upstream body: finite positive closes on ISO dates, one per date, oldest first; meta trimmed to known small fields; every asked symbol is either in series or in missing.
- The response follows request order and adds `aliases` and a `note` ('end of day … never live').
- An upstream 404 (route not deployed) or 5xx gives a structured 503 `upstream_down` with a hint.
- X-Cache headers are set.
  - tests: test_live_market_closes.py, 11 passed: contract body, order, aliases, missing; one read per 10 min, then a stale-while-revalidate background refresh, then a miss past 1 h; tail passed through; four 422 cases with zero upstream calls; 404 and 500 upstream give a structured 503; malformed rows dropped; concurrent identical requests share one read; static check that no Yahoo fetcher is reached. The gate patch below adds a call-graph check (with a mutation control).
- [done] (2) EVTS/BRF results-reacting: price filers from /api/live/quotes (never Yahoo), keep response keys, add source/age/state
  - `_results_reacting` in markets.py:
- Prices every filer plus 'NIFTY 50' with one `live.hub().quotes(...)` call (Breeze tick → NSE website → stored close).
- No longer calls `news_scanner.get_quotes`, `/db/live-quotes` (26 NSE heatmap lists) or `/db/nifty-live`.
- New pure helpers:
  - `todays_move`: live/delayed rows count, or the session's close dated today.
  - `price_fields` / `preopen_fields` / `price_summary`: the labels added to rows and the top level.
- An NSE holiday (hub market closed with a session_date that is not today) gives phase 'closed' with no reaction.
- Pre-open rows: source 'nse_api'; state 'delayed' when ≤ 90 s old, else 'stale'; the reason names NSE's pre-open auction (IEP).
- A pinnable clock `_react_now()` was added for tests.
- Rows keep every key the UI reads and add source, state, age_s, ltt and reason. The top level adds market, nifty and price_source {sources, max_age_s}.
  - tests: test_live_results_reacting.py, 17 passed:
- In session: live, delayed, stale, unavailable and other-session-close rows are labelled right; a stale EOD row's change (yesterday's) is never shown; vs_nifty is computed from the hub's NIFTY row.
- One hub read covers every filer plus the index; zero Yahoo; zero /db/live-quotes and /db/nifty-live reads.
- Negative control: the old get_quotes path under LIVE_QUOTES_NSE=0 does reach the Yahoo spy, while results-reacting does not.
- After the close: today's close counts and a 15:45 filing reacts next session.
- Holiday; pre-open labels aging from delayed to stale; nothing priced before 09:00.
- 11 `todays_move` cases.

The existing test_results_reacting.py (5) still passes.
- [done] (3) news-scanner quotes base layer for '.NS': name, 22-session spark, 52-week high/low from stored NSE data; live price from the live service; prove with a fake transport that no Yahoo host is contacted
  - Checked first: the round-1 spark and 52-week range already came from the bhavcopy, and the name was null.

Changes in routers/live.py:
- `EodContext` gained `name` and `source`.
- `eod_context_from_closes` / `eod_contexts_from_closes` replace the per-symbol history parser.
- `ClosesBatcher` merges all per-symbol context fetches started inside 5 ms on a loop into one `/db/closes?days=366&tail=22` read (at most 300 symbols). A failed read fails only that batch. A 404 (route not deployed) stops reads for 60 s.
- Index names now get a context too.
- `news_row` takes the name from EQUITY_L, else the live row's own name, else the index's NSE name; it adds `eod_source`; a `key` keeps the asked ticker.
- New `NSE_INDEX_TICKERS` map (^NSEI/^NSEBANK/^INDIAVIX/^CNXIT) and `nse_name()`.
- Module docstring updated.

news_scanner.get_quotes now also routes `NSE_INDEX_TICKERS` to the live hub (rollback lever `LIVE_QUOTES_NSE=0` still restores Yahoo); docstrings updated.
  - tests: test_live_news_quotes.py, 19 passed. New or changed tests:
- One stored-close read serves every symbol of a request, including ^NSEI with nse_index_file; 'not stored' is cached.
- Negative control: a batcher limited to one symbol per read makes N reads.
- A 404 backoff that resumes after 60 s.
- ^NSEI/^CNXIT come from the hub keyed as asked, while BSE symbols (.BO, ^BSESN) stay on Yahoo.
- The kill switch puts the indices back on Yahoo.
- A deciding read of ^NSEI never gets a stale price.
- Wire-level proof with the REAL Yahoo fetcher behind the fake transport: zero Yahoo hosts for RELIANCE.NS/TCS.NS/INFY.NS/^NSEI/^NSEBANK/^INDIAVIX; positive control (^GSPC reaches finance.yahoo.com); negative control (LIVE_QUOTES_NSE=0 puts RELIANCE.NS on finance.yahoo.com, seen by the transport).

test_live_support.py's FakeDataService gained /db/closes (+ `closes()` helper, `closes_calls()`); its hub tests still pass.
- [partial] ui-api suite green, live gates kept green (and added to)
  - ui-api suite is fully green. The live gates have one failure in the existing tests: `test_the_known_nse_callers_still_pass_through_get_quotes` asserts that results-reacting calls `get_quotes`, which is the Yahoo-capable path this brief removes. That file is not mine, so the fix is the patch request below. It inverts the assertion and adds a new S1 test: results-reacting reaches /live/quotes and no Yahoo fetcher; /api/market/closes reads /db/closes and no Yahoo fetcher.
  - tests: Patched copy in /Users/sudheer/.suryadhana_pm_scratch/live/L2-API/tree: 77 passed (76 + 1 new). Mutation script /Users/sudheer/.suryadhana_pm_scratch/live/L2-API/mut/gate_mutation.py: on the real tree, results-reacting has no Yahoo sinks and reaches /live/quotes; the mutant (`get_quotes` with '.NS' again) shows sink news_scanner._yahoo_chart and a markets caller, so both rules catch it.
  - reason: test_live_gates.py is outside L2-API's owned paths; the PM applies the patch request.

## contract_notes
- /db/closes body (data-service). The contract keys are {as_of, source: 'nse_bhavcopy', series: {SYM: [{date, close}]}}. Extras:
- from, to (window dates), tail, generated_at.
- meta {SYM: {source: 'nse_bhavcopy' | 'nse_index_file', name, first_date, last_date, sessions, high, low, last_series, actions: [{date, k}]}}.
- missing {SYM: reason}.
Rules:
- A symbol with no stored rows is absent from series and listed in missing.
- as_of is a DATE (the newest stored session among the answered rows), not a timestamp.
- Params: symbols ≤ 300; days = calendar days back, 5..3700, default 365; tail = keep only the last N sessions (meta high/low still cover the whole window); budget symbols × days ≤ 120,000 (422 above it).
- Series filter (deviation from shared.nse_panel). The brief says EQ/BE, so BZ (trade-to-trade) rows are excluded, matching /live/quotes' EOD rows. shared.nse_panel's research panel includes BZ. Otherwise the adjustment is identical (pick_equity_rows + adjust); splits rows filed as SYM.NS are mapped to SYM.
- Back-adjustment is relative to the newest session in the window: an ex-date inside the window rescales the older closes in that window, the same as /db/security/{sym}/history and nse_panel.
- Indices in /db/closes come from index_ohlc_daily only (NSE's ind_close_all file or the valuation-history close), never market_index_daily (NIFTY50 / INDIAVIX rows there can be Yahoo's). Index meta high/low can be null where only closes were loaded. Before Terminal v2's table is deployed, an index reads missing: 'index_ohlc_daily (NSE's daily index file) is not deployed on this data-service'.
- /api/market/closes (ui-api) body:
- The data-service body (validated) plus `aliases` {asked spelling: NSE name} and a `note` ('end of day … never live').
- Keys are canonical NSE names in request order: 'infy.ns' → 'INFY', '^NSEI' → 'NIFTY 50', '^CNXIT' → 'NIFTY IT'.
- Errors: 422 code invalid (bad symbol, over 300, over budget) with no upstream call; 503 code upstream_down with a deploy hint when data-service has no /db/closes (404) or fails.
- SWR: refresh after 600 s in the background, never served older than 3,600 s; X-Cache / X-Cache-Age headers.
- Advice for LV-UI / L2-UI (seen in their useNseBase.ts / nseBase.ts). The NSE base layer asks days=366 with no tail for up to 300 symbols: about 250 points × 300 symbols, roughly 2–3 MB. Passing tail=22 and reading meta.high / meta.low (adjusted, whole 366-day window) and meta.name gives the same spark, 52-week range and name at about a tenth of the payload. Measured: 300 × 366 d with tail 22 is 332 KB / 332 ms on a synthetic DB.
- news-scanner quotes ('.NS'). Changed from round 1:
- name = NSE's EQUITY_L company name, else the live row's own name; it was null before.
- New key eod_source ('nse_bhavcopy' | 'nse_index_file').
- The spark / 52-week range / prev_date / eod_as_of semantics are unchanged; they now come from /db/closes in one batch read per request instead of N /db/security/{sym}/history reads.
- Deviation from round 1, closing its checker's minor finding: on /api/news-scanner/quotes the NSE index tickers '^NSEI', '^NSEBANK', '^INDIAVIX' and '^CNXIT' (NIFTY IT) now answer from the live hub with zero Yahoo calls.
- Rows are keyed as asked; resolved_symbol is the ticker; name is the NSE index name; exchange NSE; currency INR.
- spark comes from index_ohlc_daily (empty until that table holds history; never Yahoo).
- The controller's fresh=1 NIFTY fallback is therefore priced by NSE/Breeze or not at all.
- '^BSESN' and '.BO' stay on Yahoo (BSE).
- LIVE_QUOTES_NSE=0 puts the indices back on Yahoo along with '.NS'.
- results-reacting response. Every legacy key is kept.
- Row additions: source (breeze_ws | nse_api | eod | null), state, age_s, ltt, and reason when there is one.
- Top-level additions: market (the hub's {state, session_date}, or null outside the session), nifty {source, state, age_s, ltt}, price_source {sources: {source|none: n}, max_age_s over rows that show a change}.
- Pre-open rows use source 'nse_api' (NSE's pre-open book; not a new enum value), state 'delayed' when ≤ 90 s past the book's timestamp else 'stale', and a reason naming the IEP.
- Rows with no price (closed phase, holiday, not in the pre-open book) have source/state/age_s/ltt null and a reason.
- An NSE holiday reports phase 'closed' (the UI's type has no 'holiday').
- todays_move rule (results-reacting):
- A change is shown only for state live or delayed whose date (ltt's IST date, else `date`) is today or unknown, or state closed whose date is known and is today.
- A stale EOD row in session carries the previous session's change and is never shown.
- The same rule prices the NIFTY 50 for vs_nifty.

## deploy_notes
- Deploy data-service and ui-api together tonight (21:37, outside both freeze windows) in the RUNBOOK order: stop ui-api → restart data-service and wait for /ready 200 → start ui-api. Otherwise data-service comes back READ-ONLY.
- If ui-api is deployed without the new data-service:
- /api/market/closes answers 503 upstream_down with the hint 'deploy data-service with the live-NSE round 2 build'.
- '.NS' news quotes still price (from /live/quotes, also new in that build) but carry no name, spark or 52-week range from storage. The batcher then asks /db/closes at most once a minute.
- No Yahoo fallback either way.
- Apply the gate patch requests (tests/integration/test_live_gates.py) before declaring the core suite green: today it is 1 failed / 1275 passed / 9 skipped; with the patch, that gates file runs 77 passed.
- Index sparks (^NSEI, ^NSEBANK, ^INDIAVIX, ^CNXIT on the news-scanner route; 'NIFTY 50' on /api/market/closes, used by COMP's benchmark) need index_ohlc_daily history: Terminal v2's nightly ind_close_all file and/or fo_iv `load_index_history_csv`. Until it has ≥ 22 sessions those sparks are short or empty (honest; never Yahoo).
- Load changes after deploy:
- results-reacting no longer reads /db/live-quotes (the 26-list NSE heatmap, the heaviest NSE call) or /db/nifty-live every 30–60 s. NSE website load from that panel drops to the hub's demand-driven poller.
- Cold WTCH, MKT-map and news-dock loads cost one /db/closes read per request (≤ 300 symbols) instead of one history read per stock.
- Breeze subscription demand. results-reacting asks the hub for every filer, as round 1 already did for non-heatmap filers through get_quotes, and asking ensures a subscription. On a peak results day (300+ filers) the filers compete with hover/WTCH names for the ≥ 100 on-demand slots; data-service keeps pins first, then the most recent requests. Filers beyond the cap, outside NSE's heatmap lists and beyond NextApi's 20 names read 'stale' and show no change, never a Yahoo price. Watch /live/status subscribed and no_first_tick during results season.
- No new env var, dependency or job. The /db/closes route reads data/reference/nse_equity_list.csv read-only (refreshed by scripts/refresh_instrument_reference.py); it is re-read only when the file changes.

## open_issues
- The gate fix is a patch request (test_live_gates.py is not L2-API's file). Until it is applied, the core suite has 1 failure: the inverted D10 assertion.
- /api/news-scanner/chart/{SYM}.NS (the news dock's NewsChart and stock charts) still reads Yahoo daily/intraday bars. It is outside this brief, which covered the quotes base layer and the batch closes route. Daily ranges could be served from /api/market/closes or /db/security/{sym}/history; intraday needs a Breeze or NSE source.
- Consumers outside my paths still print price/change_pct without state for '.NS' rows from the news-scanner route (round-1 checker minor: scripts/telegram_bot.py fmt_quote/fmt_book, scripts/master_controller.py closing note, scripts/daily_wrap.py). A stale EOD row's change during the session would read as today's move there.
- results-reacting's previous trading day (the 'since' cutoff) still skips only weekends, not NSE holidays. This is pre-existing; the hub's market.session_date could replace it.
- The EVTS/BRF panels do not yet render the new per-row source/state/age_s or the top-level price_source in a SourceChip. That is UI work for LV-UI/L2-UI; the data is in the response.
- test_cache_warm.py (pre-existing, not mine) still attempts real network calls to query1.finance.yahoo.com, news.google.com, FRED and treasury on every unguarded ui-api run. My runs refused them with a socket guard (/Users/sudheer/.suryadhana_pm_scratch/live/L2-API/plug/netguard.py). A conftest-level guard in services/ui-api/tests is still recommended.
- The live data-service was not probed (no GET at all), so /db/closes latency on the real 4.4 GB nse_bhavcopy is estimated from a synthetic 2.7 M-row temp DB. Re-measure once after deploy with one paced GET, e.g. symbols=TCS,INFY&days=366&tail=22, and one 300-symbol call.

## adversarial check: **ACCEPT-WITH-NOTES**
- [minor] tests/integration/test_live_gates.py: The core suite fails until the PM applies L2-API's two patch requests. L2-API correctly moved results-reacting (D10) off news_scanner.get_quotes, which inverts an existing gate assertion.
  - evidence: Real tree, run with a socket guard: core gives 1 failed / 1275 passed / 9 skipped. The failure is TestNoYahooForNsePricesS1::test_the_known_nse_callers_still_pass_through_get_quotes. I built my own scratch tree (/Users/sudheer/.suryadhana_pm_scratch/live/L2-API-CHECK/tree) and applied both patches from PATCH_REQUESTS_L2-API.json; each 'old' string occurs exactly once. Result: 77 passed. Mutant tree (tree2, markets.py calling get_quotes with '.NS' again): both the inverted rule and the new test_results_reacting_and_stored_closes_read_nse_only fail (2 failed, 75 passed). The patch makes the gate stricter, not weaker.
  - fix: PM: apply both patch requests to tests/integration/test_live_gates.py before committing. The core suite is then green and the gates file has 77 tests.
- [minor] services/ui-api/routers/live.py: news_row reports high_52w / low_52w as today's day high / low whenever the stored context is missing. That happens on a cold /db/closes read slower than CTX_WAIT_S = 1.5 s, during the 60 s 404 backoff, or for a symbol with no stored history. The fields are still labelled as the 52-week range. L2-API now routes ^NSEI, ^NSEBANK, ^INDIAVIX and ^CNXIT through this path, and their context (index_ohlc_daily) has no history until Terminal v2's index file has filled, so after tonight's deploy those rows carry a fabricated 52-week range. The pattern predates L2-API (round 1, for stocks), but brief item (3) requires the 52-week high/low to come from stored NSE data.
  - evidence: Repro: news_row('NIFTY 50', {price 24010, day_high 24050, day_low 23880, state live, ...}, ctx=None or EodContext(found=False), market, key='^NSEI') returns high_52w 24050.0, low_52w 23880.0, spark [], eod_as_of None. Cause: `"high_52w": _hi(ctx.high_52w if ctx else None, row.get("day_high"))` and the matching _lo line. WTCH's own '.NS' rows now take the 52-week range from L2-UI's nseBase (null when there is no base), so the visible impact is limited to the remaining consumers of the news-scanner quote route.
  - fix: In news_row, set high_52w / low_52w to None when ctx is None or not found. Widen with today's day high / low only when a stored range exists. Add a test where ctx is missing or found=False and assert both fields are None.
- [minor] tests/unit/test_live_closes.py: No test exercises the splits-table path of /db/closes, including the SYM.NS -> SYM ticker mapping. The TCS fixture's 2-for-1 split produces a 0.5 overnight gap, which shared.nse_panel's gap heuristic also snaps to k = 0.5. The test passes whether or not the splits table is read.
  - evidence: Mutation plugin /Users/sudheer/.suryadhana_pm_scratch/live/L2-API-CHECK/plug/mut_nosplits.py sets frames['splits'] = None in _closes_frames. With it, tests/unit/test_live_closes.py still gives 14 passed, 0 failed. The code itself is correct: it matches security.py's ticker IN (sym, sym.NS) mapping.
  - fix: Add a fixture where only the splits table explains the event. Example: an overnight gap of 0.45 (outside SNAP_TOL of 0.5, so the gap heuristic does not snap it) plus a splits row 'XYZ.NS' with ratio 2.0 (inside the 15 % match). Assert actions == [{date, k: 0.5}] and no day below -20 %. Then confirm the nosplits mutant fails.
- [minor] ui/components/WorldMarkets.tsx: The India panel's labels are now wrong. Its SourceChip hint still says 'SENSEX and the sparks: Yahoo, delayed', and when the live hook is unavailable the panel falls back to sourceOf(..., {source: 'Yahoo'}). Since L2-API, getNewsQuotes answers ^NSEI / ^NSEBANK / ^CNXIT / ^INDIAVIX from the live NSE hub, with sparks from NSE's index file. Those sparks are empty until index_ohlc_daily has 22 or more sessions. The label under-claims (it says Yahoo for NSE data), so it is not fake-live, but it is no longer accurate. The file is outside L2-API's paths.
  - evidence: WorldMarkets.tsx line 152 has the hint text 'SENSEX and the sparks: Yahoo, delayed'. Line 72 comment: 'Yahoo keeps the sparks'. news_scanner.get_quotes now sends `s in _live.NSE_INDEX_TICKERS` to _live.news_quotes. test_index_and_odd_symbols asserts that yahoo.calls are only BHEL.BO and ^BSESN.
  - fix: Patch request to the UI owner: change the hint to 'NSE indices: <live hint> · their sparks: NSE daily index file (EOD) · SENSEX: Yahoo, delayed'. Make the India fallback chip name NSE for the four index rows.

### claimed done but not
- The test list says the 2-for-1 split is adjusted 'via the splits table under TCS.NS'. The split is adjusted, but the test does not show the splits table doing it: with the splits table dropped (mutant mut_nosplits), all 14 tests in test_live_closes.py still pass, because the gap heuristic gives the same k = 0.5 on the same date.

### notes
I re-checked every claim I could myself. All runs used DATA_SERVICE_URL=http://127.0.0.1:9 and my own socket guard (/Users/sudheer/.suryadhana_pm_scratch/live/L2-API-CHECK/plug/chkguard.py), which blocks ports 8001/8010/8008/3000 and any non-loopback DNS or connect.

**Test counts (real tree)**
- ui-api: 1318 passed. The guard blocked 15 attempts, all from the pre-existing test_cache_warm.py (query1.finance.yahoo.com ×8, news.google.com ×5, FRED, treasury). None came from L2-API code.
- core: 1 failed / 1275 passed / 9 skipped, zero guard hits. The one failure is the known gate, fixed by the patch request.
- scripts/tests: 447 passed / 1 skipped.
- L2-API's three test files together: 47 passed (17 + 19 + 11).
- test_live_closes plus the unpatched gates: 1 failed / 89 passed.
- Patched gates in my scratch tree: 77 passed.
- ruff (line length 130, the changed files) and `ruff check .`: clean.
- mypy on the ui-api routers: 30 errors, none in the new code (live.py clean). data-service main.py: 17 errors, none in lines 850-1029.

**My mutation runs**
- Counting a stale row as today's move: caught by test_todays_move[stale]. The route-level date guard also blocks it on its own.
- Emptying NSE_INDEX_TICKERS: 4 failures, including the wire-level no-Yahoo test.
- A todays_move that accepts closed rows of another session: 5 failures.
- No ^CNXIT alias: 1 failure.
- Restoring get_quotes in results-reacting: caught by both patched gates.
- Dropping the splits table: survives (the test gap above).

**Contract and honesty, verified in code**
- /db/closes: one GET route block only. It reads nse_bhavcopy EQ/BE (BZ excluded, documented), up to today only, through the same pick_equity_rows + adjust as shared.nse_panel. Indices come only from index_ohlc_daily, never the Yahoo-tainted market_index_daily. It runs synchronously in the threadpool under the store's shared read lock, with parameterised SQL (no injection). No other route shadows /db/closes.
- /api/market/closes: SWR 600 s / 3600 s, single flight, 422 before any upstream call, 503 upstream_down with a deploy hint, and a note saying 'never live'.
- results-reacting: prices come from live.hub() (the same hub as /api/live/quotes). There are no /db/live-quotes, /db/nifty-live or get_quotes calls left. todays_move counts only live/delayed rows (dated today or undated) or a closed row dated today. A holiday reads as 'closed'. The pre-open IEP is labelled nse_api, delayed then stale.
- Coverage: data-service live_quotes' NSE fallback polls the same heatmap lists, so coverage is no worse than the old heatmap read. hub().quotes splits large requests into chunks of 300, so a peak results day cannot exceed the cap.
- news-scanner: '.NS' and the 4 NSE index tickers go to the hub. BSE and '.BO' stay on Yahoo. The wire-level proof uses the real Yahoo fetcher, with positive and negative controls.

**Ownership, secrets and the live stack**
- Every changed file is inside L2-API's paths. test_alert_quote_freshness.py is a news_scanner test, so it is covered by '+ their tests'.
- No secrets, account numbers or holdings in the diff.
- .logs/data-service.log and .logs/ui-api.log contain no hit for /db/closes or /api/market/closes, so nothing reached the live stack.
- While I worked, another agent (L2-UI) edited ui/components/__tests__/live.check.ts (149 → 152 added lines). That file is not L2-API's.

**Deploy note for the PM**
- The 52-week fallback and the WorldMarkets label are follow-ups, not blockers.
- The index sparks, COMP's NIFTY benchmark and the ^NSEI 52-week range depend on index_ohlc_daily history after tonight's Terminal v2 deploy.
- Re-measure /db/closes latency on the real database with one paced GET after deploy. A cold 300-symbol read slower than 1.5 s makes the first quotes go out without context.

# L2-UI

## summary
All three round-2 UI items are built. tsc, every UI node check, the core suite and scripts/tests are green. The live gates have one failure, and it comes from L2-API's in-progress markets.py change, not from this work. Nothing touched the live stack. Every API call in the fixture screenshots was answered inside the browser; 0 were aborted and none reached :8010, :8001, :8008, NSE, Breeze or Yahoo.

(1) COMP no longer uses Yahoo for NSE stocks.
- NSE stocks read NSE's stored closes in one request: `GET /api/market/closes` (L2-API's route; new getter `getMarketCloses`).
- The NIFTY 50 benchmark asks the same route for 'NIFTY 50' in a separate request. That is NSE's daily index file (index_ohlc_daily). Until that table covers the chosen period, the page uses the stored index closes from `/api/market/index-daily` (market_index_daily). The chip says those older rows may have been loaded from Yahoo.
- Only symbols that are not NSE codes (a leading '^' or a dot, the page's existing rule) still read Yahoo daily closes, and their tag says YAHOO.
- A stock the closes route does not know shows the route's reason (for example 'no NSE closes stored'). It is never filled from Yahoo.
- The header reads 'NSE closes · 04 Nov 2026'. Panel chips read 'EOD · 04 NOV', STALE after 4 days, with every source named in the hover text.
- Rules are in the new pure module ui/components/CompareCloses.ts.

(2) OSTR is seeded from NSE's live option chain during the session (09:15–15:30). Pricing math is unchanged.
- The live quote service's market state decides the session when it has answered; otherwise the client calendar does.
- In session the page calls `/api/market/option-chain-live`. Spot, forward and leg premiums come from that chain, with its own timestamp in the header.
- The legs and payoff chips read 'DELAYED · NSE · 61s' from NSE's records.timestamp. They are never LIVE, and turn STALE after 10 minutes.
- The book is seeded once. Pressing ↻ CHAIN re-seeds it. Crossing 15:30 never reloads, so a book on screen is never wiped.
- One correction: if the first market-state answer disagrees with the calendar's choice (a holiday, or a wrong clock), the page reloads once.
- If the live chain fails, the end-of-day chain is used, with a visible note and an 'EOD · <date>' chip.
- After the close, the F&O bhavcopy chain is labelled 'CLOSE · 05 NOV'. If the session's file is not stored yet (it lands around 20:10), it reads STALE with the reason.
- A 'spot now' line shows the underlying's live price (LIVE · BREEZE) and its drift since the seed, as context only. The analyze and margin requests still read the chain's forward.
- Rules are in the new pure module ui/components/strategySeed.ts.

(3) WTCH and the news dock: NSE rows get name, one-month spark and 52-week range from the NSE base layer, and price from the live hook.
- The base layer is new: news/useNseBase.ts over the pure news/nseBase.ts. It makes one `/api/market/closes?days=366` request for the whole list every 10 minutes, using the route's meta high/low (adjusted daily bars) and NSE company name. Today's live point extends the spark and widens the 52-week range. A previous-close row during the session never does, and its change is never shown as today's.
- The 60-second /api/news-scanner/quotes request now carries only non-NSE symbols (US names, commodities, FX). NSE rows go there only while /api/live/quotes returns 404 (live service not deployed); that fallback is labelled YAHOO.
- The dock's TERMINAL chart for an NSE pick now uses NSE's stored daily bars (bhavcopy, split/bonus-adjusted in news/nseChart.ts, 5Y as weekly bars; chip 'EOD · <date>'). 1D comes from the tick store. 5D is not offered for NSE picks. Yahoo charts only for non-NSE picks.
- WTCH's price-alert check now runs on its own 60-second timer (NSE rows no longer refresh the quotes state).

Fixture screenshots in /Users/sudheer/.suryadhana_pm_scratch/live/L2-UI/shots/ — I looked at them. They cover COMP, OSTR, WTCH, the dock with a US pick and the dock with an NSE pick, each at market open, at 16:10 after the close, and at 21:05 after the day's files are stored. In all three runs the fixture log shows no '.NS' symbol sent to either Yahoo route.

## resolved
- [done] (1) COMP history from /api/market/closes, labelled 'NSE closes · <last date>'; Yahoo only for non-NSE symbols
  - New getter getMarketCloses. Compare.tsx makes one closes request for the NSE stocks, a separate one for 'NIFTY 50' (index file), and falls back to stored index closes for the benchmark until the index file covers the period. Yahoo is limited to symbols with '^' or a dot. Invalid codes are never sent, so one bad entry cannot fail the batch. Each missing stock shows the route's own reason. Header shows 'NSE closes · DD Mon YYYY'. Chip is 'EOD · <newest NSE close>' (STALE after 4 days) and its hover text names every source, including the Yahoo-ingested caveat for the stored index closes. The newest-request-wins guard string pages.check expects is kept.
  - tests: live.check L20 (16 checks incl. negative controls: an NSE code never maps to Yahoo; a symbol the route lacks is never filled; a 2-session index file does not make a 1-year benchmark) + L24 static scan; pages.check R1/M1/Y2 still green; mutation 'COMP Yahoo for NSE' caught by L24 and the proposed gate; screenshots comp_open/closed/night.png
- [done] (2) OSTR seeded from the live chain in session with its timestamp and a DELAYED · NSE · age chip (never LIVE); EOD chain after the close labelled CLOSE <date>; pricing math unchanged
  - StrategyBuilder.tsx picks the seed source at load time (market state from the live service, else the calendar from 09:15). In session it calls getOptionChainLive and falls back to EOD with a note. Header shows the chain's 'as of HH:MM:SS IST'. Legs and payoff chips come from strategySeed.chainSeedSource. A one-shot correction reloads if the first market-state answer disagrees with the calendar. The F&O underlyings list is read once when the live chain lacks it. A 'spot now' line shows the live underlying price with its chip and drift since the seed, as context only. The analyze and margin request bodies are unchanged.
  - tests: live.check L21 (17 checks: mode rules; chip DELAYED·NSE·60s; a 1 s-old chain is still not LIVE; STALE after 10 min; EOD fallback with reason; CLOSE·05 NOV; STALE when the day's file is missing; analyze body unchanged; live spot never reaches pricing; one-shot correction); terminal_v2.check P6 and pages.check R1 still green; mutations 'live chain labelled LIVE' (3 fail) and 'live spot into pricing' caught; screenshots ostr_open (DELAYED · NSE · 60s + LIVE · BREEZE spot), ostr_closed (STALE · 04 NOV: the 05 Nov file not stored yet), ostr_night (CLOSE · 05 NOV)
- [done] (3) WTCH and the news dock: NSE rows take spark/52-week/name from the NSE base layer and the live price from the hook; no Yahoo request for an NSE row
  - New news/nseBase.ts (pure rules) and news/useNseBase.ts (one /api/market/closes request per 300 symbols, every 10 min, keeps the last good answer). WatchMonitor and NewsTerminal build each NSE row with nseQuoteRow(base, live hook row). The 60 s quotes request goes through yahooCallSymbols, which carries NSE rows only while the live route returns 404. WTCH chip, footnote and subtitle rewritten; the 1M and 52W columns carry title text naming the basis and the stored date; the alert check moved to its own 60 s timer. The news dock's TERMINAL chart for an NSE pick is built from /api/stocks/{sym}/history (adjusted, weekly for 5Y, cached per symbol per day) or the tick store for 1D; stats use the Yahoo route's formulas on NSE daily bars; its own chip reads EOD · <date>. 5D maps to 1M for NSE picks.
  - tests: live.check L22 (14 checks: meta high/low vs closing range vs too-short; spark last 22 + today's point; previous-close row in session never paints yesterday's move, spark point or range; the Yahoo request carries NSE rows only on 404) + L23 (10 checks: bonus adjustment with negative control, weekly bars, RSI/SMA, daily ranges, 1D empty store → no chart) + L24 static scans with negative controls; alerts.check, platform.check K5, terminal_v2.check S5 green; mutations caught; screenshots wtch_* (rows read nse_closes, per-row live/delayed/closed dots), newsdock_nse_* (LIVE · BREEZE quote + EOD · 04 NOV chart), newsdock_us_* (Yahoo only for AAPL)
- [partial] Gates: keep test_live_gates green and add to them for what I changed
  - tests/integration/test_live_gates.py is outside my paths, so the additions are a patch request: class TestRound2NseRowsL2UI with 3 static tests and negative controls, inserted before TestNseWebsiteNeverLiveS4. Checked in a scratch mirror: 15 passed for Round2/S2/S3/S4; 4 scratch mutations each fail one test. In-tree the gates are 75 passed, 1 failed; the failure (test_the_known_nse_callers_still_pass_through_get_quotes) comes from L2-API's in-progress markets.py, which now prices results-reacting from the live hub instead of get_quotes.
  - tests: scratch mirror /Users/sudheer/.suryadhana_pm_scratch/live/L2-UI/gatepatch/repo: full patched file 78 passed + the same 1 L2-API failure
  - reason: The test file is not mine (patch request). The single red test is caused by L2-API's change and needs L2-API or the PM to update it.
- [done] Screenshots of COMP, OSTR, WTCH against fixtures (scratch server), read them
  - Static export built in /Users/sudheer/.suryadhana_pm_scratch/live/L2-UI/stage (marker-gated staging copy, node_modules symlinked; ui/.next, ui/dist and ui/out untouched). shots.py serves it on a private port, answers every /api call (including the analyze POST) from fixtures, aborts any other host, and sets the browser clock to the fixture time. 15 PNGs plus logs for open / closed / night.
  - tests: log_open/closed/night.json: aborted [], nse_symbol_sent_to_yahoo [] in all three; Yahoo routes saw only AAPL, ^GSPC, GC=F, BZ=F, INR=X; chips as described in the summary

## contract_notes
- COMP benchmark: L2-API's route also serves 'NIFTY 50' from index_ohlc_daily (NSE's daily index file), so COMP asks for it in a separate request; a refusal there cannot fail the stocks' batch. Until that series starts within 10 days of the period start (the table is new with Terminal v2), the benchmark comes from /api/market/index-daily (market_index_daily), and the chip says its older rows may be Yahoo-ingested. That is a stored series and the page makes no Yahoo request for it.
- COMP label: the header reads 'NSE closes · 04 Nov 2026' as the brief asks. The SourceChip itself keeps the kit's daily wording 'EOD · 04 NOV' with source 'NSE closes' in its hover text; source.ts is not mine and its wording is shared.
- WTCH and the dock's 'NSE base layer' is /api/market/closes (days=366, no tail): name from meta.name (NSE EQUITY_L), 52-week range from meta.high/low (adjusted daily high/low), spark = the last 22 closes. Without meta, a full year of closes gives a labelled 52-week closing range; with fewer than 200 sessions there is no range. These rows no longer use the server's news-scanner '.NS' rows, so they work whatever L2-API does to that route.
- The one remaining path where an NSE row reaches /api/news-scanner/quotes is when /api/live/quotes returns 404 (status 'missing': the live service is not deployed on this ui-api). That keeps round 1's 'UI can ship before the API' safety, and the fallback is labelled YAHOO / 'pre-live quotes route'. When the live service exists but errors, NSE rows show the last live rows under its OFFLINE chip; there is never a Yahoo fallback.
- OSTR after the close, a deviation from 'EOD chain labelled CLOSE <date>': when the session that just ended has no stored F&O bhavcopy yet (16:00–20:10), the chip is STALE · <file date> with the reason 'the <session> F&O bhavcopy is not stored yet'. Calling yesterday's file today's close would mislead. Before the next open it reads CLOSE · <date>; a file more than 4 days old reads STALE.
- OSTR seeds once per load (symbol, expiry or ↻ CHAIN). The live chain is never auto-refreshed: re-seeding would overwrite edited premiums, and each re-analyze would also re-ask the margin route (Breeze when a session is live). The chip age keeps growing and turns STALE after 10 minutes. Spot and forward for pricing come from the chain snapshot; the live underlying price is shown only as 'spot now' with its own chip.
- The news dock offers 1D (tick-store 5-minute bars, honest empty state) and 1M–5Y (bhavcopy) for NSE picks. 5D is not offered because there is no stored 15-minute NSE source; a 5D selection made on a US pick becomes 1M on an NSE pick. Non-NSE picks keep all 8 Yahoo ranges.
- Extra getter fields: getMarketCloses(symbols, days, tail?) and the types MarketCloses / MarketClosesMeta match L2-API's ui-api route as it stands in the tree (series, meta, missing). Only `series` is required; meta and missing are optional.

## deploy_notes
- UI-only changes: they ship with tonight's build-ui release. Nothing to restart for them, and no new npm dependency.
- COMP, the WTCH sparks / 52-week ranges and the dock's NSE rows depend on L2-API's /api/market/closes (ui-api) and /db/closes (data-service). If ui-api lacks the route (404), COMP tags read 'NSE closes route not deployed'. If data-service lacks /db/closes (ui-api answers 503), they read 'NSE closes unavailable: HTTP 503'. WTCH and dock NSE rows then keep live prices with no spark or 52-week range, and the chip hint says why. There is no Yahoo fallback for NSE names.
- OSTR's live seed reads /api/market/option-chain-live, which already exists (data-service caches NSE option-chain-v3 for 30 s). It makes one call per chain load, with no polling, so NSE website load is unchanged.
- By eye after the release: COMP header 'NSE closes · <date>' with '^X · YAHOO' only on non-NSE tags. OSTR in session shows 'DELAYED · NSE · Ns' on legs and payoff plus a LIVE · BREEZE 'spot now' (with LIVE_TICKS=1); after the close 'CLOSE · <date>', or STALE before about 20:10. WTCH 1M and 52W hover text says 'stored to <date>'. The Shift+N dock with an NSE pick shows an 'EOD · <date>' chart chip.
- Scratch (untracked, safe to delete): /Users/sudheer/.suryadhana_pm_scratch/live/L2-UI/ — stage/ (344 MB export build, node_modules is a symlink), shots/ (15 PNG + logs, fixture data only), shots.py, gatepatch/ (scratch mirror with the patched gate), tsbuildinfo.head.

## open_issues
- test_live_gates::TestNoYahooForNsePricesS1::test_the_known_nse_callers_still_pass_through_get_quotes fails on the current tree. L2-API's markets.py now prices results-reacting from live.hub() instead of news_scanner.get_quotes, and the test asserts a 'markets' caller of get_quotes. The test needs updating (L2-API or the PM); no UI file is involved.
- The hover card (terminal/index.tsx, not mine) still reads /api/stocks/{t}/history per symbol for its spark and 52-week range. It could share /api/market/closes with WTCH and the dock (L2-API's route header names it), which would save one DuckDB read per hovered symbol per day.
- Dock 1D for NSE picks depends on the tick store holding 5-minute bars for the symbol (LIVE_TICKS armed tonight; the symbol must be subscribed, which the dock's live-hook request ensures). Until then 1D shows 'no intraday bars stored … pick 1M or longer'. There is no NSE 5D source.
- COMP aligns every series on common dates. If the benchmark's store lacks the newest session the bhavcopy has (or the reverse), the chart ends a day earlier while the header label still shows the newest NSE close. This alignment behaviour predates this change.
- The final NewsTerminal tweak (5D maps to 1M instead of 1D for NSE picks) landed after the last export build. The screenshots do not exercise it; tsc and every check were re-run after it.
- WTCH's subtitle and footnote still say 'live NSE quotes every 3 s' after 15:30 (round-1 wording); the chips and per-row dots correctly read CLOSE · <date>.

## adversarial check: **ACCEPT-WITH-NOTES**
- [minor] ui/components/CompareCloses.ts: Two kinds of NSE symbol still go to Yahoo. seriesSource() treats any symbol containing a dot or starting with '^' as non-NSE, so 'TCS.NS' and NSE index tickers such as '^NSEBANK' or '^CNXIT' still fetch Yahoo daily closes. That goes against 'never Yahoo for an NSE symbol', and contract_notes do not mention it. The COMP input box strips '.NS' on submit (Compare.tsx:159). The GO bar does not: `COMP TCS.NS INFY` stores 'TCS.NS' unchanged (CommandBar.tsx:184), and an older stored compare set can do the same. The tag does say YAHOO and the data is daily history, not a live price.
  - evidence: A node probe of the in-tree module returned: seriesSource('TCS.NS') = 'yahoo', 'tcs.ns' = 'yahoo', '^NSEBANK' = 'yahoo', '^CNXIT' = 'yahoo', 'TCS' = 'nse_closes'. CommandBar.tsx:184 passes `rest.filter(Boolean)` through with no '.NS' strip. L2-API's closes route already turns 'infy.ns' into INFY and '^NSEBANK' into NIFTY BANK (closes_symbols through live.nse_name).
  - fix: In CompareCloses, strip a trailing '.NS' before isNseCode/seriesSource and use the stripped code when reading series, missing and the tag. Send NSE index tickers (^NSEBANK, ^CNXIT and the rest of NSE_INDEX_TICKERS) to the closes route, which serves NSE's daily index file. Add an L20 check with 'TCS.NS' and '^NSEBANK' as negative controls.
- [minor] ui/components/StrategyBuilder.tsx: The one-time seed correction can wipe a book handed over from OMON. The first chain load uses up pendingSeed. If the live service's first market-state answer disagrees with the calendar, loadChain() runs again. The new chain then hits the [chain] effect with no pending seed and no template, so setLegs([]) clears the OMON legs. This contradicts the claim that 'a book on screen is never wiped'. It happens only when the calendar and the service disagree: a holiday before the client holiday list loads, the seconds around 09:15 or 15:30, or a special session.
  - evidence: StrategyBuilder.tsx:298-313: pendingSeed.current = null on first use, then `else setLegs([])` for a custom or OMON book. Lines 271-279: the correction effect calls loadChain() with no guard for seeded or edited legs.
  - fix: Before the correction reload, put the used OMON seed back (keep it in a ref until the check has run), or skip the correction once the legs have been seeded from OMON or edited, and show the live/EOD mismatch as a note instead.
- [minor] ui/components/news/NewsTerminal.tsx: For an NSE pick during the session, some EOD numbers sit next to live numbers with no date on them. The key-stat 'VOL / 20D AVG' and the TECHNICALS tab's 1D/5D now come from the last stored bhavcopy session (yesterday). The VOLUME stat and the price beside them are live. Before this change, Yahoo's daily candles included today's partial bar. Showing yesterday's move under '1D' is what isStaleEod was added to prevent.
  - evidence: nseChart.ts dailyStats(): volume_ratio uses the last daily candle and ret_1d = closes[-1]/closes[-2]. NewsTerminal.tsx:539 (VOL / 20D AVG) and :688 (1D/5D) render them with no date. Screenshot newsdock_nse_open.png shows VOLUME 4.66M (live) next to VOL / 20D AVG 1.01× (from the 04 Nov file).
  - fix: During the session, compute the ratio as live volume / st.avg_volume_20d, or label the stat with the last stored date. Head the technicals tab with 'NSE daily bars to <last_date>', and label 1D as the last session's move in session.
- [minor] ui/components/WatchMonitor.tsx: The WTCH subtitle now always says 'live NSE quotes every 3 s · NSE closes' once the live route is deployed. That includes while the live service is loading or erroring (chip OFFLINE) and after 15:30. Round 1 showed this only when liveQ.available. The builder lists the after-close case as an open issue but not the error case. Every chip, row dot and footnote is correct.
  - evidence: WatchMonitor.tsx subtitle: `${legacy ? 'quotes every 60 s (…)' : 'live NSE quotes every 3 s · NSE closes'}`. The old code was conditional on `liveQ.available`.
  - fix: Base the wording on liveQ.available and on liveQ.market.state, for example 'NSE closes · CLOSE <session>' after the close and 'live NSE service not answering' on error.
- [minor] ui/components/CompareCloses.ts: pickBench's last fallback uses NSE's index file even when it covers only a few sessions, which happens when /api/market/index-daily fails. COMP lines every series up on dates they share, so the whole chart and every stat shrink to those 2-3 sessions. The L20 claim that a 2-session index file never becomes a 1-year benchmark holds only while the stored index closes answer.
  - evidence: pickBench: `if (fromCloses && fromCloses.dates.length >= 2) return {... source: 'nse_index_file'}` after the store branch. Compare.tsx:151-153 intersects dates across [BENCH, ...syms].
  - fix: Return no benchmark ('error') when neither source covers the period. Or leave the benchmark out of the shared-date step, show it only on its own dates and label it 'NIFTY 50 from <first date>'.
- [minor] ui/components/__tests__/live.check.ts: Missing test: the branch of seedMode() where the market is 'pre-open' (and the seed must come from end of day) has no check. In my mutation run it was the only one of 12 mutations that live.check did not catch.
  - evidence: Mutation M8 (`if (o.marketState === 'pre-open' || o.marketState === 'closed') return 'eod'` changed to `if (o.marketState === 'closed') return 'eod'`): live.check stayed at 176 passed, 0 failed. The other 11 mutations each failed 1 to 4 checks.
  - fix: Add an L21 check: seedMode({marketState: 'pre-open', calendarOpen: true, nowMs: 09:30 IST}) === 'eod'.
- [minor] ui/components/news/useNseBase.ts: The NSE base layer downloads more data than it uses. It asks /api/market/closes?days=366 with no tail and gets about 250 points × up to 300 symbols, roughly 2-3 MB of JSON per window every 10 minutes. It uses only the last 22 closes plus meta high/low. data-service says its meta high/low cover the whole days window even when tail is set. Separately, NewsTerminal's nseHistCache is keyed by IST day, so after the bhavcopy lands (~18:30) the dock keeps the morning's bars until midnight. The chip shows the older date, so this is honest.
  - evidence: useNseBase.ts calls getMarketCloses(chunk, BASE_DAYS) with no tail. data-service /db/closes docstring: "``meta`` high/low cover the whole ``days`` window". NewsTerminal.tsx nseHistory() checks `hit.day === istDay()`.
  - fix: Pass tail = SPARK_N + 1 and keep the closing-range fallback only for when meta is absent. Key the history cache on IST day plus the hour bucket after 18:30, or re-read once when the chip date is older than the latest session.

### claimed done but not
- COMP 'Yahoo only for non-NSE symbols': not fully true. A '.NS' NSE code from the GO bar or a stored set, and NSE index tickers (^NSEBANK, ^CNXIT), still read Yahoo; contract_notes give the '^' or dot rule but not this consequence.
- OSTR 'a book on screen is never wiped': the one-time market-state correction can clear an OMON hand-off book in the edge cases described above. The 15:30 crossing itself never reloads, as claimed.

### notes
The builder's claims hold up, with seven minor problems and no blockers or majors.

**Tests I re-ran (all with DATA_SERVICE_URL=http://127.0.0.1:9, nothing sent to the live stack):**
- `cd ui && npx tsc --noEmit -p . --incremental false`: exit 0. ui/tsconfig.tsbuildinfo is unchanged (same md5, git clean).
- `node ui/components/__tests__/live.check.ts`: 176 passed, 0 failed.
- Every plain-node UI check, run as CI runs them: all exit 0. gold 221, gold_views ok, live 176, no-dialogs 0 calls, pages 281, terminal_v2 G9 30, desktop 398, vol/terminal_v2 104, alerts 31, platform 123, prefs 164, streamProxy 76, ws 82. errors.check needs tsx and was skipped, as in CI.
- `node --test ui/scripts/*.test.mjs`: 26 passed, 0 failed.
- `pytest tests/integration/test_live_gates.py`: 75 passed, 1 failed. The failure is TestNoYahooForNsePricesS1::test_the_known_nse_callers_still_pass_through_get_quotes. It finds only the ('alerts', 'run_alerts') caller because L2-API's markets.py now prices results-reacting through `_live.hub()`. No UI file is involved; L2-API or the PM must update that test.
- Core `pytest tests`: 1275 passed, 9 skipped, 1 failed (the same L2-API test).
- `pytest scripts/tests`: 447 passed, 1 skipped.

**Gate patch:** the anchor `class TestNseWebsiteNeverLiveS4:` appears exactly once. I applied the patch myself in /Users/sudheer/.suryadhana_pm_scratch/live/L2-UI-CHECK/repo; the new class is byte-identical to the builder's mirror. Full gate file: 78 passed + the same 1 L2-API failure. `-k Round2`: 3 passed. Ruff at line length 130 passes on the patched file. It is safe to apply as written.

**My own mutations** (12, on a copy in L2-UI-CHECK/mut, never in-tree):
- Caught (11): NSE rows sent to Yahoo whenever the hook is not ok; a stale EOD row extending the spark or range; the missing after-close F&O file reading CLOSE instead of STALE; COMP NSE codes sent to Yahoo; bhavcopy adjustment off by one; the benchmark ignoring period coverage; the live chain chip reading CLOSE in session; meta high/low dropped; the 52-week range not widened; a missing COMP symbol filled from another series; an empty 1D tick store still drawing a chart.
- Survived (1): the pre-open branch of seedMode (problem 6).

**Honesty rules:** no live claim is faked.
- OSTR's live chain goes through nseDelayedSource with marketOpen true, so its chip reads DELAYED, then STALE after 10 minutes, and never LIVE.
- COMP and the dock chart read EOD · <date>; the tick-store 1D chart reads DELAYED · TICK STORE · HH:MM.
- An in-session EOD row never paints yesterday's move.
- I checked the routes behind the new panes: /api/stocks/{sym}/history reads nse_bhavcopy with action_k, and /api/charts/intraday reads the W6 tick store. Neither touches Yahoo.

**Ownership:**
- Every UI change is inside L2-UI's paths: Compare*, StrategyBuilder.tsx plus strategySeed.ts (used only by it), WatchMonitor.tsx, news/**.
- ui/lib/api.ts has 11 added lines and none removed: one new getter and its two types.
- live.check.ts has 152 added lines and none removed.
- The other modified files belong to L2-API.

**Secrets:** none in the changed files. The screenshots and logs hold fixture data only and are untracked in scratch.

**Live stack:** shots.py routes every request, aborts any host other than its own 127.0.0.1 port and answers every /api call from fixtures. The WebSocket is built from the page origin, so it also stays on that port. The logs show aborted [] and nse_symbol_sent_to_yahoo [] in all three runs. ui/.next (11 Oct), ui/.next-prod (25 Oct) and ui/dist (05 Nov 04:10) are untouched, and ui/node_modules/.cache does not exist.

**Screenshots:** I looked at ostr_open, wtch_open, comp_open and newsdock_nse_open. They match the claimed chips: DELAYED · NSE · 60s with a LIVE · BREEZE 'spot now' on OSTR, 'NSE closes · 04 Nov 2026' with EOD · 04 NOV chips on COMP, per-row dots on WTCH, and LIVE · BREEZE plus EOD · 04 NOV in the dock.

**Deploy:** COMP, the WTCH and dock sparks and 52-week ranges need L2-API's /api/market/closes in ui-api and /db/closes in data-service. That means restarting data-service outside 18:30–21:15 and following the ui-api → data-service → ui-api order; the 21:37 slot qualifies. Without those routes, the panes say 'NSE closes route not deployed' or 'HTTP 503' and never fall back to Yahoo.

Everything I ran or wrote is in /Users/sudheer/.suryadhana_pm_scratch/live/L2-UI-CHECK/ (core.log, scripts.log, tsc.log, mutate.py, the probe scripts, the repo/ mirror with the patched gate, the mut/ copy).
