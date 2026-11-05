# G-APP — Gold in the SuryaDhana terminal: audit, consolidation and the GOLD page architecture

Written Monday 26 Oct 2026, 05:40–06:40 IST, read-only against the live stack (ui-api :8010, data-service :8001; GET only, no
broker-touching route called). Every number below was either read from the code or fetched during this hour; fetch results
are in §15. Sibling agents (G-COT, G-CME, G-PHYSICAL, G-MACRO, G-INDIA, G-KITCO, G-LOGIN, G-STUDY, G-EDU) verify the
external datasets; this report audits what the app does with gold today and specifies where the new data goes.

**Verdict in one paragraph.** Gold is on six surfaces today (BRF panel, CMDT board + Gold Pre-Open desk + accuracy log,
MCXG desk, WEI row, the macro tape, and the 08:45 Telegram alert) fed by three routers and four separate Yahoo fetchers.
The fair-open model is the only piece of real analysis and it is printed in five places; COMEX, USD/INR, DXY and the
settlement are printed in three to five places each; no gold series is stored, so there is no daily / weekly / monthly
view of anything, no gold chart in rupees, no positioning (COT), no flows, no physical premium, no curve. The accuracy log
that was meant to size the ₹300 chase limit has two completed rows after two weeks, with misses of ₹2,880 and ₹3,518,
and one row with no open because the jobs do not know MCX's holiday calendar. Recommendation: one new page **GOLD**
(id `gold`, GO alias `XAU`), the pre-open desk and context move there, MCXG stays the trading desk, CMDT becomes
commodities-only with a card link, WEI gets a two-line gold cue card, BRF one line; data-service gets seven DuckDB tables
with point-in-time columns and a light IST ingest schedule; ui-api gets `routers/gold.py` behind `/api/gold/*` with the
existing SWR cache; the 42-page gates become 43-page gates in six named files.

---

## 1. What the owner asked, mapped to what exists

| Owner's words | Exists today | Gap |
|---|---|---|
| "CFTC Commitments: Comex Gold Futures/Options" | nothing | G-COT verifies the source; storage + page section specified here (§8.3, §10) |
| "health check for gold" | the pre-open verdict (OK / WAIT) is the only verdict; the context table marks each driver SUPPORTIVE / HEADWIND | a scored, dated, sourced health card (§7.2); context-only until G-STUDY passes it |
| "include like kitco.com/charts/gold" | a link in the Manual checks list | own charts from stored daily series (§7.4); Kitco stays a link (robots allow, no embed product found, §15) |
| "over the counter deals" | nothing | G-PHYSICAL (LBMA trade data); table `gold_series` rows (§8.2) |
| "COT and so forth … supply demand" | nothing | `gold_cot`, `gold_etf_holdings`, `gold_series` (imports, reserves, SGE) |
| "weeks, days and month" | everything is live-only; no history | DuckDB tables with `report_date` + `release_at`; D/W/M resampling in `/api/gold/series` |
| "create a visual separately" | gold is a panel inside CMDT and a panel inside BRF | the GOLD page (§7) |
| "remove repeated information" | see §4: fair value ×5, COMEX ×5, USD/INR ×4, settlement ×3, headlines ×2–3, DXY ×2 | the consolidation table (§7.3) |
| "keep it in the world market tabs as well" | WEI has a GC=F row (price, change, spark, day range) | the row becomes a 2-line cue card with the health line and a link; no second price print |
| "autologin icici" | job `icici_session_refresh` 08:00 Mon–Fri exists; the SMS-OTP leg needs the owner's Telegram reply; TOTP unattended path pending the owner enabling TOTP (memory `icici_auto_login.md`, 28 Sep) | G-LOGIN; the gold desk already picks the session up (`routers/positions._get_breeze_client`, retried after a minute) |
| "which position got closed, who are short / long, daily and weekly" | nothing | weekly: COT by trader category with week-on-week change (§10 `/api/gold/cot`); daily: MCX open interest per contract from the ICICI master today, official bhavcopy when G-INDIA solves MCX access (403 from scripts, §15); COMEX daily OI via G-CME |
| "choose the contract different" | MCXG has a contract (GOLD/GOLDM/GOLDPETAL/GOLDGUINEA) and expiry selector; the pre-open desk picks the front GOLD contract by open interest | one shared contract picker (prefs-synced) driving both pages and the COMEX month (§7.1) |
| "basic to complex" | explanations are footnotes under each panel | every number gets an "about" popover from the catalog table (publisher, cadence, lag, formula, pitfalls, verdict) and the glossary (§13) |
| "analyse first: will it be useful? if yes then only publish" | — | verdict column on every source/metric (§12) |

---

## 2. Inventory: where every gold number, chart and control appears today

Read from `ui/app/page.tsx` (42 pages), the six components and three routers. "Cadence" is the browser poll interval.

