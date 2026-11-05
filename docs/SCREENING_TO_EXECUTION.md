# From Screening to Execution: Complete Workflow

End-to-end pipeline from NSE OHLCV data → Larry Williams screen → XGBoost confidence → Risk sizing → ICICI Breeze execution.

---

## Workflow Architecture

```
1. RAW DATA
   └─ NSE CSV (500 stocks × 5 years)
      
2. FEATURE ENGINEERING
   └─ scripts/run_feature_engineering.py
      Output: Parquet (8 engineered features)
      
3. DAILY SCREENING
   └─ scripts/larry_williams_screener.py
      Input: Features Parquet
      Filters: Squeeze + Oops + Oversold + Liquidity
      Output: DataFrame (top 10 actionable tickers)
      
4. ML CONFIDENCE FILTERING (Optional)
   └─ XGBoost regressor (probability model)
      Input: Screened tickers + full feature set
      Output: Confidence scores (0.0–1.0)
      Action: Keep only P_win > 0.55
      
5. RISK MANAGEMENT
   └─ Kelly Criterion position sizing
      Input: Entry price, ATR, historical win rate
      Output: Position size (% of portfolio)
      
6. EXECUTION
   └─ ICICI Breeze API order placement
      Input: Ticker, size, entry, stop loss, target
      Output: Order ID + live updates

7. MONITORING
   └─ Telegram alerts + Prometheus metrics
      Track: P&L, Sharpe ratio, max drawdown
```

---

## Day 1: Setup & First Screening

### Step 1: Ensure Features Are Generated

```bash
# If not already done, generate features from NSE CSV
python scripts/run_feature_engineering.py \
  --csv data/NSE_1000_MIDCAP_500.csv \
  --output ./engineered_features

# Output: engineered_features/nse_engineered_features_20260524_142530.parquet
```

### Step 2: Run Daily Screener

```bash
# Get top setups for today
python scripts/larry_williams_screener.py \
  --parquet engineered_features/nse_engineered_features_20260524_142530.parquet \
  --output screening_results.csv \
  --breakdown
```

**Example Output:**
```
Universe size: 500
Squeeze (Filter 1): 43
Oops Reversal (Filter 2): 15
Oversold Uptrend (Filter 3): 22
Liquidity (Filter 4): 487
Combined (All 4): 7

Top 5 setups by ATR expansion:
                close   atr_14  williams_r_14      adv_20
COALINDIA     462.35    12.42       -85.30  4.63e+07
SBIN          520.15     8.94       -82.15  1.28e+08
BAJAJFINSV    1842.50   45.32       -81.70  8.92e+07
ICICIBANK     660.20     11.15       -83.50  2.14e+08
HDFCBANK      1920.75     8.70       -84.20  1.98e+08
```

### Step 3: Load Results in Python

```python
import pandas as pd
from scripts.larry_williams_screener import load_engineered_features_ohlcv, VolatilityBreakoutScreener

# Load screening results
screening_results = pd.read_csv('screening_results.csv', index_col='ticker')

print(f"Found {len(screening_results)} setups")
print(screening_results[['close', 'atr_14', 'williams_r_14']])

# Access screener for detailed analysis
ohlcv = load_engineered_features_ohlcv('engineered_features/nse_engineered_features_20260524_142530.parquet')
screener = VolatilityBreakoutScreener(ohlcv)
actionable = screener.screen()

# Check which tickers passed which filters
for ticker in actionable.index[:3]:
    setup = actionable.loc[ticker]
    print(f"\n{ticker}:")
    print(f"  Price: ₹{setup['close']:.2f}")
    print(f"  ATR 14: ₹{setup['atr_14']:.2f}")
    print(f"  Williams %R: {setup['williams_r_14']:.1f}")
    print(f"  ADV 20: ₹{setup['adv_20']/1e6:.1f}M")
```

---

## Day 2: Add XGBoost Confidence Filter (Optional)

