#!/usr/bin/env python3
"""
Bulk download OHLCV data from yfinance for NSE 1000 & Midcap 500 universe.
Stores in DuckDB for efficient time-series operations.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import duckdb
from typing import Dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.logging import configure_logging, get_logger
from shared.config import get_settings

logger = get_logger(__name__)
configure_logging("download_bulk_ohlcv", "INFO")


def load_universe_tickers() -> list[str]:
    """Load tickers from NSE universe CSV."""
    try:
        df = pd.read_csv("data/NSE_1000_MIDCAP_500.csv")
        tickers = df["ticker"].tolist()
        logger.info(f"Loaded {len(tickers)} tickers from universe CSV")
        return tickers
    except Exception as e:
        logger.error(f"Failed to load universe CSV: {e}")
        return []


def download_batch(tickers: list[str], years: int = 5) -> Dict[str, pd.DataFrame]:
    """Download historical data using yfinance bulk API."""
    logger.info(f"Downloading {years} years OHLCV for {len(tickers)} tickers...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365)

    results = {}
    errors = []

    # Download in batches to avoid rate limits
    batch_size = 20
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        logger.info(f"Batch {i//batch_size + 1}: downloading {len(batch)} tickers...")

        # Format tickers for yfinance (NSE format)
        yf_tickers = [f"{t}.NS" for t in batch]

        try:
            # Download using yfinance
            df_batch = yf.download(
                yf_tickers,
                start=start_date,
                end=end_date,
                progress=False,
                interval="1d",
                ignore_tz=True,
            )

            if df_batch.empty:
                logger.warning(f"Batch {i//batch_size + 1}: No data returned")
                continue

            # Process each ticker's data
            for j, ticker in enumerate(batch):
                try:
                    # Extract ticker data from batch result
                    if len(batch) == 1:
                        # Single ticker
                        ticker_data = df_batch.reset_index()
                    else:
                        # Multiple tickers
                        ticker_data = df_batch[[("Open", f"{ticker}.NS"), ("High", f"{ticker}.NS"),
                                               ("Low", f"{ticker}.NS"), ("Close", f"{ticker}.NS"),
                                               ("Volume", f"{ticker}.NS")]].copy()

                        ticker_data.columns = ["Open", "High", "Low", "Close", "Volume"]
                        ticker_data = ticker_data.reset_index()
                        ticker_data = ticker_data[ticker_data["Close"].notna()]

                    if ticker_data.empty:
                        logger.warning(f"{ticker}: No data after processing")
                        continue

                    # Standardize columns
                    ticker_data = ticker_data.rename(columns={
                        "Open": "open",
                        "High": "high",
                        "Low": "low",
                        "Close": "close",
                        "Volume": "volume",
                        "Date": "timestamp",
                    })

                    ticker_data["ticker"] = ticker
                    ticker_data["source"] = "yfinance"

                    # Keep only required columns
                    required_cols = ["ticker", "timestamp", "open", "high", "low", "close", "volume", "source"]
                    ticker_data = ticker_data[[c for c in required_cols if c in ticker_data.columns]]

                    results[ticker] = ticker_data

                except Exception as e:
                    logger.warning(f"Failed to process {ticker}: {e}")
                    errors.append(f"{ticker}: {str(e)}")

        except Exception as e:
            logger.error(f"Batch download failed: {e}")
            for ticker in batch:
                errors.append(f"{ticker}: batch error")

    logger.info(f"Downloaded: {len(results)} tickers. Errors: {len(errors)}")
    return results


def save_to_duckdb(data: dict[str, pd.DataFrame], db_path: str = "data/market.duckdb") -> int:
    """Save OHLCV data to DuckDB."""
    logger.info(f"Storing {len(data)} tickers in DuckDB ({db_path})...")

    conn = duckdb.connect(db_path)
    total_rows = 0

    # Create main OHLCV table
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                ticker VARCHAR,
                timestamp DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                source VARCHAR,
                PRIMARY KEY (ticker, timestamp)
            )
        """)

        for ticker, df in data.items():
            if df.empty:
                continue

            try:
                # Ensure proper data types
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df["open"] = pd.to_numeric(df["open"], errors="coerce")
                df["high"] = pd.to_numeric(df["high"], errors="coerce")
                df["low"] = pd.to_numeric(df["low"], errors="coerce")
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

                # Remove NaNs
                df = df.dropna(subset=["close"])

                if df.empty:
                    logger.warning(f"{ticker}: No valid OHLCV data after cleaning")
                    continue

                # Upsert into main table
                conn.execute("INSERT OR REPLACE INTO ohlcv SELECT * FROM df")
                total_rows += len(df)
                logger.info(f"{ticker}: {len(df)} rows")

            except Exception as e:
                logger.warning(f"Failed to save {ticker}: {e}")

        logger.info(f"Total rows saved: {total_rows}")

        # Create index for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker ON ohlcv(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(timestamp)")

    finally:
        conn.close()

    logger.info(f"Stored {total_rows} OHLCV rows in {db_path}")
    return total_rows


def main():
    """Main execution."""
    logger.info("=" * 80)
    logger.info("Bulk OHLCV Download from yfinance")
    logger.info("=" * 80)

    # Step 1: Load universe
    logger.info("\n[Step 1] Loading stock universe...")
    tickers = load_universe_tickers()
    if not tickers:
        logger.error("Failed to load tickers. Exiting.")
        return

    # Step 2: Download data
    logger.info(f"\n[Step 2] Downloading historical data...")
    data = download_batch(tickers, years=5)

    if not data:
        logger.error("No data downloaded. Exiting.")
        return

    # Step 3: Save to DuckDB
    logger.info(f"\n[Step 3] Saving to DuckDB...")
    total = save_to_duckdb(data)

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Downloaded: {len(data)} tickers")
    logger.info(f"Total rows: {total}")
    logger.info(f"Database: data/market.duckdb")
    logger.info("\nNext: Start the system with docker compose")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
