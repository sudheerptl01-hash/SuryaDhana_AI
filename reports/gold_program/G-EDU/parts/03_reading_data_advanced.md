
---

# PART 6 — Reading the data

## 6.1 The Commitments of Traders (COT) report

**[B]** Every Friday evening (US time) the CFTC, the US futures regulator, publishes who held COMEX gold futures as of the
previous Tuesday: commercial hedgers, big speculative funds, and small traders, long and short. It is the only public
window on *who* is positioned in gold. It is a week old when you read it and it covers COMEX only, not London, Shanghai
or MCX. The page sums the week up in one label: the larger of the two fund moves names it — and when price fell while
funds still added more longs than shorts, the label is "funds bought the dip".

**[P]** Anatomy, using the actual 20 Oct 2026 legacy block (CFTC short format, `cftc.gov/dea/futures/deacmxsf.htm`,
verified 200):
```
GOLD - COMMODITY EXCHANGE INC.                                       Code-088691
FUTURES ONLY POSITIONS AS OF 10/20/26
      NON-COMMERCIAL      |   COMMERCIAL    |      TOTAL      | NONREPORTABLE
  LONG  | SHORT  |SPREADS |  LONG  | SHORT  |  LONG  | SHORT  |  LONG  | SHORT
(CONTRACTS OF 100 TROY OUNCES)                       OPEN INTEREST:      402,279
COMMITMENTS
 237,142   37,277   54,199   59,531  295,113  350,872  386,589   51,407   15,690
CHANGES FROM 10/13/26 (CHANGE IN OPEN INTEREST:      5,934)
  -8,158     -144    8,304    5,112   -1,837    5,258    6,323      676     -389
PERCENT OF OPEN INTEREST FOR EACH CATEGORY OF TRADERS
    58.9      9.3     13.5     14.8     73.4     87.2     96.1     12.8      3.9
NUMBER OF TRADERS IN EACH CATEGORY (TOTAL TRADERS:      288)
     158       59       69       53       42      241      143
```

**[P]** Line by line:
- **Code 088691** = COMEX gold (100 oz). **Micro gold is a separate line (088695)**; do not add them (10 oz each) without
  scaling by 0.1.
- **Open interest 402,279** contracts × 100 oz = 40.2 Moz ≈ 1,251 t (≈ 1/3 of annual supply, ≈ 4 months of mine output).
  "Futures only": there is a second table "futures and options combined" (options delta-adjusted; 20 Oct 2026 OI
  532,443). Use futures-only for positioning, combined for crowding.
- **Legacy categories**: *Non-commercial* = speculators above the reporting level (gold: 200 contracts); *commercial* =
  hedgers; *non-reportable* = everyone below the level (retail + small pros). Spreads = positions held long in one month
  and short in another (relative value, roll).
- **Identity**: long sum = short sum = OI: 237,142 + 54,199 + 59,531 + 51,407 = 402,279 ✓. Any net you compute must
  sum to zero across categories (§4.1 does).
- **Changes** are week over week (Tuesday to Tuesday). Here non-commercial longs −8,158 while spreads +8,304 and OI
  +5,934: positions moved *from outright to spread* (roll footprint, GCZ26 FND 30 Nov), not a liquidation. Reading
  changes without the spread column is the commonest COT error.
- **% of OI** tells you crowding; **number of traders** tells you breadth (158 reportable longs vs 59 shorts; a rally on
  a rising count is broad, on a falling count is concentrated).
- **Disaggregated** report (same page family, `other_lf.htm`, verified 200): splits commercial into **Producer/Merchant/
  Processor/User** (miners, refiners, jewellers, physical dealers) and **Swap Dealers** (banks hedging OTC swaps); splits
  non-commercial into **Managed Money** (CTAs, CPOs, hedge funds) and **Other Reportables**. 20 Oct 2026, futures only:
  PM 19,715 L / 34,498 S; SD 17,737 L / 238,536 S / 22,079 spread; MM 120,970 L / 16,764 S / 38,634 spread (78 long
  traders, 25 short); OR 116,172 L / 20,513 S / 15,565 spread; NR 51,407 L / 15,690 S. Changes: MM long −3,777, MM short
  −894 (longs leaving and shorts covering at once: a quiet de-grossing, not a directional bet); PM short −2,325 (hedgers
  lifting hedges into a dip: supportive); SD long +3,761.
- **Concentration**: top-4 traders' gross share: long 20.4%, short 37.8%. The short side of gold is always concentrated
  (a few banks); a rising short concentration with falling price is "the banks are pressing", with rising price it is
  "the banks are being squeezed" — context only.