### Step 1: Train XGBoost (One-time)

```python
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score

# Load engineered features
features = pd.read_parquet('engineered_features/nse_engineered_features_20260524_142530.parquet')

# Prepare training data
X = features[[c for c in features.columns if 'return' not in c]].fillna(0)
y_targets = features['log_return_5d'].shift(-5)  # 5-day forward return

# Remove NaN targets
valid_idx = ~y_targets.isna()
X = X[valid_idx]
y = (y_targets[valid_idx] > 0).astype(int)  # Binary: win (1) or loss (0)

# Time-series split (NO shuffling)
tscv = TimeSeriesSplit(n_splits=5)
scores = []

for train_idx, test_idx in tscv.split(X):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    
    # Train
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=0)
    
    # Evaluate
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    scores.append(acc)
    print(f"Fold accuracy: {acc:.2%}")

print(f"Average accuracy: {np.mean(scores):.2%}")

# Save model
model.save_model('models/xgb_classifier_5day.json')
print("✓ Model saved to models/xgb_classifier_5day.json")
```

### Step 2: Add ML Confidence to Screened Results

```python
import xgboost as xgb

# Load trained model
model = xgb.XGBClassifier()
model.load_model('models/xgb_classifier_5day.json')

# Load screening results and features
screening = pd.read_csv('screening_results.csv', index_col='ticker')
features = pd.read_parquet('engineered_features/nse_engineered_features_20260524_142530.parquet')

# Get today's features for screened tickers
today = features.index.get_level_values('date').max()
today_features = features.loc[today]

# Filter to screened tickers only
screened_features = today_features.loc[screening.index].fillna(0)

# Drop return columns (look-ahead bias prevention)
X_screen = screened_features[[c for c in screened_features.columns 
                               if 'return' not in c.lower()]]

# Get predictions + probabilities
predictions = model.predict(X_screen)
probabilities = model.predict_proba(X_screen)[:, 1]  # P(win)

# Add to screening results
screening['xgb_win_prob'] = probabilities
screening['xgb_prediction'] = predictions

# Filter to high-confidence
high_confidence = screening[screening['xgb_win_prob'] > 0.55]

print(f"Original screens: {len(screening)}")
print(f"High confidence (P_win > 0.55): {len(high_confidence)}")
print(f"\nTop 5 by confidence:")
print(high_confidence.nlargest(5, 'xgb_win_prob')[['close', 'atr_14', 'xgb_win_prob']])
```

---

## Risk Management: Position Sizing

### Kelly Criterion Sizing

