
---

# PART 3 — Futures mechanics

## 3.1 Lot, multiplier, tick value, notional, P&L, cost

**[B]** A futures lot is a fixed quantity of gold. The price is quoted per 10 g, but you own 1 kg (GOLD) or 100 g
(GOLDM), so every ₹1 move in the quote is ₹100 or ₹10 of profit or loss. The *tick* is the smallest price step.

**[P]**
- `multiplier = lot_grams / quote_grams` (GOLD 1000/10 = 100; GOLDM 100/10 = 10; GUINEA 8/8 = 1; PETAL 1/1 = 1).
- `tick value = tick × multiplier` (GOLD ₹1 × 100 = ₹100).
- `notional = price × multiplier × lots` (GOLD at ₹1,46,079: **₹1.46 crore per lot**; GOLDM ₹14.6 lakh; PETAL ₹14,581).
- `P&L = (exit − entry) × multiplier × lots − costs`.
- Round-trip cost, squared off, one GOLD lot at ₹1,46,079 (app ticket model, `shared/mcx_specs.round_trip_costs`):
  exchange 0.0021% × 2 sides ≈ ₹614; CTT 0.01% sell side ≈ ₹1,461; stamp 0.002% buy ≈ ₹292; SEBI ₹10/crore × 2 ≈ ₹29;
  brokerage ₹20 × 2; GST 18% on brokerage + exchange + SEBI ≈ ₹123 → **≈ ₹2,560 ≈ 0.018% of notional ≈ 26 ticks** (26 Oct 2026 prices; ≈ ₹2,445 / 24.5 ticks on 5 Nov — the CONTRACTS card prints today's). The
  breakeven move is ₹26 per 10 g. Costs are not the problem in gold futures; **leverage and gaps are.** (Compare the
  project's equity delivery round trip of ≈ 0.93%.)

**[APP]** MCXG paper ticket (`notional`, `tick_value_position`, `round_trip`). Tooltip on "Tick": "₹1 on the quote =
₹100 on one GOLD lot (1 kg ÷ 10 g)".

## 3.2 Margin and leverage

**[B]** You do not pay the full ₹1.46 crore for a GOLD lot; you post a deposit (margin) — 9.25% of notional on every MCX gold contract on 25 Oct 2026 (exchange NRML,
Zerodha mirror; it changes daily and jumps after circulars) — and the exchange marks your position to the settlement price every evening, debiting losses in cash. If your cash runs out the
broker closes you. The deposit is small, so the leverage is large: a 1% move is about a 10–15% move on your margin.

**[P]**
- `leverage = notional / margin`. At 9.25%: 10.8×. A 1% adverse day on one GOLD lot = ₹1,46,000 against ≈ ₹13.3 lakh of
  margin = **−11% of margin in one day**. Gold's realised daily volatility has run 1–1.5% in 2024–26,
  with 3–6% days on event shocks (Apr 2025, Oct 2025).
- Daily MTM in **cash**; the margin itself can be pledged collateral but MTM losses cannot. Keep MTM headroom of at
  least 3 daily-vol moves (≈ 4–5% of notional) in cash beyond the initial margin, or the first bad week ends the trade
  for you.
- Margins **change**: SPAN parameters are reset daily; special/additional margins are imposed by circular on volatile
  days; delivery margins rise in the tender period; a margin increase on an open position is a cash call the next
  morning. The MCXG `margin_pct_indicative` is a planning number, never the broker's number.
- Calendar-spread margin benefit: a long Dec / short Feb pair carries a fraction of outright margin (exchange-defined);
  this is what makes term-structure trades (§7.3) financeable.

**[APP]** MCXG ticket (`indicative_margin`, `margin_pct_indicative`). The "Manual checks" list already links MCX
circulars for margin changes.

## 3.3 Contango, backwardation, cost of carry, implied lease rate

**[B]** Futures for later months usually cost more than for nearer months, because whoever holds gold for you until then
has to finance and store it. That upward slope is *contango*. When later months are *cheaper* (backwardation), someone
wants gold now badly enough to pay up: a shortage signal.

**[P]**
- Cost of carry: `F = S × exp((r − l + s) × T)`, with r the funding rate of the quote currency, l the gold lease rate
  (what a borrower of metal pays), s storage/insurance. Gold is almost always in contango because r ≫ l.
- **Implied carry** from two futures months: `c = ln(F2/F1) × 365/days(F1→F2)`. On COMEX, compare c with SOFR/T-bills:
  `implied lease ≈ r − c` (ignoring storage). On MCX, the carry embeds the **rupee** rate: `c_MCX ≈ c_COMEX + (r_INR −
  r_USD)` by covered interest parity; the INR forward premium (historically 1–4%/yr) makes MCX contango steeper in %
  than COMEX's. **A steeper MCX curve is not a bullish Indian signal; it is interest-rate differential.**
- **Backwardation** in gold is rare and meaningful: Nov 2008, 2013 (post-crash physical demand), Jan–Feb 2025 (tariff
  scare: front COMEX bid above London spot, EFP $40–60). On MCX, apparent backwardation across a Budget date usually
  means the market is pricing a **duty cut** into the later month, not physical tightness. Read the calendar first.
- Roll yield for a long holder = −c: holding gold futures through contango costs the carry every roll (≈ 4–5%/yr in USD
  at 2024–26 rates, more in INR). This is the "no coupon" of §1.4 made explicit.

**[APP]** GOLD › CONTRACTS `c.comex` (six COMEX months with last week's ghost curve, calendar spreads, implied carry
p.a.) and `c.mcx` (the MCX chain with implied carry); one carry convention per page (against the front month). Micro-copy
§8.2.10.

## 3.4 Roll: when, cost, what it does to the data

**[B]** Before a contract expires, traders move their position to the next month: sell Dec, buy Feb. Everyone does it in
the same two weeks, so prices and open interest shift between months in a predictable pattern.

**[P]**
- COMEX: roll in the ~10 sessions before FND (Dec-26 FND = 30 Nov 2026); volume leaves the front around 2 weeks out;
  CME's "pace of roll" is the public tracker. MCX GOLD: roll in the last week before the 5th; the app's contract picker
  uses "highest OI among expiries more than 5 days away" (`pick_contract(roll_days=5)`) and the ICICI master's OI.
- Roll cost = calendar spread paid = carry (§3.3) ± liquidity. On MCX the Dec/Feb spread trades its own book; a retail
  roll is two market orders and ~2× the round-trip costs.
- Data effects: front-month **OI falls and next-month OI rises** — total-market OI is the only honest OI series across a
  roll; the **continuous price series jumps** by the spread at the roll date (back-adjust before computing returns);
  **COT is total-market** so it is roll-proof, but its *spreading* column swells in roll weeks (20 Oct 2026: non-commercial
  spreads +8,304 while longs −8,158: a roll/relative-value footprint, not a liquidation).

**[APP]** `pick_contract` (Pre-Open), `_resolve_expiry` (MCXG). Tooltip on "front (by OI)": "the month with the most
open interest at least 5 sessions from expiry; traders roll before expiry week".

## 3.5 Settlement, expiry, delivery, and choosing the contract

**[B]** Every futures contract ends. On MCX the big contracts end with physical delivery, so a trader who does not want
to receive or deliver a kilo of gold must close or roll before the delivery window. Choose the contract by what you want:
the liquid month for trading, the small contract for sizing, never a far month for a short trade.

**[P]** The contract chooser the owner asked for, as a decision table:

| Purpose | Choose | Why | Avoid |
|---|---|---|---|
| Intraday / swing, ₹ sizing > ₹10 lakh risk capacity | **GOLD front** (Dec-26 now) | most metal, tightest spread, OI 16.6k lots | far months (Apr-27: thin, wide) |
| Swing with 1% account risk on a ₹5–20 lakh account | **GOLDM front** (Nov-26, then Dec-26) | ×10 multiplier makes ATR-stops affordable (§7.6) | GOLD (₹100 tick, ₹8.8 lakh margin) |
| Learning with real ticks, pocket money | GOLDPETAL / GOLDGUINEA | ₹1 per ₹1, margin ≈ ₹900–7,000 | treating them as a liquidity benchmark (they are thin per lot) |
| Holding through a COMEX roll (mid/late Nov) | the MCX month that **matches the next COMEX active month** (Feb-27 ↔ GCG27) | the overlay compares like with like; MCX Dec vs COMEX Feb mixes carry into "premium" | mismatched months in the premium calc |
| Expressing "gold up, rupee flat" | GOLD/GOLDM **plus short USD/INR futures** (§7.4) | strips the rupee leg | believing MCX gold is a pure gold bet |
| Delivery / physical arbitrage | GOLD or GOLDM with a delivery-enabled broker, before tender | 995 bars at Ahmedabad; assay rules | retail accounts (brokers auto-square-off) |

**[P]** Dates on the roll calendar (`c.roll`; computed by `active_expiries`, verified against the ICICI master):
GOLD 4 Dec 2026 / 5 Feb 2027 / 5 Apr 2027; GOLDM 5 Nov / 4 Dec / 5 Jan; PETAL & GUINEA 30 Oct / 30 Nov / 31 Dec. COMEX
GCZ26 FND 30 Nov 2026, LTD ≈ 29 Dec 2026.

**[APP]** GOLD › CONTRACTS `c.selector` (shared with MCXG) and `c.roll`; this table is the LEARN companion of the
selector; per-column tooltips in §8.1.12.

## 3.6 Basis and EFP

**[B]** *Basis* is the gap between the futures price and the cash price. *EFP* (exchange for physical) is the trade
dealers use to swap a futures position for real metal in London; its price is the COMEX–London spread. When bars cannot
move, the EFP explodes and the futures price detaches from spot.

**[P]**
- `basis = F − S` (quote: $/oz for COMEX front vs loco London spot; ₹/10 g for MCX vs IBJA/dealer spot). Fair basis =
  carry (§3.3); the **residual basis** (actual − fair) is the stress gauge.
- EFP = futures-vs-spot swap, quoted by bullion banks as a spread; positive and wide = NY bid for metal (Mar 2020: $70+;
  Jan–Feb 2025: $40–60 on tariff fears, COMEX stocks rose above 40 Moz as metal flew in); collapsing to zero or negative =
  NY long on metal, London short.
- MCX–IBJA basis (₹/10 g): the Indian version. IBJA publishes 999/995 rates daily (AM/PM), free on `ibjarates.com`
  (verified 200: 999 ₹14,163/g, 995 ₹14,106/g on the morning of 26 Oct 2026, i.e. 995 = ₹1,41,060/10 g vs MCX Dec fair
  ₹1,44,228: +2.2%, of which Dec carry ≈ 1% and the rest local premium/expectation). Caveat: IBJA's timestamp ("Rates will
  be uploaded soon" for today's AM) means the board can be yesterday's PM; always store the date with the rate.

**[APP]** GOLD › PHYSICAL `ph.ladder` (IBJA 999 PM and the MCX front against duty-paid landed, each derived number at
its own clock) and `ph.india` (premium and basis history); IBJA is stored by the 13:45 / 18:10 jobs. PUBLISH-CONTEXT,
attributed (owner decision O-1).

---

# PART 4 — The players, and who is long or short structurally

## 4.1 The cast

**[B]** Gold has a small number of recurring characters. Miners dig it and sell it forward; refiners turn it into bars;
bullion banks stand between everyone, lending, storing and hedging; central banks hold it as a reserve; ETFs hold it
for investors; jewellers and fabricators buy it to make things; funds trade it; and retail buys coins, jewellery and
futures. Each one has a structural side.

**[P]**

| Player | What they do | Structural futures position | COT category (§6.1) | Read them via |
|---|---|---|---|---|
| **Bullion banks** (JPM, HSBC, UBS, ICBC Standard, StoneX…) | market-make OTC, vault, lend, hedge client flow, run ETF custody/APs | **net short futures** (hedging OTC longs sold to clients and physical inventory) | Swap Dealer (mostly) + Producer/Merchant | COT swap-dealer short (−238,536 on 20 Oct 2026), CFTC Bank Participation Report (monthly) |
| Refiners (Valcambi, PAMP, Argor, Rand, Indian: MMTC-PAMP) | melt scrap and doré into bars; the physical bottleneck | short futures vs metal in process | Producer/Merchant | LBMA GD List, EFP stress |
| Miners | produce ~3,600 t/yr; hedge a slice of future output | short (hedge book; small since the 2000s de-hedging) | Producer/Merchant | WGC/Metals Focus hedge-book data (paid), quarterly reports |
| Central banks | hold ~36,000 t; net buyers every year since 2010; >1,000 t/yr in 2022, 2023, 2024 (WGC) | none on COMEX; buy OTC/locally | — | WGC/IMF monthly, PBoC (~7th), RBI WSS (weekly $ value), RBI half-yearly tonnes |
| ETFs (GLD, IAU, GOLDBEES…) | hold allocated bars; create/redeem via APs | none; their flow is physical | — | SPDR daily tonnes (now a PDF), WGC weekly/monthly flows |
| Jewellers / fabricators (India, China, Turkey, Gulf) | ~2,000 t/yr jewellery; buy spot, hedge inventory | short futures (inventory hedge) or long (pre-season) | Producer/Merchant (MCX: "hedgers") | India premium/discount, SGE premium, trade data |
| CTAs / managed futures / macro funds | trend and macro trading in size | **the swing long**; occasionally net short (Oct 2023: −7,561) | Managed Money | COT MM net, COT index, number of traders |
| Family offices, prop desks, unregistered funds | discretionary | mixed; in 2025–26 a large **net long** (other reportables +95,659 on 20 Oct 2026) | Other Reportables | COT |
| Retail (futures) | small lots | net long, sentiment-driven | Non-reportable | COT non-reportable; MCX participant-wise OI (if MCX publishes it: UNVERIFIED) |
| Indian importers: nominated agencies, banks, IIBX | import under RBI/DGFT rules | hedge on MCX/COMEX | — | DGCI&S monthly imports, RBI, customs tariff value |
| Governments | duty, quotas, sanctions, reserve freezes | — | — | Budget, CBIC, PBoC quotas |

**[P]** The structural picture in one line, with the 20 Oct 2026 numbers: **commercials are net short 235,582 contracts (73% of
OI on the short side) and almost all of it is swap dealers (−220,799), not miners (−14,783); non-commercials are net long
(managed money +104,206, other reportables +95,659); retail is net long +35,717.** This is the normal shape of the gold
market since 2016: hedgers short, investors long. The *change* in these numbers, not the level, is the information (§6.1).

## 4.2 Physical flow in round numbers (WGC Gold Demand Trends, annual; approximate, for scale)

**[B]** Gold is a stock, not a flow: about 216,000 tonnes exist above ground and a year of mining adds under 2 % of it,
so the price is set by who wants to hold what already exists — investors and central banks — not by this year's mine
output.

**[P]** Supply ≈ 4,800 t/yr: mine ≈ 3,600 t + recycling ≈ 1,200 t. Demand ≈ jewellery 2,000 t + bars & coins 1,200 t + central
banks 1,000 t + technology 300 t ± ETF flows (−250 to +900 t in a given year) ± OTC/other (the balancing item, which
the WGC itself labels as including unreported OTC investment). Above-ground stock ≈ 216,000 t (a 21 m cube), of which
jewellery ≈ 45%, private investment ≈ 22%, central banks ≈ 17%. Annual mine supply is ≈ 1.7% of the stock: **gold is a
stock market, not a flow market — price is set by who wants to hold the existing stock, not by this year's mine output.**
That is why "supply/demand" for gold means investor + central-bank demand, and why the COT and ETF data matter more than
mine news.

**[APP]** GOLD › MONTHLY `m.balance` (the WGC quarterly balance sheet, attributed, display-only); the round numbers above
are the LEARN version.

---

# PART 5 — What moves gold, and the regimes

## 5.1 Real yields

**[B]** Gold pays nothing. When safe bonds pay a lot *after inflation*, holding gold costs you that income, so gold falls;
when real yields drop or go negative, gold rises. From 2007 to 2021 this was the single best explanation of the gold
price. Since 2022 it has worked much less well, because central banks started buying gold regardless of yields.

**[P]**
- Measure: 10-year TIPS yield (FRED `DFII10`, daily, published T+1; US Treasury real yield curve CSV same day but ~20 s
  to fetch — the app already uses both). Also 5y and 2y real; the 10y is the convention.
- Mechanism: gold ≈ a zero-coupon real perpetuity; its "duration" to real yields was empirically ≈ −15 to −25 (a 100 bp
  fall in the 10y real yield went with +15–25% in gold) during 2007–2021. **2022–2026 broke the level relationship**: the
  real yield rose from −1.1% (Aug 2020, gold $2,075) to +2.64% (22 Oct 2026) while gold went from $2,075 to ~$4,000. The
  direction still matters day to day (a 10 bp real-yield jump on a CPI print still knocks gold), the level no longer
  anchors it. Reason in §5.3.
- Evidence: Erb & Harvey, "The Golden Dilemma" (Financial Analysts Journal 2013; SSRN 2078535 — SSRN answered 403 to
  this machine, standard reference): the real gold price mean-reverts over decades and gold is an unreliable short-run
  inflation hedge; the real-yield correlation is strong in-sample but regime-dependent. The app's own data
  (`context` row "10-year real yield") is signed "supportive/headwind" by the *change since the MCX close*: that is the
  right use (direction), and the LEARN tooltip must say so.

**[APP]** the header strip (10-y real yield, T+1) and GOLD › MACRO `mc.drivers` (history, percentile, 60-day
correlation), `mc.health` (the rolling correlation and the betas by regime). PUBLISH-CORE; one driver panel, no second
plot.

## 5.2 The dollar

**[B]** Gold is priced in dollars, so when the dollar weakens against other currencies, gold tends to rise in dollar
terms (and vice versa). For an Indian trader there are two dollars: the world dollar (DXY) that moves COMEX, and USD/INR
that moves MCX on top.

**[P]** DXY (ICE, 57.6% euro) and the Fed's broad index (FRED `DTWEXBGS`, 121.40 on 16 Oct 2026; T+~7 days) are the
measures. Correlation of daily changes with gold ≈ −0.3 to −0.5 historically; it weakens in crises when both rise
(Mar 2020, 2022 H1, Apr 2025). The MCX exposure is `∂MCX/∂USDINR ≈ settlement/USDINR ≈ ₹1,539 per ₹1` (26 Oct 2026). The
EUR/USD "trigger" on the desk (1.1161 default) is the owner's own level: context, no study behind it.

**[APP]** USD/INR on the header strip and `mc.drivers`; the dollar tile on `h.gauges` and `mc.drivers` names the series it
uses (DXY from stored bars, or FRED's broad index DTWEXBGS with its ≈ 1-week lag when that is all the store has — never
the one under the other's name); `mc.kgx` splits a move into gold and the dollar. PUBLISH-CORE for USD/INR; CONTEXT for
the dollar.

## 5.3 Central-bank buying

**[B]** Since 2010 central banks have been net buyers of gold every year, and since 2022 — after Russia's dollar reserves
were frozen — they have bought more than 1,000 tonnes a year (about a quarter of annual supply). They buy for reserve
diversification, not for price, so they keep buying when funds sell. That is the main reason the real-yield rule broke.

**[P]** WGC (IMF IFS + central-bank reports): 2022 ≈ 1,082 t, 2023 ≈ 1,037 t, 2024 ≈ 1,045 t (WGC annual Gold Demand
Trends; approximate). Leaders: PBoC (reports monthly via SAFE around the 7th; pauses and restarts are market events),
Poland, Turkey, India (RBI ≈ 880 t by 2025 after buying 70+ t in 2024; weekly WSS shows the $ value, tonnes in the
half-yearly reserve-management report), Czech, Singapore, Kazakhstan, Uzbekistan. Reporting lag 1–2 months; some buying
is unreported (the WGC's "OTC and other" balancing item). Evidence of predictive value: **context only** — the flow is
steady and lagged; it explains the level regime, not next week.

**[APP]** GOLD › PHYSICAL `ph.official` (IMF holdings as Moz and tonnes, each with its data month; the PBoC streak; RBI
weekly value and share) and MONTHLY `m.official` (net purchases over 12 months). PUBLISH-CONTEXT.

## 5.4 ETF flows

**[B]** Gold ETFs buy and vault physical bars when investors put money in and sell them when money leaves. Their tonnage
is public daily, so it is the cleanest daily read on Western investor demand.

**[P]** GLD (largest; ~900–1,000 t range in 2024–26) publishes "Total Net Asset Value Tonnes in the Trust" daily; the
historical CSV the project once used **now returns a PDF** (verified 26 Oct 2026: `GLD_US_archive_EN.csv` → `%PDF-1.5`,
697 KB) — the page itself is 200 and the number is readable in a browser. iShares IAU page verified 200 (1.6 MB,
JS-heavy). WGC aggregates all funds weekly and monthly (page verified: "Flows and holdings data are updated on the
website weekly and monthly… xlsx monthly", latest "Gold ETF Flows: September 2026"). Indian gold ETFs: AMFI monthly AUM
(₹), tonnes via WGC.
Evidence: flows are **contemporaneous** with price (they are the price's footprint in Western demand), forward
predictive power is weak and regime-dependent (2013: −880 t with −28%; 2020: +877 t with +25%; 2022–23 outflows while
price held because of §5.3). Use as "who is buying", not "what is next". **Context only.**

**[APP]** GOLD › PHYSICAL `ph.etf` (GLD tonnes daily since 2004 with changes, IAU, WGC weekly flows by region;
display-only, attributed, O-1) and the ETF tile on `h.gauges`. PUBLISH-CONTEXT.

## 5.5 Risk-off and the safe-haven claim

**[B]** In a crisis people buy gold — usually. But in the first days of a liquidity crash (Mar 2020, Oct 2008) gold falls
with everything else because it is the asset people *can* sell. The safe-haven effect comes after the margin calls.

**[P]** Baur & Lucey (2010, Financial Review) and Baur & McDermott (2010, JBF): gold is a hedge for equities on average
and a *safe haven in extreme stock-market days*, but the effect fades within ~15 trading days. Practical reading: gold's
first move on a shock is noise (liquidation), its second move is the signal. The desk's "event risk" headline count
(risk words in the last 24 h) is a tally with **no study behind it**: it wears a `heuristic` chip and gives no sizing
advice.

**[APP]** GOLD › HEALTH `h.headlines` (the risk-word count with its `heuristic` chip).

## 5.6 Inflation expectations

**[B]** Gold is sold as an inflation hedge. Over decades it roughly keeps its purchasing power; over months it does not
track inflation at all. The market watches *expected* inflation (breakevens) because that, with nominal yields, sets the
real yield.

**[P]** `real yield ≈ nominal (DGS10 4.96%) − breakeven (T10YIE 2.34%)` ≈ 2.62% (22–23 Oct 2026; FRED DFII10 2.64%:
consistent). Erb–Harvey: gold/CPI ratio has swung 2× to 8× — a "hedge" with a 4× range is not a hedge at a 1-year horizon.
A CPI print moves gold through the real-yield channel in the first minute (§7.5).

**[APP]** `mc.drivers` shows the breakeven (T10YIE) beside the real yield. PUBLISH-CONTEXT.

## 5.7 Positioning extremes

**[B]** When nearly everyone who might buy has already bought, there is no one left to push the price up; the same in
reverse. The COT shows how crowded the speculative side is.

**[P]** COT index (§6.1) at > 90 or < 10 on the 52-report or 3-year window is what desks call "crowded". **Our own study
says it does not forecast** (G-STUDY, 26 Oct 2026: 1,063 reports 2006→2026, every signal dated at its Friday release,
Newey-West t, 0.15% costs): rank IC at 1/4/13 weeks ≈ 0 for every positioning metric; the classic rule points the wrong way
(crowded weeks +1.08% vs washed-out +0.63% over the next 4 weeks); 0 of 69 walk-forward long/flat rules beat scaled
buy-and-hold. The academic record agrees (Sanders, Irwin & Merrin 2009; Wang 2003 — standard references, not live-verified),
and our NSE analogue (`reports/fii_positioning/FINDINGS.md`) failed the same way. What the COT does do, strongly and stably,
is **describe the week that just ended** (Δ fund net vs the week's move: Spearman +0.65, stable by sub-period, next week
−0.02). So: PUBLISH-CONTEXT; the `p.crowd` gauge is worded "crowdedness, not a signal" and never coloured; nothing on the
page sizes or times a trade on it.

## 5.8 The rupee, duty and policy (the Indian layer)

**[B]** Indian gold = world gold × rupee + duty. The rupee is set by RBI policy, oil, flows and the dollar; duty is set
by the Finance Ministry in the Budget (1 Feb) and occasionally between budgets. Both can move MCX gold with COMEX flat.

**[P]** Rupee drivers to watch: USD/INR spot and the FBIL reference rate (13:30 IST; fbil.org.in verified 200), RBI
intervention (WSS weekly: reserves, forward book), oil (India's import bill), FPI flows (already in MKT). Duty history:
10% (2013) → 12.5% (2019) → 15% incl. AIDC (Jul 2022) → 6% (23 Jul 2024) → **15% (BCD 10% + AIDC 5%) from 13 May 2026,
Notification 16/2026-Customs** (MCX June gold rose 6–7% that day; Budget Feb 2026 had left it unchanged). The primary CBIC
page is unreadable to scripts, so the owner confirms the rate and the fortnightly tariff-value practice in a browser (PLAN
O-3); Budget 1 Feb 2027 can change it again. A duty change is the one scheduled event where MCX gaps *against* COMEX. §7.5 has the playbook. Seasonality:
Dhanteras/Diwali (Oct–Nov), weddings (Nov–Jan, Apr–May), Akshaya Tritiya (Apr/May); the premium/discount responds, the
world price barely does (**context only**; no study).

**[APP]** USD/INR on the GOLD header strip and `mc.drivers`; the FBIL rate stored daily (`USDINR_FBIL`); the duty as a dated
constant (`GOLD_IMPORT_DUTY_PCT`, `DUTY_HISTORY`) printed on `ph.ladder`; duty steps annotated on `ph.india`.

## 5.9 Regimes 2001–2025: what drove each

**[B]** Gold has had five different "reasons" in 25 years — the dollar and real yields, then rising yields, then a range,
then QE, then central banks. Each regime's rule stops working in the next one; the table shows what drove each.

**[P]** The regimes, with what the data looked like:
| Period | Price path ($/oz, LBMA PM approx.) | Dominant drivers | What the data looked like |
|---|---|---|---|
| 2001–2011 | $256 (Apr 2001) → $1,895 (Sep 2011; $1,921 intraday) | dollar bear 2002–08, real yields falling, GFC + QE1/QE2, ETF era (GLD Nov 2004), China/India demand, central banks turn net buyers (2010), miners de-hedge | MM net long builds to records 2011; ETFs +2,000 t; backwardation scare Nov 2008 |
| 2011–2015 | → $1,046 (Dec 2015) | real yields rise (2013 taper tantrum: gold −28% in 2013, the worst year since 1981), dollar bull 2014–15, ETF outflows (−880 t in 2013), Fed lift-off Dec 2015 | MM net short episodes (2013, 2015); Chinese/Indian physical buying on dips (SGE premium spikes); India duty to 10% and 80:20 rule |
| 2016–2019 | $1,050–$1,550 range; breakout Jun 2019 | Fed hikes 2016–18 cap it; 2019 Fed pivot, $17 trn negative-yielding debt, trade war | MM swings ±200k; central banks 650 t/yr |
| 2020–2021 | $1,450 (Mar 2020 liquidity crash) → $2,075 (Aug 2020) → ~$1,800 chop (2021) | real yields to −1.1%, QE4, ETF record +877 t, EFP blow-out (bar logistics); 2021 real yields rise, ETF outflows | April 2020: 4GC contract; COMEX stocks 8 → 38 Moz |
| 2022–2025 | 2022 flat (~$1,800); 2023 +13% ($2,063); 2024 +27% ($2,620); 2025 $3,000 (Mar), $3,500 (Apr), $4,000 (Oct), record ≈ $4,380 then a ~6% one-day washout (late Oct 2025) | fastest Fed hikes ever **but** central banks > 1,000 t/yr after the Russian reserve freeze; PBoC streak; geopolitics; US tariff shock Apr 2025; India duty cut Jul 2024 (MCX −5–6% that day); ETF inflows resume 2024–25 | the real-yield level link breaks; MM net long peaks ≈ 219k (3-yr max in our CFTC pull); other reportables grow into a second structural long; EFP/warehouse episode Jan–Feb 2025 |
| 2026 | read from CHRT / WEI; this document's knowledge ends June 2026 | — | our pull: MM net fell from 144,747 (52-wk max) to 104,206 by 20 Oct 2026 while gold ≈ $4,000; USD/INR ≈ 95; MCX premium 18% |

**[P]** Reading rule: the driver of the **next** regime is the one the current regime's rule ignores. In 2026 the real-yield
rule says gold is too high; the central-bank rule says yields do not matter; the positioning rule says the crowd is
leaving. A panel that shows all three with history is worth more than any one of them.
