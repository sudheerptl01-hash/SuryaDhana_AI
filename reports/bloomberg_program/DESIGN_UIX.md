# DESIGN_UIX — Phase 2 UI/UX design for workstreams B4 + B5 (14 Oct 2026, ~22:40 IST)

Binding inputs: `PLAN.md`, `REQUIREMENTS.md` (F4.*, F5.*, F3.3 frontend side, S6–S8),
`reports/production_review/design_audit.md` (findings F-001…F-015, screenshots in
`~/.gstack/projects/SuryaDhana_AI/designs/design-audit-20261014/screenshots/`). PM decisions applied: freshness
chips in panel headers (row-level only in the stock window); BRIEF eager, all other tabs `dynamic()`; fixed error
enum + one shared frontend normalizer. Everything below is spec'd against the CURRENT code as read tonight
(file:line cited); builders change nothing outside their named files. No new deps, no new visual language.

## ⚑ Contract conflicts flagged (resolve before build — do not assume)
1. **Live-quotes shape.** My brief says `GET /api/quotes/live` rows `{ltp, chg_pct, ts, source}`;
   REQUIREMENTS **F3.2** (binding) says `GET /api/quotes/ticks?symbols=` → `{symbol: {price, chg_pct,
   source: "icici-ws"|"yahoo", as_of}}`. **This design follows F3.2.** Systems designer must confirm the final
   path+field names in DESIGN_SYSTEMS; the frontend hook below isolates the shape in ONE adapter
   (`ui/lib/liveTicks.ts`) so a rename costs one file.
2. **Error envelope.** I design the frontend normalizer to F2.4's enum
   (`not_found | upstream_down | degraded | unauthorized | invalid | state | internal`); if DESIGN_SYSTEMS
   alters codes, only `ui/lib/errors.ts` changes.

## 0. Kit state (as-is, for every builder's orientation)
- Tokens `T`: `ui/components/news/format.ts:3-22` (19 tokens; amber `#ffb000`; CSS twins `--t-*` in
  `app/globals.css:9-16+` — **two sources that must stay in sync**).
- Kit components: `ui/components/terminal/index.tsx` (628 lines): `Label, Dot, Chip, Btn, PageHeader, Panel,
  Grid, Stat, KV, Meter, Spark, Tabs, Empty, Loading, errorText, ErrorBox, Notice, DataTable, Input, Select,
  TickerLink, EventBadge, ResearchNote, AvoidFlag` + formatters (`fmtInr, fmtPct, fmtNum, fmtCr, fmtDay,
  ordinal, median, fiscalQuarter, tone…`).
- The one footer/status line already exists: `app/page.tsx:651-663` (fixed, h 22, `zIndex: 40`) — F-001 docks
  into it.
- z-index census (tonight): 1, 2, 3, 40 (footer), 50, 80, 90 (NewsDock ×3), 100 (NewsTerminal), 1000 ×2,
  9999, 99999 — no scale. §1.3 introduces one.

---

## 1. F4.1 — News-pill dock (F-001, HIGH)
**Current:** `ui/components/news/NewsDock.tsx` renders two `position: fixed; right:16; bottom:30/32; zIndex:90`
buttons (quiet pill lines 63-72; loud "NEW" card lines 73-92) — these float over DESK's Book-vs-NIFTY chart and
MARKETS' P/E panel (evidence `desk.png`, `markets.png`).

**Target:** the pill becomes a **footer segment**, never floating.
- `app/page.tsx` footer (651-663): insert a slot between `{/* spacer */}` (`<span style={{flex:1}}/>`) and the
  `/ GO` button: `<NewsDockSlot />`.
- `NewsDock.tsx` refactor (same file owns both modes):
  - Export `NewsDockSlot()` — inline-flex footer segment, height 22, NO `position:fixed`:
    `[●] NEWS 14-10 · 12` where ● is `Dot(color: isNew ? T.amber : T.green, pulse: isNew)`, count chip
    `background:T.amber,color:T.bg` only when `picks>0`; `isNew` additionally appends blinking `NEW` text
    (reuse existing `nd-pulse` keyframes). Font: `T.mono 9.5px letterSpacing 1` (matches footer).
  - Click + existing Shift+N + `suryadhana:open-news` all call the same `openTerminal()`; `NewsTerminal`
    overlay unchanged (`zIndex` moves to `Z.overlay`, §1.3).
  - The old fixed-position variants are DELETED (no page is allowed a floating pill; mobile included — the
    footer is already fixed and visible at 375px).
