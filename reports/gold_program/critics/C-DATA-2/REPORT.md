# C-DATA-2 — data-correctness re-review of the GOLD page after wave 1c (release 20261105-034204)

Reviewed 5 Nov 2026 03:49 → 04:05 IST against http://127.0.0.1:8010 (GET only, paced) and the data-service store on :8001.
MCX closed (opens 09:00), no Breeze quote cached, COMEX in its 17:00–18:00 ET maintenance hour. Every payload fetched is
under `/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/C-DATA-2/api/`
(`fetch.py`, 42 GETs); 1440×900 full-page screenshots of all nine sub-views in both layers plus the DOM text of every
`data-gold-panel` under `…/scratchpad/C-DATA-2/shots/` (`<sub>_P.png`, `<sub>_B.png`, `dom.json`; 0 console errors, 0 API
errors). Prior review: `reports/gold_program/critics/C-DATA/REPORT.md`.

## Verdict

**PUBLISH-WITH-FIXES, 7.5/10** (was HOLD 4/10). All nine C-DATA blockers and all six C-TRADER blockers are closed on the live
page; 13 of the 15 C-DATA/C-TRADER majors are closed, one (next FOMC) is still open with a different wrong value, one
(C-TRADER-14) could not be retested at this hour. The round introduced one new major (the Shanghai panel prints a false
identity "865.47 CNY/g = $3,935.1 at USDCNY 6.6643" — that product is $4,039) and a handful of minors (the header strip's
basis label is doubled on every sub-view, the WEI line prints "GOLD-SPECIF", ui-api ignores the store's `partial` flag,
the COT release appears twice in the event strip, the pre-open card still says "Trade the open only if …").

## 1. Re-derivations (stored rows → screen)

