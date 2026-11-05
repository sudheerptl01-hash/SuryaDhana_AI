"""Batch 2: ETF holdings — SPDR GLD, iShares IAU, Sprott PHYS, AMFI (India)."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verify import fetch  # noqa: E402

# SPDR GLD: the historical archive CSV the site has served for years, plus the pages
fetch("GLD archive CSV (historical holdings)", "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv", save_as="gld_archive.csv")
fetch("GLD historical data page", "https://www.spdrgoldshares.com/usa/historical-data/", save_as="gld_hist_page.html")
fetch("GLD home (usa)", "https://www.spdrgoldshares.com/usa/", save_as="gld_home.html")
fetch("GLD robots", "https://www.spdrgoldshares.com/robots.txt")
# World gold ETF list on the SPDR site (monthly, 'world gold ETFs' table)
fetch("SPDR GLD world gold ETFs page", "https://www.spdrgoldshares.com/usa/world-gold-etfs/", save_as="gld_world_etfs.html")

# iShares IAU: product page + holdings/ performance CSV download endpoints
fetch("IAU product page", "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund", save_as="iau_page.html")
fetch("IAU holdings CSV", "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund/1467271812596.ajax?fileType=csv&fileName=IAU_holdings&dataType=fund", save_as="iau_holdings.csv")
fetch("iShares robots", "https://www.ishares.com/robots.txt")

# Sprott PHYS
fetch("Sprott PHYS page", "https://sprott.com/investment-strategies/physical-bullion-trusts/gold/", save_as="phys_page.html")
fetch("Sprott robots", "https://sprott.com/robots.txt")

# AMFI India: daily NAV (all schemes, text) + monthly AUM pages
fetch("AMFI NAVAll.txt (daily NAV all schemes)", "https://www.amfiindia.com/spages/NAVAll.txt", save_as="amfi_navall.txt")
fetch("AMFI AUM data page", "https://www.amfiindia.com/research-information/aum-data/average-aum", save_as="amfi_aum_page.html")
fetch("AMFI monthly AUM (industry) page", "https://www.amfiindia.com/research-information/other-data/mf-industry-monthly-data", save_as="amfi_monthly_page.html")
fetch("AMFI robots", "https://www.amfiindia.com/robots.txt")
