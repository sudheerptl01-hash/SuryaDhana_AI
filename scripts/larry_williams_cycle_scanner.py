"""
Larry Williams Macro Cycle & Pattern Scanner

Analyzes 500 stocks across 5 years for:
1. 28-Day Lunar/Calendar Cycle edge
2. Volume-Price Divergence at tops/bottoms
3. Accumulation/Distribution Failure Reversals
4. Blast-Off Momentum accumulation signals

Outputs top 20 stocks with strongest cyclical tendencies.

Author: ML Quant Team (Larry Williams methodology)
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import scipy.stats as stats
from enum import Enum

# ============================================================================
# SECTION 1: DATA CONFIGURATION & GENERATION
# ============================================================================

@dataclass
class ScannerConfig:
    """Configuration for Larry Williams scanner."""
    n_stocks: int = 500
    n_days: int = 1260  # 5 years of trading days
    lookback_days: int = 20
    calendar_cycle_window: int = 28
    expansion_window: int = 3
    divergence_threshold: float = 0.95  # 5% lower volume threshold


class DataGenerator:
    """Generate synthetic OHLCV + broader index data."""

    def __init__(self, n_stocks: int = 500, n_days: int = 1260, random_state: int = 42):
        np.random.seed(random_state)
        self.n_stocks = n_stocks
        self.n_days = n_days

    def generate(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Generate OHLCV for 500 stocks + SPY (market index)."""
        data = []
        base_date = datetime(2019, 1, 1)

        # Generate broader market (SPY proxy)
        spy_close = 250.0
        spy_data = []
        trading_dates = []

        # First pass: generate trading dates and SPY
        date = base_date
        while len(trading_dates) < self.n_days:
            if date.weekday() < 5:  # Only trading days
                trading_dates.append(date)
            date += timedelta(days=1)

        # Generate SPY data for all trading dates
        for date in trading_dates:
            daily_ret = np.random.normal(0.0004, 0.012)
            spy_close = spy_close * (1 + daily_ret)
            spy_open = spy_close * (1 + np.random.normal(0, 0.005))
            spy_high = max(spy_close, spy_open) * (1 + abs(np.random.normal(0, 0.008)))
            spy_low = min(spy_close, spy_open) * (1 - abs(np.random.normal(0, 0.008)))
            spy_volume = np.random.uniform(50000000, 100000000)

            spy_data.append({
                'date': date,
                'ticker': 'SPY',
                'open': spy_open,
                'high': spy_high,
                'low': spy_low,
                'close': spy_close,
                'volume': spy_volume,
            })

        # Generate individual stocks for all trading dates
        for stock_id in range(self.n_stocks):
            close = 100.0
            ticker = f"STOCK_{stock_id:04d}"

            for day_idx, date in enumerate(trading_dates):
                # Individual stock GBM (correlated with SPY)
                beta = np.random.uniform(0.8, 1.5)
                if day_idx > 0:
                    market_ret = spy_data[day_idx]['close'] / spy_data[day_idx-1]['close'] - 1
                else:
                    market_ret = 0
                idio_ret = np.random.normal(0, 0.015)
                daily_ret = beta * market_ret + idio_ret
                close = close * (1 + daily_ret)

                open_price = close * (1 + np.random.normal(0, 0.005))
                high = max(close, open_price) * (1 + abs(np.random.normal(0, 0.01)))
                low = min(close, open_price) * (1 - abs(np.random.normal(0, 0.01)))
                volume = np.random.uniform(100000, 1000000)

                data.append({
                    'date': trading_dates[day_idx],
                    'ticker': ticker,
                    'stock_id': stock_id,
                    'open': open_price,
                    'high': high,
                    'low': low,
                    'close': close,
                    'volume': volume,
                })

        df_stocks = pd.DataFrame(data)
        df_spy = pd.DataFrame(spy_data)

        df_stocks['date'] = pd.to_datetime(df_stocks['date'])
        df_spy['date'] = pd.to_datetime(df_spy['date'])

        df_stocks = df_stocks.sort_values(['stock_id', 'date']).reset_index(drop=True)
        df_spy = df_spy.sort_values('date').reset_index(drop=True)

        return df_stocks, df_spy


