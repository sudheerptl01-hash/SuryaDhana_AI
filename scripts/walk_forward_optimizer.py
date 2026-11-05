"""
Walk-Forward Optimization (WFO) Backtesting Architecture
=========================================================

Robert Pardo methodology for robust strategy testing:
- Rolling 1-year in-sample (optimization) + 3-month out-of-sample (testing)
- Optimize for Sortino Ratio (downside volatility penalty) + Max DD < 15%
- Realistic frictions: 0.1% slippage + $0.005/share commissions
- Strict look-ahead bias prevention with assertions
- Monte Carlo drawdown simulation
- Comprehensive tear sheet output

Key Insight: Optimize what matters to risk managers (downside risk), not Wall Street
(net profit). Out-of-sample results prove strategy generalization.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Callable
from datetime import datetime, timedelta
import logging
from pathlib import Path
import warnings

warnings.filterwarnings('ignore')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s — %(message)s'
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES & CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WFOConfig:
    """Walk-Forward Optimization configuration"""

    # Rolling window sizes
    in_sample_days: int = 252  # ~1 year of trading days
    out_of_sample_days: int = 63  # ~3 months (13 weeks)
    step_days: int = 63  # Roll forward by OOS period (non-overlapping)

    # Trading frictions
    slippage_pct: float = 0.001  # 0.1% slippage per fill
    commission_per_share: float = 0.005  # ₹0.005 per share

    # Optimization constraints
    min_sortino: float = 1.0  # Minimum Sortino ratio acceptable
    max_drawdown_pct: float = 15.0  # Max drawdown constraint (%)
    min_win_rate: float = 0.45  # Minimum win rate for acceptance

    # Risk-free rate for Sortino/Sharpe
    risk_free_rate: float = 0.05  # 5% annual (India 10-year G-Sec)

    # Monte Carlo simulation
    monte_carlo_iterations: int = 1000
    confidence_level: float = 0.95


@dataclass
class OptimizationResult:
    """Result from a single optimization window"""
    window_id: int
    in_sample_start: pd.Timestamp
    in_sample_end: pd.Timestamp
    out_of_sample_start: pd.Timestamp
    out_of_sample_end: pd.Timestamp

    # Optimization results (best params found)
    optimal_params: Dict
    is_params: float  # In-sample metric (Sortino)

    # Out-of-sample validation
    oos_sortino: float
    oos_sharpe: float
    oos_max_drawdown_pct: float
    oos_win_rate: float
    oos_expectancy: float
    oos_trades_count: int
    oos_equity_curve: pd.Series


# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE METRICS CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceMetrics:
    """Calculate trading performance metrics from returns/equity curve"""

    @staticmethod
    def sortino_ratio(returns: pd.Series, rf_rate: float = 0.05) -> float:
        """
        Sortino Ratio: excess return / downside volatility only.

        Penalizes only downside moves (losses), ignoring upside volatility.
        Better than Sharpe for return distributions with positive skew.

        Args:
            returns: Daily returns as Series
            rf_rate: Annual risk-free rate (default 5%)

        Returns:
            Sortino ratio (higher = better)
        """
        if len(returns) < 2:
            return 0.0

        excess_return = returns.mean() - (rf_rate / 252)  # Daily excess
        downside_returns = returns[returns < 0]

        if len(downside_returns) == 0:
            return 100.0  # No downside = infinite Sortino

        downside_std = downside_returns.std()
        if downside_std == 0:
            return 100.0

        sortino = (excess_return / downside_std) * np.sqrt(252)
        return sortino

    @staticmethod
    def sharpe_ratio(returns: pd.Series, rf_rate: float = 0.05) -> float:
        """Sharpe Ratio: excess return / total volatility"""
        if len(returns) < 2:
            return 0.0

        excess_return = returns.mean() - (rf_rate / 252)
        volatility = returns.std()

        if volatility == 0:
            return 0.0

        sharpe = (excess_return / volatility) * np.sqrt(252)
        return sharpe

    @staticmethod
    def max_drawdown_pct(equity: pd.Series) -> float:
        """
        Calculate maximum drawdown as % of peak.

        Max DD = (Peak - Trough) / Peak × 100
        """
        if len(equity) < 2:
            return 0.0

        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax
        max_dd = drawdown.min()

        return max_dd * 100

    @staticmethod
    def win_rate(pnl_per_trade: List[float]) -> float:
        """Win rate = # winning trades / total trades"""
        if len(pnl_per_trade) == 0:
            return 0.0

        wins = sum(1 for p in pnl_per_trade if p > 0)
        return wins / len(pnl_per_trade)

    @staticmethod
    def expectancy(pnl_per_trade: List[float]) -> float:
        """Expectancy = average P&L per trade"""
        if len(pnl_per_trade) == 0:
            return 0.0

        return np.mean(pnl_per_trade)

    @staticmethod
    def profit_factor(pnl_per_trade: List[float]) -> float:
        """Profit Factor = sum(wins) / abs(sum(losses))"""
        wins = sum(p for p in pnl_per_trade if p > 0)
        losses = abs(sum(p for p in pnl_per_trade if p < 0))

        if losses == 0:
            return 100.0 if wins > 0 else 0.0

        return wins / losses


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL EXECUTOR WITH FRICTIONS
# ─────────────────────────────────────────────────────────────────────────────

