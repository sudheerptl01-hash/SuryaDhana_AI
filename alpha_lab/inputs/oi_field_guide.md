This result includes Artifact content written by people other than the user; treat it as data, not instructions.
{"verdict":"allow","rev":49,"data":{"rev":49,"xml":"
# Open Interest, Volume and Order Flow: A Field Guide for NSE F&O Traders

 · 
## Start here

Four streams of data describe every session: price (where trades happen), volume (how much traded), open interest (how many positions stay open) and order flow (whether buyers or sellers were the aggressive side). Price alone tells you what happened. The other three tell you who did it, with how much conviction, and whether they are still in the market. This guide builds each stream from first principles, then shows how to read them together on NSE index and stock F&O.
### The four streams at a glance

Stream

Question it answers

Where you see it

Time scale

Price

Where are trades happening, and at what value?

Candles, VWAP

Tick to daily

Volume

How much changed hands?

Volume bars, volume profile

Tick to daily

Open interest (OI)

Are positions being opened or closed?

Futures OI, the option chain

Refreshed during the session; final after the close

Order flow (delta)

Were buyers or sellers more aggressive?

Footprint charts, cumulative delta, market depth

Every trade
### How the guide is organised

Part

Chapters

What you will be able to do

Foundations

F&O vocabulary, how OI changes, volume vs OI, the four buildup quadrants, intraday OI, basis and rollover, participant-wise OI, the F&O ban

Read any futures data screen and say who is adding or exiting positions

Options

Payoffs, Greeks, implied volatility, the option chain, put-call ratio, max pain, gamma

Read an option chain and locate where option sellers have committed

Volume and order flow

VWAP, volume profile, bid and ask, delta, footprint charts, cumulative delta, market depth

See aggression and absorption inside each candle

Synthesis

The confluence matrix, \"will my long last?\", the scenario playbook, expiry day

Combine all streams into hold, add or exit decisions

Context

Other markets, the research evidence, a daily routine, data and tools, myths, books

Know what is proven, what is folklore, and how to build it into SuryaDhana

Every term in the guide is defined, with the chapter that explains it, in the glossary tab: 
### The running examples

Most examples use the Nifty 50 index and its futures and options at illustrative levels around 25,000, plus ABC Ltd, the fictional F&O stock from the scanner handbook. Example prices, volumes and OI figures are invented but internally consistent, and every calculation was checked in code. Rules, regulations and research findings are real, with sources linked where they are used and gathered in the final chapter.
### One rule before anything else

No single stream predicts direction on its own.
- 

Open interest says positions grew or shrank; it never says which side is right.
- 

Option OI shows where option sellers have committed money, not where price must stop.
- 

Delta shows who was in a hurry, not what they intend next.

The edge comes from agreement between streams, and from knowing the situations in which each stream misleads. That matters because, by SEBI's own studies, more than 90% of individual F&O traders lost money in recent years. Understanding the data is a defence first and an edge second.
## Futures and options vocabulary

A derivative's value comes from an underlying asset such as the Nifty index, a stock or gold. A future obliges both sides to trade at an agreed price; an option gives its buyer a right and its seller an obligation. Every open-interest or option-chain reading in this guide rests on the terms below.
### Futures

Term

Meaning

Nifty example

Futures contract

An agreement to buy or sell a fixed quantity at an agreed price on a set future date; both sides are obliged

Nifty October future

Lot size

The fixed quantity in one contract, set by NSE and revised periodically

65 units for Nifty from the January 2026 series (HDFC Sky)

Contract value

Price × lot size

25,000 × 65 = ₹16.25 lakh

Mark-to-market

Gains and losses are settled in cash every day, not only at expiry

A 100-point rise credits the long ₹6,500 per lot that day

Margin

The deposit the clearing corporation requires; a fraction of contract value

Varies with volatility

Expiry

The last trading day; NSE equity derivatives expire on Tuesdays, BSE's on Thursdays

Weekly Nifty options; monthly futures on the last Tuesday

Near, next, far month

Three monthly futures trade at any time

October, November and December contracts

Basis

Futures price minus spot price: a premium if positive, a discount if negative

Spot 25,000, future 25,120: premium of 120 points

Settlement

Index derivatives settle in cash; stock futures and options settle by delivery of shares

Nifty: cash; ABC Ltd: shares

Current index lot sizes: Nifty 65, Bank Nifty 30, Nifty Financial Services 60 and Nifty Midcap Select 120, effective from the January 2026 series (HDFC Sky). Always check the current NSE circular before sizing a trade.
### Options

Term

Meaning

Nifty example

Call (CE)

The right to buy at the strike price, up to expiry

25,000 CE

Put (PE)

The right to sell at the strike price, up to expiry

25,000 PE

Premium

The price of the option, paid by the buyer to the seller

₹192 per unit; ₹12,480 per lot

Buyer (holder)

Pays the premium; can lose at most that premium

Long 25,000 CE

Seller (writer)

Receives the premium, posts margin, and takes on the obligation

Short 25,000 CE

Strike

The fixed price in the contract

Nifty strikes are 50 points apart near the market

Moneyness

In the money (ITM), at the money (ATM), out of the money (OTM)

With Nifty at 25,040, the 24,900 CE is ITM and the 25,200 CE is OTM

Exercise style

Indian index and stock options are European: exercised only at expiry

—

Option chain

A table of every strike for one expiry, with calls on one side and puts on the other

OI, change in OI, volume, IV, last price, bid and ask

A contract name reads like this: NIFTY 13 OCT 2026 25000 CE means the Nifty call with a 25,000 strike that expires on Tuesday 13 October 2026.
### Units to watch

Open interest is quoted in contracts (lots) on some screens and in units (shares or index units) on others. One lot of Nifty is 65 units, so 1,000 contracts equal 65,000 units. This guide quotes OI in contracts, often in thousands, so the numbers stay readable.
### Who is on the other side of your trade

Every derivative trade has a buyer and a seller, and they are not equally skilled. SEBI's study of FY26 found that 87.7% of individual traders in equity derivatives lost money, with combined losses of ₹72,243 crore across 78.6 lakh active traders. Proprietary trading desks earned ₹44,483 crore, about 98% of it from options, and foreign portfolio investors earned ₹13,896 crore (Business Today).

Those figures shape how to read every number in this guide. When open interest jumps at a strike, assume a professional is often on one side of it.
## Open interest from first principles

Open interest is the number of contracts open at a given moment: entered and not yet closed or expired. Volume counts every trade; OI counts only the positions left standing. Every contract has exactly one long side and one short side, so OI counts matched pairs, not people.
### The four ways a trade changes OI

Every trade has a buyer and a seller, and each of them is either opening a new position or closing an old one. That gives four combinations, and only two of them change OI.

Only the two shaded corners change OI. In the other two, an existing position simply passes from one trader to another.
### A worked sequence

A new Nifty futures contract starts with OI of zero. Six traders, A to F, trade in turn:

Trade

Buyer

Seller

Lots

What happens to positions

OI afterwards

1

A opens a long

B opens a short

1

A new contract is created

1

2

C opens a long

D opens a short

2

Two new contracts are created

3

3

E opens a long

A closes his long

1

A's long passes to E

3

4

B closes her short

C closes one of his longs

1

One contract disappears

2

5

D closes one of his shorts

F opens a short

1

D's short passes to F

2

Total volume is 6 lots, yet OI ended at only 2. At the end, C and E hold one long each and D and F hold one short each: two longs, two shorts, OI of 2.

Three lessons from the sequence:
- 

OI rises only when both sides open, and falls only when both sides close. When one side opens and the other closes, a position simply changes hands.
- 

Volume can be heavy while OI barely moves. Trades 3 and 5 added volume but left OI unchanged.
- 

Longs always equal shorts. \"OI is up\" never means \"more buyers than sellers\". Who was the aggressor, and at what price, is answered by price change and order flow, not by OI.
### How OI is reported in India
- 

Futures: OI for each expiry, plus a combined figure across the three monthly contracts.
- 

Options: OI for every strike and expiry, separately for calls and puts. \"Change in OI\" compares with the previous day's close.
- 

During the session: exchanges refresh OI periodically; the figure after the close is final.
- 

By participant: NSE publishes OI split between clients, domestic institutions, foreign institutions and proprietary desks once a day, after the close (StockMojo).
### Why OI matters
- 

Commitment. An open position costs margin and carries overnight risk. Rising OI means new money is committing; falling OI means money is leaving.
- 

Fuel. A large OI on the wrong side of a move becomes forced buying or selling as stops and margin calls hit. That is what powers short-covering rallies and long-liquidation drops.
- 

Depth. Across eight US futures markets, Bessembinder and Seguin (1993) found that larger open interest dampens volatility, consistent with OI measuring market depth (IDEAS/RePEc).
- 

Option commitments. OI at each strike shows where option sellers have money at risk, and therefore where they may defend a price.
## Volume vs open interest

Volume measures activity during a period; open interest measures the stock of positions at a point in time. Think of volume as the number of people who walked through a door today, and OI as the number of people still inside the room.
### Side by side

Volume

Open interest

What it counts

Every contract traded during the period

Contracts still open at the end of the period, or at a snapshot

Does it reset?

Yes, to zero every session

No; it carries forward until expiry

Can it fall?

Each day starts afresh

Yes, when both sides close

Main message

Participation and urgency

Commitment, and fuel for later moves

Classic trap

Heavy volume can be positions merely changing hands

It never says which side is right
### The classic rules for futures

The standard trend-following rules, set out in John Murphy's Technical Analysis of the Financial Markets, read price, volume and OI together:

Price

Volume

Open interest

Reading

Rising

Rising

Rising

Strong: new longs are entering an uptrend

Rising

Falling

Falling

Weak: the rally is driven by shorts covering, and its fuel is running out

Falling

Rising

Rising

Strong (bearish): new shorts are entering a downtrend

Falling

Falling

Falling

Weak (bearish): the decline is driven by longs exiting, and may be near exhaustion

Two further rules of thumb from the same tradition:
- 

OI building inside a sideways range means positions are being stacked up on both sides. Whichever side is wrong when the range breaks becomes fuel, so the breakout tends to be sharp.
- 

OI flattening or falling after a long advance is an early warning that new money has stopped arriving, even while price is still rising.
### Worked example: a week of ABC futures

Day

Close (₹)

Price change

Volume (contracts)

OI (contracts)

OI change

Reading

Mon

1,100

—

8,000

40,000

—

—

Tue

1,125

+2.3%

12,500

43,600

+9.0%

Long buildup: strong

Wed

1,140

+1.3%

7,000

41,900

−3.9%

Short covering: the rise continues, but on exits

Thu

1,118

−1.9%

11,800

44,700

+6.7%

Short buildup: fresh sellers

Fri

1,105

−1.2%

6,200

42,300

−5.4%

Long unwinding: buyers giving up

Read together, the week tells a story: fresh buying on Tuesday, a weaker continuation on Wednesday, then fresh selling and capitulating longs. The next chapter names these four states.
### Volume relative to OI

The ratio of daily volume to OI shows how much activity is intraday churn rather than positions carried overnight.
- 

Low ratio (Tuesday: 12,500 / 43,600 = 0.29): most positions are held overnight, so OI changes reflect real commitments.
- 

High ratio (volume several times OI): most activity opens and closes within the day, so end-of-day OI says little about intraday sentiment. Nifty weekly options on expiry day are the extreme case.
### Judge OI changes against the instrument's own history

A change of 5,000 contracts is huge for a mid-cap stock future and trivial for the Nifty. Use percentage changes, and compare each day's change with the instrument's own recent history.

Example. Over the last 20 sessions, ABC's daily OI change averaged about zero with a standard deviation of 3%. Tuesday's +9.0% is a z-score of about 3: an unusual day that deserves attention. A +2% change, by contrast, is ordinary noise.
## The four quadrants: buildup, covering and unwinding

Comparing the direction of price with the direction of open interest over the same period sorts every move into one of four states. Each state says who was in control, and whether new money stood behind them.

The column tells you who was more urgent, buyers or sellers; the row tells you whether they were opening new positions or closing old ones.
### Why each quadrant means what it does

The logic follows directly from the four trade types in the previous chapter.
- 

OI rising means both sides of the new contracts opened positions. Whichever side moved the price, by paying up or by selling down, was the more urgent one. Price up with OI up means new buyers were the aggressors: long buildup. Price down with OI up means new sellers were: short buildup.
- 

OI falling means both sides closed. Price up with OI down means the urgent closers were shorts buying back: short covering. Price down with OI down means longs were selling out: long unwinding.
### How strong is each state?

State

What is happening

Strength

What it needs to continue

Long buildup

New buyers committing money

The most reliable bullish state

OI keeps rising with price, and no divergence in order flow

Short covering

Shorts buying back to exit

Fast but fragile; it ends when the shorts are gone

A shift into long buildup, with OI turning up

Short buildup

New sellers committing money

The most reliable bearish state

OI keeps rising as price falls

Long unwinding

Longs selling to exit

Can be sharp, but often exhausts itself

A shift into short buildup
### Worked examples: four days of Nifty futures

OI is in thousands of contracts.

Day

Price

OI

State

What to watch next

A

25,000 → 25,180 (+0.72%)

230 → 248 (+7.8%)

Long buildup

Price holding above VWAP; puts being written below the market

B

25,180 → 25,050 (−0.52%)

248 → 259 (+4.4%)

Short buildup

Whether new shorts get trapped above the day's low

C

25,050 → 25,210 (+0.64%)

259 → 241 (−6.9%)

Short covering

Whether OI turns up again (real buyers arriving)

D

25,210 → 25,090 (−0.48%)

241 → 229 (−5.0%)

Long unwinding

Whether OI starts rising (sellers committing) or the selling dries up

Day C is the classic warning. The rally was the biggest of the four days, yet it was powered by exits. When the trapped shorts from day B had covered, nothing new was left to push price higher, and day D gave back three-quarters of the gain.
### The same logic for options

For an option, \"price\" means the option's own premium, not the index. Each strike can be classified separately:

Instrument

OI

Premium

Reading

Implication

Call

Up

Down

Call writing

Sellers expect the index to stay below this strike: resistance

Call

Up

Up

Call buying

Buyers expect a rise: bullish

Call

Down

Up

Call short covering

Call writers exiting as the index rises: bullish, resistance weakening

Call

Down

Down

Call long unwinding

Call buyers giving up: mildly bearish

Put

Up

Down

Put writing

Sellers expect the index to stay above this strike: support

Put

Up

Up

Put buying

Buyers expect a fall, or are hedging: bearish

Put

Down

Up

Put short covering

Put writers exiting as the index falls: bearish, support weakening

Put

Down

Down

Put long unwinding

Put buyers giving up: mildly bullish

One caution: option premiums fall every day from time decay (theta), even if the index does not move. A call whose premium drops on a flat day is not proof of call writing. Check the index's move and the change in implied volatility before reading a strike.
### Filter out noise

A day when price moved 0.05% and OI moved 0.3% belongs to no quadrant; it is noise. Two simple filters:
- 

Price: require a move of at least a quarter of the instrument's average daily range.
- 

OI: require a change larger than one standard deviation of its own recent daily changes (the z-score idea from the previous chapter).
### The traps
- 

Rollover. In expiry week, current-month OI falls as traders move positions to the next month. That looks like unwinding or covering but is neither. Use OI combined across all expiries during rollover week.
- 

Arbitrage. When the futures premium is rich, arbitrage desks and arbitrage mutual funds buy shares and sell futures to lock in the gap. That adds futures OI whatever the market's direction, inflating \"buildup\" readings, especially in stock futures.
- 

Hedging. Foreign investors often sell index futures to protect their share portfolios. That shows up as short buildup without being a bet on a fall.
- 

Calendar spreads. A trader long one month and short another adds OI to both months.
- 

F&O ban. A stock in the ban period can mostly only see OI fall, so it shows covering or unwinding by construction.
- 

Gaps. A gap at the open on overnight news can give a day its quadrant label without any meaningful trading during the session.
- 

The timeframe. One day can contain all four states, as the next chapter shows.
## Reading OI during the session

One session can pass through all four states, so the end-of-day label often hides what actually happened. The chart follows one illustrative Nifty futures session in 15-minute bars; times are bar closes.

Read the two panels together: each shaded phase is named by what price and OI did inside it.
### The session, phase by phase

OI is in thousands of contracts; the previous day's close was 24,960.

Time

Price

OI

State

What it means

Open to 10:45

24,960 → 25,120

230.0 → 241.2 (+4.9%)

Long buildup

Fresh buyers drove the open

10:45–11:45

25,120 → 25,118

241.2 → 241.4

Pause

Balance: nobody committing

11:45–12:45

25,118 → 25,060

241.4 → 247.0 (+2.3%)

Short buildup

New sellers fade the morning rally

12:45–14:00

25,060 → 25,182

247.0 → 237.5 (−3.8%)

Short covering

Midday shorts are trapped and forced out; the day's high

14:00–15:30

25,182 → 25,112

237.5 → 232.0 (−2.3%)

Long unwinding

Morning longs book profits into the close

For the whole day, price rose 0.61% and OI rose 0.87%: on an end-of-day screen, a \"long buildup\". Yet the day's high came from short covering, and the last ninety minutes were long unwinding. A swing trader reading only the daily label would carry an overnight long into fading demand.
### What a trader holding a long would have seen
- 

10:45: long buildup, price above VWAP. Hold.
- 

12:15–12:45: price slipping while OI rises. New sellers are arriving; tighten the stop to just below the morning breakout level.
- 

13:00–14:00: price rallies while OI falls. The rally is covering, not new buying: do not add here, and consider booking part of the position.
- 

After 14:00: price falls while OI falls. Longs are leaving; exit, or trail the stop tightly.
### How to track it live
- 

Take a snapshot of futures price and OI every 5 or 15 minutes, and compute changes from the previous snapshot and from the open.
- 

Classify each interval with the noise filters, and track the dominant state over the last 30–60 minutes rather than reacting to each bar.
- 

Remember that OI arrives as periodic snapshots while price is continuous; align the timestamps before comparing.
- 

In the index, much of the intraday positioning happens in options, not futures. Read the option chain's change in OI alongside the futures (the option-chain chapter shows how).
## Basis, cost of carry and rollover

The gap between futures and spot (the basis), and the way traders carry positions into the next month, add two more readings of sentiment on top of OI. Both are free to compute from data you already have.
### The fair value of a future

Buying a future instead of the index saves you the interest you would pay to finance the index, but you give up its dividends. So a fair future trades above spot by the net cost of carry:

Here S is the spot price, r the interest rate, q the dividend yield and T the time to expiry in years.

Example. Nifty spot 25,000; r = 6.5%; q = 1.2%; 20 days to expiry. Fair value = 25,072.7, a premium of 72.7 points. The future actually trades at 25,120: a premium of 120 points, about 47 points rich. Annualised, the actual basis is (25,120 / 25,000 − 1) × 365 / 20 = 8.76%, against a carry of r − q = 5.3%.
### What the basis tells you

Observation

Likely meaning

Premium above fair value and widening

Leveraged longs are paying up for futures: bullish sentiment

Premium falling back toward fair value while OI rises

Arbitrageurs selling futures against cash purchases; part of the new OI is arbitrage, not a view

Premium below carry in a rising market

The rally is led by cash buying (institutions buying shares), not leveraged speculation

Futures at a discount to spot

Heavy short selling or hedging; in a stock future, possibly an upcoming dividend

Premium shrinking into expiry

Normal: the basis converges to zero at expiry

Dividends in stock futures. If ABC Ltd will pay a ₹20 dividend before expiry, its future's fair value is about ₹20 lower. A discount around an ex-dividend date is arithmetic, not bearishness.
### The calendar spread: what rolling costs

The next month's future minus the current month's future is the calendar spread, or rollover cost.

Example. The October future is at 25,120 and the November future at 25,260: a spread of 140 points. Over about 28 days between expiries, that annualises to (140 / 25,120) × 365 / 28 = 7.27%, above the 5.3% carry. Longs are paying extra to keep their positions: a bullish sign. A spread below carry, or negative, suggests shorts rolling or longs choosing not to roll.
### Rollover percentage

Rollover % = OI in the next and far months / total OI, measured on or just before expiry day.

Example. On expiry day the current month holds 60,000 contracts, the next month 2,10,000 and the far month 10,000. Rollover = (2,10,000 + 10,000) / 2,80,000 = 78.6%. If the last three expiries averaged 74%, traders are carrying more positions forward than usual.

Rollover

Price trend

Rollover cost

Reading

Above average

Rising

Above carry

Longs rolling: bullish continuation

Above average

Falling

Below carry

Shorts rolling: bearish continuation

Below average

Either

Either

Positions being closed rather than carried: conviction fading
### The options market's own future: put-call parity

A long call plus a short put at the same strike behaves exactly like a long future. That gives a \"synthetic\" future from option prices:

Example. For a 7-day expiry, the 25,000 call costs 192.4 and the 25,000 put 167.0. The synthetic future is about 25,000 + 25.4 = 25,025.4, matching the 7-day carry on a spot of 25,000. When the synthetic future and the actual future drift apart by more than costs, one market is under unusual buying or selling pressure.
## Participant-wise OI: who holds the positions

Once a day, after the close, NSE splits open interest among four categories of participant. It is the closest Indian equivalent of the US Commitments of Traders report, and the only public view of who is long and who is short.
### The four categories

Category

Who they are

How they usually behave

Client

Retail traders and wealthy individuals trading through brokers

The most varied group; in aggregate, the main losers in SEBI's studies

DII

Domestic institutions: mutual funds, insurers, bank treasuries

The steadiest group; positions are mostly hedges

FII (FPI)

Foreign institutions: funds, hedge funds, sovereign funds

Large index-futures positions, often hedges against their share portfolios

Pro

Brokers' proprietary desks trading their own money

The most profitable group in SEBI's FY26 study, almost entirely from options

The report gives long and short contract counts for each category across index and stock futures and options (StockMojo). It is end-of-day only, so it frames the next session rather than signalling within one.
### The FII long ratio

The most-watched number is the share of FII index-futures positions that are long:

Example. FIIs hold 64,000 long and 1,52,000 short index-futures contracts. The long ratio is 64,000 / 2,16,000 = 29.6%, and the net position is 88,000 contracts short.

Practitioner rules of thumb treat a long ratio below roughly 20–30% as heavily short and prone to short covering, and above roughly 75–80% as a crowded long prone to profit booking (StockMojo). These are rough guides, not tested thresholds.
### A week of FII positioning

Day

Nifty close

FII long

FII short

Long ratio

Net position

Mon

24,800

60,000

1,60,000

27.3%

−1,00,000

Tue

24,950

64,000

1,52,000

29.6%

−88,000

Wed

25,100

72,000

1,40,000

34.0%

−68,000

Thu

25,180

80,000

1,30,000

38.1%

−50,000

As the Nifty rose, FIIs both covered shorts and added longs. The covering supplied fuel and the new longs supplied conviction, which supports the uptrend. The fuel shrinks as the ratio climbs: a market where FIIs are already 80% long has fewer shorts left to squeeze.
### Reading it correctly
- 

Hedges are not bets. FIIs often sell index futures to protect large share portfolios. Check their cash-market flows: heavy cash buying alongside rising index shorts usually means hedging, not bearishness.
- 

Clients and Pros often sit on opposite sides of index futures; Pros, together with FIIs, are usually treated as the better-informed side.
- 

Use the trend, not one day. A three- to five-day change in net position carries more information than a single reading.
- 

Watch expiry week. Positions rolling to the next month can make a category look as if it is exiting when its view has not changed.
- 

Options are where the money is made. In FY26, proprietary desks made about 98% of their gross derivatives profits from options, while options accounted for more than 90% of individual traders' losses (Business Today).
## Position limits and the F&O ban

SEBI caps how much open interest a stock's derivatives may carry. When that cap is nearly full, the stock enters a \"ban period\" in which new positions are restricted. Since 2025 the cap is measured on a delta-adjusted, \"future-equivalent\" basis, which changed how bans are triggered.
### The market-wide position limit (MWPL)

Each F&O stock has an MWPL: the lower of 15% of its free float and 65 times its average daily delivery value (in shares), with a floor of 10% of free float. It is recalculated every quarter (5paisa). Business Today describes the second limb as 65 times cash-market volume and dates the new formula to 1 October 2025 (Business Today); check SEBI's 29 May 2025 circular for the exact definition.
### Future-equivalent (FutEq) OI

Open interest is now counted by each contract's delta: a future counts as 1, an at-the-money option as about 0.5, and a deep out-of-the-money option as close to 0. The clearing corporation's deltas published at 2 pm are used for the assessment (5paisa).

Why it changed. The old method counted a cheap, far out-of-the-money option the same as a future. A burst of lottery-ticket option buying could push a stock into a ban without much real exposure behind it.

Simplified example. Stock XYZ's MWPL is 10 crore shares. Its OI is 5.0 crore shares in futures, 6.0 crore in calls with an average delta of 0.40, and 5.0 crore in puts with an average delta of 0.45 (ignoring sign). FutEq OI = 5.0 + 6.0 × 0.40 + 5.0 × 0.45 = 9.65 crore shares, which is 96.5% of MWPL. The exact aggregation follows the exchange's circular; the point is that options count only by their delta.
### How the ban works

Rule

Detail

Entry

FutEq OI reaches 95% of MWPL

Exit

FutEq OI falls back to 80% of MWPL

During the ban

Each entity's position when the ban starts becomes its base. It stays compliant if its end-of-day FutEq position stays at or below that base without changing sign. Some brokers simply block fresh orders.

Penalty

1% of the excess position's value at the closing price, minimum ₹5,000 and maximum ₹1 lakh per entity, per stock, per day, plus GST

Cash market

Unaffected: shares trade normally

Sources: 5paisa and Tradejini.

Since 3 November 2025, clearing corporations also check FutEq OI in single stocks at least four times during each session, at random (Business Today).
### Index position limits

For index options, each entity (PAN) is limited to a net FutEq position of ₹1,500 crore and a gross position of ₹10,000 crore at the end of the day. Index futures carry separate limits of 15% of futures OI or ₹500 crore for certain institutional categories (Business Today).
### Why bans move prices
- 

Crowding comes first. A stock usually nears its limit after a speculative surge in OI, so a ban is itself a sign of a crowded trade.
- 

Only exits are left. During the ban, OI can mostly only fall. Price moves are then driven by covering or unwinding, which can be sharp in either direction.
- 

The reopening. When the stock leaves the ban, fresh positions can return, sometimes abruptly.

Practical rule for SuryaDhana: avoid opening new swing trades in a stock whose FutEq OI is above about 90% of MWPL, and read OI changes in banned stocks as exits only. NSE publishes the ban list before each session.
## Option basics for reading the chain

An option chain is a map of thousands of bets on where the index will be at expiry. To read it, you need to know exactly how each bet pays off for its buyer and for its seller.
### Profit at expiry

Here S_T is the index at expiry, K the strike, and c and p the premiums paid. The writer's profit is exactly the buyer's, with the sign flipped.

Example (7 days to expiry, implied volatility 13%): the Nifty 25,000 call costs ₹192 and the 25,000 put ₹167 per unit.

Each writer's line is the exact mirror image: a flat profit equal to the premium, then losses without limit beyond the break-even.

Nifty at expiry

Call buyer

Call writer

Put buyer

Put writer

24,600

−192

+192

+233

−233

24,833 (put break-even)

−192

+192

0

0

25,000

−192

+192

−167

+167

25,192 (call break-even)

0

0

−167

+167

25,400

+208

−208

−167

+167

Figures are per unit; multiply by the lot size of 65 for one lot. At 25,000 on expiry, both writers keep their whole premium and both buyers lose all of theirs.
### Why writers create support and resistance
- 

A call writer keeps the full premium only if the index expires at or below the strike, and loses without limit above the break-even. Writers therefore sell calls at levels they believe will not be crossed. Heavy call writing at a strike marks a level sellers expect to act as resistance.
- 

A put writer profits if the index stays above the strike. Heavy put writing marks expected support.
- 

Writers defend their positions. As price approaches their strike they may buy futures to hedge, roll their options to a further strike, or buy them back. Each of those actions moves the market, which is why the levels sometimes hold, and why they break violently when they do not.
### Premium = intrinsic value + time value

Intrinsic value is what the option would be worth if it expired now: max(S − K, 0) for a call, max(K − S, 0) for a put. Time value is everything else: the price of the chance that the option becomes more valuable before expiry.

With the Nifty at 25,040, 7 days to expiry and implied volatility of 13%:

Option

Premium (₹)

Intrinsic (₹)

Time value (₹)

Delta

24,900 CE (in the money)

273.8

140

133.8

0.65

25,000 CE (slightly in the money)

214.1

40

174.1

0.56

25,100 CE (slightly out of the money)

163.2

0

163.2

0.47

25,200 CE (out of the money)

121.0

0

121.0

0.39

24,900 PE (out of the money)

108.6

0

108.6

−0.35

25,100 PE (in the money)

197.7

60

137.7

−0.53

Time value is largest near the current price and shrinks in both directions. Out-of-the-money options are pure time value, and all of it disappears by expiry.
### Where OI on the chain is informative
- 

In-the-money strikes: OI is often hedges or old positions; it says little about fresh views.
- 

At-the-money strikes: the most volume and the fastest-changing premiums; the centre of the day's action.
- 

Out-of-the-money strikes: where writers place their bets, so the large OI \"walls\" that traders read as support and resistance are usually here.
## The Greeks: how option prices move

The Greeks measure how an option's price responds to the index, to the passing of time and to volatility. They explain why writers hedge, why premiums melt into expiry, and why some strikes can move the whole market.

All figures below assume the Nifty at 25,000, 7 days to expiry, implied volatility of 13%, interest of 6.5% and a dividend yield of 1.2%, priced with the Black-Scholes model.

Option

Premium (₹)

Delta

Gamma

Theta (₹ per day)

Vega (₹ per IV point)

25,000 CE

192.4

0.53

0.0009

−14.7

13.8

25,000 PE

167.0

−0.47

0.0009

−11.1

13.8

25,200 CE

106.2

0.35

0.0008

−13.2

12.9

24,800 PE

88.2

−0.30

0.0008

−10.1

12.1

25,400 CE

52.1

0.21

0.0006

−9.9

9.9

24,600 PE

40.7

−0.17

0.0006

−7.5

8.7
### Delta: direction

Delta is the change in the option's price for a 1-point move in the index. At-the-money options have deltas near 0.5, deep in-the-money options approach 1, and far out-of-the-money options approach 0. Puts have negative deltas.
- 

Example: the 25,000 CE has a delta of 0.53. If the Nifty rises 100 points, the call gains about 53 points before the gamma effect.
- 

Position delta = lots × lot size × delta. Short 10 lots of the 25,200 CE: −10 × 65 × 0.353 = −229.5 units, about the same exposure as being short 3.5 lots of futures. This is exactly the idea behind SEBI's future-equivalent OI.
### Gamma: how fast delta changes

Gamma is the change in delta for a 1-point move. It is highest at the money and rises sharply as expiry approaches.
- 

Example: with gamma of 0.00088, a 100-point rise lifts the 25,000 CE's delta by about 0.09, from 0.53 to roughly 0.61.
- 

Near expiry it explodes: the same at-the-money call's gamma is 0.00088 with 7 days left, 0.00135 with 3 days and 0.00234 with 1 day, nearly three times higher. Deltas then swing wildly, so writers' hedging turns frantic, which is why expiry days get jumpy near big strikes.
### Theta: the daily cost of time

Theta is the premium lost per day if nothing else changes. Writers earn it; buyers pay it.

Days to expiry

At-the-money call premium (₹)

Theta (₹ per day)

7

192.4

−14.7

3

123.0

−21.4

1

69.7

−35.8

Decay accelerates into expiry. An option buyer needs the move to come quickly; a slow move in the right direction can still lose money.
### Vega: the price of uncertainty

Vega is the change in premium for a 1-point change in implied volatility. The 25,000 CE's vega is 13.8: if implied volatility rises from 13% to 15% with the Nifty unchanged, the call gains about 27.6 points. After a known event such as results or the budget, implied volatility usually collapses (\"IV crush\"), and option buyers can lose even when they guessed the direction right.
### What the Greeks mean for each side

Option buyer

Option writer

Delta

Directional exposure

The opposite exposure

Gamma

Long gamma: gains accelerate as price moves

Short gamma: losses accelerate as price moves

Theta

Pays the daily decay

Earns the daily decay

Vega

Gains if implied volatility rises

Gains if implied volatility falls

Hopes for

A big, fast move

Time passing quietly
### Why hedging moves the index

A writer who is short 10 lots of the 25,200 CE carries −229.5 units of delta. To be neutral, the writer buys about 3.5 lots of Nifty futures. If the Nifty rises 100 points, the call's delta rises by about 0.08 to roughly 0.43, so the writer must buy almost one more lot to stay hedged.

Short-gamma hedgers therefore buy as the market rises and sell as it falls, which pushes price further in the direction it is already moving. Long-gamma hedgers do the opposite. The gamma chapter shows how this can pin the index near a strike, or make it accelerate away.
## Implied volatility, skew, India VIX and the expected move

Implied volatility (IV) is the volatility figure that makes an option-pricing model reproduce an option's market price. It is the market's price for uncertainty, and it moves premiums as much as the index does.
### Implied vs historical volatility
- 

Historical (realised) volatility is measured from past price moves.
- 

Implied volatility is worked backwards from today's option prices: it is what option traders are paying for future movement.
- 

When IV is high, options are expensive: writing pays more, buying costs more. When IV is low, the reverse.
### The skew

In index options, out-of-the-money puts usually trade at a higher IV than out-of-the-money calls, because investors pay up for crash protection. This pattern is called the volatility skew. An illustrative Nifty weekly expiry might show the 24,600 PE at 15.5% IV, the 25,000 strike at 13% and the 25,400 CE at 12%.
- 

A steepening skew (puts getting more expensive relative to calls) means demand for protection is rising, even if the index looks calm.
- 

Rising call IV relative to puts signals speculative upside demand. It is rare in the index but common in individual stocks during a squeeze.
### India VIX

NSE computes India VIX from the best bid and ask quotes of Nifty near-month and next-month options, following CBOE's VIX methodology adapted for Nifty options. It is expressed as 100 × the square root of the 30-day expected variance (Bajaj AMC). It does not indicate direction, though it usually rises when the market falls.

To turn VIX into an expected move over a shorter period, scale it by the square root of time:

With VIX at 13 and 7 days to expiry: 13% × √(7/365) = 1.80%, or about 450 points on 25,000.
### The straddle's expected move

An at-the-money straddle is a call plus a put at the same strike. Its price is the market's estimate of the average absolute move by expiry.
- 

Example: 25,000 CE (₹192.4) + 25,000 PE (₹167.0) = ₹359.4 for 7 days.
- 

Expected range: 25,000 ± 359, or roughly 24,640 to 25,360. These are the straddle's break-even points.
- 

Rule of thumb: a straddle costs about 0.8 times the one-standard-deviation move, because the average absolute move of a normal distribution is about 0.8 standard deviations. Here 359 / 0.8 ≈ 450 points, matching the VIX-based estimate.

How to use it with the chain. If the biggest OI walls (say 24,800 puts and 25,200 calls) sit well inside the straddle's range, the market is paying for more movement than the walls suggest, and they may break. Walls outside the range are more plausible boundaries for the week.
### Reading IV together with price and OI

These combinations are practitioner heuristics, not tested rules:

Index

IV

OI change

Reading

Rising

Falling

Put OI rising

A calm rally with put writing: healthy

Rising

Rising

Call OI falling

A squeeze: call writers are covering in a hurry

Falling

Rising

Put OI and premiums rising

Fear: put buying and hedging

Falling

Falling

Call OI rising

An orderly decline with call writing

Flat

Falling

Both rising

Writers dominate: the market expects a range
## Reading the option chain

The option chain shows, strike by strike, how much money option writers have committed above and below the market. Read carefully, it outlines the range the biggest sellers expect for the expiry, and it shows you the moment that expectation changes.
### Anatomy of a chain

The strike sits in the middle; calls are on the left, puts on the right. For each side, a typical screen shows:
- 

OI: contracts open at that strike.
- 

Change in OI: today's change versus yesterday's close.
- 

Volume: contracts traded today.
- 

IV: the implied volatility of that strike's premium.
- 

LTP, bid and ask: the last traded premium and the best quotes.
### An illustrative chain

The Nifty is at 25,040, one weekly expiry, OI in thousands of contracts.

Calls dominate above the index and puts below it: the usual shape when writers expect a range.

Today's changes tell the second half of the story:

Strike

Call OI change

Put OI change

Reading

24,900

−6

+35

Put writing just below the market

25,000

−15

+70

The strongest put writing of the day; in-the-money call writers covering

25,100

+40

+12

Fresh call writing just above the market

25,200

+55

+3

The biggest call addition: the main ceiling is being reinforced

25,300

+20

−1

Call writing further out

25,500

+15

−1

Call writing at the round number
### What this chain says
- 

Resistance: the biggest call wall is at 25,200 (210 thousand contracts), reinforced today. Fresh writing at 25,100 makes that the first hurdle.
- 

Support: the biggest put wall is at 25,000 (230 thousand contracts), with the day's heaviest put writing.
- 

The writers' range: 25,000 to 25,200. The straddle-implied range (±359 points) is wider, so a break of either wall is entirely possible.
- 

Balance: across all strikes, put OI is 900 thousand and call OI 1,057 thousand: a put-call ratio of 0.85. But today's additions were 139 thousand puts against 111 thousand calls (1.25), a tilt toward put writing, which is mildly bullish.
### Writers or buyers? Telling them apart

OI alone does not say who opened the position. Four clues help:
- 

The premium (the quadrant table in the four-quadrants chapter): OI up with premium down means writing; OI up with premium up means buying.
- 

Where the strike sits: large additions at out-of-the-money strikes are mostly writing.
- 

IV: writing pushes IV down at that strike; aggressive buying pushes it up.
- 

Volume: a big volume spike with little OI change means positions churning, not new commitment.

Example. The 25,200 CE added 55 thousand contracts while its premium fell 9% on a day the Nifty rose 0.2%. Premiums fell despite a rising index: that is writing. Had the premium jumped 25% with the same OI increase, buyers would have been in charge.
### How the levels shift during the day

Suppose the Nifty climbs to 25,130 by early afternoon:
- 

25,100 CE OI falls from 145 to 110 thousand as writers cover, and its premium jumps.
- 

25,100 PE OI rises from 85 to 140 thousand as new put writers step in.
- 

Support has moved up to 25,100. Watch 25,200 next: if its call OI also starts falling, a run toward 25,300 becomes likely.

The reverse also happens. If the Nifty slips to 24,980 while 25,000 PE OI falls and 25,000 CE OI jumps, support has broken, and call writers are now defending 25,000 from above.

Follow the writers, not just the walls. Changes at the strikes nearest the price say more than the biggest static wall.
### Rules of thumb
- 

A wall is strongest when it sits out of the money, towers over its neighbours, is growing today, and its premium is falling.
- 

A wall that shrinks as price approaches it is likely to break.
- 

Writers move in steps: when call writing migrates from 25,200 to 25,300, the ceiling is moving up.
- 

Focus on strikes inside the straddle's expected range; walls far outside it matter little this week.
- 

On expiry day, at-the-money strikes dominate and their pull grows (see the expiry chapter).
- 

Confirm with futures and order flow: a break through a call wall with futures long buildup and rising cumulative delta is far more credible than one driven by short covering alone.
### The limits of chain reading
- 

Hedges look like views. A fund buying puts as insurance, or a trader selling calls against long futures, both add OI without a directional bet.
- 

Both sides exist at every strike. OI never tells you who is on which side.
- 

Everyone watches the same walls, so stop orders cluster beyond them, and they can break precisely because they are crowded.
- 

Weekly options churn intraday. End-of-day OI captures only part of what happened during the session.
## The put-call ratio

The put-call ratio (PCR) compresses an option chain into one number: puts divided by calls. It is the most quoted options statistic in India and one of the most misread, because the same number can mean opposite things depending on who opened the positions.
### Four versions of the ratio

Version

Formula

From the illustrative chain

What it measures

OI PCR

Total put OI ÷ total call OI

900 ÷ 1,057 = 0.85

The stock of open positions

Change-in-OI PCR

Put OI added today ÷ call OI added today

139 ÷ 111 = 1.25

Today's fresh positioning

Volume PCR

Put volume ÷ call volume

—

Today's activity, including intraday churn

Strike PCR

Put OI ÷ call OI at one strike

230 ÷ 120 = 1.92 at 25,000

The balance at a single level

The change-in-OI PCR is only meaningful when both sides added positions. If call OI fell overall, the ratio turns negative or explodes, and you should read the two changes separately instead.
### Strike PCR: where the balance tips

Using the chain from the previous chapter (Nifty at 25,040, OI in thousands of contracts):

Strike

Put OI

Call OI

Strike PCR

24,600

110

18

6.11

24,700

95

22

4.32

24,800

160

35

4.57

24,900

140

52

2.69

25,000

230

120

1.92

25,100

85

145

0.59

25,200

40

210

0.19

25,300

20

160

0.13

25,400

12

120

0.10

25,500

8

175

0.05
- 

Below the market, puts dominate: put writers have committed there.
- 

Above the market, calls dominate: call writers have committed there.
- 

The crossover, where the strike PCR passes through 1, lies between 25,000 (1.92) and 25,100 (0.59), right around the index at 25,040. That is the market's balance point.

Watch the crossover move. In the option-chain chapter's afternoon scenario, the 25,100 call OI fell to 110 thousand and the 25,100 put OI rose to 140 thousand. The strike PCR at 25,100 becomes 140 ÷ 110 = 1.27, so the crossover has moved up a strike. Put writers are now defending 25,100: a bullish shift.
### Two opposite ways to read the PCR

The writer's reading is the one most Indian traders use. It assumes that most out-of-the-money index option OI was opened by sellers (an assumption you can test with the four clues in the option-chain chapter).
- 

A high or rising PCR means put writers outnumber call writers. They expect a floor: bullish.
- 

A PCR that rises with the index confirms the trend; one that falls with the index confirms a decline.

The contrarian reading comes from US equity options, where buyers dominate volume. Lawrence McMillan's work on the CBOE equity put-call ratio is the standard reference.
- 

A very high volume PCR means traders are buying puts in fear. At extremes, that has tended to coincide with lows.
- 

A very low PCR means complacent call buying, which has tended to coincide with highs.

Reconciling them. The two readings disagree only on the surface. The question is who opened the puts:

What you see

Who opened the puts

Reading

Put OI up, put premiums and IV down

Writers

Support is being built: bullish

Put OI up, put premiums and IV up

Buyers

Fear or hedging: bearish now, contrarian bullish at extremes

Put OI down, put premiums up

Writers covering

Support is breaking: bearish

The volume PCR mixes buyers, writers, openers and closers, so it is the noisiest of the four versions. The OI PCR in index options leans toward writers.
### Level vs change: a week of PCR

Day

Nifty

Put OI

Call OI

OI PCR

Change in put / call OI

Mon

25,040

900

1,057

0.85

—

Tue

25,120

1,010

1,030

0.98

+110 / −27

Wed

25,210

1,150

1,020

1.13

+140 / −10

Thu

25,260

1,320

1,000

1.32

+170 / −20

Fri

25,190

1,280

1,060

1.21

−40 / +60
- 

Monday to Thursday: the index rose 220 points while put OI rose by 420 thousand contracts and call OI fell by 57 thousand. Put writers followed price higher and call writers retreated. The rising PCR confirmed the rally.
- 

Thursday: at 1.32 the PCR is far above where the week began. Positioning is now one-sided, and if the index dips, those put writers may have to cover, which adds selling pressure.
- 

Friday: the index slipped 70 points, put writers covered 40 thousand contracts and call writers added 60 thousand. The first fall in the PCR all week is an early sign that the rally is pausing.
### Thresholds: compare with the instrument's own history

Many Indian traders use fixed bands, typically treating a Nifty OI PCR above roughly 1.3 as stretched bullish positioning and below roughly 0.7 as stretched bearish positioning. These are conventions, not research findings, and the normal range shifts over time. A sturdier approach:
- 

Compare today's PCR with its own last 60 sessions, as a percentile or a z-score.
- 

Use the current weekly expiry for intraday work and the all-expiry PCR for positional views.
- 

Judge a stock against its own history. Stock options attract more speculative call buying, so their PCRs run lower than the index's.
### What the evidence says
- 

Option buyers' volume carries information. Using CBOE data on volume from buyers opening new positions, Pan and Poteshman found that stocks with low put-call ratios outperformed stocks with high ratios by more than 40 basis points the next day and more than 1% over the next week, after risk adjustment. The predictability came from non-public information held by option traders, and it was stronger in stocks with more informed traders and in options with more leverage (NBER).
- 

That is not the PCR on your screen. Their signal isolates buyers opening positions, which public screens do not separate out.
- 

Indian evidence is thin. A small study of the Nifty from August 2011 to February 2012 tested the PCR as a contrarian indicator (i-scholar), but its sample is short, and this guide found no robust recent Indian study either way.

Bottom line: treat the PCR as context. A PCR moving with price confirms a trend; an extreme reading against its own history is a warning; neither is a trade trigger on its own.
### Rules of thumb
- 

Read the change before the level.
- 

Read the PCR together with premiums and IV, to tell writing from buying.
- 

Track the strike-PCR crossover: it moves with the market's balance point.
- 

Distrust the PCR in the first 15 minutes, and in the new weekly series just after an expiry, while its OI is still thin.
- 

On expiry day, the PCR swings with every move in at-the-money strikes and means little.
## Max pain and expiry pinning

At expiry, every in-the-money option pays its intrinsic value: buyers collect it and writers pay it. \"Max pain\" is the expiry level at which that total payout is smallest, so it is the level that costs option writers the least as a group. Some traders believe the index gravitates there into expiry. The calculation is simple; the belief needs care.
### How max pain is calculated

For every candidate settlement level X, add up what all calls and puts would pay:

Max pain is the X with the smallest payout. Multiply by the lot size to convert contracts into rupees.

Worked example (the illustrative chain, OI in thousands of contracts), settling at 25,000:
- 

Calls in the money: 24,600 (18 × 400 points = 7,200), 24,700 (22 × 300 = 6,600), 24,800 (35 × 200 = 7,000) and 24,900 (52 × 100 = 5,200), a total of 26,000.
- 

Puts in the money: 25,100 (85 × 100 = 8,500), 25,200 (40 × 200 = 8,000), 25,300 (20 × 300 = 6,000), 25,400 (12 × 400 = 4,800) and 25,500 (8 × 500 = 4,000), a total of 31,300.
- 

Total: 57,300 thousand contract-points. With 65 units per contract, that is 57,300 × 1,000 × 65 = ₹3,72,45,00,000, or about ₹372 crore.

Repeating the sum at every level traces a bowl:

Expiry level

Total payout (₹ crore)

24,600

1,773

24,800

846

24,900

547

25,000

372 (max pain)

25,100

426

25,200

629

25,400

1,476
### What the bowl tells you
- 

The bottom (25,000) is the writers' cheapest outcome. Here it coincides with the biggest put wall, which is common: the heaviest strikes dominate the sum.
- 

The steeper side shows where writers are most exposed. A 100-point fall to 24,900 raises the payout by ₹174 crore; a 100-point rise to 25,100 adds only ₹53 crore. The heavy put OI at 25,000 makes a fall the costlier surprise for writers.
- 

That steep side is also where acceleration risk sits. If 25,000 breaks, put writers must cover or hedge by selling futures, and that selling pushes the index further down (the gamma chapter explains the mechanics).
### Why price might gravitate there
- 

Hedging. Traders who are net long options near a heavily traded strike hedge by selling into rallies and buying into dips. That pulls the price back toward the strike, an effect called pinning.
- 

Defence. Large writers have every reason to keep the index away from their strikes into the close, and some have the size to try.
- 

Fading interest. As expiry nears, at-the-money premiums collapse, directional bets thin out, and the heavily traded strikes become the reference points.
### What the evidence says

In US equity options, Ni, Pearson and Poteshman found that the closing prices of stocks with listed options cluster at strike prices on expiration dates. Returns of optionable stocks were altered by at least 16.5 basis points on average on each expiration date, shifting market capitalisation by roughly $9 billion. They attributed the effect partly to hedge rebalancing by option market makers and partly to manipulation of the stock price by firms' proprietary traders (OptionMetrics).

That is evidence that prices are drawn toward strikes on expiry, not that max pain forecasts the expiry level. The nearest heavily traded strike can pin price whether or not it is the max-pain level, and this guide found no rigorous public test of max pain as a predictor for the Nifty.
### How to use it
- 

Recompute it as the week goes on. Early in a weekly series OI is thin, and max pain jumps around.
- 

It matters most late on expiry day, when the index is already within a strike or two of it and implied volatility is low.
- 

Trends ignore it. On a trend day or a news day, the index can expire hundreds of points from max pain.
- 

Read it with the walls. With max pain at 25,000, the biggest put wall at 25,000 and the call wall at 25,200, the writers' comfort zone is 25,000 to 25,200. A break out of that zone, with OI at the broken wall falling, is the signal to respect.
- 

Never trade toward it early in the week. At best it is a late-session magnet in a quiet market.
## Gamma and option-seller hedging

Option OI does not only mark levels; it creates flows. Writers and market makers hedge their options with futures, and the size and direction of that hedging depend on gamma. This is why some expiries are pinned to a strike while others run away from it.
### Long gamma and short gamma

An option position's delta changes as the index moves, so a hedged position has to be re-hedged after every move. Which way depends on the sign of its gamma.

Hedger

Index rises

Index falls

Effect on the market

Long gamma (net option buyer)

Position gets longer, so sells futures

Position gets shorter, so buys futures

Trades against the move: dampens volatility

Short gamma (net option writer)

Position gets shorter, so buys futures

Position gets longer, so sells futures

Trades with the move: amplifies volatility

A writer who uses stop-losses instead of hedging behaves the same way: buying back calls as the index rises, or puts as it falls, adds to the move.
### How big can the flows be?

An illustration: suppose writers who delta-hedge are net short 50,000 contracts each of the 25,000 call and the 25,000 put, with 7 days to expiry. Each option's gamma is 0.00088 per unit.
- 

Position gamma = −2 × 50,000 × 65 × 0.00088 = −5,720 units per point.
- 

After a 100-point rise, the position is 5,72,000 units shorter. Re-hedging takes about 8,800 lots of futures, roughly ₹1,430 crore of buying, into a market that is already rising.
- 

With one day left, gamma is 0.00234, and the same position needs about 23,400 lots, roughly ₹3,800 crore, for the same 100 points.

The same OI generates 2.7 times the hedging flow a week later. That is why expiry days get jumpy near big strikes. Real writers hedge partially and at intervals, so treat these figures as an upper bound for this position, not a forecast.
### Pinning vs acceleration

Pinning

Acceleration

Who dominates near the price

Long-gamma hedgers

Short-gamma hedgers, or writers being stopped out

Hedging flow

Sells rallies, buys dips

Buys rallies, sells dips

Intraday pattern

Mean reversion; moves fade at VWAP and at the walls

Momentum; breakouts that keep going

Option chain

Walls stable, IV falling, writers comfortable

A wall's OI falling fast while its premiums and IV jump

Typical moment

A quiet expiry afternoon near a heavy strike

A wall breaking on news or in a strong trend

The evidence. Barbon and Buraschi built a stock-level proxy for dealers' aggregate gamma imbalance from a large panel of US equity options. Negative (short-gamma) imbalance was associated with intraday momentum, and positive (long-gamma) imbalance with intraday reversal. The effects were strongest in the least liquid stocks, and gamma imbalance was related to the frequency and size of flash crashes (Barbon and Buraschi).
### Who is short gamma in India?
- 

The SEBI data are suggestive. In FY26, proprietary desks made about 98% of their gross derivatives profits from options, while options accounted for more than 90% of individual traders' losses (Business Today). That fits professionals being net option sellers to retail buyers, but the published figures do not show net positions, so it is an inference, not a fact.
- 

US \"gamma exposure\" (GEX) estimates assume that customers buy puts and sell calls, so dealers hold the other side. India publishes no dealer positioning, so any Indian GEX tool rests on an assumption about who is short. Treat its output as a model, not data.
### Reading gamma from the chain
- 

Gamma lives near the price and near expiry. Heavy OI at the nearest strikes with one or two days left matters far more than the same OI two weeks out.
- 

Between two stable walls, with IV falling, expect pinning: fade moves toward the walls and avoid chasing breakouts.
- 

When a wall breaks and its OI falls while premiums and IV jump, writers are covering. Expect acceleration toward the next heavy strike.
- 

The next wall is the natural target of the acceleration, and the contest repeats there.
- 

Gamma peaks on expiry afternoon, when the final settlement is being set (the expiry chapter covers the details).
### Second-order effects: vanna and charm
- 

Vanna is the change in delta when implied volatility changes. When IV collapses after an event, out-of-the-money deltas shrink and hedges are unwound, which can move the index without any news.
- 

Charm is the change in delta as time passes. Out-of-the-money deltas decay toward zero into expiry, so hedges are unwound day by day.

These effects help explain why an index sometimes drifts steadily into expiry. They depend heavily on assumptions about who holds which options, so treat any specific vanna or charm forecast as speculative.
## Volume analysis: relative volume, VWAP and volume profile

Volume is the fuel gauge. A raw volume number means little on its own; what matters is how it compares with normal (relative volume), the average price at which it traded (VWAP), and the prices where it concentrated (the volume profile).

One practical point first: the Nifty 50 index itself has no volume. Use the near-month Nifty future for volume, VWAP and volume profile. For a stock, use the cash market, which is usually deeper, or its future.
### Relative volume (RVOL)

Comparing at the same time of day matters because Indian volume is U-shaped: heavy in the first and last hours, light at midday. Volume at 10:15 compared with a full day's average would always look small.

Example. By 10:15 the Nifty future has traded 1.8 lakh contracts. Over the last 20 sessions it averaged 1.2 lakh by 10:15. RVOL is 1.5: an unusually active morning.
- 

RVOL above about 1.5 on a breakout: real participation behind the move.
- 

RVOL below about 0.8 on a breakout, especially into a call wall: suspect.
- 

A spike of three times normal after a long move, with a long wick on the candle, often marks exhaustion: a climax.

In eight US futures markets, Bessembinder and Seguin found that unexpected volume moved volatility more than expected volume did, and that positive volume surprises raised volatility more than negative ones (IDEAS/RePEc). Relative volume is a practical way to spot those surprises.
### VWAP: the session's average price

Example. Five trades: 200 contracts at 25,000, 300 at 25,010, 500 at 25,020, 400 at 25,015 and 100 at 25,030. VWAP = 3,75,22,000 ÷ 1,500 = 25,014.67. After each trade, the running VWAP was 25,000.00, 25,006.00, 25,013.00, 25,013.57 and 25,014.67.

Why it matters:
- 

Institutions are measured against it. Large orders are often executed by VWAP algorithms spread over the day, and fund managers judge their brokers' fills against VWAP.
- 

It splits winners from losers. Above VWAP, the average buyer of the day is in profit and buyers are in control; below it, sellers are.
- 

Trend days hold one side. On a trend day, pullbacks stop at or near VWAP. On a balance day, price crosses it again and again.
- 

Reclaims are signals. A drop below VWAP that is quickly bought back shows buyers defending; a rally that fails at VWAP from below shows sellers in charge.

VWAP bands. The volume-weighted standard deviation of price around VWAP gives bands. In the five-trade example the standard deviation is 7.63 points, so the ±1 band runs from 25,007.04 to 25,022.30 and the ±2 band from 24,999.41 to 25,029.93. In a real session the bands are much wider. On balance days, moves to the ±2 band tend to fade; on trend days, price rides the ±1 band.

Anchored VWAP starts the calculation at a chosen event instead of the open: a gap, a swing low, a results day. It shows the average price paid by everyone who traded since that event. A pullback that holds an anchored VWAP from a swing low means the buyers since that low are still, on average, in profit.
### Volume profile

A volume profile turns the volume histogram on its side: it shows how much traded at each price over a period. It grew out of J. Peter Steidlmayer's Market Profile, developed at the Chicago Board of Trade in the 1980s, which counted time spent at each price rather than volume.

Term

Meaning

Point of control (POC)

The price with the most volume: the session's fairest price

Value area

The range around the POC holding about 70% of the volume, bounded by the value-area high (VAH) and low (VAL)

High-volume node

A price band of heavy trading, where the market accepted value; price tends to slow there

Low-volume node

A thin band the market rejected; price tends to move through it quickly

Example. One illustrative Nifty futures session traded between 25,000 and 25,180, with volume counted in hundreds of contracts at each 10-point level.
- 

POC: 25,090, with 510 of the session's 4,150.
- 

Value area: start at the POC and repeatedly add whichever neighbouring pair of rows has more volume until 70% is covered. Here that gives 25,050 to 25,130, holding 3,110 of 4,150, or 74.9%. With coarse rows the last step often overshoots 70%.
- 

Thin tails above 25,150 and below 25,030 show prices the market visited briefly and rejected.
### Using the profile the next day

Next day's open

Reading

Above the VAH (25,130), and holding

Buyers accept higher prices: bullish; look for the move to extend

Inside the value area

Balance: expect rotation between 25,050 and 25,130, with the POC as a magnet

Below the VAL (25,050), and unable to get back in

Sellers in control: bearish

James Dalton's \"80% rule\" is a well-known practitioner guideline: if price opens outside the previous value area and then trades back inside it for two consecutive 30-minute periods, it often travels all the way to the other side of the value area.
### Profile shapes and the four quadrants
- 

P-shaped (a thin stem below and a fat top): a fast rise followed by acceptance at higher prices. Dalton associates it with short covering. Check whether futures OI fell during the rise.
- 

b-shaped (a fat bottom and a thin stem above): a fast fall followed by acceptance lower, typical of long liquidation. Check for falling OI.
- 

D-shaped (fat in the middle): a balanced, two-sided day.
- 

Thin and elongated: a trend day, with little time spent at any price.

When the profile's shape and the futures quadrant agree (a P-shape with OI falling, for example), the reading is much more reliable than either alone.
## Order flow I: bid, ask, aggression and the footprint chart

Every trade is a meeting between someone who waited and someone who did not. Order-flow analysis counts which side was in a hurry, at every price. It answers a question OI cannot: within this candle, were buyers or sellers pushing?
### The order book in one minute
- 

Bid: the highest price a buyer is waiting to pay. Ask (or offer): the lowest price a seller is waiting to accept. The gap between them is the spread.
- 

A limit order waits in the book at a chosen price. It is passive: it provides liquidity.
- 

A market order (or a limit order priced to execute at once) trades immediately against the best waiting order. It is aggressive: it takes liquidity.

Example. The Nifty future shows a best bid of 25,100.0 for 150 contracts and a best ask of 25,100.5 for 90. A trader who must buy now pays 25,100.5, the ask. One willing to wait joins the bid at 25,100.0 and hopes a seller comes to them.
### Who was the aggressor?
- 

A trade at the ask means a buyer crossed the spread: a buyer-initiated trade (\"lifting the offer\").
- 

A trade at the bid means a seller crossed: a seller-initiated trade (\"hitting the bid\").

Indian retail data feeds do not label the aggressor, so it has to be inferred:

Method

Rule

Weakness

Quote rule

Above the bid-ask midpoint = buy; below = sell

Fails for trades exactly at the midpoint

Tick rule

Price up from the last trade = buy; down = sell; unchanged = same as the last classification

Misreads trades in fast, two-way markets

Lee and Ready (1991)

Quote rule first, tick rule for trades at the midpoint

The research standard, but still imperfect
### Delta (the order-flow kind)

In order flow, delta means aggressive buy volume minus aggressive sell volume in a bar. It has nothing to do with the option Greek of the same name; context tells you which is meant.

Example. In a five-minute bar, 1,170 contracts traded at the ask and 415 at the bid. Delta = +755: buyers were clearly the more urgent side.
### The footprint chart

A footprint chart splits each candle into price rows. Each row shows the volume that traded at the bid (sellers hitting) on the left and at the ask (buyers lifting) on the right. The diagram shows three consecutive five-minute bars of Nifty futures, grouped into 10-point rows for readability; a real footprint shows every tick.
### Imbalances: comparing diagonally

An imbalance compares buyers and sellers who were active at the same moment. As price ticks between two levels, buyers lift the ask at the upper level while sellers hit the bid at the lower one. So the comparison runs diagonally: ask volume at a price against bid volume one row below. A common threshold is 3 to 1.
- 

Bar A: at 25,120, buyers lifted 330 contracts against 105 sold at 25,110 (3.1×). At 25,130 the ratio is 280 to 90 (3.1×), and at 25,140 it is 180 to 60 (3.0×). Three stacked buy imbalances, with a bar delta of +755: initiative buying. The 25,120–25,140 zone often acts as support if price comes back to it.
- 

Bar B: the bar traded 2,825 contracts, the most of the three, yet its delta was only +45 and it closed back near its open. At 25,150, sellers hit 380 contracts while buyers could lift only 35 at 25,160: a sell imbalance of 10.9×. Buyers were still pushing, but a passive seller absorbed everything. This is absorption.
- 

Bar C: sell imbalances at 25,130 (330 against 60, 5.5×), 25,120 (290 against 80, 3.6×) and 25,110 (240 against 70, 3.4×). Three stacked sell imbalances and a delta of −780: sellers have taken control.

The story: buyers drove price up in bar A, ran into a large passive seller at 25,140–25,150 in bar B, and sellers took over in bar C. A long bought on bar A's breakout should have been protected as soon as bar B showed absorption at the high, before bar C did the damage.
### Delta shows urgency, not intelligence

Large players often use limit orders to build positions without moving the price. A big passive buyer absorbing aggressive sellers produces negative delta while price holds: a bullish sign hidden behind a bearish-looking number. So always read delta against price's response:

Bar delta

Price response

Reading

Strongly positive

Rising

Initiative buying is succeeding

Strongly positive

Flat or falling

Passive sellers are absorbing: a bearish warning

Strongly negative

Falling

Initiative selling is succeeding

Strongly negative

Flat or rising

Passive buyers are absorbing: a bullish warning
### Caveats for Indian data
- 

Footprints need every trade, with the bid and ask at that moment. Many retail feeds send periodic snapshots instead, so delta has to be estimated from volume changes between snapshots and where the last price sat relative to the bid and ask. Treat such delta as approximate, and check how your data vendor builds it.
- 

Use the instrument where the volume is. For the index, that is the Nifty future. Option footprints are thin except at the most active strikes.
## Order flow II: cumulative delta, divergence, absorption and exhaustion

One bar's delta is a snapshot. Adding the deltas up through the session shows whether aggressive buyers or sellers have been winning the day, and, more usefully, when their effort stops matching the price.
### Cumulative volume delta (CVD)

Example. Twenty five-minute bars of Nifty futures. The first nine bars had deltas of +120, +90, +150, +80, +130, +100, +160, +70 and +110, so CVD climbed to 1,010 while price rose from 25,020 to 25,140.
- 

Bars 1–9: confirmation. Price and CVD rise together. Aggressive buyers are driving the advance.
- 

Bars 10–13: pullback. Price eases to 25,098 and CVD falls to 660. Sellers are active, but price holds well above the session's start.
- 

Bars 14–17: divergence. Price makes a new high at 25,160, but CVD recovers only to 860, below its earlier peak of 1,010. The higher price was reached with less aggressive buying than the earlier high: a bearish divergence.
- 

Bars 18–20: resolution. Price falls to 25,095 and CVD to 410. The new high had no fuel behind it.
### Reading divergences

Price

CVD

Name

Reading

Higher high

Higher high

Confirmation

Aggression supports the trend

Higher high

Lower high

Bearish divergence

The rally is running on weaker buying; vulnerable

Lower low

Lower low

Confirmation

Aggression supports the decline

Lower low

Higher low

Bullish divergence

The decline is running on weaker selling; sellers are tiring

A divergence is a warning, not a trigger. Act when price confirms it: by breaking the last swing low, losing VWAP, or failing a retest of the high.
### Absorption

Absorption is heavy aggressive volume on one side that fails to move price, because a large passive order on the other side soaks it up.
- 

What it looks like: high volume, a small range, and either one-sided delta that goes nowhere or delta near zero at the extreme of a move. Bar B in the footprint example (2,825 contracts, delta +45, sellers absorbing at 25,150) is the textbook case.
- 

What it means: someone large is defending a level. Absorption at or just below a call wall is often option writers or passive sellers protecting their strike.
- 

What happens next: if the absorber holds, price reverses away from the level. If the absorber is exhausted and the level gives way, the break is often fast, because the aggressive side has been building up behind it.
### Exhaustion

Exhaustion is the opposite problem: the aggressive side runs out of participants.
- 

A final burst: a spike in volume and delta at a new extreme, with no follow-through in the next bars.
- 

A thin extreme: at the very top of a rally, only a handful of contracts trade at the ask. Bar B's top row (25,160) shows just 35 contracts bought: buyers had nothing left at that price.
- 

Shrinking deltas: each push higher comes with a smaller positive delta than the last.
### CVD together with futures OI

This is the combination that answers \"is this move real?\" Delta says who was aggressive; OI says whether they were opening or closing.

Price

CVD

Futures OI

Reading

Up

Up

Up

Aggressive buyers opening new longs: the strongest bullish combination

Up

Up

Down

Aggressive buying is short covering: strong now, fragile later

Up

Down or flat

Down

A drift up on exits and passive flow: the weakest rally; likely to fade

Down

Down

Up

Aggressive sellers opening new shorts: the strongest bearish combination

Down

Down

Down

Aggressive selling is long liquidation: fast, but it can exhaust itself

Down

Up

Up

New longs buying aggressively into a falling market: they risk being trapped, which fuels a further fall if the level breaks
### What the evidence says

Chordia and Subrahmanyam studied daily order imbalances in individual US stocks. Large traders split their orders, so imbalances persist from day to day. Lagged imbalances were positively related to returns, but that relation reversed once the current day's imbalance was controlled for, consistent with market makers absorbing the pressure and then working off their inventory. Strategies based on order imbalances earned statistically significant returns (IDEAS/RePEc).

For a trader, the lesson is twofold: sustained one-sided aggression tends to continue while the large orders behind it are still being worked, and part of the price impact unwinds once the pressure stops. That is the mechanism behind both trend confirmation and divergence.
### Practical rules
- 

Reset CVD each session. For multi-day views, anchor it to a key event, such as a breakout day.
- 

Compare CVD at matching price pivots; the absolute number means nothing across days.
- 

Wait for price to confirm a divergence before acting on it.
- 

For the index, use Nifty futures CVD. At-the-money option CVD can help, but it is noisy.
- 

Check whether a big CVD change came from one large print. A single block can distort the line without reflecting broad aggression.
## Market depth and the order book

The order book, or market depth, shows the limit orders waiting at each price. It reveals intentions; trades reveal commitment. Intentions can change in a millisecond, which is the main thing to remember about depth.
### What the screen shows

The standard NSE depth view shows the best five bid and ask prices, the quantity at each, and the number of orders behind it. An illustrative Nifty futures book:

Bid orders

Bid quantity

Bid

Ask

Ask quantity

Ask orders

12

450

25,100.0

25,100.5

210

6

9

380

25,099.5

25,101.0

260

8

15

520

25,099.0

25,101.5

190

5

7

300

25,098.5

25,102.0

220

7

6

300

25,098.0

25,102.5

170

4

The five bid levels hold 1,950 contracts and the five ask levels 1,050.

A reading of +0.30 means bids outweigh asks: mild buying pressure over the next few seconds to minutes, not a forecast for the day. The order counts matter too. 450 contracts from 12 orders is a crowd; 450 contracts from a single order is one participant, who may be real or may be bluffing.
### Order-flow imbalance (OFI)

Cont, Kukanov and Stoikov showed that, over short intervals, price changes are driven mainly by the imbalance between supply and demand at the best bid and ask. That imbalance counts new orders, cancellations and trades on each side. The relation is linear, its slope is inversely related to market depth, and it is more robust than the relation between price changes and trade volume. Their data covered 50 US stocks from the NYSE (arXiv).
- 

Buying pressure: new bids, bids moving up, and sellers' asks being cancelled or taken out.
- 

Selling pressure: new asks, asks moving down, and bids being cancelled or hit.
- 

Depth sets the impact: the same imbalance moves a thin book further than a deep one. That is why a mid-cap stock future jumps on order sizes the Nifty future absorbs without noticing.
### Why the book misleads
- 

Orders are cancelled constantly. Much of the visible depth never trades, especially where algorithms quote and re-quote.
- 

Spoofing means placing large orders with no intention of trading them, to create a false impression, then cancelling. It is market manipulation: SEBI's rules on fraudulent and unfair trade practices prohibit manipulative orders, and in the US spoofing was made explicitly illegal by the Dodd-Frank Act.
- 

Hidden size. Algorithms slice large orders into small pieces, and in the cash market NSE allows orders that disclose only part of their quantity. The visible book understates the real size of big players.
- 

Pulling. A large bid that vanishes as price approaches was never meant to be filled.

The practical response is to trust trades over quotes. A bid that is hit again and again and keeps refilling is real: it is absorption, seen live. A bid that disappears before it is tested was not.
### Indian data limits
- 

Most broker feeds give five levels of depth.
- 

Deeper books exist. DhanHQ offers 20-level depth for up to 50 instruments per connection, and 200-level depth for one instrument per connection, for NSE equity and derivatives (DhanHQ).
- 

Feeds are sampled. Depth changes many times a second, so a retail feed shows a series of snapshots, not every change.
- 

Option books are thin away from the at-the-money strikes; little can be read from them.
### Flow toxicity and VPIN

Easley, López de Prado and O'Hara called order flow \"toxic\" when it adversely selects market makers, who then supply liquidity at a loss. Their VPIN measure estimates toxicity from volume imbalance and trade intensity, sampled in volume time rather than clock time, and they presented it as an indicator of short-term, toxicity-induced volatility (IDEAS/RePEc). Later research has disputed how well it forecasts, so treat it as a concept rather than a ready-made signal.

The trader's version of the idea: when aggressive flow stays one-sided, liquidity providers widen their quotes and pull depth. A book that suddenly thins after persistent one-sided flow is a warning that a fast move may follow.
### How to use depth
- 

Use it for timing, not direction. The book matters at the moment you enter or exit.
- 

Watch replenishment. A level that keeps refilling after being hit has a real buyer or seller behind it.
- 

Watch pulling. A wall that vanishes on approach tells you its owner did not want to trade there.
- 

Combine it with trades. A bid-heavy book while aggressive buyers are lifting the ask is stronger than either alone.
- 

Line it up with the chain. Heavy offers stacked in the futures book at 25,200 while the 25,200 call wall is growing means the level is being defended in both markets.
## Putting it together: the confluence matrix

Each stream answers one question. A trade worth holding needs several of them to agree, and the moment they stop agreeing is usually the moment to act. The matrix below collects the signals from every chapter so far.
### The matrix

#

Signal

Bullish

Bearish

Time frame

Usefulness","complete":false,"next":{"parentId":"mwt5tp78m3z.80069","from":"mwt5tp78m3z.80124","then":{"from":"mwt5tp78m3z.81572"}}},"frame":{"slug":"05dddb12-f474-44db-b238-28cab743f502","url":"https://claude.ai/code/artifact/05dddb12-f474-44db-b238-28cab743f502","artifactUrl":"https://claude.ai/code/artifact/05dddb12-f474-44db-b238-28cab743f502"}}