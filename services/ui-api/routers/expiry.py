"""OMON › LIVE tape + OMON › XPRY (Terminal v2 PLAN 2.1 and 2.4, builder W2-TAPE).

Two reads, both mounted at ``/api/derivatives`` beside ``routers/derivatives.py`` (no path overlaps):

  GET /iv/{symbol}/oi-tape?date=&expiry=   the intraday OI / IV tape: per snapshot the forward, ATM IV, the straddle at the
                                            floating ATM and at the day's opening strike, PCR, max pain; OI by strike at the
                                            open and now (both sides) with the latest bid / ask; the OI time-lapse frames
  GET /expiry-day?symbol=&date=            XPRY: on an expiry day the expiring series' OI unwind by strike, the max-pain path,
                                            today's straddle decay against the historical expiry-day curve (Breeze 1-minute
                                            replays), the pin-risk strikes; every day the next expiry and the
                                            implied-vs-realised scorecard of past expiries
  GET /replay?symbol=&expiry=              E-REPLAY (FINAL ROUND wave E, F-17): the practice simulator's stored tapes — the
                                            list of replayed expiries, or one expiry's 1-minute rows (minutes after 09:15
                                            IST, clock times only; the date-bearing fields sit at the top level so the
                                            client's date-hidden mode shows no date until the reveal)

Store, then show (PLAN §0.2): both read data-service (``/db/fo-iv/oi-tape/{symbol}``, ``/db/fo-iv/expiry-day/{symbol}``) through
the process-wide client and ONE stale-while-revalidate cache; no publisher is ever on the request path. A data-service that
does not serve the reads yet (404: the tape package not deployed) degrades the panel to ``ok: false`` with the reason, never
a 500. Stored 2-minute snapshots are DELAYED with their age, never LIVE (the L13 rule).

Honesty rules (PLAN §0): every derived number carries a badge — ``context`` for OI change, PCR, max pain, pin risk and the
straddle path; ``arithmetic`` for IV and the scorecard; no ``signal`` exists; no composite score; nothing here feeds the
Decision Desk, the S1 shadow, a directional alert or a ticket price; the sentences end "describes, does not predict".
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from cache import SWRCache, TTLCache, cache_headers
from errors import fail
from fastapi import APIRouter, Query, Response

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.http_client import UpstreamError, get_json  # noqa: E402

router = APIRouter()
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
_SYMBOL = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")
_DATE = r"^\d{4}-\d{2}-\d{2}$"

TAPE = SWRCache("expiry.tape", max_items=128, refresh_after=30.0, max_age=300.0)
DOWN_TTL_S = 20.0
_down = TTLCache("expiry.down", max_items=32, default_ttl=DOWN_TTL_S)

DESCRIBES = "describes, does not predict"
BADGES = {"tape": "context", "iv": "arithmetic", "oi": "context", "max_pain": "context", "pin_risk": "context", "straddle": "context",
          "scorecard": "arithmetic", "curve": "context"}
PRECEDENT_TAPE = "Bloomberg OMON intraday / Sensibull OI change / Quantsapp IV live"
PRECEDENT_XPRY = "Opstra / Sensibull expiry-day tools, ORATS implied-vs-realised"
COVERAGE = ("the tape snaps NIFTY, BANKNIFTY and FINNIFTY (near expiry every 2 minutes when the Breeze budget allows, the next "
            "expiry when liquid) and the watch list's F&O names (near expiry, every 15 minutes), 09:15–15:30 IST")


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
            raise _Unavailable("data-service does not serve the tape reads yet (404): the W2-TAPE routes are not deployed") from exc
        raise _Unavailable(f"data-service {exc.status_code}: {str(exc.detail)[:160]}") from exc


async def _read(kind: str, path: str, response: Response | None, **params: Any) -> tuple[dict[str, Any] | None, str | None]:
    """One cached data-service read; ``kind`` keys the short "store down" memory (a 404 route is not re-asked for 20 s)."""
    clean = {k: v for k, v in params.items() if v is not None}
    key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
    down = _down.get(f"down:{kind}")
    if down is not None:
        return None, str(down)
    try:
        served = await TAPE.get(key, lambda: _fetch(path, clean))
    except _Unavailable as exc:
        _down.set(f"down:{kind}", str(exc), ttl=DOWN_TTL_S)
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — a bad body is a store problem, not a page problem
        return None, type(exc).__name__
    cache_headers(response, served)
    value = served.value
    return (value if isinstance(value, dict) else None), (None if isinstance(value, dict) else "unexpected body")


def age_s(last_ts: str | None, now: datetime | None = None) -> float | None:
    """Seconds since the last stored snapshot (ISO with offset), for the DELAYED chip."""
    if not last_ts:
        return None
    try:
        t = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return max(0.0, ((now or datetime.now(timezone.utc)) - t).total_seconds())


def chip(body: dict[str, Any] | None, last_ts: str | None, snapshots: int, now: datetime | None = None) -> dict[str, Any]:
    """The SourceChip the panel shows: stored snapshots are DELAYED with their age (never LIVE); none → OFFLINE."""
    src = str((body or {}).get("source") or "OFFLINE").upper()
    if not snapshots or src == "OFFLINE":
        return {"state": "offline", "source": "Breeze chain tape", "as_of": (body or {}).get("date"), "age_s": None,
                "hint": "no snapshot stored for this session"}
    label = "BREEZE" if src == "BREEZE" else ("NSE v3 (fallback)" if src == "NSE" else src)
    return {"state": "delayed", "source": label, "as_of": last_ts, "age_s": age_s(last_ts, now),
            "hint": "stored chain snapshots (2-minute tape through the Breeze budget ledger)"}


def shape_tape(body: dict[str, Any] | None, symbol: str, err: str | None, now: datetime | None = None) -> dict[str, Any]:
    """The tape payload with its chip, badges and coverage line; an unavailable store keeps the shape with ``ok: false``."""
    b = body or {}
    snaps = int(b.get("snapshots") or 0)
    out = {"symbol": symbol, "date": b.get("date"), "expiry": b.get("expiry"), "expiries": b.get("expiries") or [], "lot": b.get("lot"),
           "dte_calendar": b.get("dte_calendar"), "path": b.get("path") or [], "strikes": b.get("strikes") or [], "frames": b.get("frames") or [],
           "snapshots": snaps, "first": b.get("first"), "last": b.get("last"), "last_ts": b.get("last_ts"), "median_gap_min": b.get("median_gap_min"),
           "source": b.get("source") or "OFFLINE", "units": b.get("units") or {}, "model_version": b.get("model_version"),
           "chip": chip(b, b.get("last_ts"), snaps, now), "badges": BADGES, "coverage": COVERAGE, "precedent": PRECEDENT_TAPE,
           "note": f"OI change since the first snapshot of the day, the straddle at the opening ATM strike and at the moving ATM; {DESCRIBES}",
           "ok": err is None, "store_errors": {"oi-tape": err} if err else {}}
    return out


def curve_honesty(curve: dict[str, Any], last_expiry: Any) -> dict[str, Any]:
    """The replay curve with an honest as-of (FINAL ROUND B-XPRY): ``as_of`` = the latest REPLAYED expiry, and
    ``replay_pending`` naming the lag when ``iv_expiry_daily`` holds newer expiries than ``iv_expiry_replay`` does
    (the store, not this read, is behind: the after-close replay job, O-T16 — the PM runs it, never this service)."""
    exps = curve.get("expiries") or []
    as_of = str(exps[-1]) if exps else None
    curve["as_of"] = as_of
    last = str(last_expiry) if last_expiry else None
    if as_of and last and last > as_of:
        curve["replay_pending"] = (f"latest replayed expiry {as_of}; expiries stored up to {last} are not replayed yet "
                                   "(the after-close replay job, O-T16)")
    return curve


# F1-TRADER (13 Nov 2026), R3-NITS: the store pairs each expiry with the LAST session stored BEFORE it
# (``MAX(date) < expiry``), so a hole in ``iv_expiry_daily`` around an expiry produces a row priced months out —
# the live find was 2026-06-25 "priced 2025-07-31 (329d)", realised −8.10 %: a data gap, not an implied-vs-realised
# observation. A healthy pairing prices 1–4 calendar days before expiry (a long weekend at most), so anything whose
# pricing gap exceeds this bound is dropped here, counted and named in ``excluded_note`` — never silently.
SCORECARD_MAX_PRICING_GAP_DAYS = 7


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _rescore(rows: list[dict[str, Any]], fair: Any) -> dict[str, Any]:
    """The scorecard stats over the kept rows (the store's own formulae, intraday.scorecard): needed only when a
    DROPPED bogus row had been scored, so the served stats never count a row the table no longer shows."""
    scored = [r for r in rows if r.get("implied_move_pct") is not None]
    stats: dict[str, Any] = {"n": len(scored)}
    if not scored:
        return stats
    err_i = [abs(abs(r["realised_move_pct"]) - r["implied_move_pct"]) for r in scored]
    stats.update({"exceeded_pct": round(100 * sum(bool(r.get("exceeded")) for r in scored) / len(scored), 1),
                  "median_ratio": round(_median([r["ratio"] for r in scored]), 3),
                  "mean_ratio": round(_mean([r["ratio"] for r in scored]), 3),
                  "mean_abs_miss_pct": round(_mean(err_i), 3)})
    if fair is not None:
        stats["fair_exceeded_pct"] = fair
    both = [r for r in scored if r.get("naive_move_pct") is not None]
    if both:
        err_n = [abs(abs(r["realised_move_pct"]) - r["naive_move_pct"]) for r in both]
        err_ib = [abs(abs(r["realised_move_pct"]) - r["implied_move_pct"]) for r in both]
        stats.update({"naive_mean_abs_miss_pct": round(_mean(err_n), 3),
                      "implied_closer": int(sum(a < b for a, b in zip(err_ib, err_n, strict=True))), "compared": len(both)})
    return stats


def filter_scorecard(sc: dict[str, Any]) -> dict[str, Any]:
    """Drop stale-pairing rows (pricing gap > SCORECARD_MAX_PRICING_GAP_DAYS calendar days) from the served
    scorecard. The row count and the reason are stated; stats are re-derived only when a dropped row was scored
    (the live bogus row is unscored — ``implied_move_pct`` null — so the store's stats normally pass through)."""
    rows = [r for r in (sc.get("rows") or []) if isinstance(r, dict)]
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for r in rows:
        (dropped if isinstance(r.get("dte"), (int, float)) and r["dte"] > SCORECARD_MAX_PRICING_GAP_DAYS else kept).append(r)
    if not dropped:
        return sc
    out = dict(sc)
    out["rows"] = kept
    out["excluded"] = len(dropped)
    out["excluded_note"] = ("excluded " + ", ".join(f"{r.get('expiry')} (priced {r.get('priced_on')}, {r.get('dte')}d before)" for r in dropped)
                            + f": a pricing gap over {SCORECARD_MAX_PRICING_GAP_DAYS} calendar days is a store hole, not an observation")
    if any(r.get("implied_move_pct") is not None for r in dropped):
        out["stats"] = _rescore(kept, (sc.get("stats") or {}).get("fair_exceeded_pct"))
    return out


def shape_expiry(body: dict[str, Any] | None, symbol: str, err: str | None, now: datetime | None = None) -> dict[str, Any]:
    b = body or {}
    live = b.get("live") or {"snapshots": 0}
    sc = filter_scorecard(b.get("scorecard") or {"rows": [], "stats": {"n": 0}})
    curve = curve_honesty(dict(b.get("curve") or {"n": 0, "points": []}), b.get("last_expiry"))
    out = {"symbol": symbol, "date": b.get("date"), "is_expiry_day": bool(b.get("is_expiry_day")), "next_expiry": b.get("next_expiry"),
           "last_expiry": b.get("last_expiry"), "live": live, "curve": curve, "scorecard": sc,
           "chip": chip({"source": live.get("source"), "date": b.get("date")}, live.get("last_ts"), int(live.get("snapshots") or 0), now),
           "badges": BADGES, "precedent": PRECEDENT_XPRY,
           "verdict": f"Expiry-day view: OI unwind, max-pain drift, straddle decay, pin risk and the implied-vs-realised record; {DESCRIBES}",
           "ok": err is None, "store_errors": {"expiry-day": err} if err else {}}
    return out


# ── E-REPLAY (FINAL ROUND wave E, F-17): the expiry replay simulator's read — stored rows only ───────────────────────
# The simulator practises on recorded expiry-day tapes (``iv_expiry_replay``; the PM's after-close job O-T16 fills it,
# never this service). Practice entries never exist server-side: the browser keeps them, the paper F&O book's store is
# never written, no alert and no ticket is touched. Scoring is client arithmetic over these stored rows. No direction
# words; the copy is "your mark vs the actual print", never a side having been the better one.

REPLAY_BADGES = {"tape": "context", "scoring": "arithmetic"}
REPLAY_NOTE = f"a rehearsal on recorded data — {DESCRIBES}"
REPLAY_PRACTICE = ("practice entries stay in this browser (localStorage) — never the paper F&O book, never an order; "
                   "PAPER ONLY stands")
# the per-row keys served to the client: clock times only (no per-row date), so date-hidden mode leaks nothing per print
_REPLAY_ROW_KEYS = ("minute", "ist", "straddle", "ce_close", "pe_close", "ce_oi", "pe_oi", "ce_volume", "pe_volume")


def replay_chip(as_of: str | None, stored: bool, hint: str) -> dict[str, Any]:
    """Recorded history is REFERENCE (never LIVE, never DELAYED: there is no feed to be behind); none stored → OFFLINE."""
    if not stored:
        return {"state": "offline", "source": "Breeze 1-minute replay", "as_of": None, "age_s": None, "hint": hint}
    return {"state": "reference", "source": "Breeze 1-minute replay", "as_of": as_of, "age_s": None, "hint": hint}


def shape_replay(body: dict[str, Any] | None, symbol: str, expiry: str | None, err: str | None) -> dict[str, Any]:
    """The replay payload: the list of replayed expiries (no ``expiry``) or one expiry's tape. Rows pass through
    point-in-time (a null stays a gap) but are re-keyed to ``_REPLAY_ROW_KEYS`` so no per-row timestamp carries a date."""
    b = body or {}
    base: dict[str, Any] = {"symbol": symbol, "badges": REPLAY_BADGES, "note": REPLAY_NOTE, "practice": REPLAY_PRACTICE,
                            "ok": err is None, "store_errors": {"replay": err} if err else {}}
    if expiry is None:
        exps = [e for e in (b.get("expiries") or []) if isinstance(e, dict)]
        last = str(exps[-1].get("expiry")) if exps else None
        return {**base, "mode": "list", "expiries": exps, "n": len(exps),
                "chip": replay_chip(last, bool(exps),
                                    "replayed expiry days stored by the after-close job (O-T16); recorded history, not a feed"),
                "empty_note": None if exps else str(b.get("note") or "no expiry day replayed yet (the PM's after-close job, O-T16)")}
    rows = [{k: r.get(k) for k in _REPLAY_ROW_KEYS} for r in (b.get("rows") or []) if isinstance(r, dict)]
    return {**base, "mode": "tape", "expiry": str(b.get("expiry") or expiry), "strike": b.get("strike"),
            "spot_open": b.get("spot_open"), "source": b.get("source"), "rows": rows, "n": len(rows),
            "chip": replay_chip(str(b.get("expiry") or expiry), bool(rows),
                                "one recorded expiry day (Breeze 1-minute bars, backfilled); every print is historical")}


@router.get("/iv/{symbol}/oi-tape")
async def oi_tape(symbol: str, response: Response, date_: str | None = Query(None, alias="date", pattern=_DATE),
                  expiry: str | None = Query(None, pattern=_DATE)) -> dict:
    """The intraday OI / IV tape for one underlying (default: today's or the latest stored session, nearest expiry)."""
    sym = _check_symbol(symbol)
    body, err = await _read("oi-tape", f"/db/fo-iv/oi-tape/{sym}", response, date=date_, expiry=expiry)
    return shape_tape(body, sym, err)


@router.get("/expiry-day")
async def expiry_day(response: Response, symbol: str = Query("NIFTY"), date_: str | None = Query(None, alias="date", pattern=_DATE),
                     n: int = Query(26, ge=1, le=260)) -> dict:
    """XPRY for one underlying: the expiry-day panels when ``date`` (default today, IST) is an expiry, the scorecard always."""
    sym = _check_symbol(symbol)
    if date_:
        try:
            date.fromisoformat(date_)
        except ValueError:
            fail(422, "invalid", f"bad date {date_!r}", "YYYY-MM-DD")
    body, err = await _read("expiry-day", f"/db/fo-iv/expiry-day/{sym}", response, date=date_, n=n)
    return shape_expiry(body, sym, err)


@router.get("/replay")
async def expiry_replay(response: Response, symbol: str = Query("NIFTY"),
                        expiry: str | None = Query(None, pattern=_DATE)) -> dict:
    """E-REPLAY (F-17): the stored expiry-day replay tapes for the practice simulator — the list of replayed expiries
    (no ``expiry``), or one expiry's 1-minute rows. Read-only over ``iv_expiry_replay``; the backfill is the PM's
    after-close job (O-T16), never run from here. A data-service without the replay read (404) degrades to
    ``ok: false`` with the reason, never a 500."""
    sym = _check_symbol(symbol)
    if expiry:
        try:
            date.fromisoformat(expiry)
        except ValueError:
            fail(422, "invalid", f"bad expiry {expiry!r}", "YYYY-MM-DD")
    body, err = await _read("replay", f"/db/fo-iv/replay/{sym}", response, expiry=expiry)
    return shape_replay(body, sym, expiry, err)
