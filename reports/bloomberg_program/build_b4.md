# build_b4 — Frontend/design workstream (B4)

14 Oct 2026, overnight build. Scope: DESIGN_UIX.md with red-team amendments **A2, A6** and minors **13/14/16**
binding. Files touched: `ui/` only. Gates: `tsc --noEmit` after every item (all green), prod `next build` green,
normalizer harness 14/14.

## Must-land items — all 8 landed

**1. Error normalizer (F2.4/A2)** — `ui/lib/errors.ts`: `normalizeError()`/`apiError()`, order
**error{code,message,hint} → detail (string | FastAPI validation array) → legacy** (`{error:"str"}` → degraded,
`{connected:false}` → state), never returns an object child. Code enum `{not_found, upstream_down, degraded,
unauthorized, invalid, state, internal}`; unknown codes tolerated (message kept, code → null). Adopted at **61
call-sites in 39 files** (every `response?.data?.detail` render path in ui/, incl. the review's crash list:
CommodityTab, LWScanner ×3, OptionChain ×3 — slice(0,80) behaviour preserved — InsiderMonitor, IndexContribution,
CompanyFilings, GoldPreOpen, IndexMembers, OwnershipShifts, MarketMonitor, FundamentalsScreen, BasketRisk, …).
Zero `.detail` render sites remain. **Minor 13 harness**: `ui/lib/__tests__/errors.check.ts` — 14 runtime cases,
type-checked by every `tsc` run, executed via `npx tsx` (passing). It also pins the A2 contract for B2's handler:
`detail` stays a string, `error{}` is a sibling.

**2. tabular-nums (F4.2)** — kit-level: DataTable `<table>` (now covers th/td/footers), `Stat` value, `KV` value;
`.t-nums` utility in globals.css. Hand-adopted in the named non-kit surfaces: Brief `Line` value span (covers the
whole BRIEF numbers column), LiveMovers' own `<table>` + sector-drill grid. DESK watchlist/holdings, MKT movers/
sectors/members, MEMB are kit DataTables → covered by the kit edit. Census: 66 `tabular-nums` sites. MUST-NOTs
untouched (RSCH prose, display headers, GO input).

**3. ALERT rebuild (F4.3 + minor 14)** — `ChartActions` gains `alertLayout: 'inline' | 'row'`. The stock window
passes `alertLayout="row"`: the 🔔 chip toggles and the form opens on a **full-width row under the chips**, so the
modal's `nowrap` header row never overflows (fix is inside ChartActions; the modal diff is 2 lines). Form rebuilt
on kit `Input label=` (`ABOVE ₹`, `BELOW ₹`, **new `MOVE %`** — server already prices it) with example
placeholders, `role="group"`, aria-labels on fields and SET/CLEAR/✕, ✕ hit area 24×24. `ui/lib/alerts.ts`:
new `setLevels(sym, {above, below, move}, yahoo?)`; `setBoth` kept as a wrapper sending the exact old payload
(absent `move` = server keeps it), so WatchMonitor's flows are byte-identical. Kit `Chip`/`Input` accept
`aria-label` (backwards-compatible).

**4. NewsDock → status line (F4.1)** — both fixed pills deleted. `NewsDock` now renders one footer segment
(`[●] NEWS 14-10 · 12`) mounted in the page footer between the spacer and `/ GO`; states quiet (green dot,
muted) / unread (amber pulse + filled count + NEW) / open (active border). Shift+N and `NEWS <GO>` unchanged;
NewsTerminal z → `Z.overlay`. Nothing floats over page content any more.

**5. Live ticks + SourceChip (F3.3/F4.8)** — `ui/lib/liveTicks.ts`: `useLiveTicks(symbols)`, the **only** file
that knows the wire shape (`GET /api/quotes/ticks?symbols=`; per A1 the GET auto-ensures subscription, no POST).
2 s poll, visibility-paused, failure backoff 2→4→8→30 s, AbortController, `NEXT_PUBLIC_MOCK_TICKS=1` dev walk.
State: server's word, else error→degraded / connected→live / else delayed; fetch-fail → offline. Kit `SourceChip`
(LIVE·ICICI pulse / DELAYED·YAHOO / DEGRADED / OFFLINE, tooltip + hint). Consumers wired: **WATCH** (ticks overlay
the 60 s Yahoo rows — price/day/position recompute; Yahoo stays the base layer; chip in the Monitor panel header),
**DESK** (new live LAST col width 96 — the DESK-clip medium — plus Value/P&L recomputed from ticks; chip on
Holdings with "EOD marks" hint when delayed), **stock window** (tick beats the legacy WS price; chip next to the
live price). If B3's final route/fields differ, `liveTicks.ts` is the whole diff.