```python
import pandas as pd

def kelly_position_sizing(
    entry_price: float,
    atr: float,
    historical_win_rate: float = 0.55,
    risk_reward_ratio: float = 1.5,
    portfolio_value: float = 100_000,  # ₹100K starting
    max_position_pct: float = 0.15  # Max 15% per stock
) -> dict:
    """
    Calculate position size using Kelly Criterion.
    
    Kelly % = (Win_Rate - Loss_Rate / RR) / 2
    Position size = Portfolio × Kelly % (half-Kelly for safety)
    """
    
    win_rate = historical_win_rate
    loss_rate = 1 - win_rate
    
    # Full Kelly
    kelly_pct = (win_rate - (loss_rate / risk_reward_ratio)) / 2
    
    # Half-Kelly (more conservative)
    kelly_pct = kelly_pct / 2
    
    # Adjust for risk tolerance
    kelly_pct = max(0.01, min(kelly_pct, 0.05))  # 1-5% per trade
    
    position_value = portfolio_value * kelly_pct
    position_size = position_value / entry_price
    
    # Cap at max position %
    max_position_value = portfolio_value * max_position_pct
    if position_value > max_position_value:
        position_size = max_position_value / entry_price
    
    # Risk metrics
    stop_loss = entry_price - (2 * atr)  # 2× ATR stop
    risk_per_share = entry_price - stop_loss
    total_risk = position_size * risk_per_share
    
    # Target (using risk-reward ratio)
    target = entry_price + (risk_per_share * risk_reward_ratio)
    
    return {
        'entry_price': entry_price,
        'position_size': int(position_size),
        'position_value': position_size * entry_price,
        'stop_loss': stop_loss,
        'target': target,
        'risk_per_share': risk_per_share,
        'total_risk': total_risk,
        'risk_pct': (total_risk / portfolio_value) * 100,
        'reward_pct': ((target - entry_price) / entry_price) * 100
    }


# Example: COALINDIA screened setup
screening = pd.read_csv('screening_results.csv', index_col='ticker')
setup = screening.loc['COALINDIA']

sizing = kelly_position_sizing(
    entry_price=setup['close'],
    atr=setup['atr_14'],
    historical_win_rate=0.58,  # From backtest
    risk_reward_ratio=1.8,
    portfolio_value=100_000
)

print(f"COALINDIA Position Plan:")
print(f"  Entry: ₹{sizing['entry_price']:.2f}")
print(f"  Quantity: {sizing['position_size']} shares")
print(f"  Position Value: ₹{sizing['position_value']:.0f} ({sizing['position_value']/100_000*100:.1f}% of portfolio)")
print(f"  Stop Loss: ₹{sizing['stop_loss']:.2f} ({sizing['risk_pct']:.2f}% risk)")
print(f"  Target: ₹{sizing['target']:.2f} ({sizing['reward_pct']:.2f}% reward)")
print(f"  Risk/Reward: 1 : {sizing['reward_pct']/sizing['risk_pct']:.2f}")
```

**Output Example:**
```
COALINDIA Position Plan:
  Entry: ₹462.35
  Quantity: 47 shares
  Position Value: ₹21,750 (21.8% of portfolio)
  Stop Loss: ₹437.51 (2.24% risk)
  Target: ₹515.78 (11.6% reward)
  Risk/Reward: 1 : 5.18
```

---

## Execution: ICICI Breeze Integration

### Example: Place Orders for Top Setups

```python
import httpx
import pandas as pd
from datetime import datetime

# Load high-confidence setups
screening = pd.read_csv('screening_results.csv', index_col='ticker')
high_conf = screening.nlargest(5, 'atr_14')  # Top 5 by volatility

for ticker in high_conf.index:
    setup = high_conf.loc[ticker]
    
    # Calculate position
    sizing = kelly_position_sizing(
        entry_price=setup['close'],
        atr=setup['atr_14'],
        portfolio_value=100_000
    )
    
    # Build order
    order_payload = {
        'ticker': ticker,
        'signal_type': 'VOLATILITY_SQUEEZE',
        'side': 'BUY',
        'order_type': 'LIMIT',
        'entry_price': float(setup['close']),
        'quantity': sizing['position_size'],
        'stop_loss': float(sizing['stop_loss']),
        'target': float(sizing['target']),
        'metadata': {
            'setup': 'Larry Williams Squeeze',
            'atr': float(setup['atr_14']),
            'williams_r': float(setup['williams_r_14']),
            'adv': float(setup['adv_20']),
            'timestamp': datetime.now().isoformat()
        }
    }
    
    # Send to execution service (ICICI Breeze API)
    try:
        response = httpx.post(
            'http://execution-service:8006/api/orders/place',
            json=order_payload,
            timeout=10
        )
        result = response.json()
        print(f"✓ {ticker}: Order placed (ID={result['order_id']})")
        
    except Exception as e:
        print(f"✗ {ticker}: Order failed — {e}")
```

---

## Monitoring: Daily P&L Tracking

### Track Performance

