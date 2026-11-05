"""One HTTP client per process, host-allowlisted and paced (Terminal v2 PLAN §0.6 + 1.5; R-ARCH fix 4).

Two halves, one allowlist:

* **Async, service-to-service** (ui-api → data-service / master-controller): ``get_json(url, route=...)`` on a
  single module-level ``httpx.AsyncClient`` per process (``Limits(max_connections=32, max_keepalive_connections=16)``,
  keep-alive reused instead of ≈130 per-request client constructions), per-route timeouts (``ROUTE_TIMEOUTS``),
  a per-upstream circuit breaker (5 failures in 30 s → open 20 s → one half-open probe) and stale-serve: the last
  good body of a route is served, marked ``stale: true``, while the upstream flakes (``stale_for`` seconds).
  Failures raise ``UpstreamError(status_code, detail)``; routers map it to their HTTPException.
* **Sync, publisher fetches** (NSE, niftyindices, the gold list): ``PacedClient`` — the ``gold/hosts.py`` etiquette
  lifted here: refuse any host outside ``ALLOWED_HOSTS`` before a socket opens, ≥ 1.2 s between requests to one
  host, 20 s timeout, browser UA for NSE, 403/429 on an NSE host → 600 s breaker, Yahoo only for the one gold
  fetcher that opts in (``allow_yahoo=True``; PLAN §0.7: no new Yahoo caller).

The forbidden publishers (owner decisions) are listed so the static scans can assert their absence.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from shared.logging import get_logger

logger = get_logger(__name__)

# ── The allowlist (PLAN §0.6; gold's §c.6 list included verbatim) ─────────────────────────────────────────────────
NSE_HOSTS: frozenset[str] = frozenset({"nsearchives.nseindia.com", "www.nseindia.com", "niftyindices.com",
                                       "www.niftyindices.com"})
BREEZE_HOSTS: frozenset[str] = frozenset({"api.icicidirect.com", "breezeapi.icicidirect.com"})
YAHOO_HOSTS: frozenset[str] = frozenset({"query1.finance.yahoo.com", "query2.finance.yahoo.com"})
GOLD_HOSTS: frozenset[str] = frozenset({
    "publicreporting.cftc.gov", "www.cftc.gov", "ftp.cmegroup.com", "home.treasury.gov", "fred.stlouisfed.org",
    "api.stlouisfed.org", "api.spdrgoldshares.com", "www.ishares.com", "fsapi.gold.org", "api.imf.org", "cdn.lbma.org.uk",
    "www.lbma.org.uk", "en.sge.com.cn", "www.sge.com.cn", "www.shfe.com.cn", "ibjarates.com", "www.rbi.org.in",
    "directlink.icicidirect.com", "zerodha.com", "portal.amfiindia.com", "pib.gov.in", "ocean.nivel.bazg.admin.ch",
    "www.atlantafed.org", "nfs.faireconomy.media", "www.bea.gov", "www.matteoiacoviello.com", "thedocs.worldbank.org",
    "api.gold-api.com", "news.google.com",
})
ALLOWED_HOSTS: frozenset[str] = NSE_HOSTS | BREEZE_HOSTS | YAHOO_HOSTS | GOLD_HOSTS
# Our own services: loopback names and the legacy compose DNS names. Never a publisher.
INTERNAL_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1", "localhost", "::1", "data-service", "ui-api", "master-controller",
    "api-gateway", "feature-service", "ml-service", "rl-service", "risk-service", "execution-service", "monitoring-service",
    "redis",
})
FORBIDDEN_HOST_FRAGMENTS: tuple[str, ...] = (
    "www.cmegroup.com", "mcxindia.com", "kitco.com", "prices.lbma.org.uk", "stooq.com", "goldprice.org", "investing.com",
)

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 SuryaDhana")
PLAIN_UA = "SuryaDhana/1.0 (+private terminal; contact via repo)"
APP_UA = "Mozilla/5.0 (SuryaDhana-GoldDesk)"            # the only UA Yahoo answers with 200 (gold G-KITCO)
LIBRARY_UA_HOSTS: frozenset[str] = frozenset({"fred.stlouisfed.org"})   # FRED stalls on any UA naming this app
_PLAIN_UA_HOSTS: frozenset[str] = frozenset({"api.imf.org", "home.treasury.gov", "api.gold-api.com", "nfs.faireconomy.media",
                                             "api.stlouisfed.org"})

MIN_GAP_S = 1.2                      # between requests to one host (PLAN §0.6)
YAHOO_GAP_S = 6.0
DEFAULT_TIMEOUT_S = 20.0
NSE_BLOCK_S = 600.0                  # 403 / 429 from an NSE host → breaker for 600 s
YAHOO_BACKOFF_MIN = (5, 10, 20)


class HostNotAllowed(RuntimeError):
    """Raised before any network activity when a URL's host is outside the allowlist."""


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_internal(url: str) -> bool:
    return host_of(url) in INTERNAL_HOSTS


