"""ALFA honesty (5 Nov review M19, m090, m091): the gap engine's net figures are after the real ICICI delivery round trip
from shared/trading_costs.py (≈ 0.93 % at ₹1,00,000, never a flat 0.15 %), carry n and a 95 % interval for the window
AND the whole loaded history, and the strategy no longer borrows alpha_lab's "S3" name. Negative controls included."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.trading_costs import default_model  # noqa: E402

import routers.alpha as alpha  # noqa: E402


def _panel(n_tickers: int = 6, n_days: int = 300) -> pd.DataFrame:
    """A deterministic panel where every ticker gaps up 6 % and holds on a few days (Leg B fires), then drifts."""
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    rows = []
    for t in range(n_tickers):
        close = 100.0 + t
        for i, d in enumerate(dates):
            gap = 0.06 if (i % 37 == 5 + t) else 0.0
            o = close * (1 + gap)
            c = o * (1.002 if gap else 1.0 + 0.001 * np.sin(i + t))
            h, lo = max(o, c) * 1.005, min(o, c) * 0.995
            rows.append({"ticker": f"T{t}", "date": d, "open": o, "high": h, "low": lo, "close": c,
                         "adjusted_close": c, "volume": 100_000})
            close = c
    return pd.DataFrame(rows).sort_values(["ticker", "date"]).reset_index(drop=True)


@pytest.fixture()
def scan(monkeypatch):
    df = _panel()

    async def fake_load(days: int) -> pd.DataFrame:
        return df.copy()

    monkeypatch.setattr(alpha, "_load_bulk_ohlcv", fake_load)

    def run(**kw):
        req = alpha.ScanRequest(strategy_id="S3_GAP_POLARITY", mode=kw.pop("mode", "recent"), recent_days=5, **kw)
        return asyncio.run(alpha.run_scan(req))
    return run


def test_engine_charges_the_shared_round_trip_not_a_flat_friction():
    eng = alpha._load_engine()
    assert not hasattr(eng.GapPolarityStrategy, "FRICTION_ROUND_TRIP")
    real = default_model().round_trip_pct(100_000) / 100
    assert eng.round_trip_cost(100_000) == pytest.approx(real)
    assert 0.0090 < real < 0.0095                                             # ≈ 0.93 % on ICICI MoneySaver
    # the fixed ₹24 DP charge makes small positions dearer (negative control: a flat friction would not move)
    assert eng.round_trip_cost(10_000) > eng.round_trip_cost(100_000) > eng.round_trip_cost(10_000_000)
    diag = eng.GapPolarityStrategy().forward_diagnostics(_panel(), position_inr=100_000)
    ok = diag.dropna(subset=["fwd5"])
    assert np.allclose(ok["net5"], ok["fwd5"] - real)
    assert not np.allclose(ok["net5"], ok["fwd5"] - 0.0015)                   # the old 0.15 % is gone


def test_scan_reports_cost_interval_and_history(scan):
    out = scan()
    cost = out["cost"]
    assert cost["model"] == "shared/trading_costs.py" and cost["position_inr"] == 100_000
    assert cost["round_trip_pct"] == pytest.approx(default_model().round_trip_pct(100_000), abs=1e-4)
    hist, win = out["edge_history"], out["edge"]
    assert hist is not None and win is not None
    assert hist["n_with_forward"] >= win["n_with_forward"]
    assert hist["cost_bps"] == pytest.approx(cost["round_trip_pct"] * 100, abs=0.01)
    assert hist["mean_gross5_bps"] - hist["mean_net5_bps"] == pytest.approx(hist["cost_bps"], abs=0.02)
    lo, hi = hist["mean_net5_ci95_bps"]
    assert lo <= hist["mean_net5_bps"] <= hi
    wl, wh = hist["win_rate_ci95"]
    assert 0 <= wl <= hist["win_rate"] <= wh <= 1
    assert hist["n_dates"] >= 2 and "signal dates" in hist["ci_method"]
    assert out["badge"] == "arithmetic" and out["verdict"]["verdict"] == "NO EDGE"
    assert "Describes, does not predict" in out["verdict"]["note"]


def test_a_bigger_position_costs_less_per_rupee(scan):
    small, big = scan(position_inr=10_000), scan(position_inr=1_000_000)
    assert small["cost"]["round_trip_pct"] > big["cost"]["round_trip_pct"]
    assert small["edge_history"]["mean_net5_bps"] < big["edge_history"]["mean_net5_bps"]


def test_rows_carry_the_last_close_to_close_change(scan):
    out = scan()
    r = out["results"][0]
    assert r["eod_change_pct"] is not None and r["eod_change_date"] == out["as_of"]
    df = _panel()
    t = df[df["ticker"] == r["ticker"]]
    assert r["eod_change_pct"] == pytest.approx((t["close"].iloc[-1] / t["close"].iloc[-2] - 1) * 100, abs=0.01)


def test_edge_stats_rules():
    idx = pd.MultiIndex.from_tuples([("A", pd.Timestamp("2026-01-01")), ("B", pd.Timestamp("2026-01-01")),
                                     ("C", pd.Timestamp("2026-01-02"))], names=["ticker", "date"])
    st = alpha.edge_stats(pd.Series([0.01, -0.02, 0.03], index=idx), 0.009)
    assert st["n_with_forward"] == 3 and st["n_dates"] == 2 and st["win_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert st["mean_net5_bps"] == pytest.approx(66.67, abs=0.01)
    assert st["top3_dates"][0] == {"date": "2026-01-01", "n": 2, "mean_net5_bps": -50.0}
    assert st["top3_dates_signal_share"] == 1.0                                 # 3 signals on 2 dates: all in the top 3
    # negative controls: no forward window ⇒ None; a single signal date ⇒ no interval is invented
    assert alpha.edge_stats(pd.Series([np.nan], index=idx[:1]), 0.009) is None
    one = alpha.edge_stats(pd.Series([0.01, 0.02], index=idx[:2]), 0.009)
    assert one["mean_net5_ci95_bps"] is None and one["n_dates"] == 1


def test_strategy_name_no_longer_borrows_alpha_lab_s3():
    eng = alpha._load_engine()
    name = eng.GapPolarityStrategy.NAME
    assert "S3-Simplified" not in name and "not alpha_lab S3" in name
