# G-CME: COMEX / CME free daily gold data — verified sources, meaning, verdicts

Agent G-CME · SuryaDhana GOLD program · verified live on **Mon 26 Oct 2026, 07:30–09:40 IST** from the owner's Mac
(`/Users/sudheer/Desktop/jupyter_env/bin/python`, httpx + curl; browser-like User-Agent; ≥1.5 s between requests).
Raw evidence: `samples/` (every body saved), `probe_log.jsonl` (status, latency, bytes per request), `probe.py`.
Read-only on the repo; no live service, no ICICI, no Telegram touched.

Companion briefs (not duplicated here): CFTC COT (weekly positioning) · LBMA / spot / lease rates · ETF flows ·
WGC supply–demand · Kitco / news · MCX itself. Where this report touches them it is only to cross-check a COMEX number.

---

## 0. The one-paragraph answer

COMEX is where the world's gold *price* is set and where the "who is long, who is short, what got closed" question is
answerable **daily** (open interest), not weekly (COT). Of the ~25 things the brief asked for, **the free, official,
script-safe route is CME's FTP server `ftp.cmegroup.com`** (a separate AWS host, not behind CME's web firewall). It
gives, verified today: daily volume **and open interest for every COMEX gold and silver product** (GC, MGC, 1OZ, QO,
OG calls/puts, weeklies, SI, SIL, SIC) with a **daily archive back to 2 Jan 2014** (3,227 files); the **EFRP transaction
breakdown** (every EFP / EFR print, daily, archive from 2017: these are the "over-the-counter deals that print on
CME"); the **product calendar** (first notice, last trade, delivery windows for every month) and the **product
reference file** (contract size, tick, settlement method, initial margin, EFP/block eligibility, dated today).
**Everything on `www.cmegroup.com` is blocked for this IP** (HTTP 403 "This IP address is blocked due to suspected web
scraping activity", 17 of 17 URLs, including plain PDF/XLS downloads and the FTP's HTTPS mirror; a headless Chromium
got `ERR_HTTP2_PROTOCOL_ERROR`). That block takes out the four most-wanted pages: the **Daily Bulletin** (settlement
and OI **by contract month**), the **warehouse stocks** (registered / eligible / pledged by depository), the
**delivery notices** (issues & stops by firm) and **all options data** (by strike, QuikStrike, CVOL). I verified their
layout and latest content through Internet Archive copies taken on 25 Oct 2026 (so the fields and numbers below are real,
but that is not a production feed). Verdict pattern: **PUBLISH-CORE** = daily OI/volume by product (FTP), the roll
calendar (FTP), contract specs/margins (FTP), the term structure from Yahoo's per-month quotes (free, verified, no OI);
**PUBLISH-CONTEXT** = EFP prints, warehouse stocks and deliveries (when access is restored), put/call OI, gold/silver
ratio, SHFE/SGE context; **DO-NOT-PUBLISH** = anything scraped from `www.cmegroup.com` (the block message cites CME's
Data Terms of Use: "Use of scripts … is strictly prohibited") and the dead/paywalled fallbacks (Nasdaq CHRIS, Stooq).

What the app already shows (so it is not repeated): the COMEX front price in **five** places (WEI commodities row, CMDT
board, Gold Pre-Open context, MCXG overlay, BRF gold panel), silver (WEI, CMDT, GPO), USD/INR, DXY, TIPS, and the MCX
front contract's own OI (lots) from ICICI's master. **Nothing** below (COMEX OI, volume, curve, EFP, stocks,
deliveries, options, calendar) exists in the app today, and no gold series is stored in DuckDB.

---

## 1. Access reality (read this before building anything)

| Host | What it serves | Result today | Terms |
|---|---|---|---|
| `https://www.cmegroup.com/…` (Akamai) | CmeWS JSON used by CME's own pages, Daily Bulletin PDFs, `delivery_reports/*.xls|pdf`, contract-spec pages, `/ftp/` HTTPS mirror | **403 on every path** (0.17–0.25 s, 602-byte JSON): *"This IP address is blocked due to suspected web scraping activity associated with it on this CMEgroup.com page. Use of scripts, software, spiders, robots … is strictly prohibited by CME Group's website Data Terms of Use … contact CME Group's Global Command Center (GCC) at gcc@cmegroup.com"*. Same with curl and with a headless Chromium (`ERR_HTTP2_PROTOCOL_ERROR`). The repo never fetched cmegroup.com automatically (only the FedWatch link in `gold_preopen.py`), so the block predates this program; cause unknown (open question 1). | Website Data Terms of Use: personal, non-commercial; **no scripts**. A terminal that scrapes it is in breach even if the block were lifted. |
| `ftp://ftp.cmegroup.com/` (AWS 13.57.171.25, alias ftp.cme.akadns.net) | `daily_volume/`, `efrp/`, `span/util/` (product calendar), `pub/fprf/` (product reference), `webmthly/` (monthly PDFs), `settle/TCF/` (Treasury conversion factors, not metals), `pub/delivery_reports/` (FX, cattle, lumber only — **no metals**), `pub/span/archive/` (SPAN files 2013–2025) | **Works**: anonymous FTP, directory listing 2.6 s, 100 KB file 4–5 s, 38 MB calendar 153 s. No robots, no terms file in the tree; CME has run this server for programmatic distribution for 15+ years. | No terms posted on the server. The Daily Bulletin footer (same data) says "compiled for the convenience of the user … furnished without responsibility for accuracy". Treat as free for in-house use; do not re-publish outside the terminal. |
| `web.archive.org` | Archived copies of the blocked www files (snapshots dated 25 Oct 2026: someone archives these daily) | Direct `…/web/2026id_/<url>` fetches worked (200, 2–5 s) after the availability API rate-limited me (429). | Layout verification only. **Not** a feed: no SLA, days can be missing, and it would be scraping CME by proxy. |

**Consequence for the architecture:** the data-service can ingest the FTP files on a schedule today (plain `ftplib`/curl,
no key, no login). The four www-only datasets need an owner decision (open question 1 / owner action 1): either the IP
block is a mistake that CME's GCC lifts (then a once-a-day download of three small public files is defensible as
personal use — still "automated"; the owner decides), or they stay **LINK-ONLY** panels the owner opens in a browser.

---

## 2. Source dictionary (NSE_DATA_DICTIONARY style)

Each entry: what it is · get it · verified (what I actually saw) · published/lag/history · key fields · what it tells a gold
trader · who uses it and how · evidence · already in app · verdict.

### 2.1 CME FTP — Daily Volume and Open Interest by product  ·  **PUBLISH-CORE**
*How many contracts changed hands and how many are still open, per product, every day — the daily "who is holding" tape.*

