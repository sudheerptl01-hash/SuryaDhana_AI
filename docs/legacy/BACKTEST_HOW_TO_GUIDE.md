# SuryaDhana Backtest Lab — Complete How-To Guide

## 🎯 What is Backtesting?

**Backtesting** = Testing your trading ideas on **historical data** before risking real money.

Think of it like this:
- **Without backtest**: You have an idea → Execute immediately → Hope it works
- **With backtest**: You have an idea → Test on past 6 months → See results → Execute if good

### What the Backtest Tells You

For a set of trading filters, it simulates:
1. **Which stocks would have passed** your filters on each day
2. **What would have happened** if you bought them
3. **Win rate**: What % of trades would have been profitable
4. **Average return**: How much you'd have made per trade (after 5 days)
5. **Risk metrics**: How volatile was the equity curve (Sharpe ratio, max drawdown)

---

## 🚀 Step-by-Step Tutorial

### Step 1: Navigate to Backtest Lab

Open **SuryaDhana Dashboard** in your browser:
```
http://localhost:3000
```

Click the **🧪 Backtest Lab** tab in the navigation bar.

You'll see a screen with:
- Left panel: **Filter configuration**
- Right panel: **Results visualization**

---

### Step 2: Choose Your Date Range

The date range determines how much historical data to analyze.

#### Quick Selection (Recommended)
Click one of the preset buttons:

| Button | Period | Use Case |
|--------|--------|----------|
| **1M** | 1 month | Quick test, fast results |
| **3M** | 3 months | Baseline validation |
| **6M** | 6 months | ⭐ **Recommended starting point** |
| **1Y** | 1 year | More robust test |
| **2Y** | 2 years | Multi-market cycle |
| **5Y** | 5 years | Long-term strategy |

**Pro Tip**: Start with **6M** (6 months). This typically generates 5,000-6,000 trades, which is enough for statistical significance.

#### Manual Selection
Or click the **"From"** and **"To"** date fields to select custom dates:
- **From**: Start date of your test period
- **To**: End date of your test period

---

### Step 3: Enable Filters

Filters define which stocks to buy each day.

#### Filter Categories

The filters are organized into 6 categories. Click the checkbox to enable each filter:

### 📊 Category 1: Valuation (Fundamental Analysis)

These filters find cheap or expensive stocks based on company value.

**P/E Ratio** (Price-to-Earnings)
```
What it means: How much you pay per rupee of profit
Lower P/E = Cheaper stock
Higher P/E = More expensive stock (faster growth expected)

Recommended values:
  • P/E < 25  ← Reasonable valuation
  • P/E < 20  ← Cheap stocks
  • P/E < 15  ← Very cheap stocks
  • P/E > 15  ← Exclude super-cheap

Example:
  If RELIANCE has P/E 22.5 and you set filter "P/E < 25"
  → RELIANCE PASSES the filter ✓
```

**Dividend Yield %**
```
What it means: Annual dividend / current price
Higher yield = More income from stock

Recommended values:
  • Div Yield > 1%  ← Income stocks
  • Div Yield > 2%  ← High income
  • Div Yield > 3%  ← Very high income

Best for: Income-focused investors
```

**Market Cap** (Market Capitalization)
```
What it means: Total stock market value of company
Larger cap = More liquid, less volatile

Recommended values:
  • Market Cap > 500 Cr   ← Mid-cap minimum
  • Market Cap > 1000 Cr  ← Large-cap minimum
  • Market Cap > 5000 Cr  ← Very large-cap

Best for: Reducing risk, improving liquidity
```

---

### 💪 Category 2: Quality (Business Efficiency)

These filters find well-run companies.

**ROCE** (Return on Invested Capital)
```
What it means: How efficiently the company uses investor money
Higher ROCE = Better business

Interpretation:
  • ROCE > 15%  = Good quality business ⭐
  • ROCE > 20%  = Excellent business ⭐⭐
  • ROCE > 25%  = Outstanding business ⭐⭐⭐
  • ROCE < 5%   = Poor quality business

Historical Result:
  ROCE > 15% filter alone gives +0.80% return
  (vs +0.17% with no filter)
  ← Most reliable single filter

Best for: Quality-focused investors
```

