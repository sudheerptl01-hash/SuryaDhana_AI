"""Trade ticket (routers/costs.py): shares, ATR stop and risk use the shared cost model unchanged."""
import pytest

import routers.costs as c
from shared.trading_costs import default_model


def test_ticket_matches_the_cost_model_and_stop_maths():
    t = c.ticket(50_000, 707.25, 2.18, 2.0, 500_000)
    assert t["shares"] == 70 and t["notional"] == pytest.approx(49_507.5)
    assert t["round_trip"]["total"] == pytest.approx(default_model().round_trip(49_507.5).total, abs=0.01)
    assert t["stop"]["price"] == pytest.approx(707.25 * (1 - 0.0436), abs=0.01)
    assert t["stop"]["loss_if_hit"] == pytest.approx(70 * (707.25 - t["stop"]["price"]) + t["round_trip"]["total"], abs=0.5)   # stop price is rounded to paise
    assert t["stop"]["loss_pct_of_capital"] == pytest.approx(t["stop"]["loss_if_hit"] / 5000, abs=0.01)
    assert t["tax_on_10pct_gain"]["long_term_with_exemption"] == 0.0        # within the ₹1.25 L exemption
    assert t["tax_on_10pct_gain"]["short_term"] == pytest.approx(4_950.75 * 0.20 * 1.04, abs=0.05)


def test_ticket_without_atr_or_capital():
    t = c.ticket(1_000, 5_000, None, 2.0, None)            # price above the amount → 0 shares, no stop block
    assert t["shares"] == 0 and "stop" not in t and t["round_trip_pct"] is None
