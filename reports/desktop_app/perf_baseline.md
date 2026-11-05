# Desktop program · UI performance baseline and fixes (D4)

Saturday 24 Oct 2026, market closed. Harness: `scripts/ui_perf.py` (Playwright, Chromium + WebKit; WebKit is the
engine of the app's WKWebView). Patch blocks: `reports/desktop_app/patches/D4.md`. Raw samples (one CSV row per
sample) are next to this file:

| CSV | What was measured | When |
|---|---|---|
| `perf_baseline_3000.csv` | the live Next prod server on :3000 (read-only) | 11:1x IST |
| `perf_export_before.csv` | static export of the morning source (28 px strip, layout patches only), served PoC-style on :8093 | 11:4x IST |
| `perf_export_before_pm.csv` | **before**: static export of the current source + layout patches P1–P6 (no perf patches) | 15:49 IST |
| `perf_export_after.csv` | **after**: the same source + every patch block (P1–P9) | 16:07 IST |

Every run: 3 runs per engine, sequential, one browser at a time; each run is a fresh context (cold cache), one cold
load of `/`, then all 42 pages through the app's own navigation (`suryadhana:goto`, what `goToPage()` dispatches),
order alternating between runs. Non-GET `/api` calls are aborted (the live stack stays read-only; 3 were blocked:
`POST /api/alpha/scan`, `/api/mcx/ticket`, `/api/options/strategy/analyze`). The scratch server forwards `/api`, SSE
and the monitor WebSocket to the live ui-api on :8010, so API latencies are real. The before/after pair ran back to
back with an 8 s post-load idle window (`--post-load-wait 8`), so both start their tab sweep from a quiet page.

Definitions. **UI-ready**: `document.title` shows the tab's code, the lazy-tab skeleton is gone and the URL says the
tab (sampled per animation frame). **Settled**: UI-ready and the tab's own requests idle for 500 ms (chrome pollers
and streams excluded). "First visit" = every sample here: each run visits each page once in a fresh context.

## 1. Budgets (PLAN AC-13) and where we stand

| Budget | Before | After (P1–P9) | Status |
|---|---|---|---|
| First-load JS ≤ 300 kB gz | 269.9 kB | **257.1 kB** (P9) | PASS (both) |
| Tab switch p95 < 400 ms, page on screen (UI-ready) | 326 ms Chromium · 379 ms WebKit | **45 ms · 107 ms** | PASS (both; before it passed by only 74 / 21 ms) |
| Tab switch p95 < 400 ms, data settled | 1,981 ms · 3,121 ms | 1,804 ms · 1,852 ms | **FAIL**: API-bound tabs (§7), not the UI |
| Boot to interactive < 2.5 s (warm stack) | app ready 100 ms · 124 ms | 102 ms · 121 ms | PASS (browser harness; the app's own boot is D2's self-test) |
| Boot paint < 0.5 s | FCP 92 ms · 106 ms | 88 ms · 105 ms | PASS (browser harness) |
| One idle window < 500 MB RSS, < 3 % CPU | not measurable here | JS heap after a full 42-page sweep 10.8–12.1 MB (Chromium, after GC) | self-test (D2) |

The UI side meets every AC-13 budget it controls. "Settled" p95 stays above 400 ms because 20–23 pages wait on
slow API endpoints (WEI 8 s, BRF/CMDT gold pre-open up to 7 s, IPO 5 s cold, MCXG up to 4 s); §7 names each one.
That is server work (ui-api / data-service owners), not something a UI patch can honestly fix.

## 2. Cold load of `/`

Median of 3 runs.

| Build | Engine | TTFB ms | FCP ms | load ms | app ready ms | requests | JS fetched until idle, gz kB | fonts / off-origin |
|---|---|---|---|---|---|---|---|---|
| live :3000 (Next server) | Chromium | 6.8 | 340 | 630 | 800 | 67 | 380 | 5 / **5** |
| live :3000 (Next server) | WebKit | 6.0 | 495 | 483 | 500 | 66 | 380 | 4 / **4** |
| export, before | Chromium | 1.5 | 92 | 40 | 100 | 72 | 396 | 6 / 0 |
| export, before | WebKit | 1.0 | 106 | 49 | 124 | 73 | 396 | 5 / 0 |
| export, after | Chromium | 1.6 | 88 | 40 | 102 | 117 ¹ | 621 ¹ | 6 / 0 |
| export, after | WebKit | 2.0 | 105 | 51 | 121 | 116 ¹ | 383 ¹ | 5 / 0 |

