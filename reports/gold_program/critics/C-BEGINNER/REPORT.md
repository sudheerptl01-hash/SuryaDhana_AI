# C-BEGINNER — the GOLD page read by someone who has never traded a commodity

Critic id: C-BEGINNER · UI release 20261104-230634 at http://127.0.0.1:8010 (`?tab=gold`) · walked 4–5 Nov 2026, 23:53–00:05 IST ·
headless Chromium 1440×900 (Playwright), B layer on every sub-view, then P · read-only GETs only · screenshots in `shots/`
(`<sub>_B_viewport.png`, `<sub>_B_full.png`, `<sub>_P_full.png`, `panel_<id>.png`, `learn_*`, `health_window_*`, `contracts_family_*`).
Raw extraction (every panel's copy line, dotted terms, hover titles, glossary searches, window and family switches):
`/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/C-BEGINNER/walk.json`.

## Executive summary

**Verdict: PUBLISH-WITH-FIXES · learning path 6 / 10.**

The page never tells me to buy or sell, every verdict ends "describes, does not predict", every context number is grey, and every
panel has a plain [B] line and a dense, honest hover. The curriculum (LEARN) is the real thing: it starts with five numbers, defines
troy ounce, purity, venues, lot, margin, roll, COT, managed money, basis, real yield in that order, and Part 6 teaches the OI
quadrants, the week's driver, EFP and the India ladder. Nothing on the page forecasts.

Four things stop it being a safe teacher tonight, all "wrong word or number under a label", all small code fixes:

1. **The lesson the page is built around misfires.** POSITIONING prints `FUND-DRIVER LABEL · new shorts` directly above
   `new 1,538 longs / new 182 shorts` and `CHANGE ON THE WEEK +1,356`; the same "new shorts" sits in the HEALTH verdict in all three
   windows and in WEEKLY's one-liner. `driver_label()` (`services/ui-api/routers/gold.py:390-409`) can never say "funds bought the
   dip" when any new shorts exist. A beginner who has just read the panel's own [B] line ("a negative Δshort means they covered
   shorts") cannot reconcile the three numbers with the word.
2. **The India ladder prints a premium its own footnote calls clock error.** `IBJA premium vs duty-paid −3.93 %` is Tuesday's IBJA
   fix divided by *Wednesday 23:51's* duty-paid landed after a +3.4 % day; the stored fix-minute premium for 3 Nov is −0.71 %
   (`/api/gold/premiums india.history[-1]`). The hover says "inputs sampled at the IBJA fix minute" — not for this number.
3. **The official-sector table is off by a million.** `MOZ 2,16,34,000.00` (ounces), `TONNES 67,28,92,617` (grams), Brazil
   `5,54,42,78,723 Moz`, `PBOC LATEST 7,74,70,000.00 Moz`.
4. **The COMEX spec card describes the wrong contract.** It is GC Nov-26 (`mmy 202611`, "first notice Fri 30 Oct · 5 d ago") while
   the header, pickers and strip say the matched month is DEC-26 (GCZ26); its `TICK $1.00 = $100` contradicts the panel's own [P]
   line and the glossary (`$0.10 = $10`); `SETTLEMENT P`, `100 oz_tr` are raw codes.

Below those, the learning path has structural gaps: dotted glossary terms exist on only four of nine views (HEALTH, DAILY, WEEKLY,
MONTHLY and CONTRACTS have none — the verdict sentence alone uses nine undefined words), the LEARN reading routines are written in
panel-id shorthand (`h.open`, `mc.drivers`, `d.quadrant`), the glossary opens on "4GC" and lacks the words the page actually
uses most (w/w, bp, pp, percentile, z-score, Moz, "long liquidation", "new shorts", "MM"), the "only [B] copy" toggle strips just
20 % of the text (36 of 249 paragraphs are marked [P]; 15 sections have no [B] line), and 50 of 151 glossary entries print the
same sentence twice. Several panels show "—" with no reason (MONTHLY return ladder ₹ and basket columns, MACRO "Gold or the
dollar?", HEALTH DOLLAR tile "OFFLINE" while MACRO shows DXY 121.67).

## What works (keep it)

- No buy/sell anywhere; "describes, does not predict" on the verdict in D / W / M; context never coloured; `HEURISTIC · measured miss`
  on the chase limit; the accuracy log says "WORSE" than naive in plain sight. The honesty is the product and it is intact.
- The five-number health check (CURRICULUM §0) is the first thing LEARN shows and the header strip repeats it in the same order.
- [B] lines are genuinely plain on most panels: "every long has a short; swap dealers are the banks' hedge of the OTC and ETF book",
  "there is no COT for London", "contango (later months dearer) is the normal state for gold; backwardation is news", "how big a
  normal day is, in rupees per lot you trade".
- Hover tooltips are dense and dated: the quadrant cells explain themselves ("price down with new positions: sellers opened"), the
  seasonality cells show n, p10/p90 and the t-stat, every lag chip carries its as-of.
- The `?` about popover gives publisher · cadence · lag · verdict · evidence · terms per panel; the glossary has `see also` chains and
  151 terms with the project's own vocabulary (evidence badge, context, signal, point-in-time).
- The contract selector works as a novice would use it: GOLD → GOLDM → GOLDPETAL re-labels the strip, the expiry list carries OI, the
  cards print lot, tick, margin (dated), round trip, "1 % move = ₹" and the tender date; D / W / M re-words the verdict headline.
- 0 console errors, 0 failed requests, every sub-view and every panel rendered; term click opens the docked glossary on the right term.

## Findings (most severe first)

| # | Sev | Sub-view · panel | Issue | Evidence | Fix |
|---|---|---|---|---|---|
| 1 | blocker | POSITIONING · `p.hero` (echoed in HEALTH `h.verdict` H3, WEEKLY `w.whodid`) | "new shorts" printed as the week's fund driver while funds added 1,538 longs and 182 shorts (net +1,356, price −1.64 %) | `shots/positioning_B_viewport.png`, `shots/health_B_viewport.png`; `/api/gold/health` clause H3 text "funds net 105,562 (+1.3 % w/w, new shorts)"; `/api/gold/cot` hero; `services/ui-api/routers/gold.py:390-409` down-week branch `return "new shorts" if d_short > 0 else "funds bought the dip"` | `if d_short > 0 and d_short >= max(d_long, 0.0): return "new shorts"` then `return "funds bought the dip"` (mirror the up-week test); this week reads "funds bought the dip" |
| 2 | blocker | PHYSICAL · `ph.ladder` | `IBJA premium vs duty-paid −3.93 %` divides Tue 3 Nov IBJA PM by Wed 23:51 duty-paid landed; the fix-minute value stored for 3 Nov is −0.71 %; the hover ("inputs sampled at the IBJA fix minute") is false for the printed number | `shots/panel_ph.ladder.png`; `/api/gold/premiums` india.premium_pct −3.93 vs history[2026-11-03].premium_pct −0.71; `gold.py:3018-3024` (`ibja["value"] / (duty_paid * FINENESS_ADJ) - 1` with the live duty_paid) | print the stored `INDIA_PREMIUM_PCT` of `premium_date` ("−0.71 % · Tue 03 Nov, at the fix minute"); keep the live bars labelled "now" |
| 3 | blocker | PHYSICAL · `ph.official` | "MOZ" column shows ounces, "TONNES" shows grams; BRA row 5.5 bn; PBoC "7,74,70,000.00 Moz" | `shots/physical_B_full.png`; `/api/gold/flows` official[] `oz_mn: 77470000.0, tonnes: 2409586347.7` for CHN; `ui/components/gold/PhysicalView.tsx:67-69` renders raw | server: oz_mn ÷ 1e6, tonnes ÷ 1e6 (or label oz / g); exclude or flag BRA (unit error at source) |
| 4 | blocker | CONTRACTS · `c.spec` | card is GC 202611 (Nov) with "FIRST NOTICE Fri 30 Oct · 5 d ago" while the matched month is DEC-26; "TICK $1.00 = $100" vs [P] copy and glossary "$0.10 = $10"; "SETTLEMENT P", "100 oz_tr" | `shots/panel_c.spec.png`; `/api/gold/contracts?exchange=COMEX` comex_spec `{mmy 202611, min_px_incr 1.0, tick_value_usd 100, first_notice 2026-10-30}` vs `comex_matched_by_family.GOLD = GCZ26.CMX`; `ContractsView.tsx:243,292-309` | pick the PRF row by `comex_matched` (202612); apply the PRF display factor (0.1) to MinPxIncr; map P → "physical delivery", oz_tr → "troy oz" |
| 5 | major | PHYSICAL · `ph.ladder` | "MCX basis +1.50 %" sits beside bars 1,40,186 (Tue settle) and 1,42,625 (duty-paid now) which give −1.7 % by the panel's own [P] formula | `panel_ph.ladder.png`; `/api/gold/premiums` ladder steps `mcx.value 140186, duty_paid.value 142625, basis_pct 1.5` | label the clock: "basis +1.50 % at the Tue 03 Nov settlement vs that session's duty-paid"; [B] add "the two right-hand bars are yesterday's prices, the five on the left are now — do not divide across them" |
| 6 | major | HEALTH · strip + `h.gauges` | first number a novice meets: "COMEX DEC-26 — settle — NO DATA"; DOLLAR tile "— OFFLINE · No source is responding" while MACRO prints DXY 121.67 (Fri 30 Oct) | `health_B_viewport.png`, `macro_B_viewport.png`; PLAN a.1 "shows the last stored value + STALE + reason, never blank" | strip: "settle — (COMEX settlements arrive with the CME backfill; live last shown)"; tile: "121.67 · STALE Fri 30 Oct · FRED lags a week" |
| 7 | major | all views · dotted terms | glossary terms are underlined on 4 of 9 views only (HEALTH 0, DAILY 0, WEEKLY 0, MONTHLY 0, CONTRACTS 0; POSITIONING 4, PHYSICAL 1, MACRO 3, LEARN 2); the verdict sentence uses real yield, bp, funds net, w/w, India basis, duty-paid landed, roll, GLD, t undefined | walk.json `allTerms` per view; PLAN a.1 "a term's first appearance in a view has a dotted underline → glossary" | wrap first uses with `<Term t="…">` — HEALTH: real yield, basis point, managed money, duty-paid landed, roll, GLD, chase limit, fair open; DAILY: open interest, OI quadrants, settlement by session, roll; WEEKLY: COT, managed money, IBJA rate, GLD; MONTHLY: DXY, landed price, PBoC, SGE withdrawals, hit rate; CONTRACTS: lot, tick value, margin, notional, tender period, FND / LTD, contango, calendar spread |
| 8 | major | LEARN · `learn.routines` | routine steps are panel-id shorthand: "h.open: fair vs settlement, COMEX part vs rupee part (h.moved), the event-risk chip; decide OK/WAIT *before* 09:00" | `learn_B_viewport.png`; `ui/lib/gold/learn.ts` parseRoutines keeps ids as text | map ids to panel titles with the id in `title=`: "Today's open (HEALTH): fair value vs yesterday's settlement; how much of the gap is COMEX and how much the rupee; the event-risk chip. Decide OK / WAIT before 09:00 — the ₹300 limit is unproven." |
| 9 | major | LEARN · `learn.curriculum` "only [B] copy" | removes only the 36 `**[P]**` paragraphs (24 k of 120 k chars); 177 unmarked paragraphs (CFTC block anatomy, formulas, regime tables) remain; 15 sections have no [B] line (2.5, 4.2, 5.9, 6.4, 6.5, 6.8, 6.9, 6.10, 7.5, 7.7, 8.0–8.4) | CURRICULUM.md marker count; walk.json learn_onlyB | mark the pro paragraphs `[P]` (tables and code fences count as [P] when the filter is on); add one [B] line to each of the 15 sections |
| 10 | major | LEARN · glossary order | opens on "4GC", "995 vs 999", "accuracy log", "active month"; the dock after a term click lists 4GC second | `learn_B_viewport.png`, `positioning_term_click_glossary_dock.png` | pin a "start here" dozen above the alphabet when the box is empty: troy ounce, spot, futures, COMEX, MCX, open interest, COT, managed money, net position, basis, roll, real yield |
| 11 | major | LEARN · glossary gaps | zero hits for "w/w", "percentile", "z-score", "long liquidation", "new shorts", "what is gold"; "bp" → KGX only; "MM" → COT / DGCI&S; "Moz" → open interest; "OI" top-5 lacks open interest; "driver" → no fund-driver entry | walk.json glossary_search | add: w/w · d/d · m/m; bp vs pp; percentile; z-score; Moz; fund-driver label (the six words with their rule); India price ladder; T+1; an `aliases` field (MM → managed money, OI → open interest, FND → first notice day) |
| 12 | major | strip ↔ glossary "basis" | strip says "basis vs duty-paid landed +1.5 %"; glossary `basis` = "Futures minus spot (₹/10 g on MCX vs IBJA; $/oz on COMEX vs London)…", see_also lacks "MCX basis" | glossary.json | short → "The gap between a futures price and the reference it is compared with. On this page: MCX basis = MCX front settle ÷ duty-paid landed − 1 (%); on COMEX: futures − London spot in $/oz."; see_also + "MCX basis" |
| 13 | major | HEALTH · `h.open` [B] copy | "Within the chase limit → trade your plan; beyond it → wait … and recompute." is an action rule from a heuristic the same view scores "WITHIN ₹300 0 % · MODEL VS NAIVE WORSE"; the caveat is [P]-only | `panel_h.open.png` | [B] → "Where MCX 'should' open given COMEX and the rupee since the close. The OK / WAIT strip is a house rule (₹300) that has missed by ₹1,360 on a typical morning and is worse than 'open = yesterday's settlement' so far — arithmetic to read, not advice." |
| 14 | major | MACRO · `mc.kgx` | "pure gold —", "USD effect —", "total = pure + USD effect (identity off by more than 0.02 pp — check the inputs)" — a developer assertion shown to the reader; the panel the [B] line sells shows nothing | `macro_B_full.png`; walk.json macro mc.kgx text | when DXY is stale print "USD effect unavailable: DXY last Fri 30 Oct (FRED lags a week)"; hide the identity check |
| 15 | major | MONTHLY · `m.ladder` | "LANDED ₹/10 G" and "IN THE DXY BASKET" are "—" on all nine horizons with no reason, while [B] promises both | `panel_m.ladder.png` | one line: "₹ and basket columns fill as USD/INR and DXY daily history accrues (since 27 Oct 2026)" or hide until filled |
| 16 | major | POSITIONING · `p.asia` | raw ids "SGE_AUTD_OI · no verdict — not published" ×3 in the release build | `positioning_B_full.png`; PLAN §f.2 (dev shows placeholder, release hides) | hide, or show the catalog name with "awaiting verdict" |
| 17 | minor | LEARN · glossary | 50 of 151 entries have `long` == `short`, printed twice (e.g. "accuracy log") | build check; `GlossaryPanel.tsx` Entry | render `long` only when it differs; write real long lines for lot, multiplier, leverage, basis, backwardation, net position, short covering, long unwinding, non-reportable, other reportables, TIPS, GLD, FOMC, CPI / NFP |
| 18 | minor | HEALTH · strip / gauges / verdict | MM net appears three times in two formats ("+1,05,562" ×2, "105,562") | `health_B_viewport.png` | one formatter (Indian grouping) page-wide; verdict clause keeps only "+1.3 % w/w, …" |
| 19 | minor | MONTHLY `m.liquidity`, MACRO `mc.drivers`, POSITIONING `p.hero` | "93th pct", "43th pct", "52th pct", "92th pct", "14th pct of history"; "pct" means percent and percentile | walk.json texts | ordinal helper; write "percentile" |
| 20 | minor | MACRO · `mc.drivers` | tiles say "1d +0.02 pp", hover says "bp for yields", verdict says "−4 bp" — neither unit defined | `panel_mc.drivers.png` | one unit (bp) + glossary "bp / pp" |
| 21 | minor | HEALTH · `h.gauges` SHANGHAI PREMIUM | "−$1.55 ▲+47.36 % W": % change of a signed near-zero premium | `health_B_full.png` | show Δ in $/oz ("Δ +$1.4 W") |
| 22 | minor | glossary dock | Escape does not close it | walk.json term_click.esc_closes false | keydown Escape → close |
| 23 | minor | LEARN · corrections note + curriculum | "Part 8 panel names: Carry the PLAN panel ids…" and "the proposed GOLD header strip", "[APP] … which proposed panel it attaches to" are builder-speak | `learn_B_viewport.png`, `learn_B_front_part.png` | hide the note at [B]; "proposed" → "the GOLD header strip" |
| 24 | minor | DAILY · `d.quadrant` | "Tue 03 Nov: flat · Δprice −0.74 % · ΔOI —" calls a −0.74 % day "flat" because OI is missing | `panel_d.quadrant.png` | "no OI yet (CME file lands T+1 ≈ 15:30 IST)" |
| 25 | minor | HEALTH · strip label + INDIA BASIS chip | "COT MM NET" ("MM" undefined on screen); chip "LIVE · MCX SETTLEMENT (P…" truncated beside "Tue 03 Nov" | `health_B_viewport.png` | "COT funds net (managed money)"; chip "SETTLEMENT · PROXY · Tue 03 Nov" |
| 26 | minor | pickers · family switch | GOLDPETAL / GOLDM / TEN / GUINEA map to "COMEX NOV-26 · GCX26", a serial month the glossary calls illiquid; the strip shows "— settle —" for it | walk.json family_switch; `/api/gold/contracts` comex_matched_by_family | match to the nearest liquid month (Feb/Apr/Jun/Aug/Oct/Dec) and say "(nearest liquid COMEX month)" |

## The novice's walk, view by view

**LEARN first.** The routines panel is the first thing on the page and it is written in ids (`h.verdict`, `h.gauges`, `h.open`,
`mc.drivers`) — I did not know those were panels until I found the "Where each panel went" map at the bottom. The curriculum
itself is excellent in order and tone: Part 0 (five numbers) → Part 1 (troy ounce, purity, who holds what) → Part 2 (London, COMEX,
Shanghai, MCX, the rupee ladder) → Part 3 (lot, margin, contango, roll, basis/EFP) → Part 4 (the cast) → Part 5 (drivers) →
Part 6 (COT, quadrants, warehouse, ETF, OTC, premiums, term structure, vol) → Part 7 (advanced). The "only [B] copy" toggle
disappoints: Part 6.1 is a CFTC text block with twelve derived metrics and stays whole at [B]. The glossary on the right opens
on 4GC; typing "managed money" works, typing "MM" (the strip's own label) does not.

**HEALTH.** The verdict reads well as a sentence, but every noun in it is undefined on this view (0 dotted terms), and its COT
clause carries the wrong word (finding 1). The eight tiles have good one-liners ("The cost of holding gold: falling real yields
support gold"). The first strip number is "— settle — NO DATA" and the DOLLAR tile is blank. Today's open tells me "DON'T CHASE —
WAIT" in red at 23:59 with a limit the next panel says has been hit 0 % of the time.

**DAILY.** Readable: the dotted previous day and dashed settlement are explained in [B]; the quadrant matrix explains itself on
hover. "flat" with Δprice −0.74 % confused me (finding 24).

**WEEKLY.** Candles, Mon–Fri table and the heat grid are the easiest panels on the page. The one-line "who did what" repeats the
"driver: new shorts" contradiction.

**MONTHLY.** The seasonality grid's hover (n, p10/p90, t) is the best teaching device on the page; the return ladder has two empty
columns with no reason.

**POSITIONING.** The one-sentence lead ("Who is answered weekly by the CFTC … what got opened or closed is answered daily by exchange
open interest, which never says who") is exactly the lesson. The hero contradicts itself (finding 1). "Who is long / who is short"
bars with "closed … longs / covered … shorts" chips are clear. The crowdedness gauge is neutral and labelled "not a signal". The
drawer opens to trader counts, concentration, micro gold, the options line and the raw CFTC link — good, but "avg long 1,512"
has no unit and the three Shanghai rows print raw series ids.

**PHYSICAL.** The ladder is the right picture (COMEX → × USD/INR → landed → + duty → duty-paid → IBJA → MCX), each bar timestamped
and sourced; but the two derived numbers under it do not follow from the bars (findings 2, 5). The official-sector table is off
by a million (finding 3). The OTC window's [B] line ("there is no COT for London") is a model sentence.

**MACRO.** The driver strip's "SUPPORTIVE (falling = supportive, rising = headwind)" prints the rule beside the tag, which is
honest; "Gold or the dollar?" shows dashes and a developer message (finding 14). The expected-move panel in ₹ per lot is the most
useful arithmetic for an MCX novice.

**CONTRACTS.** The five family cards answer "which contract for which purpose" in one glance (tick, margin, round trip, 1 % move,
tender); the roll calendar counts down in words. The COMEX spec card is the wrong contract (finding 4).

## Exact copy changes requested (current → proposed)

- `p.hero` FUND-DRIVER LABEL (this week): "new shorts" → "funds bought the dip" (code fix, finding 1); [B] line add: "the label is the
  bigger of the two moves; when price fell and the net still rose, funds bought the dip."
- `h.verdict` H3 clause: "funds net 105,562 (+1.3 % w/w, new shorts)" → "funds net +1.3 % w/w (bought the dip)".
- `h.open` [B]: "Where MCX “should” open given COMEX and the rupee since 23:30. Within the chase limit → trade your plan; beyond it →
  wait for the rupee's 09:00 open and recompute." → text in finding 13.
- `ph.ladder` footer: "IBJA premium vs duty-paid −3.93 %" → "IBJA premium vs duty-paid −0.71 % (Tue 03 Nov, both at the fix minute)";
  "MCX basis +1.50 %" → "MCX basis +1.50 % at the Tue 03 Nov settlement".
- `ph.official` headers: "Moz" → value ÷ 1e6; "Tonnes" → value ÷ 1e6.
- `c.spec`: "GC 202611" → "GC 202612 (GCZ26)"; "$1.00 = $100" → "$0.10 = $10"; "P" → "physical delivery"; "100 oz_tr" → "100 troy oz".
- strip: "— settle —  NO DATA" → "settle — (arrives with the CME backfill) · live last shown".
- `h.gauges` DOLLAR: "— OFFLINE" → "121.67 · STALE Fri 30 Oct".
- `d.quadrant`: "Tue 03 Nov: flat" → "Tue 03 Nov: no OI yet (T+1)".
- glossary `basis` short → finding 12; new entries → finding 11; "start here" pin → finding 10.
- LEARN routine step texts → panel titles (finding 8); "the proposed GOLD header strip" → "the GOLD header strip".
- `mc.kgx`: "total = pure + USD effect (identity off by more than 0.02 pp — check the inputs)" → "USD effect unavailable: DXY last
  Fri 30 Oct; the split needs today's basket".

## Questions for the owner

1. Should the six-word fund-driver label be shown at the B layer at all, or should [B] show only "new 1,538 longs / new 182 shorts" and
   leave the label to [P]?
2. Brazil's IMF row (5.5 bn in the oz field): exclude, or convert at source once the unit is known?
3. May the glossary carry an `aliases` field (MM, OI, FND, GC1) — that is a `build_glossary.py` change in G-EDU?
4. Appendix C "Evidence ledger" still renders as a LEARN part; is it meant to stay beside SOURCES.md §11?
5. Is the matched-month rule for the small families (→ serial Nov GCX26) intended, given the curriculum calls serial months illiquid?
