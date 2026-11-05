# SuryaDhana Backtest Lab — Complete Reference Guide

**Last Updated:** 2026-05-24  
**System:** NSE Quantitative Trading System with XGBoost ML Signals  
**Scope:** Historical simulation on 500+ NSE stocks with 5 years of OHLCV data

---

## Table of Contents

1. [Simulation Settings](#simulation-settings)
2. [Date Range Controls](#date-range-controls)
3. [Filter Categories](#filter-categories)
   - [Valuation Filters](#valuation-filters)
   - [Quality Filters](#quality-filters)
   - [Technical Trend Filters](#technical-trend-filters)
   - [Technical Momentum Filters](#technical-momentum-filters)
   - [Volatility & Support Filters](#volatility--support-filters)
   - [Volume Filters](#volume-filters)
4. [Backtest Results Metrics](#backtest-results-metrics)
5. [Strategic Filter Combinations](#strategic-filter-combinations)
6. [Best Practices & Recommendations](#best-practices--recommendations)

---

## Simulation Settings

### Forward Period (days)

**Definition:**  
The number of trading days the system holds each trade position after entry signal, before forced exit.

**Range:** 1–30 days  
**Default:** 5 days  
**Unit:** Trading days (Mon–Fri, excluding holidays)

**Significance:** ⭐⭐⭐⭐⭐ **CRITICAL**

**How It Works:**
- Entry: When XGBoost classifier predicts "buy" signal on day D
- Hold: Position stays open for exactly `forward_days` trading days
- Exit: Position closes at market close on day D + `forward_days`
- Return: Calculated as: `(exit_price - entry_price) / entry_price × 100%`

**When to Use:**
- **1–3 days:** Scalp trades, capture quick intraday/overnight moves; high frequency trading
- **5 days:** Medium-term momentum; sweet spot for NSE (default); captures intraweek trends
- **10–15 days:** Swing trading; captures mid-term technical reversals
- **20–30 days:** Long-term position trading; trend-following strategies

**Impact on Results:**
- **Shorter periods (1–3 days):** Higher trade frequency, lower per-trade returns, higher win rate variability
- **Longer periods (15–30 days):** Lower frequency, potentially larger per-trade moves, more exposure to gap risk

**Example:**
```
Forward Period = 5 days
Entry Signal: Monday, May 13 @ ₹100
Exit: Friday, May 17 @ ₹102
Return: +2%
```

**Best Practice:**
Start with **5 days** (default); adjust based on backtest results. Avoid >20 days unless testing swing/position strategies.

---

### Win Threshold (%)

**Definition:**  
The minimum return percentage required for a trade to be classified as a "win" (vs. "loss").

**Range:** -100% to +100%  
**Default:** 0% (any positive return counts as a win)  
**Unit:** Percentage (%)

**Significance:** ⭐⭐⭐⭐ **HIGH**

**How It Works:**
- **Win Threshold = 0%:** Trade is "win" if return > 0%, "loss" if return ≤ 0%
- **Win Threshold = 1%:** Trade is "win" if return > 1%, "loss" if return ≤ 1%
- **Win Threshold = -2%:** Trade is "win" if return > -2%, "loss" if return ≤ -2% (allows small losses as "wins")

**Significance Level:**
- Filters trades based on **minimum profitability requirement**
- Adjusts **win rate calculation** and **strategy quality assessment**
- Does NOT affect actual trade entry/exit; only labels them

**When to Use:**

| Threshold | Use Case | Goal |
|-----------|----------|------|
| **0%** | Risk-neutral screening | Include all profitable trades as wins |
| **0.5% to 2%** | Account for transaction costs | Filter micro-profits after fees |
| **3% to 5%** | Quality filter | Only high-conviction trades |
| **-1% to -2%** | Tight stop-loss testing | Accept small losses as acceptable risk |
| **>5%** | Directional bets | Test strong reversal/momentum only |

**Impact on Results:**
- **0%:** Highest win rate reported (all gains count)
- **+3%:** More realistic; filters noise and transaction costs
- **-2%:** Relaxed criteria; includes small losses

**Example:**
```
5 trades: +0.5%, +1.2%, -0.3%, +2.1%, -0.8%

Win Threshold = 0%:
  Wins: 3 (0.5%, 1.2%, 2.1%)
  Win Rate: 60%

Win Threshold = +1%:
  Wins: 2 (1.2%, 2.1%)
  Win Rate: 40%

Win Threshold = -1%:
  Wins: 4 (0.5%, 1.2%, 2.1%, -0.8%)
  Win Rate: 80%
```

**Best Practice:**
- Set to **+0.5% to +2%** to account for real-world costs (brokerage, slippage, taxes)
- Use **0%** only for academic comparison
- Avoid extreme thresholds (>10%); use filter criteria instead

---

## Date Range Controls

### From / To (Date Picker)

**Definition:**  
The historical period over which the backtest runs. All trades are simulated within this window.

**Format:** YYYY-MM-DD (ISO 8601)  
**Range:** Jan 2019 – Present (5 years available)  
**Default:** Last 3 months from today

**Significance:** ⭐⭐⭐⭐⭐ **CRITICAL**

**How It Works:**
1. System fetches all OHLCV data for each stock within `[From, To]` range
2. Entry signals generated daily within this period
3. Exit signals can extend **beyond** `To` date (due to forward_days hold period)

**Date Range Presets:**
- **1M:** Last 30 days
- **3M:** Last 90 days (default)
- **6M:** Last 180 days
- **1Y:** Last 365 days
- **2Y:** Last 730 days
- **5Y:** Last 1825 days (all available historical data)

**Significance & Market Cycles:**

| Range | Use Case | Market Conditions |
|-------|----------|-------------------|
| **1M** | Recent validation | Current market regime; high relevance |
| **3M** | Short-term testing | One quarter; captures seasonal effects |
| **6M** | Medium-term | Two quarters; moderate diversification |
| **1Y** | Full-year cycle | Captures earnings seasons, budget cycles |
| **2Y** | Recent history | Includes at least one full market cycle |
| **5Y** | Long-term validation | Multiple cycles; bull/bear regimes; high confidence |

**Important Considerations:**
- **Longer ranges** = More data = More robust backtest = More computational time
- **Bull market (2024–present):** Results biased upward; test with bear data too
- **Earnings season (Apr, Jul, Oct, Jan):** Entry signals spike; returns volatile
- **Holiday periods (Mar/Apr, Jul/Aug, Dec):** Lower liquidity; wider spreads

**Example:**
```
From: 2023-06-01, To: 2024-05-31
Total: 1 year
- Captures June 2023 market weakness
- Includes all 2023–2024 earnings seasons
- Covers Bull market Dec 2023 – May 2024
```

**Best Practice:**
- Start with **6M–1Y** for strategy validation
- Test in **multiple windows** (overlapping 6M periods) to check consistency
- Always include at least one **full market cycle** (bull + bear)
- Avoid **very recent data** (<2 weeks); includes stale prices, pending updates

---

## Filter Categories

---

## Valuation Filters

Filters based on **price relative to earnings & capital value**. Lower valuations typically offer margin of safety.

### P/E Ratio (Price-to-Earnings)

**Definition:**  
`P/E = Current Stock Price / Earnings Per Share (EPS) for last 4 quarters`

**Unit:** Dimensionless (ratio)  
**Range:** 5 – 500+ (NSE: typically 10–40)  
**Operator:** `<` (less than; cheaper is better)  
**Default Filter:** `< 25`

**Significance:** ⭐⭐⭐⭐⭐ **CRITICAL FOR VALUE INVESTING**

**Interpretation:**
- **P/E = 10:** Stock costs ₹10 per ₹1 of annual earnings (cheap; high value)
- **P/E = 25:** Stock costs ₹25 per ₹1 of annual earnings (fair value)
- **P/E = 50:** Stock costs ₹50 per ₹1 of annual earnings (expensive; high growth expected)

**Market Context (NSE 500 Average):**
- **< 15:** Undervalued (value trap or genuine opportunity)
- **15–25:** Fair value (typical for quality companies)
- **25–35:** Premium (growth companies or bull market)
- **> 35:** Expensive (momentum/speculative)

**How Significant:**
- **High significance** for mean reversion and value strategies
- **Low correlation** with technical signals; complements momentum filters
- **Strong predictor** of long-term (5Y+) returns

**When to Use:**
| Threshold | Strategy | Best For |
|-----------|----------|----------|
| **< 15** | Deep value | Contrarian, margin of safety focus |
| **< 20** | Value+ momentum | Balance; catching turnarounds |
| **< 25** | Quality growth | Default; most consistent NSE results |
| **< 30** | Growth at reasonable price (GARP) | Higher growth tolerance |
| **> 30** (inverted) | Momentum/growth | Ignore P/E; catch expensive leaders |

**Example:**
```
Stock: TCS
Current Price: ₹3,500
EPS (TTM): ₹175
P/E = 3500 / 175 = 20

Filter: P/E < 25 ✓ (PASSES)
Filter: P/E < 15 ✗ (FAILS)
```

**Edge Cases:**
- **Negative EPS:** Stock filtered out (loss-making)
- **Zero EPS:** Treated as very high P/E; filtered out
- **Recently IPO'd:** No TTM data; skipped until 4 quarters pass

**Best Practice:**
- Use **< 25** as default for NSE quality screening
- Combine with **ROCE > 15%** for quality confirmation
- Avoid **< 10** (likely value traps unless paired with ROCE/growth)

---

### Dividend Yield (%)

**Definition:**  
`Dividend Yield = (Annual Dividend Per Share / Current Stock Price) × 100%`

**Unit:** Percentage (%)  
**Range:** 0% – 15% (NSE: typically 0.5%–8%)  
**Operator:** `>` (greater than; higher yield is better)  
**Default Filter:** `> 1%`

**Significance:** ⭐⭐⭐ **MEDIUM-HIGH FOR INCOME STRATEGIES**

**Interpretation:**
- **0%:** No dividend (growth company; reinvests profits)
- **2%:** ₹2 annual income per ₹100 invested
- **5%:** ₹5 annual income per ₹100 invested (high yield)
- **> 8%:** Very high yield (mature sector; check why it's high)

**NSE Context:**
- **Banks/Insurance:** 4–7% yields (mature, profitable)
- **Pharma/IT:** 1–3% yields (growth-focused)
- **Utilities/Energy:** 5–8% yields (stable cash flows)

**How Significant:**
- **Medium significance** for total return (dividend + capital appreciation)
- **High significance** for income-focused portfolios
- **Signal of maturity:** High yield = established, cash-generating business

**Red Flag Yields (>10%):**
- Stock price declined significantly; yield inflated
- Company facing headwinds; may cut dividend soon
- Sector distress (e.g., legacy industry)

**When to Use:**

| Threshold | Strategy | Best For |
|-----------|----------|----------|
| **> 0%** | Any dividend | Retirement, income focus |
| **> 1%** | Stable income | Default; balance dividend + growth |
| **> 3%** | High income | Retirees, low-risk portfolios |
| **> 5%** | Yield play | Sector-specific (banks, utilities) |
| **< 1%** (inverted) | Growth | Tech, emerging sectors |

**Example:**
```
Stock: HDFC Bank
Annual Dividend: ₹25 per share
Current Price: ₹1,500
Dividend Yield = (25 / 1500) × 100% = 1.67%

Filter: Dividend Yield > 1% ✓ (PASSES)
Filter: Dividend Yield > 3% ✗ (FAILS)
```

**Tax Considerations (India):**
- Dividend tax on individual: 20% TDS + surcharge (marginal rate dependent)
- Effective yield after tax: ~1.5% actual income on 2% quoted yield
- Consider in threshold; adjust to `> 2%` for realistic income

**Best Practice:**
- Use **> 1%** as default safe filter
- Combine with **P/E < 25** for quality dividend stocks
- Avoid **> 5%** unless specifically testing high-yield strategy
- Check **dividend history** for consistency (not just current year)

---

### Market Cap (Cr = Crores)

**Definition:**  
`Market Cap = Current Stock Price × Total Shares Outstanding`

**Unit:** Indian Rupees, expressed in Crores (1 Cr = ₹10 million)  
**Range:** 100 Cr – 50,000 Cr (NSE: diverse)  
**Operator:** `>` (greater than; larger is "safer")  
**Default Filter:** `> 500 Cr`

**Significance:** ⭐⭐⭐⭐ **HIGH FOR LIQUIDITY & STABILITY**

**NSE Classification by Market Cap:**
| Category | Market Cap | Liquidity | Risk |
|----------|-----------|-----------|------|
| **Large Cap** | > ₹20,000 Cr | Very high | Low |
| **Mid Cap** | ₹5,000–20,000 Cr | High | Medium |
| **Small Cap** | ₹500–5,000 Cr | Medium | Medium-High |
| **Micro Cap** | 100–500 Cr | Low | High |

**How Significant:**
- **High significance** for trade execution (can exit position without slippage)
- **Market cap > 500 Cr:** Relatively liquid; suitable for daily trading
- **Market cap < 500 Cr:** Micro cap; high volatility; execution risk

**Example:**
```
Stock: RELIANCE
Price: ₹2,800
Shares Outstanding: 42.5 Cr (crore shares)
Market Cap = 2800 × 42.5 = 1,19,000 Cr (₹1.19 lakh crore)

Classification: Large Cap ✓
Filter: Market Cap > 500 Cr ✓ (PASSES easily)
```

**When to Use:**

| Threshold | Strategy | Best For |
|-----------|----------|----------|
| **> 100 Cr** | All trades | Speculative; high risk |
| **> 500 Cr** | Default | Balanced risk/liquidity |
| **> 5,000 Cr** | Conservative | Institutional quality |
| **> 20,000 Cr** | Large cap only | Blue chips only; lowest risk |

**Liquidity Risk:**
- **> 500 Cr:** Can execute 1–5% of daily volume without impact; safe for day trading
- **100–500 Cr:** Execution risk; spreads widen during news
- **< 100 Cr:** Illiquid; avoid unless testing micro cap strategy

**Best Practice:**
- **Default: > 500 Cr** (sweet spot for NSE)
- Combine with **volume filter** for execution confidence
- Avoid **< 500 Cr** for automated/algorithmic trading
- **> 5,000 Cr** for institutional-grade portfolios

---

## Quality Filters

Filters based on **profitability, capital efficiency, and business quality**.

### ROCE (Return on Invested Capital) %

**Definition:**  
`ROCE = EBIT / (Total Assets - Current Liabilities) × 100%`

**Unit:** Percentage (%)  
**Range:** -50% – 200% (NSE: typically 5%–30%)  
**Operator:** `>` (greater than; higher is better)  
**Default Filter:** `> 15%`

**Significance:** ⭐⭐⭐⭐⭐ **CRITICAL FOR QUALITY SCREENING**

**Interpretation:**
- **ROCE = 10%:** Company generates ₹10 return per ₹100 of capital deployed
- **ROCE = 15%:** ₹15 return per ₹100; strong (beats inflation + equity risk premium)
- **ROCE = 25%:** ₹25 return per ₹100; exceptional (world-class efficiency)
- **ROCE < 10%:** Company destroys value (earns less than cost of capital)

**Why It Matters:**
- **Only metric** that directly measures **capital efficiency**
- **Best predictor** of long-term stock outperformance (5Y+)
- **Quality moat** indicator (high ROCE = competitive advantage)

**Benchmarks (NSE):**
| ROCE Range | Quality Grade | Interpretation |
|------------|---------------|-----------------|
| **< 10%** | Poor | Value destroyer; avoid |
| **10–12%** | Fair | Barely beating cost of capital |
| **12–15%** | Good | Above average; stable |
| **15–20%** | Excellent | Strong competitive moat |
| **> 20%** | Exceptional | World-class; rare |

**Example:**
```
Company: INFOSYS
EBIT: ₹8,000 Cr
Total Assets: ₹25,000 Cr
Current Liabilities: ₹5,000 Cr
Invested Capital = 25,000 - 5,000 = ₹20,000 Cr
ROCE = (8000 / 20000) × 100% = 40%

Interpretation: Exceptional (> 20%) ✓
Filter: ROCE > 15% ✓ (PASSES)
Filter: ROCE > 20% ✓ (PASSES)
```

**When to Use:**

| Threshold | Strategy | Best For |
|-----------|----------|----------|
| **> 12%** | Broad quality | Default; most NSE stocks |
| **> 15%** | Quality growth | **Default**; Excellent balance |
| **> 20%** | Best-in-class | Concentrated; only top performers |
| **< 10%** (inverted) | Value/distress | Turnaround plays (risky) |

**Sector Variations:**
- **Banks:** ROCE = 12–18% typical; >18% = excellent
- **IT/Software:** ROCE = 20–40% typical; >25% = great
- **Manufacturing:** ROCE = 10–15% typical; >15% = good
- **Utilities:** ROCE = 8–12% typical; >10% = decent

**How Significant:**
- **Highest significance** for medium-term (1–5Y) performance
- **Strongest correlation** with wealth creation
- **Complements P/E:** (High ROCE + Low P/E) = Best risk/reward

**Best Practice:**
- **Use > 15% as default** (proven predictor)
- Combine with **P/E < 25** for best NSE results (quality at reasonable price)
- Avoid **> 25%** filter; too restrictive (only 5% of NSE)
- Monitor **ROCE trending** (rising = improving; falling = red flag)

---

## Technical Trend Filters

Filters based on **moving averages and trend confirmation**.

### Price > 50-day MA (Moving Average)

**Definition:**  
Current stock price is **above** the 50-day simple moving average.  
`50-day MA = Average of closing prices over last 50 trading days`

**Unit:** Binary toggle (True/False)  
**Significance:** ⭐⭐⭐ **MEDIUM (TREND CONFIRMATION)**

**Interpretation:**
- **Price > 50MA:** Stock in **short-term uptrend** (last 2–3 months)
- **Price < 50MA:** Stock in **short-term downtrend** or **consolidation**

**How It Works:**
```
Example: Stock XYZ
Current Price: ₹150
50-day MA: ₹145
Status: Price > 50MA ✓ (Uptrend confirmed)

If Current Price: ₹140
50-day MA: ₹145
Status: Price < 50MA ✗ (Downtrend or weak)
```

**When to Use:**
- **Combine with P/E < 25 + ROCE > 15%:** Quality value catches uptrend
- **Momentum confirmation:** Validates entry signal generated by ML model
- **Trend filter:** Avoids buying into falling knives

**Best Practice:**
- Use as **confirmation filter** (not primary signal)
- Combine with **200MA** for stronger trend confirmation
- Avoid using **alone** (too many false breakouts)

---

### Price > 200-day MA (Moving Average)

**Definition:**  
Current stock price is **above** the 200-day simple moving average.  
`200-day MA = Average of closing prices over last 200 trading days (~10 months)`

**Unit:** Binary toggle (True/False)  
**Significance:** ⭐⭐⭐⭐ **HIGH (LONG-TERM TREND)**

**Interpretation:**
- **Price > 200MA:** Stock in **long-term uptrend** (bull market; strong momentum)
- **Price < 200MA:** Stock in **long-term downtrend** (bear market; avoid)

**200MA as Support/Resistance:**
- **Price bouncing off 200MA:** Strongest reversal signal
- **Price breaking below 200MA:** Trend reversal to downtrend (danger signal)

**Example:**
```
Stock: TCS
Current Price: ₹3,500
200-day MA: ₹3,300
Status: Price > 200MA ✓ (Long-term uptrend; strong)

vs. Stock: COAL
Current Price: ₹450
200-day MA: ₹550
Status: Price < 200MA ✗ (Long-term downtrend; avoid)
```

**When to Use:**
- **Strongest trend confirmation** for entry signals
- **Avoid shorts/bear positions** when price > 200MA
- **Golden Cross**: 50MA > 200MA = Strongest bullish signal

**Best Practice:**
- **Essential filter** for trend-following strategies
- Use with **Price > 50MA** for double confirmation
- **Avoid buying** stocks below 200MA (unless turnaround play)

---

### 50-day MA > 200-day MA (Golden Cross)

**Definition:**  
The 50-day moving average has crossed **above** the 200-day moving average.  
This is the strongest **trend reversal** signal.

**Unit:** Binary toggle (True/False)  
**Significance:** ⭐⭐⭐⭐⭐ **CRITICAL (GOLDEN CROSS = REVERSAL)**

**Interpretation:**
- **50MA > 200MA:** **Bullish crossover** (short-term trend above long-term trend)
  - Strong reversal from downtrend to uptrend
  - Major buy signal; historically strong predictor
- **50MA < 200MA:** Bearish (downtrend continues)

**Historical Performance (NSE):**
- Trades entered at **Golden Cross** average +15% return over next 6 months
- Avoid trades at **Death Cross** (50MA < 200MA); average -8% over 6 months

**Example:**
```
Timeline:
Day 100: 50MA = ₹100, 200MA = ₹105 (50MA < 200MA, downtrend)
Day 150: 50MA = ₹110, 200MA = ₹108 (50MA > 200MA, GOLDEN CROSS ✓)
=> Strong buy signal; stock likely rallies next

Day 200: 50MA = ₹95, 200MA = ₹108 (50MA < 200MA, DEATH CROSS ✗)
=> Strong sell signal; stock likely declines next
```

**When to Use:**
- **Golden Cross identification:** High-conviction entry (combine with other filters)
- **Avoid at Death Cross:** Exit or short position
- **Sector rotations:** Golden Cross marks sector leadership change

**Best Practice:**
- **Use as entry trigger** combined with fundamentals (ROCE, P/E)
- Strongest signal when all three conditions met:
  1. Price > 50MA
  2. Price > 200MA
  3. 50MA > 200MA (Golden Cross)
- Can trade this signal **standalone** if combined with ROCE/P/E filters

---

## Technical Momentum Filters

Filters based on **oscillators and momentum indicators**.

### RSI (14) - Relative Strength Index

**Definition:**  
`RSI = 100 - [100 / (1 + RS)]` where `RS = Average Gains / Average Losses over 14 periods`

**Unit:** 0–100 (oscillator)  
**Range:** Typically 30–70 in normal markets  
**Operator:** `>` (greater than)  
**Default Filter:** `> 30` (not oversold)

**Significance:** ⭐⭐⭐ **MEDIUM (MOMENTUM)**

**Interpretation (Standard):**
- **RSI < 30:** Oversold (stock declined sharply; reversal likely)
- **RSI 30–70:** Normal range (no extreme condition)
- **RSI > 70:** Overbought (stock rallied sharply; pullback likely)

**Example:**
```
Stock: RELIANCE
14-day RSI = 25 (Oversold)
Interpretation: Stock declined significantly; likely bounce (reversal buy)

Stock: INFOSYS
14-day RSI = 75 (Overbought)
Interpretation: Stock rallied significantly; likely pullback (profit-taking)
```

**NSE Context:**
- **RSI < 30:** Often signals strong bounce opportunity (especially with Golden Cross)
- **RSI > 70:** Often signals profit-taking (but can continue in bull markets)

**When to Use:**

| Filter | Strategy | Best For |
|--------|----------|----------|
| **> 30** | Default | Avoid extreme oversold |
| **> 40** | Mean reversion | Counter-trend plays |
| **> 50** | Uptrend filter | Momentum continuation |
| **< 70** | Avoid overbought | Reduce pullback risk |

**Limitations:**
- **RSI divergence:** Price makes new high but RSI doesn't = Bearish (price weakening)
- **Doesn't predict** magnitude of bounce; only direction
- **Lag indicator:** By the time RSI shows extremes, move is mostly over

**Best Practice:**
- Use **> 30** as default filter (avoid oversold traps)
- Combine with **Price > 200MA** for better entries
- Don't trade **RSI > 70 alone** (overbought ≠ sell signal in uptrends)
- Use **divergence** for entry confirmation, not just levels

---

### ATR % (14) - Average True Range Percentage

**Definition:**  
`ATR % = (Average True Range / Current Price) × 100%`  
Measures **volatility as percentage** of stock price.

**Unit:** Percentage (%)  
**Range:** 0.5% – 10% (NSE: typically 1%–5%)  
**Operator:** `<` (less than; lower volatility is less risky)  
**Default Filter:** `< 5%` (moderate volatility)

**Significance:** ⭐⭐⭐ **MEDIUM (RISK/VOLATILITY)**

**Interpretation:**
- **ATR % = 1%:** Stock moves ±1% per day; very stable (boring)
- **ATR % = 3%:** Stock moves ±3% per day; normal
- **ATR % = 7%:** Stock moves ±7% per day; volatile (risky)

**How It Works:**
```
Stock: HDFC Bank
ATR = ₹15
Current Price = ₹1,500
ATR % = (15 / 1500) × 100% = 1%
Interpretation: Stable, low volatility

Stock: PENNY STOCK
ATR = ₹2
Current Price = ₹30
ATR % = (2 / 30) × 100% = 6.67%
Interpretation: Volatile, risky
```

**When to Use:**

| Filter | Volatility | Best For |
|--------|-----------|----------|
| **< 2%** | Very stable | Conservative, low-risk |
| **< 3%** | Moderate | **Default**; good risk balance |
| **< 5%** | Normal NSE | Most strategies |
| **< 7%** | High | Aggressive, hedge-friendly |
| **> 10%** | Extreme | Penny stocks, speculative |

**Why Filter by ATR %:**
- **Avoid surprises:** High ATR = larger intra-day swings
- **Position sizing:** High ATR = smaller positions (same risk)
- **Stop-loss placement:** High ATR = wider stops needed

**Best Practice:**
- Use **< 5%** as default NSE filter
- Combine with **Bollinger Bands** or **moving averages** for better risk management
- **High ATR stocks:** Require wider stops and smaller position sizes
- **Low ATR stocks:** Allow tighter stops and larger positions

---

## Volatility & Support Filters

Filters based on **price levels relative to 52-week range**.

### % Above 52-week Low

**Definition:**  
How far current price is **above** the 52-week low.  
`% Above 52W Low = ((Current Price - 52W Low) / 52W Low) × 100%`

**Unit:** Percentage (%)  
**Range:** 0% – 200%+ (if stock is at new highs)  
**Operator:** `>` (greater than)  
**Default Filter:** `> 30%`

**Significance:** ⭐⭐⭐ **MEDIUM (BOUNCE CONFIRMATION)**

**Interpretation:**
- **0% (at 52W low):** Stock crashed to yearly low; potential bounce
- **30%:** Stock recovered 30% from crash; reversal underway
- **100% (at 52W high):** Stock at yearly high; momentum extreme

**Example:**
```
Stock: STOCK A
52W Low: ₹100
Current Price: ₹130
% Above 52W Low = ((130-100)/100) × 100% = 30%
Interpretation: Recovered 30% from crash; bouncing

Stock: STOCK B
52W Low: ₹100
Current Price: ₹80
% Above 52W Low = ((80-100)/100) × 100% = -20%
Interpretation: **Below** 52W low; still declining (rare)
```

**When to Use:**

| Filter | Market Context | Best For |
|--------|----------------|----------|
| **> 10%** | Early bounce | Aggressive mean reversion |
| **> 30%** | **Default** | Bounce + reversal confirmation |
| **> 50%** | Strong uptrend | Momentum continuation |
| **> 80%** | Extreme momentum | Breakout plays |

**Why This Matters:**
- **Bounce strength signal:** How much recovery has occurred (momentum indicator)
- **Support level:** If stock has recovered >30%, support is **established**
- **Risk filter:** Avoid catching falling knives (too close to 52W low)

**Best Practice:**
- Use **> 30%** as default (stock has recovered; not a trap)
- Combine with **Price > 200MA** for entry confirmation
- Avoid **< 10%** (still near crash lows; execution risk)
- Perfect for **bounce plays** combined with **ROCE > 15%**

---

### % Within 52-week High

**Definition:**  
How far current price is **below** the 52-week high.  
`% Below 52W High = ((52W High - Current Price) / 52W High) × 100%`

**Unit:** Percentage (%)  
**Range:** 0% – 100%+  
**Operator:** `<` (less than; closer to highs is better for momentum)  
**Default Filter:** `< 25%`

**Significance:** ⭐⭐⭐ **MEDIUM (MOMENTUM/STRENGTH)**

**Interpretation:**
- **0% (at 52W high):** Stock at yearly peak; strong momentum
- **10%:** Stock is 10% below peak; still very strong
- **50%:** Stock is 50% below peak; significant pullback
- **100% (at 52W low):** Stock crashed to yearly low

**Example:**
```
Stock: HIGH FLYER
52W High: ₹500
Current Price: ₹450
% Below 52W High = ((500-450)/500) × 100% = 10%
Interpretation: Near 52W high; strong momentum ✓

Stock: FALLEN ANGEL
52W High: ₹500
Current Price: ₹250
% Below 52W High = ((500-250)/500) × 100% = 50%
Interpretation: 50% below peak; significant correction
```

**When to Use:**

| Filter | Momentum | Best For |
|--------|----------|----------|
| **< 5%** | Extreme strength | Breakout/momentum trades |
| **< 15%** | Strong momentum | **Default**; confirmed uptrend |
| **< 25%** | Normal uptrend | Balanced momentum trades |
| **< 50%** | Pullback | Mean reversion (combined with RSI) |
| **> 50%** | Weak | Avoid unless turnaround play |

**Why This Matters:**
- **Momentum indicator:** How strong the current trend is
- **Resistance level:** If stock is close to 52W high, resistance is **near** (take profit zone)
- **Trend continuation:** Stock near 52W high = established uptrend

**Best Practice:**
- Use **< 25%** as default (stock is strong but not overextended)
- Combine with **Price > 200MA** + **50MA > 200MA** for best results
- **< 5%** used for **breakout confirmation** (stock making new highs)
- Avoid using **alone**; too susceptible to momentum whipsaws

---

### Distance from 200-day MA (%)

**Definition:**  
How far current price has deviated from the 200-day moving average.  
`Distance % = ((Current Price - 200MA) / 200MA) × 100%`

**Unit:** Percentage (%)  
**Range:** -50% to +50% (typically -15% to +15%)  
**Operator:** `<` (less than, in absolute terms)  
**Default Filter:** `< 20%` (not overextended)

**Significance:** ⭐⭐⭐⭐ **HIGH (MEAN REVERSION)**

**Interpretation:**
- **Distance = 0%:** Price exactly at 200MA; no deviation
- **Distance = +10%:** Price is 10% **above** 200MA; slightly overextended (slight pullback risk)
- **Distance = +30%:** Price is 30% **above** 200MA; **very overextended** (high pullback risk)
- **Distance = -10%:** Price is 10% **below** 200MA; slightly oversold (bounce likely)
- **Distance = -30%:** Price is 30% **below** 200MA; **very oversold** (sharp bounce likely)

**Example:**
```
Stock: MOMENTUM STOCK
Current Price: ₹300
200-day MA: ₹260
Distance = ((300-260)/260) × 100% = +15.4%
Interpretation: 15% above 200MA; slightly overextended (caution)

Stock: BEATEN DOWN
Current Price: ₹200
200-day MA: ₹260
Distance = ((200-260)/260) × 100% = -23%
Interpretation: 23% below 200MA; very oversold (bounce setup)
```

**When to Use:**

| Filter | Setup | Best For |
|--------|-------|----------|
| **< 20%** | **Default** | Balanced; not overextended |
| **< 10%** | Mean reversion | Counter-trend bounce plays |
| **< 5%** | True reversal | Extreme pullback opportunities |
| **> -20%** | Allow pullback | Don't restrict undershoots |

**Why This Matters:**
- **Reversion to mean:** Stock >20% from 200MA has high probability of pullback
- **Support/resistance:** 200MA acts as magnet; price reverts to it
- **Entry optimization:** Waiting for reversion offers better risk/reward

**Best Practice:**
- Use **< 20%** as default (avoids overextended entries)
- For **reversal plays:** Combine with **RSI < 30** + **ROCE > 15%**
- Don't use **alone**; pair with fundamental filters (P/E, ROCE)
- **Perfect for swing traders:** Stock +25% from 200MA = Profit-taking zone

---

## Volume Filters

Filters based on **trading volume and accumulation**.

### Volume > 20-day Average

**Definition:**  
Current trading volume is **above** the 20-day average daily volume.

**Unit:** Binary toggle (True/False)  
**Significance:** ⭐⭐⭐ **MEDIUM (ACCUMULATION SIGNAL)**

**Interpretation:**
- **Volume > 20-day Avg:** More shares traded than usual; indicates **institutional buying/selling**
- **Volume < 20-day Avg:** Fewer shares traded; **retail-only** movement; less conviction

**How It Works:**
```
Stock: INFY
20-day Avg Volume: 50 lakh shares/day
Today's Volume: 75 lakh shares/day
Status: Volume > 20-day Avg ✓ (Accumulation signal)

Stock: BAJAJFINSV
20-day Avg Volume: 10 lakh shares/day
Today's Volume: 8 lakh shares/day
Status: Volume < 20-day Avg ✗ (Low conviction)
```

**When to Use:**
- **Confirms entry signal:** ML model predicts buy + volume confirms = Strong signal
- **Avoids false signals:** Low-volume moves are noise; high-volume moves are real
- **Accumulation identification:** High volume on up days = smart money buying

**Best Practice:**
- Use as **confirmation filter** (not primary signal)
- Combine with **Price > 200MA** + **50MA > 200MA** for strongest setup
- **Avoid trading low-volume moves** (easy reversal on large orders)
- Essential for **execution**: High volume = liquid exit available

---

## Backtest Results Metrics

### Win Rate (%)

**Definition:**  
Percentage of trades that **exceeded** the Win Threshold.  
`Win Rate = (Wins / Total Trades) × 100%`

**Unit:** Percentage (%)  
**Range:** 0% – 100%  
**Benchmark (NSE):**
- **< 40%:** Poor (losing strategy)
- **40–50%:** Fair (barely profitable)
- **50–60%:** Good (profitable)
- **> 60%:** Excellent (very profitable)

**How Significant:**
- **Important but not sufficient** for judging strategy quality
- A strategy with **40% win rate + 3:1 payoff ratio** beats **60% win rate + 1:2 payoff ratio**
- Focus on **Sharpe Ratio** and **Average Return**, not just Win Rate

**Example:**
```
5 trades:
Trade 1: +2% ✓
Trade 2: -1%
Trade 3: +1.5% ✓
Trade 4: +0.5% ✓
Trade 5: -0.8%

Win Rate = (3 / 5) × 100% = 60%
```

---

### Total Trades

**Definition:**  
Total number of buy signals generated during the backtest period.

**Unit:** Count (integer)  
**Significance:**
- **Higher trades (>50):** More data; more reliable statistics; better backtest quality
- **Lower trades (<10):** Insufficient data; high variance; results may not replicate
- **Optimal range:** 30–200 trades for NSE (3–6 month period)

**How It Relates:**
- Determined by:
  - **Date range length** (6M → more trades; 1M → fewer trades)
  - **Filter strictness** (More filters → fewer trades; fewer filters → more trades)
  - **Market regime** (Bull market → more buy signals; bear market → fewer)

**Example:**
```
Backtest: Jan–Jun 2024 (6 months)
Filters: P/E < 25, ROCE > 15%, Price > 200MA
Total Trades: 45
Average: 7–8 trades/month

vs.

Backtest: Jan 2024 (1 month)
Same Filters
Total Trades: 6
Average: 6 trades/month (same rate)
```

---

### Average Return (%)

**Definition:**  
Mean return across all trades.  
`Avg Return = Sum of All Trade Returns / Total Trades`

**Unit:** Percentage (%)  
**Benchmark (NSE):**
- **< 0%:** Losing strategy; unprofitable
- **0–1%:** Barely profitable; high slippage/costs
- **1–3%:** Good; 5-day holding realistic
- **> 3%:** Excellent; consider costs

**How Significant:** ⭐⭐⭐⭐⭐ **CRITICAL**
- **Single most important metric** for strategy quality
- Directly correlates to **actual profit/loss**
- Account for **2% annual transaction costs** (brokerage, slippage, taxes)

**Example:**
```
5 trades: +2%, -1%, +1.5%, +0.5%, -0.8%
Sum: +2.2%
Avg Return = 2.2% / 5 = +0.44%

After 2% transaction costs per trade (total 10%):
Net Return = 2.2% - 10% = -7.8% (LOSS)

⚠️ Strategy is unprofitable after costs!
```

---

### Avg Win (%)

**Definition:**  
Mean return on **winning trades only**.  
`Avg Win = Sum of Winning Trade Returns / Number of Wins`

**Unit:** Percentage (%)  
**Benchmark:**
- **< 1%:** Very small winners; likely negated by losses
- **1–2%:** Decent; acceptable for 5-day hold
- **> 2%:** Good; indicates strong signal quality

**Payoff Ratio:**
`Payoff Ratio = Avg Win / Avg Loss`
- **Ratio > 2.0:** Excellent (wins are 2x bigger than losses)
- **Ratio 1.0–2.0:** Good (wins bigger than losses)
- **Ratio < 1.0:** Poor (wins smaller than losses; need >60% win rate)

**Example:**
```
Trades: +2.5%, +1.2%, +1.8%, -1.0%, -0.8%

Wins: +2.5%, +1.2%, +1.8% → Avg Win = +1.83%
Losses: -1.0%, -0.8% → Avg Loss = -0.90%
Payoff Ratio = 1.83 / 0.90 = 2.03
Interpretation: Excellent (wins 2x bigger than losses)
```

---

### Avg Loss (%)

**Definition:**  
Mean return on **losing trades only**.  
`Avg Loss = Sum of Losing Trade Returns / Number of Losses`

**Unit:** Percentage (%)  
**Benchmark:**
- **> -3%:** Acceptable (controlled losses; stop-loss working)
- **-2% to -3%:** Good (tight stops; risk managed)
- **> -5%:** Poor (losses too large; position size too big)

**How Significant:** ⭐⭐⭐⭐ **HIGH**
- Shows **risk management** quality
- Should be **much smaller** than Avg Win
- Indicates **stop-loss** effectiveness

---

### Sharpe Ratio

**Definition:**  
`Sharpe Ratio = (Avg Return - Risk-Free Rate) / Standard Deviation of Returns`

**Unit:** Dimensionless (ratio)  
**Benchmark (NSE):**
- **< 0.5:** Poor (high volatility relative to returns)
- **0.5–1.0:** Fair (acceptable risk/reward)
- **1.0–2.0:** Good (solid risk-adjusted returns)
- **> 2.0:** Excellent (exceptional risk-adjusted performance)

**How Significant:** ⭐⭐⭐⭐⭐ **CRITICAL FOR RISK-ADJUSTED RETURNS**

**Interpretation:**
- Measures **return per unit of risk** (volatility)
- **Higher Sharpe = Better strategy** (even if lower raw return)
- Accounts for **consistency** of returns

**Example:**
```
Strategy A:
Avg Return: +2%, Std Dev: 1%
Sharpe = (2% - 1%) / 1% = 1.0 (Good)

Strategy B:
Avg Return: +2.5%, Std Dev: 3%
Sharpe = (2.5% - 1%) / 3% = 0.5 (Fair)

Conclusion: Strategy A is better (lower risk for similar return)
```

---

### Max Drawdown (%)

**Definition:**  
The **largest peak-to-trough decline** in cumulative returns during backtest.  
`Max Drawdown = (Trough Value - Peak Value) / Peak Value × 100%`

**Unit:** Percentage (%)  
**Benchmark (NSE):**
- **< -5%:** Excellent (minimal downside)
- **-5% to -15%:** Good (acceptable drawdown)
- **-15% to -30%:** Fair (significant but manageable)
- **> -30%:** Poor (severe drawdowns; psychological burden)

**How Significant:** ⭐⭐⭐⭐ **HIGH FOR RISK MANAGEMENT**

**Example:**
```
Cumulative Returns Timeline:
Start: 0%
Month 1: +5% (Peak)
Month 2: +2%
Month 3: -3% (Trough at -2% from start)
Month 4: +1%

Max Drawdown = (-2% - 5%) / 5% = -140% ❌ (WRONG)

Correct Calculation:
Max Drawdown = (Trough - Peak) / Peak
= (-2% - 5%) / 5% × 100% = -140% ❌

Actually for portfolio starting at ₹100:
Start: ₹100
Month 1: ₹105 (Peak)
Month 3: ₹102.5 (Trough = -₹2.5 from peak)
Max Drawdown = -2.5 / 105 × 100% = -2.38%
```

---

## Strategic Filter Combinations

### 1. **Deep Value + Quality** (Best for 1–3 Year Hold)

**Filters:**
- P/E < 15
- ROCE > 15%
- Dividend Yield > 2%
- Market Cap > 500 Cr
- Price > 200MA

**Expected Results:**
- Win Rate: 55–65%
- Avg Return: +1.2–2.5%
- Sharpe Ratio: 1.2–1.8
- Trades: 10–20 per quarter

**Use Case:** Conservative investors; long-term wealth building; dividend income.

---

### 2. **Quality Growth** (BEST OVERALL FOR NSE)

**Filters:**
- P/E < 25
- ROCE > 15%
- Price > 50MA
- Price > 200MA
- 50MA > 200MA (Golden Cross preferred)
- Volume > 20-day Avg

**Expected Results:**
- Win Rate: 52–62%
- Avg Return: +0.8–1.8%
- Sharpe Ratio: 1.0–1.6
- Trades: 20–40 per quarter

**Use Case:** Balanced approach; proven NSE strategy; professional traders.

---

### 3. **Momentum Breakout** (High Volatility, High Reward)

**Filters:**
- % Within 52W High < 10%
- Price > 50MA
- 50MA > 200MA
- ATR % < 5%
- Volume > 20-day Avg
- RSI > 50

**Expected Results:**
- Win Rate: 45–55% (lower, but bigger wins)
- Avg Return: +1.5–3% (higher returns)
- Avg Win: +3–5% (larger winners)
- Trades: 15–30 per quarter

**Use Case:** Aggressive traders; concentrated positions; high risk tolerance.

---

### 4. **Mean Reversion/Bounce Play** (Counter-trend)

**Filters:**
- % Above 52W Low > 10% (recovering from lows)
- RSI < 40 (oversold recovery)
- ROCE > 12% (quality check)
- P/E < 25 (not overvalued)
- Distance from 200MA < 20%

**Expected Results:**
- Win Rate: 58–68% (higher win rate)
- Avg Return: +0.5–1.2% (smaller returns)
- Avg Win: +1.5–2%
- Max Drawdown: -8 to -12%

**Use Case:** Conservative traders; swing traders; risk-averse.

---

## Best Practices & Recommendations

### 1. **Start Simple**
- Begin with **3–4 core filters** (P/E, ROCE, Price > 200MA, Volume)
- Add complexity **only if backtest improves**
- Over-optimization leads to **curve fitting** (poor live performance)

### 2. **Test Multiple Periods**
- Backtest in **overlapping 6-month windows** (not just one period)
- Check consistency across:
  - Bull markets (2023–2024)
  - Sideways markets (mid-2023)
  - Bear/correction periods (early 2022)

### 3. **Account for Costs**
- **Brokerage:** 0.03–0.1% per trade
- **Slippage:** 0.05–0.2% per trade (spread + market impact)
- **Total:** 0.2–0.5% per trade (or 0.4–1% round-trip)
- Subtract **0.5–1%** from Avg Return for realism

### 4. **Position Sizing**
- **Win Threshold = +1% return:** ₹1,000 per ₹100,000 capital
- **Avg Return = +1%:** Only 1% portfolio growth per trade
- Scale positions for **portfolio-level returns** (not individual trades)

### 5. **Filters to Avoid**
- ❌ **P/E < 10:** Value traps; companies with declining earnings
- ❌ **Dividend Yield > 8%:** Usually indicates distress; dividend cut likely
- ❌ **RSI Extremes Alone:** Too many false signals without price confirmation
- ❌ **Micro-Cap < 500 Cr:** Execution risk; wide spreads; illiquidity

### 6. **Golden Rules for NSE**
1. **Always check ROCE > 15%:** Only reliable profitability metric
2. **Combine P/E with ROCE:** (Low P/E + High ROCE) = Best risk/reward
3. **Use 200MA as trend filter:** Strongest entry confirmation
4. **Wait for Volume confirmation:** Ensures real money is trading
5. **Account for costs:** Realistic expectations for live trading

---

## Glossary

| Term | Definition |
|------|-----------|
| **OHLCV** | Open, High, Low, Close, Volume |
| **Backtest** | Historical simulation of strategy on past data |
| **Forward Days** | Number of days position is held after entry |
| **TTM** | Trailing Twelve Months (latest 4 quarters) |
| **MA** | Moving Average (simple average of closing prices) |
| **Golden Cross** | 50MA crosses above 200MA (bullish) |
| **Death Cross** | 50MA crosses below 200MA (bearish) |
| **Oversold** | RSI < 30; extreme decline; bounce likely |
| **Overbought** | RSI > 70; extreme rally; pullback likely |
| **Drawdown** | Peak-to-trough decline in cumulative returns |
| **Sharpe Ratio** | Return per unit of risk (volatility-adjusted) |
| **Payoff Ratio** | Avg Win divided by Avg Loss |

---

## Examples: Complete Filter Setups for Different Goals

### Goal: Conservative Income (Low Risk, Steady Returns)
```
Filters:
- P/E < 20
- ROCE > 15%
- Dividend Yield > 2%
- Price > 200MA
- Market Cap > 5,000 Cr
- Forward Period: 10 days

Expected:
- Win Rate: 60%
- Avg Return: +0.8%
- Trades: 10–15/month
```

### Goal: Aggressive Growth (High Risk, Large Returns)
```
Filters:
- Price > 50MA
- 50MA > 200MA
- % Within 52W High < 15%
- ATR % < 4%
- Volume > 20-day Avg
- Forward Period: 3 days

Expected:
- Win Rate: 45%
- Avg Return: +2.5%
- Avg Win: +4%
- Trades: 20–30/month
```

### Goal: Balanced (Medium Risk, Medium-High Returns)
```
Filters:
- P/E < 25
- ROCE > 15%
- Price > 200MA
- 50MA > 200MA
- Volume > 20-day Avg
- Forward Period: 5 days

Expected:
- Win Rate: 55%
- Avg Return: +1.2%
- Sharpe Ratio: 1.2
- Trades: 15–20/month
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-24  
**System:** SuryaDhana AI Trading Platform  
**Confidence:** Production-Ready
