"""
Live L1 ticks from the ICICI Breeze websocket — push, not poll (REQUIREMENTS F3.1; amendments A1, A5; minor 15).

Design (reports/bloomberg_program/DESIGN_SYSTEMS.md §6 as amended by design_review.md; live-NSE program LV-DATA):
- One `LiveTicks` per data-service process (registered singleton, S4): the Breeze socketio client runs its own
  receive thread; we add exactly one worker thread (`live-ticks-ws`) for connect/resubscribe/watchdog and never
  block the event loop.
- Token mapping (LV-DATA, 5 Nov 2026 — the September "L1 ticks silent" root cause): every tick arrives keyed
  `symbol = '4.1!<NSE token>'` (indices by name: '4.1!NIFTY 50'), NOT the isec code. We subscribe with the token list
  (`subscribe_feeds(stock_token=[...])`, the security master's EQ/BE row via the provider's `_resolve_ws_token`) and map
  ticks back through `_token_to_sym`. The old stock_code/isec lookup stays only as a legacy path.
- Subscription model (A1): callers *ensure* symbols via GET; the set is a UNION with per-symbol `last_requested`
  and a 10-minute TTL eviction, capped at MAX_SYMBOLS by most-recently-requested, with the holdings and the registered
  pin source (indices, NIFTY 50 / NIFTY BANK members, watchlist while the market is open) always first.
  There is no POST and no set-replace — concurrent panels cannot thrash each other, and restarts self-heal
  within one poll.
- Cap (L-CAPACITY, 5 Nov 2026): one socket carried 540 tokens clean twice and 1,040 for 90 s; the live contract caps the
  engine at 300 (index + members + holdings + on-screen names), half the measured clean load.
- chg_pct (A5): prefer the previous close carried by the tick itself; fall back to the bhavcopy close joined at
  subscribe time; |chg| > 25% is clamped to None with hint "possible corporate action".
- Watchdog (minor 15): LIVE + market hours + no tick for 120 s → DEGRADED; the next tick flips it straight back
  to LIVE. Connect failures: 3 strikes in 5 minutes → DEGRADED with a 10-minute cool-off.
- Teardown (L-CAPACITY): `BreezeConnect.ws_disconnect()` does not close the socket (python-socketio reconnects in 2-3 s
  and Breeze's rewatch re-joins every token), so teardown also closes the handler's own `sio` and clears its tokenlist.
- Kill switch: `LIVE_TICKS` env, **default OFF** until the PM flips it at deploy — everything constructs lazily and no
  websocket is touched unless LIVE_TICKS=1.

Session handling: the Breeze client is BORROWED from the existing provider (`provider._breeze`); there is no
second login path. If the provider's session dies, the worker tears down and parks in DISCONNECTED; the next
ensure() after the provider reconnects (08:00 login or /provider/configure) starts a fresh worker. A provider swap
(a new `_breeze` object after /provider/configure) tears the old socket down and reconnects on the new client.
"""
from __future__ import annotations

import os
import random
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

import pytz

from shared.breeze_cache import patch_socketio_wait
from shared.logging import get_logger

import tick_store  # W6: tick persistence — lazy, kill-switched; see the _on_tick hook

logger = get_logger("live-ticks")

IST = pytz.timezone("Asia/Kolkata")
SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
INDEX_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &:/.()%-]{2,59}$")
CAP_DEFAULT, CAP_FLOOR, CAP_CEILING = 300, 52, 500


def cap_from_env(raw: str | None) -> int:
    """LIVE_TICKS_MAX_SYMBOLS → the subscription cap. Default 300 (the live contract). L-CAPACITY measured 540 tokens (500
    stocks + 40 indices) clean on one socket at 11-13 % of a core and recommends ≤ 500 stocks, hence the ceiling; the floor
    keeps NIFTY + its 50 members + one more. Raising it trades fewer evictions (a page re-opened after a busy stretch shows
    STALE rows for 2-5 s while its names re-subscribe) for CPU on the GIL-holding socket.io receive thread."""
    try:
        v = int(str(raw).strip()) if raw not in (None, "") else CAP_DEFAULT
    except ValueError:
        return CAP_DEFAULT
    return max(CAP_FLOOR, min(CAP_CEILING, v))


