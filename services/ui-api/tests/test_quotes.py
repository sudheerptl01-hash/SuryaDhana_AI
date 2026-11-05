"""routers/quotes.py: tick-vs-Yahoo merge, ensure-on-GET union with holdings, degraded fallbacks (A1/F3.2)."""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers import quotes  # noqa: E402


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.AsyncClient; records the ensure call's params."""
    calls: list[dict] = []
    next_payload: dict = {}
    raise_error: bool = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        FakeClient.calls.append({"url": url, "params": params or {}})
        if FakeClient.raise_error:
            import httpx
            raise httpx.ConnectError("down")
        return FakeResp(200, FakeClient.next_payload)


@pytest.fixture(autouse=True)
def _wire(monkeypatch, tmp_path):
    FakeClient.calls, FakeClient.next_payload, FakeClient.raise_error = [], {}, False
    monkeypatch.setattr(quotes.httpx, "AsyncClient", FakeClient)

    async def fake_yahoo(symbols: str):
        return {"as_of": "Y-AS-OF",
                "quotes": {s: {"price": 99.0, "change_pct": 1.5} for s in symbols.split(",")}}
    monkeypatch.setattr(quotes, "_yahoo_quotes", fake_yahoo)
    holdings = tmp_path / "last_holdings.json"
    holdings.write_text(json.dumps({"positions": [{"symbol": "CUPID"}]}))
    monkeypatch.setattr(quotes, "_holdings_symbols", lambda: ["CUPID"])
    yield


def run(symbols):
    return asyncio.run(quotes.live_quotes(symbols=symbols))


def test_fresh_tick_wins_and_holdings_are_unioned_into_the_ask():
    FakeClient.next_payload = {"state": "LIVE", "connected": True,
                               "ticks": {"TCS": {"price": 2100.0, "chg_pct": 0.5, "ts_age_s": 1.2,
                                                 "as_of": "T-AS-OF"}}}
    out = run("TCS.NS")
    assert out["connected"] and out["state"] == "LIVE"
    assert out["ticks"]["TCS"] == {"price": 2100.0, "chg_pct": 0.5, "as_of": "T-AS-OF", "source": "icici-ws"}
    asked = FakeClient.calls[0]["params"]["symbols"].split(",")
    assert "TCS" in asked and "CUPID" in asked                      # A1: holdings pinned into every ensure


def test_stale_or_missing_ticks_fall_to_yahoo_per_symbol():
    FakeClient.next_payload = {"state": "LIVE", "connected": True,
                               "ticks": {"TCS": {"price": 2100.0, "ts_age_s": 9.0}}}   # stale > 5 s
    out = run("TCS,INFY")
    assert out["ticks"]["TCS"]["source"] == "yahoo"
    assert out["ticks"]["INFY"]["source"] == "yahoo"
    assert out["ticks"]["INFY"]["price"] == 99.0 and out["ticks"]["INFY"]["as_of"] == "Y-AS-OF"


def test_feed_off_and_unreachable_degrade_honestly():
    FakeClient.next_payload = {"state": "OFF", "connected": False, "ticks": {}}
    out = run("TCS")
    assert out["state"] == "OFF" and not out["connected"] and out["ticks"]["TCS"]["source"] == "yahoo"
    FakeClient.raise_error = True
    out2 = run("TCS")
    assert out2["state"] == "UNREACHABLE" and out2["ticks"]["TCS"]["source"] == "yahoo"


def test_clamp_hint_passes_through():
    FakeClient.next_payload = {"state": "LIVE", "connected": True,
                               "ticks": {"TCS": {"price": 10.0, "chg_pct": None, "ts_age_s": 0.5,
                                                 "as_of": "T", "hint": "possible corporate action"}}}
    out = run("TCS")
    assert out["ticks"]["TCS"]["hint"] == "possible corporate action"
    assert out["ticks"]["TCS"]["chg_pct"] is None


def test_wire_key_is_ticks_not_quotes():
    """Pin the B4 wire contract: ui/lib/liveTicks.ts parses `data.ticks` — shipping `quotes`
    left the terminal permanently tickless (bloomberg_verdict defect #1). Never rename."""
    FakeClient.next_payload = {"state": "OFF", "connected": False, "ticks": {}}
    out = run("TCS")
    assert "ticks" in out and "quotes" not in out
