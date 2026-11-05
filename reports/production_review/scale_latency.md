# Scale & latency review — SuryaDhana stack (agent SCALE, 14 Oct 2026 ~21:4x IST)

Scope: read-only audit + GET-only measurements (≤3 sequential hits/route) of ui-api :8010, data-service :8001,
Next :3000, master-controller :8008. No restarts, no writes, no Telegram. Raw timings:
`endpoint_latency_scale.json` (this folder).

## Headline
The single-user Mac deployment is in good shape on warm paths (most hot routes answer in **7–50 ms**, all 16
measured routes 200 OK). The real scale/latency debt is concentrated in five places: **(1) the UI is serving a
dev build** (7.4 MB main bundle, no BUILD_ID), **(2) 352 MB parquet loads happen on the ui-api event loop**,
**(3) ~5–6 full 4.7 GB DuckDB copies every evening** across jobs/scripts, **(4) unbounded per-symbol dict caches**
(the past 2 GB OOM's likely mechanism), **(5) one orphaned 2.9 GB snapshot temp file** leaking in /tmp.

## 1. Blocking work inside async handlers (event-loop rule audit)
223 async defs in ui-api, 8 in data-service. AST scan (blocking call inside `async def`, not thread-offloaded):

| Sev | Site | Problem | Fix |
|---|---|---|---|
| **P1** | `services/ui-api/routers/pipeline.py:422,747,890` | `pd.read_parquet(FEATURES_PARQUET)` inside `async` routes — **352 MB** file decoded on the event loop: multi-second freeze of *every* request + ~1–2 GB RSS spike (matches the historical ui-api OOM at 2 GB) | `await asyncio.to_thread(pd.read_parquet, …)`, cache the frame once (bounded, see §4), load only needed columns (`columns=[…]`) |
| P2 | `services/ui-api/routers/stocks.py:635` | DuckDB `conn.execute` in `async screener()` — snapshot queries can take 100s of ms on big scans | offload with `asyncio.to_thread` (pattern already used elsewhere in the file) |
| P2 | `services/ui-api/routers/dashboard.py:579,608` | DuckDB executes in `async get_universe_status()` / `data_check()` | same offload |
| P3 | `services/ui-api/routers/markets.py:566` | `read_text()` of `india_data_calendar.json` in `async eco_calendar()` | tiny file; cache at import or ignore |
| OK | `gold_preopen.py:215,361`, `positions.py:226`, `lw_scanner.py:38` | sync `httpx`/`requests` calls live in **sync** `def` routes/helpers → FastAPI threadpool handles them | no change needed |

The event-loop rule from the 8-Oct incident is otherwise respected: heavy Yahoo/NSE fan-outs use async httpx +
`asyncio.gather` (e.g. `news_scanner.py:574`).

## 2. The 4.7 GB snapshot-copy economy
`data/market.duckdb` = **4.67 GB** (+11 MB WAL). Everything that cannot share data-service's RW connection copies it.

**Call-sites (16):** ui-api `snapshot.py` ReadSnapshot (the only *managed* one: change-detection + stale-while-
revalidate + pointer swap — well designed) · `alpha_lab/backtest/data_access.py` (shadow job 19:50 nightly +
any `run_today`) · `scripts/news_scan_performance.py` (19:45 **nightly**) · 13 research scripts (ml_label,
evidence_probability, results_drift, phase_b, held_overnight, fii, value_area, poc, idea_lab, qa ×2, combinatorial,
nse_panel_qa_old) — on-demand only.

**Recurring daily budget (evening):** eod 18:30 mutates DB → ReadSnapshot rebuild (~4.7 GB) · desk 19:30
`fresh=True` sync rebuild if changed · news_track 19:45 copy · alpha_shadow 19:50 copy → **≈ 4–6 × 4.7 GB ≈
20–28 GB SSD writes/day**, ~40 s each. Disk headroom is fine today (123 GiB free), but this is pure waste and
SSD wear.

**Found leaking:** `/tmp/bt_snapshot.1791926709339415000.duckdb.tmp` — **2.9 GB orphan** from an interrupted copy
at 02:55 (ReadSnapshot `grace` cleanup removes superseded *versions*, not `.tmp` partials). Fix: on build start,
unlink stale `*.duckdb.tmp` older than 1 h (3 lines in `snapshot.py:_build`).

**Proposal (S effort, big win):** one shared read-only snapshot per evening. After eod (≈19:10), a controller job
builds ONE versioned copy (reuse `ReadSnapshot` with a fixed dir, e.g. `/tmp/shared_snapshot`); `news_scan_performance`,
`alpha_lab/data_access`, and research scripts take `SNAPSHOT_PATH` env pointing at it (fall back to private copy when
absent). Cuts evening copies from 4–6 to 1–2. Longer term: nightly parquet export of the hot tables
(`nse_bhavcopy`, `nse_fo_daily`) — scripts load parquet 5–10× faster than copying 4.7 GB.

## 3. In-process cache map (ui-api + data-service)
| Cache | Key/TTL | Bound? | Risk |
|---|---|---|---|
| `news_scanner._cache` (:292) | `q:{sym}` 60 s, `d:{sym}` 300 s (2-yr candles ~100 KB each), search 3600 s | **unbounded dict, expired entries never evicted** | **P1 memory**: browsing/scanning hundreds of symbols accumulates `d:` frames → 100s of MB; most plausible contributor to the historical 2 GB OOM together with §1 |
| `commodity._CACHE` (:79) | per-instrument, TTL | unbounded | low (few keys) |
| `gold_preopen._cache` (:84) | per-day | unbounded | low |
| `positions._probe_cache/_client_cache/_BOOK_CACHE` | single-slot | bounded | OK (15-min expired-token memo — good) |
| `pipeline._sample_cache` | single-slot DataFrame | bounded 1 | OK but holds a big frame; pairs with §1 fix |
| `markets._FOMC_CACHE/_REACTING_CACHE` | 24 h / 60 s | single-slot | OK |
| `stocks`/`positions` `lru_cache(maxsize=1)` | static refs | bounded | OK |
| data-service `nse_live._cache`, `preopen._cache` | per-path TTL 15–300 s | unbounded but small keyspace | OK |
| `option_chain lru_cache(4)` | bounded | OK |

**Fix (S):** one 10-line `TTLDict(max_items=512)` (evict expired + LRU overflow on set) swapped into
`news_scanner._cache_set` — removes the only real leak class.

## 4. Measured warm latency (p50 of 3, sequential; full table in JSON)
| Route | p50 | Note |
|---|---|---|
| indices-live / results-reacting / eco / alerts / desk/status / open-positions (memoised) | **1–8 ms** | excellent |
| surveillance / news quotes / monitor / events / profile / valuation | 13–43 ms | fine; `monitor` 79 KB, OK |
| `/api/market/events` | 29 ms, **239 KB** | biggest payload; add `?limit`/windowing before multi-user |
| `/api/data/live/quote/TCS` | **295 ms** | Breeze round trip (sync `def` route → threadpool, correct); acceptable; cache 1–2 s if WATCH polls it per-symbol |
| first `open-positions` after restart | 875 ms once | probe; then memoised 1 ms — by design |
| Next `/` TTFB | 2–3 ms | but see §5 — this is the dev server |

No warm route exceeded 500 ms p50. Cold paths (first snapshot build ~40 s) are correctly moved off request paths
(`warm_snapshot()` at startup, `analytics.py:73`).

## 5. Frontend bundle — the dev-build finding (P1)
`ui/.next` has **no BUILD_ID** → :3000 is running **`next dev`**, not the prod build (`UI_MODE=prod ./start-local.sh
restart frontend` exists for that). Consequences measured: `main-app.js` **7.4 MB**, `.next` 717 MB, React dev
warnings active, no minification — on a laptop reload that's ~7 MB parse per hard refresh and much slower tab
first-paints than prod.
Additionally `ui/app/page.tsx` **statically imports all 56 modules / 73 components with zero `dynamic()`** — every
tab (charts, options pricer, research reader…) ships in the first load even in prod. `xlsx` is already lazy
(`backtestExport.ts:102` dynamic import — good; 2.4 MB chunk stays out of first load).
**Fix:** (a) run the prod build for daily use; (b) convert per-tab components in `page.tsx` to
`next/dynamic(() => import(...), { ssr:false })` — 15 tabs → first load carries only the active tab; expected
first-load JS cut of 60–80 %.

## 6. Upstream fan-out / N+1
- `news_scanner.get_quotes`: concurrent `asyncio.gather` over ≤60 symbols, per-symbol 60 s cache — good.
- `markets` results-reacting: serial *batches* of 60 via get_quotes — acceptable (1–2 batches).
- Rate-limit exposure: all Yahoo calls share one IP; at 10 concurrent users on WATCH the per-symbol cache (60 s)
  dedupes most load, but a cold burst of ~200 symbols risks Yahoo 429s. For >1 user: move quote fan-out behind a
  single shared fetcher with request coalescing (one in-flight per symbol) — S effort, pattern already half-present.

## 7. Evening job pressure (19:30–21:05)
`desk_daily` 19:30 (fresh snapshot) → `news_track` 19:45 (own 4.7 GB copy) → `alpha_shadow` 19:50 (own copy) →
`results_capture` 20:45 → `wrap` 21:00. Three multi-GB copies + model runs inside 25 min on one SSD. With §2's
shared snapshot this collapses to one copy. Memory now: data-service **1,284 MB RSS** (DuckDB buffers — cap with
`PRAGMA memory_limit` if it climbs), controller 52 MB, ui-api 6 MB (lean until a pipeline route loads parquet — §1).

## 8. Priorities
**Today (single user, Mac):**
| P | Change | Effort | Win |
|---|---|---|---|
| 1 | Serve the prod Next build; per-tab `dynamic()` in `page.tsx` | S/M | tab switches + reloads feel Bloomberg-fast; −60–80 % first-load JS |
| 1 | `asyncio.to_thread` + bounded cache for the 3 parquet routes (`pipeline.py`) | S | removes multi-second stalls + the 1–2 GB RSS spikes (OOM class) |
| 1 | Bounded TTL cache in `news_scanner` | S | closes the unbounded-growth leak |
| 2 | Shared evening snapshot + `.tmp` orphan cleanup | S | −15–25 GB/day SSD writes; frees 2.9 GB now |
| 2 | Offload DuckDB in `stocks.screener`, `dashboard` async routes | S | keeps the loop clean under load |
| 3 | `events` payload windowing; 1–2 s cache on `live/quote/{t}` | S | smaller/burst-safe |

**If this served 100 traders (Bloomberg-grade), additionally:** websocket fan-out for quotes/tape (one upstream
subscription → N clients) instead of per-client polling; Redis (or similar) shared cache replacing all module-dict
caches; DuckDB replaced on the read path by nightly parquet + an OLAP store or read replicas; ui-api horizontal
behind a proxy with sticky-less stateless routes (the module caches currently make instances stateful); CDN for
static; auth/RBAC and per-user rate limits; SLOs with p95 dashboards (Prometheus endpoints already exist).

*Out-of-scope observation for other agents: `services/ui-api/routers/pipeline.py` routes look unused by the
current 15-tab UI — contract agent should confirm orphan status before anyone optimises them deeply.*
