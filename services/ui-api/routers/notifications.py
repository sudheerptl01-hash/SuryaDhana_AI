"""Notification feed for the desktop shell (desktop review completeness-final-02 / K5).

GET /api/notifications/feed?since=<epoch ms | ISO-8601>&limit=<1..200>

The scheduler already produces every alert the app should show natively; nothing new is stored here, the
feed only reads what exists:

* ``<data>/notifications.jsonl``: one line per notification master-controller sent (``_notify_mac`` records
  every macOS banner first: price alerts, filings by your stocks, results numbers, market moves, closing and
  pre-market notes) plus the inbox-only records (nightly wrap, weekly journal). The header bell and ALRT read
  the same file through GET /api/alerts/feed.
* ``<data>/price_alerts.json`` history: every crossed WTCH level, written by POST /api/alerts/run. The
  scheduler announces the hits it fires itself, but a level crossed by a WTCH page's own check (lib/alerts.ts
  calls /run too) never reaches notifications.jsonl, so hits are read here as well.

A hit and the scheduler's notification of the same hit are ONE event: they are paired when the notification
is kind ``price``, its body is exactly the text master-controller formats for that hit (``hit_text``) and it
was recorded 0-15 min after the hit. The pair keeps the hit's id and time, so an event's id does not change
when the scheduler's line lands after the shell already saw the hit.

Item: ``{id, at, at_ms, kind, title, body, source, banner, tab}``
  id      stable for the life of the record: ``h-…`` (a price-alert hit) or ``n-…`` (a scheduler line), a
          digest of the record's own fields (an exact duplicate record gets a ``-2``, ``-3`` … suffix)
  at      ISO-8601 in IST; at_ms the same instant in epoch milliseconds
  kind    as recorded (price · move · filing · results · close · morning · wrap · journal · …)
  source  ``price_alert`` or ``scheduler``
  banner  True when the scheduler shows it as a macOS banner (False for the inbox-only wrap and journal)
  tab     the terminal page a click should open: watch (price-alert hits), filings (a filing by your stock),
          events (results numbers), brief (holding / NIFTY moves, closing and pre-market notes), wrap, alerts

Response: ``{items (newest first, at most limit), count, truncated, since, next_since, server_time_ms}``.
``since`` is inclusive (``at_ms >= since``). Poll contract for the shell: first call without ``since`` and
treat what comes back as already seen; afterwards pass ``next_since`` and de-duplicate by ``id``.
``next_since`` is the newest returned ``at_ms`` minus FEED_OVERLAP_MS (60 s), because the two files are written
by different processes and a record can land a few seconds after a later-stamped one. ``truncated`` says that
more than ``limit`` events matched (the oldest were left out). Read-only; both files are re-parsed only when
their size or mtime changes.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from errors import fail
from fastapi import APIRouter, Query

from routers import alerts as price_alerts

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
FEED_OVERLAP_MS = 60_000
PAIR_WINDOW_S = 900.0            # a scheduler line within 15 min after a hit, with the same text, is that hit
MAX_READ_BYTES = 512 * 1024      # notifications.jsonl is trimmed to ~400 KB by master-controller
DEFAULT_LIMIT, MAX_LIMIT = 50, 200
MAX_SINCE_DIGITS = 15            # epoch ms has 13 digits today
INBOX_ONLY_KINDS = frozenset({"wrap", "journal"})        # _record_notification only: never a macOS banner
TAB_BY_KIND = {"price": "watch", "move": "brief", "filing": "filings", "results": "events",
               "close": "brief", "morning": "brief", "wrap": "wrap", "journal": "alerts"}
HIT_TITLE = "SuryaDhana price alert"                     # master_controller.price_alerts_check's title


def hit_text(hit: dict[str, Any]) -> str | None:
    """The banner text master-controller's price_alerts_check formats for one hit (None if malformed)."""
    try:
        sym, side = str(hit["sym"]), hit["side"]
        if side == "move":
            return f"{sym} {float(hit['change_pct']):+.1f}% today (alert at ±{float(hit['level']):g}%, now ₹{float(hit['price']):,.2f})"
        if side in ("above", "below"):
            return (f"{sym} {'rose above' if side == 'above' else 'fell below'} "
                    f"₹{float(hit['level']):,.2f} (now ₹{float(hit['price']):,.2f})")
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _parse_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def parse_since(raw: str | None) -> int | None:
    """``since`` as epoch ms: ASCII digits are epoch milliseconds, anything else ISO-8601 (no offset = IST).
    Anything else is a 422, never a 500 (str.isdigit also accepts '²', which int() refuses)."""
    if raw is None or not raw.strip():
        return None
    v = raw.strip()
    if v.isascii() and v.isdigit():
        if len(v) > MAX_SINCE_DIGITS:                # past year 33658: not a time (and too big for an i64 consumer)
            fail(422, "invalid", "since must be epoch milliseconds or an ISO-8601 time")
        return int(v)
    dt = _parse_at(v)
    if dt is None:
        fail(422, "invalid", "since must be epoch milliseconds or an ISO-8601 time")
    return _ms(dt)


