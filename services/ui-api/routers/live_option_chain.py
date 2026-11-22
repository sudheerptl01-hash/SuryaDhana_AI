"""The live option chain for OMON / OSTR / BRF (owner-approved 22 Nov 2026): ``GET /api/live/option-chain/{symbol}``.

Mounted at ``/api/live`` beside ``/api/live/quotes``: it mirrors data-service's ``/live/option-chain/{symbol}`` the way
``/api/live/quotes`` mirrors ``/live/quotes``. Query: ``expiry`` (YYYY-MM-DD, optional) and ``width`` (strikes either
side of the money that carry the Breeze overlay, 1-20, optional: data-service's default when absent).

* **Primary**: data-service ``/live/option-chain/{symbol}`` (services/data-service/live_chain.py): NSE's option-chain v3
  frame (else the last F&O bhavcopy) with the Breeze websocket ticks overlaid on ATM +/- width, recomputed by the one
  ``option_chain.chain()``. The body passes through UNCHANGED (rows, per-side ``source`` / ``age_s`` / ``tick_state`` /
  bid / ask, the chain-level ``feed`` block) plus two keys: ``served_by: "live_chain"`` and ``fallback_reason: null``.
* **Fallback**: data-service ``/db/option-chain-live/{symbol}`` (NSE's v3 chain, about a minute behind, never live; the
  paper book's mark source) when the live route answers 404 (not deployed yet, or no chain), 5xx, a transport error, an
  open breaker or a body without rows. Its body passes through with ``served_by: "nse_fallback"`` and
  ``fallback_reason`` (why the live route was not used). It carries no ``feed`` block, so the UI labels it DELAYED · NSE.
* Both through the process-wide client (``shared.http_client.get_json``; no AsyncClient per call). The live read has a
  short timeout and a breaker of its own (``UPSTREAM``), so a slow or failing live chain never opens the breaker of
  every other data-service read; the fallback is an ordinary data-service read. No stale-serve: an old live chain is
  never served as if it were current (the fallback is the honest answer).
* A live route that answers FastAPI's bare 404 ("Not Found": data-service not redeployed yet) is not asked again for
  ``ROUTE_MISSING_S``; requests in that window go straight to the fallback and say so.
* Both upstreams failing: 503 (or the upstream's 4xx) naming both reasons; the UI then shows the end-of-day chain.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from errors import code_for_status, fail
from fastapi import APIRouter, Query

from routers.live import data_svc
from shared.http_client import UpstreamError, get_json

router = APIRouter()

UPSTREAM = "data-service-live-chain"      # breaker name: a failing live chain never opens the other reads' breaker
LIVE_TIMEOUT = httpx.Timeout(8.0, connect=2.0)   # data-service memoises 1 s; a cold first compute may need NSE (8 s)
ROUTE_MISSING_S = 60.0                    # a bare 404 (route not deployed) is re-probed after this long
SERVED_LIVE, SERVED_FALLBACK = "live_chain", "nse_fallback"
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")       # data-service's own symbol rule
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

_clock: Callable[[], float] = time.monotonic
_route_missing_until = 0.0


def reset_for_tests() -> None:
    global _route_missing_until
    _route_missing_until = 0.0


def _route_missing(exc: UpstreamError) -> bool:
    """FastAPI's bare 404 for an unknown path (data-service without /live/option-chain), not the route's own 404."""
    return exc.status_code == 404 and exc.detail.strip() == "Not Found"


def _usable(body: Any) -> bool:
    return isinstance(body, dict) and body.get("found") is not False and isinstance(body.get("rows"), list)


async def _live(sym: str, params: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """(body, None) from the live route, or (None, why it was not used)."""
    global _route_missing_until
    if _clock() < _route_missing_until:
        return None, "data-service has no /live/option-chain yet (HTTP 404: not deployed)"
    try:
        body = await get_json(f"{data_svc()}/live/option-chain/{sym}", route="live", params=params or None,
                              upstream=UPSTREAM, timeout=LIVE_TIMEOUT)
    except UpstreamError as exc:
        if exc.status_code == 422:
            fail(422, "invalid", f"live option chain: {exc.detail}"[:300], "symbol like NIFTY or RELIANCE; expiry YYYY-MM-DD")
        if _route_missing(exc):
            _route_missing_until = _clock() + ROUTE_MISSING_S
            return None, "data-service has no /live/option-chain yet (HTTP 404: not deployed)"
        return None, f"live chain unavailable (HTTP {exc.status_code}: {exc.detail})"[:300]
    if not _usable(body):
        return None, "live chain answered without rows"
    return body, None


@router.get("/option-chain/{symbol}")
async def live_option_chain(symbol: str, expiry: str | None = Query(None, pattern=DATE_PATTERN),
                            width: int | None = Query(None, ge=1, le=20)) -> dict[str, Any]:
    """The live option chain (see the module docstring): the Breeze-overlaid chain when data-service serves it, else
    NSE's v3 chain; ``served_by`` says which, ``fallback_reason`` why."""
    if not _SYMBOL_RE.fullmatch(symbol):
        fail(422, "invalid", f"Bad symbol {symbol!r}", "NSE F&O underlyings look like NIFTY, BANKNIFTY, RELIANCE, M&M")
    sym = symbol.upper()
    params: dict[str, Any] = {}
    if expiry:
        params["expiry"] = expiry
    if width is not None:
        params["width"] = width
    body, why = await _live(sym, params)
    if body is not None:
        return {**body, "served_by": SERVED_LIVE, "fallback_reason": None}
    try:
        nse = await get_json(f"{data_svc()}/db/option-chain-live/{sym}", route="read",
                             params={"expiry": expiry} if expiry else None)
    except UpstreamError as exc:
        # a 4xx is the upstream saying no for this symbol / expiry (kept); anything else is the upstream being down
        status = exc.status_code if 400 <= exc.status_code < 500 else 503
        fail(status, "upstream_down" if status == 503 else code_for_status(status),
             f"{why}; NSE's option chain unavailable too (HTTP {exc.status_code}: {exc.detail})"[:400],
             "the end-of-day chain (/api/market/option-chain) still answers")
    if not isinstance(nse, dict):
        fail(503, "upstream_down", f"{why}; NSE's option chain answered without a body", None)
    return {**nse, "served_by": SERVED_FALLBACK, "fallback_reason": why}
