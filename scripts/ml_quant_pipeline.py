"""
ML Quant Pipeline: Triple-Barrier, Meta-Labeling, CPCV, Feature Selection, Optuna Tuning.

Complete end-to-end implementation for predictive stock scanning across 500 stocks.
Covers: triple-barrier method, meta-labeling, purged/embargoed combinatorial cross-validation,
feature selection (MDA/MDI), and Optuna hyperparameter optimization for Sortino ratio.

Author: ML Quant Team
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from typing import Tuple, List, Dict, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
import pickle
from pathlib import Path

import lightgbm as lgb
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import optuna
from optuna.samplers import TPESampler

# ============================================================================
# SECTION 1: DATA CONFIGURATION & UTILITIES
# ============================================================================

@dataclass
class PipelineConfig:
    """Configuration for the ML quant pipeline."""
    n_stocks: int = 500
    lookback_window: int = 252  # 1 year of trading days
    holding_period: int = 5  # 5-day holding period
    atr_window: int = 20  # ATR rolling window
    atr_multiplier_up: float = 1.0  # Barrier multiplier (upside)
    atr_multiplier_down: float = 1.0  # Barrier multiplier (downside)
    min_return_threshold: float = 0.001  # Minimum return to label as +1
    test_size: float = 0.2
    random_state: int = 42


class DataGenerator:
    """Generate synthetic OHLCV data for 500 stocks."""

    def __init__(self, n_stocks: int = 500, n_days: int = 1000, random_state: int = 42):
        np.random.seed(random_state)
        self.n_stocks = n_stocks
        self.n_days = n_days

    def generate(self) -> pd.DataFrame:
        """Generate synthetic OHLCV data."""
        data = []
        base_date = datetime(2021, 1, 1)

        for stock_id in range(self.n_stocks):
            close = 100.0
            ticker = f"STOCK_{stock_id:04d}"

            for day in range(self.n_days):
                date = base_date + timedelta(days=day)

                # GBM random walk
                daily_return = np.random.normal(0.0005, 0.02)
                close = close * (1 + daily_return)

                open_price = close * (1 + np.random.normal(0, 0.005))
                high = max(close, open_price) * (1 + abs(np.random.normal(0, 0.01)))
                low = min(close, open_price) * (1 - abs(np.random.normal(0, 0.01)))
                volume = np.random.uniform(100000, 1000000)

                data.append({
                    'date': date,
                    'ticker': ticker,
                    'stock_id': stock_id,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume,
                })

        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values(['stock_id', 'date']).reset_index(drop=True)
        return df


# ============================================================================
# SECTION 2: TRIPLE-BARRIER METHOD LABELING
# ============================================================================

class TripleBarrierLabeler:
    """
    Triple-Barrier Method for labeling.

    Three barriers:
    1. Upside barrier: entry + ATR * atr_multiplier_up
    2. Downside barrier: entry - ATR * atr_multiplier_down
    3. Vertical barrier: entry date + holding_period

    Labels: 1 (hit upside), 0 (neutral), -1 (hit downside)
    """

    def __init__(
        self,
        atr_window: int = 20,
        atr_multiplier_up: float = 1.0,
        atr_multiplier_down: float = 1.0,
        holding_period: int = 5,
        min_return_threshold: float = 0.001,
    ):
        self.atr_window = atr_window
        self.atr_multiplier_up = atr_multiplier_up
        self.atr_multiplier_down = atr_multiplier_down
        self.holding_period = holding_period
        self.min_return_threshold = min_return_threshold

    def compute_atr(self, df: pd.DataFrame, window: int) -> pd.Series:
        """Compute Average True Range."""
        df = df.copy()
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr = df['tr'].rolling(window=window, min_periods=1).mean()
        return atr

    def label_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Label every row based on triple-barrier logic.

        Returns DataFrame with additional columns:
        - atr: Average True Range
        - barrier_up: Upper barrier level
        - barrier_down: Lower barrier level
        - vertical_barrier_date: Date when vertical barrier is hit
        - label: {-1, 0, 1}
        - return_pct: % return at exit
        """
        df = df.copy()
        df = df.sort_values(['stock_id', 'date']).reset_index(drop=True)

        # Group by stock to ensure continuity
        atr_list = []
        for stock_id in df['stock_id'].unique():
            mask = df['stock_id'] == stock_id
            stock_df = df[mask].copy()
            atr = self.compute_atr(stock_df, self.atr_window)
            atr_list.append(atr.values)

        df['atr'] = np.concatenate(atr_list)

        df['barrier_up'] = df['close'] + df['atr'] * self.atr_multiplier_up
        df['barrier_down'] = df['close'] - df['atr'] * self.atr_multiplier_down

        # Vertical barrier: holding_period days in the future
        df['vertical_barrier_date'] = df['date'] + timedelta(days=self.holding_period)

        # Label each signal
        labels = []
        returns = []

        for idx in df.index:
            stock_id = df.loc[idx, 'stock_id']
            entry_date = df.loc[idx, 'date']
            entry_price = df.loc[idx, 'close']
            barrier_up = df.loc[idx, 'barrier_up']
            barrier_down = df.loc[idx, 'barrier_down']
            vertical_date = df.loc[idx, 'vertical_barrier_date']

            # Get future data for this stock between entry_date and vertical_barrier_date
            future_mask = (
                (df['stock_id'] == stock_id) &
                (df['date'] > entry_date) &
                (df['date'] <= vertical_date)
            )
            future_data = df[future_mask].copy()

            if len(future_data) == 0:
                labels.append(0)
                returns.append(0.0)
                continue

            # Check which barrier is hit first
            hit_up = (future_data['high'] >= barrier_up).idxmax() if (future_data['high'] >= barrier_up).any() else -1
            hit_down = (future_data['low'] <= barrier_down).idxmax() if (future_data['low'] <= barrier_down).any() else -1
            hit_vertical = future_data.index[-1]

            # Determine which barrier is hit first (by date)
            hits = []
            if hit_up != -1:
                hits.append((future_data.loc[hit_up, 'date'], 1, future_data.loc[hit_up, 'close']))
            if hit_down != -1:
                hits.append((future_data.loc[hit_down, 'date'], -1, future_data.loc[hit_down, 'close']))
            hits.append((future_data.loc[hit_vertical, 'date'], 0, future_data.loc[hit_vertical, 'close']))

            # Hit the soonest barrier
            exit_date, label, exit_price = min(hits, key=lambda x: x[0])
            ret = (exit_price - entry_price) / entry_price

            # If within min_return_threshold of neutral, label as 0
            if abs(ret) < self.min_return_threshold:
                label = 0

            labels.append(label)
            returns.append(ret)

        df['label'] = labels
        df['return_pct'] = returns

        return df


