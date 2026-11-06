# GOLD program — phase 2 build plan

Written Mon 26 Oct 2026 by the synthesis agent from the ten research reports (see `SOURCES.md` for every source, verdict and
resolved disagreement). This is the hand-off to builders with disjoint ownership. Nothing here is built yet; nothing here
changes the paper-only posture, the Decision Desk, the S1 shadow, the freeze windows or the 08:00 login job.

**The owner's words → what this plan delivers**

| Owner said | Delivered by |
|---|---|
| "CFTC Commitments: Comex Gold Futures/Options … who are short, who are longs on a daily and weekly basis … which position got closed" | §a POSITIONING: weekly COT "who did what" strip (five trader groups, Δ week, who closed what) + options overlay line; **daily** COMEX OI by product (CME FTP) and MCX OI per contract (ICICI master) with the opened/closed read |
| "health check for gold" | §a HEALTH: five-number header strip, eight gauges, a rule-based verdict that **describes, does not predict** |
| "include like kitco.com/charts/gold" | §a DAILY: our own 24-h chart (IST + NY axes, previous-day overlay, settle line, Shanghai/London/New York/MCX session bands, 3-day overlay) from stored 1-minute bars; Kitco stays a link |
| "over the counter deals and COT and so forth" | §a PHYSICAL › OTC window (LBMA weekly turnover, London vaults, CME EFP prints) + POSITIONING |
| "gold supply demand and price change" | §a PHYSICAL (balance sheet, ETF flows, central banks, premiums, imports) + MACRO (why the price moved: real yield, dollar/KGX, Fed path) |
| "weeks days and month" | §c DuckDB tables with point-in-time columns; §d `/api/gold/series?freq=D|W|M`; WEEKLY and MONTHLY sub-views |
| "create a visual separately and remove repeated information" | one new page GOLD (43rd); §b removes the five-fold fair-value print, the double gold price, the duplicated context rows |
| "keep it in the world market tabs as well" | §b WEI compact card (one extra line + hover) and BRF one line |
| "choose the contract different" | §a CONTRACTS: exchange × family × expiry selector (incl. GOLDTEN), per-contract economics, OI ladder, roll calendar, matched COMEX month |
| "autologin icici" | §g BRKR "Auto-login (TOTP)" panel + today's owner actions (§i O-4) |
| "basic to complex, very sophisticated" | §e LEARN (CURRICULUM.md Parts 0–9, 129-term glossary, 93 tooltips), [B]/[P] layers on every panel |
| "analyse first … if yes then only publish" | §f badge rules; `SOURCES.md` verdict per source and metric; nothing without a verdict renders |

---

## 0. Scope, principles, slices and ownership

### 0.1 Binding principles (acceptance criteria, not advice)