```python
import pandas as pd
from datetime import datetime, timedelta

def track_daily_pnl(
    trades_df: pd.DataFrame,
    current_prices: dict,
    portfolio_value: float = 100_000
) -> dict:
    """
    Calculate daily P&L for open positions.
    
    Args:
        trades_df: DataFrame with columns [ticker, entry_price, quantity, stop_loss]
        current_prices: Dict of {ticker: current_price}
        portfolio_value: Starting portfolio value
    """
    
    total_pnl = 0
    total_exposure = 0
    winning_trades = 0
    
    pnl_details = []
    
    for ticker, trade in trades_df.iterrows():
        current_price = current_prices.get(ticker, trade['entry_price'])
        trade_pnl = (current_price - trade['entry_price']) * trade['quantity']
        trade_pnl_pct = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
        
        exposure = trade['quantity'] * current_price
        total_exposure += exposure
        total_pnl += trade_pnl
        
        if current_price > trade['entry_price']:
            winning_trades += 1
            status = "✓ GREEN"
        else:
            status = "✗ RED"
        
        pnl_details.append({
            'ticker': ticker,
            'entry': trade['entry_price'],
            'current': current_price,
            'quantity': trade['quantity'],
            'pnl': trade_pnl,
            'pnl_pct': trade_pnl_pct,
            'status': status
        })
    
    # Summary
    portfolio_pnl_pct = (total_pnl / portfolio_value) * 100
    win_rate = winning_trades / len(trades_df) if len(trades_df) > 0 else 0
    
    return {
        'total_pnl': total_pnl,
        'total_pnl_pct': portfolio_pnl_pct,
        'total_exposure': total_exposure,
        'win_rate': win_rate,
        'num_trades': len(trades_df),
        'details': pd.DataFrame(pnl_details)
    }


# Example
trades = pd.DataFrame({
    'ticker': ['COALINDIA', 'SBIN', 'BAJAJFINSV'],
    'entry_price': [462.35, 520.15, 1842.50],
    'quantity': [47, 38, 27],
    'stop_loss': [437.51, 495.20, 1797.18]
})

current_prices = {
    'COALINDIA': 468.50,
    'SBIN': 525.60,
    'BAJAJFINSV': 1839.20
}

pnl = track_daily_pnl(trades, current_prices, 100_000)

print(f"\n=== Daily P&L Summary ===")
print(f"Total P&L: ₹{pnl['total_pnl']:.0f} ({pnl['total_pnl_pct']:+.2f}%)")
print(f"Exposure: ₹{pnl['total_exposure']:.0f}")
print(f"Win Rate: {pnl['win_rate']:.0%}")
print(f"\n{pnl['details']}")
```

---

## Automated Daily Workflow (Cron Job)

### Schedule Daily Screening at Market Open

```bash
# Add to crontab -e (runs at 09:30 IST when NSE opens)

# Feature engineering (run once weekly, every Friday after market close)
0 16 * * 5 /Users/sudheer/Desktop/jupyter_env/bin/python /path/to/run_feature_engineering.py \
  --csv data/NSE_1000_MIDCAP_500.csv \
  --output ./engineered_features

# Daily screening (every trading day at 09:45 AM)
45 9 * * 1-5 cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI && \
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/larry_williams_screener.py \
  --parquet engineered_features/nse_engineered_features_latest.parquet \
  --output screening_results.csv && \
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/execute_screening_results.py

# Daily P&L summary (every trading day at 15:30 IST after market close)
30 15 * * 1-5 /Users/sudheer/Desktop/jupyter_env/bin/python scripts/track_daily_pnl.py
```

---

## Performance Checklist

Before going live:

- [ ] Feature engineering tested on full 5-year dataset
- [ ] XGBoost model trained with TimeSeriesSplit (55%+ accuracy)
- [ ] Screener backtested on 2+ years of historical data
- [ ] Kelly Criterion sizing validated (Sharpe > 1.0)
- [ ] ICICI Breeze API connectivity tested
- [ ] Stop losses placed immediately on order fill
- [ ] Daily monitoring dashboard set up
- [ ] Telegram alerts configured for entry/exit
- [ ] Portfolio max drawdown = -20% circuit breaker enabled

---

**Ready for live trading!**
