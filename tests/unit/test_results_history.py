"""Results reactions (services/data-service/results_history.py): release parsing and reaction-session timing."""
import sys
from datetime import date, datetime
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


# ── review M12: the release time is the results filing (NSE announcement), not the later integrated broadcast ──────
def _ann(an_dt, desc, text):
    return {"an_dt": an_dt, "desc": desc, "attchmntText": text, "symbol": "MOTHERSON"}


MOTHERSON_ANN = [
    _ann("05-Nov-2026 14:58:36", "Outcome of Board Meeting",
         "Samvardhana Motherson International Limited has submitted to the Exchange, the financial results for the period ended September 30, 2026."),
    _ann("05-Nov-2026 15:40:11", "Analysts/Institutional Investor Meet/Con. Call Updates",
         "Schedule of earnings call on the financial results for the quarter ended September 30, 2026"),          # not results
    _ann("28-Oct-2026 18:02:00", "Board Meeting Intimation",
         "to consider and approve the unaudited financial results for the quarter ended September 30, 2026"),   # not results
]


def test_period_from_text_reads_nse_wording():
    assert str(rh.period_from_text("the financial results for the period ended Jun 30, 2026.")) == "2026-06-30"
    assert str(rh.period_from_text("results for the quarter and nine months ended December 31, 2024")) == "2024-12-31"
    assert str(rh.period_from_text("for the quarter ended 30th September, 2026")) == "2026-09-30"
    assert rh.period_from_text("board meeting held on July 18, 2024") is None                 # no 'ended'
    assert rh.period_from_text("for the period ended July 18, 2024") is None                  # not a quarter end


def test_results_announcements_keep_only_the_results_filing():
    ann = rh.results_announcements(MOTHERSON_ANN)
    assert ann == [(datetime(2026, 11, 5, 14, 58, 36), datetime(2026, 9, 30).date())]


def test_intraday_filer_is_moved_to_its_own_session():
    """MOTHERSON 5 Nov 2026: the integrated feed said 20:34 ('after close' → scored on Friday); the filing was 14:58."""
    feed = pd.DataFrame([{"symbol": "MOTHERSON", "period_end": datetime(2026, 9, 30).date(), "released_at": datetime(2026, 11, 5, 20, 34)},
                         {"symbol": "MOTHERSON", "period_end": datetime(2026, 6, 30).date(), "released_at": datetime(2026, 8, 7, 18, 10)}])
    out = rh.reconcile_with_announcements(feed, rh.results_announcements(MOTHERSON_ANN), "MOTHERSON")
    q2 = out[out["period_end"] == datetime(2026, 9, 30).date()].iloc[0]
    assert q2["released_at"] == pd.Timestamp("2026-11-05 14:58:36") and q2["source"] == "announcement"
    sessions = pd.DatetimeIndex(pd.bdate_range("2026-11-02", "2026-11-09"))
    pos, timing = rh.reaction_pos(pd.Timestamp(q2["released_at"]), sessions)
    assert timing == "market hours" and sessions[pos] == pd.Timestamp("2026-11-05")
    q1 = out[out["period_end"] == datetime(2026, 6, 30).date()].iloc[0]
    assert q1["source"] == "feed" and q1["released_at"] == pd.Timestamp("2026-08-07 18:10")      # no filing: unchanged


def test_a_later_filing_never_moves_a_release_later():
    """Negative control: an announcement after the feed's time (a revised filing) leaves the earlier time."""
    feed = pd.DataFrame([{"symbol": "X", "period_end": datetime(2026, 9, 30).date(), "released_at": datetime(2026, 11, 5, 14, 0)}])
    later = [(datetime(2026, 11, 6, 10, 0), datetime(2026, 9, 30).date())]
    out = rh.reconcile_with_announcements(feed, later, "X")
    assert out.iloc[0]["released_at"] == pd.Timestamp("2026-11-05 14:00") and out.iloc[0]["source"] == "feed"


