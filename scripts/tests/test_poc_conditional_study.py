"""POC conditional study: trade simulator, span-matched benchmark, week-clustered stats."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import poc_conditional_study as pc  # noqa: E402


def _bars(closes):
    c = np.array(closes, float)
    return c.copy(), c + 1, c - 1, c


def test_long_trade_time_stop_exits_at_close_of_last_session():
    o, h, l, c = _bars([100, 101, 102, 103, 104, 105, 106])
    x_day, x_px, stopped = pc._long_trade(o, h, l, c, entry_day=1, entry_px=101, stop_px=90)
    assert (x_day, x_px, stopped) == (1 + pc.HOLD_DAYS - 1, c[1 + pc.HOLD_DAYS - 1], False)


def test_long_trade_stop_and_gap_through_stop():
    o, h, l, c = _bars([100, 100, 95, 100, 100, 100, 100])
    o[2] = 98                                                                   # opens above the stop …
    assert pc._long_trade(o, h, l, c, 1, 100, 96.5) == (2, 96.5, True)       # … low 94 hits it
    o2 = o.copy()
    o2[2] = 90                                                                  # opens below the stop
    assert pc._long_trade(o2, h, l, c, 1, 100, 96.5) == (2, 90, True)


def test_long_trade_needs_full_horizon():
    o, h, l, c = _bars([100, 101, 102])
    assert pc._long_trade(o, h, l, c, 1, 101, 90) is None


def test_universe_bench_matches_open_to_close_mean_and_liquidity_mask():
    dates = pd.bdate_range("2024-01-01", periods=30)
    rows = []
    for tk, px, vol in (("A", 100.0, 1e6), ("B", 50.0, 10.0)):              # B is illiquid
        for i, d in enumerate(dates):
            rows.append({"ticker": tk, "date": d, "open": px + i, "high": px + i + 1, "low": px + i - 1,
                         "close": px + i + 0.5, "volume": vol})
    prices = pd.DataFrame(rows)
    e, x = pd.Series([dates[25]]), pd.Series([dates[27]])
    a = (100 + 27.5) / (100 + 25) - 1
    b = (50 + 27.5) / (50 + 25) - 1
    assert np.isclose(pc.UniverseBench(prices).span(e, x)[0], (a + b) / 2 * 100)
    assert np.isclose(pc.UniverseBench(prices, liquid_cr=1.0).span(e, x)[0], a * 100)


def test_clustered_t_counts_a_crowded_week_once():
    d = pd.Series(pd.to_datetime(["2024-01-01"] * 500 + [f"2024-0{m}-10" for m in range(2, 8)]))
    v = pd.Series([-1.0] * 500 + [1.0] * 6)
    assert pc.weekly_means(v, d).mean() > 0 > v.mean()


def test_spread_t_matched_and_welch_fallback():
    rng = np.random.default_rng(1)
    dates = pd.Series(pd.bdate_range("2023-01-02", periods=300))
    top = pd.DataFrame({"date": dates, "x": 1 + rng.normal(0, 1, 300)})
    bot = pd.DataFrame({"date": dates, "x": rng.normal(0, 1, 300)})
    diff, t = pc.spread_t(top, bot, "x")
    assert 0.7 < diff < 1.3 and t > 5
    diff2, t2 = pc.spread_t(top.iloc[:150], bot.iloc[150:], "x")               # no shared weeks
    assert 0.6 < diff2 < 1.4 and t2 > 3
