# ML Quant Pipeline — Quick Reference

Fast lookup for common tasks and configuration patterns.

---

## One-Liners

### Run with default config (500 stocks, 1000 days)
```bash
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ml_quant_pipeline.py
```

### Run examples (5 demonstrations, 2 min)
```bash
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/pipeline_quickstart.py
```

### Run with real DuckDB data
```python
from services.data_service.storage import DuckDBStore
from scripts.ml_quant_pipeline import MLPipeline, PipelineConfig

store = DuckDBStore('/data/market.duckdb')
df = store.get_all_ohlcv()

pipeline = MLPipeline(PipelineConfig(n_stocks=500))
results = pipeline.run_pipeline(df)
```

### Load trained model
```python
import pickle
model = pickle.load(open('data/lgb_meta_label_model.pkl', 'rb'))
predictions = model.predict(X_test)
```

---

## Configuration Snippets

### Conservative (low risk)
```python
config = PipelineConfig(
    atr_multiplier_up=2.0,      # Wider profit target
    atr_multiplier_down=0.5,    # Tight stop
    holding_period=10,          # Longer hold
    min_return_threshold=0.005, # Higher min profit
)
```

### Aggressive (high reward)
```python
config = PipelineConfig(
    atr_multiplier_up=0.8,      # Tight profit target
    atr_multiplier_down=1.5,    # Loose stop
    holding_period=3,           # Quick exit
    min_return_threshold=0.0001,# Lower min profit
)
```

### Mean-Reversion (inverse signal)
```python
# In MetaLabeler.compute_primary_signal()
# Replace: signal = (df['close'] > df['sma']).astype(int)
# With:    signal = (df['close'] < df['sma']).astype(int)
```

---

## Feature Selection

### See top 20 features
```python
ranking_df = results['feature_ranking']
print(ranking_df.head(20))
```

### Use different top-N
```python
ranking_df = selector.rank_features(mda_scores, mdi_scores, top_n=50)
```

### Export selected features
```python
with open('selected_features.txt', 'w') as f:
    f.write('\n'.join(results['selected_features']))
```

---

## Performance Metrics

### Compute Sortino Ratio
```python
from scripts.ml_quant_pipeline import PerformanceMetrics
sortino = PerformanceMetrics.compute_sortino_ratio(returns)
```

### Compute Sharpe Ratio
```python
sharpe = PerformanceMetrics.compute_sharpe_ratio(returns)
```

### Compute Max Drawdown
```python
cumulative_returns = (1 + returns).cumprod()
max_dd = PerformanceMetrics.compute_max_drawdown(cumulative_returns)
```

### Compute Win Rate
```python
win_rate = PerformanceMetrics.compute_win_rate(labels)
```

---

## Cross-Validation

### 5-fold purged CV
```python
from scripts.ml_quant_pipeline import PurgedKFoldCV

cv = PurgedKFoldCV(n_splits=5, embargo_pct=0.01)
for train_idx, test_idx in cv.split(X.assign(date=df['date'])):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    # train model
```

### 10-fold with 5% embargo
```python
cv = PurgedKFoldCV(n_splits=10, embargo_pct=0.05)
```

---

## Feature Engineering

### Engineer all 40+ features
```python
from scripts.ml_quant_pipeline import FeatureEngineer

engineer = FeatureEngineer()
df_features = engineer.engineer_features(df)  # 40+ new columns
```

### Add custom feature
```python
df['custom_feature'] = df.groupby('stock_id')['close'].apply(...)
```

---

## Triple-Barrier Labeling

### Apply labeling
```python
from scripts.ml_quant_pipeline import TripleBarrierLabeler

labeler = TripleBarrierLabeler(atr_window=20, holding_period=5)
df_labeled = labeler.label_signals(df)
```

### Change parameters
```python
labeler = TripleBarrierLabeler(
    atr_window=30,              # Longer ATR window
    atr_multiplier_up=1.5,      # 1.5 × ATR above entry
    atr_multiplier_down=0.8,    # 0.8 × ATR below entry
    holding_period=10,          # 10-day holding
    min_return_threshold=0.01,  # 1% minimum return
)
```

---

## Meta-Labeling

### Generate meta-labels
```python
from scripts.ml_quant_pipeline import MetaLabeler

df['primary_signal'] = MetaLabeler.compute_primary_signal(df, lookback=20)
df['meta_label'] = MetaLabeler.create_meta_labels(df)
```

### Check meta-label quality
```python
meta_1 = df[df['meta_label'] == 1]
accuracy = (meta_1['primary_signal'] == (meta_1['label'] > 0).astype(int)).mean()
print(f"Meta-signal accuracy: {accuracy:.2%}")
```

---

## Hyperparameter Tuning

### Modify Optuna trials
```python
# In MLPipeline.run_pipeline()
# Change n_trials=50 to n_trials=100 for more thorough search
```

### Custom objective function
```python
def objective(trial):
    params = { ... }
    # ... train and predict
    # Replace sortino with your metric:
    return PerformanceMetrics.compute_sharpe_ratio(returns)
```

### See best params
```python
print(results['params'])
# {'n_estimators': 250, 'max_depth': 10, 'learning_rate': 0.05, ...}
```

---

## Model Deployment

### Save model
```python
import pickle
with open('model.pkl', 'wb') as f:
    pickle.dump(results['model'], f)
```

### Load model
```python
model = pickle.load(open('model.pkl', 'rb'))
```

