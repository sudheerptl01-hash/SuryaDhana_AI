"""Unit tests for the institutional backtest engine math (pure, no IO)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_engine as be  # noqa: E402


# ── Friction realism ────────────────────────────────────────────────────────────

def test_friction_netting_flat_path():
    # Price rises 100 -> 110 over 5 days, no SL/trail. Gross +10%, net = 10 - 0.15.
    highs = np.array([102, 104, 106, 108, 111])
    lows = np.array([99, 101, 103, 105, 108])
    closes = np.array([101, 103, 105, 107, 110])
    r = be.resolve_trade_exit(highs, lows, closes, entry_price=100, forward_days=5,
                              friction_bps=15.0)
    assert r["exit_reason"] == "time_stop"
    assert r["holding_days"] == 5
    assert r["gross_return_pct"] == pytest.approx(10.0, abs=1e-6)
    assert r["net_return_pct"] == pytest.approx(9.85, abs=1e-6)
    assert r["is_win"] is True


def test_zero_friction_equals_gross():
    closes = np.array([105.0])
    r = be.resolve_trade_exit(np.array([106.0]), np.array([104.0]), closes,
                              entry_price=100, forward_days=1, friction_bps=0.0)
    assert r["net_return_pct"] == pytest.approx(r["gross_return_pct"])


# ── Stop-loss / trailing / time-stop ──────────────────────────────────────────────

def test_stop_loss_trigger():
    # SL at -2% => 98. Day 2 low pierces 97 -> exit at 98.
    highs = np.array([101, 100, 105])
    lows = np.array([99, 97, 103])
    closes = np.array([100, 98.5, 104])
    r = be.resolve_trade_exit(highs, lows, closes, entry_price=100, forward_days=3,
                              friction_bps=15.0, stop_loss_pct=2.0)
    assert r["exit_reason"] == "stop_loss"
    assert r["holding_days"] == 2
    assert r["exit_price"] == pytest.approx(98.0)
    assert r["gross_return_pct"] == pytest.approx(-2.0, abs=1e-6)
    assert r["net_return_pct"] == pytest.approx(-2.15, abs=1e-6)
    assert r["is_win"] is False


def test_trailing_stop_trigger():
    # trail 5%. Day1 high=110 (peak->110 after check). Day2 trail=104.5; low 104 pierces.
    highs = np.array([110, 108, 109])
    lows = np.array([101, 104, 106])
    closes = np.array([109, 105, 108])
    r = be.resolve_trade_exit(highs, lows, closes, entry_price=100, forward_days=3,
                              friction_bps=0.0, trailing_stop_pct=5.0)
    assert r["exit_reason"] == "trailing_stop"
    assert r["holding_days"] == 2
    assert r["exit_price"] == pytest.approx(104.5)


def test_time_stop_when_nothing_triggers():
    highs = np.array([101, 102, 103])
    lows = np.array([99.5, 100, 101])
    closes = np.array([100.5, 101, 102.5])
    r = be.resolve_trade_exit(highs, lows, closes, entry_price=100, forward_days=3,
                              friction_bps=10.0, stop_loss_pct=10.0, trailing_stop_pct=20.0)
    assert r["exit_reason"] == "time_stop"
    assert r["holding_days"] == 3
    assert r["exit_price"] == pytest.approx(102.5)


def test_stop_loss_takes_priority_over_trailing_same_day():
    # Both SL (98) and a trailing level would be pierced; SL must win.
    highs = np.array([100.0])
    lows = np.array([90.0])
    closes = np.array([92.0])
    r = be.resolve_trade_exit(highs, lows, closes, entry_price=100, forward_days=1,
                              friction_bps=0.0, stop_loss_pct=2.0, trailing_stop_pct=5.0)
    assert r["exit_reason"] == "stop_loss"
    assert r["exit_price"] == pytest.approx(98.0)


# ── Capital-managed compounding portfolio ─────────────────────────────────────────

def test_portfolio_compounds_not_additive():
    # Two sequential +10% net trades, max 1 position. 1000 -> 1100 -> 1210 (compounded),
    # NOT 1200 (the old additive bug).
    all_dates = [f"2024-01-0{i+1}" for i in range(5)]
    price = {("T1"): 100.0, ("T2"): 100.0}

    def price_at(idx, ticker):
        return price[ticker]

    entries = {
        0: [{"ticker": "T1", "entry_price": 100.0, "exit_idx": 2,
             "net_return_pct": 10.0, "gross_return_pct": 10.0, "exit_price": 110.0,
             "exit_reason": "time_stop", "holding_days": 2, "win_threshold": 0.0,
             "entry_date": all_dates[0], "exit_date": all_dates[2]}],
        2: [{"ticker": "T2", "entry_price": 100.0, "exit_idx": 4,
             "net_return_pct": 10.0, "gross_return_pct": 10.0, "exit_price": 110.0,
             "exit_reason": "time_stop", "holding_days": 2, "win_threshold": 0.0,
             "entry_date": all_dates[2], "exit_date": all_dates[4]}],
    }
    equity, trades = be.simulate_portfolio(
        all_dates, 0, 4, entries, price_at, starting_capital=1000.0, max_positions=1)

    assert len(trades) == 2
    assert equity[-1]["nav"] == pytest.approx(1210.0, abs=1e-6)
    m = be.compute_metrics(equity, trades, bench_nav=[], starting_capital=1000.0)
    assert m["total_return_pct"] == pytest.approx(21.0, abs=1e-6)
    assert m["final_nav"] == pytest.approx(1210.0, abs=1e-6)


def test_max_positions_caps_concurrency():
    all_dates = [f"2024-01-0{i+1}" for i in range(6)]

    def price_at(idx, ticker):
        return 100.0

    # Three signals on day 0, but max_positions=2 -> only 2 entered.
    entries = {
        0: [
            {"ticker": f"S{i}", "entry_price": 100.0, "exit_idx": 5,
             "net_return_pct": 5.0, "gross_return_pct": 5.0, "exit_price": 105.0,
             "exit_reason": "time_stop", "holding_days": 5, "win_threshold": 0.0,
             "entry_date": all_dates[0], "exit_date": all_dates[5]}
            for i in range(3)
        ]
    }
    equity, trades = be.simulate_portfolio(
        all_dates, 0, 5, entries, price_at, starting_capital=1000.0, max_positions=2)
    assert len(trades) == 2  # third signal rejected — no slot


def test_duplicate_ticker_same_day_does_not_destroy_capital():
    # Regression: duplicate same-ticker candidates must not double-spend cash.
    all_dates = [f"2024-01-0{i+1}" for i in range(4)]

    def price_at(idx, ticker):
        return 100.0

    dup = {
        "ticker": "DUP", "entry_price": 100.0, "exit_idx": 3, "net_return_pct": 0.0,
        "gross_return_pct": 0.0, "exit_price": 100.0, "exit_reason": "time_stop",
        "holding_days": 3, "win_threshold": 0.0,
        "entry_date": all_dates[0], "exit_date": all_dates[3],
    }
    entries = {0: [dict(dup), dict(dup), dict(dup)]}  # same ticker x3
    equity, trades = be.simulate_portfolio(
        all_dates, 0, 3, entries, price_at, starting_capital=1000.0, max_positions=3)
    assert len(trades) == 1                      # only one position for DUP
    assert equity[0]["nav"] == pytest.approx(1000.0)   # capital fully preserved
    assert equity[-1]["nav"] == pytest.approx(1000.0)


# ── Risk / return analytics ───────────────────────────────────────────────────────

def test_beta_alpha_identical_series():
    rets = np.array([0.01, -0.02, 0.015, 0.0, 0.03])
    beta, alpha = be.beta_alpha(rets, rets)
    assert beta == pytest.approx(1.0, abs=1e-6)
    assert alpha == pytest.approx(0.0, abs=1e-6)


def test_beta_double_series():
    bench = np.array([0.01, -0.02, 0.015, 0.0, 0.03])
    port = bench * 2.0
    beta, _ = be.beta_alpha(port, bench)
    assert beta == pytest.approx(2.0, abs=1e-6)


def test_expectancy_formula():
    # 60% win rate, +5 avg win, -2 avg loss => 0.6*5 - 0.4*2 = 2.2
    assert be.expectancy(60.0, 5.0, -2.0) == pytest.approx(2.2, abs=1e-9)


def test_max_drawdown_and_duration():
    nav = [100, 110, 90, 95, 115]
    assert be.max_drawdown(nav) == pytest.approx((90 / 110 - 1) * 100, abs=1e-6)
    # Peak 110 @1, recovers 115 @4 -> 3 trading days underwater.
    assert be.max_drawdown_duration(nav) == 3


def test_drawdown_duration_monotonic_is_zero():
    assert be.max_drawdown_duration([100, 110, 120, 130]) == 0


def test_drawdown_duration_never_recovers():
    assert be.max_drawdown_duration([100, 95, 90, 85]) == 3


def test_monte_carlo_shape():
    mc = be.monte_carlo_drawdowns([2.0, -1.5, 3.0, -2.0, 1.0], n_runs=200)
    assert set(mc.keys()) == {"p5", "p25", "p50", "p75", "p95", "histogram"}
    assert len(mc["histogram"]) == 30
    assert mc["p95"] >= mc["p5"]


def test_fundamental_filter_detection():
    assert be.fundamental_filters_active([{"field": "pe_ratio", "op": "lt", "value": 25}])
    assert not be.fundamental_filters_active([{"field": "rsi_14", "op": "gt", "value": 50}])
