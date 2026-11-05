# R-UI · SuryaDhana terminal, rated as a Bloomberg-terminal design lead would (4 Nov 2026, 22:10–23:10 IST)

Reviewer id **R-UI** · scope: UI/UX of all 43 pages of the live release served on http://127.0.0.1:8010 (UI release
`20261025-223942-0ae66db`, built 25 Oct — **before** the GOLD program, so `?tab=gold` is not in it). Read-only: the stack was
only visited with GETs through the project's own audit harness (`scripts/ui_audit.py`, prefs mode `readonly`) plus one
scripted probe of my own; nothing was restarted, written or posted by me (three pages post compute requests on their own:
OSTR `POST /api/options/strategy/analyze`, ALFA `POST /api/alpha/scan`, MCXG `POST /api/mcx/ticket`; none changes state).
Evidence lives in `/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-UI/`
(`audit/` = 43-page Chromium + WebKit run with screenshots and `audit_report.md`; `probe/` = my time-to-first-number, phone-width,
GO-bar and stock-window captures). PORT/BRKR screenshots show no URL bar and no login URL; the owner's broker balance appears
in `audit/*/broker.png` and is not quoted here.

## Executive summary (10 lines)

1. **Overall UI/UX: 7.1 / 10 as a market terminal, 4.5 / 10 as an options-and-commodity trader's terminal.** Kit, honesty and density are
   already Bloomberg-grade on the market-data pages (BRF, MKT, MEMB, MOV, OMON, DERV, PRE, WEI, DEAL); the gaps are workflow, not polish.
2. **Measured:** 42/43 pages render clean in Chromium (0 console errors, 0 failed requests); page-ready p50 **46 ms**, p95 **205 ms**,
   max 2,254 ms (CMDT, which blocks its header on the gold pre-open fetch). `?tab=gold` fails `not_ready` because the live release
   predates GOLD and the shell **silently lands on BRF** with no notice (audit/chromium/gold.png is the brief).
3. **The page strip is built for the 2025 research product, not the 2026 trader:** 21 slots, 7 of them legacy/research pages
   (Pipeline, LW Scan, Alpha, Glass-Box, ML, Explorer, Warehouse — three carry a RESEARCH · FAIL / NO EDGE banner) while OMON, OSTR,
   CHRT, ALRT, GOLD, MCXG, RSK live behind MORE ▾. Alt+0 goes to PORT, a dormant engine with a red LIQUIDATE & HALT button.
4. **No panel linking.** OMON cannot hand its symbol/expiry/strike to OSTR (OSTR starts on NIFTY from a `<select>`); CHRT ignores the
   stock you came from (always RELIANCE); the stock window has no chain or chart-studio tab. The trader's path
   stock → chain → strategy → ticket → positions is four re-entries of the same symbol and ends in a page that records nothing.
5. **The GO bar is the product's best asset** (type-to-GO, `TCS OMON`, `COMP A B`, mnemonics GP/TOP/MOST/BACK, history recall,
   Shift+Enter new window) and is 80 % of a Bloomberg command language; it needs arguments (expiry, strike, template, alert level)
   and a visible recall list.
6. **Alerts are price-only** (above / below / ±% move). An options trader needs IV-rank, PCR, basis, OI-change, event-in-N-days and
   gold fair-gap alerts, created from the chart or the chain, with repeat/snooze; the bot already has parity for price.
7. **Phone use is unsupported:** no breakpoint below 720 px except hiding tape items; pages overflow sideways at 390 px
   (`probe/mobile_*.png`, §4.2); the owner's real phone surface today is the Telegram bot.
8. **Kit drift is visible to the eye:** EQS, BTST, PIPE, ALFA, GBOX, MLEN, DEXP still use the pre-terminal Tailwind look
   (different inputs, 51-px rows, three ambers; 597 hex literals and tabular-nums in only 70 places per the 14 Oct design audit).
9. **Staleness is told in prose, not chips:** RSK "broker book as of 2026-10-14 (stale)", WRAP "breadth is from 2026-10-30",
   CMDT at 22:18 says "wait 15–30 minutes for the rupee's 09:00 open"; `SourceChip` exists in the kit but only gold code uses it.
10. **Fifteen changes** (§5) would move the trader score from 4.5 to ~8: strip re-cut, a linked active-symbol context, a Launchpad
    workspace, chain-first OMON with Greeks and strike→leg, OSTR journal + what-ifs, typed alerts, column-configurable WATCH, chart
    linking/tools, GO v2 arguments, chrome budget, staleness chips, a phone mode, kit unification, a "who drives NIFTY" function,
    and honest empty/degraded states.

---

## 1. Method

