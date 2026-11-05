# NSE free data dictionary

Every free NSE dataset useful for research, verified live on 2026-09-28 with `scripts/nse_free_data_catalog.py` (68 of 72 sources returned data; samples in `reports/nse_catalog/`), and re-verified for the Terminal v2 program on 4–5 Nov 2026 (paced GET/HEAD probes, browser UA; evidence in `reports/terminal_v2/R-DATA/probe_results_2026-11-04.json`, `R-IV/nse_probes.json`, `R-DRIVERS/evidence/`, `R-OPTIONS/REPORT.md` §4). Entries marked **Verified (Nov 2026)** carry the measured publication minute (HTTP `Last-Modified`, IST). The `<a id>` anchors are the targets of `dictionary_anchor` in data-service's `dataset_catalog` (`services/data-service/data_health/catalog.py`); the per-dataset terminal view is `docs/TERMINAL_DATA_DICTIONARY.md` (generated). Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price; every derived number the terminal shows carries a badge (`context` / `arithmetic` / `heuristic`; no `signal` exists in F&O or index attribution).

## Your question: who is holding overnight?

| Question | Dataset | Measure |
|---|---|---|
| Are buyers keeping the shares overnight? | Delivery quantity and % | Delivery volume vs its 60-day average |
| Are they doing it with borrowed money? | Margin trading (MTF) funded positions | Change in MTF financed quantity |
| Are F&O traders adding positions as it rises? | F&O bhavcopy (every contract) | Price change × change in OI (long build-up) |
| How crowded is the F&O book? | Combined OI vs market-wide limit (MWPL) | OI as % of market-wide limit |
| Is it a few big players? | Clients holding ≥3% of a stock's MWPL | Clients each holding ≥3% of the limit |
| Who: FIIs, institutions, prop desks or retail? | Participant-wise open interest | Net long/short by participant |
| Did named institutions buy in size? | Bulk deals | Bulk and block deals by client name |
| Are insiders buying? | Insider trading disclosures (SEBI PIT) | Promoter open-market purchases |
| Are more or fewer people holding it? | Shareholding pattern and number of shareholders | Quarterly shareholder counts by category |
| Is anyone betting against it? | Institutional short selling | Institutional short sales |

## Who is holding overnight

Positions and ownership: delivery, leverage, F&O open interest, shareholders

<a id="bhavcopy"></a>
### Delivery quantity and %
*Did buyers keep the shares overnight, or square off intraday?*

- **Where on the site:** All Reports → Equities → Full Bhavcopy and Security Deliverable data
- **Get it:** `nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv · per stock back to 2005: www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData?from=&to=&symbol=&type=priceVolumeDeliverable&series=ALL · MTO file nsearchives.nseindia.com/archives/equities/mto/MTO_DDMMYYYY.DAT`
- **Verified (Nov 2026):** `sec_bhavdata_full_04112026.csv` `Last-Modified` **22:05:35 IST** although the stack had stored a copy at 21:36 — NSE **re-publishes** the file after the first evening version. The 22:45 pass re-fetches it with `If-Modified-Since`; a changed body is a new `ingest_log` row (`revision` + 1, `sha256`), never a silent overwrite (point-in-time rule, PLAN §0.3). This file (`sec_bhavdata_full`) is what the `nse_bhavcopy` table stores (all securities incl. delisted, raw prices, delivery %).
- **Published:** Daily, evening after close · **History:** File format since Oct-2019; MTO file and per-stock API back to 2005 (verified)
- **Key fields:** DELIV_QTY, DELIV_PER, TTL_TRD_QNTY, NO_OF_TRADES, TURNOVER_LACS, AVG_PRICE (VWAP)
- **How to use it:** The closest free measure of shares carried overnight. Compare 5-day delivery volume with its 60-day average: a rising price on rising delivery volume suggests accumulation; rising price on falling delivery suggests intraday froth. SuryaDhana already stores this (nse_bhavcopy).

<a id="mtf"></a>
### Margin trading (MTF) funded positions
*Are traders buying this stock with borrowed money and holding it?*

- **Where on the site:** All Reports → Equities → Margin Trading Disclosure
- **Get it:** `nsearchives.nseindia.com/content/equities/mrg_trading_DDMMYY.zip (file for day T is published on T+1)`
- **Verified (Nov 2026):** `mrg_trading_031126.zip` (positions of 3 Nov) carried `Last-Modified` **22:12 IST on 4 Nov**: the file for session T lands late on T+1, so the terminal's 20:30 pass can never have it; the **22:45 pass** (`nse_evening_pass`) fetches it and the 08:35 sweep retries. Catalog row `nse_mtf` (`expected_offset_days` 1).
- **Published:** Daily, next day · **History:** Recent files verified; older naming not verified
- **Key fields:** Market totals (outstanding, fresh exposure, liquidated, ₹ lakh) + per stock: Qty financed (shares), Amount financed (₹ lakh)
- **How to use it:** Leveraged longs carried overnight by brokers' MTF clients. Rising financed quantity alongside a rising price means leveraged momentum; very high leverage near highs is crowding risk (forced selling on a dip). Market total today: ₹1.50 lakh crore outstanding.

<a id="shareholding"></a>
### Shareholding pattern and number of shareholders
*How many people hold it, and how much do FPIs, mutual funds, promoters and retail own?*

- **Where on the site:** Company page → Corporate Information → Shareholding Pattern
- **Get it:** `www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=SYMBOL (each filing links an XBRL file with NumberOfShareholders and % per category)`
- **Published:** Quarterly, within 21 days of quarter end (plus event filings, e.g. buybacks) · **History:** Last ~21 filings (5 years) via this API
- **Key fields:** promoter %, public %, XBRL: NumberOfShareholders and % for retail ≤₹2 lakh, HNI, FPI Cat I/II, mutual funds, insurers, AIFs, banks…
- **How to use it:** Ownership trend: fewer holders with rising FPI/MF % suggests institutional accumulation; a surge in retail holders with falling FPI count suggests distribution. INFY Jun-25→Jun-26: retail holders 2.49M→2.85M, FPIs 1,504→1,377 while the price fell.

### Promoter pledges (encumbrance)
*Have promoters pledged their shares, and is it rising?*

- **Where on the site:** Corporate Filings → Pledged Data
- **Get it:** `www.nseindia.com/api/corporate-pledgedata?index=equities`
- **Published:** As disclosed · **History:** Current snapshot (1,544 companies)
- **Key fields:** percPromoterHolding, percSharesPledged, numSharesPledged, percTotShares, disclosure dates
- **How to use it:** Risk filter: a high or rising pledged share means forced-selling risk if the price falls. Exclude or down-weight.

<a id="participant-oi"></a>
### Participant-wise open interest
*Are FIIs, domestic institutions, proprietary traders or retail clients long or short?*

- **Where on the site:** All Reports → Derivatives → Participant wise Open Interest
- **Get it:** `nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv (skip first line)`
- **Verified (Nov 2026):** `fao_participant_oi_04112026.csv` `Last-Modified` **20:10 IST** (R-DATA §4), 20 minutes before the 20:30 pass that ingests it (`nse_participant_oi`).
- **Published:** Daily, evening · **History:** Back to at least 2012 (verified)
- **Key fields:** Client / DII / FII / Pro × long and short contracts in index & stock futures and options
- **How to use it:** Market regime. On 25-Sep-2026 FIIs held 46,305 long vs 358,306 short index futures while retail clients were net long: a strong bearish tilt by FIIs. Use the FII net index-futures position as a go/no-go filter for new swing longs.

<a id="participant-vol"></a>
### Participant-wise trading volume
*Who traded today in F&O?*

