"""data-service index valuation vs history: same-basis percentiles only (NSE moved index P/E to consolidated in 2021)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))

import main as data_service  # noqa: E402


def _history() -> pd.DataFrame:
    days = pd.bdate_range("2019-01-01", "2026-10-13").strftime("%Y-%m-%d")
    pe = [30.0 if d < "2021-03-31" else 18.0 + (i % 10) for i, d in enumerate(days)]   # standalone era runs higher
    return pd.DataFrame({"date": days, "index": "NIFTY 50", "pe": pe})


def test_percentile_ignores_days_before_the_basis_change() -> None:
    out = data_service.valuation_vs_history(_history(), {"NIFTY 50": 22.5}, basis_from="2021-03-31")
    v = out["NIFTY 50"]
    assert v["since"] >= "2021-03-31"
    assert 40 <= v["pctl"] <= 60          # 18..27 evenly → 22.5 sits mid-range; the 30× standalone days would drag it down
    assert v["high"] == 27.0 and v["low"] == 18.0
    assert v["p25"] <= v["median"] <= v["p75"]


def test_short_or_missing_history_is_left_out() -> None:
    h = _history()
    assert data_service.valuation_vs_history(h, {"NIFTY 50": 20.0}, basis_from="2026-09-01") == {}   # < 250 days
    assert data_service.valuation_vs_history(h, {"NIFTY IT": 25.0}) == {}
    assert data_service.valuation_vs_history(h, {"NIFTY 50": None}) == {}
    assert data_service.valuation_vs_history(None, {"NIFTY 50": 20.0}) == {}


def test_seasonality_grid_months_and_current() -> None:
    import seasonality as sea
    days = pd.bdate_range("2023-12-01", "2026-10-13")
    # +1% every business day in October, flat otherwise → October up every completed year, current Oct "so far"
    step = [1.01 if d.month == 10 else 1.0 for d in days]
    closes = pd.Series(pd.Series(step, index=days).cumprod().to_numpy() * 100, index=days)
    out = sea.seasonality(closes)
    octo = next(m for m in out["months"] if m["month"] == "Oct")
    assert octo["n"] == 2 and octo["pct_up"] == 100 and octo["avg"] > 20         # Oct 2024 and Oct 2025, ~22 sessions each
    jan = next(m for m in out["months"] if m["month"] == "Jan")
    assert jan["n"] == 3 and jan["avg"] == 0.0                                   # Jan 2024–2026, flat
    assert out["current"]["month"] == "Oct" and out["current"]["year"] == 2026 and out["current"]["ret"] > 0
    assert out["grid"][0]["year"] == 2026 and out["grid"][0]["months"]["Oct"] is None   # current month not in the grid
    dec = next(m for m in out["months"] if m["month"] == "Dec")
    assert dec["n"] == 2                                                         # Dec 2023 is the partial first month


def test_yield_gap_joins_months_and_compares_same_basis() -> None:
    import yield_gap as yg
    days = pd.bdate_range("2020-01-01", "2026-07-31")
    nifty = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "pe": [25.0 if d < pd.Timestamp("2021-03-31") else 20.0 for d in days]})
    months = pd.period_range("2020-01", "2026-07", freq="M")
    y10 = pd.Series([6.0] * len(months), index=months)
    out = yg.yield_gap(nifty, y10)
    first, last = out["points"][0], out["points"][-1]
    assert first["month"] == "2020-01" and first["ey"] == 4.0 and first["gap"] == -2.0
    assert last["month"] == "2026-07" and last["ey"] == 5.0 and last["gap"] == -1.0
    assert out["stats"]["months"] == 64 and out["stats"]["median"] == -1.0          # Apr 2021 → Jul 2026 only
    assert yg.yield_gap(nifty.iloc[0:0], y10)["points"] == []


def test_relative_valuation_vs_nifty() -> None:
    days = pd.bdate_range("2021-04-01", "2026-10-13").strftime("%Y-%m-%d")
    h = pd.concat([pd.DataFrame({"date": days, "index": "NIFTY 50", "pe": 20.0}),
                   pd.DataFrame({"date": days, "index": "NIFTY SMALLCAP 250", "pe": [24.0 + (i % 5) for i in range(len(days))]})])
    out = data_service.relative_vs_history(h, {"NIFTY SMALLCAP 250": 36.0}, 20.0)
    v = out["NIFTY SMALLCAP 250"]
    assert v["ratio"] == 1.8 and v["pctl"] == 100 and v["median"] == 1.3      # 24..28 over 20 → 1.2..1.4
    assert data_service.relative_vs_history(h, {"NIFTY SMALLCAP 250": 36.0}, None) == {}


def test_implied_event_move_separates_the_results_day() -> None:
    import math
    import option_chain as oc
    # 5 trading days, normal days 1.5% σ, options price ±5% by expiry → event σ = √(25 − 4×2.25) = 4.0%
    out = oc.implied_event_move(5.0, 5, 1.5)
    assert out["event_sigma_pct"] == 4.0 and out["event_abs_move_pct"] == round(4.0 * math.sqrt(2 / math.pi), 2)
    assert oc.implied_event_move(2.0, 5, 1.5)["event_sigma_pct"] == 0.0       # nothing extra priced in
    assert oc.implied_event_move(0, 5, 1.5)["event_sigma_pct"] is None


def test_term_structure_event_move() -> None:
    import math
    import option_chain as oc
    # normal daily σ 1%: front (10 days incl. the event) and next (30 days) both price the same 4% event
    em1, em2 = math.sqrt(9 * 1 + 16), math.sqrt(29 * 1 + 16)
    out = oc.implied_event_move_term(em1, 10, em2, 30)
    assert out["normal_daily_pct"] == 1.0 and out["event_sigma_pct"] == 4.0
    assert oc.implied_event_move_term(5.0, 10, 4.0, 30)["event_sigma_pct"] is None     # inverted: no reading
