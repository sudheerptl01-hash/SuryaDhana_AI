# C1-trader-ux — BLOCK

From a Bloomberg user's chair, the terminal already looks the part. It is amber on black with function codes on every page. The GO bar handles ticker plus function (RELIANCE DES/FA/ERN/HP/OMON/DEAL), there are 42 pages, the BRF/OMON/MCXG/MOV/PRE pages say plainly when the market is closed, and the parity audits are clean. What stops me calling it production-grade:

(1) There is no error isolation. One unexpected field in one API response replaces the whole window with a minified stack trace. The title strip, header, GO bar and navigation all go. I reproduced this in WebKit.

(2) The resilience UX promises more than it does. After LINK UP the banner says "the terminal resumes on its own", but every panel that failed stays "Unavailable: Network Error". I saw this both in my drill and during the PM's real ui-api restart. Separately, one non-essential bootstrap call (enrichment-status) failing blocks all 42 pages with a wrong "ui-api may be starting up" diagnosis while every light is green.

(3) Status is contradictory or misleading:
- The chrome shows two clocks (1 s apart in one frame), two session clocks with different rules (the header will say green "NSE OPEN" on the 10 Nov and 24 Nov holidays), two brands and two sets of service lights.
- The footer "● READY" stays green during LINK DOWN.
- The title-strip dots go grey 27% of the time in steady state, because the shell's 30 s heartbeat is longer than the UI's 20 s staleness limit.
- On a "PAPER ONLY" product the PORT page (Alt+0) shows the legacy engine as LIVE with the LIVE⚡ toggle selected.
- PORT and BRKR print the ICICI login URL with its API key in plain text. That URL is now also in the audit screenshots under reports/, which git does not ignore.

(4) Prices are misreported or formatted inconsistently. Desk "Last" rounds to 1 decimal: CUPID 311.65 shows as ₹311.70→₹311.7 (MOREPENLAB 125.99 shows as ₹126.0). Several price columns have ragged decimals. NIFTY appears with 0, 1 or 2 decimals on the same screen.

(5) Keyboard-first operation has gaps:
- Esc does not close the stock window, although the footer and the help both promise it.
- Typing a ticker does nothing until you press / first.
- There is no page history or BACK. Browser Back leaves the terminal.
- The desktop help still teaches Alt 1…0 and never mentions ⌘1–9, ⌘N or ⌘W.

(6) At the app's own default 1600×1000 window, header row 1 overflows on every page I sampled: REFRESH is cut off and a horizontal scrollbar appears.

Finding 01 is a blocker. Most of the rest are small, UI-only fixes. None of them touches trading logic.

