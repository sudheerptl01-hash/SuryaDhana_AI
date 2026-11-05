# C-TRADER-2 — GOLD page re-review after wave 1c (UI release 20261105-034204, walked Thu 5 Nov 2026 03:49–03:55 IST)

Same critic as C-TRADER (fifteen years of gold on a Bloomberg terminal). Hour: pre-MCX (opens 09:00, "MCX opens in 5h09m"),
COMEX in its 17:00–18:00 ET maintenance hour, last 1-min bar 03:14 IST, CFTC 27 Oct report still current (next Sat 7 Nov
02:00 IST). Method as before: every sub-view opened headless (Chromium 1440×900, read-only prefs, [B] and [P] layers),
every `/api/gold/*` body pulled once (GET only, ≤ 2/s, `evidence/*.json`), cross-checked against the data-service store
(`/db/gold/*`, `evidence/ds_*.json`) and against each other. Screenshots `shots/<sub>_{b,p}.png` (full) and
`shots/<sub>_{b,p}_vp.png` (viewport); page text dumps `evidence/text_<sub>_{b,p}.txt`; glossary-term counts per view
`evidence/terms.log`. Console errors 0, failed requests 0 on all nine views in both layers (`evidence/shoot_{b,p}.json`).

## Executive summary

**Verdict: PUBLISH-WITH-FIXES. Score 7.0 / 10** (was HOLD 4.5). Every one of my six blockers is closed on the live
page with the critic's own evidence re-run, and 12 of my 13 majors are closed; the one not closed (C-TRADER-14, the
post-09:15 behaviour of TODAY'S OPEN) cannot be tested at this hour — the pre-open copy it shows now ("WAITING FOR THE
OPEN") is the right copy for 03:50. The page now answers the brief's seven questions (see below), and the honesty rules
hold everywhere I looked: badges on every panel, no composite, context never coloured, "DESCRIBES, DOES NOT PREDICT"
closes the verdict, [P] shows rule id · series · value · threshold per clause, the strip shows the settlement clock
(basis_clock `settlement`, `mcx_live` null, no cross-clock ratio anywhere).

What the round introduced or left: (1) the header strip's MCX cell prints its basis label twice ("basis +1.58 % at the
at the Tue 03 Nov settlement vs that session's duty-paid landed vs that session's duty-paid") on every view —
`HealthStrip.tsx:76` appends its own "at the … vs that session's duty-paid" around a server label that already contains
it; (2) the COMEX cell still leads with "settle —" before the per-month last, and prints $4,072.2 twice in one cell;
(3) the Wed 04 Nov GC=F daily bar is stored `partial: true` (fetched 21:40 UTC, before the 22:00 UTC Globex close) and
the HEALTH TREND tile, WEEKLY row, MONTHLY ladder and MACRO six-currency table all print its 4,070.8 as a finished close
while the strip prints 4,072.2 from the GCZ26 per-month bar (fetched after the close) — the API's
`gauges[TREND].last_bar_partial` is `false`, so the "partial" badge the round added never fires; (4) the WEI line
truncates the headline to "STRONG WEEK, GOLD-SPECIF" (`routers/gold.py:1136` `[:24]`); (5) the EVENT RISK strip and the
MACRO calendar carry two rows for the same COT release (data-service `ingest_cot.py:224` writes one into `gold_events`,
ui-api `routers/gold.py:4797` synthesises another); (6) small label things listed below. None of these changes a number
a trader would act on; all are a line each.

## Can a pro answer the brief's questions from the page now?

