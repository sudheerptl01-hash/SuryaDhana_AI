# R-UI-PAGES — SHIP-WITH-FIXES

I diffed every file W2-UI-PAGES touched against its pre-wave-2 snapshot (scratchpad/W2-UI-PAGES/orig, 41 files). I also checked the three PM-applied patches against ~/.suryadhana_pm_backups/wave2_20261025-153255. I found no change to a computed value: every diff only changes how a number is printed (2 dp prices, U+2212 minus, 'cr' casing, Indian grouping inside the gold verdict sentences). Backtest CSV/Excel exports still write raw values. The kit's table CSV turns U+2212 back into ASCII '-'. Gates re-run: pages.check 119 passed / 0 failed / 0 pending, and tsc is clean (build info written to scratch, so the repo's tsbuildinfo is untouched). PR-1/PR-2: the TS and CSS tokens match, and dim is now 4.59 to 4.94:1 on the 5 tested backgrounds. PR-3 works: the live GET /api/mcx/quote reason no longer has the doubled ').'. The normal PORT path is right (the final-audit capture shows PAPER ONLY, LIVE struck through, the login button and no URL). StockRow memoization gets everything a row shows through its props, and the parent never mutates stock objects in place, so rows cannot go stale.

Two majors. (1) The new 'CALL WALL' label on the OMON OI chart marks the wrong strike whenever the real wall is outside the ±width_pct strike window. Live today, NIFTY's chart says CALL WALL 23,500 while the OI walls stat on the same page says 24,000, and FINNIFTY shows 25,000 against 26,000. (2) The PORT paper-only policy fails open when status is null: if the first refresh fails, PORT shows a working LIVE button and the 'Real orders will be sent to ICICI Breeze' confirm, and pages.check P1 'null status' locks this behaviour in as expected. The ui-api guard still refuses LIVE, so nothing can reach the broker. Minors: COMP merge-on-write brings back a removed last symbol on the next add (reproduced in a simulation of the component logic), the flash-clear timer can leave flashes stuck (pre-existing, and wave 2 added another way to trigger it), and the wave-2 tests are mostly source-string guards.

## RUP-01 [major] OI chart labels the in-window OI maximum as 'CALL WALL'/'PUT WALL', contradicting the page's OI walls stat
- verify: REAL->major
- file: ui/components/OptionChain.tsx:70
- evidence: OiBars computes callWall/putWall as argmax over data.rows (OptionChain.tsx:70) and draws 'CALL WALL'/'PUT WALL' above that bar (:101-112). But data-service option_chain.py:139-140 trims rows to a ±width_pct window around spot, while resistance/support (:168) are computed over ALL strikes, and the OI walls Stat (OptionChain.tsx:263) shows data.resistance[0]/support[0]. Live GET /api/market/option-chain/NIFTY: rows 21,250..23,950, resistance[0]=24,000, but the chart's argmax is 23,500. FINNIFTY: rows 22,950..25,850, stat 26,000, chart 25,000. BANKNIFTY and RELIANCE agree. The final audit capture reports/desktop_app/final/audit_8010/chromium/options.png shows 'OI WALLS 24,000 / 21,500' in the stat row and 'CALL WALL' over 23,500 in the chart. Secondary: the ATM dashed line sits at the bar's left edge (P + atm*bw, :89) while its amber tick/label is at the bar centre cx(atm).
- failure: On an expiry where the biggest call OI sits just outside the chain window (NIFTY and FINNIFTY today), a trader reading OMON sees two different call walls on one page (24,000 in the stat, 'CALL WALL' at 23,500 on the chart) and may place a resistance-based decision at the wrong strike. The label was added in wave 2 (the pre-wave-2 chart had no wall labels), so this is a new correctness regression.
- fix: Take the wall strikes from the server (data.resistance[0], data.support[0]) and find their index in rows. If a wall strike is not in rows, draw an edge marker instead ('CALL WALL 24,000 →' at the right edge) and do not label the in-window maximum as the wall. Keep the argmax only as an unlabelled emphasis, or drop it. Draw the ATM line at cx(atm), or label the bar edge, so the line and its tick line up. Add a pages.check case with a wall outside the window.

## RUP-02 [major] PORT paper-only policy fails open when status is null: LIVE button and the 'Go LIVE' confirm come back
- verify: REAL->minor
- file: ui/components/portfolio/policy.ts:50
- evidence: paperOnly = s?.live_allowed === false || policy === 'PAPER_ONLY' (policy.ts:50), so missing fields mean LIVE is allowed. LivePortfolio.refresh fetches status, positions and orders through one Promise.all (LivePortfolio.tsx:752). If any of the three rejects, status stays null and the page renders with defaultStatus (:850), which has no live_allowed/mode_policy. My node probe of the repo's policy.ts gives, for defaultStatus and for null: {known:false, paperOnly:false, modeLabel:'PAPER', liveSelectable:true, liquidateAllowed:true, liquidateLabel:'■ LIQUIDATE & HALT'}. pages.check.ts:167 ('P1 null status') asserts !paperOnly for null, which locks the fail-open in as expected. The 'older ui-api' compatibility path it protects cannot happen in this program, because the UI is served by the same ui-api release (:8010 static export, :3000 proxies to the same repo).
- failure: During a ui-api stall or any 5xx/timeout on /api/execution/positions or /orders at page load (the 14:40 loop-stall incident is exactly such a window), PORT shows a selectable LIVE button. Clicking it opens '▲ You are switching to LIVE mode. Real orders will be sent to ICICI Breeze.' with a confirm, and LIQUIDATE & HALT is enabled against an UNAVAILABLE engine. The server still refuses (403), so nothing reaches the broker, but the claims 'no path to Yes, Go LIVE' and 'fails closed' are false, and the owner sees a LIVE affordance on a PAPER ONLY terminal.
- fix: Fail closed on unknown: paperOnly = !(s?.live_allowed === true && upper(s?.mode_policy) === 'LIVE_ALLOWED'). With status == null, show a 'STATUS UNKNOWN · PAPER ONLY' chip and disable both LIVE and LIQUIDATE. Use Promise.allSettled in refresh so a positions/orders failure does not discard a good status. Change pages.check P1 'null status' and 'older API' to expect paperOnly=true and liveSelectable=false.

## RUP-03 [minor] COMP merge-on-write brings back a removed last symbol on the next add
- verify: not verified (minor/nit)
- file: ui/components/Compare.tsx:98
- evidence: The write effect skips empty sets (Compare.tsx:92, `if (!syms.length) return`), so removing the last chip never reaches storage. latestSyms() (:98) then reads load().syms from storage, which still holds the removed symbol. A simulation of the exact component logic with the repo's compareSet.ts (scratch final-R-UI-PAGES/compare_sim.mts): mount [TCS] → ✕ TCS → syms [] with storage still {syms:[TCS]} → add INFY → [TCS, INFY]. The pre-wave-2 code (`setSyms([...syms, s])`) gave [INFY]. load() also falls back to the TCS/INFY/HCLTECH defaults when the stored value is corrupt, so an add then merges into the defaults instead of the visible set.
- failure: The user clears COMP down to nothing and types a new ticker. The symbol they just removed comes back next to it and is persisted and synced to the server (and to every other window).
- fix: Persist the empty set (write {syms: [], period} and keep the 'no data' UI), or make latestSyms() fall back to the in-memory syms when the in-memory set is empty or the stored value fails to parse. Add an M1 case: remove last, then add, gives only the new symbol.

## RUP-04 [minor] Flash-clear timer is cancelled by the next tick or stocks change, so CMP flashes stick (pre-existing; wave 2 added a trigger)
- verify: not verified (minor/nit)
- file: ui/components/StockTable.tsx:176
- evidence: The flash effect sets a 700 ms timer that clears only that run's newFlashes, and its cleanup (`return () => clearTimeout(timer)`, :176) runs before every re-run. AppContext.setLiveQuote (context/AppContext.tsx:159-160) creates a new liveQuotes object per WS message, so with several watched symbols ticking within 700 ms each run cancels the previous run's clear. Earlier symbols keep 'up'/'down' (green/red cell and dot) until they tick again. Wave 2 added `tickers` (derived from `stocks`) to the deps (:177), so a filter, load-more or list reload inside the window also strands flashes. Now that rows are memoized, a stuck flash prop is never refreshed by an unrelated re-render.
- failure: In a live session with 10+ watched stocks on EQS, many CMP cells stay tinted green or red, showing a stale tick direction rather than the last 700 ms move.
- fix: Track a clear-deadline per symbol, e.g. a ref Map<sym, timeoutId> cleared only for that symbol, or one interval that nulls entries older than 700 ms, and do not clear timers in the effect cleanup except on unmount. Add a behavioural test with two ticks 300 ms apart.

## RUP-05 [minor] Wave-2 page checks are mostly source-string guards; none of them can catch RUP-01..04
- verify: not verified (minor/nit)
- file: ui/components/__tests__/pages.check.ts:213
- evidence: E1 (:213-220) checks for strings such as 'const StockRow = memo(function StockRow(' and 'fmtFixed(price, 2)'. M1 (:239-241) checks 'useExternalPrefChange(COMP_KEY' and 'compareAdd(latestSyms(), s)'. P1 (:167) asserts the fail-open null case. There is no behavioural test of row staleness, flash clearing, the remove-last COMP path or the OI wall source. Chart maths (§4) and the format functions are tested properly.
- failure: Refactors that keep the strings but break behaviour pass, and the behaviour bugs above shipped with a green 119/0 suite.
- fix: Add pure-function tests for wall selection (wall outside the window), a policy table with fail-closed rows, a Compare reducer test (remove last, then add), and extract the flash bookkeeping into a pure helper with a timed test.

## RUP-06 [nit] PR-1/2: muted and dim are now nearly the same grey; panel3 rows below 4.5:1; 41 hard-coded old muted copies remain
- verify: not verified (minor/nit)
- file: ui/components/news/format.ts:12
- evidence: Computed WCAG ratios: new dim #747e92 is 4.30:1 on panel3 #131926, which is used for selected and hover rows (MarketMonitor:226, CommandBar:305, RotationChart:92, EQS row hover). T1 tests only 5 backgrounds and leaves panel3 out. Muted/dim separation dropped from 1.87:1 to 1.28:1, and new dim vs old muted is 1.06:1. 'T1 muted ≥ dim' (pages.check:205) only checks ordering, so the hierarchy has effectively collapsed. 41 literal '#6f7a8e' (old muted) remain (GlassBoxStudio axis ticks, CommodityTab/WarehouseHealth MUTED, PipelineStudio, FactorDiagnosticStudio, global-error, ErrorCatcher, QuantKPICard slate border), so two different 'muted' greys now show.
- failure: Tertiary labels (as-of times, 'no data' dashes) read as secondary text, dim text on a selected row is just below AA, and charts built with Recharts keep the darker old grey next to kit charts.
- fix: Add panel3 to the T1 backgrounds, either nudging dim to about #7a8498 or excusing panel3. Require at least about 1.4:1 between muted and dim. Replace the 41 literals with var(--t-muted)/T.muted in a follow-up sweep.

## RUP-07 [nit] Regex lookbehind now sits in the kit-wide chunk while the app's floor is macOS 13.0
- verify: not verified (minor/nit)
- file: ui/lib/format/index.ts:84
- evidence: indianGrouping uses /(?<![\d,.])…/ (:84). lib/format is re-exported by components/terminal/index.tsx:23, so it loads with every page. Lookbehind needs WebKit/Safari 16.4 (macOS 13.3). desktop/src-tauri/tauri.conf.json:46 sets minimumSystemVersion 13.0. SWC cannot transpile lookbehind. Markdown.tsx already had one before wave 2, but only in its own chunk.
- failure: On macOS 13.0–13.2 with stock WebKit, the shared chunk throws a SyntaxError at parse time and every page goes blank. The owner's Mac (macOS 26) is not affected.
- fix: Rewrite without lookbehind, e.g. /(^|[^\d,.])(\d{1,3}(?:,\d{3})+)(\.\d+)?(?!\d|,\d)/g keeping $1, or raise minimumSystemVersion to 13.3.

## RUP-08 [nit] Stock-window legend moved into the layout flow, so the chart shifts down when it appears or wraps
- verify: not verified (minor/nit)
- file: ui/components/IndicatorPriceChart.tsx:285
- evidence: The legend row is conditional on legendEntries/overlay/lastVol (:284) and uses flex-wrap. With no indicators active it appears only after bars arrive (lastVol), and with many indicators it wraps to two lines, pushing the lightweight-charts canvas down. The file header still says 'zero layout shift'.
- failure: Opening a stock window or toggling indicators moves the price pane by 1–2 rows (a visible jump, CLS).
- fix: Reserve the legend row (fixed min-height, render it always with placeholders), or keep it absolute inside a reserved top margin of the price scale (scaleMargins.top).

## RUP-09 [nit] Incremental-mount limit never resets; memoized rows freeze the daysUntil badges
- verify: not verified (minor/nit)
- file: ui/components/StockTable.tsx:236
- evidence: `limit` grows to the full length once and is never reset (:236-242). It also keeps growing while `loading` shows the skeleton, so a later filter or screener result (up to ~1,500 rows) renders in one synchronous pass, which is the pre-fix cost. EventBadge's days=daysUntil(...) is computed inside the memoized StockRow, and useCorpEvents never refreshes its Map while mounted, so a badge such as 'in 1d' no longer updates on hover or tick re-renders. Before wave 2 the whole table re-rendered on every hover or tick.
- failure: Applying a screener filter in WebKit stalls for about 1 s as before. On a desktop app left open on EQS across midnight, event badges show yesterday's day count.
- fix: Reset limit to FIRST_ROWS when the result set changes (key the effect on the `stocks` identity or filters), and pass an IST day key (istDateISO()) to StockRow as a prop so badges re-render once a day.

## RUP-10 [nit] MLEW and GBOX default ranges now move every day
- verify: not verified (minor/nit)
- file: ui/components/MLEngineWorkspace.tsx:56
- evidence: MLEW now defaults to trailingRange(36) ending today (was 2023-01-01 → 2025-12-31), and GBOX to trailingRange(9) (GlassBoxStudio.tsx:41-42). A default 'Run Production Engine' now trains on a window that changes daily and ends on a date whose last ~5 sessions have no forward label yet.
- failure: Two default runs on different days are not comparable, and baseline-vs-current parity of MLEW defaults no longer matches the pre-program build, even though training logic is unchanged.
- fix: Show the computed range explicitly and record it in the run metadata, or end the default at the last labelled session (today minus the label horizon). Note the default change in the improvement log so the owner sees it.

## RUP-11 [nit] Round-tick axes can drop to 2 unlabelled-unit ticks; small cleanups
- verify: not verified (minor/nit)
- file: ui/components/DerivativesDesk.tsx:87
- evidence: In the final audit capture derivatives.png, the near-month annualised basis axis shows only '50' and '0' (no '%') for a range of about −45..+85, because niceAxis with 4 ticks over the padded range gives a step of 50. Also: MarketMap group average colours a −0.03 average red while fmtPct prints '0.0%' (MarketMap.tsx g.avg >= 0 test vs the rounded label). lib/format exports unicodeMinus and fmtSigned that nothing uses.
- failure: A reader cannot read basis levels between 0 and 50, and sees red '0.0%' industry headers.
- fix: Use maxTicks 5–6 with the ticks' dp and a '%' suffix on rPct/basis axes. Colour by the rounded value. Drop the unused exports or use them.