def is_allowed(url: str, *, allow_yahoo: bool = False) -> bool:
    host = host_of(url)
    if host in INTERNAL_HOSTS:
        return True
    if host in YAHOO_HOSTS:
        return allow_yahoo
    return host in ALLOWED_HOSTS


def assert_allowed(url: str, *, allow_yahoo: bool = False) -> str:
    host = host_of(url)
    if not is_allowed(url, allow_yahoo=allow_yahoo):
        why = "Yahoo is reserved for the single gold fetcher" if host in YAHOO_HOSTS else "host not in the allowlist"
        raise HostNotAllowed(f"{why}: {host or '<none>'}")
    return host


def user_agent_for(host: str) -> str | None:
    """``None`` means "send the HTTP library's default" (FRED refuses every UA that names this app)."""
    if host in LIBRARY_UA_HOSTS:
        return None
    if host in YAHOO_HOSTS:
        return APP_UA
    if host in _PLAIN_UA_HOSTS:
        return PLAIN_UA
    return BROWSER_UA


# ── Async half: one client per process, per-route timeouts, breaker, stale-serve ────────────────────────────────
LIMITS = httpx.Limits(max_connections=32, max_keepalive_connections=16)
ROUTE_TIMEOUTS: dict[str, httpx.Timeout] = {
    "live": httpx.Timeout(15.0, connect=3.0),         # nifty-live, gift-nifty, indices-live, quotes
    "default": httpx.Timeout(20.0, connect=3.0),
    "read": httpx.Timeout(30.0, connect=3.0),         # DuckDB-backed reads (history, screens)
    "slow": httpx.Timeout(120.0, connect=3.0),        # big payloads (events, fundamentals screen)
    "job": httpx.Timeout(600.0, connect=3.0),         # POST /jobs/* that run inline
}

_client_lock = threading.Lock()
_clients: dict[int, httpx.AsyncClient] = {}


def get_async_client() -> httpx.AsyncClient:
    """The process-wide AsyncClient for the running event loop (tests spin up loops; each gets its own)."""
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    with _client_lock:
        client = _clients.get(loop_id)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(limits=LIMITS, timeout=ROUTE_TIMEOUTS["default"], follow_redirects=False)
            _clients[loop_id] = client
        return client


async def aclose_async_client() -> None:
    """Close the client of the current loop (service shutdown / test teardown)."""
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    with _client_lock:
        client = _clients.pop(loop_id, None)
    if client is not None and not client.is_closed:
        await client.aclose()


class UpstreamError(Exception):
    """An upstream answer the caller cannot use: ``status_code`` (503 for transport / breaker) + ``detail``."""

    def __init__(self, status_code: int, detail: str, *, upstream: str = "", retry_after_s: float | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.upstream = upstream
        self.retry_after_s = retry_after_s


@dataclass
class CircuitBreaker:
    """Closed → (``threshold`` failures inside ``window_s``) → open for ``open_s`` → half-open: one probe."""

    name: str
    threshold: int = 5
    window_s: float = 30.0
    open_s: float = 20.0
    clock: Callable[[], float] = time.monotonic
    _failures: list[float] = field(default_factory=list)
    _opened_at: float | None = None
    _probing: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def state(self) -> str:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self.clock() - self._opened_at >= self.open_s:
            return "half-open"
        return "open"

    def allow(self) -> bool:
        """True when a call may go out now (closed, or the single half-open probe)."""
        with self._lock:
            st = self._state_locked()
            if st == "closed":
                return True
            if st == "half-open" and not self._probing:
                self._probing = True
                return True
            return False

    def remaining_s(self) -> float:
        with self._lock:
            if self._opened_at is None:
                return 0.0
            return max(0.0, self.open_s - (self.clock() - self._opened_at))

    def record(self, ok: bool) -> None:
        with self._lock:
            now = self.clock()
            if ok:
                self._failures.clear()
                self._opened_at = None
                self._probing = False
                self._set_gauge(False)
                return
            self._failures = [t for t in self._failures if now - t <= self.window_s] + [now]
            if self._opened_at is not None or len(self._failures) >= self.threshold:
                self._opened_at = now           # (re)open; a failed probe re-opens for a full period
                self._probing = False
                self._set_gauge(True)

    def _set_gauge(self, is_open: bool) -> None:
        with suppress(Exception):                  # metrics are optional
            from shared.metrics import set_breaker_open
            set_breaker_open(self.name, is_open)


_breakers: dict[str, CircuitBreaker] = {}
_stale: dict[str, tuple[Any, float]] = {}
_stale_lock = threading.Lock()
STALE_MAX_ITEMS = 256


def breaker_for(upstream: str) -> CircuitBreaker:
    with _client_lock:
        b = _breakers.get(upstream)
        if b is None:
            b = _breakers[upstream] = CircuitBreaker(upstream)
        return b


def reset_state() -> None:
    """Tests: forget breakers and stale bodies."""
    with _client_lock:
        _breakers.clear()
    with _stale_lock:
        _stale.clear()


def _stale_key(url: str, params: Mapping[str, Any] | None) -> str:
    return url if not params else url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))


