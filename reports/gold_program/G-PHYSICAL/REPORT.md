# G-PHYSICAL research report (materialised from the agent's structured result, 26 Oct 2026)

# G-PHYSICAL — Physical supply, demand, OTC and the gold balance sheet

**FILE STATUS: the harness refused this agent's write of `reports/gold_program/G-PHYSICAL/REPORT.md` ("subagents should return findings as text"). This `summary` field IS the long-form report; the parent should materialise it at that path.** All evidence files exist: `reports/gold_program/G-PHYSICAL/verify_log.jsonl` (154 requests, UTC timestamps, status, latency, bytes, first 600 bytes) and `reports/gold_program/G-PHYSICAL/samples/` (134 payloads, 24 MB), plus the harness `verify.py` and the four `batch_*.py` scripts.

Verified live Monday 26 Oct 2026, 05:30–06:30 IST. No live service touched (no :8001/:8010/:8008 calls, no ICICI/Breeze); `.env` grepped for key names only (FRED_API_KEY, EIA_API_KEY, DATA_GOV_IN_API_KEY: none set). Python: jupyter_env only, no installs (note: `lxml` is NOT installed, `bs4`, `pypdf`, `pymupdf`, `openpyxl` are).

Read with two hats: plain text for someone new to gold; "▸ Pro" for the exact definition/formula/traps.

## 0. Headline findings
1. **Three of the brief's named URLs are dead or walled**: FRED `GOLDAMGBD228NLBM`/`GOLDPMGBD228NLBM` were REMOVED by FRED in Jan 2022 (404; series pages redirect to the removal notice); `prices.lbma.org.uk/json/gold_pm.json` is Cloudflare-403 for any script (both UAs); `spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv` now redirects to a bar-list PDF.
2. **Working free replacements were found and verified**: WGC's open chart API `fsapi.gold.org` (no login) serves LBMA AM/PM in USD/GBP/EUR, SGE AM/PM in CNY and MCX AM/PM in INR daily for 1y (252 points, last 23 Oct 2026: LBMA PM $4,013.30), global ETF holdings/flows weekly since 2003 by region, 21 countries (India 124.4 t) and top/bottom-10 funds, the quarterly supply/demand balance sheet (Q2-26), and weekly India/China premiums; GLD's `api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en` gives 5,720 daily rows (18 Nov 2004 → 22 Oct 2026, tonnes 1,045.64, −11.98 t on 22 Oct); IMF's SDMX API (`api.imf.org`, dataset IRFCL) gives monthly official gold in million fine troy oz per country (China 76.73 Moz Aug-26, +0.65 Moz m/m ≈ +20 t; India 28.309 Moz = 880.5 t flat; Poland +0.80 Moz Sep-26); SGE's EN site gives the daily Au99.99/Au(T+D) table (OI 260,054 lots, direction "Long to Short", delivery 24,570 lots on 23 Oct), the SHAU benchmark JSON since 2016, and the monthly Data Highlights PDF with **withdrawals (Sep-26: 92.08 t; YTD 832.4 t)**; SHFE daily `kx` JSON on the post-redesign path (au2612 OI 198,578 lots, settle 869.20 CNY/g); LBMA vault XLSX (Sep-26: 9,821 t gold, +189 t m/m; silver 28,985 t); LBMA Trade Data headline on-page (12-wk MA weekly gold turnover $964.17 bn to 16 Oct 2026; full data is a Nasdaq/Bloomberg/LSEG subscription); RBI weekly reserves via the press-release page (gold US$105,800 mn as on 16 Oct 2026); IBJA daily ₹/10 g (999 PM ₹140,882 on 23 Oct); AMFI NAVAll.txt (~80 gold-ETF NAV rows); Perth Mint monthly sales (Aug-26 23,932 oz gold).
3. **Blocked or unverifiable from this machine**: Sprott PHYS (Cloudflare 403), US Mint (Cloudflare 403), CME gold stocks (Akamai 403, G-COT scope), data.imf.org portal (403 but the API works), Nasdaq Data Link LBMA/GOLD (Incapsula 403 without key), SHFE warehouse-stock file path (4 guesses 404), AMFI monthly AUM (site is now a Next.js SPA; old URLs 404), DGCI&S data portal (DNS failure), PIB September-2026 trade release URL (content confirmed only via Reuters/India Today 15–16 Oct), SwissImpex (now a JS dashboard, no API), HK C&SD gold table id (API live, id unresolved), SAFE China page (no table in HTML).
4. **Terms are the real constraint, not technology**: WGC T&Cs say personal/non-commercial use, no scraping/redistribution/framing without written authorisation and accreditation (and the LBMA price inside is IBA-licensed); SPDR's XLSX disclaimer says "reproduction or redistribution … expressly prohibited without prior written consent"; Kitco prohibits framing/mirroring/robots (so its chart images are LINK-ONLY); IMF is PUBLIC_OPEN with citation; LBMA vault XLSX is a free public download. The owner's single-user private terminal viewing numbers with attribution is defensible; re-serving them is not (owner action O-1).
5. **Already in the app**: nothing physical is numeric. `gold_preopen.py` MANUAL_CHECKS links to SGE delayed quotes, WGC ETF flows, GLD holdings and Kitco; `GoldPreOpen.tsx`/`McxGoldDesk.tsx` show an "implied premium %" that is MCX vs landed COMEX **ex-duty** (a futures-basis-plus-duty number, not the physical dealer premium); WEI and CMDT show COMEX GC=F. Four of the manual-check links become numbers with this work; the MCX premium should be relabelled.
6. **A landed-cost error is latent**: headlines on 16 Oct 2026 report India's gold import duty raised to 15%; `mcx.py` still notes "no import duty or local premium" and the implied premium is computed duty-free. Verify at CBIC before any India premium is shown (O-3).
7. **Evidence**: none of these series has verified out-of-sample timing value at day-to-week horizons (survey literature: O'Connor, Lucey, Batten & Baur 2015 IRFA; Erb & Harvey 2013 FAJ; Baur & Lucey 2010; WGC's attribution model treats ETF flows/positioning as contemporaneous drivers). Their value is regime diagnosis (who is the marginal buyer), risk management at the MCX open, and the India basis. Four cheap G-STUDIES are proposed; the GLD 22-year daily history makes GS-P1 runnable today.

## 1. The gold balance sheet
**Beginner.** Gold is not consumed: ~216,000 t exists above ground (WGC); mines add ~3,800 t/yr and recycling ~1,400 t, under 2.5% of the stock. So price is set by who wants to hold the existing stock — the marginal buyer/seller — not by this year's production. The quarterly industry table (WGC/Metals Focus):
```
SUPPLY: mine production + recycled gold ± net producer hedging
DEMAND: jewellery (fabrication; consumption) + technology + bar & coin + ETFs + central banks + "OTC and other" (balancing item)
```
Q2 2026 (fetched live, tonnes): supply = mine 965.6 + recycled 326.1 + hedging −22.8 = 1,268.9. Identified demand = jewellery fabrication 310.3 + technology 80.4 + bar & coin 307.1 + ETFs −44.8 + central banks 288.9 = 941.9 → "OTC and other" ≈ 327 t. Full-year 2025: mine 3,822.9, recycled 1,403.8, hedging −53.9 vs jewellery 1,647.7, technology 322.9, bar & coin 1,405.9, ETFs +803.3, central banks 848.2. One-sentence read: in 2025–26 investment and central banks replaced jewellery as the marginal buyer (jewellery fabrication 2,208 t in 2023 → 1,648 t in 2025; ETFs −242 t → +803 t; central banks 850–1,090 t/yr for three years). Price-sensitive demand retreats as price rises; price-insensitive demand chases it — the physical data tells you which side is winning now.

**▸ Pro.** Supply ≡ demand by construction; "OTC and other" = unidentified investment + error, not a measured OTC flow (the measured OTC flow is LBMA turnover, gross not net). Stock-flow: F/S ≈ 2.4%, so mine supply is irrelevant at trading horizons; elasticities that matter are demand-side (jewellery −, central banks ~0, ETFs +momentum) and holders' willingness to sell (recycling 1,234 t 2023 → 1,404 t 2025). Where metal lives: London vaults 9,821 t (Sep-26), ETFs 4,279 t (16 Oct 2026), COMEX vaults (G-COT), SGE/SHFE vaults, central banks ~36 kt. Tightness shows as (i) positive Shanghai/Mumbai premium, (ii) rising SGE withdrawals, (iii) ETF creations, (iv) backwardated EFP/lease (G-COT/rates), (v) London vault outflows; several at once beats any one. Revisions: WGC revises every quarter; China under-reports and reports late — never backtest on the latest vintage (ALFRED rule, docs/PROGRAMMATIC_DATA_ACCESS.md §3). Units: 1 troy oz = 31.1034768 g; 1 t = 32,150.7 oz; MCX ₹/10 g; SGE CNY/g; LBMA $/oz; SHFE and SGE Au(T+D) 1 lot = 1 kg; GLD ≈ 0.0917 oz/share (23 Oct 2026, falls daily by the expense ratio).

