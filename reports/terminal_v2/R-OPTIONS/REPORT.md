# R-OPTIONS — the options trader's day on SuryaDhana: audit, gaps, and the IV-history design

Date: Wed 4 Nov 2026, 22:20–23:10 IST (after the close; EOD data for 4 Nov already in the stack).
Scope: NIFTY / BANKNIFTY / FINNIFTY / stock options and futures for a day-to-day options trader and strategist.
Method: read-only — code (`services/data-service/option_chain.py`, `fo_analytics.py`, `nse_positions.py`, `main.py`,
`services/ui-api/routers/{derivatives,options_strategy,alerts,markets}.py`, `options_math.py`, `ui/components/{OptionChain,
StrategyBuilder,OptionPricer,DerivativesDesk,ParticipantPositioning,ResultsImpliedMoves}.tsx`), paced GETs on the live
stack (:8010), one audit run with screenshots (`/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-OPTIONS/shots/*.png`,
4/4 PASS, 0 console errors), six paced range-GETs on NSE archive files, and a six-call read-only ICICI Breeze probe through
the existing catalog helper (`scratchpad/R-OPTIONS/breeze_probe.py`, raw answers in `breeze_samples/`; no credential printed).

## Executive summary (10 lines)

1. **Verdict: the EOD foundation is Bloomberg-grade for India (OMON chain + OVME pricer + OSTR builder + DERV); the
   options trader's *day* is not covered.** Overall 5.5/10 for an options trader; 8/10 for an EOD analyst.
2. What exists and foots: EOD chain for 224 F&O underlyings (parity-forward Black-76 IV, OI walls, max pain, expected
   move), a live NSE chain in market hours (30 s), 578 sessions of NIFTY/BANKNIFTY ATM-IV/PCR/max-pain history, term
   structure / basis (2019→) / rollover / VIX-vs-realised, a 4-leg strategy analyser with exact breakevens and Greeks,
   participant positioning, and "options into results" implied moves (53 names tonight).
3. **IV history — the owner's explicit ask — is the biggest gap and the cheapest to close:** ATM-only, two indices, from
   2024-07-08 — while 1,182 older F&O bhavcopies (2019-10 → 2024-07, every strike, OI, close) sit cached and unread
   (`option_chain.FILE_RE` matches UDiFF names only). No term structure, no skew, no per-stock IV, no intraday IV.
4. **ICICI Breeze verified tonight as the licensed feed for everything intraday:** per-strike chain quotes with bid/ask/
   OI/ΔOI (60 strikes a side, 0.35 s), **expired** NIFTY weekly option 1-minute bars with OI (376 bars, 27 Oct 22900 CE),
   daily option bars, and `margin_calculator` returning real SPAN.
5. **Margin is wrong by ≈ 4.8×:** Breeze SPAN for a NIFTY 09-Nov iron condor is ₹81,497 (short put alone ₹1,72,461);
   OSTR's heuristic would show ≈ ₹3.9 L. Labelled ESTIMATE, but it mis-sizes every spread. Fix is free (Breeze) + offline
   (NSE SPAN file `nsccl.20261104.s.zip`, verified).
6. **No F&O paper book, no position Greeks, no what-if over time/vol, no options alerts, no expiry-day view, no option
   charts** — the things IBKR Risk Navigator / thinkorswim Analyze / Sensibull are used for every hour.
7. Honesty: footers say "context, not signals", and the product's own studies back it (FII positioning FAIL, OI-PCR no
   effect, VRP no effect on NIFTY, OI build-up no edge). Two colour violations of PLAN §0.1 rule 5 remain (PCR green ≥ 1,
   VIX turns red ≥ 80th pctile). "IV rank" is actually IV *percentile* — relabel.
8. The only F&O series with evidence of forecasting power in this repo is **excess carry** (alpha_lab Q1, t −4.2 / −2.9,
   Robust, lead only); it is on DERV as basis but not surfaced as a ranked screen.
9. Top five builds, in order: (1) point-in-time IV/skew/term archive from the files on disk, (2) IV dashboard + F&O IV
   screener, (3) real SPAN margin, (4) paper F&O book + Greeks aggregation + what-if, (5) intraday OI/IV tape from Breeze.
10. All of it is free or already licensed; nothing needs paid data. Historical tick/order-level data would (NSE ₹1.1 L/yr
    per segment) and is not needed for any item here.

