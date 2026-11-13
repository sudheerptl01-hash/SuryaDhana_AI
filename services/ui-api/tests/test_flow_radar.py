"""routers/flow_radar.py (FINAL ROUND wave E, E-RADAR): the DERV › RADAR read.

Rules, each with a control: the OI change is latest stored frame − the nearest stored frame at or before the window
mark — NEVER interpolated, never scaled to a per-30-minute rate; a gapped tape says so (window.gapped + the gap list)
and the raw span is served as stored; per-strike volume absent → vol ÷ OI is None with the honest note (present →
computed); the IV change is the ATM path's and says so; every badge is ``context`` (no ``signal``); no direction word
anywhere in the payload's copy; a 404 store degrades to ``ok: false``, never a 500; the shaping of a full stored day
stays far inside the 250 ms p95 line. The real router on a bare app, the data-service fetch monkeypatched.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import flow_radar  # noqa: E402


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

    app.include_router(flow_radar.router, prefix="/api/derivatives")
    return app


@pytest.fixture(autouse=True)
def _fresh_caches():
    flow_radar._down.clear()
    flow_radar.RADAR.invalidate()
    yield
    flow_radar._down.clear()
    flow_radar.RADAR.invalidate()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "+00:00"


BASE = datetime(2026, 11, 13, 3, 46, tzinfo=timezone.utc)  # 09:16 IST


def _tape(minutes: list[int], *, strikes=(25800.0, 25900.0, 26000.0), oi_step=1000.0, volume=False) -> dict:
    """A tape body whose frames/path share the stamps 09:16 + m minutes; CE OI grows ``oi_step``/frame at the second
    strike, PE OI falls half that at the third; strikes past the third hold still; ATM IV climbs 0.05 pts a frame."""
    stamps = [BASE + timedelta(minutes=m) for m in minutes]

    def _ce(i: int, j: int) -> float:
        return [10_000.0, 50_000.0 + i * oi_step, 20_000.0][j] if j < 3 else 15_000.0 + 100.0 * j

    def _pe(i: int, j: int) -> float:
        return [30_000.0, 40_000.0, 60_000.0 - i * oi_step / 2][j] if j < 3 else 25_000.0 + 100.0 * j

    frames = [{"ts": _iso(t), "ist": (t + timedelta(hours=5, minutes=30)).strftime("%H:%M"),
               "ce": [_ce(i, j) for j in range(len(strikes))],
               "pe": [_pe(i, j) for j in range(len(strikes))]}
              for i, t in enumerate(stamps)]
    path = [{"ts": _iso(t), "ist": frames[i]["ist"], "forward": 25_910.0 + i, "spot": 25_900.0, "atm_strike": 25_900.0,
             "atm_iv": 12.0 + 0.05 * i, "straddle": 180.0 - i, "pcr": 0.90 + 0.002 * i, "max_pain": 25_900.0,
             "n_strikes": 3, "source": "breeze"} for i, t in enumerate(stamps)]
    srows = []
    for j, k in enumerate(strikes):
        r = {"strike": k, "ce_oi_open": frames[0]["ce"][j], "ce_oi": frames[-1]["ce"][j],
             "ce_chg_open": frames[-1]["ce"][j] - frames[0]["ce"][j], "ce_mid": 100.0 - j, "ce_bid": 99.0, "ce_ask": 101.0,
             "ce_chg_prev": None, "pe_oi_open": frames[0]["pe"][j], "pe_oi": frames[-1]["pe"][j],
             "pe_chg_open": frames[-1]["pe"][j] - frames[0]["pe"][j], "pe_mid": 90.0 + j, "pe_bid": 89.0, "pe_ask": 91.0,
             "pe_chg_prev": None}
        if volume:
            r["ce_volume"] = 120_000.0
            r["pe_volume"] = 80_000.0
        srows.append(r)
    return {"symbol": "NIFTY", "date": "2026-11-13", "expiry": "2026-11-17", "expiries": ["2026-11-17"], "lot": 65,
            "dte_calendar": 4, "path": path, "strikes": srows, "frames": frames, "snapshots": len(path),
            "first": frames[0]["ist"], "last": frames[-1]["ist"], "last_ts": _iso(stamps[-1]),
            "median_gap_min": 2.0, "source": "breeze", "units": {"oi": "shares"}, "model_version": "b76-pcp-v1-i"}


def _coro(v):
    async def f(path, params):
        return v
    return f


def _get(monkeypatch, body, url="/api/derivatives/flow-radar/NIFTY?window_min=30"):
    monkeypatch.setattr(flow_radar, "_fetch", _coro(body))
    r = TestClient(_app()).get(url)
    assert r.status_code == 200
    return r.json()


# ── the rolling window on a clean 2-minute tape ───────────────────────────────────────────────────────────────────────

def test_30_min_delta_uses_the_nearest_stored_frame_and_is_never_scaled(monkeypatch):
    j = _get(monkeypatch, _tape(list(range(0, 81, 2))))      # 09:16 → 10:36, every 2 min (41 frames)
    w = j["window"]
    assert w["requested_min"] == 30.0 and w["actual_min"] == 30.0 and w["gapped"] is False and w["note"] is None
    # CE at 25,900 grows 1,000/frame: 15 frames in 30 min → +15,000, exactly as stored (never a per-30-min rescale)
    mid = next(r for r in j["ladder"] if r["strike"] == 25_900.0)
    assert mid["ce_d"] == 15_000.0 and mid["ce_oi"] == 90_000.0
    top = j["movers"][0]
    assert top["strike"] == 25_900.0 and top["side"] == "CE" and top["oi_delta"] == 15_000.0
    assert top["line"] == "OI rose 15.0 k at 25,900 CE in 30 min — describes, does not predict"
    # falling OI reads "fell", with the sign kept raw
    pe = next(m for m in j["movers"] if m["side"] == "PE" and m["strike"] == 26_000.0)
    assert pe["oi_delta"] == -7_500.0 and pe["line"].startswith("OI fell 7.5 k at 26,000 PE")
    # the ATM IV change is the path's and is labelled as the floating-ATM read
    assert j["atm_iv"]["delta"] == 0.75 and "floating-ATM" in j["atm_iv"]["label"]
    assert j["pcr"]["delta"] == 0.03 and j["max_pain"]["delta"] == 0.0
    assert j["chip"]["state"] == "delayed" and j["chip"]["source"] == "BREEZE"
    assert j["ok"] is True and j["gaps"] == []


def test_a_gapped_tape_shows_the_gap_and_serves_the_raw_span(monkeypatch):
    # stored 09:16–09:40 every 2 min, a 50-minute hole, then 10:30–10:50: the 30-min baseline from 10:50 crosses the hole
    j = _get(monkeypatch, _tape([*range(0, 25, 2), 74, 80, 86, 94]))
    w = j["window"]
    assert w["gapped"] is True and w["actual_min"] == 70.0       # 09:40 → 10:50, as stored
    assert "gapped inside the window" in w["note"] and "never interpolated" in w["note"]
    assert j["gaps"] == [{"from_ist": "09:40", "to_ist": "10:30", "minutes": 50.0}]
    # the delta is the raw difference across the hole (frame index 12 → 16: 4 steps of 1,000), not a filled estimate
    mid = next(r for r in j["ladder"] if r["strike"] == 25_900.0)
    assert mid["ce_d"] == 4_000.0
    assert "in 70 min" in j["movers"][0]["line"]


def test_a_tape_shorter_than_the_window_names_its_real_span(monkeypatch):
    j = _get(monkeypatch, _tape([0, 2, 4, 6]))
    w = j["window"]
    assert w["actual_min"] == 6.0 and w["gapped"] is True
    assert "covers only 6.0 min" in w["note"]


def test_one_snapshot_computes_nothing_and_says_why(monkeypatch):
    j = _get(monkeypatch, _tape([0]))
    assert j["window"]["note"] == "only one stored snapshot — no change computable yet"
    assert all(r["ce_d"] is None and r["pe_d"] is None for r in j["ladder"])
    assert j["movers"] == [] and j["atm_iv"] is None and j["pcr"] is None


def test_an_empty_store_keeps_the_shape_offline(monkeypatch):
    body = {"symbol": "NIFTY", "date": None, "expiry": None, "expiries": [], "path": [], "strikes": [], "frames": [],
            "snapshots": 0, "source": "OFFLINE"}
    j = _get(monkeypatch, body)
    assert j["ok"] is True and j["chip"]["state"] == "offline" and j["ladder"] == [] and j["movers"] == []
    assert j["window"]["note"] == "no snapshot stored"


# ── vol ÷ OI honesty ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_vol_oi_absent_is_declared_not_invented(monkeypatch):
    j = _get(monkeypatch, _tape(list(range(0, 41, 2))))
    assert j["vol_oi_available"] is False and "not stored in the tape read yet" in j["vol_oi_note"]
    assert all(r["ce_vol_oi"] is None and r["pe_vol_oi"] is None for r in j["ladder"])


def test_vol_oi_computes_when_the_store_serves_volume(monkeypatch):
    j = _get(monkeypatch, _tape(list(range(0, 41, 2)), volume=True))
    assert j["vol_oi_available"] is True and j["vol_oi_note"] is None
    first = next(r for r in j["ladder"] if r["strike"] == 25_800.0)
    assert first["ce_vol_oi"] == 12.0                           # 120,000 ÷ 10,000
    assert first["pe_vol_oi"] == round(80_000.0 / 30_000.0, 3)


# ── copy / labelling rules ───────────────────────────────────────────────────────────────────────────────────────────

def test_everything_is_context_and_no_direction_word_appears(monkeypatch):
    j = _get(monkeypatch, _tape(list(range(0, 61, 2))))
    assert set(j["badges"].values()) == {"context"} and "signal" not in j["badges"]
    text = json.dumps(j).lower()
    for word in ("bullish", "bearish", "buy", "sell", "should", "opportunity", "setup", "bias", "long", "short",
                 "support", "resistance", "writers", "buyers", "breakout", "target"):
        assert not re.search(rf"\b{word}\b", text), f"direction word {word!r} in the payload"
    assert "describes, does not predict" in j["note"]
    assert all(m["line"].endswith("describes, does not predict") for m in j["movers"])
    assert "never interpolated" in j["frames_note"]


# ── store failures and bad input ─────────────────────────────────────────────────────────────────────────────────────

def test_a_404_store_degrades_to_ok_false_never_a_500(monkeypatch):
    async def fake(path, params):
        raise flow_radar._Unavailable("data-service does not serve the tape read yet (404): the W2-TAPE routes are not deployed")

    monkeypatch.setattr(flow_radar, "_fetch", fake)
    r = TestClient(_app()).get("/api/derivatives/flow-radar/NIFTY")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is False and "oi-tape" in j["store_errors"] and "404" in j["store_errors"]["oi-tape"]
    assert j["ladder"] == [] and j["chip"]["state"] == "offline"


def test_bad_symbol_and_bad_window_are_422(monkeypatch):
    monkeypatch.setattr(flow_radar, "_fetch", _coro(_tape([0, 2])))
    c = TestClient(_app())
    assert c.get("/api/derivatives/flow-radar/NIFTY%20X").status_code == 422
    assert c.get("/api/derivatives/flow-radar/NIFTY?window_min=2").status_code == 422
    assert c.get("/api/derivatives/flow-radar/NIFTY?window_min=500").status_code == 422


# ── pure helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_pick_base_takes_the_latest_stamp_at_or_before_the_mark():
    stamps = [BASE + timedelta(minutes=m) for m in (0, 10, 28, 30, 42, 60)]
    i = flow_radar.pick_base(stamps, 30.0)                      # 60 − 30 = minute 30 exactly → index 3
    assert i == 3
    assert flow_radar.pick_base(stamps, 25.0) == 3              # minute 35 mark → the 30-minute stamp
    assert flow_radar.pick_base(stamps, 500.0) == 0             # shorter than the window → the first stamp
    assert flow_radar.pick_base(stamps[:1], 30.0) is None


def test_fmt_shares_units():
    f = flow_radar.fmt_shares
    assert f(850) == "850" and f(41_200) == "41.2 k" and f(1_30_000) == "1.3 L" and f(2.1e7) == "2.1 cr"


def test_shaping_a_full_stored_day_is_fast():
    body = _tape(list(range(0, 375, 2)), strikes=tuple(25_000.0 + 100 * i for i in range(31)))
    t0 = time.perf_counter()
    out = flow_radar.shape(body, "NIFTY", None, 30.0)
    assert (time.perf_counter() - t0) < 0.25                    # one shape well under the endpoint's 250 ms p95 line
    assert len(out["ladder"]) == 31 and out["window"]["actual_min"] == 30.0
