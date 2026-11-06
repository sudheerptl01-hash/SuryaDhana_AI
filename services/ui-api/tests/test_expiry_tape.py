"""routers/expiry.py (W2-TAPE, PLAN 2.1 + 2.4): the OMON › LIVE tape and the XPRY read.

Rules, each with a negative control: stored snapshots are DELAYED with their age, never LIVE; no snapshot → OFFLINE; a
data-service that does not serve the reads (404) degrades to ``ok: false`` with the reason, never a 500, and is not re-asked
for the down-TTL; no ``signal`` badge exists; the sentences end "describes, does not predict"; bad symbols / dates are 422.
The real router on a bare app (main.py's contract handler mirrored), the data-service fetch monkeypatched.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import expiry  # noqa: E402


def _app() -> FastAPI:
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from errors import code_for_status, error_block

    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def handler(request, exc):  # mirror of main.py's contract handler
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block = error_block(d["code"], str(d["message"]), d.get("hint"))
            message = str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = error_block(code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code)

    app.include_router(expiry.router, prefix="/api/derivatives")
    return app


@pytest.fixture(autouse=True)
def _fresh_down_memory():
    expiry._down.clear()
    yield
    expiry._down.clear()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "+00:00"


TAPE = {"symbol": "NIFTY", "date": "2026-11-06", "expiry": "2026-11-09", "expiries": ["2026-11-09", "2026-11-17"], "lot": 65,
        "path": [{"ts": "2026-11-06T03:46:00+00:00", "ist": "09:16", "forward": 24500.0, "atm_iv": 14.2, "straddle": 300.0,
                  "straddle_open_strike": 300.0, "pcr": 0.9, "max_pain": 24500.0}],
        "strikes": [{"strike": 24500.0, "ce_oi_open": 100.0, "ce_oi": 150.0, "ce_chg_open": 50.0}], "frames": [], "snapshots": 1,
        "first": "09:16", "last": "09:16", "last_ts": None, "source": "breeze", "units": {"oi": "shares"}, "model_version": "b76-pcp-v1-i"}


def test_tape_is_delayed_with_its_age_never_live(monkeypatch):
    last = datetime.now(timezone.utc) - timedelta(seconds=90)
    body = {**TAPE, "last_ts": _iso(last)}

    async def fake(path, params):
        assert path == "/db/fo-iv/oi-tape/NIFTY" and params == {"expiry": "2026-11-09"}
        return body

    monkeypatch.setattr(expiry, "_fetch", fake)
    r = TestClient(_app()).get("/api/derivatives/iv/nifty/oi-tape?expiry=2026-11-09")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["chip"]["state"] == "delayed" and j["chip"]["source"] == "BREEZE" and 60 <= j["chip"]["age_s"] <= 200
    assert j["strikes"][0]["ce_chg_open"] == 50.0 and j["badges"]["tape"] == "context" and "signal" not in j["badges"].values()
    assert "describes, does not predict" in j["note"] and "09:15–15:30" in j["coverage"]
    # negative control: no snapshot stored → OFFLINE, nothing invented
    monkeypatch.setattr(expiry, "_fetch", lambda p, q: _coro({**TAPE, "snapshots": 0, "path": [], "source": "OFFLINE"}))
    expiry.TAPE.invalidate()
    j2 = TestClient(_app()).get("/api/derivatives/iv/BANKNIFTY/oi-tape").json()
    assert j2["chip"]["state"] == "offline" and j2["path"] == []


async def _coro(v):
    return v


def test_a_store_without_the_routes_degrades_and_is_not_reasked(monkeypatch):
    from shared.http_client import UpstreamError

    calls = {"n": 0}

    async def missing(url, **kw):
        calls["n"] += 1
        raise UpstreamError(404, "Not Found")

    monkeypatch.setattr(expiry, "get_json", missing)
    c = TestClient(_app())
    j = c.get("/api/derivatives/expiry-day?symbol=NIFTY").json()
    assert j["ok"] is False and "not deployed" in j["store_errors"]["expiry-day"] and j["scorecard"]["stats"]["n"] == 0
    assert j["chip"]["state"] == "offline"
    c.get("/api/derivatives/expiry-day?symbol=BANKNIFTY")
    assert calls["n"] == 1                                              # the down-TTL holds the 404 for every symbol of the route
    # negative control: the other route is asked (its own down memory)
    j3 = c.get("/api/derivatives/iv/NIFTY/oi-tape").json()
    assert j3["ok"] is False and calls["n"] == 2


def test_expiry_day_shape_and_validation(monkeypatch):
    body = {"symbol": "NIFTY", "date": "2026-11-09", "is_expiry_day": True, "next_expiry": "2026-11-17", "last_expiry": "2026-11-03",
            "live": {"snapshots": 3, "last_ts": _iso(datetime.now(timezone.utc)), "source": "breeze", "pin_risk": [{"strike": 24500.0}],
                     "decay": [{"minute": 1, "pct_of_open": 100.0}]},
            "curve": {"n": 4, "points": [{"minute": 0, "median": 100.0}]}, "scorecard": {"rows": [], "stats": {"n": 0}, "badge": "arithmetic"}}
    seen = {}

    async def fake(path, params):
        seen.update(path=path, params=params)
        return body

    monkeypatch.setattr(expiry, "_fetch", fake)
    c = TestClient(_app())
    j = c.get("/api/derivatives/expiry-day?symbol=nifty&date=2026-11-09").json()
    assert seen == {"path": "/db/fo-iv/expiry-day/NIFTY", "params": {"date": "2026-11-09", "n": 26}}
    assert j["is_expiry_day"] is True and j["live"]["pin_risk"][0]["strike"] == 24500.0 and j["chip"]["state"] == "delayed"
    assert j["verdict"].endswith("describes, does not predict") and j["badges"]["scorecard"] == "arithmetic"
    assert c.get("/api/derivatives/expiry-day?symbol=NI%20FTY").status_code == 422
    assert c.get("/api/derivatives/expiry-day?symbol=NIFTY&date=2026-13-40").status_code == 422
    assert c.get("/api/derivatives/iv/BAD$/oi-tape").status_code in (404, 422)
    assert c.get("/api/derivatives/expiry-day?symbol=NIFTY&date=09-11-2026").status_code == 422      # negative control: format


def test_no_signal_badge_and_no_direction_words():
    assert "signal" not in expiry.BADGES.values()
    import inspect
    src = inspect.getsource(expiry)
    for word in ("bullish", "bearish", "buy signal", "sell signal"):
        assert word not in src.lower()
    assert expiry.chip(None, None, 0)["state"] == "offline"
    assert expiry.chip({"source": "nse"}, _iso(datetime.now(timezone.utc)), 2)["source"].startswith("NSE")
