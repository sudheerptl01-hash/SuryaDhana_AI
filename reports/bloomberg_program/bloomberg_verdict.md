# BLOOMBERG VERDICT — Phase 5 adversarial critique (15 Oct 2026, 00:00–00:25 IST)

**BLOOMBERG-GRADE: NO — as a delayed-data paper terminal it is fast, honest and well-tested, but the program's two headline claims fail primary-source verification: the live-tick feature cannot render a single tick (server sends `quotes{}`, client reads `ticks{}`), and the disaster-recovery story depends on a git remote that does not exist, backups that have never run, and 481 untracked files including the trading strategy itself.**

Everything below was verified against primary sources by this critic: code reads, live GETs against :8001/:8010/:8008/:3000, my own curl timings, my own runs of the five pytest suites + `tsc --noEmit` + `scripts/check_event_loop.py`, and ~18 adversarial probes. No report was trusted unverified. Read-only posture kept throughout (GETs only, no restarts, no secrets read, LIVE_TICKS untouched).

---

## 1. The six-point bar

### (a) FAST — 6/10
**Verified myself** (3 hits per route, warm = hits 2–3):
- Excellent spine: `dashboard/summary` 15 ms · `stocks/list` 12 ms · `alerts/feed` 1 ms · `positions/summary` 1–2 ms · `desk/status` 1 ms · `quotes/live` 12–17 ms warm. Matches `latency_after.csv` (warm p50 ~4 ms over ~150 routes) — the CSV was not cooked; my numbers reproduce it.
- **Three trader-touched routes break the program's own bar** (PLAN.md bar 1: "no endpoint a trader touches in-session over 500 ms warm"; S8: "…or crosses 500 ms"):
  `/api/alpha/universe` **1,417–1,472 ms** · `/api/lw/screener` **2,905–3,080 ms** · `/api/pipeline/features-explorer` **765–836 ms** — every hit, fully warm. Cause: both scan routes re-pull the 69.5 MB `/db/ohlcv-bulk` **per call** (`services/ui-api/routers/alpha.py:201` `await _load_bulk_ohlcv(days)` in `universe_size`; `services/ui-api/routers/lw_scanner.py:30–40`), no TTL on the frame. test_report.md §3 reports this as "PASS with 3 explained flags / ticketed" — by the program's written bar these are FAILs, re-labelled.
- **Concurrency**: 8 simultaneous `/api/alpha/universe` → perfect serialization at ~0.73 s/request (1.53 → 6.62 s). No request coalescing, no cache: duplicate requests queue linearly. 100 users on PLAN's "scales at 100" framing = 73 s tail on this route.
- CSV methodology nits: warm = `min(hit2,hit3)` (best-case stat), single client, localhost; `/api/commodity/price/{symbol}` row is still the literal-template 404 despite the claimed parametrized re-measure.

**10 needs:** 60 s TTL + single-flight on the bulk frame; every in-session route <500 ms warm p95 under 10 concurrent clients; median (not min) warm stats.

