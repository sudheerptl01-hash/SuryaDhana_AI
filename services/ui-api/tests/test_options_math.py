"""OSTR math tests (W3): Black-76 identities, EXACT breakevens on the piecewise-linear
payoff, honest bounded/unbounded max P&L, Greeks signs, margin/cost estimate sanity, and
the /api/options/strategy/analyze contract."""
import math
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import options_math as om  # noqa: E402
from options_math import Leg, black76  # noqa: E402
from routers import options_strategy  # noqa: E402

F, R = 22600.0, 0.065


# ── Black-76 identities ──────────────────────────────────────────────────────────────────

def test_put_call_parity_holds():
    """C − P = df · (F − K) to 1e-9, across moneyness and tenors."""
    for k in (20000.0, 22600.0, 25000.0):
        for t in (5 / 365, 30 / 365, 180 / 365):
            for iv in (0.08, 0.125, 0.40):
                c = black76("CE", F, k, t, iv, R).price
                p = black76("PE", F, k, t, iv, R).price
                assert c - p == pytest.approx(math.exp(-R * t) * (F - k), abs=1e-9)


def test_delta_limits_deep_itm_and_otm():
    """Futures-equivalent N(d1) delta → 1 deep ITM call / −1 deep ITM put; → 0 far OTM."""
    t, iv = 5 / 365, 0.125
    assert black76("CE", F, F * 0.5, t, iv).delta == pytest.approx(1.0, abs=1e-6)
    assert black76("PE", F, F * 2.0, t, iv).delta == pytest.approx(-1.0, abs=1e-6)
    assert black76("CE", F, F * 2.0, t, iv).delta == pytest.approx(0.0, abs=1e-6)
    assert black76("PE", F, F * 0.5, t, iv).delta == pytest.approx(0.0, abs=1e-6)


def test_theta_negative_for_long_atm_and_gamma_vega_match_put_call():
    c = black76("CE", F, F, 10 / 365, 0.125, R)
    p = black76("PE", F, F, 10 / 365, 0.125, R)
    assert c.theta_day < 0 and p.theta_day < 0            # long options decay
    assert c.gamma == pytest.approx(p.gamma, rel=1e-12)   # same d1 → same gamma/vega
    assert c.vega == pytest.approx(p.vega, rel=1e-12)
    assert c.rho == pytest.approx(-10 / 365 * c.price / 100)   # Black-76: ∂V/∂r = −T·V


def test_expiry_intrinsic_only():
    assert black76("CE", F, F - 100, 0.0, 0.125).price == pytest.approx(100.0)
    assert black76("PE", F, F + 250, 0.0, 0.125).price == pytest.approx(250.0)


# ── exact breakevens (root of the piecewise-linear payoff, never sampled) ────────────────

def _leg(side, kind, strike, premium, lots=1, lot_size=1, **kw):
    return Leg(side=side, kind=kind, strike=strike, premium=premium,
               lots=lots, lot_size=lot_size, **kw)


def test_long_call_breakeven_exact():
    legs = [_leg("buy", "CE", 22600.0, 137.25)]
    assert om.breakevens(legs) == pytest.approx([22737.25], abs=1e-9)


def test_bull_call_spread_breakeven_is_k1_plus_net_debit_exactly():
    k1, k2, p1, p2 = 22600.0, 22800.0, 137.25, 58.6
    legs = [_leg("buy", "CE", k1, p1, lots=2, lot_size=65),
            _leg("sell", "CE", k2, p2, lots=2, lot_size=65)]
    assert om.breakevens(legs) == pytest.approx([k1 + (p1 - p2)], abs=1e-9)
    profit, loss = om.max_profit_loss(legs)
    assert not profit.unbounded and not loss.unbounded
    assert profit.value == pytest.approx(((k2 - k1) - (p1 - p2)) * 130, abs=0.01)
    assert loss.value == pytest.approx(-(p1 - p2) * 130, abs=0.01)


def test_straddle_two_breakevens_and_unbounded_upside():
    k, pc, pp = 22600.0, 137.25, 125.4
    legs = [_leg("buy", "CE", k, pc), _leg("buy", "PE", k, pp)]
    assert om.breakevens(legs) == pytest.approx([k - (pc + pp), k + (pc + pp)], abs=1e-9)
    profit, loss = om.max_profit_loss(legs)
    assert profit.unbounded and profit.value is None
    assert not loss.unbounded and loss.value == pytest.approx(-(pc + pp), abs=0.01)
    assert loss.at == k


