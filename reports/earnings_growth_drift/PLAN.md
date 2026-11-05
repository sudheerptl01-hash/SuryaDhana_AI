# Earnings-growth drift on NSE: pre-registered plan

Written Tue 13 Oct 2026, 15:00 IST, **before** the data was assembled (the first full financials sweep runs after
today's close). Nothing below may be changed after the results are seen; anything added later is labelled
exploratory.

## Question
After a company files its quarterly results, does **what the numbers said** (profit and revenue growth vs the
same quarter a year earlier, read from the filing's XBRL) predict the stock's return over the next 20 and 60
sessions, beyond the market, after real costs?

This complements `reports/results_drift` (which bucketed the **price reaction**: bad-reaction drift passed, the
good-news side failed). Here the signal is the **fundamentals**, not the price.

## Data
- Filings: `data/nse_archive/financials/<SYMBOL>.json` (FA cache: up to 12 quarters per company, consolidated
  where filed; filing time = NSE broadcast time of the results XBRL).
- Growth: `financials.with_growth` (profit YoY, revenue YoY; a sign change is "to loss" / "to profit").
  Both inputs (this quarter and the year-ago quarter) were public at the filing time.
- Prices: split/bonus-adjusted NSE bhavcopy panel (`shared.nse_panel.load_panel`) from a snapshot copy of
  `data/market.duckdb`.

## Event, entry, exit (same mechanics as results_drift)
- Reaction session R = the first session that trades on the filing (filed before 15:30 on a session → that
  session; otherwise the next one).
- **Entry at the open of R+1**: the day after the reaction, so the signal is fully public. Exit at the close of
  R+h, h ∈ {20, 60}.
- Excess return = stock return − equal-weight return of the liquid universe over the same window.
- Tradable at entry: EQ series, price ≥ ₹20, 20-day median turnover ≥ ₹5 cr, not an ETF.
- Costs: `shared.trading_costs.default_model().round_trip_pct(₹50,000)` (ICICI MoneySaver, ≈ 0.93% + DP).

## Buckets (fixed now)
| Bucket | Rule |
|---|---|
| strong growth | profit YoY ≥ +30% **and** revenue YoY ≥ +10% |
| growth | profit YoY in [0, +30%), not "strong growth" |
| decline | profit YoY in (−30%, 0) |
| collapse | profit YoY ≤ −30%, or profit turned into a loss |
| (excluded) | no year-ago quarter, or both quarters loss-making |

## Split
- Discovery: entries before 2025-07-01. Holdout: entries on or after 2025-07-01.
- The FA cache reaches back ~3 years, so both halves are short. That is a stated limitation, not a reason to
  move the split.

## Hypotheses and pass rules (60-session horizon decides; 20 is descriptive)
- **H1 (long side):** "strong growth" has positive average excess in **both** halves, Newey-West t ≥ 2.0 in
  discovery (weekly-averaged events, lags = h/5), and holdout excess **after costs** > 0.
- **H2 (avoid side):** "collapse" has negative average excess in both halves with discovery t ≤ −2.0.
- **H3 (spread):** strong growth − collapse (weekly) is positive in both halves.
- Descriptive only: strong growth split by the price reaction (reaction excess ≥ +2% vs below).

## Verdicts
- PASS only if H1 (or H2, for an avoid filter) passes as written. Anything weaker is NO EDGE / PROMISING with a
  forward test, never a rule change.
- Nothing here changes the Decision Desk. A PASS would only be proposed to the owner as a UI flag, as with the
  results-drift avoid flag.

## Known biases (stated up front)
- **Selection / survivorship:** the companies read are today's liquid names plus holdings / Desk / watchlist,
  so delisted and shrunken companies are missing. This flatters long-side results.
- Revisions: a year-ago quarter revised after the current filing would leak a little. This is rare and not corrected.
- Short history (≈ 8 quarters with growth per company): wide confidence intervals.

## Addendum (13 Oct 2026, 16:25: written before the broad data was read)
The first run (15:59) showed every bucket beating the universe: the selection bias named above. To test the same
question without it, the identical script and rules are re-run on a **broad universe**: every NSE EQ symbol with
median daily turnover ≥ ₹1 cr since Jan-2024 (1,821 companies, including any that have since stopped trading;
the count is reported), once their filings are read (13 Oct evening sweep).
- Same buckets, horizons, split, costs and pass rules (H1–H3). Reported separately as `broad/REPORT.md`.
- Decision rule fixed now: the broad run supersedes the first for the verdict. **H1 must pass on the broad run**
  (and the within-sample same-week check must be positive in both halves) for anything stronger than PROMISING.
- Delisted companies whose filings NSE no longer serves stay missing; their count is reported.