MAX_SYMBOLS = cap_from_env(os.getenv("LIVE_TICKS_MAX_SYMBOLS"))
SYMBOL_TTL_S = 600.0               # A1: unsubscribe symbols nobody asked about for 10 min
REQUESTED_CAP = 2 * MAX_SYMBOLS    # hard bound on the request ledger itself (S1)
FRESH_S = 5.0                      # consumers treat ticks older than this as stale
HEARTBEAT_S = 10.0                 # L-CAPACITY: NIFTY 50 ticks at 10 Hz; no tick on the socket for 10 s = feed not healthy
RESYNC_EVERY_S = 30.0
NO_TICK_DEGRADED_S = 120.0         # minor 15: global watchdog, flips back on the next tick
STRIKES, STRIKE_WINDOW_S, COOLOFF_S = 3, 300.0, 600.0
BACKOFF_S = (2.0, 4.0, 8.0, 16.0, 32.0, 60.0)
CLAMP_PCT = 25.0                   # A5
SUB_CHUNK = 50                     # tokens per subscribe_feeds call (one socket.io 'join' each; L-CAPACITY used 50)
UNRESOLVED_RETRY_S = 3600.0        # a name with no websocket token is not retried for an hour (keeps it out of the cap)

OFF, CONNECTING, LIVE, DEGRADED, DISCONNECTED = "OFF", "CONNECTING", "LIVE", "DEGRADED", "DISCONNECTED"

# Index names: the terminal speaks NSE's allIndices spelling; Breeze's index tokens are the security master's names.
INDEX_WS_ALIASES: dict[str, str] = {
    "NIFTY FINANCIAL SERVICES": "NIFTY FIN SERVICE", "NIFTY MIDCAP SELECT": "NIFTY MID SELECT",
    "NIFTY SMALLCAP 100": "NIFTY SMLCAP 100", "NIFTY SMALLCAP 50": "NIFTY SMLCAP 50",
    "NIFTY INFRASTRUCTURE": "NIFTY INFRA", "NIFTY SERVICES SECTOR": "NIFTY SERV SECTOR",
    "NIFTY TOTAL MARKET": "NIFTY TOTAL MKT", "NIFTY HEALTHCARE INDEX": "NIFTY HEALTHCARE",
    "NIFTY INDIA CONSUMPTION": "NIFTY CONSUMPTION", "NIFTY INDIA FPI 150": "NIFTY FPI 150",
}
# L-CAPACITY: these index tokens exist in the master but never ticked (35 of 40 stream).
SILENT_INDEX_TOKENS = frozenset({"CNX 100", "CNX DEFTY", "CNX NIFTY JUNIOR", "NIFTY CPSE", "S&P CNX NIFTYY", "DJIA",
                                 "FTSE100", "S&P500"})
# Old spellings callers still send for the three tape indices.
LEGACY_INDEX_NAMES: dict[str, str] = {"NIFTY": "NIFTY 50", "NIFTY50": "NIFTY 50", "NSEI": "NIFTY 50", "^NSEI": "NIFTY 50",
                                      "BANKNIFTY": "NIFTY BANK", "NIFTYBANK": "NIFTY BANK", "^NSEBANK": "NIFTY BANK",
                                      "INDIAVIX": "INDIA VIX", "^INDIAVIX": "INDIA VIX"}

# Breeze L1 field aliases seen in the wild (intraday-data memory + defensive):
_PRICE_KEYS = ("last", "ltp", "Ltp", "last_traded_price")
_PREV_CLOSE_KEYS = ("close", "previous_close", "prev_close")
_TTQ_KEYS = ("ttq", "TTQ", "total_quantity_traded")
_LTT_KEYS = ("ltt", "last_traded_time")
_BID_KEYS = ("bPrice", "best_bid_price", "bid")
_ASK_KEYS = ("sPrice", "best_offer_price", "ask")
_SYMBOL_KEYS = ("stock_code", "symbol", "stock_name")      # legacy (isec) path only — see _on_tick