### (b) LIVE — 3/10
The backend engine is genuinely good; the feature as a whole is **inoperable end-to-end**.
- Engine design (`services/data-service/live_ticks.py`) verified by read + its 7 unit tests: lazy kill-switched arm, union+TTL+cap-50 subscriptions with holdings pinned, per-symbol sub-error isolation, 3-strikes/10-min cool-off, 120 s watchdog with flip-back, WS-only (zero REST quote calls — F3.4 census checked: `routers/quotes.py` imports only the Yahoo path), teardown on provider death. Served payloads honest today: `/live/ticks` → `state OFF, ticks{}`; `/api/quotes/ticks` → every symbol `source:"yahoo"`.
- **CRITICAL (D1): the wire contract is broken.** `services/ui-api/routers/quotes.py:94` returns the per-symbol map under **`"quotes"`**; `ui/lib/liveTicks.ts:44–49` parses **`data.ticks`** — always `{}`. `ui/next.config.js` is a transparent rewrite (no rename), no `app/api/quotes` route exists. Verified live: `GET :8010/api/quotes/ticks?symbols=RELIANCE,TCS` → `{"connected":false,"state":"OFF","quotes":{…}}`. Therefore **no tick can ever reach WATCH, DESK or the stock window**, even with LIVE_TICKS=1 and a flowing websocket. The receipts: build_b4.md:93–95 explicitly told the PM the frontend expects `ticks{}` and that any B3 drift needs a ~15-line `liveTicks.ts` patch; B3's own tests assert `out["quotes"]` (`services/ui-api/tests/test_quotes.py:71`). Integration (integration.md patch #1) printed the payload and missed the key. The Phase-4 "live spike" ran after-hours, where zero rendered ticks is indistinguishable from broken; the F3.3 UI test used `NEXT_PUBLIC_MOCK_TICKS=1`, which synthesizes ticks client-side and bypasses the wire. design_review.md's BLOCKER 1 was literally "the live feed would stay empty" — the same class of bug was reintroduced at integration.
- **D4**: chip states derive "LIVE" from `connected` alone: `WatchMonitor.tsx:119`, `DecisionDesk.tsx:114`, `liveTicks.ts:60–62`. With D1 unfixed and LIVE_TICKS=1, WATCH shows a pulsing green **LIVE · ICICI** (hint "0 ticking") over 60 s Yahoo rows, and the DESK book shows LIVE over `p.last` desk marks (`DecisionDesk.tsx:171–177`). Even after D1 is fixed, a feed stall <120 s (watchdog window) keeps the chip LIVE while every row has already fallen back to Yahoo.
- Server state vocabulary (`OFF/LIVE/DEGRADED/UNREACHABLE`, uppercase) never matches the client's lowercase checks (`liveTicks.ts:59`) — the DEGRADED chip state is unreachable from the live path; UNREACHABLE renders as 'delayed'.
- No market-hours tick has ever been observed end-to-end (test_report admits this; deferred-verification is reasonable, but it means LIVE is unproven even backend-to-backend under real tick volume).

**10 needs:** rename one key (server alias `ticks` or 5-line client patch), chips derived from actually-fresh broker-sourced rows, one market-hours session with ticks rendered ≤2 s and a mid-session fallback flip demonstrated.

### (c) NEVER LIES — 6.5/10
- Contract real and adopted: `/api/stocks/ZZZ/detail` → 404 `{detail str, error{not_found, hint "Try the GO bar search…"}}` (F2.4 AC verified live). `errors.py` keeps `detail` a string with structured sibling (A2); `ui/lib/errors.ts` normalizes string/array/dict families (14-case harness). Per-symbol `source` labels truthful; A5 clamp verified (±25% → `chg_pct null` + "possible corporate action", test-pinned); chip tooltip "Yahoo … 60 s refresh" matches the actual 60 s quote TTL (`news_scanner.py:572`); DESK delayed hint says "desk marks at last close".
- **Deductions:**
  - D4 above (panel-level LIVE claim decoupled from row truth).
  - `/api/stocks/ZZZ/ohlcv` → `error.code:"upstream_down"` for a plain unknown ticker, message leaks the internal URL `http://localhost:8001/ohlcv/ZZZ` + an MDN link. Wrong code, internals on the wire.
  - `/api/lw/screener?days=-3` → 404 **"No OHLCV data in DuckDB"** — a false statement (there are 8.2M rows); the route validated nothing and misdiagnosed its own empty query. Should be 422 `invalid`.
  - Two 422 conventions: ui-api-local validation errors are raw FastAPI arrays with no `error{}` (`/api/stocks/RELIANCE/ohlcv?days=-10`), proxied data-service 422s come back as *stringified Python reprs* inside `detail` (`/api/market/events?start=2050-13-45`). The client normalizer survives both, but S7 "one convention" is half-kept.
  - Mixed timestamp conventions in one payload: `quotes.py:94` top-level `as_of` is naive local; Yahoo rows carry `+00:00`; ticks carry IST. A freshness comparison across fields is off by 5.5 h.
  - Observation for the owner (pre-existing, out of program scope): `/api/positions/summary` returned `cash_readings_10m: [453658.73, 1123699.91]` — a ₹6.7 L cash jump between consecutive readings at midnight. Something in the funds parse double-counts; worth an eye before trusting the capital line.

**10 needs:** chips from row-level truth, one 422 envelope everywhere, `not_found` for unknown tickers with no internal URLs, tz-aware `as_of` everywhere.

