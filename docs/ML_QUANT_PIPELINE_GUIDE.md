# ML Quant Pipeline: Complete Technical Guide

## Overview

Complete end-to-end production-grade machine learning pipeline for predictive stock scanning across 500+ stocks. Implements five advanced quantitative finance techniques:

1. **Triple-Barrier Method** — Dynamic labeling with ATR-based barriers + vertical time barrier
2. **Meta-Labeling** — Two-tier classification: primary trend model + secondary trust classifier
3. **Purged & Embargoed CPCV** — Time-series safe cross-validation preventing look-ahead bias
4. **Feature Selection** — MDA (Mean Decrease Accuracy) + MDI (Mean Decrease Impurity) ranking
5. **Optuna Hyperparameter Tuning** — Bayesian optimization maximizing Sortino ratio

---

## Architecture & Components

### 1. Triple-Barrier Method (`TripleBarrierLabeler`)

**Purpose**: Generate ground-truth labels for supervised learning in time-series.

**Three Barriers**:
- **Upper Barrier**: `entry_price + ATR * atr_multiplier_up`
- **Lower Barrier**: `entry_price - ATR * atr_multiplier_down`
- **Vertical Barrier**: `entry_date + holding_period` days

**Labeling Logic**:
- Label = **1** if upper barrier hit first (profit opportunity)
- Label = **-1** if lower barrier hit first (loss risk)
- Label = **0** if vertical barrier hit first (neutral outcome)

**Key Parameters**:
```python
atr_window: int = 20            # Rolling ATR period
atr_multiplier_up: float = 1.0  # How many ATRs above entry
atr_multiplier_down: float = 1.0# How many ATRs below entry
holding_period: int = 5         # Maximum holding days
min_return_threshold: float = 0.001  # Min return to avoid label 0
```

**Implementation**:
```python
labeler = TripleBarrierLabeler(
    atr_window=20,
    atr_multiplier_up=1.0,
    atr_multiplier_down=1.0,
    holding_period=5,
    min_return_threshold=0.001,
)
df_labeled = labeler.label_signals(df)
# Output: df with 'label', 'return_pct', 'atr', 'barrier_up', 'barrier_down'
```

**Advantages**:
- Avoids fixed stop-loss thresholds (adaptive to volatility via ATR)
- Captures both profit-taking and loss-avoiding opportunities
- Respects holding period constraint (realistic for holding strategies)
- Prevents look-ahead bias (barriers calculated at entry time)

---

### 2. Meta-Labeling (`MetaLabeler`)

**Purpose**: Create a secondary layer of classification to determine if primary model predictions should be trusted.

**Two-Tier Architecture**:

```
Tier 1: Primary Model (Trend-Following)
  Input: Technical features
  Output: Direction signal (bullish=1, bearish=0)
  Example: Price > 20-day SMA → bullish

Tier 2: Secondary Classifier (Meta-Model)
  Input: Primary signal + features
  Output: Confidence score (should execute signal? 1=yes, 0=no)
  Logic: Meta-label = 1 if primary signal aligns with actual outcome
```

**Meta-Label Calculation**:
```python
primary_signal = 1 if price > sma_20 else 0

# Meta-label is 1 only if primary signal was CORRECT
meta_label = 1 if (primary_signal == 1 and actual_return > 0) or \
                   (primary_signal == 0 and actual_return < 0)
meta_label = 0 otherwise
```

**Implementation**:
```python
df['meta_label'] = MetaLabeler.create_meta_labels(df)

# Train secondary classifier on meta_label to learn when primary model is reliable
X = df[feature_columns]
y = df['meta_label']  # 1 = trust signal, 0 = ignore signal
```

**Advantages**:
- Filters out unreliable primary signals
- Reduces false positives (higher precision)
- Focuses trading on high-confidence setups only
- Reduces transaction costs (fewer trades, higher quality)

---

### 3. Feature Engineering (`FeatureEngineer`)

**40+ Technical Indicators** engineered automatically:

**Price-Based Features** (8):
- `return` — simple daily return
- `log_return` — log return
- `price_momentum_5`, `price_momentum_20` — rolling average of returns
- `sma_5`, `sma_20`, `sma_50` — simple moving averages
- `price_to_sma5`, `price_to_sma20` — price-to-SMA ratios

**Volatility Features** (5):
- `volatility_5`, `volatility_20` — rolling volatility (std of returns)
- `atr` — Average True Range
- `hl_spread` — (high - low) / close
- `hl_spread_ma` — rolling mean of spread

**Momentum Indicators** (6):
- `rsi_14` — Relative Strength Index
- `macd`, `macd_signal`, `macd_diff` — MACD components
- `bb_upper`, `bb_middle`, `bb_lower` — Bollinger Bands
- `bb_position` — Price position within bands [0, 1]

