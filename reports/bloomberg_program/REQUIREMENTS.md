# REQUIREMENTS — Bloomberg-grade program, Phase 1 (14 Oct 2026, ~22:15 IST)

Contract for Phases 2–5. Every F/S item cites its source finding and carries testable acceptance criteria (AC).
Sources: reports/production_review/{REPORT,design_audit,contract_audit,scale_latency,devex_audit,duplicates,
architecture_reality}.md + endpoint_latency.csv; memories: ui-api-event-loop, ui-api-snapshot-proxy,
intraday-data-sources, icici-auto-login, jupyter-env-shared; code: services/data-service/providers/
icici_breeze_provider.py, services/ui-api/snapshot.py, breeze_connect (installed lib, API inspected).

## 1. Functional requirements by workstream

### B1 — Reliability / Ops
- **F1.1 `.env.example` truth.** (devex §1: missing ICICI_CLIENT_ID/PASSWORD/MOBILE; no TOTP/COST_PROFILE/DESK_*/
  UI_MODE.) Sync names+comments with every key the code reads (grep os.environ/dotenv across services/, scripts/,
  shared/); placeholder values only, NEVER real secrets.
  AC: a name-diff script in the test shows `live .env keys − example keys = ∅` for keys referenced in code; no
  value in the example matches any live secret; file documents which keys are login-critical vs optional.
- **F1.2 Restore runbook.** (devex: disk-wipe test fails; DB 4.4 GB git-ignored, zero restore docs.)
  `docs/RUNBOOK_RESTORE.md`: fresh-machine sequence (brew python hazard incl. HOMEBREW_NO_AUTOREMOVE=1 per
  jupyter-env memory, jupyter_env pointing, playwright chromium, node, .env reconstruction incl. Telegram+ICICI,
  DuckDB restore from backup, LaunchAgent note, start-local, verify list). AC: doc exists; every command
  copy-pasteable; cross-linked from CLAUDE.md and GETTING_STARTED.md; names the backup location from F1.3.
