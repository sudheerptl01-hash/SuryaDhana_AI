"""
Live ticks overlay (Bloomberg program F3.2, amendment A1), aligned with the live NSE contract (LV-API, 5 Nov 2026).

`GET /api/quotes/ticks?symbols=` (alias `/api/quotes/live`, one handler) is the overlay ui/lib/liveTicks.ts polls
every 2 s (stock window, DESK book, WTCH rows). It reads the SAME per-symbol hub as `/api/live/quotes`
(routers/live.py -> data-service `/live/quotes`: Breeze websocket tick -> NSE website -> last EOD close), so an NSE
symbol is never priced from Yahoo here (inventory defect D4: Yahoo rows inside this map overwrote broker prices).

Rows in `ticks`: only prices a consumer may paint OVER its own base layer -- state `live` (Breeze tick), `delayed`
(NSE website, about a minute old) or `closed` (after the session). `stale` (an EOD close during the session) and
`unavailable` rows are left out, so the consumer keeps what it has (the stock window's REST quote, the Desk's mark).
Each row carries `state`, `age_s`, `ltt` and the contract source in `feed`; `source` stays the wire value
liveTicks.ts keys its row-truth rule on (`icici-ws` for a Breeze tick, otherwise the contract source).

Asking is subscribing (A1): data-service ensures every requested symbol (union + TTL; it pins holdings, the NIFTY 50 /
NIFTY BANK members and the watchlist itself). Quota safety (F3.4): no Breeze REST call and no Yahoo call here.
"""
from __future__ import annotations

import asyncio
from typing import Any

from cache import cache_headers
from fastapi import APIRouter, Query, Response

from routers import live

router = APIRouter()

MAX_SYMBOLS = live.MAX_SYMBOLS
TICK_STATES = frozenset({"live", "delayed", "closed"})
_WIRE_SOURCE = {"breeze_ws": "icici-ws"}          # the B4 wire value for a broker tick (liveTicks.ts parse())


def _norm(symbols: str) -> list[str]:
    """Tolerant (as before): unknown entries are skipped, '.NS' dropped, order kept, at most MAX_SYMBOLS."""
    out: list[str] = []
    for s in symbols.split(","):
        try:
            sym = live.normalize_symbol(s)
        except ValueError:
            continue
        if sym not in out:
            out.append(sym)
    return out[:MAX_SYMBOLS]


def tick_row(row: dict[str, Any], as_of: str) -> dict[str, Any] | None:
    """One live-contract row -> the overlay row, or None when the consumer should keep its own price."""
    if row.get("price") is None or row.get("state") not in TICK_STATES:
        return None
    src = row.get("source")
    day = row.get("date") if isinstance(row.get("date"), str) and len(row["date"]) == 10 else None
    when = row.get("ltt") or (f"{day}T15:30:00+05:30" if src == "eod" and day else as_of)   # a close is dated, not "now"
    out: dict[str, Any] = {"price": row["price"], "chg_pct": row.get("change_pct"), "prev_close": row.get("prev_close"),
                           "ttq": row.get("volume"), "as_of": when,
                           "source": _WIRE_SOURCE.get(src, src) if isinstance(src, str) else None, "feed": src,
                           "state": row["state"], "age_s": row.get("age_s"), "ltt": row.get("ltt")}
    for k in ("hint", "reason"):
        if row.get(k):
            out[k] = row[k]
    return out


@router.get("/live")
@router.get("/ticks")
async def live_quotes(symbols: str = Query(..., min_length=1, max_length=12000),
                      response: Response = None) -> dict[str, Any]:  # type: ignore[assignment]  # injected by FastAPI
    """{connected, state, as_of, market, ticks: {SYM: {price, chg_pct, prev_close, ttq, as_of, source, feed, state,
    age_s, ltt, hint?, reason?}}}; `state` / `connected` describe the Breeze tick engine (data-service /live/status;
    UNREACHABLE when it cannot be read). Wire key `ticks` (the B4 contract) -- never rename it."""
    syms = _norm(symbols)
    if not syms:
        status = await live.status_or_none()
        state = status["state"] if status else "UNREACHABLE"
        return {"connected": state == "LIVE", "state": state, "as_of": live.now_ist().isoformat(timespec="seconds"),
                "market": None, "ticks": {}}
    snap, status = await asyncio.gather(live.hub().quotes(syms), live.status_or_none())
    payload = snap.payload
    ticks: dict[str, dict[str, Any]] = {}
    for s in syms:
        t = tick_row(payload["quotes"].get(s) or {}, payload["as_of"])
        if t is not None:
            ticks[s] = t
    state = status["state"] if status else "UNREACHABLE"
    cache_headers(response, snap.served)
    # Wire key is `ticks` -- the B4 contract ui/lib/liveTicks.ts parses (build_b4.md §cross-builder).
    # Shipping this as `quotes` left the UI permanently tickless (bloomberg_verdict defect #1).
    return {"connected": state == "LIVE", "state": state, "as_of": payload["as_of"], "market": payload["market"],
            "ticks": ticks}