## 2. Source-by-source (details, verdicts and ingest notes are itemised in the `sources` array; the narrative points that matter)
- **LBMA price (2.1)**: use `https://fsapi.gold.org/api/goldprice/v13/chart/main?period=1y` (daily; `3y`/`10y` are downsampled to 381/425 points; `…/chart/price/` gives USD back to the 1970s at coarse granularity). Store into a new DuckDB table `gold_reference_prices(date, series, value)`; fetch 21:00 and 09:00 IST. Timestamps are epoch-ms midnight UTC of the London date.
- **LBMA Trade Data (2.2)**: the OTC series. Public page carries only "Trade Reporting Weekly Turnover … 12 week moving average … period ending 16 October 2026. Gold: $964.17 bn, Silver $129.69 bn, Pt $16.10 bn, Pd $7.21 bn"; daily T+1 and weekly product-level data via Nasdaq/Bloomberg/LSEG subscription. Open-volume reports are not netted between reporters. $964 bn/week at $4,000/oz ≈ 7,500 t gross turnover per week (annual mine supply every 2–3 days). Regex the page weekly.
- **LBMA vault (2.3)**: monthly XLSX, 2016-07 → 2026-09 in thousand oz; filename changes monthly — resolve the href from the vault page. Dates are mixed string/datetime (`pd.to_datetime(format="mixed")`).
- **GLD (2.5)**: XLSX sheets `Disclaimer` + `US GLD Historical Archive`; columns Date, Closing Price, Ounces per Share, NAV 10:30, Indicative 16:15, Mid, Premium/Discount, Volume, Total Ounces, Tonnes, Total NAV; holiday rows carry "US Holiday" text. Last 5 tonnes: 1,059.04 / 1,058.47 / 1,060.18 / 1,057.62 / 1,045.64 (22 Oct, −11.98 t on 17.5 M shares). All-time high 1,353.35 t (7 Dec 2012). Row for day T appears T+1 ~06:00 IST (Friday rows by Monday morning).
- **IAU (2.6)**: the page JSON has "Tonnes in Trust" 463.05, net assets $59.74 bn, 792.05 M shares as of 23 Oct 2026; the documented `.ajax?fileType=csv` endpoint returns the HTML page (stale id). Regex fallback → WGC fund table.
- **WGC ETF (2.8)**: three open JSONs (`holdings-chart2`, `flows-chart2`, `archive-tablegroup/all`): weekly from 2003-02-28; week 42 ending 16 Oct 2026 global +13.69 t (+$1.90 bn), holdings 4,278.9 t, AUM $578.7 bn; NA 2,123.2 t, Europe 1,529.3, Asia 549.9, Other 76.5; Sep-26 monthly +67.9 t (+$10.0 bn; Asia +16.9 t, India +3.1 t/+$496 mn, China +11.9 t); countries table (US 2,048.9, UK 689.2, CH 382.6, DE 337.6, CN 310.9, IN 124.4 …); top inflow fund SPDR Gold Shares +6.19 t, top outflow iShares Gold Trust −0.96 t. Page's XLSX → 403 without a free Goldhub login. Columns contain `<br/>`; values are strings; some fund rows have None holdings.
- **WGC supply/demand (2.9)**: `supply-and-demand/43` → 66 quarters Q1'10→Q2'26 and 2010→2025 annual, 3 supply + 15 demand series incl. LBMA quarterly average price (Q2-26 $4,506.3; 2025 $3,431.5). Q3-26 due early Nov.
- **WGC premiums (2.10)**: `local-gold-price-premiums` weekly 255 points: 16 Oct 2026 India +$11.44/oz, China +$7.76/oz; monthly Sep-26 China +24.59, India −3.76 (Aug-26 India −113.6 — the duty-change month).
- **SGE daily (2.12)**: `en.sge.com.cn/data/data_daily_international_new?start_date=&end_date=` HTML table (SerialNumber, Date, Contract, Open, Highest, Lowest, Close, Up/Down yuan/%, WeightedAveragePrice, Volume(Kg), Amount(yuan), OpenInterest(Lot), Direction, DeliveryVolume(Lot)); 23 Oct Au99.99 close 864.00 (−1.85%), VWAP 863.44, vol 13,963.7 kg; Au(T+D) close 863.38, vol 56,720 kg, OI 260,054, "Long to Short", delivery 24,570. Direction = who pays the deferred fee: "Short to Long" = shorts pay = physical tightness. The delayed-quotes page the app links renders zeros outside hours. Parse with bs4/regex (no lxml).
- **SGE benchmark (2.13)**: `data_BenchmarkPrice_Daily` (7 sessions; 23 Oct AM 862.91 / PM 862.76 CNY/g); `graph/DayilyJzj` JSON `{zp: AM, wp: PM}` 2,553 daily points since 19 Apr 2016 (lags HTML by a day); `data_MonthlyAveragePrice` since 2016-04.
- **SGE monthly PDF (2.14)**: list at `data_MonthlyReport`; Sep-26 PDF 5 pages (pypdf): page 5 gold delivery 613,288.68 kg (ratio 51.03%), withdrawal 92,083.24 kg, YTD 832,399.98 kg; pages 3–4 per-contract volumes with m/m, y/y (Au99.99 Sep 157,073.5 kg, +24.5% m/m, −43.1% y/y). Filenames became UUIDs from Jul-26. CN weekly 行情周报 download links are JS-generated (not verified).
- **SHFE (2.15)**: `https://www.shfe.com.cn/data/tradedata/future/dailydata/kxYYYYMMDD.dat` (old `/data/dailydata/kx/` path is 404); JSON `o_curinstrument`, filter `PRODUCTID=="au_f"`; non-trading days return a 404 HTML page. Warehouse-stock path UNVERIFIED (page `…DailyData/?query_params=dailystock` exists).
- **IMF IRFCL (2.17)**: portal 403, API open. Dims COUNTRY.INDICATOR.SECTOR.FREQUENCY; indicators `IRFCLDT1_IRFCL56V_FTO` (gold, million fine troy oz), `IRFCLDT1_IRFCL56_USD` (value), `IRFCLDT1_IRFCL57_USD`, `IRFCLDT1_IRFCL40_USD`. Query: `https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/IND+CHN+RUS+TUR+POL+USA.IRFCLDT1_IRFCL56V_FTO+IRFCLDT1_IRFCL56_USD..M?startPeriod=2025-06&format=csv` with `Accept: text/csv` (1.3 s, 334 rows). Latest: China 76.73 Moz Aug-26 (2,386.6 t; +0.65 Moz in Aug and +0.64 in Jul ≈ +20 t/month), India 28.3093 Moz = 880.5 t flat Jun–Aug (value $102.6 → 104.7 → 116.25 bn), Russia 72.80 Moz Sep-26 (2,264.3 t, −0.20), Turkey 25.443 Moz Aug (791.4 t, +0.61), Poland 21.634 Moz Sep (672.9 t, +0.80), USA 261.499 Moz Jul (8,133.5 t). Dataset updated 25 Oct 2026 06:09 UTC. Licence PUBLIC_OPEN with citation. Trap: stale months repeat the last value — check TIME_PERIOD.
- **RBI (2.18)**: `wss_rss.xml` and `pressreleases_rss.xml` work; the "Bulletin Weekly Statistical Supplement – Extract" press release (prid 63855) has the table in HTML: as on 16 Oct 2026 gold ₹10,04,583 cr / US$105,800 mn, week +US$706 mn, over end-March −9,595, y/y −2,746; total reserves US$721,016 mn (gold ≈ 14.7%). RBI's valuation convention explains US$105.8 bn ÷ 28.31 Moz ≈ $3,737/oz < spot; use IMF ounces for quantity. The brief's `website.rbi.org.in/...weekly-statistical-supplement` URL redirects to the home page; `WSSView.aspx` pages are JS shells.
- **IBJA (2.19)**: 30-day AM/PM table ₹/10 g by purity; 23 Oct 999 AM 141,448 / PM 140,882; silver 195,027/kg. Before upload the AM cell reads "Rates will be uploaded soon".
- **AMFI (2.20)**: NAVAll.txt verified (`;`-separated, section "Open Ended Schemes(Exchange Traded Funds (ETFs) - Gold ETF)", NAV 23-Oct-2026); AUM pages 404 (SPA) — WGC already carries India tonnes.
- **India imports (2.21)**: tradestat is a POST form (Trade Type/Report/Year/HS level; HS 7108; US$ mn / ₹ cr / quantity), "Last data updated on 07/08/2026"; DGCI&S DDP DNS fails; PIB Sep-26 release URL not found (content: Reuters 15 Oct, India Today "Gold imports tumble 81% … in September" 16 Oct, BusinessLine "drop 27% after customs duty hike to 15%").
- **Swiss (2.22)**: SwissImpex moved to `https://www.swissimpex.admin.ch/` (JS dashboard; manual PDF); `gate.ezv.admin.ch/swissimpex/` 404. Monthly flow map by destination — manual export.
- **HK (2.23)**: C&SD API `api/get.php?id=<table>&lang=en&param=<base64 JSON>` live (validation errors prove it); gold (SITC 971) table id unresolved.
- **Dubai (2.24)**: narrative only (DMCC "15% of global gold trade"). **US Mint/Perth (2.25)**: Mint 403; Perth monthly posts verified ("sold 23,932 troy ounces (oz) of gold … August 2026"; July 30,871 oz). **Kitco (2.27)**: page 200, images on charts.kitco.com/… and kitco.com/chart-images/…, robots allow, terms forbid framing/mirroring/robots → LINK-ONLY. **CME stocks (2.28)**: 403 Akamai, G-COT.

## 3. Metrics (formulas in the `metrics` array)
Worked Shanghai premium, 22 Oct 2026: SGE PM 879.84 CNY/g × 31.1034768 ÷ USD/CNY 6.6779 (Yahoo CNY=X) = $4,098.0/oz vs LBMA PM $4,048.25 → +$49.8/oz (+1.23%); 21 Oct: $4,120.9 vs $4,127.4 → −$6.5 (−0.16%). Pitfalls: Yahoo CNY=X had no 23 Oct row (use PBOC central parity/CFETS); SGE PM is 14:15 Beijing vs LBMA PM 15:00 London (7-hour gap — compare with LBMA AM or the COMEX print at 14:15 Beijing on volatile days); the level embeds quotas/VAT, read changes and sign flips; WGC's weekly series (+$7.76) is the sanity check. India premium: IBJA_999_PM − LBMA_PM × USDINR ÷ 3.1103477 × (1 + duty + cess); GST 3% is on top of IBJA; duty must be verified (O-3); until then show ex-duty and label it.

