# From Backtest to Live Trading — Complete Workflow

End-to-end: Data → Features → Screener → WFO Backtest → Tear Sheet → Paper Trade → Live

---

## Phase 1: Prepare Data & Features (Week 1)

### Step 1a: Generate Features
```bash
python scripts/run_feature_engineering.py \
  --csv data/NSE_1000_MIDCAP_500.csv \
  --output ./engineered_features

# Output: engineered_features/nse_engineered_features_20260524_142530.parquet
```

### Step 1b: Verify Feature Quality
```python
import pandas as pd

features = pd.read_parquet('engineered_features/nse_engineered_features_20260524_142530.parquet')

print(f"Shape: {features.shape}")  # Expected: (630K, 8)
print(f"Date range: {features.index.get_level_values('date').min()} to {features.index.get_level_values('date').max()}")
print(f"Tickers: {features.index.get_level_values('ticker').nunique()}")
print(f"Missing %: {features.isna().sum() / len(features) * 100}")

assert features.shape[0] > 600_000, "Insufficient data"
assert features.isna().sum().sum() / features.size < 0.05, "Too many NaNs"
print("✓ Features validated")
```

---

## Phase 2: Backtest Strategy with WFO (Week 2-3)

### Step 2a: Define Your Signal Logic

```python
import pandas as pd
import numpy as np
from scripts.walk_forward_optimizer import WalkForwardOptimizer, WFOConfig

def my_rsi_oversold_strategy(data: pd.DataFrame, params: Dict) -> pd.DataFrame:
    """
    Simple RSI mean reversion strategy.
    Buy when RSI < oversold threshold AND price > 200-day MA
    """
    rsi_period = params.get('rsi_period', 14)
    rsi_oversold = params.get('rsi_oversold', 30)
    ma_period = params.get('ma_period', 200)

    signals = pd.DataFrame(0, index=data.index, columns=['signal'])

    for ticker in data.index.get_level_values('ticker').unique():
        ticker_data = data.loc[data.index.get_level_values('ticker') == ticker].copy()

        if len(ticker_data) < max(rsi_period, ma_period):
            continue

        close = ticker_data['close'].values
        high = ticker_data['high'].values
        low = ticker_data['low'].values

        # RSI calculation
        delta = np.diff(close, prepend=close[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        gain_ma = pd.Series(gain).rolling(window=rsi_period).mean().values
        loss_ma = pd.Series(loss).rolling(window=rsi_period).mean().values

        rs = gain_ma / (loss_ma + 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # SMA calculation
        sma = pd.Series(close).rolling(window=ma_period).mean().values

        # Signal: Buy oversold in uptrend, otherwise neutral/short
        signal = np.zeros_like(close)
        signal[rsi < rsi_oversold] = 1    # Oversold: BUY
        signal[(rsi >= rsi_oversold) & (close > sma)] = 0  # Uptrend but not oversold: HOLD
        signal[(rsi >= rsi_oversold) & (close <= sma)] = -1  # Downtrend: SHORT

        signals.loc[data.index.get_level_values('ticker') == ticker, 'signal'] = signal

    return signals
```

### Step 2b: Run Walk-Forward Optimization

```python
from scripts.walk_forward_optimizer import WalkForwardOptimizer, WFOConfig

# Load data
print("Loading features...")
ohlcv = pd.read_parquet('engineered_features/nse_engineered_features_20260524_142530.parquet')

# Configure WFO
config = WFOConfig(
    in_sample_days=252,        # 1 year optimization
    out_of_sample_days=63,     # 3 months testing
    step_days=63,              # Non-overlapping windows
    slippage_pct=0.001,        # 0.1% slippage
    commission_per_share=0.005,  # ₹0.005/share
    max_drawdown_pct=15.0,     # Stop if DD > 15%
    min_sortino=1.0            # Minimum acceptable
)

# Initialize optimizer
optimizer = WalkForwardOptimizer(config)

# Define parameter grid
param_grid = {
    'rsi_period': [7, 14, 21],
    'rsi_oversold': [20, 30, 40],
    'ma_period': [100, 200, 300]
}
# Total combos: 3 × 3 × 3 = 27 per window

print("Running Walk-Forward Optimization...")
results = optimizer.run_walk_forward(
    data=ohlcv,
    param_grid=param_grid,
    signal_fn=my_rsi_oversold_strategy
)

print(f"✓ Completed {len(results)} windows")
```

### Step 2c: Generate Tear Sheet