# ============================================================================
# SECTION 2: LARRY WILLIAMS PATTERN 1 - 28-DAY LUNAR/CALENDAR CYCLE
# ============================================================================

class CalendarCycleScanner:
    """
    Detects statistically significant edge during specific weeks of calendar month.

    Larry Williams observed that markets tend to have cyclical patterns:
    - Week 1 (1-7): Often bullish post-weekend gaps
    - Week 2 (8-14): Mid-month strength
    - Week 3 (15-21): Options expiration volatility
    - Week 4+ (22+): Month-end repositioning

    Also checks around options expiration (3rd Friday).
    """

    def __init__(self, lookback_days: int = 252):
        self.lookback_days = lookback_days

    def analyze_calendar_edge(self, df: pd.DataFrame) -> Dict:
        """
        Compute returns by calendar week within month.
        Return dict with:
        - week_returns: avg return by week (1-4)
        - exp_week_returns: returns around options expiration
        - edge_score: -1.0 to 1.0 (positive = bullish edge)
        - p_value: statistical significance
        """
        df = df.copy().sort_values('date')

        # Recent data only (lookback window)
        df = df.iloc[-self.lookback_days:]

        if len(df) == 0:
            return {'edge_score': 0.0, 'p_value': 1.0, 'week_returns': {}}

        # Calculate daily returns
        df['return'] = df['close'].pct_change()

        # Assign week of month (1-4)
        df['day_of_month'] = df['date'].dt.day
        df['week_of_month'] = pd.cut(
            df['day_of_month'],
            bins=[0, 7, 14, 21, 31],
            labels=[1, 2, 3, 4],
            include_lowest=True
        )

        # Identify options expiration week (3rd Friday of month)
        def is_options_expiration_week(date):
            # 3rd Friday is typically in range 15-21
            return 15 <= date.day <= 21 and date.weekday() == 4  # Friday

        df['is_exp_week'] = df['date'].apply(is_options_expiration_week)

        # Compute returns by week
        week_returns = {}
        week_counts = {}

        for week in [1, 2, 3, 4]:
            week_data = df[df['week_of_month'] == week]
            if len(week_data) > 0:
                avg_ret = week_data['return'].mean()
                week_returns[week] = avg_ret
                week_counts[week] = len(week_data)

        # Options expiration edge
        exp_data = df[df['is_exp_week']]
        exp_return = exp_data['return'].mean() if len(exp_data) > 0 else 0.0

        # Edge score: positive if week 2-3 outperform week 1-4
        if len(week_returns) > 0:
            strong_weeks = [week_returns.get(i, 0) for i in [2, 3]]
            weak_weeks = [week_returns.get(i, 0) for i in [1, 4]]
            strong_avg = np.mean(strong_weeks) if strong_weeks else 0
            weak_avg = np.mean(weak_weeks) if weak_weeks else 0
            edge_diff = strong_avg - weak_avg
        else:
            edge_diff = 0

        # Normalize to [-1, 1]
        edge_score = np.tanh(edge_diff * 100)

        # Statistical test: compare week 2-3 vs week 1-4
        week_23_returns = df[df['week_of_month'].isin([2, 3])]['return'].dropna()
        week_14_returns = df[df['week_of_month'].isin([1, 4])]['return'].dropna()

        if len(week_23_returns) > 1 and len(week_14_returns) > 1:
            t_stat, p_value = stats.ttest_ind(week_23_returns, week_14_returns)
        else:
            p_value = 1.0

        return {
            'edge_score': edge_score,
            'p_value': p_value,
            'week_returns': week_returns,
            'exp_week_return': exp_return,
            'strong_weeks_edge': edge_diff,
        }


