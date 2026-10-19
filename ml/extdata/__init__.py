"""External-data stream (P3) of the SuryaDhana improvement phase.

Downloads NSE archive files (F&O bhavcopy, all-index closes, participant-wise
open interest, index constituent lists, equity master) into ml/data_raw/,
parses them into staging parquet under ml/data_ext/, and builds the four
pre-registered feature families F1-F4 (ml/IMPROVEMENT_PLAN.md, section 2-P3).

Never opens nse_market.duckdb: spot prices and the universe come from the
parquet exports in ml/results/improve/cache/.
"""
