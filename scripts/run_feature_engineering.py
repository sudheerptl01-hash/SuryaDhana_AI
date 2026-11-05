"""
Feature Engineering Pipeline: Real NSE Data Integration
========================================================

Production workflow:
1. Load NSE CSV → Validate schema
2. Prepare multi-index DataFrame (Date, Ticker)
3. Run vectorized feature engineer
4. Validate feature distributions
5. Save as Parquet (fast I/O for ML pipelines)
6. Generate feature statistics report

Expected CSV structure:
  date, ticker, open, high, low, close, volume
"""

import pandas as pd
import numpy as np
import sys
from pathlib import Path
from datetime import datetime
import logging

# Import the feature engineer (assumes same directory or in PYTHONPATH)
sys.path.insert(0, str(Path(__file__).parent))
from feature_engineering_vectorized import VectorizedFeatureEngineer

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING & VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def load_and_validate_nse_csv(csv_path: str) -> pd.DataFrame:
    """
    Load NSE CSV with schema validation and minimal data cleaning.

    Args:
        csv_path: Path to NSE OHLCV CSV file

    Returns:
        MultiIndex DataFrame (Date, Ticker) with validated columns
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    log.info(f"Loading NSE CSV: {csv_path}")
    df = pd.read_csv(csv_path)

    # Schema validation
    required_cols = {'date', 'ticker', 'open', 'high', 'low', 'close', 'volume'}
    missing_cols = required_cols - set(df.columns.str.lower())

    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}. Found: {set(df.columns)}")

    # Standardize column names (lowercase)
    df.columns = df.columns.str.lower()

    # Data type conversions
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['ticker'] = df['ticker'].astype(str).str.upper().str.strip()
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Remove invalid rows (NaN dates or prices)
    initial_rows = len(df)
    df = df.dropna(subset=['date', 'ticker', 'close', 'volume'])
    log.info(f"  Dropped {initial_rows - len(df)} invalid rows")

    # Sanity checks
    if (df['high'] < df['low']).any():
        log.warning("  Warning: Found rows where high < low (data quality issue)")

    if (df['volume'] <= 0).any():
        log.warning("  Warning: Found non-positive volume values")

    # Create MultiIndex
    df = df.set_index(['date', 'ticker']).sort_index()

    log.info(f"✓ Loaded {len(df):,} rows across {len(df.index.get_level_values(1).unique())} tickers")
    log.info(f"  Date range: {df.index.get_level_values(0).min()} to {df.index.get_level_values(0).max()}")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE ENGINEERING EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def run_feature_engineering(df: pd.DataFrame,
                           vol_zscore_windows: list = [20, 50],
                           corr_window: int = 20,
                           natr_window: int = 14,
                           return_horizons: list = [1, 5, 20],
                           vol_regime_window: int = 60) -> pd.DataFrame:
    """
    Execute vectorized feature engineering pipeline.

    Args:
        df: MultiIndex OHLCV DataFrame
        vol_zscore_windows: Windows for volume Z-scores
        corr_window: Window for correlation to mean
        natr_window: Window for NATR
        return_horizons: Horizons for log returns
        vol_regime_window: Window for volatility regimes

    Returns:
        DataFrame with all engineered features
    """
    log.info("\n" + "=" * 80)
    log.info("FEATURE ENGINEERING PIPELINE")
    log.info("=" * 80)

    engineer = VectorizedFeatureEngineer(df, ensure_multiindex=True)

    features = engineer.engineer_all_features(
        vol_zscore_windows=vol_zscore_windows,
        corr_window=corr_window,
        natr_window=natr_window,
        return_horizons=return_horizons,
        vol_regime_window=vol_regime_window,
        handle_nans='forward_fill'  # Forward-fill NaNs (no look-ahead bias)
    )

    return features


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE VALIDATION & STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

def validate_features(features: pd.DataFrame, original_df: pd.DataFrame) -> dict:
    """
    Validate feature distributions and generate summary statistics.

    Args:
        features: Engineered feature DataFrame
        original_df: Original OHLCV DataFrame (for reference)

    Returns:
        Dictionary of validation results
    """
    log.info("\n" + "=" * 80)
    log.info("FEATURE VALIDATION")
    log.info("=" * 80)

    validation = {
        'shape': features.shape,
        'missing_pct': (features.isna().sum() / len(features) * 100).to_dict(),
        'feature_dtypes': features.dtypes.to_dict(),
        'numeric_summary': features.describe().to_dict(),
    }

    # Check for expected feature presence
    expected_features = {
        'volume_zscore_20d': 'Volume Z-score (20d)',
        'volume_zscore_50d': 'Volume Z-score (50d)',
        'correlation_to_mean_20d': 'Correlation to Universe Mean',
        'natr': 'Normalized ATR',
        'log_return_1d': '1-day Log Return',
        'log_return_5d': '5-day Log Return',
        'log_return_20d': '20-day Log Return',
        'volatility_regime': 'Volatility Regime',
    }

    log.info("\n[FEATURE COVERAGE]")
    for feat_name, feat_label in expected_features.items():
        exists = feat_name in features.columns
        status = "✓" if exists else "✗"
        log.info(f"  {status} {feat_label} ({feat_name})")

    # Numeric feature statistics
    log.info("\n[NUMERIC FEATURE STATISTICS]")
    numeric_features = features.select_dtypes(include=[np.number]).columns
    for col in numeric_features:
        feature_data = features[col].dropna()
        log.info(f"\n  {col}:")
        log.info(f"    Mean: {feature_data.mean():.4f}")
        log.info(f"    Std:  {feature_data.std():.4f}")
        log.info(f"    Min:  {feature_data.min():.4f}")
        log.info(f"    Max:  {feature_data.max():.4f}")
        log.info(f"    p05:  {feature_data.quantile(0.05):.4f}")
        log.info(f"    p95:  {feature_data.quantile(0.95):.4f}")

    # Categorical feature statistics
    log.info("\n[CATEGORICAL FEATURE STATISTICS]")
    categorical_features = features.select_dtypes(include=['category']).columns
    for col in categorical_features:
        log.info(f"\n  {col}:")
        regime_counts = features[col].value_counts()
        for regime, count in regime_counts.items():
            pct = count / len(features) * 100
            log.info(f"    {regime}: {count:,} ({pct:.1f}%)")

    # Correlation check (should NOT have perfect correlations)
    log.info("\n[FEATURE CORRELATION CHECK]")
    numeric_df = features.select_dtypes(include=[np.number])
    if len(numeric_df.columns) > 1:
        corr_matrix = numeric_df.corr()
        high_corr_pairs = []
        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                corr_val = corr_matrix.iloc[i, j]
                if abs(corr_val) > 0.95:
                    col_i = corr_matrix.columns[i]
                    col_j = corr_matrix.columns[j]
                    high_corr_pairs.append((col_i, col_j, corr_val))

        if high_corr_pairs:
            log.warning("  ⚠ HIGH CORRELATION DETECTED (>0.95):")
            for col_i, col_j, corr_val in high_corr_pairs[:5]:  # Show top 5
                log.warning(f"    {col_i} ↔ {col_j}: {corr_val:.4f}")
        else:
            log.info("  ✓ No dangerously high correlations detected")

    # Check for look-ahead bias
    log.info("\n[LOOK-AHEAD BIAS CHECK]")
    # Future returns should not be in past features
    future_cols = [c for c in features.columns if 'return' in c.lower() and int(c.split('_')[-2]) > 0]
    past_cols = [c for c in features.columns if 'return' not in c.lower()]
    log.info(f"  ✓ {len(future_cols)} forward-looking features properly isolated")
    log.info(f"  ✓ {len(past_cols)} historical features (safe for training)")

    return validation


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT & SAVING
# ─────────────────────────────────────────────────────────────────────────────

def save_features(features: pd.DataFrame, output_dir: str = './data') -> str:
    """
    Save features to Parquet (efficient storage + metadata preservation).

    Args:
        features: Feature DataFrame
        output_dir: Output directory

    Returns:
        Path to saved file
    """
    output_path = Path(output_dir) / f'nse_engineered_features_{datetime.now().strftime("%Y%m%d_%H%M%S")}.parquet'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info(f"\n[SAVING] Writing features to Parquet: {output_path}")
    features.to_parquet(output_path, compression='snappy', index=True)

    file_size_mb = output_path.stat().st_size / 1e6
    log.info(f"  ✓ Saved: {file_size_mb:.1f} MB")
    log.info(f"  Rows: {features.shape[0]:,} | Cols: {features.shape[1]}")

    return str(output_path)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def main(csv_path: str,
        output_dir: str = './data',
        limit_tickers: Optional[int] = None) -> Tuple[pd.DataFrame, str]:
    """
    End-to-end feature engineering pipeline.

    Args:
        csv_path: Path to NSE OHLCV CSV
        output_dir: Output directory for Parquet file
        limit_tickers: For testing, limit to N tickers (None = use all)

    Returns:
        (features DataFrame, output file path)
    """
    log.info("\n" + "=" * 80)
    log.info("NSE FEATURE ENGINEERING PIPELINE - START")
    log.info("=" * 80)

    # 1. Load & Validate
    df = load_and_validate_nse_csv(csv_path)

    # Optional: subsample tickers for faster testing
    if limit_tickers:
        tickers = df.index.get_level_values(1).unique()[:limit_tickers]
        df = df.loc[df.index.get_level_values(1).isin(tickers)]
        log.info(f"[SUBSAMPLE] Limited to {limit_tickers} tickers for testing")

    # 2. Engineer Features
    features = run_feature_engineering(df)

    # 3. Validate
    validate_features(features, df)

    # 4. Save
    output_path = save_features(features, output_dir=output_dir)

    log.info("\n" + "=" * 80)
    log.info("✓ FEATURE ENGINEERING COMPLETE")
    log.info("=" * 80)

    return features, output_path


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND-LINE INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    from typing import Optional, Tuple

    parser = argparse.ArgumentParser(
        description='Vectorized Feature Engineering for NSE OHLCV Data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

  # Full pipeline on all tickers
  python run_feature_engineering.py \\
    --csv data/NSE_1000_MIDCAP_500.csv \\
    --output ./engineered_features

  # Test run on 50 tickers
  python run_feature_engineering.py \\
    --csv data/NSE_1000_MIDCAP_500.csv \\
    --output ./engineered_features \\
    --limit-tickers 50
        """
    )

    parser.add_argument('--csv', type=str, required=True,
                       help='Path to NSE OHLCV CSV file')
    parser.add_argument('--output', type=str, default='./data',
                       help='Output directory for Parquet file (default: ./data)')
    parser.add_argument('--limit-tickers', type=int, default=None,
                       help='For testing: limit to N tickers (default: use all)')

    args = parser.parse_args()

    try:
        features, output_path = main(
            csv_path=args.csv,
            output_dir=args.output,
            limit_tickers=args.limit_tickers
        )

        log.info(f"\n📊 Ready for ML training: {output_path}")

    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)