def test_iron_condor_max_profit_equals_net_credit():
    lot = 65
    legs = [_leg("buy", "PE", 22000.0, 40.0, lot_size=lot),
            _leg("sell", "PE", 22200.0, 75.0, lot_size=lot),
            _leg("sell", "CE", 23000.0, 70.0, lot_size=lot),
            _leg("buy", "CE", 23200.0, 38.0, lot_size=lot)]
    credit = (75.0 - 40.0 + 70.0 - 38.0) * lot            # 67 × 65
    profit, loss = om.max_profit_loss(legs)
    assert not profit.unbounded and profit.value == pytest.approx(credit, abs=0.01)
    assert not loss.unbounded                              # wings cap both sides
    assert loss.value == pytest.approx((67.0 - 200.0) * lot, abs=0.01)
    bes = om.breakevens(legs)
    assert bes == pytest.approx([22200.0 - 67.0, 23000.0 + 67.0], abs=1e-9)
    assert om.entry_cashflow(legs) == pytest.approx(credit)


def test_short_call_unbounded_loss_short_put_bounded_at_zero():
    profit, loss = om.max_profit_loss([_leg("sell", "CE", 22600.0, 137.25)])
    assert loss.unbounded and loss.value is None
    assert not profit.unbounded and profit.value == pytest.approx(137.25)
    profit2, loss2 = om.max_profit_loss([_leg("sell", "PE", 22600.0, 125.4)])
    assert not loss2.unbounded                             # S stops at 0
    assert loss2.value == pytest.approx(-(22600.0 - 125.4)) and loss2.at == 0.0


def test_covered_call_future_plus_short_ce():
    lot = 65
    legs = [_leg("buy", "FUT", None, 22648.5, lot_size=lot),
            _leg("sell", "CE", 23000.0, 70.0, lot_size=lot)]
    profit, loss = om.max_profit_loss(legs)
    assert not profit.unbounded
    assert profit.value == pytest.approx(((23000.0 - 22648.5) + 70.0) * lot, abs=0.01)
    assert not loss.unbounded                              # bounded at S=0 (huge, but finite)
    assert om.breakevens(legs) == pytest.approx([22648.5 - 70.0], abs=1e-9)


def test_breakeven_touching_kink_counted_once():
    # buy CE at K with zero premium: payoff ≥ 0, touches zero on [0, K] — K is the kink
    legs = [_leg("buy", "CE", 22600.0, 0.0)]
    assert om.breakevens(legs) == pytest.approx([22600.0])


def test_calendar_book_breakeven_by_bisection():
    legs = [_leg("sell", "CE", 22600.0, 137.25, days=5.5, iv=12.5),
            _leg("buy", "CE", 22600.0, 220.0, days=33.5, iv=13.5)]
    bes = om.breakevens_any(legs, 5.5, 12.5)
    assert len(bes) >= 1
    for b in bes:                                          # each root really is a zero
        assert abs(om.nearest_expiry_payoff(legs, b, 5.5, 12.5)) < 0.05


# ── greeks aggregation ───────────────────────────────────────────────────────────────────

def test_net_greeks_straddle_and_fut_delta():
    lot = 65
    legs = [_leg("buy", "CE", F, 137.25, lot_size=lot, iv=12.5),
            _leg("buy", "PE", F, 125.4, lot_size=lot, iv=12.5)]
    net = om.net_greeks(legs, F, 5.5, 12.5)
    assert abs(net["delta"]) < 2.0                        # ATM straddle ≈ delta-neutral
    assert net["gamma"] > 0 and net["vega"] > 0 and net["theta_day"] < 0
    g = om.leg_greeks(_leg("sell", "FUT", None, 22648.5, lots=2, lot_size=lot), F, 5.5, 12.5)
    assert g["delta"] == -130 and g["gamma"] == 0 and g["theta_day"] == 0


# ── margin + costs are labelled estimates and behave sanely ─────────────────────────────

