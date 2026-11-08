# Gold free-data dictionary (SuryaDhana GOLD program)

Every free source for trading gold on MCX, verified live on **Monday 26 Oct 2026, 03:30–09:40 IST** by ten research agents
(G-COT, G-CME, G-PHYSICAL, G-MACRO, G-INDIA, G-KITCO, G-EDU, G-APP, G-LOGIN, G-STUDY), synthesised here with every
disagreement resolved explicitly. Style follows `docs/NSE_DATA_DICTIONARY.md`. Companion: `PLAN.md` (the phase-2 build).

Evidence on disk (nothing in this file rests on memory alone):
`reports/gold_program/G-COT/` (REPORT.md, `data/` full COT history, 2 PNGs, `scratch/`) · `G-CME/` (REPORT.md, `probe_log.jsonl`,
`samples/`) · `G-PHYSICAL/` (**no REPORT.md was written — the harness refused it; the long-form report is the agent's
structured summary held by the orchestrator**; `verify_log.jsonl` 154 requests, `samples/` 134 payloads, `verify.py`, `batch_*.py`)
· `G-MACRO/` (**same: no REPORT.md**; `sources_verified.md` 149 rows, `verification*.json`, `g_study.py`, `study.json`, `data/`,
`tables/`) · `G-INDIA/` (REPORT.md, `scratch/` incl. 81 AMFI files, AMFI study) · `G-KITCO/` (REPORT.md, `scratch/bodies/`)
· `G-EDU/` (REPORT.md, CURRICULUM.md, glossary.json, tooltips.json, verify_*.json) · `G-APP/` (REPORT.md) · `G-LOGIN/` (REPORT.md)
· `G-STUDY/` (REPORT.md, FINDINGS.md, RESULTS_TABLES.md, DATA_SOURCES.md, `g_study.py`, `data/`, `results/`, `figures/`).

Rules kept by every agent: public free sources only, polite rate, identified User-Agent, no credential use, no live-service
writes, no `.env` values printed. Nothing below is fabricated: every URL and field was seen in a live response or is marked
UNVERIFIED / BLOCKED with the exact failure.

---

## 0. Your questions, answered by dataset

| Owner's question | Dataset (entry) | Measure | Cadence · lag | Verdict |
|---|---|---|---|---|
| Who is long, who is short COMEX gold; what got closed this week? | CFTC COT disaggregated (B1) | long/short/spread per trader group, Δ week, OI | weekly · Tue positions, Fri 15:30 ET (Sat 01:00/02:00 IST) | PUBLISH-CORE (descriptive) |
| …and daily? | CME FTP daily volume & OI by product (C1); MCX OI per expiry via ICICI master (F1) | ΔOI × Δprice (long build-up / short covering / short build-up / long unwinding) | daily · T+1 ≈14:00–15:30 IST (COMEX); ~07:30 IST (MCX) | PUBLISH-CORE (labels are context) |
| CFTC "Futures/Options"? | COT combined report (B2) minus futures-only | options-only net per group, combined OI | weekly | PUBLISH-CONTEXT (drawer) |
| Over-the-counter deals? | LBMA Trade Data headline (E15); CME EFRP prints (C2); London vault holdings (E16) | weekly gross OTC turnover ($ bn, 12-wk MA); daily EFP/EFR lots; monthly vault tonnes | weekly / daily / monthly | PUBLISH-CONTEXT |
| Supply and demand? | WGC quarterly balance sheet (E7); IMF official gold (E12); WGC ETF flows (E5); GLD daily (E1); SGE withdrawals (D5); India imports (F14, E20) | tonnes by category; central-bank buying by country; ETF flows by region; Shanghai withdrawals; imports | quarterly / monthly / weekly / daily | CORE (ETF, IMF) · CONTEXT (rest) |
| Is gold "healthy"? | real yield (G1/G3), dollar (A5), COT (B1), ETF (E1/E5), premiums (F10, D3), curve (A2/C3), GVZ (A6) | the five-number strip + eight gauges + a descriptive verdict | mixed | CONTEXT (no driver passed as a forecast) |
| The Kitco chart? | Yahoo `GC=F` 1-min bars (A1) | 24-h IST chart with previous-day overlay, settle line, session bands (incl. MCX) | ≈1 min delayed | PUBLISH-CORE (Kitco itself LINK-ONLY) |
| Days, weeks, months? | DuckDB tables filled by the jobs in PLAN §c | D/W/M resampling of every stored series | from the day ingestion starts | PUBLISH-CORE (plumbing) |
| Choose the contract? | ICICI master (F1) + Zerodha margin mirror (F8) + CME product reference & calendar (C3, C4) + Yahoo months (A2) | per-contract economics, OI ladder, roll dates, matched COMEX month, carry | daily | PUBLISH-CORE |
| What is the rupee price made of? | duty notification (F9), IBJA (F10), FBIL/RBI rate (F13), Yahoo INR=X (A5) | COMEX → ×INR → landed → +15 % duty → duty-paid → IBJA premium → MCX basis/carry | daily, timestamp-synchronised | PUBLISH-CORE (ladder) · CONTEXT (premium as a signal) |
| Auto-login ICICI? | ICICI TOTP (I-section) | zero-touch 08:00 login once the setup key is stored | daily | PUBLISH-CORE (PLAN §g) |

---

## 1. Verdict vocabulary, badge rules and the counts

**Verdict (per source / metric)** — the owner's gate: "will it be useful to refer to the data? if yes then only publish".

| Verdict | Meaning in the terminal |
|---|---|
| **PUBLISH-CORE** | ingested into DuckDB (or computed) and shown on the GOLD page's primary panels; may feed the health strip, the WEI card and the BRF line |
| **PUBLISH-CONTEXT** | ingested and shown inside its section or a details drawer, always with the `context` badge; never on WEI/BRF; never a buy/sell colour |
| **LINK-ONLY** | a labelled link button (publisher page), nothing fetched by the stack |
| **DO-NOT-PUBLISH** | not fetched, not shown (dead, blocked by terms, no gold content, or shown to be noise) |

**Evidence badge (per metric, PLAN §f)** — separate from the verdict: `signal` (a pre-registered study PASSED as a forecast in both
halves after costs — **none today**), `context` (PASS as a description, or context-only), `arithmetic` (an identity, cost or
spec: makes no claim about the future), `heuristic` (a house rule with no evidence yet: the ₹300 chase limit, the headline
risk count). A number with no verdict row in `gold_series_catalog` is not rendered.

**Counts (sources, this file; one per `### <id>` entry, classified from its `**Verdict:**` line by `G-SYNTH/count_verdicts.py`):**
PUBLISH-CORE **28** · PUBLISH-CONTEXT **41** · LINK-ONLY **53** · DO-NOT-PUBLISH **18** — **140 entries**. Derived metrics (§10, 71 rows):
PUBLISH-CORE 36 · PUBLISH-CONTEXT 27 · LINK-ONLY 3 · DO-NOT-PUBLISH 5. The 28 PUBLISH-CORE sources: A1, A2, A5, A6, A11, B1, B3, C1,
C3, C4, D3, E1, E5, E12, F1, F2, F9, F10, G1, G2, G3, G5, G8, G16, G19, H2, H3, I4.

---

## 2. Disagreements between agents, resolved

| # | Topic | Positions | Decision and reason |
|---|---|---|---|
| 1 | Where gold lives | G-COT: MCXG or a GOLD page; G-STUDY: MCXG + WEI echo; G-APP: one new page GOLD; G-KITCO: GOLD with 9 sub-views; G-PHYSICAL: a GPHY page; G-MACRO: a GMAC view; G-EDU: a LRN page | **One new page, code `GOLD` (id `gold`, aliases `XAU`, `GC`, `GPHY`, `GMAC`, `LRN` → sub-views)**. Three new pages would triple the repetition the owner called a defect; the owner asked for "a visual separately", singular. MCXG stays the trading desk. |
| 2 | Pre-open desk home | G-APP: move from CMDT to GOLD; G-KITCO: keep in CMDT ("pre-open workflow artefact"); G-EDU: keep the accuracy log next to the verdict | **Moves to GOLD › HEALTH ("Today's open")**, with the accuracy log beside it; CMDT keeps a "GOLD ›" chip on its gold tile. G-APP's fetch map shows the model printed in five places; one home ends that. The 08:45/09:10 jobs keep posting to aliased endpoints. |
| 3 | BRF gold panel | G-APP: one line; G-KITCO: keep the full panel + one line | **One line** (before 09:00: fair/gap/verdict/health; after the captured open: open vs fair, miss). The Telegram 08:45 alert carries the rest. |
| 4 | Health check | G-APP: 7 chips with a supportive/headwind score; G-KITCO: 8 gauges + descriptive verdict; G-EDU: five numbers, "no composite index because none is a validated predictor"; G-STUDY: every driver FAILS as a forecast | **Five-number strip (header) + eight gauges + a rule-based descriptive sentence; no score, no count of "supportive" drivers.** A score reads as a forecast; 0 of 69 walk-forward rules beat buy-and-hold. Every gauge carries `context`. |
| 5 | COT verdict | G-COT: PUBLISH-CONTEXT (panel), CORE for the descriptive metrics; G-STUDY: "who did what" strip CORE, index CONTEXT, options-only DO-NOT-PUBLISH; G-KITCO/G-EDU: CORE | **Source and the weekly "who did what" strip: PUBLISH-CORE with the `context` badge ("explains the week, does not forecast"); COT index / z / percentile: PUBLISH-CONTEXT crowdedness gauge labelled "no forecasting power 2006–2026 (G-STUDY)"; options-only: one line in the details drawer (the owner wrote "Futures/Options" verbatim, G-STUDY found no information in it). No COT alert, no COT rule, nothing feeds the Decision Desk or the ticket.** |
| 6 | Legacy COT report | G-COT: PUBLISH-CORE (ingest, 1986→); G-STUDY: LINK-ONLY | **Ingest (same job, zero cost) for the 1986–2006 history chart; never a panel of its own.** |
| 7 | Customs duty | G-INDIA: 15 % since 13 May 2026 (Notification 16/2026-Customs; secondary sources, CBIC cert chain broken); G-EDU knew 6 %; G-PHYSICAL and G-MACRO flagged the unexplained 18–20 % "premium" | **15 % (BCD 10 % + AIDC 5 %), effective 2026-05-13, stored as a dated constant; owner confirms at CBIC in a browser (PLAN §i O-3).** "Implied premium" is split into duty (dated) + MCX basis vs duty-paid landed. |
| 8 | GLD daily tonnes | G-PHYSICAL: CORE; G-STUDY/G-KITCO/G-MACRO: CONTEXT (issuer disclaimer); G-EDU: LINK-ONLY (saw only the CSV→PDF path) | **PUBLISH-CORE, display-only with attribution on the private terminal, derived series stored, file never re-served; badge `context`.** The XLSX endpoint was verified by four agents; G-EDU's path is dead. Owner terms decision O-1 can downgrade to LINK-ONLY. |
| 9 | LBMA price | all: LBMA JSON blocked, FRED series removed; G-PHYSICAL found WGC's open `fsapi.gold.org` chart API serving LBMA AM/PM daily (1 y) | **PUBLISH-CONTEXT, provisional**: reference marks (AM/PM) and the base for the Shanghai/India premiums, fetched once a day, attributed, gated on O-1 (WGC T&Cs forbid scraping/redistribution; the price inside is IBA-licensed). Yahoo `GC=F` stays the stored benchmark. |
| 10 | Yahoo history | G-KITCO: daily-since-2000 and FX pairs UNVERIFIED (429); G-MACRO: verified all of them with `period1/period2` and the app UA | **Verified (G-MACRO `verification_yahoo_daily.json`)**. Rules: one fetcher, the app UA, `period1/period2` never `range=max` for daily bars, ≤ 6 chart calls/min across the app. |
| 11 | CME data | G-CME: FTP server works (OI by product daily since 2014, EFRP, calendar, product reference); G-EDU/G-KITCO/G-STUDY/G-APP: CME LINK-ONLY (saw only the www 403) | **FTP sources PUBLISH-CORE/CONTEXT; www files LINK-ONLY until the owner resolves the IP block with CME (O-2); CmeWS JSON DO-NOT-PUBLISH.** This answers the "daily: no" of G-COT: daily COMEX OI exists. |
| 12 | Seasonality | G-KITCO: proposes G-STUDY-SEASON; G-MACRO H3 (1971→) and G-STUDY §4.4 (2006→) already ran it: no month passes in both halves | **Done; CONTEXT-ONLY grid with the caveat; no further study.** |
| 13 | Real yields / DXY on the gold page | G-MACRO: CORE with history; G-STUDY: "do not duplicate, already on the Pre-Open page" | **One home: GOLD › MACRO driver strip (the Pre-Open context table moves there).** No duplication once the desk moves. |
| 14 | Event-risk headline count | G-APP: DO-NOT-PUBLISH as advice; G-EDU: HEURISTIC chip | **Keep the count as a label with the `heuristic` badge; drop the "consider half size" advice.** |
| 15 | India price stack placement | G-INDIA: an "India stack" strip on MCXG; G-APP: MCXG overlay shrinks to one line | **The ladder (COMEX → ×INR → landed → +duty → duty-paid → IBJA → MCX basis/carry) lives once on GOLD › PHYSICAL; MCXG's overlay becomes one line linking to it.** |
| 16 | WEI card contents | G-APP: 2-line cue card; G-KITCO: row + 4-number hover; G-COT: a COT chip; G-CME: OI/carry/roll strip; G-PHYSICAL: LBMA PM chip; G-INDIA: basis number; G-STUDY: 2-line COT echo | **The GC=F row stays; one second line only: verdict words · MCX basis % · COT MM net (Δ w/w) · next roll date · `GOLD ›`; the hover shows the five-number strip.** Nothing else. |
| 17 | kitconet "Kitco mini" tile | G-KITCO: optional, off by default, "recommendation: drop" | **Dropped (DO-NOT-PUBLISH):** 172×114 px, HTTP-only (mixed content in the desktop webview), unverifiable data. |
| 18 | Options-only / Swissquote / Perth Mint / AMFI NAV | each proposed CONTEXT by one agent | downgraded (drawer / LINK-ONLY) on usefulness: see entries B2, A14, E18, F17. |
| 19 | COT index "washed-out" reading | G-COT H3: bottom-decile net % OI → +5.2 % over 65 sessions (t 2.6 full, 1.4/1.3 halves); G-STUDY: COT index ≤ 10 earns less than ≥ 90 | **Both FAIL the halves rule; the sentence "washed-out positioning has preceded good quarters more often than not" may appear in LEARN, never as a badge.** |
| 20 | Where the five G-EDU tables / seven G-APP tables / ten G-KITCO tables go | overlapping schemas from six agents | **One reconciled schema (PLAN §c): generic PIT `gold_series` for single-value series, typed tables where a long format does not fit (COT, CME, curve, bars, Asia, ETF, events, log, brief, health).** |

---

## 3. Repetition audit (today) and the consolidation decision

| Number | Printed today (G-APP inventory) | After phase 2 |
|---|---|---|
| Model fair open / fair value | CMDT desk (stat + table + waterfall), MCXG quote fallback, MCXG overlay, BRF panel, 08:45 Telegram | GOLD › HEALTH once; MCXG one-line overlay; BRF one line; Telegram unchanged |
| COMEX gold price | macro tape (GC=F), WEI (GC=F), CMDT board (GC=F), CMDT desk (GCZ26), MCXG overlay (GCZ26) — two instruments never distinguished | tape (label "GOLD GC1"), WEI row, CMDT board tile, GOLD header strip (named: spot proxy / GC1 / matched month / MCX) |
| USD/INR | tape, WEI, CMDT desk, MCXG overlay | tape, WEI, GOLD header |
| MCX settlement / band | CMDT desk, MCXG quote fallback, MCXG specs | MCXG quote; GOLD header (labelled by **session**, never by file date) |
| Implied premium | CMDT desk, MCXG overlay | GOLD › PHYSICAL ladder (split into duty + basis); MCXG one-line |
| DXY, US10Y, EUR/USD, silver, TIPS | WEI rows, CMDT desk context table | WEI rows; GOLD › MACRO driver strip (one home for the gold-signed view) |
| Headlines | CMDT desk, BRF, News terminal | GOLD › HEALTH (gold topics only), News terminal; BRF market headlines unchanged |
| Accuracy stats | CMDT log, BRF after 09:00 | GOLD › HEALTH (full log), BRF one line (miss) |
| Contract / expiry / OI lots | CMDT subtitle, MCXG quote, MCXG specs | MCXG selector (replaces the specs card), GOLD › CONTRACTS chain |
| Manual-check links (10) | CMDT desk | 4 become numbers (SGE, ETF flows, GLD, real yields); Fed odds becomes the Atlanta Fed panel; the rest (FedWatch, MCX circulars, FBIL, TradingView, Kitco) move to GOLD › PHYSICAL/CONTRACTS "linked" lists; investing.com link removed (403 to scripts; INR=X is in the app) |

---

## A. Prices and benchmarks

### A1 · Yahoo Finance chart API — COMEX gold front future `GC=F`
*What is gold worth right now, and what did it do over any window from one minute to 26 years?*
- **Publisher / URL:** Yahoo Finance (unofficial, undocumented) · `https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=7d&interval=1m&includePrePost=true` · daily history **only** via `https://query2.finance.yahoo.com/v8/finance/chart/GC=F?period1=<epoch>&period2=<epoch>&interval=1d`
- **Access:** FREE · **Verified:** G-KITCO 05:42 IST: `1d/5m` 200 · 305 ms · `regularMarketPrice 4003.4, previousClose 4007.9, 52w 5586.2/3901.3`; `7d/1m` 200 · 379 ms · 8,748 timestamps, 6,998 closes (19 → 26 Oct); `60d/5m` 17,016 bars; `10y/1wk` 523 bars; G-MACRO `period1/period2` daily 200 · 518 ms · **6,564 rows 2000-08-30 → 2026-10-25**; G-STUDY the same. Trap (three agents): `range=max&interval=1d` silently returns **monthly** bars. Trap: a browser-like or `python-httpx` UA gets **429**; only the app's `Mozilla/5.0 (SuryaDhana-GoldDesk)` on `query2` got 200; G-KITCO's ~25 calls/min triggered a 429 that lasted ≥ 16 min.
- **Frequency / lag / history:** ≈1 min delayed; 1-min bars kept 7 days, 5-min 60 days; daily since Aug 2000.
- **Terms:** Yahoo ToS, personal use, no redistribution; the app already relies on it (tape, WEI, CMDT, GPO, MCXG).
- **[B]** The world's benchmark gold price is the COMEX December future, not "spot". **[P]** `GC=F` rolls by Yahoo's rule a few days before first notice (after ≈25 Nov it is Feb-27 while MCX Dec trades to 4 Dec); the "close" is the last trade, not the settlement (23 Oct: 4,001.30 vs settlement 4,007.90).
- **Pros use it:** `GC1 Comdty GP/GIP` — the chart under everything; settlement from the bulletin.
- **Evidence:** it is the price. Time-series momentum in gold is documented (Moskowitz–Ooi–Pedersen 2012, cited by G-KITCO, not re-verified) and weak.
- **In app today:** five surfaces. **Consolidation:** one fetcher (`gold_preopen._yahoo_bars_cached`), data-service owns history (`gold_daily_bars`, `gold_bars_intraday`).
- **Verdict:** PUBLISH-CORE — the stored benchmark; every chart on the page. · **Catalog:** `COMEX_GC_FRONT` · tables `gold_daily_bars`, `gold_bars_intraday` · jobs `gold_overnight`, `gold_intraday_bars`

