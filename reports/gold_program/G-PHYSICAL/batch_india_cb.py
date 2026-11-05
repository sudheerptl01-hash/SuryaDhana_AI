"""Batch 4: WGC/Goldhub, US Mint, Perth Mint, India imports (Commerce/DGCI&S/PIB), RBI WSS, IMF IFS, CME stocks."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verify import fetch  # noqa: E402

# World Gold Council / Goldhub
fetch("WGC Goldhub data index", "https://www.gold.org/goldhub/data", save_as="wgc_data_index.html")
fetch("WGC central bank statistics", "https://www.gold.org/goldhub/data/gold-reserves-by-country", save_as="wgc_cb_reserves.html")
fetch("WGC monthly central bank statistics", "https://www.gold.org/goldhub/data/monthly-central-bank-statistics", save_as="wgc_cb_monthly.html")
fetch("WGC gold ETF flows", "https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows", save_as="wgc_etf.html")
fetch("WGC demand & supply", "https://www.gold.org/goldhub/data/gold-supply-and-demand-statistics", save_as="wgc_supply_demand.html")
fetch("WGC gold prices", "https://www.gold.org/goldhub/data/gold-prices", save_as="wgc_prices.html")
fetch("WGC gold demand trends (research)", "https://www.gold.org/goldhub/research/gold-demand-trends", save_as="wgc_gdt.html")
fetch("WGC terms", "https://www.gold.org/terms-and-conditions", save_as="wgc_terms.html")
fetch("WGC robots", "https://www.gold.org/robots.txt")

# US Mint bullion sales
fetch("US Mint bullion sales figures", "https://www.usmint.gov/about/production-sales-figures/bullion-sales", save_as="usmint_bullion.html")
fetch("US Mint robots", "https://www.usmint.gov/robots.txt")
# Perth Mint monthly sales (blog)
fetch("Perth Mint news/blog", "https://www.perthmint.com/news/", save_as="perthmint_news.html")
fetch("Perth Mint robots", "https://www.perthmint.com/robots.txt")

# India imports: Ministry of Commerce tradestat, PIB monthly trade press release, DGCI&S
fetch("Commerce tradestat (commodity-wise)", "https://tradestat.commerce.gov.in/eidb/default.asp", save_as="tradestat.html")
fetch("Commerce tradestat home", "https://tradestat.commerce.gov.in/", save_as="tradestat_home.html")
fetch("DGCI&S", "https://www.dgciskol.gov.in/", save_as="dgcis.html")
fetch("PIB press releases search (Commerce)", "https://pib.gov.in/allRel.aspx", save_as="pib.html")
fetch("Commerce ministry press release page", "https://commerce.gov.in/press-releases/", save_as="commerce_press.html")

# RBI: weekly statistical supplement + DBIE
fetch("RBI WSS page", "https://website.rbi.org.in/web/rbi/publications/weekly-statistical-supplement", save_as="rbi_wss.html")
fetch("RBI legacy WSS view", "https://rbi.org.in/Scripts/WSSView.aspx", save_as="rbi_wss_legacy.html")
fetch("RBI DBIE", "https://data.rbi.org.in/", save_as="rbi_dbie.html")
fetch("RBI robots", "https://website.rbi.org.in/robots.txt")

# IMF IFS (data.imf.org) + IMF's newer datasets portal; also World Bank fallback for reserves incl. gold
fetch("IMF data portal", "https://data.imf.org/", save_as="imf_data.html")
fetch("IMF IFS dataset page", "https://data.imf.org/en/datasets/IMF.STA:IFS", save_as="imf_ifs.html")
fetch("IMF SDMX REST (new) dataflow list", "https://api.imf.org/external/sdmx/2.1/dataflow", save_as="imf_sdmx.xml")

# CME COMEX gold warehouse stocks (physical vault data; cross-ref G-COT)
fetch("CME COMEX gold stocks XLS", "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls", save_as="cme_gold_stocks.xls")
fetch("CME robots", "https://www.cmegroup.com/robots.txt")
