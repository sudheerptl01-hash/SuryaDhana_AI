"""
Production-grade Yahoo Finance v8 Chart API provider.

Bypasses yfinance's broken crumb/cookie handling by calling the v8 chart endpoint
directly with a persistent session. Tested inside Docker on NSE tickers.
"""
from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import requests

from shared.logging import get_logger
from shared.models import OHLCV, OHLCVBatch

logger = get_logger(__name__)

NSE_SUFFIX = ".NS"

_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )
    return _SESSION


def _to_nse(ticker: str) -> str:
    return ticker if ticker.endswith(NSE_SUFFIX) else f"{ticker}{NSE_SUFFIX}"


def _fetch_ticker(
    yf_ticker: str,
    start_ts: int,
    end_ts: int,
    retries: int = 3,
) -> Optional[dict]:
    session = _get_session()
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_ticker}"
    params = {"interval": "1d", "period1": start_ts, "period2": end_ts}

    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=20)

            if r.status_code == 429:
                wait = 30 + random.uniform(5, 15) * (attempt + 1)
                logger.warning("Rate-limited", ticker=yf_ticker, wait_s=round(wait, 1))
                time.sleep(wait)
                continue

            if r.status_code != 200:
                logger.warning(
                    "Non-200 response", ticker=yf_ticker, status=r.status_code
                )
                return None

            data = r.json()
            result = data.get("chart", {}).get("result")
            if not result:
                err = data.get("chart", {}).get("error")
                logger.warning("No chart result", ticker=yf_ticker, error=err)
                return None

            return result[0]

        except requests.exceptions.Timeout:
            logger.warning("Timeout", ticker=yf_ticker, attempt=attempt + 1)
            time.sleep(5 * (attempt + 1))
        except Exception as exc:
            logger.error("Fetch error", ticker=yf_ticker, error=str(exc))
            if attempt < retries - 1:
                time.sleep(3)

    return None


def _parse_chart(ticker: str, chart: dict) -> OHLCVBatch:
    timestamps = chart.get("timestamp", [])
    quote = chart.get("indicators", {}).get("quote", [{}])[0]
    adj = chart.get("indicators", {}).get("adjclose", [{}])
    adjclose_list = adj[0].get("adjclose", []) if adj else []

    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])

    records: list[OHLCV] = []
    for i, ts in enumerate(timestamps):
        try:
            row_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            o = opens[i] if i < len(opens) else None
            h = highs[i] if i < len(highs) else None
            lo = lows[i] if i < len(lows) else None
            c = closes[i] if i < len(closes) else None
            v = volumes[i] if i < len(volumes) else None
            ac = adjclose_list[i] if i < len(adjclose_list) else c

            if None in (o, h, lo, c) or c != c:  # NaN guard
                continue

            # Yahoo occasionally reports open/close a few ticks outside [low, high]
            # (rounding). Rejecting those drops a real trading day, so repair small
            # gaps; large ones are left for the OHLCV validator to reject.
            if min(o, h, lo, c) > 0:
                hi_needed, lo_needed = max(o, c, h), min(o, c, lo)
                if hi_needed / h - 1 <= 0.02 and 1 - lo_needed / lo <= 0.02:
                    h, lo = hi_needed, lo_needed

            records.append(
                OHLCV(
                    ticker=ticker,
                    date=row_date,
                    open=float(o),
                    high=float(h),
                    low=float(lo),
                    close=float(c),
                    volume=int(v) if v is not None else 0,
                    adjusted_close=float(ac) if ac is not None else float(c),
                )
            )
        except Exception as exc:
            logger.warning("Skipping bad row", ticker=ticker, index=i, error=str(exc))

    return OHLCVBatch(ticker=ticker, records=records, source="yahoo_v8")


class DirectYahooProvider:
    """
    Fetches NSE OHLCV data via Yahoo Finance v8 chart API.

    Uses a persistent session with proper browser headers to avoid rate limiting.
    Throttles requests with per-ticker delay + jitter to stay within Yahoo limits.
    """

    def __init__(self, per_ticker_delay: float = 0.5, jitter: float = 0.3):
        self._delay = per_ticker_delay
        self._jitter = jitter

    def _sleep(self) -> None:
        time.sleep(self._delay + random.uniform(0, self._jitter))

    def fetch_historical(
        self,
        tickers: list[str],
        years: int = 5,
        end_date: date | None = None,
    ) -> dict[str, OHLCVBatch]:
        end = end_date or date.today()
        start = end - timedelta(days=years * 365 + 10)
        end_ts = int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        start_ts = int(datetime(start.year, start.month, start.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())

        logger.info("Fetching historical", tickers=len(tickers), start=start, end=end, years=years)

        results: dict[str, OHLCVBatch] = {}
        for i, ticker in enumerate(tickers):
            yf_ticker = _to_nse(ticker)
            chart = _fetch_ticker(yf_ticker, start_ts, end_ts)
            if chart:
                batch = _parse_chart(ticker, chart)
                results[ticker] = batch
                logger.info("Fetched", ticker=ticker, rows=len(batch.records))
            else:
                results[ticker] = OHLCVBatch(ticker=ticker, records=[], source="yahoo_v8")
                logger.warning("No data", ticker=ticker)

            if i < len(tickers) - 1:
                self._sleep()

        return results

    def fetch_single(
        self,
        ticker: str,
        start: date,
        end: date | None = None,
    ) -> OHLCVBatch:
        end = end or date.today()
        end_ts = int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        start_ts = int(datetime(start.year, start.month, start.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())

        yf_ticker = _to_nse(ticker)
        chart = _fetch_ticker(yf_ticker, start_ts, end_ts)
        if chart:
            return _parse_chart(ticker, chart)
        return OHLCVBatch(ticker=ticker, records=[], source="yahoo_v8")

    def fetch_index(self, symbol: str, start: date, end: date | None = None) -> OHLCVBatch:
        """Fetch an index by its raw Yahoo symbol (e.g. ``^NSEI``) — no ``.NS`` suffix."""
        end = end or date.today()
        end_ts = int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        start_ts = int(datetime(start.year, start.month, start.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        chart = _fetch_ticker(symbol, start_ts, end_ts)
        if chart:
            return _parse_chart(symbol, chart)
        return OHLCVBatch(ticker=symbol, records=[], source="yahoo_v8")

    def to_dataframe(self, batch: OHLCVBatch) -> "pd.DataFrame":
        import pandas as pd

        if not batch.records:
            return pd.DataFrame()
        rows = [r.model_dump() for r in batch.records]
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
