# Held-overnight study — findings (H1–H6, updated 2026-09-28)

Pre-registered tests in `scripts/held_overnight_study.py`; full tables in `REPORT.md` (regenerated each run).

**Data.** NSE bhavcopy with delivery (Oct-2019 → Sep-2026, 3,756 stocks incl. delisted), F&O OI per stock,
120,520 bulk-deal records, 79,851 insider (PIT) disclosures with an intimation date, 2.07 million MTF rows
(from Jan-2022), 5,465 quarterly shareholding filings (FPI / MF / retail / HNI parsed for 2021–2026).

**Method.** Entry at the next open after the data is public. Excess = trade return minus random picks from
the same universe on the same date (H4–H6: random picks of similar liquidity). Round-trip cost 0.95% on
₹50,000. One observation per week; because 20- and 60-day holding windows overlap, verdicts use a
Newey-West t (`t_nw`), which is stricter than the plain weekly t reported earlier. A result counts only if it
has the same sign and |t_nw| ≥ 2 in both periods: discovery 2019-10…2023-12, holdout 2024-01…2026-09
(H5: split at mid-2024 because MTF data starts in 2022).

## Verdicts (pre-registered)

| Hypothesis | Result | Detail (discovery / holdout) |
|---|---|---|
| H1 · Delivery surge + rising price | **No edge** | 5-day excess −0.04% / −0.28%; plain momentum with ordinary delivery did no worse. |
| H2 · Long build-up continues, short covering does not | **No edge** | Long build-up 5-day −0.74% (t_nw −3.0) then +0.03%: not stable. Other classes: nothing consistent. |
| H3 · MF / insurer bulk-deal net buying | **Promising, not proven** | 20-day +0.96% / +1.34%, same sign, t_nw 0.7 / 1.9, 129 + 227 events. |
| H3 · Bulk-deal net buying by everyone else | **Negative, borderline in the holdout** | 20-day −2.22% / −1.23%, t_nw −2.5 / −2.0; beat random only 40% / 43% of the time. Plain weekly t was −2.7 / −2.3. |
| H4 · Insider open-market purchases ≥ ₹10 lakh | **Strongest candidate, not proven** | 20-day +1.01% / +2.58% (t_nw 1.7 / 1.7); 60-day +4.40% / +2.71% (t_nw 2.6 / 0.9); 726 / 175 events. Holdout 20-day excess clears costs (+1.63% after costs). |
| H4 · Insider open-market sales | **No signal** | 20-day +0.37% / +0.36%, 60-day ≈ 0. |
| H5 · MTF leverage surge near the 52-week high | **No edge** | 20-day +0.44% / −0.16% vs +0.52% / +0.27% for names near the high with ordinary MTF growth; share of ≥ 10% drops 9.5% / 12.6% vs 8.7% / 13.3%. |
| H6 · Accumulation (holders down, FPI + MF up > 0.5 pp) | **No edge beyond filing-season timing** | 20-day +1.18% / +2.57% (t_nw 0.9 / 2.7); 60-day +2.13% / +2.83% (t_nw 1.8 / 2.6). Fails the both-periods rule, and the control below explains most of the holdout number. |
| H6 · Distribution (holders up > 5%, FPI + MF down) | **Rejected** | Did not lag: 20-day +0.31% / +0.09%, 60-day −0.29% / +3.77%. |

None of the six produces a buy signal that beats random picks after costs in both periods with
confidence. The robust uses are a filter (H3) and one candidate to track forward (H4).

**Correction (2026-09-29): coverage bias in H4 and H6.** Insider and shareholding data were fetched only
for the 319 stocks liquid in 2026, a set chosen with hindsight: in 2019–2023 those names beat the universe
by +0.21% per 20 sessions while the rest lagged by −0.27% (`reports/ml_labels/FINDINGS.md` §5). H4's and
H6's excess against random picks is therefore overstated. The within-set comparisons below (insider buys
vs sales in the same weeks; accumulation vs other filers) are the fair numbers, and H4 still holds on them.
H3 (bulk deals) and H1, H2, H5 use market-wide files and are unaffected.

## Exploratory checks (not pre-registered; they only qualify the verdicts above)

**H3b · who drives the negative bulk-buy result?** (name-based split, chosen after seeing H3)

| Buyer type | 2019–23 excess 20d | t | 2024–26 excess 20d | t |
|---|---|---|---|---|
| Foreign / fund-like | −2.67% | −2.5 | −1.84% | −2.7 |
| Companies, brokers, LLPs | −3.33% | −3.2 | −0.91% | −1.1 |
| Individuals | −2.02% | −1.1 | −0.01% | 0.0 |