### (d) SURVIVES — 3/10
- The good, verified: `docs/RUNBOOK_RESTORE.md` exists and is mostly copy-pasteable; `scripts/db_backup.py` design is sound (snapshot-sourced, verify-row-count-before-compress, sha256 meta, 7 daily + 4 weekly rotation, zstd-optional honoring the shared-env rule); `db_backup_daily` (02:15) and `shared_snapshot_build` (19:20) are registered with real next-runs (GET :8008/api/scheduler/status, verified); failure path alerts via the pre-existing channel; unit tests exist (`scripts/tests/test_db_backup.py`, in the green 130).
- **The fatal, verified:**
  - **`git remote -v` is EMPTY. Last commit: 14 June 2026.** 481 untracked paths include `shared/momentum.py`, `shared/decision_desk.py`, `shared/trading_costs.py`, **all of `alpha_lab/`** (the S1 shadow that goes live today), and every Bloomberg-program file (live_ticks.py, quotes.py, cache.py, errors.py, db_backup.py, the runbook, ci.yml, liveTicks.ts). Runbook step 1 — `git clone <repo>` — **is impossible**: there is no remote, and even a local re-clone would resurrect a June repo with no Decision Desk, no alpha_lab, no terminal program.
  - `data/backups/duckdb/` **does not exist** — zero backups have ever been produced (first scheduled run is tonight 02:15). `data/snapshots/evening/` does not exist either, so tonight's backup will exercise the never-tested 4.4 GB `_consistent_private_copy` + zstd-level-6 path for the first time, unattended.
  - Backups land on the same disk as the database; offsite is a manual suggestion in runbook §6. A dead Mac tonight = total loss of 4 months of code and all data.
  - F1.3's own AC — "manual run produces a verified file" — was not met; the test_report defers it to "verify in the morning".
  - CI (`.github/workflows/ci.yml`) is correctly written (5 suites + tsc + purity scan, requirements-ci.txt exists) but **can never run**: no remote. Bar 6's "CI gates green" is aspirational.

**10 needs:** push to a private remote tonight; one real backup + one rehearsed restore into a scratch dir with row-count match; automated offsite copy; then the runbook as written is credible (it is well-made otherwise).

### (e) SCALES — 7/10
- Verified real, not just written: `cache.py` TTLCache used at 3 call-sites (`news_scanner.py:296` 600-cap, `commodity.py:81`, `gold_preopen.py:88`) and observable live — `GET /api/telemetry/caches` shows `news_scanner size 195/600, hits 2839, evictions 0, expired 133` (real traffic through the bound). `PRAGMA memory_limit` set (`duckdb_store.py:552`). **Event-loop purity proven by me**: `/health` p50 0.64 ms / p95 0.71 ms while 8 heavy scans ran concurrently; `scripts/check_event_loop.py` → 0 findings (my run). Push-not-poll architecture correct: one upstream WS, N clients on dict reads, ensure-on-GET self-heals restarts.
- **Deductions:**
  - **S6 unmet**: default payloads measured by me — `ohlcv-meta` 597,924 B · `fundamentals-screen` 528,290 B · `events` 244,306 B (budget: ≤150 KB; F2.5 AC "measured default payloads … ≤150 KB" simply not delivered — opt-in `fields=core` shipped instead, defaults unchanged).
  - **S1 violated by the new code itself (D6)**: `LiveTicks._requested` grows without bound while the engine is OFF/parked — eviction lives only in `_target_set()` (`live_ticks.py:278–286`), which only the armed worker calls; `ensure()` (`:134–145`) inserts unconditionally. Proven live: three GETs with garbage symbols drove `requested` 13 → 23 → 33, state OFF, nothing pruned. It also pollutes `/provider/status` telemetry.
  - The 69.5 MB bulk-per-call pattern + serialized heavy routes (see FAST) is a genuine dead-end left in place, acknowledged only as a ticket.
  - Hot-path smells at 100-user scale: new `httpx.AsyncClient` per request and a sync `last_holdings.json` read per poll (`quotes.py:32–38, 61`); the 2 s hook polls even when the feed is disconnected (F3.3 said poll only while connected) — cheap today thanks to the 60 s quote TTL, but it's a spec deviation.

**10 needs:** bulk-frame TTL + coalescing, budgets enforced on defaults, `_requested` pruned in `ensure()`, pooled client.

