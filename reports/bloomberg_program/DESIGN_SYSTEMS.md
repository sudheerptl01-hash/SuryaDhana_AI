# DESIGN — Systems (B1 · B2 · B3 · S1–S8) — Phase 2, 14 Oct 2026 ~22:40 IST

Binding inputs: PLAN.md, REQUIREMENTS.md (F/S numbering reused). PM's answers to the six open questions are
incorporated. Everything below was designed against the code as read tonight (file:line cited). Corrections to
Phase-1 inputs are marked **[CORRECTION]** — builders implement THIS doc.

---

## 0. Facts established by code reading (builders rely on these)

| Fact | Evidence |
|---|---|
| `ReadSnapshot` already does versioned copy + pointer + single-flight + stale-while-revalidate | `services/ui-api/snapshot.py` (class; pointer json; `_build_locked` writes `<name>.<ns>.duckdb` + `.tmp`) |
| Its only instance: `analytics._snapshot = ReadSnapshot(lambda: db.DB_PATH, dir=$ANALYTICS_SNAPSHOT_DIR or /tmp, name="bt_snapshot")` | `routers/analytics.py:69` |
| **[CORRECTION]** `pipeline.py` 747/890 are ALREADY off-loop (`features_explorer` → `run_in_executor` at :786; `train-config` `_prepare_data` → `run_in_executor` at :949). The real inline offender is the **:422 region inside `GET /data-quality` (`async def get_data_quality`, :378)** — raw `pd.read_parquet(FEATURES_PARQUET)` fallback on the loop | pipeline.py:378–440, 786, 949 |
| `_sample_cache` is single-slot with TTL + `asyncio.Lock` single-flight (bounded by design) | pipeline.py:588–592 |
| `stocks.screener` (:477) is `async def` with **zero awaits** and inline `get_conn()` DuckDB work | stocks.py:477–665 (grep: no `await` in body) |
| `dashboard.py` universe-status (:~575) and `data-check` (:597) run DuckDB inline in `async def` | dashboard.py:565–615 |
| Unbounded dict caches (multi-key): `news_scanner._cache` (:292, per symbol/chart key — the P1 leak), `commodity._CACHE` (:79), `gold_preopen._cache` (:84), `markets._FOMC_CACHE` (:443), data-service `_fo_eod_cache` (main.py:1251, per symbol+expiry) | grep census |
| Single-slot (size-1, inherently bounded) caches to REGISTER, not migrate: `markets._REACTING_CACHE`, `pipeline._sample_cache`, `positions._probe_cache/_client_cache/_BOOK_CACHE`, data-service `_typical_cache` (has a growing `asked:set` — cap it), `_pe_pct_cache`, `_surv_cache`, `_ivh_cache`, `_monitor_cache` | grep census |
| Watchlist lives **in the browser** (localStorage), server holds none | monitor.py:22 comment |
| Holdings on the server: `data/last_holdings.json` via positions router |established earlier in repo |
| Breeze WS surface: `ws_connect()`, `subscribe_feeds(stock_token=…| exchange_code+stock_code+product_type…, get_exchange_quotes, get_market_depth, get_order_notification)`, `unsubscribe_feeds`, `on_ticks` assignable; socketio handshake needs `wait_timeout≥20 s` patch (`scripts/breeze_data_catalog.py:54–68`); ticker→ISEC map helper `_resolve_isec_code` caches via `get_names` (`providers/icici_breeze_provider.py:299`); provider singleton `_live` built in data-service `lifespan` (main.py:103–128), accessor `get_live_provider()` (:389) | code |
| Controller spawn pattern passes env per job (`env={**os.environ, "PYTHONPATH": …}`) — master_controller.py:1231,1255,1274,1294; alerts via `await _alerts.info/critical` | code |
| Dead-route decorators located: dashboard.py:597 `/data-check`, execution.py:210 `/order/scheduled`, monitor.py:202 `/embed`, ml_workspace.py:630 `/runs`, positions.py:672 `/refresh-session`, stocks.py:229 `/reload-universe`; plus `ml/health` (grep `@router.get("/health")` in ml_workspace.py) and `data/db/screener` (grep `"/db/screener"` in data_proxy.py) | grep |
| Payload offenders: ui-api `markets.announcements` (:325) · `markets.fundamentals-screen` (:696) · `data_proxy /db/ohlcv-meta` (:253 → data-service main.py:2797) · markets events route (grep `"/events"` in markets.py) | code + contract_audit |