def _remember(key: str, body: Any) -> None:
    with _stale_lock:
        if len(_stale) >= STALE_MAX_ITEMS and key not in _stale:
            oldest = min(_stale, key=lambda k: _stale[k][1])
            _stale.pop(oldest, None)
        _stale[key] = (body, time.monotonic())


def _stale_body(key: str, max_age_s: float | None) -> tuple[Any, float] | None:
    if not max_age_s:
        return None
    with _stale_lock:
        hit = _stale.get(key)
    if hit is None:
        return None
    age = time.monotonic() - hit[1]
    return (hit[0], age) if age <= max_age_s else None


def _mark_stale(body: Any, age_s: float) -> Any:
    if isinstance(body, dict):
        return {**body, "stale": True, "stale_age_s": round(age_s, 1),
                "stale_note": "upstream unavailable; the last good answer is shown"}
    return body


def _count(upstream: str, route: str, outcome: str) -> None:
    with suppress(Exception):                      # metrics are optional
        from shared.metrics import count_upstream
        count_upstream(upstream, route, outcome)


def upstream_of(url: str) -> str:
    """Upstream name for the breaker: the compose DNS name, else ``host:port``."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in ("data-service", "ui-api", "master-controller"):
        return host
    return f"{host}:{parsed.port}" if parsed.port else host


async def get_json(url: str, *, route: str = "default", params: Mapping[str, Any] | None = None,
                   upstream: str | None = None, timeout: httpx.Timeout | float | None = None,
                   stale_for: float | None = None, headers: Mapping[str, str] | None = None,
                   client: httpx.AsyncClient | None = None) -> Any:
    """GET a JSON body from one of our services (or an allowlisted host) through the shared client.

    ``route`` picks the timeout (``ROUTE_TIMEOUTS``) and labels the metric. ``stale_for`` enables stale-serve:
    the last 200 body for this URL+params is returned (marked ``stale: true``) when the upstream is down,
    answers 5xx, or the breaker is open, as long as it is at most ``stale_for`` seconds old. Non-2xx answers
    raise ``UpstreamError`` carrying the upstream status and a trimmed detail; transport errors and an open
    breaker raise ``UpstreamError(503, ...)``.
    """
    assert_allowed(url)
    name = upstream or upstream_of(url)
    br = breaker_for(name)
    key = _stale_key(url, params)
    if not br.allow():
        stale = _stale_body(key, stale_for)
        _count(name, route, "breaker_open")
        if stale is not None:
            return _mark_stale(stale[0], stale[1])
        raise UpstreamError(503, f"{name} unavailable: circuit open for {br.remaining_s():.0f} s", upstream=name,
                            retry_after_s=br.remaining_s())
    tmo = timeout if isinstance(timeout, httpx.Timeout) else (httpx.Timeout(timeout, connect=3.0) if timeout
                                                              else ROUTE_TIMEOUTS.get(route, ROUTE_TIMEOUTS["default"]))
    c = client or get_async_client()
    try:
        r = await c.get(url, params=dict(params) if params else None, timeout=tmo, headers=dict(headers) if headers else None)
    except httpx.HTTPError as exc:
        br.record(False)
        _count(name, route, "transport_error")
        stale = _stale_body(key, stale_for)
        if stale is not None:
            return _mark_stale(stale[0], stale[1])
        raise UpstreamError(503, f"{name} unreachable: {type(exc).__name__}: {exc}"[:300], upstream=name) from exc
    if 200 <= r.status_code < 300:
        try:
            body = r.json()
        except ValueError as exc:
            br.record(False)
            _count(name, route, "bad_json")
            raise UpstreamError(502, f"{name} returned a non-JSON body", upstream=name) from exc
        br.record(True)
        _count(name, route, "ok")
        if stale_for:
            _remember(key, body)
        return body
    detail = _detail(r)
    if r.status_code >= 500:
        br.record(False)
        _count(name, route, f"{r.status_code // 100}xx")
        stale = _stale_body(key, stale_for)
        if stale is not None:
            return _mark_stale(stale[0], stale[1])
    else:
        br.record(True)                       # a 4xx is a healthy upstream saying no
        _count(name, route, f"{r.status_code // 100}xx")
    raise UpstreamError(r.status_code, detail, upstream=name)


def _detail(r: httpx.Response, limit: int = 300) -> str:
    """The upstream's ``detail`` when it sent the error envelope, else the trimmed body (routers/_upstream.py)."""
    try:
        body = r.json()
        if isinstance(body, dict) and "detail" in body:
            d = body["detail"]
            return d if isinstance(d, str) else str(d)[:limit]
    except ValueError:
        pass
    return (r.text or f"HTTP {r.status_code}")[:limit]


