from __future__ import annotations

import math

from shared.logging import get_logger

logger = get_logger(__name__)


def kelly_fraction(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """
    Full Kelly Criterion: f* = (p*b - q) / b
    where p=win_rate, q=1-win_rate, b=avg_win/avg_loss

    Returns a fraction of capital (0-1).
    In practice, use fractional Kelly (50% Kelly) to reduce variance.
    """
    # avg_win_pct <= 0 (no winning trades yet) must size to zero, not divide by zero.
    if avg_loss_pct <= 0 or avg_win_pct <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win_pct / avg_loss_pct
    q = 1 - win_rate
    f_star = (win_rate * b - q) / b
    return max(0.0, min(f_star, 1.0))


def fractional_kelly(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    fraction: float = 0.5,
    max_position_pct: float = 0.15,
) -> float:
    """
    Fractional Kelly (default 50%) capped at max_position_pct.
    Reduces risk vs full Kelly while preserving growth characteristics.
    """
    full_kelly = kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
    frac = full_kelly * fraction
    result = min(frac, max_position_pct)
    logger.debug(
        "Kelly sizing",
        full_kelly=round(full_kelly, 4),
        fractional=round(frac, 4),
        capped=round(result, 4),
    )
    return result


def size_position(
    portfolio_value_inr: float,
    position_pct: float,
    stock_price: float,
) -> tuple[int, float]:
    """
    Calculates number of shares and actual INR allocation.

    Returns: (shares, allocated_inr)
    """
    target_inr = portfolio_value_inr * position_pct
    shares = math.floor(target_inr / stock_price)
    if shares < 1:
        return 0, 0.0
    actual_inr = shares * stock_price
    return shares, actual_inr