---

## 1. B2.1 — `services/ui-api/cache.py` (bounded TTL cache, F2.1/S1)

**New file.** Stdlib only.

```python
class TTLCache:
    def __init__(self, name: str, max_items: int, default_ttl: float, clock=time.monotonic): ...
    def get(self, key: str) -> Any | None            # expired → evict+miss; hit moves key to MRU
    def set(self, key: str, value: Any, ttl: float | None = None) -> None
    def stats(self) -> dict  # {"name","size","max_items","hits","misses","evictions","expired"}
REGISTRY: dict[str, TTLCache]                        # name → instance, for telemetry
def cache_stats() -> list[dict]                      # snapshot of all registered caches
```

- Implementation: `collections.OrderedDict` store `{key: (expires_at, value)}`; `move_to_end` on hit;
  `popitem(last=False)` while `len > max_items`; everything under one `threading.Lock` (used from threadpool
  routes — S2 does not apply to the lock itself, operations are O(1)).
- **Adoption map (keep key strings and TTLs EXACTLY as today):**
  | Site | Replace | Instance |
  |---|---|---|
  | `news_scanner._cache` + `_cache_get/_cache_set` (:292–307) | functions become thin wrappers over instance | `TTLCache("news_scanner", max_items=600, default_ttl=120)` (keys: `q:`/`d:`/search per symbol; 600 ≈ 3× universe slice actually touched) |
  | `commodity._CACHE` (:79) | same wrapper pattern | `TTLCache("commodity", 64, …)` |
  | `gold_preopen._cache` (:84) | same | `TTLCache("gold_preopen", 32, …)` |
  | `markets._FOMC_CACHE` (:443) | dict-style get/set swap | `TTLCache("markets_fomc", 16, ttl as today)` |
- data-service `_fo_eod_cache` (main.py:1251): same class vendored? **No** — data-service imports nothing from
  ui-api. Builder adds the same 60-line class as `services/data-service/ttl_cache.py` (header notes the twin; the
  duplicates report already proposes a future `shared/` home — out of scope tonight), bound `max_items=256`.
- `_typical_cache["asked"]` set (data-service main.py:712): cap with `if len(asked) > 4096: asked.clear()` (one
  line, documented in the register).
- **Telemetry:** `routers/telemetry.py` gains `GET /api/telemetry/caches` → `cache_stats()` (ui-api only).
- Tests (`services/ui-api/tests/test_ttl_cache.py`): expiry on read; LRU eviction order at overflow; `stats`
  counts; 8-thread × 10k ops hammer ends with `size ≤ max_items`; news_scanner existing tests stay green.

## 2. B2.2 — Event-loop purity fixes (F2.2/S2) — exact verdicts

