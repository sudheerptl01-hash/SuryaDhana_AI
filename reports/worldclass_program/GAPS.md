# GAPS — what an Indian-market + MCX-gold trader needs vs what the terminal has (15 Oct 2026, 03:00)

Grades: **HAVE** (verified working) · **PARTIAL** · **MISS-B** (missing, buildable tonight) ·
**MISS-EXT** (missing, needs paid data / eligibility / exchange agreements — honesty section).
Build IDs reference PLAN.md Team 1.

## 1. NSE cash equities
| Need | Status | Evidence / gap | Build |
|---|---|---|---|
| Universe + screeners (technical, fundamental) | HAVE | EQS T1–T8, FUND (XBRL), LW scanner | — |
| Live quotes | HAVE | tick engine (LIVE_TICKS, verified) + Yahoo 60 s fallback, source-labeled | — |
| Pre-open auction (09:00–09:08 IEP, imbalance) | HAVE | PRE page | — |
| Movers / 52w / volume surges | HAVE | MOV | — |
| **Interactive charting** (candles, indicators, multi-TF, intraday) | **MISS-B** | only sparklines + static charts today; a Bloomberg GP-equivalent is the single biggest UI gap | **W1** |
| **VWAP / session volume profile** | **MISS-B** | no intraday persistence → no VWAP | **W6→W1** |
| Market depth (best-5 bid/ask) | PARTIAL | Breeze WS carries depth fields; not stored/shown | W6 stores L1+best bid/ask; full depth panel = later |
| Order ticket (paper) | HAVE | stock Profile trade ticket + costs | — |
| Order blotter / paper fills | PARTIAL | PORT + paper ledger; no modify/cancel workflow (paper) | later (small) |
| Corporate filings, results, events, dividends | HAVE | CF, EVTS, results pages, release-time history | — |
| Deals (bulk/block), insiders, holders, MTF | HAVE | DEAL, INSD, HDS, MRGN | — |
| Surveillance flags (ASM/GSM) on holdings | HAVE | per 11–14 Oct sprint | — |
| News + per-stock news | HAVE | news scanner + Profile | — |
| Alerts (price, filing, results) | HAVE | ALRT + Telegram | — |
| Index members / weights / seasonality / world | HAVE | MEMB, SEAG, WEI, ECO | — |

## 2. NSE F&O
| Need | Status | Evidence / gap | Build |
|---|---|---|---|
| Option chain live (OI walls, IV, PCR, max pain) | HAVE | OMON (market hours) | — |
| **Futures term structure, basis, rollover history** | **MISS-B** | nse_fo_daily (2019→) has it all; no page computes it | **W2** |
| **PCR / max-pain history, expiry analytics** | **MISS-B** | daily chain snapshots exist; no time series view | **W2** |
| **Options strategy builder (payoff, Greeks, BE, margin est.)** | **MISS-B** | nothing | **W3** |
| Position Greeks aggregation | PARTIAL | W3 ships the math; wiring to paper book after | W3 (lib) |
| Participant OI (FII/DII/pro/client) | HAVE | panels + study verdict (context only) | — |
| Intraday OI change | MISS-EXT/PARTIAL | exchange snapshots ~3 min; Breeze quote OI could be sampled — not tonight | later |
| IV surface / smile history | MISS-B(later) | needs chain archive discipline first | later |

## 3. MCX gold (the owner trades gold)
| Need | Status | Evidence / gap | Build |
|---|---|---|---|
| Pre-open fair value (COMEX × USDINR), ₹300 verdict | HAVE | Gold desk + 08:55 job | — |
| **MCX session awareness (09:00–23:30, MCX holiday calendar ≠ NSE)** | **MISS-B** | terminal is NSE-clocked everywhere | **W4** |
| **Live MCX gold quotes through the evening session** | **MISS-B** | Breeze commodity quotes if the account is entitled — detect and degrade honestly; ICICI price band already flows today | **W4** |
| **Contract specs: GOLD 1 kg / GOLDM 100 g / GOLDPETAL 1 g, tick value, margins, expiries** | **MISS-B** | static + computable; nothing shown | **W4** |
| COMEX session + USDINR + DXY live overlay | PARTIAL | FRED/Yahoo daily exists; live overlay in session | **W4** |
| Paper gold ticket (lot-aware, margin-aware) | MISS-B | — | **W4** |
| MCX tick history / depth | MISS-EXT | paid; bhavcopy is free (later ingest) | honesty list |
| Gold options (MCX) | MISS-B(later) | after W4 quotes land | later |

## 4. Portfolio & risk
| Need | Status | Evidence / gap | Build |
|---|---|---|---|
| Paper book, P&L, sector exposure | HAVE | PORT, positions router | — |
| **VaR (hist-sim), beta decomposition, stress replays (COVID-20, elections-24), drawdown ladder vs the −20 % HARD stop** | **MISS-B** | panel has 16 yrs of survivorship-free data; no risk page | **W5** |
| Kelly/costs on ticket | HAVE | costs/ticket | — |
| Monte-Carlo drawdown lens on S1/S1H (QuantLab A1) | MISS-B | spec in quantlab_gap_analysis.md | **W8** |
| Weekly decision journal (A2) | MISS-B | spec ibid. | **W8** |

## 5. Platform flaws being fixed tonight (from the Bloomberg critique)
| Flaw | Build |
|---|---|
| 69.5 MB bulk-per-call: alpha/universe 1.4 s, lw/screener 2.9 s → 60 s TTL cache | **W7** |
| 4 payloads > 150 KB (fundamentals-screen 516 KB, mtf 369 KB, events 240 KB, announcements 218 KB) | **W7** |
| LOW: two 422 envelope conventions, upstream error leaks internal URL, lw `days<=0` false message | **W7** |
| Tick data vanishes on restart (memory only) | **W6** |

## 6. Honesty list — MISS-EXT (cannot be built from free/entitled sources; would need money or agreements)
- **True L2/L3 depth (20-deep) & tick-by-tick**: NSE TBT feed is paid/colo-grade. Best-5 via broker WS is the ceiling here.
- **Professional news wire** (Reuters/Bloomberg News, embargoed releases): paid. Free proxy = NSE filings + the news scanner (whose 199-pick track record matched random — context only).
- **Consensus estimates / sell-side models**: paid (Refinitiv/Visible Alpha class). XBRL actuals only.
- **Real-time F&O OI**: exchange disseminates snapshots; true real-time is member-data territory.
- **Earnings-call audio/transcripts beyond NSE submissions**: mostly paid aggregators.
- **Global futures live** (CME GC for gold): 10-min delayed free at best; live = paid data agreement.
- **MCX tick history**: paid; daily bhavcopy is the free grain.
- **Live order routing compliance**: SEBI retail algo rules (Apr 2026) — broker approval + static IP + audit; owner process, not code. Paper mode sidesteps it deliberately.
- **Bloomberg IB/chat, multi-user entitlements**: single-user terminal by design.

Everything in MISS-B is in tonight's build. Everything in MISS-EXT goes in the final report as the honest
"what would make it fully Bloomberg" list with price/effort notes.
