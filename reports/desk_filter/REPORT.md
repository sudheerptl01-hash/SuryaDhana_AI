# Decision Desk candidate filter: avoid non-institutional bulk buys

Generated 2026-09-28 23:23. Window 2019-11-01 → 2026-09-28, ₹500,000 capital, 66% equity share + liquid fund, ICICI costs and taxes.

## Performance

| Run | Period | CAGR % | Max DD % | Sharpe | Vol % |
|---|---|---|---|---|---|
| approved rules | full | 18.52 | -13.75 | 0.98 | 12.47 |
| approved rules | discovery | 26.22 | -13.75 | 1.36 | 13.76 |
| approved rules | holdout | 3.87 | -7.91 | -0.17 | 9.18 |
| + avoid bulk buys (20 sessions) | full | 18.72 | -12.4 | 0.99 | 12.44 |
| + avoid bulk buys (20 sessions) | discovery | 26.48 | -12.4 | 1.38 | 13.75 |
| + avoid bulk buys (20 sessions) | holdout | 3.95 | -7.65 | -0.16 | 9.09 |
| + avoid bulk buys (60 sessions, sensitivity) | full | 18.55 | -13.24 | 0.99 | 12.36 |
| + avoid bulk buys (60 sessions, sensitivity) | discovery | 25.88 | -13.24 | 1.35 | 13.69 |
| + avoid bulk buys (60 sessions, sensitivity) | holdout | 4.52 | -6.81 | -0.1 | 8.96 |

## Activity

| Run | Months with a blocked name | Blocked name-months | Fees ₹ | Taxes ₹ |
|---|---|---|---|---|
| approved rules | 0 | 0 | 238,997 | 344,715 |
| + avoid bulk buys (20 sessions) | 82 | 446 | 245,835 | 348,178 |
| + avoid bulk buys (60 sessions, sensitivity) | 83 | 1243 | 240,066 | 346,198 |

## Names the 20-session filter kept out (31)

Median next-month return of the skipped names: -4.23% (mean -1.01%, 17 of 31 negative).

## Verdict

PASSES the pre-registered test (holdout CAGR not lower and drawdown not deeper).

Adoption still needs the owner's review: CLAUDE.md trading rules change only after review.
