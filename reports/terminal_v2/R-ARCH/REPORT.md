# R-ARCH — Architecture review: scalability, reliability, operability

Reviewer role: principal engineer. Scope: the running 3-process stack (data-service :8001, ui-api :8010,
master-controller :8008), its DuckDB data layer, the Redis/WebSocket tick path, the static-UI release flow,
watchdog/launchd self-healing, backups, secrets, telemetry, tests/CI and code hygiene. Review date: 4 Nov 2026,
22:10–22:40 IST, on the live Mac (M4 Pro, 12 cores, 24 GB, macOS 26.6.2), stack up since 21:27 IST after a reboot.
Method: read-only on the repository; GET-only, paced probes of the live services; an APFS clone of `market.duckdb`
opened read-only under the scratchpad; `ps`, `lsof`, logs. No service was restarted, no POST was sent.
Caveat on numbers: a parallel reviewer (R-UI) was running the headless-browser page audit at the same time
(load average 5–7), so every latency below is a **pessimistic** reading; the ordering and the contention
ratios are what matter, not the absolute milliseconds.

## Executive summary (10 lines)

1. As a **single-trader appliance on one Mac** the stack is unusually well engineered: self-healing watchdog with hang detection, verified nightly backups, downtime catch-up, freeze windows, atomic UI releases with rollback, Host/Origin guard, PAPER-only enforced in code. Rating 8/10 for that job.
2. As the **foundation of a Bloomberg-class, multi-user terminal** it is a 4–5/10: one process owns one DuckDB connection behind one global `threading.Lock`, so every read serialises. Measured: 10 concurrent distinct-symbol reads take 1,243 ms wall vs 134–165 ms each alone (sum 1,456 ms) — a 10-client burst is a queue, not a pool.
3. **The single largest risk is not scale, it is loss**: no `git remote`, no commit since **14 Jun 2026** (642 dirty paths, 348 untracked source files, 41,631 insertions uncommitted), Time Machine has **no destination**, the 20 GB of backups sit on the same internal SSD, and `ui/node_modules` (14,455 files) is still tracked. The runbook (§"Version control and off-machine backup") already prescribes the 20-minute fix; it has not been done.
4. Warm read latency is good: 17 of 20 key ui-api endpoints answer in **3–75 ms** warm; `/health` stays at 2–3 ms even during a 10-request burst on the heaviest route, so the event loop is clean (the 25 Oct loop-stall fix holds).
5. Memory is modest: data-service 1.44 GB RSS (DuckDB 4 GB cap), ui-api 470 MB, controller 68 MB, desktop shell 82 MB, Redis 1 MB. DuckDB file 4.44 GiB / 52 tables / 30.8 M rows — but **25 M of those rows are dormant ML tables** (`ml_features` 9.1 M × 75 cols, `ml_labels` 8 M), and 16 % of blocks are free: the hot store is carrying a cold warehouse, which inflates every clone, backup and copy.
6. Observability is half-built: structured JSON logging with correlation IDs exists in `shared/logging.py` but **no request ever sets a correlation id** (0 callers on the request path) and 99.9 % of ui-api log lines are plain uvicorn access lines (14 `/health` + 12 `GET /` per minute); `/metrics` does **not exist** on ui-api or data-service although CLAUDE.md and the previous review say it does. There are no SLOs.
7. Three different DuckDB access paths coexist in ui-api (HTTP via data-service; its own persistent read-only connection in `db.py` used by 4 routers; 4.4 GB `/tmp` snapshot copies via `snapshot.py`), contradicting the "single owner" rule and making the data tier hard to reason about or replace.
8. Engineering hygiene: 2,363 Python tests in five suites plus 11 UI checks and Rust tests, all in CI — good (the whole Python set runs in ≈ 1.6 min: ui-api 1,151 in 47 s, core 766 in 43 s, scripts 342 in 7 s). But **no ruff/mypy/black configuration or CI gate** (ruff: 1,315 findings incl. one `F821` undefined name and 255 blind `except`s; mypy: 247 errors and a duplicate-module-name error that blocks a whole-repo run), the CI pins (`fastapi==0.115.0`, `pandas==2.2.3`) are far from what production runs (`fastapi 0.141.1`, `pandas 3.0.3`), and `tests/test_gold_study_reproduce.py` failed collection today.
9. Security posture is right for loopback (binds, guard, keychain TOTP, no secrets in logs) with three loose ends: Redis listens on `*:6379` with no password (protected-mode is the only barrier), `.env` is mode 644, and `Settings` keeps secrets as plain `str` (not `SecretStr`), so a stray `print(settings)` leaks them.
10. Ordered fixes: (1) DR in a day [S]; (2) DuckDB read concurrency via per-request cursors + a read/write lock [M]; (3) split the cold ML tables out and VACUUM [M]; (4) one shared HTTP client + circuit breakers [S]; (5) `/metrics`, request ids, JSON access logs, SLOs [M]; (6) push fan-out instead of polling [M]; (7) persisted job queue [M/L]; (8) ruff + mypy + pin-drift gates in CI [S]; (9) Redis bind/auth, `.env` 600, `SecretStr` [S]; (10) chaos drills [M]; multi-user (auth, stateless ui-api, read replicas) only when a second user exists [XL].

---

## 1. What actually runs (verified)

