"""GPLN — Morning Game Plan (terminal_final PLAN W7 / F-11, wave E).

One GET assembles the trader's morning context from EXISTING stores and routes — nothing new is fetched from a
publisher, nothing is forecast, nothing is scored. Facts assembled, the trader decides.

Tiles (each badged, each dated, each degrades alone — a dead read never kills the page):
  overnight   GIFT NIFTY (data-service /db/gift-nifty, NSE copy) + COMEX gold's stored daily bars   `context`
  levels      the prior session's high / low / close from index_ohlc_daily                          `arithmetic`
  oi          max pain, PCR, the largest call / put OI strikes from the stored EOD chain            `context`
  iv          IV30 + percentile + rank + IV−RV (close-to-close) today vs the prior session          `context`
  events      ECO calendar rows for today / tomorrow + today's NSE corporate calendar               `context`
  focus       the owner's watchlist (prefs) + alert fires since the prior session's close           `context`

Honesty rules (PLAN §1, binding): every tile carries a badge and its own as-of; no direction words anywhere; no
composite score; the payload states "assembled from stored/live reads — describes, does not predict". Nothing here
feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price. The 08:50 Telegram digest
(scripts/morning_gameplan.py) renders THIS payload as text lines — one assembly, two faces.

Upstream policy: data-service only, through the process-wide client (shared.http_client.get_json); the eco / corporate
calendars reuse routers.markets' own composition; watchlist and alert fires are local SQLite reads run off the event
loop (asyncio.to_thread). Errors are normalized — no raw transport text ever reaches a panel (O-F5a).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any

from cache import TTLCache
from fastapi import APIRouter, Query

for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.http_client import UpstreamError, get_json  # noqa: E402

router = APIRouter()
DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")

IST = timezone(timedelta(hours=5, minutes=30))
SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
GOLD_SYMBOL = "GC=F"
WATCHLIST_PREF_KEY = "suryadhana.watchlist"

DESCRIBES = "describes, does not predict"
NOTE = f"assembled from stored/live reads — {DESCRIBES}"
FEEDS_NOTHING = ("nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price; "
                 "orders are manual at ICICI")

CACHE_TTL_S = 60.0
_cache = TTLCache("gameplan", max_items=8, default_ttl=CACHE_TTL_S)

BADGE = {"overnight": "context", "levels": "arithmetic", "oi": "context", "iv": "context",
         "events": "context", "focus": "context"}


# ── pure helpers (unit-tested) ────────────────────────────────────────────────────────────────────────────


def overnight_window_start(now_ist: datetime) -> datetime:
    """The prior NSE session's 15:30 IST — the 'overnight' window for alert fires. Weekend-safe: Monday (and the
    weekend itself) look back to Friday 15:30. Holidays are not consulted: a holiday morning simply shows a longer
    window, honestly stamped (`since`)."""
    day = now_ist.date()
    # before today's 15:30 the prior close is the previous weekday's; after it, today's own
    if now_ist.time() < dtime(15, 30):
        day = day - timedelta(days=1)
    while day.weekday() >= 5:  # Sat/Sun → Friday
        day = day - timedelta(days=1)
    return datetime(day.year, day.month, day.day, 15, 30, tzinfo=IST)


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN → None


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Rows from data-service's reply shapes ({rows: […]}, a bare list)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    return []


def pct_change(last: float | None, prev: float | None) -> float | None:
    """(last / prev − 1) × 100 — an identity, badge `arithmetic`."""
    if last is None or prev is None or prev == 0:
        return None
    return round((last / prev - 1.0) * 100.0, 2)


def _err(exc: Exception) -> str:
    """A small, calm error line — never raw transport text (O-F5a / error contract)."""
    if isinstance(exc, UpstreamError):
        return "the data service did not answer" if exc.status_code == 503 else f"data-service {exc.status_code}"
    return type(exc).__name__


def _tile(key: str, **data: Any) -> dict[str, Any]:
    return {"ok": True, "badge": BADGE[key], **data}


def _dead(key: str, exc: Exception, source: str) -> dict[str, Any]:
    return {"ok": False, "badge": BADGE[key], "source": source, "as_of": None, "error": _err(exc)}


# ── collectors (each guarded; data-service through the shared client only) ───────────────────────────────


async def _overnight() -> dict[str, Any]:
    src = "NSE (GIFT copy) + stored COMEX daily bars"
    gift: dict[str, Any] | None = None
    gold: dict[str, Any] | None = None
    gift_error: str | None = None
    gold_error: str | None = None
    try:
        g = await get_json(f"{DATA_SVC}/db/gift-nifty", route="live", stale_for=120)
        if isinstance(g, dict):
            gift = {k: g.get(k) for k in ("last", "implied_gap_pct", "prev_close", "time", "as_of", "stale") if k in g}
    except Exception as exc:  # noqa: BLE001 — a tile degrades, never the page
        gift_error = _err(exc)
    try:
        frm = (datetime.now(IST).date() - timedelta(days=12)).isoformat()
        b = await get_json(f"{DATA_SVC}/db/gold/bars", route="read",
                           params={"symbol": GOLD_SYMBOL, "interval": "1d", "from": frm})
        bars = _rows(b)
        if len(bars) >= 2:
            last, prev = bars[-1], bars[-2]
            gold = {"symbol": GOLD_SYMBOL, "last": _f(last.get("close")), "last_date": str(last.get("trade_date") or "")[:10],
                    "prev_close": _f(prev.get("close")), "prev_date": str(prev.get("trade_date") or "")[:10],
                    "change_pct": pct_change(_f(last.get("close")), _f(prev.get("close"))),
                    "partial": bool(last.get("partial"))}
    except Exception as exc:  # noqa: BLE001
        gold_error = _err(exc)
    if gift is None and gold is None:
        return {"ok": False, "badge": BADGE["overnight"], "source": src, "as_of": None,
                "error": gift_error or gold_error or "no overnight reads answered"}
    as_of = (gift or {}).get("as_of") or (gift or {}).get("time") or (gold or {}).get("last_date")
    return _tile("overnight", source=src, as_of=as_of, gift=gift, gold=gold,
                 **({"gift_error": gift_error} if gift_error else {}), **({"gold_error": gold_error} if gold_error else {}))


#: the index-close store keys indices by their NSE names, not the F&O underlying codes (F-TRADER's one dead tile)
_INDEX_NAME = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FINANCIAL SERVICES"}


async def _levels(symbol: str) -> dict[str, Any]:
    src = "index_ohlc_daily (NSE index close file)"
    try:
        body = await get_json(f"{DATA_SVC}/db/index-ohlc/{_INDEX_NAME.get(symbol, symbol)}", route="read", params={"days": 6})
    except Exception as exc:  # noqa: BLE001
        return _dead("levels", exc, src)
    rows = _rows(body)
    if not rows:
        return {"ok": False, "badge": BADGE["levels"], "source": src, "as_of": None, "error": "no stored sessions"}
    last = rows[-1]
    prev_close = _f(rows[-2].get("close")) if len(rows) >= 2 else None
    day = str(last.get("date") or "")[:10]
    return _tile("levels", source=src, as_of=day, session=day,
                 high=_f(last.get("high")), low=_f(last.get("low")), close=_f(last.get("close")),
                 change_pct=pct_change(_f(last.get("close")), prev_close),
                 note="the prior stored session's range — a record, not a level to trade")


_OI_KEYS = ("date", "expiry", "days_to_expiry", "spot", "future", "atm", "atm_iv", "expected_move_pct",
            "pcr_oi", "max_pain", "lot")


async def _oi(symbol: str) -> dict[str, Any]:
    src = "stored EOD option chain (NSE F&O bhavcopy)"
    try:
        body = await get_json(f"{DATA_SVC}/db/option-chain/{symbol}", route="read", timeout=45.0)
    except Exception as exc:  # noqa: BLE001
        return _dead("oi", exc, src)
    if not isinstance(body, dict) or not body.get("found", True):
        return {"ok": False, "badge": BADGE["oi"], "source": src, "as_of": None, "error": "no stored chain"}
    out = {k: body.get(k) for k in _OI_KEYS}
    # NSE convention renamed to the OI fact it is: the strikes holding the largest call / put OI (no direction words)
    return _tile("oi", source=src, as_of=body.get("date"),
                 call_walls=body.get("resistance") or [], put_walls=body.get("support") or [],
                 walls_note="the 3 strikes holding the largest call / put OI in the stored chain", **out)


_IV_KEYS = ("iv30_cm", "iv_pctile_252", "iv_rank_252", "iv_minus_rv20", "expected_move_1d_pct")


async def _iv(symbol: str) -> dict[str, Any]:
    src = "iv_summary_daily (stored IV store)"
    try:
        body = await get_json(f"{DATA_SVC}/db/iv/summary", route="read", params={"symbol": symbol, "days": 10})
    except Exception as exc:  # noqa: BLE001
        return _dead("iv", exc, src)
    rows = _rows(body)
    if not rows:
        return {"ok": False, "badge": BADGE["iv"], "source": src, "as_of": None,
                "error": "no stored IV rows (iv_eod has not run for this symbol)"}
    def pick(r: dict[str, Any]) -> dict[str, Any]:
        return {"date": str(r.get("date") or "")[:10], **{k: _f(r.get(k)) for k in _IV_KEYS}}
    today, yday = pick(rows[-1]), (pick(rows[-2]) if len(rows) >= 2 else None)
    delta = None
    if yday is not None:
        delta = {k: (round(today[k] - yday[k], 2) if today.get(k) is not None and yday.get(k) is not None else None)
                 for k in ("iv30_cm", "iv_pctile_252", "iv_rank_252", "iv_minus_rv20")}
    return _tile("iv", source=src, as_of=today["date"], today=today, prior=yday, change=delta,
                 spread_estimator="IV − RV20 is close-to-close",
                 definitions={"iv_pctile_252": "share of the past 252 sessions whose IV30 was below today's",
                              "iv_rank_252": "where today's IV30 sits between its 252-session min (0) and max (100)"})


async def _events() -> dict[str, Any]:
    src = "ECO calendar + NSE corporate calendar"
    today = datetime.now(IST).date()
    tomorrow = today + timedelta(days=1)
    eco_rows: list[dict[str, Any]] = []
    corp: dict[str, Any] | None = None
    eco_error: str | None = None
    corp_error: str | None = None
    try:
        from routers import markets  # late import: heavy module, already loaded in the app
        eco = await markets.eco_calendar(back=0, ahead=4)
        eco_rows = [{"date": e.get("date"), "kind": e.get("kind"), "what": e.get("what") or e.get("label"),
                     "time": e.get("time")}
                    for e in (eco.get("events") or [])
                    if isinstance(e, dict) and str(e.get("date") or "") in (today.isoformat(), tomorrow.isoformat())]
    except Exception as exc:  # noqa: BLE001
        eco_error = _err(exc)
    try:
        from routers import markets
        ev = await markets.market_events(start=today.isoformat(), end=tomorrow.isoformat(), limit=400, fields=None)
        rows = [r for r in (ev.get("rows") or []) if isinstance(r, dict)]
        corp = {"count": len(rows), "date": today.isoformat(),
                "rows": [{"symbol": r.get("symbol"), "date": r.get("event_date") or r.get("date"),
                          "kind": r.get("kind"), "label": r.get("purpose") or r.get("kind")} for r in rows[:12]]}
    except Exception as exc:  # noqa: BLE001
        corp_error = _err(exc)
    if eco_error and corp_error:
        return {"ok": False, "badge": BADGE["events"], "source": src, "as_of": None, "error": eco_error}
    return _tile("events", source=src, as_of=today.isoformat(), eco=eco_rows, corporate=corp,
                 **({"eco_error": eco_error} if eco_error else {}), **({"corporate_error": corp_error} if corp_error else {}))


def _read_watchlist() -> list[str]:
    """The owner's watchlist from the prefs store (SQLite; called via to_thread)."""
    from routers.prefs import get_store
    rec = get_store().all().get(WATCHLIST_PREF_KEY)
    if not rec or rec.get("value") in (None, ""):
        return []
    try:
        val = json.loads(rec["value"])
    except (TypeError, ValueError):
        return []
    return [str(s) for s in val if isinstance(s, str)][:40] if isinstance(val, list) else []


