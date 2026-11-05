# Earnings-growth drift: findings

Study run 13 Oct 2026, 15:59, on the plan pre-registered at 15:00 the same day (`PLAN.md`). The full tables are
in `REPORT.md`; script: `scripts/earnings_growth_drift_study.py`.

**Verdict (final, 13 Oct 22:11): NO EDGE.** The pre-registered broad re-run (PLAN addendum, below) supersedes the
first run's PROMISING. Nothing changes in the Desk or the UI.

## Broad re-run (supersedes the first run)
Run 13 Oct 2026, 22:11, under the addendum written at 16:25 before any broad data was read. Same script, buckets,
horizons, split, costs and pass rules. 1,832 companies' filings were read; **1,142** had at least one filing with a
year-ago quarter that was tradable at entry (price ≥ ₹20, turnover ≥ ₹5 cr), giving 5,785 filings (entries Jul 2023 →
Oct 2026). 16 of those companies have since stopped trading. Tables: `broad/REPORT.md`.

| 60 sessions | Discovery (before Jul-2025) | Holdout (Jul-2025 →) | Rule | |
|---|---|---|---|---|
| Whole sample vs universe | +0.2% | −0.6% | (bias check) | the selection bias is gone |
| H1 strong growth | +1.3%, t 0.89 | +1.0%, weekly t −2.34, +0.03% after costs | t ≥ 2 and > 0 in both | **FAIL** |
| H2 collapse | +0.2% | −1.8%, t −1.87 | negative both, t ≤ −2 | FAIL |
| H3 strong growth − collapse | +5.8%, t 2.01 | +0.2%, t 0.32 | positive both | passes, but nothing in holdout |
| Addendum: strong growth vs same-week filings | +2.2% weekly (t 1.95) | +0.3% weekly (t 0.74) | positive both | positive, not significant |

**Reading:** once the companies that shrank, slipped or delisted are included, strong reported growth does not
beat the market after the reaction: about +1% over 60 sessions before costs, about zero after one round trip, and
its median filing lags. The first run's +3.7% / +6.4% was the selection bias it warned about. The addendum's rule
(H1 must pass on the broad run for anything above PROMISING) gives **NO EDGE**. Descriptive only: strong growth
*with* a ≥ +2% price reaction averaged +2.5% (t 1.0, n = 465).

The forward test planned below is dropped: the broad sample already covers it with more data.

---

## First run (13 Oct 15:59, today's liquid names only) — superseded

**Its verdict was: PROMISING, not a PASS. Forward test only; nothing changes in the Desk.**

## What was tested
1,691 quarterly results filings (241 companies, entries May 2024 → Oct 2026), bucketed by what the numbers said:
profit and revenue vs the same quarter a year earlier, read from each filing's XBRL. Entry at the open after the
reaction session, exit 20 / 60 sessions later, excess vs the equal-weight liquid universe, ICICI costs (0.95%
round trip at ₹50,000).

## Pre-registered results (60 sessions)
| | Discovery (before Jul-2025) | Holdout (Jul-2025 →) | Rule | |
|---|---|---|---|---|
| H1 strong growth (profit ≥ +30%, revenue ≥ +10%) | +3.7%, t 2.93 | +6.4%, t 8.04, +5.4% after costs | t ≥ 2 and > 0 in both | **passes as written** |
| H2 collapse (profit ≤ −30% or to loss) | **+4.7%**, t 0.50 | **+4.6%**, t 4.16 | negative both, t ≤ −2 | FAIL |
| H3 strong growth − collapse | −1.6%, t −0.53 | +3.2%, t 3.05 | positive both | FAIL |

## Why H1's pass is not believed
- **Every bucket beats the universe**, including the companies whose profit collapsed (+4.6% to +4.7% over 60
  sessions). The whole sample averages +2.6% / +4.1%. That is the selection bias named in the plan: the companies
  whose filings were read are today's liquid names (market-map top 250, the Desk's momentum list, your holdings),
  i.e. stocks that did well over this window. Measured against the universe, anything in this sample looks good.
- The pre-registered within-sample test (H3) fails in discovery.
- **Exploratory** (added after seeing the results, so it cannot rescue the verdict): strong growth vs the same-week
  average of all sampled filings removes the shared bias. Result: **+1.3% (t 0.47) in discovery, +2.2% (t 2.77)
  in holdout** over 60 sessions. _(Correction, 13 Oct 21:50: those averages weight every filing equally while the t
  is on weekly averages; on weekly averages, as the plan's statistics use, they are +0.8% and +2.4%. Same t, same
  reading. The script now prints both: `within_sample`.)_ Collapse vs the same-week sample: +2.3% (t 0.89) / −0.3%, so there is no avoid signal.

## What it means
- A possible small edge for strong reported growth (≈ +2% over 60 sessions vs comparable stocks), seen only in
  the most recent 15 months: about +1.2% after one round trip of costs, and with no support in the discovery
  period. Not enough to act on.
- Descriptive: strong growth **and** a positive price reaction (≥ +2% vs market) did best (+8.5% vs universe,
  n = 165), but this has the same selection caveat.
- A fair test needs the filings of **all** listed companies, including those that later shrank or delisted. The
  FA cache can be widened to the full ~2,000 EQ names (about 3.5 hours of polite reading), which would remove most
  of the bias. Proposed, not run.

## Forward test (from today)
Q2 FY27 results (filed from 8 Oct 2026) are out-of-sample. Re-run the script after the season plus 60 sessions
(mid-January 2027) and read the within-sample (same-week) line for strong growth. Promote only if it is positive
with t ≥ 2 on that fresh data.
