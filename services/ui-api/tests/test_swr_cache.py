"""cache.SWRCache (desktop review C-PERF-01/-02): stale-while-revalidate, single flight, the max-age bound,
errors, invalidation, LRU, the kill switch and the response headers."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cache
from cache import BYPASS, HIT, MISS, STALE, Served, SWRCache, cache_headers, cache_stats, merge_served


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Upstream:
    """A fetch that returns v1, v2, ... and counts calls; optional delay and failures."""

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.fail_next = 0

    async def __call__(self) -> dict:
        self.calls += 1
        n = self.calls
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError(f"upstream down #{n}")
        return {"v": n}


def _cache(clock: Clock, **kw) -> SWRCache:
    return SWRCache(f"t.swr.{id(clock)}.{len(kw)}", max_items=kw.pop("max_items", 8), refresh_after=kw.pop("refresh_after", 60),
                    max_age=kw.pop("max_age", 300), clock=clock)


async def _settle() -> None:
    """Let background refresh tasks finish."""
    for _ in range(5):
        await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.wait(pending, timeout=2)


def test_fresh_entries_are_served_without_a_fetch() -> None:
    clock, up = Clock(), Upstream()
    c = _cache(clock)

    async def run() -> list[Served]:
        a = await c.get("k", up)
        clock.t += 59.0
        b = await c.get("k", up)
        return [a, b]
    a, b = asyncio.run(run())
    assert (a.state, a.value, a.age_s) == (MISS, {"v": 1}, 0.0)
    assert (b.state, b.value) == (HIT, {"v": 1}) and b.age_s == pytest.approx(59.0)
    assert up.calls == 1


def test_stale_entries_are_served_at_once_and_refreshed_in_the_background() -> None:
    clock, up = Clock(), Upstream(delay=0.05)
    c = _cache(clock)

    async def run() -> tuple[Served, Served, int]:
        await c.get("k", up)
        clock.t += 61.0
        stale = await c.get("k", up)                 # no wait for the 50 ms upstream
        calls_right_after = up.calls
        await _settle()
        fresh = await c.get("k", up)
        return stale, fresh, calls_right_after
    stale, fresh, calls_right_after = asyncio.run(run())
    assert (stale.state, stale.value) == (STALE, {"v": 1}) and stale.age_s == pytest.approx(61.0)
    assert calls_right_after == 1                    # the caller got its answer before the refresh even ran
    assert c.stats()["refreshes"] == 1
    assert (fresh.state, fresh.value) == (HIT, {"v": 2})
    assert up.calls == 2


def test_nothing_older_than_max_age_is_ever_served() -> None:
    """The staleness bound (negative control for the stale path): at max_age the caller waits for new data."""
    clock, up = Clock(), Upstream()
    c = _cache(clock)

    async def run() -> Served:
        await c.get("k", up)
        clock.t += 300.0
        return await c.get("k", up)
    s = asyncio.run(run())
    assert (s.state, s.value, s.age_s) == (MISS, {"v": 2}, 0.0)


def test_concurrent_misses_share_one_fetch() -> None:
    clock, up = Clock(), Upstream(delay=0.05)
    c = _cache(clock)

    async def run() -> list[Served]:
        return list(await asyncio.gather(*(c.get("k", up) for _ in range(8))))
    out = asyncio.run(run())
    assert up.calls == 1 and {s.value["v"] for s in out} == {1}
    assert c.stats()["coalesced"] == 7


def test_many_stale_readers_start_one_refresh() -> None:
    clock, up = Clock(), Upstream(delay=0.05)
    c = _cache(clock)

    async def run() -> None:
        await c.get("k", up)
        clock.t += 120.0
        await asyncio.gather(*(c.get("k", up) for _ in range(10)))
        await _settle()
    asyncio.run(run())
    assert up.calls == 2 and c.stats()["refreshes"] == 1


def test_a_caller_that_gives_up_does_not_cancel_the_shared_fetch() -> None:
    clock, up = Clock(), Upstream(delay=0.2)
    c = _cache(clock)

    async def run() -> Served:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(c.get("k", up), 0.01)
        await asyncio.sleep(0.4)
        return await c.get("k", up)
    s = asyncio.run(run())
    assert up.calls == 1 and s.state == HIT and s.value == {"v": 1}


def test_a_failed_fetch_stores_nothing_and_reaches_every_waiter() -> None:
    clock, up = Clock(), Upstream(delay=0.02)
    up.fail_next = 1
    c = _cache(clock)

    async def run() -> Served:
        results = await asyncio.gather(c.get("k", up), c.get("k", up), return_exceptions=True)
        assert all(isinstance(r, RuntimeError) for r in results)
        return await c.get("k", up)                  # retried, not a cached error
    s = asyncio.run(run())
    assert s.state == MISS and s.value == {"v": 2} and up.calls == 2


def test_a_failed_background_refresh_keeps_the_old_value_until_max_age(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, up = Clock(), Upstream()
    c = _cache(clock)
    lines: list[str] = []
    monkeypatch.setattr(cache.log, "warning", lambda msg, *a, **k: lines.append(msg))

    async def run() -> tuple[Served, Served]:
        await c.get("k", up)
        clock.t += 100.0
        up.fail_next = 2
        first = await c.get("k", up)                 # stale; the refresh fails
        await _settle()
        clock.t += 1.0
        second = await c.get("k", up)                # still the old value; another refresh, fails again
        await _settle()
        return first, second
    first, second = asyncio.run(run())
    assert first.value == second.value == {"v": 1} and second.state == STALE
    assert c.stats()["errors"] == 2
    assert lines == ["swr_refresh_failed"]           # one line per cache per minute


def test_policy_sets_per_value_freshness_or_skips_caching() -> None:
    clock = Clock()
    c = _cache(clock)
    calls = {"n": 0}

    async def fetch() -> dict:
        calls["n"] += 1
        return {"available": calls["n"] > 1}

    def policy(v: dict):
        return (10.0, 20.0) if v["available"] else None

    async def run() -> None:
        await c.get("k", fetch, policy=policy)       # not available: not cached
        await c.get("k", fetch, policy=policy)       # cached for 20 s
        clock.t += 15.0
        s = await c.get("k", fetch, policy=policy)
        assert s.state == STALE
    asyncio.run(run())
    assert calls["n"] == 3


def test_invalidate_drops_entries_and_a_running_fetch_stores_nothing() -> None:
    clock, up = Clock(), Upstream(delay=0.05)
    c = _cache(clock)

    async def run() -> Served:
        task = asyncio.ensure_future(c.get("k", up))
        await asyncio.sleep(0.01)
        c.invalidate()                               # the data changed while the fetch was running
        assert (await task).value == {"v": 1}
        return await c.get("k", up)
    s = asyncio.run(run())
    assert s.state == MISS and s.value == {"v": 2}


def test_entries_are_lru_bounded() -> None:
    clock, up = Clock(), Upstream()
    c = _cache(clock, max_items=3)

    async def run() -> None:
        for k in "abcd":
            await c.get(k, up)
    asyncio.run(run())
    assert len(c) == 3 and c.stats()["evictions"] == 1


def test_the_kill_switch_bypasses_every_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, up = Clock(), Upstream()
    c = _cache(clock)
    monkeypatch.setenv("UI_API_SWR", "0")

    async def run() -> list[Served]:
        return [await c.get("k", up), await c.get("k", up)]
    out = asyncio.run(run())
    assert [s.state for s in out] == [BYPASS, BYPASS] and up.calls == 2


def test_bad_bounds_are_refused() -> None:
    with pytest.raises(ValueError):
        SWRCache("t.bad1", max_items=1, refresh_after=10, max_age=5)
    with pytest.raises(ValueError):
        SWRCache("t.bad2", max_items=0, refresh_after=1, max_age=5)


def test_headers_carry_state_and_whole_seconds_and_merge_takes_the_oldest() -> None:
    class R:
        headers: dict[str, str]

        def __init__(self) -> None:
            self.headers = {}
    r = R()
    cache_headers(r, merge_served([Served(None, 3.9, HIT), Served(None, 41.2, STALE), Served(None, 0.0, MISS)]))
    assert r.headers == {"X-Cache": "stale", "X-Cache-Age": "41"}
    cache_headers(None, Served(None, 1.0, HIT))      # a direct call (no Response) is a no-op
    assert merge_served([]) is None
    assert merge_served([Served(None, 0.0, MISS), Served(None, 2.0, HIT)]).state == MISS


def test_swr_caches_report_through_the_shared_registry() -> None:
    SWRCache("t.swr.registry", max_items=2, refresh_after=1, max_age=2)
    row = next(s for s in cache_stats() if s["name"] == "t.swr.registry")
    assert row["kind"] == "swr" and row["max_age_s"] == 2.0 and row["hits"] == 0


# ── fresh=True: decision reads never act on a stale-while-revalidate answer (round 3 review, major) ──────────

def test_a_fresh_read_waits_for_the_refresh_instead_of_taking_the_stale_value() -> None:
    clock, up = Clock(), Upstream(delay=0.01)
    c = _cache(clock, refresh_after=30, max_age=60)

    async def run() -> tuple[Served, Served, Served]:
        await c.get("k", up)                                  # v1 at t
        clock.t += 31.0                                       # past refresh_after, inside max_age
        decided = await c.get("k", up, fresh=True)            # waits: v2
        clock.t += 31.0
        display = await c.get("k", up)                        # control: the display read takes the stale value
        await _settle()
        return decided, display, await c.get("k", up)
    decided, display, after = asyncio.run(run())
    assert (decided.state, decided.value, decided.age_s) == (MISS, {"v": 2}, 0.0)
    assert (display.state, display.value) == (STALE, {"v": 2}) and display.age_s == pytest.approx(31.0)
    assert after.value == {"v": 3} and up.calls == 3
    assert c.stats()["fresh_waits"] == 1


def test_a_fresh_read_still_uses_a_young_entry_and_never_fetches_for_it() -> None:
    clock, up = Clock(), Upstream()
    c = _cache(clock, refresh_after=30, max_age=60)

    async def run() -> Served:
        await c.get("k", up)
        clock.t += 29.9
        return await c.get("k", up, fresh=True)
    s = asyncio.run(run())
    assert (s.state, s.value) == (HIT, {"v": 1}) and s.age_s == pytest.approx(29.9) and up.calls == 1


def test_a_fresh_read_joins_a_refresh_that_is_already_running() -> None:
    clock = Clock()
    gate = asyncio.Event()
    calls = {"n": 0}

    async def fetch() -> dict:
        calls["n"] += 1
        if calls["n"] > 1:
            await gate.wait()
        return {"v": calls["n"]}
    c = _cache(clock, refresh_after=30, max_age=60)

    async def run() -> tuple[Served, Served]:
        await c.get("k", fetch)
        clock.t += 40.0
        stale = await c.get("k", fetch)                       # a display read starts the background refresh
        waiter = asyncio.ensure_future(c.get("k", fetch, fresh=True))
        await asyncio.sleep(0.01)
        assert not waiter.done()                              # it waits for the running refresh ...
        gate.set()
        return stale, await waiter
    stale, fresh = asyncio.run(run())
    assert stale.value == {"v": 1} and fresh.value == {"v": 2} and calls["n"] == 2   # ... and starts no second one


def test_a_fresh_read_keeps_the_per_value_policy_window() -> None:
    """A value the policy keeps without an early refresh ("not available": refresh_after == max_age) is served to
    a fresh read until max_age, as before: fresh only refuses the stale-while-revalidate window."""
    clock, up = Clock(), Upstream()
    c = _cache(clock, refresh_after=30, max_age=60)

    async def run() -> list[Served]:
        out = [await c.get("k", up, policy=lambda v: (120, 120))]
        clock.t += 119.0
        out.append(await c.get("k", up, policy=lambda v: (120, 120), fresh=True))
        clock.t += 1.0
        out.append(await c.get("k", up, policy=lambda v: (120, 120), fresh=True))
        return out
    _, b, d = asyncio.run(run())
    assert (b.state, b.value) == (HIT, {"v": 1}) and (d.state, d.value) == (MISS, {"v": 2})


# ── invalidate(key) is per key (round 3 review, nit) ────────────────────────────────────────────────────────

def test_invalidating_one_key_keeps_another_keys_running_fetch() -> None:
    clock, up = Clock(), Upstream(delay=0.05)
    c = _cache(clock)

    async def run() -> tuple[Served, Served]:
        a = asyncio.ensure_future(c.get("a", up))
        b = asyncio.ensure_future(c.get("b", up))
        await asyncio.sleep(0.01)
        c.invalidate("a")                                     # only a's data changed
        await asyncio.gather(a, b)
        return await c.get("a", up), await c.get("b", up)
    a2, b2 = asyncio.run(run())
    assert a2.state == MISS                                   # a's running fetch stored nothing
    assert b2.state == HIT and b2.value in ({"v": 1}, {"v": 2})   # b's was kept
    assert up.calls == 3


def test_invalidate_all_still_drops_every_running_fetch() -> None:
    clock, up = Clock(), Upstream(delay=0.05)
    c = _cache(clock)

    async def run() -> tuple[Served, Served]:
        a = asyncio.ensure_future(c.get("a", up))
        b = asyncio.ensure_future(c.get("b", up))
        await asyncio.sleep(0.01)
        c.invalidate("a")
        c.invalidate()
        await asyncio.gather(a, b)
        return await c.get("a", up), await c.get("b", up)
    a2, b2 = asyncio.run(run())
    assert a2.state == MISS and b2.state == MISS and up.calls == 4