- **Where on the site:** All Reports → Derivatives → Participant wise Trading Volumes
- **Get it:** `nsearchives.nseindia.com/content/nsccl/fao_participant_vol_DDMMYYYY.csv`
- **Verified (Nov 2026):** 200; measured **14:40 IST** (B1 probe, 4 Nov). Ingested by the 20:30 pass into `nse_participant_vol` (same layout as the OI file: a title line, then Client Type + 14 columns); badge `context`.
- **Published:** Daily, evening · **History:** Same as participant OI
- **Key fields:** Same layout as participant OI, but volumes
- **How to use it:** Pairs with participant OI: FIIs adding shorts on heavy volume carries more weight than a quiet change.

<a id="combined-oi"></a>
### Combined OI vs market-wide limit (MWPL)
*How crowded are F&O positions in this stock?*

- **Where on the site:** All Reports → Derivatives → Combine Open Interest across exchanges
- **Get it:** `nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_DDMMYYYY.zip`
- **Verified (Nov 2026):** `combineoi_04112026.zip` `Last-Modified` **19:23 IST** (R-DATA §4); 200 on 5 Nov. Ingested by the 20:30 pass (`nse_positions.TERMINAL_DATASETS['nse_combined_oi_zip']`) into `nse_combined_oi` (columns `mwpl`, `oi`, `limit_next_day`) beside the delta-equivalent file below; shown on OMON / DERV as a `context` column (% of MWPL), never coloured.
- **Published:** Daily, evening · **History:** Back to at least 2015 (verified)
- **Key fields:** NSE Symbol, MWPL, Open Interest, Future Equivalent Open Interest, Limit for Next Day
- **How to use it:** OI as a share of MWPL = crowding. Above 95% the stock enters the F&O ban; the approach to that level is often volatile. Rising OI share with rising price = new longs piling in.

<a id="combined-oi-deleq"></a>
### Delta-equivalent combined OI
*What is the real directional exposure once options are delta-adjusted?*

- **Where on the site:** All Reports → Derivatives → Combined Delta Equivalent OI
- **Get it:** `nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_deleq_DDMMYYYY.csv`
- **Published:** Daily, evening · **History:** Recent files verified
- **Verified (Nov 2026):** 200 on 4–5 Nov; measured **13:48 IST** on 4 Nov (B1 probe), i.e. the delta-equivalent file is published around midday for margins while the MWPL zip above follows at 19:23. Stored in `nse_combined_oi` (`notional_oi`, `fut_equiv_oi`); catalog row `nse_combined_oi`, badge `context`, verdict PUBLISH-CONTEXT. Precedent: the futures-equivalent OI column Bloomberg's OMON shows for stock options.
- **Key fields:** Symbol, Notional Open Interest, Portfolio-wise Futures Equivalent Open Interest
- **How to use it:** Better than raw OI for stocks with big option books: tells you the futures-equivalent position the market is carrying.

<a id="mwpl-cli"></a>
### Clients holding ≥3% of a stock's MWPL
*Is the F&O position concentrated in a few big players?*

- **Where on the site:** All Reports → Derivatives → Clients Position % ≥3% of Stock MWPL
- **Get it:** `nsearchives.nseindia.com/content/nsccl/mwpl_cli_DDMMYYYY.xls (dated T−1)`
- **Verified (Nov 2026):** 200; measured **12:50 IST** for the previous session (B1 probe). Ingested by the 20:30 pass into `nse_mwpl_clients` (`client_rank`, `pct_mwpl`; `t_minus` 1); badge `context`.
- **Published:** Daily, next day · **History:** Recent files verified
- **Key fields:** Underlying stock, then Client 1…14 = each large client's position as % of MWPL (anonymous)
- **How to use it:** Concentration signal: e.g. five clients each held 4–8% of ADANIENSOL's limit. Concentrated positioning can unwind violently; track entries and exits of big clients.

<a id="fo-bhavcopy"></a>
### F&O bhavcopy (every contract)
*Where is open interest building, by contract and strike?*

- **Where on the site:** All Reports → Derivatives → UDiFF Common Bhavcopy Final
- **Get it:** `nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip · before Jul-2024: nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip`
- **Published:** Daily, evening · **History:** Back to 2001 (verified)
- **Verified (Nov 2026):** `BhavCopy_NSE_FO_0_0_0_20261104_F_0000.csv.zip` `Last-Modified` **20:10 IST** (R-DATA §4); the 18:30 EOD job cannot have it, the **20:30 pass** is the real path and `iv_eod` runs last inside it (retry 22:45, sweep 08:35). Cached on disk: 578 UDiFF files 2024-07-08 → today (655 MB) and 1,182 legacy files 2019-10-01 → 2024-07-05 (712 MB) under `data/nse_archive/fo/<year>/`.
- **Key fields (UDiFF, 34 columns):** TradDt, BizDt, FinInstrmTp (IDF/IDO/STF/STO), TckrSymb, XpryDt, StrkPric, OptnTp, OpnPric/HghPric/LwPric/ClsPric/LastPric/PrvsClsgPric, **UndrlygPric**, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTradgVol (units), TtlTrfVal, TtlNbOfTxsExctd, NewBrdLotQty. `ClsPric` is the last-30-minute average, `LastPric` the last trade; on an untraded strike `SttlmPric` is NSE's theoretical value, so the IV store uses `ClsPric` only when `TtlTradgVol > 0` (`price_source` stored, untraded strikes carry no IV).
- **Legacy format (before 8 Jul 2024, `foDDMONYYYYbhav.csv.zip`, 16 columns):** INSTRUMENT (FUTIDX/OPTIDX/FUTSTK/OPTSTK), SYMBOL, EXPIRY_DT (`DD-Mon-YYYY`), STRIKE_PR, OPTION_TYP (CE/PE/XX), OPEN, HIGH, LOW, CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP — **no underlying price, volume in contracts**. Verified `fo01APR2022bhav.csv.zip` (788,691 B, `Last-Modified` 01 Apr 2022): the put-call-parity forward removes the need for a spot (NIFTY 1 Apr 2022: 11 expiries, monthly ATM IV 17.13 %, 25Δ skew 3.83, 96 IV strikes). Parser: `services/data-service/fo_iv/legacy_parser.py` (`nse_positions.parse_fo_bhavcopy` for the aggregate).
- **How to use it:** The official daily OI. Classify each stock daily: price up + OI up = long build-up, price up + OI down = short covering, price down + OI up = short build-up, price down + OI down = long unwinding. Also put/call ratio and largest-OI strikes per stock.

<a id="fii-stats"></a>
### FII derivatives statistics
*How much did FIIs buy and sell in F&O, and what do they hold?*

- **Where on the site:** All Reports → Derivatives → FII derivatives statistics
- **Get it:** `nsearchives.nseindia.com/content/fo/fii_stats_DD-Mon-YYYY.xls`
- **Verified (Nov 2026):** 200; measured **14:40 IST** (B1 probe, 4 Nov). Ingested by the 20:30 pass into `nse_fii_stats` (one row per instrument line: INDEX FUTURES, NIFTY FUTURES, INDEX OPTIONS, …); badge `context`.
- **Published:** Daily, evening · **History:** Recent files verified; 2010 naming differs
- **Key fields:** Index/stock futures and options: buy & sell contracts and value, OI contracts and value
- **How to use it:** A money-weighted view of FII positioning that complements participant OI.

### F&O turnover by client category
*Is F&O activity driven by retail, proprietary desks or foreign investors?*

