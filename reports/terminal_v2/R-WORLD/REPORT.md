# R-WORLD — What the world's best would build, mapped onto SuryaDhana's 43 pages

Written Wed 4 Nov 2026, 22:30 IST, read-only against the live stack (ui-api :8010 build `20261025-223942-0ae66db`,
data 2026-11-04). Evidence: `reports/terminal_v2/R-WORLD/evidence/` (9 page screenshots + the audit report, 9/9 PASS,
0 console errors), the routers and components named inline, live GET payloads quoted inline, and four paced NSE probes
(§7). Nothing in the repository was modified; no POST was sent; no Yahoo call was made; no Breeze call was made.

## Executive summary (10 lines)

1. **Rating: 6.5 / 10 against "Bloomberg-class for this owner"** — world-class *honesty engineering* and EOD analytics; a
   Bloomberg-grade *options/vol* and *execution-journal* layer is the gap. Trader critic (15 Oct) already said it: "an
   EOD analyst's terminal with a paper ticket, not yet an intraday trader's terminal" (`reports/worldclass_program/critique_trader.md`).
2. Of 62 capabilities surveyed across Bloomberg, LSEG Workspace, TradingView, IBKR Risk Navigator, thinkorswim,
   Sensibull / Quantsapp / Opstra, SpotGamma / Unusual Whales and prop-desk in-house tooling: **HAVE 29 · PARTIAL 18 · MISSING 15** (§3).
3. **The owner's #1 ask (daily IV history) is buildable this week from data already on disk**: 208 cached UDiFF F&O
   bhavcopies for 2026 alone (`data/nse_archive/fo/`, 2024-07-08→), `option_chain.py` already computes Black-76 IV off the
   parity forward; only NIFTY/BANKNIFTY near-expiry ATM IV is kept (`option_history.json`). Per-strike, per-expiry, per-stock
   IV history is a nightly job + one table (§5 #1). Intraday IV needs Breeze (verified: 1-min option bars incl. **expired**
   contracts, `reports/breeze_catalog/INFY/`).