def test_undated_filing_matches_only_within_the_lead_window():
    feed = pd.DataFrame([{"symbol": "X", "period_end": datetime(2026, 9, 30).date(), "released_at": datetime(2026, 11, 5, 20, 0)}])
    near = [(datetime(2026, 11, 5, 13, 0), None)]
    far = [(datetime(2026, 10, 20, 13, 0), None)]                                               # 16 days before: another filing
    assert rh.reconcile_with_announcements(feed, near, "X").iloc[0]["released_at"] == pd.Timestamp("2026-11-05 13:00")
    assert rh.reconcile_with_announcements(feed, far, "X").iloc[0]["released_at"] == pd.Timestamp("2026-11-05 20:00")


def test_a_quarter_not_on_the_feeds_yet_is_added_from_the_filing():
    feed = pd.DataFrame([{"symbol": "X", "period_end": datetime(2026, 6, 30).date(), "released_at": datetime(2026, 8, 7, 18, 10)}])
    out = rh.reconcile_with_announcements(feed, [(datetime(2026, 11, 5, 14, 58), datetime(2026, 9, 30).date())], "X")
    assert len(out) == 2 and out.iloc[-1]["source"] == "announcement_only"
    stale = [(datetime(2027, 6, 1, 10, 0), datetime(2026, 9, 30).date())]                      # > 120 days after: ignored
    assert len(rh.reconcile_with_announcements(feed, stale, "X")) == 1


# ── review M12, round 2: the filing time lives in its own column; released_at (alpha_lab's S1 input) never moves ──────
ROOT = Path(__file__).resolve().parents[2]
FEED_Q2 = {"broadcast_Date": "05-Nov-2026 20:34:10", "qe_Date": "30-Sep-2026", "type": "Integrated Filing- Financials"}
FEED_Q1 = {"broadcast_Date": "07-Aug-2026 18:10:00", "qe_Date": "30-Jun-2026", "type": "Integrated Filing- Financials"}


def _feeds(feed_rows: dict[str, list[dict]]):
    """A MockTransport httpx.Client for the two results feeds (rows per symbol on the integrated feed)."""
    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.rsplit("/", 1)[-1] != "corporate-announcements", "announcements must go through the paced client"
        if req.url.path.endswith("integrated-filing-results"):
            return httpx.Response(200, json=feed_rows.get(req.url.params["symbol"], []))
        return httpx.Response(200, json=[])
    return httpx.Client(transport=httpx.MockTransport(handler))


def _paced(ann_by_symbol: dict[str, list[dict]], seen: list | None = None, fail_days: tuple[str, ...] = ()):
    """shared/http_client.PacedClient on a MockTransport (no sleeping) for the corporate-announcements reads."""
    import httpx
    from shared.http_client import PacedClient

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "www.nseindia.com" and req.url.path.endswith("/corporate-announcements")
        if seen is not None:
            seen.append(dict(req.url.params))
        if req.url.params.get("from_date") in fail_days:
            return httpx.Response(503, text="down")
        sym = req.url.params.get("symbol")
        rows = ann_by_symbol.get(sym, []) if sym else [r for rows in ann_by_symbol.values() for r in rows]
        return httpx.Response(200, json=rows)
    return PacedClient(transport=httpx.MockTransport(handler), sleep=lambda _s: None)


def test_fetch_releases_keeps_released_at_and_puts_the_filing_in_filed_at():
    seen: list = []
    with _feeds({"MOTHERSON": [FEED_Q2, FEED_Q1]}) as c:
        df = rh.fetch_releases("MOTHERSON", client=c, sleep_s=0, today=datetime(2026, 11, 6).date(),
                               announcement_days=rh.ANNOUNCEMENT_RECENT_DAYS, paced=_paced({"MOTHERSON": MOTHERSON_ANN}, seen))
        q2 = df[df["period_end"] == datetime(2026, 9, 30).date()].iloc[0]
        assert q2["released_at"] == pd.Timestamp("2026-11-05 20:34:10")                  # the feed's time, untouched
        assert q2["filed_at"] == pd.Timestamp("2026-11-05 14:58:36") and q2["filed_source"] == "announcement"
        q1 = df[df["period_end"] == datetime(2026, 6, 30).date()].iloc[0]
        assert q1["filed_at"] == q1["released_at"] and q1["filed_source"] == "feed"     # no filing in the window
        assert seen == [{"index": "equities", "symbol": "MOTHERSON", "from_date": "07-10-2026", "to_date": "06-11-2026"}]  # 30 days
        # negative control: without announcements filed_at is the feed's time
        old = rh.fetch_releases("MOTHERSON", client=c, sleep_s=0, with_announcements=False)
        assert (old["filed_at"] == old["released_at"]).all() and (old["released_at"] == df["released_at"]).all()
        # the default asks NO announcements (an unpatched caller keeps the two pre-M12 requests)
        seen.clear()
        dflt = rh.fetch_releases("MOTHERSON", client=c, sleep_s=0, paced=_paced({"MOTHERSON": MOTHERSON_ANN}, seen))
        assert seen == [] and (dflt["filed_at"] == dflt["released_at"]).all()
        # prefetched day-wide filings (the nightly pass) make no per-symbol request
        seen.clear()
        pre = rh.fetch_releases("MOTHERSON", client=c, sleep_s=0, announcements=rh.results_announcements(MOTHERSON_ANN),
                                paced=_paced({}, seen))
        assert seen == [] and pre.iloc[-1]["filed_at"] == pd.Timestamp("2026-11-05 14:58:36")


