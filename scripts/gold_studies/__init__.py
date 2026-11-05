"""Pre-registered gold studies (GOLD program phase 2, builder B7).

Each study has a `PLAN.md` under `reports/gold_program/<study>/` written before any result was looked at, a runnable
script here that reads only stored data (saved research samples or the data-service gold tables), and a `FINDINGS.md`
row in the `reports/fii_positioning` format once it has run. Every study honours the project anti-patterns: no
look-ahead (signals dated at their public release, entry at the next session's close), no shuffling, walk-forward
out-of-sample, round-trip costs at the 0.15 % project floor.

Studies: G-STUDY-2 (daily OI x price quadrant), GS-P1 (GLD daily tonnes), GS-P2 (WGC weekly ETF flows),
GS-P4 (month-of-year seasonality of gold in rupees). A study whose data is not stored yet exits 3 ("data not yet
ingested") or 4 ("insufficient history") and writes nothing. The row shape for the aggregate FINDINGS.md is in
`FINDINGS_ROW_TEMPLATE.md`; `tests/test_gold_study_reproduce.py` re-runs the studies and asserts their headline numbers.
"""
