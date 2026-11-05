"""risk_math (W5): the RSK dashboard's math pinned by hand.

Every expectation below is computed on paper first — the suite fails if the VaR
order-statistic convention, the beta estimator, the Euler decomposition, the stress
window compounding or the ladder distances drift.
"""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import risk_math as rm  # noqa: E402


def _dates(start: str, n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


# ── VaR / ES on a known synthetic series ───────────────────────────────────────────

def test_var_es_hand_computed_percentiles():
    """100 returns, worst five = −10, −8, −6, −5, −4 %. k=ceil(0.05·100)=5 → VaR95 is
    the 5th worst (4%); ES95 = mean of the five = 6.6%. k=ceil(0.01·100)=1 → VaR99=ES99=10%."""
    tail = [-0.10, -0.08, -0.06, -0.05, -0.04]
    body = [0.001 * ((i % 21) - 10) for i in range(95)]        # 95 values within ±1%
    r = tail + body
    var95, es95 = rm.hist_var_es(r, 0.95)
    var99, es99 = rm.hist_var_es(r, 0.99)
    assert var95 == pytest.approx(0.04)
    assert es95 == pytest.approx(0.066)
    assert var99 == pytest.approx(0.10)
    assert es99 == pytest.approx(0.10)
    # magnitude ordering: deeper confidence ⇒ bigger loss; ES ≥ VaR at the same level
    assert var95 < var99
    assert es95 >= var95 and es99 >= var99


def test_var_small_sample_clamps_k_to_worst():
    var, es = rm.hist_var_es([-0.03, 0.01, 0.02], 0.95)        # k = ceil(0.15)=1
    assert var == pytest.approx(0.03) and es == pytest.approx(0.03)


def test_var_empty_sample_is_none():
    assert rm.hist_var_es([], 0.95) == (None, None)


def test_sqrt_horizon_scaling_is_sqrt5():
    assert rm.sqrt_horizon(0.02, 5) == pytest.approx(0.02 * np.sqrt(5))
    assert rm.sqrt_horizon(None, 5) is None


# ── Beta ───────────────────────────────────────────────────────────────────────────

def test_beta_of_y_equals_2x_is_exactly_2():
    idx = _dates("2024-01-01", 120)
    rng = np.random.default_rng(7)
    x = pd.Series(rng.normal(0, 0.01, len(idx)), index=idx)
    assert rm.beta(2.0 * x, x) == pytest.approx(2.0, rel=1e-12)


def test_beta_requires_min_overlap_and_market_variance():
    idx = _dates("2024-01-01", 30)
    x = pd.Series(np.linspace(-0.01, 0.01, 30), index=idx)
    assert rm.beta(x, x, min_obs=60) is None                   # 30 < 60 overlap
    flat = pd.Series(0.0, index=_dates("2024-01-01", 120))
    assert rm.beta(flat, flat) is None                         # var(market)=0


# ── Risk contributions (Euler) ─────────────────────────────────────────────────────

def test_risk_contributions_sum_to_portfolio_stdev():
    idx = _dates("2023-01-02", 300)
    rng = np.random.default_rng(42)
    panel = pd.DataFrame({s: rng.normal(0, v, len(idx)) for s, v in
                          [("AAA", 0.01), ("BBB", 0.02), ("CCC", 0.015)]}, index=idx)
    weights = {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2}
    sigma_p, contrib = rm.risk_contributions(panel, weights)
    rp = rm.portfolio_returns(panel, weights)
    assert sigma_p == pytest.approx(float(rp.std(ddof=1)), rel=1e-12)
    assert sum(contrib.values()) == pytest.approx(sigma_p, rel=1e-9)
    assert set(contrib) == {"AAA", "BBB", "CCC"}


# ── Stress window compounding ──────────────────────────────────────────────────────

def test_window_return_compounds_actual_sessions():
    """Sessions inside (2020-02-20, 2020-03-23]: −5%, −10%, −20% →
    0.95·0.90·0.80 − 1 = −31.6%."""
    r = pd.Series(
        [0.01, -0.05, -0.10, -0.20],
        index=pd.to_datetime(["2020-02-19", "2020-02-21", "2020-02-24", "2020-03-23"]),
    )
    out = rm.window_return(r, date(2020, 2, 20), date(2020, 3, 23))
    assert out == pytest.approx(0.95 * 0.90 * 0.80 - 1.0)      # −0.316


def test_window_return_excludes_late_listings_and_missing_sessions():
    late = pd.Series([0.1], index=pd.to_datetime(["2020-03-02"]))   # first ret > start+5d
    assert rm.window_return(late, date(2020, 2, 20), date(2020, 3, 23)) is None
    # single-day window (election 2024-06-04): no session that day → None
    r = pd.Series([0.01, 0.02], index=pd.to_datetime(["2024-06-03", "2024-06-05"]))
    assert rm.window_return(r, date(2024, 6, 3), date(2024, 6, 4)) is None
    hit = pd.Series([0.01, -0.0579], index=pd.to_datetime(["2024-06-03", "2024-06-04"]))
    assert rm.window_return(hit, date(2024, 6, 3), date(2024, 6, 4)) == pytest.approx(-0.0579)


def test_stress_scenario_pnl_coverage_and_worst_holding():
    idx = pd.to_datetime(["2020-02-19", "2020-02-21", "2020-02-24", "2020-03-23"])
    rets = {
        "CRASHY": pd.Series([0.01, -0.05, -0.10, -0.20], index=idx),   # window −31.6%
        "MILD": pd.Series([0.0, -0.10, 0.0, 0.0], index=idx),          # window −10%
        "NEWKID": pd.Series([0.2], index=pd.to_datetime(["2020-03-02"])),  # excluded
    }
    values = {"CRASHY": 60_000.0, "MILD": 40_000.0, "NEWKID": 40_000.0}
    out = rm.stress_scenario(rets, values, date(2020, 2, 20), date(2020, 3, 23))
    expected_pnl = 60_000 * (0.95 * 0.90 * 0.80 - 1.0) + 40_000 * (-0.10)
    assert out["pnl_inr"] == pytest.approx(expected_pnl)               # ≈ −22,960
    assert out["portfolio_pct"] == pytest.approx(expected_pnl / 100_000 * 100)
    assert out["covered_value_pct"] == pytest.approx(100_000 / 140_000 * 100)
    assert out["worst"]["symbol"] == "CRASHY"
    assert [e["symbol"] for e in out["excluded"]] == ["NEWKID"]


# ── Panel alignment policy ─────────────────────────────────────────────────────────

def test_build_panel_zero_fills_gaps_and_excludes_thin_histories():
    full = pd.Series(0.01, index=_dates("2024-01-01", 100))
    gappy = full.drop(full.index[10:20])                       # 10 missing sessions
    thin = pd.Series(0.01, index=_dates("2024-05-01", 5))
    panel, excluded = rm.build_panel({"FULL": full, "GAPPY": gappy, "THIN": thin},
                                     lookback=750, min_obs=60)
    assert "THIN" in excluded and "need ≥ 60" in excluded["THIN"]
    assert list(panel.columns) == ["FULL", "GAPPY"]
    assert (panel.loc[full.index[10:20], "GAPPY"] == 0.0).all()    # carried price = 0 return
    assert len(panel) == 100


def test_portfolio_returns_renormalizes_weights_over_panel_columns():
    idx = _dates("2024-01-01", 80)
    r = pd.Series(np.linspace(-0.01, 0.01, 80), index=idx)
    panel = pd.DataFrame({"A": r, "B": r})
    rp = rm.portfolio_returns(panel, {"A": 2.0, "B": 1.0, "GHOST": 5.0})
    assert np.allclose(rp.values, r.values)                    # GHOST ignored, A+B renormalized


# ── Sector concentration & ladder ──────────────────────────────────────────────────

def test_sector_concentration_breaches_on_count_share():
    holdings = [
        {"symbol": "A", "value": 10_000, "sector": "Capital Markets"},
        {"symbol": "B", "value": 10_000, "sector": "Capital Markets"},
        {"symbol": "C", "value": 10_000, "sector": "Capital Markets"},
        {"symbol": "D", "value": 35_000, "sector": "Pharma"},
        {"symbol": "E", "value": 35_000, "sector": "Auto"},
    ]
    rows = rm.sector_concentration(holdings, cap_pct=40.0)
    cm = next(r for r in rows if r["sector"] == "Capital Markets")
    assert cm["positions"] == 3 and cm["count_pct"] == pytest.approx(60.0) and cm["breach"]
    assert sum(r["value_pct"] for r in rows) == pytest.approx(100.0)
    assert not next(r for r in rows if r["sector"] == "Pharma")["breach"]


def test_drawdown_ladder_distances():
    """navs 100→110→99: peak 110, dd −10%, stop at 88, a further 11.11% fall to reach it;
    today −10% is through the −2% halt → room 0."""
    out = rm.drawdown_ladder([100.0, 110.0, 99.0])
    assert out["peak"] == pytest.approx(110.0)
    assert out["drawdown_pct"] == pytest.approx(-10.0)
    assert out["stop_nav"] == pytest.approx(88.0)
    assert out["further_fall_to_stop_pct"] == pytest.approx((99 - 88) / 99 * 100)
    assert out["today_return_pct"] == pytest.approx(-10.0)
    assert out["room_before_halt_pct"] == 0.0


def test_drawdown_ladder_calm_book_and_empty_series():
    out = rm.drawdown_ladder([100.0, 101.0])
    assert out["drawdown_pct"] == pytest.approx(0.0)
    assert out["today_return_pct"] == pytest.approx(1.0)
    assert out["room_before_halt_pct"] == pytest.approx(3.0)   # +1% − (−2%)
    empty = rm.drawdown_ladder([])
    assert empty["nav"] is None and empty["drawdown_pct"] is None


# ── Histogram & severity chips ─────────────────────────────────────────────────────

def test_histogram_counts_cover_every_observation():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 500)
    h = rm.histogram(r, bins=31)
    assert len(h) == 31 and sum(b["n"] for b in h) == 500
    assert rm.histogram([]) == []


def test_severity_thresholds():
    assert rm.severity_var(None) == "na"
    assert rm.severity_var(0.9) == "ok" and rm.severity_var(1.0) == "warn" and rm.severity_var(2.0) == "crit"
    assert rm.severity_beta(1.0) == "ok" and rm.severity_beta(1.3) == "warn" and rm.severity_beta(1.6) == "crit"
    assert rm.severity_sector(20.0) == "ok" and rm.severity_sector(33.0) == "warn" and rm.severity_sector(41.0) == "crit"
    assert rm.severity_dd(-5.0) == "ok" and rm.severity_dd(-12.0) == "warn" and rm.severity_dd(-16.0) == "crit"
    assert rm.severity_dd(-1.0, stopped=True) == "crit"        # emergency stop engaged