### A2 · Yahoo per-contract COMEX months `GCZ26.CMX, GCG27.CMX, GCJ27.CMX, GCM27.CMX, GCQ27.CMX, GCZ27.CMX` (+ `MGC=F`, `SIZ26.CMX`)
*Which December/February/April price is which, and what does the curve say?*
- **URL:** `https://query1.finance.yahoo.com/v8/finance/chart/GCZ26.CMX?range=5d&interval=1d`
- **Access:** FREE · **Verified:** G-CME 08:30 IST, 0.24–0.77 s each: Dec-26 3,999.6 · Feb-27 4,035.8 · Apr-27 4,081.2 · Jun-27 4,115.0 · Aug-27 4,142.6 · Dec-27 4,209.0 (previous closes 4,142.6 … 4,355.3); G-KITCO 05:45: 4,002.9 / 4,044.0 / 4,081.2 / 4,115.0 / 4,142.6 / 4,209.0. **No open interest; last trade, not settlement.** Back months print sparsely (Feb-27 139 contracts of 5-min volume vs 4,422 Dec-26).
- **Frequency / lag:** intraday, delayed. · **Terms:** as A1.
- **[B]** Later months cost more (contango) because carrying metal costs interest and storage. **[P]** implied carry Dec→Feb = (4,041.30/4,007.90 − 1) × 365/57 ≈ 5.3 % p.a. on settlements (G-CME); the Yahoo-last version differs by a few dollars.
- **Pros use it:** `CT` (contract table), `CCRV` (curve today vs a week ago).
- **Evidence:** roll yield is a cost, not a forecast (G-KITCO citing Erb–Harvey 2006; not re-verified).
- **In app today:** `GCZ26.CMX` only (fair value). **Consolidation:** the curve is new; stored daily with a 1-week ghost.
- **Verdict:** PUBLISH-CORE — the curve, calendar spreads, carry; label "last trade, not settlement" until C7 is allowed. · **Catalog:** `gold_curve` rows exchange `COMEX`, source `yahoo` · job `gold_overnight`

### A3 · Yahoo `SI=F` (silver), `PL=F` (platinum), `CL=F` (WTI)
- **Verified:** G-MACRO daily 2000→ (SI=F 6,565 rows, PL=F 6,591, CL=F 6,572); G-CME SI=F 53.83 (26 Oct). · **Access:** FREE.
- **[B]** The gold/silver ratio (74) says how many ounces of silver buy one of gold; it drifts for years. **[P]** G/S median since 2000 ≈ 70, range 32–126 (G-MACRO); G/Pt 2.58 is the 95th percentile.
- **Evidence:** no predictive evidence for gold; relative-value context only.
- **In app today:** silver on WEI, CMDT, GPO. **Consolidation:** ratio line on GOLD › MACRO only.
- **Verdict:** PUBLISH-CONTEXT — ratios with percentiles. · **Catalog:** `COMEX_SI_FRONT`, `NYMEX_PL_FRONT` · `gold_daily_bars`

### A4 · Yahoo `GLD`, `GOLDBEES.NS`, `TIP`, `IEF`
- **Verified:** G-MACRO daily: GLD 2004-11-18→ (5,517 rows), GOLDBEES.NS 2009-01-02→ (4,388 rows, ₹115.96 on 23 Oct), TIP 2003→, IEF 2002→; G-KITCO GOLDBEES `1mo/1d` 200.
- **[B]** GOLDBEES is an Indian gold ETF: the only free **rupee gold price with 17 years of history**. **[P]** tracks duty-paid Indian gold incl. expense drag; GLD vs GC=F weekly correlation 0.983 (G-STUDY roll check); GLD price vs NAV = ETF premium/discount.
- **Verdict:** PUBLISH-CONTEXT — the ₹ return ladder and the ETF premium; not a second gold price on any page. · **Catalog:** `GOLDBEES_CLOSE`, `GLD_CLOSE` · `gold_daily_bars`

### A5 · Yahoo FX: `INR=X`, `DX-Y.NYB`, `EURUSD=X`, `JPY=X`, `GBPUSD=X`, `CAD=X`, `SEK=X`, `CHF=X`, `CNY=X`
- **Verified:** G-MACRO daily via `period1/period2`: DX-Y.NYB 1990→ 9,381 rows (last 101.687), INR=X 2003-12→ 5,939 rows (94.93), EURUSD 2003→, JPY 1996→, GBPUSD 2003→, CAD 2003→, SEK 2001→, CHF 2003→, CNY 2001→ (6,344 rows, 6.6606). Trap (G-PHYSICAL): `CNY=X` had no 23 Oct row — use the previous close or PBOC parity for the Shanghai premium.
- **[B]** MCX gold = world gold × the rupee; a 1 % rupee move is a 1 % MCX move with gold flat. **[P]** the DXY is a six-currency geometric basket (EUR 57.6 %, JPY 13.6 %, GBP 11.9 %, CAD 9.1 %, SEK 4.2 %, CHF 3.6 %); the KGX decomposition `usd_move = −Σ wᵢ Δln fᵢ`, `pure_gold = gold_usd + usd_move`.
- **Evidence (G-MACRO H2):** weekly beta of gold to DXY ≈ −1.0 in every regime (t −11.6 / −13.2 / −6.4) — a contemporaneous explainer; G-STUDY: 4-week DXY change forecasts nothing (t ≤ 1.4).
- **In app today:** INR=X (tape, WEI, desk, MCXG), DXY (WEI, desk), EURUSD (WEI, desk). **Consolidation:** GOLD header (INR), MACRO (KGX bar, gold in currencies); the desk's context rows go.
- **Verdict:** PUBLISH-CORE — inputs to landed cost, KGX and gold-in-currencies. · **Catalog:** `USDINR_CLOSE`, `DXY_CLOSE`, `FX_<PAIR>` · `gold_daily_bars`

### A6 · Yahoo `^GVZ` (CBOE gold ETF volatility), `^VIX`, `^TNX`
- **Verified:** G-MACRO `^GVZ` 2008-06-03→ (4,628 rows, last 24.34 on 23 Oct), `^VIX` 1990→, `^TNX` 1990→ (4.988).
- **[B]** GVZ is the market's expected 30-day swing in gold; divide by √252 for one day. **[P]** GVZ 24.15 → 1σ day = 1.52 % ≈ $61/oz ≈ ₹2,200 on the MCX quote ≈ **₹2.2 lakh per 1-kg lot** (G-MACRO); realised 20-day vol 14.9 %; `^TNX` = CBOE 10-y yield ×10, the only free intraday nominal-yield proxy (real ≈ ^TNX − last T10YIE).
- **Evidence:** sizing arithmetic (no forecast claim).
- **Verdict:** PUBLISH-CORE — the "expected move per lot" tile. · **Catalog:** `GVZ_CLOSE`, `VIX_CLOSE`, `TNX_CLOSE` · `gold_daily_bars`

### A7 · Yahoo `XAUUSD=X` (spot), `XAU=X`, `PAXG-USD`
- **Verified:** `XAUUSD=X` **404** "No data found, symbol may be delisted" (G-KITCO ×2, G-MACRO ×2). `XAU=X`, `PAXG-USD`: 429 only (G-KITCO) → UNVERIFIED.
- **Verdict:** DO-NOT-PUBLISH — the symbol does not exist; a Yahoo "spot" is not available. The app's `spot_proxy` field must say "COMEX front, not spot".

### A8 · LBMA Gold Price AM/PM (prices.lbma.org.uk JSON; MyLBMA portal)
- **URL:** `https://prices.lbma.org.uk/json/gold_pm.json` (and `gold_am.json`, `silver.json`); page `https://www.lbma.org.uk/prices-and-data/precious-metal-prices`
- **Access:** PAID (IBA licence) · **Verified:** JSON **403 Cloudflare** with browser, plain and curl UAs (G-KITCO, G-MACRO, G-PHYSICAL); the page (200, 1.1 s) says the tables "have moved to the MyLBMA Portal" and "A licence from IBA is required in order to obtain, use or redistribute real-time or historical benchmark data".
- **[B]** The twice-daily London auction price (10:30 and 15:00 London = 16:00 / 20:30 IST on GMT) that contracts, ETFs and SGBs settle on. **[P]** the AM/PM are auction clearing prices, not a continuous quote; UK moved to GMT on 25 Oct 2026.
- **Verdict:** LINK-ONLY — licensed; never scrape. The fix times are drawn as marks on the chart; the value comes from A9 (provisional) or the COMEX print at 15:00 London.

### A9 · LBMA AM/PM, SGE AM/PM and MCX AM/PM via the World Gold Council chart API
- **URL:** `https://fsapi.gold.org/api/goldprice/v13/chart/main?period=1y`
- **Access:** FREE (no login) but terms-gated · **Verified (G-PHYSICAL):** 200, daily 252 points for 1 y (LBMA AM/PM in USD/GBP/EUR, SGE AM/PM in CNY, MCX AM/PM in INR); last 23 Oct 2026 LBMA PM $4,013.30; `3y`/`10y` downsampled (381/425 points); `…/chart/price/` gives USD back to the 1970s at coarse granularity; timestamps are epoch-ms midnight UTC of the London date. Note G-KITCO's probe of a different endpoint (`…/charts/spotprice`) got 429.
- **Terms:** WGC T&Cs: personal/non-commercial use, no scraping/redistribution/framing without written authorisation; the LBMA price inside is IBA-licensed (owner action O-1).
- **Verdict:** PUBLISH-CONTEXT (provisional) — one fetch a day for AM/PM reference marks and the premium bases; attributed; not the charted series; downgrade to LINK-ONLY if O-1 says no. · **Catalog:** `LBMA_AM_USD`, `LBMA_PM_USD`, `SGE_AM_CNY_WGC`, `MCX_AM_INR_WGC` · `gold_series` · job `gold_london_close`

### A10 · FRED `GOLDAMGBD228NLBM` / `GOLDPMGBD228NLBM`
- **Verified:** **404** (five agents); SPDR's XLSX states the LBMA price "has been removed at the request of the ICE Benchmark Administration" (Jan 2022).
- **Verdict:** DO-NOT-PUBLISH — the series no longer exists; remove the assumption from any doc that cites it.

### A11 · Shanghai Gold Benchmark Price (SHAU) AM/PM — SGE
- **URL:** `https://en.sge.com.cn/graph/DayilyJzj` (JSON `{zp: AM, wp: PM}`, daily since 19 Apr 2016, 2,553 points) · `https://en.sge.com.cn/data_BenchmarkPrice_Daily` (HTML, last 7 sessions) · `data_MonthlyAveragePrice` since 2016-04
- **Access:** FREE · **Verified:** G-CME 200 · 2.6 s · 117 KB (first value 256.92 CNY/g); G-PHYSICAL 23 Oct AM 862.91 / PM 862.76 CNY/g; the JSON lags the HTML by a day.
- **Frequency:** daily, AM ≈10:15 / PM ≈14:15 Beijing (07:45 / 11:45 IST).
- **[B]** China's official gold price per gram. **[P]** PM is 14:15 Beijing vs LBMA PM 15:00 London — a 7-hour gap; compare with LBMA AM or the COMEX print at 14:15 Beijing on volatile days, or the level embeds clock error.
- **Terms:** SGE lists licensed distributors; view-only, no redistribution.
- **Verdict:** PUBLISH-CORE — the base of the Shanghai premium. · **Catalog:** `SGE_SHAU_AM`, `SGE_SHAU_PM` · `gold_series` · job `gold_asia_close`

### A12 · gold-api.com real-time XAU (keyless)
- **URL:** `https://api.gold-api.com/price/XAU` · **Verified (G-KITCO):** 200 · 637 ms · `{"price":3991.60,"updatedAt":"2026-10-26T00:13:42Z"}` on a Sunday evening. Terms (10 Sep 2026): free 24/7, "commercial use … always permitted", no accuracy guarantee, IP ban for multiple requests per second; provider unnamed.
- **Verdict:** PUBLISH-CONTEXT — a 24/7 spot cross-check chip in the header (≤ 1 call/min), never the charted series. · **Catalog:** `XAU_CROSSCHECK` (not stored)

