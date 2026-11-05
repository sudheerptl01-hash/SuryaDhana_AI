import json
from datetime import date
from pathlib import Path

from routers.markets import build_eco_calendar

REF = {"releases": [{"date": "2026-09-12", "kind": "CPI", "what": "CPI inflation · Aug 2026", "time": "16:00"},   # a Saturday
                    {"date": "2026-10-12", "kind": "CPI", "what": "CPI inflation · Sep 2026", "time": "16:00"}],
       "monthly_rules": [{"day": 14, "kind": "WPI", "what": "Wholesale inflation (WPI)", "time": "12:00", "source": "DPIIT"}],
       "valid_until": "2027-03-31"}


def test_weekend_release_moves_to_monday():
    ev = build_eco_calendar(REF, [], [], date(2026, 9, 1), date(2026, 9, 30))
    cpi = next(e for e in ev if e["kind"] == "CPI")
    assert cpi["date"] == "2026-09-14" and cpi["moved"]            # MoSPI did release Aug CPI on Mon 14 Sep


def test_fixed_day_rule_names_the_previous_month_and_stops_at_validity():
    ev = build_eco_calendar(REF, [], [], date(2026, 10, 1), date(2026, 10, 31))
    wpi = next(e for e in ev if e["kind"] == "WPI")
    assert wpi["date"] == "2026-10-14" and wpi["what"].endswith("Sep 2026") and not wpi["moved"]
    later = build_eco_calendar(REF, [], [], date(2027, 4, 1), date(2027, 5, 31))
    assert not [e for e in later if e["kind"] == "WPI"]           # past the calendar's year: no invented dates


def test_policy_decisions_and_fed_time_in_ist():
    rbi = [{"start": "2026-12-02", "end": "2026-12-04"}]
    fed = [{"start": "2026-10-27", "end": "2026-10-28", "projections": False},     # US summer time: same evening IST
           {"start": "2026-12-08", "end": "2026-12-09", "projections": True}]       # winter: 00:30 IST next day
    ev = build_eco_calendar(REF, rbi, fed, date(2026, 10, 1), date(2026, 12, 31))
    kinds = [(e["kind"], e["date"], e["time"]) for e in ev if e["kind"] in ("RBI", "FED")]
    assert kinds == [("FED", "2026-10-28", "23:30"), ("RBI", "2026-12-04", "10:00"), ("FED", "2026-12-10", "00:30")]
    assert [e["date"] for e in ev] == sorted(e["date"] for e in ev)


def test_reference_file_is_well_formed():
    ref = json.loads((Path(__file__).resolve().parents[3] / "data" / "reference" / "india_data_calendar.json").read_text())
    ev = build_eco_calendar(ref, [], [], date(2026, 10, 1), date(2026, 11, 30))
    got = {(e["kind"], e["date"]) for e in ev}
    assert {("CPI", "2026-10-12"), ("IIP", "2026-10-28"), ("GDP", "2026-11-30"), ("WPI", "2026-10-14"), ("CORE", "2026-10-20")} <= got


def test_market_holidays_are_listed_not_used_to_move_releases():
    hol = [{"date": "2026-10-20", "weekday": "Tue", "description": "Dussehra"}]
    ref = {"releases": [], "monthly_rules": [{"day": 20, "kind": "CORE", "what": "Core industries index", "time": "17:00"}],
           "valid_until": "2027-03-31"}
    ev = build_eco_calendar(ref, [], [], date(2026, 10, 19), date(2026, 10, 21), hol)
    # the closure leads the day (no time); the release keeps its planned date (government calendar, not NSE's)
    assert [(e["kind"], e["date"]) for e in ev] == [("HOLIDAY", "2026-10-20"), ("CORE", "2026-10-20")]
    assert ev[0]["what"] == "NSE closed · Dussehra"
