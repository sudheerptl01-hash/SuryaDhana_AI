"""scripts/evidence_probability_study.py: the statistics behind the conditional-probability map and the labels."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import evidence_probability_study as ep  # noqa: E402


def test_newey_west_widens_the_error_of_an_autocorrelated_series():
    rng = np.random.default_rng(1)
    e = rng.normal(size=600)
    ar = np.zeros(600)
    for i in range(1, 600):                       # overlapping windows behave like a positively autocorrelated series
        ar[i] = 0.8 * ar[i - 1] + e[i]
    m0, se0, n = ep.nw_mean_se(ar, 0)
    m4, se4, _ = ep.nw_mean_se(ar, 12)
    assert n == 600 and m0 == m4 and se4 > 1.8 * se0
    assert math.isnan(ep.nw_mean_se([1.0, 2.0], 4)[1])          # too short for a standard error


def test_empirical_bayes_shrinks_noisy_estimates_more():
    theta = np.array([0.5, 0.5, -0.1, 0.05, 2.0])
    se = np.array([0.1, 1.0, 0.1, 0.1, 0.2])
    eb = ep.eb_shrink(theta, se)
    assert eb["tau2"] > 0
    assert abs(eb["mean"][0]) > abs(eb["mean"][1])               # same estimate, more noise → pulled harder to 0
    assert eb["p_sign"][0] > eb["p_sign"][1] and eb["p_sign"][4] > 0.99
    flat = ep.eb_shrink(np.array([0.01, -0.01]), np.array([1.0, 1.0]))   # nothing beyond noise → τ² = 0, full shrink
    assert flat["tau2"] == 0 and np.allclose(flat["mean"], 0)


def test_verdict_rules_from_the_plan():
    s = lambda d, t, w=50: {"d_ex": d, "t_ex": t, "weeks": w}  # noqa: E731
    assert ep.verdict(s(-0.5, -3), s(-0.4, -2.5)) == "Robust"
    assert ep.verdict(s(-0.5, -3), s(-0.2, -1.2)) == "Holds (weaker)"
    assert ep.verdict(s(-0.5, -3), s(0.3, 1.0)) == "Unstable"
    assert ep.verdict(s(0.1, 0.5), s(0.1, 0.8)) == "No effect"
    assert ep.verdict(s(-0.5, -3), s(-0.4, -2.5, w=5)) == "too little data"


def test_weekly_series_compares_flagged_with_covered_stocks_the_same_week():
    d = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-03"] * 4 + ["2020-01-10"] * 4),
        "flag": [1, 0, 0, np.nan, 1, 1, 0, 0],                   # NaN = not covered by the dataset: excluded
        "ex": [0.05, -0.01, -0.02, 0.50, -0.03, 0.01, 0.02, 0.0],
        "rk": [0.95, 0.4, 0.3, 0.99, 0.1, 0.6, 0.7, 0.5]})
    ws = ep.weekly_series(d, "flag", "ex", "rk")
    w1 = ws.loc[pd.Timestamp("2020-01-03")]
    assert w1.nA == 1 and w1.nE == 3                              # the uncovered +50% stock never enters the base
    assert math.isclose(w1.d_ex, 0.05 - (0.05 - 0.01 - 0.02) / 3)
    assert math.isclose(w1.d_win, 1 - 1 / 3)
    w2 = ws.loc[pd.Timestamp("2020-01-10")]
    assert w2.nA == 2 and math.isclose(w2.botA, 0.5)


def test_relative_triple_barrier_first_touch_and_universe_neutral():
    n, h = 30, 5
    I = np.cumprod(np.full(n, 1.01))                           # the universe rises 1% a day
    C = np.column_stack([I * 1.0, I * np.r_[np.ones(10), np.full(n - 10, 1.2)], I * np.r_[np.ones(10), np.full(n - 10, 0.8)]])
    O = C.copy()
    on = np.zeros(n)
    sig = np.full((n, 3), 0.02)                                # barrier = 0.02 · √5 ≈ 4.5%
    lab, days = ep.relative_triple_barrier(C, O, I, on, sig, np.array([7, 25]), h, 1.0)
    assert lab[0].tolist() == [0.0, 1.0, -1.0]                  # tracks the universe → no touch, however much it rose
    assert days[0, 1] == 3                                      # counted from the signal row 7: the jump lands at row 10
    assert np.isnan(lab[1]).all()                               # window runs past the data → no label


def test_value_area_break_detection_on_a_range_then_breakout():
    n = 60
    c = 100 + 0.05 * np.sin(np.arange(n))                       # closes sit in the middle of each day's range
    c[40] = 108.0                                               # a close far above a tight 20-day range
    hi, lo, vo = c + 1.0, c - 1.0, np.full(n, 1e5)
    vo[40] = 3e5
    _, up, dn, rv = ep.va_one(("X", hi, lo, c, vo))
    assert up[40] and not dn[40] and rv[40] == 3.0
    assert not up[:40].any()


def test_hindsight_coverage_does_not_change_predictions(monkeypatch):
    # Training: covered stocks always beat the market (the hindsight effect). Today, two stocks identical except for
    # coverage must get the same P(win), or the model is ranking stocks by "will be liquid in 2026".
    rng = np.random.default_rng(5)
    dates = pd.date_range("2016-01-08", "2020-12-25", freq="W-FRI")
    rows = []
    for d in dates:
        for j in range(60):
            cov = float(j < 30)
            rows.append({"date": d, "symbol": f"S{j}", "inL": True, "is_week": True, "mom_pctL": rng.random(),
                         "k1": (float(rng.random() < 0.1) if cov else np.nan), "cov_shp": cov,
                         "exL_20": (0.02 if cov else -0.02) + rng.normal(0, 0.01), "rkL_20": rng.random()})
    df = pd.DataFrame(rows)
    sessions = pd.bdate_range("2015-01-01", "2021-12-31")
    pred, _, _ = ep.walk_forward(df, "inL", "exL_20", "rkL_20", ["k1"], ["cov_shp"], "mom_pctL", {}, sessions,
                                 [2020], lambda *_: None)
    test = df.loc[pred.index][df.loc[pred.index, "date"].dt.year == 2020].assign(p=pred["pC_win"])
    test = test[test["k1"].fillna(0) == 0]
    gap = test.groupby(test["cov_shp"] == 1)["p"].mean()
    assert abs(gap[True] - gap[False]) < 0.01          # membership alone no longer moves the probability
    monkeypatch.setattr(ep, "HINDSIGHT_COV", set())      # the first run's behaviour: the leak is visible
    pred, _, _ = ep.walk_forward(df, "inL", "exL_20", "rkL_20", ["k1"], ["cov_shp"], "mom_pctL", {}, sessions,
                                 [2020], lambda *_: None)
    leak = test.assign(p=pred.loc[test.index, "pC_win"]).groupby(test["cov_shp"] == 1)["p"].mean()
    assert leak[True] - leak[False] > 0.2
