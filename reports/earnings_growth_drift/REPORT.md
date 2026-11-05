# Earnings-growth drift: report

Run 2026-10-13 15:59 · plan: PLAN.md (pre-registered 13 Oct 2026, 15:00) · 1691 filings from 241 companies · entries 2024-05-07 → 2026-10-12 · round-trip cost 0.95% at ₹50,000

## Verdict on the pre-registered hypotheses (60 sessions)

- **H1 strong growth drifts up:** PASS
- **H2 collapse drifts down (avoid):** FAIL
- **H3 strong growth − collapse spread positive in both halves:** FAIL

## 20 sessions after entry (excess vs equal-weight liquid universe, %)

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|---|---|---|
| strong growth | discovery | 170 | 24 | 0.15 | 0.74 | 52.9 | -0.6 | -0.8 |
| strong growth | holdout | 358 | 30 | 2.63 | 1.87 | 57.0 | 4.86 | 1.67 |
| growth | discovery | 256 | 26 | 0.29 | -0.42 | 48.4 | -0.48 | -0.67 |
| growth | holdout | 456 | 32 | 0.84 | 0.15 | 51.3 | 0.78 | -0.12 |
| decline | discovery | 99 | 20 | 0.6 | 0.84 | 52.5 | 1.18 | -0.35 |
| decline | holdout | 149 | 31 | 0.7 | -0.35 | 48.3 | 0.47 | -0.25 |
| collapse | discovery | 79 | 21 | 1.36 | 0.75 | 51.9 | 0.98 | 0.41 |
| collapse | holdout | 123 | 29 | 1.11 | 0.69 | 50.4 | 1.17 | 0.16 |
| all | discovery | 604 | 31 | 0.44 | 0.3 | 50.8 | -0.61 | -0.51 |
| all | holdout | 1086 | 33 | 1.44 | 0.55 | 52.7 | 2.31 | 0.49 |

## 60 sessions after entry (excess vs equal-weight liquid universe, %)

| bucket | period | events | weeks | avg_excess | median_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|---|---|---|
| strong growth | discovery | 170 | 24 | 3.68 | 1.64 | 58.2 | 2.93 | 2.73 |
| strong growth | holdout | 267 | 25 | 6.39 | 3.86 | 59.6 | 8.04 | 5.43 |
| growth | discovery | 256 | 26 | 1.02 | -0.86 | 46.9 | 0.64 | 0.06 |
| growth | holdout | 375 | 27 | 2.11 | 1.79 | 53.6 | 0.53 | 1.15 |
| decline | discovery | 99 | 20 | 2.9 | 1.16 | 54.5 | 0.86 | 1.95 |
| decline | holdout | 130 | 26 | 4.72 | 2.84 | 61.5 | 2.03 | 3.76 |
| collapse | discovery | 79 | 21 | 4.65 | 1.14 | 55.7 | 0.5 | 3.69 |
| collapse | holdout | 97 | 24 | 4.63 | 4.07 | 55.7 | 4.16 | 3.68 |
| all | discovery | 604 | 31 | 2.55 | 0.65 | 52.5 | 0.09 | 1.6 |
| all | holdout | 869 | 28 | 4.09 | 2.72 | 56.8 | 1.35 | 3.14 |

## Strong growth − collapse, weekly spread (60 sessions)

| period | weeks | spread | t_nw |
|---|---|---|---|
| discovery | 18 | -1.64 | -0.53 |
| holdout | 23 | 3.15 | 3.05 |

## Descriptive: strong growth by price reaction (60 sessions, both halves together)

| split | events | avg_excess | beat_pct | t_nw | excess_after_costs |
|---|---|---|---|---|---|
| reaction ≥ +2% | 165 | 8.5 | 67.3 | 3.05 | 7.54 |
| reaction < +2% | 272 | 3.41 | 54.0 | 2.97 | 2.46 |

## Caveats (from the plan)

- Selection / survivorship: companies read are today's liquid names plus holdings / Desk / watchlist.
- Short history: about eight quarters with growth per company, so both halves are small.
- A year-ago quarter revised after the current filing leaks slightly (rare, not corrected).