---

## 1. The options trader's day (IST) and what the product gives at each step

| Time | What the trader needs | Have today | Evidence / gap |
|---|---|---|---|
| 07:30–08:45 | Overnight: GIFT NIFTY gap, US/Asia, VIX, yesterday's IV close vs 1-yr percentile, event list (RBI, US CPI, expiries, results), ban list | BRF, WEI, ECO, EVTS, OMON header (ban list), DERV VIX card | Expiry calendar is not on EVTS/ECO (`EventCalendar.tsx` KIND_ORDER has no EXPIRY); no "IV at yesterday's close vs percentile" line in BRF |
| 08:45–09:15 | Pre-open: expected move for the day from the near-expiry straddle, OI walls, where max pain sits vs spot, FII/Pro positioning change | OMON (EOD), DERV, MKT participants | Expected move is to *expiry* only (`expected_move_pct = atm_iv·√T`); no 1-day σ; no "straddle at 09:15 vs yesterday's close" |
| 09:15–09:45 | Open: live chain, OI build by strike, IV jump at the open, straddle price curve | OMON LIVE (NSE v3, 30 s, cached 30 s; no bid/ask) | NSE scrape is the only live path (`nse_live.NseLive`, 403/429 → 10-min circuit breaker); Breeze chain has bid/ask + OI and is unused |
| 09:45–15:00 | Manage a book: net Δ/Γ/Θ/V, P&L vs IV shift, roll decision, margin headroom, OI change tape, alerts on IV / OI walls / basis | OSTR (prices a hypothetical book only), alerts (price above/below/move only: `routers/alerts.py` `LEVEL_KEYS`) | **No paper F&O book**, no Greeks aggregation (RSK is cash VaR; ticket is `product_type="cash"`), no options alerts |
| 15:00–15:30 | Expiry-day: unwind vs max pain, straddle decay, pin risk, settlement | nothing specific | Breeze 1-min option bars with OI make a T-0 view possible (verified) |
| 15:30–19:30 | Post-close: EOD chain, IV change on the day, term structure, skew, IV percentile, results implied moves, participant OI, rollover | OMON EOD, DERV, EVTS implied moves, MKT participants — all through the 18:30 EOD pipeline (`eod_data_pipeline`) | Per-strike IV not stored; only ATM for 2 indices |
| Evening | Journal + research: what did IV do into/after the event, did the straddle overprice the move | RSCH verdicts | No event-vol history (IV before/after results per stock) |

## 2. What the best tools do (named function → what it is → India feed → status here)

### Bloomberg
| Function | What | India feed | Status |
|---|---|---|---|
| OMON | live chain, OI, IV by strike | Breeze chain quotes (live) / NSE v3 / UDiFF EOD | HAVE (EOD + NSE live); Breeze path missing |
| OVME | single-option pricer, Greeks, what-if IV/days | own Black-76 (`ui/lib/black76.ts`) | HAVE (`OptionPricer.tsx`) |
| OSA | option scenario analysis: multi-leg P&L over price × time × vol, position Greeks | own math (`options_math.py`) | PARTIAL: price × {today, expiry} only; no time grid, no vol shift, no book |
| OVDV / SKEW / TERM | vol surface, 25Δ skew, IV term structure, history of each | UDiFF + old F&O bhavcopies (every strike, 2019→) | **MISSING** (only ATM, 2 indices, 2024-07→) |
| HIVG / IVOL-HVOL / VCA | IV vs realised cone, IV percentile over 1y/3y | same + `nse_bhavcopy` closes | PARTIAL: DERV has VIX vs RV20; OMON has an IV *percentile* mislabelled "IV rank" |
| GV / WVOL | volatility monitor across underlyings (screen by IV percentile, IV−RV) | same archive, 224 underlyings | **MISSING** |
| CCRV | futures curve / carry | UDiFF | HAVE (DERV term structure; excess carry in alpha_lab) |
| OMST | most-active options / OI change leaders | UDiFF `TtlTradgVol`, `ChngInOpnIntrst` | PARTIAL (MOV has OI spurts from NSE live; no EOD leaders table) |
| PCR, max pain, OI by strike | description of writers | UDiFF | HAVE, honestly labelled |
| Event calendar vol crush | implied earnings move, IV before/after | own term-structure split (`implied_event_move_term`) | HAVE for results ahead; **no post-event history** |