### claimed fixed but not
- C1-trader-ux-04 (W2: 'fails closed', 'There is no green LIVE and no path to Yes, Go LIVE'): when the first PORT refresh fails (status null → defaultStatus), executionPolicy gives liveSelectable=true and the LIVE confirm is reachable (RUP-02); pages.check P1 'null status' asserts this fail-open.
- C1-trader-ux-17 (W2: 'OMON's OI chart shows which strike holds each wall', 'ATM and the two OI walls always labelled'): when the wall strike is outside the chain's strike window the chart names the wrong strike: NIFTY 23,500 vs stat 24,000 and FINNIFTY 25,000 vs 26,000, live today (RUP-01).
### not checked
- No browser was used (per brief). Not checked: px-sized charts shrinking on window resize inside flex/grid ancestors, the stock-window legend layout shift, and WebKit rendering of the new SVG axes. I only looked at the PM's final-audit PNGs already on disk.
- EQS performance numbers (hover p50, tick main-thread %, first-screen times) were not re-measured.
- The two-window COMP browser E2E (scripts/desktop_qa/e2e_compare.py) was not re-run. Merge-on-write was checked by code reading plus a node simulation of the component logic.
- Parsing of lookbehind regexes on macOS 13.0–13.2 WebKit was not tested.
- The PM's 42-page audit and the :8097/:8098 symmetric parity (still running; AUDIT3_DONE did not exist during this review).
- Other wave-2 streams (W2-UI-SHELL, W2-API, W2-RUST, W2-OPS) beyond PR-3's mcx.py line, and the other UI node suites (desktop/prefs/platform/alerts/ws), which I did not re-run.
- Server-side PAPER-ONLY guard behaviour beyond reading execution.py; no POSTs were sent (GET-only rule).

# R-UI-SHELL — SHIP-WITH-FIXES

I diffed W2-UI-SHELL against the fixer's pre-wave-2 snapshot (scratchpad/W2-UI-SHELL/orig, 25 files plus 14 new ones) and diffed PR-WS1 and PR-CHIP1/2 against ~/.suryadhana_pm_backups/wave2_20261025-153255. I read every changed file. Gates I re-ran myself: desktop.check 222/222, prefs 160, platform 120, alerts 18, ws.check 66 with section 7 now enforcing (PR-WS1 is detected in the source), and pages 119. tsc is clean; I ran it with --incremental false so ui/tsconfig.tsbuildinfo was not touched. With GETs on :8010 I confirmed that the live release 20261025-153533 contains the PR-WS1 guard (`this.ws===e&&(...)`) and the PR-CHIP strings.

The core mechanics hold up. History works with Next 15.5.18, whose patched pushState/replaceState copy __NA (I checked app-router.js), so popstate restores without a page reload. There are no double pushes (same-tab and open-stock-window cases are guarded). A deep-linked stock window is removed in place, and only a window the page pushed is closed with Back. In the app, Back is blocked at the boot page by the Rust policy and its selftest. Type-to-GO skips text inputs, contentEditable, modifier keys, IME composition, key repeat and keys another handler already used (DataTable j/k runs first through React's root listener). Error boundaries reset on keys compared by value, so they cannot loop. sharedFetch drops rejected requests and keys entries by IST day. The holiday store owns one retry timer per entry. All 41 lazyTab export names match their modules. PR-WS1 is correct: a plain disconnect behaves as before, and only a replaced socket's late close is ignored.

I found no blockers. Real issues:
- **Outage dimming breaks overlays inside pages.** The filter and opacity on .sd-page re-anchor fixed overlays inside pages during an outage. That covers the ALFA and BTST stock windows, the PIPE and ModelLab modals, and the IndicatorMenu backdrop.
- **OVRV shows zeros as data.** Removing the bootstrap gate made OVRV render "Universe 0 / 0% CURRENT / ▶ Enrich now" before its data loads. That contradicts the claim that "what OVRV shows is unchanged".
- **Wrong chips during Muhurat.** The new feed chips will actively claim CLOSED / "NO TICKS" during the Muhurat session on Sun 8 Nov 2026.
- **Silent boundaries never retry.** The GO, NEWS and watchlist boundaries only reset after an outage.
- **The post-outage reload is coarse.** One epoch remounts both the page and the stock window, in every window at the same moment.

Also: C1-trader-ux-16 is marked fixed but is incomplete (no ⌘-click on TickerLink, no polling back-off), and the mnemonic part of C1-trader-ux-09 was not done. The rest are nits: copy, the Back-key hint for browsers on macOS, a test that can never fail, and the autofocus in the confirm dialog.

## R-UI-SHELL-01 [minor] LINK DOWN dimming (filter + opacity on .sd-page) re-anchors and buries fixed overlays rendered inside pages
- verify: not verified (minor/nit)
- file: ui/app/globals.css:405
- evidence: globals.css:405 `.sd-main[data-link="down"] .sd-page { opacity: .55; filter: saturate(.55) }`. Per CSS Filter Effects, filter≠none makes the element the containing block for position:fixed descendants, and opacity<1 creates a stacking context. These fixed overlays render inside .sd-page: AlphaDiscoveryDesk.tsx:593 and BacktestPanel.tsx:592 mount <StockDetailModal> (StockDetailModal.tsx:221 `fixed inset-0`, z Z.modal=120, top var(--shell-top)); also PipelineStudio.tsx:138, ModelLab.tsx:257 (`fixed inset-0 z-50`) and IndicatorMenu.tsx:60 (backdrop). The sticky header (Z.header=30) and the fixed footer (Z.footer=40) sit outside .sd-page, so after the stacking context forms they paint over anything inside it.
- failure: The owner has the ALFA (or BTST) stock window open when ui-api stalls, as in today's 14:40 incident. After the 4 s grace, link='down' applies the rule. The window is then laid out against the .sd-page box, which can be several thousand px tall, so its centred content can drop below the viewport. It paints under the sticky header, watchlist bar and footer, at 55% opacity, and backdrop clicks outside the page box no longer close it. The same happens to an open PIPE/ModelLab training dialog. Everything snaps back at LINK UP.
- fix: Do not put filter or opacity on an ancestor of page content. Set `.sd-page{position:relative}` and dim with an overlay that does not wrap the content: `.sd-main[data-link=down] .sd-page::after{content:'';position:absolute;inset:0;background:rgba(5,7,10,.45);pointer-events:none}`. Alternatively, portal the page-level modals (inline StockDetailModal, PipelineStudio/ModelLab dialogs) to document.body.

## R-UI-SHELL-02 [minor] OVRV now renders before the dashboard summary and shows invented zeros ('Universe 0', '0% CURRENT', '0 of 0 enriched', '▶ Enrich now')
- verify: not verified (minor/nit)
- file: ui/app/page.tsx:931
- evidence: Before wave 2, the gate kept OVRV hidden until getDashboardSummary resolved. Now OverviewTab renders immediately. page.tsx:903-916 sets every stat to `dashboard?.x ?? 0` (enrichTotal and dbCount fall back to totalStocks, which stays 0 unless EQS was visited). :931 shows Universe 0 and In database 0, the freshness chip reads 0% CURRENT in red, and :976 labels the button '▶ Enrich now' because `enriched === 0`. There is no loading state for `!dashboard && !dashError`. The ErrorBox (:924) appears only after a failure, and the zeros still render under it. W2-UI-SHELL claims 'What EQS and OVRV show is unchanged'.
- failure: During the 18:30–21:15 EOD window, when DuckDB is busy (the scenario that motivated C1-trader-ux-03), /api/dashboard/summary takes several seconds or fails. OVRV says the database has 0 stocks and 0% current, and offers 'Enrich now' as if nothing were enriched. The owner may trust it, or start a universe-wide enrichment job for no reason.
- fix: In OverviewTab, when `!dashboard`, render a Pending/Loading state (or '—' values) instead of 0, and disable or hide the enrich button until the summary has loaded. If dashError is set, show only the ErrorBox.

## R-UI-SHELL-03 [minor] New chips actively claim 'CLOSE <day>' / 'SOCKET OK · NO TICKS' during the 8 Nov 2026 Muhurat session
- verify: not verified (minor/nit)
- file: ui/lib/feedState.ts:68
- evidence: socketChip (:68) and niftySourceChip (:48) switch to closed wording whenever useMarketOpen() is false. That flag comes from nseSession, which returns CLOSED for every weekday 0/6 (components/desktop/session.ts:58) and has no special-session support. The repo itself lists 'Muhurat trading (Diwali Laxmi Pujan)' on 2026-11-08, a Sunday (shared/mcx_specs.py:92). The live eco calendar (GET ?back=0&ahead=20) has only the 2026-11-10 holiday and no special-session entry. Before wave 2 the chips said STREAMING/LIVE, which would have been correct during that session.
- failure: In two weeks, during the Muhurat hour, the ICICI stream ticks and NIFTY moves in the header. Meanwhile the NIFTY chip reads 'CLOSE 06-NOV', the watchlist bar and ALFA read '● SOCKET OK · NO TICKS', and the session chip reads CLOSED. A positive false claim on a live session.
- fix: Make the chips data-driven first: if a monitor tick for NIFTY or a watched symbol arrived within the last ~90 s, show the live wording whatever the calendar says. Then add a special-sessions list to session.ts, fed from the ECO/NSE feed or from shared/mcx_specs.

## R-UI-SHELL-04 [minor] 'silent' boundaries (GO, NEWS, WATCHLIST BAR) only reset after an outage, so one throw disables GO / ⌘K / type-to-GO for the rest of the window's life
- verify: not verified (minor/nit)
- file: ui/app/page.tsx:854
- evidence: page.tsx:802, :844 and :854 pass resetKey={epoch}. Epoch changes only after a reconnect whose page text matches the failure regex, and TabErrorBoundary.onReconnected only fires on RECONNECTED_EVENT. The silent variant renders null (TabErrorBoundary.tsx:145) with no RETRY. The CommandBar items memo has an unguarded path, CommandBar.tsx:182 `s.n.toUpperCase()`, which throws on a symbols row with a null name.
- failure: /api/stocks/symbols returns one row with n=null (a newly listed stock), and the owner types its prefix. CommandBar throws and the GO boundary swallows it. From then on '/', ⌘K, type-to-GO, Shift+Enter and the app's Go-menu command-bar event do nothing in that window. The only cue is the footer chip '⚠ 1 UI ERROR'. It recovers only on reload or after an outage.
- fix: Key the silent boundaries on `${epoch}:${view}` so a page switch retries them. Also reset the GO boundary on the next 'suryadhana:command' or keydown, and show a one-line footer cue ('GO unavailable · retry'). Separately, guard `s.n` in CommandBar.

## R-UI-SHELL-05 [minor] Post-outage reload is coarse: one epoch remounts the page AND the stock window, in every window at the same moment
- verify: not verified (minor/nit)
- file: ui/app/page.tsx:362
- evidence: onReconnected (page.tsx:359-366) scans main.innerText and the stock window's textContent, and if either matches it bumps the single `epoch`. That epoch keys both the page div (pageKey) and `stock:${epoch}` (:859). The handler fires in every window at the same LINK UP edge, with no jitter. BRF alone issues about 30 useLoad GETs on mount (Brief.tsx:94-150). The scan also includes the in-page LINK DOWN notice (it is still in the DOM when the event fires). I checked with node that today's notice wording does not match FAILED_LOAD_TEXT, but no test guards that.
- failure: (a) The owner has BTST results or OSTR legs on screen, with a stock window on top whose intraday panel failed during the outage. On LINK UP the healthy page underneath is remounted too, and the results and inputs are lost. That contradicts 'healthy pages keep their state'. (b) With several windows open after a ui-api stall, all of them remount at once and send a burst of GETs to a ui-api and data-service that have just recovered. (c) A future change to the notice wording that contains 'server unreachable' would remount every page on every reconnect.
- fix: Use separate page and stock epochs, each bumped only for the surface whose text failed. Scan `.sd-page` instead of `main`, so the notice is excluded, and add the notice text to the 'healthy' cases in desktop.check. Add a 0–2 s random delay per window before remounting. Where a page uses useLoad, prefer re-running only the loads that failed.

## R-UI-SHELL-06 [minor] C1-trader-ux-16 is marked 'fixed' but TickerLink ⌘-click/middle-click to a new window and the chrome-polling back-off are not implemented
- verify: not verified (minor/nit)
- file: ui/components/terminal/index.tsx:618
- evidence: The round-1 fix asked for '⌘-click or middle-click on page tabs and TickerLinks call newWindow(tab, sym)' and for 'back off chrome polling when the market is closed or the window is hidden'. TickerLink's onClick (terminal/index.tsx:618) always calls openTicker(symbol) and ignores metaKey and button 1. MarketCommandHeader still polls on 5 s/15 s/60 s intervals (:83, :98, :195) whatever the session or visibility. Only page-tab ⌘-click, GO Shift+Enter, ?sym= and the stock window's NEW WINDOW were done.
- failure: ⌘-clicking a ticker in DESK, MKT or EVTS opens it in the same window instead of a new one. With 8 windows open on a weekend, the header chrome still polls about 8× more than it needs to.
- fix: In TickerLink, if e.metaKey/e.ctrlKey or e.button===1, call newWindow(currentTab, symbol) (onAuxClick for the middle button). In NiftyLive and the macro tape, lengthen the intervals while !marketOpen or document.hidden. Or mark C1-trader-ux-16 as partially fixed.

## R-UI-SHELL-07 [nit] The Bloomberg-alias part of C1-trader-ux-09 was not done; 'BACK' still resolves to BTST now that real Back exists
- verify: not verified (minor/nit)
- file: ui/components/CommandBar.tsx:174
- evidence: The round-1 fix included 'aliases GP→CHRT, TOP/N→NEWS, MOST→MOV, BRIEF→BRF'. The scoring at CommandBar.tsx:174 has no alias table. I computed the results against the live /api/stocks/symbols (GET): 'BACK' matches the 'Backtest lab' label prefix, so BTST is the top item, and 'GP' resolves to the tickers GPIL/GPPL/GPTINFRA.
- failure: A Bloomberg user types BACK <GO> expecting to go back and lands in the Backtest lab. Typing GP opens a ticker instead of the chart.
- fix: Add a small alias table (BACK→history.back, GP→charts, TOP/N→news, MOST→movers, BRIEF→brief), ranked above ticker matches. Or record this sub-item as deferred.

## R-UI-SHELL-08 [nit] Browser-mode help and footer teach Alt+←/→ for Back/Forward, which is the Windows/Linux binding (the owner is on macOS)
- verify: not verified (minor/nit)
- file: ui/lib/shortcuts.ts:64
- evidence: helpKeys(false) at :64 shows 'Alt ← · Alt →' and footerHint(false) at :76 shows 'ALT+←/→ BACK/FWD'. In Safari and Chrome on macOS, Back/Forward are ⌘[ / ⌘] (or ⌘← / ⌘→), and Alt+← moves by word.
- failure: The owner uses the :3000 or :8010 browser terminal on the Mac, presses Alt+←, and nothing happens.
- fix: Detect a Mac (navigator.userAgentData?.platform or navigator.platform) and show '⌘[ · ⌘]' there.

## R-UI-SHELL-09 [nit] 'The error was logged for diagnosis' is shown even when nothing was sent; the chip says 'ON THIS PAGE' but lists the whole window
- verify: not verified (minor/nit)
- file: ui/components/shell/TabErrorBoundary.tsx:186
- evidence: TabErrorBoundary.tsx:186 and global-error.tsx:83 always say the error was logged. clientErrors.send() skips the POST in readonly QA mode, the gate drops duplicates and rate-capped reports, and the fetch fails silently during an outage, which is exactly when the global card tends to appear. ErrorCatcher.tsx:80 says 'UI ERRORS ON THIS PAGE', but the log is module-level and spans every page visited in that window.
- failure: After a crash during an outage, the owner relies on the server log for diagnosis, but no line was ever written.
- fix: Use the entry's `sent` flag ('reported to ui-api' / 'will not be reported: ui-api unreachable'), and rename the heading to 'UI ERRORS IN THIS WINDOW'.

## R-UI-SHELL-10 [nit] LINK UP does not kick the live-quote socket; wsManager's backoff can keep 'WS RECONNECTING' for up to 32 s after the banner says reconnected
- verify: not verified (minor/nit)
- file: ui/lib/monitorLifecycle.ts:33
- evidence: attachMonitorSocket listens only to pagehide/pageshow. wsManager._scheduleReconnect (wsManager.ts:244-250) doubles the delay from 2 s up to 32 s. Over a 15–60 s ui-api restart, the next attempt can land 15–30 s after LINK UP.
- failure: During market hours, ui-api restarts for 20 s. The banner turns green, but the watchlist bar and the NIFTY chip stay on reconnecting/ICICI and no ticks arrive for another ~10–30 s.
- fix: In attachMonitorSocket, also listen for RECONNECTED_EVENT. When !socket.isConnected, call a new wsManager.reconnectNow() that cancels the timer, resets the delay to 2 s and calls _open().

## R-UI-SHELL-11 [nit] stripScreenPx is a tautology, so the 7 'strip inset is 84 screen px' checks can never fail
- verify: not verified (minor/nit)
- file: ui/components/desktop/zoom.ts:31
- evidence: zoom.ts:29-32 returns `cssPx * (1 / z) * z`, which equals cssPx, and desktop.check.ts:508 asserts that it is 84. The real geometry is covered only by browser section Z, which used CSS zoom on <html> rather than WKWebView pageZoom.
- failure: A future change to the strip's counter-zoom (dropping `zoom: 1 / z`, or moving the inset to padding in rem) would still pass these checks, so the 222-check count overstates coverage.
- fix: Remove stripScreenPx and its 7 checks. Assert the real geometry in the app selftest (W2-RUST) after set_zoom: read the wordmark's getBoundingClientRect().left × factor ≥ 84.

## R-UI-SHELL-12 [nit] The confirm popover autofocuses START DOWNLOAD, so click + Enter/Space starts the 1,500-stock / 5-year download
- verify: not verified (minor/nit)
- file: ui/components/MarketCommandHeader.tsx:477
- evidence: MarketCommandHeader.tsx:477: `<button autoFocus onClick={() => { setAsk(false); onConfirm() }}>START DOWNLOAD`. Esc and outside clicks cancel, but a keyboard confirm takes one keystroke.
- failure: The owner clicks UPDATE DATA to read the scope and presses Enter or Space out of habit, and a long data-service job starts (during the EOD window, the warning they just saw is bypassed).
- fix: Autofocus CANCEL (or nothing), so that starting the download takes a deliberate click or Tab.

### claimed fixed but not
- C1-trader-ux-03 (claim 'What EQS and OVRV show is unchanged'): OVRV now renders before /api/dashboard/summary and shows Universe 0 / In database 0 / 0% CURRENT (red) / 0 of 0 enriched / '▶ Enrich now' while the summary loads or after it fails (ui/app/page.tsx:903-976). EQS handles its loading state correctly.
- C1-trader-ux-16 (marked fixed): TickerLink ⌘-click/middle-click to a new window (ui/components/terminal/index.tsx:618) and the closed-market/hidden-window back-off of chrome polling, both in the round-1 fix, are not implemented. Only page-tab ⌘-click, GO Shift+Enter, ?sym= and the stock window's NEW WINDOW were done.
- C1-trader-ux-09 (marked fixed): the Bloomberg mnemonic sub-item (aliases GP→CHRT, TOP/N→NEWS, MOST→MOV, BACK, exact-code priority) was not done. 'BACK' still resolves to BTST and 'GP' to the tickers GPIL/GPPL (computed against the live symbols list).
### not checked
- Any browser run (not allowed by this brief): I did not render the CSS-filter containing-block effect (R-UI-SHELL-01), the OVRV zeros (R-UI-SHELL-02), or real popstate in WebKit or Chromium. Those conclusions come from code plus the CSS spec, plus the fixer's 13/13 browser sections.
- Real WKWebView pageZoom geometry of the counter-zoomed strip (K3). I did not launch the app; the fixer's section Z used CSS zoom on <html>.
- Idle CPU of 2.6% now vs 0.79% this morning. I found no new infinite animation or per-second timer in the shell or BRF chrome (HeaderClock renders only in browser mode, NewsDock and NEW BUILD animations are finite, the feed chips tick once a minute). The remaining infinite animations are in page files: the SystemStatusWidget Dot pulse on OVRV/ALFA, animate-pulse in SystemTelemetry, LivePortfolio and PipelineStudio, and StockTable live dots. The installed app's main window is on BRF (state.json), so the cause is not established.
- Server side of K1 (/api/client-errors), the K2 migration block, PR-OPS1 netpolicy, and the Rust Go-menu and session code beyond the lines quoted (R-API / R-OPS / R-RUST scope).
- ui/scripts node --test suites and the pytest desktop contract/harness (not re-run; the PM's gates report them green).

# C-SECREL — SHIP-WITH-FIXES

On the live stack, the round-1 security blockers are closed for direct access to all three services. I used GET/OPTIONS probes plus write probes to a route that does not exist, so the guard's verdict comes before any handler could run.
- **Host checks:** a spoofed Host, `testserver`, the LAN IP and a foreign X-Forwarded-Host all get 400 on :8010, :8001 and :8008.
- **Origin checks:** a foreign Origin, a null Origin, Sec-Fetch-Site cross-site, a remote X-Forwarded-For write and a WebSocket from a foreign Origin all get 403. Control: the terminal's own origin gets 404.
- **CORS:** there are no CORS grants left anywhere.
- **PAPER ONLY:** /api/execution/status reports mode PAPER, live_allowed false, mode_policy PAPER_ONLY, and .env has no EXECUTION_LIVE_ALLOWED key. Every order path goes through `_guarded_engine`, and the only callers of `place_order` are in the execution router. Writing that key through .env is blocked by a key allowlist plus refusal of newlines and control characters.
- **Headers and docs:** HTML gets the CSP / X-Frame-Options DENY / Referrer-Policy headers, and ui-api's /docs and /redoc return 404.
- **Downloads and the shell:** downloads are hardened. The trust guard runs live (it recognised pid 81132 as this user's CPython). The release binary has no Web Inspector.
- **Loop-stall watchdog:** it works live. It caught the PM's 45 s SIGSTOP drill (a 48.5 s stall at 15:39:40 IST) with full stacks.
- **App crash relaunch:** the LaunchAgent is correct (KeepAlive SuccessfulExit=false, ThrottleInterval 20, running as a launchd job).
- **Secrets:** a scan of 602 artifact and log files found 0 secret values.

**What is still open:**
1. **Guard bypass through :3000 (major, security).** C2-security-01 is only closed for direct access. The optional :3000 server is running right now for the owner's settings migration, and its six Next route handlers re-send requests to ui-api without Origin or X-Forwarded-Host. I confirmed this live: a DNS-rebinding Host gets 400 through the /api rewrite but 200 through /api/telemetry/logs/stream. In scratch, against the real guard, a cross-site text/plain POST gets 403 when sent directly and 200 when it goes through a copy of the route handler. Any web page could therefore start unlimited ML training runs or backtests.
2. **No off-machine alerting (major, ops).** The Mac stopped uncleanly at about 16:35 IST on 24 Oct and stayed down until it rebooted at 10:57 on 25 Oct. No alert went out, and the 02:15 backup was missed. The dead-man switch (HEALTHCHECK_PING_URL) is not configured, and neither the RUNBOOK nor .env.example mentions it.

**Minor items:**
- .env values containing ` #`, `${…}` or a leading quote are accepted, written raw, and read back differently at the next start. A leading quote can swallow the keys that follow, including TELEGRAM_BOT_TOKEN.
- A credential save resets .env from 0600 to 0644.
- The trust verdict is cached for 30 s, and the scripts that already-open windows load are never checked.
- A watchdog lock left by an unclean stop blocks the watchdog for up to 20 min after boot. During that time the app shows "the watchdog is starting the stack" and offers no Start.
- Crash relaunch only covers the instance launchd started; a copy reopened by hand after ⌘Q is not relaunched.
- Data-service and master-controller still serve /docs, which loads swagger-ui from a CDN without version pinning or integrity checks.
- The CSP is minimal.
- Every proxied request builds a new httpx client on the event loop.
- Small issues in status, Telegram and the single-instance socket.

None of these touch trading logic.

## SECREL-01 [major] Next :3000 route handlers re-send POSTs and streams to ui-api with no Origin, Sec-Fetch-Site or X-Forwarded-Host, so the guard sees a trusted no-Origin local client
- verify: REAL->major
- file: ui/app/api/ml/train/stream/route.ts:20
- evidence: The 6 handlers under ui/app/api/** (ml/train/stream, analytics/backtest/stream, analytics/wfo-backtest/stream are POST; telemetry/logs/stream, pipeline/ml-stream, pipeline/rl-stream are GET) are unchanged since 13 Jun. Each calls fetch(`${API_BACKEND}/...`, {headers:{'content-type':'application/json'}, body: await req.text()}) and forwards no browser context. The live :3000 is `next start -H 127.0.0.1 -p 3000` (pid 44875) serving ui/.next-prod built 25 Oct 11:44, whose server/app/api/ml/train/stream/route.js is present. Live probes, GET only: Host rebind.attacker.example:3000 to /api/health (the rewrite path) gets 400; the same Host to /api/telemetry/logs/stream (a route handler) gets 200. OPTIONS from https://evil.example returns 204 with no CORS headers, which does not matter for simple requests. Scratch reproduction with the real install_http_guard on a FastAPI echo (:18971) and a Node replica of route.ts (:18972): a text/plain POST with Origin https://evil.example and Sec-Fetch-Site cross-site gets 403 when sent directly and 200 through the replica. The handler then saw origin=null, sec-fetch-site=null, xfh=null, host=localhost:18971. ml_workspace.train_stream has no limit on concurrent runs, and each run saves a model file. The round-1 FX-PY adversarial check reported this as 'not really fixed'; wave 2 did not take it up.
- failure: The owner follows RUNBOOK §8: `start frontend`, open http://localhost:3000 in their usual browser, and leave :3000 running for a while (it is running now). Any web page they open in that browser loops `fetch('http://127.0.0.1:3000/api/ml/train/stream',{method:'POST',mode:'no-cors',body:'{"mode":"production",...}'})`, plus the backtest streams. Each call starts XGBoost training or a backtest inside ui-api, the terminal's only backend. CPU and memory are exhausted (the 15 Oct OOM class) and models/ fills with run files. A DNS-rebinding page can also read the scheduler log stream through the GET handlers.
- fix: In the three POST handlers forward the browser context the way the rewrite does: headers {'content-type':'application/json','x-forwarded-host': req.headers.get('host') ?? '', origin, sec-fetch-site when present}. In the three GET handlers add 'x-forwarded-host'. Alternatively, reject in the handler itself: 400 unless Host is 127.0.0.1:3000 or localhost:3000; 403 when Origin is present and is not http://<host>, or when Sec-Fetch-Site is cross-site. Rebuild ui/.next-prod, then add a test that a cross-site text/plain POST through a handler gets 403. Until then, stop :3000 right after the owner's one-time migration. Consider a cap of 1–2 concurrent production training runs in ml_workspace.

## SECREL-02 [major] No off-machine dead-man signal: an 18-hour unclean outage on 24–25 Oct went unalerted, and HEALTHCHECK_PING_URL is undocumented and unset
- verify: REAL->major
- file: scripts/stack_watchdog.sh:341
- evidence: `last reboot shutdown`: reboot Sat 24 Oct 15:36, then the next reboot Sun 25 Oct 10:57 with no shutdown record between them. `pmset -g log` has entries up to 24 Oct 16:35 and nothing (no Sleep, Wake or Shutdown) until 'powerd process is started' at 25 Oct 10:57:46. The master-controller log at the 25 Oct start says 'controller was down since 2026-10-24T16:36:09 … missed: db_backup_daily: 1'. data/backups/duckdb has no market-20261025 backup. .logs/watchdog.log has nothing between 24 Oct 15:xx and 25 Oct 10:58. The only alert path is Telegram sent from the same Mac. In .env, `grep -c '^HEALTHCHECK_PING_URL=.+'` returns 0. The key is absent from .env.example and docs/RUNBOOK_RESTORE.md; the only mentions are in the watchdog header and an install_launch_agents.sh comment. No panic report exists, so the cause is unknown, and the 24 Oct service logs were truncated by the old start-local.sh.
- failure: The unattended Mac mini loses power or freezes on a trading-day afternoon. The 18:30 EOD pipeline, the 19:30 Desk paper run, the 19:50 S1 shadow and the 02:15 backup all silently miss. Nobody is told until someone walks up to the Mac, which is exactly what happened on 24–25 Oct (and on 16–19 Oct before it).
- fix: Owner action: create a free healthchecks.io check (2-min pings, period about 5 min, grace about 10 min) and set HEALTHCHECK_PING_URL in .env. The watchdog already pings it, and pings /fail when the stack is unhealthy. Repo side: add the key with a comment to .env.example; add it to RUNBOOK §2's key table and to 'What still needs a human'; have `./start-local.sh status` print a yellow 'dead-man: not configured' row; optionally send a weekly Telegram reminder while it is unset.

## SECREL-03 [minor] Values containing ' #', '${…}' or a leading quote pass validate_env_updates, are written raw, and python-dotenv reads them back differently at the next start (a leading quote swallows the keys that follow)
- verify: not verified (minor/nit)
- file: services/ui-api/icici_admin.py:128
- evidence: Scratch test with the real icici_admin plus dotenv_values. Every value below is accepted (env_value_problem returns None). ICICI_PASSWORD='Secret #2026' reads back as 'Secret'. 'Ab${HOME}9' reads back as 'Ab/Users/sudheer9' (interpolated). "'Quote1" reads back as None (key dropped). Two writes, ICICI_API_KEY='"abc' and then ICICI_SESSION_TOKEN='tok"', turn ICICI_API_KEY into a multi-line value that swallows TELEGRAM_BOT_TOKEN, REDIS_URL and ICICI_API_SECRET, so those keys disappear. persist_env_updates writes f'{key}={value}' unquoted (lines 128 and 132). The running process keeps the correct value (os.environ is set directly), so nothing looks wrong until a restart. Newline injection of EXECUTION_LIVE_ALLOWED is correctly blocked.
- failure: The owner saves an ICICI password containing ' #' or '${' on the Broker tab. It works until the next restart. Then the 08:00 unattended login uses a truncated or interpolated password, retries fail, and the ICICI account risks a lockout. Alternatively, a same-origin injection (terminal XSS, or a squatter per SECREL-04) sends a leading-quote value that makes .env drop TELEGRAM_BOT_TOKEN at the next start, so the watchdog's alerts go silent.
- fix: Always write KEY='value' (python-dotenv keeps single-quoted values literally: no interpolation and no comment stripping), and refuse a value that contains a single quote (or escape it inside double quotes with $ escaped). Add a round-trip test: for every value env_value_problem accepts, dotenv_values() of the written file returns it exactly; cover ' #', '${HOME}', leading and trailing quotes, and backslashes. The watchdog's env_val already strips surrounding quotes.

## SECREL-04 [minor] The trusted verdict is cached for 30 s and only gates new navigation, so a squatter that binds within one poll serves scripts to open terminal windows (which hold the IPC grant) for up to about 30 s
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/health.rs:837
- evidence: TrustCache::PASS_TTL = 30 s (health.rs:837/844). The cache is forgotten only when a poll sees ui down or a non-HTML root (health.rs:1056), and polls run every 5 s. trust.rs only answers 'who listens'. Nothing checks the requests an already-open window makes, and lazy page chunks and API fetches go to whoever holds 127.0.0.1:8010. Eviction needs a fresh Foreign verdict after the cache expires. README's residual-risk text covers only a sandboxed app running Homebrew python. Code review only; binding :8010 or launching the app is forbidden.
- failure: ui-api crashes. A same-user process waiting in a bind loop takes 127.0.0.1:8010 within milliseconds and answers /health 200 and / text/html, so no poll sees the port down and the cached Trusted verdict stands. During the next ~30 s, the owner switching tabs in an open window lazy-loads a chunk from the squatter. That chunk runs with __TAURI_INTERNALS__ and can call shell_notify, shell_open_external and shell_save_download. The real UI's API calls also go to the squatter, for example credential POSTs from BRKR.
- fix: Cheap: cache the trusted listener's pid and executable, and on every fast poll check only that pid (its socket fds via proc_pidfdinfo, plus proc_pidpath unchanged). Drop the cache when it no longer holds the port, or on any failed /health. Otherwise lower PASS_TTL to the poll interval. Document in desktop/README that open windows trust the port for up to one poll. The durable fix remains the ui-api↔shell shared secret (HMAC on /health) already named in PLAN §8.

## SECREL-05 [minor] A watchdog lock left by an unclean stop blocks every watchdog run for up to 20 min after boot, and the app reads the same lock as 'the watchdog is starting the stack' and hides Start
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:253
- evidence: The lock is a bare mkdir. It counts as stale only by age (`find -mmin +20`); neither its owner pid nor kern.boottime is checked. The EXIT trap does not run on SIGKILL or power loss, and bash defers it while a foreground `sleep 30` or `timeout 300 start-local.sh` runs, which is longer than launchd's 20 s exit timeout. Scratch run of the real script with a lock dated 3 min ago (boot 10:57, lock 15:59): exit 0, 0 watchdog.log lines, 0 start-local.sh calls. In the app, stack.rs:373 probe_files sets watchdog_running whenever the lock is younger than WATCHDOG_LOCK_STALE (20 min), again without a boot check. startup_phase then returns StartingReason::Watchdog, which hides Start/Stop. crash.rs already applies the 'older than kern.boottime' rule to run.json.
- failure: A power blip or forced restart happens while a watchdog run is starting or restarting a service (the unhealthy case, when runs last 30 s to minutes). The Mac is back and logged in within 2–3 min. Every watchdog run exits silently because of the fresh-looking lock, and the app shows 'The watchdog is starting the stack' with no Start. A Start from the tray only kickstarts the same blocked watchdog. The stack stays down for up to 20 min with no alert.
- fix: Write `$$` and the boot time into $LOCK/owner. Treat the lock as stale when that pid is dead or its boot time differs from kern.boottime (or the lock mtime is earlier than boot). Apply the same rule in stack.rs probe_files (lock mtime earlier than macos::boot_time_secs means not running). Add a test for each.

## SECREL-06 [minor] Only the instance launchd started is relaunched; after ⌘Q and a reopen from the Dock or Finder, the app runs unsupervised until the next login, while CLAUDE.md says it is 'relaunched after a crash'
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:1101
- evidence: KeepAlive{SuccessfulExit:false} applies to the job's process only. A manual launch runs outside the job. A later login-job start finds it via the /tmp socket and exits 0 (lib.rs:1101–1104), so the job stays 'not running' with a successful exit. desktop/README.md:79–94 and :351 admit 'only the login-job instance is relaunched'. CLAUDE.md:116 says 'relaunched after a crash, never after Quit' without qualification, and the RUNBOOK does not mention it. Live now, launchctl shows the job running as pid 83455 (runs = 1), so it is supervised today only because the PM started it through launchd.
- failure: The owner quits the app once (⌘Q) and reopens it from the Dock, which is normal desktop behaviour. A WebKit or plugin panic on a later trading day then kills it. Nothing relaunches it: the tray NIFTY, service-down notifications and ICICI-expiry banners are gone for the rest of the week. This is the C2-reliability-ops-12 scenario.
- fix: On a manual launch with Launch at Login on and the job loaded but not running, hand off to launchd: run `launchctl kickstart gui/<uid>/SuryaDhana` (bounded, through exec.rs) and exit, letting the job instance become primary (pass a 'focus' intent through, e.g. an env var or a marker file, so it shows its window). Otherwise warn in the tray. Fix CLAUDE.md:116 and add one line to RUNBOOK §5.

## SECREL-07 [minor] data-service and master-controller still serve /docs and /redoc, which load unpinned swagger-ui-dist@5 from jsDelivr with no SRI, on origins whose writes the guard admits (Origin == Host)
- verify: not verified (minor/nit)
- file: services/data-service/main.py:389
- evidence: Live: :8001 and :8008 /docs and /redoc return 200 (ui-api returns 404 after completeness-06). The pages load https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js and its CSS (a floating major version, no integrity attribute) and send no CSP or X-Frame-Options. http_guard admits unsafe requests whose Origin equals the request Host, so script on http://127.0.0.1:8001/docs can POST to any data-service route (e.g. /jobs/build-ml-dataset, the runtime-config ICICI keys), and on :8008 to /api/scheduler/autopilot or icici-refresh.
- failure: A compromised or hijacked swagger-ui-dist 5.x release on the CDN runs the next time the owner or an agent opens :8001/docs or :8008/docs. With same-origin write rights it toggles autopilot, triggers repeated ICICI logins, or starts the heavy dataset build (the 15 Oct OOM).
- fix: Mirror ui-api: docs_url/redoc_url None unless DATA_SERVICE_DOCS=1 or CONTROLLER_DOCS=1. Or serve get_swagger_ui_html with a pinned version and SRI, and add X-Frame-Options DENY.

## SECREL-08 [minor] The terminal's CSP restricts only framing, object and base; script and connect sources are open on the origin that holds the 9-command IPC grant
- verify: not verified (minor/nit)
- file: services/ui-api/static_ui.py:154
- evidence: Live response headers on / and on the browser-navigation 404: `content-security-policy: frame-ancestors 'none'; object-src 'none'; base-uri 'self'`, plus X-Frame-Options DENY, nosniff and Referrer-Policy same-origin. There is no script-src, connect-src or frame-src. FX-PY marked C2-security-09 fixed while stating that the strict policy was deferred by the PM. The only HTML sink in ui/ is a static CSS string (MLEngineWorkspace), so today's XSS exposure is low.
- failure: A future injection (a non-React sink for news or NSE text, or a malicious dependency) runs in the terminal origin unrestricted and calls shell_save_download, shell_open_external and shell_notify. That is the finding's original scenario, still unmitigated.
- fix: build_ui.sh hashes Next's inline bootstrap scripts into build-info. static_ui then emits script-src 'self' 'sha256-…'; connect-src 'self' ws://127.0.0.1:8010 ws://localhost:8010; frame-src https://s.tradingview.com https://*.tradingview.com; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'. Gate the change on a 42-page Chromium and WebKit audit with 0 CSP violations.

## SECREL-09 [minor] Each proxied request builds a new httpx.AsyncClient on the event loop: an SSL context plus a macOS SystemConfiguration proxy lookup every time
- verify: not verified (minor/nit)
- file: services/ui-api/routers/data_proxy.py:182
- evidence: The 15:39:40 loop_stall dump (the PM's SIGSTOP drill) caught the main thread in get_live_nifty_direct → httpx.AsyncClient.__init__ → _get_proxy_map → urllib.request.getproxies → getproxies_macosx_sysconf. Measured with the jupyter_env python: httpx.AsyncClient() takes 2.58 ms median, 3.51 ms p90 and 26 ms max of loop time per construction (2.34 ms with trust_env=False; the SSL context dominates). The pattern appears at 134 `httpx.AsyncClient(` call sites in ui-api routers. Every window's NIFTY and quote polls pay it. scripts/check_event_loop.py does not flag it.
- failure: With several windows, the tape and the WATCH page polling quotes, ui-api spends tens of ms per second of loop time building clients, and gets no keep-alive to data-service. A slow configd (network change, wake from sleep) stretches the synchronous SystemConfiguration call on the loop: /health latency rises and the app's 5 s hung detector and the watchdog's 8 s probe get closer to a false 'not responding'.
- fix: Use one module-level httpx.AsyncClient per loopback upstream (data-service, master-controller), created in the lifespan with trust_env=False and sensible limits, reused by every route and closed at shutdown. Teach check_event_loop.py to flag `httpx.AsyncClient(` inside request handlers.

## SECREL-10 [nit] The single-instance socket sits at a fixed, predictable path in world-writable /tmp, and the owner of an existing socket file is never checked
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/instance.rs:37
- evidence: The live log shows 'single-instance lock /tmp/ai_suryadhana_terminal_si.sock'. claim_with() first connects to whatever listens at that path; on success it returns Secondary, and lib.rs then exits 0. Because /tmp has the sticky bit, a socket created there by another account can neither be removed nor out-raced by the owner's app.
- failure: Another local account (the C2-security-14 threat) binds /tmp/ai_suryadhana_terminal_si.sock with mode 0777. From then on, every SuryaDhana launch by the owner, including the login job, hands off and exits 0. launchd does not relaunch it, so the app silently never starts.
- fix: Move the socket into a per-user 0700 directory (~/Library/Application Support/ai.suryadhana.terminal/si.sock, or $TMPDIR). Before handing off on the legacy /tmp path, lstat it and require uid == getuid().

## SECREL-11 [nit] The desktop-app status row takes the first process named SuryaDhana, so it reported a self-test copy from desktop/target as the installed app
- verify: not verified (minor/nit)
- file: start-local.sh:794
- evidence: `./start-local.sh status` printed 'desktop-app 58496 running /Applications/SuryaDhana.app 1.0.0'. pid 58496 is …/desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app/… --self-test (started 16:03). The installed, launchd-supervised app is pid 83455 (`pgrep -x SuryaDhana | head -1`).
- failure: During troubleshooting the owner kills or samples the pid shown in status and hits a test copy. Or status shows 'running' while the installed app is actually down and only a test or build copy is alive.
- fix: Match on the executable path, e.g. ps -axo pid=,command= | awk '$2 == "/Applications/SuryaDhana.app/Contents/MacOS/SuryaDhana"' (or the ~/Applications variant). List any other SuryaDhana processes as 'other copies'.

## SECREL-12 [nit] Telegram /status still shows ui-api green when no UI release is served, and has no terminal-UI line
- verify: not verified (minor/nit)
- file: scripts/master_controller.py:1775
- evidence: _bot_status probes only data-service and ui-api /health, plus positions and setup-status. A grep finds no use of /ready or ui_build in master_controller.py. The watchdog's 6-hourly missing-release Telegram covers part of this.
- failure: Away from the Mac after a restore or a stray rm of ui/dist, the owner sends /status and sees everything green, while the app and the browser show 'UI build not found'.
- fix: Add one line from GET {UI_API}/ready: 'terminal UI <ui_build_id>' or '🔴 terminal UI MISSING: ./start-local.sh build-ui (or --rollback)'.

## SECREL-13 [nit] Every Broker-tab save recreates .env with mode 0644, undoing an owner's chmod 600
- verify: not verified (minor/nit)
- file: services/ui-api/icici_admin.py:135
- evidence: Live .env is -rw-r--r-- (C2-security-14 is still open). Scratch: a test .env at 0600, then persist_env_updates({'ICICI_API_KEY':'new'}), leaves it at 0o644. tmp.write_text plus replace() creates a new inode with the umask default.
- failure: The owner hardens .env to 0600. The next credential or session-token save makes ICICI_API_KEY/SECRET/PASSWORD and TELEGRAM_BOT_TOKEN readable by the staff group again.
- fix: Create the temp file with os.open(tmp, O_WRONLY|O_CREAT|O_TRUNC, 0o600) (or copy the original's mode) before replace(). chmod 600 .env once and add a test.

### claimed fixed but not
- C2-security-01 (FX-PY: fixed): closed for direct access to :8010, :8001 and :8008, but not through the optional :3000 server. Its 6 Next route handlers (unchanged since 13 Jun; the live ui/.next-prod built 25 Oct 11:44 contains them) re-send requests without Origin, Sec-Fetch-Site or X-Forwarded-Host. Live: a rebinding Host gets 400 on /api/health but 200 on /api/telemetry/logs/stream. Scratch: a cross-site text/plain POST gets 403 directly and 200 through a route.ts replica. The round-1 adversarial check's 'not really fixed' item was never taken into wave 2 (SECREL-01).
- C2-security-09 (FX-PY: fixed): the CSP is only frame-ancestors / object-src / base-uri, with no script-src or connect-src. The finding's failure scenario (an injected script calling the 9 IPC commands) is unmitigated; the strict policy was deferred (SECREL-08).
- C2-security-04 (W2-RUST: fixed): partial. Beyond the documented residual risk (a sandboxed app running Homebrew python), the 30 s trusted-verdict cache and the lack of checks on what open windows load let a squatter that binds within one poll run scripts in trusted windows (SECREL-04).
- C2-reliability-ops-12 / C1-desktop-native-13 (FX-RUST: fixed): crash relaunch covers only the instance launchd started. Any copy reopened by hand after ⌘Q is unsupervised until the next login, while CLAUDE.md:116 says 'relaunched after a crash' without qualification (SECREL-06).
- C2-reliability-ops-04 (FX-RUST: fixed for the app side; FX-OPS: partial): Telegram /status still has no terminal-UI release line and shows ui-api green with no release (SECREL-12).
### not checked
- No browser was used (per the brief). CSP behaviour, the TradingView iframe sandbox and the WebKit download path were not re-exercised in a browser.
- No real cross-site write was sent to the live stack. The :3000 POST bypass was reproduced in scratch with the real shared/http_guard.py and a Node copy of route.ts; the live evidence is GET-only.
- The app was not launched and :8010 was not bound, so SECREL-04 (trust cache and checks on open-window loads) and SECREL-10 (/tmp socket squat) are from code review.
- The watchdog's hung-restart path was not exercised live (there was no hang). Only the stale-lock silent exit was run, on a scratch copy.
- The first nightly settings-store backup (02:15 on 26 Oct) has not run yet. db_backup.backup_prefs was reviewed as code only.
- The release rollback (build-ui --rollback) and build_desktop.sh --rollback were not executed: they would modify ui/dist or /Applications.
- Tailscale Serve and the remote read-only behaviour are untested (Tailscale is not installed).
- Root cause of the 24 Oct ~16:35 to 25 Oct 10:57 outage: there is no panic report, and the 24 Oct service logs were truncated by the pre-fix start-local.sh.
- The app's idle CPU (2.6% now vs 0.79% for the morning build) was not investigated (outside this brief).
- cargo, node and pytest suites were not re-run (the PM reports them green); I ran no build that would write into the repo.

# R-API — SHIP-WITH-FIXES

I reviewed the W2-API diff against the 13:59 snapshot (W2-API/orig) and tested the risky paths in scratch. There are no blockers. The hang fix holds.

- **Monitor hub, loop safety:** I instrumented every redis-py Connection method (connect, send_packed_command, read_response, can_read, on_connect, disconnect) under a real uvicorn on a scratch port. Over 200-socket churn, a Redis restart, a slow-client flood, the cap test and a hung-Redis test, 0 of about 40,000 calls ran on the loop thread. Redis calls ran only in the asyncio worker, in the redis-quotes-hub reader, and once by GC inside the fake server's thread (a disconnect).
- **Monitor hub, other paths:** reconnect took 2.02 s and the open socket resumed. In the stop-window race the quote was delivered exactly once. A client that never reads stays bounded (queue 256, 19,028 dropped, RSS +2.7 MB). The cap refuses with 403 and the counter returns to 0. /health stayed at or under 8.6 ms in every run.
- **Negative control:** I re-ran test_monitor_churn.py against the round-1 monitor.py. It still fails (3 x /health TimeoutError after 2.00 s), so the test catches the original bug.
- **Gates:** ui-api suite 806 passed; churn + hub + watchdog 19 passed, three times in a row. scripts/check_event_loop.py reports 0 findings. Ruff shows 5 leftover BLE001/S112 in monitor.py (W2-API reports 11 -> 5).
- **Features explorer:** an independent equivalence run on both real matrices (lower-case, unknown and missing tickers; bogus sort columns and directions; middle, last and past-the-end pages) found 0 differences in 64 cases. In-place and atomic rewrites invalidate the cache correctly. Caches are bounded by LRU.
- **Gzip:** streams, SSE, FileResponse/ETag, 206 and non-/api paths pass through untouched. Content-Length and Vary are correct. Live check: 934,658 B -> 113,235 B.
- **Watchdog:** costs about 0.04% CPU when idle (0.0009% without it). SIGUSR1 dumps all stacks and the process survives.
- **/docs, /redoc, oauth2-redirect:** all 404 live; /openapi.json is 200.
- **testserver Host:** returns 400 on :8001, :8008 and :8010, and all three processes started after the last code change.
- **PYTEST_CURRENT_TEST:** I found no way for it to reach a production service. .env writes refuse PYTEST_*, the ops shell tests use a minimal environment, and no service is started from pytest with an inherited environment.

What remains is minor:
1. With a hung Redis, sockets joining at the same time wait one after another (the k-th waits k x 10 s).
2. The K2 migration block is written by any non-provisional import, not only one from :3000.
3. A tailnet client counts as remote (read-only) only if the proxy adds X-Forwarded-For.
4. The .env validator still lets quote characters through, and python-dotenv then drops or swallows lines at the next start.
5. A loop_stall report after a whole-process suspend is indistinguishable from a real stall. The 15:40:29 IST entry in the live log is the PM's SIGSTOP drill: first reported 48.5 s in, and its dump points at an innocent frame.
6. The client-errors masking misses JSON-style and colon-style secrets.

Nits: raw U+2028/U+0085 in client-error log lines, a non-object JSON message on the monitor socket crashes that socket's handler, a tiny TOCTOU window in the DEXP file signature, a silent fallback to the slow DEXP path, and test-mode detection that a child process can inherit.

## RAPI-01 [minor] With a hung Redis (TCP accepted, no reply), concurrent monitor joins wait one after another behind the hub lock: the k-th socket waits k x 10 s
- verify: not verified (minor/nit)
- file: services/ui-api/routers/monitor.py:290
- evidence: Scratch hung_hub.py: a listener that accepts and never answers, 4 sockets opened at once against a real uvicorn. Each socket's wait for redis_unavailable: 10.0 s, 20.0 s and 30.0 s. The 4th socket got nothing and was closed by the server's WebSocket ping timeout at 40.0 s (my raw client does not answer pings). /health max 8.6 ms, so the loop itself is safe. Cause: _ensure_running holds self._lock across asyncio.to_thread(_open_quotes_pubsub), and each waiter makes its own attempt. Each attempt blocks 10 s in CLIENT SETINFO / PING because the pool uses socket_timeout=READ_STALL_S (measured with hung_open.py: connect -> on_connect -> read_response 10.0 s). The _reconnect task competes for the same lock.
- failure: Redis wedged (SIGSTOP, swap storm, a long blocking command) while the owner has 3-4 windows open or reloads them. Each window's socket stays open but silent for up to N x 10 s before it learns redis_unavailable. Every waiting handler holds a _ws_active slot, so clients that reconnect while waiting can push sockets toward the cap of 32.
- fix: Make the connect single-flight: the first joiner creates one shared future and every other joiner awaits it, so all of them fail at 10 s. Remember a failed attempt for the current backoff step and fail later joins immediately. Use a short socket_timeout (2-3 s) for the handshake and PING, then set READ_STALL_S on the connection once subscribed. Add a test with a never-answering server and 4 concurrent sockets: all must get redis_unavailable within about 10 s.

## RAPI-02 [minor] The migration block is written by the first non-provisional import from ANY origin; the backfill and the UI's own rule only count port-3000 origins
- verify: not verified (minor/nit)
- file: services/ui-api/routers/prefs.py:485
- evidence: Scratch store (PREFS_DB in scratch), mirroring the live state, which has one provisional suryadhana.watchlist from http://127.0.0.1:8010. I ran import_items({...watchlist: '[]'}, 'http://127.0.0.1:8010', provisional=False). Result: migration() = {legacy_import_at: <now>, legacy_origin: 'http://127.0.0.1:8010', legacy_keys: 1, inferred: False}. A later :3000 import of the real watchlist came back skipped, and the server value stayed []. ui/lib/prefs/migration.ts migrationNoticeState returns 'imported' as soon as legacyImport.at != null; the caller then stores the local 'imported' marker and the notice never returns. The backfill (_ensure_meta, line 282) filters with is_legacy_browser_origin. The live writer at lines 485-490 checks only `not provisional and valid`.
- failure: Any :8010 origin whose localStorage held SYNC keys before its sync code first ran sends a LEGACY import. Examples: the WKWebView store of an earlier app build, or a browser tab on http://localhost:8010, which is a different origin from 127.0.0.1:8010. The server then records 'migrated from http://127.0.0.1:8010'. The app hides the 'open http://localhost:3000 once' notice for good, the owner never migrates, and his real watchlist and pins stay only in the old browser. If he does open :3000 later, its import is skipped because the key is no longer provisional.
- fix: Write the block only when is_legacy_browser_origin(origin) is true, the same rule as the backfill and isLegacyBrowserOrigin. Also make migrationNoticeState treat legacyImport.at as proof only when isLegacyBrowserOrigin(legacyImport.origin). Add a test: a non-provisional import from :8010 leaves NO_MIGRATION. Separately, consider whether a non-3000 legacy import should replace a provisional value at all; that is the pre-existing merge design.

## RAPI-03 [minor] Tailnet read-only depends only on the proxy adding X-Forwarded-For; a proxy path without XFF gives remote devices full write access
- verify: not verified (minor/nit)
- file: shared/http_guard.py:349
- evidence: I called evaluate() with GUARD_ALLOWED_HOSTS=mac.tailnet-x.ts.net, Host mac.tailnet-x.ts.net, Origin https://mac.tailnet-x.ts.net and peer 127.0.0.1. With X-Forwarded-For 100.101.102.103 the POST gets 403 remote_write. Without XFF the POST is allowed. Host mac.tailnet-x.ts.net:8010 with Origin http://...:8010 and no XFF is also allowed, because a bare name in the allowlist matches any port. _client_is_local (line 238) looks only at the socket peer, which is always loopback behind a local proxy, and at XFF.
- failure: The owner (or a later runbook) exposes ui-api through a forwarder that does not add XFF, for example `tailscale serve --tcp`, an ssh -R forward, or another local reverse proxy. A tailnet device then counts as local and can place paper orders, rewrite ICICI credentials and re-enable the Desk without GUARD_ALLOW_REMOTE_WRITES=1. The documented `tailscale serve --bg 8010` does set XFF according to W2-API and RUNBOOK section 7 (I could not test Tailscale itself), so this is defence in depth.
- fix: Count a request as REMOTE also when its Host, or any X-Forwarded-Host entry, is not one of the loopback default names (127.0.0.1, localhost, [::1]). The browser's Host is authoritative, and local callers (terminal, desktop shell, scripts, the Next :3000 rewrite) always use loopback names. Keep the peer and XFF checks as extra signals. Add a test for the no-XFF ts.net write.

## RAPI-04 [minor] The .env validator still lets quote characters through; python-dotenv then swallows or drops lines when the file is next read
- verify: not verified (minor/nit)
- file: services/ui-api/icici_admin.py:128
- evidence: Scratch fake .env, using the real persist_env_updates with allowed_keys=ICICI_ENV_KEYS:
- {ICICI_SESSION_TOKEN: '"', ICICI_PASSWORD: 'x"'} -> dotenv_values gives ICICI_SESSION_TOKEN='\nEXECUTION_LIVE_ALLOWED=0\nICICI_PASSWORD=x'. The EXECUTION_LIVE_ALLOWED line and the password key vanish.
- '"abc' -> 'could not parse statement'; the token key is dropped entirely.
- 'abc #x' -> stored as 'abc'.
- '${EXECUTION_LIVE_ALLOWED}' -> interpolated to ''.
env_value_problem (line 78) refuses only control and format characters, and the line is written raw as f"{key}={value}". In the real .env (key names checked, values not printed), the writable ICICI lines are 15-20 and no quote appears after line 20. So today two quoted fields can only bracket ICICI lines.
- failure: A pasted password or token that starts with a quote, or contains ' #' or '${', is saved and works in the running process (os.environ), then is silently corrupted or lost at the next ui-api or master-controller start, breaking the broker login. A local page with write access (XSS) can make whole lines between two of its values disappear. 'No line can be injected' holds; 'other keys cannot be changed' does not in general.
- fix: Write values in a form python-dotenv reads back exactly: single-quoted with \\ and \' escaped, or refuse " ' \ # $. Before the atomic rename, re-parse the temp file with dotenv_values. Refuse the write unless parsed[key] == value for every update and every other key's parsed value is unchanged. Add those cases to test_env_injection.py.

## RAPI-05 [minor] A stall while the whole process was frozen (SIGSTOP, GIL held, suspension) is reported after the fact like a real stall, and its stack dump blames an innocent frame
- verify: not verified (minor/nit)
- file: services/ui-api/routers/_loop_watchdog.py:129
- evidence: Live .logs/ui-api.log line 64685 (pid 81132, 10:10:29 UTC = 15:40:29 IST, the PM's SIGSTOP drill): loop_stall stalled_s 48.54, first reported at 48.5 s instead of 5 s because the watcher thread was frozen too, then loop_stall_recovered 49.04 half a second later. In the dump, the main thread is in routers/data_proxy.py:182 get_live_nifty_direct -> httpx.AsyncClient.__init__ -> urllib getproxies_macosx_sysconf. That is simply where the loop was after SIGCONT. Nothing in the record says the dump was taken after the stall ended.
- failure: Someone triaging later (owner, watchdog hang capture, a review agent) reads this as 'the loop blocked 48 s in get_live_nifty_direct / getproxies' and chases the wrong cause. The same happens for any stall in which the watcher cannot run (a C extension holding the GIL, process suspension).
- fix: In _watch, remember the previous wake time. If now - previous_wake > check_s + stall_s, the watcher itself did not run. Log the stall with post_hoc=true and watcher_gap_s, and either skip the dump or label it 'taken after the stall ended'. Add a test that freezes the watcher (or simulates the gap). Note in the hand-off that the 15:40:29 entry is the drill.

## RAPI-06 [minor] Credential masking covers only key=value and Bearer; JSON-style, colon-style and Basic-auth secrets are logged verbatim
- verify: not verified (minor/nit)
- file: services/ui-api/routers/client_errors.py:53
- evidence: Scratch app (real router plus guard, ASGITransport, peer 127.0.0.1) posting these messages:
- 'fetch failed {"apisession": "S3CR3T-123456", "session_token":"TKN-abcdef"}'
- 'Authorization: Basic dXNlcjpwYXNz api_key: AKIA1234567890'
Both were logged unchanged. The ?apisession= query form and the ?token= form in a stack were masked as designed. _SECRET_RE requires '=' after the name.
- failure: A UI error that embeds a request or response body puts the ICICI session token or API key in .logs/ui-api.log in clear text. For example, the Broker tab could throw Error(JSON.stringify(body)) with the session-token POST body, or with a response that echoes credentials. That log is copied into .logs/hangs/ captures and quoted in review reports.
- fix: Extend the pattern to quoted and colon forms, e.g. (?i)(["']?[a-z0-9_]*(?:api_?key|apisession|api_session|token|secret|password|passwd)["']?\s*[:=]\s*)(["']?)[^"'\s,&}]+ replaced with \1\2<redacted>. Add (?i)\bauthorization\s*:\s*\S+\s+\S+ and (?i)\bbasic\s+[A-Za-z0-9+/=]{8,}. Add tests for JSON and colon forms.

## RAPI-07 [nit] Raw U+2028/U+2029/U+0085 survive _clean_text and ensure_ascii=False, so one record splits into several lines for splitlines() readers
- verify: not verified (minor/nit)
- file: services/ui-api/routers/client_errors.py:113
- evidence: Scratch: messages containing  {"event": "loop_stall", "forged": true} and \x85FORGED were logged raw. 7 records = 7 lines by '\n' but 9 by str.splitlines(). icici_admin already treats Zl/Zp/C1 as line breaks for .env. I found no programmatic reader of ui-api.log today.
- failure: A future log tool that uses splitlines() (Python's default for text munging) sees broken JSON records, or a forged record fragment produced by a page's error text.
- fix: Reuse icici_admin's character-category filter (Cc, Cf, Zl, Zp) in _clean_text, keeping \n and \t only in stack, or log with ensure_ascii=True.

## RAPI-08 [nit] A non-object JSON message, or non-string symbols, raises AttributeError out of the handler (traceback in the log, close 1011)
- verify: not verified (minor/nit)
- file: services/ui-api/routers/monitor.py:445
- evidence: payload.get('action') runs on whatever json.loads returned ([1], "x", 5), and {s.upper() for s in syms} runs on any list. Only WebSocketDisconnect is caught. Cleanup is correct (the finally releases manager, sender and hub entries; ws_monitor releases the slot), and this behaviour already existed in round 1. Read-only tailnet clients may open WebSockets.
- failure: A buggy or hostile client, including a read-only tailnet device, can write 'Exception in ASGI application' tracebacks into .logs/ui-api.log at will.
- fix: Use `if not isinstance(payload, dict): continue`. Keep only string symbols (e.g. `{s.upper() for s in syms if isinstance(s, str)}`) and cap the list length (e.g. 500). Answer unknown shapes with {error: 'bad_message'}.

## RAPI-09 [nit] The file signature is taken from the path after the file was opened, and builds re-read by path: a rebuild landing in between can cache mixed old/new data under the new signature
- verify: not verified (minor/nit)
- file: services/ui-api/routers/_features_explorer.py:220
- evidence: page() opens pq.ParquetFile(src) at line 201, then file_signature(src) runs os.stat on the path at line 220. _get_base and _get_order read ticker, date and the sort column through pd.read_parquet(path) (lines 269 and 312), while null counts and page rows come through the already-open pf. Writers replace the file atomically (data-service ml_dataset.py:54 os.replace). My invalidation test (in-place rewrite and atomic replace between requests) passed. This race is a microsecond window.
- failure: A Phase-3 rebuild replaces computed_features.parquet exactly between the open and the stat. The page cache then stores rows from the old file, ordered by the new file, under the new signature, and keeps serving them until LRU eviction.
- fix: Derive the signature from os.fstat on the opened file (or stat before and after and retry if they differ), and read every column through the same ParquetFile.

## RAPI-10 [nit] The fallback to the slow full-file path is silent (only a stats counter)
- verify: not verified (minor/nit)
- file: services/ui-api/routers/_features_explorer.py:218
- evidence: Any file whose pandas metadata lists index_columns, including the default RangeIndex metadata written by df.to_parquet() without index=False, takes legacy_page: 0.8 s and about 830 MB per click. Today both matrices have index_columns=[] (footer checked), and both writers use index=False.
- failure: A future writer drops index=False. DEXP silently returns to whole-file reads per click (the RSS growth seen in round 1) with nothing in the log.
- fix: Log one JSON WARNING per file signature when falling back, with the reason (no ticker/date, or index_columns). Optionally treat a 'range' index entry as row numbers.

## RAPI-11 [nit] Test-mode detection relies only on an inheritable environment variable
- verify: not verified (minor/nit)
- file: shared/http_guard.py:427
- evidence: in_test_mode() checks only os.environ['PYTEST_CURRENT_TEST'], per request. Any process started from inside a test with the parent's environment keeps test mode for its whole life: Host testserver and peer testclient are accepted. I found no current path into production: .env writes refuse PYTEST_* (icici_admin PROTECTED_ENV_PREFIXES), scripts/tests/test_ops_shell.py and tests/integration/test_desktop_ops.py run shell scripts with a minimal environment, and scripts/desktop_qa/scratch_server.py (spawned with inherited environment) installs no guard.
- failure: A future integration test that runs `./start-local.sh restart ui-api` with subprocess.run(..., env=None) leaves a production ui-api that admits Host: testserver until its next restart.
- fix: Also require 'pytest' in sys.modules (a uvicorn- or launchd-started service never imports it). Log a WARNING at HostOriginGuard init when test mode is active.

### claimed fixed but not

### not checked
- Tailscale Serve's actual X-Forwarded-For behaviour (not installed or used here); RAPI-03 reasons from the guard code and the runbook.
- Behaviour against the live Redis or the live :8010 monitor socket. I used only the RESP stand-in and never-answering listeners on scratch ports; on the live stack I made GET requests only.
- HEAD semantics of gzip on the real app (FastAPI GET routes answer HEAD with 405, which is pre-existing).
- The UI-side reporters of client errors and the UI migration-notice flow in a browser (no browser per my brief); RAPI-02 is shown on the server store plus a reading of migration.ts.
- Why the SuryaDhana.app CPU went from 0.79% to 2.6% (an app/Rust question outside R-API's scope; ui-api's watchdog accounts for about 0.04%).
- data-service and master-controller beyond the testserver Host check and process start times.
- The PAPER-ONLY startup guard and execution paths (not part of the W2-API diff).

# R-OPS — SHIP-WITH-FIXES

I reviewed the W2-OPS diff and its follow-up and found no blockers. The hang restart does what it claims. I ran tests/integration/test_desktop_ops.py (53 passed) and scripts/tests/test_ops_shell.py (19 passed). `bash -n` passes under /bin/bash 3.2.57 on both scripts. The ownership pattern matches the real live listeners on 8001, 8008 and 8010, all `Python -m uvicorn <app> --host 127.0.0.1 --port <p> --timeout-graceful-shutdown …`. The login regex works against real processes. `./start-local.sh status` is read-only, takes 0.47 s live, and its rows are correct.

Today's .logs/watchdog.log has only the 14:42 and 14:45 ui-api "already running / FAILED to start" pairs and the 14:48 deferral. There has been no hang capture since the new script went live at 15:16, and no false "listening but unhealthy" event for data-service in any run since 19 Oct, across about five EOD pipelines.

Your question: can it restart data-service mid-pipeline outside the freeze windows? In principle yes, because the hang test ignores CPU use and running jobs. In practice it is unlikely. data-service's /health is an async handler that never touches DuckDB (main.py:427), and every job runs in a worker thread (jobs.py:68). The event-loop scan is also clean on master_controller.py. So a restart needs about 3 minutes of real event-loop or GIL starvation (5 failed 8-s probes), not just a slow DuckDB job.

The weak spots are in the restart policy:
- The ICICI-login deferral blocks every service, has no time limit, and also matches the interactive icici_session_helper.py waiting at its `input()` prompt. Reproduced with real pgrep.
- There is no backoff: a service that stays wedged is restarted every ~4 min indefinitely.
- A "restart FAILED" alert is silenced by an earlier "restarted" alert, because both use the same 30-min throttle key. Reproduced.
- Right before restarting, it does not re-check a paused marker or a concurrent start-local.sh, and the restart clears the marker. Reproduced. The app's Stop Stack button and the boot page's "restart it now" line make this race reachable.
- Ownership is checked on the first listener only, while the restart kills every listener on the port. The probe also goes to `localhost`, which tries IPv6 first. Reproduced: a foreign [::1] server answered 404 for a hung 127.0.0.1 service.
- The capture gets no Python stacks for data-service or master-controller, and it does not use ui-api's SIGUSR1 faulthandler hook.

QA tooling regression: the scratch_server X-Forwarded-Host change means a scratch server started with default flags (backend = live :8010, no --block-mutations) now passes the live guard for same-origin writes. Before the change the guard refused them. Also, no shared QA browser context mocks WebSockets.

What checks out:
- I re-ran the baseline tools into scratch: all 8 checks true, MANIFEST.sha256 and diff_vs_snapshot.patch byte-identical.
- The contract tests now fail instead of skipping, and the CI drift test passes.

Side observation, outside my brief: at 15:40 IST (10:10:29Z) ui-api logged a 48.5 s loop stall. The main thread was in `httpx.AsyncClient()` → `getproxies_macosx_sysconf` (routers/data_proxy.py:182). It most likely coincides with the PM's SIGSTOP drill; R-API should confirm.

## R-OPS-01 [minor] ICICI-login deferral blocks hang restarts of all services with no time limit, and matches the interactive manual helper
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:179
- evidence: LOGIN_RX (line 113) matches any `python … icici_session_helper.py`. scripts/icici_session_helper.py:87 waits on input() forever, writes only .env, and is neither a child of master-controller nor dependent on its Telegram poller. handle_hung checks login_running for every service, ui-api included (lines 179-183), and the deferral has no cap. Reproduced in scratch (wd4) with the real login_running()/pgrep and a `python scripts/icici_session_helper.py` stand-in: `ui-api hung (2..4 checks) while an ICICI login runs: restart deferred`, zero restart calls.
- failure: The owner runs the manual helper at 08:30, the ICICI page fails, and the prompt stays open in a Terminal tab. At 11:00 ui-api hangs the way it did at 14:40. The watchdog never restarts it, or any other hung service, for the rest of the day, and only sends 'An ICICI login is in progress' every 15 min.
- fix: Defer only master-controller, and only for a daily_session_refresh.py whose ancestor is the master-controller pid. Never defer ui-api or data-service. Cap the deferral at the controller's own 480 s timeout plus a margin (e.g. 10 min), then restart and alert.

## R-OPS-02 [minor] No backoff or cap on hang restarts: a service that stays wedged is restarted every ~4-5 min indefinitely
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:163
- evidence: By design the count resets after every attempt (line 163 comment, line 198), so a service that stays hung is restarted every HANG_RUNS runs. Simulation in scratch (wd3), with a persistent HTTP 503 from data-service: 24 runs (~48 min) gave 12 `restart data-service` calls and 1 alert. Each master-controller start also sends 'SuryaDhana Online' (master_controller.py:2153), schedules a start-up ICICI session check on trading days (2112-2119) and a downtime catch-up (2137-2145). Only the newest 10 captures are kept (HANG_KEEP), so the first hang's diagnostics are pruned after ~10 cycles.
- failure: A cause that comes back on start, e.g. a wedged Redis that accepts TCP but never replies, blocks data-service's poller `redis_client.ping()` on the loop. That gives a restart loop every ~4-5 min that kills each in-flight data job outside the freeze windows. For master-controller, it also spams Telegram and repeats the start-up login checks. The first, most useful capture is gone within the hour.
- fix: Add per-service backoff: after N (e.g. 3) hang restarts in 60 min, switch to alert-only until a manual `start-local.sh restart` or a healthy run clears the state, or double the required runs after each attempt. Never prune the first capture of a storm (or any capture younger than 24 h).

## R-OPS-03 [minor] A 'restart FAILED' alert is silenced by an earlier 'restarted' alert (same 30-min throttle key)
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:206
- evidence: The success alert (line 202) and the failure alert (line 206) both use `throttled "hang-$svc" 30`. Reproduced in scratch (wd): a successful hang restart, then a hung run whose restart fails. The log has `ui-api restart after a hang FAILED` but no `alert:` line after it. The follow-up summary says 'a failed restart gets its own alert'. The stack-down summary alert does not include hang failures either (lines 313-324).
- failure: At 10:00 the owner gets 'ui-api was hung … restarted'. The new instance wedges again and its restart at 10:08 fails, leaving it listening but unresponsive. For up to 30 min the owner's last message says 'restarted' while the terminal is down.
- fix: Use separate keys (hang-ok-$svc, hang-fail-$svc), and never let an OK alert throttle a following FAILED one. Optionally add hang failures to the stack-down summary alert.

## R-OPS-04 [minor] No re-check of paused marker / concurrent start-local.sh / unchanged listener right before the hang restart; restart clears the owner's pause
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:200
- evidence: Paused markers and start_local_running are checked only in candidates() and once after the debounce (lines 220-228, 261). There are ~13 s between that check and `start-local.sh restart` (final probe up to 8 s, then capture: sample 3 s, lsof, tail), or minutes if dead services are started first. start-local.sh:895 `restart` calls clear_paused. Reproduced in scratch (wd2): .pids/paused/ui-api plus a running start-local.sh before the second handle_hung, and the watchdog still ran `restart ui-api` and the marker was gone. The app makes this reachable: Stop Stack runs `start-local.sh stop` (desktop/src-tauri/src/stack.rs:154-157), and the boot page says 'To restart it now: ./start-local.sh restart ui-api' while the watchdog is counting (desktop/boot/boot.js:187-191).
- failure: The owner sees NOT RESPONDING and clicks Stop Stack to restore DuckDB per RUNBOOK_RESTORE. The watchdog, already in its capture step, then restarts data-service on the half-copied file and clears the paused marker. Or the owner runs the suggested manual restart and the two restarts race, so one kills the other's new instance and a false '🔴 restart FAILED' is sent.
- fix: Immediately before `start-local.sh restart`, re-check: `[ -f .pids/paused/$svc ]`, `start_local_running`, and listener_pids unchanged since the capture. If any check fails, log 'skipped: stopped/restarted by hand' and clear the count.

## R-OPS-05 [minor] Ownership is checked on the first listener only, but the restart kills every listener; and the probe uses localhost (IPv6-first) while the service binds 127.0.0.1
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:271
- evidence: main() classifies using `listener_pid` (lowest pid, line 82) and listener_is_ours on that pid only. start-local.sh stop_one (line 441) then kills every LISTEN pid on the port. health_url uses http://localhost:<port> (lines 66-69), but services bind 127.0.0.1 only (start-local.sh:285). Reproduced in scratch (wd5, ephemeral port): a hung 'uvicorn … <P>' listener on 127.0.0.1 and a foreign IPv6 HTTP server on [::1]:P. health_code via localhost returned 404 (the foreign server), 127.0.0.1 returned 000. listener_pids listed both, and the first (ours) decided 'hung'.
- failure: A dev server (Node binds [::] by default) or another tool listens on [::1]:8010. The watchdog reads its 404 as 'ui-api answered HTTP 404', restarts ui-api every ~4 min, and start-local.sh kills the foreign program too. This breaks the documented 'a port held by another program is never stopped'. If the foreign pid is the lower one, a truly hung ui-api is never restarted.
- fix: Probe http://127.0.0.1:<port>/health, the address the services bind. Take the hang path only when every listener pid is ours; otherwise use the foreign path.

## R-OPS-06 [minor] The hang test does not tell a busy service from a wedged one; data-service and master-controller can be restarted mid-job outside the freeze windows
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:164
- evidence: The decision is only 5 failed 8-s /health probes over ~2.5-3 min (two runs, plus the final probe). The %CPU captured in summary.txt is never used, and running jobs are not considered. The 14:40 wedge was at 0% CPU. A loop starved by a GIL-holding job thread or memory thrash would show high CPU. These run outside 07:45-09:20 and 18:30-21:15: startup_catchup re-runs the EOD pipeline at any hour after an outage (master_controller.py:2137-2145), Saturday 09:00/10:00 jobs (2025-2029, 2088-2096), the 02:15 backup (a child of the controller, killed by the tree stop), and manual PIPE job triggers. Mitigating evidence: data-service /health is async and DB-free (services/data-service/main.py:427-431), jobs run in threads (jobs.py:68), the controller passes check_event_loop.py, and watchdog.log since 19 Oct has no false listening-but-unhealthy event for data-service.
- failure: On a Saturday-morning catch-up after an outage, a long ML-dataset phase holds the GIL (large DuckDB→pandas conversions) or the Mac thrashes swap. /health misses 8 s five times over ~3 min, and the watchdog kills data-service mid-upsert (SIGKILL after 20 s, no CHECKPOINT). The catch-up is lost and the controller alerts 'EOD Data Pipeline FAILED'.
- fix: For data-service and master-controller, sample the listener's %CPU twice (ps -o pcpu=). If it is busy (e.g. >50%), log 'busy, not hung', alert once, and require many more runs (e.g. 8, ~16 min) before restarting. Optionally write a job-in-progress marker file that the watchdog respects outside the freeze windows.

## R-OPS-07 [minor] The capture gets no Python stacks for data-service or master-controller, and does not use ui-api's SIGUSR1 faulthandler hook
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:123
- evidence: capture_hang collects only `/usr/bin/sample` (C frames, i.e. _PyEval_EvalFrameDefault), lsof and the log tail. W2-API's services/ui-api/routers/_loop_watchdog.py:165-170 registers faulthandler on SIGUSR1 (all-thread Python stacks, works while the loop is stuck), but capture_hang never sends it. grep shows faulthandler registered only in ui-api, not in data-service or master_controller.py. The follow-up's own open issue says the root cause of the next hang may stay unknown.
- failure: data-service or master-controller wedges. The capture shows only interpreter C frames, the restart wipes the evidence, and the root cause stays unknown, as with the 14:40 incident before W2-API's dump.
- fix: Register faulthandler on SIGUSR1 in data-service and master-controller (a shared helper). In capture_hang, `kill -USR1` each listener whose service registers it, before sample/tail, so the dump lands in log-tail.txt. Never send USR1 to an unregistered process (default action is terminate).

## R-OPS-08 [minor] After the X-Forwarded-Host change, a default-flag scratch server relays page writes to the live ui-api and they pass the guard
- verify: not verified (minor/nit)
- file: scripts/desktop_qa/scratch_server.py:71
- evidence: Defaults: --backend http://127.0.0.1:8010 (line 287), --block-mutations off (line 288). forward_headers now sets X-Forwarded-Host to the page's Host, so a same-origin POST passes shared/http_guard. test_scratch_proxy_same_origin_write_reaches_the_guarded_backend passes (200), while the fixer's negative control test_without_x_forwarded_host_the_guard_refuses_the_same_write shows the pre-change proxy got 403. The docstring (lines 18-19) still says 'Read-only by construction'.
- failure: An agent or a later QA run starts scratch_server without --block-mutations against the live stack. A page action (Desk re-enable, paper order, alert create, monitor subscribe) now mutates the live paper state. Before W2-OPS the live guard refused these.
- fix: Make --block-mutations the default whenever the backend is the live :8010 (add an explicit --allow-mutations), or add X-Forwarded-Host only under --allow-mutations / --prefs-db. Correct the docstring.

## R-OPS-09 [minor] The shared QA browser context does not mock WebSockets; parity, ui_audit, e2e_multiwin and delta_probe open live monitor sockets
- verify: not verified (minor/nit)
- file: scripts/desktop_qa/probe.py:106
- evidence: new_qa_context only installs the prefs-mode init script. Of the QA scripts, only scripts/desktop_qa/e2e_compare.py:69 calls route_web_socket; parity.py:177-178, ui_audit.py:62, e2e_multiwin.py:72/134/210 and delta_probe.py:137 do not. scratch_server relays /api WebSockets to the live backend by default (scratch_server.py:125,153). The 14:40 incident involved ~200 relayed connections on :8010, and this round's hard rule requires 0 live monitor sockets.
- failure: The final 42-page audit or a parity run opens a monitor WebSocket per page and per context against live ui-api. With wave 2's monitor hub this is cheaper, but the tools do not follow the rule the PM imposes by hand, and a regression in the hub would again load the live service.
- fix: In new_qa_context, call `ctx.route_web_socket(re.compile(r'.*'), <mock>)` by default, with an explicit opt-out flag. Make scratch_server refuse WS relaying to :8010 unless asked.

## R-OPS-10 [nit] status shows a garbage latency for a listener whose /health fails, which is exactly the hung case
- verify: not verified (minor/nit)
- file: start-local.sh:816
- evidence: curl -w prints '000 <time>' with no newline, then `|| echo '000 -'` adds to the same line, so t='<time>000 -'. Reproduced: the row prints `HTTP 000   0.000192000 -s`; for a timeout it would be `5.00xxxx000 -s`.
- failure: During a hang, the owner's first tool shows a confusing latency cell next to HTTP 000.
- fix: `read -r code t <<< "$(curl … ; true)"` and print '-' when code is 000, or use `|| true` and drop the echo.

## R-OPS-11 [nit] Hang count is not tied to the listener pid or to time
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:116
- evidence: .pids/watchdog/hung-<svc> stores only a number, with no pid and no mtime check. A count left before a Mac sleep, or by an instance the owner has since restarted, carries into the next run.
- failure: Count 1 at 01:58, then the Mac sleeps. After wake, one slow pair of probes against a different pid makes the count 2, and the service is restarted after a single real observation.
- fix: Store '<pid> <count>' and reset when the pid differs or the file is older than ~6 min (`find -mmin +6`).

## R-OPS-12 [nit] Hang-recovery timing is understated; Rust docstring is stale
- verify: not verified (minor/nit)
- file: docs/RUNBOOK_RESTORE.md:244
- evidence: From the code: next run up to 120 s after the hang starts; run 1 takes 8+30+8 s; run 2 starts 120 s later, then 8+30+8 s, a final 8 s probe and ~5-8 s capture. The restart therefore begins ~3.0-5.0 min after the hang starts, plus ~25 s for stop and start. The RUNBOOK says 'about 2.5–4.5 min'. desktop/src-tauri/src/health.rs:151-152 still says 'the watchdog never restarts a running service' (boot.js:187 was updated).
- failure: The owner waits the documented time, sees no recovery, and restarts by hand, which is the race in R-OPS-04.
- fix: Say 'about 3–5.5 min'. Update the health.rs NotResponding docstring.

## R-OPS-13 [nit] The committed reconstruction report lacks the three new checks the README now describes
- verify: not verified (minor/nit)
- file: reports/desktop_app/baseline_preprogram/reconstruct_report.json:1
- evidence: The committed report's checks list: d3_section2_pairs_match_doc, forward_replay_reproduces_snapshot, inventory_matches_0539Z_listing, pm_backup_equal_after_step1, untouched_files_predate_program. My scratch re-run (fx-qa/ui_start, --pm-backup desktop_integration_20261025-110448) gives exit 0 and adds records_pinned, touched_files_dated_at_their_last_record=true and pm_backup_mtimes_predate_program_or_match_records=true. MANIFEST.sha256 and diff_vs_snapshot.patch are byte-identical to the committed files.
- failure: An auditor reads the AC-3 evidence file and cannot see the drift checks that README lines 52-56 rely on.
- fix: Regenerate with --report-dir reports/desktop_app/baseline_preprogram (MANIFEST and patch are unchanged, as reproduced).

## R-OPS-14 [nit] .logs/ and .pids/ are not git-ignored, and the new hang captures land there, while the CI plan requires committing today's untracked trees
- verify: not verified (minor/nit)
- file: .gitignore:1
- evidence: `git check-ignore` returns 'NOT ignored' for .logs/x, .logs/hangs/x and .pids/x, and git status shows `?? .logs/` and `?? .pids/` (11 MB of logs). capture_hang writes sample, lsof and 200-line log-tail files under .logs/hangs. The W2-OPS deploy note says CI can only run once .github/, desktop/, ui/ and scripts/ are committed. Separately, ui/node_modules and ui/.next are partly tracked (pre-existing).
- failure: The owner runs `git add -A` to land the program for CI and commits service logs, process stack samples and open-file lists, plus pid and watchdog state.
- fix: Add `.logs/` and `.pids/` (and ui/.next/, ui/node_modules/) to .gitignore before the first program commit.

### claimed fixed but not
- W2-OPS-followup: 'a failed restart gets its own alert'. It does not within 30 min of a 'restarted' alert, because both use the throttle key hang-$svc (R-OPS-03, reproduced).
- W2-OPS-followup: 'A port held by another program … is never stopped'. Only the first listener pid is checked, while `start-local.sh restart` kills every listener on the port, and the localhost probe can be answered by a foreign IPv6 listener (R-OPS-05, reproduced).
- W2-OPS scratch_server docstring 'Read-only by construction for the audit'. With the X-Forwarded-Host change and default flags, same-origin writes now reach and pass the live guard (R-OPS-08).
### not checked
- ci.yml on a real GitHub runner: the macOS job's sudo-created canonical python path, availability of GNU timeout and /usr/bin/sample, Rust 1.94.1 and the static export, and Linux-only failures in the ubuntu suites.
- A real hang restart against the live stack (forbidden: no SIGSTOP or restart of live services). Hang behaviour was checked only with stubs, scratch processes and the existing e2e test on an ephemeral port.
- The Tailscale Serve guidance in RUNBOOK §7 (Tailscale is not installed).
- Browser-based tools (parity, ui_audit, e2e_multiwin, delta_probe) were not executed (no browser in my brief). Their WS and mutation behaviour was judged from code.
- The 15:40 IST ui-api 48.5 s loop stall (main thread in httpx.AsyncClient() → urllib getproxies_macosx_sysconf at services/ui-api/routers/data_proxy.py:182). Probably the PM's SIGSTOP drill, but building an httpx client per request on the event loop calls the macOS proxy lookup; R-API should confirm.
- The idle CPU question (2.6% vs 0.79% for the app) is R-RUST/perf scope.

# R-RUST — SHIP-WITH-FIXES

I re-ran the W2-RUST gates and they are green. In my scratch target: cargo test 124 passed, clippy 0 (default and devtools), fmt clean, boot_check 52/52, desktop pytest 104 passed. The BUILT copy has the same sha256 as /Applications (28d6ca4e…, build 0ae66db-dirty-fc2248df-20261025T1005Z). Its --self-test against my own stub-backed scratch server on :18791 gave 48/49, with 1 skipped because the screen is locked. The libproc decoding is sound: clang on macOS 26.6.2 confirms sizeof(socket_fdinfo)=792 and offsets soi_kind=256, insi_lport=268, tcpsi_state=344. Each unsafe call passes a correctly sized buffer. The in-process scan costs 2.0 ms CPU (1,606 syscalls, 565 own pids, 719 sockets) and touches no files. launchd reconcile never boots out its own job: the running instance reports XPC_SERVICE_NAME=SuryaDhana and launchctl shows it under the job. SIGTERM, power-cut and poisoned-lock handling are correct. The install/rollback script uses atomic renames and never touches user state.

The port-squatting guard, the headline wave-2 fix, can be bypassed in two ways, and I reproduced both end to end with the built app against my own scratch servers. (1) The 30 s cached Trusted verdict is not tied to the listening process. I swapped the trusted server for a plain C squatter between two polls. The terminal then loaded a fresh document (GET /?tab=system) and all its /api/* calls from the squatter, nothing re-verified, and the self-test still PASSED. (2) A listener whose executable has been deleted gets an Unknown verdict, and Unknown never holds a window back. A squatter that unlinked its own binary was served as the terminal origin with __SURYADHANA_SHELL__ injected. The same mechanism means that after `brew upgrade` (python@3.13 is outdated on this Mac right now, and brew removes the old keg) the live ui-api's verdict turns Unknown. The guard is then silently off until ui-api restarts. Other problems: concurrent WebKit downloads of the same URL escape quarantine and the byte budget. A crash before setup() relaunches forever under KeepAlive. Crash relaunch covers only instances that launchd started.

Idle CPU (2.6% now vs 0.79% this morning): the shell's own work is negligible. All tokio workers together use about 3 ms/s (0.06%), the trust probe 2 ms per 30 s, launchctl print under 10 ms per 30 s, and GET / returns 7.7 KB every 5 s. My 60 s sample of the installed instance (pid 83455 + helpers) totals 2.2%. The shell process is 1.19% of that: JavaScriptCore libpas scavenger 0.63–0.73%, CVDisplayLink 0.20–0.23%, main thread 0.21–0.24%, about 200 wakeups/s. WebContent (BRIEF tab) is 0.54%, GPU 0.24%, Networking 0.23%. A display link is running at refresh rate even though the screen is locked (IOConsoleLocked=true). So the gap comes from the page's rendering or animation (an infinite CSS animation such as .t-pulse, or rAF on the restored BRIEF tab), not from the wave-2 poll, heartbeat or trust-probe cadence. The harness reports only the aggregate number, so this cannot be attributed today.

## R-RUST-01 [major] Cached Trusted verdict (PASS_TTL 30 s) survives a swap of the listening process: any squatter that binds between two polls serves the IPC-granted origin for up to 30 s
- verify: REAL->minor
- file: desktop/src-tauri/src/health.rs:837
- evidence: TrustCache (health.rs:829-858) reuses a pass for 30 s and is forgotten only when a poll sees ui down (health.rs:1053-1057). Its doc claims 'every (re)appearance of the terminal port is verified again'. Reproduced: built app --self-test with SURYADHANA_UI_URL=http://127.0.0.1:18795 (my scratch_server.py, Homebrew CPython, Trusted at 16:05:01). At +12 s I killed it and started a compiled C squatter (squat2.c, not Python, so Foreign by the rule) on the same port. The squatter's log shows the shell's own /health and GET / polls at 16:05:18/:23/:28 answered by it. The webview fetched ~40 page API calls from the squatter, including /api/positions/connection-status, /api/positions/open-positions and /api/monitor/ws/monitor. At 16:05:30 the main window loaded a fresh document 'GET /?tab=system' from it ('[window] main: terminal loaded'). The app log has exactly one [trust] line (the 16:05:01 Trusted), no REFUSED, and the self-test reported passed=true.
- failure: ui-api crashes, is restarted by start-local.sh, or is restarted by the new watchdog hang rule. A same-user process waiting in a bind loop (any binary, including a sandboxed app with the network.server entitlement, which is the exact threat the PLAN row names) takes 127.0.0.1:8010 within milliseconds. For up to 30 s every open terminal window talks to it. Any reload, new window, history step or build-changed reload loads the squatter's HTML with the 9 remote shell_* commands: fake notifications, shell_open_external to a phishing URL, files in Downloads, fake positions/NAV. The watchdog cannot restart ui-api meanwhile because the port is taken.
- fix: Pin the pass to the listener's identity: store (pid, pbi_start_tvsec/usec from PROC_PIDTBSDINFO) with the Trusted verdict, and treat it as fresh only while that same pid still owns the only LISTEN socket on the port. Simpler: drop PASS_TTL and re-verify on every fast poll. The full scan measured 2.0 ms CPU, i.e. 0.2% at the 1 s fast cadence and 0.04% at 5 s. Add a self-test or drill that swaps the listener mid-run and asserts eviction within one poll.

## R-RUST-02 [major] A live same-uid listener whose executable is unreadable (proc_pidpath ENOENT) is 'Unknown', and Unknown never holds windows back: bypass by unlinking the binary, and the guard goes silently off after brew upgrade
- verify: REAL->minor
- file: desktop/src-tauri/src/policy.rs:660
- evidence: policy.rs:659-663 maps exe None to TrustFail::Unknown('executable unreadable (exited?)') even though the uid was read, so the process is alive. health.rs:1266-1268 maps any non-Foreign verdict to Ready. Kernel behaviour, measured with my own compiled binary (pidpath.c): proc_pidpath returns the path while the file exists, fails with errno 2 (ENOENT) after rm, and follows rename(2) to the new path. End to end: squat.c bound 127.0.0.1:18794 and unlinked its own executable. Built app --self-test against it: listener_verified FAIL 'Unknown("pid 57979: executable unreadable (exited?)")', terminal_loaded OK, title 'SQUATTER', shell_object_in_terminal OK. Log: '[trust] ui port 18794 not verified ... windows are not held back' then 'main: terminal loaded http://127.0.0.1:18794/'. On this Mac `brew outdated` lists python@3.13 (keg 3.13.15, the live ui-api's exe). `brew upgrade --help`: 'brew cleanup will then be run for the upgraded formulae', i.e. the running keg is deleted.
- failure: (a) Any same-user binary, not only Homebrew CPython as the README's residual-risk note says, passes the guard indefinitely by deleting its executable after bind. (b) The owner runs `brew upgrade`. The 3.13.15 keg is removed while ui-api, data-service and master-controller keep running from it. From then until ui-api restarts, every verdict is Unknown, the menu-bar shows 'port not verified (retrying)' permanently, and the guard is off: a squatter during the next restart gap is never refused. W2's claim 'the old running path is still trusted' is true only for the pure string test (trusted_python_locations_survive_a_brew_upgrade), not for the running process.
- fix: Split the inconclusive case. If proc_uid succeeds (alive) but proc_pidpath fails, re-check liveness. If alive: Trusted only when (pid, start time) matches a previously Trusted listener (the R-RUST-01 pin), which keeps the running ui-api trusted across brew cleanup. Otherwise use a new 'unverifiable' state that keeps NEW windows on the boot page with 'ui-api's executable is gone (Python upgraded?): ./start-local.sh restart ui-api' and does not evict open windows. Add a unit test for exe None with uid Some(own).

## R-RUST-03 [minor] WebKit downloads are tracked in a HashMap keyed by URL: concurrent downloads of the same URL leave files untagged and uncharged, and the wrong file is charged or removed
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:655
- evidence: windows.rs:628 `HashMap<String, PathBuf>`. On Requested: `pending.insert(url.to_string(), path)` (652-655) overwrites. On Finished: `remove(url.as_str())` (665). A second Finished finds None and only logs 'ended without a file (refused or not admitted)' (694-697): no quarantine, no budget charge, no notification. wry 0.57.1 wkwebview/download.rs:54-55 and 95-96 passes originalRequest().URL for both events, so two downloads of one URL (one blob URL clicked twice, or one export endpoint) share a key.
- failure: The owner double-clicks an 'Export CSV' link, or a buggy or compromised page calls a.click() N times on one 1 GB blob URL. Download A's file is never tagged com.apple.quarantine nor charged to the 200 MB/h budget. A's Finished charges B's partially written file, quarantines it, or removes it mid-write if over budget, and shows a 'Saved' or 'Could not save' notice for the wrong file. N concurrent copies are admitted at once (the 5 GB free check is per admission) and only one is ever charged, so the hourly budget and the disk floor no longer bound WebKit downloads.
- fix: Refuse a Requested whose URL is already pending ('already downloading'), or keep a FIFO Vec<PathBuf> per URL and resolve each Finished against the oldest entry. As a safety net, at Finished, quarantine-sweep files created in the Downloads dir since the request. Add a self-test step that clicks the same blob URL twice.

## R-RUST-04 [minor] Crash bookkeeping runs inside setup(): a failure before it relaunches forever every 20 s under KeepAlive {SuccessfulExit:false}
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:1198
- evidence: crash::startup_check is called inside .setup() (lib.rs:1198). Before it, tauri_plugin_log builds with `?` on create_dir_all, app_log_dir and the log file open (tauri-plugin-log-2.10.1 lib.rs:806-832). Its error fails Builder::build, and `.expect("error while building the SuryaDhana app")` (lib.rs:1412) panics with exit 101. Non-zero exit makes launchd relaunch after ThrottleInterval 20. run.json/crashes.json are never written, so is_loop never becomes true. Separately, write_atomic errors in CrashFiles::on_start are ignored (`let _ =`), so an unwritable or full config volume also stops the breaker from ever standing down. maintain_autostart (which rotates launchd-stderr.log) never runs on this path either.
- failure: Disk full (the Mac holds a 4.4 GB DuckDB plus logs), ~/Library/Logs/ai.suryadhana.terminal unwritable, or a plugin init error after a macOS update. The login job panics at build, launchd respawns it every 20 s for the whole session (roughly 0.3 s CPU and one panic in launchd-stderr.log each time), and the README promise '4 crashes in 10 min stop it' does not hold.
- fix: Move crash::startup_check (plain file I/O on HOME + bundle id) to the top of run(), before tauri::Builder, and make the login-job stand-down independent of Tauri. Under --autostart, treat a Builder::build Err as 'log to stderr, exit 0' after N attempts. If the run marker cannot be written during a login start, stand down (exit 0) rather than run unaccounted.

## R-RUST-05 [minor] Crash relaunch covers only launchd-started instances, and common paths start the app outside launchd, so 'crash relaunch in force now' (completeness-03) is not true for the running instance
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:537
- evidence: KeepAlive applies only to the process launchd spawned. After first-run enable or a toggle, reconcile_launchd (lib.rs:537 / 512) bootstraps the job. Its RunAtLoad copy hands off with LOGIN and exits 0 (instance.rs:144, lib.rs:1101-1104), so the job's last exit is 0 and the manually launched instance that keeps running is not supervised. After ⌘Q, a Dock or Spotlight reopen is a LaunchServices launch, also unsupervised. Nothing calls -[NSApp disableRelaunchOnLogin], so macOS 'Reopen windows when logging back in' can relaunch it via LaunchServices at login and win the single-instance race against RunAtLoad. W2-RUST user_visible_change and build_desktop.sh:310 say 'crash relaunch in force now'. The README (lines 79-95) correctly says only the launchd instance is relaunched.
- failure: The owner quits SuryaDhana (⌘Q) in the afternoon and reopens it from the Dock. A WebKit or Rust crash that evening leaves no terminal and no tray until the next login. The same happens on any login where loginwindow's resume wins the race.
- fix: Call [NSApp disableRelaunchOnLogin] at startup (the login item owns relaunch). On a non-launchd start with the login entry present and the job loaded but not running, hand off to launchd: release the lock, run `launchctl kickstart gui/<uid>/SuryaDhana` (bounded), exit 0, and let the launchd copy become primary. Correct the W2 user-facing text.

## R-RUST-06 [minor] Idle CPU went from 0.79% to 2.6% because of page-driven rendering, not the shell's poll cadence. The harness reports only an aggregate, so regressions near the 3% budget cannot be attributed
- verify: not verified (minor/nit)
- file: scripts/desktop_qa/run_selftest.py:514
- evidence: My 60 s sample (proc_pidinfo PROC_PIDTASKINFO, helpers attributed via responsibility_get_pid_responsible_for_pid) of the installed app: SuryaDhana 1.193% (201.7 wakeups/s, 248 ctxsw/s), WebKit.GPU 0.235%, Networking 0.229%, WebContent 0.542%, total 2.199%. Per-thread over 20 s, two runs: 'JavaScriptCore libpas scavenger' 126-146 ms, main 42-49 ms, CVDisplayLink 39-46 ms, all five tokio-rt-workers together 12-16 ms (~0.06%). The trust probe measured 2.0 ms CPU per run (PASS_TTL 30 s), launchctl print under 10 ms per 30 s, GET / 7,734 bytes, /health 34 bytes. The screen is locked (IOConsoleLocked=true), yet a display link runs at refresh rate. The restored tab is BRIEF (state.json). Infinite CSS animations exist (globals.css:80 .t-pulse, :197 .t-shimmer, used by components/terminal/index.tsx:92 Dot pulse and :700). The morning report (switchover/app_selftest) has the same 6-process composition at 0.79%, so the delta is in what the page renders.
- failure: With two or three windows open, or a page showing a pulsing LIVE dot or skeleton, idle CPU crosses the 3% budget while the owner is away (screen locked) and the battery drains. The cause gets blamed on the Rust pollers because the gate prints one number.
- fix: Extend sample_resources to print per-process and per-thread CPU and wakeups (the same libproc calls as my threads.c), and raise the 12 s warm-up so load work falls outside the window. UI side (R-UI-*): make infinite animations finite (the NewsDock rule `t-pulse 1.2s ... 6`) or pause them when document.hidden or the window is occluded. Shell side, optional: when a window is hidden to the tray or the session is locked, suspend rendering with WKWebView setVisible/occlusion.

## R-RUST-07 [nit] 'Every external program is bounded' is not fully true: drain threads are joined without a bound after kill, plutil runs unbounded, and SMAppService XPC is unbounded
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/exec.rs:86
- evidence: run_bounded kills only the direct child, then `h.join()` on the pipe readers (exec.rs:86). A grandchild that inherited stdout keeps the pipe open and the join blocks. autostart::plist_program uses `Command::new("/usr/bin/plutil")...output()` (autostart.rs:100-103) on the setup path. login_item_status (SMAppService.statusForLegacyURL, macos.rs:177) is a blocking XPC call made from the 60 s tokio loop and from the main thread on toggle.
- failure: Theoretical for launchctl and plutil. A wedged backgroundtaskmanagementd would block the main thread on a Launch-at-Login toggle (UI freeze) or a runtime worker every 60 s.
- fix: Join the drain threads through a channel with a deadline, and route plutil through run_bounded. Call login_item_status on spawn_blocking with a timeout, keeping the last known state.

## R-RUST-08 [nit] The build id ignores Cargo features: a devtools build (Web Inspector on the IPC-granted origin) has the same id as the release build
- verify: not verified (minor/nit)
- file: desktop/src-tauri/build.rs:190
- evidence: build_id = sha7[-dirty]-source_hash-UTC (build.rs:190-195). Nothing encodes CARGO_FEATURE_DEVTOOLS or the profile. build_desktop.sh --install does not refuse a devtools binary.
- failure: A local `--features devtools` build is installed by mistake. About, --version and installed-build look identical to a release, and the terminal origin ships with the inspector enabled.
- fix: Append '-devtools' (and the profile, if not release) to SURYADHANA_BUILD_ID when CARGO_FEATURE_DEVTOOLS is set, and have install_app refuse it unless forced.

## R-RUST-09 [nit] A failed quit leaves a hidden bundle in /Applications, and the Apple-Event quit depends on Homebrew's `timeout`
- verify: not verified (minor/nit)
- file: scripts/build_desktop.sh:175
- evidence: install_app copies with ditto into $dest_dir/.SuryaDhana.app.installing.$$ (line 173) before quit_copy (line 175). quit_copy's `die` exits with no trap, so the temp bundle stays. quit_copy line 148 uses `timeout 20 osascript`. On this Mac `timeout` is /opt/homebrew/bin/timeout (coreutils); /usr/bin/timeout does not exist and check_toolchain does not check it. Without it the command fails, `|| true` hides the failure, and the script waits 10 s and falls back to SIGTERM (which the app handles as Quit).
- failure: Each failed install leaves an 8 MB hidden SuryaDhana bundle in /Applications that LaunchServices may register (duplicate 'Open With' or Spotlight entries). On a Mac without coreutils the graceful quit never runs.
- fix: Add `trap 'rm -rf "$tmp"' EXIT` in install_app (cleared after the final mv), or quit before ditto. Check `command -v timeout`, or use a bash-native timeout around osascript.

## R-RUST-10 [nit] Logout or Dock 'Quit' (an AppKit terminate) skips the session save: only RunEvent::Exit fires
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:1422
- evidence: tao 0.37.2 implements only applicationWillTerminate, mapped to LoopDestroyed and RunEvent::Exit (app_delegate.rs:130-133). The session is saved in quit() and RunEvent::ExitRequested (lib.rs:1422-1429), neither of which runs on that path. Exit removes run.json correctly, so this is not a false crash. The periodic save runs every 60 s.
- failure: Windows opened or moved within 60 s before a logout or shutdown are not restored at the next login.
- fix: Call windows::save_session in the RunEvent::Exit arm too, guarded by the quitting flag so it does not double-save.

### claimed fixed but not
- C2-security-04 (wave 2 trust guard): 'Every listener must be this user's process whose executable is a CPython' and TrustCache's 'every (re)appearance of the terminal port is verified again' are bypassable. A listener swapped between polls is served for up to 30 s (R-RUST-01, reproduced), and a listener with a deleted executable is Unknown, i.e. fail-open, indefinitely (R-RUST-02, reproduced). 'The old running path is still trusted' after brew upgrade holds only for the pure string rule: once brew cleanup deletes the keg, the running ui-api is Unknown and the guard is off.
- C2-security-11: 'WebKit downloads are charged to the same app-wide ByteBudget' and 'every file is tagged com.apple.quarantine' do not hold for concurrent downloads of the same URL (R-RUST-03, code-level).
- completeness-03 user_visible_change 'Turning Launch at Login on or off applies immediately (crash relaunch in force now)': for the instance that is running, which was not started by launchd, no crash relaunch is in force (R-RUST-05). The README states this correctly; the W2 report and build_desktop.sh:310 do not.
### not checked
- I did not launch the app normally (forbidden). Quit, logout, shutdown, the crash loop and the loginwindow 'Reopen windows' race were checked by reading lib.rs and the tao 0.37.2 app_delegate only, not exercised live.
- Concurrent same-URL WebKit downloads (R-RUST-03) were not reproduced: the webview cannot be driven outside the fixed self-test.
- No browser was used, per the brief, so the exact CSS animation or rAF loop keeping the display link alive on the BRIEF tab is not identified.
- relaunch_drill.sh and the install/rollback flow were not re-run: both launch the app or rewrite LaunchAgents.
- W2's hung-listener and closed-port self-test modes were not re-run; the PM's SIGSTOP drill on the live stack covers that path.
- boot_page_painted (< 500 ms) is unmeasurable because the session is locked.
- The pre-setup crash loop (R-RUST-04) was not triggered: making the log dir unwritable would require a normal launch.

# C-TRADER — SHIP-WITH-FIXES

I reviewed the live product as a Bloomberg user would. Release 20261025-153533-0ae66db was served on :8010, and I used one WebKit browser after AUDIT3_DONE. Prefs were readonly, every WebSocket was mocked (0 live sockets) and every non-GET was refused in the browser. Only 3 POSTs were attempted and all were refused: OSTR analyze, MCXG ticket, and my own UPDATE DATA test. I ran it in browser mode and in a simulated SuryaDhana.app shell, at 1600x1000 and 1100x700. I took 50+ screenshots covering 18 pages and the stock window, and ran keyboard, outage, crash and table-geometry scripts.

Most round-1 C1-trader-ux fixes hold up when exercised for real:
- **Error isolation (-01):** a malformed eco-calendar or desk payload gives a 'BRF/DESK FAILED TO RENDER' panel. The strip, header, footer chip and navigation stay up and no stack is shown.
- **Outage and recovery (-02):** a LINK DOWN drill dims the page and shows the banner, footer OFFLINE · LINK DOWN and NIFTY ◌ STALE. Failed panels reload within 3 s of LINK UP.
- **Status chrome (-06, -07):** the app shows a single brand, clock and set of lights, and the dots stay green.
- **Header width (-10):** row 1 has scrollWidth equal to clientWidth on every page, in both modes, at 1600 and 1100.
- **PORT/BRKR (-04, -05):** they show PAPER ONLY with LIVE struck through, and no login URL appears in the DOM.
- **Keyboard (-09):** type-to-GO, Esc closing the stock window, and Back/Forward all work in both hosts. TICKER DES/FA/OMON, help with ⌘ keys and ?sym= deep links also work.
- **Prices (-08):** prices print with 2 decimals (₹311.65, ₹1,125.30).
- **Charts (-17):** charts render in CSS px.

What still stops a professional user, ranked by impact:
1. **TICKER OMON shows the wrong chain.** When it is run from any other page, OMON shows NIFTY's chain while the selection says RELIANCE/INFY. This is a stale-response race and was reproduced 2/2.
2. **Two call walls on one screen.** OMON's OI chart labels CALL WALL at 23,500 while the KPI and BRF say 24,000. This came in with the C1-17 fix.
3. **The Desk watchlist hides columns.** NEXT EVENT is hidden at the app's default 1600 width. At the 1100 minimum, 12M, LAST, P/E, PROFIT Y/Y and NEXT EVENT are hidden. This was part of -10, which is claimed fixed.
4. **UPDATE DATA reports false success.** A failed request still shows 'Refresh complete'. START DOWNLOAD also has autofocus, so a click followed by Enter starts the universe download.
5. **Wrong level on the index charts.** The prev-close tag reads 22687.5 for 22,687.65. The index chart uses precision 1, the tray title also prints 1 dp, and the MKT tile prints 0 dp, which contradicts the '-08 index levels always 2 dp' claim.

There are also minor gaps in navigation priority, stock-window honesty and layout, EQS density, Bloomberg aliases, the Muhurat session on 8 Nov and units, plus polish nits. None of these needs a trading-logic change, and I found no blockers.

## CT-01 [major] 'RELIANCE OMON' (or any TICKER OMON) from another page shows NIFTY's option chain: a stale-response race overwrites the requested underlying
- verify: REAL->major
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/OptionChain.tsx:161
- evidence: omon.py (WebKit, simulated app): from DESK, GO 'RELIANCE OMON' then Enter. localStorage suryadhana.omon.v1=RELIANCE, but the page header read 'OMON OPTION MONITOR NIFTY · … lot 65' at +1 s, +3 s and +8 s. Same result for 'INFY OMON'. Network log: on mount the page sends /option-chain/NIFTY (first render: useState('NIFTY') at :161; the load effect fires before the localStorage read at :175 re-renders) AND /option-chain/RELIANCE in the same ms. RELIANCE answered at .43, NIFTY at .43/.46, and the later NIFTY response wins setData (:182, no request-id guard). Only when OMON is already open (event path) does RELIANCE show (lot 500). Screenshots final-ctrader/shots/omon-handoff-0.png and app-keys-rel-omon.png. The same code is in the pre-program baseline (baseline_src.tar.gz OptionChain.tsx:132-144), so this predates the program, but it is a headline function in the help card.
- failure: The trader types 'RELIANCE OMON' from BRF/DESK (the normal path). OMON opens showing NIFTY's walls, PCR and max pain. Nothing says loading or error. The trader reads index levels as a stock chain, or decides the stock has no chain. Whichever response arrives last wins, so it can also flip on a slow day.
- fix: UI only. Initialise state from the hand-off key: useState(() => localStorage.getItem(OMON_KEY) || 'NIFTY'). In load(), tag each request (a ref counter or AbortController) and drop any response whose symbol/expiry is not the current one. On a symbol change, clear `data` or show 'LOADING RELIANCE…' so the old chain never sits under the new selection. Add a pages.check plus a browser test: GO 'RELIANCE OMON' from DESK must end on the RELIANCE header.

## CT-02 [major] OI-by-strike chart names a different CALL WALL (23,500) than the OI WALLS KPI and BRF (24,000) on the same screen
- verify: REAL->major
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/OptionChain.tsx:69
- evidence: app-1600-OMON.png: the KPI 'OI WALLS 24,000 / 21,500' sits above a chart that labels 'CALL WALL' on the 23,500 bar and colours 23,500 red on the strike axis. GET /api/market/option-chain/NIFTY: resistance [24000, 23500, 23000]; rows span 21,250 to 23,950 (55 rows); 24,000 is not in rows; argmax of ce.oi over rows = 23,500 (1.92 cr). OiBars computes callWall = argmax over the displayed window (:69), while the KPI (:263) and the chain highlight (:217/:296) use data.resistance[0]. The 'CALL WALL' label was added by the wave-2 C1-17 fix.
- failure: A derivatives user reads the chart, the page's most prominent visual, and takes 23,500 as the call wall/resistance, while the KPI and BRF ('walls 24,000/21,500') say 24,000. One of the two is wrong on every expiry where the true wall lies outside the strike window, which is common for far-OTM call walls.
- fix: Label walls from data.resistance[0] / data.support[0]. When a wall strike is outside the plotted rows, draw an edge marker ('CALL WALL 24,000 →'), or widen the rows to include both walls. Keep argmax only as 'largest in view' if wanted, with a different label. Add a pages.check case with a wall outside the window.

## CT-03 [major] Momentum watchlist hides its NEXT EVENT column at the default 1600 px and hides LAST, P/E, PROFIT, 12M and NEXT EVENT at the 1100 px minimum (round-1 -10 evidence, still open)
- verify: REAL->major
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DecisionDesk.tsx:240
- evidence: tables.py (DOM geometry, simulated app): at 1600x1000 the watchlist table is 1033 px wide in an 866 px scroll box (overflow 167 px) and NEXT EVENT is entirely outside it. At 1100x700 the table is 1033 px in a 588 px box (overflow 445) and the hidden headers are ['12M','LAST','P/E','PROFIT Y/Y','NEXT EVENT']. app-1600-DESK.png shows the last visible column is PROFIT Y/Y. Chromium 1680 (PM audit desk.png) shows 'RESUL'/'FUND' chips cut. The grid at :240 puts the watchlist in a 1.25fr column beside BOOK VS NIFTY, and the Industry column (:153, 'Automobile and Auto Components') takes the width. Round-1 C1-trader-ux-10 listed exactly this ('NEXT E', 'FUND R' cut); W2 marked -10 fixed after fixing only the header.
- failure: On the default window, the owner never sees which watchlist names report results next week, which is the reason the column exists. In a quarter-screen or 1100 px window, the Desk watchlist shows names and 6M returns but no price at all, unless the user discovers a hidden horizontal scroll.
- fix: Below about 1500 px, stack the watchlist full-width above BOOK VS NIFTY. Give Industry a max width with ellipsis and a title. Make NEXT EVENT and LAST fixed columns. Add the watchlist table to the ui_audit width checks (1100/1280/1440/1600/1680: no hidden th).

## CT-04 [major] A failed UPDATE DATA request is reported as 'Refresh complete', and the confirm's autofocus on START DOWNLOAD lets click-then-Enter start the 1,500-stock download
- verify: REAL->minor
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx:503
- evidence: update.py (simulated app, POST refused in the browser with 403): click '⤓ UPDATE DATA' and document.activeElement is 'START DOWNLOAD' (MarketCommandHeader.tsx:477 autoFocus). Pressing Enter sent POST /api/dashboard/refresh (blocked). The panel then read 'Refresh complete' (update-data-after-enter.png), because handleRefresh's catch (page.tsx:503-506) only console.errors and the label falls through to 'Refresh complete' (:700-708). The panel is still the legacy indigo/emerald Tailwind skin, with 'Downloading 5yr OHLCV … via yfinance' and 'python scripts/nifty500_pipeline.py --mode …' dev commands (:688-799).
- failure: The trigger fails: ui-api 5xx, data-service down, an http_guard 403, or a timeout during the 18:30–21:15 EOD window. The owner is told 'Refresh complete' and trusts the data as current. Separately, a reflexive Enter after opening the popover queues a multi-minute universe download (the EOD warning is shown but the action is not blocked).
- fix: On a trigger error, set refreshError (or a new triggerError) and show 'UPDATE FAILED · <reason> · RETRY'. Never default to 'Refresh complete' without a status. Put autofocus on CANCEL, or require a second explicit click. Disable START DOWNLOAD inside 18:30–21:15 unless confirmed again. Restyle the progress panel with the terminal kit and drop the CLI text, or move it behind a 'details' disclosure.

## CT-05 [minor] Index intraday charts tag the previous close with a wrong value (22687.5 for 22,687.65) and print the axis at 1 dp; the tray title and MKT tile also break the 'index levels always 2 dp' claim
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/IndexIntraday.tsx:75
- evidence: crop-brf-chart.png (BRF) and app-1600-MOV.png: the 'prev' price-line label reads 22687.5 while the text above reads 'prev 22,687.65' (API previous_close 22687.65). The axis reads 22800.0/22500.0. The cause is priceFormat {precision: index === 'INDIA VIX' ? 2 : 1, minMove: 0.01} at :75. BANK shows 54925.7 for 54,925.70. The tray title uses group_thousands(n.last, 1) at desktop/src-tauri/src/health.rs:421 ('NIFTY 22,600.0 ▼0.39% · closed'; only the tooltip uses 2 dp). MKT's NIFTY 500 tile prints 21,428 (fmtNum, MarketMonitor.tsx:188) while BRF prints 21,427.60. W2-UI-PAGES claimed both IndexIntraday and the tray were 2 dp.
- failure: A trader reads the prev-close tag as 22687.5, a value that never printed, or the menu bar as 22,600.0, and sees three precisions for the same index across pages. These are the misreads C1-08 was meant to remove.
- fix: Set priceFormat {type:'price', precision: 2, minMove: 0.05} (NSE index tick) for every index, and VIX at 2/0.0025. Use group_thousands(n.last, 2) in tray_title. Use fmtIdx for the MKT index tile and its 200-DMA. Add a pages.check guard: no precision 1 in IndexIntraday.

## CT-06 [minor] The page strip and ⌘1–9/Alt+0 favour research and dormant pages while CHRT, OMON, RSK, MCXG, MOV and WEI sit behind MORE; PORT still has Alt+0, a 'Portfolio' vs 'Execution Engine' name mismatch and an 'ACTIVE' chip on a dormant engine
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx:537
- evidence: tabList (:537-559): slots 1–9 = Brief, Watch, Desk, Markets, Deriv, Events, Overview, Stocks, Backtest, slot 0 = positions (legacy PORT). The visible strip then shows Broker, Pipeline, LW Scan, Alpha, Commodity, Glass-Box, ML, Explorer, Warehouse, Research, System. CHRT, OMON, OSTR, RSK, MCXG, MOV, WEI and ALRT appear only in MORE (every screenshot). keys.py: Alt+Digit0 → ?tab=positions. app-1600-PORT.png: strip 'PORT PORTFOLIO', page 'EXECUTION ENGINE', header chips 'PAPER ONLY · LEGACY · DORMANT' next to 'Execution Control Panel [ACTIVE]' (LivePortfolio.tsx:199-206) and a full-width red LIQUIDATE & HALT · PAPER. 'NET EQUITY ₹10.0K' uses Western K units (LivePortfolio.tsx:87). W2-UI-PAGES listed the Alt+0 slot and the label as open remainders while marking -04 fixed.
- failure: The keys a pro learns first (⌘1–9) lead to Overview/Backtest and Alt+0 to a dormant legacy engine. The daily-use market pages need MORE or GO. On PORT the owner sees ACTIVE and a big liquidate button on an engine the header calls dormant.
- fix: Reorder tabList by daily use (BRF, WTCH, DESK, MKT, CHRT, OMON, DERV, MOV, RSK, then MCXG/EVTS) and move OVRV/BTST/PIPE/LWSC/ALFA/GBOX/MLEN/DEXP/WHSE to MORE. Mirror the order in desktop/src-tauri/src/pages.rs shortcut and keep the contract test. Rename PORT to 'Legacy engine' in the strip and menu. Show the state chip as 'LEGACY · DORMANT', grey, and collapse LIQUIDATE behind a disclosure when there are 0 positions.

## CT-07 [minor] The stock window shows a green, endlessly pulsing price pill with no change, % change, as-of time or CLOSE marker, and at the 1100 px minimum the price pill overlaps the PIN button
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StockDetailModal.tsx:243
- evidence: app-1600-STOCK.png (Sunday): TCS ₹2,530.00 sits in an emerald pill with an animate-pulse dot (:243-250, infinite, unlike the 'finite animations' C2-performance-03 claim). It is labelled only '● DELAYED · YAHOO'. There is no day change, no %, no 'CLOSE 23-OCT' and no timestamp, while the header NIFTY chip correctly says CLOSE 23-OCT. The header has no company name either (ticker only). crop-stock1100.png: at 1100x700 the '●₹2,530.00' pill is drawn over '☆ PIN'.
- failure: The core Bloomberg loop is ticker → stock window. On weekends, holidays and after hours, which is most of the clock, the window presents Friday's close as a live green quote without the move or the time. At the minimum window size, the price and the PIN action collide.
- fix: Render the header the way the NIFTY chip does: last, ▲/▼ change and %, an as-of time, and feedState's CLOSE <day> / STALE wording (useFeedState). Use a neutral colour and a static dot when the market is closed or the price is delayed, and add the company name. Let the identity block wrap above the action chips below about 1250 px (flex-wrap on the outer row) so nothing overlaps.

## CT-08 [minor] EQS rows are still ~50 px with 3 columns hidden at 1600 px and 8 at 1100 px, in the legacy slate/rounded Tailwind skin (C1-trader-ux-11 still open)
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StockTable.tsx:474
- evidence: tables.py: stocks table 16 columns, 1777 px wide in a 1570 px box at 1600 (hidden DATA%, HEALTH, WATCH) and a 1070 px box at 1100 (hidden MKT CAP, DIV YLD, NP QTR, SALES QTR, ROCE, DATA%, HEALTH, WATCH). Rows measure 50 px (two-line company cell, py-1.5 at :474/:482). app-1600-EQS.png shows 9 rows above the fold. The P/E column is ragged (AAVAS '17' vs '10.4'), and the header '1,500 of 1,500' sits next to the footer '1,496 STOCKS'. W2-UI-SHELL marked -11 partial and left this to the screener owner.
- failure: The screener, which is a scanning surface, shows a ninth of what a Bloomberg EQS shows per screen. The fundamentals the user filters on (ROCE, sales) need a horizontal scroll on a laptop.
- fix: Use a dense single-line row (company name in a title or tooltip, sector as a narrow column, about 26 px like FUND/DataTable). Fix P/E to 1 dp. Make the stock count one source. Port the table to the kit DataTable or its tokens (square, mono, T.* colours).

## CT-09 [minor] Bloomberg mnemonics still misfire: GP opens GPIL/GPPL, TOP opens SHOPERSTOP, MOST opens a ticker 'MOST', BACK opens BTST, NIFTY offers MEMB/SEAG/NIFTY1 (part of the round-1 -09 fix, not done)
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/CommandBar.tsx:170
- evidence: keys.py GO results: GP → ['GPIL …','GPPL …','GPTINFRA …']; TOP → ['SHOPERSTOP …']; MOST → ['MOST MOST']; BACK → ['BTST Backtest lab']; NIFTY → ['MEMB …','SEAG …','NIFTY1 …']. N → NEWS works. CommandBar has no alias table (only score() at :170-176). Round-1 -09's fix asked for GP→CHRT, TOP/N→NEWS, MOST→MOV, BRIEF→BRF and exact-code priority; W2 marked -09 fixed without them. Everything else in -09 verified: type-to-GO, Esc, Back/Forward and help all PASS in both hosts.
- failure: Bloomberg muscle memory (TCS GP, TOP, MOST, NIFTY OMON) lands on unrelated tickers or the backtester. Enter on the first item opens the wrong thing.
- fix: Add an alias map ahead of symbol matching: GP/GIP → CHRT (and 'TICKER GP' → chart focus), TOP/N → NEWS, MOST → MOV, BACK → history.back(), NIFTY/BANKNIFTY → an index item (chart + OMON). Rank exact page codes and aliases above ticker prefix matches.

## CT-10 [minor] Muhurat trading on Sun 8 Nov 2026 is not modelled: the strip, header, NIFTY chip and tray will say CLOSED · WEEKEND during the live special session
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/session.ts:56
- evidence: nseSession() returns CLOSED/WEEKEND for every Sunday (:56) and accepts only a holidays map. GET /api/market/eco-calendar?ahead=40 lists only HOLIDAY events (10 Nov, 24 Nov) and no special session. health.rs is_nse_session (:298) also excludes weekends. The app's own MCXG page lists '2026-11-08: Muhurat trading (Diwali Laxmi Pujan) — Sunday evening special session'. Round-1 -13 flagged this; W2-RUST marked -13 fixed and W2-UI-SHELL partial, and neither touched special sessions.
- failure: In two weeks, during the one-hour Muhurat session, every NSE indicator says CLOSED and the NIFTY chip reads 'CLOSE 06-NOV' while prices move. The fix round just removed exactly this kind of 'which light do I trust' contradiction.
- fix: Add a special-sessions input (from the NSE circular via the ECO feed, or a small config list) to nseSession / headerSession / feedState and to the Rust classify_quote, labelled 'MUHURAT'. Add unit cases for 2026-11-08 in desktop.check and cargo tests.

## CT-11 [minor] Mixed units within one column and one product remain: DERV OI column mixes cr and L, PORT uses Western K, index precision varies by page
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DerivativesDesk.tsx:48
- evidence: app-1600-DERV.png futures term structure: OI (SHARES) column reads '1.13 cr', '85.5 L', '8.5 L', and OI CHG reads '-24.9 L', '26.4 L', '1.1 L' (oiFmt :48 picks the unit per cell). PORT reads 'NET EQUITY ₹10.0K · Start ₹10.0K' (LivePortfolio.tsx:87) while the rest of the app uses lakh/crore. NIFTY 500 shows 21,428 on MKT and 21,427.60 on BRF. Round-1 -08's fix asked for 'one unit per axis or column'.
- failure: Scanning a right-aligned OI column, the eye compares digits and 1.13 cr reads smaller than 85.5 L, an order-of-magnitude misread. K next to L and cr invites the same.
- fix: Pick the unit per column from the largest value (all L or all cr) and print it in the header ('OI · L'). Replace the K formatter with the kit's Indian formatter. Use fmtIdx for every index level.

## CT-12 [minor] RSCH 'What's new' and docs/IMPROVEMENT_LOG.md say nothing about the desktop program (last entry 19 Oct): the owner is not told about new keys, UPDATE DATA, PORT PAPER ONLY or the app
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/docs/IMPROVEMENT_LOG.md:1
- evidence: app-1600-RSCH.png: 'WHAT'S NEW docs/IMPROVEMENT_LOG.md · 1766 lines · updated 6 days ago', headed 'terminal polish sprint (11–15 Oct 2026)'. The file mtime is 19 Oct 10:16 and grep finds no SuryaDhana.app or desktop-program entry. PLAN AC-15 requires IMPROVEMENT_LOG to be current. The repo CLAUDE.md says to read it before UI work.
- failure: The owner opens the new app and finds ⌘ shortcuts, a renamed and confirmed UPDATE DATA, a PAPER ONLY PORT, type-to-GO and new failure panels, with no release note in the place the product itself points to for 'what changed'.
- fix: Add a dated 25 Oct entry at the top of IMPROVEMENT_LOG.md: the app, login start, keys, LINK DOWN behaviour, UPDATE DATA, PORT, the migration step, and known gaps from this review. It then appears in RSCH automatically.

## CT-13 [nit] 'today' and 'morning' wording on a closed Sunday; strip says MORNING BRIEF over an EVENING BRIEF page; BRF clock in 12-h
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LiveMovers.tsx:120
- evidence: app-1600-MOV.png: both panels read 'INTRADAY today vs previous close' and 'WHO MOVED THE INDEX each stock's contribution today' (LiveMovers.tsx:120-121) under a header that says 'market closed: last session'. WTCH reads 'UP / DOWN TODAY 0 / 0' in green. app-1600-BRF.png: strip 'BRF MORNING BRIEF' (components/desktop/pages.ts:16) above page 'EVENING BRIEF Sunday, 25 October at 04:03 PM IST' (Brief.tsx:262, 12-h clock next to the strip's 16:03:39).
- failure: Small contradictions that a professional reads as unfinished, and that weaken the closed-market honesty the rest of the product now gets right.
- fix: Use feedState: 'last session (23 Oct) vs previous close' when closed. Have the strip take the page's dynamic title, or use a neutral 'Brief'. Use 24-h time in the BRF subtitle.

## CT-14 [nit] Colour emoji and dev paths remain in the glyph terminal; the menu title still embeds '(⌘K in the terminal)'; CHRT RSI pane not time-aligned
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/AlertsBell.tsx:53
- evidence: 🔔 renders as Apple colour emoji in the header bell (AlertsBell.tsx:53), the stock window '🔔 ALERT' chip (terminal/ChartActions.tsx:116) and WTCH (WatchMonitor.tsx:198/244), against W2-UI-PAGES' 'No emoji' claim. CHRT footer: 'EMA/BB/RSI computed client-side from the bars shown (lib/chartData.ts)' (ChartStudio.tsx:409). BRKR: 'python scripts/icici_session_helper.py (the stack's Python)'. desktop/src-tauri/src/menu.rs:243 is still 'GO Bar…   (⌘K in the terminal)'. CHRT's RSI pane time axis is not aligned with the price pane (app-1600-CHRT.png: 'Jun' at x≈50 vs 107).
- failure: Cosmetic only. The terminal look breaks where emoji and file paths appear, and the native menu looks unfinished. Misaligned panes make RSI-vs-price reads at a date imprecise.
- fix: Swap 🔔 for a kit glyph or an SVG bell. Reword the dev-path copy ('indicators computed from the bars shown'). Give the menu item a real ⌘K accelerator or drop the parenthetical. Sync the RSI pane's timeScale with the price chart (subscribeVisibleLogicalRangeChange).

## CT-15 [nit] The SETTINGS migration notice floats over page content and above modal dialogs on every page until migration; the macro tape is not marked stale during LINK DOWN
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/globals.css:363
- evidence: Every app screenshot: the fixed .sd-note (globals.css:363-364, bottom 32 px, about 860 px wide) covers DESK watchlist rows 10–11, the EQS rows, the OMON smile axis, and the bottom of the help card and stock window (app-keys-help.png, app-1100-STOCK.png). At 1100x700 it covers about 40% of the bottom band. drill-brief-down.png: during LINK DOWN the tape still shows GIFT/BANK/VIX values with no stale mark, while the NIFTY chip correctly says ◌ STALE.
- failure: Until the owner does the :3000 migration, which has not happened yet, the first-run app hides data rows on every page and sits over dialogs. During an outage the tape presents old numbers as current.
- fix: Dock the notice into the footer or top strip as a one-line chip, below Z.modal. Dim the tape and add a ◌ STALE tag while link === 'down' (useShellState).

### claimed fixed but not
- C1-trader-ux-10 (marked fixed): the header row is fixed, but the DESK momentum-watchlist clipping that was part of the same finding is not. NEXT EVENT is hidden at 1600, and LAST, P/E, PROFIT Y/Y, 12M and NEXT EVENT are hidden at 1100 (CT-03).
- C1-trader-ux-08 (marked fixed: 'Index levels always 2 dp: IndexIntraday…, the tray already prints NIFTY with 2 dp'): IndexIntraday still uses precision 1 and tags prev close 22,687.65 as 22687.5. The tray title uses group_thousands(n.last, 1) (health.rs:421), and only the tooltip is 2 dp. MKT index tile is 0 dp. DERV OI column still mixes cr and L (CT-05, CT-11).
- C1-trader-ux-09 (marked fixed): the Bloomberg aliases in the fix (GP, TOP/N, MOST, BACK, exact-code priority) were not added. GP, TOP, MOST and BACK still land on tickers or BTST. The rest of -09 verified (CT-09).
- C1-trader-ux-04 (marked fixed): PORT still owns the Alt+0 slot. Strip and menu say 'Portfolio' while the page says 'Execution Engine', and an 'ACTIVE' chip sits next to 'LEGACY · DORMANT' (CT-06).
- C1-trader-ux-13 (W2-RUST marked fixed): Muhurat/special sessions are still not modelled. MOV 'today' wording remains, and the stock window has no closed or as-of marker (CT-07, CT-10, CT-13).
- C1-trader-ux-18 / W2-UI-PAGES 'No emoji': 🔔 colour emoji remain in the header bell, stock-window ALERT chip and WTCH. menu.rs '(⌘K in the terminal)' and dev paths in CHRT/BRKR copy also remain (CT-14).
- C2-performance-03 'attention animations are finite': the stock window's price-pill dot is an infinite Tailwind animate-pulse (StockDetailModal.tsx:248). Observed in code only (CT-07).
### not checked
- Native SuryaDhana.app chrome: real WKWebView pageZoom with the K3 strip counter-zoom, traffic-light alignment, native menu/tray rendering, notifications, and NEW WINDOW / Shift+Enter opening real windows. The brief forbids launching the app, so I used a simulated __SURYADHANA_SHELL__/__TAURI_INTERNALS__ in Playwright WebKit (same engine, different host).
- OSTR payoff, Greeks and breakeven rendering, and MCXG ticket pricing: their POSTs were refused by my GET-only harness, so the C1-17 OSTR label claims are unverified here.
- Market-hours behaviour: live ticks and flashes, OMON LIVE chain, PRE auction, ICICI-connected states and a Muhurat session. Today is Sunday and Breeze is not connected.
- The 2.6% vs 0.79% idle CPU difference of the installed app. That is outside the trader-UX brief, though the infinite animate-pulse in the stock window (CT-07) is one candidate if a stock window was open.
- A real ui-api outage or sleep/wake. My drill aborted /api in the browser and faked the shell status, and no live service was touched.
- Multi-monitor layouts, an 8-window session restore and VoiceOver.
- Whether the OMON hand-off race (CT-01) also affects other GO hand-offs. DEAL and COMP use different code paths and were not exercised.
- Chromium. My brief limited me to one WebKit browser, and the PM's 42-page Chromium/WebKit audit covers console and API errors.

# C-PERF — SHIP-WITH-FIXES

I measured the live :8010 product and the installed app (build 0ae66db-dirty-fc2248df-20261025T1005Z) using GET requests only. In the browser every WebSocket was mocked (8 mocked, 0 forwarded) and prefs were readonly. I ran one browser at a time, after AUDIT3_DONE. Scratch: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/final-cperf/.

**AC-13 budgets I can measure**
| Budget | Result | Status |
|---|---|---|
| First-load JS ≤ 300 kB gz | 274.0 kB (round 1: 263.3) | PASS |
| Cold load | FCP 120 / 127 ms, app ready 125 / 157 ms (Chromium / WebKit) | PASS |
| Tab switch p95 < 400 ms, page on screen | 33.7 / 67.0 ms (round 1: 40.8 / 81) | PASS on all 42 pages |
| Idle RSS | 332–389 MB RSS, 146–225 MB footprint | PASS |
| Idle CPU | 1.85–1.93 % steady state over three samples (90–119 s, 30 s), screen locked | PASS (locked screen only) |

**Still slow: data-settled tab switch.** The p95 for data to finish loading is 1,279 / 1,210 ms. It was 1,563 ms in a quiet WebKit re-run, against 1,461 / 1,379 in round 1. 13 to 18 of the 42 pages are over 400 ms. Server endpoints that C2-performance-04 named but wave 2 did not touch account for this.

**Round-1 performance items**
- Fixed and checked live:
  - **EQS:** CSS hover costs +0.2 ms (Chromium) and +4 ms (WebKit) over the control; round 1 was +79 / +123 ms. WebKit shows the first rows in 0.35 s. With 1 Hz ticks on 21 symbols there were 0 long tasks.
  - **Animations:** none running on BRF at 15 s, 60 s or 10 min.
  - **PipelineStudio:** 0 /api/pipeline/* requests while idle.
  - **Gzip:** stock list 934,658 → 113,235 B.
  - **DEXP:** v1 page clicks 5–98 ms; v2 0.885 s cold, then 58 ms.
  - **Redis:** one Redis connection on ui-api.
  - **Status pulls:** no repeated status pulls.
- **Not fully fixed:**
  - Gold-preopen: 0.80 s cold, 0.05–0.07 s warm, but 0.47 s again after its 30 s TTL and 3.56 s when Yahoo was slow. The page refreshes every 60 s, so with one window the cache almost never hits.

**10-minute idle on BRF (Chromium):**
- 27.0 requests/min, all of them shared page-chrome polls; 16 of the 27 are NIFTY polls.
- JS heap after GC went 7.87 → 8.57 MB and levelled off from minute 6. DOM nodes (1,593) and listeners (486) stayed flat. Main thread 0.37–0.47 % busy, no long tasks.

**Why the installed app read 2.6 % CPU this afternoon and 0.79 % this morning:** neither number is an idle measurement.
- **Start-up load:**
  - Both runs sample for 60 s starting 12 s after launch, with the screen locked.
  - The afternoon run started 2 minutes after ui-api restarted (15:35:49) and 2 minutes after the brand-new release 20261025-153533 went live. So BRF's ~30 calls hit cold caches, and the page's warm-up fetched and compiled 44 chunks (394 kB) of a release WebKit had never cached.
  - The morning run hit warm caches.
- **Real steady-state changes:**
  - The status heartbeat went from 30 s to 8 s. WebContent CPU bursts land on an exact 8 s period, about 20–30 ms each, or 0.25–0.35 %.
  - The Rust pollers themselves are negligible: tokio workers ≈ 0.08 %, the libproc trust probe ≈ 2.5 ms per 30 s, launchctl children ≈ 0.03 %.
- **Most of the shell's ~1.1 %:** it comes from WebKit threads inside the app process. The libpas memory scavenger takes 0.63–0.66 % and CVDisplayLink (the screen-refresh timer) 0.18–0.20 %. Together they cause about 200 wakeups/s, although no animation is running. An idle Safari under the same locked screen sits at about 0 %.

**Ranked by user-visible impact:**
1. Stale-while-revalidate cache for gold-preopen (CMDT and BRF wait 0.5–5.8 s).
2. Server caches for results-recent?days=95 (0.97 s every call; EQS and WTCH), results-implied-moves (0.74 s; EVTS) and the news quotes (1.7–2.3 s cold; WEI), plus warming them when ui-api starts.
3. A real AC-13 idle run: screen unlocked, 10 minutes, 1 and 3 windows, boot paint.
4. Profile the shell's 200 wakeups/s.
5. Cheaper heartbeats and one set of chrome polls per app instead of per window.
6. Batch EQS ticks per frame.
7. Mock WebSockets by default in ui_perf.
8. Keep an eye on first-load JS growth.

## C-PERF-01 [major] Settled p95 is still 1.2–1.6 s: results-recent, results-implied-moves and news quotes are uncached, and C2-performance-04 is marked fixed
- verify: REAL->major
- file: services/ui-api/routers/markets.py:154
- evidence: WS-mocked ui_perf, 3 runs × 42 pages per engine. Settled p50/p95: Chromium 71.5/1,279 ms, WebKit 98.9/1,210 ms. A quiet WebKit re-run after the parity run ended gave 107/1,563 ms. Pages with settled p95 over 400 ms: 13 (Chromium) and 18 (WebKit); round 1 had 12 and 11. Page-on-screen p95 is only 34/67 ms, so the time goes to the server. Direct curl: /api/market/results-recent?days=95 took 0.976, 0.972 and 0.990 s on three consecutive calls. The handler (markets.py:154) proxies data-service with no cache; ui/lib/useCorpEvents.ts:56 calls it on the first EQS or WTCH visit in each window, and it was the dominant call there (1,036–1,109 ms). /api/market/results-implied-moves took 0.747 and 0.736 s on back-to-back calls (markets.py:913, uncached); it was EVTS's dominant call at 924 ms and EVTS settled at 1.29–1.58 s. /api/news-scanner/quotes was WEI's dominant call at 1.7–2.3 s cold (60 s TTL), with WEI settled at 1.7–3.1 s. Other slow ones: fundamentals-screen 0.6–1.7 s under the page's own parallel calls, /api/mcx/specs 1.5 s, index-intraday 0.79 s. W2-API's C2-performance-04 outcome ('fixed') changed only gold-preopen and DEXP. Round 1's prescribed 5-minute caches for results-implied-moves and results-recent, and the stale-while-revalidate quotes, were not done.
- failure: In market hours the trader opens EQS or WTCH in a new window and the results-avoid badges arrive about 1.1 s late. EVTS shows its implied-move table after about 1.5 s on every visit, and WEI shows numbers after 1.7–3 s on any visit more than 60 s after the last. Each extra window pays again.
- fix: Logic stays unchanged. Add a stale-while-revalidate, single-flight cache in ui-api (or data-service) for /results-recent keyed by days, and for /results-implied-moves keyed by days, with a 5-minute TTL. Invalidate them on the nse_results / F&O bhavcopy ingest (the EOD job) so freshness is unchanged. Serve /api/news-scanner/quotes stale-while-revalidate for up to 5 min with a background refresh. Warm the BRF, EQS and EVTS endpoint set once after ui-api starts. Then re-run ui_perf and record the settled p95 in perf_baseline.md.

## C-PERF-02 [major] Gold-preopen's 30 s Yahoo TTL is shorter than the 60 s UI refresh, with no stale-while-revalidate, so almost every CMDT/BRF refresh is cold (0.47–3.56 s)
- verify: REAL->minor
- file: services/ui-api/routers/gold_preopen.py:264
- evidence: YAHOO_TTL_S defaults to 30 s (gold_preopen.py:264); ui/components/GoldPreOpen.tsx:19 sets REFRESH_MS = 60_000 (setInterval at :114). Curl with the UI's parameters: 0.803 s cold, 0.053–0.067 s for 4 calls within 30 s, then 0.472 s again 35 s later. ui_perf: gold-preopen was CMDT's dominant call at 615 ms (WebKit) and BRF's at 634–727 ms. CMDT settled p50 was 838 ms (Chromium) and 1,599 ms (WebKit). In the quiet WebKit re-run, gold-preopen took 3,558 ms and CMDT settled at 5,828 ms. Each miss starts 6 Yahoo chart fetches.
- failure: The trader keeps CMDT open before the 09:00 MCX open. Every minute the panel shows UPDATING for 0.5–3.5 s because each refresh misses the 30 s cache. Switching back to CMDT or BRF after a minute shows a loading gold verdict for the same time; when Yahoo is slow, the gold desk takes several seconds.
- fix: Use stale-while-revalidate: return the cached series immediately while it is younger than e.g. 120 s, and refresh in the background, single-flight (the existing in-flight map). Alternatively set the TTL to at least 75 s so a 60 s refresher hits. The computation is unchanged; the as_of fields already show the data's age. Warm the 6 series when ui-api starts.

## C-PERF-03 [major] The idle CPU/RSS figures (2.6 % now, 0.79 % this morning) come from a 60 s screen-locked window 12 s after launch, so they measure start-up, not idle
- verify: REAL->major
- file: scripts/desktop_qa/run_selftest.py:575
- evidence: Both selftest_report.json files (switchover/app_selftest and app_selftest_wave2) record idle_resources over 60.5–60.6 s with screen_locked true; --warmup defaults to 12 s (:575). The wave-2 window was about 15:37:54–15:38:54. ui-api had started at 15:35:49 (ps lstart pid 81132) and release 20261025-153533 had gone live at 15:36:00 (app log), so BRF's ~30 calls hit cold caches (gold 0.80 s, results-reacting 2.66 s cold, then 1 ms). ui_perf's post-load window shows the page's warm-up fetching 44 JS files (394 kB) in its first seconds. My steady-state samples of the same installed app 6–50 minutes after launch are 1.87 % (119 s, ps), 1.853 % (90 s, rusage) and 1.931 % (30 s). Even then, macOS runs WebContent's main thread at priority 4 (background) while the screen is locked, so a visible window is still unmeasured. boot_page_painted was skipped in both runs (AC-13 boot paint < 0.5 s unmeasured in the app). There is no 1- versus 3-window or EQS measurement. Neither fix round nor wave 2 records an outcome for C2-performance-05.
- failure: AC-13 '< 3 % CPU, < 500 MB' is signed off from a 60 s locked-screen start-up sample. A visible window during market hours, or the 3–8 windows that session restore allows, has never been measured. The 2.6 % vs 0.79 % gap is read as a regression when it mostly reflects cold caches.
- fix: Run run_selftest.py --live --warmup 120 --idle 600 with the screen unlocked and the window visible. Measure 1 and 3 windows, on BRF and on EQS. Record per process and per thread (the read-only proc_pidinfo thread sampler in my scratch dir, threads.py). Budget on phys_footprint. Measure boot_page_painted unlocked. Record the results in perf_baseline.md and never take the sample within 5 minutes of a ui-api restart or release swap.

## C-PERF-04 [minor] The idle shell wakes about 200 times a second (~1.1 % CPU), almost all in WebKit's CVDisplayLink and libpas scavenger threads; the Rust pollers cost about 0.08 %
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:535
- evidence: proc_pid_rusage on pid 83455: 198.8 wakeups/s and 1.074 % over 90 s at 15:50; 199.8 wakeups/s and 1.263 % over 30 s at 16:28. Named per-thread CPU (PROC_PIDTHREADINFO, read-only) over 30 s and 60 s: 'JavaScriptCore libpas scavenger' 0.63–0.66 %, main 0.22 %, CVDisplayLink 0.18–0.20 %, all tokio-rt-workers together ≈ 0.08 %, child processes (launchctl) 31 ms per 90 s. The display link and the scavenger run continuously; a 250 ms series shows them rising and falling together. The page has no running animation (document.getAnimations() at 15 s, 60 s and 10 min: none running) and no rAF loop (only QuantKPICard's finite one). An idle Safari UI process under the same locked screen used about 0.00 % with no active display link.
- failure: On a MacBook the always-on app (login item, KeepAlive) keeps a 60 Hz display link and about 200 wakeups/s running all day with nothing changing on screen. That costs energy, and every extra window may add to it. It cannot be ruled out that it gets worse with the screen unlocked.
- fix: With the screen unlocked, profile the shell in Instruments (Time Profiler plus Energy Log) to find who starts the display link: WKWebView / remote layer tree, tao's run loop, or the strip's 1 Hz DOM updates. Check whether hiding or minimizing the main window stops it. If a window property or polling mode keeps it alive, fix it there. Add an idle wakeups/s budget (e.g. < 50 for the shell) to the self-test, using ri_pkg_idle_wkups + ri_interrupt_wkups, which run_selftest's _RUsage already reads.

## C-PERF-05 [minor] Each 8 s status heartbeat costs the page about 20–30 ms of CPU (React state update, re-render, and a fresh evaluateJavaScript), about 0.3 % per window
- verify: not verified (minor/nit)
- file: ui/components/desktop/PlatformShell.tsx:143
- evidence: Over 90 s (rusage, 100 ms steps), WebContent 83523 burns CPU in bursts at t≈1, 9, 17, 25, 33, 41, 49, 57, 65, 73, 81, 89 s: 49, 12, 12, 41, 31, 14, 11, 8, 34, 11, 7, 23 ms, plus a 2–8 ms tail. This matches STATUS_HEARTBEAT = 8 s (health.rs:43). On every beat lib.rs broadcast_status_if_due calls window.eval(shell_event_js(...)), so WKWebView compiles a fresh script, and handle() always calls setStatus with a new object plus setStatusAt. PlatformShell and TitleStrip re-render even when change_key is unchanged. The morning app used a 30 s heartbeat (round-1 C2-performance-10). The cost multiplies with every window broadcast() reaches.
- failure: With 3–8 restored windows, the 8 s heartbeat alone wakes and re-renders every window about 7.5 times a minute with nothing changing on screen. That is roughly 1–2.5 % of extra CPU spread across helpers and a share of the idle CPU budget.
- fix: Keep the ≤ 10 s contract but make an unchanged beat cheap. In the page, compare the incoming status's change_key-equivalent fields; when nothing visible changed, update only statusRxRef/statusAt refs, with no setStatus. Have the stale check read the ref on its existing 5 s tick. In Rust, deliver events through Tauri's event channel (app.emit_to) instead of evaluateJavaScript, and skip hidden or minimized windows.

## C-PERF-06 [minor] Each window polls the page chrome at about 27 requests/min while idle; 16/min are NIFTY polls that continue with the market closed and duplicate the shell's own poll
- verify: not verified (minor/nit)
- file: ui/components/MarketCommandHeader.tsx:98
- evidence: 10-minute idle on BRF (Chromium, desktop mode faked, WS mocked): 27.0 req/min, unchanged every minute. WebKit 2 min: 26.5/min. Breakdown: /api/data/live/index/nifty 12.00/min (setInterval 5 s, :98), /api/market/nifty-live 4.00/min (15 s, :83), data health/ready/provider 2/min each (AppContext 30 s), alerts feed, gift-nifty, news quotes, indices-live and news scans 1/min each. The run was Sunday with the market closed. The shell already polls /api/market/nifty-live every 15 s (health.rs poll_market) and sends nifty in every status event. Round-1 C2-performance-09's fix (one poller elected for all windows via BroadcastChannel, or let the shell push NIFTY) was not done; W2-API marked the item fixed for the server hub only.
- failure: After a restore of 8 windows, ui-api and data-service get about 216 chrome requests/min plus the shell's ~57/min, all for the same NIFTY and status data. On a weekend or overnight the 5 s NIFTY poll serves nothing new.
- fix: In desktop mode use the shell's status.nifty for the header when the ICICI socket is not streaming. Back the 5 s poll off to 60 s when nseSession() is CLOSED and pause it while document.hidden. Optionally elect one leader window per origin with BroadcastChannel for the global chrome polls. Trading logic is untouched (display only).

## C-PERF-07 [minor] ui_perf.py does not mock WebSockets, so every run against live :8010 opens live monitor sockets (the 14:40 incident class)
- verify: not verified (minor/nit)
- file: scripts/ui_perf.py:389
- evidence: grep finds no route_web_socket in scripts/ui_perf.py. new_perf_context (:389) adds only the prefs-mode script and the perf script, and install_write_guard routes only /api HTTP. Each cold context loads the terminal, which opens /api/monitor/ws/monitor. My run needed a wrapper (scratch perf_wsmock.py) that adds context.route_web_socket; it mocked 6 sockets in the full run and 2 in the re-run. scripts/desktop_qa/e2e_compare.py:69 already shows the pattern. PLAN AC-13 names ui_perf.py as its measurement tool.
- failure: Whoever next runs the documented command (`ui_perf.py --base http://127.0.0.1:8010 --browser both --runs 3`) churns 6+ live monitor sockets through ui-api. The round-1 hang root cause was exactly fast monitor-socket churn. The monitor hub now survives churn, but the harness still breaks the 'no live sockets' rule and adds Redis-subscriber churn while a measurement is running.
- fix: In new_perf_context, mock every WebSocket by default: context.route_web_socket(re.compile('.*'), handler) with no connect_to_server. Add a --live-ws flag that is refused unless --base is a scratch server (/__qa/health answers). Record ws_mocked in the result meta, and add a test next to test_ui_perf_contexts_are_readonly_by_default.

## C-PERF-08 [nit] Every quote message replaces the whole liveQuotes object, so StockTable reconciles 1,500 memo rows per message: 12 % main thread at 1 Hz × 21 symbols
- verify: not verified (minor/nit)
- file: ui/context/AppContext.tsx:159
- evidence: cperf.py eqs (Chromium, monitor WS mocked, 21 symbols at 1 Hz for 30 s, 630 messages): main thread 12.23 % busy (CDP TaskDuration), 0 long tasks, 19.2 style recalcs/s. WebKit: 537 ms of event-loop lag over 30 s, max 68 ms, no freezes over 120 ms. Round 1 was 36 freezes/min and 3.9 s/min blocked at 0.2 Hz, so wave 2 fixed the stutter. setLiveQuote (:159) runs setLiveQuotes(prev => ({...prev, [sym]: quote})) once per message, and StockTable's useLiveQuotes effect walks every entry on each change.
- failure: In market hours with a 30–50-symbol watchlist ticking at 1–2 Hz, EQS keeps one core 20–40 % busy (Chromium estimate; WebKit similar). That costs battery but causes no visible stutter.
- fix: Buffer incoming quotes in a ref and flush once per animation frame, or every 250 ms, with a single setLiveQuotes merge. StockTable can then diff only the changed tickers.

## C-PERF-09 [nit] First-load JS has grown to 274.0 kB gz (budget 300): +10.7 kB since round 1 and +16.9 kB since D4
- verify: not verified (minor/nit)
- file: ui/app/page.tsx:1
- evidence: The live index.html's first-load chunks (fetched over HTTP, gzip-6, polyfills nomodule excluded) total 274.0 kB gz / 889.1 kB raw. ui_perf cold rows agree (js_gz 274.0). The largest are app/page 59.1 kB, 87c73c54 54.4 kB and 1601 50.1 kB. D4 measured 257.1 kB and round 1 263.3 kB.
- failure: A few more eager imports in page.tsx (the shell, formatter kit, error reporting) push first-load JS past 300 kB, and AC-13 fails without anyone noticing.
- fix: Add a CI check on build_ui output (e.g. ui_perf --bundle-dir) that fails above 290 kB. Move rarely used shell pieces (migration notice, client-error reporter, chunk recovery) behind dynamic import.

### claimed fixed but not
- C2-performance-04 (W2-API outcome 'fixed'): only gold-preopen and DEXP were changed. results-recent (0.97 s per call at days=95) and results-implied-moves (0.74 s per call) are still uncached, and quotes have no stale-while-revalidate. The gold-preopen cache is a 30 s TTL with no stale-while-revalidate, so a 60 s UI refresher almost never hits it (0.47 s after expiry, 3.56 s when Yahoo was slow). Settled p95 is 1.2–1.6 s.
- C2-performance-09 (W2-API outcome 'fixed'): the server half is done (one Redis subscription; I saw 1 Redis connection on ui-api). The UI half, one set of chrome polls for all windows, is not: each window still polls at ~27 req/min idle, 16/min of it NIFTY.
- C2-performance-05: no outcome recorded in fix round 1 or wave 2. Idle CPU/RSS is still a 60 s screen-locked sample 12 s after launch, with no unlocked run, no 1/3-window run and no boot_page_painted.
### not checked
- Idle CPU/RSS with the screen unlocked and the window visible: the session was locked the whole time (CGSSessionScreenIsLocked = 1 since 11:42). WebContent ran at background priority 4, so my 1.85–1.93 % is a locked-screen number.
- Multi-window cost (3–8 restored windows) and the app's boot_page_painted: I did not launch the app or open windows in it.
- Who starts the CVDisplayLink in the shell: that needs Instruments or `sample` on the app, which I avoided (read-only brief, no process suspension).
- Market-hours behaviour with real ICICI ticks; my tick tests used a mocked socket.
- A trading-day memory trend. App WebContent footprint went 58.7 MB (15:50) → 85.9 MB (16:28) → 86.1 MB (16:31). It looks flat at the end, but 40 minutes is too short to rule out slow growth.
- Clean server latencies: my first ui_perf run (16:03–16:09) overlapped the PM's WebKit parity run, which ended at 16:16. The quiet re-run (16:29) was worse because of Yahoo upstream latency, so settled numbers vary between 1.2 and 1.6 s.
- ui-api CPU at idle with only the app attached: other agents' traffic was present throughout.
- The installed app's autostart check: the wave-2 selftest_report shows autostart FAIL (loaded: false at 15:37). This is outside C-PERF; the app has since been started by the login job (15:39:19, app log).

# completeness-final — SHIP-WITH-FIXES

I looked for risks that none of the 8 final reviews covered, and checked 6 of them myself using code, logs, read-only system settings and live GETs (no browser, no app launch, nothing written).

What I could not break:
- The PAPER-ONLY guard covers every order path in ui-api: /order, /rebalance with dry_run=false and /liquidate. It fails closed.
- The trading-rule files have not changed since 27–29 Sep.
- Every internal caller uses a loopback URL, so the new HTTP guard does not block the scheduled jobs. Today's logs show only critics' probe rejections.
- The freeze windows are computed in IST in both Rust and the watchdog, whatever timezone the Mac is in.
- Holidays come from NSE's holiday master, not a hard-coded list.
- The app's own log rotates, and /api/client-errors is rate limited.

What nobody examined, and is not production-grade:
1. **No version control.** None of the production system is in version control. The last commit is from 14 Jun. There are 563 untracked, 124 modified and 59 deleted files, there is no remote, Time Machine is off, and backups sit on the same disk. The running app and the UI release are both built from '0ae66db-dirty'. For the backend files edited during the program there is no 'before' copy, so 'logic unchanged' is proven only for ui/.
2. **Native price alerts were dropped.** Round-1 C1-desktop-native-06 [major] was deferred, then never taken up in wave 2. The app shows a price-alert notification only while WTCH is the active page. The controller still sends every alert through osascript, so it appears as 'Script Editor'.
3. **A crashed page stays black.** Round-1 C1-desktop-native-02 [major] was marked 'refuted' with no reason given, and it looks real. wry always implements WebKit's crash callback, which turns off WebKit's own auto-reload. The shell registers no handler, so a crashed page leaves a terminal window black until ⌘R.
4. **Unattended reboots leave everything down.** FileVault is on, macOS installs updates automatically, and the Mac does not power back on after a power cut (autorestart 0). The Mac booted 4 times in about 4 days. Every job is a per-user LaunchAgent, so after any such reboot the whole 24×7 stack and the app stay down until a person logs in. This is about the triggers; SECREL-02 covers only detection.
5. **Redis has no supervisor.** It is not watched by the watchdog, the app or the controller. data-service's NIFTY poller stops using Redis for good after one failed reconnect, so live ticks can stop silently while every status light stays green.
6. **No plan for the first trading day.** All of the final backend code went live on a Sunday and has never run a session. There is no first-trading-day checklist and no commit to roll back to.

None of these is a blocker on its own. Items 1 and 4 are actions for the owner and should be done before calling this production-grade.

## completeness-final-01 [major] The production system exists only as an uncommitted working tree on one disk: no commit since 14 Jun, no git remote, no Time Machine, backups on the same disk, and no backend 'before' copy
- verify: not verified (minor/nit)
- file: reports/desktop_app/PLAN.md:75
- evidence: Version control:
- `git log -1`: 0ae66db, 2026-06-14.
- `git status --porcelain`: 563 untracked, 124 modified, 59 deleted. The untracked files include desktop/, shared/http_guard.py, services/ui-api/routers/monitor.py, services/ui-api/static_ui.py, scripts/build_ui.sh, ui/components/desktop/, ui/lib/platform/ and ui/lib/prefs/.
- `git remote -v` is empty and `git stash list` has 0 entries.

What is running:
- The installed app: `SuryaDhana --version` gives `1.0.0 (0ae66db-dirty-fc2248df-20261025T1005Z)`.
- GET /version: ui_build `20261025-153533-0ae66db`, git_sha 0ae66db, git_dirty true.

Backups:
- `tmutil destinationinfo`: 'No destinations configured'.
- scripts/db_backup.py:43 writes DEST_DEFAULT = ROOT/data/backups/duckdb on the same internal disk (20 GB; the data volume is 73% used).
- The PM backups are in ~/.suryadhana_pm_backups (same disk). The agents' 'orig' copies are under /private/tmp (lost at reboot).

Baseline:
- The 'logic unchanged' proof (baseline_preprogram/README.md) covers ui/ only.
- scripts/master_controller.py and services/data-service/main.py were edited on 25 Oct at 12:15 and 12:14. I found no copy of either from before those edits, in ~/.suryadhana_pm_backups or in the fx-py scratch. Git HEAD is 4 months older.
- W2-OPS open issue: 'ci.yml can only run once .github/, desktop/, ui/ and scripts/ are committed'.
- failure: Any of these loses the only copy of the desktop shell, the HTTP guard, the monitor-hub fix, the static serving and 4 months of earlier work (Bloomberg program, alpha_lab):
- a disk failure;
- an agent or owner running `git checkout -- .`, `git clean -fd` or `git stash -u`;
- a bad patch applied over a file.

If Monday shows a regression, there is no known-good commit to diff against or roll back to. The 'logic unchanged' claim for the backend files edited during the program cannot be checked. CI cannot run.
- fix: Owner action, today:
1. Git-ignore .logs/, .pids/, data/, ui/dist/, ui/.build-ui/ and any screenshots that may hold the ICICI login URL.
2. Commit the tree on a branch.
3. Tag the deployed state (for example `desktop-20261025`, which matches the release id and the app build id).
4. Push to a private remote.
5. Turn on Time Machine, or another off-disk copy, for the repo and data/backups.

For future programs: record a sha256 manifest of every backend file at program start, the same way the UI baseline does.

## completeness-final-02 [major] Round-1 C1-desktop-native-06 [major] was deferred and then silently dropped: the app shows a price-alert banner only while WTCH is the active page; the controller still sends every alert as 'Script Editor'
- verify: not verified (minor/nit)
- file: ui/app/page.tsx:602
- evidence: History:
- fix_round1.md:365 records C1-desktop-native-06 as 'deferred' (design only; 'not fixed because: Brief item 7').
- None of the 6 wave-2 JSON files mentions it, and none of the 8 final reviews reports it.

Code today:
- The app's only price-alert path is WatchMonitor (components/WatchMonitor.tsx:128) → notifyHits (lib/alerts.ts:119-121) → platform notify.
- WatchMonitor is rendered only while 'watch' is the active tab (page.tsx:602, `case 'watch': return <WatchMonitor />`).
- Grepping desktop/src-tauri/src for alerts/feed or _notify_mac finds nothing: there is no shell-side alert poller.
- scripts/master_controller.py:739-747: _notify_mac still runs /usr/bin/osascript `display notification` for every price, filing, move and closing note.

Live: the installed app's only window is at http://127.0.0.1:8010/?tab=movers (state.json, 16:54).
- failure: The normal setup is one window on BRF or MOV, or the window closed to the menu bar. A WTCH alert level crossed at 11:00 then produces no SuryaDhana notification. It shows only as a 'Script Editor' banner and on Telegram. If the owner allowed SuryaDhana but not Script Editor in Notifications or Focus, there is no banner on the Mac at all. When WTCH is open, every crossing produces two banners.

Two statements are false for price alerts:
- PLAN §1: 'Native notifications (price alerts …)' and 'Closing the window keeps the app (and its notifications) alive in the menu bar'.
- AC-8: 'Native notifications … work'.
- fix: Implement the design already written in fix_round1.md:365:
1. A Rust poller on GET /api/alerts/feed every 15–30 s. It de-duplicates by (kind, at, title) in state.json and posts through tauri-plugin-notification. A click opens WTCH, EVTS or BRIEF according to the kind.
2. The shell touches an 'alive' file every 60 s. While that file is newer than 180 s, _notify_mac skips osascript. Keep osascript as the fallback for when the app is not running.
3. Inside the app, WatchMonitor stops calling notify().

Also give this item an owner, so deferred findings cannot drop out between rounds.

## completeness-final-03 [major] A crashed web-content process leaves a terminal window black for good: wry's empty crash callback turns off WebKit's auto-reload, and the shell registers no handler (round-1 C1-desktop-native-02 was 'refuted' with no reason given)
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:936
- evidence: History: critics_round1.md:461 records C1-desktop-native-02 as `verify: ['REFUTED->not-a-defect']` with no rationale, so it never received a fix outcome.

Shell code:
- `on_web_content_process_terminate` appears nowhere in desktop/src-tauri/src, although tauri 2.12.5 provides Builder::on_web_content_process_terminate (~/.cargo/registry/.../tauri-2.12.5/src/app.rs:1910). The builder is at lib.rs:1147.
- navigator_tick (windows.rs:936-975) acts only on Boot and Loading windows. A dead Terminal window stays Terminal, and the status events keep eval()-ing into a dead page.

wry 0.57.1:
- It declares `webViewWebContentProcessDidTerminate:` on its navigation delegate class unconditionally (wkwebview/class/wry_navigation_delegate.rs:100).
- When no handler is set, the method does nothing (wkwebview/navigation.rs, web_content_process_did_terminate).

WebKit: WebPageProxy::dispatchProcessDidTerminate auto-reloads (tryReloadAfterProcessTermination) only when the navigation delegate does not implement that selector. wry's empty implementation therefore turns the reload off.

Memory context: data-service RSS is 1.19 GB and ui-api 490 MB, next to a 4 GB DuckDB.
- failure: A WebKit content process crashes (a WebKit bug, a GPU-process reset, or a kill under memory pressure on a long trading day with several windows). The window turns plain black: no title strip, no banner, no error. If the main window was hidden to the menu bar, it is black when reopened from the tray. Only View ▸ Reload (⌘R) brings it back, and nothing on screen says so. An unattended login-started terminal is the case where nobody notices.
- fix: Register `.on_web_content_process_terminate(...)` on the tauri Builder:
- log the crash;
- set the window to Loading and reload it, or call navigate_to_terminal, with backoff (for example at most 3 times in 5 minutes);
- after that, send it to the boot page with 'page crashed — ⌘R / Retry'.

Add a --self-test case that kills its own WebContent pid and asserts the window recovers.

## completeness-final-04 [major] Unattended reboots are enabled and undocumented (macOS auto-update on, no power-on after a power failure), and with FileVault on plus LaunchAgents only, each one takes the 24×7 stack and the app down until a person logs in
- verify: not verified (minor/nit)
- file: docs/RUNBOOK_RESTORE.md:269
- evidence: Read-only checks:
- `fdesetup status`: 'FileVault is On'.
- /Library/Preferences/com.apple.SoftwareUpdate: AutomaticallyInstallMacOSUpdates = 1, CriticalUpdateInstall = 1, AutomaticDownload = 1.
- `pmset -g`: autorestart 0, so the Mac stays off after a power failure.
- There is no autoLoginUser.
- `last reboot`: Thu 22 Oct 16:32, Sat 24 Oct 15:28, Sat 24 Oct 15:36, Sun 25 Oct 10:57. That is 4 boots in about 4 days; the last one ended the 24→25 Oct 18-hour outage.

Every SuryaDhana job is a per-user LaunchAgent: com.suryadhana.watchdog, com.suryadhana.awake and SuryaDhana (all in ~/Library/LaunchAgents).

scripts/install_launch_agents.sh:8-10 and RUNBOOK:269 accept 'after a reboot nothing runs until someone logs in' as a given. They name neither trigger (automatic macOS install, autorestart off), so the triggers stay switched on.
- failure: macOS installs an update overnight, or a power blip happens while autorestart is 0. The Mac then waits at the FileVault/login screen, or stays off. Everything stays down until the owner physically logs in:
- the 02:15 backup;
- the 08:00 ICICI login;
- the trading day's ingest;
- the 18:30 EOD pipeline, the 19:30 Desk and the 19:50 S1 shadow (paper);
- the Telegram bot;
- the desktop app.

HEALTHCHECK_PING_URL is unset (SECREL-02), so nobody is told. SECREL-02 covers detection; this finding is about the preventable triggers.
- fix: Owner actions, to record in RUNBOOK §'What still needs a human':
- `sudo pmset -a autorestart 1`.
- Turn off automatic installation of macOS updates; keep the download on. Install updates by hand on a weekend with `sudo fdesetup authrestart`.
- Set up the dead-man ping (SECREL-02).
- Make an explicit decision about FileVault versus unattended recovery.
- Show the pmset and SoftwareUpdate state in `install_launch_agents.sh status` and in Telegram /status, so drift is visible.

## completeness-final-05 [minor] Redis, the live-quote bus, is supervised and monitored by nothing, and data-service's NIFTY poller stops using it for good after one failed reconnect, so ticks can stop with every status light green
- verify: not verified (minor/nit)
- file: scripts/stack_watchdog.sh:41
- evidence: Supervision:
- CORE (stack_watchdog.sh:41) does not include Redis.
- Redis is started only as a side effect of starting a core service (start-local.sh:355 and 886), with `--save "" --appendonly no`, so the `monitored.stocks` set does not survive a restart.
- `grep -i redis` finds nothing in stack_watchdog.sh or desktop/src-tauri/src/health.rs, and the controller only mentions the mirror (master_controller.py:787).

data-service, services/data-service/main.py:
- 183-190: a failed connect at startup sets redis_client = None.
- 250-257: after a publish failure followed by a failed ping and a failed reconnect, the NIFTY poller sets redis_client = None and never creates a client again.
- The watchlist poller (282-292, loop condition `redis_client is None` → sleep) never creates a client if Redis was down when it started.

Live: redis-server pid 2578 listens on `*:6379` with protected-mode yes and no password. Protected mode refuses LAN clients; the macOS firewall is off.
- failure: Redis exits during market hours (a crash, OOM, or someone running `redis-cli shutdown`, which start-local.sh's own stop message suggests). The watchdog sees 3 healthy services and does nothing. Monitor-socket ticks, the WTCH watchlist quotes and the 'monitored.stocks' registry stop or disappear, while the tray, the strip and /ready stay green.

Even after Redis is restarted by hand, the NIFTY poller publishes nothing until data-service restarts, and restarting data-service is forbidden 07:45–09:20.
- fix: - Add a Redis check to the watchdog (`redis-cli -h 127.0.0.1 ping`). Restart it when it is down; it is stateless, so the freeze windows do not matter.
- Report it in /ready or ShellStatus as the TICKS dependency.
- Make both data-service pollers retry client creation on every loop instead of keeping None.
- Start Redis with `--bind 127.0.0.1 -::1` explicitly.

## completeness-final-06 [minor] The final backend code has never run a trading session, and there is no first-trading-day checklist or rollback recipe for Monday
- verify: not verified (minor/nit)
- file: reports/desktop_app/final/audit_8010.log:1
- evidence: When the code went live:
- ui-api pid 81132 has been up 1h09m and data-service/master-controller 1h18m (ps at about 16:50 IST on Sunday 25 Oct). All of the final backend code (http_guard, PAPER guard, monitor hub, loop-stall watchdog, gzip, client-errors, prefs migration) went live on a non-trading day.

No plan:
- `grep -i 'monday|26 oct|first trading day|soak|canary'` over reports/desktop_app/{final,switchover} and docs/RUNBOOK_RESTORE.md: no hits.

No production runs yet:
- Today's http_guard.rejected lines on all 3 services are critics' probes or rebinding tests.
- loop_stall fired only once, for the SIGSTOP drill.

So the following have zero runs on this code:
- the guard against real job traffic;
- the monitor hub under real Breeze ticks;
- the 08:00 login path;
- the 18:30–21:15 chain;
- the first 02:15 settings-store backup.
- failure: A regression first shows on Monday at 09:15 (ticks through the new hub) or in the 18:30 EOD → 19:30 Desk → 19:50 shadow chain, for example a host or origin mismatch for a job path no test covers. With no checklist, the owner finds out from a missing Desk report. With no commit (completeness-final-01), the rollback is a manual restore of scattered PM backups.
- fix: Write a one-page Monday checklist:
- 08:05: ICICI login job outcome.
- 09:20: live.quotes flowing (`redis-cli PUBSUB NUMSUB live.quotes`, monitor tick counts) and no http_guard.rejected lines apart from probe paths.
- 15:35 and 21:20: job outcomes in master-controller.log and the Desk/shadow outputs.
- 02:20: the first ui_prefs backup exists in data/backups.

Add a pre-written rollback, ideally `git checkout <tag>` once completeness-final-01 is done, plus `build-ui --rollback`.

### claimed fixed but not
- PLAN §1 / AC-8 'Native notifications (price alerts, service down/up)' and 'Closing the window keeps the app (and its notifications) alive in the menu bar': only service notifications come from the shell. Price alerts reach the app only while WTCH is the active page (ui/app/page.tsx:602). Round-1 C1-desktop-native-06 [major] is still deferred (fix_round1.md:365) and appears in no wave-2 result.
- C1-desktop-native-02 [major] (round-1 verify: 'REFUTED->not-a-defect', critics_round1.md:461, no rationale): the defect looks real. wry 0.57.1 always implements webViewWebContentProcessDidTerminate (wry_navigation_delegate.rs:100), which turns off WebKit's auto-reload, and the shell registers no on_web_content_process_terminate handler. A crashed content process leaves a black terminal window (completeness-final-03).
### not checked
- The WebKit auto-reload behaviour behind completeness-final-03 was not reproduced. Launching the app is forbidden and the screen is locked, and WebKit delays a crash reload until the view is visible, so a scratch WKWebView test would prove nothing. The conclusion rests on the wry source plus WebKit's WebPageProxy logic.
- Multi-window connection limits: WebKit's network process shares about 6 HTTP/1.1 connections per host across all windows. SYS's EventSource open in 6 or more windows, or several long NDJSON backtest streams, could starve other fetches. Not tested (no browser).
- A Python crash report (~/Library/Logs/DiagnosticReports/Python-2026-10-25-160501.ips): Homebrew Python 3.13.15, SIGSEGV in gc_collect_main during _Py_Finalize, 0.02 s after launch, parent already exited. No live service restarted (their pids predate it), so it was probably an agent's script. Not attributed.
- TCC 'Downloads folder' and Background Task Management (Login Items) behaviour across ad-hoc-signed rebuilds; the BTM and TCC databases need sudo or Full Disk Access.
- The 18:30–21:15 job chain, the 08:00 login and real tick load on the new code; today is Sunday and the services are GET-only.
- The cause of the 22, 24 and 25 Oct reboots and of the 24 Oct shutdown stall (/Library/Logs/DiagnosticReports/shutdown_stall_2026-10-24-153552…): not analysed.
- No browser was used and the app was not launched. Everything here comes from code, logs, read-only `defaults`/`pmset`/`fdesetup`/`launchctl print`, redis-cli CONFIG GET and live HTTP GETs.