**6. Z scale (F4.4)** — `ui/lib/z.ts` (base 0 · raised 2 · header 30 · footer 40 · dropdown 60 · overlay 100 ·
modal 120 · commandbar 140 · toast 160). Migrated every literal: ErrorCatcher 99999→toast, CommandBar+Help
1000→commandbar, HoverCard portal 9999→commandbar (must sit above the modal), MarketCommandHeader 50→header &
menu 80→dropdown, AlertsBell 90→dropdown, NewsDock/NewsTerminal→overlay, StockDetailModal `z-50`→modal,
LivePortfolio toast `z-50`→toast, footer 40→footer, sticky th/CSV/chart badges→raised. **Census: 0 raw zIndex
literals remain** (the modal's internal sticky `z-10` is inside its own stacking context, left by design).

**7. Code-splitting + skeletons (F4.9/F4.7 core + minor 16)** — kit `Skeleton` (shimmer, reduced-motion safe)
and `TabSkeleton` (header bar + 4 ghost panels). `app/page.tsx`: **36 components converted to per-tab
`dynamic()`** with `{loading: <TabSkeleton/>, ssr:false}` — list derived from the real import block (minor 16),
incl. SeasonalityPage's module mapping; StockDetailModal lazy with `Loading`; 2 dead imports (KPICard,
QuantKPICard) removed. Eager: BRIEF + chrome (header, tape, GO bar, footer, NewsDock, ErrorCatcher, providers).
PipelineStudio keep-mounted pattern preserved. **System page**: mount probes explicitly
`Promise.allSettled`-concurrent; first paint shows PageHeader + TabSkeleton instead of a wall of '—'.
**Measured: page chunk 944 kB → 282 kB (−70 %); chunk files 10 → 47; shared first-load 103 kB (unchanged).**

**8. GO recall (F4.6)** — `suryadhana.cmd.history.v1`: 20 raw inputs, dedup move-to-front, seeded once from the
old recent-stocks key, recorded in the single `run()` path (raw input, or the picked code when input is empty).
**↑/↓ recall only when the input is empty, unchanged since recall, or matches nothing — list navigation is
untouched otherwise.** RECALL chips row when open+empty (mouse-down fills without stealing focus); footer hint
updated. All storage behind try/catch like the existing keys.

## A6 unification (must-land tail) + mediums
- **Amber**: 66 literals across 12 files (`#FFB200`, `#f59e0b`, `#f5b301`, `#fbbf24`) → `#ffb000` (= T.amber).
  Census after: 0 variants.
- **#FFF → T.bright** (4 sites incl. kit Btn danger fg; AA 4.6:1).
- Token hexes: 44 quoted literals in kit-importing files → `T.*` (value-identical). 415 non-token shades remain
  (charts, one-off tints) — that is the full-597 sweep, explicitly out of top-20 scope.
- **Mediums landed**: DESK LAST col (in item 5) · macro-tape slicing at 720/1024/1280 (drops from the right via
  CSS classes, no scrollbar) · `ML Engine` tab label → `ML` (was truncating) · 9px floor: 12 sub-9px font sizes
  raised to 9 · stock window <768px = full-height sheet, backdrop `rgba(5,7,10,.7)` always, body scroll-lock
  while open.

## Cut (listed per A6, census target relaxed pro-rata)
1. **Kit relocation** `components/terminal/index.tsx` → `ui/lib/terminal.ts` — skipped under its own
   "skip if <45 min" clause: pure path churn touching every component, no behaviour. 2-line job for a quiet day.
2. **F4.7 ten per-component data-skeletons** — TabSkeleton covers every lazy tab's load state and SYS got a
   data-level skeleton; the remaining per-panel adoptions are polish, not structure.
3. **Full 597-hex sweep** — top-20/token subset done (114 literals removed); the rest are deliberate shades.

## Cross-builder notes (A8)
- **B2 (error handler)**: `ui/lib/errors.ts` + harness pin the A2 wire contract — `detail` string + sibling
  `error{code,message,hint}`; codes from the enum above. Nothing for B2 to apply in ui/.
- **B3 (ticks)**: frontend expects `GET /api/quotes/ticks?symbols=CSV` → `{connected, state?, as_of?, ticks:
  {SYM: {price|ltp, chg_pct?, prev_close?, ttq?, as_of?, source?}}}`; soft-200 degraded via `error{}`. Any drift:
  patch `ui/lib/liveTicks.ts` only (parse() + URL, ~15 lines).
- No files outside `ui/` were touched; no service restarted; no commits.

## Verification
- `tsc --noEmit` clean after each of the 8 items and at final state.
- `next build` (isolated dist dir, since removed): compiles, 5/5 static pages, route table healthy.
- `npx tsx ui/lib/__tests__/errors.check.ts`: **14/14 pass**.
- Censuses: `.detail` render sites 0 · raw zIndex literals 0 · amber variants 0 · sub-9px fonts 0 ·
  tabular-nums 66 sites · page chunk 282 kB (was 944 kB) · chunks 47 (was 10).
- Not verified here (needs running stack / Phase 4): live-tick behaviour against B3's real endpoint (mock + offline
  paths exercised by design), the 37-page visual pass, ALERT acceptance screenshot (minor 14 says screenshot governs).