---

### 📈 Category 3: Technical Trend (Price Momentum)

These filters find stocks moving upward.

**Price > 50-day MA** (Moving Average)
```
What it means: Is price above its 50-day average?
If YES = Short-term uptrend

Usage:
  ✓ Checkbox enabled = Only uptrend stocks
  ✕ Checkbox disabled = All stocks

Interpretation:
  • Price > MA50 = In short-term uptrend
  • Price < MA50 = In short-term downtrend

Best for: Momentum traders
```

**Price > 200-day MA**
```
What it means: Is price above its 200-day average?
If YES = Long-term uptrend (stronger signal)

Usage:
  ✓ Checkbox enabled = Only long-term uptrend stocks
  ✕ Checkbox disabled = All stocks

Interpretation:
  • Price > MA200 = In long-term uptrend (bullish)
  • Price < MA200 = In long-term downtrend (bearish)

Best for: Conservative trend followers
```

**50-day MA > 200-day MA** (Golden Cross)
```
What it means: Is short-term trend stronger than long-term?
This signals trend acceleration/reversal

Usage:
  ✓ Checkbox enabled = Only accelerating uptrends
  ✕ Checkbox disabled = All stocks

Interpretation:
  • MA50 > MA200 = Bullish crossover, momentum building
  • MA50 < MA200 = Bearish crossover, momentum weakening

Best for: Swing traders
```

---

### 🔥 Category 4: Technical Momentum (Strength)

These filters measure how strong the buying/selling pressure is.

**RSI** (Relative Strength Index)
```
What it means: Is stock in oversold (panic selling) or overbought (greed buying)?
Range: 0-100

Interpretation:
  • RSI < 30  = Oversold (panic selling, possible bounce)
  • RSI 30-70 = Normal
  • RSI > 70  = Overbought (excessive buying, possible pullback)

Recommended values:
  • RSI > 30  ← Avoid panic-sold stocks
  • RSI > 40  ← Only stronger uptrends
  • RSI < 70  ← Avoid overbought (use op: "lt")

Note: RSI alone is weak; use with other filters

Best for: Contrarian traders, mean reversion
```

**ATR %** (Average True Range)
```
What it means: How volatile is the stock?
Higher ATR % = More volatile price swings
Lower ATR % = More stable price

Interpretation:
  • ATR < 2%  = Very stable stock
  • ATR < 5%  = Stable stock
  • ATR > 5%  = Volatile stock
  • ATR > 10% = Highly volatile (risky)

Recommended values:
  • ATR % < 5%  ← Stable selections
  • ATR % < 3%  ← Very stable
  • ATR % > 5%  ← If you want volatility

Note: Some traders prefer volatile stocks (better moves)

Best for: Risk management, reducing noise
```

---

### 🌊 Category 5: Volatility & Support (Relative Value)

These filters find stocks based on support/resistance levels.

**% Above 52-Week Low**
```
What it means: How far above the yearly low is the stock?
Example: 52-week low = ₹100, current price = ₹130
→ 30% above 52-week low

Interpretation:
  • > 20%  = Recovery signal (bounce from bottom)
  • > 30%  = Decent recovery (not bottom fishing)
  • > 50%  = Already recovered significantly

Recommended values:
  • > 20%  ← Catch early recovery
  • > 30%  ← Safer recovery signal
  • > 50%  ← Already in recovery

Historical Result:
  > 30% filter gives +0.25% return
  ← Second-best single filter

Best for: Contrarian traders, value investors
```

**% Within 52-Week High**
```
What it means: How far below the yearly high?
Example: 52-week high = ₹200, current price = ₹160
→ 20% within 52-week high (20% below peak)

Interpretation:
  • < 10%  = Near all-time high
  • < 25%  = Recent pullback (opportunity zone)
  • < 50%  = Significant pullback

Recommended values:
  • < 25%  ← Pullback opportunity
  • < 15%  ← Near-high (continuation)

Best for: Continuation traders, momentum chasers
```

