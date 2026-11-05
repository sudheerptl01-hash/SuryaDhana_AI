"""Market Monitor (services/data-service/market_monitor.py): breadth maths on a synthetic NSE panel."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "market_monitor", Path(__file__).resolve().parents[2] / "services" / "data-service" / "market_monitor.py")
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)


def _panel(n_days: int = 320, trend: dict[str, float] | None = None) -> dict[str, pd.DataFrame]:
    """Stocks with a constant daily drift; UP* rise, DN* fall. Liquid, EQ, priced well above ₹20."""
    trend = trend or {"UP1": 0.002, "UP2": 0.002, "UP3": 0.001, "DN1": -0.002}
    idx = pd.bdate_range("2024-01-01", periods=n_days)
    close = pd.DataFrame({s: 100 * np.exp(np.arange(n_days) * g) for s, g in trend.items()}, index=idx)
    vol = pd.DataFrame(1e6, index=idx, columns=close.columns)
    return {"open": close, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": vol,
            "turnover_cr": pd.DataFrame(10.0, index=idx, columns=close.columns),
            "series": pd.DataFrame("EQ", index=idx, columns=close.columns), "raw_close": close,
            "deliv_pct": pd.DataFrame(50.0, index=idx, columns=close.columns)}


def test_breadth_counts_rising_stocks_above_their_averages():
    p = _panel()
    s = mm.breadth_series(p, p["close"].mean(axis=1), pd.Series(15.0, index=p["close"].index))
    last = s.iloc[-1]
    assert last["universe"] == 4
    assert last["pct_above50"] == pytest.approx(75.0)      # 3 of 4 rising
    assert last["pct_above200"] == pytest.approx(75.0)
    assert last["adv"] == 3 and last["dec"] == 1


def test_breadth_is_missing_not_zero_during_warmup():
    """Before the 200-DMA exists the share must be NaN, not a fake 0% (the chart showed a cliff)."""
    p = _panel()
    s = mm.breadth_series(p, p["close"].mean(axis=1), pd.Series(15.0, index=p["close"].index))
    first_valid_universe = s["universe"].first_valid_index()
    assert pd.isna(s.loc[first_valid_universe, "pct_above200"])
    assert s["pct_above200"].dropna().min() > 0


def test_universe_excludes_penny_illiquid_and_non_eq():
    p = _panel()
    p["raw_close"].loc[:, "UP3"] = 10.0                     # below ₹20
    p["turnover_cr"].loc[:, "DN1"] = 0.2                    # below ₹1 cr
    p["series"].loc[:, "UP2"] = "BE"
    assert list(mm.universe(p).iloc[-1][lambda x: x].index) == ["UP1"]


def test_snapshot_contract():
    p = _panel()
    snap = mm.snapshot(p, p["close"].mean(axis=1), "TEST", pd.Series(15.0, index=p["close"].index),
                       {"UP1": "IT", "UP2": "IT", "UP3": "IT", "DN1": "Power"})
    assert 0 <= snap["regime"]["score"] <= 4
    assert len(snap["regime"]["components"]) == 4
    assert snap["history"][-1]["date"] == snap["as_of"]
    assert snap["sectors"][0]["industry"] == "IT" and snap["sectors"][0]["stocks"] == 3
    assert {"gainers", "losers", "most_active", "volume_shockers", "new_highs", "new_lows"} <= snap["movers"].keys()
    assert snap["movers"]["gainers"][0]["symbol"] == "UP1"


@pytest.mark.parametrize("x,want", [(1, "1st"), (2, "2nd"), (11, "11th"), (13, "13th"), (22, "22nd"), (71.4, "71st")])
def test_ordinal(x, want):
    assert mm._ordinal(x) == want


def test_market_map_sizes_by_turnover_and_returns():
    p = _panel()
    p["turnover_cr"].loc[:, "UP1"] = 50.0                       # most traded first
    rows = mm.market_map(p, {"UP1": "IT"}, n=3)
    assert [r["symbol"] for r in rows][0] == "UP1" and len(rows) == 3
    assert rows[0]["industry"] == "IT" and rows[1]["industry"] == "Unclassified"
    assert rows[0]["r1"] == pytest.approx((np.exp(0.002) - 1) * 100, abs=0.01)


def test_universe_excludes_etfs():
    p = _panel(trend={"UP1": 0.002, "NIFTYBEES": 0.001, "GOLDETF": 0.001})
    assert list(mm.universe(p).iloc[-1][lambda x: x].index) == ["UP1"]


def test_rotation_puts_the_outperformer_on_the_right():
    trend = {f"A{i}": 0.003 for i in range(5)} | {f"B{i}": 0.0 for i in range(5)}
    p = _panel(trend=trend)
    inds = {f"A{i}": "Strong" for i in range(5)} | {f"B{i}": "Weak" for i in range(5)}
    rot = {r["industry"]: r for r in mm.rotation(p, inds)}
    assert set(rot) == {"Strong", "Weak"}
    assert rot["Strong"]["tail"][-1]["x"] > 100 > rot["Weak"]["tail"][-1]["x"]
    assert len(rot["Strong"]["tail"]) == 8
