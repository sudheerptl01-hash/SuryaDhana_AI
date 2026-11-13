"""routers/expiry.py — the E-REPLAY read (FINAL ROUND wave E, F-17), each rule with a negative control.

The practice simulator replays RECORDED expiry-day tapes (``iv_expiry_replay``; the PM's after-close job O-T16 fills
the store — never this service). Rules under test:

1. ``GET /api/derivatives/replay`` (list mode) passes the replayed expiries through with an honest REFERENCE chip
   (recorded history is never LIVE and never DELAYED — there is no feed to be behind).
2. Tape mode passes the 1-minute rows through point-in-time (a null print stays a gap) and RE-KEYS them to clock
   times only — no per-row ``ts``/date field survives, so the client's date-hidden mode leaks nothing per print.
3. A store without the replay read (404) degrades to ``ok: false`` with the reason, never a 500.
4. The router stays read-only and never touches the paper book: practice entries exist in the browser only.
5. Labelling rules: badges ``context``/``arithmetic`` only, the copy ends "describes, does not predict", and no
   direction or judgement word appears anywhere in the payload.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import expiry  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(expiry.router, prefix="/api/derivatives")
    return app


@pytest.fixture(autouse=True)
def _fresh_cache():
    expiry._down.clear()
    expiry.TAPE.invalidate()
    yield
    expiry._down.clear()
    expiry.TAPE.invalidate()


# The shape the data-service read serves (patch e-replay/patches/data_service_replay_read.patch); trimmed rows.
LIST_BODY = {
    "symbol": "NIFTY", "n": 3,
    "expiries": [
        {"expiry": "2026-08-26", "rows": 374, "first_ist": "09:15", "last_ist": "15:29", "strike": 24900.0,
         "spot_open": 24903.3, "source": "breeze_1m"},
        {"expiry": "2026-10-27", "rows": 371, "first_ist": "09:15", "last_ist": "15:29", "strike": 25750.0,
         "spot_open": 25742.1, "source": "breeze_1m"},
        {"expiry": "2026-11-03", "rows": 373, "first_ist": "09:15", "last_ist": "15:29", "strike": 25900.0,
         "spot_open": 25891.4, "source": "breeze_1m"},
    ],
}

# One recorded day: the raw store row carries ts/first_seen_at — the read must strip every date-bearing per-row key.
TAPE_BODY = {
    "symbol": "NIFTY", "expiry": "2026-11-03", "strike": 25900.0, "spot_open": 25891.4, "source": "breeze_1m", "n": 4,
    "rows": [
        {"minute": 0, "ist": "09:15", "straddle": 195.6, "ce_close": 101.2, "pe_close": 94.4, "ce_oi": 100.0,
         "pe_oi": 120.0, "ce_volume": 1.0, "pe_volume": 2.0, "ts": "2026-11-03T03:45:00", "first_seen_at": "2026-11-12T18:00:00"},
        {"minute": 60, "ist": "10:15", "straddle": None, "ce_close": None, "pe_close": 71.0, "ce_oi": None,
         "pe_oi": 130.0, "ce_volume": None, "pe_volume": 3.0, "ts": "2026-11-03T04:45:00"},
        {"minute": 180, "ist": "12:15", "straddle": 121.4, "ce_close": 60.2, "pe_close": 61.2, "ce_oi": 140.0,
         "pe_oi": 150.0, "ce_volume": 5.0, "pe_volume": 6.0, "ts": "2026-11-03T06:45:00"},
        {"minute": 374, "ist": "15:29", "straddle": 31.9, "ce_close": 30.1, "pe_close": 1.8, "ce_oi": 90.0,
         "pe_oi": 80.0, "ce_volume": 7.0, "pe_volume": 8.0, "ts": "2026-11-03T09:59:00"},
    ],
}

FORBIDDEN = ("buy", "sell", "bullish", "bearish", "should", "opportunity", "setup", "bias",
             "right side", "wrong side", "signal")


def _strings(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in [*v.keys(), *v.values()] for s in _strings(x)]
    if isinstance(v, (list, tuple)):
        return [s for x in v for s in _strings(x)]
    return []


def _get(monkeypatch, body, url):
    async def fake(path, params):
        return body
    monkeypatch.setattr(expiry, "_fetch", fake)
    r = TestClient(_app()).get(url)
    assert r.status_code == 200
    return r.json()


def test_list_mode_passes_the_replayed_expiries_through_with_a_reference_chip(monkeypatch):
    j = _get(monkeypatch, LIST_BODY, "/api/derivatives/replay?symbol=NIFTY")
    assert j["ok"] is True and j["mode"] == "list" and j["n"] == 3
    assert [e["expiry"] for e in j["expiries"]] == ["2026-08-26", "2026-10-27", "2026-11-03"]
    assert j["expiries"][0]["rows"] == 374 and j["expiries"][0]["strike"] == 24900.0   # point-in-time pass-through
    # recorded history is REFERENCE (never live, never delayed), stamped with the latest replayed expiry
    assert j["chip"]["state"] == "reference" and j["chip"]["as_of"] == "2026-11-03" and j["chip"]["age_s"] is None
    assert "recorded history" in j["chip"]["hint"]
    # labelling: badges context/arithmetic only, the note describes, the practice line keeps entries in the browser
    assert j["badges"] == {"tape": "context", "scoring": "arithmetic"}
    assert j["note"].endswith("describes, does not predict")
    assert "localStorage" in j["practice"] and "never the paper F&O book" in j["practice"] and "never an order" in j["practice"]


def test_an_empty_list_is_offline_with_the_store_note_and_invents_no_as_of(monkeypatch):
    empty = {"symbol": "NIFTY", "expiries": [], "n": 0, "note": "no replay stored yet (the PM's after-close job, O-T16)"}
    j = _get(monkeypatch, empty, "/api/derivatives/replay?symbol=BANKNIFTY")
    assert j["ok"] is True and j["n"] == 0 and j["expiries"] == []
    assert j["chip"]["state"] == "offline" and j["chip"]["as_of"] is None
    assert "no replay stored yet" in j["empty_note"]


def test_tape_mode_is_point_in_time_and_strips_every_date_bearing_row_key(monkeypatch):
    j = _get(monkeypatch, TAPE_BODY, "/api/derivatives/replay?symbol=NIFTY&expiry=2026-11-03")
    assert j["ok"] is True and j["mode"] == "tape" and j["expiry"] == "2026-11-03" and j["n"] == 4
    assert j["strike"] == 25900.0 and j["spot_open"] == 25891.4
    # point-in-time: stored prints pass through exactly; a null print stays a gap, never filled
    assert [r["straddle"] for r in j["rows"]] == [195.6, None, 121.4, 31.9]
    assert j["rows"][1]["ce_close"] is None and j["rows"][1]["pe_close"] == 71.0
    # the date-hidden guarantee: rows carry clock times only — no ts, no date, no first_seen_at survives the shaping
    allowed = set(expiry._REPLAY_ROW_KEYS)
    for r in j["rows"]:
        assert set(r) <= allowed, f"a date-bearing row key leaked: {sorted(set(r) - allowed)}"
    assert j["rows"][0]["ist"] == "09:15" and j["rows"][-1]["minute"] == 374
    # the chip stamps the expiry itself (shown only after the client's reveal)
    assert j["chip"]["state"] == "reference" and j["chip"]["as_of"] == "2026-11-03"


def test_a_store_without_the_replay_read_degrades_honestly_never_a_500(monkeypatch):
    async def fake(path, params):
        raise expiry._Unavailable("data-service does not serve the tape reads yet (404): the W2-TAPE routes are not deployed")
    monkeypatch.setattr(expiry, "_fetch", fake)
    r = TestClient(_app()).get("/api/derivatives/replay?symbol=NIFTY")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and "404" in j["store_errors"]["replay"]
    assert j["mode"] == "list" and j["expiries"] == [] and j["n"] == 0


def test_validation_bad_symbol_and_bad_expiry_are_422(monkeypatch):
    async def fake(path, params):  # never reached
        raise AssertionError("validation must fail before the store is asked")
    monkeypatch.setattr(expiry, "_fetch", fake)
    c = TestClient(_app())
    assert c.get("/api/derivatives/replay?symbol=NOT%20OK!").status_code == 422
    assert c.get("/api/derivatives/replay?symbol=NIFTY&expiry=20261103").status_code == 422   # pattern
    assert c.get("/api/derivatives/replay?symbol=NIFTY&expiry=2026-13-99").status_code == 422  # not a date


def test_the_router_is_read_only_and_never_touches_the_paper_book():
    # practice entries live in the browser: no POST/PUT/DELETE route exists, and the module never imports the book
    for route in expiry.router.routes:
        assert set(getattr(route, "methods", {"GET"})) == {"GET"}, f"{route.path} is not read-only"
    src = Path(expiry.__file__).read_text(encoding="utf-8")
    assert "fo_book" not in src and "paper_fo" not in src
    # and the replay read never triggers the backfill job (the PM's, O-T16)
    assert "/jobs/expiry-replay" not in src


def test_no_direction_or_judgement_words_anywhere_in_the_payloads(monkeypatch):
    for body, url in ((LIST_BODY, "/api/derivatives/replay?symbol=NIFTY"),
                      (TAPE_BODY, "/api/derivatives/replay?symbol=NIFTY&expiry=2026-11-03")):
        expiry.TAPE.invalidate()
        j = _get(monkeypatch, body, url)
        text = " ".join(_strings(j)).lower()
        for word in FORBIDDEN:
            assert word not in text, f"forbidden word {word!r} in the {j['mode']} payload"