```python
from scripts.walk_forward_optimizer import MonteCarloSimulator

# Generate aggregate OOS results
tear_sheet = optimizer.generate_tear_sheet(results)

# Print summary
print("\n" + "="*80)
print("OUT-OF-SAMPLE TEAR SHEET")
print("="*80)
print(f"Total Return: {tear_sheet['total_return_pct']:+.2f}%")
print(f"Annual Return (CAGR): {tear_sheet['annual_return_pct']:+.2f}%")
print(f"Sortino Ratio: {tear_sheet['sortino_ratio']:.2f}")
print(f"Sharpe Ratio: {tear_sheet['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {tear_sheet['max_drawdown_pct']:.2f}%")
print(f"Win Rate: {tear_sheet['win_rate']:.1%}")
print(f"Average Expectancy: ₹{tear_sheet['avg_expectancy']:.2f}")
print(f"Total Trades: {tear_sheet['total_trades']}")

# Decision: Proceed to paper trading?
if tear_sheet['sortino_ratio'] > 1.5 and tear_sheet['max_drawdown_pct'] > -15:
    print("✓ PASS: Ready for paper trading")
else:
    print("✗ FAIL: Back to drawing board")

# Monte Carlo simulation
mc = MonteCarloSimulator()
mc_results = mc.simulate_drawdowns(
    tear_sheet['daily_returns'],
    iterations=1000,
    confidence_level=0.95
)

print(f"\nMonte Carlo (1000 iterations):")
print(f"  95% VaR: {mc_results['var_max_dd']:.2f}%")
print(f"  99th Percentile DD: {mc_results['percentile_99']:.2f}%")
print(f"  Mean Max DD: {mc_results['mean_max_dd']:.2f}%")
```

### Step 2d: Analyze Window-by-Window Results

```python
import matplotlib.pyplot as plt

# Compare In-Sample vs Out-of-Sample Sortino (overfitting check)
is_sortinos = [r.is_params for r in results]
oos_sortinos = [r.oos_sortino for r in results]

print(f"IS Sortino (avg): {np.mean(is_sortinos):.2f}")
print(f"OOS Sortino (avg): {np.mean(oos_sortinos):.2f}")
print(f"Degradation: {(np.mean(is_sortinos) - np.mean(oos_sortinos)) / np.mean(is_sortinos) * 100:.1f}%")

if (np.mean(is_sortinos) - np.mean(oos_sortinos)) / np.mean(is_sortinos) > 0.30:
    print("⚠ WARNING: >30% degradation suggests overfitting")
    print("  → Try wider parameter ranges or fewer parameters")
else:
    print("✓ Reasonable generalization")

# Plot equity curve
plt.figure(figsize=(12, 6))
plt.plot(tear_sheet['equity_curve'].index, tear_sheet['equity_curve'].values, linewidth=2)
plt.xlabel('Date')
plt.ylabel('Portfolio Value (₹)')
plt.title('Out-of-Sample Equity Curve')
plt.grid(True, alpha=0.3)
plt.savefig('oos_equity_curve.png', dpi=150, bbox_inches='tight')
print("✓ Saved: oos_equity_curve.png")
```

---

## Phase 3: Paper Trade (Week 4-5)

### Step 3a: Get Today's Signals

```python
import pandas as pd
from datetime import datetime

# Load latest features (run feature engineering daily)
latest_features = pd.read_parquet('engineered_features/nse_engineered_features_latest.parquet')

# Get today's date
today = latest_features.index.get_level_values('date').max()

# Use BEST parameters found during WFO
best_window = results[-1]  # Or choose specific window
best_params = best_window.optimal_params

print(f"Using best params from window: {best_params}")

# Generate today's signals
today_data = latest_features.loc[today]
signals = my_rsi_oversold_strategy(latest_features, best_params)
today_signals = signals.loc[today]

print(f"\nToday ({today.date()}) Signals:")
print(today_signals['signal'].value_counts().to_dict())
print(f"  BUY (1): {(today_signals['signal'] == 1).sum()} stocks")
print(f"  HOLD (0): {(today_signals['signal'] == 0).sum()} stocks")
print(f"  SHORT (-1): {(today_signals['signal'] == -1).sum()} stocks")
```

### Step 3b: Paper Trade (Manual or Automated)