- The static export paints 3.7× (Chromium) / 4.7× (WebKit) sooner than the :3000 server and is interactive in
  ~0.1 s. On :3000 every cold load still fetched Google Fonts (5 / 4 requests off the machine); the export fetches
  none (self-hosted fonts, D4 §C).
- ¹ After P8 the idle warm-up (§4) fetches the 42 lazy page chunks once, 3 s after mount. Depending on timing it
  lands inside the cold-load idle wait (then the cold columns include it: 117 requests, 621 kB) or inside the
  post-load window (then they do not: 383 kB). First-load JS is unchanged by P8; see §6 for the bundle.
- WebKit DCL: the harness now falls back to Navigation Timing L1 when WebKit reports 0 (fixed between the before and
  after runs, so the earlier CSVs show 0 for WebKit DCL and `perf_export_after.csv` shows the real value).

## 3. Tab switch, all 42 pages

| Build | Engine | samples | UI-ready p50 | UI-ready p95 | settled p50 | settled p95 | pages with settled p95 > 400 ms | not settled |
|---|---|---|---|---|---|---|---|---|
| live :3000 | Chromium | 126 | 311 | 326 | 424 | 2,944 | 31 / 42 | 1 |
| live :3000 | WebKit | 126 | 321 | 382 | 493 | 2,032 | 30 / 42 | 1 |
| export, before | Chromium | 126 | 311 | 326 | 416 | 1,981 | 30 / 42 | 0 |
| export, before | WebKit | 126 | 315 | 379 | 453 | 3,121 | 28 / 42 | 0 |
| **export, after** | Chromium | 126 | **21** | **45** | **125** | 1,804 | 23 / 42 | 0 |
| **export, after** | WebKit | 126 | **30** | **107** | **139** | 1,852 | 20 / 42 | 0 |

Per page (p50 of 3 runs, before → after): UI-ready improves on 39 / 42 pages in Chromium (median −290 ms, range
−306 … +109 ms) and 40 / 42 in WebKit (median −287 ms, range −310 … +11 ms). Settled improves by a median −294 ms
(Chromium) / −296 ms (WebKit); pages whose settled p50 is ≤ 400 ms go from 21 to 29 (Chromium) and 20 to 30
(WebKit). The one regression is EQS in Chromium (+109 ms, see §8). The pages that did not move are the eager ones
(BRF, OVERVIEW) and PIPELINE, which never paid the floor.

## 4. The ~300 ms floor on every lazy page (P7 + P8)

**Finding.** Before the fix, every lazy page had UI-ready between 304 and 330 ms, whatever its size: DESK, RSCH and
RSK, whose chunks arrive in 4–8 ms, were ready at 305–318 ms. Cause: the tab components are `next/dynamic` (a
`React.lazy` + Suspense boundary). The first render suspends, shows `TabSkeleton`, and React 19 then holds the
reveal until 300 ms after the fallback was shown (`FALLBACK_THROTTLE_MS`; in the bundled react-dom:
`(lanes & 62914560) === lanes && (exitStatus = globalMostRecentFallbackTime + 300 - now(), 10 < exitStatus)`).
The page's data fetches start in its effects, i.e. only after the reveal, so the throttle delays the data too: the
first API request of a page started at a median **309 ms** after the switch (211 samples).

**Fix.** P7: each lazy page remembers its resolved module; once resolved it renders the component directly (no
Suspense, no skeleton, no throttle). The choice is made once per mount (`useState` initializer), so a mounted page
never swaps component type (no remount, no state loss). P8: warm the 42 page modules one at a time in idle time,
starting 3 s after the terminal mounted (skipped with Save-Data; errors swallowed), so the first visit is instant too.
Same components, same props, same API calls; only *when* a module is resolved changes.

**After.** UI-ready p50 21 ms (Chromium) / 30 ms (WebKit); the first API request of a page now starts at a median
**12 ms** after the switch (212 samples), so data lands ~300 ms sooner on every lazy page.

**Cost of P8** (measured on the scratch build, Chromium with CDP, 3 runs each, 14 s window after app ready):

| | JS fetched in the window | JS heap after GC, Δ over the window | event-loop lag > 100 ms | long tasks |
|---|---|---|---|---|
| before (no warm-up) | 0 | +0.16 … +0.36 MB | 0 ms | 0 ms |
| after (warm-up) | 42 chunks · 757.8 kB raw · **238.8 kB gz** | +0.46 … +0.48 MB | 0 ms | 0 ms |

So the warm-up costs ~0.25 MB of JS heap and ~239 kB gz of localhost transfer once per window (hashed chunks are
immutable, so later windows read them from cache), and it never blocked the main thread for 100 ms.

