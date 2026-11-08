# PART 8 — "How to read this panel": micro-copy, panel by panel

**[P]** Format per panel: **Reads** (2–3 lines for the panel header tooltip) · **Is not** (the misreading to prevent) ·
**Updates** (cadence and lag) · **Evidence** chip — one of the four badges of PLAN §f: `signal` (a pre-registered study
PASSED as a forecast; **none today**), `context` (PASS as a description, or context-only), `arithmetic` (an identity,
cost or spec), `heuristic` (a house rule without evidence). Phase-2 pass (26 Oct 2026, B5-LEARN-DOCS): every heading now
names the GOLD panel id(s) of `PLAN.md` §a that the copy belongs to, or the page that keeps the panel (MCXG, WEI, BRF,
CMDT, ECO). The ids are what the UI keys its `?` popovers and `tooltips.json` on; `validate_learn.py` checks that every
id named here exists in the plan and that every panel in the plan has a tooltip.

## 8.0 Where each panel went (PLAN Appendix B)

**[B]** The names used when this guide was written and the panel ids the page uses now, side by side — only needed when
an older note refers to a panel by its old name.

**[P]** The map:
| G-EDU name (26 Oct 05:50) | GOLD panel id(s) / home |
|---|---|
| 8.1.1 verdict · 8.1.2 key numbers · 8.1.4 inputs | `h.open` |
| 8.1.3 gap build-up | `h.open` waterfall · `h.moved` |
| 8.1.5 context table | `mc.drivers` |
| 8.1.6 headlines | `h.headlines` |
| 8.1.7 manual checks | `ph.links` · `c.links` (four links became data) |
| 8.1.8 accuracy log | `h.accuracy` |
| 8.1.9 session clock · 8.1.10 quote · 8.1.13 ticket | MCXG (unchanged; ticket gains sizing arithmetic) |
| 8.1.11 overlay | MCXG one line · `ph.ladder` |
| 8.1.12 specs | `c.selector` (shared with MCXG) |
| 8.1.14 WEI row · 8.1.15 BRF panel · 8.1.16 CMDT board | WEI card (one extra line) · BRF one line · CMDT tile with a `GOLD ›` chip |
| 8.2.1 health strip | header strip · `h.gauges` |
| 8.2.2 COT | `p.hero` · `p.whois` · `p.crowd` · `p.drawer` |
| 8.2.3 daily OI × price | `d.quadrant` · `p.daily.comex` · `p.daily.mcx` |
| 8.2.4 warehouse | `ph.comex.stocks` |
| 8.2.5 ETF | `ph.etf` |
| 8.2.6 OTC window | `ph.otc` |
| 8.2.7 premium monitor | `ph.ladder` · `ph.india` · `ph.shanghai` |
| 8.2.8 drivers | `mc.drivers` · `mc.move` · `mc.health` |
| 8.2.9 central banks | `ph.official` · `m.official` |
| 8.2.10 term structure | `c.comex` · `c.mcx` |
| 8.2.11 chooser + calendar | `c.selector` · `c.roll` · `h.events` |
| 8.2.12 events calendar | `h.events` · `mc.calendar` (+ ECO) |
| 8.2.13 Kitco-style chart | `d.24h` · `d.3day` |
| 8.2.14 periodicity switch | the `window` param · WEEKLY / MONTHLY views |

## 8.1 Existing panels (today's surfaces, and where each one now lives)

**[B]** The panels that existed before the GOLD page — the pre-open desk, the MCXG quote and ticket, the WEI and BRF lines
— and where each one lives now. On the page every panel carries this copy as its own [B] line and its `?` popover; this
section is the reference version.