| Surface (page · panel) | Component | Endpoint(s) | Cadence | What it shows | Controls |
|---|---|---|---|---|---|
| **BRF · "Gold open (MCX)"** panel (leads the grid before 09:15 IST weekdays; after that it is the last panel) | `Brief.tsx` lines 220–263, 484, 646 | `GET /api/commodity/gold-preopen` (no params) + `GET /api/commodity/gold-preopen/log?threshold=300` | once per BRF load + REFRESH ALL | before 09:00: verdict title/detail, fair open, baseline + source, expected gap (₹ and %), chase limit, event-risk advice, the "baseline is older" note; after 09:00 with a captured open: THIS MORNING'S CALL (fair vs actual, model vs naive miss, MCX now vs open, track record) | `CMDT ›` chip |
| **BRF · Market panel · "Global cues"** | `Brief.tsx` line 93 `GLOBAL` | `/api/news-scanner/quotes?symbols=^GSPC,^N225,BZ=F,INR=X` | per load | S&P, NKY, Brent, ₹/$ — **no gold** | WEI › |
| **Header · macro tape row 2** (every page) | `MarketCommandHeader.tsx` line 179 | `/api/news-scanner/quotes` (GC=F among 7) | 60 s | "GOLD" = Yahoo GC=F (front COMEX future, Dec-26 now), price + change | — |
| **WEI · Commodities panel** | `WorldMarkets.tsx` line 25 | `/api/news-scanner/quotes` (GC=F, SI=F among 36 symbols, 60-symbol batches) | 60 s | price, change, change %, 22-bar spark, position in day range, minutes since last print | — |
| **CMDT · Gold Pre-Open Desk** (top of the page) | `GoldPreOpen.tsx` (298 lines) | `GET /api/commodity/gold-preopen?baseline&mcx_price&threshold&eurusd_trigger` | 60 s + 400 ms debounce on typing | verdict strip; 5 stats (baseline, fair, gap, MCX vs fair, chase limit); gap build-up table + SVG waterfall; rule-of-thumb line (₹ per $1 COMEX, ₹ per ₹1 USD/INR, implied premium, today's band); inputs panel; context table (DXY, EUR/USD, US10Y, silver, 10y TIPS); headlines (6 topics, 18 max); manual checks (10 links, ticks persisted); accuracy log; method note | baseline override, MCX price, chase limit, EUR/USD trigger (localStorage `goldPreOpen.v1`, prefs-synced), checklist ticks, REFRESH |
| **CMDT · Accuracy log** (inside the desk) | `GoldAccuracyLog.tsx` | `GET …/gold-preopen/log?days=60&threshold=` · `POST …/gold-preopen/actual` | on load / refresh | days measured, median/mean/p90 miss, % within ₹300, bias, model vs naive; row table | type an open + SAVE |
| **CMDT · futures board** | `CommodityTab.tsx` | `GET /api/commodity/overview` (6 Yahoo symbols, 1mo/1d) | 60 s | Gold card: GC=F price, change %, 40-bar spark | click → 6-month detail chart `GET /api/commodity/price/GC=F?range=6mo&interval=1d`, "open on TradingView GC1!" via `ChartActions` |
| **CMDT · FRED / EIA legs** | `CommodityTab.tsx` | same overview | 60 s | both show "key required": `FRED_API_KEY` and `EIA_API_KEY` are **not set** in `.env` (checked by name, count 0) | — |
| **MCXG · Session** | `McxGoldDesk.tsx` | `GET /api/mcx/session` | 30 s + 1 s local tick | OPEN/CLOSED, segment, countdown, evening close rule, MCX 2026 holidays, Muhurat | — |
| **MCXG · Quote** | same | `GET /api/mcx/quote?contract&expiry` | 30 s | Breeze LTP/open/high/low/prev close when live; else honest degrade with band settlement (+OI lots) and fair value, "desk price in use" | contract + expiry selects |
| **MCXG · COMEX × rupee overlay** | same | `GET /api/mcx/overlay?contract&expiry&mcx_price` | 60 s | COMEX GCZ26, USD/INR, landed (no duty), fair (model), implied premium %, premium vs fair when a live LTP exists | — |
| **MCXG · Contract specs** | same | `GET /api/mcx/specs` | 5 min | 4 contracts: lot, quotation, tick value, delivery/purity, indicative margin, cycle, computed vs observed expiries, front settlement + band + OI | click row → select |
| **MCXG · Paper ticket** | same | `POST /api/mcx/ticket` | debounced | notional, margin, tick value, round-trip cost legs, breakeven ticks | lots, price, brokerage |
| **Telegram / inbox** | `scripts/master_controller.py` `gold_preopen_snapshot` | `POST …/gold-preopen/snapshot` 08:45 Mon–Fri | daily | "GOLD DEC-26: fair open ₹X (+Y vs settlement ₹Z). Don't chase more than ₹300 above it." | — |
| **Files, not surfaced** | `gold_premarket/YYYYMMDD.json` (9 briefs, 9–23 Oct; schema `gold_premarket.schema.json`, 14 top-level keys) | written by a scheduled external task (`gold_premarket/scheduled_task_prompt.txt`) | daily ~08:40–09:00 | overnight brief: baseline, markets, gap model, Fed, triggers, 12–25 news items with impact, flows, circulars, technicals, calendar, synthesis, data quality | **ingested nowhere** (grep across services/ui/scripts/shared: no reference) |
| **Research library (RSCH)** | `routers/research.py` | `GET /api/research` | — | 84 studies listed; **none** about gold; `_discover` globs `reports/*/*.md` (one level), so `reports/gold_program/G-*/REPORT.md` will not appear unless cataloged | — |

Also present but not gold-specific: `ChartActions.futuresInstrument('GC=F')` maps to TradingView `GC1!` (external link only;
`NewsChart.TradingViewEmbed` is a sandboxed iframe of TradingView's widget — memory notes it as a US-only embed path).
CHRT (chart studio) serves DuckDB EOD + broker ticks for NSE symbols; it has no futures/commodity instrument.

---

## 3. Fetch map: what each gold endpoint reads upstream, how it is cached, how long it took today

| Endpoint | Upstream calls per uncached hit | Cache (module) | Measured now |
|---|---|---|---|
| `GET /api/commodity/gold-preopen` | ICICI `SecurityMaster.zip` (3 MB, `MCXScripMaster.txt`, stale-while-revalidate 300/600 s, single flight); **Breeze** `get_quotes` (remembered broken 10 min) then after 09:00 `get_historical_data_v2` 1-min bars (10–15 s, cached 60 s); Yahoo 5-min bars ×6 (`GCZ26.CMX`, `INR=X`, `DX-Y.NYB`, `EURUSD=X`, `^TNX`, `SI=F`; SWR 30/120 s, single flight, own client); FRED `fredgraph.csv` DFII10 (SWR 3 h/6 h); Treasury real-curve CSV (background thread, 6 h); Google News RSS ×6 topics (SWR 150/300 s) | `TTLCache("gold_preopen", 32)`: today 21 entries, 74 hits / 25 misses | not called (touches Breeze); memory + log say ≈1–2 s warm, 15–18 s when the 1-min-bar cache has expired |
| `POST …/snapshot` (08:45) / `POST …/capture-open` (09:10) / `POST …/actual` / `GET …/log` | the above with fresh-only Yahoo; Breeze; file `data/gold_preopen/log.json` (atomic replace, lock) | — | `/log?days=10` 0.01 s, 4 rows |
| `GET /api/mcx/session` | none (pure `shared/mcx_specs`) | — | 0.01 s |
| `GET /api/mcx/specs` | ICICI master (shared loader) | `TTLCache("mcx", 64)` `gold_family` 600 s | **6.89 s cold** at 05:42 (zip re-downloaded because ICICI's copy is not today's: Last-Modified Fri 23 Oct 01:58 GMT) |
| `GET /api/mcx/quote` | master; Breeze (degrade memory per contract 10 min); Yahoo ×2 via `gp._yahoo_bars` **uncached** (not the SWR path), result cached 60 s per contract | `quote:{code}:{expiry}` 15 s | not called (Breeze) |
| `GET /api/mcx/overlay` | master; Yahoo ×2 (same uncached path, `fair:` 60 s) | 60 s | 0.36 s |
| `GET /api/commodity/overview` | Yahoo 1mo/1d ×6 (`commodity._yahoo_chart`, own client, query1→query2); FRED/EIA skipped (no keys) | `TTLCache("commodity", 64)` 60 s | 0.31 s |
| `GET /api/news-scanner/quotes` (tape, WEI, BRF) | Yahoo 1mo/1d per symbol (`news_scanner._yahoo_chart`, semaphore 6) | `SWRCache("news_scanner.quotes", 600)` 30/60 s: 72 hits, 620 stale hits, 454 misses, 617 refreshes since start | 0.99 s for 7 symbols |

Four independent Yahoo chart fetchers live in ui-api (`gold_preopen._yahoo_bars` + its SWR wrapper, `mcx` calling the raw
one, `commodity._yahoo_chart`, `news_scanner._yahoo_chart`). The GOLD page must not add a fifth (§9.3).

External feed check (details §15): Yahoo answers **429 to a browser-like or `python-httpx` User-Agent and 200 to the app's
plain `Mozilla/5.0 (SuryaDhana-GoldDesk)`** — keep the UA exactly as it is, and store daily closes so the page is not
hostage to it. FRED CSV without a key: 0.75 s, last row 2026-10-22 = 2.64. Treasury real curve: 1.53 s (memory said ~20 s),
last row 10/23/2026 10 YR = 2.66, one day fresher than FRED as documented. Google News RSS: 0.8 s, 100 items. ICICI master:
HEAD 200, 2,998,716 bytes, `Last-Modified` present (usable for a conditional GET; today's loader ignores it).

---

## 4. Repetition map (the owner's defect)

Counting the places a trader sees the same number, before any change:

| Number | Printed in | Count |
|---|---|---|
| Model fair open / fair value (₹) | CMDT desk (stat + table + waterfall), MCXG quote fallback, MCXG overlay, BRF panel, 08:45 Telegram | 5 |
| COMEX gold price | macro tape (GC=F), WEI (GC=F), CMDT board (GC=F), CMDT desk (GCZ26 now/at close), MCXG overlay (GCZ26) | 5 (two different instruments: continuous front vs the matched month — never labelled as such) |
| USD/INR | macro tape, WEI, CMDT desk gap table, MCXG overlay | 4 |
| MCX settlement / price band | CMDT desk (baseline + band line), MCXG quote fallback (band), MCXG specs front row | 3 |
| Implied premium over landed | CMDT desk rule-of-thumb line, MCXG overlay | 2 |
| DXY, US 10y yield | WEI rows, CMDT desk context table (with "for gold" signal) | 2 |
| Headlines (same fetcher, overlapping topics) | CMDT desk (gold/Fed/Iran/China/rupee/France), BRF headlines (market topics), News terminal | 2–3 |
| Accuracy stats | CMDT accuracy log, BRF after 09:00 | 2 |
| Contract name / expiry / OI lots | CMDT desk subtitle + band line, MCXG quote subtitle + fallback, MCXG specs | 3 |

A tape and a board legitimately repeat a *quote*; the defect is the model, the inputs and the explanations repeated on
three pages with three different vocabularies ("fair open", "fair value (COMEX×INR model)", "fair (model)").

---

## 5. Stale or weak (each with evidence)

1. **Monday-morning baseline is two sessions old and labelled by file date, not session.** At 05:42 Mon 26 Oct the ICICI
   master is Friday's file (published 01:58 GMT Fri 23 Oct) carrying the **22 Oct** settlement (₹146,079; band
   141,697–150,461; OI 16,650 lots). `gold_preopen` says "MCX settlement 22 Oct" (good); `mcx.py` labels the same number
   "ICICI price-band midpoint (2026-10-23 master)" — a trader reads 23 Oct. Friday's own settlement arrives only with
   Monday's ~07:30 file. Fix: always print the **session** the settlement belongs to; store it (§8).
2. **The chase limit has no evidence yet, and the two completed rows contradict it.** `data/gold_preopen/log.json` has 4
   rows since 15 Oct: 15 Oct fair 151,000 vs open 147,482 (miss −3,518; naive −968, i.e. the model was *worse* than
   "open = settlement"); 23 Oct fair 144,938 vs open 142,058 (miss −2,880; naive −4,021, better). 20 Oct has no open.
   Mean miss ≈ ₹3,200 against a ₹300 limit. On 15 Oct COMEX rose 1.7% between the MCX close and 08:45 yet MCX opened
   −0.65% below settlement: an input is wrong on that day (settlement source, the 23:30 reference window, or the first
   1-minute bar used as "open"). The rupee leg shows `inr_now == inr_ref` to 3–4 decimals on 2 of 3 days (95.14/95.14,
   94.808/94.808): Yahoo `INR=X` had no fresh overnight bar, so the rupee contributed nothing. The snapshot must store its
   full inputs (bars used, master publish date, Breeze bars) so misses can be audited; the 08:45 alert's "don't chase more
   than ₹300" wording should carry the measured error until ≥20 rows exist.
3. **The gold jobs and the desk verdict ignore MCX's own holiday calendar.** 20 Oct (Dussehra) is a *morning* closure in
   `shared/mcx_specs.MCX_HOLIDAYS_2026` (open 17:00 →). `gold_preopen_snapshot` ran at 08:45 and `gold_open_capture` at
   09:10 found no bars, so the row has no open and the stats skip it; `verdict()` treats every weekday ≥ 09:00 as "opened".
   Fix: gate both jobs and `verdict()` on `mcx_specs.trading_window(day)`; capture at open+10 min of the real window.
4. **Every CMDT/BRF refresh after 09:00 can hold the threadpool on a 10–15 s Breeze historical call.** The 1-minute-bar
   fetch is cached 60 s while the desk polls every 60 s (`REFRESH_MS = 60_000`), so roughly every poll pays it; BRF's
   `getGoldPreOpen` has a 30 s client timeout. Also a Breeze REST quota cost that `quotes.py` deliberately avoids for
   equities (F3.4 "zero ICICI REST quote calls"). Fix: serve the live MCX price from the tick store / a 1-min-bar SWR with
   a 5-min max age refreshed in the background; one fetch per minute at most, never on the request path.
5. **The 3 MB security master is re-downloaded all weekend.** `_load_mcx_master` re-fetches whenever the cached copy's
   publish date is not today, so from Friday 07:30 until Monday 07:30 every 5–10 min refresh (desk, specs, warm) downloads
   the zip again (6.9 s cold hit measured). The server sends `Last-Modified`; a conditional GET (`If-Modified-Since`) makes
   those refreshes free. Keep the publish-date logic for the "which session" label.
6. **Two Yahoo paths for the same two series.** `mcx._fair_value` calls `gp._yahoo_bars` directly (no SWR, no single
   flight) while `gold_preopen` uses `_yahoo_bars_cached`; with MCXG and CMDT open side by side that is four Yahoo requests
   per minute for GCZ26 + INR=X. Fix: `mcx` should call `gp._yahoo_bars_cached`.
7. **"GOLD" on the tape and WEI is the Dec-26 COMEX future, not spot**, and the desk uses the matched month (GCZ26 today,
   GCG27 after the roll). Three instruments share one word. The page must name them: *spot (XAU/USD)*, *COMEX front (GC1)*,
   *COMEX matched month (GCZ26)*, *MCX GOLD Dec-26*.
8. **Personal, dated inputs are baked into the router**: `eurusd_trigger=1.1161` default and a "France / OAT" headline
   topic — artefacts of one week's narrative. Move triggers to prefs (owner-set), drop the topic or make topics a prefs list.
9. **`event_risk` is a keyword count** (attack, strike, missile, war, …) over ≤18 headlines, shown as "consider half size"
   at ≥3 hits. No evidence; it flagged 3 on 23 Oct. Verdict DO-NOT-PUBLISH as advice; keep the count as a label.
10. **Manual checks are the data the program is now fetching**: SGE premium, ETF flows, GLD tonnes, live real yields, Fed odds.
    After ingestion the list shrinks to the true link-only items (FedWatch 403 to scripts, Kitco, MCX circulars 403).
11. **The daily brief JSON is orphaned**: nine files written by the external task are never read by the app; the ingest and a
    "today's brief" block are specified in §8.5 / §10.
12. **FRED/EIA legs on CMDT have shown "key required" since they were built**: no `FRED_API_KEY`/`EIA_API_KEY` in `.env`. The
    gold desk already reads FRED keyless (`fredgraph.csv`, 0.75 s). The GOLD page should use the keyless CSV for every FRED
    series it needs (DFII10, DGS10, DTWEXBGS) and the CMDT leg should say so instead of asking for a key.
13. **Breeze MCX quotes for the minis were never verified** (`mcx.py` `BREEZE_CODE` comment: "LIVE-VERIFY after the 08:00
    login"); the quote panel shows "LIVE-VERIFY PENDING". Still true on 26 Oct per the code.
14. **BRF rotates the gold panel on the NSE clock (09:15)** while MCX opens 09:00; the "this morning's call" branch needs the
    captured open, which arrives 09:10 — so between 09:00 and 09:15 the panel shows a pre-open verdict as if still live.

---

## 6. What a Bloomberg gold trader would miss (and the terminal function it maps to)

Bloomberg function names are given where I am confident; otherwise "desk practice".

| Need | Bloomberg habit | Terminal today | Where it lands |
|---|---|---|---|
| Spot vs futures distinction, 24-hour spot chart | `XAU Curncy GP` / `GIP` | GC=F front only, 6-month daily line on CMDT | GOLD §7.4 (own charts from stored bars; Kitco link) |
| MCX gold chart in rupees, daily/weekly/monthly | `GP` on the MCX contract | none (CHRT is NSE-only) | GOLD charts from `gold_curve` (history starts the day ingestion starts; shown honestly) |
| Futures curve, calendar spreads, roll yield | `CCRV` | front settlement only | GOLD curve panel from `gold_curve` (COMEX months via G-CME, MCX months from the master today) |
| Positioning: COT by trader category, w/w change, percentiles | COT screens (desk practice: managed-money net vs price) | none | GOLD positioning (`gold_cot`, G-COT) |
| Daily open interest and volume by contract | exchange daily bulletins | OI lots per MCX contract from the ICICI master (no history) | `gold_curve.open_interest` daily; COMEX via G-CME |
| ETF holdings and flows | `GLD US Equity HDS`, WGC data | link to WGC / SPDR | `gold_etf_holdings` (G-PHYSICAL / G-MACRO) |
| Real yields and the dollar as drivers, with history | `DFII10 Index GP`, `DXY Curncy` | one-day change on CMDT desk; WEI quote | GOLD health card + 1-year overlay chart |
| Physical premiums: Shanghai, India dealer premium/discount, IBJA | desk practice (Reuters Asia gold weekly) | link | `gold_series` (G-PHYSICAL, G-INDIA) |
| Central-bank buying, India imports, RBI reserves | WGC / IMF IFS, DGCI&S, RBI WSS | none | `gold_series` monthly / weekly (G-MACRO, G-INDIA) |
| Event calendar with gold relevance: FOMC, CPI, NFP, RBI, COMEX first-notice/last-trade, MCX expiries, COT release | `ECO`, contract calendar | FOMC/RBI dates on WEI/ECO; MCX expiries on MCXG | `gold_events` (§8.6) and a calendar strip on GOLD |
| Implied volatility (GVZ) and MCX gold options | `GVZ Index`, `OMON` on GC | none (worldclass GAPS: "Gold options MISS-B later") | out of scope here; GVZ is a candidate `gold_series` row if G-CME verifies a free feed |
| One-line "state of gold" before the open | desk practice (morning sheet) | the ₹300 verdict | GOLD health line, reused on WEI and BRF |

---

## 7. The consolidation

### 7.1 The new page

- **id** `gold` · **code** `GOLD` · **label** "Gold intelligence" · **hint** "spot, COMEX, MCX, positioning (COT), flows,
  real yields, health check, pre-open fair value". Group `DerivativesGold` in `desktop/src-tauri/src/pages.rs` (next to
  CMDT and MCXG). GO aliases `XAU` and `GC` → `{ kind: 'page', id: 'gold' }` in `ui/lib/goAliases.ts`. Why `GOLD` and not
  `XAU` as the code: the GO bar ranks an exact code match first (`CommandBar.tsx` score 4), and the owner types "gold";
  today that word only surfaces MCXG through its hint. `XAU` stays the Bloomberg-style alias.
- **Contract picker** (shared with MCXG through `ui/lib/prefs`, key `gold.contract.v1`): MCX contract + expiry (front by
  OI default) ↔ matched COMEX month (`gp.comex_symbol`) ↔ continuous front (GC=F) ↔ spot proxy. Every price on the page
  says which of the four it is.
- **Sections, top to bottom** (each loads on its own, like BRF): (1) health card; (2) today's open: the pre-open model
  (verdict, 5 stats, gap waterfall, inputs) before 09:00 → live fair value & premium after; compact accuracy strip with a
  link to the full log; (3) charts with D/W/M toggle: USD gold (spot/COMEX), MCX GOLD ₹, USD/INR, 10y real yield overlay;
  (4) positioning: COT table (weekly) + daily OI/volume by contract; (5) flows & physical: ETF tonnes, WGC flows, SGE and
  India premiums, imports, RBI reserves; (6) curve & basis: COMEX and MCX settlement curves, MCX premium over landed
  history; (7) calendar strip; (8) headlines (gold topics only); (9) "about this data" rail from `/api/gold/catalog`
  (publisher, cadence, lag, verdict, terms) + the reduced link-only list; (10) today's brief (when `gold_brief_docs` has
  the day).

### 7.2 The health check (one line, seven chips; context only until a study passes)

`health = { score: supportive − headwind, of: 7, line: "4 of 7 drivers supportive · real yields ↓, dollar ↓, ETF inflow; COT crowded long" }`.
Drivers and the direction that is *supportive* for gold, each with value, change over the chosen window (D/W/M), freshness
and an evidence tag:

| Driver | Source table / series | Supportive when | Evidence tag |
|---|---|---|---|
| 10y real yield (TIPS) | `gold_series` FRED DFII10 / Treasury real curve | falling | context (the best-documented driver; the sign is well established, timing is not — the WGC return-attribution framework and Erb & Harvey 2013 are the references G-MACRO should cite; G-STUDY tests predictiveness) |
| Dollar index (DXY) | `gold_daily_bars` DX-Y.NYB | falling | context |
| COMEX managed-money net position + 1-year percentile | `gold_cot` | **crowded long = headwind**, washed-out = supportive (contrarian at extremes) | context until G-STUDY |
| ETF holdings, 5-day change | `gold_etf_holdings` | inflow | context (contemporaneous with price per WGC; weak lead) |
| Shanghai premium (SGE vs London/COMEX) | `gold_series` | positive and rising | context |
| MCX premium over landed (local demand / duty / rupee) | computed from `gold_curve` + USD/INR | rising | context |
| COMEX term structure (front − second, annualised) | `gold_curve` | contango narrowing / backwardation | context |

Rules: a chip with data older than its catalog `max_age_days` shows STALE and does not count; the line always ends with
"context only" until `reports/gold_program/FINDINGS.md` records a PASS for a driver, after which that chip carries the
verdict chip (`ResearchNote` component). The verdict strip of the pre-open model stays separate: that one *is* actionable
(it is a price-vs-fair comparison, not a forecast).

### 7.3 What moves, what stays

| Surface | After |
|---|---|
| **GOLD** (new) | everything in §7.1; owns the fair-open model UI, the context table (now the health chips), headlines, manual checks (reduced), accuracy log, method notes |
| **MCXG** (trading desk) | keeps session clock, holidays, quote with contract/expiry selector, specs, paper ticket; the overlay panel shrinks to one line *rendered from `/api/gold/health`'s `fair` block* (COMEX, USD/INR, fair, premium vs live) with "GOLD ›"; no model explanation, no implied-premium prose |
| **CMDT** | drops `<GoldPreOpen />` (CommodityTab.tsx line 259) and "· Gold desk" from label/hint/subtitle; the Gold board card gains a "GOLD ›" chip; FRED leg switches to the keyless CSV or states that keys are optional |
| **WEI** | the GC=F row becomes a two-line cue card: line 1 unchanged (price, change, spark, range, age), line 2 = `health.line` + "GOLD ›"; no second price |
| **BRF** | the gold panel is replaced by one `Line` in the Market panel: before 09:00 "Gold open: fair ₹X (gap +Y) · OK/WAIT · health 4/7 · GOLD ›"; after the captured open "Gold opened ₹X, fair ₹Y (miss ₹Z) · health 4/7 · GOLD ›"; `getGoldPreOpen` is no longer called from BRF (it calls `/api/gold/health`, 60 s cache, no Breeze on the path) |
| **Macro tape** | unchanged (a tape repeats quotes by design); label becomes "GOLD GC1" to name the instrument |
| **08:45 alert** | unchanged text + measured error ("model miss so far: median ₹N over M days") |
| `GoldPreOpen.tsx`, `GoldAccuracyLog.tsx` | move under `ui/components/gold/` and are composed by `GoldPage.tsx`; the localStorage key `goldPreOpen.v1` is kept so synced inputs survive |

### 7.4 Charts and "like Kitco"

Kitco's chart is their own JavaScript widget on their own feed; the page is public (200, robots `Allow: /`), but no embed
or data product for the chart was found on the page or in the terms, so it stays **LINK-ONLY** (G-KITCO owns the final
word). The GOLD page draws its own charts with the terminal kit (`Spark`, `chart.ts`, the SVG conventions checked by
`pages.check.ts`) from `gold_daily_bars` (USD legs, from the day ingestion starts plus a one-time Yahoo backfill of daily
history — Yahoo daily bars are the project's existing history provider) and `gold_curve` (MCX ₹; honest "since
<first ingest date>" until G-INDIA finds official history). Every chart has D/W/M resampling server-side.

### 7.5 Adding the 43rd page: the exact touch points

`ui/app/page.tsx` (the `Tab` union, `TAB_IDS`, `COMMAND_PAGES`, a `lazyTab('gold', …)`, the render `case`, optionally the
tab strip `tabList`); `ui/components/shell/tabModules.ts` (loader map); `ui/components/desktop/pages.ts` (code + label for
the title strip, header comment "42"); `desktop/src-tauri/src/pages.rs` (`PAGES`, `PAGE_COUNT` 42 → 43, three tests assert
42, group coverage test); `ui/lib/goAliases.ts` (XAU, GC); `scripts/ui_audit.py` default `TABS` (+ `gold`, so the
RUNBOOK's "15/15 ok" becomes 16/16); `docs/RUNBOOK_RESTORE.md` and `CLAUDE.md` ("42 pages"); `reports/desktop_app/
FEATURE_PARITY.md`. `scripts/desktop_qa/pages.py` parses `page.tsx` and `pages.rs` and will raise if they disagree, which is
the safety net; `scripts/ui_perf.py` cross-checks `TAB_IDS` vs `COMMAND_PAGES` and applies the 400 ms tab-switch p95 and
300 KB first-load budgets automatically (keep the page lazy like every other tab); `scripts/desktop_qa/probe.py` expects
the `PageHeader` amber code chip to equal the function code (`GOLD`); `scripts/desktop_qa/parity.py` compares A/B per tab —
the new page has no A side, so it is declared under the harness's expected-program-deltas list rather than failing.

---

## 8. Storage design (data-service, DuckDB `data/market.duckdb`)

Conventions copied from the NSE tables in `services/data-service/storage/duckdb_store.py`: `CREATE TABLE IF NOT EXISTS`
in the schema block, `INSERT OR REPLACE` through `_upsert(table, df, cols, casts)`, `store.checkpoint()` at the end of a
job, a row in `get_positions_meta()` for freshness, and a `last_date` allowlist entry. Point-in-time (PIT) rule from
`docs/PROGRAMMATIC_DATA_ACCESS.md` §3: every observation carries the period it describes (`report_date`) and the moment it
became public (`release_at`, UTC); revisions are new rows, never updates; a reader asks "as of" a timestamp. Every table
also carries `first_seen_at` (our fetch time) so a backfilled row can never masquerade as one we had at the time.

### 8.1 `gold_series_catalog` — the data dictionary as a table (drives the page's "about" popovers and `/api/gold/catalog`)

```sql
CREATE TABLE IF NOT EXISTS gold_series_catalog (
    series_id        VARCHAR PRIMARY KEY,   -- e.g. FRED_DFII10, UST_REAL_10Y, LBMA_PM_USD, SGE_AU9999_CLOSE, IBJA_999_PM,
                                            --      GLD_TONNES, WGC_ETF_FLOW_T, RBI_GOLD_RESERVES_USD_MN, DGCIS_GOLD_IMPORT_USD_MN,
                                            --      USDINR_FBIL, COMEX_GC_FRONT_SETTLE, MCX_GOLD_FRONT_SETTLE, LBMA_OTC_VOL_OZ …
    name             VARCHAR NOT NULL,
    publisher        VARCHAR NOT NULL,
    url              VARCHAR NOT NULL,      -- the verified fetch URL (never invented: the G-* reports supply it)
    freq             VARCHAR NOT NULL,      -- 'D' | 'W' | 'M'
    unit             VARCHAR NOT NULL,
    publish_time_ist VARCHAR,               -- e.g. '01:45 next day (FRED, prior US session)'
    lag_note         VARCHAR,
    access           VARCHAR NOT NULL,      -- FREE | FREE-KEY | FREE-REGISTRATION | PAID | BLOCKED | UNVERIFIED
    terms            VARCHAR,               -- licence / embed / redistribution note
    verdict          VARCHAR NOT NULL,      -- PUBLISH-CORE | PUBLISH-CONTEXT | LINK-ONLY | DO-NOT-PUBLISH
    verdict_reason   VARCHAR,
    beginner_note    VARCHAR,               -- plain-English one-liner
    pro_note         VARCHAR,               -- definition, formula, pitfalls
    how_pros_use_it  VARCHAR,
    evidence         VARCHAR,               -- study citation or 'context only'
    ingest_job       VARCHAR,               -- master-controller job id that fills it
    max_age_days     INTEGER NOT NULL,      -- freshness threshold (feeds DATASET_MAX_AGE_DAYS and the WHSE panel)
    verified_at      TIMESTAMP, verified_by VARCHAR   -- G-COT / G-CME / … and the date of the live check
);
```

### 8.2 `gold_series` — every single-value daily / weekly / monthly series, point-in-time

```sql
CREATE TABLE IF NOT EXISTS gold_series (
    series_id      VARCHAR   NOT NULL,
    report_date    DATE      NOT NULL,   -- the period the value describes: the day; the week-ending date; the month-end
    freq           VARCHAR   NOT NULL,   -- 'D' | 'W' | 'M' (denormalised for cheap resampling)
    value          DOUBLE    NOT NULL,
    release_at     TIMESTAMP NOT NULL,   -- publisher's publication moment, UTC (the PIT key); when the publisher gives only a
                                         -- date, the catalog's publish_time_ist is applied and release_source = 'rule'
    release_source VARCHAR   NOT NULL,   -- 'publisher' | 'rule' | 'fetch' (fetch = we only know when we saw it)
    first_seen_at  TIMESTAMP NOT NULL,   -- our fetch time, UTC
    source         VARCHAR   NOT NULL,   -- publisher endpoint tag, e.g. 'fred:fredgraph.csv', 'treasury:real_yield_csv'
    quality        VARCHAR   NOT NULL,   -- 'official' | 'derived' | 'proxy'
    revision       INTEGER   NOT NULL DEFAULT 0,
    PRIMARY KEY (series_id, report_date, release_at)
);
-- Latest value per period, as of a moment (the only read pattern the page needs):
-- SELECT * FROM gold_series WHERE series_id = ? AND release_at <= ?asof
-- QUALIFY ROW_NUMBER() OVER (PARTITION BY report_date ORDER BY release_at DESC) = 1 ORDER BY report_date;
```

Dedupe: the primary key. A re-fetch of an unchanged value is a no-op (`INSERT OR REPLACE` on the same key with the same
`release_at`); a revised value has a later `release_at` and becomes a new row with `revision + 1`. Volume: ~30 series ×
260 days ≈ 8k rows/year — negligible.

### 8.3 `gold_cot` — CFTC Commitments of Traders, COMEX gold (G-COT fills the column map)

```sql
CREATE TABLE IF NOT EXISTS gold_cot (
    report_date       DATE      NOT NULL,   -- positions as of Tuesday
    release_at        TIMESTAMP NOT NULL,   -- Friday 15:30 ET (shifted after US holidays), UTC
    market_code       VARCHAR   NOT NULL,   -- CFTC contract-market code for COMEX gold (G-COT verifies the code)
    report            VARCHAR   NOT NULL,   -- 'disagg_fo' | 'disagg_f' | 'legacy_fo' | 'legacy_f'
    category          VARCHAR   NOT NULL,   -- producer_merchant | swap_dealer | managed_money | other_reportable |
                                            -- nonreportable | commercial | noncommercial | total
    long_pos BIGINT, short_pos BIGINT, spread_pos BIGINT,
    chg_long BIGINT, chg_short BIGINT, chg_spread BIGINT,          -- week-on-week, as published
    pct_oi_long DOUBLE, pct_oi_short DOUBLE,
    traders_long INTEGER, traders_short INTEGER,
    open_interest BIGINT, chg_open_interest BIGINT,
    first_seen_at     TIMESTAMP NOT NULL,
    source            VARCHAR   NOT NULL,
    PRIMARY KEY (report_date, release_at, market_code, report, category)
);
```

Derived on read, never stored: net = long − short; 1-year and 3-year percentiles of net; "who closed what" = the
`chg_*` columns by category; a long-only vs short-only split for the owner's "who are short / who are long".

### 8.4 `gold_curve` — settlement curve per exchange per day (basis, term structure, roll, OI by contract)

```sql
CREATE TABLE IF NOT EXISTS gold_curve (
    trade_date    DATE    NOT NULL,
    exchange      VARCHAR NOT NULL,   -- 'COMEX' | 'MCX'
    symbol        VARCHAR NOT NULL,   -- 'GC' | 'GOLD' | 'GOLDM' | 'GOLDPETAL' | 'GOLDGUINEA'
    expiry        DATE    NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, settle DOUBLE,
    volume BIGINT, open_interest BIGINT, oi_change BIGINT, value_lakh DOUBLE,
    unit          VARCHAR NOT NULL,   -- 'USD/oz' | 'INR/10g' | 'INR/g' | 'INR/8g'
    source        VARCHAR NOT NULL,   -- 'icici_master_band' | 'mcx_bhavcopy' | 'cme_settlements' | 'yahoo'
    quality       VARCHAR NOT NULL,   -- 'proxy' (band midpoint) | 'official'
    release_at    TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL,
    PRIMARY KEY (trade_date, exchange, symbol, expiry, source)
);
```

`source` is in the key on purpose: the 07:35 ICICI band midpoint (proxy, the only MCX settlement the stack can read today)
and the official MCX bhavcopy (when G-INDIA gets past the 403) coexist; readers take `official` when both exist. Today's
ICICI master gives, per MCX contract and expiry, the settlement proxy and open interest in lots — so a daily OI history by
contract starts the day this table exists.

### 8.5 `gold_daily_bars`, `gold_etf_holdings`, `gold_preopen_log`, `gold_brief_docs`

```sql
CREATE TABLE IF NOT EXISTS gold_daily_bars (     -- own daily history of the live legs: GC=F, GC<month>.CMX, SI=F, INR=X,
    trade_date DATE NOT NULL, symbol VARCHAR NOT NULL,   --   DX-Y.NYB, ^TNX, GLD, EURUSD=X (Yahoo today; replaceable)
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
    source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
    PRIMARY KEY (trade_date, symbol, source)
);
CREATE TABLE IF NOT EXISTS gold_etf_holdings (   -- GLD, IAU, GOLDBEES … tonnes/shares/NAV (G-PHYSICAL / G-INDIA sources)
    report_date DATE NOT NULL, fund VARCHAR NOT NULL,
    tonnes DOUBLE, shares BIGINT, nav DOUBLE, aum_usd_mn DOUBLE, aum_inr_cr DOUBLE,
    release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
    PRIMARY KEY (report_date, fund, source)
);
CREATE TABLE IF NOT EXISTS gold_preopen_log (    -- migrates data/gold_preopen/log.json; one row per MCX trading day
    day DATE PRIMARY KEY, snapshot_at TIMESTAMP, contract VARCHAR, expiry DATE,
    baseline DOUBLE, baseline_source VARCHAR, baseline_session DATE,   -- the SESSION the settlement belongs to (finding 1)
    comex_symbol VARCHAR, comex_ref DOUBLE, comex_now DOUBLE, inr_ref DOUBLE, inr_now DOUBLE,
    fair_open DOUBLE, threshold DOUBLE, event_risk INTEGER,
    actual_open DOUBLE, actual_source VARCHAR, captured_at TIMESTAMP,
    error DOUBLE, naive_error DOUBLE,
    inputs_json VARCHAR                              -- the bars and master metadata used (finding 2: auditable misses)
);
CREATE TABLE IF NOT EXISTS gold_brief_docs (     -- gold_premarket/YYYYMMDD.json, validated against its schema on ingest
    report_date DATE PRIMARY KEY, generated_at TIMESTAMP, schema_version VARCHAR,
    bias VARCHAR, bias_score DOUBLE, confidence DOUBLE, model_fair_open DOUBLE, open_signal VARCHAR,
    doc JSON NOT NULL, file_sha256 VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL
);
```

### 8.6 `gold_events` — the gold calendar

```sql
CREATE TABLE IF NOT EXISTS gold_events (
    event_date DATE NOT NULL, time_ist VARCHAR, kind VARCHAR NOT NULL,   -- FOMC | US_CPI | US_NFP | RBI | MCX_EXPIRY |
    name VARCHAR NOT NULL, detail VARCHAR, source VARCHAR NOT NULL,       -- COMEX_FND | COMEX_LTD | COT_RELEASE | MCX_HOLIDAY | WGC_RELEASE
    first_seen_at TIMESTAMP NOT NULL,
    PRIMARY KEY (event_date, kind, name)
);
```
FOMC and RBI rows come from the existing parsers in `routers/markets.py` (moved to data-service or called by the job);
MCX expiries and holidays from `shared/mcx_specs`; COMEX FND/LTD and COT release dates from G-CME / G-COT.

### 8.7 Freshness and explorer wiring

`get_positions_meta()` gains `gold_series: report_date`, `gold_cot: report_date`, `gold_curve: trade_date`,
`gold_daily_bars: trade_date`, `gold_etf_holdings: report_date`, `gold_preopen_log: day`, `gold_brief_docs: report_date`;
`last_date()`'s allowlist gains the same names; `scripts/master_controller.py` `DATASET_MAX_AGE_DAYS` and
`ui/components/NseDatasets.tsx` `MAX_AGE_DAYS`/`ABOUT` gain rows (`gold_cot` 9 days — weekly plus a holiday shift;
`gold_curve` 4; `gold_daily_bars` 4; `gold_etf_holdings` 5; `gold_preopen_log` 4; `gold_series` per-series from the
catalog, reported as the worst one). The WHSE panel then shows OK / STALE for gold like it does for NSE tables, and the
08:30 `pre_market_sync` freshness alert covers gold with no new code path.

---

## 9. Ingest jobs (data-service endpoints) and the IST schedule (master-controller)

### 9.1 Endpoints (same `_submit` job registry; `POST` returns `job_id`, the controller polls `/jobs/{id}`)

| Endpoint | Body | Writes | Notes |
|---|---|---|---|
| `POST /jobs/ingest-gold` | `{"groups": ["overnight","mcx_master","cot","weekly","monthly","brief"], "backfill_from": "YYYY-MM-DD"?}` | all gold tables by group | one endpoint, idempotent groups; each group skips when not due (`gold_series_catalog.freq` + last `report_date`); a group's failure is reported per series, never fails the others |
| `POST /jobs/gold-log` | `{"day", "snapshot": {...}}` or `{"day", "actual_open", "actual_source"}` | `gold_preopen_log` | called by ui-api's `/snapshot` and `/capture-open` (dual-write with `log.json` until the UI reads the table) |
| `GET /db/gold/series?ids=&from=&to=&asof=` · `/db/gold/cot` · `/db/gold/curve` · `/db/gold/etf` · `/db/gold/events` · `/db/gold/log` · `/db/gold/brief?date=` · `/db/gold/catalog` | — | — | read endpoints ui-api proxies; `asof` defaults to now |

### 9.2 Schedule (IST). Light jobs (seconds); none restart anything, so the 07:45–09:20 / 18:30–21:15 freeze windows only
constrain *restarts*; still, nothing heavy is placed inside them.

| Time (IST) | Job id | Group | Why this time |
|---|---|---|---|
| 06:40 daily (Mon–Sat) | `gold_overnight_ingest` | `overnight`: COMEX settlements for the prior US session (G-CME), FRED DFII10/DGS10/DTWEXBGS via keyless CSV (FRED posts ~01:45 IST), Treasury real curve, Yahoo daily bars for the live legs, GLD/IAU tonnes (G-PHYSICAL), catalog-driven monthly/weekly rows that are due | after every US publication, before the 07:45 window; Saturday run picks up Friday's US close |
| 07:35 Mon–Fri (+ retry 08:35) | `gold_mcx_master_ingest` | `mcx_master`: conditional GET of the ICICI master (`If-Modified-Since`), band-midpoint settlement + OI per contract → `gold_curve` (proxy), warms ui-api's master | ICICI publishes ~07:00–07:30 (Fri: 07:28); the 08:35 retry catches a late file; MCXG/GOLD then never pay the 6.9 s cold load during the morning |
| 08:45 Mon–Fri | `gold_preopen_snapshot` (exists) | writes `gold_preopen_log` via `/jobs/gold-log`; **skips full and morning-closure MCX holidays** (`mcx_specs.trading_window`) | unchanged time |
| open + 10 min | `gold_open_capture` (exists; 09:10 normally, 17:10 on morning-closure days) | actual open → `gold_preopen_log` | finding 3 |
| 13:45 Mon–Fri | `gold_inr_reference` | FBIL/RBI USD/INR reference → `gold_series` (G-INDIA verifies) | FBIL publishes ~13:30 |
| 21:30 Mon–Fri | `gold_london_close` | LBMA PM price, SGE close, IBJA PM rate → `gold_series` (G-PHYSICAL / G-INDIA verify access and terms) | London 15:00 = 20:30 IST in winter / 19:30 in summer; 21:30 is after both and after the 21:15 freeze |
| 00:40 Tue–Sat | `gold_mcx_bhavcopy` | official MCX bhavcopy → `gold_curve` (official) — **only if G-INDIA finds a scriptable path (403 today)** | MCX evening close 23:30/23:55 |
| Sat 02:40 (+ catch-up inside Sat/Tue 06:40) | `gold_cot_weekly` | CFTC COT → `gold_cot`; COT release date rows → `gold_events` | CFTC releases Fri 15:30 ET = 01:00 IST (US DST) / 02:00 IST (standard); Monday releases after US holidays are caught by the Tuesday overnight run |
| Sat 10:30 | `gold_weekly_ingest` | RBI WSS gold reserves, any weekly catalog series | alongside `financials_sweep`; keeps Saturday morning light |
| in `gold_overnight_ingest` when due | monthly: WGC ETF flows, central-bank purchases, DGCI&S imports, AMFI gold-ETF AUM | catalog `freq='M'` + `publish_time_ist` rule | no separate cron; a due check is cheaper than a calendar |
| 08:50 Mon–Fri (existing `morning_note`) | add the health line | reads `/api/gold/health` | one line in the note the owner already gets |
| 09:00–09:05 daily | `gold_brief_ingest` | `gold_premarket/*.json` → `gold_brief_docs` (schema-validated; sha256 dedupe) | the external task writes 08:40–09:00 |

Catch-up after downtime: `missed_jobs()` already lists missed runs; `gold_overnight_ingest` is idempotent and re-runnable
with `backfill_from`, so the existing `startup_catchup` only needs the job id added to `_KEY_JOBS`.

### 9.3 ui-api: router, caching, warm

- New `services/ui-api/routers/gold.py` mounted at `/api/gold` (tag `gold`). It **composes**, never re-implements:
  `gold_preopen` for the fair-open model and the Yahoo SWR fetcher (`_yahoo_bars_cached`), `mcx` for the Breeze quote path
  and `shared/mcx_specs` for sessions/expiries, data-service `/db/gold/*` for stored series. `mcx._fair_value` switches to
  `gp._yahoo_bars_cached` (finding 6). One Yahoo fetcher for gold, period.
- Caches (all `cache.py` primitives, all self-registered for `/api/telemetry/caches`): `SWRCache("gold.store", max_items=256,
  refresh_after=120, max_age=900)` for data-service reads (the stored series change once a day; the page shows
  `X-Cache-Age`); `TTLCache("gold", 64)` with `health` 60 s, `catalog` 3600 s, `overview` 30 s; live legs keep the 30/120 s
  Yahoo SWR; the Breeze path keeps `QUOTE_TTL_S = 15` and the 10-minute broken memory. Invalidation: `/jobs/ingest-gold`
  completion is followed by the controller calling `POST /api/gold/invalidate` (or simply letting the 120 s refresh pass;
  the controller already tolerates such staleness elsewhere).
- Warm: add `("gold_overview", lambda: gold.overview())` to `routers/_cache_warm.warm_calls` (the existing
  `gold_yahoo_series` step stays).
- Compatibility: `/api/commodity/gold-preopen*` paths stay as thin aliases for one release (the controller posts to them;
  `lib/api.ts` points at `/api/gold/*`).

---

## 10. API contract for the GOLD page (`/api/gold/*`)

All responses: `as_of` (IST ISO), per-block `freshness` (`{source, as_of, age_s, state: live|delayed|stale|unavailable}`),
the `errors.py` envelope on failure (`fail` → `{detail, error{code,message,hint}}`; usable-but-partial → `degraded(...)`
with `ok:false` + `error_info`). Numbers are numbers (never pre-formatted strings); the UI formats with the terminal kit.

### `GET /api/gold/overview?contract=GOLD&expiry=&window=D|W|M`
```json
{
  "as_of": "2026-10-26T08:50:12+05:30",
  "contract": {"mcx": "GOLD", "expiry": "2026-12-04", "expiry_source": "observed", "comex_matched": "GCZ26.CMX",
               "comex_front": "GC=F", "spot_proxy": "XAUUSD=X", "lot": "1 kg", "tick_value": 100},
  "session": {"mcx": {"is_open": false, "opens_at": "...", "closes_at": "...", "holiday": null},
              "comex": {"is_open": true, "note": "CME Globex 18:00–17:00 ET, 60-min break"}},
  "health": { "...": "same object as /api/gold/health" },
  "fair": { "...": "same object as /api/gold/fair (the pre-open model)" },
  "quote": { "...": "same object as /api/mcx/quote for the picked contract (available / degrade / fallbacks)" },
  "headlines": [{"topic": "Gold", "title": "...", "publisher": "...", "link": "...", "published_at": "..."}],
  "brief": {"available": true, "report_date": "2026-10-26", "bias": "neutral", "bias_score": 0.5, "confidence": 0.6,
            "overnight_summary": "...", "open_plan": "...", "key_risks_today": ["..."]},
  "calendar": [{"date": "2026-10-29", "time_ist": "23:30", "kind": "FOMC", "name": "FOMC decision", "days": 3}],
  "freshness": {"health": {"state": "delayed", "age_s": 41}, "fair": {"state": "live"}, "quote": {"state": "degraded"}}
}
```

### `GET /api/gold/health?window=D|W|M`
```json
{
  "as_of": "...", "window": "D",
  "score": 2, "supportive": 4, "headwind": 2, "stale": 1, "of": 7,
  "line": "4 of 7 drivers supportive · real yields ↓, dollar ↓, ETF inflow; COT crowded long · context only",
  "evidence": "context only",
  "drivers": [
    {"key": "real_yield_10y", "label": "10y real yield (TIPS)", "value": 2.66, "unit": "%", "change": -0.10,
     "report_date": "2026-10-23", "release_at": "2026-10-23T19:30:00Z", "age_days": 3, "state": "delayed",
     "direction_for_gold": "supportive", "rule": "falling real yields support gold",
     "source": "US Treasury real yield curve (FRED DFII10 fallback)", "series_id": "UST_REAL_10Y", "evidence": "context only",
     "percentile_1y": 38},
    {"key": "cot_managed_money_net", "label": "COMEX managed-money net (contracts)", "value": 180234, "change": -9100,
     "report_date": "2026-10-20", "release_at": "2026-10-23T19:30:00Z", "age_days": 6, "state": "delayed",
     "direction_for_gold": "headwind", "rule": "crowded long (≥ 90th pct) is a headwind; washed-out is supportive",
     "percentile_1y": 92, "source": "CFTC COT disaggregated, futures+options", "series_id": "COT_MM_NET", "evidence": "context only"}
  ],
  "fair": {"fair_value": 144231, "mcx_live": null, "premium_rupees": null, "premium_pct": null, "comex": 4004.3, "usdinr": 94.93,
           "landed": 122214, "implied_premium_pct": 18.02, "settlement": 146079, "settlement_session": "2026-10-22"},
  "freshness": {"state": "delayed", "oldest_driver": "cot_managed_money_net", "age_days": 6}
}
```
(The driver values above are illustrative shapes; the COT numbers are placeholders until G-COT's ingest exists. The `fair`
block numbers are today's live `/api/mcx/overlay` values.)

### `GET /api/gold/fair?baseline=&mcx_price=&threshold=&contract=&expiry=`
Exactly today's `/api/commodity/gold-preopen` body (`contract`, `baseline{value,source,session,close_time,
settlement_from_band}`, `mcx_price{value,source,broker}`, `model{comex{...},inr{...},fair_open,gap,gap_pct,comex_part,
inr_part,rs_per_comex_dollar,rs_per_inr_rupee,implied_premium_pct,lot_pnl_per_rupee,threshold_in_comex_dollars}`,
`threshold`, `verdict{state,title,detail,diff}`, `event_risk{flagged_headlines,advice}`, `context[]`, `headlines[]`,
`manual_checks[]`, `notes[]`) plus three additions: `baseline.session_label` ("Thu 22 Oct settlement"), `accuracy{days,
median_abs_error,within_threshold_pct,naive_mean_abs_error}` (so the verdict can show its track record), and
`holiday{closure, note}` when `mcx_specs.holiday_on(today)` is set. `eurusd_trigger` leaves the query string and becomes a
prefs value the UI passes only if set.

### `GET /api/gold/series?ids=FRED_DFII10,UST_REAL_10Y&from=2025-10-01&to=&freq=D|W|M&asof=`
```json
{"as_of": "...", "asof_applied": "2026-10-26T03:20:00Z", "freq": "W",
 "series": [{"series_id": "FRED_DFII10", "name": "10-year TIPS yield", "unit": "%", "freq_native": "D", "quality": "official",
             "points": [{"report_date": "2026-10-17", "value": 2.70, "release_at": "2026-10-17T20:15:00Z"}],
             "resample": "last", "catalog": {"publisher": "FRED", "verdict": "PUBLISH-CONTEXT", "lag_note": "prior US session, ~01:45 IST"}}]}
```
Resampling rules are explicit per series (`last` for levels, `sum` for flows, `mean` for premiums) and come from the catalog.

### `GET /api/gold/cot?weeks=52&report=disagg_fo`
```json
{"as_of": "...", "report": "disagg_fo", "market_code": "...", "latest": {"report_date": "2026-10-20", "release_at": "..."},
 "categories": [{"category": "managed_money", "long": 0, "short": 0, "spread": 0, "net": 0,
                 "chg_long": 0, "chg_short": 0, "chg_net": 0, "pct_oi_long": 0.0, "pct_oi_short": 0.0,
                 "traders_long": 0, "traders_short": 0, "net_percentile_1y": 0, "net_percentile_3y": 0}],
 "open_interest": {"total": 0, "chg": 0},
 "history": [{"report_date": "...", "managed_money_net": 0, "commercial_net": 0, "open_interest": 0, "price_settle": 0.0}],
 "who_closed": {"longs_cut": ["managed_money"], "shorts_cut": ["swap_dealer"], "note": "week-on-week change in positions by category"}}
```

### `GET /api/gold/positioning/daily?exchange=MCX|COMEX&days=60`
Per `trade_date` and contract: `open_interest`, `oi_change`, `volume`, `settle`, `quality` (proxy/official) from
`gold_curve`; the MCX side exists from day one (ICICI master), the COMEX side when G-CME's feed is in.

### `GET /api/gold/curve?exchange=COMEX|MCX&date=`
`[{expiry, settle, open_interest, volume, days_to_expiry, spread_vs_front, annualised_carry_pct}]` plus
`basis: {mcx_front_inr, landed_inr, premium_pct, usdinr, duty_note}` and `history: [{trade_date, premium_pct}]`.

### `GET /api/gold/flows?months=24`
`etf: [{report_date, fund, tonnes, chg_5d_t, chg_1m_t}]`, `wgc_monthly: [...]`, `physical: [{series_id, report_date, value}]`
(SGE premium, India premium/discount, imports, RBI reserves), each with the catalog block and the verdict.

### `GET /api/gold/calendar?days=30` → `gold_events` rows with `days` and `time_ist`.
### `GET /api/gold/log?days=60&threshold=300` · `POST /api/gold/log/actual` → today's accuracy-log shapes, read from the table.
### `GET /api/gold/catalog` → `gold_series_catalog` rows (the data dictionary; also rendered as `docs/GOLD_DATA_DICTIONARY.md`).
### `GET /api/gold/brief?date=` → the stored brief document and its `data_quality` block.
### `POST /api/gold/snapshot` · `POST /api/gold/capture-open` → today's semantics, holiday-aware, dual-writing to the table.

---

## 11. Gates: how ui_perf / ui_audit / parity / tests extend

| Gate | What changes | Pass condition |
|---|---|---|
| `scripts/ui_audit.py` | default `TABS` + `gold`; `--tabs all` resolves 43 via `desktop_qa.pages` | 16/16 default, 43/43 `--browser both`; zero console errors; failed requests only platform seams |
| `scripts/ui_perf.py` | nothing to edit: parses `COMMAND_PAGES`, cross-checks `TAB_IDS` | tab-switch p95 ≤ 400 ms for `gold`; first-load gz ≤ 300 KB (page lazy-loaded; charts drawn with the kit, no new chart library) |
| `scripts/desktop_qa/parity.py` | `gold` listed as an expected program delta (no A side) | 42 PARITY + 1 expected delta |
| `scripts/desktop_qa/probe.py` | nothing: `PageHeader code="GOLD"` renders the amber chip | chip text == `GOLD` |
| `desktop/src-tauri` tests | `PAGE_COUNT = 43`, three `assert_eq!(…, 42)` → 43, group coverage | `cargo test` green |
| `ui/components/__tests__/pages.check.ts` | add: health line contains "context only" until a PASS verdict; signed numbers use U+2212; one unit per column; the four instrument labels are distinct strings | node checks green |
| `services/ui-api/tests/test_gold.py` (new) | offline: data-service mocked; health scoring (stale chips excluded), as-of resampling, D/W/M, catalog-driven freshness, holiday gating of snapshot/capture, aliases to `/api/commodity/gold-preopen*` | pytest green; keep `test_gold_preopen.py` + `test_mcx.py` (49 tests today) untouched |
| `tests/` (data-service) | PIT as-of query returns the vintage, not the revision; `INSERT OR REPLACE` dedupe on re-fetch; `source`-in-key coexistence of proxy and official curve rows | green |
| `scripts/tests/` | holiday-aware job gating (20 Oct morning closure → skip 08:45, capture 17:10); conditional-GET master loader (304 path) | green |
| RUNBOOK / CLAUDE.md | "42 pages" → 43; "15/15 ok" → 16/16 | docs match the parsers |

---

## 12. Metrics and sources: verdicts (usefulness is the gate)

Sources the app relies on today, as verified in this hour (external datasets proposed by the other agents are judged in
their reports; the catalog table carries all of them):

| Source | Access | Used by | Verdict | Reason |
|---|---|---|---|---|
| Yahoo v8 chart JSON (GC=F, GC<month>.CMX, SI=F, INR=X, DX-Y.NYB, ^TNX, EURUSD=X, GLD) | FREE, unofficial; UA-sensitive (429 with browser/py UA, 200 with the app's UA); no redistribution terms published for this endpoint | tape, WEI, CMDT, desk, MCXG | PUBLISH-CORE for live legs with the source labelled "Yahoo, delayed"; store daily closes in `gold_daily_bars` so history does not depend on it | the project's existing history provider; cheap; but unofficial — never the only copy of a number |
| FRED `fredgraph.csv` (DFII10 and any series, keyless) | FREE | desk (TIPS) | PUBLISH-CONTEXT | official, 0.75 s, one day late; the keyless CSV avoids the unset `FRED_API_KEY` |
| US Treasury daily real yield curve CSV | FREE | desk (TIPS, one day fresher) | PUBLISH-CONTEXT | official; 1.5 s today |
| Google News RSS (gold topics) | FREE; personal RSS use; redistribution of headlines beyond links is not granted | desk, BRF | PUBLISH-CONTEXT as links (title + publisher + link only, as today) | context; no evidence (the news-scanner study was NO EDGE) |
| ICICI Direct `SecurityMaster.zip` → `MCXScripMaster.txt` | FREE public file, no login | desk, MCXG | PUBLISH-CORE for specs/expiries/OI/band; settlement as `proxy` labelled by session | the only MCX settlement source reachable without a browser; use conditional GET |
| ICICI Breeze (MCX 1-min bars / quotes) | account credential; not exercised here (rule) | desk after 09:00, MCXG | PUBLISH-CORE when live, with the existing honest degrade | the only live MCX price; keep REST calls off the request path |
| Kitco gold chart page | FREE page; robots `Allow: /`; no embed/data product found; terms silent on chart embedding | manual link | LINK-ONLY | the owner's reference chart; own charts replace the need |
| CME FedWatch | BLOCKED to scripts (403) | manual link | LINK-ONLY | fine as a link; G-CME may find the underlying probabilities feed |
| mcxindia.com (bhavcopy, circulars, margins) | BLOCKED to scripts (403); UNVERIFIED in a browser session from here | manual link | LINK-ONLY until G-INDIA verifies | the official settlement; today the ICICI proxy stands in |
| `gold_premarket/*.json` briefs (internal) | local files | nothing | PUBLISH-CONTEXT after schema validation, labelled "automated brief, confidence X" | it already exists daily; synthesis, not data |

Metrics on the page:

| Metric | Formula / definition | Verdict | Reason |
|---|---|---|---|
| Fair open (₹/10 g) | settlement × (COMEX now ÷ COMEX at the MCX close) × (USD/INR now ÷ USD/INR at the close); references = 30-minute averages before 23:30/23:55 IST | PUBLISH-CORE | the one actionable number; misses must be shown next to it |
| Expected gap, COMEX part, rupee part | fair − settlement; settlement×(r_c−1); settlement×r_c×(r_i−1) | PUBLISH-CORE | explains the gap; the waterfall is the right visual |
| MCX now vs fair, chase limit | live − fair; threshold ₹300 default | PUBLISH-CORE with the measured error attached | limit unproven (2 rows, misses ₹2.9–3.5k) |
| Implied MCX premium over landed | settlement ÷ (COMEX×USDINR×10/31.1035) − 1 | PUBLISH-CONTEXT (history chart) | duty + local premium + rupee expectations; its *changes* carry information, the level is mostly duty |
| Rule of thumb ₹ per $1 / ₹ per ₹1 | settlement ÷ COMEX ref; settlement ÷ INR ref | PUBLISH-CONTEXT | useful desk arithmetic |
| Accuracy stats (MAE, median, p90, within-limit %, bias, naive MAE) | from `gold_preopen_log` | PUBLISH-CORE | the only honesty check on the model |
| Health score / line | §7.2 | PUBLISH-CONTEXT, explicitly "context only" | no predictive evidence yet; G-STUDY tests it |
| Event-risk headline count | keyword hits | DO-NOT-PUBLISH as advice; keep as a count label | no evidence; keyword noise |
| COT managed-money net, w/w change, 1y percentile | from `gold_cot` | PUBLISH-CONTEXT (the owner's explicit ask) | positioning is context; extremes are a known but noisy contrarian cue — G-STUDY |
| Daily OI by contract and change | `gold_curve` | PUBLISH-CONTEXT | "who added / closed" at the contract level; no trader split exists for MCX |
| Term structure / carry | (second − front) ÷ front × 365 ÷ days | PUBLISH-CONTEXT | roll cost is real money for a holder; the alpha-lab's carry result is for NSE F&O, not gold |
| ETF tonnes 5-day change | `gold_etf_holdings` | PUBLISH-CONTEXT | contemporaneous flow proxy |
| Tick value, notional, margin, round-trip cost | `shared/mcx_specs` | PUBLISH-CORE (stays on MCXG) | sizing arithmetic |

Studies to catalog (`routers/research.py` CATALOG rows; area "Gold"): `reports/gold_program/FINDINGS.md` (the program's
verdict page — at one level under `reports/` so `_discover` lists it), `docs/GOLD_DATA_DICTIONARY.md` (REFERENCE, generated
from the catalog table), every `reports/gold_program/G-*/REPORT.md` as explicit CATALOG entries (nested paths are not
auto-discovered), and G-STUDY's FINDINGS in the fii_positioning format (pre-registered PLAN.md, REPORT.md tables, a
PASS/FAIL/NO EDGE verdict with t-statistics and both halves). The GOLD page shows each driver's `ResearchNote` chip once a
verdict exists.

---

## 13. Glossary (first use for the newcomer; exact definition for the professional)

- **Spot gold (XAU/USD)** — the price for immediate delivery of one troy ounce (31.1035 g) of 995+ fine gold in London
  (loco London). Pro: an OTC market; the published "spot" is a composite of dealer quotes, there is no exchange tape.
- **COMEX GC** — the CME gold futures contract, 100 oz, USD/oz, delivery months Feb/Apr/Jun/Aug/Oct/Dec plus nearby months.
  `GC=F` on Yahoo is the continuous front month (Dec-26 today); `GCZ26` is the specific December-2026 contract.
- **MCX GOLD / GOLDM / GOLDPETAL / GOLDGUINEA** — India's exchange-traded gold futures: 1 kg (₹ per 10 g, tick ₹1 = ₹100
  per lot), 100 g (₹10 per tick), 1 g, 8 g. Expiries: 5th of Feb/Apr/Jun/Aug/Oct/Dec for GOLD, monthly for the rest.
- **Settlement price** — the exchange's official end-of-day price (MCX: the volume-weighted average of the last 30 minutes),
  used for margins and the next day's price band. The app's settlement is a *proxy*: the midpoint of ICICI's ±3% band.
- **Price band (DPR)** — the daily range the exchange allows around the previous settlement (±3% initially for gold, widened
  in steps on a limit hit). Pro: the band in ICICI's file is centred on the previous settlement — that is why the midpoint works.
- **Landed cost** — COMEX price × USD/INR × 10 ÷ 31.1035: what 10 g of gold costs in rupees before duty, GST and premium.
  **Implied premium** — how far MCX trades above landed (customs duty + local premium + rupee expectations).
- **Fair value / fair open** — where MCX "should" trade given COMEX and the rupee since the last settlement (§12 formula).
  Pro: multiplicative; the two references are 30-minute averages, matching MCX's own settlement window.
- **Basis** — futures minus spot; **contango** (futures above spot: positive carry cost) vs **backwardation** (below).
  **Term structure / curve** — settlements of successive expiries; **roll yield** is what a holder pays or earns moving to
  the next contract.
- **Open interest (OI)** — contracts outstanding; rises when new longs meet new shorts, falls when positions close.
- **COT (Commitments of Traders)** — the CFTC's weekly report of futures positions by trader category as of Tuesday,
  released Friday: producers/merchants (hedgers), swap dealers, **managed money** (funds, the "speculators"), other
  reportables, non-reportables (small). Net = long − short. Pro: use the disaggregated futures-and-options report; watch the
  week-on-week change and percentiles, not levels; after a US holiday the release slips to Monday.
- **Real yield** — a Treasury yield minus expected inflation; measured by TIPS (DFII10 = 10-year). Gold pays nothing, so a
  higher real yield raises its opportunity cost — the sign of the relationship is the best-established fact in gold.
- **DXY** — the dollar index against six major currencies; a weaker dollar makes gold cheaper for non-dollar buyers.
- **ETF holdings** — tonnes held by funds such as GLD (SPDR) and IAU; changes track investment flows.
- **SGE premium** — Shanghai Gold Exchange price minus the London/COMEX equivalent: Chinese physical demand.
- **LBMA** — the London bullion market's association; its twice-daily auction prices (AM/PM) are the global benchmark; it
  also publishes OTC trade volumes (the "over-the-counter deals" the owner asked about).
- **IBJA** — India Bullion and Jewellers Association, publishes the Indian reference rates (999/995) used for sovereign
  gold bond pricing.
- **Chase limit** — the desk rule: do not buy the open more than ₹300 above fair; wait for the 09:00 rupee open to settle.
- **Point-in-time (PIT)** — storing each value with when it became public, so research never uses a revised or late number
  as if it had been known earlier.

---

## 14. Owner actions and open questions

Owner actions: (1) decide the page code (`GOLD` recommended, `XAU` alias) and that CMDT drops the gold desk; (2) approve
the Monday-morning labelling rule ("Thu 22 Oct settlement", never the file date); (3) approve dual-write of the accuracy log
to DuckDB and the holiday-aware job gating (it changes when the 08:45 alert fires on partial holidays); (4) confirm the
Breeze REST budget for MCX 1-minute bars (one call per minute at most, off the request path); (5) the TOTP unattended login
(memory 28 Sep) is still pending the owner enabling TOTP in ICICI settings — until then Monday's 08:00 SMS-OTP reply remains
manual (G-LOGIN).

Open questions for the sibling agents: the CFTC market code and column map for COMEX gold (G-COT); a scriptable COMEX
settlement/OI feed and the CME holiday calendar (G-CME); LBMA/SGE/IBJA access and redistribution terms (G-PHYSICAL,
G-INDIA); a browser-session path to mcxindia.com bhavcopy (G-INDIA); whether any free GVZ or gold-options feed exists
(G-CME); whether the health drivers have any measurable lead on next-week MCX returns (G-STUDY — pre-register before
looking); the Kitco embed question (G-KITCO).

---

## 15. Verification log (what was fetched, status, latency, latest date carried)

| Target | Result |
|---|---|
| `GET :8010/health` / `:8001/health` | 200 ok / 200 ok (`db_read_only: false`) |
| `GET :8010/api/mcx/session` | 200, 0.01 s; closed, opens 09:00, closes 23:30 (US DST), next holidays 10 Nov (morning), 24 Nov (morning), 25 Dec (full) |
| `GET :8010/api/mcx/specs` | 200, **6.89 s** (cold master download); GOLD front 2026-12-04 observed==computed; settlement 146,079; band 141,697–150,461; OI 16,650 lots; indicative margin ₹876,474/lot |
| `GET :8010/api/commodity/health` | `eia_enabled: false`, `fred_enabled: false` |
| `GET :8010/api/commodity/gold-preopen/log?days=10` | 200, 0.01 s; 4 rows (15, 20, 23 Oct + one more); 23 Oct fair 144,938 / open 142,058 / error −2,880 / naive −4,021 / event_risk 3 |
| `GET :8010/api/news-scanner/quotes?symbols=GC=F,SI=F,GLD,INR=X,DX-Y.NYB,^TNX,GCZ26.CMX` | 200, 0.99 s; GC=F "Gold Dec 26" 4,004.3, prev 4,007.9 (2026-10-23), market_date 2026-10-25 (Sunday-evening Globex), 52w 3,901–5,586 |
| `GET :8010/api/mcx/overlay?contract=GOLD` | 200, 0.36 s; GCZ26 4,004.3 (as of 05:32 IST), INR=X 94.93 (as of 01:32 IST — four hours old), landed 122,214, fair 144,231, gap −1,848 vs the 22 Oct settlement, implied premium 18.02% |
| `GET :8010/api/commodity/overview` | 200, 0.31 s; six Yahoo cards; FRED/EIA "key required" |
| `GET :8010/api/telemetry/caches` | `gold_preopen` 21/32 items 74 hits 25 misses; `mcx` 9 items 50/42, 10 expired; `commodity` 1 item; `news_scanner.quotes` 40 items, 620 stale hits, 617 background refreshes |
| `GET :8001/db/freshness` · `/jobs` | latest bar 2026-10-23, 1,374 eligible tickers current; last job `nse_events` done 25 Oct 17:11 UTC |
| `GET :8010/api/research` | 84 studies, none gold |
| Yahoo chart GC=F (and 7 others) with a Chrome-like UA | **429** ×8 in 0.25 s each |
| Yahoo chart GC=F with `Mozilla/5.0 (SuryaDhana-GoldDesk)` | **200**, 0.37 s, 4,002.8 @ 1792973025; with `python-httpx` UA → 429 |
| FRED `fredgraph.csv?id=DFII10&cosd=2026-10-01` (no key, plain UA) | 200, 0.75 s, last `2026-10-22,2.64` |
| Treasury `daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve` | 200, 1.53 s, 204 rows, last `10/23/2026` 10 YR 2.66 |
| Google News RSS `"gold prices" when:1d` (hl=en-IN) | 200, 0.80 s, 100 items |
| ICICI `SecurityMaster.zip` (HEAD) | 200, 0.27 s, 2,998,716 bytes, `Last-Modified: Fri, 23 Oct 2026 01:58:26 GMT` |
| kitco.com/charts/gold · robots.txt · terms-of-use | 200 (0.64 s, title "Gold Price Today … 24 Hour Spot Chart") · `User-agent: * Allow: /` · 200; no embed clause found by keyword scan (redistribution clause concerns user content) |
| cmegroup.com FedWatch page | 403 (JSON body) to a script |
| mcxindia.com home and `backpage.aspx/GetMarketWatch` | 403 both |
| `data/.scheduler_history.json` | saved 02:15 today; only `db_backup_daily` and `overnight_rl_retrain` recorded since the last reset — the gold jobs' last runs are evidenced by `log.json` (23 Oct 08:45 snapshot, 09:10 capture) |
| `.env` key names | `FRED_API_KEY`, `EIA_API_KEY`, `DATA_DIR`, `GOLD_LOG_PATH`: absent (count 0 each; values never read) |
| Not called on purpose | `/api/commodity/gold-preopen`, `/api/mcx/quote`, `/capture-open`, anything Breeze; no POST anywhere |
