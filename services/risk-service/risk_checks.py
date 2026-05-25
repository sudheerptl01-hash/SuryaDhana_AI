from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str
    action: Literal["allow", "reject", "halt"]


def check_position_limit(
    ticker: str,
    proposed_value_inr: float,
    portfolio_value_inr: float,
    max_position_pct: float = 0.15,
) -> RiskCheckResult:
    pct = proposed_value_inr / portfolio_value_inr if portfolio_value_inr else 1.0
    if pct > max_position_pct:
        return RiskCheckResult(
            passed=False,
            reason=f"{ticker}: position {pct:.1%} exceeds max {max_position_pct:.1%}",
            action="reject",
        )
    return RiskCheckResult(passed=True, reason="OK", action="allow")


def check_sector_concentration(
    sector: str,
    proposed_value_inr: float,
    existing_sector_value_inr: float,
    portfolio_value_inr: float,
    max_sector_pct: float = 0.40,
) -> RiskCheckResult:
    sector_total = existing_sector_value_inr + proposed_value_inr
    pct = sector_total / portfolio_value_inr if portfolio_value_inr else 1.0
    if pct > max_sector_pct:
        return RiskCheckResult(
            passed=False,
            reason=f"Sector '{sector}': {pct:.1%} would exceed max {max_sector_pct:.1%}",
            action="reject",
        )
    return RiskCheckResult(passed=True, reason="OK", action="allow")


def check_max_positions(
    current_positions: int,
    max_positions: int = 5,
) -> RiskCheckResult:
    if current_positions >= max_positions:
        return RiskCheckResult(
            passed=False,
            reason=f"Portfolio full: {current_positions}/{max_positions} positions",
            action="reject",
        )
    return RiskCheckResult(passed=True, reason="OK", action="allow")


def check_daily_loss_limit(
    daily_pnl_pct: float,
    daily_loss_limit: float = -0.02,
) -> RiskCheckResult:
    if daily_pnl_pct <= daily_loss_limit:
        return RiskCheckResult(
            passed=False,
            reason=f"Daily loss limit hit: {daily_pnl_pct:.2%} (limit: {daily_loss_limit:.2%})",
            action="halt",
        )
    return RiskCheckResult(passed=True, reason="OK", action="allow")


def check_max_drawdown(
    drawdown_pct: float,
    max_drawdown: float = -0.20,
) -> RiskCheckResult:
    if drawdown_pct <= max_drawdown:
        return RiskCheckResult(
            passed=False,
            reason=f"Max drawdown breached: {drawdown_pct:.2%} (limit: {max_drawdown:.2%}). Emergency stop.",
            action="halt",
        )
    return RiskCheckResult(passed=True, reason="OK", action="allow")


def run_all_checks(
    ticker: str,
    sector: str,
    proposed_value_inr: float,
    portfolio_value_inr: float,
    current_positions: int,
    existing_sector_value_inr: float,
    daily_pnl_pct: float,
    drawdown_pct: float,
    max_position_pct: float = 0.15,
    max_sector_pct: float = 0.40,
    max_positions: int = 5,
    daily_loss_limit: float = -0.02,
    max_drawdown: float = -0.20,
) -> list[RiskCheckResult]:
    checks = [
        check_daily_loss_limit(daily_pnl_pct, daily_loss_limit),
        check_max_drawdown(drawdown_pct, max_drawdown),
        check_max_positions(current_positions, max_positions),
        check_position_limit(ticker, proposed_value_inr, portfolio_value_inr, max_position_pct),
        check_sector_concentration(sector, proposed_value_inr, existing_sector_value_inr, portfolio_value_inr, max_sector_pct),
    ]
    for c in checks:
        if not c.passed:
            logger.warning("Risk check failed", ticker=ticker, reason=c.reason, action=c.action)
    return checks
