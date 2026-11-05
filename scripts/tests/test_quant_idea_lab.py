"""Idea lab: circuit-lock detection, weekly schedule, verdict rule, factor look-ahead."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import quant_idea_lab as ql  # noqa: E402


def _col(vals):
    return np.array(vals, float).reshape(-1, 1)


def test_lower_circuit_lock_needs_band_move_and_close_at_low():
    c = _col([100, 95, 90.25, 88])
    l = _col([99, 95, 90.0, 87])              # day 1 pinned at low; day 2 closed off the low
    o = h = _col([100, 99, 94, 90])
    got = ql.lower_circuit_locks(o, h, l, c)[:, 0]
    assert got.tolist() == [False, True, False, False]   # day 3: −2.5% is not a band


def test_lower_circuit_bands_10_and_20pct():
    c = _col([100, 90, 72])
    got = ql.lower_circuit_locks(c, c, c, c)[:, 0]
    assert got.tolist() == [False, True, True]


def test_weekly_schedule_signals_on_last_session_of_week():
    idx = pd.bdate_range("2024-01-01", periods=20)          # Mon..Fri × 4
    sched = ql.weekly_schedule(idx)
    assert all(idx[s].dayofweek == 4 for s, _, _ in sched)
    assert all(e == s + 1 and x == s + ql.HOLD for s, e, x in sched)


def test_verdict_rule():
    assert ql.verdict(3.0, 0.2, 2.5, 0.3) == "STRONG"
    assert ql.verdict(2.2, 0.1, 1.2, 0.3) == "PROMISING"
    assert ql.verdict(3.0, -0.1, 2.5, 0.3) == "REJECTED"
    assert ql.verdict(3.0, 0.2, 2.5, -0.3) == "REJECTED"


def test_factors_use_no_future_data():
    idx = pd.bdate_range("2023-01-02", periods=120)
    rng = np.random.default_rng(3)
    base = pd.DataFrame(100 + rng.normal(0, 1, (120, 3)).cumsum(0), index=idx, columns=list("ABC"))
    w = {"open": base * 0.999, "high": base * 1.01, "low": base * 0.99, "close": base,
         "volume": base * 0 + 1e5, "adjusted_close": base,
         "div": pd.DataFrame({"ticker": ["A"], "date": [idx[50]], "amount": [2.0]}),
         "splits": pd.DataFrame(columns=["ticker", "date", "ratio"])}
    f1 = ql.factors(w)
    w2 = {k: (v.copy() if isinstance(v, pd.DataFrame) else v) for k, v in w.items()}
    for k in ("open", "high", "low", "close", "adjusted_close", "volume"):
        w2[k].iloc[100:] *= 3                                # change only the future
    f2 = ql.factors(w2)
    for name in f1:
        pd.testing.assert_frame_equal(f1[name].iloc[:100], f2[name].iloc[:100])