- **Get it:** `ftp://ftp.cmegroup.com/daily_volume/daily_volume.xlsx` (latest) and `daily_volume_YYYYMMDD.xlsx` (archive: 3,227 files, 2014-01-02 → 2026-10-22, plus `daily_volume_reports_2013.zip`). Anonymous FTP. ~100 KB.
- **Verified:** latest file 99,720 B in 4.1 s; sheet 2 "CME Group Vol and OI by Product", header row 3, **Trade Date 10/22/2026** (file mtime Oct 23 03:31 server clock). Nine more dated files (Oct 9–21) fetched at 4.4–4.8 s each. Column `Open Interest ②` is the product's OI at the close of the trade date.
- **Sample (10/22/2026, COMEX):** GC futures Globex 237,695 · OTC (ClearPort/ex-pit) 8,324 · total 246,019 · MTD ADV 165,279 · **OI 403,397**; MGC 351,808 / OI 124,151; 1OZ 57,462 / OI 87,158; QO (E-mini) 3,603 / OI 8,551; **OG gold calls OI 631,061, puts OI 259,338**; weekly gold options OG1–OG5 and the Mon/Tue/Wed/Thu/Fri series (G1M … G5R); SI OI 114,637; SIL (micro silver) 24,507; SIC (100-oz) 11,849; QI 1,164.
- **Published / lag / history:** daily, one file per trade date, posted the next calendar day 03:30–05:00 on the FTP server's clock. FTP timestamps look like **US Central** (the product calendar's internal `DATE_CREATED 10/23/2026 16:30:49` matched its FTP mtime 16:33), so expect the file ≈ 14:00–15:30 IST on T+1; verify with the first week of ingest. History 12.8 years daily.
- **Key fields:** Description (asset class), Exchange Name, Commodity Indicator (product code), Product Description, Future/Option Indicator, CME Globex Volume, Pit Volume, ExPit Volume, OTC Volume, Total Volume, MTD ADV, Open Interest.
- **What it tells you:** OI is the number of contracts open overnight; every contract has one long and one short, so OI = total longs = total shorts. The **daily change in OI with the daily change in price** is the four-quadrant read (section 4.6): rising price + rising OI = new longs (long build-up); falling price + rising OI = new shorts; rising price + falling OI = shorts closing (short covering); falling price + falling OI = longs closing. This is the daily answer to "which position got closed"; COT (weekly) then says *who*. Volume/OI (churn) shows whether a move is day-trading noise or position-taking.
- **Who uses it:** every futures desk; Bloomberg `GCA Comdty OIS`/`FHG` (futures history), `CTM`, the "Volume & OI" column on `GIP`. Desks watch the OI change on big down days (short build-up vs long liquidation) and the roll (OI migrating Dec → Feb).
- **Evidence:** Hong & Yogo (2012, *J. Financial Economics*) find futures open-interest growth has forecasting power for commodity returns at monthly horizons; Bessembinder & Seguin (1993, *JFQA*) link volume/OI to volatility. For daily gold specifically: **context only** until we run G-STUDY-1 (we now have the 12-year daily product OI to do it; see §6).
- **Already in app:** no COMEX OI anywhere (MCXG shows MCX lots from ICICI's master only).
- **Verdict: PUBLISH-CORE.** Store daily; show the OI/price quadrant for GC, the OI by product (GC/MGC/1OZ/QO/options) and volume, with the 12-year history for percentiles.
- **Ingest notes:** `ftplib` or `curl ftp://…`; parse sheet index 1 with pandas/openpyxl (header is row 2, trade date in cell A2 as "Trade Date:  10/22/2026"; column names contain newlines and a `②` footnote mark — normalise). Idempotent by trade date; backfill with the dated files (3,227 × 100 KB ≈ 330 MB, one-off, paced at 1 file/2 s ≈ 2 h). Cross-check: CFTC's Tuesday OI (402,279 on 20 Oct) vs this file's 10/20 OI (402,507) agree within 0.06%.

### 2.2 CME FTP — EFRP transaction breakdown (EFP / EFR prints)  ·  **PUBLISH-CONTEXT**
*The privately negotiated "off-screen" gold deals that are reported to and cleared on COMEX, one line per transaction.*

- **Get it:** `ftp://ftp.cmegroup.com/efrp/efrp_transaction_breakdown/efrp-report.csv` (latest) / `efrp-report_YYYYMMDD.csv|.xlsx` (3,704 entries; xlsx from 2017-01-20, csv for recent years).
- **Verified:** `efrp-report_20261023.csv` 33,597 B in 3.6 s. Columns: `Original Process Date, Product Long Desc, Product Line, Transaction Type Description, Contract Expiry (YYYY-MM), Future/Option Indicator, Volume - Round Turns`. 23 Oct: 439 EFP rows + 68 EFR rows across all products; **GOLD: 19 EFP prints, 3,115 round turns, all Dec-2026** (sizes 50–500). The archived Daily Bulletin for the same day shows **EFP 3,115** for GC Dec-26: exact match, so this file *is* the bulletin's ex-pit column with per-transaction detail.
- **Published / lag:** daily; file for T appeared between 05:03 and 18:45 server clock on T+1 (variable). History ≈ 9.8 years.
- **What it tells you:** An **EFP** (exchange for physical) swaps a futures position for the physical metal (or an OTC forward) at a privately agreed price: a bank that sold London bullion to a client and hedged on COMEX, or a refiner delivering into a future, prints an EFP. **EFR** (exchange for risk) swaps futures for an OTC swap. Rising EFP volume = physical/OTC business being moved onto or off the exchange; big EFP days around first-notice day are dealers rolling physical hedges. The EFP *price* (futures − spot differential) is what tells you physical tightness, but **CME does not publish EFP prices**, only volumes (the price is in the OTC market: LBMA members quote "EFP bid/offer" — covered by the LBMA brief; a free proxy is Dec futures − spot from §2.11).
- **Who uses it:** bullion banks and arbitrage desks (the EFP is their main instrument); Bloomberg `GCA Comdty` ex-pit volume, `EFP` in `CTM`. Retail rarely sees it; a trader uses it as *context* for abnormal days (e.g., Jan–Mar 2025 tariff-driven gold migration to New York showed up first as record EFP volumes).
- **Evidence:** no predictive study for gold returns; **context only**.
- **Already in app:** no.
- **Verdict: PUBLISH-CONTEXT** — a small "EFP tape" (today's prints, 20-day average, % of total volume) on the COMEX panel; not a signal.
- **Ingest notes:** csv when present else xlsx; filter `Product Long Desc == 'GOLD'` (micro/1OZ have their own descriptions: none printed on 23 Oct); sum by expiry; store raw rows.

### 2.3 CME FTP — Product calendar XML (first notice, last trade, delivery windows)  ·  **PUBLISH-CORE**
*The roll calendar: the dates that force positions to move or deliver.*

- **Get it:** `ftp://ftp.cmegroup.com/span/util/product-calendar-new.xml` (38.7 MB, all CME Group products; 153 s to download). Filter `Exchange == XCEC`.
- **Verified:** `DATE_CREATED 10/23/2026 16:30:49`; per contract: `FTD` first trade, `LTD` last trade, `SD` settlement date, `DD`, `LTD_END_TIME` (12:30:00 PM for metals = 12:30 CT), and for physically delivered contracts `FID/LID` (first/last intent), `FND/LND` (first/last notice), `FDD/LDD` (first/last delivery). Counts: GC 34 futures months + 77 option series; MGC 12 + 33; 1OZ 12; QO 11; SI 32 + 75; SIL 8; SIC 10.
- **Sample:** **GCZ6 (Dec-26): FND 30 Nov 2026, first intent 27 Nov, LTD 29 Dec 12:30 CT, LND 30 Dec, delivery 1–31 Dec.** GCG7: FND 29 Jan 2027, LTD 24 Feb. GCJ7: FND 31 Mar, LTD 28 Apr. GCM7: FND 28 May, LTD 28 Jun. MGCZ6 same dates as GC. **1OZZ6 and QOZ6: LTD 25 Nov 2026, no notice dates (financially settled).** Weekly gold options expire Mon–Fri (G1M…G5R, OG1…OG5), e.g. OG1V6 LTD 2 Oct 2026.
- **Published / lag:** regenerated daily; forward-looking (no lag). History irrelevant (reference data), but keep each day's file to reproduce past rolls.
- **What it tells you:** the **first notice day (FND)** is when a long can be assigned delivery: speculators must be out of the front month before it (brokers force-liquidate), so OI migrates to the next month in the two weeks before FND. The app's MCX contract pick already uses "highest OI" (ICICI master); the COMEX equivalent needs these dates: **Dec-26 is front until ~25 Nov; the OI migration to Feb-27 has visibly started** (Dec OI −12,246 and Feb +9,869 on 23 Oct, §2.6).
- **Who uses it:** everyone; Bloomberg `GCZ6 Comdty DES` (first notice, last trade), `CTM` roll dates. The MCX GOLD Dec contract (expiry 4 Dec) sits *after* COMEX's FND, so the Pre-Open desk's COMEX leg must roll to GCG27 around 25 Nov while MCX is still on Dec: a mismatch the fair-open model (`comex_symbol()` maps MCX Dec ↔ GCZ26) must handle explicitly.
- **Verdict: PUBLISH-CORE** (a "days to FND / LTD" countdown and the roll status on the COMEX panel, and a mapping used by the Pre-Open desk).
- **Ingest notes:** stream-parse with `xml.etree.iterparse` (done in `samples/comex_gold_silver_calendar.csv`: 304 COMEX gold/silver contracts); refresh weekly (it is 38 MB; CME also exposes `product_calendar.xml` of 88 B — a stub). Alternative with the same dates and smaller: §2.4.

### 2.4 CME FTP — COMEX product reference file (specs, margins, eligibility)  ·  **PUBLISH-CORE**
*Official instrument definitions for every COMEX future, refreshed daily, including the initial margin.*

- **Get it:** `ftp://ftp.cmegroup.com/pub/fprf/csv/cmeg.comex.fut.prf.csv.zip` (46 KB zip → 583 KB csv). (Directory mtimes say Nov 2024 but the content carries `BizDt 2026-10-26`: updated in place.) Options: `pub/fprf/cmeg.strat.prf.xml` (168 MB, all products; too big to pull daily).
- **Verified:** 82 columns incl. `InitMargin, MaintMargin, Sym, Desc, MMY, SecTyp, MatDt, UOM, UOMQty, Mult, MinPxIncr, SettlMeth, FirstTrdDt, LastTrdDt, FirstDlvDt, LastDlvDt, FirstNoticeDt, LastNoticeDt, LastEFPDt, FirstBlockTASDt, LastBlockTASDt, EligForBlock, EligForEFP, EligForEFR, TickIncrReg, StartTickPxRngReg, EndTickPxRngReg`. Gold-family symbols present: GC, MGC, QO, 1OZ, GCT/MGT/QOT (trade-at-settlement), GCD (London TAM first PM), GC7 (London marker), SGU/SGC (Shanghai Gold USD/CNH futures on COMEX), KYG10–16 (synthetic time-stamped), GCCP1/GCCPA (price series), ECGC (event contracts).
- **Sample (Dec-26 rows, BizDt 2026-10-26):**

| Sym | Desc | Size (oz) | SettlMeth | Tick (TickIncrReg / MinPxIncr) | InitMargin (USD) | LTD | FND | LastEFPDt |
|---|---|---|---|---|---|---|---|---|
| GC | COMEX 100 GOLD FUTURES | 100 | P (physical) | 0.10 | **20,302** (≈5.1% of $400,790 notional at 4,007.90) | 2026-12-29 | 2026-11-30 | 2026-12-30 |
| MGC | MICRO GOLD FUTURES | 10 | P | MinPxIncr 1 (=$0.10) | 2,031 | 2026-12-29 | 2026-11-30 | — |
| 1OZ | 1 OUNCE GOLD FUTURES | 1 | **C (cash)** | MinPxIncr 25 (=$0.25) | 204 | 2026-11-25 | — | — |
| QO | E-MINI GOLD FUTURES | 50 | **C (cash)** | MinPxIncr 25 (=$0.25) | 10,152 | 2026-11-25 | — | — |
| SI | COMEX 5000 SILVER FUTURES | 5,000 | P | MinPxIncr 1 (=$0.005) | 22,003 | 2026-12-29 | 2026-11-30 | 2026-12-30 |
| SIL | MICRO SILVER | 1,000 | P | 1 | 4,401 | 2026-12-29 | 2026-11-30 | — |
| SIC | 100-OUNCE SILVER | 100 | C | 1 | 441 | 2026-11-25 | — | — |

  The field named `MaintMargin` (GC 1,400; MGC 140; 1OZ 14) scales with contract size at $14/oz and cannot be the maintenance margin (which is ≈ 90% of initial); it is probably the intra-commodity spread charge. **Treat `InitMargin` as the outright initial margin and confirm the second field's meaning with CME's margin page** (open question 3). Margins differ slightly by month (GCV6 20,214; GCX6 20,231; GCZ6 20,302; GCG7 20,471 …) because CME scales them with the price.
- **What it tells you:** the exact contract you are trading, its leverage (margin/notional ≈ 5% today → 20× leverage; a 5% gold move wipes the margin) and the dates. For a MCX trader it is the Rosetta stone between MCX GOLD (1 kg = 32.15 oz, ₹/10 g) and COMEX GC (100 oz, $/oz): 1 GC ≈ 3.11 MCX lots.
- **Verdict: PUBLISH-CORE** (a specs card on the COMEX panel with margin % of notional updated daily; the Pre-Open desk's `comex_symbol()` should take LTD/FND from here instead of assuming month codes).
- **Ingest notes:** daily, tiny; keep history of `InitMargin` (margin hikes are themselves events: CME raised gold margins repeatedly in the 2025–26 rally).

### 2.5 CME FTP — monthly volume and OI reports (`webmthly`)  ·  **LINK-ONLY**
- **Get it:** `ftp://ftp.cmegroup.com/webmthly/YYYYMM.zip` (2013 → 202609; 2.7 MB; 17 PDFs: `Web_OI_Report_NYMEX_COMEX_YYYYMM.pdf`, `Web_Volume_Report_…`, `Web_ADV_Report_…`, `Web_Volume_Comparison_…`).
- **Verified:** 202609.zip 2.72 MB in 11.8 s; OI report (Sep 2026): **COMEX GOLD GC month-end OI 397,291 vs 493,748 a year earlier (−19.5%) and 419,328 the prior month (−5.3%)**; SI 106,011 (−35.3% y/y); QO 8,672 (+253% y/y, so the E-mini is not dead); E-mini silver 1,124.
- **What it tells you:** the monthly frame the owner asked for ("weeks, days and month"): year-over-year participation. The daily file (§2.1) already contains every month-end, so this adds only the printed y/y comparison.
- **Verdict: LINK-ONLY** (repetition of §2.1 aggregated; keep the link for the monthly view and compute month-end stats from the daily table instead).

### 2.6 CME Daily Bulletin, Section 62 "Metal Futures Products" (per-month settlement, OI, volume, ex-pit)  ·  **PUBLISH-CORE if access, else LINK-ONLY**
*The official end-of-day sheet: for every contract month the settlement price, change, open interest, Globex volume, PNT/pit volume, high/low, and a second page with deliveries, blocks, EFP, TAS, EFR by month.*

- **Get it:** `https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf` (preliminary in the evening CT, final next morning), Section 63 = metals options; archive `…/daily_bulletin/preliminary_voi/…` and dated bulletins. **403 from this IP.** Verified instead via `web.archive.org/web/20261025000515id_/…` (105,656 B, 9 pages, "Fri, Oct 23, 2026 · BULLETIN # 205 · PRELIMINARY").
- **Sample (GC, 23 Oct 2026):** settlement Oct-26 3,991.10 · Nov-26 3,993.80 · **Dec-26 4,007.90 (−52.50)** · Jan-27 4,026.00 · Feb-27 4,041.30 · Apr-27 4,073.40 · Jun-27 4,107.90 · Aug-27 4,142.60 · Dec-27 4,209.00 · … Dec-29 4,597.40. OI: Dec-26 **295,084 (−12,246)**, Feb-27 **60,591 (+9,869)**, Apr-27 18,606 (+814), Jun-27 11,598 (+1,463); **total 401,548**. Globex volume Dec-26 176,399, PNT/pit 3,921. Ex-pit page, COMEX GOLD: deliveries 6 today / 3,208 "settled to-date" (Oct-26), **EFP Dec-26 3,115** (= FTP EFRP file), TAS and EFR columns populated, Block TAS 180. Silver Dec-26 settlement 53.949 → **gold/silver ratio 74.29**.
- **Published / lag:** preliminary ≈ 20:00 CT (06:30 IST next morning, before MCX opens), final ≈ 08:00 CT. History: CME's dated bulletin archive (www).
- **What it tells you:** the **term structure** (contango: each later month higher), the **roll** (Dec OI shrinking while Feb grows), the **true settlement** (Yahoo's "close" is the last trade, not the settlement the margin is marked to), and the ex-pit breakdown that answers "how much of today's volume was OTC". It is the one document a Bloomberg user reads as `GC1 Comdty GIP`/`CTM`/`OIS` combined.
- **Verdict: PUBLISH-CORE if the owner restores access** (it is a public PDF meant for daily download; one fetch/day), **otherwise LINK-ONLY** with the Yahoo per-month fallback (§2.11) for the curve and §2.1 for total OI. Do not scrape through the Internet Archive.
- **Ingest notes (when allowed):** `pymupdf` text extraction works but interleaves columns (the ex-pit table needs positional parsing with `page.get_text("words")`); the FTP has no copy (checked `pub/`, `settle/`, `daily_volume/`).

### 2.7 COMEX warehouse stocks (Gold_Stocks.xls, Silver_stocks.xls)  ·  **PUBLISH-CORE if access, else LINK-ONLY**
*How much metal sits in COMEX-approved vaults, by depository, split into registered (deliverable), eligible (in the vault but not registered) and pledged (registered metal posted as collateral).*

- **Get it:** `https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls`, `…/Silver_stocks.xls` (also Gold Kilo / 4GC enhanced delivery are folded into the gold file). **403 from this IP.** Verified via archive snapshot `20261025234631` (16,896 B, sheet "Daily Metal Stocks Report", **Report Date 10/23/2026, Activity Date 10/22/2026**). Not on the FTP (`pub/delivery_reports/` holds FX, live cattle, lumber only).
- **Fields:** per depository (Asahi, Brink's, Delaware Depository, HSBC, IDS of Delaware, JP Morgan, Loomis, Malca-Amit, Manfra Tordella & Brookes): rows Registered / Pledged / Eligible / Total × columns PREV TOTAL, RECEIVED, WITHDRAWN, NET CHANGE, ADJUSTMENT, TOTAL TODAY (troy oz, 3 dp); then TOTAL REGISTERED, TOTAL PLEDGED, TOTAL ELIGIBLE, COMBINED TOTAL. Footnote: combined total covers both the GC and the 4GC (enhanced delivery, 400-oz bar) contracts.
- **Sample (activity 10/22/2026):** **Registered 14,814,284 oz; Pledged 1,746,271; Eligible 8,468,689; Combined 23,282,973 oz (≈724 t)**; day's flow: 60,090 oz withdrawn from eligible (Brink's −53,628, Asahi −6,462), 2,685 oz re-classified registered→eligible. Largest: Brink's 6.98M, HSBC 5.05M, JPM 4.58M, MTB 2.07M, Asahi 1.83M, Malca-Amit 1.57M. Silver: registered 100,514,943 oz, eligible 237,586,643, total 338,101,586.
- **Published / lag:** daily, report for activity day T posted on T+1 (US morning).
- **What it tells you:** the physical side of the paper market. **Registered** = warrants issued, deliverable against futures tomorrow; **eligible** = metal meeting the bar standard but not warranted (its owner would have to register it to deliver); **pledged** = registered warrants lodged with CME Clearing as margin collateral (not available for delivery unless unpledged). Large *inflows* (Dec 2024–Mar 2025: +20M oz into New York ahead of tariff fears) tell you about EFP economics and the London–New York spread; large *registered* draws in a delivery month tell you deliveries are being met from the shelf. Daily changes are mostly noise; the **level vs open interest** is the "coverage ratio" (§4.5) that gets abused online.
- **Evidence:** theory-of-storage literature ties inventories to the basis (Gorton, Hayashi & Rouwenhorst 2013, *Review of Finance*), but for gold inventories are never binding and no study shows COMEX stock changes predict the price. **Context only.**
- **Already in app:** no.
- **Verdict: PUBLISH-CONTEXT (core of the "physical" panel) when access is restored; until then LINK-ONLY.**
- **Ingest notes:** `xlrd` (legacy .xls); parse rows by label; store depository × category × date; derive daily received/withdrawn; compute coverage = GC OI × 100 / registered.

### 2.8 COMEX delivery notices: Metals Issues & Stops (daily) and YTD by firm  ·  **PUBLISH-CONTEXT if access, else LINK-ONLY**
- **Get it:** `https://www.cmegroup.com/delivery_reports/MetalsIssuesAndStopsReport.pdf` (daily, 2 pages) and `MetalsIssuesAndStopsYTDReport.pdf` (28 pages). **403 from this IP**; verified via archive snapshots `20261025161618` / `20261025223808`.
- **Sample (daily):** "CONTRACT: OCTOBER 2026 COMEX 100 GOLD FUTURES · SETTLEMENT 3,991.10 · INTENT DATE 10/23/2026 · DELIVERY DATE 10/27/2026": issued — Dorman 1, JP Morgan Securities (C) 6, StoneX (C) 3, Advantage (C) 14; stopped — Goldman (H) 4, Wells Fargo (H) 13, CME 7; **total 24 / 24; month-to-date 13,479 contracts (1.35M oz ≈ 41.9 t)**. YTD report: firm × month × Issued/Stopped with C (customer) / H (house) flags.
- **What it tells you:** who is taking physical delivery (a "stop") and who is delivering ("issue"); house accounts (H) stopping = banks taking metal for their own book. Deliveries happen only in the delivery month; the ratio deliveries ÷ OI at first notice (typically 2–6% for gold) is the normal "paper settles, metal rarely moves" picture; a spike is news. The bulletin's "3,208 settled to-date" and this report's "13,479 MTD" measure different things (open question 4).
- **Who uses it:** physical desks, Bloomberg `CTM`→deliveries; gold commentators read the YTD file to say "JPM stopped X tonnes".
- **Evidence:** context only.
- **Verdict: PUBLISH-CONTEXT (delivery-month panel) if access, else LINK-ONLY.**

### 2.9 COMEX options data (OI by strike, settlements, QuikStrike, CVOL, Section 63)  ·  **BLOCKED / UNVERIFIED → LINK-ONLY**, with one derived metric from §2.1
- **Get it (intended):** Daily Bulletin Section 63 (metals options), CmeWS `Settlements/Options/Settlements/{id}/OOF` and `Volume/Details/O/…` JSON (used by CME's option pages), QuikStrike (`cmegroup.com/tools-information/quikstrike/…`, JS app), CVOL (gold implied-volatility index). **All on www → 403; none verified.** The Wayback availability API rate-limited me before I could check archived option bulletins.
- **What the FTP does give:** daily total OI and volume per option product (§2.1): **OG calls 631,061 vs puts 259,338 → put/call OI 0.41** on 22 Oct; weekly series volume; OMG (micro gold options) negligible. No strikes, no implied vol.
- **What it tells you:** put/call OI ratio is positioning context (a crowd long calls); the strike distribution shows where dealers' hedging pins/accelerates price; CVOL is the market's expected move (≈ VIX for gold).
- **Evidence:** context only (no free study on gold P/C ratio).
- **Verdict:** put/call OI ratio **PUBLISH-CONTEXT** (from §2.1); strike/IV data **LINK-ONLY** (QuikStrike in a browser) until an allowed source exists. Do not scrape.

### 2.10 CME website JSON (CmeWS: Settlements, Volume/Details, ProductCalendar, Quotes)  ·  **DO-NOT-PUBLISH (scraping)**
- **Get it (what CME's pages call):** `/CmeWS/mvc/Settlements/Futures/Settlements/437/FUT?tradeDate=…`, `/CmeWS/mvc/Volume/Details/F/437/YYYYMMDD/P`, `/CmeWS/mvc/ProductCalendar/Future/437`, `/CmeWS/mvc/Quotes/Future/437/G` (437 = GC). **403 on all five** (0.17–0.22 s). Field layouts not verified (archive had no copies).
- **Verdict: DO-NOT-PUBLISH via scraping.** The block message quotes the Data Terms of Use. Everything these endpoints carry is available from the FTP (OI by product, calendar, specs) or the bulletin PDF (per-month settlement/OI) or Yahoo (per-month last price). If the owner wants the JSON legitimately: CME Market Data (licensed) or CME DataMine (paid).

### 2.11 Yahoo Finance chart API — per-contract-month COMEX quotes (term structure fallback)  ·  **PUBLISH-CORE** (curve), already partly in app
- **Get it:** `https://query1.finance.yahoo.com/v8/finance/chart/GCZ26.CMX?range=5d&interval=1d` (and `GCG27.CMX`, `GCJ27.CMX`, `GCM27.CMX`, `GCQ27.CMX`, `GCZ27.CMX`, `MGC=F`, `SI=F`, `SIZ26.CMX`); no key.
- **Verified (26 Oct ~08:30 IST, 0.24–0.77 s each):** GCZ26 3,999.6 · GCG27 4,035.8 · GCJ27 4,081.2 · GCM27 4,115.0 · GCQ27 4,142.6 · GCZ27 4,209.0 (previous closes 4,142.6 / 4,176.9 / 4,210.6 / 4,246.7 / 4,283.8 / 4,355.3); MGC=F 4,000.9; SI=F 53.83 (→ ratio 74.3). Volume per month is present (Globex), **no open interest**, and the "close" is the last trade, not the settlement (vs bulletin Dec-26 settle 4,007.90).
- **Terms:** Yahoo's unofficial API, personal use; the app already relies on it (CMDT, WEI, GPO, MCXG).
- **Already in app:** `GC=F` (WEI, CMDT, BRF), `GCZ26.CMX` (GPO/MCXG fair value), `SI=F` (WEI, CMDT, GPO context). **The per-month curve is new.**
- **Verdict: PUBLISH-CORE** for the curve and calendar spreads (one chart, on the COMEX panel only), as the no-permission-needed stand-in for §2.6; label it "last trade, not settlement".

### 2.12 CFTC Commitments of Traders, public reporting API  ·  cross-check only (G-COT's brief)
- **Verified:** `https://publicreporting.cftc.gov/resource/6dca-aqww.json?cftc_contract_market_code=088691&$order=report_date_as_yyyy_mm_dd DESC&$limit=3` → 200 in 1.3 s: **20 Oct 2026: OI 402,279 (+5,934); non-commercial long 237,142 / short 37,277; commercial long 59,531 / short 295,113.** Weekly (Tuesday positions, published Friday 15:30 ET = Sat 01:00 IST).
- **Use here:** validates that CME's daily product OI (§2.1) is the same universe the COT splits by trader type; the daily OI change tells you *that* positions opened or closed, COT tells you *who*. Weekly → **the daily OI series is the only free daily "who closed" proxy.**

### 2.13 SHFE daily market data JSON (Shanghai gold futures `au`)  ·  **PUBLISH-CONTEXT**
- **Get it:** `https://www.shfe.com.cn/data/tradedata/future/dailydata/kxYYYYMMDD.dat` (JSON; the old `/data/dailydata/kx/` path is 404). Referer header helps.
- **Verified:** `kx20261023.dat` 200 in 2.3 s, 122,744 B; `o_curinstrument[]` rows with `PRODUCTID, DELIVERYMONTH, PRESETTLEMENTPRICE, OPENPRICE, HIGHESTPRICE, LOWESTPRICE, CLOSEPRICE, SETTLEMENTPRICE, ZD1_CHG, ZD2_CHG, VOLUME, OPENINTEREST, OPENINTERESTCHG, TURNOVER, TASVOLUME`. **au2612 settle 869.20 CNY/g, OI 198,578 (−9,623), volume 286,554; au2702 OI 101,168; total `au` OI 368,618 (−11,127), volume 366,650** (1 kg per lot).
- **Published / lag:** daily after the 15:00 Beijing close (night session 21:00–02:30 is included in the next day). History: dated files (not probed beyond one).
- **What it tells you:** China is the largest physical market; SHFE OI/volume and the SHFE–COMEX price gap (after CNY and 31.1035 g/oz conversion) show Chinese speculative appetite and the Shanghai premium/discount (the premium itself is better taken from SGE, §2.14, and belongs to the Asia brief).
- **Terms:** SHFE data pages are public; redistribution not stated. **Verdict: PUBLISH-CONTEXT** (one line: SHFE front OI change and premium), computed in the data-service, not shown on every page.

### 2.14 SGE (Shanghai Gold Exchange) JSON endpoints  ·  **PUBLISH-CONTEXT** (Asia brief owns the premium)
- **Verified:** `https://www.sge.com.cn/graph/quotations` → JSON `{times[782], data[782], min 855, max 872, heyue "Au99.99", now, delaystr "2026年10月26日 02:29:55"}` (one-minute delayed intraday Au99.99, CNY/g, 1.7 s); `https://www.sge.com.cn/graph/DayilyJzj` → `{zp:[[epoch_ms, CNY/g]…], wp:[…]}` = **Shanghai Gold Benchmark AM/PM fix, daily since 19 Apr 2016 (first value 256.92)**, 117 KB in 2.6 s. The English "Delayed Quotes" page (`en.sge.com.cn/data_DelayedQuotes`) renders zeros without JS (values come from these XHRs). The Chinese menu also lists `/sjzx/mrhqsj` (daily data), `/sjzx/jzj` (benchmark), `/sjzx/goldEtf`, `/sjzx/hjzjckll` (gold lease reference rates).
- **Terms:** SGE lists "Licensed Market Data Distributors"; treat as view-only, no redistribution. **Verdict: PUBLISH-CONTEXT** (Shanghai benchmark vs COMEX in one number, on the gold page only).

### 2.15 JPX / OSE gold (Tokyo)  ·  **LINK-ONLY**
- **Verified:** `https://www.jpx.co.jp/english/markets/derivatives/trading-volume/index.html` (200, 1.1 s) links `…/vk0khi000002j00k-att/20261023open_interest_e.xlsx` (200, 131 KB): Gold (Standard) Oct-26 OI 693, Pocket Gold 100 Dec-26 7,384, Gold Mini 179, Gold Rolling-Spot 8,949, Options on Gold Futures 0. Tiny next to COMEX (401k) and SHFE (369k). **LINK-ONLY.**

### 2.16 DGCX (Dubai) · Borsa Istanbul · Stooq · Nasdaq Data Link · Kitco
- **DGCX** `dgcx.ae` and its daily market report: **403 Cloudflare "Just a moment"** (script-blocked) → **UNVERIFIED, LINK-ONLY** (Dubai gold is a small INR-relevant venue; the Shariah/kilobar contract is quoted in USD).
- **Borsa Istanbul** precious-metals pages: root 200 (2.1 s) but both market-data URLs tried: *server disconnected* → **UNVERIFIED, LINK-ONLY** (Turkish retail demand matters for WGC flows, not for intraday trading).
- **Stooq** `stooq.com/q/d/l/?s=xauusd&i=d`: 200 but a 796-byte "This site requires JavaScript" gate → **UNVERIFIED, DO-NOT-PUBLISH** (Yahoo already covers it).
- **Nasdaq Data Link CHRIS/CME_GC1** (the old free continuous-futures history with OI): **403, discontinued** → **DO-NOT-PUBLISH**; the FTP archive (§2.1) replaces it for OI, Yahoo for prices.
- **Kitco** `kitco.com/charts/gold`: 200 (0.6 s, 119 KB), `robots.txt` allows all; terms at `/terms-of-use` (not read); content is a licensed spot feed and news → **LINK-ONLY** (already a "manual check" link in GPO). Nothing in it is unavailable elsewhere; do not add a second gold-price source.

### 2.17 CME SPAN risk-parameter archive  ·  **LINK-ONLY**
- `ftp://ftp.cmegroup.com/pub/span/archive/cme/2013…2025` (and `MOD`, `nr`, `xml`); no 2026 directory found. Margins for display come from §2.4 instead.

---

## 3. Contract specs the owner asked for (verified from the product reference file and calendar; CME spec pages were unreachable)

| Contract | Code | Size | Quote | Tick | Settlement | Months / expiry (verified Dec-26) | Role for an MCX trader |
|---|---|---|---|---|---|---|---|
| COMEX Gold | **GC** | 100 oz (3.11 kg) | $/oz | $0.10 ($10) | **Physical** (registered 100-oz bar or 3 × 1-kg bars, 995+) | Feb/Apr/Jun/Aug/Oct/Dec liquid + serial months; Dec-26 FND 30 Nov, LTD 29 Dec 12:30 CT (23:00/24:00 IST) | The benchmark; MCX GOLD (1 kg) ≈ 0.32 GC. MCX's 09:00–23:30 IST overlaps Globex (which runs 18:00–17:00 CT, i.e. 04:30→03:30 IST, with a 60-minute break). |
| Micro Gold | **MGC** | 10 oz | $/oz | $0.10 ($1) | Physical via accumulated certificates (ACE) — practically rolled | Same dates as GC; OI 124,151 and **daily volume above GC's** (351,808 vs 237,695): retail's contract | Closest to MCX GOLDM (100 g = 3.2 oz) in spirit. |
| 1-Ounce Gold | **1OZ** | 1 oz | $/oz | $0.25 | **Cash** (financial, `SettlMeth C`), no notice days | Launched 13 Jan 2025 (FirstTrdDt of Dec-26 row); LTD 25 Nov 2026 for Dec-26; OI 87,158 | Comparable to MCX GOLDPETAL (1 g) in size tier; cash-settled so no delivery risk. |
| E-mini Gold | **QO** | 50 oz | $/oz | $0.25 ($12.50) | **Cash** (converted from physical; no FND in calendar) | Listed (Dec-26, Feb-27 …), OI 8,551, volume ~3,600/day: alive but thin | Avoid: liquidity is in MGC. |
| Silver | **SI** | 5,000 oz | $/oz | $0.005 ($25) | Physical | Dec-26 FND 30 Nov, LTD 29 Dec; OI 114,637 | For the gold/silver ratio. |
| Micro silver / 100-oz silver | **SIL / SIC** | 1,000 / 100 oz | $/oz | $0.005 | Physical / cash | OI 24,507 / 11,849 | — |
| Gold options | **OG** (+ weeklies OG1–5, G1M…G5R, micro OMG) | 1 GC | $/oz | — | American, into GC | Monthly expiry ≈ 4 business days before month-end of the month preceding the futures month (OOF rows in calendar); weeklies every weekday | P/C OI 0.41 on 22 Oct. |
| Shanghai Gold futures on COMEX | **SGU / SGC** | 1 kg | USD or CNH per g | — | Cash to the SGE benchmark | In the reference file; OI not material | Context: CME's own Shanghai-price contract. |
| SHFE gold | **au** | 1 kg | CNY/g | 0.02 | Physical (SGE-registered) | Monthly; Dec-26 front OI 198,578 | China's price; night session 21:00–02:30 Beijing. |
| SGE spot / Au(T+D) | Au99.99, Au(T+D) | 1 kg / 1 kg deferred | CNY/g | — | Physical | Shanghai Gold Benchmark AM/PM (CNY/g, since 2016) | The "Shanghai premium" base. |
| DGCX gold, TOCOM/OSE gold, Borsa Istanbul | — | 1 kg / 1 kg / 1 kg-ish | USD/oz, JPY/g, TRY/g | — | — | Not verified today | LINK-ONLY context. |

Pitfalls: (1) Yahoo's `GC=F` is "front month by Yahoo's rule", which flips a few days before FND; after 25 Nov `GC=F`
will be Feb-27 while MCX Dec still trades to 4 Dec. (2) Bulletin settlement ≠ Yahoo close (Dec-26: 4,007.90 vs
4,001.30 last on 23 Oct). (3) CME trading-hour abbreviations are **CT**; FND/LTD "12:30 PM" is CT = 23:00 IST (24:00
IST in winter after the US clock change on 1 Nov 2026).

---

## 4. Concepts, for the newcomer and the professional

**4.1 Contango and backwardation (the term structure).** Beginner: a December contract and a February contract are two
prices for the same gold delivered at different dates. When later months cost *more* (today: Dec-26 4,007.90 < Feb-27
4,041.30 < Apr-27 4,073.40 < Dec-27 4,209.00) the curve is in **contango**; it is the normal state for gold because
whoever carries metal for you must be paid interest and storage. When later months are *cheaper* (**backwardation**) the
market is paying a premium for metal *now* — physical tightness or a scramble, rare in gold and always news.
Pro: F(T2) ≈ F(T1) × (1 + (r − l) × Δt), r = USD funding (SOFR/term), l = gold lease rate. Implied carry from Dec→Feb
today: (4,041.30/4,007.90 − 1) × 365/57 ≈ **5.3% p.a.** — above SOFR, i.e. the lease rate is slightly negative/the curve
is rich; if this drops toward or below zero while the price rises, physical demand is pulling metal forward. Watch it
daily; the number comes free from §2.11 (last trade) or properly from §2.6 (settlements).

**4.2 Calendar spreads.** A spread = long one month, short another (Dec/Feb). Its price is the implied carry above;
spread *moves* carry information that outright prices hide: narrowing contango with a flat price = funding or lease
stress; a widening contango in a sell-off = longs rolling out (the Dec/Feb spread is bid during the roll because sellers
of Dec buy Feb). Pro pitfall: compare settlement-to-settlement, not Yahoo last-to-last; the two months print at
different times.

**4.3 Basis to spot.** Basis = futures − spot (London loco). Dec-26 at 4,007.90 against a spot near 3,980 would be a
+$28 basis = carry to late December. Basis beyond carry = the EFP premium (New York bars worth more than London bars:
Jan–Mar 2025 the EFP blew out to $40–60 on tariff fears and 20M oz flew to COMEX vaults). CME does not publish the EFP
price (§2.2); the LBMA/spot brief should supply a spot series so the terminal can show basis minus theoretical carry.

**4.4 EFP: what the volume (and the price, when you can get it) means.** An EFP is a swap of a futures position for an
equal amount of physical/OTC gold between two parties, at a negotiated differential, then *registered* with CME (so it
shows in the ex-pit column and in §2.2). It is how bullion banks move exposure between London (OTC, unallocated) and
New York (futures). High EFP volumes with a *positive* EFP price = physical being pulled to New York (demand for
deliverable bars); negative EFP = metal leaving/New York over-supplied. For a MCX trader the parallel is the MCX
premium over landed COMEX gold (already modelled as `implied_premium_pct` in `gold_preopen.py`).

**4.5 "Paper vs physical" coverage ratio and its abuse.** Definition: open interest in ounces ÷ registered ounces.
Today: GC 403,397 × 100 = 40.34M oz ÷ 14.81M registered = **2.72×** (÷ combined 23.28M = 1.73×; all gold futures incl.
MGC/1OZ/QO ≈ 42.1M oz → 2.84×). Silver: 573M ÷ 100.5M = 5.7×. Beginner: "there are 2.7 ounces of futures for every
deliverable ounce" is true and *irrelevant* most of the time — fewer than 5% of contracts ever go to delivery, eligible
metal can be registered in a day, and shorts can deliver 1-kg or 100-oz bars from eligible stock after a warrant is
issued. Pro: the ratio only matters inside the delivery window of the front month: compare **front-month OI after FND
(still open) vs registered**; if that approaches 1 while registered is falling, a squeeze is mechanically possible
(silver, Jan–Feb 2021 and 2025–26 episodes). The internet's "100:1 paper gold" number counts *all* months and ignores
eligible: do not show it without the front-month version next to it.

**4.6 Open interest × price: the four-quadrant read, daily.** With ΔOI and Δprice from §2.1 and §2.6/§2.11:

| ΔOI | Δprice ↑ | Δprice ↓ |
|---|---|---|
| **↑** (new contracts) | **Long build-up** — buyers initiating; trend has fuel | **Short build-up** — sellers initiating; bearish conviction |
| **↓** (contracts closed) | **Short covering** — shorts buying back; rally may lack new buyers | **Long unwinding / liquidation** — longs selling out; capitulation if volume high |

Verified on the real series (FTP OI, Yahoo close): 13–14 Oct short build-up (−13, −69 with OI +4,993, +1,895), 15–16 Oct
long build-up (+62, +11; OI +1,661, +127), 21 Oct short covering (+7, OI −2,117), **22 Oct short build-up (−89.6, OI
+3,007)**, and the bulletin's 23 Oct Dec-26 line (−52.50, OI −12,246 but Feb +9,869 → mostly *roll*, not liquidation).
Pro pitfalls: (a) use product OI, and during the roll read front+next together; (b) OI changes on expiry, delivery and
option exercise days are mechanical; (c) daily OI is published T+1 (≈14:00 IST) while COT is weekly (Sat 01:00 IST):
the daily series is the only free way to answer "which positions were closed *yesterday*"; (d) it never says *who* — COT
does, once a week, and the two reconcile (CFTC OI 402,279 vs CME 402,507 on 20 Oct).

**4.7 Delivery-month dynamics.** Timeline for Dec-26 GC: 25 Nov = last day for 1OZ/QO and for most speculators to be out
(brokers require it before FND); **27 Nov first intent / 30 Nov first notice**: shorts can tender, longs still holding can
be assigned; 1–31 Dec delivery days; 29 Dec LTD; 30 Dec last notice/last EFP. OI collapses from ~300k to <5% by FND;
what remains delivers (Oct-26: 13,479 contracts MTD by 23 Oct). Tells: registered stock *rising* into FND (shorts
preparing bars) vs OI *staying high* (longs intending to stand) is the squeeze set-up; the issues/stops report then names
the firms (H = own book).

**4.8 Daily vs weekly vs monthly, as the owner asked.** Daily: OI/volume by product (FTP), settlement curve (bulletin or
Yahoo), warehouse flows and deliveries (www), EFP prints (FTP), SHFE/SGE close. Weekly: COT (CFTC) = who; weekly options
expiries. Monthly: month-end OI y/y (`webmthly`), contract roll, margin changes.

---

## 5. Repetition audit and where this should live

The gold price is on five pages; silver on three; USD/INR on four. Any COMEX panel must therefore **not** show the
front price again. Proposed single home: a **"COMEX" section inside the gold page (MCXG or a new GOLD page), with WEI
only linking to it** (the owner wants gold in World Markets too: a one-line "COMEX OI Δ / curve carry / roll days" strip
there, no prices). Contents, top to bottom: (1) OI/price quadrant tape for GC (last 20 days) + OI by product; (2) term
structure chart (Yahoo months; settlement when allowed) with implied carry; (3) roll countdown (FND/LTD from §2.3/2.4)
and margin % of notional; (4) EFP tape; (5) physical panel (registered/eligible/pledged, flows, coverage front-month and
all-months) — LINK-ONLY until access; (6) deliveries — LINK-ONLY until access; (7) P/C OI; (8) context line: SHFE front
OI Δ, Shanghai benchmark vs COMEX, gold/silver ratio. The Pre-Open desk keeps its fair-value job and gains the correct
COMEX month from the calendar.

---

## 6. Studies this unlocks (pre-register before building signals)

- **G-STUDY-1 (OI quadrant):** 2014→2026 daily GC OI (FTP archive) × Yahoo `GC=F` settlement proxy: does the previous
  day's quadrant predict the next 1/5/20-day return, with Newey–West t-stats and both halves (format of
  `reports/fii_positioning`)? Expect "context only" (Hong–Yogo is monthly), but it is a one-day job once ingested.
- **G-STUDY-2 (roll pressure):** front/next OI ratio and days-to-FND vs the Dec/Feb spread and MCX premium.
- **G-STUDY-3 (physical):** registered-stock changes and EFP volume vs next-week returns — only after access.

---

## 7. Open questions

1. Why is this IP blocked by cmegroup.com (every path, since before this program)? Shared ISP NAT, a past experiment, or
   a browser extension? The owner should load `https://www.cmegroup.com/markets/metals/precious/gold.volume.html` in a
   normal browser; if blocked there too, email gcc@cmegroup.com (the message invites it) stating personal, non-commercial use.
2. Terms: is a once-daily download of three public files (warehouse XLS, issues/stops PDF, bulletin PDF) acceptable
   "personal use", given the Data Terms prohibit "automated means"? Owner decision; the FTP route has no such wording.
3. Product reference file: meaning of `MaintMargin` (1,400 for GC) and whether `InitMargin` is the speculator or hedger rate.
4. Bulletin "deliveries settled to-date 3,208" vs Issues & Stops "month-to-date 13,479" for Oct-26: different definitions
   (intents vs settled deliveries?) — resolve from CME's bulletin legend once reachable.
5. FTP server clock time zone (Central assumed from the calendar stamp) → exact IST arrival of `daily_volume.xlsx`.
6. Yahoo `GCZ26.CMX` last vs CME settlement: acceptable error for the curve chart? (23 Oct: 4,001.30 vs 4,007.90.)

## 8. Owner actions

1. Decide the www.cmegroup.com question (open questions 1–2). Until then the terminal gets FTP + Yahoo only.
2. Approve a DuckDB ingest in data-service: `cme_daily_voi` (from `daily_volume_*.xlsx`, backfill 2014→), `cme_efrp`,
   `cme_calendar`, `cme_prf` (daily snapshot incl. margins); scheduler jobs at ~15:30 IST (daily volume) and 20:00 IST
   (EFRP), outside the 07:45–09:20 and 18:30–21:15 freeze windows.
3. Approve the COMEX panel layout in §5 and the "no second gold price" rule.
4. Ask G-LBMA/spot brief for a free spot series so basis and the EFP proxy can be shown; ask G-COT to align its weekly
   OI with `cme_daily_voi` for the daily-vs-weekly view.
5. Pre-register G-STUDY-1 (PLAN.md) before any quadrant "signal" is shown as more than context.

---

## Appendix A — verification log (status · latency · bytes · what was seen)

| # | Source | Result |
|---|---|---|
| 1 | www.cmegroup.com CmeWS Settlements/Volume/Calendar/Quotes (5 URLs) | 403 · 0.17–0.22 s · 602 B · "IP blocked … Data Terms of Use" |
| 2 | www.cmegroup.com daily_bulletin Section62/63 current + prelim (3) | 403 |
| 3 | www.cmegroup.com /ftp/, /ftp/pub/settle/, /ftp/bulletin/, /ftp/pub/bulletin/ (4) | 403 |
| 4 | www.cmegroup.com delivery_reports Gold_Stocks.xls, Silver_stocks.xls, MetalsIssuesAndStops*.pdf, notices page (5) | 403 |
| 5 | curl (browser UA) homepage · headless Chromium gold.volume.html | 403 · ERR_HTTP2_PROTOCOL_ERROR |
| 6 | ftp.cmegroup.com root listing | 226 OK · 2.6 s · 15 directories |
| 7 | ftp daily_volume.xlsx / 9 dated files | 200-equiv · 4.1–4.8 s · 99–108 KB · trade date 10/22/2026, archive 2014-01-02→ (3,227 files) |
| 8 | ftp efrp-report_20261023.csv | 3.6 s · 33,597 B · 19 GOLD EFP rows = 3,115 RT |
| 9 | ftp span/util/product-calendar-new.xml | 153 s · 38.66 MB · DATE_CREATED 10/23/2026 16:30:49 · 304 COMEX gold/silver contracts |
| 10 | ftp pub/fprf/csv/cmeg.comex.fut.prf.csv.zip | 4.1 s · 46 KB · BizDt 2026-10-26 · 82 columns |
| 11 | ftp webmthly/202609.zip | 11.8 s · 2.72 MB · 17 PDFs · GC month-end OI 397,291 |
| 12 | ftp settle/TCF, pub/delivery_reports, pub/span/archive | listed; no metals settlements/deliveries on FTP |
| 13 | Wayback: Gold_Stocks.xls (20261025234631), Silver_stocks.xls (20261025234600), Section62 (20261025000515), Issues&Stops (20261025161618), YTD (20261025223808) | 200 · 2–5 s · parsed (availability API: 429) |
| 14 | Yahoo chart GC=F, GCZ26…GCZ27, MGC=F, SI=F, SIZ26 (10) | 200 · 0.24–0.77 s · prices listed in §2.11 · no OI field |
| 15 | CFTC publicreporting 6dca-aqww code 088691 | 200 · 1.3 s · 20 Oct OI 402,279 |
| 16 | Nasdaq Data Link CHRIS/CME_GC1 | 403 |
| 17 | SHFE kx20261023.dat (new path) / old path | 200 · 2.3 s · 122,744 B / 404 |
| 18 | SGE graph/quotations · graph/DayilyJzj · en delayed-quotes HTML · cn pages | 200 · 1.7 s / 2.6 s / 0.8 s / 1–1.9 s |
| 19 | JPX trading-volume page + 20261023open_interest_e.xlsx | 200 · 1.1 s / 1.0 s · 131 KB |
| 20 | DGCX home + daily report | 403 Cloudflare challenge |
| 21 | Borsa Istanbul root / precious-metals pages | 200 · 2.1 s / server disconnected ×2 |
| 22 | Stooq xauusd, xagusd | 200 · 796 B JS gate |
| 23 | Kitco robots.txt, charts/gold | 200 · allow all · 119 KB |

Files: `samples/daily_volume_2026*.xlsx`, `samples/efrp-report_20261023.csv`, `samples/comex_gold_silver_calendar.csv`,
`samples/prf/cmeg.comex.fut.prf.csv`, `samples/gc_daily_oi_series_oct2026.csv`, `samples/comex_gold_family_daily_oi_oct2026.csv`,
`samples/wb_gold_stocks.xls` (+`_parsed.csv`), `samples/wb_silver_stocks.xls`, `samples/wb_bulletin_s62.pdf`,
`samples/wb_issues_stops.pdf`, `samples/wb_issues_stops_ytd.pdf`, `samples/shfe_daily_new.json`, `samples/sge_graph_quotations.json`,
`samples/sge_dayilyjzj.json`, `samples/jpx_20261023_open_interest_e.xlsx`, `samples/yahoo_gc_months.json`, `samples/cftc_gold_legacy_fo.json`.