| What | Inputs (store, 03:50 IST) | Derived | On screen / payload | OK |
|---|---|---|---|---|
| Landed ₹/10 g | GCZ26.CMX 4,072.2 (03:29 IST) × INR=X 94.63 × 10 ÷ 31.1035 | 1,23,893.5 | ph.ladder ₹1,23,894 = c.mcx footer = health.fair.landed 123,894 | ✓ one number page-wide |
| Duty-paid landed | × 1.15 | 1,42,477.6 | ₹1,42,478 on PHYSICAL, CONTRACTS, HEALTH fair | ✓ |
| Desk fair open | 140,186 × (1 + (4,072.2 − 3,942.82)/3,942.82) + rupee leg (94.63 vs 94.74) | 140,186 + 4,600 − 163 ≈ 1,44,623 | h.open ₹1,44,618, gap +₹4,432 (+3.16 %); comex_part 4,600, rupee −168 | ✓ (ref rounding) |
| Settlement basis | MCX_BASIS_PCT 2026-11-03 stored 1.58 | 1.58 | strip, INDIA BASIS gauge, H4 clause "+1.6 %", ph.ladder "+1.58 % at the Tue 03 Nov settlement", c.mcx footer | ✓ one clock, one number (was 1.50 model vs 1.58 stored) |
| Strip clock at 03:50 | session.mcx.is_open false, mcx_live null | settlement | strip.mcx_shown 'settlement', basis_clock 'settlement', "₹1,40,186 Tue 03 Nov settlement" | ✓ |
| COT MM net 27 Oct | 122,508 − 16,946 | 105,562; Δ +1,356 (+1.30 %) | +105,562 / +1,356 everywhere | ✓ |
| Driver word 27 Oct | ΔL +1,538, ΔS +182, price −1.64 % → net rose on a down week | "funds bought the dip" | /cot.driver_label, p.hero, w.whodid, H3 "(bought the dip)" | ✓ (was "new shorts") |
| COT release | gold_cot.release_at 2026-10-30T19:30 UTC | Sat 31 Oct 01:00 IST | /cot.latest.release_at '2026-10-31T01:00:00+05:30', release_ist 'Sat 31 Oct 01:00 IST'; p.hero "released Sat 31 Oct 01:00 IST" | ✓ |
| Crowd percentiles | data-service 1986→ panel | 50.0 / OI 19.5 | p.crowd "percentile 50 · all-history percentile (1986→, data-service)", p.hero OI "percentile 20" | ✓ |
| 1-min bar clock | /db/gold/bars 1m last ts '2026-11-04T21:44:20+00:00' | 03:14:20 IST | /api/gold/bars bars[-1].ts '2026-11-05T03:14:20+05:30' = freshness.as_of; tape "03:10 16:40 · 4,070.10" | ✓ (was 5 h 30 early) |
| DAILY legend | gold_daily_bars 2 Nov 3,969.6 / 3 Nov 3,940.4 | +1.81 % / −0.74 % | "Mon 02 Nov close 3,969.60 ▲+1.81 %", "Tue 03 Nov close 3,940.40 ▼−0.74 %", "Wed 04 Nov last 4,070.10"; dashed line = Tue 03 Nov close 3,940.40 | ✓ |
| Gold week to date | 30 Oct 3,898.9 → 4 Nov 4,070.8 | +4.41 % | verdict "+4.4 % week to date (since the Fri 30 Oct close)" = w.table +4.41 % = w.grid +4.4 % | ✓ (was 5-session +0.7 %) |
| DXY week to date | DX-Y.NYB 30 Oct 101.88 → 4 Nov 101.523 | −0.35 % → usd effect +0.35, share 0.08 < 0.4 | dollar gauge "101.5 ▼−0.35 % W"; headline GOLD-SPECIFIC with both legs tested (H2 value 0.35) | ✓ (word now earned) |
| DXY 1 w (MACRO) | 28 Oct 102.19 → 101.523 | −0.65 % | mc.drivers "DOLLAR INDEX (DXY) 101.52 · 1w −0.65% · SUPPORTIVE", series DXY_CLOSE | ✓ (was DTWEXBGS 121.67 HEADWIND) |
| Real yield W | DFII10 30 Oct 2.60 → 2 Nov 2.62 | +2 bp | gauge "▲+2 bp W", mc.drivers "1d +2 bp" | ✓ |
| Shanghai gauge Δ W | −1.55 (3 Nov) − 75.34 (30 Oct) | −$76.89/oz | "▼−$76.89/oz W" | ✓ unit (was "+47.36 %") |
| Shanghai premium | same report_date only: SGE 3 Nov $3,935.10 vs LBMA PM 3 Nov 3,936.65 | −1.55 | "−1.55 · Tue 03 Nov (stored) · awaiting the LBMA PM of Wed 04 Nov"; gap "8 h 45 min" | ✓ (was +$109 cross-date) |
| SGE tile | 865.47 CNY/g (4 Nov) × 31.1035 ÷ 6.6643 | **$4,039.4** | "865.47 CNY/g = $3,935.1 at USDCNY 6.6643 · Wed 04 Nov" | ✗ NEW (N1) |
| India premium | INDIA_PREMIUM_PCT 2026-11-03 | −0.71 | ph.ladder "IBJA premium vs duty-paid −0.71% · Tue 03 Nov, both legs at the IBJA fix minute (stored)"; gauge extra −0.71 | ✓ (was −3.94 cross-clock) |
| IMF USA | 261,499,000 oz | 261.50 Moz · 8,133.5 t | ph.official "USA 2026-07 261.50 8,134" | ✓ |
| IMF BRA | 5,544,278.7 oz (all 12 stored months, Mar–Sep 2026 re-ingested 22:13 UTC, no scale break) | 5.54 Moz · 172 t | "BRA 2026-09 5.54 172 0.00"; m.official Δ 12 m +27.3 t (= 5.544 − 4.666 Moz) | ✓ |
| IMF CHN / POL | 77,470,000 / 21,634,000 oz | 2,409.6 / 672.9 t; Δ +0.74 Moz | "CHN 77.47 2,410 +0.74", "POL 21.63 673 +0.80"; PBOC 2,410 t | ✓ |
| COMEX spec card | CME calendar GC 202612: FND 2026-11-30, LTD 2026-12-29; PRF init 19,702, MinPxIncr 1 × factor 0.1 | DEC-26, 25 d / 54 d, $0.10 = $10 | c.spec "GC DEC-26 (202612) · FIRST NOTICE Mon 30 Nov · in 25 d · LAST TRADE Tue 29 Dec · in 54 d · TICK $0.10 = $10"; gold_events COMEX_FND row; verdict "FND in 25 d"; p.daily.comex "25 days to FND (Mon 30 Nov)" | ✓ (was NOV-26, FND 5 d ago) |
| COMEX carry | 4,105.0 / 4,072.2 − 1; 57 d | +0.806 %, +5.16 %/yr | c.comex "+32.8 = +0.81 % (+5.2 %/yr)" = verdict H5 | ✓ |
| MCX carry | 142,926 / 140,186 − 1; 63 d (FEB-27); 144,327 (APR-27) | +11.32 / +8.84 %/yr vs front | c.mcx "+11.3 % / +8.8 %"; /contracts expiries carry_pct 11.32 / 8.84 with carry_convention 'annualised vs the front expiry (as /curve)'; OI ladder prints OI only | ✓ one convention |
| MCX OI Δ | rows 29 Oct and 3 Nov only | 3 sessions | d.quadrant / p.daily.mcx "ΔOI +863 · Δ over 3 sessions (rows missing between)", sessions_spanned 3 | ✓ labelled |
| GLD | 1,037.66; 30 stored points from 1,056.84 (23 Sep); 2 Oct 1,055.70; 31 Dec 1,070.56 | −2.85 d, −19.18, −18.04, −32.90 | ph.etf "GLD CHANGE OVER THE LAST 30 STORED POINTS −19.2 t · 1 m −18.0 t · YTD −32.9 t"; w.table GLD Δ t −1.14 / −2.85 | ✓ (honest label; column filled) |
| Brief header | /brief bias 'neutral', confidence 0.45 | — | h.brief "automated brief · bias neutral · confidence 45 %"; 'aligned_tradeable' not on screen | ✓ |
| Next FOMC | no decision row in gold_events; fed.meetings[0] 2026-12-16 | real next decision Wed 9 Dec 2026 (statement 00:30 IST Thu 10 Dec) | mc.fed "next FOMC 2026-12-17 00:30 IST" | ✗ (F9/T12 still open) |

