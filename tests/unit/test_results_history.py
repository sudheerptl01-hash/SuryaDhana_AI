"""Results reactions (services/data-service/results_history.py): release parsing and reaction-session timing."""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
import results_history as rh  # noqa: E402


def test_parse_releases_keeps_earliest_per_quarter_across_feeds():
    old = [{"broadCastDate": "09-Jan-2025 21:39:43", "toDate": "31-Dec-2024"},
           {"broadCastDate": "09-Jan-2025 21:36:33", "toDate": "31-Dec-2024"}]          # standalone first
    new = [{"broadcast_Date": "08-Oct-2026 22:07:33", "qe_Date": "30-Sep-2026"},
           {"broadcast_Date": "-", "qe_Date": "30-Jun-2026"}]                            # unparseable → dropped
    df = rh.parse_releases([(old, "broadCastDate", "toDate"), (new, "broadcast_Date", "qe_Date")], "TCS")
    assert len(df) == 2
    assert df.iloc[0]["released_at"] == datetime(2025, 1, 9, 21, 36, 33)


def _bars():
    dates = pd.bdate_range("2026-10-05", periods=6)          # Mon 5 → Mon 12 Oct (no weekend rows)
    close = [100, 102, 110, 99, 100, 105]
    return pd.DataFrame({"date": dates, "adj_open": [c - 1 for c in close], "adj_close": close})


NIFTY = pd.Series([1000, 1000, 1010, 1010, 1010, 1010], index=pd.bdate_range("2026-10-05", periods=6))


@pytest.mark.parametrize("released,react_date,move,timing", [
    ("2026-10-07 11:00", "2026-10-07", 110 / 102 - 1, "market hours"),     # in session → same day
    ("2026-10-07 18:30", "2026-10-08", 99 / 110 - 1, "after close"),       # after 15:30 → next session
    ("2026-10-10 10:00", "2026-10-12", 105 / 100 - 1, "after close"),      # Saturday → Monday
    ("2026-10-07 00:10", "2026-10-07", 110 / 102 - 1, "pre-open"),         # before 09:15 → same session
])
def test_reaction_session_follows_release_time(released, react_date, move, timing):
    rel = pd.DataFrame({"symbol": "X", "period_end": ["2026-09-30"], "released_at": [pd.Timestamp(released)]})
    rx = rh.reactions(rel, _bars(), NIFTY)
    assert rx[0]["reaction_date"] == react_date and rx[0]["timing"] == timing
    assert rx[0]["move_pct"] == pytest.approx(move * 100, abs=0.01)


def test_reaction_vs_nifty_and_summary():
    rel = pd.DataFrame({"symbol": "X", "period_end": ["2026-09-30"], "released_at": [pd.Timestamp("2026-10-07 11:00")]})
    rx = rh.reactions(rel, _bars(), NIFTY)
    assert rx[0]["vs_nifty_pct"] == pytest.approx((110 / 102 - 1) * 100 - 1.0, abs=0.01)   # NIFTY +1% that day
    s = rh.summary(rx)
    assert s["quarters"] == 1 and s["up_pct"] == 100
    assert rh.summary([]) == {"quarters": 0}


def test_typical_moves_from_duckdb_skips_unadjusted_splits():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE nse_results (symbol VARCHAR, period_end DATE, released_at TIMESTAMP)")
    con.execute("CREATE TABLE nse_bhavcopy (symbol VARCHAR, series VARCHAR, date DATE, close DOUBLE)")
    days = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=30), periods=40)
    closes = [100.0] * 40
    closes[10] = 104.0          # release 1 reacts +4%
    closes[20:] = [52.0] * 20   # a 1:2 split left unadjusted: −50% → must be ignored
    closes[30:] = [49.4] * 10   # release 3 reacts −5%
    con.executemany("INSERT INTO nse_bhavcopy VALUES ('X', 'EQ', ?, ?)", [[d.date(), c] for d, c in zip(days, closes)])
    for i in (10, 20, 30):
        con.execute("INSERT INTO nse_results VALUES ('X', ?, ?)", [days[i].date(), days[i] + pd.Timedelta(hours=11)])
    out = rh.typical_moves(con, ["X", "NOPE"])
    assert set(out) == {"X"}
    assert out["X"]["quarters"] == 2 and out["X"]["avg_abs_move_pct"] == pytest.approx(4.5, abs=0.01)


