# Evidence → probability: findings (14 Oct 2026)

Plan pre-registered at 18:10 (`PLAN.md`); full tables in `REPORT.md`; script `scripts/evidence_probability_study.py`
(about 90 s). Research only: no trading rule, Desk setting or filter changed.

**The question:** every study in this project tested one idea on its own terms. What does each one say as a
probability, measured the same way? Can the "fails" (avoid) and the "works" (buy) be merged into one buy / sell
probability that holds up out of sample? And how should labels be built for a model?

**The short answer:**
1. **Probability shifts are small.**
   - A liquid NSE stock beats the market average over the next 20 sessions about **45%** of the time. It is not 50%
     because a few big winners pull the average up.
   - The best evidence lifts that to about **50%**; the worst cuts it to about **41%**.
   - The bigger effects show up as "chance of landing in the worst fifth": 32% for the most volatile stocks against
     20% normally.
2. **The avoid side is more reliable than the buy side.** That is the same pattern as every earlier study.
3. **Merging works when done properly.** A logistic merge of all flags ranks stocks about twice as well as momentum
   alone, out of sample, and its probabilities are honest: when it says 33%, it happened 32% of the time.
4. **Use it as a veto, not as the picker.** As a veto on the Desk's momentum picks it helps a little (+0.9 to +1.4
   points a year). As a stand-alone stock picker it does much worse than momentum.
5. **Horizon decides whether it pays.**
   - **5 sessions:** the probabilities are sharpest, but costs eat everything.
   - **20 sessions:** the buy-vs-avoid spread is about one round-trip cost.
   - **60 sessions:** the spread is 3–3.5% against about 1% cost.
6. **Labels:**
   - Use the stock's return **minus the market's**, from the next open, ranked per date.
   - Match the label horizon to the holding period.
   - Prefer 60 sessions for buy / sell probabilities and 20 sessions for the Desk veto.
   - Do not build a 5-day model on delivery costs.

---

## 1. Every condition as a probability (20 sessions, liquid NSE universe, 2011 → Oct 2026)

**How to read these tables:**
- **Universe:** EQ stocks, ≥ ₹20, 20-day median turnover ≥ ₹5 cr, point in time. That is 1,945 stocks over time
  and 391,000 stock-dates (weekly and month-end).
- **P(beat):** the share of flagged stocks that beat the universe average over the next 20 sessions (entry next
  open), with the base on the same weeks next to it. For results, insider and shareholding flags, the base is only
  the stocks those datasets cover.
- **Mean excess:** flagged minus base. Shown as pre-2024 / 2024+ with the Newey-West t.
- **Credibility:** the empirical-Bayes probability that the effect really has this sign.

### What fails: evidence a stock will lag (sell / avoid side)
| Flag | P(beat) flagged vs base | P(worst 20%) | Mean excess, pre / 2024+ (t) | Verdict | Credibility |
|---|---|---|---|---|---|
| Close below its 200-day average | 44.0% vs 45.9% | 19.6% | −0.69% (−5.1) / −0.60% (−3.2) | **Robust** | 100% |
| Within 10% of the 52-week low | 45.0% vs 46.4% | 18.0% | −0.65% (−3.0) / −0.71% (−2.4) | **Robust** | 100% |
| Momentum bottom decile | 41.5% vs 45.1% | 21.0% | −0.51% (−2.0) / −0.92% (−3.1) | Holds (weaker); **Robust at 60 sessions** (−2.2% / −2.2%) | 100% |
| 60-day volatility, top decile | 40.8% vs 45.1% | **32.0%** | −0.79% (−2.6) / −0.49% (−1.4) | Holds (weaker) | 99% |
| Beta, top decile | 42.1% vs 45.0% | 27.0% | −0.31% / −0.37% (n.s.) | No effect on the average; a risk flag | 81% |
| Biggest 1-day gain in 20 days, top decile | 42.7% vs 45.1% | 27.8% | ≈ 0 | No effect on the average; a risk flag | 65% |

Short-horizon avoid flags (they work over **5 sessions**, not 20):