| Process | PID | RSS | Threads | Port | Start → `Application startup complete` |
|---|---|---|---|---|---|
| data-service (`uvicorn main:app`) | 2497 | 1,444 MB | 33 | 127.0.0.1:8001 | 21:27:41 → 21:27:42 (≈ 1 s; Breeze connect fails 25 s later "Session key is expired", continues) |
| ui-api (`uvicorn main:app`) | 2803 | 469 MB | 47 | 127.0.0.1:8010 | 21:28:07 → ≈ 21:28:09; `cache_warm_done ok=8 failed=[] elapsed_s=44.28` |
| master-controller | 3303 | 70 MB | 8 | 127.0.0.1:8008 | 21:29:00 → ≈ 21:29:02; 44 jobs registered (37 `add_job` call sites + gold loop) |
| redis-server | 2486 | 3 MB | — | **\*:6379** | started by `start-local.sh start_redis` (no `--bind`) |
| SuryaDhana.app (Tauri) | 1029 | 82 MB | — | — | `--autostart` from launchd |
| caffeinate -s -i | 1040 | — | — | — | keeps the Mac awake |

Whole-stack start from the first banner to the controller's "startup complete": **≈ 80 s** (`start-local.sh` starts the
three services strictly in sequence and waits for each `/health`). Evidence: `.logs/{data-service,ui-api,master-controller}.log`
banners at lines 269944 / 27542 / 82088; `ps -axo pid,rss,…`; `lsof -iTCP -sTCP:LISTEN`.

Single uvicorn worker per service (no `--workers`), FastAPI's default 40-thread `anyio` pool for sync handlers.
data-service: **135 sync `def` endpoints, 4 async** (`services/data-service/main.py`), i.e. almost everything runs on
the 40-thread pool and then queues on the DuckDB lock below.

### 1.1 The data layer as built

- `storage/duckdb_store.py:505-540` — `DuckDBStore` opens **one** read-write `duckdb.connect()` for the process lifetime and
  serialises every operation with `self._lock = threading.Lock()`. The docstring explains why (a virtioFS lock race on
  Docker Desktop that does not apply to the native Mac stack that runs today).
- **42 call sites outside the store reach into `store._conn` directly** (`grep -rn "store\._conn"`: `main.py`,
  `fo_analytics.py`, `gold/*`), wrapped in `with store._lock:` by convention (27 such blocks in `main.py`). The invariant
  "one connection, one lock" is enforced by discipline, not by an API.
- `/db/market-monitor` (`main.py:2290-2313`) holds `_monitor_lock` while it may call **Yahoo `query1.finance.yahoo.com`
  on the request path** (`_nifty500_close`, 20 s timeout, fallback after NSE): one Yahoo stall blocks every monitor
  caller for 20 s, and it is a Yahoo caller outside the budgeted fetcher the CLAUDE.md anti-pattern names.
- The DuckDB file: 4.44 GiB, 52 tables, 30.75 M estimated rows, 1 view, 0 indexes; `pragma database_size` reports
  18,193 blocks of 256 KiB with 15,333 used — **≈ 0.7 GB of free blocks** (never vacuumed). Top tables (APFS clone, read-only):

| table | rows | cols | note |
|---|---|---|---|
| ml_features | 9,126,027 | 75 | legacy 5-day ML, dormant (autopilot OFF) |
| nse_bhavcopy | 8,255,173 | 15 | the survivorship-free panel (hot) |
| ml_labels | 8,033,226 | 10 | legacy ML, dormant |
| nse_mtf | 2,120,432 | 5 | |
| ohlcv | 1,813,136 | 10 | Yahoo history (hot) |
| ml_oos_predictions | 353,691 | 5 | dormant |
| nse_fo_daily | 329,822 | 16 | F&O (hot for DERV/OSTR) |

  → **~57 % of rows and most of the width belong to the dormant ML era.** Every evening snapshot (19:20), every 02:15
  backup, every `/tmp/bt_snapshot.*` copy and every restore drags them along. `data/` is 36 GB: 20 GB backups
  (uncompressed 4.7 GB copies; `.zst` is optional and unused), 8.8 GB snapshots, 4.4 GB live DB, 1.5 GB NSE archive.
- ui-api's three ways to read the same data:
  1. HTTP to data-service (`DATA_SVC`), the documented path — ~130 `httpx.AsyncClient(...)` constructions across
     12 routers (markets.py 45, pipeline.py 28, data_proxy.py 18, …), **none module-level**: a new client, a new
     connection pool and a fresh TCP connection per request; timeouts range from 3 s to 600 s.
  2. `services/ui-api/db.py` — "a SINGLE persistent read-only connection at module startup" on the **live**
     `market.duckdb` (DuckDB ≥ 1.1 allows it), used by `analytics.py`, `dashboard.py`, `desk.py`, `stocks.py`.
  3. `services/ui-api/snapshot.py` `ReadSnapshot` — a versioned **4.4 GB copy in `/tmp`** (`bt_snapshot.<ns>.duckdb`,
     one present now, made 21:28 at boot) for analytics/backtests; stale-while-revalidate on file signature.
  `routers/alpha.py` documents yet another rule ("must NOT open the DB directly … pulls the full-universe OHLCV over HTTP").
  Four conventions for one database is the tell that the tier has no owner-defined read API.

### 1.2 Live data / tick path

- Breeze L1 ticks: `services/data-service/live_ticks.py` (`LIVE_TICKS` default **OFF**; one worker thread; union
  subscription ≤ 50 symbols with a 10-minute TTL; DEGRADED watchdog; bounded `tick_store` parquet parts, 50,000-row
  buffer with drop-oldest). Design is sound and bounded. Today `data/ticks` is empty (ticks never armed).