def _digest(prefix: str, fields: list[Any], seen: dict[str, int]) -> str:
    d = hashlib.sha256(json.dumps(fields, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]
    n = seen.get(d, 0) + 1
    seen[d] = n
    return f"{prefix}-{d}" if n == 1 else f"{prefix}-{d}-{n}"


def _event(eid: str, dt: datetime, kind: str, title: str, body: str, source: str) -> dict[str, Any]:
    return {"id": eid, "at": dt.astimezone(IST).isoformat(timespec="seconds"), "at_ms": _ms(dt), "kind": kind,
            "title": title, "body": body, "source": source, "banner": kind not in INBOX_ONLY_KINDS,
            "tab": TAB_BY_KIND.get(kind, "alerts")}


class _FileParse:
    """Re-parse a file only when its (size, mtime) changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple[str, int, int] | None = None
        self._value: list[dict[str, Any]] = []

    def get(self, path: Path, parse: Callable[[Path], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        try:
            st = path.stat()
        except OSError:
            return []
        key = (str(path), int(st.st_size), int(st.st_mtime_ns))
        with self._lock:
            if key == self._key:
                return self._value
        value = parse(path)
        with self._lock:
            self._key, self._value = key, value
        return value


_scheduler_cache = _FileParse()


def _read_tail(path: Path) -> list[str]:
    with path.open("rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        start = max(0, size - MAX_READ_BYTES)
        fh.seek(start)
        data = fh.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if start > 0 else lines          # a cut first line is partial


def scheduler_events(path: Path) -> list[dict[str, Any]]:
    """notifications.jsonl rows as events (file order); malformed lines are skipped."""
    try:
        lines = _read_tail(path)
    except OSError:
        return []
    seen: dict[str, int] = {}
    out = []
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        dt = _parse_at(rec.get("at"))
        if dt is None:
            continue
        kind, title, body = (str(rec.get(k) or "") for k in ("kind", "title", "body"))
        eid = _digest("n", [rec.get("at"), kind, title, body], seen)
        out.append(_event(eid, dt, kind or "alert", title, body, "scheduler"))
    return out


def hit_events(history: list[Any]) -> list[dict[str, Any]]:
    """price_alerts.json history hits as events (oldest first)."""
    seen: dict[str, int] = {}
    out = []
    for h in reversed(history):                    # history is newest first
        if not isinstance(h, dict):
            continue
        dt = _parse_at(h.get("at"))
        text = hit_text(h)
        if dt is None or text is None:
            continue
        eid = _digest("h", [h.get("sym"), h.get("side"), h.get("level"), h.get("price"), h.get("at"),
                            h.get("change_pct")], seen)
        out.append(_event(eid, dt, "price", HIT_TITLE, text, "price_alert"))
    return out


def merge_events(scheduler: list[dict[str, Any]], hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every event once, newest first: a scheduler 'price' line that announces a hit is folded into the hit."""
    open_hits = sorted(hits, key=lambda e: e["at_ms"])
    paired: set[str] = set()
    out = list(hits)
    for ev in sorted(scheduler, key=lambda e: e["at_ms"]):
        if ev["kind"] == "price":
            match = next((h for h in open_hits if h["id"] not in paired and h["body"] == ev["body"]
                          and 0 <= ev["at_ms"] - h["at_ms"] <= PAIR_WINDOW_S * 1000), None)
            if match is not None:
                paired.add(match["id"])
                continue
        out.append(ev)
    out.sort(key=lambda e: (-e["at_ms"], e["id"]))
    return out


def feed(since_ms: int | None, limit: int, *, now_ms: int | None = None) -> dict[str, Any]:
    alerts_path = price_alerts._path()
    scheduler = _scheduler_cache.get(alerts_path.with_name("notifications.jsonl"), scheduler_events)
    with price_alerts._lock:
        history = price_alerts._read()["history"]
    events = merge_events(scheduler, hit_events(history if isinstance(history, list) else []))
    if since_ms is not None:
        events = [e for e in events if e["at_ms"] >= since_ms]
    items = events[:limit]
    newest = items[0]["at_ms"] if items else None
    next_since = max(newest - FEED_OVERLAP_MS, since_ms or 0) if newest is not None else since_ms
    return {"items": items, "count": len(items), "truncated": len(events) > limit, "since": since_ms,
            "next_since": next_since, "server_time_ms": int(time.time() * 1000) if now_ms is None else now_ms}


@router.get("/feed")
def notification_feed(since: str | None = Query(None, max_length=40, description="epoch ms or ISO-8601; inclusive"),
                      limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)) -> dict[str, Any]:
    """Server-side alert events for native notifications, newest first (see the module docstring)."""
    return feed(parse_since(since), limit)
