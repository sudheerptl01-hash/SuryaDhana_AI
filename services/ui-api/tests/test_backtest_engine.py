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


# ── P1/P2: advanced risk sizing + gates in simulate_portfolio ─────────────────────

def _dates(n: int) -> list[str]:
    return [f"2023-01-{d:02d}" for d in range(1, n + 1)]


def _entry(ticker: str, ret: float, exit_idx: int = 2, entry_price: float = 100.0,
           atr_pct=None, sector="Unknown") -> dict:
    """Minimal entry candidate as consumed by simulate_portfolio."""
    return {
        "ticker": ticker, "entry_price": entry_price, "exit_price": entry_price * (1 + ret / 100),
        "exit_idx": exit_idx, "net_return_pct": ret, "gross_return_pct": ret,
        "holding_days": exit_idx, "exit_reason": "time_stop", "win_threshold": 0.0,
        "entry_date": "2023-01-01", "exit_date": _dates(exit_idx + 1)[exit_idx],
        "atr_pct": atr_pct, "sector": sector,
    }


def _flat_price(idx, ticker):
    return 100.0   # flat MTM → NAV moves only on realised exits


def test_default_sizing_is_equal_weight():
    # All advanced knobs off → two same-day entries get identical NAV/max_positions allocation.
    entries = {0: [_entry("A", 10.0), _entry("B", 10.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5)
    allocs = {t["ticker"]: t["capital_allocated"] for t in trades}
    assert allocs["A"] == pytest.approx(allocs["B"], rel=1e-9)
    assert allocs["A"] == pytest.approx(200_000.0, rel=1e-6)   # 1,000,000 / 5


def test_vol_target_sizes_inversely_to_atr():
    # vol_target 2% : calm name (ATR 1%) scales 2×, jumpy name (ATR 4%) scales 0.5×.
    entries = {0: [_entry("CALM", 5.0, atr_pct=1.0), _entry("JUMPY", 5.0, atr_pct=4.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      vol_target_pct=2.0)
    allocs = {t["ticker"]: t["capital_allocated"] for t in trades}
    assert allocs["CALM"] == pytest.approx(400_000.0, rel=1e-6)   # base 200k × 2.0
    assert allocs["JUMPY"] == pytest.approx(100_000.0, rel=1e-6)  # base 200k × 0.5


def test_vol_target_scale_is_bounded():
    # An ultra-low ATR cannot lever the position past the 2.5× cap.
    entries = {0: [_entry("A", 5.0, atr_pct=0.01)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      vol_target_pct=2.0)
    assert trades[0]["capital_allocated"] == pytest.approx(500_000.0, rel=1e-6)  # 200k × 2.5 cap


def test_max_position_pct_caps_allocation():
    entries = {0: [_entry("A", 5.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      max_position_pct=10.0)
    assert trades[0]["capital_allocated"] == pytest.approx(100_000.0, rel=1e-6)  # min(200k, 10% NAV)


def test_sector_cap_rejects_overconcentration():
    # Two 20%-NAV entries in one sector with a 25% sector cap → only the first is taken.
    entries = {0: [_entry("A", 5.0, sector="Tech"), _entry("B", 5.0, sector="Tech")]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      max_sector_pct=25.0)
    assert [t["ticker"] for t in trades] == ["A"]
    assert trades[0]["sector"] == "Tech"


def test_sector_cap_allows_diversified_entries():
    entries = {0: [_entry("A", 5.0, sector="Tech"), _entry("B", 5.0, sector="Energy")]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      max_sector_pct=25.0)
    assert sorted(t["ticker"] for t in trades) == ["A", "B"]


def test_regime_gate_blocks_entries_when_risk_off():
    entries = {0: [_entry("A", 5.0)]}
    _, blocked = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                       starting_capital=1_000_000, max_positions=5,
                                       regime_ok_by_date={"2023-01-01": False})
    assert blocked == []
    _, allowed = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                       starting_capital=1_000_000, max_positions=5,
                                       regime_ok_by_date={"2023-01-01": True})
    assert [t["ticker"] for t in allowed] == ["A"]


# ── P4: ADV participation cap + market-impact slippage ────────────────────────────

def _entry_liq(ticker, ret, adv, atr_pct=2.0, exit_idx=2):
    e = _entry(ticker, ret, exit_idx=exit_idx, atr_pct=atr_pct)
    e["adv"] = adv
    return e


def test_adv_cap_clips_allocation_to_participation():
    # Base alloc would be 200k (NAV/5); a thin name (ADV 1M, cap 10%) limits fill to 100k.
    entries = {0: [_entry_liq("THIN", 5.0, adv=1_000_000)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      max_participation_pct=10.0)
    assert trades[0]["capital_allocated"] == pytest.approx(100_000.0, rel=1e-6)


def test_adv_cap_no_effect_when_liquid():
    # A deep name (ADV 100M) is unconstrained — full 200k base alloc fills.
    entries = {0: [_entry_liq("DEEP", 5.0, adv=100_000_000)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      max_participation_pct=10.0)
    assert trades[0]["capital_allocated"] == pytest.approx(200_000.0, rel=1e-6)


def test_market_impact_degrades_return_with_size():
    # alloc 200k into ADV 1M = 20% participation, ATR 2%, coef 1 →
    # round-trip impact = 2 · 1 · 2 · sqrt(0.2) = 1.789%, deducted from +5% gross.
    entries = {0: [_entry_liq("X", 5.0, adv=1_000_000, atr_pct=2.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      impact_coef=1.0)
    expected_impact = 2.0 * 1.0 * 2.0 * (200_000 / 1_000_000) ** 0.5
    assert trades[0]["impact_pct"] == pytest.approx(expected_impact, abs=1e-3)
    assert trades[0]["return_pct"] == pytest.approx(5.0 - expected_impact, abs=1e-2)


def test_impact_off_by_default_leaves_return_untouched():
    entries = {0: [_entry_liq("X", 5.0, adv=1_000_000)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5)
    assert trades[0]["impact_pct"] == 0.0
    assert trades[0]["return_pct"] == pytest.approx(5.0, rel=1e-9)


# ── G3: multiple-testing statistics (Deflated Sharpe / PBO) ───────────────────────

def test_psr_monotonic_and_bounded():
    p_low = be.probabilistic_sharpe_ratio(0.05, 0.0, 252)
    p_high = be.probabilistic_sharpe_ratio(0.15, 0.0, 252)
    assert 0.0 <= p_low <= 1.0 and 0.0 <= p_high <= 1.0
    assert p_high > p_low


def test_expected_max_sharpe_grows_with_trials():
    s10 = be.expected_max_sharpe(0.01, 10)
    s100 = be.expected_max_sharpe(0.01, 100)
    assert s100 > s10 > 0


def test_expected_max_sharpe_degenerate():
    assert be.expected_max_sharpe(0.0, 100) == 0.0      # no trial dispersion
    assert be.expected_max_sharpe(0.01, 1) == 0.0       # single trial


def test_deflated_sharpe_penalizes_more_trials():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.001, 0.01, 500)                 # mild positive daily edge
    few = be.deflated_sharpe_ratio(rets, [1.0, 1.1, 0.9])
    many = be.deflated_sharpe_ratio(rets, list(rng.normal(0.5, 0.5, 200)))
    assert 0.0 <= many["dsr"] <= few["dsr"] <= 1.0      # more trials ⇒ harsher deflation
    assert few["n_obs"] == 500 and many["n_trials"] == 200


def test_deflated_sharpe_short_series_safe():
    out = be.deflated_sharpe_ratio([0.01, 0.02], [1.0, 1.0])
    assert out["dsr"] == 0.0 and out["n_obs"] == 2


def test_pbo_zero_when_one_config_dominates():
    # Config 0 is the best in every block, in-sample and out-of-sample → never overfit.
    M = np.tile([3.0, 2.0, 1.0, 0.0], (6, 1))
    out = be.probability_of_backtest_overfitting(M)
    assert out["pbo"] == 0.0 and out["n_blocks"] == 6 and out["n_configs"] == 4


def test_pbo_handles_odd_blocks_and_small_matrix():
    assert be.probability_of_backtest_overfitting(np.ones((3, 5))) is None   # <4 even blocks
    M = np.random.default_rng(1).normal(size=(8, 10))
    out = be.probability_of_backtest_overfitting(M)
    assert out is not None and 0.0 <= out["pbo"] <= 1.0 and out["n_splits"] == 70  # C(8,4)


# ── G6: Fama-French / Carhart factor attribution ─────────────────────────────────

def test_compute_factor_returns_columns():
    rng = np.random.default_rng(2)
    n = 260
    df = pd.DataFrame({
        "ticker": np.repeat(list("ABCDEF"), n),
        "date": list(pd.date_range("2022-01-03", periods=n, freq="B")) * 6,
    })
    df["close"] = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(df))))
    df["mktcap_cr"] = np.repeat([100.0, 200, 500, 1000, 5000, 20000], n)
    fr = be.compute_factor_returns(df)
    assert {"MKT", "SMB", "UMD"}.issubset(fr.columns)
    assert len(fr) > 200 and fr.index.is_monotonic_increasing


def test_factor_attribution_recovers_loadings():
    rng = np.random.default_rng(0)
    dates = pd.date_range("2022-01-03", periods=300, freq="B")
    mkt = rng.normal(0.0005, 0.01, 300)
    umd = rng.normal(0.0, 0.006, 300)
    fr = pd.DataFrame({"MKT": mkt, "SMB": rng.normal(0, 0.006, 300), "UMD": umd}, index=dates)
    port = 0.6 * mkt + 0.3 * umd + 0.0004 + rng.normal(0, 0.002, 300)   # true α≈10%/yr
    out = be.factor_attribution(port, list(dates), fr)
    assert out["loadings"]["MKT"] == pytest.approx(0.6, abs=0.06)
    assert out["loadings"]["UMD"] == pytest.approx(0.3, abs=0.06)
    assert out["alpha_annual_pct"] > 0 and out["alpha_tstat"] > 2     # significant positive α
    assert out["r_squared"] > 0.8 and out["factors"] == ["MKT", "SMB", "UMD"]


def test_factor_attribution_insufficient_data_is_none():
    fr = pd.DataFrame({"MKT": [0.01, 0.02, -0.01]}, index=pd.date_range("2022-01-03", periods=3))
    assert be.factor_attribution([0.01, 0.0, -0.01], list(fr.index), fr) is None
    assert be.factor_attribution([0.01] * 50, list(range(50)), None) is None


# ── G4: endogenous Amihud/Kyle permanent market impact ────────────────────────────

def test_amihud_permanent_impact_scales_with_illiquidity():
    # Same √-law-off setup; only the Amihud permanent leg fires. perm% = coef·illiq·alloc·100.
    illiq = 1e-9          # return per rupee
    e = _entry_liq("X", 5.0, adv=1e9, atr_pct=2.0)
    e["amihud"] = illiq
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, {0: [e]}, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      amihud_coef=1.0)
    alloc = 200_000.0     # 1,000,000 / 5
    expected = 1.0 * illiq * alloc * 100.0
    assert trades[0]["impact_pct"] == pytest.approx(expected, rel=1e-6)
    assert trades[0]["return_pct"] == pytest.approx(5.0 - expected, abs=1e-4)


def test_amihud_and_sqrt_impact_compose():
    # Both legs active → impact is the sum of the √-law temporary + Amihud permanent.
    illiq = 2e-9
    e = _entry_liq("X", 5.0, adv=1_000_000, atr_pct=2.0)
    e["amihud"] = illiq
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, {0: [e]}, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      impact_coef=0.5, amihud_coef=1.0)
    alloc = 200_000.0
    temp = 2.0 * 0.5 * 2.0 * (alloc / 1_000_000) ** 0.5
    perm = 1.0 * illiq * alloc * 100.0
    assert trades[0]["impact_pct"] == pytest.approx(temp + perm, abs=1e-3)  # stored at 4dp


# ── G5: HMM regime detection + soft throttle ──────────────────────────────────────

def test_hmm_tracks_regime_switch_causally():
    rng = np.random.default_rng(0)
    bull1 = rng.normal(0.001, 0.008, 250)     # calm bull
    bear = rng.normal(-0.0015, 0.025, 150)    # volatile bear
    bull2 = rng.normal(0.001, 0.008, 150)
    p, params = be.gaussian_hmm_regime(np.concatenate([bull1, bear, bull2]))
    assert params["sd"][params["bull_state"]] < params["sd"][1 - params["bull_state"]]  # bull = low-vol
    assert p[50:250].mean() > 0.8           # high P(bull) in the bull regime
    assert p[250:400].mean() < 0.3          # de-grossed in the bear regime
    assert p[430:].mean() > 0.8             # recovers after the switch


def test_hmm_short_series_returns_none():
    assert be.gaussian_hmm_regime(np.random.default_rng(1).normal(size=40)) is None


def test_regime_soft_throttle_scales_allocation():
    entries = {0: [_entry("A", 5.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      regime_scale_by_date={"2023-01-01": 0.3})
    assert trades[0]["capital_allocated"] == pytest.approx(60_000.0, rel=1e-6)  # 200k × 0.3


# ── G10: fractional-Kelly sizing ──────────────────────────────────────────────────

def test_kelly_caps_size_below_equal_weight_on_weak_edge():
    # One trade per day closes sequentially, building a weak-edge Kelly window
    # (W=0.52, R=1 → f*≈0.04); a later PROBE entry must be Kelly-capped far below the
    # 20% equal-weight allocation.
    dates = [f"d{i}" for i in range(36)]
    pattern = [1.0] * 13 + [-1.0] * 12          # 25 closed trades, W=0.52, R=1
    entries = {i: [_entry(f"T{i}", r, exit_idx=i + 1)] for i, r in enumerate(pattern)}
    entries[30] = [_entry("PROBE", 3.0, exit_idx=31)]
    _, trades = be.simulate_portfolio(dates, 0, 31, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      kelly_fraction=0.5)
    probe_trade = next(t for t in trades if t["ticker"] == "PROBE")
    assert probe_trade["capital_allocated"] < 100_000.0   # Kelly de-risked below equal-weight


def test_kelly_off_keeps_equal_weight():
    entries = {0: [_entry("A", 5.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5)
    assert trades[0]["capital_allocated"] == pytest.approx(200_000.0, rel=1e-6)


# ── G2: survivorship — delisting sweep + as-of membership resolution ───────────────

def test_delisting_force_closes_at_terminal_return():
    # A name whose natural exit is at idx 4 (+10%) is delisted at idx 2 with a −100%
    # wipe-out: it must exit at idx 2 with the terminal return, never the +10% it would
    # have "survived" to. Survivorship is not rewarded.
    entries = {0: [_entry("DEAD", 10.0, exit_idx=4)]}
    _, trades = be.simulate_portfolio(_dates(6), 0, 4, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      delist_by_ticker={"DEAD": (2, -100.0)})
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "delisted"
    assert t["return_pct"] == pytest.approx(-100.0, abs=1e-9)
    assert t["pnl"] == pytest.approx(-t["capital_allocated"], rel=1e-9)   # full loss of the stake


def test_delisting_after_natural_exit_is_noop():
    # Delist bar (idx 5) falls AFTER the natural exit (idx 2): the position already
    # realised its +8% normally, so the delisting must not fire.
    entries = {0: [_entry("LIVE", 8.0, exit_idx=2)]}
    _, trades = be.simulate_portfolio(_dates(8), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      delist_by_ticker={"LIVE": (5, -100.0)})
    assert len(trades) == 1
    assert trades[0]["exit_reason"] != "delisted"
    assert trades[0]["return_pct"] == pytest.approx(8.0, abs=1e-9)


def test_delisting_buyout_premium_is_realised():
    # Not every delisting is a wipe-out: an acquisition can close the position at a
    # premium. A +25% terminal return must be realised on the delist bar.
    entries = {0: [_entry("BOUGHT", 2.0, exit_idx=4)]}
    _, trades = be.simulate_portfolio(_dates(6), 0, 4, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      delist_by_ticker={"BOUGHT": (3, 25.0)})
    assert trades[0]["exit_reason"] == "delisted"
    assert trades[0]["return_pct"] == pytest.approx(25.0, abs=1e-9)


def test_attach_membership_as_of_resolution():
    # Membership intervals must gate each (ticker, date) bar point-in-time: a name is a
    # member only while a bar falls inside [effective_from, effective_to).
    import routers.analytics as an
    df = pd.DataFrame({
        "ticker": ["A", "A", "A", "B", "B", "B"],
        "date": pd.to_datetime(["2023-01-01", "2023-06-01", "2024-01-01",
                                "2023-01-01", "2023-06-01", "2024-01-01"]),
        "close": [100.0] * 6,
    })
    mem = pd.DataFrame({
        "ticker": ["A", "B"],
        "effective_from": pd.to_datetime(["2023-03-01", "2023-01-01"]),
        "effective_to": pd.to_datetime(["2099-12-31", "2023-09-01"]),
    })
    out = an._attach_membership(df.copy(), mem).sort_values(["ticker", "date"]).reset_index(drop=True)
    flags = {(r.ticker, str(r.date.date())): bool(r.index_member) for r in out.itertuples()}
    assert flags[("A", "2023-01-01")] is False     # before A joined
    assert flags[("A", "2023-06-01")] is True       # after A joined
    assert flags[("B", "2023-06-01")] is True        # B still a member
    assert flags[("B", "2024-01-01")] is False       # B already ejected
    assert out.attrs["membership_pit"] is True


def test_attach_membership_absent_table_is_full_universe():
    # No membership table ⇒ every bar is a member (survivorship-biased) and the PIT flag
    # is explicitly False so the UI can warn.
    import routers.analytics as an
    df = pd.DataFrame({"ticker": ["A", "B"], "date": pd.to_datetime(["2023-01-01", "2023-01-01"]),
                       "close": [100.0, 100.0]})
    out = an._attach_membership(df.copy(), None)
    assert bool(out["index_member"].all()) is True
    assert out.attrs["membership_pit"] is False


# ── C2: per-name temporary-leg impact coefficient (impact_coef_map) ───────────────

def test_impact_coef_map_overrides_scalar_per_name():
    # Two same-size entries into identical ADV; the map charges A a 2x coefficient and B 0.5x.
    # Temp impact = 2·coef·ATR%·√(alloc/ADV); ratio of impacts must equal the coef ratio.
    entries = {0: [_entry_liq("A", 5.0, adv=10_000_000, atr_pct=2.0),
                   _entry_liq("B", 5.0, adv=10_000_000, atr_pct=2.0)]}
    _, trades = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      impact_coef=1.0,
                                      impact_coef_map={"A": 2.0, "B": 0.5})
    by = {t["ticker"]: t["impact_pct"] for t in trades}
    assert by["A"] > by["B"] > 0
    assert by["A"] / by["B"] == pytest.approx(4.0, rel=1e-3)   # (2.0 / 0.5); impact_pct stored at 4dp


def test_impact_coef_map_falls_back_to_scalar_for_unmapped_name():
    # C charged via scalar (map has no entry); equals the no-map result exactly.
    entries = {0: [_entry_liq("C", 5.0, adv=10_000_000, atr_pct=2.0)]}
    _, mapped = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      impact_coef=1.0, impact_coef_map={"OTHER": 9.0})
    _, scalar = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                      starting_capital=1_000_000, max_positions=5,
                                      impact_coef=1.0)
    assert mapped[0]["impact_pct"] == pytest.approx(scalar[0]["impact_pct"], rel=1e-9)


def test_impact_coef_map_none_is_legacy_behaviour():
    # Explicit guarantee of zero regression: map=None reproduces the scalar-only path.
    entries = {0: [_entry_liq("X", 5.0, adv=1_000_000, atr_pct=2.0)]}
    _, t = be.simulate_portfolio(_dates(5), 0, 2, entries, _flat_price,
                                 starting_capital=1_000_000, max_positions=5,
                                 impact_coef=1.0, impact_coef_map=None)
    expected = 2.0 * 1.0 * 2.0 * (200_000 / 1_000_000) ** 0.5
    assert t[0]["impact_pct"] == pytest.approx(expected, abs=1e-4)   # impact_pct stored at 4dp


# ── C1/C2/C3: at-scale auto-impact calibration (the completed cost stack) ──────────

def _adv_frame(advs: dict, illiqs: dict | None = None, n_days: int = 5) -> pd.DataFrame:
    """Build a minimal prepared frame with adv20 (+ optional amihud_illiq) per ticker."""
    rows = []
    dates = pd.to_datetime([f"2024-01-0{d+1}" for d in range(n_days)])
    for tkr, adv in advs.items():
        for d in dates:
            row = {"ticker": tkr, "date": d, "adv20": float(adv)}
            if illiqs is not None:
                row["amihud_illiq"] = float(illiqs.get(tkr, np.nan))
            rows.append(row)
    return pd.DataFrame(rows)


class _Req:
    """Minimal duck-typed BacktestRequest for the calibration unit."""
    def __init__(self, starting_capital, max_positions=5, impact_coef=None):
        self.starting_capital = starting_capital
        self.max_positions = max_positions
        self.impact_coef = impact_coef


def test_calibrate_auto_impact_off_at_retail_scale():
    # ₹1L / 5 pos = ₹20k per position into a ₹1Cr ADV name ⇒ 0.0002 << 0.005 trigger ⇒ None.
    import routers.analytics as an
    df = _adv_frame({"A": 1e7}, {"A": 1e-9})
    assert an._calibrate_auto_impact(df, _Req(starting_capital=1e5)) is None


def test_calibrate_auto_impact_on_at_scale_enables_all_three_legs():
    # ₹100Cr / 5 pos = ₹20Cr per position into a ₹18Cr median ADV ⇒ >>0.005 ⇒ full stack on.
    import routers.analytics as an
    df = _adv_frame({"A": 1.8e8, "B": 6e7}, {"A": 1e-9, "B": 4e-9})
    cal = an._calibrate_auto_impact(df, _Req(starting_capital=1e9))
    assert cal is not None
    assert cal["auto_impact"] == 1.0                       # temp leg
    assert cal["auto_amihud"] is not None and cal["auto_amihud"] > 0    # C1 permanent leg
    assert cal["auto_participation"] == 10.0               # C3 ADV cap
    assert cal["impact_coef_map"] is not None              # C2 per-name temp coef


def test_calibrate_per_name_coef_higher_for_illiquid():
    # B is the more illiquid name (higher Amihud) ⇒ its temporary coefficient must exceed A's.
    import routers.analytics as an
    df = _adv_frame({"A": 1.8e8, "B": 6e7}, {"A": 1e-9, "B": 9e-9})
    cal = an._calibrate_auto_impact(df, _Req(starting_capital=1e9))
    cmap = cal["impact_coef_map"]
    assert cmap["B"] > cmap["A"]                           # microcap charged a stiffer √-law
    assert all(an._YI_FLOOR <= v <= an._YI_CEIL for v in cmap.values())   # bounded band


def test_calibrate_explicit_impact_coef_disables_auto():
    # A caller-supplied impact_coef must win — auto-calibration returns None (no override).
    import routers.analytics as an
    df = _adv_frame({"A": 1.8e8}, {"A": 1e-9})
    assert an._calibrate_auto_impact(df, _Req(starting_capital=1e9, impact_coef=1.5)) is None


def test_calibrate_degenerate_adv_returns_none_not_raises():
    # All-NaN / zero ADV ⇒ no valid liquidity baseline ⇒ graceful None (never raises).
    import routers.analytics as an
    df = _adv_frame({"A": 0.0, "B": np.nan})
    assert an._calibrate_auto_impact(df, _Req(starting_capital=1e9)) is None


def test_calibrate_missing_amihud_column_still_enables_caps():
    # Frame without amihud_illiq ⇒ no per-name map, but the ADV cap + scalar temp leg still fire.
    import routers.analytics as an
    df = _adv_frame({"A": 1.8e8, "B": 6e7}, illiqs=None)
    cal = an._calibrate_auto_impact(df, _Req(starting_capital=1e9))
    assert cal is not None
    assert cal["impact_coef_map"] is None
    assert cal["auto_participation"] == 10.0


# ── D1: survivorship-premium haircut banner ───────────────────────────────────────

class _Ctx:
    """Minimal duck-typed _SimContext for the survivorship-warning unit."""
    def __init__(self, membership_pit=False, delist_by_ticker=None):
        self.membership_pit = membership_pit
        self.delist_by_ticker = delist_by_ticker


def test_survivorship_warning_active_when_bias_live():
    # No PIT membership + no delistings applied ⇒ bias is live ⇒ structured haircut banner.
    import routers.analytics as an
    w = an._survivorship_warning(_Ctx(membership_pit=False, delist_by_ticker=None))
    assert w is not None and w["active"] is True
    band = w["cagr_haircut_pct_per_year"]
    # BGIR 1–4%/yr band, monotone low ≤ central ≤ high.
    assert band["low"] == 1.0 and band["high"] == 4.0
    assert band["low"] <= band["central_low"] <= band["central_high"] <= band["high"]


def test_survivorship_warning_cleared_when_membership_pit():
    # Point-in-time membership (tables backfilled) ⇒ bias mitigated ⇒ no banner.
    import routers.analytics as an
    assert an._survivorship_warning(_Ctx(membership_pit=True, delist_by_ticker=None)) is None


def test_survivorship_warning_cleared_when_delistings_applied():
    # Delisting returns actually applied ⇒ survivorship adjusted ⇒ no banner.
    import routers.analytics as an
    assert an._survivorship_warning(_Ctx(membership_pit=False,
                                         delist_by_ticker={"X": (3, -90.0)})) is None


# ── C7a (revised, §3.4) — true volatility-adaptive ATR stop; -2% is now a FLOOR ───

def test_effective_stop_atr_scaled_no_floor_default():
    # Default (no stop_floor_pct): the stop is exactly k·ATR%. Calm name ATR 0.5%,
    # k=2 -> 1.0% stop. No floor binds; the stop is purely volatility-driven.
    s = be.effective_stop_pct(atr_pct=0.5, atr_stop_mult=2.0, fixed_stop_pct=2.0)
    assert s == pytest.approx(1.0)


def test_effective_stop_widens_in_storm_not_clamped():
    # APPROVED REVISION: storm name ATR 3.24% (universe median), k=2 -> 6.48% — the
    # stop now WIDENS to k·ATR% instead of being clamped to the old -2% cap, so
    # volatility no longer knocks the trade out on noise (audit §3.4).
    s = be.effective_stop_pct(atr_pct=3.24, atr_stop_mult=2.0, fixed_stop_pct=2.0)
    assert s == pytest.approx(6.48)
    # A very-high-vol name gets an even wider stop — no upper clamp at all.
    assert be.effective_stop_pct(atr_pct=10.0, atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0) == pytest.approx(20.0)


def test_effective_stop_floor_is_minimum_width_not_cap():
    # When stop_floor_pct IS set, it acts as a *minimum* width (floor on protection):
    # an ultra-calm name (ATR 0.5%, k·ATR=1.0%) is widened up to the 2% floor, while a
    # storm name (ATR 3.24%, k·ATR=6.48%) is left WIDE — the floor never caps it.
    assert be.effective_stop_pct(atr_pct=0.5, atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0, stop_floor_pct=2.0) == pytest.approx(2.0)
    assert be.effective_stop_pct(atr_pct=3.24, atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0, stop_floor_pct=2.0) == pytest.approx(6.48)


def test_effective_stop_scales_linearly_with_atr_when_unfloored():
    # Property: with no floor, the stop is strictly monotone increasing in ATR (k·ATR).
    prev = -1.0
    for atr in [0.1, 0.5, 1.0, 2.0, 3.24, 6.0, 12.0]:
        s = be.effective_stop_pct(atr_pct=atr, atr_stop_mult=2.0, fixed_stop_pct=2.0)
        assert s is not None and s == pytest.approx(2.0 * atr)
        assert s > prev
        prev = s


def test_effective_stop_legacy_floor_pct_alias_now_acts_as_floor():
    # Back-compat: the deprecated `floor_pct` kwarg still maps to stop_floor_pct, but
    # now carries the NEW floor (min-width) semantics — a storm name is NOT clamped.
    s = be.effective_stop_pct(atr_pct=3.24, atr_stop_mult=2.0,
                              fixed_stop_pct=2.0, floor_pct=2.0)
    assert s == pytest.approx(6.48)


def test_effective_stop_falls_back_to_fixed_when_atr_missing():
    # No ATR data for the name -> fall back to the legacy fixed-% stop exactly.
    assert be.effective_stop_pct(atr_pct=None, atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0) == pytest.approx(2.0)
    assert be.effective_stop_pct(atr_pct=0.0, atr_stop_mult=2.0,
                                 fixed_stop_pct=1.5) == pytest.approx(1.5)
    # NaN / negative ATR are degenerate -> fixed fallback, never a crash.
    assert be.effective_stop_pct(atr_pct=float("nan"), atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0) == pytest.approx(2.0)
    assert be.effective_stop_pct(atr_pct=-1.0, atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0) == pytest.approx(2.0)


def test_effective_stop_opt_out_to_pure_fixed():
    # atr_stop_mult=None (opt-out) -> pure fixed-% stop, ATR ignored entirely.
    assert be.effective_stop_pct(atr_pct=0.5, atr_stop_mult=None,
                                 fixed_stop_pct=2.0) == pytest.approx(2.0)


def test_effective_stop_none_when_no_stop_configured():
    # No ATR mult and no fixed stop -> None (time-stop only), identical to pre-C7a.
    assert be.effective_stop_pct(atr_pct=3.0, atr_stop_mult=None,
                                 fixed_stop_pct=None) is None
    assert be.effective_stop_pct(atr_pct=None, atr_stop_mult=None,
                                 fixed_stop_pct=None) is None


def test_effective_stop_no_floor_allows_wide_atr():
    # When stop_floor_pct is explicitly None (the default), the ATR stop is the pure
    # k·ATR% distance — the storm name keeps its wide 6.48% stop (audit §3.4 intent).
    s = be.effective_stop_pct(atr_pct=3.24, atr_stop_mult=2.0,
                              fixed_stop_pct=2.0, stop_floor_pct=None)
    assert s == pytest.approx(6.48)


def test_effective_stop_handles_garbage_inputs_without_raising():
    # Non-numeric inputs must degrade, never raise (zero-regression boundary).
    assert be.effective_stop_pct(atr_pct="x", atr_stop_mult=2.0,
                                 fixed_stop_pct=2.0) == pytest.approx(2.0)
    assert be.effective_stop_pct(atr_pct=1.0, atr_stop_mult="x",
                                 fixed_stop_pct=2.0) == pytest.approx(2.0)


# ── C7b — daily realised-loss VaR governor (mirrors the live 2% kill-switch) ──────

def test_daily_loss_governor_unit_math():
    # ℓ=2%: a -2.5% day vs day-open NAV trips; a -1.5% day does not.
    g = be.DailyLossGovernor(2.0)
    g.open_day(1000.0)
    assert g.is_halted(975.0) is True       # -2.5% ⇒ halt
    g2 = be.DailyLossGovernor(2.0)
    g2.open_day(1000.0)
    assert g2.is_halted(985.0) is False      # -1.5% ⇒ no halt
    # Exactly at the limit (-2.0%) trips (≤ boundary, matching live kill-switch ≤).
    g3 = be.DailyLossGovernor(2.0)
    g3.open_day(1000.0)
    assert g3.is_halted(980.0) is True


def test_daily_loss_governor_inert_when_none():
    # None ⇒ governor never halts (legacy behaviour exactly).
    g = be.DailyLossGovernor(None)
    g.open_day(1000.0)
    assert g.is_halted(500.0) is False       # even a -50% day is not halted when off
    assert g.days_halted == 0


def test_daily_loss_governor_degenerate_nav_safe():
    # Degenerate day-open / current NAV must never raise and never spuriously halt.
    g = be.DailyLossGovernor(2.0)
    g.open_day(0.0)                          # zero day-open ⇒ undefined ⇒ no halt
    assert g.is_halted(900.0) is False
    g.open_day(float("nan"))
    assert g.is_halted(900.0) is False
    g.open_day(1000.0)
    assert g.is_halted(float("nan")) is False
    assert g.is_halted("garbage") is False   # type: ignore[arg-type]


def test_daily_loss_governor_counts_halt_days():
    g = be.DailyLossGovernor(2.0)
    for _ in range(3):
        g.open_day(1000.0)
        g.is_halted(960.0)                   # -4% each day
    assert g.days_halted == 3


def test_daily_var_halt_blocks_new_entries_end_to_end():
    # Bar 1: T1 (held from bar 0) marks down hard so the bar-1 MTM NAV is -3% vs the
    # bar-0 close. A 2% daily governor must block the bar-1 T2 entry; without it, taken.
    all_dates = [f"2024-01-0{i+1}" for i in range(4)]

    # T1 opens bar 0 at 100; on bar 1 it trades at 70 (a -3%-of-NAV intraday hole given
    # full deployment), then recovers. price_at drives the MTM.
    px = {(0, "T1"): 100.0, (1, "T1"): 70.0, (2, "T1"): 100.0, (3, "T1"): 100.0}

    def price_at(idx, ticker):
        return px.get((idx, ticker), 100.0)

    entries = {
        0: [{"ticker": "T1", "entry_price": 100.0, "exit_idx": 2, "net_return_pct": 0.0,
             "gross_return_pct": 0.0, "exit_price": 100.0, "exit_reason": "time_stop",
             "holding_days": 2, "win_threshold": 0.0,
             "entry_date": all_dates[0], "exit_date": all_dates[2]}],
        1: [{"ticker": "T2", "entry_price": 100.0, "exit_idx": 3, "net_return_pct": 5.0,
             "gross_return_pct": 5.0, "exit_price": 105.0, "exit_reason": "time_stop",
             "holding_days": 2, "win_threshold": 0.0,
             "entry_date": all_dates[1], "exit_date": all_dates[3]}],
    }
    # With the 2% daily governor: full capital into T1 at bar 0 (NAV~1000 at bar-0
    # close), then bar-1 MTM = 700 ⇒ -30% vs day-open ⇒ T2 blocked.
    _, halted = be.simulate_portfolio(all_dates, 0, 3, entries, price_at,
                                      starting_capital=1000.0, max_positions=1,
                                      daily_loss_halt_pct=2.0)
    _, open_ = be.simulate_portfolio(all_dates, 0, 3, entries, price_at,
                                     starting_capital=1000.0, max_positions=1)
    # max_positions=1 means T2 can only be taken after T1 exits (bar 2); the governor
    # is irrelevant to that race, so use a 2-slot book to isolate the halt effect.
    entries2 = {
        0: [dict(entries[0][0])],
        1: [dict(entries[1][0])],
    }
    _, h2 = be.simulate_portfolio(all_dates, 0, 3, entries2, price_at,
                                  starting_capital=1000.0, max_positions=2,
                                  daily_loss_halt_pct=2.0)
    _, o2 = be.simulate_portfolio(all_dates, 0, 3, entries2, price_at,
                                  starting_capital=1000.0, max_positions=2)
    assert len(h2) == 1   # T2 blocked on the -30% bar by the daily governor
    assert len(o2) == 2   # T2 taken when the governor is off


def test_daily_var_halt_default_reduces_or_matches_drawdown_vs_off():
    # Property: with the governor ON (default), a portfolio cannot enter on a
    # breached day, so its trade count is ≤ the governor-off count on the same path.
    all_dates = [f"2024-01-0{i+1}" for i in range(5)]
    px = {(0, "A"): 100.0, (1, "A"): 60.0, (2, "A"): 100.0, (3, "A"): 100.0, (4, "A"): 100.0}

    def price_at(idx, ticker):
        return px.get((idx, ticker), 100.0)

    e = {
        0: [{"ticker": "A", "entry_price": 100.0, "exit_idx": 2, "net_return_pct": 0.0,
             "gross_return_pct": 0.0, "exit_price": 100.0, "exit_reason": "time_stop",
             "holding_days": 2, "win_threshold": 0.0,
             "entry_date": all_dates[0], "exit_date": all_dates[2]}],
        1: [{"ticker": "B", "entry_price": 100.0, "exit_idx": 3, "net_return_pct": 1.0,
             "gross_return_pct": 1.0, "exit_price": 101.0, "exit_reason": "time_stop",
             "holding_days": 2, "win_threshold": 0.0,
             "entry_date": all_dates[1], "exit_date": all_dates[3]}],
    }
    _, on = be.simulate_portfolio(all_dates, 0, 4, {0: [dict(e[0][0])], 1: [dict(e[1][0])]},
                                  price_at, starting_capital=1000.0, max_positions=2,
                                  daily_loss_halt_pct=2.0)
    _, off = be.simulate_portfolio(all_dates, 0, 4, {0: [dict(e[0][0])], 1: [dict(e[1][0])]},
                                   price_at, starting_capital=1000.0, max_positions=2)
    assert len(on) <= len(off)
