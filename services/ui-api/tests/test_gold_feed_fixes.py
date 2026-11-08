"""GOLD feed-honesty fixes (8 Nov 2026 RCA, lane G-FEED) — every rule with a negative control. Offline: test_gold's
data-service fake, pinned clock and Yahoo fake; no broker, no network, no POST.

CT-03 / F2 / C-DATA-01  a scheduled COT release that has passed with nothing stored is named (`latest.overdue`,
                        `catch_up_note`, `stale`, the chip) while `next_release_*` keeps meaning the next UPCOMING
                        release (API_CONTRACT §2.5, the controller digest).
CT-04 / F3              the US calendar says how far the loaded Forex Factory week reaches (`us_coverage`), and
                        /calendar's freshness comes from that coverage instead of the request clock.
CT-06                   the MCX quadrant tape is read off the picked contract's Breeze daily bars (close × OI) with the
                        master's all-expiry sum beside it, each labelled; a settle cell names which stand-in it holds
                        and an empty cell carries no quality word.
F6                      /fair carries the PICKED contract's own OK/WAIT in the pick's own quotation unit, beside GOLD's
                        (the scored model, the 08:45 call and the accuracy log stay on GOLD 1 kg).
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import routers.gold_preopen as gp  # noqa: E402
from routers import gold  # noqa: E402
from test_gold import DB, NOW, _app, _fake_db, _offline  # noqa: E402,F401 — the autouse fakes (no network) and the app

IST = gp.IST
DEC26 = date(2026, 12, 4)
NOV26 = date(2026, 11, 5)


def at(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


@pytest.fixture
def client() -> Any:
    with TestClient(_app()) as c:
        yield c


# ══ CT-03 / F2 / C-DATA-01: an overdue COT report is named ════════════════════════════════════════════════════════

def test_overdue_cot_reports_names_a_due_report_and_next_stays_upcoming() -> None:
    """The report dated after the stored one whose release instant is past. No grace: between the Saturday 02:00 release
    and the 02:30 fetch the report genuinely is released-and-not-stored."""
    stored = date(2026, 10, 27)
    # one minute before the 03 Nov report's scheduled release: nothing is due (the negative control)
    assert gold.overdue_cot_reports(stored, at(2026, 11, 7, 1, 59)) == []
    for now in (at(2026, 11, 7, 2, 1), at(2026, 11, 8, 10, 17)):
        od = gold.overdue_cot_reports(stored, now)
        assert [(r["report_date"], r["ist"]) for r in od] == [("2026-11-03", "Sat 07 Nov 02:00 IST")]
        # `next_*` is unchanged: it still names a release AFTER now (API_CONTRACT §2.5, the Saturday digest)
        assert gold.next_cot_release(stored, now)["ist"] == "Tue 17 Nov 02:00 IST"
    # a caught-up store owes nothing, and the holiday-shifted 10 Nov release is not due until Tue 17 Nov 02:00 IST
    assert gold.overdue_cot_reports(date(2026, 11, 3), at(2026, 11, 8, 10, 30)) == []
    assert gold.overdue_cot_reports(date(2026, 11, 3), at(2026, 11, 17, 1, 0)) == []
    assert len(gold.overdue_cot_reports(date(2026, 11, 3), at(2026, 11, 17, 2, 30))) == 1
    # two missed weeks are counted, newest last
    two = gold.overdue_cot_reports(stored, at(2026, 11, 17, 2, 30))
    assert [r["report_date"] for r in two] == ["2026-11-03", "2026-11-10"]
    note = gold.cot_overdue_note(two, stored)
    assert note is not None and "2 reports behind" in note and "Tue 10 Nov" in note
    # the note says "was due", never "released": the calendar cannot prove the CFTC published
    one = gold.cot_overdue_note(gold.overdue_cot_reports(stored, at(2026, 11, 8, 10, 17)), stored)
    assert one is not None and "was due Sat 07 Nov 02:00 IST" in one and "released" not in one
    assert gold.cot_overdue_note([], stored) is None


def test_cot_chip_goes_stale_the_moment_a_release_passes_unstored() -> None:
    """The panel chip agrees with `latest.stale` and with /api/data/health instead of reading DELAYED for ~2 more days."""
    rel, now = "2026-10-31T01:00:00+05:30", at(2026, 11, 8, 10, 5)
    # the old rule (9 days since release) — the negative control
    assert gold.freshness(rel, 9.0, "CFTC", now=now)["state"] == "delayed"
    od = gold.overdue_cot_reports(date(2026, 10, 27), now)
    fr = gold.cot_freshness(rel, od, now, "CFTC")
    assert fr["state"] == "stale" and "Tue 03 Nov" in str(fr.get("reason")) and "was due" in str(fr.get("reason"))
    # nothing overdue leaves the ordinary rule alone
    assert gold.cot_freshness(rel, [], now, "CFTC")["state"] == "delayed"


def test_cot_payload_flags_the_due_report_and_keeps_next_upcoming(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's newest report is Tue 20 Oct (released Sat 24 Oct 01:00 IST). At the pinned clock nothing is due; a
    week later the Tue 27 Oct report is due and unstored, and the panel must say so while `next` stays upcoming."""
    body = client.get("/api/gold/cot").json()
    assert body["latest"]["report_date"] == "2026-10-20"
    assert body["latest"]["overdue"] == [] and body["latest"]["stale"] is False
    assert body["latest"]["catch_up_note"] is None and body["freshness"]["state"] == "delayed"

    gold._ttl.clear()
    monkeypatch.setattr(gold, "_now_ist", lambda: at(2026, 11, 1, 10, 0))
    late = client.get("/api/gold/cot").json()
    lat = late["latest"]
    assert [r["report_date"] for r in lat["overdue"]] == ["2026-10-27"]
    assert lat["overdue_report_date"] == "2026-10-27" and lat["overdue_release_ist"] == "Sat 31 Oct 01:00 IST"
    # the OLD rule would still say stale False here: 8.4 days since release, under STALE_COT_DAYS = 10
    assert (lat["age_days"] or 0) < gold.STALE_COT_DAYS
    assert lat["stale"] is True and late["freshness"]["state"] == "stale"
    assert "was due Sat 31 Oct 01:00 IST" in str(lat["catch_up_note"])
    # `next_release_*` is still an UPCOMING release (the contract, the test at test_gold.py and the Saturday digest)
    assert lat["next_release_at"] > at(2026, 11, 1, 10, 0).isoformat()


