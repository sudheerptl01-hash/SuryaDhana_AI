"""
Live quotes with honest fallback (Bloomberg program F3.2, amendment A1).

`GET /api/quotes/live?symbols=` (alias `/api/quotes/ticks`, the F3.2/UIX name — one handler):
merges data-service L1 ticks (fresh ≤ 5 s → source "icici-ws") with the EXISTING Yahoo quote path
(source "yahoo") per symbol. Asking is subscribing (A1): the request's symbols ∪ the saved holdings
are pushed to data-service's ensure-on-GET endpoint on every poll — idempotent, 2 s cadence bounds
churn, and restarts of either service self-heal within one poll. No frontend POST exists.

Quota safety (F3.4): the fallback is `news_scanner.get_quotes` (Yahoo) — this module adds **zero**
ICICI REST quote calls.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Query

from routers.news_scanner import get_quotes as _yahoo_quotes   # existing Yahoo path — reused, not duplicated

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
FRESH_S = 5.0
MAX_SYMBOLS = 60


def _holdings_symbols() -> list[str]:
    """Saved broker book — always unioned into the ensure set (A1: holdings pinned)."""
    try:
        raw = json.loads((Path(__file__).resolve().parents[3] / "data" / "last_holdings.json").read_text())
        return [p.get("symbol", "") for p in raw.get("positions", []) if p.get("symbol")]
    except (OSError, ValueError):
        return []


def _norm(symbols: str) -> list[str]:
    out: list[str] = []
    for s in symbols.split(","):
        s = s.strip().upper().replace(".NS", "")
        if s and s not in out:
            out.append(s)
    return out[:MAX_SYMBOLS]


@router.get("/live")
@router.get("/ticks")
async def live_quotes(symbols: str = Query(..., min_length=1, max_length=1500)) -> dict:
    """Per symbol: {price, chg_pct, source: "icici-ws"|"yahoo", as_of} (+hint on a clamped move);
    global {connected, state} describe the tick feed. Feed off/stale/unreachable ⇒ every symbol
    degrades to Yahoo — the panel keeps prices either way and the chip tells the truth."""
    syms = _norm(symbols)
    ask = list(dict.fromkeys(syms + _holdings_symbols()))[: MAX_SYMBOLS]
    ticks: dict = {}
    state, connected = "OFF", False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{DATA_SVC}/live/ticks", params={"symbols": ",".join(ask)})
        if r.status_code == 200:
            payload = r.json()
            state = payload.get("state", "OFF")
            connected = bool(payload.get("connected"))
            ticks = payload.get("ticks") or {}
    except httpx.HTTPError:
        state = "UNREACHABLE"

    out: dict[str, dict] = {}
    misses: list[str] = []
    for s in syms:
        t = ticks.get(s) or {}
        age = t.get("ts_age_s")
        if t.get("price") is not None and age is not None and age <= FRESH_S:
            row = {"price": t["price"], "chg_pct": t.get("chg_pct"), "as_of": t.get("as_of"),
                   "source": "icici-ws"}
            if t.get("hint"):
                row["hint"] = t["hint"]
            out[s] = row
        else:
            misses.append(s)

    if misses:
        y = await _yahoo_quotes(symbols=",".join(f"{s}.NS" for s in misses))
        quotes = y.get("quotes") or {}
        for s in misses:
            q = quotes.get(f"{s}.NS") or {}
            out[s] = {"price": q.get("price"), "chg_pct": q.get("change_pct"),
                      "as_of": y.get("as_of"), "source": "yahoo"}

    # Wire key is `ticks` — the B4 contract ui/lib/liveTicks.ts parses (build_b4.md §cross-builder).
    # Shipping this as `quotes` left the UI permanently tickless (bloomberg_verdict defect #1).
    return {"connected": connected, "state": state,
            "as_of": datetime.now().isoformat(timespec="seconds"), "ticks": out}
