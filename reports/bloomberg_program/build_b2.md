# Build report — B2 (Backend scale: caches, error contract, event-loop purity, payload budgets)

Builder: B2 · 2026-10-14 · branch `feature/backtest-lab-institutional` (no commits, per PLAN)
Directive basis: REQUIREMENTS §B2 (F2.1–F2.5, S1, S2) · DESIGN_SYSTEMS §B2/§S · design_review amendments **A2, A3, A8**, minors **9, 11**.

**Final battery: ui-api suite 328 → 349 passed, 0 failed · `compileall` ui-api + data-service clean · purity scan: 0 findings, 0 allowlisted.**

---

## 1. Shipped (file:line)

### Unit 1 — bounded TTL+LRU cache (F2.1/S1)
| What | Where |
|---|---|
| `TTLCache` (OrderedDict LRU, expiry on read+write, threading.Lock, injectable clock, stats, self-registering `REGISTRY`) | `services/ui-api/cache.py` (new, 72 lines) |
| news-scanner cache migrated (the P1 OOM leak: per-symbol 2-yr candle frames, never evicted) | `services/ui-api/routers/news_scanner.py:296` — `TTLCache("news_scanner", 600, ttl=120)` |
| commodity cache migrated | `services/ui-api/routers/commodity.py:81` — `TTLCache("commodity", 64, ttl=600)` |
| gold_preopen migrated, **read-time-TTL semantics preserved** (stores `(stored_at, value)`, `_cached(key, ttl)` re-checks age per call-site window: fred 6 h / news 300 s / mcx 600 s; 12 h eviction TTL) | `services/ui-api/routers/gold_preopen.py:88` |
| telemetry endpoint `GET /api/telemetry/caches` → hits/misses/evictions/expired per cache | `services/ui-api/routers/telemetry.py:49` |
| unit tests: fake-clock expiry, LRU bound, 8-thread × 10k hammer (len ≤ 64), registry stats | `services/ui-api/tests/test_ttl_cache.py` (4 tests) |

### Unit 2 — one error contract (F2.4/S7, amendment A2)
| What | Where |
|---|---|
| `errors.py`: `Code` enum (not_found·upstream_down·degraded·unauthorized·invalid·state·internal), `fail()`, `degraded()`, `error_block()`, `code_for_status()` | `services/ui-api/errors.py` (new, 56 lines) |
| app-level handler: every HTTPException (incl. legacy plain-string raises and framework 404s) → `{"detail": "<string>", "error": {code,message,hint?}}` — **detail stays a string** (A2: 20+ components render it as a React child) | `services/ui-api/main.py:94` `_error_contract_handler` (B2 is sole writer of this file per minor 17) |
| 404s with GO-bar hints | `services/ui-api/routers/stocks.py:367` (unknown ticker), `:455` (no OHLCV) |
| degraded-200 adoption (legacy keys preserved, incl. the legacy **string** `error`; adds `ok:false` + `error_info{}`) | `positions.py:385,466,483,521` (broker-down family, hint "Send /login on Telegram or use the Broker tab") · `pipeline.py:504` (internal), `:1066` (SHAP, hint "Train a model first (ModelLab)"), `:1217` (metrics) |
| contract unit tests (mirror app, no live deps; incl. a source-check that main.py keeps the handler) | `services/ui-api/tests/test_errors_contract.py` (6 tests) |

**⚠ B4 normalizer note (A2 cross-builder contract):** in degraded-200 payloads the legacy `error` key is a **string** and stays one; the structured block rides as a **sibling `error_info{}`**. Normalizer case order must be: `error_info` → `error`(object) → `error`(string) → `detail` → `connected:false` → network.

**Census correction (soft-200 family):** design claimed pipeline 35× / positions 11× / dashboard 9× `{error}` envelope sites. Ground truth: true return-envelope sites = **positions 4 + pipeline 3** (all migrated). Pipeline's other hits are `_jobs[job_id]["error"]` job-state records — a data schema polled by ModelLab, wrong to migrate. Dashboard's 6 lived inside the dead `/data-check` route (deleted below).

