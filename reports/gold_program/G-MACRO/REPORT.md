# G-MACRO research report (materialised from the agent's structured result, 26 Oct 2026)

# G-MACRO — Macro drivers of the gold price: sources, evidence, verdicts

NOTE ON THE REPORT FILE: the harness Write guard refused to create REPORT.md ("Subagents should return findings as text"), and I did not bypass it. This `summary` IS the long-form report. Evidence on disk in /Users/sudheer/MahaKubera_108/SuryaDhana_AI/reports/gold_program/G-MACRO/: verify_sources.py (117 live checks), verify_extra.py, fetch_yahoo_daily.py, g_study.py (pre-registered), build_tables.py, verification.json / verification_extra.json / verification_pass3*.json / verification_yahoo_daily.json, sources_verified.md (149-row table), study.json, tables/*.csv, data/*.csv (every history used), samples/ (raw bodies), *.log. The orchestrator may save this summary as REPORT.md there. Run: Monday 26 Oct 2026 05:40–07:30 IST, before the 07:45 freeze; no local service, Telegram or ICICI call was made. `FRED_API_KEY` and `EIA_API_KEY` are NOT set in .env (count 0; both only in .env.example).

## 0. For both readers
New reader: gold pays nothing, so its dollar price is mostly a vote on (1) what a safe dollar investment pays after inflation — the REAL YIELD (up = bad for gold), (2) the DOLLAR (weaker = good for gold), (3) fear and policy (wars, central banks, inflation scares). Every number here measures one of those. Pro: 39 sources verified live (HTTP status, latency, fields, latest date), 14 derived metrics, a pre-registered study H1–H5 on 6,049 daily observations 2003→2026 (all numbers are ours, not quoted).

### One-page verdicts
| Driver / source | Answers | Our evidence | In app today | Verdict |
|---|---|---|---|---|
| 10y real yield (Treasury CSV; FRED DFII10) | cost of holding gold | 2010–21 weekly beta −9.9 %/100 bp (t −12); 2022–26 −5.0 (t −4); level fit sign-flipped | GoldPreOpen: one number | PUBLISH-CORE (history, 5y/30y, health flag) |
| DXY (Yahoo DX-Y.NYB) | gold or dollar? | weekly beta ≈ −1.0 in every regime (t −12/−13/−6) | WEI + GoldPreOpen | PUBLISH-CORE only as input to the KGX bar; no third tile |
| KGX-style decomposition (computed) | how much of today was the dollar | Thu 22 Oct: −2.18 % = pure −2.29 % + USD +0.10 % | no | PUBLISH-CORE |
| Gold in INR/EUR/JPY/CNY/GBP (computed) | what MY gold did; China/India price | YTD USD −7.8 %, INR −2.5 %, CNY −12.2 %; 1y USD −3.3 %, INR +4.6 % | no (MCXG: landed ₹ only) | PUBLISH-CORE |
| 2y Treasury (Treasury CSV / DGS2) | where the Fed is going | nominal split t −11 (2010–21) | no | PUBLISH-CORE |
| Atlanta Fed Market Probability Tracker xlsx | hike/cut % per meeting | official, daily since Mar 2023; FedWatch is 403 and this IP is on CME's block list | GoldPreOpen links FedWatch | PUBLISH-CORE (replaces the link) |
| Fed funds futures ZQ (Yahoo) | implied rate per month | ZQZ26 4.04 % vs EFFR 3.88 % = 64 % of a Dec hike | no | PUBLISH-CONTEXT |
| US release calendar with consensus (ForexFactory JSON; BEA page) | when CPI/NFP/PCE/FOMC hit, in IST | verified; BLS pages 403 | ECO has NO US CPI/NFP/PCE | PUBLISH-CORE |
| Breakevens, 5y5y, Cleveland Fed, Michigan (FRED) | inflation expectations vs real tightening | breakeven beta +12.7 %/100 bp (t +10) 2010–21; +4.3 (t 1.8) since 2022 | no | PUBLISH-CONTEXT |
| GVZ gold-vol index (Yahoo ^GVZ, FRED GVZCLS) | how big a move to size for | GVZ 24 → 1σ day 1.52 % ≈ $61 ≈ ₹2,200/10 g ≈ ₹2.2 lakh per 1 kg lot | no | PUBLISH-CORE |
| VIX, oil | risk-off / inflation impulse | context (not tested) | WEI, CMDT | PUBLISH-CONTEXT via existing quote |
| Gold/silver, gold/platinum | metals relative value | no predictive evidence; G/S 74 (60th pct), G/Pt 2.58 (95th pct) | no | PUBLISH-CONTEXT |
| Gold vs M2 / Fed balance sheet | debasement narrative | gold/M2 98th pct since 1975; untestable monthly | no | PUBLISH-CONTEXT (monthly) |
| GPR index (Caldara–Iacoviello) | is war-news high by history | next-month t 1.0, R² 0.002; contemporaneous t 0.8 | GoldPreOpen counts risk headlines | PUBLISH-CONTEXT (explainer) |
| ETF holdings (SPDR GLD archive xlsx) | Western investors buying? | weekly corr 0.33–0.37 contemporaneous, ≈0 predictive | GoldPreOpen link | PUBLISH-CONTEXT + terms flag |
| Seasonality (World Bank 1971→ + GC=F) | good month? | no month passes t≥2 in both halves; Jan/Aug best | no | PUBLISH-CONTEXT (strip + caveat) |
| Fair-value regressions | mispriced? | 2010–21 model says $788 vs $4,002 (+408 %); trailing-3y refit has the WRONG SIGN; residual t 0.15 | no | DO-NOT-PUBLISH as a number; publish driver-health panel |
| LBMA JSON · Kitco · CME FedWatch · Stooq · BLS pages | benchmark/charts/odds/history/schedule | 403 bot wall · JS + terms · IP BLOCKED · HTML wall · 403 | Kitco/FedWatch linked | LINK-ONLY |

Health check 26 Oct 2026 (verified feeds): gold $4,002 (GC=F), −24.8 % from the $5,318 ATH of 29 Jan 2026, −7.8 % YTD; 10y real 2.66 % (99th percentile since 2003; 2026 peak 2.95 % on 5 Oct); 10y nominal 5.00 % (5.31 % on 5 Oct, highest since 2007); 2y 4.69 %; breakeven 2.34 %; 5y5y 2.20 %; DXY 101.7 (83rd pct since 1990); Fed 3.75–4.00 %, EFFR 3.88 %; FOMC Wed 28 Oct 23:30 IST, consensus hold; hikes priced into 2027 (Dec-window P(hike) 86.9 %, Atlanta Fed); Brent $115, WTI $102; VIX 19.5; GVZ 24.3 (84th pct); GPR daily 98th pct (19 Oct); GLD 1,045.6 t (−25 t YTD, −8 t this week); HY OAS 3.40 %. Reading: record real yields + firm dollar + ETF outflows are beating geopolitics + oil inflation — the lesson of H1: since 2022 the real-yield rule explains a third of what it used to; the dollar never stopped working.

## 1. Repetition audit (what the app already fetches)
- COMEX gold GC=F: WEI "GOLD", CMDT board, GoldPreOpen model, MCXG overlay (Yahoo v8 in gold_preopen._yahoo_bars, commodity._yahoo_chart, news_scanner quotes) → 4 places; one owner (data-service history), macro page shows changes/decomposition only.
- USD/INR: WEI, GoldPreOpen, MCXG. DXY: WEI "DOLLAR INDEX" + GoldPreOpen "Dollar index (DXY)". EUR/USD: WEI + GoldPreOpen (1.1161 trigger). US10Y: WEI + GoldPreOpen (^TNX). Silver: WEI, CMDT, GoldPreOpen. VIX/Brent/WTI/copper/gas: WEI, CMDT. FOMC dates: WEI strip, BRF, ECO (markets.parse_fomc). 10y real: GoldPreOpen only (FRED fredgraph.csv DFII10 + Treasury CSV fallback), one number, no history.
- ECO: India CPI/WPI/IIP/GDP + RBI + Fed decisions only — US CPI/NFP/PCE missing (gap).
- CMDT FRED legs (DCOILWTICO/BRENT/DHHNGSP/DTWEXBGS) use the key-gated REST API; FRED_API_KEY not set → panel shows "not available", while gold_preopen.py proves the key-free fredgraph.csv path (0.3–0.9 s today). EIA legs: key not set, unrelated to gold.
- GoldPreOpen manual-check links (Fed odds, real yields, ETF flows, GLD, Kitco, SGE, MCX circulars, FBIL, TradingView): Fed odds, real yields, ETF flows, GLD are replaced by data below; keep SGE/circulars/FBIL/TradingView as links. GoldPreOpen event_risk headline count stays as the live geopolitical gauge.

## 2. G-STUDY (pre-registered in g_study.py; numpy OLS; HAC t on levels (60 lags); plain t on non-overlapping weekly/monthly changes)
Data: GC=F daily (Yahoo, Aug 2000→, fetched with period1/period2), FRED DFII10/DGS10/T10YIE, Yahoo DX-Y.NYB (1990→), World Bank CMO monthly gold 1971→Dec 2024 spliced with GC=F month-ends, GPR monthly 1985→Sep 2026. Daily panel 6,049 rows 2003-01-02→2026-10-25.

H1 Real yields — PASS for 2010–21, breakdown since 2022 confirmed. Level fit ln(gold) on DFII10: 2003–09 β −18 %, t −1.3, R² 0.04 (DXY was the story: R² 0.66); 2010–21 β −20.4 % per 100 bp, t −14.4, R² 0.68 (0.76 with DXY); 2022–26 β +24.1 % (sign flip), t +4.2, R² 0.28. Weekly changes: 2003–09 −3.3 (t −2.9, R² 0.02); 2010–21 −9.9 (t −12.2, R² 0.19, corr −0.44); 2022–26 −5.0 (t −4.0, R² 0.06, corr −0.24). Monthly: −10.1/−13.8/−6.9 (t −4.9/−7.1/−3.1); since 2022 insignificant once DXY is included (t −0.9). Nominal-vs-breakeven split weekly 2010–21: nominal −9.4 (t −11.2), breakeven +12.7 (t +10.0); 2022–26: −5.0 (t −4.0), +4.3 (t 1.8). Rolling 1y corr of daily changes gold vs real yield at year-ends: 2019 −0.54, 2021 −0.35, 2022 −0.45, 2023 −0.48, 2024 −0.30, 2025 −0.03, 2026 −0.15; vs DXY −0.43, −0.44, −0.47, −0.51, −0.31, −0.42, −0.38. Reading: real yields still move gold on the day; they no longer tell you the level (central banks >1,000 t/yr 2022–24 per WGC — the supply/demand agent's brief).

H2 Dollar — PASS in every regime. Weekly β (gold % per 1 % DXY): 2003–09 −1.23 (t −11.6, R² 0.27); 2010–21 −1.02 (t −13.2, R² 0.22); 2022–26 −0.97 (t −6.4, R² 0.14). Monthly −1.21/−0.81/−1.21 (t −5.7/−4.7/−4.5). The only macro variable that keeps significance in the joint monthly regression since 2022.

H3 Seasonality — NOT reliable (as pre-registered). Monthly log returns 1971→2026; rule: pass only if t ≥ 2 in BOTH halves (1971–2000, 2001–2026): no month passes. Jan +2.55 % (hit 67 %, t 2.7; halves t 1.4/3.9; GC=F 2001–26 +2.8 %, t 3.0), Feb +1.35 (t 2.2), Mar −0.14, Apr +0.42, May +0.49 (hit 38 %), Jun 0.00 (GC=F −1.01 %, hit 42 %), Jul +0.10, Aug +1.12 (t 1.9; GC=F +2.38 %, t 2.8, hit 73 %), Sep +1.15 (t 1.6, hit 48 %; Baur 2013 "Autumn effect" visible, not significant in either half), Oct +0.73, Nov +0.09, Dec +0.50 (GC=F +1.34 %, hit 65 %). Diwali (Oct–Nov) shows nothing in USD gold — Indian demand lives in the local premium; Chinese New Year run-up coincides with Jan but attribution is ambiguous.

H4 GPR — weak, no prediction (as pre-registered). 500 months: contemporaneous β +0.54 % per 100 % GPR change, t 0.8, R² 0.001; GPR change → next month t 1.0, R² 0.002; level → next month t 1.5; top-decile months +0.64 % vs +0.53 % all; following month +0.68 %. Latest Sep 2026 = 146.2 (90th pct); daily 248.7 on 19 Oct (98th), 30-day avg 176 (96th).

H5 Mispricing residual — not a signal (as pre-registered). OOS 2022–26 (55 month-ends): residual → next 63-session return β 0.003, t 0.15, R² 0.002. Residual at year-ends: 2018 +11 %, 2019 +11 %, 2020 +4 %, 2021 +4 %, 2022 +87 %, 2023 +116 %, 2024 +218 %, 2025 +367 %, today +408 % (model fair value $788). Trailing-3y refit: R² 0.62 but β +38.8 % per 100 bp (wrong sign) → residual −1.9 % is meaningless. Publish the driver-health panel instead.

Descriptive: KGX last sessions (DXY-weight basket EUR .576 JPY .136 GBP .119 CAD .091 SEK .042 CHF .036; usd_move = −Σw·Δln f; pure_gold = gold_usd + usd_move; usd_effect = −usd_move): Wed 21 Oct +0.18 % = pure +0.01 + USD +0.17 (all dollar); Thu 22 Oct −2.18 % = −2.29 + 0.10 (gold selling); Fri 23 Oct −1.30 % = −1.42 + 0.12. Gold in currencies (26 Oct): USD 4,002 (YTD −7.8 %, 1y −3.3 %), EUR 3,567 (−3.5/+0.1), JPY 628,746 (−7.4/−0.4), GBP 2,992 (−7.2/−3.6), CNY 26,656 (−12.2/−9.6), INR 379,910/oz (−2.5/+4.6); landed ₹/10 g no duty 122,144 vs MCX Dec settlement 146,079 (app log 23 Oct) → 19.6 % gap = duty+GST+basis (MCX agent). Ratios: G/S 74.1 (median since 2000 70, range 32–126, 60th pct; silver $54.0); G/Pt 2.58 (median 1.1, 95th pct; Pt $1,553). GVZ 24.15 (84th pct since 2008; 2026 range 21.4–46.0): 1σ day = 24.15/√252 = 1.52 % ≈ $61/oz ≈ ₹1,858/10 g landed ≈ ₹2,200 on MCX price ≈ ₹2.2 lakh per 1 kg lot; realised 20d vol 14.9 %. Gold/M2 0.192 (98th pct since 1975; M2 Aug $23,343 bn). ZQ front 96.10 → 3.90 % (EFFR 3.88); ZQZ26 95.96 → 4.04 % = +16 bp = 64 % of a 25 bp hike by Dec. Atlanta Fed (22 Oct, target 375–400): Dec-16 window P(hike) 86.9 %, P(cut) 4.5 %, mean 4.17 %; Mar-27 4.37 %; Sep-27 4.56 %; Dec-27 4.55 %. GLD tonnes 1,045.6 (22 Oct): 1w −8.3, 1m −10.3, YTD −24.9; 2026 high 1,101.3 (27 Feb); ATH 1,353 (Dec 2012); weekly corr tonnes%-vs-return 0.33 (0.37 since 2022), next-week −0.02 (−0.06). Intraday real-yield proxy: real ≈ ^TNX live − last T10YIE; daily SD of ΔT10YIE 3.1 bp (p95 7 bp); nominal explains 75 % of daily real-yield variance 2022–26. This week in IST (ForexFactory): Wed 28 Oct 23:30 Fed decision (4.00 % hold), Thu 00:00 presser, Thu 29 Oct 18:00 Advance GDP (3.2 %) + Core PCE m/m (0.3 % vs 0.2 %).

## 3. Driver notes (definitions for the new reader are in the glossary; pro pitfalls here)
3.1 Real yields: DFII10 = 10y TIPS constant maturity (H.15); identity DGS10 = DFII10 + T10YIE verified to 0.0 bp. Pitfalls: TIPS liquidity premium (2008, Mar 2020), 5y most Fed-sensitive, 30y term premium, no free intraday feed (proxy above). Treasury CSV posts ~15:30–16:30 ET = 02:00–03:00 IST next morning; FRED one US business day later (verified: at 05:40 IST Mon FRED had Thu 22 Oct, Treasury had Fri 23 Oct; same-date values identical). Literature: Erb & Harvey 2013 FAJ; O'Connor et al. 2015 IRFA.
3.2 Inflation expectations: T5YIFR = Fed's preferred; EXPINF* Cleveland Fed model (monthly); MICH noisy/polarised. Positive driver (breakeven beta above).
3.3 Nominal/2y: Treasury nominal CSV 1 Mo…30 Yr (23 Oct: 3m 4.22, 2y 4.69, 10y 5.00, 30y 5.33, 10y−2y +31 bp). Yahoo ^TNX = CBOE 10y ×10 (live US hours); no free intraday 2y index on Yahoo (ZT=F direction or DGS2 daily).
3.4 Dollar: DXY = ICE six-currency geometric basket (no CNY/INR/EM); DTWEXBGS broad but weekly H.10 (latest 16 Oct) → monthly use only. Capie–Mills–Wood 2005, Reboredo 2013. KGX method public, Kitco's numbers proprietary.
3.5 Gold in currencies: gold_ccy = gold_usd × ccy/USD; landed ₹/10 g = gold_usd × USDINR × 10/31.1034768.
3.6 Fed expectations: ZQ price = 100 − expected avg EFFR for the month; FedWatch steps at meetings; Atlanta Fed uses 3m SOFR options → full distribution (percentiles, mean, mode, P(cut), P(hike)) per meeting window; reference_start = meeting that starts the window. FOMC decision 14:00 ET = 23:30 IST in US summer (MCX close), 00:30 IST in winter (after close → gap risk at 09:00).
3.7 US releases: CPI (BLS, mid-month), PCE (BEA, month-end), NFP (first Friday) at 08:30 ET = 18:00 IST (19:00 in US winter) — during the MCX evening session. BLS pages 403 for scripts; BLS API v1 no key (25/day); BEA page parseable ("October 29 8:30 AM Personal Income and Outlays, September 2026"); ForexFactory JSON fields title,country,date(ISO, −04:00),impact,forecast,previous — NO `actual` field in any of 96 events; nextweek.json 404.
3.8 Volatility: VIX (WEI), GVZ (CBOE gold ETF vol, from GLD options), OVX. GVZ → expected move per lot via shared/mcx_specs multipliers (GOLD ₹100/₹1, GOLDM ₹10, GOLDPETAL ₹1).
3.9 Oil: inflation channel (positive) vs yields/Fed channel (negative); today the second dominates; reuse WEI/CMDT quote.
3.10 Ratios: relative value for silver/platinum traders; not a gold predictor.
3.11 M2/liquidity: gold/M2 98th pct; "net liquidity" = WALCL − RRP − TGA has no OOS evidence → inputs only. FRED foreign M2 dead (Euro Mar 2017, China Dec 2018, Japan Feb 2017).
3.12 GPR: Caldara & Iacoviello 2022 AER; GPR/GPRH/GPRT/GPRA/GPRC_*; daily GPRD with THREAT/ACT, MA7/MA30, labelled events; daily file updated weekly (~1 week lag).
3.13 ETF: SPDR archive xlsx 18 Nov 2004→22 Oct 2026 (Date, Closing Price, Ounces/Share, NAV, Indicative, Mid, Premium/Discount, Volume, Total Ounces, Tonnes, Total NAV); Disclaimer: "Reproduction or redistribution … expressly prohibited without prior written consent" (flag); old CSV URL returns a PDF; iShares ajax CSV returned HTML (UNVERIFIED); WGC flows need free registration. Flows confirm, don't lead.
3.14 Seasonality: World Bank CMO xlsx sheet "Monthly Prices" from 1960M01 but the file at the documented URL ends Dec 2024 (stale vintage); CC BY-4.0; monthly averages. Reuse data-service seasonality.py (SEAG) renderer.
3.15 Fair value: DO-NOT-PUBLISH as a number.
3.16 Benchmark history: LBMA JSON 403 ×5 (bot wall; FRED LBMA series 404) → LINK-ONLY; Yahoo GC=F daily 2000→ is the stored benchmark; GLD (2004→) and GOLDBEES.NS (2009→, ₹115.96) cross-checks; Stooq returns HTML (blocked); Kitco charts JS-rendered, robots allows crawl but terms forbid republishing → LINK-ONLY.

## 4. Proposed GOLD MACRO view (GO code GMAC; 6-tile strip reused by MCXG and WEI)
1 Driver strip (1d/1w/1m change + supportive/headwind tag + health badge): 10y real (bp), 2y (bp), breakeven (bp), DXY %, USD/INR %, GVZ, oil %, GLD tonnes. 2 "Gold or the dollar?" KGX bar (today/week/month). 3 Gold in USD/INR/EUR/JPY/CNY (1d/1w/1m/YTD; INR line links MCXG). 4 Fed path: Atlanta Fed per-meeting P(cut)/P(hike)/mean, ZQ implied Dec/Mar/Jun, EFFR, next FOMC in IST (from ECO). 5 US calendar in IST this week with consensus/previous; flag in-session (18:00–23:30 IST) vs after-close (gap risk). 6 Expected move: GVZ → 1σ in %, $/oz, ₹/10 g, ₹ per lot per contract; realised 20d vol. 7 Context (collapsed, monthly): ratios + percentiles, gold/M2, GPR monthly/daily percentile, seasonality strip, inflation-expectation models, HY OAS. 8 Driver-health panel (weekly): rolling 1y corr vs real yield/DXY, weekly betas by regime. Remove/merge: GoldPreOpen context rows DXY/EUR/US10Y/silver become the strip; replace manual links Fed odds/real yields/ETF flows/GLD/Kitco with data.

Storage (data-service owns; nothing stored today): gold_macro_series(series_id, date, value, source, fetched_at PK(series_id,date)); gold_macro_catalog(series_id,label,publisher,url,frequency,lag_days,terms,verdict); gold_us_calendar(event_time_utc,title,country,impact,forecast,previous,actual,source,fetched_at); gold_fed_path(asof,meeting,prob_cut,prob_hike,rate_mean_bp,rate_mode_bp); gold_etf_holdings(date,fund,tonnes,nav_usd,shares). Backfill once (free): FRED full CSVs, Yahoo period1/period2, SPDR 2004→, Atlanta Fed 2023→, GPR 1985→, World Bank 1971→2024. Jobs (IST, outside 07:45–09:20 and 18:30–21:15): 03:00 Treasury real+nominal CSV, Yahoo daily closes, ForexFactory; 06:30 SPDR xlsx, Atlanta Fed xlsx; 21:30 FRED daily batch; Tue 03:00 H.10; Fri 03:00 WALCL/WTREGEN; Mon 06:30 GPR daily; monthly 5th: GPR monthly, M2SL, CPI/PCE/PAYEMS, EXPINF, MICH. Point-in-time (fetched_at) per docs/PROGRAMMATIC_DATA_ACCESS.md §3.

Ingestion traps found: T1 Yahoo range=max silently returns MONTHLY bars (quarterly for DX-Y.NYB and ^TNX) even with interval=1d — first study run had 329 "daily" rows; use period1/period2 (21/21 symbols daily since 1990/2000). T2 Yahoo 429 ×37 with a Chrome UA on query1; the app's UA "Mozilla/5.0 (SuryaDhana-GoldDesk)" on query2 got 200 ×21 at 6 s spacing — keep the app UA and SWR cache, never run a second poller from this IP. T3 FRED stalls browser UAs; plain client 0.3–0.9 s; fredgraph.csv needs no key, REST/ALFRED do (400). T4 FRED LBMA series 404; foreign M2 dead. T5 Treasury CSV per year, different columns real vs nominal, MM/DD/YYYY, 0.8 s today (not 20 s). T6 ForexFactory: thisweek only, no actual field, −04:00/−05:00 offsets. T7 SPDR CSV URL now serves a PDF; xlsx via api.spdrgoldshares.com with Disclaimer sheet. T8 Atlanta Fed xlsx 7 MB daily; parse DATA sheet only.

## 5. Terms
Public domain/attribution: Treasury, BLS, BEA, Fed Board, FRED (fred.stlouisfed.org/legal), Atlanta Fed (LICENSE sheet not machine-readable — read it), GPR (cite), World Bank CC BY-4.0. Personal use/no redistribution: Yahoo (unofficial), ForexFactory (cache), SPDR (expressly prohibited), LBMA, WGC (registration), Kitco. Proprietary/blocked: CME (and this IP is on its block list). For a single-user desktop terminal everything marked PUBLISH is displayable; nothing may be re-served to third parties.

## 6. Literature (qualitative; numbers above are ours)
Erb & Harvey 2013 FAJ 69(4); Baur & Lucey 2010 Financial Review 45(2); Baur & McDermott 2010 JBF 34(8); Capie, Mills & Wood 2005 JIFMIM 15(4); Reboredo 2013 JBF 37(8); Baur 2013 RIBAF 27(1) (Autumn effect); Lucey & Tully 2006 Applied Financial Economics 16; Caldara & Iacoviello 2022 AER 112(4); O'Connor, Lucey, Batten & Baur 2015 IRFA 41; WGC Gold Demand Trends / GRAM (Goldhub, registration; GRAM URL not verified).

## 7. Glossary
bp = 0.01 %. Nominal yield = stated Treasury rate. Real yield/TIPS = yield after inflation (DFII10 = 10y). Breakeven = nominal − real = expected inflation; 5y5y = expected inflation 5–10 years out. DXY = dollar vs six rich-country currencies; broad index = vs all partners (weekly). KGX/pure gold = gold measured against a currency basket. FOMC = Fed rate meeting (8/yr); EFFR = overnight rate the Fed targets; fed funds futures ZQ: price = 100 − expected rate; FedWatch/MPT convert prices to % odds. CPI/PCE/NFP = US inflation (BLS), the Fed's inflation measure (BEA), jobs (BLS); consensus = average forecast; market trades the surprise. VIX/GVZ/OVX = expected 30-day vol of stocks/gold/oil; ÷√252 for a one-day 1σ. GPR = newspaper-based war/terror index, 100 = 1985–2019 average. ETF holdings = physical gold in GLD. Gold/silver ratio = oz of silver per oz of gold. M2 = money supply; WALCL = Fed balance sheet. β/R²/t = slope, variance explained, signal-to-noise (|t| ≥ 2 ≈ probably real); Newey-West = t corrected for autocorrelation; residual = actual − fitted. Point-in-time = store values as first known. Landed price = COMEX $/oz × USD/INR × 10/31.1035 before duty/GST/premium; MCX GOLD lot 1 kg, quoted per 10 g, ₹1 = ₹100 per lot.

## Sources

### US Treasury daily real yield curve CSV (5/7/10/20/30 YR)
- publisher: US Department of the Treasury · url: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2026
- access: FREE · frequency: daily (US business days) · lag: same day, posted ~15:30-16:30 ET = 02:00-03:00 IST next morning; one US business day ahead of FRED · history: one file per calendar year back to 2003 (change the year in the URL)
- verified: HTTP 200, 767 ms (code comment says ~20 s; not today); 204 rows for 2026; columns Date,5 YR,7 YR,10 YR,20 YR,30 YR; latest 2026-10-23 = 5y 2.34, 7y 2.49, 10y 2.66, 20y 2.94, 30y 3.08
- terms: US government work, public domain
- what it tells: The real (after-inflation) yield across maturities: the cost of holding gold. 10y real at 2.66% is the 99th percentile since 2003.
- how pros use it: Bloomberg USGGT10Y / GTII10 Govt; desks quote gold moves per bp of 10y real
- evidence of value: G-STUDY H1: weekly beta -9.9%/100bp (t -12) 2010-21; -5.0 (t -4) 2022-26; level fit sign-flipped since 2022
- **verdict: PUBLISH-CORE** — Primary free daily source for the strongest classic driver; already used as a fallback in gold_preopen.py; extend to history + 5y/30y + health flag
- already in app: gold_preopen.py _treasury_real_10y (background fallback for the 10y only)
- ingest notes: CSV with Date MM/DD/YYYY; columns differ from the nominal file; fetch the current year daily at 03:00 IST; store point-in-time

### US Treasury daily nominal par yield curve CSV (1 Mo..30 Yr)
- publisher: US Department of the Treasury · url: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026
- access: FREE · frequency: daily · lag: same day (02:00-03:00 IST next morning) · history: per-year files back to 1990
- verified: HTTP 200, 884 ms; 204 rows; columns Date,1 Mo,1.5 Month,2 Mo,3 Mo,4 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr; latest 2026-10-23: 3m 4.22, 2y 4.69, 10y 5.00, 30y 5.33
- terms: public domain
- what it tells: Nominal yields incl. the 2-year (the cleanest free Fed-expectations gauge) and the curve slope (10y-2y +31 bp)
- how pros use it: USGG2YR; 2s10s; 'Fed path' read
- evidence of value: nominal-vs-breakeven split: nominal beta -9.4%/100bp (t -11) 2010-21
- **verdict: PUBLISH-CORE** — The 2y is new to the app and daily; same file family as the real curve
- already in app: 10y only via Yahoo ^TNX (WEI, GoldPreOpen)
- ingest notes: same job as the real curve

### FRED fredgraph.csv (no key): real yields DFII5, DFII7, DFII10, DFII20, DFII30
- publisher: Federal Reserve Bank of St. Louis (FRED), data from Treasury H.15 · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10
- access: FREE · frequency: daily · lag: next US business day (verified one day behind Treasury) · history: 2003-01-02 onward
- verified: all 5 HTTP 200, 0.37-0.71 s; DFII10 5,956 rows from 2003-01-02, latest 2026-10-22 = 2.64 (Treasury had 2026-10-23); header observation_date,DFII10
- terms: FRED terms of use: free with attribution (fred.stlouisfed.org/legal)
- what it tells: Full daily history of real yields since 2003 for backfill and the rolling-correlation health panel
- how pros use it: same as Treasury; FRED for charts/history
- evidence of value: G-STUDY H1 (see Treasury entry)
- **verdict: PUBLISH-CORE** — Free, keyless, full history; the app already uses this exact endpoint
- already in app: gold_preopen._fred_fetch (DFII10, last 30 days only)
- ingest notes: plain client, NO browser User-Agent (FRED stalls browser UAs 20 s+); cosd= to limit; store as long table; FRED's LBMA gold series are 404

### FRED: breakevens and inflation expectations T10YIE, T5YIE, T5YIFR, EXPINF1YR, EXPINF10YR, MICH
- publisher: FRED (Treasury, Cleveland Fed, U. Michigan) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10YIE
- access: FREE · frequency: daily (breakevens) / monthly (EXPINF, MICH) · lag: next business day / monthly · history: 2003 (breakevens); 1982 (EXPINF); 1978 (MICH)
- verified: all 6 HTTP 200 (0.37-0.80 s); T10YIE latest 2026-10-23 = 2.34; T5YIFR 2026-10-23 = 2.20; EXPINF10YR 2026-10-01 = 2.73; MICH 2026-09-01; T10YIE = DGS10 - DFII10 verified to 0.0 bp
- terms: FRED terms
- what it tells: Whether a yield move was inflation expectations (gold-positive) or real-rate tightening (gold-negative); the Fed's 5y5y gauge
- how pros use it: USGGBE10; 5y5y forward; Cleveland Fed model
- evidence of value: G-STUDY H1 split
- **verdict: PUBLISH-CONTEXT** — Needed for the nominal = real + breakeven split; breakeven beta +12.7%/100bp (t +10) 2010-21 but only +4.3 (t 1.8) since 2022
- already in app: no
- ingest notes: same FRED job; note T10YIE is an identity, not independent data

### FRED: nominal yields and slope DGS2, DGS10, DGS30, DGS3MO, T10Y2Y
- publisher: FRED (Treasury H.15) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS2
- access: FREE · frequency: daily · lag: next US business day · history: 1962/1976 onward
- verified: all HTTP 200 (0.48-0.63 s); DGS2 from 1976-06-01, latest 2026-10-22 = 4.65; DGS10 from 1962, latest 2026-10-22 = 4.96; T10Y2Y latest 2026-10-23
- terms: FRED terms
- what it tells: Nominal curve history for the 2y Fed proxy and slope
- how pros use it: USGG2YR/USGG10YR
- evidence of value: nominal beta -9.4 (t -11.2) 2010-21; -5.0 (t -4.0) 2022-26
- **verdict: PUBLISH-CORE** — History for the 2y (Treasury CSV is the same-day source)
- already in app: 10y via Yahoo only
- ingest notes: same FRED job

### FRED: policy rate DFF, EFFR, FEDFUNDS, DFEDTARU, DFEDTARL, SOFR
- publisher: FRED (Fed Board, NY Fed) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF
- access: FREE · frequency: daily (DFF/EFFR/SOFR), monthly (FEDFUNDS), on change (target) · lag: next business day · history: 1954 onward
- verified: all HTTP 200; DFF latest 2026-10-22 = 3.88 (from 1954); EFFR 2026-10-22 = 3.88; DFEDTARU 2026-10-25 = 4.00, DFEDTARL 3.75; SOFR 2026-10-22 = 3.90; FEDFUNDS 2026-09-01
- terms: FRED terms
- what it tells: Where the Fed actually is (target 3.75-4.00%, effective 3.88%) - the anchor for implied-rate math
- how pros use it: FEDL01, FDTR
- evidence of value: context only
- **verdict: PUBLISH-CONTEXT** — Context number under the Fed-path panel
- already in app: no
- ingest notes: same FRED job

### FRED: dollar indices and H.10 FX DTWEXBGS, DTWEXAFEGS, DEXINUS, DEXUSEU, DEXJPUS, DEXCHUS, DEXUSUK, DEXCAUS, DEXSDUS, DEXSZUS
- publisher: FRED (Federal Reserve Board H.10) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS
- access: FREE · frequency: daily values, published weekly (Monday 16:15 ET for the prior week) · lag: 3-10 days (verified: 10 days behind today) · history: 2006 (broad), 1971-73 (bilateral)
- verified: all 10 HTTP 200 (0.33-1.5 s); DTWEXBGS from 2006-01-02, latest 2026-10-16 = 121.40; DEXINUS 2026-10-16 = 94.96 (from 1973); all H.10 series end 2026-10-16
- terms: FRED terms
- what it tells: The broad trade-weighted dollar (includes CNY, INR) and official noon FX fixes - the economically better dollar gauge, but too late for daily trading
- how pros use it: Fed broad index for research; DXY for trading
- evidence of value: monthly DXY beta -1.2 (t -4.5) 2022-26; broad index not separately tested
- **verdict: PUBLISH-CONTEXT** — Monthly/backfill use only; DXY (Yahoo) is the daily gauge
- already in app: DTWEXBGS listed in commodity.py FRED leg but key-gated and key not set
- ingest notes: weekly job Tue 03:00 IST; fredgraph.csv needs no key (commodity.py could switch to it)

### FRED: volatility indices VIXCLS, GVZCLS, OVXCLS
- publisher: FRED (Cboe) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=GVZCLS
- access: FREE · frequency: daily · lag: next business day · history: 2008 (GVZ), 1990 (VIX)
- verified: all 3 HTTP 200 (0.64-0.80 s); GVZCLS from 2008-06-03, latest 2026-10-22 = 24.15; VIXCLS from 1990, latest 2026-10-22 = 19.03
- terms: FRED terms; Cboe data via FRED
- what it tells: Gold's own implied volatility (GVZ): the expected size of daily moves; VIX risk-off; OVX oil vol
- how pros use it: GVZ Index on Bloomberg; expected move = IV/sqrt(252)
- evidence of value: GVZ 24.15 -> 1-day 1 sigma 1.52% (~$61/oz, ~Rs 2,200/10 g, ~Rs 2.2 lakh per 1 kg lot); 84th percentile since 2008; realised 20d vol 14.9%
- **verdict: PUBLISH-CORE** — GVZ gives the expected move in rupees per lot - the sizing number no page shows; VIX already in WEI
- already in app: VIX in WEI via Yahoo; GVZ nowhere
- ingest notes: daily FRED job; Yahoo ^GVZ gives the same-day close

### FRED: oil spot DCOILWTICO, DCOILBRENTEU
- publisher: FRED (EIA) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU
- access: FREE · frequency: daily · lag: 2-3 business days · history: 1986/1987 onward
- verified: both HTTP 200; DCOILWTICO 3.2 s (slow today), DCOILBRENTEU 0.67 s; latest 2026-10-20 = Brent 115.22
- terms: FRED terms
- what it tells: Oil spot as the inflation impulse; Brent $115 today
- how pros use it: CO1/CL1 Comdty
- evidence of value: context only (not tested here)
- **verdict: PUBLISH-CONTEXT** — Already in WEI/CMDT via Yahoo futures; FRED only for history
- already in app: CMDT FRED leg (key-gated, unavailable); Yahoo CL=F/BZ=F in WEI and CMDT
- ingest notes: daily FRED job

### FRED: money and Fed liquidity M2SL, WM2NS, WALCL, RRPONTSYD, WTREGEN, BOGMBASE
- publisher: FRED (Federal Reserve Board H.6, H.4.1; NY Fed) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL
- access: FREE · frequency: monthly (M2SL), weekly (WM2NS, WALCL, WTREGEN), daily (RRP) · lag: M2 ~4 weeks (4th Tuesday); WALCL Thursday 16:30 ET · history: 1959 onward
- verified: all 6 HTTP 200; M2SL from 1959, latest 2026-08-01 = 23,342.8 $bn; WALCL latest 2026-10-21 = 6,753,604 $mn; RRPONTSYD 2026-10-23; WTREGEN 2026-10-21
- terms: FRED terms
- what it tells: Money supply and Fed balance sheet for the 'debasement' and 'net liquidity' narratives
- how pros use it: gold/M2 chart; WALCL-RRP-TGA 'net liquidity'
- evidence of value: context only; FRED foreign M2 series are dead (Euro ends 2017-03, China 2018-12, Japan 2017-02)
- **verdict: PUBLISH-CONTEXT** — Gold/M2 at the 98th percentile since 1975 is a talking point, not a timing tool; 'net liquidity' formula has no OOS evidence - publish inputs only
- already in app: no
- ingest notes: weekly Fri 03:00 IST + monthly job

### FRED: US macro prints CPIAUCSL, CPILFESL, PCEPI, PCEPILFE, PAYEMS, UNRATE
- publisher: FRED (BLS, BEA) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL
- access: FREE · frequency: monthly · lag: CPI ~2 weeks, PCE ~4 weeks, NFP ~1 week after month end · history: 1947+
- verified: all 6 HTTP 200; CPIAUCSL latest 2026-09-01 = 336.298 (SA); PCEPILFE 2026-08-01 = 130.455; PAYEMS 2026-09-01 = 159,044k; UNRATE 2026-09-01
- terms: FRED terms
- what it tells: The levels behind the three market-moving releases
- how pros use it: CPI YoY / core PCE YoY vs Fed 2% target
- evidence of value: context only
- **verdict: PUBLISH-CONTEXT** — The event (actual vs consensus) is what moves gold; the level is a monthly-view context; revised values - use ALFRED (key) for backtests
- already in app: no
- ingest notes: monthly job; store vintage date

### FRED: high-yield credit spread BAMLH0A0HYM2
- publisher: FRED (ICE BofA) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2
- access: FREE · frequency: daily · lag: next business day · history: 1996+
- verified: HTTP 200, 484 ms; latest 2026-10-22 = 3.40
- terms: FRED terms; ICE BofA licence via FRED (display only)
- what it tells: Risk appetite (wider = risk-off)
- how pros use it: HY OAS
- evidence of value: context only
- **verdict: PUBLISH-CONTEXT** — Not in the brief; useful next to VIX; untested
- already in app: no
- ingest notes: daily FRED job

### FRED: LBMA gold GOLDAMGBD228NLBM / GOLDPMGBD228NLBM
- publisher: FRED (formerly LBMA) · url: https://fred.stlouisfed.org/graph/fredgraph.csv?id=GOLDPMGBD228NLBM
- access: BLOCKED · frequency: - · lag: - · history: -
- verified: HTTP 404 for both (HTML not-found page)
- terms: -
- what it tells: Used to be the free daily LBMA fix history; discontinued
- how pros use it: -
- evidence of value: -
- **verdict: DO-NOT-PUBLISH** — Series no longer exist
- already in app: no
- ingest notes: do not reference; use Yahoo GC=F for daily history

### FRED REST API and ALFRED vintages (api.stlouisfed.org)
- publisher: FRED · url: https://api.stlouisfed.org/fred/series/observations?series_id=DFII10
- access: FREE-KEY · frequency: - · lag: - · history: -
- verified: HTTP 400 {error_code:400, 'Variable api_key is not set'} for both the series and the realtime_start (ALFRED) calls; FRED_API_KEY absent from .env
- terms: FRED API terms (free key)
- what it tells: Same data as fredgraph.csv plus point-in-time vintages (ALFRED) and the release-dates calendar
- how pros use it: ALFRED for backtests
- evidence of value: -
- **verdict: LINK-ONLY** — Key not set; commodity.py's FRED leg is dead because of it; register the free key or switch to fredgraph.csv
- already in app: commodity.py _fred_series (gated)
- ingest notes: owner action

### Yahoo Finance chart v8: COMEX gold GC=F, silver SI=F, platinum PL=F (daily via period1/period2)
- publisher: Yahoo Finance (unofficial, undocumented endpoint) · url: https://query2.finance.yahoo.com/v8/finance/chart/GC=F?period1=631152000&period2=<now>&interval=1d
- access: FREE · frequency: intraday (5m bars) and daily · lag: delayed quotes; daily close next morning IST · history: 2000-08-30 (GC=F), 1997 (PL=F)
- verified: HTTP 200, 0.5 s each with the app's UA on query2; GC=F 6,564 daily rows 2000-08-30 -> 2026-10-25, median gap 1 day, regularMarketPrice 4002.0 (Sun-night Globex); SI=F 54.02; PL=F 1553.3. First pass with a Chrome UA on query1: 429 'Too Many Requests' on 37/37 symbols. range=max silently returned MONTHLY bars.
- terms: Yahoo ToS: personal, non-commercial; no SLA; no redistribution
- what it tells: The gold benchmark history (2000->), silver and platinum for the ratios
- how pros use it: GC1 Comdty; Bloomberg GCA
- evidence of value: basis of G-STUDY
- **verdict: PUBLISH-CORE** — The only key-free daily gold history that answered today (LBMA and Stooq are walled); already the app's price provider
- already in app: GC=F in WEI, CMDT, GoldPreOpen (GCZ26), MCXG; SI=F in WEI/CMDT/GoldPreOpen
- ingest notes: TRAPS: use period1/period2 not range=max for daily; keep UA 'Mozilla/5.0 (SuryaDhana-GoldDesk)' and host query2; never run a second poller from this IP; stale-while-revalidate cache already in gold_preopen.py

### Yahoo Finance: dollar index DX-Y.NYB and FX basket EURUSD=X, JPY=X, GBPUSD=X, CAD=X, SEK=X, CHF=X, CNY=X, INR=X
- publisher: Yahoo Finance (ICE, interbank quotes) · url: https://query2.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?period1=631152000&period2=<now>&interval=1d
- access: FREE · frequency: intraday / daily · lag: delayed · history: 1990 (DXY), 1996-2003 (FX)
- verified: all 9 HTTP 200 (0.5-0.6 s); DX-Y.NYB 9,381 daily rows from 1990-01-01, last 101.69; EURUSD=X 1.1221, JPY=X 157.11, CNY=X 6.6606, INR=X 94.93; FX prints Sun 22:00 UTC onward (latest 2026-10-26)
- terms: Yahoo ToS
- what it tells: The dollar (DXY) and the six-currency basket for the KGX decomposition; CNY/INR for gold in local currency
- how pros use it: DXY Curncy; Kitco KGX; gold in EUR/CNY/INR
- evidence of value: G-STUDY H2: beta ~ -1.0 in every regime
- **verdict: PUBLISH-CORE** — Inputs to the KGX bar and the gold-in-currencies panel (new information); DXY itself must not get a third tile
- already in app: DX-Y.NYB in WEI + GoldPreOpen; EURUSD=X in WEI + GoldPreOpen; INR=X in WEI/GoldPreOpen/MCXG; JPY=X, CNY=X in WEI
- ingest notes: same Yahoo job; FX quotes have no volume; weekend prints exist

### Yahoo Finance: ^GVZ, ^VIX, ^TNX
- publisher: Yahoo Finance (Cboe) · url: https://query2.finance.yahoo.com/v8/finance/chart/^GVZ?period1=631152000&period2=<now>&interval=1d
- access: FREE · frequency: intraday (US hours) / daily · lag: delayed · history: 2008 / 1990
- verified: HTTP 200 x3; ^GVZ 4,628 daily rows from 2008-06-03, last 24.34 (2026-10-23); ^VIX 19.45; ^TNX 4.988 (=4.99%)
- terms: Yahoo ToS
- what it tells: Same-day gold implied vol and 10y yield during US hours (FRED is next-day)
- how pros use it: GVZ Index, VIX Index
- evidence of value: GVZ expected move; nominal explains 75% of daily real-yield variance 2022-26, breakeven daily SD 3.1 bp
- **verdict: PUBLISH-CORE** — ^GVZ is the live expected-move input; ^TNX is the intraday real-yield proxy leg (^TNX - last T10YIE)
- already in app: ^TNX in WEI + GoldPreOpen; ^VIX in WEI; ^GVZ nowhere
- ingest notes: same Yahoo job

### Yahoo Finance: 30-day fed funds futures ZQ=F (continuous) and ZQZ26.CBT, ZQH27.CBT (months)
- publisher: Yahoo Finance (CME/CBOT quotes) · url: https://query2.finance.yahoo.com/v8/finance/chart/ZQZ26.CBT?range=5d&interval=5m
- access: FREE · frequency: intraday · lag: delayed · history: 2000 (ZQ=F)
- verified: ZQ=F HTTP 200 daily from 2000-09-01, last 96.10 (-> 3.90%); ZQZ26.CBT HTTP 200 5-min bars, last 95.96 (-> 4.04%) at 2026-10-25 22:07 UTC; ZQH27.CBT 429 in the first pass only; SR3Z26.CME 429 (UNVERIFIED)
- terms: Yahoo ToS; CME data via Yahoo
- what it tells: Market-implied average fed funds rate per month: 100 - price; Dec-26 at 4.04% vs EFFR 3.88% = +16 bp = 64% of one hike
- how pros use it: FFZ6 Comdty; FedWatch methodology
- evidence of value: consistent with Atlanta Fed (hike priced by Dec)
- **verdict: PUBLISH-CONTEXT** — Cheap implied-rate strip; the Atlanta Fed tracker gives the per-meeting probabilities with a distribution
- already in app: no
- ingest notes: symbol per month: ZQ + month code + yy + .CBT; roll monthly

### Yahoo Finance: GLD, TIP, IEF, GOLDBEES.NS
- publisher: Yahoo Finance · url: https://query2.finance.yahoo.com/v8/finance/chart/GOLDBEES.NS?period1=631152000&period2=<now>&interval=1d
- access: FREE · frequency: daily · lag: delayed · history: 2004/2003/2002/2009
- verified: all HTTP 200; GLD 5,517 daily rows from 2004-11-18, last 366.61; TIP 106.24; IEF 91.05; GOLDBEES.NS 4,388 rows from 2009-01-02, last Rs 115.96 (2026-10-23)
- terms: Yahoo ToS
- what it tells: GLD price (cross-check vs SPDR NAV), TIPS vs Treasury ETF ratio (intraday real-yield direction), the NSE gold ETF (Indian gold price proxy during NSE hours)
- how pros use it: GLD US Equity; TIP/IEF ratio
- evidence of value: context
- **verdict: PUBLISH-CONTEXT** — Cross-checks; GOLDBEES is an Indian-hours gold proxy worth a line on the INR panel
- already in app: no
- ingest notes: same Yahoo job

### Yahoo Finance symbols NOT verified today: PA=F, ^FVX, ^TYX, ^IRX, ^OVX, AUDUSD=X, BZ=F, IAU, ZT=F, ZN=F, SR3Z26.CME, GOLDIETF.NS, ^NSEI (429 in the first pass, not retried); XAUUSD=X
- publisher: Yahoo Finance · url: https://query2.finance.yahoo.com/v8/finance/chart/PA=F
- access: UNVERIFIED · frequency: - · lag: - · history: -
- verified: 429 'Too Many Requests' with a Chrome UA, not retried with the app UA; XAUUSD=X retried: HTTP 404 {'code':'Not Found','description':'No data found'} - the symbol does not exist on Yahoo
- terms: Yahoo ToS
- what it tells: palladium, 5y/30y/13w indices, oil vol, AUD, Brent (BZ=F is used by the app and works there), iShares gold, 2y/10y note futures, SOFR futures, ICICI gold ETF, NIFTY
- how pros use it: -
- evidence of value: -
- **verdict: LINK-ONLY** — Expected to work with the app UA (BZ=F does in production) but not verified in this run; XAUUSD=X must not be used
- already in app: BZ=F in WEI/CMDT
- ingest notes: retry with the app UA at 6 s spacing before use

### Atlanta Fed Market Probability Tracker - historical data xlsx
- publisher: Federal Reserve Bank of Atlanta (CenFIS) · url: https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx
- access: FREE · frequency: daily (business days) · lag: 1-2 business days (22 Oct carried on 26 Oct morning IST) · history: 2023-03-29 onward
- verified: HTTP 200, 1.8 s, 7,118,990 bytes; sheets LICENSE / DICTIONARY / DATA; DATA columns date, reference_start, target_range, field, value; 316,010 rows 2023-03-29 -> 2026-10-22; fields 'Prob: cut', 'Prob: hike', 'Prob: <range>', 'Rate: mean/mode/25th/75th'; latest: target 375-400 bps, Dec-16-2026 window P(hike) 86.9%, P(cut) 4.5%, mean 417 bp; Mar-27 mean 437; Sep-27 456. Page https://www.atlantafed.org/cenfis/market-probability-tracker HTTP 200 (3.4 MB)
- terms: Atlanta Fed site terms; LICENSE sheet present but unreadable by script - check
- what it tells: Per-meeting probability of a cut/hike and the full rate distribution implied by 3-month SOFR options - what CME FedWatch shows, from an official free source
- how pros use it: FedWatch / WIRP on Bloomberg
- evidence of value: methodologically standard (SOFR options); not a predictor of gold per se - it is the Fed-expectations input
- **verdict: PUBLISH-CORE** — FedWatch is unreachable (403, IP blocked) and has no API; this is official, daily, with history since 2023
- already in app: no (GoldPreOpen links FedWatch as a manual check)
- ingest notes: download daily 06:30 IST, parse only the DATA sheet (7 MB), keep rows for the latest asof; LICENSE sheet text is not machine-readable (image/text box) - a human must read it before publishing

### CME FedWatch tool page and CME internal quotes endpoint
- publisher: CME Group · url: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
- access: BLOCKED · frequency: - · lag: - · history: -
- verified: page HTTP 403 (600-char body); https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/305/G HTTP 403 with body 'This IP address is blocked due to suspected web scraping activity associated with it on this CMEgroup.com property'
- terms: CME terms prohibit automated access/redistribution
- what it tells: Meeting-by-meeting hike/cut probabilities (web only)
- how pros use it: browser only
- evidence of value: -
- **verdict: LINK-ONLY** — No free API, terms forbid scraping, and this IP is on CME's block list - owner action; use the Atlanta Fed tracker + ZQ futures instead
- already in app: GoldPreOpen MANUAL_CHECKS link
- ingest notes: find and stop whatever process hit cmegroup.com from this IP; the block will also affect COMEX settlement/OI scrapes

### Federal Reserve Board FOMC calendar page
- publisher: Federal Reserve Board · url: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- access: FREE · frequency: updated when the schedule changes · lag: none · history: page lists 5+ years
- verified: HTTP 200, 587 ms; fomc-meeting__date entries present; already parsed by markets.parse_fomc; next decision 28 Oct 2026 14:00 ET = 23:30 IST
- terms: public domain
- what it tells: Meeting dates (SEP meetings starred)
- how pros use it: FOMC dates; decision at 14:00 ET
- evidence of value: event timing
- **verdict: PUBLISH-CONTEXT** — Already in the app (WEI strip, BRF, ECO) - link to ECO, do not re-fetch
- already in app: markets.py /fomc; WEI, BRF, ECO
- ingest notes: none (exists)

### Forex Factory economic calendar JSON (this week)
- publisher: Forex Factory / Fair Economy (nfs.faireconomy.media) · url: https://nfs.faireconomy.media/ff_calendar_thisweek.json
- access: FREE · frequency: weekly file, refreshed continuously · lag: none for the schedule; consensus updates during the week · history: current week only (no archive)
- verified: HTTP 200, 304 ms, 96 events; keys exactly title,country,date,impact,forecast,previous (NO 'actual' key in any event this morning); sample: 2026-10-28T14:00:00-04:00 USD High 'Federal Funds Rate' forecast 4.00% previous 4.00%; 2026-10-29T08:30:00-04:00 'Core PCE Price Index m/m' 0.3% vs 0.2%, 'Advance GDP q/q' 3.2% vs 1.5%; ff_calendar_nextweek.json HTTP 404
- terms: Forex Factory: personal use, must cache, no hammering, no resale
- what it tells: When US (and other) releases hit, their impact rating, consensus and previous - in IST after conversion: FOMC Wed 23:30, GDP/Core PCE Thu 18:00
- how pros use it: ECO <GO> on Bloomberg
- evidence of value: event risk is the one macro effect every trader experiences; the surprise (actual - consensus) is the tradable quantity
- **verdict: PUBLISH-CORE** — Fills the ECO gap (no US CPI/NFP/PCE) with consensus; BLS schedule pages are 403 for scripts
- already in app: no (ECO has India + RBI + Fed decision dates only)
- ingest notes: fetch hourly, cache, convert -04:00/-05:00 offsets to IST; verify whether 'actual' appears after release before promising it; only thisweek exists

### BLS news release schedule pages (CPI, Employment Situation, schedule home, 2026_sched)
- publisher: US Bureau of Labor Statistics · url: https://www.bls.gov/schedule/news_release/cpi.htm
- access: BLOCKED · frequency: - · lag: - · history: -
- verified: HTTP 403 on all four pages even with a browser-like User-Agent (BLS bot wall)
- terms: public domain content, automated access blocked
- what it tells: Official CPI/NFP release dates and times
- how pros use it: BLS calendar
- evidence of value: -
- **verdict: LINK-ONLY** — Blocked for scripts; use ForexFactory/BEA for dates and open BLS in the browser
- already in app: no
- ingest notes: do not scrape

### BLS public API v1 (no key) - CPI-U NSA CUUR0000SA0
- publisher: US Bureau of Labor Statistics · url: https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0
- access: FREE · frequency: monthly · lag: ~2 weeks after month end · history: 10 years per query
- verified: HTTP 200, 4.5 s, status REQUEST_SUCCEEDED; latest 2026-M09 = 336.940, M08 334.980, M07 333.918
- terms: public domain; API usage policy
- what it tells: The CPI level straight from the source (no key); v2 with a free key gives 500 queries/day
- how pros use it: CPI YoY
- evidence of value: context
- **verdict: PUBLISH-CONTEXT** — Same numbers as FRED CPIAUCSL (SA) / NSA; useful as the official value on release day
- already in app: no
- ingest notes: 25 queries/day/IP, 3 years per request default; GET works for one series

### BEA news release schedule page (PCE = Personal Income and Outlays, GDP)
- publisher: US Bureau of Economic Analysis · url: https://www.bea.gov/news/schedule
- access: FREE · frequency: annual schedule, updated as needed · lag: none · history: 2025/2026/2027 schedule tabs
- verified: HTTP 200, 1.5 s, 71 KB HTML; parsed text: 'October 29 8:30 AM - GDP (Advance Estimate), 3rd Quarter 2026', 'October 29 8:30 AM - Personal Income and Outlays, September 2026', 'November 4 8:30 AM - U.S. International Trade ...'
- terms: public domain
- what it tells: Official PCE and GDP release dates/times
- how pros use it: BEA calendar
- evidence of value: event timing
- **verdict: PUBLISH-CONTEXT** — Official source for PCE dates (BEA API needs a free UserID key for the values)
- already in app: no
- ingest notes: HTML; strip tags, regex 'Month D H:MM AM ... Personal Income and Outlays'

### FRED releases calendar HTML page
- publisher: FRED · url: https://fred.stlouisfed.org/releases/calendar
- access: FREE · frequency: - · lag: - · history: -
- verified: HTTP 200, 987 ms with a plain client (timed out with a browser UA); release names present (Consumer Price Index, Employment Situation, Personal Income and Outlays, H.10, H.15, H.6, GDP) but dates are rendered client-side - only 3 date tokens in the HTML
- terms: FRED terms
- what it tells: Would give all release dates in one place; needs the key-gated releases/dates API to be useful
- how pros use it: -
- evidence of value: -
- **verdict: LINK-ONLY** — Not parseable without the FRED key
- already in app: no
- ingest notes: with FRED_API_KEY: /fred/releases/dates

### Geopolitical Risk index - monthly xls (Caldara & Iacoviello)
- publisher: Dario Caldara and Matteo Iacoviello (matteoiacoviello.com) · url: https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls
- access: FREE · frequency: monthly · lag: first days of the following month · history: 1985 (GPR), 1900 (GPRH)
- verified: HTTP 200, 1.6 s; 1,521 rows; columns month, GPR, GPRT, GPRA, GPRH, GPRHT, GPRHA, SHARE_GPR, N10, ..., GPRC_<country>; latest 2026-09-01 (GPR 146.2 = 90th percentile since 1985; Aug 125.6)
- terms: free with citation
- what it tells: How much war/terror/military-threat news there is versus the 1985-2019 average (=100)
- how pros use it: cited in sell-side gold notes as 'geopolitical premium'
- evidence of value: Caldara & Iacoviello 2022 AER (effects on activity/investment); our gold test negative
- **verdict: PUBLISH-CONTEXT** — G-STUDY H4: no explanatory (t 0.8, R2 0.001) or predictive (t 1.0) power for monthly gold - an explainer and historical ruler, not a signal
- already in app: no (GoldPreOpen counts risk headlines live)
- ingest notes: xls via xlrd; month column; cite the authors

### Geopolitical Risk index - daily recent xls
- publisher: Caldara & Iacoviello · url: https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls
- access: FREE · frequency: daily values, file updated about weekly · lag: ~1 week (19 Oct carried on 26 Oct) · history: 1985 onward (despite the 'recent' name)
- verified: HTTP 200, 2.1 s; 15,267 rows 1985-01-01 -> 2026-10-19; columns DAY, N10D, GPRD, GPRD_ACT, GPRD_THREAT, date, GPRD_MA30, GPRD_MA7, event; latest GPRD 248.7 (98th percentile), MA30 176.0 (96th); labelled events e.g. 2022-02-25 'Russia / Ukraine Tensions'
- terms: free with citation
- what it tells: Daily news-based geopolitical stress with threat/act split
- how pros use it: same
- evidence of value: as monthly
- **verdict: PUBLISH-CONTEXT** — Too late for the day's trading (use the app's live headline count); good for 'how unusual is this week'
- already in app: no
- ingest notes: weekly Mon job; DAY as yyyymmdd int

### SPDR Gold Shares (GLD) historical archive xlsx via api.spdrgoldshares.com
- publisher: State Street Global Advisors / World Gold Trust Services · url: https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en
- access: FREE · frequency: daily · lag: next morning IST (after NY 4:15 pm) · history: 2004-11-18 onward
- verified: HTTP 200, 0.6-0.7 s, xlsx 542 KB; sheets 'Disclaimer', 'US GLD Historical Archive'; 5,720 daily rows 18-Nov-2004 -> 22-Oct-2026; columns Date, Closing Price, Ounces of Gold per Share, NAV/Share 10:30am, Indicative Price 4:15pm, Mid, Premium/Discount, Daily Share Volume, Total Ounces, Tonnes of Gold, Total NAV; latest tonnes 1,045.64 (20 Oct 1,060.18, 21 Oct 1,057.62). The old CSV URL spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv returned HTTP 200 but a PDF.
- terms: Disclaimer: 'Reproduction or redistribution of any of this information is expressly prohibited without prior written consent'
- what it tells: Physical gold held by the largest ETF - Western investment demand; -8.3 t this week, -10.3 t 1m, -24.9 t YTD; 2026 high 1,101.3 t (27 Feb); ATH 1,353 t (Dec 2012)
- how pros use it: GLD tonnes on Bloomberg (ETF holdings screens); WGC flows
- evidence of value: own correlation test above
- **verdict: PUBLISH-CONTEXT** — Weekly tonnes change correlates 0.33-0.37 with the same week's gold return and ~0 with the next week: it confirms, it does not lead; AND the Disclaimer states reproduction/redistribution is prohibited without consent - display only, flagged for the owner (the flows agent owns the deep dive)
- already in app: GoldPreOpen manual-check link
- ingest notes: xlsx via openpyxl; skip the Disclaimer sheet and preamble; dates '18-Nov-2004'; daily 06:30 IST

### iShares Gold Trust (IAU) holdings CSV (ajax)
- publisher: BlackRock iShares · url: https://www.ishares.com/us/products/239561/ishares-gold-trust-fund/1467271812596.ajax?fileType=csv&fileName=IAU_holdings&dataType=fund
- access: UNVERIFIED · frequency: daily snapshot · lag: - · history: snapshot only
- verified: HTTP 200 but the body is the HTML product page, not a CSV (ajax id wrong or bot gate); product page itself HTTP 200 (1.6 MB)
- terms: iShares site terms
- what it tells: Would give today's IAU ounces (no history)
- how pros use it: -
- evidence of value: -
- **verdict: LINK-ONLY** — Not verified; GLD archive already covers the ETF driver
- already in app: no
- ingest notes: find the correct ajax id on the product page if wanted

### World Gold Council Goldhub pages: ETF holdings & flows, gold prices in currencies, GRAM
- publisher: World Gold Council · url: https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows
- access: FREE-REGISTRATION · frequency: monthly (flows), daily (prices) · lag: monthly report ~1 week after month end · history: -
- verified: ETF flows page HTTP 200 (66 KB, downloads behind a free Goldhub login; only a 'template' xlsx link in the HTML); gold prices page HTTP 200 (same); GRAM research page at the guessed URL HTTP 404
- terms: WGC terms: no redistribution
- what it tells: Global ETF flows by region, gold in every currency, central-bank demand (Gold Demand Trends), the GRAM driver-attribution framework
- how pros use it: Goldhub, GRAM monthly attribution
- evidence of value: WGC GDT: central banks >1,000 t/yr 2022-24 (the H1 breakdown explanation)
- **verdict: LINK-ONLY** — Registration required and WGC terms forbid redistribution; we compute gold-in-currencies ourselves; the flows/central-bank data belong to the supply-demand agent
- already in app: GoldPreOpen manual-check link
- ingest notes: owner may register (free) for personal downloads

### LBMA precious metal prices JSON (gold AM/PM, silver, platinum, palladium)
- publisher: LBMA (prices.lbma.org.uk) · url: https://prices.lbma.org.uk/json/gold_pm.json
- access: BLOCKED · frequency: - · lag: - · history: 1968+ on the site
- verified: HTTP 403 x5 with an HTML bot-challenge page (gold_am, gold_pm, silver, platinum_am, palladium_am)
- terms: LBMA: free for personal/non-commercial use, attribution, no redistribution
- what it tells: The official London benchmark fixes (the number most physical contracts settle on)
- how pros use it: GOLDLNPM Index
- evidence of value: -
- **verdict: LINK-ONLY** — Walled for scripts; LBMA terms allow personal viewing only, no redistribution
- already in app: no
- ingest notes: do not scrape; Yahoo GC=F is the stored daily benchmark

### World Bank Commodity Markets Outlook 'Pink Sheet' monthly prices xlsx
- publisher: World Bank · url: https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx
- access: FREE · frequency: monthly · lag: ~1 week (for the current file; this URL is stale) · history: 1960 onward
- verified: HTTP 200, 684 ms; sheet 'Monthly Prices' from 1960M01 with Gold ($/troy oz, monthly average), Silver, Platinum; BUT the file served at this URL ends 2024-12 (a Jan-2025 vintage)
- terms: CC BY-4.0
- what it tells: Longest free monthly gold history (1960->) for seasonality and long-run charts
- how pros use it: long-run real gold price charts
- evidence of value: G-STUDY H3 input
- **verdict: PUBLISH-CONTEXT** — Used for the seasonality study (1971-2024 + GC=F); monthly averages, not month-ends; find the current file URL before relying on it
- already in app: no
- ingest notes: header row 4 names, row 5 units, data from row 6; month as 'YYYYMmm'; CC BY-4.0

### Stooq daily CSV (xauusd, xagusd, xptusd, usdinr, dx.f)
- publisher: Stooq (stooq.com) · url: https://stooq.com/q/d/l/?s=xauusd&i=d
- access: BLOCKED · frequency: - · lag: - · history: -
- verified: HTTP 200 x5 but the body is an HTML page (robots noindex) instead of CSV - bot wall or daily cap
- terms: Stooq: personal use, daily download limit
- what it tells: Would give long daily spot-gold history
- how pros use it: -
- evidence of value: -
- **verdict: DO-NOT-PUBLISH** — Unreliable for scripts; not needed (Yahoo GC=F works)
- already in app: no
- ingest notes: do not use

### Kitco gold charts page
- publisher: Kitco Metals · url: https://www.kitco.com/charts/gold
- access: FREE · frequency: live · lag: - · history: -
- verified: HTTP 200, 1.8 s, 119 KB HTML; prices/KGX rendered client-side from Kitco's own API; robots.txt HTTP 200 'User-agent: * Allow: /'
- terms: Kitco terms of use: no automated collection or republishing
- what it tells: Spot gold, gold in currencies, the Kitco Gold Index (gold vs a currency basket) - exactly what the owner asked for
- how pros use it: quick spot/KGX glance
- evidence of value: -
- **verdict: LINK-ONLY** — Kitco's terms prohibit scraping/republishing its data; the page's content is reproduced legitimately by our KGX decomposition and gold-in-currencies panels from Yahoo inputs
- already in app: GoldPreOpen manual-check link
- ingest notes: keep the link; do not fetch

### Cleveland Fed inflation expectations page
- publisher: Federal Reserve Bank of Cleveland · url: https://www.clevelandfed.org/indicators-and-data/inflation-expectations
- access: FREE · frequency: monthly · lag: mid-month · history: 1982+
- verified: HTTP 200, 1.1 s (HTML); the same model estimates are on FRED as EXPINF1YR..EXPINF30YR (verified 200, Oct 2026 = 2.73% 10y)
- terms: public
- what it tells: Model-based expected inflation and real-rate term structure
- how pros use it: Cleveland Fed expected inflation
- evidence of value: context
- **verdict: LINK-ONLY** — Use the FRED series instead of the page
- already in app: no
- ingest notes: via FRED

## Metrics

### 10y real-yield change and health flag (daily)
- definition: Change in the 10-year TIPS yield over 1 day / 1 week / 1 month in basis points, with the rolling 252-day correlation of daily gold vs real-yield changes as a 'driver health' badge
- formula: d_bp = 100*(DFII10_t - DFII10_{t-k}); health = corr_252(dln gold, dDFII10); supportive if d_bp < 0
- inputs: Treasury real curve CSV (same day), FRED DFII10 (history), Yahoo GC=F daily closes
- beginner: The real yield is what a safe US bond pays after inflation. When it rises, gold (which pays nothing) loses; when it falls, gold gains. The badge says how strongly that rule is working right now (-0.15 today = weakly).
- pro: 2010-21 weekly beta -9.9% per 100bp (t -12, R2 0.19); 2022-26 -5.0 (t -4, R2 0.06). Level fit sign-flipped since 2022 - never show a level fair value. Intraday proxy: ^TNX live minus last T10YIE (breakeven daily SD 3.1 bp).
- **verdict: PUBLISH-CORE** — The strongest classic daily driver, still significant on changes; the health badge prevents over-reading it

### Nominal = real + breakeven split (daily)
- definition: Decompose the 10y nominal yield change into its real-yield part and its breakeven (expected inflation) part
- formula: dDGS10 = dDFII10 + dT10YIE (identity); gold reaction ~ -9.4%*dnominal + 12.7%*dbreakeven per 100bp (2010-21 weekly)
- inputs: Treasury real + nominal CSV; FRED T10YIE
- beginner: A yield rise is bad for gold only if it is a REAL rise. If yields rose because inflation expectations rose, gold usually likes it. This shows which one happened.
- pro: Since 2022 the breakeven coefficient fell to +4.3 (t 1.8); TIPS liquidity premium distorts the split in stress.
- **verdict: PUBLISH-CONTEXT** — Explains the day's yield move; weaker in the current regime

### 'Gold or the dollar?' KGX-style decomposition (daily)
- definition: Split gold's USD return into the part caused by the dollar's move against a currency basket and the 'pure gold' part
- formula: usd_move = -sum(w_i * dln f_i) with DXY weights (EUR .576, JPY .136, GBP .119, CAD .091, SEK .042, CHF .036), f_i = USD per unit; pure_gold = dln(gold_usd) + usd_move; usd_effect = -usd_move; gold_usd = pure_gold + usd_effect
- inputs: Yahoo GC=F and 6 FX pairs
- beginner: If the dollar falls 1%, gold in dollars rises ~1% even if nobody bought gold. This bar shows how much of today's move was 'the dollar' and how much was 'gold itself'. Thu 22 Oct: gold -2.18% = gold selling -2.29% + dollar +0.10%.
- pro: Replicates Kitco's KGX concept with public inputs; exact in log returns; use trade weights for an alternative basket.
- **verdict: PUBLISH-CORE** — New information; the dollar beta is ~ -1 in every regime (H2), so this is the first question a desk asks

### Gold in INR, EUR, JPY, GBP, CNY (and landed INR/10 g) (daily)
- definition: Gold price converted into each currency; landed Indian price before duty/GST
- formula: gold_ccy = gold_usd * ccy_per_usd; landed_inr_10g = gold_usd * USDINR * 10 / 31.1034768; changes 1d/1w/1m/YTD
- inputs: Yahoo GC=F, INR=X, EURUSD=X, JPY=X, GBPUSD=X, CNY=X
- beginner: An MCX trader owns gold in rupees. Over the past year gold fell 3.3% in dollars but rose 4.6% in rupees because the rupee weakened. The Chinese price (-12% YTD) tells you whether the biggest physical buyer sees a bargain.
- pro: Landed Rs 122,144/10 g vs MCX Dec settlement Rs 146,079 (23 Oct) - the 19.6% gap (duty, GST, basis) is the MCX agent's number, already shown by the MCXG desk as implied premium.
- **verdict: PUBLISH-CORE** — Directly what the owner trades; not shown anywhere today

### 2-year yield as the Fed-expectations proxy (daily)
- definition: US 2y Treasury yield level and change
- formula: DGS2 (Treasury CSV same day); 10y-2y slope
- inputs: Treasury nominal CSV, FRED DGS2
- beginner: The 2-year yield is the market's bet on where the Fed will be over two years. 4.69% with the Fed at 3.88% means hikes are priced.
- pro: No free intraday 2y index on Yahoo; ZT=F futures price for direction intraday.
- **verdict: PUBLISH-CORE** — Cleanest daily free gauge of policy expectations; new to the app

### Fed-path probabilities per meeting (daily)
- definition: Probability of a cut / hike and the mean expected rate for each FOMC meeting window
- formula: Atlanta Fed MPT DATA rows for the latest asof: fields 'Prob: cut', 'Prob: hike', 'Rate: mean'; cross-check with ZQ: implied = 100 - price; hike odds ~ (implied - EFFR)/25bp
- inputs: Atlanta Fed xlsx (daily), Yahoo ZQ month contracts, FRED EFFR
- beginner: What the market thinks the Fed will do at each meeting, in percent. Today: 87% chance of a hike by the December window, mean 4.17%; Dec futures price 64% of one hike. Hikes are bad for gold.
- pro: MPT uses 3m SOFR options (full distribution); FedWatch uses fed funds futures with a step function; FedWatch is 403 + IP blocked.
- **verdict: PUBLISH-CORE** — Replaces the manual FedWatch link with official daily data

### US release calendar in IST with consensus (daily)
- definition: This week's US high/medium-impact releases converted to IST with consensus and previous, flagged by whether they land during the MCX session
- formula: ForexFactory JSON (country USD, impact High/Medium) -> IST = date + 9.5h (summer) / 10.5h (winter); in_session = 18:00 <= IST <= 23:30
- inputs: ForexFactory thisweek JSON, BEA schedule page, FOMC calendar (app)
- beginner: The US jobs, inflation and Fed decisions land at 18:00-19:00 IST (data) and 23:30/00:30 IST (Fed) - during or right at the end of MCX's evening session. Knowing the time and the expected number tells you when to be flat or small.
- pro: No 'actual' field in the feed; next-week file does not exist; BLS pages 403.
- **verdict: PUBLISH-CORE** — Fills the ECO gap; event risk is the one macro effect every gold trader meets

### GVZ expected move (rupees per lot) (daily)
- definition: One-day one-standard-deviation gold move implied by GVZ, expressed in %, $/oz, Rs/10 g and Rs per MCX lot, next to realised 20-day vol
- formula: sd_1d = GVZ/sqrt(252); usd = gold*sd_1d; inr_10g = mcx_price*sd_1d; per_lot = inr_10g * multiplier (GOLD 100, GOLDM 10, GOLDPETAL 1)
- inputs: Yahoo ^GVZ / FRED GVZCLS, GC=F, MCX settlement (gold_preopen), shared/mcx_specs
- beginner: GVZ 24 means gold is expected to move about 1.5% on a typical day - about Rs 2,200 per 10 g, or Rs 2.2 lakh on one 1 kg GOLD lot. Size positions so one such day is survivable.
- pro: 84th percentile since 2008; 2026 range 21-46; realised 20d 14.9% so implied is rich into FOMC.
- **verdict: PUBLISH-CORE** — The sizing number; nothing in the app shows gold's own volatility

### Gold/silver and gold/platinum ratios with percentiles (daily)
- definition: Ounces of silver (platinum) per ounce of gold, with the percentile since 2000
- formula: GC/SI, GC/PL; percentile = share of history <= today
- inputs: Yahoo GC=F, SI=F, PL=F
- beginner: Silver is half industrial, platinum mostly industrial. G/S 74 (median 70) says gold is a bit expensive vs silver; G/Pt 2.58 (95th percentile) says platinum is extremely cheap vs gold.
- pro: No evidence the ratio predicts gold; a relative-value tool for silver/platinum trades.
- **verdict: PUBLISH-CONTEXT** — Context only; no predictive claim

### Gold / M2 percentile (monthly)
- definition: Gold price divided by US M2 money stock, ranked since 1975
- formula: gold_usd / M2SL($bn); percentile since 1975
- inputs: Yahoo GC=F (or World Bank monthly), FRED M2SL
- beginner: The 'too many dollars' story. Gold is at the 98th percentile of its history versus the money supply - by this yardstick it is already very expensive, not cheap.
- pro: M2 lags ~4 weeks; untestable at monthly frequency with any power; 'net liquidity' (WALCL-RRP-TGA) has no OOS evidence.
- **verdict: PUBLISH-CONTEXT** — Narrative context, monthly view only

### Geopolitical risk percentile (GPR monthly and daily) (weekly)
- definition: Latest GPR and 30-day average ranked against history since 1985
- formula: percentile of GPR_t (monthly) and GPRD_MA30 (daily) in their histories
- inputs: GPR xls files
- beginner: How unusual the amount of war news is. 98th percentile this week means only 2% of days since 1985 had more. Gold did NOT reliably rise after such months historically.
- pro: H4: contemporaneous t 0.8, R2 0.001; next-month t 1.0; top-decile months +0.64% vs +0.53% average.
- **verdict: PUBLISH-CONTEXT** — Explainer, not predictor; the app's live headline count is the intraday gauge

### GLD tonnes change (1w / 1m / YTD) (daily)
- definition: Change in physical gold held by SPDR Gold Shares
- formula: tonnes_t - tonnes_{t-k}; weekly % change vs weekly gold return
- inputs: SPDR archive xlsx
- beginner: When Western investors buy the gold ETF, its tonnes rise. They have been selling: -8 t this week, -25 t this year.
- pro: Contemporaneous weekly corr 0.33 (0.37 since 2022), next-week -0.02: confirms, does not lead. SPDR disclaimer prohibits redistribution - display only.
- **verdict: PUBLISH-CONTEXT** — Confirming indicator with a terms flag; deep dive belongs to the flows agent

### Seasonality strip (month-of-year average) (monthly)
- definition: Average monthly log return and hit rate by calendar month, 1971-2026
- formula: mean and t of 100*dln(gold) by month; halves 1971-2000 / 2001-2026
- inputs: World Bank monthly 1971-2024 + Yahoo GC=F month-ends
- beginner: January has been the best month (+2.6% average, up 67% of years) and June the worst, but no month is reliable enough to trade on - it is a 55-year average, not a forecast.
- pro: H3: no month passes t>=2 in both halves; Aug t 2.8 and Jan t 3.0 in 2001-26 only; Baur's Autumn (Sep) effect t 1.6 overall.
- **verdict: PUBLISH-CONTEXT** — Context with an explicit caveat; never a gate

### Fair-value residual from real-yield/DXY regression (weekly)
- definition: Actual gold vs the value predicted by ln(gold) = a + b1*DFII10 + b2*ln(DXY) fitted on 2010-2021 (or trailing 3 years)
- formula: resid% = 100*(gold / exp(a + b1*DFII10 + b2*lnDXY) - 1)
- inputs: GC=F, DFII10, DX-Y.NYB
- beginner: The old rule of thumb says gold 'should' be about $790 at today's real yields - it is $4,000. The rule is broken, so this number must NOT be shown as 'fair value'; it would mislead.
- pro: H5: residual +408% today; year-end residuals 2022 +87%, 2023 +116%, 2024 +218%, 2025 +367%; trailing-3y refit has the wrong sign (+38.8%/100bp); residual does not predict 3m forward returns (t 0.15).
- **verdict: DO-NOT-PUBLISH** — Model invalid in the current regime; publish the driver-health panel (rolling correlations, regime betas) instead

### Driver-health panel (rolling correlations and regime betas) (weekly)
- definition: Rolling 252-day correlation of daily gold changes with real-yield and DXY changes, plus weekly betas by regime
- formula: corr_252(dln gold, dDFII10), corr_252(dln gold, dln DXY); weekly OLS betas 2003-09 / 2010-21 / 2022-26
- inputs: GC=F, DFII10, DX-Y.NYB
- beginner: Tells you which driver is 'in charge' now. Today gold tracks the dollar (-0.38) much more than real yields (-0.15), so watch DXY first.
- pro: Year-end values: real yield -0.54 (2019) .. -0.03 (2025), -0.15 (2026); DXY -0.43 .. -0.38. Dollar beta ~ -1 in every regime.
- **verdict: PUBLISH-CORE** — The honest replacement for a fair value; the key finding of the study

## Open questions

- REPORT.md was NOT written: the harness Write guard refused report files for subagents and I did not bypass it; the long-form report is the `summary` field - the orchestrator should save it to reports/gold_program/G-MACRO/REPORT.md (evidence files, scripts, study.json, tables/ and sources_verified.md are on disk there).
- Does ForexFactory's thisweek.json add an `actual` field after a release? None of the 96 events had one at fetch time (Monday morning) - verify before promising actual-vs-consensus on the page.
- The Atlanta Fed MPT xlsx has a LICENSE sheet whose text is not machine-readable (image/text box); a human must read it before the per-meeting probabilities go live.
- Why is this IP on CME's 'suspected web scraping' block list (403 on cmegroup.com)? Which process hit CME? It will affect any COMEX settlement/OI work by other agents.
- The World Bank CMO monthly file at the documented URL ends Dec 2024 (stale vintage); where is the current file if a 1971-> monthly chart is wanted?
- SPDR's disclaimer prohibits reproduction/redistribution without consent: is on-screen display inside the owner's private single-user terminal acceptable to the owner (legal reading, not technical)?
- Foreign M2 (ECB/PBoC/BoJ) for a 'global liquidity' line: FRED's series are dead since 2017-18; DBnomics/ECB SDW not verified today.
- Yahoo symbols not retried after the 429 pass (PA=F, ^FVX, ^TYX, ^IRX, ^OVX, AUDUSD=X, BZ=F, IAU, ZT=F, ZN=F, SR3Z26.CME, GOLDIETF.NS): expected to work with the app UA, unverified today; XAUUSD=X does not exist (404).
- The 19.6% gap between the landed rupee price (Rs 122,144/10 g) and the MCX settlement (Rs 146,079) exceeds duty+GST (~9%): the MCX/basis agent should confirm the 2026 customs duty and local premium.
- Which currency basket should the published KGX bar use - DXY weights (replicable, Europe-heavy) or Fed broad trade weights (includes CNY/INR, weekly lag)?

## Owner actions

- Decide the CME block: stop any scraper hitting cmegroup.com from this IP; use the Atlanta Fed Market Probability Tracker xlsx + Yahoo ZQ futures for Fed odds; open FedWatch in the browser only.
- FRED_API_KEY (and EIA_API_KEY) are not set in .env: either register the free FRED key (also unlocks ALFRED vintages for point-in-time backtests and the releases/dates calendar) or switch commodity.py's FRED leg to the key-free fredgraph.csv path that gold_preopen.py already uses (0.3-0.9 s today).
- Add US CPI / NFP / PCE / FOMC-in-IST to the ECO calendar from the ForexFactory JSON (hourly, cached, personal-use terms) + the BEA schedule page; BLS pages are 403 for scripts (link only).
- Approve the GOLD MACRO (GMAC) layout: driver strip, KGX 'gold or the dollar?' bar, gold in 5 currencies, Fed path, US calendar in IST, GVZ expected move per lot, collapsed monthly context, weekly driver-health panel - and the removal of the duplicated DXY/EUR/US10Y/silver rows from GoldPreOpen once the strip exists; replace the Fed-odds/real-yields/ETF-flows/GLD/Kitco manual links with data.
- Fix Yahoo history fetches: never use range=max for daily bars (it silently returns monthly/quarterly bars); use period1/period2; keep the app's own User-Agent and query2 (a browser UA from this IP got 429 on 37/37 requests).
- Create the DuckDB tables gold_macro_series / gold_macro_catalog / gold_us_calendar / gold_fed_path / gold_etf_holdings in data-service and schedule the jobs (03:00 Treasury+Yahoo+ForexFactory, 06:30 SPDR+Atlanta Fed, 21:30 FRED daily, Tue 03:00 H.10, Fri 03:00 WALCL/TGA, Mon 06:30 GPR daily, monthly 5th) - all outside the 07:45-09:20 and 18:30-21:15 IST freeze windows; store point-in-time.
- Read the Atlanta Fed LICENSE sheet and the SPDR disclaimer before those two panels go live (display-only; no re-serving).
- Keep any 'fair value from real yields' number OFF the terminal (study H5: the 2010-21 model implies $788; residual +408%; trailing refit has the wrong sign); approve the driver-health panel instead.
- Backfill histories once (all free): FRED full CSVs, Yahoo daily via period1/period2, SPDR archive 2004->, Atlanta Fed 2023->, GPR 1985->, World Bank monthly 1971->2024.
