from __future__ import annotations

import csv
import io
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from shared.breeze_budget import BudgetExceeded, ledger
from shared.logging import get_logger
from shared.models import OHLCV, OHLCVBatch


def _retry_real_errors(exc: BaseException) -> bool:
    """Retry a transient RuntimeError, but NEVER a budget refusal.

    F9-03: these calls were invisible to the Breeze ledger, and metering them created a trap — the ledger's
    ``BudgetExceeded`` IS a RuntimeError, so the plain ``retry_if_exception_type(RuntimeError)`` these methods
    used would have turned one refusal into three attempts with exponential backoff, each one asking the ledger
    again. A refusal is a decision, not a transient fault: fail it immediately and let the caller pause.
    """
    return isinstance(exc, RuntimeError) and not isinstance(exc, BudgetExceeded)

logger = get_logger(__name__)

# ICICI Breeze v2 daily data: up to 1 year per request
_MAX_CHUNK_DAYS = 365

# Market session times (IST → UTC offset doesn't matter here; ICICI accepts IST-aligned strings)
_MARKET_OPEN = "T09:15:00.000Z"
_MARKET_CLOSE = "T15:30:00.000Z"


def _to_icici_dt(d: date, eod: bool = False) -> str:
    """Format a date as the ICICI API datetime string: 'YYYY-MM-DDTHH:MM:SS.000Z'."""
    suffix = _MARKET_CLOSE if eod else _MARKET_OPEN
    return f"{d.isoformat()}{suffix}"


