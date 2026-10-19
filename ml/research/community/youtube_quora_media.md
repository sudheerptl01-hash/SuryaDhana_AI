# What the Internet Reports for ML Stock Prediction: Community Evidence (Area B)

**Date:** 2026-10-19 · **From:** community research, area B (YouTube, Quora, Medium/TDS/Substack, LinkedIn, X, Kaggle) · **Companion:** `ml/research/community/youtube_quora_media.json` (41 entries; [n] below is the entry number in that file)

**Credibility mix:** 16 A, 14 B, 11 C.
**Verification:** 24 entries were opened and read. 7 were partly verified: title and channel via YouTube oEmbed, description from search snippets. 10 are "unverified (snippet only)" because the host blocked fetching: Quora, X, most Kaggle pages, and the TDS article pages. Each entry's status is in its `verification` field.

## Summary

1. **Two genres with very different reach.**
   - The hype videos found have 0.59M to 1.36M views each [1][2][3].
   - The most-viewed debunk video found has 150k views [6].
   - Hype figures run from "very high accuracy" [4] through 94.4% "forecasting accuracy" [17], 99% accuracy and R² 0.99 [33][34]. All of them are **price-level** metrics.
2. **Every 90%+ claim we could inspect is a price-level artefact.**
   - An LSTM scores R² 0.89 on a pure random walk [13].
   - A one-day LSTM scores R² 0.988 while being "a sophisticated moving average" [15].
   - Once a naive "tomorrow = today" baseline is added, the LSTM ranks 9th of 14 and the naive forecast is unbeaten [16].
