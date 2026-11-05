"""Indian cash-equity cost & tax model: itemised charges, profiles, viability, tax."""
import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from shared.trading_costs import (  # noqa: E402
    PROFILES, CostModel, TaxRules, capital_gains_tax, profile_from_env,
)

MS = CostModel(PROFILES["icici_moneysaver"])
ZERO = CostModel(PROFILES["discount_zero"])


def test_delivery_round_trip_itemised_for_icici_moneysaver():
    rt = MS.round_trip(100_000)
    assert rt.brokerage == pytest.approx(580.0)            # 0.29% × 2 legs
    assert rt.stt == pytest.approx(200.0)                  # 0.1% × 2
    assert rt.stamp == pytest.approx(15.0)                 # buy only
    assert rt.dp == pytest.approx(20.0)                    # sell only, per scrip
    gst_base = 580 + 2 * 100_000 * (0.00322 + 0.0001 + 0.0001) / 100 + 20
    assert rt.gst == pytest.approx(gst_base * 0.18)
    assert rt.pct_of(100_000) == pytest.approx(0.9314, abs=1e-3)


def test_small_tickets_are_dominated_by_the_fixed_dp_charge():
    assert MS.round_trip_pct(1_500) == pytest.approx(2.48, abs=0.02)
    assert MS.round_trip_pct(1_500) > 2.5 * MS.round_trip_pct(1_000_000)
    assert ZERO.round_trip_pct(100_000) < 0.3


def test_intraday_has_no_dp_and_sell_side_stt_only():
    rt = MS.round_trip(100_000, "intraday")
    assert rt.dp == 0 and rt.stt == pytest.approx(25.0) and rt.stamp == pytest.approx(3.0)


def test_min_brokerage_and_flat_fee():
    flat = CostModel(PROFILES["icici_moneysaver"].__class__("flat", 0.0, 0.0, flat_per_order=20.0))
    assert flat.leg(1_000_000, "buy").brokerage == 20.0
    floor = CostModel(PROFILES["icici_moneysaver"].__class__("min", 0.27, 0.0, min_brokerage=35.0))
    assert floor.leg(1_000, "buy").brokerage == 35.0       # 0.27% of ₹1,000 = ₹2.7 → floored


def test_min_position_for_target_and_impossible_target():
    pos = MS.min_position_for(1.0)
    assert pos is not None and MS.round_trip_pct(pos) <= 1.0 < MS.round_trip_pct(pos * 0.95)
    assert MS.min_position_for(0.5) is None               # % part alone (~0.91%) exceeds 0.5%
    prime = CostModel(PROFILES["icici_prime_9999"])
    assert prime.min_position_for(0.5) is not None         # 0.07% plan can get under 0.5%


def test_annual_drag_matches_hand_calculation():
    # ₹1L, 5 names, weekly full turnover (the current 5-day system)
    drag = MS.annual_drag_pct(100_000, 5, 52, 1.0)
    assert drag == pytest.approx(52 * MS.round_trip_pct(20_000), rel=1e-9)
    assert drag > 45                                        # no equity edge survives this
    monthly = MS.annual_drag_pct(1_000_000, 20, 12, 0.3)
    assert monthly < 3.5


def test_profile_from_env_overrides_single_values():
    p = profile_from_env({"COST_PROFILE": "icici_moneysaver", "COST_BROKERAGE_DELIVERY_PCT": "0.22",
                          "COST_DP_CHARGE": "15"})
    assert (p.delivery_brokerage_pct, p.dp_charge, p.name) == (0.22, 15.0, "icici_moneysaver+calibrated")
    assert profile_from_env({}).name == "icici_moneysaver"      # default = ICICI's default plan
    with pytest.raises(ValueError):
        profile_from_env({"COST_PROFILE": "nope"})


def test_capital_gains_tax_short_long_and_exemption():
    assert capital_gains_tax(10_000, 200, 125_000) == (pytest.approx(10_000 * 0.20 * 1.04), 0.0)
    tax, used = capital_gains_tax(200_000, 400, 125_000)
    assert used == 125_000 and tax == pytest.approx(75_000 * 0.125 * 1.04)
    assert capital_gains_tax(-5_000, 10, 0) == (0.0, 0.0)
    assert TaxRules().long_term_after_days == 365
