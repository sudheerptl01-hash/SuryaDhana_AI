"""GPLN — Morning Game Plan (wave E, F-11): the assembly, its honesty rules and the digest.

What is pinned here (the acceptance lines of the E-PLAN brief):
  - every tile carries a badge and its own as-of / source; a dead read degrades ONE tile, never the page;
  - the payload states "assembled from stored/live reads — describes, does not predict";
  - zero direction words anywhere in the payload or the rendered digest;
  - the digest renders the SAME payload as text lines (fixture-tested, pure);
  - the overnight alert-fire window is the prior session's 15:30 IST, weekend-safe.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import gameplan  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

# PLAN §1 / WAVE_ORDERS labelling rules: words that may never appear in gameplan copy. Field values from fixtures
# are ours, so the whole serialized payload is scanned. ("long"/"short" are position words — none exist here.)
DIRECTION_WORDS = re.compile(
    r"\b(buy|sell|bullish|bearish|should|opportunity|setups?|bias|resistance|support|breakout|target|"
    r"go long|go short|right side|wrong side)\b", re.IGNORECASE)


# ── fixture upstream ──────────────────────────────────────────────────────────────────────────────────────


def _fake_get_json(responses: dict[str, Any]):
    async def fake(url: str, **kw: Any) -> Any:
        for frag, body in responses.items():
            if frag in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise AssertionError(f"unexpected upstream read in test: {url}")
    return fake


GIFT = {"last": 26120.0, "implied_gap_pct": 0.21, "time": "08:44", "as_of": "2026-11-13T08:44:00+05:30"}
GOLD_BARS = {"rows": [
    {"trade_date": "2026-11-11", "close": 4100.0, "partial": False},
    {"trade_date": "2026-11-12", "close": 4120.5, "partial": False},
]}
INDEX_OHLC = {"rows": [
    {"date": "2026-11-11", "open": 25900, "high": 26000, "low": 25850, "close": 25980},
    {"date": "2026-11-12", "open": 25990, "high": 26110, "low": 25920, "close": 26050},
]}
CHAIN = {"found": True, "date": "2026-11-12", "expiry": "2026-11-18", "days_to_expiry": 6, "spot": 26050.0,
         "future": 26080.0, "atm": 26050, "atm_iv": 12.4, "expected_move_pct": 1.6, "pcr_oi": 0.94,
         "max_pain": 26000.0, "lot": 75, "resistance": [26200.0, 26500.0], "support": [25800.0, 25500.0]}
IV_SUMMARY = {"rows": [
    {"date": "2026-11-11", "iv30_cm": 12.1, "iv_pctile_252": 35.0, "iv_rank_252": 38.0, "iv_minus_rv20": 0.9,
     "expected_move_1d_pct": 0.76},
    {"date": "2026-11-12", "iv30_cm": 12.4, "iv_pctile_252": 38.0, "iv_rank_252": 41.0, "iv_minus_rv20": 1.2,
     "expected_move_1d_pct": 0.78},
]}
ECO = {"events": [{"date": datetime.now(IST).date().isoformat(), "kind": "CPI", "what": "CPI inflation · Oct 2026",
                   "time": "16:00"}]}
CORP = {"rows": [{"symbol": "TCS", "event_date": datetime.now(IST).date().isoformat(), "kind": "results",
                  "purpose": "Financial results"}]}

RESPONSES = {"/db/gift-nifty": GIFT, "/db/gold/bars": GOLD_BARS, "/db/index-ohlc/": INDEX_OHLC,
             "/db/option-chain/": CHAIN, "/db/iv/summary": IV_SUMMARY}


@pytest.fixture()
def wired(monkeypatch):
    """Every collector wired to fixtures; the TTL cache cleared."""
    gameplan._cache.clear()
    monkeypatch.setattr(gameplan, "get_json", _fake_get_json(RESPONSES))

    async def fake_eco(back: int = 0, ahead: int = 4) -> dict:
        return ECO

    async def fake_events(**kw: Any) -> dict:
        return CORP

    import routers.markets as markets
    monkeypatch.setattr(markets, "eco_calendar", fake_eco)
    monkeypatch.setattr(markets, "market_events", fake_events)
    monkeypatch.setattr(gameplan, "_read_watchlist", lambda: ["RELIANCE", "TCS"])
    monkeypatch.setattr(gameplan, "_read_fires", lambda since: [
        {"symbol": "NIFTY", "series": "iv30", "at": "2026-11-12T18:40:00+05:30", "text": "NIFTY iv30 crossed 12"}])
    yield
    gameplan._cache.clear()


def _build(symbol: str = "NIFTY") -> dict[str, Any]:
    return asyncio.run(gameplan.build_gameplan(symbol))


# ── the assembly ──────────────────────────────────────────────────────────────────────────────────────────


def test_every_tile_carries_badge_source_and_as_of(wired):
    p = _build()
    assert set(p["tiles"]) == {"overnight", "levels", "oi", "iv", "events", "focus"}
    for name, tile in p["tiles"].items():
        assert tile["ok"] is True, (name, tile)
        assert tile["badge"] in ("context", "arithmetic"), name          # a `signal` badge does not exist
        assert tile.get("source"), name
        assert tile.get("as_of"), name
    assert p["note"].endswith("describes, does not predict")
    assert "Decision Desk" in p["feeds"] and "S1 shadow" in p["feeds"]


def test_numbers_come_from_the_stores_not_recomputed(wired):
    p = _build()
    t = p["tiles"]
    assert t["levels"]["close"] == 26050 and t["levels"]["high"] == 26110 and t["levels"]["session"] == "2026-11-12"
    assert t["levels"]["change_pct"] == pytest.approx(0.27, abs=0.01)    # (26050/25980 − 1) × 100
    assert t["oi"]["max_pain"] == 26000.0 and t["oi"]["call_walls"] == [26200.0, 26500.0]
    assert t["oi"]["put_walls"] == [25800.0, 25500.0]
    assert "resistance" not in json.dumps(t["oi"]) and "support" not in json.dumps(t["oi"])
    assert t["iv"]["today"]["iv30_cm"] == 12.4 and t["iv"]["prior"]["iv30_cm"] == 12.1
    assert t["iv"]["change"]["iv30_cm"] == pytest.approx(0.3)
    assert t["overnight"]["gold"]["change_pct"] == pytest.approx(0.5, abs=0.01)
    assert t["focus"]["watchlist"] == ["RELIANCE", "TCS"] and t["focus"]["fires"]["count"] == 1


def test_no_direction_words_anywhere_in_the_payload(wired):
    blob = json.dumps(_build())
    m = DIRECTION_WORDS.search(blob)
    assert m is None, f"direction word {m.group(0)!r} in the gameplan payload"


def test_one_dead_read_degrades_one_tile_never_the_page(wired, monkeypatch):
    from shared.http_client import UpstreamError
    broken = dict(RESPONSES)
    broken["/db/iv/summary"] = UpstreamError(503, "All connection attempts failed", upstream="data-service")
    monkeypatch.setattr(gameplan, "get_json", _fake_get_json(broken))
    gameplan._cache.clear()
    p = _build()
    assert p["tiles"]["iv"]["ok"] is False
    assert "connection attempts" not in json.dumps(p)                      # raw transport text never reaches a panel
    assert p["tiles"]["iv"]["error"] == "the data service did not answer"
    for other in ("overnight", "levels", "oi", "events", "focus"):
        assert p["tiles"][other]["ok"] is True, other


def test_route_serves_and_caches(wired):
    app = FastAPI()
    app.include_router(gameplan.router, prefix="/api/gameplan")
    with TestClient(app) as client:
        r = client.get("/api/gameplan", params={"symbol": "NIFTY"})
        assert r.status_code == 200
        first = r.json()
        assert first["symbol"] == "NIFTY" and first["tiles"]["oi"]["ok"]
        # second call is the cached assembly (same as_of stamp)
        assert client.get("/api/gameplan?symbol=NIFTY").json()["as_of"] == first["as_of"]
        assert client.get("/api/gameplan?symbol=DOGE").status_code == 422   # only the four index underlyings


# ── the overnight window (pure) ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("now, want", [
    (datetime(2026, 11, 13, 8, 50, tzinfo=IST), datetime(2026, 11, 12, 15, 30, tzinfo=IST)),   # Fri morning → Thu close
    (datetime(2026, 11, 16, 8, 50, tzinfo=IST), datetime(2026, 11, 13, 15, 30, tzinfo=IST)),   # Mon morning → Fri close
    (datetime(2026, 11, 15, 12, 0, tzinfo=IST), datetime(2026, 11, 13, 15, 30, tzinfo=IST)),   # Sunday → Fri close
    (datetime(2026, 11, 16, 16, 0, tzinfo=IST), datetime(2026, 11, 16, 15, 30, tzinfo=IST)),   # Mon evening → Mon close
])
def test_overnight_window_start(now, want):
    assert gameplan.overnight_window_start(now) == want


# ── the digest (fixture payload → text; pure) ─────────────────────────────────────────────────────────────


def _load_digest_module():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("morning_gameplan", root / "scripts" / "morning_gameplan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_digest_renders_the_same_payload_as_text(wired):
    mg = _load_digest_module()
    payload = _build()
    text = mg.render_digest(payload)
    lines = text.splitlines()
    assert lines[0].startswith("MORNING GAME PLAN · NIFTY")
    assert any(l.startswith("OVERNIGHT") and "GIFT 26,120" in l for l in lines)
    assert any(l.startswith("PRIOR SESSION") and "26,050" in l for l in lines)
    assert any(l.startswith("CHAIN") and "max pain 26,000" in l and "PCR 0.94" in l for l in lines)
    assert any(l.startswith("IV") and "IV30 12.4" in l and "close-to-close" in l for l in lines)
    assert any(l.startswith("EVENTS") and "CPI" in l for l in lines)
    assert any(l.startswith("FOCUS") and "RELIANCE" in l for l in lines)
    assert lines[-1] == "assembled from stored/live reads — describes, does not predict"
    m = DIRECTION_WORDS.search(text)
    assert m is None, f"direction word {m.group(0)!r} in the digest"


def test_digest_degrades_honestly_on_a_dead_tile():
    mg = _load_digest_module()
    payload = {"symbol": "NIFTY", "date": "2026-11-13",
               "tiles": {k: {"ok": False, "badge": "context", "error": "the data service did not answer"}
                         for k in ("overnight", "levels", "oi", "iv", "events", "focus")}}
    text = mg.render_digest(payload)
    assert text.count("unavailable (the data service did not answer)") == 6
    assert text.splitlines()[-1].endswith("describes, does not predict")