| Question | Answer from the page | Where |
|---|---|---|
| What happened this week and why | +4.4 % week to date since the Fri 30 Oct close (3,898.9 → 4,070.8); of which the dollar +0.3 % (DXY −0.35 % w/w), real yield +2 bp → GOLD-SPECIFIC by the H2 rule (usd share 0.35/4.41 < 0.4); headlines: midterms, Warsh sworn in, Iran de-escalation, oil down | HEALTH verdict, gauges, headlines; MACRO kgx "+3.31 %: +3.06 % gold, +0.25 % the dollar; rupee −0.10 %" |
| Who did what | 27 Oct COT: funds +1,538 L / +182 S, net +1,356 on a −1.64 % week → "funds bought the dip"; other reportables closed 14,956 longs; swap dealers covered 12,256 shorts; small specs added 3,759 shorts; OI −5,469 to 396,810 (20th all-history pct). Released Sat 31 Oct 01:00 IST, next Sat 7 Nov 02:00 IST | POSITIONING hero + who-is-long bars, WEEKLY w.whodid |
| What got closed | COMEX product OI 400,666 on 3 Nov with no Δ yet (CME history starts 3 Nov; 2014→ backfill scheduled ≥ 10:00 today) — the page says so ("no OI yet… lands T+1 ≈ 15:30 IST"); MCX GOLD ΔOI +863 over 3 sessions (29 Oct → 3 Nov, labelled) = short build-up | DAILY/POSITIONING quadrants |
| Physical premium | IBJA 999 PM −0.71 % vs duty-paid at the Tue 3 Nov fix minute (one number, stored); Shanghai −$1.55 (−0.04 %) on the last same-date pair (3 Nov), "awaiting the LBMA PM of Wed 04 Nov"; WGC survey lines $2.9 (India) / $6.7 (China) | PHYSICAL ladder, ph.india, ph.shanghai; HEALTH gauges agree (−0.71 is not shown on HEALTH; INDIA BASIS 1.58 % is) |
| Curve / roll | COMEX Dec→Feb +32.8 = +0.81 % = 5.2 %/yr (×365/57 ✓), full strip to DEC-27 all 4.4–5.6 %/yr; GC DEC-26 FND Mon 30 Nov (25 d), LTD Tue 29 Dec; MCX DEC-26 → FEB-27 +2,740 = 11.3 %/yr (1,180 lots) | CONTRACTS c.comex, c.spec, c.mcx; HEALTH H5 |
| Event risk tonight | Thu 19:00 IST claims (Medium), 19:20/19:40 Hammack/Barkin (Low, not starred), 23:30 MCX GOLDM Nov-26 expiry; tomorrow 19:00 NFP / unemployment / AHE ★ High in session; Dhanteras Fri; Sat 02:00 COT; next FOMC decision Wed 16 Dec (00:30 IST Thu, after the MCX close) | HEALTH h.events (22 rows, whole week), MACRO calendar + fed |
| Which MCX contract and its roll | GOLD DEC-26 (1 kg, ₹100/tick, round trip ₹2,457 = 0.018 %, NRML margin ₹12.9 lakh), OI 16,282 vs FEB-27 1,180 (ratio 13.8); tender from Tue 1 Dec (26 d), expiry Fri 4 Dec; hedge ≈ 32.15 oz/lot | CONTRACTS selector + ladder; POSITIONING p.daily.mcx |

Yes — with the caveats that the funds' answer is nine days old by construction (COT), "what got closed" on COMEX waits
on the CME history, and the India premium is Tuesday's fix (IBJA's 13:45 / 18:10 fixes today will refresh it).

## Sub-view scores (0–10, "faster than Bloomberg?")