# ============================================================================
# SECTION 3: LARRY WILLIAMS PATTERN 2 - VOLUME-PRICE DIVERGENCE
# ============================================================================

class VolumePriceDivergenceScanner:
    """
    Detects volume-price divergence at market tops/bottoms.

    Rule: Stock makes new 20-day high on LOWER volume than previous high.
          While broader market fails to make new high.

    This indicates potential exhaustion and trend reversal.
    Classic Williams observation: "High on low volume = lack of conviction"
    """

    def __init__(self, lookback_days: int = 20, volume_threshold: float = 0.95):
        self.lookback_days = lookback_days
        self.volume_threshold = volume_threshold  # 95% = 5% lower

    def detect_divergence(self, df_stock: pd.DataFrame, df_market: pd.DataFrame) -> Dict:
        """
        Detect volume-price divergence signals.

        Returns:
        - divergence_count: # of divergence signals in lookback
        - divergence_intensity: avg intensity of signals
        - recent_divergence: true if divergence in last 3 days
        - consistency_score: 0-1 (higher = more consistent pattern)
        """
        df_stock = df_stock.copy().sort_values('date')
        df_market = df_market.copy().sort_values('date')

        # Align dates
        df_stock = df_stock.iloc[-self.lookback_days:]
        df_market = df_market[df_market['date'].isin(df_stock['date'])]

        if len(df_stock) < 5 or len(df_market) < 5:
            return {'divergence_count': 0, 'divergence_intensity': 0.0, 'recent_divergence': False}

        divergence_signals = []
        divergence_intensities = []

        # For each day, check if stock made new high on lower volume
        for i in range(2, len(df_stock)):
            current_close = df_stock.iloc[i]['close']
            current_volume = df_stock.iloc[i]['volume']
            current_high = df_stock.iloc[i]['high']

            # Previous 20-day high (excluding current)
            prev_window = df_stock.iloc[max(0, i-self.lookback_days):i]
            if len(prev_window) == 0:
                continue

            prev_high = prev_window['high'].max()
            prev_high_volume = prev_window.loc[prev_window['high'].idxmax(), 'volume']

            # Market check: did SPY also make new high?
            market_window = df_market[df_market['date'] <= df_stock.iloc[i]['date']]
            if len(market_window) > self.lookback_days:
                market_prev = market_window.iloc[-self.lookback_days:-1]
                market_prev_high = market_prev['high'].max()
                market_current_high = market_window.iloc[-1]['high']
                market_made_new_high = market_current_high > market_prev_high
            else:
                market_made_new_high = False

            # Divergence signal:
            # Stock makes new high BUT:
            # 1. Volume is lower than previous high volume
            # 2. Market fails to make new high (exhaustion)
            if current_high > prev_high and current_volume < (prev_high_volume * self.volume_threshold) and not market_made_new_high:
                intensity = 1.0 - (current_volume / prev_high_volume)  # How much lower is volume?
                divergence_signals.append(i)
                divergence_intensities.append(intensity)

        recent_divergence = len(divergence_signals) > 0 and (divergence_signals[-1] >= len(df_stock) - 3)

        return {
            'divergence_count': len(divergence_signals),
            'divergence_intensity': np.mean(divergence_intensities) if divergence_intensities else 0.0,
            'recent_divergence': recent_divergence,
            'consistency_score': min(1.0, len(divergence_signals) / 5.0),  # Higher if more signals
        }


# ============================================================================
# SECTION 4: LARRY WILLIAMS PATTERN 3 - ACCUMULATION/DISTRIBUTION REVERSAL
# ============================================================================

