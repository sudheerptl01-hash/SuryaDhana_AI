# C-TRADER — GOLD page critique (UI release 20261104-230634, walked Wed 4 Nov 2026 23:51–23:57 IST)

Critic: fifteen years of gold on a Bloomberg terminal. Method: every sub-view opened headless (Chromium 1440×900, read-only
prefs, both [B] and [P] layers), every `/api/gold/*` body pulled once (GET only, ≤ 2/s), the numbers cross-checked against
the data-service store (`/db/gold/*`) and against each other. Screenshots: `shots/<sub>_{b,p}.png` (full page) and
`shots/<sub>_{b,p}_vp.png` (viewport). Raw JSON and page text dumps are in the scratchpad (`C-TRADER/*.json`, `text_*_b.txt`).

## Executive summary

**Verdict: HOLD. Score 4.5 / 10.** The frame is right — the honesty rules are honoured almost everywhere (badges on every
derived number, no composite, the verdict ends "describes, does not predict", [P] shows every threshold, the accuracy
log says WORSE than naive out loud) and no page crashes, no console errors, every planned panel renders. But a trader
cannot yet answer "what happened in gold this week and why, who did what, what got closed, where the premium is, what the
curve says, what hits tonight, which MCX contract and its roll" from this page alone, because several of the numbers that
would answer it are **wrong under their label**:

1. **DAILY is 5 h 30 min off.** data-service serialises UTC bar timestamps without a zone (`2026-11-04T18:05:00`);
   `ui/lib/gold/sessions.ts:153` hands that string to `new Date()` which parses it as browser-local (IST). The 24-h line
   ends at "18:05 IST" when the clock reads 23:49 IST, the tape prints "18:05 IST · 07:35 NY" for a 13:05 NY bar, and
   every session band (Shanghai/London/NY/MCX) is misaligned with the price path. The legend's "closes" are IST-day
   bucket ends, not settlements (Tue 03 Nov "close 3,949.80 ▲+0.32 %" vs the stored daily bar 3,940.4 ▼−0.74 %, which WEEKLY
   prints on the same page). The one view built for "when in the day and which centre" is unusable until this is fixed.
2. **The funds' driver label is wrong.** 27 Oct: managed money +1,538 longs, +182 shorts, net +1,356 on a −1.64 % week.
   The page (HEALTH verdict, POSITIONING hero, WEEKLY strip) says **"new shorts"**. The rule in
   `services/data-service/gold/cot_metrics.py:65` / `routers/gold.py:409` tests `ΔS > 0` before comparing magnitudes, so any
   down-week where funds add even one short is labelled "new shorts". The correct word by the rule's own intent is "funds
   bought the dip". The COT figures themselves are right (OI identity 396,810 holds on both sides; Δs match the CFTC change
   fields stored in `gold_cot`).
3. **Two premiums, both clock error, on the same page.** PHYSICAL ladder prints "IBJA premium vs duty-paid −3.94 %" (IBJA
   PM of Tue 3 Nov vs a duty-paid landed computed at 23:41 Wed after a +3.5 % day) while the HEALTH gauge prints the
   synchronised −0.71 % (3 Nov). Shanghai: PHYSICAL prints **+$109 (2.77 %)** (SGE Wed 4 Nov vs LBMA PM Tue 3 Nov) while
   HEALTH prints −$1.55 (3 Nov). The ladder panel's own footnote says a premium read across clocks is clock error — and
   then prints one.
4. **Official-sector table is wrong by 10⁶ and sorts Brazil above the USA.** `IMF_GOLD_OZ_*` is stored in ounces; the API
   labels it `oz_mn` and multiplies by 31.1035 for "tonnes" (`routers/gold.py:3253-3255`), so POL shows "2,16,34,000 Moz ·
   67,28,92,617 t" (true: 21.6 Moz · 673 t). The BRA series itself is 5.54 bn oz (true ≈ 4.2 Moz) — a unit fault in the
   ingest. Rendered twice (PHYSICAL `ph.official`, MONTHLY `m.official`).
