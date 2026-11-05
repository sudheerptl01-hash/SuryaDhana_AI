# Decision Desk candidate filter: skip stocks after bad results (pre-registered plan)

Written 2026-10-11, before running. Follows `reports/results_drift/FINDINGS.md` (H2 PASS).

- **Rule tested:** do not open a new Desk position in a stock whose results-day reaction was ≤ −5% vs the
  equal-weight liquid universe in the last 60 sessions. Existing holdings are kept, the same as the bulk-deal
  filter.
- **Events:** `reports/results_drift/events.csv` rows with `reaction_x ≤ −5`, dated on the reaction session.
  They are known at that session's close, so they are point-in-time for a month-end signal on or after that day.
- **Baseline:** the approved rules (mom_nse | N20 | nifty200_vt | sector cap 40%), 66% equity share plus the
  liquid fund, ₹5 lakh, real ICICI costs and taxes (`scripts/phase_b_allocator.py`, the Desk's own code).
- **Candidate:** the baseline plus this filter at 60 sessions. A 20-session window is reported as sensitivity
  only.
- **Window:** 2015-03-01 (the first full year of results events) → latest. Discovery before 2024-07-01,
  holdout from 2024-07-01 (the same split as Phase B and the bulk-deal filter).
- **Adoption bar (same as the bulk-deal filter):** holdout CAGR not lower **and** holdout max drawdown not
  deeper than the baseline. Full-period CAGR is reported. Even a PASS changes nothing until the owner reviews it.
