"""Paper shadow (alpha_lab/paper/shadow.py): signal timing, pre-start state and replay determinism."""
import sys
from pathlib import Path

import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
from paper import shadow  # noqa: E402


def test_signal_rows_are_month_ends_that_already_have_a_fill_session():
    sessions = pd.DatetimeIndex(["2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03",
                                 "2026-11-27", "2026-11-30"])
    rows = shadow.signal_rows(sessions, pd.Timestamp("2026-10-15"))
    assert [str(sessions[r].date()) for r in rows] == ["2026-10-30"]      # 30 Nov waits for a December session
    # before the start date nothing signals, even a month end
    assert shadow.signal_rows(sessions, pd.Timestamp("2026-12-01")) == []
    # once a December session exists, 30 Nov becomes the second signal
    sessions2 = sessions.append(pd.DatetimeIndex(["2026-12-01"]))
    rows2 = shadow.signal_rows(sessions2, pd.Timestamp("2026-10-15"))
    assert [str(sessions2[r].date()) for r in rows2] == ["2026-10-30", "2026-11-30"]


def test_span_before_launch_is_the_armed_anchor():
    sessions = pd.bdate_range("2026-10-01", "2026-10-14")
    span = shadow.span_of(sessions, pd.Timestamp("2026-10-15"))
    assert len(span) == 1 and span[0] == sessions[-1]
    after = shadow.span_of(sessions, pd.Timestamp("2026-10-10"))
    assert after[0] == pd.Timestamp("2026-10-12")                          # first session ≥ start


def test_replay_is_deterministic_and_prestart_nav_is_flat():
    # two replays over the same tiny world give identical NAV; pre-signal NAV = 100 for every track
    idx = pd.bdate_range("2026-09-01", "2026-10-14")
    close = pd.DataFrame(100.0, index=idx, columns=["AAA", "BBB"])
    panel = {"close": close, "open": close.copy(), "raw_close": close.copy(),
             "series": close.notna().map(lambda b: "EQ"),
             "corporate_actions": pd.DataFrame(columns=["symbol", "date", "k"])}
    nifty = pd.Series(100.0, index=idx)
    res = {"S1": shadow.engine.Result(pd.Series(1_000_000.0, index=idx[-1:]), pd.Series(1_000_000.0, index=idx[-1:]),
                                      pd.DataFrame(), 0.0, shadow.VARIANTS["S1"], []),
           "S1H": shadow.engine.Result(pd.Series(5_000_000.0, index=idx[-1:]), pd.Series(5_000_000.0, index=idx[-1:]),
                                       pd.DataFrame(), 0.0, shadow.VARIANTS["S1H"], [])}
    nav1 = shadow.nav_frame(res, nifty, idx, shadow.START)
    nav2 = shadow.nav_frame(res, nifty, idx, shadow.START)
    assert nav1.equals(nav2)
    assert (nav1[["S1", "S1H"]].iloc[-1] == 100.0).all()