## 2. Status of every C-DATA / C-TRADER blocker and major

Closed (live evidence in §1 unless noted): C-DATA-1, -2, -3, -4, -5, -6, -7, -8, -10, -11, -12, -13, -14, -15, -16, -17;
C-TRADER-1, -2, -3, -4, -5, -6, -7, -8, -9, -10, -11, -13, -15, -16, -17, -18, -19.

Notes on the closures that carry a caveat:
- **C-DATA-13 / C-TRADER-10** (desk state / live basis): at 03:50 there is no Breeze quote, so the page shows one state
  everywhere (fair.desk_verdict_state AWAITING_OPEN, h.open "WAITING FOR THE OPEN", BRF line "Gold open: fair ₹144,618 (gap
  +4,432)") and one basis clock (settlement). The resolved-expiry cache key and the live-hours path were not exercised with
  a quote; the B3 re-checker's closed-hours cached-LTP case (reports/gold_program/build/wave1c.md, B3 adversarial re-check)
  remains an untested risk for the 23:55 → session-expiry window and the 08:00 → 09:00 login window.
- **C-DATA-17**: the live catalog (211 rows) still has no row for SGE_AUTD_OI / SGE_AUTD_DIRECTION / SHFE_AU_FRONT_OI
  (`/api/gold/series` → published false, 0 points), so B1's seed is not on the live store; the release build hides p.asia,
  so no "no verdict — not published" row is rendered. Closed on screen, open at the source (minor).
- **C-DATA-9 / C-TRADER-12**: still open — see F9 below.
- **C-TRADER-14**: not retested (it is 03:50 IST; the after-09:15 states need the 08:45/09:10 jobs and daylight). The [B]
  copy is now the honest data-driven wording; the server's `verdict.detail` still prints an action rule (N6).

### Still open

