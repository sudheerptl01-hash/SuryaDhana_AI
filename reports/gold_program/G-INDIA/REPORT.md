# G-INDIA — India gold market structure and MCX positioning: free sources, verified live

**Agent:** G-INDIA (SuryaDhana GOLD program) · **Verified:** Monday 26 Oct 2026, 05:40–06:30 IST, from the owner's Mac (egress IP country = IN) · **Repo touched:** nothing outside `reports/gold_program/G-INDIA/` · **Live services, ICICI credentials, Telegram:** not touched.

**Scratch evidence:** `reports/gold_program/G-INDIA/scratch/` (saved pages, the AMFI monthly files 2020-01→2026-09, `amfi_gold_etf_study.csv`, `amfi_study_results.json`, `landed_23oct.json`, the PyPI sources of `mcxlib 0.4` and `mcxpy 0.0.3`, the RBI WSS extract of 23 Oct 2026).

---

## 0. Verdict board (read this first)

| # | Item (brief) | Best free source | Access from this machine | Verdict | One-line reason |
|---|---|---|---|---|---|
| 1a | MCX daily bhavcopy (settle, volume, OI per contract) | mcxindia.com `backpage.aspx/GetDateWiseBhavCopy` | **BLOCKED** (Akamai 403 to every scripted client, even from an Indian IP; also 403 from the fetch proxy) | PUBLISH-CORE **once a working collector exists**; today LINK-ONLY | The one dataset that answers "what got built/closed yesterday". Two legal workarounds exist (browser-automation download; ICICI's public master already gives settle + OI daily). |
| 1b | Participant / category-wise OI (FPI, DFI, prop, hedgers, others, long vs short) | mcxindia.com `docs/default-source/market-data/historicaldata/{yyyy}/{month}/category-wise-oi-{mon}-{yyyy}.xlsx` | **BLOCKED** (403) | PUBLISH-CONTEXT (monthly file, when collected) | It is published as a **monthly** workbook, not a daily report; "who is long/short" by category is only knowable at that cadence. |
| 1c | SPAN / risk-parameter files | mcxccl.com (403) → mirror: Zerodha commodity margin table (200) | mirror FREE | PUBLISH-CONTEXT (margin per contract, daily) | Zerodha republishes the exchange NRML margin every day (25 Oct 2026: 9.25% on every gold contract). Good enough for paper sizing; not the SPAN file itself. |
| 1d | MCX spot price polling (Ahmedabad 995) | mcxindia.com spot-market-price | **BLOCKED** | LINK-ONLY | IBJA's two daily fixes are the practical, free Indian spot reference; MCX's polled spot matters only for expiry (DDR). |
| 1e | Expiry / settlement circulars | mcxindia.com `GetCircularAdvanceSearch` | **BLOCKED**; broker republications FREE | LINK-ONLY (+ keep `shared/mcx_specs.py` hand-maintained) | Muhurat 2026 circular found via a compliance republisher: **MCX/TRD/590/2026 (19 Oct 2026): Sun 8 Nov, 14:05–14:19 special session, 14:20–15:30 trading** — the app's note "evening timings by circular" is now wrong. |
| 2 | ICICI Breeze gold contracts, expiries, lots, bands, OI | ICICI public `SecurityMaster.zip` (the app already caches it) | FREE, no login (HEAD 200, 2.99 MB, Last-Modified Fri 23 Oct 07:28 IST) | PUBLISH-CORE | Five futures families (GOLD, GOLDM, **GOLDTEN**, GOLDGUINEA, GOLDPETAL) + options on GOLD and GOLDM futures. GOLDTEN is tradable on ICICI but missing from `mcx_specs.CONTRACTS`. |
| 3a | Customs duty on gold | CBIC notification (primary unreachable: broken cert chain) → tax-law republishers | FREE (secondary) | PUBLISH-CORE (one number, with its date) | **15% since 13 May 2026** (BCD 10% + AIDC 5%, Notification 16/2026-Customs of 12 May 2026; was 6%). The app's "landed (no duty)" and "+17.4% implied premium" conflate duty with premium. |
| 3b | IBJA daily AM/PM rates (999/995/916/750/585, silver, platinum) | ibjarates.com | FREE (page scrape; the JSON API is paid) | PUBLISH-CORE | The reference India spot: SGB redemption prices and bank loans key off it. 23 Oct 2026 PM 999 = ₹1,41,630/10 g. No history beyond ~30 days on the page → store it daily. |
| 3c | Retail premium / discount to landed | Reuters "Asia Gold" weekly (news) · compute your own | LINK-ONLY / derived | PUBLISH-CONTEXT (derived series) | No free official series exists. Derive: IBJA 999 PM − duty-paid landed at the same timestamp. 23 Oct 2026: +0.9% (indicative; timestamp sync matters, see §5.3). Reuters: discount up to $6/oz (9 Oct) → premium up to $3/oz (late Oct). |
| 3d | GST, hallmarking, making charges | cbic-gst.gov.in (200), bis.gov.in (200) | FREE | PUBLISH-CONTEXT (glossary card only) | 3% GST on gold, 5% on making; 6-digit HUID mandatory since 1 Apr 2023. Static facts, not data. |
| 4a | RBI gold reserves (weekly value) | RBI WSS Table "Foreign Exchange Reserves" (old-site extract page) | FREE (200, 1.2 s) | PUBLISH-CONTEXT (weekly) | As on 16 Oct 2026: gold **US$105,800 mn** (+706 mn w/w; −9,595 mn since end-Mar 2026) of US$721,016 mn total → 14.7%. Tonnes only half-yearly/annual (880.52 t at 31 Mar 2026). |
| 4b | Sovereign Gold Bonds | RBI press releases (200) | FREE | PUBLISH-CONTEXT (link + formula) | No new issuance since Feb 2024; only premature-redemption prices, which are the 3-day average of **IBJA 999 PM** (verified in PR 2026-2027/1060). Nothing to trade on MCX from this. |
| 4c | Rupee reference rate | RBI Reference Rate Archive (form POST, 200) · FBIL JSON API (HTTP 500) | FREE / UNVERIFIED API | PUBLISH-CONTEXT (one daily number) | USD/INR 94.9432 on 23 Oct 2026 (FBIL fix ~13:30 IST). The app already shows Yahoo INR=X live; the fix is only needed to timestamp the landed-cost calculation. |
| 5a | Monthly gold imports (commerce ministry / DGCI&S) | PIB monthly trade release (~15th) · tradestat.commerce.gov.in (form) | FREE | PUBLISH-CONTEXT (monthly) | Sept 2026: **US$1.8 bn, −81% YoY**; Apr–Sep US$19.27 bn (−27%) after the duty hike. One number a month; lag ~15 days. |
| 5b | Swiss exports to India (cross-check) | opendata.swiss BAZG "by tariff number / country" monthly since 1988 | FREE (692 MB zip, Last-Modified 20 Oct 2026) | PUBLISH-CONTEXT (monthly) | Bulk file, filter HS 7108.12 × India. Heavy; monthly job only. |
| 6a | Festival / wedding / monsoon calendar | panchang + IMD | FREE (static dates) | PUBLISH-CONTEXT (calendar rows in ECO/MCXG) | Dhanteras Fri 6 Nov 2026, Diwali Sun 8 Nov (Muhurat), Akshaya Tritiya was Sun 19 Apr 2026. Context, not a signal (no study shows a tradable MCX effect; literature: an "autumn effect" in USD gold, Baur 2013, is small and unstable). |
| 6b | AMFI gold-ETF monthly flows | portal.amfiindia.com `am{mon}{yyyy}repo.xls` | FREE (81 of 81 months fetched, 200) | PUBLISH-CONTEXT · **G-STUDY G-INDIA-1: FAIL as a timing signal** | Sept 2026 net +₹4,450.6 cr, AUM ₹1,88,934 cr (≈146 t). Flows **follow** last month's return (ρ +0.25, p 0.03) and do not predict next month's (ρ +0.12, p 0.31; halves disagree). |
| 7 | MCX OI-price matrix daily ("who is long/short, what got closed") | needs 1a (or the ICICI-master mirror + Breeze bars) stored daily | not possible today: **no gold history exists in DuckDB** | PUBLISH-CONTEXT after 60+ sessions of history; DO-NOT-PUBLISH as a signal until a G-STUDY passes | Daily data gives ΔOI × Δprice (long build-up / short covering / short build-up / long unwinding) in aggregate only; category attribution is monthly. |

**Three things the owner should act on first:** (i) start a daily snapshot of the ICICI MCX master into DuckDB today (free, already downloaded, gives settlement + OI for every gold contract — the OI history the owner asked for starts the day the job starts); (ii) add the 15% duty leg to the landed-cost model so MCXG shows the real local premium (~+1%) instead of a 17% "implied premium"; (iii) add GOLDTEN to `shared/mcx_specs.py` and the Muhurat timings from circular MCX/TRD/590/2026.

---

## 1. How this was verified, and the honesty notes

- **Method.** Every URL below was requested from this Mac with `httpx` (browser-like User-Agent) and, where it mattered, with `curl` (different TLS stack) and with the sandbox's fetch proxy (different network). I record status, latency, bytes, the content type and a sample of real fields. Searches were used only to find candidate URLs and to cross-check facts; a fact that rests on a secondary source is labelled so.
- **MCX is blocked for machines, not for countries.** `www.mcxindia.com` and `www.mcxccl.com` return Akamai `Access Denied` (HTTP 403, ~0.2 s) for the home page, every market-data page, every `backpage.aspx` JSON method and the static `docs/default-source/...` workbooks, with Chrome headers, with the exact header set the `mcxpy` wrapper uses, with `curl`, and from the fetch proxy. The egress IP geolocates to India, so this is Akamai Bot Manager fingerprinting (no JS challenge cookie such as `_abck`/`bm_sz`), not geo-blocking. Consequence: MCX's own data is reachable only through a **real browser session** (Playwright/Chromium with a persistent profile, which the project's `browse` tooling could drive once a day) or by hand. I did not attempt to defeat the bot manager; that would be against the brief's "respect robots/terms".
- **No ICICI credentials were used.** The only ICICI call is a `HEAD` of the public `SecurityMaster.zip` the app already downloads at ~07:30 IST; Breeze itself was not invoked (the 08:00 login window was in progress).
- **Two certificate traps.** `www.cbic.gov.in` and `taxinformation.cbic.gov.in` serve an incomplete chain (Sectigo OV intermediate missing; `openssl` verify code 21), so Python's `ssl` refuses them while `curl -k` gets 200. The duty facts therefore come from tax-law republishers (taxguru, a2ztaxcorp, thetaxcorp, LiveLaw) and ICRA, which all quote the same notification number and rates. Do not disable verification in the app; pin the CBIC intermediate or treat CBIC as link-only.
- **What could not be verified at all** is marked UNVERIFIED: the FBIL JSON route (HTTP 500 for every date format tried), MCX's due-date-rate wording and the daily/monthly granularity inside the category-wise OI workbook (only the column layout is known, from the `mcxlib` parser).

