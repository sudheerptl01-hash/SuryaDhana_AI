from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.logging import get_logger
from shared.models import OHLCV, OHLCVBatch

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
    def get_intraday_ohlcv(self, ticker: str, interval: str = "5minute") -> OHLCVBatch: ...

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
        retry=retry_if_exception_type(RuntimeError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_live_quote(self, ticker: str) -> dict[str, Any]:
        self._require_connection()
        stock_code = self._resolve_isec_code(ticker)
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
        retry=retry_if_exception_type(RuntimeError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_intraday_ohlcv(self, ticker: str, interval: str = "5minute") -> OHLCVBatch:
        """Fetch today's intraday bars using Breeze v2."""
        self._require_connection()
        stock_code = self._resolve_isec_code(ticker)
        today = date.today()
        response = self._breeze.get_historical_data_v2(
            interval=interval,
            from_date=_to_icici_dt(today, eod=False),
            to_date=_to_icici_dt(today, eod=True),
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
        retry=retry_if_exception_type(RuntimeError),
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
        return True

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
