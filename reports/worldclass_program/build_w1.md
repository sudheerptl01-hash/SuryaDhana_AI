# W1 — CHRT Chart Studio (build report, 15 Oct 2026)

Expert: frontend charting engineer. Feature: the terminal's Bloomberg GP-equivalent —
interactive candlestick chart studio with indicators, D/W/M resample and intraday-ready
tick-store wiring (W6 contract).

## What shipped (3 owned files + 2 support files, all new)

| File | What it is |
|---|---|
| `services/ui-api/routers/charts.py` | `GET /ohlcv?symbol=&tf=D\|W\|M&days=` — proxies data-service `/ohlcv/{ticker}` (never opens DuckDB), resamples W/M in pandas, every W/M bar labelled by the bucket's **last trading day**; 60 s in-module cache per (symbol, start) so D→W→M flips don't re-read DuckDB. `GET /intraday?symbol=&date=&interval=1m\|5m\|15m` — proxies W6's `/ticks/bars`; on 404/unreachable returns **degraded-200** `{bars: [], note: "tick store not live", ok: false, error_info{…}}` per `errors.py`. All routes sync `def` (threadpool — event-loop purity), one error contract everywhere (`fail`/`degraded`, `upstream_detail`). |
| `ui/lib/chartData.ts` | Typed fetchers for both endpoints + pure indicator math: `ema` (SMA-seeded), `bollinger` (population σ, charting convention), `rsi` (Wilder), `sma`, `istChartTime` (IST wall-clock on the chart's UTC axis — same convention as IndexIntraday). All index-aligned, null during warm-up. |
| `ui/components/ChartStudio.tsx` | The CHRT page: candles + volume histogram, EMA 20/50/200 + BB(20,2) overlays, RSI(14) sub-pane time-synced to the main pane, crosshair OHLC+V readout with % change ("vs prev day/week/month", intraday "vs open"), symbol search box fed by `/api/stocks/symbols` (same directory as the GO bar), range select (AUTO/6M…MAX), VWAP price line + 60 s auto-refresh on intraday, and an honest amber notice while the tick store is not live. Terminal kit throughout (`T.*`, PageHeader/Panel/Chip/Notice, tabular-nums, JetBrains Mono). `lightweight-charts` is **dynamic-imported** inside the component (type-only import at top), so the canvas lib stays out of the tab's initial chunk. |
| `services/ui-api/tests/test_charts.py` | 15 tests (below). |
| `ui/package.json` | `lightweight-charts` pinned **exact `4.2.3`** (was `^4.2.3`; node_modules already held 4.2.3 — lockfile synced via `npm install lightweight-charts@4.2.3 --save-exact`). |

## Provenance honesty
- EOD: panel subtitle `DUCKDB EOD · AS OF <last bar date>` + readout label `SOURCE: DUCKDB EOD · YAHOO HISTORY`.
- Intraday: source passed through from the tick store (`icici-ws`), session date + VWAP shown; while W6 isn't live the page says `INTRADAY UNAVAILABLE — tick store not live` and shows **no fake bars**.
- W/M bars never carry a synthetic Sunday/month-end date — label = last traded session of the bucket.

## PATCH BLOCKS (PM applies — I did not touch shared files)

### (a) `ui/app/page.tsx` — 5 edits

**1. Lazy import** — after the `SeasonalityPage` line:
```
OLD:
const SeasonalityPage = lazyTab(() => import('@/components/Seasonality').then(m => m.SeasonalityPage))
NEW:
const SeasonalityPage = lazyTab(() => import('@/components/Seasonality').then(m => m.SeasonalityPage))
const ChartStudio = lazyTab(() => import('@/components/ChartStudio').then(m => m.ChartStudio))
```

**2. `Tab` union** — add `'charts'` after `'watch'`:
```
OLD:
type Tab = 'brief' | 'watch' | 'compare' | 'screen' | 'alerts' | 'eco' | 'seag' | 'memb' | 'options' | 'insiders' | 'deals' | 'preopen' | 'ipo' | 'movers' | 'wrap' | 'filings' | 'margin' | 'holders' | 'world' | 'desk' | 'markets' | 'events' | 'overview' | 'stocks' | 'backtest' | 'positions' | 'broker' | 'pipeline' | 'scanner' | 'discovery' | 'commodity' | 'glassbox' | 'mlengine' | 'explorer' | 'warehouse' | 'research' | 'system'
NEW:
type Tab = 'brief' | 'watch' | 'charts' | 'compare' | 'screen' | 'alerts' | 'eco' | 'seag' | 'memb' | 'options' | 'insiders' | 'deals' | 'preopen' | 'ipo' | 'movers' | 'wrap' | 'filings' | 'margin' | 'holders' | 'world' | 'desk' | 'markets' | 'events' | 'overview' | 'stocks' | 'backtest' | 'positions' | 'broker' | 'pipeline' | 'scanner' | 'discovery' | 'commodity' | 'glassbox' | 'mlengine' | 'explorer' | 'warehouse' | 'research' | 'system'
```

**3. `TAB_IDS`** — same insertion:
```
OLD:
const TAB_IDS: Tab[] = ['brief', 'watch', 'compare', 'screen', 'alerts', 'eco', 'seag', 'memb', 'options', 'insiders', 'deals', 'preopen', 'ipo', 'movers', 'wrap', 'filings', 'margin', 'holders', 'world', 'desk', 'markets', 'events', 'overview', 'stocks', 'backtest', 'positions', 'broker', 'pipeline', 'scanner',
NEW:
const TAB_IDS: Tab[] = ['brief', 'watch', 'charts', 'compare', 'screen', 'alerts', 'eco', 'seag', 'memb', 'options', 'insiders', 'deals', 'preopen', 'ipo', 'movers', 'wrap', 'filings', 'margin', 'holders', 'world', 'desk', 'markets', 'events', 'overview', 'stocks', 'backtest', 'positions', 'broker', 'pipeline', 'scanner',
```

**4. `COMMAND_PAGES` entry** — after the `watch` row:
```
OLD:
  { id: 'watch',     code: 'WTCH',  label: 'Watch monitor',         hint: 'watchlist, pins, holdings: live quotes' },
NEW:
  { id: 'watch',     code: 'WTCH',  label: 'Watch monitor',         hint: 'watchlist, pins, holdings: live quotes' },
  { id: 'charts',    code: 'CHRT',  label: 'Chart studio',          hint: 'candles, indicators, intraday VWAP' },
```

**5. Render branch** — after the `compare` branch:
```
OLD:
            {view === 'compare' && <Compare />}
NEW:
            {view === 'compare' && <Compare />}
            {view === 'charts' && <ChartStudio />}
```

### (b) `services/ui-api/main.py` — 2 edits

```
OLD:
from routers import alerts as price_alerts
NEW:
from routers import alerts as price_alerts
from routers import charts
```
```
OLD:
app.include_router(price_alerts.router, prefix="/api/alerts", tags=["alerts"])
NEW:
app.include_router(price_alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(charts.router, prefix="/api/charts", tags=["charts"])
```

## Test results

- `pytest services/ui-api/tests/test_charts.py -q` → **15 passed** in 0.35 s.
  Coverage: D passthrough sorted/shaped · paise rounding · **W bar aggregates the week's
  O/H/L/C/V exactly** (incl. a mid-week holiday + a part-week, labels = last trading day) ·
  M bar exactness · days clamp (10…7320) · invalid tf/interval/date/symbol → 400 `invalid`
  envelope · unknown symbol → 404 `not_found` · data-service down → 502 `upstream_down` ·
  **intraday 404 → degraded-200** (`bars=[]`, `note="tick store not live"`, `ok=false`,
  `error_info.code="degraded"`) · unreachable → degraded-200 `upstream_down` · live bars
  pass through unchanged (vwap/source preserved) · empty live session noted, NOT an error ·
  routes are sync `def` (loop purity).
- Full ui-api suite: `pytest services/ui-api/tests -q` → **400 passed** (was 385; +15, 0 broken).
- `python -m compileall routers/charts.py tests/test_charts.py` → clean.
- `cd ui && npx tsc --noEmit` → **clean** (ChartStudio.tsx + chartData.ts compile unregistered).
- Indicator math spot-verified by execution (`npx tsx`): Wilder textbook series → first RSI
  **70.46** ✓; flat→50 / all-up→100 / all-down→0 ✓; EMA seed = SMA ✓; Bollinger pop-σ on
  [2,4,6,8,10] → 6 ± 5.657 ✓; IST epoch helper ✓.

## Live spot-check (real data-service :8001, router on a bare TestClient app)

```
D 200 rows: 62 as_of: 2026-10-14 last: {"t":"2026-10-14","o":1167.0,"h":1188.0,"l":1162.7,"c":1174.6,"v":10934134}
W 200 rows: 53 as_of: 2026-10-14 last: {"t":"2026-10-14","o":1180.3,"h":1188.0,"l":1152.2,"c":1174.6,"v":33260949}
M 200 rows: 61 as_of: 2026-10-14 last: {"t":"2026-10-14","o":1180.1,"h":1220.8,"l":1152.2,"c":1174.6,"v":120223136}
404: {"detail":"No OHLCV data for ZZZTOP","error":{"code":"not_found",…,"hint":"NSE ticker as in the EQS screener…"}}
intraday: 200 {"symbol":"RELIANCE","date":"2026-10-14","interval":"1m","bars":[],"vwap":null,"source":null,
               "note":"tick store not live","ok":false,"error_info":{"code":"degraded",…}}   ← real upstream 404 today
M&M W: 200 rows: 26 (ampersand symbol round-trips)
```
Raw upstream check: `curl ":8001/ohlcv/RELIANCE?start=2026-10-01"` → 9 rows, yahoo_v8 source.
(W6's `/ticks/bars` genuinely 404s right now — the degraded path above is the live behaviour, by design.)
No uvicorn was started and Breeze was never touched (session invalid until ~08:00 IST).

## Cut for time (deliberate)
- No drawing tools / fibs / comparison overlay (second symbol) — next sprint candidates.
- No MACD/ATR panes — EMA/BB/RSI/VOL per spec; `chartData.ts` structure makes adding one ~15 lines.
- Intraday date picker: endpoint takes `date=` (tested) but the UI always charts today's session.
- No JS unit-test runner exists in ui/ — indicator math verified by executed reference checks
  (documented above) + tsc; resample correctness carries the pytest weight per the brief.

## Risks / notes for PM
- `ui/package.json` + lockfile changed (exact-pin 4.2.3). `npm install` already run; no other deps touched.
- RSI pane is a second lightweight-chart time-synced to the main pane (v4 has no native panes);
  sync is loop-guarded both ways.
- When W6's `/ticks/bars` lands, CHRT needs **zero changes** — contract consumed as specified
  (incl. vwap/source passthrough, `t:"HH:MM"` IST → chart UTC-axis convention).
- Intraday polls every 60 s only while an intraday tf is selected; EOD fetches are cached 60 s
  server-side per (symbol, window) so tf flips cost one DuckDB read, not three.
- `/api/charts` route names avoid every existing prefix; router imports only `errors`,
  `routers._upstream`, httpx, pandas — no shared-file edits anywhere.
