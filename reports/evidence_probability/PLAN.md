# Evidence → probability: plan (pre-registered 14 Oct 2026, 18:10 IST, before any number below was computed)

Script: `scripts/evidence_probability_study.py`. Output: `REPORT.md` (tables), `FINDINGS.md` (reading), CSVs.

## Why
Each earlier study measured one idea, each on its own universe, horizon and period, so their numbers cannot be
added up. This study puts every condition the project has tested on **one frame**. Each one becomes a conditional
probability ("given this flag, how likely is the stock to beat the market?"), the flags are merged into one
probability, and the merge is checked out of sample. It also measures which **label** a model should learn from,
for short, swing and long horizons.

## Frame (fixed)
- **Prices:** survivorship-free, split/bonus-adjusted NSE bhavcopy panel from 2010 (`shared/nse_panel.py`).
- **Universe L (primary):** EQ series, raw close ≥ ₹20, 20-session median turnover ≥ ₹5 cr, ≥ 250 sessions of
  history, no ETFs. Point in time.
- **Universe T:** the Decision Desk's top 300 by liquidity (`scripts/ml_label_study.desk_universe`). Used for the
  Desk book test and the ML-score conditions.
- **Signal dates:** the last session of each week, from 2011. Entry at the next open.
- **Outcomes:** h ∈ {5, 20, 60} sessions, next open → open h sessions later, minus the equal-weight mean of the
  universe on the same signal date (`shared/xs_labels.py`).
  - **win** = excess > 0.
  - **bottom / top** = bottom / top quintile of excess within the universe that date.
  - Windows with a > 50% one-day move are dropped (data breaks).
- **Periods:**
  - **P1:** 2011-01 → 2019-09 (prices only; for the 2020–26 price-action studies this decade is unseen).
  - **P2:** 2019-10 → 2023-12 (NSE event data exists).
  - **P3 (holdout):** 2024-01 → end.
  - "Pre" = P1 + P2 where the condition's data exists.
- **Cost:** ICICI MoneySaver round trip at ₹50,000 (`shared/trading_costs.py`).

