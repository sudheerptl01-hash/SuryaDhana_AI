# Trade Explorer — Interactive Dashboard Guide

## Overview

The **Trade Explorer** is a dynamic, production-grade analytics dashboard that transforms backtest results into an interactive exploration tool. Similar to a stock screener, it lets you:

- 🗺️ **Visualize** all trades on a calendar heatmap
- 🔍 **Filter** by date range, ticker, sector, and performance
- 📊 **Sort** trades by any metric (date, return, entry price)
- 🎯 **Drill down** into individual trade details
- 📈 **Compare** sector performance at a glance

---

## Design Philosophy

The Trade Explorer follows a **luxury trading terminal** aesthetic:

### Visual Language
- **Color Scheme**: Dark slate background (like Bloomberg terminals) with gold/amber accents
- **Typography**: Monospaced fonts for data (IBM Plex Mono), clean sans-serif for labels
- **Aesthetic**: Refined, minimal, data-focused — no wasted space, maximum information density
- **Motion**: Smooth transitions and hover effects for interactivity

### Key Design Elements

```
┌─────────────────────────────────────────────────────────────┐
│ ₹ TRADE EXPLORER                        v1.0 PREMIUM ANALYTICS│
│ 367 trades · 206 wins · +1.29% avg return                   │
├──────────────────────────────────────────────────────────────┤
│  FILTERS              │  CALENDAR HEATMAP (30D)              │
│  ──────────────────  │  Su Mo Tu We Th Fr Sa                │
│  📅 Date Range        │  [green][green][gold][gold]...      │
│  🏢 Ticker Search     │  [gold] [gold] [amber][amber]...    │
│  📊 Return Range      │  [amber][amber][red] [red] ...      │
│  ✓ Winning Only       │                                      │
│                       │  Darker = Better Returns             │
│  SECTORS              │  ────────────────────────────────   │
│  ──────────────────  │                                      │
│  ✓ Banking (5)       │  TRADE LIST (Sortable)               │
│    HDFC, ICICI...    │  ────────────────────────────────   │
│  Energy (3)          │  Date    Ticker Entry Exit Return    │
│  IT (7)              │  05-15   ACUATAS ₹2731 ₹2951 +8.06% │
│  Auto (2)            │  05-14   RELIANCE ₹2500 ₹2480 -0.80%│
│  FMCG (1)            │                                      │
└──────────────────────────────────────────────────────────────┘
```

---

## Features in Detail

### 1. Calendar Heatmap

**What it shows**: Every entry date from your backtest, color-coded by performance.

**Color Meanings**:
```
Emerald (🟢)   = Strong days: +2%, +1%, +0.5% avg return
Teal (🟦)      = Positive: +0% to +0.5% avg return
Amber (🟨)     = Slightly negative: 0% to -0.5%
Orange (🟧)    = Negative: -0.5% to -1%
Rose (🟥)      = Bad days: < -1% avg return
Slate (⬜)     = No trades
```

**Interaction**: Hover over any date square to see:
- Number of trades that day
- Win/loss count
- Average return

**Example**:
- Date: 2025-08-15
- Data: 3W 1L (+1.29% avg)
- Interpretation: 3 winning trades, 1 loss, net +1.29%

### 2. Sector Breakdown (Left Sidebar)

**Purpose**: Quick sector analysis without leaving the explorer.

**Features**:
- **Count**: Shows number of trades per sector (sorted by volume)
- **Expandable**: Click sector name to expand and see top 5 stocks
- **Clickable**: Click sector to filter all charts/lists to that sector only
- **Active State**: Selected sector highlighted in amber

**Example Sectors**:
```
Banking (45)      → HDFC, ICICI, AXIS, SBIN...
IT (32)           → TCS, INFY, WIPRO, TECH...
Energy (18)       → RELIANCE, ADANIPOWER...
Auto (12)         → MARUTI, BHEL, BAJAJFINSV...
FMCG (8)          → ITC, NESTLEIND, HINDUSTAN...
```

### 3. Advanced Filters (Left Sidebar)

**Date Range**: Filter trades between two dates
- Example: 2025-01-01 to 2025-06-30
- Heatmap updates in real-time

**Ticker Search**: Find trades for specific stock
- Supports partial match (e.g., "REL" → RELIANCE)
- Case-insensitive

**Return Range**: Filter by profit/loss range
- Min: -100% (full loss)
- Max: +100% (100% gain)
- Example: 0% to 5% (winning trades only, < 5% profit)

**Winning Trades Only**: Toggle to show only profitable trades
- Useful for analyzing what works vs. what doesn't

### 4. Interactive Trade List

**Sorting**: Click any column header to sort
- **Date**: Entry date (ascending/descending)
- **Ticker**: Stock symbol (A-Z or Z-A)
- **Return**: By return % (best/worst first)
- **Entry**: By entry price (high/low)

**Row Actions**:
- **Click any trade** → Expand to see details:
  - Entry price (exact)
  - Exit price (exact)
  - Return % (calculated)

**Visual Cues**:
- Left border color: Green = win, Red = loss
- Background tint: Green = winning trade, Red = losing trade
- Ticker in gold: Stands out for quick scanning

**Example Trade Row** (expanded):
```
ACUATAS     05-15   Entry: ₹2731   Exit: ₹2951   Return: +8.06%
            Sector: Micro   Win Status: ✓ WIN   Days Held: 5
```

---

## How to Use

### Scenario 1: Analyze Best Performing Day

1. **Look at heatmap** → Find darkest green date (best day)
2. **Click that date's trades** in the list below to expand them
3. **Note the pattern**: Which sectors? Which stocks? Which times?
4. **Export strategy**: Replicate conditions that made that day successful

