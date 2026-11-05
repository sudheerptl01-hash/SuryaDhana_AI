"""Batch 3: Shanghai Gold Exchange, SHFE, Swiss customs, Hong Kong C&SD, Dubai."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verify import fetch  # noqa: E402

# SGE English site
fetch("SGE delayed quotes", "https://en.sge.com.cn/data_DelayedQuotes", save_as="sge_delayed.html")
fetch("SGE benchmark price page", "https://en.sge.com.cn/data_BenchmarkPrice", save_as="sge_benchmark.html")
fetch("SGE data index", "https://en.sge.com.cn/data", save_as="sge_data.html")
fetch("SGE weekly data", "https://en.sge.com.cn/data_WeeklyData", save_as="sge_weekly.html")
fetch("SGE monthly data", "https://en.sge.com.cn/data_MonthlyData", save_as="sge_monthly.html")
fetch("SGE CN robots", "https://www.sge.com.cn/robots.txt")
fetch("SGE EN robots", "https://en.sge.com.cn/robots.txt")

# SHFE: English data pages and the daily JSON the CN site serves
fetch("SHFE EN home", "https://www.shfe.com.cn/eng/", save_as="shfe_en.html")
fetch("SHFE daily data JSON (kx) 23 Oct 2026", "https://www.shfe.com.cn/data/dailydata/kx/kx20261023.dat", save_as="shfe_kx_20261023.json")
fetch("SHFE daily data JSON (kx) 24 Oct 2025 (old format check)", "https://www.shfe.com.cn/data/dailydata/kx/kx20251024.dat", save_as="shfe_kx_20251024.json")
fetch("SHFE data index EN", "https://www.shfe.com.cn/eng/market/data/", save_as="shfe_data_en.html")
fetch("SHFE robots", "https://www.shfe.com.cn/robots.txt")

# Swiss customs (BAZG / FOCBS): Swiss-Impex portal and the monthly 'Aussenhandel' press material
fetch("Swiss-Impex portal", "https://www.gate.ezv.admin.ch/swissimpex/", save_as="swissimpex.html")
fetch("BAZG foreign trade statistics page", "https://www.bazg.admin.ch/bazg/en/home/topics/swiss-foreign-trade-statistics.html", save_as="bazg_trade.html")
fetch("BAZG robots", "https://www.bazg.admin.ch/robots.txt")

# Hong Kong Census & Statistics: merchandise trade by commodity (Table 56 / 100)
fetch("HK C&SD trade by commodity page", "https://www.censtatd.gov.hk/en/scode230.html", save_as="hk_censtatd.html")
fetch("HK C&SD open data API (sample)", "https://www.censtatd.gov.hk/api/get.php?id=56&lang=en&param=N4Ig", save_as="hk_api_sample.json")
fetch("HK C&SD robots", "https://www.censtatd.gov.hk/robots.txt")

# Dubai: DMCC and Dubai Customs (public stats pages)
fetch("Dubai Customs statistics", "https://www.dubaicustoms.gov.ae/en/Pages/default.aspx", save_as="dubai_customs.html")
fetch("DMCC gold page", "https://www.dmcc.ae/gold", save_as="dmcc_gold.html")
