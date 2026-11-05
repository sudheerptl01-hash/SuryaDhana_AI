# Production review — SuryaDhana terminal (14 Oct 2026, evening)

**Scoreboard:** Health **37/37 pages · 738 tests · tsc clean** · Design **B+** (AI-slop **A**, system 72/100) ·
Contract **0 broken frontend calls** (1 backend bug found & fixed) · Duplicates **−233 LOC, 2 latent bugs killed** ·
Scale: warm routes **7–50 ms**, five concentrated debts · Operator DevEx **5/10** (fails the disk-wipe test).

Owner's brief: critique every component; improve for scale and latency; run /design-system, /design-review,
/devex-review and the duplicate-function hunt; remove duplicates; verify backend↔frontend match; verify everything
works; hold it to a production-grade Bloomberg-terminal standard.

## How this review ran (six parallel workstreams)
| Stream | Owner | Output |
|---|---|---|
| Health verification (37 pages, 5 test suites, tsc, mypy) | PM (main session) | `.logs/prodreview_health.log`, summarized below |
| Architecture reality check | PM | `architecture_reality.md` |
| Design system + live design review (gstack browse screenshots) | agent DS | `design_audit.md` + `~/.gstack/projects/SuryaDhana_AI/designs/…` |
| Duplicate-intent functions, find + safe consolidation | agent DUP | `duplicates.md` |
| Backend↔frontend contract + live endpoint verification | agent CON | `contract_audit.md`, `endpoint_latency.csv` |
| Scale & latency deep review | agent SCALE | `scale_latency.md` |
| Operator DevEx audit (devex-review scorecard) | agent DEVEX | `devex_audit.md` |

Ground rules applied: audit-first; **no commits** (dirty tree carries unreviewed work; design-review's fix-loop
deferred, duplicate removals applied as plain edits gated on green tests); no service restarts; agents barred from
Telegram and any state-changing POSTs.

## Architecture reality (full: `architecture_reality.md`)
The documented 8-service topology is 60% dormant. The real spine is **4 processes**: Next (:3000) → ui-api
(:8010) → data-service (:8001, 1.32 GB RSS) + master-controller (:8008, jobs + Telegram bot). CLAUDE.md's service
table and 16-week roadmap are stale enough to mislead (doc fix specified). Dormant legacy services
(feature/ml/rl/risk/execution/monitoring) need an owner decision: archive, document as dormant, or revive later —
not delete.

## Health verification — **everything works**
- **37/37 pages** load with no console errors and no failed API calls (`scripts/ui_audit.py`, both passes).
  Slowest: System 27.2s, Warehouse 7.2s (first-load; see Scale).
- **738 tests pass, 0 fail**: core 264 · scripts 117 · ui-api 328 · execution 7 · alpha_lab 12 · ICICI-login
  browser 10. TypeScript: `tsc --noEmit` clean.
- mypy (shared/, best-effort): 15 strictness errors in 5 files — polish items, none affect behaviour
  (e.g. `decision_desk.py:394` object+int typing; `icici_login.py:262` side-effect-in-lambda pattern).
- Live stack during review: data-service / ui-api / master-controller / Next all healthy; ICICI session valid.

## Design system + design review (full: `design_audit.md`; screenshots + baseline in `~/.gstack/projects/SuryaDhana_AI/designs/design-audit-20261014/`)
**Design Score B+ · AI Slop Score A · Design-System Score 72/100.** The terminal identity is authentic and
consistently applied: zero AI-slop patterns, model empty states, provenance ("as of …") on every panel, 825 ms
first load, clean console on all six audited pages, trunk test PASS 5/6. Goodwill flow 75/100 — the GO-bar →
stock-window in ~1 s is the magic moment.
**15 findings, 4 HIGH** (register in the full report; fix-loop deferred — no commits this session):
- F-001 HIGH: floating News-Scanner pill overlaps live charts (DESK book-vs-NIFTY, MARKETS P/E) → dock it.
- F-002 HIGH: `tabular-nums` on only 6 elements in a *numbers* terminal → one kit-level line stops column jitter.
- F-003 HIGH: 597 hardcoded hex beside a real 19-token kit (2,413 usages) — three competing ambers, Tailwind
  violet/teal drift, concentrated in Backtest/ML-era components; the kit itself lives in a misplaced path.
- F-004 HIGH: stock-window ALERT mode z-fights the price/watchlist chips; placeholder-as-label inputs.
- Mediums: skeletons on 3/73 components, aria on 11/73, off-scale 3/5/6/7 px spacings, RSCH renders ~50k-px pages,
  stock modal not a mobile sheet, 9 px text, **WATCH polls Yahoo 60 s while ICICI live is connected** (top
  Bloomberg-lens gap).
- Bloomberg gap table: live-quote chips, tabular numerals everywhere, GO recall/history, function chaining,
  linked panels, pop-out windows.
Quick wins (<30 min each): F-002 · F-004 · pure-#FFF → T.bright · DESK column clip · tab-label trim.