---

## 2. Glossary for the newcomer (each term defined once, used everywhere below)

- **Bhavcopy** — the exchange's end-of-day file: for every contract the open/high/low/close, **settlement price**, volume (lots and ₹ value) and **open interest**. NSE's is free and the app already stores it; MCX's is the gold equivalent and is the subject of §3.1.
- **Settlement price (daily)** — the official closing value MCX fixes each evening (gold: the volume-weighted average of trades in the last 30 minutes before the 23:30/23:55 IST close). Margins and the daily mark-to-market are computed on it. ICICI's next-morning price band is ±3% around it, which is how the app recovers it without a login.
- **Open interest (OI)** — the number of contracts (lots) that exist overnight. Every lot has one long and one short, so OI counts positions, not people. OI rises when a new buyer meets a new seller; falls when an existing long sells to an existing short ("positions got closed"). OI cannot tell you *who* closed — only the category file can.
- **Lot, tick, tick value, multiplier** — a lot is the quantity one contract controls (GOLD = 1 kg). Price is quoted per 10 g, so a ₹1 move on GOLD is ₹100 per lot (multiplier 100). Tick = smallest price step (₹1 on all gold futures; ₹0.50 on options).
- **Expiry, tender period, DDR** — gold futures are *compulsory delivery*: hold a GOLD lot through the tender period (the last ~5 sessions) and you must give or take 1 kg of 995 gold at an exchange vault. The **Due Date Rate (DDR)** is the final settlement price MCX derives from its polled spot price on the expiry day (UNVERIFIED wording; the MCX spec is behind the block). Retail traders roll or square off before the tender period.
- **Price band** — the daily limit (±3% for gold, extendable) within which orders are accepted; it sits around the previous settlement.
- **SPAN + exposure margin** — the deposit per lot the clearing corporation demands (Standard Portfolio Analysis of Risk, a scenario-loss model). Gold is currently 9.25% of notional (≈₹13.3 lakh per GOLD lot).
- **Landed cost** — what imported gold costs in rupees at the port: COMEX/LBMA dollar price × USD/INR ÷ 31.1035 × 10 (per 10 g). *Duty-paid landed* adds customs duty (15%). Retail adds 3% GST.
- **BCD, AIDC, SWS, IGST** — Basic Customs Duty; Agriculture Infrastructure and Development Cess (a surcharge collected with customs); Social Welfare Surcharge (nil on gold now); Integrated GST (3%) paid at import and creditable by dealers.
- **Premium / discount** — how far the local price sits above/below the duty-paid landed cost. A premium means domestic demand exceeds freely importable supply; a discount means stock is being dumped (weak demand, or post-duty-hike inventory).
- **IBJA** — India Bullion and Jewellers Association, which fixes an AM and a PM rate per purity each business day; the government uses the 999 PM fix for SGB prices and import-valuation checks.
- **Contango / backwardation** — a later-dated future above/below the near one. Gold in rupees is normally in contango by roughly the rupee interest rate minus the dollar lease rate (≈6–7% a year, i.e. ≈0.5–0.6% a month).
- **FPI / DFI / prop / hedger / VCP / FPO** — MCX's participant categories: Foreign Portfolio Investors; Domestic Financial Institutions (banks, mutual funds, insurers); proprietary desks of brokers; hedgers = Value-Chain Participants (refiners, jewellers, importers); Farmer Producer Organisations (agri only); "Others" = retail/clients.
- **SGB** — Sovereign Gold Bond: a rupee bond paying 2.5% a year whose principal tracks the IBJA 999 price. New issues stopped in Feb 2024; old ones trade on NSE/BSE and are redeemed early at RBI-published prices.
- **WSS** — RBI's Weekly Statistical Supplement, released Fridays ~17:00 IST, whose Table 1 is the reserves (foreign-currency assets, gold, SDRs, IMF position) as of the previous Friday.
- **Muhurat trading** — the one-hour ceremonial session on Diwali evening/afternoon.

---

## 3. Item 1 — MCX data

### 3.1 Daily bhavcopy (settlement, volume, OI per contract)

**What it tells a trader.** For every gold contract and expiry: where it settled, how much traded, and how many lots are open. The day-on-day change in OI with the change in settlement is the only honest "positioning" read available daily (§9).

**Who uses it and how.** On a Bloomberg terminal this is `GOLD Comdty OI`/`GIP` on MCX tickers; desks keep a per-expiry OI ladder and watch (i) the front-month OI decline into the tender period (roll), (ii) total OI vs the 20-day average (crowding), (iii) ΔOI × Δprice (build-up vs unwinding).

**Where it is published.** `https://www.mcxindia.com/market-data/bhavcopy` (form: date, instrument, CSV/XLS download). The form posts to `https://www.mcxindia.com/backpage.aspx/GetDateWiseBhavCopy` with JSON body `{"Date":"YYYYMMDD","InstrumentName":"FUTCOM"|"OPTFUT"|"FUTIDX"|"OPTCOM"|"ALL"}` and headers `Content-Type: application/json`, `X-Requested-With: XMLHttpRequest`, `Referer`/`Origin` on mcxindia.com; the answer is `{"d":{"Data":[...]}}` (source: `mcxlib 0.4` and `mcxpy 0.0.3`, PyPI, read from their tarballs — these libraries are the de-facto documentation of the endpoints; MCX publishes none). Other methods in the same family: `GetMarketWatch` (live table incl. LTT), `GetOptionChain`, `GetQuote`, `GetHistoricalDataDetails` (`GroupBy:"D"`, date range → daily volume/OI by commodity), `GetCommoditywisePutCallRatio`, `GetHeatMap`, `GetGainer/GetLosers`, `GetCircularAdvanceSearch`.

**Verified.** HTTP **403** `Access Denied` on the page (0.22 s, 398 B), on the POST (0.15 s, 406 B) and on the fetch proxy; identical with curl and with the wrapper's exact header set. Fields therefore come from the wrappers' parsers, not from a live row — treat the column list as UNVERIFIED until a browser collector runs.

**Frequency / lag / history.** Daily after the close (available the same night / next morning); the site serves historical dates back several years through the same form.

**Evidence of value.** Volume–OI–volatility relations are documented for futures generally (Bessembinder & Seguin 1993, *JFQA*: unexpected volume raises volatility, open interest dampens it). For MCX gold specifically there is no study in this project; the OI-price matrix (§9) is a **description**, not a predictor, until G-STUDY tests it on ≥ 250 sessions.

**Terms.** MCX's site terms restrict redistribution of its data; a personal, single-user terminal reading its own daily download is the normal broker-client use. Do not republish MCX rows to third parties.