# ══ CT-04 / F3: what the US calendar covers ═══════════════════════════════════════════════════════════════════════

def _ff(day: str, time_ist: str = "19:00", name: str = "Unemployment Claims") -> dict[str, Any]:
    return {"event_date": day, "time_ist": time_ist, "kind": "US_CLAIMS", "name": name, "country": "USD",
            "impact": "High", "source": "forexfactory_thisweek"}


# the week Forex Factory actually served on Sun 8 Nov 2026 (Sun 01 → Sat 07 Nov, New York)
WEEK_1_7_NOV = [_ff(f"2026-11-0{d}") for d in (2, 3, 4, 5, 6)] + [_ff("2026-11-07", "01:30", "Consumer Credit m/m")]


def test_us_calendar_coverage_names_the_loaded_week_and_what_it_cannot_cover() -> None:
    cov = gold.us_calendar_coverage(WEEK_1_7_NOV, at(2026, 11, 8, 10, 5), 7)
    assert cov["state"] == "stale"                     # the window is entirely past the loaded week
    assert cov["covers_through_label"] == "Sat 07 Nov"
    assert cov["uncovered"] == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    assert "US releases loaded through Sat 07 Nov" in str(cov["note"]) and "Mon 09 – Fri 13 Nov" in str(cov["note"])
    assert "BLS" in str(cov["note"])
    # the roll is NOT assumed: no clock time is promised, only the hourly check window
    assert "10:30 IST" not in str(cov["note"]) and "checked hourly 09:00–23:00 IST" in str(cov["note"])

    # the week after it rolled: the whole 7-day window fits inside the loaded week → live, no note (negative control)
    rolled = [_ff(f"2026-11-{d}") for d in (9, 10, 11, 12, 13)]
    fresh = gold.us_calendar_coverage(rolled, at(2026, 11, 9, 10, 0), 7)
    assert fresh["state"] == "live" and fresh["uncovered"] == [] and fresh["note"] is None
    assert fresh["covers_through_label"] == "Sat 14 Nov"

    # mid-week the window always reaches into the next US week; ≥ 3 uncovered weekdays is amber, 1–2 only dim
    thu = gold.us_calendar_coverage(rolled, at(2026, 11, 12, 19, 0), 7)
    assert thu["state"] == "stale" and thu["uncovered"][0] == "2026-11-16"
    tue = gold.us_calendar_coverage(rolled, at(2026, 11, 10, 19, 0), 8)
    assert tue["state"] == "delayed" and tue["uncovered"] == ["2026-11-16", "2026-11-17"]
    # no Forex Factory row at all is 'unavailable' — never 'live' and never a quiet week
    empty = gold.us_calendar_coverage([{"event_date": "2026-11-10", "kind": "MCX_HOLIDAY", "source": "mcx_specs"}],
                                      at(2026, 11, 8, 10, 5), 7)
    assert empty["state"] == "unavailable" and "empty, not quiet" in str(empty["note"])