| Sub-view | Was | Now | One line |
|---|---|---|---|
| HEALTH | 4 | 7 | verdict, driver word, dollar tile, whole-week events, brief fields all right; strip label doubled, "settle —" prefix, partial Wed bar unflagged, duplicate COT rows |
| DAILY | 2 | 7.5 | zone fixed (rally plotted 18:00–20:00 IST = London/NY morning), legend closes from daily bars, dashed line = Tue 3 Nov close 3,940.40, MCX Δ "over 3 sessions"; SGE tile honest (OFFLINE + link) |
| WEEKLY | 6 | 7 | table / grid / verdict agree on +4.41 %; GLD Δ filled; duplicate Mon/Tue volume marked "?"; Wed close 4,070.8 is a partial bar printed as final |
| MONTHLY | 5 | 7 | ladder's ₹ and DXY columns filled; official net-purchase bars in tonnes; percentiles hidden < 60 obs; "as of Wed 01 Jul" on the net-purchase header is the oldest country's month |
| POSITIONING | 6 | 8 | driver "funds bought the dip"; Western grouping; all-history percentiles; FND 25 d / tender 1 Dec; "long unwinding" under the fund-driver label is the OI quadrant, unlabelled |
| PHYSICAL | 3 | 7.5 | one premium per clock (−0.71 % at the fix; basis +1.58 % at the settlement); Shanghai same-date pair with the pending note; official table in Moz/t with BRA 5.54 Moz = 172 t; RBI from the IMF row; OTC "$964.2 bn · week ending" |
| MACRO | 5 | 7 | real DXY 101.52 labelled DXY; kgx identity holds; six currencies filled; next FOMC = 16 Dec decision; "00:30 ISTAFTER MCX CLOSE" spacing; Dec hike 85 % has no ZQ cross-check on the page |
| CONTRACTS | 6 | 8 | DES card GC DEC-26 (202612) with FND 30 Nov / LTD 29 Dec; FND marked on the curve; carry columns agree between ladder and chain; one landed / duty-paid rupee shared with PHYSICAL and HEALTH |
| LEARN | 8 | 8.5 | routines in plain words with the view link per step; START HERE (12 terms); glossary 160 terms with 272 aliases (w/w, percentile, z-score, new shorts, bought the dip all findable); basis entry now names the MCX definition |

## Re-test of my findings (C-TRADER-1 … 28) against the live page

