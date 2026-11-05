# R-IV — Implied-volatility history and daily IV analysis for SuryaDhana AI

Author: R-IV (terminal v2 research round) · Date: 4 Nov 2026 (22:10–22:40 IST, market closed) · Posture: read-only on the
repository, GET-only on the live stack, 3 read-only Breeze calls, 6 paced NSE GETs · Prototype and raw evidence:
`/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-IV/`
(copies of `iv_proto.py`, `iv_compare_NIFTY.csv`, `nse_probes.json`, `breeze_probe_fields.json` sit next to this report).

## Executive summary (10 lines)

1. **Nobody sells us IV history; we must compute it, and we already can.** ICICI Breeze's option chain has **no IV field** (26 fields, verified live tonight); NSE's option-chain-v3 carries IV but only *now*; India VIX is the only published IV history (NSE `vixhistory` API, OHLC, verified).
2. **The raw material is on disk:** 1,760 cached NSE F&O bhavcopies (UDiFF 2024-07-08→2026-11-04, 578 files, 655 MB; legacy `foDDMONYYYYbhav` 2019-10-01→2024-07-05, 1,182 files, 712 MB). Every strike's close, settle, OI and volume per expiry — the same inputs Bloomberg's OVDV/HIVG use at end of day. The legacy format lacks the underlying price; the put-call-parity forward removes the need for it (verified on the 1 Apr 2022 file).
3. **The product's current IV is correct but thin:** OMON computes per-strike Black-Scholes IV from the latest bhavcopy, ATM IV, a smile, an expected range and a 1-year near-expiry ATM-IV line for NIFTY/BANKNIFTY only (`option_history.json`, 578 sessions). There is no stored surface, no constant-maturity IV, no skew or term history, no per-stock IV history, no Parkinson/Yang-Zhang realised vol (NIFTY OHLC is not stored), no event IV-crush measurement, and the "IV rank" label on OMON is a **percentile** (73) — the true 252-day IV rank tonight is **21–23**.
4. **The prototype (`iv_proto.py`) rebuilds NIFTY IV from the cached files in 105 s for 578 sessions:** Black-76 on the PCP forward per expiry, ATM IV interpolated at the forward, 25-delta skew, a VIX-style 30-day constant-maturity ATM IV (`iv30_cm`), term ratio, IV rank/percentile.
5. **Agreement:** ours vs the product's `option_history.json` ATM IV: corr **0.998** (Jul-2024→Nov-2026, n=578), mean +0.47 vol-pt (a known convention difference: the product adds half a day to T and uses the nearest strike); Oct-2026 month alone: corr 0.990, +0.57. Monthly-expiry ATM IV vs India VIX: corr **0.983** in level, **0.944** in daily changes; VIX sits **+1.08 pt** above ATM IV on average (VIX is a variance strip, it carries the skew) — the gap itself is a useful descriptive series.
6. **The near-expiry series the product charts is a saw-tooth, not a history:** mean near-expiry ATM IV by days-to-expiry is 15.0 (3 d), 11.1 (4 d), 12.2, 12.9, 12.7, 13.2, 13.5 (9 d). Day-to-day IV analysis needs the constant-maturity series (`iv30_cm`) and the monthly-expiry series, both prototyped.
7. **Breeze adds what the bhavcopy cannot:** 1-second/1-minute/1-day OHLC+OI for any option, **live and expired** (2020, 2022, 2023, 2025 contracts verified) → intraday IV paths and expiry-day studies. Trap: Breeze's daily "close" is the **last trade** (198.00 on 3 Nov for NIFTY 24000 CE) not NSE's official close (193.20, the last-30-minute average); volume is in units (contracts × 65); OI is a different snapshot. Budget 100 calls/min, 5,000/day (`get_quotes` already hits a lower cap).
8. **Proposed build:** 5 point-in-time DuckDB tables (`iv_surface_daily`, `iv_expiry_daily`, `iv_summary_daily`, `vix_daily`, `iv_event_log`) + NIFTY OHLC from NSE's `ind_close_all` file; an EOD step in the existing 19:xx pipeline (≈3 s per bhavcopy for all 224 underlyings), a 15-minute intraday snapshot for NIFTY/BANKNIFTY/watchlist; backfill ≈ 30 min (UDiFF) + 1 h (legacy, cached) + an optional 2.5 h paced download for 2001→2019 (~3.6 GB) if the owner wants a 25-year cone.
9. **Panels (DERV gains a VOL sub-view; OMON gains history):** IV history with VIX overlay and event markers, IV rank *and* percentile (both labelled), 25-delta skew history, term structure (30/60/90 and the live expiries), IV vs realised (close-to-close, Parkinson, Yang-Zhang), IV cone, expected move, results IV-crush ledger per stock. Every one is `context`/`arithmetic`; **none is a signal**; each panel ends "describes, does not predict".
10. **Rating of today's IV capability: 4/10** (correct math, honest labels, but no history, no stock coverage, no surface, mislabelled rank). With the plan above and no paid data it reaches the Sensibull/Opstra/ORATS level (8/10); Bloomberg's intraday surface and 20-year cones stay out of reach only because of the pre-2019 download and the intraday storage budget, both decided by the owner.