**Trend Indicators** (5):
- `ema_12`, `ema_26` — Exponential moving averages
- `obv` — On-Balance Volume
- `vpt` — Volume Price Trend

**Volume Indicators** (3):
- `volume_ma_5`, `volume_ma_20` — rolling volume averages
- `volume_ratio` — current volume / 20-day avg

**Statistical Features** (5):
- `returns_skew` — skewness of returns
- `returns_kurt` — kurtosis of returns
- `return_autocorr_lag1` — lag-1 autocorrelation
- `gap` — open - previous close
- `range` — high - low

**Implementation**:
```python
engineer = FeatureEngineer()
df_features = engineer.engineer_features(df)
# Output: df with 40+ feature columns
```

**Why 40+ Features?**
- Redundancy → feature selection identifies truly predictive features
- Diverse signal sources → captures multiple market regimes
- Robustness → selected features more likely to be stable OOS

---

### 4. Purged & Embargoed Cross-Validation (`PurgedKFoldCV`)

**Problem**: Standard K-fold CV causes look-ahead bias in time-series:
- Training set includes dates temporally overlapping with test set
- Model sees "future" information when making "past" predictions
- Wildly overestimates out-of-sample performance

**Solution**: Purging + Embargo

```
Standard 5-Fold CV:
Fold 1: Train: [0-200]      Test: [201-250]      ← Overlap!
Fold 2: Train: [0-250]      Test: [251-300]      ← Overlap!

Purged & Embargoed 5-Fold CV:
Fold 1: Train: [0-180]      Embargo: [181-220]   Test: [221-250]
Fold 2: Train: [0-230]      Embargo: [231-270]   Test: [271-300]
                            ↑ Removed from training
```

**Key Concepts**:

1. **Purging**: Remove all training samples with dates overlapping test fold
2. **Embargo**: Remove training samples in the embargo window (before/after test fold)
   - Prevents leakage from information arriving after test date
   - Default: 1% of dataset

**Implementation**:
```python
cv = PurgedKFoldCV(n_splits=5, embargo_pct=0.01)

for train_idx, test_idx in cv.split(X):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    
    # Training set has NO temporal overlap with test set
    # Realistic OOS evaluation
```

**Advantages**:
- Prevents look-ahead bias
- Realistic performance estimates
- Avoids overfitting to specific dates
- More conservative evaluation

---

### 5. Feature Selection (MDA & MDI)

**Two Complementary Methods**:

#### Mean Decrease Accuracy (MDA)
- **Measures**: How much accuracy drops when feature is randomly permuted
- **Interpretation**: Features that hurt prediction when shuffled are important
- **Captures**: Predictive value in test set
- **Pros**: Reflects OOS predictive power; model-agnostic
- **Cons**: Computationally expensive; can be noisy

#### Mean Decrease Impurity (MDI)
- **Measures**: Total decrease in splitting criteria (Gini/Entropy) across all trees
- **Interpretation**: Features that split on frequently are important
- **Captures**: How much the model relies on each feature
- **Pros**: Fast to compute; stable
- **Cons**: Biased toward high-cardinality features; training-set performance

#### Combined Ranking
```
importance_score = 0.5 * normalized_mda + 0.5 * normalized_mdi
```

**Implementation**:
```python
selector = FeatureSelector()

# Compute both importance measures
mda_scores = selector.compute_mda(model, X_test, y_test, n_repeats=10)
mdi_scores = selector.compute_mdi(model)

# Combine and rank
ranking_df = selector.rank_features(mda_scores, mdi_scores, top_n=30)

print(ranking_df)
#              feature  importance  mda_score  mdi_score
# 0         rsi_14      0.95        0.90      1.00
# 1         volatility_20  0.88    0.82      0.94
# ...
```

**Output**: Top 30 features for training

---

### 6. Optuna Hyperparameter Tuning

**Objective Function**: Maximize **Sortino Ratio** on validation set

**Sortino Ratio**:
```
Sortino = Annual Return / Downside Volatility

Downside Volatility = sqrt(mean(min(returns - target, 0)^2))

Why Sortino?
- Penalizes only downside risk (not upside moves)
- Aligns with trader preferences (care about losses, not gains)
- More realistic objective than accuracy
```

