# What Forums Say About ML Stock Prediction: Calibration for SuryaDhana

**Date:** 2026-10-19 · **From:** community-research agent (area A: Reddit and forums) · **Companion:** `ml/research/community/reddit_forums.json` (39 entries)

## Coverage and access limits (read first)

- **Reddit could not be read.**
  - WebSearch rejects `reddit.com` ("not accessible to our user agent"), and WebFetch refuses `old.reddit.com`.
  - I did not route around this through Reddit mirrors or archive snapshots, because the block is Reddit's opt-out of this agent.
  - The two Reddit entries are both `unverified (snippet only)`. One is known through its Hacker News repost; the other only through a search snippet of a mirror page.
- **quant.stackexchange.com and stats.stackexchange.com** have no entries. WebFetch refuses both sites, and WebSearch never returned a page from either.
- **QuantNet and Wilmott** both return HTTP 403 to WebFetch. The two QuantNet entries are snippet-only. No substantive Wilmott thread surfaced, so Wilmott has no entries.
- **Sites read in full:** Hacker News (with intermittent 403s), Elite Trader, the Numerai forum, TradingQnA (Zerodha's community forum), the Kite Connect developer forum, the QuantConnect forum and the pythonprogramming.net community.
  - I added the last five to replace the blocked sources. TradingQnA and the Kite forum are India's largest retail trading and API forums, and stand in for the blocked Indian subreddits.
  - The Numerai forum is the closest public analogue to our task: real-money, out-of-sample, cross-sectional stock ranking.
- **Search budget.** The session-wide limit of 200 WebSearch calls ran out near the end. Three planned searches did not run: Elite Trader hit-rate threads, survivorship-bias threads, and more India ML threads.
- **Quotes** are the text the fetch tool extracted when asked for verbatim wording. Spot-check them against the live page before quoting externally.
- **Grading.** Credibility grades rate the claimed number where there is one. For commentary entries they rate the soundness of the quoted view.

## Executive summary

1. **Forum claims fall into two groups.**
   - High numbers that collapse on inspection. Examples: price-level "near-perfect" fits, 87.6% direction accuracy on a test of about 15 days, and 98% training accuracy produced by label leakage. All are grade C, and the threads themselves name the causes: persistence, leakage and tiny test windows.
   - Small numbers that survive. Good Numerai models show live cross-sectional correlations of 0.015 to 0.025, and practitioners put realistic Sharpe ratios at about 1 to 2 for automated systems.
2. **"Good enough", in practitioners' words.**
   - **Direction:** accuracy only needs to be credibly above 0.50 after costs ("At least you should show >50% correct direction prediction"). Hit rate alone is the wrong test ("You can also lose a lot of money even if you are right 90% of the time").
   - **Ranking:** Numerai participants call correlation "almost noise(corr 0.03 at the best)" and describe 0.03 on validation as "pretty good". An HN commenter says about 5% correlation can be very profitable (the fetch tool's paraphrase).
   - **Sharpe:** "1.0 and 2.0 is probably more realistic for automated trading". But a Sharpe of about 1 held for decades "would be unbelievable and extremely rare".
3. **Reddit lore I could not confirm.** I found no accessible verbatim source for the familiar rules "52 to 53% is good" or "an IC of 0.02 to 0.05 is tradeable with breadth", because Reddit was blocked. The Numerai and HN evidence supports the IC rule.
4. **India.** No forum thread tests delivery % or ML on NSE.
   - Delivery % is used as a screen, with thresholds of above 65%, or above 60% for 5 sessions. A senior TradingQnA contributor dismisses it because BTST trades inflate it.
   - Costs: one TradingQnA backtest went from +7.3% to −2.5% once delivery-side STT was charged.
   - SEBI's retail algo framework, live since 1 April 2026, requires a registered static IP and protected market orders for API trading. Algo registration applies only above an order-rate threshold.
5. **Track record.** Forum minimums range from 6 months of paper trading (folk advice) to "more than 3 years" (allocators). Statistically, a true IR of 1 needs about 4 years to reach t = 2 (our arithmetic).
6. **Where SuryaDhana sits.**
   - AUC 0.537, a hit rate of about 52% and a rank IC of 0.04 to 0.05 (NW t ≈ 3) are all in the credible range.
   - The IC is at the top of what live Numerai models achieve.
   - By every forum standard, the +4.2%/yr paper result is too short to judge. The DSR of 0.08 says the same.

## 1. Distribution of claimed numbers by task

There are 39 entries:
- **By task:** commentary 20, direction 6, ranking 6, return 5, price level 2.
- **By credibility:** A 4, B 16, C 19.
- **By platform:** Hacker News 10, Elite Trader 10, Numerai forum 6, TradingQnA 5, Reddit 2, QuantNet 2, Kite forum 2, QuantConnect 1, pythonprogramming.net 1.

| Task | n | Claimed values (credibility) | Pattern |
|---|---:|---|---|
| Price level | 2 | "near-perfect fit" and "tight-looking fit", no numbers (C, C) | Persistence, plus a scaler fitted before the train/test split. A forecast that repeats the last price does as well. |
| Direction | 6 | 87.6% on about 15 test days (C)<br>over 98% training accuracy after label leakage (C)<br>0.498 accuracy with correlation −0.007 (C)<br>a 75% win-rate filter after more than 1M strategies were tested (C)<br>an ML trade filter that keeps return (146% → 145%) and halves drawdown on one 14-month test (C)<br>no numbers (C) | Every high number has a named defect. The credible direction numbers sit at about 0.50. |
| Return / portfolio | 5 | backtest +7.3% → −2.5% after costs (B)<br>FX Sharpe 0.8–0.9 per strategy, 1.3 for two combined, over 2.6 for four, with estimated costs (C)<br>an LLM "Grok +56% in 8 months" (C)<br>30k → 103k in under a month (C)<br>none (B, QuantNet snippet) | Short records and no risk adjustment. Costs flip small edges. |
| Ranking (Numerai) | 6 | live mean CORR of about 0.018 for the best of 15 staked models (A)<br>Signals live 0.015–0.025 with correlation Sharpe 0.57–1.12 over about 19 rounds (B)<br>feature-neutral live correlation Sharpe above 1 vs about 0.6 for others, over 30 weeks (B)<br>per-round CORR range of about ±0.06 (B)<br>0.03 on validation called "pretty good" (C)<br>validation 0.0717, and an implausible 0.8 (C) | The only set of out-of-sample, real-money ranking numbers. They are small and noisy. |
| Commentary | 20 | Sharpe 1–2 "realistic"; above 3 "super hard"; 30–60 trades a year; 6 months of paper trading; "at most 10%" of papers valid | See sections 2, 3 and 5. |

Two points for management:
- **Numerai is the only comparable out-of-sample source.** No forum entry reports a multi-year walk-forward IC or AUC on equities.
- **The higher the number, the worse the method.** Every claim above 60% direction accuracy, and every Sharpe above 2.5, is grade C with an identified flaw.

## 2. Practitioner consensus on "good enough"

**Direction accuracy**
- **Floor:** credibly above 0.50.
  - "At least you should show >50% correct direction prediction" (chunsj, HN 18415336).
  - "Wouldn't directional accuracy have to be greater than .50 to be profitable?" (jjallen, HN 49172936).
- **Ceiling:** the only figure quoted is "an approach that may yield 58% accuracy" (throwawaywego, HN 20720095). It is hypothetical, not evidence.
- **Hit rate alone is rejected as a measure.** To "If you're right 51% of the time when you invest you're going to get rich", the reply was "You can also lose a lot of money even if you are right 90% of the time" (HN 12001742).
- **The direct question went unanswered.** An Elite Trader poster asked "Should it be 51% or 60, maybe sth different?" and got no reply on that point (ET 320539).
- **Not verified:** I found no verbatim source for the specific rule "52 to 53% is good".

**Correlation / IC (ranking)**
- **Numerai participants treat about 0.03 as the practical ceiling.**
  - "almost noise(corr 0.03 at the best)" (habakan, Numerai 5508).
  - "In my experiemnts it easily pushes the CORR on validation above 0.03, which is pretty good." (nyuton, Numerai 3145)
- **Live numbers are lower.** The best of 15 staked accounts averaged about 0.018 (Numerai 1454), and Signals models ran 0.015 to 0.025 (Numerai 5508).
- **One HN commenter goes higher.** RuiWang0811 (HN 49172936) said about a 5% correlation to future returns can be very profitable, depending on horizon and data. This is the fetch tool's paraphrase.
- **Consistency** is judged by the Sharpe of per-round correlation: about 0.6 for ordinary models, and "significantly above 1" for feature-neutral models over 30 weeks (Numerai 1369).
- **Not verified:** I found no verbatim source for "IC 0.02 to 0.05 is tradeable with breadth", although the numbers above support it.

**Sharpe / information ratio**
- **The Elite Trader rule of thumb:** "A ratio somewhere between 1.0 and 2.0 is probably more realistic for automated trading. ... If you are below 1.0, you might as well just buy and hold the SP500 or NDX." (Businessman, ET 372122 p9)
- **Counterweights:**
  - "A consistent Sharpe above 3 with useful capacity is super hard to achieve." (prophet, ET 372122)
  - A Sharpe of about 1 at index-like risk, sustained over decades, "would be unbelievable and extremely rare" (Actuarial_Fun, ET 372122 p5).
  - On capacity, a Sharpe of 2 is possible on $15K to $150K "But not a $15 Million account." (Businessman, ET 372122 p5)
  - A vendor's own FX backtests put single strategies at 0.8 to 0.9 after estimated costs (ET 333364).
- **Verdict:** the rule "a Sharpe above 1 after costs is rare for retail" is supported in spirit. These posters mostly trade futures and FX on absolute returns.

**Linear vs nonlinear**
- "With this amount of noise, it's generally hard to do much better than a linear regression." (murbard2, HN 14944613)
- A QuantNet snippet says much industry ML is Naive Bayes or linear regression.
- "Generally, systems based on some financial model seem to have still better performance than machine learning systems." (jcl366, ET 300585)

**What an edge is**
- "edge is how far away a strategy's P&L has been from randomness (after all transaction costs are taken into account)" (bd10, ET 337609).
- That is a significance test on net P&L, which is exactly what SuryaDhana's DSR gate is.

## 3. Failure modes

| Failure mode | Forum evidence | SuryaDhana status |
|---|---|---|
| Predicting price levels; the persistence illusion | "You could trivially get better forecasts than this by naively repeating the last-observed price." (HN 18415336)<br>"one-step behind prediction" (HN 16641784) | Does not apply. The label is 20-day relative performance, so the naive baseline is AUC 0.50. |
| Preprocessing leakage (scaler or selector fitted on test data) | "by scaling his single variable before making a test-train split, he's allowed his model to know how the future is distributed." (HN 16641784) | **Applies.** Audit T9 found feature selection on CV test folds. Nesting selection inside each training window is still open (`SOTA_FORECASTING.md`). |
| Label leakage | 98% training accuracy because "the algorithm found out how the label was set" (pythonprogramming.net 280) | Keep a shifted-label placebo test in the audit. |
| Shuffled or random splits of a time series | "split train/test by date, not randomly" (vl, HN 18415336)<br>"You can't just randomly drop out samples in a time series" (bcheung, HN 16641784) | Monthly walk-forward over 43 folds. Check that the purge or embargo is at least the 20-session label horizon. |
| Future information inside the model (bidirectional nets, LLM memorisation) | bidirectional LSTMs leak t+1 (laichzeit0, HN 20720095)<br>"these LLMs have the advantage of foresight over historical data" (sethops1, HN 46154491) | Not an issue today. Relevant if LLM-derived features are added. |
| Tiny test windows and luck | 87.6% on about 15 days (HN 1803505); one 14-month test (ET 312136); 8 months with one run (HN 46154491) | The 43 monthly folds are adequate. The 6-month paper book is the weak link. |
| Multiple testing and correlated samples | "over 1 million strategies" on correlated ETFs (ET 320539)<br>"increased the chances of a chance correlation" (sgt101, HN 20720095) | A DSR gate exists and NW t handles dependence. PBO/CPCV is still open. |
| Costs ignored | "as soon as you add transaction costs it all disappears" (paulpauper, HN 20720095)<br>+7.3% → −2.5% after costs (TradingQnA 46202) | Base case 20 bps/side, stress 40 bps, break-even about 39–41 bps/side (`SOTA_FORECASTING.md`). |
| Alpha decay after publication | scarmig and edwardy20 (HN 20720095, 20723576)<br>about 30–50% a year cited (HN 49172936, paraphrase) | Track IC by calendar year across the 5-year walk-forward. |
| Validation overfit | validation CORR 0.8 with Sharpe 54 (Numerai 419)<br>"I guess it's a big overfit" (Numerai 3145) | Watch the CV-to-holdout IC gap (0.057 → 0.040, `sota_map.json`). |
| Survivorship bias | No accessible forum thread surfaced before the search budget ran out. | Confirm the bhavcopy universe keeps delisted and suspended names. |

## 4. India-specific findings

**Sources.** The Indian subreddits (r/IndianStockMarket, r/IndiaInvestments, r/StockMarketIndia, r/DalalStreetTalks) could not be read. India coverage therefore comes from TradingQnA (5 entries) and the Kite Connect developer forum (2 entries).

**Delivery %: popular as a screen, never tested**
- Mynk1 (2026) screens for delivery above 65% and turnover above Rs 50 crore. There is no backtest; the replies praise convenience only.
- Karthik Rangappa, quoted from 2014, says delivery above 60% sustained for at least 5 sessions is "good", and "Higher the % of deliverable quantity, the more bullish the stock is perceived." (TradingQnA 14122)
- In 2017 the same contributor (posting as Karthik, and pointing users to Zerodha Varsity) wrote: "Frankly, I'd pay little or no attention to this. ... Many may have bought the stock on a BTST basis with an intention of selling at the following day's open." (TradingQnA 12685)
- Another member wrote that "The concept could be very less relevant nowadays" (portfolioplus911, TradingQnA 20535). I read this thread but did not enter it as a row.
- Rising delivery into a falling price is read as bullish by one poster and bearish by another (TradingQnA 14122).

Implications:
- If SuryaDhana's delivery-% result holds, the community has neither replicated nor refuted it.
- The BTST point argues for testing delivery as a change or z-score against each stock's own history, and for checking that it holds in the liquid tercile.

**Costs**
- A Streak backtest of CNC (delivery) trades went from +7.3% to −2.5% after costs. Streak's explanation: "During CNC the brokerage charge is zero but other costs such as STT/CTT is higher because you are taking delivery." (TradingQnA 46202)
- Statutory per-side costs (STT 10 bps, plus stamp duty 1.5 bps on buys) are covered in `SOTA_FORECASTING.md` and not re-derived here.

**SEBI retail algo framework**
- Zerodha's TradingQnA announcement (2026-03-25) sets out the rules:
  - static-IP registration is required by 1 April 2026;
  - market and SL-M orders need market protection, and "Orders placed with market protection set to "0" will be rejected.";
  - limit and SL-limit orders are unchanged.
- On the Kite forum, the answers were "algos need to be registered, not API orders" and, for non-algo API use, "The only change will be the need of a static IP to access broker APIs."
- Implication: an end-of-day book rebalanced every 20 days by API needs a static IP and limit or protected market orders. It is far below the order-rate level that triggers algo registration. Broker notices in search snippets put that level at 10 orders per second per exchange; no forum post confirmed the figure.

**What Indian retail algo traders report**
- Complaints about static-IP overhead and storing API keys in the cloud.
- Surprise at costs.
- No ML performance claims for NSE appeared in any accessible Indian forum thread.

## 5. Track-record rules of thumb

| Rule (source) | Value |
|---|---|
| Paper trading before going live (ET 303819) | 6 months; "a year and some months"; "until your account is doubled" |
| Trades needed (ET 279919) | 30–60 a year for "minimum statistical significance"; "Add another year"; dbphoenix: no fixed number |
| Allocator screen (ET 372122) | "more than 3 years record" at a Sharpe of 2 to 3; one fund reports a "3-year Sharpe ~2" |
| Sustainability (ET 372122 p5) | "how long can you keep that 2 going for." |
| Numerai (1369, 1454) | 30 weeks treated as preliminary ("I would like to repeat this analysis at 52 weeks"); "I didn't have a lot of performance data to use." Context: Numerai's reputation score is a one-year average (docs.numer.ai, from a search snippet). |
| LLM trading test (HN 46154491) | 8 months, one path per model: "By no means is this statistically significant" (the author) |

**Our arithmetic,** using t ≈ IR × √years:
- A true IR of 1.0 needs about 4 years to reach t = 2. An IR of 0.5 needs about 16 years.
- After 6 months, a true IR of 1.0 has an expected t of only about 0.7. A 6-month paper record cannot confirm even a real strategy, which is what SuryaDhana's DSR of 0.08 and IR interval of −2.4 to +4.3 show.
- The forum's minimums (6 months on paper, 30 to 60 trades) are psychological and operational checks, not statistical ones. The allocator figure of 3+ years is the closest to the statistics.

## 6. Where SuryaDhana's numbers sit

| SuryaDhana metric | Our value | Forum band | Reading |
|---|---|---|---|
| ROC AUC (20-day relative label) | 0.5366; above 0.50 in 81% of months | No forum AUCs. Credible direction claims sit just above 0.50; claims of 87–98% come from leakage. | Credible and modest. The month-by-month consistency is the strong part. |
| Directional hit rate | ~52% | Floor "credibly above 50%"; a hypothetical "58%" ceiling; 51% claims dismissed when payoffs are ignored | In range. It is not inflated by market drift, because the label is relative to the universe. |
| Per-date rank IC | 0.04–0.05, NW t ≈ 3 | Numerai live: 0.015–0.025 for good models, 0.03 "at the best"; about 0.05 "very profitable" (HN, paraphrase) | Top of the community range. Plausibly real given India's less efficient, small-cap-heavy universe and a raw, non-neutralised target. Likely to shrink in the liquid tercile and after neutralisation. |
| IC consistency | t ≈ 3 over 43 monthly folds (about 3.6 years), which implies about 1.6 a year (our arithmetic, t/√years) | Numerai per-round correlation Sharpe: 0.57–1.12, above 1 for feature-neutral models (not annualised, so not directly comparable) | Good. Report monthly IC mean and standard deviation in Numerai's format for a like-for-like check. |
| Paper-book active return | +4.2%/yr vs equal-weight, net of 20 bps/side, 6 months (5.5 in STRATEGY.md) | Forum minimum 6 months; allocators want 3+ years; costs flip small edges (TradingQnA) | Promising but statistically silent: DSR 0.08. |
| Sharpe framing | A long-only book, so mostly market beta | "1–2 realistic"; "below 1, buy the index" (ET) | The retail Sharpe yardstick does not apply. Present the information ratio of active returns with its confidence interval. |

**Bottom line.** An experienced forum practitioner would call SuryaDhana's signal "real but small".
- The prediction metrics (AUC, IC, hit rate) are at the honest end of what people report.
- The economic result is unproven until the paper record runs for years.
- No forum source would treat +4.2%/yr over six months as evidence.

## 7. Source list

**F** = fetched and read. **S** = unverified (snippet only). Unless noted otherwise, every URL came from a WebSearch or WebFetch result.

**Reddit (S)**
- https://www.reddit.com/r/algotrading/comments/cr7jey/ive_reproduced_130_research_papers_about/ (URL taken from the HN page)
- https://reddit.fabiomanganiello.com/r/algotrading/comments/1gphasq/is_end_of_2024_quantopian_founded_at_2011_had (search snippet of a third-party mirror; not opened)

**Hacker News (F)**
- https://news.ycombinator.com/item?id=20720095
- https://news.ycombinator.com/item?id=20723576
- https://news.ycombinator.com/item?id=16641784
- https://news.ycombinator.com/item?id=18415336
- https://news.ycombinator.com/item?id=46154491
- https://news.ycombinator.com/item?id=12001742
- https://news.ycombinator.com/item?id=14944613
- https://news.ycombinator.com/item?id=34118677
- https://news.ycombinator.com/item?id=1803505
- https://news.ycombinator.com/item?id=49172936. Disclosure: I built this item URL from the story_id that the HN Algolia API returned, then confirmed it by fetching the page. It is the only URL in the JSON not taken directly from a tool result.
- Read but not entered: https://news.ycombinator.com/item?id=17894664 and https://news.ycombinator.com/item?id=14389280. HTTP 403: https://news.ycombinator.com/item?id=8657839

**Elite Trader (F)**
- https://www.elitetrader.com/et/threads/using-machine-learning-to-improve-systematic-trading.312136/post-4500649
- https://www.elitetrader.com/et/threads/machine-learning-algo-for-trading.300585/post-4293417
- https://www.elitetrader.com/et/threads/targets-on-machine-learning-approach.320539/post-4645059
- https://elitetrader.com/et/threads/sharpe-ratio.372122/post-5896953
- https://elitetrader.com/et/threads/sharpe-ratio.372122/post-5747043
- https://elitetrader.com/et/threads/sharpe-ratio.372122/post-5755570
- https://elitetrader.com/et/threads/how-much-trades-for-validate-a-strategy.279919/post-3908362
- https://www.elitetrader.com/et/threads/paper-trading.303819/post-4349366
- https://elitetrader.com/et/threads/what-is-an-edge.337609/post-4959285
- https://elitetrader.com/et/threads/trade-more-sh-t.333364/
- Read but not entered: https://elitetrader.com/et/threads/automated-trading-faqs.286301/post-4023763

**QuantNet (S; HTTP 403 on fetch)**
- https://quantnet.com/threads/quant-machine-learning-positions.22367
- https://quantnet.com/threads/msc-thesis-random-forest-long-term-return-prediction.43281/post-265500
- HTTP 403, not entered: https://quantnet.com/threads/machine-learning-deep-learning-and-ai-perspectives.30932/post-205892

**Wilmott (HTTP 403; no entries)**
- https://forum.wilmott.com/viewtopic.php?p=610826

**Numerai forum (F)**
- https://forum.numer.ai/t/what-is-a-good-sharpe-ratio-and-validation-correlation/419
- https://forum.numer.ai/t/does-good-model-diagnostics-correlate-with-tournament-performance/1454
- https://forum.numer.ai/t/live-results-on-fn/1369
- https://forum.numer.ai/t/what-is-good-models-for-numerai-signals/5508
- https://forum.numer.ai/t/nn-architecture-for-0-03-corr-on-validation-set/3145
- https://forum.numer.ai/t/relationship-of-daily-round-correlations-to-final-round-correlations/1176
- Read but not entered: https://forum.numer.ai/t/proposal-improving-signals-competition/5218
- Context (official docs, from a search snippet): https://docs.numer.ai/numerai-tournament/scoring

**QuantConnect forum (F)**
- https://www.quantconnect.com/forum/discussion/560/machine-learning-for-equity-price-trend-prediction/
- Read but not entered: https://www.quantconnect.com/forum/discussion/5231/trading-algo-based-on-machine-learning/

**pythonprogramming.net community (F)**
- https://www.pythonprogramming.net/community/280/Stock Prediction Over 90 Percent Accuracy (the URL contains spaces, exactly as returned)

**TradingQnA, Zerodha (F)**
- https://tradingqna.com/t/sharing-daily-nse-bhavcopy-delivery-data-useful-for-swing-traders-07-aug-2026/196866
- https://tradingqna.com/t/how-deliverable-volume-helps-in-ananlysis/12685
- https://tradingqna.com/t/when-stock-deliverable-quantity-is-increasing-and-price-decreasing-what-does-it-mean/14122
- https://tradingqna.com/t/zerodha-streak-brokerage-issue/46202
- https://tradingqna.com/t/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types/192636
- Read but not entered: https://tradingqna.com/t/does-high-delivery-indicate-a-possible-uptrend/20535 and https://tradingqna.com/t/what-does-lower-and-higher-delivery-volumes-of-a-stock-suggests-from-trading-point-of-view/5366

**Kite Connect developer forum (F)**
- https://kite.trade/forum/discussion/14668/new-sebi-rules
- https://kite.trade/forum/discussion/14794/what-would-the-new-sebi-laws-about-algo-trading-mean-for-non-algo-api-access

**Context only (broker notices from search snippets; not forums, not in the JSON):**
- https://www.tradejini.com/blogs/what-sebis-new-algo-trading-rules-mean-for-you
- https://oga-prod.angelone.in/news/market-updates/what-s-changing-in-angel-one-s-smartapi-access-from-april-1-2026

**Blocked or empty:** reddit.com (both tools); quant.stackexchange.com and stats.stackexchange.com (WebFetch refused, no search hits); forum.wilmott.com (HTTP 403, no substantive thread found).