**How to get it anyway (three legal routes, in order of effort):**
1. **ICICI public master as a daily mirror (zero effort, already in the app).** `MCXScripMaster.txt` carries, for every MCX contract, the next day's price band (settlement = band midpoint) and the previous session's OI in lots (the shifted `MarginPercentage` column). It lacks volume. Snapshotting it once a day gives settlement + OI history for every gold expiry from the day the job starts. See §10 for the table design.
2. **ICICI Breeze historical bars (owner's account, after the 08:00 login).** `get_historical_data_v2(interval="1day", exchange_code="MCX", product_type="futures", stock_code="GOLD", expiry_date=...)` returns OHLCV and (for derivatives) open interest; the 1-minute variant worked on 12 Oct 2026 when `get_quotes` returned HTTP 500 (`routers/mcx.py`). UNVERIFIED today by design (no credential use); verify after the login window.
3. **Browser-automation download of MCX's own CSV** (Playwright with a persistent Chromium profile, one visit per evening, modest and identifiable). This is the only route to **volume** and to the official file; it also unlocks the option chain and the category workbook (§3.2).

**Verdict: PUBLISH-CORE once collected via route 1 (today) and 3 (when built); LINK-ONLY until then.** Repetition note: MCXG already shows front-month OI in lots from the master (`front.open_interest_lots`) — the new value is the *history* and the per-expiry ladder, not the number itself.

### 3.2 Participant / category-wise open interest (SEBI-mandated)

**What it is.** SEBI requires commodity exchanges to disclose open interest by participant category. MCX publishes it as a workbook per month: `https://www.mcxindia.com/docs/default-source/market-data/historicaldata/{yyyy}/{month-name-lowercase}/category-wise-oi-{mon}-{yyyy}.xlsx` (e.g. `/2026/september/category-wise-oi-sep-2026.xlsx`), columns (from the `mcxlib` parser): `Date, Commodity, Instrument, Open Interest, FPOs/Farmers (Long, Short), VCPs/Hedgers (Long, Short), Proprietary traders (Long, Short), Domestic Financial Institutional Investors (Long, Short), Foreign Participants (Long, Short), Others (Long, Short)`. A sibling `category-wise-turnover-{mon}-{yyyy}.xlsx`, `trading-statistics-{mon}-{yyyy}.xlsx` (algo vs non-algo share) and `ccl_delivery.xlsx` (deliveries) sit beside it. A JSON method `GetPROClientDetailsSegmentWise` (`{"GroupBy":"M","Segment":"ALL","CommodityHead":"ALL","Commodity":"ALL","Startdate":"YYYYMM"}`) gives the proprietary-vs-client turnover split per month.

**Does MCX publish it daily?** The file is monthly and carries a `Date` column, so it is most likely date-wise rows inside a monthly workbook (UNVERIFIED: the file is behind the block). There is **no daily participant-wise report on the public site** comparable to NSE's `fao_participant_oi_DDMMYYYY.csv`. The answer to "who is long and who is short on a daily basis" for MCX gold is therefore: *only in arrears, once a month, with the exchange's own categories* — and FPIs were only allowed into non-agri contracts in 2022, so their line is thin.

**Verified.** 403 on the September 2026 workbook from both networks. BSE's equivalent page (`bseindia.com/markets/Derivatives/DeriReports/DeriMarketDisclosures.aspx`) exists for BSE's own (illiquid) contracts — not an MCX mirror.

**Evidence of value.** The CFTC literature on positioning (Sanders, Irwin & Merrin 2009; Wang 2003) finds little or inconsistent forecast power for commercial/non-commercial positions; hedging-pressure (de Roon, Nijman & Veld 2000) is a *risk-premium* story at monthly horizons. Nothing India-specific exists. Context only.

**Verdict: PUBLISH-CONTEXT (monthly panel "who holds MCX gold", once a browser collector fetches the workbook); DO-NOT-PUBLISH as a daily indicator** — it cannot be one.

### 3.3 SPAN margin files

MCX Clearing Corporation (`mcxccl.com`, 403 from here) publishes the daily SPAN risk-parameter files; brokers apply them. **Free mirror verified:** `https://zerodha.com/margin-calculator/Commodity/` (200, 0.24 s, "updated: 25 Oct 2026") lists NRML margin per contract: **9.25%** of notional for GOLD Dec-26/Feb-27/Apr-27 (₹13,25,636 / ₹13,49,918 / ₹13,78,128 per lot), GOLDM Nov/Dec/Jan (₹1,31,165 / ₹1,32,552 / ₹1,33,858), GOLDTEN Oct/Nov/Dec (₹13,155 / ₹13,291 / ₹13,434), GOLDGUINEA Nov/Dec/Jan (₹10,686 / ₹10,793 / ₹10,903), GOLDPETAL Nov/Dec/Jan (₹1,335 / ₹1,348 / ₹1,362). Note that `shared/mcx_specs.py` carries 6% "indicative" — **the live number is 9.25%**, i.e. the paper ticket under-states margin by a third. Terms: Zerodha's page is a public calculator; scraping once a day for a personal terminal is reasonable, but ICICI's own margin (plan-dependent) is what the account will actually be charged — show both or label "exchange NRML (Zerodha mirror)".

**Verdict: PUBLISH-CONTEXT** (one margin number per contract, refreshed daily; replace the 6% constant).

### 3.4 Spot price polling

MCX polls a panel of bullion dealers/refiners for a spot price per commodity and basis centre (gold: Ahmedabad, 995, duty-paid) and uses it for the DDR at expiry. Page `market-data/spot-market-price`: 403. There is no free mirror of MCX's polled number; **IBJA's fixes (§5.2) are the practical substitute**, and the difference between them is a few hundred rupees per 10 g. **Verdict: LINK-ONLY** (explain the DDR mechanism in the contract card; show IBJA).

### 3.5 Expiry / settlement circulars

Circular search: 403. What matters is republished by brokers and compliance sites within a day: the 2026 holiday list (already in `mcx_specs.py` from ICICI/Kotak/5paisa), and the Muhurat circular **MCX/TRD/590/2026 dated 19 Oct 2026** (teamleaseregtech.com, fetched): Sunday 8 Nov 2026, special session 14:05–14:19, trading 14:20–15:30, client-code modification until 15:45, all commodities and indices. **Owner action:** replace the `SPECIAL_SESSIONS_2026` note ("evening timings by MCX circular") with these timings. **Verdict: LINK-ONLY** (hand-maintained constants; no feed).

---

## 4. Item 2 — ICICI Breeze: which gold contracts the account can trade, and the "choose the contract" selector

### 4.1 What the public master says (cached copy dated 2026-10-23; file `data/reference/icici_security_master/MCXScripMaster.txt`, 26,722 rows)

The public zip `https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip` answered HEAD 200, 2,998,716 bytes, `Last-Modified: Fri, 23 Oct 2026 01:58:26 GMT` (= 07:28 IST), S3-hosted — so it is published ~07:30 IST each trading day; at 05:46 IST today it still carried Friday's file. The gold family in it:

| Family (`CompanyName`) | ICICI `ShortName` (= Breeze `stock_code`) | Lot | Quote | Tick (paise) | Expiries listed | OI (lots, prior session) | Price band 23 Oct (₹) |
|---|---|---|---|---|---|---|---|
| GOLD (1 kg, 995) | `GOLD` | 1 kg | ₹/10 g | 100 | 04-Dec-26, 05-Feb-27, 05-Apr-27, 04-Jun-27, 05-Aug-27, 05-Oct-27 | **16,650**, 749, 42, 4, 0, 0 | Dec: 1,41,697–1,50,461 (settle 1,46,079) |
| GOLDM (100 g, 995) | `GOLDMI` | 100 g | ₹/10 g | 100 | 05-Nov-26, 04-Dec-26, 05-Jan-27, 05-Feb-27, 05-Mar-27, 05-Apr-27 | **48,437**, 22,922, 4,752, 2,434, 475, 72 | Nov: 1,40,247–1,48,921 |
| GOLDTEN (10 g, 999) | `GOLDTE` | 10 g | ₹/10 g | 100 | 30-Oct-26, 30-Nov-26, 31-Dec-26, 29-Jan-27, 26-Feb-27, 31-Mar-27 | **25,655**, 21,986, 9,596, 4,924, 1,383, 259 | Oct: 1,40,665–1,49,365 |
| GOLDGUINEA (8 g, 999) | `GOLDGU` | 8 g | ₹/8 g | 100 | 30-Oct-26, 30-Nov-26, 31-Dec-26, 29-Jan-27, 26-Feb-27, 31-Mar-27 | 12,009, 10,169, 4,399, 1,982, 630, 142 | Oct: 1,13,149–1,20,147 |
| GOLDPETAL (1 g, 999) | `GOLDPE` | 1 g | ₹/1 g | 100 | 30-Oct-26, 30-Nov-26, 31-Dec-26, 29-Jan-27, 26-Feb-27, 31-Mar-27 | **155,778**, 171,840, 81,166, 41,758, 14,955, 5,286 | Oct: 14,144–15,018 |
| Options on GOLD futures | `GOLD` (`Series=OPTION`, `OPTSTK`) | 1 (= one GOLD lot) | ₹/10 g premium | **50** | 30-Oct-26 and 27-Nov-26 (1,044 CE + 1,044 PE each, strikes 1,16,500→2,73,000 step ₹500), then monthly to 28-Sep-27 (111–186 strikes each) | — (not in master) | premium bands per strike |
| Options on GOLDM futures | `GOLD` short name, `CompanyName=GOLDM` | 1 (= one GOLDM lot) | ₹/10 g premium | 50 | 29-Oct-26 (146 strikes), 27-Nov-26 (126), 29-Dec-26 (117), step ₹500 | — | — |

Observations that matter for the selector:
- **GOLDTEN exists and is liquid** (25,655 lots in Oct, more than GUINEA) but is absent from `shared/mcx_specs.CONTRACTS` and from `MASTER_ALIASES`/`BREEZE_CODE` in `routers/mcx.py` (ShortName `GOLDTE`). Spec: 10 g lot, quoted per 10 g, 999 purity, month-end expiry (same cycle as PETAL/GUINEA), tick ₹1 = ₹1 per lot. Launched 1 Apr 2025 (Rupeezy).
- Options expire **before** the futures they settle into (GOLD options 30-Oct and 27-Nov both sit on the Dec-26 future; GOLDM 29-Oct option on the Nov-26 future). Exercise leaves you with the futures position — the selector must say so.
- The master's `OpenInterest` column is empty; OI is in `MarginPercentage` (ICICI's header is shifted — already handled in `gold_preopen.parse_mcx_gold`). `TickSize` is in paise (100 = ₹1; 50 = ₹0.50 on options). `LotSize` is in the `QuantityUnit` (KGS for GOLD, GRMS for the rest).
- Band half-width is exactly 3.0% of the midpoint for every row checked → settlement recovery is sound.

