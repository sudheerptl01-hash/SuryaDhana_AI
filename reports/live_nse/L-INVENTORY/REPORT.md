# L-INVENTORY — every price pane in the terminal, its source, its lag, and how it can go live from NSE

Written Thu 5 Nov 2026, 10:12–10:40 IST, market open. Survey only: source read on the tree as it is (Terminal v2 wave 1
committed, **not deployed**: its routes answer 404 on the running ui-api), plus paced GETs against the live stack
(≤ 1 request/s; 79 ui-api/data-service GETs in total, every NSE-backed route hit at most 4 times, ≥ 20 s apart, through
the existing cached client). Not called, on purpose: any route that would reach Yahoo (`/api/news-scanner/*`,
`/api/quotes/ticks`, `/api/commodity/*`, `/api/mcx/overlay`, `/api/gold/health`, `/api/market/results-reacting`), any route
that calls Breeze historical (`/api/data/live/intraday`, `/api/mcx/quote`), account data (`/api/positions/*` except the
connection-free budget probe, `/api/risk/dashboard`), every POST. One Breeze REST `get_quotes` was spent (the stock
window's `GET /api/data/live/quote/RELIANCE`). No restart, no write, no Telegram, no login. Scratch and raw probe output:
`/Users/sudheer/.suryadhana_pm_scratch/live/L-INVENTORY/` (`meas_a.json`, `meas_b.json`, `lag_samples.json`, `ui_scan2.txt`,
`api_routes.txt`, `rows.py`).

## Executive summary

1. **92 panes on 43 pages + the shell** (header, tape, watchlist line, hover card, news dock, stock window) show a price,
   change, volume, breadth, OI, IV or a number derived from them. Classified: **25 yes-breeze** (an NSE price the
   websocket can carry), **13 yes-nse-api** (NSE live aggregates: movers, breadth, chain, pre-open, filings, GIFT,
   valuation), **25 eod-only**, **10 periodic**, **19 n/a** (non-NSE or no market number). Full table in §5, ranked work in §4.
2. **Nothing on screen is Breeze-websocket live today.** `GET :8001/live/ticks` → `state OFF, connected false,
   subscribed 0` (10:15:57); `/ticks/store-status` → `started false`; CHRT intraday answers "no tick data for RELIANCE on
   2026-11-05". The engine is off (`LIVE_TICKS=0`) and, if armed, would still drop every tick: ticks arrive keyed
   `4.1!<NSE token>` and `live_ticks.py` maps by `stock_code`/isec (`_isec_to_sym`, `_SYMBOL_KEYS`), and `MAX_SYMBOLS = 50`
   is one short of NIFTY 50 + its 50 members.
3. **Yahoo is the live price of NSE stocks in 11 places**: the hover card, the news dock, the stock window (after its first
   paint), WTCH's table, BRF "Your book" day move, BRKR day move, ALRT table, the server-side price-alert check, the market
   map (names outside NSE's heatmap), "results reacting" (BRF + EVTS, filers outside the heatmap), and COMP's history
   (EOD, under a chip that says "NSE closes"). The DESK holdings overlay is Yahoo too whenever ticks are off.
4. **The stock window's broker price is overwritten by Yahoo.** It paints a Breeze REST quote on open (measured:
   `ltt 10:19:19` read at 10:19:19, i.e. real time), then `useLiveTicks` polls `/api/quotes/ticks` every 2 s; with ticks
   off, `services/ui-api/routers/quotes.py` fills every symbol from Yahoo and returns it inside the `ticks` map, and
   `StockDetailModal.tsx` copies any `tick.price` over the live price. Same mechanism on DESK and WTCH.
5. **Header NIFTY is ICICI, but by REST, not websocket**: data-service `_nifty_poller` calls `get_quotes` every 15 s
   (stored `ltt 10:19:16` at 10:19:17), pushed to the browser over Redis + the monitor socket. It runs outside the Breeze
   budget ledger and costs about **1,580 calls per session day = 32 % of ICICI's documented 5,000/day** (40 % of the
   owner's 4,000 cap). The websocket carries the same index at ~10 ticks/s with zero REST calls (PM probe, 10:00 today).
6. **NSE website APIs, measured lag now** (exchange stamp vs clock, at the moment the terminal would read it):
   allIndices (header fallback, tape, MOV/WEI index rows, valuation, contribution index level) **113–172 s**, stamped to the
   minute only; heatmap-symbols per-stock `lastUpdatedTime` **10–16 s** fresh, **10–68 s** as served (60 s cache);
   live-analysis movers **18–71 s**; option-chain-v3 **34–92 s** (NSE refreshes it about once a minute); index intraday
   chart **122 s**; internals archive **123 s** + its 2-min UI poll; GIFT **115 s**; announcements ≤ 60 s cache.
7. **Two honesty defects independent of the source**: BRF loads every panel **once per visit** (`useLoad` has no poll;
   only the intraday chart, 60 s, and the holdings move, 120 s, refresh), so its "who moved NIFTY", option line, GIFT and
   valuation freeze for as long as the page stays open; MOV hangs **one** chip (the live-analysis timestamp) on five panels
   whose real as-of differs by up to 2 minutes; MEMB loads once with `live:false`. The hover card shows no time at all.
8. **What the websocket fixes (ranked by how often the owner sees it)**: header + tape (every page), hover card (every
   ticker on every page), BRF, WTCH, MOV "who moved the index" (one connection = index + 50 members, verified), MKT map,
   stock window price + intraday, DESK/BRKR/RSK book marks, CHRT intraday (tick store), OMON/DERV/OSTR underlying spot,
   ALRT and the server alert check, MEMB points, EQS visible rows. Target order of sources for any NSE symbol:
   **Breeze tick ≤ 5 s → NSE heatmap row (age shown) → last close labelled CLOSE/STALE <date>**; Yahoo never.
9. **What stays on NSE's own APIs** (Breeze cannot give these aggregates): movers lists, breadth/internals, sector index
   rows, option-chain-v3 (until the Breeze chain tape through the budget ledger), pre-open (09:00–09:08 only), filings,
   GIFT NIFTY, live P/E. Keep the current TTLs (the 26-list heatmap fan-out is already the heaviest NSE load; tighter
   polling invites an Akamai block): make prices live through the websocket and label NSE panes with NSE's own stamp.
10. **35 panes can never be live** (25 EOD + 10 periodic: bhavcopy-based monitor/regime, F&O term structure/rollover/basis/
    PCR/IV history, participant OI, FII/DII, deals, MTF T−1 (served T+2: as_of 2026-11-02), shareholding, PIT (2026-10-30),
    valuation history (2026-10-30), Desk marks (2026-10-30), wraps, seasonality, results/fundamentals): each needs a
    `SourceChip` "EOD <publish date>". The chip plumbing exists: 131 of the 132 `<Panel>` instances in the page modules
    pass a `source` (the exception is the gold kit's own wrapper); what is wrong is what several chips *say* (§3).

---

## 1. Upstream sources, measured now (5 Nov, 10:15–10:21 IST)

Lag = clock at the GET minus the exchange/publisher stamp in the payload. "Served" includes the server cache; the UI poll
interval adds up to its own length on top.

| Upstream | Path in the stack | Caches end to end | Measured | Stamp quality |
|---|---|---|---|---|
| **Breeze websocket** (L1 ticks) | data-service `live_ticks.py` → `/live/ticks` → ui-api `/api/quotes/ticks` (2 s UI poll) | none (dict read) | **OFF**: `state OFF, subscribed 0` (10:15:57, 10:19:34); PM probe 10:00 today: 51 instruments, ~57 ticks/s, ltt→receive median **0.65 s**, p90 1.25 s, 0 REST calls | `ltt` per second |
| Breeze REST `get_quotes` (NIFTY) | data-service `_nifty_poller` every 15 s → DuckDB `live_quotes` + Redis `live.quotes` → monitor WS | 15 s poll | stored `ltt 10:19:16` read 10:19:17 (**0–15 s**) | `ltt` per second |
| Breeze REST `get_quotes` (one stock) | ui-api `/api/data/live/quote/{t}` → data-service `/live/quote` | none | RELIANCE `ltt 10:19:19` read 10:19:19 (**~0–1 s**) | `ltt` per second |
| Breeze REST watchlist poller | data-service `_watchlist_poller` every 15 s for Redis `monitored.stocks` | 15 s | **0 symbols** in the set (`/api/monitor/list`, 10:19) | — |
| NSE `allIndices` | `nse_live.get("allIndices", ttl_open=15)` | 15 s | 113, 114, 121, 128, 137, 154, 172, 119 s across 8 reads | **minute only** ("05-Nov-2026 10:14") |
| NSE `heatmap-symbols` (per index list) | `nse_live.heatmap_quotes()` / `index_members()` / contribution | 60 s | per-stock `lastUpdatedTime` **10–16 s** right after a refresh, **36–42 s**, **62–68 s** on later reads | per second, per stock |
| NSE `live-analysis-*` (movers) | `nse_live.snapshot()` (8 endpoints, 4 workers) | 30 s | **18, 20, 46, 71 s** (NSE stamp 10:15:41, 10:17:49 held for 71 s) | per second |
| NSE `option-chain-v3` | `/db/option-chain-live/{sym}` | 30 s | **92, 45, 70, 34 s** (NSE refreshes ≈ every 60 s) | per second |
| NSE `chart-databyindex` | `/db/index-intraday` | 30 s | last point 10:14:00 at 10:16:01 (**122 s**) | 1-min points |
| NSE allIndices samples (internals) | controller `internals_sample` every 2 min → `nse_archive/internals` | 2 min | last sample 10:14 at 10:16:02 (**123 s**) | minute |
| NSE `marketStatus` (GIFT NIFTY) | `/db/gift-nifty` | 30 s | **115 s** | minute |
| NSE `corporate-announcements` | `/db/announcements` | 60 s | newest filing 10:14:53 at 10:16:13 | per second |
| NSE pre-open | `/db/preopen` | auction 09:00–09:08, then 10 min | NSE ts 09:09:31 (final book) | per second |
| Yahoo chart quotes | ui-api `news_scanner` SWR (`QUOTE_REFRESH_AFTER_S 30`, `QUOTE_MAX_AGE_S 60`) | ≤ 60 s server, + hover 60 s client, + WTCH/ALRT/WEI 60 s polls | **not measured** (no-Yahoo rule); the code bound is ≤ 60 s served (typically ~58 s for a 60 s poller), up to ~120 s on the hover card, plus Yahoo's own exchange delay (unknown) | `regularMarketTime` (not shown) |
| DuckDB EOD tables | bhavcopy, F&O, participants, deals, monitor, ohlcv | — | 2026-11-04 for daily sets; MTF 2026-11-02; PIT, valuation history, Desk mark 2026-10-30 | date |

Wave 1 routes that 404 on the running ui-api (deploy tonight 21:37): `/api/market/index-drivers*`, `/api/derivatives/iv*`,
`/api/derivatives/vol-screen`, `/api/positions/breeze-budget` (so the budget ledger counters could not be read).

## 2. What "live from NSE" can mean per class (the target architecture in one paragraph)

- **yes-breeze (25 panes)**: one Breeze websocket in data-service (the existing `live_ticks.py` engine, fixed) carries
  every NSE-listed price the owner looks at: the always-on set (NIFTY 50 index, NIFTY BANK index, the 50 NIFTY members,
  holdings, Desk book, watchlist, alerted symbols) plus on-demand symbols with a TTL (stock window, hover, OMON/DERV/OSTR
  underlying, EQS visible rows). Verified today: one `ws_connect` held 51 instruments. The per-connection instrument limit
  beyond 51 is **unverified** and must be measured before the cap is raised past ~100. Order of sources for an NSE symbol
  in `/api/quotes/ticks` (and the hover card, which should move onto it): Breeze tick ≤ 5 s old → NSE heatmap row (its
  `lastUpdatedTime` as the age) → last stored close labelled `CLOSE <date>` / `STALE`. Yahoo stays only for non-NSE
  symbols (US, FX, commodities) through the existing single fetchers.
- **yes-nse-api (13 panes)**: aggregates Breeze does not publish (movers lists, breadth, internals, sector rows,
  option-chain-v3, pre-open, filings, GIFT, live P/E). Source unchanged; each panel shows NSE's own stamp and age, not a
  borrowed one. allIndices stamps only the minute and runs 1–3 minutes behind: label it `NSE DELAYED ≈ n min`, never LIVE.
- **eod-only / periodic (35 panes)**: cannot be live; `SourceChip` "NSE EOD <date>" / "<publisher> <period>", STALE when
  the date is behind the last session (MTF, PIT, valuation history and Desk mark are today).
- **n/a (19 panes)**: non-NSE instruments (world, commodities, COMEX/rupee gold model, MCX overlay) or no market number.

## 3. Defects found that block or mislabel "live" (file, evidence, fix owner-path)

| # | Defect | Where | Evidence | Consequence |
|---|---|---|---|---|
| D1 | Ticks never map to symbols | `services/data-service/live_ticks.py` (`_SYMBOL_KEYS = ("stock_code","symbol","stock_name")`, `_isec_to_sym` keyed by the isec code passed to `subscribe_feeds`) | PM probe: ticks arrive as `symbol "4.1!<NSE token>"` (index `"4.1!NIFTY 50"`); map with `get_names(exchange_code='NSE', stock_code=SYM)['isec_token_level1']`, first token (HDFCBANK `'4.1!1333 1462 17320'` → `'4.1!1333'`) | every tick lands under an unknown key: the Sep "L1 ticks silent" note |
| D2 | Cap one short | `live_ticks.py` `MAX_SYMBOLS = 50`, ui-api `quotes.py` `MAX_SYMBOLS = 60` | NIFTY 50 + members = 51; + BANK index + holdings + watchlist ≈ 60–120 | "who moved the index" cannot be fully live |
| D3 | Engine off, store not started | env `LIVE_TICKS=0` (default) | `/live/ticks state OFF`; `/ticks/store-status started false`; CHRT intraday 0 bars | CHRT/BRF/MOV intraday have no tick bars |
| D4 | Yahoo rows inside the tick map overwrite broker prices | `services/ui-api/routers/quotes.py` (misses → `_yahoo_quotes`, row `source "yahoo"`), consumed by `ui/components/StockDetailModal.tsx` (`if (tick?.price != null) setLivePrice(tick.price)`), `DecisionDesk.tsx`, `WatchMonitor.tsx` | code; stock window paints the Breeze REST quote then shows Yahoo with a DELAYED chip | NSE stock shown at a Yahoo price although a broker quote answered |
| D5 | BRF loads once per visit | `ui/components/Brief.tsx` `useLoad` (no interval; only ↻ REFRESH ALL) | code; contribution/option/GIFT/valuation/pre-open/world lines | numbers hours old on a page left open |
| D6 | One chip for five MOV panels | `ui/components/LiveMovers.tsx` `feedSource` from `live-movers.timestamp` reused on Intraday ×2, Who moved, Internals, Sector board | live-movers 18–71 s vs allIndices 114–154 s vs internals 123 s | chip age wrong by up to 2 min |
| D7 | Hover card has no time | `ui/components/terminal/index.tsx` `HoverCard` ("Yahoo · ≈1 min delayed", 60 s client Map on top of the 60 s SWR) | code | the owner's complaint this morning |
| D8 | NIFTY REST poller outside the budget ledger | `services/data-service/main.py` `_nifty_poller` (15 s, no `shared/breeze_budget` import in data-service) | 395 min × 4/min ≈ 1,580 calls/day | 32 % of the 5,000/day ceiling spent on a number the websocket gives free |
| D9 | Server price alerts on Yahoo | `services/ui-api/routers/alerts.py` `run_alerts` (`get_quotes(fresh=True)`) | code | alerts fire on a Yahoo price |
| D10 | Yahoo for NSE names outside the heatmap | `routers/markets.py` `_results_reacting`; `ui/components/MarketMap.tsx` `loadYahoo` | code | results-reacting and the map mix NSE and Yahoo moves in one panel |
| D11 | COMP history from Yahoo under "NSE closes" | `ui/components/Compare.tsx` → `/api/news-scanner/chart/{SYM.NS}` | code (`compareSrc` says 'NSE closes') | mislabelled source (EOD; switch to stored bhavcopy/ohlcv) |
| D12 | MEMB points today frozen, chip `live:false` | `ui/components/IndexMembers.tsx` | index stamp 172 s at load | stale "points today" |
| D13 | Tape shows one stamp for two sources | `MarketCommandHeader.tsx` "NSE + YAHOO · hh:mm" | code | a 2-min-old NSE index and a 1-min-old Yahoo FX share one time |

## 4. Ranked work (owner exposure first; P = rank used in the table)

| P | Work | Panes it makes live / honest | Depends on |
|---|---|---|---|
| 1 | Fix the tick engine (D1 token map via `get_names`, D2 cap ≥ 120, reconnect + session-expiry handling, budget-free) and arm `LIVE_TICKS=1` in one supervised session; header + tape read the `4.1!NIFTY 50` / `4.1!NIFTY BANK` ticks; retire the 15 s REST NIFTY poller (D8) | header NIFTY, tape NIFTY/BANK (VIX if carried), watchlist line | owner: data-service restart outside 07:45–09:20 / 18:30–21:15, restart order ui-api → data-service → ui-api |
| 2 | `/api/quotes/ticks` source order Breeze → NSE heatmap row → CLOSE/STALE, per-row `source` + `age_s`; never a Yahoo row for an NSE symbol (D4); the hover card and the news dock read it, with a time line (D7) | hover card, news dock, stock window price | P1 |
| 3 | BRF: poll the live lines (60 s NSE, ticks for prices) (D5); "who moved NIFTY" from ticks | BRF ×6 | P1, P2 |
| 4 | WTCH rows, DESK book, BRKR day move, ALRT table + server check (D9) on ticks (ensure the symbols) | WTCH, DESK, BRKR, ALRT | P1, P2 |
| 5 | MOV: who moved the index from the 51-instrument subscription; one chip per panel with its own as-of (D6); map without Yahoo (D10) | MOV ×7, MKT map | P1 |
| 6 | Tick store → 1-min bars + VWAP for CHRT intraday, BRF/MOV intraday charts, stock-window intraday (today) | CHRT, BRF, MOV, stock window | P1 |
| 7 | OMON/DERV/OSTR underlying spot from ticks; chain panels show NSE's `records.timestamp` age; OSTR seeds from the live chain in session | OMON, DERV, OSTR | P1 |
| 8 | MEMB points (D12), EVTS/BRF results reacting (D10), EQS visible rows, MCXG (Breeze MCX tick, saves REST) | MEMB, EVTS, EQS, MCXG | P1, P2 |
| 9 | EOD/periodic chip sweep: "NSE EOD <date>", STALE when behind; COMP to stored closes (D11); tape per-item stamp (D13) | the 35 EOD/periodic panes | — |

## 5. Full inventory (92 rows)

Polls and TTLs are as in the code on 5 Nov; "UI" = the browser poll. `ui/` paths are relative to the repo. Rebuilt by the PM from the agent's structured rows (the original file was overwritten during integration); P = rank where the original table carried it.

| P | Page | Pane | UI file | API route(s) | Current source and TTLs end to end | Measured lag (5 Nov, 10:15-10:21 IST) | live_capable | Target source |
|---|---|---|---|---|---|---|---|---|
| 1 | ALL (header) | NIFTY 50 chip: LTP, change, %, O/H/L + LIVE/NSE/STALE/CLOSE chip | `ui/components/MarketCommandHeader.tsx` | WS /api/monitor/ws/monitor; GET /api/market/nifty-live; GET /api/data/live/index/nifty | Breeze REST get_quotes NIFTY every 15 s (data-service _nifty_poller, outside budget ledger, ~1,580 calls/day) -> Redis -> monitor WS; fallback NSE allIndices (15 s cache, UI 15 s); last fallback stored ICICI quote (UI 5 s) | REST ltt 10:19:16 read 10:19:17 (0-15 s by cadence); NSE fallback 113-154 s | **yes-breeze** | Breeze ws tick '4.1!NIFTY 50' (~10 ticks/s, median 0.65 s, 0 REST); NSE allIndices labelled 'NSE DELAYED <age>' as fallback; CLOSE <date> after 15:30; retire the REST poller |
| 1 | ALL (tape) | Tape: NIFTY 50, BANK NIFTY, INDIA VIX | `ui/components/MarketCommandHeader.tsx` | GET /api/market/indices-live | NSE allIndices (15 s cache in session); UI 60 s; one 'NSE + YAHOO hh:mm' stamp for the whole tape | 114 s (NSE '10:14' at 10:15:53); worst ~3.5 min with the 60 s poll | **yes-breeze** | Breeze ws index ticks NIFTY 50 / NIFTY BANK (VIX if the ws carries it, unverified; else NSE labelled DELAYED); per-item age |
| 1 | ALL (tape) | Tape: GIFT NIFTY | `ui/components/MarketCommandHeader.tsx` | GET /api/market/gift-nifty | NSE marketStatus.giftnifty (30 s cache); UI 60 s | 115 s | **yes-nse-api** | keep NSE marketStatus with its own TIMESTMP age |
| 1 | ALL (tape) | Tape: USD/INR, BRENT, GOLD GC1, S&P 500 | `ui/components/MarketCommandHeader.tsx` | GET /api/news-scanner/quotes | Yahoo chart via the one SWR cache (refresh 30 s, max 60 s); UI 60 s | not measured (no-Yahoo rule); code bound <= 60 s served, typ ~58 s | n/a | keep Yahoo (non-NSE, single fetcher), label DELAYED <age> per item |
| — | ALL (header) | Watchlist line (LiveMonitorBar) | `ui/components/LiveMonitorBar.tsx` | WS /api/monitor/ws/monitor | Breeze REST get_quotes per watched symbol every 15 s (_watchlist_poller, <=50) -> Redis -> WS | monitored set = 0 symbols at 10:19 (nothing streamed) | **yes-breeze** | Breeze ws ticks for the watchlist, no REST polling |
| — | ALL (hover card) | TickerLink hover card: last, day %, day/52w range, 1-month spark, P/E line | `ui/components/terminal/index.tsx (HoverCard)` | GET /api/news-scanner/quotes?symbols=SYM.NS; GET /api/market/financials-latest | Yahoo chart 1mo/1d (SWR <= 60 s) + 60 s client cache; no timestamp shown; spark = 22 daily closes | not measured (no-Yahoo); code: up to ~120 s + Yahoo's own delay | **yes-breeze** | subscribe-on-hover Breeze ws tick, else NSE heatmap row (lastUpdatedTime), else CLOSE <date>; spark from stored EOD + tick bars; source + age line; never Yahoo for .NS |
| 2 | ALL (news dock) | News dock (Shift+N): picks' quotes + charts | `ui/components/news/NewsTerminal.tsx` | GET /api/news-scanner/quotes; /api/news-scanner/chart/{SYM.NS} | Yahoo quotes (SWR <= 60 s) + Yahoo charts | not measured (no-Yahoo) | **yes-breeze** | Breeze ws / NSE heatmap prices; charts from stored EOD + tick bars |
| — | BRF | Market panel: regime, breadth, valuation line, GIFT line, global cues | `ui/components/Brief.tsx` | GET /api/market/monitor, /index-valuation, /gift-nifty, /api/news-scanner/quotes | loaded ONCE per visit (useLoad, no poll): DuckDB monitor EOD + NSE allIndices P/E + NSE marketStatus + Yahoo | monitor 2026-11-04; valuation 137 s; GIFT 115 s, then frozen while open | **yes-nse-api** | regime/breadth EOD chip; valuation + GIFT re-polled 60 s with NSE age; global cues Yahoo labelled |
| — | BRF | Your book: Desk value/return + ICICI holdings today's move | `ui/components/Brief.tsx` | GET /api/desk/status, /api/positions/open-positions, /api/news-scanner/quotes (120 s) | Desk ledger (EOD mark) + Breeze REST holdings + Yahoo day move per holding | desk last_mark 2026-10-30; holdings not probed | **yes-breeze** | Breeze ws ticks for held symbols (pinned); Desk mark labelled EOD <date> |
| 3 | BRF | Market today: intraday NIFTY chart | `ui/components/IndexIntraday.tsx` | GET /api/market/index-intraday | NSE chart-databyindex (30 s cache); UI 60 s | 122 s | **yes-breeze** | tick-store 1-min bars from the Breeze ws index tick; NSE chart labelled fallback |
| — | BRF | Market today: NIFTY 500 breadth line | `ui/components/Brief.tsx` | GET /api/market/internals | controller samples of NSE allIndices every 2 min; loaded once per visit | 123 s + page-open age | **yes-nse-api** | NSE allIndices breadth re-polled 2 min, age chip |
| — | BRF | Market today: who moved NIFTY | `ui/components/Brief.tsx` | GET /api/market/index-contribution | NSE heatmap NIFTY 50 (60 s) + allIndices (15 s); loaded once per visit | members 10-68 s, index 121 s, then frozen | **yes-breeze** | Breeze ws index + 50 members on one connection; recompute per tick or 2-5 s |
| — | BRF | NIFTY options line (ATM IV, PCR, max pain) | `ui/components/Brief.tsx` | GET /api/market/option-chain-live/NIFTY | NSE option-chain-v3 (30 s cache) in session, EOD otherwise; loaded once per visit | 34-92 s | **yes-nse-api** | NSE v3 re-polled 60 s with records.timestamp; spot from Breeze tick |
| — | BRF | Pre-open line | `ui/components/Brief.tsx` | GET /api/market/preopen | NSE pre-open (09:00-09:08), archived | NSE ts 09:09:31 (final book) | periodic | NSE pre-open live 09:00-09:08; 'PRE-OPEN <date>' after |
| — | BRF | Results reacting today | `ui/components/Brief.tsx` | GET /api/market/results-reacting | NSE announcements + NSE heatmap + Yahoo for filers outside the heatmap | not measured (route calls Yahoo) | **yes-breeze** | Breeze ws (ensure on demand) / NSE heatmap; never Yahoo |
| 3 | BRF | FII/DII cash line | `ui/components/Brief.tsx` | GET /api/market/fii-dii-cash | NSE fiidiiTradeReact stored 20:30 | through 2026-11-04 | eod-only | chip 'NSE EOD <date> (provisional)' |
| 3 | BRF | This week / News scanner / Headlines / System | `ui/components/Brief.tsx` | GET /api/market/events, /api/news-scanner/scan, /api/market/headlines, /api/telemetry/status | stored NSE calendar, scanner JSON, Google News RSS, controller | - | n/a | unchanged; dated chips |
| — | WTCH | Monitor table: price, day %, ranges, spark, volume | `ui/components/WatchMonitor.tsx` | GET /api/news-scanner/quotes (60 s); GET /api/quotes/ticks (2 s) | Yahoo SWR on a 60 s poll; the 2 s tick overlay falls back to the same Yahoo cache (LIVE_TICKS=0) | not measured (no-Yahoo); ticks state OFF | **yes-breeze** | Breeze ws per row (raised cap), NSE heatmap overflow, CLOSE labelled; per-row source + age |
| — | WTCH | Your book X-ray, alerts panel, best/worst | `ui/components/WatchMonitor.tsx` | GET /api/market/basket-risk, /api/alerts | DuckDB EOD returns + alert levels | EOD 2026-11-04 | eod-only | EOD chip |
| — | ALRT/WTCH (server) | Server-side price-alert check (inbox + Telegram) | `services/ui-api/routers/alerts.py` | POST /api/alerts/run (scheduler, every minute) | Yahoo get_quotes fresh=True (< 30 s) | not measured (POST + Yahoo) | **yes-breeze** | Breeze ws ticks for alerted symbols, cross on tick; NSE heatmap fallback |
| — | MOV | Index tiles: NIFTY 50, NIFTY 500 breadth, Mid/Small 100, 52w counts | `ui/components/LiveMovers.tsx` | GET /api/market/live-movers | NSE allIndices + live-analysis snapshot (30 s); UI 30 s; ONE shared chip for all panels | movers stamp 18-71 s; allIndices 114-154 s | **yes-nse-api** | index levels from Breeze ws; breadth NSE with own stamp; one chip per panel |
| — | MOV | Gainers/Losers/Most active/Volume surge/52w highs-lows/OI spurts | `ui/components/LiveMovers.tsx` | GET /api/market/live-movers | NSE live-analysis-* (30 s cache; UI 30 s) | 18-71 s | **yes-nse-api** | keep NSE (aggregate), show NSE timestamp age; LTP may overlay Breeze ticks |
| — | MOV | Intraday NIFTY 50 / NIFTY BANK charts | `ui/components/IndexIntraday.tsx` | GET /api/market/index-intraday | NSE chart-databyindex (30 s); UI 60 s; chip borrowed from movers | 122 s | **yes-breeze** | tick-store bars from Breeze ws index ticks; NSE fallback labelled |
| — | MOV | Who moved the index (points per member) | `ui/components/IndexContribution.tsx` | GET /api/market/index-contribution | NSE heatmap (60 s) + allIndices (15 s), weights from filings; UI 120 s | members 10-68 s, index 121 s; + up to 120 s poll (~4 min worst) | **yes-breeze** | Breeze ws index + 50 members (verified 10:00 today: 6,850 ticks/120 s); push or 2-5 s; BREEZE LIVE <age> |
| — | MOV | Market internals | `ui/components/MarketInternals.tsx` | GET /api/market/internals | controller allIndices samples every 2 min; UI 120 s | 123 s + up to 120 s poll | **yes-nse-api** | NSE allIndices breadth 1-2 min, age chip |
| — | MOV | Sector board + drill-down members | `ui/components/LiveMovers.tsx` | GET /api/market/live-movers; /api/market/index-members | NSE allIndices sector rows + NSE heatmap per sector (60 s; UI 60 s) | members 10-68 s; sector rows 114-154 s | **yes-nse-api** | sector rows NSE; members from Breeze ws when subscribed, NSE heatmap otherwise |
| — | MOV/MKT | Market map (LIVE mode) | `ui/components/MarketMap.tsx` | GET /api/market/live-quotes; /api/news-scanner/quotes | NSE heatmap (~300 names, 60 s) + Yahoo for other NSE names (5 min); UI 60 s | heatmap rows 10-68 s; Yahoo part not measured | **yes-nse-api** | NSE heatmap only (+ more broad lists if served), rest EOD labelled; never Yahoo |
| — | MKT | Regime, A/D, DMA breadth, 52w, Monitor ±4 %, distribution days, VIX, 1-yr breadth, industry table/rotation | `ui/components/MarketMonitor.tsx` | GET /api/market/monitor | DuckDB market monitor from NSE bhavcopy (18:30 job) | as_of 2026-11-04 | eod-only | chip 'NSE EOD 2026-11-04' |
| — | MKT | Valuation NSE (P/E, P/B, DY now) | `ui/components/IndexValuation.tsx` | GET /api/market/index-valuation | NSE allIndices pe/pb/dy (15 s); loaded on mount | 137 s | **yes-nse-api** | keep NSE, age chip, re-poll 60 s |
| — | MKT | Valuation history + equity vs bonds | `ui/components/IndexValuation.tsx` | GET /api/market/index-valuation-history, /yield-gap | NSE daily index file (19:15 job) + bond yields | asof 2026-10-30 (4 sessions behind) | eod-only | EOD chip, STALE when behind |
| — | MKT | Who holds index futures + FII/DII cash | `ui/components/ParticipantPositioning.tsx` | GET /api/market/participants, /fii-dii-cash | NSE participant OI (20:10) + FII/DII (20:30) | 2026-11-04 | eod-only | chip 'NSE EOD <date>' |
| — | Stock window (?sym=) | Header price line: LTP, change, %, LIVE/DELAYED/CLOSE marker | `ui/components/StockDetailModal.tsx` | GET /api/data/live/quote/{t}; WS monitor; GET /api/quotes/ticks (2 s) | Breeze REST get_quotes once on open, then overwritten every 2 s by the quotes.py Yahoo fallback (LIVE_TICKS=0); chip DELAYED | REST ltt 10:19:19 read 10:19:19 (~0-1 s); Yahoo price that stays not measured | **yes-breeze** | Breeze ws tick (ensure on open) as the only price; REST quote first paint; NSE heatmap fallback; never Yahoo |
| — | Stock window (?sym=) | Intraday chart tab (5-min) | `ui/components/StockDetailModal.tsx` | GET /api/data/live/intraday/{t} | Breeze REST get_historical_data_v2 -> NSE chart-databysymbol (30 s) -> daily bars | not measured (Breeze historical not allowed) | **yes-breeze** | tick-store bars today; Breeze historical via budget ledger for past days; NSE fallback labelled |
| — | Stock window (?sym=) | Daily chart / Data / HP / SEAG tabs | `ui/components/StockDetailModal.tsx` | GET /api/stocks/{t}/ohlcv, /api/data/ohlcv/{t}, /api/market/seasonality, /index-daily | DuckDB ohlcv (Yahoo EOD history) + nse_bhavcopy | last bar 2026-11-04 | eod-only | chip 'EOD <date>'; forming candle from tick store |
| — | Stock window (?sym=) | Profile DES/FA/ERN/filings/actions | `ui/components/StockProfile.tsx` | GET /api/stocks/{t}/profile etc. | NSE bhavcopy + results XBRL + actions (stored) | per filing | periodic | dated chips |
| — | Stock window (?sym=) | Trade ticket cost estimate | `ui/components/TradeTicket.tsx` | GET /api/costs/ticket | arithmetic on the price passed in | - | n/a | price input = the live tick shown |
| — | DESK | Holdings: Last, value, P&L | `ui/components/DecisionDesk.tsx` | GET /api/desk/status; GET /api/quotes/ticks (2 s) | Desk paper marks overlaid by /api/quotes/ticks = Yahoo while LIVE_TICKS=0 | last_mark 2026-10-30 (Nov plan pending, cash) | **yes-breeze** | Breeze ws ticks for the book; 'MARK EOD <date>' beside |
| — | DESK | Brief / momentum watchlist / NAV / rules / activity | `ui/components/DecisionDesk.tsx` | GET /api/desk/status, /api/desk/preview | Desk ledger + DuckDB EOD ranks | signal_date 2026-10-30 | eod-only | chip 'Desk EOD <date>' |
| — | DESK | Crash filter (NIFTY vs 200-DMA) | `ui/components/DecisionDesk.tsx` | GET /api/market/crash-filter | DuckDB index closes | 2026-11-04 | eod-only | EOD chip; optional live context from the Breeze index tick |
| — | DESK | Book vs NIFTY attribution; Drivers (wave 1) | `ui/components/drivers/DeskAttribution.tsx` | GET /api/desk/attribution, /api/market/index-drivers* | EOD bhavcopy attribution (wave 1) | 404 (not deployed) | eod-only | EOD chips |
| — | CHRT | Intraday 1m/5m/15m candles + VWAP | `ui/components/ChartStudio.tsx` | GET /api/charts/intraday -> data-service /ticks/bars | tick store fed by live_ticks.py: LIVE_TICKS=0, store not started, '4.1!' ticks would not map; UI 60 s | 0 bars ('no tick data for RELIANCE on 2026-11-05') | **yes-breeze** | Breeze ws ticks persisted (token map fix, cap > 51) -> 1m bars + VWAP; NSE chart-databysymbol fallback labelled |
| — | CHRT | Daily/weekly/monthly candles + indicators | `ui/components/ChartStudio.tsx` | GET /api/charts/ohlcv | DuckDB ohlcv (Yahoo EOD) 60 s cache | as_of 2026-11-04 | eod-only | EOD chip; forming daily bar from tick store |
| — | OMON | LIVE chain: spot/forward, ATM IV, range, PCR, max pain, OI walls, chain, smile | `ui/components/OptionChain.tsx` | GET /api/market/option-chain-live/{sym} | NSE option-chain-v3 (30 s) + IV/forward in data-service; UI 30 s; spot = NSE underlyingValue | 34-92 s | **yes-nse-api** | NSE v3 with records.timestamp age; spot tile from Breeze ws tick; Breeze chain quotes via budget ledger later |
| — | OMON | EOD chain + IV/PCR history, IV rank | `ui/components/OptionChain.tsx` | GET /api/market/option-chain/{sym}, /option-history/{sym} | NSE F&O bhavcopy (20:10) -> derived history | 2026-11-04 | eod-only | chip 'NSE F&O EOD <date>' |
| — | OMON | IV today 15-min pilot (wave 1) | `ui/components/vol/IvLivePath.tsx` | GET /api/derivatives/iv/{sym}/intraday | planned stored Breeze chain / NSE v3 snapshots | 404 (not deployed) | periodic | as PLAN, chip LIVE Breeze / LIVE NSE / OFFLINE + age |
| — | OMON | Option pricer | `ui/components/OptionPricer.tsx` | - | client Black-76 on chain row | - | n/a | inherits chain chip |
| — | DERV | Underlying spot tile + futures OI | `ui/components/DerivativesDesk.tsx` | GET /api/derivatives/term-structure | NSE F&O bhavcopy + index closes (EOD) | as_of 2026-11-04 | **yes-breeze** | Breeze ws tick for the underlying in session; CLOSE <date> after |
| — | DERV | Term structure, rollover, basis, PCR & max pain, VIX history, realised vol | `ui/components/DerivativesDesk.tsx` | GET /api/derivatives/* | NSE F&O bhavcopy + market_index_daily | 2026-11-04 | eod-only | EOD chips; optional live basis tile from Breeze futures - index ticks |
| — | DERV | VOL view: skew, term, IV cone, screener (wave 1) | `ui/components/vol/VolView.tsx` | GET /api/derivatives/iv*, /vol-screen | IV store from F&O bhavcopy | 404 (not deployed) | eod-only | EOD chips |
| — | OSTR | Legs priced off the chain, Greeks, payoff, margin | `ui/components/StrategyBuilder.tsx` | GET /api/market/option-chain/{sym}; POST /api/options/strategy/analyze | EOD chain seed + Black-76 | chain 2026-11-04 | **yes-nse-api** | seed from NSE v3 live chain in session (timestamp shown), spot from Breeze tick |
| — | MEMB | Members: weight, points today, returns, 52w, P/E; breadth, top-5 | `ui/components/IndexMembers.tsx` | GET /api/market/index-memb | index-contribution (NSE heatmap + allIndices) + DuckDB returns; loaded once; chip live:false | index 172 s; members <= 68 s; then frozen | **yes-breeze** | points + LTP from the MOV Breeze subscription; returns/P/E EOD dated |
| — | MEMB | Drivers: sector contribution, leaderboard (wave 1) | `ui/components/drivers/DriversView.tsx` | GET /api/market/index-drivers* | EOD bhavcopy | 404 (not deployed) | eod-only | EOD chips |
| — | ALRT | Price alerts table (price vs levels) | `ui/components/AlertsCenter.tsx` | GET /api/news-scanner/quotes (60 s) | Yahoo SWR on a 60 s poll | not measured (no-Yahoo) | **yes-breeze** | Breeze ws ticks; NSE heatmap fallback |
| — | ALRT | Fired / Inbox | `ui/components/AlertsCenter.tsx` | GET /api/alerts, /api/alerts/feed | alert history + notifications.jsonl | - | n/a | unchanged |
| — | EVTS | Results reacting today | `ui/components/EventCalendar.tsx` | GET /api/market/results-reacting (UI 120 s) | NSE announcements + heatmap + Yahoo for the rest | not measured (Yahoo) | **yes-breeze** | Breeze ws / NSE heatmap; never Yahoo |
| — | EVTS | Your stocks, season, next five weeks, all events, eco | `ui/components/EventCalendar.tsx` | GET /api/market/events, /results-recent, /eco-calendar | stored NSE calendar + results + MoSPI/RBI/Fed | events through 2026-12-05 (R-DATA) | periodic | dated chips |
| — | EVTS | Options into results + IV crush ledger | `ui/components/ResultsImpliedMoves.tsx` | GET /api/market/results-implied-moves | EOD F&O bhavcopy | fo_date 2026-11-04 | eod-only | chip 'NSE F&O EOD <date>' |
| — | WEI | India row: NIFTY/BANK/VIX/GIFT/breadth | `ui/components/WorldMarkets.tsx` | GET /api/market/indices-live, /gift-nifty, /live-movers | NSE allIndices / marketStatus / live-analysis; UI 60-120 s | 114-154 s; GIFT 115 s | **yes-breeze** | Breeze ws NIFTY 50 / NIFTY BANK; NSE for VIX, GIFT, breadth with ages |
| — | WEI | World boards: US/Europe/Asia/FX/commodities/rates | `ui/components/WorldMarkets.tsx` | GET /api/news-scanner/quotes (60 s) | Yahoo SWR | not measured (no-Yahoo) | n/a | keep Yahoo (non-NSE), DELAYED <age> |
| — | WEI | Policy dates (FOMC, RBI) | `ui/components/WorldMarkets.tsx` | GET /api/market/fomc, /rbi-mpc | Fed / RBI calendars | - | n/a | unchanged |
| — | PRE | Pre-open book: IEP, gaps, matched, imbalance | `ui/components/PreOpen.tsx` | GET /api/market/preopen | NSE pre-open (UI 20 s during 09:00-09:08); archived | NSE ts 09:09:31 | periodic | NSE live 09:00-09:08 with age; 'PRE-OPEN <date> 09:08' after |
| — | CF | Company filings list | `ui/components/CompanyFilings.tsx` | GET /api/market/announcements (UI 60 s) | NSE corporate-announcements (60 s cache) | newest filing 10:14:53 at 10:16:13 | **yes-nse-api** | keep NSE, age chip |
| — | IPO | Open issues (live subscription) + listings scorecard | `ui/components/IpoMonitor.tsx` | GET /api/market/ipo (UI 20 s) | NSE ipo-current-issue (TTL caches) + bhavcopy | no timestamp in payload | periodic | NSE subscription with its update time; scorecard EOD chip |
| — | EQS | Stocks table: CMP + flash, T1-T8, MA50, RS | `ui/components/StockTable.tsx` | AppContext universe + WS /api/monitor/ws/monitor | DuckDB latest_price (Yahoo EOD) + REST-poller ticks only for monitored set (0) -> effectively EOD | latest close 2026-11-04 | **yes-breeze** | NSE heatmap ~300 + Breeze ws for watched/visible rows; rest 'CLOSE <date>' |
| — | BRKR | Holdings, allocation, P&L, day move | `ui/components/PortfolioSummary.tsx` | GET /api/positions/summary, /open-positions (15 s); /api/news-scanner/quotes (60 s) | Breeze REST holdings/funds + Yahoo day move | not probed (account data) | **yes-breeze** | Breeze ws ticks for held symbols; REST only for qty/cost |
| — | RSK | VaR, beta, drawdown, holdings risk, sectors, stress | `ui/components/RiskDashboard.tsx` | GET /api/risk/dashboard | Desk ledger + broker book file + DuckDB EOD | not probed (account data) | eod-only | EOD chip; NAV optionally marked on ticks (labelled) |
| — | COMP | Performance, risk & return, correlation | `ui/components/Compare.tsx` | GET /api/news-scanner/chart/{SYM.NS} | Yahoo chart history for NSE stocks under a chip saying 'NSE closes' | not measured (Yahoo) | eod-only | stored nse_bhavcopy/ohlcv closes, chip 'NSE EOD <date>' |
| — | COMP | Fundamentals | `ui/components/Compare.tsx` | GET /api/market/financials-latest | NSE results XBRL (stored) | per company | periodic | dated chip |
| — | MCXG | MCX gold quote: LTP, O/H/L, prev close, band | `ui/components/McxGoldDesk.tsx` | GET /api/mcx/quote (UI 30 s) | Breeze REST get_quotes MCX (QUOTE_TTL_S) + historical v2 | not measured (route calls Breeze historical) | **yes-breeze** | Breeze ws MCX futures tick (MCX, not NSE) on the same connection |
| — | MCXG | Fair value overlay, session, contracts, paper ticket | `ui/components/McxGoldDesk.tsx` | GET /api/mcx/overlay, /session, /api/gold/contracts | Yahoo single fetcher (SWR 30/120 s) + MCX calendar + margins | session as_of 1 s | n/a | unchanged (non-NSE) |
| — | GOLD | 9 sub-views + pre-open desk | `ui/components/gold/*.tsx` | GET /api/gold/*, /api/commodity/gold-preopen | stored gold_* tables (catalog chips) + Yahoo 1-min bars via data-service job | per catalog (not re-measured) | n/a | unchanged (gold rules; nothing gold feeds NSE panes) |
| — | CMDT | Global commodity board + charts | `ui/components/CommodityTab.tsx` | GET /api/commodity/overview (60 s), /price/{sym} | Yahoo chart (60 s / 300 s) | not measured (Yahoo) | n/a | unchanged, DELAYED <age> |
| — | DEAL | Bulk/block deals, netted clients, short selling | `ui/components/DealsMonitor.tsx` | GET /api/market/deals, /short-selling | NSE deals API stored 20:30 | through 2026-11-04 | eod-only | chip 'NSE EOD <date>' |
| — | MRGN | MTF book, build-ups, crowded, largest funded | `ui/components/MarginMonitor.tsx` | GET /api/market/mtf-monitor | NSE MTF file (T-1, ~22:12) | as_of 2026-11-02 (T+2) | eod-only | chip 'NSE MTF <date> (T-1)' STALE |
| — | HDS | Ownership shifts | `ui/components/OwnershipShifts.tsx` | GET /api/market/holding-changes | NSE shareholding XBRL (quarterly) | quarterly | periodic | chip 'quarter ended <date>' |
| — | INSD | Insider buying + since-filing return | `ui/components/InsiderMonitor.tsx` | GET /api/market/insider-buys | NSE PIT (Sat weekly job) | last_date 2026-10-30 | periodic | chip 'PIT through <date>' |
| — | WRAP | Daily wrap archive + document | `ui/components/DailyWrap.tsx` | GET /api/market/wraps | markdown written 21:00 | 2026-11-04 | eod-only | dated chip per section |
| — | FUND | Fundamentals screener | `ui/components/FundamentalsScreen.tsx` | GET /api/market/fundamentals-screen | NSE results XBRL + bhavcopy price | per filing | periodic | dated chips; price EOD labelled |
| — | SEAG | Seasonality grid | `ui/components/Seasonality.tsx` | GET /api/market/seasonality | DuckDB EOD | asof 2026-11-04 | eod-only | EOD chip |
| — | ECO | Economic calendar | `ui/components/EconomicCalendar.tsx` | GET /api/market/eco-calendar | MoSPI/RBI/Fed calendars + NSE holidays | - | n/a | unchanged |
| — | OVRV | System status, data freshness | `ui/components/SystemStatusWidget.tsx` | GET /api/data/provider/status | service + DuckDB meta | provider connected=True | n/a | unchanged |
| — | SYS | Services, jobs, broker latency; data health (wave 1) | `ui/components/SystemTelemetry.tsx` | GET /api/telemetry/status, /api/data/health | controller + dataset catalog | - | n/a | add a live-feeds row per source with last-tick age |
| — | WHSE | Warehouse coverage, NSE datasets | `ui/components/WarehouseHealth.tsx` | GET /api/data/db/* | DuckDB meta | - | n/a | unchanged |
| — | BTST | Backtest lab | `ui/components/BacktestPanel.tsx` | /api/analytics/* | DuckDB EOD history | - | eod-only | unchanged |
| — | PORT | Legacy portfolio / execution control (dormant) | `ui/components/LivePortfolio.tsx` | GET /api/execution/*, /api/positions/summary (8 s) | dormant execution-service + Breeze REST summary | - | n/a | no live price; move under RESEARCH |
| — | PIPE | ML pipeline studio | `ui/components/PipelineStudio.tsx` | GET /api/pipeline/* | legacy ML artefacts | - | n/a | unchanged |
| — | LWSC | LW scanner | `ui/components/LWScanner.tsx` | GET /api/lw/* | DuckDB EOD | - | eod-only | EOD chip |
| — | ALFA | Alpha discovery | `ui/components/AlphaDiscoveryDesk.tsx` | GET /api/alpha/* | DuckDB EOD | - | eod-only | EOD chip |
| — | GBOX | Glass-box studio | `ui/components/GlassBoxStudio.tsx` | GET /api/analytics/factor-series, rrg, volume-profile | DuckDB EOD | - | eod-only | EOD chip |
| — | MLEN | ML engine workspace | `ui/components/MLEngineWorkspace.tsx` | /api/ml/train/stream | local training | - | n/a | unchanged |
| — | DEXP | Data explorer | `ui/components/DataExplorerTab.tsx` | GET /api/data/provider/status | DuckDB / history fetch | - | n/a | unchanged |
| — | RSCH | Research library | `ui/components/ResearchLibrary.tsx` | GET /api/research* | reports on disk | - | n/a | unchanged |

## 6. Facts and risks

- Breeze websocket engine is OFF: GET :8001/live/ticks -> state OFF, connected false, subscribed 0 (10:15:57 and 10:19:34); /ticks/store-status started=false; /api/charts/intraday RELIANCE 1m -> 0 bars, 'no tick data for RELIANCE on 2026-11-05'.
- services/data-service/live_ticks.py maps ticks by stock_code/symbol/stock_name through _isec_to_sym keyed on the isec code; Breeze ticks arrive keyed '4.1!<NSE token>' (index '4.1!NIFTY 50'), so every tick would land under an unknown key. MAX_SYMBOLS=50 is below the 51 needed for NIFTY 50 plus members; ui-api quotes.py MAX_SYMBOLS=60.
- Header NIFTY is Breeze REST: data-service _nifty_poller calls get_quotes every 15 s (09:00-15:35), outside shared/breeze_budget (data-service never imports it): about 1,580 calls/day, 32 % of the 5,000/day ceiling and 40 % of the 4,000 owner cap. Stored ltt 10:19:16 was read at 10:19:17.
- Breeze REST stock quote measured real time: /api/data/live/quote/RELIANCE ltt 10:19:19 read at 10:19:19 (1 get_quotes spent).
- Watchlist REST poller has nothing to do: /api/monitor/list -> 0 symbols at 10:19.
- ui-api routers/quotes.py fills every symbol without a tick <= 5 s old from Yahoo and returns those rows inside the 'ticks' map with source 'yahoo'. StockDetailModal.tsx copies any tick.price over the Breeze REST price, so the stock window shows Yahoo every 2 s. DecisionDesk.tsx and WatchMonitor.tsx use the same overlay.
- NSE allIndices (header fallback, tape, MOV/WEI index rows, valuation, contribution index level) measured 113-172 s behind, timestamp to the minute only.
- NSE heatmap-symbols per-stock lastUpdatedTime is 10-16 s old right after a refresh and 10-68 s as served (60 s cache); NSE live-analysis movers 18-71 s; option-chain-v3 34-92 s (NSE refreshes it about every 60 s); chart-databyindex 122 s; internals archive 123 s; GIFT 115 s.
- Brief.tsx useLoad loads every panel once per visit with no polling (only IndexIntraday at 60 s and holdings at 120 s refresh), so BRF's who-moved, option, GIFT and valuation lines freeze while the page stays open.
- LiveMovers.tsx uses one feedSource (the live-movers timestamp) as the chip for Intraday x2, Who moved, Internals and Sector board, although their real as-of times differ by up to 2 min. IndexMembers.tsx loads once with live:false.
- Yahoo is the source of NSE stock prices in 11 places: hover card (terminal/index.tsx, 60 s client cache, no timestamp), news dock, stock window, WTCH table, BRF and BRKR holdings day move, ALRT table, server price alerts (alerts.py run_alerts fresh=True), market map outside the heatmap, results-reacting (markets.py), COMP history (Yahoo chart under an 'NSE closes' chip).
- 131 of 132 <Panel> instances in the page modules pass a source prop; what is wrong is what several chips say, not that they are missing.
- Terminal v2 wave 1 routes return 404 on the running ui-api: /api/market/index-drivers, /api/derivatives/iv/NIFTY, /api/derivatives/vol-screen, /api/positions/breeze-budget.
- EOD sets current to 2026-11-04 (monitor, F&O, participants, deals, crash filter, ohlcv); MTF as_of 2026-11-02 (T+2); index valuation history, insider PIT and the Desk mark are at 2026-10-30.
- Inventory: 92 panes; 25 yes-breeze, 13 yes-nse-api, 25 eod-only, 10 periodic, 19 n/a; all 43 pages in ui/components/desktop/pages.ts covered.

- risk: The Breeze per-connection instrument limit is only verified at 51. EQS (1,500 names) and the market map (~500) cannot all ride the websocket, so they need the NSE heatmap plus CLOSE labels. Measure the limit before raising the cap past about 100.
- risk: The websocket dies with the ICICI session (the 08:00 login needed a human on 4 of 4 recent runs). Every live pane must degrade to 'NSE DELAYED <age>' from the heatmap or allIndices, never silently to Yahoo.
- risk: Arming LIVE_TICKS needs a data-service restart, which is the owner's call: outside 07:45-09:20 and 18:30-21:15, with ui-api stopped first, or data-service comes back READ-ONLY.
- risk: Do not shorten NSE TTLs to 'go live'. The 26-list heatmap fan-out every 60 s is already the heaviest NSE load, and an Akamai block would break the whole terminal. Prices should go live through the websocket; NSE aggregates keep their cadence.
- risk: Tick volume is about 57 ticks/s for 51 instruments, roughly 1.3 M per session. Persistence and fan-out must stay off the ui-api event loop (the past loop-stall incident). Push over the monitor WS rather than having every window poll /api/quotes/ticks every 2 s.
- risk: allIndices stamps only the minute and runs 1-3 min behind, so NSE index panes must never read LIVE. After 15:30 every live price must read CLOSE <session date>.
- risk: Yahoo panes were not measured (no-Yahoo rule). Their lag in the report comes from the code bound (<= 60 s served, up to ~120 s on the hover card) plus Yahoo's own exchange delay, which is unknown.
- risk: Wave 1 deploys tonight 21:37. The new panes (IV store, drivers, data health, budget ledger) were inventoried from source and their live behaviour is unverified until then.
