"""
ML Quant Pipeline - Quick Start Example

Demonstrates immediate usage of the complete pipeline with explanatory output.
"""

import numpy as np
import pandas as pd
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ml_quant_pipeline import (
    PipelineConfig,
    DataGenerator,
    TripleBarrierLabeler,
    FeatureEngineer,
    MetaLabeler,
    PurgedKFoldCV,
    PerformanceMetrics,
    MLPipeline,
)


def example_1_triple_barrier():
    """Example 1: Understanding Triple-Barrier Labeling"""
    print("\n" + "="*80)
    print("EXAMPLE 1: TRIPLE-BARRIER METHOD")
    print("="*80)

    # Generate minimal data
    dates = pd.date_range('2023-01-01', periods=100, freq='D')
    data = []
    close = 100.0

    for i, date in enumerate(dates):
        daily_ret = np.random.normal(0.0005, 0.02)
        close = close * (1 + daily_ret)
        data.append({
            'date': date,
            'ticker': 'TEST',
            'stock_id': 0,
            'open': close * 0.99,
            'high': close * 1.02,
            'low': close * 0.98,
            'close': close,
            'volume': 1000000,
        })

    df = pd.DataFrame(data)

    # Apply triple-barrier labeling
    labeler = TripleBarrierLabeler(
        atr_window=20,
        atr_multiplier_up=1.0,
        atr_multiplier_down=1.0,
        holding_period=5,
    )

    df_labeled = labeler.label_signals(df)

    # Display results
    print("\nSample of labeled data:")
    print(df_labeled[['date', 'close', 'atr', 'barrier_up', 'barrier_down', 'label', 'return_pct']].head(30))

    print(f"\nLabel distribution:")
    print(df_labeled['label'].value_counts())

    print(f"\nAverage return per label:")
    for label in [-1, 0, 1]:
        avg_ret = df_labeled[df_labeled['label'] == label]['return_pct'].mean()
        print(f"  Label {label:2d}: {avg_ret:7.4f}")


def example_2_feature_engineering():
    """Example 2: Feature Engineering"""
    print("\n" + "="*80)
    print("EXAMPLE 2: FEATURE ENGINEERING")
    print("="*80)

    # Generate synthetic data
    generator = DataGenerator(n_stocks=10, n_days=500, random_state=42)
    df = generator.generate()

    # Engineer features
    print(f"\nInput data: {df.shape[0]} rows, {df.shape[1]} columns")

    engineer = FeatureEngineer()
    df_features = engineer.engineer_features(df)

    print(f"Output data: {df_features.shape[0]} rows, {df_features.shape[1]} columns")

    # List features
    feature_cols = [col for col in df_features.columns if col not in
                    ['date', 'ticker', 'stock_id', 'open', 'high', 'low', 'close', 'volume']]

    print(f"\n✓ Engineered {len(feature_cols)} features:")
    for i, feat in enumerate(feature_cols, 1):
        print(f"  {i:2d}. {feat}")

    # Show sample values
    print("\nSample feature values (first 3 rows):")
    print(df_features[['date', 'close'] + feature_cols[:10]].head(3))


def example_3_meta_labeling():
    """Example 3: Meta-Labeling"""
    print("\n" + "="*80)
    print("EXAMPLE 3: META-LABELING")
    print("="*80)

    # Generate data
    generator = DataGenerator(n_stocks=5, n_days=300, random_state=42)
    df = generator.generate()

    # Apply triple-barrier labeling
    labeler = TripleBarrierLabeler(holding_period=5)
    df = labeler.label_signals(df)

    # Compute primary signal
    df['primary_signal'] = MetaLabeler.compute_primary_signal(df, lookback=20)

    # Create meta-labels
    df['meta_label'] = MetaLabeler.create_meta_labels(df)

    # Analysis
    print("\nCrosstab: Primary Signal vs Actual Outcome")
    crosstab = pd.crosstab(
        df['primary_signal'],
        df['label'],
        margins=True
    )
    print(crosstab)

    print("\nMeta-Label Distribution:")
    print(f"  Meta-label 1 (trust signal):  {(df['meta_label'] == 1).sum()} ({100*(df['meta_label'] == 1).mean():.1f}%)")
    print(f"  Meta-label 0 (ignore signal): {(df['meta_label'] == 0).sum()} ({100*(df['meta_label'] == 0).mean():.1f}%)")

    print("\nPrimary signal accuracy (when it should be trusted):")
    meta_1_data = df[df['meta_label'] == 1]
    if len(meta_1_data) > 0:
        accuracy = ((meta_1_data['primary_signal'] == (meta_1_data['label'] > 0).astype(int)).mean())
        print(f"  Accuracy: {accuracy:.2%}")