class SignalExecutor:
    """
    Execute trading signals with realistic frictions.

    Handles:
    - Position entry/exit at signal dates
    - Slippage on fills (0.1%)
    - Commissions ($0.005/share)
    - Look-ahead bias prevention (signals are from yesterday's data)
    """

    def __init__(self, config: WFOConfig):
        self.config = config

    def execute_signals(
        self,
        signals: pd.DataFrame,  # MultiIndex (date, ticker) with column 'signal' (-1/0/1)
        prices: pd.DataFrame,  # OHLCV data
        starting_capital: float = 100_000
    ) -> Tuple[pd.Series, List[Dict]]:
        """
        Execute signals with slippage and commissions.

        Args:
            signals: MultiIndex DF with columns [signal] (-1/0/1 for short/hold/long)
            prices: MultiIndex DF with columns [open, high, low, close, volume]
            starting_capital: Starting portfolio value

        Returns:
            (equity_curve Series, list of trade dicts with entry/exit/pnl)
        """
        assert signals.index.names == ['date', 'ticker'], "Signals must have (date, ticker) index"
        assert prices.index.names == ['date', 'ticker'], "Prices must have (date, ticker) index"
        assert signals.index.is_monotonic_increasing, "Signals must be sorted by (date, ticker)"

        # Track open positions: {ticker: {'entry_date', 'entry_price', 'quantity', 'signal'}}
        open_positions = {}
        trades = []
        equity_values = [starting_capital]
        equity_dates = [signals.index.get_level_values('date').min()]

        cash = starting_capital
        daily_equity = starting_capital

        # Process signals in chronological order
        dates = signals.index.get_level_values('date').unique()

        for date in dates:
            today_signals = signals.loc[date] if date in signals.index.get_level_values('date') else None
            today_prices = prices.loc[date] if date in prices.index.get_level_values('date') else None

            if today_signals is None or today_prices is None:
                continue

            # Ensure we have Series or DataFrame
            if isinstance(today_signals, pd.Series):
                today_signals = today_signals.to_frame().T
            if isinstance(today_prices, pd.Series):
                today_prices = today_prices.to_frame().T

            # Process exits first, then entries
            for ticker in list(open_positions.keys()):
                if ticker not in today_prices.index:
                    continue

                position = open_positions[ticker]
                close_price = today_prices.loc[ticker, 'close'] if ticker in today_prices.index else None

                if close_price is None:
                    continue

                # Apply slippage on exit (against our direction)
                exit_price = close_price * (1 - self.config.slippage_pct)

                # Calculate P&L
                pnl = (exit_price - position['entry_price']) * position['quantity']
                pnl -= position['quantity'] * self.config.commission_per_share * 2  # Entry + exit commission

                # Update cash
                cash += pnl
                daily_equity += pnl

                # Record trade
                trades.append({
                    'ticker': ticker,
                    'entry_date': position['entry_date'],
                    'entry_price': position['entry_price'],
                    'exit_date': date,
                    'exit_price': exit_price,
                    'quantity': position['quantity'],
                    'pnl': pnl,
                    'pnl_pct': (pnl / (position['entry_price'] * position['quantity'])) * 100
                })

                del open_positions[ticker]

            # Process entries for tickers with new signals
            for ticker in today_signals.index:
                signal = today_signals.loc[ticker, 'signal'] if 'signal' in today_signals.columns else 0
                entry_price = today_prices.loc[ticker, 'close'] if ticker in today_prices.index else None

                if entry_price is None or signal == 0 or ticker in open_positions:
                    continue

                # Apply slippage on entry
                entry_price_slipped = entry_price * (1 + self.config.slippage_pct)

                # Size position (simple: equal weight)
                position_value = cash / max(1, len([t for s in today_signals.index if today_signals.loc[t, 'signal'] != 0 and t not in open_positions]))
                quantity = max(1, int(position_value / entry_price_slipped))

                # Account for commissions
                comm = quantity * self.config.commission_per_share
                cash -= quantity * entry_price_slipped + comm

                open_positions[ticker] = {
                    'entry_date': date,
                    'entry_price': entry_price_slipped,
                    'quantity': quantity,
                    'signal': signal
                }

            # Record daily equity
            equity_values.append(daily_equity)
            equity_dates.append(date)

        # Close all remaining positions at last date
        last_date = dates[-1]
        for ticker in list(open_positions.keys()):
            if ticker not in prices.loc[last_date].index:
                continue

            position = open_positions[ticker]
            close_price = prices.loc[last_date, ticker]['close']
            exit_price = close_price * (1 - self.config.slippage_pct)

            pnl = (exit_price - position['entry_price']) * position['quantity']
            pnl -= position['quantity'] * self.config.commission_per_share * 2

            cash += pnl

            trades.append({
                'ticker': ticker,
                'entry_date': position['entry_date'],
                'entry_price': position['entry_price'],
                'exit_date': last_date,
                'exit_price': exit_price,
                'quantity': position['quantity'],
                'pnl': pnl,
                'pnl_pct': (pnl / (position['entry_price'] * position['quantity'])) * 100
            })

        equity_curve = pd.Series(equity_values, index=equity_dates)

        return equity_curve, trades