### Retail / pro option platforms
| Product / feature | What a daily trader uses it for | Status here |
|---|---|---|
| Sensibull — Strategy builder, Positions Greeks, IV chart, OI change tape | build/track a book, net Greeks & P&L today / at expiry / at a date; IV history chart per underlying | builder HAVE; positions/Greeks **MISSING**; IV chart ATM-only |
| Quantsapp — IV percentile, OI analysis by strike through the day, straddle/strangle charts | intraday OI change by strike at 3/5-min; straddle price charts | **MISSING** intraday OI/straddle series (Breeze makes it possible) |
| Opstra (Definedge) — builder with P&L heat map (price × date), IV chart, FII data, option simulator | 2-D P&L, IV shift slider, multi-expiry | PARTIAL (1-D payoff, one expiry in UI; API accepts per-leg `days`) |
| Tradytics / Unusual Whales — options flow, net premium, GEX/dealer gamma | flow is US-only data (OPRA); GEX needs dealer-position assumptions | NOT applicable as-is; a *heuristic* "who is short options" from the NSE participant file is possible (Pro/Client/FII call & put short OI exist in `nse_participant_oi`) — badge `heuristic`, never a signal |
| IBKR Risk Navigator — portfolio Greeks, P&L vs underlying/vol/time, beta-weighted delta | the daily risk page | **MISSING** |
| thinkorswim Analyze — Add Simulated Trades, Risk Profile with price slices and date/vol sliders, Probability analysis | the what-if page | PARTIAL (OSTR lacks date/vol sliders, POP, price slices) |
| Expiry-day tools (Quantsapp max-pain tracker, Sensibull OI unwinding) | T-0 | **MISSING** |
| Margin/SPAN calculators (Zerodha, Sensibull, Upstox) | real margin incl. spread benefit | **MISSING** (heuristic ≈ 4.8× too high; Breeze returns SPAN) |
| Roll tools (ToS "Roll", Sensibull "Adjust") | roll a leg to the next expiry with net debit/credit | **MISSING** |

## 3. Audit of what exists (evidence)

### 3.1 OMON — option monitor (`ui/components/OptionChain.tsx`, `services/data-service/option_chain.py`)
- Payload tonight (`GET /api/market/option-chain/NIFTY`): date 2026-11-04, expiry 2026-11-09 (5 d), 18 expiries, lot 65,
  spot 23,960.60, forward 23,931.23 (put–call parity), ATM 23,950, ATM IV 13.9 %, expected move ±1.71 %, PCR 1.07,
  max pain 23,800, walls 25,000 / 23,000, 57 strike rows, 224 underlyings. Screenshot `shots/options-full.png`.
- IV: bisection on Black–Scholes with S_eff = F·e^(−rT), r 6.5 %, calendar days + ½ expiry day; OTM (and ≤ 3 % ITM) only;
  bounds reject sub-intrinsic prints. Live chain converts NSE OI contracts → shares with the bhavcopy lot (`live_frame`).
  Unit tests: `tests/unit/test_option_chain.py` (6).
- IV history panel: "IV rank 73 (share of the past year below today)". That definition is **IV percentile**; IV rank in
  every retail tool (tastytrade, Sensibull, Quantsapp) is (IV − 52-wk low) ÷ (52-wk high − low). Relabel or show both.
- Live mode: NSE `option-chain-v3`, 30 s TTL, cookie warm every 10 min, 403/429 → 600 s circuit breaker serving the
  last copy (`nse_live.py` 272–318). Good hygiene; but NSE's payload has no bid/ask and NSE is a scrape, not a licence.
- Colour: PCR coloured green when ≥ 1 (`OptionChain.tsx` ~line 252) — a context metric with a bullish colour (PLAN §0.1
  rule 5). Footer text is honest ("context, not signals").
- Rating **8/10** as an EOD chain; **6/10** as a live chain.

### 3.2 OVME pricer (`OptionPricer.tsx`)
Black-76 on the chain forward, Greeks, breakeven, N(d2) labelled "what the price implies, not a forecast", IV and days
editable, one long lot payoff today/expiry. Clean. Missing: short side and lots. **8/10.**

