"""Phase 4 / §3.3 — tests for portfolio_sizing (risk-parity / vol-target / Kelly book)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio_sizing as ps  # noqa: E402
import backtest_engine as be  # noqa: E402


# ── Legacy equal-weight (zero regression) ────────────────────────────────────────

def test_equal_mode_is_bitwise_legacy():
    w = ps.compute_slate_weights([1.0, 2.0, 3.0], sizing_mode="equal", max_positions=5)
    assert np.allclose(w, 1.0 / 5)
    # ATR / mode irrelevant: every slot is exactly 1/max_positions.
    w2 = ps.compute_slate_weights([0.5, 9.9], sizing_mode="equal", max_positions=4)
    assert np.allclose(w2, 0.25)


def test_unknown_mode_falls_back_to_equal():
    w = ps.compute_slate_weights([1.0, 2.0], sizing_mode="nonsense", max_positions=2)
    assert np.allclose(w, 0.5)


# ── Risk parity: wᵢ ∝ 1/σᵢ, normalised ──────────────────────────────────────────

def test_risk_parity_inverse_vol_proportional():
    sig = [1.0, 2.0, 4.0]
    w = ps.compute_slate_weights(sig, sizing_mode="risk_parity", max_positions=5,
                                 max_position_weight=1.0)  # no cap interference
    # Sums to 1 (no liquidity cap, no Kelly gross).
    assert w.sum() == pytest.approx(1.0)
    # Ratios match 1/σ: w0:w1:w2 = 1 : 1/2 : 1/4 = 4 : 2 : 1.
    assert w[0] / w[2] == pytest.approx(4.0)
    assert w[1] / w[2] == pytest.approx(2.0)
    # Lower-vol name gets MORE capital.
    assert w[0] > w[1] > w[2]


def test_risk_parity_degenerate_sigma_uses_median_not_crash():
    # NaN / 0 / negative σ are replaced by the slate median, never crashing.
    w = ps.compute_slate_weights([2.0, float("nan"), 0.0, -1.0],
                                 sizing_mode="risk_parity", max_positions=5,
                                 max_position_weight=1.0)
    assert np.all(np.isfinite(w))
    assert w.sum() == pytest.approx(1.0)
    # The 3 degenerate names take the median (2.0) ⇒ all four weights equal.
    assert np.allclose(w, w[0])


def test_risk_parity_empty_slate():
    assert ps.compute_slate_weights([], sizing_mode="risk_parity").size == 0


# ── Liquidity + per-position caps ────────────────────────────────────────────────

def test_liquidity_cap_binds():
    # NAV ₹100Cr, φ=0.10. A thin name (ADV ₹1Cr) can absorb at most 0.10·1/100 = 0.001
    # of NAV; a deep name (ADV ₹10000Cr) is effectively uncapped.
    w = ps.compute_slate_weights(
        [2.0, 2.0], sizing_mode="risk_parity", max_positions=5,
        nav=100e7, advs=[1e7, 10000e7], liquidity_phi=0.10, max_position_weight=1.0,
    )
    assert w[0] <= 0.001 + 1e-12        # thin name clipped to φ·ADV/NAV
    assert w[1] > w[0]                  # deep name gets the redistributed budget


def test_max_position_weight_cap():
    # 2 equal-σ names, 15% cap each ⇒ each ≤0.15 (book under-invested, that's fine).
    w = ps.compute_slate_weights([2.0, 2.0], sizing_mode="risk_parity",
                                 max_positions=5, max_position_weight=0.15)
    assert np.all(w <= 0.15 + 1e-12)


# ── Vol target: scale the book to a target σ ─────────────────────────────────────

def test_vol_target_hits_target_sigma():
    # Single name, σ=4%, target 2% ⇒ scale = 2/4 = 0.5; w starts at 1.0 → 0.5.
    w = ps.compute_slate_weights([4.0], sizing_mode="vol_target", max_positions=5,
                                 vol_target_pct=2.0, max_position_weight=1.0)
    # Realised independent-name σ_port = w·σ = 0.5·4 = 2.0 == target.
    sigma_port = float(np.sqrt(np.sum((w * np.array([4.0])) ** 2)))
    assert sigma_port == pytest.approx(2.0, abs=1e-9)


def test_vol_target_never_upgrosses_past_invested():
    # Calm slate (σ=1%) with a high target ⇒ scale clamped at 1.0 (never lever up).
    w = ps.compute_slate_weights([1.0, 1.0], sizing_mode="vol_target", max_positions=5,
                                 vol_target_pct=50.0, max_position_weight=1.0)
    assert w.sum() <= 1.0 + 1e-9


# ── Fractional Kelly book gross ──────────────────────────────────────────────────

def test_kelly_book_gross_formula_and_half_cap():
    # W=0.6, R=2 ⇒ f* = 0.6 - 0.4/2 = 0.4; half-Kelly ⇒ 0.2.
    assert ps.kelly_book_gross(0.6, 2.0, kappa=0.5) == pytest.approx(0.2)
    # κ is hard-capped at ½ regardless of request — full-Kelly is refused.
    assert ps.kelly_book_gross(0.6, 2.0, kappa=1.0) == pytest.approx(0.2)


def test_kelly_book_gross_negative_edge_stands_down():
    # W=0.3, R=1 ⇒ f* = 0.3 - 0.7/1 = -0.4 < 0 ⇒ gross 0 (do not bet).
    assert ps.kelly_book_gross(0.3, 1.0) == 0.0


def test_kelly_book_gross_degenerate_inputs():
    assert ps.kelly_book_gross(float("nan"), 2.0) == 1.0   # degrade to fully-invested
    assert ps.kelly_book_gross(0.6, 0.0) == 1.0
    assert ps.kelly_book_gross("x", "y") == 1.0


def test_kelly_gross_scales_the_whole_book():
    # gross=0.5 halves every slate weight (sizes the BOOK, not a single bet).
    w_full = ps.compute_slate_weights([1.0, 2.0], sizing_mode="risk_parity",
                                      max_positions=5, max_position_weight=1.0,
                                      kelly_gross=1.0)
    w_half = ps.compute_slate_weights([1.0, 2.0], sizing_mode="risk_parity",
                                      max_positions=5, max_position_weight=1.0,
                                      kelly_gross=0.5)
    assert np.allclose(w_half, w_full * 0.5)


# ── Safe wrapper never raises ────────────────────────────────────────────────────

def test_safe_wrapper_returns_none_on_garbage_without_raising():
    # Garbage that would make compute_slate_weights misbehave still degrades to None.
    out = ps.safe_compute_slate_weights([1.0], sizing_mode="risk_parity",
                                        max_positions="not-an-int")
    # Either a clean vector or None — never an exception.
    assert out is None or np.all(np.isfinite(out))


# ── Engine wiring: equal default is bit-for-bit; risk-parity de-grosses tail ─────

def _toy_entries():
    """Two concurrent candidates on bar 0: one calm (ATR 1%), one jumpy (ATR 5%),
    both +10% gross winners. Equal-weight gives each NAV/5; risk-parity tilts toward
    the calm name."""
    dates = list(range(10))
    cands = [
        {"ticker": "CALM", "entry_price": 100.0, "exit_idx": 5, "net_return_pct": 10.0,
         "gross_return_pct": 10.0, "exit_price": 110.0, "exit_reason": "time",
         "entry_date": "d0", "exit_date": "d5", "atr_pct": 1.0, "sector": "A",
         "holding_days": 5, "win_threshold": 0.0},
        {"ticker": "JUMP", "entry_price": 100.0, "exit_idx": 5, "net_return_pct": 10.0,
         "gross_return_pct": 10.0, "exit_price": 110.0, "exit_reason": "time",
         "entry_date": "d0", "exit_date": "d5", "atr_pct": 5.0, "sector": "B",
         "holding_days": 5, "win_threshold": 0.0},
    ]
    return dates, {0: cands}


def _price_at(idx, ticker):
    return 100.0  # flat book between entry and exit for a deterministic MTM


def test_engine_equal_default_unchanged_by_phase4_param():
    dates, entries = _toy_entries()
    legacy = be.simulate_portfolio(dates, 0, 9, entries, _price_at,
                                   starting_capital=1e7, max_positions=5)
    explicit_equal = be.simulate_portfolio(dates, 0, 9, entries, _price_at,
                                            starting_capital=1e7, max_positions=5,
                                            sizing_mode="equal")
    # Same trades, same allocations — Phase-4 param is inert at its default.
    assert [t["capital_allocated"] for t in legacy[1]] == [t["capital_allocated"] for t in explicit_equal[1]]


def test_engine_risk_parity_tilts_to_low_vol_name():
    dates, entries = _toy_entries()
    # max_position_pct=100 removes the 15% per-name cap so the pure inverse-vol tilt is
    # observable (with the locked 15% cap, both 2-name weights would clip equal to 15%
    # — itself correct institutional behaviour, just not what this test isolates).
    eq = be.simulate_portfolio(dates, 0, 9, entries, _price_at,
                               starting_capital=1e7, max_positions=5,
                               sizing_mode="equal", max_position_pct=100.0)
    rp = be.simulate_portfolio(dates, 0, 9, entries, _price_at,
                               starting_capital=1e7, max_positions=5,
                               sizing_mode="risk_parity", max_position_pct=100.0)
    eq_alloc = {t["ticker"]: t["capital_allocated"] for t in eq[1]}
    rp_alloc = {t["ticker"]: t["capital_allocated"] for t in rp[1]}
    # Equal-weight: both names get NAV/5 = ₹2M.
    assert eq_alloc["CALM"] == pytest.approx(eq_alloc["JUMP"])
    # Risk-parity: the calm (low-ATR) name gets MORE than the jumpy one (5× the σ).
    assert rp_alloc["CALM"] > rp_alloc["JUMP"]
    assert rp_alloc["CALM"] / rp_alloc["JUMP"] == pytest.approx(5.0, rel=0.02)


def test_engine_15pct_cap_binds_under_risk_parity():
    # With the locked 15% per-name cap and a 2-name slate, risk-parity weights (0.833 /
    # 0.167) both clip to 0.15 — proving the cap is enforced and the book under-invests
    # rather than over-concentrating into the calm name.
    dates, entries = _toy_entries()
    rp = be.simulate_portfolio(dates, 0, 9, entries, _price_at,
                               starting_capital=1e7, max_positions=5,
                               sizing_mode="risk_parity")  # default 15% cap
    alloc = {t["ticker"]: t["capital_allocated"] for t in rp[1]}
    assert alloc["CALM"] == pytest.approx(0.15 * 1e7)
    assert alloc["JUMP"] == pytest.approx(0.15 * 1e7)


# ── Pillar C — unallocated cash is TRACKED and compounds (no forced full investment) ─

def test_risk_parity_unallocated_cash_is_tracked_in_equity_curve():
    """When inverse-vol weights + the 15% cap under-invest the book, the residual must
    stay as CASH in the equity curve (never silently forced to full investment), and every
    bar's NAV must reconcile to cash + mark-to-market longs."""
    dates, entries = _toy_entries()
    equity, trades = be.simulate_portfolio(
        dates, 0, 9, entries, _price_at,
        starting_capital=1e7, max_positions=5, sizing_mode="risk_parity")  # 15% cap binds
    # Two names clip to 0.15·NAV ⇒ ₹3M deployed, ₹7M unallocated on the entry bar.
    deployed = sum(t["capital_allocated"] for t in trades)
    assert deployed == pytest.approx(3e6)
    entry_bar = equity[0]
    assert entry_bar["cash"] == pytest.approx(1e7 - 3e6)        # ₹7M genuinely uninvested
    assert entry_bar["cash"] > 0                                # NOT forced fully-invested
    # NAV reconciliation WHILE positions are open (bars 0..4, before the idx-5 exit): a flat
    # book (price_at=100) ⇒ NAV == starting capital, with ₹3M in longs-at-cost + ₹7M cash —
    # proving the unallocated cash is carried in NAV, not dropped or force-invested.
    for e in equity[:5]:
        assert e["positions"] == 2
        assert e["cash"] == pytest.approx(7e6)
        assert e["nav"] == pytest.approx(1e7)


def test_risk_parity_cash_compounds_after_winning_exit():
    """On exit the (impact-free) +10% proceeds return to cash and the NAV steps up — the
    compounded equity curve reflects realised gains on the deployed sleeve while the
    unallocated cash is preserved (not leaked)."""
    dates, entries = _toy_entries()
    equity, trades = be.simulate_portfolio(
        dates, 0, 9, entries, _price_at,
        starting_capital=1e7, max_positions=5, sizing_mode="risk_parity")
    # Both winners exit at idx 5 at +10% on ₹3M deployed ⇒ +₹300k realised.
    post_exit = equity[6]   # bar after the idx-5 exit settles to cash
    assert post_exit["positions"] == 0
    assert post_exit["cash"] == pytest.approx(1e7 + 0.10 * 3e6)   # ₹10.3M all in cash
    assert post_exit["nav"] == pytest.approx(1.03e7)             # compounded, not 1e7