**Can Breeze trade them?** The master lists them for the ICICI commodity segment, and `routers/mcx.py` already maps four of the five. Live verification (a `get_quotes`/`get_historical_data_v2` call per code) must happen after the 08:00 IST login — not done here by rule. Known failure: `get_quotes` on MCX futures returned HTTP 500 on 12 Oct 2026; 1-minute bars worked.

### 4.2 Per-contract economics at Friday's prices (Zerodha 25 Oct prices; costs from `shared/mcx_specs.round_trip_costs`, ₹20/order flat)

| Contract | Lot | Quote | Tick value / lot | Notional | NRML margin (9.25%) | Round-trip cost (squared off) | Breakeven ticks | 1% move = |
|---|---|---|---|---|---|---|---|---|
| GOLD Dec-26 @ 1,43,309 | 1 kg | ₹/10 g | ₹100 | ₹1,43,30,900 | ₹13,25,636 | ₹2,511 (0.018%) | 25.1 | ₹1,43,309 |
| GOLDM Nov-26 @ 1,41,802 | 100 g | ₹/10 g | ₹10 | ₹14,18,020 | ₹1,31,165 | ₹291 (0.021%) | 29.1 | ₹14,180 |
| GOLDTEN Nov-26 @ 1,43,684 | 10 g | ₹/10 g | ₹1 | ₹1,43,684 | ₹13,291 | ₹72 (0.050%) | 71.9 | ₹1,437 |
| GOLDGUINEA Nov-26 @ 1,15,526 | 8 g | ₹/8 g | ₹1 | ₹1,15,526 | ₹10,686 | ₹67 (0.058%) | 67.1 | ₹1,155 |
| GOLDPETAL Nov-26 @ 14,438 | 1 g | ₹/1 g | ₹1 | ₹14,438 | ₹1,335 | ₹50 (0.344%) | 49.7 | ₹144 |

