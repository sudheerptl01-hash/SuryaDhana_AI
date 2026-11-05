"""
Price alerts, server-side: "tell me when TCS goes above 2,200 or below 2,050", checked every minute in market
hours by the master controller (POST /api/alerts/run), so they fire with the terminal closed. A crossed level fires
once (macOS notification + Telegram via the controller, and a toast in WTCH) and is removed. Not a broker order.

GET  /api/alerts                levels + recent hits
PUT  /api/alerts/{sym}          {"above": 2200 | null, "below": 2050 | null, "yahoo": "TCS.NS"}  (both null → delete)
POST /api/alerts/run            price every alerted symbol (Yahoo, ≈1 min delayed) and fire crossings → {"hits": [...]}
Storage: <data>/price_alerts.json (ALERTS_PATH overrides), written atomically.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
_lock = threading.Lock()
HISTORY_MAX = 50
_SYM = re.compile(r"^[A-Za-z0-9&^.=_-]{1,30}$")


def _path() -> Path:
    env = os.environ.get("ALERTS_PATH", "").strip()
    if env:
        return Path(env)
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "price_alerts.json"
    return Path("price_alerts.json")


def _read() -> dict[str, Any]:
    p = _path()
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        d = {}
    return {"alerts": d.get("alerts", {}), "history": d.get("history", [])}


def _write(d: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


LEVEL_KEYS = ("above", "below", "move")


def check_levels(alerts: dict[str, dict[str, Any]], prices: dict[str, Optional[float]], now: Optional[str] = None,
                 changes: Optional[dict[str, Optional[float]]] = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Pure: crossed levels → hits; crossed sides are removed, symbols with no level left are dropped. `move` fires
    when today's change (vs NSE's official previous close, from `changes`) reaches ±move %."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    left: dict[str, dict[str, Any]] = {}
    hits: list[dict[str, Any]] = []
    for sym, lv in alerts.items():
        lv = dict(lv)
        p = prices.get(sym)
        if p is not None and p == p:
            if lv.get("above") is not None and p >= lv["above"]:
                hits.append({"sym": sym, "side": "above", "level": lv["above"], "price": p, "at": now})
                lv.pop("above")
            if lv.get("below") is not None and p <= lv["below"]:
                hits.append({"sym": sym, "side": "below", "level": lv["below"], "price": p, "at": now})
                lv.pop("below")
            ch = (changes or {}).get(sym)
            if lv.get("move") is not None and ch is not None and abs(ch) >= lv["move"]:
                hits.append({"sym": sym, "side": "move", "level": lv["move"], "price": p, "change_pct": round(ch, 2), "at": now})
                lv.pop("move")
        if any(lv.get(k) is not None for k in LEVEL_KEYS):
            left[sym] = lv
    return left, hits


class Levels(BaseModel):
    above: Optional[float] = Field(None, gt=0)
    below: Optional[float] = Field(None, gt=0)
    move: Optional[float] = Field(None, gt=0, le=50)        # ± % day move vs the official previous close
    yahoo: Optional[str] = Field(None, max_length=30)


@router.get("")
def list_alerts() -> dict[str, Any]:
    with _lock:
        return _read()


@router.put("/{sym}")
def set_alert(sym: str, body: Levels) -> dict[str, Any]:
    if not _SYM.match(sym) or (body.yahoo and not _SYM.match(body.yahoo)):
        raise HTTPException(status_code=400, detail="bad symbol")
    with _lock:
        d = _read()
        if "move" not in body.model_fields_set:      # older callers (WTCH 🔔) send only above/below: keep a move level
            body.move = d["alerts"].get(sym, {}).get("move")
        if body.above is None and body.below is None and body.move is None:
            d["alerts"].pop(sym, None)
        else:
            d["alerts"][sym] = {k: v for k, v in (("above", body.above), ("below", body.below), ("move", body.move),
                                                  ("yahoo", body.yahoo or d["alerts"].get(sym, {}).get("yahoo") or f"{sym}.NS"))
                                if v is not None}
        _write(d)
        return d


@router.post("/run")
async def run_alerts() -> dict[str, Any]:
    """Price every alerted symbol and fire the crossings (called every minute in market hours by the scheduler).

    Prices with FRESH quotes only (each under news_scanner.QUOTE_REFRESH_AFTER_S, 30 s, old): the quote cache's
    stale-while-revalidate answer is for display, and at the scheduler's 60 s cadence it would always be the
    previous minute's quote (round 3 review, major)."""
    from routers.news_scanner import get_quotes
    with _lock:
        alerts = _read()["alerts"]
    if not alerts:
        return {"hits": [], "checked": 0}
    yahoo = {sym: lv.get("yahoo") or f"{sym}.NS" for sym, lv in alerts.items()}
    quotes: dict[str, Any] = {}
    ys = sorted(set(yahoo.values()))
    for i in range(0, len(ys), 60):
        quotes.update((await get_quotes(symbols=",".join(ys[i:i + 60]), fresh=True))["quotes"])
    prices = {sym: (quotes.get(y) or {}).get("price") if (quotes.get(y) or {}).get("available") else None for sym, y in yahoo.items()}
    changes = {sym: (quotes.get(y) or {}).get("change_pct") if (quotes.get(y) or {}).get("available") else None for sym, y in yahoo.items()}
    with _lock:                                   # re-read: levels may have changed while we priced
        d = _read()
        left, hits = check_levels(d["alerts"], prices, changes=changes)
        if hits:
            d["alerts"] = left
            d["history"] = (hits + d["history"])[:HISTORY_MAX]
            _write(d)
    return {"hits": hits, "checked": len(alerts), "priced": sum(p is not None for p in prices.values())}



@router.get("/feed")
def notification_feed(limit: int = 50) -> dict[str, Any]:
    """The notifications the scheduler sent (price, move, filing, wrap), newest first: <data>/notifications.jsonl."""
    p = _path().with_name("notifications.jsonl")
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 500)):]
    except OSError:
        return {"items": []}
    items = []
    for ln in reversed(lines):
        try:
            items.append(json.loads(ln))
        except ValueError:
            continue
    return {"items": items}