A plausible mechanism is large placements after a run-up adding supply. Retest as its own hypothesis on
fresh data.

**H4 · is it timing or information?** Insiders can trade only when the trading window reopens after
results, so insider *sales* in the same week are a fair control for timing.

| Cut (plain weekly t) | 20-day discovery | 20-day holdout | 60-day discovery | 60-day holdout |
|---|---|---|---|---|
| Buys minus same-week sales | +1.05% (t 1.6) | +1.67% (t 1.2) | +4.43% (t 2.7) | +2.39% (t 0.9) |
| Without Feb–Jun 2020 (COVID-crash buying) | +1.26% (t 2.3) | +2.58% (t 2.3) | +4.29% (t 3.1) | +2.71% (t 1.4) |
| First buy per stock per 90 days | +2.15% (t 3.0, n 198) | +3.06% (t 2.3, n 58) | +5.25% (t 3.3) | +4.18% (t 1.6) |
| Without the 5 most frequent stocks | +0.99% (t 1.6) | +3.19% (t 2.7) | +1.68% (t 1.3) | +4.16% (t 1.7) |

The buy signal survives every cut and beats same-week sales, so it is not just results-season timing.
It is concentrated: 901 events in 93 stocks, GRASIM alone 91, and the top five stocks hold 31% of events.
"First buy per stock per 90 days" (fresh insider buying) is the cleanest version. Call it **H4b**: it is
now pre-registered to be tracked forward on data from Oct-2026, because both historical periods
have been seen.

**H6 · is it ownership or the filing season?** Shareholding filings arrive in results season. Against
every other consecutive-quarter filing broadcast in the same week (same liquidity-matched baseline):

| Horizon | Accumulation | Other filings, same weeks | Paired weekly difference |
|---|---|---|---|
| 20-day, discovery | +1.18% | +0.34% | +0.64% (t 0.3) |
| 20-day, holdout | +2.57% | +1.12% | +0.47% (t 0.4) |
| 60-day, discovery | +2.13% | +1.20% | +0.04% (t 0.0) |
| 60-day, holdout | +2.83% | +1.35% | +0.45% (t 0.3) |

Most of the accumulation "edge" is the week the filing lands, which every filer shares. Clustering by
calendar quarter tells the same story: discovery t 1.2, holdout positive in all 11 quarters but on 11
observations.

## Decision Desk candidate filter (`reports/desk_filter/REPORT.md`)

Rule: do not open new positions in stocks that a non-institutional client net-bought through a bulk deal
in the last 20 sessions; held names are not force-sold. Approved rules otherwise; ₹5 lakh, 66% equity
share + liquid fund, ICICI costs and taxes, Nov-2019 → Sep-2026.

| Run | Full CAGR / max DD | Holdout (Jul-2024 →) CAGR / max DD |
|---|---|---|
| Approved rules | 18.52% / −13.75% | 3.87% / −7.91% |
| + filter, 20 sessions (candidate) | 18.72% / −12.40% | 3.95% / −7.65% |
| + filter, 60 sessions (sensitivity) | 18.55% / −13.24% | 4.52% / −6.81% |

It passes the pre-registered test (holdout CAGR not lower, drawdown not deeper). The effect is small: the
filter changed the portfolio 31 times in seven years; the skipped names' median next-month return was
−4.23%. It is built into the Desk and **OFF** (`DESK_AVOID_BULK_BUY_DAYS=0`) until the owner reviews it;
turning it on means setting that variable to 20 and restarting ui-api. It does not change the bigger
picture: the approved rules returned 3.9% a year in the holdout, below a liquid fund.

## What this means for trading

- Tested and dropped as swing signals: delivery surge (H1), OI build-up (H2), MTF leverage (H5), ownership
  drift (H6). Don't re-pitch them without new evidence.
- Filter: skip recent non-institutional bulk-deal buys (H3); Decision Desk version awaits owner review.
- Track forward, paper only: fresh insider buying (H4b) and MF / insurer bulk buys (H3). Re-evaluate when
  each has at least 100 new events after Oct-2026.

## Data notes

- Shareholding XBRL comes in three layouts (2019–21: one FPI line; 2022–24: FPI Category I/II spelt
  "Catergory"; 2025+: `_ContextI` contexts with fractions). The parser reads all three; the layout-change
  quarters show no jump in the cross-section. Files are cached gzipped in `data/nse_archive/shareholding_xbrl/`.
- 45 filings have no XBRL at NSE (listed as `…/xbrl/-`).
- Insider disclosures contain typo dates (years 1925, 2028): events are kept only when the intimation date
  is 0–30 days after the trade and inside the price data.