class AccumulationDistributionReversal:
    """
    Accumulation/Distribution Failure Reversals.

    Rule: Stock breaks out of 20-day range (new high or low)
          BUT closes back inside range within 48 hours

    This indicates failed accumulation/distribution and counter-trend setup.
    Classic Williams: "Failed breakouts are among highest probability trades"
    """

    def __init__(self, range_lookback: int = 20, reversal_window: int = 2):
        self.range_lookback = range_lookback
        self.reversal_window = reversal_window  # 48 hours = 2 trading days

    def identify_failed_breakouts(self, df: pd.DataFrame) -> Dict:
        """
        Identify failed range breakouts.

        Returns:
        - failed_breakout_count: # of signals
        - failure_rate: % of breakouts that fail
        - reversal_intensity: avg price movement post-failure
        - counter_trend_bias: direction of likely reversal
        """
        df = df.copy().sort_values('date')

        if len(df) < self.range_lookback + self.reversal_window:
            return {'failed_breakout_count': 0, 'failure_rate': 0.0, 'reversal_intensity': 0.0}

        failed_breakouts = []
        reversal_sizes = []
        reversal_directions = []  # 1 = down, -1 = up

        # Scan for breakouts
        for i in range(self.range_lookback, len(df) - self.reversal_window):
            # Establish 20-day range
            range_window = df.iloc[i - self.range_lookback:i]
            range_high = range_window['high'].max()
            range_low = range_window['low'].min()

            current_high = df.iloc[i]['high']
            current_low = df.iloc[i]['low']
            current_close = df.iloc[i]['close']

            # Detect breakout
            is_high_breakout = current_high > range_high
            is_low_breakout = current_low < range_low

            if is_high_breakout or is_low_breakout:
                # Check if price fails to hold breakout within reversal_window
                future_window = df.iloc[i + 1:i + 1 + self.reversal_window]

                if len(future_window) > 0:
                    future_close = future_window.iloc[-1]['close']

                    # Failed high breakout: closed back below range high
                    if is_high_breakout and future_close < range_high:
                        reversal_size = (current_high - future_close) / range_high
                        failed_breakouts.append(i)
                        reversal_sizes.append(reversal_size)
                        reversal_directions.append(1)  # Next move should be down

                    # Failed low breakout: closed back above range low
                    elif is_low_breakout and future_close > range_low:
                        reversal_size = (future_close - current_low) / range_low
                        failed_breakouts.append(i)
                        reversal_sizes.append(reversal_size)
                        reversal_directions.append(-1)  # Next move should be up

        # Calculate metrics
        total_breakouts = len(failed_breakouts)
        failure_rate = total_breakouts / max(1, len(df) - self.range_lookback - self.reversal_window)

        counter_trend_bias = np.mean(reversal_directions) if reversal_directions else 0.0

        return {
            'failed_breakout_count': total_breakouts,
            'failure_rate': failure_rate,
            'reversal_intensity': np.mean(reversal_sizes) if reversal_sizes else 0.0,
            'counter_trend_bias': counter_trend_bias,  # -1 to 1
        }


# ============================================================================
# SECTION 5: LARRY WILLIAMS PATTERN 4 - BLAST-OFF MOMENTUM
# ============================================================================