Reading it: brokerage is flat, so the smaller the contract the larger the cost as a share of notional (PETAL round trip is 0.34% — a third of a typical day's range). Margin covers a 9.25% adverse move on every size; the difference between contracts is purely granularity of exposure and liquidity (GOLD and GOLDM carry the OI; PETAL has the most lots but tiny rupee value; GUINEA/TEN/PETAL are 999 purity and settle at month-end, GOLD/GOLDM are 995 and settle on the 5th).

### 4.3 "Choose the contract" selector — design

Three cascaded pickers, state in the URL (`?ex=MCX&c=GOLDM&exp=2026-12-04`), defaults = exchange MCX, family by owner preference (GOLDM for a ₹1–2 lakh margin budget), expiry = highest-OI expiry more than 5 sessions from the tender period (reuse `gold_preopen.pick_contract`).

- **Exchange** (MCX only today; NSE/BSE commodity segments list gold but have negligible OI — show them greyed with the reason).
- **Contract family** — card per family with: lot, quote unit, purity, expiry rule and the next three expiries (observed from the master, computed fallback), tick value, OI by expiry (bar), margin ₹ and %, round-trip cost ₹ and %, "1% move = ₹", delivery unit and the tender-period start date (expiry − 5 sessions for GOLD/GOLDM; month-end families have their own), and a plain sentence: "This contract moves ₹X per ₹1 change in the 10 g price; a ₹Y margin covers a Z% move."
- **Expiry** — the OI ladder with the roll warning (front-month OI falling faster than the next month rising = roll in progress) and the COMEX month it maps to (`comex_symbol`).
- **What changes when you switch** (show as a diff strip): tick value, margin, cost %, liquidity (OI and the Breeze LTP freshness), purity/settlement rule, COMEX hedge ratio (GOLD ≈ 32 oz, GOLDM ≈ 3.2 oz, TEN ≈ 0.32 oz).
- **Options** — a separate toggle (CE/PE, strike list from the master, premium band) with the note that an exercised option becomes the underlying future; margin for short options is SPAN-based and much larger than the premium.

Everything above is derivable from the master (already cached) plus the Zerodha margin mirror; nothing needs a login. Live LTP comes from the existing `/quote` route with its honest degrade.

**Verdict: PUBLISH-CORE** (the selector) — it removes the hard-coded "GOLD only" assumption in the pre-open desk and gives the newcomer the per-contract economics in one place. Repetition: the MCXG "Contract specs" card already lists four families; the selector should *replace* it, not sit beside it.

---

## 5. Item 3 — The Indian price stack: from COMEX to the shop counter

### 5.1 The formula

```
landed (₹ per 10 g)      = P_usd_per_oz × USDINR ÷ 31.1034768 × 10
duty-paid landed         = landed × (1 + BCD + AIDC)          = landed × 1.15   (since 13 May 2026)
importer's cash outlay   = duty-paid landed × (1 + IGST 3 %)  = landed × 1.1845 (IGST is creditable, so dealers quote ex-GST)
dealer / IBJA price      = duty-paid landed + local premium (or − discount)      ← IBJA quotes "without 3 % GST"
retail jewellery price   = (IBJA × purity factor + making charges) × 1.03 GST, with making charges taxed at 5 %
MCX futures              = duty-paid landed + premium + carry (≈ 6–7 % p.a. ≈ 0.5–0.6 % per month to expiry) ± basis noise
```

Purity factors: 999 = 1.000, 995 = 0.996, 916 (22 K) = 0.917, 750 (18 K) = 0.751, 585 (14 K) = 0.586 (IBJA's own ladders match these within ±0.1%).

### 5.2 Every input, verified

**Customs duty — 15% total.** Notification **No. 16/2026-Customs dated 12 May 2026, effective 13 May 2026** (with Nos. 15/17/18 of the same date for findings, spent catalysts and industrial inputs): BCD on gold (HS 7108) **10%** (from 5%), AIDC **5%** (from 1%), SWS nil; silver and platinum the same. Before that, 6% since the July 2024 budget; Budget Feb 2026 had left it unchanged. All-in import levy incl. IGST 3% = 18.45%. Sources: taxguru.in, a2ztaxcorp.net, thetaxcorp.in, livelawbiz.com, ICRA note (secondary; CBIC primary unreachable — cert chain). Market reaction on 13 May 2026: MCX June gold +6–7%, intraday high ₹1,64,497/10 g (Business Today, Invezz, DSIJ).

**GST.** 3% on the gold value, 5% on making charges; unchanged by the 56th GST Council "GST 2.0" rationalisation effective 22 Sep 2025 (cbic-gst.gov.in reachable, 200; rates per multiple tax advisories).

**IBJA rates** — `https://ibjarates.com/` (200, 0.86 s, 156 KB; `ibja.co` 200). Two fixes a day (AM, PM), per 10 g for gold, per kg for silver, "without 3% GST and making charges". Verified rows:

| Date | Fix | 999 | 995 | 916 | 750 | 585 | Silver 999 (₹/kg) | Platinum 999 |
|---|---|---|---|---|---|---|---|---|
| 23 Oct 2026 | AM | 1,41,448 | 1,40,882 | 1,29,566 | 1,06,086 | 82,747 | 1,95,027 | 55,916 |
| 23 Oct 2026 | PM | 1,41,630 | 1,41,063 | 1,29,733 | 1,06,223 | 82,854 | 1,94,415 | 55,743 |
| 22 Oct 2026 | PM | 1,42,694 | 1,42,123 | 1,30,708 | 1,07,021 | 83,476 | 1,99,777 | 56,347 |
| 21 Oct 2026 | PM | 1,44,105 | 1,43,528 | 1,32,000 | 1,08,079 | 84,301 | 2,06,783 | 58,143 |
| 19 Oct 2026 | PM | 1,45,944 | 1,45,360 | 1,33,685 | 1,09,458 | 85,377 | 2,08,750 | 57,026 |

No fix on 20 Oct (Dussehra). At 05:45 IST today the page said "Rates will be uploaded soon" — the AM fix appears around midday, the PM fix late afternoon (exact minute not verifiable from here; the SGB press release calls the PM fix the "closing price"). The page embeds a 30-day chart series (dates 01/10→23/10/2026) but no longer history; the official API (`indiagoldratesapi.com`) is a paid subscription (bank and NBFC logos on the page). **Ingest:** scrape the two tables (`<table>` 2 = AM, 3 = PM; columns as above) twice a day at ~13:00 and ~18:30 IST, store `(date, fix, purity, rate)`, never backfill from the chart. Parsing needs no lxml — `bs4` with `html.parser` works (verified). Terms: a personal terminal reading the public page is normal use; do not redistribute or embed IBJA's table in a public product without their licence.

**MCX spot (Ahmedabad 995)** — blocked (§3.4).

**Rupee** — RBI/FBIL reference rate (§6.3): 94.9432 on 23 Oct 2026, published ~13:30 IST; Yahoo `INR=X` close that day was 94.7113 (0.25% lower — the two are not interchangeable at the ₹300 chase-limit level).

**Retail premium / discount — no free series.** Reuters' weekly "Asia Gold" piece reports Indian dealers' quotes against "official domestic prices inclusive of 15% import and 3% sales levies": discount up to $14/oz (early Oct), up to $6 (week of 9 Oct), **premium up to $3/oz** (late Oct, first since early Sept). That is ±0.1–0.4% of price. The World Gold Council's India desk publishes a similar premium chart in its monthly India commentary (not fetched). **Derived series (recommended):** `IBJA 999 PM − duty-paid landed`, with COMEX and the FBIL rate sampled at the IBJA fix time; store daily.

### 5.3 Worked example — Friday 23 Oct 2026 (all inputs above)

- COMEX GC=F 4,007.90 $/oz (Dec-26 future = GCZ26 4,007.90); USD/INR 94.7113 (Yahoo, NY close) → **landed ex-duty ₹1,22,042**; × 1.15 → **duty-paid ₹1,40,348**; × 1.03 → ₹1,44,559 retail-equivalent for 999 bullion before making charges.
- IBJA 999 PM 1,41,630 → **+0.91% (₹+1,282 / 10 g ≈ $42/oz) over duty-paid landed.** This is larger than Reuters' "+$3", for two reasons the app must handle: the IBJA PM fix is struck in the Indian afternoon while my COMEX/INR are New York closes on a day gold fell 1.9%, and GC=F is a December future (≈ $20–25 of contango above spot). Sampled at the same minute with spot (XAU) and the FBIL fix, the residual is the true premium. Lesson for the panel: **synchronise timestamps or the "premium" is mostly clock error.**
- MCX GOLD Dec-26 close 1,43,309 → +2.11% over duty-paid landed; +1.19% over IBJA 999; carry to 4 Dec at ~6.5% p.a. is ≈ 0.75%, leaving ≈ +0.4% as the futures' own premium/basis. That is the number a trader wants on screen.
- The app's current "implied premium" (`gold_preopen.fair_open`: settlement ÷ ex-duty landed − 1) reads **+17.4%** — it is the duty (15%) plus carry plus a small premium rolled into one number, labelled "duty + local premium" in `GoldPreOpen.tsx`. Split it: show duty as a constant with its notification date, and the residual as the premium.

### 5.4 Why MCX trades at a premium or discount, and how duty changes jump the price

- **Why a premium exists at all.** MCX gold is *duty-paid* gold in an Indian vault; its floor is the duty-paid landed cost, and the ceiling is the cost of bringing more metal in (duty-paid landed + bank/refiner margin + a few days' logistics). Between those, the price is set by local demand: festival/wedding buying, jeweller restocking and ETF creations push it to a premium; a price spike that stalls retail demand, a duty hike that leaves importers holding inventory bought at the old duty, or heavy smuggling (which supplies the grey market with duty-free metal) push it to a discount. Since the May hike the market has mostly sat at a **discount** (Reuters: up to $14/oz) and only turned to a small premium in late October as imports collapsed (−81% in September) and festival demand arrived.
- **The duty jump arithmetic.** Duty is applied to the landed value, so a change in the rate moves the duty-paid floor by `landed × Δrate`. On 13 May 2026, going from 6% to 15% raised the floor by 9 percentage points of landed, i.e. **+8.5% on a price that already carried 6%** (= 1.15/1.06 − 1). On Friday's landed of ₹1,22,042 that is **+₹10,984 per 10 g**. MCX June gold rose 6–7% that day — the market did not pay the full 8.5% at once because (i) duty-paid inventory already in vaults was now worth more and some of it was sold into the move, and (ii) the discount widened to absorb the rest. A cut works in reverse (July 2024, 15% → 6%: MCX gold fell ~₹4,000 in a session). The practical rule for a trader: **budget announcements (1 Feb) and any surprise notification are jump events; the fair-open model must take the duty rate as a dated input, not a constant.**
- **Hallmarking and making charges** do not touch MCX but matter to the retail-demand story: 6-digit HUID hallmarking has been mandatory since 1 Apr 2023 (sale without HUID prohibited), covering 14/18/20/22/23/24 K with 9 K added as a grade in 2025, and extended to 380 districts in the 6th phase (Mar 2026). Making charges run ~8–25% of the gold value for jewellery (0.5–3% for coins/bars) and carry 5% GST — the reason coins/bars and ETFs take share when prices spike (WGC Q2 2026: bar & coin +9%, jewellery −15%).

**Verdicts.** Duty rate with its date: PUBLISH-CORE (one dated constant in `shared/`). IBJA AM/PM: PUBLISH-CORE (daily store, the India spot line). Derived premium (IBJA vs synchronised duty-paid landed) and MCX basis: PUBLISH-CONTEXT. GST/hallmarking/making: PUBLISH-CONTEXT as a static explainer card. Reuters piece: LINK-ONLY.

---

## 6. Item 4 — RBI

### 6.1 Gold reserves (weekly, value) — verified

`https://www.rbi.org.in/Scripts/BS_viewWssExtract.aspx?SelectedDate=10/23/2026` (200, 1.22 s, 127 KB; the calendar page `BS_viewWssExtract.aspx` lists each Friday as a postback whose target is this plain GET). Table "Foreign Exchange Reserves", **as on 16 Oct 2026**:

| Item | ₹ crore | US$ mn | Δ week (US$ mn) | Δ since end-Mar 2026 (US$ mn) | Δ year (US$ mn) |
|---|---|---|---|---|---|
| Total reserves | 68,46,160 | 721,016 | −5,011 | +29,909 | +18,736 |
| Foreign currency assets | 56,19,655 | 591,847 | −5,758 | +39,565 | +21,437 |
| **Gold** | **10,04,583** | **105,800** | **+706** | **−9,595** | **−2,746** |
| SDRs | 1,76,396 | 18,578 | +30 | −44 | −144 |
| IMF reserve position | 45,525 | 4,791 | +11 | −17 | +189 |

Gold = 14.7% of reserves by value. PDF of the same release: `https://rbidocs.rbi.org.in/rdocs/PressRelease/PDFs/PR1377WSS3F6FA9957B4E49E38C63F2C1DA3D5DC8.PDF`. Cadence: Fridays ~17:00 IST, data as of the previous Friday (7-day lag). **Tonnes** are not weekly: 880.52 t at 31 Mar 2026 (RBI Annual Report; 77% held domestically after the 2024–26 repatriations) and the half-yearly *Report on Management of Foreign Exchange Reserves*. The new website (`website.rbi.org.in`) renders its WSS index with JavaScript and 301s the publications path to the home page — use the old-site extract URL above. The RBI DBIE portal (`data.rbi.org.in`, Angular, undocumented `/api/services/queryInterface`) is link-only.

**What it tells a trader.** Central-bank buying is the structural bid under gold since 2022 (WGC); the RBI line shows whether India is adding (it bought ~73 t in 2024, little in 2025–26 — value changes week to week are almost entirely price). The weekly ₹/US$ value divided by the London fix gives an implied tonnage check. Context only — no study links RBI purchases to MCX returns. **Verdict: PUBLISH-CONTEXT** (one weekly row with tonnes derived; the app shows nothing of this today).

### 6.2 Sovereign Gold Bonds — verified

Press release **2026-2027/1060 (7 Sep 2026)**: premature redemption of SGB 2020-21 Series VI on 8 Sep 2026 at **₹15,384 per unit**, "based on the simple average of closing price of gold of 999 purity of the previous three business days (3, 4 and 7 Sep 2026) as published by IBJA". Other 2026 redemptions found: 15,840 (25 May), 15,672 (1 Jun), 14,086 (1 Jul), 14,199 (16 Jul), 15,295 (17 Aug). **No new tranche since 2023-24 Series IV (Feb 2024, ₹6,262/g); the Budget of 1 Feb 2025 confirmed discontinuation** (cost of servicing). Old series trade on NSE/BSE (`SGB*` symbols) usually at a small discount to IBJA. **What it tells a trader:** nothing about direction; it is the official proof that **IBJA 999 PM is the government's reference price**, and the redemption calendar is a minor source of retail selling. **Verdict: PUBLISH-CONTEXT** (link + formula in the glossary; no feed).

### 6.3 Rupee reference rate — verified (archive), API UNVERIFIED

`https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx` — ASP.NET form; a GET to capture `__VIEWSTATE`/`__EVENTVALIDATION` then a POST with `txtFromDate`, `txtToDate` (dd/mm/yyyy), `chkUSD=on`, `btnSubmit=Submit` returns the table (200, 0.32 s). USD/INR: 23 Oct 94.9432 · 22 Oct 94.6986 · 21 Oct 94.7145 · 16 Oct 95.0194 · 15 Oct 95.0691 · 14 Oct 95.0317. The rate is computed by FBIL from a 12:00–12:30 IST polling window and published ~13:30 IST. FBIL's own SPA (`fbil.org.in`) calls `https://www.fbil.org.in/wasdm/refrates/fetch?forDate=…` — every date format tried (dd-mm-yyyy, yyyy-mm-dd, dd/mm/yyyy) returned HTTP 500 (UNVERIFIED parameter format; the bundle also lists `refrates/fetchusdinrcomputed`). **Use:** the timestamp-matched rupee for the landed-cost and premium series; the live rupee stays Yahoo `INR=X` (already in WEI and MCXG). **Verdict: PUBLISH-CONTEXT** (daily store; display only inside the landed-cost card).

---

## 7. Item 5 — Imports

### 7.1 Commerce ministry / DGCI&S monthly — verified (listing + secondary numbers)

The monthly merchandise-trade release (PIB, ~15th of the following month, with the commodity table "Gold" in US$ mn): **September 2026 gold imports US$1.80 bn (−81.27% YoY); silver US$665 mn (−49.11%); April–September 2026 gold US$19.27 bn vs 26.51 bn (−27.3%)**; exports 44.40 bn (+23.04%), imports 74.61 bn, deficit 30.21 bn. `pib.gov.in/allRel.aspx` answered 200 (listing, 0.70 s); the specific PRID page was not retrieved — the numbers are from PTI/Business Today/ThePrint coverage and a PDF copy of the release (worldtradescanner.com). DGCI&S's query portal `https://tradestat.commerce.gov.in/` (200, 2.95 s) exposes form pages (`/eidb/commodity_wise_import`, `/meidb/commoditywise_export`, HS 7108) — free, no key, no API, POST with viewstate; `commerce.gov.in/press-releases/` is 404 (the ministry site moved). Lag ~15 days; monthly; history to 1997 on tradestat. **What it tells a trader:** the demand pulse after a duty change and the state of the current account (the policy driver of duty). 2026 is the textbook case: imports −81% four months after the hike, then the discount narrows. **Verdict: PUBLISH-CONTEXT** (one monthly bar; ingest from the PIB page text with a regex, or by hand on the 15th).

### 7.2 Swiss exports to India — verified (bulk open data)

opendata.swiss / BAZG "Goods: foreign trade by tariff number / country", monthly since 1988, CKAN package `e6bcc098-2c55-4305-a5ed-35c7bf7cde55` (200). Export resource `https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_EXP_en/TN8_EXP_en.zip` — HEAD 200, **692,443,287 bytes**, `Last-Modified 20 Oct 2026 06:06 GMT` (September data; BAZG releases around the 18th–20th). Filter: tariff 7108.1200 (unwrought gold, non-monetary) × partner India, kg and CHF. Swiss-Impex's interactive portal (`gate.ezv.admin.ch/swissimpex/` 404 at the old path — now a dashboard) is browser-only. Terms (opendata.swiss standard): open use with source attribution; commercial use requires the owner's permission — fine for a personal terminal. **What it tells a trader:** Switzerland refines most of the bars India imports, so Swiss customs is the fastest hard count of physical flow (Reuters cites it monthly); it leads the Indian release by ~0–5 days and is in tonnes, not dollars. **Verdict: PUBLISH-CONTEXT** (monthly job, download → filter → one row; do not fetch the 692 MB file more than once a month).

---

## 8. Item 6 — Demand seasonality

### 8.1 Calendar (static, verified dates)

| Event | 2026 date | Why it matters | Market practice |
|---|---|---|---|
| Akshaya Tritiya | Sun 19 Apr 2026 (next: 2027 TBD) | Auspicious buying day; jewellers report same-day volumes | Premium often firms in the week before; no evidence of a futures effect |
| Dhanteras | Fri 6 Nov 2026 | Peak retail gold day of the year | Dealers restock in late Oct; watch the premium flip (it did: discount → premium in late Oct 2026) |
| Diwali / Laxmi Pujan + MCX Muhurat | Sun 8 Nov 2026, 14:05–14:19 special, 14:20–15:30 trading (circular MCX/TRD/590/2026) | Ceremonial session; token volumes | Do not read the Muhurat print as a signal |
| Wedding seasons | mid-Nov → mid-Feb, late Apr → Jun (regional) | ~50% of jewellery demand | Context |
| Monsoon (IMD Jun–Sep) | IMD long-range forecast Apr, updates Jun | Rural India is ~55–60% of jewellery demand; a deficient monsoon weakens post-harvest (Oct–Dec) buying | WGC cited a weak monsoon as a 2026 headwind |
| Budget | 1 Feb | Duty announcements | Jump risk (§5.4) |

**Evidence.** USD gold has a documented but small and unstable September–November seasonal ("autumn effect", Baur 2013, *Research in International Business and Finance*, attributed partly to Indian wedding demand); no study — including this one — shows a tradable seasonal in MCX futures after costs. **Verdict: PUBLISH-CONTEXT** as rows in the existing ECO/EVTS calendar (the app already has RBI MPC/CPI/Fed rows; add these, do not build a new calendar).

### 8.2 AMFI gold-ETF monthly flows — verified, with a G-STUDY

`https://portal.amfiindia.com/spages/am{mon}{yyyy}repo.xls` (mon = jan…dec), e.g. `amsep2026repo.xls` (200, 0.48 s, 110 KB, sheet `MCR_MonthlyReport`, row "Gold ETF"); PDF twin `amsep2026repo.pdf` created 8 Oct 2026 20:35 IST → published ~8–10th of the next month. Files back to Apr 2018 (`amapr2018repo.xls`); I fetched all 81 months Jan 2020→Sep 2026 (all 200). Row layout: `[sr, "Gold ETF", schemes, folios, funds mobilised ₹cr, repurchase ₹cr, net inflow ₹cr, average AUM ₹cr, month-end AUM ₹cr]`. **September 2026: 26 schemes, 1,26,77,259 folios, mobilised 5,310.65, repurchase 860.04, net +4,450.61 cr, month-end AUM ₹1,88,934 cr ≈ 146 t** at the month-end rupee price. (Press reports the same +₹4,451 cr, +71% m/m.) `xlrd 2.0.1` is in the env; no key, no registration. Terms: AMFI data is public; attribute.

**G-STUDY G-INDIA-1 — "Do monthly gold-ETF flows predict next month's rupee gold return?"** (`scratch/amfi_gold_etf_study.csv`, `amfi_study_results.json`)
- Data: net flow ÷ prior month-end AUM (flow %), Feb 2020→Aug 2026, **N = 79 months**; rupee gold = Yahoo `GC=F × INR=X` month-end closes (same inputs the desk uses).
- Flow %(t) → return(t+1): **Spearman +0.115 (p 0.31)**; Pearson +0.22 (p 0.048, driven by a few large months). Terciles of flow → next-month mean return: low +1.60%, mid +1.38%, high +2.20%; **high − low = +0.59 pp (Welch t 0.45, p 0.65)**. Halves: Feb 2020–Apr 2023 ρ −0.11 (p 0.49); May 2023–Aug 2026 ρ +0.30 (p 0.06) — sign flips.
- Flow %(t) vs return(t−1): **Spearman +0.25 (p 0.028)** — flows chase last month's return.
- **Verdict: FAIL as a timing signal; PASS as a description (trend-following retail flow).** Use it as the "how crowded is Indian paper gold" context line (AUM in tonnes, months of positive flow in a row), never as a trigger. Caveats: 79 months, one asset, continuous-futures proxy, AMFI net flow includes NFOs.

### 8.3 WGC India demand (quarterly)

Gold Demand Trends Q2 2026 (India focus, published 30 Jul 2026; secondary coverage, WGC page in the search listing but not fetched): total 131.4 t (−6% YoY), jewellery 75.1 t (−15%), bar & coin 50.3 t (+9%), ETF 4.2 t (+49%), value a record ₹1.98 lakh crore; full-year 650–750 t with price and monsoon as headwinds. Q3 2026 is due around the end of October. Likely covered by the G-DEMAND agent; **LINK-ONLY from this brief** (quarterly, 1-month lag, context).

---

## 9. Item 7 — The MCX OI-price matrix, daily

### 9.1 The method (what daily data can and cannot say)

With yesterday's and today's settlement `S` and open interest `OI` per contract:

| Δ settle | Δ OI | Label | Plain English |
|---|---|---|---|
| up | up | **long build-up** | new buyers are entering and sellers are new too — fresh money, conviction |
| up | down | **short covering** | price rose while positions closed — shorts bought back; weaker than a build-up |
| down | up | **short build-up** | new sellers pressing — fresh bearish positions |
| down | down | **long unwinding** | longs sold out to existing shorts — positions got closed on the way down |

Add: OI change as % of the 20-day average OI (size), the roll ratio (front OI ÷ next OI) and days to the tender period. "What got closed" is the OI decline (in lots and as % of OI); "who closed" is not identifiable daily — only the monthly category workbook (§3.2) says whether the hedgers, the prop desks, the DFIs or the FPIs changed their net. Options add the put/call OI ratio and max-pain per expiry (`GetOptionChain`, blocked; the ICICI master lists strikes but not OI).

### 9.2 Evidence of value

Generic futures evidence (Bessembinder & Seguin 1993) is about volatility, not direction. The build-up labels are a description that every Indian broker app shows; nobody has shown them to predict MCX gold after costs, and this project has **no MCX history to test on** (no gold table in DuckDB, the ICICI master is overwritten daily, Breeze OI is unreliable for old contracts per the project's own memory). **Verdict: PUBLISH-CONTEXT after ≥ 60 sessions of stored history; DO-NOT-PUBLISH as a signal until a pre-registered G-STUDY (ΔOI×Δprice quartiles → next-5-session return, two halves) passes.** The single most valuable thing the owner can do today is to start the history.

---

## 10. Ingest plan (DuckDB owner = data-service; all times IST; nothing here needs a login except Breeze bars)

| Table | Source | Schedule | Parser / traps |
|---|---|---|---|
| `mcx_gold_master_daily(date, family, short_name, expiry, settle, band_lo, band_hi, oi_lots, tick_paise, lot, quote_unit)` | ICICI `SecurityMaster.zip` → `MCXScripMaster.txt` (public; the app already downloads it) | 07:40 (after the ~07:30 publish; retry 08:30) — a fetch, not a restart, so the 07:45–09:20 freeze is not violated | OI is in `MarginPercentage`; settle = band midpoint; `ShortName` 6-char aliases incl. `GOLDTE`; options have `Series=OPTION`, tick 50; dedupe on `(publish_date, token)` |
| `mcx_gold_bars_daily(date, family, expiry, o,h,l,c, volume, oi)` | Breeze `get_historical_data_v2(interval="1day")` per liquid expiry | 23:59 or 07:00 next day (after login) | verify fields on first run; OI known to be wrong for *old* contracts — store only live expiries; mark source |
| `mcx_bhavcopy(date, symbol, expiry, instrument, o,h,l,c, settle, volume_lots, value_cr, oi)` | MCX CSV via browser automation (`GetDateWiseBhavCopy`, `InstrumentName=FUTCOM` and `OPTFUT`) | 23:50 | only with a real browser profile; 403 otherwise; keep the raw CSV |
| `mcx_category_oi_monthly` | `category-wise-oi-{mon}-{yyyy}.xlsx` via the same browser | 5th of each month | columns per §3.2; check whether rows are per day |
| `mcx_margin_daily(date, contract, expiry, nrml_rupees, nrml_pct, ref_price)` | Zerodha commodity margin page | 07:30 | `bs4` html.parser; first column "GOLD Dec 2026 Lot size 1 KGS" |
| `ibja_fix(date, fix[AM/PM], purity, rate)` | ibjarates.com tables 2 (AM) and 3 (PM) | 13:05 and 18:35; skip when "will be uploaded soon" | per 10 g (gold) / kg (silver); no history → never backfill |
| `inr_reference_rate(date, usdinr)` | RBI archive form POST (fallback) · FBIL API (once the parameter format is known) | 13:45 | dd/mm/yyyy; viewstate round-trip |
| `india_landed_daily(date, comex_spot_usd, usdinr_ref, landed, duty_rate, duty_paid, ibja999_pm, premium_pct, mcx_front_settle, basis_pct)` | derived | 18:40 | sample COMEX spot at the IBJA PM minute (Yahoo 5-min bars already cached by the desk) |
| `rbi_reserves_weekly(week_ended, gold_usd_mn, gold_inr_cr, total_usd_mn, tonnes_est)` | `BS_viewWssExtract.aspx?SelectedDate=mm/dd/yyyy` (Friday) | Fri 18:00, retry Sat | parse the "Foreign Exchange Reserves" table text; tonnes = value ÷ London PM |
| `india_gold_imports_monthly(month, usd_bn, yoy_pct)` | PIB release text | 16th 10:00 | regex "Gold" row; keep the PRID |
| `swiss_gold_exports_monthly(month, partner, kg, chf)` | BAZG `TN8_EXP_en.zip` | 22nd, monthly | 692 MB; stream, filter `7108.1200` × `India`; delete the zip |
| `amfi_gold_etf_monthly(month, schemes, folios, mobilised, repurchase, net, avg_aum, end_aum, tonnes_est)` | `am{mon}{yyyy}repo.xls` | 11th 10:00, retry daily until 200 | `xlrd`; row match `^Gold ETF`; a few 2020 files label it "GOLD ETF" |
| `mcx_duty_rate(effective_date, bcd, aidc, sws, igst, notification)` | hand-maintained constant | on change | current row: 2026-05-13, 10, 5, 0, 3, "16/2026-Customs" |

Point-in-time discipline applies (docs/PROGRAMMATIC_DATA_ACCESS.md): key every row by the date it became known, not the reference date.

---

## 11. Where it goes in the terminal, and the repetition audit

Already shown today (do not duplicate): COMEX `GC=F`, `INR=X`, DXY in **WEI** (World Markets) and in **MCXG**'s overlay; COMEX×INR landed (ex-duty) and "implied premium" in **MCXG** and **GOLD** (pre-open); MCX holidays and session clock in MCXG; front-month OI in lots in MCXG specs; RBI MPC/CPI/IIP/GDP in **ECO**; nothing from IBJA, RBI reserves, imports, AMFI, duty or margins anywhere.

Proposed placement (one home per number):
- **MCXG → new "India stack" strip** (the visual the owner asked for, separate from the pre-open desk): a left-to-right waterfall *COMEX spot → × USD/INR → landed → + duty 15% (dated) → duty-paid → IBJA 999 PM (premium x%) → MCX front settle (basis y%, carry z%)*, with timestamps under each bar. Below it the **contract selector** (§4.3) replacing the current specs card, with margin from the Zerodha mirror.
- **MCXG → "Positioning" card** (only after history exists): OI ladder per expiry, ΔOI×Δsettle label, roll ratio, days to tender; monthly category bars when the workbook is collected.
- **WEI → one row** in the India block: "MCX GOLD basis vs duty-paid landed: +0.4%" with the premium colour — a single number so the world-markets page is not a second gold desk.
- **ECO/EVTS → calendar rows**: Dhanteras, Diwali/Muhurat (with the circular's timings), Akshaya Tritiya, budget day, PIB trade release (~15th), AMFI (~10th), RBI WSS (Fridays), BAZG (~20th).
- **BRF (morning brief)** → one line when something changed: duty notification, IBJA premium flip, RBI gold purchase, import print.
- **RSCH** → add a catalogue row for G-INDIA-1 (AMFI flows, verdict FAIL as signal).

---

## 12. Open questions

1. Are the rows inside MCX's monthly `category-wise-oi` workbook daily or month-end? (Needs one browser download.)
2. Which Breeze calls work for MCX today — `get_quotes` (500 on 12 Oct), `get_historical_data_v2` daily bars with `open_interest`, and the `GOLDTE` code? (Verify after the 08:00 login, outside the freeze window.)
3. Exact DDR wording for GOLD/GOLDM vs the 999 month-end families (MCX spec PDF, behind the block).
4. FBIL `wasdm/refrates/fetch` parameter format (every tried format → 500); is the RBI archive form stable enough to rely on?
5. Does the Swiss `TN8_EXP` zip carry 7108.1200 at 8-digit granularity with India as a partner row, and in which unit (kg vs "additional unit")? (Needs one monthly 692 MB download.)
6. Is a Playwright-based MCX collector acceptable to the owner under MCX's site terms for a personal terminal? If not, the MCX-native data stays link-only and the ICICI master + Breeze bars are the whole history.
7. Will the duty be revisited in Budget 2027 (1 Feb)? The model must treat the rate as a dated input either way.

## 13. Owner actions (ordered)

1. **Start the daily snapshot of `MCXScripMaster.txt` into DuckDB now** (§10, first row) — the OI history starts the day this runs; zero new network dependencies.
2. **Add the duty leg** (`duty_rate` dated constant, 15% since 13 May 2026) to `gold_preopen.fair_open`/MCXG overlay; relabel "implied premium" as basis vs duty-paid landed; add the FBIL/RBI reference rate for the timestamped version.
3. **Add GOLDTEN** to `shared/mcx_specs.CONTRACTS` (10 g, ₹/10 g, 999, month-end, tick ₹1 = ₹1/lot) and `GOLDTE` to `MASTER_ALIASES`/`BREEZE_CODE`; replace the 6% indicative margin with the daily Zerodha mirror (9.25% today); fix the Muhurat note with circular MCX/TRD/590/2026 timings.
4. **Ingest IBJA AM/PM, RBI weekly gold, PIB monthly imports, AMFI monthly** per §10 — all verified free, all parse without new packages.
5. **Build the contract selector** (§4.3) and the India-stack waterfall in MCXG; put one basis number in WEI; calendar rows in ECO.
6. After the login window: live-verify the five Breeze codes and daily bars; decide on the browser collector for MCX bhavcopy/options/category OI.
7. Register the OI-price-matrix G-STUDY (pre-registered plan, two halves, costs from `shared/mcx_specs`) to run once 60+ sessions exist; until then show positioning as description only.
8. Add `reports/gold_program/G-INDIA` to the RSCH catalogue (verdict rows: AMFI flows FAIL as signal; everything else context).

---

## Appendix A — Verification log (26 Oct 2026, IST ≈ 05:40–06:30; egress IP country IN)

| URL | Method | Status | Latency | Bytes | Note |
|---|---|---|---|---|---|
| https://www.mcxindia.com/ | GET (httpx, Chrome UA) · GET (curl) | 403 · 403 | 0.33 s · 0.18 s | 370 | Akamai "Access Denied" |
| https://www.mcxindia.com/market-data/bhavcopy | GET ×2 · fetch proxy | 403 · 403 · 403 | 0.2 s | 398 | |
| https://www.mcxindia.com/market-data/spot-market-price | GET | 403 | 0.21 s | 415 | |
| https://www.mcxindia.com/market-data/participant-wise-open-interest | GET | 403 | 0.18 s | 432 | path may not exist; blocked before routing |
| https://www.mcxindia.com/market-operations/circulars | GET | 403 | 0.21 s | 405 | |
| https://www.mcxindia.com/backpage.aspx/GetMarketWatch | POST `{}` (curl, XHR headers) | 403 | 0.15 s | 406 | |
| https://www.mcxindia.com/backpage.aspx/GetDateWiseBhavCopy | POST `{"Date":"20261023","InstrumentName":"FUTCOM"}` (mcxpy header set) | 403 | 0.15 s | — | |
| https://www.mcxindia.com/docs/default-source/market-data/historicaldata/2026/september/category-wise-oi-sep-2026.xlsx | GET · fetch proxy | 403 · 403 | 0.21 s | — | |
| https://www.mcxccl.com/ and /risk-management/span | GET | 403 · 403 | 1.22 s · 0.17 s | 368 | |
| https://pypi.org/pypi/mcxlib/json · mcxpy/json (+ sdists) | GET | 200 | <1 s | — | endpoint catalogue read from source |
| https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip | HEAD | 200 | <1 s | 2,998,716 | Last-Modified Fri 23 Oct 01:58 GMT; S3 |
| https://zerodha.com/margin-calculator/Commodity/ | GET | 200 | 0.24 s | 99,765 | "updated: 25 Oct 2026"; 15 gold rows, 9.25% |
| https://ibjarates.com/ · https://ibja.co/ | GET | 200 · 200 | 0.86 s · 0.87 s | 156,145 · 136,092 | AM/PM tables 19–23 Oct 2026 |
| https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx | GET + POST (13/10→23/10/2026, USD) | 200 · 200 | 0.49 s · 0.32 s | 79,832 · 81,789 | 6 USD rows returned |
| https://www.fbil.org.in/ (+ main.js 5.2 MB) · /wasdm/refrates/fetch?forDate=… | GET | 200 · **500** ×3 | 1.4 s · 0.3 s | — | API base `https://www.fbil.org.in/wasdm`; format unknown |
| https://www.rbi.org.in/Scripts/BS_viewWssExtract.aspx?SelectedDate=10/23/2026 | GET | 200 | 1.22 s | 127,425 | reserves table as on 16 Oct 2026 |
| https://www.rbi.org.in/Scripts/WSSView.aspx · BS_viewWss.aspx · BS_ViewWSSTable.aspx | GET | 200 ×3 | 0.5–0.6 s | — | listings only |
| https://www.rbi.org.in/Scripts/WSSView.aspx?Type=section&PARAM1=1 | GET | 418 | 0.26 s | 626 | "Unauthorised Access" (WAF) |
| https://website.rbi.org.in/web/rbi/publications/weekly-statistical-supplement | GET · fetch proxy | 200 (generic shell) · 301 → rbi.org.in | 0.97 s | 153,765 | JS-rendered; use old site |
| https://data.rbi.org.in/ (+ main.js 15.2 MB, 31.8 s) | GET | 200 | 1.15 s | 50,732 | `/api/services/queryInterface` undocumented |
| https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63538 | GET | 200 | 0.78 s | 113,841 | SGB PR 2026-2027/1060 |
| https://portal.amfiindia.com/spages/amsep2026repo.xls (and 80 more months) | GET | 200 ×81 | 0.5–4.5 s | ~110,000 each | Gold ETF row parsed |
| https://portal.amfiindia.com/spages/amsep2026repo.pdf | GET | 200 | 0.83 s | 349,837 | created 8 Oct 2026 20:35 IST |
| https://pib.gov.in/allRel.aspx | GET | 200 | 0.70 s | 186,552 | listing |
| https://commerce.gov.in/press-releases/ | GET | 404 | 3.69 s | 196 | moved |
| https://tradestat.commerce.gov.in/ | GET | 200 | 2.95 s | 30,981 | eidb/meidb form links |
| https://ckan.opendata.swiss/api/3/action/package_show?id=e6bcc098-… | GET | 200 | 0.96 s | 17,747 | 6 CSV-zip resources |
| https://ckan.opendata.swiss/api/3/action/package_show?id=schweizerische-exporte-und-importe-… | GET | 403 | 2.55 s | 245 | slug not readable; use the UUID |
| https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_EXP_en/TN8_EXP_en.zip | HEAD | 200 | <1 s | 692,443,287 | Last-Modified 20 Oct 2026 |
| https://www.bazg.admin.ch/en/swiss-foreign-trade-statistics-current-data | GET | 200 | 1.78 s | 399,459 | no xlsx links, no India mention |
| https://www.gate.ezv.admin.ch/swissimpex/ | GET | 404 | 2.96 s | 11,824 | old portal path |
| https://www.cbic.gov.in/ · https://taxinformation.cbic.gov.in/ | GET (httpx) · curl -k | SSL verify failed · 200 | 0.17 s · 0.48 s | 7,423 | incomplete chain (verify code 21) |
| https://cbic-gst.gov.in/ | GET (curl) | 200 | 0.82 s | — | |
| https://www.bis.gov.in/ | GET | 200 | 2.44 s | 578,907 | |
| https://www.nseindia.com/all-reports-commodities | GET | 404 | 0.31 s | 383 | NSE commodity reports path unknown; not an MCX mirror |
| https://nsearchives.nseindia.com/archives/com/bhavcopy/ | GET | 404 | 0.28 s | 3,535 | |
| https://www.bseindia.com/markets/commodity/CommodityBhavcopy.aspx | GET | 200 | 0.34 s | 14,287 | BSE's own contracts (illiquid) |
| https://www.moneycontrol.com/commodity/gold-price.html | GET | 403 | 0.22 s | 411 | Akamai |
| https://www.5paisa.com/commodity-trading/mcx-bhavcopy | GET | 404 | 1.75 s | — | |
| https://query1.finance.yahoo.com/v8/finance/chart/{GC=F,INR=X,GCZ26.CMX} | GET | 200 ×3 | 0.26–0.33 s | — | 23 Oct closes used in §5.3 |
| https://teamleaseregtech.com/updates/article/60567/… | fetch proxy | 200 | — | — | Muhurat circular text |
| https://www.drishtiias.com/…/gold-import-duty-hiked-to-18-4/print_manually | fetch proxy | 200 | — | — | duty table (no notification no.) |

## Appendix B — Secondary sources used for facts (not fetched from the primary)

Duty notification 16/2026-Customs: taxguru.in, a2ztaxcorp.net, thetaxcorp.in, livelawbiz.com, ICRA (May 2026) · Budget 2026 unchanged at 6%: Motilal Oswal (1 Feb 2026) · 13 May 2026 MCX reaction: Business Today, Invezz, DSIJ · Imports Sept 2026: PTI via ThePrint/Business Today/Kotak Neo, worldtradescanner.com PDF of the PIB release · RBI tonnes 880.52 t: RBI Annual Report 2025-26 via Deccan Herald/DrishtiIAS · SGB discontinued: Budget 2025 coverage (goldenpi, tradejini) · Akshaya Tritiya 19 Apr 2026, Dhanteras 6 Nov 2026: Business Today, BankBazaar · WGC Q2 2026 India: Angel One/PTI (WGC page `gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-india-focus-q2-2026` in the search listing) · Reuters Asia Gold (9 Oct and late Oct 2026) via mining.com / engineeringnews · GST 3%/5% unchanged after 22 Sep 2025: Bajaj Finserv, Busy, BasuNivesh · Hallmarking: BIS blog, GJEPC, newsonair (6th phase, 12 Mar 2026) · GOLDTEN launch 1 Apr 2025: Rupeezy.
