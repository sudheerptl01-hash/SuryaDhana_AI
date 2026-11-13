"""DERV › RADAR — the options flow radar (FINAL ROUND wave E, E-RADAR; PLAN W7 / F-16).

One read:

  GET /flow-radar/{symbol}?date=&expiry=&window_min=   per strike over a rolling window (default 30 min): the OI change,
                                                        OI now, and — only when the store serves per-strike volume — the
                                                        day's volume ÷ OI; beside it the ATM IV, PCR and max-pain change
                                                        over the same window from the tape's full-resolution path.

Everything is computed from the EXISTING 2-minute tape read (data-service ``/db/fo-iv/oi-tape/{symbol}``, the same store
OMON › LIVE shows) through the process-wide client and one stale-while-revalidate cache — no new table, no new job, no
publisher on the request path (store, then show).

Honesty rules (binding, PLAN §1 + WAVE E scope): every number is ``context`` (no ``signal`` badge exists); the copy is a
fact pattern ("OI rose 41.2 k at 25,900 CE in 28 min — describes, does not predict"), never a writers/buyers story and
never a direction word; when the tape gapped the gap is SHOWN and the change spans the stored window with its actual
length named — never interpolated, never scaled to a per-30-minute rate. The tape's time-lapse frames are a sample
(≤ 48 of the day's snapshots), so the baseline is the nearest STORED frame at or before the window mark and the payload
says how long the span really is. Per-strike IV and volume are not stored in the tape read today: the IV change shown is
the ATM path's (labelled so), and vol ÷ OI renders only when the store serves volume (a PM patch request adds the
passthrough; nothing is invented here). Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a
ticket price.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from cache import SWRCache, TTLCache, cache_headers
from errors import fail
from fastapi import APIRouter, Query, Response
from routers.expiry import COVERAGE, chip as tape_chip  # the tape's own chip rule: stored snapshots are DELAYED, never LIVE

from shared.http_client import UpstreamError, get_json

router = APIRouter()
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
_SYMBOL = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")
_DATE = r"^\d{4}-\d{2}-\d{2}$"

RADAR = SWRCache("flow_radar.tape", max_items=64, refresh_after=30.0, max_age=300.0)
DOWN_TTL_S = 20.0
_down = TTLCache("flow_radar.down", max_items=16, default_ttl=DOWN_TTL_S)

DESCRIBES = "describes, does not predict"
WINDOW_MIN_DEFAULT = 30
GAP_MIN = 10.0            # a hole > 10 min in the stored tape is a gap (the same threshold as the D-PIPE tape_gap alarm)
MOVERS_TOP = 8
BADGES = {"oi_delta": "context", "vol_oi": "context", "iv_change": "context", "pcr": "context", "max_pain": "context",
          "tape": "context"}
VOL_OI_NOTE = ("per-strike volume is not stored in the tape read yet — vol ÷ OI renders when the store serves it; "
               "nothing is invented here")
FRAMES_NOTE = ("the OI baseline is the nearest stored time-lapse frame at or before the window mark (the frames are a "
               "sample of the day's snapshots) — the span's real length is in window.actual_min, never interpolated")


def _check_symbol(symbol: str) -> str:
    if not _SYMBOL.fullmatch(symbol or ""):
        fail(422, "invalid", f"Bad symbol {symbol!r}", "NSE underlyings look like NIFTY, BANKNIFTY, RELIANCE")
    return symbol.upper()


class _Unavailable(RuntimeError):
    pass


async def _fetch(path: str, params: dict[str, Any]) -> Any:
    try:
        return await get_json(f"{DATA_SVC}{path}", route="read", params=params)
    except UpstreamError as exc:
        if exc.status_code == 404:
            raise _Unavailable("data-service does not serve the tape read yet (404): the W2-TAPE routes are not deployed") from exc
        raise _Unavailable(f"data-service {exc.status_code}: {str(exc.detail)[:160]}") from exc


async def _read(path: str, response: Response | None, **params: Any) -> tuple[dict[str, Any] | None, str | None]:
    clean = {k: v for k, v in params.items() if v is not None}
    key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
    down = _down.get("down:oi-tape")
    if down is not None:
        return None, str(down)
    try:
        served = await RADAR.get(key, lambda: _fetch(path, clean))
    except _Unavailable as exc:
        _down.set("down:oi-tape", str(exc), ttl=DOWN_TTL_S)
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — a bad body is a store problem, not a page problem
        return None, type(exc).__name__
    cache_headers(response, served)
    value = served.value
    return (value if isinstance(value, dict) else None), (None if isinstance(value, dict) else "unexpected body")


# ── pure helpers (unit-tested in tests/test_flow_radar.py) ───────────────────────────────────────────────────────────

def parse_ts(iso: Any) -> datetime | None:
    """A tape stamp (ISO, UTC with offset) as an aware datetime; None when unparsable."""
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)


def ist_clock(t: datetime) -> str:
    return (t.astimezone(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%H:%M")


def pick_base(stamps: Sequence[datetime], window_min: float) -> int | None:
    """The baseline index for a rolling window ending at the last stamp: the LATEST stamp at or before
    (last − window). A tape shorter than the window keeps its first stamp (the caller reports the actual span —
    honesty lives in the window block, not in stretching data). None with fewer than 2 stamps."""
    if len(stamps) < 2:
        return None
    target = stamps[-1] - timedelta(minutes=window_min)
    base = 0
    for i, t in enumerate(stamps):
        if t <= target:
            base = i
        else:
            break
    return base


def find_gaps(stamps: Sequence[datetime], gap_min: float = GAP_MIN) -> list[dict[str, Any]]:
    """Holes between consecutive stored stamps longer than ``gap_min`` — shown, never filled."""
    out = []
    for a, b in zip(stamps, stamps[1:], strict=False):  # the tail is one shorter by construction
        m = (b - a).total_seconds() / 60.0
        if m > gap_min:
            out.append({"from_ist": ist_clock(a), "to_ist": ist_clock(b), "minutes": round(m, 1)})
    return out


def window_block(stamps: Sequence[datetime], requested_min: float, gap_min: float = GAP_MIN) -> dict[str, Any]:
    """What the rolling window REALLY spans over the stored stamps: the baseline index, the actual length, and an
    honest note whenever the span is not the requested one (short tape, sampled frames, or a gap inside it)."""
    base = {"requested_min": requested_min, "actual_min": None, "from_ist": None, "to_ist": None, "from_ts": None,
            "to_ts": None, "base_index": None, "gapped": False, "note": None}
    if not stamps:
        return {**base, "note": "no snapshot stored"}
    if len(stamps) < 2:
        return {**base, "to_ist": ist_clock(stamps[-1]), "note": "only one stored snapshot — no change computable yet"}
    i = pick_base(stamps, requested_min)
    assert i is not None
    actual = (stamps[-1] - stamps[i]).total_seconds() / 60.0
    inner = find_gaps(stamps[i:], gap_min)
    note = None
    if inner:
        g = inner[0]
        note = (f"the tape gapped inside the window ({g['from_ist']} → {g['to_ist']} IST, {g['minutes']} min): the change "
                f"spans {round(actual, 1)} min of stored tape — shown as stored, never interpolated")
    elif actual < requested_min - gap_min:
        note = f"the stored tape covers only {round(actual, 1)} min so far — the change is over that span, not {requested_min:g} min"
    elif actual > requested_min + gap_min:
        note = (f"the nearest stored snapshot before the {requested_min:g}-minute mark is {round(actual, 1)} min old — "
                "the change spans it, never interpolated")
    return {**base, "actual_min": round(actual, 1), "from_ist": ist_clock(stamps[i]), "to_ist": ist_clock(stamps[-1]),
            "from_ts": stamps[i].isoformat(), "to_ts": stamps[-1].isoformat(), "base_index": i,
            "gapped": bool(inner) or abs(actual - requested_min) > gap_min, "note": note}


def _at(frame: dict[str, Any] | None, side: str, j: int) -> float | None:
    arr = (frame or {}).get(side) or []
    v = arr[j] if j < len(arr) else None
    return float(v) if isinstance(v, (int, float)) else None


def oi_ladder(strikes_rows: list[dict[str, Any]], frames: list[dict[str, Any]], base_index: int | None) -> list[dict[str, Any]]:
    """Per strike (the tape's own axis — ``frames`` arrays are aligned to ``strikes`` rows): OI now, the change over the
    window (latest frame − baseline frame; None when either side is missing — a hole stays a hole), the latest mids, and
    vol ÷ OI when the store serves per-strike volume (``{side}_volume`` on the strikes rows; day-cumulative)."""
    last = frames[-1] if frames else None
    basef = frames[base_index] if frames and base_index is not None and 0 <= base_index < len(frames) else None
    rows: list[dict[str, Any]] = []
    for j, r in enumerate(strikes_rows):
        row: dict[str, Any] = {"strike": r.get("strike")}
        for side in ("ce", "pe"):
            now = _at(last, side, j)
            if now is None and isinstance(r.get(f"{side}_oi"), (int, float)):
                now = float(r[f"{side}_oi"])
            then = _at(basef, side, j)
            row[f"{side}_oi"] = now
            row[f"{side}_d"] = round(now - then, 1) if now is not None and then is not None else None
            row[f"{side}_mid"] = r.get(f"{side}_mid")
            vol = r.get(f"{side}_volume")
            row[f"{side}_vol_oi"] = (round(float(vol) / now, 3)
                                     if isinstance(vol, (int, float)) and now is not None and now > 0 else None)
        rows.append(row)
    return rows


def fmt_shares(v: float) -> str:
    """A compact share count for the fact lines (exchange unit): 41.2 k / 1.3 L / 2.1 cr."""
    a = abs(v)
    if a >= 1e7:
        return f"{a / 1e7:.1f} cr"
    if a >= 1e5:
        return f"{a / 1e5:.1f} L"
    if a >= 1e3:
        return f"{a / 1e3:.1f} k"
    return f"{a:.0f}"


def movers(ladder: list[dict[str, Any]], actual_min: float | None, top: int = MOVERS_TOP) -> list[dict[str, Any]]:
    """The largest |OI change| per (strike, side) with its fact line — a fact about open interest, never a story about
    who traded or which way anything is headed."""
    cand: list[dict[str, Any]] = []
    for r in ladder:
        for side in ("ce", "pe"):
            d = r.get(f"{side}_d")
            if d is None or d == 0 or r.get("strike") is None:
                continue
            cand.append({"strike": r["strike"], "side": side.upper(), "oi_delta": d, "oi_now": r.get(f"{side}_oi"),
                         "vol_oi": r.get(f"{side}_vol_oi")})
    cand.sort(key=lambda c: -abs(c["oi_delta"]))
    out = cand[:top]
    span = f" in {actual_min:g} min" if actual_min else ""
    for c in out:
        verb = "rose" if c["oi_delta"] > 0 else "fell"
        c["line"] = f"OI {verb} {fmt_shares(abs(c['oi_delta']))} at {c['strike']:,.0f} {c['side']}{span} — {DESCRIBES}"
    return out


def path_change(path: list[dict[str, Any]], key: str, window_min: float, dp: int = 2) -> dict[str, Any] | None:
    """now / then / delta of one path series (the tape's FULL-resolution path, not the sampled frames) over the rolling
    window, with its own actual span — the path and the frames can cover different stamps, so each says its own."""
    pts = []
    for p in path:
        t = parse_ts(p.get("ts"))
        v = p.get(key)
        if t is not None and isinstance(v, (int, float)):
            pts.append((t, float(v)))
    if len(pts) < 2:
        return None
    stamps = [t for t, _ in pts]
    i = pick_base(stamps, window_min)
    assert i is not None
    actual = (stamps[-1] - stamps[i]).total_seconds() / 60.0
    now, then = pts[-1][1], pts[i][1]
    return {"now": round(now, dp), "then": round(then, dp), "delta": round(now - then, dp),
            "from_ist": ist_clock(stamps[i]), "to_ist": ist_clock(stamps[-1]), "actual_min": round(actual, 1)}


def shape(body: dict[str, Any] | None, symbol: str, err: str | None, window_min: float,
          now: datetime | None = None) -> dict[str, Any]:
    """The radar payload from one tape body; an unavailable store keeps the shape with ``ok: false``."""
    b = body or {}
    path = [p for p in (b.get("path") or []) if isinstance(p, dict)]
    frames = [f for f in (b.get("frames") or []) if isinstance(f, dict)]
    strikes_rows = [r for r in (b.get("strikes") or []) if isinstance(r, dict)]
    frame_stamps = [t for t in (parse_ts(f.get("ts")) for f in frames) if t is not None]
    window = window_block(frame_stamps, window_min)
    ladder = oi_ladder(strikes_rows, frames, window.get("base_index"))
    path_stamps = [t for t in (parse_ts(p.get("ts")) for p in path) if t is not None]
    last = path[-1] if path else None
    iv = path_change(path, "atm_iv", window_min)
    vol_oi_available = any(isinstance(r.get("ce_volume"), (int, float)) or isinstance(r.get("pe_volume"), (int, float))
                           for r in strikes_rows)
    snaps = int(b.get("snapshots") or 0)
    return {"symbol": symbol, "date": b.get("date"), "expiry": b.get("expiry"), "expiries": b.get("expiries") or [],
            "lot": b.get("lot"), "dte_calendar": b.get("dte_calendar"),
            "window": window, "gaps": find_gaps(path_stamps), "ladder": ladder,
            "movers": movers(ladder, window.get("actual_min")),
            "forward": (last or {}).get("forward"),
            "atm_iv": None if iv is None else {**iv, "label": "ATM IV from the tape's path (the floating-ATM read); "
                                                              "per-strike IV is not stored in this read"},
            "pcr": path_change(path, "pcr", window_min, dp=3),
            "max_pain": path_change(path, "max_pain", window_min, dp=0),
            "vol_oi_available": vol_oi_available, "vol_oi_note": None if vol_oi_available else VOL_OI_NOTE,
            "snapshots": snaps, "first": b.get("first"), "last": b.get("last"), "last_ts": b.get("last_ts"),
            "median_gap_min": b.get("median_gap_min"), "source": b.get("source") or "OFFLINE",
            "units": b.get("units") or {}, "model_version": b.get("model_version"),
            "frames_note": FRAMES_NOTE, "chip": tape_chip(b, b.get("last_ts"), snaps, now), "badges": BADGES,
            "coverage": COVERAGE,
            "note": ("Flow radar over the stored 2-minute tape: per strike the OI change in the rolling window, the "
                     "day's volume ÷ OI where the store serves volume, and the ATM IV / PCR / max-pain change over the "
                     f"same window; gaps are shown, never interpolated; {DESCRIBES}"),
            "ok": err is None, "store_errors": {"oi-tape": err} if err else {}}


@router.get("/flow-radar/{symbol}")
async def flow_radar(symbol: str, response: Response, date_: str | None = Query(None, alias="date", pattern=_DATE),
                     expiry: str | None = Query(None, pattern=_DATE),
                     window_min: int = Query(WINDOW_MIN_DEFAULT, ge=5, le=240)) -> dict:
    """The flow radar for one underlying (default: today's or the latest stored session, nearest expiry, 30-minute window)."""
    sym = _check_symbol(symbol)
    body, err = await _read(f"/db/fo-iv/oi-tape/{sym}", response, date=date_, expiry=expiry)
    return shape(body, sym, err, float(window_min))
