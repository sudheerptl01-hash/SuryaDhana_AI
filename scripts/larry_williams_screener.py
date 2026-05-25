"""
Larry Williams Volatility Breakout Daily Screener
==================================================

Production-grade daily stock screener identifying 4 specific setups:
1. The Squeeze: 20-day Bollinger Bands inside 20-day Keltner Channels
2. The "Oops" Reversal: Open below prior low, now trading above prior low
3. Extreme Oversold in Uptrend: Williams %R < -80 + price > 200-day SMA
4. Liquidity Filter: 20-day ADV > $10M

Output: Sorted DataFrame of actionable tickers by ATR expansion magnitude.

Architecture:
- Vectorized pandas computations (no iterrows loops)
- Proper multi-index handling (Date, Ticker)
- Forward-fill NaNs respecting ticker boundaries
- Real-time calculation ready (single row = today's data)
"""

import pandas as pd
import numpy as np
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, Optional
from datetime import datetime, timedelta


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s — %(message)s'
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES & CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScreenerConfig:
    """Configurable thresholds for Larry Williams setups"""

    # The Squeeze: Bollinger Bands inside Keltner Channels
    bb_period: int = 20
    bb_std_dev: float = 2.0
    kc_period: int = 20
    kc_atr_multiplier: float = 1.5

    # The "Oops" Reversal: Open < Prior Low, Close > Prior Low
    oops_lookback: int = 1

    # Extreme Oversold in Uptrend
    williams_r_period: int = 14
    williams_r_threshold: float = -80.0
    sma_200_period: int = 200

    # Liquidity Filter: 20-day ADV > $10M
    adv_period: int = 20
    adv_threshold: float = 10_000_000.0

    # ATR for expansion ranking
    atr_period: int = 14