class BlastOffMomentumScanner:
    """
    Blast-Off Momentum Indicator.

    Formula: Detects 3-day rapid expansion in daily range (High - Low)

    Logic: When daily range expands significantly over 3 days,
           it indicates institutional accumulation and major trend initiation.

    Rule: If avg(range_3day) > 1.5 × avg(range_20day)
          Then strong momentum accumulation signal
    """

    def __init__(self, accumulation_window: int = 3, baseline_window: int = 20):
        self.accumulation_window = accumulation_window
        self.baseline_window = baseline_window

    def detect_blast_off(self, df: pd.DataFrame) -> Dict:
        """
        Detect blast-off accumulation patterns.

        Returns:
        - blast_off_signals: # of signals detected
        - momentum_strength: -1 to 1 (intensity)
        - is_active_blast_off: true if signal in last 3 days
        - trend_direction: 1 (up) or -1 (down)
        """
        df = df.copy().sort_values('date')

        if len(df) < self.baseline_window:
            return {'blast_off_signals': 0, 'momentum_strength': 0.0, 'is_active_blast_off': False}

        # Calculate daily range
        df['range'] = df['high'] - df['low']
        df['range_pct'] = df['range'] / df['close']

        blast_off_events = []
        momentum_strengths = []
        directions = []

        # Scan for blast-off patterns
        for i in range(self.baseline_window, len(df)):
            # 3-day accumulation window
            accum_window = df.iloc[i - self.accumulation_window:i]
            accum_range = accum_window['range'].mean()

            # 20-day baseline
            baseline_window = df.iloc[i - self.baseline_window:i]
            baseline_range = baseline_window['range'].mean()

            # Blast-off threshold: 1.5x baseline
            expansion_ratio = accum_range / baseline_range if baseline_range > 0 else 0

            if expansion_ratio > 1.5:
                # Determine direction by comparing opens/closes
                accum_close_avg = accum_window['close'].mean()
                accum_open_avg = accum_window['open'].mean()

                if accum_close_avg > accum_open_avg:
                    direction = 1  # Uptrend
                else:
                    direction = -1  # Downtrend

                # Momentum strength: how much above threshold?
                strength = np.tanh((expansion_ratio - 1.5) / 0.5)  # Normalize

                blast_off_events.append(i)
                momentum_strengths.append(strength)
                directions.append(direction)

        is_active = len(blast_off_events) > 0 and (blast_off_events[-1] >= len(df) - 3)

        trend_direction = np.mean(directions) if directions else 0.0

        return {
            'blast_off_signals': len(blast_off_events),
            'momentum_strength': np.mean(momentum_strengths) if momentum_strengths else 0.0,
            'is_active_blast_off': is_active,
            'trend_direction': trend_direction,
        }


# ============================================================================
# SECTION 6: MASTER SCANNER & RANKING ENGINE
# ============================================================================

class LarryWilliamsMasterScanner:
    """Master scanner combining all 4 Larry Williams patterns."""

    def __init__(self, config: ScannerConfig):
        self.config = config
        self.cycle_scanner = CalendarCycleScanner(lookback_days=252)
        self.divergence_scanner = VolumePriceDivergenceScanner(lookback_days=20)
        self.reversal_scanner = AccumulationDistributionReversal()
        self.momentum_scanner = BlastOffMomentumScanner()

    def scan_stock(self, df_stock: pd.DataFrame, df_market: pd.DataFrame) -> Dict:
        """
        Comprehensive scan of a single stock across all 4 patterns.
        """
        ticker = df_stock['ticker'].iloc[0] if len(df_stock) > 0 else "UNKNOWN"

        # Pattern 1: Calendar Cycle
        cycle_result = self.cycle_scanner.analyze_calendar_edge(df_stock)

        # Pattern 2: Volume-Price Divergence
        divergence_result = self.divergence_scanner.detect_divergence(df_stock, df_market)

        # Pattern 3: Failed Reversals
        reversal_result = self.reversal_scanner.identify_failed_breakouts(df_stock)

        # Pattern 4: Blast-Off Momentum
        momentum_result = self.momentum_scanner.detect_blast_off(df_stock)

        # Composite score: weight each pattern
        weights = {
            'cycle': 0.25,
            'divergence': 0.25,
            'reversal': 0.25,
            'momentum': 0.25,
        }

        # Normalize scores to [0, 1]
        cycle_score = max(0, cycle_result['edge_score'])
        divergence_score = divergence_result['consistency_score']
        reversal_score = max(0, reversal_result['failure_rate'])
        momentum_score = max(0, momentum_result['momentum_strength'])

        composite_score = (
            weights['cycle'] * cycle_score +
            weights['divergence'] * divergence_score +
            weights['reversal'] * reversal_score +
            weights['momentum'] * momentum_score
        )

        return {
            'ticker': ticker,
            'composite_score': composite_score,
            'cycle_edge': cycle_result['edge_score'],
            'cycle_pvalue': cycle_result['p_value'],
            'divergence_count': divergence_result['divergence_count'],
            'divergence_intensity': divergence_result['divergence_intensity'],
            'recent_divergence': divergence_result['recent_divergence'],
            'failed_breakouts': reversal_result['failed_breakout_count'],
            'failure_rate': reversal_result['failure_rate'],
            'reversal_intensity': reversal_result['reversal_intensity'],
            'blast_off_signals': momentum_result['blast_off_signals'],
            'momentum_strength': momentum_result['momentum_strength'],
            'is_active_momentum': momentum_result['is_active_blast_off'],
            'momentum_direction': momentum_result['trend_direction'],
        }

    def scan_all_stocks(self, df_stocks: pd.DataFrame, df_market: pd.DataFrame) -> pd.DataFrame:
        """
        Scan all stocks and return ranking matrix.
        """
        results = []

        for stock_id in df_stocks['stock_id'].unique():
            df_stock = df_stocks[df_stocks['stock_id'] == stock_id].copy()
            result = self.scan_stock(df_stock, df_market)
            results.append(result)

        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values('composite_score', ascending=False)

        return results_df


