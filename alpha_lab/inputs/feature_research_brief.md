# India Equity Feature Research Brief: Cash-Market & F&O-Derived Signals

 · 
## 1. Executive summary

F&O data is worth adding to an Indian equity model, but it reaches the cash book by three routes and only one of them is stock-specific.
- 

Stock-level signals, for the roughly 200–230 F&O stocks. Option-implied measures have the strongest record abroad and are almost untested on NSE: changes in call and put IV, the call–put IV spread, put skew and option-to-stock volume. India's limits on overnight shorting push bearish views into derivatives, so these should be more informative here, especially for bad news.
- 

Market regime, for every stock. India VIX, the variance risk premium, the Nifty put-call ratio and FII and client positioning describe the regime that stock features should be read in.
- 

Spillovers, for stocks without derivatives. Sector aggregates of F&O features and lead-lag from large F&O peers carry the information to the rest of a 1,500–2,000 stock universe.

On the example of rising open interest: rising OI alone says only that leveraged positions are growing, not which side holds them. It becomes informative when combined with price direction (the build-up quadrant), where the OI sits (calls or puts, which strikes, how IV moves), who holds it (participant data) and how large it is against float and MWPL. Raw OI and the build-up quadrants have no rigorous Indian test, and max pain shows no effect, so they belong on the test list rather than in the core.

Cash-market evidence is stronger. Indian momentum earned about 11% a year from 1993 to 2025 in the IIM Ahmedabad factor data, and earnings drift, short-term reversal and 52-week-high proximity are the next candidates. Four rule changes since October 2025 (delta-based ban rules, the futures pre-open, the April 2026 STT rise and the August 2026 closing auction) split the history into regimes that every backtest must respect.

Test these first

Rank

Feature

IDs

Why first

1

12-1 month momentum

MOM-01

Strongest Indian factor evidence

2

52-week-high proximity

MOM-03

Adds to momentum and matches the trend template

3

Short-term reversal

MOM-02

Global regularity; separates breakouts from overextension

4

Earnings surprise and announcement return

FUN-01, FUN-02

Indian drift evidence, mixed but cheap to test

5

Abnormal volume × return sign

LIQ-03

Documented high-volume premium from free data

6

Delivery % z-score

LIQ-01

India-only signal that has never been rigorously tested

7

Lottery demand (MAX)

VOL-04

Strong abroad and plausible in a retail-heavy market

8

Change in call and put IV

OPT-02

About 1% a month decile spreads in US data

9

Call–put IV spread

OPT-03

50 bp a week in US data; fits the short-sale channel

10

Put skew

OPT-04

10.9% a year in US data; supportive Indian event studies

11

Option-to-stock volume

OPT-08

0.34% a week in US data, stronger where shorting is costly

12

Price × OI quadrant, continuous

FUT-01

The most-used Indian heuristic, never properly tested

13

Excess carry

FUT-04

Captures bearish demand that cash shorting cannot express

14

India VIX percentile and variance risk premium

POS-04, POS-05

Sets the volatility regime and barrier widths

15

Sector aggregates of F&O features

SEC-01

Carries derivatives information to non-F&O stocks
## 2. Scope, design assumptions and evidence grades

This brief is built for a daily-scan swing strategy: 5–20 trading-day holds, entries once or twice a week, on roughly 1,500–2,000 NSE stocks. Only F&O-eligible stocks have their own futures and options, so every idea below is tagged by where it can be used.

Item

Assumption used in this brief (change any row that is wrong)

Universe

~1,500–2,000 NSE equity stocks (EQ and BE series) after liquidity filters; a Minervini-style trend template as a pre-filter

Horizon

Swing, 5–20 trading days; end-of-day features; intraday features only where flagged

Model

One pooled ("universal") LightGBM model across all stocks, trained on cross-sectionally normalised features

Labels

Triple-barrier: profit-take, stop-loss and time-out, with barriers set in ATR multiples

Validation

Purged and embargoed walk-forward

Costs

India-specific: STT, stamp duty, exchange and SEBI fees, GST, DP charges, plus market impact

Later extension

A futures and options overlay on the equity book: hedges, leverage and shorts

Tag

Where the feature can be used

ALL

Every stock in the cash universe

FNO

Only stocks with their own futures and options (F&O-eligible)

MKT

A market- or sector-level series broadcast to every stock as regime or context

Grade

Meaning

How to treat it

A

Replicated in peer-reviewed work across markets, with supporting Indian evidence

Core candidate; expect a small but persistent edge

B

Strong evidence abroad; Indian evidence thin, mixed or untested

Test early; Indian rules may strengthen or kill it

C

Practitioner heuristic with weak or no rigorous evidence

Treat as a hypothesis; drop quickly if it fails out of sample

A feature marked IN exists only because of Indian market rules or disclosures, so there is no foreign evidence to lean on. Feature IDs such as FUT-03 point to the master catalogue in section 10. Everything here is a research hypothesis for backtesting, not investment advice.
## 3. What makes India different

Indian rules change what the signals mean and how a backtest can trade them, and four rule changes since October 2025 split any test window into regimes.

Rule

Current state (October 2026)

What it means for features and backtests

Short selling

Anyone may short, but naked shorts are banned and institutions cannot day-trade. Only F&O-traded stocks are eligible, so an overnight short needs borrowed stock through SLB. Brokers upload scrip-wise short sales each morning; exchanges publish them weekly.

Bearish views move into futures and options, so derivatives carry more negative information here than where borrowing is cheap. Non-F&O stocks are long-only in practice.

F&O universe

Entry needs a top-500 rank, median quarter-sigma order size of at least ₹75 lakh, MWPL of at least ₹1,500 crore and average daily delivery value of at least ₹35 crore over six months. Exits use a product-success test, such as ₹75 crore daily turnover and ₹500 crore notional OI.

