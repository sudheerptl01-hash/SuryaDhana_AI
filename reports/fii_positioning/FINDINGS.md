# FII index-futures positioning vs NIFTY: findings (12 Oct 2026)

Pre-registered (`PLAN.md`); tables in `REPORT.md`; script `scripts/fii_positioning_study.py`. 1,735 sessions,
Oct 2019 → Oct 2026. The NIFTY 50 return is measured from the close after the signal day (tradable), with
Newey-West t-statistics for the overlapping windows.

**Verdict: FAIL on both hypotheses. FII positioning does not predict NIFTY over 5–20 sessions.**

| Signal | 20-session result | Both halves |
|---|---|---|
| H1 · FII net futures flow over 5 days (top minus bottom tercile) | −0.53% (t −1.34) | −0.93% / −0.30% |
| H2 · FII long ratio in the bottom 10% of its year | +0.05% vs average (t 0.07) | −0.40% / +0.38% |

- If anything, heavy FII buying preceded slightly *weaker* NIFTY (a contrarian sign), but nowhere near significant.
- Extreme FII shorting did not reliably precede rebounds. Today's 9.6% long ratio is only the 22nd percentile of
  the past year: FIIs have been very short all year.
- **Use:** the MKT "Who holds index futures" panel is context about who is positioned where, not a timing tool.
  The Decision Desk keeps its own regime rule (NIFTY vs its 200-DMA).