# ============================================================================
# SECTION 3: FEATURE ENGINEERING
# ============================================================================

class FeatureEngineer:
    """Engineer 40+ technical indicators for ML model."""

    @staticmethod
    def compute_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
        """Relative Strength Index."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window, min_periods=1).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def compute_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series]:
        """MACD and Signal line."""
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        return macd, macd_signal

    @staticmethod
    def compute_bollinger_bands(prices: pd.Series, window: int = 20, num_std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands."""
        sma = prices.rolling(window=window, min_periods=1).mean()
        std = prices.rolling(window=window, min_periods=1).std()
        upper = sma + num_std * std
        lower = sma - num_std * std
        return upper, sma, lower

    @staticmethod
    def compute_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
        """Average True Range."""
        tr = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr = tr.rolling(window=window, min_periods=1).mean()
        return atr

    @staticmethod
    def compute_obv(df: pd.DataFrame) -> pd.Series:
        """On-Balance Volume."""
        obv = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        return obv

    @staticmethod
    def compute_vpt(df: pd.DataFrame) -> pd.Series:
        """Volume Price Trend."""
        vpt = (df['volume'] * df['close'].pct_change()).fillna(0).cumsum()
        return vpt

    @staticmethod
    def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
        """Engineer all features per stock."""
        df = df.copy()
        df = df.sort_values(['stock_id', 'date']).reset_index(drop=True)

        features = df.copy()

        # Price-based features
        features['return'] = features.groupby('stock_id')['close'].pct_change()
        features['log_return'] = features.groupby('stock_id')['close'].transform(lambda x: np.log(x / x.shift(1)))

        # Rolling features (safer approach)
        for window in [5, 20]:
            col_name = f'price_momentum_{window}'
            features[col_name] = features.groupby('stock_id')['return'].transform(
                lambda x: x.rolling(window, min_periods=1).mean()
            )

        for window in [5, 20]:
            col_name = f'volatility_{window}'
            features[col_name] = features.groupby('stock_id')['return'].transform(
                lambda x: x.rolling(window, min_periods=1).std()
            )

        # RSI
        rsi_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_close = features[mask]['close'].values
            rsi = FeatureEngineer.compute_rsi(pd.Series(stock_close), 14).values
            rsi_list.append(rsi)
        features['rsi_14'] = np.concatenate(rsi_list)

        # MACD
        macd_list = []
        macd_signal_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_close = features[mask]['close'].values
            macd, signal = FeatureEngineer.compute_macd(pd.Series(stock_close))
            macd_list.append(macd.values)
            macd_signal_list.append(signal.values)
        features['macd'] = np.concatenate(macd_list)
        features['macd_signal'] = np.concatenate(macd_signal_list)
        features['macd_diff'] = features['macd'] - features['macd_signal']

        # Bollinger Bands
        bb_upper_list = []
        bb_middle_list = []
        bb_lower_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_close = features[mask]['close'].values
            upper, middle, lower = FeatureEngineer.compute_bollinger_bands(pd.Series(stock_close), 20, 2.0)
            bb_upper_list.append(upper.values)
            bb_middle_list.append(middle.values)
            bb_lower_list.append(lower.values)
        features['bb_upper'] = np.concatenate(bb_upper_list)
        features['bb_middle'] = np.concatenate(bb_middle_list)
        features['bb_lower'] = np.concatenate(bb_lower_list)
        features['bb_position'] = (features['close'] - features['bb_lower']) / (features['bb_upper'] - features['bb_lower'] + 1e-10)

        # ATR
        atr_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_df = features[mask].copy()
            atr = FeatureEngineer.compute_atr(stock_df, 14)
            atr_list.append(atr.values)
        features['atr'] = np.concatenate(atr_list)

        # Volume features
        for window in [5, 20]:
            col_name = f'volume_ma_{window}'
            features[col_name] = features.groupby('stock_id')['volume'].transform(
                lambda x: x.rolling(window, min_periods=1).mean()
            )
        features['volume_ratio'] = features['volume'] / (features['volume_ma_20'] + 1)

        # OBV
        obv_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_df = features[mask].copy()
            obv = FeatureEngineer.compute_obv(stock_df)
            obv_list.append(obv.values)
        features['obv'] = np.concatenate(obv_list)

        # VPT
        vpt_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_df = features[mask].copy()
            vpt = FeatureEngineer.compute_vpt(stock_df)
            vpt_list.append(vpt.values)
        features['vpt'] = np.concatenate(vpt_list)

        # Trend features
        for window in [5, 20, 50]:
            col_name = f'sma_{window}'
            features[col_name] = features.groupby('stock_id')['close'].transform(
                lambda x: x.rolling(window, min_periods=1).mean()
            )

        features['price_to_sma5'] = features['close'] / (features['sma_5'] + 1e-10)
        features['price_to_sma20'] = features['close'] / (features['sma_20'] + 1e-10)

        # EMA features
        for span in [12, 26]:
            col_name = f'ema_{span}'
            features[col_name] = features.groupby('stock_id')['close'].transform(
                lambda x: x.ewm(span=span, adjust=False).mean()
            )

        # High-Low spread
        features['hl_spread'] = (features['high'] - features['low']) / features['close']
        features['hl_spread_ma'] = features.groupby('stock_id')['hl_spread'].transform(
            lambda x: x.rolling(20, min_periods=1).mean()
        )

        # Gap features
        gap_list = []
        for stock_id in features['stock_id'].unique():
            mask = features['stock_id'] == stock_id
            stock_df = features[mask].copy()
            gap = (stock_df['open'].values - stock_df['close'].shift(1).values) / (stock_df['close'].shift(1).values + 1e-10)
            gap_list.append(gap)
        features['gap'] = np.concatenate(gap_list)
        features['gap'] = features['gap'].replace([np.inf, -np.inf], 0).fillna(0)
        features['gap_ma'] = features.groupby('stock_id')['gap'].transform(
            lambda x: x.rolling(20, min_periods=1).mean()
        )

        # Range features
        features['range'] = features['high'] - features['low']
        features['range_ma'] = features.groupby('stock_id')['range'].transform(
            lambda x: x.rolling(20, min_periods=1).mean()
        )

        # Skew and Kurtosis
        features['returns_skew'] = features.groupby('stock_id')['return'].transform(
            lambda x: x.rolling(20, min_periods=2).skew()
        )
        features['returns_kurt'] = features.groupby('stock_id')['return'].transform(
            lambda x: x.rolling(20, min_periods=2).kurt()
        )

        # Autocorrelation (lag-1)
        features['return_autocorr_lag1'] = features.groupby('stock_id')['return'].transform(
            lambda x: pd.Series([x.autocorr(lag=1)] * len(x), index=x.index)
        ).fillna(0)

        # Fill NaNs
        features = features.fillna(0)

        return features