def test_a_filing_for_a_quarter_the_feeds_lack_is_not_stored():
    """nse_results needs the feed's released_at: an announcement-only quarter waits for the feed (no invented row)."""
    with _feeds({"X": [FEED_Q1]}) as c:
        df = rh.fetch_releases("X", client=c, sleep_s=0, announcements=[(datetime(2026, 11, 5, 14, 58), datetime(2026, 9, 30).date())])
    assert len(df) == 1 and str(df.iloc[0]["period_end"]) == "2026-06-30"


def test_day_wide_filings_one_paced_request_per_day_and_none_on_a_failed_day():
    seen: list = []
    other = [{**_ann("05-Nov-2026 16:01:00", "Financial Result Updates",
                     "submitted to the Exchange, the financial results for the period ended September 30, 2026"), "symbol": "TITAN"}]
    got = rh.results_filings_by_day(datetime(2026, 11, 4).date(), datetime(2026, 11, 5).date(),
                                    paced=_paced({"MOTHERSON": MOTHERSON_ANN, "TITAN": other}, seen))
    assert [x["from_date"] for x in seen] == ["04-11-2026", "05-11-2026"] and all("symbol" not in x for x in seen)
    assert set(got) == {"MOTHERSON", "TITAN"} and got["MOTHERSON"] == [(datetime(2026, 11, 5, 14, 58, 36), datetime(2026, 9, 30).date())]
    # negative control: one failed day → None (the caller falls back to per-symbol reads; a failure is never 'no filing')
    assert rh.results_filings_by_day(datetime(2026, 11, 4).date(), datetime(2026, 11, 5).date(),
                                     paced=_paced({"MOTHERSON": MOTHERSON_ANN}, fail_days=("05-11-2026",))) is None


def _s1_releases_sql() -> str:
    """The exact query alpha_lab's S1 shadow runs on nse_results (read from its source, so the test follows any change)."""
    import re
    src = (ROOT / "alpha_lab" / "backtest" / "data_access.py").read_text()
    m = re.search(r'releases = q\(((?:\s*"[^"]*")+)\)', src)
    assert m, "alpha_lab's releases query moved: update this test"
    return "".join(re.findall(r'"([^"]*)"', m.group(1)))


def _s1_input_bytes(store) -> bytes:
    """The S1 shadow's release input as alpha_lab builds it (its SQL, its to_datetime), as bytes."""
    with store.reader() as con:
        df = con.execute(_s1_releases_sql()).df()
    df["released_at"] = pd.to_datetime(df["released_at"])
    df = df.sort_values(["symbol", "period_end"]).reset_index(drop=True)   # the query has no ORDER BY: compare content
    return df.to_csv(index=False).encode() + pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()