Stock-level derivative features exist for roughly 200–230 names (approximate; take the dated list from each day's F&O bhavcopy). Entry and exit are events in their own right.

Settlement of stock derivatives

Stock futures and options settle by physical delivery; index derivatives settle in cash.

In-the-money stock positions are cut before expiry, so stock OI falls mechanically in the final days of each series. Normalise OI by days-to-expiry.

Expiry calendar

NSE contracts expire on Tuesday (Nifty weekly; monthly contracts on the last Tuesday) and BSE on Thursday. The last NSE Thursday expiry was 28 Aug 2025. Only one benchmark index per exchange keeps weekly options. SEBI said in September 2025 it would consult on ending weekly expiries; this review found no consultation paper by October 2026.

Use days-to-expiry, not weekday dummies. Expect another break if weeklies end.

Position limits and bans

OI is counted on a delta-based futures-equivalent (FutEq) basis. Single-stock MWPL is the lower of 15% of free float or 65× cash volume, reset quarterly (from 1 Oct 2025). Above 95% of MWPL only risk-reducing trades are allowed, and intraday checks run at least four random times a day (from 3 Nov 2025).

MWPL utilisation and ban flags were redefined in October 2025 (notional to FutEq). Rebuild the series on one basis or add a regime flag. A ban stops new F&O positions, not cash trading.

Opening and closing prices

The cash pre-open auction takes orders from 9:00 to 9:08. Stock and index futures got the same pre-open on 8 Dec 2025. From 3 Aug 2026, F&O-eligible stocks close through a 3:15–3:35 pm auction (reference price = VWAP of 3:00–3:15 pm, ±3% band) and F&O trades until 3:40 pm. Other stocks keep the 3:00–3:30 pm VWAP close.

Before August 2026 the official close was a 30-minute average, not a price anyone could trade. Since then F&O stocks close at an auction you can join. Model "execute at close" separately for each era.

Price bands and surveillance

Non-F&O stocks have fixed daily bands of 2%, 5%, 10% or 20%; F&O stocks have dynamic bands. Exchanges place stocks under ASM, GSM or ESM stages, some in trade-for-trade, with higher margins.

A stock locked at its band cannot be traded, so simulate fills and cap labels. Surveillance stage is both a filter and a feature.

Costs and tax

STT is 0.1% on each side of delivery trades. From 1 Apr 2026 it is 0.05% on futures sold, 0.15% on option premium sold and 0.15% on exercised options (was 0.02%, 0.10% and 0.13%). Buyback proceeds are now taxed as capital gains, with an extra charge for promoters.

Futures hedges and shorts carry 2.5× the STT of a year earlier, so re-cost any F&O overlay. Buyback events need the new tax treatment.

Sources: short-selling framework · F&O eligibility · Tuesday expiry · weekly-expiry consultation remark · FutEq and MWPL · ban and monitoring dates · F&O pre-open · closing auction design (NSE) · closing auction start date · STT from April 2026 · buyback tax

Regime-break log (newest first). Split every backtest at least at November 2024 and 1 Oct 2025, and report results per regime.

Date

Change

Backtest treatment

3 Aug 2026

Closing auction for F&O stocks; F&O hours extended to 3:40 pm

New close-price definition for F&O stocks

1 Apr 2026

F&O STT raised (futures 0.05%, option premium 0.15%)

Higher overlay costs; check for lower speculative OI

8 Dec 2025

Pre-open auction for current-month stock and index futures

Futures opens become auction prices

3 Nov 2025

Intraday FutEq checks on MWPL

Fewer intraday limit breaches

1 Oct 2025

FutEq OI for bans; new MWPL formula

Ban and utilisation series redefined

2 Sep 2025

First NSE Tuesday expiry; BSE moves to Thursday

Expiry calendar shifts

3 Jul 2025

SEBI interim order against Jane Street alleging Bank Nifty expiry-day manipulation on 18 expiries, January 2023 to March 2025; ₹4,843.57 crore impounded (allegations, contested)

Flag or drop expiry-day index moves in labels

1 Jul 2025

New index-futures position limits (institutions: 15% of OI or ₹500 crore)

Index futures OI composition may shift

Nov 2024

Weekly options cut to one benchmark index per exchange; larger index contracts

Bank Nifty weeklies end; index options OI changes character

1 Oct 2024

F&O STT raised to 0.02% (futures) and 0.10% (option premium)

Earlier cost step

Source for the Jane Street row: Oxford Business Law Blog.
## 4. Cash-market features

For a 5–20 day swing model, the best-supported cash-market predictors in India are 12-1 month momentum, 52-week-high proximity, short-term reversal and post-earnings drift. Indian disclosures add delivery, ownership, pledge and surveillance data that have no foreign equivalent, and little published testing.

Indian momentum is unusually strong: the IIM Ahmedabad factor library shows the momentum factor (WML) earning 10.96% a year from October 1993 to December 2025, against 6.86% for value (HML) and −4.01% for size (SMB).
### 4.1 Technical terms used below, worked on one stock at ₹600

Term

Definition

Example

DMA (daily moving average)

Average of the last n closing prices; the 50-DMA uses 50 days

50 closes averaging ₹560 put the price 7.1% above its 50-DMA

ATR(14) (average true range)

14-day average of the true range = max(high − low, |high − previous close|, |low − previous close|)

True ranges averaging ₹12 give ATR = ₹12, or 2.0% of price; a 2×ATR stop sits at ₹576

ADR% (average daily range)

20-day mean of (high − low) / close; not the US-listed receipts in 4.8

Daily ranges averaging ₹15 give ADR% = 2.5%

RSI(14) (relative strength index)

100 − 100 / (1 + average gain / average loss) over 14 days, Wilder-smoothed; above 70 is stretched up, below 30 stretched down

Average gain ₹6 and average loss ₹3 give RS = 2 and RSI = 66.7

Relative strength (RS)

Stock return minus benchmark return, or the percentile rank of a weighted 3/6/9/12-month return

Stock +40% vs Nifty 500 +12% over 12 months is RS of +28 points
### 4.2 Trend and momentum

ID

Feature

How to compute

Grade

Evidence or rationale

MOM-01

12-1 month momentum

Return from day t−252 to t−21

A

WML 10.96% a year, 1993–2025 (IIMA library); 17.3% a year, 1994–2017 (Agarwalla, Jacob & Varma 2017)

MOM-02

Short-term reversal

Return over the last 5 and 21 days; expect a negative sign

A

Global regularity (Jegadeesh 1990; Lehmann 1990); FII-flow-driven moves in Indian stocks partly reverse within five days (Acharya, Anshuman & Kumar 2015)

MOM-03

52-week-high proximity

Close / highest close of the last 252 days

B

Predicts beyond plain momentum in US data (George & Hwang 2004); also a trend-template rule

MOM-04

Residual momentum

12-1 month momentum of residuals from a market-plus-sector regression

B

Lower crash risk than raw momentum (Blitz, Huij & Martens 2011); untested in India

MOM-05

Relative strength

63- and 126-day excess return vs Nifty 500 and the sector index; percentile rank

B

Combines stock and industry momentum (Moskowitz & Grinblatt 1999)

MOM-06

Trend-template distances

Close vs 50/150/200-DMA stack; 21-day slope of the 200-DMA; % above 52-week low; % below 52-week high

C

Practitioner rule (Minervini); feed the continuous distances, not only the pass/fail flag

MOM-07

Moving-average distance

(close / 50-DMA − 1) and (close / 200-DMA − 1), in ATR units

B

Trend strength; with MOM-02 it separates breakouts from overextension

MOM-08

Momentum quality

Share of up-days minus share of down-days in the momentum window, signed by the return

B

Momentum built from many small moves persists longer (Da, Gurun & Warachka 2014)

MOM-09

Industry momentum

6-month equal-weighted return of the stock's industry

B

Moskowitz & Grinblatt (1999); useful for small caps without derivatives

MOM-10

RSI(14) and distance from 20-day high or low

As defined in 4.1

C

Mostly a short-term reversal proxy; keep only if it adds to MOM-02
### 4.3 Volatility and risk

ID

Feature

How to compute

Grade

Evidence or rationale

VOL-01

Realised volatility

Annualised standard deviation of daily log returns, 21 and 63 days

B

Low-volatility deciles beat high-volatility deciles in the Nifty 200 (11.4% vs 1.3% a year, 2001–15), but not after controlling for beta (Joshipura & Joshipura 2016)

VOL-02

Idiosyncratic volatility

Residual standard deviation from a market-plus-sector regression, 63 days

B

High idiosyncratic volatility predicts low returns in US data (Ang, Hodrick, Xing & Zhang 2006)

VOL-03

Beta

252-day beta to Nifty 500, shrunk toward 1

B

Betting-against-beta earned 1.70% a month in India, 1998–2013 (Agarwalla, Jacob, Varma & Vasudevan 2014)

VOL-04

Lottery demand (MAX)

Average of the 5 highest daily returns in the past 21 days

B

Lottery-like stocks underperform (Bali, Cakici & Whitelaw 2011); retail-heavy markets may show it more

VOL-05

Volatility contraction

ATR(10) / ATR(50); Bollinger bandwidth percentile over 252 days

C

Base-building before breakouts; also scales triple-barrier widths

VOL-06

Overnight vs intraday returns

21-day sums of close-to-open and open-to-close returns

B

The two legs reflect different clienteles and predict differently (Lou, Polk & Skouras 2019)

VOL-07

Downside risk

63-day skewness of daily returns; downside beta

B

Investors overpay for positive skew (Boyer, Mitton & Vorkink 2010)
### 4.4 Volume, delivery and liquidity

ID

Feature

How to compute

Grade

Evidence or rationale

LIQ-01

Delivery percentage

Deliverable quantity / traded quantity from the NSE full bhavcopy; z-score vs the stock's own 60 days, then rank across stocks

C · IN

No rigorous test found; the only study found covers two stocks. Hypothesis: high delivery on up-days marks accumulation

LIQ-02

Delivery value shock

₹ delivery value / its 50-day median

C · IN

Same idea in money terms; average daily delivery value also drives F&O eligibility

LIQ-03

Abnormal volume with return sign

Volume / 50-day median, interacted with the day's return sign

B

Unusually high volume is followed by higher returns (Gervais, Kaniel & Mingelgrin 2001)

LIQ-04

Average trade size

Traded quantity / number of trades (both in the full bhavcopy), z-scored

C · IN

Larger trades suggest institutional participation

LIQ-05

Close vs day VWAP

Close / day's average price (AVG_PRICE in the full bhavcopy) − 1

C

Closing above the day's VWAP suggests late-day buying

LIQ-06

Amihud illiquidity

21-day mean of |return| / ₹ traded value

A

Illiquidity premium (Amihud 2002); also a capacity filter

LIQ-07

Turnover

Volume / free-float shares, 21 days

B

High turnover predicts lower returns (Datar, Naik & Radcliffe 1998)

LIQ-08

Volume dry-up

10-day / 50-day average volume inside a base

C

Practitioner breakout setup; test together with VOL-05

LIQ-09

Spread estimate

Corwin–Schultz or Abdi–Ranaldo estimator from daily high, low and close

B

Feeds the cost model and capacity limits
### 4.5 Ownership and flows

ID

Feature

How to compute

Grade

Evidence or rationale

OWN-01

FPI holding change

Quarter-on-quarter change in FPI % from the shareholding pattern, dated by its filing (due within 21 days of quarter end)

B · IN

Institutional ownership changes predict returns in many markets; never date it to quarter end

OWN-02

Mutual fund holding change

Month-on-month change in shares held by all schemes (portfolios disclosed within 10 days of month end)

B · IN

Domestic funds became the marginal buyer as SIP flows grew; test both herding and crowding

OWN-03

Promoter and insider buying

Net open-market buys from insider and takeover-code disclosures, scaled by market cap

B · IN

Opportunistic insider buys predict returns abroad (Cohen, Malloy & Pomorski 2012); disclosures reach exchanges within a few trading days

OWN-04

Promoter pledge

Pledged % of promoter holding, its change, and pledge creation, release or invocation events

C · IN

High or rising pledges raise forced-selling risk

OWN-05

Bulk and block deals

Named daily deals as % of float, flagged by buyer and seller type

C · IN

Known long-term buyers may signal quality; large sellers add supply

OWN-06

Short-sale disclosures

Weekly short positions published by exchanges under the 2024 framework, as % of float

B · IN

Short interest predicts lower returns abroad (Asquith, Pathak & Ritter 2005); the Indian series is short

OWN-07

SLB activity

Borrowed quantity and lending fee in the SLB segment

C · IN

Costly borrow signals short demand; Indian SLB is thin

OWN-08

Margin-funded positions

Scrip-wise margin-trading exposure as % of float, if the exchange report is available for the full history

C · IN

Concentrated retail leverage means crowding and forced-sale risk
### 4.6 Fundamentals and earnings

ID

Feature

How to compute

Grade

Evidence or rationale

FUN-01

Standardised unexpected earnings (SUE)

(EPS this quarter − EPS four quarters ago) / standard deviation of that change over 8 quarters

B

Top-minus-bottom SUE decile drifted 4.8% over days +2 to +64 in the Nifty 500, 2002–17 (Harshita, Singh & Yadav 2018); a 2014–18 study found no drift (Gupta & Dhusia 2021)

FUN-02

Earnings announcement return

Abnormal return vs sector from day −1 to +1 around the results filing

B

Measures the surprise without consensus data (Chan, Jegadeesh & Lakonishok 1996)

FUN-03

Revenue surprise

SUE computed on quarterly sales

B

Adds to earnings surprise (Jegadeesh & Livnat 2006)

FUN-04

Estimate revisions

1- and 3-month change in consensus EPS; needs a consensus vendor

A

Revision momentum is among the strongest global signals

FUN-05

Value

Earnings, book and cash-flow yields, ranked within sector

B

HML earned 6.86% a year in India, 1993–2025 (IIMA library); slow-moving, so mainly a conditioning variable for swing trades

FUN-06

Quality and profitability

Gross profit / assets, ROCE, accruals, leverage, interest cover

B

Profitability adds explanatory power in BSE-500 stocks, 1999–2020 (Prakash, Singh & Singh 2023); accruals (Sloan 1996)

FUN-07

Growth and acceleration

Year-on-year sales and EPS growth; change in growth over three quarters; margin trend

C

Central to most Indian swing playbooks, with little formal testing

FUN-08

Results calendar

Days to and since results (due within 45 days of quarter end, 60 for the year-end quarter)

—

A control and event flag rather than a signal: results days dominate swing-trade variance
### 4.7 Events and calendar

ID

Feature

How to compute

Grade

Evidence or rationale

EVT-01

Index inclusion and exclusion

Days to the effective date of Nifty, Sensex, MSCI and FTSE changes; estimated passive flow in days of volume

B

Nifty 50 additions give back their gain within 60 days; deletions fall for 10 days, then gain 4–7% over days 60–240 (Chhatwani 2020)

EVT-02

AMFI cap reclassification

Moves between AMFI's large-, mid- and small-cap lists, revised twice a year

C · IN

Scheme mandates force buying or selling after a move

EVT-03

F&O inclusion or exclusion

Exchange circular date and days to the first or last trading day

B · IN

Excluded stocks underperformed by 4.07% around removal (Agrawal et al., ISB working paper); inclusion announcements earned positive abnormal returns (Chaturvedula & Kamaiah 2008)

EVT-04

IPO lock-in expiry

Days to anchor (30 and 90 days) and pre-IPO (6 months) lock-in expiries; unlocking shares / float

B · IN

Supply overhang depresses prices around lock-in expiry (Field & Hanka 2001, US)

EVT-05

Equity issuance

QIP, OFS, rights and large block sales: discount to market and size / float

C

Short-term price pressure, then partial recovery

EVT-06

Splits, bonuses and buybacks

Announcement and record dates; buyback size, premium and route

B

Splits drift up after announcement (Ikenberry, Rankine & Stice 1996); buyback tax changed in 2026

EVT-07

Credit-rating actions

Downgrades and outlook changes from CRISIL, ICRA, CARE and India Ratings

B · IN

Negative events with drift; option skew predicts the post-downgrade move (Shukla et al. 2026, 42 events)

EVT-08

Governance red flags

Auditor or senior-management resignation, pledge invocation, regulator orders, tax demands, from classified announcements

C · IN

Rare, large negative events; use as exclusion flags

EVT-09

Calendar controls

Turn of month, pre-holiday, Union Budget, RBI policy and US FOMC days, results-season density

B

Mostly variance controls; expiry effects are in section 8
### 4.8 Cross-market and macro (tag MKT)

ID

Feature

How to compute

Grade

Evidence or rationale

MAC-01

GIFT Nifty overnight move

GIFT Nifty change from the Nifty close to 9:00 IST

B

Prices the overnight session; drives gap and opening-auction features

MAC-02

US ADR overnight return

Overnight FX-adjusted return of the US-listed ADRs of Infosys, Wipro, HDFC Bank, ICICI Bank and Dr Reddy's vs the local close

B

Lead-lag for those names and their sectors

MAC-03

Rupee

5- and 21-day USD/INR change

B

Exporters (IT, pharma) vs importers; FPI flow pressure

MAC-04

Crude oil

5- and 21-day Brent change

B

Hurts oil marketers, paints, aviation and tyres; helps upstream

MAC-05

Global risk

S&P 500 futures, US 10-year yield and dollar-index changes

B

Emerging-market risk appetite and FPI flows

MAC-06

Domestic rates

10-year G-sec yield change, term spread, banking-system liquidity

B

Banks, NBFCs and real-estate sensitivity

MAC-07

Breadth

Share of stocks above their 50- and 200-DMA; advances minus declines; new 52-week highs minus lows

B

Market regime for a long-only book; trend-template pass rates move with it

MAC-08

Sector rotation

Rank of each sector index's 1- and 3-month return

B

Context for MOM-05 and MOM-09
### 4.9 Text and alternative data

ID

Feature

How to compute

Grade

Evidence or rationale

ALT-01

Announcement classifier

LLM labels for each NSE/BSE filing (results, order win, fund-raise, management change, litigation), keyed to the filing timestamp

B

Turns thousands of filings into event features

ALT-02

Earnings-call tone

Tone and guidance change in call transcripts vs the prior quarter

B

Call tone predicts returns abroad (Price, Doran, Peterson & Bliss 2012)

ALT-03

Attention

Google Trends and news-count spikes

B

Attention spikes bring price pressure that later reverses (Da, Engelberg & Gao 2011)

ALT-04

Sector nowcasts

Monthly auto sales, GST collections, power demand, cement dispatches, monsoon rainfall vs normal

C

Sector context, mostly for slower strategies

Indian sources: IIMA factor library · Agarwalla, Jacob & Varma 2017 · Acharya, Anshuman & Kumar 2015 · Joshipura & Joshipura 2016 · Betting against beta in India · PEAD in India 2018 · PEAD null result 2021 · Profitability factor 2023 · Nifty 50 reorganisation · F&O exclusion (ISB) · F&O introduction · Skew and rating downgrades
## 5. Do F&O signals carry information for equities?

Yes, but conditionally. Derivatives data adds the most for the roughly 200–230 F&O stocks, for bearish news, and at horizons from a day to a few weeks. Raw OI predicts little in published Indian work; option-implied measures predict well in US data but are largely untested on NSE, which makes them the main research opportunity.
### 5.1 Why it should work: four channels

Channel

Mechanism

Footprint to measure

Expected sign

Strongest evidence

Leverage

Futures and options give more exposure per rupee, so traders with private information often trade there first (Easley, O'Hara & Srinivas 1998)

Option volume, new OI, changes in implied volatility

Call buying precedes rises; put buying precedes falls

Stocks with low put-call ratios beat high-ratio stocks by over 40 bp the next day and over 1% the next week (Pan & Poteshman 2006). The ratio uses opening-buyer volume, which NSE does not publish

Short-sale constraints

When shorting the stock is costly, negative information moves into options and futures

Option-to-stock volume (O/S), rich puts, steep skew, futures discount to fair value

High O/S precedes lower returns

Lowest O/S decile beats the highest by 0.34% a week (19.3% a year), more so where shorting is costly (Johnson & So 2012). India's short-sale limits make this the channel most likely to be stronger here

Information in option prices

Option prices embed expected volatility and jump risk, and informed demand bends the smile

Call–put IV spread, put skew, monthly change in call and put IV, realised minus implied volatility

Rich calls up; steep skew down; rising call IV up; rising put IV down; high RV−IV down

Rich-call stocks beat rich-put stocks by 50 bp a week, fading over the sample (Cremers & Weinbaum 2010). Steepest-skew stocks lag by 10.9% a year for at least six months (Xing, Zhang & Zhao 2010). IV-change decile spreads are about 1% a month for up to six months (An, Ang, Bali & Cakici 2014). RV−IV predicts negatively and the call–put spread positively (Bali & Hovakimian 2009)

Positioning and hedging flows

OI measures how much leveraged exposure is open; arbitrage and dealer hedging transmit it to the cash price

OI change, basis, rollover, participant positions, dealer gamma

Depends on who holds the risk: crowding raises reversal risk, hedging demand moves the index

Weekly net buying of index puts forecasts weekly S&P 500 returns (Chordia, Kurov, Muravyev & Subrahmanyam 2021). The variance risk premium explains over 15% of quarterly market excess returns (Bollerslev, Tauchen & Zhou 2009)
### 5.2 What Indian studies show

Question

Finding

Verdict

Does raw OI move with or predict prices?

Same-day correlation of OI change and price change ran from −0.23 to +0.18 across 16 stocks, mostly insignificant (Garag & Ramesh 2011, 2002–06). Option OI was reported to carry information about future prices (Aggarwal 2010, 26 stocks, no magnitudes)

Weak. The price × OI build-up quadrants have never been tested formally

Does the put-call ratio predict Nifty?

OI-based PCR Granger-causes Nifty returns at 6–12-day frequencies (p = 0.009); volume-based PCR does not (p = 0.47) (Jena, Tiwari & Mitra 2019, 2001–13)

Mixed, but it matches a swing horizon. The sign is not reported, so test both directions

Does India VIX predict?

Correlation with Nifty of −0.83, and better realised-volatility forecasts than GARCH (Thenmozhi & Chandra 2013); evidence for return direction is weak

Strong for volatility, weak for direction

Do FIIs lead or follow?

FII flows chase past returns (Batra 2003). Flow-driven price moves partly reverse within days (Acharya, Anshuman & Kumar 2015). FII option OI leads India VIX but follows Nifty returns (Sharma, Bhatia & Roy 2023)

Mostly trend-following. No study tests NSE participant-wise OI against returns

Do F&O bans move prices?

1,246 bans in 2018–22 showed insignificant returns before, during and after the ban (Panda et al. 2025)

Weak for direction; use for volatility and tradability

Do futures lead the cash market?

Nifty futures led spot by roughly 10–25 minutes in 2005–06 5-minute data (NSE research paper). For single stocks the cash market led in 28 of 50 names (Jain & Biswal 2015)

Intraday only; no value for end-of-day swing features

Are there expiry effects?

Prices dip the day before expiry and recover after (Vipul 2005). Derivative stocks are far more volatile in the last 30 minutes of expiry days (Agarwalla & Pandey 2012). Pinning is weak and max pain absent (Singh & Sen 2010)

Model the expiry cycle; drop max pain as a directional signal

Do option-implied measures predict?

Day-before skew and put-call volume ratio predict the sign of earnings surprises (Saurav, Agarwalla & Varma 2024). Skew predicts post-downgrade returns (Shukla et al. 2026, 42 events). No NSE test of IV spread or O/S was found

Largely untested: the biggest gap and opportunity
### 5.3 Where it breaks down
- 

Coverage. Only F&O names have stock-level derivatives, so most of a 1,500–2,000 stock universe gets derivative information only through the market and sector routes in section 9.
- 

No signed volume. NSE publishes neither opening-buy nor closing-sell option volume, so Pan–Poteshman-style ratios cannot be built, and OI is net and unsigned.
- 

Who holds the OI. Index options OI is dominated by very short-dated contracts traded by proprietary desks and market makers, much of it in hedged spreads. Individuals are mostly on the losing side: about 91% lost money in FY25 and 87.7% in FY26 by SEBI's counts, which makes their positioning a contrarian candidate.
- 

Decay. The US effects shrank as they became known, and Indian effects will likely shrink as quant capital grows. Weight recent years in validation.
- 

Horizon. Most effects live between one day and one month, so refresh derivative features at least weekly.
- 

Rule changes. The November 2024 and October 2025 reforms changed who trades what, so pre- and post-reform OI is not like-for-like (section 3).

Indian sources: Garag & Ramesh 2011 · Aggarwal 2010 · Jena, Tiwari & Mitra 2019 · Thenmozhi & Chandra 2013 · Batra 2003 · Sharma, Bhatia & Roy 2023 · Panda et al. 2025 · Nifty futures lead-lag (NSE) · Jain & Biswal 2015 · Vipul 2005 · Agarwalla & Pandey 2012 · Singh & Sen 2010 · Saurav, Agarwalla & Varma 2024 · SEBI FY25 study coverage · SEBI FY26 study coverage

Global sources: Johnson & So 2012 · Cremers & Weinbaum 2010 · Xing, Zhang & Zhao 2010 · An, Ang, Bali & Cakici 2014 · Pan & Poteshman 2006 · Bali & Hovakimian 2009 · Bollerslev, Tauchen & Zhou 2009 · Chordia, Kurov, Muravyev & Subrahmanyam 2021
## 6. Futures-derived features (tag FNO)

Single-stock futures give four usable signals from the daily F&O bhavcopy: the price–OI quadrant, OI scaled to float and liquidity, the basis against fair carry, and expiry-week rollover. None has a rigorous Indian test, so treat them as grade C hypotheses built on cheap, clean data.
### 6.1 Price × OI quadrant (FUT-01)

Sum OI across all live expiries (near, next, far) in shares before computing changes, so that rolls do not look like new positions. Use 1-, 5- and 10-day changes.

Price

OI

Label

Usual reading

Hypothesis to test

Up

Up

Long build-up

New longs entering

Continuation over 5–20 days

Down

Up

Short build-up

New shorts entering

Continued weakness, with squeeze risk when shorts are crowded

Up

Down

Short covering

Shorts exiting

Weaker continuation than a long build-up

Down

Down

Long unwinding

Longs exiting

Selling pressure fades once unwinding ends

Worked example: a stock at ₹1,000 carries 10.0 million shares of futures OI. Five days later the price is ₹1,040 (+4.0%) and OI is 11.5 million (+15%), a long build-up. Had OI fallen to 9.0 million (−10%), the same +4% move would be short covering.

Feed the model the continuous inputs, not just the label: price change %, OI change %, their product, and OI change scaled by ATR%. Flag the last three to four sessions before expiry, when physical-settlement margins force mechanical unwinding, and ban days, when OI can only fall.
### 6.2 OI scaling and crowding (FUT-02, FUT-03)

ID

Feature

How to compute

Hypothesis

FUT-02

OI intensity

Futures OI / free-float shares; OI / 20-day average cash volume; OI z-score vs 60 days

Crowded leverage brings higher volatility and sharper reversals on news

FUT-03

MWPL utilisation and ban state

Combined FutEq OI / MWPL from the exchange's daily file; flags at 80% and 95%; days in ban; days since ban exit

Bans showed no reliable directional effect in 2018–22 (section 5.2); use for volatility and as a trade filter, since no new F&O positions are allowed during a ban
### 6.3 Basis and cost of carry (FUT-04, FUT-05)

The basis tells you whether futures buyers pay more or less than financing costs justify. Because Indian cash shorting is hard, a futures discount can persist and carry bearish information.

    

Here F is the futures price, S the spot price, D the calendar days to expiry and r the 91-day T-bill yield. The dividend adjustment applies only when an ex-date falls before expiry.

Worked example: S = ₹1,000, near-month F = ₹1,006 and D = 20. The basis is 0.6%, or 0.6% × 365 / 20 = 10.95% annualised. With an illustrative r of 6.0%, excess carry is +4.95 points, a sign of strong demand for leveraged longs. At F = ₹996 the annualised basis is −7.3%, a discount that arbitrage cannot close easily unless a dividend explains it.

ID

Feature

How to compute

Hypothesis

FUT-04

Excess carry

As above, ranked across F&O stocks each day

Test both signs: leverage demand (continuation) or crowding (reversal); a large negative value suggests bearish positioning

FUT-05

Change in excess carry

5-day change in FUT-04

Shifts in demand are likely more informative than the level

Use synchronous prices. Futures closed on a 30-minute VWAP and, since 3 Aug 2026, on the 3:10–3:40 pm VWAP, while F&O stocks now close at the auction price. Take the underlying price reported in the F&O bhavcopy, or VWAPs over the same window, rather than mixing the two official closes.
### 6.4 Rollover (FUT-06)

Rollover % = (next-month + far-month OI) / total OI, measured one to three sessions before expiry and compared with the average of the last three expiries. Rollover cost is the annualised basis of the next-month contract.

Worked example: two sessions before expiry, near-month OI is 4.0 million shares, next month 7.5 million and far month 0.5 million. Rollover is 8.0 / 12.0 = 66.7%, against a three-expiry average of 58%, so 8.7 points above normal. Practitioners read high rollover with a rising price as longs carried forward (grade C, IN).
### 6.5 Activity ratios (FUT-07, FUT-08)

ID

Feature

How to compute

Hypothesis

FUT-07

Futures churn

Futures volume / futures OI

High churn means day-trading rather than positional conviction

FUT-08

Derivatives share of activity

Futures volume in shares / cash volume

Johnson & So logic applied to futures: a rising share suggests information moving to the leveraged venue (grade B, untested in India)
### 6.6 Contract hygiene
- 

Exchange files report OI in shares; lot sizes change at periodic revisions, so never count contracts.
- 

Splits and bonuses adjust open contracts, so OI jumps on the ex-date and must be adjusted.
- 

New F&O entrants need about 60 sessions of history before their z-scores mean anything.
## 7. Options-derived features (tag FNO)

The option features with the best published record are changes in implied volatility, the call–put IV spread, put skew and option-to-stock volume. Put-call ratios and OI walls are the most popular in India and the least tested.
### 7.1 Build an implied-volatility surface first
- 

Compute IV for every contract each day with Black-76, using the same-expiry futures price as the forward (no dividend forecast needed) and the 91-day T-bill as r.
- 

Keep only contracts that traded that day, since bhavcopy prices for untraded contracts are not market prices. Drop premiums of a few ticks and moneyness outside 0.8–1.2.
- 

Per stock per day, interpolate a 30-day constant-maturity ATM IV from the near and next monthly expiries, plus 25-delta put and call IVs.
- 

Drop the last three sessions before expiry, when physical settlement and tiny time value distort IVs.

Stock options list only three monthly expiries, so the term structure has two or three points. Section 12 has the full recipe.
### 7.2 Feature list

ID

Feature

How to compute

Grade

Evidence or hypothesis

OPT-01

IV level and rank

30-day ATM IV; percentile vs own 252 days; IV / 21-day realised volatility

B

The level alone predicts little (Bali & Hovakimian 2009); use it for risk scaling and barrier widths

OPT-02

Change in call and put IV

21-day change in ATM call IV and in ATM put IV, kept separate

B

Rising call IV precedes higher returns and rising put IV lower; decile spreads of about 1% a month (An, Ang, Bali & Cakici 2014)

OPT-03

Call–put IV spread

OI-weighted average over strikes of call IV minus put IV at the same strike and expiry

B

Rich-call stocks beat rich-put stocks by 50 bp a week (Cremers & Weinbaum 2010). Indian puts may trade rich because synthetic shorts stand in for borrowing, so rank across stocks rather than reading the level

OPT-04

Put skew

IV of the 0.95-moneyness put minus ATM call IV

B

Steepest-skew stocks lag by 10.9% a year (Xing, Zhang & Zhao 2010); in India skew predicts the sign of earnings surprises and post-downgrade returns

OPT-05

Risk-neutral skewness

Bakshi–Kapadia–Madan moments from the full strike strip

B

More negative skewness preceded higher returns in US data (Conrad, Dittmar & Ghysels 2013), the opposite reading to OPT-04, so test both; needs a dense strip

OPT-06

Realised minus implied volatility

21-day realised volatility minus 30-day ATM IV

B

Negative relation with future returns (Bali & Hovakimian 2009)

OPT-07

IV term structure

Next-month ATM IV minus near-month ATM IV

C

An inverted structure marks a near-term event or stress

OPT-08

Option-to-stock volume (O/S)

Option volume in underlying shares (optionally delta-weighted) / cash volume, 5-day average, ranked

B

Lowest-O/S decile beat the highest by 0.34% a week (Johnson & So 2012); Indian short-sale limits argue for a stronger effect

OPT-09

Stock put-call ratio

Put OI / call OI and put volume / call volume, all strikes and near-ATM only, plus 5-day change

C

Unsigned ratios are weaker than the opening-buyer ratios used abroad; test as contrarian and as informed

OPT-10

OI walls

Strike with the largest call OI and the largest put OI; spot distance to each in ATR units; OI-weighted mean strike

C

Read as resistance and support by practitioners; any effect is likely confined to expiry week

OPT-11

Max pain

Strike that minimises the total payout to option holders

C

No max-pain effect in NSE data (Singh & Sen 2010); test once, expect to drop

OPT-12

Implied earnings move

Near-expiry ATM straddle price / spot, the day before results

B

Sets barrier widths around results; realised over implied move afterwards measures the surprise

OPT-13

Unusual activity

Out-of-the-money call or put volume vs its 20-day average and vs existing OI, near-month strikes

B

Informed option buying before takeover news is well documented abroad (Augustin, Brenner & Subrahmanyam 2019); use as an event detector

OPT-14

Delta-adjusted exposure

Futures OI plus the sum of delta × option OI, i.e., FutEq OI per stock

C

Total leveraged directional exposure; the side holding it is unknown at stock level
### 7.3 Worked examples

Feature

Inputs

Result

Put-call ratio (OPT-09)

Put OI 4.2 million shares, call OI 3.0 million

PCR = 1.40

Call–put spread (OPT-03)

₹1,000 strike, 30 days: call IV 32%, put IV 35%

−3.0 vol points; rank it against other F&O stocks

Put skew (OPT-04)

0.95-moneyness put IV 38%, ATM call IV 31%

+7.0 points, a steep skew

RV − IV (OPT-06)

21-day realised 24%, ATM IV 30%

−6.0 points

Implied move (OPT-12)

ATM straddle ₹48, spot ₹1,200

±4.0% expected by expiry; set the results-week barrier at the larger of this and k × ATR

O/S (OPT-08)

Option volume 1.8 million underlying shares, cash volume 3.0 million

O/S = 0.60
## 8. Positioning and market-regime features (tag MKT)

Market-level F&O data is the cheapest way to bring derivatives information to all 1,500–2,000 stocks: it describes the regime that a pooled model can interact with stock features. Volatility measures have strong evidence; positioning measures are Indian-specific and untested.

ID

Feature

How to compute

Grade

Evidence or hypothesis

POS-01

Participant positioning

From NSE's daily participant-wise OI file (Client, DII, FII, Pro): long / (long + short) in index futures per category; net index futures; net calls minus net puts in index options

C · IN

FII positioning follows Nifty returns (Sharma, Bhatia & Roy 2023). Hypothesis: extreme FII long share and extreme client net longs are contrarian

POS-02

FII derivative flows

Daily FII net buy value and OI change in index futures, index options, stock futures and stock options (NSE FII statistics file); 5-day sums

C · IN

Separates index hedging from stock-specific positioning

POS-03

FII and DII cash flows

Daily provisional net flows (NSE) and final FPI data (NSDL); 5- and 20-day sums / free-float market cap

B · IN

FII flows chase returns (Batra 2003) and flow-driven moves partly reverse (Acharya, Anshuman & Kumar 2015). Domestic funds have absorbed heavy FII selling in recent years, so test for decay

POS-04

India VIX

Level, 5-day change, 252-day percentile, VIX / 21-day realised Nifty volatility

A for risk, C for direction

Correlation with Nifty of −0.83 and better volatility forecasts than GARCH (Thenmozhi & Chandra 2013); use it to scale barriers and exposure

POS-05

Variance risk premium

(India VIX / 100)² minus annualised 21-day realised Nifty variance

B

Explains over 15% of quarterly US market excess returns (Bollerslev, Tauchen & Zhou 2009); untested in India

POS-06

Nifty put-call ratio

OI-based PCR across all strikes, plus nearest-expiry and next-month versions; 5-day change

B · IN

OI-PCR Granger-causes Nifty returns at 6–12-day frequencies (Jena, Tiwari & Mitra 2019); compute per expiry because weeklies dominate OI

POS-07

Build-up breadth

Share of F&O stocks in long build-up minus share in short build-up over 5 days, market-wide and per sector

C · IN

Turns FUT-01 into a sentiment gauge and feeds non-F&O stocks (section 9)

POS-08

Leverage cycle

Total stock-futures OI in ₹ / free-float market cap of F&O stocks; z-score vs 252 days

C

Peaks in leveraged OI should precede higher volatility

POS-09

Dealer gamma proxy

Sum over Nifty strikes of OI × gamma × spot² × 1%, signed by whichever participant group the daily file shows as net short options

C · IN

Dealer gamma moves underlying volatility in US data (Ni, Pearson, Poteshman & White 2021); assumption-heavy in India

POS-10

Expiry cycle

Trading days to the next weekly and monthly expiry; expiry-day and post-expiry flags

B · IN

Pre-expiry dip and post-expiry recovery (Vipul 2005); much higher volatility late on expiry days (Agarwalla & Pandey 2012)

POS-11

Nifty futures basis

Annualised near-month Nifty basis minus the T-bill rate

C

Index-level leverage demand; distorted around index dividends and rebalances

POS-12

Speculative froth

Index-option premium turnover / cash-market turnover, 20 days

C · IN

A retail-frenzy gauge for sentiment extremes

Worked examples:
- 

POS-01. FIIs hold 120,000 index-futures contracts long and 280,000 short, a long share of 120 / 400 = 30%. Compare it with the ratio's own history, not with 50%, because FII index shorts partly hedge cash holdings.
- 

POS-05. India VIX at 15 implies variance of 0.15² = 0.0225. Realised volatility of 12% is a variance of 0.0144, so the premium is 0.0081: implied volatility runs 3 points above realised.

Two cautions. Participant files count contracts, so a lot-size revision changes the numbers without any change in exposure; convert to ₹ notional with the day's lot size and index level. Expiry days since the move to Tuesday (2 Sep 2025) are not comparable with earlier Thursday expiries, and the Jane Street case shows expiry-day index prints can be engineered, so keep expiry days flagged in both features and labels.
## 9. Extending derivatives information to non-F&O stocks

Most of the universe has no derivatives, so F&O information reaches it by three routes: market regime, sector aggregates of F&O peers, and lead-lag from large F&O peers to small non-F&O peers. None of them needs stock-level option data for the target stock.

Route 1 needs the stock's own futures and options; routes 2 and 3 reach every stock, which is how a pooled model can use derivatives data across the whole universe.

Route

How to build it

Why it should work

Grade

Regime gating

Give every stock the section 8 features and let the trees interact them with stock features; alternatively train per-regime models or use the regime only for position sizing

Momentum, breakouts and reversal behave differently across volatility regimes, and option-based regimes are forward-looking

B

Sector aggregation (SEC-01)

For each industry, OI-weighted means of its F&O members' features (build-up breadth, IV change, skew, excess carry, O/S), assigned to every stock in the industry

Industry news diffuses slowly from large to small firms (Hou 2007)

B

Peer lead-lag (SEC-02)

For each non-F&O stock, its 3–5 closest F&O peers by industry and return correlation; use the peers' lagged derivative features and returns

Large stocks lead small ones (Lo & MacKinlay 1990), and news at linked firms predicts returns (Cohen & Frazzini 2008)

B

Meta-labelling

A primary cash-feature model proposes trades for all stocks; a secondary model with regime and sector-derivative features decides whether to take each trade and how big

Separates the direction call from the timing and sizing call (López de Prado 2018)

B
- 

Missing by design. Stock-level derivative features are structurally missing for non-F&O stocks. LightGBM handles NaN, but F&O membership tracks size and liquidity, so the model can learn a size effect through missingness. Add an explicit F&O flag, report results for both subsets, and test a separate F&O-only model.
- 

Point-in-time membership. Use the F&O list and the industry classification as they stood on each date.
- 

Timing. Peer and sector features may use only data published by the close of the signal day.
## 10. Master feature catalogue

The catalogue lists 99 features: 17 to test first (P1), 10 controls every model should carry, 44 for the second round and 28 for later. Formulas and evidence sit in sections 4–9; set Status as tests finish. Expected sign is the hypothesis to test, and "test" means the evidence is silent or split.
### 10.1 Price, volume and risk

ID

Feature

Tag

Data source, frequency

Expected sign

Priority

Status

MOM-01

12-1 month momentum

ALL

CM bhavcopy, daily

+

P1 test first

Not tested

MOM-02

Short-term reversal (5 and 21 days)

ALL

CM bhavcopy, daily

−

P1 test first

Not tested

MOM-03

52-week-high proximity

ALL

CM bhavcopy, daily

+

P1 test first

Not tested

MOM-04

Residual momentum

ALL

CM bhavcopy, daily

+

P2 next

Not tested

MOM-05

Relative strength vs index and sector

ALL

CM bhavcopy, index files, daily

+

P2 next

Not tested

MOM-06

Trend-template distances

ALL

CM bhavcopy, daily

+ (filter)

Control

Not tested

MOM-07

Moving-average distance in ATR units

ALL

CM bhavcopy, daily

+ trend, − when extreme

P2 next

Not tested

MOM-08

Momentum quality

ALL

CM bhavcopy, daily

+

P2 next

Not tested

MOM-09

Industry momentum

ALL

CM bhavcopy, industry map, daily

+

P2 next

Not tested

MOM-10

RSI(14), distance from 20-day high or low

ALL

CM bhavcopy, daily

− short term

P3 later

Not tested

VOL-01

Realised volatility

ALL

CM bhavcopy, daily

−

Control

Not tested

VOL-02

Idiosyncratic volatility

ALL

CM bhavcopy, daily

−

P2 next

Not tested

VOL-03

Beta

ALL

CM bhavcopy, daily

−

Control

Not tested

VOL-04

Lottery demand (MAX)

ALL

CM bhavcopy, daily

−

P1 test first

Not tested

VOL-05

Volatility contraction

ALL

CM bhavcopy, daily

+ before breakouts

P2 next

Not tested

VOL-06

Overnight vs intraday returns

ALL

CM bhavcopy, daily

test

P2 next

Not tested

VOL-07

Return skewness, downside beta

ALL

CM bhavcopy, daily

−

P3 later

Not tested

LIQ-01

Delivery % z-score

ALL · IN

Full bhavcopy, daily

+ on up-days

P1 test first

Not tested

LIQ-02

Delivery value shock

ALL · IN

Full bhavcopy, daily

+ on up-days

P2 next

Not tested

LIQ-03

Abnormal volume × return sign

ALL

CM bhavcopy, daily

+

P1 test first

Not tested

LIQ-04

Average trade size

ALL · IN

Full bhavcopy, daily

+

P2 next

Not tested

LIQ-05

Close vs day VWAP

ALL

Full bhavcopy, daily

+

P2 next

Not tested

LIQ-06

Amihud illiquidity

ALL

CM bhavcopy, daily

+ premium; capacity filter

Control

Not tested

LIQ-07

Turnover

ALL

CM bhavcopy, shareholding, daily

−

Control

Not tested

LIQ-08

Volume dry-up in a base

ALL

CM bhavcopy, daily

+ before breakouts

P3 later

Not tested

LIQ-09

Spread estimate

ALL

CM bhavcopy, daily

cost input

Control

Not tested
### 10.2 Ownership, fundamentals and events

ID

Feature

Tag

Data source, frequency

Expected sign

Priority

Status

OWN-01

FPI holding change

ALL · IN

Shareholding pattern, quarterly

+

P2 next

Not tested

OWN-02

Mutual fund holding change

ALL · IN

Fund portfolios, monthly

+ flow; − crowding

P2 next

Not tested

OWN-03

Promoter and insider buying

ALL · IN

Insider and takeover-code filings, event

+

P2 next

Not tested

OWN-04

Promoter pledge level and change

ALL · IN

Pledge disclosures, event

−

P3 later

Not tested

OWN-05

Bulk and block deals

ALL · IN

Bulk and block deal files, daily

test

P3 later

Not tested

OWN-06

Short-sale disclosures

FNO · IN

Exchange short-sale report, weekly

−

P2 next

Not tested

OWN-07

SLB borrow and fee

FNO · IN

SLB segment, daily

−

P3 later

Not tested

OWN-08

Margin-funded positions

ALL · IN

Exchange margin-trading report, daily (confirm history)

−

P3 later

Not tested

FUN-01

Standardised unexpected earnings

ALL

Results filings, quarterly

+

P1 test first

Not tested

FUN-02

Earnings announcement return

ALL

Results filings and prices, event

+

P1 test first

Not tested

FUN-03

Revenue surprise

ALL

Results filings, quarterly

+

P2 next

Not tested

FUN-04

Estimate revisions

ALL

Consensus vendor, daily

+

P3 later

Not tested

FUN-05

Value yields within sector

ALL

Financials and prices, daily

+

P2 next

Not tested

FUN-06

Quality and profitability

ALL

Financials, quarterly

+

P2 next

Not tested

FUN-07

Growth and acceleration

ALL

Results filings, quarterly

+

P3 later

Not tested

FUN-08

Results calendar

ALL

Board-meeting notices, event

control

Control

Not tested

EVT-01

Index inclusion and exclusion

ALL

Index-provider notices, event

+ before effective date for adds

P2 next

Not tested

EVT-02

AMFI cap reclassification

ALL · IN

AMFI list, twice a year

+ on upgrade

P2 next

Not tested

EVT-03

F&O inclusion or exclusion

ALL · IN

Exchange circulars, event

+ inclusion; − exclusion

P2 next

Not tested

EVT-04

IPO lock-in expiry

ALL · IN

Offer documents, event

−

P2 next

Not tested

EVT-05

Equity issuance discount

ALL

Filings, event

− short term

P3 later

Not tested

EVT-06

Splits, bonuses, buybacks

ALL

Corporate actions, event

+

P3 later

Not tested

EVT-07

Credit-rating actions

ALL · IN

Rating-agency releases, event

− on downgrade

P3 later

Not tested

EVT-08

Governance red flags

ALL · IN

Announcements, event

− (exclude)

P3 later

Not tested

EVT-09

Calendar controls

MKT

Exchange calendar

control

Control

Not tested
### 10.3 Macro, text and futures

ID

Feature

Tag

Data source, frequency

Expected sign

Priority

Status

MAC-01

GIFT Nifty overnight move

MKT

NSE IX, daily

+ for the open

P2 next

Not tested

MAC-02

US ADR overnight return

FNO (5 names)

US prices and FX, daily

+

P2 next

Not tested

MAC-03

USD/INR change

MKT

FX, daily

by sector

P2 next

Not tested

MAC-04

Brent change

MKT

Commodities, daily

by sector

P2 next

Not tested

MAC-05

Global risk appetite

MKT

Vendor, daily

+ risk-on

P3 later

Not tested

MAC-06

Domestic rates and liquidity

MKT

RBI and FBIL, daily

by sector

P3 later

Not tested

MAC-07

Market breadth

MKT

CM bhavcopy, daily

+

P2 next

Not tested

MAC-08

Sector rotation rank

MKT

Index files, daily

+

P2 next

Not tested

ALT-01

Announcement classifier

ALL

NSE and BSE filings, event

by event type

P2 next

Not tested

ALT-02

Earnings-call tone

ALL

Transcripts, quarterly

+

P3 later

Not tested

ALT-03

Attention spikes

ALL

Search trends, news counts, daily

− after the spike

P3 later

Not tested

ALT-04

Sector nowcasts

MKT

Monthly releases

by sector

P3 later

Not tested

FUT-01

Price × OI quadrant, continuous

FNO

F&O bhavcopy, daily

+ for long build-up

P1 test first

Not tested

FUT-02

OI intensity

FNO

F&O bhavcopy, daily

− (crowding)

P2 next

Not tested

FUT-03

MWPL utilisation and ban state

FNO · IN

Combined-OI and ban files, daily

volatility; filter

P2 next

Not tested

FUT-04

Excess carry

FNO

F&O bhavcopy, T-bill, daily

test both

P1 test first

Not tested

FUT-05

Change in excess carry

FNO

F&O bhavcopy, daily

test both

P2 next

Not tested

FUT-06

Rollover % and cost

FNO · IN

F&O bhavcopy, each expiry

+ with rising price

P2 next

Not tested

FUT-07

Futures churn

FNO

F&O bhavcopy, daily

test

P3 later

Not tested

FUT-08

Futures volume / cash volume

FNO

F&O and CM bhavcopy, daily

−

P2 next

Not tested
### 10.4 Options, positioning and sector links (complete, re-fetched)

| ID | Feature | Tag | Data source, frequency | Expected sign | Priority |
|---|---|---|---|---|---|
| OPT-01 | IV level and rank | FNO | Computed IV, daily | risk scaling | Control |
| OPT-02 | Change in call and put IV | FNO | Computed IV, daily | + call; − put | P1 test first |
| OPT-03 | Call–put IV spread | FNO | Computed IV, daily | + | P1 test first |
| OPT-04 | Put skew | FNO | Computed IV, daily | − | P1 test first |
| OPT-05 | Risk-neutral skewness | FNO | Computed IV, daily | test | P2 next |
| OPT-06 | Realised minus implied volatility | FNO | Computed IV, daily | − | P2 next |
| OPT-07 | IV term structure | FNO | Computed IV, daily | test | P3 later |
| OPT-08 | Option-to-stock volume | FNO | F&O and CM bhavcopy, daily | − | P1 test first |
| OPT-09 | Stock put-call ratio | FNO | F&O bhavcopy, daily | test | P3 later |
| OPT-10 | OI walls | FNO | F&O bhavcopy, daily | expiry week only | P3 later |
| OPT-11 | Max pain | FNO | F&O bhavcopy, daily | none expected | P3 later |
| OPT-12 | Implied earnings move | FNO | Computed IV, event | barrier width | P2 next |
| OPT-13 | Unusual options activity | FNO | F&O bhavcopy, daily | event detector | P2 next |
| OPT-14 | Delta-adjusted exposure | FNO | Computed IV, daily | test | P3 later |
| POS-01 | Participant positioning | MKT · IN | Participant-wise OI, daily | contrarian at extremes | P2 next |
| POS-02 | FII derivative flows | MKT · IN | FII derivatives statistics, daily | test | P2 next |
| POS-03 | FII and DII cash flows | MKT · IN | NSE provisional and NSDL, daily | + short term, then reversal | P2 next |
| POS-04 | India VIX level, change, percentile | MKT | India VIX, daily | risk scaling | P1 test first |
| POS-05 | Variance risk premium | MKT | India VIX and Nifty, daily | + | P1 test first |
| POS-06 | Nifty put-call ratio | MKT · IN | F&O bhavcopy, daily | test both | P2 next |
| POS-07 | Build-up breadth | MKT · IN | F&O bhavcopy, daily | + | P2 next |
| POS-08 | Leverage cycle | MKT | F&O bhavcopy, market cap, daily | − | P3 later |
| POS-09 | Dealer gamma proxy | MKT · IN | F&O bhavcopy, participant OI, daily | volatility | P3 later |
| POS-10 | Expiry cycle | MKT · IN | Exchange calendar | control | Control |
| POS-11 | Nifty futures basis | MKT | F&O bhavcopy, T-bill, daily | test | P3 later |
| POS-12 | Speculative froth | MKT · IN | F&O and CM turnover, daily | − at extremes | P3 later |
| SEC-01 | Sector aggregates of F&O features | ALL | Derived from FUT and OPT features, daily | sign of the source feature | P1 test first |
| SEC-02 | Peer lead-lag | ALL | Derived, daily | + | P2 next |

> Extraction note (alpha_lab): sections 11–16 of the original doc (data sources, dataset recipes incl. the IV construction formula, backtest standards, research sequence, decisions, references) were not pulled into this file — the connector read truncates at ~253K chars. Their headings are in the doc outline; fetch section-by-section if needed. All signal CLAIMS live in sections 1–10, which are complete here.