### (f) DISCIPLINED — 7.5/10
- Frozen zones untouched **in substance**: mtimes `momentum.py` Sep 28 21:56, `decision_desk.py` Sep 28 21:59, `trading_costs.py` Sep 27 11:38; `alpha_lab/strategies/*` and `PLAN.md` all pre-22:00 Oct 14; the only program-window touch is the sanctioned F2.3 hook (`alpha_lab/backtest/data_access.py:34`, 22:32, PLAN-amendment recorded) and the alpha_lab drift suite is green (my run). Triple semantic match verified: CLAUDE.md Trading Rules == `StrategyConfig` defaults (`momentum.py:29–43`: n=20, buffer 1.5, equity 0.66, sector 0.40, pos 0.15, dd −0.20, bulk-filter 0=OFF) == the live desk (`GET /api/desk/status` serves the same config).
- **Paper posture verified at runtime**: `GET /api/execution/status` → `mode:"PAPER"`; `get_engine()` defaults PAPER (`live_execution.py:1089`); AUTOPILOT_DEFAULT=off (`start-local.sh:144`) and every legacy trading job skips with "AUTOPILOT OFF" (`master_controller.py:434,491,520`). LIVE_TICKS confirmed off by behavior (state OFF), without reading `.env`.
- Docs truth: CLAUDE.md's 4-process table matches `./start-local.sh status` and my health curls; the five documented suites pass exactly as documented (779/779, my run); dead routes return bare 404s as tombstoned.
- **Deductions:** the mandated freeze check (`git diff HEAD --stat` clean on frozen files) is **vacuous** — those files are `??` untracked, so git diff can show nothing by construction; discipline held but is unverifiable by the stated means until a baseline commit exists. `start-local.sh status` still parades ml/feature/rl as red "down" rows and the scheduler registers 3 legacy no-op jobs — noise against the "4-process spine" story. B4's "amber census: 0 variants" misses 3 `#f59e0b` in `ui/lib/indicators.ts` (outside its components+app scope — a pedantic overclaim). CI gate exists but is unexecutable (no remote).

**10 needs:** commit the baseline so the freeze is diffable; status output that reflects the real spine.

---

## 2. Ranked defects

| # | Sev | What | Where | Repro |
|---|-----|------|-------|-------|
| D1 | **CRITICAL** | Live-tick wire contract broken: server key `quotes`, client reads `ticks` → UI can never render a tick; flagship F3.3 dead end-to-end | `services/ui-api/routers/quotes.py:94` vs `ui/lib/liveTicks.ts:44–49`; warned in `build_b4.md:93–95` | `curl ':8010/api/quotes/ticks?symbols=TCS'` → `"quotes":{…}`; grep `data.ticks` in liveTicks.ts |
| D2 | **CRITICAL** | No git remote, last commit 14 Jun, 481 untracked files incl. strategy + alpha_lab + whole program; runbook step 1 (`git clone`) impossible; CI can never run; zero backups exist (`data/backups/duckdb/` absent, first run 02:15 tonight, same disk) | repo root; `docs/RUNBOOK_RESTORE.md:29,51` | `git remote -v` (empty); `git status --porcelain \| grep -c '^??'`; `ls data/backups/duckdb` |
| D3 | HIGH | 3 in-session routes >500 ms warm (1.42 s / 2.9–3.1 s / 0.77 s), serialized ~0.73 s each under concurrency (8× → 6.6 s tail); 69.5 MB bulk pull per call, no cache/coalescing; test_report relabels its own bar-fail as "PASS with flags" | `alpha.py:201`, `lw_scanner.py:30–40,64,91` | 3× curl each route; 8 parallel curls + `/health` timing |
| D4 | HIGH | Chips claim LIVE from `connected` alone → with LIVE_TICKS=1: green LIVE·ICICI over Yahoo rows (WATCH) and last-close desk marks (DESK); ≤115 s lie window even after D1 fix | `WatchMonitor.tsx:119`, `DecisionDesk.tsx:114,171–177`, `liveTicks.ts:59–62` | code read; state-vocab case mismatch makes client 'degraded' unreachable |
| D5 | MED | S6/F2.5 AC unmet: default payloads 598 KB / 528 KB / 244 KB (budget ≤150 KB) | `/api/data/db/ohlcv-meta`, `/api/market/fundamentals-screen`, `/api/market/events` | `curl -w '%{size_download}'` each, no params |
| D6 | MED | `LiveTicks._requested` unbounded while engine OFF/parked (S1 violation in the S1-flagship module); pollutes status telemetry | `live_ticks.py:134–145` (insert), `:278–286` (only pruner, worker-only) | 3 GETs `:8001/live/ticks?symbols=<10 fresh garbage>` → `requested` 13→23→33 |
| D7 | LOW | Unknown-ticker OHLCV → `upstream_down` + internal URL + MDN link leaked; lw screener `days=-3` → 404 with false message "No OHLCV data in DuckDB" | stocks OHLCV proxy; `lw_scanner.py` | `curl ':8010/api/stocks/ZZZ/ohlcv?days=5'`; `curl ':8010/api/lw/screener?days=-3'` |
| D8 | LOW | Two 422 shapes on the wire: raw FastAPI arrays (local) vs stringified Python-repr detail (proxied) — S7 half-kept; client normalizer copes | compare `stocks/RELIANCE/ohlcv?days=-10` vs `market/events?start=2050-13-45` | curls above |
| D9 | LOW | Ops-surface noise contradicting the 4-process story: 3 legacy no-op jobs registered; status prints ml/feature/rl "down"; redis up but absent from the architecture table | scheduler status; `start-local.sh` | `./start-local.sh status` |
| D10 | LOW | Latency CSV: warm=min() best-case stat; `commodity/price/{symbol}` still measured as literal template (404) despite claimed param fix | `latency_after.csv` | grep the CSV |
| D11 | INFO | Mixed `as_of` conventions (naive local + UTC + IST) in one quotes payload; hook polls 2 s even when feed disconnected (spec said only-while-connected); per-request AsyncClient + sync file read on hot path | `quotes.py:32–38,61,94`; `liveTicks.ts` | payload read |
| D12 | INFO | Owner's eye: `cash_readings_10m` jumped ₹453,659 → ₹1,123,700 between consecutive midnight readings (funds parse suspect; pre-existing) | `/api/positions/summary` | curl it |

