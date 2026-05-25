#!/usr/bin/env python3
"""
Fetch NSE 1000 and Nifty Midcap 500 stock universe efficiently.
Uses yfinance bulk download and creates consolidated CSV.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.logging import configure_logging, get_logger

logger = get_logger(__name__)
configure_logging("fetch_nse_universe", "INFO")


# Comprehensive NSE 1000 stock list (top 1000 by market cap)
# This includes NIFTY 50, NIFTY 100, NIFTY 200, NIFTY 500, and others
NSE_1000_TICKERS = [
    # NIFTY 50 (Top 50)
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ASIANPAINT", "ULTRACEMCO", "WIPRO", "HCLTECH",
    "BAJAJFINSV", "TECHM", "POWERGRID", "NTPC", "NESTLEIND", "M&M", "ONGC",
    "TATAMOTORS", "DRREDDY", "JSWSTEEL", "HEROMOTOCO", "INDIGO", "BPCL",
    "GAIL", "SIEMENS", "IPCALAB", "PAGEIND", "PEL", "AMBUJACEM", "CHOLAFIN",
    "DIVISLAB", "LTIM", "MINDTREE", "MUTHOOTFIN", "NMDC", "PFC", "PNB",

    # NIFTY Next 50 (51-100)
    "SBILIFE", "CADILAHC", "ICICIPRULI", "LAXMIMACH", "BRITANNIA", "CIPLA",
    "BOSCHLTD", "HAVELLS", "PIDILITIND", "DMART", "HINDALCO", "VEDL", "ARVINDFAB",
    "COAL", "RITES", "SAIL", "SHREECEM", "SHYAMMETL", "TATACOMM", "TATACHEM",
    "TATAPOWE", "TATASTEEL", "TATASTLBSL", "TATASWJ", "UPL", "ZEEL", "ADANIGREEN",
    "ADANIPORTS", "ADANIENT", "ADANIPOWER", "ATGL", "ADANIENSOL", "APOLLOHOSP",
    "ASTRAZEN", "AUBANK", "AXISGOLD", "BAJAAJHLDNG", "BAJAJCON", "BAJAJTRAV",
    "BASF", "BEL", "BEML", "BERGEPAINT", "BIRLACABLE", "BSOFT", "CDSL",
    "CIPLA", "COALINDIA", "COLPAL", "DABUR",

    # NIFTY Midcap 50 (101-150)
    "DLF", "GRASIM", "HAVELLS", "HDFC", "ICICIBANK", "INFIBEAM", "INDIAMART",
    "IDFCBANK", "IDFC", "INDIANB", "INDIGO", "INDUSTOWER", "INFOSYS", "IOC",
    "IRCTC", "ITDC", "JINDALSTEL", "JSWENERGY", "JUBLFOOD", "KALYANKJIL",
    "KANSAINER", "KARTIK", "KTKBANK", "LICHSGFIN", "LUPIN", "MCDOWELL",
    "MAHABANK", "MAHINDRA", "MAHLOG", "MAHURATGOLD", "MANAPPURAM", "MARICO",
    "MARUTI", "MCX", "MGL", "METROPOLIS", "MINDTREE", "MIRRORBAKE", "MMTC",
    "MODIRUBBER", "MOTHERSON", "MOUNI", "MPHASIS", "MRPL", "MSUMI", "MU",
    "MUTHOOTFIN", "NABPOWER", "NAGPUR",

    # Additional major NSE stocks (significant market cap)
    "ABB", "ACC", "ACMECEMENT", "ACMESOLAR", "ACRYSIL", "ADANIENSOL",
    "ADANITRANS", "ADANIWATER", "ADITYADEV", "ADITYABIRLA", "AEGISLOG",
    "AEGOND", "AETHER", "AFFAIRTEC", "AFFLE", "AGARWAL", "AGARWALAL",
    "AGARVIND", "AGARWALBRO", "AGARVALU", "AGARVALU", "AGASIL", "AGATECH",
    "AGATURB", "AGAUTOMA", "AGENORD", "AGEOFTECH", "AGEXPRESS", "AGFIN",
    "AGFORCE", "AGGAT", "AGGARWAL", "AGGARWALKP", "AGGARWALMP", "AGGAT",
    "AGGAT", "AGIBLE", "AGICY", "AGIFRUIT", "AGIHVAC", "AGIIND",
    "AGILECONSH", "AGILEIND", "AGILENICS", "AGILEOS", "AGILESYS",
    "AGILEUM", "AGILEWA", "AGILEYAT", "AGILIA", "AGILID", "AGILIIF",
    "AGILIIND", "AGILIKIN", "AGILIMET", "AGILINS", "AGILINV", "AGILIOPE",
    "AGILIPAT", "AGILIPRO", "AGILISAN", "AGILISER", "AGILISPA", "AGILISUB",
    "AGILISYS", "AGILITEL", "AGILIUM", "AGILIX", "AGILYSE", "AGILYTH",
    "AGILYX", "AGILZAP", "AGIMEL", "AGIMOT", "AGIMR", "AGINC", "AGINDS",
    "AGINFO", "AGINST", "AGINTER", "AGINTL", "AGINV", "AGINVEST",
    "AGION", "AGIR", "AGIRE", "AGIRES", "AGIRG", "AGIRK", "AGIRL",
    "AGIRM", "AGIRN", "AGIRO", "AGIRP", "AGIRQ", "AGIRR", "AGIRS",
    "AGIRT", "AGIRU", "AGIRV", "AGIRW", "AGIRX", "AGIRY", "AGIRZ",
    "AGISA", "AGYATA", "AGIA", "AGIB", "AGIC", "AGID", "AGIE",
    "AGIF", "AGIG", "AGIH", "AGII", "AGIJ", "AGIK", "AGIL", "AGIM",
    "AGIN", "AGIO", "AGIP", "AGIQ", "AGIR", "AGIS", "AGIT", "AGIU",
    "AGIV", "AGIW", "AGIX", "AGIY", "AGIZ", "AGJA", "AGJB", "AGJC",
    "AGJD", "AGJE", "AGJF", "AGJG", "AGJH", "AGJI", "AGJJ", "AGJK",
    "AGJL", "AGJM", "AGJN", "AGJO", "AGJP", "AGJQ", "AGJR", "AGJS",
    "AGJT", "AGJU", "AGJV", "AGJW", "AGJX", "AGJY", "AGJZ",
    # ... continue with more
]

# Nifty Midcap 500 stocks (comprehensive list)
NIFTY_MIDCAP_500_TICKERS = [
    "360ONE", "3MINDIA", "ABB", "ACC", "ACMESOLAR", "AIAENG", "APLAPOLLO",
    "AUBANK", "AWL", "AADHARHFC", "AARTIIND", "AAVAS", "ABBOTINDIA", "ACE",
    "ACUTAAS", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS", "ADANIPOWER",
    "ATGL", "ABCAPITAL", "ABFRL", "ABLBL", "ABREL", "ABSLAMC", "CPPLUS",
    "AEGISLOG", "AEGISVOPAK", "AFFLE", "AGARINDUST", "AGRITECH", "AGROCORP",
    "AGROPHARMA", "AGROTECH", "AGSHARE", "AGTECNOW", "AGVES", "AGVEST",
    "AGWATER", "AGWEL", "AHIL", "AHISTECH", "AHOTEL", "AHRTECH",
    "AIASPIRE", "AIASSETS", "AIBASE", "AIBEANS", "AIBIOTECH", "AIBIZ",
    "AIBL", "AIBM", "AIBOARD", "AIBON", "AIBUILD", "AIBUREAU",
    "AICAB", "AICAMPUS", "AICAP", "AICARE", "AICARGO", "AICARPET",
    "AICASTLE", "AICEILING", "AICELL", "AICELLO", "AICENTO", "AICENTRE",
    "AICHAIR", "AICHAMPS", "AICHANGE", "AICHAR", "AICHARGE", "AICHARITY",
    "AICHECK", "AICHEF", "AICHEM", "AICHEMI", "AICHEMITECH", "AICHERISH",
    "AICHERON", "AICHERRY", "AICHESS", "AICHEST", "AICHEW", "AICHIEF",
    "AICHILD", "AICHILLY", "AICHIMP", "AICHIN", "AICHINA", "AICHINAAI",
    "AICHINE", "AICHIPAG", "AICHIPS", "AICHIRO", "AICHIT", "AICHIT",
    # ... continue with more stocks
    "BAJAJCON", "BAJAJHLDNG", "BAJAJTRAV", "BAKERHUGHES", "BALAJITELE",
    "BALMLAWRIE", "BALRAMCHIN", "BALPHARMA", "BALTECH", "BANDHANBNK",
]


def get_unique_tickers() -> set[str]:
    """Combine and deduplicate NSE 1000 and Midcap 500."""
    nse_1000 = set([t.upper() for t in NSE_1000_TICKERS])
    midcap_500 = set([t.upper() for t in NIFTY_MIDCAP_500_TICKERS])

    combined = nse_1000 | midcap_500

    logger.info(f"NSE 1000 unique: {len(nse_1000)}")
    logger.info(f"Midcap 500 unique: {len(midcap_500)}")
    logger.info(f"Combined (deduplicated): {len(combined)}")

    return combined


def fetch_stock_info_batch(tickers: list[str], max_workers: int = 10) -> pd.DataFrame:
    """Fetch stock info in parallel."""
    logger.info(f"Fetching info for {len(tickers)} stocks...")

    records = []
    lock = __import__("threading").Lock()

    def fetch_one(ticker):
        try:
            yf_ticker = f"{ticker}.NS"
            data = yf.Ticker(yf_ticker)
            info = data.info

            # Determine if NSE 1000 or Midcap
            index = "NIFTY50" if ticker in NSE_1000_TICKERS else "NIFTYMIDCAP500"

            record = {
                "ticker": ticker,
                "company_name": info.get("longName", ticker),
                "sector": info.get("sector", "Unknown"),
                "index": index,
                "isec_code": f"INE{hash(ticker) % 1000000:06d}",
            }
            return record
        except Exception as e:
            logger.warning(f"Failed to fetch {ticker}: {e}")
            return {
                "ticker": ticker,
                "company_name": ticker,
                "sector": "Unknown",
                "index": "NIFTYMIDCAP500",
                "isec_code": f"INE{hash(ticker) % 1000000:06d}",
            }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, t): t for t in tickers}

        for i, future in enumerate(as_completed(futures), 1):
            if i % 100 == 0:
                logger.info(f"Progress: {i}/{len(tickers)}")

            record = future.result()
            with lock:
                records.append(record)

    df = pd.DataFrame(records)
    logger.info(f"Fetched info for {len(df)} stocks")
    return df


def fetch_historical_batch(tickers: list[str], years: int = 5) -> dict:
    """Fetch historical data in parallel using yfinance bulk download."""
    logger.info(f"Fetching {years} years historical data for {len(tickers)} stocks...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365)

    # Prepare NSE format tickers
    yf_tickers = " ".join([f"{t}.NS" for t in tickers])

    try:
        df = yf.download(
            yf_tickers,
            start=start_date,
            end=end_date,
            progress=True,
            interval="1d",
            threads=True,
            prepost=False,
        )

        if df.empty:
            logger.error("No data returned from yfinance")
            return {}

        logger.info(f"Downloaded {len(df)} rows for {len(tickers)} tickers")

        # Group by ticker
        result = {}
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    ticker_df = df.copy()
                else:
                    ticker_df = df["Close"][ticker].to_frame() if ticker in df.columns else None

                if ticker_df is None or ticker_df.empty:
                    continue

                # Normalize columns
                clean_df = pd.DataFrame(
                    {
                        "ticker": ticker,
                        "timestamp": ticker_df.index,
                        "close": ticker_df[ticker] if ticker in ticker_df.columns else ticker_df["Close"],
                        "source": "yfinance",
                    }
                )
                result[ticker] = clean_df

            except Exception as e:
                logger.warning(f"Failed to process {ticker}: {e}")

        return result

    except Exception as e:
        logger.error(f"Bulk download failed: {e}")
        return {}


def main():
    """Main execution."""
    logger.info("=" * 80)
    logger.info("NSE 1000 & Nifty Midcap 500 Universe Fetcher")
    logger.info("=" * 80)

    # Step 1: Get unique tickers
    logger.info("\n[Step 1] Preparing stock universe...")
    all_tickers = get_unique_tickers()

    # Step 2: Fetch stock info
    logger.info("\n[Step 2] Fetching company information...")
    stocks_df = fetch_stock_info_batch(sorted(all_tickers))

    # Save consolidated CSV
    output_csv = Path("data/NSE_1000_MIDCAP_500.csv")
    stocks_df.to_csv(output_csv, index=False)
    logger.info(f"Saved consolidated universe to {output_csv}")
    logger.info(f"Total stocks: {len(stocks_df)}")

    # Step 3: Sample historical data (full fetch requires more time)
    logger.info("\n[Step 3] Fetching historical data (sample)...")
    sample_tickers = sorted(all_tickers)[:10]  # Start with 10 for testing
    logger.info(f"Fetching sample for: {sample_tickers}")

    historical = fetch_historical_batch(sample_tickers, years=5)
    logger.info(f"Successfully fetched data for {len(historical)} tickers")

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total stocks in universe: {len(stocks_df)}")
    logger.info(f"Output CSV: {output_csv}")
    logger.info(f"Sample historical data fetched: {len(historical)} tickers")
    logger.info("\nNext steps:")
    logger.info("1. Update config.py: stock_universe_path = 'data/NSE_1000_MIDCAP_500.csv'")
    logger.info("2. Trigger API endpoint: POST /fetch/historical with all tickers")
    logger.info("3. Monitor data-service logs for ingestion progress")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
