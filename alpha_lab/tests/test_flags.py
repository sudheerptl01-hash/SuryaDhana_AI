"""alpha_lab flags: reaction-session timing and event windows are point-in-time safe."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
from strategies import flags as fl  # noqa: E402


def tiny_panel(n=320):
    idx = pd.bdate_range("2023-01-02", periods=n)
    base = pd.DataFrame(100.0, index=idx, columns=["AAA", "BBB", "CCC", "DDD", "EEE"])
    return {"close": base.copy(), "raw_close": base.copy(), "turnover_cr": base * 0 + 10.0,
            "series": base.notna().map(lambda b: "EQ"),
            "corporate_actions": pd.DataFrame(columns=["symbol", "date", "k"])}


def test_results_reaction_timing_and_strength():
    p = tiny_panel()
    c = p["close"]
    sessions = c.index
    d0 = sessions[260]
    # AAA falls 8% on the session AFTER an evening release; BBB falls 8% on the SAME session for a
    # market-hours release; CCC falls only 3% (not strong).
    c.loc[d0:, "AAA"] = 92.0
    c.loc[sessions[259]:, "BBB"] = 92.0
    c.loc[sessions[259]:, "CCC"] = 97.0
    releases = pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC"],
        "period_end": [pd.Timestamp("2023-12-31")] * 3,
        "released_at": [pd.Timestamp(sessions[259]) + pd.Timedelta(hours=19),     # after close → reacts at 260
                        pd.Timestamp(sessions[259]) + pd.Timedelta(hours=11),     # in hours → reacts at 259
                        pd.Timestamp(sessions[259]) + pd.Timedelta(hours=11)],
    })
    ev = fl.results_reactions(p, releases, strong=5.0)
    got = {(r.symbol, r.date) for r in ev["down"].itertuples()}
    assert ("AAA", sessions[260]) in got
    assert ("BBB", sessions[259]) in got
    assert all(sym != "CCC" for sym, _ in got)                     # −3% is not a strong reaction
    # the flag window: bad_results_60d must be False BEFORE the reaction session
    frames = fl.s1_veto_frames(p, releases)
    assert not frames["bad_results_60d"].loc[sessions[259], "AAA"]
    assert frames["bad_results_60d"].loc[sessions[260], "AAA"]
    assert frames["bad_results_60d"].loc[sessions[310], "AAA"]     # still inside 60 sessions


def test_split_flag_covers_20_sessions_only():
    p = tiny_panel()
    sessions = p["close"].index
    p["corporate_actions"] = pd.DataFrame({"symbol": ["DDD"], "date": [sessions[270]], "k": [0.5]})
    frames = fl.s1_veto_frames(p, pd.DataFrame(columns=["symbol", "period_end", "released_at"]))
    f = frames["split_20d"]
    assert not f.loc[sessions[269], "DDD"]
    assert f.loc[sessions[270], "DDD"] and f.loc[sessions[289], "DDD"]
    assert not f.loc[sessions[291], "DDD"]


def test_lab_eligible_uses_raw_close_floor():
    p = tiny_panel()
    p["raw_close"]["EEE"] = 15.0                                    # raw below ₹20 → out, whatever adjusted says
    p["close"]["EEE"] = 500.0
    sig = {"hist": p["close"].notna().cumsum(),
           "liq": p["turnover_cr"].rolling(5, min_periods=1).median()}
    uni = fl.lab_eligible(sig, p, 300)
    assert "EEE" not in uni and "AAA" in uni
