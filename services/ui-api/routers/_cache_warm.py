"""Warm the slow-endpoint caches once after ui-api starts (desktop review C-PERF-01 / C-PERF-02).

After a restart every SWR cache is empty, so the first visit to BRF, EQS/WTCH, EVTS, SCRN or CMDT waited on the
same 0.7-3.6 s reads the caches exist to hide. WARM_DELAY_S after start-up (the loop is serving by then) one
background task runs, ONE AT A TIME so data-service is not hit with a burst, exactly the calls those pages make
first: results-recent for 5/7/10/95 days, results-implied-moves (10), the fundamentals screen (core) and the gold
desk's six Yahoo series (no broker call). Each call goes through the normal cached path and so fills the cache;
a failure is only counted (the page fetches it itself later, as before). One JSON line reports the outcome: a
healthy start logs ``"ok": 8, "failed": []`` (eight calls, incl. the gold overview). The gold step counts as failed, ``gold_yahoo_series:
<usable>/6``, when fewer than all six series came back (warm_series itself never raises).

Off with UI_API_CACHE_WARM=0, and never while pytest runs a test (shared.http_guard.in_test_mode).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

WARM_DELAY_S = 5.0
CALL_TIMEOUT_S = 90.0

log = logging.getLogger("suryadhana.cache_warm")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class WarmShortfall(Exception):
    """A warm-up call that answered but filled only part of its cache; str() is what the log shows (e.g. '2/6')."""


async def _gold_series() -> None:
    from routers import gold_preopen
    usable = await gold_preopen.warm_series()
    if usable < gold_preopen.WARM_SERIES_COUNT:
        raise WarmShortfall(f"{usable}/{gold_preopen.WARM_SERIES_COUNT}")


async def _gold_overview() -> None:
    """GOLD page frame (PLAN §d warm list): fills the 30 s memo and the gold store cache; no Breeze beyond mcx's cached quote."""
    from routers import gold
    await gold.overview()


def warm_calls() -> list[tuple[str, Callable[[], Awaitable[Any]]]]:
    from routers import markets
    return [
        ("results_recent_5", lambda: markets.results_recent(days=5)),          # BRF
        ("results_recent_7", lambda: markets.results_recent(days=7)),          # MKT
        ("results_recent_10", lambda: markets.results_recent(days=10)),        # EVTS
        ("results_recent_95", lambda: markets.results_recent(days=95)),        # EQS / WTCH (useCorpEvents)
        ("results_implied_moves_10", lambda: markets.results_implied_moves(days=10)),
        ("fundamentals_screen_core", lambda: markets.fundamentals_screen(limit=2500, fields="core")),
        ("gold_yahoo_series", _gold_series),
        ("gold_overview", _gold_overview),            # GOLD page frame (routers/gold.py)
    ]


async def warm(delay_s: float = WARM_DELAY_S,
               calls: list[tuple[str, Callable[[], Awaitable[Any]]]] | None = None) -> dict[str, Any]:
    """Run the warm-up calls one by one; never raises (cancellation aside)."""
    await asyncio.sleep(delay_s)
    started = time.monotonic()
    ok, failed = [], []
    for name, call in (warm_calls() if calls is None else calls):
        try:
            await asyncio.wait_for(call(), CALL_TIMEOUT_S)
            ok.append(name)
        except asyncio.CancelledError:
            raise
        except WarmShortfall as exc:
            failed.append(f"{name}:{exc}")
        except Exception as exc:  # noqa: BLE001 — a warm-up miss only means the first visit waits, as before
            failed.append(f"{name}:{type(exc).__name__}")
    summary = {"event": "cache_warm_done", "component": "cache_warm", "ok": len(ok), "failed": failed,
               "elapsed_s": round(time.monotonic() - started, 2)}
    with contextlib.suppress(Exception):
        log.info(json.dumps(summary))
    return summary


def start_from_env() -> asyncio.Task[dict[str, Any]] | None:
    """Schedule the warm-up on the running loop unless UI_API_CACHE_WARM=0 or a test is running."""
    if os.environ.get("UI_API_CACHE_WARM", "1").strip() == "0":
        return None
    try:
        from shared.http_guard import in_test_mode
        if in_test_mode():
            return None
    except ImportError:
        pass
    try:
        return asyncio.get_running_loop().create_task(warm(), name="ui-api-cache-warm")
    except RuntimeError:
        return None


async def stop(task: asyncio.Task[Any] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(BaseException):
        await task