5. **The dollar is missing where it matters and mislabelled where it appears.** `DXY_CLOSE`, `FX_*`, `USDINR_CLOSE`,
   `GOLDBEES_CLOSE` have no stored points, so the HEALTH dollar tile is OFFLINE, "Gold or the dollar?" is empty, "gold in
   six currencies" has one row, the return ladder's ₹ and DXY-basket columns are dashes — yet the verdict still says
   **"GOLD-SPECIFIC"** (the driver word defaults to it when the dollar leg is None, `routers/gold.py:884-900`). MACRO's
   driver strip quietly falls back to FRED DTWEXBGS (the Fed broad index, 121.67) under the label "DOLLAR INDEX (DXY)".
6. **The header strip's first number is blank** ("COMEX DEC-26 — settle — · NO DATA" next to a live price): there are no
   `GCZ26.CMX` daily bars in the store, so the matched-month settlement never renders. The MCX cell shows yesterday's proxy
   settlement (₹1,40,186) while the live Breeze quote (₹1,43,249) is on the same page in `h.open`; "basis vs duty-paid
   landed +1.5 %" is the model's fair value vs landed, not the market (live MCX vs landed = +0.4 %).
7. **Event risk omits the week's event and the roll.** `h.events` is capped at 14 rows (`HealthView.tsx:163`) so Friday's
   NFP (High) never shows while two "FOMC Member … Speaks" (Low) rows carry the ★. "next FOMC 2026-11-05 19:20" on MACRO
   is Hammack speaking, not a meeting. No COMEX GCZ26 FND (30 Nov) anywhere on HEALTH, POSITIONING ("— sessions to FND")
   or the CONTRACTS roll calendar (`gold_cme_calendar` is not in the store's table list); the DES card shows **GC 202611**,
   a contract already past first notice, with a margin-history sparkline built from a $25 row.

What a trader gets today: the COT "who is long / who is short" bars (correct, with the right gross changes per group),
the eight gauges with their rules, the COMEX term structure with correct spread/carry arithmetic (Dec→Feb +34.1 = +0.84 %
= 5.35 %/yr over 57 d; Feb→Apr 4.6 %; Apr→Jun 4.3 %; Jun→Dec 5.1 %), the MCX chain and selector cards (lot, tick,
round-trip, 1 % move, hedge ratio all check), the expected-move panel (GVZ 25.82 → 1.63 %/day → ₹2,280/10 g → ₹2,28,014
per GOLD lot), the weekly Mon–Fri table and 26-week grid, the ETF panel, and a LEARN section better than most desks' wikis.

## Sub-view scores (0–10, "faster than Bloomberg?")

| Sub-view | Score | One line |
|---|---|---|
| HEALTH | 4 | right shape, wrong driver word, blank settle, dollar gone, events truncated, brief blank, pre-open copy at 23:53 |
| DAILY | 2 | timezone shift breaks the chart, legend "closes" wrong sign, settle line = live last |
| WEEKLY | 6 | table and grid correct; GLD Δ column empty though stored; "week" in the verdict contradicts the grid (+0.7 % vs +4.6 %) |
| MONTHLY | 5 | candles and seasonality fine; official-sector units wrong; ladder ₹/DXY columns empty; "14th pct of 14 months" |
| POSITIONING | 6 | COT numbers verified; driver label wrong; lakh grouping on contract counts; FND "—"; MCX quadrant is a 3-session Δ labelled as a day |
| PHYSICAL | 3 | both premiums are clock error; official sector ×10⁶; OTC "bn/day" under "weekly"; EFP 20-d avg = today |
| MACRO | 5 | drivers fine; DXY mislabelled; KGX and six-currency panels empty; "next FOMC" is a speaker |
| CONTRACTS | 6 | selector and curve arithmetic correct; DES card on the wrong month; no GCZ26 FND; three different landed prints |
| LEARN | 8 | solid; glossary, routines and the health-rule table are what a junior needs |

## Cross-checks performed

- **COT 27 Oct (released Fri 30 Oct 19:30Z = Sat 31 Oct 01:00 IST).** Stored disaggregated futures-only row: MM 122,508 L /
  16,946 S / 40,502 spread → net 105,562; OR 101,216 / 20,327 / 19,853; SD 20,230 / 226,280 / 23,392; PM 20,487 / 30,061; NR
  48,622 / 19,449; OI 396,810. Long-side sum = short-side sum = 396,810 (identity holds). Δ vs 20 Oct: MM +1,538 / +182 (=
  stored `chg_mm_*`), OR −14,956 / −186, SD +2,493 / −12,256, PM +772 / −4,437, OI −5,469 — all as the `p.whois` chips
  print. The external check against cftc.gov could not be run under the GET-only rule (only :8010/:8001 allowed); the
  stored raw payload is the CFTC's own JSON, so the page = the store = the CFTC unless the ingest mis-mapped a column, and
  the identity test says it did not. Next release Sat 7 Nov 02:00 IST (EST) — correct.
- **Fair value.** 4,077.5 × 94.63 ÷ 3.11035 = ₹1,24,055 landed; × 1.15 = ₹1,42,663 duty-paid (matches). Fair 1,44,806 =
  settlement 1,40,186 × (COMEX now / COMEX ref) × (INR now / INR ref) — the +3.3 % gap is today's rally; fine as arithmetic.
  But the "basis +1.5 %" is fair ÷ duty-paid − 1, not the market: live MCX 1,43,249 ÷ 1,42,663 − 1 = **+0.41 %**.
- **Curve.** COMEX Dec 4,078.3 → Feb 4,112.4: +34.1 = +0.836 %; × 365/57 = 5.35 %/yr ✓ (header rounds to 5.3, CONTRACTS to
  5.4 — same number, two prints). MCX Dec 1,40,186 → Feb 1,42,926: +1.95 % over 63 d = 11.3 %/yr ✓ (a proxy on 1,180 lots).
- **Basis sign.** Positive = MCX above duty-paid landed ✓ throughout; the "−9.82 % carry-adjusted" on `/curve` is basis −
  annualised MCX carry, a quantity no desk uses — drop it.
- **Expected move.** 25.82/√252 = 1.627 % ✓; × 4,078.7 = $66.4 ✓; × 1,40,186 = ₹2,281 ✓; per lot ×100/×10/×1/×0.8/×0.1 ✓.
- **Week.** Daily bars: Fri 30 Oct 3,898.9 → Wed 4 Nov 4,078.7 = +4.6 % (the WEEKLY grid) — the verdict's "+0.7 % over the
  week" is a trailing five-session window (28 Oct 4,051.6 → 4,078.7). A −3.3 % Friday and a +3.5 % Wednesday became "FIRM
  WEEK".

## Findings (ranked)

| # | Sev | Sub-view · panel | Issue | Evidence | Fix |
|---|---|---|---|---|---|
| 1 | blocker | DAILY · d.24h, d.3day, d.tape | intraday bars plotted 5 h 30 early; axis/bands/legend wrong | `shots/daily_b.png`; store ts `2026-11-04T18:19:57` (naive UTC; maintenance gap at 22:00–23:00 proves UTC); tape "18:05 IST · 07:35 NY" at 23:53 IST; header "as of 23:39 IST" converts correctly | `ui/lib/gold/sessions.ts:153`: append `Z` to zone-less datetime strings; or emit `+00:00` from `services/data-service/gold/reads.py` bars |
| 2 | blocker | DAILY · d.24h legend | "Tue 03 Nov close 3,949.80 ▲+0.32 %" vs daily bar 3,940.4 ▼−0.74 % (WEEKLY table) | `DailyView.tsx:162-166` uses the last point of the IST-day bucket as "close" | legend closes from `gold_daily_bars` (settlement), label the bucket price "last" |
| 3 | blocker | HEALTH h.verdict · POSITIONING p.hero · WEEKLY w.whodid | funds driver "new shorts" on +1,538 L / +182 S, net +1,356 | `/api/gold/cot` groups[mm], driver_label; `cot_metrics.py:65`, `routers/gold.py:409` | down-week: compare magnitudes — `"new shorts" if ΔS > max(ΔL,0) else "funds bought the dip"`; mirror for up-week |
| 4 | blocker | PHYSICAL · ph.ladder | "IBJA premium vs duty-paid −3.94 %" is 3 Nov IBJA vs 4 Nov 23:41 landed; HEALTH gauge says −0.71 % | `/api/gold/premiums` india.premium_pct −3.95 (ts ibja 2026-11-03, landed 23:40:25); `routers/gold.py:3018-3024` | compute the ladder premium against the landed cost at the IBJA PM minute (stored `INDIA_PREMIUM_PCT`), print one number |
| 5 | blocker | PHYSICAL · ph.shanghai | "+$109 (2.77 %)" = SGE Wed vs LBMA PM Tue; HEALTH gauge −$1.55 (3 Nov) | `/api/gold/premiums` shanghai ts_sge 2026-11-04, ts_ref 2026-11-03; `routers/gold.py:3130-3141` | pair same-date SGE PM with same-date reference; otherwise show the stored `SHANGHAI_PREMIUM_USD` and say "awaiting today's LBMA PM" |
| 6 | blocker | PHYSICAL ph.official · MONTHLY m.official | Moz and tonnes ×10⁶; Brazil 5.54 bn oz sorted first | `/db/gold/series IMF_GOLD_OZ_BRA` 5,544,278,723 oz; `routers/gold.py:3253-3255` (`oz_mn = value`, `tonnes = value × 31.1035`) | divide oz by 1e6 before labelling Moz; tonnes = oz / 32,150.75; fix the BRA SDMX unit in `ingest_physical.py`; render the table once |
| 7 | major | HEALTH · h.verdict | "GOLD-SPECIFIC" asserted with the dollar leg unavailable | gauges[dollar].state unavailable; `_driver_word` returns GOLD-SPECIFIC when usd_effect is None (`routers/gold.py:884-900`) | omit the driver word when either leg is missing; say "driver unknown (dollar series offline)" |
| 8 | major | MACRO · mc.drivers, mc.kgx, mc.ccy · MONTHLY m.ladder · HEALTH dollar tile | DXY/FX/USDINR/GOLDBEES PUBLISH-CORE series have no points; MACRO falls back to FRED broad index under "DOLLAR INDEX (DXY)" | `/db/gold/series DXY_CLOSE` points []; `routers/gold.py:3422` fallback | fix the `yahoo_daily` job for DX-Y.NYB / FX pairs / INR=X / GOLDBEES.NS; label the fallback "Fed broad USD index (DTWEXBGS)" or hide it |
| 9 | major | header strip | "COMEX DEC-26 — settle — · NO DATA" beside a live price | `/db/gold/bars?symbol=GCZ26.CMX` count 0; `HealthStrip.tsx:40` | store per-month daily bars (the curve job already fetches GCZ26 last trade) and render "last 4,078.3 (Yahoo, not settlement)" rather than NO DATA |
| 10 | major | header strip · HEALTH india_basis | MCX cell shows yesterday's proxy settle and "basis +1.5 %" (model fair vs landed) while live MCX 1,43,249 is on the page; market basis +0.41 % | `/api/gold/health` fair.basis_pct 1.5 = 144,806/142,663 − 1; `h.open` MCX now 1,43,249 | when a Breeze quote exists, header = live MCX with settle beneath; basis = live MCX vs landed, labelled "vs Tue settle: +1.6 %" |
| 11 | major | HEALTH · h.events | 14-row cap hides Fri NFP (High); ★ on "FOMC Member Speaks" (Low) | `HealthView.tsx:163` `.slice(0, 14)`; `/api/gold/calendar` has NFP 06 Nov 19:00 High | sort by impact then time, show 7 days, ★ only impact High or FOMC decision |
| 12 | major | MACRO · mc.fed | "next FOMC 2026-11-05 19:20 IN SESSION" is Hammack speaking | calendar kind FOMC covers speakers; `routers/gold.py:3677` | next FOMC = next `FOMC_DECISION` row (9 Dec 2026); speakers are a separate kind |
| 13 | major | CONTRACTS · c.roll, c.spec · POSITIONING p.daily.comex · HEALTH curve tile | no GCZ26 FND (30 Nov) anywhere; "— sessions to FND"; DES card shows GC 202611 (FND 30 Oct, "5 d ago") with a $25 margin-history row | `/api/gold/contracts` comex_spec.mmy 202611; `/db/gold/meta` has no `gold_cme_calendar`; `routers/gold.py:2913-2918` picks the first GC row | run/verify the Sunday CME calendar job; write FND/LTD rows into `gold_events`; select the prf row whose mmy = matched month; drop margin rows < $1,000 |
| 14 | major | HEALTH · h.open | at 23:53 IST the panel still says "DON'T CHASE — WAIT … wait for the rupee's 09:00 open" and no 08:45/09:10 rows exist for 29 Oct–4 Nov | `/api/gold/log` last snapshot 28 Oct; controller log "down since 2026-10-31"; `desk_verdict_state NEED_PRICE` | after 09:15 switch to "this morning's call" or "no snapshot today (job missed)"; verify the 08:45 / 09:10 jobs re-armed after the outage |
| 15 | major | HEALTH · h.brief | panel prints "bias — · confidence —" though the brief has bias neutral, confidence 0.45; brief carries `open_signal: aligned_tradeable` | `/api/gold/brief`; `HealthView.tsx:187` | read the top-level fields; never surface a "tradeable" signal word on a context panel |
| 16 | major | HEALTH · h.verdict vs WEEKLY w.grid | "FIRM WEEK +0.7 %" is a trailing 5-session window; the calendar week is +4.6 % after a −3.3 % Friday | daily bars 30 Oct 3,898.9 → 4 Nov 4,078.7 | window W = Mon-to-date when the week has started; say "5-session" otherwise |
| 17 | major | DAILY · d.24h | the dashed "settlement" line is today's last trade (4,078.30), not the last settlement (3,940.4) | legend "DEC-26 last trade (Yahoo), not a settlement 2026-11-04 4,078.30" | draw the previous session's daily-bar close, labelled "Tue 03 Nov close (Yahoo)" |
| 18 | major | DAILY d.quadrant · WEEKLY w.table · POSITIONING p.daily.mcx | "Tue 03 Nov: short build-up · Δprice −2.45 % · ΔOI +863" is 29 Oct → 3 Nov (30 Oct, 2 Nov missing) | `/api/gold/positioning/daily?exchange=MCX` rows 2026-10-29 and 2026-11-03 only | label multi-session deltas "over 3 sessions" or grey them as the mechanical flag does |
| 19 | major | all | the same quantity printed with different values: landed ₹1,24,037 / 1,24,055 / 1,24,082 and duty-paid 1,42,642 / 1,42,663 / 1,42,695 (PHYSICAL, HEALTH, CONTRACTS); GLD 1,037.7 t on three views; official-sector table on two | text dumps `text_*_b.txt`; PLAN §f.6 | one fair block per page load (`/api/gold/overview`) feeding every view; drop the duplicate tables |
| 20 | minor | POSITIONING, header, WEEKLY | CFTC contract counts in lakh grouping ("1,05,562", "3,96,810", "4,00,666") while the verdict prints 105,562 | screenshots | contracts, ounces, tonnes and dollars in Western grouping; rupees in Indian grouping |
| 21 | minor | PHYSICAL · ph.otc | "LBMA WEEKLY TURNOVER (12-WK MA) $964.2 bn/day"; "CME EFP 20-d avg 3,141" equals today (one day stored) | `/api/gold/flows` otc | fix the unit; print "since 3 Nov" instead of a 20-d average with one point |
| 22 | minor | PHYSICAL · ph.official | "RBI tonnes est. 815 t" (value ÷ 3 Nov London PM) beside the IMF's 28.3 Moz = 880.6 t | same panel | use the IMF ounces; drop the price-implied estimate |
| 23 | minor | MONTHLY · m.liquidity | "gold / M2: 14th pct of 14 months" | text dump | hide a percentile with < 60 observations |
| 24 | minor | CONTRACTS · c.comex | x-axis "days to expiry" uses LTD (55 d) while a long must leave by FND (26 d) | screenshot | add FND ticks; the roll countdown should be to FND |
| 25 | minor | HEALTH · h.verdict | "GLD -2.9 t on the day· DESCRIBES" (missing space); "19:20IN SESSION" on MACRO | screenshots | spacing |
| 26 | minor | DAILY · d.sge | "NO VERDICT — NOT PUBLISHED" rendered in the release build | PLAN §f.2 says hidden in release | hide, or show the link tile |
| 27 | minor | WEEKLY · w.table | GLD Δ t column blank though 3 Nov −2.85 t is stored; COMEX volume identical Mon/Tue (1,72,512) | `/api/gold/flows` etf chg_1d; daily bars | join on report_date; re-fetch Tuesday's final volume |
| 28 | minor | POSITIONING · p.daily.mcx, p.drawer | "26 sessions to tender" are calendar days; MCX tender for GOLD starts on the 1st of the expiry month, not 5 sessions before; `identity_check` null | `/api/gold/positioning/daily` days_to_tender 26 | say "days"; tender_start = 1st of month per contract spec; run the identity check on the disagg fields |

## What works (keep)

- Rule discipline: badges everywhere, [P] layer shows rule id · series · value · threshold per clause, verdict suffix,
  crowdedness "not a signal", accuracy log reports the model is WORSE than naive, MCX settlement labelled PROXY and by
  session, Yahoo months labelled LAST TRADE, every number dated, sources attributed.
- POSITIONING `p.whois` and `p.decomp`: the correct way to show "who did what" — gross long/short per group with the
  closed/new chips; the since-the-low decomposition (funds −59,734 net, commercials +49,958, OI −139,171, GLD +167.7 t)
  is the single most useful COT table I have seen outside a bank note.
- CONTRACTS selector cards and the MCX chain: lot, tick value, round-trip cost, 1 % move, hedge ratio, tender and
  expiry dates — all correct, all on one screen; the diff strip idea is right.
- COMEX term structure arithmetic and labelling; MACRO expected-move per lot; the weekly Mon–Fri table and 26-week grid;
  the 3-day overlay design (once the zone is fixed); the ETF panel; LEARN.

## Questions for the owner

1. Is "week" on HEALTH meant to be the calendar week (Mon→now) or a trailing five sessions? Traders read the former.
2. May the header show the live Breeze MCX quote during MCX hours (it already appears in `h.open`), with the settlement beneath?
3. The CME calendar table (`gold_cme_calendar`) is absent from the store — did the Sunday 04:00 job ever run? FND/LTD rows depend on it.
4. The `yahoo_daily` job stores GC/GVZ but not DX-Y.NYB, INR=X, EURUSD=X, GOLDBEES.NS — a symbol-list gap or a 429 backoff?
5. The 08:45 snapshot and 09:10 capture have no rows since 28 Oct (controller outage 31 Oct); are they re-armed for 5 Nov?