**[P]** **8.1.1 Pre-Open desk — verdict → `h.open` (verdict strip, GOLD › HEALTH; BRF keeps one line before 09:00)**
Reads: "Where MCX GOLD 'should' open given what COMEX and the rupee did since the close — arithmetic to read, not advice.
The OK / WAIT strip is a house rule (the ₹300 chase limit) that has missed by thousands of rupees on a typical scored
morning and has been worse than 'open = yesterday's settlement' so far (8.1.8)."
Is not: a direction call, and not an instruction to trade or to wait. Fair can be ₹2,000 above yesterday and the day can
still close lower.
Updates: every 60 s; the baseline (settlement) is computed once the MCX session closes and is labelled by its
**session** ("Thu 22 Oct settlement") and its source, never by the file date.
Evidence: `heuristic` — the ₹300 chase limit has **no support yet**: 7 scored days to 5 Nov 2026, 0% within ₹300, model
worse than naive (8.1.8) — and those mornings were priced off the band midpoint, which ran one MCX session stale (each
miss ≈ the previous session's gold move). The chip carries the measured miss until ≥ 20 VWAP-baseline rows say otherwise.

**[P]** **8.1.2 Key numbers (baseline, fair, expected gap, MCX now vs fair, chase limit) → `h.open`**
Reads: "Baseline = the last completed session's MCX settlement — the VWAP of its last 30 minutes of Breeze 1-minute bars
(VWAP30 PROXY), else the midpoint of the ±3% band (BAND PROXY, set around an earlier session; an amber note when the two
differ by > 0.6 %). Fair = baseline × COMEX ratio × rupee ratio. Gap = fair − baseline, also per lot (×100) and per Mini (×10)."
Is not: a prediction of the *close*; a mismatch of the COMEX month and the MCX month (both Dec today; GCZ26 → GCG27
around 25 Nov while MCX Dec runs to 4 Dec) would add carry to the gap — the symbol is printed so you can check.
Updates: 60 s. Evidence: `arithmetic`; the *usefulness* is what the accuracy log measures.

**[P]** **8.1.3 Gap build-up (COMEX part, rupee part, waterfall) → `h.open` waterfall · `h.moved`**
Reads: "How much of the expected gap is world gold and how much is the rupee. ₹36.5 per $1 on COMEX, ₹1,539 per ₹1 on
USD/INR (today's values)."
Is not: additive beyond small moves (the model is multiplicative; the split is a first-order approximation).
Updates: 60 s. Evidence: `arithmetic`.

**[P]** **8.1.4 Your inputs → `h.open` (inputs panel; triggers live in prefs `gold.triggers.v1`)** — Reads: "Override the baseline with
your broker's close; type the MCX price at the open if ICICI is not connected; chase limit and EUR/USD trigger are your
settings." Evidence: n/a.

**[P]** **8.1.5 Context table (DXY, EUR/USD, US 10y, silver, 10y real yield) → `mc.drivers` (GOLD › MACRO; the desk's rows go)**
Reads: "Each driver's move since the MCX close, signed for gold (falling real yields and dollar = supportive), with its
60-day correlation to gold's daily change. Explains the overnight COMEX move; does not forecast the next one."
Is not: a level signal — the real yield is 2.64% with gold at $4,000; the level relationship broke in 2022 (§5.1).
Updates: Yahoo 30–120 s; DFII10 T+1 (printed). Evidence: `context` (G-MACRO H1/H2: contemporaneous betas, no lead).

**[P]** **8.1.6 Headlines + event-risk chip → `h.headlines`** — Reads: "Last 24 h of gold / Fed / Hormuz / China / rupee headlines;
the chip counts risk words (war, strike, sanction, margin, halt…)." Is not: sentiment analysis, and not sizing advice (the
old "half size at ≥ 3" line is gone, disagreement 14). Evidence: `heuristic` (say so on the chip). The "France / OAT"
topic is dropped; the topic list is a pref.

**[P]** **8.1.7 Manual checks → `ph.links` · `c.links`** — four of the ten links became data (SGE, ETF flows, GLD, real yields), Fed
odds became `mc.fed` (Atlanta Fed), FedWatch / MCX circulars / FBIL / TradingView / Kitco moved to the two "linked"
lists, the investing.com USD/INR link was removed (403 to scripts; INR=X is in the app). Add from this document: CFTC COT
(Saturday, now a job), IBJA rate (now a job), CBIC duty/tariff value (fortnightly, owner), CME warehouse stocks (browser,
O-2). Evidence: n/a.

**[P]** **8.1.8 Accuracy log → `h.accuracy` (strip + the full table)**
Reads: "The 08:45 fair open vs the actual 09:00 open, day by day. 'Naive' = open at yesterday's settlement. Need ~20 days
before the chase limit means anything."
Is not: a judgement yet. **As of 26 Oct 2026: 4 rows, 3 with an actual open; misses +₹1,090, −₹3,518, −₹2,880; mean
₹2,496 vs naive ₹2,147; 0% within ₹300.** The 15 Oct row (baseline 1,48,450 → actual 1,47,482, fair 1,51,000) looks like
a stale baseline (the "settlement before last" case the desk warns about) — the table flags such rows (`stale_baseline`)
and keeps every input (`inputs_json`) for the audit.
Updates: daily (08:45 snapshot, 09:10 capture; holiday-aware since phase 2). Evidence: this *is* the evidence; keep it on
the page.

**[P]** **8.1.9 MCXG session clock + holidays → MCXG (unchanged)** — Reads: "OPEN/CLOSED with time to close; evening close 23:30 IST
while New York is on daylight time, 23:55 otherwise (switches 2 Nov 2026). Holidays are MCX's own: morning-only or
evening-only days exist. Muhurat Sun 8 Nov 2026: special session 14:05–14:19, trading 14:20–15:30 (MCX/TRD/590/2026)."
Is not: NSE's calendar. Evidence: n/a.

**[P]** **8.1.10 Quote (Breeze / price band / fair value) → MCXG (unchanged, honest degrade)** — Reads: "Live LTP from ICICI when the
account can serve MCX; otherwise the previous settlement (band midpoint, PROXY) and the COMEX × rupee fair value, each
labelled. 'Desk price in use' is what the ticket prices with." Is not: a fair-vs-fair premium (the overlay only computes
a premium against a *live* broker price). Evidence: n/a.

**[P]** **8.1.11 COMEX × rupee overlay → MCXG one line · `ph.ladder` (GOLD › PHYSICAL)** — Reads (MCXG line): "COMEX GCZ26 ·
₹/$ · duty-paid landed · fair · live vs fair · GOLD ›". Reads (`ph.ladder`): "COMEX → × USD/INR → landed → + duty 15%
(dated, Notification 16/2026-Customs) → duty-paid landed → IBJA premium → MCX basis and carry, each bar with its
timestamp." Is not: an arbitrage; the basis is a demand and policy variable. The old "18% implied premium" was
0.995 × 1.15 × 1.031 (§2.6) — mostly duty. Evidence: `arithmetic` (ladder); `context` (premium, basis).

**[P]** **8.1.12 Contract specs → `c.selector` (GOLD › CONTRACTS, the same component on MCXG)** — per-column tooltips: Lot "metal
per contract"; Quote "price unit — ₹ per 10 g, 8 g or 1 g"; Tick "₹1 on the quote = ₹100 / ₹10 / ₹1 per lot"; Delivery
"what you receive if you hold to expiry; 995 vs 999"; Margin "exchange NRML (Zerodha mirror, dated: 9.25% of notional on
25 Oct 2026); special and delivery margins come on top"; Cycle "bimonthly / monthly"; Next expiries "observed = ICICI
master; computed = rule (5th / month-end, previous business day if closed)". Adds GOLDTEN, the FND/LTD of the matched
COMEX month, the broker tender cut-off (owner action O-9) and a diff strip on switch.

**[P]** **8.1.13 Paper ticket → MCXG ticket (+ sizing arithmetic)** — Reads: "Notional, NRML margin (dated), tick value and round-trip
costs for N lots at the desk price. PAPER: prices the trade, sends nothing." Adds `max_lots_at_risk_pct`,
`hedge_usdinr_lots`, `atr14_rupees` (§7.6, §7.4). Is not: a broker margin statement. Nothing gold feeds the ticket's
price. Evidence: cost model from `shared/mcx_specs.py` (rates cited there).

**[P]** **8.1.14 WEI commodities row (GOLD, SILVER) → WEI card (the row + one second line + hover)** — Reads: "Yahoo continuous front
month (GC=F), delayed; day change and 1-month spark." Second line: "GOLD · verdict words · basis % · COT MM net (Δ) · next
roll · GOLD ›"; the hover is the five-number header strip. Is not: the Dec contract the desk uses — the tooltip names the
symbol difference. Nothing else moves into WEI.

**[P]** **8.1.15 BRF gold panel → BRF one line** — before 09:00 "Gold open: fair ₹… (gap …) · WAIT · verdict words · GOLD ›"; after
the captured open "Gold opened ₹… vs fair ₹… (miss ₹…) · … · GOLD ›"; on MCX holidays "Gold: MCX closed (…) · GOLD ›". The
full panel and its rotation on the NSE 09:15 clock go (G-APP finding 14).