# Pin source registered by the live-quotes layer (main.py route block): the index + members + watchlist while the
# market is open. A module-level slot so the lifespan's init() call stays untouched.
_pins_source: Optional[Callable[[], list[str]]] = None


def set_pins_source(fn: Optional[Callable[[], list[str]]]) -> None:
    global _pins_source
    _pins_source = fn


def _registered_pins() -> list[str]:
    """The registered pin source, read at call time (only the process singleton from init() uses it)."""
    fn = _pins_source
    return list(fn() or []) if fn is not None else []


def enabled() -> bool:
    """Kill switch (gate condition): default OFF; only LIVE_TICKS=1 arms the websocket."""
    return os.getenv("LIVE_TICKS", "0") == "1"


def market_hours(now: Optional[datetime] = None) -> bool:
    n = now or datetime.now(IST)
    if n.weekday() >= 5:
        return False
    hm = n.hour * 60 + n.minute
    return 9 * 60 + 15 <= hm <= 15 * 60 + 30


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", 0, "0") or (k in _PREV_CLOSE_KEYS and isinstance(v, (int, float)) and v):
            return v
    return None


def _num(v: Any) -> Optional[float]:
    """Tick field → float; '' (index ticks carry empty bid/ask/ttq), None, junk → None."""
    if v is None or v == "":
        return None
    try:
        x = float(str(v).replace(",", "").rstrip("Cc"))
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def parse_ltt(v: Any) -> Optional[float]:
    """Breeze's ltt → epoch seconds. The SDK formats the raw epoch with `datetime.fromtimestamp(x).strftime('%c')`
    (process-local time, e.g. 'Thu Nov  5 10:02:23 2026'), so time.mktime (local time) inverts it exactly."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for fmt in ("%a %b %d %H:%M:%S %Y", "%d-%b-%Y %H:%M:%S"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def is_index(sym: str) -> bool:
    """Index names carry a space ('NIFTY 50', 'INDIA VIX'); NSE equity symbols never do."""
    return " " in sym


def canonical(sym: str) -> Optional[str]:
    """Request spelling → the engine's key: upper case, '.NS' dropped, legacy index names mapped; None if invalid."""
    s = re.sub(r"\s+", " ", str(sym)).strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        s = s[:-3]
    s = LEGACY_INDEX_NAMES.get(s, s)
    if not s:
        return None
    if is_index(s):
        return s if INDEX_RE.fullmatch(s) else None
    return s if SYMBOL_RE.fullmatch(s) else None


def ws_name(sym: str) -> str:
    """The name the security master knows: NSE index spellings mapped to Breeze's (equities unchanged)."""
    return INDEX_WS_ALIASES.get(sym, sym)


def _normalize(symbols: list[str]) -> list[str]:
    out: list[str] = []
    for s in symbols:
        c = canonical(s)
        if c and c not in out:
            out.append(c)
    return out