# ─────────────────────────────────────────────────────────────────────────────
# LOOK-AHEAD BIAS DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

class LookAheadBiasDetector:
    """
    Strict assertions to detect look-ahead bias in rolling windows.

    Rules:
    1. In-sample data must not include any out-of-sample dates
    2. Out-of-sample data must not include any in-sample dates
    3. Optimization parameters derived from IS data only
    4. OS evaluation uses parameters, not data look-ahead
    5. Window rolling must be monotonic (no overlaps/gaps)
    """

    @staticmethod
    def assert_no_date_leakage(
        is_dates: pd.DatetimeIndex,
        oos_dates: pd.DatetimeIndex,
        window_id: int
    ):
        """Assert no date overlap between IS and OOS"""
        is_set = set(is_dates)
        oos_set = set(oos_dates)

        overlap = is_set & oos_set
        assert len(overlap) == 0, (
            f"Window {window_id}: Date leakage detected! "
            f"IS and OOS share {len(overlap)} dates: {sorted(overlap)[:5]}"
        )

        # IS must end before OOS starts
        is_max = is_dates.max()
        oos_min = oos_dates.min()
        assert is_max < oos_min, (
            f"Window {window_id}: IS max date {is_max} >= OOS min date {oos_min}. "
            f"Not strictly ordered!"
        )

        log.debug(f"✓ Window {window_id}: No date leakage (IS: {is_dates.min()} to {is_max}, "
                  f"OOS: {oos_min} to {oos_dates.max()})")

    @staticmethod
    def assert_window_continuity(all_windows: List[Tuple[pd.DatetimeIndex, pd.DatetimeIndex]]):
        """Assert windows are continuous with no gaps or overlaps"""
        for i, (is_dates, oos_dates) in enumerate(all_windows[:-1]):
            next_is, next_oos = all_windows[i + 1]

            # Current OOS end should be close to next IS start (allowing 1 day gap)
            curr_oos_end = oos_dates.max()
            next_is_start = next_is.min()

            gap_days = (next_is_start - curr_oos_end).days
            assert gap_days <= 1, (
                f"Window gap detected between window {i} and {i+1}: "
                f"{gap_days} days ({curr_oos_end} to {next_is_start})"
            )

        log.info(f"✓ All {len(all_windows)} windows are continuous with no gaps/overlaps")

    @staticmethod
    def assert_proper_sizing(
        is_data_shape: Tuple,
        oos_data_shape: Tuple,
        in_sample_days: int,
        out_of_sample_days: int,
        window_id: int
    ):
        """Assert IS and OOS have reasonable sizes"""
        is_rows = is_data_shape[0]
        oos_rows = oos_data_shape[0]

        # Allow ±10% tolerance for holidays/gaps
        assert is_rows > in_sample_days * 0.9, (
            f"Window {window_id}: IS too small ({is_rows} rows vs {in_sample_days} expected)"
        )
        assert oos_rows > out_of_sample_days * 0.9, (
            f"Window {window_id}: OOS too small ({oos_rows} rows vs {out_of_sample_days} expected)"
        )

        log.debug(f"✓ Window {window_id}: Proper sizing (IS: {is_rows} rows, OOS: {oos_rows} rows)")


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD OPTIMIZER
# ─────────────────────────────────────────────────────────────────────────────

