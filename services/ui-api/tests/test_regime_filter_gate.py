"""Phase 4 / §3.5 — tests for regime_filter_gate (mean-reversion filter gating)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import regime_filter_gate as g  # noqa: E402


# A representative mixed screen: a mean-reversion dip-buy (RSI<35), a 52w-low pullback,
# an intention_pullback (bool dip-buy), AND trend/momentum filters that must survive.
def _mixed_filters():
    return [
        {"field": "rsi_14", "op": "lt", "value": 35},            # mean-reversion
        {"field": "above_52w_low_pct", "op": "lt", "value": 5},   # mean-reversion
        {"field": "intention_pullback"},                          # mean-reversion (bool)
        {"field": "price_gt_ma200"},                              # trend (keep)
        {"field": "ma50_gt_ma200"},                               # trend (keep)
        {"field": "vipt_breakout"},                               # breakout/momentum (keep)
        {"field": "rsi_14", "op": "gt", "value": 70},             # MOMENTUM use of RSI (keep)
    ]


# ── classify_regime (§3.5 thresholds) ────────────────────────────────────────────

def test_classify_regime_posterior_thresholds():
    assert g.classify_regime(0.61) == g.BREAKOUT
    assert g.classify_regime(0.95) == g.BREAKOUT
    assert g.classify_regime(0.39) == g.CRASH
    assert g.classify_regime(0.05) == g.CRASH
    assert g.classify_regime(0.50) == g.NEUTRAL
    assert g.classify_regime(0.60) == g.NEUTRAL   # boundary: not > 0.6
    assert g.classify_regime(0.40) == g.NEUTRAL   # boundary: not < 0.4


def test_classify_regime_sma_boolean_fallback():
    assert g.classify_regime(p_bull=None, regime_ok=True) == g.BREAKOUT
    assert g.classify_regime(p_bull=None, regime_ok=False) == g.CRASH


def test_classify_regime_degenerate_is_neutral():
    assert g.classify_regime(float("nan")) == g.NEUTRAL
    assert g.classify_regime("x") == g.NEUTRAL
    assert g.classify_regime(None) == g.NEUTRAL


# ── mean-reversion classification (op/value-aware) ───────────────────────────────

def test_is_mean_reversion_bool_and_numeric_direction():
    assert g.is_mean_reversion_filter({"field": "intention_pullback"}) is True
    assert g.is_mean_reversion_filter({"field": "rsi_14", "op": "lt", "value": 35}) is True
    assert g.is_mean_reversion_filter({"field": "above_52w_low_pct", "op": "lte"}) is True
    # Momentum use of the SAME numeric field is NOT mean-reversion.
    assert g.is_mean_reversion_filter({"field": "rsi_14", "op": "gt", "value": 70}) is False
    # Pure trend/momentum filters are never mean-reverting.
    assert g.is_mean_reversion_filter({"field": "vipt_breakout"}) is False
    assert g.is_mean_reversion_filter({"field": "price_gt_ma200"}) is False


# ── filter set selection per regime ──────────────────────────────────────────────

def test_crash_disables_exactly_the_mean_reversion_filters():
    active, disabled = g.active_filters_for_regime(_mixed_filters(), g.CRASH)
    disabled_fields = [(f["field"], f.get("op")) for f in disabled]
    assert ("rsi_14", "lt") in disabled_fields
    assert ("above_52w_low_pct", "lt") in disabled_fields
    assert ("intention_pullback", None) in disabled_fields
    assert len(disabled) == 3
    # Trend / momentum / the RSI>70 momentum clause all SURVIVE.
    active_fields = [(f["field"], f.get("op")) for f in active]
    for keep in [("price_gt_ma200", None), ("ma50_gt_ma200", None),
                 ("vipt_breakout", None), ("rsi_14", "gt")]:
        assert keep in active_fields
    assert len(active) == 4


def test_breakout_disables_mean_reversion_too():
    active, disabled = g.active_filters_for_regime(_mixed_filters(), g.BREAKOUT)
    assert len(disabled) == 3       # same toxic set faded in an expansionary breakout
    assert len(active) == 4


def test_neutral_keeps_all_filters():
    active, disabled = g.active_filters_for_regime(_mixed_filters(), g.NEUTRAL)
    assert disabled == []
    assert len(active) == len(_mixed_filters())


def test_active_filters_preserves_order():
    active, _ = g.active_filters_for_regime(_mixed_filters(), g.CRASH)
    # Surviving clauses keep their original relative order.
    assert active == [f for f in _mixed_filters() if not g.is_mean_reversion_filter(f)]


# ── gate_filters top-level entry point ───────────────────────────────────────────

def test_gate_disabled_is_inert_noop():
    out = g.gate_filters(_mixed_filters(), p_bull=0.05, enabled=False)
    assert out["gated"] is False
    assert out["disabled"] == []
    assert out["active"] == _mixed_filters()   # untouched


def test_gate_crash_gates_mean_reversion():
    out = g.gate_filters(_mixed_filters(), p_bull=0.10, enabled=True)
    assert out["regime"] == g.CRASH
    assert out["gated"] is True
    assert len(out["disabled"]) == 3


def test_gate_neutral_does_not_gate():
    out = g.gate_filters(_mixed_filters(), p_bull=0.50, enabled=True)
    assert out["regime"] == g.NEUTRAL
    assert out["gated"] is False
    assert len(out["disabled"]) == 0


def test_gate_pure_trend_screen_never_gated_even_in_crash():
    # A trend-only screen has no mean-reversion clause ⇒ nothing disabled in a crash.
    trend_only = [{"field": "price_gt_ma200"}, {"field": "ma50_gt_ma200"},
                  {"field": "vipt_breakout"}]
    out = g.gate_filters(trend_only, p_bull=0.01, enabled=True)
    assert out["regime"] == g.CRASH
    assert out["gated"] is False
    assert out["active"] == trend_only


def test_gate_handles_empty_and_garbage_without_raising():
    assert g.gate_filters([], p_bull=0.1, enabled=True)["active"] == []
    # Garbage filter clause must not crash classification/selection.
    out = g.gate_filters([{"field": None}, "not-a-dict"], p_bull=0.1, enabled=True)
    assert isinstance(out["active"], list)


def test_trend_momentum_constant_complement_of_mean_reversion():
    # No filter is simultaneously classified trend AND mean-reversion (no overlap).
    for fld in g.TREND_MOMENTUM_FILTERS:
        assert g.is_mean_reversion_filter({"field": fld}) is False