| Flag (5 sessions) | P(beat) flagged vs base | Mean excess, pre / 2024+ (t) | Verdict |
|---|---|---|---|
| Split / bonus ex-date in the last 20 sessions | 40.2% vs 45.4% | −0.80% (−4.2) / −0.95% (−2.4) | **Robust** |
| Upside value-area break, last 5 sessions | 44.1% vs 44.9% | −0.15% (−3.2) / −0.20% (−2.4) | **Robust** |
| Strong bad results (≤ −5% vs market) in the last 5 sessions *(post-hoc)* | **39.2%** vs 45.4% | −0.53% (−2.0) / −0.88% (−4.4) | Holds |
| Burst (≥ +4% on higher volume), last 5 sessions | 43.4% vs 45.1% | −0.09% (−2.1) / −0.10% (−1.7) | Holds (weaker), small |

### What works: evidence a stock will beat the market (buy side)
| Flag | P(beat) flagged vs base | P(worst 20%) | Mean excess, pre / 2024+ (t) | Verdict | Credibility |
|---|---|---|---|---|---|
| Momentum score, top decile (the Desk's signal) | **49.4%** vs 45.1% | 22.7% | +1.32% (5.7) / +0.55% (1.6) | Holds (weaker); weak since 2024 | 100% |
| Strong good results (≥ +5% reaction), last 60 sessions | 48.6% vs 45.1% | 18.7% | +0.39% (1.4) / +0.79% (3.3) | Holds (weaker) | 100% |
| RSI(2) < 5 in a momentum leader | 50.7% vs 45.4% | 17.6% | +1.30% (3.7) / +0.42% (0.9) | No effect at 20; **Robust at 5 sessions** | 100% |
| 52-week-high breakout on volume | 46.0% vs 44.1% | 22.4% | +0.56% (2.2) / +0.15% (0.4) | No effect (sign is +, not −) | 96% |
| ML A2 score, top decile (Desk top 300) | 51.1% vs 46.2% | 16.6% | +0.88% (4.0) / +0.44% (1.3) | Holds (weaker) | — |

- **Over 5 sessions:**
  - **RSI(2) < 5 in a momentum leader** is robust: 53.1% vs 46.1%, +0.49% (t 2.9) / +0.58% (t 2.5).
  - **5-day losers on below-normal volume** hold: +0.14% / +0.30% (t 3.2).
- **Breakouts:** the handbook lost money *trading* breakouts with 1–3 day holds and tight stops. The breakout itself
  is followed by mildly positive drift.

### What has no effect (measured, not assumed)
In liquid stocks over 20 sessions, none of these changes the probability reliably:
- **Bulk deals:** all three kinds.
  - Non-institutional buying was −1.9% (t −2.5) in 2019–23 when fresh, and is gone since 2024: −0.1%.
  - This matters for the bulk-buy filter you have not decided on yet.
- **Insider buys:** right sign (+1.1% / +0.8%) but too few events (t 1.7 / 0.9). Insider sales: nothing.
- **F&O build-ups:** long and short.
- **Put/call OI ratio:** +0.34% (t 2.3) in 2024+ only.
- **MTF crowding.**
- **Shareholding accumulation.**
- **Delivery surge.**
- **Overnight momentum.**
- **Abnormal volume.**
- **Illiquidity.**
- **1- and 4-week reversal** (at 20 sessions).
- **"Any results recently".**

**Bad results, at 20–60 sessions:** strong bad results are weaker in this frame than in `results_drift` (−0.5% to −1%
vs −1.8% to −3.7%). This frame compares them with *comparable covered stocks*; that study used the whole liquid
market, which small caps dominated. The ⚠ BAD RESULTS flag remains a sound short-term warning (5 sessions, above).

**How far to trust "credibility":**
- The shrinkage was fitted on pre-2024 data and used to predict which effects would keep their sign in 2024+.
- **5 sessions:** of the effects given ≥ 80%, 93% kept their sign.
- **20 sessions:** 75%.
- **60 sessions:** only 59%. Long-horizon effects are less stable: fewer independent observations, and regimes
  change.

## 2. Merging them into one probability

**Three ways, refit every January from 2016, tested on the following year:**
- **A:** momentum alone.
- **B:** scorecard: add each flag's (shrunk) log-odds.
- **C:** logistic regression on every flag plus momentum.

| 20 sessions (pre-registered) | A momentum only | B scorecard | **C logistic merge** |
|---|---|---|---|
| Rank IC of P(beat), 2016–2026 (t) | 0.036 (3.3) | 0.057 (5.2) | **0.062 (6.1)** |
| Same, 2024+ | 0.035 (2.1) | 0.063 (3.5) | **0.059 (4.0)** |
| Calibration slope of P(worst 20%), 2024+ | 0.48 | 0.38 (says 29%, truth 20%) | **0.98** |

- **The naive scorecard is overconfident about losers.** Volatility, beta, lottery spikes, bursts and overnight
  jumps are one risk counted five times. Adding them up says 29% where 20% happened. The logistic merge corrects for
  that.
- **Pre-registered tests, C vs A:**
  - **Ranking:** gain +0.026 IC, t 4.2 overall and 2.9 in 2024+ → **PASS**.
  - **Calibration:** slope 0.84 for P(beat) and 0.98 for P(worst 20%) in 2024+, Brier skill > 0 → **PASS**.
- **What a predicted probability meant, 2024+ (model C):**
  - P(worst 20%) top decile: said 33.2%, happened 31.8%.
  - P(worst 20%) bottom decile: said 14.7%, happened 13.8%.
  - P(beat) top decile: said 49.7%, happened 48.4%.

**Decision buckets (out of sample).**
- **BUY:** P(beat) in the top 10% of that year's training predictions.
- **AVOID:** P(worst 20%) in the top 20%.
- **Excess:** vs the liquid universe. **"After cost":** the stock's own return minus a 0.96% round trip.

| Holding period | Period | BUY: P(beat) / excess | AVOID: P(beat) / excess | BUY minus AVOID | Round trip |
|---|---|---|---|---|---|
| 5 sessions *(post-hoc)* | 2024+ | 49.5% / +0.18% | 42.8% / −0.07% | 0.25% | 0.96% → **loses money** |
| 20 sessions | 2016–23 | 49.7% / +0.75% | 41.4% / −0.41% | 1.2% | 0.96% → about break-even |
| 20 sessions | 2024+ | 49.9% / +0.76% | 41.4% / −0.28% | 1.0% | 0.96% → about break-even |
| 60 sessions *(post-hoc)* | 2016–23 | 52.6% / +2.54% | 40.4% / −0.79% | 3.3% | 0.96% → **pays** |
| 60 sessions *(post-hoc)* | 2024+ | 50.6% / +2.25% | 38.2% / −1.28% | 3.5% | 0.96% → **pays** |

**On the Desk (top 300, monthly, net of costs at ₹25,000 a position, vs the universe):**

| Book | 2016–23 | 2024+ | All | Turnover |
|---|---|---|---|---|
| Momentum (the Desk) | +16.8%/yr | −1.8%/yr | +12.1%/yr | 0.275 |
| Momentum + merged veto (never newly buy C's bottom 30%) | **+17.7%/yr** | **−0.4%/yr** | +13.2%/yr | 0.277 |
| Momentum + ML A2 veto (reference: the earlier lead) | +18.2%/yr | +1.3%/yr | +14.0%/yr | 0.280 |
| Merged probability as the picker (top 20 by C) | +4.9%/yr | +3.1%/yr | +4.4%/yr | 0.446 |

- **The merged veto passes the pre-registered test**: better in both periods, turnover up 0.7%. The gain is
  modest.
- **The ML A2 veto helps more,** but it is not an independent test: the lead was found on the same years.
- **Keep momentum as the picker.** The merged probability picks well across the whole list but not at the very top,
  and it trades 60% more.

**Correction in this run:**
- The first run let the merged model use three coverage flags chosen with hindsight: stocks whose results, insider
  or shareholding data were fetched because they are liquid *today*. The model rewarded that membership: +5 points
  of probability for the 319-stock shareholding set.
- Those flags now stay in training but are neutralised when predicting.
- That run is kept in `first_run_coverage_leak/`. With the leak, the merged veto *failed* (it was steering away from
  small-cap momentum winners).
- The test `test_hindsight_coverage_does_not_change_predictions` guards the fix.

## 3. Is it a good time to own stocks at all? (market level)
| State (2011–23 / 2024+) | Average liquid stock, next 20 sessions | P(that basket rose) | P(a single stock beat its costs) |
|---|---|---|---|
| NIFTY below its 200-day average | +2.18% / +2.44% | 66% / 67% | 54% / 51% |
| NIFTY above it | +0.91% / +0.24% | 61% / 52% | 46% / 42% |
| Weakest breadth (bottom fifth of % above the 50-day) | +2.72% / +3.06% | 60% / 68% | 55% / 56% |

On average, weak markets have been followed by *better* 20-day returns, not worse. The Desk's crash filter is a rule
about surviving the rare deep falls (2020, 2022), not about average returns. This does not argue for removing it,
and nothing changes without your review. As a stand-alone timing signal, "below the 200-day" has been a buy, not a
sell.

## 4. Labels: how to build them

**Measured on the liquid universe, weekly 2011 → 2026; round trip 0.96%:**

| | 5 sessions | 10 | 20 | 60 | 120 |
|---|---|---|---|---|---|
| Share of a stock's move that is just the market | 26% | 26% | 26% | 24% | 23% |
| "Beat the market" labels that still lose money after costs | 26% | 23% | 20% | 16% | 14% |
| Labels inside the ±cost dead zone | 19% | 13% | 9% | 5% | 3% |
| Week-to-week label overlap (persistence) | 0.01 | 0.47 | 0.71 | 0.90 | 0.95 |
| Momentum rank IC vs the label (t) | 0.023 (3.9) | 0.035 (4.4) | 0.047 (4.5) | 0.074 (4.7) | 0.100 (4.5) |
| 5-day reversal IC (t) | **0.033 (7.2)** | 0.021 (4.6) | 0.013 (2.7) | −0.005 | −0.015 (−3.0) |
| Low volatility IC (t) | 0.041 (5.8) | 0.045 (5.0) | 0.050 (4.2) | 0.071 (3.7) | 0.083 (3.0) |
| Momentum top decile held h, net of costs | +6.2%/yr | +10.0% | +11.1% | **+12.6%** | +10.4% |

### Rules that apply at every horizon
1. **Entry at the next open,** exit at an open h sessions later. A signal computed after the close cannot buy that
   close.
2. **Target = the stock's return minus the universe's.** About a quarter of every move is the market. A model trained
   on raw returns learns market timing, which has its own model (§3).
3. **Rank the target per date** (or classify top / bottom fifth). This makes it outlier-proof and the same in bull
   and bear years.
4. **Two targets, not one:** P(top fifth) and P(bottom fifth) behave differently. The avoid side is more reliable.
5. **Horizon = holding period.** Overlapping labels (persistence 0.71 at 20 sessions, 0.90 at 60) mean far fewer
   independent samples than rows. So:
   - sample every h/5 weeks, or weight by uniqueness;
   - purge h + 1 sessions before every test period;
   - refit walk-forward yearly.
6. **Survivorship-free NSE panel from 2010,** delisted exits at the last traded price, windows with data breaks
   dropped (`shared/xs_labels.py`).
7. **Judge a model by rank IC and a net-of-cost top-N book.** Not accuracy or AUC.

### By horizon
| | Short (1–5 sessions) | Swing (20 sessions) | Long (60 sessions) |
|---|---|---|---|
| What predicts it | reversal, RSI(2) dips in leaders, fresh results shocks, split ex-dates | momentum, trend, 52-week position, volatility, good results | the same as swing, stronger: momentum, 52-week high, low volatility |
| Recommended label | **meta-label** a defined setup: 1 if that trade (next open → its exit rule) beats the round-trip cost, else 0. Optional: relative triple barrier ±1·σ√h | **20-session next-open excess, ranked** (the A2 label, already shown to beat the old labels) + a bottom-fifth classifier | **60-session next-open excess, ranked**, sampled every 12 weeks; P(top fifth) / P(bottom fifth) heads |
| Cost reality | 26% of "winning" labels lose money; the best merged BUY bucket earns +0.18% vs 0.96% cost | the BUY − AVOID spread ≈ one round trip | spread 3.3–3.5% vs 0.96% |
| Use | **don't build it on delivery costs.** At most paper-track RSI(2)-leader dips | the Desk veto (passes) | buy / sell probabilities on single stocks |

**Triple-barrier labels** (±1·σ√h on the stock-vs-market line):
- When a barrier is touched, the label agrees with the plain excess sign 92.6–95.4% of the time.
- At 60 sessions momentum predicts it slightly better (IC 0.081 vs 0.074).
- But half the labels are "neither". Use them only if you size positions by them. Ranked excess is simpler and
  about as good.

## 5. Features for a model (what to feed it, point in time)
| Group | Features (continuous, ranked per date) | Evidence here | Notes |
|---|---|---|---|
| Momentum / trend | 6- and 12-month return ÷ volatility (the Desk score), distance from the 52-week high / low, price vs the 200-day | strongest at every horizon | the backbone |
| Risk | 60-day volatility, beta, biggest 1-day gain, Amihud illiquidity | the best "bottom fifth" predictors (32% vs 20%) | they drive the avoid side |
| Short-term price action | 5-day return, RSI(2), bursts, value-area breaks, volume vs average | 5-session effects only | only for short labels |
| Events (days since, not "in window") | results reaction size and days since, split / bonus ex-date, bulk-deal type and days since, insider buys | fresh events work; 60-day windows dilute them | encode *days since* and *size* |
| Market state | NIFTY vs 200-day, breadth, FII positioning | timing, not selection | keep it out of the stock model; give it its own model |
| Coverage | only point-in-time ones (F&O membership, dataset start dates) | — | **never** "is this stock in a dataset fetched today" (the leak found here) |

The earlier ML study (`reports/ml_labels/`) found NSE flow data adds nothing *on top of* technical features. This
study agrees: flows are mostly no-effect in liquid names.

## 6. Today's readings (13 Oct close; research only, not trading advice)
- 889 liquid stocks plus PCJEWELLER scored: 16 BUY, 180 AVOID, 694 neutral.
- **Highest P(beat):** HONASA, ENTERO, FINCABLES, NEULANDLAB, SHILPAMED, UNIMECH, NAVINFLUOR, LAURUSLABS
  (51.7–53.6%). Mostly momentum leaders with strong recent results or an RSI(2) dip.
- **Highest P(worst fifth):** AHCL, MOBIKWIK, UTTAMSUGAR, INDORAMA, PREMIERPOL (42–48% vs 20% normal). Very high
  volatility, lottery-like spikes, retail bulk buying.
- **Your holdings as of 12 Oct** (ICICI now reports none; please confirm if you sold):

  | Stock | P(beat) | P(worst 20%) | Call | Why |
  |---|---|---|---|---|
  | CUPID | 48.9% | 20.3% | neutral | top momentum and at its high, offset by a recent burst |
  | AEROFLEX | 45.2% | 36.3% | AVOID | high volatility and beta, volume spike, upside value-area break |
  | PCJEWELLER | 38.7% | 33.9% | AVOID | high volatility, overnight jumps, delivery surge. Below ₹20, outside the universe the model was fitted on |
  | SYNCOMF | 39.5% | 38.9% | AVOID | high volatility, lottery spikes, illiquid |

## 7. Caveats
- **Weekly sampling.** Daily signals are seen on the week's last session, about 2 days late on average for 5-day
  effects. A daily study could find slightly stronger short-term numbers.
- **Selection.** Several conditions were chosen because earlier studies on 2020–26 found them, so 2024+ is not a
  clean holdout for those. 2011–19 is clean for the price-action ones, and most of them did not hold there.
- **Post-hoc parts are labelled.** The 5- and 60-session merges and the fresh-event flags were added after the first
  run and need forward confirmation.
- **Costs.** The ₹50,000 ICICI MoneySaver round trip. Smaller positions cost more.
- **Universe.** The Desk universe uses adjusted prices for its ₹20 floor (as in `ml_labels`).

## 8. What I'd suggest next (your call)
1. **Probability in the terminal (display only).** P(beat) and P(worst fifth) on every stock window, the WATCH and
   BOOK pages, and a Telegram `/prob TCS` command. Nightly refresh, research label, no trading.
2. **Desk veto: a 12-month paper shadow.** Run momentum + merged veto next to the Desk before any rule change. The
   pre-registered test passed, but the gain is modest.
3. **A 60-session model, the proper way.** Ranked excess label, P(top) / P(bottom) heads, continuous features, the
   purging above. Then test it against this logistic merge.
4. **Short term:** paper-track RSI(2)-leader dips only. No model.
5. **Bulk-buy filter (pending):** the effect it relies on has faded since 2024 in liquid stocks. Leaving it OFF is
   consistent with the data.
