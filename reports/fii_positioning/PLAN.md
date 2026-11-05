# Does FII index-futures positioning predict NIFTY? Pre-registered plan

Written 2026-10-12 00:05 IST, before any result. Script: `scripts/fii_positioning_study.py`.

## Data
- **Positioning:** NSE participant-wise OI (`nse_participant_oi`), FII index futures long and short contracts,
  Oct 2019 → Oct 2026. The file for day t is published that evening, so it is known at t's close.
- **Market:** NIFTY 50 close (`market_index_daily`).
- **Target:** the NIFTY return from close(t+1) to close(t+1+h), for h = 5 and 20 sessions. It starts the day
  after the signal so it is tradable, and it excludes day t.

## Signals (fixed)
- **S1 · flow:** the 5-session change in FII net index futures (long − short), in contracts.
- **S2 · positioning extreme:** the FII long ratio (long ÷ (long + short)) vs its own trailing 250-session range
  (percentile rank, using past values only).

## Hypotheses and pass bars
- **H1 (flow follows informed money):** forward 20-session NIFTY return after S1 in its top tercile minus after
  its bottom tercile is > 0. The terciles use expanding cut-offs (past data only). It must have Newey-West
  t ≥ 2.0 (lags 20) over the full sample and the same sign in both halves (Oct-2019→2022, 2023→2026).
- **H2 (contrarian extreme):** forward 20-session NIFTY return when S2 is in the bottom 10% of its trailing year
  minus the unconditional mean is > 0, with t ≥ 2.0 (lags 20) and the same sign in both halves.

5-session results are reported as secondary. One market and ~1,700 overlapping days is a small sample: a PASS
here would be a candidate for a regime input, not a trading rule.
