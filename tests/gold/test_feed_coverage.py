"""The US calendar's own coverage window on the data-service side (critics CT-04 / F3, 8 Nov 2026).

`ff_calendar_thisweek.json` is ONE Sunday-to-Saturday week in New York time, and `ff_calendar_nextweek.json` is a 404
(SOURCES.md G19), so the file's week is the hard limit of what GOLD's event panels can show. They ran a now + 7 days
window and said "the whole week, nothing cut off". `ff_week_window` records what the fetched body actually covers so the
page can say where the US calendar ends; `ingest_ff_calendar` returns it beside the row count.

Each rule has a negative control. Offline: a body literal, no fetch.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from gold import db, ingest_macro

# the body Forex Factory actually served on Sun 8 Nov 2026 (its first row is the DST shift at Sun 01 Nov 02:00 EDT),
# trimmed to the rows that matter; `date` carries the publisher's own New York offset
BODY: list[dict[str, Any]] = [
    {"title": "Daylight Saving Time Shift", "country": "USD", "date": "2026-11-01T02:00:00-04:00", "impact": "Holiday"},
    {"title": "ISM Manufacturing PMI", "country": "USD", "date": "2026-11-02T10:00:00-05:00", "impact": "High"},
    {"title": "Unemployment Claims", "country": "USD", "date": "2026-11-05T08:30:00-05:00", "impact": "High"},
    {"title": "Consumer Credit m/m", "country": "USD", "date": "2026-11-06T15:00:00-05:00", "impact": "Low"},
]


def test_ff_week_window_is_the_loaded_new_york_sunday_week() -> None:
    win = ingest_macro.ff_week_window(json.dumps(BODY))
    assert win is not None
    start, end = win
    assert (start.date(), f"{start:%H:%M}") == (date(2026, 11, 1), "00:00")
    assert (end.date(), f"{end:%H:%M}") == (date(2026, 11, 8), "00:00")
    # New York wall clock on both ends, across the DST change: EDT at the start, EST at the end
    assert start.utcoffset() == timedelta(hours=-4) and end.utcoffset() == timedelta(hours=-5)
    # the window is derived from the EARLIEST event, so a body that starts mid-week still names its own Sunday
    mid = ingest_macro.ff_week_window(json.dumps(BODY[2:]))
    assert mid is not None and mid[0].date() == date(2026, 11, 1)


def test_ff_week_window_is_none_without_a_dated_event() -> None:
    """The negative control: nothing is invented from an empty, broken or undated body."""
    assert ingest_macro.ff_week_window("[]") is None
    assert ingest_macro.ff_week_window("not json") is None
    assert ingest_macro.ff_week_window(json.dumps([{"title": "x", "country": "USD"}])) is None
    assert ingest_macro.ff_week_window(json.dumps([{"title": "x", "country": "USD", "date": "soon"}])) is None


def test_the_window_follows_the_body_not_the_calendar_week_of_the_run() -> None:
    """A week that has rolled reports the NEXT Sunday: the page's coverage end moves only when the file does."""
    rolled = [{"title": "Unemployment Claims", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High"}]
    win = ingest_macro.ff_week_window(json.dumps(rolled))
    assert win is not None and (win[0].date(), win[1].date()) == (date(2026, 11, 8), date(2026, 11, 15))
    # and it is NOT the 1–7 Nov week the earlier body carried
    assert win[0].date() != date(2026, 11, 1)


def test_ingest_reports_the_coverage_beside_the_row_count(store: Any) -> None:
    out = ingest_macro.ingest_ff_calendar(store, json.dumps(BODY), now=datetime(2026, 11, 8, 4, 30))  # noqa: DTZ001
    assert out["rows"] >= 4
    assert out["covers_from"].startswith("2026-11-01T00:00") and out["covers_until"].startswith("2026-11-08T00:00")
    stored = db.query_df(store, "SELECT event_date, source FROM gold_events WHERE source = 'forexfactory_thisweek'")
    assert len(stored) >= 4 and str(stored["event_date"].max())[:10] <= "2026-11-07"
    # a body with no dated event stores nothing and claims no coverage
    empty = ingest_macro.ingest_ff_calendar(store, "[]", now=datetime(2026, 11, 8, 4, 30))  # noqa: DTZ001
    assert "covers_until" not in empty


def test_no_next_week_fetch_was_added() -> None:
    """SOURCES.md G19: `ff_calendar_nextweek.json` is a 404 and the terms forbid hammering. The fix is a coverage label,
    never a second fetch."""
    import inspect

    src = inspect.getsource(ingest_macro)
    assert "ff_calendar_thisweek.json" in src and "nextweek" not in src.replace("nextweek.json` is a 404", "")


@pytest.mark.parametrize("hhmm", ["00:30", "10:00", "11:00"])
def test_the_window_does_not_depend_on_when_the_run_happened(store: Any, hhmm: str) -> None:
    """The file had NOT rolled by 00:30 New York on Sun 8 Nov 2026: the coverage comes from the body, never a clock.

    The clock is what the three runs at 10:00 / 10:20 / 11:00 IST differed by, and all three got the same 1-7 Nov body,
    so the ingest must report the same window at any of them. Negative control below: the ROLLED body at the SAME clock
    reports the next week, which is what proves the window follows the file."""
    hh, mm = (int(x) for x in hhmm.split(":"))
    at = datetime(2026, 11, 8, hh, mm)  # noqa: DTZ001
    out = ingest_macro.ingest_ff_calendar(store, json.dumps(BODY), now=at)
    assert out["covers_from"].startswith("2026-11-01T00:00"), out
    assert out["covers_until"].startswith("2026-11-08T00:00"), out
    rolled = [{"title": "Unemployment Claims", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High"}]
    moved = ingest_macro.ingest_ff_calendar(store, json.dumps(rolled), now=at)
    assert moved["covers_until"].startswith("2026-11-15T00:00") and moved["covers_until"] != out["covers_until"]