**Optimized Hyperparameters**:
```python
params = {
    'objective': 'binary',
    'n_estimators': trial.suggest_int(50, 500),       # Trees
    'max_depth': trial.suggest_int(3, 15),            # Tree depth
    'learning_rate': trial.suggest_float(0.001, 0.1), # Step size
    'num_leaves': trial.suggest_int(20, 100),         # Leaves per tree
    'min_child_samples': trial.suggest_int(5, 50),    # Min samples in leaf
    'subsample': trial.suggest_float(0.5, 1.0),       # Row subsampling
    'colsample_bytree': trial.suggest_float(0.5, 1.0),# Feature subsampling
    'reg_alpha': trial.suggest_float(0.0, 1.0),       # L1 regularization
    'reg_lambda': trial.suggest_float(0.0, 1.0),      # L2 regularization
}
```

**Optuna Workflow**:
1. Sample hyperparameters from distributions
2. Train LightGBM on train fold
3. Predict on validation fold
4. Compute Sortino ratio
5. Update distributions based on performance
6. Repeat for N trials
7. Return best hyperparameters

**Implementation**:
```python
pipeline = MLPipeline(config)
results = pipeline.run_pipeline(df)

# Automatically:
# 1. Engineers features
# 2. Creates labels (triple-barrier)
# 3. Meta-labels
# 4. Selects features (MDA/MDI)
# 5. Runs purged 5-fold CV
# 6. Optimizes hyperparameters with Optuna (30 trials per fold)
# 7. Trains final model

print(f"Final Sortino Ratio: {results['final_sortino']:.4f}")
print(f"Selected Features: {results['selected_features']}")
```

---

## Integration with SuryaDhana

### Step 1: Use Real OHLCV Data
```python
from services.data_service.storage import DuckDBStore

# Load 500 stocks from your DuckDB
store = DuckDBStore('/path/to/market.duckdb')
df = store.get_all_ohlcv()  # ← Replace DataGenerator

pipeline = MLPipeline(config)
results = pipeline.run_pipeline(df)
```

### Step 2: Integrate with Feature Service
```python
# Modify feature-service/main.py to use FeatureEngineer
from ml_quant_pipeline import FeatureEngineer

@app.post("/features/compute")
async def compute_features(req: FeaturesRequest):
    engineer = FeatureEngineer()
    df_features = engineer.engineer_features(req.ohlcv)
    return {"features": df_features.to_dict()}
```

### Step 3: Use Selected Model in ML Service
```python
# Save trained model
import pickle
with open('data/lgb_meta_label_model.pkl', 'wb') as f:
    pickle.dump(results['model'], f)

# Load in ml-service
model = pickle.load(open('data/lgb_meta_label_model.pkl', 'rb'))

@app.post("/predict")
async def predict(X: np.ndarray):
    predictions = model.predict(X)
    return {"predictions": predictions}
```

### Step 4: Backtest with Meta-Labels
```python
# Use meta_label predictions in backtest
trades = []
for idx, row in df.iterrows():
    if row['meta_label'] == 1:  # Only execute if meta-label says trust signal
        trades.append({
            'ticker': row['ticker'],
            'entry_date': row['date'],
            'entry_price': row['close'],
            'expected_return': row['return_pct'],
        })

# Run backtest on filtered trades
backtest_results = backtest(trades)
```

---

## Complete Usage Example

### Basic Execution
```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ml_quant_pipeline.py
```

### Custom Configuration
```python
from scripts.ml_quant_pipeline import MLPipeline, PipelineConfig, DataGenerator

# Configure
config = PipelineConfig(
    n_stocks=500,
    lookback_window=252,
    holding_period=5,
    atr_window=20,
    atr_multiplier_up=1.5,  # Adjust barriers
    atr_multiplier_down=1.0,
    min_return_threshold=0.005,
)

# Generate data
gen = DataGenerator(n_stocks=500, n_days=1500)
df = gen.generate()

# Run pipeline
pipeline = MLPipeline(config)
results = pipeline.run_pipeline(df)

# Access results
model = results['model']
selected_features = results['selected_features']
final_sortino = results['final_sortino']
feature_ranking = results['feature_ranking']
cv_results = results['cv_results']
```

### Extracting Results
```python
# Feature importance
print(results['feature_ranking'].head(20))

# Cross-validation metrics
print(f"CV Accuracy Mean: {np.mean(results['cv_results']['fold_accuracies']):.4f}")
print(f"CV Accuracy Std: {np.std(results['cv_results']['fold_accuracies']):.4f}")

# Make predictions on new data
new_predictions = results['model'].predict(new_features)

# Save selected features for feature-service
with open('selected_features.txt', 'w') as f:
    f.write('\n'.join(results['selected_features']))
```

---

## Hyperparameter Tuning Details

### Why Optuna?
- **Bayesian Optimization**: Uses previous trials to guide sampling
- **Pruning**: Stops unpromising trials early
- **Multi-objective**: Can optimize multiple metrics
- **Flexible**: Works with any objective function