- **F1.3 Nightly DuckDB backup.** (devex bus-factor 3/10.) Script `scripts/db_backup.py`: consistent copy of
  market.duckdb (+wal) → `data/backups/duckdb/market-YYYYMMDD.duckdb.zst` (zstd if available else plain copy;
  prefer DuckDB's own `.backup`-equivalent: open read-only snapshot copy pattern already proven), rotate keep 7
  daily + 4 weekly; verify by opening the copy read-only and counting nse_bhavcopy rows ≥ source−ε. Scheduled in
  master-controller **02:15 IST daily** (quiet window; eod 18:30, rl 23:00, login 08:00 untouched).
  AC: unit test on a tiny DB fixture (copy+verify+rotate); job registered (scheduler status shows it); manual run
  produces a verified file; failure path alerts via existing `_alerts` (uses the established channel — this is the
  ONE permitted Telegram path, pre-existing).
- **F1.4 CI.** (devex: none.) `.github/workflows/ci.yml`: on push/PR — the 5 pytest suites with their PYTHONPATHs
  (tests/ minus browser-marked, scripts/tests, services/ui-api/tests, services/execution-service/tests,
  alpha_lab/tests) + `tsc --noEmit` + ruff if config exists (don't add new lint rules tonight). Python 3.13,
  pip install -r requirements.txt into the RUNNER env (never jupyter_env; that's local-only).
  AC: `yaml` parses; a local `act`-style dry run is NOT required — instead a test asserts the workflow lists all
  five suite paths + tsc; CLAUDE.md "Running services" section gains the CI note. Browser-login tests marked/
  skipped on CI (no Chrome guarantee) via existing skip fixture (it already skips when Chrome unavailable — verify).
- **F1.5 Dead-surface removal.** (contract C3: 8 routes; scale §1 P1: pipeline parquet routes.) Delete the 8
  dead routes; for `pipeline.py:422,747,890` parquet routes: they ARE reachable from ModelLab UI (contract says
  pipeline endpoints are consumed; the ORPHAN suspicion applied to heavy sample/feature routes) — resolve per
  CON+SCALE: routes confirmed consumer-less are deleted; consumer-ful heavy ones get F2.2 treatment instead.
  AC: openapi path count drops by exactly the removed set; grep shows zero ui/scripts references to removed
  paths; ui-api tests green; a tombstone note in build_b1.md lists each removed route + evidence of no consumer.
- **F1.6 `/api/data/fetch/icici/daily` tombstone** marked deprecated in openapi (contract C4). AC: openapi shows
  deprecated:true; behaviour unchanged.

### B2 — Backend scale (existing flows made scalable)
- **F2.1 Bounded shared cache.** (scale §3: news_scanner._cache unbounded = P1 leak.) New
  `services/ui-api/cache.py`: `TTLCache(max_items, default_ttl)` — expiry on read+write, LRU eviction on
  overflow, `stats()` (hits, misses, evictions, size), thread-safe (used from threadpool routes too).
  Migrate `news_scanner._cache` (+`commodity._CACHE`, `gold_preopen._cache` if trivial) without changing key
  semantics or TTLs. AC: unit tests (expiry, LRU overflow at max_items, thread hammer 10k ops no growth beyond
  bound); news_scanner behaviour unchanged (its existing tests green); `/api/telemetry` or log line exposes
  cache stats (observability).
- **F2.2 Event-loop hygiene completion.** (scale §1; event-loop memory.) `asyncio.to_thread` (or sync `def`)
  for: pipeline.py parquet loads (plus `columns=` projection + the existing single-slot frame cache made
  bounded), stocks.py:635 screener DuckDB, dashboard.py:579,608. AC: new regression test pattern — hit the
  route (monkeypatched heavy fn with 0.5 s sleep) while timing `/health` concurrently; health p95 < 100 ms
  (the memory's diagnostic, automated); existing suites green.
- **F2.3 Shared evening snapshot.** (scale §2: 4–6 × 4.7 GB/evening.) Honour `SURYA_SNAPSHOT_PATH` env in the
  three nightly consumers (`alpha_lab/backtest/data_access.load`, `scripts/news_scan_performance.py` snapshot
  helper, research-script helper is OUT of scope — frozen) + controller job `shared_snapshot_build` **19:20 IST**
  building one versioned copy via ReadSnapshot into a fixed dir and exporting the path to child jobs (controller
  sets env when spawning news/shadow jobs). Fall back silently to private copy when env absent/stale>24 h.
  `.tmp` orphan cleanup (>1 h) in `snapshot.py:_build` (3 lines, scale finding). alpha_lab/ is frozen EXCEPT
  this single additive env hook in `backtest/data_access.py` — PLAN amendment recorded: data_access is engine
  plumbing, not strategy/rule code; the vendored-lib drift test must stay green (data_access is NOT vendored).
  AC: with env set to a prepared snapshot, `load()` opens it and skips copying (test with tmp dirs + mtime
  checks); job registered 19:20; evening copy count math documented ≤2; orphan-cleanup unit test.
- **F2.4 One error contract.** (contract C6.) `services/ui-api/errors.py`: helpers `fail(status, code, message,
  hint=None)` → HTTPException detail `{code,message,hint}`, and `degraded(data_extra, code, message)` → 200
  `{connected/ok:false, error:{...}}` reserved ONLY for usable-but-degraded data. Frontend `ui/lib/apiError.ts`:
  `normalizeError(resp|err)` returning `{code,message,hint}` from all three legacy families. Migrate the worst
  soft-200 offenders (pipeline 35×, positions 11×, dashboard 9×) to the contract WITHOUT breaking existing UI
  branches: keep legacy keys alongside new `error{}` for one release (additive).
  AC: unit tests for both helpers + normalizer (9 shape cases incl. legacy); grep census in build report shows
  soft-200 `{error:}`-only responses reduced to the degraded-data whitelist; stocks `/ZZZ` 404 now carries
  hint "Unknown ticker — try GO search" (devex error sample upgraded to 3/3); ui-api suites green.
- **F2.5 Payload budgets.** (contract/scale: events 239 KB, announcements 218 KB, fundamentals-screen 529 KB,
  ohlcv-meta 598 KB.) Add `limit`/windowing params with generous defaults that cut default payloads ≤150 KB
  each WITHOUT changing what current UI shows (UI passes explicit params where it needs more).
  AC: measured default payloads of the four routes ≤150 KB; UI pages pixel-identical data (audit pass); params
  documented in openapi.

### B3 — Live data (push, not poll)
Breeze facts (verified tonight): `BreezeConnect.ws_connect()` / `subscribe_feeds(stock_token|exchange_code+
stock_code+product_type..., get_exchange_quotes, get_market_depth, get_order_notification)` /
`unsubscribe_feeds` / `on_ticks` callback exist in the installed lib; provider (`icici_breeze_provider.py`) has
NO ws code today but has `_resolve_isec_code` (line 299) for ticker→ISEC mapping; memory: L1 fields include
last/ltp, ltq, ltt, ttq (cum volume), TotalTrades (+bid/ask when depth on); socketio needs the wait_timeout
3 s→20 s patch; REST `get_quotes` has a hidden daily cap (exhausted by 11:00 once) → **REST polling for live is
forbidden; WS only.** `connection-status` probe/caching pattern exists in positions.py.
- **F3.1 Tick subscriber (data-service).** New module `services/data-service/live_ticks.py`: on demand (first
  subscriber request) when provider connected: ws_connect with the wait_timeout patch, subscribe ≤50 symbols
  (book + watchlist set pushed from ui-api), on_ticks → in-memory `{symbol: {ltp, chg_pct? (needs prev close
  join), ltt, ttq, bid, ask, ts_received}}`, reconnect with backoff on drop, full teardown on disconnect();
  symbols changeable at runtime (resubscribe diff). Endpoint `GET /live/ticks` → `{connected, as_of,
  ticks:{...}}` (cheap dict dump); `POST /live/ticks/symbols {symbols:[...]}` (idempotent set-replace, cap 50,
  validated against security master). Guard: if ws errors 3× in 5 min → degraded flag, stop retrying for 10 min.
  AC: unit tests with a fake Breeze object (subscribe called with ISEC codes, tick updates store, resubscribe
  diff, reconnect backoff, teardown); live smoke next market session (Phase 4 if in-hours, else recorded as
  deferred-verification with the fake-driven integration test standing in).
- **F3.2 ui-api proxy + freshness.** `GET /api/quotes/ticks?symbols=` → merges data-service ticks with
  Yahoo-path fallback per symbol: `{symbol: {price, chg_pct, source: "icici-ws"|"yahoo", as_of}}`; declares
  degraded per F2.4 when ws down. AC: contract test (fake upstream states: connected/degraded/absent);
  latency < 20 ms warm (local dict).
- **F3.3 WATCH/book go live.** (design F-015 — top Bloomberg gap.) Frontend hook `useLiveTicks(symbols)`
  polling F3.2 at 2 s ONLY while tab visible + ICICI connected (else existing 60 s Yahoo flow untouched);
  WATCH + DESK book + stock-window header adopt it; per-panel freshness chip `LIVE·ICICI` (green dot) /
  `DELAYED·Yahoo 60s` (amber) — chip component in the kit.
  AC: with ws mocked in dev: rows re-render ≤2 s after tick, chip states correct incl. mid-session fallback
  flip; visibility-hidden stops polling (test via document.hidden mock); 37-page audit green.
- **F3.4 Quota safety.** No REST quote call added anywhere by B3; grep in build report proves `get_quotes`
  call-sites unchanged. AC: census identical before/after.

### B4 — Frontend / design (design_audit register)
- **F4.1** F-001 news-pill dock → footer-right slot, auto-collapse to bell over panels. AC: screenshots DESK/
  MARKETS show charts unobstructed; pill functions preserved.
- **F4.2** F-002 kit-level `tabular-nums` on all numeric cells (kit table/cell styles + the 5 worst tables by
  hand). AC: computed-style census ≥95% of numeric cells tabular (browse JS re-run; baseline 6 elements).
- **F4.3** F-004 ALERT z-fight: action row conditional-rendered away in alert mode; labelled inputs (above ₹ /
  below ₹ as visible labels) + `move %` field (bot parity, wired to existing alerts API `move` key). AC:
  screenshot clean; set-alert flow works against live API in dev; aria-labels on the strip controls.
- **F4.4** F-003/F-009/F-013 token discipline: kit relocated to `ui/lib/terminal.ts` (re-export from old path),
  3 ambers → T.amber, violet/teal strays → tokens in the top-20-hex files, pure #FFF → T.bright. AC: hex census
  in ui/components+app drops ≥300 (from 597); tsc green; visual spot-diff on QuantKPICard/BacktestPanel pages.
- **F4.5** F-014/F-012 polish: DESK LAST min-width, tape priority-trim, "ML" tab label. AC: screenshots.
- **F4.6** GO recall (Bloomberg lens): ↑/↓ history (last 20, localStorage, wrapped in try/catch per storage
  rules) + "recent" chips under GO when focused+empty. AC: keyboard test in dev; no SSR breakage (guarded).
- **F4.7** F-007 skeletons: kit `Skeleton` + adopt in the 10 heaviest panels (list in design_audit). AC:
  component + visible during artificial 2 s delay in dev; no layout shift (CLS check on BRIEF).
- **F4.8** System page 27 s first load (scale correction note): make its setup/status probes concurrent
  (Promise.all) + skeleton. AC: System first-load < 8 s cold in audit harness.
- **F4.9** Per-tab `next/dynamic` for the 15 tab components in `app/page.tsx` (ssr:false where browser-only).
  AC: prod build route JS for `/` drops ≥40%; tab switch still instant (prefetch on hover optional); 37-page
  audit green.

### B5 — Docs / architecture truth
- **F5.1** CLAUDE.md: service table → "running stack (4 procs)" + "dormant legacy" sections (architecture_
  reality); roadmap table → pointer to PRODUCT_STRATEGY + IMPROVEMENT_LOG; add canonical "how to run things"
  (PYTHONPATH conventions incl. `PYTHONPATH=alpha_lab python alpha_lab/...`, shadow manual run, test suite map
  — devex findability misses). AC: doc asserts match `curl :800{1,8}/health` reality; grep for "Phase 1 | ⏳"
  gone; shadow command findable.
- **F5.2** Root `README.md` (devex: none): 30-line front door — what this is, screenshot pointer, quickstart
  (warm machine), links (GETTING_STARTED, RUNBOOK_RESTORE, IMPROVEMENT_LOG, CLAUDE.md, RSCH). AC: exists, links
  valid.
- **F5.3** GETTING_STARTED.md corrected (start-local reality, Playwright/Chrome prerequisite, .env pointer,
  DB restore pointer). AC: devex §1 step table re-run shows no doc-vs-reality contradictions.
- **F5.4** Root sweep: the ~50 legacy root files → `docs/legacy/` (git mv-style moves — allowed as working-tree
  moves, still NO commits; moves must not break imports: verify nothing imports them; result CSVs → docs/legacy/
  data/). AC: repo root ≤15 entries (dirs + core files); grep proves no references broke; `nse_panel_qa_old.py`
  → docs/legacy/ (not deleted).
- **F5.5** Script `--help` floor (devex): real one-line descriptions for the 6 main scripts' argparse; add
  argparse to `alpha_lab/run_today.py` (−−help must not execute the 15 s load). AC: `--help` returns <1 s with
  meaningful text for all 6.

## 2. Scalability requirements (retrofit the EXISTING flows)
- **S1 Bounded memory everywhere:** no unbounded dict cache may remain in ui-api/data-service (census in build
  report; F2.1 is the mechanism). Data-service DuckDB gets `PRAGMA memory_limit='1.5GB'` guard (scale §7) set at
  connect — verify no query regression in its tests.
- **S2 Event-loop purity:** zero blocking IO (>50 ms class: file reads >1 MB, DB, network, pandas) inside
  `async def` in ui-api/data-service request paths. Mechanism F2.2; verified by the concurrent-health test
  pattern applied to the 4 known routes + a static AST scan script (`scripts/check_event_loop.py`, reusable;
  CI-wired via F1.4) whose whitelist starts empty and FAILS on new violations.
- **S3 One snapshot per evening** (F2.3): steady-state evening SSD writes ≤ 2 × DB size; measured by file-count
  math in test report.
- **S4 Stateless-capable handlers:** module-level caches must be (a) bounded and (b) documented in
  `docs/ARCHITECTURE_NOTES.md` singleton register (B5 writes the register from B2's census) so a second ui-api
  replica's divergence surface is known. No new sticky state introduced by any workstream.
- **S5 Push-not-poll for live data:** F3.x; the ONLY upstream live subscription is the single Breeze WS in
  data-service; N frontend clients cost 0 extra upstream load (local dict reads).
- **S6 Payload budget:** default GET ≤150 KB (F2.5 fixes the 4 known violators; test report re-measures all
  routes from the baseline CSV and lists any >150 KB with justification).
- **S7 Error contract** (F2.4) is the single convention for all NEW code; legacy additive-migrated.
- **S8 Latency floors hold:** Phase 4 re-measures the baseline CSV; no route's warm p50 regresses >25% or
  crosses 500 ms; System page cold < 8 s (F4.8); `/` first-load JS −40% (F4.9).

## 3. Non-goals (explicit, tonight)
No Redis/queue/new infra · no multi-user auth/RBAC · no kubernetes/deploy changes · no trading-rule or Desk
changes · no per-strike options data · no new strategy/research work · no Next version upgrade · no repo-wide
lint reformat · research scripts' private snapshots stay (frozen files).

## 4. Constraints & frozen zones (binding, from PLAN + found)
PLAN constraints verbatim (no commits · no Telegram sends except the pre-existing `_alerts` channel used by the
new backup job's failure path · restarts PM-only outside 07:45–09:20/18:30–21:15 · ICICI REST quote polling
forbidden) **plus:** jupyter_env is shared — NO new Python deps without explicit PM sign-off (zstandard optional
in F1.3 must degrade gracefully if absent; prefer stdlib); `shared/momentum.py`, `shared/decision_desk.py`,
`shared/trading_costs.py`, `alpha_lab/**` (except the F2.3 env hook in `backtest/data_access.py` — PLAN
amendment), `scripts/*_study.py`, research `reports/*/` all frozen; `ui/.next*` never hand-edited; secrets never
in reports; the duplicates-agent survivors (terminal kit exports) are the canonical helpers — new UI code uses
them; breeze import must go through `shared/breeze_cache.install()` (hang fix) — B3 must follow.

## 5. Requirement → test matrix (Phase 4 contract)
| Req | Verification |
|---|---|
| F1.1 | unit: key-diff script vs code-referenced keys; secret-leak grep |
| F1.2/F5.x | docs link-check + devex step-table re-walk (agent) |
| F1.3 | unit fixture backup/verify/rotate; scheduler listing; one real run artifact |
| F1.4 | workflow-content test (5 suites+tsc listed); yaml parse |
| F1.5/F1.6 | openapi diff exact; grep zero consumers; suites green |
| F2.1 | TTLCache unit (expiry/LRU/threads); news_scanner tests; stats exposed |
| F2.2/S2 | concurrent-health latency test ×4 routes; AST scan clean |
| F2.3/S3 | env-hook unit tests; job registered; copy-count math; orphan-cleanup test |
| F2.4/S7 | helper+normalizer units (9 shapes); soft-200 census delta; /ZZZ hint live |
| F2.5/S6 | live payload re-measure ≤150 KB ×4; UI data-parity on audit |
| F3.1 | fake-Breeze unit suite (subscribe/tick/resub/reconnect/teardown) |
| F3.2 | contract test 3 upstream states; warm <20 ms |
| F3.3 | dev-mock UI test ≤2 s + chip states + visibility stop; 37-page audit |
| F3.4 | get_quotes call-site census unchanged |
| F4.1–F4.9 | screenshot evidence per finding; hex census ≥−300; tabular census ≥95%; System <8 s; `/` JS −40%; audit 37/37 |
| S1 | cache census table: every cache bounded + PRAGMA set |
| S4 | singleton register exists & complete vs census |
| S5 | code census: zero new REST live polls |
| S8 | full latency CSV re-measure vs baseline, regression rule |

## 6. Open questions for the designers (≤6)
1. F2.3: should the controller pass `SURYA_SNAPSHOT_PATH` via job env only, or also write a pointer file for
   ad-hoc manual runs (recommend both: env wins, pointer fallback)?
2. F3.1 prev-close join for chg_pct: from security-master/last EOD close in data-service (cheap) or let ui-api
   compute vs its Yahoo prev? (recommend data-service joins bhavcopy prev close at subscribe time.)
3. F3.3 chip placement: per-panel header right slot vs per-row? (recommend panel header; row-level only in
   stock window.)
4. F4.9 which tabs stay eagerly loaded? (recommend BRIEF only; all else dynamic.)
5. F2.4 error codes enum: fixed set now (`not_found, upstream_down, degraded, unauthorized, invalid, state`) or
   free-form? (recommend fixed set + `internal`.)
6. F1.3 zstd: acceptable to try import and fall back to uncompressed? (recommend yes; no new dep install.)