def test_coverage_checked_at_and_freshness_as_of_are_never_in_the_future() -> None:
    """Round 2 (checker): `freshness.as_of` was built from `covers_until`, the Sunday that ENDS the loaded week — an
    instant in the FUTURE on every normal week, so a chip read 'as of 15 Nov' on Mon 09 Nov while `age_s` stayed 0.
    The honest value is the last CHECK of the file; the week's end is `covers_through_label` / `reason`."""
    rolled = [_ff(f"2026-11-{d}") for d in (9, 10, 11, 12, 13)]
    seen = [{**r, "first_seen_at": "2026-11-08T07:30:00+00:00"} for r in rolled]      # the 13:00 IST hourly run
    now = at(2026, 11, 9, 10, 0)
    cov = gold.us_calendar_coverage(seen, now, 7)
    assert cov["checked_at"] == "2026-11-08T13:00:00+05:30"
    assert "first_seen_at" in str(cov["checked_at_source"])                            # the stamp is named, not trusted
    fr = gold.freshness(cov["checked_at"], None, "x", now=now)
    assert fr["as_of"] <= now.isoformat() and fr["age_s"] == 75600                      # 21 h, not 0
    # the negative control: the week's end IS in the future, which is exactly what must not be used as `as_of`
    assert str(cov["covers_until"]) > now.isoformat()
    assert gold.freshness(cov["covers_until"], None, "x", now=now)["age_s"] == 0
    # an explicit store value wins over the derived stamp, and is named as such
    told = gold.us_calendar_coverage(seen, now, 7, checked_at="2026-11-09T09:00:00+05:30")
    assert told["checked_at"] == "2026-11-09T09:00:00+05:30" and "calendar_us.last_fetch" in str(told["checked_at_source"])
    # with no stamp at all nothing is invented
    assert gold.us_calendar_coverage(rolled, now, 7)["checked_at"] is None


