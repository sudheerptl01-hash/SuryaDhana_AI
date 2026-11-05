# Earnings-growth drift: report (broad run)

Run 2026-10-13 22:11 · plan: PLAN.md (pre-registered 13 Oct 2026, 15:00) · 5785 filings from 1142 companies · entries 2023-07-20 → 2026-10-13 · round-trip cost 0.95% at ₹50,000

Companies that have since stopped trading (last close > 30 days before the data end): 16 (CIGNITITEC, GSPL, HERCULES, HINDMOTORS, IDFC, ISEC, ISMTLTD, IWEL, JBCHEPHARM, MANGCHEFER, PEL, TATACOFFEE…)

## Verdict on the pre-registered hypotheses (60 sessions)

- **H1 strong growth drifts up:** FAIL
- **H2 collapse drifts down (avoid):** FAIL
- **H3 strong growth − collapse spread positive in both halves:** PASS
- **Addendum check, strong growth vs same-week filings (positive in both halves):** yes · discovery 2.24% weekly / 0.96% per filing (t 1.95, 35 weeks) · holdout 0.34% weekly / 1.63% per filing (t 0.74, 33 weeks)

## 20 sessions after entry (excess vs equal-weight liquid universe, %)

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|---|---|---|
| strong growth | discovery | 522 | 35 | 1.19 | 0.9 | 53.3 | 0.79 | 0.24 |
| strong growth | holdout | 1062 | 37 | 0.36 | -1.07 | 44.7 | -1.18 | -0.59 |
| growth | discovery | 831 | 38 | -0.15 | -1.13 | 44.4 | 0.07 | -1.11 |
| growth | holdout | 1441 | 34 | -0.64 | -1.27 | 42.7 | -0.74 | -1.59 |
| decline | discovery | 380 | 31 | -0.48 | -1.08 | 45.3 | -0.91 | -1.44 |
| decline | holdout | 601 | 34 | -0.61 | -1.27 | 42.1 | -1.81 | -1.57 |
| collapse | discovery | 375 | 41 | -0.09 | -1.03 | 43.7 | -0.68 | -1.05 |
| collapse | holdout | 563 | 34 | -0.89 | -1.58 | 41.2 | -1.7 | -1.84 |
| all | discovery | 2108 | 58 | 0.13 | -0.79 | 46.6 | -0.95 | -0.82 |
| all | holdout | 3667 | 39 | -0.38 | -1.27 | 43.0 | -2.47 | -1.34 |

## 60 sessions after entry (excess vs equal-weight liquid universe, %)

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|---|---|---|
| strong growth | discovery | 522 | 35 | 1.3 | 0.06 | 50.2 | 0.89 | 0.34 |
| strong growth | holdout | 776 | 33 | 0.98 | -1.78 | 45.6 | -2.34 | 0.03 |
| growth | discovery | 829 | 37 | -0.31 | -1.95 | 44.1 | 0.42 | -1.26 |
| growth | holdout | 1167 | 30 | -0.96 | -2.39 | 41.5 | -1.33 | -1.92 |
| decline | discovery | 379 | 30 | -0.18 | -3.09 | 41.2 | -2.31 | -1.14 |
| decline | holdout | 501 | 29 | -0.86 | -2.46 | 41.9 | -2.17 | -1.81 |
| collapse | discovery | 373 | 41 | 0.2 | -1.02 | 44.2 | -2.08 | -0.76 |
| collapse | holdout | 454 | 30 | -1.77 | -4.89 | 41.6 | -1.87 | -2.73 |
| all | discovery | 2103 | 57 | 0.2 | -1.35 | 45.1 | -1.91 | -0.75 |
| all | holdout | 2898 | 35 | -0.55 | -2.58 | 42.7 | -3.57 | -1.51 |

## Strong growth − collapse, weekly spread (60 sessions)

| period | weeks | spread | t_nw |
|---|---|---|---|
| discovery | 28 | 5.79 | 2.01 |
| holdout | 29 | 0.18 | 0.32 |

## Descriptive: strong growth by price reaction (60 sessions, both halves together)

| split | events | avg_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|
| reaction ≥ +2% | 465 | 2.54 | 50.3 | 1.04 | 1.58 |
| reaction < +2% | 833 | 0.31 | 45.9 | -0.38 | -0.64 |

## Caveats (from the plan)

- Universe: every NSE EQ name with median turnover ≥ ₹1 cr since Jan 2024 whose filings NSE still serves; companies NSE no longer serves are missing (those that stopped trading are counted above).
- Short history: about eight quarters with growth per company, so both halves are small.
- A year-ago quarter revised after the current filing leaks slightly (rare, not corrected).