**Distance from 200-day MA**
```
What it means: Is stock extended away from its long-term average?
Example: Price = ₹150, MA200 = ₹140
→ 7% above MA200 (not too extended)

Interpretation:
  • -10% to +10%  = Normal range
  • +10% to +20%  = Slightly extended up (overbought)
  • +20%+         = Very extended (vulnerable to pullback)
  • -10% to -20%  = Slightly extended down (oversold)
  • -20%-         = Very extended down (deep value)

Recommended values:
  • < 20%   ← Not overextended
  • < 15%   ← Tight consolidation
  • > -10%  ← Avoid deep oversold

Best for: Mean reversion traders
```

---

### 🎯 Category 6: Volume (Conviction)

**Volume > 20-day Average**
```
What it means: Is today's volume higher than usual?
Higher volume = Conviction (many traders agree)
Lower volume = Weak signal (few traders care)

Interpretation:
  ✓ Enabled = Only high-volume stocks
  ✕ Disabled = All stocks

Usage:
  Volume > Avg filter confirms breakouts
  (Price moves on high volume = real, not noise)

Best for: Confirming other signals
```

---

### Step 4: Adjust Settings (Optional)

Below the filters, adjust these parameters:

**Forward Period** (days to hold)
```
How many days after buying should we check if stock went up?

Recommended values:
  • 5 days  ← Short-term momentum
  • 10 days ← Medium-term move
  • 20 days ← Longer-term trend

This test uses: 5 days
(Check if stock is up 5 trading days after entry)
```

**Win Threshold** (%)
```
What % return do we need to count as a "win"?

Examples:
  • 0%     = Any positive return counts as win
  • 0.5%   = Must make at least 0.5% to count
  • 1%     = Must make at least 1% to count

Default: 0% (any positive return = win)
```

---

### Step 5: Run the Backtest

Click the **▶ Run Backtest** button.

**Wait 10-30 seconds** while it:
- Loads 6 months of historical data
- Computes 15+ technical indicators for each stock
- Simulates filter application on each day
- Calculates returns for each trade
- Aggregates statistics

You'll see a loading spinner. When done, results appear.

---

## 📊 Understanding Results

### KPI Cards (Top Section)

Four key metrics appear at the top:

**Win Rate %**
```
What it is: % of trades that made money

Interpretation:
  • < 45%  = Bad (skip this strategy)
  • 45-50% = OK (needs good returns per trade)
  • 50-60% = Good (institutional standard)
  • > 60%  = Excellent (rare, validate carefully)

Expected ranges for good strategies:
  • Conservative: 52-55%
  • Balanced: 50-53%
  • Aggressive: 50-52%

Why not 100%?
  Because the market is random sometimes
  Any strategy with 50% win rate is already beating chance
```

**Avg Return %**
```
What it is: Average return per trade (after 5 days)

Interpretation:
  • < 0%   = Losing strategy (STOP)
  • 0-0.5% = Marginal (after costs: break-even)
  • 0.5-1% = Good (typical professional target)
  • > 1%   = Excellent (validate for overfitting)

Example:
  100 trades × 0.5% avg return = 50% portfolio return (over 6 months)

Remember:
  Even 0.1% per trade × 250 trading days = 25% annual
```

**Max Drawdown %**
```
What it is: Worst losing streak (peak to trough)

Interpretation:
  • -5%   = Excellent (smooth equity)
  • -10%  = Good (normal strategy)
  • -20%  = High (risky but possible)
  • -30%+ = Very high (too much risk)

Example:
  -15% max drawdown means:
  If you had ₹100,000, worst point dropped to ₹85,000
  (You'd need ₹15,000 buffer)
```

**Sharpe Ratio**
```
What it is: Risk-adjusted return (return per unit of risk)

Interpretation:
  • < 0.2  = Lumpy, inconsistent
  • 0.2-0.5 = Acceptable
  • > 0.5  = Good risk-adjusted return

Why this matters:
  50% win rate with high Sharpe = consistent profits
  60% win rate with low Sharpe = inconsistent profits

Better to have:
  ✓ 52% win + 0.25 Sharpe = stable wealth growth
  ✗ 60% win + 0.05 Sharpe = erratic portfolio
```