### 3.3 OSTR strategy builder (`StrategyBuilder.tsx`, `routers/options_strategy.py`, `options_math.py`)
- 4 legs, 8 templates, Black-76 Greeks per leg and net, exact piecewise-linear breakevens, bounded/unbounded max P&L,
  payoff grid with kinks as grid points, itemised statutory cost estimate (STT 0.1 % sell premium etc., FY25-26),
  `paper_only: true`. 18 unit tests (`services/ui-api/tests/test_options_math.py`). Screenshot `shots/ostrategy-full.png`
  (straddle 23950: debit ₹21,187, BE 23,624.1 / 24,276.0, θ −₹1,918/day, vega ₹1,521).
- **Margin:** `margin_estimate` = 12 % of notional per short leg + premium. For tonight's NIFTY 09-Nov condor (sell 23700
  PE / buy 23500 PE / sell 24200 CE / buy 24400 CE, 1 lot): heuristic ≈ 2 × 0.12 × 23,931 × 65 + premiums ≈ ₹3.9 L;
  **Breeze `margin_calculator` says SPAN ₹81,497.07** (`breeze_samples/margin_NIFTY_iron_condor.json`); a lone short
  23700 PE is ₹1,72,460.67. The label says ESTIMATE and `defined_risk_floor` is shown, but a trader sizing from the
  headline is 4.8× under-levered. Same finding as the worldclass trader critic (MED-3).
- Missing vs ToS/Opstra/IBKR: probability of profit (N(d2) exists in the lib), P&L at a chosen date (T+n) and IV shift,
  2-D heat map, multi-expiry in the UI (API has per-leg `days`), save as paper position, roll helper.
- Rating **7/10** (math 9, risk/margin 3, workflow 5).

### 3.4 DERV derivatives desk (`fo_analytics.py`, `DerivativesDesk.tsx`)
- Tonight: NIFTY near basis +0.81 % ann (19 d), next +4.25 %, far +4.97 %; rollover 10.4 % at T−19 vs 74.8 % average
  final; aggregate PCR 1.15 (2019→); VIX 15.27, 70th pctile 1y, 61st 5y, RV20 16.01, spread −0.74; VIX history from
  2014-08-05 (3,000 rows). Screenshot `shots/derivatives-full.png`. Data-grain honesty is in the module docstring and on
  the page ("near-month basis", "all-expiry aggregate PCR").
- Colour: VIX accent turns red at ≥ 80th percentile; "VIX below realized — complacent pricing" is an interpretation on a
  context card. Minor §0.1 rule-5 issues.
- Rating **8/10** for futures; the options half (PCR/max-pain history) is the ATM-only series again.

### 3.5 Positioning and event-vol panels (MKT, EVTS)
- `GET /api/market/participants`: FII index futures 13.6 % long, net −185,979 contracts (+49,063 over 5 d); options
  bull−bear net per participant. Verdict on the panel: "tested: does not predict NIFTY over 5–20 sessions (RSCH)"
  (`reports/fii_positioning/FINDINGS.md`: H1 −0.53 % t −1.34, H2 +0.05 % t 0.07). **Exemplary labelling.**
- `GET /api/market/results-implied-moves?days=10`: 53 F&O names; e.g. CUMMINSIND results 4 Nov, ATM IV 36.6 %, priced
  event move ±3.82 % vs usual ±2.83 % → 1.35×, method "term" (`implied_event_move_term`). Footer: "describes what the
  options charge, not which way the stock moves". **Exemplary.** Gap: no *history* of priced-vs-realised per stock.

### 3.6 Plumbing: data update, scalability, alerts, ticket
- EOD: `eod_data_pipeline` 18:30 IST → bhavcopy, F&O bhavcopy (UDiFF cached under `data/nse_archive/fo/<year>/`,
  1.3 GB, 1,760 files 2019-10→), participant OI (1,760 files), `option_history.json` refreshed in a background thread on
  first request, futures panel likewise. Tonight's chain history was ready at 21:49 (file mtime). Fine for an EOD desk.
- The chain endpoint loads a whole UDiFF zip into pandas per file (`lru_cache(maxsize=4)`); warm calls ~18 ms (critic
  measured), cold load seconds — acceptable, but a per-strike history over 1,760 files is impossible this way: it needs a
  stored, derived table (§5).
- Alerts: `routers/alerts.py` supports `above / below / move` on a Yahoo price only. No IV, OI, basis, straddle or ban
  alerts.
