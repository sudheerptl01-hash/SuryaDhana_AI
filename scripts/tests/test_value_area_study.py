"""Value-area study: profile math, event detection, look-ahead safety, statistics."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import value_area_study as va  # noqa: E402


def test_profile_poc_sits_at_volume_cluster_and_va_holds_70pct():
    high = np.array([61.0, 61.0, 61.0, 70.0, 52.0])
    low = np.array([59.0, 59.0, 59.0, 68.0, 50.0])
    vol = np.array([1000.0, 1000.0, 1000.0, 50.0, 50.0])
    poc, val, vah = va.volume_profile(high, low, vol, n_bins=40)
    assert 59 <= poc <= 61
    assert 59 <= val < vah <= 61                 # VA sits inside the heavy 59–61 cluster
    assert vah - val >= 0.7 * 2 * (3100 * 0.7 / 3000) - 0.25   # ≈70% of all volume


def test_profile_handles_flat_bars_and_zero_range():
    poc, val, vah = va.volume_profile(np.array([10.0, 11.0]), np.array([10.0, 9.0]), np.array([500.0, 10.0]), 20)
    assert abs(poc - 10) < 0.2
    assert all(np.isnan(va.volume_profile(np.array([5.0]), np.array([5.0]), np.array([1.0]))))


def _balanced_then_breakout(n_balance=30, breakout=75.0, after=(72, 66, 60, 60, 60)):
    closes = [60 + (i % 3 - 1) * 0.5 for i in range(n_balance)] + [breakout, *after]
    c = np.array(closes, float)
    h, l, o = c + 1, c - 1, c.copy()
    v = np.full(len(c), 1000.0)
    return o, h, l, c, v


def test_up_breakout_detected_and_poc_return_counted():
    cfg = va.StudyConfig(window=20, balance_days=5, horizon=5)
    o, h, l, c, v = _balanced_then_breakout()
    prof = va.rolling_profiles(h, l, v, cfg)
    atr = va.wilder_atr(h, l, c, cfg.atr_len)
    ev = va.detect_events(o, h, l, c, v, prof, atr, cfg)
    assert len(ev) == 1
    e = ev[0]
    assert e["direction"] == "UP" and e["complete"] and e["t"] == 30
    assert e["poc_reached"] and e["days_to_poc"] == 3          # close 60 on day 3 → low 59 ≤ POC
    assert e["poc_touch_days"] == 3 and e["va_reentry"]


def test_profile_has_no_look_ahead():
    cfg = va.StudyConfig(window=20)
    o, h, l, c, v = _balanced_then_breakout()
    base = va.rolling_profiles(h, l, v, cfg)
    h2, l2, v2 = h.copy(), l.copy(), v.copy()
    h2[31:], l2[31:], v2[31:] = 500, 400, 1e9               # scramble the future
    assert np.allclose(va.rolling_profiles(h2, l2, v2, cfg)[:31], base[:31], equal_nan=True)


def test_down_breakout_long_trade_exits_at_poc():
    cfg = va.StudyConfig(window=20, horizon=5, cost_pct=0.0)
    o, h, l, c, v = _balanced_then_breakout(breakout=45.0, after=(47, 55, 60, 60, 58))
    prof = va.rolling_profiles(h, l, v, cfg)
    atr = va.wilder_atr(h, l, c, cfg.atr_len)
    e = va.detect_events(o, h, l, c, v, prof, atr, cfg)[0]
    assert e["direction"] == "DOWN" and e["poc_reached"]
    # entry = next open 47; day 3 opens at 60, already through the POC → filled at that open
    assert e["poc"] <= 60
    assert abs(e["trade_ret_pct"] - (60 / 47 - 1) * 100) < 1e-9


def test_open_event_at_end_of_data_is_flagged_incomplete():
    cfg = va.StudyConfig(window=20, horizon=5)
    o, h, l, c, v = _balanced_then_breakout(after=(72, 70))
    prof = va.rolling_profiles(h, l, v, cfg)
    ev = va.detect_events(o, h, l, c, v, prof, va.wilder_atr(h, l, c, 14), cfg)
    assert len(ev) == 1 and not ev[0]["complete"]


def test_excursions_match_bruteforce():
    rng = np.random.default_rng(0)
    c = 100 + rng.normal(0, 1, 60).cumsum()
    h, l = c + rng.uniform(0, 1, 60), c - rng.uniform(0, 1, 60)
    atr = np.ones(60)
    down, up = va.excursions(h, l, c, atr, 5)
    for s in (0, 10, 54):
        assert np.isclose(down[s], c[s] - l[s + 1:s + 6].min())
        assert np.isclose(up[s], h[s + 1:s + 6].max() - c[s])
    assert np.isnan(down[55]) and np.isnan(up[59])


def test_excess_test_and_bh():
    hits = np.array([1, 1, 1, 1, 0] * 20, float)
    p = np.full(100, 0.5)
    exc, z, pv = va.excess_test(hits, p)
    assert abs(exc - 0.3) < 1e-9 and z > 5 and pv < 1e-6
    q = va.bh_qvalues(np.array([0.01, 0.04, 0.03, 0.5]))
    assert np.allclose(q, [0.04, 0.16 / 3, 0.16 / 3, 0.5])