def test_calendar_route_as_of_is_the_last_check_on_a_rolled_week(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The route half of the rule above, on the week the feed actually serves today (Sun 08 → Sat 14 Nov)."""
    rows = [{**_ff(f"2026-11-{d}"), "first_seen_at": "2026-11-08T07:30:00+00:00"} for d in (9, 10, 11, 12, 13)]

    async def db(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/events":
            lo, hi = str(params.get("from")), str(params.get("to"))
            return {"rows": [r for r in rows if lo <= r["event_date"] <= hi]}
        return await _fake_db(path, params)

    monkeypatch.setattr(gold, "_db_fetch", db)
    monkeypatch.setattr(gold, "_now_ist", lambda: at(2026, 11, 9, 10, 0))
    gold.STORE.invalidate()
    body = client.get("/api/gold/calendar", params={"days": 7}).json()
    fr, cov = body["freshness"], body["us_coverage"]
    assert cov["state"] == "live" and cov["covers_through_label"] == "Sat 14 Nov"
    # the whole point: an 'as of' the viewer reads is never later than now, and the age is the real one
    assert fr["as_of"] == "2026-11-08T13:00:00+05:30" and fr["as_of"] < body["as_of"] and fr["age_s"] == 75600
    assert "last check of the Forex Factory week file" in str(fr["source"])
    assert "US releases loaded through Sat 14 Nov" in str(fr["reason"])
    # negative control: the week's end is where the OLD code read `as_of`, and it is in the future
    assert str(cov["covers_until"]) > str(body["as_of"]) and fr["as_of"] != cov["covers_until"]


def test_coverage_reads_the_new_york_week_from_the_instant_not_the_ist_date() -> None:
    """A 01:30 IST row is the PREVIOUS New York afternoon: the Sat 07 Nov 01:30 IST Consumer Credit print is Fri 06 Nov
    15:00 ET, so it must not push the loaded week to the one starting Sun 08 Nov."""
    assert gold._ff_instant_ny(_ff("2026-11-07", "01:30")) == date(2026, 11, 6)
    assert gold._ff_instant_ny(_ff("2026-11-06", "19:00")) == date(2026, 11, 6)
    cov = gold.us_calendar_coverage([_ff("2026-11-07", "01:30")], at(2026, 11, 8, 10, 5), 7)
    assert cov["covers_through_label"] == "Sat 07 Nov"


def test_calendar_route_reports_the_feeds_coverage_not_the_request_clock(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = WEEK_1_7_NOV + [{"event_date": "2026-11-10", "time_ist": None, "kind": "MCX_HOLIDAY",
                            "name": "MCX morning closure", "country": "IN", "source": "mcx_specs"}]

    async def db(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/events":
            lo, hi = str(params.get("from")), str(params.get("to"))
            return {"rows": [r for r in rows if lo <= r["event_date"] <= hi]}
        return await _fake_db(path, params)

    monkeypatch.setattr(gold, "_db_fetch", db)
    monkeypatch.setattr(gold, "_now_ist", lambda: at(2026, 11, 8, 10, 5))
    gold.STORE.invalidate()
    body = client.get("/api/gold/calendar", params={"days": 7}).json()
    cov = body["us_coverage"]
    # the loaded week is only findable because the route now reads BACK as well as forward (every FF row is before today)
    assert cov["covers_through_label"] == "Sat 07 Nov" and cov["state"] == "stale"
    # the OLD freshness was {state: 'live', age_s: 0} on exactly this payload; now the state is the feed's own grade
    # and the reason names the days it cannot cover. `as_of` is the LAST CHECK (these fixture rows carry no
    # `first_seen_at`, so it falls back to the request clock) and NEVER the week's end — see the test below.
    assert body["freshness"]["state"] == "stale"
    assert "Mon 09 – Fri 13 Nov" in str(body["freshness"]["reason"])
    assert body["freshness"]["covers_through"] == "Sat 07 Nov"
    assert str(body["freshness"]["as_of"]) <= at(2026, 11, 8, 10, 5).isoformat()
    # the back-read never leaks a past row into the printed list
    assert body["events"] and all(e["event_date"] >= "2026-11-08" for e in body["events"])


# ══ CT-06: the MCX tape reads the better source ═══════════════════════════════════════════════════════════════════

# The GOLDM sessions of the finding, copied verbatim from `GET :8001/db/gold/curve/history?exchange=MCX&symbol=GOLDM`
# on 8 Nov 2026 (data-service's own wave-1d re-keyed shape: `settle` IS the settlement of `settle_session`,
# `band_midpoint` the raw band of `band_session`). NOV-26 expires on the 05th and leaves the master before its band is
# published, which is where the permanent 04 Nov hole came from; the all-expiry ΔOI sums are −9,871 / −4,356 / +1,476.
def _m(td: str, exp: str, settle: float | None, oi: int, doi: float, span: int, band_mid: float, band_sess: str) -> dict[str, Any]:
    return {"trade_date": td, "symbol": "GOLDM", "expiry": exp, "settle": settle, "open_interest": oi, "oi_change": doi,
            "sessions_spanned": span, "source": "icici_master_band", "quality": "proxy",
            "band_midpoint": band_mid, "band_session": band_sess,
            "settle_source": "band_midpoint" if settle is not None else None,
            "settle_quality": "band_proxy" if settle is not None else None,
            "settle_session": td if settle is not None else None, "settle_vwap30": None, "settle_band": settle}


MASTER_GOLDM = [
    _m("2026-11-03", "2026-11-05", 137966.0, 7777, -22119.0, 3, 138498.0, "2026-11-02"),
    _m("2026-11-03", "2026-12-04", 139483.0, 41281, 9389.0, 3, 140234.0, "2026-11-02"),
    _m("2026-11-03", "2027-01-05", 140970.0, 8069, 2052.0, 3, 141732.0, "2026-11-02"),
    _m("2026-11-03", "2027-02-05", 142371.0, 3146, 453.0, 3, 143000.0, "2026-11-02"),
    _m("2026-11-03", "2027-03-05", 143930.0, 774, 166.0, 3, 144445.0, "2026-11-02"),
    _m("2026-11-03", "2027-04-05", 145139.0, 360, 188.0, 3, 145816.0, "2026-11-02"),
    _m("2026-11-04", "2026-11-05", None, 1421, -6356.0, 1, 137966.0, "2026-11-03"),
    _m("2026-11-04", "2026-12-04", 143268.0, 42786, 1505.0, 1, 139483.0, "2026-11-03"),
    _m("2026-11-04", "2027-01-05", 144801.0, 8550, 481.0, 1, 140970.0, "2026-11-03"),
    _m("2026-11-04", "2027-02-05", 146216.0, 3106, -40.0, 1, 142371.0, "2026-11-03"),
    _m("2026-11-04", "2027-03-05", 147756.0, 835, 61.0, 1, 143930.0, "2026-11-03"),
    _m("2026-11-04", "2027-04-05", 149006.0, 353, -7.0, 1, 145139.0, "2026-11-03"),
    _m("2026-11-05", "2026-12-04", None, 44067, 1281.0, 1, 143268.0, "2026-11-04"),
    _m("2026-11-05", "2027-01-05", None, 8625, 75.0, 1, 144801.0, "2026-11-04"),
    _m("2026-11-05", "2027-02-05", None, 3135, 29.0, 1, 146216.0, "2026-11-04"),
    _m("2026-11-05", "2027-03-05", None, 855, 20.0, 1, 147756.0, "2026-11-04"),
    _m("2026-11-05", "2027-04-05", None, 424, 71.0, 1, 149006.0, "2026-11-04"),
]
BREEZE_GOLDM = [
    {"trade_date": d, "family": "GOLDM", "expiry": "2026-12-04", "close": c, "open_interest": oi, "volume": None,
     "source": "breeze_daily", "quality": "broker"}
    for d, c, oi in (
        ("2026-10-29", 142308.0, 31892), ("2026-10-30", 138550.0, 34827), ("2026-11-02", 140268.0, 39054),
        ("2026-11-03", 139483.0, 41281), ("2026-11-04", 143250.0, 42786), ("2026-11-05", 143950.0, 44067),
    )
]
TODAY = date(2026, 11, 8)


def _tape(p: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["trade_date"]: t for t in p["quadrant_tape"]}


def test_mcx_tape_reads_the_picked_contracts_breeze_bars_and_names_its_scope() -> None:
    p = gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=BREEZE_GOLDM, breeze_published=True)
    t = _tape(p)
    assert p["tape_source"] == "breeze_daily+icici_master"
    assert p["tape_oi_scope"] == "GOLDM DEC-26" and p["tape_expiry"] == "2026-12-04"
    # the word the traded contract earns on every session (the master gave none at all here)
    assert (t["2026-11-03"]["label"], t["2026-11-03"]["dprice_pct"], t["2026-11-03"]["doi"]) == ("short build-up", -0.56, 2227)
    assert (t["2026-11-04"]["label"], t["2026-11-04"]["dprice_pct"], t["2026-11-04"]["doi"]) == ("long build-up", 2.7, 1505)
    assert (t["2026-11-05"]["label"], t["2026-11-05"]["dprice_pct"], t["2026-11-05"]["doi"]) == ("long build-up", 0.49, 1281)
    assert all(t[d]["oi_source"] == "breeze_daily" and t[d]["price_source"] == "breeze_close" for d in ("2026-11-03", "2026-11-05"))
    # the master's all-expiry sum stays beside it, flagged while an expiring month is running off
    assert t["2026-11-03"]["doi_family"] == -9871 and t["2026-11-03"]["family_mechanical"] is True
    assert t["2026-11-04"]["doi_family"] == -4356 and t["2026-11-04"]["family_mechanical"] is True
    assert t["2026-11-05"]["doi_family"] == 1476 and t["2026-11-05"]["family_mechanical"] is False
    assert "Breeze daily bars" in str(p["tape_note"])


def test_mcx_tape_falls_back_to_the_master_when_breeze_daily_is_not_published() -> None:
    """PLAN §f.2: no PUBLISH verdict, no number. The master's own read is unchanged except for the expiry hole."""
    p = gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=BREEZE_GOLDM, breeze_published=False)
    t = _tape(p)
    assert p["tape_source"] == "icici_master" and p["tape_oi_scope"] == "all GOLDM expiries"
    # 03 Nov still has no word: the price and the OI deltas span different numbers of sessions
    assert t["2026-11-03"]["label"] is None and "span different sessions" in str(t["2026-11-03"]["note"])
    assert all(r["settle_source"] != "breeze_close" for r in p["rows"])
    # and the permanent expiry hole is gone: 04 Nov prices off DEC's band, not the NOV contract that is expiring
    assert t["2026-11-04"]["dprice_pct"] == 2.71 and t["2026-11-04"]["price_contract"] == "GOLDM DEC-26"