---

### Equity Curve (Chart)

The **equity curve** shows cumulative profit over time.

**How to read it:**

```
Smooth upward line
  ✓ GOOD: Consistent profitable strategy

Zigzag (ups and downs)
  ⚠️ VOLATILE: Profits inconsistent, drawdowns painful

Trending down
  ✗ BAD: Strategy not working, filters not profitable

Flat line
  ✗ VERY BAD: No trades generated (filters too strict)
```

---

### Trade List (Bottom Table)

Shows every individual trade made.

**Columns:**

| Column | Means |
|--------|-------|
| **Date** | Entry date (when signal triggered) |
| **Ticker** | Stock symbol (e.g., RELIANCE, INFY, TCS) |
| **Entry ₹** | Stock price when you bought |
| **Exit ₹** | Stock price 5 days later (sell point) |
| **Return %** | Profit/loss percentage on trade |
| **Result** | Green = Win, Red = Loss |

**Click any row** to see:
- 30-day price chart for that stock
- Highlighted entry date
- Price action around your entry point

---

## 🎲 Pre-Built Strategies to Test

Copy these filter combinations to start testing immediately:

### Strategy A: Quality Value (Conservative)
```
Recommended settings:
  Date Range: 6M (6 months)
  Filters:
    ☑ P/E Ratio < 25
    ☑ ROCE > 15%
    ☑ Price > 200-day MA

Expected Results:
  Trades: 350-400
  Win Rate: 52-55% ⭐
  Avg Return: +0.8% to +1.5% ⭐⭐
  Sharpe: 0.15-0.25
  Max Drawdown: -8% to -15%

Best For:
  • Risk-averse investors
  • Long-term wealth building
  • Pension/retirement funds
  • Conservative traders

How to Run:
  1. Click [6M] button
  2. Check P/E < 25, ROCE > 15%, Price > MA200
  3. Click [▶ Run Backtest]
  4. Wait 15-20 seconds
```

### Strategy B: Balanced Momentum
```
Recommended settings:
  Date Range: 6M (6 months)
  Filters:
    ☑ ROCE > 15%
    ☑ Price > 50-day MA
    ☑ Volume > 20-day Avg

Expected Results:
  Trades: 1,500-2,000
  Win Rate: 51-53%
  Avg Return: +0.7% to +1.0%
  Sharpe: 0.15-0.20
  Max Drawdown: -10% to -18%

Best For:
  • Active traders
  • Momentum followers
  • Retail investors
  • Medium risk tolerance

How to Run:
  1. Click [6M] button
  2. Check ROCE > 15%, Price > MA50, Volume > Avg
  3. Click [▶ Run Backtest]
  4. Wait 20-25 seconds
```

### Strategy C: Aggressive Growth
```
Recommended settings:
  Date Range: 6M (6 months)
  Filters:
    ☑ ROCE > 20%
    ☑ Above 52W Low > 30%
    ☑ Price > 50-day MA

Expected Results:
  Trades: 500-800
  Win Rate: 50-52%
  Avg Return: +0.6% to +1.2%
  Sharpe: 0.12-0.18
  Max Drawdown: -15% to -25%

Best For:
  • High-conviction traders
  • Growth-focused investors
  • Risk-taking personalities
  • Active monitoring required

How to Run:
  1. Click [6M] button
  2. Check ROCE > 20%, 52W Low > 30%, Price > MA50
  3. Click [▶ Run Backtest]
  4. Wait 15-20 seconds
```

---

## ⚡ Troubleshooting

### "0 trades generated"
**Problem**: Filters are too strict  
**Solution**:
1. Remove the strictest filter (highest number threshold)
2. Increase P/E limit (e.g., 25 → 30)
3. Decrease ROCE requirement (e.g., 15% → 10%)
4. Re-run test