**[P]** **Derived metrics**
1. **Net position** per category: `net = long − short` (spreads excluded). MM net +104,206 (20 Oct 2026).
2. **Net as % of OI**: 104,206 / 402,279 = 25.9%.
3. **COT index** (the "stochastic" of positioning): `100 × (net − min_N) / (max_N − min_N)` over N weeks (26, 52, 156).
   Worked, from our 160-week pull (`cot_gold_mm_history.csv`): 52-week min 89,752, max 144,747 → **(104,206 − 89,752) /
   (144,747 − 89,752) = 26.3**; 3-year (156-week) range 34,176 → 219,029 gives **37.9**. Reading: managed money is in the
   lower third of its 1-year range after five straight weekly declines (133,116 on 15 Sep → 104,206), with gold still near
   $4,000: speculators have been *leaving a rising/flat market*, which is the opposite of a crowded top.
4. **Weekly change in net** and its z-score over 52 weeks (a ±2σ week is a positioning event).
5. **Long/short ratio** (MM): 120,970 / 16,764 = 7.2 (very long-skewed; above 10 is rare).
6. **"Who closed what"** (the owner's words): per category, `Δlong` and `Δshort` with signs: closed longs = negative
   Δlong; closed shorts (short covering) = negative Δshort; new longs = +Δlong; new shorts = +Δshort. The 20 Oct 2026
   row: MM closed 3,777 longs and covered 894 shorts; producers covered 2,325 shorts and added 1,329 longs; swap
   dealers added 3,761 longs and 466 shorts; other reportables closed 4,381 longs (120,553 → 116,172) and added 750 shorts.
7. **Fund-driver label** (`p.hero`; the HEALTH verdict's H3 clause; WEEKLY `w.whodid`): the larger of the two managed-money
   legs names the week — one rule, `services/data-service/gold/driver_rule.py`, mirrored by ui-api. ΔL / ΔS are the w/w
   changes in managed-money long / short contracts, the week's direction is the Tue→Tue price change. Down-week: `long
   liquidation` if ΔL < 0 and |ΔL| ≥ |ΔS|; `new shorts` if ΔS > 0 and ΔS ≥ |ΔL|; else `funds bought the dip` (the bigger leg
   moved against the price: net length added). Up-week, mirrored: `short covering` if ΔS < 0 and |ΔS| ≥ |ΔL|; `new longs`
   if ΔL > 0 and ΔL ≥ |ΔS|; else `funds sold into it` (net length cut). Ties go to the leg that moves with the price.
   Narration of the week that ended (G-STUDY §5.2: right ≈ 3 weeks in 4 as narration), never a forecast. The 27 Oct 2026
   week — price −1.64 %, +1,538 longs, +182 shorts, net +1,356 — reads "funds bought the dip" (ΔS 182 < ΔL 1,538); the
   earlier rule, which tested the sign of ΔS before its size, called it "new shorts" (C-TRADER-3 / C-BEGINNER-1, fixed
   5 Nov 2026).

**[P]** **Patterns, in the data** — the table:
| Pattern | Price | MM long | MM short | OI | Usual meaning |
|---|---|---|---|---|---|
| Fresh long build | ↑ | ↑ | flat | ↑ | trend being bought; healthy while traders-count rises |
| **Short-covering rally** | ↑ | flat/↓ | **↓ sharply** | ↓ | shorts forced out; rally has no new buyers → fades unless longs follow next week (Mar 2024 start: MM short fell from ~90k while longs rose: that one *did* get followed) |
| Long liquidation | ↓ | ↓ sharply | flat | ↓ | crowded longs leaving (late Oct 2025 washout) |
| Short build | ↓ | flat | ↑ | ↑ | new bets against; sets up the next covering rally if price turns |
| De-grossing | flat | ↓ | ↓ | ↓ | risk-off in funds (Oct 2026 weeks) |
| Roll footprint | any | ↓ | ↓ | spreads ↑ | ignore; look again after FND |

**[P]** **Timing in IST**: data as of Tuesday close; released **Friday 15:30 ET = Saturday 01:00 IST (US DST) / 02:00 IST (from
7 Nov 2026 onward, US standard time)**; so the first MCX session that can trade it is Monday 09:00 — six days after the
data. Federal holidays shift releases to Monday (the CFTC release-schedule page, verified 200, lists them; the page's
date text is rendered in JavaScript, so parse the table in a browser or hard-code the holiday shifts).

**[P]** **Access**: free, no key. Socrata API `publicreporting.cftc.gov/resource/72hh-3qpy.json` (disaggregated futures-only),
`kh3c-gbw2` (disaggregated combined), `6dca-aqww` (legacy futures-only); filter
`market_and_exchange_names='GOLD - COMMODITY EXCHANGE INC.'`; JSON, ~1.3 s, 186 fields, verified 26 Oct 2026 with latest
`report_date_as_yyyy_mm_dd = 2026-10-20`. History zips by year (`fut_disagg_txt_2026.zip`, 2.0 MB, verified). An app
token is optional (higher rate limits). Terms: US government data, public domain.

**[P]** **Pitfalls** (the tooltip list): (1) Tuesday data read on Monday; (2) spreads ≠ direction; (3) micro gold separate;
(4) futures-only vs combined; (5) reporting-level changes shift history; (6) the categories are self-declared on CFTC
Form 40 — a bank's prop desk can sit in "swap dealer"; (7) COMEX ≠ the world: LBMA OTC is 5–10× larger and has no COT;
(8) a record net long is only a record until the next one (2020, 2024, 2025 all set records before rising further).

**[P]** **Evidence**: §5.7 — context only. **G-STUDY ran (26 Oct 2026, `reports/gold_program/G-STUDY/FINDINGS.md`)**: 1,063 reports 2006→2026, signals dated at
the Friday release, entry the next session, Newey-West, 0.15% costs. **FAIL as a forecast** at 1/4/13 weeks for every
metric (net, % OI, COT index, z, 4-week change, commercials, small specs, OI, options-only, GLD Δ, real-yield Δ, DXY Δ);
0 of 69 walk-forward rules beat scaled buy-and-hold. **PASS as description**: the same-week Δ fund net vs price Spearman is
+0.65. Hence the panel's label — *explains the week, does not forecast* — and no COT alert, rule or colour anywhere.

**[APP]** GOLD › POSITIONING `p.hero` (net, the change in words, the fund-driver label), `p.whois` (who is long / short,
closed / covered chips), `p.history`, `p.crowd` (COT index, z-scores, a percentile over the window it names — never
coloured), `p.drawer` (trader counts, concentration, micro gold, the options line, the raw block); the weekly "who did
what" line is echoed on WEEKLY `w.whodid` and in the HEALTH verdict's H3 clause. Micro-copy §8.2.2.

## 6.2 Daily open interest with price: the four quadrants

**[B]** Open interest (OI) is the number of contracts alive. Price and OI together say whether a move is being made by
new money entering or old money leaving. Rising price with rising OI = new buyers; rising price with falling OI = shorts
escaping; falling price with rising OI = new sellers; falling price with falling OI = longs giving up.

**[P]** The quadrant map (the NSE vocabulary the terminal already uses on DERV):

| ΔPrice | ΔOI | Name | Who | Confidence rule |
|---|---|---|---|---|
| + | + | **Long build-up** | new longs vs new shorts; longs winning | strongest with rising volume and rising number of traders (COT) |
| + | − | **Short covering** | shorts closing; no new conviction | fades unless OI turns up within days |
| − | + | **Short build-up** | new shorts vs new longs; shorts winning | strongest into a known event (FOMC, Budget) |
| − | − | **Long unwinding** | longs closing | typical of post-record washouts |

**[P]** Rules: (1) use **total OI across all months** (sum of contracts) — single-month OI is destroyed by the roll; (2) compare
to the 20-day average ΔOI, not raw; (3) expiry days (MCX 5th, COMEX LTD) drop OI mechanically; (4) for MCX, OI per
contract comes from the exchange bhavcopy (blocked for bots; browser/broker) or ICICI's master (yesterday's OI only, no
history); for COMEX, CME's daily bulletin / volume-OI page (browser only; the CFTC COT carries weekly total OI as a
free fallback); (5) the quadrant is a **description**, not a forecast — the DERV page's own evidence standard applies.

**[APP]** GOLD › DAILY `d.quadrant` and POSITIONING `p.daily.comex` (CME FTP, T+1; history since 2014 once the backfill
lands) / `p.daily.mcx` (ICICI master at 07:35; history since the job started). A day whose OI file has not landed has no
label yet (the API sends none; T+1); roll and expiry days are greyed `mechanical`. PUBLISH-CONTEXT.

## 6.3 COMEX warehouse stocks

**[B]** COMEX publishes every day how much gold sits in its approved New York vaults and how much of it is "registered"
(has a warehouse receipt and can be delivered against a futures contract). Metal flowing in means someone wants
deliverable gold in New York; registered metal rising means more inventory is ready for delivery.

**[P]** Categories: **Registered** (warrant issued; deliverable), **Eligible** (meets spec, stored, no warrant — can be
registered in a day), **Pledged** (registered metal posted as clearing collateral; reported separately since 2020 — check
the report footnote for whether it is netted). `Total = registered + eligible`. Metrics: registered/OI coverage (`registered
oz / (OI × 100)`: 20 Oct 2026 OI = 40.2 Moz; a typical registered stock of 15–25 Moz gives 40–60% "coverage" — social
media calls the inverse "owners per ounce"; **deliveries are ≈ 1–3% of OI per month, so coverage is context only**),
daily net inflow (tonnes), and the **delivery notices** report (first-notice-day tallies) which is the real physical
demand on COMEX. Episodes: Mar–Jul 2020 (8 → 38 Moz as banks shipped metal to cover EFP shorts), Jan–Feb 2025 (to > 40 Moz
on tariff fears), outflows thereafter as the EFP normalised.
Access: `cmegroup.com/delivery_reports/Gold_Stocks.xls` — **403 for non-browser clients** (26 Oct 2026); readable in a
browser; CME's data terms restrict redistribution of real-time data but the warehouse report is public. UNVERIFIED as a
feed from this machine.

**[APP]** GOLD › PHYSICAL `ph.comex.stocks`: link-only tiles until the owner resolves CME's block (O-2); the daily
per-product OI and the EFP prints come from the CME FTP instead.

## 6.4 ETF holdings and flows

**[B]** Gold ETFs own real bars in a vault: when money comes in they buy bars, when it leaves they sell. Their tonnage is
published daily, so it is the simplest daily read of Western investors — and it moves *with* the price, not ahead of it.

**[P]** See §5.4 for the evidence. Read: **tonnes, Δtonnes (1d/5d/20d), flows in $ (WGC)**, and the *divergence* between price and
tonnes (price up / tonnes down in 2022–23 = non-Western buying; price flat / tonnes up = Western accumulation into
weakness). Pitfall: GLD's daily number is at the US close; Indian ETF AUM (AMFI) is monthly and in ₹ (includes price
effect — convert to tonnes via WGC).

**[APP]** GOLD › PHYSICAL `ph.etf`, the ETF tile on `h.gauges`, the GLD Δ t column on `w.table`; micro-copy §8.2.5.

## 6.5 LBMA trade data and London vault holdings (the OTC window)

**[B]** London is where most gold changes hands, between banks, in private. There is no report of who is long or short
there — only how much traded each week and how much metal sits in London vaults each month. Activity and stock, never
positions.

**[P]** Read: weekly turnover ($ bn and Moz) — rising turnover with rising price = active two-way institutional
market; vault tonnes monthly (9,821 t end-Sep 2026, +1.96% m/m) — a rising London stock while COMEX stocks fall = metal
returning East→West or being re-allocated; the Bank of England share (central banks' custody) in the same release. Lag: 1
month+ for vaults, 1 week for turnover. Evidence: context only; no public study links LBMA turnover to returns.

**[APP]** GOLD › PHYSICAL `ph.otc` (LBMA-i weekly turnover in $ bn, 12-week average; London vault tonnes, monthly; CME EFP
round turns). PUBLISH-CONTEXT (the WGC / LBMA rows are gated on O-1).

## 6.6 SGE premium and the Indian premium/discount

**[B]** Compare the local price (Shanghai, or India) with the world price after converting units and currency. A premium
means local buyers are paying up (demand or import friction); a discount means they are not.

**[P]** SGE: §2.3 formula, in $/oz. India: `premium_$ = (IBJA_999 ₹/10 g × 31.1035/10 ÷ USDINR) / (1 + duty) − COMEX spot`
… but the dealer premium Reuters quotes is *over the duty-paid official price* in $/oz (−$50 to +$20 typical; −$14 → +$3
through Oct 2026); the old overlay's **implied premium** (18.0% on 26 Oct 2026) was a duty-inclusive quantity and is now
split into the dated 15% duty and the **MCX basis vs duty-paid landed** (+3.1% that morning, ≈ 1% of it carry). Three
definitions, three panels (`ph.ladder`, `ph.india`, `ph.shanghai`); never mix them, and sample both legs at the same minute
(NY close vs the IBJA afternoon fix gave a spurious +0.9%, G-INDIA §5.3; SGE PM vs LBMA PM are 7 hours apart). Reading: a widening Indian discount into Dhanteras is a demand failure; a premium with a weak
rupee is import-channel stress; a jump on a Budget day is duty. Evidence: context only.

**[APP]** `ph.ladder` (the stack, live for the first three bars), `ph.india` (IBJA premium and MCX basis history with the
duty steps), `ph.shanghai` (SGE PM vs London PM / COMEX at 14:15 Beijing, both timestamps shown); IBJA AM/PM and the SGE
daily table are stored by the 13:45 / 16:10 / 18:10 jobs, so the history starts the day they start.

## 6.7 Gold/silver ratio

**[B]** How many ounces of silver buy one ounce of gold. Around 60–80 for most of the last 20 years; above 90 silver is
cheap relative to gold (deflation/risk-off fear); below 60 silver is expensive (reflation, industrial boom).

**[P]** `GSR = gold $/oz ÷ silver $/oz`. Range since 2000: ≈ 32 (Apr 2011) to ≈ 125 (Mar 2020). Silver's beta to gold ≈
1.5–2 with an industrial component (solar, electronics); the ratio trends for years, so "extreme" means vs a 2–3 year
window. Trade expression: ratio spread (long one, short the other, dollar-neutral) — on MCX via GOLD/SILVER contracts
(SILVER 30 kg lot). Evidence: mean reversion at multi-year horizons (context only; no citation we could verify live).

**[APP]** GOLD › MACRO `mc.context` (gold/silver and gold/platinum with percentiles over the window they name).

## 6.8 Real yield, breakeven, dollar: reading the driver table

**[B]** The driver tiles say whether each input helped or hurt gold *over the window shown* — a description of what just
happened, not a forecast of tonight. Falling real yields and a falling dollar are "supportive"; rising ones are
"headwind".

**[P]** `mc.drivers` signs each row by its change over the window (supportive / headwind, the rule printed beside the
tag) and shows the 60-day correlation with gold's daily change. Correct reading: these rows explain the move that
happened; they do not forecast the next one. The level (percentile over 1 year) is there for *regime*, not timing. The
T+1 lag on DFII10 is printed as the data's date; the dollar tile names the series it uses (DXY bars, or FRED's broad
index DTWEXBGS with its lag).

**[APP]** GOLD › MACRO `mc.drivers`, `mc.health`; the real-yield and dollar tiles on `h.gauges`.

## 6.9 Central-bank data

**[B]** Central banks report their gold holdings monthly, one to two months late. China's monthly number (around the
7th) — and whether it is still buying — is the one the market reacts to; India's shows up as a rupee value every Friday.

**[P]** Monthly tonnes by country (WGC/IMF, 1–2 month lag), PBoC monthly (~7th), RBI weekly $ value (WSS, verified 200; tonnes
only half-yearly). Reading: streaks (PBoC buying 18 straight months 2022–24, pause May 2024, resume Nov 2024) are
headline events; the annual total vs the 1,000 t line is the regime gauge.

**[APP]** GOLD › PHYSICAL `ph.official` (IMF ounces shown as Moz and tonnes, each with its data month; the PBoC streak;
RBI weekly value and share), MONTHLY `m.official` (net purchases over 12 months).

## 6.10 Term structure and implied carry

**[B]** The curve is the list of prices for each future month. Normally later months cost more (contango); the page turns
each step into a yearly % so MCX and COMEX can be read on one scale, and warns when the shape is unusual.

**[P]** Read §3.3. Panel reading: plot the MCX curve (Dec/Feb/Apr) and the COMEX curve as **annualised % carry** between adjacent
months, next to SOFR and the INR–USD rate gap; a COMEX carry above SOFR + storage = stress (negative implied lease);
MCX carry far below COMEX carry + rate gap into a Budget = duty-cut expectation.

**[APP]** GOLD › CONTRACTS `c.comex`, `c.mcx` (one carry convention per page: against the front month); the curve/roll
tile on `h.gauges` and the verdict's H5 clause.

## 6.11 Volatility: GVZ, realised, ATR in rupees

**[B]** Volatility is the size of typical daily moves. In gold it is quoted three ways: implied (what options expect:
GVZ), realised (what happened: the standard deviation of daily returns), and ATR (the average daily range in price
units, which is what a stop-loss needs).

**[P]** GVZ (Cboe Gold ETF Volatility Index on GLD options; Yahoo `^GVZ`, free, delayed; 429 for this machine at the time
of writing): normal 14–20, stress > 30. Realised: `σ_daily = stdev(ln returns, 20d)`; annualise × √252. ATR(14) in
₹/10 g: at 1.2% daily range and ₹1,46,000 that is ≈ ₹1,750 (26 Oct 2026; ATR14 was ₹2,820 on 5 Nov — MACRO prints today's) — the unit of every stop in §7.6. Implied minus realised
(the variance premium) is usually positive; a negative gap after a shock = options are cheap vs what is happening.

**[APP]** GOLD › MACRO `mc.move` (GVZ → a 1σ day in %, $/oz, ₹/10 g and ₹ per lot per family; realised 20-day vol; ATR14
in rupees).

---

# PART 7 — Advanced

## 7.1 Carry, GOFO and lease rates: what died and what replaced it

**[B]** Gold can be lent, like money. The interest a borrower pays in gold is the *lease rate*. Until 2015 the London
banks published a benchmark (GOFO) that let anyone compute it; they stopped, and today you have to infer it from futures
prices.

**[P]** GOFO (Gold Forward Offered Rate) = the rate at which contributing banks would lend gold on swap against US
dollars; `lease ≈ LIBOR − GOFO`. LBMA **discontinued GOFO on 30 January 2015** (benchmark-regulation burden after the
LIBOR scandal, shrinking contributor panel). Replacements: (a) **implied lease from the futures curve**:
`lease_implied ≈ r_USD − [ln(F2/F1) × 365/days]` (storage ignored); (b) bullion-bank OTC swap quotes (not public);
(c) Bloomberg/LSEG derived curves (paid); (d) the SGE Au(T+D) deferral fee (§2.3) as China's lease signal. A **negative
GOFO / high lease rate** (2013, Jan–Feb 2025) = physical tightness (longs willing to pay to hold metal now). Pitfall:
the implied number is noisy on the front spread in roll weeks; use the 2nd/3rd month pair.

**[APP]** GOLD › CONTRACTS `c.comex` (implied lease ≈ SOFR − COMEX carry, one number).

## 7.2 Options: skew, risk reversals, what gold's smile says

**[B]** Options prices reveal what the market fears. If calls cost more than equally-distant puts, the market pays for
upside protection or upside bets — common in gold, unlike stocks where puts cost more.

**[P]** `RR25 = IV(25Δ call) − IV(25Δ put)`; gold's RR25 is usually **positive** (call skew) in bull/crisis phases
(2020, 2024–25) and flips negative in liquidation phases (2013, late 2025 washout). Butterfly `BF25 = (IV25c + IV25p)/2 −
ATM` measures tail demand. GVZ is the ATM proxy. COMEX OG options: American, exercise into GC; weekly expiries. MCX
GOLD/GOLDM options: European, cash-settled into a *futures position* at expiry (§2.4 pitfall). Vol surface data is paid
(CME, Bloomberg); GVZ is the free scalar. Use: when GVZ spikes and RR flips negative on a down day, longs are buying
puts = capitulation footprint (context only).

**[APP]** OSTR (options strategy builder) exists for NSE; gold options are out of scope for the paper ticket. LEARN only.

## 7.3 Term-structure trades

**[B]** Instead of betting on the price, bet on the gap between two months. Buying the far month and selling the near
one profits if the curve steepens (carry rises); the reverse profits if the front tightens (shortage) or a duty cut is
priced into the far month.

**[P]** MCX calendar spread Dec/Feb: fair = carry (INR rate − lease + storage) × 2/12; margin benefit makes it
capital-light; P&L per ₹1 of spread = ₹100 per lot pair. Drivers: RBI/Fed rate gap, Budget duty expectations (short the
spread — short Feb vs long Dec — ahead of an expected duty cut; the Feb-27 contract spans 1 Feb 2027), physical tightness
(long front). COMEX: the Dec/Feb spread vs SOFR is the cleanest "implied lease" trade; retail rarely has the fee
structure for it. Evidence: context only; the carry itself is arithmetic, the *change* in carry is the bet.

## 7.4 Cross-exchange: MCX vs COMEX, duty, rupee, timing

**[B]** You cannot arbitrage MCX against COMEX by buying one and selling the other: the gap is made of duty, GST, the
rupee and shipping rules, not mispricing. What you *can* do is understand that an MCX gold position is three bets at
once, and hedge the ones you do not want.

**[P]** Decomposition (26 Oct 2026): `MCX_fair = COMEX × USDINR × 10/31.1035 × 0.995 × (1 + duty) × (1 + local premium) ×
(1 + carry_adj)`. Hedging the rupee: one GOLD lot ≈ 32.15 oz × $4,004 ≈ **$128,700 ≈ 129 USD/INR futures ($1,000 each,
NSE/BSE currency segment, 09:00–17:00 IST)**; a GOLDM lot ≈ 13 lots. Long GOLD + short 129 USDINR futures ≈ long gold in
dollars, financed in rupees (you keep the INR–USD rate gap as cost: that is the covered-interest cost, ≈ the MCX
contango excess). Timing: MCX trades 14.5 h, COMEX 23 h; every MCX open is a gap trade against 8.5 hours of COMEX
(the Pre-Open desk); the currency segment closes at 17:00 while MCX runs to 23:30 — **the rupee hedge is off for the
evening session** (the offshore NDF moves it, but the app has no NDF feed: Yahoo `INR=X` stops at its last evening print, so the
08:45 fair open carries no overnight rupee move and the card prints that print's time). Duty: §5.8, §7.5.

**[APP]** `ph.ladder` and `mc.kgx` (with the rupee leg) compute the pieces; the MCXG paper ticket carries
`hedge_usdinr_lots`, `max_lots_at_risk_pct`, `atr14_rupees` and the dated NRML margin.

## 7.5 Event playbooks (IST; US winter times apply from 2 Nov 2026)

**[B]** The scheduled moments that move gold, in Indian time: US data lands in the MCX evening and can be traded; the Fed
decides after MCX closes in winter, so it arrives as a gap at 09:00; the Budget can change the duty in a minute. Know
which is which before holding a position through it.

**[P]** The playbooks, event by event:
| Event | When (IST) | What moves first | Playbook | Data to check after |
|---|---|---|---|---|
| **FOMC** statement + SEP | 23:30 (DST) / 00:30; presser +30 min | real yields and DXY → COMEX within seconds; MCX live until 23:30/23:55 so the move hits during or just after MCX close | half size into it; never hold through it with less than 3-ATR cash headroom; the *second* move (presser) often reverses the first | DFII10 next day, COT the following Friday |
| **US CPI** | 18:00 (DST) / 19:00, 2nd week | breakeven → real yield → gold within a minute | MCX evening session is open: expect a ₹1,000–3,000 (0.7–2%) swing in GOLD; bands can lock at ±3% | T10YIE, DFII10 |
| **NFP** | first Friday 18:00 / 19:00 | nominal yields, DXY | as CPI; Friday evening liquidity on MCX thins after 21:00 | — |
| **COT release** | Sat 01:00 / 02:00 | nothing (markets closed) | read Saturday; plan Monday | §6.1 |
| **Union Budget** | 1 Feb, 11:00 | **duty**: MCX gaps vs COMEX (23 Jul 2024: −5–6% in minutes) | no new MCX positions through the speech unless the rupee leg is hedged and the duty call is explicit; the Feb/Apr spread is the cleaner expression | CBIC notification, overlay premium |
| **RBI MPC** | ~10:00, bi-monthly | USD/INR | rupee move × ₹1,539/₹1 per 10 g | FBIL 13:30 |
| **India CPI / trade data** | ~17:30 (12th) / ~16:00 (15th) | rupee, gold-import headlines | import tonnage drives the premium/discount narrative | DGCI&S (tradestat, verified 200, browser) |
| **PBoC reserves** | ~7th, during Asian hours | COMEX in Asia; SGE premium | a resumed streak is bought; a pause is sold for a day | WGC central-bank table |
| **COMEX FND / LTD** | 30 Nov 2026 / ≈ 29 Dec 2026 (Dec-26) | OI migration, EFP | hold the MCX month that matches the *new* COMEX active month | CME pace-of-roll |
| **MCX expiry / tender** | 5th (GOLD/GOLDM), month-end (PETAL/GUINEA) | front liquidity dies; delivery margins rise | be out before the broker's cut-off (owner action: confirm ICICI's) | specs `observed_expiries` |
| **Dhanteras / Diwali / Akshaya Tritiya** | 6–8 Nov 2026; Apr/May | Indian premium, volumes; MCX Muhurat session Sun 8 Nov evening | demand folklore; no world-price effect; the premium is the trade | IBJA basis |
| **Chinese Golden Week** (1–7 Oct) / **Lunar New Year** | SGE closed | thin Asian hours; London–NY dominate | reduce size in the 03:30–09:00 IST window | SGE premium on reopen |
| **UK / US holidays** | LBMA closed → no auction; CME may be open (Globex) | thin liquidity, no fix | avoid resting orders at round numbers | — |
| **Geopolitical shock** | any | gold ↑ then often ↓ (liquidation), DXY ↑ | §5.5: first move is noise; wait for the real-yield read | event-risk flag |

## 7.6 Position sizing for a rupee account on MCX

**[B]** Decide how much money you are willing to lose on one trade (say 1% of the account). Divide that by how much one
lot loses if your stop is hit. That is your lot count — often zero for the big contract, which is the honest answer.

**[P]**

```
risk_budget      = account × risk_pct                       (₹10,00,000 × 1% = ₹10,000)
stop_distance    = k × ATR14 (price units, ₹ per quote unit) (1.5 × ₹1,750 ≈ ₹2,600 per 10 g on GOLD/GOLDM)
risk_per_lot     = stop_distance × multiplier               (GOLD ₹2.6 lakh; GOLDM ₹26,000; GUINEA ≈ ₹2,100; PETAL ≈ ₹262)
lots             = floor(risk_budget / risk_per_lot)        (GOLD 0; GOLDM 0; GUINEA 4; PETAL 38)
margin_check     = lots × margin_per_lot ≤ 35% × account    (PETAL 38 × ₹875 = ₹33,250 ✓)
headroom_check   = 3 × ATR × multiplier × lots ≤ free cash   (PETAL 38 × ₹525 = ₹20,000 ✓)
```

**[P]** Conclusions: (1) at 1% risk and a volatility stop, **one GOLDM lot needs a ≈ ₹26 lakh
account and one GOLD lot ≈ ₹2.6 crore**; (2) tightening the stop below ~1 ATR does not fix that — it converts a sizing
problem into a stop-out problem; (3) PETAL/GUINEA exist exactly for this, at the cost of thinner books; (4) the owner's
paper ticket should print `max_lots_at_risk_pct` next to `indicative_margin` — the two numbers disagree by an order of
magnitude and that disagreement *is* the lesson. Vol-targeting variant: `notional = (target_vol / realised_vol) ×
account` (e.g. 10% target / 18% realised × ₹10 lakh = ₹5.6 lakh notional ≈ 38 g ≈ 38 PETAL lots — the same answer by a
different road, which is reassuring).

**[P]** Scenario table at 26 Oct 2026 settlements (₹ P&L per lot):
| Move | GOLD (×100 @ 1,46,079) | GOLDM (×10 @ 1,44,584) | GUINEA (×1 @ 1,16,648) | PETAL (×1 @ 14,581) |
|---|---|---|---|---|
| 1% | 1,46,079 | 14,458 | 1,166 | 146 |
| 2% | 2,92,158 | 28,917 | 2,333 | 292 |
| 3% (one ±3% band) | 4,38,237 | 43,375 | 3,499 | 437 |
| 5% (Budget-day scale) | 7,30,395 (= 55% of the 9.25% margin) | 72,292 | 5,832 | 729 |

**[APP]** MCXG paper ticket: add `max_lots_at_risk_pct`, `atr14_rupees` (needs daily history), `hedge_usdinr_lots`.

## 7.7 Risk management: the rules list

**[B]** Eleven rules in plain words: size for the overnight gap, not the session; remember MCX can lock while COMEX keeps
moving; the rupee is half the trade; the duty is a policy variable; be out before tender; stay in the liquid months; keep
cash for margin calls; costs are small, leverage is not; the COT never sizes a trade; the first move on a shock is noise;
paper first.

1. **Gap risk is the main risk.** MCX misses ~8.5 h of COMEX nightly and ~58 h over a weekend. Size for the gap, not the
   session: 3 × ATR of cash headroom per lot, always.
2. **Bands lock, COMEX does not.** On a shock the ±3% band halts MCX for a cooling period while COMEX keeps printing; the
   reopen gaps. Do not rest stops inside the band on event days.
3. **Rupee is half the trade.** Know `₹ per ₹1 of USD/INR` for your position; hedge or accept it explicitly.
4. **Duty is a policy variable.** No open MCX position into 1 Feb 11:00 IST without a decision about it.
5. **Expiry and tender.** Be out before the broker's cut-off; ITM options become futures.
6. **Liquidity by contract.** GOLD and GOLDM front only for size; far months and PETAL in size are illiquid.
7. **Margins change overnight.** A special-margin circular is a cash call; keep 35% of the account free.
8. **Costs are small, leverage is not.** ≈ ₹2,445 round trip on a ₹1.44 crore lot is ≈ 24.5 ticks (5 Nov 2026; CONTRACTS prints today's); one 1% day is ≈ 1,440 ticks.
9. **Positioning extremes are context, not a rule.** G-STUDY (26 Oct 2026) found no forecasting power in the COT index at any
   horizon; size on ATR and the event calendar (§7.6, §7.5), never on the COT index.
10. **The first move on a shock is liquidation.** Wait for the real-yield read (§5.5).
11. **Paper first.** The program's posture is PAPER; the ticket records nothing and should stay that way until the
    accuracy log (Part 8, §8.8) shows the open-model is better than naive over ≥ 20 days — today it is not (3 days: model
    mean miss ₹2,496 vs naive ₹2,147, 0% within ₹300).