- Ticket / book: `routers/positions.py` and `scripts/live_execution.py` are `product_type="cash"`; the tick engine
  subscribes `product_type="cash"` only (`live_ticks.py` 311). No F&O instrument exists in any paper book.
- Tests: OMON 6, OSTR 18, DERV 15 unit tests; no UI `.check.ts` for the three pages.

## 4. Verified sources (tonight, 22:20–22:55 IST)

| Source | Exact URL / call | Fields (verified) | Cadence · publication (IST) | Terms | Verdict |
|---|---|---|---|---|---|
| ICICI Breeze `get_option_chain_quotes` | `stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date="2026-11-09T06:00:00.000Z", right="call"\|"put"` | 60 strikes/side: ltp, ltt, best_bid/offer price+qty, open/high/low/previous_close, open_interest, chnge_oi, total_quantity_traded, total_buy/sell_qty, spot_price, circuits (26 fields) | snapshot, 0.35–0.39 s; after close ltt 15:39:59; limits 100/min, 5,000/day (shared with every caller) | ICICI API T&C: own-account use, no redistribution | **PUBLISH-CORE** for intraday chain/OI/IV; poll ≤ every 2 min per (index, side, expiry) |
| Breeze `get_historical_data_v2` options | `interval="1minute"`, expired NIFTY 27-Oct-2026 22900 CE, 09:15–15:30 | 376 bars: OHLC, volume, open_interest (OI 9.36 M → 10.09 M on expiry day); daily 19 bars 29 Sep→27 Oct | historical, expired contracts included (INFY 2020/2023/2025 verified in `reports/breeze_catalog`); 1,000 bars/call, latest-first paging | same | **PUBLISH-CORE** for intraday IV history, straddle curves, expiry-day replay |
| Breeze `margin_calculator` | 4-leg condor + single short put, `"NFO"` | span_margin_required, non_span_margin_required, order_value | live, 0.3 s | same | **PUBLISH-CORE** for real margin |
| NSE SPAN risk-parameter file | `https://nsearchives.nseindia.com/archives/nsccl/span/nsccl.20261104.s.zip` | 206 Partial on range GET, application/zip, last-modified 17:02 IST | daily EOD (NCL also publishes intraday files; names not probed) | public, browser UA | **PUBLISH-CORE** (offline SPAN when the Breeze session is down) |
| NSE F&O daily volatility | `…/archives/nsccl/volt/FOVOLT_04112026.csv` | Symbol, underlying close, log return, previous/current daily vol (EWMA), futures vol | daily, 17:01 IST | public | **PUBLISH-CONTEXT** (NCL's own vol; a free realised-vol series per underlying) |
| NSE contract delta factors | `…/content/nsccl/Contract_Delta_04112026.csv` | Date, Symbol, Expiry, Strike, Option Type, Delta Factor | daily, 19:18 IST | public | **PUBLISH-CONTEXT** (delta-weighted OI without a model) |
| NSE combined delta-equivalent OI | `…/archives/nsccl/mwpl/combineoi_deleq_04112026.csv` | ISIN, Symbol, Notional OI, Futures-equivalent OI | daily, 19:18 IST | public | **PUBLISH-CONTEXT** (MWPL crowding) |
| NSE F&O ban list | `…/archives/fo/sec_ban/fo_secban_05112026.csv` (named for the next session) | 62 bytes: KAYNES, SAIL | daily, 19:24 IST | public | HAVE (OMON header) |
| NSE lot sizes | `…/content/fo/fo_mktlots.csv` | lot by expiry month | on change (30 Oct) | public | HAVE via bhavcopy `NewBrdLotQty` |
| NSE F&O bhavcopy (old format) | `…/content/historical/DERIVATIVES/2021/APR/fo01APR2021bhav.csv.zip` (cached) | INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN/HIGH/LOW/CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI (no underlying-price column) | archived 2019-10 → 2024-07-05 on disk (1,182 files) | public | **PUBLISH-CORE** — `nse_positions.parse_fo_bhavcopy` already parses it; extend IV history to 2019 |
| NSE option chain v3 | `www.nseindia.com/api/option-chain-contract-info` → `option-chain-v3?type=Indices&symbol=NIFTY&expiry=09-Nov-2026` | per strike CE/PE OI, ΔOI, impliedVolatility (NSE's), lastPrice, bid/ask, volume, underlyingValue | live, ~1 min delayed; not archived | scrape; 403/429 risk (handled) | KEEP as fallback only |
| INDIA VIX | `market_index_daily` via Yahoo `^INDIAVIX` (`ingest.py` 264); official daily file `…/content/indices/ind_close_all_DDMMYYYY.csv` includes INDIA VIX (dictionary entry; not re-probed tonight) | close | daily | public | move the VIX close to the NSE daily file (removes a Yahoo dependency) |

Not verified tonight (do not cite as fact): intraday SPAN file names, niftyindices.com VIX history download, NSE
participant-wise trading-volume file for options.

## 5. The IV history engine (the owner's ask) — a design that fits the repo

**Store, then show (PLAN §0.1 rule 3), point-in-time (rule 4).** Two DuckDB tables in `data/market.duckdb`, written by
the 18:30 EOD step after the F&O bhavcopy lands, plus one parquet stream for intraday:

1. `fo_option_eod` — per (date, symbol, expiry, strike, type): close, settle, OI, ΔOI, volume, **iv** (our Black-76 on the
   parity forward, the same code path as OMON), delta. Source: UDiFF (2024-07-08→) and the old format (2019-10→, spot
   from `nse_bhavcopy` EQ close for stocks and `market_index_daily` NIFTY50 for NIFTY; BANKNIFTY/FINNIFTY use the parity
   forward only, which `chain()` already prefers). Size: ~200k option rows/day; keep strikes within ±15 % of the forward
   and the first three expiries → ~25k rows/day, ~45 M rows for 7 years — fine for DuckDB; keep it out of the ui-api
   snapshot copy (memory `ui_api_snapshot_proxy`).
2. `fo_vol_surface_daily` — per (date, symbol, expiry): atm_iv, iv_25d_put, iv_25d_call, skew_25d, expected_move_pct,
   straddle_price, pcr_oi, max_pain, total_oi, dte, plus `release_at` (file publication time) and `first_seen_at`.
   ~700 rows/day. Every page reads this table.
3. `fo_chain_intraday` (parquet under `data/ticks/`, like the tick store): Breeze chain quotes every 2 min for the first
   two expiries of NIFTY / BANKNIFTY / FINNIFTY (6 calls per 2 min ≈ 1,100/day, inside the 5,000/day cap with headroom
   for the live-quote provider), each snapshot with `captured_at`. Derived per minute: ATM IV, 25Δ skew, straddle, PCR,
   max pain, OI change since open by strike — the OI tape and the intraday IV chart.
4. Backfill: one job over the 1,760 cached files (UDiFF era ≈ 1 min per `update_history`'s docstring; old format via
   `parse_fo_bhavcopy`) — outside the freeze windows, never beside the 02:15 backup.

Pages fed by it (all `arithmetic` or `context`, no composite score):
- OMON: IV term-structure strip (near/next/far ATM IV), 25Δ skew with its 1-yr percentile, **IV percentile and IV rank
  both**, IV vs 20/60-day realised cone, straddle price vs its history, the year chart extended to 2019.
- New **VOL screen** (Bloomberg GV/WVOL; Sensibull IV chart for all 224 underlyings): rank by IV percentile, IV − RV,
  term slope, skew; a "results in next 10 d" chip; export.
- DERV: VRP panel (VIX² − realised variance) labelled context with the alpha_lab Q3 verdict ("no effect" on NIFTY).
- EVTS: per-stock **vol-crush history** — ATM IV T−1 vs T+1 and priced vs realised move for the last 8 results.

## 6. Gap list, ranked by value for a day-to-day NSE options trader (cost: S ≤ 1 day · M ≤ 1 week · L ≤ 3 weeks · XL more)

| # | Gap | Feed (free / licensed) | Value | Cost | Badge |
|---|---|---|---|---|---|
| 1 | Point-in-time IV / skew / term archive from the files on disk (§5 tables 1–2) | cached NSE F&O bhavcopies 2019→ | XL | M | arithmetic |
| 2 | IV dashboard on OMON + VOL screener across 224 underlyings (IV pctile & rank, IV−RV, term, skew) | table 2 | XL | M | arithmetic / context |
| 3 | Real SPAN margin: Breeze `margin_calculator` when the session is live, NSE SPAN-file parser offline; keep the heuristic as last resort with its 4.8× warning | Breeze (verified) + `nsccl.YYYYMMDD.s.zip` (verified) | L | S (Breeze) + M (SPAN parser) | arithmetic |
| 4 | Paper F&O book: save an OSTR book as paper positions (PAPER ONLY enforced), mark daily from the EOD chain / Breeze quotes, aggregate net Greeks on RSK, P&L vs underlying × days × IV shift (Risk Navigator / Analyze) | own math + Breeze quotes | XL | L | arithmetic |
| 5 | Intraday OI / IV tape for the three indices (§5 table 3): OI change by strike since open, ATM IV and straddle through the day, Breeze bid/ask on OMON LIVE | Breeze chain quotes (verified) | L | M | context |
| 6 | Options alerts: IV percentile crosses, straddle price, OI wall moved, basis / rollover pace, ban-list entry/exit, results-in-N-days for held underlyings (controller job like `price_alerts_check`) | tables 2–3 | L | S–M | context |
| 7 | Expiry-day (T-0) view: OI unwind by strike, max-pain drift, straddle decay vs the historical expiry-day curve (Breeze 1-min bars of past expiries, verified) | Breeze history + table 3 | M | M | context |
| 8 | OSTR workflow: probability of profit (lib has N(d2)), P&L at T+n and ±IV sliders, 2-D heat map, multi-expiry legs in the UI, roll helper (close leg → next expiry, net credit/debit) | own math | M | M | arithmetic |
| 9 | Vol-crush history on EVTS (IV before/after results, priced vs realised, last 8 quarters per stock) | table 2 + `nse_results` | M | S–M | context |
| 10 | Option series in CHRT: straddle / strangle / single-option 1-min and daily candles with OI | Breeze history (verified) | M | M | arithmetic |
| 11 | Expiry calendar + ban list on EVTS/ECO (weekly NIFTY, monthly stocks, holiday shifts from the Breeze master) | bhavcopy expiries, `fo_mktlots.csv`, `fo_secban` | S | S | context |
| 12 | Delta-equivalent OI and NCL contract deltas as context columns on OMON/DERV (MWPL crowding, delta-weighted positioning) | `combineoi_deleq`, `Contract_Delta` (verified) | S | S | context |
| 13 | Excess-carry screen (the one Robust F&O lead: alpha_lab Q1) as a DERV table of discount-quintile names, verdict text attached, no colour | UDiFF + `nse_bhavcopy` | M | S | context (lead, not a rule) |
| 14 | "Who is short options" heuristic from participant OI (Pro/Client/FII call/put short), as a GEX-style context line | `nse_participant_oi` (have) | S | S | heuristic |
| 15 | Replace Yahoo `^INDIAVIX` with the NSE daily indices file | `ind_close_all_DDMMYYYY.csv` | S | S | — |
| 16 | MCX gold options | needs MCX bhavcopy / Breeze MCX (owner decision O-8) | later | — | — |

Needs paid data (stated plainly): historical tick / order-level options data (NSE ₹1.1 L/yr per segment), US-style
options flow (no equivalent in India). Nothing in rows 1–15 needs it.

## 7. Honest-labelling stance (what each number is, with the evidence)

| Item | Nature | Evidence |
|---|---|---|
| Greeks, payoff, breakevens, model price, expected move (IV·√T), straddle price, basis/carry, SPAN | **arithmetic** given a price and a model | `options_math.py` tests; Black-76 is a convention, not a forecast |
| Implied volatility, IV percentile / rank, term structure, 25Δ skew | **arithmetic** (price → vol); their *percentiles* are **description** of relative richness. IV mean-reverts (any GARCH / Heston fit), so a percentile frames premium selling vs buying, not direction | Goyal & Saretto (2009, JFE): IV−HV spread predicts *option* returns cross-sectionally in the US — a vol-selling result, not a direction call; untested on NSE |
| OI change, "long build-up / short covering" quadrants | **description** — tested, no edge, unstable | `docs/NSE_DATA_DICTIONARY.md` H2 row (line 629) |
| PCR (OI) | **description** — alpha_lab Q4 index OI-PCR percentile and 5-d change: "No effect"; the published predictive result (Pan & Poteshman 2006, RFS) uses signed, non-public open-buy *volume*, not public OI | `alpha_lab/reports/quick_tests_RESULTS.md` Q4 |
| Max pain | **description** of where writers would pay least. No NSE evidence of a forecast; the US "pinning" evidence (Ni, Pearson & Poteshman 2005, JFE) is a clustering of closes near strikes on expiry day, a few bp, driven by hedging — not a tradable level | no repo study; label stays "context" |
| Participant OI / FII futures flow | **description** — FAIL at 5–20 sessions | `reports/fii_positioning/FINDINGS.md` |
| VIX level / percentile, VIX − realised (variance risk premium) | **description**; Bollerslev–Tauchen–Zhou (2009) found VRP predicts US quarterly returns; on NIFTY alpha_lab Q3 found "No effect" at 20/60 sessions | `quick_tests_RESULTS.md` Q3 |
| Results implied move, priced ÷ usual | **description** of what options charge; selling it is a volatility-risk-premium bet with tail risk | `ResultsImpliedMoves.tsx` footer |
| Excess carry (discount quintile lags 20 d) | the only F&O **lead** with both-period evidence (t −4.2 / −2.9); a candidate for a pre-registered study, never a live rule | alpha_lab Q1 |
| GEX / dealer gamma "signals" | **heuristic** at best in India (no dealer-position data; participant file is a proxy) | — |
| Sizing reality | SEBI: 91 % of individual F&O traders lost money in FY25 | `docs/PRODUCT_STRATEGY.md` line 38 |

Rule check against `reports/gold_program/PLAN.md` §0.1: badges exist only on GOLD; the options pages use footers instead
(acceptable, but a badge per card would make it uniform); two colour violations (OMON PCR, DERV VIX); no composite score
anywhere (good); ATM IV / max pain / PCR appear on OMON, DERV and MKT — once per page holds.

## 8. Ratings

| Area | 0–10 | Evidence |
|---|---|---|
| EOD option chain & pricer (OMON/OVME) | 8 | §3.1–3.2, `shots/options-full.png`, 6 + 18 tests |
| Live chain | 6 | NSE scrape only, 30 s, no bid/ask; Breeze path unused (§4) |
| IV analysis & history | 4 | ATM only, 2 indices, 578 sessions; 1,182 older files unread; no term/skew/per-stock |
| Strategy builder math | 9 | exact breakevens, Greeks foot (critic verified; §3.3) |
| Margin / SPAN | 3 | ₹3.9 L heuristic vs ₹81,497 SPAN for the same condor (§3.3) |
| Position risk book & Greeks aggregation | 1 | no F&O instrument in any book; RSK cash VaR only (§3.6) |
| What-if (time / vol / price grid) | 4 | today + expiry only; IV/days editable in OVME single leg |
| Positioning & event-vol context | 8 | participants with verdict text; implied moves with method and footer (§3.5) |
| Futures analytics (DERV) | 8 | term, basis 2019→, rollover, VIX vs RV (§3.4) |
| Expiry-day tooling | 2 | nothing; data verified available (Breeze) |
| Options alerts | 1 | price-only alerts (§3.6) |
| Data update cadence (EOD) | 7 | 18:30 pipeline, incremental caches, ready 21:49 tonight; no intraday capture |
| Scalability of the options data path | 5 | per-request UDiFF zip loads; no stored per-strike table (§3.6, §5) |
| Honest labelling | 8 | verdict text on panels; two colour slips; "IV rank" mislabel |
| Overall for an options trader's day | 5.5 | strong EOD analyst desk, weak trading-day instrument |

## 9. Open questions for the owner

1. Breeze budget: may the chain poller take ~1,100 of the 5,000 daily calls (2-min cadence, 3 indices, 2 expiries), or
   only the near expiry (≈ 550)? The live-quote provider already hit a `get_quotes` cap once (28 Sep).
2. Paper F&O book: should OSTR books be saveable as paper positions under the same PAPER ONLY enforcement, marked from
   Breeze quotes, before any Decision-Desk-style promotion gate exists for options?
3. Which event list should the vol tools treat as "events" for NIFTY (RBI, Budget, US CPI/NFP/FOMC, elections)? ECO has
   RBI/Fed; the gold program's `gold_events` US calendar is not read by EVTS yet.
4. Backfill window for the 1,182 old-format files and the Breeze 1-min expiry-day replays (≈ 2 h and ≈ 400 calls per
   index-year): a weekend, outside the 02:15 backup?
5. Rename OMON "IV rank" to "IV percentile" and add IV rank, or show both with definitions?
6. VOL screener across all 224 underlyings as its own page (GO `VOL`) or a view inside OMON?
