# How good is good enough? What the internet reports, and where SuryaDhana sits

**Date:** 2026-10-19 · **From:** program lead, synthesising three research streams · **Evidence files (this folder):** `reddit_forums.md/.json` (39 entries), `youtube_quora_media.md/.json` (41 entries), `competitions_platforms.md/.json` (42 entries) · **Program numbers:** `ml/PROGRAM_REPORT.md`, `ml/results/scale5y/SCALE5Y.md` · **Goal ladder:** `ml/GOALS.md`

**Note on numbers.** The three research agents were briefed with the pilot's figures (AUC 0.537, rank IC 0.04 to 0.05, DSR 0.08). This synthesis places SuryaDhana with the final five-year figures: rank IC +0.065 (Newey-West t 6.0), AUC 0.5366 on all features and 0.5359 with nested selection (95% interval [0.5250, 0.5483]), the rank ensemble's +7.0% a year over the equal-weight universe (IR 1.26 [0.32, 2.37]), DSR 0.16 at 177 trials, and 0 of 5 pre-registered gates passed by any single model (1 of 5 by the ensemble).

---

## 1. The answer in one page

**What people online report splits into two genres that barely overlap.**

- **The loud genre** reports 90% to 99% "accuracy". Every such claim the team could inspect is a **price-level fit**: an LSTM predicting tomorrow's price from the last 60 days, scored by R² or percentage error. The three most-viewed stock-prediction tutorials found (1.36 million, 0.67 million and 0.59 million views; the third is by an Indian educator) are all of this kind. Kaggle notebooks advertise "99% accuracy" and "0.99 R²" in their titles. The community itself has done the debunking: an LSTM scores R² 0.89 on a **pure random walk**; a one-day LSTM with R² 0.988 is "a sophisticated moving average"; when a naive "tomorrow equals today" forecast is added to a 14-model comparison it is unbeaten and the LSTM ranks ninth; the top comment on the 1.36-million-view video explains that the model is "predicting 1 day in the future GIVEN the last 60 days of actual values". Direction claims above 60% carry the same defects: 87.6% on about 15 test days, 98% training accuracy from label leakage, 70% at a 40-to-60-day horizon on one rising stock with no base rate.
- **The quiet genre**, written by people who trade or allocate, quotes small numbers and treats big ones as bugs. Renaissance's Robert Mercer: "right 50.75 percent of the time". Man AHL's chief scientist: "slightly more than a coin flip". Finance students handed the next day's newspaper called direction 51.5% of the time, half lost money and 16% went bust. A Nifty next-day model's honest test accuracy was 54 to 55% behind an 80% training-accuracy headline. Practitioners' information-coefficient bands: 0.04 to 0.06 is a "real signal", 0.08 to 0.12 "strong, rare", above 0.15 "suspicious". Live Numerai models achieve correlations of 0.015 to 0.025, with 0.03 "at the best". Retail-forum Sharpe lore: 1 to 2 "realistic for automated trading", above 3 "super hard". Rob Carver plans on a Sharpe of about 0.24 per instrument and caps costs at one third of pre-cost returns. A 2025 academic replication found nonlinear ML long-short returns fall from 3.63% to 0.79% a month once microcaps, factor hindsight and costs are handled.

**What the honest benchmarks say "good" is.**

