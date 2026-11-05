"""
Live L1 ticks from the ICICI Breeze websocket — push, not poll (REQUIREMENTS F3.1; amendments A1, A5; minor 15).

Design (reports/bloomberg_program/DESIGN_SYSTEMS.md §6 as amended by design_review.md):
- One `LiveTicks` per data-service process (registered singleton, S4): the Breeze socketio client runs its own
  receive thread; we add exactly one worker thread (`live-ticks-ws`) for connect/resubscribe/watchdog and never
  block the event loop.
- Subscription model (A1): callers *ensure* symbols via GET; the set is a UNION with per-symbol `last_requested`
  and a 10-minute TTL eviction, capped at 50 by most-recently-requested, with the holdings always pinned.
  There is no POST and no set-replace — concurrent panels cannot thrash each other, and restarts self-heal
  within one poll.
- chg_pct (A5): prefer the previous close carried by the tick itself; fall back to the bhavcopy close joined at
  subscribe time; |chg| > 25% is clamped to None with hint "possible corporate action".
- Watchdog (minor 15): LIVE + market hours + no tick for 120 s → DEGRADED; the next tick flips it straight back
  to LIVE. Connect failures: 3 strikes in 5 minutes → DEGRADED with a 10-minute cool-off.
- Kill switch: `LIVE_TICKS` env, **default OFF** until the Phase-4 live spike passes — everything constructs
  lazily and no websocket is touched unless LIVE_TICKS=1.

Session handling: the Breeze client is BORROWED from the existing provider (`provider._breeze`); there is no
second login path. If the provider's session dies, the worker tears down and parks in DISCONNECTED; the next
ensure() after the provider reconnects (08:00 login or /provider/configure) starts a fresh worker.
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
MAX_SYMBOLS = 50
SYMBOL_TTL_S = 600.0               # A1: unsubscribe symbols nobody asked about for 10 min
REQUESTED_CAP = 200                # hard bound on the request ledger itself (S1), 4× the sub cap
FRESH_S = 5.0                      # consumers treat ticks older than this as stale
RESYNC_EVERY_S = 30.0
NO_TICK_DEGRADED_S = 120.0         # minor 15: global watchdog, flips back on the next tick
STRIKES, STRIKE_WINDOW_S, COOLOFF_S = 3, 300.0, 600.0
BACKOFF_S = (2.0, 4.0, 8.0, 16.0, 32.0, 60.0)
CLAMP_PCT = 25.0                   # A5

OFF, CONNECTING, LIVE, DEGRADED, DISCONNECTED = "OFF", "CONNECTING", "LIVE", "DEGRADED", "DISCONNECTED"

# Breeze L1 field aliases seen in the wild (intraday-data memory + defensive):
_PRICE_KEYS = ("last", "ltp", "Ltp", "last_traded_price")
_PREV_CLOSE_KEYS = ("close", "previous_close", "prev_close")
_TTQ_KEYS = ("ttq", "TTQ", "total_quantity_traded")
_LTT_KEYS = ("ltt", "last_traded_time")
_BID_KEYS = ("bPrice", "best_bid_price", "bid")
_ASK_KEYS = ("sPrice", "best_offer_price", "ask")
_SYMBOL_KEYS = ("stock_code", "symbol", "stock_name")


def enabled() -> bool:
    """Kill switch (gate condition): default OFF tonight; only LIVE_TICKS=1 arms the websocket."""
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


def _normalize(symbols: list[str]) -> list[str]:
    out: list[str] = []
    for s in symbols:
        s = s.strip().upper().replace(".NS", "").replace(".BO", "")
        if s and SYMBOL_RE.fullmatch(s) and s not in out:
            out.append(s)
    return out


class LiveTicks:
    """State machine OFF → CONNECTING → LIVE ⇄ DEGRADED → DISCONNECTED (→ CONNECTING on next ensure)."""

    def __init__(self,
                 provider_getter: Callable[[], Any],
                 prev_close_fn: Optional[Callable[[list[str]], dict[str, float]]] = None,
                 holdings_fn: Optional[Callable[[], list[str]]] = None,
                 clock: Callable[[], float] = time.time,
                 enabled_fn: Callable[[], bool] = enabled,
                 market_hours_fn: Callable[[], bool] = market_hours) -> None:
        self._get_provider = provider_getter
        self._prev_close_fn = prev_close_fn or (lambda syms: {})
        self._holdings_fn = holdings_fn or (lambda: [])
        self._clock = clock
        self._enabled = enabled_fn
        self._market_hours = market_hours_fn

        self._lock = threading.RLock()
        self._ticks: dict[str, dict[str, Any]] = {}
        self._requested: dict[str, float] = {}          # SYM → last_requested (A1 union + TTL)
        self._subscribed: dict[str, str] = {}           # SYM → isec code on the wire
        self._isec_to_sym: dict[str, str] = {}
        self._prev_close: dict[str, float] = {}         # bhavcopy fallback (A5)
        self._sub_errors: dict[str, str] = {}

        self.state = OFF
        self.error: Optional[str] = None
        self.last_tick_at: Optional[float] = None
        self.started_at: Optional[float] = None

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._resync = threading.Event()
        self._ws_up = False
        self._strikes: list[float] = []
        self._cooloff_until = 0.0
        self._last_sync = 0.0
        self._first_tick_logged = False
        self._store: Any = None            # W6: lazy TickStore; False = persistence decided OFF

    # ── public API ──────────────────────────────────────────────────────────────

    def ensure(self, symbols: list[str]) -> dict:
        """A1 auto-ensure: record the request (union semantics), arm the worker when enabled, return status.
        Cheap and idempotent — called on every GET /live/ticks poll."""
        now = self._clock()
        with self._lock:
            for s in _normalize(symbols)[:MAX_SYMBOLS]:
                self._requested[s] = now
            # Bound the request ledger HERE, not only in the worker's _target_set(): while the
            # kill switch is OFF no worker runs, so without this the dict grows per distinct
            # symbol forever (bloomberg_verdict defect #5 / S1). TTL first, then hard cap.
            self._requested = {s: t for s, t in self._requested.items() if now - t <= SYMBOL_TTL_S}
            if len(self._requested) > REQUESTED_CAP:
                keep = sorted(self._requested, key=self._requested.get, reverse=True)[:REQUESTED_CAP]
                self._requested = {s: self._requested[s] for s in keep}
        if self._enabled():
            self._kick()
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
                row = {"price": price, "chg_pct": round(chg, 4) if chg is not None else None,
                       "prev_close": prev, "ttq": t.get("ttq"), "bid": t.get("bid"), "ask": t.get("ask"),
                       "ltt": t.get("ltt"), "as_of": t.get("as_of"),
                       "ts_age_s": round(now - t["ts"], 1) if t.get("ts") else None}
                if hint:
                    row["hint"] = hint
                out[sym] = row
        return out

    def status(self) -> dict:
        with self._lock:
            age = round(self._clock() - self.last_tick_at, 1) if self.last_tick_at else None
            return {"state": self.state, "connected": self.state == LIVE, "error": self.error,
                    "subscribed": len(self._subscribed), "requested": len(self._requested),
                    "last_tick_age_s": age,
                    "sub_errors": dict(self._sub_errors) if self._sub_errors else {}}

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

    def _kick(self) -> None:
        if self._clock() < self._cooloff_until:
            return
        self._resync.set()
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
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
            prov = self._safe_provider()
            if prov is None or not prov.is_connected():
                self._teardown_ws()
                self._set_state(DISCONNECTED, "broker session not connected")
                return                                   # parked; next ensure() restarts us
            now = self._clock()
            if now < self._cooloff_until:
                self._stop.wait(5.0)
                continue
            if not self._ws_up:
                self._set_state(CONNECTING)
                try:
                    self._connect_once(prov)
                    self._ws_up = True
                    self._strikes.clear()
                    self._set_state(LIVE, None)
                    self._resync.set()
                except Exception as exc:                 # noqa: BLE001 — network path
                    self._register_strike(f"ws_connect failed: {exc}")
                    n = max(min(len(self._strikes), len(BACKOFF_S)) - 1, 0)
                    self._stop.wait(BACKOFF_S[n] + random.uniform(0, 1))
                    continue
            if self._resync.is_set() or now - self._last_sync > RESYNC_EVERY_S:
                self._resync.clear()
                try:
                    self._sync_subscriptions(prov)
                except Exception as exc:                 # noqa: BLE001 — a failed diff is retried next cycle
                    logger.warning("live-ticks resubscribe failed", error=str(exc))
                self._last_sync = now
            self._watchdog_check()
            self._stop.wait(1.0)

    def _connect_once(self, prov: Any) -> None:
        patch_socketio_wait(20.0)
        breeze = prov._breeze                            # borrowed client; documented in the singleton register
        breeze.on_ticks = self._on_tick
        breeze.ws_connect()

    def _teardown_ws(self) -> None:
        prov = self._safe_provider()
        try:
            if self._ws_up and prov is not None and getattr(prov, "_breeze", None) is not None:
                prov._breeze.ws_disconnect()
        except Exception:  # noqa: BLE001 — teardown is best-effort
            pass
        self._ws_up = False
        with self._lock:
            self._subscribed.clear()                     # a reconnect resubscribes everything

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

    def _target_set(self) -> list[str]:
        """Holdings pinned first, then requested-within-TTL by recency, capped at MAX_SYMBOLS."""
        now = self._clock()
        with self._lock:
            self._requested = {s: t for s, t in self._requested.items() if now - t <= SYMBOL_TTL_S}
            pinned = _normalize(self._holdings_fn())
            rest = sorted((s for s in self._requested if s not in pinned),
                          key=lambda s: self._requested[s], reverse=True)
        return (pinned + rest)[:MAX_SYMBOLS]

    def _sync_subscriptions(self, prov: Any) -> None:
        target = self._target_set()
        with self._lock:
            current = set(self._subscribed)
        add = [s for s in target if s not in current]
        drop = [s for s in current if s not in target]
        if add:
            self._join_prev_close(add)
        breeze = prov._breeze
        for sym in add:
            try:
                isec = prov._resolve_isec_code(sym)
                breeze.subscribe_feeds(exchange_code="NSE", stock_code=isec, product_type="cash",
                                       get_exchange_quotes=True, get_market_depth=False)
                with self._lock:
                    self._subscribed[sym] = isec
                    self._isec_to_sym[isec] = sym
                    self._sub_errors.pop(sym, None)
            except Exception as exc:                     # noqa: BLE001 — per-symbol failure is not fatal (design)
                with self._lock:
                    self._sub_errors[sym] = str(exc)[:120]
        for sym in drop:
            try:
                isec = self._subscribed.get(sym)
                if isec:
                    breeze.unsubscribe_feeds(exchange_code="NSE", stock_code=isec, product_type="cash",
                                             get_exchange_quotes=True, get_market_depth=False)
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                isec = self._subscribed.pop(sym, None)
                if isec:
                    self._isec_to_sym.pop(isec, None)

    def _join_prev_close(self, symbols: list[str]) -> None:
        """Bhavcopy fallback previous closes (A5), fetched on the worker thread — never the event loop."""
        try:
            got = self._prev_close_fn(symbols) or {}
            with self._lock:
                self._prev_close.update({k: float(v) for k, v in got.items() if v})
        except Exception as exc:  # noqa: BLE001 — fallback only; tick-carried close still works
            logger.warning("prev-close join failed", error=str(exc))

    # ── ticks ───────────────────────────────────────────────────────────────────

    def _on_tick(self, payload: Any) -> None:
        """Runs on the socketio receive thread: O(µs), one dict write, no IO."""
        try:
            if not isinstance(payload, dict):
                return
            if not self._first_tick_logged:
                self._first_tick_logged = True
                logger.debug("first raw tick", keys=sorted(payload.keys()), sample=str(payload)[:400])
            raw_sym = _first(payload, _SYMBOL_KEYS)
            if not raw_sym:
                return
            raw_sym = str(raw_sym).upper()
            sym = self._isec_to_sym.get(raw_sym, raw_sym)
            price = _first(payload, _PRICE_KEYS)
            if price is None:
                return
            prev = _first(payload, _PREV_CLOSE_KEYS)
            now = self._clock()
            tick = {"price": float(price), "ts": now, "as_of": datetime.now(IST).isoformat(timespec="seconds"),
                    "ttq": payload.get(_TTQ_KEYS[0]) or _first(payload, _TTQ_KEYS),
                    "ltt": _first(payload, _LTT_KEYS),
                    "bid": _first(payload, _BID_KEYS), "ask": _first(payload, _ASK_KEYS)}
            if prev:
                try:
                    tick["prev_close"] = float(prev)                     # A5: the tick's own close wins
                except (TypeError, ValueError):
                    pass
            with self._lock:
                self._ticks[sym] = tick
            self.last_tick_at = now
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
        _instance = LiveTicks(provider_getter, prev_close_fn=prev_close_fn, holdings_fn=holdings_fn)
    return _instance


def instance() -> Optional[LiveTicks]:
    return _instance


def shutdown_instance() -> None:
    global _instance
    if _instance is not None:
        _instance.shutdown()
        _instance = None