**F9 · MACRO mc.fed — "next FOMC 2026-12-17 00:30 IST" is an IMM futures date, not the decision (major, still-open).**
The Hammack speech is gone (`event_kind` → FOMC_SPEECH, `fed.speakers` lists the five speakers), but with no decision row in
`gold_events` (ForexFactory covers this week only) `next_fomc()` (services/ui-api/routers/gold.py:4700) falls back to
`fed.meetings[0]` = 2026-12-16. The whole `meetings` list — 16 Dec 2026, 17 Mar, 16 Jun, 15 Sep, 15 Dec 2027, 15 Mar,
21 Jun, 20 Sep 2028 — is the third Wednesday of each quarter-end month (the SOFR/IMM expiries the Atlanta tracker prices
to), spaced quarterly, which the FOMC's eight meetings a year are not; the December 2026 FOMC is 8–9 Dec, statement 14:00
ET Wed 9 Dec = 00:30 IST Thu 10 Dec. B3's own test fixture expects '2026-12-10 00:30 IST'; the live page prints a week
later and `days: 42` instead of 35. The same panel labels the eight IMM horizons as meetings ("Wed 16 Dec cut 4 % hike 85 %").
Evidence: `api/macro.json` fed.next_fomc {date_et 2026-12-16, source 'Atlanta Fed meeting dates (statement time computed)'},
fed.meetings[].meeting; `shots/macro_P.png`; DOM mc.fed "next FOMC 2026-12-17 00:30 ISTAFTER MCX CLOSE" (also the missing
separator C-TRADER-27 noted). Fix: keep a dated FOMC decision calendar (the Fed's published 2026/2027 schedule) in
shared/ or gold_events (kind FOMC, source 'federalreserve.gov') and never fall back to the tracker's horizons; label the
tracker's columns "SOFR horizon" not "meeting".

### New defects introduced or exposed by the round

**N1 · PHYSICAL ph.shanghai — the SGE tile prints a false identity (major).** "SGE AU99.99 PM 865.47 CNY/g = $3,935.1 at
USDCNY 6.6643 (Yahoo CNY=X) · Wed 04 Nov": 865.47 × 31.1035 ÷ 6.6643 = **$4,039.4**. The server pairs the latest SGE
CNY/g leg (ts_sge 2026-11-04) with `sge_usd_oz` taken from the stored 3 Nov pair (3,936.65 − 1.55 = 3,935.10), and
PhysicalView.tsx:150 joins them with "=" and dates the line Wed 04 Nov. The hero premium itself is right (−1.55, same-date
pair, "awaiting the LBMA PM of Wed 04 Nov"), but the tile beside it is exactly the cross-date leg the critics asked to be
removed, now hidden inside a wrong conversion. Evidence: `api/premiums.json` shanghai {sge_pm_cny_g 865.47, ts_sge
2026-11-04, sge_usd_oz 3935.1, usdcny 6.6643, pair_date 2026-11-03}; services/ui-api/routers/gold.py:3843-3846;
`shots/physical_P.png`. Fix: emit the CNY/g and USD legs of the SAME date (the pair's SGE leg in CNY/g when the premium is
the stored pair), or print the 4 Nov CNY/g alone with "USD leg awaits the 4 Nov LBMA PM"; never print "=" across dates.

**N2 · Header strip (every sub-view) — the MCX basis label is doubled (minor).** "basis +1.58 % at the at the Tue 03 Nov
settlement vs that session's duty-paid landed vs that session's duty-paid". The server's `strip.basis_session_label` (an
alias B3 added for HealthStrip) carries the full sentence "at the Tue 03 Nov settlement vs that session's duty-paid landed",
and HealthStrip.tsx:51,76 wraps it in its own "at the {basisSession} vs that session's duty-paid" template. Evidence:
`api/overview.json` strip.basis_session_label; DOM header of every view; `shots/health_P.png`. Fix: `basis_session_label`
should be the session only ("Tue 03 Nov settlement") or the UI should print `basis_label` verbatim.

**N3 · WEI line — "GOLD · STRONG WEEK, GOLD-SPECIF · basis +1.6 % …" (minor).** `health_line()` (gold.py:1136) slices the
headline to 24 characters, cutting the word. Evidence: `api/health.json` line. Fix: cut at a word boundary or allow 26.

**N4 · ui-api ignores the store's `partial` flag (minor, C-DATA-21 follow-up).** data-service marks GC=F 2026-11-04
`partial: true` (first_seen 21:40 UTC, 20 min before the 22:00 UTC winter close; the GCZ26.CMX bar fetched at 22:14 UTC
closes 4,072.2, not 4,070.8), but ui-api derives partial from `report_date >= today and comex_open` (gold.py:1245, 2203),
so the TREND tile "$4,070.80 ▲+4.41 % W", w.table "Wed 11-04 close 4,070.8" and /bars.settle_line "Wed 4 Nov close" are
printed as final with `last_bar_partial false`. Evidence: `api/ds_bars_gcf_1d.json` row 2026-11-04 partial true vs
`api/bars_1d.json` daily_closes[3].partial false. Fix: read `partial` from the store row and prefer it.