def test_a_master_filled_tape_session_never_passes_the_family_sum_off_as_the_contracts() -> None:
    """Round 2 (checker): `gold_breeze_daily` is a 09:35 SESSION job, so a session with no Breeze bar is normal. The
    master row that fills it carries the ALL-EXPIRY sum, and it used to be written into `doi` while the payload's one
    scope still said 'GOLDM DEC-26' — so WEEKLY printed the same −9,871 under a per-contract header and again under the
    family one. The filled session now carries no per-contract ΔOI and no quadrant word at all."""
    gap = [r for r in BREEZE_GOLDM if r["trade_date"] != "2026-11-03"]
    p = gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=gap, breeze_published=True)
    t = _tape(p)
    row = t["2026-11-03"]
    assert row["oi_source"] == "icici_master" and row["fill"] == "icici_master"
    assert row["doi"] is None and row["label"] is None and row["oi_scope"] is None
    assert row["doi_family"] == -9871 and row["family_mechanical"] is True
    assert "no Breeze bar for this session" in str(row["note"])
    # the two scopes are each named by the server, and the fill is counted and said
    assert p["tape_oi_scope"] == "GOLDM DEC-26" and p["tape_family_scope"] == "all GOLDM expiries"
    assert p["tape_fill_sessions"] == 1 and "no per-contract ΔOI" in str(p["tape_fill_note"])
    # NO filled row anywhere presents the family sum as the picked contract's, and the two columns never print one
    # number twice (PLAN §f.6)
    for r in p["quadrant_tape"]:
        assert not (r.get("fill") and r.get("doi") is not None)
        assert r.get("doi") is None or r.get("doi_family") is None or r["doi"] != r["doi_family"]
    # negative control: the full Breeze store fills nothing, and 03 Nov is the traded contract's own +2,227 short
    # build-up — the opposite sign to the family sum beside it
    full = _tape(gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=BREEZE_GOLDM, breeze_published=True))
    assert full["2026-11-03"]["doi"] == 2227 and full["2026-11-03"]["doi_family"] == -9871
    assert full["2026-11-03"]["fill"] is None and full["2026-11-03"]["label"] == "short build-up"