## 4. Cadence map (IST)
Daily: LBMA AM ~16:00 / PM ~20:35; SGE benchmark AM ~07:45 / PM ~11:45, daily table ~16:00; SHFE kx ~13:30; IBJA AM ~12:30 / PM ~17:30; GLD/IAU next morning ~06:00; AMFI NAV ~23:00; derived premiums. Weekly: WGC ETF (Monday ~11:30 for week ended Friday); LBMA turnover (12-wk MA, Friday-dated); RBI (Friday 17:00); WGC premiums (Friday-dated). Monthly: LBMA vault (~day 20–25); SGE Data Highlights (~day 10–12); IMF IRFCL (rolling 1–2 month lag, refreshed ~25th); Perth (~day 4–10); India imports (~15th release; tradestat later); Swiss (~day 20, manual). Quarterly: WGC GDT (~5 weeks after quarter; Q3-26 early Nov 2026). Annual: mine supply.

## 5. Terminal placement and de-duplication
One new page **GPHY — Gold Physical**: (1) Flows this week — WGC regional table + GLD/IAU daily, India/China pinned; (2) Premiums — daily Shanghai and India (ours) with WGC weekly as reference; (3) China desk — SGE Au99.99/Au(T+D) row, direction flag, SHFE OI, monthly withdrawals; (4) Official sector — IMF top holders and last-month buyers (each with its data month), RBI weekly value; (5) Balance sheet — WGC quarterly stacked bars + London vault line; (6) Links — PHYS, US Mint, Kitco, SwissImpex, LBMA detail, Good Delivery (67 refiners). Remove the SGE/WGC/GLD manual-check links from the pre-open desk (keep Kitco); relabel MCXG's "premium" as "MCX basis vs landed COMEX (ex-duty)"; WEI gets one "LBMA PM" chip linking to GPHY, no second table; BRIEF carries one line. New `gold_*` DuckDB tables in data-service with scheduled jobs (respecting the 07:45–09:20 and 18:30–21:15 freeze windows) so daily/weekly/monthly histories start accruing from ship day.