### Unit 3 — event-loop purity fixes (F2.2, amendment A3)
| What | Where |
|---|---|
| **A3 screener**: route stays `async def` (it awaits httpx); the legacy DuckDB block (145 lines, verified unreachable — the delegate always returns/raises) extracted to module-level sync `_screener_legacy_duckdb()` called via `await asyncio.to_thread(...)` | `services/ui-api/routers/stocks.py:476` (route), `:520–:521` (to_thread call), `:525` (extracted fn) |
| `universe-status` async→sync def (zero awaits; CSV + DuckDB count → FastAPI threadpool) | `services/ui-api/routers/dashboard.py:561` |
| `staleness` async→sync def — **found by my scanner, missed by the design census** (full-table DuckDB aggregate inline in async def) | `services/ui-api/routers/dashboard.py:489` |
| pipeline data-quality parquet fallbacks → `asyncio.to_thread` with column projection (`columns=["ticker"]`; labels via pyarrow schema probe + 2-column read) | `services/ui-api/routers/pipeline.py:433,461` (other pre-existing to_thread sites `:628,:645,:704` unchanged) |
| **Dead route deleted**: `GET /api/dashboard/data-check` (:597–:684, DuckDB-heavy diagnostic) | `dashboard.py` (route removed to EOF) |
| **Dead route deleted**: `POST /api/stocks/reload-universe` (:231–:235) | `stocks.py` (route removed) |
| purity runtime tests: TestClient on one shared loop; p95 of 20 `GET /health` < 100 ms while each heavy route runs; **plus a deliberately-blocking control route proving the harness detects blocking** | `services/ui-api/tests/test_event_loop_purity.py` (4 tests) |

**Grep proofs for deletions** (run before deleting; both empty):
```
grep -rn "data-check|reload-universe" ui/ scripts/ services/ alpha_lab/ docs/ shared/ tests/
  (excluding the defining router files and reports/)  →  NO CONSUMERS
grep -rn "data-check|data_check|reload-universe|reload_universe" services/ui-api/tests/  →  NONE
```

### Unit 4 — payload budgets (S2) — **with live measurements, two honest zeros**
Measured live on :8010 before editing: events 468 rows / 254 KB · announcements 516 items / 230 KB · fundamentals-screen 1,611 rows / 584 KB · ohlcv-meta 1,496 tickers / 655 KB.

| Route | Shipped | Measured effect today |
|---|---|---|
| `markets.py:63` `/events` | `limit=Query(500, le=5000)` applied after merge (calendar is date-ascending → cut drops farthest-future only), `truncated` flag | 468 < 500 → **UI data unchanged**; growth guard |
| `markets.py:335` `/announcements` | `limit=Query(1000, le=5000)` + `text` truncated at 400 chars unless `?full=true`; `counts` stays whole-day truth | **0.0 % byte cut today** (only 4 texts > 400, max 600) — guard, not a win |
| `markets.py:723` `/fundamentals-screen` | `limit=Query(2500, le=10000)` + floats rounded 2 dp | **0 % byte cut** — upstream already serves ≤ 2 dp. Guard against future precision bloat only |
| `pipeline.py:390` data-quality → ohlcv-meta | opts into `?fields=core` (needs 3 of 19 fields) | **67 % cut once B3 applies the patch below** (655 KB → 215 KB, measured); today's data-service ignores the param → identical behaviour, order-independent |

**Deviation from design defaults (binding AC wins):** design said `limit=200` (announcements), `limit=250` (fundamentals-screen), `days=10` (events). Live counts are 516 / 1,611 / 468 — those defaults would drop data the CF overlay, EQS client-side filter, and EVTS calendar render **today**, violating the "current UI data preserved" AC. Defaults set above live volumes; the knobs + caps still bound growth. The design's projected byte savings for announcements-truncate and 2 dp-rounding were **wrong** (≈ 0 today); the real S2 win on this family is ohlcv-meta `fields=core` (67 %).