## 3. Probed and did NOT break
- **779/779 tests green** (all five suites, my run: 281+130+349+7+12) + `tsc --noEmit` clean + `check_event_loop.py` 0 findings.
- Event loop under fire: `/health` p95 **0.71 ms** while 8 heavy scans ran — the 8-Oct freeze class is genuinely fixed.
- ~18 malformed-input probes all handled: negative/huge `days` (bounds 5–9999), `limit` caps (2000/5000), negative skip, SQL-ish `search` (parameterized, empty result), null bytes (422 + envelope), 3,000-char symbol strings (length caps 1200/1500), 80 garbage symbols (capped at 60, honest `price:null source:yahoo`), `/live/ticks` garbage safe, `/ohlcv/FAKEZZ` clean 404, bulk `days=-1` → empty 200 (no crash).
- 37/37 page-audit artifacts verified by count (`reports/ui_audit/after*/audit.json`: 37 pages, ok=37, 0 console errors, 0 failed API).
- `db_backup_daily` (02:15) + `shared_snapshot_build` (19:20) registered with real next-runs; backup script's verify-then-compress + rotation logic reads correct and is unit-tested.
- Bounded caches live with real hit/evict counters; PAPER mode live-verified; desk config == frozen rules; prod UI build serving (`next-server 15.5.18`, `.next-prod`); modal z-scale (`Z.modal`) + ALERT `alertLayout="row"` + GO recall + tabular-nums landed as claimed; `/api/stocks/ZZZ/detail` hint exactly per AC.

## 4. The single biggest risk, tomorrow morning
The owner follows test_report's own instruction, adds `LIVE_TICKS=1`, and opens the terminal at 09:15. The engine connects (that part works), `connected:true` flows downstream, and WATCH and the DESK book light up with pulsing green **LIVE · ICICI** chips — while every price on screen is still a 60-second Yahoo quote or yesterday's desk mark, because the one field name nobody reconciled (`quotes` vs `ticks`) means no tick can reach the UI. He would be trading paper decisions against delayed data wearing a live label — the exact "staleness lie" this program was chartered to eliminate. And while he does so, nothing protects the system itself: no git remote, no commit since June, 481 untracked files including the approved strategy code, and a first-ever database backup that fires unattended at 02:15 tonight onto the same disk it is meant to protect. One disk failure erases the strategy, the terminal, and the program that built it. Fix order: commit+push tonight (10 min), rename one JSON key (1 line), derive chips from row truth (10 lines), then this verdict flips to CONDITIONAL-YES.
