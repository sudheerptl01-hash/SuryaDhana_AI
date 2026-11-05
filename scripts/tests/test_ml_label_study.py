"""ML label study helpers: book accounting, period returns, IC and Newey-West."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ml_label_study as mls  # noqa: E402


def test_period_returns_run_from_next_open_to_next_open():
    idx = pd.bdate_range("2024-01-01", periods=8)
    op = pd.DataFrame({"A": [10, 11, 12, 13, 14, 15, 16, 17.0]}, index=idx)
    r = mls.period_returns(op, idx[[0, 3, 6]], max_gap=5)
    assert abs(r.at[idx[0], "A"] - (14 / 11 - 1)) < 1e-12 and abs(r.at[idx[3], "A"] - (17 / 14 - 1)) < 1e-12
    assert np.isnan(r.at[idx[6], "A"])                        # the last rebalance has no exit yet


def test_book_charges_costs_on_names_traded_and_measures_against_the_universe():
    dates = pd.bdate_range("2024-01-01", periods=2)
    syms = [f"S{i}" for i in range(60)]
    scores = pd.DataFrame([np.arange(60, 0, -1)] * 2, index=dates, columns=syms, dtype=float)
    rets = pd.DataFrame(0.0, index=dates, columns=syms)
    rets.iloc[:, :20] = 0.05                                  # the top-20 names each make 5%
    uni = pd.DataFrame(True, index=dates, columns=syms)
    b = mls.run_book(scores, rets, uni, cost_side=0.005)
    first = b.iloc[0]
    assert abs(first["gross"] - 0.05) < 1e-12 and abs(first["bench"] - 20 * 0.05 / 60) < 1e-12
    assert abs(first["cost"] - 0.005) < 1e-12                 # 20 buys / 20 names × 0.5%
    assert b.iloc[1]["cost"] == 0 and b.iloc[1]["turnover"] == 0


def test_daily_ic_is_a_per_date_rank_correlation():
    d = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"] * 4 + ["2024-01-08"] * 4),
                      "s": [1, 2, 3, 4, 1, 2, 3, 4], "y": [10, 20, 30, 40, 40, 30, 20, 10]})
    ic = mls.daily_ic(d, "s", "y")
    assert ic.tolist() == [1.0, -1.0]


def test_newey_west_shrinks_t_for_autocorrelated_series():
    rng = np.random.default_rng(3)
    x = pd.Series(np.convolve(rng.normal(0.01, 0.05, 600), np.ones(4) / 4, mode="valid"))
    plain = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert abs(mls.newey_west_t(x, 4)) < abs(plain)