| Route | File:line | Verdict |
|---|---|---|
| `GET /api/pipeline/data-quality` | pipeline.py:378 (:411–440 fallback) | wrap the two parquet fallback blocks in ONE `await asyncio.to_thread(_quality_from_parquet)`; inside, `pd.read_parquet(path, columns=["ticker"])` for the feature block and `columns=["ticker","label_direction"]` for labels — counts only are used |
| `GET /api/stocks/screener` | stocks.py:477 | change `async def screener` → `def screener` (zero awaits; FastAPI threads sync routes — repo's own established pattern) |
| `GET /api/dashboard/universe-status` | dashboard.py (route above :575) | `async def` → `def` (same rule; body is CSV stats + one DuckDB count) |
| `GET /api/dashboard/data-check` | dashboard.py:597 | **deleted** (dead route, F1.5) — no fix needed |
| pipeline :747/:890 | — | **[CORRECTION] no change** (already executor-offloaded); record in build report |

- Regression-test pattern (new `services/ui-api/tests/test_event_loop_purity.py`): FastAPI `TestClient` on the
  real app; monkeypatch the heavy callable (e.g. `pd.read_parquet`) with `time.sleep(0.5)`; fire the heavy route
  in a thread, then 20 sequential `GET /health` timed: p95 < 100 ms. Apply to data-quality + screener +
  universe-status.

## 3. B2.3 — Shared evening snapshot (F2.3/S3) + orphan cleanup

**Owner: master-controller job `shared_snapshot_build`, 19:20 IST Mon–Fri** (after eod 18:30 lands, before desk
19:30/news 19:45/shadow 19:50).

- New `scripts/shared_snapshot.py` (stdlib + duckdb):
  - `build(dest_dir="data/snapshots/evening") -> dict` — copies `data/market.duckdb` (+`.wal`) to
    `evening-<YYYYMMDD-HHMM>.duckdb` via copy→verify→rename-`.tmp` (reuse the torn-copy retry idea from
    `snapshot.py:_build_locked`: compare `source_signature` before/after copy, retry once); verify = duckdb
    read-only open + `SELECT COUNT(*) FROM nse_bhavcopy` > 0; writes pointer `data/.evening_snapshot.json`
    `{path, created_at, db_mtime_ns, db_size}`; deletes older `evening-*.duckdb` keeping 1.
  - `current(max_age_h=24) -> str | None` — pointer file → path if exists and fresh and source mtime matches
    OR `allow_stale=True` for consumers that only need "tonight's" data.
- Controller job (pattern of news_track_record_daily): runs the script; on success exports nothing globally but
  **adds `SURYA_SNAPSHOT_PATH=<path>` to the `env=` dict of the 19:45 news job and 19:50 shadow job spawns**
  (env wins per PM answer); failure → `_alerts.warning`, consumers fall back.
- Consumer hooks (each ≤6 lines, same shape):
  - `alpha_lab/backtest/data_access.load()` — **the PLAN-amended single hook**: at top,
    `p = os.getenv("SURYA_SNAPSHOT_PATH") or _pointer_fallback()`; if `p` exists → `duckdb.connect(p, read_only=True)`,
    skip the private copy; else today's behaviour. `_pointer_fallback()` reads `data/.evening_snapshot.json`
    honouring `max_age_h=24` (pointer fallback per PM answer). Vendored-drift test unaffected (data_access is
    not vendored).
  - `scripts/news_scan_performance.py` (:85–95 copy block): same env+pointer check before `shutil.copy2`.
  - Research scripts: **frozen, untouched** (non-goal).
- `.tmp` orphan cleanup (scale finding): in `snapshot.py` `_build_locked`, before building: glob
  `self._dir/f"{self._name}.*.duckdb.tmp*"`, unlink files older than 1 h (3 lines) — and the same in
  `shared_snapshot.build`.
- Evening copy math (test-report input): ReadSnapshot rebuild (desk fresh=True after 18:30 ingest) 1 + shared
  build 1 = **2 copies**; news+shadow+02:15 backup consume the shared file (backup reads the snapshot, not the
  live DB). Steady-state ≈ 2 × 4.7 GB ✓ S3.
- Tests (`scripts/tests/test_shared_snapshot.py`): build+verify+pointer on a tiny fixture DB; rotation keeps 1;
  `current()` staleness (mtime mismatch → None unless allow_stale); data_access env hook (env set → connects
  read-only, no copy — assert via monkeypatched `shutil.copy2` raising); orphan cleanup removes old `.tmp` only.

## 4. B2.4 — Error contract (F2.4/S7)

**New `services/ui-api/errors.py`:**
```python
Code = Literal["not_found","upstream_down","degraded","unauthorized","invalid","state","internal"]
def fail(status: int, code: Code, message: str, hint: str | None = None) -> NoReturn:
    raise HTTPException(status, detail={"code": code, "message": message, **({"hint": hint} if hint else {})})
def degraded(payload: dict, code: Code, message: str, hint: str | None = None) -> dict:
    # 200 with usable-but-degraded data ONLY; adds error block ADDITIVELY, never removes legacy keys
    return {**payload, "ok": False, "error": {"code": code, "message": message, **({"hint": hint} if hint else {})}}
```
- App-level handler in `main.py`: `@app.exception_handler(HTTPException)` — if `detail` is a str, wrap to
  `{"code":"internal" if 500≤s else "state" if s==503 else "invalid" if s in (400,422) else "not_found" if s==404 else "internal", "message": detail}`;
  if already a dict with `code`, pass through. **Legacy-safe:** response keeps FastAPI's `{"detail": …}` shape —
  `detail` just becomes the structured object (additive; axios callers reading `detail` as message must tolerate
  object → the frontend normalizer handles it; the ONLY ui places reading `.detail` directly get updated by B4's
  normalizer adoption — see UIX design).
- Tonight's migrations (additive, keep every legacy key): soft-200 `{error: str}` sites in `pipeline.py` (35×),
  `positions.py` (11×), `dashboard.py` (9×) → `degraded({...legacy...}, code, message)`; `positions` connected:false
  family: add `error{}` beside it via `degraded`. Routers NOT in the three families: untouched tonight; new code
  must use the module (S7).
- Specific AC item: `stocks` unknown-ticker 404s (profile + ohlcv) → `fail(404, "not_found", f"Unknown ticker {t}", hint="Try the GO bar search — e.g. `TCS` or `GO TCS`")`.
- **Frontend normalizer `ui/lib/apiError.ts`:**
  `export function normalizeError(x: unknown): {code: string; message: string; hint?: string}` — handles: axios
  error with `response.data.detail` as string | object; `{error: string}` soft-200; `{error:{code,…}}`;
  `{connected:false, error?}`; network error → `upstream_down`; fallback `internal`. Unit-tested with the 9
  shapes (vitest? none configured — use a plain ts test via tsc + a tiny node script, or add the cases to an
  existing pattern — UIX designer finalizes the harness; contract here is the signature + cases).
- Census method for AC: `grep -rn '"error": \|{"error"' services/ui-api/routers | classify` before/after in
  build_b2.md.

## 5. B2.5 — Payload budgets (F2.5/S6)

| Route | Today | Change (defaults keep current UI data — UI callers updated to pass explicit params only where they truly render more) |
|---|---|---|
| `GET /api/markets/announcements` (markets.py:325) | 218 KB | add `limit:int=200` (rows, newest first) + truncate each `desc/detail` field to 400 chars with `…` (full text behind `?full=true`); UI announcement panes show ≤ ~50 rows today |
| markets events route | 239 KB | add `days:int=10` window + `limit=500`; EVTS tab passes its current wider window explicitly |
| `GET /api/markets/fundamentals-screen` (:696) | 529 KB | add `limit:int=250` + round floats to 2dp at serialization; FUND tab paginates/passes `limit=1000` if it renders all |
| `/api/data/db/ohlcv-meta` (data_proxy:253 → data-service main.py:2797) | 598 KB | data-service gains `fields=core` default returning {ticker, latest_date, rows, days_since_update, data_density_pct, sessions_behind}; `fields=full` = today; ui-api proxy forwards the param; the two ui callers (stocks table health chips) use core |
- AC measurement in Phase 4: `curl -s … | wc -c` ≤ 150 KB default each; ui_audit data-parity.

## 6. B3 — Live ticks (F3.1–F3.4) — the centerpiece

### data-service: new `services/data-service/live_ticks.py`
State machine (module singleton, registered per S4): `OFF → CONNECTING → LIVE → DEGRADED → DISCONNECTED`.

```python
class LiveTicks:
    def __init__(self, provider_getter=get_live_provider, clock=time.time): ...
    def set_symbols(self, symbols: list[str]) -> dict      # validated, ≤50, diff-subscribe; returns state
    def snapshot(self, symbols: list[str] | None = None) -> dict
    def shutdown(self) -> None
    state: str; last_tick_at: float | None; started_at; error: str | None
```
- **Connect path** (`_ensure_ws`, called lazily on first `set_symbols` with non-empty set, only if
  `provider.is_connected()` and `os.getenv("LIVE_TICKS","1") != "0"`):
  1. `shared.breeze_cache.install()` already ran at provider import; add **`patch_socketio_wait(20.0)` moved
     INTO `shared/breeze_cache.py`** (copy of breeze_data_catalog.py:54–68; catalog script keeps its local copy —
     note only, frozen-adjacent script untouched).
  2. `breeze = provider._breeze` (document this provider-internal access in the singleton register; provider and
     LiveTicks live in the same process by design).
  3. `breeze.on_ticks = self._on_tick`; `breeze.ws_connect()` in a **worker thread** (`threading.Thread`,
     daemon, name `live-ticks-ws`) because ws_connect blocks ~3–5 s; socketio then runs its own receive thread.
  4. Subscribe loop: per symbol `breeze.subscribe_feeds(exchange_code="NSE", stock_code=_isec(symbol),
     product_type="cash", get_exchange_quotes=True, get_market_depth=False)`; `_isec` reuses
     `provider._resolve_isec_code` (cached). Subscribe/unsubscribe diffs under a lock.
- **Prev-close join (PM answer: data-service, at subscribe time):** one store query per `set_symbols` diff:
  `SELECT symbol, close FROM nse_bhavcopy WHERE date=(SELECT max(date) FROM nse_bhavcopy) AND series='EQ' AND symbol IN (…)`
  via the existing store in a thread (`get_store()` pattern used by sync endpoints); stored as `prev_close` per
  symbol; chg_pct = ltp/prev_close−1 computed at snapshot time.
- **Tick handler `_on_tick(payload)`** (runs on socketio thread — must be O(µs), no locks beyond a dict write):
  normalize Breeze field names (`last`/`ltp`, `ltt`, `ttq`, `bRt`? — builder logs ONE raw tick at debug on first
  receipt and maps defensively with `.get` across the known aliases from the intraday memory: last, ltp, ltq,
  ltt, ttq, totalTrades, bPrice/sPrice if present) → `self._ticks[sym] = {"ltp": float, "ts": clock(),
  "ttq": int|None, "ltt": str|None, "bid": float|None, "ask": float|None}`. Symbol reverse-map ISEC→NSE kept from
  subscribe step.
- **Watchdog thread** (daemon, 15 s period): if state LIVE and market hours (09:15–15:30 IST Mon–Fri) and
  `now − last_tick_at > 120` → state=DEGRADED (chips show it; F-risk: the catalog memory's "L1 ticks silent").
  If ws error/disconnect callback fires → reconnect with backoff 2,4,8,…60 s + jitter, resubscribe current set;
  **3 failures within 5 min → state=DEGRADED, stop retrying 10 min** (F3.1 guard). If `provider.is_connected()`
  turns false (session died) → clean teardown → DISCONNECTED (no retry until a new `set_symbols` arrives after
  reconnection; positions router already refreshes the provider on login).
- **Endpoints (data-service main.py):**
  - `GET /live/ticks?symbols=A,B` → `{"state": state, "connected": state=="LIVE", "as_of": iso(now),
    "ticks": {SYM: {ltp, chg_pct, ts_age_s, ttq, bid, ask}}}` — pure dict read, sync `def`, O(n≤50).
  - `POST /live/ticks/symbols {"symbols":[…]}` → set-replace (validate `^[A-Z0-9&-]{1,20}$`, cap 50, unknown
    ISEC resolution failures reported per-symbol, not fatal) → returns state. Idempotent.
  - Lifespan shutdown hook calls `live_ticks.shutdown()`.
- **Kill switch:** `LIVE_TICKS=0` → `set_symbols` returns `{"state":"OFF"}` and never touches Breeze.

### ui-api: merge endpoint (F3.2)
`services/ui-api/routers/quotes.py` (new, mounted `/api/quotes`):
- `GET /api/quotes/ticks?symbols=` → calls data-service `/live/ticks` (httpx async, 3 s timeout, no caching) →
  for each requested symbol: tick fresh (`ts_age_s ≤ 5`) → `{price, chg_pct, source:"icici-ws", as_of}`; else
  fall through to the EXISTING Yahoo quote path (`news_scanner.get_quotes` internals refactored to an importable
  async helper `yahoo_quotes(symbols)` — no new REST to ICICI, F3.4) with `source:"yahoo"`. Upstream absent/
  degraded → `degraded(payload, "degraded", "live feed unavailable — Yahoo prices")` envelope.
- `POST /api/quotes/watch {"symbols": […]}` → union with server-side holdings symbols (read
  `data/last_holdings.json` like positions does) → forward to data-service `POST /live/ticks/symbols`. Frontend
  pushes its visible set (watchlist is browser-side — established fact); holdings are always included so the
  stock-window/book stays live even before any push.
- F3.4 census: build report greps `get_quotes(` sites before/after — identical.
- Tests: fake data-service via `respx`/monkeypatched httpx (3 states), fake Yahoo helper; warm handler path
  < 20 ms asserted with perf counter on the pure-merge branch; fake-Breeze unit suite for LiveTicks (subscribe
  called with ISEC codes, tick→snapshot, resubscribe diff, backoff sequence with fake clock, watchdog DEGRADED,
  teardown idempotent) in `services/data-service` tests (new dir? data-service has no tests dir — put
  `tests/unit/test_live_ticks.py` in repo root tests/, importing via path like other service tests do — follow
  `tests/unit/test_label_builder.py` import pattern).
- **Live spike (bounded, Phase 4):** market closed tonight → ws_connect returns but no ticks; spike = connect,
  subscribe 2 symbols, assert state LIVE and clean teardown within 60 s, zero ticks OK. Run once by PM/test
  agent while session valid; failure → feature stays behind kill switch, chips show DELAYED (honest fallback),
  program proceeds.

## 7. B1 — Ops designs

- **F1.3 backup `scripts/db_backup.py`:** source = `shared_snapshot.current(max_age_h=30, allow_stale=True)`
  (consistent, zero new live-DB copy); fallback: build a private consistent copy via the same copy-verify-retry
  helper (factored into `shared_snapshot.py`). Then: optional zstd (`try: import zstandard` → `.duckdb.zst`,
  else plain `.duckdb` — PM answer), write to `data/backups/duckdb/market-YYYYMMDD.duckdb[.zst]`, fsync, verify
  (open the pre-compression copy read-only: `nse_bhavcopy` count ≥ pointer's recorded count − 0; for zst keep a
  `*.meta.json {rows, sha256, src_mtime}`), rotate: keep 7 daily + 4 weekly (weekly = Sundays), delete older.
  Controller job `db_backup_daily` **02:15 IST daily**, timeout 1200 s, failure → `_alerts.critical` (the one
  permitted alert channel). Tests on a fixture DB: backup+verify+rotate+zstd-absent fallback.
- **F1.4 CI `.github/workflows/ci.yml`:** jobs `python` (3.13, `pip install -r requirements.txt`, then the five
  suites each with its documented PYTHONPATH; browser-login tests already self-skip without Chrome — verify the
  fixture `_need_chrome` exists (it does, `tests/integration/test_icici_login_browser.py`) — plus
  `python scripts/check_event_loop.py`) and `ui` (node 20, `npm ci`, `tsc --noEmit`). No service containers.
  A meta-test (`scripts/tests/test_ci_workflow.py`) asserts the yml lists all five suite paths + tsc + the scan.
- **F1.5 dead routes — delete list (exact):** dashboard.py:597 `data-check` · execution.py:210
  `order/scheduled` · monitor.py:202 `embed` · ml_workspace.py:630 `runs` · positions.py:672 `refresh-session`
  · stocks.py:229 `reload-universe` · ml_workspace `GET /health` (grep) · data_proxy `GET /db/screener` (grep).
  Each: remove decorator+handler+any dedicated tests; tombstone row in build_b1.md (route, evidence grep).
  **Keep** `/api/data/fetch/icici/daily` but mark `deprecated=True` in the decorator (F1.6).
- **F1.1 `.env.example`:** generate candidate key list via
  `grep -rhoE "os\.environ(\.get)?\(['\"][A-Z0-9_]+|getenv\(['\"][A-Z0-9_]+" services shared scripts alpha_lab | sort -u`
  + dotenv_values(.env) names; write grouped file (login-critical / desk / ui / telegram / optional) with
  placeholders; test `scripts/tests/test_env_example.py` re-runs the grep and asserts coverage ∅-diff and that no
  example value equals a live `.env` value (reads live only inside the test, never prints).
- **F1.2 RUNBOOK_RESTORE.md outline:** prerequisites (brew python + HOMEBREW_NO_AUTOREMOVE, jupyter_env path,
  node 20, playwright chromium install cmd) → clone → `.env` reconstruction table (key, where to get it) → DB
  restore (`zstd -d` or copy from `data/backups/duckdb/latest`, verify count cmd) → `./start-local.sh start` →
  verification checklist (health curls, ui_audit, /shadow, bot /status) → LaunchAgent note. Cross-link from
  CLAUDE.md + GETTING_STARTED (B5 owns those edits; B1 writes the runbook).

## 8. S-retrofits

- **S2 scanner `scripts/check_event_loop.py`:** AST walk over `services/ui-api/**/*.py` +
  `services/data-service/**/*.py`: inside `async def` bodies (excluding nested sync `def`), flag calls whose
  dotted name matches BLOCKLIST = {`pd.read_parquet`, `pd.read_csv`, `duckdb.connect`, `.execute` on names bound
  from `get_conn`/`duckdb` (approximation: any `*.execute(` when the enclosing file imports duckdb — minus
  allowlist), `shutil.copy*`, `time.sleep`, `requests.*`, `httpx.get|post` (sync module-level), `subprocess.run`,
  `open(` with literal >? no — skip `open`}; allowlist file `scripts/event_loop_allowlist.txt` (`path:line:reason`,
  starts with the audited-OK cases: pipeline executor wrappers etc. — builder populates from the scan's first
  run, each entry justified). Exit 1 on non-allowlisted hits; wired into CI; `scripts/tests` meta-test runs it.
- **S1 PRAGMA:** data-service `storage/duckdb_store.py` `__init__` after connect: `self._conn.execute("SET
  memory_limit='1.5GB'")` (+ `SET temp_directory='data/.duckdb_tmp'` so spills go to disk not RAM); verify its
  test suite (tests/unit store tests) green.
- **S4 singleton register:** `docs/ARCHITECTURE_NOTES.md` section "Process-local state (replica divergence
  surface)" — B5 writes it FROM the census table in §0 + LiveTicks + ReadSnapshot + provider `_live` + bot
  offset file; every entry: name, file:line, bounded-by, replica consequence.
- **S6/S8:** Phase-4 agent re-measures `endpoint_latency.csv` routes + the four payload routes; regression rule
  verbatim from REQUIREMENTS.

## 9. Sequencing, interference, restarts

1. Build order: **B2.1 cache → B2.2 purity → B2.4 errors → B2.5 payloads** (one builder, same files) ∥ **B3**
   (new files + small main.py additions in data-service + new ui-api router — no file overlap with B2 except
   `main.py` of ui-api: B2's exception handler vs B3's router mount — B2 owns `services/ui-api/main.py`; B3
   hands its 2-line router mount to B2's builder via its build report... **simpler: B3 owns the mount lines; B2
   touches only the handler block; they edit different regions and B2 finishes `main.py` first — PM applies B3's
   mount if a conflict shows**) ∥ **B1** (scripts/, workflows/, controller job regs — controller is shared with
   B2.3's job: B1 owns ALL master_controller.py edits, B2 hands B1 the `shared_snapshot_build` job spec — single
   writer per file preserved) ∥ B4/B5 per UIX design.
   **File-ownership matrix (binding):** master_controller.py → B1 · ui-api/main.py → B2 · data-service/main.py
   → B3 · data-service/ttl_cache.py+duckdb_store.py → B2 · alpha_lab/backtest/data_access.py +
   news_scan_performance.py + shared_snapshot.py → B2 · shared/breeze_cache.py → B3 · errors/cache/quotes new
   files → their builders · .env.example/ci.yml/db_backup/RUNBOOK → B1 · check_event_loop.py → B2.
2. B2↔B3 share nothing else (confirmed).
3. **Restarts (PM only, once, after Phase-3 merge + suites green, ~06:15–07:30 IST):** data-service → ui-api →
   `UI_MODE=prod` frontend rebuild → master-controller (new jobs 02:15/19:20 register). Outside both freeze
   windows; before the 08:00 login job.

## 10. Risk table (top 8)

| # | Risk | Mitigation |
|---|---|---|
| 1 | Breeze WS unstable / silently tickless on this network (seen once) | watchdog→DEGRADED at 120 s; chips honest; kill switch `LIVE_TICKS=0`; Yahoo path untouched as permanent fallback |
| 2 | ws_connect blocks or throws at startup | lazy start in worker thread; 3-strikes→10-min cooloff; provider state checked first |
| 3 | Session dies intraday (token killed by re-login elsewhere) | `is_connected()` polled by watchdog; teardown→DISCONNECTED; resumes on next `set_symbols` after reconnect |
| 4 | socketio thread leaks on reload/shutdown | single named daemon thread; `shutdown()` in lifespan; idempotent teardown test |
| 5 | Shared-snapshot pointer stale → jobs read yesterday | mtime+age check in `current()`; consumers fall back to private copy silently; copy-count math in test report catches regressions |
| 6 | Backup corrupts/half-writes | copy-verify-retry + row-count verify + sha in meta; restore path documented and tested on fixture |
| 7 | Error-contract migration breaks a UI branch reading `detail` as string | handler keeps `{"detail": …}` envelope; normalizer tolerates both; ui_audit 37-page gate + targeted axios-caller grep in B4 |
| 8 | TTLCache behaviour drift vs old dicts (TTL semantics) | wrappers preserve exact key/TTL semantics; news_scanner suite + golden `_cache_get` tests |

**Unknowns needing live experiment (flagged):** exact Breeze tick field names (mitigated by defensive mapping +
first-tick debug log); ws behaviour outside market hours (spike plan §6); zstd availability in jupyter_env
(try-import designed in).
