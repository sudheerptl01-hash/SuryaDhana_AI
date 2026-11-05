"""Basket risk (services/data-service/basket_risk.py) on synthetic returns with known properties."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import basket_risk as br  # noqa: E402


def _data(n=252, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    m = pd.Series(rng.normal(0, 0.01, n), index=idx)
    a = 1.5 * m + rng.normal(0, 0.005, n)          # beta 1.5
    b = 0.5 * m + rng.normal(0, 0.005, n)          # beta 0.5
    c = pd.Series(rng.normal(0, 0.02, n), index=idx)  # independent
    return pd.DataFrame({"A": a, "B": b, "C": c}, index=idx), m


def test_per_stock_beta_vol_and_drawdown():
    rets, m = _data()
    out = br.basket_risk(rets, m)
    s = {x["symbol"]: x for x in out["stocks"]}
    assert s["A"]["beta"] == pytest.approx(1.5, abs=0.1) and s["B"]["beta"] == pytest.approx(0.5, abs=0.1)
    assert s["C"]["vol"] == pytest.approx(0.02 * np.sqrt(252) * 100, rel=0.15)
    assert s["A"]["max_dd"] <= 0


def test_basket_diversifies_and_flags_the_most_correlated_pair():
    rets, m = _data()
    b = br.basket_risk(rets, m)["basket"]
    assert b["n"] == 3 and b["vol"] < b["avg_stock_vol"] and b["diversification"] > 1
    assert b["beta"] == pytest.approx((1.5 + 0.5 + 0) / 3, abs=0.1)
    assert {b["most_correlated"]["a"], b["most_correlated"]["b"]} == {"A", "B"}


def test_short_history_is_reported_not_used():
    rets, m = _data()
    rets["NEW"] = np.nan
    rets.iloc[-20:, rets.columns.get_loc("NEW")] = 0.01
    out = br.basket_risk(rets, m)
    new = next(x for x in out["stocks"] if x["symbol"] == "NEW")
    assert new["vol"] is None and new["obs"] == 20 and out["basket"]["n"] == 3


def test_single_stock_still_gets_nifty_comparison():
    rets, m = _data()
    out = br.basket_risk(rets[["A"]], m)
    assert "basket" not in out and out["nifty"]["vol"] > 0 and out["stocks"][0]["beta"] is not None


def test_value_weights_tilt_the_basket():
    rets, m = _data()
    eq = br.basket_risk(rets, m)["basket"]
    tilted = br.basket_risk(rets, m, weights={"A": 10.0, "B": 0.0, "C": 0.0})["basket"]
    assert tilted["weighting"] == "value" and eq["weighting"] == "equal"
    assert tilted["beta"] == pytest.approx(1.5, abs=0.1)          # all weight on A


def test_tail_risk_is_the_5pct_loss_and_its_average():
    import numpy as np
    import pandas as pd
    r = pd.Series(np.r_[np.full(95, 0.001), [-0.01, -0.02, -0.03, -0.04, -0.05]])     # 100 days, five losses
    t = br.tail_risk(r)
    assert t["worst_day"] == 5.0
    assert 0.9 <= t["var95"] <= 1.1                    # the 5th-percentile day is about the smallest of the five losses
    assert t["es95"] >= t["var95"] and t["es95"] <= 5.0
    assert br.tail_risk(r.iloc[:30]) == {"var95": None, "es95": None, "worst_day": None}