```python
# Option A: Manual paper trading (spreadsheet)
paper_trades = []

for ticker in today_signals.index[today_signals['signal'] == 1].head(5):  # Top 5 BUY signals
    price = latest_features.loc[(today, ticker), 'close']
    atr = latest_features.loc[(today, ticker), 'atr_14'] if 'atr_14' in latest_features.columns else 10

    # Kelly Criterion sizing
    position_value = 100_000 * 0.02  # 2% per trade
    qty = int(position_value / price)
    stop_loss = price - (2 * atr)
    target = price + (3 * atr)

    paper_trades.append({
        'date': today.date(),
        'ticker': ticker,
        'signal': 'BUY',
        'entry_price': price,
        'quantity': qty,
        'position_value': qty * price,
        'stop_loss': stop_loss,
        'target': target
    })

paper_trades_df = pd.DataFrame(paper_trades)
print(paper_trades_df)

# Option B: Automated via execution service
for _, trade in paper_trades_df.iterrows():
    order = {
        'ticker': trade['ticker'],
        'side': trade['signal'],
        'quantity': trade['quantity'],
        'entry_price': trade['entry_price'],
        'stop_loss': trade['stop_loss'],
        'target': trade['target'],
        'order_type': 'LIMIT',  # Use limit orders
        'time_in_force': 'GTC'  # Good Till Cancel
    }
    # httpx.post('http://execution-service:8006/paper_trade', json=order)
```

### Step 3c: Monitor Paper Trading

```python
# Daily P&L tracking spreadsheet
import pandas as pd
from datetime import datetime, timedelta

paper_positions = pd.read_csv('paper_positions.csv')  # Manually update daily

def track_paper_pnl(positions_df):
    # Get current prices
    latest = pd.read_parquet('engineered_features/nse_engineered_features_latest.parquet')
    today = latest.index.get_level_values('date').max()

    pnl_summary = []

    for _, pos in positions_df.iterrows():
        if pd.isna(pos['close_date']):  # Still open
            current_price = latest.loc[(today, pos['ticker']), 'close']
            pnl = (current_price - pos['entry_price']) * pos['quantity']
            pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
            status = 'OPEN'
        else:  # Closed
            pnl = (pos['exit_price'] - pos['entry_price']) * pos['quantity']
            pnl_pct = ((pos['exit_price'] - pos['entry_price']) / pos['entry_price']) * 100
            status = 'CLOSED'

        pnl_summary.append({
            'ticker': pos['ticker'],
            'entry': pos['entry_price'],
            'current': current_price if pd.isna(pos['close_date']) else pos['exit_price'],
            'qty': pos['quantity'],
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'status': status
        })

    pnl_df = pd.DataFrame(pnl_summary)
    print(f"\nPaper Trading P&L ({today.date()}):")
    print(pnl_df)
    print(f"Total P&L: ₹{pnl_df['pnl'].sum():.0f} ({pnl_df['pnl_pct'].mean():+.2f}%)")

    return pnl_df

track_paper_pnl(paper_positions)
```

### Step 3d: Exit Rules for Paper Trading

```python
# Exit when:
# 1. Target hit → close at target price
# 2. Stop loss hit → close at stop loss
# 3. Reverse signal → close immediately
# 4. Time-stop → close after 5 trading days

# Example: Monitor and close positions
latest = pd.read_parquet('engineered_features/nse_engineered_features_latest.parquet')
today = latest.index.get_level_values('date').max()

for _, pos in paper_positions.iterrows():
    if pd.notna(pos['close_date']):  # Already closed
        continue

    ticker = pos['ticker']
    current_price = latest.loc[(today, ticker), 'close']
    days_held = (today - pos['entry_date']).days

    # Check exit conditions
    if current_price >= pos['target']:
        print(f"{ticker}: TARGET HIT @ ₹{current_price:.2f}")
        # Close at target
    elif current_price <= pos['stop_loss']:
        print(f"{ticker}: STOP LOSS @ ₹{current_price:.2f}")
        # Close at stop loss
    elif days_held > 5:
        print(f"{ticker}: TIME STOP (held {days_held} days)")
        # Close at market price

    # Also check for reverse signal
    today_signal = my_rsi_oversold_strategy(latest, best_params).loc[today]
    if today_signal.loc[ticker, 'signal'] != pos['signal']:
        print(f"{ticker}: REVERSE SIGNAL")
        # Close position
```

---

## Phase 4: Go Live (Week 6+)

### Step 4a: Pre-Live Checklist

```python
# Final validation before going live
checklist = {
    '✓ WFO Sortino > 1.5': tear_sheet['sortino_ratio'] > 1.5,
    '✓ WFO Max DD < 15%': abs(tear_sheet['max_drawdown_pct']) < 15,
    '✓ Paper trading passed': 'P&L positive for 2+ weeks',
    '✓ Signals generated daily': 'Run feature engineering daily at 08:00',
    '✓ Order execution tested': 'Place test order on ICICI Breeze',
    '✓ Stop losses programmed': 'All orders have 2× ATR stops',
    '✓ Position sizing verified': 'Kelly Criterion calculated',
    '✓ Max drawdown circuit': '-20% triggers trading halt',
    '✓ Telegram alerts set up': 'Entry/exit notifications working'
}

all_pass = all(checklist.values())
print(f"\nPre-Live Checklist: {'✓ PASS' if all_pass else '✗ FAIL'}")
for item, status in checklist.items():
    print(f"  {item}: {status}")
```