# ============================================================================
# SECTION 7: OUTPUT & RANKING MATRIX
# ============================================================================

def generate_ranking_table(results_df: pd.DataFrame, top_n: int = 20) -> str:
    """
    Generate formatted ranking matrix table of top 20 stocks.
    """
    top_stocks = results_df.head(top_n).copy()

    # Format columns for readability
    top_stocks['Rank'] = range(1, len(top_stocks) + 1)
    top_stocks['Ticker'] = top_stocks['ticker']
    top_stocks['Composite Score'] = top_stocks['composite_score'].apply(lambda x: f"{x:.3f}")
    top_stocks['Calendar Edge'] = top_stocks['cycle_edge'].apply(lambda x: f"{x:.2f}")
    top_stocks['Div Count'] = top_stocks['divergence_count'].astype(int)
    top_stocks['Div Intensity'] = top_stocks['divergence_intensity'].apply(lambda x: f"{x:.2f}")
    top_stocks['Failed BO'] = top_stocks['failed_breakouts'].astype(int)
    top_stocks['Reversal %'] = (top_stocks['failure_rate'] * 100).apply(lambda x: f"{x:.1f}%")
    top_stocks['Blast-Off'] = top_stocks['blast_off_signals'].astype(int)
    top_stocks['Momentum'] = top_stocks['momentum_strength'].apply(lambda x: f"{x:.2f}")
    top_stocks['Active'] = top_stocks['is_active_momentum'].apply(lambda x: "✓" if x else "")

    # Select columns for display
    display_df = top_stocks[[
        'Rank', 'Ticker', 'Composite Score',
        'Calendar Edge', 'Div Count', 'Div Intensity',
        'Failed BO', 'Reversal %', 'Blast-Off', 'Momentum', 'Active'
    ]]

    # Format as table
    output = "\n" + "="*150 + "\n"
    output += "LARRY WILLIAMS MACRO CYCLE & PATTERN SCANNER — TOP 20 STOCKS\n"
    output += "="*150 + "\n\n"

    output += display_df.to_string(index=False)

    output += "\n\n" + "="*150 + "\n"
    output += "PATTERN DEFINITIONS:\n"
    output += "  Composite Score: Weighted score (0-1) combining all 4 patterns\n"
    output += "  Calendar Edge: 28-day cycle bias (-1 to 1, positive = bullish)\n"
    output += "  Div Count: Number of volume-price divergence signals\n"
    output += "  Div Intensity: Average intensity of divergence (0-1)\n"
    output += "  Failed BO: Number of failed 20-day range breakouts\n"
    output += "  Reversal %: % of breakouts that failed and reversed\n"
    output += "  Blast-Off: Number of 3-day range expansion signals\n"
    output += "  Momentum: Strength of momentum accumulation (0-1)\n"
    output += "  Active: Recent signal in last 3 days\n"
    output += "="*150 + "\n"

    return output