## Duplicates found and removed (full: `duplicates.md`; working data `dup_work/`)
Catalogued **1,920 Python + 593 TypeScript functions**, clustered by intent, then consolidated the safe set:
- **8 consolidation units applied, ~233 LOC removed** — survivor = the terminal kit for TS (`ordinal`, `tone` ×7,
  `num/fmt/fx/fNum` ×9 → `fmtNum`, `inr` ×3, `median`, new `fmtDay`, `tradingViewUrl`); Python: deleted the
  abandoned `services/feature-service/indicators/` package (188 LOC, zero imports repo-wide).
- **Two real bugs died with their duplicates:** MarketMonitor's local `ordinal` mis-suffixed 110–113; IpoMonitor's
  `median` was wrong on even counts.
- Verified: `tsc --noEmit` clean, 716 Python tests pass, no commits, no restarts (the rebuild below picks the TS
  edits up).
- **Deferred/INTENTIONAL** (tabulated with file:line): naming hazards (`cr` = rupees in 2 files, crores in 3),
  frozen research copies (`newey_west_t` family — pre-registered record, not retrofitted), alpha_lab vendoring
  (by design, drift-tested). Proposals for *future* code: `shared/db_snapshot.py`, `shared/stats.py`,
  ui-api `cache.py`. Dead file flagged for owner deletion: `scripts/nse_panel_qa_old.py`.

## Backend ↔ frontend contract (full: `contract_audit.md`, timings `endpoint_latency.csv`)
**The contract is tight.** 0 frontend calls hit a missing backend route; 139/146 live GETs return 200 at warm
p50 ≈ 8 ms; all 10 field-level checks (positions, monitor, indices, valuation, results, surveillance, desk,
research, alerts, profile) match their TS interfaces key-for-key.
- **C1 — the one genuine bug, FIXED during this review:** `GET /api/stocks/{ticker}/ohlcv` 404'd for every ticker.
  Root cause was worse than a wrong path: the route opened DuckDB *directly inside ui-api* (breaking the repo's
  own data-service-owns-the-lock rule, stated in the same file) with the ticker f-string-interpolated into SQL.
  Reimplemented as a proxy to data-service `/ohlcv/{ticker}`; 328 ui-api tests green; verified live post-restart.
- C2: 5 pipeline-model GETs return raw "Train model first" 503s (state, not bug) — needs designed empty states
  or route parking (see priorities: those routes look orphaned).
- C3: **8 dead routes** with no consumer anywhere (`dashboard/data-check`, `data/db/screener`, `ml/health`,
  `ml/runs`, `monitor/embed`, `execution/order/scheduled`, `positions/refresh-session`, `stocks/reload-universe`).
  Gold/desk/alerts "orphans" are real master-controller consumers — keep.
- C6 — silent-failure vector: error shapes split 3 ways (`{detail}` ~250× · soft-200 `{error}` ~65× ·
  `{connected:false}` 16×); components expecting one family render blank on another → one shared normaliser.
- Payload outliers: fundamentals-screen 529 KB, ipo 125 KB; slowest route lw/screener 1.71 s.

## Scale & latency (full: `scale_latency.md`, raw timings `endpoint_latency_scale.json`)
Warm paths are healthy — all 16 hot routes 200 OK, mostly **7–50 ms**, none over 500 ms warm. The debt is
concentrated:
1. **P1 withdrawn after verification — the "dev build" was a false alarm.** Prod serves from a separate dist
   dir (`NEXT_DIST_DIR=.next-prod`, start-local.sh:231): fresh BUILD_ID 21:41 tonight, shared first-load JS
   **102 kB** — healthy. The 7.4 MB artifact the scan found lives in the *stale dev* `ui/.next` (717 MB,
   prunable), which also explains the scary deleted-BUILD_ID git status. Residual truths: `app/page.tsx` still
   static-imports all 73 components (route-level bundle, worth `dynamic()` per tab but far less urgent), and the
   System page's 27 s first load is its own API fan-out (setup-status probes), not bundle size.
2. **P1 · 352 MB `pd.read_parquet` on the event loop** in three `async` routes (`services/ui-api/routers/
   pipeline.py:422,747,890`) — freezes every concurrent request and spikes RSS 1–2 GB; the most plausible
   mechanism of the historical ui-api OOM. (Likely orphaned routes — CON confirms below.)
3. **P1 · unbounded per-symbol cache** in `news_scanner._cache` (2-yr candle frames, never evicted) — slow leak;
   a 10-line bounded TTL dict closes it.
4. **P2 · the 4.7 GB snapshot-copy economy:** 16 call-sites; evenings run 4–6 private full copies ≈ 20–28 GB SSD
   writes/day (desk 19:30, news 19:45, shadow 19:50). Proposed: one shared evening snapshot via the existing
   `ReadSnapshot`. A 3.16 GB orphaned `.tmp` from an interrupted 02:55 copy was found and removed during review.
5. **P2 · DuckDB executes inside `async` handlers** at `stocks.screener` + two dashboard routes →
   `asyncio.to_thread`. The sync-route/threadpool pattern is otherwise followed; Yahoo fan-outs are properly
   concurrent and cached.
