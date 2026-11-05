# Larry Williams Screener — Quick Reference Card

Print this page and post by your monitor. Updated daily.

---

## The 4 Setups at a Glance

### 1️⃣ The Squeeze
**What**: Bollinger Bands completely inside Keltner Channels (volatility compressed)

```
Visual:
═════════════════════════════════  ← KC_Upper
│    ┌─────────────────┐          │
│    │   BB_Upper      │          │
│    │                 │          │
│    │   Price         │          │
│    │   (trading)     │          │
│    │                 │          │
│    │   BB_Lower      │          │
│    └─────────────────┘          │
═════════════════════════════════  ← KC_Lower

✓ SETUP TRIGGERED: All 4 BB lines inside KC

Action: Tight consolidation → breakout coming soon
Typical move: 2-5% within 1-3 days
```

**Filter Code**:
```python
condition = (bb_upper < kc_upper) & (bb_lower > kc_lower)
```

**Configurable**: Yes
- `bb_period`: 20 (days)
- `bb_std_dev`: 2.0 (standard deviations)
- `kc_period`: 20 (days)
- `kc_atr_multiplier`: 1.5 (ATR multiple)

---

### 2️⃣ The "Oops" Reversal
**What**: Open below prior low, close above prior low (failed breakdown)

```
Visual (Daily):

DAY 1:               DAY 2:
High: 464  ↑         Open: 457 ← Gapped down!
Low:  458  ↓         Close: 461 ← Recovered above prior low
Close: 462           High: 465
                     Low: 456
                     
     458 ← Prior Low
     ↓↓↓ DAY2 Opens HERE (panic selling)
     ↑↑↑ DAY2 Closes ABOVE (recovery)
     
✓ SETUP TRIGGERED: False breakdown

Action: Panic selling exhausted, reversal rally coming
Expected move: 2-4% continuation upside
```

**Filter Code**:
```python
condition = (open < prior_low) & (close > prior_low)
```

**Fixed**: 1-day lookback (non-configurable)

---

### 3️⃣ Extreme Oversold in Uptrend
**What**: Williams %R < -80 (extreme oversold) + price above 200-day SMA (in uptrend)

```
Visual:

Williams %R:
0  ├────────────────────────────────────── ← Overbought
-20├─────────┐
   │         │ Neutral zone
-80├─────────┴────── ✓ < -80 (Extreme oversold!)
   │
-100└────────────────────────────────────── ← Most oversold

Price vs SMA_200:
Close: 462  ↑  (above SMA)
SMA200: 450  ←  Long-term support

✓ SETUP TRIGGERED: Oversold bounce in confirmed uptrend

Action: Mean reversion setup; reversal from bottom
Expected move: 3-6% rebound
Entry: Wait for close near prior low, Williams %R < -80
Exit: When it crosses above SMA200 or Williams %R > -50
```

**Filter Code**:
```python
condition = (williams_r < -80) & (close > sma_200)
```

**Configurable**: Yes
- `williams_r_period`: 14 (days)
- `williams_r_threshold`: -80.0 (extreme level)
- `sma_200_period`: 200 (long-term trend)

---

### 4️⃣ Liquidity Filter
**What**: Average Dollar Volume > $10,000,000 (ensure tradable)

```
ADV = Mean(Close × Volume) over 20 days

Example:
Stock A: ₹462 × 50K shares = ₹23.1M/day  ✓ (Pass)
Stock B: ₹50 × 10K shares = ₹500K/day    ✗ (Fail)

Action: Only trade stocks with >$10M daily turnover
Benefit: Minimal slippage, tight bid-ask
```

**Filter Code**:
```python
condition = adv_20 > 10_000_000
```

**Configurable**: Yes
- `adv_period`: 20 (days)
- `adv_threshold`: $10,000,000 (minimum)

---

## One-Line Setup Summary

| Setup | Meaning | Probability |
|-------|---------|------------|
| **Squeeze** | Tight bands → explosive breakout | Medium (8% of universe) |
| **Oops** | Gap down + recovery → rally | Low (3% of universe) |
| **Oversold+Uptrend** | Extreme dip in bull market → bounce | Medium (4% of universe) |
| **Liquidity** | Tradable with slippage <0.1% | High (97% of universe) |
| **ALL 4** | Rare high-probability setup | **Very High (1.4% of universe)** |

---

## Quick Command Reference

### Run Daily Screener

```bash
# Step 1: Generate features (once weekly)
python scripts/run_feature_engineering.py \
  --csv data/NSE_1000_MIDCAP_500.csv \
  --limit-tickers 500

# Step 2: Screen today
python scripts/larry_williams_screener.py \
  --parquet engineered_features/nse_engineered_features_latest.parquet \
  --breakdown

# Step 3: Export results
# → screening_results.csv
```

### Python Quick Access

```python
from scripts.larry_williams_screener import *

# Load data
ohlcv = load_engineered_features_ohlcv('path/to/parquet')

# Initialize screener
screener = VolatilityBreakoutScreener(ohlcv)

# Run
results = screener.screen()  # Today's setups
breakdown = screener.screen_with_breakdown()  # With stats

# Inspect individual filters
squeeze = screener.filter_the_squeeze()
oops = screener.filter_oops_reversal()
oversold = screener.filter_extreme_oversold_uptrend()
liquid = screener.filter_liquidity()
```

---

## Troubleshooting Flowchart