# ============================================================================
# SECTION 8: MAIN EXECUTION
# ============================================================================

def main():
    """Execute complete Larry Williams cycle scanner."""

    print("\n" + "="*80)
    print("LARRY WILLIAMS MACRO CYCLE & PATTERN SCANNER")
    print("="*80)

    # Configuration
    config = ScannerConfig(
        n_stocks=500,
        n_days=1260,  # 5 years
        lookback_days=20,
    )

    # Generate synthetic data
    print(f"\n[1/5] Generating OHLCV data for {config.n_stocks} stocks over {config.n_days} days...")
    generator = DataGenerator(n_stocks=config.n_stocks, n_days=config.n_days)
    df_stocks, df_spy = generator.generate()
    print(f"✓ Generated {len(df_stocks):,} stock records + {len(df_spy)} market records")

    # Initialize scanner
    print(f"\n[2/5] Initializing master scanner...")
    scanner = LarryWilliamsMasterScanner(config)
    print(f"✓ Ready to scan patterns:")
    print(f"  - 28-Day Calendar/Lunar Cycle")
    print(f"  - Volume-Price Divergence")
    print(f"  - Accumulation/Distribution Reversals")
    print(f"  - Blast-Off Momentum")

    # Scan all stocks
    print(f"\n[3/5] Scanning {config.n_stocks} stocks...")
    results_df = scanner.scan_all_stocks(df_stocks, df_spy)
    print(f"✓ Scanned all {len(results_df)} stocks")

    # Summary statistics
    print(f"\n[4/5] Generating summary statistics...")
    print(f"\nComposite Score Distribution:")
    print(f"  Mean: {results_df['composite_score'].mean():.3f}")
    print(f"  Median: {results_df['composite_score'].median():.3f}")
    print(f"  Std: {results_df['composite_score'].std():.3f}")
    print(f"  Min: {results_df['composite_score'].min():.3f}")
    print(f"  Max: {results_df['composite_score'].max():.3f}")

    print(f"\nPattern Signal Frequency:")
    print(f"  Stocks with divergence signals: {(results_df['divergence_count'] > 0).sum()} ({100*(results_df['divergence_count'] > 0).mean():.1f}%)")
    print(f"  Stocks with failed breakouts: {(results_df['failed_breakouts'] > 0).sum()} ({100*(results_df['failed_breakouts'] > 0).mean():.1f}%)")
    print(f"  Stocks with blast-off signals: {(results_df['blast_off_signals'] > 0).sum()} ({100*(results_df['blast_off_signals'] > 0).mean():.1f}%)")
    print(f"  Stocks with active momentum: {results_df['is_active_momentum'].sum()} ({100*results_df['is_active_momentum'].mean():.1f}%)")

    # Generate ranking table
    print(f"\n[5/5] Generating ranking matrix...")
    ranking_table = generate_ranking_table(results_df, top_n=20)
    print(ranking_table)

    # Save results
    output_dir = Path('/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data')
    output_dir.mkdir(exist_ok=True)

    # Save full results
    results_path = output_dir / 'larry_williams_scan_results.csv'
    results_df.to_csv(results_path, index=False)
    print(f"\n[SAVED] Full results: {results_path}")

    # Save ranking table
    ranking_path = output_dir / 'larry_williams_ranking.txt'
    with open(ranking_path, 'w') as f:
        f.write(ranking_table)
    print(f"[SAVED] Ranking table: {ranking_path}")

    print("\n" + "="*80)
    print("✓ SCAN COMPLETE")
    print("="*80)

    return results_df


if __name__ == '__main__':
    results = main()