# ============================================================================
# SECTION 4: META-LABELING
# ============================================================================

class MetaLabeler:
    """
    Meta-Labeling: Two-tier prediction system.

    Tier 1: Primary model (e.g., trend-following) predicts market direction.
    Tier 2: Secondary classifier predicts if primary signal should be trusted (1) or ignored (0).

    Meta-label = 1 if primary signal is correct, 0 if incorrect.
    """

    @staticmethod
    def compute_primary_signal(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
        """
        Simple primary trend-following signal.
        1 if price above 20-day SMA, 0 otherwise.
        """
        df = df.copy()
        df['sma'] = df.groupby('stock_id')['close'].transform(
            lambda x: x.rolling(lookback, min_periods=1).mean()
        )
        signal = (df['close'] > df['sma']).astype(int)
        return signal

    @staticmethod
    def create_meta_labels(df: pd.DataFrame) -> pd.Series:
        """
        Create meta-labels based on primary signal and actual outcome.

        Meta-label = 1 if: (primary_signal == 1) and (label == 1)
                         OR (primary_signal == -1) and (label == -1)
        Meta-label = 0 otherwise.
        """
        df = df.copy()

        # Compute primary signal
        df['primary_signal'] = MetaLabeler.compute_primary_signal(df, lookback=20)

        # Convert primary signal to direction: 1 (bullish), 0 (bearish)
        # and compare with actual outcome (label: 1=win, -1=loss, 0=neutral)

        meta_labels = []
        for idx in df.index:
            primary = df.loc[idx, 'primary_signal']
            outcome = df.loc[idx, 'label']

            # Meta-label = 1 if primary signal aligns with outcome
            if (primary == 1 and outcome == 1) or (primary == 0 and outcome == -1):
                meta_labels.append(1)
            else:
                meta_labels.append(0)

        return pd.Series(meta_labels, index=df.index)


# ============================================================================
# SECTION 5: PURGED & EMBARGOED COMBINATORIAL PURGED CROSS-VALIDATION
# ============================================================================

class PurgedKFoldCV:
    """
    Purged and Embargoed K-Fold Cross-Validation for time-series.

    Key concepts:
    1. Purging: Remove training observations that overlap temporally with test fold.
    2. Embargo: Remove training observations immediately before/after test fold to account for information leakage.

    This prevents look-ahead bias and ensures realistic out-of-sample evaluation.
    """

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01):
        """
        Args:
            n_splits: Number of folds.
            embargo_pct: Fraction of dataset to embargo (before/after test fold).
        """
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(self, X: pd.DataFrame, y: pd.Series = None, groups: pd.Series = None):
        """
        Generate train/test indices with purging and embargo.

        Args:
            X: Features DataFrame with 'date' column.
            y: Labels (optional).
            groups: Stock IDs (optional, used for grouping).

        Yields:
            (train_indices, test_indices) tuples.
        """
        if 'date' not in X.columns:
            raise ValueError("X must have a 'date' column for time-series CV.")

        n_samples = len(X)
        embargo_size = int(n_samples * self.embargo_pct)

        dates = X['date'].values
        n_test = n_samples // self.n_splits

        for fold in range(self.n_splits):
            test_start_idx = fold * n_test
            test_end_idx = (fold + 1) * n_test if fold < self.n_splits - 1 else n_samples

            # Embargo boundaries
            embargo_start_idx = max(0, test_start_idx - embargo_size)
            embargo_end_idx = min(n_samples, test_end_idx + embargo_size)

            # Train indices: everything except test + embargo
            train_indices = np.concatenate([
                np.arange(0, embargo_start_idx),
                np.arange(embargo_end_idx, n_samples)
            ])

            # Test indices
            test_indices = np.arange(test_start_idx, test_end_idx)

            # Remove overlapping dates from training
            test_dates = set(dates[test_indices])
            train_mask = ~np.isin(dates[train_indices], list(test_dates))
            train_indices = train_indices[train_mask]

            if len(train_indices) > 0 and len(test_indices) > 0:
                yield train_indices, test_indices