## C1-trader-ux-01 [blocker] No per-page error boundary: one malformed API field crashes the whole terminal window to a raw minified stack trace
- verify: ['REAL->major', 'REAL->blocker']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/global-error.tsx:1
- area: resilience / error states · reproduced: True
- evidence: grep finds no componentDidCatch/getDerivedStateFromError/ErrorBoundary/error.tsx anywhere in ui/. The only boundary is app/global-error.tsx, which replaces the root layout. Repro (crash.py, WebKit, simulated shell): I client-side-mocked ONE GET (/api/market/eco-calendar?back=0&ahead=7, used by Brief.tsx:179 `new Map((eco.data?.events ?? []).filter(...))`) to return events as an object, then navigated DESK→BRF. At +3 s the result was {exc:true, strip:false, header:false}, with body text "⚠ Client-side Exception (null!=(q=null==(a=tl.data)?void 0:a.events)?q:[]).filter is not a function…" followed by 9 lines of chunk URLs. Screenshot: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/crit/C1-trader-ux/shots/crash-6s.png. The project log already records an earlier render crash of this kind ("RSK tz TypeError" in the RSCH what's-new entry).
- failure: A backend change, a partial or empty payload, or a null in any of about 200 render paths (42 pages, the stock window, hover cards) during market hours. The trader's window becomes a stack-trace page: no title strip (in the app that also removes the drag region), no GO bar, no menu-driven navigation (no goto listener), and all page state is lost. Every page is one bad payload away from this.
- fix: In ui/app/page.tsx, wrap each `{view === '<tab>' && …}` render (and StockDetailModal, NewsTerminal and CommandBar) in a small TabErrorBoundary keyed by tab. Its fallback is a terminal Panel: "<CODE> failed to render · RETRY · details", with the stack hidden behind a disclosure and the error posted to ui-api's log. The chrome (PlatformShell, MarketCommandHeader, footer) stays mounted. Reset the boundary on tab change and on reconnect. Reduce global-error.tsx to the last-resort case and stop showing stack traces by default. Remove ErrorCatcher.tsx, which is itself marked "DIAGNOSTIC TOOL. Remove once the root cause is identified", or gate it behind a dev flag.

## C1-trader-ux-02 [major] After LINK UP, panels that failed during the outage stay 'Unavailable: Network Error'; the banner's 'the terminal resumes on its own' is false
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/ShellNotices.tsx:30
- area: resilience / connection banner · reproduced: True
- evidence: Drill (scenarios.py step 7, client-side abort of /api/** plus shell status ui_api.up=false). The LINK DOWN banner appeared correctly. At 32 s BRF panels showed "Loading…" indefinitely while the header still showed NIFTY 22,600.00 with the "● NSE" chip. After unrouting and status up=true, 21 s later: strip dots green and banner gone, but every BRF panel still read "Unavailable: Network Error" and Scheduler read "offline" (recovered_body_has_error=true; shots/s-recovered-21s.png). Real-world confirmation: during the PM's actual ui-api restart (new pid 42312, 11:49:02) my 1100×700 run captured DERV showing only "▲ Load failed  [RETRY]" (shots/d1100-derivatives.png). Banner copy ShellNotices.tsx:30: "the terminal resumes on its own · your pages keep their state". PlatformShell.tsx:159-163 flips to 'recovered' but tells no page.
- failure: The 18:30 EOD or ui-api watchdog restarts ui-api, or the Mac wakes from sleep. The trader returns to a green-lit terminal whose panels all say Network Error or Load failed. They must find each Retry button or switch tabs, and they may trust stale or missing panels because the chrome says everything is healthy.
- fix: On the down→recovered transition, dispatch `suryadhana:reconnected` from PlatformShell. In page.tsx, remount the active tab (bump a `key`) or have the shared useLoad/Pending helpers re-run any load that ended in error. While down, render panel state as "LINK DOWN · last data HH:MM" instead of an endless "Loading…". Change the copy to what is actually guaranteed.

## C1-trader-ux-03 [major] Every page is gated on 3 bootstrap calls (incl. a 0.9 MB 1,500-stock list); one failing non-essential call blocks all 42 pages with a wrong diagnosis
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx:598
- area: loading / bootstrap gating · reproduced: True
- evidence: page.tsx:221-244 awaits getDashboardSummary, getEnrichmentStatus and listStocks(0,1500) together. page.tsx:598-604 renders only "Backend unreachable" for every view if any of them fails. curl shows /api/stocks/list?limit=1500 = 934,658 B per window open. gate.py: a client-side 503 on /api/dashboard/enrichment-status alone, opening MCXG (which never uses it). At 8 s the page shows "BACKEND UNREACHABLE ▲ Request failed with status code 503: ui-api may be starting up (auto-retry every 10 s)" while the strip shows UI/DATA/CTRL green and the header DATA/DB green. It then alternates between "Connecting…" and "Unreachable" every 10 s (shots/gate-8s.png, gate-15s.png).
- failure: A slow or failing dashboard or enrichment endpoint (DuckDB busy during the 18:30–21:15 EOD window, a data-service sub-route error) keeps the trader out of DESK, MCXG, OMON and RSK, none of which need those calls. The message blames ui-api, which is healthy.
- fix: Mount the active tab immediately. Fetch dashboard and enrichment lazily, only for OVRV, EQS and the footer, and the stock universe only for EQS. Show a non-blocking footer chip on failure ("universe stats unavailable"). Keep the blocking screen only for a real ui-api outage, as reported by the shell or the health monitor.

## C1-trader-ux-04 [major] On a PAPER-ONLY terminal, PORT (Alt+0) shows the engine as LIVE with the LIVE⚡ toggle selected and a big LIQUIDATE & HALT button
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LivePortfolio.tsx:829
- area: paper-only posture / page semantics · reproduced: True
- evidence: GET /api/execution/status → mode "LIVE", state "ACTIVE" (secret fields excluded). The PORT header chip (LivePortfolio.tsx:829) renders a green "LIVE". The mode toggle (243-281) shows "LIVE ⚡" selected in emerald, while the banner on the same page says "running in PAPER mode only" and the subtitle says autopilot OFF. Seen in PM audit chromium/positions.png and my d1680-positions.png and d1100-positions.png. PORT is strip slot 10, so Alt+0 opens it. Its labels also disagree: strip and menu say "Portfolio", the page says "Execution Engine".
- failure: The owner, or anyone glancing at a shared screen, sees LIVE in green on a terminal that everywhere else says PAPER. That undermines trust in the PAPER posture, and the selected LIVE toggle plus "Yes, Go LIVE" flow sits one hotkey away.
- fix: UI only: render PORT's mode chip as "LEGACY · DORMANT" (grey). Show the engine's reported mode as a warning line ("engine reports LIVE · autopilot OFF · no broker session · nothing can be sent") and disable the toggle in the UI. Take PORT out of the Alt+0 slot (tabList) in favour of RSK or CHRT. Owner decision: set the dormant legacy engine's mode to PAPER (a state change, not a trading-rule change).

## C1-trader-ux-05 [major] PORT and BRKR print the full ICICI login URL (with the API key) as on-screen text; the audit screenshots now hold it under reports/, and git does not ignore them
- verify: ['REAL->minor']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LivePortfolio.tsx:659
- area: broker banner / secret hygiene in UI · reproduced: True
- evidence: LivePortfolio.tsx:659-661 renders `{status.login_url}` as plain monospace text. PortfolioSummary.tsx:229-233 renders it as the link's visible text. The PM's audit captures reports/desktop_app/switchover/audit_8010/{chromium,webkit}/positions.png (and broker.png) show the URL with its api_key parameter in full; I am not reproducing it. `git check-ignore` on those PNGs returns nothing (exit 1), so a `git add reports/` would commit them. PLAN §2.6 says the login_url must never be shown or logged.
- failure: Screen share, screenshot, the audit artifacts or a future commit expose the broker API key. On PORT the URL is not even clickable, so the user has to select and copy it.
- fix: Replace the raw URL in both components with a "LOG IN TO ICICI ↗" button that calls openExternal(login_url) and never renders the URL text (mask it as api_key=•••• if it must be shown). Add reports/desktop_app/switchover/**/*.png (or all audit screenshot dirs) to .gitignore. Make scripts/ui_audit.py mask or blank PORT and BRKR captures. Delete or redact the existing captures.

## C1-trader-ux-06 [major] Duplicated and contradictory status chrome: 2 brands, 2 clocks (1 s apart), 2 session clocks with different holiday rules, 2 sets of service lights, page identity ×3, footer READY stays green during LINK DOWN
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx:35
- area: desktop chrome / status consistency · reproduced: True
- evidence: Retina crop (shots/s-retina-chrome.png): the strip shows "11:52:24 IST" and the header shows "11:52:23" in the same frame. Strip: "◆ SURYADHANA │ DESK DECISION DESK … NSE CLOSED WEEKEND … ● UI ● DATA ● CTRL". Header right below: "◉ SURYADHANA ▸ DESK … ● DATA ● DB ● ICICI … WEEKEND". The page header then repeats "DESK DECISION DESK". The header's sessionState (MarketCommandHeader.tsx:35-43) has no holiday input. Running both functions in node for 2026-11-10 10:30 and 2026-11-24 14:00 IST (holidays from /api/market/eco-calendar) gives strip="CLOSED HOLIDAY" and header="NSE OPEN" (green). The header also has a CLOSING state the strip lacks (15:45: strip "AFTER CLOSE", header "CLOSING"). page.tsx:708 footer `loadError ? 'OFFLINE' : 'READY'` reflects only the first load: during my outage drill it read "● READY" (green) under a red LINK DOWN banner (shots/s-outage-7s.png). D4 noted the double clock but left it in place.
- failure: On Diwali-Balipratipada (10 Nov) the most prominent session chip says green NSE OPEN while the title strip says CLOSED · HOLIDAY. During an outage the footer says READY. A professional cannot tell which indicator to trust. About 75 px of the most valuable screen area repeats the same facts.
- fix: In desktop mode (html[data-sd-shell=desktop]), drop the header's brand, clock, session chip and DATA/DB lights; keep NIFTY, ICICI, alerts and refresh. In browser mode, have the header reuse session.ts nseSession() with the ECO holidays and the shared useSecondTick(). Derive the footer status from PlatformShell's banner phase (export it through context) rather than from loadError.

## C1-trader-ux-07 [major] Title-strip service dots go grey ('status is stale (shell poller silent)') ~27% of the time in steady state: UI stale threshold 20 s < shell heartbeat 30 s
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/PlatformShell.tsx:46
- area: title strip / shell status cadence · reproduced: True
- evidence: desktop/src-tauri/src/lib.rs:333-338 re-broadcasts an unchanged status only when `since >= 30 s`; change_key ignores latency and time. PlatformShell.tsx:46 sets STATUS_STALE_MS = 20_000 and :123-134 flips `fallback` (starting the browser /health monitor) after 20 s of silence. heartbeat.py emulates the lib.rs cadence exactly (a push every 30 s). Over 75 s, all three dots were grey for 20 samples (t=21-27 s and 52-58 s), with tooltip "ui-api :8010: status is stale (shell poller silent)", and the fallback /health probe fired every cycle (counter 0→1→2). Steady state covers most of the time: after 15:30, overnight, weekends and holidays, whenever NIFTY does not change.
- failure: Every evening and weekend the strip's health lights flicker grey for about 8 of every 30 seconds, and the tooltip claims the shell poller is silent. The professional learns to ignore the health lights, which defeats them on the day of a real outage.
- fix: Set STATUS_STALE_MS to at least 1.5× the heartbeat (≥ 45 s), or lower the Rust heartbeat to 10 s, or have the UI call the non-blocking cached `shell_status` every 10 s when no event arrived. Add a test that pins the two constants together.

## C1-trader-ux-08 [major] Displayed prices don't match the exchange: Desk 'Last' rounds to 1 dp; price columns elsewhere have ragged decimals; NIFTY shown with 0/1/2 dp on one screen
- verify: ['REAL->minor']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DecisionDesk.tsx:152
- area: number formatting · reproduced: True
- evidence: DecisionDesk.tsx:152 `render: w => fmtInr(w.close, 1)`. The API (/api/desk/status plans[0].summary.watchlist) gives CUPID 311.65, MOREPENLAB 125.99, FCL 57.45, PAISALO 76.41. The screen shows ₹311.7, ₹126.0, ₹57.5, ₹76.4 (PM chromium/desk.png, webkit/desk.png, my d1680-desk.png). StockTable.tsx:98-101 and 10 other sites (PreOpen, IndexMembers, DealsMonitor, AlertsCenter, LiveMovers, PriceHistory, kit) use `toLocaleString('en-IN', {maximumFractionDigits: 2})` only, so a right-aligned CMP column reads ₹189.41 / ₹1,125.3 / ₹33,100 / ₹363.05 (EQS) and PRE IEP reads 1,187 / 46.65 / 194.5. NIFTY appears as 22,600.00 (header), 22,600.0 (BRF/MOV intraday, IndexIntraday.tsx:91), 22,600 (MOV tile) and tray "NIFTY 22,600.0". CMDT shows "within ₹300 of ₹144,376" (Western grouping from the server text) next to "₹1,44,376". ALFA shows ₹3910.30 with no grouping. OSTR payoff axis mixes ₹1.3L and ₹88.9k (StrategyBuilder.tsx:112).
- failure: A trader reads ₹311.7 for a stock that closed at ₹311.65, an impossible value on the 0.05 tick grid, and ₹126.0 for ₹125.99. Ragged decimals break the decimal alignment a pro scans by, and mixed L/k units on one axis invite misreads by orders of magnitude.
- fix: Add one kit formatter, fmtPx(v) = toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}), and use it for every equity, index and commodity price column (Desk Last, EQS CMP, PRE IEP/prev, MEMB, DEAL, ALRT, MOV, HP, ALFA). Index levels always 2 dp, including the tray. Use one unit per axis or column (all ₹ L or all ₹ cr), and format server-built verdict strings client-side in Indian grouping.