## 5. Fonts never leave the machine (P10)

The waterfalls of the before run show that one page still reached Google: **ALFA** (`discovery`) fetched
`fonts.googleapis.com/css2?family=Chakra+Petch…` plus two `fonts.gstatic.com` woff2 files in every run, both engines,
because `AlphaDiscoveryDesk.tsx` has an inline `<style>` with `@import url('https://fonts.googleapis.com/…')`. The
after run (P1–P9) still shows it (`Off-origin hosts contacted during tab switches: discovery → fonts.googleapis.com,
fonts.gstatic.com`). Chakra Petch 500/600/700 is now self-hosted under the same family name, so P10 drops the
`@import`. Verified on the scratch build with P10 (WebKit and Chromium): opening ALFA and BRF makes **no off-origin
request**, and every loaded face (Chakra Petch 500/600/700, JetBrains Mono 400–700) comes from `/fonts` on the
same origin. `TradeExplorer.tsx` has the same kind of `@import` (IBM Plex Mono), but nothing imports that component.
The other external hosts in the UI source are links and the TradingView embed (`finance.yahoo.com`,
`*.tradingview.com`), which are user-initiated and out of D4's scope.

## 6. Bundle (P9)

Static analysis of the export (`ui_perf.py --bundle-dir`; first-load = the scripts index.html loads; Next's
`noModule` polyfills excluded, a module-capable engine never fetches them):

| Build | first-load JS gz | raw | first-load CSS gz | all JS gz (files) |
|---|---|---|---|---|
| current source, unpatched (`build_ui.sh --out`) | 269.9 kB | 887.9 kB | 15.3 kB | 892.0 kB (61) |
| + layout + perf (P1–P8) | 270.1 kB | 888.5 kB | 15.3 kB | 891.2 kB (61) |
| **+ bundle (P9)** | **257.1 kB** | **842.5 kB** | 15.3 kB | 894.1 kB (64) |

**Finding.** `CommandBar` (eager, part of the page chunk) imported three string constants from the `Compare`,
`OptionChain` (+ `OptionPricer`) and `DealsMonitor` page components, which pulled those three whole pages into
first-load JS. **Fix (P9a–e).** The constants move to an import-free `lib/pageKeys.ts`; the three components re-export
them (same values, same exports for their other importers). Result: page chunk 277.4 → 231.3 kB raw (80.5 → 67.4 kB
gz), first-load **−13.0 kB gz (−4.8 %), −46 kB raw** to parse at boot; the three pages become their own lazy chunks.

Largest chunks today (all lazy unless marked):