def test_recent_reactions_after_close_and_pending():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE nse_results (symbol VARCHAR, period_end DATE, released_at TIMESTAMP)")
    con.execute("CREATE TABLE nse_bhavcopy (symbol VARCHAR, series VARCHAR, date DATE, close DOUBLE, turnover_lacs DOUBLE)")
    con.execute("CREATE TABLE market_index_daily (symbol VARCHAR, date DATE, close DOUBLE)")
    days = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=1), periods=30)
    for i, d in enumerate(days):
        c = 100.0 if i < 28 else 106.0                      # +6% on the second-to-last session
        con.execute("INSERT INTO nse_bhavcopy VALUES ('A', 'EQ', ?, ?, 1000)", [d.date(), c])
        con.execute("INSERT INTO market_index_daily VALUES ('NIFTY50', ?, ?)", [d.date(), 1000.0 if i < 28 else 1010.0])
    con.execute("INSERT INTO nse_results VALUES ('A', '2026-09-30', ?)", [days[27] + pd.Timedelta(hours=19)])   # after close → days[28]
    con.execute("INSERT INTO nse_results VALUES ('A', '2026-06-30', ?)", [pd.Timestamp.now() + pd.Timedelta(hours=1)])  # not traded yet
    rows = rh.recent_reactions(con, days=10)
    done = [r for r in rows if r["move_pct"] is not None]
    pending = [r for r in rows if r["move_pct"] is None]
    assert len(done) == 1 and done[0]["timing"] == "after close"
    assert done[0]["move_pct"] == pytest.approx(6.0) and done[0]["vs_nifty_pct"] == pytest.approx(5.0)
    assert done[0]["sessions_since"] == 1 and done[0]["avoid"] is False      # a strong *good* reaction is never flagged
    assert len(pending) == 1


def test_recent_reactions_flags_strong_bad_results_as_avoid():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE nse_results (symbol VARCHAR, period_end DATE, released_at TIMESTAMP)")
    con.execute("CREATE TABLE nse_bhavcopy (symbol VARCHAR, series VARCHAR, date DATE, close DOUBLE, turnover_lacs DOUBLE)")
    con.execute("CREATE TABLE market_index_daily (symbol VARCHAR, date DATE, close DOUBLE)")
    days = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=1), periods=30)
    for i, d in enumerate(days):
        con.execute("INSERT INTO nse_bhavcopy VALUES ('B', 'EQ', ?, ?, 1000)", [d.date(), 100.0 if i < 25 else 90.0])
        con.execute("INSERT INTO market_index_daily VALUES ('NIFTY50', ?, 1000)", [d.date()])
    con.execute("INSERT INTO nse_results VALUES ('B', '2026-09-30', ?)", [days[25] + pd.Timedelta(hours=11)])  # in session
    r = rh.recent_reactions(con, days=30)[0]
    assert r["vs_nifty_pct"] == pytest.approx(-10.0) and r["sessions_since"] == 4 and r["avoid"] is True


def test_governance_filings_are_not_results_releases():
    # ETERNAL, integrated feed (real rows, 14 Oct 2026): the governance filing comes a week before the results
    rows = [{"qe_Date": "30-JUN-2026", "broadcast_Date": "14-Jul-2026 13:24:50", "type": "Integrated Filing- Governance"},
            {"qe_Date": "30-JUN-2026", "broadcast_Date": "22-Jul-2026 19:17:12", "type": "Integrated Filing- Financials"},
            {"qe_Date": "30-SEP-2026", "broadcast_Date": "12-Oct-2026 18:24:38", "type": "Integrated Filing- Governance"}]
    df = rh.parse_releases([(rows, "broadcast_Date", "qe_Date")], "ETERNAL")
    assert len(df) == 1                                            # no fake Q2 FY27 "release" from the governance filing
    assert str(df.loc[0, "released_at"]) == "2026-07-22 19:17:12"
