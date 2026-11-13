"""FINAL ROUND B-OSTR (P0-8 + T-07b) — the margin answer cache and the cost-aware breakevens.

* POST /api/options/margin `cached_only`: the instant probe — a cache hit re-serves the LAST successful Breeze
  answer with `served_from_cache: true`, its ORIGINAL `as_of` and `cache_age_s`; a miss is `{"hit": false}` and
  calls nothing. `stale_ok`: a failed / timed-out Breeze degrades to the cached answer (age shown) BEFORE the
  SPAN file / heuristic; without the flag the ladder is exactly as before (the existing tests stay the contract).
* POST /api/options/strategy/analyze `breakevens_net_of_costs`: levels where the expiry P&L equals the
  round-trip costs — wider than the raw breakevens, badge arithmetic, exercise STT excluded.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _terminal_v2_fixtures as fx  # noqa: E402
import routers.options_strategy as osr  # noqa: E402
from shared import breeze_budget as bb  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(fx.make_app())


@pytest.fixture(autouse=True)
def _fresh_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(bb.ENV_DB, str(tmp_path / "budget.sqlite"))
    monkeypatch.delenv(bb.ENV_CAP_DAY, raising=False)
    bb.reset_ledger()
    osr._SPAN_CACHE.clear()
    osr.reset_margin_answer_cache()
    monkeypatch.setenv(osr.SPAN_DIR_ENV, str(tmp_path / "no-span-files"))
    yield
    bb.reset_ledger()
    osr.reset_margin_answer_cache()


class FakeBreeze:
    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls = 0
        self.delay_s = delay_s

    def margin_calculator(self, lists: list[dict[str, str]], exchange_code: str) -> dict[str, Any]:
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return fx.BREEZE_MARGIN_SAMPLE


def _no_session(*_: Any, **__: Any) -> tuple[None, str]:
    return None, "ICICI credentials not configured in .env"


def _wire_breeze(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    import routers.positions as pos
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (fake, None))


# ── the cache probe (cached_only) ──────────────────────────────────────────────────────────────────────────────

def test_cached_only_miss_is_instant_and_calls_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBreeze()
    _wire_breeze(monkeypatch, fake)
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS, "cached_only": True}).json()
    assert b == {"hit": False, "served_from_cache": False, "paper_only": True,
                 "note": "no cached Breeze answer for these legs on this ui-api yet"}
    assert fake.calls == 0                                     # the probe never reaches the SDK


def test_a_breeze_success_fills_the_cache_and_the_probe_serves_it_with_age(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeBreeze()
    _wire_breeze(monkeypatch, fake)
    full = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS}).json()
    assert full["source"] == "BREEZE" and full["served_from_cache"] is False
    hit = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS, "cached_only": True}).json()
    assert hit["hit"] is True and hit["served_from_cache"] is True
    assert hit["cache_age_s"] >= 0                             # the age is ON the payload — a cached SPAN never poses as fresh
    assert hit["as_of"] == full["as_of"]                       # the ORIGINAL answer time, never re-stamped
    assert hit["span_margin_required"] == full["span_margin_required"] == 81497.07
    assert hit["attempts"][0]["source"] == "CACHE" and "cached" in hit["attempts"][0]["reason"]
    assert "served from this ui-api's cache" in hit["note"] and hit["paper_only"] is True
    assert fake.calls == 1                                     # the probe made no second SDK call


def test_the_cache_key_is_the_legs_shape_not_the_premiums(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_breeze(monkeypatch, FakeBreeze())
    client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS})
    # same contracts, drifted premiums → the same shape, still a hit (SPAN is about the contracts; the age is shown)
    drifted = [dict(lg, premium=lg["premium"] + 1.5) for lg in fx.CONDOR_LEGS]
    assert client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": drifted, "cached_only": True}).json()["hit"] is True
    # a different strike → a different shape → a miss
    other = [dict(fx.CONDOR_LEGS[0], strike=23650)] + fx.CONDOR_LEGS[1:]
    assert client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": other, "cached_only": True}).json()["hit"] is False
    # another underlying → a miss
    assert client.post("/api/options/margin", json={"symbol": "BANKNIFTY", "legs": fx.CONDOR_LEGS, "cached_only": True}).json()["hit"] is False


# ── stale_ok: the degrade ladder (cached → SPAN file → heuristic) ─────────────────────────────────────────────

def test_stale_ok_serves_the_cached_answer_when_breeze_dies(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.positions as pos
    _wire_breeze(monkeypatch, FakeBreeze())
    client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS})          # warm the cache
    monkeypatch.setattr(pos, "_get_breeze_client", _no_session)                                   # the session dies
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS, "stale_ok": True}).json()
    assert b["source"] == "BREEZE" and b["served_from_cache"] is True and b["cache_age_s"] >= 0
    assert b["span_margin_required"] == 81497.07
    assert [a["source"] for a in b["attempts"]] == ["BREEZE", "CACHED_BREEZE"]
    assert b["attempts"][0]["ok"] is False and "no live Breeze session" in b["attempts"][0]["reason"]
    assert "s old" in b["attempts"][1]["reason"]


def test_without_stale_ok_the_old_ladder_is_untouched_even_with_a_warm_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.positions as pos
    _wire_breeze(monkeypatch, FakeBreeze())
    client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS})          # warm the cache
    monkeypatch.setattr(pos, "_get_breeze_client", _no_session)
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "forward": 23931.0, "legs": fx.CONDOR_LEGS}).json()
    assert [a["source"] for a in b["attempts"]] == ["BREEZE", "NSE_SPAN_FILE", "HEURISTIC"]       # the existing contract
    assert b["source"] == "HEURISTIC" and b["served_from_cache"] is False


def test_a_slow_breeze_times_out_and_the_ladder_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    # measured INSIDE the coroutine: a long-lived production loop answers at the timeout; TestClient's per-request
    # loop teardown would join the abandoned worker thread and hide the very latency this bounds (P0-8)
    import asyncio

    _wire_breeze(monkeypatch, FakeBreeze(delay_s=1.6))
    body = osr.MarginIn.model_validate({"symbol": "NIFTY", "forward": 23931.0, "legs": fx.CONDOR_LEGS,
                                        "breeze_timeout_s": 1.0})

    async def run() -> tuple[float, dict[str, Any]]:
        t0 = time.monotonic()
        resp = await osr.margin(body)
        return time.monotonic() - t0, resp

    elapsed, b = asyncio.run(run())
    assert elapsed < 1.5                                        # 40 s of nothing is forbidden (P0-8)
    assert b["attempts"][0]["source"] == "BREEZE" and b["attempts"][0]["ok"] is False
    assert "did not answer within 1 s" in b["attempts"][0]["reason"]
    assert b["source"] == "HEURISTIC"                           # cold cache, no SPAN file → the labelled heuristic


# ── T-07b: breakevens net of costs ────────────────────────────────────────────────────────────────────────────

def _straddle_body(slippage: float = 0.0) -> dict[str, Any]:
    return {"symbol": "NIFTY", "forward": 24000.0, "days_to_expiry": 5.0, "default_iv": 12.0, "grid": False,
            "slippage_per_unit": slippage,
            "legs": [{"side": "buy", "kind": "CE", "strike": 24000, "premium": 150.0, "lots": 1, "lot_size": 65},
                     {"side": "buy", "kind": "PE", "strike": 24000, "premium": 140.0, "lots": 1, "lot_size": 65}]}


def test_breakevens_net_of_costs_sit_outside_the_raw_breakevens(client: TestClient) -> None:
    d = client.post("/api/options/strategy/analyze", json=_straddle_body()).json()
    raw = d["breakevens"]
    net = d["breakevens_net_of_costs"]
    assert raw == [pytest.approx(23710.0), pytest.approx(24290.0)]      # K ± (150 + 140)
    assert net["badge"] == "arithmetic" and net["costs_inr"] > 0
    assert net["costs_inr"] == pytest.approx(d["costs"]["round_trip"]["total"], abs=0.02)
    lo, hi = net["values"][0], net["values"][-1]
    # a long straddle must travel FURTHER before the costs are covered: lower BE lower, upper BE higher
    per_unit = net["costs_inr"] / (1 * 65)
    assert lo == pytest.approx(raw[0] - per_unit, abs=0.5) and hi == pytest.approx(raw[1] + per_unit, abs=0.5)
    note = net["note"].lower()
    assert "describes" not in note or "predict" in note
    for word in ("buy the", "sell the", "bullish", "bearish", "should", "opportunity"):
        assert word not in note


def test_breakevens_net_of_costs_include_the_bid_ask_input(client: TestClient) -> None:
    base = client.post("/api/options/strategy/analyze", json=_straddle_body(0.0)).json()["breakevens_net_of_costs"]
    wide = client.post("/api/options/strategy/analyze", json=_straddle_body(2.0)).json()["breakevens_net_of_costs"]
    # 2 ₹/unit/side × 130 units × 2 sides = ₹520 more to cover
    assert wide["costs_inr"] == pytest.approx(base["costs_inr"] + 520.0, abs=0.02)
    assert wide["values"][0] < base["values"][0] and wide["values"][-1] > base["values"][-1]