| Ref | Sev | Status | Evidence now |
|---|---|---|---|
| C-TRADER-1 | blocker | closed | `/db/gold/bars?symbol=GC=F&interval=1m` last ts `2026-11-04T21:44:20+00:00` (offset present); DAILY axis "IST / NY" 06:00…04:00, tape "03:10 16:40 · 4,070.10" at 03:51 IST (= 16:40 EST ✓); the +3.3 % rally sits in the London/NY-morning bands; CME maintenance hatched 03:30–04:30 IST. `shots/daily_b.png` |
| C-TRADER-2 | blocker | closed | legend "Mon 02 Nov close (Yahoo daily, not settlement) 3,969.60 ▲70.70 (+1.81 %) · Tue 03 Nov close 3,940.40 ▼29.20 (−0.74 %) · Wed 04 Nov last 4,070.10" = stored daily bars (`ds_bars_gc_1d.json`) and the WEEKLY table |
| C-TRADER-3 | blocker | closed | `/api/gold/cot` `driver_label` "funds bought the dip", `driver_rule` text served; HEALTH H3 "funds +1.3 % w/w (bought the dip)", POSITIONING hero, WEEKLY w.whodid; `/db/gold/cot` agrees. "new shorts" appears only in LEARN (the rule's six words) |
| C-TRADER-4 | blocker | closed | `/api/gold/premiums` india.premium_pct −0.71, premium_date 2026-11-03, premium_clock "IBJA PM fix minute: both legs sampled at the fix (stored INDIA_PREMIUM_PCT)"; ladder prints "IBJA premium vs duty-paid −0.71 % · Tue 03 Nov, both legs at the IBJA fix minute". `shots/physical_b_vp.png` |
| C-TRADER-5 | blocker | closed | shanghai.pair_date 2026-11-03, premium_usd −1.55 (−0.04 %), note "awaiting today's PM: SGE Wed 4 Nov is in, its London PM is not stored yet"; page: "SGE Wed 04 Nov · reference Tue 03 Nov — … no premium is divided across them"; HEALTH tile −$1.55 (same number) |
| C-TRADER-6 | blocker | closed | `/api/gold/flows` official: USA oz 261,499,000 → oz_mn 261.499 → tonnes 8,133.5; POL 21.63 Moz / 673 t; BRA 5.54 Moz / 172 t (`/db/gold/series IMF_GOLD_OZ_BRA` every month 5,544,278 oz, quality `rescaled_x1000` — the mixed-scale history the B1 re-check feared is gone after the imf re-run); table sorted USA first; rendered once (PHYSICAL), MONTHLY keeps the net-purchase bars |
| C-TRADER-7 | major | closed | dollar leg present: gauges[DOLLAR] 101.523 ▼−0.35 % W (state delayed, not unavailable); H2 clause value 0.35 vs usd_share 0.4 × 4.41 → GOLD-SPECIFIC is now a tested claim |
| C-TRADER-8 | major | closed | `/api/gold/series?ids=DXY_CLOSE,USDINR_CLOSE,GLD_TONNES,FX_EURUSD,GOLDBEES_CLOSE` 276 / 284 / 275 / 284 / 269 points; MACRO "DOLLAR INDEX (DXY) 1d −0.34 % · 1w −0.65 %" = DX-Y.NYB (no DTWEXBGS fallback; "121.67" absent); kgx and six-currency table filled; MONTHLY ladder ₹ and DXY columns filled |
| C-TRADER-9 | major | closed (residual nit) | `/db/gold/bars?symbol=GCZ26.CMX&interval=1d` 4 rows; strip `comex_matched_last` 4,072.2 "last trade (Yahoo per-month daily bar), not a settlement"; "NO DATA" absent on all views. Residual: the cell still opens with "settle —" and prints $4,072.2 twice (new finding 2) |
| C-TRADER-10 | major | closed | strip `mcx_shown` settlement, `mcx_live` null, `basis_pct` 1.58 = `basis_settle_pct`, `basis_clock` settlement; fair.basis_pct (model, 1.5) is no longer printed on any view; the B3/B4A re-check's out-of-hours cross-clock regression does not reproduce at 03:50 (no Breeze quote cached: `quote.available` false) — the in-hours case is not testable now |
| C-TRADER-11 | major | closed | h.events "22 rows", sorted High → Medium → context → Low; Fri 06 Nov 19:00 ★ NFP / Unemployment Rate / AHE (High); Hammack/Barkin Low, no ★; [B] "the whole week, nothing cut off" |
| C-TRADER-12 | major | closed | `/api/gold/macro` fed.next_fomc {date_et 2026-12-16, name "FOMC statement", kind FOMC}; page "next FOMC 2026-12-17 00:30 IST" (spacing defect carried, see C-TRADER-25) |
| C-TRADER-13 | major | closed | comex_spec mmy 202612 "picked_by matched month", first_notice 2026-11-30 (25 d), last_trade 2026-12-29; `/db/gold/cme/calendar?symbol=GC` 35 rows (GC 202612 FND 30 Nov ✓); `/db/gold/events` COMEX_FND/LTD/FIRST_INTENT rows; roll calendar shows "Mon 30 Nov COMEX GC 2026-12 first notice day"; POSITIONING "25 days to FND (Mon 30 Nov)"; margin rows < $1,000 dropped (one $19,848 row) |
| C-TRADER-14 | major | not-retested | at 03:50 the panel reads "WAITING FOR THE OPEN · Trade the open only if MCX opens within ₹300 of ₹1,44,618" with `desk_verdict_state` AWAITING_OPEN — correct for the hour; the ≥ 09:15 branch ("this morning's call" / "no snapshot today") and the re-armed 08:45 / 09:10 jobs can only be judged after 09:15 today (`/api/gold/log` still ends 30 Oct: no rows 3–4 Nov; 5 Nov not yet due) |
| C-TRADER-15 | major | closed | `/api/gold/brief` top-level bias "neutral", confidence 0.45; panel "automated brief · bias neutral · confidence 45 %"; `open_signal` not rendered ("no open signal is shown here") |
| C-TRADER-16 | major | closed | verdict "gold +4.4 % week to date (since the Fri 30 Oct close)", window_label on every tile; WEEKLY "week +4.41 %" and the 02 Nov grid row "+4.4 %" — one week, one number |
| C-TRADER-17 | major | closed | dashed line labelled "Tue 03 Nov close (Yahoo daily, not settlement) 3,940.40" (`shots/daily_b.png`) |
| C-TRADER-18 | major | closed | `/api/gold/positioning/daily?exchange=MCX` rows carry `sessions_spanned` 3, quadrant_tape `span_note` "over 3 sessions (master skipped 2)"; DAILY and POSITIONING print "Δ over 3 sessions (rows missing between)" |
| C-TRADER-19 | major | closed | one landed ₹1,23,894 and one duty-paid ₹1,42,478 on PHYSICAL, CONTRACTS footer ("the same rupee as HEALTH and PHYSICAL") and `/api/gold/overview` fair; the official table is on PHYSICAL only; GLD 1,037.7 t once per view. Residual: the COMEX last appears as 4,070.8 / 4,072.2 (new finding 3) |
| C-TRADER-20 | minor | closed | "+105,562", "396,810", "400,666" in Western grouping on every view; rupees stay Indian |
| C-TRADER-21 | minor | closed | OTC "$964.2 bn · week ending Fri 16 Oct"; EFP "3,141 round turns · Tue 03 Nov · 20-d avg —" with `avg_note` "average needs 5 prior sessions; 0 stored since Tue 3 Nov" served (the page prints the dash, not the note — cosmetic) |
| C-TRADER-22 | minor | closed | "RBI GOLD SHARE OF RESERVES 14.3 % · tonnes: the IMF IND row above"; IND 28.31 Moz / 881 t; no price-implied estimate |
| C-TRADER-23 | minor | closed | "gold / M2: 0.174 · 14 months since 2025-10 — too few for a percentile" (all five context ratios) |
| C-TRADER-24 | minor | closed | curve axis "days to last trade · a long leaves by FND (25 d)"; points carry first_notice / days_to_fnd |
| C-TRADER-25 | minor | still-open | HEALTH "GLD −2.9 t on the day · DESCRIBES" spaced now, but MACRO prints "next FOMC 2026-12-17 00:30 ISTAFTER MCX CLOSE · gap risk at 09:00" (`MacroView.tsx:193` Chip with no leading separator) |
| C-TRADER-26 | minor | closed | SGE tile shows "OFFLINE · No SGE bars stored for today yet — the asia job writes them during SGE hours" plus the link tile; "NOT PUBLISHED" absent |
| C-TRADER-27 | minor | closed (partly) | GLD Δ t column filled (−1.14 / −2.85); Mon/Tue COMEX volume still 172,512 both days but Tuesday's is marked "?" with the stale-partial tooltip; the re-fetch is the 03:10 job's |
| C-TRADER-28 | minor | closed | "26 days to tender · tender from Tue 01 Dec (computed; the MCX circular is the legal source)", `days_unit` "calendar days", `tender_start` 2026-12-01 |

### Other critics' blockers/majors my evidence covers (same live run)

closed: C-BEGINNER-1/2/3/4/5/6/7 (glossary terms now on every view: HEALTH 17, DAILY 3, WEEKLY 4, MONTHLY 6,
POSITIONING 7, PHYSICAL 3, MACRO 4, CONTRACTS 9, LEARN 2 — `evidence/terms.log`), C-BEGINNER-8 (routines in words with
a view link per step), C-BEGINNER-10 (START HERE · 12 terms), C-BEGINNER-11 (aliases: "w/w", "percentile", "z-score",
"new shorts", "bought the dip" resolve), C-BEGINNER-12 (glossary "basis" names the MCX definition), C-BEGINNER-14/15/16;
C-DATA-1 … C-DATA-16 all closed on the evidence above (C-DATA-7: "▼−$76.89/oz W"; C-DATA-13: WAITING FOR THE OPEN with
`AWAITING_OPEN` and the BRF line "fair ₹144,618 (gap +4,432)" — one state; C-DATA-14: "percentile 50 · all-history
percentile (1986→, data-service)"; C-DATA-16: ladder and chain both +11.3 % on FEB-27). Not retested: C-BEGINNER-9 (the
"only [B] copy" toggle), C-BEGINNER-13 — see finding 6 (the action sentence is still printed). C-DATA-17: the p.asia
panel is no longer rendered, but `/api/gold/series?ids=SGE_AUTD_OI` returns 0 points while `/db/gold/series` has 1
(2026-10-30, 252,006 kg) — finding 8.

## New / residual findings (ranked)

| # | Sev | Sub-view · panel | Issue | Evidence | Fix |
|---|---|---|---|---|---|
| 1 | minor | all views · header strip (MCX cell) | basis label printed twice: "basis +1.58 % **at the at the** Tue 03 Nov settlement vs that session's duty-paid landed **vs that session's duty-paid**" | `shots/health_b_vp.png`; `/api/gold/overview` strip.basis_session_label already = "at the Tue 03 Nov settlement vs that session's duty-paid landed"; `ui/components/gold/HealthStrip.tsx:76` wraps it in "at the {basisSession} vs that session's duty-paid" | print the server label verbatim; keep the local wrapper only when `basis_session_label` is null |
| 2 | minor | all views · header strip (COMEX cell) | cell opens "settle — $4,072.2 last Wed 04 Nov · Yahoo, not settlement" then "last $4,072.2 ▲+3.28 % … 03:29 IST": the dash reads as "no settlement" and the same number is printed twice in one cell (§f.6) | strip `comex_matched_settle` null, `comex_matched_last` 4,072.2, `comex_live` 4,072.2 | when the settle is null show one line "last $4,072.2 (Yahoo per-month, not settlement) · Wed 04 Nov · +3.28 % vs the pre-close ref"; add "settle: bulletin (O-2)" as a sub-label, not a dash |
| 3 | minor | HEALTH TREND · WEEKLY w.table · MONTHLY m.ladder/m.liquidity · MACRO mc.ccy | the Wed 04 Nov GC=F close is stored `partial: true` (first_seen 21:40 UTC, 20 min before the Globex close) and prints as 4,070.8 everywhere a "close" is read, while the strip prints 4,072.2 from the GCZ26 bar fetched after the close — one contract, two closes, no "partial" badge (`gauges[TREND].last_bar_partial` is `false`) | `ds_bars_gc_1d.json` 2026-11-04 partial true close 4,070.8; `ds_bars_gcz26.json` 2026-11-04 partial false close 4,072.2; `health_W.json` TREND last_bar_partial false | ui-api: derive `last_bar_partial` from the bar row's `partial`, not from the clock; B2: move yahoo_daily to 03:40 as the B1 note asked, or let the matched-month bar be the front's close when GC=F = GCZ26 |
| 4 | minor | WEI card (HEALTH `lines.wei`) | headline cut to "STRONG WEEK, GOLD-SPECIF" | `health_W.json` line "GOLD · STRONG WEEK, GOLD-SPECIF · basis +1.6 % …"; `routers/gold.py:1136` `[:24]` | widen to the full headline (≤ 32 chars) or cut at a word boundary |
| 5 | minor | HEALTH h.events · MACRO mc.calendar | the same COT release listed twice at Sat 07 Nov 02:00: "CFTC COT (positions as of Tue 03 Nov)" (gold_events, `ingest_cot.py:224`) and "CFTC COT release (Tue 03 Nov positions)" (synthesised, `routers/gold.py:4797`); repeats for 17 Nov, 21 Nov, 1 Dec | `calendar_30.json` rows 19–20, 23–24, 25–26, 37–38 | dedupe by (date, kind COT_RELEASE) in the router; prefer the stored row |
| 6 | minor | HEALTH h.open | "Trade the open only if MCX opens within ₹300 of ₹1,44,618." is still an instruction, under a [B] line that now says the rule "has missed by ₹1,360 on a typical morning and is worse than 'open = yesterday's settlement'" | `text_health_b.txt`; C-BEGINNER-13 | "The house chase limit is ₹300 around ₹1,44,618 (unproven: 0 % within limit over 6 days)" — a statement, not an imperative |
| 7 | minor | POSITIONING p.hero | under "FUND-DRIVER LABEL funds bought the dip" the sub-line reads "week price −1.64 % · long unwinding" — that second word is the exchange-OI quadrant (OI −5,469 on a down week), not the funds; two driver words in one tile with no label | `cot_52.json` quadrant_label "long unwinding", driver_label "funds bought the dip" | "OI quadrant: long unwinding (OI −5,469)" |
| 8 | minor | ui-api /api/gold/series | `SGE_AUTD_OI` returns 0 points via ui-api while data-service serves 1 (2026-10-30, 252,006 kg); SGE_AUTD_DIRECTION / SHFE_AU_FRONT_OI not checked | `series_ui.json` vs `ds_series_fx.json` | check the ui-api window / catalog gate for the three Asia ids (C-DATA-17 render path) |
| 9 | minor | MACRO mc.fed | Dec 16 "hike 85 % · 414 bp" against EFFR 3.88 % and a 3.75–4.00 % target rests on one source (Atlanta Fed tracker, as of Mon 02 Nov) with no ZQ Dec/Jan implied on the page to cross-check (ZQ shows NOV-26 3.88 % only); a trader reading an 85 % hike wants the futures strip beside it | `macro_D.json` fed.meetings[0], zq | store ZQZ26 / ZQF27 in yahoo_daily and print "ZQ implied DEC-26 x.xx %" next to the tracker; or label "tracker only, unverified" |
| 10 | minor | HEALTH gauges (SHANGHAI) | "▼−$76.89/oz W" is measured from the Fri 30 Oct pair (+$75.34), which the panel's own note calls an artefact on a big day (SGE PM 14:15 Beijing vs LBMA PM 15:00 London on a −3.3 % Friday); the weekly Δ is dominated by that timing spike | `premiums_365.json` shanghai.history 30 Oct +75.34, 2 Nov −50.53, 3 Nov −1.55 | show the level and a 5-pair median, or the Δ vs the previous same-date pair |
| 11 | minor | MONTHLY m.official · CONTRACTS c.spec | "OFFICIAL SECTOR · NET PURCHASES … as of Wed 01 Jul" takes the oldest country's data month (USA 2026-07) as the panel date while 15 of 19 rows are 2026-09; COMEX spec card's freshness chip reads "LIVE · ICICI MCX SECURIT…" for a CME PRF-sourced card | `text_monthly_b.txt`, `text_contracts_b.txt` | panel date = max data month; chip source = "CME PRF (FTP) · Thu 05 Nov" |
| 12 | minor | MACRO mc.fed | "00:30 ISTAFTER MCX CLOSE" (C-TRADER-25 carried) | `MacroView.tsx:193` | leading " · " |

## Cross-checks re-run

- **Week.** GC=F Fri 30 Oct 3,898.9 → Wed 4 Nov 4,070.8 = +4.41 % (HEALTH, WEEKLY table, WEEKLY grid "02 Nov +4.4 %"
  all agree). Using the GCZ26 bar (4,072.2) it would be +4.44 % — the 0.03 pp is finding 3.
- **Driver word.** ΔL +1,538, ΔS +182, net +1,356 > 0 on a −1.64 % week → "funds bought the dip" by the served rule ✓.
  OI identity still 396,810 both sides; group Δs = CFTC change fields.
- **Dollar / H2.** DXY 101.523, w/w −0.35 % → usd effect +0.35 % < 0.4 × 4.41 → GOLD-SPECIFIC ✓; kgx D: 3.31 = 3.06 +
  0.25 ✓ (identity holds, note null).
- **Basis.** MCX_BASIS_PCT 3 Nov = 1.58 % (settle 1,40,186 vs that session's duty-paid) — one clock, printed as 1.58 on
  the strip, PHYSICAL, CONTRACTS, HEALTH tile and "+1.6 %" in the verdict. The live-vs-landed figure is absent because
  there is no Breeze quote at this hour (`quote.available` false) — as it should be.
- **Fair open.** 4,072.2 × 94.63 ÷ 3.11035 = ₹1,23,894 landed ✓; × 1.15 = ₹1,42,478 ✓; fair 1,44,618 = 1,40,186 × (4,072.2
  / 3,942.8) × (94.630 / 94.740) = 1,44,614 ✓ (rounding); gap +4,432; "COMEX +₹4,600 · rupee −₹168" ✓.
- **Curve.** Dec 4,072.2 → Feb 4,105.0: +32.8 = +0.8055 %; × 365/57 = 5.16 %/yr ✓ (verdict "+5.2 %/yr", curve "+5.2
  %/yr", gauge 0.81 % — one rounding this time). MCX Dec→Feb +2,740 / 1,40,186 = 1.95 % over 63 d = 11.3 %/yr ✓.
- **Expected move.** GVZ 24.11 / √252 = 1.519 % ✓; × 4,072.2 = $61.9 (page $61.8, uses 4,070.8) ; × 1,40,186 = ₹2,129 ✓;
  per lot ✓.
- **Events.** FND 30 Nov − 5 Nov = 25 d ✓; MCX tender 1 Dec = 26 d ✓; GOLDM Nov-26 expiry tonight 23:30 ✓ (5th); FOMC 16
  Dec 14:00 ET = 17 Dec 00:30 IST ✓.
- **Official sector.** 261,499,000 oz / 32,150.75 = 8,133.5 t ✓; 5,544,278 / 32,150.75 = 172.4 t ✓.

## What the C-BEGINNER fixes did to readability (a trader's view)

Net positive and not in the way. Dotted glossary terms now sit in the [B] copy of every view (none on HEALTH before, 17
now) and are the words a junior actually trips on (managed money, duty-paid landed, bp vs pp, OI quadrants, FND / LTD,
loco London); hover gives the one-liner, click opens the dock; the pro layer is untouched. The routines panel reads as
a desk checklist now ("The header strip … then the verdict sentence … and the eight tiles") with a HEALTH › / MACRO › /
DAILY › link per step instead of panel ids — that is how I would brief a new hire. START HERE (12 terms in reading
order) is the right entry; the glossary search finds "w/w", "percentile", "z-score", "new shorts", "bought the dip"
through 272 aliases. The fund-driver entry quotes the six words and the rule. The only beginner-facing copy I would
still change is the imperative chase-limit sentence (finding 6).

## What works (keep)

Everything listed under "keep" in C-TRADER still stands, plus: the DAILY chart is now the quickest "when and where did
it move" read I know outside a Bloomberg GIP; the one-clock discipline on PHYSICAL (bars labelled now / fix /
settlement, every ratio naming its clock) is better than most bank notes; the EVENT RISK strip ordered by impact with
the whole week visible and speakers un-starred; the roll calendar with first intent / first notice / last trade per
product; the honest OTC / EFP / official-sector wording.

## Questions for the owner

1. TODAY'S OPEN after 09:15 today (C-TRADER-14): does the panel switch to the 08:45 snapshot vs the captured open, and do
   the 08:45 / 09:10 rows land for 5 Nov? `/api/gold/log` has nothing since 30 Oct.
2. Is the December FOMC "hike 85 %" what the Atlanta Fed tracker really says this week? The page cannot cross-check it
   without the ZQ Dec contract (finding 9).
3. The 03:10 yahoo_daily slot keeps storing a partial Wednesday bar every winter morning (finding 3); B1's 03:40
   suggestion is still open with B2.