| Step | What | Where |
|---|---|---|
| Read | CLAUDE.md, IMPROVEMENT_LOG (newest first), PRODUCT_STRATEGY, desktop FINAL_REPORT, gold PLAN §0.1 + FINDINGS, the 14 Oct design audit, the desktop critics' round-1 trader-UX section | `docs/`, `reports/` |
| Source | `ui/app/page.tsx` (COMMAND_PAGES, tabList, hotkeys), `CommandBar.tsx`, `lib/goAliases.ts`, `lib/shortcuts.ts`, `lib/pageKeys.ts`, `components/terminal/index.tsx` (the kit: 40 exports), `deskLayout.ts`, `pageModels.ts`, the F&O pages (`OptionChain`, `StrategyBuilder`, `DerivativesDesk`, `TradeTicket`, `McxGoldDesk`, `AlertsCenter`, `WatchMonitor`, `ChartStudio`, `StockDetailModal`), `globals.css` media queries, `gold/GoldPage.tsx` | `ui/` |
| Live | `scripts/ui_audit.py --tabs all --browser both --prefs-mode readonly` at 1680×1050 (43 pages × 2 engines, screenshots, console, failed requests, Navigation Timing, structural fingerprint) | `scratchpad/R-UI/audit/` |
| Probe | my own Playwright script (`probe_ttfn.py`): time to the first numeric token inside `.sd-page` per page, body size, phone width 390×844 for 10 pages, GO bar empty / `TCS` / `TCS OMON`, the stock window's first price, the `?` help card, the MORE menu, 1280 and 1100 px widths on DESK / OMON / MKT | `scratchpad/R-UI/probe/` |

Criteria (as briefed): keyboard-first workflow and linking; information density vs legibility; kit consistency; latency as felt
(measured); empty/degraded states; phone use; beginner discoverability vs pro speed; the trader's path stock → chain → strategy →
ticket → positions. Scores are 0–10 where 10 is "a Bloomberg function head would ship it as is".

## 2. Shell and cross-page systems

