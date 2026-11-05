# W7 — FLAWS: bulk cache, payload trims, LOW defects (15 Oct 2026, ~03:20 IST)

Scope: bloomberg_verdict.md **D3** (1.4 s / 2.9 s bulk-per-call routes), **D5/S6** (4 payloads
> 150 KB), **D7** (URL leak + false lw 404), **D8** (two 422 conventions). Files touched (all
mine per PLAN.md): `services/ui-api/bulk_cache.py` (NEW), `routers/alpha.py`, `routers/lw_scanner.py`,
`routers/markets.py`, `routers/stocks.py`, `errors.py`, `tests/test_bulk_cache.py` (NEW),
`tests/test_w7_fixes.py` (NEW). No shared file edited — main.py / api.ts / components are patch
blocks below (§6). No commits, no Telegram, no secrets, no restarts issued by me (but see §7 R1).

## 1. Fix 1 — bulk cache (D3)

`services/ui-api/bulk_cache.py`: one module-level fetch of `GET :8001/db/ohlcv-bulk`, parsed
once into the canonical frame (alpha's old `_payload_to_frame` format — lw's parse was a column
subset of it), cached in a `cache.TTLCache` named **`bulk_ohlcv`** (visible at
`/api/telemetry/caches`), **TTL 60 s, keyed `(days, equity_only)`, max 2 entries LRU**,
per-key-lock **single-flight** (concurrent same-key callers wait for the one fetch instead of
each pulling 70 MB). Thread-safe for both caller styles: lw's sync `def` routes call it in the
threadpool; alpha wraps it in `asyncio.to_thread` — nothing blocks the loop
(`check_event_loop.py`: 0 findings; `test_event_loop_purity.py` green). Returns a **shallow
copy** per call (callers may add columns / set_index / sort; in-place value writes are banned
and both callers already mask-select-copy first — documented in the module docstring, pinned by
`test_copy_on_return_isolates_callers`). Empty frames are returned but **not cached** (a
transient upstream hiccup must not poison 60 s). httpx errors propagate so each caller keeps its
exact old error contract (alpha: upstream status + text / 502 / 503-empty; lw: 503 "DB load
failed", now without the URL-bearing httpx repr).

**Memory — MEASURED, not assumed** (fresh process, jupyter_env python):

| step | RSS | note |
|---|---|---|
| baseline | 110 MB | |
| + key (400, all): payload 69.5 MB, 391,673 rows, 1,496 tickers | 463 MB | frame deep-mem **28 MB** |
| + key (530, eq): payload 83.9 MB, 475,074 rows | 812 MB | frame deep-mem **34 MB** |

The frames are light (**62 MB deep for both keys** — the "300–500 MB?" fear was wrong; 70–84 MB
is JSON wire overhead). RSS beyond that is the Python allocator's high-water from the transient
`r.json()` list-of-dicts — **the identical spike the old code paid on EVERY request**; the cache
cuts its frequency to once per key per 60 s, so pressure strictly drops. Cap kept at 2 LRU
anyway (the two live keys: alpha `400|all`, lw screener `530|eq`; lw's rare manual cycle-scan
uses `430|eq` and will LRU-churn one entry — one extra 1.4 s fetch per scan, accepted). Live
worker RSS after serving both keys + the measurement traffic: 1.02 GB (same magnitude as the
offline harness; no pre-change worker RSS exists to compare — the old worker was replaced by
the dev reloader, §7 R1).

**Latency — before measured on untouched :8010, after verified on the SAME live :8010** (§7 R1):

| route | before (warm, every hit) | after cold (1/60 s) | after warm | target |
|---|---|---|---|---|
| `GET /api/alpha/universe` | 1.43–1.50 s | 1.43 s | **55 ms** | <100 ms ✓ |
| `GET /api/lw/screener` | 2.90–3.13 s | 3.13 s | **1.44 s** | fetch share cut ✓ |
| 8 × concurrent warm universe | 6.62 s wall (~0.73 s each, serialized) | — | **0.49 s wall** | — |

Honest residual: lw's warm 1.44 s is the LW screener's own indicator compute (verified: the
in-process run logs "Computing indicators… 1.3 s"); the fetch+parse share (~1.7 s) is what the
cache removes. Universe warm also got a micro-fix: `_apply_eligibility`'s python-level
`groupby.apply(sort)` → stable date-sort + `groupby.last()` (98 → 58 ms on the 392k-row frame,
output proven `DataFrame.equals`-identical offline before adopting).

## 2. Fix 2 — payload trims (D5/S6): opt-in `fields=core`, defaults byte-identical

**Consumer census first** (every fetch of the 4 paths in `ui/` + `scripts/`):

| route | consumer | fields actually read | core-able? |
|---|---|---|---|
| fundamentals-screen | `FundamentalsScreen.tsx` (EQS) | 14 of 17 (not revenue/bank/consolidated) | yes — via api.ts |
| | `EventCalendar.tsx` (season panel) | symbol, industry, period_end, pat_yoy, revenue_yoy, pat_yoy_turn | yes — same fetcher |
| | `scripts/master_controller.py:800` | symbol only | stays on full default |
| mtf-monitor | `MarginMonitor.tsx` (MRGN, the only consumer) | all stock+market fields, rendered ≤2 dp | yes — via api.ts |
| events | `EventCalendar.tsx`, `Brief.tsx`, `useCorpEvents.ts` (9 components via it), `StockProfile.tsx` | all EXCEPT `sources[]`, `announced_at`, `first_seen`; `purpose` IS used (StockProfile:156, EventCalendar:176) | yes — via api.ts |
| | `telegram_bot.py:389/406/416`, `daily_wrap.py:201`, `master_controller.py:1169` | rows (full) | stay on full default |
| announcements | `CompanyFilings.tsx` (CF) | ALL 8 fields incl. text/pdf | **must stay full** |
| | `EventCalendar.tsx:100`, `Brief.tsx:126` — both POLL EVERY 2 MIN | symbol, time, category only | yes — new core fetcher |
| | `master_controller.py:821` (filing_alerts) | full items | stays on full default |

**Server (markets.py, all additive — `fields` absent ⇒ the old code path byte-for-byte):**
- `fundamentals-screen?fields=core` → same rows **columnar** `{columns, data}` (all 17 fields,
  values untouched — per-row key repetition was ~60 % of the body).
- `mtf-monitor?fields=core` → `stocks` columnar + floats to 2 dp (display precision; MRGN renders
  rounded); small `market` block untouched.
- `events?fields=core` → columnar, minus `sources`/`announced_at`/`first_seen` (read by no ui
  consumer), `purpose` nulled only where it duplicates `detail` (client restores `purpose ??= detail`,
  so consumers see identical values).
- `announcements?fields=core` → items = `{symbol, time, category}` only (overrides `full`).
- `fields` is `Query(None, pattern="^core$")` — a typo'd value fails loud (422), never a silent
  528 KB fallback.

**Measured on the live service (same upstream moment, `curl -w %{size_download}`):**

| route | default | core | cut | ≤150 KB budget |
|---|---|---|---|---|
| fundamentals-screen | 528,290 B | **241,722 B** | −54 % | still over — honest miss; next step is dropping the 3 EQS-unread fields, blocked on `FinLatest` type sharing |
| mtf-monitor | 378,219 B | **161,696 B** | −57 % | 8 % over |
| events | 244,778 B | **141,964 B** | −42 % | ✓ |
| announcements (full day 14 Oct) | 224,731 B | **37,063 B** | −84 % | ✓ — and this one is polled every 2 min by two panels |

Defaults verified unchanged: live default sizes byte-identical to the pre-change measurements
(528,290 / 378,219 / 244,77x / 224,731 B), and `test_w7_fixes.py` pins default shapes (text-trim,
rounding, `sources`, purpose-no-dedupe).

## 3. Fix 3 — LOW defects

- **D7a** `stocks.py /{ticker}/ohlcv`: upstream 404 no longer goes through `raise_for_status()`
  (which produced 502 `upstream_down` + the internal URL + MDN link). Live now:
  `GET :8010/api/stocks/ZZZ/ohlcv?days=5` → **404**
  `{"detail":"No OHLCV data for ZZZ","error":{"code":"not_found","message":…,"hint":"Try the GO bar search — e.g. \`TCS\` or \`GO TCS\`"}}`.
  Other upstream ≥400 → 502 with `upstream_detail()` (its message, never its URL); non-JSON guarded.
- **D7b** `lw_scanner.py /screener?days=-3`: was a false 404 "No OHLCV data in DuckDB". Now
  `fail(422, "invalid", "days must be >= 1 (got -3)")` — live verified with the full envelope.
  Also sanitized the screener's 503 path: an `httpx.HTTPStatusError` repr (embeds the URL) is now
  reported as "DB load failed: data-service returned <code>".
- **D8** one 422 envelope: `errors.py` gains `validation_message()` + async
  `validation_error_handler()` (detail = compact human string, `error{code:"invalid"}` sibling,
  raw items under `errors`, `jsonable_encoder`-guarded against non-JSON inputs). Registration is
  one main.py patch line (§6.1) — until applied, local validation 422s stay FastAPI-default
  (verified live with `fields=junk`); the handler itself is fully tested via a mirror app.

## 4. Tests

- **New**: `test_bulk_cache.py` (10) — one fetch per key per TTL, TTL refetch, 8-thread
  single-flight (1 fetch, <1 s), copy-on-return isolation, empty-not-cached, error propagation
  ×2-not-cached, LRU cap 2, alpha wiring (full-universe key, 503-empty, status passthrough, 502),
  lw wiring (+30 headroom, equity flag, 7-column subset, empty shape). `test_w7_fixes.py` (11) —
  D7a clean-404/no-URL + 502-no-URL, D7b 422, D8 envelope + message compaction, trim helpers,
  and route-level default-vs-core for events/announcements/fundamentals (fake `httpx.AsyncClient`,
  same pattern as test_quotes.py).
- **Full ui-api suite: 461 passed, 0 failed** (440 pre-existing tonight + 21 mine; the 350
  baseline in my brief predates other builders' tests landing).
- `scripts/check_event_loop.py`: **0 findings**; `test_event_loop_purity.py` + `test_purity_scanner.py` green.
- `python -m compileall services/ui-api`: clean. **tsc not run — I edited no ui/ file** (all
  frontend changes are patch blocks below).

## 5. PM verification commands (after integration restart; already true on the live dev server)

```bash
for i in 1 2 3; do curl -s -o /dev/null -w "%{time_total}s\n" :8010/api/alpha/universe; done   # hit2/3 < 0.1s
for i in 1 2; do curl -s -o /dev/null -w "%{time_total}s\n" :8010/api/lw/screener; done        # hit2 ≈ 1.4s
time (for i in $(seq 8); do curl -s -o /dev/null :8010/api/alpha/universe & done; wait)        # ≈ 0.5s wall
curl -s :8010/api/telemetry/caches | python3 -c "import json,sys;print([c for c in json.load(sys.stdin)['caches'] if c['name']=='bulk_ohlcv'])"
curl -s -o /dev/null -w "%{size_download}\n" ":8010/api/market/fundamentals-screen?fields=core" # ≈ 241,722
curl -s -o /dev/null -w "%{size_download}\n" ":8010/api/market/fundamentals-screen"             # unchanged 528,290
curl -s ":8010/api/lw/screener?days=-3"                 # 422 {"detail":"days must be >= 1 (got -3)","error":{"code":"invalid",…}}
curl -s ":8010/api/stocks/ZZZ/ohlcv?days=5"             # 404 not_found, no localhost:8001, no MDN
curl -s ":8010/api/stocks/RELIANCE/ohlcv?days=-10"      # AFTER main.py patch: 422 with error{} envelope
```

## 6. Patch blocks (PM applies — shared files)

### 6.1 services/ui-api/main.py — register the validation handler (D8)
Insert directly AFTER the `_error_contract_handler` function (after its final
`return JSONResponse(...)` line), before `app.add_middleware(CORSMiddleware, …)`:
```python
# W7 (bloomberg_verdict.md D8): local validation 422s were the one error family without the
# envelope (raw FastAPI arrays). Handler lives in errors.py; tested in tests/test_w7_fixes.py.
from fastapi.exceptions import RequestValidationError  # noqa: E402
from errors import validation_error_handler  # noqa: E402
app.add_exception_handler(RequestValidationError, validation_error_handler)
```

### 6.2 ui/lib/api.ts — core adoption (components unchanged except §6.3/6.4)
(a) Add once, near the top-level helpers:
```ts
// W7 S6: columnar core payloads ({columns, data}) → row objects, so components keep their shapes
export function fromColumnar<T>(columns: string[], data: unknown[][]): T[] {
  return data.map(row => {
    const o: Record<string, unknown> = {}
    columns.forEach((c, i) => { o[c] = row[i] })
    return o as T
  })
}
```
(b) In `interface CorpEvent`, make the three server-dropped fields optional —
`sources: string[]` → `sources?: string[]`; `announced_at: string | null` →
`announced_at?: string | null`; `first_seen: string | null` → `first_seen?: string | null`.
(c) Replace `getMarketEvents`:
```ts
export const getMarketEvents = (start?: string, end?: string) =>
  client.get<{ start: string; end: string; columns: string[]; data: unknown[][]; count: number; refreshing: boolean }>(
    '/api/market/events', { params: { start, end, fields: 'core' }, timeout: 30000 })
    .then(r => ({
      ...r,
      data: {
        start: r.data.start, end: r.data.end, count: r.data.count, refreshing: r.data.refreshing,
        // the core wire nulls `purpose` where it duplicated `detail` — restore it exactly
        rows: fromColumnar<CorpEvent>(r.data.columns, r.data.data).map(e => ({ ...e, purpose: e.purpose ?? e.detail ?? null })),
      },
    }))
```
(d) Replace `getFundamentalsScreen`:
```ts
export const getFundamentalsScreen = () =>
  client.get<{ columns: string[]; data: unknown[][]; count: number }>(
    '/api/market/fundamentals-screen', { params: { fields: 'core' }, timeout: 30000 })
    .then(r => ({ ...r, data: { rows: fromColumnar<ScreenRow>(r.data.columns, r.data.data), count: r.data.count } }))
```
(e) Replace `getMtfMonitor`:
```ts
export const getMtfMonitor = (lookback = 20, min_amount_cr = 0) =>
  client.get<{ as_of: string | null; base_date: string | null; lookback: number; market: MtfMarketRow[]; stocks: { columns: string[]; data: unknown[][] } }>(
    '/api/market/mtf-monitor', { params: { lookback, min_amount_cr, fields: 'core' } })
    .then(r => ({ ...r, data: { ...r.data, stocks: fromColumnar<MtfStock>(r.data.stocks.columns, r.data.stocks.data) } }))
```
(f) Add beside `getAnnouncements` (which stays UNCHANGED — CompanyFilings needs full items):
```ts
// W7 S6: the 2-min pollers (EVTS/BRIEF) read only these three fields — 224 KB → 37 KB per poll
export interface FilingCore { symbol: string; time: string | null; category: string }
export const getAnnouncementsCore = (day?: string) =>
  client.get<{ date: string; items: FilingCore[]; counts: Record<string, number>; market_open: boolean }>(
    '/api/market/announcements', { params: { ...(day ? { day } : {}), fields: 'core' }, timeout: 40000 })
```

### 6.3 ui/components/EventCalendar.tsx (2 one-line swaps)
- Line 13 import list: `getAnnouncements,` → `getAnnouncementsCore,`
- Line ~100: `const get = () => getAnnouncements().then(r => {` → `const get = () => getAnnouncementsCore().then(r => {`

### 6.4 ui/components/Brief.tsx (2 one-line swaps)
- Line 14 import list: `getAnnouncements, type Filing,` → `getAnnouncementsCore, type FilingCore,`
- Line 126: `const filings = useLoad<{ items: Filing[] }>(() => getAnnouncements())` →
  `const filings = useLoad<{ items: FilingCore[] }>(() => getAnnouncementsCore())`

Apply order: 6.2 before 6.3/6.4; run `npx tsc --noEmit` after. 6.1 is independent.

## 7. Risks / honesty

- **R1 — the dev server self-reloaded my edits.** ui-api on :8010 runs `uvicorn --reload`; its
  file-watcher hot-reloaded each save (I issued no restart, and it is 03:20 IST — outside both
  freeze windows, market closed, LIVE_TICKS OFF). Consequence: the §1/§2 "after" numbers are
  real production-process numbers, and the before numbers were captured beforehand. PM's
  integration restart will land on identical code.
- **R2 — 60 s staleness window** on alpha/lw results. EOD data (updates once per evening);
  during the EOD ingest a scan can be up to 60 s behind the freshest rows. Accepted; TTL is a
  one-line knob (`bulk_cache.TTL_SECONDS`).
- **R3 — read-only discipline is convention, not enforcement.** A future caller writing in-place
  into the returned (shallow-copied) frame would corrupt the cache for 60 s. Documented in the
  module docstring + pinned test; deep-copy-on-return remains the 1-line fallback (~30 ms/call).
- **R4 — fundamentals-screen core (242 KB) and mtf core (162 KB) still exceed the 150 KB budget.**
  −54 %/−57 % shipped; the next honest cut (drop EQS-unread `revenue/bank/consolidated`) needs
  `FinLatest`-type surgery in api.ts shared with `getFinancialsLatest` — deliberately not
  smuggled in tonight.
- **R5 — until 6.1 is applied**, local validation 422s remain FastAPI-default arrays (the lw
  `days=-3` fix does NOT depend on it — live-verified with the envelope already).
- **R6 — out of my scope, still slow**: `/api/pipeline/features-explorer` (1.04 s live, parquet
  path, pipeline.py is not my file) — D3's third route; left for its owner/ticket.
- Scripts consumers (telegram_bot, daily_wrap, master_controller, nse_free_data_catalog) all hit
  the default routes — byte-identical, untouched, unaffected.
