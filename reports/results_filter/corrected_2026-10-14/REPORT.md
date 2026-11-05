# Decision Desk candidate filter: skip stocks after bad results

Plan: `PLAN.md` (pre-registered). Events: results reactions ≤ −5 % vs the market (`reports/results_drift/events.csv`).

Generated 2026-10-14 02:54. Window 2015-03-01 → 2026-10-13, ₹500,000 capital, 66% equity share + liquid fund, ICICI costs and taxes.

## Performance

| Run | Period | CAGR % | Max DD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| approved rules | full | 13.21 | -22.0 | 0.61 | 12.31 |
| approved rules | discovery | 15.56 | -22.0 | 0.75 | 12.97 |
| approved rules | holdout | 3.98 | -7.9 | -0.16 | 9.13 |
| + skip after bad results (60 sessions) | full | 13.16 | -22.0 | 0.61 | 12.28 |
| + skip after bad results (60 sessions) | discovery | 15.53 | -22.0 | 0.75 | 12.95 |
| + skip after bad results (60 sessions) | holdout | 3.86 | -7.91 | -0.17 | 9.07 |
| + skip after bad results (20 sessions, sensitivity) | full | 13.17 | -22.0 | 0.61 | 12.3 |
| + skip after bad results (20 sessions, sensitivity) | discovery | 15.52 | -22.0 | 0.75 | 12.96 |
| + skip after bad results (20 sessions, sensitivity) | holdout | 3.92 | -7.92 | -0.16 | 9.13 |

## Activity

| Run | Months with a blocked name | Blocked name-months | Fees ₹ | Taxes ₹ |
|---|---|---|---|---|
| approved rules | 0 | 0 | 382,927 | 497,686 |
| + skip after bad results (60 sessions) | 132 | 2137 | 380,325 | 488,833 |
| + skip after bad results (20 sessions, sensitivity) | 88 | 717 | 381,994 | 494,855 |

## Names the 60-session filter kept out (32)

Median next-month return of the skipped names: 0.90% (mean 3.38%, 15 of 32 negative).

## Verdict

FAILS the pre-registered test (holdout CAGR lower or drawdown deeper): do not adopt.

Adoption still needs the owner's review: CLAUDE.md trading rules change only after review.