- States: `quiet` (muted label) · `unread` (amber dot pulse + NEW + amber count) · `open` (terminal overlay
  showing; segment renders `active` Chip style).
**Acceptance (Phase 4):** re-screenshot `desk.png`/`markets.png` framing — zero intersection of pill with any
`Panel` bounding box (browse JS: `getBoundingClientRect` overlap check = 0); Shift+N and NEWS GO still open the
terminal; footer height unchanged (22px, no layout shift on any of the 37 audit pages).

### 1.3 Z scale (one-time, enables F4.1 + F4.3)
Add to kit `ui/components/terminal/index.tsx`:
`export const Z = { base: 0, raised: 2, header: 30, footer: 40, dropdown: 60, overlay: 100, modal: 120,
commandbar: 140, toast: 160 } as const`
Migrations in this program only (full sweep is out of scope): NewsTerminal 100→`Z.overlay`; StockDetailModal
backdrop/card (currently Tailwind/implicit) → `Z.modal`; CommandBar (9999/99999) → `Z.commandbar`; toasts
1000 → `Z.toast`; footer stays 40 = `Z.footer`. Builder adds a one-line comment at each site: `// Z scale: see
terminal kit`.

---

## 2. F4.2 — `tabular-nums` kit-wide (F-002, HIGH)
**Where the one rule lands (3 exact edits):**
1. `DataTable` (kit :351-454): on the `<table>` style add `fontVariantNumeric: 'tabular-nums'` — covers every
   kit table (WATCH, DESK, EVTS, MEMB, SCREEN, …).
2. `Stat` (:191) value span + `KV` (:207) value cells + `Spark` axis labels if text: same property.
3. `app/globals.css`: `.t-nums { font-variant-numeric: tabular-nums; }` + apply `tabular-nums` inside the
   existing `td, th` rule of the terminal table class if present; ALSO add to `body` a safe default?
   **No** — body-wide would hit prose (see exclusions). Keep it per-primitive + utility class.
