"""Commodity lane (final round R5-EVTS): MCX holidays + special sessions (shared/mcx_specs) and the stored
gold_events rows as one EVTS lane — each event once, each row naming its source, context only."""
import asyncio
from datetime import date, timedelta

import routers.markets as mk
from routers.markets import (
    gold_event_lane_rows,
    mcx_holiday_rows,
    mcx_session_rows,
    merge_commodity_rows,
)


def test_mcx_holiday_rows_window_closure_and_source():
    rows = mcx_holiday_rows(date(2026, 11, 1), date(2026, 11, 30))
    by_date = {r["date"]: r for r in rows}
    assert set(by_date) == {"2026-11-10", "2026-11-24"}                     # Diwali-Balipratipada, Guru Nanak
    r = by_date["2026-11-10"]
    assert r["kind"] == "MCX_HOLIDAY" and r["closure"] == "morning"
    assert "morning session closed" in r["what"] and "evening session trades" in r["what"]
    assert r["source"].startswith("shared/mcx_specs")
    assert r["covers_eco_id"] is None            # NSE's HOLIDAY eco row is a different exchange, not a duplicate
    full = mcx_holiday_rows(date(2026, 12, 20), date(2026, 12, 31))
    assert [x["closure"] for x in full] == ["full"] and "closed all day" in full[0]["what"]   # Christmas
    assert mcx_holiday_rows(date(2027, 1, 1), date(2027, 12, 31)) == []     # outside CALENDAR_YEARS: no invented dates


def test_mcx_session_rows_cover_the_eco_session_row():
    rows = mcx_session_rows(date(2026, 11, 1), date(2026, 11, 30))
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2026-11-08" and r["kind"] == "MCX_SESSION" and r["time"] == "14:20"
    assert r["covers_eco_id"] == "SESSION-2026-11-08"        # the eco SESSION diamond is skipped: drawn once
    assert r["circular"] == "MCX/TRD/590/2026"
    assert "14:20–15:30" in r["what"] and "pre-open 14:05–14:19" in r["what"]
    assert "NSE holds its own session" in r["what"]          # NSE's Muhurat the same day: said, not listed twice
    assert mcx_session_rows(date(2026, 12, 1), date(2026, 12, 31)) == []


def test_gold_event_lane_rows_filter_kinds_impact_and_cover():
    events = [
        {"event_date": "2026-11-18", "time_ist": "19:00", "kind": "US_CPI", "name": "CPI y/y", "impact": "High",
         "forecast": "2.4%", "previous": "2.4%", "actual": None},
        {"event_date": "2026-11-18", "time_ist": "19:00", "kind": "US_DATA", "name": "Housing Starts", "impact": "Low",
         "forecast": None, "previous": None, "actual": None},                      # Low impact stays on GOLD (M28)
        {"event_date": "2026-12-10", "time_ist": "00:30", "kind": "FOMC", "name": "Federal Funds Rate", "impact": "High",
         "forecast": "3.75%", "previous": "4.00%", "actual": None},
        {"event_date": "2026-11-18", "time_ist": None, "kind": "treasury", "name": "not a calendar row", "impact": "High"},
        {"event_date": "2027-03-01", "time_ist": "19:00", "kind": "US_NFP", "name": "NFP", "impact": "High"},  # out of window
    ]
    rows = gold_event_lane_rows(events, date(2026, 11, 1), date(2026, 12, 31))
    assert [(r["kind"], r["date"]) for r in rows] == [("US_CPI", "2026-11-18"), ("FED", "2026-12-10")]
    cpi, fed = rows
    assert cpi["covers_eco_id"] == "US-2026-11-18"           # the aggregated eco US row for that day
    assert fed["covers_eco_id"] == "FED-2026-12-10"          # federalreserve.gov serves the same decision on ECO
    assert cpi["forecast"] == "2.4%" and cpi["actual"] is None and cpi["source"].startswith("gold_events")
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_merge_commodity_rows_dedupes_by_id_and_sorts():
    a = [{"id": "X-1", "date": "2026-11-20", "time": "10:00"}, {"id": "X-2", "date": "2026-11-18", "time": None}]
    b = [{"id": "X-1", "date": "2026-11-20", "time": "10:00"}, {"id": "X-3", "date": "2026-11-18", "time": "09:00"}]
    out = merge_commodity_rows(a, b)
    assert [r["id"] for r in out] == ["X-3", "X-2", "X-1"]   # same event never twice; date then time (none last)


def test_endpoint_shape_badges_and_covered_ids(monkeypatch):
    day = (date.today() + timedelta(days=3)).isoformat()  # noqa: DTZ011 — the endpoint's own (local) clock

    async def fake(start, end):
        return [{"event_date": day, "time_ist": "19:00", "kind": "US_CPI", "name": "CPI y/y", "impact": "High",
                 "forecast": "2.4%", "previous": "2.4%", "actual": None}]

    monkeypatch.setattr(mk, "_gold_events_window", fake)
    body = asyncio.run(mk.commodity_calendar(back=7, ahead=30))
    assert body["badges"] == {"calendar": "context"}
    assert "never a call" in body["note"] and body["errors"] is None
    ids = [r["id"] for r in body["rows"]]
    assert len(ids) == len(set(ids))                          # the same event never twice in the lane
    assert f"US-{day}" in body["covers_eco_ids"]
    assert any(r["kind"] == "US_CPI" and r["date"] == day for r in body["rows"])
    # no direction words anywhere in what the lane says (labelling rules bind every commodity surface)
    text = " ".join(str(r.get("what") or "") for r in body["rows"]) + " " + body["note"]
    assert "bullish" not in text.lower() and "bearish" not in text.lower()


def test_endpoint_survives_gold_events_unavailable(monkeypatch):
    from shared import http_client

    async def boom(start, end):
        raise http_client.UpstreamError(status_code=503, detail="down")

    monkeypatch.setattr(mk, "_gold_events_window", boom)
    body = asyncio.run(mk.commodity_calendar(back=7, ahead=366))
    assert body["errors"] == {"us": "gold_events unavailable (503): MCX rows still shown"}
    # MCX constants still serve their rows (window-dependent: today is inside CALENDAR_YEARS until end-2026)
    if date.today().year in body["mcx_calendar_years"]:  # noqa: DTZ011 — the endpoint's own (local) clock
        assert any(r["kind"] == "MCX_HOLIDAY" for r in body["rows"])