### "Win rate is 30% or lower"
**Problem**: Filters are selecting wrong stocks  
**Solution**:
1. Check filter logic (is it backwards?)
2. Try longer holding period (5 → 10 days)
3. Add quality filter (ROCE > 15%)
4. Try different time period (test on 2024 data)

### "Equity curve is very erratic"
**Problem**: Too few trades or bad filter combination  
**Solution**:
1. Extend date range (1M → 6M → 1Y)
2. Relax filters (allow more stocks)
3. Add volatility control (ATR < 5%)
4. Combine with quality filter (ROCE)

### "Results look amazing (90% win rate)"
**Problem**: Likely overfitted to this time period  
**Solution**:
1. Test on different time period (2023, 2022)
2. Add more filters (reduce trades)
3. Extend date range significantly
4. Validate on out-of-sample data

---

## 🎓 Best Practices

### ✅ DO This

```
✓ Start with 6-month date range (5,000+ trades)
✓ Use 3-5 filters (simpler = more robust)
✓ Test on multiple time periods
✓ Aim for 50-55% win rate (not 80%+)
✓ Check Sharpe > 0.3 (consistent profits)
✓ Use quality filter (ROCE) as anchor
✓ Validate return >= 0.5% per trade (after costs)
```

### ❌ DON'T Do This

```
✗ Test on 1 month (too small sample)
✗ Use 15+ filters (overfitting)
✗ Expect 80%+ win rates (unrealistic)
✗ Only test on 2025 data (look-ahead bias)
✗ Ignore transaction costs (0.05% per trade)
✗ Trust 0.01% average return (too small)
✗ Use single indicator (weak signal)
```

---

## 🚀 Next Steps After Backtesting

### If Results Look Good:

1. **Paper Trade** (simulate live trading for 2-4 weeks)
   - Same filters, but don't use real money
   - Verify strategy works in real-time (not just historical)

2. **Small Live Trade** (start with ₹1,000)
   - Monitor daily for issues
   - Check for slippage, order fills
   - Ensure no bugs in live execution

3. **Scale Up** (increase position size gradually)
   - ₹1,000 → ₹5,000 → ₹10,000 → Full size
   - Stop if win rate drops <40%

### If Results Look Bad:

1. **Debug the Filters**
   - Which filter is causing losses?
   - Test each filter individually

2. **Try Different Settings**
   - Different time period
   - Different holding period (5 → 10 days)
   - Add/remove specific filters

3. **Research Similar Strategies**
   - Look at BACKTEST_QUICK_REFERENCE.md
   - See what worked for other traders
   - Copy validated strategies first

---

## 📞 FAQ

**Q: Can I trade what the backtest says?**  
A: No. Backtest is validation only. Always paper trade first. Backtests can have look-ahead bias.

**Q: Why does same filter have different results at different times?**  
A: Markets change. A filter that worked in bull market may fail in bear market. Always validate on multiple periods.

**Q: How many filters should I use?**  
A: 3-5 is ideal. More filters = overfitting. Fewer filters = weak signal.

**Q: What if my backtest shows losses?**  
A: Remove the problematic filter. Start simple (1-2 filters). Build up complexity gradually.

**Q: Should I trust Sharpe ratio or win rate?**  
A: Both matter. 52% win + 0.25 Sharpe > 60% win + 0.05 Sharpe.

**Q: Can I backtest with live/real-time data?**  
A: No, backtest uses only historical data. For live signals, use Portfolio tab.

---

## 🎯 Summary

1. **Navigate** to Backtest Lab
2. **Select** date range (recommend 6M)
3. **Enable** filters (start with 3)
4. **Run** backtest (wait 10-30 seconds)
5. **Review** KPIs: win rate 50-55%, return +0.5-1%, Sharpe 0.2+
6. **Iterate**: adjust filters if needed
7. **Validate**: test on different time period
8. **Deploy**: paper trade → small live → scale up

**That's it!** You now have a statistically validated trading strategy.

---

**Last Updated**: May 23, 2026  
**Status**: ✅ Ready to Use  
**Questions?** Check BACKTEST_QUICK_REFERENCE.md or BACKTEST_COMPREHENSIVE_VERIFICATION.md