**[P]** **8.1.16 CMDT futures board → CMDT tile with a `GOLD ›` chip** — gold/silver/copper/oil/gas continuous; the gold tile's detail
chart opens GOLD › WEEKLY; the Pre-Open desk leaves CMDT. The tape's "GOLD" quote is relabelled "GOLD GC1" (a tape
repeats quotes by design).

## 8.2 The GOLD page panels (the owner's list, under the ids the build uses)

**[B]** One entry per GOLD panel: what it reads, what it is not, how often it updates and which evidence badge it wears. A
beginner needs none of this to use the page — each panel's own [B] line says the same in one sentence; this is the audit
copy.

**[P]** **8.2.1 GOLD health strip → header strip (page-global) · `h.gauges` (GOLD › HEALTH)** — Reads: "COMEX matched-month settle
and live · USD/INR · 10-y real yield (T+1) · MCX settle (by session) · basis vs duty-paid landed · managed-money net (COT,
weekly) · MCX opens in …: the five numbers of §0 — what you are long when you buy an MCX lot. Below them, eight tiles:
TREND, REAL YIELD, DOLLAR, POSITIONING, INDIA BASIS, SHANGHAI PREMIUM, ETF HOLDINGS, CURVE/ROLL." Is not: a score; there
is no composite index because none of the inputs is a validated predictor (0 of 69 rules, G-STUDY). Updates: 60 s / T+1 /
weekly. Evidence: `context` on every tile (`arithmetic` on curve/roll).

**[P]** **8.2.2 COT positioning (weekly) → `p.hero` · `p.whois` · `p.crowd` · `p.drawer` (GOLD › POSITIONING)** — Reads: "Who held
COMEX gold futures last Tuesday: producers/merchants, swap dealers (banks), managed money (funds), other reportables,
small traders — long, short, net, change on the week in words ('closed 3,777 longs, covered 894 shorts'), the fund-driver
label (the larger of the two fund legs: 'funds bought the dip' when price fell and the net still rose), OI. Spreads are
excluded from net." Is not: this week — it is 4–6 days old, COMEX only, no London/MCX; and not a
forecast: G-STUDY (26 Oct 2026) FAILED every positioning metric at 1/4/13 weeks and PASSED it as a description of the
week (Spearman +0.65). Updates: Saturday 01:00/02:00 IST; catch-up Monday/Tuesday after holidays; STALE at 10 days.
Evidence: `context` ("explains the week — does not forecast").
Sub-copy: *Who closed what* (`p.whois`): "negative Δlong = longs closed; negative Δshort = shorts covered". *Crowdedness*
(`p.crowd`): "0 = most short in the window, 100 = most long. Crowdedness, not a signal — no forecasting power 2006–2026
(G-STUDY); never coloured." *Options overlay* (`p.drawer`, one line): "options add +4,479 to funds' net; combined OI
532,443 — no information in it (G-STUDY)".

**[P]** **8.2.3 Daily OI × price → `d.quadrant` (GOLD › DAILY) · `p.daily.comex` · `p.daily.mcx` (GOLD › POSITIONING)** — Reads:
"Price change vs open-interest change, all months summed: new longs (both up), short covering (price up, OI down), new
shorts (price down, OI up), long unwinding (both down). COMEX product OI from the CME FTP daily file (T+1, ≈15:30 IST,
history since 2014); MCX OI per contract from the ICICI master (07:35; history since the job started)." Is not: a
forecast; roll weeks and expiry days distort OI (greyed, `mechanical`); OI never says *who* — the COT does, weekly.
Evidence: `context` ("folklore until G-STUDY-2", the pre-registered daily study).

**[P]** **8.2.4 COMEX warehouse stocks → `ph.comex.stocks` (GOLD › PHYSICAL, LINK-ONLY tiles)** — Reads: "Registered (deliverable)
and eligible gold in COMEX vaults, pledged warrants; the coverage ratio with its front-month version beside it. Rising
inflow = metal wanted in New York (EFP stress)." Is not: "owners per ounce" — deliveries are 1–3% of OI a month; the
internet's "100:1" counts all months and ignores eligible. Updates: not fetched — www.cmegroup.com blocks this IP and
its terms forbid scripts; tiles link out until the owner resolves it (O-2). Evidence: `context` (no study shows stock
changes predict gold).

**[P]** **8.2.5 ETF holdings and flows → `ph.etf` (GOLD › PHYSICAL; HEALTH tile)** — Reads: "GLD tonnes daily since 2004 (display-only,
attributed) with daily changes; IAU; WGC weekly flows by region and the India tonnes; AMFI gold-ETF AUM monthly.
Divergence from price (price up, tonnes down) = non-Western buying." Is not: a leading indicator (contemporaneous; G-STUDY
4-week change t ≤ 1; G-MACRO weekly corr 0.33–0.37, ≈ 0 predictive; AMFI flows chase last month's return, G-INDIA-1).
Updates: daily ≈06:00 IST T+1 (GLD) / Monday ≈11:30 (WGC) / monthly. Evidence: `context`.

**[P]** **8.2.6 OTC window (LBMA trade turnover + London vault holdings + EFP prints) → `ph.otc`** — Reads: "The London
over-the-counter market, where most gold trades: weekly turnover (12-week average, $bn — $964 bn for the week ended 16 Oct
2026 ≈ 7,500 t gross), tonnes in London vaults (monthly, ~1 month lag; 9,821 t at end-Sep 2026) and the EFP prints
registered on COMEX (round turns, 20-day average, % of volume). There is no COT for London — this is activity and stock,
not positions." Is not: 'deals' with names; OTC counterparties are never public; CME publishes EFP volume, never the EFP
price. Updates: weekly / monthly / daily. Evidence: `context`.

