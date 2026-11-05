import sys
from pathlib import Path
# Service folders use hyphens (not importable as packages): put the repo root
# (for `shared`) and the service folder on sys.path and import the module directly.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/risk-service"))

from position_sizer import kelly_fraction, fractional_kelly, size_position


def test_kelly_fraction_typical():
    f = kelly_fraction(win_rate=0.55, avg_win_pct=2.0, avg_loss_pct=2.0)
    assert 0 < f < 1


def test_kelly_fraction_zero_on_bad_inputs():
    assert kelly_fraction(0.0, 2.0, 2.0) == 0.0
    assert kelly_fraction(0.55, 0.0, 2.0) == 0.0


def test_fractional_kelly_capped():
    f = fractional_kelly(0.55, 2.0, 2.0, fraction=0.5, max_position_pct=0.15)
    assert f <= 0.15


def test_size_position_rounds_down():
    shares, allocated = size_position(10000, 0.15, 150.0)
    assert shares == 10  # floor(1500 / 150)
    assert allocated == 1500.0


def test_size_position_too_small():
    shares, allocated = size_position(100, 0.15, 500.0)
    assert shares == 0
    assert allocated == 0.0