| Chunk | raw / gz kB | What | Loaded |
|---|---|---|---|
| `98f82933…` | 402.9 / 135.5 | SheetJS (`xlsx`) | on export only |
| `3349…` | 375.9 / 102.3 | recharts | with the pages that chart |
| `app/page-…` | 276.8 / 80.2 | the terminal shell + eager pages | **first load** |
| `9277-…` | 220.3 / 71.5 | lightweight-charts + axios | **first load** (BRF's index chart, stock window) |
| `framework-…` | 185.3 / 58.4 | React (pages-router copy) | not by the app router |
| `18-…`, `87c73c54-…` | 170.0 / 45.8, 169.0 / 53.1 | Next runtime, react-dom | **first load** |

lightweight-charts stays first-load on purpose: BRF (the landing page) draws an intraday chart. No other cheap,
pure-performance first-load win was found.

## 7. Top 10 slowest pages after the fixes, and why

Ranked by settled p95 (3 samples per page per engine, so p95 = the worst sample). "Dominant call" = the request that
took longest in that page's own waterfall (median over its samples).

| Page | Chromium settled p50 / p95 ms | WebKit p50 / p95 ms | Dominant call (median ms) | Why |
|---|---|---|---|---|
| WEI | 1,804 / 14,585 | 1,852 / 15,018 | `/api/news-scanner/quotes` (8,162 / 8,377) | upstream index-quote fetch; 2.6–8.4 s across runs (4.5 s in the before run). Server side not investigated |
| BRF | 4,291 / 7,362 | 797 / 5,310 | `/api/commodity/gold-preopen` (up to 7,333) | slow endpoint (0.8–7.3 s across runs), on BRF next to 30 other calls. Server side not investigated |
| CMDT | 1,998 / 4,708 | 1,682 / 7,050 | `/api/commodity/gold-preopen`, `/api/commodity/overview` (0.6–3.9 s) | same gold endpoint plus the commodity overview |
| IPO | 235 / 5,419 | 242 / 5,264 | `/api/market/ipo` (5–6 s first call, ~0.2 s after) | slow first call of a run, ~0.2 s afterwards (looks like a server-side cache warming) |
| MCXG | 919 / 992 | 774 / 8,094 | `/api/mcx/overlay`, `/api/mcx/quote` (0.6–4.3 s) | slow endpoint, highly variable. Server side not investigated |
| EQS | 423 / 1,513 | 1,378 / 2,382 | render (no API on the critical path); `/api/market/results-recent`, `/api/market/events` (~1.1 s) | **UI-bound**: StockTable renders all 1,496 rows at once: ~0.4 s (Chromium) / ~1 s (WebKit) of main thread (§8) |
| EVTS | 1,296 / 1,300 | 1,276 / 1,289 | `/api/market/fundamentals-screen` (1.0–1.3 s), `/api/market/results-implied-moves` (0.9–1.2 s) | two heavy screens, 10–12 calls |
| WTCH | 980 / 1,133 | 68 / 1,173 | `/api/market/results-recent` (~1.1 s) | same endpoint as EQS/DESK |
| DEXP | 924 / 1,061 | 1,012 / 1,056 | `/api/pipeline/features-explorer` (~0.9 s) | one slow endpoint |
| MOV · MKT | 603 / 1,230 · 335 / 987 | 676 / 1,294 (MKT) | `/api/market/index-intraday` (0.4 s) · `/api/market/monitor` (0.2 s) | 7 calls each |

What would move them (not D4 patches: they are ui-api / data-service changes, listed for the owners):
short-TTL server caches for `/api/news-scanner/quotes` (WEI), `/api/commodity/gold-preopen` (BRF, CMDT; its inputs
change at most per minute), `/api/mcx/overlay`; a warm-up of `/api/market/ipo` and `/api/market/results-recent` at
ui-api start (the same warmer that already copies the snapshot); and windowing in StockTable (EQS, §8).

## 8. Not patched, with reasons

- **EQS (StockTable)** renders the whole 1,496-stock universe synchronously: a long task of ~350–420 ms in Chromium
  and ~1 s of event-loop lag in WebKit, both before and after. Before P7 part of it was hidden inside the 300 ms
  throttle window, so P7 shows it: Chromium UI-ready p50 314 → 423 ms (+109 ms), WebKit 1,066 → 994 ms. The real
  fix is row windowing or progressive rendering in StockTable. That changes the component's rendering (DOM, scroll,
  find-in-page), so it is a follow-up for the UI owner, not a pure-performance patch block.
- **Server latency** (§7): out of scope for UI patches.
- **lightweight-charts in first-load JS**: needed by the landing page (§6).

## 9. Latent bug found while verifying (P11)

Verifying P5 (toasts below the title strip) showed the toast stack at **left: 0** and painted *under* the sticky
header. Cause: `tailwind.config.ts` scans only `app/` and `components/`, so 17 of the 44 utility classes used in
`context/ToastContext.tsx` are never generated (`z-[9999]`, `right-4`, `pointer-events-auto`,
`bg-{amber,rose,emerald,indigo}-950/90`, `border-*-600/60`, `opacity-0/100`, `translate-x-4`, `transition-opacity`,
`break-words`, `hover:opacity-100`). Every toast in the terminal today has a transparent background, sits at the
left edge and has no z-index. P11 adds `./context/**/*` to the content globs. A rule-by-rule diff of the built CSS
shows the change is additive: 18 new utility rules, +137 B gz, and the only other difference is one selector list
the minifier regrouped with identical declarations. After P5 + P11 the toast sits 16 px below the strip and 16 px
from the right edge, above the header, in both engines (screenshot checked).

## 10. Reproduce

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
# bundle only (no browser):
$P scripts/ui_perf.py --bundle-dir <export dir> --runs 0 --tabs none --label bundle
# live :3000 (read-only), both engines:
$P scripts/ui_perf.py --base http://127.0.0.1:3000 --browser both --runs 3 --label baseline_3000
# a static export behind a PoC proxy (forwards /api, SSE, WS to :8010):
$P scripts/ui_perf.py --base http://127.0.0.1:8093 --browser both --runs 3 --post-load-wait 8 --label export_after
# tables from the CSVs in this folder:
$P scripts/ui_perf.py --summarize reports/desktop_app/perf_export_before_pm.csv reports/desktop_app/perf_export_after.csv
```

Scratch builds were made with D1's staging (`ui/scripts/release.mjs stage`, then `next build` with
`NEXT_OUTPUT=export`, never in `ui/`), with the D4 patch blocks applied by the same script that writes `D4.md`.
