# G-KITCO — Kitco as the model: what it shows, what it allows, and how SuryaDhana builds its own GOLD page from free data

Agent G-KITCO · SuryaDhana GOLD program · written Monday 26 Oct 2026, 05:40–06:30 IST (Sunday 25 Oct 20:10–21:00 New York).
Everything marked **verified** was fetched live from this Mac during that window; raw responses are in
`reports/gold_program/G-KITCO/scratch/bodies/`, probe logs in `scratch/probe_*.json`, `scratch/retry.log`,
`scratch/yahoo_retry*.log`, the probe code in `scratch/probe.py`, `scratch/retry.py`, `scratch/inspect_bodies.py`.
Nothing in the repo outside `reports/gold_program/G-KITCO/` was touched; no live service was written to (one read-only
`GET /api/mcx/overlay` on :8010, nothing else; no ICICI call).

Sibling briefs: **G-COT** (CFTC positioning in depth), **G-PHYSICAL** (ETF/SGE/IBJA/central banks in depth), **G-LOGIN**
(ICICI auto-login). Where this report touches their ground it verifies only what the visual spec needs and defers the rest.

---

## 0. Verdict in one screen

| Question the owner asked | Answer |
|---|---|
| Can we copy Kitco's charts? | **No — and we should not want to.** Kitco's Terms of Use (3 Jan 2024) forbid robots, data-mining, framing and mirroring; there is no public data API (the page is a Next.js app fed by Kitco's own dealing-desk feed, "Prices provided by Kitco Metals Inc."). The only thing Kitco licenses for free is the old **kitconet.com chart images** (still served, 172×114 px, "free of charge" if the image is a hotlink to kitco.com). Verdict for Kitco data: **LINK-ONLY**; for the kitconet images: allowed with link-back, low value, optional tile. |
| Can we replicate every Kitco visual with free data? | **Yes, all of them, and better in two places** (we add MCX/INR and positioning, which Kitco does not have). Spot proxy = COMEX front future from Yahoo (1-min bars for 7 days, 5-min for 60 days, weekly for 10 years, monthly since 2000 — **verified**); a keyless 24/7 spot cross-check (gold-api.com, **verified**, commercial use permitted by its terms). The LBMA price is **not** free any more (IBA licence; FRED series removed; prices.lbma.org.uk blocked by Cloudflare — all **verified**). stooq (the brief's XAUUSD CSV) is **blocked** by a JavaScript proof-of-work challenge. |
| What does a Bloomberg gold trader look at that Kitco does not show? | Positioning (CFTC COT by category — **verified** free from CFTC's Socrata API), the futures curve (**verified** from six Yahoo contract months), ETF holdings (**verified** SPDR XLSX back to 2004; iShares page), physical premiums (Shanghai **verified** from SGE's daily report; India **verified** from IBJA), real yields and the dollar (**verified** FRED), and the house's own basis: MCX vs landed COMEX (already in the app). |
| Separate page? | Yes: a new **GOLD** page (GO bar code `GOLD`), nine sub-views (HEALTH · DAILY · WEEKLY · MONTHLY · POSITIONING · PHYSICAL · MACRO · CONTRACTS · LEARN). CMDT keeps only the pre-open fair-open desk; MCXG keeps the broker quote, specs and paper ticket; WEI keeps one row; BRF keeps one line. The de-duplication map is §5.11. |
| Is any of it predictive? | Honestly: **almost none of it is a timing signal.** Real yields and the dollar explain moves contemporaneously; COT, ETF flows and premiums are context with weak, unstable lead; seasonality is weak. The page's value is **understanding and risk control** (what moved, who holds, what the roll costs, what the India premium is doing), not prediction. Each metric carries its verdict in §6; three G-STUDYs are proposed in §8. |
| Biggest operational finding | **Yahoo rate-limits this IP**: after ~25 chart requests in one minute Yahoo answered `429 Too Many Requests` on both `query1` and `query2` and was **still refusing at 06:04 IST, 16+ minutes later** (observed, `scratch/yahoo_retry2.log`). The GOLD page must share the existing `gold_preopen` stale-while-revalidate cache and add **no new per-minute Yahoo pollers**; history must be stored once in DuckDB (§7), never re-fetched per view. Owner: watch today's 08:45 snapshot (it needs fresh Yahoo series; see §8 item 8). |

---

## 1. What Kitco shows, and how (verified 26 Oct 2026 05:42 IST = 25 Oct 20:12 NY)

### 1.1 The page the owner cited: https://www.kitco.com/charts/gold

HTTP 200 in 1.44 s, 119 KB, `text/html`. A Next.js pages-router app (`__NEXT_DATA__` present). The legacy URLs
`/charts/livegold.html`, `/charts/historicalgold.html` and `/price/precious-metals/gold` all **301 → /charts/gold** (verified).
`/kitco-gold-index` is **404** (moved to `/markets/kitco-gold-index`, verified 200).

What the page displays, literally as served:

| Block | Content (as served at 20:11 NY) | How Kitco gets it |
|---|---|---|
| **Live price strip** | "Live Gold Price Oct 25, 2026 - 20:11 NY Time · **Bid 3,987.20 −7.70 (−0.19%) · Ask 3,989.20**" | Kitco's own dealer feed. No delay statement anywhere on the page. |
| **Units table** | ounce 3,987.20 · gram 128.19 · kilo 128,193.42 · pennyweight 199.36 · tola 1,495.20 · tael 4,845.56 (each with its $ change) | bid ÷ 31.1034768 g/oz; tola 11.6638 g; HK tael 37.799 g (the page says so) |
| **Day's range** | 3,984.70 – 4,004.80 | their feed |
| **Purity table** | "Gold Value by Purity at spot bid": 24K 99.99% $3,987.20 · 22K 91.67% $3,655.07 · 18K 75% $2,990.40 · 14K · 10K | bid × purity |
| **Charts** | 24-hour New York chart (`charts.kitco.com/images/live/gold_ny_hours_usd.webp`), 3-day chart (`gold_3day_usd.webp`), legacy small GIFs 30d/60d (London) and 6m/1y/5y/10y (NY): `www.kitco.com/chart-images/LFgif/AU0030lnb.gif`, `AU0060lnb`, `AU0182nyb`, `AU0365nyb`, `AU1825nyb`, `AU3650nyb` | server-rendered images regenerated every minute (`?t=` cache-buster) |
| **Historical chart selector** | month Jan–Dec × year 2000–2026 | their archive |
| **"Gold Price Historical Performance" widget** | Time / Change / Change% for 3 Days · 7 Days · 30 Days · 60 Days · 6 Months · 1 Year · 5 Years · 10 Years · 15 Years; currency USD CAD EUR GBP JPY CHF AUD CNY INR MXN BRL ZAR RUB; unit OZ / Kilo / Gram / Tola. "Want this widget on your site? Get the widget" → `widgets.kitco.com/#/widgets/precious_metals_performance` | computed from daily closes |
| **Gold in currencies** | the dehydrated state carries, per currency, `{timestamp, bid, ask, mid, change, changePercentage, ctousd, usdtoc}` for AUD BRL GBP CAD CNY EUR HKD INR JPY MXN ZAR … (e.g. GBP mid 0.74795, CNY mid 6.67485, EUR mid 0.89195 at 1792973460) | **USD spot × FX mid, computed client-side** — exactly what we will do |
| **Gold/silver ratio** | "The gold-silver ratio — the gold price divided by the silver price — is currently **74.1**" | spot gold ÷ spot silver |
| **KGX blurb** | "the Kitco Global Index (KGX) tracks gold's value measured against a basket of major currencies with the U.S. dollar's influence stripped out." | §1.3 |
| **Explainer prose** | "it moves nearly around the clock as trading follows the sun from New York to London, Zurich, Shanghai and Hong Kong", troy ounce definition, drivers, central-bank buying | editorial |
| **Nav to related pages** | `/charts/{silver,platinum,palladium,rhodium}`, `/price/fixes/kitco-fix`, `/price/fixes/shanghai-benchmark`, `/price/precious-metals/text-quotes`, `/price?Symbol=INR` … | — |

### 1.2 The three chart images, as actually rendered (converted and viewed)

**(a) 24-hour New York chart** (`gold_ny_hours_usd.webp`, 1260×730, served in 88 ms): title "New York Spot Gold (Bid)",
subtitle "October 25, 2026 20:18 New York Time". Legend of **three rows: "Oct 22 Close 4023.30 ▼ −117.00 (−2.83%)",
"Oct 23 Close 3994.90 ▼ −28.20 (−0.70%)", "Oct 25 Last 3993.50 ▼ −1.40 (−0.04%)"** — two previous NY closes plus the live
print. A dashed horizontal **"Last Close 3994.90"** reference line; "New York - High: 4002.40 Low: 3983.70". x-axis **08:00 →
17:00 NY Time only**, y in USD/oz with a tight auto-range (3980–4005), dark grid. On a Sunday evening the line is empty: just
the live marker. (The compact `gold_24h_compact_usd_light.png` on the home page is the 00:00–23:59 version with a dashed
"3995" previous-close line and the line coloured green above / red below it.)

**(b) 3-day chart** (`gold_3day_usd.webp`, 1260×730): title "Gold Spot (Bid) 3 Day", x-axis **00:00 → 23:59 NY time with a
second GMT row** beneath. **Three days overlaid on one 24-hour axis**, one colour each (Oct 22 cyan, Oct 23 red, Oct 25
green), legend with each day's close and change; "3 Day - High: 4145.30 Low: 3975.10". **Session bands at the bottom:
SHANGHAI (≈00:00–04:00 NY), LONDON (03:00–12:00), NEW YORK (08:00–17:00), SHANGHAI again (20:00–24:00), SYDNEY (19:00–24:00)**
with the New York hours shaded on the chart body. Today's image says *Shanghai*, not *Hong Kong*. A flat segment ≈17:00–18:00
NY: the COMEX/OTC maintenance hour.

**(c) 30-day London chart** (`AU0030lnb.gif`, 450×275, 8 KB, legacy): "30 Day Gold · High 4290.75 Low 3994.90", **three
series: NY Close (red line), London AM fix (blue squares), London PM fix (pink diamonds)**, dates 25 Sep → 23 Oct, "USD per
ounce". `lnb` = London fixes + NY bid close; `nyb` (6m/1y/5y/10y) = NY bid close only.

Kitco's periods are therefore: live 24 h (NY hours or full day), 3 days overlaid, 30/60 days with fixes, 6 m / 1 y / 5 y /
10 y closes, the monthly archive back to 2000, and the performance widget back 15 years. **All reproducible from free
data; the only Kitco-specific ingredient is their own bid/ask feed.**

### 1.3 KGX — the Kitco Gold Index (`/markets/kitco-gold-index`, verified 200)

- Definition (page text): gold valued in the **US Dollar Index basket instead of USD**: "Euro (57.6%), Japanese Yen (13.6%),
  British Pound (11.9%), Canadian Dollar (9.1%), Swedish Krona (4.2%), and Swiss Franc (3.6%)"; it "removes the US dollar
  component". Display per metal: **Last (Bid)**, **"Change due to Weakening of USD"**, **"Change due to Predominant Buyers"**
  (normal trading), **Total change**; periods Real Time · 30D · 60D · 6M · 1Y · 5Y · 10Y; "Oct 25, 2026, 20:12 NY Time". No
  disclaimer, no data-source statement beyond the timestamp.
- Formula (pro definition): with gold in USD `G` and the DXY-basket value of one dollar `B = Π FX_i^{w_i}` (geometric, as the
  ICE DXY), `KGX = G × B / B_0` (gold priced in the basket, rebased). Over a period `ΔG_total = ΔG_usd + ΔG_trading`, where
  `ΔG_usd = G_1 × (1 − B_1/B_0)` (what the USD price would have done had gold been flat in the basket while the dollar moved)
  and `ΔG_trading = ΔG_total − ΔG_usd`.
- Beginner translation: *"gold rose $20 today; $12 of that is just the dollar falling, $8 is people actually bidding for gold."*
- Pitfalls: the DXY is 57.6% euro, so KGX is largely gold-in-euros; it says nothing about **rupee** gold — for an MCX trader
  the same arithmetic must be done against USD/INR, which the app's gap waterfall already does for the overnight gap (COMEX
  part vs rupee part). Generalised in §5.7 ("WHAT MOVED": dollar / rupee / real-yield / residual).

### 1.4 Does Kitco expose data? Terms and the embeddable images

- **Terms of Use** (https://www.kitco.com/terms-of-use, 200, "January 3, 2024"), verbatim: *"'Frame' or 'mirror' any content
  available through the Websites or the Services without our prior written authorization"*; *"Use any robot, spider, site
  search/retrieval application, or other manual or automatic device or process to download, retrieve, index, 'data mine', or
  in any way reproduce or circumvent the navigational structure"*; plus the general *"copying, reproduce, republish, store,
  retransmit, alter, modify, distribute …"* clause. `robots.txt` says `Allow: /` — crawling is technically permitted, but the
  ToU forbids data-mining; a 60-second scraper of the `__NEXT_DATA__` state would breach it. **Verdict: LINK-ONLY.** No data
  licensing contact appears in the ToU.
- **The old "Free Charts on Your Website" service still exists at kitconet.com** (`main.html`, `menu.html`, `price/`,
  `webcharts/au_en_us.html`, `webcharts/au_en_inr.html` all 200). Its condition, verbatim: *"Display the latest precious
  metals quote or exchange rate charts on your website 24 hours a day, free of charge. … To take advantage of this no-charge
  service you must make the image a hotlink to www.kitco.com. … as long as the link to 'connecting.html' remains. … If there
  is no link back to www.kitco.com charges will apply."* (page carries a 2007 maintainer comment). Images live today:
  - `http://www.kitconet.com/charts/metals/gold/t24_au_en_usoz_2.gif` — 24-hour gold USD/oz, **172×114 px, 1.8 KB, 200**
    (viewed: tiny red line, "3989.30 ▼ −5.70", "Oct 25, 2026 20:21 NY Time", kitco.com watermark);
  - `tny_au_en_usoz_2.gif` (NY session), `t24_au_en_uskg_2/4.gif` (per kg), `_4` = larger, `au_xx_` = language-neutral;
  - **INR versions**: `t24_au_en_inoz_2.gif`, `t24_au_en_ingr_2.gif`, `tny_au_en_inoz_2.gif`, `tny_au_en_ingr_2.gif` (all 200).
  - The larger live images the site uses (`charts.kitco.com/images/live/gold_ny_hours_usd.webp`, `gold_3day_usd.webp`,
    `gold_24h_compact_usd_light.png`) and the LFgif series are **not** on the kitconet licence list; hot-linking them = "mirroring".
  - Legacy `www.kitco.com/images/live/gold.gif`, `nygold.gif`, `t24_au_en_usoz_2.gif` → **502** (dead).
  - `www.kitco.com/connecting.html` now 301s to the home page (the condition is still satisfiable).
  **Verdict:** allowed with link-back, but **low value**: unreadable in the terminal, HTTP-only, and the only panel whose
  data we could not verify. Offer as an optional "Kitco mini" tile in LEARN, off by default.
- **widgets.kitco.com** is a JS app; terms not visible to a non-JS fetch (**UNVERIFIED**). Not used.
- Kitco RSS `/rss/` → 404. Headlines keep coming from Google News RSS (already in the app), which indexes Kitco News.

---

## 2. Free data that replicates each Kitco visual — live verification

Every row was fetched from this machine with a browser-like User-Agent (FRED with a plain one, as the app does) and ≥1.2 s
between requests. "Latest" = the last date/time carried. Latency = one cold request.

### 2.1 Spot and futures prices

| # | Source | Access | Verified (status · latency · sample · latest) | Freq / lag | Verdict |
|---|---|---|---|---|---|
| S1 | **Yahoo chart API `GC=F`** (COMEX gold front future, continuous) `https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=…&interval=…` | FREE, no key | `1d/5m`: 200 · 305 ms · `exchangeName=CMX, currency=USD, regularMarketPrice=4003.4, previousClose=4007.9, regularMarketTime=26 Oct 05:32 IST, dayHigh 4017.9, dayLow 4002.7, 52w 5586.2/3901.3`, 24 bars from 03:40 IST (Sunday 18:10 ET open). `7d/1m`: 200 · 379 ms · **8,748 timestamps, 6,998 non-null closes, 19 Oct 03:40 → 26 Oct 05:32 IST**. `60d/5m`: 200 · 313 ms · 17,016 bars (13,459 non-null), 17 Aug → 26 Oct. `10y/1wk`: 523 weekly bars. `max/1d`: Yahoo **silently coarsens to monthly** (`dataGranularity=1mo`, 269 bars, first Sep 2000, `chartPreviousClose 273.9`) — daily history must use `period1/period2` (**UNVERIFIED today**: 429, §9). `validRanges`: 1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max. | ≈1 min delayed; 1-min kept 7 d, 5-min 60 d | **PUBLISH-CORE** (24-h, 3-day, intraday and history charts; already the app's price feed) |
| S2 | **Yahoo `XAUUSD=X`** (spot) | — | **404** `"No data found, symbol may be delisted"` (`5d/5m`, `max/1d`); `XAU=X` and `PAXG-USD` answered 429 (UNVERIFIED) | — | not available |
| S3 | **Yahoo contract months `GCZ26.CMX, GCG27, GCJ27, GCM27, GCQ27, GCZ27`** | FREE | all 200 · 111–121 ms · last **4002.9 (Dec-26), 4044.0 (Feb-27), 4081.2 (Apr), 4115.0 (Jun), 4142.6 (Aug, last print 23 Oct), 4209.0 (Dec-27, last print 23 Oct)**; Feb-27 had 139 contracts of 5-min volume vs 4,422 for Dec-26 | as S1; back months print sparsely | **PUBLISH-CORE** (term structure, roll yield, which contract) |
| S4 | **Yahoo `SI=F`** (silver) | FREE | 200 · 114 ms · 53.88 (prev 53.949) → **gold/silver 74.3** (Kitco spot-based 74.1) | as S1 | PUBLISH-CONTEXT (ratio line only) |
| S5 | **Yahoo `GLD`, `GOLDBEES.NS`** | FREE | `GLD 1mo/1d`: 200 · 366.61 at 23 Oct close, 52w 509.7/360.12. `GOLDBEES.NS 1mo/1d`: 200 · ₹115.96 at 23 Oct 15:30 IST, NSI/INR | daily | PUBLISH-CONTEXT (GOLDBEES = the free **INR gold proxy with history**; GLD for ETF premium/discount) |
| S6 | **gold-api.com `https://api.gold-api.com/price/XAU`** | FREE, no key | 200 · 637 ms · `{"currency":"USD","price":3991.600098,"symbol":"XAU","updatedAt":"2026-10-26T00:13:42Z","updatedAtReadable":"a few seconds ago"}`. Terms (10 Sep 2026): "The API is free to use, 24/7", "No Rate Limiting for real time prices", *"Commercial use of the API is always permitted, including use in web applications, mobile apps, and third-party websites"*, no accuracy guarantee, IP ban for "multiple requests per second". Provider unnamed ("fallback to the next source"). | real-time-ish, 24/7 (printed Sunday evening) | **PUBLISH-CONTEXT as the 24/7 spot cross-check chip** (not the charted series) |
| S7 | **Swissquote public quotes `forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD`** | FREE, undocumented | 200 · 1.13 s · bid/ask per spread profile, e.g. `elite bid 3990.523 ask 3991.027`, `ts 1792973631613` | real-time broker quote | PUBLISH-CONTEXT (spread sanity only) — terms **UNVERIFIED**; never the displayed price |
| S8 | **stooq.com daily CSV `https://stooq.com/q/d/l/?s=xauusd&i=d`** (the brief's XAUUSD source) | — | 200 but the body is a **JavaScript proof-of-work challenge** ("This site requires JavaScript to verify your browser … crypto.subtle.digest … POST /__verify") with browser *and* curl UAs; `i=5`, `gc.f` same; quote endpoint `q/l/` 404 | — | **BLOCKED** for scripts (26 Oct 2026) |
| S9 | **goldprice.org `data-asg.goldprice.org/dbXRates/USD`** | — | 403 plain; **200 only with a spoofed `Referer: https://goldprice.org/`** → `{"date":"Oct 25th 2026, 08:18:45 pm NY","items":[{"curr":"USD","xauPrice":3994.92,"xagPrice":54.1281,"chgXau":1.25,"pcXau":0.0313,"xauClose":3993.67,…}]}`; their widget (`charts.goldprice.org/gold-price.js`) requires a link-back and the site's main chart is a TradingView embed | ~10 s | **DO-NOT-PUBLISH** (works only by misrepresenting the client) |
| S10 | **BullionVault `view_market_json.do`** | FREE, undocumented | 200 · 520 ms · 16 KB order board: GOLD/USD best buy 128,190 $/kg (= 3,987.15/oz), best sell 128,380 (= 3,993.06/oz) | live | LINK-ONLY (their exchange's order book, not spot; LEARN uses their spot/daily/order-board explanation) |
| S11 | **tradingeconomics.com/commodity/gold** | page free; API PAID | 200 · 647 ms; headline "3,983.30"; *"according to trading on a contract for difference (CFD) that tracks the benchmark market"*; model forecasts | — | LINK-ONLY (CFD price, model forecasts) |
| S12 | **investing.com XAU/USD** | — | **403** | — | BLOCKED |

### 2.2 Benchmarks and fixes

| # | Source | Access | Verified | Freq / lag | Verdict |
|---|---|---|---|---|---|
| B1 | **LBMA Gold Price JSON `prices.lbma.org.uk/json/gold_am.json`, `gold_pm.json`, `silver.json`** | — | **403 Cloudflare "Sorry, you have been blocked"** with browser, plain and curl UAs | — | **BLOCKED**. `lbma.org.uk/prices-and-data/lbma-precious-metal-prices` (200) says the tables *"have moved to the MyLBMA Portal"* and *"A licence from IBA is required in order to obtain, use or redistribute real-time or historical benchmark data"*. **LINK-ONLY**. |
| B2 | **FRED `GOLDAMGBD228NLBM` / `GOLDPMGBD228NLBM`** | — | **404** "Error - St. Louis Fed" | — | removed (SPDR's XLSX: "The LBMA Gold Price has been removed at the request of the ICE Benchmark Administration"). Does not exist. |
| B3 | **Kitco Fix page** (`/price/fixes/kitco-fix`) | Kitco ToU | same site/ToU | — | LINK-ONLY |
| B4 | **Shanghai Gold Benchmark (SHAU) `en.sge.com.cn/data_BenchmarkPrice`** | FREE page | 200 · 1.03 s; table **rendered by JavaScript** (no rows in HTML); "Contract: SHAU" | daily AM/PM | LINK-ONLY; use B5 for the number |
| B5 | **SGE daily report (URL observed in SGE's own page) `https://en.sge.com.cn/data/data_daily_international_new?start_date=2026-10-23&end_date=2026-10-23`** | FREE, no key | 200 · 373 ms · 90 KB HTML table, rows per contract: **`2026-10-23 Au99.99 open 874.50 high 883.98 low 856.01 close 864.00 chg −16.3 (−1.85%) VWAP 863.44 volume 13,963.7 kg turnover ¥12.06 bn`**; also Au99.95 (854.00), Au100g (865.54), iAu99.99 (862.33), Au(T+D) rows; delayed-quotes page shows zeros while closed | daily after the 15:30 Beijing close (13:00 IST) | **PUBLISH-CORE for the Shanghai premium** (CNY/g → $/oz via USD/CNY). G-PHYSICAL owns the deep dive. |
| B6 | **IBJA `https://ibjarates.com/`** | FREE page | 200 · 485 ms · 156 KB; headline **"999 Purity 14163 (1 Gram)"**, 995 14,106, 916 12,973, 750 10,622, 585 8,285; "AM / PM — Rates will be uploaded soon" (05:43 IST Monday); a **"Previous 30 Days" table is in the HTML**: `23/10/2026 999 141,448 · 995 140,882`, `22/10 143,152`, `21/10 144,060`, `19/10 146,406` (₹/10 g, "without 3% GST and making charges"). Advertises a paid "INDIA GOLD AND SILVER METAL RATES API"; `/terms` 404 | twice daily (AM ≈12:00, PM ≈17:00 IST) | **PUBLISH-CORE for the India premium** (also the SGB/RBI reference rate). Terms **UNVERIFIED** → parse for display, store our own derived premium, never re-serve their table. |

### 2.3 Macro — FRED (`fredgraph.csv`, plain UA; browser UAs stall as `gold_preopen.py` notes)

| Series | Verified (latest row) | Lag | Verdict |
|---|---|---|---|
| `DFII10` 10-y TIPS real yield | 200 · 59 ms · `2026-10-22, 2.64` (10-21 2.76, 10-20 2.77) | 1 business day | PUBLISH-CORE (already in the pre-open desk; Treasury CSV same-day fallback exists) |
| `T10YIE` 10-y breakeven | 200 · 80 ms · `2026-10-23, 2.34` | 1 day | PUBLISH-CONTEXT |
| `DGS10`, `DGS2` | 200 · `2026-10-22, 4.96` / `4.65` | 1 day | PUBLISH-CONTEXT (2s10s, real-yield build-up) |
| `DTWEXBGS` broad dollar | 200 · `2026-10-16, 121.40` | **~1 week** | PUBLISH-CONTEXT (live dollar = DXY `DX-Y.NYB`, already in the app) |
| `DEXINUS` USD/INR (H.10) | 200 · `2026-10-16, 94.96` | ~1 week | LINK-ONLY (Yahoo `INR=X` live; FBIL reference) |
| `DCOILBRENTEU` Brent | 200 · `2026-10-20, 115.22` | 3–4 days | PUBLISH-CONTEXT (live Brent is in WEI) |
| US Treasury real-yield CSV | already in the app (`_treasury_real_10y`, ~20 s site) | same day | keep |

### 2.4 Positioning (who is long, who is short)

| # | Source | Verified | Freq / lag | Verdict |
|---|---|---|---|---|
| P1 | **CFTC Socrata, Disaggregated futures-only `https://publicreporting.cftc.gov/resource/72hh-3qpy.json?cftc_contract_market_code=088691&$order=report_date_as_yyyy_mm_dd DESC&$limit=2`** | 200 · 1.2 s · 194 fields/row; **report 2026-10-20 (Tue), released Fri 23 Oct**: `GOLD - COMMODITY EXCHANGE INC.` open interest **402,279 (+5,934 w/w)**; Producer/Merchant long 19,715 short 34,498; **Swap dealers long 17,737 short 238,536**; **Managed Money long 120,970 short 16,764 (net +104,206; prior week +107,089)**; Other reportables long 116,172 short 20,513; Non-reportable long 51,407 short 15,690; 288 traders | weekly: Tuesday positions, Friday 15:30 ET release (Sat 01:00 IST) → 3-day lag; **no daily COT exists** | **PUBLISH-CORE** (stacked-bar and net-vs-price charts). G-COT owns legacy/combined variants and the study. |
| P2 | **CFTC legacy short format `cftc.gov/dea/futures/deacmesf.htm`** | 200 · 245 ms · 68 KB (not parsed here) | weekly | G-COT |
| P3 | **CME daily volume/OI, settlements, FedWatch** (`cmegroup.com/CmeWS/mvc/…`, `…/gold.settlements.html`) | **403** on all three (602-byte JSON refusal) | daily | **BLOCKED** → LINK-ONLY |
| P4 | **MCX open interest per expiry via ICICI's public `MCXScripMaster.txt`** (already parsed by the app; master published 23 Oct) | from the cached file: GOLD Dec-26 settle ₹146,079 **OI 16,650 lots**; Feb-27 ₹148,589 / 749; Apr-27 ₹150,972 / 42; Jun-27 ₹153,601 / 4; GOLDM Nov-26 ₹144,584 / **48,437**; Dec-26 ₹146,081 / 22,922; Jan-27 / 4,752; GOLDGUINEA Oct-30 ₹116,648 / 12,009; Nov-30 / 10,169 … | daily ~07:00 IST (T−1 settlement + OI) | **PUBLISH-CORE** (the only free *daily* positioning number for MCX gold: OI by contract and its day-to-day change = positions opened/closed) |
| P5 | **MCX bhavcopy** `mcxindia.com/market-data/bhavcopy` | **403** | daily | BLOCKED (known; ICICI master substitutes) |

### 2.5 Physical / investment demand

| # | Source | Verified | Freq / lag | Terms | Verdict |
|---|---|---|---|---|---|
| H1 | **SPDR GLD historical archive XLSX** `https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en` (URL observed on the site's historical-data page) | 200 · 468 ms · 542 KB; sheet "US GLD Historical Archive" **5,721 rows, 18-Nov-2004 → 22-Oct-2026**; columns `Date, Closing Price, Ounces of Gold per Share, NAV/Share at 10:30am NYT, Indicative Price 4:15pm, Mid point bid/ask 4:15pm, Premium/Discount, Daily Share Volume, Total Ounces of Gold in the Trust, Tonnes of Gold, Total Net Asset Value`; latest **22-Oct-2026: tonnes 1,045.64 (−11.98 t d/d), NAV $136.06 bn; 21 Oct 1,057.62; 20 Oct 1,060.18** | daily (site: updated 10:30–10:45 and 16:00–16:45 NY) | file disclaimer: *"Reproduction or redistribution of any of this information is expressly prohibited without prior written consent"* | **PUBLISH-CONTEXT** (plot tonnes and Δ on the owner's private terminal; store the derived series, never re-serve the file) |
| H2 | **SPDR "archive CSV" `spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv`** | 200 but **302 → `api.spdrgoldshares.com/api/v1/barlist?underlying=gld`, a 697 KB PDF** (the bar list) | — | — | old CSV path gone; use H1 |
| H3 | **iShares IAU product page** | 200 · 1.76 s · 1.6 MB HTML; **"Tonnes in Trust 463.05 as of Oct 23, 2026", "Ounces in Trust 14,887,293.30", Net Assets $59,737,420,617, NAV 75.42**; no CSV/ajax link found in the HTML | daily | page scrape | PUBLISH-CONTEXT (G-PHYSICAL) |
| H4 | **WGC Goldhub — ETF holdings & flows** `gold.org/goldhub/data/gold-etfs-holdings-and-flows` | 200 · 316 ms; **monthly XLSX "Gold ETF Flows: September 2026"** behind an "I agree to the terms and conditions" modal; *"Flows and holdings data are updated on the website weekly and monthly. Downloadable data in excel is available on a monthly basis"*; licence `gold.org/terms-and-conditions#proprietary-rights` | monthly file; weekly web | T&C click | LINK-ONLY (manual-check row, already in the desk) |
| H5 | **WGC Goldhub — gold prices** `gold.org/goldhub/data/gold-prices` | 200 · 488 ms; XLSX **"Gold price averages in a range of currencies since 1978"** (`gold.org/download/file/8369/…xlsx`, T&C modal); the live spot block calls `https://fsapi.gold.org/api/goldprice/v13/charts/spotprice` which answered **429** (HTML) to a script | monthly averages | WGC T&C | LINK-ONLY; fsapi **UNVERIFIED/BLOCKED** |
| H6 | **CME COMEX warehouse stocks** | same host as P3 → **BLOCKED** | daily | — | LINK-ONLY (G-PHYSICAL) |

### 2.6 Kitco-side images

| Image | Verified | Terms | Verdict |
|---|---|---|---|
| `kitconet.com/charts/metals/gold/t24_au_en_usoz_2.gif` (+ `inoz`, `ingr`, `tny_*`) | 200, 172×114, 1.8 KB, per-minute | free with hotlink to kitco.com | optional LEARN tile, off by default |
| `charts.kitco.com/images/live/gold_ny_hours_usd.webp`, `gold_3day_usd.webp`, `gold_24h_compact_usd_light.png`, `kitco.com/chart-images/LFgif/AU0030lnb.gif` … | all 200 (88–502 ms) | **not** in the kitconet licence; ToU forbids mirroring | DO-NOT-PUBLISH (design reference only) |

### 2.7 Bloomberg / Eikon

No terminal access from this machine → **UNVERIFIED** (public guides only; §3, Appendix C).

---

## 3. How the professionals lay gold out — what to steal, what to avoid

**Bloomberg** (public university Bloomberg guides — JHU, U. Delaware, U. Ljubljana — and the BBGsymbols CFTC-ticker
reference; **UNVERIFIED on a terminal**): tickers `XAU Curncy` = spot gold as a currency pair (`GOLDS Comdty` resolves to
Gold Spot $/oz), `GC1 Comdty` = generic front COMEX future, `GCZ6 Comdty` a dated contract, `GCA Comdty` active contract.
Desk habits: **DES** (contract specs, tick, margin, first notice), **GP/GIP** (price / intraday graph), **CT** (contract
table — every listed month with last, change, volume, open interest = the term structure in one grid), **CCRV/FWCV**
(forward curve today vs 1 week / 1 month ago), **HP** (history table), **GLCO** (global commodity prices), **ECO**, and
CFTC data as its own tickers (BBGsymbols documents the suffixes: Disaggregated `PML/PMS` producer-merchant, `SWL/SWS` swap
dealers, `MML/MMS` managed money, `…N` = net; TFF via `ALLX TFF1 <GO>`). "WGC <GO>" could not be confirmed from public
material (**UNVERIFIED**); WGC indices are distributed through vendors (Cbonds lists "Gold (WGC, USD)").
Steal: **one grid per contract chain (CT)**, **curve today vs a week ago (CCRV)**, **DES-style spec card on every
instrument**, **every number carries source and timestamp**. Avoid: assuming the reader knows the mnemonics — our tooltips
carry the definition.

**LSEG Workspace / Eikon** (Refinitiv developer-community pages found by search): RICs `XAU=` spot gold, `XAG=`, `XPT=`;
instrument-centred commodities app with price/chart/news/events side by side. Same lesson.

**CME's free Commitment of Traders tool** (page timed out at 60 s; description from the search index: *"a comprehensive and
highly configurable graphical representation of the CFTC's report … Physical Commodities (Producer, Swap Dealer, Managed
Money and Other Reportable)"*): the standard visual is **net position by category as stacked bars with the price line on a
second axis** — adopted in §5.5.

**Free dashboards** (all verified 200):
- *goldprice.org*: strengths — currency and unit selectors on the headline, per-gram/kilo pages, 43 years of history;
  weaknesses — the main chart is a **TradingView embed** (not their data), crypto clutter, the refresh note hidden in a
  calculator; their API refuses non-browser callers (S9). Steal: unit/currency toggles on the headline. Avoid: embedding
  someone else's chart as the main chart.
- *BullionVault*: strengths — the clearest explanation of **spot (professional mid) vs the daily LBMA price vs their order
  board**, periods 10 minutes → 20 years, "live gold price data processed about every 10 seconds"; weaknesses — no
  gold/silver ratio; three prices confuse a newcomer. Steal: the three-price explanation for LEARN.
- *Trading Economics*: strengths — the one-paragraph narrative ("Gold rose to … on … as …"), related-commodities table,
  52-week/YTD stats; weaknesses — price is a **CFD**, forecasts are a model's, data/API paid. Steal: the narrative line (the
  app already generates verdict sentences). Avoid: CFD prices and model forecasts.
- *Kitco*: strengths — the **3-day overlay with session bands**, the **two-previous-closes legend**, the **"Last Close"
  reference line**, **bid and ask both shown**, units/purity tables, KGX; weaknesses — NY-centric clock (no IST), no
  positioning, no curve, no India.

---

## 4. Design principles for the GOLD page (binding for the build)

1. **Terminal kit only**: `PageHeader`, `Panel`, `Stat`, `DataTable`, `Chip`, `Notice`, `Tabs`, `Spark`, `KV`, `Markdown`,
   `useChartSize` + `axisTicks` from `ui/components/terminal`; `T` tokens (`bg #05070a`, `panel #0a0d13`, `amber #ffb000`,
   `green #16d98a`, `red #ff4d5e`, `cyan #39c6ff`, `violet #b58bff`; JetBrains Mono data, Chakra Petch display).
   Candles/OHLC through the vendored `lightweight-charts 4.2.3` (as `ChartStudio.tsx`), everything else inline SVG in CSS px.
2. **Every number: value · source · as-of · lag chip** (`SourceChip`: LIVE Breeze / DELAYED Yahoo / STALE / OFFLINE). Daily
   data shows its date, not a clock.
3. **Hover = definition.** Every label has a `title` with the one-line LEARN definition; a term's first appearance in a view
   gets a dotted underline.
4. **Degrade-honest**: a panel whose source is blocked/429 shows the last stored value with a STALE chip and the reason —
   never blank, never fabricated (the `errors.degraded` envelope MCXG already uses).
5. **Density like MKT/DERV**: 11–12 px data, 9.5 px labels, 1-px rules, no rounded cards, 12-column grid, charts 220–320 px
   tall, two charts side by side at ≥1,280 px.
6. **IST first, NY second** on every intraday axis (Kitco shows NY+GMT; we show IST+NY).
7. **No new Yahoo pollers.** Live values come from the existing `gold_preopen` cache (30 s TTL, stale-while-revalidate to
   120 s, single flight). History comes from DuckDB. Budget: today's ≤6 chart calls/min across the app + the 5-minute bar job.
8. **Repetition is a defect**: the de-duplication map (§5.11) is part of the acceptance test.

Page frame (GO bar code **GOLD**, tab id `gold`, label "Gold terminal", hint "spot, MCX, positioning, physical, macro, contracts"):

```
┌ GOLD  GOLD TERMINAL   spot $4,003.4 ▼0.11% · MCX GOLD DEC ₹1,46,079 (settle 22 Oct) · fair ₹1,44,181 · INR 94.93 · ◷ MCX opens in 3h04m   [DELAYED·YAHOO] ┐
│ HEALTH │ DAILY │ WEEKLY │ MONTHLY │ POSITIONING │ PHYSICAL │ MACRO │ CONTRACTS │ LEARN │                        contract: [GOLD DEC-26 ▾]  unit: [$/oz ▾] │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
The header strip is the only place the live spot/MCX/fair/INR numbers appear on this page; sub-views never repeat them.
The contract picker (GOLD/GOLDM/GOLDPETAL/GOLDGUINEA × expiry, default front-by-OI as MCXG does) and the unit picker
($/oz · ₹/10 g · ₹/g · $/g · tola) are page-global.

---

## 5. The sub-views — layout, charts, data, definitions

### 5.1 HEALTH — "is gold healthy right now?" (the owner's health check)

Purpose: one screen a newcomer reads in 30 seconds and a pro can audit. Eight gauges (`Stat` + 60-day `Spark` + a plain
state) and a **descriptive, not predictive** verdict line (house rule: no implied forecast without a study).

```
┌ VERDICT ────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ▼ WEAK WEEK, DOLLAR-DRIVEN · gold −2.8% Thu was the dollar and real yields, not futures selling          │
│   (managed money net −2.7% w/w) · India premium 18.0% over landed · roll into FEB costs 1.03% (3.2%/yr)  │
│   · GLD −12 t on the day.                                                      describes · does not predict│
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ TREND ───────────┐┌ REAL YIELD ──────┐┌ DOLLAR ──────────┐┌ POSITIONING ─────┐
│ $4,003  −0.11%    ││ 2.64% ▼ 12bp     ││ DXY  ▲           ││ MM net +104k ▼2.7%│
│ ▁▂▃▅▇▆▅▃▂▁ 60d    ││ ▁▂▂▃▅▆▇▇▆▅ 60d   ││ ▃▃▄▅▅▆▆▇▇█ 60d    ││ ▇▇▆▆▅▅▅▄▄▄ 26w   │
│ 52w −28% from high││ falling = GOOD   ││ rising = BAD     ││ pct of 3y: n/a yet│
│ below 20d / 200d  ││ for gold         ││ for gold         ││ "long, not crowded"│
└──────────────────┘└──────────────────┘└──────────────────┘└──────────────────┘
┌ INDIA PREMIUM ───┐┌ SHANGHAI PREM ───┐┌ ETF HOLDINGS ────┐┌ CURVE / ROLL ────┐
│ +18.0% implied   ││ Au99.99 ¥864/g   ││ GLD 1,045.6 t     ││ contango 1.03%    │
│ ▅▅▆▆▆▇▇▇▇█ 90d   ││ ▂▃▃▄▅▅▆▇▆▅ 60d   ││ ▇▇▇▇▇▆▆▆▅▅ 60d    ││ ▃▃▃▃▄▄▄▄▄▄ 60d    │
│ IBJA 999 1,41,448││ premium vs spot  ││ −12.0 t d/d       ││ DEC→FEB +$41.1    │
│ landed 1,22,171  ││ at 13:00 IST     ││ (outflow)         ││ 3.2%/yr annualised│
└──────────────────┘└──────────────────┘└──────────────────┘└──────────────────┘
┌ WHAT MOVED (since Thu MCX close) ────────────────────────────┐┌ EVENT RISK ─────────────────────────────┐
│ COMEX ████▌ ₹−161   rupee ▌ ₹+77   → fair ₹1,44,181 (−1,898) ││ FOMC ★ · US CPI · COT Fri · GOLDGUINEA  │
│ (reuse the CMDT waterfall; one line, not the whole desk)      ││ OCT expires Fri 30 Oct · GOLD DEC 4 Dec  │
└───────────────────────────────────────────────────────────────┘└─────────────────────────────────────────┘
```
Numbers above are the verified ones where they exist (spot 4,003.4; DFII10 2.64; MM net +104,206; GLD 1,045.64 t,
−11.98 t; landed ₹1,22,171; fair ₹1,44,181; IBJA 999 ₹1,41,448; DEC→FEB 4002.9→4044.0 = +1.03%) and illustrative where they
do not (sparklines, percentiles). The build computes, never hard-codes.
Charts: eight `Stat` tiles with `Spark`; one attribution bar (reuse `Waterfall` from `GoldPreOpen.tsx`).
Data: S1, FRED (DFII10/T10YIE/DGS2/DGS10), DXY (`DX-Y.NYB`, app), P1 (COT net + percentile once history exists), P4, B5/B6,
H1, S3, events (ECO + `shared/mcx_specs` expiries).
Refresh: tiles 60 s from the cache; daily series from DuckDB at page load.
Tooltips: definition + "why it matters for gold" + lag.
Verdict: **PUBLISH-CORE**. The verdict sentence must be rule-based and reviewable (each clause maps to a threshold listed in
LEARN) and must say "describes, does not predict".

### 5.2 DAILY — the Kitco 24-hour and 3-day charts, done our way

```
┌ 24 HOURS · COMEX GC DEC-26 (Yahoo, ≈1 min delayed) · cross-check gold-api $3,991.6 00:13Z ──── [1m|5m] [prev day ☑] [sessions ☑] ┐
│ $/oz                                                                                              NY 08:00        17:00   │
│ 4,020 ┤                 ····prev day (Thu 23 Oct, dotted)····                                                             │
│ 4,010 ┤        ╭─╮                                                                                                       │
│ 4,000 ┤ ───────╯ ╰──╮   ─ ─ ─ ─ ─ last settle 4,007.9 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│ 3,990 ┤             ╰──╮                                                                   ●4,003.4 ▼4.5 (−0.11%)        │
│ 3,980 ┤                ╰─                                                                                                  │
│       └──┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┬──                     │
│  IST   03:30     06:00    09:00    12:00    15:00    18:00    21:00    00:00    02:30 ▒gap▒ 03:30                           │
│  NY    18:00     20:30    23:30    02:30    05:30    08:30    11:30    14:30    17:00                                       │
│  ▒ SYDNEY/TOKYO ▒▒ SHANGHAI (SGE) ▒▒▒ LONDON ▒▒▒▒ NEW YORK ▒▒▒  · MCX 09:00–23:30 IST (bar under the axis)                  │
├ LEGEND  Wed 22 Oct close 4,160.1 ▼ · Thu 23 Oct close 4,007.9 ▼ · Mon 26 Oct last 4,003.4 ▼4.5 (−0.11%) · hi 4,017.9 lo 4,002.7│
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
┌ 3 DAYS OVERLAID (one 24-h axis, IST) ─────────────────────┐┌ WHAT MOVED TODAY ─────────────────────────────────────┐
│ ─ Thu (cyan) ─ Fri (red) ─ Mon (green)  bands as above     ││ since MCX close Thu 23:30 IST: COMEX ₹−161 · INR ₹+77 │
│                                                            ││ fair ₹1,44,181 (−1,898 vs settle) · gold/silver 74.3  │
└────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────┘
┌ INTRADAY TAPE (last 12 × 5-min bars)  time · last · Δ · range · volume ───────────────────────────────────────────────────┐
```
Chart types: line (1-min from the 7-day store) with the **previous day as a dotted overlay** on the same 24-h axis (Kitco's
feature), the **last settlement as a dashed reference line** ("Last Close"), **session bands**, two-row time axis (IST over
NY). 3-day overlay = three coloured lines on one 24-h axis. Inline SVG (`useChartSize`, `axisTicks`); no candles intraday.
Session bands (fixed, documented in LEARN, IST): Sydney/Tokyo 03:30–11:30; Shanghai (SGE) 06:30–09:00 & 11:00–13:00 plus the
night session 17:30–00:00; London 12:30/13:30–21:00/22:00 (BST/GMT); New York 18:30/19:30–23:00/00:00; MCX 09:00–23:30/23:55
(`shared/mcx_specs.evening_close`). The 17:00–18:00 ET maintenance hour (02:30–03:30 IST summer, 03:30–04:30 winter) is a
hatched column (visible in Kitco's 3-day image as the flat segment).
Data: S1 `GC=F` 1-min (7-day window) in DuckDB `gold_bars_1m`; live last from the cache; S6 cross-check chip; the "what
moved" numbers from `/api/mcx/overlay` (already computed — do **not** recompute).
Refresh: 60 s (the view re-reads the cache; the 5-minute job fetches).
Verdict: **PUBLISH-CORE** — the visual the owner asked for, with IST and MCX hours that Kitco lacks. Tape: PUBLISH-CONTEXT.

### 5.3 WEEKLY — this week in context

```
┌ 60 SESSIONS · daily candles GC front (Yahoo 1d) + MCX GOLD settle (ICICI master, ₹ right axis) ─── [candles|line] [MCX ☑] ┐
│ lightweight-charts candlestick, 20/50-day lines, volume below; right axis ₹/10 g for the MCX settle line; Mondays shaded     │
├ WEEK TABLE  Mon ▸ Fri: open · high · low · close · Δ% · range% · COMEX vol · MCX OI Δ (lots) · IBJA PM · GLD Δt · COT (Fri)─┤
│ 20 Oct … │ 21 Oct … │ 22 Oct ▼2.83% · GLD −12.0 t │ 23 Oct ▼0.70% · IBJA 1,41,448 │ COT Tue 20: MM net +104,206 (−2.7%)      │
├ WEEKLY RETURNS GRID (last 26 weeks): colour cells Mon–Fri daily Δ% plus the week total ─────────────────────────────────────┤
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
Charts: candlesticks (`lightweight-charts`), a 26-week heat grid (SVG), a week table (`DataTable`, CSV export built in).
Data: S1 daily (`gold_daily`), P4 (`mcx_gold_daily`), B6 IBJA PM, H1 GLD tonnes, P1 weekly row.
Verdict: PUBLISH-CORE (the owner asked for "weeks"); nothing predictive, the table is the audit trail.

### 5.4 MONTHLY — the long view and seasonality

```
┌ MONTHLY CANDLES since 2000 (GC continuous; Yahoo `max` monthly verified; daily→M once period1 history is stored) · log ☑ · ₹ ☐ ┐
├ SEASONALITY GRID (median monthly return 2000→2025; hit-rate % second row; Indian festival/wedding months marked) ─────────┤
│        Jan   Feb   Mar   Apr   May   Jun   Jul   Aug   Sep   Oct   Nov   Dec                                                │
│ med %   …     …     …                                                                                                       │
│ hit %   …                                                                                                                   │
│ 26 years is a small sample; hover shows the box of outcomes per month — the spread dwarfs the median                        │
├ RETURN LADDER  3d · 7d · 30d · 60d · 6m · 1y · 5y · 10y · 15y (Kitco's widget) — in $, in ₹ (GOLDBEES / landed) and in the DXY basket┤
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
Charts: monthly candles (log), seasonality grid (SVG heat cells with box-plot hover), return ladder (`KV` + sparklines).
Data: S1 (`max` monthly verified; `10y/1wk` verified; daily since 2000 UNVERIFIED today), S5 GOLDBEES for the ₹ ladder,
H5 WGC monthly averages (link only).
Verdict: PUBLISH-CONTEXT. Seasonality published with the caveat and becomes a G-STUDY candidate (§8).

### 5.5 POSITIONING — who is long, who is short (weekly COT + daily MCX OI)

```
┌ CFTC COT · GOLD (COMEX 088691) · Disaggregated, futures only · report Tue 20 Oct · released Fri 23 Oct · next Fri 30 Oct (Sat 01:00 IST) ┐
│ NET POSITION BY CATEGORY (stacked bars, 2 y) + price line (right axis)                                                                  │
│  +300k ┤ ▇ managed money   ▇ other reportables   ▇ non-reportable            ─ GC front ($)                                          │
│      0 ┼───────────────────────────────────────────────────────────────────────────────────────────                                  │
│  −300k ┤ ▇ swap dealers   ▇ producer/merchant                                                                                          │
├ LATEST WEEK  category · long · short · net · Δnet w/w · % of OI · 3-y percentile ──────────────────────────────────────────────────┤
│ Managed money     120,970   16,764   +104,206   −2,883   25.9%   (pct once history is stored)                                           │
│ Swap dealers       17,737  238,536   −220,799   +3,295   the other side of the ETF/OTC book                                             │
│ Producer/merchant  19,715   34,498    −14,783   +3,654                                                                                  │
│ Other reportables 116,172   20,513    +95,659   −5,131                                                                                  │
│ Non-reportable     51,407   15,690    +35,717   +1,065                                                                                  │
│ Open interest 402,279 (+5,934 w/w) · 288 traders                                                                                        │
├ OI × PRICE QUADRANT (weekly, last 52 points) ───────────────────────────┐┌ MCX OPEN INTEREST BY CONTRACT (daily, ICICI master) ──────────┐
│  price ▲/OI ▲ long build-up      price ▲/OI ▼ short covering             ││ GOLD DEC-26 16,650 lots · FEB-27 749 · APR 42                 │
│  price ▼/OI ▲ short build-up     price ▼/OI ▼ long unwinding             ││ GOLDM NOV 48,437 · DEC 22,922 · GUINEA OCT 12,009 (exp. Fri)   │
│  (dots by quadrant; this week highlighted; "folklore until tested")      ││ stacked bars, 60 d; "positions closed" = OI ↓ on the day       │
└─────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────────────┘
```
Charts: stacked bars + dual-axis price line (SVG), quadrant scatter (SVG), MCX OI stacked bars (SVG), `DataTable`s.
Data: P1 (Socrata weekly → `cot_gold_weekly`; G-COT specifies the full field map and the legacy/combined variants), P4 (daily
→ `mcx_gold_daily`), S1 weekly close.
The owner's "which position got closed, who are short/long **daily**": daily is answered only by **MCX OI per contract**
(opened = OI up, closed = OI down; it does not say *who*) and by ETF tonnes; *who* is answered **weekly** by COT with a 3-day
lag. The page says this in one sentence under the title.
Verdict: PUBLISH-CORE for charts/tables; the quadrant labels are **context** (the classic OI reading has no proven edge in
the house's own FII study on NSE — `reports/fii_positioning/FINDINGS.md`, FAIL — and no gold study yet; G-COT will run one).

### 5.6 PHYSICAL — premiums and investment demand

```
┌ INDIA PREMIUM ────────────────────────────────────────────┐┌ SHANGHAI PREMIUM ────────────────────────────────────────────┐
│ IBJA 999 PM ₹1,41,448/10 g (23 Oct) · landed COMEX×INR     ││ SGE Au99.99 close ¥864.00/g (23 Oct) → $/oz = 864 ÷ USDCNY    │
│ ₹1,22,171 (26 Oct 05:55; INR 94.93) → +15.8% · MCX DEC     ││ × 31.1035 (CNY 6.6749 at 20:11 NY) = $4,026 vs spot at the SGE │
│ settle 1,46,079 → +18.0% implied (app's figure)            ││ close → premium shown with BOTH timestamps                    │
│ line 1 y: premium % with duty steps annotated (6% + 1% AIDC)││ line 1 y; hover: "premium = Chinese buyers pay above London = │
│ hover: "duty + GST are not in COMEX; above duty = local     ││ physical demand; discount = weak demand"                       │
│ demand; below = discount, imports slow"                    ││                                                               │
├ ETF HOLDINGS ─────────────────────────────────────────────┐┌ LINKED (no free feed) ───────────────────────────────────────┐
│ GLD tonnes (daily since 2004) + daily Δ bars; IAU 463.05 t ││ WGC ETF flows (monthly xlsx) · WGC central-bank buying ·       │
│ (23 Oct); 30-day cumulative flow                           ││ COMEX warehouse stocks (CME 403) · LBMA (licence) · DGCI&S     │
└────────────────────────────────────────────────────────────┘└───────────────────────────────────────────────────────────────┘
```
Charts: two premium lines (SVG) with annotated duty changes, ETF tonnes line + Δ bars, a linked-checks list (the pre-open
desk's `manual_checks` component, moved here — §5.11).
Data: B6 IBJA (parse the public 30-day table 12:30 and 17:30 IST → `gold_india_ibja`), B5 SGE (13:30 IST → `gold_sge_daily`),
H1 SPDR XLSX (07:00 IST → `gold_etf_holdings`), H3 iShares page (G-PHYSICAL to decide), USD/CNY from the app's Yahoo cache.
Definitions: landed price; duty/AIDC/GST stack; 995 vs 999 (MCX GOLD is 995; IBJA quotes both — compare like with like:
IBJA 995 vs MCX, IBJA 999 vs landed × 999/995); Shanghai premium.
Verdict: PUBLISH-CORE for the two premiums (the supply-demand gauges a bullion desk watches), PUBLISH-CONTEXT for ETF tonnes.

### 5.7 MACRO — why gold moved (the KGX idea, generalised)

```
┌ DRIVERS (60 d; each with its 60-d correlation to gold's daily change) ────────────────────────────────────────────────────────┐
│ 10-y real yield 2.64% · corr −0.xx │ DXY · corr −0.xx │ breakeven 2.34% │ 2s10s 31 bp │ Brent $115 │ VIX │ USD/INR 94.93     │
├ GOLD IN THE DXY BASKET (KGX replica) ─────────────────────────────┐┌ GOLD IN CURRENCIES (Kitco's table) ───────────────────────┐
│ line: gold USD (rebased) vs gold in basket (rebased), 1 y          ││ USD 4,003.4 · INR 1,22,171/10 g landed · EUR · GBP · JPY · │
│ today: Δ total = dollar part + trading part (formula §1.3)         ││ CNY · CHF · AUD · CAD · SEK (1-d Δ% each)                   │
│ weights EUR 57.6 JPY 13.6 GBP 11.9 CAD 9.1 SEK 4.2 CHF 3.6          ││ hover: "up in USD but down in EUR = it was the dollar"      │
├ GOLD vs REAL YIELD scatter (5 y monthly; this month highlighted) ──┐┌ GOLD/SILVER RATIO 74.3 · 10-y line with percentile bands ──┐
└────────────────────────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────┘
```
Data: FRED daily (`macro_daily`), Yahoo FX for the basket (EURUSD=X and INR=X already fetched by the app; JPY=X, GBPUSD=X,
CAD=X, SEK=X, CHF=X **UNVERIFIED today** — 429), DXY `DX-Y.NYB` (app).
Verdict: PUBLISH-CORE for drivers + the KGX replica ("understand the price change"), PUBLISH-CONTEXT for scatter and ratio.
Evidence: real yields and the dollar are **contemporaneous explainers, not leading indicators**; the correlation is shown so
the page never implies a forecast.

### 5.8 CONTRACTS — which contract, what it costs, when it rolls

```
┌ COMEX TERM STRUCTURE (Yahoo contract months) ───────────────────────────┐┌ MCX GOLD CHAIN (ICICI master 23 Oct) ────────────────────────┐
│ $/oz 4,250 ┤                                              ● DEC-27 4,209 ││ expiry · settle ₹ · band ±3% · OI lots · ΔOI · implied carry │
│      4,150 ┤                               ● AUG 4,142.6                 ││ 04 Dec 26  1,46,079  1,41,697–1,50,461  16,650  …     —      │
│      4,100 ┤                     ● JUN 4,115.0                           ││ 05 Feb 27  1,48,589                        749   1.7% (10%/y)│
│      4,050 ┤          ● APR 4,081.2                                      ││ 05 Apr 27  1,50,972                         42   1.6%        │
│      4,000 ┤ ● DEC-26 4,002.9  ● FEB 4,044.0                             ││ GOLDM 05 Nov 1,44,584 OI 48,437 · 04 Dec 1,46,081 OI 22,922   │
│            └──────┬────────┬────────┬────────┬────────┬──                 ││ GUINEA 30 Oct 1,16,648 OI 12,009 (expires this Friday)        │
│  contango DEC→FEB +$41.1 = 1.03% (3.2%/y) · ghost curve: 1 week ago       ││ curve today vs 1 week ago (CCRV) · expiry flags                │
├ ROLL CALENDAR ──────────────────────────────────────────────────────────┐┌ SPEC CARD (DES) + COST ─────────────────────────────────────┐
│ MCX GOLD DEC-26 expires Fri 4 Dec (5th is Sat); liquidity typically moves ││ GOLD 1 kg · ₹/10 g · tick ₹1 = ₹100 · 995 · delivery 1 kg ·    │
│ to FEB ~5 sessions before · GOLDM monthly 5th · COMEX GCZ6 first notice  ││ margin ≈6% indicative · round trip from the MCXG ticket       │
│ (CME rule; CME blocked for scripts → "verify on CME" link)               ││ (reuse MCXG's specs row; do not duplicate the ticket)          │
└─────────────────────────────────────────────────────────────────────────┘└──────────────────────────────────────────────────────────────┘
```
Charts: curve as dot-and-line SVG with a stored "1 week ago" ghost; MCX chain `DataTable`; roll calendar list.
Data: S3 (store daily → `gold_curve_daily`), P4 (`mcx_gold_daily`), `shared/mcx_specs` (specs, expiries, costs — already
correct, reuse), CME first-notice dates LINK-ONLY.
Definitions: contango/backwardation; implied carry = (F2/F1 − 1) × 365/days; why MCX back months carry more (rupee rates,
duty expectations); the front-by-OI rule.
Verdict: PUBLISH-CORE (the owner asked to "choose the contract differently"; chain + roll calendar + carry is that decision
support). Roll cost is a cost, not a signal — presented as such.

### 5.9 LEARN — basic to sophisticated, on the page

A `Markdown` panel with collapsible sections, each term linking back to the view that uses it. Required entries (each:
plain-English line · exact definition/formula · pitfall): spot vs bid/ask vs futures vs CFD; troy ounce, gram, tola, tael,
995/999; LBMA price (AM/PM auction; why it is licensed now); COMEX GC (100 oz, $0.10 tick = $10, months G/J/M/Q/V/Z, first
notice, 23-hour session, 17:00–18:00 ET break); MCX GOLD/GOLDM/PETAL/GUINEA (from `mcx_specs`); landed price and the duty
stack; India and Shanghai premium; contango/backwardation/roll yield; open interest and the four quadrants (folklore until
tested); COT categories (producer/merchant, swap dealer, managed money, other reportables, non-reportable; futures-only vs
combined; Tuesday/Friday timing); ETF tonnes; real yield as gold's opportunity cost; DXY and the KGX decomposition (§1.3);
gold/silver ratio; seasonality caveats; the house fair-open model and the ₹300 chase rule (link to CMDT); the session clock;
BullionVault's three prices; what is **not** free (LBMA, CME OI/warehouse, MCX bhavcopy, Kitco feed) and where to click.
Optional: the "Kitco mini" kitconet tile (off by default, hot-linked per their condition).
Verdict: PUBLISH-CORE.

### 5.10 What the compact WEI card and the BRF line keep

- **WEI** (Commodities group, row `GC=F GOLD`): keep the current row exactly — last, Δ, Δ%, 1-month spark, day-range
  position, age. Add **one** thing: the row jumps to the GOLD page (GO `GOLD`) and its hover card shows *spot · MCX settle ·
  implied premium · roll* (four numbers from the cache). Nothing else moves into WEI.
- **BRF**: keep the "Gold open (MCX)" panel exactly as it is (verdict, fair open, baseline, gap, chase limit before 09:15;
  "this morning's call" after). Add **one line** under it: `GOLD health: WEAK WEEK, DOLLAR-DRIVEN · India premium 18.0% ·
  roll 1.03% · COT MM net −2.7% w/w ›` (the HEALTH verdict, truncated, linking to GOLD). No second chart, no second number set.

### 5.11 De-duplication map

| Number / panel | Today | After |
|---|---|---|
| Fair open, gap waterfall, chase verdict, inputs, accuracy log | CMDT (`GoldPreOpen`), BRF | **stay** (a pre-open workflow); GOLD header shows fair value once |
| Context table (DXY, EUR/USD, US10Y, silver, TIPS) | CMDT | **→ GOLD › MACRO** (CMDT keeps only the two legs the model uses) |
| Headlines | CMDT | stay (and MKT); GOLD does not repeat them |
| Manual checks list | CMDT | **→ GOLD › PHYSICAL "linked"** (FedWatch, MCX circulars → CONTRACTS) |
| Session clock, holidays, Breeze quote, specs, paper ticket | MCXG | **stay**; GOLD › CONTRACTS shows the chain (new) and links the specs row |
| COMEX × rupee overlay (COMEX, INR, landed, fair, premium) | MCXG | **stays as the broker-price comparison**; GOLD header shows landed/fair once; GOLD › PHYSICAL shows the premium **history** (new) |
| Futures board + 6-M line chart | CMDT | gold tile stays in the board; its detail chart opens GOLD › WEEKLY |
| Gold row | WEI | stays (one row, + hover) |
| Gold panel | BRF | stays + one line |

---

## 6. Usefulness verdicts per metric (the owner's gate)

| Metric | Plain English | Desk practice / Bloomberg analogue | Lag · freq | Evidence of predictive value | Verdict |
|---|---|---|---|---|---|
| Spot/front-future price, bid/ask, day range | what gold costs now, how far it moved | `XAU Curncy`/`GC1 Comdty` GP/GIP | ≈1 min · continuous | n/a (it is the price) | PUBLISH-CORE |
| 24-h chart with previous-day overlay and sessions | *when* in the day the move happened and which centre was trading | GIP with session shading (Kitco's signature) | 1 min | diagnostic, none claimed | PUBLISH-CORE |
| 3-day overlay | today's path vs the last two days, hour by hour | Kitco | 1 min | none | PUBLISH-CONTEXT |
| Daily/weekly/monthly candles, return ladder | the trend at three horizons | GP D/W/M; HP | daily | time-series momentum in gold is documented (Moskowitz–Ooi–Pedersen 2012, 58 futures incl. gold), weak and regime-dependent | PUBLISH-CORE (chart); ladder PUBLISH-CONTEXT |
| Seasonality grid | which months tended to be strong | commodity seasonality screens; bullion folklore (Sep–Feb, Diwali, Chinese New Year) | annual | weak, unstable, 26 samples → **context only** | PUBLISH-CONTEXT with caveat |
| COT managed-money net, % of OI, percentile | how long the fast money is | CFTC tickers; CME COT tool; traders fade extremes | 3 days · weekly | large-trader positioning shows little short-horizon predictive power in the COT literature (Sanders–Irwin–Merrin 2009); house FII study on NSE: FAIL; no gold study yet → **context until G-COT's study** | PUBLISH-CORE (chart); signal claims DO-NOT-PUBLISH |
| Swap-dealer / producer net | the hedging side (ETF-provider and miner hedges) | same | weekly | context | PUBLISH-CONTEXT |
| Open-interest quadrant | did the move come with new positions or closing ones | futures-desk heuristic | daily (MCX) / weekly (COMEX) | folklore; untested in-house | PUBLISH-CONTEXT (labelled) |
| MCX OI by contract, daily Δ | positions opened/closed on MCX, where liquidity sits, when to roll | DERV-style rollover panel | T−1 · daily | n/a (operational) | PUBLISH-CORE |
| Term structure, implied carry, roll cost | what holding the future costs | CT, CCRV | 1 min / daily | roll yield is a **cost**, not a forecast (Erb–Harvey 2006) | PUBLISH-CORE |
| India premium (IBJA vs landed; MCX implied) | is India paying above/below world price → local demand, import flow | bullion desks; RBI/SGB reference | 2×/day · daily | reflects demand; price-lead unknown → **G-STUDY** | PUBLISH-CORE |
| Shanghai premium | same for China | bullion desks | daily (13:00 IST) | SGE premium tracks Chinese import demand; price-lead unproven in-house | PUBLISH-CORE |
| ETF tonnes and daily Δ | Western investment demand ("paper gold" flows) | WGC, SPDR; desks watch GLD Δt | daily | largely coincident/lagging with price | PUBLISH-CONTEXT |
| Real yield, breakeven, DXY, USD/INR | the opportunity cost of holding gold; the currency effect | ECO/GP overlays; KGX | 1 day (FRED) / live (Yahoo) | high **contemporaneous** explanatory power (2006–2021 real-yield link, weaker since 2022); no lead | PUBLISH-CORE as explanation; DO-NOT-PUBLISH as signal |
| KGX-style decomposition | how much of today's move was the dollar | Kitco KGX | live | arithmetic identity | PUBLISH-CORE |
| Gold/silver ratio | silver's relative cheapness; sentiment proxy | RV desks | live | slow, unreliable mean reversion | PUBLISH-CONTEXT |
| Fair open / chase verdict | should I trade the MCX open | house model | 08:45 | accuracy log has **4 rows** (26 Oct): too few; keeps logging | stays in CMDT |
| Event calendar (FOMC, CPI, COT release, MCX expiry) | when the known shocks are | ECO | — | event-day volatility is well documented | PUBLISH-CORE (one strip) |
| Kitco bid/ask, KGX values, Kitco images | — | — | — | — | LINK-ONLY / optional kitconet tile |
| LBMA AM/PM | the benchmark everyone settles on | — | daily | — | LINK-ONLY (licensed; blocked) |
| CME OI/volume/settlements/warehouse/FedWatch | the official COMEX numbers | — | daily | — | LINK-ONLY (403) |

---

## 7. Data plumbing (so "weeks, days and months" exist)

Nothing gold-related is in DuckDB today. Proposed tables (data-service `storage/duckdb_store.py` style) and jobs
(master-controller IST scheduler → `POST /jobs/...` on data-service, as `ingest-bhavcopy`; the UI reads via ui-api proxies):

| Table | Grain / PK | Source | Job (IST) | Notes |
|---|---|---|---|---|
| `gold_bars_1m` | (symbol, ts); `GC=F`, front `GC?NN.CMX`, `SI=F`, `INR=X`, `DX-Y.NYB` | S1 `7d/1m` | every 5 min 03:30–02:30; **shares the `gold_preopen` cache** | keep 400 days (≈500k rows/symbol); backfill from `60d/5m` on first run |
| `gold_daily` | (symbol, date) OHLCV | S1 daily (`period1/period2`, to verify) + `GLD`, `GOLDBEES.NS` | 03:00 | continuous front |
| `gold_curve_daily` | (date, contract) last, volume | S3 | 03:00 | six months; keeps "1 week ago" |
| `mcx_gold_daily` | (date, contract, expiry) settle, band, OI | P4 (read the file ui-api already downloads; do not re-download) | 07:15 | the only free daily MCX history; start today |
| `cot_gold_weekly` | (report_date) five categories long/short + OI + traders | P1 (G-COT field map; legacy too) | Sat 02:00 + Mon 07:00 catch-up | backfill since 2006 (`$limit=5000`) |
| `gold_etf_holdings` | (date, fund) tonnes, ounces, NAV, shares | H1 XLSX, H3 page | 07:00 | private use only (terms) |
| `gold_sge_daily` | (date, contract) OHLC, VWAP, volume, turnover + USD/CNY | B5 | 13:30 | CNY/g |
| `gold_india_ibja` | (date, session, purity) ₹/10 g | B6 (30-day table) | 12:30, 17:30 | premium computed at read time |
| `macro_daily` | (series, date) | FRED (plain UA), Treasury | 06:30 | DFII10, T10YIE, DGS2, DGS10, DTWEXBGS, DCOILBRENTEU; studies must use ALFRED vintages (docs/PROGRAMMATIC_DATA_ACCESS.md §3) |
| `gold_health_daily` | (date) eight gauge values + verdict text | computed | 08:30 | lets a later study check whether "weak weeks" behaved differently |

Rate budget and resilience: Yahoo returned **429 after ~25 chart calls in a minute and was still refusing 16 minutes
later** on both hosts. Rules: data-service owns Yahoo history; ui-api keeps its existing six live series; the 5-min job
makes **one** `7d/1m` call per symbol; every job backs off on 429 (5 → 10 → 20 min) and logs STALE; the UI shows the stored
last bar with its timestamp. gold-api.com ≤ 1 call/min (its terms ban "multiple requests per second"). SGE/IBJA/SPDR once
per slot, browser-like UA, 20-s timeouts, failures to the Telegram `info` channel like the gold snapshot. FRED plain UA.
All new jobs sit outside the 07:45–09:20 and 18:30–21:15 IST freeze windows.

---

## 8. Open questions and proposed studies

1. **G-STUDY-PREMIUM**: does the India premium (IBJA vs landed) or the Shanghai premium lead MCX/COMEX returns over 5–20
   sessions? Needs ≥2 years of `gold_india_ibja`/`gold_sge_daily` — start storing now.
2. **G-STUDY-COT** (G-COT's): managed-money extremes vs forward gold returns (Socrata back to 2006).
3. **G-STUDY-SEASON**: monthly seasonality with bootstrap bands before the grid may say more than "median".
4. Terms: show the SPDR XLSX (redistribution prohibited) and IBJA table (terms 404) at all, or only derived numbers? My
   recommendation: derived numbers only, with the publisher link.
5. Yahoo daily history since 2000 (`period1/period2`) — confirm once the 429 clears.
6. FX basket pairs for the KGX replica (JPY, GBP, CAD, SEK, CHF) — verify after the 429 clears.
7. Should the GOLD page host the accuracy log (today in CMDT)? I say no — it is a pre-open workflow artefact.
8. **Today's 08:45 snapshot**: it uses `FRESH_ONLY` Yahoo series; if Yahoo is still throttling this IP at 08:45 the snapshot
   returns 503 ("No fair value right now") and the accuracy log skips a day. My probes (~45 Yahoo calls between 05:43 and
   06:04) contributed to the throttle; the app's own 60-s polling is the standing load. Check the 08:45 Telegram alert.

---

## 9. Addendum — results of the delayed Yahoo probe

Second probe queued after a 100-s back-off (05:48 IST): all 15 symbols **429** on `query2`. Third probe after a 600-s back-off
(06:04 IST), five symbols 8 s apart on `query1`: `PAXG-USD`, `XAU=X`, `GC=F period1=2000-01-01 interval=1d`, `GOLDBEES.NS max`,
`GC=F 1d/1m` — **all 429 "Too Many Requests"** (`scratch/yahoo_retry2.log`). So the following remain **UNVERIFIED today**
(not "unavailable"): a Yahoo spot symbol (`XAU=X`), tokenised 24/7 gold (`PAXG-USD`) as a weekend proxy, daily GC history
since 2000, GOLDBEES full history, 1-minute bars via `range=1d`, and the five KGX basket FX pairs. The first batch proved the
feed itself (1-min bars for 7 days, 5-min for 60 days, weekly for 10 years, monthly since 2000). Re-run `scratch/retry.py`
tomorrow outside the app's busy hours before building the MONTHLY daily resample.

---

## Appendix A — probe log (26 Oct 2026 05:42–06:10 IST)

| name | status | ms | content-type | bytes | note |
|---|---|---|---|---|---|
| kitco_charts_gold | 200 | 1438 | text/html | 119,207 | Next.js page |
| kitco_home | 200 | 615 | text/html | 263,567 | links charts.kitco.com compact 24h png |
| kitco_livegold_legacy / historicalgold_legacy / price_gold | 200 (301→/charts/gold) | 1352 / 1197 / 1228 | text/html | 119,194 | |
| kitco_img_live gold.gif / nygold.gif / t24 | **502** | ~360 | text/html | 332 | dead legacy paths |
| /kitco-gold-index | **404** | 402 | text/html | 49,990 | moved to /markets/kitco-gold-index (200) |
| kitco_terms | 200 | 497 | text/html | 157,578 | Jan 3, 2024 |
| corp.kitco.com/terms-of-use | 404 | 1569 | | | |
| kitco robots.txt | 200 | 362 | text/plain | 406 | Allow: / |
| kitco /rss/ | 404 | 991 | | | |
| kitconet main / menu / price | 200 | 1694 / 349 / 348 | text/html | 15,762 / 4,284 / 42,555 | free-embed conditions |
| kitconet webcharts au_en_us / au_en_inr | 200 | 835 / 344 | text/html | 27,003 / 12,436 | image lists |
| kitconet t24 usoz / inoz / ingr / tny usoz | 200 | 584 / 301 / 297 / 289 | image/gif | 1,761–1,883 | 172×114 |
| kitco LFgif AU0030lnb | 200 | 502 | image/gif | 8,176 | 450×275 |
| charts.kitco.com 3day / ny_hours webp | 200 | 338 / 88 | image/webp | 21,736 / 15,512 | 1260×730 |
| charts.kitco.com 24h compact png | 200 | 370 | image/png | 20,209 | 438×337 |
| kitco connecting.html | 200 (301→home) | 1185 | | | |
| yahoo GC=F 1d/5m · 7d/1m · 60d/5m · max/1d · 10y/1wk | 200 | 305 / 379 / 313 / 139 / 152 | json | 3 KB / 578 KB / 1.1 MB / 26 KB / 51 KB | |
| yahoo XAUUSD=X 5d/5m · max/1d | **404** | 122 / 135 | json | 108 | "symbol may be delisted" |
| yahoo SI=F 1d/5m | 200 | 114 | | | |
| yahoo GCZ26 / GCG27 / GCJ27 / GCM27 / GCQ27 / GCZ27 | 200 | 111–121 | | | |
| yahoo GLD 1mo/1d · GOLDBEES.NS 1mo/1d | 200 | 111 / 121 | | | |
| yahoo second batch (15) 05:48 · third batch (5) 06:04 | **429** | ~100–780 | text/html | 19 | both hosts |
| stooq xauusd d / xagusd d / 5min / gc.f (browser + curl UA) | 200 | 170–814 | text/html | 796 | JS proof-of-work |
| stooq q/l quote | 404 | 173 | | | |
| lbma gold_am / gold_pm / silver (3 UAs) | **403** | 71–608 | text/html | 4,546–4,571 | Cloudflare |
| lbma prices page | 200 | 1119 | text/html | 274,147 | IBA licence text |
| FRED GOLDPMGBD228NLBM / GOLDAMGBD228NLBM | **404** | 646 / 464 | | | removed |
| FRED DFII10 / DTWEXBGS / T10YIE / DEXINUS / DGS2 / DGS10 / DCOILBRENTEU | 200 | 59–680 | application/csv | 274–690 | |
| gold-api.com XAU | 200 | 637 | json | 182 | |
| goldprice.org dbXRates (plain / spoofed referer) | 403 / 200 | 220 / 228 | | 10 / 241 | |
| swissquote XAU/USD | 200 | 1134 | json | 1,129 | |
| spdr GLD_US_archive_EN.csv | 200 (302→barlist) | 736 | **application/pdf** | 696,843 | |
| spdr usa / historical-data pages | 200 | 259 / 613 | text/html | 83 KB / 1.3 MB | |
| spdr historical-archive xlsx | 200 | 468 | xlsx | 542,343 | 5,721 rows |
| ishares IAU page | 200 | 1761 | text/html | 1,633,473 | |
| sge delayed / benchmark / daily report | 200 | 1039 / 1030 / 373 | text/html | 46 KB / 55 KB / 90 KB | |
| ibja home | 200 | 485 | text/html | 156,145 | /terms 404 |
| cme settlements page / settlements api / volume api | **403** | 167 / 81 / 80 | json | 602 | |
| mcx bhavcopy | **403** | 222 | | 398 | |
| wgc goldhub prices / etf | 200 | 488 / 316 | text/html | 73 KB / 66 KB | |
| wgc fsapi spotprice | **429** | 764 | text/html | 33,116 | |
| cftc socrata 72hh-3qpy gold | 200 | 1205 | json | 13,595 | 2 rows × 194 fields |
| cftc deacmesf.htm | 200 | 245 | text/html | 67,978 | |
| goldprice.org / bullionvault chart / bullionvault market json / tradingeconomics | 200 | 1282 / 860 / 520 / 647 | | | |
| investing.com xau-usd | **403** | 238 | text/plain | 3 | |
| local GET /api/mcx/overlay?contract=GOLD (05:55 IST) | 200 | — | json | — | COMEX 4002.9 (05:45), INR 94.93 (01:32), landed 122,171, fair 144,181, implied premium 18.02% vs 22 Oct settlement |

## Appendix B — Kitco chart anatomy → our implementation

| Kitco feature | Ours |
|---|---|
| Bid/ask spot strip, NY time | header: GC last (Yahoo) + gold-api cross-check; IST with NY in the tooltip; bid/ask only when Breeze serves MCX (1-min bars verified in-house) |
| Units table (oz/g/kg/dwt/tola/tael) | page-global unit picker; tola and ₹/g for India |
| Purity table | LEARN + the premium view compares like with like (995 vs 999) |
| Day's range | header + DAILY legend |
| 24-h NY chart: previous closes legend, Last Close line, hi/lo | DAILY |
| 3-day overlay with session bands | DAILY (IST axis, MCX band added) |
| 30/60-day with London AM/PM | WEEKLY candles; fixes are licensed → LBMA row is a link |
| 6 m / 1 y / 5 y / 10 y | WEEKLY/MONTHLY (`10y/1wk` verified; daily since 2000 to verify) |
| Historical archive by month since 2000 | MONTHLY candles + CSV export of any table |
| Performance widget 3 d … 15 y, 13 currencies, 4 units | MONTHLY return ladder in $, ₹ and the DXY basket |
| Gold in currencies | MACRO (USD spot × Yahoo FX mids — Kitco's own method) |
| Gold/silver ratio | MACRO |
| KGX | MACRO (formula §1.3, generalised with the rupee leg) |
| Kitco Fix, Shanghai benchmark pages | LINK-ONLY; Shanghai *price* from the SGE daily report |
| (absent on Kitco) positioning, curve, MCX, premiums, health verdict | POSITIONING, CONTRACTS, PHYSICAL, HEALTH |

## Appendix C — Bloomberg function map used here (public guides; UNVERIFIED on a terminal)

DES description · GP/GIP/GPO graphs · HP history table · CT contract table (chain with volume/OI) · CTM exchange contracts
search · CCRV/FWCV forward curves · GLCO global commodity prices · CPFC price forecasts · ECO releases · ALLX TFF1/TFC1
(CFTC TFF) · CFTC disaggregated ticker suffixes PML/PMS/SWL/SWS/MML/MMS/…N (BBGsymbols). Tickers: `XAU Curncy` spot,
`GC1 Comdty` front future, `GCZ6 Comdty` dated. "WGC <GO>": not confirmed.
