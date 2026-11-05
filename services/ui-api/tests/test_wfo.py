"""Unit tests for the real walk-forward optimizer's pure helpers.

These cover the deterministic scaffolding of `_core_wfo` — window generation,
candidate-combination enumeration, objective extraction, embargo enforcement,
and filter labelling — without touching DuckDB. The full IS→OOS simulation is
exercised live against the database in integration runs.
"""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routers.analytics as an  # noqa: E402


# ── Window generation + embargo ───────────────────────────────────────────────────

def test_wfo_windows_have_embargo_gap_and_tile_oos():
    f, t = date(2021, 1, 1), date(2025, 1, 1)
    wins = an._wfo_windows(f, t, in_sample_days=365, out_sample_days=90, embargo_days=7)
    assert len(wins) > 1
    for is_s, is_e, oos_s, oos_e in wins:
        # In-sample length is fixed; OOS strictly after the embargo gap.
        assert (is_e - is_s).days == 365
        assert (oos_s - is_e).days == 7          # embargo gap honored
        assert oos_s <= oos_e <= t               # OOS never runs past the requested end
        assert oos_s > is_e                       # no IS/OOS overlap
    # Consecutive OOS windows tile contiguously (cursor advances by out_sample_days).
    starts = [w[2] for w in wins]
    for a, b in zip(starts, starts[1:]):
        assert (b - a).days == 90


def test_wfo_windows_empty_when_span_too_short():
    f = date(2024, 1, 1)
    t = f + timedelta(days=200)               # < in_sample + embargo → no OOS fold fits
    wins = an._wfo_windows(f, t, in_sample_days=365, out_sample_days=90, embargo_days=7)
    assert wins == []


# ── Candidate combination enumeration ─────────────────────────────────────────────

def test_candidate_combos_enumerates_up_to_max_size():
    pool = [{"field": "a"}, {"field": "b"}, {"field": "c"}]
    combos = an._candidate_combos(pool, max_combo_size=3)
    # C(3,1)+C(3,2)+C(3,3) = 3 + 3 + 1 = 7
    assert len(combos) == 7
    assert [{"field": "a"}] in combos
    combo_fields = {tuple(f["field"] for f in c) for c in combos}
    assert ("a", "b", "c") in combo_fields          # the full triple is enumerated
    assert combo_fields == {("a",), ("b",), ("c",),
                            ("a", "b"), ("a", "c"), ("b", "c"), ("a", "b", "c")}


def test_candidate_combos_respects_cap():
    pool = [{"field": f"f{i}"} for i in range(10)]
    combos = an._candidate_combos(pool, max_combo_size=5, cap=12)
    assert len(combos) == 12


def test_candidate_combos_empty_pool_is_single_empty_config():
    assert an._candidate_combos([], max_combo_size=3) == [[]]


def test_candidate_combos_clamps_max_size_to_pool():
    pool = [{"field": "a"}, {"field": "b"}]
    combos = an._candidate_combos(pool, max_combo_size=9)
    assert len(combos) == 3   # C(2,1)+C(2,2)


# ── Objective extraction ──────────────────────────────────────────────────────────

def test_objective_selects_named_metric():
    m = {"sharpe_ratio": 1.4, "calmar_ratio": 0.6, "total_return_pct": 88.0, "profit_factor": 1.9}
    assert an._objective(m, "sharpe") == 1.4
    assert an._objective(m, "calmar") == 0.6
    assert an._objective(m, "total_return") == 88.0
    assert an._objective(m, "profit_factor") == 1.9
    assert an._objective(m, "unknown_defaults_to_sharpe") == 1.4


def test_objective_handles_infinite_profit_factor():
    # A loss-free in-sample window yields PF=inf; the objective must stay finite/sortable.
    assert an._objective({"profit_factor": float("inf")}, "profit_factor") == 1e6


def test_objective_nan_safe_on_missing_keys():
    assert an._objective({}, "sharpe") == 0.0
    assert an._objective({"calmar_ratio": None}, "calmar") == 0.0


# ── Filter labelling ──────────────────────────────────────────────────────────────

def test_filter_label_numeric_and_boolean():
    assert an._filter_label({"field": "vmi_ratio", "op": "gte", "value": 1.0}) == "vmi_ratio≥1"
    assert an._filter_label({"field": "rsi_14", "op": "lt", "value": 30}) == "rsi_14<30"
    # Boolean filters render as the bare field name (no operator/threshold).
    assert an._filter_label({"field": "squeeze_on"}) == "squeeze_on"


# ── Request contract defaults (backward compatibility) ────────────────────────────

def test_wfo_request_defaults_are_backward_compatible():
    # A legacy payload that only sets the old fields must still validate.
    req = an.WFOBacktestRequest(from_date="2021-01-01", to_date="2024-01-01",
                                in_sample_days=180, out_sample_days=60, monte_carlo_runs=500)
    assert req.objective == "sharpe"
    assert req.candidate_filters == []
    assert req.base_filters == []
    assert req.max_combo_size == 3
    assert req.min_is_trades == 20


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