---

## 1. What exists today (evidence)

| Area | Where | What it does | Verified by |
|---|---|---|---|
| EOD chain + IV | `services/data-service/option_chain.py` (`chain()`, `implied_vol()`) | Black-Scholes bisection on S_eff = F·e^{−rT}, F from put-call parity at the ATM strike (else near future, else spot); r = 6.5 % constant; T = calendar days/365 + 0.5/365; IV only for OTM strikes within 3 % ITM; ATM IV = mean(CE, PE) at the nearest strike; max pain, PCR, OI walls | code read; GET `/api/market/option-chain/NIFTY` → 57 strikes, CE IV on 43, PE IV on 42, forward "put-call parity" |
| IV history | `option_chain.update_history()` → `data/nse_archive/derived/option_history.json` | near-expiry (>2 d) ATM IV, PCR, max pain per session, NIFTY + BANKNIFTY only, UDiFF era only (2024-07-08→) | GET `/api/derivatives/option-history/NIFTY?days=2000` → 578 rows |
| OMON page | `ui/components/OptionChain.tsx` | ATM IV, expected range (±1σ), smile, OI by strike, 1-year IV+PCR chart, "IV rank N (share of the past year below today)" | screenshot `ui_audit/options.png` (audit PASS, 0 console errors) |
| DERV page | `routers/derivatives.py` → `fo_analytics.py` | term structure (futures), basis history 2019-10→, rollover, PCR history, **India VIX panel** (level, 1y/5y percentile, VIX − 20-day close-to-close RV) | screenshot `ui_audit/derivatives.png`; GET `/api/derivatives/vix?days=3000` → 3,000 rows, 2014-08-05→2026-11-04 |
| OSTR page | `routers/options_strategy.py` + `options_math.py` | Black-76 greeks, breakevens, margin/cost ESTIMATE; seeded with the chain's ATM IV | screenshot `ui_audit/ostrategy.png` |
| Results implied move | `/api/market/results-implied-moves` (term-structure split of event variance), `nse_results` release times, `typical_moves` | 53 stocks with results in 10 days; e.g. BSE: ATM IV 36.4, expected move 8.41 %, event σ 4.82 %, typical 3.8 % over 8 quarters | GET tonight |
| VIX storage | `market_index_daily` (symbol, date, **close only**), Yahoo `^INDIAVIX` with NSE `allIndices` overriding the session close | no VIX open/high/low, no NIFTY OHLC anywhere in DuckDB (needed for Parkinson/Yang-Zhang) | `duckdb_store.py` L310, `main.py` L501, `ingest.py` L264 |
| F&O daily summary | `nse_fo_daily` 2019-10-01→ (near future, total call/put OI per underlying) | no per-strike data; good for PCR history only | GET basis-history → 1,752 rows from 2019-10-01 |
| Risk-free | `RISK_FREE = 0.065` in `option_chain.py`, `R_DEFAULT = 0.065` in `options_math.py`, `r = 0.065` in `ui/lib/black76.ts` | one undated constant in three places | grep |

Reading of the code: the math is right (forward from parity, Black-76 in OSTR, OTM-only IVs). The gaps are *history*, *coverage* and *labels*, not correctness.

## 2. Sources, verified tonight