## Conditions (point in time at the signal close; expected sign from the source study)
| # | Condition | Expected | Source |
|---|---|---|---|
| 1 | Desk momentum score, top decile of L | + | phase_b (ADOPTED) |
| 2 | momentum bottom decile | − | phase_b / ml_labels |
| 3 | close below its 200-day average | − | handbook regime / trend |
| 4 | within 5% of the 52-week high | + | poc_conditional (rejected as modifier) |
| 5 | within 10% of the 52-week low | − | ml_labels (model's skill) |
| 6 | 60-day volatility, top decile | − | ml_labels |
| 7 | 252-day beta, top decile | − | ml_labels |
| 8 | biggest 1-day gain in 20 days, top decile | − | idea_lab (MAX) |
| 9 | Amihud illiquidity, top decile of L | 0 | ml_labels |
| 10 | abnormal volume (5d / 60d), top decile | − | idea_lab |
| 11 | 20-day overnight return, top decile | − | idea_lab (wrong sign found) |
| 12 | delivery surge top decile + 20-day return > 0 | 0 | held_overnight H1 |
| 13 | upside value-area break in the last 5 sessions | − | value_area |
| 14 | the same, on volume ≥ 2× the 20-day median | − | poc_conditional |
| 15 | downside value-area break on volume ≥ 2× | − | poc_conditional |
| 16 | 52-week closing-high breakout on ≥ 1.5× volume, close in the top 40% of the range, last 5 sessions | − | handbook A |
| 17 | burst: day ≥ +4% on higher volume, last 5 sessions | − | handbook E |
| 18 | RSI(2) < 5 above the 200-day average (at the signal close) | + | handbook F |
| 19 | the same in a momentum leader (top 30% of L) | + | handbook F |
| 20 | 5-day return, bottom decile | + | idea_lab (reversal) |
| 21 | 5-day bottom decile on below-normal volume | + | idea_lab (quiet loser) |
| 22 | 20-day return, bottom decile | + | classic 1-month reversal |
| 23 | strong bad results (≤ −5% vs market) in the last 60 sessions | − | results_drift H2 (PASS) |
| 24 | strong good results (≥ +5%) in the last 60 sessions | + | results_drift H1 (FAIL) |
| 25 | any results in the last 20 sessions | 0 | descriptive |
| 26 | split / bonus ex-date in the last 20 sessions | − | idea_lab |
| 27 | non-institutional bulk-deal net buy, last 20 sessions | − | held_overnight H3 / desk_filter |
| 28 | MF / insurer bulk-deal net buy, last 20 sessions | + | held_overnight H3 |
| 29 | non-institutional bulk-deal net sell, last 20 sessions | 0 | held_overnight H3 |
| 30 | fresh insider buy (first in 90 days, ≥ ₹10 lakh, KMP / promoter), last 21 sessions | + | held_overnight H4b |
| 31 | insider open-market sale ≥ ₹10 lakh, last 63 sessions | 0 | held_overnight H4 |
| 32 | F&O long build-up (5-day price > +3%, OI > +10%) | 0 | held_overnight H2 |
| 33 | F&O short build-up (price < −3%, OI > +10%) | 0 | held_overnight H2 |
| 34 | put/call OI ratio, top quintile of F&O stocks | + | ml_labels (untested lead) |
| 35 | within 5% of the 52-week high + MTF growth top decile | − | held_overnight H5 |
| 36 | shareholding accumulation filed in the last 20 sessions | + | held_overnight H6 |
| 37 | ML A2 model score, bottom 30% of T | − | ml_labels §6 (lead) |
| 38 | ML A2 model score, top decile of T | + | ml_labels |

**Coverage:** each condition is compared only with stocks its dataset covers, on the same dates:
- results: symbols with NSE release times;
- insider: symbols with insider records;
- shareholding: its 319 symbols;
- F&O: F&O stocks;
- MTF: from 2022;
- bulk deals: from 2019-10;
- ML scores: universe T.

## Statistics
- Per week: mean excess, win rate and bottom-quintile rate of the flagged stocks, minus the same for all covered
  stocks that week. Verdicts use the weekly series with a Newey-West t (lags 1 / 4 / 12 for h = 5 / 20 / 60).
- **Verdict** (primary h = 20, on mean excess):
  - **Robust:** same sign pre and post, |t| ≥ 2 in both.
  - **Holds (weaker):** same sign, |t| ≥ 2 in one period and ≥ 1 in the other.
  - **Unstable:** opposite signs with |t| ≥ 2 in one.
  - **No effect:** everything else.
- **Credibility:** empirical-Bayes shrinkage across the conditions (normal prior on true effects, variance by
  method of moments). It reports P(the effect has the measured sign). It is also checked as a forecast: predicted
  replication from pre-2024 data vs what 2024+ showed.

## Merge (pre-registered tests)
- **Models, universe L, target = 20-session outcomes:**
  - **A:** momentum percentile only (logistic).
  - **B:** scorecard: naive Bayes log-odds with the shrunk effects.
  - **C:** L2 logistic on all condition flags + coverage flags + momentum percentile.
- **Separate models for P(win) and P(bottom quintile).**
- **Walk-forward:** refit every January.
  - Test years: 2016 → 2026.
  - Training ends 21 sessions before the test year.
  - A dataset joins once it has ≥ 2 years of training data.
- **Universe T:** the same models (plus the ML-score flags) feed the Desk book test.

**Pass rules:**
1. **Ranking:** C beats A on weekly rank IC vs 20-session excess over 2016–2026 (paired NW t ≥ 2), and C ≥ A in
   2024+.
2. **Probability:** C is usable as a probability if its 2024+ calibration slope is within 0.7–1.3 and its Brier
   skill is > 0.
3. **Desk veto:** top-20 momentum book with the Desk's buffer, monthly, net of ICICI costs at ₹25,000 a position,
   vs the universe. The veto rule is: never newly buy a stock in the bottom 30% of C_T's P(win) that date. It
   passes if the veto book beats plain momentum in both 2016–2023 and 2024+, with turnover at most 10% higher.
4. **Decision buckets:** thresholds come from each year's training predictions.
   - BUY = top 10% of P(win).
   - AVOID = top 20% of P(bottom).
   - Reported as realised out-of-sample win rate, mean excess and after-cost return.

## Labels (descriptive, no pass/fail)
- **Horizons:** 5, 10, 20, 60, 120 sessions.
- **Candidate labels:**
  - raw return;
  - excess return;
  - volatility-scaled excess;
  - per-date rank;
  - cost-aware ternary (dead zone ± cost);
  - relative triple barrier (±1·σ√h on the stock-vs-universe line, vertical at h).
- **Measured for each:**
  - market share of variance;
  - share of labels inside the cost dead zone;
  - share of "beat the market" labels that still lose money after costs;
  - week-to-week persistence;
  - rank IC of fixed signals (momentum, reversal, low volatility, 52-week high);
  - net-of-cost momentum decile spread at that holding period.
- Recommendations for short / swing / long labels follow from these measurements.

## What will not change
Trading rules, the Desk and the bulk-buy filter (OFF) stay as they are. Any adoption is the owner's decision after
reading the findings.