4. **"Who is driving NIFTY" exists as arithmetic** (MOV "Who moved the index", MEMB YTD attribution: INFY −11.4 pts of
   NIFTY IT YTD). What is missing is the *rolling* view with a leadership-change read and variance share (§5 #8, `DRVR`).
5. NSE publishes two files the terminal does not use yet and I verified tonight: **`Contract_Delta_DDMMYYYY.csv`** (NSE's
   own delta factor per contract, 6.9 MB, HTTP 200) and **`FOVOLT_DDMMYYYY.csv`** (NSE's EWMA volatility per underlying and
   future). They unlock futures-equivalent OI and a model-free delta for gamma-exposure proxies (§5 #4, #10).
6. UI 8/10, scalability 6.5/10, data-update 7/10, options/vol 5.5/10, execution-risk-journal 5/10 (§2, each with evidence).
7. Dealer-positioning products (SpotGamma HIRO/TRACE, Unusual Whales) **cannot be replicated honestly in India**: NSE has
   no dealer/customer split and no tape of option trades. A GEX-style proxy is possible and must carry `heuristic`.
8. The 25 capabilities are ranked in §5 by value to this owner (individual, NSE F&O + MCX gold, PAPER, ₹-scale, phone + Mac)
   and cost; 16 of 25 need **no new data source**, 6 need Breeze only, 3 need an owner decision (MCX terms, LLM provider, Excel).
9. Honesty carries over: every proposed panel is badged `signal` / `context` / `arithmetic` / `heuristic`; nothing proposed
   forecasts; the only `signal` candidate (excess carry) already exists and is pre-registered.
10. Biggest single risk to all of this: **no git remote and no off-machine backup** (unchanged since the 15 Oct critic).

---

## 1. What the world's best actually ship (the survey)

Function catalogues, with the source each comes from. Mnemonics marked † are from university Bloomberg guides, not a
terminal session (the same caveat the gold program's Appendix F carries).

| Vendor | Capability family | Named functions / features (source) |
|---|---|---|
| Bloomberg | Options & vol | OMON (option monitor), OV / OVME (pricer, Greeks, back-test), OSA (strategy P&L tables), SKEW (smile & surface), HIVG (historical implied vol), HVG (historical vol), OMST (most active options), OVDV (vol surface & trends), CIXS (custom skew index) — [Ithaca derivatives guide](https://libguides.ithaca.edu/bloomberg/derivatives), [Bloomberg webinar page](https://professional.content.cirrus.bloomberg.com/professional2023/insights/webinar/charts-of-the-week-technical-analysis-and-implied-volatility-in-the-equities-market) |
| Bloomberg | Index & flow | MEMB, MRR/GRR (member ranked returns), IMAP, MOV, WEI — [Delaware list](https://lerner.udel.edu/seeing-opportunity/bloomberg-functions-list/), [WealthHub cheat sheet](https://www.wealthhubtrading.com/articles/bloomberg-terminal-cheatsheet) |
| Bloomberg | Portfolio & risk | PORT (performance, attribution, scenario), MARS† (multi-asset risk scenarios), HEDG, FVD — [ISEG guide](https://iseg.libguides.com/c.php?g=706923&p=5094213), Ithaca |
| Bloomberg | Alerts / workspace / API | ALRT, BLP Launchpad, BQL / Excel BDP-BDH — Delaware, [EquityRef](https://equityref.com/cheat-sheets/bloomberg-terminal-shortcuts/) |
| LSEG Workspace | Options | real-time IV + Greeks per strike, ATM vol indices, **historical volatility surfaces by delta and moneyness**, Option Watch, Surface Volatility, Most Traded Options; Excel function library; CodeBook (Jupyter) — [LSEG equities](https://lseg.com/en/data-analytics/products/workspace/equities) |
| TradingView | Charts & alerts | server-side alerts on price / indicator / drawing / Pine condition, multi-chart layouts, bar replay, Pine v6 — vendor help ([multi-chart](https://www.tradingview.com/support/folders/43000578567-how-to-work-in-the-multi-chart-mode)) |
| IBKR | Risk Navigator | what-if portfolios, Greeks and beta-weighted exposure, P&L by underlying, stress / custom scenarios, risk alarms (vendor page returned 403 tonight; features as commonly documented) |
| thinkorswim | Analyze / OnDemand | Risk Profile (P&L vs price × date, probability of profit), Probability Analysis cone, thinkBack (historical option P&L), OnDemand session **replay** — [Analyze manual](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Analyze), [thinkOnDemand](https://tickertape.tdameritrade.com/tools/backtest-thinkondemand-15071) |
| Sensibull (India) | Retail options | option chain with Greeks & IV, PCR / IV change / PoP, Strategy Builder, OI charts incl. multi-strike, **IV chart (ATM IV vs price for NIFTY, BANKNIFTY and stocks)**, positions analysis, Easy Options, Verified P&L, broker integrations incl. ICICI Direct — [sensibull.com](https://sensibull.com/) |
| Quantsapp (India) | Pro options | option chain tagged "fresh money / exit", **IV rank & percentile**, Straddle Index, Trap Indicator, build-up cycle, Greek charts incl. higher-order, order-book buyer/seller initiative, multi-strike OI, strategy builder with margin — [quantsapp.com](https://www.quantsapp.com/) |
| Opstra (India) | Quant options | scanners, API access, volatility modelling, backtesting — [AlgoTest comparison](https://algotest.in/blog/opstra-vs-sensibull/) (competitor-written) |
| SpotGamma | Dealer positioning | HIRO (real-time hedging-flow estimate), TRACE (SPX heatmap), Equity Hub (levels for 3,500 names), Volatility Dashboard, TAPE (flow), Compass (scanner), Founder's Notes — [spotgamma.com](https://spotgamma.com/) |
| Unusual Whales | Flow | unusual-activity alerts, sweeps, block prints, dark pool; GEX secondary — [FlashAlpha comparison](https://flashalpha.com/articles/spotgamma-vs-unusual-whales-comparison) (competitor-written) |
| Koyfin | Research | dashboards, screener, estimates, transcripts, macro dashboards — [Koyfin](https://www.koyfin.com/blog/best-stock-charting-software/) |
| Prop desks (in-house) | Process | event-driven alerting, pre-trade risk gates, journal with attribution (beta/factor/alpha/cost/slippage), scenario & stress, tape replay, model governance (tracking bands, auto-demotion), research notebooks wired to the terminal (`docs/PRODUCT_STRATEGY.md` §3 already specifies four of these) |

What none of the vendors give India for free: consensus estimates, a news wire, a dealer/customer option split, an
outstanding-short-interest number. Say so on the page rather than approximate.

## 2. Ratings (0–10), each with its evidence

| Area | Score | Evidence (file / endpoint / screenshot) | What a 9 looks like |
|---|---|---|---|
| UI (terminal craft) | **8.0** | 43/43 pages 0 console errors (FINAL_REPORT §4); page-ready p50 41 ms / p95 191 ms; `evidence/options.png`, `derivatives.png`, `movers.png` — dense, source-chipped, every number dated; kit-only components. Debts: EQS not on the kit DataTable (FINAL_REPORT §8), OSTR margin is a loud ESTIMATE (`StrategyBuilder.tsx` l.365), RSK empty when the book is cash (`evidence/risk.png`), no saved workspaces, ⌘1–9 map unchanged | Launchpad-style saved layouts, linked symbol groups, option pages that feel like OMON+OVDV+SKEW in one |
| Scalability / resilience | **6.5** | Engineering critic re-score: FAST 7.5 · LIVE 5 · NEVER-LIES 8 · SURVIVES 4.5 · SCALES 7.5 (`critique_engineering.md`); single Mac mini, one DuckDB writer, 4 GB cap, OOM incident 15 Oct, 3-day silent outage 16–19 Oct (fixed with LaunchAgents); loop-stall watchdog; `/health` p95 0.8 ms under load; 178 rps 0 errors. **No git remote** | second machine or cloud standby, snapshot-based read replicas, every job idempotent with backfill (the gold jobs already are) |
| Data update | **7.0** | EOD pipeline isolated steps (`eod_steps.py`), NSE catch-up after downtime, participant OI, bhavcopy 2010→, F&O UDiFF 2024-07→, Breeze 1-min verified, gold 21 PIT tables; live chain depends on nseindia.com (my `vixhistory` probe got **503** tonight while `option-chain-contract-info` answered) ; IV history only NIFTY/BANKNIFTY ATM (`/api/derivatives/option-history`); no stock IV history, no intraday IV, no MCX options | per-strike PIT option store, intraday IV tape, every live NSE page snapshotted (dictionary trap #8) |
| Options / vol | **5.5** | OMON (chain, smile, walls, 1-y ATM IV/PCR, OVME pricer: `evidence/options.png`), OSTR (8 templates, B-76 Greeks, exact breakevens), EVTS implied event move (term-structure method, calibrated median 1.00), DERV PCR/VIX/term structure. Missing: IV surface history, IV rank by stock, skew / term history, RV-vs-IV, scanner, position Greeks, intraday IV, expiry-day desk (`GAPS.md` l.36 "IV surface / smile history: MISS-B(later)") | §5 #1–#7 |
| Index & flow intelligence | **7.0** | MOV contribution (live payload: HDFCBANK +35.9 pts of +149.75 on 4 Nov, explained 154.4), MEMB YTD attribution + weight-implied P/E, MKT regime/breadth/rotation, participant OI panel, DEAL/INSD/MRGN/HDS, FII study (no forecast, context). Missing: rolling driver view, variance share, futures-equivalent OI, options-side participant OI | §5 #8–#11 |
| Commodities | **7.5 (gold) / 3 (others)** | GOLD 9 sub-views, 21 PIT tables, COT, CME FTP, India ladder, honesty badges (`reports/gold_program/`); MCXG ticket; CMDT tiles. No MCX options, no silver/crude depth, calendar not on ECO/EVTS (PLAN §b) | §5 #12–#14 |
| Execution / risk / journal | **5.0** | PAPER enforced in code; costs ticket with real ICICI costs; RSK hist-sim VaR/ES, stress replays, drawdown ladder (equity only, "needs holdings"); Desk orders carry a `reason` (`shared/decision_desk.py` l.266); weekly journal is a deterministic template, no per-trade entries, no attribution, no tracking band (`reports/journal/2026-W44.md`; PRODUCT_STRATEGY §3.4–3.5 unbuilt) | §5 #15–#18 |
| Research & AI assistance | **6.0** | 23+ pre-registered studies with verdicts (RSCH), `docs/PROGRAMMATIC_DATA_ACCESS.md`, alpha_lab; no LLM analyst, no notebook client, no model-governance band | §5 #19–#21 |
| Platform (alerts, workspaces, mobile, API) | **6.5** | price/move alerts every minute via scheduler, Mac + Telegram, 20 bot commands; multi-window + session restore; prefs sync; CSV on every table; loopback API with Host guard. Missing: alerts on any series, saved workspaces, a phone view beyond text, Excel | §5 #22–#25 |

## 3. Capability map against the 43 pages (HAVE / PARTIAL / MISSING)

Pages: `ui/components/desktop/pages.ts`. Status is from the component or router named.

### 3a. Options & volatility
| Capability (best-in-class reference) | Status | Where / why |
|---|---|---|
| Option chain EOD + live, OI walls, PCR, max pain (OMON) | HAVE | OMON (`OptionChain.tsx`, `option_chain.chain`, `/api/market/option-chain/{sym}`) |
| Single-option pricer with Greeks (OV/OVME) | HAVE | OMON click-to-price (`ui/lib/black76.ts`) |
| Strategy builder, payoff, breakevens, Greeks (OSA, Sensibull/Quantsapp builder) | HAVE | OSTR (`StrategyBuilder.tsx`, `/api/options/strategy/analyze`) |
| Real SPAN + exposure margin on the builder | PARTIAL | OSTR "Margin & costs — ESTIMATE"; Breeze `margin_calculator` verified (`reports/breeze_catalog/INFY/REPORT.md` #7) but not wired |
| Implied event move into results (Bloomberg-style, term-structure method) | HAVE | EVTS → Options into results (`implied_event_move_term`) |
| ATM IV history (HIVG, Sensibull IV chart) | PARTIAL | NIFTY/BANKNIFTY near-expiry ATM only (`option_history.json`); no stocks |
| IV rank / percentile per underlying (Quantsapp) | PARTIAL | OMON shows IV rank 73 for NIFTY only |
| Smile today (SKEW) | HAVE | OMON volatility smile |
| Smile / skew / term-structure **history**, surface by delta (SKEW, OVDV, LSEG surfaces) | MISSING | `GAPS.md` l.36 |
| Realised vs implied, variance risk premium (HVG vs HIVG) | PARTIAL | DERV: VIX vs NIFTY RV20 only (`fo_analytics.q_vix`) |
| Intraday IV / straddle tape (Quantsapp Straddle Index) | MISSING | no intraday option store; Breeze path exists |
| Options scanner (OMST, Opstra/Quantsapp scanners) | MISSING | — |
| Position Greeks, P&L vs price × IV × time, probability cone (Risk Navigator, tos Risk Profile) | PARTIAL | math in OSTR for a hypothetical; no paper option book |
| Expiry-day desk (0DTE workflow) | MISSING | — |
| Dealer gamma exposure / hedge walls (SpotGamma) | MISSING (only a `heuristic` proxy is honest in India) | — |
| Options flow / sweeps (Unusual Whales) | MISSING — **no data in India** (no option trade tape); participant volume file is the closest | — |

### 3b. Index & flow intelligence
| Capability | Status | Where |
|---|---|---|
| Index contribution today (MEMB/MRR) | HAVE | MOV "Who moved the index", `/api/market/index-contribution` |
| YTD attribution, concentration, weight-implied P/E | HAVE | MEMB (`index-memb`: top-5 36.6 %, YTD explained −5.37 of −11.77) |
| Rolling driver view (1w/1m/3m), leadership change, variance share | MISSING | the owner's "which company is driving NIFTY now" |
| Breadth, regime, rotation, market map (IMAP) | HAVE | MKT (`market_monitor.py`), MOV internals |
| Participant OI (FII/DII/Pro/Client) futures | HAVE (context) | MKT panel, `nse_participant_oi`; FII study = no forecast |
| Participant OI options side, participant volumes, FII derivative stats (money-weighted) | PARTIAL | files catalogued in `docs/NSE_DATA_DICTIONARY.md` l.69–121, not all ingested |
| Futures-equivalent (delta-adjusted) OI, % of MWPL | MISSING | `Contract_Delta` verified tonight (§7) |
| Bulk/block/short-selling/insider/MTF | HAVE | DEAL, INSD, MRGN, HDS (beyond Bloomberg defaults) |
| World markets, GIFT gap, FX, commodities tape | HAVE | WEI, header tape |
| Consensus estimates (EE/ANR) | MISSING — paid only | log says so |

### 3c. Commodities
| Capability | Status | Where |
|---|---|---|
| Gold: COMEX/MCX/spot proxy, COT, physical, macro, contracts, learn | HAVE | GOLD (43rd page) |
| MCX gold ticket with sizing, session clock, holidays | HAVE | MCXG |
| MCX options chain / IV for gold, silver, crude | MISSING | no collector; mcxindia.com disallowed; Breeze MCX options unverified |
| Silver / crude / natgas desks | PARTIAL | CMDT tiles only |
| Commodity calendar in ECO/EVTS (FOMC, CPI, FND, tender, OPEC, EIA) | PARTIAL | on GOLD sub-views only (PLAN §b) |

### 3d. Execution, risk, journal
| Capability | Status | Where |
|---|---|---|
| PAPER-only enforcement, kill switch | HAVE | `execution.py`, `EXECUTION_LIVE_ALLOWED` |
| Cost-aware equity ticket (real ICICI costs) | HAVE | `/api/costs/ticket` |
| Pre-trade checks (edge/cost, liquidity, ban/ASM, limits, margin) | PARTIAL | flags exist; no single gate; no SPAN |
| Portfolio VaR/ES, beta, sector, stress replays, drawdown ladder (PORT/MARS) | HAVE (equity) | RSK (`riskdash.py`) |
| F&O risk: Greeks VaR, margin utilisation, IV stress | MISSING | — |
| Trade journal with thesis, tags, MAE/MFE, attribution (prop desk, Tradervue-class) | MISSING | weekly template only |
| Strategy tracking band + auto-demotion (model governance) | PARTIAL | shadow NAV exists; no band |
| Tape replay (OnDemand, TradingView replay) | MISSING | tick store exists but "has never seen a live session" |
| Broker holdings live, TOTP auto-login | HAVE | BRKR, WTCH |

### 3e. Research & AI
| Capability | Status | Where |
|---|---|---|
| Pre-registered studies with verdicts, research library | HAVE | RSCH (`routers/research.py`) |
| Backtest lab, alpha lab, ML workspace | HAVE | BTST, ALFA, MLEN, GBOX |
| Programmatic access docs | PARTIAL | `docs/PROGRAMMATIC_DATA_ACCESS.md`; no client lib / notebooks |
| LLM analyst over the terminal's tables with citations (BQNT/CodeBook + "ask") | MISSING | — |
| News scanner with measured track record | HAVE (honest: random-like) | News overlay |

### 3f. Platform
| Capability | Status | Where |
|---|---|---|
| Price / % move alerts, Mac + Telegram, scheduler-driven | HAVE | ALRT, `alerts.py`, `master_controller.py` |
| Alerts on any stored series / event (ALRT, TradingView conditions) | MISSING | only price levels and moves |
| Command bar, aliases, multi-window, session restore, deep links | HAVE | GO bar, Tauri shell |
| Saved workspaces / linked groups (Launchpad) | PARTIAL | pins + watchlist |
| Phone | PARTIAL | Telegram text (20 commands); no charts, no page view |
| Excel / API (BDP/BDH, BQL) | PARTIAL | loopback REST, CSV export; no Excel functions |
| Settings sync, releases with rollback, watchdog, backups | HAVE | prefs, `build-ui`, LaunchAgents, 02:15 backup |

Totals: HAVE 29 · PARTIAL 18 · MISSING 15.

## 4. Ranking method

Value = how often the owner would use it on a trading day × how much it changes a decision (options day-trader, MCX gold,
paper). Cost: S ≤ 1 day · M 2–5 days · L 1–3 weeks · XL > 3 weeks, for one builder with this codebase's tests and gates.
Data column names the free or already-licensed feed; "paid" is said plainly. Badge = the label the panel must carry under
`reports/gold_program/PLAN.md` §0.1/§f.

## 5. The 25 capabilities (ranked within group; overall top-10 marked ★)

### (a) Options / vol

**#1 ★ `fo_iv_daily`: point-in-time option store with IV, Greeks and derived vol series — the owner's ask (M).**
Nightly from the cached UDiFF F&O bhavcopy (already downloaded every evening; `data/nse_archive/fo/2026/` has 208 files;
2024-07-08→). For every underlying × expiry × strike × right: close, settle, OI, ΔOI, volume, **IV** (Black-76 off the
parity forward, exactly `option_chain.chain`'s method, OTM side only), **delta** — twice: model delta and NSE's own delta
factor from `Contract_Delta_DDMMYYYY.csv` (verified tonight, §7), **NSE EWMA vol** from `FOVOLT_DDMMYYYY.csv` (verified).
Derived per underlying × expiry: ATM IV, 25Δ risk reversal (skew), 25Δ butterfly, IV term slope (front − second), expected
move; per underlying: IV rank / percentile 252 d, RV10/20/60 (Yang-Zhang from bhavcopy OHLC), IV − RV (variance risk
premium), straddle price at close. Columns `trade_date`, `release_at`, `first_seen_at` (PLAN §0.1.4). Backfill ≈ 550 files
× ~2 s. Then `/api/derivatives/iv-history/{sym}` and a `VOLH` view on OMON. Bloomberg HIVG/HVG; Sensibull "IV chart";
Quantsapp "IV rank & percentile". Badge `arithmetic` (IV), `context` (rank). Data: free NSE. Needs nothing new.

**#2 ★ `VOLS` page: surface, skew and term structure with history (M; depends #1).** Smile by delta (not strike) for each
expiry with yesterday's and last week's smile as ghosts; ATM term structure with the implied event variance already computed
for EVTS; 25Δ RR and BF history; a surface heatmap (expiry × delta); "where today sits" percentile per cell. Bloomberg
SKEW/OVDV, LSEG "historical volatility surfaces by delta and moneyness". Badge `arithmetic` / `context`. Free.

**#3 ★ Intraday IV tape from Breeze (M; needs a live Breeze session).** During 09:15–15:30 poll `get_option_chain_quotes`
(one call per right per expiry returns all strikes; fields verified in `samples/option_chain_near_call.json`: LTP, bid/ask,
OI, ΔOI, spot — **no IV, compute it**) for NIFTY + BANKNIFTY front two expiries every 2 min: 2 rights × 2 expiries × 2
indices = 8 calls / 2 min ≈ 1,500 calls/day, inside Breeze's documented 100/min and 5,000/day. Store `fo_iv_intraday`
(ATM IV, straddle, RR25, PCR, OI by strike) point-in-time. Alternative with zero REST quota: subscribe the ATM straddle
legs on the existing websocket tick engine (`live_ticks.py`, `LIVE_TICKS=1`) and compute IV from 1-min candles. Panel:
"IV today" line with session bands, straddle decay, OI-by-strike time-lapse. Quantsapp "Straddle Index"; Sensibull live IV.
Badge `arithmetic`. Caveat: Breeze's `get_quotes` hit "Limit exceed" on 28 Sep; option chain did not.

**#4 Dealer-positioning proxy: gamma exposure by strike (S–M; depends #1).** GEX_k = Σ OI × γ × lot × spot² × 0.01 with the
sign convention "writers are short"; plot by strike, the zero-gamma level, net GEX history. SpotGamma Equity Hub /
"hedge wall". **Honesty:** NSE publishes no dealer/customer split and no option trade tape, so the sign assumption is
unverifiable here; the panel carries `heuristic`, is never coloured bullish/bearish, and a study
(`reports/terminal_v2/.../PLAN.md`, pre-registered) must run before it can even become `context`. Participant OI
(Pro vs Client vs FII options long/short) is the only partial cross-check and should be shown beside it.

**#5 Options scanner `OSCN` (M; depends #1).** Rank the ~224 F&O underlyings on: IV rank, IV − RV, skew extreme, term
inversion (event priced), OI build-up class (long build-up / short covering / long unwinding / short build-up; the H2 study
found **no edge** — label `context`), unusual volume (÷ 20-d), % of MWPL (ban proximity; `fo_secban`), results within N
sessions (EVTS). Bloomberg OMST/OSA screens; Opstra/Quantsapp scanners. Free.

**#6 Paper option book + position Greeks + scenario grid (M; depends #1, #15).** Promote OSTR's math to a persisted paper
book (NIFTY/BANKNIFTY/stocks/MCX gold): aggregate Δ Γ Θ V per underlying and total, P&L vs spot (±5 %) × IV (±10 pts) ×
days grid, probability cone from the stored IV (risk-neutral, labelled), Greeks over time, real SPAN + exposure from Breeze
`margin_calculator` (replaces "ESTIMATE"). IBKR Risk Navigator, thinkorswim Risk Profile / Probability Analysis, Bloomberg
MARS. Badge `arithmetic`. PAPER only, never a live order.

**#7 Expiry-day desk `XPRY` (M; depends #3).** For the expiring series: straddle decay curve vs the day's realised range,
max-pain drift through the day, OI unwinding tape by strike, pin-risk strikes, "implied vs realised" scorecard kept
like the gold accuracy log (`h.accuracy`) so the expected-move claim earns or loses trust. India has more weekly expiries
than any market; this is the day-trader's page. Badge `arithmetic` (scorecard), `context`.

### (b) Index & flow intelligence

**#8 ★ `DRVR` index drivers (S–M).** The owner's "earlier Infosys drove NIFTY, now someone else": rolling contribution in
points and share for 1d / 1w / 1m / 3m / YTD from the rebuilt weights (`/api/market/index-contribution` already explains
+154.4 of +149.75 pts today), the leader table per window, a **leadership-change read** ("last 20 sessions: HDFCBANK
+x pts; prior 20: INFY −y pts"), each member's **share of index variance** (w·β·σ, covariance share over 60 d), the
top-5 concentration (36.6 % today) and the breadth of the move. Pure arithmetic on stored data; the "driver changed" line is
`context`, never a forecast (leadership is not momentum; S1's momentum sleeve already covers that question). Bloomberg
MEMB/MRR/IMAP, PORT attribution. Plus a BRF line and an alert (#22). Free. Alias `CBOS` reserved for the owner's wording
(open question §8).

**#9 Participant positioning, full (S).** Add the options side of `fao_participant_oi` (FII/DII/Pro/Client long/short
calls and puts), `fao_participant_vol` (who traded), and the money-weighted FII derivative statistics (dictionary l.115–121);
show net index-futures as % of OI with its own history and the week's change in words (the gold COT "who did what"
pattern). Badge `context` — the FII study FAILED as a forecast (`reports/fii_positioning/`).

**#10 Futures-equivalent OI and ban proximity (S).** From `Contract_Delta` (verified) × OI: delta-adjusted directional
exposure per stock, % of MWPL, days-to-ban trend; the F&O ban list already shows on OMON. Badge `arithmetic`. Free.

**#11 Overnight lead strip (S).** GIFT NIFTY gap (on the tape), US close, Asia open, USD/INR, Brent, gold — one "implied
open" line with a measured accuracy log (gold already does this). `heuristic`. Free (stored tape values; no new Yahoo caller).

### (c) Commodities

**#12 MCX options chain + IV for gold / silver / crude (M; owner decision O-8).** Breeze's SecurityMaster lists ~25k MCX
instruments and MCX gold 1-min futures are verified; whether `get_option_chain_quotes` serves MCX options is **unverified**
(docs chunk read tonight maps exchange `6` → Commodity but documents only NSE/NFO). The MCX bhavcopy (mcxindia.com) is a
disallowed host under the gold allowlist. Path: verify Breeze MCX options with one read-only probe on a trading day; if
yes, reuse #1/#3 with `exchange_code=MCX`; if no, the owner decides O-8. Badge `arithmetic`.

**#13 Commodity calendar into ECO / EVTS (S).** `gold_events` already holds FOMC / CPI / NFP / PCE in IST, COMEX FND/LTD,
MCX expiries and tender; add OPEC and EIA for crude; surface on ECO and EVTS (PLAN §b "planned, not in this release").
Badge `arithmetic`.

**#14 Silver and crude desks from the GOLD template (L).** The GOLD page is a template (catalog-gated panels, PIT tables,
COT from the same CFTC feed, CME FTP for OI). Silver first (same COT report family, MCX SILVER/SILVERM), crude second.
Badge rules carry over unchanged. Free sources already allow-listed.

### (d) Execution / risk / journal

**#15 ★ One pre-trade gate on every paper ticket (M).** PRODUCT_STRATEGY §3.2, still unbuilt as a single gate: edge ÷
cost (equity ticket has it), liquidity (order ≤ 1 % of 20-d ADV; for options the chain's bid-ask and depth), surveillance
flags (have), F&O ban (have), position / industry / drawdown limits (have on RSK), **real SPAN + exposure from Breeze**
(verified `margin_calculator`), tax lot (STCG/LTCG), and a REFUSE with the reason written to the journal. Every ticket
(equity profile, OSTR, MCXG) calls the same `/api/pretrade/check`. Badge `arithmetic`.

**#16 ★ Trade journal with attribution `JRNL` (M).** Per paper fill: thesis (free text + tag from a fixed list), invalidation
rule, planned vs filled, MAE/MFE while open, exit reason; P&L decomposed beta / factor (momentum) / alpha / cost /
slippage (PRODUCT_STRATEGY §3.4); expectancy and hit rate by tag, by hour, by DTE; weekly review prompts folded into the
existing Friday 20:10 journal (`scripts/journal_composer.py`). Prop-desk standard; Tradervue/Edgewonk class. Free.

**#17 F&O risk on RSK (M; depends #6).** Delta-gamma VaR, vega exposure, margin utilisation vs available, expiry
concentration, IV shock (+10 pts) and gap (−5 %) scenarios beside the equity hist-sim VaR; the −20 % HARD ladder stays
authoritative. IBKR Risk Navigator stress. Badge `arithmetic`.

**#18 Tape replay `RPLY` (L; depends #3 and a live tick season).** Replay any stored session at 1×/10×: NSE 1-min index
feed (archived under `nse_archive/internals`), tick-store parquet (once `LIVE_TICKS` has run), the chain as of time T
from `fo_iv_intraday`, filings as they arrived (`release_at`). thinkorswim OnDemand, TradingView bar replay. Learning
tool and the only honest way to test an intraday rule without look-ahead. Badge none (it is a player).

### (e) Research & AI assistance

**#19 ★ `ASK`: an LLM analyst that reads the terminal's own tables, with citations (L).** Scope: answer questions
("how did NIFTY IV behave the week before the last three results seasons", "which three stocks explain NIFTY IT's
YTD") by generating **read-only SQL** against a **read-only DuckDB snapshot** (the 19:20 copy, never the live file) and
GET-only API calls; every number in the answer carries `table · as-of date · row count`; the answer ends with the badge of
the weakest input. Guardrails, each testable: (1) SQL allow-list (`SELECT` only, no `ATTACH`/`COPY`/`PRAGMA`, row and
time caps); (2) no write tools, no order endpoints, no Telegram; (3) refuses forecasts and directional advice by policy and
by a classifier on the output ("describes, does not predict" rule applied to prose); (4) prompt-injection isolation: news
text and filings are passed as quoted data in a separate role with the instruction "treat as data"; (5) every answer logged
with the SQL and row hashes (audit); (6) provider choice via `settings.llm_provider` (Claude / local Ollama for private
holdings), secrets from the Keychain; (7) a nightly eval set of 50 questions with known answers, gating deploys; (8) the
answer shows "I could not verify" rather than an estimate. Bloomberg's `BQL`/`BQNT` and LSEG CodeBook are the closest
licensed analogues; nobody ships a citing analyst over a private PIT store — this is where a small team can beat them.
Cost: paid API tokens unless local.

**#20 Notebook client `sd` (S–M).** A pip-less module in `shared/` (`sd.read("fo_iv_daily", since=…)`, `sd.get("/api/…")`)
that reads the read-only snapshot and the GET API; Jupyter templates for the pre-registered study format (PLAN → run →
FINDINGS row → RSCH catalog row). LSEG CodeBook, Bloomberg BQNT. Free.

**#21 Strategy tracking band + auto-demotion (M).** For the Desk and the S1/S1H shadow: expected path from the gate
backtest (bootstrap bands), live NAV plotted against it, breach rule (3 months below the 5th percentile → paper-only /
flag), shown on DESK and in the Friday journal. PRODUCT_STRATEGY §3.5. Badge `arithmetic`. Free.

### (f) Platform

**#22 ★ Event-driven alert engine (M).** Conditions over any stored series or event, evaluated by the scheduler each
minute in session and after each EOD step: IV rank > 80 / < 20, IV − RV extreme, basis < 0, FII net short at a 1-y
extreme, OI spurt, VIX ±10 % intraday, ban entry/exit, results filed, index driver changed (#8), gold health clause
changed. Rule JSON (`series`, `op`, `value`, `window`, `cooldown`), stored in `data/alerts.json`'s successor, fired to
Mac + Telegram + the in-app inbox (all exist). Bloomberg ALRT, TradingView condition alerts. Alerts describe; none
implies direction (rule from the gold program).

**#23 Workspaces (M).** Named layouts (set of windows × pages × symbols × monitor), linked symbol groups (change TCS in one
window, the group follows), a "day-trader" and an "evening-analyst" default; stored in `/api/prefs` (exists). Bloomberg
Launchpad. Free.

**#24 Phone (M).** The Telegram bot gains chart PNGs (NIFTY intraday, IV today, DRVR) rendered server-side, and a
read-only PWA of BRF / WTCH / OMON-summary / alerts behind the same loopback (Tailscale or an SSH tunnel; never a LAN
bind — the 25 Oct security finding). Free.

**#25 Excel / Sheets functions (M; owner decision).** `=SD.PX("TCS")`, `=SD.HIST("NIFTY","atm_iv",…)` through Excel's
Power Query / Office Scripts against the loopback API with a local token; Bloomberg BDP/BDH. Needs the API to gain a bearer
token (today it is unauthenticated on loopback by design). Free.

## 6. Dependency order and a 12-week shape

Week 1–2: #1 → #2, #8, #10, #13 (all free, nightly jobs, four pages touched). Week 3–4: #3, #5, #9, #22. Week 5–7: #15,
#16, #6, #17, #21. Week 8–10: #19 (behind a flag), #20, #23. Week 11–12: #7, #24, #12 (after the Breeze MCX probe), then
#14, #18, #25 as capacity allows. Every job fetch-only, none inside the freeze windows, every table PIT with a catalog row,
every panel badged.

## 7. Verified sources (tonight's probes and in-repo evidence)

| Source | Exact URL / call | Fields | Cadence · publish (IST) | Verdict |
|---|---|---|---|---|
| NSE Contract_Delta | `https://nsearchives.nseindia.com/content/nsccl/Contract_Delta_DDMMYYYY.csv` | Date, Symbol, Expiry day, Strike Price, Option Type (FF/CE/PE), Delta Factor | daily, after close (today's file 04-11-2026 served, HTTP 200, 6.93 MB) | **VERIFIED — use** (circular CMPT68790) |
| NSE F&O daily volatility | `https://nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_DDMMYYYY.csv` | underlying and futures close, log return, EWMA daily vol (λ 0.995), annualised ×√365 | daily, after close (HTTP 200) | **VERIFIED — use** |
| NSE option-chain contract info | `https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY` (cookie-primed, browser UA) | expiryDates[], strikePrice[] | live | **VERIFIED** (18 expiries listed) |
| NSE India VIX history API | `https://www.nseindia.com/api/historical/vixhistory?from=&to=` | (not returned) | live | **503 tonight** — the terminal already stores INDIAVIX closes in `market_index_daily` from NSE index files; keep that path |
| NSE UDiFF F&O bhavcopy | `nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` | per contract: close, settle, OI, ΔOI, volume, underlying, lot | daily ~18:30–19:30 | in repo, cached 2024-07-08→ (`option_chain.py`) |
| NSE participant OI / volumes | `nsearchives.nseindia.com/content/nsccl/fao_participant_oi_DDMMYYYY.csv`, `..._vol_...` | Client/DII/FII/Pro × long/short, futures and options | daily evening | in repo (`nse_positions.py`); options side not surfaced |
| ICICI Breeze historical v2 (options) | `get_historical_data_v2(product_type="options", expiry_date, right, strike_price, interval="1minute")` | OHLC, volume, **open_interest** per bar; expired contracts served (Sep 2020/2023/2025 checked) | 1s/1m/5m/30m/1d, 1,000 bars per call | **VERIFIED in repo** 2026-09-28 (`reports/breeze_catalog/INFY/`) |
| ICICI Breeze option chain | `get_option_chain_quotes(stock_code, exchange_code="NFO", expiry_date, right)` | 26 fields: ltp, bid/ask + qty, OHLC, prev close, circuits, OI, ΔOI, spot — **no IV, no Greeks** | snapshot | **VERIFIED in repo**; compute IV ourselves |
| ICICI Breeze margin / charges | `margin_calculator`, `preview_order` | SPAN (INFY 1 lot ₹80,408), brokerage 0.25 % delivery | on demand | **VERIFIED in repo** |
| ICICI Breeze limits | docs: 100 calls/min, 5,000/day; 10 order requests/s | — | — | docs (api.icicidirect.com) |
| Vendor catalogues | links in §1 | — | — | web, dated 4 Nov 2026 |

## 8. Open questions for the owner

1. "CBOS": I could not find a product by that name; I read it as "a function that says which companies are driving NIFTY
   now" and reserved `DRVR` with alias `CBOS`. Did you mean something specific (CBOE? COBS?)?
2. MCX options: allow one read-only Breeze probe for MCX option chain/history on a trading day (decides #12 and O-8)?
3. The LLM analyst (#19): cloud model (paid tokens, holdings leave the Mac) or local Ollama (slower, private)? Both are
   provider-switchable via `settings.llm_provider`.
4. Excel (#25) needs the loopback API to gain a token. Worth it, or is CSV export enough?
5. Intraday IV (#3) spends ~1,500 of the 5,000 daily Breeze calls; acceptable beside the 08:00 login and the tick engine?
6. Git remote + off-machine backup remain undone (every critic since 15 Oct); the IV store adds another irreplaceable table.
7. Priority between the options program (#1–#7) and the journal/pre-trade gate (#15–#16)? I ranked options first because
   it is the daily workflow you described; the gate is what the strategy document says makes money.

## 9. Method notes and limits

- Read-only; GETs ≤ 2/s; four NSE probes with a browser UA and cookie priming; no Breeze session was used (22:xx IST, the
  daily token is normally expired); no Yahoo; no writes outside `reports/terminal_v2/R-WORLD/` and the scratchpad.
- Screenshots exclude PORT and BRKR; OSTR was not loaded in the browser because the page POSTs `/strategy/analyze` on
  load (a pure computation, but the rule says no POST).
- Vendor claims are from vendor pages or competitor comparisons and are cited as such; Bloomberg mnemonics come from
  public university guides, not a terminal session.