**[P]** **8.2.7 Premium monitor → `ph.ladder` · `ph.india` · `ph.shanghai`** — Reads: "`ph.ladder`: the India price stack with the
duty printed and dated (15%, Notification 16/2026-Customs, 13 May 2026). `ph.india`: IBJA 999 PM vs duty-paid landed (the
dealer premium) and MCX front vs duty-paid landed (the basis, carry-adjusted beside it), history with duty steps, WGC's
weekly India premium and the Reuters survey as sanity lines. `ph.shanghai`: SGE PM (CNY/g → $/oz) vs London PM or COMEX
at 14:15 Beijing, both timestamps shown, WGC weekly China premium beside it." Is not: one number — three definitions,
three uses; a premium computed from prices seven hours apart is clock error (G-INDIA §5.3: +0.9% spurious), so each
derived number on the ladder names the clock it used (the IBJA premium at the fix minute, the MCX basis at the settlement
session) and the live bars, stamped "now", are never divided by a settlement. Updates: daily
at the IBJA fix minutes (13:45 / 18:10 jobs) and the SGE close (16:10); the first three ladder bars live. Evidence:
`arithmetic` (ladder) · `context` (premiums; no study yet — GS-P3 and GS-PREMIUM wait for history).

**[P]** **8.2.8 Drivers → `mc.drivers` · `mc.move` · `mc.health` (GOLD › MACRO)** — Reads: "The macro inputs with history and today's
percentile: 10-y real yield, 2-y, breakeven, DXY / broad dollar, USD/INR, GVZ, Brent, GLD; each tagged supportive or
headwind by its rule and its 60-day correlation. `mc.move`: GVZ → a 1σ day in %, $/oz, ₹/10 g and ₹ per lot per family;
realised vol; ATR14 ₹. `mc.health`: the rolling 1-year correlations and the betas by regime." Is not: a model. The
*level* link to gold broke in 2022 (G-MACRO H1: beta −9.9%/100 bp 2010–21, −5.0 since 2022); the dollar never stopped
working (H2: beta ≈ −1 in every regime); neither forecasts (G-STUDY). Updates: daily T+1 (FRED/Treasury), 60 s (Yahoo).
Evidence: `context` (drivers) · `arithmetic` (`mc.move`).

**[P]** **8.2.9 Central banks → `ph.official` (GOLD › PHYSICAL) · `m.official` (GOLD › MONTHLY)** — Reads: "Monthly net purchases by
country from the IMF (ounces shown as Moz and tonnes, each with its data month; 1–2 month lag; China 76.73 Moz ≈ 2,409 t
in Aug-26, +20 t/month), the PBoC
streak, RBI tonnes (half-yearly) and the weekly $ value and share (14.7% of reserves on 16 Oct 2026); the 1,000 t/yr
line." Is not: timely — it explains the regime (the 2024-26 doubling with funds *cutting* net length: the marginal buyer is
outside the COT). Updates: monthly (~25th) / weekly (Friday). Evidence: `context` (GS-P5 proposed, not yet pre-registered; honest prior FAIL as
timing).

**[P]** **8.2.10 Term structure / carry → `c.comex` · `c.mcx` (GOLD › CONTRACTS)** — Reads: "COMEX six months with last week's ghost
curve, calendar spreads, implied carry p.a. (Dec-26 → Feb-27 +$41.1 = 1.03% ≈ 3.2%/yr on settlements); MCX chain with
settle (proxy/official), band, OI, implied carry; implied lease ≈ SOFR − COMEX carry. Backwardation = shortage (COMEX) or
duty-cut expectation (MCX, into Feb)." The MCX chain is ONE session: its settles are the ICICI band midpoints of the session
the band belongs to (5 Nov 2026: the Tue 03 Nov band, with the OI at the Wed 04 Nov close), printed with that session — never
the file or request date; vs-front and carry are taken inside it. The basis under it names its own session (the latest
close's last-30-min VWAP), so the note says when the two differ. PETAL (₹/1 g) and GUINEA (₹/8 g) also print a ₹/10 g
equivalent. Is not: a yield you earn — a long pays the carry at every roll; and Yahoo's per-month price is the last trade,
not the settlement (labelled LAST TRADE until the bulletin is allowed, O-2). Updates: daily. Evidence: `arithmetic`.

**[P]** **8.2.11 Contract chooser + calendar strip → `c.selector` · `c.roll` · `h.events`** — Reads: "Which contract for which purpose
(§3.5 table, now with GOLDTEN: PETAL round trip 0.34% of notional vs GOLD 0.018%); next MCX expiries, COMEX first intent /
FND / LTD in IST, broker tender cut-off (owner, O-9), Budget, FOMC, COT release." Is not: advice on direction. Updates:
daily. Evidence: `arithmetic`.

**[P]** **8.2.12 Gold events calendar (the 'weeks, days, months' view) → `h.events` · `mc.calendar` (+ ECO)** — Reads: "Scheduled
events that move gold, in IST, with the in-session / after-close flag (US data 18:00/19:00 IST inside the MCX evening;
FOMC 23:30 / 00:30 after the close in US winter → gap risk at 09:00)." Written once into `gold_events`, read by GOLD
(`h.events`, `mc.calendar`, `c.roll`). ECO / EVTS reading the same rows (US CPI/NFP/PCE/GDP in IST and the gold-specific
rows: COT release, COMEX FND/LTD, MCX expiries, Dhanteras, Diwali/Muhurat, Akshaya Tritiya, Budget, PIB/AMFI/WSS days)
is PLAN §b's intent and **not in this release**: today ECO and EVTS do not read `gold_events`. Evidence: `arithmetic`
(dates), with the caveat that no seasonal passes both halves (G-MACRO H3, G-STUDY §4.4).

**[P]** **8.2.13 Chart (Kitco-style 24-hour with session shading) → `d.24h` · `d.3day` (GOLD › DAILY)** — Reads: "COMEX matched
month, 24 h, 1-minute line from our own stored bars, with the previous day dotted, the settlement dashed, a two-row time
axis (IST over NY), session bands Sydney/Tokyo · Shanghai · London · New York and the **MCX 09:00–23:30/23:55 bar**; the
3-day overlay beside it; the SGE Au99.99 line on the Shanghai band." Is not: Kitco's chart — Kitco's terms (verified
26 Oct 2026) allow personal, non-commercial use only and prohibit redistribution; **link, never embed or scrape.** The
bars come from one Yahoo fetcher through data-service (`gold_bars_intraday`), never from a publisher on the request path.
Evidence: `arithmetic` (it is the price).

**[P]** **8.2.14 Periodicity switch (day / week / month) → the `window` param · `w.table` · `w.grid` (GOLD › WEEKLY) · `m.physical` · `m.balance` (GOLD › MONTHLY)** — Reads: "Same series,
aggregated: daily changes, weekly (Tuesday COT weeks, `w.table`, `w.grid`), monthly (vaults, central banks, ETF monthly,
India imports, `m.physical`, `m.balance`)." Every history starts the day its job starts and the page says so ("since
27 Oct 2026"); the resampling rule (last / sum / mean) comes from the catalog. Evidence: n/a (plumbing).

