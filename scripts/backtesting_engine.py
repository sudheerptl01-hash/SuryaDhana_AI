"""
Comprehensive Backtesting Engine
=================================

Production-grade event-driven and vectorized backtesting framework for 500+ stocks.

Core Components:
1. DataHandler: Multi-index data management, corporate actions, look-ahead bias prevention
2. PortfolioState: Cash, positions, equity tracking, margin, drawdowns
3. ExecutionModel: Transaction costs, slippage, short borrow costs
4. RiskManager: Stops, trailing stops, sector limits, VaR constraints
5. PerformanceReporter: Comprehensive metrics, Monte Carlo simulation

Design: Robert Pardo methodology with institutional-grade risk management.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s — %(message)s'
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS & DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

class OrderType(Enum):
    """Order type enumeration"""
    BUY = 1
    SELL = -1
    CLOSE = 0


class OrderStatus(Enum):
    """Order status enumeration"""
    PENDING = 'PENDING'
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'
    REJECTED = 'REJECTED'


@dataclass
class Order:
    """Represents a single order"""
    date: pd.Timestamp
    ticker: str
    order_type: OrderType
    quantity: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    max_slippage_pct: float = 0.01  # 1% max slippage
    status: OrderStatus = OrderStatus.PENDING
    filled_price: Optional[float] = None
    filled_quantity: int = 0
    commission: float = 0.0
    slippage_cost: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def __repr__(self):
        return (f"Order(date={self.date.date()}, {self.ticker}, "
                f"{self.order_type.name}, qty={self.quantity}, "
                f"status={self.status.value})")


@dataclass
class Position:
    """Represents a single position in a stock"""
    ticker: str
    shares: int = 0  # Positive = long, negative = short
    avg_entry_price: float = 0.0
    entry_date: Optional[pd.Timestamp] = None
    total_cost: float = 0.0  # Cost basis (cash paid in)
    realized_pnl: float = 0.0  # Realized profit/loss from closed positions
    borrow_cost: float = 0.0  # Cost to borrow shares (for shorts)

    @property
    def is_long(self) -> bool:
        return self.shares > 0

    @property
    def is_short(self) -> bool:
        return self.shares < 0

    @property
    def is_open(self) -> bool:
        return self.shares != 0

    def __repr__(self):
        if self.is_long:
            return f"Long {self.ticker}: {self.shares} @ ₹{self.avg_entry_price:.2f}"
        elif self.is_short:
            return f"Short {self.ticker}: {abs(self.shares)} @ ₹{self.avg_entry_price:.2f}"
        else:
            return f"Closed {self.ticker}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. DATA HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class CorporateAction:
    """Represent stock splits and dividends"""

    @staticmethod
    def adjust_price_for_split(price: float, split_ratio: float) -> float:
        """
        Adjust price backward for stock split.

        If stock 2:1 split (split_ratio=2), price halves.

        Args:
            price: Original price
            split_ratio: New shares / old shares (e.g., 2 for 2:1 split)

        Returns:
            Adjusted price
        """
        adjusted = price / split_ratio
        return adjusted

    @staticmethod
    def adjust_position_for_split(shares: int, split_ratio: float) -> int:
        """
        Adjust position for stock split.

        If 100 shares and 2:1 split, become 200 shares.

        Args:
            shares: Original share count
            split_ratio: New shares / old shares

        Returns:
            Adjusted share count
        """
        adjusted = int(shares * split_ratio)
        return adjusted


class DataHandler:
    """
    Manages OHLCV data with corporate action alignment.

    Prevents look-ahead bias by:
    - Returning only data up to current backtest date
    - Adjusting historical prices for splits/dividends
    - Enforcing date ordering
    """

    def __init__(self, ohlcv_df: pd.DataFrame, corporate_actions: Optional[Dict] = None):
        """
        Initialize DataHandler.

        Args:
            ohlcv_df: MultiIndex (date, ticker) OHLCV DataFrame
            corporate_actions: Dict of {date: {ticker: action_dict}}
                action_dict: {'split_ratio': float, 'dividend': float}
        """
        self.ohlcv_df = ohlcv_df.copy()
        self.corporate_actions = corporate_actions or {}
        self.current_date = None  # Track backtest date to prevent look-ahead

        self._validate_data()
        self._apply_corporate_actions()

    def _validate_data(self) -> None:
        """Validate OHLCV data structure and quality"""
        # Check MultiIndex
        assert isinstance(self.ohlcv_df.index, pd.MultiIndex), "Must have MultiIndex (date, ticker)"
        assert self.ohlcv_df.index.names == ['date', 'ticker'], "Index must be (date, ticker)"

        # Check required columns
        required_cols = {'open', 'high', 'low', 'close', 'volume'}
        df_cols = set(self.ohlcv_df.columns.str.lower())
        assert required_cols.issubset(df_cols), f"Missing columns: {required_cols - df_cols}"

        # Check sorting
        assert self.ohlcv_df.index.is_monotonic_increasing, "Data must be sorted by (date, ticker)"

        # Data quality
        assert (self.ohlcv_df['high'] >= self.ohlcv_df['low']).all(), "High < Low found"
        assert (self.ohlcv_df['close'] > 0).all(), "Non-positive close found"

        log.info(f"✓ Data validation passed: {len(self.ohlcv_df):,} rows, "
                f"{self.ohlcv_df.index.get_level_values('ticker').nunique()} tickers")

    def _apply_corporate_actions(self) -> None:
        """
        Apply corporate action adjustments to historical prices.

        Reverse-adjust all prices BEFORE each action date.

        Process:
        1. For each corporate action (earliest first)
        2. Find all dates BEFORE this action
        3. Adjust prices backward
        """
        if not self.corporate_actions:
            return

        for action_date_str, tickers_actions in sorted(self.corporate_actions.items()):
            action_date = pd.to_datetime(action_date_str)

            for ticker, action in tickers_actions.items():
                # Adjust prices BEFORE this date
                mask = (self.ohlcv_df.index.get_level_values('date') < action_date) & \
                       (self.ohlcv_df.index.get_level_values('ticker') == ticker)

                if 'split_ratio' in action:
                    ratio = action['split_ratio']
                    for col in ['open', 'high', 'low', 'close']:
                        self.ohlcv_df.loc[mask, col] = self.ohlcv_df.loc[mask, col].apply(
                            lambda p: CorporateAction.adjust_price_for_split(p, ratio)
                        )

                if 'dividend' in action:
                    dividend = action['dividend']
                    # Dividend reduces close price
                    self.ohlcv_df.loc[mask, 'close'] = self.ohlcv_df.loc[mask, 'close'] - dividend

        log.info(f"✓ Applied {len(self.corporate_actions)} corporate actions")

    def set_backtest_date(self, date: pd.Timestamp) -> None:
        """
        Set current backtest date (prevents look-ahead bias).

        Only data up to this date is accessible.

        Args:
            date: Current backtest date
        """
        self.current_date = date

    def get_current_price(self, ticker: str, date: Optional[pd.Timestamp] = None) -> float:
        """
        Get close price for ticker at date (no look-ahead).

        Args:
            ticker: Stock ticker
            date: Date (uses self.current_date if None)

        Returns:
            Close price at that date

        Raises:
            KeyError if date/ticker not found
        """
        if date is None:
            date = self.current_date

        assert date <= self.current_date, f"Cannot look ahead! {date} > {self.current_date}"

        try:
            return self.ohlcv_df.loc[(date, ticker), 'close']
        except KeyError:
            raise KeyError(f"No data for {ticker} on {date.date()}")

    def get_ohlcv(self, ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
        """
        Get OHLCV slice for ticker over date range (no look-ahead).

        Args:
            ticker: Stock ticker
            start_date: Start of range
            end_date: End of range

        Returns:
            DataFrame with OHLCV columns

        Raises:
            AssertionError if end_date > current_backtest_date (look-ahead)
        """
        assert end_date <= self.current_date, f"Cannot look ahead! {end_date} > {self.current_date}"

        mask = (self.ohlcv_df.index.get_level_values('date') >= start_date) & \
               (self.ohlcv_df.index.get_level_values('date') <= end_date) & \
               (self.ohlcv_df.index.get_level_values('ticker') == ticker)

        return self.ohlcv_df.loc[mask]

    def get_all_tickers(self) -> Set[str]:
        """Return set of all tickers in dataset"""
        return set(self.ohlcv_df.index.get_level_values('ticker').unique())

    def get_dates(self) -> pd.DatetimeIndex:
        """Return sorted list of all trading dates"""
        return self.ohlcv_df.index.get_level_values('date').unique().sort_values()


# ─────────────────────────────────────────────────────────────────────────────
# 2. PORTFOLIO STATE
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioState:
    """
    Track portfolio state: cash, positions, equity, margin, drawdowns.

    Maintains complete position history and daily equity.
    """

    def __init__(self, starting_capital: float = 100_000):
        """
        Initialize portfolio.

        Args:
            starting_capital: Starting cash (₹)
        """
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.positions: Dict[str, Position] = {}  # {ticker: Position}
        self.closed_positions: List[Position] = []

        # Equity curve
        self.equity_history: List[float] = [starting_capital]
        self.date_history: List[pd.Timestamp] = []

        # Drawdown tracking
        self.peak_equity = starting_capital
        self.max_drawdown = 0.0
        self.max_drawdown_date = None

        # Margin tracking
        self.margin_used = 0.0
        self.margin_available = 0.0
        self.margin_ratio = 0.0  # Cash / Total equity

    def add_position(self, ticker: str, shares: int, entry_price: float, entry_date: pd.Timestamp) -> None:
        """
        Add or update position.

        For averaging up/down, updates avg_entry_price.

        Args:
            ticker: Stock ticker
            shares: Number of shares (positive=long, negative=short)
            entry_price: Price per share
            entry_date: Date of entry
        """
        if ticker not in self.positions:
            self.positions[ticker] = Position(ticker=ticker)

        pos = self.positions[ticker]

        if pos.shares == 0:
            # New position
            pos.shares = shares
            pos.avg_entry_price = entry_price
            pos.entry_date = entry_date
            pos.total_cost = shares * entry_price

        else:
            # Averaging
            total_shares_after = pos.shares + shares
            total_cost_after = pos.total_cost + (shares * entry_price)

            if total_shares_after == 0:
                # Position closed
                pos.shares = 0
                pos.avg_entry_price = 0.0
                pos.total_cost = 0.0
                self.closed_positions.append(pos)
            else:
                # Update average entry price
                pos.shares = total_shares_after
                pos.avg_entry_price = total_cost_after / total_shares_after
                pos.total_cost = total_cost_after
                pos.entry_date = entry_date if pos.entry_date is None else pos.entry_date

    def close_position(self, ticker: str, exit_price: float) -> float:
        """
        Close position and calculate realized P&L.

        Args:
            ticker: Stock ticker
            exit_price: Exit price per share

        Returns:
            Realized P&L (₹)
        """
        if ticker not in self.positions or not self.positions[ticker].is_open:
            return 0.0

        pos = self.positions[ticker]

        # Realized P&L = (exit_price - entry_price) × shares
        realized_pnl = (exit_price - pos.avg_entry_price) * pos.shares

        pos.realized_pnl = realized_pnl
        self.cash += realized_pnl  # Add realized gain/loss to cash

        # Move to closed positions
        self.closed_positions.append(pos)
        del self.positions[ticker]

        return realized_pnl

    def get_current_positions_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total market value of all open positions.

        Total = Σ(shares × current_price) for each position

        Args:
            current_prices: {ticker: current_price}

        Returns:
            Total position value (₹)
        """
        total_value = 0.0

        for ticker, pos in self.positions.items():
            if ticker in current_prices:
                position_value = pos.shares * current_prices[ticker]
                total_value += position_value

        return total_value

    def get_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total unrealized P&L of all positions.

        Unrealized P&L = (current_price - entry_price) × shares

        Args:
            current_prices: {ticker: current_price}

        Returns:
            Total unrealized P&L (₹)
        """
        total_unrealized = 0.0

        for ticker, pos in self.positions.items():
            if ticker in current_prices:
                unrealized = (current_prices[ticker] - pos.avg_entry_price) * pos.shares
                total_unrealized += unrealized

        return total_unrealized

    def get_total_equity(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio equity.

        Total Equity = Cash + Σ(Position Value)

        Args:
            current_prices: {ticker: current_price}

        Returns:
            Total equity (₹)
        """
        position_value = self.get_current_positions_value(current_prices)
        total_equity = self.cash + position_value

        return total_equity

    def update_equity_history(self, total_equity: float, date: pd.Timestamp) -> None:
        """
        Update daily equity curve and tracking metrics.

        Also updates peak equity and drawdown.

        Args:
            total_equity: Current total equity
            date: Current date
        """
        self.equity_history.append(total_equity)
        self.date_history.append(date)

        # Update peak and drawdown
        if total_equity > self.peak_equity:
            self.peak_equity = total_equity

        drawdown = (total_equity - self.peak_equity) / self.peak_equity
        if drawdown < self.max_drawdown:
            self.max_drawdown = drawdown
            self.max_drawdown_date = date

    def get_max_drawdown_pct(self) -> float:
        """
        Get maximum drawdown as percentage.

        Returns:
            Max drawdown (negative %, e.g., -0.15 for -15%)
        """
        return self.max_drawdown * 100

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get position object for ticker"""
        return self.positions.get(ticker)

    def has_position(self, ticker: str) -> bool:
        """Check if open position exists"""
        return ticker in self.positions and self.positions[ticker].is_open

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all open positions"""
        return {t: p for t, p in self.positions.items() if p.is_open}


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXECUTION MODEL
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionModel:
    """
    Model trade execution with realistic costs.

    Costs modeled:
    1. Commission: Fixed per share ($0.005/share)
    2. Slippage: % of price based on order size relative to volume
    3. Short borrow: Interest rate on borrowed shares
    """

    def __init__(self, commission_per_share: float = 0.005, risk_free_rate: float = 0.05):
        """
        Initialize ExecutionModel.

        Args:
            commission_per_share: Commission (₹/share), default ₹0.005
            risk_free_rate: Annual interest rate for short positions (5%)
        """
        self.commission_per_share = commission_per_share
        self.risk_free_rate = risk_free_rate
        self.daily_borrow_rate = risk_free_rate / 252  # Convert to daily

    def calculate_commission(self, quantity: int, price: float) -> float:
        """
        Calculate commission cost.

        Commission = quantity × commission_per_share

        Args:
            quantity: Number of shares
            price: Price per share (unused, for consistency)

        Returns:
            Commission cost (₹)
        """
        commission = abs(quantity) * self.commission_per_share
        return commission

    def calculate_slippage(
        self,
        quantity: int,
        price: float,
        daily_volume: int,
        bid_ask_spread_pct: float = 0.001
    ) -> float:
        """
        Calculate slippage based on order size and liquidity.

        Model: slippage_pct = base_spread + order_size_factor

        order_size_factor = (|quantity| / daily_volume) × max_slippage
        max_slippage = 0.50% (50 bps) for very large orders relative to volume

        Total slippage = quantity × price × slippage_pct

        Args:
            quantity: Order quantity (shares)
            price: Price per share
            daily_volume: Average daily volume for ticker
            bid_ask_spread_pct: Base bid-ask spread (default 0.1%)

        Returns:
            Slippage cost (₹)
        """
        if daily_volume == 0:
            daily_volume = 1

        # Order size as % of daily volume
        order_size_pct = abs(quantity) / daily_volume

        # Slippage scales with order size (0.5% max for very large orders)
        max_slippage = 0.005  # 50 bps
        size_based_slippage = order_size_pct * max_slippage

        # Total slippage
        total_slippage_pct = bid_ask_spread_pct + size_based_slippage

        # Slippage cost
        slippage_cost = abs(quantity) * price * total_slippage_pct

        return slippage_cost

    def calculate_short_borrow_cost(self, shares_borrowed: int, price: float, days_held: int) -> float:
        """
        Calculate cost to borrow shares for short position.

        Annual borrow cost = shares_borrowed × price × annual_borrow_rate
        Daily cost = annual_cost / 252
        Total cost = daily_cost × days_held

        Args:
            shares_borrowed: Number of shares borrowed (absolute value)
            price: Price per share
            days_held: Number of days position was open

        Returns:
            Total borrow cost (₹)
        """
        annual_borrow_cost = shares_borrowed * price * self.daily_borrow_rate
        total_borrow_cost = annual_borrow_cost * days_held

        return total_borrow_cost

    def execute_order(
        self,
        order: Order,
        current_price: float,
        daily_volume: int
    ) -> Tuple[float, float, float]:
        """
        Execute order and calculate total cost.

        Returns execution price, commission, and slippage.

        Args:
            order: Order object
            current_price: Current market price
            daily_volume: Daily volume for liquidity calculation

        Returns:
            (executed_price, commission_cost, slippage_cost)
        """
        # Calculate slippage
        slippage = self.calculate_slippage(order.quantity, current_price, daily_volume)

        # Execution price includes slippage
        slippage_pct = slippage / (abs(order.quantity) * current_price) if order.quantity != 0 else 0
        executed_price = current_price * (1 + slippage_pct)

        # Calculate commission
        commission = self.calculate_commission(order.quantity, executed_price)

        return executed_price, commission, slippage

    def apply_execution_to_portfolio(
        self,
        portfolio: PortfolioState,
        order: Order,
        executed_price: float,
        commission: float
    ) -> None:
        """
        Apply executed order to portfolio (update cash and position).

        Cash reduction = (shares × executed_price) + commission

        Args:
            portfolio: PortfolioState object
            order: Order object
            executed_price: Executed price from execute_order()
            commission: Commission cost from execute_order()
        """
        cost = (order.quantity * executed_price) + commission
        portfolio.cash -= cost  # Cash goes OUT

        # Update position
        portfolio.add_position(order.ticker, order.quantity, executed_price, order.date)


