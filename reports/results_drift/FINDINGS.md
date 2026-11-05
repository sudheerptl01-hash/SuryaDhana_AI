# Post-results drift on NSE: findings (11 Oct 2026)

Pre-registered in `PLAN.md` before any number was computed. Full tables are in `REPORT.md`; every event is in
`events.csv`. Script: `scripts/results_drift_study.py`.

**Data:**
- **Events:** 16,247 quarterly results of 651 stocks, 2015 → Oct 2026. The stock list is the 300 most traded
  in each year 2014–2025, including later-delisted names.
- **Release times:** exact NSE broadcast times (`nse_results`).
- **Entry:** the open after the reaction session.
- **Excess:** vs the equal-weight liquid NSE universe.
- **Costs:** ICICI round trip 0.95% at ₹50,000.

> **Correction, 14 Oct 2026 (02:55):** release times for 2025–26 were often SEBI's quarterly *governance* filing
> (1–2 weeks before the results) instead of the results themselves: about 77% of integrated-era quarters were
> wrong. The parser is fixed, the data repaired, and the study re-run unchanged on corrected data
> (`corrected_2026-10-14/REPORT.md`, 16,271 events). **All three verdicts stand, and H2 is stronger:** holdout
> 60-session excess after strong bad news −2.04% (t −3.03), was −1.82% (t −2.50). H1 holdout +3.40% (t 3.41),
> still FAIL on discovery. H3 holdout +5.39% (t 3.50). The 2015–21 discovery is unaffected. The ⚠ BAD RESULTS
> flag now uses the corrected dates (42 stocks flagged, was 10).

## Verdicts

| Hypothesis | Result | 60-session excess (discovery 2015–21 / holdout 2022–26) |
|---|---|---|
| H1 · strong good news (≥ +5% vs market on the reaction day) keeps drifting up | **FAIL** | +2.72% (t 1.37) / +3.58% (t 3.98); holdout +2.62% after costs |
| H2 · strong bad news (≤ −5%) keeps drifting down | **PASS** | −3.69% (t −2.77) / −1.82% (t −2.50) |
| H3 · strong-up minus strong-down spread > 0 | **PASS** | +7.38% (t 2.79) / +5.41% (t 2.85) |

## What it means for you

1. **Bad results keep hurting: this is a usable avoid-filter.**
   - After a reaction of −5% or worse vs the market, the stock lagged the market by another 1.8–3.7% over the
     next 60 sessions, in both periods.
   - Only 34–39% of these stocks beat the market afterwards.
   - The book cannot short, but it can refuse to buy. Do not open a new position within ~3 months of a strong
     negative results reaction.
2. **Good results drift up, but the evidence is not clean enough to trade alone.**
   - The strong-up bucket earned +2.7% / +3.6% excess, and the holdout is highly significant (t 4.0).
   - But 2015–2021 alone did not clear t ≥ 2.0 (t 1.37), and the median 2015–21 strong-up stock still *lagged*
     (−1.5%).
   - By the pre-registered rule this is a FAIL. It stays a candidate to watch, not a signal.
3. **Ordinary results (between −5% and +5%) carry no drift.** All three middle buckets are within ±1.2% of the
   market, with no consistent sign. Most results are noise for a 3-month holder.
4. **For the Desk (exploratory, not pre-registered):**
   - The drift after good news was strongest in less-traded names (< ₹50 cr/day: +5.3% / +4.6%).
   - In large names it appeared only in 2022–26.
   - Gap-and-hold vs gap-fade made little difference.

## Caveats

- **Coverage:**
  - 77 of the 744 symbols have no release times on NSE. They are mostly renamed (ADANIGAS→ATGL, LTI→LTIM…) or
    delisted, plus ETFs and a few NSE gaps (MCX, HEG).
  - Delisted names' results are the most likely to be missing, so the strong-down drift is, if anything,
    understated.
- **No analyst consensus:** the "surprise" is the market's reaction, not earnings vs expectations.
- **Inference:** weekly averages with Newey-West lags. Weeks with no results (between seasons) are skipped,
  not zero-filled.
- **Costs:** a ₹50,000 position. Smaller positions cost more (see `reports/costs/CAPITAL_VIABILITY.md`).

## Next step (needs your review; nothing changed)

Test H2 as a **Decision Desk candidate filter**: "skip a momentum pick within 60 sessions of a ≤ −5% excess
results reaction". It should be pre-registered and use the same holdout rule as the bulk-deal filter
(`reports/desk_filter/REPORT.md`). Trading rules change only after your review.
