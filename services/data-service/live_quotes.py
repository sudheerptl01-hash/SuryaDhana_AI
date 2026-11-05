"""
/live/quotes and /live/status — one quote per NSE symbol from the best live source, labelled honestly (live-NSE program,
LV-DATA, 5 Nov 2026; contract in reports/live_nse/).

Order of sources per symbol (the PM-fixed contract):
  1. the Breeze websocket tick (live_ticks.py) — `live` when it is ≤ 5 s old, and also while the socket is healthy (a tick
     on it in the last 10 s; NIFTY 50 is pinned and ticks at 10 Hz) and the symbol is subscribed and ticked within 120 s:
     Breeze pushes on every trade or quote change, so a quiet name's last tick IS the current price (L-CAPACITY: liquid
     NIFTY 50 names go 5.0 s median / 7.6 s worst between ticks, illiquid ones up to 78 s);
  2. the NSE website copies held by the fallback poller below (heatmap-symbols rows, allIndices, the NextApi equity
     quote) — `delayed` while ≤ 90 s old, `stale` beyond; their age comes from NSE's own stamps, corrected where
     L-CAPACITY measured the stamp lying (see _from_nse);
  3. the last EOD close (nse_bhavcopy; index_ohlc_daily / market_index_daily) — `closed` once the session is over and the
     close belongs to that session, `stale` during the session (or when the session's own close is not stored yet).
Never Yahoo: nothing in this module (or the poller) can reach a Yahoo host.

Request path (`LiveQuotes.quotes`): dict reads, the tick snapshot, and a cached DuckDB read for EOD rows — never an NSE
call, never a Breeze REST call (store, then show: Terminal v2 PLAN §0.2). Asking for a symbol ENSURES its websocket
subscription (live_ticks' union + TTL ledger). The pinned set (NIFTY 50 / NIFTY BANK / INDIA VIX, the NIFTY 50 and NIFTY
BANK members, the watchlist; the holdings are pinned by live_ticks itself) is served to live_ticks while the market is open.

NSE fallback poller: one daemon thread (`live-quotes-nse`), demand-driven (symbols asked for in the last 2 min that no
fresh tick covers), only 09:00–15:40 IST on trading days, through the shared cookie-primed NseLive client (its cache and
its 403/429 600 s breaker are shared with every other NSE route). Cadences are L-CAPACITY's floors, never faster:
allIndices ≥ 15 s, each heatmap-symbols list ≥ 60 s (only the lists that cover a needed symbol, broad lists first), the
NextApi quote ≥ 120 s per symbol and ≥ 4 s apart overall, on demand for at most 20 recently asked names outside every
heatmap list; ≥ 1.2 s between any two network calls.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import live_ticks as lt_mod
from nse_live import equity_quote_path, heatmap_path, parse_all_indices_rows, parse_equity_quote, parse_heatmap_rows
from shared.logging import get_logger

logger = get_logger("live-quotes")

IST = ZoneInfo("Asia/Kolkata")


def _env_floor(name: str, default: float, floor: float) -> float:
    """Config override that can slow a cadence down but never push it below L-CAPACITY's floor."""
    try:
        return max(floor, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


MAX_REQUEST = 300                   # symbols per /live/quotes call (the contract)
FRESH_S = lt_mod.FRESH_S            # ≤ 5 s = live, always
QUIET_LIVE_S = 120.0                # healthy socket + subscribed: the last tick is the current price up to this age
DELAYED_MAX_S = 90.0                # NSE (or an older tick) ≤ 90 s = delayed; older = stale
DEMAND_TTL_S = 120.0                # the poller works for symbols asked within this window
FOCUS_TTL_S = 60.0                  # the per-symbol NextApi quote only for names asked within the last minute
EOD_TTL_S = 600.0                   # EOD rows re-read at most every 10 min (the 18:30 bhavcopy shows within 10 min)
EOD_MISS_TTL_S = 900.0
PIN_TTL_S = 60.0
MEMBERS_TTL_S = 1800.0
HOLIDAYS_TTL_S = 12 * 3600.0
POLL_EVERY_S = 2.0
PIN_CAP = 200                       # pins never take more than 2/3 of the 300-token cap
PINNED_INDICES = ("NIFTY 50", "NIFTY BANK", "INDIA VIX")
PIN_MEMBERS_OF = ("NIFTY 50", "NIFTY BANK")

ALLINDICES_TTL_S = _env_floor("LIVE_NSE_INDICES_TTL_S", 15.0, 15.0)
HEATMAP_TTL_S = _env_floor("LIVE_NSE_HEATMAP_TTL_S", 60.0, 60.0)
NEXTAPI_TTL_S = _env_floor("LIVE_NSE_QUOTE_TTL_S", 120.0, 60.0)
NEXTAPI_GAP_S = _env_floor("LIVE_NSE_QUOTE_GAP_S", 4.0, 4.0)
NSE_GAP_S = 1.2                     # between any two NSE network calls from this poller
NEXTAPI_MAX_SYMBOLS = 20
NEXTAPI_MIN_LAG_S = 50.0            # L-CAPACITY: NextApi values were 48.6-65.2 s behind Breeze while lastUpdateTime claimed 8-9 s
MINUTE_STAMP_SPAN_S = 59.0          # allIndices: a minute label; its values were 2-60 s old while the label read 1-2 min
LIST_RELEARN_S = 3600.0
SECTOR_INDEX_PATH = "heatmap-index?type=Sectoral%20Indices"

OPEN_HM, PREOPEN_HM, CLOSE_HM = (9, 15), (9, 0), (15, 30)
POLL_FROM_HM, POLL_TO_HM = (9, 0), (15, 40)
PIN_FROM_HM, PIN_TO_HM = (8, 55), (15, 45)

SOURCE_BREEZE, SOURCE_NSE, SOURCE_EOD = "breeze_ws", "nse_api", "eod"
LIVE, DELAYED, STALE, CLOSED, UNAVAILABLE = "live", "delayed", "stale", "closed", "unavailable"


# ── the market clock ──────────────────────────────────────────────────────────────────────────────────────────────────

def is_trading_day(d: date, holidays: set[str]) -> bool:
    return d.weekday() < 5 and d.isoformat() not in holidays


def previous_trading_day(d: date, holidays: set[str]) -> date:
    x = d - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(x, holidays):
            return x
        x -= timedelta(days=1)
    return x


def market_state(now: datetime, holidays: set[str]) -> tuple[str, date]:
    """(open | pre-open | closed, session_date): the session in progress, or the last one that traded."""
    d, hm = now.date(), (now.hour, now.minute)
    if not is_trading_day(d, holidays) or hm < PREOPEN_HM:
        return "closed", (d if is_trading_day(d, holidays) and hm >= PREOPEN_HM else previous_trading_day(d, holidays))
    if hm < OPEN_HM:
        return "pre-open", d
    if hm < CLOSE_HM:
        return "open", d
    return "closed", d


def _in_window(now: datetime, holidays: set[str], start: tuple[int, int], end: tuple[int, int]) -> bool:
    return is_trading_day(now.date(), holidays) and start <= (now.hour, now.minute) <= end


def parse_trading_holidays(payload: Any) -> set[str]:
    """NSE holiday-master?type=trading → the CM (equity) holidays as ISO dates."""
    out: set[str] = set()
    rows = (payload.get("CM") or []) if isinstance(payload, dict) else []
    for h in rows:
        try:
            out.add(datetime.strptime(str(h.get("tradingDate")), "%d-%b-%Y").replace(tzinfo=IST).date().isoformat())
        except ValueError:
            continue
    return out


def _iso(epoch: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(epoch, IST).isoformat(timespec="seconds") if epoch else None


def _r(x: Optional[float], nd: int = 2) -> Optional[float]:
    return round(x, nd) if isinstance(x, (int, float)) else None


class LiveQuotes:
    """Composes /live/quotes and /live/status; owns the NSE fallback poller. One per data-service process."""

    def __init__(self, *, ticks_getter: Callable[[], Any], nse_getter: Callable[[], Any],
                 eod_fn: Callable[[list[str]], dict[str, dict]],
                 session_fn: Optional[Callable[[], bool]] = None,
                 holdings_fn: Optional[Callable[[], list[str]]] = None,
                 watchlist_fn: Optional[Callable[[], list[str]]] = None,
                 members_fn: Optional[Callable[[str], list[str]]] = None,
                 holidays_fn: Optional[Callable[[], set[str]]] = None,
                 clock: Callable[[], float] = time.time,
                 sleep_fn: Optional[Callable[[float], Any]] = None,
                 start_poller: bool = True) -> None:
        self._ticks_getter = ticks_getter
        self._nse_getter = nse_getter
        self._eod_fn = eod_fn
        self._session_fn = session_fn or (lambda: False)
        self._holdings_fn = holdings_fn
        self._watchlist_fn = watchlist_fn
        self._members_fn = members_fn
        self._holidays_fn = holidays_fn
        self._clock = clock
        self._stop = threading.Event()
        self._sleep = sleep_fn or self._stop.wait
        self._start_poller = start_poller

        self._lock = threading.RLock()
        self._demand: dict[str, float] = {}
        self._eod: dict[str, tuple[float, Optional[dict]]] = {}
        self._nse_idx: dict[str, dict] = {}
        self._nse_eq: dict[str, dict] = {}
        self._list_members: dict[str, set[str]] = {}
        self._list_seen: dict[str, float] = {}
        self._list_order: list[str] = []
        self._sym_list: dict[str, str] = {}
        self._quote_fetched: dict[str, float] = {}
        self._holidays: set[str] = set()
        self._holidays_at = -HOLIDAYS_TTL_S
        self._pins: tuple[float, list[str]] = (-PIN_TTL_S, [])
        self._members: dict[str, tuple[float, list[str]]] = {}
        self._last_net = -NSE_GAP_S
        self._last_nextapi = -NEXTAPI_GAP_S
        self._nse: dict[str, Any] = {"ok": None, "last_ok_at": None, "last_error": None, "last_error_at": None,
                                     "polls": 0, "network_calls": 0, "nextapi_calls": 0}
        self._thread: Optional[threading.Thread] = None

    # ── clock ─────────────────────────────────────────────────────────────────────────────────────────────────────────

    def _now_ist(self, now: Optional[float] = None) -> datetime:
        return datetime.fromtimestamp(self._clock() if now is None else now, IST)

    def market(self, now: Optional[float] = None) -> tuple[str, date]:
        return market_state(self._now_ist(now), self._holidays)

    # ── request path ──────────────────────────────────────────────────────────────────────────────────────────────────

    def quotes(self, symbols: list[str]) -> dict:
        now = self._clock()
        syms = lt_mod._normalize(list(symbols))[:MAX_REQUEST]
        state, session = self.market(now)
        with self._lock:
            for s in syms:
                self._demand[s] = now
            if len(self._demand) > 4 * MAX_REQUEST:
                self._demand = {s: t for s, t in self._demand.items() if now - t <= DEMAND_TTL_S}
        lt = self._ticks()
        snap: dict[str, dict] = {}
        healthy = False
        if lt is not None and syms:
            try:
                lt.ensure(syms)                                    # A1 union + TTL; a no-op while LIVE_TICKS is off
                snap = lt.snapshot(syms)
                healthy = bool(lt.feed_healthy())
            except Exception as exc:  # noqa: BLE001 — the tick engine failing must not blank the quotes
                logger.warning("live-quotes: tick snapshot failed", error=str(exc)[:160])
        eod = self._eod_rows(syms, now)
        out: dict[str, dict] = {}
        for s in syms:
            subscribed = bool(lt is not None and lt.is_subscribed(s))
            out[s] = self._compose(s, now, state, session, snap.get(s), self._nse_row(s), eod.get(s), healthy, subscribed)
        if syms:
            self._ensure_poller()
        return {"as_of": _iso(now), "market": {"state": state, "session_date": session.isoformat()}, "quotes": out,
                "feed": {"breeze": getattr(lt, "state", lt_mod.OFF) if lt is not None else lt_mod.OFF,
                         "heartbeat_age_s": lt.heartbeat_age() if lt is not None else None,
                         "healthy": healthy, "nse_ok": self._nse["ok"]}}

    def _ticks(self) -> Any:
        try:
            return self._ticks_getter()
        except Exception:  # noqa: BLE001
            return None

    def _nse_row(self, sym: str) -> Optional[dict]:
        return self._nse_idx.get(sym) if lt_mod.is_index(sym) else self._nse_eq.get(sym)

    def _eod_rows(self, syms: list[str], now: float) -> dict[str, dict]:
        with self._lock:
            missing = [s for s in syms if s not in self._eod
                       or now - self._eod[s][0] > (EOD_TTL_S if self._eod[s][1] is not None else EOD_MISS_TTL_S)]
        if missing:
            try:
                got = self._eod_fn(missing) or {}
            except Exception as exc:  # noqa: BLE001 — DuckDB busy / table missing: try again next call
                logger.warning("live-quotes: EOD read failed", error=str(exc)[:160])
                got = None
            if got is not None:
                with self._lock:
                    for s in missing:
                        self._eod[s] = (now, got.get(s))
        with self._lock:
            return {s: row for s in syms if s in self._eod and (row := self._eod[s][1]) is not None}

    # ── composition ───────────────────────────────────────────────────────────────────────────────────────────────────

    def _from_tick(self, sym: str, t: dict, now: float) -> dict:
        price, prev = t.get("price"), t.get("prev_close")
        chg_pct = t.get("chg_pct")
        clamped = bool(t.get("hint"))
        change = _r(price - prev) if price is not None and prev and not clamped else None
        ttq, avg = t.get("ttq"), t.get("avg_price")
        ts = t.get("ts") or now
        ltt = t.get("ltt_epoch")
        c = {"source": SOURCE_BREEZE, "price": price, "change": change, "change_pct": _r(chg_pct) if not clamped else None,
             "prev_close": prev, "open": t.get("open"), "day_high": t.get("high"), "day_low": t.get("low"),
             "volume": ttq, "value_cr": _r(ttq * avg / 1e7) if ttq and avg else None,
             "bid": t.get("bid"), "ask": t.get("ask"), "ltt": _iso(ltt), "age_s": round(max(0.0, now - ts), 1),
             "age_basis": "tick_received", "date": self._now_ist(ts).date().isoformat(), "_t": ts,
             "last_trade_age_s": t.get("last_trade_age_s")}
        if clamped:
            c["hint"] = t.get("hint")
        if ltt and self._now_ist(ltt).date() < self._now_ist(ts).date():
            c["note"] = "no trade yet this session: the price is the last trade"
        return c

    def _from_nse(self, n: dict, now: float) -> dict:
        """NSE's copy with an honest age: heatmap rows by their own stamp (L-CAPACITY matched it against Breeze volume);
        allIndices by the END of its minute label (the label runs 1-2 min behind its values); the NextApi quote floored
        at 50 s past our fetch (its stamp understates the age). Never younger than our own fetch."""
        fetched = n.get("fetched_at") or now
        stamp = n.get("stamp_epoch")
        kind = n.get("kind")
        fetch_age = now - fetched
        if kind == "all_indices":
            age = max(fetch_age, now - (stamp + MINUTE_STAMP_SPAN_S)) if stamp else fetch_age
            basis = "nse_minute_stamp" if stamp else "fetch"
        elif kind == "equity_quote":
            age = max(now - stamp if stamp else 0.0, fetch_age + NEXTAPI_MIN_LAG_S)
            basis = "nse_quote_floor"
        else:
            age = max(fetch_age, now - stamp) if stamp else fetch_age
            basis = "nse_row_time" if stamp else "fetch"
        data_t = stamp or fetched
        return {"source": SOURCE_NSE, "price": n.get("price"), "change": n.get("change"), "change_pct": n.get("change_pct"),
                "prev_close": n.get("prev_close"), "open": n.get("open"), "day_high": n.get("day_high"),
                "day_low": n.get("day_low"), "volume": n.get("volume"), "value_cr": _r(n.get("value_cr")),
                "bid": n.get("bid"), "ask": n.get("ask"), "ltt": _iso(stamp), "age_s": round(max(0.0, age), 1),
                "age_basis": basis, "date": self._now_ist(data_t).date().isoformat(), "_t": data_t,
                "nse_stamp": n.get("stamp"), "nse_feed": kind}

    def _from_eod(self, e: dict, now: float) -> dict:
        d = e.get("date")
        day = date.fromisoformat(str(d)[:10])
        close_at = datetime(day.year, day.month, day.day, CLOSE_HM[0], CLOSE_HM[1], tzinfo=IST).timestamp()
        close, prev = e.get("close"), e.get("prev_close")
        return {"source": SOURCE_EOD, "price": close, "change": _r(close - prev) if close is not None and prev else None,
                "change_pct": _r((close / prev - 1) * 100) if close is not None and prev else None, "prev_close": prev,
                "open": e.get("open"), "day_high": e.get("high"), "day_low": e.get("low"), "volume": e.get("volume"),
                "value_cr": _r(e.get("value_cr")), "bid": None, "ask": None, "ltt": None,
                "age_s": round(max(0.0, now - close_at), 1), "age_basis": "eod_close", "date": day.isoformat(),
                "_t": close_at, "eod_table": e.get("table")}

    def _compose(self, sym: str, now: float, state: str, session: date, tick: Optional[dict], nse: Optional[dict],
                 eod: Optional[dict], healthy: bool, subscribed: bool) -> dict:
        today = self._now_ist(now).date().isoformat()
        b = self._from_tick(sym, tick, now) if tick and tick.get("price") is not None else None
        n = self._from_nse(nse, now) if nse and nse.get("price") is not None else None
        e = self._from_eod(eod, now) if eod and eod.get("close") is not None else None
        base = {"kind": "index" if lt_mod.is_index(sym) else "equity", "subscribed": subscribed}
        if state in ("open", "pre-open"):
            intraday = [c for c in (b, n) if c is not None and c["date"] == today]
            pre = " (pre-open: prices before 09:15 may be the indicative auction price, not trades)" if state == "pre-open" else ""
            b_today = b is not None and any(c is b for c in intraday)
            if b is not None and b_today and (b["age_s"] <= FRESH_S or (healthy and subscribed and b["age_s"] <= QUIET_LIVE_S)):
                why = None if b["age_s"] <= FRESH_S else f"quiet: no new trade or quote for {b['age_s']:.0f} s on a healthy feed"
                return self._finish(b, LIVE, (why or "") + pre or None, base)
            if intraday:
                best = min(intraday, key=lambda c: c["age_s"])
                st = DELAYED if best["age_s"] <= DELAYED_MAX_S else STALE
                why = ("no live tick; " if b is None or b is not best else "the feed is not healthy; ") + \
                      f"{'NSE website copy' if best['source'] == SOURCE_NSE else 'last tick'} {best['age_s']:.0f} s old"
                return self._finish(best, st, why + pre, base)
            if e is not None:
                if state == "pre-open":
                    return self._finish(e, CLOSED, f"previous session close ({e['date']}); the session opens 09:15", base)
                return self._finish(e, STALE, f"no live source answered; last close {e['date']}", base)
            return self._unavailable(base, "no live source and no stored close")
        # closed
        if e is not None and e["date"] == session.isoformat():
            return self._finish(e, CLOSED, None, base)
        intraday = [c for c in (b, n) if c is not None and c["date"] == session.isoformat()]
        if intraday:
            best = max(intraday, key=lambda c: c["_t"])
            return self._finish(best, CLOSED, f"last price of the {session.isoformat()} session; NSE's official close "
                                              "(the last-30-minute VWAP for stocks) arrives with the EOD files", base)
        if e is not None:
            if e["date"] > session.isoformat():
                return self._finish(e, CLOSED, None, base)
            return self._finish(e, STALE, f"the {session.isoformat()} close is not stored yet; showing the {e['date']} close",
                                base)
        return self._unavailable(base, "no stored close")

    @staticmethod
    def _finish(c: dict, state: str, reason: Optional[str], base: dict) -> dict:
        q = {k: v for k, v in c.items() if not k.startswith("_")}
        q.update(base)
        q["state"] = state
        note = q.pop("note", None)
        reason = "; ".join(x for x in (reason, note) if x) or None
        if reason:
            q["reason"] = reason
        return q

    @staticmethod
    def _unavailable(base: dict, reason: str) -> dict:
        return {"price": None, "change": None, "change_pct": None, "prev_close": None, "open": None, "day_high": None,
                "day_low": None, "volume": None, "value_cr": None, "bid": None, "ask": None, "ltt": None, "source": None,
                "age_s": None, "age_basis": None, "date": None, **base, "state": UNAVAILABLE, "reason": reason}

    # ── pins (served to live_ticks while the market is open) ──────────────────────────────────────────────────────────

    def pinned_symbols(self) -> list[str]:
        now = self._clock()
        if not _in_window(self._now_ist(now), self._holidays, PIN_FROM_HM, PIN_TO_HM):
            return []
        at, cached = self._pins
        if now - at < PIN_TTL_S:
            return list(cached)
        out: list[str] = list(PINNED_INDICES)
        for ix in PIN_MEMBERS_OF:
            out += self._index_members(ix, now)
        for fn in (self._holdings_fn, self._watchlist_fn):
            if fn is None:
                continue
            try:
                out += list(fn() or [])
            except Exception as exc:  # noqa: BLE001
                logger.debug("live-quotes: pin source failed", error=str(exc)[:120])
        pins = lt_mod._normalize(out)[:PIN_CAP]
        self._pins = (now, pins)
        return list(pins)

    def _index_members(self, index: str, now: float) -> list[str]:
        at, cached = self._members.get(index, (-MEMBERS_TTL_S, []))
        if now - at < (MEMBERS_TTL_S if cached else 300.0):
            return cached
        got: list[str] = []
        if self._members_fn is not None:
            try:
                got = [str(s).upper() for s in (self._members_fn(index) or [])]
            except Exception as exc:  # noqa: BLE001
                logger.debug("live-quotes: members read failed", index=index, error=str(exc)[:120])
        if not got:                                       # the NSE list this poller already learned (no network here)
            kind = "Broad Market Indices" if index in ("NIFTY 50", "NIFTY NEXT 50", "NIFTY MIDCAP 50") else "Sectoral Indices"
            got = sorted(self._list_members.get(heatmap_path(kind, index), set()))
        self._members[index] = (now, got)
        return got

    # ── NSE fallback poller ───────────────────────────────────────────────────────────────────────────────────────────

    def _ensure_poller(self) -> None:
        if not self._start_poller:
            return
        t = self._thread
        if t is None or not t.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._poll_loop, name="live-quotes-nse", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5)
        self._thread = None

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_nse_once()
            except Exception as exc:  # noqa: BLE001 — the poller never dies on one bad cycle
                self._note_error(f"poll failed: {exc}")
            self._stop.wait(POLL_EVERY_S)

    def _note_error(self, msg: str) -> None:
        self._nse.update(ok=False, last_error=msg[:200], last_error_at=_iso(self._clock()))

    def _note_ok(self) -> None:
        self._nse.update(ok=True, last_ok_at=_iso(self._clock()))

    def _client(self) -> Any:
        try:
            return self._nse_getter()
        except Exception as exc:  # noqa: BLE001
            self._note_error(f"NSE client unavailable: {exc}")
            return None

    def _net_get(self, client: Any, path: str, ttl: float) -> Any:
        """client.get through the shared NseLive cache; a call that will reach the network waits until ≥ 1.2 s after
        this poller's previous network call."""
        at = client.cached_at(path)
        if at is None or self._clock() - at >= ttl:
            wait = NSE_GAP_S - (self._clock() - self._last_net)
            if wait > 0:
                self._sleep(wait)
            self._last_net = self._clock()
            self._nse["network_calls"] += 1
        return client.get(path, ttl_open=ttl, ttl_closed=ttl)

    def _refresh_holidays(self, client: Any, now: float) -> None:
        if now - self._holidays_at < HOLIDAYS_TTL_S or self._now_ist(now).weekday() >= 5:
            return
        try:
            if self._holidays_fn is not None:
                self._holidays = set(self._holidays_fn() or set())
            elif client is not None:
                self._holidays = parse_trading_holidays(self._net_get(client, "holiday-master?type=trading", 86_400.0))
            self._holidays_at = now
        except Exception as exc:  # noqa: BLE001 — weekday-only calendar meanwhile; retry in 30 min
            self._holidays_at = now - HOLIDAYS_TTL_S + 1800.0
            logger.debug("live-quotes: holiday list unavailable", error=str(exc)[:120])

    def _covered_by_ticks(self, demand: list[str]) -> set[str]:
        lt = self._ticks()
        if lt is None:
            return set()
        try:
            snap = lt.snapshot(demand)
            healthy = bool(lt.feed_healthy())
        except Exception:  # noqa: BLE001
            return set()
        out = set()
        for s, t in snap.items():
            age = t.get("ts_age_s")
            if age is not None and (age <= FRESH_S or (healthy and lt.is_subscribed(s) and age <= QUIET_LIVE_S)):
                out.add(s)
        return out

    def poll_nse_once(self) -> dict:
        """One poller cycle (the thread calls it every 2 s; tests call it directly). Returns what it did."""
        now = self._clock()
        with self._lock:
            demand = {s: t for s, t in self._demand.items() if now - t <= DEMAND_TTL_S}
        if not demand:
            return {"skipped": "no demand"}
        client = self._client()
        blocked = float(getattr(client, "blocked_until", 0.0) or 0.0) if client is not None else 0.0
        if blocked > time.time():                          # NSE refused us: not one call (not even the calendar) until it clears
            self._note_error(f"NSE breaker open until {time.strftime('%H:%M', time.localtime(blocked))}")
            return {"skipped": "NSE breaker open"}
        self._refresh_holidays(client, now)
        if not _in_window(self._now_ist(now), self._holidays, POLL_FROM_HM, POLL_TO_HM):
            return {"skipped": "outside the session"}
        if client is None:
            return {"skipped": "no NSE client"}
        self._nse["polls"] += 1
        covered = self._covered_by_ticks(list(demand))
        need = [s for s in demand if s not in covered]
        need_idx = [s for s in need if lt_mod.is_index(s)]
        need_eq = [s for s in need if not lt_mod.is_index(s)]
        did: dict[str, Any] = {"need_indices": len(need_idx), "need_stocks": len(need_eq)}
        try:
            if need_idx:
                self._poll_indices(client)
            if need_eq:
                did["lists"] = self._poll_heatmaps(client, need_eq, now)
                did["quote"] = self._poll_quote(client, need_eq, demand, now)
            self._note_ok()
        except Exception as exc:  # noqa: BLE001 — one failure ends the cycle: never hammer NSE after an error
            self._note_error(str(exc))
            did["error"] = str(exc)[:160]
        return did

    def _poll_indices(self, client: Any) -> None:
        payload = self._net_get(client, "allIndices", ALLINDICES_TTL_S)
        rows = parse_all_indices_rows(payload if isinstance(payload, dict) else {})
        fetched = client.cached_at("allIndices") or self._clock()
        with self._lock:
            for name, r in rows.items():
                r["fetched_at"] = fetched
                self._nse_idx[name] = r

    def _store_eq(self, rows: dict[str, dict], fetched: float) -> None:
        with self._lock:
            for sym, r in rows.items():
                r["fetched_at"] = fetched
                old = self._nse_eq.get(sym)
                if old is None or (r.get("stamp_epoch") or fetched) >= (old.get("stamp_epoch") or old.get("fetched_at") or 0):
                    self._nse_eq[sym] = r

    def _poll_heatmaps(self, client: Any, need_eq: list[str], now: float) -> list[str]:
        """Fetch only the heatmap lists that cover a needed symbol (each symbol assigned to the FIRST list holding it,
        broad lists first: NIFTY 50 covers 50 names in one GET) plus lists not learned in the last hour."""
        self._net_get(client, SECTOR_INDEX_PATH, 3600.0)          # paced here so heatmap_lists() is a cache hit
        paths = [heatmap_path(kind, ix) for kind, ix in client.heatmap_lists()]
        self._list_order = paths
        unknown = [p for p in paths if p not in self._list_members or now - self._list_seen.get(p, -LIST_RELEARN_S) >= LIST_RELEARN_S]
        wanted = list(dict.fromkeys(self._sym_list[s] for s in need_eq if s in self._sym_list))
        done: list[str] = []
        for p in list(dict.fromkeys(wanted + unknown)):
            if self._stop.is_set():
                break
            raw = self._net_get(client, p, HEATMAP_TTL_S)
            rows = parse_heatmap_rows(raw if isinstance(raw, list) else (raw or {}).get("data", []))
            self._store_eq(rows, client.cached_at(p) or self._clock())
            self._list_members[p] = set(rows)
            self._list_seen[p] = now
            done.append(p)
        with self._lock:
            sym_list: dict[str, str] = {}
            for p in paths:
                for s in self._list_members.get(p, ()):
                    sym_list.setdefault(s, p)
            self._sym_list = sym_list
        return done

    def _poll_quote(self, client: Any, need_eq: list[str], demand: dict[str, float], now: float) -> Optional[str]:
        """The NextApi quote for ONE recently asked name outside every heatmap list, once all lists are learned."""
        if not self._list_order or any(p not in self._list_members for p in self._list_order):
            return None
        uncovered = sorted((s for s in need_eq if s not in self._sym_list and now - demand.get(s, -1e9) <= FOCUS_TTL_S),
                           key=lambda s: demand[s], reverse=True)[:NEXTAPI_MAX_SYMBOLS]
        t = self._clock()                                  # after this cycle's paced list fetches, not the cycle start
        due = [s for s in uncovered if t - self._quote_fetched.get(s, -NEXTAPI_TTL_S) >= NEXTAPI_TTL_S]
        if not due or t - self._last_nextapi < NEXTAPI_GAP_S:
            return None
        sym = due[0]
        if len(self._quote_fetched) > 4 * NEXTAPI_MAX_SYMBOLS:
            self._quote_fetched = {s: ts for s, ts in self._quote_fetched.items() if now - ts < NEXTAPI_TTL_S}
        self._last_nextapi = self._quote_fetched[sym] = t           # a failed call counts too: no retry storm on errors
        self._nse["nextapi_calls"] += 1
        path = equity_quote_path(sym)
        raw = self._net_get(client, path, NEXTAPI_TTL_S)
        self._last_nextapi = self._quote_fetched[sym] = self._clock()    # the moment the call went out (after pacing)
        q = parse_equity_quote(raw)
        if q.get("price") is not None and q.get("symbol") in (None, sym):
            q.pop("symbol", None)
            q.pop("series", None)
            self._store_eq({sym: q}, client.cached_at(path) or self._clock())
        return sym

    # ── status ────────────────────────────────────────────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        now = self._clock()
        state, session = self.market(now)
        lt = self._ticks()
        st: dict[str, Any] = lt.status() if lt is not None else {}
        try:
            session_ok = bool(self._session_fn())
        except Exception:  # noqa: BLE001
            session_ok = False
        armed = lt_mod.enabled()
        return {"as_of": _iso(now), "state": st.get("state", lt_mod.OFF) if armed else lt_mod.OFF, "enabled": armed,
                "subscribed": st.get("subscribed", 0), "requested": st.get("requested", 0),
                "pinned": len(self._pins[1]), "ticks_per_min": st.get("ticks_per_min", 0),
                "last_tick_age_s": st.get("last_tick_age_s"), "cap": lt_mod.MAX_SYMBOLS, "breeze_session": session_ok,
                "error": st.get("error"), "unmapped_ticks": st.get("unmapped_ticks", 0),
                "no_first_tick": st.get("no_first_tick", {"count": 0, "symbols": []}),
                "unresolved": st.get("unresolved", []), "sub_errors": st.get("sub_errors", {}),
                "market": {"state": state, "session_date": session.isoformat()},
                "nse_fallback": {"ok": self._nse["ok"], "last_ok_at": self._nse["last_ok_at"],
                                 "last_error": self._nse["last_error"], "last_error_at": self._nse["last_error_at"],
                                 "polls": self._nse["polls"], "network_calls": self._nse["network_calls"],
                                 "nextapi_calls": self._nse["nextapi_calls"], "lists_known": len(self._list_members),
                                 "demand": sum(1 for t in self._demand.values() if now - t <= DEMAND_TTL_S),
                                 "cadence_s": {"all_indices": ALLINDICES_TTL_S, "heatmap_list": HEATMAP_TTL_S,
                                               "equity_quote": NEXTAPI_TTL_S, "min_gap": NSE_GAP_S}}}