| Source | What counts as good | Type |
|---|---|---|
| MSCI Barra (2010) | IC 0.05 "good", 0.10 "very good" | industry rule of thumb |
| M6 competition organisers | IC 0.05 moderate, 0.10 good, 0.15 exceptional | live competition design |
| Microsoft Qlib reference LightGBM (CSI300, Alpha158) | IC 0.0448, ICIR 0.366, rank IC 0.0469, 9.0% a year excess, IR 1.02, net of 5/15 bps | open benchmark |
| Numerai | good models: live CORR 0.015 to 0.025; example model's correlation Sharpe 2 on validation; a live participant's 1.32 | real-money tournament |
| Kaggle, live-scored | G-Research crypto winner: live correlation 0.033; Ubiquant winner 0.127 (fund-engineered features, obfuscated target); JPX Tokyo winner: daily Sharpe 0.381 (about 6 annualised, gross) over three months, which is within what luck produces among 2,033 entrants | forward tests, no costs |
| M6 (163 teams, 12 live months) | 28.8% beat the equal-weight portfolio; none did in all 12 months | the closest live analogue to our task |
| Quantopian | keep a factor if mean IC > 0.01 at p < 0.05; "a Q Sharpe of 1 and above is likely a good candidate"; in-sample Sharpe explained out-of-sample Sharpe with R² < 0.025 across 888 algorithms | allocator |
| QuantConnect Alpha Streams | PSR(true Sharpe > 1) > 80%; only 9 of 280 strategies (3.2%) passed; six months live weighted in full | allocator |
| WorldQuant BRAIN (third-party sources) | 5-year Sharpe > 1.25, fitness > 1, daily turnover 1% to 70%; one entrant submitted 28 of 1,103 alphas tried (2.5%) | alpha platform |
| Forums on track record | 6 months of paper trading (folk minimum); "more than 3 years record" (allocators); 30 to 60 trades a year for "minimum statistical significance" | practitioner lore |

**Where SuryaDhana sits.** On **signal quality** it is a good model by every honest yardstick: rank IC 0.065 is above MSCI's "good" line and Qlib's reference LightGBM, its hit rate of about 52% is the band Mercer, Man AHL and the newspaper experiment describe, and its month-to-month consistency (per-month IC mean over sd about 0.9 for the single model and about 1.3 for the ensemble) matches a good live Numerai model. On **proven economics** it is not yet good enough by any allocator's standard: only one pre-registered configuration beats the equal-weight universe net of costs (+7.0% a year, interval clear of zero), that result is the best of 34 trials in its run and 177 in the program, its Deflated Sharpe is 0.16, and its live track record is zero months against a six-month folk minimum, a three-year allocator minimum and about four years for statistical proof at its information ratio. **Verdict: good enough to paper-trade one frozen strategy; not good enough to fund.** That is the same verdict the program's own gates reached (`SCALE_UP.md`), now reached a second way.

---

## 2. The landscape of claims, by genre

### 2.1 The loud genre (all graded C)

| Claim | Where | Reach | What it actually measures |
|---|---|---|---|
| "Near-perfect" LSTM fit of a stock's price | YouTube tutorial, 2019 | 1,358,627 views | next-day price given the last 60 true prices (teacher forcing); persistence |
| "Predict the closing price of the S&P 500 … Easily" | YouTube, 2017 | 667,870 views | price-level fit |
| Stacked-LSTM price forecasting (Indian educator) | YouTube, 2020 | 588,878 views; assigned by teachers | price-level fit |
| "Average forecasting accuracy of all stocks is 94.4%" (501 stocks, next-day high) | Medium, 2021 | unknown | 1 − percentage error on a price level |
| "99% accuracy", "0.99 R²" | Kaggle notebook titles | unknown | linear/LSTM regression of price on lagged price |
| 87.6% direction accuracy from Twitter mood | Hacker News thread on a 2010 paper | | about 15 test days |
| "over 98% accuracy" | pythonprogramming.net | | training accuracy; "the algorithm found out how the label was set" |
| 75% win-rate strategies | Elite Trader | | survivors of "over 1 million strategies" tested on correlated ETFs |
| 70.29% direction at a 58-day window | LinkedIn, 2021 | | window tuned on the reporting sample; one rising stock, no base rate |
| Monthly returns of 30% to 120% | Reddit r/algotrading comment, seen only through a mirror snippet | | unverified anecdote |

