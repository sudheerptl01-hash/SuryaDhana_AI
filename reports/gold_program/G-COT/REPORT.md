# G-COT · CFTC Commitments of Traders for COMEX gold

**SuryaDhana GOLD program · research brief G-COT · written 26 Oct 2026 (Mon) from this Mac, every source fetched live that
morning.** Output directory: `reports/gold_program/G-COT/` (this report, `data/` with the full gold history in CSV, two
charts, `scratch/` with the scripts). Nothing outside this directory was touched; no live service, no ICICI call.

---

## 0. Findings (the verdict first)

**Verdict: PUBLISH-CONTEXT.** The Commitments of Traders (COT) report is the only free, official, machine-readable
answer to "who is long and who is short COMEX gold, and who added or closed this week". It explains the week that
just happened and shows when a trader group is crowded. It does **not** time the next move: in our own test over
1,011–1,063 weekly reports (2006 → Oct 2026, G-STUDY COT-1 below) no positioning signal cleared t ≥ 2 in both halves
of the sample, and the same-week correlation between the gold move and fund flow is 0.64 (Spearman): positioning
follows price. Show it, label it "weekly, 3 days old on arrival, context only", and never let it place a trade.

| Question | Answer | Evidence |
|---|---|---|
| Free and machine-readable? | Yes. CFTC Public Reporting API (Socrata, JSON/CSV, no key; a free app token lifts the throttle), weekly text files, zipped history back to 1986. US-government work → public domain. | 7 API datasets, 15 weekly files and 44 archive zips all answered 200 on 26 Oct 2026; gold rows from API and archives identical (2,113 / 1,822 / 1,237 / 1,237) |
| Where is gold? | Legacy report (1986→) and Disaggregated report (2006→), futures-only and futures+options, code **088691** GOLD (100 oz), 088695 MICRO GOLD (10 oz, Dec 2020→), 088LM1 Coinbase 1-oz gold (6 rows, Dec 2025 → Sep 2026). **Not** in Traders in Financial Futures, **not** in the Commodity Index Trader supplement. | API aggregates per contract code (§3.4) |
| When does it arrive? | Tuesday-close positions released Friday 15:30 ET = **Saturday 01:00 IST** in US summer time, **02:00 IST from 7 Nov 2026** (US clocks change 1 Nov). Six 2026 releases slip to a Monday for US holidays (next: 16 Nov, 30 Nov, 28 Dec). The API rows landed at 15:30:13 ET on Fri 23 Oct. By Monday's MCX open the snapshot is 6 days old. | release-schedule page, Socrata `rowsUpdatedAt`, zip `Last-Modified` 19:28 GMT (§3.5) |
| Does positioning predict gold? | **Not usably.** 52-week fund-positioning extremes: the top-minus-bottom spread flips sign between 2006–16 and 2016–26. Weekly fund flow: slightly contrarian (−0.29 %/SD over 20 sessions, t −1.9), never significant. Washed-out positioning (bottom decile of fund net % OI) preceded +5.2 % over 65 sessions (t 2.6 full sample, 1.4 / 1.3 in the halves): a backdrop, not a trigger. | §9, `data/study_tables.md`, `cot_gold_study_deciles.png` |
| What it says now (as of Tue 20 Oct 2026) | Funds (managed money) net long 104,206 contracts = 10.4 Moz ≈ 324 t ≈ $43 bn, cut for **8 straight weeks** from 144,747 on 25 Aug while gold fell from $4,694 to $4,143 (−12 %). 52-week COT index 26: no longer crowded. Swap dealers net short 220,799 absorb the other side; commercials covered 6,949 shorts this week; options add +4,479 to the funds' net. | §8, `data/cot_gold_latest.json`, `cot_gold_positioning_2010_2026.png` |

**What to build (summary; detail in §12–13):** one weekly positioning panel (MCXG or a GOLD page) fed from a DuckDB
table `cot_gold` that a Saturday 02:30 IST job fills from the API; WorldMarkets/CMDT get a one-line chip that links
to it, never a second copy. Nothing from COT goes into the Decision Desk or the gold ticket.

---

## 1. For someone new to gold: what this report is

