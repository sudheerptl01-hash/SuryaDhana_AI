import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pytest
from services.risk_service.risk_checks import (
    check_position_limit,
    check_sector_concentration,
    check_max_positions,
    check_daily_loss_limit,
    check_max_drawdown,
)


def test_position_limit_passes():
    result = check_position_limit("RELIANCE", 1200, 10000, max_position_pct=0.15)
    assert result.passed


def test_position_limit_fails():
    result = check_position_limit("RELIANCE", 2000, 10000, max_position_pct=0.15)
    assert not result.passed
    assert result.action == "reject"


def test_max_positions_full():
    result = check_max_positions(5, max_positions=5)
    assert not result.passed
    assert result.action == "reject"


def test_daily_loss_halt():
    result = check_daily_loss_limit(-0.025, daily_loss_limit=-0.02)
    assert not result.passed
    assert result.action == "halt"


def test_max_drawdown_emergency_stop():
    result = check_max_drawdown(-0.22, max_drawdown=-0.20)
    assert not result.passed
    assert result.action == "halt"
