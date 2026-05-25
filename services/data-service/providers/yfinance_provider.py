from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from shared.logging import get_logger
from shared.models import OHLCV, OHLCVBatch

logger = get_logger(__name__)

NSE_SUFFIX = ".NS"


def _to_nse_ticker(ticker: str) -> str:
    """Ensures ticker has .NS suffix for yfinance NSE queries."""
    return ticker if ticker.endswith(NSE_SUFFIX) else f"{ticker}{NSE_SUFFIX}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download_raw(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    yf_tickers = [_to_nse_ticker(t) for t in tickers]
    df = yf.download(
        tickers=yf_tickers,
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    return df


class YFinanceProvider:
    """Downloads historical OHLCV data for NSE stocks via yfinance."""

    def fetch_historical(
        self,
        tickers: list[str],
        years: int = 5,
        end_date: date | None = None,
    ) -> dict[str, OHLCVBatch]:
        end = end_date or date.today()
        start = end - timedelta(days=years * 365 + 10)  # slight buffer for weekends/holidays

        logger.info("Fetching historical data", tickers=len(tickers), start=start, end=end)

        try:
            raw = _download_raw(tickers, start, end)
        except Exception as exc:
            logger.error("yfinance download failed", error=str(exc))
            raise

        return self._parse_multi(raw, tickers)

    def fetch_single(
        self,
        ticker: str,
        start: date,
        end: date | None = None,
    ) -> OHLCVBatch:
        end = end or date.today()
        raw = _download_raw([ticker], start, end)
        batches = self._parse_multi(raw, [ticker])
        return batches.get(ticker, OHLCVBatch(ticker=ticker, records=[], source="yfinance"))

    def _parse_multi(self, raw: pd.DataFrame, tickers: list[str]) -> dict[str, OHLCVBatch]:
        results: dict[str, OHLCVBatch] = {}

        if raw.empty:
            logger.warning("yfinance returned empty DataFrame")
            return results

        # yfinance returns MultiIndex columns when multiple tickers requested
        is_multi = isinstance(raw.columns, pd.MultiIndex)

        for ticker in tickers:
            try:
                if is_multi:
                    yf_ticker = _to_nse_ticker(ticker)
                    df = raw.xs(yf_ticker, axis=1, level=1) if yf_ticker in raw.columns.get_level_values(1) else pd.DataFrame()
                else:
                    df = raw

                if df.empty:
                    logger.warning("No data for ticker", ticker=ticker)
                    results[ticker] = OHLCVBatch(ticker=ticker, records=[], source="yfinance")
                    continue

                df = df.dropna(subset=["Close"])
                df.index = pd.to_datetime(df.index).date

                records = []
                for row_date, row in df.iterrows():
                    try:
                        records.append(
                            OHLCV(
                                ticker=ticker,
                                date=row_date,
                                open=float(row["Open"]),
                                high=float(row["High"]),
                                low=float(row["Low"]),
                                close=float(row["Close"]),
                                volume=int(row["Volume"]),
                                adjusted_close=float(row["Close"]),  # auto_adjust=True → Close is already adjusted
                            )
                        )
                    except Exception as exc:
                        logger.warning("Skipping bad row", ticker=ticker, date=str(row_date), error=str(exc))

                results[ticker] = OHLCVBatch(ticker=ticker, records=records, source="yfinance")
                logger.info("Fetched OHLCV", ticker=ticker, rows=len(records))

            except Exception as exc:
                logger.error("Failed to parse ticker", ticker=ticker, error=str(exc))
                results[ticker] = OHLCVBatch(ticker=ticker, records=[], source="yfinance")

        return results

    def to_dataframe(self, batch: OHLCVBatch) -> pd.DataFrame:
        if not batch.records:
            return pd.DataFrame()
        rows = [r.model_dump() for r in batch.records]
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