**Hand-adopt in the 5 worst non-kit tables** (audit list): DecisionDesk watchlist (`DecisionDesk.tsx`),
MarketMonitor breadth/contrib tables, Brief tape+movers rows, LiveMovers grid, IndexMembers table — add
`className="t-nums"` (or the inline property where no className plumbing exists).
**Must NOT get it (3):** (1) running prose in RSCH doc pane and wrap/brief narrative paragraphs; (2) the
`T.display` Chakra-Petch headers/logo (display face, letter-spaced); (3) GO command-bar input (user types
free text). Rationale: tabular figures in prose look typewritten; display face has no tabular variants.
**Acceptance:** browse JS census (re-run audit's computed-style scan) ≥95% of numeric cells report
`font-variant-numeric: tabular-nums` (baseline: 6 elements); before/after screenshot of WATCH while ticking
(with §4 flash) shows zero horizontal jitter.

---

## 3. F4.3 — ALERT mode fix + labelled inputs + move-% (F-004 HIGH, F-008 MED)
**Current mechanism of the z-fight (found tonight — it is an overflow fight, not z-index):** the inline
`AlertForm` (`ui/components/terminal/ChartActions.tsx:40-58`) expands INSIDE the modal-header action row that is
mounted with `style={{ marginRight: 6, flexWrap: 'nowrap' }}` (`StockDetailModal.tsx:229`); the expanded span
(~430px) overflows the `flex-shrink-0` header cell and renders across the price block/`+ WATCHLIST` chips
(evidence `alert-editor.png`).

**Target spec:**
1. `ChartActions` gains prop `alertLayout?: 'inline' | 'row'` (default `'inline'` keeps current behaviour for
   wide chart headers like Commodity).
2. `StockDetailModal.tsx:229` passes `alertLayout='row'`: when `alertOpen`, ChartActions **replaces its whole
   chip row** with the AlertForm (conditional render — PIN/WATCHLIST/TV/YAHOO chips unmount while editing; the
   audit's exact fix) so nothing can overlap; ESC and ✕ both close (add `onKeyDown` Escape on the form root).
3. **AlertForm rebuild** (same file, stays ≤ ~40 lines):
   - Visible labels, kit `Input` (:456 — it already supports `label`): `ABOVE ₹`, `BELOW ₹`, `MOVE %` as
     10px `Label` above each box; placeholders become examples (`2 450`, `2 100`, `3`), never the label.
   - `MOVE %` wires bot parity: extend `ui/lib/alerts.ts` `setBoth` → new
     `setLevels(sym, {above, below, move}, yahoo?)` posting the existing server `move` key (bot already
     supports it); keep `setBoth` as a 2-arg wrapper for other callers (grep shows WatchMonitor uses
     `setLevel/setBoth` — untouched).
   - Buttons: `SET` (Chip green), `CLEAR` (red, only when existing), `✕` (muted, min hit area 24×24 via
     `padding: '6px 8px'` — F-008 tiny-target fix). All three get `aria-label`.
   - Form root: `role="group" aria-label={'Price alert ' + inst.base}`.
**Acceptance:** `alert-editor.png` re-shot — no glyph overlap (pixel-diff region clean); in dev, SET with
move=3 lands `{move: 3}` on `GET /api/alerts` (live API check); keyboard: Tab order above→below→move→SET,
Escape closes; aria names present in the browse accessibility snapshot.

---

## 4. F3.3 frontend — freshness chips + `useLiveTicks` (Bloomberg gap F-015)
**New kit component `SourceChip`** (kit file, ~20 lines):
`<SourceChip state="live"|"delayed"|"degraded"|"offline" detail?: string />` →
- `live`: `Dot(T.green, pulse)` + `LIVE·ICICI` (green text) — tooltip "Breeze websocket, ticks as they arrive".
- `delayed`: amber `Dot` + `DELAYED·Yahoo 60s`.
- `degraded`: amber outline + `DEGRADED` + detail (from error envelope `hint`).
- `offline`: `Dot(T.red)` + `OFFLINE`.
Form: existing `Chip` with 9.5px mono, NO background fill (header furniture, not a button).
**Placement standard (PM decision):** right slot of `Panel`/`PageHeader` (`right={<SourceChip …/>}`) — WATCH
header, DESK "Watchlist risk"/book panel header, BRIEF's book panel; **row-level only inside the stock window**
(StockDetailModal price block gets a small inline SourceChip after the price).

**Hook `ui/lib/liveTicks.ts`** (new file, ~70 lines, the ONLY place that knows the endpoint shape):
```ts
useLiveTicks(symbols: string[]): { ticks: Record<sym,{price,chg_pct,as_of,source}>, state: ChipState }
```
- Polls `GET /api/quotes/ticks?symbols=…` (F3.2, LOCAL ui-api only) every **2 000 ms**; pauses on
  `document.hidden` (visibilitychange listener) and on empty `symbols`; exponential backoff 2s→4s→8s→30s cap on
  error, reset on success; aborts in-flight on unmount (`AbortController`).
- `state` derives: any `source==='icici-ws'` → `live`; envelope `error.code==='degraded'` → `degraded`; all
  yahoo → `delayed`; fetch failing → `offline`.
- Consumers: `WatchMonitor.tsx` (keeps its existing 60s `getNewsQuotes` flow — `REFRESH_MS` :27 — as the base
  data; live ticks OVERLAY price/chg where present), `DecisionDesk.tsx` book, `StockDetailModal` header.
  Integration pattern: `const live = useLiveTicks(connected ? syms : [])` — the `connected` flag comes from the
  ticks response itself (first call cheap), so no extra probe.
**Row flash-on-change:** kit utility `flashStyle(dir)` + CSS in globals:
`.t-flash-up { animation: tFlashUp .6s ease-out }` keyframe background `rgba(22,217,138,.18)`→transparent;
`.t-flash-dn` red twin `rgba(255,77,94,.18)`. Rule: flash the PRICE CELL only (not the row), max once per 2s
tick, no transform/size change (F4.2 tabular-nums prerequisite guarantees no width shift). Respect
`prefers-reduced-motion: reduce` → no animation (media query in globals).
**Acceptance:** F3.3's AC verbatim (≤2s re-render with ws mocked; chip flips live↔delayed on mid-session
fallback; `document.hidden` mock stops polling; 37-page audit green); plus: network tab shows ZERO calls while
hidden; chip present on WATCH/DESK/BRIEF-book headers in screenshots.

---

## 5. F4.4 — Token discipline (F-003/F-009/F-013 + the modal's stray amber)
1. **Relocation:** create `ui/lib/terminal.ts` = the single token+formatter source (move `T`, `CCY`, fmt*,
   `signColor`, `timeAgo`, `convictionColor`, `REGION_LABEL` from `components/news/format.ts`).
   `components/news/format.ts` becomes a 2-line re-export (`export * from '@/lib/terminal'`); kit
   `components/terminal/index.tsx:15` imports from the new path. NO call-site churn required (34 files import
   from `news/format` or `components/terminal` — both keep working). tsc gates.
2. **Amber unification — survivor `T.amber #ffb000`** (and its dim pair `T.amberDim`). Census tonight: 93×
   `#ffb000` (kit-consistent), plus strays `#FFB200` (AlphaDiscoveryDesk, TradeExplorer, EquityCockpitChart),
   `#f59e0b` (PipelineStudio, GlassBoxStudio, BacktestPanel — Tailwind amber-500), **`#f5b301`
   (`StockDetailModal.tsx:221` — found tonight, 4th variant)**. Replace all three stray hexes with `T.amber`
   (import where missing). Visual spot-diff pages: PIPELINE, DISCOVERY, BACKTEST, stock window.
3. **#FFF sweep (F-013):** `'#fff'|#ffffff` literals in `PipelineStudio.tsx`, `IndicatorPriceChart.tsx`,
   `ModelLab.tsx`, and kit `index.tsx:114` (`danger` Btn fg) → `T.bright` (danger fg may stay `#fff`
   intentionally on red — decide: use `T.bright`; contrast on `T.red` passes AA at 10px bold? 4.6:1 ✓).
4. **Top-20 hex offenders → tokens:** builder generates the mapping mechanically:
   `grep -rEoh "#[0-9a-fA-F]{3,8}" ui/components ui/app | sort | uniq -c | sort -rn | head -30`, maps every hex
   within ΔE≈0 of a token (`#05070a→T.bg, #0a0d13→T.panel, #1a2130→T.border, #2a3448→T.borderHi,
   #d6dbe4→T.text, #f2f5fa→T.bright, #6f7a8e→T.muted, #475063→T.dim, #16d98a→T.green, #ff4d5e→T.red,
   #39c6ff→T.cyan, #b58bff→T.violet, #8a94a6→T.muted(nearest — note in report)`) and replaces ONLY in the
   top-20 files by count. Any hex with no token within tolerance is LEFT and listed in the build report.
   Target (F4.4 AC): census 597 → ≤297 in components+app.
**Acceptance:** hex census delta ≥300; tsc green; QuantKPICard/BacktestPanel screenshots unchanged except
amber shade unification; `globals.css` `--t-*` values verified byte-identical to `T` (add a comment in both
files pointing at each other; a sync unit test is B4-optional).

---

## 6. F4.6 — GO recall / history
**Current:** `CommandBar.tsx` already stores recent TICKERS (`suryadhana.cmd.recent.v1`, 8, `loadRecent()`
:42-45) shown somewhere in the list; no ↑/↓ history of full commands.
**Spec (all inside `CommandBar.tsx`):**
- New key `suryadhana.cmd.history.v1`: array of the last **20 executed raw inputs** (exact string the user
  submitted: `TCS`, `TCS FA`, `MKT`, `COMP TCS INFY`…), most-recent first, deduped (move-to-front), writes
  wrapped in try/catch (repo convention, matches :145-155).
- Record in the single `run(item)`/submit path at the point the command executes.
- **↑/↓ at empty-or-prefix:** when the input is empty OR unchanged since last fill, ArrowUp cycles
  history[cursor++] into the input (ArrowDown back; past newest restores the draft). When the suggestion list
  is open with matches, ↑/↓ keep their EXISTING list-navigation meaning — history cycling engages only when
  `symbols` list has no matches or input empty (no behaviour break). ESC unchanged (closes bar).
- **Recent chips:** when focused+empty, render one row under the input: `RECENT:` + up to 8 history entries as
  `Chip`s (click = execute). Reuses the existing recent-tickers row if present — unify both into the new
  history store (migrate: seed history from old RECENT_KEY once, keep old key untouched otherwise).
- SSR guard: all storage access already client-side (`'use client'`), keep try/catch.
**Acceptance:** dev keyboard test — type `TCS`⏎, `MKT`⏎, reopen GO, ↑ shows `MKT`, ↑ `TCS`, ⏎ navigates;
chips row screenshot; no regression in list navigation (type `T`, ↑/↓ moves selection as before).

---

## 7. F4.9 + F4.7 + F4.8 — per-tab `dynamic()`, Skeleton, System page
### 7.1 dynamic() import map (`app/page.tsx`)
Eager (PM decision): `Brief` + chrome (`MarketCommandHeader`, `CommandBar`, `LiveMonitorBar`, footer,
`NewsDock` slot, `ErrorCatcher`, providers) + `StockDetailModal`? — **StockDetailModal lazy too** (openable
from BRIEF but 605 lines + Profile tree; loading state = kit `Loading` inside the modal shell).
Lazy with `next/dynamic` (each `{ loading: () => <TabSkeleton/>, ssr: false }` — all are client/data
components; `ssr:false` avoids hydration cost):
`WatchMonitor, Compare, FundamentalsScreen, AlertsCenter, EconomicCalendar, SeasonalityPage, IndexMembers,
OptionChain, InsiderMonitor, DealsMonitor, PreOpen, IpoMonitor, LiveMovers, DailyWrap, CompanyFilings,
MarginMonitor, OwnershipShifts, WorldMarkets, DecisionDesk, MarketMonitor, EventCalendar, ResearchLibrary,
SystemTelemetry, LWScanner, AlphaDiscoveryDesk, CommodityTab, GlassBoxStudio, MLEngineWorkspace,
DataExplorerTab, WarehouseHealth, BacktestPanel, LivePortfolio, PortfolioSummary, PipelineStudio(†),
StockTable/overview pair`.
(† `pipeline` renders in a keep-mounted `display:none` div (`page.tsx:643`) — dynamic still fine: it mounts on
first visit then stays.)
### 7.2 Kit `Skeleton` (F4.7)
Kit primitive: `Skeleton({ h = 12, w = '100%', style })` → block `background: linear-gradient(90deg, T.panel2,
T.panel3, T.panel2)` with `t-shimmer 1.4s infinite` keyframes (globals), `borderRadius: 2`;
`TabSkeleton()` = PageHeader bar skeleton + `Grid` of 4 `Panel`s each with 3 `Skeleton` lines (mirrors real
panel anatomy → near-zero CLS). Adopt real skeletons (replacing `Loading` spinner) in the 10 heaviest panels:
Brief book+tape, WATCH table, DESK book, MARKETS map, EVTS calendar, RSCH list, SCREEN table, MEMB table,
movers grid, stock-window profile. Shimmer respects `prefers-reduced-motion` (static two-tone).
### 7.3 System page (F4.8)
`SystemTelemetry.tsx:252-257` already parallel-ish (two fetches), but BRIEF's `getSetupStatus` and System's
probes serialise elsewhere — builder: find the SYSTEM page's slow path by timing (`audit load=27.2s`); the
design rule: ALL mount-time probes go through one `Promise.allSettled([...])`; each card renders its own
Skeleton until its promise settles (no all-or-nothing); 10s/5s refresh intervals unchanged.
**Acceptance:** prod build route `/` first-load JS −40% vs tonight's baseline (build log table); tab switch
<300ms warm (prefetch optional, NOT in scope); 37-page audit green; System cold <8s; CLS on BRIEF <0.02 with
skeletons (browse perf).

---

## 8. Bundled mediums/polish (F4.5 + F-005/F-006 subset)
- **DESK LAST clip (F-014):** `DecisionDesk.tsx` watchlist table LAST column → `minWidth: 96` + §2 class; same
  for NAV column if clipped at 1280.
- **Tape priority-trim (F-012):** Brief tape renders items with `flex-shrink:0`; overflow rule: drop items
  from the RIGHT (least priority last: GOLD, VIX keep, breadth drops first) via CSS `overflow:hidden` +
  ordered rendering — builder implements by slicing the array at container width breakpoints (720/1024/1280),
  not mid-item truncation. "ML E…" tab label → `ML` (`page.tsx` tab defs).
- **9px floor (F-005, partial):** 97 `fontSize: 9|9.x` sites tonight; this program raises ONLY the data-
  bearing ones in audited pages (industry-rotation labels → 10px + hover-only per F-011-adjacent; footer 9.5px
  may stay — it is chrome, listed as exempt). Full sweep deferred; report the remaining census.
- **F-006 (mobile sheet + backdrop):** StockDetailModal at <768px: `position:fixed; inset:0` sheet, backdrop
  `rgba(5,7,10,.7)` ALWAYS (desktop too — fixes scroll-compete), body scroll-lock while open. (Backdrop at
  `Z.modal - 1`.)

---

## 9. B5 — Docs/architecture truth (F5.1–F5.5)
### 9.1 CLAUDE.md surgical edits (keep everything else byte-identical)
- **Replace** the "## Architecture" 8-service table with:
```markdown
## Architecture — what actually runs

Local stack (the real spine, 4 processes — see reports/production_review/architecture_reality.md):

| Process | Port | Role |
|---|---|---|
| data-service | 8001 | DuckDB owner, NSE live/EOD ingest, panels, Breeze live ticks |
| ui-api | 8010 | the terminal's single backend; proxies data-service; alerts, desk, research |
| master-controller | 8008 | IST job scheduler, Telegram bot, telemetry |
| Next.js terminal | 3000 | the UI (prod build via UI_MODE=prod; dist dir ui/.next-prod) |

Dormant legacy (code + tests kept, not running; autopilot OFF — do not plan against these):
api-gateway :8000 · feature :8002 · ml :8003 · rl :8004 · risk :8005 · execution :8006 · monitoring :8007
(the 5-day ML pipeline era; Breeze execution lives in ui-api/positions + scripts/live_execution today).
```
- **Replace** the "## 16-Week Roadmap" table with:
```markdown
## Where the plan lives
Product plan: docs/PRODUCT_STRATEGY.md (sleeves, Decision Desk, gates) · Operations journal:
docs/IMPROVEMENT_LOG.md (newest first) · Research verdicts: the RSCH tab / reports/*/FINDINGS.md.
```
- **Add** under "## Running Services" a canonical **How to run things** block: test-suite map (5 suites + the
  exact pytest commands), PYTHONPATH conventions (`PYTHONPATH=alpha_lab python alpha_lab/run_today.py`,
  `alpha_lab/paper/shadow.py --status`), `scripts/ui_audit.py`, `UI_MODE=prod ./start-local.sh restart
  frontend`, and the restart-freeze windows (07:45–09:20, 18:30–21:15 IST).
**AC:** `grep -n "Phase 1" CLAUDE.md` returns no roadmap row; table matches live `curl` reality; shadow
command findable by grep "shadow".
### 9.2 Root README.md (new, ≤40 lines)
Sections: what this is (2 lines + screenshot pointer to the design-audit first-impression.png path) · Quick
start (warm Mac): `./start-local.sh start` → :3000, `status`, `stop` · The three surfaces (terminal :3000,
Telegram bot commands, RSCH research library) · Where things live (CLAUDE.md map, docs/GETTING_STARTED.md,
docs/RUNBOOK_RESTORE.md (B1 writes it — link now, file lands same phase), docs/IMPROVEMENT_LOG.md) · Safety
line (paper only; no live orders).
### 9.3 GETTING_STARTED.md corrections
Fix the "UI API + frontend only" claim → full-stack reality of `start-local.sh` verbs; add prerequisites
actually read from scripts tonight: Node 20+/npm, `/Users/sudheer/Desktop/jupyter_env` python (NEVER system),
Chrome for Playwright login, `.env` from `.env.example` (B1 syncs keys) + pointer to RUNBOOK_RESTORE for the
4.4GB DB. AC: devex §1 table re-run → zero doc-vs-reality contradictions.
### 9.4 Root sweep manifest → `docs/legacy/` (moves only, nothing deleted; verify no imports first)
KEEP at root (15): `CLAUDE.md README.md GETTING_STARTED.md start-local.sh requirements.txt package.json(×?)
.env.example .gitignore Dockerfile docker-compose→infra/ pointer files alpha_lab/ data/ docs/ infra/ k8s/
logs/ reports/ scripts/ services/ shared/ tests/ ui/`.
MOVE → `docs/legacy/` (builder runs `git mv`, then `grep -rn <name> --include="*.py" --include="*.ts*"
--include="*.md" .` proves 0 live references each): the ~50 root-level `*.md` sprint/delivery files
(`ADVANCED_FEATURE_ENGINEERING_GUIDE.md`-era set lives in docs/ already — the ROOT strays are the target:
`*_SUMMARY.md, *_DELIVERY.md, PHASE*.md, *_REPORT.md, test_*.png`, loose `*.csv` → `docs/legacy/data/`).
Builder generates the exact list with `ls -p | grep -v /` minus KEEP, prints it in build_b5.md (the manifest
IS the deliverable; I deliberately do not freeze 50 filenames here — tree may shift by build time).
Plus `scripts/nse_panel_qa_old.py` → `docs/legacy/` (superseded; grep-verified unreferenced tonight).
### 9.5 `--help` floor (F5.5)
Six scripts get real one-line argparse descriptions + arg help: `daily_session_refresh.py` (has flags; verify
<1s), `ui_audit.py`, `nifty500_pipeline.py`, `evidence_probability_study.py`, `master_controller.py` (if
argparse absent, add `--help` short-circuit printing its docstring), and **`alpha_lab/run_today.py` — add
argparse BEFORE `load()` so `--help` returns <1s without the 15s panel load** (move `main()` body behind
`if args` parse; keep zero behaviour change on plain run).

---

## 10. Acceptance matrix (Phase 4 contract for B4+B5)
| Item | Verification |
|---|---|
| F4.1 pill dock | browse JS overlap=0 on DESK/MARKETS; Shift+N works; footer h22 unchanged; screenshots before/after |
| F4.2 tabular | computed-style census ≥95% numeric cells; WATCH tick screenshot no jitter |
| F4.3 alert | pixel-clean alert-editor screenshot; live SET lands `move`; Tab/Escape; aria snapshot |
| F3.3 chips/hook | mocked-ws ≤2s update; chip state flips; hidden-tab zero requests; audit 37 green |
| F4.4 tokens | hex census −≥300; tsc; amber-unified page spot-diffs; T↔--t-* sync check |
| F4.5/8 polish | DESK/tape/label screenshots; modal sheet at 375px with backdrop |
| F4.6 GO recall | scripted keyboard test in dev; chips screenshot; list-nav regression check |
| F4.7 skeletons | artificial 2s-delay screenshots on 10 panels; BRIEF CLS <0.02 |
| F4.8 System | audit harness System load <8s cold |
| F4.9 dynamic | `/` first-load JS −40% (build log diff); 37-page audit green |
| F5.1–3 docs | greps per AC; devex step-table re-run clean; README links resolve |
| F5.4 sweep | root entries ≤~15 dirs+core; per-file 0-reference greps printed in build report |
| F5.5 --help | `time script --help` <1s ×6 with meaningful text |

**Out-of-scope note (one sentence):** `lib/alerts.ts` keeps a `LEGACY_KEY` localStorage migration that can be
retired in a later cleanup, and the Tailwind-era styling inside `StockDetailModal` (slate/indigo classes,
`#2a3448`/`#8a94a6` literals) deserves a dedicated kit-migration pass beyond this program's token sweep.