## 8.3 Glossary and tooltips

**[B]** Every dotted word on the page opens the glossary; the search box also understands the page's own abbreviations
(MM, OI, FND, w/w, bp, GC1) and a dozen "start here" terms sit above the alphabet until you type.

**[P]** `glossary.json` (this folder, rebuilt 5 Nov 2026): 160 terms with `term`, `short` (≤ 200 chars, the tooltip),
`long` (the LEARN entry; empty when the short line is the whole story — the panel prints it only when it exists),
`see_also` (every reference resolves), `aliases` (272 abbreviations and page labels — MM, OI, FND, LTD, GC1, w/w, bp, pp,
Shanghai premium, India basis, funds bought the dip … — each unique and never a term's own name; the search ranks an alias
hit like the term itself) and a top-level `start_here` list of twelve terms the glossary panel pins above the alphabet
while the search box is empty. `build_glossary.py` asserts all of it; `validate_learn.py` re-checks the written file
(check 10) and has a `--selftest` with negative controls. `tooltips.json`: 259 one-liners — 203 keyed by the app's payload
field names (`basis_pct`, `duty_pct`, `rs_per_comex_dollar`, `tick_value`, `mm_net`, `cot_index_52w`, `driver_label`, …)
and 56 keyed by the panel ids of PLAN §a (`h.verdict` … `c.links`, listed under `panels`) so the UI can attach them
without parsing prose. `validate_learn.py` checks all of it against `PLAN.md` and, in the other direction, that every
field key is referenced by name in a `ui/` source file (check 9): the keys no view renders are retired from the file and
listed in `build_glossary.py` (`RETIRED_FIELD_KEYS`) for the day a view renders the field. Tooltips that state a server
rule (the fund-driver label — `driver_rule.py`, the larger leg; the 1w / 1m / 1y windows, which step back 7 / 30 / 365
calendar days to the nearest earlier session; the percentile windows; the dollar series named on its tile; the premium and
basis clocks) were re-read against the code on 5 Nov 2026.

## 8.4 The health verdict, clause by clause (the rule table the owner can audit)

**[B]** The verdict is one sentence made of short facts — how gold moved, whether the dollar or yields explain it, what
funds did, where India's price sits against imported gold, what the roll costs, what the big ETF did — each from a stored
number with a threshold. No score, no count of "supportive" items, and it ends "describes, does not predict" on purpose.

**[P]** `h.verdict` is one sentence built from thresholded clauses on stored series. Each clause the API returns carries
`rule_id`, `series_id`, `value` and `threshold`, so every word can be traced to a number. There is **no score** and no
count of "supportive" clauses: 0 of 69 walk-forward rules beat buy-and-hold (G-STUDY), so a count would read as the
forecast it cannot be. A gauge whose `state` is `stale` or `unavailable` contributes no clause (the `freshness.stale[]`
and `freshness.unavailable[]` lists name it and the tile says STALE); nothing is guessed. The table below **is**
`HEALTH_RULES` in `services/ui-api/routers/gold.py` (ui-api `/api/gold/health`), rule for rule: the code is the source,
this table follows it, and `validate_learn.py` (check 8) reads that list with `ast` and fails when the two differ.
Changing a threshold is a one-line change in that list; GOLD › LEARN renders the live clauses with their `rule_id`
directly above this text, so the two can be compared on the page.

