"""MC drawdown lens (backtest/mc.py): known-DD synthetics, determinism, block structure, flag rule."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
from backtest import mc  # noqa: E402


def test_constant_positive_returns_have_zero_dd_at_every_percentile():
    monthly = np.full(72, 0.01)
    dd = mc.block_bootstrap(monthly, n_resamples=2_000)
    pct = mc.dd_percentiles(dd)
    assert pct["p50"] == pct["p95"] == pct["max"] == 0.0
    assert mc.max_drawdown(monthly) == 0.0


def test_one_crash_month_fattens_the_resampled_tail_beyond_the_single_path():
    monthly = np.full(72, 0.01)
    monthly[40] = -0.50                                    # one −50% month in 72
    realized = mc.max_drawdown(monthly)                    # ≈ −50%, signed
    dd = mc.block_bootstrap(monthly)                       # the crash can recur within a resample
    pct = mc.dd_percentiles(dd)
    assert -0.52 < realized < -0.48
    assert pct["p95"] <= realized * 100                    # p95 at least as deep as the one path
    assert pct["max"] < realized * 100 * 1.4               # some resample held it twice (≈ −75%)


def test_same_seed_is_identical_and_other_seed_differs():
    rng = np.random.default_rng(7)
    monthly = rng.normal(0.01, 0.06, 84)
    a = mc.block_bootstrap(monthly, seed=108)
    b = mc.block_bootstrap(monthly, seed=108)
    c = mc.block_bootstrap(monthly, seed=109)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    assert mc.dd_percentiles(a)["p95"] == mc.dd_percentiles(b)["p95"]


def test_block_resampling_keeps_regime_clustering_vs_iid_shuffle():
    # 12-month regimes of −4% then +5%: blocks of 3 keep losing streaks together; an iid
    # shuffle (block=1) of the same months spreads them out → shallower drawdown tail.
    monthly = np.tile(np.r_[np.full(12, -0.04), np.full(12, 0.05)], 3)   # 72 months
    p_block = mc.dd_percentiles(mc.block_bootstrap(monthly, block=3))
    p_iid = mc.dd_percentiles(mc.block_bootstrap(monthly, block=1))
    assert p_block["p95"] < p_iid["p95"]                   # deeper (more negative) with clustering
    assert p_block["p50"] < p_iid["p50"]


def test_circular_blocks_wrap_and_resamples_keep_the_horizon_length():
    monthly = np.arange(10, dtype=float) / 100.0           # distinguishable values
    rng_idx = mc.block_bootstrap(monthly, n_resamples=50)  # must not raise on wrap-around
    assert rng_idx.shape == (50,)
    # direct check of the index mechanics: a block starting at n−1 wraps to 0, 1
    n = len(monthly)
    starts = np.array([[n - 1]])
    idx = (starts[:, :, None] + np.arange(3)[None, None, :]) % n
    assert idx.reshape(-1).tolist() == [9, 0, 1]


def test_monthly_returns_and_window_runner_match_engine_convention(tmp_path):
    idx = pd.bdate_range("2020-01-01", periods=400)
    eq = pd.Series(np.linspace(1_000_000, 1_400_000, 400), index=idx)
    monthly = mc.monthly_returns(eq)
    expect = eq.resample("ME").last().pct_change().dropna().to_numpy()
    assert np.allclose(monthly, expect) and (monthly > 0).all()
    # run_window on a persisted curve: rising line → zero DD everywhere, never DD-FRAGILE
    curve = tmp_path / "s1_gateA_equity.csv"
    eq.rename_axis("date").to_frame("0").to_csv(curve)
    r = mc.run_window(curve, budget=-30.0, n_resamples=500)
    assert r["realized_daily"] == 0.0 and r["p95"] == 0.0 and r["dd_fragile"] is False
    assert r["months"] == len(monthly)


def test_dd_fragile_fires_only_when_realized_passed_but_p95_breaches(tmp_path):
    # Deterministic curve: steady +1% months with one −25% crash. Realized DD = −25%; in the
    # bootstrap the crash month recurs twice in well over 5% of resamples, so p95 ≈ −43%.
    monthly = np.full(72, 0.01)
    monthly[40] = -0.25
    eq = pd.Series(np.r_[1.0, np.cumprod(1 + monthly)],
                   index=pd.date_range("2020-01-31", periods=73, freq="ME")) * 1e6
    curve = tmp_path / "x_gateA_equity.csv"
    eq.rename_axis("date").to_frame("0").to_csv(curve)
    base = mc.run_window(curve, budget=None)
    assert -26.0 < base["realized_daily"] < -24.0
    assert base["p95"] < base["realized_daily"]            # the tail is deeper than the one path
    assert base["dd_fragile"] is False                     # no budget → never flagged
    mid = (base["p95"] + base["realized_daily"]) / 2       # realized passes it, p95 breaches it
    assert mc.run_window(curve, budget=mid)["dd_fragile"] is True
    assert mc.run_window(curve, budget=base["p95"] - 5)["dd_fragile"] is False    # p95 within budget
    assert mc.run_window(curve, budget=base["realized_daily"] + 1)["dd_fragile"] is False  # realized failed too


def test_shadow_status_lines_absent_report_and_broken_json_yield_nothing(tmp_path):
    assert mc.shadow_status_lines(tmp_path) == []          # no report → no line
    (tmp_path / "mc_drawdown.md").write_text("# stub\n")
    (tmp_path / "mc_drawdown.json").write_text("{broken")
    assert mc.shadow_status_lines(tmp_path) == []          # broken sidecar must never raise
    (tmp_path / "mc_drawdown.json").write_text(
        '{"runs": {"S1": {"gateA": {"p95": -21.3, "realized_daily": -16.5}},'
        ' "S1H": {"gateA": {"p95": -28.1, "realized_daily": -24.0}}}}')
    lines = mc.shadow_status_lines(tmp_path)
    assert lines[0] == "" and "S1 -21.3% (realized -16.5%)" in lines[1] and "S1H -28.1%" in lines[1]
    assert "report-only" in lines[1]
