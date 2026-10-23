"""Company events from the exchange's daily announcement files (phase-2 stream Q6).

parse     PR bundles -> one record per announcement (ml/data_ext/events_raw.parquet)
classify  fixed rule table: results / routine / rating / mgmt_change / orders / insolvency
features  family E of ml/IMPROVEMENT_PLAN_2.md Q6 on the ten-year dataset rows
checks    coverage, point-in-time recompute, delete-the-future and shift tests
ic        descriptive rank IC (last step)
report    events.json -> EVENTS.md
"""
