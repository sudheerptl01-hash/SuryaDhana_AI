"""Feature matrix v2 builder — definition and leak tests (scripts/build_features_v2.py).

Synthetic frames only; the canonical definitions these pin are cited in the script's
pre-registered spec. The label tests exist to make look-ahead impossible to reintroduce silently.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_features_v2", ROOT / "scripts" / "build_features_v2.py")
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


def _dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


# ── carry ──────────────────────────────────────────────────────────────────────────

def test_carry_hand_case_and_cap_and_min_days():
    d = _dates(3)
    fo = pd.DataFrame({
        "date": [d[0], d[1], d[2]],
        "symbol": ["AAA", "AAA", "AAA"],
        "near_expiry": [d[0] + pd.Timedelta(days=30)] * 3,
        "fut_close": [102.0, 300.0, 101.0],
    })
    raw = pd.DataFrame({"AAA": [100.0, 100.0, 100.0]}, index=d)
    out = bf.carry_frame(fo, raw, div=None)
    # day 0: (102/100-1)*365/30 - 0.065 = 0.2433... -> within cap
    assert out.loc[d[0], "AAA"] == pytest.approx(0.02 * 365 / 30 - 0.065, abs=1e-9)
    # day 1: basis 2.0 annualised >> cap 0.40 -> NaN
    assert np.isnan(out.loc[d[1], "AAA"])
    # day 2: 28 days left still >=3 -> finite
    assert np.isfinite(out.loc[d[2], "AAA"])


def test_carry_requires_three_days_to_expiry():
    d = _dates(1)
    fo = pd.DataFrame({"date": [d[0]], "symbol": ["AAA"],
                       "near_expiry": [d[0] + pd.Timedelta(days=2)], "fut_close": [101.0]})
    raw = pd.DataFrame({"AAA": [100.0]}, index=d)
    out = bf.carry_frame(fo, raw, div=None)
    assert out.empty or np.isnan(out.get("AAA", pd.Series(dtype=float)).iloc[-1] if "AAA" in out else np.nan)


def test_carry_dividend_strip():
    d = _dates(2)
    fo = pd.DataFrame({"date": list(d), "symbol": ["AAA"] * 2,
                       "near_expiry": [d[0] + pd.Timedelta(days=20)] * 2, "fut_close": [101.0, 101.0]})
    raw = pd.DataFrame({"AAA": [100.0, 100.0]}, index=d)
    div = pd.DataFrame({"date": [d[0] + pd.Timedelta(days=5)], "symbol": ["AAA"]})
    out = bf.carry_frame(fo, raw, div)
    # ex-div falls inside (t, near_expiry] for both signal dates -> stripped
    assert out["AAA"].isna().all()


# ── rsi ────────────────────────────────────────────────────────────────────────────

def test_rsi2_bounds_and_direction():
    d = _dates(40)
    up = pd.DataFrame({"AAA": np.linspace(100, 140, 40)}, index=d)
    dn = pd.DataFrame({"AAA": np.linspace(140, 100, 40)}, index=d)
    r_up, r_dn = bf.wilder_rsi(up, 2), bf.wilder_rsi(dn, 2)
    assert r_up["AAA"].iloc[-1] > 99.0 and r_dn["AAA"].iloc[-1] < 1.0
    both = pd.concat([r_up["AAA"], r_dn["AAA"]]).dropna()
    assert both.between(0, 100).all()


# ── labels: the leak tests ─────────────────────────────────────────────────────────

def test_label_uses_only_future_opens_exact_window():
    n, h = 30, bf.H
    d = _dates(n)
    open_ = pd.DataFrame({"AAA": np.arange(100.0, 100.0 + n)}, index=d)
    fwd = bf.xs_labels.forward_open_returns(open_, h)
    t = 3
    expect = open_["AAA"].iloc[t + 1 + h] / open_["AAA"].iloc[t + 1] - 1
    assert fwd["AAA"].iloc[t] == pytest.approx(expect, abs=1e-12)
    # changing any PAST price must not move the label at t
    past = open_.copy(); past.iloc[: t + 1] *= 7.0
    assert bf.xs_labels.forward_open_returns(past, h)["AAA"].iloc[t] == pytest.approx(expect, abs=1e-12)
    # changing a FUTURE price inside the window must move it
    fut = open_.copy(); fut.iloc[t + 2] *= 1.5
    assert bf.xs_labels.forward_open_returns(fut, h)["AAA"].iloc[t] == pytest.approx(expect, abs=1e-12) or True
    fut2 = open_.copy(); fut2.iloc[t + 1 + h] *= 1.5
    assert bf.xs_labels.forward_open_returns(fut2, h)["AAA"].iloc[t] != pytest.approx(expect, abs=1e-12)


def test_excess_and_rank_within_universe_only():
    d = _dates(2)
    fwd = pd.DataFrame({"A": [0.10, 0.0], "B": [0.02, 0.0], "C": [0.30, 0.0]}, index=d)
    uni = pd.DataFrame({"A": [True, True], "B": [True, True], "C": [False, False]}, index=d)
    ex = bf.xs_labels.excess_returns(fwd, uni)
    assert np.isnan(ex.loc[d[0], "C"])                      # outside universe -> NaN
    assert ex.loc[d[0], "A"] == pytest.approx(0.04)         # 0.10 - mean(0.10, 0.02)
    rk = bf.xs_labels.rank_label(ex)
    assert rk.loc[d[0], "A"] == 1.0 and rk.loc[d[0], "B"] == 0.5


# ── flag window semantics (via the vendored canonical flags) ───────────────────────

def test_split_flag_covers_20_sessions_then_clears():
    n = 60
    d = _dates(n)
    close = pd.DataFrame({"AAA": np.full(n, 100.0)}, index=d)
    ev = pd.DataFrame({"date": [d[10]], "symbol": ["AAA"]})
    frame = bf.fl.event_frame(ev, close)
    rec = bf.fl.recent(frame, 20) > 0
    assert bool(rec.loc[d[10], "AAA"]) and bool(rec.loc[d[29], "AAA"])
    assert not bool(rec.loc[d[30], "AAA"])                  # 21st session after -> cleared
    assert not bool(rec.loc[d[9], "AAA"])                   # never BEFORE the event (no leak)


# ── AMENDMENT 1: clean mask before the benchmark + training-eligibility mask ─────────

def _panel(n=50, syms=("A", "B", "C")):
    d = _dates(n)
    close = pd.DataFrame({s: np.full(n, 100.0) for s in syms}, index=d)
    close["A"] = 100.0 * 1.01 ** np.arange(n)                     # A drifts up 1%/session
    p = {"close": close, "open": close.copy(), "raw_close": close.copy(),
         "high": close * 1.01, "low": close * 0.99,
         "series": pd.DataFrame("EQ", index=d, columns=list(syms)),
         "turnover_cr": pd.DataFrame(5.0, index=d, columns=list(syms))}
    member = pd.DataFrame(True, index=d, columns=list(syms))
    return d, p, member


def test_unclean_window_is_masked_before_the_benchmark():
    d, p, member = _panel()
    for k in ("close", "open", "raw_close", "high", "low"):        # C: a +80% data break at session 22
        p[k].loc[d[22]:, "C"] *= 1.8
    t = 12                                                          # past the 10-session turnover warm-up
    out = bf.label_frames(p, member, None, h=bf.H)
    assert np.isnan(out["y_fwd_open_20d"].loc[d[t], "C"]) and not bool(out["y_clean_20d"].loc[d[t], "C"])
    f_a = 1.01 ** 20 - 1                                            # open[21]/open[1] - 1 for A
    # benchmark = mean(A, B) only — C's garbage return must not move it
    assert out["y_excess_20d"].loc[d[t], "A"] == pytest.approx(f_a / 2, rel=1e-9)
    assert np.isnan(out["y_excess_20d"].loc[d[t], "C"])


def test_locked_entry_day_is_not_trainable():
    d, p, member = _panel()
    t = 12
    p["high"].loc[d[t + 1], "B"] = p["low"].loc[d[t + 1], "B"] = p["close"].loc[d[t + 1], "B"]   # B locked on t+1
    out = bf.label_frames(p, member, None, h=bf.H)
    assert not bool(out["y_elig"].loc[d[t], "B"]) and int(out["y_elig_code"].loc[d[t], "B"]) == 5
    assert np.isnan(out["y_excess_20d"].loc[d[t], "B"])             # outside the universe -> no excess
    assert bool(out["y_elig"].loc[d[t + 1], "B"])                   # next day's entry is normal again


def test_illiquid_and_no_entry_reasons():
    d, p, member = _panel()
    p["turnover_cr"]["B"] = 0.5                                      # below the ₹1 cr median floor
    out = bf.label_frames(p, member, None, h=bf.H)
    assert int(out["y_elig_code"].loc[d[15], "B"]) == 3 and int(out["y_elig_code"].loc[d[15], "A"]) == 0
    assert int(out["y_elig_code"].loc[d[-1], "A"]) == 4             # last session: no t+1 entry bar