### Unit 5 — purity scanner (S2 enforcement)
| What | Where |
|---|---|
| AST scanner: flags blocking calls **directly** inside `async def` bodies; skips nested `def`/`lambda` (to_thread workers pass by design); blocklist: pandas read_*, duckdb.connect, time.sleep, shutil.copy*/move, subprocess.*, requests.*, sync httpx verbs, os.system, `get_conn`, `X.execute` in duckdb/get_conn modules; `--paths` / `--write-allowlist` / exit 1 on new findings | `scripts/check_event_loop.py` (new) |
| allowlist — **empty baseline** (tree is clean; nothing to rot) | `scripts/event_loop_allowlist.txt` |
| meta-tests: current tree clean · planted 4-violation file caught exactly (and the nested to_thread worker NOT flagged) · allowlist suppression works | `services/ui-api/tests/test_purity_scanner.py` (3 tests) |

Scan output (final):
```
event-loop purity: 0 finding(s), 0 new, 0 allowlisted
OK
```
It caught one real bug during the build (`dashboard.get_staleness`, fixed above) — the harness is not vacuous.
CI wiring is B1's (with if-exists guard); local enforcement = `test_purity_scanner.py::test_current_tree_is_clean`.

### Minor 11 — DuckDB memory PRAGMA (my duckdb_store.py exception under A8)
`services/data-service/storage/duckdb_store.py:539` — one `_apply_pragmas()` helper (`:543`) applied after **whichever** of the three connect branches succeeds: `SET memory_limit` (env `DUCKDB_MEMORY_LIMIT`, default `1.5GB`) + `SET temp_directory=<db-dir>/.duckdb_tmp` (mkdir'd; anchors at the db's parent = `data/.duckdb_tmp` in prod — cwd-proof in Docker), best-effort-guarded. Smoke-verified on a scratch store: `current_setting('memory_limit')` → 488.2 MiB for `512MB` (decimal→binary display), temp dir set. Store unit tests pass (2/2).

---

## 2. Cache census — before / after

| Cache | Before | After |
|---|---|---|
| `news_scanner._cache` | unbounded module dict (P1 leak) | `TTLCache("news_scanner", 600, 120 s)` |
| `commodity._CACHE` | unbounded module dict | `TTLCache("commodity", 64, 600 s)` |
| `gold_preopen._cache` | unbounded module dict | `TTLCache("gold_preopen", 32, 12 h eviction, per-read windows kept)` |
| `markets._FOMC_CACHE` (:443) | design census called it unbounded — **correction: fixed two-key dict `{at, rows}`, inherently bounded** | unchanged; documented here for B5's ARCHITECTURE_NOTES |
| data-service `_fo_eod_cache` (main.py:1260) | design: "unbounded, migrate to twin TTLCache(256)" — **correction: single-slot keyed `{key, df}`; `.update(key=…, df=…)` replaces in place; bound = 1 DataFrame.** A 256-slot TTLCache would hold up to 256 F&O DataFrames — strictly worse | unchanged; **twin `ttl_cache.py` NOT created** (directive: "if census requires" — it does not) |
| data-service `_typical_cache.asked` (main.py:721) | design: "growing set → cap 4096" — **correction: `asked` is wholesale-replaced with `set(want)` on every refresh (`:761`), `map` likewise (`:760`); bound = one request's symbol set** | unchanged; cap would be dead code |

Observability: `GET /api/telemetry/caches` reports every registered cache's size/max/hits/misses/evictions/expired.

---

## 3. Patch block for B3 (data-service `main.py` — B3 is sole writer, minor 17)

Only one data-service main.py change survives the corrected census. Apply to the `/db/ohlcv-meta` route (currently `main.py:2849`):