# ─────────────────────────────────────────────────────────────────────────────
# 4. RISK MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class RiskManager:
    """
    Enforce risk constraints across portfolio.

    Constraints:
    1. Per-position trailing stops
    2. Portfolio-wide stop loss (-20% from peak)
    3. Maximum sector exposure (max 40% per sector)
    4. Value at Risk (VaR) limit
    """

    def __init__(
        self,
        max_portfolio_dd_pct: float = -20.0,
        max_sector_exposure_pct: float = 0.40,
        var_confidence: float = 0.95,
        var_threshold: float = -0.25
    ):
        """
        Initialize RiskManager.

        Args:
            max_portfolio_dd_pct: Max drawdown before halt (-20%)
            max_sector_exposure_pct: Max exposure per sector (40%)
            var_confidence: VaR confidence level (95%)
            var_threshold: Max acceptable VaR (-25%)
        """
        self.max_portfolio_dd_pct = max_portfolio_dd_pct
        self.max_sector_exposure_pct = max_sector_exposure_pct
        self.var_confidence = var_confidence
        self.var_threshold = var_threshold

        # Trailing stop tracking
        self.trailing_stops: Dict[str, float] = {}  # {ticker: stop_price}

    def update_trailing_stops(
        self,
        positions: Dict[str, Position],
        current_prices: Dict[str, float],
        trailing_stop_pct: float = 0.10
    ) -> None:
        """
        Update trailing stop levels based on current prices.

        For long: stop = max(current_price × (1 - trailing_stop_pct), prior_stop)
        For short: stop = min(current_price × (1 + trailing_stop_pct), prior_stop)

        Args:
            positions: {ticker: Position}
            current_prices: {ticker: current_price}
            trailing_stop_pct: Percentage below current for longs (default 10%)
        """
        for ticker, pos in positions.items():
            if not pos.is_open or ticker not in current_prices:
                continue

            current_price = current_prices[ticker]
            prior_stop = self.trailing_stops.get(ticker, float('-inf') if pos.is_long else float('inf'))

            if pos.is_long:
                # Long: stop trails below price
                new_stop = current_price * (1 - trailing_stop_pct)
                new_stop = max(new_stop, prior_stop)  # Never lower the stop
                self.trailing_stops[ticker] = new_stop

            else:  # Short
                # Short: stop trails above price
                new_stop = current_price * (1 + trailing_stop_pct)
                new_stop = min(new_stop, prior_stop)  # Never raise the stop
                self.trailing_stops[ticker] = new_stop

    def check_trailing_stops(
        self,
        positions: Dict[str, Position],
        current_prices: Dict[str, float]
    ) -> List[str]:
        """
        Check if any positions have hit trailing stops.

        Returns:
            List of tickers to exit

        Args:
            positions: {ticker: Position}
            current_prices: {ticker: current_price}
        """
        to_exit = []

        for ticker, pos in positions.items():
            if not pos.is_open or ticker not in current_prices:
                continue

            current_price = current_prices[ticker]
            stop_price = self.trailing_stops.get(ticker)

            if stop_price is None:
                continue

            if pos.is_long and current_price <= stop_price:
                to_exit.append(ticker)
            elif pos.is_short and current_price >= stop_price:
                to_exit.append(ticker)

        return to_exit

    def check_portfolio_stop_loss(self, portfolio: PortfolioState) -> bool:
        """
        Check if portfolio has hit max drawdown circuit breaker.

        Returns:
            True if portfolio should be halted

        Args:
            portfolio: PortfolioState object
        """
        max_dd = portfolio.get_max_drawdown_pct()
        return max_dd <= self.max_portfolio_dd_pct

    def check_sector_exposure(
        self,
        positions: Dict[str, Position],
        current_prices: Dict[str, float],
        ticker_to_sector: Dict[str, str],
        total_equity: float
    ) -> Dict[str, float]:
        """
        Calculate sector exposure percentages.

        Returns dict of {sector: exposure_pct}

        Args:
            positions: {ticker: Position}
            current_prices: {ticker: current_price}
            ticker_to_sector: {ticker: sector_name}
            total_equity: Total portfolio equity
        """
        sector_exposure = {}

        for ticker, pos in positions.items():
            if not pos.is_open or ticker not in current_prices:
                continue

            sector = ticker_to_sector.get(ticker, 'UNKNOWN')
            position_value = abs(pos.shares * current_prices[ticker])
            exposure_pct = position_value / total_equity if total_equity > 0 else 0

            if sector not in sector_exposure:
                sector_exposure[sector] = 0
            sector_exposure[sector] += exposure_pct

        return sector_exposure

    def is_sector_exposure_ok(
        self,
        positions: Dict[str, Position],
        current_prices: Dict[str, float],
        ticker_to_sector: Dict[str, str],
        total_equity: float
    ) -> Tuple[bool, Dict[str, float]]:
        """
        Check if sector exposure is within limits.

        Returns:
            (is_ok, sector_exposure_dict)
        """
        sector_exposure = self.check_sector_exposure(positions, current_prices, ticker_to_sector, total_equity)

        for sector, exposure in sector_exposure.items():
            if exposure > self.max_sector_exposure_pct:
                return False, sector_exposure

        return True, sector_exposure

    def calculate_portfolio_var(
        self,
        daily_returns: np.ndarray,
        confidence: Optional[float] = None
    ) -> float:
        """
        Calculate Value at Risk (VaR) at confidence level.

        VaR = Percentile of daily returns distribution

        For 95% confidence, VaR is the 5th percentile return.

        Args:
            daily_returns: Array of daily returns (decimals, e.g., 0.01 for 1%)
            confidence: Confidence level (default uses self.var_confidence)

        Returns:
            VaR as decimal (e.g., -0.15 for -15% VaR at 95%)
        """
        if confidence is None:
            confidence = self.var_confidence

        percentile = 100 * (1 - confidence)
        var = np.percentile(daily_returns, percentile)

        return var

    def check_var_limit(self, portfolio_var: float) -> bool:
        """
        Check if portfolio VaR exceeds limit.

        Returns:
            True if VaR is acceptable (not too negative)
        """
        return portfolio_var >= self.var_threshold