| # | Source | Exact access | Fields | Cadence / publication (IST) | Licence / terms | Verdict |
|---|---|---|---|---|---|---|
| 1 | **ICICI Breeze `get_option_chain_quotes`** | SDK 1.0.69, `stock_code="NIFTY", exchange_code="NFO", product_type="options", expiry_date="2026-11-23T06:00:00.000Z", right="call"` → 60 rows in 438 ms | exchange_code, product_type, stock_code, expiry_date, right, strike_price, ltp, ltt, best_bid/offer price+qty, open, high, low, previous_close, ltp_percent_change, upper/lower_circuit, total_quantity_traded, spot_price, ltq, open_interest, chnge_oi, total_buy_qty, total_sell_qty — **no IV, no greeks** | live, market hours (quotes carried `ltt` 15:39 after close); 100 calls/min, 5,000/day | account licence; personal use | PUBLISH as *our* IV from bid/ask mid intraday; store the snapshot |
| 2 | **Breeze `get_historical_data_v2` options, 1day** | same SDK; NIFTY 24000 CE 23-Nov-2026, 2026-09-01→11-04 → 42 rows; NIFTY 17500 CE 28-Apr-2022 (expired) → 39 rows, 254 ms | close, datetime, exchange_code, expiry_date, high, low, open, open_interest, product_type, right, stock_code, strike_price, volume | history to at least 2020 (catalog: Sep-2020 expired option at 1-min); ≤1,000 bars/call, latest-first | same | PUBLISH-CONTEXT for intraday IV paths; **not** the EOD source (close = last trade, see §5) |
| 3 | **Breeze `get_historical_data_v2` options, 1minute / 1second** | catalog 2026-09-28: 376 one-minute bars/day, 1,000 one-second bars/call, expired contracts OK | as above | same | same | PUBLISH-CONTEXT (expiry-day studies, event-day IV crush at minute resolution) |
| 4 | **NSE UDiFF F&O bhavcopy** | `nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip`; cached 2024-07-08→2026-11-04 | 34 cols: TradDt, FinInstrmTp (IDO/STO/IDF/STF), TckrSymb, XpryDt, StrkPric, OptnTp, OpnPric/HghPric/LwPric/ClsPric/LastPric/PrvsClsgPric, **UndrlygPric**, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTradgVol, TtlTrfVal, TtlNbOfTxsExctd, NewBrdLotQty | daily, evening (EOD pipeline already ingests it) | NSE archives: free, personal/non-commercial, no redistribution | PUBLISH-CORE — the EOD IV source |
| 5 | **NSE legacy F&O bhavcopy** | `nsearchives.nseindia.com/content/historical/DERIVATIVES/2022/APR/fo01APR2022bhav.csv.zip` → HTTP 200, 788,691 bytes, `Last-Modified: 01 Apr 2022`; cached locally 2019-10-01→2024-07-05 | 16 cols: INSTRUMENT (FUTIDX/OPTIDX/FUTSTK/OPTSTK), SYMBOL, EXPIRY_DT (DD-Mon-YYYY), STRIKE_PR, OPTION_TYP (CE/PE/XX), OPEN, HIGH, LOW, CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP — **no underlying price, volume in contracts** | historical, static | same | PUBLISH-CORE for the 2001→2024 backfill (parser prototyped) |
| 6 | **India VIX history** | `www.nseindia.com/api/historicalOR/vixhistory?from=01-10-2026&to=04-11-2026` (needs the site cookie first, browser UA) → JSON `data[]` | EOD_TIMESTAMP, EOD_OPEN/HIGH/LOW/CLOSE_INDEX_VAL, EOD_PREV_CLOSE, VIX_PTS_CHG, VIX_PERC_CHG | daily after close; ranges of ≤ 1 year per call (same trap as the 70-row APIs: page it) | NSE site terms (personal use) | PUBLISH-CORE → `vix_daily` with OHLC (today only the close is stored) |
| 7 | **NSE `ind_close_all_DDMMYYYY.csv`** | `nsearchives.nseindia.com/content/indices/ind_close_all_03112026.csv` → 200, 7,394 B, `Last-Modified 17:50 IST` | Index Name, Index Date, Open/High/Low/Closing Index Value, Points Change, Change(%), Volume, Turnover, P/E, P/B, Div Yield — includes Nifty 50 and India VIX rows | daily ≈ 17:50 IST | same | PUBLISH-CORE → NIFTY OHLC for Parkinson / Yang-Zhang realised vol |
| 8 | **NSE Contract_Delta** | `nsearchives.nseindia.com/content/nsccl/Contract_Delta_03112026.csv` → 200, `Last-Modified 12:58 IST` (T+0 noon, for margins) | Date, Symbol, Expiry day, Strike Price, Option Type, Delta Factor | daily | same | PUBLISH-CONTEXT: NSE's own delta per contract = a cross-check of our IV/delta (NCL prices with its own vol) |
| 9 | **NSE FOVOLT** | `nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_03112026.csv` → 200, 14,907 B, 11:28 IST | per underlying: close, prev close, log return, **EWMA daily vol (λ = 0.995)**, annualised ×√365, same for the future | daily | same | PUBLISH-CONTEXT: the exchange's realised-vol estimate per F&O underlying (margin vol), a third RV line |
| 10 | **NSE option-chain-v3** | `www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry=09-Nov-2026` (documented in `docs/NSE_DATA_DICTIONARY.md`; `option_chain.live_frame()` already parses it) | per strike CE/PE: impliedVolatility, lastPrice, bid/ask, OI, ΔOI, volume, underlyingValue | live only; not archived; cookie + UA traps; rate-limit bans | NSE site terms | PUBLISH-CONTEXT for intraday snapshots (NSE's IV alongside ours; they differ by model inputs) |
| 11 | **Risk-free** | in repo: `data/nse_archive/derived/india_10y_fred.csv` (FRED `INDIRLTLT01STM`, monthly 10-y, 2011-12→2026-09); not in repo: RBI 91-day T-bill auction cut-off (weekly Wednesday press release), FBIL MIBOR/T-bill curve (FBIL publishes daily; terms restrict re-use) | — | — | FRED keyless; RBI press releases public; FBIL display-only | see §4.3: for IV the rate barely matters once the forward comes from parity; keep a **dated** constant and record it per row |

Not needed / paid: Bloomberg OVDV surfaces, ORATS/IVolatility/LiveVol histories, Sensibull/Opstra/Quantsapp IV charts (all computed from the same bhavcopy + live chain; none sells raw IV history for NSE at retail terms that allow storage).

## 3. The prototype and what it found

`iv_proto.py SYMBOL START END` (scratchpad): reads the cached UDiFF files, per expiry computes the PCP forward (nearest-to-spot strike where both sides traded; else the matching-month future; else spot·e^{rT}), Black-76 IV per strike (traded strikes only; calls for K ≥ 0.97F, puts for K ≤ 1.03F; mean when both), **ATM IV = IV interpolated at the forward**, 25-delta call/put IV and skew (strike found by inverting each strike's own delta), the near (>2 d) and monthly (20–60 d) expiry series, and `iv30_cm` = variance-interpolated 30-day constant-maturity ATM IV (the CBOE/NSE VIX bracketing rule applied to ATM variance). Outputs: `iv_surface_<SYM>.csv` (one row per expiry per day), `iv_summary_<SYM>.csv`, `iv_compare_<SYM>.csv` (joined to `option_history.json` and the DERV VIX rows).

**One month, NIFTY, 1 Oct → 4 Nov 2026 (23 sessions, 238 expiry rows, 4.4 s):**

| date | spot | near exp (dte) | ours near ATM | product ATM | iv30_cm | monthly ATM | 25Δ skew | India VIX | RV20 |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-01 | 22,421.95 | 10-06 (5) | 12.01 | 11.7 | 13.61 | 13.53 | 2.11 | 14.46 | 10.35 |
| 2026-10-09 | 22,520.45 | 10-13 (4) | 10.80 | 10.4 | 13.58 | 13.21 | 2.18 | 14.38 | 13.74 |
| 2026-10-16 | 23,146.15 | 10-19 (3) | 10.84 | 10.0 | 12.94 | 12.83 | 1.96 | 14.06 | 16.09 |
| 2026-10-23 | 22,600.00 | 10-27 (4) | 14.61 | 13.7 | 15.99 | 15.87 | 2.84 | 16.86 | 16.32 |
| 2026-10-26 | 22,753.20 | 11-03 (8) | 16.84 | 16.6 | 15.91 | 16.21 | 3.08 | 17.16 | 15.62 |
| 2026-10-30 | 23,053.10 | 11-03 (4) | 12.06 | 11.3 | 13.93 | 14.07 | 2.53 | 15.30 | 14.96 |
| 2026-11-04 | 23,960.60 | 11-09 (5) | 14.56 | 13.9 | 12.81 | 13.06 | 2.22 | 15.27 | 16.01 |

(the `iv_compare_NIFTY.csv` next to this report is the whole-era run, 578 sessions from 2024-07-08; filter `date >= 2026-10-01` for this table)

**Agreement (Oct 2026, n = 23):** ours-near vs product ATM IV corr 0.990 (0.987 in changes), mean +0.57 pt, max 0.92; monthly ATM vs VIX corr 0.933 (0.974 in changes), VIX − ATM = +1.14 pt; iv30_cm vs VIX 0.885 / 0.785, +1.24.
**Agreement (whole UDiFF era, 2024-07-08 → 2026-11-04, n = 578, 105 s):** ours-near vs product corr **0.998** (0.988 changes), +0.47 pt, max 1.88; monthly ATM vs VIX **0.983 / 0.944**, +1.08; iv30_cm vs VIX 0.978 / 0.886, +1.09. The +0.47 is the product's extra half-day in T (lower IV) plus nearest-strike vs interpolated ATM; the +1.08 vs VIX is structural (VIX is a model-free variance strip over the OTM wings; ATM IV ignores the skew), and the skew term (2–3 pt at 25Δ here) explains its size. Both series move together day to day: **the stored bhavcopy reproduces India VIX's dynamics without NSE's intraday feed.**

**Findings that change the design**
- Near-expiry ATM IV by days-to-expiry (n=578): 3 d 15.00 · 4 d 11.13 · 5 d 12.21 · 6 d 12.88 · 7 d 12.66 · 8 d 13.22 · 9 d 13.50. With weekly expiries the "near" series is a saw-tooth driven by the calendar, not by volatility; OMON's 1-year chart shows exactly this. History needs **constant-maturity** (30/60/90 d) and **fixed-expiry** series side by side.
- IV rank vs percentile: on `iv30_cm` tonight (12.81; 252-session min 8.50, max 28.87) **rank = 21, percentile = 60**; on the monthly series rank 23 / percentile 62. OMON prints "IV rank 73" and defines it as the share of the past year below today — that is the percentile, on the saw-tooth series. Both numbers are useful; both must be labelled by their definition (Bloomberg prints "IVOL %ile" and "IVOL rank" separately; TradingView/Sensibull call them IVR and IVP).
- Stocks: the 3 Nov 2026 file has 224 option underlyings; only 381 expiry rows had ≥ 4 strikes with a computable IV — far-month stock options barely trade, so a stock's term structure is the near and next month at best. IDEA (4 strikes) and YESBANK (5) are the thin end. RELIANCE Oct-2026: near/next expiries 46 / 38 IV strikes, forward from parity every day; the Dec and Jan expiries fall back to the future on some days (18 and 11 strikes).
- Legacy format works without an underlying price: 1 Apr 2022 NIFTY → 11 expiries, monthly 28-Apr ATM 17.13 %, 25Δ skew 3.83, 96 IV strikes, forward from parity (India VIX closed near 19–20 that week; the gap is again the skew).
- Throughput: one UDiFF file, all 224 underlyings, all expiries: 0.1 s load + 2.9 s compute = **3.0 s/file** single-threaded, so the whole cached archive (1,760 files) is ≈ 1.5 h once, ≈ 3 s per evening afterwards.

## 4. Method decisions (what the best would do, and what we do)

### 4.1 Model and inputs
- **Black-76 on the forward, per expiry** (Bloomberg OVME/OVDV, ORATS, Sensibull all price index options off the forward). Forward from put-call parity at the strike nearest spot where both sides traded (F = K + (C − P)·e^{rT}); fall back to the matching-month future, then spot·e^{rT}; **store `forward_source`**. Dividends: parity and the future already carry them (NIFTY is a price index; stock futures price the dividend), so no dividend input is needed except in the spot fallback, which is flagged.
- **Price used:** `ClsPric` when `TtlTradgVol > 0`, else *no IV* (NSE's `SttlmPric` on an untraded strike is a theoretical value; using it would feed NSE's model back as "market" IV — the product already does this right). Keep `price_source` per row.
- **T:** calendar days from the trade date to the expiry date, at the 15:30 close, / 365 (both sessions end 15:30, so whole days; the product's +0.5 day is a historical choice, keep one convention and record `model_version`). Expiry-day rows: compute (T = 0 → no IV), never chart them in the "near" series.
- **Strike selection:** OTM wings plus 3 % ITM (as today); ATM IV by linear interpolation in strike at the forward; 25Δ/10Δ IVs by inverting each strike's own delta (what Bloomberg's SKEW and ORATS "skew" report); the smile stored as (log-moneyness, IV) so surfaces are comparable across days.
- **Constant maturity:** VIX-style variance interpolation between the two expiries bracketing 30 / 60 / 90 days (the product's `fo_analytics` has the bracketing structure already for futures). Also keep **fixed-expiry** histories (each expiry's ATM IV from listing to expiry — the "IV by contract" view option sellers use).

### 4.2 Realised volatility and IV − RV
Close-to-close (exists: `realized_vol_series`), **Parkinson** (needs high/low) and **Yang-Zhang** (needs open/high/low/close) over 10/20/60 sessions. NIFTY OHLC is not stored: take it from `ind_close_all` (daily, 17:50 IST, verified) for indices and from `nse_bhavcopy` for stocks (already stored, 2010→). Add NSE's FOVOLT EWMA as a third line ("the exchange's margin vol"). Label: *arithmetic*. The spread IV − RV is **context** (volatility risk premium); never colour it bullish/bearish.

### 4.3 Risk-free rate
For IV the rate is nearly irrelevant once the forward comes from parity: a 100 bp change moves a 30-day ATM NIFTY option price by ≈ 0.08 % and its IV by ≈ 0.01 vol-pt; it matters for the *forward* only when we fall back to spot. Decision: keep a **dated constant table** (`rate_curve`: date, tenor, rate, source) seeded with the current 6.5 % and the FRED 10-year already in `data/nse_archive/derived/india_10y_fred.csv`; if the owner wants the 91-day T-bill, the RBI weekly auction press release is public and free (not probed tonight — one paced GET per week), FBIL curves are display-only. Record `r` on every stored row so a later change never silently rewrites history.

### 4.4 Event handling (results)
`nse_results` holds release timestamps (8 quarters for the big names, e.g. INFY typical move 3.22 %, RELIANCE 2.89 %). For each (symbol, release) store: ATM IV of the first expiry after the release on T−5…T−1, the IV on T+1, the realised |move| at the next open/close, the options' implied event σ (the term-structure split already in `results-implied-moves`). That gives a measured **IV-crush ledger** ("over the last 8 quarters INFY's near ATM IV fell 38 % → 24 % on results day; the stock moved 2.9 % vs 4.1 % implied") — the Market Chameleon / ORATS "earnings" page, from free data. Label `context`; the ledger describes past events, it does not forecast the next.

### 4.5 Data-quality traps (each becomes a stored flag)
1. Untraded strikes carry NSE's theoretical settle → no IV (flag `untraded`). 2. Deep ITM prices stale → wings only. 3. Expiry-day and T ≤ 2 d IVs blow up (the 3-day mean of 15.0 above) → excluded from "near", kept in the surface. 4. `ClsPric` is the last-30-minute average, `LastPric` the last trade: use `ClsPric`; Breeze's daily close is the last trade (198.00 vs 193.20 on 3 Nov) — a 2.5 % price gap is ≈ 0.4 vol-pt on that strike. 5. Breeze OI/volume are different snapshots and units (10,408,970 units = 160,138 contracts × 65). 6. Legacy files: dates `DD-Mon-YYYY`, no underlying, `CONTRACTS` not units, expiries weekly only for indices after 2019. 7. Expiry calendar changes (Thursday → Tuesday Sept 2025 → Monday/other in 2026 for NIFTY; `expiries` tonight: 09-Nov, 17-Nov, 23-Nov, 01-Dec …) → never assume a weekday; read expiries from the file. 8. Corporate actions on stock options (strike/lot adjustments) → the symbol's chain shifts; store `NewBrdLotQty` and flag days where the strike grid changes. 9. Holidays and half-days (Muhurat) → T from calendar days still fine; the session count for RV uses trading days. 10. PCP forward with a wide bid-ask on an illiquid ATM pair → fall back to the future when |F_pcp − F_future| > 0.5 %.

## 5. Breeze: what to use it for
- **Not** the EOD source (close convention, OI snapshot, 5,000/day budget, and the bhavcopy is official and free).
- **Intraday IV path:** a 15-minute snapshot job (09:20–15:30, 25 snapshots) for NIFTY + BANKNIFTY (2 expiries × 2 sides) = 200 calls/day, plus the owner's F&O watchlist (≤ 10 names × 1 expiry × 2 sides × 25 = 500) — ≈ 700 of the 5,000/day budget. Compute IV from the bid/ask mid (not `ltp`), store `iv_intraday` (ts, symbol, expiry, strike, mid, iv, oi, source="breeze"); derive intraday ATM IV, skew and the "IV at 09:20 vs 15:25" line. NSE's option-chain-v3 can run alongside at the same cadence to store NSE's IV next to ours (two models, labelled).
- **Expiry-day / event-day replays:** 1-minute option bars for expired contracts (verified back to 2020) → "how did IV collapse through results day" studies, on demand, paced, never bulk.
- Session must be live (it was tonight: data-service reports the Breeze provider connected; no token printed).

## 6. Proposed storage (point-in-time, PLAN §0.1 rules)

```sql
-- per strike, per expiry, per session: the surface (indices + watchlist always; all 224 underlyings if the owner approves ~1 GB)
CREATE TABLE iv_surface_daily (
  date DATE, symbol VARCHAR, expiry DATE, strike DOUBLE, opt_type VARCHAR,        -- CE | PE
  price DOUBLE, price_source VARCHAR,        -- close | none (untraded)
  forward DOUBLE, forward_source VARCHAR,    -- pcp | future | spot
  t_years DOUBLE, r DOUBLE, iv DOUBLE, delta DOUBLE, vega DOUBLE,
  oi DOUBLE, oi_chg DOUBLE, volume DOUBLE, lot INTEGER, log_moneyness DOUBLE,
  model_version VARCHAR, source_file VARCHAR, first_seen_at TIMESTAMP,
  PRIMARY KEY (date, symbol, expiry, strike, opt_type));
-- per expiry per session: ATM, skew, counts (small: ~400 rows/day)
CREATE TABLE iv_expiry_daily (
  date DATE, symbol VARCHAR, expiry DATE, dte INTEGER, forward DOUBLE, forward_source VARCHAR,
  atm_iv DOUBLE, iv_25d_put DOUBLE, iv_25d_call DOUBLE, skew_25d DOUBLE, iv_10d_put DOUBLE, iv_10d_call DOUBLE,
  n_iv_strikes INTEGER, call_oi DOUBLE, put_oi DOUBLE, pcr DOUBLE, expected_move_pct DOUBLE,
  quality_flags VARCHAR, model_version VARCHAR, first_seen_at TIMESTAMP, PRIMARY KEY (date, symbol, expiry));
-- per underlying per session: the series the pages chart (~224 rows/day)
CREATE TABLE iv_summary_daily (
  date DATE, symbol VARCHAR, spot DOUBLE,
  iv30_cm DOUBLE, iv60_cm DOUBLE, iv90_cm DOUBLE, near_atm_iv DOUBLE, near_expiry DATE, near_dte INTEGER,
  monthly_atm_iv DOUBLE, monthly_expiry DATE, skew_25d_30 DOUBLE, term_slope_30_90 DOUBLE,
  iv_rank_252 DOUBLE, iv_pctile_252 DOUBLE, rv20_cc DOUBLE, rv20_parkinson DOUBLE, rv20_yz DOUBLE, fovolt_ann DOUBLE,
  iv_minus_rv20 DOUBLE, expected_move_1d_pct DOUBLE, quality_flags VARCHAR, model_version VARCHAR, first_seen_at TIMESTAMP,
  PRIMARY KEY (date, symbol));
CREATE TABLE vix_daily (date DATE PRIMARY KEY, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, prev_close DOUBLE,
  source VARCHAR, first_seen_at TIMESTAMP);                                   -- NSE vixhistory; today only the close exists
CREATE TABLE index_ohlc_daily (symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  source VARCHAR, first_seen_at TIMESTAMP, PRIMARY KEY (symbol, date));        -- ind_close_all; for Parkinson / Yang-Zhang
CREATE TABLE iv_event_log (symbol VARCHAR, released_at TIMESTAMP, expiry DATE, iv_pre_5d DOUBLE, iv_pre_1d DOUBLE,
  iv_post_1d DOUBLE, crush_pct DOUBLE, implied_move_pct DOUBLE, realised_move_pct DOUBLE, first_seen_at TIMESTAMP,
  PRIMARY KEY (symbol, released_at));
CREATE TABLE iv_intraday (ts TIMESTAMP, symbol VARCHAR, expiry DATE, strike DOUBLE, opt_type VARCHAR, mid DOUBLE,
  iv DOUBLE, nse_iv DOUBLE, oi DOUBLE, source VARCHAR, PRIMARY KEY (ts, symbol, expiry, strike, opt_type, source));
CREATE TABLE rate_curve (date DATE, tenor VARCHAR, rate DOUBLE, source VARCHAR, PRIMARY KEY (date, tenor, source));
```
Size: NIFTY ≈ 1,000 surface rows/day; all underlyings ≈ 25–30 k/day → 1,760 days ≈ 50 M rows ≈ 2–3 GB; restricting the surface to indices + watchlist and keeping `iv_expiry_daily`/`iv_summary_daily` for everyone is ≈ 0.3 GB and loses nothing the pages show (the per-strike surface for any stock/day is recomputable from the cached file in 3 s). A `model_version` bump re-derives, never overwrites.

## 7. Jobs (IST) and backfill
- **EOD (existing pipeline, after the F&O bhavcopy ingest, ≈ 19:35):** `iv_eod` — parse the day's file, write the three daily tables, VIX OHLC (`vixhistory`, one call), `ind_close_all` (one GET), FOVOLT (one GET), Contract_Delta cross-check (one GET, differences > 0.05 delta logged), the results ledger for releases since yesterday. ≈ 5 s + 4 fetches. Fetch-only, like the gold jobs; it never restarts anything.
- **Intraday (trading days, 09:20–15:30 every 15 min):** `iv_intraday` — Breeze chain for NIFTY/BANKNIFTY (near + next expiry) and the watchlist; optional NSE v3 in the same tick. Skipped when the Breeze session is not live; budget-guarded (≤ 800 calls/day, ≤ 30/min).
- **Weekly (Sat 03:00):** recompute `iv_rank_252`/`iv_pctile_252` windows after any late bhavcopy corrections; re-run `--check` on the catalogue of IV series (same gating idea as `gold_series_catalog`: no verdict row, no panel).
- **Backfill, one-off, owner-approved:** (a) UDiFF cached 2024-07→: ≈ 578 × 3 s ≈ 30 min; (b) legacy cached 2019-10→2024-07: ≈ 1,182 × 3 s ≈ 1 h; (c) optional 2001→2019-09 from `nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip`: ≈ 4,500 files, ~0.8 MB each ≈ 3.6 GB, one file every 2 s with the browser UA ≈ 2.5 h download then ≈ 3.5 h compute; run outside 07:45–09:20 and 18:30–21:15, never beside the 02:15 backup, resumable by date. NSE terms: personal use, no redistribution (same posture as the equity bhavcopy archive).

## 8. Panels — DERV › VOL sub-view and OMON history (each with its label)

| Panel | Content | Source tables | Label | Named precedent |
|---|---|---|---|---|
| IV history | `iv30_cm` (and 60/90 as toggles) with **India VIX overlay**, results/budget/expiry markers, fixed-expiry lines on hover | iv_summary_daily, vix_daily, nse_results | `context` — "describes, does not predict" | Bloomberg HIVG / GV, TradingView IV chart, Sensibull IV chart, IBKR Volatility Lab |
| IV rank and percentile | both numbers, each with its definition and window (252 sessions), on `iv30_cm` **and** on the monthly expiry; the OMON subtitle fixed to say "percentile" | iv_summary_daily | `arithmetic` | Bloomberg "IVOL %ile / rank", thinkorswim IV percentile, tastytrade IVR |
| Skew history | 25Δ put − call IV, 10Δ, with the current smile in log-moneyness; "today vs 1 month ago" overlay | iv_expiry_daily, iv_surface_daily | `context` | Bloomberg SKEW, Cboe SKEW, ORATS skew |
| Term structure | live expiries' ATM IV by dte + constant-maturity 30/60/90; slope history | iv_expiry_daily, iv_summary_daily | `context` | Bloomberg OVDV term tab, Opstra term structure, IBKR term structure |
| IV vs realised | `iv30_cm` vs RV20 close-to-close / Parkinson / Yang-Zhang / FOVOLT; spread history; "IV paid vs vol delivered" over the last 12 expiries (what a seller of the monthly straddle collected vs what moved — a **measured ledger**, no forecast) | iv_summary_daily, index_ohlc_daily, nse_bhavcopy | `arithmetic` for the vols; `context` for the spread | Bloomberg VCA / HVG, Market Chameleon IV30 vs HV, IBKR IV vs HV |
| IV cone | min/25/50/75/max of constant-maturity IV by tenor over 1/3/5 years with today's term structure on it | iv_summary_daily (history), iv_expiry_daily (today) | `context` | Opstra IV cone, Bloomberg GV cone |
| Expected move | ±1σ to each expiry from its ATM IV; 1-day move; realised-to-implied hit rate over the last 60 sessions (measured) | iv_expiry_daily | `arithmetic`; the hit-rate `context` | OMON already; Bloomberg OSA "expected move", thinkorswim MMM |
| Results IV-crush ledger | per stock: last 8 releases — IV before/after, crush %, implied vs realised move; terminal-wide table sortable by next results date | iv_event_log, nse_results | `context` | ORATS earnings, Market Chameleon earnings, Unusual Whales earnings |
| Per-stock IV strip (EQS / Profile) | each F&O stock's `iv30_cm`, rank, percentile, skew, IV − RV, next results | iv_summary_daily | `context` | Bloomberg DES "Implied vol" strip, Sensibull stock IV |
| Intraday IV | today's ATM IV and skew path every 15 min for NIFTY/BANKNIFTY/watchlist; NSE's IV as a second line | iv_intraday | `context`; source chip LIVE Breeze / NSE | Bloomberg OMON intraday IV, Quantsapp IV live |

Rules carried over from the gold program: one number appears once per page; the VIX stays on DERV's header strip and the IV-history overlay (same figure, one source: `vix_daily`); nothing from these tables feeds the Decision Desk, the S1 shadow, directional alerts or the paper ticket's price — the OSTR ticket may read `iv_summary_daily` for its default IV (what it does today from the chain). No composite "vol score".

## 9. Ratings (0–10, evidence in §1 and §3)

| Area | Score | Why |
|---|---|---|
| IV correctness today | 7 | forward from parity, OTM-only, Black-76 in OSTR; one undated r; +0.5 d convention; cross-checked by the prototype (corr 0.998) |
| IV history and coverage | 2 | JSON cache of one saw-tooth series for 2 indices since Jul-2024; no stocks, no surface, no skew/term, no pre-2024 |
| Realised vol | 3 | close-to-close 20-d on NIFTY only; no OHLC estimators; no FOVOLT; VIX close only |
| Labels and honesty | 6 | OMON/DERV describe, never forecast; but "IV rank" is a percentile on the saw-tooth series |
| Event IV | 5 | results implied move (term split) + typical move exist; no measured crush ledger |
| Intraday IV | 1 | none stored; Breeze chain available (no IV field) with 5,000/day budget |
| Data-update design | 6 | bhavcopy cached daily by the EOD pipeline; VIX via Yahoo + NSE override (no OHLC); no vixhistory, ind_close_all, FOVOLT, Contract_Delta |
| Overall IV capability | **4** | correct but thin; the plan above is ≈ 2 weeks of work on free data |

## 10. Top recommendations

1. **`iv_eod` + the five tables, UDiFF era first** (M): everything in §6–7 for indices + watchlist; 30-min backfill; OMON history chart switches to `iv30_cm` with the monthly line; rank and percentile both shown. Value: the owner's day-to-day IV view with a true history.
2. **Legacy parser → 2019-10 backfill** (S after 1): one mapping (prototyped), 1 h run; 7-year IV cone and rank windows that cover 2020 and 2022.
3. **VIX OHLC + NIFTY OHLC + FOVOLT ingest** (S): three paced daily GETs; Parkinson/Yang-Zhang and the exchange's own vol; the VIX − ATM gap as a stored series.
4. **Results IV-crush ledger** (M): from `nse_results` + `iv_expiry_daily`; the single most used page by an options trader around earnings season.
5. **Intraday snapshots via Breeze (and NSE v3 alongside)** (M): 15-min cadence, budget-guarded, IV from mid; the "IV at open vs close" line and expiry-day behaviour.
6. **Fix the label** (XS): OMON subtitle "IV rank" → "IV percentile" now; add rank when 1 ships.
7. **Dated rate table + `model_version` on every row** (S): stop the 6.5 % constant from living in three files; record it per row.
8. **2001→2019 archive download** (L, owner decision): 3.6 GB, 2.5 h paced; only if a 25-year cone is wanted; same NSE terms posture as the equity archive.

## 11. Open questions for the owner
1. Scope of `iv_surface_daily`: indices + watchlist (≈ 0.3 GB) or all 224 underlyings (≈ 2–3 GB)?
2. Approve the one-off backfills (30 min UDiFF, 1 h legacy) and, separately, the 2001→2019 download under NSE's personal-use terms?
3. Intraday source: Breeze only (our IV, 700 calls/day) or Breeze + NSE option-chain-v3 (NSE's IV beside ours; NSE's site terms and ban risk)?
4. Risk-free policy: keep a dated 6.5 % constant with the FRED 10-year as context, or add the weekly RBI 91-day T-bill cut-off (one paced GET/week)?
5. Should OMON's "IV rank" be relabelled "IV percentile" in the next UI release before the history tables exist (a one-line change in `OptionChain.tsx`)?
6. Which results releases define the crush ledger: `nse_results` timestamps only (8 quarters stored) or the corporate-announcements feed for a longer window?

## 12. Scope and limits of this review
GET-only on :8010/:8001, three read-only Breeze calls (chain + two daily histories), six paced NSE GETs with a browser UA, no Yahoo, no writes outside `reports/terminal_v2/R-IV/` and the scratchpad; the prototype reads the cached files only. The one-month comparison uses the DERV VIX endpoint's rows (NSE/Yahoo closes already stored), not a new VIX download. Not done: a Yang-Zhang number (no NIFTY OHLC stored yet), a stock-level crush ledger (needs the tables), any intraday storage.
