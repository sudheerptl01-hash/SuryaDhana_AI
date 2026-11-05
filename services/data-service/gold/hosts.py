"""Fetch etiquette for the gold package (PLAN §c.6): the host allowlist, per-host pacing, the UA rules and
the 429 back-off. Every HTTP or FTP request the package makes goes through ``GoldHttp`` / ``ftp_fetch``; a
URL whose host is not allowlisted is refused before any socket opens. Test T8 scans this package statically
for the same hosts, so the two cannot drift apart.

Forbidden by owner decision (never fetched, link-only in the UI): www.cmegroup.com, mcxindia.com, kitco.com,
prices.lbma.org.uk, stooq.com, goldprice.org, investing.com. CME's FTP host is a separate server and allowed.
"""
from __future__ import annotations

import ftplib
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from shared.logging import get_logger

logger = get_logger(__name__)

# ── The allowlist (PLAN §c.6) ──────────────────────────────────────────────────────────────────────────
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "query1.finance.yahoo.com", "query2.finance.yahoo.com",      # app UA only, ≤ 6 chart calls/min
    "publicreporting.cftc.gov", "www.cftc.gov",
    "ftp.cmegroup.com",                                           # FTP, paced 1 file / 2 s
    "home.treasury.gov", "fred.stlouisfed.org",                   # FRED: fredgraph.csv, plain UA
    "api.spdrgoldshares.com", "www.ishares.com",
    "fsapi.gold.org",                                             # gated on owner decision O-1
    "api.imf.org", "cdn.lbma.org.uk", "www.lbma.org.uk",
    "en.sge.com.cn", "www.sge.com.cn", "www.shfe.com.cn",
    "ibjarates.com", "www.rbi.org.in", "directlink.icicidirect.com", "zerodha.com",
    "portal.amfiindia.com", "pib.gov.in", "ocean.nivel.bazg.admin.ch",
    "www.atlantafed.org", "nfs.faireconomy.media", "www.bea.gov",
    "www.matteoiacoviello.com", "thedocs.worldbank.org",
    "api.gold-api.com",                                           # ≤ 1 call / min
    "news.google.com",                                            # existing headline fetcher
})

# Hosts the stack must never contact (terms / bot walls); the static test asserts they are absent too.
FORBIDDEN_HOST_FRAGMENTS: tuple[str, ...] = (
    "www.cmegroup.com", "mcxindia.com", "kitco.com", "prices.lbma.org.uk", "stooq.com", "goldprice.org",
    "investing.com",
)

# Our own services (ui-api for the health snapshot). Never a publisher; accepted by the wrapper, not part of §c.6.
INTERNAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost"})

APP_UA = "Mozilla/5.0 (SuryaDhana-GoldDesk)"          # the only UA Yahoo answers with 200 (G-KITCO / G-MACRO)
PLAIN_UA = "SuryaDhana-GoldDesk/1.0 (+private terminal; contact via repo)"
# FRED stalls (20 s+) on ANY User-Agent that names this app — APP_UA and PLAIN_UA alike (probed 4 Nov 2026: 0.8 s with
# httpx's default UA, ReadTimeout with both of ours; R-DATA §6: 18 series dead since 30 Oct). The library default is sent there.
LIBRARY_UA_HOSTS = {"fred.stlouisfed.org"}
FRED_TIMEOUT_S = 8.0
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 SuryaDhana-GoldDesk")

_YAHOO_HOSTS = {"query1.finance.yahoo.com", "query2.finance.yahoo.com"}
_PLAIN_UA_HOSTS = {"fred.stlouisfed.org", "api.imf.org", "home.treasury.gov", "api.gold-api.com", "nfs.faireconomy.media"}

MIN_GAP_S = 1.2                 # between requests to the same host
YAHOO_GAP_S = 6.0               # one Yahoo call per symbol 6 s apart (PLAN §c.4)
FTP_GAP_S = 2.0                 # CME FTP: 1 file / 2 s
DEFAULT_TIMEOUT_S = 20.0
YAHOO_BACKOFF_MIN = (5, 10, 20)  # minutes, after successive 429s