### Tuning Loop (Per Fold)
```
Fold 1 (Train: 80%, Val: 20%)
├─ Trial 1: n_estimators=150, max_depth=8, lr=0.05 → Sortino=0.82
├─ Trial 2: n_estimators=300, max_depth=10, lr=0.02 → Sortino=0.95
├─ Trial 3: n_estimators=250, max_depth=7, lr=0.03 → Sortino=0.91
├─ ...
└─ Trial 30: Best params → Sortino=1.23

Fold 2 (Train: 80%, Val: 20%)
├─ Trial 1: ... (guided by Fold 1 results)
└─ Trial 30: Best params → Sortino=1.18

...

Final Model: Train on all folds with best overall params
```

### Sortino Ratio Calculation
```python
returns = array of daily returns from predictions
target_return = 0.0  # Target (usually 0)

downside_returns = [min(r - target, 0) for r in returns]
downside_vol = sqrt(mean(downside_returns^2))

annual_return = mean(returns) * 252
sortino = annual_return / downside_vol
```

---

## Output Files

After running the pipeline, saved to `/data/`:

1. **lgb_meta_label_model.pkl**
   - Trained LightGBM model
   - Loaded with: `pickle.load(open(...))`
   - Predicts meta-labels (1=execute, 0=skip)

2. **feature_ranking.csv**
   - Top 30 features with scores
   - Columns: feature, importance, mda_score, mdi_score
   - Use for feature-service configuration

3. **selected_features.txt**
   - List of selected feature names
   - One per line
   - Use for feature selection in production

---

## Performance Expectations

Typical performance on synthetic/real data:

| Metric | Typical Range |
|--------|---------------|
| CV Accuracy | 52-58% |
| CV Precision | 55-65% |
| CV Recall | 40-55% |
| CV F1-Score | 45-55% |
| Final Sortino Ratio | 0.8-1.5 |
| Win Rate (execution signals) | 50-60% |

**Note**: Actual performance depends on:
- Market regime (trending vs. mean-reverting)
- Feature quality
- Hyperparameter tuning
- Data quality
- Out-of-sample period

---

## Advanced Customization

### 1. Custom Triple-Barrier Parameters
```python
labeler = TripleBarrierLabeler(
    atr_window=14,              # Shorter lookback
    atr_multiplier_up=2.0,      # More conservative profit target
    atr_multiplier_down=0.5,    # Tighter stop-loss
    holding_period=10,          # Longer holding
)
```

### 2. Custom Feature Set
```python
# Add custom features before feature selection
df['custom_feature'] = ...
df['another_feature'] = ...

# Exclude from feature selection
exclude_cols.append('custom_feature')
```

### 3. Custom Primary Signal (Meta-Labeling)
```python
# In MetaLabeler.compute_primary_signal()
# Replace trend-following with your signal:
# - Mean-reversion: price below 20-day SMA
# - Volatility: return > 2*std
# - Correlation: price correlated with sector
```

### 4. Different Optimization Metric
```python
# Change from Sortino to Sharpe:
def objective(trial):
    ...
    sharpe = PerformanceMetrics.compute_sharpe_ratio(pred_returns)
    return sharpe
```

---

## Troubleshooting

### Issue: High CV variance (accuracy fluctuates)
**Cause**: Features too noisy or insufficient data
**Solution**: 
- Increase embargo_pct to 0.05
- Reduce feature count (select top 15 instead of 30)
- Increase atr_window (20 → 30)

### Issue: Low Sortino ratio despite high accuracy
**Cause**: Predictions align with high-return periods only
**Solution**:
- Decrease min_return_threshold
- Use different primary signal (meta-labeling)
- Increase atr_multiplier to widen barriers

### Issue: Script runs out of memory
**Cause**: 500 stocks × 1000 days = 500K rows
**Solution**:
- Reduce n_stocks to 100-200
- Reduce n_days to 500-750
- Run feature selection on random sample

---

## References

**Core Concepts**:
- De Prado, M. L. (2018). *Advances in Financial Machine Learning*
- Prado & Fabozzi (2020). *Machine Learning for Asset Managers*

**Methods**:
- Triple-Barrier: de Prado, Chapter 3
- Meta-Labeling: de Prado, Chapter 4
- Purged CV: de Prado, Chapter 7
- Feature Selection: Scikit-learn Inspection API

**Libraries**:
- [LightGBM](https://lightgbm.readthedocs.io/)
- [Optuna](https://optuna.readthedocs.io/)
- [Scikit-learn](https://scikit-learn.org/)

---

## Version & Support

**Version**: 1.0.0  
**Last Updated**: 2026-05-24  
**Python**: 3.9+  
**Dependencies**: lightgbm, optuna, scikit-learn, pandas, numpy