# ── Sync half: the paced publisher client (gold/hosts.py lifted) ────────────────────────────────────────────────
@dataclass
class _HostState:
    last_at: float = 0.0
    backoff_until: float = 0.0
    strikes: int = 0


@dataclass
class PacedClient:
    """Allowlisted, paced, keep-alive HTTP client for publisher fetches (sync; jobs and ingests run on threads).

    ``transport`` lets tests inject ``httpx.MockTransport``; ``sleep`` / ``clock`` let them skip the pacing.
    One ``httpx.Client`` per instance (cookies persist, so an NSE cookie-priming GET on ``www.nseindia.com/``
    carries into the next call).
    """

    timeout_s: float = DEFAULT_TIMEOUT_S
    allow_yahoo: bool = False
    transport: Any = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    _states: dict[str, _HostState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self.timeout_s, follow_redirects=True, transport=self.transport,
                                        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4))
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def _state(self, host: str) -> _HostState:
        return self._states.setdefault(host, _HostState())

    def _pace(self, host: str) -> None:
        gap = YAHOO_GAP_S if host in YAHOO_HOSTS else MIN_GAP_S
        with self._lock:
            st = self._state(host)
            now = self.clock()
            if st.backoff_until > now:
                raise UpstreamError(503, f"{host}: backing off for {int(st.backoff_until - now)} s", upstream=host,
                                    retry_after_s=st.backoff_until - now)
            wait = st.last_at + gap - now
            if wait > 0:
                self.sleep(wait)
            st.last_at = self.clock()

    def _note_status(self, host: str, status: int) -> None:
        with self._lock:
            st = self._state(host)
            if host in NSE_HOSTS and status in (403, 429):
                st.strikes += 1
                st.backoff_until = self.clock() + NSE_BLOCK_S
                logger.warning("http.nse_blocked", host=host, status=status, backoff_s=NSE_BLOCK_S, strikes=st.strikes)
            elif status == 429:
                minutes = YAHOO_BACKOFF_MIN[min(st.strikes, len(YAHOO_BACKOFF_MIN) - 1)]
                st.strikes += 1
                st.backoff_until = self.clock() + minutes * 60
                logger.warning("http.throttled", host=host, backoff_min=minutes, strikes=st.strikes)
            elif status < 400:
                st.strikes = 0

    def blocked_until(self, host: str) -> float:
        with self._lock:
            return self._state(host).backoff_until

    def _headers(self, host: str, headers: Mapping[str, str] | None) -> dict[str, str]:
        ua = user_agent_for(host)
        out = {"Accept": "*/*"} if ua is None else {"User-Agent": ua, "Accept": "*/*"}
        if headers:
            out.update(headers)
        return out

    def get(self, url: str, *, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None,
            timeout_s: float | None = None) -> httpx.Response:
        host = assert_allowed(url, allow_yahoo=self.allow_yahoo)
        if host in INTERNAL_HOSTS:
            return self._http().get(url, params=dict(params) if params else None, timeout=timeout_s or self.timeout_s)
        self._pace(host)
        t0 = self.clock()
        resp = self._http().get(url, params=dict(params) if params else None, headers=self._headers(host, headers),
                                timeout=timeout_s or self.timeout_s)
        self._note_status(host, resp.status_code)
        logger.info("http.get", host=host, status=resp.status_code, ms=int((self.clock() - t0) * 1000), bytes=len(resp.content))
        return resp

    def get_if_modified(self, url: str, *, last_modified: str | None, headers: Mapping[str, str] | None = None,
                        timeout_s: float | None = None) -> httpx.Response:
        """GET with ``If-Modified-Since`` (NSE re-publishes the bhavcopy at 22:05; a 304 costs no body)."""
        hdrs = dict(headers or {})
        if last_modified:
            hdrs["If-Modified-Since"] = last_modified
        return self.get(url, headers=hdrs, timeout_s=timeout_s)