def test_the_tapes_own_range_is_stated_apart_from_the_oi_ladders() -> None:
    """PLAN §f.6: the ladder's `since` is the day the 07:35 master job started; the tape reads the Breeze bars, which
    reach further back. One printed range cannot describe both."""
    p = gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=BREEZE_GOLDM, breeze_published=True)
    # a real difference on this fixture: the Breeze bars reach back to 29 Oct, so the tape's first Δ is one session
    # before the ladder's oldest row (29 Oct, its first bar) — and, on the live GOLDM store, months before it (2026-08-13 vs 2026-10-28)
    assert p["tape_since"] == "2026-10-29" and p["since"] == "2026-11-02" and p["tape_since"] < p["since"]
    # negative control: with no Breeze bars the tape IS the ladder's own sessions, so the two ranges agree and the UI
    # prints one range (`tapeSinceLabel` returns null)
    master_only = gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=[], breeze_published=False)
    assert master_only["tape_since"] == master_only["since"] == "2026-11-02"


def test_mcx_settle_cell_names_its_stand_in_and_an_empty_cell_has_no_quality_word() -> None:
    p = gold.build_positioning_mcx(MASTER_GOLDM, TODAY, "GOLDM", [], breeze_rows=BREEZE_GOLDM, breeze_published=True)
    by = {(r["trade_date"], r["expiry"]): r for r in p["rows"]}
    dec05 = by[("2026-11-05", "2026-12-04")]
    assert dec05["settle_or_close"] == 143950.0 and dec05["settle_source"] == "breeze_close" and dec05["quality"] == "broker"
    assert "not the settlement" in str(dec05["settle_note"])
    # JAN-27 has no band and no Breeze bar: an empty cell carries no value AND no quality word ('— PROXY' before)
    jan = by[("2026-11-05", "2027-01-05")]
    assert jan["settle_or_close"] is None and jan["quality"] is None
    # the band's own session keeps its own label
    assert by[("2026-11-04", "2026-12-04")]["settle_source"] == "band_midpoint"