## 6. Evidence and proposed studies
No verified OOS timing edge at day-to-week horizons for any series here; value = regime diagnosis, risk management at the MCX open (a −12 t GLD day or a Shanghai discount in a rally argues for the desk's existing "don't chase" verdict), and the India basis the fair-open model silently assumes constant. G-STUDY queue: GS-P1 GLD daily tonnes (2004→) → 5/20-day COMEX return (runnable today); GS-P2 WGC weekly regional flows (2003→) → next-week LBMA return; GS-P3 SGE premium + Au(T+D) OI (history from 2026-10) → 5-day return; GS-P4 IRFCL monthly net CB buying → next-month return. Honest prior: FAIL as timing, PASS as context.

## Sources

### LBMA Gold Price AM/PM (via WGC Goldhub fsapi; LBMA JSON bot-walled; FRED copy removed)
- publisher: ICE Benchmark Administration / LBMA, served by World Gold Council fsapi.gold.org · url: https://fsapi.gold.org/api/goldprice/v13/chart/main?period=1y
- access: FREE · frequency: daily (AM 10:30, PM 15:00 London) · lag: same day (~20:35 IST for PM); row present next morning · history: 1y daily via period=1y; 10y downsampled; chart/price/ USD back to the 1970s (coarse)
- verified: 200, 1.3 s, JSON keys lbma_am_usd/lbma_pm_usd/_gbp/_eur, sge_am_cny/sge_pm_cny, mcx_am_inr/mcx_pm_inr; period=1y is daily (252 pts 2025-10-23→2026-10-23), 6m daily (129), 3y/10y downsampled (381/425). Last 23 Oct 2026: AM 4026.70, PM 4013.30 $/oz. prices.lbma.org.uk/json/gold_pm.json → 403 Cloudflare (both UAs); FRED GOLDPMGBD228NLBM fredgraph.csv → 404 (removed Jan 2022).
- terms: WGC T&Cs: personal, non-commercial; no scraping/redistribution/framing without written authorisation + accreditation; LBMA price is IBA-licensed for commercial use
- what it tells: The London benchmark the physical world settles on; reference for IBJA, SGE premium and ETF NAVs.
- how pros use it: Bloomberg GOLDLNPM Index / GOLDLNAM Index; bullion-bank P&L; WGC price tables
- evidence of value: It is the price itself; no predictive claim
- **verdict: PUBLISH-CORE** — The reference price every other physical number is measured against; free daily feed verified; the two brief URLs are dead/walled.
- already in app: Not shown; app uses COMEX GC=F (gold_preopen.py, commodity.py, WorldMarkets.tsx) — different instrument (futures basis), not a repetition
- ingest notes: GET period=1y at 21:00 and 09:00 IST; epoch-ms = midnight UTC of the London date; upsert gold_reference_prices(date, series, value); do not backfill long history from the downsampled 10y payload without flagging it

### LBMA Trade Data (formerly LBMA-i) — London OTC turnover
- publisher: LBMA / Nasdaq (distribution via Bloomberg, LSEG) · url: https://www.lbma.org.uk/prices-and-data/lbma-daily-trade-reporting-data
- access: FREE (headline on page) / PAID (daily and weekly product-level data) · frequency: weekly on page (12-wk MA); daily T+1 and weekly for subscribers · lag: page value Friday-dated; subscriber data T+1 · history: public page shows the latest window only; subscribers since Nov 2018
- verified: 200, 1.6 s; page text: 'Trade Reporting Weekly Turnover … 12 week moving average value of trades for the period ending 16 October 2026. Gold: $964.17 bn, Silver: $129.69 bn, Platinum: $16.10 bn, Palladium: $7.21 bn'; 'Daily reporting is available through subscription … contact Bloomberg and LSEG'. Nasdaq product page → 404 (moved).
- terms: Headline is public; full data under Nasdaq licence; open-volume reports are not netted between reporting entities
- what it tells: How much gold actually traded OTC in London (spot, swaps/forwards, options, leases): real liquidation vs futures noise; swap volume = physical financing demand. THE over-the-counter deals series.
- how pros use it: Bloomberg LBMA page (per LBMA webinar), LSEG RICs (refinitivtradedataricodes.xlsx); bullion desks
- evidence of value: Context only: gross turnover; no published directional predictive study; WGC's trading-volume estimates are built on it
- **verdict: PUBLISH-CONTEXT** — One free weekly number is worth showing with its 12-wk-MA label; the product-level data is paid, so detail is link-only
- already in app: None
- ingest notes: Monday job; regex 'Gold: \$([\d.,]+) bn' and 'period ending (\d+ \w+ \d{4})'; store lbma_turnover_weekly(period_end, metal, usd_bn); label as 12-week moving average

### LBMA London Vault Holdings Data
- publisher: LBMA · url: https://cdn.lbma.org.uk/downloads/LBMA-London-Vault-Holdings-Data-September-2026.xlsx
- access: FREE · frequency: monthly · lag: ~3–4 weeks after month-end · history: 2016-07 onward in the file
- verified: 200, 1.0 s, 23.7 KB XLSX, 123 monthly rows 2016-07→2026-09, thousand troy oz; Sep 2026 gold 315,756 koz (=9,821 t), Aug 309,681 (=9,632 t) → +189 t m/m; silver 931,898 koz (=28,985 t); link resolved from https://www.lbma.org.uk/prices-and-data/london-vault-data
- terms: Free public download; no terms inside the file; attribute LBMA
- what it tells: Whether bars are leaving London (east, COMEX, Swiss refiners) or arriving; basis of the 'free float' (vault minus BoE minus ETF-backed bars).
- how pros use it: LBMA members, float analysts; no Bloomberg function (spreadsheet)
- evidence of value: Context only (London float analysis)
- **verdict: PUBLISH-CONTEXT** — Clean official monthly series, free; a narrative/tightness input, not a timing signal
- already in app: None
- ingest notes: Monthly job ~25th: fetch vault page, find href ending .xlsx (filename changes monthly), parse (mixed date types: use pd.to_datetime(format='mixed')), upsert gold_vault_london(month_end, gold_koz, silver_koz)

### LBMA Good Delivery List (gold)
- publisher: LBMA · url: https://www.lbma.org.uk/good-delivery/gold-current-list
- access: FREE · frequency: as changed · lag: n/a · history: 
- verified: 200, 0.8 s, 397 KB; page text '67 Gold refiners'; table rendered client-side (no <tr> rows in HTML)
- terms: LBMA site T&Cs
- what it tells: Which refiners' 400-oz bars London accepts (995+ fineness).
- how pros use it: Compliance/settlement reference
- evidence of value: n/a
- **verdict: LINK-ONLY** — Reference data for the glossary, not a signal; JS-rendered
- already in app: None
- ingest notes: 

### SPDR Gold Shares (GLD) historical archive
- publisher: State Street Global Advisors / World Gold Trust Services · url: https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en
- access: FREE · frequency: daily · lag: T+1 ~06:00 IST (Friday row by Monday) · history: 2004-11-18 →
- verified: 200, 0.7 s, 542 KB XLSX; sheets Disclaimer + 'US GLD Historical Archive'; 5,720 daily rows 18 Nov 2004 → 22 Oct 2026; columns Date, Closing Price, Ounces of Gold per Share, NAV/Share 10:30, Indicative 16:15, Mid, Premium/Discount, Daily Share Volume, Total Ounces, Tonnes of Gold, Total NAV. Last tonnes 1,059.04/1,058.47/1,060.18/1,057.62/1,045.64 (22 Oct −11.98 t, 17.5 M shares). ATH 1,353.35 t 7 Dec 2012. The brief's CSV URL now redirects to api…/barlist?underlying=gld which returns the bar-list PDF.
- terms: Disclaimer sheet: 'Reproduction or redistribution of any of this information is expressly prohibited without prior written consent' — private use only, do not re-serve
- what it tells: Daily creations/redemptions in tonnes of allocated bars = cleanest daily measure of Western investment demand; premium/discount shows AP arbitrage health.
- how pros use it: Bloomberg GLD US Equity (FA/HDS, ETF flows); every gold desk's morning sheet
- evidence of value: Contemporaneous with price (WGC attribution; O'Connor et al. 2015 survey); weak lead — G-STUDY GS-P1 proposed on this history
- **verdict: PUBLISH-CORE** — 22 years of daily tonnes, free, verified; replaces the app's link-only 'GLD holdings' manual check
- already in app: MANUAL_CHECKS link to spdrgoldshares.com/usa/ in gold_preopen.py (number not shown)
- ingest notes: Daily 06:30 IST (+09:30 retry): pd.read_excel(sheet_name=1), drop 'US Holiday' rows, upsert gold_etf_daily(date, fund='GLD', tonnes, ounces, nav_usd, volume, prem_disc_pct); derive 1/5/20-day change, 20-day z, streak

### iShares Gold Trust (IAU) product page
- publisher: BlackRock iShares · url: https://www.ishares.com/us/products/239561/ishares-gold-trust-fund
- access: FREE · frequency: daily · lag: T+1 · history: page shows current only
- verified: 200, 1.3 s, 1.6 MB; embedded key-facts JSON: 'Tonnes in Trust' 463.05, Net Assets $59,737,420,617, Shares Outstanding 792,050,000, as of Oct 23, 2026. CSV endpoint (…/1467271812596.ajax?fileType=csv…) and ?tab=all&fileType=json both return the HTML page (stale id).
- terms: Standard iShares site terms; no bulk redistribution
- what it tells: Second-largest US gold ETF's tonnes; with GLD ≈ 1,510 t (~35% of all gold ETFs).
- how pros use it: Bloomberg IAU US Equity
- evidence of value: As GLD
- **verdict: PUBLISH-CONTEXT** — Confirms GLD; brittle page scrape with WGC weekly fund table as fallback
- already in app: None
- ingest notes: Regex '"Tonnes in Trust"…"formattedValue":"([\d.,]+)"'; fallback WGC archive-tablegroup fund row 'iShares Gold Trust' (462.88 t on 16 Oct)

### Sprott Physical Gold Trust (PHYS)
- publisher: Sprott · url: https://sprott.com/investment-strategies/physical-bullion-trusts/gold/
- access: BLOCKED · frequency: daily · lag: T+1 · history: 
- verified: 403 Cloudflare challenge page (6 KB) for scripts; robots.txt also 403
- terms: n/a
- what it tells: Closed-end trust: premium/discount to NAV is a retail-allocation sentiment gauge.
- how pros use it: PHYS US Equity premium/discount
- evidence of value: Context (premium as sentiment)
- **verdict: LINK-ONLY** — Bot-walled; WGC monthly bottom-10 table showed 'Sprott Physical Gold & Silver Trust' −$41.5 mn Sep 2026 so flows are visible elsewhere
- already in app: None
- ingest notes: 

### WGC Goldhub gold-ETF holdings and flows (fsapi JSON: holdings-chart2, flows-chart2, archive-tablegroup/all)
- publisher: World Gold Council · url: https://fsapi.gold.org/api/v11/charts/etfv2/revised/archive-tablegroup/all
- access: FREE (JSON, no login) / FREE-REGISTRATION (monthly XLSX; /download/file/21216/ETF_Flows_2026-10-02_1401.xlsx → 403 HTML without Goldhub login) · frequency: weekly (Monday for week ending Friday) and monthly (within 1 week of month-end) · lag: 3 days (weekly); ~1 week (monthly) · history: weekly 2003-02-28 →; monthly 284 rows
- verified: holdings-chart2 200 1.2 s 210 KB (Weekly/Monthly/Quarterly/Yearly × tonnes/usd; columns Date, North America, Europe, Asia, Other, Gold US$/oz; weekly 1,231 rows from 2003-02-28; 16 Oct 2026 NA 2,123.16 t, Europe 1,529.34, Asia 549.89, Other 76.47); flows-chart2 200 0.8 s (weekly 16 Oct: NA +7.29 t, Europe +1.96, Asia +4.72, Other −0.28; Sep monthly NA +27.72, Europe +21.72, Asia +16.85, Other +1.65); archive-tablegroup/all 200 0.7 s: regional (Total 4,278.86 t, AUM $578.74 bn, week +13.69 t/+$1,903.8 mn), countries (21; India 124.41 t/$19.12 bn, China 310.90 t), top10/bottom10 funds (SPDR Gold Shares +6.19 t; iShares Gold Trust −0.96 t) for Weekly/Monthly/Quarterly/YTD with asOfDate 2026-10-16 / 2026-09-30
- terms: WGC T&Cs: personal, non-commercial; no scraping/distribution/framing without prior written authorisation and accreditation; robots.txt does not disallow /goldhub/data; XLSX route requires free registration
- what it tells: Global ETF demand by region, country (India, China) and fund — the picture GLD alone misses (Asia-led inflows in 2025–26).
- how pros use it: WGC/Bloomberg 'ETF inflows' headlines; strategists' regional demand read
- evidence of value: Contemporaneous; regional split is diagnostic; GS-P2 proposed (weekly regional flows 2003→ vs next-week return)
- **verdict: PUBLISH-CORE** — Only free source of global/regional/fund-level ETF tonnes with 23-year weekly history; terms posture needs owner decision (O-1)
- already in app: MANUAL_CHECKS link to gold.org ETF page (number not shown)
- ingest notes: Monday 12:00 IST job + daily asOfDate check; parse 3 JSONs; strings → floats; columns contain <br/>; some fund rows None; upsert gold_etf_wgc_weekly(week_end, level, name, holdings_t, flow_t, flow_usd_mn, aum_usd_bn); cache 1 h; attribute 'World Gold Council, gold.org'

### WGC Goldhub supply and demand statistics (quarterly balance sheet)
- publisher: World Gold Council / Metals Focus · url: https://fsapi.gold.org/api/v11/charts/supply-and-demand/43
- access: FREE (JSON) / FREE-REGISTRATION (GDT_Tables_Q2'26_EN.xlsx → 403 without login) · frequency: quarterly · lag: ~5 weeks after quarter-end (Q3-26 due early Nov 2026) · history: 2010 →
- verified: 200, 0.4 s, 16 KB; Supply/Demand Quarterly (66 quarters Q1'10→Q2'26) and Annually (2010→2025); series: Mine production, Net producer hedging, Recycled gold; Jewellery consumption/inventory/fabrication, Technology (Electronics, Other industrial, Dentistry), Investment (Total bar & coin: Physical bar, Official coin, Medals), ETFs, Central banks, LBMA avg price. Q2-26: mine 965.579, hedging −22.781, recycled 326.094; jewellery fab 310.33, technology 80.355, bar&coin 307.083, ETFs −44.838, CB 288.862; LBMA Q2-26 avg $4,506.3. 2025: mine 3,822.88, recycled 1,403.79, hedging −53.93; jewellery fab 1,647.67, tech 322.87, bar&coin 1,405.94, ETFs 803.32, CB 848.17. asOfDate 2026-06-30.
- terms: WGC T&Cs as above
- what it tells: The structure: who is the marginal buyer (central banks floor, ETF momentum, price-sensitive jewellery brake); OTC/other residual.
- how pros use it: Gold Demand Trends report; strategist decks
- evidence of value: Structural; context only; revised each release
- **verdict: PUBLISH-CONTEXT** — Essential for understanding, useless for timing; one stacked-bar panel refreshed quarterly
- already in app: None
- ingest notes: Monthly check; parse categories/series into gold_supply_demand(period, line, tonnes); flag revisions by storing vintage date

### WGC local gold price premiums (India, China)
- publisher: World Gold Council / Metals Focus · url: https://fsapi.gold.org/api/v11/charts/local-gold-price-premiums
- access: FREE · frequency: weekly · lag: Friday-dated, published following week · history: ~5 years weekly
- verified: 200, 1.6 s; india_premdisc and china_premdisc weekly, 255 points; 16 Oct 2026 India +11.44 $/oz, China +7.76 $/oz; -thumb variant monthly 12 points (Sep-26 China +24.59, India −3.76; Aug-26 India −113.63)
- terms: WGC T&Cs
- what it tells: What a buyer in Mumbai/Shanghai pays over London after duty and freight: discount = local demand cannot absorb supply; premium = scarcity.
- how pros use it: WGC/Reuters 'India discount/China premium' commentary
- evidence of value: Context; no published forward-return evidence
- **verdict: PUBLISH-CONTEXT** — Industry reference premium; our daily IBJA/SGE-based premiums are the fast version, this is the sanity check
- already in app: GoldPreOpen/McxGoldDesk show an 'implied premium %' = MCX vs landed COMEX ex-duty (futures basis, not the dealer premium) — relabel to avoid apparent disagreement
- ingest notes: Weekly GET; epoch-ms dates; store gold_local_premium_wgc(week_end, market, usd_per_oz)

### WGC central-bank gold statistics page
- publisher: World Gold Council (IMF IFS based) · url: https://www.gold.org/goldhub/data/gold-reserves-by-country
- access: FREE page / FREE-REGISTRATION for XLSX · frequency: monthly · lag: 1–2 months · history: 
- verified: 200, 0.5 s; 'Data as of 30 June, 2026', IFS September 2026 edition; XLSX links World_official_gold_holdings_as_of_Oct2026_IFS.xlsx, Changes_latest_as_of_Oct2026_IFS.xlsx, Quarterly_gold_and_FX_Reserves_Q2_2026.xlsx all → 403 HTML without Goldhub login; dashboard 'limited' when not logged in
- terms: WGC T&Cs; registration for downloads
- what it tells: Official reserves by country, % of reserves, monthly changes.
- how pros use it: Press headlines on central-bank buying
- evidence of value: See IMF IRFCL
- **verdict: LINK-ONLY** — Superseded by the free, machine-readable IMF IRFCL API which carries the same ounces; WGC adds commentary only
- already in app: None
- ingest notes: Not needed; compute % of reserves from IRFCL gold value ÷ total reserves

### Shanghai Gold Exchange daily market data (international/main board table)
- publisher: Shanghai Gold Exchange · url: https://en.sge.com.cn/data/data_daily_international_new?start_date=2026-10-20&end_date=2026-10-23
- access: FREE · frequency: daily · lag: same evening (~16:00 IST) · history: query any date range (keep ≤1 month per call); CN site has historical data pages
- verified: 200, 2.6 s, HTML table 21 rows/4 days; headers SerialNumber, Date, Contract, Open, Highest, Lowest, Close, Up/Down(yuan), Up/Down(%), WeightedAveragePrice, Volume(Kg), Amount(yuan), OpenInterest(Lot), Direction, DeliveryVolume(Lot). 23 Oct 2026: Au99.99 close 864.00 (−1.85%), VWAP 863.44, volume 13,963.7 kg; Au(T+D) close 863.38, volume 56,720 kg, OI 260,054 lots, Direction 'Long to Short', delivery 24,570 lots; iAu99.99 862.33. The app's linked data_DelayedQuotes page renders zeros outside hours (JS). No robots.txt on either SGE host.
- terms: Public data; terms not stated in English; attribute SGE
- what it tells: Chinese physical price (→ Shanghai premium), Au(T+D) open interest (Chinese positioning), delivery volume, and the settlement-fee Direction: 'Short to Long' = shorts pay = physical tightness.
- how pros use it: China desks; Reuters 'Shanghai premium/discount' reports
- evidence of value: Context; GS-P3 proposed once history accrues
- **verdict: PUBLISH-CORE** — Daily, free, structured; replaces the link-only SGE manual check with real numbers incl. the tightness flag
- already in app: MANUAL_CHECKS link to en.sge.com.cn/data_DelayedQuotes
- ingest notes: Daily 16:00 IST GET with start=end=today; parse with bs4/regex (lxml not installed); upsert sge_daily(date, contract, ohlc, vwap, volume_kg, amount_cny, oi_lots, direction, delivery_lots)

### SGE Shanghai Gold Benchmark Price (SHAU) AM/PM
- publisher: Shanghai Gold Exchange · url: https://en.sge.com.cn/graph/DayilyJzj
- access: FREE · frequency: daily (AM ~10:15, PM ~14:15 Beijing) · lag: HTML same day; JSON one day · history: 2016-04-19 →
- verified: GET → 200, 2.7 s, JSON {zp: [[epoch_ms, AM]…], wp: [[…PM]]}, 2,553 daily points since 19 Apr 2016, last 22 Oct 2026 (884.95/879.84); https://en.sge.com.cn/data_BenchmarkPrice_Daily → 200 last 7 sessions, 23 Oct AM 862.91 / PM 862.76 CNY/g; data_MonthlyAveragePrice → 200 monthly averages since 2016-04
- terms: Public data; attribute SGE
- what it tells: China's benchmark in CNY/g — the CNY leg of the Shanghai premium; referenced by Chinese banks and the PBOC.
- how pros use it: Shanghai premium calculations; WGC price tables
- evidence of value: Price itself
- **verdict: PUBLISH-CORE** — Full daily history free; needed for the premium
- already in app: None
- ingest notes: Daily: both endpoints; store gold_reference_prices(series='SGE_AM_CNY'|'SGE_PM_CNY'); backfill from JSON; zp/wp = 早盘/晚盘

### SGE monthly Data Highlights PDF (volumes, delivery, withdrawals)
- publisher: Shanghai Gold Exchange · url: https://en.sge.com.cn/data_MonthlyReport
- access: FREE · frequency: monthly · lag: ~10–12 days after month-end · history: PDFs listed from Dec 2025 on the EN page; older via CN site
- verified: List page 200 with PDF links Dec-25→Sep-26; Sep 2026 PDF (…/upload/file/202610/12/0e7caabc-d215-4949-9c1f-d848b03332eb.pdf) 200, 6.0 s, 5 pages, pypdf-extractable: gold delivery volume Sep 613,288.68 kg (ratio 51.03%), YTD 5,873,644.04 kg; withdrawal volume Sep 92,083.24 kg, YTD 832,399.98 kg; silver withdrawals 147,465 kg; per-contract volumes with m/m, y/y (Au99.99 Sep 157,073.5 kg +24.53% m/m −43.09% y/y; Au(T+D) 871,508 kg)
- terms: Public PDF; attribute SGE
- what it tells: 'SGE withdrawals' — kilograms physically taken out of SGE vaults: the public proxy for Chinese wholesale demand; 92 t/month vs 130–170 t/month in 2013–19 = weak offtake at these prices.
- how pros use it: China demand commentary (Reuters, bullion-bank notes)
- evidence of value: Popular 2013–16 narrative; no robust forward-return evidence (context)
- **verdict: PUBLISH-CONTEXT** — The famous demand series, free and monthly; no timing value
- already in app: None
- ingest notes: Monthly ~12th: fetch list page, newest PDF href (filenames are UUIDs since Jul-26), pypdf page 5, regex 'Withdrawal Volume \(Present Month\)\s+([\d,\.]+)'; store sge_monthly(month, withdrawals_kg, delivery_kg, delivery_ratio)

### SHFE daily futures data (kx JSON)
- publisher: Shanghai Futures Exchange · url: https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261023.dat
- access: FREE · frequency: daily · lag: after 15:00 Beijing (~13:30 IST) · history: daily files by date (verified 2025-10-24 and 2026-10-23)
- verified: 200, 4.2 s, 123 KB JSON key o_curinstrument (331 rows), 9 'au' rows (PRODUCTID 'au_f', DELIVERYMONTH, PRESETTLEMENTPRICE, OPEN/HIGH/LOW/CLOSE/SETTLEMENTPRICE, VOLUME, OPENINTEREST, OPENINTERESTCHG, TURNOVER); 23 Oct 2026 au2612 settle 869.20 CNY/g, close 864.36, volume 286,554, OI 198,578 (−9,623); au2702 OI 101,168. Same format verified for kx20251024.dat. Old path /data/dailydata/kx/ → 404.
- terms: Public exchange data; attribute SHFE
- what it tells: Chinese futures positioning and curve (1 lot = 1 kg); SHFE–SGE basis with USD/CNY gives a China carry read.
- how pros use it: China desks; Bloomberg SHFE gold tickers
- evidence of value: Context
- **verdict: PUBLISH-CONTEXT** — Useful one-row context; positioning analysis belongs to G-COT
- already in app: None
- ingest notes: Daily 13:30 IST GET; filter PRODUCTID=='au_f' and real delivery months; non-trading day returns a 404 HTML (4.8 KB); store shfe_daily(date, month, settle, volume, oi, oi_chg)

### SHFE gold warehouse stocks
- publisher: Shanghai Futures Exchange · url: https://www.shfe.com.cn/eng/reports/StatisticalData/DailyData/?query_params=dailystock
- access: UNVERIFIED · frequency: weekly · lag: ~Friday · history: 
- verified: EN page link exists; four guessed .dat paths (…/dailydata/20261023dailystock.dat, dailystock20261023.dat, weeklydata/20261023weeklystock.dat, weeklystock20261023.dat) → 404; page is JS
- terms: Public
- what it tells: Deliverable gold in SHFE vaults (China's COMEX-stocks equivalent).
- how pros use it: China physical tightness
- evidence of value: Context
- **verdict: LINK-ONLY** — Cannot be fetched without the XHR path (owner action O-5)
- already in app: None
- ingest notes: Capture the request URL from a browser network tab, then same pattern as kx

### IMF IRFCL — official monetary gold by country (ounces and US$), SDMX API
- publisher: International Monetary Fund (Statistics Dept) · url: https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/IND+CHN+RUS+TUR+POL+USA.IRFCLDT1_IRFCL56V_FTO+IRFCLDT1_IRFCL56_USD+IRFCLDT1_IRFCL57_USD+IRFCLDT1_IRFCL40_USD..M?startPeriod=2025-06&format=csv
- access: FREE · frequency: monthly · lag: 1–2 months (ragged by country) · history: from 2000 for most reporters
- verified: dataflow list 200 (223 flows; IMF.STA:IRFCL 12.0.0); structure 200 (dims COUNTRY.INDICATOR.SECTOR.FREQUENCY); data CSV 200, 1.3 s, 334 rows (Accept: text/csv). Latest: China 76.73 Moz Aug-26 (=2,386.6 t; +0.65 Moz Aug, +0.64 Jul), India 28.3093 Moz = 880.5 t flat Jun–Aug (value $102.59→104.74→116.25 bn), Russia 72.80 Moz Sep-26 (−0.20), Turkey 25.443 Moz Aug (+0.61), Poland 21.634 Moz Sep (+0.80), USA 261.499 Moz Jul. UPDATE_DATE 2026-10-25T06:09Z; LICENSE © IMF; ACCESS_SHARING_LEVEL PUBLIC_OPEN. data.imf.org portal → 403 (bot wall) but API open.
- terms: © IMF, PUBLIC_OPEN, suggested citation: IMF IRFCL, data.imf.org/en/datasets/IMF.STA:IRFCL
- what it tells: Who is buying: central-bank net purchases in tonnes (the structural bid of 2022–26); China's consecutive +20 t months.
- how pros use it: WGC monthly CB stats; Bloomberg country reserve series; de-dollarisation research
- evidence of value: Structural/slow; no month-level timing evidence; GS-P4 (low priority)
- **verdict: PUBLISH-CORE** — Primary source behind every 'central banks bought' headline; free, open, machine-readable, verified
- already in app: None
- ingest notes: Monthly ~26th and ~8th: pull all countries for IRFCL56V_FTO (leave COUNTRY empty between dots) from 2000; store cb_gold_reserves(country, month, oz_m, usd); tonnes = Moz × 31.1034768; keys are positional (IND..M); stale months repeat last value — check TIME_PERIOD; some countries quarterly

### RBI Weekly Statistical Supplement — Foreign Exchange Reserves (gold line)
- publisher: Reserve Bank of India · url: https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=63855
- access: FREE · frequency: weekly (Friday 17:00 IST) · lag: 7 days (data for previous Friday) · history: weekly press releases/RSS
- verified: wss_rss.xml 200 (items 'Weekly Statistical Supplement (October 23, 2026)', 'Foreign Exchange Reserves' WSSView.aspx?Id=28789); press release 'Bulletin Weekly Statistical Supplement – Extract' 200, 0.7 s, HTML table: as on 16 Oct 2026 gold ₹10,04,583 cr / US$105,800 mn; week +US$706 mn; over end-March −9,595; y/y −2,746; total reserves US$721,016 mn. WSSView pages are JS shells; brief's website.rbi.org.in WSS URL redirects to the home page.
- terms: © RBI, public
- what it tells: India's gold reserve value weekly and its share of reserves (~14.7%); tonnage comes from IMF (880.5 t).
- how pros use it: India macro desks
- evidence of value: Context
- **verdict: PUBLISH-CONTEXT** — Official weekly; value mostly reflects price and RBI's revaluation convention (US$105.8 bn ÷ 28.31 Moz ≈ $3,737/oz < spot)
- already in app: None
- ingest notes: Friday 17:30 IST: read pressreleases_rss.xml, find 'Weekly Statistical Supplement – Extract', regex the '1.2 Gold' row; store rbi_gold_weekly(as_on, inr_cr, usd_mn, wow_usd_mn)

### IBJA daily gold rates (India benchmark ₹/10 g)
- publisher: India Bullion & Jewellers Association · url: https://ibjarates.com/
- access: FREE · frequency: daily (AM ~12:30, PM ~17:30 IST) · lag: same day · history: 30 days on page
- verified: 200, 0.4 s, 156 KB; today's 999/995/916/750/585 ₹/g and a 30-day AM/PM table ₹ per 10 g: 23/10/2026 999 AM 141,448 / PM 140,882; 22/10 143,152; silver 999 ₹195,027/kg; platinum. Before upload the AM cell reads 'Rates will be uploaded soon'.
- terms: Public page; no redistribution clause found (terms page not fetched)
- what it tells: India's domestic spot reference (used for Sovereign Gold Bonds); with the landed cost gives the India physical premium/discount daily.
- how pros use it: Indian bullion dealers; SGB pricing
- evidence of value: Context; India premium is a demand/duty read
- **verdict: PUBLISH-CORE** — The India premium needs a domestic spot; IBJA is the official one and is free
- already in app: None (WGC price payload also carries mcx_am_inr/mcx_pm_inr: 23 Oct 141,031)
- ingest notes: Daily 18:00 IST: parse 'Previous 30 Days' table (date, AM/PM per purity); store ibja_daily(date, purity, am, pm)

### AMFI NAVAll.txt (daily NAV, all schemes incl. gold ETFs)
- publisher: Association of Mutual Funds in India · url: https://www.amfiindia.com/spages/NAVAll.txt
- access: FREE · frequency: daily · lag: same night (~23:00 IST) · history: NAV history via portal DownloadNAVHistoryReport (not verified)
- verified: 302 → portal.amfiindia.com/spages/NAVAll.txt 200, 1.5 s, 1.5 MB, ';'-separated (Scheme Code; ISIN; ISIN; Scheme Name; Plan; Option; NAV; Date); section 'Open Ended Schemes(Exchange Traded Funds (ETFs) - Gold ETF)' ~80 rows (Aditya Birla, Axis, DSP, Groww, 360 ONE, Baroda BNP, Choice…), NAV 23-Oct-2026
- terms: Public
- what it tells: NAV per Indian gold ETF (price only, no tonnes).
- how pros use it: Indian wealth desks
- evidence of value: Price only
- **verdict: PUBLISH-CONTEXT** — Useful for the owner's own ETF choices; tonnes/flows for India come from WGC (124.4 t, Sep +3.1 t)
- already in app: None
- ingest notes: Daily 23:30 IST: parse rows under the Gold ETF header; store amfi_gold_etf_nav(date, scheme, nav)

### AMFI monthly AUM per scheme
- publisher: AMFI · url: https://www.amfiindia.com/research-information
- access: UNVERIFIED · frequency: monthly · lag: ~10 days · history: 
- verified: Brief's URLs /research-information/aum-data/average-aum and /other-data/mf-industry-monthly-data → 404; home and research pages are a Next.js SPA with no data links; portal.amfiindia.com/AUMReport.aspx → 404
- terms: Public
- what it tells: ₹ AUM per gold ETF.
- how pros use it: Indian fund-flow commentary
- evidence of value: n/a
- **verdict: LINK-ONLY** — Not machine-discoverable from here; WGC country table already gives India tonnes and AUM
- already in app: None
- ingest notes: Capture the SPA's API call from a browser if ever needed

### India gold imports — Ministry of Commerce tradestat (DGCI&S) HS 7108
- publisher: Department of Commerce / DGCI&S · url: https://tradestat.commerce.gov.in/eidb/commodity_wise_export
- access: FREE (interactive POST form, no API) · frequency: monthly · lag: ~45 days (tradestat); ~15th (press release) · history: FY2017-18 →
- verified: 200, 0.4 s: 'Data available 2017-2018 to 2025-2026 · Last data updated on 07/08/2026'; form fields Eidb_ReportCwe, EidbYearCwe, EidbComLevelCwe, HS search; values in US$ mn / ₹ cr / quantity. dgciskol.gov.in 200 ('PC level data up to June 2026 uploaded'); ddp.dgcis.gov.in DNS failure; PIB Sep-2026 release URL not found by search (content confirmed via Reuters 15 Oct, India Today 16 Oct 'Gold imports tumble 81% … in September', BusinessLine 'drop 27% after customs duty hike to 15%')
- terms: Government open data
- what it tells: India's physical imports in tonnes/US$ — demand destruction when price or duty rises; festival-season seasonality.
- how pros use it: India macro/bullion desks; current-account analysis
- evidence of value: Context
- **verdict: PUBLISH-CONTEXT** — Important monthly demand number for the #2 consumer, but manual until a stable URL/API exists
- already in app: None
- ingest notes: Owner-run monthly form query (Imports, Commodity-wise, HS 7108, quantity + US$) → india_gold_imports(month, usd_mn, kg); capture the press-release sentence via the Google News RSS the desk already uses

### India monthly trade press release (PIB / Commerce) — gold imports line
- publisher: Press Information Bureau / Department of Commerce · url: https://www.pib.gov.in/allRel.aspx
- access: UNVERIFIED · frequency: monthly (~15th) · lag: ~15 days · history: 
- verified: PIB listing 200; Google News RSS site:pib.gov.in 'Foreign Trade' returned 2013–2020 items only; commerce.gov.in/press-releases/ → 404; the September 2026 release exists per Reuters/India Today 15–16 Oct 2026
- terms: Government
- what it tells: Official 'gold imports US$ x bn, y/y' sentence.
- how pros use it: Headline source for 'India gold imports'
- evidence of value: Context
- **verdict: LINK-ONLY** — URL pattern not discoverable from here
- already in app: None
- ingest notes: Resolve PRID pattern once; or use news RSS

### Swiss customs gold trade (FOCBS SwissImpex)
- publisher: Federal Office for Customs and Border Security (BAZG/FOCBS) · url: https://www.swissimpex.admin.ch/
- access: FREE (JS dashboard; no API found) · frequency: monthly · lag: ~20 days · history: 
- verified: bazg.admin.ch foreign-trade page 200 → links to SwissImpex dashboard; swissimpex.admin.ch 200 but JS app (text 'AHST'); old gate.ezv.admin.ch/swissimpex/ and index.xhtml → 404; manual PDF available
- terms: Swiss open government data
- what it tells: Where physical gold is flowing (Swiss refiners handle ~2/3 of world gold): exports to India, China, HK, UK, US, Turkey by month.
- how pros use it: Reuters/bullion-bank monthly 'Swiss exports to India/China' notes
- evidence of value: Context
- **verdict: LINK-ONLY** — The best monthly flow map, but only via manual dashboard export from this machine
- already in app: None
- ingest notes: Manual monthly export (tariff 7108 by country) or automate the dashboard's XHR later

### Hong Kong C&SD merchandise trade (gold with mainland China)
- publisher: Census and Statistics Department, HKSAR · url: https://www.censtatd.gov.hk/en/scode230.html
- access: FREE (API live; gold table id unresolved) · frequency: monthly · lag: ~4 weeks · history: 
- verified: page 200; API https://www.censtatd.gov.hk/api/get.php?id=410-51001&lang=en → 200 'Parameter is not defined' (proves the API is live; needs base64 param); web_table 410-51001 page 200 with XLSX/CSV/API download options; SITC 971 gold table id not found this session
- terms: Open data
- what it tells: HK gold imports/re-exports to the mainland — the classic China-demand proxy.
- how pros use it: China demand proxy (2012–17 staple)
- evidence of value: Context
- **verdict: LINK-ONLY** — Verifiable API but the gold row was not resolved (owner action O-5)
- already in app: None
- ingest notes: Find the table id via web_table.html?id=…&api_popup=1 for the SITC commodity table, then GET api with param

### Dubai (DMCC / Dubai Customs)
- publisher: DMCC; Dubai Customs · url: https://dmcc.ae/ecosystems/gold
- access: FREE page, no data series · frequency: ad hoc · lag: n/a · history: 
- verified: dmcc.ae 200 ('15% Dubai's share of the global trade of gold', DGCX 2023 stats); dubaicustoms.gov.ae 200 generic page; no machine-readable gold series
- terms: n/a
- what it tells: Narrative on the Middle East/Africa hub and DGCX gold futures.
- how pros use it: n/a
- evidence of value: n/a
- **verdict: DO-NOT-PUBLISH** — No series to show; glossary mention only
- already in app: None
- ingest notes: 

### US Mint bullion sales
- publisher: United States Mint · url: https://www.usmint.gov/about/production-sales-figures/bullion-sales
- access: BLOCKED · frequency: monthly · lag: ~1 week · history: 
- verified: 403 Cloudflare 'Just a moment' (6 KB) for scripts; robots.txt also 403
- terms: US government
- what it tells: American Eagle/Buffalo coin sales — US retail demand gauge.
- how pros use it: Retail demand commentary
- evidence of value: Context (sentiment)
- **verdict: LINK-ONLY** — Bot-walled
- already in app: None
- ingest notes: 

### Perth Mint monthly sales updates
- publisher: The Perth Mint · url: https://www.perthmint.com/news/
- access: FREE · frequency: monthly · lag: ~1–2 weeks · history: posts since 2015 on the site
- verified: 200, 1.4 s, 515 KB; monthly posts Mar–Aug 2026 (…/august-2026-sales-update/): 'The Perth Mint sold 23,932 troy ounces (oz) of gold, 333,880 oz of silver and 1,060 oz of platinum in minted product form during August 2026' (posted 4 Sep); July 30,871 oz gold; robots.txt allows
- terms: Public blog; cite
- what it tells: Minted coin/bar demand (Western and Asian retail) — small in tonnes (~0.7 t/month), a sentiment gauge.
- how pros use it: Retail demand commentary
- evidence of value: Context
- **verdict: PUBLISH-CONTEXT** — Free, regular, one number; not a balance-sheet mover
- already in app: None
- ingest notes: Monthly regex on the news list: 'sold ([\d,]+) troy ounces \(oz\) of gold'; store mint_sales(month, mint, gold_oz)

### Mine supply and recycling (WGC quarterly; company reports)
- publisher: World Gold Council / Metals Focus; miners · url: https://fsapi.gold.org/api/v11/charts/supply-and-demand/43
- access: FREE (JSON); company reports LINK-ONLY · frequency: quarterly / annual · lag: ~5 weeks / annual · history: 
- verified: Q2-26 mine 965.58 t (Q1-26 901.34), recycled 326.09 t, hedging −22.78; 2025 mine 3,822.88, recycled 1,403.79
- terms: WGC T&Cs
- what it tells: New supply is <2.5% of above-ground stock; recycling rises with price (holders selling).
- how pros use it: Mining analysts; GDT
- evidence of value: Structural; context
- **verdict: PUBLISH-CONTEXT** — Inside the balance-sheet panel only; never a daily number
- already in app: None
- ingest notes: 

### CME COMEX gold warehouse stocks (cross-ref G-COT)
- publisher: CME Group · url: https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls
- access: BLOCKED · frequency: daily · lag: T+1 · history: 
- verified: 403 Akamai (602 bytes) for scripts; robots.txt 403
- terms: CME data terms
- what it tells: Registered/eligible gold in COMEX vaults — the US leg of the physical balance sheet.
- how pros use it: COMEX delivery/stocks analysis
- evidence of value: Context (delivery squeeze narratives)
- **verdict: LINK-ONLY** — G-COT's brief; bot-walled from this machine
- already in app: None
- ingest notes: 

### Kitco gold charts
- publisher: Kitco Metals · url: https://www.kitco.com/charts/gold
- access: FREE page; terms prohibit framing/robots · frequency: live · lag: n/a · history: 
- verified: 200, 0.6 s; chart images at https://charts.kitco.com/images/live/gold_3day_usd.webp and https://www.kitco.com/chart-images/LFgif/AU0030lnb.gif; robots.txt Allow: /; terms-of-use (200): 'Frame or mirror any content … without our prior written authorization' and 'Use any robot, spider, site search/retrieval application… to download, retrieve, index' prohibited
- terms: Kitco Terms of Use (no framing/mirroring/robots)
- what it tells: Spot gold intraday chart and news.
- how pros use it: Retail reference; news
- evidence of value: n/a
- **verdict: LINK-ONLY** — Terms forbid embedding/hot-linking; the desk already has spot from Yahoo and will have LBMA/SGE benchmarks
- already in app: MANUAL_CHECKS link (keep)
- ingest notes: 

### FRED GOLDAMGBD228NLBM / GOLDPMGBD228NLBM
- publisher: FRED (St. Louis Fed), data from IBA · url: https://fred.stlouisfed.org/series/GOLDPMGBD228NLBM
- access: BLOCKED (removed) · frequency: n/a · lag: n/a · history: 
- verified: fredgraph.csv → 404 for both IDs; series pages redirect to fred.stlouisfed.org/news/2022/01/ice-benchmark-administration-ltd-iba-data-to-be-removed-from-fred
- terms: n/a
- what it tells: (was) LBMA AM/PM price.
- how pros use it: n/a
- evidence of value: n/a
- **verdict: DO-NOT-PUBLISH** — Dead reference in the brief; use the WGC fsapi feed
- already in app: None (app uses FRED only for DFII10)
- ingest notes: 

### Nasdaq Data Link LBMA/GOLD
- publisher: Nasdaq Data Link (ex-Quandl) · url: https://data.nasdaq.com/api/v3/datasets/LBMA/GOLD.json?rows=3
- access: UNVERIFIED · frequency: daily · lag: T+1 · history: 
- verified: 403 Incapsula without an API key
- terms: Nasdaq Data Link terms
- what it tells: LBMA AM/PM history in USD/GBP/EUR.
- how pros use it: Quant backfills
- evidence of value: Price
- **verdict: LINK-ONLY** — Needs a free key; free-tier availability of the LBMA dataset not confirmable from here
- already in app: None
- ingest notes: If the owner creates a key: NASDAQ_DATA_LINK_API_KEY in .env, test rows=3

### SAFE China official reserve assets
- publisher: State Administration of Foreign Exchange (China) · url: https://www.safe.gov.cn/en/OfficialReserveAssets/index.html
- access: FREE page; no table in HTML · frequency: monthly (~7th) · lag: ~1 week · history: 
- verified: 200, 2.4 s; navigation text only, no data table or dated links in the HTML
- terms: Chinese government
- what it tells: China's own monthly gold line (oz and US$).
- how pros use it: PBOC buying headlines
- evidence of value: See IMF
- **verdict: LINK-ONLY** — Same number arrives via IMF IRFCL (China Aug-26 76.73 Moz) which is machine-readable
- already in app: None
- ingest notes: 

## Metrics

### Global gold-ETF flow by region (weekly, monthly) (weekly)
- definition: Net creations minus redemptions across all physically backed gold ETFs, in tonnes and US$ mn, by North America / Europe / Asia / Other and total.
- formula: flow_t = holdings_t − holdings_{t−1} per region (WGC flows-chart2 provides it directly); demand % = flow ÷ holdings
- inputs: WGC fsapi holdings-chart2, flows-chart2, archive-tablegroup/all
- beginner: An ETF holds real bars; when investors buy more shares than exist, new bars are bought and 'holdings' rise. This is the clearest weekly measure of investment demand, and the regional split shows whether Asia or the West is driving it.
- pro: Contemporaneous with price (WGC attribution); treat as confirmation/diagnosis, not a lead; terms require attribution and no redistribution
- **verdict: PUBLISH-CORE** — Free weekly data since 2003 with regional/fund detail; week 42 2026 +13.7 t, Asia 2.5× NA as % of holdings

### GLD daily creation/redemption (tonnes) (daily)
- definition: Day-on-day change in tonnes of gold held by SPDR Gold Shares; 5- and 20-day sums; 20-day z-score; streak length.
- formula: Δt = tonnes_t − tonnes_{t−1}; z20 = (Δt − mean20)/sd20
- inputs: GLD historical-archive XLSX (5,720 rows)
- beginner: The biggest gold fund reports every day how many tonnes it holds. A −12 t day (22 Oct 2026) means real bars were sold, not just paper.
- pro: Holiday rows carry text; ounces per share decays by the expense ratio; premium/discount column flags AP stress
- **verdict: PUBLISH-CORE** — 22-year daily history, free, T+1; the only physical series long enough for a proper study now (GS-P1)

### Shanghai premium (daily)
- definition: SGE Shanghai Gold Benchmark PM (CNY/g) converted to $/oz minus LBMA PM, in $/oz and %.
- formula: prem = SGE_PM_CNY_g × 31.1034768 ÷ USDCNY − LBMA_PM_USD_oz; pct = prem ÷ LBMA_PM
- inputs: SGE DayilyJzj / data_BenchmarkPrice_Daily; WGC fsapi LBMA PM; USD/CNY (Yahoo CNY=X or PBOC central parity)
- beginner: How much more (or less) gold costs in Shanghai than in London for the same ounce. A premium means Chinese buyers are pulling metal in; a discount means they have stepped back.
- pro: SGE PM 14:15 Beijing vs LBMA PM 15:00 London (7-hour gap) — compare with LBMA AM on volatile days; level embeds quotas/VAT so read changes and sign flips; Yahoo CNY=X had a missing 23 Oct row; WGC weekly China premium (+$7.76 on 16 Oct) is the sanity check
- **verdict: PUBLISH-CORE** — Worked example 22 Oct 2026: +$49.8/oz (+1.23%); 21 Oct −$6.5; all inputs verified free

### India physical premium/discount (daily)
- definition: IBJA 999 PM rate (₹/10 g) minus the landed cost of London gold in India.
- formula: landed = LBMA_PM × USDINR ÷ 3.1103477 × (1 + duty + cess); premium = IBJA_999_PM − landed (₹/10 g), and ÷ (USDINR/3.1103477) for $/oz
- inputs: IBJA daily; WGC fsapi LBMA PM; Yahoo INR=X; import duty table (to be verified)
- beginner: Whether Indian buyers pay more or less than the imported cost. A discount means jewellers are not buying (weak demand); a premium means scarcity or smuggling incentives.
- pro: GST 3% is on top of IBJA; MCX futures embed the same duty, so the app's existing 'implied premium' (MCX vs landed COMEX ex-duty) must be relabelled as basis, not premium; WGC monthly India premium Aug-26 was −$113.6 (duty-change month)
- **verdict: PUBLISH-CORE** — India is the #2 consumer and the owner trades MCX; both inputs verified; but the duty (headlines say 15% from Oct 2026) must be verified first (O-3) — show ex-duty and label it until then

### Central-bank net gold purchases (monthly)
- definition: Month-on-month change in official monetary gold holdings per country, in tonnes; top buyers/sellers and the sum of the top-30.
- formula: Δt = (oz_m − oz_{m−1}) × 31.1034768 ÷ 1e6 (oz in million fine troy oz)
- inputs: IMF IRFCL indicator IRFCLDT1_IRFCL56V_FTO (and _IRFCL56_USD for value)
- beginner: Central banks have been the steadiest big buyer of gold since 2022; this shows which banks added metal last month (China +20 t in Jul and Aug 2026).
- pro: Ragged lags (India/China Aug, Russia/Poland Sep as of 25 Oct); repeats of the last value are not 'unchanged'; China is believed to under-report; revisions common
- **verdict: PUBLISH-CORE** — Primary, free, open-licence source; verified for 6 countries; each country's data month differs — show it

### SGE withdrawals and delivery ratio (monthly)
- definition: Kilograms physically withdrawn from SGE vaults in the month; delivery volume ÷ trading volume.
- formula: from the Data Highlights PDF page 5; tonnes = kg ÷ 1000; y/y vs same month
- inputs: SGE monthly Data Highlights PDF
- beginner: Gold taken out of the Shanghai exchange's vaults is gold going to Chinese jewellers, banks and investors — the closest public measure of Chinese wholesale demand (92 t in Sep 2026).
- pro: Series became less watched after 2019 when SGE changed reporting; compare with 2013–19 run-rates of 130–170 t/month
- **verdict: PUBLISH-CONTEXT** — Free, official, monthly; narrative value, no timing value

### SGE Au(T+D) open interest and settlement direction (daily)
- definition: Open interest (lots = kg) of the deferred contract and the daily 'Direction' flag: Long to Short (longs pay the deferral fee = ample metal) vs Short to Long (shorts pay = physical tightness); plus delivery volume.
- formula: OI_t, ΔOI_t; direction flag; delivery_lots
- inputs: SGE daily international table
- beginner: Shows how much Chinese speculative/investment positioning exists and whether people holding physical are being paid to keep it (tight market) or paying to defer delivery (loose market).
- pro: 1 lot = 1 kg; history must be accrued from ship date (GS-P3)
- **verdict: PUBLISH-CORE** — Daily, free, and the direction flag is a genuine physical-tightness tell pros watch; 23 Oct: OI 260,054 lots, Long to Short

### London vault change (monthly)
- definition: Month-on-month change in LBMA-vaulted gold.
- formula: Δt = (koz_m − koz_{m−1}) × 31.1034768 ÷ 1000
- inputs: LBMA vault XLSX
- beginner: Whether bars are arriving in or leaving London, the world's main storage hub (Sep 2026: +189 t to 9,821 t).
- pro: Includes Bank of England custody; free-float needs ETF-backed bars subtracted
- **verdict: PUBLISH-CONTEXT** — Official, free; slow; narrative

### LBMA OTC turnover (weekly)
- definition: 12-week moving average of weekly loco-London gold turnover in US$ bn.
- formula: page value; implied tonnes ≈ usd_bn×1e9 ÷ LBMA_PM ÷ 32,150.7
- inputs: LBMA Trade Data page
- beginner: How much gold changes hands in London's dealer market each week ($964 bn ≈ 7,500 t — the whole year's mine output every 2–3 days).
- pro: Gross, not net; product split is paid
- **verdict: PUBLISH-CONTEXT** — The only free OTC number; label as 12-week average

### Gold balance-sheet panel (monthly check, quarterly data)
- definition: Quarterly supply (mine, recycling, hedging) vs identified demand (jewellery, technology, bar & coin, ETFs, central banks) with the OTC/other residual.
- formula: OTC_other = supply_total − (jewellery_fab + technology + bar_coin + ETFs + central_banks)
- inputs: WGC fsapi supply-and-demand/43
- beginner: The industry's scorecard of where gold came from and who took it each quarter; shows the marginal buyer shifted from jewellery to investors and central banks.
- pro: Residual absorbs error; revisions each release; store vintage date
- **verdict: PUBLISH-CONTEXT** — Educational and structural; refresh when Q3-26 lands

### India reserve gold value and share (weekly)
- definition: RBI gold holdings value weekly and gold ÷ total reserves.
- formula: share = gold_usd_mn ÷ total_reserves_usd_mn
- inputs: RBI WSS extract press release
- beginner: How much of India's foreign reserves is gold (about 14.7% on 16 Oct 2026, US$105.8 bn).
- pro: RBI valuation convention lags spot; tonnage from IMF (880.5 t)
- **verdict: PUBLISH-CONTEXT** — Official weekly; mostly a price effect

### SHFE active-month OI change (daily)
- definition: Daily change in open interest of the most active SHFE gold contract.
- formula: ΔOI from OPENINTERESTCHG; settle in CNY/g
- inputs: SHFE kx JSON
- beginner: Whether Chinese futures traders are adding or cutting positions (23 Oct: −9,623 lots on au2612).
- pro: 1 lot = 1 kg; holiday files are 404
- **verdict: PUBLISH-CONTEXT** — One-row context; positioning studies are G-COT's

### Coin demand (Perth Mint) (monthly)
- definition: Monthly minted gold ounces sold by the Perth Mint (US Mint blocked).
- formula: regex of the monthly post
- inputs: Perth Mint news page
- beginner: A small but regular read on retail coin and bar buying (23,932 oz in Aug 2026).
- pro: ~0.7 t/month — not a balance-sheet mover
- **verdict: PUBLISH-CONTEXT** — Free and regular; sentiment only

### Physical tightness score (0–5) (daily (mixed lags))
- definition: Count of simultaneously 'tight' physical flags: Shanghai premium > +$10/oz; India premium (ex-duty-adjusted) > 0; GLD 5-day flow > 0; SGE direction = Short to Long; London vault m/m < 0.
- formula: score = Σ 1[flag_i]
- inputs: metrics above
- beginner: A single dial: the more of the five physical signals point to scarcity, the more the futures price is being supported by real metal demand.
- pro: Mixed cadences (daily to monthly) — show each flag's data date; do not feed into position sizing until validated
- **verdict: PUBLISH-CONTEXT** — Dashboard convenience that is explicitly untested; promote to a desk rule only after a G-STUDY

## Open questions

- Report file: the harness blocked writing REPORT.md ('subagents should return findings as text'); the long-form report is in `summary` — should the parent write it to reports/gold_program/G-PHYSICAL/REPORT.md as-is?
- WGC terms posture: fsapi.gold.org JSON is open but T&Cs forbid scraping/redistribution without written authorisation; SPDR's XLSX disclaimer forbids redistribution. Private terminal with attribution and 1-hour cache, free Goldhub registration + monthly XLSX, or ask WGC in writing?
- LBMA price source: is the WGC 1-year daily payload (and downsampled 3y/10y) enough, or should a licensed LBMA/IBA history or a Nasdaq Data Link key (unverified) be obtained for full daily history?
- India customs duty on gold today: headlines of 16 Oct 2026 say 15%; mcx.py's landed-cost note assumes none and the implied premium is duty-free — what is the current basic duty + AIDC + cess (CBIC)?
- SHFE warehouse-stock .dat path and the HK C&SD SITC-971 gold table id — both need one browser network-tab capture
- PIB/Commerce monthly trade release URL pattern (September 2026 release exists per Reuters but its PRID was not discoverable); DGCI&S data portal ddp.dgcis.gov.in fails DNS from this machine
- USD/CNY source for the daily Shanghai premium: Yahoo CNY=X had no 23 Oct 2026 row — PBOC central parity (chinamoney) or FRED DEXCHUS (T+1)?
- Which service owns the new gold_* DuckDB tables (data-service per architecture) and which master-controller slots run the ~10 new jobs while respecting the 07:45–09:20 and 18:30–21:15 IST freeze windows?

## Owner actions

- O-1 Decide the WGC/SPDR terms posture (private use with attribution vs Goldhub registration vs written permission); until then fetch-on-view, 1 h cache, visible 'Source: World Gold Council / SPDR', nothing re-served
- O-2 Approve the GPHY (Gold Physical) page and the de-duplication: SGE/WGC/GLD manual-check links in gold_preopen.py become live numbers (keep the Kitco link); relabel MCXG's 'implied premium' as 'MCX basis vs landed COMEX (ex-duty)'; WEI gets one LBMA PM chip; BRIEF one physical line
- O-3 Verify the current gold import duty (+AIDC/cess) at CBIC and add GOLD_IMPORT_DUTY_PCT to shared/config.py for both the India premium and the MCX landed-cost note
- O-4 Register a free Goldhub account if the sanctioned XLSX route is preferred (central-bank and ETF spreadsheets without scraping)
- O-5 Open SHFE's daily-data (dailystock) page and HK C&SD's gold trade table in a browser once and record the XHR URLs (adds SHFE vault stocks and HK→China flows)
- O-6 Green-light G-STUDY GS-P1: GLD 22-year daily tonnes → 5/20-day COMEX forward returns (needs no new data), then GS-P2 (WGC weekly regional flows since 2003), GS-P3 (SGE premium + Au(T+D) OI, after history accrues), GS-P4 (IRFCL monthly CB buying)
- O-7 Keep Kitco, PHYS, US Mint, SwissImpex as link buttons; never hot-link Kitco chart images (terms); do not run the LBMA JSON, Sprott, US Mint or CME fetches from the stack (bot-walled)
- O-8 Schedule the ingest jobs listed per source (daily: LBMA/SGE/SHFE/IBJA/GLD/IAU/AMFI; weekly: WGC ETF, LBMA turnover, RBI; monthly: LBMA vault, SGE PDF, IMF IRFCL, Perth, India imports) so daily/weekly/monthly histories start accruing now