- **Where on the site:** All Reports → Derivatives → Category-Wise Turnover
- **Get it:** `nsearchives.nseindia.com/archives/fo/cat/fo_cat_turnover_DDMMYY.xls`
- **Published:** Daily, evening · **History:** Recent files verified
- **Key fields:** Turnover by category (proprietary, FPI, retail, others)
- **How to use it:** Sentiment gauge: retail share of F&O turnover tends to rise into speculative phases.

### Institutional short selling
*Are institutions betting against the stock?*

- **Where on the site:** All Reports → Equities → Short Selling; Reports → Bulk & block deals → Short selling
- **Get it:** `nsearchives.nseindia.com/archives/equities/shortSelling/shortselling_DDMMYYYY.csv · history: www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=short_selling&from=&to=&csv=true`
- **Published:** Daily, evening · **History:** Recent years; a 2015 query returned nothing
- **Key fields:** Symbol, security name, trade date, quantity sold short
- **How to use it:** Bearish pressure. Repeated short sales in a rising stock can precede a failed breakout, or fuel a squeeze if the price keeps rising.


## Big-money footprints

Named large trades, insiders, stake changes, institutional flows

<a id="deals"></a>
### Bulk deals
*Which named investors bought or sold at least 0.5% of the company in a day?*

- **Where on the site:** Market Data → Large Deals / Reports → Bulk & block deals
- **Get it:** `Latest day: nsearchives.nseindia.com/content/equities/bulk.csv · history: www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from=DD-MM-YYYY&to=DD-MM-YYYY&csv=true`
- **Published:** Daily, evening · **History:** Back to 2005 (verified; 149 deals in Jan-2005)
- **Key fields:** Date, Symbol, Client Name, Buy/Sell, Quantity Traded, Trade Price / Wght. Avg. Price
- **How to use it:** Names the buyer (fund, insurer, FPI, promoter entity). Study drift after institutional buys vs sells; watch repeat buyers. Use the csv=true download: the JSON version silently stops at 70 rows.

### Block deals
*Which large negotiated trades crossed in the block window?*

- **Where on the site:** Market Data → Large Deals
- **Get it:** `Latest day: nsearchives.nseindia.com/content/equities/block.csv · history: …optionType=block_deals…&csv=true`
- **Published:** Daily, evening · **History:** Back to at least 2010 (verified)
- **Key fields:** Date, Symbol, Client Name, Buy/Sell, Quantity, Price
- **How to use it:** Stake transfers between big holders. A promoter or PE exit at a discount often weighs on the price for days.

<a id="insider"></a>
### Insider trading disclosures (SEBI PIT)
*Are promoters, directors or employees buying or selling their own stock?*

- **Where on the site:** Company page → Corporate Filings → Insider Trading
- **Get it:** `www.nseindia.com/api/corporates-pit?index=equities&symbol=SYMBOL (market-wide query returned empty; loop per stock)`
- **Published:** A few days after the trade (use intimation date) · **History:** Recent filings per stock
- **Key fields:** acqName, personCategory (Promoter/Director/KMP…), acqMode (market purchase, ESOP, pledge…), buy/sell quantity & value, holding % before/after, acqfromDt, intimDt
- **How to use it:** Promoter open-market purchases are a classic positive signal to test; ESOP sales are noise. Always date the signal by intimDt (when the public learned), not the trade date.

**Moved on 5 May 2026 (verified 12 Oct 2026):** `corporates-pit` has almost nothing after early May 2026 (3 rows in
May–June, none from July). NSE circular NSE/CML/2026/11 moved PIT Reg 7(2)/7(3) disclosures to the single-filing
system. The NSE website now calls **`www.nseindia.com/api/corporates-pit-gg?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`**.
It works market-wide; each row is one filing (appId, symbol, broadcastDateTime, xmlFileName), and the trades are
inside the XBRL file (`in-bse-co:` facts, one context per disclosure: NameOfThePerson, CategoryOfPerson,
SecuritiesAcquiredOrDisposedTransactionType, ModeOfAcquisitionOrDisposal, …). SuryaDhana parses them into
`nse_insider_trades` (record_id `gg|appId|context`, dated by the broadcast; `nse_filings.ingest_pit_gg`).
Also seen: the old feed has typo dates years ahead (DMART 2028); cap them at the broadcast date.

### Substantial acquisitions (SAST Reg 29)
*Is someone building or cutting a large stake?*

- **Where on the site:** Corporate Filings → SAST
- **Get it:** `www.nseindia.com/api/corporate-sast-reg29?index=equities`
- **Published:** As disclosed · **History:** Recent filings (285 rows market-wide)
- **Key fields:** acquirerName, promoterType, noOfShareAcq / Sale, holding after, acquisitionMode, dates
- **How to use it:** Stake building beyond 5% (and each further 2%) is disclosed here: a slower, larger-holder complement to bulk deals.

<a id="fii-dii"></a>
### FII/FPI and DII cash-market flows
*Did foreign and domestic institutions buy or sell equities today?*

- **Where on the site:** Market Data → FII/DII trading activity
- **Get it:** `www.nseindia.com/api/fiidiiTradeReact`
- **Published:** Daily, same evening (provisional) · **History:** Latest day only via this API: collect daily
- **Key fields:** category (FII/FPI, DII), buyValue, sellValue, netValue (₹ crore)
- **How to use it:** Market-level regime input. Persistent FII selling with DII absorption is a common Indian pattern; test as a filter, not a stock signal.


## Prices and volume

End-of-day prices, delivery history, valuation, volatility

<a id="cm-bhavcopy"></a>
### Equity bhavcopy (UDiFF standard)
*Official end-of-day prices for every listed security.*

- **Where on the site:** All Reports → Equities → CM-UDiFF Common Bhavcopy Final
- **Get it:** `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`
- **Published:** Daily, evening · **History:** Since Jul-2024 (older formats before)
- **Key fields:** TckrSymb, ISIN, SctySrs, OHLC, PrvsClsgPric, SttlmPric, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd
- **How to use it:** ISIN-keyed prices survive symbol changes (INFOSYSTCH → INFY in 2011).

### 52-week highs and lows
*Which stocks are near their 52-week extremes?*

- **Where on the site:** All Reports → Equities → 52 Week High Low Report
- **Get it:** `nsearchives.nseindia.com/content/CM_52_wk_High_low_DDMMYYYY.csv (first line is a disclaimer)`
- **Published:** Daily, evening · **History:** Recent files verified
- **Key fields:** Symbol, series, adjusted 52-week high and low with dates
- **How to use it:** Distance from the 52-week high is a well-studied momentum signal (George & Hwang). A breakout on rising delivery is the swing setup to test.

### Stock P/E ratios
*How expensive is the stock on trailing earnings?*

- **Where on the site:** All Reports → Equities → PE Ratio
- **Get it:** `nsearchives.nseindia.com/content/equities/peDetail/PE_DDMMYY.csv`
- **Published:** Daily, evening · **History:** Recent files verified
- **Key fields:** SYMBOL, SYMBOL P/E, ADJUSTED P/E
- **How to use it:** Valuation filter or tilt for the monthly portfolio (avoid momentum names at extreme P/E).