3. **Experienced practitioners quote small numbers:**
   - Hit rates of 50.75% (the Renaissance/Mercer anecdote [28]) and 51.5% (students given the next day's newspaper [41]).
   - IC of 0.04–0.06 as a "real signal", with anything above 0.15 "suspicious" [22].
   - A planning Sharpe of about 0.24 per instrument, and costs capped at one third of pre-cost returns [21].
   - ML factor long-short returns falling from 3.63% to 0.79% a month once realistic constraints are imposed [19].
4. **Forward-tested Kaggle competitions are the most honest public benchmark.**
   - Ubiquant winners reached a Pearson correlation of about 0.12–0.13 using a fund's own engineered features [35].
   - JPX (about 2,000 Japanese stocks, a cross-sectional ranking like ours): the top five scored 0.339–0.381 on a daily Sharpe, pre-cost, over about three months [36]. The scores are so close that rank looks partly luck.
5. **SuryaDhana's numbers sit in the realistic band.** AUC 0.537, rank IC 0.04–0.05 with Newey-West t about 3, and a 52% hit rate are what this community calls a genuine but modest edge. The weak points are the ones practitioners stress most:
   - **Significance:** DSR 0.08.
   - **Cost drag:** by our arithmetic, costs are about 49% of gross active return, above Carver's one-third rule [21].
6. **India.**
   - Indian ML content is dominated by price-level tutorials [2] and index-direction work at about 54–55% [29].
   - **No community source tests delivery %** with data; it is circulated as a heuristic [40].
   - Statutory delivery costs are about 10 bps per side plus 1.5 bps stamp duty on buys [37].
   - SEBI's retail algo framework has applied in full since 2026-04-01: a static IP is mandatory for API users, and strategies above 10 orders/second must be registered [38][39].

## How the evidence was gathered

- **Searches.** WebSearch, standard and extended modes, often restricted to one platform's domain.
- **YouTube.** Titles and channels came from oEmbed. For four videos, the watch-page HTML gave the exact view count, upload date, description and a top comment. YouTube then rate-limited further fetches, so the remaining view counts are "unknown".
- **Medium** article pages are behind Cloudflare. Three articles were read through the author's Medium RSS feed (derived from the search-returned article URL and noted per entry). The TDS pages returned 403.
- **Quora and X** pages cannot be fetched. Their entries use the search-result or page-title text and are marked "unverified (snippet only)". One X thread was read through Thread Reader [27].
- **Kaggle** pages are JavaScript-rendered. Competition scores were confirmed where possible from the exchange's GitHub repository [36].
- **No URL was constructed for citation.** Every URL in the JSON came back from a search or fetch.

---

## 1. The hype genre: typical claims, view counts, and why they are wrong

**What it looks like.** These are YouTube tutorials and blog posts that train an LSTM on one stock's or one index's closing prices. They plot predicted against actual prices, and the two lines overlap.

| Item | Reach | Claim | Credibility |
|---|---:|---|:-:|
| Computer Science (compsci112358), "Stock Price Prediction Using Python & Machine Learning" (2019) [1] | 1,358,627 views | visual near-perfect fit, 60-day window → next day | C |
| Siraj Raval, "How to Predict Stock Prices Easily" (2017) [3] | 667,870 views | "predict the closing price of the S&P 500" | C |
| Krish Naik, "Stock Price Prediction And Forecasting Using Stacked LSTM" (2020) [2] | 588,878 views | price-level forecasting tutorial (Indian educator) | C |
| Tech Know How, "…with Very High Accuracy Using LSTM - Tesla" [4] | unknown | "Very High Accuracy" | C |
| A. Tayyip Saka (Medium, 2021) [17] | unknown | "Average forecasting accuracy of all stocks is 94.4%" (next-day high price, 501 stocks) | C |
| Kaggle: "Nestle … LR - 99% accuracy" [33]; "NVIDIA … 0.99 R2 Score" [34] | unknown | 99% / R² 0.99 | C |
| LinkedIn (Rajasombat, 2021) [30] | unknown | 70.29% direction at a 58-day window, tuned on the same data | C |
| LinkedIn (Khuperkar, 2019) [29] | unknown | ~80% "global indicator" model, but that is **training** accuracy; test results were ~54–55% | B |

**Why the numbers are wrong.** There are five mechanisms, each documented by the community itself.

1. **Price-level metrics reward persistence.**
   - Tomorrow's price is about today's price, so R², MAPE and "1 − percentage error" are near-perfect for any model that copies the last value.
   - Flovik builds an LSTM on a **random walk**. It scores R² 0.89 although "the model might have no predictive power whatsoever" [13]. Its prediction-vs-actual cross-correlation peaks at a one-day lag.
   - Aung Si gets R² 0.98759 and MAE 0.37995 on the DBC ETF from a model that is "producing a sophisticated moving average of the existing time series" [15].
2. **The shifted-by-one illusion (teacher forcing).** Each test-day forecast is fed the true prices up to yesterday, so the chart tracks reality by construction.
   - The top comment on the 1.36M-view video says exactly this: "it's predicting 1 day in the future GIVEN the last 60 days of actual values" [1].
   - Commenters on a popular Kaggle LSTM notebook report the prediction sits one day behind the actual series, and the author acknowledged it [32].
3. **No naive baseline.** When one is added, it wins.
   - "tomorrow's price equals today's price, MAE 11.66 — remained unbeaten", against an LSTM MAE of 14.99 that ranked 9th of 14 [16].
4. **Leakage and in-sample tuning.**
   - Min-max scaling of unbounded prices is flagged in Kaggle comments [32].
   - Window length is tuned on the reporting sample [30].
   - Training accuracy is promoted as the headline [29].
   - A GitHub project returned by our search says most "stock predictor" repositories report 90%+ accuracy and attributes it to shuffled time-series splits (https://github.com/luwymna/stock-predictor; snippet only, not a JSON entry).
5. **Long-horizon direction without a base rate.** A "70% at 40–60 days" result on one rising stock [30] is largely market drift. An always-up rule would score similarly, and none was reported.

**The contrarian version of hype also exists.** For example, "Why 99% of Machine Learning Fail" style titles cite statistics that are themselves unsourced. We recorded none of these as evidence.

## 2. The sober genre: what realistic numbers are quoted

| Source | What they say | Number | Cred. |
|---|---|---|:-:|
| Ernie Chan (Mutiny Fund podcast) [12]; Chat With Traders interview [10] | Direct ML prediction of the market has "low" odds "because of the low signal to noise ratio"; use ML to judge whether a trade will be profitable | — | A |
| Rob Carver, *This Blog is Systematic* (2020) [21] | A fast trend rule's theory-implied Sharpe is 1.68 but its backtested pre-cost Sharpe is 0.07; plan on an expected Sharpe of about **0.24** per instrument; "DO NOT SPEND MORE THAN ONE THIRD OF YOUR EXPECTED PRE-COST RETURNS ON COSTS" | SR 0.24; costs ≤ 1/3 | A |
| *Systematically Biased* Substack (2026), reviewing Esakia & Goltz (2025) [19] | Nonlinear ML long-short falls from **3.63% to 0.79% a month** once microcaps, factor hindsight and costs are handled. Linear vs nonlinear is insignificant on sparse features, and long-only gains shrink further | 0.79%/month | A |
| QuanterLab, IC explainer (2026) [22] | IC 0.04–0.06 = "Real signal"; 0.08–0.12 = strong, rare; > 0.15 = "Suspicious" | IC bands | B |
| Robot Wealth (2021) [20] | "you almost never want to be analyzing asset prices"; "The market is dominated by noise." | — | A |
| TDS (snippet) [18] | A 51.5% next-candle model is "essentially no better than guessing" | 51.5% | B |
| Quantopian, López de Prado, QuantCon 2018 [7]; Hudson & Thames on meta-labeling [8] | Failure modes of financial ML (leakage, overfitting, labelling); ML as a sizing or filter layer | — | A |
| Swedish House of Finance, "Virtue of Complexity" talk [9] | Pro-complexity counterpoint (Kelly, Malamud & Zhou); speaker and numbers not captured from the video | — | B |

**Consensus.** Practitioners expect single-digit-hundredths ICs, hit rates of a point or two above 50%, and Sharpe ratios well below 1 per instrument after costs. They treat anything much better as a reason to look for a bug.

**Searched but not found** (no matching performance content surfaced):

- **Dimitri Bianco:** only a promo short, https://www.youtube.com/shorts/Lh4o1H7RaLc.
- **Part Time Larry:** the channel covers backtesting tooling, not ML results, https://www.youtube.com/c/parttimelarry/videos.
- **QuantPy, Algovibes, Coding Jesus:** nothing matching.
- **Jane Street and Two Sigma talks:** none found.

## 3. Quora consensus

Quora returns HTTP 403, so everything here is snippet-level and anonymous (credibility B at best).

- **Small edges are enough if sized well.** On "70% direction accuracy, can't predict magnitude": "casinos and top poker players amass great profits with the slimmest of predictive margins" [23]. Another answer in the same result set says the best traders are right about 60% of the time.
- **Live underperformance comes from hindsight mining.** "it is quite easy to discover "patterns" in hindsight which either do not really exist or are temporary" [24].
- **Predict returns, not prices; the data are mostly noise.** These snippets appeared in Quora results for "why can't ML predict the stock market", but we could not tie them to a specific thread, so they are not JSON entries:
  - "you should not predict prices, but returns. The problem with prices is that they are non stationary."
  - "there is simply too much noise in stock data."
- **The Mercer "right 50.75 percent of the time" quote** has its own Quora question [28 notes].

**Net.** Quora answerers agree with professionals that roughly 51–55% is the realistic range. They warn that offline results shrink live.

## 4. Kaggle

- **Hype notebooks** advertise their headline in the title: "99% accuracy" [33] and "0.99 R2 Score" [34]. Both are price regressions.
- **Community correction.** The comment threads of popular LSTM notebooks debunk them: the one-day lag, and min-max scaling [32].
- **Competitions are the honest benchmark.** They are forward-tested on data the teams never saw, but they carry no costs and short windows.
  - **Ubiquant Market Prediction (2022) [35]:**
    - Private leaderboard: 1st 0.126987, 2nd 0.123175, 3rd 0.120538 (Pearson correlation).
    - The winner averaged 5-fold LightGBM and TabNet on 300 provided plus 100 engineered features.
    - So even with a quant fund's own features, the best forward correlation is about 0.13. Market and horizon were anonymised.
  - **JPX Tokyo Stock Exchange Prediction (2022) [36]:**
    - Task: rank about 2,000 Japanese stocks daily, scored as the daily Sharpe of the top-200 minus bottom-200 spread over about three live months.
    - Private scores, top five: 0.381, 0.356, 0.352, 0.347, 0.339 (J-Quants GitHub).
    - 0.381 daily is about 6 annualised (×√252, our derivation), before costs and over only about 60 sessions.
    - The tight clustering of the top five suggests luck dominates rank (our inference).

## 5. Practitioner posts on LinkedIn and X

- **The "original sin" frame.** López de Prado (X, 2020) [25]: "The purpose of backtesting is to prove a theory wrong, not to suggest the existence of a theory."
- **The walk-forward critique.** López de Prado (X, 2019) [26]: "A walk-forward backtest is not an experiment, and it does not provide scientific support for a financial theory." He points to combinatorial cross-validation instead. This applies directly to our 43-fold walk-forward.
- **Backtest-error checklists.** @macrocephalopod's "24 days of backtest errors" (Dec 2022) [27] includes look-ahead in signals and "observe a closing price and assume you can trade at that price".
  - SuryaDhana's engine already enters at the t+1 open (`ml/results/strategy/STRATEGY.md`).
- **The thin-edge anchor.** Mercer: "We're right 50.75 percent of the time … You can make billions that way." It is reposted widely, for example [28] and a 2021 post tagged #MachineLearning (https://x.com/mytradesignals/status/1406572848756531201, snippet only).
- **LinkedIn.**
  - A vendor CEO writes "We don't expect to be right all the time, but rather to be more right than wrong" and describes an out-of-sample → costs → live paper portfolio ladder [31].
  - Two Pulse articles show the typical inflation patterns: training accuracy as headline [29] and in-sample window tuning [30].
- **Not found as a citable post.** The "if your backtest shows 90% you have leakage" genre exists mainly as a theme, not as one canonical post.
  - Search summaries mention a LinkedIn checklist post listing "Information Coefficient of 0.03-0.07 (this is genuinely strong)" and a t-stat > 3 bar (Harvey, Liu & Zhu).
  - LinkedIn profile pages return HTTP 999 and no post URL surfaced, so it is **unverified and not entered**.

## 6. India-specific

- **Costs.** Zerodha's equity-delivery schedule [37]:

  | Charge | Rate |
  |---|---|
  | Brokerage | zero |
  | STT | 0.1% on buy & sell |
  | NSE transaction charge | 0.00307% |
  | SEBI fee | ₹10/crore |
  | Stamp duty | 0.015% on buys |
  | GST | 18% on brokerage + SEBI + transaction charges |
  | DP charge | ₹15.34 per scrip on sell |

  - **Statutory total:** about 10.3 bps per side plus 1.5 bps stamp duty on buys (our arithmetic).
  - **What's left in the base case:** SuryaDhana's 20 bps/side leaves about 8–9 bps for spread and impact. That is adequate for the liquid tercile and thin for small caps.
- **SEBI retail algo rules.**
  - The 2025-02-04 circular took effect on 2025-08-01, moved to 2025-10-01 by circular 2025/108 [39], and then followed a glide path to full application on **2026-04-01** [38].
  - API orders are tagged.
  - A static IP is mandatory for every API user ("Regardless of whether you are above or below the 10 orders-per-second threshold, a static IP is mandatory").
  - Strategies above 10 orders/second need broker registration and an exchange-linked audit [38].
  - **Effect on us:** a monthly end-of-day book is far below the threshold. If it is executed via API, it still needs a static IP.
- **Delivery %.** Indian retail content treats it as a "smart money" filter.
  - Typical rule: large caps above 50% are "healthy" and above 60% signal "strong institutional interest", read against the stock's own average.
  - These guides show **no backtest, hit rate or sample size** [40].
  - We found no community or retail source that tests delivery % against forward returns. SuryaDhana's results on delivery features would be among the first systematic public evidence (see also SOTA_FORECASTING.md: no peer-reviewed test found).
- **Indian ML content.**
  - Price-level LSTM tutorials dominate. Krish Naik's has 588,878 views, and a viewer says a teacher assigned it as the starting point [2].
  - There is Nifty direction content [5].
  - A Nifty 50 next-day study reports about 54–55% test accuracy and an 80% training-accuracy headline [29].
  - One Indian channel teaches overfitting control [11].
- **Retail framing from Zerodha's CEO** [41]. In Elm Wealth's "Crystal Ball Challenge", 118 finance students got the next day's front page.
  - They called direction 51.5% of the time.
  - Half lost money, and about 16% went bust.
  - Kamath: "Even if you could predict the future, it wouldn't save you from poor risk management."
  - Secondary reports cite SEBI data that over 90% of retail F&O traders lose money. That figure was not verified here.

## 7. Where SuryaDhana's numbers sit

| Metric | SuryaDhana | Hype genre | Sober / practitioner reference | Reading |
|---|---|---|---|---|
| Directional hit rate | ~52% | 90–99% "accuracy" (price level) [17][33] | 50.75% Medallion anecdote [28]; 51.5% with tomorrow's newspaper [41]; ~54–55% Nifty next-day test [29]; 51.5% "guessing" for one asset [18] | Normal band. With ~2,400 stocks, value comes from breadth, not from the hit rate itself |
| ROC AUC | 0.5366, > 0.5 in 81% of months | not used | rarely quoted in community sources; it is a small-edge number by construction | Consistent with a real, small edge; the monthly consistency is the stronger evidence |
| Rank IC (per date) | 0.04–0.05, NW t ≈ 3 | not used | 0.04–0.06 "real signal", > 0.15 suspicious [22]; Ubiquant forward winners ~0.12–0.13 with proprietary features [35] | Real but modest. About one third of a top Kaggle score achieved with a fund's own features, using price/volume/delivery data only |
| Net active return | +4.2%/yr vs EW, 6-month paper book, 20 bps/side | — | ML long-short 0.79%/month in a realistic setting (~9.5%/yr simple, our arithmetic), with long-only gains smaller [19] | Plausible magnitude for long-only |
| Statistical confidence | DSR 0.08 | — | JPX winners' 3-month scores cluster within 0.04 [36]; walk-forward is one path [26]; hindsight mining [24] | Not yet significant. That is expected for a 6-month window and is the reason for the pre-registered paper book and CPCV/PBO |
| Cost drag | 80% of basket replaced per 20-session tranche | ignored | Carver: costs ≤ 1/3 of pre-cost returns [21] | ~4.0%/yr costs vs ~8.2%/yr gross active ≈ 49% (our arithmetic). Above the rule; reduce turnover (hold longer, add a rank buffer) or trade only the liquid tercile |

**One-line calibration for management.**

- SuryaDhana's predictive numbers are in the range that working quants call genuine but modest. Anyone quoting 90%+ "accuracy" for stocks is measuring price persistence, not prediction.
- What is not yet shown is economic significance after costs, over a long enough live window. That is where the program's effort should go.

## 8. Source list

The JSON holds the full fields. V means verified (opened); P means partly verified (title and channel via oEmbed); S means unverified (snippet only).

1. V, YouTube, Computer Science (compsci112358): https://www.youtube.com/watch?v=QIUxPv5PJOY
2. V, YouTube, Krish Naik: https://www.youtube.com/watch?v=H6du_pfuznE
3. V, YouTube, Siraj Raval: https://www.youtube.com/watch?v=ftMq5ps503w
4. P, YouTube, Tech Know How: https://www.youtube.com/watch?v=LWZueqlFV8c
5. P, YouTube, Angels Healing (Nifty): https://www.youtube.com/watch?v=mmq94I0saOM
6. V, YouTube, CodeTrading: https://www.youtube.com/watch?v=lhrCz6t7rmQ
7. P, YouTube, Quantopian / López de Prado: https://www.youtube.com/watch?v=BRUlSm4gdQ4
8. P, YouTube, Hudson & Thames: https://www.youtube.com/watch?v=ZCFmZFBtqsQ
9. P, YouTube, Swedish House of Finance: https://www.youtube.com/watch?v=MoMm7kSLASI
10. P, YouTube, Chat With Traders / Ernie Chan: https://www.youtube.com/watch?v=DW9zQ8Hz6gQ
11. P, YouTube, Surbhi Verma (India): https://www.youtube.com/watch?v=Zy4nonUVdZk
12. V, Podcast, Mutiny Fund / Ernie Chan: https://mutinyfund.com/ernest-chan-qts-capital-management/
13. V, KDnuggets / TDS, Flovik (2019): https://www.kdnuggets.com/2019/05/machine-learning-time-series-forecasting.html (TDS original, S: https://medium.com/towards-data-science/how-not-to-use-machine-learning-for-time-series-forecasting-avoiding-the-pitfalls-19f9d7adf424)
14. V, KDnuggets / TDS, Flovik (2020): https://www.kdnuggets.com/2020/03/machine-learning-time-series-forecasting-sequel.html
15. V (RSS), Medium, Aung Si: https://medium.com/@aungsi/the-conditional-clairvoyance-of-lstms-in-stock-market-forecasting-8ef001fe2908
16. V (RSS), Medium, Umang Gulati: https://medium.com/@umang.gulati19/the-verdict-what-14-models-taught-me-about-stock-prediction-13217024bac0
17. V (RSS), Medium, A. Tayyip Saka: https://abdullahsaka.medium.com/long-short-term-memory-lstm-model-in-stock-prediction-d0e1c93717b3
18. S, TDS: https://medium.com/towards-data-science/stock-prediction-using-recurrent-neural-networks-c03637437578
19. V, Substack, Systematically Biased: https://systematicallybiased.substack.com/p/what-drives-the-performance-of-machine
20. V, Robot Wealth: https://robotwealth.com/how-to-predict-asset-prices-and-how-not-to/
21. V, Rob Carver: https://qoppac.blogspot.com/2020/04/how-fast-should-we-trade.html
22. V, QuanterLab: https://quanterlab.com/articles/diagnostics-information-coefficient
23. S, Quora (70% direction): https://www.quora.com/If-we-can-predict-the-direction-of-daily-stock-price-movement-w-70-accuracy-consistently-but-can-not-predict-the-magnitude-of-the-movement-is-there-a-good-way-to-ensure-consistent-trading-profits-tried-Kelly-formula
24. S, Quora (offline vs live): https://www.quora.com/Why-do-machine-learning-models-not-perform-well-when-used-in-live-stock-market-prediction-but-on-the-other-hand-perform-very-well-offline
25. S, X, López de Prado: https://twitter.com/lopezdeprado/status/1224732984852520966
26. S, X, López de Prado: https://twitter.com/lopezdeprado/status/1147906139461496832
27. V, X thread via Thread Reader, @macrocephalopod: https://threadreaderapp.com/thread/1599071391973711872.html (series post, S: https://x.com/macrocephalopod/status/1598823745681903616)
28. S, X, Steve Burns (Mercer quote): https://x.com/SJosephBurns/status/1996156631361507421 (Quora question, S: https://www.quora.com/What-did-Bob-Mercen-mean-when-he-said-that-Renaissance-Technologies-were-100-percent-right-50-75-percent-of-the-time-What-is-their-risk-to-reward-ratio)
29. V, LinkedIn, Khuperkar (Nifty 50): https://www.linkedin.com/pulse/how-forecast-stock-index-movement-using-machine-abhijit-khuperkar
30. V, LinkedIn, Rajasombat: https://www.linkedin.com/pulse/using-supervised-machine-learning-models-predict-price-rajasombat
31. V, LinkedIn, Erez Katz: https://www.linkedin.com/pulse/how-validate-alternative-data-stock-forecasting-erez-katz
32. S, Kaggle, faressayah notebook comments: https://www.kaggle.com/code/faressayah/stock-market-analysis-prediction-using-lstm/comments
33. S, Kaggle, Nestle 99%: https://www.kaggle.com/code/mansigaikwad/nestle-stock-price-prediction-lr-99-accuracy
34. S, Kaggle, NVIDIA 0.99 R²: https://www.kaggle.com/code/arnabchaki/nvidia-stock-price-prediction-0-99-r2-score
35. S, Kaggle, Ubiquant: https://www.kaggle.com/competitions/ubiquant-market-prediction/leaderboard (1st-place write-up: https://www.kaggle.com/competitions/ubiquant-market-prediction/writeups/k-i-y-1st-place-solution-our-betting-strategy)
36. V, J-Quants GitHub (JPX winners): https://github.com/J-Quants/JPXTokyoStockExchangePrediction (metric discussion, S: https://www.kaggle.com/competitions/jpx-tokyo-stock-exchange-prediction/discussion/335393)
37. V, Zerodha charges: https://www.zerodha.com/charges
38. V, Zerodha Substack (SEBI algo, April 2026): https://inthemoneybyzerodha.substack.com/p/sebi-algo-trading-changes-april-2026
39. V, Taxmann (SEBI extension): https://www.taxmann.com/post/blog/sebi-extends-deadline-for-retail-algo-trading-framework
40. V, SpikeDesk (delivery %): https://spikedesk.com/blog/delivery-percentage-guide
41. V, BusinessToday (Kamath / Crystal Ball): https://www.businesstoday.in/personal-finance/investment/story/they-saw-the-future-and-blew-their-bets-nithin-kamath-has-a-warning-for-indias-retail-traders-485481-2025-07-21