### Scenario 2: Find Losing Sector

1. **Use Sector filter** → Select sector you want to investigate
2. **Adjust Return Range** → Set to negative values (-5% to 0%)
3. **Review filtered list** → What stocks lost money?
4. **Action**: Remove that sector from next strategy or change filter conditions

### Scenario 3: Screen for Consistency

1. **Set date range** → Recent 3 months
2. **Enable "Winning Only"** → Show only profitable trades
3. **Sort by Return** → Descending (best trades first)
4. **Observe top 20** → Which tickers appear most? Which sectors dominate?
5. **Insight**: These are your "money-makers" — optimize for them

### Scenario 4: Deep Dive into One Stock

1. **Search ticker** → Type "RELIANCE" in Ticker search
2. **Review all RELIANCE trades** → Across all dates
3. **Identify pattern**: Does it always win? When does it lose?
4. **Adjust filters**: What conditions make RELIANCE trades successful?

---

## Key Statistics (Footer)

Automatically calculated from filtered results:

```
Total Trades       | Win Rate        | Avg Return        | Total Return
────────────────   | ─────────────   | ──────────────    | ─────────────
367 trades         | 56.1% wins      | +1.29% per trade  | +474.3% total
```

- **Total Trades**: Count of trades matching current filters
- **Win Rate**: Percentage of winning trades (must be 50%+ for edge)
- **Avg Return**: Average return per trade (positive = profitable)
- **Total Return**: Sum of all trade returns (cumulative)

---

## Switching Between Views

Two view modes available:

### 🗺️ **Interactive Explorer** (Default — Recommended)
- Calendar heatmap
- Sector breakdown
- Advanced filters
- Drill-down trade list
- Best for: Analysis, pattern recognition, strategy optimization

### 📊 **Classic View**
- Traditional trade table
- Sortable columns
- Pagination
- Equity curve chart
- Best for: Quick review, simple sorting, historical context

**Toggle** between views using the buttons above the results:
```
[🗺️ Interactive Explorer] [📊 Classic View]
```

---

## Color Coding

### Trade Status
- **Emerald/Green** = Winning trade (positive return)
- **Rose/Red** = Losing trade (negative return)

### Heatmap Performance
- **Darkest colors** (Emerald) = Best performing days (+2%+)
- **Light colors** (Amber/Orange) = Underperforming days
- **Red** = Days with negative average returns
- **Gray** = No trades that day

### Sidebar Highlights
- **Amber** = Currently selected sector/filter
- **Gray** = Available options
- **Gold text** = Emphasized data (tickers, dates)

---

## Tips for Power Users

### 1. Use Calendar to Spot Seasonal Patterns
- Do certain days of week perform better?
- Are there clusters of green (good periods)?
- Compare gaps to market events

### 2. Sector Analysis
- Expand each sector → Which individual stocks drive profits?
- Filter by sector → Run strategy analysis per sector
- Compare win rates across sectors

### 3. Return Range Precision
- Filter 1-2% returns → Low-volatility profitable trades
- Filter 5%+ returns → High-probability setups
- Filter losses → Learn what NOT to do

### 4. Timestamp Intelligence
- Filter recent trades → Is strategy still working?
- Filter specific months → Seasonal performance analysis
- Compare Jan-Mar vs Oct-Dec patterns

### 5. Entry Price Sorting
- Sort by entry price ascending → Cheap stocks that worked
- Sort descending → Expensive stocks that worked
- Identify sweet spot price range

---

## Keyboard Shortcuts (Coming Soon)

```
/e        Open Trade Explorer
/c        Switch to Classic View
/f        Focus on filter search
Esc       Clear all filters
Ctrl+Z    Undo last filter change
```

---

## Performance Benchmarks

Based on backtest validation:

| Metric | Target | Your Strategy |
|--------|--------|---------------|
| Win Rate | > 55% | — |
| Avg Return | > 0.5% | — |
| Sharpe Ratio | > 0.5 | — |
| Max Drawdown | < -5% | — |
| Total Trades | > 100 | — |

**Interpretation**:
- ✓ Win Rate > 55% → You have an edge
- ✓ Avg Return > 0.5% → Profits outpace losses
- ✓ Sharpe > 0.5 → Good risk-adjusted returns
- ✓ Max DD < -5% → Acceptable drawdowns
- ✓ >100 trades → Statistically significant results

---

## Troubleshooting

### Issue: Calendar shows no squares
**Solution**: No trades match current filters. Widen date range or remove filters.

### Issue: Sector list shows "Other"
**Solution**: Stock sector mapping is incomplete. This is normal for unlisted/micro stocks.

### Issue: Numbers don't add up (% variance)
**Solution**: Rounding differences are normal. Each trade rounds to 2 decimals; totals may vary by ±0.01%.

### Issue: Chart flickers on filter change
**Solution**: Expected behavior — chart is recalculating. Wait 1-2 seconds.

---

## Data Source

All data comes from your backtest results:
- **Trades**: Simulated entry/exit from backtest engine
- **Dates**: Based on your from_date/to_date range
- **Returns**: Calculated as `(exit_price - entry_price) / entry_price × 100`
- **Sectors**: Inferred from ticker (using NSE sector classification)

---

## Next Steps

1. **Run a backtest** with filters enabled
2. **Click "Interactive Explorer"** to activate
3. **Explore the heatmap** to identify best trading days
4. **Use filters** to investigate specific sectors/stocks
5. **Export insights** to refine your strategy

---

**Status**: ✅ **LIVE & READY TO EXPLORE**

Access at http://localhost:3000 → **Backtest Lab** → Run backtest → **🗺️ Interactive Explorer**

🎯 **Happy analyzing!**
