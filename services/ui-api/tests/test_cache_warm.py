"""routers/_cache_warm.py (desktop review C-PERF-01 / C-PERF-02): after a restart the slow-endpoint SWR caches are
filled once, in the background, one call at a time, with exactly the variants the pages request first."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import _cache_warm as cw
from routers import gold_preopen, markets

ROOT = Path(__file__).resolve().parents[3]


def test_calls_run_one_at_a_time_in_order_and_failures_never_raise() -> None:
    running: list[str] = []
    order: list[str] = []
    overlap: list[bool] = []

    def call(name: str, fail: bool = False):
        async def run() -> None:
            overlap.append(bool(running))
            running.append(name)
            await asyncio.sleep(0.01)
            order.append(name)
            running.remove(name)
            if fail:
                raise RuntimeError("data-service down")
        return run

    calls = [("a", call("a")), ("b", call("b", fail=True)), ("c", call("c"))]
    summary = asyncio.run(cw.warm(delay_s=0, calls=calls))
    assert order == ["a", "b", "c"] and not any(overlap)                 # sequential: no burst on data-service
    assert summary["ok"] == 2 and summary["failed"] == ["b:RuntimeError"] and summary["event"] == "cache_warm_done"


def test_a_hung_call_is_bounded_and_the_rest_still_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cw, "CALL_TIMEOUT_S", 0.05)
    done: list[str] = []

    async def hang() -> None:
        await asyncio.sleep(30)

    async def quick() -> None:
        done.append("quick")
    summary = asyncio.run(cw.warm(delay_s=0, calls=[("hang", hang), ("quick", quick)]))
    assert done == ["quick"] and summary["failed"] == ["hang:TimeoutError"]


def test_stop_cancels_a_pending_warm_up() -> None:
    async def scenario() -> bool:
        ran: list[str] = []

        async def call() -> None:
            ran.append("x")
        task = asyncio.get_running_loop().create_task(cw.warm(delay_s=10, calls=[("x", call)]))
        await asyncio.sleep(0)
        await cw.stop(task)
        await cw.stop(None)                                                   # no task: nothing to do
        return task.cancelled() and not ran
    assert asyncio.run(scenario())


def test_off_switch_and_test_mode_start_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def start() -> Any:
        return cw.start_from_env()
    monkeypatch.setenv("UI_API_CACHE_WARM", "0")
    assert asyncio.run(start()) is None
    monkeypatch.delenv("UI_API_CACHE_WARM")
    assert asyncio.run(start()) is None                                     # pytest is running: test mode
    assert cw.start_from_env() is None                                      # and no running loop: nothing either


def test_the_warm_up_starts_outside_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.http_guard as hg
    monkeypatch.setattr(hg, "in_test_mode", lambda *a, **k: False)
    monkeypatch.delenv("UI_API_CACHE_WARM", raising=False)
    seen: list[float] = []

    async def fake_warm(delay_s: float = cw.WARM_DELAY_S, calls: Any = None) -> dict[str, Any]:
        seen.append(delay_s)
        return {}
    monkeypatch.setattr(cw, "warm", fake_warm)

    async def scenario() -> None:
        task = cw.start_from_env()
        assert task is not None
        await task
    asyncio.run(scenario())
    assert seen == [cw.WARM_DELAY_S]


def test_the_warm_set_is_what_the_pages_request_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each warm call must fill the SAME cache key a page then reads, or it warms nothing. Pins the UI's
    parameters (ui/lib/api.ts + callers) against the warm list."""
    ui = (ROOT / "ui").resolve()
    api = (ui / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "'/api/market/fundamentals-screen', { params: { fields: 'core' }" in api
    callers = "".join(p.read_text(encoding="utf-8") for p in (ui / "components").glob("*.tsx"))
    callers += (ui / "lib" / "useCorpEvents.ts").read_text(encoding="utf-8")
    recent_days = {int(d) for d in re.findall(r"getRecentResults\((\d+)\)", callers)}
    implied_days = {int(d) for d in re.findall(r"getResultsImpliedMoves\((\d+)\)", callers)}

    got: list[tuple[str, Any]] = []

    async def rr(days: int = 10, response: Any = None) -> dict:
        got.append(("recent", days))
        return {}

    async def im(days: int = 10, response: Any = None) -> dict:
        got.append(("implied", days))
        return {}

    async def fs(limit: int = 2500, fields: str | None = None, response: Any = None) -> dict:
        got.append(("fundamentals", (limit, fields)))
        return {}

    async def gold() -> int:
        got.append(("gold", None))
        return 6
    monkeypatch.setattr(markets, "results_recent", rr)
    monkeypatch.setattr(markets, "results_implied_moves", im)
    monkeypatch.setattr(markets, "fundamentals_screen", fs)
    monkeypatch.setattr(gold_preopen, "warm_series", gold)
    summary = asyncio.run(cw.warm(delay_s=0))
    assert summary["failed"] == []
    assert {d for k, d in got if k == "recent"} == recent_days                # BRF 5, MKT 7, EVTS 10, EQS/WTCH 95
    assert {d for k, d in got if k == "implied"} == implied_days == {10}
    assert ("fundamentals", (2500, "core")) in got and ("gold", None) in got



def _fake_pages(monkeypatch: pytest.MonkeyPatch, gold_usable: int) -> None:
    async def page(*a: Any, **k: Any) -> dict:
        return {}

    async def gold() -> int:
        return gold_usable
    for name in ("results_recent", "results_implied_moves", "fundamentals_screen"):
        monkeypatch.setattr(markets, name, page)
    monkeypatch.setattr(gold_preopen, "warm_series", gold)


def test_a_healthy_start_logs_ok_7(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The round-3 deploy note said ok=9; the warm set has seven calls (review minor)."""
    _fake_pages(monkeypatch, gold_preopen.WARM_SERIES_COUNT)
    summary = asyncio.run(cw.warm(delay_s=0))
    assert len(cw.warm_calls()) == 8 and summary["ok"] == 8 and summary["failed"] == []   # + gold_overview (PLAN §d)
    assert gold_preopen.WARM_SERIES_COUNT == 6


@pytest.mark.parametrize("usable", [0, 5])
def test_a_gold_warm_up_that_fetched_too_few_series_is_reported_as_failed(monkeypatch: pytest.MonkeyPatch,
                                                                          usable: int) -> None:
    """warm_series never raises (it returns how many series came back), so 0 of 6 used to count as ok."""
    _fake_pages(monkeypatch, usable)
    summary = asyncio.run(cw.warm(delay_s=0))
    assert summary["ok"] == 7 and summary["failed"] == [f"gold_yahoo_series:{usable}/6"]

def test_the_lifespan_starts_and_stops_the_warm_up(monkeypatch: pytest.MonkeyPatch) -> None:
    import main
    from fastapi.testclient import TestClient
    events: list[str] = []
    monkeypatch.setattr(main.positions, "warm_breeze_probe", lambda: None)
    monkeypatch.setattr(main.analytics, "warm_snapshot", lambda: None)
    monkeypatch.setattr(main.gold_preopen, "warm", lambda: None)

    async def _no_paper_check() -> None:
        return None
    monkeypatch.setattr(main.execution, "enforce_paper_only_at_startup", _no_paper_check)
    monkeypatch.setattr(main._cache_warm, "start_from_env", lambda: events.append("start") or None)

    async def stop(task: Any) -> None:
        events.append("stop")
    monkeypatch.setattr(main._cache_warm, "stop", stop)
    with TestClient(main.app, base_url="http://127.0.0.1:8010"):
        assert events == ["start"]
    assert events == ["start", "stop"]