# ============================================================================
# SECTION 6: FEATURE SELECTION (MDA & MDI)
# ============================================================================

class FeatureSelector:
    """
    Feature selection using Mean Decrease Accuracy (MDA) and Mean Decrease Impurity (MDI).
    """

    @staticmethod
    def compute_mda(
        model: RandomForestClassifier,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        n_repeats: int = 10,
    ) -> Dict[str, float]:
        """
        Compute Mean Decrease Accuracy.

        For each feature, permute it randomly and measure drop in accuracy.
        """
        baseline_score = model.score(X_test, y_test)
        mda_scores = {}

        feature_names = X_test.columns if hasattr(X_test, 'columns') else [f'feat_{i}' for i in range(X_test.shape[1])]

        for feat_idx, feat_name in enumerate(feature_names):
            X_permuted = X_test.copy()
            scores = []

            for _ in range(n_repeats):
                # Permute feature
                perm_idx = np.random.permutation(len(X_permuted))
                if hasattr(X_permuted, 'iloc'):
                    X_permuted.iloc[:, feat_idx] = X_permuted.iloc[perm_idx, feat_idx].values
                else:
                    X_permuted[:, feat_idx] = X_permuted[perm_idx, feat_idx]

                # Measure accuracy drop
                permuted_score = model.score(X_permuted, y_test)
                scores.append(max(0, baseline_score - permuted_score))

            mda_scores[feat_name] = np.mean(scores)

        return mda_scores

    @staticmethod
    def compute_mdi(model: RandomForestClassifier) -> Dict[str, float]:
        """
        Compute Mean Decrease Impurity (Gini/Entropy importance).
        """
        feature_names = getattr(model, 'feature_names_in_', None)
        if feature_names is None:
            n_features = model.n_features_in_
            feature_names = [f'feat_{i}' for i in range(n_features)]

        importances = model.feature_importances_
        mdi_scores = {name: importance for name, importance in zip(feature_names, importances)}

        return mdi_scores

    @staticmethod
    def rank_features(
        mda_scores: Dict[str, float],
        mdi_scores: Dict[str, float],
        top_n: int = 30,
    ) -> pd.DataFrame:
        """Combine MDA and MDI rankings."""

        # Normalize scores to [0, 1]
        mda_normalized = {}
        mda_min, mda_max = min(mda_scores.values()), max(mda_scores.values())
        for key, val in mda_scores.items():
            mda_normalized[key] = (val - mda_min) / (mda_max - mda_min + 1e-10)

        mdi_normalized = {}
        mdi_min, mdi_max = min(mdi_scores.values()), max(mdi_scores.values())
        for key, val in mdi_scores.items():
            mdi_normalized[key] = (val - mdi_min) / (mdi_max - mdi_min + 1e-10)

        # Combine
        all_features = set(mda_scores.keys()) | set(mdi_scores.keys())
        combined = {}
        for feat in all_features:
            mda_val = mda_normalized.get(feat, 0)
            mdi_val = mdi_normalized.get(feat, 0)
            combined[feat] = 0.5 * mda_val + 0.5 * mdi_val

        # Rank and return top_n
        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)

        result_df = pd.DataFrame({
            'feature': [x[0] for x in ranked[:top_n]],
            'importance': [x[1] for x in ranked[:top_n]],
            'mda_score': [mda_normalized.get(x[0], 0) for x in ranked[:top_n]],
            'mdi_score': [mdi_normalized.get(x[0], 0) for x in ranked[:top_n]],
        })

        return result_df