def _read_fires(since: datetime) -> list[dict[str, Any]]:
    """Alert fires since `since` from the alerts SQLite (called via to_thread)."""
    from routers import alerts as alerts_router
    body = alerts_router.list_fires(symbol=None, limit=100, origin="all")
    out: list[dict[str, Any]] = []
    for f in body.get("fires") or []:
        at = str(f.get("at") or f.get("fired_at") or "")
        try:
            t = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= since:
            out.append({"symbol": f.get("symbol"), "series": f.get("series"), "at": at,
                        "text": f.get("text") or f.get("label")})
    return out


async def _focus() -> dict[str, Any]:
    src = "your watchlist (prefs) + alert fires (alerts store)"
    now = datetime.now(IST)
    since = overnight_window_start(now)
    watchlist: list[str] = []
    fires: list[dict[str, Any]] = []
    wl_error: str | None = None
    fires_error: str | None = None
    try:
        watchlist = await asyncio.to_thread(_read_watchlist)
    except Exception as exc:  # noqa: BLE001
        wl_error = _err(exc)
    try:
        fires = await asyncio.to_thread(_read_fires, since)
    except Exception as exc:  # noqa: BLE001
        fires_error = _err(exc)
    if wl_error and fires_error:
        return {"ok": False, "badge": BADGE["focus"], "source": src, "as_of": None, "error": wl_error}
    return _tile("focus", source=src, as_of=now.isoformat(timespec="seconds"),
                 watchlist=watchlist, fires={"since": since.isoformat(timespec="seconds"), "count": len(fires),
                                             "rows": fires[:10]},
                 note="names you chose to watch and levels you set yourself — a reading list, not a ranking",
                 **({"watchlist_error": wl_error} if wl_error else {}), **({"fires_error": fires_error} if fires_error else {}))


# ── assembly + route ──────────────────────────────────────────────────────────────────────────────────────


async def build_gameplan(symbol: str) -> dict[str, Any]:
    now = datetime.now(IST)
    overnight, levels, oi, iv, events, focus = await asyncio.gather(
        _overnight(), _levels(symbol), _oi(symbol), _iv(symbol), _events(), _focus())
    return {
        "symbol": symbol, "date": now.date().isoformat(), "as_of": now.isoformat(timespec="seconds"),
        "symbols": list(SYMBOLS),
        "tiles": {"overnight": overnight, "levels": levels, "oi": oi, "iv": iv, "events": events, "focus": focus},
        "badges": dict(BADGE),
        "note": NOTE, "feeds": FEEDS_NOTHING,
    }


@router.get("")
@router.get("/")
async def gameplan(symbol: str = Query("NIFTY", pattern="^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY)$")) -> dict[str, Any]:
    """The Morning Game Plan payload (GPLN page + the 08:50 Telegram digest). 60 s TTL per symbol — the page polls
    and the digest script share one assembly."""
    key = f"gameplan:{symbol}"
    hit = _cache.get(key)
    if hit is not None:
        return hit
    payload = await build_gameplan(symbol)
    _cache.set(key, payload)
    return payload