def example_4_purged_cv():
    """Example 4: Purged Cross-Validation"""
    print("\n" + "="*80)
    print("EXAMPLE 4: PURGED & EMBARGOED CROSS-VALIDATION")
    print("="*80)

    # Generate data
    n_samples = 1000
    dates = pd.date_range('2022-01-01', periods=n_samples, freq='D')
    X = pd.DataFrame({
        'date': dates,
        'feature_1': np.random.randn(n_samples),
        'feature_2': np.random.randn(n_samples),
    })

    # Purged CV
    cv = PurgedKFoldCV(n_splits=5, embargo_pct=0.01)

    print(f"\nData: {len(X)} samples over {(X['date'].max() - X['date'].min()).days} days")
    print(f"Embargo: {int(len(X) * 0.01)} samples (~1%)")

    fold_num = 1
    for train_idx, test_idx in cv.split(X):
        train_dates = X.iloc[train_idx]['date']
        test_dates = X.iloc[test_idx]['date']

        print(f"\nFold {fold_num}:")
        print(f"  Train: {len(train_idx)} samples, {train_dates.min().date()} to {train_dates.max().date()}")
        print(f"  Test:  {len(test_idx)} samples, {test_dates.min().date()} to {test_dates.max().date()}")
        print(f"  Overlap: {len(set(train_dates.dt.date) & set(test_dates.dt.date))} days (should be 0)")

        fold_num += 1


def example_5_full_pipeline():
    """Example 5: Complete Pipeline Execution"""
    print("\n" + "="*80)
    print("EXAMPLE 5: COMPLETE PIPELINE (QUICK VERSION)")
    print("="*80)

    # Configuration (reduced for speed)
    config = PipelineConfig(
        n_stocks=50,  # Reduced from 500 for demo
        lookback_window=252,
        holding_period=5,
        atr_window=20,
    )

    # Generate data
    print(f"\n[Step 1/6] Generating data for {config.n_stocks} stocks...")
    generator = DataGenerator(n_stocks=config.n_stocks, n_days=500, random_state=42)
    df = generator.generate()
    print(f"✓ Generated: {df.shape[0]} rows × {df.shape[1]} columns")

    # Run pipeline
    pipeline = MLPipeline(config)
    print(f"\n[Step 2/6] Preparing data...")
    X, y, df_full = pipeline.prepare_data(df)
    print(f"✓ Features: {X.shape[1]}, Labels: {y.value_counts().to_dict()}")

    # Feature selection
    print(f"\n[Step 3/6] Selecting top features (MDA/MDI)...")
    selected_features, ranking_df = pipeline.select_features_with_mda_mdi(X, y, n_top=20)
    print(f"✓ Selected: {len(selected_features)} features")

    # Show top 10
    print("\nTop 10 features:")
    print(ranking_df.head(10).to_string(index=False))

    # Purged CV (simplified)
    print(f"\n[Step 4/6] Purged cross-validation (demo)...")
    X_selected = X[selected_features]
    cv = PurgedKFoldCV(n_splits=2, embargo_pct=0.01)

    fold = 1
    cv_scores = []
    for train_idx, test_idx in cv.split(X_selected.reset_index(drop=True).assign(date=df_full['date'].values)):
        print(f"  Fold {fold}: Train={len(train_idx)}, Test={len(test_idx)}")
        # In production, would train model here
        fold += 1

    print(f"✓ Cross-validation ready for model training")

    print("\n" + "="*80)
    print("PIPELINE DEMONSTRATION COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("  1. Run full pipeline: ml_quant_pipeline.py")
    print("  2. Review feature ranking in data/feature_ranking.csv")
    print("  3. Load trained model from data/lgb_meta_label_model.pkl")
    print("  4. Integrate with SuryaDhana feature-service")
    print("  5. Backtest trades filtered by meta-label predictions")


def main():
    """Run all examples."""
    print("\n" + "="*80)
    print("ML QUANT PIPELINE - QUICK START EXAMPLES")
    print("="*80)

    example_1_triple_barrier()
    example_2_feature_engineering()
    example_3_meta_labeling()
    example_4_purged_cv()
    example_5_full_pipeline()

    print("\n" + "="*80)
    print("✓ ALL EXAMPLES COMPLETE")
    print("="*80)
    print("\nDocumentation: docs/ML_QUANT_PIPELINE_GUIDE.md")
    print("Full pipeline: scripts/ml_quant_pipeline.py")


if __name__ == '__main__':
    main()