### Step 4b: Daily Execution Workflow (Automated)

```bash
#!/bin/bash
# Run at 08:00 IST every trading day (before market open)

# 1. Update features (5 min)
/Users/sudheer/Desktop/jupyter_env/bin/python /path/to/run_feature_engineering.py \
  --csv data/NSE_1000_MIDCAP_500.csv \
  --limit-tickers 500 2>&1 | tee logs/feature_$(date +%Y%m%d).log

# 2. Generate today's signals (2 min)
/Users/sudheer/Desktop/jupyter_env/bin/python /path/to/daily_signal_generator.py \
  --best-params best_params_from_wfo.json \
  --output today_signals.csv 2>&1 | tee logs/signal_$(date +%Y%m%d).log

# 3. Execute orders (5 min)
/Users/sudheer/Desktop/jupyter_env/bin/python /path/to/execute_orders.py \
  --signals today_signals.csv \
  --capital 100000 \
  --max-dd-circuit -20000 2>&1 | tee logs/execution_$(date +%Y%m%d).log

# 4. Send alerts
echo "Daily trading complete. Check logs for details." | \
  telegram-send --text "$(date): Orders executed. See Kite for details."
```

### Step 4c: Daily P&L Monitoring

```python
# Run at 16:00 IST (after market close)

import pandas as pd
import httpx
from datetime import datetime

# Get daily P&L
today_pnl = track_daily_pnl()

# Aggregate metrics
print(f"Total P&L: ₹{today_pnl['total_pnl']:+,.0f}")
print(f"Exposure: ₹{today_pnl['total_exposure']:,.0f}")
print(f"Win Rate Today: {today_pnl['win_rate']:.0%}")

# Check circuit breaker
if today_pnl['total_pnl'] < -20_000:
    print("⚠ -20% DRAWDOWN CIRCUIT BREAKER TRIGGERED!")
    print("   Halt trading for rest of week")
    # Send URGENT alert
else:
    # Send daily summary
    summary = f"""
Daily P&L Report ({datetime.now().date()})
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total P&L: ₹{today_pnl['total_pnl']:+,.0f}
Win Rate: {today_pnl['win_rate']:.0%}
Open Positions: {today_pnl['num_open']}
Max P&L: ₹{today_pnl['max_pnl']:+,.0f}
Min P&L: ₹{today_pnl['min_pnl']:+,.0f}
    """
    # Send via Telegram
```

---

## Metrics to Track Weekly

```python
# Weekly review (every Friday)

weekly_metrics = {
    'cumulative_pnl': 'Total money made',
    'weekly_sharpe': 'Risk-adjusted return',
    'max_dd_week': 'Worst drawdown',
    'win_rate': 'Percentage of winning trades',
    'avg_trade_size': 'Average position size',
    'avg_hold_time': 'Days in trade',
    'best_trade': 'Largest winner',
    'worst_trade': 'Largest loser'
}

# If weekly Sharpe < 0.5:
#   → Strategy is deteriorating; investigate
# If max DD > -15%:
#   → Reduce position size or tighten stops
# If win rate < 50%:
#   → Entry signal may be degraded; backtest again
```

---

## When to Retrain

**Retrain Walk-Forward every**:
- [ ] Monthly (check for parameter drift)
- [ ] After 2 consecutive losing weeks
- [ ] When Sortino drops below 1.0
- [ ] When max DD exceeds 20%

**Update features daily** (required).

---

## Post-Mortem: Backtest vs Live

When live returns diverge from backtest:

| Gap | Root Cause | Fix |
|-----|-----------|-----|
| Live worse | Slippage > 0.1% | Use limit orders only |
| Live worse | Commissions missed | Verify ₹0.005/share |
| Live worse | Fills at worse prices | Increase time budget for orders |
| Live better | Market is trending | Lucky; stay the course |
| Live volatility > expected | Market regime changed | Reduce position size |

---

## Long-Term Success (6+ Months)

**Signs you're on track:**
- ✓ OOS Sharpe > 1.0 sustained
- ✓ Win rate stays 50%+
- ✓ Max DD never exceeds circuit (-20%)
- ✓ Monthly returns consistent with backtest
- ✓ Sortin ratio > 1.5 for 6+ months

**Time to scale:**
- After 6 months profitability: 2× capital
- After 12 months: 5× capital (if Sharpe > 1.5)
- After 24 months: Full allocation

**When to pause:**
- 3 consecutive losing months → investigate
- Sortino < 0.5 for 2+ weeks → backtest again
- Live results diverge >30% from WFO → rebuild

---

**Generated for SuryaDhana Backtest Lab · NSE Quantitative Trading**