### Daily volatility per stock
*How volatile is the stock right now (as NSE's risk system sees it)?*

- **Where on the site:** All Reports → Equities → Daily Volatility
- **Get it:** `nsearchives.nseindia.com/archives/nsccl/volt/CMVOLT_DDMMYYYY.CSV`
- **Published:** Daily, evening · **History:** Recent files verified
- **Key fields:** Close, log return, EWMA daily volatility, annualised volatility
- **How to use it:** Position sizing (volatility targeting) and stop width, straight from NSE.

### Market activity report
*How did the whole market trade today?*

- **Where on the site:** All Reports → Equities → Market Activity Report
- **Get it:** `nsearchives.nseindia.com/archives/equities/mkt/MADDMMYY.csv`
- **Published:** Daily, evening · **History:** Recent files verified
- **Key fields:** Turnover, number of trades, advances/declines summary
- **How to use it:** Breadth and participation context.


## Derivatives detail

Option chains, contract data, settlement and margins inputs

<a id="option-chain"></a>
### Option chain (v3)
*Where are option writers positioned, and what is implied volatility?*

- **Where on the site:** Derivatives → Option Chain
- **Get it:** `www.nseindia.com/api/option-chain-contract-info?symbol=SYMBOL → www.nseindia.com/api/option-chain-v3?type=Indices|Equity&symbol=SYMBOL&expiry=DD-Mon-YYYY`
- **Published:** Live (not archived) · **History:** Now only: snapshot it daily to build history
- **Key fields:** per strike CE/PE: openInterest, changeinOpenInterest, impliedVolatility, lastPrice, bid/ask, totalTradedVolume, underlyingValue
- **How to use it:** Put/call ratio, largest-OI strikes (support/resistance), IV level and skew. The old /option-chain-indices endpoint now 404s.

### OI spurts
*Which F&O stocks had the biggest change in open interest today?*

- **Where on the site:** Market Data → Live Analysis → OI Spurts
- **Get it:** `www.nseindia.com/api/live-analysis-oi-spurts-underlyings`
- **Published:** Live during the day · **History:** Now only
- **Key fields:** symbol, latestOI, prevOI, changeInOI, volume, underlyingValue
- **How to use it:** A ready-made daily scan for long or short build-up candidates.

<a id="contract-delta"></a>
### Contract delta factors
*What delta does NSE's clearing use for each option?*

- **Where on the site:** All Reports → Derivatives → NCL Contract Delta
- **Get it:** `nsearchives.nseindia.com/content/nsccl/Contract_Delta_DDMMYYYY.csv`
- **Published:** Daily · **History:** Recent files verified
- **Verified (Nov 2026):** `Contract_Delta_03112026.csv` 200, `Last-Modified` **12:58 IST** (R-IV); `Contract_Delta_04112026.csv` measured 13:48 (B1) — published around midday for margins, between ≈ 13:00 and 19:20 on the days measured; 6.9 MB. Fetched by `iv_eod` inside the 20:30 pass (`fo_iv.jobs.EOD_FILES`) into `nse_contract_delta`.
- **Key fields:** Date, Symbol, Expiry day, Strike Price, Option Type, Delta Factor (futures rows = 1)
- **How to use it:** Delta-weight options OI yourself without a pricing model. In the terminal it is NSE's own delta beside ours on OMON / DERV (`context`); `iv_eod` logs any strike where |Δ_ours − Δ_NSE| > 0.05 as a model cross-check.

### Futures settlement prices
*Official daily mark-to-market price per future.*

- **Where on the site:** All Reports → Derivatives → Daily Settlement Prices
- **Get it:** `nsearchives.nseindia.com/archives/nsccl/sett/FOSett_prce_DDMMYYYY.csv`
- **Published:** Daily · **History:** Recent files verified
- **Key fields:** Instrument, underlying, expiry, MTM settlement price
- **How to use it:** Accurate futures P&L and basis history.

<a id="fovolt"></a>
### F&O daily volatility
*Volatility NSE uses for derivative margins.*

- **Where on the site:** All Reports → Derivatives → Daily Volatility
- **Get it:** `nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_DDMMYYYY.csv`
- **Published:** Daily · **History:** Recent files verified
- **Verified (Nov 2026):** `FOVOLT_04112026.csv` `Last-Modified` **17:01 IST**, `FOVOLT_03112026.csv` 11:28 IST (14,907 B): published between late morning and ≈ 17:05. Fetched by `iv_eod` inside the 20:30 pass into `nse_fo_volt`; `fovolt_ann` is the third realised-vol line on OMON / DERV (`context`).
- **Key fields:** per underlying: close, previous close, log return, **EWMA daily volatility (λ = 0.995)**, annualised (× √365), and the same for the current-month future. NSE's header carries the formulas as column names, so the parser is positional.
- **How to use it:** Margin-aware sizing for futures hedges; the exchange's own realised-vol estimate to set beside IV (IV − FOVOLT is a volatility risk premium, a description, never a direction).

<a id="span"></a>
### SPAN risk-parameter file
*What margin does the clearing corporation actually charge for a position?*

- **Where on the site:** All Reports → Derivatives → SPAN risk parameter files (NSE Clearing)
- **Get it:** `nsearchives.nseindia.com/archives/nsccl/span/nsccl.YYYYMMDD.s.zip` (end of day; NCL also publishes intraday files whose names were not probed — do not cite them)
- **Published:** Daily, ≈ 17:00 · **History:** Recent files
- **Verified (Nov 2026):** `nsccl.20261104.s.zip` answered **206 Partial** to a range GET, `application/zip`, `Last-Modified` **17:02 IST** (R-OPTIONS §4). Breeze's `margin_calculator(legs, "NFO")` returned real SPAN for the same legs: a NIFTY 09-Nov-2026 iron condor ₹81,497.07, a lone short 23700 PE ₹1,72,460.67, against ₹3.9 L from the old 12 %-of-notional heuristic (**4.8× too high**).
- **Key fields:** the SPAN risk arrays per contract (16 price/vol scenarios), the calendar-spread charge, the short-option minimum, exposure (non-SPAN) margin rates
- **How to use it:** Real margin for an options structure when the broker session is down. In the terminal `POST /api/options/margin` tries Breeze (through the budget ledger) → this file parsed offline from `data/nse_archive/span/` (`SPAN_ARCHIVE_DIR`) → the heuristic last, with its measured 4.8× error printed; the ticket shows `span_margin_required`, `non_span_margin_required` and a source chip BREEZE / NSE SPAN FILE / HEURISTIC. Badge `arithmetic`. **Fetch status:** the parser and the fallback chain are in the tree; no scheduled job downloads this file yet (the 20:30 pass does not include it) — place a file by hand or wait for the fetch step.

<a id="lot-sizes"></a>
### F&O lot sizes
*How many shares per contract for each expiry?*

- **Where on the site:** Derivatives → Lot sizes
- **Get it:** `nsearchives.nseindia.com/content/fo/fo_mktlots.csv`
- **Published:** When changed · **History:** Current
- **Key fields:** Underlying, symbol, lot size by expiry month
- **How to use it:** Needed to convert OI in contracts to shares and to size hedges.

### Top-10 clearing members
*How concentrated is F&O volume among clearing members?*

- **Where on the site:** All Reports → Derivatives → Top 10 Clearing Member Volumes
- **Get it:** `nsearchives.nseindia.com/content/nsccl/fao_top10cm_to_DDMMYYYY.csv`
- **Published:** Daily · **History:** Recent files verified
- **Key fields:** Volume and turnover of the top 10 clearing members
- **How to use it:** Market structure context; rarely a trading signal.

### Most active stock futures
*Which futures are trading heaviest right now?*

- **Where on the site:** Market Data → Derivatives → Most active
- **Get it:** `www.nseindia.com/api/liveEquity-derivatives?index=stock_fut`
- **Published:** Live · **History:** Now only
- **Key fields:** contract, expiry, lastPrice, volume, value, openInterest, underlyingValue
- **How to use it:** Attention and liquidity scan.


## Risk and surveillance filters

What to avoid: surveillance flags, bans, circuit bands

<a id="surveillance"></a>
### Surveillance indicators
*Is the stock under ASM, GSM, ESM, insolvency or other surveillance?*

- **Where on the site:** All Reports → Equities → Surveillance Indicator (New)
- **Get it:** `nsearchives.nseindia.com/content/cm/REG1_INDDDMMYY.csv`
- **Published:** Daily · **History:** Recent files verified
- **Key fields:** Symbol, GSM stage, long/short-term ASM, IRP (insolvency), default, pledge and other flags
- **How to use it:** Hard exclusion list for swing trades: surveillance brings higher margins, trade-to-trade settlement and thin liquidity.

### ASM and GSM lists
*Which stocks are under additional or graded surveillance, and at which stage?*

- **Where on the site:** Surveillance → ASM / GSM
- **Get it:** `www.nseindia.com/api/reportASM · www.nseindia.com/api/reportGSM`
- **Published:** Daily · **History:** Current
- **Key fields:** symbol, stage, survCode, survDesc
- **How to use it:** Same use as above, with the stage (stricter stages mean worse liquidity).

<a id="ban-list"></a>
### F&O ban list
*Which stocks crossed 95% of their F&O limit (no new positions)?*

- **Where on the site:** All Reports → Derivatives → Security in ban period
- **Get it:** `nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_DDMMYYYY.csv (named for the next trade date)`
- **Published:** Daily, evening · **History:** Recent files verified
- **Key fields:** List of symbols
- **How to use it:** Entering and leaving the ban are volatile events; avoid fresh swing entries around them.

### Price bands and changes
*How far can the stock move in a day (circuit limit)?*

- **Where on the site:** All Reports → Equities → Price Band complete list / Price Band changes
- **Get it:** `nsearchives.nseindia.com/content/equities/sec_list_DDMMYYYY.csv · nsearchives.nseindia.com/content/equities/eq_band_changes_DDMMYYYY.csv`
- **Published:** Daily · **History:** Recent files verified
- **Key fields:** Symbol, series, band (2/5/10/20% or none); band changes effective next day
- **How to use it:** A 2–5% band can trap you in a circuit; a band cut is an NSE caution sign.

### Series changes
*Did the stock move to trade-to-trade (BE/BZ) settlement?*

- **Where on the site:** All Reports → Equities → Latest change
- **Get it:** `nsearchives.nseindia.com/content/equities/series_change.csv`
- **Published:** As changed · **History:** Recent
- **Key fields:** Symbol, from series, to series, change date
- **How to use it:** EQ → BE/BZ removes intraday trading and usually hurts liquidity: exclude.

### Circuit hitters (live)
*Which stocks are locked at upper or lower circuit now?*

- **Where on the site:** Market Data → Live Analysis → Price band hitters
- **Get it:** `www.nseindia.com/api/live-analysis-price-band-hitter`
- **Published:** Live · **History:** Now only
- **Key fields:** upper, lower, both, count
- **How to use it:** Avoid chasing locked circuits: you often cannot exit (the lesson from the rejected circuit-rebound study).


## Company events and news

Filings, results, board meetings, corporate actions, IPOs

### Corporate announcements (news feed)
*What did the company just disclose?*

- **Where on the site:** Company page → Corporate Filings → Announcements; market-wide feed
- **Get it:** `www.nseindia.com/api/corporate-announcements?index=equities[&symbol=SYMBOL]`
- **Published:** Real time, timestamped · **History:** INFY back to Sep-2004: 2,927 filings (verified)
- **Key fields:** an_dt / exchdisstime (timestamp), desc (subject), attchmntText (summary), attchmntFile (PDF), hasXbrl, smIndustry
- **How to use it:** The official news stream. Classify filings (orders, results, M&A, management change, fund raise, litigation) with an LLM, then measure post-event drift per type. Timestamps make it point-in-time.

<a id="results"></a>
### Financial results filings
*What were the latest quarterly numbers?*

- **Where on the site:** Company page → Financial Results
- **Get it:** `www.nseindia.com/api/corporates-financial-results?index=equities&symbol=SYMBOL&period=Quarterly`
- **Published:** Quarterly · **History:** 144 filings for INFY
- **Key fields:** period, fromDate/toDate, audited, consolidated, filingDate, XBRL detail link
- **How to use it:** Earnings surprise and post-earnings drift research; revenue/profit growth screens.
- **Trap (verified 2026-10-11):** this feed stops in **early 2025** (TCS, HDFCBANK and CUPID all end Jan/Feb 2025).
  Newer quarters are only in the integrated filing below. Use both for a complete history.

### Integrated filing: financials (results from April 2025)
*SEBI's combined quarterly filing; where results live now.*

- **Get it:** `www.nseindia.com/api/integrated-filing-results?index=equities&symbol=SYMBOL`
- **Published:** Quarterly · **History:** April 2025 → today (20 filings for TCS: standalone + consolidated)
- **Key fields:** broadcast_Date (exact release time), qe_Date (quarter end), audited, consolidated, ixbrl, pdf_attach
- **How to use it:** The release timestamp separates pre-open, in-market and after-close results, so you
  can find the correct reaction session. SuryaDhana stores the earliest broadcast per quarter in `nse_results`
  (`services/data-service/results_history.py`).

### Board meetings
*When are results, dividends or fund-raising decided?*

- **Where on the site:** Company page → Board Meetings
- **Get it:** `www.nseindia.com/api/corporate-board-meetings?index=equities&symbol=SYMBOL`
- **Published:** As announced · **History:** Recent history
- **Key fields:** bm_date, bm_purpose, bm_desc, attachment
- **How to use it:** Know the results date: either avoid holding a swing trade through it or trade the post-result drift.

<a id="events"></a>
### Event calendar
*Which companies have events coming up?*

- **Where on the site:** Corporate Filings → Event Calendar
- **Get it:** `www.nseindia.com/api/event-calendar?index=equities`
- **Published:** Forward-looking · **History:** Upcoming (87 events)
- **Key fields:** symbol, company, purpose, date
- **How to use it:** A weekly pre-trade check across your watchlist.

### Corporate actions
*Dividends, bonus, splits, rights: when and how much?*

- **Where on the site:** Corporate Filings → Corporate Actions
- **Get it:** `www.nseindia.com/api/corporates-corporateActions?index=equities[&symbol=SYMBOL]`
- **Published:** As announced · **History:** Per-stock history
- **Key fields:** subject (e.g. dividend ₹), exDate, recDate, bcStart/End, faceVal
- **How to use it:** Price adjustment for backtests and ex-date effects; complements SuryaDhana's corporate-action factors.

### Annual reports
*Where is the full annual report?*

- **Where on the site:** Company page → Annual Reports
- **Get it:** `www.nseindia.com/api/annual-reports?index=equities&symbol=SYMBOL`
- **Published:** Yearly · **History:** 17 reports for INFY
- **Key fields:** fromYr, toYr, fileName (PDF), dissemination time
- **How to use it:** Input for deeper LLM reading (risks, guidance, related-party items).

### IPOs and subscription
*What is listing, and how heavily was each investor category subscribed?*

- **Where on the site:** Market Data → IPO
- **Get it:** `www.nseindia.com/api/ipo-current-issue`
- **Published:** During issue · **History:** Current issues
- **Key fields:** companyName, issue dates, price band, size, category, noOfTime (times subscribed)
- **How to use it:** Listing-day and post-listing drift research by subscription level.


## Indices and market regime

Index levels, valuations, breadth, VIX

<a id="ind-close-all"></a>
### All indices with valuation and breadth
*Where is each index, how expensive, how broad is the move?*

- **Where on the site:** Market Data → Indices
- **Get it:** `www.nseindia.com/api/allIndices · daily file nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv`
- **Published:** Live / daily · **History:** Daily file for history
- **Verified (Nov 2026):** `ind_close_all_03112026.csv` 200 · 7,394 B · `Last-Modified` **17:50 IST**; columns Index Name, Index Date, Open/High/Low/Closing Index Value, Points Change, Change(%), Volume, Turnover, P/E, P/B, Div Yield — one row per index **including India VIX**. One GET in the 19:15 `index_valuation_daily` job and in `iv_eod`; it feeds `index_ohlc_daily` (every index OHLC: the Parkinson / Yang-Zhang inputs and the index level `L` for the drivers), `vix_daily` (OHLC) and `market_index_daily` (`source = nse_daily_file`; readers prefer it over the Yahoo rows). Whether it also replaces the NIFTY series under the crash filter is O-T9 ("DO NOT CHANGE without review").
- **Key fields:** index, last, change, P/E, P/B, dividend yield, advances, declines, 30-day & 365-day change (INDIA VIX included)
- **How to use it:** Regime inputs: NIFTY P/E, breadth and India VIX for sizing and for the crash filter.

<a id="vix"></a>
### India VIX history
*What did implied volatility do over the years, as NSE itself measures it?*

- **Where on the site:** Market Data → India VIX → Historical data
- **Get it:** `www.nseindia.com/api/historicalOR/vixhistory?from=DD-MM-YYYY&to=DD-MM-YYYY` (cookie-primed session, browser UA; **≤ 1 year per call**, so page it; paced 2 s) · the daily close also sits in the `ind_close_all` file above
- **Published:** Daily after close · **History:** 2014 → today (verified ranges in 2026)
- **Verified (Nov 2026):** 200 with the site cookie (R-IV; `R-IV/nse_probes.json`); the older `api/historical/vixhistory` path answered **503** on 4 Nov (R-WORLD) — use `historicalOR`. One-off backfill job `vix_backfill` (`POST :8001/jobs/iv-eod?job=vix_backfill`) writes `vix_daily` with `source = nse_vixhistory`; the nightly rows come from the daily file (`source = nse_daily_file`).
- **Key fields:** EOD_TIMESTAMP, EOD_OPEN/HIGH/LOW/CLOSE_INDEX_VAL, EOD_PREV_CLOSE, VIX_PTS_CHG, VIX_PERC_CHG
- **How to use it:** The only *published* IV history for India. In the terminal `vix_daily` is the one source of the VIX everywhere (DERV header strip, the overlay on the IV chart); India VIX is a model-free 30-day variance strip over the OTM wings, so it sits ≈ 1 vol-pt above our ATM `iv30_cm` (the skew term) and both move together (corr 0.978 since Jul 2024). Badge `context`.

<a id="constituents"></a>
### Index constituents
*Which stocks are in NIFTY 50, Next 50, 500…?*

- **Where on the site:** niftyindices.com → Index constituents
- **Get it:** `niftyindices.com/IndexConstituent/ind_nifty50list.csv (and similar per index)`
- **Published:** When the index changes · **History:** Current list
- **Verified (Nov 2026):** `ind_nifty50list.csv` 200 · 3,344 B · 50 rows; `ind_niftybanklist.csv` 200 · 916 B · **14 rows** (the 12-vs-14 member count is owner decision O-T13). Reconstitutions are semi-annual (effective the last trading day of Mar / Sep) plus ad-hoc changes, so the terminal archives both lists daily (2 conditional GETs in the 19:25 `index_drivers_daily` job) into `index_constituents_daily`; members as of today are applied before the first archived list and the page says so. Posture: display with attribution, never re-served (O-T11).
- **Key fields:** Company Name, Industry, Symbol, Series, ISIN
- **How to use it:** Universe definition and sector mapping; index inclusion/exclusion events are a studied effect.

<a id="top10"></a>
### NIFTY 50 top-10 weights
*Which stocks dominate the index?*

- **Where on the site:** All Reports → Indices → NIFTY 50 Top 10 Holdings
- **Get it:** `nsearchives.nseindia.com/content/indices/top10nifty50_DDMMYY.csv` (note the two-digit year: `top10nifty50_041126.csv`)
- **Published:** Daily · **History:** Recent
- **Verified (Nov 2026):** 200 · 370 B · text/csv on 4 Nov (HDFCBANK 10.20, ICICIBANK 9.22, RELIANCE 7.91, BHARTIARTL 5.68, LT 4.17, SBIN 3.65, INFY 3.60, AXISBANK 3.20, KOTAKBANK 3.05, BAJFINANCE 2.45; Σ 53.13 %). Present by 22:18; the exact publication minute is not yet measured, so the 19:25 job reads it and the 20:30 pass retries at 20:35. NSE publishes **no full daily weight file** for free; this is the only official daily weight anchor.
- **Key fields:** SYMBOL, SECURITY, WEIGHTAGE(%)
- **How to use it:** Concentration context for index hedges. In the terminal it calibrates the rebuilt point-in-time weights (`index_weights_daily.method = rebuilt_calibrated`, `iwf_correction = official ÷ rebuilt` on the ten names, the other forty pro rata; the fit explains 99.6 % of daily variance, MAE 9.4 pts/day over 229 sessions). Display-only with attribution (O-T11).

### Market status and GIFT Nifty
*Is the market open, and where is GIFT Nifty indicating?*

- **Where on the site:** Homepage ticker
- **Get it:** `www.nseindia.com/api/marketStatus`
- **Published:** Live · **History:** Now only
- **Key fields:** marketState[], marketcap, indicativenifty50, giftnifty
- **How to use it:** Pre-market read of the open for next-open orders.


## Intraday snapshots

Pre-open, movers, new highs (live only, not archived)

<a id="preopen"></a>
### Pre-open session
*Where will each stock open, and is buying or selling heavier?*

- **Where on the site:** Market Data → Pre-Open Market
- **Get it:** `www.nseindia.com/api/market-data-pre-open?key=ALL (or key=FO, NIFTY)`
- **Published:** 09:00–09:08 IST, then frozen for the day · **History:** Now only: snapshot daily
- **Now archived (12 Oct 2026):** the 09:09 `preopen_capture` job saves each session's final book to `data/nse_archive/preopen/<date>_<key>.json`; terminal page PRE. Trap: `key=NIFTY`/`BANKNIFTY` return `No Data Found` between sessions, while `FO`/`ALL` keep the last book. Buy/sell quantities after 09:08 are the orders left unmatched at the IEP.
- **Key fields:** per stock: indicative equilibrium price, change %, final quantity, total buy & sell quantity
- **How to use it:** The Decision Desk buys at the open: the pre-open imbalance tells you the likely gap before you commit.

<a id="internals"></a>
### Intraday breadth samples (market internals)
*How broad is the move while the session runs?*

- **Where on the site:** Market Data → Indices (the live `allIndices` payload: advances, declines, segment moves)
- **Get it:** `www.nseindia.com/api/allIndices` sampled every 2 minutes 09:00–15:58 by the controller's `internals_sample` job (`POST :8001/db/internals/sample`), archived per day under `data/nse_archive/internals/`
- **Published:** Live only · **History:** Only what the terminal sampled (since Oct 2026; sessions the stack was down are lost for good)
- **How to use it:** MOV / WRAP breadth and the within-day index map. A session with no samples is written as an explicit gap row (`data_gaps`) so the pages say "no intraday data for 2–4 Nov" instead of showing the last day with data. Badge `context`.

### Gainers, losers, most active
*What is moving and trading most right now?*

- **Where on the site:** Market Data → Live Analysis
- **Get it:** `www.nseindia.com/api/live-analysis-variations?index=gainers|loosers · www.nseindia.com/api/live-analysis-most-active-securities?index=value|volume`
- **Published:** Live · **History:** Now only
- **Key fields:** symbol, lastPrice, pChange, volume, value, yearHigh/Low
- **How to use it:** Attention scans; not a signal on their own.

### New 52-week highs today
*Which stocks broke to a new 52-week high this session?*

- **Where on the site:** Market Data → Live Analysis → 52 Week High
- **Get it:** `www.nseindia.com/api/live-analysis-data-52weekhighstock`
- **Published:** Live · **History:** Now only (daily file for history)
- **Key fields:** symbol, ltp, new52WHL, prev52WHL, prevHLDate
- **How to use it:** Breakout watchlist; confirm with delivery the same evening.


## Reference data

Security master, holidays, lot sizes, the report index itself

### The All Reports index
*Which files did NSE publish today, and at what URL?*

- **Where on the site:** Market Data → All Reports
- **Get it:** `www.nseindia.com/api/daily-reports?key=CM|FO|INDEX|CD|COM|WDM|NBF (PreviousDay = full evening set)`
- **Published:** Daily · **History:** Current and previous day
- **Key fields:** displayName, fileActlName, filePath
- **How to use it:** Build the download job from this list instead of hard-coding names: NSE renames files over time.

### Security master
*Every listed security with ISIN, series, lot, face value, book closure.*

- **Where on the site:** All Reports → Equities → CM - MII - Security File
- **Get it:** `nsearchives.nseindia.com/content/cm/NSE_CM_security_DDMMYYYY.csv.gz`
- **Published:** Daily · **History:** Current
- **Key fields:** FinInstrmId, TckrSymb, SctySrs, ISIN, ParVal, BookClsrStartDt/EndDt, PricRg…
- **How to use it:** Symbol↔ISIN mapping and trading eligibility.

<a id="holidays"></a>
### Trading holidays
*Which days is each segment closed?*

- **Where on the site:** Resources → Holidays
- **Get it:** `www.nseindia.com/api/holiday-master?type=trading`
- **Published:** Yearly · **History:** Current year
- **Key fields:** tradingDate, weekDay, description, per segment
- **How to use it:** Calendar for schedulers and expiry shifts.

<a id="yahoo"></a>
### Non-NSE sources the terminal catalog anchors here

- **Yahoo Finance daily bars (`ohlcv`, 1,496 tickers):** the existing nightly refresh through the app's single cached fetcher stays; **no new Yahoo caller** may be added anywhere (CLAUDE.md anti-pattern; PLAN §0.7), and the Yahoo leg under `/db/market-monitor`'s lock is being replaced by the `ind_close_all` row stored nightly. Yahoo rows in `market_index_daily` are kept as a second source; readers prefer `nse_daily_file`.
- **ICICI Breeze (read-only):** option chain quotes (60 strikes/side, 26 fields, **no IV, no Greeks**), option history (`get_historical_data_v2`, 1-minute / 1-day, expired contracts served back to 2020; daily close = last trade, so never the EOD source), `margin_calculator`. Every call passes through `shared/breeze_budget.py` (100/min · 5,000/day documented ceiling; the owner's cap O-T6 is the budget) and only when a session is live. Own-account use, no redistribution.

## When each dataset becomes public (avoid look-ahead)

| Dataset | Published | Earliest you can act |
|---|---|---|
| Corporate announcements | Real time, with a dissemination timestamp | Use exchdisstime as the signal time |
| Pre-open | 09:00–09:08 IST | Usable the same morning |
| FII/DII cash flows | Same evening (provisional) | Next session |
| Bhavcopy, delivery, bulk/block, short selling, F&O bhavcopy, participant OI, combined OI, ban list | Evening after the close | Next session's open at the earliest |
| Margin trading (MTF), clients ≥3% MWPL | Next day (T+1) | Two sessions after the positions |
| **Measured (HTTP `Last-Modified`, IST, 3–4 Nov 2026):** FOVOLT 11:28 / 17:01 · Contract_Delta 12:58 / 13:48 · clients ≥3% MWPL 12:50 (T−1) · participant volumes and FII stats 14:40 · SPAN file 17:02 · `ind_close_all` 17:50 · combined OI (MWPL zip) 19:23 · ban list 19:24 (named for the next session) · **F&O bhavcopy and participant OI 20:10** · **equity bhavcopy re-published 22:05** · **MTF 22:12 for T−1** · top-10 weights present by 22:18 (minute unmeasured) | the terminal's schedule follows this clock: 18:30 equity-only, 20:30 F&O pass (+ `iv_eod` last, 20:35 drivers retry), 22:45 late files and revisions, 08:35 sweep | a dataset stored before its re-publication is a revision row in `ingest_log`, never an overwrite |
| Insider trades (PIT) | A few days after the trade | Use the intimation date, never the trade date |
| Shareholding pattern | Within 21 days of quarter end | Use the broadcast date |
| Financial results | Within 45 days of quarter end (60 for Q4) | Use the filing timestamp |

## Traps

1. The history JSON for bulk, block and short deals stops at 70 rows, even for one day. Add &csv=true: 25-Sep-2026 had 237 bulk deals and September had 3,677.
2. Some files are dated one day behind (MTF, clients ≥3% MWPL); the ban list is named for the next trading day.
3. Formats changed in July 2024 (UDiFF bhavcopies). Old and new files need different parsers.
4. Symbols change (Infosys was INFOSYSTCH before 2011). Key everything by ISIN.
5. Newer shareholding XBRL files store percentages as fractions (0.27 = 27%); older ones use percent (31.91).
6. The 52-week file starts with a disclaimer line; the participant OI file with a title line.
7. NSE expects a browser User-Agent and throttles fast clients: pace at about one request a second.
8. Live-only pages (pre-open, option chain, OI spurts, movers) are not archived. If you want their history, snapshot them daily.
9. The equity bhavcopy is re-published late in the evening (22:05 on 4 Nov 2026) after the first copy: re-fetch with `If-Modified-Since` and keep revisions as new rows (`ingest_log`), or your "official" close may be the first draft.
10. `historicalOR/vixhistory` serves at most one year per call and needs the site cookie; the older `api/historical/vixhistory` path answers 503.
11. The top-10 weights file name uses a two-digit year (`top10nifty50_041126.csv`); every other daily file uses `DDMMYYYY`.
12. In the F&O bhavcopy an untraded strike's `SttlmPric` is NSE's theoretical value: computing IV from it feeds the exchange's model back as "market" IV. Use `ClsPric` only when `TtlTradgVol > 0`. Expiry calendars change (NIFTY: Thursday → Tuesday in Sep 2025 → other days in 2026): read expiries from the file, never assume a weekday.
13. Breeze's daily option close is the last trade (198.00 vs NSE's 193.20 `ClsPric` on 3 Nov 2026) and its OI / volume are different snapshots and units (10,408,970 units = 160,138 contracts × 65): never mix Breeze bars with NSE files in one series.
14. NSE's F&O volatility files annualise with √365, the IV store's realised vols with √252: label the convention next to the number.

## Not available for free, or blocked

| What | Where | Status | Use instead |
|---|---|---|---|
| Live quote & trade-info pages | `www.nseindia.com/api/quote-equity` | Blocked for scripts and headless Chrome (Akamai). | Delivery, prices and metadata come from the bhavcopy, MTO file and security master. |
| Derivative quote page | `www.nseindia.com/api/quote-derivative` | Returns 404 (moved). | F&O bhavcopy + option chain v3 (+ ICICI Breeze for intraday). |
| Old option-chain endpoints | `www.nseindia.com/api/option-chain-indices / -equities` | 404 / empty since the v3 change. | Use option-chain-v3. |
| Market-wide insider query | `www.nseindia.com/api/corporates-pit?index=equities&from_date…` | Returns empty (re-verified 4 Nov 2026: `{"acqNameList":[],"data":[]}`). | Query per stock (works; the Saturday job uses it). |
| Per-constituent live weights / free-float cap | `www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050` (once carried `ffmc`) | **404**, also through the project's warmed `NseLive` session (4 Nov 2026). Dead — DO NOT USE. | The daily top-10 weights file + weights rebuilt from XBRL shares and shareholding, calibrated to it (`index_weights_daily`). |
| Full daily index weights / IWF, official bank cap factors | NSE Indices data products | Paid. | Not needed: the free top-10 file calibrates the rebuild to 99.6 % of daily variance; NIFTY Bank capping (33 % / 62 %) is approximate until O-T13. |
| Raw IV history for NSE options | Bloomberg OVDV, ORATS, IVolatility, Sensibull / Opstra / Quantsapp charts | Paid, or no storage rights; none sells raw NSE IV history at retail terms. | Compute it from the stored F&O bhavcopies (`iv_eod`): corr 0.998 vs the product's ATM IV, 0.983 vs India VIX. |
| Tick-by-tick trades | `NSE Data & Analytics` | Paid (₹1.1 lakh/year per segment). | Approximate from Breeze 1-second bars. |

## Research playbook

### One or two trades a week

- **Universe:** Liquid EQ-series stocks. Drop anything flagged in the surveillance file, in the F&O ban, moved to BE/BZ, or with a high promoter pledge.
- **Trend:** Close above its 50-day average and within about 10% of the 52-week high.
- **Conviction score:** Tested 28-Sep-2026 (H1–H6). Keep as positives: a promoter, director or KMP open-market purchase of at least ₹10 lakh in the last 30 days (H4, the strongest candidate; fresh first buys are tracked forward as H4b) · a mutual-fund or insurer bulk-deal buy (H3, right sign, not yet significant). Dropped: delivery surge (H1) and futures long build-up (H2) added nothing over plain price momentum; quarterly ownership drift (H6) was mostly results-season timing.
- **Warnings:** Skip stocks that a non-institutional client net-bought through a bulk deal in the last 20 sessions (H3: −2.2% / −1.2% vs random over 20 days). A spike in MTF-financed quantity near the high did not predict drops (H5), so it is context only. Skip names with results in the next five sessions.
- **Regime dial:** When FIIs are heavily net short index futures (participant OI) and breadth is weak, halve size or wait.
- **Execution:** Pick the top one or two on Friday evening; check the pre-open imbalance before the Monday open; exit on a trend break or a time stop. Costs are about 0.9% per round trip, so a setup needs an expected move well above 2%.

### One or two trades a month (Decision Desk)

- The approved Decision Desk rules stay as they are unless you review a change. These datasets are candidates to test as filters, not replacements.
- Tested filter: skip new entries in stocks a non-institutional client net-bought through a bulk deal in the last 20 sessions. Backtest Nov-2019 → Sep-2026 on the approved rules: CAGR 18.52% → 18.72%, worst drawdown −13.75% → −12.40%; holdout 3.87% → 3.95%, −7.91% → −7.65%. Built into the Desk but OFF (DESK_AVOID_BULK_BUY_DAYS=0) until the owner reviews it.
- Still to test on the monthly picks: exclude surveillance-flagged and heavily pledged names. (MTF leverage spikes and delivery accumulation were tested as swing signals and showed nothing.)
- A market-level risk dial to test alongside the NIFTY 200-day crash filter: FII net index-futures position and India VIX.

### Hypotheses and results

| Hypothesis | Claim | Data | Result |
|---|---|---|---|
| H1 · Delivery accumulation | Stocks in the top decile of 5-day delivery-volume surge with a positive 20-day return outperform over the next 5 and 20 sessions, after costs. | Delivery (bhavcopy/MTO), prices | Tested 28-Sep-2026: no edge (−0.28% vs random over 5 days in 2024–26). |
| H2 · Long build-up vs short covering | Among F&O stocks, a price rise with rising OI continues over 1–2 weeks; a rise with falling OI (short covering) does not. | F&O bhavcopy, combined OI | Tested: no edge, unstable between periods. |
| H3 · Named institutional buying | Bulk-deal buys by mutual funds, insurers and FPIs are followed by positive 20-day drift; sells by promoters or PE by negative drift. | Bulk & block deals | Tested: MF/insurer buys +1.0% / +1.3% vs random over 20 days (not yet significant). Buys by others −2.2% / −1.2% (t −2.5 / −2.0 after the overlap correction, borderline in 2024–26): used as the candidate avoid filter. |
| H4 · Insider purchases | Promoter, director or KMP open-market purchases of at least ₹10 lakh (dated by intimation) are followed by positive drift; insider sales carry no signal. | Insider trading (PIT) | Tested: buys +1.0% / +2.6% vs random over 20 days and +4.4% / +2.7% over 60 days (2019–23 / 2024–26), positive in every cut and ahead of insider sales in the same weeks, but the holdout is not yet significant (Newey-West t 1.7 / 0.9). Strongest candidate: fresh first buys (H4b) are tracked forward from Oct-2026. Sales: no signal. |
| H5 · Leverage crowding | A sharp rise in MTF-financed quantity near a 52-week high raises the chance of a sharp drop over the next month. | MTF disclosure, 52-week file | Tested (2022–26): no edge. MTF-surge names did no worse than names near the high with ordinary MTF growth, and their share of ≥ 10% drops was the same. |
| H6 · Ownership drift | Falling shareholder count with rising FPI + MF holding predicts outperformance after the filing; a retail surge with FPI + MF exits predicts underperformance. | Shareholding XBRL | Tested (2022–26): no edge. Accumulation beat random picks (+1.2% / +2.6% over 20 days) but only by +0.6% / +0.5% (t 0.3–0.4) against other stocks filing in the same weeks, so the gain is mostly results-season timing. Distribution did not lag. |
| H7 · News drift | Specific filing types (large orders, capacity expansion, management exits, fund-raises) show post-announcement drift after LLM classification. | Corporate announcements | Not tested yet |

Full results: `reports/held_overnight/FINDINGS.md`.

### Method

- Point in time: date every signal by when it became public (see the timing table), trade at the next open.
- Costs: use shared/trading_costs.py (≈0.93% + ₹24 per round trip on the default plan; ICICI's own preview suggests brokerage is a little lower).
- Baselines: compare with random entries on the same dates and in the same liquidity bucket, as the earlier value-area and idea-lab studies did.
- Validation: pre-register the rule, split discovery and holdout periods, use week-clustered t-statistics with a Newey-West correction for overlapping holding windows, and a deflated Sharpe ratio for the number of variants tried.
- Expect most ideas to fail after costs, as most did in this project's earlier studies. Only survivors graduate to paper trading.

## Rerun the probe

    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/nse_free_data_catalog.py --symbol RELIANCE

The Terminal v2 rows above were verified by the research agents' paced probes on 4–5 Nov 2026 (evidence files named in the header). Every fetcher in the stack now goes through `shared/http_client.py` (`PacedClient`: host allowlist, ≥ 1.2 s between requests to one host, 20 s timeout, browser UA for NSE, a 600 s breaker after a 403/429 from an NSE host); `tests/test_hosts_allowlist_terminal.py` and `tests/arch/test_hosts_allowlist_shared.py` scan the sources for any other host. The per-dataset view the terminal itself renders (publisher, cadence, `expected_by`, ingest job, badge, verdict) is `docs/TERMINAL_DATA_DICTIONARY.md`, generated from `dataset_catalog` by `scripts/terminal_data_dictionary.py` (`--check` runs in the test suites).
