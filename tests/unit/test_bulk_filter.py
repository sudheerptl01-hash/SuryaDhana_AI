"""Candidate Decision Desk filter: block new entries after non-institutional bulk-deal buying."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.deal_filters import non_institutional_buy_events  # noqa: E402
from shared.momentum import StrategyConfig, bulk_buy_blocklist, compute_targets, select  # noqa: E402


def test_blocked_names_are_kept_if_held_but_never_newly_bought():
    score = pd.Series({"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0})
    assert select(score, held=set(), n=2, blocked={"A"}) == ["B", "C"]
    assert select(score, held={"A"}, n=2, blocked={"A"}) == ["A", "B"]      # holding is not force-sold


def test_blocklist_window_uses_only_past_sessions():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    panel = {"close": pd.DataFrame(1.0, index=idx, columns=["A", "B", "C", "D"]),
             "bulk_buy_events": pd.DataFrame({"date": [idx[5], idx[18], idx[20], idx[25]],
                                              "symbol": ["A", "B", "C", "D"]})}
    blocked = bulk_buy_blocklist(panel, s=20, days=3)       # sessions 18, 19, 20
    assert blocked == {"B", "C"}                            # A too old, D in the future


def test_filter_on_without_event_data_fails_loudly():
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    panel = {"close": pd.DataFrame(100.0, index=idx, columns=["A"]),
             "series": pd.DataFrame("EQ", index=idx, columns=["A"]),
             "turnover_cr": pd.DataFrame(10.0, index=idx, columns=["A"])}
    sig = {"hist": panel["close"].notna().cumsum(), "liq": panel["turnover_cr"],
           "mom_nse": pd.DataFrame(np.nan, index=idx, columns=["A"])}
    with pytest.raises(ValueError, match="bulk_buy_events"):
        compute_targets(StrategyConfig(avoid_bulk_buy_days=20, overlay="none"), panel, sig,
                        pd.Series(dtype=float), 299, set())


def test_non_institutional_events_exclude_funds_and_round_trips():
    deals = pd.DataFrame({
        "date": pd.to_datetime(["2024-03-01"] * 4), "symbol": ["ABC", "ABC", "XYZ", "XYZ"],
        "client_name": ["SBI MUTUAL FUND", "SOME LLP", "HFT LLP", "HFT LLP"],
        "side": ["BUY", "BUY", "BUY", "SELL"], "qty": [100, 100, 500, 490],
    })
    ev = non_institutional_buy_events(deals)
    assert ev.to_dict("records") == [{"date": pd.Timestamp("2024-03-01"), "symbol": "ABC"}]


def test_config_name_marks_the_filter():
    assert StrategyConfig().name == "mom_nse|N20|nifty200_vt|sc40"
    assert StrategyConfig(avoid_bulk_buy_days=20).name.endswith("|nobulk20")