**Why these numbers are wrong, in the community's own words.** "You could trivially get better forecasts than this by naively repeating the last-observed price." (Hacker News). "By scaling his single variable before making a test-train split, he's allowed his model to know how the future is distributed." (Hacker News). "Split train/test by date, not randomly." (Hacker News). An LSTM "might have no predictive power whatsoever" and still score R² 0.89 on a random walk (Flovik). A GitHub project returned by search attributes the 90%+ results that dominate "stock predictor" repositories to shuffled time-series splits.

### 2.2 The quiet genre (graded A or B, except the bare Hacker News assertions in the last row, graded C)

| Statement | Source | Number |
|---|---|---|
| "We're right 50.75 percent of the time … You can make billions that way." | Robert Mercer, Renaissance (Zuckerman; Institutional Investor) | 50.75% hit rate |
| "It's slightly more than a coin flip … we seek to have a tiny edge." | Anthony Ledford, Man AHL (IBTimes 2017) | |
| Students with tomorrow's front page called direction 51.5% of the time; half lost money, about 16% went bust | Elm Wealth "Crystal Ball Challenge", via Nithin Kamath (BusinessToday 2025) | 51.5% |
| Nifty 50 next-day direction: 80% training accuracy headline, 54 to 55% on test | LinkedIn Pulse, 2019 | 54 to 55% |
| "IC 0.04 to 0.06 = real signal; 0.08 to 0.12 strong, rare; above 0.15 suspicious" | QuanterLab IC explainer, 2026 | IC bands |
| Live Numerai models: 0.015 to 0.025; "almost noise (corr 0.03 at the best)" | Numerai forum participants | CORR |
| "A ratio somewhere between 1.0 and 2.0 is probably more realistic for automated trading … below 1.0, you might as well just buy and hold" | Elite Trader | Sharpe 1 to 2 |
| "A consistent Sharpe above 3 with useful capacity is super hard to achieve." | Elite Trader | |
| Plan on an expected Sharpe of about 0.24 per instrument; "do not spend more than one third of your expected pre-cost returns on costs" | Rob Carver, 2020 | SR 0.24; costs ≤ 1/3 |
| Nonlinear ML long-short falls from 3.63% to 0.79% a month under realistic constraints; linear vs nonlinear is insignificant on sparse features | Esakia and Goltz (2025), via Systematically Biased | 0.79%/month |
| Direct ML prediction of the market has low odds "because of the low signal to noise ratio"; use ML to judge whether a trade will be profitable | Ernest Chan, QTS Capital | |
| "With this amount of noise, it's generally hard to do much better than a linear regression." | Hacker News | |
| "Edge is how far away a strategy's P&L has been from randomness (after all transaction costs are taken into account)." | Elite Trader | |
| "The purpose of backtesting is to prove a theory wrong"; "A walk-forward backtest is not an experiment" | Marcos López de Prado (X, 2019 and 2020) | |
| "At least you should show >50% correct direction prediction"; "You can also lose a lot of money even if you are right 90% of the time." | Hacker News | |

**Consensus.** Working practitioners expect single-digit-hundredths information coefficients, hit rates a point or two above 50%, Sharpe ratios well below 1 per instrument after costs, and a long record before belief. They treat anything much better as a reason to look for a bug. The rules of thumb often repeated on Reddit ("52 to 53% is good", "an IC of 0.02 to 0.05 is tradeable with breadth") could not be traced to a verbatim source because Reddit blocks this environment (§6); the Numerai, MSCI and Hacker News evidence supports both numerically.

---

## 3. The ladder, and SuryaDhana on it

The competition stream derived a five-rung ladder from the benchmarks above (`competitions_platforms.md` §8); it maps onto the four stages of `ml/GOALS.md`. Hit rates are implied from IC by Sheppard's formula, ½ + arcsin(IC)/π.