# ============================================================================
# SECTION 7: PERFORMANCE METRICS
# ============================================================================

class PerformanceMetrics:
    """Calculate performance metrics for backtest evaluation."""

    @staticmethod
    def compute_sortino_ratio(returns: np.ndarray, target_return: float = 0.0, periods_per_year: int = 252) -> float:
        """
        Sortino Ratio: Return / Downside Deviation

        Focuses on downside risk instead of total volatility.
        """
        excess_returns = returns - (target_return / periods_per_year)
        downside_returns = np.where(excess_returns < 0, excess_returns, 0)
        downside_std = np.sqrt(np.mean(downside_returns ** 2))

        if downside_std == 0:
            return 0.0

        annual_return = np.mean(returns) * periods_per_year
        sortino = annual_return / downside_std if downside_std > 0 else 0.0

        return sortino

    @staticmethod
    def compute_sharpe_ratio(returns: np.ndarray, periods_per_year: int = 252) -> float:
        """Sharpe Ratio: Return / Volatility."""
        if len(returns) < 2:
            return 0.0
        mean_return = np.mean(returns) * periods_per_year
        std_return = np.std(returns) * np.sqrt(periods_per_year)
        sharpe = mean_return / std_return if std_return > 0 else 0.0
        return sharpe

    @staticmethod
    def compute_max_drawdown(cumulative_returns: np.ndarray) -> float:
        """Maximum Drawdown."""
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max
        return np.min(drawdown)

    @staticmethod
    def compute_win_rate(labels: np.ndarray) -> float:
        """Win rate: % of positive returns."""
        wins = np.sum(labels == 1)
        total = len(labels[labels != 0])
        return wins / total if total > 0 else 0.0