### 2.1 What is already Bloomberg-class (keep)
- **Honesty of every number:** provenance on every panel ("NSE EOD 2026-11-04", "NSE F&O bhavcopy 2026-11-04 · expiry 2026-11-09
  (5d) · lot 65"), research verdict banners (RESEARCH · FAIL / NO EDGE / PROMISING / REFERENCE) on the pages whose ideas failed, "health
  gauge, not a signal", "describes the past, not a forecast" captions. Rarer than any feature; it is the brand.
- **Command line:** `/` or ⌘K; typing a ticker letter anywhere opens GO seeded (type-to-GO); `TCS` ↵ opens the stock window; `TCS OMON`,
  `TCS DEAL`, `TCS FA/ERN/HP/SEAG/TV/YF/W`, `COMP TCS INFY`, `OMON RELIANCE`, mnemonics `GP TOP MOST BACK NIFTY BANKNIFTY XAU GC`;
  Shift+Enter opens a new window; ↑ recalls history (20 entries). Exact page codes outrank tickers (GP never opens GPIL). This is the
  Bloomberg `<GO>` idiom done right.
- **Keyboard:** Alt/⌘ 1–9, 0 for the first ten strip tabs; table cursor ↑↓ / j k + Enter opens the stock; Esc closes in order (help → GO →
  stock window); `?` help card; Shift+N news; ⌘[ ⌘] back/forward with history entries tagged so Back never leaves the terminal.
- **Chrome:** one header (NIFTY, change, close date, DATA/DB/ICICI lights, session state, clock, bell, UPDATE DATA), one tape
  (GIFT, NIFTY, BANK, VIX, USD/INR, Brent, Gold, S&P), one strip, one 22-px status line (READY, DATA date, universe, NEWS dock, / GO,
  key hints, NSE · PAPER). Identical on all 43 pages (audit fingerprints).
- **Resilience UX:** per-page error boundaries, LINK DOWN banner with "panels show the last data received", GO-bar self-retry,
  2-dp Indian-grouped prices, PAPER ONLY enforced and shown.

### 2.2 Where the shell falls short (evidence)
| # | Finding | Evidence |
|---|---|---|
| S1 | **Strip composition.** `tabList` (page.tsx:610) = Brief · Watch · Desk · Markets · Deriv · Events · Overview · Stocks · Backtest · Portfolio · Broker · Pipeline · LW Scan · Alpha · Commodity · Glass-Box · ML · Explorer · Warehouse · Research · System. OMON, OSTR, CHRT, ALRT, MOV, PRE, ECO, MEMB, GOLD, MCXG, RSK are all in MORE ▾. Alt+7 = OVRV (an admin page), Alt+9 = BTST (legacy form), Alt+0 = PORT (dormant). | page.tsx:610–631; every audit screenshot's strip |
| S2 | **No active-symbol context.** Handoffs are three ad-hoc localStorage keys (`COMP_KEY`, `OMON_KEY`, `DEAL_KEY`, lib/pageKeys.ts) written only by the GO bar; `ChartStudio` is mounted as `<ChartStudio />` with no symbol (page.tsx:677) so GP always shows RELIANCE; `StrategyBuilder` keeps `useState('NIFTY')` (StrategyBuilder.tsx:164) and reads nothing; the stock window's tabs are Profile/Data/Chart/HP/SEAG, no OMON/CHRT. Bloomberg's panel groups, thinkorswim's colour-linked windows and TWS Mosaic all have this as the base layer. | lib/pageKeys.ts; page.tsx:675–699; StockDetailModal.tsx:66–73 |
| S3 | **Chrome budget.** At 1050 px tall the first data row of BRF is at y≈295: settings banner (24 px — real for the owner too: `start-local.sh status` says prefs "not imported") + header 44 + tape 28 + strip 34 + page header 44 + NEW-SINCE row 36 + NEEDS-YOU row 34 + 22-px footer. OMON's chain (the object an options trader came for) starts at y≈970, below the fold. | audit/chromium/brief.png, options.png |
| S4 | **Phone:** `globals.css` has only `t-hide-xl/lg/md` (1760/1480/1240) and tape hiding at 1280/1024/720; no layout change under 720 px; `DataTable` columns have fixed min widths. See §4.2. | globals.css:79, 201–203, 423–424 |
| S5 | **Kit drift.** Two visual generations coexist: the terminal kit (`Panel/Stat/DataTable/Chip`, JetBrains Mono 11–13 px) on 30 pages, and the earlier Tailwind cards (rounded inputs, `#f59e0b` amber, 51-px rows, sentence-case labels) on EQS, BTST, PIPE, ALFA, GBOX, MLEN, DEXP. `tabular-nums` in 70 places only; ragged decimals on EQS (`₹189.41`, `₹1,125.30`, `₹33,100.00`). | audit/chromium/stocks.png, backtest.png, pipeline.png; design_audit.md (597 hex literals, 72/100 token discipline) |
| S6 | **Staleness in prose.** RSK header: "broker book as of 2026-10-14 15:13 (stale)"; WRAP: "End-of-day breadth is from 2026-10-30" under a 04 Nov title; CMDT at 22:18: "Wait 15–30 minutes for the rupee's 09:00 open"; WTCH footnote "Yahoo ~1 minute delayed" while the header light says ICICI connected. `SourceChip` (kit line 690) is used only by gold code. | audit/chromium/risk.png, wrap.png, commodity.png, watch.png |
| S7 | **Unknown tab falls back silently.** `tabFromSearch` returns `brief` for any id it does not know (pages.ts:58–66); the live release has no `gold` module, so GO `GOLD` / `XAU` / `GC` and `?tab=gold` land on BRF with the strip showing BRIEF and no toast. | ui/components/desktop/pages.ts; audit/chromium/gold.png |
| S8 | **Same number, two pages, two values.** Gold "fair value (model)" is ₹1,44,217 on CMDT and ₹1,44,256 on MCXG at the same minute. The gold PLAN's rule ("the same number appears once per page", "one page") is right; the deployed release breaks it across pages. | commodity.png vs mcxgold.png |
| S9 | **Duplicated panel titles.** MOV renders two panels both titled "INTRADAY" (NIFTY and BANK pickers side by side); the fingerprint lists `Intraday; Intraday`. | audit/chromium/movers.png; audit.json |
| S10 | **Discoverability vs speed.** Beginners get `?`, the GO placeholder, "MORNING PAGES" chips on BRF and the "32 things to try" doc; pros get hotkeys. Missing in between: a visible recent-commands row under GO (history exists but only via ↑), argument hints while typing (`TCS OMON ▸ expiry?`), and a per-page "functions here" line like Bloomberg's red-key menu. | CommandBar.tsx:60–75, items memo |

## 3. Page by page (43)

Score · evidence · what the best product does. "ready" = harness page-ready ms (Chromium, 1680×1050); first-number timings are in §4.2.

### Trader core
| Page | Score | Evidence (screenshot = audit/chromium/*.png) | What the best would do |
|---|---|---|---|
| **BRF** Brief | **8.5** | brief.png: regime 0/4, book, intraday NIFTY, this week, scanner track record (honest: "no edge yet"), headlines, NEEDS-YOU 3; 41 API calls, ready 205 ms, network idle only at 19.5 s (polls). | Bloomberg `TOP`/`BRIEF` is matched. Cut the NEW-SINCE chip soup into the bell; make NEEDS-YOU one amber header chip; drop the gold line while GOLD is not deployed. |
| **WTCH** Watch monitor | **5.0** | watch.png: empty-state copy is good; 12 fixed columns (`WatchMonitor.tsx:174–216`); quotes every 60 s from Yahoo; no groups; alert bell per row. | Bloomberg `WATC`/`MOST`, TradingView watchlists, TWS Quote Monitor: user-picked columns saved in prefs, sections (Holdings / Desk / F&O underlyings), live source chip per panel, IV-rank / PCR / next-expiry columns for F&O names, flash on tick (the LiveMonitorBar already flashes). |
| **CHRT** Chart studio | **6.0** | charts.png: candles, EMA 20/50/200, BB, RSI, VOL, D/W/M + 1m/5m/15m in session; symbol box only; no symbol handoff (page.tsx:677). | Bloomberg `GP`/`GIP`, TradingView: open on the active symbol, drawings persisted per symbol, results/ex-date markers, OI-wall and max-pain lines for F&O names, compare overlay, 2×2 multi-chart, intraday from the tick store with VWAP. |
| **OMON** Option monitor | **8.0** | options.png: expiry chips, spot/forward, ATM IV 13.9 %, expected range, PCR, max pain, OI walls, **1-year ATM IV + PCR history with IV rank 73** (the owner's "IV day to day" ask is already here, from the F&O bhavcopy), smile, OI by strike, LIVE/EOD toggle; the chain starts at y≈970; chain columns = OI, OI chg, volume, IV, price (no Greeks); no link to OSTR. | Bloomberg `OMON`/`OVDV`, Sensibull, Opstra: chain above the fold with Greeks (Δ Γ Θ ν), OI-change bars inline, straddle/strangle price row, IV-percentile chip, click strike → leg in OSTR, j/k over strikes, expiry ladder of ATM IV, IV vs realised (HV 10/20/30) cone. |
| **OSTR** Options strategies | **6.5** | ostrategy.png: 8 templates, 4 legs, exact breakevens, Black-76 Greeks, margin/cost estimates labelled ESTIMATE, payoff at expiry + today; symbol via `<select>`; nothing saved; no scenario controls; `POST …/analyze` on load. | thinkorswim Analyze, TWS Strategy Builder, Sensibull: symbol/expiry/strikes arrive from OMON; what-if sliders (date, IV ±, spot ±) and a P&L grid by date × price; probability-of-profit labelled `heuristic` (lognormal); save/name strategies; a **paper strategy book** marked daily from the EOD chain so "positions" exists for options. |
| **DERV** Derivatives desk | **8.0** | derivatives.png: term structure, annualised basis history 2021→, rollover vs prior cycles, PCR & max pain, VIX; any F&O stock. | Bloomberg `FUTS`/`CTM`: add a stock-wise basis screen (the excess-carry signal already exists in alpha_lab) and link rows to OMON. |
| **MOV** Live movers | **8.0** | movers.png: breadth tiles, two intraday charts, **"who moved the index"** (points per stock, NIFTY/BANK/IT/NEXT 50), internals, sector board, map; 13 panels / 24 canvases; two panels titled INTRADAY. | Bloomberg `MOV`/`IMAP`: rename the two intraday panels; make "who moved" a rolling 1/5/20-session leaderboard (§5 #14). |
| **MEMB** Index members | **8.5** | memb.png: weight, points today, YTD points, vs 52w high, P/E vs own history, profit/revenue y/y, "weights rebuilt from filings explain +154.4 of +149.8". | Bloomberg `MEMB`/`CACS`: already there; add a contribution sparkline per row and a "top-5 share of points" tile. |
| **PRE** Pre-open auction | **8.0** | preopen.png: IEP, gaps, matched value, buyers/sellers left over, full book with imbalance; filters. | NSE pre-open is unique to India; keep. Add "yesterday's pre-open gap → open" hit-rate as a `context` chip. |
| **EVTS** Corporate calendar | **8.0** | events.png: reacting today (size vs normal), season scorecard, results scoreboard, next five weeks. | Bloomberg `EVTS`/`ERN`: add the options-implied move next to "typical" for F&O names (OMON's expected-range math exists). |
| **ALRT** Alerts | **5.5** | alerts.png: above/below/±move, fired, inbox with kind filters; checked every minute by the scheduler. | Bloomberg `ALRT`, TradingView alerts, Sensibull/Quantsapp: condition types (IV rank, PCR, basis, OI Δ, event in N days, gold fair gap, breadth), create from chart/chain, repeat vs one-shot, snooze, per-alert channel (Mac / Telegram), alert lines on charts. |
| **DESK** Decision Desk | **8.0** | desk.png: paper book, crash-filter banner, watchlist with ASM chips, BAD RESULTS flags, Book vs NIFTY, Rules; "Unknown" industry on 3 names; hidden-column cue exists (`deskLayout.ts`). | Keep. Fix the "Unknown" industry; show the hidden-column cue as a chip in the panel header. |
| **MKT** Market monitor | **8.5** | markets.png: regime, breadth tiles, valuation history with percentiles, 14 panels; network idle 5.3 s. | Bloomberg `WEI`+`MMAP`: the flagship; load the below-fold panels lazily. |
| **WEI** World markets | **8.0** | world.png: 7 regions, sparklines, range bars, age chips, policy dates. | Bloomberg `WEI`: matched. |
| **ECO** Economic calendar | **7.5** | eco.png: why-it-matters column, IST times, holiday rows. | Bloomberg `ECO`: add consensus/previous/actual when a free source exists; today it is a schedule, labelled so. |
| **CF** Company filings | **7.5** | filings.png: 893 filings, category chips, "YOUR STOCKS 0". | Bloomberg `CN`/`CF`: j/k + Enter is missing on this list (it is not a DataTable). |
| **DEAL** Block & bulk deals | **8.0** | deals.png: research banner (H3 verdict), netted clients, biggest flows, deals table. | Keep. |
| **MRGN** Margin monitor | **7.5** | margin.png: MTF book 1 year, build-ups, crowded, largest funded. | Keep; link rows to OMON for F&O names. |
| **FUND** Fundamentals screener | **8.0** | screen.png: presets, industry medians, 1,807 rows, COMPARE handoff. | Bloomberg `EQS`: saved screens (prefs) and a column picker. |
| **HDS** Ownership shifts | **7.5** | holders.png: MF/FPI/promoter/retail pp changes, shareholder surge. | Keep. |
| **INSD** Insider monitor | **7.5** | insiders.png: H4 PROMISING banner, 86 stocks, since-filing return. | Keep. |
| **IPO** IPO monitor | **7.5** | ipo.png: live subscription, QIB-bucket table "context, not a rule", listings. | Keep. |
| **WRAP** Daily wrap | **7.0** | wrap.png: archive + document; header "written 21:00", body "Written 21:30", breadth "from 2026-10-30". | One timestamp, and a STALE chip on sections whose as-of differs from the title date. |
| **COMP** Compare | **7.0** | compare.png: rebased chart, risk table, fundamentals; single-stock empty correlation. | Bloomberg `COMP`/`GRR`: rolling beta/correlation windows and a ratio (pairs) chart. |
| **SEAG** Seasonality | **8.0** | seag.png: 15-year grid, up-month share, honest caption. | Keep. |

### Commodity / gold
| Page | Score | Evidence | What the best would do |
|---|---|---|---|
| **CMDT** Commodities | **6.0** | commodity.png: in the live release the Gold Pre-Open Desk still lives here (the 26 Oct consolidation is not deployed); copy "wait for the 09:00 open" shown at 22:18; fair value differs from MCXG's by ₹39. | After GOLD deploys, CMDT = global futures + EIA + FRED context only (PLAN §b); until then, a "pre-open desk is meaningful 08:30–09:15 only" chip. |
| **MCXG** MCX gold desk | **7.5** | mcxgold.png: session clock + holidays, Breeze LTP with honest "— / —" high/low, COMEX × rupee overlay, contract specs (GOLD/GOLDM/GOLDTEN/GUINEA/PETAL) with margins, paper ticket. | TWS/thinkorswim futures ticket: write the ticket into a paper futures book with daily MTM; depth-of-book when Breeze supplies it; the fair-value line on the chart. |
| **GOLD** Gold terminal | **7.0 (source only)** | Not in the live release (`?tab=gold` → BRF). Source: `gold/GoldPage.tsx` with 9 sub-views on the kit `Tabs` (HEALTH / DAILY / WEEKLY / MONTHLY / POSITIONING / PHYSICAL / MACRO / CONTRACTS / LEARN), HeaderStrip naming the four instruments, GO aliases XAU/GC/COT/GPHY/GMAC/LRN; 4,463 lines across 25 files; labelling rules enforced by tests. | Bloomberg `GLD`/`CMDS` + `COT`: the right shape. Once deployed: ⌥←/→ cycling across the 9 sub-views, deep links (`?tab=gold&sub=…` exists in `lib/gold/prefs`), and the HEALTH verdict as the source of BRF's gold line. |

### Portfolio / risk / broker
| Page | Score | Evidence | What the best would do |
|---|---|---|---|
| **PORT** Portfolio (legacy engine) | **3.5** | positions.png: "PORTFOLIO · LEGACY ENGINE · PAPER ONLY", RESEARCH · FAIL banner, Execution Control Panel with a struck-through LIVE and a red LIQUIDATE & HALT button, empty positions; it owns Alt+0. | Bloomberg `PRTU`/`PORT`: one Positions page = Desk paper book + broker holdings + (new) paper options/futures books, with P&L attribution; the legacy engine goes under RESEARCH. |
| **BRKR** Broker | **6.0** | broker.png: funds/holdings read-only, rules panel; refresh every 15 s. | Keep as the account page; the TOTP auto-login panel (source) belongs here. Show F&O margin available (Breeze funds has it). |
| **RSK** Risk dashboard | **6.0** | risk.png: VaR "NO RETURN SAMPLE", broker book stale 3 weeks, drawdown ladder vs the −20 % HARD stop (good), what-if basket. | Bloomberg `PORT` risk, TWS Risk Navigator: option Greeks exposure (needs the paper strategy book), beta-weighted delta vs NIFTY, event risk for the book's names. |

### Research / data / system (right to exist, wrong to sit on the strip)
| Page | Score | Evidence | Note |
|---|---|---|---|
| **EQS** Stocks | **6.0** | stocks.png: 1,500 rows rendered (body text 175 k chars), Minervini T1–T8, old kit, 51-px rows, mixed decimals. | Virtualise rows; adopt `DataTable`; Bloomberg `EQS` would page this. |
| **BTST** Backtest lab | **4.0** | backtest.png: old-kit form, "Institutional simulation cockpit" placeholder, friction default 15 bps (the project floor, not ICICI's 93 bps) next to a banner saying costs decide. | Default to `COST_PROFILE` costs; show the last run instead of a placeholder. |
| **OVRV** Overview | **5.0** | overview.png: data freshness, roadmap, system status. | An admin page; fold into SYS/WHSE. |
| **PIPE** Pipeline | **3.5** | pipeline.png: ML pipeline tabs in a third visual style. | RESEARCH menu. |
| **LWSC** LW scanner | **4.0** | scanner.png: RESEARCH · FAIL banner, composite scores 0–1 (a composite the gold rules would forbid). | RESEARCH menu; relabel "composite" as `heuristic`. |
| **ALFA** Alpha discovery | **4.0** | discovery.png: NO EDGE banner, knobs, `POST /api/alpha/scan` on every open. | RESEARCH menu; scan on demand only. |
| **GBOX** Glass-Box | **4.5** | glassbox.png: empty until Render. | Render the last basket on open. |
| **MLEN** ML engine | **3.5** | mlengine.png: FAIL banner, empty convergence chart. | RESEARCH menu. |
| **DEXP** Data explorer | **4.0** | fingerprint: 26 k chars raw grid. | RESEARCH menu. |
| **WHSE** Warehouse health | **6.0** | fingerprint: one panel "NSE research datasets". | Fine as an ops page. |
| **RSCH** Research library | **7.0** | research.png: 103 studies with verdict chips, search, full document inline (50 k px). | Collapse sections; "open on the page it affects" links. |
| **SYS** System | **7.0** | system.png: services, jobs with last latency, ICICI TOTP login ERROR visible, autopilot OFF. | Fine; ready 606 ms (slowest non-gold page). |

## 4. Measured latency, phone width, flows

### 4.1 Page-ready (harness) — Chromium 1680×1050, 42 pages with a header
ready p50 **46 ms**, p95 **205 ms**, max **2,254 ms** (CMDT); FCP p50 ≈ 48 ms. Network idle: BRF 19.5 s (41 endpoints, polling),
MKT 5.3 s, CMDT 3.7 s, WEI 2.7 s, WTCH 2.3 s, DESK 2.2 s, ALFA 2.1 s; everything else < 1.5 s. WebKit (26.4): 42/43 PASS, ready p50 74 ms / p95 657 ms / max 950 ms (`evidence/ui_audit_report.md`).

### 4.2 Time to first useful number (my probe), phone width, flows
Method: Chromium 1680×1050, chunks warm (a first pass loaded every module), each page visited once; "first #" = ms from navigation
to the first numeric token inside the page body (dates count, so it is a floor, not "first useful number"); phone = 390×844,
`scrollWidth` > 390 means the page overflows sideways. Raw: `evidence/probe.json`; script: `evidence/probe_ttfn.py`.

**Time to first number (ms):** BRF 47 · WTCH 43 · CHRT 45 · COMP 49 · **FUND 894** (1,807 rows rendered at once, 3,936 lines of text) ·
ALRT 103 · ECO 107 · SEAG 35 · MEMB 43 · OMON 119 · OSTR 107 · DERV 123 · INSD 46 · DEAL 45 · PRE 50 · **IPO 894** · MOV 54 · WRAP 30 ·
CF 168 · MRGN 42 · HDS 155 · WEI 34 · DESK 29 · **MKT 496** · EVTS 193 · OVRV 55 · EQS 48 (10,612 lines of text in the DOM) · BTST 59 ·
PORT 88 · BRKR 33 · PIPE n/a (kept-alive mount) · LWSC 39 · ALFA 104 · **CMDT 1,676** · MCXG 172 · GOLD → BRF 57 · GBOX 48 · MLEN 50 ·
DEXP 142 · WHSE 222 · **RSCH 432** (document 36,863 px tall) · RSK 34 · **SYS 599**. Felt latency is therefore excellent everywhere
except CMDT (blocks on the gold pre-open fetch), FUND/IPO/MKT/RSCH/SYS (large synchronous renders), and the pages that keep polling.

**Flows (evidence/flow_*.png):** `/` opens GO instantly; typing `TCS` lists TCS · DES · FA · ERN · HP · SEAG · OMON · DEAL · TV · W with a
key legend and "1,500 symbols"; Enter → the stock window shows the first price **805 ms** later (DELAYED · YAHOO chip, 3M candles +
SMA 20/50/150/200, PIN / WATCHLIST / ALERT / TRADINGVIEW / YAHOO / NEW WINDOW, tabs Profile · Data · Chart · HP · SEAG — no OMON, no
CHRT); `?` shows a two-column help card (function codes + keys + "reading the screens"); MORE ▾ lists 22 pages in a scrolling menu
(CHRT, WEI, ECO, MEMB, SEAG, PRE, MOV, CF, OMON, OSTR, DEAL, MRGN, FUND, ALRT, HDS, INSD, IPO, WRAP, COMP … GOLD, MCXG, RSK) — the
options pages are items 9–10 of a 22-item menu.

**Phone 390 px (evidence/mobile_*.png):** scrollWidth BRF 465 · WTCH 390 · MKT 685 · OMON 508 · OSTR 434 · GOLD(→BRF) 465 · DESK 642 ·
ALRT 390 · CHRT 390 · **DERV 1,027** (2.6 screens wide). The header clips NIFTY to "NI"; the tape shows one item; the strip shows
BRIEF · WATCH · DESK · MAR… + MORE; OMON's six stat tiles truncate their values to "2…", "1…" (mobile_options.png) and the chain is
unreachable without sideways scrolling; BRF's three banners (settings, NEW SINCE, NEEDS YOU) take the first 1,100 px. Verdict: the
terminal is unusable on a phone today; the Telegram bot is the de-facto phone surface.

**Laptop 1100 px (evidence/narrow_1100_options.png):** the strip still fits 14 tabs + the active MORE page; OMON's tiles reflow to one row;
the IV history panel is readable. DESK at 1100 px stacks the watchlist above the side panels (deskLayout.ts) with the hidden-column cue.


## 5. The 15 highest-leverage UI changes (ranked by value ÷ cost)

| # | Change | Why (evidence) | Named precedent | Cost |
|---|---|---|---|---|
| 1 | **Re-cut the strip for the trader's day.** Strip = BRF · WTCH · CHRT · OMON · OSTR · DERV · MOV · EVTS · ALRT · POS (new, §6) · GOLD · MCXG · RSK · MKT; a RESEARCH ▾ menu holds BTST, PIPE, LWSC, ALFA, GBOX, MLEN, DEXP, WHSE, OVRV, RSCH; Alt/⌘ 1–0 follow. Make the strip user-orderable (saved in prefs). | S1; 7 of 21 slots are research/legacy, 3 with FAIL/NO-EDGE banners; OMON/OSTR hidden | Bloomberg's user-defined toolbar, TWS Mosaic tab bar | S |
| 2 | **Active-symbol context (panel linking).** One `useActiveSymbol()` (prefs-synced, per window) that the stock window, OMON, OSTR, CHRT, COMP, DEAL, DERV read and write; GO `GP` opens CHRT on the active symbol; the stock window gains OMON and CHRT tabs; OMON → "OPEN IN OSTR" carries symbol + expiry + chosen strikes. | S2; OSTR `useState('NIFTY')`; CHRT mounted without a symbol; three one-off localStorage keys | Bloomberg panel groups (A/B/C), thinkorswim colour linking, TWS window groups | M |
| 3 | **Launchpad workspace.** Saved layouts of 2–4 panels in one window (chain + chart + strategy + positions), resizable grid, each panel a page component with its own header; layouts in prefs; the app's ⌘N windows become the second tier. | Every page is a full-width single column; the owner trades options and gold in one session | Bloomberg `LPAD`, TWS Mosaic, TradingView multi-chart layouts | L |
| 4 | **Chain-first OMON.** Chain above the fold (history collapses to a sparkline strip), Greeks columns (Δ Γ Θ ν from the existing Black-76 engine), inline OI-change bars, straddle row, IV percentile + rank chips, expiry ladder of ATM IV, click/Enter on a strike → leg in OSTR, keyboard over strikes. Data: the stored F&O bhavcopy history (`nse_fo_daily` 2019→) and the live NSE chain in session; Breeze option quotes for intraday IV snapshots once stored point-in-time. | options.png chain at y≈970; no Greeks; IV history already there | Bloomberg `OMON`/`OVDV`/`HIVG`, Sensibull chain, Opstra IV chart | M |
| 5 | **OSTR v2: journal + what-ifs.** Save/name strategies; paper strategy book with daily EOD MTM (becomes the options "positions"); date/IV/spot sliders with a P&L grid; POP labelled `heuristic`; compare two strategies. | OSTR records nothing; the ticket→positions path ends in nothing | thinkorswim Analyze (Risk Profile, Probability), TWS Strategy Builder, Sensibull Positions | M |
| 6 | **Typed alerts, created where you look.** Conditions: price (exists), IV rank ≥/≤, PCR, basis %, OI Δ, event in N days, gold fair gap, breadth; right-click a chart level or a chain strike to create; repeat/one-shot, snooze, channel; alert lines on charts; inbox grouped by symbol. | ALRT price-only; bot parity for price only | Bloomberg `ALRT`, TradingView alerts, Quantsapp/Unusual Whales option alerts | M |
| 7 | **Watch columns + sections + live source.** Column picker in prefs, sections (Holdings / Desk / F&O underlyings / Gold), per-panel `SourceChip` (Breeze when connected), compact density toggle, F&O columns (IV rank, PCR, next expiry, basis). | WTCH fixed 12 columns; Yahoo footnote with ICICI connected | Bloomberg `WATC`, TWS Quote Monitor, TradingView watchlist columns | S–M |
| 8 | **Chart linking + tools.** Open on the active symbol; drawings persisted per symbol (prefs); results/ex-date markers; OI walls / max-pain lines for F&O names; compare overlay; VWAP from the tick store in session; 2×2 layout (ties to #3). | charts.png; no handoff; no markers | Bloomberg `GP` with `EVTS` overlays, TradingView | M |
| 9 | **GO v2: arguments and recall.** Grammar `TICKER FUNC [ARGS]`: `TCS OMON 27NOV`, `NIFTY OSTR IC`, `ALRT TCS >3200`, `TCS VS INFY`, `GOLD COT`; argument hints as you type; a visible "recent" row (history exists but is ↑-only); a per-page footer listing that page's codes. | CommandBar items memo; S10 | Bloomberg `<GO>` autocomplete + "recent functions" | S–M |
| 10 | **Chrome budget.** Settings banner → one-time toast; NEW-SINCE chips → the bell; NEEDS-YOU → one header chip; tape collapsible (⌘⇧T) and hidden under 1280 px; strip auto-hides on scroll in the app. Target: first data row ≤ 180 px from the top. | S3 (first data at y≈295 on BRF; chain below the fold on OMON) | Bloomberg's two-line header | S |
| 11 | **Staleness chips everywhere.** `SourceChip` on every panel header: LIVE / DELAYED (age) / STALE (as-of ≠ latest session) / OFFLINE; colour the as-of when stale; never a stale number in body prose only. | S6 | Bloomberg's yellow "delayed" and the data-age field on every function | S |
| 12 | **Phone mode.** A compact layout (≤ 720 px) for BRF, WTCH, ALRT, MOV, OMON summary, MCXG/GOLD health: single column, 44-px targets, bottom tab bar, tables as cards or horizontally scrollable with a column cue (the DESK `hiddenColumnsCue` pattern); other pages show "open on the desk". Pair with the Telegram bot as the push surface. | S4; §4.2 captures | Bloomberg Anywhere mobile (watchlists, alerts, news first), Sensibull mobile | M |
| 13 | **Kit unification + DESIGN.md.** Migrate EQS/BTST/PIPE/ALFA/GBOX/MLEN/DEXP to `Panel/DataTable/Input/Btn`; `font-variant-numeric: tabular-nums` on every numeric cell via the kit; one amber; spacing scale; virtualised DataTable for > 300 rows. | S5; design_audit.md | Bloomberg's single type system | M |
| 14 | **"Who drives NIFTY" as a function (CONTRIB).** MEMB + MOV already compute points per member; add a rolling 1/5/20/60-session contribution leaderboard, leadership concentration (top-5 share of points), sector split, a "leader changed" chip when the 20-session top name changes; label `arithmetic`; link to the stock and to OMON. Free data: NSE index constituents + closes already in `market_index_daily` / `nse_bhavcopy`. | Owner's brief; memb.png / movers.png | Bloomberg `MEMB`/`CACS`/`IMAP` contribution views, Koyfin contribution charts | S–M |
| 15 | **Honest empty / degraded / unknown states.** Unknown `?tab=` → toast "GOLD is not in this release (built 25 Oct)"; BTST/GBOX/MLEN show the last result instead of a placeholder; RSK says "needs holdings" once (not in six boxes); CMDT's pre-open copy only in its window; MOV panel titles unique. | S7, S8, S9; risk.png; backtest.png | Bloomberg never shows a blank function | S |

Design rules carried over from the gold PLAN §0.1 / §f and applied to all of the above: badges `signal` / `context` / `arithmetic` /
`heuristic` on every derived number; no composite "scores" that pretend to forecast (LWSC's 0–1 composite and the regime "0/4"
gauge should carry `heuristic`); context metrics never coloured bullish/bearish; every number once per page; value · source · as-of ·
lag chip on every panel.

## 6. The trader's path today vs target

| Step | Today | Target (after #2, #4, #5) |
|---|---|---|
| Stock | `TCS` ↵ → stock window (first price timing in §4.2) | same |
| → chain | type `TCS OMON` again (GO), new page | stock-window tab OMON, or `⌥O`; chain opens on the active symbol |
| → strategy | OSTR opens on NIFTY; re-pick symbol, expiry, strikes by hand | OMON strike → leg; OSTR inherits symbol/expiry/forward/IV |
| → ticket | OSTR shows margin/cost estimates; no ticket; no record | "Book paper" writes the strategy to the paper book with MTM |
| → positions | PORT = legacy engine; BRKR = demat only; no options book | POS page: Desk book + demat + paper options/futures; Greeks and VaR in RSK |

## 7. What is already right for an options/commodity trader (do not lose it)
- OMON's 1-year ATM IV + PCR history with IV rank, smile, OI walls, expected range, F&O-ban strip, expiry chips.
- DERV's basis history and rollover vs prior cycles.
- OSTR's exact breakevens, Black-76 Greeks, honest ESTIMATE labels, "PRICES ONLY · NO ORDERS".
- MCXG's session clock with MCX holidays and US-linked close, contract family with margins, paper ticket with max-lots-at-1 %-risk.
- The research banners that keep the trader out of the ideas that failed after costs.

## 8. Open questions for the owner
1. Should the phone be a first-class surface (phone mode, #12), or does the Telegram bot stay the phone surface with the terminal desk-only?
2. Is a paper options/futures book (strategy journal with daily MTM, #5) wanted now, given PAPER ONLY, so that RSK can show Greeks exposure?
3. Confirm the strip re-cut (#1) and which ten pages get Alt/⌘ 1–0.
4. When the GOLD release ships, should CMDT keep any gold line, or only the `GOLD ›` chip (PLAN §b)?
5. Launchpad (#3) vs multi-window (⌘N exists): which do you reach for first on the Mac mini's screen?

## 9. Appendix: files and endpoints this review rests on
- Pages: `ui/app/page.tsx` (TAB_IDS 43, COMMAND_PAGES, tabList 21), `ui/components/desktop/pages.ts`, `ui/components/shell/tabModules.ts`.
- Command language: `ui/components/CommandBar.tsx`, `ui/lib/goAliases.ts`, `ui/lib/shortcuts.ts`, `ui/lib/pageKeys.ts`.
- Kit: `ui/components/terminal/index.tsx` (Panel, Stat, DataTable with j/k/Enter, Chip, SourceChip, Skeleton, Empty, ErrorBox…), `ui/app/globals.css`.
- F&O: `ui/components/OptionChain.tsx` (History panel lines 148–190, chain at 317+), `StrategyBuilder.tsx`, `DerivativesDesk.tsx`, `TradeTicket.tsx`, `AlertsCenter.tsx`, `WatchMonitor.tsx`, `ChartStudio.tsx`, `StockDetailModal.tsx`.
- Gold: `ui/components/gold/GoldPage.tsx` (+24 files), `reports/gold_program/PLAN.md` §0.1, §b, §f.
- Live: `GET http://127.0.0.1:8010/?tab=<id>` for the 43 ids; the pages' own GET calls (14–41 endpoints per page, `audit.json` `api_endpoints`).
- Harness: `scripts/ui_audit.py`, `scripts/desktop_qa/probe.py` (READY_JS, FINGERPRINT_JS).
- Prior reviews cited: `reports/production_review/design_audit.md` (14 Oct), `reports/desktop_app/review/critics_round1.md` (C1-trader-ux), `reports/desktop_app/FINAL_REPORT.md`.
