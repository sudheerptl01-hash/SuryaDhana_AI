# Walk-Forward Optimization Backtesting — Robert Pardo Methodology

## The Problem with Traditional Backtesting

**Naive approach** (❌ WRONG):
```
1. Load 5-year data
2. Optimize parameters on entire dataset (data mining!)
3. Report amazing results (Sharpe 2.5, 80% win rate)
4. Deploy live → Strategy fails (curve-fitted to noise)
```

**Why it fails**: Parameters optimized on full dataset *look into the future* implicitly. You're fitting noise, not genuine edge.

---

## Robert Pardo's Walk-Forward Optimization (✅ RIGHT)

**WFO approach**:
```
For each rolling window:
  1. Optimize on 1-year IN-SAMPLE (blind params)
  2. Test on 3-month OUT-OF-SAMPLE (unseen data)
  3. Roll forward and repeat

Aggregate OUT-OF-SAMPLE results = true expected performance
```

**Key insight**: Each parameter set is tested on data it never saw. This proves generalization.

---

## Architecture Overview

### Rolling Window Structure

```
Timeline: 5 years = 1260 trading days

Window 0:
├─ IS: Day 1–252 (1 year optimization)
└─ OOS: Day 253–315 (3 months testing)

Window 1:
├─ IS: Day 64–315 (roll forward 63 days)
└─ OOS: Day 316–378

Window 2:
├─ IS: Day 127–378
└─ OOS: Day 379–441

... repeat until end of data

OOS concat: Day 253–315, 316–378, 379–441, ...
This is your REAL performance (no look-ahead bias)
```

### Look-Ahead Bias Prevention

Strict assertions ensure:
1. ✅ IS dates < OOS dates (non-overlapping)
2. ✅ Parameter optimization on IS only
3. ✅ OOS evaluation is blind (no peeking)
4. ✅ Window continuity (no gaps)
5. ✅ All windows progress monotonically

---

## Configuration

### WFOConfig

```python
from scripts.walk_forward_optimizer import WFOConfig

config = WFOConfig(
    # Rolling window sizes
    in_sample_days=252,        # ~1 year (optimization period)
    out_of_sample_days=63,     # ~3 months (testing period)
    step_days=63,              # Roll forward by OOS size (non-overlapping)

    # Trading frictions (realistic)
    slippage_pct=0.001,        # 0.1% per fill (bid-ask + market impact)
    commission_per_share=0.005,  # ₹0.005/share (typical NSE)

    # Optimization constraints (NOT profit!)
    min_sortino=1.0,           # Minimum acceptable Sortino ratio
    max_drawdown_pct=15.0,     # Stop if DD > 15%
    min_win_rate=0.45,         # Minimum acceptance threshold

    # Risk-free rate for metrics
    risk_free_rate=0.05,       # 5% annual (India G-Sec)

    # Monte Carlo
    monte_carlo_iterations=1000,
    confidence_level=0.95
)
```

---

## Optimization Metrics (Why Sortino Ratio?)

### Metric Comparison

| Metric | Formula | Problem |
|--------|---------|---------|
| **Profit** | ∑ PnL | Ignores risk; optimize for cliffhanger |
| **Sharpe** | (Return - RF) / Volatility | Penalizes upside volatility (bad!) |
| **Sortino** | (Return - RF) / Downside_Volatility | ✅ Only penalizes losses |

### Why Sortino?

Sortino ratio ignores upside volatility. If your strategy wins 3% on good days and loses 1% on bad days:
- Sharpe penalizes both (WRONG)
- Sortino rewards the asymmetry (CORRECT)

```python
Sortino = Annual Return / Annual Downside StdDev

Good strategies: Sortino 1.5–2.5+
Excellent: Sortino > 2.0
World-class: Sortino > 3.0
```

---

## Usage

### Step 1: Load Your Signal Data

Signals must be a MultiIndex (date, ticker) DataFrame with column 'signal' (-1/0/1):

```python
import pandas as pd
from scripts.walk_forward_optimizer import WalkForwardOptimizer, WFOConfig

# Load OHLCV data
ohlcv = pd.read_parquet('engineered_features/nse_engineered_features_20260524.parquet')

# Load/generate signals
signals = pd.read_parquet('trading_signals.parquet')
# Must have:
# - MultiIndex (date, ticker)
# - Column 'signal' with values in [-1, 0, 1]
# - Sorted by (date, ticker)
```

### Step 2: Define Your Signal Generator Function

The function receives data + parameters, returns signals:

```python
def my_trading_logic(data: pd.DataFrame, params: Dict) -> pd.DataFrame:
    """
    Args:
        data: MultiIndex (date, ticker) OHLCV
        params: Dict like {'rsi_period': 14, 'rsi_oversold': 30}

    Returns:
        Signal DataFrame with column 'signal' (-1/0/1)
    """
    signals = pd.DataFrame(0, index=data.index, columns=['signal'])

    rsi_period = params.get('rsi_period', 14)
    rsi_oversold = params.get('rsi_oversold', 30)

    # Your indicator logic here
    for ticker in data.index.get_level_values('ticker').unique():
        ticker_data = data.loc[data.index.get_level_values('ticker') == ticker]
        
        # Compute RSI
        delta = ticker_data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # Generate signal
        signal = np.where(rsi < rsi_oversold, 1, -1)  # 1 = buy oversold, -1 = otherwise
        signals.loc[data.index.get_level_values('ticker') == ticker, 'signal'] = signal

    return signals
```

### Step 3: Run Walk-Forward Optimization

```python
from scripts.walk_forward_optimizer import WalkForwardOptimizer, WFOConfig

# Configure
config = WFOConfig(
    in_sample_days=252,
    out_of_sample_days=63,
    step_days=63
)

# Initialize optimizer
optimizer = WalkForwardOptimizer(config)

# Define parameter space
param_grid = {
    'rsi_period': [7, 14, 21],
    'rsi_oversold': [20, 30, 40]
    # This = 3 × 3 = 9 combinations per window
}

# Run WFO
results = optimizer.run_walk_forward(
    data=ohlcv,
    param_grid=param_grid,
    signal_fn=my_trading_logic
)

# Generate tear sheet
tear_sheet = optimizer.generate_tear_sheet(results)

# Monte Carlo
from scripts.walk_forward_optimizer import MonteCarloSimulator
mc = MonteCarloSimulator()
mc_results = mc.simulate_drawdowns(
    tear_sheet['daily_returns'],
    iterations=1000
)

print(f"Out-of-Sample Sortino: {tear_sheet['sortino_ratio']:.2f}")
print(f"Out-of-Sample Max DD: {tear_sheet['max_drawdown_pct']:.2f}%")
print(f"95% VaR (MC): {mc_results['var_max_dd']:.2f}%")
```

---

## Interpreting Results

### Tear Sheet Components

```python
tear_sheet = {
    # Aggregate OOS results
    'total_return_pct': 45.2,         # 5 years: +45.2%
    'annual_return_pct': 7.8,         # CAGR: 7.8%
    'sortino_ratio': 1.65,            # Good (>1.5)
    'sharpe_ratio': 1.42,             # Supporting metric
    'max_drawdown_pct': -12.3,        # Worst day from peak
    'win_rate': 0.58,                 # 58% of trades win
    'avg_expectancy': 125.50,         # ₹125.50 per trade on average
    'total_trades': 1247,             # Total trades across all OOS periods
    'equity_curve': pd.Series(...),   # Daily equity curve
    'daily_returns': pd.Series(...)   # Daily returns %
}
```

### Red Flags

| Issue | What to Do |
|-------|-----------|
| Sortino < 1.0 | Strategy is not worth risk; rebuild |
| Max DD > 20% | Too risky; add position sizing rules |
| Win Rate < 45% | Risk/reward misaligned; adjust stops |
| Total trades < 100 | Too few signals; diversify |
| IS vs OOS divergence > 50% | Overfitting; relax parameter space |

### Green Lights

| Metric | Excellent | Good | Acceptable |
|--------|-----------|------|-----------|
| Sortino | > 2.0 | 1.5–2.0 | > 1.0 |
| Max DD | < 10% | 10–15% | < 20% |
| Win Rate | > 60% | 55–60% | > 45% |
| Expectancy | > 200 | 100–200 | > 50 |
| CAGR | > 15% | 8–15% | > 5% |

---

## Advanced: Custom Parameter Optimization

Instead of grid search, use Bayesian optimization (faster):

```python
from scipy.optimize import differential_evolution

def objective_function(params_tuple):
    """Minimize negative Sortino (for minimization solver)"""
    params = {
        'rsi_period': int(params_tuple[0]),
        'rsi_oversold': int(params_tuple[1])
    }
    
    is_data, oos_data = window  # Current window
    
    signals = my_trading_logic(is_data, params)
    equity, trades = executor.execute_signals(signals, is_data)
    returns = equity.pct_change().dropna()
    sortino = metrics.sortino_ratio(returns)
    
    return -sortino  # Minimize negative = maximize positive

# Bounds
bounds = [(7, 21), (20, 40)]  # [rsi_period range], [oversold range]

result = differential_evolution(objective_function, bounds, seed=42)
print(f"Optimal params: {result.x}")
```