**N5 · HEALTH h.events / MACRO mc.calendar — the COT release is listed twice (minor).** "CFTC COT (positions as of Tue 03 Nov)"
(source rule+B10) and "CFTC COT release (Tue 03 Nov positions)" (computed_events, gold.py:4797) survive the dedupe because
their names differ; the same pair repeats for 17 Nov, 21 Nov and 1 Dec. Evidence: `api/calendar.json`, `api/overview.json`
calendar; DOM h.events (22 rows, two Sat 07 Nov 02:00 rows). Fix: dedupe on (date, time, kind).

**N6 · HEALTH h.open — the server verdict still prints an action rule (minor).** "WAITING FOR THE OPEN — Trade the open only
if MCX opens within ₹300 of ₹1,44,618." comes from /fair verdict.detail; the [B] copy above it now says "arithmetic to read,
not advice", so the card contradicts its own caption. Evidence: `api/fair.json` verdict.detail; DOM h.open. Fix: "MCX open
within ₹300 of ₹1,44,618 = inside the house rule; outside = outside" (a description, no imperative).

**N7 · Header strip — the same price twice (minor, §f.6).** "settle — $4,072.2 last Wed 04 Nov · Yahoo, not settlement" and
"last $4,072.2 ▲+3.28 % … 03:29 IST" print the matched month's per-month daily bar and the cached live last, which are the
same quantity from the same source. Evidence: `api/overview.json` strip.comex_matched_last 4072.2 = comex_live 4072.2. Fix:
show the daily-bar last only when it differs from the live last, else one number with both labels.

**N8 · /brief — trade-implying prose survives the key scrub (minor).** `scrub_trade_fields` removed `open_signal` keys
(stripped_fields lists them) but `doc.open_plan` still reads "Open signal is aligned_tradeable (deviation ~-100 vs a 300
threshold), so no wait is required …"; the panel does not render it today ("The document carries no summary, plan or risk
list"), so nothing shows. Evidence: `api/brief.json` doc.open_plan. Fix: strip `open_plan` or scrub the sentence.

**N9 · MACRO mc.drivers — GVZ changes in "bp" (minor).** "GVZ (GOLD VOL) 24.11% · 1d −171 bp · 1w +121 bp": the vol index
inherits the yields' bp rule (server change_unit 'bp' on a '%' level). A vol point is not a basis point to a reader. Fix:
change_unit 'vol pts' (or '%' of level) for GVZ_CLOSE.

Also noted, not scored: mc.ccy prints "₹123,851" in Western grouping while every other rupee on the page is lakh-grouped;
c.spec says "margin history: 0 dates stored" while the payload carries one row (2026-11-04, $19,848) beside the card's
$19,702 (PRF biz_date 2026-11-05) — two margins, one card; c.roll suffixes "LTD ends 12:30:00 PM" to first-notice rows;
the 1m `settle_line` of /bars is the in-progress day's (partial) bar labelled "close" (the UI draws its own Tue 03 Nov line,
so nothing shows).

## 3. "not stored yet" / "no verdict" on the live page — expected?

- "no verdict — not published": 0 occurrences in any view (p.asia hidden in the release build). ✓
- d.sge "No SGE bars stored for today yet": expected at 03:50 (SGE hours 06:30–13:00 / 17:30–00:00 IST).
- d.quadrant / p.daily.comex "no OI for this session · ΔOI not stored" for Tue 03 Nov: expected — the 3 Nov CME file is in
  (GC OI 400,666) but the delta needs the 2 Nov row, missing from the 31 Oct–4 Nov controller outage; a T+1 row for 4 Nov
  lands ≈ 15:30 IST today.
- ph.shanghai "awaiting the LBMA PM of Wed 04 Nov": expected (LBMA/WGC rows wait on O-1 and the next refresh).
- ph.otc "20-d avg —" and p.daily.comex "average from 5 sessions (1 stored)": expected until five sessions accrue.
- c.spec "margin history: 0 dates stored": not quite — one row is stored (see above); expected to stay below the three-date
  sparkline threshold until the CME VOI/EFRP/PRF histories run after 10:00.
- m.liquidity "too few for a percentile" (13–14 obs. since 2025-10): expected under the 60-observation gate.
- h.open shows the pre-open card: expected before 09:15 IST; the after-09:15 states (C-TRADER-14) were not retested.
- Nothing on the page is blank where the store has data: the dollar tile, GLD Δ column, ₹/basket ladder columns, KGX split,
  six-currency table, USD/INR and ATR14 tiles are all filled from the now-routed series ids.