### A13 · Swissquote public XAU/USD quotes
- **URL:** `https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD` · **Verified (G-KITCO):** 200 · 1.13 s · bid/ask per spread profile. Terms UNVERIFIED; undocumented.
- **Verdict:** LINK-ONLY — adds nothing beyond A12; terms unknown (downgraded from G-KITCO's CONTEXT).

### A14 · stooq.com daily CSV (`xauusd`, `xagusd`, `xptusd`, `usdinr`, `dx.f`, `gc.f`)
- **URL:** `https://stooq.com/q/d/l/?s=xauusd&i=d` · **Verified:** 200 but the body is a JavaScript proof-of-work challenge (796 B) for every symbol, browser and curl UAs (G-KITCO, G-MACRO, G-CME, G-STUDY).
- **Verdict:** DO-NOT-PUBLISH — BLOCKED; Yahoo covers it.

### A15 · goldprice.org `dbXRates` API and widget
- **URL:** `https://data-asg.goldprice.org/dbXRates/USD` · **Verified (G-KITCO):** 403 plain; 200 only with a spoofed `Referer: https://goldprice.org/`; the site's main chart is a TradingView embed.
- **Verdict:** DO-NOT-PUBLISH — works only by misrepresenting the client.

### A16 · investing.com XAU/USD and USD/INR pages
- **URL:** `https://www.investing.com/currencies/xau-usd` · **Verified:** 403 (G-KITCO). The desk's "USD/INR" manual-check link points at investing.com today.
- **Verdict:** DO-NOT-PUBLISH — blocked; remove the manual-check link (INR=X is in the app).

### A17 · BullionVault price chart and order-board JSON
- **URL:** `https://www.bullionvault.com/gold-price-chart.do` (and `view_market_json.do`) · **Verified (G-KITCO):** 200 · 520 ms · best buy 128,190 $/kg (= 3,987.15/oz).
- **Verdict:** LINK-ONLY — their exchange's order book, not spot; LEARN borrows its "three prices" explanation.

### A18 · Trading Economics gold page
- **URL:** `https://tradingeconomics.com/commodity/gold` · **Verified (G-KITCO):** 200; the price is a CFD; forecasts are a model's; API paid.
- **Verdict:** LINK-ONLY.

### A19 · Nasdaq Data Link `CHRIS/CME_GC1`
- **URL:** `https://data.nasdaq.com/api/v3/datasets/CHRIS/CME_GC1.json?rows=3` · **Verified (G-CME):** 403, discontinued.
- **Verdict:** DO-NOT-PUBLISH — the FTP archive (C1) replaces it for OI, Yahoo for prices.

### A20 · Nasdaq Data Link `LBMA/GOLD`
- **URL:** `https://data.nasdaq.com/api/v3/datasets/LBMA/GOLD.json?rows=3` · **Verified (G-PHYSICAL):** 403 Incapsula without a key → UNVERIFIED.
- **Verdict:** LINK-ONLY — unverifiable; a keyed route may exist.

### A21 · Kitco live gold charts page (the owner's link)
- **URL:** `https://www.kitco.com/charts/gold` · terms `https://www.kitco.com/terms-of-use` (3 Jan 2024)
- **Verified (G-KITCO, 05:42 IST = 25 Oct 20:12 NY):** 200 · 1.44 s · 119 KB Next.js page; bid 3,987.20 / ask 3,989.20 from Kitco's dealer feed, no delay statement; units and purity tables; 24-h NY chart (08:00–17:00 axis, two previous closes, dashed "Last Close"), 3-day overlay with SHANGHAI/LONDON/NEW YORK/SYDNEY bands, legacy 30/60-day GIFs with London AM/PM, monthly archive 2000→, performance widget 3 d → 15 y in 13 currencies, gold-in-currencies computed client-side, gold/silver 74.1, KGX blurb. `robots.txt` `Allow: /`; terms forbid robots, data-mining, framing, mirroring, redistribution; no API, no data-licensing contact. **Zero COT content** (G-COT).
- **Verdict:** LINK-ONLY — every visual is reproduced from A1/A2/A5 with IST and MCX hours added (PLAN §a DAILY); never embed or scrape.

### A22 · Kitco Gold Index (KGX) page
- **URL:** `https://www.kitco.com/markets/kitco-gold-index` · **Verified (G-KITCO):** 200 (the old `/kitco-gold-index` is 404); weights EUR 57.6 / JPY 13.6 / GBP 11.9 / CAD 9.1 / SEK 4.2 / CHF 3.6; "change due to USD" vs "change due to predominant buyers".
- **Verdict:** LINK-ONLY — the method is public and replicated (MACRO "gold or the dollar?" bar, generalised with a rupee leg); Kitco's numbers are proprietary.

### A23 · kitconet.com free embeddable chart images
- **URL:** `https://www.kitconet.com/webcharts/au_en_us.html` (images `http://www.kitconet.com/charts/metals/gold/t24_au_en_usoz_2.gif`, INR variants) · **Verified (G-KITCO):** 200, 172×114 px, per minute, licensed free "if the image is a hotlink to www.kitco.com".
- **Verdict:** DO-NOT-PUBLISH — dropped (disagreement 17): unreadable, HTTP-only, unverifiable data.

### A24 · Kitco site chart images (`charts.kitco.com/images/live/*.webp`, `kitco.com/chart-images/LFgif/*.gif`)
- **Verified (G-KITCO):** 200 (88–502 ms); not on the kitconet licence; hot-linking = "mirroring".
- **Verdict:** DO-NOT-PUBLISH — design reference only (Appendix B of G-KITCO maps each feature to our build).

### A25 · TradingView chart link (`COMEX:GCZ2026`, `GC1!`)
- **Verified:** not re-verified today; the app already opens it (`ChartActions.futuresInstrument('GC=F')` → `GC1!`; manual-check link).
- **Verdict:** LINK-ONLY — stays in CONTRACTS "linked"; the sandboxed TradingView embed is noted in memory as a US-only path.

---

## B. Positioning — CFTC Commitments of Traders (COMEX gold, contract-market code **088691**; also 088695 MICRO GOLD, 088LM1 Coinbase 1-oz)

### B1 · CFTC Public Reporting API — Disaggregated, futures-only (dataset `72hh-3qpy`)
*Who held COMEX gold last Tuesday — producers/merchants, swap dealers (banks), managed money (funds), other reportables, small traders — and who added or closed this week?*
- **Publisher / URL:** CFTC (Socrata) · `https://publicreporting.cftc.gov/resource/72hh-3qpy.json?$where=cftc_contract_market_code in ('088691','088695','088LM1')&$order=report_date_as_yyyy_mm_dd ASC&$limit=50000` · light CSV: `…/72hh-3qpy.csv?$select=report_date_as_yyyy_mm_dd,cftc_contract_market_code,open_interest_all,m_money_positions_long_all,m_money_positions_short_all&$where=cftc_contract_market_code='088691'&$order=report_date_as_yyyy_mm_dd DESC&$limit=3`
- **Access:** FREE, no key (optional free Socrata app token `CFTC_APP_TOKEN` lifts the shared per-IP throttle) · **Verified:** G-COT 200 · 2.2–11.7 s full history · **1,063 rows 2006-06-13 → 2026-10-20** for 088691 (1,237 incl. micro/Coinbase), 194 fields; G-STUDY cross-checked row-for-row against 44 CFTC zips: identical; G-EDU 200 · 1.3 s; G-KITCO 200 · 1.2 s. Latest (as of Tue 20 Oct 2026, released Fri 23 Oct 15:30:13 ET): OI 402,279 (+5,934); producer/merchant 19,715 L / 34,498 S; swap dealers 17,737 L / 238,536 S / 22,079 spread; **managed money 120,970 L / 16,764 S / 38,634 spread = net +104,206**; other reportables 116,172 L / 20,513 S; non-reportable 51,407 L / 15,690 S; 288 traders.
- **Frequency / lag / history:** weekly, Tuesday positions, released Friday 15:30 ET = **Sat 01:00 IST (02:00 IST from 7 Nov 2026)**; 2026 Monday releases 16 Nov, 30 Nov, 28 Dec; history 13 Jun 2006 →. The 2027 schedule is not yet published.
- **Parsing traps (G-COT):** every value is a JSON string; `report_date_as_yyyy_mm_dd` = `"2026-10-20T00:00:00.000"`; `cftc_commodity_code` is `"088 "` with a trailing space in 370 rows — filter on `cftc_contract_market_code`; CFTC typos must be spelled exactly (`noncomm_postions_spread_all`, `change_in_noncomm_spead_all`, `swap__positions_short_all`, `tot_rept_positions_short`); `id` = YYMMDD + code + F/C is the natural key; default `$limit` is 1,000 — always set it; 24 of 1,778 weekly-era reports carry a non-Tuesday as-of date (holidays) — key on the date itself; the CFTC occasionally republishes corrected weeks — keep the raw payload.
- **Terms:** US federal work, public domain (17 U.S.C. §105); `cftc.gov/robots.txt` says `ai-train=no` (not a restriction on display); `Crawl-delay: 1`.
- **[B]** Every contract has one long and one short, so the report shows who is on which side by *type* of trader, never by name; "spreading" is a trader long one month and short another (not a directional bet). **[P]** commercial long (legacy) = producer long + swap long + swap spread (verified on 20 Oct: 59,531 = 19,715 + 17,737 + 22,079); categories are self-declared (Form 40) and reclassifications look like flows; reporting level 200 contracts (17 CFR 15.03).
- **Pros use it:** Bloomberg `CFTC <GO>` / tickers `…MML/MMS/…N`; the CME COT tool; desks read managed-money net vs price and the week-on-week change; the "COT index" lore (≥ 90 sell / ≤ 10 buy).
- **Evidence (our own, two independent studies):** **G-STUDY** (1,063 reports, signals dated at the release, entry next session's close, Newey-West, 0.15 % costs): FAIL as a forecast at 1/4/13 weeks for every metric (1 of 45 rank-IC tests reaches |t| 2; the classic index rule points the wrong way: crowded weeks +1.08 % vs washed-out +0.63 % at 4 weeks; 0 of 69 walk-forward rules beat scaled buy-and-hold). **PASS as description:** same-week Δ managed-money net vs the week's price move Spearman **+0.65** (R² 31 %, stable +0.66/+0.70/+0.60 by sub-period), commercials −0.66 (mirror), next-week correlation −0.02. **G-COT COT-1** (same data, different design): no signal clears t ≥ 2 in both halves; same-week Spearman 0.64. The 2024-11 → 2026-03 doubling happened while funds cut net length by 66,900 and OI fell 122,000: the marginal buyer is outside the report.
- **In app today:** nothing. **Consolidation:** one panel (GOLD › POSITIONING); WEI second line carries `COT MM +104k (−2.9k)`; nothing feeds the Decision Desk, the S1 shadow or the paper ticket.
- **Verdict:** PUBLISH-CORE — the owner's first-named ask; the only free, official "who is long/short and what got closed", **labelled "explains the week — does not forecast"**. · **Catalog:** `COT_*` · tables `gold_cot_raw`, `gold_cot`, view `gold_cot_metrics` · job `gold_cot_weekly`

### B2 · CFTC API — Disaggregated, futures **+ options** combined (`kh3c-gbw2`)
- **Verified:** G-COT 1,063 rows 2006→; combined OI 532,443 on 20 Oct (+130,164 futures-equivalent of delta-adjusted options); G-EDU 200 · 1.2 s.
- **[B]** Adds the option book, converted to futures-equivalents by delta. **[P]** options-only net = combined − futures-only per group; a 20 % price move re-deltas the book without any trade; 20 Oct: options add +4,479 to managed-money net; other reportables run an 87k delta-neutral option-spread book.
- **Evidence:** G-STUDY: options-only positioning has no descriptive or predictive information (t ≤ 0.2).
- **Verdict:** PUBLISH-CONTEXT — ingested (same job); shown as one line in the POSITIONING details drawer ("options add +4,479 to funds' net; combined OI 532,443") because the owner asked for "Futures/Options"; nothing else. · **Catalog:** `gold_cot` rows `fut_or_combined='C'`

### B3 · CFTC API — Legacy, futures-only (`6dca-aqww`)
- **Verified:** G-COT **1,939 rows 1986-01-15 → 2026-10-20** (semi-monthly before 30 Sep 1992), 133 fields; non-commercial 237,142 L / 37,277 S / 54,199 spread; commercial 59,531 / 295,113; concentration ratios (top-4 net short 36.5 %); G-CME 200 · 1.3 s; G-EDU 200.
- **Verdict:** PUBLISH-CORE as an ingest (disagreement 6): the only pre-2006 history and the concentration ratios; displayed only in the long history chart and the drawer. · **Catalog:** `gold_cot` rows `report='legacy'`

### B4 · CFTC API — Legacy combined (`jun7-fc8e`)
- **Verified:** G-COT 1,648 rows 1995-03-21 →; two market-name spellings ("GOLD - CEI GOLD" / "GOLD - COMMODITY EXCHANGE INC.", G-STUDY).
- **Verdict:** PUBLISH-CONTEXT — ingested for completeness (drawer only).

### B5 · CFTC API — Traders in Financial Futures (`gpe5-46if`, `yw9f-hn96`)
- **Verified (G-COT):** a `%GOLD%` search returns only "GOLDMAN SACHS COMMODITY INDEX".
- **Verdict:** DO-NOT-PUBLISH — no gold.

### B6 · CFTC API — Supplemental Commodity Index Traders (`4zgm-a668`)
- **Verified (G-COT):** 0 gold rows (agricultural only). · **Verdict:** DO-NOT-PUBLISH.

### B7 · CFTC weekly viewable reports (`deacmxsf.htm`, `deacmxlf.htm`, `deacmxsof.htm`, `deacmxlof.htm`, `other_sf.htm`, `other_lf.htm`, `other_sof.htm`, `other_lof.htm`)
- **URL:** `https://www.cftc.gov/dea/futures/deacmxsf.htm` (COMEX legacy short) · `https://www.cftc.gov/dea/futures/other_lf.htm` (disaggregated long, metals) · **Verified (G-COT):** all 200 · 0.24–0.93 s; the gold block "GOLD - COMMODITY EXCHANGE INC. Code-088691 … OPEN INTEREST: 402,279" quoted verbatim in G-COT §3.1. (`deacmesf.htm`, probed by G-KITCO, is the **CME** page, not COMEX.)
- **Verdict:** LINK-ONLY — the canonical "open the source" link in the drawer; the data comes from B1.

### B8 · CFTC weekly raw text files (`newcot/deafut.txt`, `deacom.txt`, `f_disagg.txt`, `c_disagg.txt`)
- **URL:** `https://www.cftc.gov/dea/newcot/f_disagg.txt` · **Verified (G-COT):** 200 · 0.44–0.49 s · 430–461 KB, no header row (use the archive header as the parser).
- **Verdict:** LINK-ONLY — fallback when the API is down.

### B9 · CFTC historical compressed archives (zips by year and multi-year, text and Excel)
- **URL:** `https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm` → `https://www.cftc.gov/files/dea/history/…` (`deacot1986_2016.zip`, `deacot{yyyy}.zip`, `deahistfo_1995_2016.zip`, `deahistfo{yyyy}.zip` — underscore before 2004, none after; `fut_disagg_txt_hist_2006_2016.zip`, `fut_disagg_txt_{yyyy}.zip`, `com_disagg_txt_*`)
- **Verified:** G-COT 44 zips, 150 MB, all 200, 0.3–6.3 s; G-STUDY the same 44 (147 MB); 2026 zips refreshed every release (`Last-Modified` Fri 23 Oct 19:28 GMT). Numeric fields space-padded.
- **Verdict:** LINK-ONLY — backfill fallback and audit copy (the CSVs in `G-COT/data/` and `G-STUDY/data/` are ready seeds).

### B10 · CFTC release schedule, Historical Special Announcements, press release 7864-19
- **URL:** `https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm` · `https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm` · `https://www.cftc.gov/PressRoom/PressReleases/7864-19`
- **Verified:** G-COT 200 · 0.30 s · 2026 dates listed (G-COT `data/release_calendar_2026_ist.csv`); G-STUDY: the 2025 shutdown catch-up (reports 30 Sep–23 Dec 2025 released 19 Nov–29 Dec 2025), 2023 ION incident, 2019 plan. G-EDU notes the dates are rendered client-side on the schedule page (G-COT parsed them from the HTML successfully).
- **Verdict:** PUBLISH-CONTEXT — `gold_events` rows (`COT_RELEASE`) and the scheduler's retry rule. · **Catalog:** `gold_events`

### B11 · CFTC explanatory notes (legacy, disaggregated) and reporting levels (17 CFR 15.03 via Cornell LII)
- **URL:** `https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm` · `https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm` · `https://www.law.cornell.edu/cfr/text/17/15.03` · **Verified:** 200 (G-COT, G-EDU); gold reporting level 200 contracts.
- **Verdict:** LINK-ONLY — quoted in LEARN.

### B12 · CFTC Bank Participation Report (monthly)
- **URL:** `https://www.cftc.gov/MarketReports/BankParticipationReports/index.htm` · **Verified (G-EDU):** index page 200 · 0.8 s ("monthly on the first Friday after 3:30 ET … first Tuesday's data"); gold rows **not** verified.
- **Verdict:** LINK-ONLY — candidate for a later brief (US vs non-US bank positions in COMEX gold).

### B13 · Socrata app-token documentation
- **URL:** `https://dev.socrata.com/docs/app-tokens.html` · **Verified (G-COT):** 200; "we do not throttle API requests unless … abusive" with a token.
- **Verdict:** LINK-ONLY — owner may add `CFTC_APP_TOKEN=` (optional).

### B14 · Tradingster COT page (legacy futures-only, 088691)
- **URL:** `https://www.tradingster.com/cot/legacy-futures/088691` · **Verified (G-COT):** 200 · 4.3 s; identical CFTC numbers; "COT Analysis / Signals" free "during the preview"; no terms page (`/terms` 404); ads.
- **Verdict:** LINK-ONLY — do not scrape or embed.

### B15 · Barchart Commitment of Traders pages
- **URL:** `https://www.barchart.com/futures/quotes/GC*0/commitment-of-traders` · **Verified (G-COT):** 202 with an empty body (bot wall), also for `/terms` → UNVERIFIED.
- **Verdict:** LINK-ONLY — at most.

### B16 · Bloomberg Professional (`CFTC <GO>`, `GC1 Comdty DES/GP/CT/CCRV/HP`, `XAU Curncy`) and LSEG Workspace (`XAU=`)
- **Verified:** no terminal from this machine (G-COT, G-KITCO) → UNVERIFIED; descriptions from public university guides and BBGsymbols (`https://bautheac.github.io/BBGsymbols/reference/tickers_cftc.html`).
- **Verdict:** DO-NOT-PUBLISH — nothing to publish (paid; no redistribution); the function map goes into LEARN as text so the owner "thinks like a Bloomberg gold trader" with free data (G-KITCO Appendix C).

---

## C. COMEX / CME Group

**Access reality (G-CME, 17 of 17 www URLs):** every path on `https://www.cmegroup.com/` answers **403** *"This IP address is blocked due to suspected web scraping activity … Use of scripts … is strictly prohibited by CME Group's website Data Terms of Use … contact … gcc@cmegroup.com"* — with httpx, curl and a headless Chromium (`ERR_HTTP2_PROTOCOL_ERROR`). The repo never fetched cmegroup.com automatically (only a FedWatch link), so the block predates this program. **`ftp://ftp.cmegroup.com/` (anonymous, a separate AWS host) works** and has been CME's programmatic distribution channel for 15+ years; no terms file in the tree.

### C1 · CME FTP — daily volume and open interest by product (`daily_volume.xlsx`)
*How many COMEX gold contracts exist tonight, per product, every day since 2014 — the daily "which positions got closed" tape.*
- **URL:** `ftp://ftp.cmegroup.com/daily_volume/daily_volume.xlsx` (latest) · archive `daily_volume_YYYYMMDD.xlsx` (3,227 files, 2014-01-02 → 2026-10-22) + `daily_volume_reports_2013.zip`
- **Access:** FREE (anonymous FTP) · **Verified (G-CME):** 99,720 B in 4.1 s; sheet "CME Group Vol and OI by Product", header row 3, **Trade Date 10/22/2026**; nine more dated files 4.4–4.8 s each. Sample 22 Oct: **GC OI 403,397** (Globex 237,695 + OTC 8,324 = 246,019 volume); MGC OI 124,151 (volume 351,808 — above GC); 1OZ OI 87,158; QO 8,551; **OG calls OI 631,061, puts 259,338**; SI 114,637. Cross-check: CFTC Tuesday OI 402,279 vs this file's 20 Oct 402,507 (0.06 %).
- **Frequency / lag / history:** daily, posted the next day 03:30–05:00 on the server clock (inferred US Central → ≈14:00–15:30 IST on T+1; confirm in the first week); 12.8 years.
- **Key fields:** Description, Exchange Name, Commodity Indicator, Product Description, Future/Option Indicator, CME Globex Volume, Pit Volume, ExPit Volume, OTC Volume, Total Volume, MTD ADV, Open Interest (column names contain newlines and a `②` mark — normalise).
- **[B]** Rising price + rising OI = new longs; falling price + rising OI = new shorts; rising price + falling OI = short covering; falling price + falling OI = long liquidation. **[P]** product OI, all months summed; roll weeks (Dec OI −12,246, Feb +9,869 on 23 Oct) and expiry/exercise days are mechanical; COT then says *who*, weekly.
- **Pros use it:** `GCA Comdty OIS`, the "Volume & OI" column on `GIP`; big down days: short build-up vs long liquidation.
- **Evidence:** Hong & Yogo 2012 find OI growth forecasts commodity returns at **monthly** horizons (G-CME, not re-verified); for daily gold: context only until G-STUDY-2 (PLAN §h) — the 12-year daily series makes it runnable.
- **In app today:** nothing. **Consolidation:** GOLD › POSITIONING (daily tape) and DAILY (quadrant label).
- **Verdict:** PUBLISH-CORE — the daily answer to the owner's question; labels are `context`. · **Catalog:** `gold_cme_daily_voi` · job `gold_cme_daily` (15:45 IST, retry 17:15, final in the 03:10 overnight run); backfill 3,227 files ≈ 330 MB, paced 1 file / 2 s ≈ 2 h one-off

### C2 · CME FTP — EFRP transaction breakdown (EFP / EFR prints)
*The privately negotiated "off-screen" deals registered on COMEX — the exchange's window on OTC business.*
- **URL:** `ftp://ftp.cmegroup.com/efrp/efrp_transaction_breakdown/efrp-report.csv` · archive `efrp-report_YYYYMMDD.csv|xlsx` (3,704 entries from 2017-01-20)
- **Verified (G-CME):** `efrp-report_20261023.csv` 33,597 B in 3.6 s; columns `Original Process Date, Product Long Desc, Product Line, Transaction Type Description, Contract Expiry (YYYY-MM), Future/Option Indicator, Volume - Round Turns`; **GOLD: 19 EFP prints, 3,115 round turns, all Dec-2026** — equals the archived Daily Bulletin's EFP column exactly.
- **Frequency / lag:** daily, file for T between 05:03 and 18:45 server clock on T+1 (variable).
- **[B]** An EFP swaps a futures position for physical/OTC gold at a private price: how banks move exposure between London and New York. **[P]** CME publishes EFP **volume**, never the EFP **price**; the price (futures − spot differential) is the physical-tightness number and needs a spot series (A9) — basis minus theoretical carry is the free proxy.
- **Evidence:** none predictive; context (Jan–Mar 2025 record EFP volumes marked the gold migration to New York).
- **Verdict:** PUBLISH-CONTEXT — a small "EFP tape" (today's prints, 20-day average, % of volume). · **Catalog:** `gold_cme_efrp` · job `gold_cme_efrp` (21:30 IST)

### C3 · CME FTP — product calendar XML (first notice, last trade, delivery windows)
- **URL:** `ftp://ftp.cmegroup.com/span/util/product-calendar-new.xml` (38.7 MB; `product_calendar.xml` is an 88-B stub)
- **Verified (G-CME):** 153 s download; `DATE_CREATED 10/23/2026 16:30:49`; per contract `FTD, LTD, SD, LTD_END_TIME (12:30 CT), FID/LID, FND/LND, FDD/LDD`; **GCZ6: first intent 27 Nov, FND 30 Nov 2026, LTD 29 Dec 12:30 CT, LND 30 Dec, delivery 1–31 Dec**; GCG7 FND 29 Jan 2027, LTD 24 Feb; **1OZZ6 and QOZ6 cash-settled, LTD 25 Nov 2026**; 304 COMEX gold/silver contracts parsed to `G-CME/samples/comex_gold_silver_calendar.csv`.
- **[B]** Before first notice day a long can be assigned delivery, so speculators leave the front month in the two weeks before it. **[P]** the Pre-Open desk's `comex_symbol()` must roll GCZ26 → GCG27 around 25 Nov while MCX Dec trades to 4 Dec; 12:30 CT = 23:00 IST (24:00 IST after 1 Nov).
- **Verdict:** PUBLISH-CORE — roll countdown, `gold_events` rows (`COMEX_FND`, `COMEX_LTD`), the desk's month mapping. · **Catalog:** `gold_cme_calendar` · job `gold_cme_calendar` (weekly, Sun 04:00 IST; stream-parse with `xml.etree.iterparse`)

### C4 · CME FTP — COMEX product reference file (specs, settlement method, tick, initial margin, EFP/block eligibility)
- **URL:** `ftp://ftp.cmegroup.com/pub/fprf/csv/cmeg.comex.fut.prf.csv.zip` (46 KB → 583 KB CSV, 82 columns; content `BizDt 2026-10-26` although directory mtimes say Nov 2024)
- **Verified (G-CME):** 4.1 s. Dec-26 rows: **GC 100 oz, physical, tick 0.10, InitMargin 20,302 USD (≈5.1 % of notional at 4,007.90)**, LTD 2026-12-29, FND 2026-11-30, LastEFPDt 2026-12-30; MGC 10 oz 2,031; 1OZ 1 oz cash 204 (LTD 25 Nov); QO 50 oz cash 10,152; SI 22,003; SIL 4,401; SIC 441. The field named `MaintMargin` (GC 1,400, scaling at $14/oz) cannot be the maintenance margin — open question (PLAN §j).
- **[B]** The exact contract: 1 GC ≈ 3.11 MCX GOLD lots; 5 % margin = 20× leverage. **[P]** keep a history of `InitMargin` (margin hikes are events); margins differ slightly by month.
- **Verdict:** PUBLISH-CORE — the DES-style spec card and margin % of notional, daily. · **Catalog:** `gold_cme_prf`, `gold_margins` · job `gold_cme_daily`

### C5 · CME FTP — monthly volume and OI reports (`webmthly/YYYYMM.zip`, 2013 → 202609)
- **Verified (G-CME):** 202609.zip 2.72 MB in 11.8 s, 17 PDFs; GC month-end OI 397,291 (−19.5 % y/y).
- **Verdict:** LINK-ONLY — month-end stats are computed from C1; keep the link for the printed y/y table.

### C6 · CME FTP — SPAN risk-parameter archive (`pub/span/archive/cme/`, 2013–2025)
- **Verified (G-CME):** listed; no 2026 directory. · **Verdict:** LINK-ONLY — margins come from C4.

### C7 · CME Daily Bulletin, Section 62 Metal Futures / Section 63 Metal Options (per-month settlement, OI, volume, ex-pit)
- **URL:** `https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf` · **Access:** BLOCKED (403) · **Verified only via Internet Archive** (`web.archive.org/web/20261025000515id_/…`, 105,656 B, 9 pages, "Fri, Oct 23, 2026 · BULLETIN # 205 · PRELIMINARY"): settlements Oct-26 3,991.10 · **Dec-26 4,007.90 (−52.50)** · Feb-27 4,041.30 · Apr-27 4,073.40 · Jun-27 4,107.90 · Dec-27 4,209.00 · Dec-29 4,597.40; OI Dec-26 **295,084 (−12,246)**, Feb-27 **60,591 (+9,869)**, total 401,548; EFP Dec-26 3,115; deliveries 6 today / 3,208 settled to-date; silver Dec-26 53.949 → gold/silver 74.29.
- **[B]** The official end-of-day sheet: true settlement (what margins are marked to), the term structure, the roll. **[P]** preliminary ≈20:00 CT (06:30 IST next morning), final ≈08:00 CT; `pymupdf` interleaves columns — positional parsing needed.
- **Verdict:** LINK-ONLY until the owner resolves the block (O-2); **PUBLISH-CORE** (one fetch/day) if CME lifts it and the owner rules a once-daily download acceptable personal use. Never via the Internet Archive.

### C8 · COMEX warehouse stocks (`Gold_Stocks.xls`, `Silver_stocks.xls`)
- **URL:** `https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls` · **Access:** BLOCKED · **Verified via archive snapshot 20261025234631** (16,896 B, "Daily Metal Stocks Report", Report Date 10/23/2026, Activity Date 10/22/2026): per depository (Asahi, Brink's, Delaware, HSBC, IDS, JP Morgan, Loomis, Malca-Amit, MTB) rows Registered / Pledged / Eligible / Total × PREV TOTAL, RECEIVED, WITHDRAWN, NET CHANGE, ADJUSTMENT, TOTAL TODAY; **registered 14,814,284 oz; pledged 1,746,271; eligible 8,468,689; combined 23,282,973 oz (≈724 t)**; day's flow −60,090 oz eligible. Silver registered 100,514,943 oz.
- **[B]** Registered = warrants, deliverable tomorrow; eligible = bar-standard metal not warranted; pledged = warrants lodged as collateral. **[P]** paper-to-registered coverage GC = 40.34 Moz ÷ 14.81 = 2.72× (1.73× vs combined); meaningful only for the front month after first notice; the internet's "100:1" counts all months and ignores eligible.
- **Evidence:** theory of storage ties inventories to the basis; no study shows COMEX stock changes predict gold (G-CME).
- **Verdict:** LINK-ONLY now; PUBLISH-CONTEXT (physical panel) if access is restored (O-2).

### C9 · COMEX delivery notices — Metals Issues & Stops (daily) and YTD by firm
- **URL:** `https://www.cmegroup.com/delivery_reports/MetalsIssuesAndStopsReport.pdf` and `MetalsIssuesAndStopsYTDReport.pdf` · **BLOCKED**; archive snapshots 20261025161618 / 20261025223808: Oct-26 GC intent date 10/23: issued Dorman 1, JP Morgan (C) 6, StoneX (C) 3, Advantage (C) 14; stopped Goldman (H) 4, Wells Fargo (H) 13, CME 7; total 24; **MTD 13,479 contracts (≈41.9 t)**. The bulletin's "3,208 settled to-date" vs "13,479 MTD" is an open definitional question.
- **Verdict:** LINK-ONLY now; PUBLISH-CONTEXT (delivery-month panel) if access is restored.

### C10 · COMEX options data (OI by strike, settlements, QuikStrike, CVOL, Section 63)
- **BLOCKED / UNVERIFIED** (G-CME). The FTP gives only totals (C1: put/call OI 0.41 on 22 Oct).
- **Verdict:** LINK-ONLY (QuikStrike/CVOL in a browser); the put/call OI ratio is published from C1 as CONTEXT.

### C11 · CME website JSON (CmeWS: Settlements, Volume/Details, ProductCalendar, Quotes; FedWatch internal quotes)
- **URL:** `https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/437/FUT` etc. · **403** on all (G-CME ×5, G-MACRO).
- **Verdict:** DO-NOT-PUBLISH — scraping is forbidden by the Data Terms; everything it carries is on the FTP, the bulletin or Yahoo.

### C12 · CME FedWatch tool page
- **URL:** `https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html` · **403** (G-MACRO, G-APP, G-EDU).
- **Verdict:** LINK-ONLY — replaced as data by G16 (Atlanta Fed) + G17 (ZQ futures); keep the link in CONTRACTS/MACRO "linked".

### C13 · CME website pages (contract specs, `gold.volume.html`, `gold.settlements.html`, the free COT tool)
- **403** (G-CME, G-EDU, G-KITCO; the COT tool page timed out at 60 s for G-KITCO).
- **Verdict:** LINK-ONLY — specs come from C4; the owner should open `https://www.cmegroup.com/markets/metals/precious/gold.volume.html` in a normal browser to test whether the block is IP-wide (O-2).

---

## D. Other exchanges (Shanghai, Tokyo, Dubai, Istanbul)

### D1 · SHFE daily futures data JSON (`kxYYYYMMDD.dat`)
- **URL:** `https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261023.dat` (the old `/data/dailydata/kx/` path is 404; a Referer header helps; non-trading days return a 404 HTML page)
- **Verified (G-CME, G-PHYSICAL):** 200 · 2.3 s · 122,744 B; `o_curinstrument[]` with `PRODUCTID, DELIVERYMONTH, PRESETTLEMENTPRICE, OPENPRICE, …, SETTLEMENTPRICE, VOLUME, OPENINTEREST, OPENINTERESTCHG, TURNOVER`; filter `PRODUCTID=="au_f"`; **au2612 settle 869.20 CNY/g, OI 198,578 (−9,623)**; total `au` OI 368,618 (1 kg per lot).
- **[B]** China's futures market (night session 21:00–02:30 Beijing = 18:30–00:00 IST). **[P]** SHFE–COMEX gap after CNY and 31.1035 g/oz is a second premium read; redistribution not stated.
- **Verdict:** PUBLISH-CONTEXT — one line (SHFE front OI Δ) in POSITIONING › Asia. · **Catalog:** `gold_asia_daily` · job `gold_asia_close`

### D2 · SHFE gold warehouse stocks
- **URL:** `https://www.shfe.com.cn/eng/reports/StatisticalData/DailyData/?query_params=dailystock` · **UNVERIFIED** (page exists; the `.dat` path was not found in 4 guesses, G-PHYSICAL).
- **Verdict:** LINK-ONLY — owner action O-11 (one browser network-tab capture).

### D3 · SGE daily market data table (international/main board)
- **URL:** `https://en.sge.com.cn/data/data_daily_international_new?start_date=2026-10-20&end_date=2026-10-23` (HTML table)
- **Verified (G-PHYSICAL, G-KITCO):** 200 · 373 ms · 90 KB; columns `SerialNumber, Date, Contract, Open, Highest, Lowest, Close, Up/Down, WeightedAveragePrice, Volume(Kg), Amount(yuan), OpenInterest(Lot), Direction, DeliveryVolume(Lot)`; **23 Oct Au99.99 close 864.00 (−1.85 %), VWAP 863.44, volume 13,963.7 kg; Au(T+D) close 863.38, volume 56,720 kg, OI 260,054, direction "Long to Short", delivery 24,570 lots**. Parse with `bs4` (`lxml` is not installed). The EN "Delayed Quotes" page renders zeros without JS — the app's manual-check link is useless.
- **[B]** Shanghai's physical spot (Au99.99) and its deferred contract Au(T+D). **[P]** Direction = who pays the deferred fee: "Short to Long" = shorts pay = physical tightness; OI 260k lots of 1 kg.
- **Evidence:** none in-house (history starts now; GS-P3 proposed).
- **Verdict:** PUBLISH-CORE — the Shanghai premium's daily price and the Au(T+D) OI/direction tile. · **Catalog:** `gold_asia_daily` · job `gold_asia_close` (16:10 IST)

### D4 · SGE delayed intraday quotes JSON (`graph/quotations`)
- **URL:** `https://www.sge.com.cn/graph/quotations` · **Verified (G-CME):** 200 · 1.7 s; `{times[782], data[782], heyue "Au99.99", delaystr "2026年10月26日 02:29:55"}`.
- **Verdict:** PUBLISH-CONTEXT — an intraday Shanghai line on the DAILY chart's session band (one fetch per 5 min during SGE hours, view-only). · **Catalog:** `gold_bars_intraday` symbol `SGE_AU9999`

### D5 · SGE monthly Data Highlights PDF (volumes, delivery, **withdrawals**)
- **URL:** `https://en.sge.com.cn/data_MonthlyReport` (list; filenames became UUIDs from Jul-26) · **Verified (G-PHYSICAL):** Sep-26 PDF 5 pages (`pypdf`): gold delivery 613,288.68 kg (ratio 51.03 %), **withdrawal 92,083.24 kg, YTD 832,399.98 kg**; Au99.99 Sep 157,073.5 kg (+24.5 % m/m, −43.1 % y/y).
- **[B]** Withdrawals from SGE vaults are the best proxy for Chinese wholesale demand. **[P]** monthly, ~day 10–12; the CN weekly report links are JS-generated (not verified).
- **Verdict:** PUBLISH-CONTEXT — monthly bar on PHYSICAL › China. · **Catalog:** `SGE_WITHDRAWALS_KG` · `gold_series` · job `gold_monthly`

### D6 · SGE gold lease reference rates (`/sjzx/hjzjckll`, CN menu)
- **UNVERIFIED** (listed in the Chinese menu by G-CME; not fetched). · **Verdict:** LINK-ONLY — candidate (the lease rate is what replaced GOFO for China).

### D7 · JPX / OSE daily derivatives open interest workbook (Tokyo gold)
- **URL:** `https://www.jpx.co.jp/english/markets/derivatives/trading-volume/index.html` → `…/vk0khi000002j00k-att/20261023open_interest_e.xlsx` · **Verified (G-CME):** 200 · 131 KB; Gold (Standard) Oct-26 OI 693, Gold Rolling-Spot 8,949 — tiny next to COMEX/SHFE.
- **Verdict:** LINK-ONLY.

### D8 · DGCX (Dubai) daily market report
- **URL:** `https://www.dgcx.ae/market-data/daily-market-report` · **403 Cloudflare challenge** (G-CME) → UNVERIFIED. · **Verdict:** LINK-ONLY.

### D9 · Borsa Istanbul precious-metals market data
- **URL:** `https://www.borsaistanbul.com/en` (root 200; market-data pages: server disconnected ×2, G-CME) → UNVERIFIED. · **Verdict:** LINK-ONLY.

### D10 · BSE / NSE commodity-segment bhavcopy
- **URL:** `https://www.bseindia.com/markets/commodity/CommodityBhavcopy.aspx` (200; BSE's own illiquid contracts); NSE commodity paths 404 (G-INDIA).
- **Verdict:** DO-NOT-PUBLISH — not an MCX mirror.

---

## E. Physical supply and demand, investment flows, official sector, OTC

### E1 · SPDR Gold Shares (GLD) historical archive (XLSX)
*How much gold the biggest ETF holds, every day since 2004 — Western investors' "paper gold" demand.*
- **URL:** `https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en` (the documented CSV `https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv` 301-redirects to a bar-list **PDF**)
- **Verified:** G-KITCO 200 · 468 ms · 542 KB, sheet "US GLD Historical Archive" **5,721 rows 18 Nov 2004 → 22 Oct 2026**; columns `Date, Closing Price, Ounces of Gold per Share, NAV/Share 10:30, Indicative Price 4:15, Mid bid/ask, Premium/Discount, Daily Share Volume, Total Ounces, Tonnes of Gold, Total NAV`; **22 Oct tonnes 1,045.64 (−11.98 t d/d)**, 21 Oct 1,057.62; holiday rows carry "US Holiday"; all-time high 1,353.35 t (7 Dec 2012). Same by G-PHYSICAL, G-MACRO, G-STUDY.
- **Frequency / lag:** daily; row for T appears T+1 ≈06:00 IST (site: holdings updated 10:30–10:45 and 16:00–16:45 NY).
- **Terms:** Disclaimer sheet: "Reproduction or redistribution of any of this information is expressly prohibited without prior written consent" (O-1).
- **[B]** When investors buy GLD shares the trust buys bars; tonnes up = investment demand. **[P]** ≈0.0917 oz/share, falling daily by the expense ratio; price vs NAV = premium/discount.
- **Evidence:** G-STUDY: 4-week change forecasts nothing (t ≤ 1.0); same-week R² 16 %; G-MACRO: weekly corr 0.33–0.37 contemporaneous, ≈0 predictive. GS-P1 (daily tonnes → 5/20-day returns) is runnable today.
- **In app today:** a manual-check link. **Consolidation:** HEALTH tile + PHYSICAL line; the link goes.
- **Verdict:** PUBLISH-CORE (disagreement 8), display-only, attributed, badge `context`. · **Catalog:** `GLD_TONNES` · `gold_etf_holdings` · job `gold_morning` (06:40)

### E2 · SPDR old archive CSV URL
- **Verified:** 200 → 302 → a 697 KB PDF (G-KITCO, G-EDU, G-STUDY). · **Verdict:** DO-NOT-PUBLISH — dead path; use E1.

### E3 · iShares Gold Trust (IAU) product page
- **URL:** `https://www.ishares.com/us/products/239561/ishares-gold-trust-fund` · **Verified:** page 200 · 1.2–1.8 s · 1.6 MB; **"Tonnes in Trust 463.05 as of Oct 23, 2026"**, 14,887,293 oz, net assets $59.74 bn (G-KITCO, G-PHYSICAL); the documented `.ajax?fileType=csv` endpoint returns the HTML page (stale id; G-PHYSICAL, G-MACRO) → UNVERIFIED as a feed.
- **Verdict:** PUBLISH-CONTEXT — regex the page once a day for tonnes (second ETF line); fallback the WGC fund table (E5). · **Catalog:** `IAU_TONNES` · `gold_etf_holdings`

### E4 · Sprott Physical Gold Trust (PHYS)
- **URL:** `https://sprott.com/investment-strategies/physical-bullion-trusts/gold/` · **403 Cloudflare** (G-PHYSICAL). · **Verdict:** LINK-ONLY.

### E5 · World Gold Council Goldhub — gold-ETF holdings and flows (open chart JSON)
- **URL:** `https://fsapi.gold.org/api/v11/charts/etfv2/revised/archive-tablegroup/all` (+ `holdings-chart2`, `flows-chart2` on the same path family) · page `https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows`
- **Access:** FREE JSON (no login); the monthly XLSX (`/download/file/21216/ETF_Flows_2026-10-02_1401.xlsx`) is 403 without a free Goldhub login · **Verified (G-PHYSICAL):** weekly from 2003-02-28; **week 42 ending 16 Oct 2026: global +13.69 t (+$1.90 bn), holdings 4,278.9 t, AUM $578.7 bn; NA 2,123.2 t, Europe 1,529.3, Asia 549.9**; Sep-26 monthly +67.9 t (Asia +16.9, India +3.1 t, China +11.9); country table (US 2,048.9, UK 689.2, CH 382.6, DE 337.6, CN 310.9, **IN 124.4**); top inflow fund SPDR +6.19 t. Columns contain `<br/>`; values are strings; some fund rows have None.
- **Frequency / lag:** weekly (Monday ≈11:30 IST for the week ended Friday) and monthly.
- **Terms:** WGC T&Cs: personal/non-commercial, no scraping/redistribution/framing without written authorisation and accreditation (O-1).
- **[B]** Which region is buying or selling gold through funds, every week. **[P]** WGC revises; the weekly series is the only free regional split; India tonnes appear here.
- **Evidence:** G-PHYSICAL: no verified OOS timing value (WGC's own model treats flows as contemporaneous); GS-P2 proposed (weekly flows 2003→).
- **Verdict:** PUBLISH-CORE (regional flows + India tonnes), attributed, gated on O-1. · **Catalog:** `WGC_ETF_FLOW_T_GLOBAL`, `WGC_ETF_FLOW_T_{NA,EU,ASIA,OTHER}`, `WGC_ETF_HOLD_T_IN` · `gold_series` (freq W) · job `gold_weekly` (Mon 12:00 IST)

### E6 · WGC Goldhub ETF page and monthly XLSX (registration)
- **Verified:** page 200 (G-KITCO, G-EDU, G-MACRO); XLSX behind a T&C modal / login. · **Verdict:** LINK-ONLY (optional registration, O-7).

### E7 · WGC Goldhub — supply and demand statistics (quarterly balance sheet)
- **URL:** `https://fsapi.gold.org/api/v11/charts/supply-and-demand/43` · **Verified (G-PHYSICAL):** 66 quarters Q1'10 → Q2'26 and annual 2010–2025; 3 supply + 15 demand series incl. the LBMA quarterly average price (Q2-26 $4,506.3). Q2-26: mine 965.6 t, recycled 326.1, hedging −22.8; jewellery fabrication 310.3, technology 80.4, bar & coin 307.1, ETFs −44.8, central banks 288.9 → "OTC and other" ≈ 327 t. FY2025: mine 3,822.9, recycled 1,403.8, jewellery 1,647.7, bar & coin 1,405.9, ETFs +803.3, central banks 848.2.
- **[B]** ~216,000 t exist above ground; mines add < 2 % a year, so price is set by who wants to hold the stock — the marginal buyer. **[P]** supply ≡ demand by construction; "OTC and other" is a balancing item, not measured OTC flow; revised every quarter (never backtest on the latest vintage).
- **Verdict:** PUBLISH-CONTEXT — the balance-sheet panel (quarterly stacked bars). · **Catalog:** `WGC_SD_*` · `gold_series` (freq Q) · job `gold_monthly`

### E8 · WGC Goldhub — local gold price premiums (India, China; weekly)
- **URL:** `https://fsapi.gold.org/api/v11/charts/local-gold-price-premiums` · **Verified (G-PHYSICAL):** weekly, 255 points; **16 Oct 2026 India +$11.44/oz, China +$7.76/oz**; monthly Sep-26 China +24.59, India −3.76 (Aug-26 India −113.6, the duty-change month).
- **Verdict:** PUBLISH-CONTEXT — the reference line next to our daily premiums (F10, D3). · **Catalog:** `WGC_PREMIUM_IN`, `WGC_PREMIUM_CN` · `gold_series` (W)

### E9 · WGC Goldhub — central-bank gold reserves page
- **URL:** `https://www.gold.org/goldhub/data/gold-reserves-by-country` · **Verified:** page 200 (updated 6 Oct 2026; IMF-based); XLSX needs registration. · **Verdict:** LINK-ONLY — E12 (IMF API) is the open source of the same numbers.

### E10 · WGC Gold Demand Trends (quarterly) and India focus
- **URL:** `https://www.gold.org/goldhub/research/gold-demand-trends` · India Q2-26 page seen only in search listings (G-INDIA) → UNVERIFIED. · **Verdict:** LINK-ONLY (Q3-26 due early Nov 2026).

### E11 · WGC Goldhub — gold prices page, GRAM
- **URL:** `https://www.gold.org/goldhub/data/gold-prices` (200; XLSX "averages since 1978" behind T&C) · GRAM page **404** (G-MACRO). · **Verdict:** LINK-ONLY.

### E12 · IMF IRFCL — official monetary gold by country (SDMX API)
*Which central banks bought gold last month, in ounces.*
- **URL:** `https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/IND+CHN+RUS+TUR+POL+USA.IRFCLDT1_IRFCL56V_FTO+IRFCLDT1_IRFCL56_USD+IRFCLDT1_IRFCL57_USD+IRFCLDT1_IRFCL40_USD..M?startPeriod=2025-06&format=csv` (header `Accept: text/csv`)
- **Access:** FREE, PUBLIC_OPEN licence with citation (the `data.imf.org` portal is 403 but the API works) · **Verified (G-PHYSICAL):** 200 · 1.3 s · 334 rows; dataset updated 25 Oct 2026 06:09 UTC. **China 76.73 Moz Aug-26 (2,386.6 t; +0.65 Moz in Aug, +0.64 in Jul ≈ +20 t/month); India 28.3093 Moz = 880.5 t flat Jun–Aug; Russia 72.80 Moz Sep (−0.20); Turkey 25.443 Moz Aug (+0.61); Poland 21.634 Moz Sep (+0.80); USA 261.499 Moz.** Trap: stale months repeat the last value — check `TIME_PERIOD`.
- **[B]** Central banks have bought ~1,000 t/yr for three years — the structural bid. **[P]** quantity in ounces (RBI's weekly value uses its own valuation convention); 1–2 month lag; China reports late and may under-report.
- **Evidence:** G-MACRO/G-PHYSICAL: regime context; GS-P5 (monthly CB buying → next-month return) proposed, not yet pre-registered (`reports/gold_program/STUDIES.md`); honest prior FAIL as timing.
- **Verdict:** PUBLISH-CORE — "official sector" panel (top holders, last-month buyers, each with its data month). · **Catalog:** `IMF_GOLD_OZ_{ISO3}`, `IMF_GOLD_USD_{ISO3}` · `gold_series` (M) · job `gold_monthly` (26th)

### E13 · SAFE China official reserve assets page
- **URL:** `https://www.safe.gov.cn/en/OfficialReserveAssets/index.html` · 200 but no table in the HTML (G-PHYSICAL). · **Verdict:** LINK-ONLY (PBoC's ~7th-of-month print; E12 carries it a month later).

### E14 · LBMA Trade Data (formerly LBMA-i) — London OTC turnover
- **URL:** `https://www.lbma.org.uk/prices-and-data/lbma-daily-trade-reporting-data` (G-PHYSICAL) / `https://www.lbma.org.uk/prices-and-data/lbma-trade-data` (G-EDU, 200 · 1.6 s)
- **Verified:** page text carries the headline only: **"Trade Reporting Weekly Turnover … 12 week moving average … period ending 16 October 2026. Gold: $964.17 bn, Silver $129.69 bn, Pt $16.10 bn, Pd $7.21 bn"**; daily T+1 and weekly product-level data are a Nasdaq/Bloomberg/LSEG subscription.
- **[B]** The London OTC market is where most gold trades: $964 bn a week ≈ 7,500 t gross ≈ a year's mine supply every 2–3 days. **[P]** open-volume reports are not netted between reporters; gross, not positions; "OTC deals" with names never exist publicly.
- **Verdict:** PUBLISH-CONTEXT — regex the page weekly; the "OTC window" tile. · **Catalog:** `LBMA_OTC_TURNOVER_USD_BN` · `gold_series` (W) · job `gold_weekly`

### E15 · LBMA London Vault Holdings data (monthly XLSX)
- **URL:** `https://cdn.lbma.org.uk/downloads/LBMA-London-Vault-Holdings-Data-September-2026.xlsx` (filename changes monthly — resolve the href from `https://www.lbma.org.uk/prices-and-data/london-vault-holdings-data`)
- **Verified:** G-PHYSICAL 2016-07 → 2026-09 in thousand oz; **Sep-26: 9,821 t gold (+189 t m/m), silver 28,985 t**; G-EDU page 200 ("+1.96 % m/m, $1.3 trillion, ≈785,690 bars"). Mixed string/datetime dates (`pd.to_datetime(format="mixed")`).
- **Verdict:** PUBLISH-CONTEXT — monthly London vault line on the balance-sheet panel. · **Catalog:** `LBMA_VAULT_GOLD_T` · `gold_series` (M) · job `gold_monthly`

### E16 · LBMA Good Delivery (about / current gold list)
- **URL:** `https://www.lbma.org.uk/good-delivery/about-good-delivery` (200, G-EDU) · `https://www.lbma.org.uk/good-delivery/gold-current-list` (G-PHYSICAL: 67 refiners). · **Verdict:** LINK-ONLY (LEARN).

### E17 · Perth Mint monthly sales updates
- **URL:** `https://www.perthmint.com/news/` · **Verified (G-PHYSICAL):** posts ("sold 23,932 troy ounces (oz) of gold … August 2026"; July 30,871 oz).
- **Verdict:** LINK-ONLY (downgraded from G-PHYSICAL's CONTEXT): one narrative number a month, regex-fragile, no study; candidate for later.

### E18 · US Mint bullion sales
- **URL:** `https://www.usmint.gov/about/production-sales-figures/bullion-sales` · **403 Cloudflare** (G-PHYSICAL). · **Verdict:** LINK-ONLY.

### E19 · Swiss customs gold trade — BAZG open data (`TN8_EXP_en.zip`) and SwissImpex dashboard
- **URL:** `https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_EXP_en/TN8_EXP_en.zip` (CKAN package `e6bcc098-2c55-4305-a5ed-35c7bf7cde55`) · dashboard `https://www.swissimpex.admin.ch/` (JS, no API; the old `gate.ezv.admin.ch/swissimpex/` is 404)
- **Verified (G-INDIA):** HEAD 200, **692,443,287 bytes**, `Last-Modified 20 Oct 2026` (September data); monthly since 1988; filter tariff 7108.1200 × India (granularity and unit to confirm on the first run, PLAN §j). Terms: open use with attribution.
- **First run (6 Nov 2026):** one member `TN8_EXP_en.csv`, comma-delimited, 25 columns (`year`, `month`, `Tariffnumber8` '7108.1200', `Country_isoAlpha2` / `Country_txt` 'India', `Supplementary_quantity`, `Quantity_kg`, `Value_CHF/EUR/USD`, `status` def/prov). Monthly, unit kg. The first live run stored 0 rows (the parser matched the ISO-code column and the unit count); fixed and re-run: 177 months, Jan 2012 (67.4 t) → Sep 2026 (3.1 t). Range-request the zip head to audit the header without the 692 MB download.
- **[B]** Switzerland refines most of the bars India imports, so Swiss customs is the fastest hard count of physical flow, in tonnes. 
- **Verdict:** PUBLISH-CONTEXT — one row a month (stream the zip, filter, delete). · **Catalog:** `SWISS_GOLD_EXPORT_IN_KG` · `gold_series` (M) · job `gold_monthly` (22nd)

### E20 · Hong Kong C&SD merchandise trade (gold with mainland China)
- **URL:** `https://www.censtatd.gov.hk/en/scode230.html` (API `api/get.php?id=<table>&lang=en&param=<base64>` live; gold table id unresolved, G-PHYSICAL). · **Verdict:** LINK-ONLY (O-11).

### E21 · Dubai (DMCC / Dubai Customs)
- **URL:** `https://dmcc.ae/ecosystems/gold` · narrative only ("15 % of global gold trade"), no series (G-PHYSICAL). · **Verdict:** DO-NOT-PUBLISH.

### E22 · Reuters "Asia Gold" weekly premium/discount commentary (via mining.com)
- **URL:** `https://www.mining.com/web/asia-gold-india-swings-premium-benchmark-price-dip-lends-appeal-elsewhere/` · **Verified (G-INDIA):** discount up to $14/oz (early Oct) → premium up to $3/oz (late Oct 2026).
- **Verdict:** LINK-ONLY — the sanity check for our derived India premium.

---

## F. India: MCX, ICICI, IBJA, RBI, duty, imports, ETFs

### F1 · ICICI Direct public security master (`SecurityMaster.zip` → `MCXScripMaster.txt`)
*Every MCX gold contract ICICI can trade, with yesterday's settlement (as the band midpoint) and open interest — the free daily MCX positioning number.*
- **URL:** `https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip` · **Access:** FREE, no login (the app already downloads it) · **Verified:** HEAD 200, 2,998,716 B, `Last-Modified: Fri, 23 Oct 2026 01:58:26 GMT` (= 07:28 IST; S3), by G-INDIA, G-APP, G-EDU, G-KITCO. Cached copy 26,722 rows. Gold families (`CompanyName` / `ShortName` = Breeze `stock_code`): **GOLD** (`GOLD`, 1 kg, Dec-26 OI 16,650, settle 1,46,079, band 1,41,697–1,50,461), **GOLDM** (`GOLDMI`, 100 g, Nov-26 OI 48,437), **GOLDTEN** (`GOLDTE`, 10 g, 999, month-end expiry, Oct-26 OI 25,655 — **missing from `shared/mcx_specs.py` and `routers/mcx.py`**), **GOLDGUINEA** (`GOLDGU`, 8 g, OI 12,009), **GOLDPETAL** (`GOLDPE`, 1 g, OI 155,778); options on GOLD and GOLDM futures (`Series=OPTION`, tick 50 paise, strikes ₹1,16,500 → ₹2,73,000 step ₹500; the 30-Oct and 27-Nov options settle into the Dec-26 future).
- **Traps (G-INDIA, G-APP):** OI sits in the shifted `MarginPercentage` column; band half-width is exactly 3.0 % → settlement = midpoint; `TickSize` in paise; the file on Monday morning is Friday's (carrying Thursday's settlement) — label settlements by **session**, never by file date; the loader re-downloads 3 MB every 5–10 min all weekend (6.9 s cold `/api/mcx/specs`) — use a conditional GET.
- **Frequency / lag / history:** daily ≈07:00–07:30 IST on trading days; **no history anywhere** — it starts the day the snapshot job runs.
- **[B]** The MCX settlement and the open positions per contract, free, every morning. **[P]** a proxy settlement (midpoint), no volume; official bhavcopy (F3) is blocked.
- **Verdict:** PUBLISH-CORE — the contract selector, the MCX OI ladder and the daily OI history. · **Catalog:** `gold_curve` rows exchange `MCX`, source `icici_master_band`, quality `proxy` · job `gold_mcx_master` (07:35, retry 08:35)

### F2 · ICICI Breeze API (MCX quotes, 1-minute bars, daily bars with open interest)
- **URL:** `https://api.icicidirect.com/breezeapi/documents/index.html` · **Access:** FREE-REGISTRATION (the owner's account; credential) · **Verified:** not exercised today by rule. Known: `get_quotes` on MCX futures returned HTTP 500 on 12 Oct 2026; 1-minute bars (`get_historical_data_v2`) worked; daily bars with `open_interest` and the `GOLDTE` code are UNVERIFIED (O-8); project memory says Breeze OI is wrong for old contracts.
- **[P]** the only live MCX price; REST calls must stay off the request path (one background call/minute at most, G-APP finding 4).
- **Verdict:** PUBLISH-CORE when live (honest degrade otherwise). · **Catalog:** daily bars → `gold_mcx_daily` (source `breeze_daily`, quality `broker`; job `gold_breeze_daily` 09:35 Mon–Fri, live expiries only; authorised O-8 on 6 Nov 2026; never `gold_curve`, whose readers do not filter by source) · existing quote path

### F3 · MCX daily bhavcopy (`GetDateWiseBhavCopy`) and market-data pages
- **URL:** `https://www.mcxindia.com/backpage.aspx/GetDateWiseBhavCopy` (POST `{"Date":"YYYYMMDD","InstrumentName":"FUTCOM"}`; endpoint catalogue recovered from the PyPI sources of `mcxlib 0.4` / `mcxpy 0.0.3`) · page `https://www.mcxindia.com/market-data/bhavcopy`
- **Verified:** **403 Akamai "Access Denied"** to every scripted client even from an Indian IP (httpx, curl, the wrapper's exact header set, the fetch proxy) — bot-management fingerprinting, not geo-blocking (G-INDIA; also G-APP, G-EDU, G-KITCO, G-STUDY).
- **Verdict:** LINK-ONLY today; PUBLISH-CORE (official settlement, **volume**, OI) once a browser-session collector exists (owner decision O-8). F1 stands in meanwhile.

### F4 · MCX participant / category-wise open interest (monthly workbook)
- **URL:** `https://www.mcxindia.com/docs/default-source/market-data/historicaldata/2026/september/category-wise-oi-sep-2026.xlsx` (columns per `mcxlib`: `Date, Commodity, Instrument, Open Interest, FPOs/Farmers, VCPs/Hedgers, Proprietary traders, Domestic Financial Institutional Investors, Foreign Participants, Others` × Long/Short)
- **Verified:** 403 (G-INDIA). Whether rows are daily or month-end is UNVERIFIED. **There is no daily participant-wise MCX report**; "who is long/short on MCX" is knowable only monthly, in arrears.
- **Verdict:** LINK-ONLY today; PUBLISH-CONTEXT (monthly "who holds MCX gold") once collected.

### F5 · MCX spot price polling (Ahmedabad 995, duty-paid) and the Due Date Rate
- **URL:** `https://www.mcxindia.com/market-data/spot-market-price` · 403 (G-INDIA). · **Verdict:** LINK-ONLY — IBJA (F10) is the practical spot; DDR wording UNVERIFIED (LEARN explains the mechanism).

### F6 · MCX circulars (expiry, margins, Muhurat) and broker/compliance republications
- **URL:** `https://www.mcxindia.com/circulars/all-circulars` (403; the app's existing link) · `https://teamleaseregtech.com/updates/article/60567/mcx-muhurat-trading-session-on-diwali-2026/` (200 via fetch proxy, G-INDIA): **circular MCX/TRD/590/2026 (19 Oct 2026): Sun 8 Nov 2026, special session 14:05–14:19, trading 14:20–15:30** — the app's "evening timings by circular" note is wrong.
- **Verdict:** LINK-ONLY — hand-maintained constants in `shared/mcx_specs.py` (fix the Muhurat row).

### F7 · MCX option chain, `mcxccl.com` SPAN files
- **403** (G-INDIA). · **Verdict:** LINK-ONLY (margins from F8).

### F8 · Zerodha commodity margin calculator (free mirror of exchange NRML margins)
- **URL:** `https://zerodha.com/margin-calculator/Commodity/` · **Verified (G-INDIA):** 200 · 0.24 s · "updated: 25 Oct 2026"; **9.25 % of notional on every gold contract** (GOLD Dec-26 ₹13,25,636/lot; GOLDM Nov ₹1,31,165; GOLDTEN Nov ₹13,291; GUINEA ₹10,686; PETAL ₹1,335) vs the app's 6 % "indicative" constant.
- **[P]** exchange NRML (SPAN + exposure); ICICI's plan-dependent margin may differ — label "exchange NRML (Zerodha mirror)".
- **Verdict:** PUBLISH-CONTEXT — one margin number per contract, daily; replaces the constant in the ticket. · **Catalog:** `gold_margins` source `zerodha_nrml` · job `gold_mcx_master`

### F9 · Customs duty on gold — Notification 16/2026-Customs (12 May 2026, effective 13 May 2026)
- **URL:** `https://www.cbic.gov.in/` (primary: incomplete TLS chain, Python refuses; `curl -k` 200) · facts from taxguru / a2ztaxcorp / thetaxcorp / LiveLaw / ICRA (secondary, all agreeing) · **Verified (G-INDIA):** **BCD 10 % + AIDC 5 % = 15 %** (was 6 % since Jul 2024; Budget Feb 2026 unchanged); SWS nil; IGST 3 % creditable → all-in 18.45 %. MCX June gold rose 6–7 % on 13 May 2026. Headlines of 16 Oct 2026 corroborate (G-PHYSICAL).
- **[B]** Indian gold = world gold + 15 % at the border; a duty change jumps the MCX price (6 → 15 % = +8.5 %). **[P]** the rate is a dated input (`effective_date`, notification number); Budget 1 Feb is a jump event.
- **Verdict:** PUBLISH-CORE — one dated constant (`GOLD_IMPORT_DUTY_PCT` in `shared/config.py`, history row in `gold_series` `GOLD_IMPORT_DUTY_PCT`); owner confirms the primary (O-3).

### F10 · IBJA daily AM/PM gold and silver rates (India's reference price, ₹/10 g by purity)
- **URL:** `https://ibjarates.com/` (and `https://ibja.co/`) · **Access:** FREE page; the official API (`indiagoldratesapi.com`) is paid; `/terms` 404 → terms UNVERIFIED · **Verified (G-INDIA, G-KITCO, G-PHYSICAL):** 200 · 0.5–0.9 s · 156 KB; tables 2 (AM) and 3 (PM) with ~30 days: **23 Oct 2026 AM 999 1,41,448 / 995 1,40,882; PM 999 1,41,630 / 995 1,41,063; 916 1,29,733; silver 999 ₹1,94,415/kg**; no fix on 20 Oct (Dussehra); before upload the cell reads "Rates will be uploaded soon" (05:45 IST Monday). RBI's SGB redemption press release (2026-2027/1060) confirms the 999 PM fix is the government's reference.
- **Frequency / lag / history:** AM ≈12:00–13:00, PM ≈17:00–18:30 IST (minute not verifiable); ~30 days on the page — store daily, never backfill from the chart.
- **[B]** What a kilo of gold costs in India today, without GST. **[P]** "without 3 % GST and making charges"; 999 vs 995 (MCX is 995); compare like with like.
- **Verdict:** PUBLISH-CORE — the India spot line and the base of the India premium. · **Catalog:** `IBJA_{999,995,916,750,585}_{AM,PM}`, `IBJA_SILVER_999_PM` · `gold_series` · jobs `gold_india_midday` (13:45), `gold_india_pm` (18:10)

### F11 · RBI Weekly Statistical Supplement — foreign-exchange reserves (gold line)
- **URL:** `https://www.rbi.org.in/Scripts/BS_viewWssExtract.aspx?SelectedDate=10/23/2026` (old site, plain GET, G-INDIA 200 · 1.22 s) · press-release form `https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63855` (G-PHYSICAL 200) · RSS `wss_rss.xml` · the new `website.rbi.org.in` WSS path is a JS shell / 301 to home
- **Verified:** as on 16 Oct 2026: **gold ₹10,04,583 cr / US$105,800 mn (+706 mn w/w; −9,595 mn since end-Mar 2026) of US$721,016 mn total → 14.7 %**. Tonnes only half-yearly (880.52 t at 31 Mar 2026, RBI Annual Report via secondary).
- **[P]** RBI's valuation convention (US$105.8 bn ÷ 28.31 Moz ≈ $3,737/oz < spot) — use IMF ounces (E12) for quantity; weekly value changes are almost all price.
- **Verdict:** PUBLISH-CONTEXT — one weekly row (value, share, implied tonnes). · **Catalog:** `RBI_GOLD_RESERVES_USD_MN`, `RBI_RESERVES_TOTAL_USD_MN` · `gold_series` (W) · job `gold_weekly` (Fri 18:00, retry Sat)

### F12 · Sovereign Gold Bond premature-redemption press releases
- **URL:** `https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63538` · **Verified (G-INDIA):** PR 2026-2027/1060: ₹15,384/unit = 3-day average of IBJA 999 PM; no new tranche since Feb 2024.
- **Verdict:** LINK-ONLY (downgraded from CONTEXT): a formula for LEARN, nothing to trade.

### F13 · RBI / FBIL USD-INR reference rate
- **URL:** `https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx` (ASP.NET form: GET for viewstate, POST `txtFromDate`/`txtToDate` dd/mm/yyyy, `chkUSD=on`) · FBIL `https://www.fbil.org.in/wasdm/refrates/fetch?forDate=…` → **HTTP 500** for every date format tried (UNVERIFIED)
- **Verified (G-INDIA):** 200 · 0.32 s; **23 Oct 94.9432**, 22 Oct 94.6986, 21 Oct 94.7145 (Yahoo close 94.7113 on 23 Oct — 0.25 % apart, not interchangeable at the ₹300 level).
- **Verdict:** PUBLISH-CONTEXT — the timestamped rupee for the landed-cost/premium series only (live rupee stays `INR=X`). · **Catalog:** `USDINR_FBIL` · `gold_series` · job `gold_india_midday` (13:45)

### F14 · India monthly gold imports — Ministry of Commerce / DGCI&S via the PIB release
- **URL:** `https://pib.gov.in/allRel.aspx` (listing 200 · 0.70 s; the September-2026 release page itself was not located — content via PTI/Business Today/ThePrint and a PDF copy at worldtradescanner.com) → URL pattern UNVERIFIED
- **Verified (G-INDIA):** **September 2026 gold imports US$1.80 bn (−81.27 % YoY); Apr–Sep US$19.27 bn (−27.3 %)**; silver US$665 mn.
- **Entered 6 Nov 2026** (group `india_imports`, `params.values`; source string names the releases): Aug 2025 5.439 · Sep 2025 9.61 · Aug 2026 2.298 · Sep 2026 1.80 (US$ bn; Department of Commerce quick estimates of 15 Sep / 15 Oct 2026 via PTI, Business Today, ThePrint, Angel One). Cross-checks: 2,298 / 5,439 = −57.75 % and 1.80 / 9.61 = −81.3 % reproduce the published changes; Apr–Aug 17.47 + Sep 1.80 = Apr–Sep 19.27. Each month needs a new entry after the 15th until a machine-readable release URL is verified. **Entry (8 Nov 2026): `python scripts/gold_india_imports.py --month 2026-10 --usd-bn 1.80`** — one command, typo-guarded (refuses ₹ crore / US$ million mistakes and a month that has not ended), dates the row the month it covers, and records in the stored source that it was typed because no feed exists. Re-checked 8 Nov: `tradestat.commerce.gov.in` is a web form with no CSV / JSON download, no API and no documented terms for automated use, so the program does not scrape it. **Second route also closed (8 Nov 2026):** the RBI Bulletin DOES print the monthly figure in prose ("gold imports grew 4.8 % y-o-y to US$ 4.2 bn in July 2026"), and rbi.org.in is already an allowlisted host — but its statistical annex has no gold-import table (Table 32 Foreign Trade breaks out POL / non-POL only; Table 21 is gold PRICES, which IBJA already supplies), and `rbidocs.rbi.org.in` answers an automated download of a Bulletin XLSX with a **captcha page** rather than the file (probed: 47,938 bytes of HTML, not a zip). So both the trade portal and the central bank are closed to an honest automated job. **PIB is not (8 Nov 2026):** the government's press agency answers a plain client with HTTP 200 and no captcha, on both its RSS listing and its release pages, and the Commerce Ministry's monthly release states the figure in prose. The GATHERING is therefore automated — `python scripts/gold_india_imports_find.py` fetches the newest trade release, reads the figure, quotes the sentence it came from, and prints the ready `gold_india_imports.py` command — while the WRITING stays with the owner, because a number parsed out of prose can be a revision, a quarter, or silver in the same sentence, and a wrong point-in-time row is worse than a missing one. Read-only, at most 5 requests spaced 1.2 s, no crawl. **Correction (8 Nov 2026, from the real document):** the Commerce Ministry's monthly release carries NO standalone gold figure — gold appears only inside the aggregate "Non-petroleum, non-gems & jewellery (gold, silver & precious metals) imports in September 2026 were US$ 51.64 Billion". A naive parse returned 51.64 for a month whose real figure is 1.8 (28x wrong) and the month guard passed it, because that sentence does name the month. The parser now requires the sentence to be ABOUT gold imports and rejects any that mentions gold only to exclude it; it returns nothing on that release, which is the right answer. The $1.8 bn the agencies print comes from the commodity-wise annexure, not this release, so the watch job will usually report "a release is out, read it" rather than store — and the plausibility band in `gold_india_imports.py` (> US$25 bn refused) is the last line if a future layout slips past both filters.
- **[B]** The demand pulse after a duty change and the current-account driver of duty policy.
- **Verdict:** PUBLISH-CONTEXT — one monthly bar; ingest by regex on the ~16th or by hand; keep the PRID. · **Catalog:** `INDIA_GOLD_IMPORTS_USD_BN` · `gold_series` (M)

### F14b · UN Comtrade — India HS 7108 monthly (the machine-readable official filing) — **added 8 Nov 2026**
- **URL:** `https://comtradeapi.un.org/public/v1/preview/C/M/HS?reporterCode=699&period=YYYYMM&partnerCode=0&cmdCode=7108&flowCode=M` — **no key**, JSON, US$ and kg.
- **Why it matters:** the four other routes are closed — tradestat is a POST form (F15), RBI answers an automated XLSX download with a **captcha**, the Commerce Ministry's monthly release carries **no standalone gold figure** (gold appears only inside "Non-petroleum, non-gems & jewellery (gold, silver & precious metals) imports … US$ 51.64 Billion", which a naive parse stored as the gold figure — 28x wrong), and PIB's RSS reaches that same release.
- **Lag ≈ 2 months** (filed through 2026-07 on 8 Nov 2026), so it never replaces the press-release figure for the current month: it fills the months behind it and **verifies** what is already stored.
- **Traps, both handled:** one period per request (preview limit), and a **throttled call answers HTTP 200 with an EMPTY data list, not an error** — believed naively that silently holes the series, so an empty answer is always re-asked slowly before it is accepted (202509 came back empty at a 1.2 s cadence and returned its real 9.61 at 6 s).
- **Never overwrites:** a stored month beyond 10 % of the filing is reported (Telegram + exit 1), never applied.
- **First run (8 Nov 2026):** series 4 → **33 points** (2024-01 → 2026-09); the hand-typed 2025-08 (5.439), 2025-09 (9.61) and 2026-08 (2.298) each matched the filing, and 2026-07 (4.162) matches the RBI Bulletin's "US$ 4.2 billion in July 2026".
- **Code:** `scripts/gold_india_imports_comtrade.py` · job `india_imports_comtrade` (20th, 11:45 IST).
- **Verdict:** PUBLISH-CORE — official, keyless, point-in-time by filing month. · **Catalog:** `INDIA_GOLD_IMPORTS_USD_BN` · `gold_series` (M)

### F15 · DGCI&S tradestat portal (HS 7108)
- **URL:** `https://tradestat.commerce.gov.in/eidb/commodity_wise_import` (POST form with viewstate; "Last data updated on 07/08/2026"; `commerce.gov.in/press-releases/` 404; `ddp.dgcis.gov.in` fails DNS) · **Verdict:** LINK-ONLY (F14 gives the number).

### F16 · AMFI monthly mutual-fund report — Gold ETF row (`am{mon}{yyyy}repo.xls`)
- **URL:** `https://portal.amfiindia.com/spages/amsep2026repo.xls` · **Verified (G-INDIA):** 200 ×81 (Jan 2020 → Sep 2026), sheet `MCR_MonthlyReport`, row "Gold ETF": **Sep 2026: 26 schemes, 1,26,77,259 folios, net +₹4,450.6 cr, month-end AUM ₹1,88,934 cr ≈ 146 t**; files back to Apr 2018; `xlrd` in the env.
- **Evidence (G-INDIA-1, N = 79 months):** flows do not predict next-month rupee gold (Spearman +0.12, p 0.31; tercile spread +0.59 pp, p 0.65; halves disagree) but **chase last month's return (ρ +0.25, p 0.03)** → FAIL as timing, PASS as description.
- **Verdict:** PUBLISH-CONTEXT — "Indian paper gold" AUM in tonnes and months of positive flow. · **Catalog:** `AMFI_GOLD_ETF_NET_CR`, `AMFI_GOLD_ETF_AUM_CR` · `gold_series` (M) · job `gold_monthly` (11th, retry daily)

### F17 · AMFI `NAVAll.txt` (daily NAV incl. ~80 gold-ETF rows) and the monthly AUM portal
- **URL:** `https://www.amfiindia.com/spages/NAVAll.txt` (200, G-PHYSICAL) · `https://www.amfiindia.com/research-information` (SPA; old URLs 404) · **Verdict:** LINK-ONLY (downgraded): GOLDBEES price (A4) and F16 cover the need; candidate for an Indian-ETF premium/discount later.

### F18 · GST and BIS hallmarking facts
- **URL:** `https://www.bis.gov.in/` (200), `cbic-gst.gov.in` (200) · 3 % GST on gold, 5 % on making; 6-digit HUID mandatory since 1 Apr 2023 (G-INDIA). · **Verdict:** PUBLISH-CONTEXT — a static card in LEARN (not a feed).

### F19 · Indian demand calendar (Dhanteras, Diwali/Muhurat, Akshaya Tritiya, wedding seasons, monsoon, Budget)
- **Verified dates (G-INDIA, secondary):** Akshaya Tritiya Sun 19 Apr 2026; Dhanteras Fri 6 Nov 2026; Diwali/Muhurat Sun 8 Nov 2026 (timings F6); Budget 1 Feb. Evidence: no tradable seasonal in MCX after costs (Baur 2013 "autumn effect" small/unstable; G-MACRO H3, G-STUDY §4.4).
- **Verdict:** PUBLISH-CONTEXT — rows in `gold_events` (and ECO), never a signal.

---

## G. Macro drivers

### G1 · US Treasury daily real yield curve CSV (5/7/10/20/30 YR)
- **URL:** `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2026`
- **Verified:** G-MACRO 200 · 0.77 s; G-APP 200 · 1.53 s (memory said ~20 s), 204 rows, **last 10/23/2026 10 YR 2.66** — one US business day fresher than FRED; one file per calendar year; MM/DD/YYYY; columns differ from the nominal file.
- **Frequency / lag:** posts ≈15:30–16:30 ET = 02:00–03:00 IST next morning.
- **[B]** The yield on inflation-protected Treasuries: what a safe dollar pays after inflation — gold's opportunity cost. **[P]** DFII10 = 10-y TIPS constant maturity; TIPS liquidity premium distorts it in crises (2008, Mar 2020); no free intraday feed (proxy: ^TNX − last T10YIE).
- **Evidence (G-MACRO H1):** weekly beta −9.9 %/100 bp 2010–21 (t −12.2, R² 0.19), **−5.0 since 2022 (t −4.0, R² 0.06)**; the *level* fit sign-flipped after 2022 (central-bank era); G-STUDY: 4-week changes forecast nothing. A contemporaneous explainer, never a forecast.
- **In app today:** Pre-Open desk (one number, FRED + this fallback). **Consolidation:** GOLD › MACRO driver strip with history; HEALTH tile.
- **Verdict:** PUBLISH-CORE. · **Catalog:** `UST_REAL_{5,7,10,20,30}Y` · `gold_series` · job `gold_overnight` (03:10)

### G2 · US Treasury daily nominal par yield curve CSV (1 Mo … 30 Yr)
- **URL:** `…/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026` · **Verified (G-MACRO):** 200 · 0.88 s; 23 Oct: 3m 4.22, **2y 4.69**, 10y 5.00, 30y 5.33.
- **[B]** The 2-year yield is where the market thinks the Fed is going. **[P]** nominal = real + breakeven (identity verified to 0.0 bp).
- **Verdict:** PUBLISH-CORE. · **Catalog:** `UST_NOM_{3M,2Y,10Y,30Y}` · `gold_series`

### G3 · FRED `fredgraph.csv` (keyless) — real yields `DFII5, DFII7, DFII10, DFII20, DFII30`
- **URL:** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10` · **Verified:** 200 · 0.06–1.1 s (plain UA; browser UAs stall), DFII10 2003-01-02 → 2026-10-22 (2.64); five agents. `FRED_API_KEY` is **not** set in `.env` (count 0); the REST/ALFRED API answers 400 without it.
- **Terms:** FRED legal: free, attribution.
- **Verdict:** PUBLISH-CORE — the history behind G1 (Treasury is the same-day source; FRED the archive). · **Catalog:** `FRED_DFII{5,7,10,20,30}` · job `gold_fred_daily` (21:30)

### G4 · FRED — breakevens and inflation expectations `T10YIE, T5YIE, T5YIFR, EXPINF1YR, EXPINF10YR, MICH`
- **Verified (G-MACRO):** 200; T10YIE 2003→ (2.34 on 23 Oct); T5YIFR 2003→ (2.20); EXPINF monthly (2026-10-01); MICH monthly.
- **Evidence (G-MACRO):** breakeven beta +12.7 %/100 bp (t +10) 2010–21; +4.3 (t 1.8) since 2022.
- **Verdict:** PUBLISH-CONTEXT — the nominal = real + breakeven split. · **Catalog:** `FRED_T10YIE`, `FRED_T5YIFR`, `FRED_EXPINF10YR`, `FRED_MICH`

### G5 · FRED — nominal yields and slope `DGS2, DGS10, DGS30, DGS3MO, T10Y2Y`
- **Verified (G-MACRO):** DGS2 1976→ (4.65), DGS10 1962→ (4.96). · **Verdict:** PUBLISH-CORE (history for G2). · **Catalog:** `FRED_DGS2`, `FRED_DGS10`, `FRED_T10Y2Y`

### G6 · FRED — policy rates `DFF, EFFR, FEDFUNDS, DFEDTARU, DFEDTARL, SOFR`
- **Verified (G-MACRO):** 200 (EFFR 3.88; target 3.75–4.00 on 25 Oct). · **Verdict:** PUBLISH-CONTEXT (Fed-path panel inputs). · **Catalog:** `FRED_EFFR`, `FRED_DFEDTARU`, `FRED_SOFR`

### G7 · FRED — dollar indices and H.10 FX `DTWEXBGS, DTWEXAFEGS, DEXINUS, DEXUSEU, DEXJPUS, DEXCHUS, DEXUSUK, DEXCAUS, DEXSDUS, DEXSZUS`
- **Verified (G-MACRO):** DTWEXBGS 2006→ (121.40 on 16 Oct — published weekly, ~1 week behind); DEXINUS 94.96 (16 Oct).
- **Verdict:** PUBLISH-CONTEXT — the broad dollar for monthly views; live dollar = A5. · **Catalog:** `FRED_DTWEXBGS`, `FRED_DEXCHUS` (the PBOC-parity fallback for CNY) · job `gold_fred_weekly` (Tue 03:10)

### G8 · FRED — volatility `VIXCLS, GVZCLS, OVXCLS`
- **Verified (G-MACRO):** GVZCLS 2008-06-03→ (22 Oct). · **Verdict:** PUBLISH-CORE (archive of A6). · **Catalog:** `FRED_GVZCLS`

### G9 · FRED — oil `DCOILWTICO, DCOILBRENTEU`
- **Verified (G-MACRO):** Brent 115.22 (20 Oct), 3–4 days behind; live Brent is on WEI. The CMDT FRED leg shows "key required" because it uses the keyed REST API — switch it to this keyless path (G-APP).
- **Verdict:** PUBLISH-CONTEXT. · **Catalog:** `FRED_DCOILBRENTEU`

### G10 · FRED — money and Fed liquidity `M2SL, WM2NS, WALCL, RRPONTSYD, WTREGEN, BOGMBASE`
- **Verified (G-MACRO):** M2SL 1959→ (Aug $23,343 bn); WALCL 2002→ (21 Oct); RRP 23 Oct. Gold/M2 at the 98th percentile since 1975.
- **Evidence:** "net liquidity" has no OOS evidence (G-MACRO). · **Verdict:** PUBLISH-CONTEXT (monthly context, collapsed). · **Catalog:** `FRED_M2SL`, `FRED_WALCL`, `FRED_RRPONTSYD`, `FRED_WTREGEN` · jobs `gold_fred_weekly` (Fri 03:10), `gold_monthly` (5th)

### G11 · FRED — US macro prints `CPIAUCSL, CPILFESL, PCEPI, PCEPILFE, PAYEMS, UNRATE`
- **Verified (G-MACRO):** 200 (CPI 2026-09, PCE 2026-08). · **Verdict:** PUBLISH-CONTEXT (actuals for the calendar's surprise column). · **Catalog:** `FRED_CPIAUCSL`, `FRED_PCEPILFE`, `FRED_PAYEMS` · job `gold_monthly` (5th)

### G12 · FRED — high-yield credit spread `BAMLH0A0HYM2`
- **Verified (G-MACRO):** 3.40 % (22 Oct). · **Verdict:** PUBLISH-CONTEXT (risk-off context line). · **Catalog:** `FRED_HY_OAS`

### G13 · FRED REST API and ALFRED vintages (`api.stlouisfed.org`)
- **Verified (G-MACRO):** 400 "api_key is not set". · **Verdict:** LINK-ONLY — FREE-KEY; the owner may register (O-7) to unlock ALFRED vintages for point-in-time studies (`docs/PROGRAMMATIC_DATA_ACCESS.md` §3).

### G14 · FRED foreign M2 (`MYAGM2EZM196N`, `MANMM101CNM189S`, `MYAGM2JPM189N`)
- **Verified (G-MACRO):** series end 2017-03 / 2018-12 / 2017-02 (dead). · **Verdict:** DO-NOT-PUBLISH.

### G15 · FRED releases calendar page
- **URL:** `https://fred.stlouisfed.org/releases/calendar` · plain client 200 (timed out once, G-MACRO). · **Verdict:** LINK-ONLY.

### G16 · Atlanta Fed Market Probability Tracker — historical data XLSX
- **URL:** `https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx` (7 MB; parse the `DATA` sheet; a `LICENSE` sheet whose text is not machine-readable — a human must read it, O-10)
- **Verified (G-MACRO):** 200 · 1.8 s; daily since Mar 2023; from 3-month SOFR options: per meeting window percentiles, mean, mode, P(cut), P(hike). **22 Oct (target 375–400): Dec-16 window P(hike) 86.9 %, P(cut) 4.5 %, mean 4.17 %; Mar-27 4.37 %; Sep-27 4.56 %.**
- **[B]** The odds of a Fed hike or cut at each meeting, from market prices. **[P]** a full distribution, not FedWatch's step function; FOMC decision 14:00 ET = 23:30 IST in US summer, **00:30 IST in winter (after the MCX close → gap risk at 09:00)**.
- **Verdict:** PUBLISH-CORE — replaces the FedWatch link as data. · **Catalog:** `gold_fed_path` · job `gold_morning` (06:40)

### G17 · Yahoo 30-day fed funds futures `ZQ=F`, `ZQZ26.CBT`, `ZQH27.CBT`
- **Verified (G-MACRO):** ZQ=F daily 2000→ (96.10 → 3.90 % vs EFFR 3.88); ZQZ26.CBT 5-min 95.96 → 4.04 % = +16 bp = 64 % of a December hike.
- **Verdict:** PUBLISH-CONTEXT — the implied-rate strip next to G16. · **Catalog:** `ZQ_<MONTH>` · `gold_daily_bars`

### G18 · Federal Reserve Board FOMC calendar page
- **URL:** `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` · **Verified:** 200 (already parsed by `routers/markets.py`). · **Verdict:** PUBLISH-CONTEXT (rows reused in `gold_events`, in IST).

### G19 · Forex Factory economic calendar JSON (this week)
- **URL:** `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (`nextweek.json` is 404) · **Verified (G-MACRO):** 200 · 0.30 s; fields `title, country, date (ISO, −04:00/−05:00 offsets), impact, forecast, previous`; **no `actual` field in any of 96 events** at fetch time. This week in IST: Wed 28 Oct 23:30 Fed decision (consensus hold 4.00 %), Thu 29 Oct 18:00 Advance GDP (3.2 %) + Core PCE m/m.
- **Terms:** personal use, cache, no hammering (hourly fetch).
- **[B]** When CPI/NFP/PCE/FOMC hit, in IST, with the consensus. **[P]** US releases at 08:30 ET = 18:00 IST (19:00 in US winter) — inside the MCX evening session; the ECO page has no US CPI/NFP/PCE today (gap).
- **Verdict:** PUBLISH-CORE — the US calendar in IST (and the ECO page's missing rows). · **Catalog:** `gold_events` kinds `US_CPI, US_NFP, US_PCE, US_GDP, FOMC` · job `gold_overnight` (hourly refresh in `gold_calendar_refresh`)

### G20 · BLS news-release schedule pages (CPI, Employment Situation)
- **URL:** `https://www.bls.gov/schedule/news_release/cpi.htm` · **403** to scripts (G-MACRO). · **Verdict:** LINK-ONLY.

### G21 · BLS public API v1 (no key) — CPI-U `CUUR0000SA0`
- **URL:** `https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0` · **Verified (G-MACRO):** 200 · 4.5 s, 2026-M09 (25 calls/day). · **Verdict:** PUBLISH-CONTEXT (actuals; FRED G11 duplicates it — use one).

### G22 · BEA news-release schedule page (PCE, GDP)
- **URL:** `https://www.bea.gov/news/schedule` · **Verified (G-MACRO):** 200 · 1.5 s, parseable ("October 29 8:30 AM Personal Income and Outlays, September 2026"). · **Verdict:** PUBLISH-CONTEXT (`gold_events` rows). 

### G23 · Geopolitical Risk index — monthly XLS (Caldara & Iacoviello)
- **URL:** `https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls` · **Verified (G-MACRO):** 200 · 1.6 s; monthly 1985→ (GPRH 1900→); Sep 2026 = 146.2 (90th pct). Free with citation (Caldara & Iacoviello 2022 AER).
- **Evidence (G-MACRO H4):** GPR change → next month t 1.0, R² 0.002; contemporaneous t 0.8. Weak, no prediction.
- **Verdict:** PUBLISH-CONTEXT (an explainer percentile). · **Catalog:** `GPR_MONTHLY` · `gold_series` (M)

### G24 · Geopolitical Risk index — daily recent XLS
- **URL:** `https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls` · **Verified (G-MACRO):** 200 · 2.1 s; daily to 19 Oct 2026 (248.7, 98th pct; 30-day avg 176); file updated ~weekly. · **Verdict:** PUBLISH-CONTEXT. · **Catalog:** `GPR_DAILY` · job `gold_weekly` (Mon)

### G25 · Cleveland Fed inflation-expectations page
- **URL:** `https://www.clevelandfed.org/indicators-and-data/inflation-expectations` · 200; same numbers as FRED `EXPINF*`. · **Verdict:** LINK-ONLY.

### G26 · World Bank Commodity Markets Outlook "Pink Sheet" monthly prices XLSX
- **URL:** `https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx` · **Verified (G-MACRO):** 200 · 0.68 s; sheet "Monthly Prices" 1960M01 → **Dec 2024 (stale vintage at the documented URL)**; monthly averages; CC BY-4.0.
- **Verdict:** PUBLISH-CONTEXT — the 1971→ seasonality grid only (spliced with GC=F month-ends). · **Catalog:** `WB_GOLD_MONTHLY_AVG`

### G27 · Google News RSS search (gold / Fed / Hormuz / China gold / rupee topics)
- **URL:** `https://news.google.com/rss/search?q=%22gold%20prices%22%20when%3A1d&hl=en-IN&gl=IN&ceid=IN%3Aen` · **Verified (G-APP):** 200 · 0.80 s · 100 items. Terms: personal RSS use; links only.
- **Evidence:** the project's news-scan track record was NO EDGE; the headline risk count is a `heuristic`.
- **Verdict:** PUBLISH-CONTEXT — gold-topic headlines (title + publisher + link) on GOLD › HEALTH; the "France/OAT" topic and the `eurusd_trigger=1.1161` default move to prefs.

---

## H. Internal reference data and files

### H1 · `gold_premarket/YYYYMMDD.json` daily briefs (written by an external scheduled task)
- **Verified (G-APP):** 9 files 9–23 Oct 2026, schema `gold_premarket.schema.json` (14 top-level keys: baseline, markets, gap model, Fed, triggers, 12–25 news items, flows, circulars, technicals, calendar, synthesis, data quality); **ingested nowhere** (grep across services/ui/scripts/shared: no reference).
- **Verdict:** PUBLISH-CONTEXT — schema-validated ingest, shown as "today's brief (automated, confidence X)". · **Catalog:** `gold_brief_docs` · job `gold_brief_ingest` (09:00–09:05)

### H2 · `data/gold_preopen/log.json` — the fair-open accuracy log
- **Verified (G-APP, G-EDU):** 4 rows since 15 Oct 2026: 15 Oct fair 151,000 vs open 147,482 (miss −3,518; naive −968 — the model was *worse* than "open = settlement"); 23 Oct fair 144,938 vs open 142,058 (miss −2,880; naive −4,021); 20 Oct has no open (Dussehra morning closure; the jobs ignore MCX's calendar); `inr_now == inr_ref` on 2 of 3 days (no fresh overnight INR bar). Mean miss ≈ ₹2.5–3.2k against a ₹300 chase limit.
- **Verdict:** PUBLISH-CORE — the only honesty check on the model; migrates to `gold_preopen_log` with `inputs_json`; the verdict carries a `heuristic` badge and the measured miss until ≥ 20 rows exist.

### H3 · `shared/mcx_specs.py` (specs, holidays, expiries, costs) and `routers/mcx.py` aliases
- **Verified (G-INDIA, G-STUDY):** `round_trip_costs("GOLD", ₹122,104)` = ₹2,146 per 1-kg lot (0.018 %); GOLDTEN missing; margin constant 6 % vs live 9.25 %; Muhurat note wrong; the fair-value path bypasses the SWR Yahoo cache (`mcx._fair_value` → `gp._yahoo_bars`).
- **Verdict:** PUBLISH-CORE — reference data behind the selector and ticket, with the four fixes in PLAN §b.

---

## I. ICICI Direct auto-login (G-LOGIN; static review, no login started)

### I1 · ICICI Direct FAQs: Login Authenticator (enable/disable/login), TOTP in the API login page, 2FA article, ways to log in
- **URLs:** `https://www.icicidirect.com/faqs/my-account/what-is-login-authenticator-how-to-enable-disable-the-login-authenticator-how-to-login-using-login-authenticator` · `https://www.icicidirect.com/faqs/fno/is-totp-option-available-in-icici-direct-api` · `https://icicidirect.com/futures-and-options/articles/two-factor-authentication-2fa-login` · `https://www.icicidirect.com/faqs/my-account/what-are-the-different-ways-to-log-in-to-the-icici-direct-platform`
- **Verified (G-LOGIN):** all 200. Quotes: Settings → "Login Authenticator" → Google Authenticator → "scan the QR code … Alternatively, manually enter the provided key"; disable = Settings → "Disable Login Authenticator" + Password/PIN; "The TOTP option is live in ICICIdirect API login page"; OTP valid 5 min; "If user generates OTP consecutively 10 times without using it, then trading account will get locked".
- **Verdict:** LINK-ONLY — the BRKR panel's "Step 1" links.

### I2 · ICICI FAQ "What is a Static IP?" (SEBI static-IP notice on the API login page)
- **URL:** `https://www.icicidirect.com/faqs/fno/what-is-a-static-ip` · 200 but the enforcement answer is not in the static body → UNVERIFIED (owner question Q4: irrelevant in PAPER, relevant before LIVE).
- **Verdict:** DO-NOT-PUBLISH (a question for the owner, not a panel).

### I3 · ICICI community posts ("TOTP Login", "Introducing Google Authenticator")
- **URL:** `https://community.icicidirect.com/totp-login` · ECONNRESET/timeout ×2 → UNVERIFIED. · **Verdict:** DO-NOT-PUBLISH (owner may read once for the wrong-code lockout rule).

### I4 · ICICI Breeze API login page
- **URL:** `https://api.icicidirect.com/apiuser/login?api_key=<app key>` · **Verified (G-LOGIN):** with a dummy key 200 · 0.28 s · "Public Key does not exist." — the form markup cannot be fetched without the real key; selectors are proven only by the real runs of 14 and 23 Oct (TOTP panel: six `tg-nm=otp` boxes inside `#pnlOTP`, "Having issues? Verify with OTP").
- **Verdict:** PUBLISH-CORE — the login path (credentialed; PLAN §g).

### I5 · Local login state and status endpoints (`.env` key names, Keychain item, `.session_cache.json`, `.icici_login_block.json`, `data/icici_otp*.json`, `.logs/icici_login_failure.png`, `GET :8008/api/scheduler/status`, `GET :8010/api/config/setup-status`, the unit/integration tests)
- **Verified (G-LOGIN):** `ICICI_TOTP_SECRET` in neither `.env` (0 lines) nor the Keychain; `.env` is **0644** (RUNBOOK says 600); the 08:00 job is scheduled (`next_run 2026-10-26T08:00 IST`); last login 23 Oct 08:08 "refreshed via ui-api" after an 08:05 SMS-panel timeout; `tests/unit/test_icici_login.py` 16 passed (RFC 6238 vectors); clock skew +0.3 s; Chrome + Playwright 1.60 present.
- **Verdict:** PUBLISH-CONTEXT — the BRKR status strip (`configured`, `source`, `env_mode`, `login_running`, `otp_pending`, `last_login`).

---

## 10. Derived metrics dictionary (what the terminal computes; verdict and badge)

Notation: `L/S/X` long/short/spread per group; `OI`; `F1,F2` consecutive futures; `G` gold USD; `INR` USD/INR; `d` duty rate; 31.1034768 g/oz; MCX ₹/10 g.

| # | Metric | Formula / definition | Cadence | Evidence | Verdict · badge |
|---|---|---|---|---|---|
| M1 | Fair open / fair value (₹/10 g) | settlement × (COMEX now ÷ COMEX at the MCX close) × (INR now ÷ INR at the close); references = 30-min averages before 23:30/23:55 | live, 08:45 snapshot | accuracy log: 2–3 scored days, misses ₹2.9–3.5k | PUBLISH-CORE · `arithmetic` (the verdict strip wears `heuristic`) |
| M2 | Expected gap, COMEX part, rupee part (waterfall) | fair − settlement; settlement × (r_c − 1); settlement × r_c × (r_i − 1) | live | identity | PUBLISH-CORE · `arithmetic` |
| M3 | MCX now vs fair; ₹300 chase limit | live − fair | live | unsupported (0 % within ₹300 so far) | PUBLISH-CORE · `heuristic` + measured miss |
| M4 | Accuracy stats (MAE, median, p90, within-limit %, bias, naive MAE) | from `gold_preopen_log` | daily | this is the evidence | PUBLISH-CORE · `arithmetic` |
| M5 | Landed cost (₹/10 g) | G × INR ÷ 31.1034768 × 10 | live/daily | identity | PUBLISH-CORE · `arithmetic` |
| M6 | Duty-paid landed | landed × (1 + d), d = 0.15 since 2026-05-13 (dated) | live/daily | identity | PUBLISH-CORE · `arithmetic` |
| M7 | India dealer premium (%) | IBJA 999 PM ÷ (duty-paid landed × 0.999) − 1 — landed (COMEX per fine oz × INR) is FINE gold, purity P = × P/1000 (PM decision D1, 5 Nov 2026); inputs sampled at the IBJA fix minute (FBIL rate) | daily | none in-house (GS-PREMIUM after 2 y); Reuters sanity | PUBLISH-CORE · `context` |
| M8 | MCX basis vs duty-paid landed; carry-adjusted basis | MCX front settlement proxy of the session ÷ (that session's duty-paid landed × purity/1000: GOLD/GOLDM 0.995, TEN/PETAL/GUINEA 0.999, D1) − 1; minus carry to expiry (≈6–7 % p.a.) | daily/live | none | PUBLISH-CORE · `context` (replaces "implied premium 18 %") |
| M9 | Shanghai premium ($/oz, %) | SGE PM (CNY/g) × 31.1034768 ÷ USDCNY − LBMA PM (or COMEX at 14:15 Beijing) | daily | none in-house (GS-P3) | PUBLISH-CORE · `context` |
| M10 | Rule of thumb ₹ per $1 COMEX / ₹ per ₹1 INR | settlement ÷ COMEX ref; settlement ÷ INR ref | live | identity | PUBLISH-CONTEXT · `arithmetic` |
| M11 | Open interest and weekly ΔOI (COT) | `open_interest_all`, `change_in_open_interest_all` | weekly | G-STUDY FAIL forecast / CONTEXT | PUBLISH-CORE · `context` |
| M12 | Long / short / spread by trader group | COT fields | weekly | descriptive | PUBLISH-CORE · `context` |
| M13 | Net position per group (contracts, Moz, tonnes, $) | N = L − S; × 100 oz; × 100/32,150.7 t; × price | weekly | descriptive | PUBLISH-CORE · `context` |
| M14 | Weekly change and the who-added / who-closed decomposition | ΔL < 0 closed longs; ΔS < 0 covered shorts; ΔL > 0 new longs; ΔS > 0 new shorts | weekly | **PASS as description** (Spearman +0.65 same week) | PUBLISH-CORE · `context` |
| M15 | Weekly fund-driver label | new longs / short covering / long liquidation / new shorts / "funds sold into it" / "funds bought the dip" | weekly | right ≈ 3 weeks in 4 (G-STUDY §5.1) | PUBLISH-CORE · `context` |
| M16 | % of OI by group; net % OI | 100 × L/OI etc. | weekly | descriptive | PUBLISH-CORE · `context` |
| M17 | COT index 26/52/156 w | 100 × (N − min)/(max − min) over N reports | weekly | FAIL (lore points the wrong way) | PUBLISH-CONTEXT · `context` ("no forecasting power 2006–2026") |
| M18 | z-score 52/156 w; all-history percentile; records | (N − mean)/sd; percentile | weekly | FAIL | PUBLISH-CONTEXT · `context` |
| M19 | Number of traders, average position | `traders_*`; L ÷ traders | weekly | — | PUBLISH-CONTEXT · `context` (drawer) |
| M20 | Concentration ratios (top 4/8, gross/net) | `conc_*` (legacy) | weekly | — | PUBLISH-CONTEXT · `context` (drawer) |
| M21 | Commercials vs speculators divergence | non-confirmation of 13-week highs; opposite 52-w extremes | weekly | FAIL | PUBLISH-CONTEXT · `context` (worded) |
| M22 | Options-only positioning | combined − futures-only per group | weekly | no information (G-STUDY) | PUBLISH-CONTEXT · `context` (one drawer line) |
| M23 | Weekly flow z | z of ΔN over 52 w | weekly | same-week corr 0.64 | PUBLISH-CONTEXT · `context` |
| M24 | Rally / decline decomposition | Δ by group, ΔOI, ΔGLD since the last 2-year low / since the high | weekly | descriptive | PUBLISH-CONTEXT · `context` |
| M25 | Managed-money long/short ratio | L ÷ S | weekly | explodes near 0 | LINK-ONLY (derivable) |
| M26 | Hedging pressure (Bessembinder) | S_comm ÷ (L_comm + S_comm) | weekly | research only | DO-NOT-PUBLISH |
| M27 | COT buy/sell signal, alert, long/flat rule | — | — | 0 of 69 rules | DO-NOT-PUBLISH |
| M28 | Daily OI × price quadrant (COMEX product OI; MCX per contract) | sign(Δprice) × sign(ΔOI) → long build-up / short build-up / short covering / long unwinding | daily | weekly version: 1 of 12 cells (G-STUDY); daily untested (G-STUDY-2) | PUBLISH-CORE tape · labels `context` |
| M29 | COMEX OI by product (GC/MGC/1OZ/QO/OG) and Δ | C1 | daily | — | PUBLISH-CORE · `context` |
| M30 | MCX OI by contract and Δ; roll ratio; days to tender | F1 | daily | — | PUBLISH-CORE · `arithmetic` |
| M31 | Term structure, calendar spread, implied carry | (F2/F1 − 1) × 365/days | daily/live | cost, not forecast | PUBLISH-CORE · `arithmetic` |
| M32 | Basis to spot; EFP proxy | F − spot − theoretical carry | daily | none | PUBLISH-CONTEXT · `context` |
| M33 | EFP volume, EFP share of volume, 20-d average | C2 | daily | none | PUBLISH-CONTEXT · `context` |
| M34 | Roll status: days to FND / LTD; front-month OI share | C3, C1 | daily | — | PUBLISH-CORE · `arithmetic` |
| M35 | Initial margin % of notional (COMEX); NRML margin % (MCX) | C4; F8 | daily | — | PUBLISH-CORE · `arithmetic` |
| M36 | Put/call OI ratio (OG) | C1 | daily | none | PUBLISH-CONTEXT · `context` |
| M37 | Paper-to-registered coverage (all months; front month after FND) | OI oz ÷ registered | daily | none; abused online | PUBLISH-CONTEXT (only with C8 access) |
| M38 | Warehouse stock flows; delivery intents MTD | C8, C9 | daily | none | PUBLISH-CONTEXT (only with access) |
| M39 | Volume/OI churn; volume vs 20-d average | C1 | daily | Bessembinder–Seguin (volatility) | PUBLISH-CONTEXT · `context` |
| M40 | Month-end OI y/y | C1 month-ends | monthly | — | LINK-ONLY (C5) |
| M41 | SHFE active-month OI Δ; SGE Au(T+D) OI and settlement direction | D1, D3 | daily | none | PUBLISH-CONTEXT · `context` (SGE direction tile CORE) |
| M42 | Gold/silver and gold/platinum ratios with percentiles | A3 | daily | none | PUBLISH-CONTEXT · `context` |
| M43 | GLD daily creation/redemption (t); 1w/1m/YTD; IAU | E1, E3 | daily | FAIL forecast; same-week R² 16 % | PUBLISH-CORE tile · `context` |
| M44 | Global ETF flow by region (weekly, monthly); India tonnes | E5 | weekly | none (GS-P2) | PUBLISH-CORE · `context` |
| M45 | Central-bank net purchases by country | E12 Δ ounces | monthly | none (GS-P5, not yet pre-registered) | PUBLISH-CORE · `context` |
| M46 | RBI gold value, share of reserves, implied tonnes | F11 | weekly | — | PUBLISH-CONTEXT · `context` |
| M47 | SGE withdrawals, delivery ratio | D5 | monthly | — | PUBLISH-CONTEXT · `context` |
| M48 | London vault change; LBMA OTC turnover | E15, E14 | monthly / weekly | — | PUBLISH-CONTEXT · `context` |
| M49 | Gold balance-sheet panel (supply vs demand by category) | E7 | quarterly | — | PUBLISH-CONTEXT · `context` |
| M50 | Physical tightness score (0–5) | count of: Shanghai premium > 0, India premium > 0, SGE withdrawals rising, ETF creations, London outflow | daily (mixed lags) | none | DO-NOT-PUBLISH (a composite reads as a signal; show the five flags separately) |
| M51 | Coin demand (Perth Mint) | E17 | monthly | — | LINK-ONLY |
| M52 | India imports (monthly $bn, y/y); Swiss exports to India (t) | F14, E19 | monthly | — | PUBLISH-CONTEXT · `context` |
| M53 | AMFI gold-ETF net flow % of AUM; AUM in tonnes | F16 | monthly | G-INDIA-1 FAIL as timing | PUBLISH-CONTEXT · `context` |
| M54 | 10-y real-yield level, Δ1d/1w/1m, 1-y percentile, health flag | G1/G3 | daily | contemporaneous beta −5.0 %/100 bp since 2022; no lead | PUBLISH-CORE · `context` |
| M55 | Nominal = real + breakeven split; 2-y yield | G2/G4/G5 | daily | — | PUBLISH-CONTEXT (split) · CORE (2-y) |
| M56 | "Gold or the dollar?" KGX decomposition (DXY weights; rupee leg added) | usd_move = −Σ wᵢ Δln fᵢ; pure = G + usd_move | daily | identity (22 Oct: −2.18 % = −2.29 % pure + 0.10 % USD) | PUBLISH-CORE · `arithmetic` |
| M57 | Gold in INR/EUR/JPY/GBP/CNY (1d/1w/1m/YTD) and landed ₹/10 g | G × ccy/USD | daily | identity | PUBLISH-CORE · `arithmetic` |
| M58 | Fed-path probabilities per meeting; ZQ implied rates | G16, G17 | daily | — | PUBLISH-CORE · `context` |
| M59 | US release calendar in IST with consensus; in-session vs after-close flag | G19, G22 | daily | event-day vol documented | PUBLISH-CORE · `arithmetic` |
| M60 | GVZ expected move: 1σ day in %, $/oz, ₹/10 g, ₹ per lot per contract; realised 20-d vol; ATR14 ₹ | GVZ/√252 × price × multiplier | daily | sizing arithmetic | PUBLISH-CORE · `arithmetic` |
| M61 | Gold/M2 percentile; HY OAS; GPR percentile (monthly, daily) | G10, G12, G23/24 | monthly/weekly | H4: no prediction | PUBLISH-CONTEXT · `context` (collapsed) |
| M62 | Seasonality strip (month-of-year mean, hit rate) | G26 + A1 | monthly | no month passes both halves | PUBLISH-CONTEXT · `context` with caveat |
| M63 | Fair-value residual from a real-yield/DXY regression | ln G on DFII10, DXY | weekly | H5: model says $788; trailing refit has the wrong sign | DO-NOT-PUBLISH |
| M64 | Driver-health panel (rolling 1-y correlations, regime betas) | daily changes | weekly | the lesson of H1 | PUBLISH-CORE · `context` |
| M65 | Health verdict sentence (rule-based, descriptive) | thresholds listed in LEARN; ends "describes, does not predict" | live | none | PUBLISH-CORE · `context` |
| M66 | Health score / "N of 7 supportive" | — | — | reads as a forecast | DO-NOT-PUBLISH (disagreement 4) |
| M67 | Event-risk headline count | keyword hits over ≤ 18 headlines | live | none | PUBLISH-CONTEXT · `heuristic` (count only; no sizing advice) |
| M68 | Tick value, multiplier, notional, round-trip cost, breakeven ticks | `shared/mcx_specs` | live | cost model | PUBLISH-CORE · `arithmetic` |
| M69 | Max lots at 1 % risk (1.5-ATR stop); USD/INR hedge lots per MCX lot | account × 1 % ÷ (1.5 × ATR₁₄ × multiplier); notional ÷ USDINR lot | daily | arithmetic (GOLDM ≈ ₹26 lakh account per lot) | PUBLISH-CORE · `arithmetic` |
| M70 | Session clock, MCX holidays, Muhurat, DST switches | `shared/mcx_specs` | live | — | PUBLISH-CORE · `arithmetic` |
| M71 | 24-h chart with previous-day overlay, settle line, session bands (IST + NY); 3-day overlay; return ladder | A1 bars | live | diagnostic | PUBLISH-CORE (ladder CONTEXT) |

---

## 11. Evidence ledger (the G-STUDY results that the badges rest on)

| Study | Data | Result | Consequence |
|---|---|---|---|
| G-STUDY (main), `reports/gold_program/G-STUDY/FINDINGS.md` | 1,063 COT reports 2006→2026, GC=F, signals dated at release, NW t, 0.15 % costs, walk-forward | **FAIL as a forecast** for every positioning metric, GLD Δ, real-yield Δ, DXY Δ at 1/4/13 weeks; 0 of 69 rules beat scaled buy-and-hold; COT-index lore reversed. **PASS as description:** Δ fund net vs the week's move Spearman +0.65 (stable), next week −0.02 | `context` badges everywhere; one weekly "who did what" strip; no COT signal/alert/rule |
| G-COT COT-1 (`G-COT/data/study_tables.md`) | same, different horizons (5/20/65 sessions) | no signal clears t ≥ 2 in both halves; bottom-decile fund net % OI → +5.2 % over 65 sessions (t 2.6 full, 1.4/1.3 halves) | a LEARN sentence, never a badge |
| G-MACRO H1–H5 (`G-MACRO/study.json`) | 6,049 daily obs 2003→2026; 1971→ monthly | H1 real yields: contemporaneous beta in every regime, weaker since 2022, level fit sign-flipped; H2 dollar: beta ≈ −1 in every regime; H3 seasonality: no month passes both halves; H4 GPR: no prediction; H5 fair value: not a signal | drivers shown as explainers with rolling correlations; fair value DO-NOT-PUBLISH |
| G-INDIA-1 (`G-INDIA/scratch/amfi_study_results.json`) | 79 months AMFI flows vs rupee gold | flows chase returns (ρ +0.25, p 0.03) and do not predict (ρ +0.12, p 0.31) | AMFI panel `context` |
| Accuracy log (H2) | 3 scored mornings | model mean miss ₹2,496 vs naive ₹2,147; 0 % within ₹300 | `heuristic` chip on the verdict; re-decide at 20 rows |
| Proposed (pre-register first, PLAN §h): G-STUDY-2 OI quadrant daily 2014→; GS-P1 GLD daily tonnes 2004→; GS-P2 WGC weekly flows 2003→; GS-P3 SGE premium + Au(T+D) OI (after history); GS-P4 seasonality in rupees (run 26 Oct 2026: VOID / FAIL — drift, not a calendar); GS-P5 IMF monthly CB buying (not yet pre-registered); GS-PREMIUM India/Shanghai premium (after 2 y); G-INDIA OI matrix (after 60 sessions); registry `reports/gold_program/STUDIES.md` | | honest prior: FAIL as timing, PASS as context | a `signal` badge appears only after a PASS row in `reports/gold_program/FINDINGS.md` |

---

## 12. Cadence map (IST) — what arrives when

| When (IST) | Arrives | Entry |
|---|---|---|
| ≈03:30 (04:30 after 1 Nov) | Globex reopens after the 17:00–18:00 ET maintenance hour | A1 |
| ≈02:00–03:00 | US Treasury real/nominal curve for the prior session | G1, G2 |
| ≈06:00 | GLD row for T−1 (Friday rows by Monday morning); IAU page | E1, E3 |
| ≈07:00–07:30 | ICICI security master (Friday's file until Monday ≈07:30) | F1 |
| 07:45 / 11:45 | Shanghai benchmark AM / PM | A11 |
| 09:00 | MCX opens (morning-closure holidays open 17:00) | H3 |
| ≈12:00–13:00 / ≈17:00–18:30 | IBJA AM / PM fixes | F10 |
| ≈12:30–13:00 | SHFE day close; SGE close 13:00; SGE daily table later in the afternoon (≈16:00) | D1, D3 |
| ≈13:30 | FBIL/RBI USD-INR reference rate | F13 |
| ≈14:00–15:30 (T+1) | CME FTP daily volume & OI | C1 |
| 16:00 / 20:30 (GMT season; 15:00/19:30 on BST) | LBMA AM / PM | A8/A9 |
| 18:00 (19:00 in US winter) | US CPI / NFP / PCE / GDP (08:30 ET) — inside the MCX evening session | G19 |
| 23:30 (00:30 in US winter) | FOMC decision (14:00 ET) — after the MCX close in winter | G16, G18 |
| 23:30 (23:55 from 2 Nov) | MCX close; settlement = VWAP of the last 30 min | H3 |
| Sat 01:00 (02:00 from 7 Nov); Mon releases → Tue 02:00 | CFTC COT | B1 |
| Mon ≈11:30 | WGC weekly ETF flows for the week ended Friday | E5 |
| Fri ≈17:00 | RBI WSS (data as of the previous Friday) | F11 |
| Weekly (Friday-dated) | LBMA 12-wk turnover headline; WGC premiums; GPR daily file | E14, E8, G24 |
| ~5th | FRED monthly macro (CPI/PCE/M2/GPR monthly) | G10, G11, G23 |
| ~7th | PBoC reserves (SAFE) | E13 |
| ~8–11th | AMFI monthly | F16 |
| ~10–12th | SGE Data Highlights PDF | D5 |
| ~15–16th | PIB trade release (gold imports) | F14 |
| ~18–20th | Swiss customs | E19 |
| ~20–25th | LBMA vault holdings; IMF IRFCL refresh (~25th) | E15, E12 |
| Quarterly (~5 weeks after quarter end; Q3-26 early Nov) | WGC Gold Demand Trends / balance sheet | E7 |
| 1 Feb | Union Budget (duty) | F9 |
| 2026 clock changes | UK → GMT 25 Oct (done); US DST ends 1 Nov (MCX 23:55 from 2 Nov; COT Sat 02:00; FOMC 00:30; US data 19:00) | — |

*Every row above is a job slot in PLAN §c; the jobs fetch, they never restart anything, so the 07:45–09:20 and 18:30–21:15 freeze windows constrain only deploys — but no heavy job is placed inside them.*