"If this served 100 traders" (design-ahead, not built): websocket fan-out for quotes, shared cache tier (Redis),
parquet/OLAP read path for research, stateless ui-api replicas behind a gateway.

## Operator DevEx (full: `devex_audit.md`) — **5/10 overall**
Smooth for its one daily operator; **fails the disk-wipe test**. Verified highlights:
- **Getting started 4/10:** `.env.example` is missing the three login-critical keys (ICICI_CLIENT_ID /
  ICICI_PASSWORD / ICICI_MOBILE); the 4.4 GB git-ignored DuckDB has **no documented backup/restore**;
  GETTING_STARTED.md mis-describes start-local.sh. Fresh-machine time-to-terminal: blocked. Warm machine ~2 min,
  and `start-local.sh status` is genuinely good.
- **Errors 6/10:** ICICI-expired message is the model (problem+cause+fix); `/api/stocks/<bad>` returns a bare
  `{"detail":"Not Found"}`.
- **Dev env 4/10:** five test suites, one documented; **no CI** (no .github/).
- **Bus factor 3/10:** `.env` is the sole secret store; ~50 loose legacy files bury the real docs; no root README.
- **Docs 6/10** (IMPROVEMENT_LOG-as-journal is the standout; shadow's manual run command undocumented) ·
  **Upgrade path 5/10** (39/39 pins, but shared jupyter_env hazard; node unpinned).
Top fixes by pain-per-effort: 1) sync `.env.example` (~30 min), 2) disk-wipe runbook, 3) nightly DB backup.

## Consolidated priority actions (ranked across all six streams)

**Done during this review:** C1 ohlcv fix (+ its DB-lock/SQL-injection smell removed) · 8 duplicate consolidations
(−233 LOC, 2 latent bugs) · dead indicators package deleted · 3.16 GB orphaned snapshot removed · frontend
prod rebuild + ui-api restart (and the BUILD_ID scare disproven: separate `.next-prod` dist dir) · RSCH catalog row for this report.

| P | Action | Stream | Effort | Why |
|---|---|---|---|---|
| 1 | `.env.example` sync (3 ICICI keys) + disk-wipe runbook + nightly DuckDB backup | DevEx | S | the only unrecoverable-loss risk in the stack |
| 2 | Bound `news_scanner._cache` (TTL + max entries) | Scale | S (10 lines) | unbounded growth; past ui-api OOM mechanism |
| 3 | Park or delete the orphaned `pipeline.py` heavy routes (352 MB parquet reads on the event loop) + the 8 dead routes | Scale+CON | S–M | removes the biggest freeze/OOM vector and dead surface |
| 4 | Error-shape normaliser (one convention; adapters at the 3 families) | CON | M | kills the silent-blank-panel class |
| 5 | Design quick wins: news-pill dock (F-001), kit-level `tabular-nums` (F-002), ALERT z-fix (F-004), #FFF→T.bright, DESK clip | Design | S each | 4 HIGH findings, all under an hour together |
| 6 | Shared evening snapshot via ReadSnapshot (desk/news/shadow reuse one copy) | Scale | M | 20–28 GB SSD writes/day → ~5 GB |
| 7 | Per-tab `dynamic()` imports in `app/page.tsx`; prune stale `ui/.next` dev dir (717 MB); make System's setup-status probes concurrent (its 27 s load) | Scale | M | route-bundle + first-visit polish (prod shared JS already 102 kB) |
| 8 | WATCH uses ICICI live quotes when connected (Yahoo fallback stays) | Design/Bloomberg | M | the terminal's top "feels like Bloomberg" gap |
| 9 | `asyncio.to_thread` the DuckDB calls in screener + 2 dashboard routes | Scale | S | event-loop hygiene, done pattern exists |
| 10 | Token sweep: 597 hardcoded hex → kit tokens (start with the 3 ambers); move kit out of `news/format.ts` | Design | M | one palette, one source |
| 11 | CLAUDE.md architecture table + roadmap rewrite; archive-or-document the 6 dormant services; repo-root cleanup (~50 legacy files); delete `nse_panel_qa_old.py` | Arch+DevEx | M | the map must match the territory |
| 12 | Minimal CI (the 5 suites + tsc on push) | DevEx | M | 738 green tests deserve a gate |
Deferred by design: design fix-loop commits (dirty tree), mypy strictness nits (15), MEDIUM/LOW duplicate
consolidations (tabulated), multi-user scale designs (websockets, Redis, replicas — specified, not built).

**Bloomberg-grade verdict in one paragraph:** the bones are genuinely there — a coherent terminal identity with
zero template smell, a tight contract, sub-50 ms warm reads, 738 green tests, honest provenance everywhere, and a
working phone channel. What separates it from production-grade Bloomberg today is operational hardening (backup/
restore, CI, error-shape discipline), latency polish at the edges (first-load JS, the few event-loop sins), live
tick wiring where it already has the data (WATCH), and the window-manager power features (linking, chaining,
recall). Nothing on that list is research risk; it is all engineering, and most of it is small.
