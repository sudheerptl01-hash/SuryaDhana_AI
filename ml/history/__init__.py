"""P4 history stream: NSE cash-market EOD 2016-10..2021-09 from the legacy archives.

Modules
-------
common    paths, URL builders, the calendar walk
download  resume-safe, rate-limited fetcher for CM bhavcopy, MTO delivery and PR bundles
parse     CM + MTO -> equity_eod schema; PR bundle -> Bc / ETF / Pd records
validate  overlap check against the stored window, calendar, continuity, coverage

Nothing here opens nse_market.duckdb; overlap checks read the parquet export in
ml/results/improve/cache/.
"""
