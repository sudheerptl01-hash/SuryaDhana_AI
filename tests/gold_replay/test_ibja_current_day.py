"""IBJA current-day parse (FINAL ROUND D-CATCH, 13 Nov 2026 — the 18:30 amber-by-design).

The ibjarates.com 'Previous 30 days' tables gain a day's row only the NEXT day, so the 13:45 / 18:10 ingests ran
one session behind forever. The fix reads the populated current-day block (``TodayRatesTableDataYes``, spans
``lblGold999_AM`` …) and dates it from the server-rendered ``HdnGold`` chart anchor — never the fetch clock.
Fixture ``ibjarates_current_day_20261113.html`` is the real page saved 13 Nov 2026 19:25 IST (both fixes up);
the pre-upload state is replayed from the existing G-INDIA capture of 26 Oct (``TodayRatesTableDataNo``)."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention — same note as tests/gold/_support.py)
import re
from datetime import date, datetime

import pandas as pd
from _support import FIXTURES, G_INDIA, read
from gold import ingest_india

LIVE = FIXTURES / "ibjarates_current_day_20261113.html"
NOW_13NOV = datetime(2026, 11, 13, 14, 0)          # UTC-naive (store convention), 19:30 IST on the capture day


def _val(df: pd.DataFrame, sid: str, d: date) -> float:
    return float(df[(df["series_id"] == sid) & (df["report_date"] == d)]["value"].iloc[0])


def test_current_day_rows_parsed_and_server_dated():
    df = ingest_india.parse_ibja_html(read(LIVE), now=NOW_13NOV)
    d = date(2026, 11, 13)
    # today's block, both fixes, all five purities + silver — the numbers printed on the saved page
    assert (_val(df, "IBJA_999_AM", d), _val(df, "IBJA_999_PM", d)) == (135884, 135809)
    assert (_val(df, "IBJA_995_AM", d), _val(df, "IBJA_995_PM", d)) == (135340, 135265)
    assert (_val(df, "IBJA_916_PM", d), _val(df, "IBJA_750_PM", d), _val(df, "IBJA_585_PM", d)) == (124401, 101857, 79448)
    assert (_val(df, "IBJA_SILVER_999_AM", d), _val(df, "IBJA_SILVER_999_PM", d)) == (177500, 178000)
    # the 30-day tables still parse beside it (yesterday's row intact)
    assert (_val(df, "IBJA_999_AM", date(2026, 11, 12)), _val(df, "IBJA_999_PM", date(2026, 11, 12))) == (138294, 137692)
    assert df["series_id"].nunique() == 12 and df["report_date"].max() == d
    # PIT release times: the fix rules, not the fetch clock (13:00 / 18:00 IST = 07:30 / 12:30 UTC)
    am = df[(df["series_id"] == "IBJA_999_AM") & (df["report_date"] == d)].iloc[0]
    pm = df[(df["series_id"] == "IBJA_999_PM") & (df["report_date"] == d)].iloc[0]
    assert (am["release_at"], pm["release_at"]) == (pd.Timestamp("2026-11-13 07:30"), pd.Timestamp("2026-11-13 12:30"))
    # no platinum series was invented
    assert not df["series_id"].str.contains("PLATINUM", case=False).any()


def test_pre_upload_page_adds_no_current_day_row():
    """The 26 Oct 05:42 capture ('Rates will be uploaded soon', table id TodayRatesTableDataNo): behaviour is
    exactly the pre-fix one — 30-day rows only, nothing dated the capture day, nothing from the chart history."""
    df = ingest_india.parse_ibja_html(read(G_INDIA / "s_ibjarates.com_.html"), now=datetime(2026, 10, 26, 5, 0))
    assert df["report_date"].max() == date(2026, 10, 23) and df["series_id"].nunique() == 12
    assert date(2026, 10, 26) not in set(df["report_date"])


def test_anchor_mismatch_yields_no_current_day_row():
    """A stale-served / half-rendered page: today-block values that the HdnGold anchor does not vouch for are
    dropped entirely rather than guessed a date for."""
    html = read(LIVE).replace('<span id="lblGold999_PM">135809</span>', '<span id="lblGold999_PM">999999</span>')
    df = ingest_india.parse_ibja_html(html, now=NOW_13NOV)
    assert df[df["report_date"] == date(2026, 11, 13)].empty          # anchor 999999 ≠ chart's 135809 → no row
    assert _val(df, "IBJA_999_AM", date(2026, 11, 12)) == 138294      # the 30-day tables are untouched


def test_missing_chart_input_yields_no_current_day_row():
    html = re.sub(r'id="HdnGold" value="[^"]*"', 'id="HdnGold" value=""', read(LIVE))
    df = ingest_india.parse_ibja_html(html, now=NOW_13NOV)
    assert df[df["report_date"] == date(2026, 11, 13)].empty


def test_am_only_upload_gates_out_the_pm_spans():
    """At 13:45 only the AM fix exists. HdnRatesAvaliable then lists only '12AM'; any PM value still printed in
    the block (layout quirk, repeated AM figure) must not be stored as a PM fix. The anchor check accordingly
    accepts the AM value when no PM survives the gate."""
    html = read(LIVE)
    m = re.search(r'id="HdnRatesAvaliable" value="([^"]*)"', html)
    assert m is not None
    html = html.replace(m.group(1), "[{&quot;ID&quot;:&quot;41126&quot;,&quot;RateTime&quot;:&quot;12AM&quot;}]")
    # make the chart anchor the AM value (as it would be before the PM upload)
    html = html.replace("137692,135809]", "137692,135884]")
    df = ingest_india.parse_ibja_html(html, now=datetime(2026, 11, 13, 8, 30))
    d = date(2026, 11, 13)
    assert _val(df, "IBJA_999_AM", d) == 135884
    assert df[(df["series_id"] == "IBJA_999_PM") & (df["report_date"] == d)].empty
    assert df[(df["series_id"] == "IBJA_SILVER_999_PM") & (df["report_date"] == d)].empty


def test_ingest_roundtrip_is_idempotent(store):
    """Tomorrow the 30-day table carries the same 13 Nov values: the revision-aware upsert stores them once."""
    from gold import ingest_physical

    df = ingest_india.parse_ibja_html(read(LIVE), now=NOW_13NOV)
    first = ingest_physical.ingest_series(store, df, now=NOW_13NOV)
    again = ingest_physical.ingest_series(store, ingest_india.parse_ibja_html(read(LIVE), now=datetime(2026, 11, 14, 14, 0)),
                                          now=datetime(2026, 11, 14, 14, 0))
    assert first["inserted"] == 60 and again["inserted"] == 0 and again["revised"] == 0