def test_s1_shadow_inputs_are_byte_identical_before_and_after_the_filing_column(tmp_path):
    """Checker major (round 1): M12 must not change what the S1 paper shadow reads. Same NSE responses through the
    pre-M12 path (feeds only, the store's upsert) and the new one (feeds + filings, store_releases): alpha_lab's
    releases query returns identical bytes; only the new filed_at column differs. Includes a re-fetch over stored rows."""
    from storage.duckdb_store import DuckDBStore
    feeds = {"MOTHERSON": [FEED_Q2, FEED_Q1], "TITAN": [{"broadcast_Date": "05-Nov-2026 17:05:00", "qe_Date": "30-Sep-2026",
                                                        "type": "Integrated Filing- Financials"}]}
    titan = [{**_ann("05-Nov-2026 16:01:00", "Financial Result Updates",
                     "submitted to the Exchange, the financial results for the period ended September 30, 2026"), "symbol": "TITAN"}]
    paced = _paced({"MOTHERSON": MOTHERSON_ANN, "TITAN": titan})
    before, after, round1 = (DuckDBStore(str(tmp_path / f"{n}.duckdb")) for n in ("before", "after", "round1"))
    try:
        with _feeds(feeds) as c:
            for _ in range(2):                                       # the nightly pass re-fetches stored symbols
                for sym in ("MOTHERSON", "TITAN"):
                    old = rh.fetch_releases(sym, client=c, sleep_s=0, with_announcements=False)
                    before.upsert_results(old[["symbol", "period_end", "released_at"]])           # pre-M12 behaviour
                    new = rh.fetch_releases(sym, client=c, sleep_s=0, today=datetime(2026, 11, 6).date(), paced=paced,
                                            announcement_days=rh.ANNOUNCEMENT_RECENT_DAYS)
                    rh.store_releases(after, new)
                    moved = new.assign(released_at=new["filed_at"])                                # round 1's behaviour
                    round1.upsert_results(moved[["symbol", "period_end", "released_at"]])
        assert _s1_input_bytes(before) == _s1_input_bytes(after)
        with after.reader() as con:
            filed = dict(con.execute("SELECT symbol, strftime(filed_at, '%H:%M:%S') FROM nse_results "
                                     "WHERE period_end = DATE '2026-09-30' ORDER BY symbol").fetchall())
            src = dict(con.execute("SELECT symbol, filed_source FROM nse_results WHERE period_end = DATE '2026-09-30'").fetchall())
        assert filed == {"MOTHERSON": "14:58:36", "TITAN": "16:01:00"} and src == {"MOTHERSON": "announcement", "TITAN": "announcement"}
        # ERN / DES (display only) read the filing time; a DB without the column keeps the feed's
        ern = rh.display_releases(after, "MOTHERSON").set_index("period_end")["released_at"]
        assert pd.Timestamp(ern[pd.Timestamp("2026-09-30")]) == pd.Timestamp("2026-11-05 14:58:36")
        ern_old = rh.display_releases(before, "MOTHERSON").set_index("period_end")["released_at"]
        assert pd.Timestamp(ern_old[pd.Timestamp("2026-09-30")]) == pd.Timestamp("2026-11-05 20:34:10")
        # negative control: round 1 (filing time written into released_at) changes the S1 input, and the check sees it
        assert _s1_input_bytes(round1) != _s1_input_bytes(before)
    finally:
        for s in (before, after, round1):
            s.close()


def test_filed_at_only_moves_earlier_and_never_touches_released_at():
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE nse_results (symbol VARCHAR, period_end DATE, released_at TIMESTAMP, PRIMARY KEY (symbol, period_end))")
    con.execute("INSERT INTO nse_results VALUES ('X', '2026-09-30', '2026-11-05 20:34:00')")
    row = {"symbol": "X", "period_end": datetime(2026, 9, 30).date(), "released_at": datetime(2026, 11, 5, 20, 34)}
    rh.write_filed_times(con, pd.DataFrame([{**row, "filed_at": datetime(2026, 11, 5, 14, 58), "filed_source": "announcement"}]))
    rh.write_filed_times(con, pd.DataFrame([{**row, "filed_at": datetime(2026, 11, 5, 20, 34), "filed_source": "feed"}]))  # later
    assert con.execute("SELECT strftime(released_at, '%H:%M'), strftime(filed_at, '%H:%M'), filed_source FROM nse_results").fetchone() \
        == ("20:34", "14:58", "announcement")
    # a row the store does not hold is not created (released_at is the store's to write)
    rh.write_filed_times(con, pd.DataFrame([{**row, "symbol": "NEW", "filed_at": datetime(2026, 11, 5, 9, 0), "filed_source": "feed"}]))
    assert con.execute("SELECT COUNT(*) FROM nse_results").fetchone()[0] == 1