class HostNotAllowed(RuntimeError):
    """Raised before any network activity when a URL's host is outside the allowlist."""


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def assert_allowed(url: str) -> str:
    host = host_of(url)
    if host not in ALLOWED_HOSTS and host not in INTERNAL_HOSTS:
        raise HostNotAllowed(f"host not in the gold allowlist: {host or '<none>'}")
    return host


def is_allowed(url: str) -> bool:
    return host_of(url) in ALLOWED_HOSTS or host_of(url) in INTERNAL_HOSTS


def user_agent_for(host: str) -> str | None:
    """The UA for a host; ``None`` means "send the HTTP library's default" (FRED refuses every UA that names this app)."""
    if host in LIBRARY_UA_HOSTS:
        return None
    if host in _YAHOO_HOSTS:
        return APP_UA
    if host in _PLAIN_UA_HOSTS:
        return PLAIN_UA
    return BROWSER_UA


@dataclass
class _HostState:
    last_at: float = 0.0
    backoff_until: float = 0.0
    strikes: int = 0


def _base_headers(host: str) -> dict[str, str]:
    ua = user_agent_for(host)
    return {"Accept": "*/*"} if ua is None else {"User-Agent": ua, "Accept": "*/*"}


@dataclass
class GoldHttp:
    """Small paced HTTP client. ``get`` returns an httpx.Response; the allowlist is checked first.

    ``transport`` lets tests inject an ``httpx.MockTransport``; ``sleep`` lets them skip the pacing.
    """

    timeout_s: float = DEFAULT_TIMEOUT_S
    transport: Any = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    _states: dict[str, _HostState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _state(self, host: str) -> _HostState:
        return self._states.setdefault(host, _HostState())

    def _pace(self, host: str) -> None:
        gap = YAHOO_GAP_S if host in _YAHOO_HOSTS else MIN_GAP_S
        with self._lock:
            st = self._state(host)
            now = self.clock()
            if st.backoff_until > now:
                raise RuntimeError(f"{host}: backing off after 429 for {int(st.backoff_until - now)} s")
            wait = st.last_at + gap - now
            if wait > 0:
                self.sleep(wait)
            st.last_at = self.clock()

    def _note_status(self, host: str, status: int) -> None:
        with self._lock:
            st = self._state(host)
            if status == 429:
                minutes = YAHOO_BACKOFF_MIN[min(st.strikes, len(YAHOO_BACKOFF_MIN) - 1)]
                st.strikes += 1
                st.backoff_until = self.clock() + minutes * 60
                logger.warning("gold.http.throttled", host=host, backoff_min=minutes, strikes=st.strikes)
            elif status < 400:
                st.strikes = 0

    def get(self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
            timeout_s: float | None = None) -> Any:
        import httpx

        host = assert_allowed(url)
        self._pace(host)
        hdrs = _base_headers(host)
        if headers:
            hdrs.update(headers)
        t0 = self.clock()
        with httpx.Client(timeout=timeout_s or self.timeout_s, headers=hdrs, follow_redirects=True,
                          transport=self.transport) as client:
            resp = client.get(url, params=params)
        self._note_status(host, resp.status_code)
        logger.info("gold.http.get", host=host, status=resp.status_code, ms=int((self.clock() - t0) * 1000),
                    bytes=len(resp.content))
        return resp

    def post(self, url: str, *, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
             timeout_s: float | None = None) -> Any:
        import httpx

        host = assert_allowed(url)
        self._pace(host)
        hdrs = _base_headers(host)
        if headers:
            hdrs.update(headers)
        with httpx.Client(timeout=timeout_s or self.timeout_s, headers=hdrs, follow_redirects=True,
                          transport=self.transport) as client:
            resp = client.post(url, data=data)
        self._note_status(host, resp.status_code)
        logger.info("gold.http.post", host=host, status=resp.status_code, bytes=len(resp.content))
        return resp

    def stream_to_file(self, url: str, path: str, *, headers: dict[str, str] | None = None, timeout_s: float = 600.0,
                       max_bytes: int = 1_000_000_000) -> int:
        """Download a large body (the 692 MB Swiss customs zip) straight to disk in 1 MB chunks — never into RAM."""
        import httpx

        host = assert_allowed(url)
        self._pace(host)
        hdrs = _base_headers(host)
        if headers:
            hdrs.update(headers)
        size = 0
        with (httpx.Client(timeout=timeout_s, headers=hdrs, follow_redirects=True, transport=self.transport) as client,
              client.stream("GET", url) as resp):
            self._note_status(host, resp.status_code)
            if resp.status_code != 200:
                raise RuntimeError(f"{host}: HTTP {resp.status_code}")
            with open(path, "wb") as fh:
                for chunk in resp.iter_bytes(1_048_576):
                    size += len(chunk)
                    if size > max_bytes:
                        raise RuntimeError(f"{host}: body exceeds {max_bytes} bytes")
                    fh.write(chunk)
        logger.info("gold.http.stream", host=host, bytes=size)
        return size


class _PassiveMixin:
    """``ftplib.FTP`` that tolerates CME's reply to PASV: the server answers ``229 Extended Passive Mode Entered (|||port|)``
    (the EPSV form) where stock ``ftplib`` expects ``227`` and raises ``error_reply`` — the reason every CME job stored
    0 rows until 4 Nov 2026 (R-DATA §6). Either reply form is parsed; the data host is the control connection's peer."""

    if TYPE_CHECKING:  # the attributes ``ftplib.FTP`` provides once mixed in
        af: int
        sock: Any
        trust_server_pasv_ipv4_address: bool

        def sendcmd(self, cmd: str) -> str: ...

    def makepasv(self) -> tuple[str, int]:
        if self.af == socket.AF_INET:
            resp = self.sendcmd("PASV")
            if resp.startswith("229"):
                return ftplib.parse229(resp, self.sock.getpeername())  # type: ignore[attr-defined]
            untrusted_host, port = ftplib.parse227(resp)  # type: ignore[attr-defined]
            host = self.sock.getpeername()[0] if self.trust_server_pasv_ipv4_address is False else untrusted_host
            return host, port
        return ftplib.parse229(self.sendcmd("EPSV"), self.sock.getpeername())  # type: ignore[attr-defined]


class _PassiveFtp(_PassiveMixin, ftplib.FTP):
    """The concrete client (tests subclass it without a socket)."""


def _ftp_client(host: str, timeout_s: float) -> ftplib.FTP:
    """Built at call time from ``ftplib.FTP`` so a test that stubs ``hosts.ftplib.FTP`` never reaches the network."""
    cls = type("_PassiveFtp", (_PassiveMixin, ftplib.FTP), {})
    return cls(host, timeout=timeout_s)


def ftp_fetch(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S, max_bytes: int = 80_000_000,
              sleep: Callable[[float], None] = time.sleep) -> bytes:
    """Anonymous FTP download (CME). Allowlisted host only; paced; bounded by ``max_bytes``."""
    host = assert_allowed(url)
    parts = urlparse(url)
    if parts.scheme != "ftp":
        raise ValueError("ftp_fetch needs an ftp:// URL")
    chunks: list[bytes] = []
    size = 0

    def _sink(block: bytes) -> None:
        nonlocal size
        size += len(block)
        if size > max_bytes:
            raise RuntimeError(f"ftp payload exceeds {max_bytes} bytes")
        chunks.append(block)

    sleep(FTP_GAP_S)                                 # 1 file / 2 s (PLAN §c.4); tests inject ``sleep``
    t0 = time.monotonic()
    with _ftp_client(host, timeout_s) as ftp:
        ftp.login()                                  # anonymous
        ftp.retrbinary(f"RETR {parts.path}", _sink, blocksize=65536)
    logger.info("gold.ftp.get", host=host, path=parts.path, bytes=size, ms=int((time.monotonic() - t0) * 1000))
    return b"".join(chunks)


def ftp_list(url_dir: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[str]:
    """Directory listing (names only) of an allowlisted FTP directory."""
    host = assert_allowed(url_dir)
    parts = urlparse(url_dir)
    with _ftp_client(host, timeout_s) as ftp:
        ftp.login()
        return sorted(ftp.nlst(parts.path))
