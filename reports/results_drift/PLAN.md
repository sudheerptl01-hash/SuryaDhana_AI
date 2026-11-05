# Post-results drift on NSE: pre-registered plan

Written 2026-10-11, **before** any result was computed. The study script (`scripts/results_drift_study.py`) must
follow this plan unchanged; anything else it reports is labelled exploratory.

## Question
After a quarterly result, does an NSE stock keep moving in the direction of its results-day reaction
(post-earnings announcement drift, PEAD)? Earlier research skipped this ("no earnings dates in DB",
`reports/idea_lab/REPORT.md`). Release timestamps are now in `nse_results`.

## Data
- **Releases:** `nse_results` (NSE `corporates-financial-results` + `integrated-filing-results`). The earliest
  broadcast per quarter-end is the release.
- **Symbols:** the union of the 300 most traded EQ stocks in each calendar year 2014–2025, including names that
  were later delisted. This avoids picking today's survivors.
- **Prices:** the NSE bhavcopy panel, split/bonus adjusted (`shared.nse_panel`).

## Event definition
- **Reaction session R:** the release's own session if it came before 15:30 IST on a trading day; otherwise the
  next session.
- **Tradable:** at R−1 the stock is EQ, priced ≥ ₹20, with a 20-session median turnover ≥ ₹5 crore.
- **Reaction excess:** the stock's close(R−1)→close(R) return minus the equal-weight return of the liquid
  universe over the same session.
- **Buckets:** fixed cut-offs (no look-ahead, no quantiles):
  - strong up: reaction excess ≥ +5%
  - up: +2% to +5%
  - flat: −2% to +2%
  - down: −5% to −2%
  - strong down: ≤ −5%
- **Entry:** the open of R+1 (the first price you could actually trade at after seeing the reaction).
- **Forward excess:** the stock's open(R+1)→close(R+h) return minus the same for the equal-weight liquid
  universe, for h = 20 and 60 sessions.
- **Costs:** ICICI MoneySaver round trip at ₹50,000 from `shared.trading_costs`.

## Periods
- Discovery: entries 2015-01-01 → 2021-12-31.
- Holdout: entries 2022-01-01 → the last entry with 60 sessions of data.

## Inference
- Each bucket's events are averaged by entry week.
- The t-statistic of the weekly means uses Newey-West with lags = horizon in weeks (4 for 20 sessions,
  12 for 60), the same helper as the held-overnight study.

## Hypotheses and pass bars
1. **H1 (drift after strong good news):** strong-up 60-session excess > 0 in both periods, NW t ≥ 2.0 in
   discovery, and holdout excess minus costs > 0.
2. **H2 (drift after strong bad news):** strong-down 60-session excess < 0 in both periods, with NW t ≤ −2.0 in
   discovery. Usable as an avoid filter, since the book cannot short.
3. **H3 (spread):** strong-up minus strong-down 60-session excess > 0 in both periods.

20-session results are reported as secondary. Splits by timing, liquidity, gap-and-hold, and reaction size
inside the buckets are exploratory.