### Make predictions
```python
predictions = model.predict(X_test)
confidence = model.predict_proba(X_test)[:, 1]
```

### Export ONNX (for production)
```python
import onnx
import onnxmltools
onnx_model = onnxmltools.convert_lightgbm(results['model'])
onnx.save_model(onnx_model, 'model.onnx')
```

---

## Debugging

### Check data dimensions
```python
print(f"Features: {X.shape}")
print(f"Labels: {y.shape}")
print(f"Date range: {df['date'].min()} to {df['date'].max()}")
```

### Check label distribution
```python
print(df['label'].value_counts())
print(df['meta_label'].value_counts())
```

### Check for NaNs
```python
print(X.isna().sum())
print(y.isna().sum())
```

### Check feature importance
```python
print(results['feature_ranking'].head(20))
```

### Check CV metrics
```python
cv_results = results['cv_results']
print(f"Accuracy: {np.mean(cv_results['fold_accuracies']):.4f} ± {np.std(cv_results['fold_accuracies']):.4f}")
print(f"Precision: {np.mean(cv_results['fold_precisions']):.4f}")
print(f"Recall: {np.mean(cv_results['fold_recalls']):.4f}")
print(f"F1: {np.mean(cv_results['fold_f1_scores']):.4f}")
```

---

## Integration Examples

### Use with SuryaDhana feature-service
```python
# services/feature-service/main.py
from scripts.ml_quant_pipeline import FeatureEngineer

engineer = FeatureEngineer()

@app.post("/features")
async def compute_features(df: pd.DataFrame):
    df_engineered = engineer.engineer_features(df)
    return df_engineered.to_json()
```

### Use with SuryaDhana ml-service
```python
# services/ml-service/main.py
import pickle
from scripts.ml_quant_pipeline import FeatureEngineer

model = pickle.load(open('data/lgb_meta_label_model.pkl', 'rb'))
engineer = FeatureEngineer()

@app.post("/predict")
async def predict(df: pd.DataFrame):
    df_engineered = engineer.engineer_features(df)
    selected_features = [...]  # from data/selected_features.txt
    predictions = model.predict(df_engineered[selected_features])
    return {'meta_label': predictions}
```

### Filter trades by meta-label
```python
# In backtesting
for trade in all_trades:
    if trade['meta_label'] == 1:  # Only execute trusted signals
        execute_trade(trade)
```

---

## Performance Tuning

### Speed up feature engineering (skip expensive features)
```python
# Comment out in FeatureEngineer.engineer_features():
# features['returns_skew'] = ...
# features['returns_kurt'] = ...
```

### Reduce memory (fewer stocks or days)
```python
config = PipelineConfig(
    n_stocks=100,      # Instead of 500
    lookback_window=500  # Instead of 1000
)
```

### Parallelize training
```python
# LightGBM automatically uses all cores
# For Optuna, use:
study.optimize(objective, n_trials=50, show_progress_bar=True)
```

---

## Error Handling

### If `ModuleNotFoundError: lightgbm`
```bash
/Users/sudheer/Desktop/jupyter_env/bin/pip install lightgbm
brew install libomp  # On macOS
```

### If `ModuleNotFoundError: optuna`
```bash
/Users/sudheer/Desktop/jupyter_env/bin/pip install optuna
```

### If memory error
```python
# Reduce data size:
df = df[df['stock_id'] < 100]  # Use 100 stocks instead of 500
df = df[df['date'] > '2023-01-01']  # Use recent data only
```

### If slow on CPU
```bash
# Use GPU acceleration (NVIDIA only):
import lightgbm as lgb
params['device_type'] = 'gpu'
params['gpu_device_id'] = 0  # or 1, 2, etc.
```

---

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| Main pipeline | `scripts/ml_quant_pipeline.py` | Core implementation |
| Examples | `scripts/pipeline_quickstart.py` | 5 working examples |
| Guide | `docs/ML_QUANT_PIPELINE_GUIDE.md` | Full documentation |
| Summary | `docs/PIPELINE_DELIVERY_SUMMARY.md` | Delivery summary |
| Quick ref | `docs/PIPELINE_QUICK_REFERENCE.md` | This file |
| Model | `data/lgb_meta_label_model.pkl` | Trained classifier |
| Features | `data/feature_ranking.csv` | Top 30 features |
| Features list | `data/selected_features.txt` | Selected feature names |

---

## Useful Commands

```bash
# Run with output to file
python scripts/ml_quant_pipeline.py | tee output.log

# Profile execution time
time python scripts/ml_quant_pipeline.py

# Check Python version
python --version

# List installed packages
pip list | grep -E "lightgbm|optuna|scikit-learn|pandas"

# View feature ranking
cat data/feature_ranking.csv | column -t -s,

# View selected features
head -20 data/selected_features.txt
```

---

## Summary

| Component | Time to Run | Output |
|-----------|-------------|--------|
| Feature Engineering | 30s | 40+ features |
| Triple-Barrier | 20s | Labels (1, 0, -1) |
| Meta-Labeling | 10s | Meta-labels (0, 1) |
| Feature Selection | 60s | Top 20–30 features |
| Optuna (5 folds × 30 trials) | 15–30 min | Best hyperparameters |
| Final Model | 5s | Trained classifier |
| **Total** | **~20–40 min** | **Production model + metrics** |

---

Last updated: 2026-05-24
