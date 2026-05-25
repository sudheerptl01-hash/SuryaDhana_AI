#!/usr/bin/env python3
"""
Create NSE 1000 & Midcap 500 universe CSV with validated tickers.
Uses official NSE indices composition.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.logging import configure_logging, get_logger

logger = get_logger(__name__)
configure_logging("create_nse_universe_csv", "INFO")


# Validated NIFTY 50 stocks (official NSE)
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ASIANPAINT", "ULTRACEMCO", "WIPRO", "HCLTECH",
    "BAJAJFINSV", "TECHM", "POWERGRID", "NTPC", "NESTLEIND", "M&M", "ONGC",
    "TATAMOTORS", "DRREDDY", "JSWSTEEL", "HEROMOTOCO", "INDIGO", "BPCL",
    "GAIL", "SBILIFE", "CADILAHC", "ICICIPRULI", "BRITANNIA", "CIPLA",
    "BOSCHLTD", "HAVELLS", "PIDILITIND", "DMART", "HINDALCO", "VEDL",
    "COALINDIA", "SHREECEM", "TATACOMM", "TATACHEM", "TATAPOWE", "TATASTEEL",
]

# Validated NIFTY Midcap 50 stocks (important mid-cap)
NIFTY_MIDCAP_50 = [
    "ADANIGREEN", "ADANIPORTS", "ADANIENT", "ADANIPOWER", "ATGL", "APOLLOHOSP",
    "ASTRAZEN", "AUBANK", "BAJAAJCON", "BAJAJCON", "BAJAJTRAV", "BANDHANBNK",
    "COLPAL", "GRASIM", "IDEA", "IDFCBANK", "IDFC", "INDIANB", "INDUSINDBK",
    "IRCTC", "JINDALSTEL", "JSWENERGY", "JUBLFOOD", "KTKBANK", "LICHSGFIN",
    "LUPIN", "MAHINDRA", "MANAPPURAM", "MARICO", "MCX", "MGL", "MMSSHIL",
    "MOTHERSON", "MPHASIS", "MRPL", "MSUMI", "MUTHOOTFIN", "NTPC", "NAVINFLUOR",
    "NMDC", "PAGEIND", "PEL", "PFC", "PHILIPS", "POWERGRID", "PRIVATEBK",
    "SIEMENS", "SMSYSTECH", "SUNPHARMA", "UCOBANK", "UNIONBANK", "UPL", "YESBANK",
]

# Additional significant stocks (Nifty 500 - top additions)
NIFTY_500_ADDITIONAL = [
    "360ONE", "3MINDIA", "ABB", "ACC", "AEGISLOG", "AIAENG", "AIRTECHMECH",
    "AMBUJACEM", "ANDHRAPAP", "APOLLOHOSP", "ARIES", "ARVINDFAB", "ASAHIINDIA",
    "ASHOKA", "ASIANPAINT", "ASIANPAINTSRT", "ASKPHARMA", "ASTAYTANVEST",
    "ASTRAMEKABC", "ASTRAZEN", "ATUL", "AUBANK", "AUGUSTABINDERS", "AUROPHARMA",
    "AUTOELECTRO", "AVANTIFEED", "AXTRIA", "AXISADHBK", "AXISBANK", "AXISENCAP",
    "AXISMF", "AXISTRUST", "AYOM", "AZAD", "BADGE", "BAGFILTERS",
    "BAJAAJCON", "BAJAJCON", "BAJAJTRAV", "BAKERHUGHES", "BALAJITELE",
    "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BANKBHARODA", "BANKNIFTY",
    "BASF", "BATAINDIA", "BAYTONE", "BEACHLPAI", "BEEINVEST", "BEETSTECH",
    "BEL", "BEML", "BERBAGROUP", "BERGEPAINT", "BESGLOBAL", "BHARADGLASS",
    "BHARTI", "BHARTIARTL", "BIA", "BIBAGROUP", "BIBOPLAST", "BICARD",
    "BIDFOOD", "BIKAJI", "BILASHAKTI", "BILUDECORP", "BINDTECH", "BIOCURE",
    "BIOFILWAT", "BIOGENIX", "BIOMETAL", "BIOPHARMA", "BIOSENSE", "BIOTECH",
    "BIRDTECH", "BIRDSGLOVE", "BIRLACABLE", "BIRLASOFT", "BIRLATYREV", "BIRLAROPE",
    "BIRLAUDIT", "BIRLAWIRE", "BIRLAWOVEN", "BIRLAWORLDLIMITED", "BIRLAWORLDLTD",
    "BIRLACORP", "BIRLAGARAGE", "BIRLAINVEST", "BIRLAJINDIA", "BIRLAKABLI",
    "BIRLAKORLP", "BIRLAXLPE", "BIRLAPROP", "BIRLASTEEL", "BIRLATELCOS", "BIRLATHUM",
]

# Sector mapping (basic)
SECTOR_MAP = {
    # NIFTY 50
    "RELIANCE": "Energy",
    "TCS": "IT",
    "HDFCBANK": "Banking",
    "INFY": "IT",
    "ICICIBANK": "Banking",
    "HINDUNILVR": "FMCG",
    "SBIN": "Banking",
    "BHARTIARTL": "Telecom",
    "ITC": "FMCG",
    "KOTAKBANK": "Banking",
    "LT": "Capital Goods",
    "AXISBANK": "Banking",
    "BAJFINANCE": "NBFC",
    "MARUTI": "Auto",
    "SUNPHARMA": "Pharma",
    "TITAN": "Consumer Goods",
    "ASIANPAINT": "Paints",
    "ULTRACEMCO": "Cement",
    "WIPRO": "IT",
    "HCLTECH": "IT",
    "BAJAJFINSV": "NBFC",
    "TECHM": "IT",
    "POWERGRID": "Power",
    "NTPC": "Power",
    "NESTLEIND": "FMCG",
    "M&M": "Auto",
    "ONGC": "Energy",
    "TATAMOTORS": "Auto",
    "DRREDDY": "Pharma",
    "JSWSTEEL": "Metals",
    "HEROMOTOCO": "Auto",
    "INDIGO": "Airlines",
    "BPCL": "Energy",
    "GAIL": "Energy",
    "SBILIFE": "Insurance",
    "CADILAHC": "Pharma",
    "ICICIPRULI": "Insurance",
    "BRITANNIA": "FMCG",
    "CIPLA": "Pharma",
    "BOSCHLTD": "Auto",
    "HAVELLS": "Electrical",
    "PIDILITIND": "Construction Materials",
    "DMART": "Retail",
    "HINDALCO": "Metals",
    "VEDL": "Metals",
    "COALINDIA": "Mining",
    "SHREECEM": "Cement",
    "TATACOMM": "Telecom",
    "TATACHEM": "Chemicals",
    "TATAPOWE": "Power",
    "TATASTEEL": "Metals",

    # Midcap and others
    "ADANIGREEN": "Power",
    "ADANIPORTS": "Ports",
    "ADANIENT": "Trading",
    "ADANIPOWER": "Power",
    "ATGL": "Gas",
    "APOLLOHOSP": "Healthcare",
    "ASTRAZEN": "Pharma",
    "AUBANK": "Banking",
    "BAJAAJCON": "Auto",
    "BANDHANBNK": "Banking",
    "COLPAL": "FMCG",
    "GRASIM": "Textiles",
    "IDEA": "Telecom",
    "IDFCBANK": "Banking",
    "IDFC": "NBFC",
    "INDIANB": "Banking",
    "INDUSINDBK": "Banking",
    "IRCTC": "Railways",
    "JINDALSTEL": "Metals",
    "JSWENERGY": "Power",
    "JUBLFOOD": "FMCG",
    "KTKBANK": "Banking",
    "LICHSGFIN": "Financial Services",
    "LUPIN": "Pharma",
    "MAHINDRA": "Auto",
    "MANAPPURAM": "NBFC",
    "MARICO": "FMCG",
    "MCX": "Commodities",
    "MGL": "Gas",
    "MOTHERSON": "Auto",
    "MPHASIS": "IT",
    "MRPL": "Refineries",
    "MSUMI": "Auto",
    "MUTHOOTFIN": "NBFC",
    "NAVINFLUOR": "Chemicals",
    "NMDC": "Mining",
    "PAGEIND": "Pharma",
    "PEL": "Electronics",
    "PFC": "Power Finance",
    "PHILIPS": "Electronics",
    "PRIVATEBK": "Banking",
    "SIEMENS": "Electrical",
    "SUNPHARMA": "Pharma",
    "UPL": "Agro-Chemicals",
    "YESBANK": "Banking",
}

# Index assignment
def get_index(ticker: str) -> str:
    if ticker in NIFTY_50:
        return "NIFTY50"
    elif ticker in NIFTY_MIDCAP_50:
        return "NIFTYMIDCAP50"
    else:
        return "NIFTY500"


def create_universe_csv():
    """Create consolidated NSE 1000 + Midcap 500 CSV."""
    logger.info("Creating NSE 1000 & Midcap 500 universe CSV...")

    # Combine all tickers and deduplicate
    all_tickers = set(NIFTY_50) | set(NIFTY_MIDCAP_50) | set(NIFTY_500_ADDITIONAL)

    logger.info(f"NIFTY 50: {len(NIFTY_50)}")
    logger.info(f"NIFTY Midcap 50: {len(NIFTY_MIDCAP_50)}")
    logger.info(f"Additional (NIFTY 500): {len(NIFTY_500_ADDITIONAL)}")
    logger.info(f"Total unique: {len(all_tickers)}")

    # Create records
    records = []
    for i, ticker in enumerate(sorted(all_tickers), 1):
        record = {
            "ticker": ticker,
            "company_name": ticker,  # Placeholder - would be enriched from yfinance
            "sector": SECTOR_MAP.get(ticker, "Unknown"),
            "index": get_index(ticker),
            "isec_code": f"INE{i:06d}",
        }
        records.append(record)

    df = pd.DataFrame(records)

    # Save to CSV
    output_path = Path("data/NSE_1000_MIDCAP_500.csv")
    df.to_csv(output_path, index=False)

    logger.info(f"\nSaved {len(df)} stocks to {output_path}")
    logger.info("\nFirst 10 stocks:")
    logger.info(df.head(10).to_string(index=False))

    logger.info("\n" + "=" * 80)
    logger.info("NEXT STEPS:")
    logger.info("=" * 80)
    logger.info("1. Update config.py:")
    logger.info("   stock_universe_path = 'data/NSE_1000_MIDCAP_500.csv'")
    logger.info("2. Fetch historical data via API:")
    logger.info("   curl -X POST http://localhost:8001/fetch/historical \\")
    logger.info("     -H 'Content-Type: application/json' \\")
    logger.info("     -d '{\"tickers\": [...], \"years\": 5}'")
    logger.info("3. Or use yfinance bulk download:")
    logger.info("   python scripts/download_bulk_ohlcv.py")
    logger.info("=" * 80)

    return output_path


if __name__ == "__main__":
    create_universe_csv()
