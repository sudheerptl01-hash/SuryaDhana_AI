"""P1 data-integrity stream of the SuryaDhana improvement phase (ml/IMPROVEMENT_PLAN.md).

Modules
-------
common             paths, logging, the polite archive client shared by every download
download_pr        resume-safe download of the daily PR bundles (and a few named files)
sessions           prev_close continuity scan, missing-session recovery, 2022-03-08 check
corporate_actions  bc-file parser, ratio rules, validation against observed prices
etf                point-in-time ETF list (etf files) and the EQUITY_L equity master
write_phase        the single read-write window on nse_market.duckdb
build_v2           the v2 five-year dataset (ml/data_5y_v2/) and the v1-vs-v2 comparison
report             integrity.json + INTEGRITY.md
"""