```python
@app.get("/db/ohlcv-meta")
def get_ohlcv_meta(fields: str = "full", store: DuckDBStore = Depends(get_store)) -> dict:
    """
    Per-ticker OHLCV + metrics stats for the stocks list page.
    Returns a list keyed by ticker with total_rows, dates, price, metrics.
    `fields=core` trims each row to the 6 data-quality keys (payload budget S2;
    measured 655 KB -> 215 KB, -67%): ticker, latest_date, total_rows,
    days_since_update, data_density_pct, sessions_behind.
    Default stays `full` so existing consumers are unchanged (WarehouseHealth's
    grid via data_proxy — which forwards no query params — and stocks list need
    the full row).
    """
    rows = store.get_ohlcv_meta_all()
    if fields == "core":
        keep = ("ticker", "latest_date", "total_rows", "days_since_update",
                "data_density_pct", "sessions_behind")
        rows = [{k: r.get(k) for k in keep} for r in rows]
    return {"count": len(rows), "data": rows}
```

Order-independence: my `pipeline.py:390` already sends `?fields=core`; today's route ignores the unknown param (full payload, current behaviour), the patched route trims. **Deviation from design:** design wanted `fields=core` as the *default*; that would silently gut WarehouseHealth (via `data_proxy.py:255`, which forwards no params) and `stocks.py:151/:359` (price+metrics consumers). Default `full` breaks nobody in any patch-ordering. No `data_proxy.py` patch needed as a result.

---

## 4. Deviations from the design (all justified)

1. **Scanner filename**: directive said `scripts/async_purity_scan.py`; design §8 and B1's CI reference `scripts/check_event_loop.py`. Shipped the design name (cross-builder contract wins).
2. **Allowlist format**: `path::call::async_func` triples instead of the design's `path:line` — line numbers rot on every edit; the triple is stable. Moot today (baseline is empty).
3. **Payload-budget defaults** raised above live volumes (see Unit 4) — binding "UI data unchanged" AC beats the design's estimated limits; measured evidence inline.
4. **ohlcv-meta default `full`** (design said `core`) — see patch block.
5. **No data-service `ttl_cache.py` twin, no `_typical_cache` cap** — census corrections in §2; shipping them would add a regression and dead code respectively.
6. **degraded() uses `error_info{}`** not `error{}` — the legacy `error` key in those payloads is a string the UI renders; overwriting it with an object is the same React-child crash class A2 exists to prevent (B4 note in §1).
7. **PRAGMA temp dir** anchored at the db file's parent rather than literal `data/.duckdb_tmp` — identical in prod, correct under Docker cwds.
8. **Purity tests mount real routers on a bare app** instead of `main.app` — main's lifespan fires Breeze/network warms (`positions.warm_breeze_probe()` et al.); route code under test is byte-identical, and a control test proves the harness detects blocking.

## 5. Scope flags for the PM

- **F2.3 not covered by any builder tonight**: `shared_snapshot.py` + the `alpha_lab data_access`/`news_scan_performance` env hooks are assigned to B2 in the design matrix but were **excluded from my directive's file list and build order**. Minor 9 (snapshot WAL pair-naming `evening-<ts>.duckdb.wal`) rides with that work. Needs explicit routing or it falls through the cracks.
- `CLAUDE.md` was rewritten on disk by B5 mid-run (architecture tables, runbook pointers) — inherited, not reverted, not mine.
- Baseline test count moved 328 → 346 during the run from parallel-builder additions landing in shared trees; my own files add 17 tests (4 + 6 + 4 + 3). Final: **349 passed, 0 failed**.

## 6. NOT done (honest list)

- F2.3 snapshot/env-hook work — excluded from directive (flagged above), **not attempted**.
- CI inclusion of the purity scanner — B1's item by design (if-exists guard); I shipped the script + local test enforcement only.
- B4's normalizer changes for `error_info` — B4's file; contract note in §1.
- Data-service restart to activate the PRAGMA / live re-measurement of route payloads post-edit — restarts are PM-only tonight; everything verified via unit tests, scratch-store smoke, and offline simulation on live JSON.
- `days=10` narrowing on `/events` — deliberately dropped (would change EVTS data); `limit` cap covers the budget.