class LiveTicks:
    """State machine OFF → CONNECTING → LIVE ⇄ DEGRADED → DISCONNECTED (→ CONNECTING on next ensure)."""

    def __init__(self,
                 provider_getter: Callable[[], Any],
                 prev_close_fn: Optional[Callable[[list[str]], dict[str, float]]] = None,
                 holdings_fn: Optional[Callable[[], list[str]]] = None,
                 clock: Callable[[], float] = time.time,
                 enabled_fn: Callable[[], bool] = enabled,
                 market_hours_fn: Callable[[], bool] = market_hours,
                 pins_fn: Optional[Callable[[], list[str]]] = None) -> None:
        self._get_provider = provider_getter
        self._prev_close_fn = prev_close_fn or (lambda syms: {})
        self._holdings_fn = holdings_fn or (lambda: [])
        self._pins_fn = pins_fn                          # init() passes the module-level registered source
        self._clock = clock
        self._enabled = enabled_fn
        self._market_hours = market_hours_fn

        self._lock = threading.RLock()
        self._ticks: dict[str, dict[str, Any]] = {}
        self._requested: dict[str, float] = {}          # SYM → last_requested (A1 union + TTL)
        self._subscribed: dict[str, str] = {}           # SYM → websocket token on the wire ('4.1!1333')
        self._subscribed_at: dict[str, float] = {}
        self._token_to_sym: dict[str, str] = {}         # '4.1!1333' → 'HDFCBANK' (what every tick is keyed by)
        self._isec_to_sym: dict[str, str] = {}          # legacy path: a tick carrying stock_code (isec) instead
        self._prev_close: dict[str, float] = {}         # bhavcopy fallback (A5)
        self._sub_errors: dict[str, str] = {}
        self._unresolved: dict[str, float] = {}         # SYM → retry-after (no websocket token)

        self.state = OFF
        self.error: Optional[str] = None
        self.last_tick_at: Optional[float] = None
        self.started_at: Optional[float] = None
        self.unmapped_ticks = 0
        self._unmapped_sample: Optional[str] = None
        self._sec_ids = [0] * 60                        # ticks-per-minute ring (O(1) per tick, no lock)
        self._sec_counts = [0] * 60

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._resync = threading.Event()
        self._ws_up = False
        self._handler: Any = None                       # the SocketEventBreeze of OUR connection (teardown fix)
        self._conn_breeze: Any = None                   # the client we connected with (provider-swap detection)
        self._strikes: list[float] = []
        self._cooloff_until = 0.0
        self._last_sync = 0.0
        self._first_tick_logged = False
        self._store: Any = None            # W6: lazy TickStore; False = persistence decided OFF

    # ── public API ──────────────────────────────────────────────────────────────

    def ensure(self, symbols: list[str]) -> dict:
        """A1 auto-ensure: record the request (union semantics), arm the worker when enabled, return status.
        Cheap and idempotent — called on every GET /live/ticks and /live/quotes poll."""
        now = self._clock()
        new = False
        with self._lock:
            for s in _normalize(symbols)[:MAX_SYMBOLS]:
                if s not in self._requested and s not in self._subscribed:
                    new = True
                self._requested[s] = now
            # Bound the request ledger HERE, not only in the worker's _target_set(): while the
            # kill switch is OFF no worker runs, so without this the dict grows per distinct
            # symbol forever (bloomberg_verdict defect #5 / S1). TTL first, then hard cap.
            self._requested = {s: t for s, t in self._requested.items() if now - t <= SYMBOL_TTL_S}
            if len(self._requested) > REQUESTED_CAP:
                keep = sorted(self._requested, key=self._requested.get, reverse=True)[:REQUESTED_CAP]  # type: ignore[arg-type]
                self._requested = {s: self._requested[s] for s in keep}
        if self._enabled():
            self._kick(resync=new or not self._ws_up)
        else:
            self.state = OFF
        return self.status()

    def snapshot(self, symbols: Optional[list[str]] = None) -> dict[str, dict]:
        now = self._clock()
        want = set(_normalize(symbols)) if symbols else None
        out: dict[str, dict] = {}
        with self._lock:
            for sym, t in self._ticks.items():
                if want is not None and sym not in want:
                    continue
                prev = t.get("prev_close") or self._prev_close.get(sym)      # A5 preference order
                chg: Optional[float] = None
                hint: Optional[str] = None
                price = t.get("price")
                if prev and price:
                    chg = (price / prev - 1) * 100
                    if abs(chg) > CLAMP_PCT:
                        chg, hint = None, "possible corporate action"        # A5 clamp
                ltt_epoch = t.get("ltt_epoch")
                row = {"price": price, "chg_pct": round(chg, 4) if chg is not None else None,
                       "prev_close": prev, "ttq": t.get("ttq"), "bid": t.get("bid"), "ask": t.get("ask"),
                       "ltt": t.get("ltt"), "as_of": t.get("as_of"),
                       "ts_age_s": round(now - t["ts"], 1) if t.get("ts") else None,
                       "ts": t.get("ts"), "open": t.get("open"), "high": t.get("high"), "low": t.get("low"),
                       "avg_price": t.get("avg_price"), "ltt_epoch": ltt_epoch,
                       "last_trade_age_s": round(now - ltt_epoch, 1) if ltt_epoch else None,
                       "token": t.get("token"), "kind": "index" if is_index(sym) else "equity"}
                if hint:
                    row["hint"] = hint
                out[sym] = row
        return out

    def is_subscribed(self, sym: str) -> bool:
        return sym in self._subscribed

    def heartbeat_age(self) -> Optional[float]:
        """Seconds since ANY tick on the socket (NIFTY 50 is pinned and ticks at 10 Hz in session)."""
        return round(self._clock() - self.last_tick_at, 1) if self.last_tick_at else None

    def feed_healthy(self) -> bool:
        age = self.heartbeat_age()
        return self.state in (LIVE, DEGRADED) and self._ws_up and age is not None and age <= HEARTBEAT_S

    def ticks_per_min(self) -> int:
        now = int(self._clock())
        return sum(c for i, c in zip(self._sec_ids, self._sec_counts, strict=True) if 0 <= now - i < 60)

    def status(self) -> dict:
        now = self._clock()
        with self._lock:
            age = round(now - self.last_tick_at, 1) if self.last_tick_at else None
            silent = sorted(s for s, at in self._subscribed_at.items()
                            if now - at > 60 and (s not in self._ticks or self._ticks[s].get("ts", 0) < at))
            return {"state": self.state, "connected": self.state == LIVE, "error": self.error,
                    "subscribed": len(self._subscribed), "requested": len(self._requested),
                    "cap": MAX_SYMBOLS, "last_tick_age_s": age, "ticks_per_min": self.ticks_per_min(),
                    "unmapped_ticks": self.unmapped_ticks,
                    "no_first_tick": {"count": len(silent), "symbols": silent[:20]},
                    "unresolved": sorted(self._unresolved)[:20],
                    "sub_errors": dict(list(self._sub_errors.items())[:20]) if self._sub_errors else {}}

    def shutdown(self) -> None:
        """Idempotent full teardown (lifespan shutdown)."""
        self._stop.set()
        self._teardown_ws()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=5)
        self._thread = None
        self.state = OFF

    # ── worker ──────────────────────────────────────────────────────────────────

    def _kick(self, resync: bool = True) -> None:
        if self._clock() < self._cooloff_until:
            return
        if resync:
            self._resync.set()
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._resync.set()
            self._thread = threading.Thread(target=self._run, name="live-ticks-ws", daemon=True)
            self._thread.start()

    def _safe_provider(self) -> Any:
        try:
            return self._get_provider()
        except Exception:  # noqa: BLE001 — provider not initialised yet
            return None

    def _run(self) -> None:
        self.started_at = self._clock()
        while not self._stop.is_set():
            if not self._enabled():
                break
            if not self._step():
                return                                   # parked; next ensure() restarts us
            self._stop.wait(1.0)

    def _step(self) -> bool:
        """One worker iteration (separate from the loop so tests drive it without threads). False = park."""
        prov = self._safe_provider()
        if prov is None or not prov.is_connected():
            self._teardown_ws()
            self._set_state(DISCONNECTED, "broker session not connected")
            return False
        if self._ws_up and self._conn_breeze is not None and getattr(prov, "_breeze", None) is not self._conn_breeze:
            logger.info("live-ticks: broker client replaced (re-login) — reconnecting the socket")
            self._teardown_ws()
        now = self._clock()
        if now < self._cooloff_until:
            self._stop.wait(5.0)
            return True
        if not self._ws_up:
            self._set_state(CONNECTING)
            try:
                self._connect_once(prov)
                self._ws_up = True
                self._strikes.clear()
                self._set_state(LIVE, None)
                self._resync.set()
            except Exception as exc:                     # noqa: BLE001 — network path
                self._register_strike(f"ws_connect failed: {exc}")
                n = max(min(len(self._strikes), len(BACKOFF_S)) - 1, 0)
                self._stop.wait(BACKOFF_S[n] + random.uniform(0, 1))
                return True
        if self._resync.is_set() or now - self._last_sync > RESYNC_EVERY_S:
            self._resync.clear()
            try:
                self._sync_subscriptions(prov)
            except Exception as exc:                     # noqa: BLE001 — a failed diff is retried next cycle
                logger.warning("live-ticks resubscribe failed", error=str(exc))
            self._last_sync = now
        self._watchdog_check()
        return True

    def _connect_once(self, prov: Any) -> None:
        patch_socketio_wait(20.0)
        breeze = prov._breeze                            # borrowed client; documented in the singleton register
        breeze.on_ticks = self._on_tick
        breeze.ws_connect()
        self._conn_breeze = breeze
        self._handler = getattr(breeze, "sio_rate_refresh_handler", None)

    def _teardown_ws(self) -> None:
        """ws_disconnect() + close OUR handler's socket and clear its tokenlist: ws_disconnect alone leaves python-socketio
        reconnecting with every token re-joined (L-CAPACITY: 1,036-1,122 ticks in the 5 s after it)."""
        handler = self._handler
        breeze = self._conn_breeze
        if breeze is None:
            prov = self._safe_provider()
            breeze = getattr(prov, "_breeze", None) if prov is not None else None
        if handler is None and breeze is not None:
            handler = getattr(breeze, "sio_rate_refresh_handler", None)
        try:
            if self._ws_up and breeze is not None:
                breeze.ws_disconnect()
        except Exception:  # noqa: BLE001 — teardown is best-effort
            pass
        if handler is not None and self._ws_up:
            try:
                tl = getattr(handler, "tokenlist", None)
                if tl is not None:
                    tl.clear()                           # a late reconnect must not re-join anything
            except Exception:  # noqa: BLE001
                pass
            try:
                sio = getattr(handler, "sio", None)
                if sio is not None:
                    sio.disconnect()                     # the call that actually ends the stream
            except Exception:  # noqa: BLE001
                pass
        self._ws_up = False
        self._handler = None
        self._conn_breeze = None
        with self._lock:
            self._subscribed.clear()                     # a reconnect resubscribes everything
            self._subscribed_at.clear()
            self._token_to_sym.clear()

    def _set_state(self, state: str, error: Optional[str] = "__keep__") -> None:
        self.state = state
        if error != "__keep__":
            self.error = error

    def _register_strike(self, why: str) -> None:
        now = self._clock()
        self._strikes = [t for t in self._strikes if now - t <= STRIKE_WINDOW_S] + [now]
        logger.warning("live-ticks strike", n=len(self._strikes), why=why[:200])
        if len(self._strikes) >= STRIKES:
            self._cooloff_until = now + COOLOFF_S
            self._strikes.clear()
            self._teardown_ws()
            self._set_state(DEGRADED, f"{STRIKES} connect failures — cooling off {int(COOLOFF_S / 60)} min")

    # ── subscriptions (A1) ──────────────────────────────────────────────────────

    def _pins(self) -> list[str]:
        fn = self._pins_fn
        if fn is None:
            return []
        try:
            return _normalize(list(fn() or []))
        except Exception as exc:  # noqa: BLE001 — a failing pin source never blocks the requested set
            logger.debug("live-ticks pin source failed", error=str(exc)[:120])
            return []

    def _target_set(self) -> list[str]:
        """Holdings pinned first, then the pin source, then requested-within-TTL by recency, capped at MAX_SYMBOLS.
        Names with no websocket token are skipped for an hour (they would only hold a slot)."""
        now = self._clock()
        pinned_all = _normalize(self._holdings_fn()) + self._pins()
        with self._lock:
            self._requested = {s: t for s, t in self._requested.items() if now - t <= SYMBOL_TTL_S}
            self._unresolved = {s: t for s, t in self._unresolved.items() if t > now}
            pinned = [s for s in dict.fromkeys(pinned_all) if s not in self._unresolved]
            pin_set = set(pinned)
            rest = sorted((s for s in self._requested if s not in pin_set and s not in self._unresolved),
                          key=lambda s: self._requested[s], reverse=True)
        return (pinned + rest)[:MAX_SYMBOLS]

    @staticmethod
    def _failed(resp: Any) -> Optional[str]:
        """subscribe_feeds returns {'message': ...} on success and a plain 'Exception while subscribing …' string on
        failure (the SDK swallows the exception); there is no server ack, so the first tick is the only proof."""
        if isinstance(resp, str) and "exception" in resp.lower():
            return resp[:120]
        return None

    def _sync_subscriptions(self, prov: Any) -> None:
        target = self._target_set()
        with self._lock:
            current = set(self._subscribed)
        target_set = set(target)
        add = [s for s in target if s not in current]
        drop = [s for s in current if s not in target_set]
        if add:
            self._join_prev_close([s for s in add if not is_index(s)])
        breeze = prov._breeze
        resolved: list[tuple[str, str]] = []
        now = self._clock()
        for sym in add:
            name = ws_name(sym)
            if is_index(sym) and name.upper() in SILENT_INDEX_TOKENS:
                with self._lock:
                    self._unresolved[sym] = now + UNRESOLVED_RETRY_S
                    self._sub_errors[sym] = "index does not stream on Breeze (L-CAPACITY)"
                continue
            try:
                resolved.append((sym, str(prov._resolve_ws_token(name))))
            except Exception as exc:                     # noqa: BLE001 — per-symbol failure is not fatal (design)
                with self._lock:
                    self._unresolved[sym] = now + UNRESOLVED_RETRY_S
                    self._sub_errors[sym] = str(exc)[:120] or "no websocket token"
        for i in range(0, len(resolved), SUB_CHUNK):
            part = resolved[i:i + SUB_CHUNK]
            tokens = [tok for _, tok in part]
            try:
                err = self._failed(breeze.subscribe_feeds(stock_token=tokens, get_exchange_quotes=True,
                                                          get_market_depth=False))
            except Exception as exc:                     # noqa: BLE001
                err = str(exc)[:120] or "subscribe failed"
            with self._lock:
                for sym, tok in part:
                    if err:
                        self._sub_errors[sym] = err      # retried at the next resync (not marked subscribed)
                        continue
                    self._subscribed[sym] = tok
                    self._subscribed_at[sym] = now
                    self._token_to_sym[tok] = sym
                    self._sub_errors.pop(sym, None)
        if drop:
            with self._lock:
                toks = [self._subscribed[s] for s in drop if s in self._subscribed]
            for i in range(0, len(toks), SUB_CHUNK):
                try:
                    breeze.unsubscribe_feeds(stock_token=toks[i:i + SUB_CHUNK], get_exchange_quotes=True,
                                             get_market_depth=False)
                except Exception:  # noqa: BLE001
                    pass
            with self._lock:
                for sym in drop:
                    tok = self._subscribed.pop(sym, "")
                    self._subscribed_at.pop(sym, None)
                    if tok:
                        self._token_to_sym.pop(tok, None)

    def _join_prev_close(self, symbols: list[str]) -> None:
        """Bhavcopy fallback previous closes (A5), fetched on the worker thread — never the event loop."""
        if not symbols:
            return
        try:
            got = self._prev_close_fn(symbols) or {}
            with self._lock:
                self._prev_close.update({k: float(v) for k, v in got.items() if v})
        except Exception as exc:  # noqa: BLE001 — fallback only; tick-carried close still works
            logger.warning("prev-close join failed", error=str(exc))

    # ── ticks ───────────────────────────────────────────────────────────────────

    def _map_symbol(self, payload: dict) -> Optional[str]:
        """'4.1!<token>' through the token map (the real wire format); a stock_code/isec-keyed payload through the
        legacy map; anything else is unmapped (counted, never stored under a raw key)."""
        raw = payload.get("symbol")
        if isinstance(raw, str) and "!" in raw:
            return self._token_to_sym.get(raw)
        code = payload.get("stock_code")
        if code:
            return self._isec_to_sym.get(str(code).upper())
        legacy = _first(payload, _SYMBOL_KEYS)
        return self._isec_to_sym.get(str(legacy).upper()) if legacy else None

    def _on_tick(self, payload: Any) -> None:
        """Runs on the socketio receive thread: O(µs), one dict write, no IO."""
        try:
            if not isinstance(payload, dict):
                return
            if not self._first_tick_logged:
                self._first_tick_logged = True
                logger.debug("first raw tick", keys=sorted(payload.keys()), sample=str(payload)[:400])
            sym = self._map_symbol(payload)
            if sym is None:
                self.unmapped_ticks += 1
                if self._unmapped_sample is None:
                    self._unmapped_sample = str(payload.get("symbol") or payload.get("stock_code"))[:40]
                return
            price = _first(payload, _PRICE_KEYS)
            if price is None or _num(price) is None:
                return
            prev = _first(payload, _PREV_CLOSE_KEYS)
            now = self._clock()
            ltt_raw = _first(payload, _LTT_KEYS)
            ltt_epoch = parse_ltt(ltt_raw)
            ttq = _num(payload.get(_TTQ_KEYS[0]) if payload.get(_TTQ_KEYS[0]) not in (None, "") else _first(payload, _TTQ_KEYS))
            tick = {"price": float(_num(price) or 0.0), "ts": now,
                    "as_of": datetime.fromtimestamp(now, IST).isoformat(timespec="seconds"),
                    "ttq": ttq, "ltt": ltt_raw, "ltt_epoch": ltt_epoch,
                    "bid": _num(_first(payload, _BID_KEYS)), "ask": _num(_first(payload, _ASK_KEYS)),
                    "open": _num(payload.get("open")), "high": _num(payload.get("high")), "low": _num(payload.get("low")),
                    "avg_price": _num(payload.get("avgPrice")), "ltq": _num(payload.get("ltq")),
                    "token": payload.get("symbol") if isinstance(payload.get("symbol"), str) else None}
            prev_f = _num(prev) if prev else None
            if prev_f:
                tick["prev_close"] = prev_f                                # A5: the tick's own close wins
            with self._lock:
                self._ticks[sym] = tick
            self.last_tick_at = now
            s = int(now)
            i = s % 60
            if self._sec_ids[i] != s:
                self._sec_ids[i], self._sec_counts[i] = s, 0
            self._sec_counts[i] += 1
            if self.state == DEGRADED:
                self._set_state(LIVE, None)                              # minor 15: flip back on next tick
            # W6 TICKS: persist to parquet via tick_store — constructed lazily ONLY when a tick
            # actually flows (zero cost while LIVE_TICKS=0). TICK_PERSIST kill switch, default ON
            # whenever ticks flow; read once per worker life. append() never raises (strike
            # counter in store stats) and this guard covers construction too: persistence can
            # NEVER break the feed.
            try:
                if self._store is None:
                    self._store = tick_store.get_store() if tick_store.persist_enabled() else False
                if self._store:
                    self._store.append(sym, tick)
            except Exception:  # noqa: BLE001 — persistence must never break the stream
                pass
        except Exception:  # noqa: BLE001 — a bad tick must never kill the stream
            pass

    def _watchdog_check(self) -> None:
        if self.state != LIVE or not self._market_hours():
            return
        ref = self.last_tick_at if self.last_tick_at is not None else self.started_at
        if ref is not None and self._clock() - ref > NO_TICK_DEGRADED_S:
            self._set_state(DEGRADED, f"no ticks for {int(NO_TICK_DEGRADED_S)} s during market hours")


# ── module singleton (S4 register: one per process; socketio owns its receive thread) ──

_instance: Optional[LiveTicks] = None


def init(provider_getter: Callable[[], Any],
         prev_close_fn: Optional[Callable[[list[str]], dict[str, float]]] = None,
         holdings_fn: Optional[Callable[[], list[str]]] = None) -> LiveTicks:
    global _instance
    if _instance is None:
        _instance = LiveTicks(provider_getter, prev_close_fn=prev_close_fn, holdings_fn=holdings_fn,
                              pins_fn=_registered_pins)
    return _instance


def instance() -> Optional[LiveTicks]:
    return _instance


def shutdown_instance() -> None:
    global _instance
    if _instance is not None:
        _instance.shutdown()
        _instance = None