def test_positioning_daily_route_asks_for_the_breeze_bars_and_the_catalog(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    async def db(path: str, params: dict[str, Any]) -> Any:
        seen.append((path, dict(params)))
        if path == "/db/gold/curve/history":
            return {"rows": MASTER_GOLDM}
        if path == "/db/gold/mcx/daily":
            return {"rows": BREEZE_GOLDM}
        return await _fake_db(path, params)

    monkeypatch.setattr(gold, "_db_fetch", db)
    gold.STORE.invalidate()
    body = client.get("/api/gold/positioning/daily", params={"exchange": "MCX", "family": "GOLDM"}).json()
    assert any(p == "/db/gold/mcx/daily" and q.get("family") == "GOLDM" for p, q in seen)
    assert body["tape_source"] == "breeze_daily+icici_master" and body["tape_oi_scope"] == "GOLDM DEC-26"
    assert _tape(body)["2026-11-05"]["label"] == "long build-up"


# ══ F6: the picked contract's own verdict ═════════════════════════════════════════════════════════════════════════

def test_contract_chase_limit_scales_with_the_quotation_unit() -> None:
    """₹300 is the house rule per 10 g; PETAL is quoted per 1 g and GUINEA per 8 g."""
    assert gold.contract_chase_limit("GOLD") == 300.0
    assert gold.contract_chase_limit("GOLDM") == 300.0
    assert gold.contract_chase_limit("GOLDTEN") == 300.0
    assert gold.contract_chase_limit("GOLDPETAL") == 30.0
    assert gold.contract_chase_limit("GOLDGUINEA") == 240.0
    assert gold.contract_chase_limit("GOLDPETAL", 600.0) == 60.0


def test_contract_fair_verdict_prices_the_pick_not_gold_1kg() -> None:
    ten = {"contract": "GOLDTEN", "expiry": "2026-11-30", "fair_value": 142476.0, "quote_unit": "₹ per 10 g"}
    # a GOLDTEN price sitting exactly on GOLDTEN's fair: OK. GOLD's own rule called the same price WAIT +₹413.
    v = gold.contract_fair_verdict(ten, 142476.0, 300.0)
    assert v is not None and v["state"] == "OK" and v["diff"] == 0 and v["badge"] == gold.BADGE_HEURISTIC
    assert "GOLDTEN" in v["detail"] and v["threshold"] == 300.0
    assert gp._verdict_body(142063.0, 142476.0, 300.0, True)["state"] == "WAIT"   # the negative control (GOLD 1 kg)
    # ₹ per 1 g: the typed price is compared with the pick's own fair and its own ₹30 limit, not a ₹-per-10-g number
    petal = {"contract": "GOLDPETAL", "expiry": "2026-11-30", "fair_value": 14296.0, "quote_unit": "₹ per 1 g"}
    pv = gold.contract_fair_verdict(petal, 14400.0, 300.0)
    assert pv is not None and pv["state"] == "WAIT" and pv["diff"] == 104 and pv["threshold"] == 30.0
    assert gold.contract_fair_verdict(petal, 14300.0, 300.0)["state"] == "OK"
    # no price at all asks for one in the pick's unit; no fair value gives no verdict
    nd = gold.contract_fair_verdict(petal, None, 300.0)
    assert nd is not None and nd["state"] == "NEED_PRICE" and "₹ per 1 g" in nd["detail"]
    assert gold.contract_fair_verdict({"contract": "GOLDM", "fair_value": None}, 1.0) is None


def test_fair_route_carries_the_picks_verdict_beside_golds(client: Any) -> None:
    base = client.get("/api/gold/fair", params={"contract": "GOLDTEN"}).json()
    cf = base["contract_fair"]
    assert cf["contract"] == "GOLDTEN" and cf["model_contract"] == "GOLD"
    assert "accuracy log run on GOLD 1 kg" in cf["model_note"]
    px = cf["fair_value"]
    assert px, "the fixture's Yahoo fake must produce a fair value for the pick"
    body = client.get("/api/gold/fair", params={"contract": "GOLDTEN", "mcx_price": px}).json()
    assert body["contract_fair"]["verdict"]["state"] == "OK" and body["contract_fair"]["verdict"]["diff"] == 0
    # GOLD's verdict is untouched (the 08:45 snapshot and the accuracy log score it) and is the one that disagrees
    assert body["verdict"]["badge"] == gold.BADGE_HEURISTIC
    # GOLD's own model prices 1 kg (₹ / 10 g of GOLD), the pick 10 g of GOLDTEN: the two fair values are not the same
    # number, which is why one verdict could not serve both (the OLD behaviour returned WAIT +413 on this very price)
    assert body["model"]["fair_open"] != px
    # GOLD itself gets no second verdict block
    assert "contract_fair" not in client.get("/api/gold/fair").json()


def test_gold_feed_fixtures_are_offline() -> None:
    """No test here reaches a broker or the network: every read is served from this module's DB fixture.

    Asserted, not asserted-about-constants: this module imports no HTTP client, and every store path the lane's routes
    read is a key of DB, so a route that reached past the fixture would KeyError rather than fetch."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(sys.modules[__name__]))
    imported = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])  # type: ignore[list-item]
        if a is not None or isinstance(n, ast.ImportFrom)
    }
    assert not imported & {"httpx", "requests", "urllib", "breeze_connect", "socket"}, sorted(imported)
    for path in ("/db/gold/mcx/daily", "/db/gold/catalog", "/db/gold/events"):
        assert path in DB, path
    assert all(r["source"] == "breeze_daily" for r in BREEZE_GOLDM)