- **Futures contract.** A standardised promise to buy or sell 100 troy ounces of gold (3.11 kg) on a future date,
  traded on COMEX (part of CME Group, New York). Prices on MCX in Mumbai are, to a first approximation, the COMEX
  price × the USD/INR rate (the app's fair-open model does exactly this).
- **Open interest (OI).** The number of contracts that exist and have not been closed. Every contract has one long
  (the buyer) and one short (the seller), so total longs always equal total shorts.
- **Long / short.** Long = profits if gold rises. Short = profits if gold falls. A miner selling futures to lock in
  a sale price is short; a hedge fund betting on a rally is long.
- **The CFTC.** The US Commodity Futures Trading Commission, the regulator. Every broker reports to it daily the
  positions of any customer holding **200 or more gold contracts** in any single month (17 CFR 15.03, verified; 20,000
  oz ≈ $83 m at $4,143). Those are "reportable" traders. The remainder of OI is "non-reportable": small traders,
  whose count and type are unknown.
- **The COT report.** Every Friday at 15:30 New York time the CFTC publishes, for the previous Tuesday's close,
  how much of the open interest each *type* of trader holds long, short and in spreads. It is the only public
  view of positioning; names are never disclosed, only categories.
- **Two ways of categorising the same traders.**
  - **Legacy (since 1986):** *commercial* (hedgers: miners, refiners, jewellers, bullion banks' dealing desks),
    *non-commercial* (speculators: funds, CTAs, prop desks) and *non-reportable* (small traders).
  - **Disaggregated (since 2006):** *producer / merchant / processor / user* (physical industry), *swap dealers*
    (banks that run over-the-counter gold books and hedge them on COMEX), *managed money* (hedge funds, CTAs,
    commodity pools) and *other reportables* (everyone else large: prop firms, family offices, options
    market-makers). Commercial = producer/merchant + swap dealer; non-commercial = managed money + other
    reportables. We verified the arithmetic on the 20 Oct 2026 numbers (§5).
- **Spreading.** A trader long one month and short another (say long Dec, short Feb) is not betting on the price
  level. The CFTC nets each speculator's long and short and reports the overlap as "spreading" so the long and
  short columns show only directional exposure. Commercials in the legacy report have no spreading column (their
  spreads sit inside long and short), which is why disaggregated numbers do not add up to legacy ones without
  adding the swap-dealer spreading column to both sides.
- **Net position** = long − short, per group. The number everyone quotes ("funds are net long 104k") is the
  managed-money or non-commercial net.
- **The lag.** Positions are as of Tuesday; you see them Friday evening New York, i.e. in the small hours of
  Saturday in India. A lot can happen in three days: between the 20 Oct snapshot and the 23 Oct release gold fell
  3.3 %.

## 2. The question the owner asked, answered plainly

*"Which position got closed, who are short, who are long, daily and weekly."*

- **Weekly, yes.** For each group COT gives long, short, spread, and the change since last week. A fall in a
  group's longs = that group closed longs (sold out); a fall in its shorts = it covered shorts (bought back); a rise
  = new positions. §7 gives the full decomposition and a worked example.
- **Daily, no.** There is no daily COT. The CFTC collects daily data but publishes only Tuesday. Daily
  proxies, each covered by another brief: CME's daily OI and volume by contract month (G-COMEX), gold ETF holdings
  (SPDR/iShares, daily), the MCX contract OI the app already reads from ICICI's security master (`open_interest_lots`
  in `/api/commodity/gold-preopen`), and NSE/MCX participant-wise OI where published.
- **Who, by name: never.** Only categories. "Swap dealers" is the closest you get to "the bullion banks".
- **Per contract month: no.** COT aggregates all expiry months of GC into one line ("All"; the "Old"/"Other" crop-year
  split is always All = Old, Other = 0 for gold). The December-vs-February question is a CME daily-OI question.

---

## 3. Sources verified live (26 Oct 2026, 05:30–06:00 IST)

All fetched with `curl` / `httpx` and a normal browser User-Agent, one request every 1–2 s. Latency is the wall-clock
of the single request from Mumbai-routed home broadband; sizes are bytes received.

### 3.1 Weekly "viewable" reports on cftc.gov (current week only, human layout)

| File | Format | Status · latency · size | Gold block present | What it shows |
|---|---|---|---|---|
| https://www.cftc.gov/dea/futures/deacmxsf.htm | Legacy, futures-only, **short** format, COMEX | 200 · 0.26 s · 14.6 KB | yes, `GOLD - COMMODITY EXCHANGE INC. Code-088691`, "FUTURES ONLY POSITIONS AS OF 10/20/26" | positions, changes, % OI, number of traders for non-commercial / commercial / non-reportable |
| https://www.cftc.gov/dea/futures/deacmxlf.htm | Legacy, futures-only, **long** format, COMEX | 200 · 0.29 s · 42.7 KB | yes | as above plus **concentration ratios** (4 and 8 largest, gross and net) and the old/other split |
| https://www.cftc.gov/dea/options/deacmxsof.htm | Legacy, futures **+ options** combined, short | 200 · 0.93 s · 14.6 KB | yes | same layout on delta-adjusted combined positions |
| https://www.cftc.gov/dea/options/deacmxlof.htm | Legacy, combined, long | 200 · 0.26 s · 42.7 KB | yes | with concentration |
| https://www.cftc.gov/dea/futures/other_sf.htm | **Disaggregated**, futures-only, short ("other" = metals and everything not ag/petroleum/gas) | 200 · 0.37 s · 126 KB | yes | producer/merchant, swap dealer, managed money, other reportables, non-reportable |
| https://www.cftc.gov/dea/futures/other_lf.htm | Disaggregated, futures-only, long | 200 · 0.43 s · 256 KB | yes | plus concentration, trader counts per sub-column |
| https://www.cftc.gov/dea/options/other_sof.htm | Disaggregated, combined, short | 200 · 0.93 s · 126 KB | yes | |
| https://www.cftc.gov/dea/options/other_lof.htm | Disaggregated, combined, long | 200 · 0.45 s · 256 KB | yes | |
| https://www.cftc.gov/dea/futures/financial_lf.htm | Traders in Financial Futures | 200 · 0.42 s · 223 KB | **no gold** (currencies, rates, equity indices, GSCI) | not relevant to gold |

Sample, the gold block of `deacmxsf.htm` exactly as published (positions as of 20 Oct 2026, released 23 Oct):

```
GOLD - COMMODITY EXCHANGE INC.                                       Code-088691
FUTURES ONLY POSITIONS AS OF 10/20/26
      NON-COMMERCIAL      |   COMMERCIAL    |      TOTAL      | NONREPORTABLE
  LONG  | SHORT  |SPREADS |  LONG  | SHORT  |  LONG  | SHORT  |  LONG  | SHORT
(CONTRACTS OF 100 TROY OUNCES)                       OPEN INTEREST:      402,279
 237,142   37,277   54,199   59,531  295,113  350,872  386,589   51,407   15,690
CHANGES FROM 10/13/26 (CHANGE IN OPEN INTEREST:      5,934)
  -8,158     -144    8,304    5,112   -1,837    5,258    6,323      676     -389
PERCENT OF OPEN INTEREST FOR EACH CATEGORY OF TRADERS
    58.9      9.3     13.5     14.8     73.4     87.2     96.1     12.8      3.9
NUMBER OF TRADERS IN EACH CATEGORY (TOTAL TRADERS:      288)
     158       59       69       53       42      241      143
```

Verdict for the app: **LINK-ONLY** (the canonical human page, for the "open the source" link); the data itself comes
from the API.

### 3.2 Weekly raw text files (current week, all markets, machine layout)

| File | Status · latency · size · lines | Note |
|---|---|---|
| https://www.cftc.gov/dea/newcot/deafut.txt (legacy futures-only) | 200 · 0.44 s · 430 KB · 376 | **no header row**; gold on lines 272–273 |
| https://www.cftc.gov/dea/newcot/deacom.txt (legacy combined) | 200 · 0.46 s · 439 KB · 384 | no header |
| https://www.cftc.gov/dea/newcot/f_disagg.txt (disaggregated futures-only) | 200 · 0.47 s · 447 KB · 277 | no header |
| https://www.cftc.gov/dea/newcot/c_disagg.txt (disaggregated combined) | 200 · 0.49 s · 461 KB · 285 | no header |
| https://www.cftc.gov/dea/newcot/FinFutWk.txt, FinComWk.txt (TFF) | 200 · 0.3 s · 77 KB · 99 | no gold |

Sample row (`f_disagg.txt`): `"GOLD - COMMODITY EXCHANGE INC.",261020,2026-10-20,088691,CMX ,01,088 ,  402279,   19715,
34498,   17737,  238536,   22079,  120970,   16764,   38634,  116172,   20513,   15565,  350872,  386589,   51407,   15690, …`
Column order follows the CFTC "Variable names" documents linked from the historical-archive page; the archive zips
carry the same columns **with** a header, so the header from a zip is the parser for these files. Verdict:
**LINK-ONLY** as a fallback when the API is down (one 450 KB download, parse by position).

### 3.3 Historical compressed archives (https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm, 200 · 0.36 s · 81 KB)

The index lists **338** zip links (`/files/dea/history/…`). Years available, per format (Text and Excel variants of each):

| Format | Multi-year zip | Yearly zips | Archive header style |
|---|---|---|---|
| Legacy futures-only | `deacot1986_2016.zip` (22.9 MB → `FUT86_16.txt` 168 MB, 146,677 rows, **1,427 gold rows**) | `deacot1986.zip` … `deacot2026.zip`; Excel `deafut_xls_YYYY.zip` 1986–2003, `dea_fut_xls_YYYY.zip` 2004–2026 | `Market and Exchange Names`, `As of Date in Form YYYY-MM-DD`, `CFTC Contract Market Code`, `Open Interest (All)`, `Noncommercial Positions-Long (All)` … (129 columns) |
| Legacy combined | `deahistfo_1995_2016.zip` (19.3 MB → `Com95_16.txt`, 132,720 rows, **1,136 gold**) | `deahistfo_1995.zip` … `deahistfo_2003.zip` (underscore), `deahistfo2004.zip` … `deahistfo2026.zip` (no underscore — a naming trap); Excel `deacom_xls_*`, `dea_com_xls_*` | same 129 columns |
| Disaggregated futures-only | `fut_disagg_txt_hist_2006_2016.zip` (12.2 MB → `F_Disagg06_16.txt`, 70,199 rows, **551 gold**) | `fut_disagg_txt_2010.zip` … `_2026.zip`; Excel `fut_disagg_xls_*` | `Market_and_Exchange_Names`, `Report_Date_as_YYYY-MM-DD`, `Prod_Merc_Positions_Long_All`, `Swap__Positions_Short_All` (double underscore) … (191 columns) |
| Disaggregated combined | `com_disagg_txt_hist_2006_2016.zip` (12.9 MB → `C_Disagg06_16.txt`, 73,248 rows, **551 gold**) | `com_disagg_txt_2010.zip` … `_2026.zip` | same 191 columns |
| TFF | `fin_fut_txt_2006_2016.zip`, `fin_com_txt_2006_2016.zip` | `fut_fin_txt_2010…2026.zip`, `com_fin_txt_*` | no gold |
| CIT supplement | `dea_cit_txt_2006_2016.zip` | `dea_cit_txt_2006…2026.zip` | no gold (agricultural only) |

Verified by downloading **44 zips (150 MB, every one 200, 0.3–6.3 s each)**: the four multi-year zips plus 2017–2026
for each gold-bearing format. The 2026 zips are refreshed every release (`Last-Modified: Fri, 23 Oct 2026 19:28:21–34
GMT`, i.e. two minutes before the 15:30 ET release). The 2026 yearly zip holds 89 gold rows (42 weeks × GOLD + MICRO
GOLD + 5 Coinbase rows). Gold rows extracted from the archives: **2,113 / 1,822 / 1,237 / 1,237**, identical to the
API; a spot check of 8 Jun 2010 matched field for field (OI 564,792; non-commercial long 270,729). Numeric fields in
the text archives are space-padded (`"  564792"`): strip before casting. Verdict: **backfill fallback and audit copy**;
the API is simpler for the same rows.

### 3.4 CFTC Public Reporting API (Socrata) — the ingest source

Host `https://publicreporting.cftc.gov`. `robots.txt`: `Crawl-delay: 1`, API paths allowed. Dataset metadata
(`/api/views/<id>.json`, 200, 2.1–3.5 s each) carries no license field; publisher "Commodity Futures Trading
Commission", contact publicreporting@cftc.gov. As a US federal work the data is public domain (17 U.S.C. §105): free
to store, chart, embed and redistribute with attribution. `cftc.gov/robots.txt` carries `Content-Signal:
search=yes, ai-train=no, use=reference` and disallows named AI *training* crawlers; this research fetched public data
on the owner's behalf with a browser User-Agent and did not train anything. Note it; it is not a restriction on the
app.

| Dataset id | Title | Columns | Gold? | Rows for 088691 · first · last |
|---|---|---|---|---|
| `6dca-aqww` | Legacy – Futures Only | 133 | yes | **1,939** · 1986-01-15 · 2026-10-20 |
| `jun7-fc8e` | Legacy – Combined | 133 | yes | **1,648** · 1995-03-21 · 2026-10-20 |
| `72hh-3qpy` | Disaggregated – Futures Only | 194 | yes | **1,063** · 2006-06-13 · 2026-10-20 |
| `kh3c-gbw2` | Disaggregated – Combined | 194 | yes | **1,063** · 2006-06-13 · 2026-10-20 |
| `gpe5-46if` / `yw9f-hn96` | TFF – Futures Only / Combined | 90 | **no** | (a `%GOLD%` search returns only "GOLDMAN SACHS COMMODITY INDEX") |
| `4zgm-a668` | Supplemental – CIT | 60 | **no** | 0 rows |

Every gold market the CFTC has ever carried (legacy futures-only, grouped by code): 088691 GOLD COMEX 1986→;
088741 GOLD – INTERNATIONAL MONETARY MARKET, 10 rows Jun–Nov 1987; 088604 / 088606 GOLD 100 TROY OZ – CHICAGO BOARD
OF TRADE, 4 rows 1988–89 and 106 rows Apr 2006 → Jul 2008; 088695 MICRO GOLD COMEX 168 rows Dec 2020→; 088LM1 GOLD
–1 TROY OUNCE – COINBASE DERIVATIVES, 6 rows 30 Dec 2025 → 8 Sep 2026 (a market is listed only in weeks when ≥ 20
traders are above the reporting level, so small contracts come and go).

**Query recipes (verified):**

```
# full history, one call per dataset (2.2–11.7 s, 8.4–9.8 MB JSON with every field, 35 MB for all four)
https://publicreporting.cftc.gov/resource/72hh-3qpy.json
   ?$where=cftc_contract_market_code in ('088691','088695','088LM1')
   &$order=report_date_as_yyyy_mm_dd ASC&$limit=50000

# weekly increment (verified: 2 rows per dataset, 1.5–2.1 s)
   ?$where=cftc_contract_market_code in ('088691','088695')
          AND report_date_as_yyyy_mm_dd > '2026-10-13T00:00:00.000'

# light CSV with chosen fields (verified: 423 bytes, 1.2 s)
https://publicreporting.cftc.gov/resource/72hh-3qpy.csv
   ?$select=report_date_as_yyyy_mm_dd,cftc_contract_market_code,open_interest_all,
            m_money_positions_long_all,m_money_positions_short_all
   &$where=cftc_contract_market_code='088691'&$order=report_date_as_yyyy_mm_dd DESC&$limit=3

# aggregates work: $select=count(*),min(report_date_as_yyyy_mm_dd),max(...) with $group
```

Throttling (dev.socrata.com/docs/app-tokens.html, 200): without an app token requests come from a shared per-IP
pool; with a free token "currently we do not throttle API requests unless those requests are determined to be
abusive". One token in `.env` as `CFTC_APP_TOKEN` (header `X-App-Token` or `$$app_token=`), optional. Default
`$limit` is 1,000: always set it, or the legacy history (1,939 rows) is silently truncated.

**Parsing traps found in the live payloads:**

1. Every value is a JSON string (`"open_interest_all": "402279"`); cast.
2. `report_date_as_yyyy_mm_dd` = `"2026-10-20T00:00:00.000"`; take the first 10 characters.
3. `cftc_commodity_code` is `"088 "` (trailing space) in 370 gold rows and `"088"` in 1,743; `cftc_market_code` is
   `"CMX "`. Never filter on these untrimmed; filter on `cftc_contract_market_code` (clean: `"088691"`).
4. Field names carry CFTC typos that you must spell exactly: `noncomm_postions_spread_all` (postions),
   `change_in_noncomm_spead_all` (spead), `swap__positions_short_all` and `swap__positions_spread_all` (double
   underscore), `traders_noncomm_spead_old`, `tot_rept_positions_short` (no `_all`), `tot_rept_positions_short_1`
   (old), `_2` (other). Legacy: `conc_gross_le_4_tdr_long` is the ALL column, `_1` old, `_2` other.
5. `id` = YYMMDD + contract code + `F` or `C` (`261020088691F`, `261020088695C`): a natural unique key per dataset.
6. `yyyy_report_week_ww` = `"2026 Report Week 42"` (CFTC's own week count, not ISO).
7. `futonly_or_combined` = `FutOnly` / `Combined`; `commodity_subgroup_name` = `PRECIOUS METALS`,
   `commodity_group_name` = `NATURAL RESOURCES`, `cftc_subgroup_code` = `N20`.
8. Cadence: semi-monthly until 30 Sep 1992 (24 rows in 1986, 31 in 1992), weekly since (52 rows/year). The `_old`
   and `_other` columns are, for gold, always equal to `_all` and zero respectively.
9. Trader counts and concentration ratios are populated from the first row (15 Jan 1986: 110 traders, top-4 net
   long 18.2 %).

Verdict: **PUBLISH-CORE as the ingest source.**

### 3.5 Release calendar

https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm (200 · 0.30 s · 48 KB) states:
"released at 3:30 p.m. Eastern time … usually on Friday … data from the previous Tuesday … Federal holidays may delay
release by one or two days." 2026 dates as published (an asterisk marks a holiday delay): Jan 05*, 09, 16, 23, 30 ·
Feb 06, 13, 20, 27 · Mar 06, 13, 20, 27 · Apr 03, 10, 17, 24 · May 01, 08, 15, 22, 29 · Jun 05, 12, 22*, 26 · Jul 06*,
10, 17, 24, 31 · Aug 07, 14, 21, 28 · Sep 04, 11, 18, 25 · Oct 02, 09, 16, 23, 30 · Nov 06, 16*, 20, 30* · Dec 04, 11,
18, 28*. Converted to IST in `data/release_calendar_2026_ist.csv`. The rest of 2026:

| Release (15:30 ET) | Positions as of | In India |
|---|---|---|
| Fri 30 Oct | Tue 27 Oct | Sat 31 Oct 01:00 IST |
| Fri 06 Nov | Tue 03 Nov | Sat 07 Nov **02:00** IST (US clocks back on 1 Nov) |
| **Mon 16 Nov** (Veterans Day) | Tue 10 Nov | Tue 17 Nov 02:00 IST |
| Fri 20 Nov | Tue 17 Nov | Sat 21 Nov 02:00 IST |
| **Mon 30 Nov** (Thanksgiving) | Tue 24 Nov | Tue 01 Dec 02:00 IST |
| Fri 04 / 11 / 18 Dec | Tue 01 / 08 / 15 Dec | Sat 02:00 IST |
| **Mon 28 Dec** (Christmas) | Tue 22 Dec | Tue 29 Dec 02:00 IST |

Observed on this cycle: files `Last-Modified` 19:28 GMT, API `rowsUpdatedAt` 19:30:13–19:30:22 GMT (Fri 23 Oct) =
15:30 ET = 01:00 IST Sat 24 Oct. So the API is as fast as the files. The 2027 schedule is not yet published (the page
says "through 2026"): re-check in December.

### 3.6 Definitions pages (used for §5–6)

- Explanatory notes https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm (200 · 0.28 s):
  open interest, reportable positions ("usually 70 to 90 percent of the total open interest"), commercial vs
  non-commercial (Form 40 self-declaration, staff may reclassify), spreading, number of traders (a trader is counted
  once in the total but in every category where it holds a position, so category counts exceed the total), old/other,
  concentration ratios, delta-adjusted options in the combined report.
- Disaggregated explanatory notes https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm
  (200 · 0.24 s): the four categories, "spreading is a computed amount equal to offsetting long and short positions
  held by a trader", classification by "predominant activity", reports published for "markets in which 20 or more
  traders hold positions equal to or above the reporting levels".
- Reporting levels 17 CFR 15.03 via Cornell LII https://www.law.cornell.edu/cfr/text/17/15.03 (200 · 1.4 s): **Gold
  200 contracts**, Silver bullion 150, Copper 100, Platinum 50 (eCFR's own API answered 406 to this client).

### 3.7 Third-party presentations

| Site | Verified | What it shows | Cost / terms |
|---|---|---|---|
| **Tradingster** https://www.tradingster.com/cot/legacy-futures/088691 | 200 · 4.3 s · 225 KB (the guessed path `/cot/futures/legacy/088691` is a 404) | the identical CFTC legacy block (OI 402,279 etc.), long-vs-short and net-vs-price charts, "View Historical Data"; new "COT Analysis / COT Signals" (ranges, extremes, net flips) | public reports and charts free, no account; Analysis/Signals free "during the preview and may require a subscription later"; Google ads; "© Tradingster.com. All rights reserved"; a privacy policy but no terms page (`/terms` 404) → **do not scrape or embed; LINK-ONLY** |
| **Barchart** https://www.barchart.com/futures/commitment-of-traders and `/futures/quotes/GC*0/commitment-of-traders` | **202 with an empty body (bot wall), also for `/terms`** → **UNVERIFIED** | from general knowledge: free COT charts per futures symbol behind ads, history/downloads in the paid "Premier" tier; I could not confirm any of this today | unknown; treat as LINK-ONLY at most |
| **Bloomberg** `CFTC <GO>` | not reachable from this machine → **UNVERIFIED** | from general knowledge: the Commitments of Traders function lists every market with the legacy and disaggregated categories, weekly history, net-position charts and each series as an Index-class ticker usable in charts and spreadsheets; also the COT tab on the contract page | Bloomberg Professional subscription (order of US$25–30k per year); nothing from it may be redistributed. Everything it shows for gold is derivable from the free CFTC data in this report |
| **Kitco** https://www.kitco.com/charts/gold (the owner's link) | 200 · 1.2 s · 119 KB; title "Gold Price Today \| Price of Gold Per Ounce \| 24 Hour Spot Chart" | a live spot chart; **zero mention of CFTC or COT** | terms at `/terms-of-use` and `/legal/terms-and-conditions` not read; the app already shows COMEX GC via Yahoo (WorldMarkets, CMDT, gold pre-open), so Kitco stays a manual-check link as today |

### 3.8 Price series used for the study

- Yahoo `GC=F` daily closes, `https://query1.finance.yahoo.com/v8/finance/chart/GC=F?period1=…&period2=…&interval=1d`:
  200 · 1.9 s · 605 KB · **6,564 rows, 30 Aug 2000 → 26 Oct 2026**, saved as `data/gc_f_daily_yahoo.csv`. Trap:
  `range=max&interval=1d` silently returns **monthly** bars (269 rows); use explicit epochs.
- FRED LBMA fixes `GOLDPMGBD228NLBM` / `GOLDAMGBD228NLBM`: **404 with a JavaScript challenge page** on both a browser
  UA and a plain `curl` (the app's note that FRED prefers a plain client did not help here). Not needed for this brief.

---

## 4. The gold contracts inside COT

| Code | Market | Unit | History | Latest (20 Oct 2026) | Who holds it |
|---|---|---|---|---|---|
| 088691 | GOLD – COMEX (GC) | 100 troy oz = 3.11 kg | 1986-01-15 → (1,939 reports) | OI 402,279 = 40.2 Moz ≈ 1,251 t; combined fut+opt OI 532,443 | the institutional contract; this is "the" COT gold |
| 088695 | MICRO GOLD – COMEX (MGC) | 10 oz | 2020-12-01 → (168) | OI 116,156 (3 % of GC in ounces); managed money long 902 / short 903 (absent); other reportables 55,634 L / 81,312 S; non-reportable 43,955 L / 26,275 S | retail and prop; a read on small speculators |
| 088LM1 | GOLD – 1 TROY OUNCE – Coinbase Derivatives | 1 oz × $2,300 | 2025-12-30 → 2026-09-08 (6 rows) | dropped out (fewer than 20 reportable traders) | curiosity |

The owner asked to "choose the contract different": COT has no per-expiry view, so the app's contract picker (MCX
Dec ↔ GCZ26) does not apply here; the positioning line is for GC as a whole. MCX GOLD, GOLDM, GOLDPETAL have no COT
equivalent (MCX is not a CFTC market); if MCX publishes participant-wise OI it belongs to the G-MCX brief.

---

## 5. Field dictionary (API ↔ archive ↔ report label) for gold

Legacy (`6dca-aqww`, `jun7-fc8e`), the `_all` set; `_old`/`_other` duplicates omitted:

| Report label | API field | Archive header |
|---|---|---|
| Open interest | `open_interest_all` | `Open Interest (All)` |
| Non-commercial long / short / spreading | `noncomm_positions_long_all`, `noncomm_positions_short_all`, `noncomm_postions_spread_all` | `Noncommercial Positions-Long (All)`, `…-Short (All)`, `…-Spreading (All)` |
| Commercial long / short | `comm_positions_long_all`, `comm_positions_short_all` | `Commercial Positions-Long (All)`, `…-Short (All)` |
| Total reportable long / short | `tot_rept_positions_long_all`, `tot_rept_positions_short` | `Total Reportable Positions-Long (All)` … |
| Non-reportable long / short | `nonrept_positions_long_all`, `nonrept_positions_short_all` | `Nonreportable Positions-Long (All)` … |
| Changes | `change_in_open_interest_all`, `change_in_noncomm_long_all`, `change_in_noncomm_short_all`, `change_in_noncomm_spead_all`, `change_in_comm_long_all`, `change_in_comm_short_all`, `change_in_tot_rept_long_all`, `change_in_tot_rept_short`, `change_in_nonrept_long_all`, `change_in_nonrept_short_all` | `Change in Open Interest (All)` … |
| % of OI | `pct_of_oi_noncomm_long_all`, `…_short_all`, `pct_of_oi_noncomm_spread`, `pct_of_oi_comm_long_all`, `…_short_all`, `pct_of_oi_tot_rept_long_all`, `pct_of_oi_tot_rept_short`, `pct_of_oi_nonrept_long_all`, `…_short_all` | `% of OI-Noncommercial-Long (All)` … |
| Traders | `traders_tot_all`, `traders_noncomm_long_all`, `traders_noncomm_short_all`, `traders_noncomm_spread_all`, `traders_comm_long_all`, `traders_comm_short_all`, `traders_tot_rept_long_all`, `traders_tot_rept_short_all` | `Traders-Total (All)` … |
| Concentration | `conc_gross_le_4_tdr_long`, `conc_gross_le_4_tdr_short`, `conc_gross_le_8_tdr_long`, `conc_gross_le_8_tdr_short`, `conc_net_le_4_tdr_long_all`, `conc_net_le_4_tdr_short_all`, `conc_net_le_8_tdr_long_all`, `conc_net_le_8_tdr_short_all` | `Concentration-Gross LT = 4 TDR-Long (All)` … |

Disaggregated (`72hh-3qpy`, `kh3c-gbw2`):

| Group | long | short | spreading | change | % OI | traders |
|---|---|---|---|---|---|---|
| Producer/merchant | `prod_merc_positions_long` | `prod_merc_positions_short` | — (none by design) | `change_in_prod_merc_long/short` | `pct_of_oi_prod_merc_long/short` | `traders_prod_merc_long_all/short_all` |
| Swap dealers | `swap_positions_long_all` | `swap__positions_short_all` | `swap__positions_spread_all` | `change_in_swap_long_all/short_all/spread_all` | `pct_of_oi_swap_long_all/short_all/spread_all` | `traders_swap_long_all/short_all/spread_all` |
| Managed money | `m_money_positions_long_all` | `m_money_positions_short_all` | `m_money_positions_spread` | `change_in_m_money_long_all/short_all/spread` | `pct_of_oi_m_money_long_all/short_all/spread` | `traders_m_money_long_all/short_all/spread_all` |
| Other reportables | `other_rept_positions_long` | `other_rept_positions_short` | `other_rept_positions_spread` | `change_in_other_rept_long/short/spread` | `pct_of_oi_other_rept_long/short/spread` | `traders_other_rept_long_all/short/spread` |
| Non-reportable | `nonrept_positions_long_all` | `nonrept_positions_short_all` | — | `change_in_nonrept_long_all/short_all` | `pct_of_oi_nonrept_long_all/short_all` | — |

**Identity between the two reports (checked on 20 Oct 2026):** commercial long 59,531 = producer long 19,715 + swap
long 17,737 + swap spreading 22,079; commercial short 295,113 = 34,498 + 238,536 + 22,079; non-commercial long
237,142 = managed money long 120,970 + other reportables long 116,172; non-commercial spreading 54,199 = 38,634 +
15,565. So the legacy report is redundant once you store the disaggregated one, except for 1986–2006.

---

## 6. Every metric a desk uses (beginner definition, exact formula, pitfalls, verdict)

Notation: for group g, L_g = long, S_g = short, X_g = spreading, OI = open interest, t = report week.
Computed series for every week since 1986/2006 are in `data/cot_gold_metrics_weekly.csv`.

| # | Metric | Beginner | Formula / inputs | Pitfalls (pro) | Verdict |
|---|---|---|---|---|---|
| 1 | **Open interest** and ΔOI | how many bets exist; rising OI = new money, falling = positions closed | `open_interest_all`; Δ = `change_in_open_interest_all` | futures-only OI (402,279) ≠ combined OI (532,443, which adds delta-adjusted options); OI excludes contracts already in delivery; compare with CME's daily OI, which will differ by the Tuesday snapshot | PUBLISH-CORE |
| 2 | **Long / short / spreading by group** | who holds what | the fields in §5 | "spreading" is only *intra-market* calendar spreads; a fund long gold and short silver is a long here; commercials have no spread column in legacy | PUBLISH-CORE |
| 3 | **Net position** | the group's directional bet | N_g = L_g − S_g; in ounces × 100; in tonnes × 100 / 32,150.7; in $ × price × 100 | nets sum to zero across all groups (each long has a short): the commercial net is roughly the mirror of the speculative net, so "commercials are record short" and "funds are record long" are the same fact, not two | PUBLISH-CORE |
| 4 | **Weekly change** (ΔL, ΔS, ΔN) | who added, who closed | ΔL_g = L_g(t) − L_g(t−1); ΔS similarly; ΔN = ΔL − ΔS | the published `change_in_*` fields are vs the previous *report*, which after a holiday-delayed week is still one week; the first week of a new contract has no change | PUBLISH-CORE |
| 5 | **"Who closed / who added" decomposition** | the week's story in words | per group: ΔL < 0 → closed longs; ΔS < 0 → covered shorts; ΔL > 0 → new longs; ΔS > 0 → new shorts; cross with ΔOI and the week's price (§7) | category totals only: inside "managed money" one fund may add while another closes; a position that moved from one category to another (reclassification) looks like a close + open | PUBLISH-CORE |
| 6 | **% of OI** | how big each group is | `pct_of_oi_*` = 100 × L_g / OI (and S_g / OI); net % OI = 100 × N_g / OI | use % OI, not raw contracts, to compare across years (OI doubled 2010 → 2020, halved into 2026) | PUBLISH-CORE |
| 7 | **Number of traders** and average size | how many players; concentration of conviction | `traders_*`; avg = L_g / traders_g_long (managed-money long: 120,970 / 78 = 1,551 contracts each) | the total counts each trader once, categories count it in each column it occupies, so columns exceed the total; counts stop at the 200-contract reporting line | PUBLISH-CONTEXT |
| 8 | **Concentration ratios** | how much of the market the 4 and 8 biggest hold | `conc_net_le_4_tdr_short_all` etc.; gross (before netting a trader's own long vs short) and net | the ratios ignore category; the "top-4 net short 36.5 %" is almost certainly bullion banks' hedges; read a rising short concentration with a falling swap-dealer net as "the hedge book is concentrating" | PUBLISH-CONTEXT (details drawer) |
| 9 | **COT index** | where today's net sits inside its own range: 0 = most short of the window, 100 = most long | I_N = 100 × (N − min_N) / (max_N − min_N), N = 26 / 52 / 156 weeks (the "Williams COT index" applies this to commercials and calls ≥ 90 bullish, ≤ 10 bearish; applied to managed money the reading is the opposite) | windows must be in *reports* (weeks), not calendar days, and must skip the semi-monthly era; the index is 0 or 100 for long stretches in a trend (see chart), which is why it fails as a trigger | PUBLISH-CONTEXT |
| 10 | **z-score** | how unusual the net is vs the last 1 / 3 years | z = (N − mean_N) / sd_N, N = 52 / 156 | nets are autocorrelated (weekly ρ₁ = 0.97 managed money, 0.99 non-commercial), so ±2 happens often and lingers; use with % OI | PUBLISH-CONTEXT |
| 11 | **Extremes / percentile rank** | record long or short | all-history percentile of N and of net % OI; record dates | raw-contract records are inflated by OI growth: managed money's record 273,076 (5 Jul 2016) was 41.8 % of OI, the 2024–25 highs ≈ 215k were 36–40 % | PUBLISH-CONTEXT |
| 12 | **Commercials vs specs divergence** | hedgers and funds disagree with price | (a) non-confirmation: price makes a 13-week high while N_mm does not (or vice versa); (b) opposite extremes: I_52(mm) ≥ 90 and I_52(comm) ≤ 10 | because the nets mirror each other (b) is one fact, not two; (a) is the only genuine divergence; our test (§9) found no edge in either | PUBLISH-CONTEXT, worded as description |
| 13 | **Options-only positioning** | what the option book adds | combined − futures-only, per group, on delta-adjusted contracts (CFTC converts long calls / short puts to long futures-equivalent, short calls / long puts to short) | deltas are the exchange's at the Tuesday close; a 20 % price move re-deltas the book without any trade; 20 Oct 2026: options add +4,479 to managed-money net, −8,074 to non-commercial net (other reportables run an 87k-contract delta-neutral option spread book: 102,525 combined spread vs 15,565 futures) | PUBLISH-CONTEXT (one line) |
| 14 | **Long/short ratio** | how one-sided the funds are | L_mm / S_mm (7.2 on 20 Oct 2026) | explodes when shorts → 0; prefer net % OI | LINK-ONLY (derivable) |
| 15 | **Hedging pressure** (Bessembinder 1992) | how short the hedgers are, 0–1 | HP = S_comm / (L_comm + S_comm) = 295,113 / 354,644 = 0.832 | the academic risk-premium variable; monotone in commercial net, so it adds nothing to #3 for a dashboard | DO-NOT-PUBLISH (research only) |
| 16 | **Flow z** | how big this week's change is | z of ΔN over 52 weeks | the input to the H2 test; same-week correlation with price 0.64, so a big flow mostly tells you the price already moved | PUBLISH-CONTEXT |
| 17 | **Position in tonnes / $** | plain-language size | contracts × 3.1103 kg; × 100 × price | helps a beginner: funds' 104,206 contracts ≈ 324 t ≈ 10 % of a year's mine supply; it is paper, not metal | PUBLISH-CORE (in the hero numbers) |

---

## 7. Reading a week: "which positions got closed, who is long, who is short"

**The matrix.** For each group take ΔL and ΔS; read with the week's price move (Tuesday to Tuesday) and ΔOI:

| Price | OI | Dominant speculator change | Reading |
|---|---|---|---|
| up | up | ΔL_mm > 0 | long build-up: new fund longs, hedgers selling into it (ΔS_comm > 0) |
| up | down | ΔS_mm < 0 or ΔS_comm < 0 | short covering: shorts bought back, nobody new |
| down | up | ΔS_mm > 0 | short build-up: new fund shorts, commercials buying (ΔL_comm > 0) |
| down | down | ΔL_mm < 0 | long liquidation: funds sold out, commercials covered hedges (ΔS_comm < 0) |
| any | up | ΔX > 0 | spread build-up: calendar spreads, often ahead of a roll; not directional |

**Who is long / who is short, 20 Oct 2026 (futures-only):**

| Group | Long | Short | Spread | Net | Δ net | What they did this week |
|---|---|---|---|---|---|---|
| Managed money (funds, CTAs) | 120,970 | 16,764 | 38,634 | **+104,206** | −2,883 | closed 3,777 longs, covered 894 shorts, added 5,077 spreads |
| Other reportables (prop, family offices, option MMs) | 116,172 | 20,513 | 15,565 | **+95,659** | −5,131 | closed 4,381 longs, added 750 shorts, added 3,227 spreads |
| Non-reportable (small traders) | 51,407 | 15,690 | — | **+35,717** | +1,065 | added 676 longs, covered 389 shorts |
| Swap dealers (banks' OTC books) | 17,737 | 238,536 | 22,079 | **−220,799** | +3,295 | added 3,761 longs, added 466 shorts: net short shrank |
| Producer / merchant (miners, refiners, jewellers) | 19,715 | 34,498 | — | **−14,783** | +3,654 | added 1,329 longs, covered 2,325 shorts |
| **Open interest** | 402,279 (+5,934) | | | | | |

Price over the report week: 4,177.3 → 4,142.6 (−0.8 %). Reading: **long liquidation by speculators (non-commercial
longs −8,158), absorbed by commercials covering hedges (commercial net short −6,949); OI still rose because
speculators added 8,304 calendar spreads.** Nobody new was betting on direction; the hedge book shrank. Then, after
the snapshot, gold fell a further 3.3 % to 4,007.9 by the Friday release: the next report (as of 27 Oct, released
Sat 31 Oct 01:00 IST) will show whether the 8-week fund liquidation continued.

**The eight-week story** (managed-money net, from `data/cot_gold_metrics_weekly.csv`): 144,747 (25 Aug, gold $4,694) →
136,771 (1 Sep) → 134,972 → 133,116 → 127,389 → 120,318 → 110,987 → 107,089 → 104,206 (20 Oct, $4,143). Eight
consecutive weekly cuts, −40,541 contracts (−28 %) against a −12 % price. 52-week COT index from 64 to 26; the
52-week low was 89,752 on 28 Apr 2026. Swap dealers' net short moved only −233k → −221k: the banks did not cover
much; producers did (−31k → −15k).

---

## 8. Current state and historical context (as of 20 Oct 2026)

| Measure | Value | Context |
|---|---|---|
| Managed-money net | +104,206 contracts = 10.4 Moz ≈ 324 t ≈ $43.2 bn | 25.9 % of OI; all-history (2006→) percentile 49; z(52w) −0.5, z(156w) −0.8; COT index 26w 26 · 52w 26 · 156w 38 |
| Non-commercial net (legacy) | +199,865 = 49.7 % of OI | percentile since 1986: 82 (raw contracts; OI growth inflates it); COT index 52w 47 · 156w 37 |
| Commercial net | −235,582 | COT index 52w 55 (mirror of the specs) |
| Swap-dealer net | −220,799 = 22.1 Moz ≈ 687 t | within 17 % of its record short (−264,731 on 4 Feb 2025) |
| Producer/merchant net | −14,783 | the physical industry is barely hedged: less short in only 31 of 1,063 weeks since 2006 (in 2013–14, 2022 and 2026); the record net short was −223,009 on 22 Jun 2010 |
| Non-reportable net | +35,717 | small traders net long, as almost always |
| Top-4 / top-8 net short | 36.5 % / 53.0 % | top-4 / top-8 net long 19.7 % / 27.7 %; gross top-4 short 37.8 % |
| Traders | 288 total; MM long 78, short 25, spread 42; swap L 18 / S 23 / X 20; producer L 20 / S 14; other L 80 / S 34 / X 27 | |
| Options overlay | combined OI 532,443 (+130,164 futures-equivalent of options); MM net +4,479 via options; non-commercial −8,074; commercial +7,019 | |
| Records | MM net max 273,076 (5 Jul 2016), min −109,454 (9 Oct 2018); non-commercial net max 353,649 (18 Feb 2020), min −88,363 (6 Apr 1999); OI max 796,883 (14 Jan 2020) | |

Chart `cot_gold_positioning_2010_2026.png`: price, net by group and the managed-money COT index since 2010.

---

## 9. G-STUDY COT-1: does COMEX positioning predict gold?

Script `scratch/cot_metrics_study.py`; panel `data/study_panel.csv`; tables `data/study_tables.md`; results
`data/study_results.json`. Hypotheses and horizons were fixed in the script before any result was printed (the
project convention is a separate PLAN.md; here the docstring serves). Not pre-registered with the owner.

**Design.** Signal known at the Friday 15:30 ET release; entry at the close of the **first session after** the
release (Monday); forward log returns over 5 / 20 / 65 sessions of Yahoo GC=F; weekly reports 13 Jun 2006 → 20 Oct
2026 for managed-money signals (1,011–1,063 weeks), legacy non-commercial from Sep 2000 where price allows; Newey–
West t with lags = horizon in weeks; full sample and two halves (2006–16, 2016–26); decile and tercile buckets plus a
linear fit per standard deviation. Pass rule, as in the project's other studies: |t| ≥ 2 in the full sample **and**
the same sign with |t| ≥ 2 in both halves.

| Hypothesis | Full 2006–26 | Half A 2006–16 | Half B 2016–26 | Result |
|---|---|---|---|---|
| H1 funds crowded (52w COT index top decile) vs washed out (bottom decile) → mean reversion | 20 sessions: top +1.52 %, bottom +1.36 %, spread +0.16 (t 1.4 / 1.3); 65 sessions spread +0.74 | spread **−1.22** (bottom decile +2.48 %, t 2.9) | spread **+1.32** (bottom +0.29 %, t −1.2) | **FAIL** (sign flips) |
| H1b 156w COT index top decile → continuation | 20 sessions +1.99 % vs 0.71 % all (t 2.05); 65 sessions +4.44 % vs 2.28 % (t 1.5) | 65 sessions t 3.35 | t 0.6–0.9 | **FAIL** (one half only) |
| H1c legacy non-commercial 52w index deciles | spreads −0.37 / +0.28 / +1.70 (t < 1.1) | −0.87 (20 s) | +1.59 (20 s) | **FAIL** |
| H2 weekly fund flow (z of Δnet) top vs bottom tercile → continuation | spreads −0.19 / −0.52 / −0.29 %, t ≤ 0.8; linear −0.10 %/SD (5 s, t −1.4), **−0.29 %/SD (20 s, t −1.9)** | −0.30 %/SD (t −1.2) | −0.15 %/SD at 5 s (t −1.6) | **FAIL**; direction mildly contrarian |
| H3 fund net % OI bottom decile → rebound | 65 sessions **+5.16 % vs 2.46 % (t 2.6), hit rate 77 %** | +4.97 % (t 1.4) | +5.06 % (t 1.35) | **FAIL the halves rule**; candidate backdrop |
| Same-week price move vs fund flow | Pearson 0.575, Spearman **0.64** (n 1,011) | | | positioning follows price |
| Fund-flow persistence | lag-1 autocorrelation 0.17 | | | flows barely persist |

Chart `cot_gold_study_deciles.png`: 20-session forward return by decile of the 52-week COT index and of weekly flow; no
decile is reliably different from the 0.76 % average.

**Verdict: FAIL as a timing signal at 1–13-week horizons; PASS as context.** Six signals × three horizons × three
periods is 54 cells; a couple of t ≈ 2 cells is what chance produces. Costs were not deducted (none of the spreads
would survive the MCX round trip in `shared/mcx_specs.py` anyway). The one reading worth keeping in words: *when the
funds have been washed out (bottom decile of net % OI) the next quarter has been good more often than not*; today's
reading (25.9 % of OI, percentile 49) is nowhere near that.

**Literature (from memory, verify before quoting):** Sanders, Boris & Manfredo (2004, *Energy Economics*) found COT
positions follow prices rather than lead them; Gorton, Hayashi & Rouwenhorst (2013, *Review of Finance*) found
trader positions do not predict futures returns; Kang, Rouwenhorst & Tang (2020, *Journal of Finance*) found that
*changes* in speculator positions are negatively related to next-week returns (speculators are paid for providing
liquidity) while long-run hedging pressure earns a premium, which is the direction our H2 shows for gold without
significance; Bessembinder (1992) is the hedging-pressure origin. Larry Williams popularised the COT index on
commercials for trend trading, without out-of-sample evidence for gold that I can cite.

---

## 10. What COT cannot show (say it on the panel)

1. **Nothing daily or intraday.** Tuesday snapshots only; the CFTC collects daily data and never publishes it.
2. **Nothing between the snapshot and the release.** Three days old on arrival, six by Monday's MCX open.
3. **Nobody by name**, and nothing on positions below 200 contracts except as the non-reportable residual.
4. **Nothing OTC.** London's forwards, swaps and unallocated accounts (the largest gold market) are outside COMEX;
   the swap-dealer line is the only shadow of them (their COMEX short hedges OTC exposure they sold to clients).
   LBMA's weekly trade data and vault holdings are a separate brief (G-PHYSICAL).
5. **No per-month positions**, no option strikes or Greeks beyond the delta-netting, no intermarket spreads
   (gold–silver, gold–platinum), no MCX positions.
6. **Categories are self-declared** (Form 40) and reclassifications happen silently; a trader moving from "other
   reportables" to "managed money" looks like a flow.
7. **Reporting levels change** (200 contracts today); comparisons across decades mix thresholds.
8. **Holiday weeks** shift the release to a Monday and, when the Tuesday itself is a holiday or closure, the as-of
   date to another weekday (24 such reports since 1992, including 10 Sep 2001 and the two Fridays of Dec 2001); the
   "change" is still vs the previous report.

---

## 11. Bloomberg, Barchart, Tradingster: what they show and charge (see §3.7 for verification status)

- Bloomberg `CFTC <GO>` (UNVERIFIED here): the complete CFTC tables for every market, both category systems, weekly
  history and charts, each series as an Index ticker for `GP`/`HP` and Excel; the value is convenience and the price
  overlay, both reproducible from the free data. Cost: the terminal.
- Barchart (UNVERIFIED, bot wall today): per-symbol COT chart page; downloads in the paid tier.
- Tradingster (verified free): exactly the CFTC block plus simple charts; its new "Analysis / Signals" (extremes, net
  flips) duplicates §6 #9–11 and may become paid.
- The CFTC's own pages (free, canonical): the viewables in §3.1 and the charts on publicreporting.cftc.gov.
- Nothing any of them shows for gold is unavailable from the API in §3.4. The app can match the Bloomberg
  presentation (table + net-vs-price chart + index) at zero data cost.

---

## 12. Where it goes in the app (repetition audit and panel design)

**Repetition audit.** No COT number exists anywhere in the app today (grep over `services/`, `ui/components`, `docs`,
`alpha_lab`: the only hit is a sentence in `alpha_lab/inputs/oi_field_guide.md` comparing NSE participant OI to COT).
The nearest existing panel is MKT's "Who holds index futures" (NSE participant OI, `fao_participant_oi`), whose own
study (`reports/fii_positioning/`) also ended "context, not a timing tool"; the COT panel should copy that panel's
framing. COMEX price (Yahoo GC=F) already appears in WorldMarkets, CMDT and the gold pre-open; the COT panel must
reuse the same series, not fetch its own.

**One home, one copy.** Put the panel on MCXG (the gold desk) as a "Positioning (CFTC COT)" section, or on a new GOLD
page if the program creates one. WorldMarkets' Commodities card and CMDT get a single chip: `COT 20 Oct · funds
+104k (−2.9k) · idx52 26` that deep-links to the panel. BRF (the morning brief) gets one sentence on the Monday after
a release.

**Panel spec (weekly cadence, one API table behind it):**

1. **Hero row:** managed-money net (contracts, tonnes, $), w/w change with the "closed longs / covered shorts"
   wording from §7, 52-week COT index as a 0–100 bar with the 20/80 bands, "as of Tue 20 Oct · released Fri 23 Oct ·
   next Sat 31 Oct 01:00 IST".
2. **Who is long / who is short:** the §7 table as paired horizontal bars (long right, short left) per group, with
   the w/w arrows; legacy groups collapsed into a toggle.
3. **History chart:** the three panels of `cot_gold_positioning_2010_2026.png` (price / net by group / COT index),
   ranges 1y · 3y · 10y · all, one y-axis per panel (never a dual axis), tooltip with the week's full decomposition.
4. **Options line:** "options add +4,479 to funds' net; combined OI 532,443".
5. **Details drawer:** trader counts, concentration ratios, non-reportable, micro gold (retail read), the raw CFTC
   block with a link to `deacmxsf.htm` and the API query.
6. **Auto narrative:** one sentence from the §7 matrix (long liquidation / short covering / build-up / spread
   build-up) with the price move of the report week.
7. **Footer:** the §10 list in one line: "weekly, Tuesday positions, released Friday 15:30 ET, no daily, no OTC,
   categories only; our test found no timing value".
8. **Telegram:** Saturday morning digest after the job runs, and an alert only on genuine extremes (52-week index ≥
   90 or ≤ 10, or |z156| ≥ 2) worded as context.

**Not to build:** a "COT signal" badge, a buy/sell colour, or any feed into the Decision Desk, the S1 shadow or the
paper ticket.

---

## 13. Ingest notes

**Storage (data-service, DuckDB `data/market.duckdb`):**

```
cot_gold_raw   (dataset TEXT, id TEXT, report_date DATE, contract_code TEXT, market_name TEXT,
                payload JSON, fetched_at TIMESTAMP, PRIMARY KEY (dataset, id))
cot_gold       (report_date DATE, contract_code TEXT, fut_or_combined TEXT,
                open_interest, oi_chg,
                nc_long, nc_short, nc_spread, c_long, c_short, nr_long, nr_short,
                pm_long, pm_short, sd_long, sd_short, sd_spread, mm_long, mm_short, mm_spread,
                or_long, or_short, or_spread,
                traders_total, traders_mm_long, traders_mm_short, …,
                conc_gross4_long, conc_gross4_short, conc_gross8_long, conc_gross8_short,
                conc_net4_long, conc_net4_short, conc_net8_long, conc_net8_short,
                source TEXT, released_at TIMESTAMP,
                PRIMARY KEY (report_date, contract_code, fut_or_combined))
cot_gold_metrics  — a VIEW computing §6 (nets, changes, % OI, COT index 26/52/156, z52/z156, options-only)
```

Keep the raw payload: the CFTC occasionally republishes corrected weeks, and reclassifications are visible only by
diffing. Legacy rows before 13 Jun 2006 fill only the legacy columns.

**Backfill:** four API calls as in §3.4 (`$limit=50000`, `$order` ascending), ~20 s total, 35 MB JSON (or the `.csv`
endpoint with `$select` for a tenth of that). Fallback: the four multi-year zips plus the yearly zips (§3.3, 44
downloads, 150 MB). The CSVs in `data/` of this directory are a ready seed.

**Weekly job (master-controller, IST):** `cot_fetch` at **Sat 02:30** (covers 01:00 EDT-season and 02:00 EST-season
releases), retry hourly until found or 06:00; `Mon 06:30` and `Tue 06:30` retries catch holiday-delayed Monday
releases (16 Nov, 30 Nov, 28 Dec 2026). Query `report_date > max(report_date)` per dataset; expect 2 rows per dataset
(GOLD + MICRO GOLD); treat 0 rows as "not yet", 429 as throttle (sleep 60 s), 5xx as retry. Stop condition: all four
datasets carry the same new Tuesday. Then compute the metrics view, write the Saturday digest, and expose
`/api/mcx/cot` (ui-api) from the table, never from a live CFTC call (the terminal must not wait on a US site).

**Dedupe and integrity:** upsert on `(dataset, id)`; `id` is deterministic (`YYMMDD + code + F/C`). Do **not** assert
that `report_date` is a Tuesday: 24 of the 1,778 weekly-era reports (1.3 %) carry a Monday, Wednesday or Friday as-of
date when the Tuesday was a US holiday or a closure (30 Sep 1992 Wed, 3 Jul 1995 Mon, 10 Sep 2001 Mon, 21 and 28 Dec
2001 Fri, 14 Feb 2003 Fri, 3 Jan 2007 Wed …); key on the date itself. Verify the legacy↔disaggregated identity of §5 on every row
(commercial long = producer long + swap long + swap spread); alert on a violated identity or on a week older than 10
days during a non-holiday period. Trim `cftc_commodity_code` / `cftc_market_code`; cast every field; ignore
`_old` / `_other`.

**Rate and etiquette:** one request per second (robots `Crawl-delay: 1`), browser-like or project User-Agent, an
optional free app token in `.env` (`CFTC_APP_TOKEN`), no more than ~10 requests per week in steady state.

**Monitoring:** `cot_last_report_date`, `cot_rows_per_week`, `cot_fetch_latency_s`, `cot_identity_violations`, plus a
staleness banner on the panel when the latest Tuesday is more than 10 days old.

---

## 14. Open questions and owner actions

Open questions

1. Should the panel live on MCXG or on a new GOLD page? (The brief asks for world-market tabs too; the answer here is
   a chip on WorldMarkets/CMDT, not a copy.)
2. Does MCX publish participant-wise open interest for GOLD (an Indian analogue)? Not verified in this brief; G-MCX.
3. The 2027 CFTC release calendar is not published yet; re-check in December and load it into `mcx_specs`-style
   reference data.
4. Barchart and Bloomberg presentations could not be verified from this machine; only Tradingster was.
5. Whether to also store silver (084691) and copper (085692) from the same COMEX file for the metals context: zero
   extra cost, same table.

Owner actions

1. Approve PUBLISH-CONTEXT for a weekly "Positioning (CFTC COT)" panel on the gold desk with the §12 spec, and the
   rule that nothing from it feeds a trade.
2. Optionally register a free Socrata app token and add `CFTC_APP_TOKEN=` to `.env` (no key is needed to start).
3. Decide the panel's home (MCXG vs a GOLD page) so the repetition rule can be enforced in the UI review.
4. Read `data/cot_gold_latest.json` and the two PNGs as the acceptance sample for the panel's first version.

---

## 15. Files in this directory

| File | What |
|---|---|
| `REPORT.md` | this report |
| `cot_gold_positioning_2010_2026.png` | price / net by group / COT index, 2010–2026 |
| `cot_gold_study_deciles.png` | forward returns by decile of two signals |
| `data/cot_gold_legacy_futures_only.csv` (2,113 rows × 133), `cot_gold_legacy_combined.csv` (1,822 × 133), `cot_gold_disagg_futures_only.csv` (1,237 × 194), `cot_gold_disagg_combined.csv` (1,237 × 194) | the full gold history from the API, every field, codes 088691 / 088695 / 088LM1 |
| `data/api_pull_log.json` | status, latency, bytes, rows and date ranges per dataset |
| `data/archives/archive_gold_*.csv`, `archive_pull_log.json` | the same rows extracted from the 44 CFTC zips, with per-zip status/size/latency and member names |
| `data/cot_gold_metrics_weekly.csv` | every §6 metric per week for GOLD 088691 |
| `data/cot_gold_latest.json` | the latest week's full decomposition and indices |
| `data/study_panel.csv`, `study_results.json`, `study_tables.md` | G-STUDY COT-1 |
| `data/gc_f_daily_yahoo.csv` | GC=F daily closes 2000–2026 |
| `data/release_calendar_2026_ist.csv` | 2026 releases with as-of Tuesdays and IST times |
| `scratch/` | scripts (`pull_api_history.py`, `pull_archives.py`, `cot_metrics_study.py`, `make_charts.py`) and the raw fetched pages |
