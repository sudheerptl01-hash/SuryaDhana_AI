# ML labels and NSE features — findings (2026-09-29)

Study: `scripts/ml_label_study.py` (rules pre-registered in its docstring before any model was fitted);
auto-generated tables in `REPORT.md`. Universe = the Decision Desk's (300 most liquid EQ stocks each date),
survivorship-free NSE panel 2010 → 2026, weekly signals, entry at the next open, LightGBM with fixed
parameters, walk-forward refits every January, test years 2013 → 2026. Costs 1.0% round trip (₹25,000 a position).

## 1. What is wrong with the v2 labels (`feature_engine.build_labels_v2`, table `ml_labels`)

| Problem | Evidence (Desk universe, weekly, 2013–2026) |
|---|---|
| The up/down label mostly records the market's direction | In 42.6% of weeks more than 70% or fewer than 30% of stocks share one label; 26% of 5-day return variance is the common market move. A model trained on it learns market timing, not which stock to own. |
| The cost hurdle is 0.15%; real costs are ≈ 1.0% | 16.4% of "UP" labels are trades that lose money after costs. |
| The ±2% triple barrier is inside daily noise | Median daily volatility is 2.19%, so 96.3% of 5-day windows touch a barrier. 5.8% touch both on the first day and are scored as a stop: 20MICRONS on 17-May-2021 is labelled −1 although it rose 41% in five days. |
| Yahoo-only, current listings, from Sep-2020 | 6.2% of universe rows since 2021 are stocks the labels never had (they later underperformed: −0.20% per 20 days). NSE's own panel goes back to 2010 with delisted stocks: 4× the history and five more drawdowns. |
| 5-day horizon | The only live strategy is monthly; at 5 days costs dominate (see the weekly books below). |

One suspicion did not hold: entering at the close instead of the next open barely matters at 5 days
(the two returns correlate 0.96).

## 2. Better labels (pre-registered comparison, same features and model)

| Label | IC vs 20-day excess (t) | IC 2024+ (t) | Monthly top-20 net excess / yr | 2024+ | Turnover | Costs / yr |
|---|---|---|---|---|---|---|
| A0 v2 (5-day close > 0.15%) | 0.059 (7.6) | 0.047 (2.7) | +1.0% | −8.3% | 0.71 | 8.5% |
| A1 5-day next-open excess, ranked | 0.071 (6.7) | 0.052 (2.5) | +1.3% | −10.1% | 0.69 | 8.3% |
| **A2 20-day next-open excess, ranked** | **0.072 (5.6)** | **0.054 (2.3)** | **+6.7%** | **−4.6%** | 0.52 | 6.3% |
| Desk momentum score (baseline) | 0.047 (4.4) | 0.027 (1.4) | +13.0% | −4.2% | 0.27 | 3.2% |

Rebalanced weekly instead, the v2-label book loses 17.7% a year to the universe (costs 31% a year); the
momentum book still makes +11.9% because its ranking barely changes.

**Verdict: A2 beats A0 on all four pre-registered measures.** For any stock-selection model the label
should be the 20-session return from the next open, minus the universe's return, ranked within each date,
computed on the survivorship-free NSE panel (`shared/xs_labels.py`).

## 3. ML ranking vs the Desk's momentum score

**Verdict: does not pass.** The A2 model ranks better on average (IC 0.072 vs 0.047) but its top-20 book
is worse net of costs (+6.7% vs +13.0% a year; −4.6% vs −4.2% since 2024). Two reasons, both measured:

| Score decile | Bottom | 2 | 5 | 9 | Top |
|---|---|---|---|---|---|
| A2 model, 20-day excess | −0.84% | −0.15% | −0.08% | +0.53% | +0.79% |
| Momentum, 20-day excess | −0.66% | −0.38% | −0.33% | +0.64% | **+1.25%** |

- The model's skill is in spotting losers (high beta, high volatility, illiquid, near 52-week lows: its top
  features). A long-only book only uses the top of the list, where momentum is stronger.
- Its picks change twice as often (52% of the book a month vs 27%), costing 6.3% a year instead of 3.2%.

## 4. NSE positioning data as ML features

Built point-in-time in `shared/xs_features.py` (publication lags: MTF T+1, insider by intimation date,
shareholding by broadcast date; unknown periods are NaN, never zero).

| Added to the technical features (label A2, 2021–2026) | IC gain (t) | Monthly net book |
|---|---|---|
| Market-wide: delivery, F&O OI and put/call OI, bulk deals, MTF | −0.001 (−0.2) | +0.7% → −0.4% |
| Per-company: insider trades, shareholding changes (covered stocks only) | +0.006 (0.6) | +12.0% → +10.7% |

**Verdict: no measurable value as model inputs.** Alone, three of 22 features pass |t| ≥ 2 (about one is
expected by chance): non-institutional bulk buying −0.016 (t −3.2, the same result as H3 and the Desk's
candidate filter), fresh insider buying +0.016 (t 2.5, consistent with H4b), put/call OI ratio +0.024
(t 2.4, new and untested). They work better as the explicit rules already built than inside a model.

## 5. Coverage bias (a correction to the held-overnight study)

Insider and shareholding data were fetched for the 319 stocks liquid in 2026. That set is chosen with
hindsight: in 2019–2023 these names beat the universe by +0.21% per 20 sessions while the rest lagged by
−0.27%, and a model trained and tested inside the set shows +12% a year, mostly survivorship. So the
H4 and H6 excess returns against random picks are overstated; their within-set comparisons (insider buys
vs sales, accumulation vs other filers) are the fair numbers. Fix, if these data are used again: fetch
filings for every stock that was ever in the universe (1,018), so coverage is known at each date.

## 6. Exploratory lead (post-hoc, not a result)

Chosen after seeing section 3, one of two variants tried: keep momentum for picking, but never newly buy
a stock the A2 model ranks in its bottom 30%.

| Monthly top-20, net vs universe | 2013–2026 | ≤ 2023 | 2024+ | IR | Turnover |
|---|---|---|---|---|---|
| Momentum (Desk) | +13.0% | +17.0% | −4.2% | 0.91 | 0.27 |
| Momentum + model veto | +14.7% | +18.5% | −1.2% | 1.06 | 0.27 |
| 50/50 blend of the two ranks | +10.5% | +13.6% | −2.8% | 0.84 | 0.39 |

The veto helps in 8 of 14 years without adding turnover: the same pattern as every other study in this
project (avoid-filters work, buy signals do not). It needs a pre-registered Desk-level backtest and a
forward paper shadow before it can be considered.

## Recommendations

1. Stop training on the v2 labels (0.15% hurdle, ±2% barrier, 5-day close-to-close). Any stock-selection
   model uses the A2 label, the NSE panel from 2010, and is judged on IC and a top-N book net of costs,
   not accuracy or AUC.
2. Keep the Desk's momentum ranking. Do not replace it with an ML score.
3. Don't feed the NSE positioning data into models; keep the rule-based bulk-buy filter (awaiting review)
   and the H4b forward test.
4. Next experiment: the ML veto, pre-registered, through the full Desk simulator plus a 12-month shadow book.