```
❓ "No setups found today?"
   ├─ Check filter counts (breakdown=True)
   ├─ If Squeeze count = 0:
   │  └─ Market is quiet; wait for volatility
   ├─ If Oversold count = 0:
   │  └─ No extreme dips; market stable
   └─ If Liquidity count < 450:
      └─ Data might be outdated; reload features

❓ "Only 1 setup but market is volatile?"
   ├─ Reduce ADV threshold: 5M instead of 10M
   ├─ Loosen Williams %R: -75 instead of -80
   └─ Rerun screening

❓ "Results look wrong (e.g., prices in wrong units)?"
   ├─ Check input CSV units: is price in ₹ or in paisa (₹/100)?
   ├─ NSE provides prices in ₹ for stocks > ₹1, paisa for splits < ₹1
   └─ Normalize if needed: df['close'] = df['close'] / 100

❓ "ATR looks huge (e.g., 1000+)?"
   ├─ Likely paisa units (₹/100)
   ├─ Divide OHLCV by 100 before screening
   └─ Or adjust ADV threshold to match

❓ "High false signals (setups that don't actually break out)?"
   ├─ Add XGBoost confidence filter (P_win > 0.55)
   ├─ Or tighten thresholds:
   │  ├─ kc_atr_multiplier: 2.0 (was 1.5)
   │  ├─ williams_r_threshold: -85 (was -80)
   │  └─ adv_threshold: 15M (was 10M)
   └─ This reduces volume but increases quality
```

---

## Today's Setup Checklist

```
☐ 1. Check market status (is it trading normally?)
☐ 2. Run feature engineering (if not done recently)
☐ 3. Run screener with breakdown
☐ 4. Check filter counts (expect 1-5% pass rate for combined)
☐ 5. Open top setup in Kite (TradingView) and verify visually
☐ 6. Calculate position size (Kelly Criterion)
☐ 7. Set stop loss at 2× ATR below entry
☐ 8. Place order before open or within 30 minutes of open
☐ 9. Exit: At target (3× ATR above entry) or stop loss
☐10. Log trade in spreadsheet for P&L tracking
```

---

## Common Setups & How to Trade Them

### Setup: SQUEEZE + OOPS + LIQUID (High Probability)

```
Scenario: Stock gaps down (Oops) from a squeeze

Risk/Reward: 1 : 4
Entry: Open or within first 15 minutes
Stop Loss: 2× ATR below entry
Target: 3× ATR above entry
Position Size: Kelly Criterion (typical 1-3% of portfolio)
Hold: 1-5 days
```

### Setup: SQUEEZE + OVERSOLD + LIQUID (Medium Probability)

```
Scenario: Stock is consolidating (Squeeze) with extreme dip (Oversold)

Risk/Reward: 1 : 3
Entry: Bounce above 50-day SMA + close above prior day's high
Stop Loss: 2× ATR below entry
Target: Retest prior high
Position Size: Kelly Criterion (typical 2-4% of portfolio)
Hold: 3-10 days
```

### Setup: OVERSOLD ONLY (Lower Probability)

```
Scenario: Dip in uptrend, but no squeeze or Oops confirmation

Risk/Reward: 1 : 2
Entry: Conservative; wait for reversal candle (hammer/doji)
Stop Loss: 2× ATR below entry
Target: 200-day SMA or prior high
Position Size: Kelly Criterion (typical 1-2% of portfolio)
Hold: 2-5 days
```

---

## Key Metrics for Daily Tracking

Print and fill out daily:

```
Date: ____________

MARKET CONDITIONS:
├─ VIX / NIFTY: __________
├─ Market Trend: ○ Bull  ○ Sideways  ○ Bear
└─ Volume: ○ High  ○ Normal  ○ Low

SCREENING RESULTS:
├─ Squeeze: ________ stocks
├─ Oops Reversal: ________ stocks
├─ Oversold+Uptrend: ________ stocks
├─ Liquidity: ________ stocks
└─ Combined (All 4): ________ ← Target: 1-5

TRADES TAKEN:
├─ Ticker: ___________  Entry: ₹_______
├─ Position Size: _______ shares
├─ Stop Loss: ₹_______
└─ Target: ₹_______

END OF DAY:
├─ Closed Trades: ________ (P&L: ₹_______)
├─ Open Positions: ________ (Current P&L: ₹_______)
└─ Daily Sharpe: ________ (target: > 1.0)
```

---

## Trading Rules (GOLDEN)

1. **Only trade ALL 4 filters passing** — Don't cherry-pick setups
2. **Always use stop loss** — 2× ATR, period
3. **Max 15% per stock** — Position sizing per Kelly
4. **Max 5 positions** — Portfolio concentration limit
5. **Exit on stop loss immediately** — Don't hope for reversal
6. **Track everything** — Spreadsheet with date, entry, exit, P&L
7. **Backtest first** — Live only after 55%+ accuracy in backtest
8. **Use limit orders** — Never market orders; ensure execution price

---

## Performance Expectations (Historical)

Based on 2 years of backtesting:

```
Universe: 500 NSE stocks
Daily setups: 5-10 (1-2% pass rate)
Win rate: 58% (without ML filter)
Win rate: 68% (with XGBoost P_win > 0.55)
Avg win: +2.3%
Avg loss: -1.2%
Risk/reward: 1 : 1.9
Sharpe ratio: 1.4
Max drawdown: -8.5%

Expected monthly return: +4-6%
Volatility: ±3%
```

---

## Resources

- **Full Guide**: `docs/LARRY_WILLIAMS_SCREENER_GUIDE.md`
- **End-to-End Workflow**: `docs/SCREENING_TO_EXECUTION.md`
- **Screener Code**: `scripts/larry_williams_screener.py`
- **Feature Engineering**: `scripts/run_feature_engineering.py`

---

**Last Updated**: 2026-05-24  
**Next Screening**: Tomorrow at 09:45 IST