# ─────────────────────────────────────────────────────────────────────────────
# 5. PERFORMANCE REPORTER
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceReporter:
    """
    Calculate comprehensive performance metrics and stress tests.

    Metrics:
    - Net Profit, CAGR
    - Sharpe, Sortino, Calmar Ratios
    - Omega Ratio
    - Max Drawdown, Win/Loss, Profit Factor
    - Monte Carlo simulation
    """

    def __init__(self, portfolio: PortfolioState, risk_free_rate: float = 0.05):
        """
        Initialize PerformanceReporter.

        Args:
            portfolio: PortfolioState object with equity history
            risk_free_rate: Annual risk-free rate (5%)
        """
        self.portfolio = portfolio
        self.risk_free_rate = risk_free_rate
        self.daily_rf_rate = risk_free_rate / 252

        # Convert equity curve to numpy for calculations
        self.equity = np.array(portfolio.equity_history)
        self.dates = np.array(portfolio.date_history)

    def calculate_net_profit(self) -> float:
        """
        Calculate net profit.

        Net Profit = Final Equity - Starting Capital

        Returns:
            Net profit (₹)
        """
        net_profit = self.equity[-1] - self.portfolio.starting_capital
        return net_profit

    def calculate_total_return_pct(self) -> float:
        """
        Calculate total return as percentage.

        Total Return % = (Final Equity / Starting Capital - 1) × 100

        Returns:
            Total return (%)
        """
        total_return_pct = ((self.equity[-1] / self.portfolio.starting_capital) - 1) * 100
        return total_return_pct

    def calculate_cagr(self) -> float:
        """
        Calculate Compound Annual Growth Rate.

        CAGR = (Ending Value / Beginning Value)^(1/years) - 1

        Args are from portfolio's date range.

        Returns:
            CAGR (decimal, e.g., 0.15 for 15%)
        """
        if len(self.dates) < 2:
            return 0.0

        start_value = self.equity[0]
        end_value = self.equity[-1]

        # Years elapsed
        days_elapsed = (self.dates[-1] - self.dates[0]).days
        years = days_elapsed / 365.25

        if years <= 0:
            return 0.0

        cagr = (end_value / start_value) ** (1 / years) - 1

        return cagr

    def calculate_daily_returns(self) -> np.ndarray:
        """
        Calculate daily returns from equity curve.

        Daily Return_t = (Equity_t / Equity_t-1) - 1

        Returns:
            Array of daily returns (decimals)
        """
        daily_returns = np.diff(self.equity) / self.equity[:-1]
        return daily_returns

    def calculate_sharpe_ratio(self) -> float:
        """
        Calculate Sharpe Ratio.

        Sharpe = (Avg Return - Risk Free Rate) / StdDev(Returns) × √252

        Where:
        - Avg Return = Mean of daily returns
        - Risk Free Rate = daily_risk_free_rate
        - StdDev = Standard deviation of daily returns
        - √252 = Annualization factor

        Returns:
            Sharpe ratio (higher is better)
        """
        daily_returns = self.calculate_daily_returns()

        if len(daily_returns) < 2:
            return 0.0

        avg_return = np.mean(daily_returns)
        std_return = np.std(daily_returns)

        if std_return == 0:
            return 0.0

        excess_return = avg_return - self.daily_rf_rate
        sharpe = (excess_return / std_return) * np.sqrt(252)

        return sharpe

    def calculate_sortino_ratio(self) -> float:
        """
        Calculate Sortino Ratio (penalizes downside volatility only).

        Sortino = (Avg Return - Risk Free Rate) / Downside StdDev × √252

        Where:
        - Downside StdDev = StdDev of returns < 0

        Returns:
            Sortino ratio (higher is better)
        """
        daily_returns = self.calculate_daily_returns()

        if len(daily_returns) < 2:
            return 0.0

        avg_return = np.mean(daily_returns)
        downside_returns = daily_returns[daily_returns < 0]

        if len(downside_returns) == 0:
            return 100.0  # No downside = infinite Sortino

        downside_std = np.std(downside_returns)

        if downside_std == 0:
            return 100.0

        excess_return = avg_return - self.daily_rf_rate
        sortino = (excess_return / downside_std) * np.sqrt(252)

        return sortino

    def calculate_calmar_ratio(self) -> float:
        """
        Calculate Calmar Ratio.

        Calmar = CAGR / |Max Drawdown|

        Returns:
            Calmar ratio (higher is better)
        """
        cagr = self.calculate_cagr()
        max_dd = abs(self.portfolio.max_drawdown)

        if max_dd == 0:
            return 100.0  # No drawdown = infinite Calmar

        calmar = cagr / max_dd

        return calmar

    def calculate_omega_ratio(self, threshold: float = 0.0) -> float:
        """
        Calculate Omega Ratio.

        Omega = Σ(returns > threshold) / Σ(|returns < threshold|)

        Ratio of gains above threshold to losses below threshold.

        Args:
            threshold: Return threshold (default 0%, break-even)

        Returns:
            Omega ratio (>1 is good, >>2 is excellent)
        """
        daily_returns = self.calculate_daily_returns()

        if len(daily_returns) < 2:
            return 1.0

        gains = daily_returns[daily_returns > threshold]
        losses = daily_returns[daily_returns < threshold]

        sum_gains = np.sum(gains - threshold)
        sum_losses = np.sum(threshold - losses)

        if sum_losses == 0:
            return 100.0 if sum_gains > 0 else 1.0

        omega = sum_gains / sum_losses

        return omega

    def calculate_max_drawdown(self) -> Tuple[float, pd.Timestamp]:
        """
        Calculate maximum drawdown from peak.

        Max DD = (Trough - Peak) / Peak

        Returns:
            (max_drawdown_pct, date_of_max_dd)
        """
        return self.portfolio.get_max_drawdown_pct(), self.portfolio.max_drawdown_date

    def calculate_win_loss_ratio(self, trades: List[Dict]) -> Tuple[float, int, int]:
        """
        Calculate win/loss ratio from trade list.

        Win Rate = Winning Trades / Total Trades
        Win/Loss Ratio = # Winning Trades / # Losing Trades

        Args:
            trades: List of dicts with 'pnl' key

        Returns:
            (win_rate_pct, num_wins, num_losses)
        """
        if not trades:
            return 0.0, 0, 0

        num_wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        num_losses = sum(1 for t in trades if t.get('pnl', 0) < 0)
        total_trades = len(trades)

        win_rate_pct = (num_wins / total_trades * 100) if total_trades > 0 else 0

        return win_rate_pct, num_wins, num_losses

    def calculate_profit_factor(self, trades: List[Dict]) -> float:
        """
        Calculate Profit Factor.

        Profit Factor = Σ(Winning Trade PnL) / Σ(|Losing Trade PnL|)

        Ratio of gross profit to gross loss. PF > 1 is profitable.

        Args:
            trades: List of dicts with 'pnl' key

        Returns:
            Profit factor (>1 is profitable)
        """
        if not trades:
            return 1.0

        winning_pnl = sum(max(t.get('pnl', 0), 0) for t in trades)
        losing_pnl = sum(abs(min(t.get('pnl', 0), 0)) for t in trades)

        if losing_pnl == 0:
            return 100.0 if winning_pnl > 0 else 1.0

        profit_factor = winning_pnl / losing_pnl

        return profit_factor

    def monte_carlo_simulation(self, num_paths: int = 1000, confidence: float = 0.95) -> Dict:
        """
        Run Monte Carlo simulation on equity curve.

        Process:
        1. Extract daily returns
        2. For each path:
           a. Resample daily returns with replacement
           b. Reconstruct equity curve
           c. Calculate max drawdown
        3. Report distribution of drawdowns

        Args:
            num_paths: Number of Monte Carlo paths (default 1000)
            confidence: Confidence level for VaR (default 95%)

        Returns:
            Dict with:
            - 'mean_max_dd_pct': Average max drawdown across paths
            - 'std_max_dd_pct': Std dev of max drawdowns
            - 'var_max_dd_pct': Value at Risk (worst case at confidence)
            - 'min_max_dd_pct': Best case max drawdown
            - 'max_max_dd_pct': Worst case max drawdown
            - 'all_max_dds': Array of all max drawdowns
        """
        daily_returns = self.calculate_daily_returns()

        if len(daily_returns) < 2:
            return {'error': 'Insufficient data for Monte Carlo'}

        all_max_dds = []

        for _ in range(num_paths):
            # Resample daily returns with replacement
            resampled_returns = np.random.choice(daily_returns, size=len(daily_returns), replace=True)

            # Reconstruct equity curve from starting capital
            equity_path = np.zeros(len(resampled_returns) + 1)
            equity_path[0] = self.portfolio.starting_capital

            for i, ret in enumerate(resampled_returns):
                equity_path[i + 1] = equity_path[i] * (1 + ret)

            # Calculate max drawdown for this path
            cummax = np.maximum.accumulate(equity_path)
            drawdown = (equity_path - cummax) / cummax
            max_dd_pct = drawdown.min() * 100

            all_max_dds.append(max_dd_pct)

        all_max_dds = np.array(all_max_dds)

        # VaR: Xth percentile (e.g., 5th for 95% confidence)
        percentile = 100 * (1 - confidence)
        var_max_dd = np.percentile(all_max_dds, percentile)

        result = {
            'mean_max_dd_pct': np.mean(all_max_dds),
            'std_max_dd_pct': np.std(all_max_dds),
            'var_max_dd_pct': var_max_dd,
            'percentile_99_max_dd_pct': np.percentile(all_max_dds, 99),
            'min_max_dd_pct': np.min(all_max_dds),
            'max_max_dd_pct': np.max(all_max_dds),
            'all_max_dds': all_max_dds
        }

        return result

    def generate_tear_sheet(self, trades: List[Dict] = None) -> Dict:
        """
        Generate comprehensive tear sheet of all metrics.

        Returns:
            Dict with all performance metrics
        """
        trades = trades or []

        daily_returns = self.calculate_daily_returns()
        cagr = self.calculate_cagr()
        max_dd_pct, max_dd_date = self.calculate_max_drawdown()
        win_rate, num_wins, num_losses = self.calculate_win_loss_ratio(trades)
        profit_factor = self.calculate_profit_factor(trades)
        mc_results = self.monte_carlo_simulation(num_paths=1000)

        tear_sheet = {
            'starting_capital': self.portfolio.starting_capital,
            'ending_equity': float(self.equity[-1]),
            'net_profit': self.calculate_net_profit(),
            'total_return_pct': self.calculate_total_return_pct(),
            'cagr_pct': cagr * 100,
            'sharpe_ratio': self.calculate_sharpe_ratio(),
            'sortino_ratio': self.calculate_sortino_ratio(),
            'calmar_ratio': self.calculate_calmar_ratio(),
            'omega_ratio': self.calculate_omega_ratio(),
            'max_drawdown_pct': max_dd_pct,
            'max_drawdown_date': max_dd_date,
            'win_rate_pct': win_rate,
            'num_winning_trades': num_wins,
            'num_losing_trades': num_losses,
            'total_trades': len(trades),
            'profit_factor': profit_factor,
            'monte_carlo': mc_results,
            'daily_returns': daily_returns
        }

        return tear_sheet


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY & EXPORTS
# ─────────────────────────────────────────────────────────────────────────────

log.info("✓ Backtesting engine loaded: DataHandler, PortfolioState, ExecutionModel, RiskManager, PerformanceReporter")