1. **One page.** All new gold panels live on `GOLD`. MCXG stays the trading desk (quote, selector, ticket). No panel is rendered on two pages; the repetition test (§h T9) fails the build otherwise.
2. **One fetcher for Yahoo.** Every live Yahoo leg goes through `gold_preopen._yahoo_bars_cached` (SWR 30/120 s, single flight, the app's UA on `query2`). data-service owns all history. Budget ≤ 6 chart calls/min across the app; `period1/period2` for daily bars, never `range=max`; every job backs off on 429 (5 → 10 → 20 min) and logs STALE.
3. **Store, then show.** Every number on the page is read from DuckDB or the SWR cache, never from a publisher on the request path. Histories (daily / weekly / monthly) begin the day the job starts; the page says so ("since 27 Oct 2026") instead of pretending.
4. **Point-in-time.** Every stored observation carries `report_date` (the period it describes) and `release_at` (when it became public) plus `first_seen_at` (our fetch time); revisions are new rows (`docs/PROGRAMMATIC_DATA_ACCESS.md` §3).
5. **Badges, not colours.** `signal` / `context` / `arithmetic` / `heuristic` per §f; no composite score; no buy/sell colour on a context metric; the health verdict ends "describes, does not predict".
6. **Terms posture.** Fetch only the hosts in the allowlist (§c.6). Never `www.cmegroup.com`, `mcxindia.com`, `kitco.com`, `prices.lbma.org.uk`, `stooq`, `goldprice.org`, `investing.com` from the stack. WGC / SPDR / IBJA / SGE numbers are displayed with attribution on the private terminal and never re-served (owner decision O-1 may downgrade them to links).
7. **Nothing feeds a trade.** No gold series enters the Decision Desk, the S1 shadow, alerts that imply direction, or the paper ticket's price. The ticket gains sizing arithmetic only.
8. **Honest labels.** Settlement is labelled by its **session** ("Thu 22 Oct settlement"), never by the ICICI file date; proxy vs official is visible; the four instruments are named (spot proxy · COMEX front GC1 · matched month GCZ26 · MCX GOLD Dec-26).
9. **Freeze windows.** Jobs only fetch; still, none is placed inside 07:45–09:20 or 18:30–21:15 IST. ui-api deploys avoid 07:55–08:10; data-service / master-controller restarts only outside both windows.
10. **Every number: value · source · as-of · lag chip** (`SourceChip`: LIVE Breeze / DELAYED Yahoo / STALE / OFFLINE), daily data shows its date, not a clock.

### 0.2 Builders, ownership, order

| Builder | Owns (paths) | Produces | Consumes | Gate before merge |
|---|---|---|---|---|
| **B1 data** | `services/data-service/gold/` (new package: `schema.py`, `ingest_*.py`, `catalog_seed.py`), `storage/duckdb_store.py` (gold DDL + `_upsert` casts + `get_positions_meta`), `main.py` (`/jobs/ingest-gold`, `/db/gold/*`) | the 19 tables (§c.1), the catalog seed (§c.2), read endpoints (§c.5) | the schema contract in §c; the samples in §h T3 | replay tests green; PIT tests green; allowlist test green |
| **B2 controller** | `scripts/master_controller.py` (gold jobs, holiday gating, `_mark_failed`, `?force=1`), `scripts/stack_watchdog.sh` untouched, `DATASET_MAX_AGE_DAYS` | the IST schedule (§c.3), Telegram digest lines, catch-up | B1's job endpoints | `scripts/tests` green; a dry-run of `missed_jobs()` lists the new ids |
| **B3 api** | `services/ui-api/routers/gold.py` (new), `gold_preopen.py` (aliases, session label, holiday, inputs_json, prefs triggers), `mcx.py` (GOLDTEN, one-line overlay, cached fair value, conditional GET), `commodity.py` (drop desk, keyless FRED), `research.py` (CATALOG rows), `routers/icici_totp.py` (new) + `icici_admin.py` allowlist, `shared/mcx_specs.py` (GOLDTEN, Muhurat, duty constant, margin source), `shared/config.py` (`GOLD_IMPORT_DUTY_PCT`, `CFTC_APP_TOKEN`) | the `/api/gold/*` contract (§d), `/api/positions/totp/*` (§g) | B1's `/db/gold/*` | `services/ui-api/tests` green incl. `test_gold.py`, `test_icici_totp_routes.py`; no new Yahoo fetcher (T9) |
| **B4 ui** | `ui/components/gold/` (new: `GoldPage.tsx`, one file per sub-view, `HealthStrip.tsx`, `GoldPreOpen.tsx` + `GoldAccuracyLog.tsx` moved here), `ui/app/page.tsx`, `ui/components/shell/tabModules.ts`, `ui/components/desktop/pages.ts`, `ui/lib/goAliases.ts`, `ui/lib/prefs` (key `gold.contract.v1`), `WorldMarkets.tsx`, `Brief.tsx`, `CommodityTab.tsx`, `McxGoldDesk.tsx`, `MarketCommandHeader.tsx` (tape label), `PortfolioSummary.tsx` (BRKR panel) | the page, the compact WEI card, the BRF line, the MCXG one-liner, the BRKR panel | §d contracts (mocked until B3 lands), `tooltips.json`, `glossary.json` | `npx tsc --noEmit`; `pages.check.ts`; `ui_audit` 16/16 and 43/43; `ui_perf` budgets |
| **B5 learn + docs** | `ui/components/gold/Learn.tsx`, `ui/lib/gold/{tooltips,glossary}.json` (copied from `G-EDU/`), `docs/GOLD_DATA_DICTIONARY.md` (generated from the catalog), `docs/RUNBOOK_RESTORE.md`, `CLAUDE.md`, `docs/IMPROVEMENT_LOG.md`, `reports/gold_program/FINDINGS.md` | LEARN, glossary panel, tooltip wiring, the docs | `G-EDU/CURRICULUM.md` (rename pass per Appendix B) | every term in `see_also` resolves; every tooltip key maps to a rendered field |
| **B6 desktop + gates** | `desktop/src-tauri/src/pages.rs` (PAGE_COUNT 43), `scripts/ui_audit.py` TABS, `scripts/desktop_qa/parity.py` expected deltas, `reports/desktop_app/FEATURE_PARITY.md` | the 43-page gates | B4 | `cargo test`, `boot_check.mjs`, parity 42 + 1 expected delta |
| **B7 studies** | `reports/gold_program/{G-STUDY-2,GS-P1,GS-P2,GS-P4}/PLAN.md` (pre-registered), `scripts/gold_studies/*.py`, `tests/test_gold_study_reproduce.py` | FINDINGS rows; the study-reproduce test | B1 tables | FINDINGS.md verdict rows in the fii_positioning format |

Order: B1 ∥ B3 (against the written contracts) → B2 → B4 ∥ B5 → B6 → B7. B4 may start on day one with a fixture server built from
`G-*/samples`. Slices ship in this order so the owner sees value early: **S1** tables + COT/CME/Yahoo/FRED/GLD/IBJA ingest + the
GOLD page with HEALTH, POSITIONING, CONTRACTS, LEARN; **S2** DAILY/WEEKLY/MONTHLY charts, PHYSICAL, MACRO; **S3** WEI/BRF/CMDT/MCXG
consolidation + the 43-page gates; **S4** BRKR auto-login panel; **S5** studies.

---

## a. The GOLD page

### a.1 Identity and frame

- `id` **`gold`** · code **`GOLD`** · label **"Gold terminal"** · hint "spot, COMEX, MCX, positioning (COT), physical, macro, contracts, health check, pre-open fair value" · group `DerivativesGold` (next to CMDT and MCXG) · GO aliases `XAU`, `GC`, `GPHY` (→ PHYSICAL), `GMAC` (→ MACRO), `LRN` (→ LEARN), `COT` (→ POSITIONING). `GOLD` as the code because the GO bar ranks an exact code match first and the owner types "gold".
- URL state: `?view=gold&sub=health&c=GOLDM&exp=2026-12-04&unit=inr10g&win=W` (sub-view, contract family, expiry, unit, window).
- **Header strip** (the only place live prices appear on this page; the five numbers of CURRICULUM §0): `COMEX GCZ26 $4,007.9 (settle 23 Oct) · live $4,003.4 ▼0.11 % DELAYED·YAHOO · USD/INR 94.93 · 10-y real 2.66 % (23 Oct) · MCX GOLD DEC-26 ₹1,46,079 (Thu 22 Oct settlement) · basis vs duty-paid landed +0.4 % · COT MM net +104,206 (−2,883 w/w, as of Tue 20 Oct) · ◷ MCX opens in 3h04m` plus a `gold-api $3,991.6 00:13Z` cross-check chip (A12) and the four-instrument tooltip.
- **Pickers (page-global, prefs-synced `gold.contract.v1`, shared with MCXG):** exchange (MCX; NSE/BSE greyed with the reason) × family (GOLD / GOLDM / GOLDTEN / GOLDGUINEA / GOLDPETAL / options toggle) × expiry (default: highest-OI expiry more than 5 sessions from the tender period, `gold_preopen.pick_contract`) ↔ matched COMEX month (`comex_symbol()` using `gold_cme_calendar` FND/LTD) ↔ continuous front `GC=F`. Unit picker: $/oz · ₹/10 g · ₹/g · $/g · tola.
- **Sub-view tabs:** HEALTH · DAILY · WEEKLY · MONTHLY · POSITIONING · PHYSICAL · MACRO · CONTRACTS · LEARN. Each sub-view loads on its own (like BRF panels) with its own freshness chip; a blocked/stale source shows the last stored value + STALE + reason, never blank.
- **Beginner / pro layers:** every panel header has an "about" popover from `/api/gold/catalog` (publisher, cadence, lag, formula, pitfalls, verdict, terms) and a `[B] / [P]` toggle (persisted in prefs `gold.layer.v1`) that switches the micro-copy between the plain line and the exact definition; a term's first appearance in a view has a dotted underline → glossary side panel (§e).
- Design: terminal kit only (`PageHeader, Panel, Stat, DataTable, Chip, Notice, Tabs, Spark, KV, Markdown`, `useChartSize`, `axisTicks`; candles via the vendored `lightweight-charts` as `ChartStudio.tsx`; everything else inline SVG); density like MKT/DERV; IST first, NY second on every intraday axis; one y-axis per panel (never dual-axis for COT history).

### a.2 HEALTH — "is gold healthy right now?"

| Panel id | Shows | Data (entry · table/endpoint) | Cadence | Chart | How to read [B] / [P] | Badge |
|---|---|---|---|---|---|---|
| `h.verdict` | one rule-based sentence: e.g. "WEAK WEEK, DOLLAR-DRIVEN · gold −2.8 % Thu was the dollar and real yields, not futures selling (MM net −2.7 % w/w) · India basis +0.4 % · roll into FEB costs 1.03 % (3.2 %/yr) · GLD −12 t on the day · **describes, does not predict**" | `/api/gold/health` (rules in LEARN §H: each clause maps to a threshold) | 60 s | text | [B] what moved and who was behind it, in one breath. [P] no forecast is implied; every clause is a threshold on a stored series | `context` |
| `h.gauges` (8 tiles) | TREND (price vs 20d/200d, 52-w drawdown) · REAL YIELD (level, Δ, "falling = supportive") · DOLLAR (DXY Δ, "rising = headwind") · POSITIONING (MM net, Δ w/w, 3-y percentile once history exists, "long, not crowded") · INDIA BASIS (vs duty-paid landed; IBJA premium) · SHANGHAI PREMIUM · ETF HOLDINGS (GLD t, Δ d/d) · CURVE/ROLL (contango DEC→FEB, annualised, days to FND) | A1, G1/G3, A5, B1, F10/F9, D3/A11, E1, A2/C3 · `gold_series`, `gold_cot`, `gold_curve`, `gold_etf_holdings` | tiles 60 s from cache; daily series at load | `Stat` + 60-day `Spark` each | [B] one line per tile ("falling real yields support gold"). [P] the direction rule, the lag, the percentile window | `context` each (`arithmetic` for curve/roll) |
| `h.open` | **Today's open** (the pre-open desk, moved from CMDT): before 09:00 the verdict strip (OK/WAIT) with the `heuristic` chip and the measured miss, 5 stats (baseline with its **session label**, fair, gap, MCX vs fair, chase limit), gap waterfall (COMEX part / rupee part), inputs panel (baseline override, MCX price, chase limit, EUR/USD trigger from prefs); after the captured open "this morning's call" (fair vs actual, model vs naive); holiday notice on MCX closures | `/api/gold/fair` (today's `/api/commodity/gold-preopen` body + `baseline.session_label`, `accuracy{}`, `holiday{}`) | 60 s | existing `Waterfall` | [B] where MCX "should" open given COMEX and the rupee since 23:30. [P] multiplicative; references are 30-min averages; the ₹300 limit is unproven (misses ₹2.9–3.5k so far) | `arithmetic` (verdict `heuristic`) |
| `h.accuracy` | compact strip: days, median/mean/p90 miss, % within limit, bias, model vs naive, stale-baseline flags; link to the full log table (`GoldAccuracyLog`, moved here) | `/api/gold/log` from `gold_preopen_log` | daily | strip + table | [B] has the 08:45 call been any good? [P] need ≈20 rows before the chase limit means anything; the 15 Oct row looks like a stale baseline | `arithmetic` |
| `h.moved` | WHAT MOVED since the MCX close: COMEX ₹−161 · rupee ₹+77 → fair (reuse the overlay numbers, one line) + gold/silver 74.3 | `/api/gold/fair.model` | 60 s | one bar | [B] how much of the overnight gap is world gold vs the rupee | `arithmetic` |
| `h.events` | EVENT RISK strip: next 7 days in IST — FOMC ★ (23:30 / 00:30 after 1 Nov), US CPI/NFP/PCE (18:00/19:00), COT release (Sat 01:00/02:00), MCX expiries, COMEX FND/LTD, Budget, Dhanteras; in-session vs after-close flag | `/api/gold/calendar` from `gold_events` | daily | strip | [B] when the known shocks hit; after-close = gap risk at 09:00 | `arithmetic` |
| `h.headlines` | gold-topic headlines (title · publisher · link) + the risk-word count as a `heuristic` chip (no sizing advice) | G27 via the existing fetcher | 5 min | list | [B] last 24 h; the count is a keyword tally, not sentiment | `heuristic` |
| `h.brief` | today's automated brief (bias, confidence, overnight summary, open plan, key risks) when `gold_brief_docs` has the day | `/api/gold/brief` | daily | text | labelled "automated brief, confidence X" | `context` |

### a.3 DAILY — the Kitco chart, done our way

| Panel id | Shows | Data | Cadence | Chart | How to read | Badge |
|---|---|---|---|---|---|---|
| `d.24h` | COMEX GC matched month, 24 h, 1-min line; **previous day as a dotted overlay** on the same 24-h axis; dashed **last settlement** line; hi/lo; two-row time axis **IST over NY**; session bands Sydney/Tokyo 03:30–11:30 · Shanghai (SGE) 06:30–09:00 & 11:00–13:00 + night 17:30–00:00 · London 12:30/13:30–21:00/22:00 · New York 18:30/19:30–23:00/00:00 · **MCX 09:00–23:30/23:55** bar under the axis; hatched 17:00–18:00 ET maintenance hour; legend: two previous closes + live last (Kitco's three-row legend) | A1 1-min from `gold_bars_intraday` (7-day window); live last from the SWR cache; A12 cross-check chip; bands from `shared/gold_sessions.py` (new, DST-aware, §j) | 60 s (view re-reads the store; the 5-min job fetches) | inline SVG line | [B] when in the day the move happened and which centre was trading. [P] GC=F rolls before FND; the settle line is the bulletin settlement when C7 is allowed, else the ICICI-free Yahoo previous close labelled as such | `arithmetic` |
| `d.3day` | three days overlaid on one 24-h IST axis, one colour each, with the session bands | same store | 60 s | SVG | [B] today's path vs the last two days, hour by hour | `context` |
| `d.sge` | SGE Au99.99 delayed intraday line on the Shanghai band (CNY/g → $/oz) | D4 `gold_bars_intraday` symbol `SGE_AU9999` | 5 min during SGE hours | SVG overlay | [B] does Shanghai lead or lag the COMEX print | `context` |
| `d.quadrant` | **yesterday's OI × price read, daily**: COMEX GC product OI Δ (C1) and MCX family OI Δ (F1) with the label (long build-up / short build-up / short covering / long unwinding) and a 20-day tape; roll/expiry days greyed | `/api/gold/positioning/daily` | daily (COMEX T+1 ≈15:30 IST; MCX 07:35) | tape + 4-cell matrix | [B] did the move come with new positions or closing ones. [P] product OI, all months summed; roll weeks are mechanical; "who" needs COT | `context` ("folklore until G-STUDY-2") |
| `d.tape` | last 12 × 5-min bars: time · last · Δ · range · volume | A1 | 60 s | table | — | `arithmetic` |

### a.4 WEEKLY — this week in context

| Panel id | Shows | Data | Cadence | Chart | Badge |
|---|---|---|---|---|---|
| `w.candles` | 60 sessions daily candles GC front + MCX GOLD settle (₹, right axis) + 20/50-day lines + volume; Mondays shaded | `gold_daily_bars`, `gold_curve` (MCX proxy settle) | daily | `lightweight-charts` | `arithmetic` |
| `w.table` | Mon ▸ Fri: open · high · low · close · Δ % · range % · COMEX volume · COMEX OI Δ · MCX OI Δ (lots) · IBJA PM · GLD Δt · COT (Fri release) ; CSV export | `gold_daily_bars`, `gold_cme_daily_voi`, `gold_curve`, `gold_series`, `gold_etf_holdings`, `gold_cot` | daily | `DataTable` | `arithmetic` |
| `w.grid` | 26-week heat grid: Mon–Fri daily Δ % + week total | `gold_daily_bars` | weekly | SVG | `context` |
| `w.whodid` | the weekly **"who did what" strip** (duplicated here as a one-line echo of POSITIONING's hero — allowed because it is the same component instance rendered once per view, not a second copy of the data) | `/api/gold/cot.latest` | weekly | line | `context` |

### a.5 MONTHLY — the long view

| Panel id | Shows | Data | Cadence | Chart | Badge |
|---|---|---|---|---|---|
| `m.candles` | monthly candles since 2000 (log); ₹ toggle via GOLDBEES/landed | A1 daily resampled; A4 | monthly | `lightweight-charts` | `arithmetic` |
| `m.ladder` | return ladder 3d · 7d · 30d · 60d · 6m · 1y · 5y · 10y · 15y in $, ₹ (GOLDBEES / landed) and the DXY basket | `gold_daily_bars` | daily | `KV` + sparklines | `context` |
| `m.season` | seasonality grid: mean monthly return and hit rate (1971→ World Bank spliced with GC=F; 2006→ alt), Indian festival months marked; caption "Dec/Jan strong historically; no month passes in both halves; walk-forward best-6-months +0.3 %/yr (G-STUDY, G-MACRO H3)"; hover shows the box of outcomes | G26 + A1 | monthly | SVG heat cells | `context` |
| `m.official` | central-bank net purchases by country, last 12 months (each with its data month); PBoC streak; RBI tonnes and weekly value | E12, F11 | monthly / weekly | bars | `context` |
| `m.physical` | SGE withdrawals (monthly), India imports ($bn, y/y), Swiss exports to India (t), AMFI gold-ETF flow and AUM-in-tonnes, London vault change | D5, F14, E19, F16, E15 | monthly | bars | `context` |
| `m.balance` | WGC quarterly balance sheet: supply (mine, recycled, hedging) vs demand (jewellery, technology, bar & coin, ETFs, central banks, OTC & other), stacked bars 2010→ | E7 | quarterly | stacked bars | `context` |
| `m.liquidity` | collapsed: gold/M2 percentile, HY OAS, GPR monthly percentile, inflation-expectation models | G10, G12, G23, G4 | monthly | `KV` | `context` |

### a.6 POSITIONING — who is long, who is short (weekly COT + daily OI)

One sentence under the title: *"Who is answered weekly by the CFTC with a 3-day lag (Tuesday positions, Friday release); what got opened or closed is answered daily by exchange open interest, which never says who."*

| Panel id | Shows | Data | Cadence | Chart | How to read | Badge |
|---|---|---|---|---|---|---|
| `p.hero` | managed-money net (contracts · Moz · t · $bn), w/w change in words ("closed 3,777 longs, covered 894 shorts"), the fund-driver label (new longs / short covering / long liquidation / new shorts / funds sold into it / funds bought the dip), OI and ΔOI, "as of Tue 20 Oct · released Fri 23 Oct · next Sat 31 Oct 01:00 IST"; catch-up/stale flag during shutdowns | B1 `gold_cot_metrics` | weekly | hero numbers | [B] the funds' bet and what they did this week. [P] net = L − S; spreads excluded; right ≈ 3 weeks in 4 as narration; next-week correlation ≈ 0 | `context` ("explains the week — does not forecast") |
| `p.whois` | **who is long / who is short**: paired horizontal bars (long right, short left) per group — managed money, other reportables, non-reportable, swap dealers, producer/merchant — with Δ arrows and "closed longs / covered shorts / new longs / new shorts" chips; legacy groups behind a toggle | B1/B3 | weekly | SVG bars | [B] every long has a short; swap dealers are the banks' hedge of the OTC/ETF book. [P] categories are self-declared; reclassification looks like a flow | `context` |
| `p.history` | three stacked panels, one y-axis each: price (GC) · net by group (stacked bars) · managed-money COT index with 20/80 bands; ranges 1y/3y/10y/all; tooltip = the week's full decomposition | B1/B3, A1 | weekly | SVG | [P] the 2024-11 → 2026-03 doubling with funds cutting net length: the marginal buyer is outside the report | `context` |
| `p.crowd` | crowdedness gauge: 52-w COT index, z52/z156, net % OI, all-history percentile — worded "crowdedness, not a signal — no forecasting power 2006–2026 (G-STUDY)"; never coloured buy/sell | `gold_cot_metrics` | weekly | small gauge | | `context` |
| `p.decomp` | rally / decline decomposition: since the last 2-year low and since the high — Δ fund long/short/net, Δ commercial net (swap · producer), Δ other reportables, Δ small specs, ΔOI, ΔGLD | `gold_cot`, `gold_etf_holdings` | weekly | two rows | | `context` |
| `p.daily.comex` | daily COMEX OI by product (GC/MGC/1OZ/QO, OG calls/puts → P/C OI), ΔOI with price, quadrant tape (20 d), volume vs 20-d average, volume/OI churn; the roll (front vs next OI when C7 is allowed; product OI meanwhile) | C1 `gold_cme_daily_voi`, A1 | daily (≈15:30 IST, T+1) | stacked bars + tape | [B] "which positions got closed yesterday": OI down = positions closed. [P] T+1; mechanical on expiry/exercise days | `context` |
| `p.daily.mcx` | MCX OI by contract and expiry (lots), ΔOI, roll ratio front ÷ next, days to tender, 60-day stacked bars; "since 27 Oct 2026" | F1 `gold_curve` (MCX) | daily 07:35 | stacked bars + ladder | [B] where MCX liquidity sits and when it moves. [P] proxy settlement; no volume until F3 | `arithmetic` |
| `p.mcx.category` | monthly "who holds MCX gold" (FPI/DFI/prop/hedgers/others long vs short) — **dormant until a collector exists** (O-8); the panel shows the LINK and the reason | F4 `gold_mcx_category_oi` | monthly | bars | | `context` |
| `p.asia` | SHFE au front OI Δ; SGE Au(T+D) OI and settlement direction ("Short to Long = shorts pay the deferred fee = physical tightness") | D1, D3 `gold_asia_daily` | daily | line | | `context` |
| `p.drawer` | details: trader counts and average size, concentration ratios (top 4/8), micro gold (retail read), **options overlay line** ("options add +4,479 to funds' net; combined OI 532,443"), the raw CFTC block with the link to `deacmxsf.htm` and the API query, the footer "weekly, Tuesday positions, released Friday 15:30 ET; no daily, no OTC, categories only; our test found no timing value" | B1–B4, B7 | weekly | drawer | | `context` |

### a.7 PHYSICAL — premiums, flows, official sector, OTC

| Panel id | Shows | Data | Cadence | Chart | How to read | Badge |
|---|---|---|---|---|---|---|
| `ph.ladder` | **the India price stack** (the visual the owner asked for): COMEX spot/front → × USD/INR → landed ₹/10 g → + duty 15 % (dated: Notification 16/2026-Customs, 13 May 2026) → duty-paid landed → IBJA 999 PM (premium x %) → MCX front settle (basis y %, carry z %), timestamps under each bar; 995/999 adjustment stated | A1, F13, F9, F10, F1 · `/api/gold/premiums` | daily at the IBJA PM minute; live for the first three bars | waterfall | [B] what a rupee gold price is made of; where demand shows up. [P] synchronise timestamps or the premium is clock error (G-INDIA §5.3: NY close vs IBJA afternoon gave +0.9 %; Reuters saw ≈ +$3) | `arithmetic` (ladder) · `context` (premium) |
| `ph.india` | India premium history (IBJA vs duty-paid landed) with duty steps annotated (6 → 15 % on 13 May 2026); WGC weekly India premium (E8) and the Reuters link as sanity lines; MCX basis history | `gold_series` `INDIA_PREMIUM_PCT`, `MCX_BASIS_PCT`, `WGC_PREMIUM_IN` | daily | line | [B] above landed = local demand exceeds importable supply; below = discount (post-duty-hike inventory, smuggling, weak demand) | `context` |
| `ph.shanghai` | Shanghai premium ($/oz, %) from SGE PM vs LBMA PM / COMEX at 14:15 Beijing, with **both timestamps**; WGC weekly China premium as reference; SGE Au99.99 close, VWAP, volume | A11, D3, A9/A1, E8 | daily | line | [P] 7-hour gap SGE PM → LBMA PM; read changes and sign flips, not the level | `context` |
| `ph.etf` | GLD tonnes (daily since 2004) + daily Δ bars + 30-day cumulative; IAU tonnes; WGC weekly flows by region (NA/Europe/Asia/Other) and the India tonnes; top inflow/outflow fund | E1, E3, E5 · `gold_etf_holdings`, `gold_series` | daily / weekly (Mon) | line + bars | [B] Western investment demand; divergence (price up, tonnes down) = non-Western buying. [P] contemporaneous, no lead (G-STUDY, G-MACRO) | `context` |
| `ph.official` | official sector: top holders and last-month buyers from IMF (ounces, each with its data month), PBoC streak, RBI weekly value and share | E12, F11 | monthly / weekly | table | | `context` |
| `ph.otc` | OTC window: LBMA weekly turnover (12-wk MA, $bn, ≈ tonnes/week), London vault tonnes (monthly), CME EFP prints (today, 20-d avg, % of volume) | E14, E15, C2 | weekly / monthly / daily | `KV` + sparklines | [B] there is no COT for London; this is activity and stock, not positions. [P] gross, not netted | `context` |
| `ph.comex.stocks` | COMEX warehouse stocks and deliveries — **LINK-ONLY tiles** until O-2 (registered / eligible / pledged; coverage ratio with the front-month version beside it) | C8, C9 | — | link + explainer | | — |
| `ph.links` | linked (no free feed): PHYS, US Mint, SwissImpex dashboard, LBMA detail/Good Delivery, WGC GDT, SAFE, HK C&SD, Kitco | E4, E18, E19, E16, E10, E13, E20, A21 | — | list (the pre-open desk's manual-check component, moved, reduced) | | — |

### a.8 MACRO — why gold moved (the KGX idea, generalised)

| Panel id | Shows | Data | Cadence | Chart | How to read | Badge |
|---|---|---|---|---|---|---|
| `mc.drivers` | driver strip: 10-y real (bp Δ 1d/1w/1m, 1-y percentile), 2-y, breakeven, DXY %, USD/INR %, GVZ, Brent %, GLD t — each with a supportive/headwind tag and its 60-day correlation to gold's daily change | G1–G5, A5, A6, G9, E1 · `gold_series`, `gold_daily_bars` | daily / 60 s | `Stat` row | [B] the cost of holding gold (real yield) and the dollar explain most days. [P] contemporaneous betas (H1/H2); the level link broke in 2022 | `context` |
| `mc.kgx` | **"Gold or the dollar?"** bar for today / week / month: total = pure gold + USD effect (DXY weights) **+ a rupee leg** for MCX; gold USD vs gold-in-basket rebased, 1 y | A5 FX basket, A1 | daily | bar + line | [B] "gold rose $20; $12 was the dollar falling, $8 was buying" | `arithmetic` |
| `mc.ccy` | gold in USD / INR (landed ₹/10 g) / EUR / JPY / GBP / CNY — 1d / 1w / 1m / YTD; INR links to MCXG | A5, A1 | daily | table | [B] up in USD but down in EUR = it was the dollar | `arithmetic` |
| `mc.fed` | Fed path: Atlanta Fed per-meeting P(cut)/P(hike)/mean, ZQ implied Dec/Mar/Jun, EFFR, target range, next FOMC in IST (23:30 / 00:30 in winter — after the MCX close) | G16, G17, G6, G18 · `gold_fed_path` | daily | bars | [P] full distribution from SOFR options; FedWatch stays a link | `context` |
| `mc.calendar` | US calendar this week in IST with consensus/previous (actual when available); in-session (18:00–23:30 IST) vs after-close flag; links BLS/BEA | G19, G22 · `gold_events` | hourly | table | | `arithmetic` |
| `mc.move` | expected move: GVZ → 1σ day in %, $/oz, ₹/10 g, ₹ per lot for GOLD/GOLDM/GOLDTEN/GUINEA/PETAL; realised 20-d vol; ATR14 ₹ | A6/G8, `shared/mcx_specs` multipliers | daily | `KV` | [B] how big a normal day is, in rupees per lot you trade | `arithmetic` |
| `mc.health` | driver-health panel (weekly): rolling 1-y correlation of daily changes vs real yield and DXY; weekly betas by regime (2003–09 / 2010–21 / 2022–26) | `gold_series`, `gold_daily_bars` | weekly | small multiples | [P] the lesson of H1: since 2022 the real-yield rule explains a third of what it used to; the dollar never stopped working | `context` |
| `mc.context` | collapsed: gold/silver and gold/platinum with percentiles, gold vs real-yield scatter (5 y monthly), GPR daily/monthly percentile, HY OAS, gold/M2 | A3, G23/24, G12, G10 | daily / weekly | scatter, `KV` | | `context` |

### a.9 CONTRACTS — which contract, what it costs, when it rolls

| Panel id | Shows | Data | Cadence | Chart | How to read | Badge |
|---|---|---|---|---|---|---|
| `c.selector` | the three cascaded pickers (exchange × family × expiry) with a card per family: lot, quote unit, purity, expiry rule, next three expiries (observed from the master, computed fallback), tick value, OI by expiry, NRML margin ₹ and % (Zerodha mirror, dated), round-trip cost ₹ and %, breakeven ticks, "1 % move = ₹", delivery unit, tender-period start, broker tender cut-off (owner action), COMEX hedge ratio (GOLD ≈ 32 oz, GOLDM 3.2, TEN 0.32), options toggle (CE/PE, strikes, "an exercised option becomes the future"); a **diff strip** showing what changes when you switch (tick value, margin, cost %, liquidity, purity/settlement, hedge ratio); **replaces MCXG's specs card** | F1, F8, H3 · `/api/gold/contracts` | daily | cards + `DataTable` | [B] which contract for which purpose (G-INDIA §4.2 table: PETAL round trip 0.34 % of notional vs GOLD 0.018 %). [P] GOLD/GOLDM 995 settle on the 5th; TEN/GUINEA/PETAL 999 month-end; options expire before the future they settle into | `arithmetic` |
| `c.comex` | COMEX term structure (six months), ghost curve "1 week ago", calendar spreads, implied carry p.a., front-next OI (when C7), "last trade, not settlement" label; Dec-26 → Feb-27 +$41.1 = 1.03 % (3.2 %/yr) | A2, C7 (when allowed) · `gold_curve` COMEX | daily | dot-and-line SVG | [B] contango is the normal state; backwardation is news. [P] carry = (F2/F1 − 1) × 365/days; implied lease ≈ SOFR − carry | `arithmetic` |
| `c.mcx` | MCX chain: expiry · settle (proxy/official) · band · OI · ΔOI · implied carry; curve today vs a week ago; expiry flags; roll warning (front OI falling faster than next rising) | F1 `gold_curve` MCX | daily | `DataTable` | [P] MCX back months carry more (rupee rates, duty expectations) | `arithmetic` |
| `c.roll` | roll calendar: MCX expiries (GOLD DEC-26 Fri 4 Dec; GOLDM 5th; TEN/GUINEA/PETAL month-end), COMEX GCZ6 first intent 27 Nov · **FND 30 Nov** · LTD 29 Dec 12:30 CT (23:00 / 24:00 IST), 1OZ/QO LTD 25 Nov, broker tender cut-off (owner), the Pre-Open desk's month mapping (GCZ26 → GCG27 around 25 Nov while MCX Dec runs to 4 Dec) | C3, C4, `shared/mcx_specs`, `gold_events` | daily | list + countdown | [B] before first notice a long can be assigned delivery; speculators leave the front month in the two weeks before | `arithmetic` |
| `c.spec` | DES-style spec card for the matched COMEX contract: size, settlement method (physical / cash), tick, InitMargin and % of notional (daily), eligibility (EFP/block), margin history sparkline | C4 `gold_cme_prf`, `gold_margins` | daily | card | [P] GC 20,302 USD ≈ 5.1 % → 20× leverage; a 5 % move wipes the margin | `arithmetic` |
| `c.links` | linked: TradingView GC1!, CME FedWatch, CME contract pages, MCX circulars, QuikStrike/CVOL, DGCX, JPX | A25, C12, C13, F6, C10, D8, D7 | — | list | | — |

### a.10 LEARN — see §e.

---

## b. The compact WEI card, the BRF line, what leaves CMDT / MCXG and what stays

| Surface | Today | After (exact) |
|---|---|---|
| **WEI › Commodities › GC=F row** | last, Δ, Δ %, 1-month spark, day-range position, age | **unchanged row** + **one second line**: `GOLD · WEAK WEEK, DOLLAR-DRIVEN · basis +0.4 % · COT MM +104k (−2.9k) · roll DEC→FEB 25 Nov · GOLD ›` (verdict words truncated to 24 chars; from `/api/gold/health`, 60 s cache, no Breeze on the path). Hover card = the five-number header strip. Nothing else moves into WEI; the tooltip names the instrument ("Yahoo continuous front GC=F, not the Dec contract"). |
| **BRF › Market panel** | a full "Gold open (MCX)" panel (verdict, fair, baseline, gap, chase limit; after 09:15 "this morning's call") | **one `Line`**: before 09:00 `Gold open: fair ₹1,44,181 (gap −1,898) · WAIT · WEAK WEEK, DOLLAR-DRIVEN · GOLD ›`; after the captured open `Gold opened ₹1,42,058 vs fair ₹1,44,938 (miss ₹−2,880) · … · GOLD ›`; on MCX holidays `Gold: MCX closed (Dussehra, opens 17:00) · GOLD ›`. `Brief.tsx` stops calling `getGoldPreOpen`; it reads `/api/gold/health.line`. The panel rotation on the NSE 09:15 clock goes (finding 14). |
| **Macro tape (every page)** | "GOLD" = GC=F | label **"GOLD GC1"**; unchanged otherwise (a tape repeats quotes by design). |
| **CMDT** | Gold Pre-Open desk at the top + accuracy log + futures board + FRED/EIA legs | **drops `<GoldPreOpen />`** (CommodityTab.tsx line 259) and "· Gold desk" from label/hint/subtitle; the gold board tile gains a `GOLD ›` chip and its detail chart opens GOLD › WEEKLY; the FRED leg switches to the keyless `fredgraph.csv` (the key-required message goes); EIA leg unchanged. |
| **MCXG** | session clock, quote (contract/expiry selects), COMEX × rupee overlay (4 stats + prose), contract specs card (4 families), paper ticket | **keeps** session clock, holidays, Muhurat (fixed timings), quote with honest degrade, paper ticket (+ `max_lots_at_risk_pct`, `hedge_usdinr_lots`, `atr14_rupees`, margin from the Zerodha mirror with its date). **Overlay shrinks to one line** rendered from `/api/gold/health.fair`: `COMEX GCZ26 $4,004.3 · ₹/$ 94.93 · duty-paid landed ₹1,40,348 · fair ₹1,44,231 · live vs fair — · GOLD ›` (no implied-premium prose). **Specs card is replaced by the shared contract selector** (`c.selector`, same component, prefs-synced). Adds GOLDTEN. |
| **08:45 Telegram** | "GOLD DEC-26: fair open ₹X (+Y vs settlement ₹Z). Don't chase more than ₹300 above it." | same + "model miss so far: median ₹N over M days"; skips full and morning-closure MCX holidays; a Saturday COT digest line after the COT job ("COT 27 Oct: funds net +Xk (ΔY), long liquidation; OI Z"). |
| **ECO / EVTS** | no US CPI/NFP/PCE; no gold events | gains US CPI/NFP/PCE/GDP in IST (G19) and the gold-specific rows (COT release, COMEX FND/LTD, MCX expiries, Dhanteras, Diwali/Muhurat, Akshaya Tritiya, Budget, PIB/AMFI/WSS release days) — written once into `gold_events`, read by both pages. |
| **RSCH** | 84 studies, none gold | CATALOG rows (§d.4). |
| `GoldPreOpen.tsx`, `GoldAccuracyLog.tsx` | under `ui/components/` | moved to `ui/components/gold/`, composed by `GoldPage.tsx`; localStorage key `goldPreOpen.v1` kept so synced inputs survive; `eurusd_trigger` and the headline topic list become prefs (`gold.triggers.v1`), the "France / OAT" topic is dropped. |
| Pre-open desk manual checks (10 links) | CMDT | four become data (SGE, ETF flows, GLD, real yields); Fed odds becomes `mc.fed`; FedWatch, MCX circulars, FBIL, TradingView, Kitco move to `ph.links` / `c.links`; the investing.com USD/INR link is removed. |

---

## c. data-service: ingest jobs, DuckDB schemas, IST schedule, backfill

Conventions (from `storage/duckdb_store.py`): `CREATE TABLE IF NOT EXISTS` in the schema block, `INSERT OR REPLACE` via `_upsert(table, df, cols, casts)`, `store.checkpoint()` at job end, a row in `get_positions_meta()`, a `last_date()` allowlist entry. All timestamps UTC; `report_date` DATE in the publisher's calendar.

### c.1 Tables (19)

```sql
-- 1. the data dictionary as a table (drives the page's "about" popovers, freshness and the badge rules)
CREATE TABLE IF NOT EXISTS gold_series_catalog (
  series_id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, source_entry VARCHAR NOT NULL,  -- e.g. 'B1' (SOURCES.md)
  publisher VARCHAR NOT NULL, url VARCHAR NOT NULL, freq VARCHAR NOT NULL,              -- 'I' intraday | 'D' | 'W' | 'M' | 'Q'
  unit VARCHAR NOT NULL, publish_time_ist VARCHAR, lag_note VARCHAR,
  access VARCHAR NOT NULL,      -- FREE | FREE-KEY | FREE-REGISTRATION | PAID | BLOCKED | UNVERIFIED
  terms VARCHAR, verdict VARCHAR NOT NULL,  -- PUBLISH-CORE | PUBLISH-CONTEXT | LINK-ONLY | DO-NOT-PUBLISH
  verdict_reason VARCHAR, badge VARCHAR NOT NULL,   -- signal | context | arithmetic | heuristic
  evidence VARCHAR, beginner_note VARCHAR, pro_note VARCHAR, how_pros_use_it VARCHAR,
  resample VARCHAR NOT NULL DEFAULT 'last',          -- last | sum | mean
  ingest_job VARCHAR, max_age_days INTEGER NOT NULL, verified_at TIMESTAMP, verified_by VARCHAR);

-- 2. every single-value series, point-in-time
CREATE TABLE IF NOT EXISTS gold_series (
  series_id VARCHAR NOT NULL, report_date DATE NOT NULL, freq VARCHAR NOT NULL, value DOUBLE NOT NULL,
  release_at TIMESTAMP NOT NULL, release_source VARCHAR NOT NULL,   -- publisher | rule | fetch
  first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, quality VARCHAR NOT NULL,  -- official | derived | proxy
  revision INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (series_id, report_date, release_at));
-- read pattern: WHERE series_id=? AND release_at<=?asof QUALIFY ROW_NUMBER() OVER (PARTITION BY report_date ORDER BY release_at DESC)=1

-- 3. CFTC COT: raw payload + typed wide row + metrics view
CREATE TABLE IF NOT EXISTS gold_cot_raw (dataset VARCHAR NOT NULL, id VARCHAR NOT NULL, report_date DATE NOT NULL,
  contract_code VARCHAR NOT NULL, market_name VARCHAR, payload JSON NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (dataset, id));                                   -- id = YYMMDD + code + F/C (deterministic)
CREATE TABLE IF NOT EXISTS gold_cot (report_date DATE NOT NULL, contract_code VARCHAR NOT NULL,
  fut_or_combined VARCHAR NOT NULL,  -- 'F' | 'C'
  report VARCHAR NOT NULL,           -- 'disagg' | 'legacy'  (both stored; legacy fills 1986-2006)
  open_interest BIGINT, oi_chg BIGINT,
  nc_long BIGINT, nc_short BIGINT, nc_spread BIGINT, c_long BIGINT, c_short BIGINT, nr_long BIGINT, nr_short BIGINT,
  pm_long BIGINT, pm_short BIGINT, sd_long BIGINT, sd_short BIGINT, sd_spread BIGINT,
  mm_long BIGINT, mm_short BIGINT, mm_spread BIGINT, or_long BIGINT, or_short BIGINT, or_spread BIGINT,
  chg_nc_long BIGINT, chg_nc_short BIGINT, chg_c_long BIGINT, chg_c_short BIGINT, chg_nr_long BIGINT, chg_nr_short BIGINT,
  chg_pm_long BIGINT, chg_pm_short BIGINT, chg_sd_long BIGINT, chg_sd_short BIGINT, chg_sd_spread BIGINT,
  chg_mm_long BIGINT, chg_mm_short BIGINT, chg_mm_spread BIGINT, chg_or_long BIGINT, chg_or_short BIGINT, chg_or_spread BIGINT,
  traders_total INTEGER, traders_mm_long INTEGER, traders_mm_short INTEGER, traders_mm_spread INTEGER,
  traders_sd_long INTEGER, traders_sd_short INTEGER, traders_pm_long INTEGER, traders_pm_short INTEGER,
  traders_or_long INTEGER, traders_or_short INTEGER,
  conc_gross4_long DOUBLE, conc_gross4_short DOUBLE, conc_gross8_long DOUBLE, conc_gross8_short DOUBLE,
  conc_net4_long DOUBLE, conc_net4_short DOUBLE, conc_net8_long DOUBLE, conc_net8_short DOUBLE,
  release_at TIMESTAMP NOT NULL, release_source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (report_date, contract_code, fut_or_combined, report));
-- VIEW gold_cot_metrics: nets (contracts, Moz, t, $), Δ, % OI, net % OI, COT index 26/52/156 (in reports), z52/z156,
--   all-history percentile, options-only (C − F) per group, flow z, the four-quadrant label (price Tue→Tue from gold_daily_bars),
--   the fund-driver label (G-STUDY §5.1 rules), identity check c_long = pm_long + sd_long + sd_spread.

-- 4-7. CME FTP
CREATE TABLE IF NOT EXISTS gold_cme_daily_voi (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, product_code VARCHAR NOT NULL,
  product_desc VARCHAR, fut_or_opt VARCHAR NOT NULL, globex_volume BIGINT, pit_volume BIGINT, expit_volume BIGINT, otc_volume BIGINT,
  total_volume BIGINT, mtd_adv BIGINT, open_interest BIGINT, oi_change BIGINT,   -- oi_change derived vs the prior trade_date
  release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (trade_date, exchange, product_code, fut_or_opt));
CREATE TABLE IF NOT EXISTS gold_cme_efrp (process_date DATE NOT NULL, product VARCHAR NOT NULL, product_line VARCHAR,
  txn_type VARCHAR NOT NULL, contract_expiry VARCHAR NOT NULL, fut_or_opt VARCHAR, round_turns BIGINT NOT NULL, row_no INTEGER NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (process_date, product, txn_type, contract_expiry, row_no));
CREATE TABLE IF NOT EXISTS gold_cme_calendar (as_of DATE NOT NULL, exchange VARCHAR NOT NULL, symbol VARCHAR NOT NULL, mmy VARCHAR NOT NULL,
  first_trade DATE, last_trade DATE, ltd_end_time VARCHAR, settle_date DATE, first_intent DATE, last_intent DATE,
  first_notice DATE, last_notice DATE, first_delivery DATE, last_delivery DATE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (as_of, exchange, symbol, mmy));
CREATE TABLE IF NOT EXISTS gold_cme_prf (biz_date DATE NOT NULL, symbol VARCHAR NOT NULL, mmy VARCHAR NOT NULL, description VARCHAR,
  sec_type VARCHAR, uom VARCHAR, uom_qty DOUBLE, multiplier DOUBLE, min_px_incr DOUBLE, tick_incr_reg DOUBLE, settl_method VARCHAR,
  init_margin DOUBLE, maint_margin_field DOUBLE, mat_date DATE, first_trd DATE, last_trd DATE, first_notice DATE, last_notice DATE,
  last_efp DATE, elig_block BOOLEAN, elig_efp BOOLEAN, elig_efr BOOLEAN, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (biz_date, symbol, mmy));

-- 8. settlement curve per exchange per day (basis, term structure, roll, OI by contract) — source in the key so proxy and official coexist
CREATE TABLE IF NOT EXISTS gold_curve (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, settle DOUBLE, band_lo DOUBLE, band_hi DOUBLE, volume BIGINT, open_interest BIGINT,
  oi_change BIGINT, unit VARCHAR NOT NULL, source VARCHAR NOT NULL,   -- icici_master_band | mcx_bhavcopy | breeze_daily | cme_bulletin | yahoo
  quality VARCHAR NOT NULL, session_date DATE NOT NULL,                -- the SESSION the settlement belongs to (never the file date)
  release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, exchange, symbol, expiry, source));

-- 9. margins (Zerodha NRML mirror for MCX; CME InitMargin for COMEX)
CREATE TABLE IF NOT EXISTS gold_margins (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, symbol VARCHAR NOT NULL, expiry DATE NOT NULL,
  source VARCHAR NOT NULL, margin_ccy DOUBLE, margin_pct DOUBLE, ref_price DOUBLE, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, exchange, symbol, expiry, source));

-- 10-11. bars
CREATE TABLE IF NOT EXISTS gold_daily_bars (trade_date DATE NOT NULL, symbol VARCHAR NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE,
  close DOUBLE, adj_close DOUBLE, volume BIGINT, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (trade_date, symbol, source));
CREATE TABLE IF NOT EXISTS gold_bars_intraday (symbol VARCHAR NOT NULL, ts TIMESTAMP NOT NULL, interval VARCHAR NOT NULL,  -- '1m' | '5m'
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (symbol, ts, interval));            -- retention 400 days; backfill from 60d/5m on first run

-- 12. Shanghai (SGE spot/deferred, SHFE futures)
CREATE TABLE IF NOT EXISTS gold_asia_daily (trade_date DATE NOT NULL, exchange VARCHAR NOT NULL, contract VARCHAR NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, settle DOUBLE, vwap DOUBLE, volume_kg DOUBLE, turnover DOUBLE,
  open_interest BIGINT, oi_change BIGINT, direction VARCHAR, delivery_lots BIGINT, unit VARCHAR NOT NULL, source VARCHAR NOT NULL,
  release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (trade_date, exchange, contract, source));

-- 13. ETF holdings (GLD, IAU; GOLDBEES AUM monthly from AMFI goes to gold_series)
CREATE TABLE IF NOT EXISTS gold_etf_holdings (report_date DATE NOT NULL, fund VARCHAR NOT NULL, tonnes DOUBLE, ounces DOUBLE, shares BIGINT,
  nav DOUBLE, aum_usd_mn DOUBLE, premium_discount DOUBLE, release_at TIMESTAMP NOT NULL, first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL,
  PRIMARY KEY (report_date, fund, source));

-- 14. Fed path (Atlanta Fed MPT)
CREATE TABLE IF NOT EXISTS gold_fed_path (as_of DATE NOT NULL, meeting DATE NOT NULL, prob_cut DOUBLE, prob_hike DOUBLE, prob_hold DOUBLE,
  rate_mean_bp DOUBLE, rate_mode_bp DOUBLE, p10_bp DOUBLE, p90_bp DOUBLE, target_lo_bp INTEGER, target_hi_bp INTEGER,
  first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, PRIMARY KEY (as_of, meeting, source));

-- 15. the gold calendar (FOMC, US releases w/ consensus, RBI, COT release, COMEX FND/LTD, MCX expiry/holiday, Indian festivals, WGC/PIB/AMFI/WSS days)
CREATE TABLE IF NOT EXISTS gold_events (event_date DATE NOT NULL, time_ist VARCHAR, kind VARCHAR NOT NULL, name VARCHAR NOT NULL, detail VARCHAR,
  country VARCHAR, impact VARCHAR, forecast VARCHAR, previous VARCHAR, actual VARCHAR, in_session BOOLEAN, source VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (event_date, kind, name));

-- 16-18. pre-open log (migrates data/gold_preopen/log.json), briefs, daily health snapshot
CREATE TABLE IF NOT EXISTS gold_preopen_log (day DATE PRIMARY KEY, snapshot_at TIMESTAMP, contract VARCHAR, expiry DATE,
  baseline DOUBLE, baseline_source VARCHAR, baseline_session DATE, comex_symbol VARCHAR, comex_ref DOUBLE, comex_now DOUBLE,
  inr_ref DOUBLE, inr_now DOUBLE, fair_open DOUBLE, threshold DOUBLE, event_risk INTEGER, actual_open DOUBLE, actual_source VARCHAR,
  captured_at TIMESTAMP, error DOUBLE, naive_error DOUBLE, stale_baseline BOOLEAN, inputs_json VARCHAR);
CREATE TABLE IF NOT EXISTS gold_brief_docs (report_date DATE PRIMARY KEY, generated_at TIMESTAMP, schema_version VARCHAR, bias VARCHAR,
  bias_score DOUBLE, confidence DOUBLE, model_fair_open DOUBLE, open_signal VARCHAR, doc JSON NOT NULL, file_sha256 VARCHAR NOT NULL,
  first_seen_at TIMESTAMP NOT NULL);
CREATE TABLE IF NOT EXISTS gold_health_daily (day DATE PRIMARY KEY, snapshot_at TIMESTAMP NOT NULL, verdict VARCHAR, gauges JSON NOT NULL);

-- 19. MCX category-wise OI (dormant until a collector exists; schema fixed now)
CREATE TABLE IF NOT EXISTS gold_mcx_category_oi (as_of DATE NOT NULL, commodity VARCHAR NOT NULL, instrument VARCHAR NOT NULL,
  category VARCHAR NOT NULL, long_pos BIGINT, short_pos BIGINT, open_interest BIGINT, granularity VARCHAR NOT NULL,  -- 'day' | 'month'
  first_seen_at TIMESTAMP NOT NULL, source VARCHAR NOT NULL, PRIMARY KEY (as_of, commodity, instrument, category));
```

Dedupe rules: primary keys as above; a re-fetch of an unchanged value is a no-op; a revised value gets a later `release_at` (new row, `revision+1`) in `gold_series`, and a new `first_seen_at` + raw diff in `gold_cot_raw`. `gold_curve.session_date` is set by the ingest from the file's publish date minus one session (ICICI master) or the trade date (bulletin/yahoo).

### c.2 Catalog seed (the series_ids the page needs on day one)

| series_id | Source | freq | resample | publish_time_ist / rule | max_age_days | badge |
|---|---|---|---|---|---|---|
| `COMEX_GC_FRONT`, `COMEX_SI_FRONT`, `NYMEX_PL_FRONT`, `GLD_CLOSE`, `GOLDBEES_CLOSE`, `USDINR_CLOSE`, `DXY_CLOSE`, `FX_EURUSD`, `FX_JPY`, `FX_GBPUSD`, `FX_CAD`, `FX_SEK`, `FX_CHF`, `FX_CNY`, `GVZ_CLOSE`, `VIX_CLOSE`, `TNX_CLOSE`, `ZQ_FRONT` | A1–A6, G17 (`gold_daily_bars`) | D | last | 03:10 overnight (prior US session) | 4 | arithmetic |
| `UST_REAL_5Y … 30Y`, `UST_NOM_3M, 2Y, 10Y, 30Y` | G1, G2 | D | last | 02:00–03:00 IST (Treasury) | 4 | context / arithmetic |
| `FRED_DFII10` (+5/7/20/30), `FRED_DGS2`, `FRED_DGS10`, `FRED_T10Y2Y`, `FRED_T10YIE`, `FRED_T5YIFR`, `FRED_GVZCLS`, `FRED_VIXCLS`, `FRED_EFFR`, `FRED_SOFR`, `FRED_DCOILBRENTEU`, `FRED_HY_OAS`, `FRED_RRPONTSYD` | G3–G12 | D | last | ≈01:45 IST, one US business day late | 5 | context |
| `FRED_DTWEXBGS`, `FRED_DEXCHUS`, `FRED_WALCL`, `FRED_WTREGEN`, `FRED_WM2NS` | G7, G10 | W | last | Mon 16:15 ET (H.10); Thu (H.4.1) | 10 | context |
| `FRED_M2SL`, `FRED_CPIAUCSL`, `FRED_CPILFESL`, `FRED_PCEPILFE`, `FRED_PAYEMS`, `FRED_UNRATE`, `FRED_EXPINF10YR`, `FRED_MICH`, `GPR_MONTHLY`, `WB_GOLD_MONTHLY_AVG` | G10, G11, G4, G23, G26 | M | last | ~5th | 45 | context |
| `GPR_DAILY` | G24 | D | last | weekly file | 10 | context |
| `GLD_TONNES`, `IAU_TONNES` | E1, E3 (`gold_etf_holdings`) | D | last | ≈06:00 IST T+1 | 5 | context |
| `WGC_ETF_FLOW_T_GLOBAL`, `_NA`, `_EU`, `_ASIA`, `_OTHER`, `WGC_ETF_HOLD_T_GLOBAL`, `WGC_ETF_HOLD_T_IN`, `WGC_PREMIUM_IN`, `WGC_PREMIUM_CN` | E5, E8 | W | sum / last | Mon ≈11:30 for the week ended Fri | 10 | context |
| `WGC_SD_<category>` (mine, recycled, hedging, jewellery, technology, bar_coin, etf, central_banks, otc_other, lbma_avg_price) | E7 | Q | last | ~5 weeks after quarter end | 120 | context |
| `IMF_GOLD_OZ_<ISO3>`, `IMF_GOLD_USD_<ISO3>` (IND, CHN, RUS, TUR, POL, USA + top-20) | E12 | M | last | ~25th, 1–2 month lag | 60 | context |
| `LBMA_AM_USD`, `LBMA_PM_USD`, `SGE_AM_CNY_WGC`, `MCX_AM_INR_WGC` (provisional, O-1) | A9 | D | last | 21:30 | 4 | context |
| `SGE_SHAU_AM`, `SGE_SHAU_PM` | A11 | D | last | 16:10 | 4 | context |
| `SGE_WITHDRAWALS_KG`, `SGE_DELIVERY_RATIO` | D5 | M | last | ~10–12th | 45 | context |
| `LBMA_OTC_TURNOVER_USD_BN` (12-wk MA) | E14 | W | last | Friday-dated | 10 | context |
| `LBMA_VAULT_GOLD_T`, `LBMA_VAULT_SILVER_T` | E15 | M | last | ~20–25th | 45 | context |
| `IBJA_{999,995,916,750,585}_{AM,PM}`, `IBJA_SILVER_999_PM` | F10 | D | last | 13:45 / 18:10 | 4 | context |
| `USDINR_FBIL` | F13 | D | last | 13:45 | 4 | arithmetic |
| `GOLD_IMPORT_DUTY_PCT` (dated rows: 2024-07-24 6.0; 2026-05-13 15.0) | F9 | D (step) | last | on change | 400 | arithmetic |
| `RBI_GOLD_RESERVES_USD_MN`, `RBI_GOLD_RESERVES_INR_CR`, `RBI_RESERVES_TOTAL_USD_MN` | F11 | W | last | Fri 18:00 | 10 | context |
| `INDIA_GOLD_IMPORTS_USD_BN`, `SWISS_GOLD_EXPORT_IN_KG`, `AMFI_GOLD_ETF_NET_CR`, `AMFI_GOLD_ETF_AUM_CR`, `AMFI_GOLD_ETF_FOLIOS` | F14, E19, F16 | M | last | ~16th / ~22nd / ~11th | 45 | context |
| derived (job `gold_derive`, 18:15 and in overnight): `GOLD_INR_LANDED`, `GOLD_INR_DUTY_PAID`, `INDIA_PREMIUM_PCT`, `MCX_BASIS_PCT`, `MCX_BASIS_CARRY_ADJ_PCT`, `SHANGHAI_PREMIUM_USD`, `SHANGHAI_PREMIUM_PCT`, `COMEX_CARRY_ANN_PCT`, `KGX_USD_EFFECT_PCT`, `KGX_PURE_GOLD_PCT`, `GOLD_IN_<CCY>`, `GSR`, `GPR_RATIO`, `GVZ_SIGMA_DAY_PCT`, `ATR14_INR` | §10 of SOURCES.md | D | last | after inputs | 4 | per metric |

### c.3 Jobs and the IST schedule (master-controller → `POST /jobs/ingest-gold {"groups":[…]}` on data-service; idempotent groups; each group skips when not due; a series failure never fails the group)

| Job id (controller) | IST | Group(s) | Sources | Retry / notes |
|---|---|---|---|---|
| `gold_overnight` | 03:10 daily (Tue–Sat; Mon for Friday's US session) | `treasury`, `yahoo_daily`, `cme_voi_final`, `fred_daily` (if 21:30 missed), `calendar_us` | G1, G2, A1–A6, G17, C1 (final), G19, G22 | one Yahoo call per symbol with 6 s spacing (18 symbols ≈ 2 min); 429 → back off 5/10/20 min, STALE |
| `gold_intraday_bars` | every 5 min, 03:35 → 02:55 (04:35 → 03:55 after 1 Nov) | `bars_1m` | A1 `GC=F` + matched month (`7d/1m`), `INR=X`; D4 SGE during 06:30–13:00 and 17:30–00:00 IST | 2–3 calls / 5 min; writes `gold_bars_intraday`; never on the request path |
| `gold_morning` | 06:40 Mon–Sat | `etf`, `fed_path`, `gpr_daily` (Mon), `monthly_due` | E1, E3, G16, G24, and every `freq='M'`/`'Q'` series whose rule says it is due (E7, E12, E15, D5, F14, F16, E19, G10/G11, G23, G26) | the only place monthly series are fetched: a due check instead of a calendar |
| `gold_mcx_master` | 07:35 Mon–Fri (+ retry 08:35) | `mcx_master`, `margins` | F1 (conditional GET `If-Modified-Since`), F8 | writes `gold_curve` (MCX, proxy) with `session_date`, `gold_margins`; warms ui-api's master; **a fetch, not a restart** — allowed in the window |
| `gold_health_snapshot` | 08:40 Mon–Fri | `health` | reads ui-api `/api/gold/health` | writes `gold_health_daily` (for a later "did weak weeks behave differently" study) |
| `gold_preopen_snapshot` (exists) | 08:45 Mon–Fri | — | → `POST /api/gold/snapshot` (alias of today's) | **skips full and morning-closure MCX holidays** (`mcx_specs.trading_window`); alert text gains the measured miss |
| `gold_open_capture` (exists) | open + 10 min (09:10; 17:10 on morning-closure days) | — | → `POST /api/gold/capture-open` | holiday-aware; writes `gold_preopen_log` via `/jobs/gold-log` (dual-write with `log.json` for one release) |
| `gold_brief_ingest` | 09:05 daily | `brief` | H1 | schema-validated; sha256 dedupe |
| `gold_calendar_refresh` | hourly 09:00–23:00 | `calendar_us` | G19 | ForexFactory this-week JSON (cache; personal use); FOMC/RBI from `routers/markets.py` parsers moved to data-service |
| `gold_india_midday` | 13:45 Mon–Fri | `ibja_am`, `inr_ref` | F10 (AM table), F13 (RBI archive form; FBIL API when its format is known) | skip IBJA when "will be uploaded soon"; never backfill IBJA from the chart |
| `gold_cme_daily` | 15:45 Mon–Sat (+ retry 17:15) | `cme_voi`, `cme_prf` | C1 (`daily_volume.xlsx` → yesterday's trade date), C4 | `ftplib`, 20-s timeout; confirm the arrival hour in week one; derive `oi_change` |
| `gold_asia_close` | 16:10 Mon–Fri | `sge_daily`, `sge_benchmark`, `shfe` | D3 (date-range HTML table), A11 (`DayilyJzj` JSON + daily HTML), D1 (`kxYYYYMMDD.dat`) | SHFE non-trading days return a 404 HTML page → not an error; `bs4` html.parser |
| `gold_india_pm` | 18:10 Mon–Fri | `ibja_pm`, `derive_india` | F10 (PM table), then the derived India ladder at the IBJA PM minute (COMEX 5-min bar nearest 17:30 IST, FBIL rate) | before the 18:30 window |
| `gold_fred_daily` | 21:30 daily | `fred_daily`, `lbma_wgc` (A9, provisional), `cme_efrp` (C2), `derive_global` | G3–G6, G8, G9, G12; A9; C2; KGX/currencies/GSR/GVZ derived | FRED plain UA (browser UAs stall); after the 21:15 window |
| `gold_cot_weekly` | Sat 02:30 (hourly retries to 06:30); Mon 06:30 and Tue 06:30 catch-up | `cot` | B1–B4 (four datasets, `report_date > max(report_date)`; expect 2 rows/dataset: GOLD + MICRO), B10 for the next release row | 0 rows = "not yet"; 429 → sleep 60 s; stop when all four datasets carry the same new Tuesday; identity check per row; staleness banner at 10 days; Saturday Telegram digest line; extremes-only note (52-w index ≥ 90 / ≤ 10 or \|z156\| ≥ 2) worded as context |
| `gold_weekly` | Mon 12:00 (WGC after its ≈11:30 update); Fri 18:00 + Sat 10:30 (RBI, LBMA turnover, WGC premiums) | `wgc_etf`, `rbi_wss`, `lbma_turnover`, `wgc_premiums`, `fred_weekly` (Tue 03:10 H.10; Fri 03:10 WALCL/TGA) | E5, F11, E14, E8, G7, G10 | regex the LBMA page; RBI by Friday date (`SelectedDate=mm/dd/yyyy`) |
| `gold_cme_calendar` | Sun 04:00 | `cme_calendar` | C3 (38 MB) | weekly is enough; `iterparse`; keep each day's `as_of` |
| `gold_mcx_bhavcopy` (dormant) | 00:40 Tue–Sat | `mcx_official` | F3 via a browser-session collector | only after O-8; `gold_curve` source `mcx_bhavcopy`, quality `official` |
| `gold_mcx_category` (dormant) | 5th 10:00 | `mcx_category` | F4 | only after O-8 |
| `gold_breeze_daily` (ACTIVE since 6 Nov 2026, O-8 decided) | 09:35 Mon–Fri (the previous session's complete bars; after the 08:00 login, outside the freeze window) | `breeze_daily` | F2 `get_historical_data_v2(interval="1day")` per LIVE expiry, budget-ledger guarded, cap 15 | own table `gold_mcx_daily` (never `gold_curve`); live-verified 6 Nov: 5 codes, 15 contracts, 1,456 bars, OI matches the ICICI master |

Catch-up: add `gold_overnight`, `gold_cot_weekly`, `gold_mcx_master` to `_KEY_JOBS` so `startup_catchup` and `missed_jobs()` re-run them with `backfill_from`. Freshness: `get_positions_meta()` gains `gold_series` (worst series per the catalog), `gold_cot`, `gold_curve`, `gold_cme_daily_voi`, `gold_daily_bars`, `gold_etf_holdings`, `gold_preopen_log`, `gold_brief_docs`; `DATASET_MAX_AGE_DAYS` and `ui/components/NseDatasets.tsx` `MAX_AGE_DAYS`/`ABOUT` gain the same rows (COT 9 days — weekly plus a holiday shift; curve 4; bars 4; ETF 5; VOI 4). The WHSE panel and the 08:30 `pre_market_sync` freshness alert then cover gold with no new code path.

### c.4 Backfill plan (one-off, in this order; all free; paced)

| Table / series | Source | Rows | How | Time |
|---|---|---|---|---|
| `gold_cot*` | B1–B4 API (`$limit=50000`, ascending) or the seed CSVs in `G-COT/data/` and `G-STUDY/data/` | 1,939 + 1,648 + 1,063 + 1,063 (+ micro, Coinbase) | four calls, ~35 MB JSON (or `.csv` with `$select`); fallback the 44 zips | ~20 s |
| `gold_cme_daily_voi` | C1 archive `daily_volume_YYYYMMDD.xlsx` 2014-01-02 → today | 3,227 files | `ftplib`, 1 file / 2 s, resumable by date | ≈2 h, ~330 MB transient |
| `gold_cme_efrp` | C2 archive 2017-01-20 → today | 3,704 files | same pacing; GOLD rows only kept | ≈2 h |
| `gold_daily_bars` | A1–A6, G17 via `period1/period2` (G-MACRO's `fetch_yahoo_daily.py` pattern; its CSVs in `G-MACRO/data/` are a seed) | ~110k rows across 21 symbols | one call per symbol, 6 s apart, app UA | ~3 min |
| `gold_bars_intraday` | A1 `60d/5m` then `7d/1m` | ~20k | first run of `gold_intraday_bars` | minutes |
| `gold_series` FRED/Treasury | G1–G12 full CSVs (G-MACRO `data/fred_*.csv` seed) | ~150k | plain UA | ~2 min |
| `gold_etf_holdings` | E1 XLSX 2004→ (5,721 rows); E3 from today | 5.7k | one download | seconds |
| WGC weekly flows / premiums / balance sheet | E5 (2003→), E8 (255 weeks), E7 (66 quarters) | ~1.5k | three JSON calls, attributed, gated on O-1 | seconds |
| IMF official gold | E12 with `startPeriod=2000-01` for the top-20 holders | ~6k | one CSV call per batch of 6 countries | seconds |
| SGE benchmark / asia | A11 `DayilyJzj` 2016→ (2,553); D3 by date range (limit unknown — probe 30-day ranges); D1 per dated file (paced, from 2026-01) | ~3k | — | minutes |
| LBMA vault, SGE monthly, AMFI, Swiss, IMF | E15 (2016-07→), D5 (2026 PDFs), F16 (`G-INDIA/scratch/` has 81 months), E19 (current month only) | small | — | minutes |
| GPR, World Bank, Atlanta Fed | G23 (1985→), G24, G26 (1960→2024), G16 (2023→) | small | one file each | seconds |
| IBJA, ICICI master, RBI ref rate, RBI WSS | F10 (30 days on the page), F1 (today's file only — **history starts the day the job runs**), F13 (form by date range), F11 (by Friday date, back as far as the extract page serves) | — | — | — |
| `gold_preopen_log` | `data/gold_preopen/log.json` (4 rows) | 4 | migration with `inputs_json=NULL`, `stale_baseline` flagged by rule | seconds |

### c.5 Read endpoints (data-service, proxied by ui-api)

`GET /db/gold/series?ids=&from=&to=&asof=&freq=` · `/db/gold/cot?weeks=&report=` · `/db/gold/cme/voi?from=&products=` · `/db/gold/cme/efrp?from=` · `/db/gold/curve?exchange=&date=` · `/db/gold/margins?date=` · `/db/gold/bars?symbol=&interval=&from=` · `/db/gold/asia?from=` · `/db/gold/etf?from=` · `/db/gold/fed-path?asof=` · `/db/gold/events?from=&to=` · `/db/gold/log?days=` · `/db/gold/brief?date=` · `/db/gold/catalog` · `/db/gold/health-daily?from=`. `POST /jobs/ingest-gold`, `POST /jobs/gold-log`. `asof` defaults to now; resampling (`last|sum|mean`) comes from the catalog.

### c.6 Fetch etiquette and the host allowlist (enforced by test T8)

Allowed hosts for the gold package: `query1.finance.yahoo.com`, `query2.finance.yahoo.com` (app UA only), `publicreporting.cftc.gov`, `www.cftc.gov` (files), `ftp.cmegroup.com`, `home.treasury.gov`, `fred.stlouisfed.org` (fredgraph.csv, plain UA), `api.spdrgoldshares.com`, `www.ishares.com`, `fsapi.gold.org` (gated on O-1), `api.imf.org`, `cdn.lbma.org.uk`, `www.lbma.org.uk` (two pages, regex), `en.sge.com.cn`, `www.sge.com.cn`, `www.shfe.com.cn`, `ibjarates.com`, `www.rbi.org.in`, `directlink.icicidirect.com`, `zerodha.com` (one page/day), `portal.amfiindia.com`, `pib.gov.in`, `ocean.nivel.bazg.admin.ch` (monthly), `www.atlantafed.org`, `nfs.faireconomy.media`, `www.bea.gov`, `www.matteoiacoviello.com`, `thedocs.worldbank.org`, `api.gold-api.com` (≤ 1/min), `news.google.com` (existing). Everything else is refused by the client wrapper. Rate: ≥ 1.2 s between requests to the same host; 20-s timeouts; browser-like UA except FRED (plain) and Yahoo (app UA); failures → the Telegram `info` channel like the gold snapshot.

---

## d. ui-api endpoints and JSON contracts (`services/ui-api/routers/gold.py`, mounted at `/api/gold`)

Rules: compose, never re-implement (`gold_preopen` for the fair-open model and `_yahoo_bars_cached`; `mcx` for the Breeze quote path; `shared/mcx_specs` for sessions/expiries/costs; data-service `/db/gold/*` for stored series). Caches: `SWRCache("gold.store", max_items=256, refresh_after=120, max_age=900)` for stored reads; `TTLCache("gold", 64)` with `health` 60 s, `catalog` 3600 s, `overview` 30 s; the Breeze path keeps `QUOTE_TTL_S=15` and the 10-minute broken memory; `POST /api/gold/invalidate` after a job. Warm: `("gold_overview", gold.overview)` in `routers/_cache_warm.warm_calls`. Responses: `as_of` (IST ISO), per-block `freshness {source, as_of, age_s, state: live|delayed|stale|unavailable}`, the `errors.py` envelope (`fail` / `degraded`). Numbers are numbers. Compatibility: `/api/commodity/gold-preopen*` stay as aliases for one release.

| Endpoint | Returns (shape) |
|---|---|
| `GET /api/gold/overview?contract=&expiry=&window=D\|W\|M` | `{as_of, contract{mcx, expiry, expiry_source, comex_matched, comex_front, spot_proxy_note, lot, tick_value}, session{mcx{is_open, opens_at, closes_at, holiday}, comex{is_open, note}}, strip{comex_matched_settle, comex_live, usdinr, real_10y, mcx_settle, mcx_settle_session, basis_pct, cot_mm_net, cot_mm_chg, cot_as_of, crosscheck{price, at}}, health{…as /health}, fair{…as /fair}, quote{…as /api/mcx/quote}, headlines[], brief{available, report_date, bias, confidence, overnight_summary, open_plan, key_risks_today[]}, calendar[], freshness{}}` |
| `GET /api/gold/health?window=` | `{as_of, window, verdict{line, clauses[{text, rule_id, series_id, value, threshold}]}, gauges[{key, label, value, unit, change, change_window, report_date, release_at, age_days, state, direction_for_gold, rule, percentile_1y, percentile_3y, series_id, source, badge, evidence}], fair{fair_value, mcx_live, premium_rupees, premium_pct, comex, usdinr, landed, duty_pct, duty_effective, duty_paid_landed, basis_pct, settlement, settlement_session}, line, freshness{state, oldest, age_days}}` — **no `score` field** (§f) |
| `GET /api/gold/fair?baseline=&mcx_price=&threshold=&contract=&expiry=` | today's `/api/commodity/gold-preopen` body + `baseline.session_label`, `accuracy{days, median_abs_error, mean_abs_error, p90, within_threshold_pct, naive_mean_abs_error, bias}`, `holiday{closure, note}`, `badge:"heuristic"` on `verdict`; `eurusd_trigger` and topics come from prefs (query only if set) |
| `GET /api/gold/series?ids=&from=&to=&freq=D\|W\|M&asof=` | `{as_of, asof_applied, freq, series[{series_id, name, unit, freq_native, quality, resample, points[{report_date, value, release_at}], catalog{publisher, verdict, badge, lag_note, terms}}]}` |
| `GET /api/gold/bars?symbol=&interval=1m\|5m\|1d&from=&to=` | `{symbol, interval, bars[{ts, o, h, l, c, v}], sessions[{name, start_ist, end_ist}], settle_line{value, label}, prev_day[{ts, c}]}` |
| `GET /api/gold/cot?weeks=52&report=disagg&fut_or_combined=F` | `{as_of, latest{report_date, release_at, next_release_ist, stale}, open_interest{total, chg, pct_rank}, groups[{key, label, long, short, spread, net, net_moz, net_t, net_usd_bn, chg_long, chg_short, chg_net, pct_oi_long, pct_oi_short, net_pct_oi, traders_long, traders_short, who_did["closed 3,777 longs", …]}], driver_label, quadrant_label, week_price_chg_pct, crowd{cot_index_26, cot_index_52, cot_index_156, z52, z156, percentile_all, label:"crowdedness, not a signal — no forecasting power 2006–2026 (G-STUDY)"}, options_overlay{mm_net_options_only, combined_oi, line}, history[{report_date, price, mm_net, or_net, nr_net, sd_net, pm_net, oi, cot_index_52}], decomposition[{span, price_from, price_to, d_mm_long, d_mm_short, d_mm_net, d_comm_net, d_sd_net, d_pm_net, d_or_net, d_nr_net, d_oi, d_gld_t}], drawer{traders, concentration, micro_gold, raw_block_url, api_query}, badge:"context", footer}` |
| `GET /api/gold/positioning/daily?exchange=COMEX\|MCX&days=60` | `{exchange, rows[{trade_date, symbol_or_product, expiry, open_interest, oi_change, volume, settle_or_close, quality}], quadrant_tape[{trade_date, dprice_pct, doi, label, mechanical: bool}], roll{front, next, ratio, days_to_tender_or_fnd}, since}` |
| `GET /api/gold/curve?exchange=COMEX\|MCX&date=` | `{exchange, date, points[{expiry, settle_or_last, source, quality, open_interest, volume, days_to_expiry, spread_vs_front, annualised_carry_pct}], ghost_1w[], basis{mcx_front_inr, landed_inr, duty_pct, duty_paid_landed_inr, basis_pct, carry_pct, basis_carry_adj_pct, usdinr, usdinr_source, ts}, history[{trade_date, basis_pct, premium_pct}]}` |
| `GET /api/gold/contracts?exchange=MCX` | `{families[{code, breeze_code, lot, quote_unit, purity, expiry_rule, expiries[{expiry, source, settle, band_lo, band_hi, oi, oi_change, margin_inr, margin_pct, margin_source, margin_date, carry_pct, comex_matched, tender_start, days_to_tender}], tick_value, round_trip{legs, total, pct, breakeven_ticks}, one_pct_move_inr, hedge_ratio_oz, delivery_unit, options{available, expiries[], strike_step}}], diff_keys[]}` |
| `GET /api/gold/premiums?days=365` | `{india{ladder[{step, label, value, ts, source}], premium_pct, basis_pct, carry_adj_pct, duty{pct, effective, notification}, history[]}, shanghai{sge_pm_cny_g, usdcny, usdcny_source, sge_usd_oz, london_pm_usd, comex_at_1415_bj, premium_usd, premium_pct, ts_sge, ts_ref, history[]}, reference{wgc_india, wgc_china, reuters_url}}` |
| `GET /api/gold/flows?months=24` | `{etf[{report_date, fund, tonnes, chg_1d, chg_5d, chg_1m}], wgc_weekly[{week_ending, region, flow_t, flow_usd_bn, holdings_t}], wgc_countries[], official[{country, month, oz_mn, tonnes, chg_oz_mn}], rbi{week, usd_mn, share_pct, tonnes_est}, otc{lbma_turnover_usd_bn, week_ending, vault_t, vault_month, efp{today_rt, avg_20d, pct_of_volume}}, physical_monthly{sge_withdrawals_kg, india_imports_usd_bn, swiss_exports_in_kg, amfi{net_cr, aum_cr, tonnes_est}}, balance_sheet[{period, series, tonnes}]}` |
| `GET /api/gold/macro?window=` | `{drivers[{key, value, unit, d1, d1w, d1m, pct_1y, corr_60d, tag, series_id}], kgx{period, total_pct, pure_gold_pct, usd_effect_pct, inr_effect_pct, weights{}}, currencies[{ccy, price, d1, d1w, d1m, ytd}], fed{meetings[{meeting, p_cut, p_hike, p_hold, mean_bp}], zq[{month, implied_pct}], effr, target, next_fomc_ist, after_mcx_close: bool}, calendar[{date, time_ist, title, country, impact, forecast, previous, actual, in_session}], move{gvz, sigma_day_pct, usd_oz, inr_10g, per_lot{GOLD, GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL}, realised_20d, atr14_inr}, driver_health{rolling_corr[{year, real_yield, dxy}], betas_by_regime[]}, context{gsr, gsr_pct, gpr_pct_m, gpr_pct_d, hy_oas, gold_m2_pct}}` |
| `GET /api/gold/calendar?days=30` | `gold_events` rows with `days`, `time_ist`, `in_session` |
| `GET /api/gold/log?days=60&threshold=` · `POST /api/gold/log/actual` | today's accuracy-log shapes from the table (+ `stale_baseline`, `inputs_json`) |
| `GET /api/gold/catalog` | `gold_series_catalog` rows (also rendered to `docs/GOLD_DATA_DICTIONARY.md`) |
| `GET /api/gold/brief?date=` | the stored brief and its `data_quality` block |
| `GET /api/gold/learn/glossary?q=` · `GET /api/gold/learn/tooltips` | `glossary.json` search; `tooltips.json` |
| `POST /api/gold/snapshot` · `POST /api/gold/capture-open` | today's semantics, holiday-aware, dual-writing to the table |

Other router changes (B3): `mcx.py` → `MASTER_ALIASES`/`BREEZE_CODE` gain `GOLDTEN`/`GOLDTE`; `_fair_value` calls `gp._yahoo_bars_cached`; `/api/mcx/overlay` returns the one-line block; the ICICI master loader uses `If-Modified-Since` (keep the publish-date logic for the session label); `/api/mcx/ticket` adds `max_lots_at_risk_pct`, `hedge_usdinr_lots`, `atr14_rupees`, `margin_source`. `gold_preopen.py` → `baseline.session_label`, `holiday`, prefs-driven triggers, `inputs_json` in the snapshot, duty leg (`landed`, `duty_paid_landed`, `basis_pct` replace `implied_premium_pct`, which stays as a deprecated alias for one release). `commodity.py` → keyless FRED, no desk. `shared/mcx_specs.py` → `GOLDTEN` (10 g, ₹/10 g, 999, month-end, tick ₹1 = ₹1/lot), Muhurat row (Sun 8 Nov 2026 14:05–14:19 special, 14:20–15:30 trading, circular MCX/TRD/590/2026), `DUTY_HISTORY` (dated), `margin_source="zerodha_nrml"`. `shared/config.py` → `GOLD_IMPORT_DUTY_PCT` (default 15.0, `GOLD_IMPORT_DUTY_EFFECTIVE=2026-05-13`), `CFTC_APP_TOKEN` (optional). `research.py` CATALOG → `reports/gold_program/FINDINGS.md` ("Gold", "FAIL"/"REFERENCE" rows), `docs/GOLD_DATA_DICTIONARY.md` ("Gold", "REFERENCE"), `reports/gold_program/SOURCES.md`, `PLAN.md`, `G-EDU/CURRICULUM.md` ("Gold", "REFERENCE"), `G-STUDY/FINDINGS.md` ("Gold", "FAIL" — as a signal; PASS as description), `G-INDIA/REPORT.md` (G-INDIA-1 FAIL), `G-COT/REPORT.md`, `G-CME/REPORT.md`, `G-KITCO/REPORT.md`, `G-APP/REPORT.md`, `G-LOGIN/REPORT.md` (nested paths are not auto-discovered).

---

## e. The LEARN view and glossary

- **Content:** `reports/gold_program/G-EDU/CURRICULUM.md` (1,260 lines: Part 0 health check; 1 units/purity/products; 2 venues and the rupee price build; 3 futures mechanics; 4 players; 5 drivers and regimes 2001–2025; 6 reading the data; 7 advanced — carry/GOFO, options skew, term-structure trades, cross-exchange, event playbooks, sizing, risk rules; 8 panel micro-copy; 9 daily/weekly/monthly routines; appendices formulas, IST clock, evidence ledger), rendered through the existing research document viewer (`routers/research.py` serves markdown from `reports/` read-only) inside GOLD › LEARN with a section index, collapsible parts and "open the view that uses this" links. Required additions before shipping (B5): (1) the **duty section** rewritten for 15 % since 13 May 2026 (CURRICULUM §2.6 still reasons from 6 %); (2) Part 8 **rename pass** to the panel ids of §a (Appendix B); (3) the **evidence ledger** replaced by SOURCES.md §11; (4) a "what is not free and where to click" list (LBMA, CME www, MCX, Kitco, Bloomberg/LSEG); (5) the Bloomberg function map (G-KITCO Appendix C) as a table "what a Bloomberg gold trader looks at → where it is here"; (6) the health-verdict rule table (every clause of `h.verdict` with its threshold) — the owner can audit the sentence.
- **Glossary:** `glossary.json` (129 terms: `term`, `short` ≤ 200 chars, `long`, `see_also`, cross-references validated by `build_glossary.py`) served by `/api/gold/learn/glossary`; a right-hand side panel with a search box, reachable from every dotted-underlined term and from the `?` on each panel; `see_also` as links. Add terms found missing by the synthesis: GOLDTEN, AIDC, Due Date Rate, EFP price vs volume, FND/LTD, registered/eligible/pledged, Au(T+D) direction, KGX rupee leg, point-in-time, `signal/context/arithmetic/heuristic`.
- **Tooltips:** `tooltips.json` (93 one-liners keyed by payload field) loaded once in `ui/lib/gold/` and attached via the kit's `title` props on `Stat`/`Chip`/`Column.label` by field name; a node check asserts every rendered gold field has a key and every key is used.
- **[B]/[P] layers:** the toggle in a.1 switches the micro-copy per panel (CURRICULUM Part 8 "Reads / Is not / Updates / Evidence" format); the [P] line carries the exact formula from SOURCES.md §10.
- **Routines:** Part 9's daily / weekly / monthly checklists become three collapsible lists at the top of LEARN with deep links (the "days, weeks, months" the owner asked for, as a reading order).

---

## f. Usefulness labelling rules (binding)

1. **Vocabulary.** `signal` — a pre-registered study (PLAN.md before results) PASSED as a forecast: |t| ≥ 2 in the full sample and the same sign with |t| ≥ 2 in both halves, after the project cost floor; recorded as a PASS row in `reports/gold_program/FINDINGS.md`. **None today.** `context` — PASS as a description (same-week relation) or context-only verdict; the chip text names the study and date ("context · G-STUDY 26 Oct 2026: no forecasting power"). `arithmetic` — an identity, cost or spec (fair value, landed cost, carry, tick value, KGX split); no claim about the future. `heuristic` — a house rule without evidence (₹300 chase limit, headline risk count); the chip carries the measured error where one exists.
2. **Rendering gate.** A panel renders only if every `series_id` it reads has a `gold_series_catalog` row with a `verdict` of PUBLISH-CORE or PUBLISH-CONTEXT and a `badge`; otherwise the panel shows "no verdict — not published" (dev builds) or is hidden (release). `pages.check.ts` enforces the catalog-field mapping statically; `test_gold.py` enforces it at the API.
3. **No colours for context.** Context metrics render in the neutral token; up/down arrows are allowed, green/red only for price changes and the `arithmetic` fair-vs-live comparison. No "bullish/bearish" words on a context metric; "supportive/headwind" is allowed only on the MACRO driver strip with the rule shown.
4. **No composite.** No score, no "N of 7", no tightness index. The health verdict is a sentence of thresholded clauses and ends "describes, does not predict".
5. **Promotion.** A badge changes from `context` to `signal` only by a FINDINGS.md PASS row from a study whose PLAN.md predates its results and whose data is PIT (`release_at`). The Decision Desk and the paper ticket stay decoupled even then until the owner approves separately (CLAUDE.md "Trading Rules").
6. **Repetition is a defect.** The same number appears once per page; the WEI line and the BRF line are the only off-page echoes; the tape repeats quotes by design.
7. **Honesty chips.** `STALE` when older than the catalog's `max_age_days`; `PROXY` on the ICICI band-midpoint settlement; `LAST TRADE` on Yahoo per-month prices until bulletin settlements are allowed; `PROVISIONAL` on A9 until O-1.

---

## g. ICICI auto-login (BRKR "Enable auto-login")

Status (G-LOGIN, verified 26 Oct 05:40 IST): the code already does zero-touch TOTP end to end (`shared/icici_login.py`, `scripts/daily_session_refresh.py`), unit-tested against the RFC 6238 vectors (16 passed); **the only missing piece is the secret** — `ICICI_TOTP_SECRET` is in neither `.env` nor the Keychain; `.env` is 0644; the 08:00 job is scheduled and untouched; the last login (23 Oct 08:08) went through the SMS-via-Telegram path after an 08:05 timeout.

**Today (owner, §i O-4):** get the setup key (Option A, official: icicidirect.com Settings → Disable Login Authenticator (PIN) → Login Authenticator → Google Authenticator → scan the QR **and** copy the "manually enter the provided key" text; re-add on the phone. Option B: export from Google Authenticator and decode the `otpauth-migration://` QR offline on this Mac), store it in the Keychain — `security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w` (prompted; nothing in argv/history) — `chmod 600 .env`, and run the one attended test after 15:40 (not 07:30–09:30): `/Users/sudheer/Desktop/jupyter_env/bin/python scripts/daily_session_refresh.py --force` → expect `code panel: totp` → `submitted authenticator code (single attempt)` → `RESULT refreshed`. If ICICI rejects the code, quote the wording (not the screenshot) — it is either a wrong secret or the inferred Submit handler (R1). Tomorrow 08:00: Telegram "ICICI session refreshed" with no OTP prompt.

**Phase 2 (B3 + B4 + B2), the BRKR panel "Auto-login (TOTP)"** on `PortfolioSummary.tsx`, rendered in both connected and not-connected layouts, kit only:

| Step | UI | Backend |
|---|---|---|
| Status strip | chip `TOTP CONFIGURED · Keychain` / `· .env` / `TOTP NOT SET` (amber); "08:00 job: enabled · next Mon 08:00 · last: 23 Oct 08:08 refreshed via ui-api"; `.env is 0644 — run chmod 600 .env` warning; cyan `AUTO-LOGIN RUNNING · since 08:00:03` while a login runs (hides the "send /login" sentence); `TOTP MISMATCH — re-register` chip after M1 | `GET /api/positions/totp/status[?reveal=1]` → `{configured, source: env|keychain|null, env_mode, auto_login_enabled, login_running, otp_pending, last_login{at, status, detail}, next_run_ist, block{credentials, totp}}`; with `reveal=1` the current `code` and `seconds_left` computed server-side (never the secret) |
| Step 1 · get the key | the three lines of Option A + `OPEN ICICI SETTINGS ↗` (`openExternal`) + FAQ links (I1) | — |
| Step 2 · paste the key | one monospace `Input` (`type=password`, SHOW toggle, accepts base32 or `otpauth://`), debounced 400 ms → live "Current code 482 913 · 17 s" with a 30-s bar; "open Google Authenticator: the ICICI entry must show the same six digits; wait for one rollover" | `POST /api/positions/totp/preview {secret}` → `{valid, digits, period, algorithm, length, code, seconds_left}`; stores nothing, logs nothing; 400 messages never echo the value |
| Step 3 · confirm and save | 6-digit confirm box + `SAVE`; on success the input is cleared from React state; a copy box with the Keychain one-liner + `DETECT` | `POST /api/positions/totp {secret, confirm_code}` → refuse unless `confirm_code` equals the current or previous-window code; normalise to bare base32; `persist_env_updates({"ICICI_TOTP_SECRET": b32}, allowed_keys=ICICI_ENV_KEYS)` with **`ICICI_TOTP_SECRET` added to `ICICI_ENV_KEYS`** (icici_admin.py:90); warn if `.env` is not 0600 |
| Step 4 · test | `CHECK SESSION / LOG IN IF EXPIRED` → "Started — watching…" → poll `/status` every 5 s up to 8 min + `/api/positions/connection-status` → `● LIVE`; secondary confirm-gated `FORCE A NEW LOGIN (ends today's session)` only when `force` is supported, disabled 09:00–15:30 with a hover reason, and warned when a credentials block file exists | `POST /api/telemetry/icici-refresh {force?}` → server-side proxy to `POST {MASTER_CONTROLLER_URL}/api/scheduler/icici-refresh[?force=1]` (the webview is pinned to :8010; the controller has no CORS by design); controller change: `?force=1` → `_run_session_refresh(("--force",))` (one line) |
| Remove | `DISABLE AUTO-LOGIN` (confirm) | `DELETE /api/positions/totp` → writes `ICICI_TOTP_SECRET=` through the guarded writer; reports `keychain_still_present` (ui-api never runs `security delete-…`) |

Hardening shipped with it (G-LOGIN §5.3, §9): **M1** on "ICICI rejected the authenticator code" write `.icici_totp_block.json` (fingerprint of the secret) so unattended runs fall back to SMS until the secret changes, with the Telegram hint "the TOTP secret no longer matches ICICI: re-register and update it on BRKR" (owner decides Q6 whether to fall back automatically); **M3** log the `security` return code ("TOTP: keychain rc=36 (locked?)"), never the value; **R1** when `mode == "totp"` prefer clicking the panel's visible Submit button, fall back to `submitotp()`; controller `_mark_failed(JOB)` on rc 2 and after the rc 3 retry (today rc 2 shows "done" in SYS); the `"OTP" in detail` hint check must not misfire on "TOTP"; `data/icici_otp*.json` added to `.gitignore`; `is_credentials_rejection` recognises a rejected authenticator code; retire `scripts/icici_session_helper.py` (bare-regex `.env` writer). Deploy order: secret first (no restart), ui-api change any time except 07:55–08:10, controller change outside both freeze windows (e.g. 16:00–18:15), attended test, then leave the 08:00 job alone. Security: Keychain preferred (encrypted, ACL to `/usr/bin/security`, not in repo backups — add the one-liner to `docs/RUNBOOK_RESTORE.md` §2 LOGIN-CRITICAL); `.env` with the seed is a complete login → 0600 and the password-manager copy treated accordingly; no secret in query strings, logs, Telegram, screenshots or prefs; the preview POST stays on loopback.

---

## h. Tests and gates

| # | Gate | What | Pass condition |
|---|---|---|---|
| T1 | Unit, ui-api (`services/ui-api/tests/test_gold.py`, new) | data-service mocked; health verdict rules (stale gauges excluded; sentence ends "describes, does not predict"; **no `score` key**); as-of resampling D/W/M; catalog-driven rendering gate; holiday gating of snapshot/capture (20 Oct morning closure → skip 08:45, capture 17:10); session label ("Thu 22 Oct settlement" from Friday's file); duty leg (15 % dated; `basis_pct` vs `implied_premium_pct` alias); aliases to `/api/commodity/gold-preopen*`; GOLDTEN in `/api/gold/contracts`; `mcx._fair_value` uses the cached fetcher (assert one Yahoo call) | pytest green; `test_gold_preopen.py` + `test_mcx.py` (49 tests) untouched and green |
| T2 | Unit, data-service (`tests/`) | PIT as-of query returns the vintage not the revision; `INSERT OR REPLACE` dedupe on re-fetch; `source`-in-key coexistence of proxy and official curve rows; COT identity check; `gold_cot_metrics` COT index/z on reports not days; Treasury vs FRED same-date equality | green |
| T3 | **Ingest replay from stored samples** (`tests/gold_replay/`) | every parser runs against the agents' saved bodies: `G-COT/data/*.csv` + `scratch/` raw pages, `G-CME/samples/` (daily_volume xlsx ×10, efrp csv, calendar csv, prf csv, SHFE/SGE/JPX json/xlsx, Wayback xls/pdf for the dormant parsers), `G-PHYSICAL/samples/` (134 payloads: fsapi JSONs, GLD xlsx, IMF csv, SGE html, LBMA xlsx, RBI html, IBJA html, AMFI txt, SGE pdf), `G-MACRO/data/` + `samples/` (FRED csv, Treasury csv, Atlanta Fed xlsx, ForexFactory json, GPR xls, World Bank xlsx, Yahoo json), `G-INDIA/scratch/` (AMFI xls ×81, RBI extract, Zerodha html, IBJA html), `G-KITCO/scratch/bodies/` (Yahoo chart JSON for 1m/5m/1wk/max — asserts the `range=max` monthly trap is detected) | each parser yields the row counts and sample values quoted in SOURCES.md (e.g. COT 20 Oct OI 402,279; GC OI 403,397 on 22 Oct; GLD 1,045.64 t; IBJA 999 PM 1,41,630; IMF CHN 76.73 Moz Aug-26) |
| T4 | Study-reproduce (`tests/test_gold_study_reproduce.py`, marked slow) | re-run `G-STUDY/g_study.py` on `G-STUDY/data/` and assert: same-week Spearman(Δ MM net, price) = 0.65 ± 0.02; 0 of 69 rules with OOS t ≥ 2; Dec/Jan the only months with t ≥ 2; re-run `G-MACRO/g_study.py` on `G-MACRO/data/`: H2 weekly DXY beta between −0.8 and −1.3 with t ≤ −2 in every regime (−1.23 / −1.02 / −0.97 / −1.01, t −11.6 / −13.2 / −6.4 / −14.4) and H3 no month passing both halves; `G-INDIA/scratch` AMFI: ρ(flow → next) = 0.115 ± 0.02 | green; proves the FINDINGS rows are reproducible before the badges rely on them |
| T5 | `scripts/tests/` (controller) | holiday-aware job gating; conditional-GET master loader (304 path); `?force=1` passes `--force` (fake); cross-site refusal still holds; `_mark_failed` on rc 2; missed-jobs lists the gold ids | green |
| T6 | `services/ui-api/tests/test_icici_totp_routes.py` | preview with the RFC vector at a frozen clock returns `287082` for t=59; bad base32 → 400 whose body does not contain the input; save refused without the matching confirm code; save writes exactly one line and keeps 0600; refused through the allowlist until the key is added (regression); no route returns the secret except `preview.code`; + `tests/unit/test_icici_login.py` cases for a 16-char key in groups of four and an `otpauth://` with `%20` | green |
| T7 | UI checks (`ui/components/__tests__/pages.check.ts`, `ui/lib/__tests__/*.check.ts`) | health line contains "describes, does not predict"; signed numbers use U+2212; one unit per column; the four instrument labels are distinct strings; every gold field has a tooltip key; glossary `see_also` resolves; the BRKR panel chip text per `source` and the 09:00–15:30 disabling rule; context metrics use the neutral token | `node` checks green; `npx tsc --noEmit` |
| T8 | **Host allowlist** (`tests/test_gold_hosts_allowlist.py`) | static scan of `services/data-service/gold/` and `routers/gold.py` for URLs: every host ∈ §c.6; forbidden hosts (`www.cmegroup.com`, `mcxindia.com`, `kitco.com`, `prices.lbma.org.uk`, `stooq.com`, `goldprice.org`, `investing.com`) absent; FRED REST (`api.stlouisfed.org`) absent unless `FRED_API_KEY` is read | green |
| T9 | **Repetition test** | static: exactly one component renders `GoldPreOpen`; `GC=F` chart fetch helpers in ui-api remain the existing four (no fifth) and `routers/gold.py` imports `_yahoo_bars_cached` only; `Brief.tsx` has no `getGoldPreOpen` call; `CommodityTab.tsx` has no `GoldPreOpen`; runtime (ui_audit): the string "fair open" appears on ≤ 1 panel per page | green |
| T10 | `scripts/ui_audit.py` | default `TABS` + `gold` (16/16); `--tabs all --browser both` 43/43; zero console errors; failed requests only platform seams | green |
| T11 | `scripts/ui_perf.py` | nothing to edit; tab-switch p95 ≤ 400 ms for `gold`; first-load gz ≤ 300 KB (lazy page; no new chart library) | green |
| T12 | Desktop gates | `cargo test && cargo clippy --all-targets && cargo fmt --check` with `PAGE_COUNT = 43` and the three asserts updated; `node desktop/scripts/boot_check.mjs`; `scripts/desktop_qa/parity.py` with `gold` declared as an expected program delta (42 PARITY + 1); `probe.py` chip == `GOLD`; `run_selftest.py --live` on the installed app | green |
| T13 | Live acceptance (first week) | the arrival hour of `daily_volume.xlsx` logged; COT job finds 31 Oct's release by Sat 03:30 IST; `gold_mcx_master` writes Monday's file at ≈07:35 with `session_date` = Friday; IBJA AM/PM both captured; the Telegram COT digest line arrives Saturday; `/api/gold/health` serves within 60 s cache with no Breeze on the path | owner reads the Saturday digest and the first GOLD page with real rows |
| T14 | Docs | `docs/RUNBOOK_RESTORE.md` ("15/15 ok" → 16/16; Keychain one-liner in §2), `CLAUDE.md` ("42 pages" → 43; GOLD page in Key Files; gold jobs in the freeze-window note), `docs/IMPROVEMENT_LOG.md` entry, `docs/GOLD_DATA_DICTIONARY.md` generated from the catalog and equal to SOURCES.md's verdicts | parsers and docs agree |

---

## i. Owner actions (ordered; nothing below is done by builders)

| # | Action | Why / when |
|---|---|---|
| O-1 | **Terms posture** for WGC (`fsapi.gold.org` JSON: no scraping/redistribution without authorisation), SPDR (XLSX disclaimer: no reproduction/redistribution), IBJA (`/terms` 404; paid API exists), SGE/SHFE (licensed distributors listed): choose (a) private single-user display with attribution, 1 fetch/day, nothing re-served (the plan's default), (b) free Goldhub registration for the sanctioned XLSX route, or (c) written permission. Kitco = links only regardless. | gates E1, E5, E7, E8, A9; decide before S1 ships |
| O-2 | **CME block**: open `https://www.cmegroup.com/markets/metals/precious/gold.volume.html` in a normal browser; if blocked, email gcc@cmegroup.com stating personal, non-commercial use (the block message invites it); then rule whether a once-daily download of three public files (warehouse XLS, issues/stops PDF, bulletin PDF) is acceptable personal use given the Data Terms forbid automated means. Until then C7–C10 are LINK-ONLY; the FTP route stands. Also: find which process on this IP hit cmegroup.com (the repo never did). | before S2's physical panel |
| O-3 | **Confirm the duty** at CBIC in a browser (Notification 16/2026-Customs: BCD 10 % + AIDC 5 % since 13 May 2026; the site's TLS chain is broken for scripts) and confirm the fortnightly tariff value practice; set `GOLD_IMPORT_DUTY_PCT=15` and the effective date in `.env`. | the 18 % "premium" is unreadable until this is dated |
| O-4 | **TOTP today** (§g): get the setup key (Option A or B), `security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w`, `chmod 600 .env`, attended `daily_session_refresh.py --force` after 15:40, check tomorrow's 08:00 Telegram line; add the Keychain line to RUNBOOK §2; decide Q1 (Keychain vs `.env` form), Q5 (`?force=1`), Q6 (fallback after a TOTP mismatch). | the owner's explicit "autologin icici" |
| O-5 | **Approve the page and the consolidation**: code `GOLD`, nine sub-views, CMDT drops the desk, BRF one line, WEI one extra line + hover, MCXG one-line overlay + shared selector, tape label "GOLD GC1", the labelling rules (settlement by session; `heuristic` chip on the chase limit; no score). | S1 |
| O-6 | **Approve the DuckDB tables (§c.1), the IST schedule (§c.3) and the backfills (§c.4)** — in particular the one-off CME FTP backfill (≈2 h, 330 MB transient) and the Yahoo history pull (one call per symbol). Every history starts the day its job starts: approving early is the cheapest decision in this plan. | S1 |
| O-7 | **Optional keys/registrations**: free Socrata token → `CFTC_APP_TOKEN=`; free `FRED_API_KEY` (unlocks ALFRED vintages for PIT studies; not needed for the CSV path); free Goldhub account (if O-1 chooses b); BEA UserID (not needed). | any time |
| O-8 | **Bot-blocked publishers**: decide whether a Playwright persistent-profile collector (one visit per evening, identifiable) for MCX bhavcopy / option chain / the monthly category-wise OI workbook is acceptable under MCX's site terms for a personal terminal; and whether to authorise a one-off Breeze historical pull of MCX GOLD/GOLDM daily OHLC+OI per expiry (credentialed) so G-STUDY can be re-run on the instrument actually traded. After an 08:00 login, live-verify the five Breeze codes (`GOLD`, `GOLDMI`, `GOLDTE`, `GOLDGU`, `GOLDPE`) and daily bars with OI. | S2; the dormant jobs |
| O-9 | **ICICI tender cut-off and delivery status** for MCX GOLD/GOLDM (not in the repo): the date decides when a swing position must be rolled; put it on the selector card. | S1 CONTRACTS |
| O-10 | **Read two licences by eye**: the Atlanta Fed MPT `LICENSE` sheet (not machine-readable) and the SPDR disclaimer — before `mc.fed` and `ph.etf` go live. | S2 |
| O-11 | **One browser session** to capture the XHR URLs for SHFE's daily warehouse stocks and HK C&SD's gold-trade table id (adds SHFE vault stocks and HK→China flows); optionally read the two ICICI community posts (TOTP lockout rule). | later |
| O-12 | **Today 08:45**: check the gold pre-open Telegram alert — G-KITCO's probes contributed to a Yahoo 429 at 06:04; if the snapshot 503'd, the accuracy log skips a day (type the open manually if needed). | today |
| O-13 | **Pre-register the studies** (B7) by approving their PLAN.md files before any result is looked at: G-STUDY-2 (daily OI quadrant 2014→, NW, both halves), GS-P1 (GLD daily tonnes 2004→), GS-P2 (WGC weekly flows 2003→), GS-P4 (seasonality in rupees — run 26 Oct 2026: VOID / FAIL, drift not a calendar), GS-P5 (IMF monthly CB buying; not yet pre-registered, waits for the monthly ingest), and the two that wait for history (GS-P3 SGE premium + Au(T+D) OI; G-INDIA OI matrix after 60 sessions; GS-PREMIUM after 2 years). Ids: `reports/gold_program/STUDIES.md`. | S5 |
| O-14 | **Approve the Telegram changes**: 08:45 wording with the measured miss and holiday skipping; the Saturday COT digest line; extremes-only COT note worded as context; no gold alert implies direction. | S1 |
| O-15 | Decide whether silver (084691) and copper (085692) ride along in the COT job (zero cost, same table) and whether SI/SIL/SIC stay in `gold_cme_daily_voi` (they do by default — the gold/silver ratio needs them). | S1 |

---

## j. Risks and open questions

### j.1 Risks (with the mitigation built into the plan)

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Yahoo throttling (429)** takes the page down; the 08:45 snapshot already depends on fresh Yahoo bars | one fetcher, app UA, ≤ 6 calls/min, `period1/period2`; data-service stores history; every panel degrades to the last stored bar with STALE; the snapshot keeps `FRESH_ONLY` but the page does not |
| R2 | **Terms** (WGC, SPDR, IBJA, SGE, Kitco, CME): displaying licensed numbers | display-only on a private terminal with attribution, nothing re-served, O-1 decision, allowlist test T8, `PROVISIONAL` chip on A9 |
| R3 | **CME IP block** spreading to the FTP host or to other CME properties | never touch `www.cmegroup.com` from the stack; FTP paced (1 file / 2 s, 20-s timeouts); O-2 resolves the block properly |
| R4 | **MCX history has no official path**; the proxy settlement (band midpoint) could diverge from the real one | `quality='proxy'` visible; `session_date` correct; official rows coexist in the key when O-8 unblocks; Breeze daily bars as a second source |
| R5 | **The duty is wrong** (15 % rests on secondary sources; Budget 2027 may change it) | dated constant, O-3 confirmation, `DUTY_HISTORY` rows; the ladder prints the rate and its notification on every render |
| R6 | **The fair-open model is weak** (2–3 rows, misses ₹2.9–3.5k; a stale-baseline case; `inr_now == inr_ref` days) | `heuristic` chip, measured miss on the alert, `inputs_json` per row for audit, stale-baseline flag, re-decide the limit at 20 rows; the 15 Oct anomaly is an open question (j.2 #9) |
| R7 | **Readers treat context as a forecast** (COT index lore, health verdict, quadrant labels) | §f rules; the sentence ends "describes, does not predict"; no colours; no score; evidence chips name the study; LEARN explains the FAIL |
| R8 | **Point-in-time violations** (WGC quarterly revisions; IMF stale months repeating; CFTC republications; FRED revisions) | `release_at` keys; raw COT payload kept and diffed; IMF `TIME_PERIOD` check; ALFRED when `FRED_API_KEY` exists |
| R9 | **Clock errors in the premiums** (IBJA afternoon vs NY close; SGE PM vs LBMA PM 7-hour gap; Yahoo CNY missing a day) | sample inputs at the fix minute (5-min bars), both timestamps shown, FBIL rate for India, PBOC/FRED DEXCHUS fallback for CNY, WGC weekly lines as sanity |
| R10 | **DST/GMT switches** (UK 25 Oct done; US 1 Nov: MCX 23:55, COT Sat 02:00, FOMC 00:30, US data 19:00) | `shared/gold_sessions.py` DST-aware bands; `gold_events` times computed per date; the COT job's retry window covers both |
| R11 | **TOTP**: the Submit handler is inferred (R1 of G-LOGIN); a stale secret retried daily; Keychain locked → silent SMS fallback | attended `--force` test; R1 hardening; M1 block file; M3 rc logging; one attempt per run |
| R12 | **Breeze REST budget / ui-api event loop** (every 60-s poll after 09:00 can wait 10–15 s on a 1-min-bar call; the 3 MB master re-downloaded all weekend) | one background bar fetch per minute, never on the request path; conditional GET; `loop_stall` WARNING already exists |
| R13 | **Scope**: ten agents proposed ~60 panels | slices S1–S5; every panel has a verdict row; S1 is four sub-views |
| R14 | **43-page gates** (parity has no A side; perf budgets; `PAGE_COUNT` asserts) | B6 owns the touch points; `gold` declared as an expected program delta |
| R15 | **"Other reportables"** (+95,659 net, opaque) and category drift make the COT narrative wrong | the strip shows all five groups; LEARN explains the bucket; no inference about who they are |
| R16 | **Two agent reports were never written** (G-PHYSICAL, G-MACRO: the harness refused) — their evidence is on disk, their prose only in the orchestrator's summaries | the orchestrator should materialise both summaries as `REPORT.md` (verbatim) before the CATALOG rows are added; SOURCES.md already carries their findings |

### j.2 Open questions (owner unless marked)

1. Does the MCX monthly category-wise OI workbook carry daily rows or month-end rows? (one browser download, F4)
2. Which Breeze calls work for MCX today — `get_quotes` (500 on 12 Oct), `get_historical_data_v2` daily with `open_interest`, the `GOLDTE` code? (after an 08:00 login, outside the freeze)
3. The exact MCX Due Date Rate wording for GOLD/GOLDM vs the 999 month-end families (spec behind the block).
4. FBIL `wasdm/refrates/fetch` parameter format (500 for every format tried); is the RBI archive form stable enough daily?
5. Does the Swiss `TN8_EXP` zip carry 7108.1200 at 8-digit granularity with India as a partner row, and in which unit? (first monthly run)
6. The meaning of the CME product-reference `MaintMargin` field (1,400 for GC) and whether `InitMargin` is the speculator or hedger rate (CME margin page once reachable).
7. Bulletin "deliveries settled to-date 3,208" vs Issues & Stops "MTD 13,479" for Oct-26 gold: different definitions (bulletin legend).
8. The FTP server clock time zone → the exact IST arrival of `daily_volume.xlsx` (first week of ingest, T13).
9. Why did the 15 Oct snapshot miss by ₹3,518 while COMEX rose 1.7 % overnight and MCX opened 0.65 % below settlement — the band-midpoint settlement, the 23:30 reference window, or the first 1-minute Breeze bar used as the open? (needs `inputs_json`)
10. Does ForexFactory's this-week JSON ever carry an `actual` field after a release? (none of 96 events had one on Monday morning)
11. Which currency basket for the published KGX bar — DXY weights (replicable, Europe-heavy) or Fed broad weights (includes CNY/INR, weekly lag)? Plan default: DXY + a separate rupee leg.
12. Where is the current World Bank CMO monthly file (the documented URL ends Dec 2024)?
13. Is Yahoo's per-month last price acceptable as the curve until bulletin settlements are allowed? (23 Oct: 4,001.30 vs 4,007.90) Plan default: yes, labelled LAST TRADE.
14. The CFTC's 2027 release calendar (not yet published; re-check in December and load it into `gold_events`).
15. Literature citations in the reports (Sanders–Boris–Manfredo 2004; Sanders–Irwin–Merrin 2009; Kang–Rouwenhorst–Tang 2020; Hong–Yogo 2012; Erb–Harvey 2013; Baur–Lucey 2010; Baur 2013; Moskowitz–Ooi–Pedersen 2012) are from memory or SSRN-blocked pages — verify before quoting in LEARN.
16. ICICI's SEBI static-IP notice for API trading "from 1 April 2026" — applies to order placement only? an IP registered? (irrelevant in PAPER, relevant before LIVE)
17. Should the TOTP mismatch (M1) fall back to SMS automatically on later mornings or stop and wait?
18. The SGE monthly PDF's CN weekly report links are JS-generated — is a weekly withdrawals series obtainable?
19. The G-EDU curriculum's duty section and Part 8 names need the rename/rewrite pass (B5) — who signs it off?
20. Whether the gold accuracy log should also store the full 1-minute open window (first 10 minutes) so "the open" can be defined by rule later.

---

## Appendix A — the 43rd-page touch points (B4/B6)

`ui/app/page.tsx` (the `Tab` union, `TAB_IDS`, `COMMAND_PAGES` entry `{id:'gold', code:'GOLD', label:'Gold terminal', hint:…}`, `lazyTab('gold', …)`, the render `case`) · `ui/components/shell/tabModules.ts` (loader) · `ui/components/desktop/pages.ts` (code + label; header comment "42" → 43) · `desktop/src-tauri/src/pages.rs` (`PAGES`, `PAGE_COUNT` 42 → 43, three `assert_eq!(…, 42)` → 43, group coverage) · `ui/lib/goAliases.ts` (`XAU`, `GC`, `GPHY`, `GMAC`, `LRN`, `COT`) · `scripts/ui_audit.py` default `TABS` (+ `gold`) · `scripts/desktop_qa/parity.py` expected deltas · `docs/RUNBOOK_RESTORE.md`, `CLAUDE.md`, `reports/desktop_app/FEATURE_PARITY.md`. `scripts/desktop_qa/pages.py` parses `page.tsx` and `pages.rs` and raises if they disagree; `scripts/ui_perf.py` cross-checks `TAB_IDS` vs `COMMAND_PAGES` automatically.

## Appendix B — G-EDU Part 8 panel names → this plan's panel ids (the rename pass)

8.1.1 verdict → `h.open` (verdict) · 8.1.2 key numbers → `h.open` · 8.1.3 gap build-up → `h.open` waterfall / `h.moved` · 8.1.4 inputs → `h.open` · 8.1.5 context table → `mc.drivers` · 8.1.6 headlines → `h.headlines` · 8.1.7 manual checks → `ph.links` + `c.links` · 8.1.8 accuracy log → `h.accuracy` · 8.1.9 session clock → MCXG (unchanged) · 8.1.10 quote → MCXG · 8.1.11 overlay → MCXG one-line + `ph.ladder` · 8.1.12 specs → `c.selector` · 8.1.13 ticket → MCXG ticket (+ sizing) · 8.1.14 WEI row → WEI card · 8.1.15 BRF panel → BRF line · 8.1.16 CMDT board → CMDT tile · 8.2.1 health strip → header strip + `h.gauges` · 8.2.2 COT → `p.hero`, `p.whois`, `p.crowd`, `p.drawer` · 8.2.3 daily OI × price → `d.quadrant`, `p.daily.comex`, `p.daily.mcx` · 8.2.4 warehouse → `ph.comex.stocks` · 8.2.5 ETF → `ph.etf` · 8.2.6 OTC window → `ph.otc` · 8.2.7 premium monitor → `ph.ladder`, `ph.india`, `ph.shanghai` · 8.2.8 drivers → `mc.drivers`, `mc.move`, `mc.health` · 8.2.9 central banks → `ph.official`, `m.official` · 8.2.10 term structure → `c.comex`, `c.mcx` · 8.2.11 chooser + calendar → `c.selector`, `c.roll`, `h.events` · 8.2.12 events calendar → `h.events`, `mc.calendar` (+ ECO) · 8.2.13 Kitco-style chart → `d.24h`, `d.3day` · 8.2.14 periodicity switch → the `window` param + WEEKLY/MONTHLY views.

## Appendix C — acceptance checklist against the owner's words

- [ ] CFTC COT futures and options: weekly who-is-long/short with who-closed-what, options overlay line, Saturday digest (`p.*`)
- [ ] Daily "which position got closed": COMEX product OI tape (T+1) and MCX OI per contract (07:35) with the opened/closed read (`d.quadrant`, `p.daily.*`)
- [ ] Health check: five-number strip, eight gauges, descriptive verdict; no score (`h.*`)
- [ ] Kitco-like chart with IST, MCX hours, previous-day overlay, settle line, session bands, 3-day overlay (`d.*`); Kitco itself a link
- [ ] OTC: LBMA turnover, London vaults, CME EFP tape (`ph.otc`)
- [ ] Supply/demand: balance sheet, ETF flows, central banks, premiums, imports (`ph.*`, `m.*`)
- [ ] Days / weeks / months: stored histories, `freq=D|W|M`, WEEKLY and MONTHLY views, Part 9 routines
- [ ] Separate visual: one new page GOLD; repeated information removed per §b and T9
- [ ] World-market tabs: WEI one-line card + hover; BRF one line
- [ ] Choose the contract: selector with GOLDTEN, economics, OI ladder, roll calendar, matched COMEX month (`c.*`)
- [ ] Auto-login ICICI: today's owner steps + the BRKR panel (§g)
- [ ] Basic → sophisticated: [B]/[P] layers, LEARN, glossary, tooltips (§e)
- [ ] Publish only what is useful: SOURCES.md verdicts; §f badges; nothing without a verdict renders
- [ ] Think like a Bloomberg gold trader: DES/CT/CCRV/COT/GIP equivalents named in LEARN and built from free data