# ─────────────────────────────────────────────────────────────────────────────
# CORE SCREENER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class VolatilityBreakoutScreener:
    """
    Larry Williams volatility breakout screener.

    Designed to work with multi-index DataFrames (Date, Ticker).
    All computations are fully vectorized.
    """

    def __init__(self, ohlcv_df: pd.DataFrame, config: Optional[ScreenerConfig] = None):
        """
        Initialize screener with OHLCV data.

        Args:
            ohlcv_df: MultiIndex DataFrame with levels (date, ticker) and columns
                     [open, high, low, close, volume]. Sorted by date, ticker.
            config: ScreenerConfig instance (uses defaults if None)
        """
        self.df = ohlcv_df.copy()
        self.config = config or ScreenerConfig()

        # Validate input
        self._validate_input()

        # Compute all required indicators
        self._compute_indicators()

    def _validate_input(self):
        """Validate OHLCV DataFrame structure and data quality"""
        required_cols = {'open', 'high', 'low', 'close', 'volume'}
        missing = required_cols - set(self.df.columns.str.lower())
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Standardize column names
        self.df.columns = self.df.columns.str.lower()

        # Verify MultiIndex
        if not isinstance(self.df.index, pd.MultiIndex):
            raise ValueError("DataFrame must have MultiIndex (date, ticker)")

        if self.df.index.names != ['date', 'ticker']:
            raise ValueError("MultiIndex levels must be named ['date', 'ticker']")

        # Data type checks
        for col in required_cols:
            if not np.issubdtype(self.df[col].dtype, np.number):
                self.df[col] = pd.to_numeric(self.df[col], errors='coerce')

        # Remove rows with missing OHLCV
        initial_len = len(self.df)
        self.df = self.df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])

        if len(self.df) < initial_len:
            log.warning(f"Dropped {initial_len - len(self.df)} rows with missing OHLCV")

    def _compute_indicators(self):
        """Compute all indicators required for screening"""
        log.info("Computing indicators...")

        self.df['sma_200'] = self._compute_sma(self.df['close'], self.config.sma_200_period)
        self.df['atr_14'] = self._compute_atr(self.config.atr_period)
        self.df['williams_r_14'] = self._compute_williams_r(self.config.williams_r_period)
        self.df['adv_20'] = self._compute_adv(self.config.adv_period)

        self.df['bb_upper'], self.df['bb_lower'] = self._compute_bollinger_bands(
            self.config.bb_period, self.config.bb_std_dev
        )
        self.df['kc_upper'], self.df['kc_lower'] = self._compute_keltner_channels(
            self.config.kc_period, self.config.kc_atr_multiplier
        )

        self.df['prior_high'] = self.df.groupby(level='ticker')['high'].shift(1)
        self.df['prior_low'] = self.df.groupby(level='ticker')['low'].shift(1)

        log.info("✓ Indicators computed")

    @staticmethod
    def _compute_sma(series: pd.Series, period: int) -> pd.Series:
        """Compute SMA grouped by ticker, respecting multi-index"""
        return series.groupby(level='ticker').transform(
            lambda x: x.rolling(window=period, min_periods=1).mean()
        )

    def _compute_atr(self, period: int) -> pd.Series:
        """Compute Average True Range grouped by ticker"""
        tr = self._true_range()
        atr = tr.groupby(level='ticker').transform(
            lambda x: x.rolling(window=period, min_periods=1).mean()
        )
        return atr

    def _true_range(self) -> pd.Series:
        """Compute True Range for ATR calculation"""
        high = self.df['high']
        low = self.df['low']
        close = self.df.groupby(level='ticker')['close'].shift(1)

        tr = pd.concat([
            high - low,
            (high - close).abs(),
            (low - close).abs()
        ], axis=1).max(axis=1)

        return tr

    def _compute_williams_r(self, period: int) -> pd.Series:
        """
        Compute Williams %R (14-period).
        Range: -100 (lowest) to 0 (highest)
        """
        def williams_r_group(group):
            high_max = group['high'].rolling(window=period, min_periods=1).max()
            low_min = group['low'].rolling(window=period, min_periods=1).min()
            close = group['close']

            wr = -100 * (high_max - close) / (high_max - low_min + 1e-10)
            return wr

        return self.df.groupby(level='ticker').apply(williams_r_group).droplevel(0)

    def _compute_bollinger_bands(self, period: int, std_dev: float) -> Tuple[pd.Series, pd.Series]:
        """Compute Bollinger Bands (upper, lower)"""
        sma = self._compute_sma(self.df['close'], period)
        std = self.df['close'].groupby(level='ticker').transform(
            lambda x: x.rolling(window=period, min_periods=1).std()
        )

        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)

        return upper, lower

    def _compute_keltner_channels(self, period: int, atr_mult: float) -> Tuple[pd.Series, pd.Series]:
        """Compute Keltner Channels using ATR"""
        ema = self.df['close'].groupby(level='ticker').transform(
            lambda x: x.ewm(span=period, adjust=False).mean()
        )
        atr = self._compute_atr(period)

        upper = ema + (atr_mult * atr)
        lower = ema - (atr_mult * atr)

        return upper, lower

    def _compute_adv(self, period: int) -> pd.Series:
        """Compute 20-day Average Dollar Volume (Close * Volume)"""
        dollar_volume = self.df['close'] * self.df['volume']
        # min_periods=5 prevents spurious ADV values for tickers with very few rows;
        # fillna(0) ensures illiquid tickers fail the liquidity filter cleanly.
        adv = dollar_volume.groupby(level='ticker').transform(
            lambda x: x.rolling(window=period, min_periods=min(period, 5)).mean()
        ).replace([np.inf, -np.inf], 0).fillna(0)
        return adv

    # ─────────────────────────────────────────────────────────────────────────
    # FILTER METHODS (return boolean Series)
    # ─────────────────────────────────────────────────────────────────────────

    def filter_the_squeeze(self) -> pd.Series:
        """
        Filter 1: The Squeeze
        Bollinger Bands entirely inside Keltner Channels.

        Condition: bb_upper < kc_upper AND bb_lower > kc_lower
        """
        squeeze = (
            (self.df['bb_upper'] < self.df['kc_upper']) &
            (self.df['bb_lower'] > self.df['kc_lower'])
        )
        return squeeze

    def filter_oops_reversal(self) -> pd.Series:
        """
        Filter 2: The "Oops" Reversal
        Open below prior low, but now trading above prior low.

        Condition: open < prior_low AND close > prior_low
        """
        oops = (
            (self.df['open'] < self.df['prior_low']) &
            (self.df['close'] > self.df['prior_low'])
        )
        return oops

    def filter_extreme_oversold_uptrend(self) -> pd.Series:
        """
        Filter 3: Extreme Oversold in Macro Uptrend
        Williams %R < -80 AND price > 200-day SMA

        Condition: williams_r_14 < -80 AND close > sma_200
        """
        extreme = (
            (self.df['williams_r_14'] < self.config.williams_r_threshold) &
            (self.df['close'] > self.df['sma_200'])
        )
        return extreme

    def filter_liquidity(self) -> pd.Series:
        """
        Filter 4: Liquidity Filter
        20-day Average Dollar Volume > $10,000,000

        Condition: adv_20 > 10M
        """
        liquid = self.df['adv_20'] > self.config.adv_threshold
        return liquid

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN SCREENING FUNCTION
    # ─────────────────────────────────────────────────────────────────────────

    def screen(self, date: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """
        Run complete screening pipeline.

        Args:
            date: Filter to specific date (None = use latest date in data)

        Returns:
            DataFrame of actionable setups sorted by ATR expansion
        """
        # Default to latest date
        if date is None:
            date = self.df.index.get_level_values('date').max()

        log.info(f"Screening for {date.date()}")

        # Filter to today's data
        today = self.df.loc[date].copy()
        if isinstance(today, pd.Series):
            today = today.to_frame().T

        # Apply all 4 filters
        filters = {
            'squeeze': self.filter_the_squeeze().loc[date],
            'oops': self.filter_oops_reversal().loc[date],
            'oversold_uptrend': self.filter_extreme_oversold_uptrend().loc[date],
            'liquidity': self.filter_liquidity().loc[date]
        }

        # Combine: stock must pass ALL filters
        combined = pd.concat(filters, axis=1).all(axis=1)
        actionable = today[combined].copy()

        if len(actionable) == 0:
            log.warning(f"No setups found on {date.date()}")
            return pd.DataFrame()

        # Sort by ATR expansion (descending = largest first)
        actionable = actionable.sort_values('atr_14', ascending=False)

        # Clean output columns
        output_cols = [
            'open', 'high', 'low', 'close', 'volume',
            'atr_14', 'williams_r_14', 'sma_200', 'adv_20',
            'bb_upper', 'bb_lower', 'kc_upper', 'kc_lower'
        ]
        output = actionable[[c for c in output_cols if c in actionable.columns]]

        # Add filter status columns for transparency
        for filter_name, series in filters.items():
            output[f'pass_{filter_name}'] = series.loc[combined.index[combined]]

        log.info(f"✓ Found {len(output)} actionable setups on {date.date()}")

        return output

    def screen_with_breakdown(self, date: Optional[pd.Timestamp] = None) -> dict:
        """
        Run screening with detailed filter breakdown (for analysis).

        Returns:
            Dict with:
            - 'actionable': DataFrame of passing setups
            - 'filter_counts': Count of stocks passing each filter
            - 'stats': Summary statistics
        """
        if date is None:
            date = self.df.index.get_level_values('date').max()

        today = self.df.loc[date].copy()
        if isinstance(today, pd.Series):
            today = today.to_frame().T

        filters = {
            'squeeze': self.filter_the_squeeze().loc[date],
            'oops': self.filter_oops_reversal().loc[date],
            'oversold_uptrend': self.filter_extreme_oversold_uptrend().loc[date],
            'liquidity': self.filter_liquidity().loc[date]
        }

        filter_counts = {name: series.sum() for name, series in filters.items()}
        combined = pd.concat(filters, axis=1).all(axis=1)

        return {
            'actionable': self.screen(date),
            'filter_counts': filter_counts,
            'universe_size': len(today),
            'combined_pass_count': combined.sum(),
            'total_universe': len(today)
        }


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def load_engineered_features_ohlcv(parquet_path: str) -> pd.DataFrame:
    """Load Parquet from run_feature_engineering.py and extract OHLCV"""
    df = pd.read_parquet(parquet_path)

    # Assume MultiIndex (date, ticker) from engineered features
    required = {'open', 'high', 'low', 'close', 'volume'}
    available = set(df.columns.str.lower())

    if not required.issubset(available):
        raise ValueError(f"Missing columns. Need {required}, have {available}")

    ohlcv = df[list(required)].copy()
    ohlcv.columns = ohlcv.columns.str.lower()

    return ohlcv.sort_index()


def export_screening_results(df: pd.DataFrame, output_path: str = './screening_results.csv'):
    """Export screening results to CSV with proper formatting"""
    if df.empty:
        log.warning("No results to export")
        return

    output_df = df.copy()

    # Format numeric columns
    numeric_cols = output_df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        if 'price' in col.lower() or col in ['open', 'high', 'low', 'close', 'sma_200']:
            output_df[col] = output_df[col].round(2)
        elif col in ['williams_r_14']:
            output_df[col] = output_df[col].round(1)
        elif col in ['atr_14']:
            output_df[col] = output_df[col].round(3)
        elif col == 'adv_20':
            output_df[col] = (output_df[col] / 1e6).round(1)  # In millions

    output_df.to_csv(output_path)
    log.info(f"Results exported to {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Larry Williams Volatility Breakout Daily Screener',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:

  # Screen today (latest date in Parquet)
  python larry_williams_screener.py --parquet engineered_features.parquet

  # Screen with breakdown stats
  python larry_williams_screener.py --parquet engineered_features.parquet --breakdown

  # Export to CSV
  python larry_williams_screener.py --parquet engineered_features.parquet --output results.csv
        """
    )

    parser.add_argument('--parquet', type=str, required=True,
                       help='Path to engineered features Parquet file')
    parser.add_argument('--output', type=str, default='screening_results.csv',
                       help='Output CSV path')
    parser.add_argument('--breakdown', action='store_true',
                       help='Show detailed filter breakdown')
    parser.add_argument('--date', type=str, default=None,
                       help='Screen specific date (YYYY-MM-DD), defaults to latest')

    args = parser.parse_args()

    try:
        # Load data
        log.info(f"Loading {args.parquet}")
        ohlcv = load_engineered_features_ohlcv(args.parquet)

        # Parse date if provided
        screen_date = None
        if args.date:
            screen_date = pd.to_datetime(args.date)

        # Initialize screener
        screener = VolatilityBreakoutScreener(ohlcv)

        # Run screening
        if args.breakdown:
            results = screener.screen_with_breakdown(screen_date)
            log.info("\n" + "=" * 80)
            log.info("SCREENING BREAKDOWN")
            log.info("=" * 80)
            log.info(f"Universe size: {results['total_universe']}")
            log.info(f"Squeeze (Filter 1): {results['filter_counts']['squeeze']}")
            log.info(f"Oops Reversal (Filter 2): {results['filter_counts']['oops']}")
            log.info(f"Oversold Uptrend (Filter 3): {results['filter_counts']['oversold_uptrend']}")
            log.info(f"Liquidity (Filter 4): {results['filter_counts']['liquidity']}")
            log.info(f"Combined (All 4): {results['combined_pass_count']}")
            log.info("=" * 80)
            actionable = results['actionable']
        else:
            actionable = screener.screen(screen_date)

        # Export
        if not actionable.empty:
            export_screening_results(actionable, args.output)
            log.info(f"\nTop 5 setups by ATR expansion:")
            print(actionable.head(5)[['close', 'atr_14', 'williams_r_14', 'adv_20']])
        else:
            log.warning("No setups found")

    except Exception as e:
        log.error(f"Screening failed: {e}", exc_info=True)
        exit(1)