def _reacting_db(with_filed: bool):
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE nse_results (symbol VARCHAR, period_end DATE, released_at TIMESTAMP)")
    con.execute("CREATE TABLE nse_bhavcopy (symbol VARCHAR, series VARCHAR, date DATE, close DOUBLE, turnover_lacs DOUBLE)")
    con.execute("CREATE TABLE market_index_daily (symbol VARCHAR, date DATE, close DOUBLE)")
    days = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=1), periods=30)
    for i, d in enumerate(days):
        c = 100.0 if i < 27 else (95.0 if i == 27 else 96.0)       # −5% on days[27] (the filing's session), +1% the next
        con.execute("INSERT INTO nse_bhavcopy VALUES ('M', 'EQ', ?, ?, 1000)", [d.date(), c])
        con.execute("INSERT INTO market_index_daily VALUES ('NIFTY50', ?, 1000)", [d.date()])
    con.execute("INSERT INTO nse_results VALUES ('M', '2026-09-30', ?)", [days[27] + pd.Timedelta(hours=20, minutes=34)])
    if with_filed:
        rh.write_filed_times(con, pd.DataFrame([{"symbol": "M", "period_end": datetime(2026, 9, 30).date(), "released_at": None,
                                                 "filed_at": days[27] + pd.Timedelta(hours=14, minutes=58), "filed_source": "announcement"}]))
    return con, days


def test_evts_reads_the_filing_time_and_falls_back_to_the_feed():
    con, days = _reacting_db(with_filed=True)
    r = rh.recent_reactions(con, days=30)[0]
    assert r["timing"] == "market hours" and r["reaction_date"] == days[27].strftime("%Y-%m-%d")    # scored on its own session
    assert r["move_pct"] == pytest.approx(-5.0) and r["time_source"] == "filing" and r["released_at"].endswith("14:58")
    assert r["feed_released_at"].endswith("20:34")
    assert rh.typical_moves(con, ["M"])["M"]["avg_abs_move_pct"] == pytest.approx(5.0)
    # negative control: no filed_at column (an older DB) → the feed time, the next session
    con2, _ = _reacting_db(with_filed=False)
    r2 = rh.recent_reactions(con2, days=30)[0]
    assert r2["timing"] == "after close" and r2["reaction_date"] == days[28].strftime("%Y-%m-%d") and r2["time_source"] == "feed"


def test_two_filings_at_the_same_second_do_not_crash_the_whole_job() -> None:
    """A live crash, 13 Nov 2026 15:15 and 17:15 IST: `nse_results` died with

        TypeError: '<' not supported between instances of 'NoneType' and 'datetime.date'

    `results_announcements` returned `sorted(out)` over `(filed_at, Optional[date])` tuples, so when one
    company filed twice in the SAME second — NSE does produce this — Python fell through to comparing the
    second element and hit a date against None. It killed the entire job rather than the one symbol, because
    `results_filings_by_day` builds every symbol inside a single comprehension, so one bad pair took the
    results data for every company with it. EVTS and the results-reaction panels read that table.
    """
    from results_history import results_announcements

    same_second = "14-Nov-2026 15:30:00"
    rows = [
        {"an_dt": same_second, "desc": "Financial Results for the quarter ended 30 September 2026",
         "attchmntText": "Unaudited financial results for the quarter ended 30.09.2026"},
        {"an_dt": same_second, "desc": "Financial Results",
         "attchmntText": "Outcome of board meeting - financial results approved"},
    ]
    out = results_announcements(rows)                      # must not raise
    assert len(out) == 2, out
    assert out[0][0] == out[1][0], "the fixture's whole point is one shared timestamp"
    assert {p for _, p in out} == {None, date(2026, 9, 30)}, out
    # and the order must not depend on the order NSE happened to return the rows in
    assert results_announcements(rows) == results_announcements(list(reversed(rows)))
    # the undated one sorts first, deterministically
    assert out[0][1] is None and out[1][1] is not None, out