| Rung | IC (level, stability) | Implied hit rate | Economics after costs | Track record | SuryaDhana (five-year numbers) |
|---|---|---|---|---|---|
| 0. Noise | < 0.01 or t < 2 | ≤ 50.3% | does not beat equal weight | | above this |
| 1. Real factor: keep researching | 0.01 to 0.03, t ≥ 2 | 50.3 to 51.0% | not yet required | ≥ 3 years of monthly folds | **all single models' long-only books sit here**: real signal, no excess over the universe |
| 2. Good model: paper-trade | about 0.04 to 0.05, per-month mean/sd ≥ 1 | 51.3 to 51.6% | IR about 1 in walk-forward; beats naive baselines | ≥ 6 months live or paper | **the rank ensemble sits here**: IC 0.065 (t 6.0), stability about 1.3, IR 1.26 [0.32, 2.37], beats equal weight and the momentum baseline over 45 months; live record 0 months |
| 3. Allocatable | ≥ 0.05 **after neutralising** momentum, size and sector; stable across sub-universes | ≥ 51.6% | Sharpe ≥ 1.25 over 5 years; PSR(SR > 1) > 80%; DSR ≥ 0.95; fitness > 1 | 5-year walk-forward plus 6 to 12 months live; about 2.6 years live for t = 2 at SR 1.25 | **not reached**: neutralised IC not yet measured (the linear model's score correlates −0.50 with volatility and −0.45 with illiquidity, so part of the raw IC is factor exposure); DSR 0.16; rough fitness 0.94; PSR(SR > 1) below 50% at Sharpe 0.99 |
| 4. Exceptional | ≥ 0.10 (a leakage warning first) | ≥ 53% | fund Sharpe ≥ 2 from breadth | multi-year live | not claimed, and should not be |

**Metric by metric**

| Metric | SuryaDhana (five years) | Honest external band | Reading |
|---|---|---|---|
| Rank IC per date | +0.065, Newey-West t 6.0, positive in 38 of 43 months (nested LightGBM) | MSCI good 0.05; Qlib LightGBM 0.045 to 0.047; QuanterLab "real" 0.04 to 0.06; Numerai live 0.015 to 0.025 on neutralised targets; Kaggle live winners 0.03 (crypto) to 0.13 (fund features) | Above the "good" line on a raw label. Expect it to shrink after factor neutralisation and in the liquid tercile; that measurement is the next step. |
| IC stability | about 0.9 per month (t/√43) for the single model; about 1.3 implied by the ensemble's 91% of months above 0.50 | Numerai live 1.32, validation 2; Qlib daily ICIR 0.37 (a daily label, not comparable in frequency) | At the level of a good live Numerai model; below the validation ideal. |
| AUC | 0.5366 on all features, 0.5359 with nested selection (95% interval [0.5250, 0.5483]), on a 20-session relative label; above 0.50 in 81 to 91% of months | rarely quoted online; credible direction claims sit just above 0.50 | Consistent with a small real edge; the monthly consistency is the stronger evidence. |
| Hit rate | about 52% | Mercer 50.75%; newspaper experiment 51.5%; Nifty next-day 54 to 55%; "58%" quoted only as a hypothetical | In the band working quants call genuine. Value comes from breadth across about 2,400 names, not from the hit rate itself. |
| Net economics | ensemble top decile +7.0% a year over the equal-weight universe, IR 1.26 [0.32, 2.37], 33 of 45 months; single models −0.7% to −3.4% a year | Qlib LightGBM 9.0% a year at IR 1.02 net; M6: top third beat equal weight, none in every month; realistic ML long-short 0.79% a month | One configuration is at the Qlib reference level; the others are not. |
| Cost drag | at 20 bps per side and 70% turnover per 20 sessions, costs are about 3.5% a year against about 10.5% gross active, one third | Carver: costs no more than one third of pre-cost returns | Exactly at the limit. Each extra 10 bps per side costs about 1.8% a year (+8.8% at 10 bps, +3.4% at 40 bps). Turnover reduction is worth more than model work. |
| Significance | PSR 0.99 against zero for the ensemble top decile; DSR 0.163 at N = 177 (0.040 for the liquid paper book) | QuantConnect PSR(SR > 1) > 80%, 3.2% pass; de Prado's example DSR 0.90 at N = 100; JPX winner within luck range | Not significant after multiple-testing adjustment. The historical record cannot fix this; only a frozen live record can. |
| Track record | 0 months live; the historical paper book was used to choose the configuration | folk minimum 6 months; allocators > 3 years; t = 2 at IR 1 needs about 4 years | Below every bar; about 4 years at IR 0.85 to reach PSR 95%. |
| Linear vs nonlinear | logistic mean AUC 0.5415 above LightGBM 0.5366; every paired interval includes zero | "hard to do much better than a linear regression" (HN); Esakia and Goltz: insignificant on sparse features; Qlib: linear 0.0397 vs LightGBM 0.0448 | The program's finding is the community's finding. |

---

## 4. Failure modes the community names, and the program's status

| Failure mode | Community evidence | SuryaDhana |
|---|---|---|
| Predicting price levels; persistence illusion | the entire loud genre; "repeat the last price" beats it | not applicable: the label is 20-session relative return, naive AUC 0.50 |
| Preprocessing or selection fitted on test data | scaler before the split (HN); window tuned in-sample (LinkedIn) | **found and fixed**: the pilot's features were chosen on CV test months (audit T9/T11); the five-year run nests selection inside each training window |
| Label leakage | 98% training accuracy (pythonprogramming.net) | labels recompute exactly; permutation null 0.500 ± 0.001; shifted-feature detector works (+21 sessions gives AUC 0.945) |
| Shuffled or random splits | "split by date, not randomly" (HN) | 43 purged monthly folds, 22-session embargo, exit-date purge |
| Tiny test windows and luck | 87.6% on 15 days; JPX winner within luck range | 43 folds and 913 signal dates; the weak link is the live record (0 months) |
| Multiple testing | "over 1 million strategies"; Quantopian R² < 0.025 | N = 177 fixed before the portfolio numbers; DSR gate; probability-of-backtest-overfitting still open |
| Costs ignored | "as soon as you add transaction costs it all disappears"; Streak backtest +7.3% to −2.5% after costs | 20 bps base, 40 bps stress; costs are one third of gross active return |
| Training-accuracy headlines | Nifty 80% train vs 54% test | only out-of-sample numbers are reported |
| Walk-forward is one path | López de Prado | combinatorial purged CV and PBO are on the open list |
| Validation overfit | Numerai validation CORR 0.8 with Sharpe 54 | CV-to-holdout gaps reported; the holdout was used once |
| Survivorship | no accessible thread | the bhavcopy universe is point-in-time and keeps delisted names (audit T5) |

---

## 5. India-specific findings

- **Delivery percentage is folklore, not evidence.** Retail guides and Zerodha's TradingQnA circulate thresholds (delivery above 65% with turnover above ₹50 crore; above 60% for five sessions is "good"; large caps above 50% "healthy"), always as a screen and never with a backtest, hit rate or sample size. A senior contributor dismissed it in 2017: "Frankly, I'd pay little or no attention to this … Many may have bought the stock on a BTST basis." No peer-reviewed test exists either (`SOTA_FORECASTING.md`). SuryaDhana's five-year result, delivery as the most consistent pillar in a monthly IC of about 0.07, is therefore among the first systematic evidence either way, and it must be treated as unreplicated until the pre-registered delivery validation runs. The BTST objection argues for testing delivery as a change against each stock's own history and inside the liquid tercile.
- **Indian ML content is the loud genre.** The 0.59-million-view stacked-LSTM tutorial is assigned as a starting point by teachers; Nifty next-day direction content reports 54 to 55% on test behind 80% training headlines. No Indian forum thread reports an out-of-sample ML result on NSE stocks.
- **Costs.** Statutory charges on delivery trades are about 10.4 bps per side plus 1.5 bps stamp duty on buys (STT 0.1% each way, exchange and SEBI charges, GST). The program's 20 bps base case leaves 8 to 9 bps for spread and impact: adequate in the liquid tercile, thin for small caps. One Streak backtest went from +7.3% to −2.5% once delivery-side STT was charged.
- **Regulation.** SEBI's retail algorithmic-trading framework has applied in full since 1 April 2026: every API user needs a registered static IP, market orders need market protection, and strategies above 10 orders per second per exchange must be registered through the broker. A monthly end-of-day book executed by API is far below the threshold but still needs the static IP and protected or limit orders. SEBI's own data: 93% of individual F&O traders lost money in FY22 to FY24, and 97% of foreign-investor profits came from algorithmic trading.
- **No Indian retail platform publishes performance norms** (Streak, Tradetron, AlgoTest, QuantMan, uTrade); one vendor claims "45% of users ended the year in profit" without method.

---

## 6. Coverage and limits of this research

- **Reddit could not be read.** Web search rejects reddit.com for this environment's user agent and direct fetches are refused. The two Reddit entries are snippet-only; the familiar r/algotrading and r/quant lore was reached only through Hacker News reposts (for example the "I've reproduced 130 research papers" thread, whose author reports that every paper failed and where a commenter estimates at most 10% would hold up) and substituted forums: Elite Trader, the Numerai forum, QuantConnect, Zerodha's TradingQnA and the Kite Connect developer forum. The Indian subreddits are therefore represented by TradingQnA and Kite, India's largest retail trading and API forums.
- **Quora** returns HTTP 403; its entries are search-snippet only. **X/Twitter** posts were read through search snippets or Thread Reader. **YouTube** search pages are empty; titles and channels came from the oEmbed endpoint and four exact view counts from watch pages before rate limiting. **Kaggle** pages are JavaScript-rendered; competition scores were confirmed from the exchange's GitHub repository where possible and are marked snippet-only otherwise. QuantNet and Wilmott return 403; the Stack Exchange sites refused fetches.
- **Verification marks** in the evidence files: fetched and read, partly verified, or "unverified (snippet only)". Of 122 entries, 34 are graded A, 41 B and 47 C; the C grade is itself a finding, because it marks the claims that do not survive inspection.
- **Agents' search budgets ran out** before three planned searches (Elite Trader hit-rate threads, survivorship-bias threads, more India ML threads).
- **Quotes** are the text the fetch tool extracted; spot-check against the live page before quoting externally.

---

## 7. What this changes in the program

1. **Nothing in the verdict.** The community calibration and the pre-registered gates agree: the signal is real and of the size good practitioners expect; the economics are unproven; paper-trade one frozen strategy; do not fund.
2. **Add two reporting conventions the community uses and we did not:** rank IC after neutralising volatility, size and momentum (Numerai's lesson; also the Stage 3 criterion), and per-month IC mean over sd in Numerai's format, so the stability claim is like-for-like.
3. **Treat turnover as the first economic lever.** Costs sit exactly at Carver's one-third limit; a rank buffer or longer holding period is worth more than another model.
4. **Keep the hype out of the house style.** The program never reports directional accuracy or AUC without the base rate, never reports a price-level metric, and never reports a Sharpe without its trial count. That is what separates the quiet genre from the loud one.
5. **Delivery percentage needs its own pre-registered test** because nobody else has run one.

---

## 8. Sources

The three evidence files hold 122 entries with URLs, verification marks, credibility grades and verbatim quotes: `reddit_forums.json`, `youtube_quora_media.json`, `competitions_platforms.json`. Their narratives (`reddit_forums.md`, `youtube_quora_media.md`, `competitions_platforms.md`) each end with a full source list. Academic references are in `ml/research/SOTA_FORECASTING.md`.