---

## Monte Carlo Interpretation

Monte Carlo reshuffles actual returns to estimate worst-case drawdown.

```python
mc_results = {
    'mean_max_dd': -8.5,        # Average worst DD across 1000 simulations
    'median_max_dd': -8.2,      # Typical worst DD
    'std_max_dd': 2.1,          # Volatility of worst DD
    'var_max_dd': -12.3,        # 95% VaR: 95% of simulations worse than -12.3%
    'percentile_99': -15.2      # 1% chance of DD worse than -15.2%
}
```

**Interpretation**:
- If 95% VaR = -12.3%, you'll likely never hit DD > 12.3%
- If you can tolerate -15% DD, you're 99% safe
- If actual max DD is -10%, you're within normal distribution

---

## Integration with Signal Screener

Combine Larry Williams screener + WFO for full pipeline:

```python
from scripts.larry_williams_screener import VolatilityBreakoutScreener
from scripts.walk_forward_optimizer import WalkForwardOptimizer

# Step 1: Get daily screened signals from Williams setup
screener = VolatilityBreakoutScreener(ohlcv)
daily_screened = screener.screen()  # Shape: (500, cols)

# Convert to signal format
signals = pd.DataFrame(-1, index=ohlcv.index, columns=['signal'])
for ticker in daily_screened.index:
    mask = signals.index.get_level_values('ticker') == ticker
    # +1 if passed screen, -1 otherwise
    signals.loc[mask, 'signal'] = 1

# Step 2: Optimize entry/exit parameters on screened universe
def williams_with_params(data, params):
    signals = signals_from_williams_screen(data, params)
    return signals

optimizer = WalkForwardOptimizer()
results = optimizer.run_walk_forward(ohlcv, param_grid, williams_with_params)
tear_sheet = optimizer.generate_tear_sheet(results)
```

---

## Common Pitfalls

### 1. Too Many Parameters (Overfitting)

❌ WRONG:
```python
param_grid = {
    'ma_fast': range(3, 51),      # 48 values
    'ma_slow': range(10, 201),    # 191 values
    'rsi_period': range(5, 30),   # 25 values
    'rsi_threshold': range(20, 80) # 60 values
}
# Total combos: 48 × 191 × 25 × 60 = 1.4M (will overfit!)
```

✅ CORRECT:
```python
param_grid = {
    'ma_fast': [5, 10, 20],       # 3 values
    'ma_slow': [20, 50, 100]      # 3 values
}
# Total combos: 3 × 3 = 9 (manageable)
```

### 2. Too Many In-Sample Periods (Luck)

❌ Small IS (30 days):
- Only 30 data points to optimize on
- Parameter optimization is pure luck
- OOS won't generalize

✅ Standard IS (252 days):
- 1 year of data
- ~50 trades to optimize
- Statistically significant

### 3. Ignoring Slippage/Commissions

❌ Backtesting without frictions:
```
Backtest: +45% annual
Live trading: +2% annual (after costs)
```

✅ Always include:
```python
slippage_pct=0.001         # 0.1% for NSE liquid stocks
commission_per_share=0.005  # ₹0.005 typical
```

---

## Benchmark Results

**For reference**, typical institutional strategies:

| Metric | Bottom 25% | Median | Top 25% | Excellent |
|--------|-----------|--------|---------|-----------|
| Sortino | < 0.5 | 1.2 | 1.8+ | > 2.5 |
| CAGR | < 5% | 8–10% | 15%+ | > 20% |
| Max DD | > 25% | 12–15% | < 10% | < 5% |
| Win Rate | < 48% | 52% | 58%+ | > 65% |
| Profit Factor | < 1.2 | 1.5 | 2.0+ | > 3.0 |

---

## Next Steps

1. **Backtest your signal logic** with WFO
2. **Check OOS Sortino** (target: > 1.5)
3. **Run Monte Carlo** to estimate worst-case drawdown
4. **Compare IS vs OOS** (divergence < 30% = good generalization)
5. **Size positions** using Kelly Criterion from historical win rate
6. **Paper trade** for 2 weeks before going live

---

## Resources

- **Code**: `scripts/walk_forward_optimizer.py`
- **Signal Screener**: `docs/LARRY_WILLIAMS_SCREENER_GUIDE.md`
- **Position Sizing**: `docs/SCREENING_TO_EXECUTION.md`
- **Pardo's Book**: "The Evaluation and Optimization of Trading Strategies"

---

**Generated for SuryaDhana Backtest Lab · NSE Quantitative Trading**
