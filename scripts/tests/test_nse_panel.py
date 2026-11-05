"""nse_panel: corporate-action detection (Yahoo splits + circuit-proof gap rule), series pick."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nse_panel as npn  # noqa: E402


def _rows(closes, opens=None, symbol="ABC", series="EQ", vol=100, start="2024-01-01"):
    d = pd.bdate_range(start, periods=len(closes))
    opens = opens if opens is not None else closes
    return pd.DataFrame({"symbol": symbol, "series": series, "date": d, "close": closes, "open": opens,
                         "prev_close": pd.Series(closes).shift(1).fillna(closes[0]).to_numpy(),
                         "high": closes, "low": closes, "avg_price": closes, "volume": vol})


def test_yahoo_split_is_applied_on_first_session_on_or_after_the_date():
    df = _rows([297.45, 300.0, 34.05, 33.0], opens=[297.0, 299.0, 30.4, 33.5], symbol="IRB")
    splits = pd.DataFrame({"ticker": ["IRB"], "date": [df["date"][2]], "ratio": [10.0]})
    out = npn.adjust(df, splits)
    assert np.allclose(out["adj_close"], [29.745, 30.0, 34.05, 33.0])
    assert np.allclose(out["adj_volume"], [1000, 1000, 100, 100])
    ev = out.attrs["corporate_actions"]
    assert list(ev["source"]) == ["yahoo_split"] and np.isclose(ev["k"].iloc[0], 0.1)


def test_gap_rule_catches_delisted_name_bonus_and_ignores_normal_moves():
    # 1:1 bonus (k = 0.5) on day 3 for a name Yahoo doesn't know; day 5 is a real −18% circuit day
    df = _rows([100.0, 102.0, 51.5, 52.0, 42.6], opens=[100.0, 101.0, 50.8, 51.9, 42.8], symbol="GONE")
    out = npn.adjust(df, pd.DataFrame(columns=["ticker", "date", "ratio"]))
    ev = out.attrs["corporate_actions"]
    assert len(ev) == 1 and ev["k"].iloc[0] == 0.5 and ev["source"].iloc[0] == "gap_heuristic"
    assert np.allclose(out["adj_close"][:2], [50.0, 51.0])


def test_yahoo_date_off_by_days_is_moved_to_the_real_gap_and_bogus_date_skipped():
    df = _rows([100.0, 100.0, 101.0, 50.5, 51.0], opens=[100.0, 100.0, 101.0, 50.4, 51.0], symbol="HAL")
    wrong = pd.DataFrame({"ticker": ["HAL"], "date": [df["date"][1]], "ratio": [2.0]})   # 2 sessions early
    ev = npn.adjust(df, wrong).attrs["corporate_actions"]
    assert list(ev["date"]) == [df["date"][3]] and ev["source"].iloc[0] == "yahoo_split"
    flat = _rows([100.0, 100.0, 101.0, 101.0])
    none = pd.DataFrame({"ticker": ["ABC"], "date": [flat["date"][2]], "ratio": [2.0]})   # no gap anywhere
    assert npn.adjust(flat, none).attrs["corporate_actions"].empty


def test_unexplained_gap_or_gap_after_long_halt_is_not_adjusted():
    odd = _rows([100.0, 100.0, 71.0], opens=[100.0, 100.0, 71.0])            # 0.71: no standard ratio
    assert npn.adjust(odd).attrs["corporate_actions"].empty
    combo = _rows([100.0, 100.0, 7.7, 7.8], opens=[100.0, 100.0, 7.7, 7.8], symbol="VST")  # 1:10 split + 3:10 bonus
    assert npn.adjust(combo).attrs["corporate_actions"].empty          # unconfirmed extreme gap: left alone
    yahoo = pd.DataFrame({"ticker": ["VST"], "date": [combo["date"][2]], "ratio": [10.0]})   # Yahoo: 1:10 only
    ev = npn.adjust(combo, yahoo).attrs["corporate_actions"]
    assert list(ev["source"]) == ["yahoo_confirmed_raw"] and np.isclose(ev["k"].iloc[0], 0.077)
    halt = pd.concat([_rows([100.0, 100.0]), _rows([50.0, 50.0], start="2024-03-01")])  # resumed after weeks
    assert npn.adjust(halt).attrs["corporate_actions"].empty


def test_pick_equity_rows_prefers_eq_over_be():
    a = _rows([10.0], series="BE")
    b = _rows([10.5], series="EQ")
    c = _rows([1.0], series="GS")                          # g-sec: dropped
    out = npn.pick_equity_rows(pd.concat([a, b, c]))
    assert list(out["series"]) == ["EQ"] and out["close"].iloc[0] == 10.5
