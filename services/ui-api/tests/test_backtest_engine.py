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


def test_gap_down_fills_at_open_not_stop():
    # SL=2% -> stop 98. Bar OPENS at 95 (gap below stop) -> fill at 95, not 98.
    r = be.resolve_trade_exit(
        highs=np.array([96.0]), lows=np.array([94.0]), closes=np.array([95.0]),
        entry_price=100, forward_days=1, friction_bps=0.0, stop_loss_pct=2.0,
        opens=np.array([95.0]))
    assert r["exit_reason"] == "stop_loss"
    assert r["exit_price"] == pytest.approx(95.0)


def test_no_gap_fills_at_stop_level():
    # Open (100) above stop (98); intraday low pierces -> fill exactly at the stop.
    r = be.resolve_trade_exit(
        highs=np.array([101.0]), lows=np.array([97.0]), closes=np.array([97.5]),
        entry_price=100, forward_days=1, friction_bps=0.0, stop_loss_pct=2.0,
        opens=np.array([100.0]))
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


def test_max_drawdown_circuit_breaker_halts_entries():
    # T1 loses 10% (NAV 1000->900, -10% DD). With a 5% halt, the day-1 T2 signal
    # must be blocked; without the halt it would be taken.
    all_dates = [f"2024-01-0{i+1}" for i in range(4)]

    def price_at(idx, ticker):
        return 100.0

    entries = {
        0: [{"ticker": "T1", "entry_price": 100.0, "exit_idx": 1, "net_return_pct": -10.0,
             "gross_return_pct": -10.0, "exit_price": 90.0, "exit_reason": "stop_loss",
             "holding_days": 1, "win_threshold": 0.0, "entry_date": all_dates[0], "exit_date": all_dates[1]}],
        1: [{"ticker": "T2", "entry_price": 100.0, "exit_idx": 3, "net_return_pct": 5.0,
             "gross_return_pct": 5.0, "exit_price": 105.0, "exit_reason": "time_stop",
             "holding_days": 2, "win_threshold": 0.0, "entry_date": all_dates[1], "exit_date": all_dates[3]}],
    }
    _, halted = be.simulate_portfolio(all_dates, 0, 3, entries, price_at,
                                      starting_capital=1000.0, max_positions=1, max_drawdown_halt_pct=5.0)
    _, open_ = be.simulate_portfolio(all_dates, 0, 3, entries, price_at,
                                     starting_capital=1000.0, max_positions=1)
    assert len(halted) == 1   # T2 blocked by the circuit breaker
    assert len(open_) == 2    # T2 taken without the breaker


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


# ── Advanced alpha factor engine (Pillar 1) ───────────────────────────────────────

import pandas as pd  # noqa: E402


def _synth(ticker, n=80, seed=0, base=100.0):
    """Deterministic OHLCV walk for one ticker."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.001, 0.02, n)
    close = base * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    openp = close * (1 + rng.normal(0, 0.005, n))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "ticker": ticker, "date": dates, "open": openp, "high": np.maximum(high, close),
        "low": np.minimum(low, close), "close": close, "volume": vol,
    })


def test_advanced_factor_columns_present_and_finite_after_warmup():
    df = pd.concat([_synth("AAA", seed=1), _synth("BBB", seed=2)], ignore_index=True)
    out = be.compute_indicators(df)
    for col in ("vmi_ratio", "vol_zscore_20", "intraday_intention", "squeeze_ratio",
                "vipt_breakout", "squeeze_on", "intention_pullback"):
        assert col in out.columns, col
    # Booleans are real bools (never NaN) so filters never crash.
    assert out["vipt_breakout"].dtype == bool
    assert out["squeeze_on"].dtype == bool
    # After warm-up the squeeze ratio is finite for most rows.
    tail = out[out["date"] > "2024-03-01"]
    assert tail["squeeze_ratio"].notna().mean() > 0.8


def test_intraday_intention_flat_bar_is_nan_not_crash():
    # A single ticker where every bar is flat (H==L==C) → CLV undefined → NaN, no crash.
    n = 10
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "ticker": "FLAT", "date": dates, "open": 100.0, "high": 100.0,
        "low": 100.0, "close": 100.0, "volume": 1_000_000.0,
    })
    out = be.compute_indicators(df)
    assert out["intraday_intention"].isna().all()       # all flat → all NaN
    assert out["intention_pullback"].dtype == bool       # boolean still well-formed
    assert not out["intention_pullback"].any()


def test_intraday_intention_bounds_and_value():
    # Close pinned to the high every bar → CLV == 1.0 → 3-day intention == 1.0.
    n = 6
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "ticker": "TOP", "date": dates, "open": 99.0, "high": 101.0,
        "low": 99.0, "close": 101.0, "volume": 1_000_000.0,
    })
    out = be.compute_indicators(df)
    assert out["intraday_intention"].dropna().between(0.0, 1.0).all()
    assert out["intraday_intention"].iloc[-1] == pytest.approx(1.0)


def test_vmi_handles_zero_atr_gracefully():
    # Flat price → ATR% == 0 everywhere → VMI must be NaN, never inf/raise.
    n = 30
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "ticker": "FLAT", "date": dates, "open": 50.0, "high": 50.0,
        "low": 50.0, "close": 50.0, "volume": 2_000_000.0,
    })
    out = be.compute_indicators(df)
    assert not np.isinf(out["vmi_ratio"].to_numpy(dtype=float)).any()
    assert out["vmi_ratio"].isna().all()


def test_compute_indicators_empty_frame():
    empty = pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    out = be.compute_indicators(empty)
    assert out.empty


def test_market_relative_factors_and_sector_dispersion():
    # Two sectors, two names each. Sector-relative momentum must sum ~0 within a
    # sector on any given day (deviation from the sector mean).
    frames = [_synth(t, seed=i) for i, t in enumerate(["AAA", "BBB", "CCC", "DDD"])]
    df = be.compute_indicators(pd.concat(frames, ignore_index=True))
    sector_of = {"AAA": "Tech", "BBB": "Tech", "CCC": "Bank", "DDD": "Bank"}
    out = be.compute_market_relative(df, sector_of)
    for col in ("sector_rel_mom_14_pct", "corr_nifty_30",
                "sector_positive_regime", "decoupled_leader"):
        assert col in out.columns, col
    assert out["corr_nifty_30"].dropna().between(-1.0001, 1.0001).all()
    # Within a (sector, date) the relative-momentum deviations net to ~0.
    last_day = out["date"].max()
    day = out[(out["date"] == last_day)]
    grp = day.groupby(day["ticker"].map(sector_of))["sector_rel_mom_14_pct"].sum()
    assert grp.abs().max() == pytest.approx(0.0, abs=1e-6)


def test_market_relative_empty_is_safe():
    empty = pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
    out = be.compute_market_relative(empty, {})
    assert out is None or out.empty


def test_boolean_factor_filters_apply_without_market_columns():
    # apply_filters must not crash if a market-relative boolean is requested on a
    # frame that only ran compute_indicators (columns absent → all-False predicate).
    df = be.compute_indicators(_synth("AAA", seed=7))
    day = df[df["date"] == df["date"].max()].copy()
    out = be.apply_filters(day, [{"field": "decoupled_leader", "op": "gt", "value": 0}])
    assert out.empty  # column absent → predicate False → no rows, no exception