| rule_id | Clause it produces | Series | Rule (as implemented) | `threshold` dict (verbatim) | Window |
|---|---|---|---|---|---|
| H1 | "WEAK WEEK" / "STRONG WEEK" / "FLAT WEEK" / "FIRM WEEK" / "SOFT WEEK" (DAY / MONTH when `window=D` / `M`) | `COMEX_GC_FRONT` | gold's change over the window: ≤ −2 % WEAK · ≥ +2 % STRONG · \|Δ\| < 0.5 % FLAT · else FIRM (up) / SOFT (down); then the trend sentence from the TREND gauge: the price vs its 20-d and 200-d averages ('below both averages' / 'between' / 'above both', both % printed) and the drawdown from the 52-week high — a description, no threshold of its own | `{"weak_pct": -2.0, "strong_pct": 2.0, "flat_pct": 0.5}` | D: latest close vs the previous session · W: the calendar week to date (Monday's close → latest) once the week has started, else the last 5 sessions — the clause names the span it used · M: 30 calendar days (the nearest earlier session) |
| H2 | "DOLLAR-DRIVEN" / "YIELD-DRIVEN" / "GOLD-SPECIFIC" after the H1 words; then the decomposition "gold −2.8 % week to date (Fri 30 Oct close → Fri 6 Nov) · of which the dollar −1.9 % (a stronger dollar) · real yield +12 bp (to Thu 5 Nov)" | `DXY_CLOSE` (the KGX dollar effect) · the 10-y real yield: the fresher of `UST_REAL_10Y` and `FRED_DFII10` (one value per page, dated in the clause) | DOLLAR-DRIVEN when the dollar effect (KGX split) is ≥ 40 % of gold's move with the same sign and \|move\| ≥ 0.5 %; YIELD-DRIVEN when the 10-y real yield moved ≥ 5 bp against gold; else GOLD-SPECIFIC; no driver word at all when \|move\| < 0.5 %, and none when the dollar or the real-yield leg is unavailable (the clause then says the driver is untested and names the offline series). 8 Nov 2026 (critic F4 / F5): the price clause is anchored end to end — its two dates, not a bare "over the week" — and the dollar figure says in words which way the dollar went, because the number is the dollar's CONTRIBUTION to gold (−Δln of the ICE DXY close over gold's own two dates, the same number the DOLLAR tile and MACRO's KGX split print), so a positive one means a weaker dollar; when the dollar leg's own end date is not the price's it carries "(to …)" as well | `{"usd_share": 0.4, "min_move_pct": 0.5, "real_yield_bp": 5.0}` | the H1 window |
| H3 | "funds −1.8 % w/w to Tue 3 Nov (new shorts; gold −3.3 % that week)" | `COT_DISAGG_F` (`gold_cot_metrics`, managed money) | managed-money net's w/w change in % **dated to the report's Tuesday** (8 Nov 2026, critic F5: positions are as of a Tuesday and published the next Friday, so this w/w never covers the price clause's week), with the fund-driver label — the larger of the two fund legs (G-STUDY §5.2; "funds bought the dip" when price fell and the net still rose) — and that COT week's OWN price move beside the label; printed whenever the positioning gauge is fresh (the net itself is on the strip and the tile, PLAN §f.6) | no threshold | latest report (Tuesday positions, Friday release) |
| H4 | "India basis +3.1 % vs duty-paid landed" (the 26 Oct 05:49 figure of §2.6) | `MCX_BASIS_PCT` | the contract's settlement (last-30-min VWAP, else the band of its real session), in ₹/10 g, vs the duty-paid landed price × purity/1000 (GOLD / GOLDM 995, GOLDTEN / PETAL / GUINEA 999; landed is fine gold — PM decision D1) at that session's close, or the live price vs now while a quote exists; one value per clock (duty dated); stated, not judged — no "wide" or "discount" word | no threshold | latest |
| H5 | "roll DEC-26→FEB-27 costs +1.03 % (+3.2 %/yr), FND in 35 d (Wed 4 Nov)" | `COMEX_CARRY_ANN_PCT` (days to FND from `gold_cme_calendar`) | front → next calendar spread as % and annualised; days to first notice; printed whenever the curve gauge is fresh; silent on the date on the price clause's own day, dated when the curve is a session behind it (8 Nov 2026, critic F5) | no threshold | latest |
| H6 | "GLD −12.0 t on Wed 4 Nov (notable)" | `GLD_TONNES` | GLD tonnes change on its OWN latest day, named (8 Nov 2026, critic F5: two consecutive nights printed "+2.9 t on the day" and "−2.9 t on the day" for Wed 4 Nov and Tue 3 Nov, because GLD reports a day late); silent on the date only when it IS the price clause's day; printed whenever the ETF gauge is fresh; ≥ 5 t is called "notable" | `{"notable_t": 5.0}` | latest day |
| H0 | "no fresh gauge: every input is stale or unavailable" (only when no other clause exists) · the closing words on every sentence | — | every verdict ends "describes, does not predict"; stale or unavailable gauges contribute no clause | no threshold | — |

**[P]** How the API labels the clauses: the first clause (the H1 words plus the H2 driver word) comes back with
`rule_id: "H1/H2"`, the decomposition line as `H2`, then `H3` … `H6` in that order; `H0` appears alone when nothing is
fresh. The sentence is the clauses joined with " · " plus " · describes, does not predict" (tests T1 / T7 assert the
ending; `line` also feeds the WEI second line and the BRF line, PLAN §b).

**[P]** Planned, not in this release (PLAN §a.2 names them; no `rule_id` exists for them and nothing on the page prints them):
the week's largest day ("gold −2.8 % Thu …"), a Shanghai-premium clause (sign flip or \|value\| ≥ $20), an event clause
for a high-impact release in the next 24 h, a "(COT 10 days old)" note inside the sentence (today a stale gauge is simply
left out and its tile says STALE), and the "wide basis" / "India at a discount" words on H4.

**[B]** Reading it: what moved and who was behind it, in one breath.

**[P]** Every clause is a threshold on a stored series; nothing in the sentence is a forecast, and the thresholds are
deliberately coarse so the sentence changes only when the data does. The sentence ends "describes, does not predict".

---

# PART 9 — Reading routines (the "days, weeks, months" the owner asked for)

Each step names the panel in words, with its id in backticks and its view in capitals; LEARN renders these three lists
as collapsible checklists whose deep link is the first panel id on the line.

**Daily (08:30–08:55 IST, 10 minutes)**
1. The header strip (top of every view): COMEX settle and live, USD/INR, the real yield (yesterday's), the MCX settlement
   (by session), the basis, funds' net (last Tuesday) — then the verdict sentence (`h.verdict`, HEALTH) and the eight
   tiles (`h.gauges`).
2. Today's open (`h.open`, HEALTH): fair value vs yesterday's settlement; how much of the gap is COMEX and how much the
   rupee (`h.moved`); the event-risk chip. Decide OK / WAIT before 09:00 — the ₹300 limit is unproven, so read the strip
   as arithmetic, not advice.
3. The drivers (`mc.drivers`, MACRO): what changed overnight and why; the headlines (`h.headlines`, HEALTH); any scheduled
   event today (`h.events`, HEALTH; the after-close flag).
4. Yesterday's OI × price (`d.quadrant`, DAILY): COMEX (T+1) and MCX (07:35); roll and expiry days are greyed.
5. The expected move (`mc.move`, MACRO): ATR in rupees and the 1σ day per lot; max lots at 1 % risk sits on the MCXG paper ticket, cash headroom is yours to keep (≥ 3 ATR per lot); the roll
   calendar (`c.roll`, CONTRACTS) if a tender cut-off is within 7 days.
Evening (the last 30 min before the MCX close: 23:25–23:55 in US winter, 23:00–23:30 in US summer): the 24-hour chart (`d.24h`, DAILY) for COMEX vs the MCX close; tomorrow's events; MCX settles on the volume-weighted average of those 30 min.

**Weekly (Saturday morning, 20 minutes)**
1. Who did what (`p.hero` / `p.whois`, POSITIONING): the nets, the change by group in words, who closed what, the
   fund-driver label; crowdedness (`p.crowd`) as context only; the drawer (`p.drawer`) for the options line and trader
   counts; days to first notice (`c.roll`, CONTRACTS) for the roll footprint.
2. ETF holdings (`ph.etf`, PHYSICAL): GLD week on week; WGC weekly flows (Monday); the week's table and its CSV
   (`w.table`, WEEKLY).
3. The OTC window (`ph.otc`, PHYSICAL): LBMA turnover (weekly), EFP prints; the warehouse link (`ph.comex.stocks`) in a
   browser.
4. Term structure (`c.comex` / `c.mcx`, CONTRACTS): carry vs SOFR, the implied lease; the MCX–COMEX carry gap.
5. Premium and basis history (`ph.india` / `ph.shanghai`, PHYSICAL); any CBIC tariff-value or duty notification (owner,
   dated).
6. Next week's calendar (`h.events`, HEALTH / `mc.calendar`, MACRO): FOMC / CPI / NFP / RBI / Budget / MCX expiry /
   COMEX first notice day.

**Monthly (first weekend)**
1. Central banks (`m.official`, MONTHLY / `ph.official`, PHYSICAL): IMF ~25th, PBoC ~7th, RBI weekly.
2. Physical flow (`m.physical`, MONTHLY): London vaults; SGE withdrawals; India imports (PIB ~15th); Swiss exports; AMFI
   AUM in tonnes.
3. The regime check (`mc.health`, MACRO + `m.ladder`, `m.season`, MONTHLY): the real-yield link, central-bank pace, the
   ETF trend, the 3-year COT index as context, the seasonality caveat (§5.9).
4. The accuracy log (`h.accuracy`, HEALTH): model vs naive over the month; the chase-limit decision at 20 rows.
5. The contract selector (`c.selector`, CONTRACTS): any margin change (dated NRML mirror); broker rate changes.

---

# Appendix A — Formulas and constants (cheat-sheet)

```
1 ozt = 31.1034768 g        1 kg = 32.1507 ozt       1 tola = 11.6638 g = 3/8 ozt
₹/10 g (999)   = $/oz × USDINR × 10 / 31.1034768
995 → 999      × 1.00402 ;   999 → 995  × 0.99600
MCX fair (desk)= settlement × (COMEX_now / COMEX_ref) × (USDINR_now / USDINR_ref)   [refs = last-30-min average before MCX close]
duty-paid      = landed_995 × (1 + BCD + AIDC)      [15% (10% + 5%) since 13 May 2026, Notification 16/2026-Customs — dated input; tariff value fortnightly]
MCX basis      = MCX (₹/10 g) / (duty-paid × P/1000) − 1, P = the contract's purity (995 GOLD/GOLDM, 999 TEN/PETAL/GUINEA; D1) ;
                 carry-adjusted basis = basis − carry_to_expiry
old implied premium = MCX / landed_999 − 1 = 0.995 × (1 + duty) × (1 + basis) − 1      [deprecated alias]
multiplier     = lot_g / quote_g  (GOLD 100, GOLDM 10, GOLDTEN 1, GUINEA 1, PETAL 1)
tick value     = ₹1 × multiplier ; notional = price × multiplier × lots ; P&L = Δprice × multiplier × lots
leverage       = notional / margin   [NRML 9.25% on 25 Oct 2026 → 10.8×]
carry (ann.)   = ln(F2/F1) × 365 / days ; implied lease ≈ r_USD − carry_COMEX ; carry_MCX ≈ carry_COMEX + (r_INR − r_USD)
basis          = F − S ; residual basis = basis − fair carry
net (COT)      = long − short (spreads excluded) ; COT index = 100 × (net − min_N)/(max_N − min_N)   [context only]
KGX            = usd_move = −Σ wᵢ Δln fᵢ (DXY weights) ; pure_gold = gold_usd + usd_move ; rupee leg = Δln USDINR
GSR            = gold $/oz ÷ silver $/oz
1σ day         = GVZ / √252  (× price × multiplier = ₹ per lot)
RR25           = IV(25Δ call) − IV(25Δ put)
lots           = floor(account × risk% / (k × ATR14 × multiplier)) ; margin ≤ 35% account ; cash headroom ≥ 3 × ATR × multiplier × lots
USDINR hedge   = lots × lot_g/31.1035 × $/oz / 1,000   (USD/INR futures of $1,000)
```

# Appendix B — The gold day in IST (US DST until 1 Nov 2026; UK on GMT from 25 Oct 2026)

| IST | What |
|---|---|
| 03:30 (04:30 winter) | CME Globex reopens after the 60-min break (Sun night: the week opens) |
| 07:45 / 11:45 | Shanghai Gold Benchmark auctions (10:15 / 14:15 Beijing); SGE day session ~06:30–13:00 IST |
| ~07:30 | ICICI publishes the MCX security master (yesterday's settlement, OI); the 07:35 job stores it |
| 08:45 / 09:10 | app: fair-open snapshot / actual-open capture (holiday-aware) |
| 09:00 | **MCX opens**; onshore USD/INR opens; NSE currency futures 09:00–17:00 |
| 13:30 | FBIL USD/INR reference rate; IBJA AM fix ≈12:00–13:00 (13:45 job) |
| 14:00–15:30 (T+1) | CME FTP daily volume & OI file (15:45 job) |
| 16:00 (15:00 BST) | **LBMA Gold Price AM** |
| 17:00 | MCX morning/evening split (partial holidays only); currency segment closes — rupee hedge is off |
| 18:00 (19:00 winter) | US data: CPI, NFP, retail sales (08:30 ET) — inside the MCX evening session |
| 18:30–00:00 | SHFE night session |
| 20:30 (19:30 BST) | **LBMA Gold Price PM**; IBJA PM fix ≈17:00–18:30 (18:10 job) |
| 23:00 (00:00 winter) | **COMEX settlement window** (13:29–13:30 ET) |
| 23:30 (23:55 winter) | **MCX closes**; settlement = VWAP of the last 30 min |
| 23:30 (00:30 winter) | FOMC statement (14:00 ET), presser +30 min — after the MCX close in winter |
| 02:30 (03:30 winter) | Globex daily close; break until 03:30 (04:30) |
| Sat 01:00 (02:00 winter) | **COT release** (Fri 15:30 ET); the job retries hourly to 06:30 |

# Appendix C — Evidence ledger

The single ledger is **`SOURCES.md` §11** (the G-STUDY results every badge rests on) with the full rows in
`G-STUDY/FINDINGS.md`, `G-MACRO/study.json`, `G-INDIA/scratch/amfi_study_results.json` and the program-level
`reports/gold_program/FINDINGS.md`. The claims this document makes, in one table:

| Claim | Status | Source |
|---|---|---|
| ₹/10 g conversion, multipliers, tick values, cost ladder, margin % | `arithmetic` | `shared/mcx_specs.py`, ICICI master, Zerodha NRML mirror (25 Oct 2026) |
| Duty 15% (BCD 10% + AIDC 5%) since 13 May 2026, Notification 16/2026-Customs | fact from secondary sources that agree; **owner confirms at CBIC (O-3)** | SOURCES.md F9 |
| COT positioning forecasts gold | **FAIL** at 1/4/13 weeks, every metric; COT-index lore reversed; 0 of 69 rules | G-STUDY (26 Oct 2026); G-COT COT-1 |
| COT describes the week | **PASS** (Δ fund net vs price Spearman +0.65, stable; next week −0.02) | G-STUDY |
| Real yields / dollar drive gold | contemporaneous explainers (H1 beta weaker since 2022; H2 ≈ −1 every regime); **no lead** | G-MACRO H1/H2; G-STUDY |
| ETF flows lead price | **no**; contemporaneous (R² 16% same week); AMFI flows chase returns | G-STUDY; G-MACRO; G-INDIA-1 |
| Seasonality (Dec/Jan, Diwali, weddings) | **context only**: no month passes both halves; walk-forward +0.3%/yr | G-MACRO H3; G-STUDY §4.4 |
| GPR, net liquidity, fair-value regressions | no prediction (H4); fair value DO-NOT-PUBLISH (H5) | G-MACRO |
| Chase limit ₹300 | **unsupported** (3 scored days, 0% within; model worse than naive) | accuracy log (SOURCES.md H2) |
| Event-risk headline chip | `heuristic`, no study; count only | `gold_preopen.py` |
| Safe-haven effect short-lived; GOFO discontinued 2015; academic COT literature | standard references, **not live-verified** | Baur & Lucey 2010; LBMA; Sanders–Irwin–Merrin 2009 (PLAN j.2 #15) |
| Source status (LBMA licence, Kitco terms, CME/MCX 403, Yahoo 429, GLD XLSX, SGE table) | **verified live 26 Oct 2026** | `verify_results.json`, `verify_pass2.json`, SOURCES.md |

# Appendix D — Source verification table

See REPORT.md §2 (the same table with status, latency, sample and verdict for all 52 probes) and `SOURCES.md` for the
program-wide 140 entries with verdicts.

# Appendix E — What is not free, and where to click instead

| Wanted | Why there is no feed | Where it is (link-only) | What the page shows instead |
|---|---|---|---|
| LBMA Gold Price AM/PM history | IBA licence; JSON 403; FRED series removed 2022 (A8, A10) | lbma.org.uk/prices-and-data | fix times as marks on `d.24h`; the WGC chart API's AM/PM as provisional reference marks (A9, gated on O-1) |
| CME daily bulletin, warehouse stocks, delivery notices, options OI, FedWatch, contract pages | www.cmegroup.com blocks this IP; its Data Terms forbid scripts (C7–C13, O-2) | the CME pages in a browser; `ph.comex.stocks`, `c.links` | per-product OI/volume, EFP prints, calendar and specs from the CME **FTP** (C1–C4); Yahoo per-month last trade labelled LAST TRADE; Atlanta Fed for the Fed path |
| MCX bhavcopy (official settlement, volume), category-wise OI, spot polling, circulars, option chain | Akamai bot wall to every scripted client (F3–F7, O-8) | mcxindia.com in a browser; `c.links` | ICICI master band midpoint as PROXY settlement and OI per contract (F1); hand-maintained circular constants; `p.mcx.category` dormant with the reason |
| Kitco charts and the KGX numbers | terms forbid robots and redistribution (A21–A24) | kitco.com/charts/gold | our own chart from stored bars (`d.24h`, `d.3day`); KGX replicated as `mc.kgx` with a rupee leg |
| Bloomberg / LSEG (`CFTC <GO>`, `GC1 Comdty`, `XAU=`) | paid, no redistribution (B16) | — | Appendix F maps each function to a free panel |
| Reuters "Asia Gold" dealer premiums | commentary, not a feed (E22) | mining.com republication | our IBJA-based premium with the Reuters number as a sanity line on `ph.india` |
| stooq, goldprice.org, investing.com | proof-of-work challenge / spoofed-referer only / 403 (A14–A16) | not even linked | Yahoo covers them |
| Sprott PHYS, US Mint, DGCX, Borsa Istanbul, SGE lease rates, HK trade, SAFE page | Cloudflare / no API / JS-only (E4, E18, D6, D8, D9, E13, E20) | `ph.links` | — |
| Nasdaq Data Link CHRIS/LBMA | discontinued / keyed (A19, A20) | — | CME FTP for OI, Yahoo for prices |
| A Yahoo "spot" gold symbol | `XAUUSD=X` is 404 (A7) | — | the spot proxy is the COMEX front, and the page says so |

# Appendix F — What a Bloomberg gold trader looks at → where it is here

Public-guide function names (G-KITCO Appendix C; UNVERIFIED on a terminal), mapped to the free build:

| Bloomberg | What it answers | Here |
|---|---|---|
| `GC1 Comdty DES` | the contract: size, tick, settlement, margin | `c.spec` (CME product reference, daily InitMargin %), `c.selector` for MCX |
| `GP` / `GIP` / `GPO` | the chart, intraday and history | `d.24h`, `d.3day` (1-min, our bars), `w.candles`, `m.candles` |
| `HP` | history table | `w.table` (+ CSV), `/api/gold/series?freq=D\|W\|M` |
| `CT` / `CTM` | the contract chain with volume and OI; exchange search | `c.mcx` (MCX chain, OI, carry), `c.comex`, `c.selector` (exchange × family × expiry) |
| `CCRV` / `FWCV` | the forward curve today vs a week ago | `c.comex` ghost curve, `c.mcx` |
| `GCA Comdty OIS`, the Volume & OI column | daily OI by product, the roll | `p.daily.comex` (CME FTP, T+1), `p.daily.mcx` |
| `CFTC <GO>`, `ALLX`, tickers `…MML/MMS/…N` | who is long and short, weekly | `p.hero`, `p.whois`, `p.history`, `p.crowd`, `p.drawer` |
| `XAU Curncy` | spot | no free spot feed: the spot proxy (COMEX front) with the note; gold-api cross-check chip |
| `GLCO` | gold in every currency | `mc.ccy` |
| `ECO` | releases with consensus | `mc.calendar`, `h.events` (ForexFactory JSON in IST, BEA/BLS links) |
| `WIRP` / FedWatch | the Fed path | `mc.fed` (Atlanta Fed MPT distribution; FedWatch stays a link) |
| `CPFC` | price forecasts | deliberately **not built** (a forecast panel contradicts §f; fair-value regressions are DO-NOT-PUBLISH) |
| WGC Goldhub, `ETF <GO>` | ETF holdings and flows, balance sheet | `ph.etf`, `m.balance`, `m.physical` (attributed, display-only) |
| `MARS` / risk | expected move, sizing | `mc.move` (GVZ → ₹ per lot), the MCXG ticket's sizing arithmetic |