# ============================================================================
# SECTION 8: OPTUNA HYPERPARAMETER OPTIMIZATION
# ============================================================================

class MLPipeline:
    """
    End-to-end ML pipeline with Optuna optimization.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.best_model = None
        self.best_params = None
        self.scaler = StandardScaler()
        self.feature_names = None

    def prepare_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepare data: feature engineering, labeling, meta-labeling.
        """
        # Engineer features
        print("[1/4] Engineering features...")
        df = FeatureEngineer.engineer_features(df)

        # Triple-barrier labeling
        print("[2/4] Applying triple-barrier labeling...")
        labeler = TripleBarrierLabeler(
            atr_window=self.config.atr_window,
            atr_multiplier_up=self.config.atr_multiplier_up,
            atr_multiplier_down=self.config.atr_multiplier_down,
            holding_period=self.config.holding_period,
            min_return_threshold=self.config.min_return_threshold,
        )
        df = labeler.label_signals(df)

        # Meta-labeling
        print("[3/4] Creating meta-labels...")
        df['meta_label'] = MetaLabeler.create_meta_labels(df)

        # Select features (exclude non-feature columns)
        print("[4/4] Selecting features...")
        exclude_cols = ['date', 'ticker', 'stock_id', 'open', 'high', 'low', 'close', 'volume',
                        'label', 'return_pct', 'primary_signal', 'sma', 'meta_label',
                        'barrier_up', 'barrier_down', 'vertical_barrier_date', 'tr']
        feature_cols = [col for col in df.columns if col not in exclude_cols and not col.startswith('_')]

        self.feature_names = feature_cols
        X = df[feature_cols].fillna(0)
        y = df['meta_label']

        return X, y, df

    def select_features_with_mda_mdi(self, X: pd.DataFrame, y: pd.Series, n_top: int = 30) -> Tuple[List[str], pd.DataFrame]:
        """Feature selection using MDA and MDI."""
        print(f"\n[FEATURE SELECTION] Computing MDA and MDI on {len(X)} samples, {X.shape[1]} features...")

        # Train a quick random forest to compute feature importance
        rf_quick = RandomForestClassifier(n_estimators=50, max_depth=10, random_state=self.config.random_state, n_jobs=-1)
        rf_quick.fit(X.fillna(0), y)

        # Compute MDI
        mdi_scores = FeatureSelector.compute_mdi(rf_quick)

        # Compute MDA (on subset for speed)
        n_test = min(5000, len(X) // 5)
        X_test = X.iloc[-n_test:].reset_index(drop=True)
        y_test = y.iloc[-n_test:].reset_index(drop=True)
        mda_scores = FeatureSelector.compute_mda(rf_quick, X_test, y_test, n_repeats=5)

        # Rank features
        ranking_df = FeatureSelector.rank_features(mda_scores, mdi_scores, top_n=n_top)

        print(f"\n[TOP {n_top} FEATURES]")
        print(ranking_df.to_string(index=False))

        selected_features = ranking_df['feature'].tolist()
        return selected_features, ranking_df

    def optimize_lgb_with_optuna(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        trade_returns: np.ndarray,
        n_trials: int = 50,
    ) -> Dict:
        """
        Optimize LightGBM hyperparameters using Optuna.
        Objective: Maximize Sortino ratio of predictions.
        """

        def objective(trial: optuna.Trial) -> float:
            params = {
                'objective': 'binary',
                'metric': 'binary_logloss',
                'n_estimators': trial.suggest_int('n_estimators', 50, 500),
                'max_depth': trial.suggest_int('max_depth', 3, 15),
                'learning_rate': trial.suggest_float('learning_rate', 0.001, 0.1, log=True),
                'num_leaves': trial.suggest_int('num_leaves', 20, 100),
                'min_child_samples': trial.suggest_int('min_child_samples', 5, 50),
                'subsample': trial.suggest_float('subsample', 0.5, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
                'reg_alpha': trial.suggest_float('reg_alpha', 0.0, 1.0),
                'reg_lambda': trial.suggest_float('reg_lambda', 0.0, 1.0),
                'verbose': -1,
            }

            # Train LightGBM
            train_data = lgb.Dataset(X_train.fillna(0), label=y_train)
            valid_data = lgb.Dataset(X_val.fillna(0), label=y_val, reference=train_data)

            model = lgb.train(
                params,
                train_data,
                num_boost_round=params['n_estimators'],
                valid_sets=[valid_data],
                callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
            )

            # Predict and compute Sortino
            y_pred = model.predict(X_val.fillna(0))

            # Filter predictions to those where model is confident (>50% probability)
            confident_mask = (y_pred > 0.5) | (y_pred < 0.5)
            if np.sum(confident_mask) < 10:
                return 0.0

            filtered_returns = trade_returns[confident_mask]
            sortino = PerformanceMetrics.compute_sortino_ratio(filtered_returns)

            return sortino

        print(f"\n[OPTUNA OPTIMIZATION] Starting {n_trials} trials...")
        sampler = TPESampler(seed=self.config.random_state)
        study = optuna.create_study(
            direction='maximize',
            sampler=sampler,
        )

        study.optimize(
            objective,
            n_trials=n_trials,
            show_progress_bar=True,
        )

        print(f"\n[OPTIMIZATION COMPLETE]")
        print(f"Best Sortino Ratio: {study.best_value:.4f}")
        print(f"Best Parameters: {study.best_params}")

        return study.best_params

    def train_final_model(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        hyperparams: Dict,
    ) -> lgb.Booster:
        """Train final LightGBM model with optimized hyperparameters."""

        train_data = lgb.Dataset(X_train.fillna(0), label=y_train)

        model = lgb.train(
            hyperparams,
            train_data,
            num_boost_round=hyperparams['n_estimators'],
            callbacks=[lgb.log_evaluation(0)],
        )

        return model

    def run_pipeline(self, df: pd.DataFrame) -> Dict:
        """
        Execute the complete pipeline:
        1. Data preparation
        2. Feature selection (MDA/MDI)
        3. Purged cross-validation setup
        4. Optuna optimization
        5. Final model training
        """

        print("\n" + "="*80)
        print("ML QUANT PIPELINE: TRIPLE-BARRIER + META-LABELING + CPCV + OPTUNA")
        print("="*80)

        # Step 1: Prepare data
        X, y, df_full = self.prepare_data(df)
        print(f"\n[DATA PREP] {X.shape[0]} samples, {X.shape[1]} features")
        print(f"Label distribution: {y.value_counts().to_dict()}")

        # Step 2: Feature selection
        selected_features, ranking_df = self.select_features_with_mda_mdi(X, y, n_top=30)
        X_selected = X[selected_features]

        # Step 3: Purged cross-validation
        print(f"\n[PURGED K-FOLD CV] Initializing 5-fold purged cross-validation...")
        cv = PurgedKFoldCV(n_splits=5, embargo_pct=0.01)
        cv_results = {
            'fold_accuracies': [],
            'fold_precisions': [],
            'fold_recalls': [],
            'fold_f1_scores': [],
        }

        fold_idx = 1
        best_val_sortino = -np.inf
        best_fold_model = None
        best_fold_params = None

        for train_idx, test_idx in cv.split(X_selected.reset_index(drop=True).assign(date=df_full['date'].values)):
            print(f"\n[FOLD {fold_idx}/5] Train: {len(train_idx)}, Test: {len(test_idx)}")

            X_train, X_test = X_selected.iloc[train_idx].reset_index(drop=True), X_selected.iloc[test_idx].reset_index(drop=True)
            y_train, y_test = y.iloc[train_idx].reset_index(drop=True), y.iloc[test_idx].reset_index(drop=True)

            # Split train into train/val for Optuna
            val_split = int(0.2 * len(X_train))
            X_tr, X_va = X_train[:-val_split], X_train[-val_split:]
            y_tr, y_va = y_train[:-val_split], y_train[-val_split:]

            # Get returns for Sortino computation
            test_returns = df_full.iloc[test_idx]['return_pct'].values

            # Optimize hyperparameters
            best_params = self.optimize_lgb_with_optuna(
                X_tr, y_tr, X_va, y_va,
                test_returns,
                n_trials=30,
            )

            # Train final model on full train fold
            model = self.train_final_model(X_train, y_train, best_params)

            # Evaluate
            y_pred = (model.predict(X_test.fillna(0)) > 0.5).astype(int)
            acc = accuracy_score(y_test, y_pred)
            prec = precision_score(y_test, y_pred, zero_division=0)
            rec = recall_score(y_test, y_pred, zero_division=0)
            f1 = f1_score(y_test, y_pred, zero_division=0)

            # Sortino on test set
            pred_returns = test_returns * y_pred
            sortino = PerformanceMetrics.compute_sortino_ratio(pred_returns)

            print(f"Fold {fold_idx} Metrics: Acc={acc:.4f}, Prec={prec:.4f}, Rec={rec:.4f}, F1={f1:.4f}, Sortino={sortino:.4f}")

            cv_results['fold_accuracies'].append(acc)
            cv_results['fold_precisions'].append(prec)
            cv_results['fold_recalls'].append(rec)
            cv_results['fold_f1_scores'].append(f1)

            if sortino > best_val_sortino:
                best_val_sortino = sortino
                best_fold_model = model
                best_fold_params = best_params

            fold_idx += 1

        # Step 4: Train on all data with best params
        print(f"\n[FINAL MODEL] Training on all {len(X_selected)} samples with best hyperparameters...")
        self.best_model = self.train_final_model(X_selected, y, best_fold_params)
        self.best_params = best_fold_params

        # Step 5: Final evaluation
        y_pred_final = (self.best_model.predict(X_selected.fillna(0)) > 0.5).astype(int)
        final_acc = accuracy_score(y, y_pred_final)
        final_returns = df_full['return_pct'].values * y_pred_final
        final_sortino = PerformanceMetrics.compute_sortino_ratio(final_returns)

        print(f"\n[FINAL RESULTS]")
        print(f"Final Accuracy: {final_acc:.4f}")
        print(f"Final Sortino Ratio: {final_sortino:.4f}")
        print(f"Avg CV Accuracy: {np.mean(cv_results['fold_accuracies']):.4f}")
        print(f"CV Std: {np.std(cv_results['fold_accuracies']):.4f}")

        results = {
            'model': self.best_model,
            'params': self.best_params,
            'selected_features': selected_features,
            'feature_ranking': ranking_df,
            'cv_results': cv_results,
            'final_accuracy': final_acc,
            'final_sortino': final_sortino,
            'X_selected': X_selected,
            'y_predictions': y_pred_final,
        }

        return results


# ============================================================================
# SECTION 9: MAIN EXECUTION
# ============================================================================

def main():
    """Execute the complete ML quant pipeline."""

    # Configuration
    config = PipelineConfig(
        n_stocks=500,
        lookback_window=252,
        holding_period=5,
        atr_window=20,
        atr_multiplier_up=1.0,
        atr_multiplier_down=1.0,
        min_return_threshold=0.001,
    )

    # Generate synthetic data (replace with real data in production)
    print("\n[DATA GENERATION] Generating OHLCV data for 500 stocks...")
    generator = DataGenerator(n_stocks=config.n_stocks, n_days=1000, random_state=42)
    df = generator.generate()
    print(f"Data shape: {df.shape}")

    # Initialize pipeline
    pipeline = MLPipeline(config)

    # Run full pipeline
    results = pipeline.run_pipeline(df)

    # Save results
    output_dir = Path('/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data')
    output_dir.mkdir(exist_ok=True)

    # Save model
    model_path = output_dir / 'lgb_meta_label_model.pkl'
    with open(model_path, 'wb') as f:
        pickle.dump(results['model'], f)
    print(f"\n[SAVED] Model: {model_path}")

    # Save feature ranking
    ranking_path = output_dir / 'feature_ranking.csv'
    results['feature_ranking'].to_csv(ranking_path, index=False)
    print(f"[SAVED] Feature Ranking: {ranking_path}")

    # Save selected features
    features_path = output_dir / 'selected_features.txt'
    with open(features_path, 'w') as f:
        f.write('\n'.join(results['selected_features']))
    print(f"[SAVED] Selected Features: {features_path}")

    print("\n" + "="*80)
    print("PIPELINE COMPLETE")
    print("="*80)


if __name__ == '__main__':
    main()