- Browser-facing live data is **polling**, not push: in the last 60,000 ui-api access lines `/api/market/nifty-live`
  3,343 hits, `/api/notifications/feed` 2,668, `/api/alerts/feed` 673, `/api/positions/connection-status` 704,
  `/health` 8,665 and `GET /` 8,031 (desktop boot gate + app health poll, ≈ 14 + 12 per minute). The one WebSocket,
  `/ws/monitor` (`routers/monitor.py`), forwards Redis `live.quotes` pub/sub; Redis currently has one channel and
  1 MB used. Redis is also the `monitored.stocks` set for the watchlist poller. There is no backpressure design for
  browser clients beyond the hub's send loop; with `LIVE_TICKS=0` the question is moot today.

### 1.3 Jobs, scheduler, self-healing

- `scripts/master_controller.py` (3,582 lines): APScheduler `AsyncIOScheduler`, 44 jobs, per-job history persisted to
  `data/.scheduler_history.json`, a 60 s heartbeat file for downtime detection, `startup_catchup` that re-runs the
  EOD pipeline and key gold jobs after an outage (it did exactly that at 21:30 today: "EOD pipeline re-run: bhavcopy
  +3 day(s)"), freeze-window deferral, Telegram alerts. `/api/scheduler/metrics` gives per-job latency stats
  (e.g. `gold_fred_daily` 390 s, `gold_mcx_master` 30 s).
- data-service `jobs.py` `JobManager`: in-process daemon threads, one job per kind, **no persistence, no queue, no
  lease** — a crash mid-job loses the job; the controller's catch-up is what makes this survivable.
- `scripts/stack_watchdog.sh` (568 lines, launchd every 2 min): two-check debounce, paused markers, hang detection
  (listening but `/health` failing), diagnostics capture to `.logs/hangs/`, ≤ 3 hang restarts/hour, freeze-window
  awareness, boot-epoch-aware stale lock, Telegram direct to the Bot API, optional healthchecks.io dead-man ping
  (`HEALTHCHECK_PING_URL` is **not set** today; no `.pids/watchdog/deadman` file). `.logs/watchdog.log` since 19 Oct:
  38 start actions, 3 "the stack was down" alerts (25 Oct 14:42 hang, 30 Oct 08:10, 4 Nov 21:29 reboot), 0 hang restarts.
- Backups: `scripts/db_backup.py` 02:15 daily — verified (read-only open + row count + sha256), 7 daily + 4 weekly,
  settings store via SQLite online backup, flock single-run; `market-20261104.duckdb` made 21:37 tonight by the missed-night
  catch-up. **All on the same disk.**

### 1.4 Release flow and security

- UI: `scripts/build_ui.sh` builds a static Next export into `ui/dist/releases/<id>/` and atomically swaps `ui/dist/current`
  (`--rollback`, `--list`, keep 3). `/version` reports `ui_build id=20261025-223942-0ae66db, git_sha 0ae66db, git_dirty=true`.
  Python services deploy by `./start-local.sh restart <svc>` — there is no CI/CD deploy, no canary, no blue/green; the
  desktop app via `scripts/build_desktop.sh --install` (ad-hoc signed).
- `shared/http_guard.py` (529 lines) — Host/Origin/CSRF/DNS-rebinding guard as the outermost ASGI middleware on all
  three services; remote clients (Tailscale) read-only unless `GUARD_ALLOW_REMOTE_WRITES=1` (not set). 6 test files cover it.
- Secrets: `.env` (88 keys in `.env.example`, git-ignored, **mode 644**), ICICI TOTP in the Keychain
  (`shared/icici_login.py`, `routers/positions.py`), Settings via pydantic-settings — secrets typed as plain `str`
  (0 `SecretStr`). Logs: 0 lines matching key/token patterns across the three service logs. PAPER-only enforced
  (`execution.enforce_paper_only_at_startup`). Redis: `bind * -::*`, `protected-mode yes`, no `requirepass`.

---

## 2. Measurements

### 2.1 Latency, 20 key ui-api endpoints (GET, paced 0.5 s, 1 "first" + 3 repeats; `latency.json` in the scratchpad)

The stack had been up 55 minutes and `_cache_warm` had run, so "first" is *first in this session*, not a true cold
start — a real cold start was not possible without a restart (forbidden). Where a cache header was returned it is shown.

| endpoint | first ms | repeat ms (3) | bytes | note |
|---|---|---|---|---|
| /health | 12.9 | 3, 3, 3 | 34 | |
| /api/market/nifty-live | 17.2 | 17, 28, 18 | 168 | proxied to data-service each call |
| /api/notifications/feed | 4.2 | 5, 5, 5 | 13,068 | polled every few s by the shell |
| /api/alerts/feed | 4.5 | 5, 4, 3 | 9,470 | |
| /api/dashboard/summary | 44.3 | 42, 47, 42 | 437 | reads DuckDB via db.py |
| /api/desk/status | 3.7 | 7, 6, 2 | 11,141 | |
| /api/market/monitor | 75.1 | 73, 74, 69 | 79,373 | cached snapshot, 79 KB gzip |
| /api/market/internals | 20.1 | 22, 25, 22 | 43,749 | |
| /api/market/index-contribution | 37.2 | 30, 27, 28 | 4,752 | |
| /api/market/results-recent?days=95 | 5.9 | 3, 3, 3 | 183,912 | SWR `stale` |
| /api/market/fundamentals-screen (2500, core) | 12.7 | 8, 15, 15 | 269,437 | SWR `hit` |
| /api/market/option-chain/NIFTY | 34.6 | 35, 36, 43 | 13,140 | |
| /api/derivatives/term-structure | 29.9 | 30, 20, 31 | 671 | |
| /api/derivatives/vix | 48.9 | 72, 95, 22 | 36,084 | |
| /api/derivatives/option-history/NIFTY | 24.2 | 29, 34, 29 | 26,834 | |
| /api/stocks/RELIANCE/detail | 34.5 | 35, 29, 50 | 835 | |
| /api/charts/ohlcv?symbol=RELIANCE&days=400 | 30.5 | 9, 26, 14 | 20,539 | |
| /api/gold/overview | **606.6** | 10, 3, 3 | 34,129 | SWR `miss` → then memo |
| /api/positions/open-positions | **865.1** | 2, 2, 2 | 43 | first call probes Breeze (session expired) |
| /api/market/events | 60.2 | 62, 57, 60 | 245,125 | 245 KB per call, no cache header |

Reading: warm p50 across the 20 is **≈ 25 ms**, p95 ≈ 75 ms; this matches the 14 Oct review (7–50 ms). The three
"slow firsts" are a cache miss (gold), a broker probe (positions) and a large uncached payload (events).

### 2.2 Ten concurrent clients on the heaviest three (+ `/health`), one burst each, 5 s apart

| endpoint | 10× wall ms | p50 ms | max ms | min ms | vs single |
|---|---|---|---|---|---|
| /api/positions/open-positions | 13.6 | 12.0 | 13.4 | 11.1 | cached, trivially parallel |
| /api/gold/overview | 24.9 | 15.7 | 24.8 | 6.4 | memo + single-flight works |
| /api/market/monitor | **372.3** | **219.7** | 371.5 | 115.7 | 75 ms alone → **×2.9 p50, ×5 max** |
| /health | 16.6 | 11.3 | 16.5 | 4.7 | |
| /health **during** the positions burst | 3.2 | | | | event loop not blocked |

### 2.3 DuckDB lock contention, distinct-symbol reads (`contention.json`)

| test | result |
|---|---|
| A. ui-api `/api/stocks/{sym}/history?days=3700`, 5 symbols, sequential | 275, 229, 215, 177, 246 ms (≈ 525 KB each) |
| B. same route, **10 different symbols concurrently** | wall **1,185 ms**, p50 648, min 217, max 1,185 |
| C. B repeated (second time) | wall 1,202 ms, p50 650 — **no caching, same cost** |
| D. data-service `/db/security/{sym}/history?days=3650` direct, 10 concurrent | wall **1,243 ms**, p50 672, min 145, max 1,243 |
| E. same 10, sequential | 134–165 ms each, **sum 1,456 ms** |
| F. data-service `/health` during the 10-burst | 2.3 ms (loop fine; the pool threads queue, not the loop) |

**D ≈ E**: ten concurrent reads cost the same as ten sequential reads. On a 12-core machine with DuckDB's own
vectorised multithreading, that is the `threading.Lock` in `DuckDBStore` (and the per-call `with store._lock` around
`store._conn`) serialising readers behind each other. Linear in clients: 100 concurrent page loads of one history
chart ≈ 15 s for the last one.

### 2.4 Logs and errors (reliability signal)

| log | lines | 5xx | loop_stall | tracebacks |
|---|---|---|---|---|
| ui-api.log (since 31 Oct) | 32,426 | 0 | 0 | 0 |
| ui-api.log.1 (25–31 Oct) | 293,293 | 40 | 1 | 3 |
| ui-api.log.2 (to 25 Oct) | 230,892 | 312 | 1 | 0 |
| data-service.log | 272 k | 75 | — | 2 |

5xx are dominated by upstream live-data failures surfaced verbatim (`/api/data/live/index/nifty` 113,
`/api/market/nifty-live` 63+17, `gift-nifty` 39; data-service `/db/nifty-live` 26, `/db/gift-nifty` 26): NSE's site
flakes become the terminal's 5xx with no stale-serve fallback for those routes.

Log format mix (last 20,000 lines): ui-api **json=4, uvicorn access=19,992**; data-service json=346, access=19,651.
The structured logger exists but the signal-to-noise is ≈ 1:5,000 on ui-api.

---

## 3. Ratings (0–10) with the evidence each rests on

| area | score | evidence |
|---|---|---|
| Single-host reliability & self-healing | **8** | watchdog hang detection + debounce + diagnostics (`stack_watchdog.sh`), launchd autostart, `startup_catchup` re-ran the EOD pipeline tonight, freeze windows, verified backups, 0 5xx / 0 stalls since 31 Oct, `/health` 2–3 ms under burst. Minus: in-process jobs without persistence; Breeze session expiry handled by "continue with yfinance" rather than a state machine visible on SYS. |
| Disaster recovery / code safety | **2** | `git remote -v` empty; last commit 14 Jun 2026; `git status --porcelain` 642 (454 untracked, 348 of them .py/.ts/.tsx/.rs); `tmutil destinationinfo`: "No destinations configured"; 20 GB of backups on the same SSD; 14,455 `ui/node_modules`+`.next` files tracked; `.git` 1.5 GB. The runbook §"Version control and off-machine backup" (written 25 Oct) is still a to-do. |
| Data-tier scalability | **4** | one connection + one `threading.Lock` (`duckdb_store.py:519-521`); 42 `store._conn` bypasses; 10-concurrent = sum of sequential (§2.3); 57 % of rows are dormant ML tables; 0.7 GB free blocks; three read conventions in ui-api; 4.4 GB `/tmp` copies; Yahoo on the request path under the monitor lock. |
| API-tier scalability | **5** | 1 uvicorn worker each; 135 sync endpoints on a 40-thread pool; ~130 per-request `httpx.AsyncClient` constructions, no shared pool; module-dict caches make ui-api stateful (cannot run two instances); warm p50 ≈ 25 ms is genuinely good. |
| Live-data / streaming | **5** | bounded, kill-switched tick engine with a DEGRADED watchdog is the right design; but browser consumption is polling (3,343 nifty-live polls / 60 k lines), one WS route only, no fan-out of ticks to the browser, no per-client backpressure policy, `LIVE_TICKS` still off. |
| Observability | **4** | `/metrics` 404 on :8001 and :8010 (CLAUDE.md "All services expose /health, /ready, /metrics" is false; the 14 Oct review's "Prometheus endpoints already exist" is also false); `set_correlation_id` has 0 request-path callers; no request-id header; access-log noise 26 lines/min from health/boot polls; good: `_loop_watchdog` stall dumps, `kill -USR1` stack dumps, `/api/telemetry/caches` hit/miss per cache, `/api/scheduler/metrics` per-job latency, `.logs/hangs/` captures. No SLOs, no synthetic probes, no tracing. |
| Security & secrets | **6** | loopback binds + outermost Host/Origin guard on all three + remote read-only + PAPER enforced + Keychain TOTP + 0 secret patterns in logs. Minus: Redis on `*:6379` without auth (protected-mode only), `.env` 644, `str` not `SecretStr`, no auth at all on the API (acceptable for one user on loopback; a hard stop for a second user), swagger off by default (good). |
| Operability | **7** | `start-local.sh` start/stop/status/logs/rotate/build-ui with paused markers and append-safe rotation; runbook with outage, reboot, FileVault, Tailscale sections; `/version` with build provenance; UI rollback. Minus: 1,074-line bash + 3,582-line controller + 3,153-line data-service `main.py` as the operational core; deploy = restart by hand; `startup_catchup` and gold backfills compete at boot (`gold_overnight: already running`). |
| Tests | **7** | 844 (tests) + 355 (scripts) + 1,137 (ui-api) + 7 (execution) + 20 (alpha_lab) = **2,363** Python tests, 11 UI node checks, 2 release-builder tests, Rust `cargo test`, boot-page checks, desktop E2E — all wired in `.github/workflows/ci.yml` (python 30 min, ui 15 min, desktop 45 min). Minus: `tests/test_gold_study_reproduce.py` fails collection today (`NameError: dataclass` in `scripts/gold_studies/gs_p2_wgc_flows.py:64`, likely the concurrent gold fix round); no coverage measurement; CI runs pins that production does not. Run times: see §5. |
| Type safety & lint | **3** | no `pyproject.toml`/`ruff.toml`/`mypy.ini`/pre-commit anywhere; CI has no lint/type step for Python (only `tsc`, `cargo clippy/fmt`); `ruff check` 1,315 findings (F/E9/B/ASYNC subset: 230, incl. `F821 pd` in `providers/direct_yahoo_provider.py:219`, 65 `B904`, 2 `ASYNC230` blocking `open()` in async routes, 255 `BLE001`, 75 `S110` try/except/pass); `mypy`: 15 + 174 + 58 = **247 errors**, and `services/data-service/main.py` vs `services/ui-api/main.py` "Duplicate module named main" blocks the documented whole-repo command. |
| Dependency hygiene | **3** | `requirements.txt` pins `fastapi==0.115.0 uvicorn==0.30.6 httpx==0.27.2 pandas==2.2.3 numpy==1.26.4`; the shared `jupyter_env` runs `fastapi 0.141.1 uvicorn 0.54.0 httpx 0.28.1 pandas 3.0.3 duckdb 1.1.1`; `requirements-ci.txt` differs by 17 lines from `requirements.txt`; `start-local.sh` deliberately only *verifies imports* because the env is shared with other projects (memory: it broke them once). CI green ≠ prod green. |
| Documentation | **8** | 22 docs + 160 report markdowns, a runbook that reads like an SRE's, data dictionaries, per-program PLAN/FINDINGS, `IMPROVEMENT_LOG`. Minus: drift (the `/metrics` claim; "data-service is the ONLY writer/owner" vs `db.py`'s live read-only connection; the docstring's virtioFS rationale for the global lock no longer applies to the native stack). |

**Overall: 8/10 as a one-trader Mac appliance; 4.5/10 as the base of a Bloomberg-class multi-user platform.**

---

## 4. Bottlenecks a 10× future hits, in the order they would hit

### 4.1 10× data (44 GB DuckDB, 300 M rows; ticks armed; F&O chains intraday)
1. **The global lock** — every read waits for every other read *and* for every ingest write (`upsert_*` under the same
   lock). The 18:30 EOD pipeline already runs for minutes; at 10× it blocks the terminal's reads for the whole pipeline.
2. **Copies** — evening snapshot, backup, `/tmp/bt_snapshot`, analytics `ReadSnapshot`: each is a full-file copy
   (APFS clone makes the *copy* free, but the copy-on-write cost and the backup/verify/sha256 scan are not); at 44 GB
   the 02:15 backup verify alone is tens of minutes and the 20 GB `data/backups` becomes 200 GB.
3. **The 4 GB `DUCKDB_MEMORY_LIMIT`** on one shared connection — one analyst query spills, every request waits.
4. **`ml_features` 75-column width** — any `SELECT *` on the ML tables is 10× the IO; they should not be in the hot file.
5. **Tick persistence** — parquet part files per 30 s, no compaction or retention job ("stated follow-up").

### 4.2 10× pages (430 panels), same user
1. **Polling fan-in** — today ≈ 100 requests/min at idle with 43 pages; the shell polls `/health`, `/`, feeds. At 10×
   with the same pattern ui-api serves 1,000 req/min of mostly identical answers — fine for one worker, but every one
   of them is a new `httpx.AsyncClient` to data-service (connect handshake, no keep-alive reuse).
2. **Module-dict caches per process** — cannot add a second ui-api worker without duplicating every cache and warm-up
   (44 s warm, 8 calls) and losing single-flight.
3. **Per-page SWR warm list** is hand-maintained (`_cache_warm.warm_calls`) — does not scale with page count.
4. **Bundle** — one static export, 189 files / 6.6 MB (1.96 MB gzip); more pages → bigger first load unless per-page
   chunks are enforced.

### 4.3 Multi-user (10 traders, phone + desktop)
1. **No identity** — no auth, no per-user prefs beyond one SQLite, no rate limits, no audit of who sent a paper order.
2. **Stateful ui-api** — cannot scale horizontally; sticky sessions would be needed; the WS hub is process-local.
3. **One Breeze session** — one broker login, one TOTP, one rate budget shared by all users.
4. **Redis unauthenticated on all interfaces** — the moment the Mac is on a LAN with other hosts this is an open
   pub/sub bus.
5. **Reads still serialise** — ten users × 10 panels = the §2.3 curve.

---

## 5. Engineering hygiene detail

### Test suites (counts from `--collect-only`; run times measured here, CI exclusions applied)

| suite | tests | run time (this Mac, under load) | notes |
|---|---|---|---|
| `tests` | 844 (+1 collection error) | **766 passed, 9 skipped in 43.2 s** (desktop_ops + the broken gold-study file excluded, as CI does) | `test_gold_study_reproduce.py` NameError today (excluded for the timing) |
| `scripts/tests` | 355 | **342 passed in 7.3 s** (test_ops_shell excluded, as CI does) | controller, Telegram bot, watchdog (5 files) |
| `services/ui-api/tests` | 1,137 collected / 1,151 passed | **46.8 s** | routers, guard (6 files), event-loop purity, cache |
| `services/execution-service/tests` | 7 | 0.03 s | |
| `alpha_lab/tests` | 20 | 0.37 s | |
| UI `__tests__/*.check.ts` | 11 files | — | plain node, as CI |
| `ui/scripts/*.test.mjs` | 2 | — | release builder |
| Rust | `cargo test` | — | desktop shell (17,564 lines) |

Code volume: ui-api 41 k Python lines, scripts 44 k, data-service 17 k, shared 3 k, UI 51 k TS/TSX (114 components,
largest `ModelLab.tsx` 1,586 lines), desktop 17.6 k Rust. Largest Python files: `routers/gold.py` 4,328,
`master_controller.py` 3,582, data-service `main.py` 3,153, `routers/analytics.py` 2,234.

### Lint / types (none configured; measured ad hoc)
- `ruff check shared services/ui-api services/data-service scripts/master_controller.py`: 1,315 (659 auto-fixable);
  top: UP045 342, BLE001 255, I001 105, RUF100 79, S110 75, B008 66, DTZ011/007/005 120 (naive datetimes in a
  timezone-critical system), B904 65, B905 56, F401 26, B023 4, ASYNC230 2 (`routers/dashboard.py:309`,
  `routers/pipeline.py:1189` open files on the loop), F821 1.
- `mypy --ignore-missing-imports`: shared 15, ui-api 174, data-service 58; whole-repo invocation (as CLAUDE.md
  documents it) aborts on the duplicate `main` module name.
- `black` not installed in the environment.

### CI (`.github/workflows/ci.yml`)
Three jobs: `python` (5 pytest suites + desktop baseline tools, 30 min), `ui` (`npm ci`, `tsc --noEmit`, node checks,
15 min), `desktop` (macOS: cargo fmt/clippy/test, boot check, release-builder tests, desktop contract/static tests,
45 min). **No** ruff/mypy/black, no dependency audit (`pip-audit`), no container build, no deploy, no coverage.
Pins installed in CI are not the pins running in production (§3).

---

## 6. Ordered fixes (cost S/M/L/XL, risk, what it buys)

| # | fix | cost | risk | why / evidence |
|---|---|---|---|---|
| 1 | **Disaster recovery today**: run the runbook's 20-minute recipe (ignore rules, `git rm --cached ui/node_modules ui/.next`, commit, private remote), then an off-machine copy of `data/backups` (rclone to an object store or an external SSD) and a Time Machine destination; set `HEALTHCHECK_PING_URL`; `sudo pmset -a autorestart 1` | S | low | §3 row 2. Nothing else on this list matters if the SSD dies. |
| 2 | **DuckDB read concurrency**: give `DuckDBStore` a `read(sql, params) -> df` that runs on `self._conn.cursor()` (a per-call cursor shares the DB, has its own transaction context, and is the DuckDB-documented way to use one database from many threads), guarded by a **readers-writer lock** (`write()` exclusive, `read()` shared); retire the 42 `store._conn` bypasses behind it; raise the pool with `anyio.to_thread.current_default_thread_limiter().total_tokens` to match; take Yahoo out of the `/db/market-monitor` request path | M | medium (ingest races must stay exclusive; test with the §2.3 harness) | §2.3: 10 concurrent reads cost 10 sequential. Expected: wall ≈ max single (~250 ms) instead of 1.2 s. |
| 3 | **Split cold from hot**: move `ml_features`/`ml_labels`/`ml_oos_predictions` (25 M rows, dormant) to parquet or a second `ml.duckdb` attached only by the ML jobs; `EXPORT/IMPORT` or `VACUUM` the hot file to reclaim the 0.7 GB; compress backups (`.zst` path already exists) | M | low–medium (ML job paths + `/db/ml-stats`, `/db/training-sample` need the ATTACH) | halves the hot file, every copy/backup/clone/restore; a 4 GB memory cap then fits the working set. |
| 4 | **One `httpx.AsyncClient` per process** (module-level, `limits=httpx.Limits(max_connections=32, max_keepalive_connections=16)`, per-route timeout objects) + a per-upstream circuit breaker and stale-serve for `nifty-live`/`gift-nifty`/`indices-live` | S | low | ~130 per-request clients; 312 + 40 5xx were upstream flakes passed through (§2.4). |
| 5 | **Observability contract**: Prometheus `/metrics` on all three (request count/latency histograms by route family, DuckDB lock wait time, job durations, cache hit ratio, tick lag); a request-id middleware that calls `set_correlation_id` and echoes `X-Request-ID`; JSON access log via the structured logger with `/health`, `/`, `/live` sampled or excluded (`--no-access-log` + own middleware); fix CLAUDE.md | M | low | §3 row Observability; CLAUDE.md promises `/metrics`. |
| 6 | **SLOs and a synthetic probe**: p95 ≤ 150 ms warm for the 20 routes in §2.1, ≤ 1.5 s first paint of any page, data freshness ≤ 1 session, job success ≥ 99 %/30 d; the probe runs from the controller every 5 min and lands on SYS with an error budget | S | low | there is no definition of "fast enough" today; the previous review measured but did not commit to targets. |
| 7 | **Push, not poll**: extend `/ws/monitor` into a typed multiplexed channel (`nifty`, `notifications`, `alerts`, `ticks:<sym>`) fed once from data-service (Redis pub/sub already in place), per-client bounded queue with drop-oldest and a `lag` counter the UI shows as a chip; keep polling as fallback | M | medium (UI subscriptions, reconnection) | 3,343 + 2,668 + 673 polls per 60 k lines are the same answer re-fetched; needed before `LIVE_TICKS=1` reaches the browser. |
| 8 | **Persisted job queue**: a `jobs` table (id, kind, state, lease, attempts, progress, result) in a small SQLite/DuckDB owned by the controller; data-service workers claim with a lease; idempotent steps (the `eod_steps` contract already is); exactly-once by `(kind, date)` key; the controller's catch-up becomes "re-enqueue unfinished", not "guess from heartbeat" | M/L | medium | `JobManager` is in-memory threads; the 15 Oct and 4 Nov catch-ups show the controller doing the queue's job by inference. |
| 9 | **Quality gates in CI**: `ruff` with a starter `pyproject.toml` (`select = ["F","E9","B","ASYNC","DTZ"]`, grow later), `mypy` per package with `explicit_package_bases` (fixes the duplicate `main`), a pin-drift check (`pip freeze` vs `requirements.txt` diff fails the job), `pip-audit`; fix the `F821` and the two `ASYNC230` now | S | low | §5; 1 undefined name and blocking `open()` on the loop are live bugs waiting. |
| 10 | **Environment isolation**: one venv per service family (or a `uv` lockfile) so CI installs what prod runs; keep `jupyter_env` for notebooks | M | medium (the shared-env break noted in memory is the reason this was avoided) | fastapi 0.115 pinned vs 0.141 running; pandas 2.2 vs 3.0. |
| 11 | **Secrets and Redis**: `redis-server --bind 127.0.0.1 --requirepass <keychain>`; `chmod 600 .env`; `SecretStr` for the 5 secret fields; a `scripts/tests` test that `repr(Settings())` contains no secret | S | low | §3 security. |
| 12 | **Chaos drills as tests**: scripted `SIGSTOP` ui-api / `SIGKILL` data-service mid-ingest / Redis down / disk 95 % / Breeze expired / clock skew, each with the expected watchdog + UI outcome, run monthly from the controller on a Sunday | M | low (run against a staging copy of the DB) | the 25 Oct hang needed root-only native sampling to diagnose; drills make the next one a known quantity. |
| 13 | **Snapshot policy**: one read-only snapshot per evening (exists) + one *per-process* read-only connection to it for analytics, instead of `/tmp/bt_snapshot.*` per ui-api boot; prune orphans at start | S | low | 4.4 GB in `/tmp` created at 21:28 tonight. |
| 14 | **Shrink the cores**: split `data-service/main.py` (3,153) into routers by domain, `master_controller.py` (3,582) into jobs/, `start-local.sh` into a small Python CLI with the same verbs | L | medium (regression surface; the equivalence audit harness from the desktop program can be reused) | review velocity and onboarding; 135 sync endpoints in one file hide the lock discipline. |
| 15 | **Multi-user groundwork (only when a second user exists)**: OIDC/passkey auth in front of ui-api, per-user prefs/alerts/paper books, rate limits, stateless ui-api (caches to Redis), N ui-api workers behind a local proxy, read replicas = per-instance read-only DuckDB on the nightly snapshot (DuckDB has no server mode; for true concurrency the read path moves to ClickHouse/Postgres+parquet) | XL | high | §4.3; do not start before 1–8. |

---

## 7. What the best would do differently (named references)

- **Bloomberg** runs the terminal as a thin client against a server tier with one subscription per instrument
  fanned out to all screens (B-PIPE semantics); the equivalent here is fix 7 — one Breeze/NSE subscription in
  data-service, N browser clients on a multiplexed WS with per-client backpressure.
- **TradingView / IBKR TWS** use a single long-lived connection with pooled keep-alive to their backends; fix 4.
- **LSEG Workspace** separates the *real-time* store from the *reference/history* store; fix 3 is the small-scale version.
- **Google SRE practice** (SLOs with error budgets, synthetic probes, request ids on every hop, RED metrics):
  fixes 5 and 6 are the minimum; the loop-stall watchdog and `.logs/hangs/` captures are already better than most shops.
- **Thinkorswim / Quantsapp** persist every long computation as a job with progress the UI can attach to after a
  reload; fix 8.
- **Any top-tier team** has the repo on a remote with CI gates (ruff/mypy/audit) and a restore drill they have
  actually run: fixes 1, 9, 12.

---

## 8. Open questions for the owner

1. Is a second user (or the phone via Tailscale) in scope in the next 6 months? It decides whether fixes 2–8 are
   enough or fix 15 starts now.
2. May the dormant ML tables leave `market.duckdb` (parquet archive, ATTACH on demand)? They are 57 % of the rows.
3. Where may the off-machine backup go (cloud object store vs an external SSD at a second location)? And may the
   repo have a private remote (GitHub/GitLab) — the runbook assumes yes.
4. Is replacing the shared `jupyter_env` for the three services with a per-stack venv acceptable now that the
   earlier shared-env break is understood?
5. When `LIVE_TICKS=1` is armed, is the browser to receive ticks (needs fix 7) or only the data-service bars/VWAP?
6. Redis: may it be bound to loopback with a password (one line in `start_redis`)? The legacy Docker stack is the
   only consumer that would need the change mirrored.

---

## Appendix A — files and endpoints the ratings rest on

Code: `start-local.sh` (1,074), `scripts/stack_watchdog.sh` (568), `scripts/master_controller.py` (3,582),
`services/data-service/main.py` (3,153), `services/data-service/storage/duckdb_store.py` (1,837; lock at 505–540),
`services/data-service/jobs.py`, `live_ticks.py`, `tick_store.py`, `eod_steps.py`, `services/ui-api/main.py` (215),
`routers/_cache_warm.py`, `routers/_loop_watchdog.py`, `routers/monitor.py` (WS), `cache.py` (TTLCache/SWRCache),
`db.py`, `snapshot.py`, `static_ui.py`, `shared/http_guard.py` (529), `shared/logging.py`, `shared/config.py`,
`scripts/db_backup.py`, `scripts/build_evening_snapshot.py`, `scripts/build_ui.sh`, `.github/workflows/ci.yml`,
`docs/RUNBOOK_RESTORE.md` §"Version control and off-machine backup", `reports/production_review/scale_latency.md`
(14 Oct baseline), `reports/desktop_app/FINAL_REPORT.md` §7–9.

Live probes (GET only): `:8001/health /ready /db/stats /db/freshness /jobs /openapi.json` (126 paths: 102 GET / 25 POST),
`:8010/health /ready /live /version /openapi.json` (254 paths: 190 GET / 62 POST / 3 DELETE / 2 PUT)
`/api/telemetry/caches /api/telemetry/status`, `:8008/health /api/scheduler/status /api/scheduler/metrics`;
`:8001/metrics` and `:8010/metrics` → 404.

Scratchpad artefacts: `/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-ARCH/`
`latency.py`, `latency.json`, `latency.log`, `contention.py`, `contention.json`, `contention.log`, `mypy_per_target.txt`,
`test_runs.txt`, `test_runs2.txt`, `openapi_ui.json`, `openapi_ds.json`, (the read-only APFS clone `dbclone/market.duckdb` was removed after the review).

## Appendix B — honesty notes on the measurements

- "First" latency is first-in-session after 55 min of uptime and a completed cache warm, not a cold process.
- The R-UI headless-browser audit ran concurrently (load 5–7 on 12 cores); absolute latencies are pessimistic.
- `startup_catchup` had just re-run the EOD pipeline (21:30–21:38); the DuckDB lock was free by 22:20 when the
  contention runs started (`/jobs` showed only the 5-minute `gold_intraday_bars`, 6 s).
- The 10-client bursts were kept inside the ≤ 2 req/s average by 5 s gaps between bursts.
- The DuckDB table statistics come from `duckdb_tables().estimated_size` on a read-only APFS clone, not from the live file.
- Test-suite timings were taken on the same loaded Mac and are upper bounds.