def test_margin_estimate_long_is_premium_short_adds_futures_margin():
    lot = 65
    long_ce = _leg("buy", "CE", 23000.0, 70.0, lot_size=lot)
    short_pe = _leg("sell", "PE", 22200.0, 75.0, lot_size=lot)
    _, loss = om.max_profit_loss([long_ce, short_pe])
    m = om.margin_estimate([long_ce, short_pe], F, 12.0, loss)
    assert m.per_leg[0] == pytest.approx(70.0 * lot)
    assert m.per_leg[1] == pytest.approx(0.12 * F * lot + 75.0 * lot)
    assert m.total == pytest.approx(m.per_leg[0] + m.per_leg[1])
    assert "ESTIMATE" in m.note


def test_costs_estimate_stt_sell_side_only_and_round_trip_symmetry():
    lot = 65
    c = om.costs_estimate([_leg("buy", "CE", F, 100.0, lot_size=lot)], brokerage_per_order=20.0)
    assert c["estimate"] is True
    prem = 100.0 * lot
    # buy entry: no STT; sell exit: 0.1% of premium — the whole round trip carries one STT hit
    assert c["round_trip"]["stt"] == pytest.approx(prem * 0.001, abs=0.01)
    assert c["round_trip"]["stamp"] == pytest.approx(prem * 0.00003, abs=0.01)
    assert c["round_trip"]["brokerage"] == 40.0
    assert c["round_trip"]["total"] == pytest.approx(c["entry"] + c["exit"], abs=0.01)


# ── payoff grid is to-scale: kinks and breakevens are exact grid points ──────────────────

def test_payoff_grid_contains_kinks_and_breakevens():
    legs = [_leg("buy", "CE", 22600.0, 137.25, lot_size=65, iv=12.5),
            _leg("sell", "CE", 22800.0, 58.6, lot_size=65, iv=12.8)]
    grid = om.payoff_grid(legs, F, 5.5, 12.5)
    xs = [g["s"] for g in grid]
    assert 22600.0 in xs and 22800.0 in xs
    be = 22600.0 + (137.25 - 58.6)
    assert any(abs(x - be) < 0.01 for x in xs)
    row = next(g for g in grid if abs(g["s"] - be) < 0.01)
    assert abs(row["expiry"]) < 0.01                      # zero P&L at the breakeven
    assert xs == sorted(xs) and len(xs) >= 100


# ── router contract ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(options_strategy.router, prefix="/api/options")
    return TestClient(app)


def _body(legs):
    return {"symbol": "NIFTY", "forward": 22612.46, "days_to_expiry": 5.5,
            "default_iv": 12.5, "legs": legs}


def test_analyze_endpoint_bull_call_spread(client):
    legs = [{"side": "buy", "kind": "CE", "strike": 22600, "premium": 137.25,
             "lots": 1, "lot_size": 65, "iv": 12.5},
            {"side": "sell", "kind": "CE", "strike": 22800, "premium": 58.6,
             "lots": 1, "lot_size": 65, "iv": 12.8}]
    r = client.post("/api/options/strategy/analyze", json=_body(legs))
    assert r.status_code == 200
    d = r.json()
    assert d["paper_only"] is True and d["net_label"] == "DEBIT"
    assert d["breakevens"] == [pytest.approx(22678.65)]
    assert d["max_profit"]["value"] == pytest.approx((200 - 78.65) * 65, abs=0.01)
    assert d["max_loss"]["value"] == pytest.approx(-78.65 * 65, abs=0.01)
    assert d["margin"]["estimate"] is True and d["costs"]["estimate"] is True
    assert len(d["payoff"]) >= 100 and d["greeks"]["net"]["delta"] > 0


def test_analyze_rejects_more_than_four_legs_and_bad_strike(client):
    leg = {"side": "buy", "kind": "CE", "strike": 22600, "premium": 10, "lots": 1, "lot_size": 65}
    r = client.post("/api/options/strategy/analyze", json=_body([leg] * 5))
    assert r.status_code == 422                            # pydantic max_length → app envelope
    r2 = client.post("/api/options/strategy/analyze",
                     json=_body([{**leg, "strike": None}]))
    assert r2.status_code == 400
    assert r2.json()["detail"]["code"] == "invalid"        # errors.fail block (bare app: no envelope handler)