## C1-trader-ux-09 [major] Keyboard gaps vs Bloomberg: Esc doesn't close the stock window, no type-to-GO, no page history/BACK (Back exits the app), desktop help still teaches Alt 1…0
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StockDetailModal.tsx:202
- area: keyboard-first navigation · reproduced: True
- evidence: scenarios.py (WebKit). stock_window_closes_on_esc=false: StockDetailModal has no Escape handler (the only 'Escape' handlers are CommandBar, NewsTerminal, ChartStudio, DataTable and MoreMenu), yet the footer (page.tsx:717 "ESC CLOSE") and help (CommandBar.tsx:304 "Esc · Close any window") promise it. type_to_go_opens_bar=false: typing TCS with no focus does nothing. page.tsx:161-166 setView uses history.replaceState, so after BRF→DESK→MKT history.length=2 and browser Back went to about:blank, leaving the terminal. menu.rs defines no Back/Forward (⌘[ / ⌘]) and no Find. Help card (shots/s-help.png, CommandBar.tsx:301) lists "Alt 1 … 0" and no ⌘1–9/⌘N/⌘W; the footer says "ALT+1…0 PAGES" while the boot page says "⌘1–⌘9 pages". Bloomberg mnemonics land wrong: GP→GPIL/GPPL tickers, TOP→SHOPERSTOP, MOST→ticker 'MOST', BACK→BTST.
- failure: The core loop is ticker ⟶ stock window ⟶ Esc ⟶ next ticker. Here Esc does nothing and the user must mouse to the ✕. After hopping TCS → OMON → DEAL there is no way back except retyping. Muscle memory from Bloomberg (GP, TOP, MOST, N, <MENU>) misfires.
- fix: Add a keydown Escape handler in StockDetailModal (when no input is focused) calling onClose. Make any printable keystroke outside inputs open the GO bar seeded with that character. Use pushState in setView with a popstate handler, and add Go ▸ Back ⌘[ / Forward ⌘] to menu.rs. In desktop mode, show ⌘1–9 / ⌘N / ⌘W / ⌘K in the footer and help. Add aliases GP→CHRT (or TICKER GP → chart), TOP/N→NEWS, MOST→MOV, BRIEF→BRF, and give exact code matches priority over substring matches.

## C1-trader-ux-10 [major] Header row 1 overflows at the app's default 1600×1000 window (REFRESH clipped, labels wrap, page-level horizontal scrollbar); also at 1680 on long page names and at 1100
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx:341
- area: layout at the app's window sizes · reproduced: True
- evidence: Measured in WebKit with the simulated shell. At 1600×1000 (windows.rs:398 inner_size), header row-1 scrollWidth vs clientWidth was 1606/1600 (BRF), 1646 (RSCH), 1643 (OVRV), 1644 (DEXP), 1653 (GBOX), 1660 (WHSE), 1657 (CMDT), and the document scrollWidth exceeded clientWidth on all 7 (metrics-mid.json). Screenshot d1600-warehouse.png shows "↻ RE" cut at the right edge, "NIFTY / 50" and the alerts bell on two lines, and the tape cut off. At 1680, the PM's screenshots show the same wrap on RESEARCH, PORTFOLIO, OVERVIEW, BACKTEST, GLASS-BOX, EXPLORER and COMMODITY. At 1100×700 row 1 overflows on MKT (1101), RSCH (1112) and PORT (1117). Separately, DESK's momentum table is clipped at 1680 in both engines (header "NEXT E", chips "FUND R"/"RESULT" cut).
- failure: On first launch, at the app's own default size, the top bar shows a horizontal scrollbar, a half-visible REFRESH button and wrapped labels. That is the first impression of 'Bloomberg-grade'. The Desk's next-event column is unreadable without discovering a hidden horizontal scroll.
- fix: Give row-1 children `whiteSpace: nowrap` and `minWidth: 0`, and let only the NIFTY block shrink. Raise the .t-hide-lg breakpoint (O/H/L, stock count, date) to about 1760 px, or drop the brand and page name in desktop mode (see -06). Check widths of 1100, 1280, 1440, 1600 and 1680 in ui_audit. On DESK, give the watchlist DataTable fixed column widths or truncate Industry so NEXT EVENT fits, and show a scroll affordance.