def _parse_icici_dt(raw: str) -> date:
    """Parse ICICI response datetime strings (v2 returns 'YYYY-MM-DD HH:MM:SS')."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.000Z", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unparseable ICICI datetime: {raw!r}")


WS_TOKEN_PREFIX = "4.1!"            # NSE cash / index exchange-quote stream (what every tick's `symbol` carries)
WS_EQ_SERIES = ("EQ", "BE")         # the tradable cash rows; EQ wins when a symbol has both
NSE_MASTER_FILE = "NSEScripMaster.txt"


def parse_nse_master_tokens(rows: Iterable[list[str]]) -> tuple[dict[str, str], dict[str, str]]:
    """ICICI's NSEScripMaster.txt rows → (equities, indices) for the websocket.

    equities: NSE symbol (the master's last column, ExchangeCode) → Token, from EQ / BE rows only, EQ preferred. Keyed
    by the NSE symbol, never by ShortName (the isec code): get_names also matches ShortName and returns every series'
    token ('1333 1462 17320' for HDFCBANK because of its W3 warrant rows), so it is only a fallback.
    indices: upper-cased index name → the exact Token (Series '0' rows, where the Token IS the name: 'NIFTY 50',
    'NIFTY BANK', 'INDIA VIX', 'Nifty CPSE'). A tick for HDFCBANK arrives keyed '4.1!1333', NIFTY as '4.1!NIFTY 50'."""
    eq: dict[str, str] = {}
    eq_series: dict[str, str] = {}
    idx: dict[str, str] = {}
    for raw in rows:
        if len(raw) < 4:
            continue
        cols = [c.strip().strip('"').strip() for c in raw]
        token, series, exch = cols[0], cols[2].upper(), cols[-1].upper()
        if not token or token.lower() == "token" or not token.strip("0"):
            continue                                        # header row; '0' / '00' are placeholder tokens of dead rows
        if series == "0":
            idx[token.upper()] = token
        elif series in WS_EQ_SERIES and exch:
            if exch not in eq or (eq_series.get(exch) != "EQ" and series == "EQ"):
                eq[exch], eq_series[exch] = token, series
    return eq, idx


def _date_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split a date range into ≤365-day chunks (v2 daily data limit)."""
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=_MAX_CHUNK_DAYS - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


class LiveDataProvider(ABC):
    """Interface contract for live market data providers."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def get_live_quote(self, ticker: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_intraday_ohlcv(self, ticker: str, interval: str = "5minute", day: "date | None" = None) -> OHLCVBatch: ...

    @abstractmethod
    def is_connected(self) -> bool: ...


class ICICIBreezeProvider(LiveDataProvider):
    """
    ICICI Direct Breeze API provider — uses get_historical_data_v2 (breeze-connect 1.0.69+).

    Breeze v2 endpoint: https://breezeapi.icicidirect.com/api/v2/historicalcharts
    Supported intervals: 1second | 1minute | 5minute | 30minute | 1day
    Supported exchanges: NSE | BSE | NFO | NDX | MCX | BFO

    Credentials required (env vars):
        ICICI_API_KEY       — from https://api.icicidirect.com/
        ICICI_API_SECRET    — API secret
        ICICI_SESSION_TOKEN — refreshed daily via the ICICI login flow

    Session token refresh flow:
        1. Run: scripts/icici_session_helper.py
        2. Open the printed URL in a browser and log in
        3. Copy the session_token query param from the redirect URL
        4. Update ICICI_SESSION_TOKEN in .env and restart the service
    """

    def __init__(self, api_key: str, api_secret: str, session_token: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._session_token = session_token
        self._breeze: Any = None
        self._connected = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def connect(self, timeout: int = 15) -> None:
        """
        Connect to ICICI Breeze. Patches the requests Session inside breeze_connect
        to enforce a connection timeout (default 15s) so the script never hangs
        waiting for a dead API endpoint.
        """
        if not self._api_key:
            logger.warning("ICICI API key not configured — live provider in stub mode")
            return
        try:
            import requests
            try:      # breeze_connect downloads ICICI's security master at import, with no timeout: use the cache
                from shared.breeze_cache import install as _breeze_cache_install
                _breeze_cache_install()
            except Exception:  # noqa: BLE001
                pass
            from breeze_connect import BreezeConnect  # type: ignore[import]

            # Monkey-patch the global requests.get used by breeze_connect
            # to inject a connect timeout before generate_session is called.
            _orig_get = requests.get
            def _get_with_timeout(url, **kwargs):
                kwargs.setdefault("timeout", timeout)
                return _orig_get(url, **kwargs)
            requests.get = _get_with_timeout

            try:
                self._breeze = BreezeConnect(api_key=self._api_key)
                self._breeze.generate_session(
                    api_secret=self._api_secret,
                    session_token=self._session_token,
                )
            finally:
                requests.get = _orig_get  # always restore

            self._connected = True
            self._code_cache: dict[str, str] = {}
            logger.info("ICICI Breeze v2 connected", api_key_prefix=self._api_key[:6])
        except Exception as exc:
            logger.error("ICICI Breeze connection failed", error=str(exc))
            raise

    def disconnect(self) -> None:
        self._connected = False
        self._breeze = None
        logger.info("ICICI Breeze disconnected")

    def is_connected(self) -> bool:
        return self._connected

    # ── Live quote ─────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception(_retry_real_errors),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_live_quote(self, ticker: str) -> dict[str, Any]:
        self._require_connection()
        stock_code = self._resolve_isec_code(ticker)
        # F9-03: metered. This is the live-quote path the NIFTY and watchlist pollers drive every 15 s —
        # the busiest Breeze consumer in the stack, and until now the ledger (and therefore the budget panel
        # and the 100/min · 5,000/day guard) could not see a single one of its calls.
        with ledger().guard("data-service.live_quote", "get_quotes"):
            response = self._breeze.get_quotes(
                stock_code=stock_code,
                exchange_code="NSE",
                product_type="cash",
                right="others",
                strike_price="0",
            )
        if response.get("Status") != 200:
            raise RuntimeError(f"ICICI quote error for {ticker}: {response}")
        return response.get("Success", [{}])[0]

    # ── Intraday OHLCV (v2) ────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception(_retry_real_errors),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_intraday_ohlcv(self, ticker: str, interval: str = "5minute", day: "date | None" = None) -> OHLCVBatch:
        """Fetch intraday bars for `day` (defaults to today) using Breeze v2."""
        self._require_connection()
        stock_code = self._resolve_isec_code(ticker)
        target = day or date.today()
        with ledger().guard("data-service.intraday", "get_historical_data_v2"):   # F9-03
            response = self._breeze.get_historical_data_v2(
                interval=interval,
                from_date=_to_icici_dt(target, eod=False),
                to_date=_to_icici_dt(target, eod=True),
                stock_code=stock_code,
                exchange_code="NSE",
                product_type="cash",
            )
        if response.get("Status") != 200:
            raise RuntimeError(f"ICICI intraday v2 error for {ticker}: {response}")

        return self._parse_ohlcv_response(ticker, response)

    # ── Daily historical OHLCV (v2) ────────────────────────────────────────────

    def get_daily_ohlcv_v2(
        self,
        ticker: str,
        start: date,
        end: date,
        exchange_code: str = "NSE",
    ) -> OHLCVBatch:
        """
        Fetch daily (1day interval) OHLCV bars via Breeze v2, with automatic
        date chunking (max 365 days per API call).

        Args:
            ticker:        NSE ticker, e.g. 'RELIANCE.NS' or 'RELIANCE'
            start:         Inclusive start date
            end:           Inclusive end date (use date.today() for latest)
            exchange_code: 'NSE' or 'BSE' (v2 supports both)
        """
        self._require_connection()
        stock_code = self._resolve_isec_code(ticker)
        all_records: list[OHLCV] = []
        chunks = _date_chunks(start, end)

        logger.info(
            "ICICI daily fetch started",
            ticker=ticker,
            isec_code=stock_code,
            start=str(start),
            end=str(end),
            chunks=len(chunks),
        )

        for chunk_start, chunk_end in chunks:
            records = self._fetch_daily_chunk(ticker, stock_code, chunk_start, chunk_end, exchange_code)
            all_records.extend(records)
            logger.debug(
                "ICICI chunk fetched",
                ticker=ticker,
                chunk_start=str(chunk_start),
                chunk_end=str(chunk_end),
                rows=len(records),
            )

        logger.info("ICICI daily fetch complete", ticker=ticker, total_rows=len(all_records))
        return OHLCVBatch(ticker=ticker, records=all_records, source="icici_breeze_v2")

    @retry(
        retry=retry_if_exception(_retry_real_errors),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=3, max=15),
        reraise=True,
    )
    def _fetch_daily_chunk(
        self,
        ticker: str,
        stock_code: str,
        chunk_start: date,
        chunk_end: date,
        exchange_code: str,
    ) -> list[OHLCV]:
        # F9-03: a history backfill walks this in chunks, so it is the one path that can empty the daily
        # quota in minutes — exactly what the ledger's per-day cap exists to stop.
        with ledger().guard("data-service.history", "get_historical_data_v2"):
            response = self._breeze.get_historical_data_v2(
                interval="1day",
                from_date=_to_icici_dt(chunk_start, eod=False),
                to_date=_to_icici_dt(chunk_end, eod=True),
                stock_code=stock_code,
                exchange_code=exchange_code,
                product_type="cash",
            )
        if response.get("Status") != 200:
            raise RuntimeError(
                f"ICICI daily v2 chunk error {ticker} "
                f"[{chunk_start}→{chunk_end}]: {response}"
            )
        return self._parse_ohlcv_response(ticker, response).records

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _parse_ohlcv_response(self, ticker: str, response: dict) -> OHLCVBatch:
        """Convert a Breeze v2 API response into an OHLCVBatch."""
        records: list[OHLCV] = []
        for bar in response.get("Success") or []:
            try:
                records.append(
                    OHLCV(
                        ticker=ticker,
                        date=_parse_icici_dt(bar["datetime"]),
                        open=float(bar["open"]),
                        high=float(bar["high"]),
                        low=float(bar["low"]),
                        close=float(bar["close"]),
                        volume=int(float(bar.get("volume", 0))),
                        adjusted_close=float(bar["close"]),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Skipping malformed ICICI bar",
                    ticker=ticker,
                    bar=bar,
                    error=str(exc),
                )
        return OHLCVBatch(ticker=ticker, records=records, source="icici_breeze_v2")

    def _resolve_isec_code(self, ticker: str) -> str:
        """
        Resolve NSE ticker → ICICI isec_stock_code.
        ICICI v2 requires isec_stock_code, not the NSE exchange code.
        Results are cached in memory for the session lifetime.
        """
        raw = ticker.replace(".NS", "").replace(".BO", "")
        if raw in self._code_cache:
            return self._code_cache[raw]
        try:
            info = self._breeze.get_names(exchange_code="NSE", stock_code=raw)
            isec = info.get("isec_stock_code") or raw
            self._code_cache[raw] = isec
            if isec != raw:
                logger.debug("Resolved isec_code", nse=raw, isec=isec)
            return isec
        except Exception as exc:
            logger.warning("isec_code lookup failed, using raw ticker", ticker=raw, error=str(exc))
            self._code_cache[raw] = raw
            return raw

    # ── Websocket token resolution (live ticks) ────────────────────────────────

    def _nse_master_rows(self) -> Iterator[list[str]]:
        """The NSE security master breeze_connect already holds in memory (module-global `zip`, loaded at import from the
        shared.breeze_cache copy), else the cached archive itself, read-only. Never imports breeze_connect (its import
        downloads the master) and never opens a socket."""
        import zipfile
        bc = sys.modules.get("breeze_connect.breeze_connect")
        zf = getattr(bc, "zip", None) if bc is not None else None
        if zf is not None and NSE_MASTER_FILE in zf.namelist():
            with zf.open(NSE_MASTER_FILE) as fh:
                yield from csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
            return
        from shared.breeze_cache import CACHE
        if CACHE.exists() and zipfile.is_zipfile(CACHE):
            with zipfile.ZipFile(CACHE) as z, z.open(NSE_MASTER_FILE) as fh:
                yield from csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))

    def ws_token_maps(self) -> tuple[dict[str, str], dict[str, str]]:
        """(NSE symbol → Token, upper index name → Token), parsed once per provider from the security master."""
        lock = self.__dict__.setdefault("_ws_lock", threading.Lock())
        with lock:
            maps = self.__dict__.get("_ws_maps")
            if maps is None or not (maps[0] or maps[1]):
                try:
                    maps = parse_nse_master_tokens(self._nse_master_rows())
                except Exception as exc:  # noqa: BLE001 — a missing master leaves only the get_names fallback
                    logger.warning("security master unreadable for websocket tokens", error=str(exc)[:160])
                    maps = ({}, {})
                self.__dict__["_ws_maps"] = maps
            return maps

    def _resolve_ws_token(self, ticker: str) -> str:
        """NSE symbol or index name → the websocket token its ticks are keyed by ('HDFCBANK' → '4.1!1333',
        'NIFTY 50' → '4.1!NIFTY 50'). The master's EQ/BE row first; then get_names' isec_token_level1, FIRST token only
        ('4.1!1333 1462 17320' → '4.1!1333'). Raises LookupError when neither knows the name (cached, so a bad name
        never re-parses the master through pandas)."""
        raw = ticker.strip().upper().replace(".NS", "").replace(".BO", "")
        eq, idx = self.ws_token_maps()
        if raw in eq:
            return WS_TOKEN_PREFIX + eq[raw]
        if raw in idx:
            return WS_TOKEN_PREFIX + idx[raw]
        misses: dict[str, str] = self.__dict__.setdefault("_ws_misses", {})
        hits: dict[str, str] = self.__dict__.setdefault("_ws_hits", {})
        if raw in hits:
            return hits[raw]
        if raw in misses:
            raise LookupError(misses[raw])
        try:
            info = self._breeze.get_names(exchange_code="NSE", stock_code=raw) if self._breeze is not None else None
            level1 = str((info or {}).get("isec_token_level1") or "")
            exch = str((info or {}).get("exchange_stock_code") or "").strip().upper()
        except Exception as exc:  # noqa: BLE001 — the SDK raises on unknown names
            level1, exch = "", ""
            logger.debug("get_names failed for websocket token", ticker=raw, error=str(exc)[:120])
        first = level1.split()[0] if level1.split() else ""
        same_name = not exch or exch.split()[0] == raw      # get_names also matches ShortName: another company's isec code
        if first.startswith(WS_TOKEN_PREFIX) and len(first) > len(WS_TOKEN_PREFIX) and same_name:
            hits[raw] = first
            return first
        misses[raw] = f"no websocket token for {raw}"
        raise LookupError(misses[raw])

    def _require_connection(self) -> None:
        if not self._connected:
            raise RuntimeError(
                "ICICIBreezeProvider is not connected. Call connect() first."
            )


# ── Stub provider (dev / no credentials) ──────────────────────────────────────

class StubLiveProvider(LiveDataProvider):
    """No-op provider used in development when ICICI credentials are not configured."""

    def connect(self) -> None:
        logger.info("StubLiveProvider: no-op connect")

    def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        # No broker behind the stub: report disconnected so the UI shows the truth and
        # the live-quote pollers idle instead of fetching empty quotes every 5 s.
        return False

    def get_live_quote(self, ticker: str) -> dict[str, Any]:
        logger.warning("StubLiveProvider.get_live_quote — returning empty dict", ticker=ticker)
        return {}

    def get_intraday_ohlcv(self, ticker: str, interval: str = "5minute") -> OHLCVBatch:
        logger.warning("StubLiveProvider.get_intraday_ohlcv — returning empty batch", ticker=ticker)
        return OHLCVBatch(ticker=ticker, records=[], source="stub")


# ── Factory ────────────────────────────────────────────────────────────────────

def build_live_provider(api_key: str, api_secret: str, session_token: str) -> LiveDataProvider:
    """Returns real ICICIBreezeProvider when credentials are set, else StubLiveProvider."""
    if api_key and api_secret and session_token:
        return ICICIBreezeProvider(api_key, api_secret, session_token)
    logger.warning("ICICI credentials missing — using StubLiveProvider")
    return StubLiveProvider()