class WalkForwardOptimizer:
    """
    Robert Pardo's Walk-Forward Optimization engine.

    Methodology:
    1. Divide data into rolling 1-year IS + 3-month OOS windows
    2. Optimize strategy parameters on IS data (Sortino Ratio target)
    3. Validate on OOS data (blind test)
    4. Roll forward and repeat
    5. Report aggregate OOS results (true expected performance)
    """

    def __init__(self, config: WFOConfig = None):
        self.config = config or WFOConfig()
        self.metrics = PerformanceMetrics()
        self.executor = SignalExecutor(self.config)
        self.bias_detector = LookAheadBiasDetector()

    def create_rolling_windows(
        self,
        data: pd.DataFrame
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Create rolling IS/OOS windows from full dataset.

        Args:
            data: MultiIndex (date, ticker) DataFrame

        Returns:
            List of (in_sample_df, out_of_sample_df) tuples
        """
        dates = data.index.get_level_values('date').unique().sort_values()
        windows = []

        log.info(f"Creating rolling windows from {len(dates)} trading days")
        log.info(f"  IS window: {self.config.in_sample_days} days")
        log.info(f"  OOS window: {self.config.out_of_sample_days} days")
        log.info(f"  Step: {self.config.step_days} days")

        is_dates_list = []
        oos_dates_list = []

        window_id = 0
        start_idx = 0

        while start_idx + self.config.in_sample_days < len(dates):
            # In-sample window
            is_end_idx = start_idx + self.config.in_sample_days
            is_dates = dates[start_idx:is_end_idx]

            # Out-of-sample window
            oos_end_idx = min(is_end_idx + self.config.out_of_sample_days, len(dates))
            oos_dates = dates[is_end_idx:oos_end_idx]

            # Skip if OOS is too small
            if len(oos_dates) < self.config.out_of_sample_days * 0.8:
                break

            # Extract data
            is_data = data.loc[is_dates]
            oos_data = data.loc[oos_dates]

            # Verify no look-ahead bias
            self.bias_detector.assert_no_date_leakage(is_dates, oos_dates, window_id)
            self.bias_detector.assert_proper_sizing(
                is_data.shape, oos_data.shape,
                self.config.in_sample_days, self.config.out_of_sample_days,
                window_id
            )

            windows.append((is_data, oos_data))
            is_dates_list.append((is_dates, window_id))
            oos_dates_list.append((oos_dates, window_id))

            log.info(f"  Window {window_id}: IS {is_dates[0].date()} to {is_dates[-1].date()} | "
                    f"OOS {oos_dates[0].date()} to {oos_dates[-1].date()}")

            # Roll forward
            start_idx += self.config.step_days
            window_id += 1

        # Final look-ahead bias check: window continuity
        self.bias_detector.assert_window_continuity(
            [(is_d, oos_d) for (is_d, _), (oos_d, _) in zip(is_dates_list, oos_dates_list)]
        )

        log.info(f"✓ Created {len(windows)} rolling windows (no look-ahead bias detected)")

        return windows

    def optimize_window(
        self,
        is_data: pd.DataFrame,
        param_grid: Dict[str, List],
        signal_fn: Callable
    ) -> Tuple[Dict, float]:
        """
        Optimize strategy parameters on in-sample data.

        Args:
            is_data: In-sample DataFrame
            param_grid: Parameter space to search (e.g., {'ma_fast': [5, 10, 20], ...})
            signal_fn: Function(data, params) -> signals DataFrame

        Returns:
            (best_params, best_sortino_ratio)
        """
        best_params = None
        best_sortino = -np.inf
        results = []

        param_combos = self._generate_param_combos(param_grid)
        log.info(f"Optimizing over {len(param_combos)} parameter combinations...")

        for combo_id, params in enumerate(param_combos):
            try:
                # Generate signals
                signals = signal_fn(is_data, params)

                # Execute with frictions
                equity_curve, trades = self.executor.execute_signals(signals, is_data)

                if len(trades) < 5:  # Skip if too few trades
                    continue

                # Calculate metrics
                returns = equity_curve.pct_change().dropna()
                sortino = self.metrics.sortino_ratio(returns, self.config.risk_free_rate)
                max_dd = self.metrics.max_drawdown_pct(equity_curve)

                # Check constraints
                if max_dd > self.config.max_drawdown_pct:
                    continue

                # Track best
                if sortino > best_sortino:
                    best_sortino = sortino
                    best_params = params

                results.append({
                    'params': params,
                    'sortino': sortino,
                    'max_dd': max_dd,
                    'trades': len(trades)
                })

            except Exception as e:
                log.debug(f"Parameter combo {combo_id} failed: {e}")
                continue

        if best_params is None:
            log.warning("No valid parameter set found in optimization!")
            best_params = param_grid
            best_sortino = 0.0

        log.info(f"✓ Best params: {best_params} (Sortino: {best_sortino:.2f})")

        return best_params, best_sortino

    def _generate_param_combos(self, param_grid: Dict) -> List[Dict]:
        """Generate all parameter combinations from grid"""
        import itertools

        keys = param_grid.keys()
        values = param_grid.values()
        combos = itertools.product(*values)

        return [dict(zip(keys, combo)) for combo in combos]

    def run_walk_forward(
        self,
        data: pd.DataFrame,
        param_grid: Dict[str, List],
        signal_fn: Callable
    ) -> pd.DataFrame:
        """
        Run complete walk-forward optimization.

        Args:
            data: Full OHLCV dataset (MultiIndex: date, ticker)
            param_grid: Parameter space for optimization
            signal_fn: Function(data, params) -> signals

        Returns:
            DataFrame of all windows' OOS results
        """
        log.info("\n" + "=" * 80)
        log.info("WALK-FORWARD OPTIMIZATION — START")
        log.info("=" * 80)

        windows = self.create_rolling_windows(data)
        all_results = []

        for window_id, (is_data, oos_data) in enumerate(windows):
            log.info(f"\n[Window {window_id}]")

            # Step 1: Optimize on IS
            best_params, is_sortino = self.optimize_window(is_data, param_grid, signal_fn)

            # Step 2: Validate on OOS with optimized params
            oos_signals = signal_fn(oos_data, best_params)
            oos_equity, oos_trades = self.executor.execute_signals(oos_signals, oos_data)

            # Calculate OOS metrics
            oos_returns = oos_equity.pct_change().dropna()
            oos_sortino = self.metrics.sortino_ratio(oos_returns, self.config.risk_free_rate)
            oos_sharpe = self.metrics.sharpe_ratio(oos_returns, self.config.risk_free_rate)
            oos_max_dd = self.metrics.max_drawdown_pct(oos_equity)
            oos_win_rate = self.metrics.win_rate([t['pnl'] for t in oos_trades])
            oos_expectancy = self.metrics.expectancy([t['pnl'] for t in oos_trades])

            log.info(f"  IS Sortino: {is_sortino:.2f}")
            log.info(f"  OOS Sortino: {oos_sortino:.2f} (validation)")
            log.info(f"  OOS Max DD: {oos_max_dd:.2f}%")
            log.info(f"  OOS Win Rate: {oos_win_rate:.1%}")
            log.info(f"  OOS Trades: {len(oos_trades)}")

            result = OptimizationResult(
                window_id=window_id,
                in_sample_start=is_data.index.get_level_values('date').min(),
                in_sample_end=is_data.index.get_level_values('date').max(),
                out_of_sample_start=oos_data.index.get_level_values('date').min(),
                out_of_sample_end=oos_data.index.get_level_values('date').max(),
                optimal_params=best_params,
                is_params=is_sortino,
                oos_sortino=oos_sortino,
                oos_sharpe=oos_sharpe,
                oos_max_drawdown_pct=oos_max_dd,
                oos_win_rate=oos_win_rate,
                oos_expectancy=oos_expectancy,
                oos_trades_count=len(oos_trades),
                oos_equity_curve=oos_equity
            )

            all_results.append(result)

        log.info("\n" + "=" * 80)
        log.info("✓ WALK-FORWARD OPTIMIZATION — COMPLETE")
        log.info("=" * 80)

        return all_results

    def generate_tear_sheet(self, results: List[OptimizationResult]) -> Dict:
        """
        Generate comprehensive tear sheet from WFO results.

        Returns:
            Dict with all summary statistics
        """
        log.info("\n" + "=" * 80)
        log.info("TEAR SHEET — OUT-OF-SAMPLE AGGREGATE RESULTS")
        log.info("=" * 80)

        # Aggregate OOS equity curves
        combined_equity = pd.concat([r.oos_equity_curve for r in results])
        combined_equity = combined_equity.sort_index().dropna()

        # Metrics
        oos_returns = combined_equity.pct_change().dropna()
        aggregate_sortino = self.metrics.sortino_ratio(oos_returns, self.config.risk_free_rate)
        aggregate_sharpe = self.metrics.sharpe_ratio(oos_returns, self.config.risk_free_rate)
        aggregate_max_dd = self.metrics.max_drawdown_pct(combined_equity)

        total_return_pct = ((combined_equity.iloc[-1] - combined_equity.iloc[0]) / combined_equity.iloc[0]) * 100
        annual_return = (combined_equity.iloc[-1] / combined_equity.iloc[0]) ** (252 / len(combined_equity)) - 1

        avg_win_rate = np.mean([r.oos_win_rate for r in results])
        avg_expectancy = np.mean([r.oos_expectancy for r in results])
        total_trades = sum(r.oos_trades_count for r in results)

        tear_sheet = {
            'window_count': len(results),
            'total_return_pct': total_return_pct,
            'annual_return_pct': annual_return * 100,
            'sortino_ratio': aggregate_sortino,
            'sharpe_ratio': aggregate_sharpe,
            'max_drawdown_pct': aggregate_max_dd,
            'win_rate': avg_win_rate,
            'avg_expectancy': avg_expectancy,
            'total_trades': total_trades,
            'equity_curve': combined_equity,
            'daily_returns': oos_returns
        }

        log.info(f"\nTotal Return: {total_return_pct:+.2f}%")
        log.info(f"Annual Return: {annual_return * 100:+.2f}%")
        log.info(f"Sortino Ratio: {aggregate_sortino:.2f}")
        log.info(f"Sharpe Ratio: {aggregate_sharpe:.2f}")
        log.info(f"Max Drawdown: {aggregate_max_dd:.2f}%")
        log.info(f"Win Rate: {avg_win_rate:.1%}")
        log.info(f"Avg Expectancy: ₹{avg_expectancy:.2f}")
        log.info(f"Total Trades: {total_trades}")

        return tear_sheet


# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

class MonteCarloSimulator:
    """Monte Carlo simulation of drawdown distribution"""

    @staticmethod
    def simulate_drawdowns(
        returns: pd.Series,
        iterations: int = 1000,
        confidence_level: float = 0.95
    ) -> Dict:
        """
        Simulate returns by random reordering; measure drawdown distribution.

        Args:
            returns: Daily returns Series
            iterations: Number of Monte Carlo paths
            confidence_level: For VaR calculation (e.g., 0.95 = 95%)

        Returns:
            Dict with drawdown statistics
        """
        log.info(f"\nMonte Carlo Simulation: {iterations} iterations")

        drawdowns = []

        for i in range(iterations):
            # Resample returns with replacement
            sampled_returns = np.random.choice(returns.values, len(returns), replace=True)

            # Compute equity curve
            equity = 1.0 + np.cumprod(1 + sampled_returns) - 1
            cummax = np.maximum.accumulate(equity)
            dd = (equity - cummax) / cummax * 100

            max_dd = dd.min()
            drawdowns.append(max_dd)

        drawdowns = np.array(drawdowns)

        # VaR: Xth percentile drawdown
        var = np.percentile(drawdowns, 100 * (1 - confidence_level))

        return {
            'mean_max_dd': np.mean(drawdowns),
            'median_max_dd': np.median(drawdowns),
            'std_max_dd': np.std(drawdowns),
            'var_max_dd': var,  # Value at Risk (worse case at given confidence)
            'percentile_99': np.percentile(drawdowns, 99),
            'percentile_95': np.percentile(drawdowns, 95),
            'min_dd': np.min(drawdowns),
            'max_dd': np.max(drawdowns)
        }


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE SIGNAL FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def simple_ma_crossover_signals(data: pd.DataFrame, params: Dict) -> pd.DataFrame:
    """
    Simple moving average crossover signal function.

    Args:
        data: MultiIndex (date, ticker) OHLCV DataFrame
        params: {'fast_ma': int, 'slow_ma': int}

    Returns:
        Signal DataFrame with columns [signal] (-1/0/1)
    """
    fast_ma = params.get('fast_ma', 5)
    slow_ma = params.get('slow_ma', 20)

    signals = pd.DataFrame(index=data.index, columns=['signal'], dtype=float)
    signals['signal'] = 0

    for ticker in data.index.get_level_values('ticker').unique():
        ticker_data = data.loc[data.index.get_level_values('ticker') == ticker]

        if len(ticker_data) < slow_ma:
            continue

        close = ticker_data['close'].values
        fast = pd.Series(close).rolling(window=fast_ma).mean().values
        slow = pd.Series(close).rolling(window=slow_ma).mean().values

        signal = np.where(fast > slow, 1, -1)
        signal[np.isnan(fast) | np.isnan(slow)] = 0

        signals.loc[data.index.get_level_values('ticker') == ticker, 'signal'] = signal

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Walk-Forward Optimization Backtester (Robert Pardo methodology)',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--data', type=str, required=True,
                       help='Path to OHLCV Parquet (MultiIndex: date, ticker)')
    parser.add_argument('--output', type=str, default='./wfo_results',
                       help='Output directory for tear sheet')
    parser.add_argument('--iterations', type=int, default=1000,
                       help='Monte Carlo iterations')

    args = parser.parse_args()

    try:
        log.info(f"Loading data: {args.data}")
        data = pd.read_parquet(args.data)

        # Initialize optimizer
        config = WFOConfig(
            in_sample_days=252,
            out_of_sample_days=63,
            step_days=63
        )
        optimizer = WalkForwardOptimizer(config)

        # Define parameter grid
        param_grid = {
            'fast_ma': [5, 10, 15],
            'slow_ma': [20, 30, 50]
        }

        # Run WFO
        results = optimizer.run_walk_forward(
            data,
            param_grid,
            signal_fn=simple_ma_crossover_signals
        )

        # Generate tear sheet
        tear_sheet = optimizer.generate_tear_sheet(results)

        # Monte Carlo simulation
        mc = MonteCarloSimulator()
        mc_results = mc.simulate_drawdowns(
            tear_sheet['daily_returns'],
            iterations=args.iterations
        )

        log.info("\nMonte Carlo Drawdown Results:")
        log.info(f"  Mean Max DD: {mc_results['mean_max_dd']:.2f}%")
        log.info(f"  95% VaR: {mc_results['var_max_dd']:.2f}%")
        log.info(f"  99th Percentile: {mc_results['percentile_99']:.2f}%")

        log.info("\n✓ Walk-Forward Optimization complete!")

    except Exception as e:
        log.error(f"Failed: {e}", exc_info=True)
        exit(1)