## C1-trader-ux-11 [minor] 160 px of stacked chrome; at the 1100×700 minimum only 541 px (77%) is content; EQS rows ~51 px tall
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx:466
- area: density / vertical real estate · reproduced: True
- evidence: metrics: strip 32 + header 106 (row1 44 + tape 26 + page strip ~36) + footer 22 = 160 px. Content height is 891 px at 1050 and 541 px at 700, plus 24 px more when the watchlist bar is non-empty. At 1100×700, DESK shows only the KPI tiles and an empty "NO TRADES THIS MONTH" panel above the fold; the momentum watchlist sits below it (d1100-desk.png). EQS (StockTable) rows are about 51 px, so about 12 rows fit on a 1050 px screen (PM stocks.png), while FUND on the same data is a dense ~26 px grid.
- failure: On a laptop or a quarter-screen tiled window, the trader scrolls for every table. EQS shows a fraction of what a Bloomberg EQS screen shows.
- fix: In desktop mode, merge the strip and header row 1 into one 32 px bar (with -06). Make the macro tape optional. Add a dense mode (row padding 3-4 px, the kit's `dense`) and apply it to StockTable. On DESK, put the watchlist above the empty-trades panel when there are 0 trades.

## C1-trader-ux-12 [minor] Header '↻ REFRESH' on every page starts a 5-year yfinance download of 1,500 stocks with no confirm, next to page-level '↻ REFRESH' buttons that only reload the page
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx:371
- area: dangerous affordance · reproduced: False
- evidence: MarketCommandHeader.tsx:371-375 → page.tsx:359-370 handleRefresh → lib/api.ts:15-16 `client.post('/api/dashboard/refresh', {universe:'nse_1500', years:5})`. DESK (PM desk.png) shows both buttons on screen, with the same label and glyph and different blast radius. I did not click it (POST).
- failure: A Bloomberg user presses the prominent amber REFRESH to update the screen and instead queues a heavy universe-wide download. It opens an indigo panel reading "Downloading 5yr OHLCV…" and loads data-service, possibly during the EOD window.
- fix: Rename it "DATA ⟳" (or move it to OVRV/PIPE), add a confirm that states scope and duration, and disable it inside the 18:30–21:15 freeze. Keep "REFRESH" for reloading the current page's data.

## C1-trader-ux-13 [minor] Closed-market and offline state not marked consistently: tray NIFTY, '● NSE', 'WS LIVE', 'STREAMING', SYS 'NOW', no Muhurat session
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/health.rs:217
- area: stale-data / market-closed semantics · reproduced: True
- evidence: Sunday 25 Oct. Tray title (health.rs:217-236, self-test "NIFTY 22,600.0 ▼0.39%") ignores the payload's `time` ("23-Oct-2026 15:30"), so the menu bar shows Friday's move all weekend with no CLOSED marker. The header shows the NIFTY change with a cyan "● NSE" live-style chip and keeps showing it unchanged during an outage (s-outage-brief-32s.png). ALFA shows "● WS LIVE" (AlphaDiscoveryDesk.tsx:352) and LiveMonitorBar shows "● STREAMING" (LiveMonitorBar.tsx:57-59): both mean the socket is connected, not that data is flowing. SYS shows 'NEXT JOB XGBoost + RL Inference Cycle NOW' with a 09:15–15:30 schedule on a Sunday. The MOV panel title reads "today vs previous close" for the last session. The hover card always says "≈1 min delayed". session.ts:54 treats every Sunday as CLOSED, although the app's own MCXG page lists "2026-11-08: Muhurat trading (Sunday evening special session)".
- failure: On weekends and holidays (most of the clock), the menu bar and several chips present Friday's numbers as live. During Muhurat trading on Sun 8 Nov every NSE session indicator will say CLOSED · WEEKEND while the market is open.
- fix: Add one shared marketState (from nseSession + holidays + a special-sessions list), and when closed suffix every last-price display with "CLOSE 23-OCT". Tray: "NIFTY 22,600.00 ▼0.39% · CL". Rename socket chips to "SOCKET OK" or show "NO TICKS (CLOSED)". Make SYS next-run weekday-aware and mark dormant jobs. Support special sessions in session.ts via the ECO feed.

## C1-trader-ux-14 [minor] ⌘−/⌘= zoom scales the CSS title strip but not the native traffic lights; zoom-out collides them with the wordmark; zoom isn't persisted
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/windows.rs:781
- area: desktop window / zoom · reproduced: False
- evidence: windows.rs:781-797 calls set_zoom (WKWebView pageZoom) on the focused window. The strip's 84 px left inset (globals.css:282) and its 32 px height are CSS px and scale with zoom; the traffic lights (windows.rs:399-402, x=14, zoom button ends at 74 px per D4) do not. Arithmetic: at 0.9 the inset is 75.6 px (touching), at 0.8 it is 67.2 px (the ◆ mark and 'S' sit under the green button), and at 0.5 (the clamp) it is 42 px with a 16 px strip, so the lower half of each light sits over the header row. WinInfo.zoom starts at 1.0 and is not part of the saved Session, so it resets on every relaunch. Not observed natively (the app may not be launched).
- failure: A user on a non-Retina external monitor zooms out to fit more columns and the wordmark disappears under the traffic lights. A user who zooms in for legibility (see -15) must redo it after every restart.
- fix: Send the zoom factor to the page (a shell event, or `window.devicePixelRatio` changes) and set the strip's padding-left to calc(84px / zoom) and its height to calc(32px / zoom). Alternatively clamp zoom-out at 1.0 and offer a UI density setting instead. Persist zoom per window label in state.json.

## C1-trader-ux-15 [minor] Dim text token #475063 is 2.4–2.55:1 on the terminal backgrounds and is used for 9–9.5 px labels throughout
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/news/format.ts:13
- area: typography / contrast · reproduced: True
- evidence: WCAG contrast computed for --t-dim/T.dim #475063: 2.55 on the strip (#020304), 2.49 on bg, 2.40 on panel. (--t-muted is 4.5–4.8:1 and is fine.) `color: T.dim` appears 334 times in ui/components and app; font-size 9/9.5 appears 115 times, plus the strip CSS (.sd-strip-k, .sd-strip-detail 9 px). Measured share of visible text elements under 10 px: 12–39% per page at 1680 and up to 41% at 1100 (metrics-big/small.json). Examples: strip 'NSE'/'IST'/build id, the footer brand, PRE's 'market closed today · showing the last session', panel hints.
- failure: Exactly the qualifying text (closed-market notes, as-of times, units) is the least legible on a non-Retina or bright-room display, so traders miss the very caveats meant to stop misreads.
- fix: Raise T.dim for text to at least #6a7487 (≥4.5:1) and keep the current value only for rules and borders. Set a 10 px floor for informational text. Promote as-of and closed notes to T.muted or T.amber.

## C1-trader-ux-16 [minor] Multi-window is clone-only: no 'open ticker/page in new window', no security deep link, each window repeats full chrome and polling
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/menu.rs:264
- area: multi-window workflow · reproduced: False
- evidence: menu.rs:264-276: ⌘N opens the focused window's tab. The only URL param is ?tab (page.tsx:158; pages.ts tabFromSearch), so a window cannot open on a security. Page tabs are <button>s (MarketCommandHeader.tsx:283), so ⌘-click or middle-click does nothing. ui/lib/platform newWindow() is reachable only through the anchor/window.open interceptor. The stock window is a single in-window modal. Session restore saves only ?tab (selftest: "/?tab=desk"). Per window the chrome polls every 5 s (NIFTY), 15 s, 30 s (3 calls), and 60 s (tape, news, alerts), regardless of market hours.
- failure: The classic layout (chart of TCS here, OMON for NIFTY there, DESK on monitor 2) requires ⌘N and then manual navigation in each window, and is lost on restart apart from the page. Eight windows multiply the background polling eightfold on a closed market.
- fix: Add deep links ?tab=charts&sym=TCS (and stock-window ?sym=), honoured on load and saved in the session. Make ⌘-click or middle-click on page tabs and TickerLinks call newWindow(tab, sym). Add 'Open in new window' to the stock window. Back off chrome polling when the market is closed or the window is hidden. Later: window-group security linking.

## C1-trader-ux-17 [minor] SVG charts scale their text with viewBox (axis labels ~17 px vs 9–11 px UI); OI-by-strike has no strike axis; overlapping labels; stock window off-style rounded
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/OptionChain.tsx:50
- area: charts / visual polish · reproduced: True
- evidence: DerivativesDesk.tsx:85 and OptionChain.tsx:33/58/101 use `viewBox` with width 100% and height auto, so fontSize 9-10 renders at about 16-17 px at 1680 (PM derivatives.png and options.png: 'Oct 21 … Oct 26', '70 / 16 / −38' oversized, non-round ticks). OiBars (OptionChain.tsx:50-75) labels only the first and last strike; other strikes appear only in a <title> on the call bar. OSTR payoff: 'BE 22324.9' and 'BE 22875.1' overlap, and x ticks are 19865/20948/… (non-round). Stock window: the SMA 200 legend is drawn over the red SMA 200 line, and the '14.91M' volume label covers a y-axis tick (s-stock-window.png). The stock window has about 16 px rounded corners because `md:rounded-2xl` (StockDetailModal.tsx:208) is not matched by the legacy skin's `.terminal .rounded-2xl`.
- failure: A derivatives user cannot read which strike holds the OI wall from the chart. Typography jumps between pages and window widths, and the stock window looks like a different app.
- fix: Render SVG axis text in a non-scaling overlay, or compute W from the container width (ResizeObserver) so 1 SVG unit = 1 px. Label OI strikes every N strikes plus the walls and ATM. Use 'nice' tick steps. Offset or collision-avoid the BE labels. Move the chart legend outside the plot. Add `.terminal .md\:rounded-2xl { border-radius: 2px }` (or use square classes).

## C1-trader-ux-18 [nit] Polish: duplicate step numbers, stale hard-coded date defaults, dev paths and emoji in UI copy, mixed minus glyphs, menu label, LAN access change
- verify: not verified
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/PipelineStudio.tsx:692
- area: copy / consistency · reproduced: True
- evidence: PipelineStudio.tsx:692-693: two tabs numbered '③' (Feature Inspector, Model Studio). GlassBoxStudio.tsx:39-40 defaults the range to 2025-09-01 → 2026-05-31, and MLEngineWorkspace.tsx:54-55 ends at 2025-12-31 (five months stale today). RiskDashboard.tsx:308 shows "Rules are read from CLAUDE.md…", and DESK shows "charges from shared/trading_costs.py". 🔍 (EQS Column Filters) and 🔌 (PORT banner) appear in a glyph-based terminal. fmtPct prints ASCII '-1.23%' while fmtSignedPct and the header print U+2212 '−'; units are written both 'cr' and 'Cr'. menu.rs:162 embeds "(⌘K in the terminal)" in the item title instead of an accelerator. The strip uses 'UI' for both the ui-api dot and the build chip. MCXG copy has a doubled "auto-login).)". Pending pm_lan.py makes ui-api loopback-only by default, so after switchover the iPad/phone URL (:3000) and localhost:3000 bookmarks stop working silently.
- failure: Small inconsistencies that a professional user reads as unfinished. A default GBOX render shows data ending five months ago. The owner's iPad loses the terminal after switchover without being told why.
- fix: Renumber the PIPE steps. Default date ranges to [today − N, today]. Replace dev paths with user-facing wording ("rules: Desk policy (owner-approved 2026-09-27)"). Swap the emoji for kit glyphs. Use U+2212 in fmtPct. Use one 'cr' casing. Set the ⌘K accelerator (or drop the parenthetical) and label the build chip 'BUILD'. Fix the typo. Add a line to the switchover notes and the start-local print_urls about UI_API_HOST=0.0.0.0 for iPad access (on a trusted LAN).

### strengths
- Consistent Bloomberg-style visual language across about 40 of the 42 pages: void black, amber accents, a JetBrains Mono data face with a Chakra Petch display face, 1 px square rules, uppercase micro-labels. Every page carries an amber function-code chip (BRF, DESK, OMON, MCXG, RSK…).
- The GO bar is genuinely terminal-grade. It takes the ticker-then-function grammar (RELIANCE → DES/FA/ERN/HP/SEAG/OMON/DEAL/TV/W), searches company names, keeps command recall with ↑, and opens with / or ⌘K. The ? help card lists every code. Shots: s-gobar-reliance.png, s-help.png.
- Honest closed-market messaging on the pages that matter most. BRF: 'NSE closed (weekend) · next session Mon, 26 Oct'. MKT: 'EOD 23 Oct 2026'. OMON: an EOD chip with 'NSE F&O bhavcopy 2026-10-23 · end of day'. MOV: 'market closed: last session'. PRE: 'book as of 23-Oct-2026 09:09:05'. MCXG: a CLOSED state with an 'opens in 21h 46m' countdown and its own MCX holiday calendar (including the 8 Nov Muhurat session). WEI: a last-print-age column.
- Indian number conventions are handled in most places: lakh/crore grouping (₹5,02,085, 1,03,32,756), ₹ L/cr units, and a ₹ glyph patched into the mono font so it renders the same in WebKit and Chromium. +/− colouring and tabular figures are in place.
- Tables are keyboard-navigable (click, then ↑↓ or j/k, Enter, Esc) and every DataTable has '⤓ CSV' export that goes to ~/Downloads in the app.
- The desktop shell basics are solid: no white flash, a black boot gate, the 32 px overlay strip with page code, IST clock, NSE session from the holiday feed, service dots and a NEW BUILD · RELOAD chip. The native menu has all 42 pages in 6 groups plus ⌘1–9, the tray shows NIFTY, health, ICICI and Desk NAV, and the connection banner is clear and shows outage duration.
- The 42-page parity is clean in Chromium and WebKit (parity.log: 42/42, no diff, no audit failures), and tab switches are fast once warm (0.01–0.06 s UI-ready for most pages in my WebKit run).
### not checked
- Native chrome inside the real SuryaDhana.app: traffic-light alignment, the drag region, how the native menu and tray look, notification banners, ⌘C/⌘V in inputs, and Window-menu titles. The brief forbids launching the app. I relied on the self-test JSON and a simulated __SURYADHANA_SHELL__/__TAURI_INTERNALS__ in Playwright WebKit (the same engine, not the same host). The zoom/traffic-light collision (-14) is inferred from code and arithmetic.
- Market-hours behaviour: live ticks, flash colouring, the OMON LIVE chain, the PRE auction at 09:00–09:15, Desk execution-day views, and the ICICI-connected states. Today is a Sunday and Breeze is expired.
- Clicking any state-changing control (header REFRESH, Desk PREVIEW NOW, PORT toggle/LIQUIDATE, alert creation, watchlist add, ENRICH). Their behaviour (-12, -04) is from code and the GET endpoints only.
- Sleep/wake reconnect, a real multi-monitor or multi-window layout, and session restore with 8 windows. These come from code and the PM's relaunch drill log only.
- A real WKWebView outage. My outage drill aborted requests client-side and faked the shell's down status. Separately, during the PM's actual ui-api restart and release swap (11:46–11:49), I observed DERV 'Load failed' (d1100-derivatives.png), and one tab switch in an ad-hoc probe did not become ready within 30 s. I did not capture what it showed, could not reproduce it in 5 later attempts, and do not report it as a finding.
- Screen-reader or VoiceOver accessibility, the light theme (if any), and iPad/phone layouts.
- A new UI release (20261025-114737) was published and ui-api restarted (pid 42312, 11:49:02) in the middle of my runs. The 1680 and 1100 captures were made on the 110718 build and the scenario, crash and gate runs on 114737. The findings do not depend on the build difference.

# C2-performance — SHIP-WITH-FIXES

The serving layer is fast and holds up under load. I measured static_ui.py live. index.html (gzip, no-cache) and a 73 kB hashed chunk (immutable) each answer in about 1 ms, and a 304 in 1.2 ms. First-load JS is 263,277 B gz against the 300 kB budget. While DEXP read a 352 MB parquet, the worst ui-api /live latency was 106 ms, so the event loop is not blocked. Tab-switch UI-ready p95 on the integrated :8010 is 40.8 ms in Chromium and 81 ms in WebKit. Cycling all 42 pages twice leaked no timers, listeners, sockets or DOM nodes. A burst of 8 windows restored at once was handled fine (/api/prefs p99 115 ms).

The problems are on specific pages and in idle cost:
(1) EQS takes 1.34 s to appear in WebKit, the app's engine. It then re-renders all 1,500 rows on every context change, every NIFTY tick (3 times each) and every row the mouse crosses.
(2) Every new window, restored window or reload still pays React's 300 ms Suspense throttle, about 510–570 ms in total. P7/P8 removed it for tab switches only.
(3) An endless "NEW" pulse in the news dock alone pushes an idle window past the 3 % CPU budget.
(4) Several server endpoints keep the data-settled p95 at 1.4–1.5 s, and DEXP adds about 830 MB of transient ui-api RSS per page click.
(5) The AC-13 RSS/CPU claim has no idle evidence, and my WebKit stand-in sits at 480–522 MB for one window.

The status-heartbeat mismatch, which turns the strip lights grey for about 16 % of the time, is confirmed on the served build. It is already fixed in the working tree (C1-desktop-native-03) and still has to be rebuilt.

Measurements: Chromium and WebKit through Playwright against live :8010 (GET only, prefs readonly, my own page's WS mocked for the tick tests), ps CPU-time deltas, CDP Performance metrics, and a 20-minute idle run. Scratch files: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/crit/C2-performance/ (c2_harness.py, anim_probe.py, stall_test.py, perf_out/, *.json).

## C2-performance-01 [major] EQS re-renders all 1,500 rows on every hover, every NIFTY tick (3x) and every 30 s status poll; 1.34 s to show in WebKit
- verify: ['REAL->major']
- file: ui/components/StockTable.tsx:394
- area: UI rendering / EQS (StockTable) · reproduced: True
- evidence: ui_perf sweep on :8010 (scratch copy, readonly prefs): EQS is the only page over 400 ms even for UI-ready, at 1,340 ms in WebKit and 411 ms in Chromium. Causes in code: onMouseEnter={() => setHovered(stock.ticker)} (:394) is state on the whole table. useLiveQuotes() (:123) plus the flash effect (:128-153) gives 3 full renders per tick: the context change, setFlashMap (:144) and the clear 700 ms later. AppContext.tsx:326 passes an inline value object, and the 30 s refreshDataStatus (:249) always sets lastChecked: Date.now(), so every consumer re-renders, HomeContent and the table included. Measured with a mocked monitor WS (my page only), Chromium: idle EQS has 2 long tasks/min (max 114 ms); NIFTY ticks at 0.2 Hz (the data-service poller rate) give 36 long tasks/min, 3,675 ms/min, main thread 8.86 % busy; at 1 Hz, 36.8 % busy. WebKit at 0.2 Hz: 36 freezes/min, 3,941 ms/min blocked, max 165 ms. Each row the mouse crosses costs +78.6 ms (Chromium) / +123 ms (WebKit) p50, up to 163/210 ms. BRF under the same ticks stays at 1.3 % CPU, so the cost is specific to EQS.
- failure: In market hours the owner opens EQS in SuryaDhana.app (WKWebView). The page takes about 1.3 s to appear. Then the table freezes for about 110 ms three times every ~5 s (each NIFTY tick), and moving the mouse down the list repaints at about 5–8 fps.
- fix: No change to data or logic: (1) drop the hovered state and use CSS hover (e.g. tr:hover / hover:bg-[#131926]); (2) extract a React.memo row that takes only its own live/flash/watched props, and pass stable callbacks (useCallback for onRowClick and onWatchToggle in page.tsx StocksTab); (3) split AppContext into LiveQuotes / Watchlist / DataServiceStatus contexts with useMemo'd values, so ticks and the 30 s poll re-render only their consumers; (4) window the rows (react-window), or as a first step add content-visibility:auto with contain-intrinsic-size on <tr>.

## C2-performance-02 [major] Every new window, restored window or reload still pays React's 300 ms Suspense throttle (content at ~510–570 ms)
- verify: ['REAL->minor']
- file: ui/app/page.tsx:258
- area: Window open / restore latency (P7/P8 gap) · reproduced: True
- evidence: P8's warm-up starts 3 s after mount (page.tsx:258), but windows open deep-linked (/?tab=<id>, windows.rs terminal_url). The tab's module is therefore never resolved at first render: lazyTab (:41-51) falls back to the dynamic() Suspense path and React holds the skeleton for its 300 ms throttle. A rAF-sampled title/skeleton timeline on :8010 with a faked shell shows the skeleton phase lasting exactly ~300 ms. Chromium: RSCH skeleton 266→567 ms, DESK 211→503, RSK 230→526. WebKit: RSCH 228→526, DESK 221→530, RSK 227→521, MKT 211→513. The PM's own audit agrees: readyB is 435–651 ms on most deep-linked pages and 190–200 ms on the few that do not suspend (switchover/audit_8010.log, parity.log). Tab switches inside a window are at 21–30 ms p50. Before the skeleton, every page also waits ~200–260 ms on loadDashboard (dashboard summary, enrichment status, and the 934,658 B /api/stocks/list?limit=1500) via pageLoading (:204, :598), even pages that never use stock data.
- failure: The owner presses ⌘N for DESK, or launches at login and the app restores 3 windows, or clicks NEW BUILD · RELOAD, or a chunk error triggers recovery. Each window shows a skeleton for about 300 ms longer than needed, so opening a window costs 2–3× a tab switch.
- fix: Key the warmers by tab id and start the URL tab's import when the module first evaluates on the client: `if (typeof window !== 'undefined') { const t = new URLSearchParams(location.search).get('tab'); WARM[t]?.() }`. The boot gate plus the dashboard gate give it about 200 ms of head start, so lazyTab's `resolved` is already set when the tab first mounts and no fallback is shown. Optional: initialise `view` from the URL in the useState initializer (safe, because PlatformShell renders only BootGate in the prerender), and stop gating non-EQS/OVRV pages on pageLoading.

## C2-performance-03 [major] An endless 'NEW' pulse in the news dock (and the NEW BUILD glow) keeps every idle window repainting at 60 fps, over the 3 % CPU budget
- verify: not verified
- file: ui/components/news/NewsDock.tsx:89
- area: Idle CPU (AC-13 < 3 %) · reproduced: True
- evidence: document.getAnimations() on idle BRF shows one running animation: nd-pulse, iterations Infinity, on the 6 px NewsDock dot (:89). Idle CPU over 60 s (ps CPU-time deltas): Chromium renderer + GPU + browser = 5.38 % with it running and 1.25 % after pausing it. WebKit (Playwright build; UI + WebContent + GPU + Networking) = 3.54 % vs 2.29 %, WebContent 2.27 % → 1.33 %. The NEW state stays on until the dock is opened, and newsTerminal.seenVersion is a LOCAL per-origin key, so the app starts out unseen and every new scan turns it on again. globals.css:328 .sd-newbuild also runs sd-attn (an infinite box-shadow animation that repaints every frame) in every open window after each release swap until reload. The reduced-motion block covers sd-newbuild but not nd-pulse.
- failure: The app sits on BRF all day with an unread scan, as is typical after each daily scan. Every window burns about 3.5 % CPU (WebKit stand-in) instead of about 2.3 %, which breaks AC-13's < 3 % per window and multiplies with every open window.
- fix: Make attention animations finite (e.g. `nd-pulse 1.2s ease-in-out 3`, then a static amber dot; the same for sd-attn). Animate only opacity or transform (move the sd-attn glow to an ::after with opacity). Pause when document.hidden. Add nd-pulse to the prefers-reduced-motion rule.

## C2-performance-04 [major] Data-settled p95 is still 1.4–1.5 s; gold-preopen re-fetches 6 Yahoo series on every call; DEXP reads 352 MB per page click (+830 MB ui-api RSS)
- verify: ['REAL->major']
- file: services/ui-api/routers/gold_preopen.py:460
- area: Server endpoints (data-settled tab switch, ui-api memory) · reproduced: True
- evidence: Integrated :8010 sweep: settled p95 1,461 ms (Chromium) / 1,379 ms (WebKit); 12 / 11 of 42 tabs over 400 ms. WEI 2,170–2,201 ms: /api/news-scanner/quotes takes 1.96 s cold and 1 ms warm by curl; the 60 s TTL (news_scanner.py:572) makes any visit more than 60 s after the last one cold. CMDT 1,426–1,710 ms and BRF 771 ms: /api/commodity/gold-preopen takes 0.50–0.89 s on every call (0.54 s then 0.50 s back to back), because :460 starts 6 uncached Yahoo chart requests per call, and CMDT re-polls it every 60 s per window. EVTS 1,243–1,461 ms: results-implied-moves takes 0.66 s on both consecutive calls; fundamentals-screen 0.45 s and 541 kB. DEXP 926–1,339 ms: features-explorer takes 0.86–0.95 s per pagination click, because pipeline.py:765 reads the whole 352 MB parquet on each call; ui-api RSS went from 1,885 to 2,712 MB after one call. BRF in WebKit never settled: results-reacting took 3,087 ms. Event loop during DEXP: /live max 106 ms, so it is offloaded correctly; the cost is latency and memory.
- failure: The trader switches to WEI, CMDT, EVTS or DEXP and waits 1–2+ s for numbers on every visit. Two windows paging DEXP at the same time allocate about 1.7 GB inside the process that now also serves the UI, so an OOM kill takes down the whole terminal, not just the API.
- fix: Add stale-while-revalidate caches with single-flight: gold-preopen 30–60 s keyed by its query params (or cache the 6 Yahoo bar series); quotes served stale while refreshing in the background; results-implied-moves and results-recent 5 min. For DEXP, query with DuckDB `SELECT … FROM read_parquet(?) [WHERE ticker=?] ORDER BY <col> LIMIT ? OFFSET ?` and cache the health block per (path, mtime, v, ticker). Warm the BRF endpoint set when ui-api starts.

## C2-performance-05 [major] AC-13 '< 500 MB / < 3 % for one idle window' has no idle measurement, and a WebKit stand-in sits at the budget
- verify: ['REAL->minor']
- file: desktop/src-tauri/target/selftest-up-20261024.json:1
- area: AC-13 evidence (idle RSS/CPU, multi-window) · reproduced: True
- evidence: The self-test app_total_rss of 396.7 MB is labelled 'measured right after the checks, not idle'; meta.screen_locked is true and the self-test reports no CPU. perf_baseline.md §1 says the idle window is 'not measurable here'. scripts/desktop_qa/run_selftest.py defaults to --warmup 12 and --idle 30 (:575-576), too short to cover the 30 s / 60 s pollers or any growth. My Playwright-WebKit stand-in for one idle BRF window: 480–491 MB at 25 s and 513–522 MB at 75–135 s (UI process 108 MB, WebContent 245–287, GPU 82, Networking 45; the Tauri shell itself was 99.9–104.7 MB in the self-test); CPU 3.54 % (see -03). The P8 warm-up does not move RSS (245 vs 251 MB with saveData). Each extra window adds another WebContent process (~250–290 MB) while the app restores up to MAX_WINDOWS = 8 (windows.rs:43), and there is no multi-window budget.
- failure: AC-13 is marked PASS from a 30 s sample taken about 5 s after load with the screen locked. In daily use one window idles at about 500 MB and 3.5 % CPU, and three restored windows approach 1 GB, with no number anyone signed off.
- fix: Run run_selftest.py --live --warmup 30 --idle 600 with the screen unlocked, for 1 and 3 windows, on BRF and EQS. Budget on phys_footprint (already collected as footprint_mb_peak) rather than RSS, which double-counts shared WebKit pages. Add a per-extra-window budget (e.g. < 250 MB). Record the results in perf_baseline.md.

## C2-performance-06 [minor] The hidden PipelineStudio is mounted on every page in every window and polls the dormant RL pipeline (27 % of idle requests)
- verify: not verified
- file: ui/app/page.tsx:696
- area: Polling waste per window · reproduced: True
- evidence: The comment says 'stays mounted once first visited', but the code mounts it unconditionally (display:none, :696-699), so it is mounted in every window from boot. 20-minute idle BRF (Chromium): 39.1 req/min in total, of which /api/pipeline/rl-status is 6.29/min (PipelineStudio.tsx:511, 10 s) and rl-training-metrics 4.24/min (15 s); the RL pipeline is dormant (autopilot OFF). Every window open also fires data-quality, feature-importance, model-metrics, rl-training-metrics and service-health (seen in every deep-link run), loads the PipelineStudio chunk at boot, and keeps 165 hidden nodes that re-render with HomeContent. The ui_perf EQS row even names rl-status as its 'dominant call'.
- failure: With 4 windows open on unrelated pages, ui-api serves about 42 RL-status requests per minute and 20 pipeline calls per round of window opens, for a page nobody opened.
- fix: Mount it on first visit, as the comment intends (`const [pipeSeen, setPipeSeen] = useState(view === 'pipeline')`, set it when view becomes 'pipeline'), and/or pause its intervals while view !== 'pipeline'.

## C2-performance-07 [minor] A 1 s clock at the top of MarketCommandHeader re-renders the whole header every second, unsynced with the strip clock
- verify: not verified
- file: ui/components/MarketCommandHeader.tsx:340
- area: Idle re-render (header clock) · reproduced: True
- evidence: `const now = useIST()` (:340; setInterval(1000) from mount, :26-35) re-renders NiftyLive, MacroTape (Intl formatting per item), PageStrip and AlertsBell every second, in every window. The desktop strip has its own second-aligned clock (TitleStrip.tsx:37-46). Idle BRF: 121.8 layouts/min and 343 style recalcs/min (Chromium CDP). The two clocks showed different seconds in 35 of 259 samples (13.5 %); D4 noted this as a known issue. Main-thread cost is small (0.84 % in total), so this is polish.
- failure: In the app the strip reads 11:45:52 while the header reads 11:45:51, about one sample in seven, in a 'Bloomberg-grade' window bar. Every window also does two layouts per second while idle.
- fix: Move the clock into a memo'd <HeaderClock/> leaf that reuses useSecondTick (second-aligned). In desktop mode drive both clocks from one shared tick, or hide one of them.

## C2-performance-08 [minor] API JSON is uncompressed on :8010 (the old :3000 gzipped it), a regression for the pending UI_API_HOST=0.0.0.0 iPad path
- verify: not verified
- file: services/ui-api/main.py:136
- area: Transfer size (pending LAN mode) · reproduced: True
- evidence: GET /api/stocks/list?limit=1500, which every window fetches at boot: :3000 sends Content-Encoding gzip, 110,043 B on the wire; :8010 sends content-length 934,658 with no encoding (curl with Accept-Encoding: gzip). ui-api has no compression middleware; the only middleware is the http_guard (main.py:134-136). On loopback the cost is negligible. pm_lan.py turns on LAN access for phone/iPad.
- failure: After pm_lan.py, an iPad on Wi-Fi downloads about 8.5× more bytes per window open and per poll than it did through :3000.
- fix: Add Starlette GZipMiddleware(minimum_size=1024, compresslevel=5) above install_http_guard. Starlette 0.52.1 already skips text/event-stream; check that it leaves the static UI's precompressed responses (Content-Encoding already set) alone. Alternatively enable it only when UI_API_HOST != 127.0.0.1.

## C2-performance-09 [minor] Each window duplicates every global poll, and each WS gets its own Redis connection and OS thread on ui-api
- verify: not verified
- file: services/ui-api/routers/monitor.py:209
- area: Multi-window scalability · reproduced: False
- evidence: Per window, the shell polls cost about 29 req/min before any page polls: nifty 12.6/min, nifty-live 4.2, data health/ready/provider 2.1 each, gift, quotes, indices, alerts feed and news scans about 1/min each. Restoring 8 windows fired 233 API requests in 8 s (ui-api coped: /api/prefs p99 115 ms, max 235 ms; all 8 interactive within 0.65 s). Server side, every ws_monitor call opens _redis.from_url + pubsub (:151) and starts a dedicated 'redis-reader' thread (:209) that schedules one coroutine per message per socket. Also, lib/wsManager.ts:243 doubles the reconnect delay up to 32 s with no reset when health recovers, so live ticks can resume up to 32 s after a watchdog restart (code reading; not measured).
- failure: With 8 windows plus a browser tab there are about 260 identical chrome polls per minute, 9 Redis connections and 9 blocked threads in ui-api, all for the same NIFTY, macro and status data. After a 2-minute outage, ICICI ticks come back up to 32 s after the banner says reconnected.
- fix: Server: run one Redis subscriber task per process and fan messages out to the connected sockets with asyncio. UI: elect one leader window with BroadcastChannel to poll the global chrome data and broadcast it, or let the shell push NIFTY and status it already polls. In wsManager, reset the backoff and reconnect immediately on online or health recovery, and add jitter.

## C2-performance-10 [minor] Confirmed on the served release: strip lights go grey about 16 % of the time and a fallback /health probe fires every cycle; the fix needs a rebuild and a check
- verify: not verified
- file: ui/components/desktop/status.ts:16
- area: Shell status cadence (already fixed in the working tree) · reproduced: True
- evidence: Served release 20261025-114737 with a simulated 30 s Rust heartbeat (the old lib.rs `since >= 30s`): dots grey in 42 of 259 samples (16.2 %), in runs at 25.1–30.2, 55.3–60.3, 85.0–90.5 and 115.2–120.7 s, with the tooltip 'status is stale (shell poller silent)'; fallback /health probes at 25.09, 55.09, 85.09 and 115.09 s. The working tree now has status.ts (STATUS_STALE_MS 35 s, pull after 10 s) and health.rs STATUS_HEARTBEAT 8 s (C1-desktop-native-03). Neither is in the served UI release or a built app yet.
- failure: If only one side ships (a new app with the old UI build, or the reverse), the flicker or extra pulls continue. With the old build live, every terminal window flickers its service lights.
- fix: Rebuild the UI (build_ui.sh) and the app together, then re-run this cadence check (scratchpad crit/C2-performance/c2_harness.py cadence --heartbeat 10) and expect 0 grey samples and 0 /health probes. Also update the health.rs:548 comment, which still says the UI's threshold is 20 s.

### strengths
- static_ui.py is production-quality. Measured live: index.html 0.9 ms (gzip 2,463 B, no-cache, strong ETag); 73 kB hashed chunk 1.0 ms (immutable, gzip); 304 revalidation 1.2 ms. Lookups and reads run on a dedicated 16-token limiter with a bounded LRU, so static serving never queues behind ui-api's sync DuckDB routes.
- ui-api's event loop stays responsive: /live p50 1–3 ms through the PM's 42-page audit, and max 106 ms while DEXP read a 352 MB parquet (the work runs in a worker thread).
- First-load JS measured live is 263,277 B gz (≤ 300 kB). No off-origin font requests (self-hosted fonts).
- P7/P8 are correct: one component type per mount, so no remount. Cycling all 42 pages twice in Chromium returned intervals to baseline (14 → 14 → 14), DOM nodes 1,875 → 1,882 → 1,882, JS listeners 460 → 464 → 464, heap after GC 8.86 → 12.74 → 13.03 MB. One WS stayed open throughout, and the SYS EventSource closed on unmount. The warm-up adds no measurable WebKit RSS (245 vs 251 MB with saveData).
- Integrated tab-switch UI-ready p95: 40.8 ms (Chromium) and 81 ms (WebKit), well inside the 400 ms budget on every page except EQS.
- A 20-minute idle Chromium run on BRF (desktop shell faked) showed main thread 0.84 % busy, heap 8.88 → 10.02 MB after GC, a flat DOM (1,873 nodes) and no long tasks. Live ticks on BRF cost only 1.3 % (0.2 Hz) to 3.3 % (1 Hz) of the main thread.
- Multi-window burst: 8 windows restored at once were all interactive within 0.65 s. /api/prefs, the boot gate's dependency, had p99 115 ms and max 235 ms, far below the 1.5 s gate ceiling.
- The Rust poller is cheap and correct: localhost GETs on a 5 s / 15 s / 60 s / 300 s cadence, and NSE upstream calls are TTL-cached in data-service, so more windows do not multiply NSE traffic.
### not checked
- The real SuryaDhana.app / WKWebView, which the rules say not to launch. All idle CPU/RSS numbers come from Playwright WebKit (UI process plus XPC helpers) and headless Chromium; Tauri's shell, hardware GPU compositing and phys_footprint may differ. Boot paint < 0.5 s: the self-test skipped it (screen locked) and I could not run it.
- How hidden or minimized windows behave over hours: windows.rs create_window sets no background_throttling policy, so WebKit's default inactive scheduling (throttle or suspend after ~5 min) applies. Its effect on polls, the WS and alert notifications in a hidden main window is unverified.
- Market-hours behaviour with real ICICI ticks through Redis. Ticks were simulated with a mocked monitor WS in my own page only (rates 0.2 and 1 Hz), never written to live Redis.
- The ui-api restart, sleep/wake and release-swap drills (PM-owned). I only observed one PM restart of ui-api at 11:47–11:49 (connection refused for about 20 s).
- The LAN/iPad path (pm_lan.py not applied) and any Wi-Fi measurements.
- CPU and memory of the Rust shell process and its poller over hours.
- RSS for 3–8 real app windows; I measured one-window stand-ins only.
- Working-tree changes made from 12:12 onwards by the fix rounds of other critics (http_guard, status.ts, holidays.ts, AppContext watchlist sync, MarketCommandHeader session label, lib.rs/health.rs) are not in the served release 20261025-114737. My browser numbers are from that release, and from 20261025-110718 for the first Chromium deep-link run. The C1 cadence fix was checked by reading the code only.

